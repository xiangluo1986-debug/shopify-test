import json
import re
import subprocess
import time
from html import escape

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_review_send_post_send_audit"
REPORT_JSON_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_review_send_post_send_audit.json"
REPORT_HTML_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_review_send_post_send_audit.html"
SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_review_and_send_execute.json"
SOURCE_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_review_and_send_execute.html"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_REVIEW_SEND_POST_SEND_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_REVIEW_SEND_POST_SEND_AUDIT_JSON_END"

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)("
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|"
    r"refresh[_\s-]?token\s*[:=]|"
    r"client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|"
    r"password\s*[:=]|"
    r"secret\s*[:=]"
    r")"
)
FULL_GMAIL_ID_RE = re.compile(r'"gmail_(?:draft|message)_id"\s*:\s*"[^"]+"')


def run_shopify_review_request_review_send_post_send_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_audit()
    if completed["success"]:
        payload = completed["payload"]
        payload["django_audit_source"] = "django"
        source_report = {}
        source_html = ""
    else:
        source_report, source_error = _load_source_json()
        source_html = _load_source_html()
        payload = _build_payload(source_report, source_error, source_html)
        payload["django_audit_source"] = "host_file_fallback"
        payload["django_failure_type"] = _safe_text(completed.get("failure_type"))
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["privacy_scan_summary"] = _privacy_scan(payload, source_report, source_html)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["audit_status"] = "blocked_privacy_scan_failed"
        payload["report_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["should_move_to_already_sent"] = False
        payload["ready_for_shopify_tag_write_next_phase"] = False
        payload["blocking_conditions"].append(
            {
                "status": "blocked_privacy_scan_failed",
                "detail": "Privacy scan found raw email, full Gmail ID, or secret-like output.",
            }
        )

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_audit() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_review_send_post_send_audit_report; "
        "payload = build_review_request_review_send_post_send_audit_report({}); "
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


def _load_source_json() -> tuple[dict, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "source_review_send_report_missing"
    try:
        payload = json.loads(SOURCE_JSON_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}, "source_review_send_report_unreadable"
    if not isinstance(payload, dict):
        return {}, "source_review_send_report_not_object"
    return payload, ""


def _load_source_html() -> str:
    if not SOURCE_HTML_PATH.exists():
        return ""
    try:
        return SOURCE_HTML_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _build_payload(source_report: dict, source_error: str, source_html: str) -> dict:
    selected_order = _canonical_order_name(
        source_report.get("selected_order")
        or source_report.get("selected_order_name")
        or source_report.get("target_order")
    )
    sent_count = _safe_int(source_report.get("sent_count"))
    email_sent_confirmed = source_report.get("email_sent") is True and sent_count == 1
    gmail_drafts_create_confirmed = source_report.get("gmail_drafts_create_called") is True
    gmail_drafts_send_confirmed = source_report.get("gmail_drafts_send_called") is True
    gmail_api_call_confirmed = source_report.get("gmail_api_call_performed") is True
    gmail_messages_send_confirmed_false = source_report.get("gmail_messages_send_called") is False
    shopify_write_confirmed_false = source_report.get("shopify_write_performed") is False
    shopify_tag_write_confirmed_false = source_report.get("shopify_tag_write_performed") is False
    customer_level_sent_record_available = bool(selected_order and email_sent_confirmed)
    should_move_to_already_sent = bool(email_sent_confirmed and sent_count == 1)
    ready_for_shopify_tag_write_next_phase = should_move_to_already_sent
    blocking_conditions = _blocking_conditions(
        source_error=source_error,
        selected_order=selected_order,
        email_sent_confirmed=email_sent_confirmed,
        sent_count=sent_count,
    )
    audit_status = (
        "review_send_post_send_audit_passed"
        if email_sent_confirmed and sent_count == 1 and not blocking_conditions
        else "blocked_send_not_confirmed"
    )
    if source_error:
        audit_status = source_error
    return {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28M",
        "mode": "dry-run-local-post-send-audit",
        "audit_status": audit_status,
        "report_status": audit_status,
        "success": audit_status == "review_send_post_send_audit_passed",
        "source_review_send_report_found": bool(source_report),
        "source_review_send_json_path": "logs/shopify_review_request_trustpilot_review_and_send_execute.json",
        "source_review_send_html_path": "logs/shopify_review_request_trustpilot_review_and_send_execute.html",
        "source_review_send_html_found": bool(source_html),
        "selected_order": selected_order,
        "email_sent_confirmed": email_sent_confirmed,
        "gmail_api_call_confirmed": gmail_api_call_confirmed,
        "gmail_drafts_create_confirmed": gmail_drafts_create_confirmed,
        "gmail_drafts_send_confirmed": gmail_drafts_send_confirmed,
        "gmail_messages_send_confirmed_false": gmail_messages_send_confirmed_false,
        "sent_count": sent_count,
        "shopify_write_confirmed_false": shopify_write_confirmed_false,
        "shopify_tag_write_confirmed_false": shopify_tag_write_confirmed_false,
        "customer_level_sent_record_available": customer_level_sent_record_available,
        "should_move_to_already_sent": should_move_to_already_sent,
        "ready_for_shopify_tag_write_next_phase": ready_for_shopify_tag_write_next_phase,
        "blocking_conditions": blocking_conditions,
        "no_gmail_api_call_in_audit": True,
        "audit_gmail_api_call_performed": False,
        "audit_gmail_draft_create_performed": False,
        "audit_gmail_drafts_send_performed": False,
        "audit_shopify_api_call_performed": False,
        "audit_shopify_write_performed": False,
        "audit_shopify_tag_write_performed": False,
        "audit_external_review_api_call_performed": False,
        "audit_translations_register_called": False,
        "next_step": "Next step: run Shopify tag write after post-send audit.",
        "detected_issue_summary": _issue_summary(
            audit_status,
            selected_order,
            email_sent_confirmed,
            sent_count,
        ),
    }


def _blocking_conditions(
    source_error: str,
    selected_order: str,
    email_sent_confirmed: bool,
    sent_count: int,
) -> list[dict]:
    conditions = []
    if source_error:
        conditions.append({"status": source_error, "detail": "Latest Review & Send report was not available."})
    if not selected_order:
        conditions.append({"status": "blocked_missing_selected_order", "detail": "No selected order was found."})
    if not email_sent_confirmed:
        conditions.append({"status": "blocked_email_not_confirmed", "detail": "email_sent=true and sent_count=1 were not both confirmed."})
    if sent_count != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "sent_count must equal 1."})
    return conditions


def _privacy_scan(payload: dict, source_report: dict, source_html: str) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    source_text = json.dumps(_safe_source_fragment(source_report), ensure_ascii=False, sort_keys=True)
    combined = "\n".join((text, source_text, source_html or ""))
    raw_emails = []
    for match in EMAIL_RE.finditer(combined):
        value = match.group(0).lower()
        if value == "info@kidstoylover.com" or "***" in value:
            continue
        raw_emails.append(_mask_email(value))
    return {
        "scan_performed": True,
        "passed": not raw_emails and SECRET_RE.search(combined) is None and FULL_GMAIL_ID_RE.search(combined) is None,
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "token_secret_bearer_pattern_count": 1 if SECRET_RE.search(combined) else 0,
        "full_gmail_draft_or_message_id_field_count": 1 if FULL_GMAIL_ID_RE.search(combined) else 0,
    }


def _safe_source_fragment(source_report: dict) -> dict:
    if not isinstance(source_report, dict):
        return {}
    safe_keys = (
        "timestamp",
        "report_generated_at",
        "task",
        "task_name",
        "phase",
        "mode",
        "execution_status",
        "selected_order",
        "selected_order_name",
        "selected_masked_email",
        "candidate_verified",
        "gmail_api_call_performed",
        "gmail_drafts_create_called",
        "gmail_drafts_send_called",
        "gmail_messages_send_called",
        "email_sent",
        "sent_count",
        "shopify_write_performed",
        "shopify_tag_write_performed",
        "privacy_scan_summary",
    )
    return {key: source_report.get(key) for key in safe_keys if key in source_report}


def _write_json(payload: dict):
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return REPORT_JSON_PATH


def _write_html(payload: dict):
    REPORT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html(payload: dict) -> str:
    rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in (
            ("Audit status", payload.get("audit_status")),
            ("Selected order", payload.get("selected_order")),
            ("Email sent confirmed", payload.get("email_sent_confirmed")),
            ("Gmail API call confirmed from source", payload.get("gmail_api_call_confirmed")),
            ("Gmail drafts.create confirmed", payload.get("gmail_drafts_create_confirmed")),
            ("Gmail drafts.send confirmed", payload.get("gmail_drafts_send_confirmed")),
            ("Gmail messages.send confirmed false", payload.get("gmail_messages_send_confirmed_false")),
            ("Sent count", payload.get("sent_count")),
            ("Shopify write confirmed false", payload.get("shopify_write_confirmed_false")),
            ("Shopify tag write confirmed false", payload.get("shopify_tag_write_confirmed_false")),
            ("Move to Already sent", payload.get("should_move_to_already_sent")),
            ("Ready for tag write next phase", payload.get("ready_for_shopify_tag_write_next_phase")),
            ("No Gmail API call in audit", payload.get("no_gmail_api_call_in_audit")),
            ("Next step", payload.get("next_step")),
        )
    )
    blocker_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('detail', '')))}</td>"
        "</tr>"
        for item in payload.get("blocking_conditions") or []
    ) or '<tr><td colspan="2">None</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review &amp; Send Post-Send Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ width: 300px; background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Review &amp; Send Post-Send Audit</h1>
  <table><tbody>{rows}</tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocker_rows}</tbody></table>
</body>
</html>"""


def _task_result(payload: dict, json_path, html_path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "audit_status": payload.get("audit_status"),
        "selected_order": payload.get("selected_order"),
        "email_sent_confirmed": payload.get("email_sent_confirmed"),
        "gmail_drafts_send_confirmed": payload.get("gmail_drafts_send_confirmed"),
        "sent_count": payload.get("sent_count"),
        "shopify_tag_write_confirmed_false": payload.get("shopify_tag_write_confirmed_false"),
        "should_move_to_already_sent": payload.get("should_move_to_already_sent"),
        "ready_for_shopify_tag_write_next_phase": payload.get("ready_for_shopify_tag_write_next_phase"),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path, html_path) -> str:
    return (
        "Review & Send post-send audit complete.\n"
        f"Status: {payload.get('audit_status')}\n"
        f"Selected order: {payload.get('selected_order') or 'None'}\n"
        f"Email sent confirmed: {payload.get('email_sent_confirmed')}\n"
        f"Gmail drafts.send confirmed: {payload.get('gmail_drafts_send_confirmed')}\n"
        f"Sent count: {payload.get('sent_count')}\n"
        f"Shopify tag write confirmed false: {payload.get('shopify_tag_write_confirmed_false')}\n"
        f"Move to Already sent: {payload.get('should_move_to_already_sent')}\n"
        f"JSON: {json_path}\n"
        f"HTML: {html_path}\n"
        "Safety: audit made no Gmail API call, no Shopify write, no external review API call, no translationsRegister.\n"
    )


def _issue_summary(audit_status: str, selected_order: str, email_sent_confirmed: bool, sent_count: int) -> str:
    if audit_status == "review_send_post_send_audit_passed":
        return (
            f"{selected_order} is confirmed sent by the local Review & Send report. "
            "Move it to Already sent with Shopify tag pending. No Gmail API call or Shopify write was performed by this audit."
        )
    return (
        f"Post-send audit blocked. selected_order={selected_order or 'missing'}; "
        f"email_sent_confirmed={email_sent_confirmed}; sent_count={sent_count}. "
        "No Gmail API call or Shopify write was performed by this audit."
    )


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _canonical_order_name(value) -> str:
    text = str(value or "").strip()
    match = re.fullmatch(r"#?(\d{3,})", text)
    return f"#{match.group(1)}" if match else text[:80]


def _mask_email(email: str) -> str:
    text = str(email or "").strip()
    if "@" not in text:
        return ""
    local, domain = text.rsplit("@", 1)
    suffix = domain.split(".")[-1] if "." in domain else ""
    head = domain.split(".", 1)[0] if domain else ""
    if suffix:
        return f"{local[:1]}***@{head[:1]}***.{suffix}"
    return f"{local[:1]}***@***"


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _safe_text(value, max_length=300) -> str:
    return _sanitize_text(value)[:max_length]


def _sanitize_text(value) -> str:
    text = str(value or "").replace("\x00", "")
    text = EMAIL_RE.sub(lambda match: _mask_email(match.group(0)), text)
    return SECRET_RE.sub("[redacted-secret-marker]", text)
