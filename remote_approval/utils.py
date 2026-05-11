import json
import logging
import os
import subprocess
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Optional, Set


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
APP_LOG_PATH = LOG_DIR / "remote_approval.log"
APPROVAL_HISTORY_PATH = LOG_DIR / "approval_history.jsonl"
APPROVAL_STATE_PATH = LOG_DIR / "approval_state.json"
INTERRUPT_FLAG_PATH = LOG_DIR / "interrupt.flag"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def ensure_log_dir() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def setup_logging() -> logging.Logger:
    ensure_log_dir()
    logger = logging.getLogger("remote_approval")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    file_handler = logging.FileHandler(APP_LOG_PATH, encoding="utf-8")
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    return logger


def load_env(keys: Iterable[str], env_path: Optional[Path] = None) -> Dict[str, str]:
    """Load selected keys from process env and .env without exposing values."""
    wanted = set(keys)
    values = {key: os.environ.get(key, "") for key in wanted}
    path = env_path or PROJECT_ROOT / ".env"
    if not path.exists():
        return values

    with path.open("r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in wanted or values.get(key):
                continue
            values[key] = value.strip().strip('"').strip("'")
    return values


def append_history(record: Dict[str, object]) -> None:
    ensure_log_dir()
    with APPROVAL_HISTORY_PATH.open("a", encoding="utf-8") as history_file:
        history_file.write(json.dumps(record, ensure_ascii=False) + "\n")


def recent_log_summary(max_lines: int = 20) -> str:
    if not APP_LOG_PATH.exists():
        return "No remote approval log entries yet."
    with APP_LOG_PATH.open("r", encoding="utf-8", errors="replace") as log_file:
        lines = log_file.readlines()
    return "".join(lines[-max_lines:]).strip() or "No remote approval log entries yet."


def format_error_trace(error: BaseException) -> str:
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def send_voice_prompt(message: str) -> bool:
    """Try Windows speech, then beep. Never fail the runner for notification errors."""
    powershell = (
        "$text=$env:LOCAL_APPROVAL_VOICE_TEXT; "
        "Add-Type -AssemblyName System.Speech; "
        "$speaker=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
        "$speaker.Speak($text)"
    )
    env = os.environ.copy()
    env["LOCAL_APPROVAL_VOICE_TEXT"] = message
    try:
        completed = subprocess.run(
            ["powershell", "-NoProfile", "-Command", powershell],
            capture_output=True,
            text=True,
            timeout=10,
            shell=False,
            env=env,
        )
        if completed.returncode == 0:
            return True
    except Exception:
        pass

    try:
        import winsound

        winsound.Beep(880, 250)
        return False
    except Exception:
        print(f"[local approval notice] {message}")
        return False


def load_processed_approval_ids() -> Set[str]:
    if not APPROVAL_STATE_PATH.exists():
        return set()
    try:
        with APPROVAL_STATE_PATH.open("r", encoding="utf-8") as state_file:
            data = json.load(state_file)
    except (json.JSONDecodeError, OSError):
        return set()
    processed = data.get("processed_approval_ids", [])
    return {str(item) for item in processed}


def mark_approval_processed(approval_id: str) -> bool:
    """Return False when the approval id was already processed."""
    ensure_log_dir()
    processed = load_processed_approval_ids()
    if approval_id in processed:
        return False
    processed.add(approval_id)
    payload = {"processed_approval_ids": sorted(processed)}
    with APPROVAL_STATE_PATH.open("w", encoding="utf-8") as state_file:
        json.dump(payload, state_file, ensure_ascii=False, indent=2)
        state_file.write("\n")
    return True
