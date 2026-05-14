import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_send_audit"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_send_audit"

SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.json"
SOURCE_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.html"
PROTECTED_DRAFT_SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.html"

SUCCESS_STATUS = "trustpilot_gmail_one_draft_send_audit_passed"
EXPECTED_SOURCE_STATUS = "one_gmail_draft_sent_and_needs_send_audit"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
FUTURE_TAG_TO_ADD = "1: trustpilot"
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


def run_shopify_review_request_trustpilot_gmail_send_audit_task(mode: str) -> dict:
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
    full_draft_id_leak = _full_draft_id_leak_detected(source_json_text, source_html_text)
    blocking_conditions = _blocking_conditions(source_report, source_error, source_privacy_scan, full_draft_id_leak)
    audit_status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        source_report=source_report,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        blocking_conditions=blocking_conditions,
        audit_status=audit_status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_report() -> tuple[dict, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "blocked_missing_send_execute_report"
    try:
        return json.loads(SOURCE_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_missing_send_execute_report: source JSON parse failed: {exc}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _blocking_conditions(source: dict, source_error: str, source_privacy_scan: dict, full_draft_id_leak_detected: bool) -> list[dict]:
    conditions = []
    if source_error:
        return [{"status": "blocked_missing_send_execute_report", "detail": _sanitize_text(source_error)}]

    if source.get("one_draft_send_execute_status") != EXPECTED_SOURCE_STATUS:
        conditions.append({"status": "blocked_source_send_not_successful", "detail": "source send status is not successful."})
    if source.get("mode") != "real-run":
        conditions.append({"status": "blocked_source_not_real_run", "detail": "source mode is not real-run."})
    if source.get("dry_run") is not False:
        conditions.append({"status": "blocked_source_dry_run", "detail": "source dry_run is not false."})
    if source.get("real_send_allowed") is not True:
        conditions.append({"status": "blocked_source_send_not_successful", "detail": "source real_send_allowed is not true."})
    if _safe_text(source.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_source_send_not_successful", "detail": "selected_order_name mismatch."})
    if _safe_text(source.get("selected_masked_email", "")) != EXPECTED_MASKED_EMAIL:
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected_masked_email mismatch."})
    if not _is_masked_email(source.get("selected_masked_email", "")):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected_masked_email is not masked."})
    if _safe_text(source.get("source_gmail_draft_id_partial", "")) != EXPECTED_DRAFT_ID_PARTIAL:
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "source Gmail draft id partial mismatch."})

    if int(source.get("sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": f"source sent_count={int(source.get('sent_count') or 0)}"})
    if source.get("gmail_drafts_send_called") is not True:
        conditions.append({"status": "blocked_missing_drafts_send", "detail": "Gmail drafts.send was not confirmed."})
    if source.get("gmail_messages_send_called") is True:
        conditions.append({"status": "blocked_messages_send_detected", "detail": "Gmail messages.send flag was true."})
    if source.get("gmail_send_performed") is not True or source.get("email_sent") is not True:
        conditions.append({"status": "blocked_email_not_sent", "detail": "email_sent/gmail_send_performed was not true."})
    if source.get("gmail_draft_created") is True or source.get("gmail_draft_create_attempted") is True:
        conditions.append({"status": "blocked_source_send_not_successful", "detail": "source indicates a new draft was created or attempted during send."})

    if source.get("shopify_api_call_performed") is True or source.get("shopify_write_performed") is True or source.get("mutation_performed") is True:
        conditions.append({"status": "blocked_shopify_write_detected", "detail": "source Shopify API/write/mutation flag was true."})
    if any(source.get(flag) is True for flag in ("tags_add_performed", "tags_remove_performed", "tagsAdd_performed", "tagsRemove_performed")):
        conditions.append({"status": "blocked_tag_write_detected", "detail": "source tag write flag was true."})
    if source.get("kudosi_api_call_performed") is True or source.get("ali_reviews_api_call_performed") is True:
        conditions.append({"status": "blocked_kudosi_or_ali_reviews_detected", "detail": "source Kudosi/Ali Reviews flag was true."})
    if source.get("blocking_condition_count") not in (0, None):
        conditions.append({"status": "blocked_source_send_not_successful", "detail": "source blocking_condition_count is not zero."})

    if not SOURCE_HTML_PATH.exists():
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source HTML report is missing."})
    if _privacy_scan_failed(source_privacy_scan):
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source JSON/HTML privacy scan failed."})
    if full_draft_id_leak_detected:
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "full Gmail draft id was detected in source JSON/HTML."})
    return conditions


def _build_payload(
    source_report: dict,
    source_error: str,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    blocking_conditions: list[dict],
    audit_status: str,
    duration_seconds: float,
) -> dict:
    success = audit_status == SUCCESS_STATUS
    safety = _audit_task_safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.17",
        "mode": "read-only-trustpilot-gmail-send-audit",
        "command_label": COMMAND_LABEL,
        "send_audit_status": audit_status,
        "success": success,
        "source_report_used": {
            "json_path": str(SOURCE_JSON_PATH),
            "html_path": str(SOURCE_HTML_PATH),
            "json_exists": SOURCE_JSON_PATH.exists(),
            "html_exists": SOURCE_HTML_PATH.exists(),
            "source_error_sanitized": _sanitize_text(source_error),
        },
        "source_one_draft_send_execute_status": _safe_text(source_report.get("one_draft_send_execute_status", "")),
        "source_mode": _safe_text(source_report.get("mode", "")),
        "source_dry_run": source_report.get("dry_run") is True,
        "source_real_send_allowed": source_report.get("real_send_allowed") is True,
        "selected_order_name": _safe_text(source_report.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_report.get("selected_masked_email", "")),
        "source_gmail_draft_id_partial": _safe_text(source_report.get("source_gmail_draft_id_partial", "")),
        "sent_count": int(source_report.get("sent_count") or 0),
        "gmail_drafts_send_confirmed": source_report.get("gmail_drafts_send_called") is True,
        "gmail_messages_send_confirmed_false": source_report.get("gmail_messages_send_called") is False,
        "email_sent_confirmed": source_report.get("email_sent") is True and source_report.get("gmail_send_performed") is True,
        "shopify_write_confirmed_false": not any(
            source_report.get(flag) is True
            for flag in ("shopify_api_call_performed", "shopify_write_performed", "mutation_performed")
        ),
        "tag_write_confirmed_false": not any(
            source_report.get(flag) is True
            for flag in ("tags_add_performed", "tags_remove_performed", "tagsAdd_performed", "tagsRemove_performed")
        ),
        "kudosi_ali_confirmed_false": not any(
            source_report.get(flag) is True
            for flag in ("kudosi_api_call_performed", "ali_reviews_api_call_performed")
        ),
        "privacy_scan_passed": not _privacy_scan_failed(source_privacy_scan) and not full_draft_id_leak_detected,
        "source_full_draft_id_leak_detected": full_draft_id_leak_detected,
        "ready_for_next_phase_shopify_tag_write_design": success,
        "shopify_tag_write_performed_now": False,
        "future_tag_to_add": FUTURE_TAG_TO_ADD,
        "source_send_flags": {
            "gmail_api_call_performed": source_report.get("gmail_api_call_performed") is True,
            "gmail_drafts_send_called": source_report.get("gmail_drafts_send_called") is True,
            "gmail_messages_send_called": source_report.get("gmail_messages_send_called") is True,
            "gmail_send_performed": source_report.get("gmail_send_performed") is True,
            "email_sent": source_report.get("email_sent") is True,
        },
        "source_no_write_flags": {
            "shopify_api_call_performed": source_report.get("shopify_api_call_performed") is True,
            "shopify_write_performed": source_report.get("shopify_write_performed") is True,
            "mutation_performed": source_report.get("mutation_performed") is True,
            "tags_add_performed": source_report.get("tags_add_performed") is True,
            "tags_remove_performed": source_report.get("tags_remove_performed") is True,
            "kudosi_api_call_performed": source_report.get("kudosi_api_call_performed") is True,
            "ali_reviews_api_call_performed": source_report.get("ali_reviews_api_call_performed") is True,
        },
        "source_privacy_scan": source_privacy_scan,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "audit_task_safety_summary": safety,
        **safety,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_gmail_send_audit_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_send_audit_path": str(REPORT_HTML_PATH),
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
        "shopify_tag_write_performed_now": False,
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
        "json_trustpilot_gmail_send_audit_path": str(json_path),
        "html_trustpilot_gmail_send_audit_path": str(html_path),
        "send_audit_status": payload["send_audit_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "sent_count": payload["sent_count"],
        "gmail_drafts_send_confirmed": payload["gmail_drafts_send_confirmed"],
        "gmail_messages_send_confirmed_false": payload["gmail_messages_send_confirmed_false"],
        "email_sent_confirmed": payload["email_sent_confirmed"],
        "shopify_write_confirmed_false": payload["shopify_write_confirmed_false"],
        "tag_write_confirmed_false": payload["tag_write_confirmed_false"],
        "kudosi_ali_confirmed_false": payload["kudosi_ali_confirmed_false"],
        "privacy_scan_passed": payload["privacy_scan_passed"],
        "ready_for_next_phase_shopify_tag_write_design": payload["ready_for_next_phase_shopify_tag_write_design"],
        "blocking_condition_count": payload["blocking_condition_count"],
        "blocking_conditions": payload["blocking_conditions"],
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
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Send Audit</title>
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
  <h1>Trustpilot Gmail Send Audit</h1>
  <p class="warning">Phase 3.17 is read/report-only. It does not call Gmail, Shopify, Kudosi, or Ali Reviews.</p>
  <p>Status: <strong>{escape(payload["send_audit_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Sent count: <strong>{escape(str(payload["sent_count"]))}</strong></p>
  <p>Gmail drafts.send confirmed: <strong>{escape(str(payload["gmail_drafts_send_confirmed"]))}</strong></p>
  <p>Gmail messages.send confirmed false: <strong>{escape(str(payload["gmail_messages_send_confirmed_false"]))}</strong></p>
  <p>Email sent confirmed: <strong>{escape(str(payload["email_sent_confirmed"]))}</strong></p>
  <p>Ready for next phase Shopify tag-write design: <strong>{escape(str(payload["ready_for_next_phase_shopify_tag_write_design"]))}</strong></p>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>This Audit Task Safety Flags</h2>
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


def _full_draft_id_leak_detected(*texts: str) -> bool:
    if not PROTECTED_DRAFT_SOURCE_JSON_PATH.exists():
        return False
    try:
        source = json.loads(PROTECTED_DRAFT_SOURCE_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    draft_id = str(source.get("gmail_draft_id") or "").strip()
    if not draft_id:
        return False
    return any(draft_id in (text or "") for text in texts)


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["send_audit_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["privacy_scan_passed"] = False
        payload["ready_for_next_phase_shopify_tag_write_design"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "send audit self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    return payload


def _is_masked_email(value) -> bool:
    text = str(value or "")
    return bool(text and "@" in text and "***" in text and not EMAIL_RE.fullmatch(text))


def _safe_masked_email(value) -> str:
    text = _safe_text(value)
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
    if status == SUCCESS_STATUS:
        return "Trustpilot Gmail one-draft send audit passed; next phase may design Shopify tag write without writing yet."
    return "Trustpilot Gmail send audit blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.17 Trustpilot Gmail send audit finished.\n"
        f"Status: {payload.get('send_audit_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Sent count: {payload.get('sent_count')}\n"
        f"Gmail drafts.send confirmed: {payload.get('gmail_drafts_send_confirmed')}\n"
        f"Gmail messages.send confirmed false: {payload.get('gmail_messages_send_confirmed_false')}\n"
        f"Ready for next phase tag-write design: {payload.get('ready_for_next_phase_shopify_tag_write_design')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: this audit task made no Gmail, Shopify, Kudosi, or Ali Reviews API calls.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
