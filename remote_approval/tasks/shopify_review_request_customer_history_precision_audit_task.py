import json
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_customer_history_precision_audit"
COMMAND_LABEL = "shopify_review_request_customer_history_precision_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_customer_history_precision_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_customer_history_precision_audit.html"
LAST_60_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_CUSTOMER_HISTORY_PRECISION_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_CUSTOMER_HISTORY_PRECISION_AUDIT_JSON_END"

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=]|secret\s*[:=])"
)


def run_shopify_review_request_customer_history_precision_audit_task(mode: str) -> dict:
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
        "build_review_request_customer_history_precision_audit_report; "
        "payload = build_review_request_customer_history_precision_audit_report({}); "
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

    blocked_rows = scan.get("blocked_candidates_summary") or scan.get("blocked_queue_rows") or []
    eligible_rows = scan.get("eligible_candidates_summary") or scan.get("eligible_queue_rows") or []
    rows = blocked_rows + eligible_rows
    note_risk_rows = [row for row in blocked_rows if row.get("note_risk_detected") is True]
    low_confidence_rows = [
        row
        for row in blocked_rows
        if "customer history not confirmed" in _safe_text(row.get("block_reason") or row.get("reason"), 500).lower()
    ]
    overcounted_rows = [
        row
        for row in rows
        if _int(row.get("customer_history_order_count_before_precision"))
        > _int(row.get("customer_history_order_count"))
    ]
    order_21083 = scan.get("order_21083_diagnosis") or {}
    active_after = _int(scan.get("review_queue_visible_count") or scan.get("eligible_candidate_count"))
    active_before = _int(scan.get("active_review_send_count_before_precision")) or active_after

    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28I",
        "mode": "dry-run-local-customer-history-precision-audit-fallback",
        "command_label": COMMAND_LABEL,
        "report_status": "customer_history_precision_audit_ready_from_last_60_scan",
        "success": True,
        "fallback_source": "last_60_days_candidate_scan_report",
        "fallback_source_path": str(LAST_60_SCAN_JSON_PATH),
        "django_failure_type": _sanitize_text(result.get("failure_type", "")),
        "order_21083_diagnosis": order_21083,
        "order_21083_found": order_21083.get("found_in_local_shopify_order") is True,
        "order_21083_displayed_order_count_before": _int(order_21083.get("displayed_order_count_before_precision")),
        "order_21083_customer_order_count_after": _int(order_21083.get("customer_history_order_count")),
        "order_21083_matched_order_names_after": order_21083.get("customer_history_matched_order_names") or [],
        "order_21083_match_method": _safe_text(order_21083.get("customer_history_match_method"), 80),
        "order_21083_customer_history_confidence": _safe_text(order_21083.get("customer_history_confidence"), 80),
        "order_21083_note_risk_detected": order_21083.get("note_risk_detected") is True,
        "order_21083_note_risk_field": _safe_text(order_21083.get("note_risk_field"), 120),
        "order_21083_note_risk_keywords": order_21083.get("note_risk_keywords") or [],
        "order_21083_final_eligibility": _safe_text(order_21083.get("final_eligibility_status"), 80),
        "order_21083_final_blockers": order_21083.get("final_blockers") or [],
        "overcounted_customer_history_count": len(overcounted_rows),
        "weak_name_only_match_count": sum(_int(row.get("customer_history_weak_match_count")) for row in rows),
        "candidates_blocked_by_low_confidence_history": len(low_confidence_rows),
        "candidates_blocked_by_note_risk": len(note_risk_rows),
        "first_order_blocked_count": _int(scan.get("first_order_blocked_count")),
        "prior_trustpilot_blocked_count": _int(scan.get("prior_trustpilot_customer_blocked_count")),
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
            f"Customer-history precision audit used last-60 scan fallback. Overcounted histories: {len(overcounted_rows)}; "
            f"note-risk blocked: {len(note_risk_rows)}; low-confidence history blocked: {len(low_confidence_rows)}; "
            f"active Review & Send before/after: {active_before}/{active_after}. "
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
        "phase": "5.28I",
        "mode": "dry-run-local-customer-history-precision-audit",
        "command_label": COMMAND_LABEL,
        "report_status": "blocked_customer_history_precision_audit_failed",
        "success": False,
        "failure_type": _sanitize_text(result.get("failure_type", "")),
        "exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(result.get("stdout", "")),
        "stderr_tail_sanitized": _tail(result.get("stderr", "")),
        "order_21083_found": False,
        "order_21083_diagnosis": {"order_name": "#21083", "final_eligibility_status": "audit_failed"},
        "overcounted_customer_history_count": 0,
        "weak_name_only_match_count": 0,
        "candidates_blocked_by_low_confidence_history": 0,
        "candidates_blocked_by_note_risk": 0,
        "first_order_blocked_count": 0,
        "prior_trustpilot_blocked_count": 0,
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
        "detected_issue_summary": "Customer-history precision audit failed before producing a local report.",
    }


def _write_json(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=True, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "exit_code": 0 if payload.get("success") is True else int(payload.get("exit_code") or 1),
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "report_status": payload.get("report_status", ""),
        "order_21083_found": payload.get("order_21083_found") is True,
        "overcounted_customer_history_count": int(payload.get("overcounted_customer_history_count") or 0),
        "candidates_blocked_by_note_risk": int(payload.get("candidates_blocked_by_note_risk") or 0),
        "candidates_blocked_by_low_confidence_history": int(
            payload.get("candidates_blocked_by_low_confidence_history") or 0
        ),
        "active_review_send_count_before_fix": int(payload.get("active_review_send_count_before_fix") or 0),
        "active_review_send_count_after_fix": int(payload.get("active_review_send_count_after_fix") or 0),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "raw_customer_email_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Review Request customer-history precision audit completed.\n"
        f"Result: {payload.get('report_status')}\n"
        f"#21083 found: {payload.get('order_21083_found') is True}\n"
        f"#21083 note risk: {payload.get('order_21083_note_risk_detected') is True}\n"
        f"Overcounted histories: {payload.get('overcounted_customer_history_count', 0)}\n"
        f"Note-risk blocked: {payload.get('candidates_blocked_by_note_risk', 0)}\n"
        f"Low-confidence history blocked: {payload.get('candidates_blocked_by_low_confidence_history', 0)}\n"
        f"Active Review & Send before/after: {payload.get('active_review_send_count_before_fix', 0)} / "
        f"{payload.get('active_review_send_count_after_fix', 0)}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "0 = stop"
    )


def _render_html(payload: dict) -> str:
    diagnosis = payload.get("order_21083_diagnosis") or {}
    blockers = "; ".join(diagnosis.get("final_blockers") or [])
    keywords = ", ".join(diagnosis.get("note_risk_keywords") or [])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Customer History Precision Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Review Request Customer History Precision Audit</h1>
  <table><tbody>
    <tr><th>Status</th><td>{escape(str(payload.get("report_status", "")))}</td></tr>
    <tr><th>#21083 found</th><td>{escape(str(payload.get("order_21083_found") is True))}</td></tr>
    <tr><th>#21083 count before</th><td>{escape(str(payload.get("order_21083_displayed_order_count_before", 0)))}</td></tr>
    <tr><th>#21083 count after</th><td>{escape(str(payload.get("order_21083_customer_order_count_after", 0)))}</td></tr>
    <tr><th>#21083 match method</th><td>{escape(str(payload.get("order_21083_match_method", "")))}</td></tr>
    <tr><th>#21083 confidence</th><td>{escape(str(payload.get("order_21083_customer_history_confidence", "")))}</td></tr>
    <tr><th>#21083 note risk</th><td>{escape(str(payload.get("order_21083_note_risk_detected") is True))}</td></tr>
    <tr><th>#21083 note field</th><td>{escape(str(payload.get("order_21083_note_risk_field", "")))}</td></tr>
    <tr><th>#21083 safe keywords</th><td>{escape(keywords)}</td></tr>
    <tr><th>#21083 final eligibility</th><td>{escape(str(payload.get("order_21083_final_eligibility", "")))}</td></tr>
    <tr><th>#21083 final blockers</th><td>{escape(blockers)}</td></tr>
    <tr><th>Overcounted histories</th><td>{escape(str(payload.get("overcounted_customer_history_count", 0)))}</td></tr>
    <tr><th>Weak name-only matches</th><td>{escape(str(payload.get("weak_name_only_match_count", 0)))}</td></tr>
    <tr><th>Blocked by note risk</th><td>{escape(str(payload.get("candidates_blocked_by_note_risk", 0)))}</td></tr>
    <tr><th>Blocked by low-confidence history</th><td>{escape(str(payload.get("candidates_blocked_by_low_confidence_history", 0)))}</td></tr>
    <tr><th>Active Review &amp; Send before/after</th><td>{escape(str(payload.get("active_review_send_count_before_fix", 0)))} / {escape(str(payload.get("active_review_send_count_after_fix", 0)))}</td></tr>
    <tr><th>Matched order names after</th><td>{escape(", ".join(diagnosis.get("customer_history_matched_order_names") or []))}</td></tr>
  </tbody></table>
  <h2>Safety</h2>
  <table><tbody>
    <tr><th>Shopify API call performed</th><td>{escape(str(payload.get("shopify_api_call_performed") is True))}</td></tr>
    <tr><th>Shopify write performed</th><td>{escape(str(payload.get("shopify_write_performed") is True))}</td></tr>
    <tr><th>Gmail API call performed</th><td>{escape(str(payload.get("gmail_api_call_performed") is True))}</td></tr>
    <tr><th>Email sent</th><td>{escape(str(payload.get("email_sent") is True))}</td></tr>
    <tr><th>Full note output</th><td>{escape(str(payload.get("full_note_output") is True))}</td></tr>
  </tbody></table>
</body>
</html>"""


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = []
    for match in EMAIL_RE.finditer(text):
        value = match.group(0)
        if "***" not in value:
            raw_emails.append(_mask_email(value))
    return {
        "scan_performed": True,
        "passed": not raw_emails and SECRET_RE.search(text) is None,
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "secret_pattern_count": 1 if SECRET_RE.search(text) else 0,
    }


def _mask_email(value: str) -> str:
    text = str(value or "").strip().lower()
    if not EMAIL_RE.fullmatch(text):
        return ""
    local, domain = text.rsplit("@", 1)
    domain_parts = domain.split(".")
    domain_mask = f"{domain_parts[0][:1]}***.{domain_parts[-1]}" if len(domain_parts) >= 2 else "***"
    return f"{local[:1]}***@{domain_mask}"


def _int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_text(value: object, max_length: int = 300) -> str:
    return _sanitize_text(value, max_length=max_length).strip()


def _sanitize_text(value: object, max_length: int = 1000) -> str:
    text = str(value or "")
    text = EMAIL_RE.sub("[masked-email]", text)
    text = SECRET_RE.sub("[redacted-secret-marker]", text)
    text = "".join(ch if ch == "\n" or ch == "\t" or ord(ch) >= 32 else " " for ch in text)
    return text[:max_length]


def _tail(value: str, max_lines: int = 80) -> str:
    return "\n".join(str(value or "").splitlines()[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return bytes(value).decode("utf-8", errors="replace")
