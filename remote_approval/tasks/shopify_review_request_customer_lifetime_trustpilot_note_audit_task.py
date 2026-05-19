import json
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_customer_lifetime_trustpilot_note_audit"
COMMAND_LABEL = "shopify_review_request_customer_lifetime_trustpilot_note_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_customer_lifetime_trustpilot_note_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_customer_lifetime_trustpilot_note_audit.html"
LAST_60_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_CUSTOMER_LIFETIME_TRUSTPILOT_NOTE_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_CUSTOMER_LIFETIME_TRUSTPILOT_NOTE_AUDIT_JSON_END"

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=]|secret\s*[:=])"
)


def run_shopify_review_request_customer_lifetime_trustpilot_note_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_audit()
    if completed["success"]:
        payload = completed["payload"]
        payload["django_audit_source"] = "django"
    else:
        payload = _fallback_from_last_60_scan(completed) or _failure_payload(completed)
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["privacy_scan_summary"] = _privacy_scan(payload)

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_audit() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_customer_lifetime_trustpilot_note_audit_report; "
        "payload = build_review_request_customer_lifetime_trustpilot_note_audit_report({}); "
        f"print('{JSON_BEGIN}'); "
        "print(json.dumps(payload, ensure_ascii=False, sort_keys=True)); "
        f"print('{JSON_END}')"
    )
    command = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", script]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=False,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
    except FileNotFoundError:
        return _failed_run("docker_command_not_found", 127, "", "Docker command was not found.")
    except PermissionError:
        return _failed_run("docker_permission_denied", 126, "", "Docker permission denied.")
    except subprocess.TimeoutExpired as exc:
        return _failed_run("timeout", 124, _to_text(exc.stdout), _to_text(exc.stderr))

    stdout = _to_text(completed.stdout)
    stderr = _to_text(completed.stderr)
    payload = _extract_payload(stdout)
    if completed.returncode != 0:
        return _failed_run("django_local_audit_failed", completed.returncode, stdout, stderr)
    if not payload:
        return _failed_run("audit_payload_missing", 1, stdout, stderr)
    return {"success": True, "exit_code": 0, "payload": payload}


def _fallback_from_last_60_scan(result: dict) -> dict:
    if not LAST_60_SCAN_JSON_PATH.exists():
        return {}
    try:
        scan = json.loads(LAST_60_SCAN_JSON_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(scan, dict):
        return {}

    order_21687 = scan.get("order_21687_diagnosis") or {}
    blocked_rows = scan.get("blocked_candidates_summary") or scan.get("blocked_queue_rows") or []
    eligible_rows = scan.get("eligible_candidates_summary") or scan.get("eligible_queue_rows") or []
    note_blocked_rows = [
        row
        for row in blocked_rows
        if row.get("customer_level_trustpilot_note_evidence_found") is True
        or row.get("trustpilot_note_evidence_found") is True
    ]
    active_after = (
        _int(scan.get("active_review_send_count_after_historical_trustpilot_note_guard"))
        or _int(scan.get("eligible_candidate_count"))
        or _int(scan.get("review_queue_visible_count"))
    )
    active_before = _int(scan.get("active_review_send_count_before_historical_trustpilot_note_guard"))
    if not active_before:
        active_before = active_after + len(note_blocked_rows)

    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.31",
        "mode": "dry-run-local-customer-lifetime-trustpilot-note-audit-fallback",
        "command_label": COMMAND_LABEL,
        "report_status": "customer_lifetime_trustpilot_note_audit_ready_from_last_60_scan",
        "success": True,
        "fallback_source": "last_60_days_candidate_scan_report",
        "fallback_source_path": str(LAST_60_SCAN_JSON_PATH),
        "django_failure_type": _sanitize_text(result.get("failure_type", "")),
        "order_21687_diagnosis": order_21687,
        "order_21687_found": order_21687.get("found_in_local_shopify_order") is True,
        "order_21687_customer_lifetime_order_count": _int(order_21687.get("customer_history_order_count")),
        "order_21687_matched_order_names": order_21687.get("customer_history_matched_order_names") or [],
        "order_21687_match_method": _safe_text(order_21687.get("customer_history_match_method"), 80),
        "order_21687_customer_history_confidence": _safe_text(order_21687.get("customer_history_confidence"), 80),
        "order_21687_trustpilot_note_evidence_found": (
            order_21687.get("customer_level_trustpilot_note_evidence_found") is True
        ),
        "order_21687_evidence_order_name": _safe_text(
            order_21687.get("customer_level_trustpilot_note_evidence_order_name"), 80
        ),
        "order_21687_safe_detected_keyword": _safe_text(
            order_21687.get("customer_level_trustpilot_note_safe_keyword"), 80
        ),
        "order_21687_final_eligibility": _safe_text(order_21687.get("final_eligibility_status"), 80),
        "order_21687_final_blockers": order_21687.get("final_blockers") or [],
        "candidates_blocked_by_historical_trustpilot_note_count": len(note_blocked_rows),
        "active_review_send_count_before_historical_trustpilot_note_guard": active_before,
        "active_review_send_count_after_historical_trustpilot_note_guard": active_after,
        "active_review_send_count_before_fix": active_before,
        "active_review_send_count_after_fix": active_after,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Customer lifetime Trustpilot note audit used last-60 scan fallback. "
            f"#21687 found={order_21687.get('found_in_local_shopify_order') is True}; "
            f"historical note blocks={len(note_blocked_rows)}; active before/after={active_before}/{active_after}. "
            "No Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, or external API calls were performed."
        ),
    }


def _extract_payload(stdout: str) -> dict:
    if JSON_BEGIN not in stdout or JSON_END not in stdout:
        return {}
    fragment = stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0].strip()
    try:
        payload = json.loads(fragment)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _failed_run(failure_type: str, exit_code: int, stdout: str, stderr: str) -> dict:
    return {
        "success": False,
        "exit_code": exit_code,
        "failure_type": failure_type,
        "stdout": _sanitize_text(stdout),
        "stderr": _sanitize_text(stderr),
    }


def _failure_payload(result: dict) -> dict:
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.31",
        "mode": "dry-run-local-customer-lifetime-trustpilot-note-audit",
        "command_label": COMMAND_LABEL,
        "report_status": "blocked_customer_lifetime_trustpilot_note_audit_failed",
        "success": False,
        "failure_type": _sanitize_text(result.get("failure_type", "")),
        "exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(result.get("stdout", "")),
        "stderr_tail_sanitized": _tail(result.get("stderr", "")),
        "order_21687_found": False,
        "order_21687_customer_lifetime_order_count": 0,
        "order_21687_matched_order_names": [],
        "order_21687_match_method": "",
        "order_21687_customer_history_confidence": "",
        "order_21687_trustpilot_note_evidence_found": False,
        "order_21687_evidence_order_name": "",
        "order_21687_safe_detected_keyword": "",
        "order_21687_final_eligibility": "audit_failed",
        "order_21687_final_blockers": ["audit_failed"],
        "candidates_blocked_by_historical_trustpilot_note_count": 0,
        "active_review_send_count_before_historical_trustpilot_note_guard": 0,
        "active_review_send_count_after_historical_trustpilot_note_guard": 0,
        "active_review_send_count_before_fix": 0,
        "active_review_send_count_after_fix": 0,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": "Customer lifetime Trustpilot note audit failed before producing a local report.",
    }


def _write_json(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(
        json.dumps(_sanitize_payload(payload), ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "status": "completed" if payload.get("success") else "failed",
        "task": TASK_NAME,
        "summary": payload.get("detected_issue_summary", ""),
        "review_file": str(json_path),
        "html_review_file": str(html_path),
        "details": {
            "report_status": payload.get("report_status"),
            "order_21687_found": payload.get("order_21687_found") is True,
            "order_21687_customer_lifetime_order_count": payload.get(
                "order_21687_customer_lifetime_order_count"
            ),
            "order_21687_trustpilot_note_evidence_found": payload.get(
                "order_21687_trustpilot_note_evidence_found"
            ) is True,
            "candidates_blocked_by_historical_trustpilot_note_count": payload.get(
                "candidates_blocked_by_historical_trustpilot_note_count"
            ),
            "active_review_send_count_before_fix": payload.get("active_review_send_count_before_fix"),
            "active_review_send_count_after_fix": payload.get("active_review_send_count_after_fix"),
            "json_report": str(json_path),
            "html_report": str(html_path),
            "approval_message": _approval_message(payload, json_path, html_path),
        },
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Customer lifetime Trustpilot note audit complete.\n"
        f"Status: {payload.get('report_status')}\n"
        f"#21687 found: {payload.get('order_21687_found')}\n"
        f"#21687 lifetime orders: {payload.get('order_21687_customer_lifetime_order_count')}\n"
        f"#21687 Trustpilot note evidence found: {payload.get('order_21687_trustpilot_note_evidence_found')}\n"
        f"Evidence order: {payload.get('order_21687_evidence_order_name') or 'None'}\n"
        f"Safe keyword: {payload.get('order_21687_safe_detected_keyword') or 'None'}\n"
        "Safety: no Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, external API, email, tag write, "
        "mutation, or translationsRegister call was performed.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}"
    )


def _render_html(payload: dict) -> str:
    rows = [
        ("Status", payload.get("report_status", "")),
        ("#21687 Found", payload.get("order_21687_found")),
        ("#21687 Lifetime Orders", payload.get("order_21687_customer_lifetime_order_count")),
        ("#21687 Matched Orders", ", ".join(payload.get("order_21687_matched_order_names") or [])),
        ("#21687 Match Method", payload.get("order_21687_match_method", "")),
        ("#21687 Confidence", payload.get("order_21687_customer_history_confidence", "")),
        ("#21687 Trustpilot Note Evidence", payload.get("order_21687_trustpilot_note_evidence_found")),
        ("#21687 Evidence Order", payload.get("order_21687_evidence_order_name", "")),
        ("#21687 Safe Keyword", payload.get("order_21687_safe_detected_keyword", "")),
        ("#21687 Final Eligibility", payload.get("order_21687_final_eligibility", "")),
        ("#21687 Final Blockers", ", ".join(payload.get("order_21687_final_blockers") or [])),
        (
            "Historical Trustpilot Note Blocks",
            payload.get("candidates_blocked_by_historical_trustpilot_note_count", 0),
        ),
        ("Active Review & Send Before", payload.get("active_review_send_count_before_fix", 0)),
        ("Active Review & Send After", payload.get("active_review_send_count_after_fix", 0)),
        ("Gmail API Call Performed", payload.get("gmail_api_call_performed") is True),
        ("Shopify API Call Performed", payload.get("shopify_api_call_performed") is True),
        ("Shopify Write Performed", payload.get("shopify_write_performed") is True),
        ("External Review API Call Performed", payload.get("external_review_api_call_performed") is True),
        ("Full Note Output", payload.get("full_note_output") is True),
        ("Raw Customer Email Output", payload.get("raw_customer_email_output") is True),
    ]
    body = "".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in rows
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Customer Lifetime Trustpilot Note Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; width: 280px; }}
  </style>
</head>
<body>
  <h1>Customer Lifetime Trustpilot Note Audit</h1>
  <table><tbody>{body}</tbody></table>
</body>
</html>"""


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(_sanitize_payload(payload), ensure_ascii=False, sort_keys=True)
    return {
        "raw_customer_email_output": bool(EMAIL_RE.search(text)),
        "secret_like_output": bool(SECRET_RE.search(text)),
        "full_note_output": any(
            key in text
            for key in (
                '"shopify_note":',
                '"shopify_note_attributes":',
                '"warehouse_note":',
                '"transfer_note":',
            )
        ),
    }


def _sanitize_payload(value):
    if isinstance(value, dict):
        return {str(key): _sanitize_payload(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _safe_text(value: object, max_length: int = 300) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:max_length]


def _sanitize_text(value: object, max_length: int = 1000) -> str:
    text = _safe_text(value, max_length)
    text = EMAIL_RE.sub("[masked-email]", text)
    text = SECRET_RE.sub("[redacted-secret-like-value]", text)
    return text


def _tail(value: str, max_lines: int = 80) -> str:
    return "\n".join(_sanitize_text(line, 500) for line in str(value or "").splitlines()[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
