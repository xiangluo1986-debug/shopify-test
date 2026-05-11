import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Optional

from remote_approval.utils import INTERRUPT_FLAG_PATH, recent_log_summary, send_voice_prompt


ALLOWED_REPLIES = {"1", "2", "0", "Y", "N", "P", "STOP", "SHOW_LOG", "SUMMARY"}


@dataclass
class ApprovalConfig:
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    timeout_seconds: int = 3600

    @property
    def has_telegram(self) -> bool:
        return bool(self.telegram_bot_token and self.telegram_chat_id)


@dataclass
class ApprovalReply:
    reply: str
    result: str
    approval_mode: str = "local"
    voice_prompt_sent: bool = False
    interrupt_detected: bool = False
    paused: bool = False


class ApprovalClient:
    def request_approval(self, message: str) -> ApprovalReply:
        raise NotImplementedError


class LocalApprovalClient(ApprovalClient):
    def __init__(self, logger):
        self.logger = logger

    def request_approval(self, message: str, summary: str = "") -> ApprovalReply:
        voice_sent = send_voice_prompt("Approval required. Please check the console.")
        print(message)
        paused = False
        while True:
            try:
                reply = input("Enter Y / N / P / STOP / SHOW_LOG / SUMMARY (legacy: 1 / 2 / 0): ").strip()
            except EOFError:
                return ApprovalReply(reply="0", result="stopped", voice_prompt_sent=voice_sent, paused=paused)
            normalized = _normalize_local_reply(reply)
            if normalized == "SHOW_LOG":
                print("\nRecent log summary:")
                print(recent_log_summary(max_lines=20))
                print()
                continue
            if normalized == "SUMMARY":
                print("\nCurrent task summary:")
                print(summary or "No task summary is available yet.")
                print()
                continue
            if normalized == "P":
                paused = True
                self.logger.info("local approval paused")
                send_voice_prompt("Task paused.")
                if self._pause_loop(summary):
                    continue
                return ApprovalReply(reply="STOP", result="stopped", voice_prompt_sent=voice_sent, paused=paused)
            if normalized in ALLOWED_REPLIES:
                mapped = _map_local_reply(normalized)
                if mapped in {"1", "2"}:
                    return ApprovalReply(reply=mapped, result="approved", voice_prompt_sent=voice_sent, paused=paused)
                if mapped == "0":
                    return ApprovalReply(reply=mapped, result="stopped", voice_prompt_sent=voice_sent, paused=paused)
            print("Invalid option. Only Y / N / P / STOP / SHOW_LOG / SUMMARY / 1 / 2 / 0 is accepted.")

    def handle_interrupt_if_requested(self, summary: str = "") -> Optional[ApprovalReply]:
        if not INTERRUPT_FLAG_PATH.exists():
            return None
        self.logger.info("interrupt flag detected: %s", INTERRUPT_FLAG_PATH)
        voice_sent = send_voice_prompt("Interrupt requested. Task paused.")
        print("\nInterrupt requested. Task paused.")
        print(f"Interrupt flag: {INTERRUPT_FLAG_PATH}")
        while True:
            try:
                reply = input("Enter C to continue and remove interrupt flag, STOP to stop, SHOW_LOG, or SUMMARY: ").strip()
            except EOFError:
                return ApprovalReply(
                    reply="STOP",
                    result="stopped",
                    voice_prompt_sent=voice_sent,
                    interrupt_detected=True,
                    paused=True,
                )
            normalized = reply.upper()
            if normalized == "SHOW_LOG":
                print("\nRecent log summary:")
                print(recent_log_summary(max_lines=20))
                print()
                continue
            if normalized == "SUMMARY":
                print("\nCurrent task summary:")
                print(summary or "No task summary is available yet.")
                print()
                continue
            if normalized == "C":
                try:
                    INTERRUPT_FLAG_PATH.unlink()
                except FileNotFoundError:
                    pass
                self.logger.info("interrupt flag cleared")
                return None
            if normalized == "STOP":
                return ApprovalReply(
                    reply="STOP",
                    result="stopped",
                    voice_prompt_sent=voice_sent,
                    interrupt_detected=True,
                    paused=True,
                )
            print("Invalid option. Only C / STOP / SHOW_LOG / SUMMARY is accepted.")

    def _pause_loop(self, summary: str = "") -> bool:
        print("\nTask paused.")
        print("C = continue")
        print("STOP = stop")
        print("SHOW_LOG = show recent log")
        print("SUMMARY = show current task summary")
        while True:
            try:
                reply = input("Enter C / STOP / SHOW_LOG / SUMMARY: ").strip()
            except EOFError:
                return False
            normalized = reply.upper()
            if normalized == "SHOW_LOG":
                print("\nRecent log summary:")
                print(recent_log_summary(max_lines=20))
                print()
                continue
            if normalized == "SUMMARY":
                print("\nCurrent task summary:")
                print(summary or "No task summary is available yet.")
                print()
                continue
            if normalized == "C":
                self.logger.info("local approval resumed")
                return True
            if normalized == "STOP":
                return False
            print("Invalid option. Only C / STOP / SHOW_LOG / SUMMARY is accepted.")


ConsoleApprovalClient = LocalApprovalClient


class TelegramApprovalClient(ApprovalClient):
    def __init__(self, config: ApprovalConfig, logger):
        self.config = config
        self.logger = logger
        self.api_base = f"https://api.telegram.org/bot{self.config.telegram_bot_token}"
        self.offset = self._initial_offset()

    def request_approval(self, message: str) -> ApprovalReply:
        self._send_message(message)
        deadline = time.time() + self.config.timeout_seconds

        while time.time() < deadline:
            reply = self._poll_reply()
            if reply == "SHOW_LOG":
                self._send_message("Recent log summary:\n" + recent_log_summary(max_lines=20))
                continue
            if reply in {"1", "2", "0"}:
                return ApprovalReply(reply=reply, result="approved" if reply in {"1", "2"} else "stopped", approval_mode="telegram")
            if reply:
                self._send_message("Invalid option. Only 1 / 2 / 0 / SHOW_LOG is accepted.")
            time.sleep(3)

        self.logger.info("approval timed out")
        try:
            self._send_message("approval timed out, task stopped")
        except Exception:
            self.logger.error("failed to send telegram timeout notice without logging token details")
        return ApprovalReply(reply="TIMEOUT", result="timed_out", approval_mode="telegram")

    def _initial_offset(self) -> Optional[int]:
        updates = self._api_get("getUpdates", {"timeout": 1})
        results = updates.get("result", [])
        if not results:
            return None
        return max(update["update_id"] for update in results) + 1

    def _poll_reply(self) -> Optional[str]:
        params = {"timeout": 20}
        if self.offset is not None:
            params["offset"] = self.offset
        updates = self._api_get("getUpdates", params)
        for update in updates.get("result", []):
            self.offset = update["update_id"] + 1
            message = update.get("message") or {}
            chat = message.get("chat") or {}
            if str(chat.get("id")) != str(self.config.telegram_chat_id):
                continue
            text = str(message.get("text", "")).strip()
            normalized = text.upper() if text.upper() == "SHOW_LOG" else text
            if normalized in ALLOWED_REPLIES:
                self.logger.info("user reply received via telegram: %s", normalized)
                return normalized
            self.logger.info("invalid telegram reply ignored")
            return "INVALID"
        return None

    def _send_message(self, text: str) -> None:
        self._api_get("sendMessage", {"chat_id": self.config.telegram_chat_id, "text": text})

    def _api_get(self, method: str, params: dict) -> dict:
        query = urllib.parse.urlencode(params)
        url = f"{self.api_base}/{method}?{query}"
        with urllib.request.urlopen(url, timeout=30) as response:
            payload = response.read().decode("utf-8")
        data = json.loads(payload)
        if not data.get("ok"):
            raise RuntimeError(f"Telegram API call failed: {method}")
        return data


def _normalize_local_reply(reply: str) -> str:
    normalized = (reply or "").strip().upper()
    if normalized in {"Y", "N", "P", "STOP", "SHOW_LOG", "SUMMARY"}:
        return normalized
    return (reply or "").strip()


def _map_local_reply(reply: str) -> str:
    if reply == "Y":
        return "1"
    if reply in {"N", "STOP"}:
        return "0"
    return reply
