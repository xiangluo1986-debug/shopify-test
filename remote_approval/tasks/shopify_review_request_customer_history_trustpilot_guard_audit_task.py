import json
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_customer_history_trustpilot_guard_audit"
COMMAND_LABEL = "shopify_review_request_customer_history_trustpilot_guard_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_customer_history_trustpilot_guard_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_customer_history_trustpilot_guard_audit.html"
LAST_60_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_CUSTOMER_HISTORY_TRUSTPILOT_GUARD_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_CUSTOMER_HISTORY_TRUSTPILOT_GUARD_AUDIT_JSON_END"

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=]|secret\s*[:=])"
)


def run_shopify_review_request_customer_history_trustpilot_guard_audit_task(mode: str) -> dict:
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
        "build_review_request_customer_history_trustpilot_guard_audit_report; "
        "payload = build_review_request_customer_history_trustpilot_guard_audit_report({}); "
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


def _fallback_from_last_60_scan(result: dict) -> dict:
    if not LAST_60_SCAN_JSON_PATH.exists():
        return {}
    try:
        scan = json.loads(LAST_60_SCAN_JSON_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(scan, dict):
        return {}

    first_order_count = int(scan.get("first_order_blocked_count") or 0)
    prior_count = int(scan.get("prior_trustpilot_customer_blocked_count") or 0)
    unknown_count = int(scan.get("customer_history_unknown_count") or 0)
    eligible_after = int(scan.get("eligible_candidate_count") or 0)
    active_count = int(scan.get("review_queue_visible_count") or 0)
    candidate_before = int(scan.get("candidate_count_before_fix") or 0)
    if not candidate_before:
        candidate_before = eligible_after + first_order_count + prior_count
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28H",
        "mode": "dry-run-local-customer-history-trustpilot-guard-audit-fallback",
        "command_label": COMMAND_LABEL,
        "report_status": "customer_history_trustpilot_guard_audit_ready_from_last_60_scan",
        "success": True,
        "fallback_source": "last_60_days_candidate_scan_report",
        "fallback_source_path": str(LAST_60_SCAN_JSON_PATH),
        "django_failure_type": _sanitize_text(result.get("failure_type", "")),
        "customer_history_resolver_enabled": True,
        "trustpilot_sent_tag_aliases": scan.get("trustpilot_sent_tag_aliases")
        or ["1: trustpilot", "1: trustpoilt", "trustpilot", "trustpoilt"],
        "first_order_candidate_count_before_fix": first_order_count,
        "first_order_blocked_count": first_order_count,
        "prior_trustpilot_customer_blocked_count": prior_count,
        "customer_history_unknown_count": unknown_count,
        "candidate_count_before_fix": candidate_before,
        "candidate_count_after_fix": eligible_after,
        "visible_review_send_count_after_fix": active_count,
        "review_queue_visible_count_after_fix": active_count,
        "active_review_send_count_after_fix": active_count,
        "order_21070_diagnosis": scan.get("order_21070_diagnosis") or {},
        "order_21075_diagnosis": scan.get("order_21075_diagnosis") or {},
        "order_21076_diagnosis": scan.get("order_21076_diagnosis") or {},
        "order_21102_diagnosis": scan.get("order_21102_diagnosis") or {},
        "order_21778_diagnosis": scan.get("order_21778_diagnosis") or {},
        "order_21778_trustpilot_tag_detection": scan.get("order_21778_trustpilot_tag_detection") or {},
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
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            f"Customer-history guard audit used last-60 scan fallback. First-order blocked: {first_order_count}; "
            f"prior Trustpilot customer-history blocked: {prior_count}; history unknown blocked: {unknown_count}; "
            f"eligible candidates after fix: {eligible_after}; active Review & Send buttons after fix: "
            f"{active_count}. No Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, or external API calls were performed."
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


def _failure_payload(result: dict) -> dict:
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28H",
        "mode": "dry-run-local-customer-history-trustpilot-guard-audit",
        "command_label": COMMAND_LABEL,
        "report_status": "blocked_customer_history_trustpilot_guard_audit_failed",
        "success": False,
        "failure_type": _sanitize_text(result.get("failure_type", "")),
        "exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(result.get("stdout", "")),
        "stderr_tail_sanitized": _tail(result.get("stderr", "")),
        "first_order_candidate_count_before_fix": 0,
        "first_order_blocked_count": 0,
        "prior_trustpilot_customer_blocked_count": 0,
        "customer_history_unknown_count": 0,
        "candidate_count_before_fix": 0,
        "candidate_count_after_fix": 0,
        "visible_review_send_count_after_fix": 0,
        "active_review_send_count_after_fix": 0,
        "order_21070_diagnosis": {"order_name": "#21070", "final_eligibility_status": "audit_failed"},
        "order_21075_diagnosis": {"order_name": "#21075", "final_eligibility_status": "audit_failed"},
        "order_21076_diagnosis": {"order_name": "#21076", "final_eligibility_status": "audit_failed"},
        "order_21102_diagnosis": {"order_name": "#21102", "final_eligibility_status": "audit_failed"},
        "order_21778_trustpilot_tag_detection": {
            "order_name": "#21778",
            "trustpilot_tag_detected": False,
            "matched_trustpilot_tag_values": [],
        },
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
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": "Customer-history Trustpilot guard audit failed before producing a Django report.",
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
        "first_order_candidate_count_before_fix": int(payload.get("first_order_candidate_count_before_fix") or 0),
        "first_order_blocked_count": int(payload.get("first_order_blocked_count") or 0),
        "prior_trustpilot_customer_blocked_count": int(payload.get("prior_trustpilot_customer_blocked_count") or 0),
        "customer_history_unknown_count": int(payload.get("customer_history_unknown_count") or 0),
        "candidate_count_before_fix": int(payload.get("candidate_count_before_fix") or 0),
        "candidate_count_after_fix": int(payload.get("candidate_count_after_fix") or 0),
        "visible_review_send_count_after_fix": int(payload.get("visible_review_send_count_after_fix") or 0),
        "active_review_send_count_after_fix": int(payload.get("active_review_send_count_after_fix") or 0),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    detection = payload.get("order_21778_trustpilot_tag_detection") or {}
    return (
        "Review Request customer-history Trustpilot guard audit completed.\n"
        f"Result: {payload.get('report_status')}\n"
        f"First-order blocked: {payload.get('first_order_blocked_count', 0)}\n"
        f"Prior Trustpilot customer blocked: {payload.get('prior_trustpilot_customer_blocked_count', 0)}\n"
        f"Customer history unknown: {payload.get('customer_history_unknown_count', 0)}\n"
        f"Candidate count before/after: {payload.get('candidate_count_before_fix', 0)} / "
        f"{payload.get('candidate_count_after_fix', 0)}\n"
        f"Active Review & Send after fix: {payload.get('active_review_send_count_after_fix', 0)}\n"
        f"#21778 Trustpilot tag detected: {detection.get('trustpilot_tag_detected') is True}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "0 = stop"
    )


def _render_html(payload: dict) -> str:
    rows = "\n".join(
        _diagnosis_row(label, payload.get(key) or {})
        for label, key in (
            ("#21070", "order_21070_diagnosis"),
            ("#21075", "order_21075_diagnosis"),
            ("#21076", "order_21076_diagnosis"),
            ("#21102", "order_21102_diagnosis"),
        )
    )
    detection = payload.get("order_21778_trustpilot_tag_detection") or {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Customer History Trustpilot Guard Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
  </style>
</head>
<body>
  <h1>Review Request Customer History Trustpilot Guard Audit</h1>
  <table><tbody>
    <tr><th>Status</th><td>{escape(str(payload.get("report_status", "")))}</td></tr>
    <tr><th>First-order candidate count before fix</th><td>{escape(str(payload.get("first_order_candidate_count_before_fix", 0)))}</td></tr>
    <tr><th>First-order blocked count</th><td>{escape(str(payload.get("first_order_blocked_count", 0)))}</td></tr>
    <tr><th>Prior Trustpilot customer blocked count</th><td>{escape(str(payload.get("prior_trustpilot_customer_blocked_count", 0)))}</td></tr>
    <tr><th>Customer history unknown count</th><td>{escape(str(payload.get("customer_history_unknown_count", 0)))}</td></tr>
    <tr><th>Candidate count before fix</th><td>{escape(str(payload.get("candidate_count_before_fix", 0)))}</td></tr>
    <tr><th>Candidate count after fix</th><td>{escape(str(payload.get("candidate_count_after_fix", 0)))}</td></tr>
    <tr><th>Active Review &amp; Send after fix</th><td>{escape(str(payload.get("active_review_send_count_after_fix", 0)))}</td></tr>
    <tr><th>#21778 Trustpilot tag detected</th><td>{escape(str(detection.get("trustpilot_tag_detected") is True))}</td></tr>
    <tr><th>#21778 matched tag values</th><td>{escape(", ".join(detection.get("matched_trustpilot_tag_values") or []))}</td></tr>
  </tbody></table>
  <h2>Focus Orders</h2>
  <table>
    <thead><tr><th>Order</th><th>Status</th><th>History count</th><th>Trustpilot history</th><th>Blockers</th></tr></thead>
    <tbody>{rows}</tbody>
  </table>
  <h2>Safety</h2>
  <table><tbody>
    <tr><th>Shopify API call performed</th><td>{escape(str(payload.get("shopify_api_call_performed") is True))}</td></tr>
    <tr><th>Shopify write performed</th><td>{escape(str(payload.get("shopify_write_performed") is True))}</td></tr>
    <tr><th>Gmail API call performed</th><td>{escape(str(payload.get("gmail_api_call_performed") is True))}</td></tr>
    <tr><th>Email sent</th><td>{escape(str(payload.get("email_sent") is True))}</td></tr>
    <tr><th>External review API call performed</th><td>{escape(str(payload.get("external_review_api_call_performed") is True))}</td></tr>
  </tbody></table>
</body>
</html>"""


def _diagnosis_row(label: str, diagnosis: dict) -> str:
    previous = " / ".join(diagnosis.get("previous_trustpilot_order_names") or [])
    blockers = "; ".join(diagnosis.get("final_blockers") or [])
    return (
        "<tr>"
        f"<td>{escape(label)}</td>"
        f"<td>{escape(str(diagnosis.get('final_eligibility_status', '')))}</td>"
        f"<td>{escape(str(diagnosis.get('customer_history_order_count', 0)))}</td>"
        f"<td>{escape(previous or 'None')}</td>"
        f"<td>{escape(blockers or 'None')}</td>"
        "</tr>"
    )


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = []
    for match in EMAIL_RE.finditer(text):
        value = match.group(0)
        if "***" not in value:
            raw_emails.append(_mask_email(value))
    secret_count = 1 if SECRET_RE.search(text) else 0
    return {
        "scan_performed": True,
        "passed": not raw_emails and not secret_count,
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "secret_pattern_count": secret_count,
    }


def _mask_email(value: str) -> str:
    text = str(value or "").strip().lower()
    if not EMAIL_RE.fullmatch(text):
        return ""
    local, domain = text.rsplit("@", 1)
    domain_parts = domain.split(".")
    if len(domain_parts) >= 2:
        domain_mask = f"{domain_parts[0][:1]}***.{domain_parts[-1]}"
    else:
        domain_mask = "***"
    return f"{local[:1]}***@{domain_mask}"


def _tail(value: str, max_lines: int = 80) -> str:
    return "\n".join(str(value or "").splitlines()[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _sanitize_text(value, max_length: int = 1000) -> str:
    text = str(value or "")
    text = EMAIL_RE.sub("[masked-email]", text)
    text = SECRET_RE.sub("[redacted-secret-marker]", text)
    text = "".join(ch if ch == "\n" or ch == "\t" or ord(ch) >= 32 else " " for ch in text)
    return text[:max_length].strip()
