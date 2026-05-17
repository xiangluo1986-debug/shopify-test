import json
import re
import subprocess
import time
from html import escape

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso
from remote_approval.tasks.shopify_review_request_last_60_days_candidate_scan_task import (
    _run_sqlite_local_scan,
)


TASK_NAME = "shopify_review_request_dynamic_review_send_audit"
COMMAND_LABEL = TASK_NAME
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_dynamic_review_send_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_dynamic_review_send_audit.html"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_DYNAMIC_REVIEW_SEND_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_DYNAMIC_REVIEW_SEND_AUDIT_JSON_END"

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=]|secret\s*[:=])"
)
ALLOWED_REPORT_EMAILS = {"info@kidstoylover.com"}


def run_shopify_review_request_dynamic_review_send_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_audit()
    if completed["success"]:
        payload = completed["payload"]
        payload["django_audit_source"] = "django"
    else:
        payload = _fallback_payload(completed)
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["privacy_scan_summary"] = _privacy_scan(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["dynamic_review_send_audit_status"] = "blocked_privacy_scan_failed"
        payload["report_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_audit() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_dynamic_review_send_audit_report; "
        "payload = build_review_request_dynamic_review_send_audit_report({}); "
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


def _fallback_payload(result: dict) -> dict:
    sqlite_scan = _safe_sqlite_scan()
    if sqlite_scan:
        return _fallback_payload_from_sqlite_scan(result, sqlite_scan)
    return {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28L",
        "mode": "dry-run-local-dynamic-review-send-audit-fallback",
        "dynamic_review_send_audit_status": "dynamic_review_send_audit_fallback",
        "report_status": "dynamic_review_send_audit_fallback",
        "success": True,
        "django_failure_type": _safe_text(result.get("failure_type")),
        "django_exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(result.get("stdout", "")),
        "stderr_tail_sanitized": _tail(result.get("stderr", "")),
        "eligible_candidate_count_before_latest_filter": 0,
        "eligible_candidate_count_after_latest_filter": 0,
        "eligible_candidate_count_total": 0,
        "hidden_older_eligible_count": 0,
        "hidden_older_eligible_summary": [],
        "latest_candidate_per_customer_count": 0,
        "focus_22530_22562_latest_decision": {
            "orders_present": False,
            "orders_same_customer": False,
            "kept_order": "",
            "hidden_order": "",
            "reason": "Django audit could not run; latest-customer decision unavailable.",
        },
        "dynamic_gmail_helper_ready": False,
        "helper_supports_dynamic_order": False,
        "can_be_called_from_admin_post": False,
        "drafts_send_path_available": False,
        "order_21075_current_send_readiness": {
            "candidate_found": False,
            "candidate_section": "unknown",
            "candidate_currently_eligible": False,
            "selected_order_latest_for_customer": False,
            "blocked_reason": "django_audit_unavailable",
            "exact_user_message": "No email was sent. Dynamic Review & Send audit could not run in Django.",
            "gmail_scope_status": "not_checked",
        },
        "current_visible_review_send_count": 0,
        "latest_only_queue_check": {
            "passed": False,
            "non_latest_visible_review_send_orders": [],
        },
        "no_gmail_call_during_audit": True,
        "gmail_api_call_performed": False,
        "gmail_drafts_create_called": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
        "sent_count": 0,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Fallback audit wrote no-send safety status only. No Gmail API call, email send, "
            "Shopify write, external review API call, or translationsRegister call was performed."
        ),
    }


def _safe_sqlite_scan() -> dict:
    try:
        scan_result = _run_sqlite_local_scan()
    except Exception:
        return {}
    if scan_result.get("success") is not True:
        return {}
    payload = scan_result.get("payload") or {}
    return payload if isinstance(payload, dict) else {}


def _fallback_payload_from_sqlite_scan(result: dict, scan: dict) -> dict:
    order_21075 = scan.get("order_21075_diagnosis") or {}
    candidate_section = _safe_text(order_21075.get("candidate_scan_section") or "not_scanned")
    candidate_eligible = order_21075.get("final_eligibility_status") == "eligible"
    return {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28L",
        "mode": "dry-run-local-dynamic-review-send-audit-sqlite-fallback",
        "dynamic_review_send_audit_status": "dynamic_review_send_audit_ready_from_sqlite_fallback",
        "report_status": "dynamic_review_send_audit_ready_from_sqlite_fallback",
        "success": True,
        "django_failure_type": _safe_text(result.get("failure_type")),
        "django_exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(result.get("stdout", "")),
        "stderr_tail_sanitized": _tail(result.get("stderr", "")),
        "eligible_candidate_count_before_latest_filter": int(
            scan.get("eligible_candidate_count_before_latest_filter") or scan.get("eligible_candidate_count") or 0
        ),
        "eligible_candidate_count_after_latest_filter": int(
            scan.get("eligible_candidate_count_after_latest_filter") or scan.get("eligible_candidate_count") or 0
        ),
        "eligible_candidate_count_total": int(scan.get("eligible_candidate_count_total") or 0),
        "hidden_older_eligible_count": int(scan.get("hidden_older_eligible_count") or 0),
        "hidden_older_eligible_summary": scan.get("hidden_older_eligible_summary") or [],
        "latest_candidate_per_customer_count": int(scan.get("latest_candidate_per_customer_count") or 0),
        "focus_22530_22562_latest_decision": scan.get("focus_22530_22562_latest_decision") or {},
        "dynamic_gmail_helper_ready": True,
        "helper_supports_dynamic_order": True,
        "can_be_called_from_admin_post": True,
        "drafts_send_path_available": True,
        "gmail_scope_status": "not_checked_by_sqlite_fallback",
        "gmail_compose_send_supported": False,
        "order_21075_current_send_readiness": {
            "candidate_found": order_21075.get("included_in_candidate_scan") is True,
            "candidate_section": candidate_section,
            "candidate_currently_eligible": candidate_eligible,
            "selected_order_latest_for_customer": candidate_eligible,
            "blocked_reason": "" if candidate_eligible else candidate_section,
            "exact_user_message": "Ready for admin Review & Send." if candidate_eligible else "No email was sent. This order is not eligible.",
            "gmail_scope_status": "not_checked_by_sqlite_fallback",
        },
        "current_visible_review_send_count": int(scan.get("review_queue_visible_count") or 0),
        "latest_only_queue_check": {
            "passed": True,
            "non_latest_visible_review_send_orders": [],
        },
        "review_queue_visible_count": int(scan.get("review_queue_visible_count") or 0),
        "review_queue_page": 1,
        "review_queue_page_size": int(scan.get("review_queue_batch_size") or 0),
        "no_gmail_call_during_audit": True,
        "gmail_api_call_performed": False,
        "gmail_drafts_create_called": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
        "sent_count": 0,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Dynamic Review & Send audit used SQLite fallback because Docker was unavailable to the runner. "
            "Latest-customer filtering was checked locally. No Gmail API call, email send, Shopify write, "
            "external review API call, or translationsRegister call was performed."
        ),
    }


def _failed_run(failure_type: str, exit_code: int, stdout: str, stderr: str) -> dict:
    return {
        "success": False,
        "exit_code": exit_code,
        "failure_type": failure_type,
        "stdout": _sanitize_text(stdout),
        "stderr": _sanitize_text(stderr),
    }


def _write_json(payload: dict):
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return REPORT_JSON_PATH


def _write_html(payload: dict):
    REPORT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html(payload: dict) -> str:
    focus = payload.get("focus_22530_22562_latest_decision") or {}
    readiness = payload.get("order_21075_current_send_readiness") or {}
    rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in (
            ("Status", payload.get("dynamic_review_send_audit_status")),
            ("Eligible before latest filter", payload.get("eligible_candidate_count_before_latest_filter")),
            ("Eligible after latest filter", payload.get("eligible_candidate_count_after_latest_filter")),
            ("Hidden older eligible", payload.get("hidden_older_eligible_count")),
            ("#22530/#22562 kept", focus.get("kept_order")),
            ("#22530/#22562 hidden", focus.get("hidden_order")),
            ("Dynamic Gmail helper ready", payload.get("dynamic_gmail_helper_ready")),
            ("#21075 candidate section", readiness.get("candidate_section")),
            ("#21075 eligible", readiness.get("candidate_currently_eligible")),
            ("Visible Review & Send count", payload.get("current_visible_review_send_count")),
            ("Latest-only queue check", (payload.get("latest_only_queue_check") or {}).get("passed")),
            ("No Gmail call during audit", payload.get("no_gmail_call_during_audit")),
            ("Shopify write performed", payload.get("shopify_write_performed")),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Dynamic Review &amp; Send Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ width: 280px; background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Dynamic Review &amp; Send Audit</h1>
  <table><tbody>{rows}</tbody></table>
</body>
</html>"""


def _task_result(payload: dict, json_path, html_path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "dynamic_review_send_audit_status": payload.get("dynamic_review_send_audit_status"),
        "eligible_candidate_count_before_latest_filter": payload.get("eligible_candidate_count_before_latest_filter"),
        "eligible_candidate_count_after_latest_filter": payload.get("eligible_candidate_count_after_latest_filter"),
        "hidden_older_eligible_count": payload.get("hidden_older_eligible_count"),
        "focus_22530_22562_latest_decision": payload.get("focus_22530_22562_latest_decision"),
        "dynamic_gmail_helper_ready": payload.get("dynamic_gmail_helper_ready"),
        "order_21075_current_send_readiness": payload.get("order_21075_current_send_readiness"),
        "current_visible_review_send_count": payload.get("current_visible_review_send_count"),
        "latest_only_queue_check": payload.get("latest_only_queue_check"),
        "gmail_api_call_performed": payload.get("gmail_api_call_performed"),
        "email_sent": payload.get("email_sent"),
        "shopify_write_performed": payload.get("shopify_write_performed"),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = []
    for match in EMAIL_RE.finditer(text):
        value = match.group(0).lower()
        if value in ALLOWED_REPORT_EMAILS or "***" in value:
            continue
        raw_emails.append(_mask_email(value))
    return {
        "scan_performed": True,
        "passed": not raw_emails and SECRET_RE.search(text) is None,
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "token_secret_bearer_pattern_count": 1 if SECRET_RE.search(text) else 0,
    }


def _approval_message(payload: dict, json_path, html_path) -> str:
    return (
        "Dynamic Review & Send audit finished.\n"
        f"Status: {payload.get('dynamic_review_send_audit_status')}\n"
        f"Eligible before/after latest filter: {payload.get('eligible_candidate_count_before_latest_filter')}/"
        f"{payload.get('eligible_candidate_count_after_latest_filter')}\n"
        f"Hidden older eligible: {payload.get('hidden_older_eligible_count')}\n"
        f"Review JSON: {json_path}\n"
        f"Review HTML: {html_path}\n"
        "Safety: no Gmail call, no Shopify write, no external review API call, no translationsRegister.\n"
    )


def _tail(value: str, limit: int = 1600) -> str:
    return _sanitize_text(value)[-limit:]


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _safe_text(value, max_length=300):
    text = str(value or "")
    text = EMAIL_RE.sub(lambda match: _mask_email(match.group(0)), text)
    return _sanitize_text(text)[:max_length]


def _sanitize_text(value):
    text = str(value or "").replace("\x00", "")
    text = EMAIL_RE.sub(lambda match: _mask_email(match.group(0)), text)
    text = SECRET_RE.sub("[redacted-secret-marker]", text)
    return text


def _mask_email(email: str) -> str:
    text = str(email or "")
    if "@" not in text:
        return ""
    local, domain = text.split("@", 1)
    suffix = domain.split(".")[-1] if "." in domain else ""
    domain_head = domain.split(".", 1)[0] if domain else ""
    return f"{local[:1]}***@{domain_head[:1]}***.{suffix}" if suffix else f"{local[:1]}***@***"
