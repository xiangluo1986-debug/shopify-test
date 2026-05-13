import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_one_draft_send_execute"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_one_draft_send_execute"

SOURCE_PREFLIGHT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight.json"
SOURCE_PREFLIGHT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight.html"
PROTECTED_DRAFT_SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPEAT_CUSTOMER_GUARD_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_repeat_customer_guard.json"
RETURNED_PACKAGE_GUARD_JSON_PATH = LOG_DIR / "shopify_review_request_returned_package_guard.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.html"

DRY_RUN_STATUS = "dry_run_real_send_not_executed"
SENT_STATUS = "one_gmail_draft_sent_and_needs_send_audit"
EXPECTED_PREFLIGHT_STATUS = "trustpilot_gmail_one_draft_send_final_preflight_ready"
EXPECTED_REPEAT_CUSTOMER_GUARD_STATUS = "repeat_customer_guard_passed"
EXPECTED_RETURNED_PACKAGE_GUARD_STATUS = "returned_package_guard_passed"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
SEND_DRAFT_ENV = "TRUSTPILOT_GMAIL_SEND_DRAFT"
SEND_DRAFT_MAX_ENV = "TRUSTPILOT_GMAIL_SEND_DRAFT_MAX"
SEND_DRAFT_ACK_ENV = "TRUSTPILOT_GMAIL_SEND_DRAFT_ACK"
SEND_DRAFT_ACK_VALUE = "YES_I_APPROVE_SENDING_ONE_TRUSTPILOT_GMAIL_DRAFT"
DRY_RUN_ENV = "DRY_RUN"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND_FROM = "info@kidstoylover.com"
ALLOWED_REPORT_EMAILS = {GMAIL_SEND_FROM.lower()}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"shpat_[A-Za-z0-9_]+"),
    re.compile(r"(?i)access[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)refresh[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)client[_\s-]?secret\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
]


def run_shopify_review_request_trustpilot_gmail_one_draft_send_execute_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_preflight, source_error = _read_source_preflight()
    source_privacy_scan = {
        "json": _privacy_scan_text(_read_text(SOURCE_PREFLIGHT_JSON_PATH)),
        "html": _privacy_scan_text(_read_text(SOURCE_PREFLIGHT_HTML_PATH)),
    }
    gates = _gate_status()
    blocking_conditions = _blocking_conditions(source_preflight, source_error, source_privacy_scan, gates)
    send_result = _send_result(source_preflight, gates, blocking_conditions)
    status = send_result["one_draft_send_execute_status"]
    payload = _build_payload(
        source_preflight=source_preflight,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        gates=gates,
        blocking_conditions=blocking_conditions,
        send_result=send_result,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_preflight() -> tuple[dict, str]:
    if not SOURCE_PREFLIGHT_JSON_PATH.exists():
        return {}, "blocked_missing_final_preflight_report"
    try:
        return json.loads(SOURCE_PREFLIGHT_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_missing_final_preflight_report: source JSON parse failed: {exc}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _read_repeat_customer_guard_report() -> tuple[dict, str]:
    if not REPEAT_CUSTOMER_GUARD_JSON_PATH.exists():
        return {}, "blocked_repeat_customer_guard_missing"
    try:
        return json.loads(REPEAT_CUSTOMER_GUARD_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_repeat_customer_guard_missing: guard JSON parse failed: {exc}")


def _read_returned_package_guard_report() -> tuple[dict, str]:
    if not RETURNED_PACKAGE_GUARD_JSON_PATH.exists():
        return {}, "blocked_returned_package_guard_missing"
    try:
        return json.loads(RETURNED_PACKAGE_GUARD_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_returned_package_guard_missing: guard JSON parse failed: {exc}")


def _gate_status() -> dict:
    requested_send_enabled = os.environ.get(SEND_DRAFT_ENV, "").strip() == "1"
    requested_send_max = os.environ.get(SEND_DRAFT_MAX_ENV, "").strip()
    ack_raw = os.environ.get(SEND_DRAFT_ACK_ENV, "").strip()
    dry_run_raw = os.environ.get(DRY_RUN_ENV, "").strip()
    dry_run = dry_run_raw != "0"
    ack_present = bool(ack_raw)
    ack_valid = ack_raw == SEND_DRAFT_ACK_VALUE
    return {
        "requested_send_enabled": requested_send_enabled,
        "requested_send_max": requested_send_max,
        "send_max_is_one": requested_send_max == "1",
        "ack_present": ack_present,
        "ack_valid": ack_valid,
        "dry_run_raw": dry_run_raw or "1",
        "dry_run": dry_run,
        "real_send_allowed": requested_send_enabled and requested_send_max == "1" and ack_valid and not dry_run,
    }


def _blocking_conditions(source_preflight: dict, source_error: str, source_privacy_scan: dict, gates: dict) -> list[dict]:
    conditions = []
    if source_error:
        return [{"status": "blocked_missing_final_preflight_report", "detail": _sanitize_text(source_error)}]
    if source_preflight.get("final_preflight_status") != EXPECTED_PREFLIGHT_STATUS or source_preflight.get("success") is not True:
        conditions.append({"status": "blocked_final_preflight_not_ready", "detail": "Phase 3.15 final preflight is not ready"})
    if source_preflight.get("ready_for_manual_real_send_approval") is not True:
        conditions.append(
            {
                "status": "blocked_not_ready_for_manual_real_send_approval",
                "detail": "source ready_for_manual_real_send_approval is not true",
            }
        )
    if source_preflight.get("selected_order_name") != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_final_preflight_not_ready", "detail": "selected_order_name mismatch"})
    if source_preflight.get("selected_masked_email") != EXPECTED_MASKED_EMAIL:
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected_masked_email mismatch"})
    if source_preflight.get("source_gmail_draft_id_partial") != EXPECTED_DRAFT_ID_PARTIAL:
        conditions.append({"status": "blocked_missing_draft_id_for_send", "detail": "source_gmail_draft_id_partial mismatch"})
    if _privacy_scan_failed(source_privacy_scan):
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source preflight JSON/HTML privacy scan failed"})
    if not _is_masked_email(source_preflight.get("selected_masked_email", "")):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected_masked_email is missing or not masked"})
    if any(source_preflight.get(flag) is True for flag in ("shopify_write_performed", "mutation_performed")):
        conditions.append({"status": "blocked_unexpected_shopify_write_flag", "detail": "source Shopify write/mutation flag was true"})
    if any(source_preflight.get(flag) is True for flag in ("tags_add_performed", "tags_remove_performed", "tagsAdd_performed", "tagsRemove_performed")):
        conditions.append({"status": "blocked_unexpected_tag_write_flag", "detail": "source tag write flag was true"})
    if any(source_preflight.get(flag) is True for flag in ("kudosi_api_call_performed", "ali_reviews_api_call_performed")):
        conditions.append({"status": "blocked_unexpected_kudosi_flag", "detail": "source Kudosi/Ali Reviews flag was true"})
    if source_preflight.get("blocking_condition_count") not in (0, None):
        conditions.append({"status": "blocked_final_preflight_not_ready", "detail": "source preflight has blocking conditions"})

    if gates["requested_send_max"] and not gates["send_max_is_one"]:
        conditions.append({"status": "blocked_send_max_not_one", "detail": "TRUSTPILOT_GMAIL_SEND_DRAFT_MAX must be 1"})
    if gates["ack_present"] and not gates["ack_valid"]:
        conditions.append({"status": "blocked_invalid_send_ack", "detail": "TRUSTPILOT_GMAIL_SEND_DRAFT_ACK is invalid"})
    if not gates["dry_run"]:
        repeat_guard_condition = _repeat_customer_guard_blocking_condition()
        if repeat_guard_condition:
            conditions.append(repeat_guard_condition)
        returned_guard_condition = _returned_package_guard_blocking_condition()
        if returned_guard_condition:
            conditions.append(returned_guard_condition)
        if not gates["requested_send_enabled"]:
            conditions.append({"status": "blocked_missing_send_enabled", "detail": "TRUSTPILOT_GMAIL_SEND_DRAFT is not 1"})
        if not gates["requested_send_max"]:
            conditions.append({"status": "blocked_send_max_not_one", "detail": "TRUSTPILOT_GMAIL_SEND_DRAFT_MAX is missing"})
        if not gates["ack_present"]:
            conditions.append({"status": "blocked_missing_send_ack", "detail": "TRUSTPILOT_GMAIL_SEND_DRAFT_ACK is missing"})
    return conditions


def _repeat_customer_guard_blocking_condition() -> dict:
    guard_report, guard_error = _read_repeat_customer_guard_report()
    if guard_error:
        return {"status": "blocked_repeat_customer_guard_missing", "detail": guard_error}
    guard_status = guard_report.get("repeat_customer_guard_status")
    if guard_status != EXPECTED_REPEAT_CUSTOMER_GUARD_STATUS:
        if guard_status == "blocked_first_order_customer" or guard_report.get("first_order_customer") is True:
            return {
                "status": "blocked_first_order_customer",
                "detail": "Repeat-customer guard indicates this is a first-order customer.",
            }
        return {
            "status": "blocked_repeat_customer_guard_not_passed",
            "detail": "Repeat-customer guard did not pass.",
        }
    if guard_report.get("repeat_customer_confirmed") is not True:
        return {
            "status": "blocked_repeat_customer_guard_not_passed",
            "detail": "Repeat-customer guard did not confirm repeat customer.",
        }
    if guard_report.get("future_trustpilot_send_allowed") is not True:
        return {
            "status": "blocked_repeat_customer_guard_not_passed",
            "detail": "Repeat-customer guard does not allow future Trustpilot send.",
        }
    return {}


def _returned_package_guard_blocking_condition() -> dict:
    guard_report, guard_error = _read_returned_package_guard_report()
    if guard_error:
        return {"status": "blocked_returned_package_guard_missing", "detail": guard_error}
    guard_status = guard_report.get("return_guard_status")
    if guard_status == "blocked_returned_package_tag_detected" or guard_report.get("return_tag_detected") is True:
        return {
            "status": "blocked_returned_package_tag_detected",
            "detail": "Returned package guard detected a return/returned tag.",
        }
    if guard_status != EXPECTED_RETURNED_PACKAGE_GUARD_STATUS:
        return {
            "status": "blocked_return_guard_not_passed",
            "detail": "Returned package guard did not pass.",
        }
    if guard_report.get("review_request_allowed") is not True or guard_report.get("trustpilot_send_allowed") is not True:
        return {
            "status": "blocked_return_guard_not_passed",
            "detail": "Returned package guard does not allow review request or Trustpilot send.",
        }
    return {}


def _send_result(source_preflight: dict, gates: dict, blocking_conditions: list[dict]) -> dict:
    result = {
        "one_draft_send_execute_status": DRY_RUN_STATUS if not blocking_conditions else blocking_conditions[0]["status"],
        "mode": "dry-run" if gates["dry_run"] else "real-run",
        "gmail_api_call_performed": False,
        "gmail_draft_send_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "sent_count": 0,
        "gmail_error_sanitized": "",
        "gmail_send_response_id_partial": "",
    }
    if blocking_conditions:
        return result
    if gates["dry_run"]:
        return result

    real_result = _send_one_gmail_draft(source_preflight)
    result.update(real_result)
    return result


def _send_one_gmail_draft(source_preflight: dict) -> dict:
    result = {
        "one_draft_send_execute_status": "blocked_missing_draft_id_for_send",
        "mode": "real-run",
        "gmail_api_call_performed": False,
        "gmail_draft_send_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "sent_count": 0,
        "gmail_error_sanitized": "",
        "gmail_send_response_id_partial": "",
    }
    draft_id = _protected_runtime_draft_id(source_preflight)
    if not draft_id:
        return result
    gmail_env = _gmail_env()
    if not gmail_env["gmail_oauth_present"]:
        result["one_draft_send_execute_status"] = "blocked_missing_gmail_oauth"
        result["gmail_error_sanitized"] = "Gmail OAuth environment is missing."
        return result
    if GMAIL_COMPOSE_SCOPE not in gmail_env["scopes"]:
        result["one_draft_send_execute_status"] = "blocked_missing_gmail_compose_scope"
        result["gmail_error_sanitized"] = "Gmail compose scope is not configured."
        return result

    try:
        service = _build_gmail_service(gmail_env, result)
        result["gmail_draft_send_attempted"] = True
        result["gmail_drafts_send_called"] = True
        result["gmail_api_call_performed"] = True
        response = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
        result["one_draft_send_execute_status"] = SENT_STATUS
        result["gmail_send_performed"] = True
        result["email_sent"] = True
        result["sent_count"] = 1
        result["gmail_send_response_id_partial"] = _partial_id(response.get("id", ""))
    except Exception as exc:  # pragma: no cover - real send is not exercised in dry-run validation.
        result["one_draft_send_execute_status"] = "blocked_gmail_draft_send_failed"
        result["gmail_error_sanitized"] = _sanitize_text(str(exc))
        result["gmail_send_performed"] = False
        result["email_sent"] = False
        result["sent_count"] = 0
    return result


def _protected_runtime_draft_id(source_preflight: dict) -> str:
    if not PROTECTED_DRAFT_SOURCE_JSON_PATH.exists():
        return ""
    try:
        source = json.loads(PROTECTED_DRAFT_SOURCE_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return ""
    draft_id = str(source.get("gmail_draft_id") or "").strip()
    if not draft_id:
        return ""
    if _partial_id(draft_id) != source_preflight.get("source_gmail_draft_id_partial"):
        return ""
    return draft_id


def _gmail_env() -> dict:
    dotenv_values = _read_dotenv_values()
    send_from = _env_value("GMAIL_SEND_FROM", dotenv_values)
    client_id = _env_value("GOOGLE_GMAIL_CLIENT_ID", dotenv_values)
    client_secret = _env_value("GOOGLE_GMAIL_CLIENT_SECRET", dotenv_values)
    refresh_token = _env_value("GOOGLE_GMAIL_REFRESH_TOKEN", dotenv_values)
    scopes = _split_scopes(_env_value("GOOGLE_GMAIL_SCOPES", dotenv_values))
    missing = []
    if send_from != GMAIL_SEND_FROM:
        missing.append("GMAIL_SEND_FROM")
    if not client_id:
        missing.append("GOOGLE_GMAIL_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_GMAIL_CLIENT_SECRET")
    if not refresh_token:
        missing.append("GOOGLE_GMAIL_REFRESH_TOKEN")
    if not scopes:
        missing.append("GOOGLE_GMAIL_SCOPES")
    return {
        "send_from": send_from,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "scopes": scopes,
        "gmail_oauth_present": not missing,
    }


def _read_dotenv_values() -> dict:
    dotenv_path = Path.cwd() / ".env"
    values = {}
    if not dotenv_path.exists():
        return values
    allowed = {
        "GMAIL_SEND_FROM",
        "GOOGLE_GMAIL_CLIENT_ID",
        "GOOGLE_GMAIL_CLIENT_SECRET",
        "GOOGLE_GMAIL_REFRESH_TOKEN",
        "GOOGLE_GMAIL_SCOPES",
    }
    for line in dotenv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in allowed:
            values[key] = value.strip().strip("\"'")
    return values


def _env_value(key: str, dotenv_values: dict) -> str:
    return (os.environ.get(key) or dotenv_values.get(key) or "").strip()


def _split_scopes(value: str) -> list[str]:
    return [item.strip() for item in value.split() if item.strip()]


def _build_gmail_service(gmail_env: dict, result: dict):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=gmail_env["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=gmail_env["client_id"],
        client_secret=gmail_env["client_secret"],
        scopes=gmail_env["scopes"],
    )
    result["gmail_api_call_performed"] = True
    credentials.refresh(Request())
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _build_payload(
    source_preflight: dict,
    source_error: str,
    source_privacy_scan: dict,
    gates: dict,
    blocking_conditions: list[dict],
    send_result: dict,
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary(send_result)
    repeat_guard_report, repeat_guard_error = _read_repeat_customer_guard_report()
    return_guard_report, return_guard_error = _read_returned_package_guard_report()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.16",
        "mode": send_result["mode"],
        "command_label": COMMAND_LABEL,
        "one_draft_send_execute_status": status,
        "success": status in {DRY_RUN_STATUS, SENT_STATUS},
        "source_final_preflight_status": _safe_text(source_preflight.get("final_preflight_status", "")),
        "source_report_used": {
            "json_path": str(SOURCE_PREFLIGHT_JSON_PATH),
            "html_path": str(SOURCE_PREFLIGHT_HTML_PATH),
            "json_exists": SOURCE_PREFLIGHT_JSON_PATH.exists(),
            "html_exists": SOURCE_PREFLIGHT_HTML_PATH.exists(),
            "source_error_sanitized": _sanitize_text(source_error),
        },
        "selected_order_name": _safe_text(source_preflight.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_preflight.get("selected_masked_email", "")),
        "source_gmail_draft_id_partial": _safe_text(source_preflight.get("source_gmail_draft_id_partial", "")),
        "repeat_customer_guard_status": _safe_text(repeat_guard_report.get("repeat_customer_guard_status", "")),
        "repeat_customer_guard_report_present": not bool(repeat_guard_error),
        "repeat_customer_confirmed": repeat_guard_report.get("repeat_customer_confirmed") is True,
        "future_trustpilot_send_allowed": repeat_guard_report.get("future_trustpilot_send_allowed") is True,
        "repeat_customer_guard_error_sanitized": _sanitize_text(repeat_guard_error),
        "return_guard_status": _safe_text(return_guard_report.get("return_guard_status", "")),
        "return_guard_report_present": not bool(return_guard_error),
        "return_tag_detected": return_guard_report.get("return_tag_detected") is True,
        "review_request_allowed_by_return_guard": return_guard_report.get("review_request_allowed") is True,
        "trustpilot_send_allowed_by_return_guard": return_guard_report.get("trustpilot_send_allowed") is True,
        "return_guard_error_sanitized": _sanitize_text(return_guard_error),
        "requested_send_enabled": gates["requested_send_enabled"],
        "requested_send_max": gates["requested_send_max"],
        "ack_valid": gates["ack_valid"],
        "ack_present": gates["ack_present"],
        "dry_run": gates["dry_run"],
        "real_send_allowed": gates["real_send_allowed"] and not blocking_conditions,
        "future_send_audit_required": True,
        "send_audit_required_next": status == SENT_STATUS,
        "future_tag_write_requires_separate_phase": True,
        "shopify_tag_write_allowed_now": False,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "source_privacy_scan": source_privacy_scan,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_gmail_one_draft_send_execute_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_one_draft_send_execute_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        **send_result,
        "safety_summary": safety,
        **safety,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary(send_result: dict) -> dict:
    return {
        "gmail_api_call_performed": bool(send_result["gmail_api_call_performed"]),
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_send_attempted": bool(send_result["gmail_draft_send_attempted"]),
        "gmail_drafts_send_called": bool(send_result["gmail_drafts_send_called"]),
        "gmail_messages_send_called": False,
        "gmail_send_performed": bool(send_result["gmail_send_performed"]),
        "email_sent": bool(send_result["email_sent"]),
        "sent_count": int(send_result["sent_count"]),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_one_draft_send_execute_path": str(json_path),
        "html_trustpilot_gmail_one_draft_send_execute_path": str(html_path),
        "one_draft_send_execute_status": payload["one_draft_send_execute_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "repeat_customer_guard_status": payload["repeat_customer_guard_status"],
        "repeat_customer_confirmed": payload["repeat_customer_confirmed"],
        "future_trustpilot_send_allowed": payload["future_trustpilot_send_allowed"],
        "return_guard_status": payload["return_guard_status"],
        "return_tag_detected": payload["return_tag_detected"],
        "review_request_allowed_by_return_guard": payload["review_request_allowed_by_return_guard"],
        "trustpilot_send_allowed_by_return_guard": payload["trustpilot_send_allowed_by_return_guard"],
        "requested_send_enabled": payload["requested_send_enabled"],
        "requested_send_max": payload["requested_send_max"],
        "ack_valid": payload["ack_valid"],
        "dry_run": payload["dry_run"],
        "real_send_allowed": payload["real_send_allowed"],
        "sent_count": payload["sent_count"],
        "blocking_condition_count": payload["blocking_condition_count"],
        "blocking_conditions": payload["blocking_conditions"],
        **payload["safety_summary"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    blocking_rows = "\n".join(
        f"<tr><td>{escape(item.get('status', ''))}</td><td>{escape(item.get('detail', ''))}</td></tr>"
        for item in payload["blocking_conditions"]
    ) or "<tr><td colspan=\"2\">None</td></tr>"
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail One-Draft Send Execute</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Gmail One-Draft Send Execute</h1>
  <p class="warning">Phase 3.16 is locked to at most one Gmail drafts.send. Shopify tag write remains disabled and reserved for a separate phase.</p>
  <p>Status: <strong>{escape(payload["one_draft_send_execute_status"])}</strong></p>
  <p>Mode: <code>{escape(payload["mode"])}</code></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Repeat-customer guard status: <code>{escape(payload["repeat_customer_guard_status"])}</code></p>
  <p>Repeat customer confirmed: <strong>{escape(str(payload["repeat_customer_confirmed"]))}</strong></p>
  <p>Future Trustpilot send allowed: <strong>{escape(str(payload["future_trustpilot_send_allowed"]))}</strong></p>
  <p>Returned package guard status: <code>{escape(payload["return_guard_status"])}</code></p>
  <p>Return tag detected: <strong>{escape(str(payload["return_tag_detected"]))}</strong></p>
  <p>Trustpilot send allowed by return guard: <strong>{escape(str(payload["trustpilot_send_allowed_by_return_guard"]))}</strong></p>
  <p>Dry-run: <strong>{escape(str(payload["dry_run"]))}</strong></p>
  <p>Real send allowed: <strong>{escape(str(payload["real_send_allowed"]))}</strong></p>
  <p>Sent count: <strong>{escape(str(payload["sent_count"]))}</strong></p>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _privacy_scan_text(text: str) -> dict:
    raw_customer_emails = []
    for match in EMAIL_RE.finditer(text or ""):
        email = match.group(0).lower()
        if email in ALLOWED_REPORT_EMAILS or "***" in email:
            continue
        raw_customer_emails.append(_mask_email(email))
    return {
        "raw_customer_email_count": len(set(raw_customer_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_customer_emails))[:5],
        "token_secret_bearer_pattern_count": sum(1 for pattern in SECRET_VALUE_PATTERNS if pattern.search(text or "")),
    }


def _privacy_scan_failed(source_privacy_scan: dict) -> bool:
    for scan in source_privacy_scan.values():
        if scan.get("raw_customer_email_count") or scan.get("token_secret_bearer_pattern_count"):
            return True
    return False


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["one_draft_send_execute_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["real_send_allowed"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "send execute report self privacy scan failed"}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
        payload["detected_issue_summary"] = _issue_summary(payload["one_draft_send_execute_status"], payload["blocking_conditions"])
    return payload


def _partial_id(value) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if len(text) <= 10:
        return "[present]"
    return f"{text[:4]}...{text[-4:]}"


def _is_masked_email(value) -> bool:
    text = str(value or "")
    return bool(text and "@" in text and "***" in text and not EMAIL_RE.fullmatch(text))


def _safe_masked_email(value) -> str:
    text = _sanitize_text(str(value or ""))
    if not text or "@" not in text:
        return ""
    if "***" in text:
        return text
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _safe_text(value) -> str:
    return _sanitize_text(str(value or ""))


def _sanitize_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _issue_summary(status: str, blocking_conditions: list[dict]) -> str:
    if status == DRY_RUN_STATUS:
        return "One-draft send execute stayed in dry-run; no Gmail send, Shopify write, or Kudosi call was performed."
    if status == SENT_STATUS:
        return "Exactly one Gmail draft was sent; send audit is required next and Shopify tag write remains disabled."
    return "One-draft send execute blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.16 Trustpilot Gmail one-draft send execute finished.\n"
        f"Status: {payload.get('one_draft_send_execute_status')}\n"
        f"Mode: {payload.get('mode')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Dry-run: {payload.get('dry_run')}\n"
        f"Sent count: {payload.get('sent_count')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Shopify tag write; Gmail messages.send is never called.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
