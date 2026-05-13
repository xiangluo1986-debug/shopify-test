import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_first_draft_audit"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_first_draft_audit"

SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
SOURCE_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.html"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_first_draft_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_first_draft_audit.html"

SUCCESS_STATUS = "first_trustpilot_gmail_draft_audit_passed"
SUCCESSFUL_SOURCE_STATUSES = {
    "gmail_one_draft_created_locked_runner",
    "gmail_draft_created",
    "one_gmail_draft_created",
}
ALLOWED_REPORT_EMAILS = {"info@kidstoylover.com"}
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


def run_shopify_review_request_trustpilot_gmail_first_draft_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error = _read_source_report()
    source_json_text = _read_text(SOURCE_JSON_PATH)
    source_html_text = _read_text(SOURCE_HTML_PATH)
    source_privacy_scan = {
        "json": _privacy_scan_text(source_json_text),
        "html": _privacy_scan_text(source_html_text),
    }
    blocking_conditions = _blocking_conditions(source_report, source_error, source_privacy_scan)
    audit_status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        source_report=source_report,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        blocking_conditions=blocking_conditions,
        audit_status=audit_status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_report() -> tuple[dict, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "blocked_missing_one_draft_report"
    try:
        return json.loads(SOURCE_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_missing_one_draft_report: source JSON parse failed: {exc}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _blocking_conditions(source_report: dict, source_error: str, source_privacy_scan: dict) -> list[dict]:
    conditions = []
    if source_error:
        return [{"status": "blocked_missing_one_draft_report", "detail": _sanitize_text(source_error)}]

    source_status = source_report.get("one_draft_status")
    if source_status not in SUCCESSFUL_SOURCE_STATUSES or source_report.get("gmail_draft_created") is not True:
        conditions.append(
            {
                "status": "blocked_one_draft_not_created",
                "detail": f"source one_draft_status={_safe_text(source_status)}",
            }
        )
    if int(source_report.get("gmail_drafts_created_count") or 0) != 1:
        conditions.append(
            {
                "status": "blocked_unexpected_draft_count",
                "detail": f"source gmail_drafts_created_count={int(source_report.get('gmail_drafts_created_count') or 0)}",
            }
        )
    if not _safe_text(source_report.get("selected_order_name", "")):
        conditions.append({"status": "blocked_one_draft_not_created", "detail": "selected_order_name missing"})
    if not _is_masked_email(source_report.get("selected_masked_email", "")):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected_masked_email is missing or not masked"})
    if source_report.get("raw_email_lookup_attempted") is not True or source_report.get("raw_email_available") is not True:
        conditions.append({"status": "blocked_missing_one_draft_report", "detail": "protected raw email lookup was not confirmed"})
    if source_report.get("raw_email_source") != "protected_runtime_lookup":
        conditions.append({"status": "blocked_missing_one_draft_report", "detail": "unexpected raw email source"})
    if source_report.get("privacy_assertion_passed") is not True:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source privacy_assertion_passed is not true"})
    if source_report.get("raw_email_leak_risk_detected") is True:
        conditions.append({"status": "blocked_raw_email_leak_risk", "detail": "source raw_email_leak_risk_detected is true"})
    if source_report.get("gmail_token_refresh_succeeded") is not True:
        conditions.append({"status": "blocked_one_draft_not_created", "detail": "Gmail token refresh did not succeed"})
    if source_report.get("gmail_api_call_performed") is not True or source_report.get("gmail_draft_create_attempted") is not True:
        conditions.append({"status": "blocked_one_draft_not_created", "detail": "Gmail draft create was not attempted"})

    send_flags = ["gmail_drafts_send_called", "gmail_messages_send_called", "gmail_send_performed", "email_sent"]
    if any(source_report.get(flag) is True for flag in send_flags):
        conditions.append({"status": "blocked_send_flag_detected", "detail": "source send flag was true"})
    shopify_write_flags = ["shopify_write_performed", "mutation_performed", "tags_add_performed", "tags_remove_performed"]
    if any(source_report.get(flag) is True for flag in shopify_write_flags):
        conditions.append({"status": "blocked_shopify_write_flag_detected", "detail": "source Shopify write flag was true"})
    kudosi_flags = ["kudosi_api_call_performed", "kudosi_write_api_call_performed", "kudosi_review_request_send_performed"]
    if any(source_report.get(flag) is True for flag in kudosi_flags):
        conditions.append({"status": "blocked_kudosi_flag_detected", "detail": "source Kudosi flag was true"})

    if not SOURCE_HTML_PATH.exists():
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source HTML report missing"})
    if _privacy_scan_failed(source_privacy_scan):
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source JSON/HTML privacy scan failed"})
    return conditions


def _build_payload(
    source_report: dict,
    source_error: str,
    source_privacy_scan: dict,
    blocking_conditions: list[dict],
    audit_status: str,
    duration_seconds: float,
) -> dict:
    safety = _audit_task_safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.12",
        "mode": "read-only-first-trustpilot-gmail-draft-audit",
        "command_label": COMMAND_LABEL,
        "first_draft_audit_status": audit_status,
        "success": audit_status == SUCCESS_STATUS,
        "source_report_used": {
            "json_path": str(SOURCE_JSON_PATH),
            "html_path": str(SOURCE_HTML_PATH),
            "json_exists": SOURCE_JSON_PATH.exists(),
            "html_exists": SOURCE_HTML_PATH.exists(),
            "source_error_sanitized": _sanitize_text(source_error),
        },
        "source_one_draft_status": _safe_text(source_report.get("one_draft_status", "")),
        "source_phase": _safe_text(source_report.get("phase", "")),
        "selected_order_name": _safe_text(source_report.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_report.get("selected_masked_email", "")),
        "source_gmail_draft_id_present": bool(source_report.get("gmail_draft_id")),
        "source_gmail_draft_id_partial": _partial_id(source_report.get("gmail_draft_id", "")),
        "raw_email_lookup_attempted": bool(source_report.get("raw_email_lookup_attempted")),
        "raw_email_available": bool(source_report.get("raw_email_available")),
        "raw_email_source": _safe_text(source_report.get("raw_email_source", "")),
        "successful_fallback_query_label": _safe_text(source_report.get("successful_fallback_query_label", "")),
        "privacy_assertion_passed": source_report.get("privacy_assertion_passed") is True,
        "raw_email_leak_risk_detected": source_report.get("raw_email_leak_risk_detected") is True,
        "source_gmail_token_refresh_succeeded": source_report.get("gmail_token_refresh_succeeded") is True,
        "source_gmail_api_call_performed": source_report.get("gmail_api_call_performed") is True,
        "source_gmail_draft_create_attempted": source_report.get("gmail_draft_create_attempted") is True,
        "source_gmail_draft_created": source_report.get("gmail_draft_created") is True,
        "source_gmail_drafts_created_count": int(source_report.get("gmail_drafts_created_count") or 0),
        "source_no_send_no_write_flags": {
            "gmail_drafts_send_called": bool(source_report.get("gmail_drafts_send_called")),
            "gmail_messages_send_called": bool(source_report.get("gmail_messages_send_called")),
            "gmail_send_performed": bool(source_report.get("gmail_send_performed")),
            "email_sent": bool(source_report.get("email_sent")),
            "shopify_write_performed": bool(source_report.get("shopify_write_performed")),
            "mutation_performed": bool(source_report.get("mutation_performed")),
            "tags_add_performed": bool(source_report.get("tags_add_performed")),
            "tags_remove_performed": bool(source_report.get("tags_remove_performed")),
            "kudosi_api_call_performed": bool(source_report.get("kudosi_api_call_performed")),
        },
        "source_privacy_scan": source_privacy_scan,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "audit_task_safety_summary": safety,
        **safety,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_gmail_first_draft_audit_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_first_draft_audit_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(audit_status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _audit_task_safety_summary() -> dict:
    return {
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
        "gmail_api_call_performed": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "no_new_shopify_writes_performed": True,
        "no_new_gmail_actions_performed": True,
        "no_new_external_api_calls_performed": True,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_first_draft_audit_path": str(json_path),
        "html_trustpilot_gmail_first_draft_audit_path": str(html_path),
        "first_draft_audit_status": payload["first_draft_audit_status"],
        "blocking_condition_count": payload["blocking_condition_count"],
        "blocking_conditions": payload["blocking_conditions"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "source_gmail_drafts_created_count": payload["source_gmail_drafts_created_count"],
        "raw_email_lookup_attempted": payload["raw_email_lookup_attempted"],
        "raw_email_available": payload["raw_email_available"],
        "successful_fallback_query_label": payload["successful_fallback_query_label"],
        "privacy_assertion_passed": payload["privacy_assertion_passed"],
        "source_json_raw_customer_email_count": payload["source_privacy_scan"]["json"]["raw_customer_email_count"],
        "source_html_raw_customer_email_count": payload["source_privacy_scan"]["html"]["raw_customer_email_count"],
        "source_json_token_secret_pattern_count": payload["source_privacy_scan"]["json"]["token_secret_bearer_pattern_count"],
        "source_html_token_secret_pattern_count": payload["source_privacy_scan"]["html"]["token_secret_bearer_pattern_count"],
        **payload["audit_task_safety_summary"],
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
        for key, value in payload["audit_task_safety_summary"].items()
    )
    privacy_json = payload["source_privacy_scan"]["json"]
    privacy_html = payload["source_privacy_scan"]["html"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail First Draft Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .safe {{ border-left: 4px solid #15803d; background: #f0fdf4; padding: 10px 12px; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Gmail First Draft Audit</h1>
  <p class="{'safe' if payload['success'] else 'warning'}">Phase 3.12 is report-only. It did not call Gmail, Shopify, Kudosi, or send email.</p>
  <p>Status: <strong>{escape(payload["first_draft_audit_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Successful fallback query: <code>{escape(payload["successful_fallback_query_label"])}</code></p>
  <h2>Source Privacy Scan</h2>
  <table><tbody>
    <tr><th>JSON raw customer email count</th><td>{privacy_json["raw_customer_email_count"]}</td></tr>
    <tr><th>HTML raw customer email count</th><td>{privacy_html["raw_customer_email_count"]}</td></tr>
    <tr><th>JSON token/secret/Bearer pattern count</th><td>{privacy_json["token_secret_bearer_pattern_count"]}</td></tr>
    <tr><th>HTML token/secret/Bearer pattern count</th><td>{privacy_html["token_secret_bearer_pattern_count"]}</td></tr>
  </tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>This Audit Task Safety</h2>
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
        payload["first_draft_audit_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "audit report self privacy scan failed"}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
        payload["detected_issue_summary"] = _issue_summary(payload["first_draft_audit_status"], payload["blocking_conditions"])
    return payload


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


def _partial_id(value) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if len(text) <= 10:
        return "[present]"
    return f"{text[:4]}...{text[-4:]}"


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


def _issue_summary(audit_status: str, blocking_conditions: list[dict]) -> str:
    if audit_status == SUCCESS_STATUS:
        return "First Trustpilot Gmail draft audit passed; this task performed no Gmail, Shopify, Kudosi, or send/write action."
    return "First Trustpilot Gmail draft audit blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.12 first Trustpilot Gmail draft audit finished.\n"
        f"Status: {payload.get('first_draft_audit_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Source Gmail drafts created: {payload.get('source_gmail_drafts_created_count')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: this audit did not call Gmail, Shopify, Kudosi, send email, or write tags.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
