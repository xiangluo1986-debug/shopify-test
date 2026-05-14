import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight"
COMMAND_LABEL = "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight"

SOURCE_DRAFT_CREATE_REPORT_PATH = "logs/shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute.json"
SOURCE_DRAFT_CREATE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight.html"

SUCCESS_STATUS = "trustpilot_one_candidate_gmail_draft_send_preflight_passed"
EXPECTED_SOURCE_TASK = "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute"
EXPECTED_SOURCE_STATUS = "real_gmail_draft_created_and_verified"
EXPECTED_ORDER_NAME = "#22620"

ALLOWED_REPORT_EMAILS = {"info@kidstoylover.com"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
DRAFT_ID_PARTIAL_RE = re.compile(r"^[A-Za-z0-9_-]{1,12}\.\.\.[A-Za-z0-9_-]{1,12}$")
SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"shpat_[A-Za-z0-9_]+"),
    re.compile(r"(?i)access[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)refresh[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)client[_\s-]?secret\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)api[_\s-]?key\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)password\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{8,}"),
]

SOURCE_SEND_WRITE_BLOCK_FLAGS = (
    "gmail_drafts_send_called",
    "gmail_messages_send_called",
    "gmail_send_performed",
    "email_sent",
    "shopify_write_performed",
    "mutation_performed",
    "tags_add_performed",
    "tags_remove_performed",
    "tagsAdd_performed",
    "tagsRemove_performed",
    "trustpilot_api_call_performed",
    "kudosi_api_call_performed",
    "kudosi_write_api_call_performed",
    "kudosi_review_request_send_performed",
    "ali_reviews_api_call_performed",
    "tracking_redirect_enabled",
    "tracking_token_generated",
)


def run_shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error, source_text = _read_source_report()
    source_privacy_scan = _privacy_scan_text(source_text)
    source_summary = _source_summary(source_report, source_error)
    source_safety = _source_safety_summary(source_report)
    blocking_conditions = _blocking_conditions(
        source_report=source_report,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        source_summary=source_summary,
        source_safety=source_safety,
        source_text=source_text,
    )
    status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        status=status,
        source_summary=source_summary,
        source_privacy_scan=source_privacy_scan,
        source_safety=source_safety,
        blocking_conditions=blocking_conditions,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_report() -> tuple[dict, str, str]:
    if not SOURCE_DRAFT_CREATE_JSON_PATH.exists():
        return {}, "blocked_missing_source_draft_create_report", ""
    text = SOURCE_DRAFT_CREATE_JSON_PATH.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(text), "", text
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_invalid_source_draft_create_json: {exc}"), text


def _source_summary(source_report: dict, source_error: str) -> dict:
    return {
        "path": SOURCE_DRAFT_CREATE_REPORT_PATH,
        "present": SOURCE_DRAFT_CREATE_JSON_PATH.exists(),
        "error_sanitized": _sanitize_text(source_error),
        "task_name": _safe_text(source_report.get("task_name", "")),
        "phase": _safe_text(source_report.get("phase", "")),
        "success": source_report.get("success") is True,
        "source_draft_create_status": _safe_text(
            source_report.get("one_candidate_gmail_draft_create_execute_status", "")
        ),
        "selected_order_name": _safe_text(source_report.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_report.get("selected_masked_email", "")),
        "gmail_draft_created": source_report.get("gmail_draft_created") is True,
        "gmail_drafts_created_count": _safe_int(source_report.get("gmail_drafts_created_count")),
        "gmail_draft_id_partial": _safe_draft_id_partial(source_report.get("gmail_draft_id_partial", "")),
        "gmail_draft_id_partial_looks_masked": _is_draft_id_partial(source_report.get("gmail_draft_id_partial", "")),
        "gmail_draft_verified": source_report.get("gmail_draft_verified") is True,
        "blocking_condition_count": _safe_int(source_report.get("blocking_condition_count")),
        "blocking_conditions_present": bool(source_report.get("blocking_conditions") or []),
        "source_self_raw_customer_email_count": _safe_int(
            (source_report.get("self_privacy_scan") or {}).get("raw_customer_email_count")
            if isinstance(source_report.get("self_privacy_scan"), dict)
            else 0
        ),
        "source_self_credential_pattern_count": _safe_int(
            (source_report.get("self_privacy_scan") or {}).get("credential_pattern_count")
            if isinstance(source_report.get("self_privacy_scan"), dict)
            else 0
        ),
    }


def _source_safety_summary(source_report: dict) -> dict:
    flags = {key: source_report.get(key) is True for key in SOURCE_SEND_WRITE_BLOCK_FLAGS}
    return {
        "source_send_write_block_flags": flags,
        "source_send_write_block_flag_names": [key for key, value in flags.items() if value],
    }


def _blocking_conditions(
    source_report: dict,
    source_error: str,
    source_privacy_scan: dict,
    source_summary: dict,
    source_safety: dict,
    source_text: str,
) -> list[dict]:
    if source_error:
        return [{"status": "blocked_missing_or_invalid_source_report", "detail": _sanitize_text(source_error)}]

    conditions = []
    if source_report.get("task_name") != EXPECTED_SOURCE_TASK:
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source task name mismatch."})
    if source_summary["success"] is not True:
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source success is not true."})
    if source_summary["source_draft_create_status"] != EXPECTED_SOURCE_STATUS:
        conditions.append(
            {"status": "blocked_source_draft_create_status", "detail": "source draft create status is not verified."}
        )
    if source_summary["selected_order_name"] != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_selected_order_mismatch", "detail": "selected order must be #22620."})
    if not _is_masked_email(source_summary["selected_masked_email"]):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected email is not masked."})
    if source_summary["gmail_draft_created"] is not True:
        conditions.append({"status": "blocked_source_draft_not_created", "detail": "gmail_draft_created is not true."})
    if source_summary["gmail_drafts_created_count"] != 1:
        conditions.append({"status": "blocked_source_draft_count_not_one", "detail": "gmail_drafts_created_count must be 1."})
    if not source_summary["gmail_draft_verified"]:
        conditions.append({"status": "blocked_source_draft_not_verified", "detail": "gmail_draft_verified is not true."})
    if not source_summary["gmail_draft_id_partial"]:
        conditions.append({"status": "blocked_missing_draft_id_partial", "detail": "gmail_draft_id_partial is missing."})
    elif not source_summary["gmail_draft_id_partial_looks_masked"]:
        conditions.append(
            {"status": "blocked_full_draft_id_leak_risk", "detail": "gmail draft id must be partial only."}
        )
    if source_summary["blocking_condition_count"] != 0 or source_summary["blocking_conditions_present"]:
        conditions.append({"status": "blocked_source_has_blocking_conditions", "detail": "source report has blockers."})
    if source_safety["source_send_write_block_flag_names"]:
        conditions.append(
            {
                "status": "blocked_source_send_write_or_tracking_flag_detected",
                "detail": "source report has Gmail send, Shopify write, external review API, or tracking flags.",
            }
        )
    if source_privacy_scan["raw_customer_email_count"]:
        conditions.append({"status": "blocked_source_raw_customer_email_detected", "detail": "source report contains raw email."})
    if source_privacy_scan["token_secret_bearer_pattern_count"]:
        conditions.append({"status": "blocked_source_token_or_secret_detected", "detail": "source report contains token-like text."})
    if source_summary["source_self_raw_customer_email_count"]:
        conditions.append(
            {"status": "blocked_source_raw_customer_email_detected", "detail": "source self-scan raw-email count is not zero."}
        )
    if source_summary["source_self_credential_pattern_count"]:
        conditions.append(
            {"status": "blocked_source_token_or_secret_detected", "detail": "source self-scan token count is not zero."}
        )
    if _full_draft_id_leak_risk(source_text):
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "source report contains a full draft id field."})
    return conditions


def _build_payload(
    status: str,
    source_summary: dict,
    source_privacy_scan: dict,
    source_safety: dict,
    blocking_conditions: list[dict],
    duration_seconds: float,
) -> dict:
    success = status == SUCCESS_STATUS
    safety = _safety_summary()
    draft_created_confirmed = (
        success
        and source_summary["gmail_draft_created"]
        and source_summary["gmail_drafts_created_count"] == 1
        and source_summary["gmail_draft_verified"]
        and bool(source_summary["gmail_draft_id_partial"])
    )
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "4.7",
        "mode": "trustpilot-one-candidate-gmail-draft-send-preflight",
        "command_label": COMMAND_LABEL,
        "one_candidate_gmail_draft_send_preflight_status": status,
        "success": success,
        "source_draft_create_report_path": SOURCE_DRAFT_CREATE_REPORT_PATH,
        "source_draft_create_status": source_summary["source_draft_create_status"],
        "source_draft_create_summary": source_summary,
        "source_draft_create_safety_summary": source_safety,
        "source_draft_create_privacy_scan": source_privacy_scan,
        "selected_order_name": source_summary["selected_order_name"],
        "selected_masked_email": source_summary["selected_masked_email"],
        "gmail_draft_id_partial": source_summary["gmail_draft_id_partial"],
        "draft_created_confirmed": draft_created_confirmed,
        "would_send_gmail_draft": success,
        "would_send_count": 1 if success else 0,
        "real_gmail_send_allowed_now": False,
        "future_real_gmail_send_needs_next_phase": True,
        "send_preflight_only": True,
        "locked_send_preflight": True,
        "tracking_redirect_allowed": False,
        "tracking_token_generation_allowed": False,
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_customer_email_output": False,
            "gmail_draft_id_full_output": False,
            "gmail_access_token_output": False,
            "gmail_refresh_token_output": False,
            "gmail_client_secret_output": False,
            "bearer_value_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
        },
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "safety_summary": safety,
        **safety,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_one_candidate_gmail_draft_send_preflight_path": str(REPORT_JSON_PATH),
        "html_trustpilot_one_candidate_gmail_draft_send_preflight_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary() -> dict:
    return {
        "gmail_api_call_performed": False,
        "gmail_draft_send_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "read_only_shopify_query_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "no_gmail_send_performed": True,
        "no_new_gmail_send_performed": True,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "no_external_review_api_calls_performed": True,
        "no_tracking_action_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_one_candidate_gmail_draft_send_preflight_path": str(json_path),
        "html_trustpilot_one_candidate_gmail_draft_send_preflight_path": str(html_path),
        "one_candidate_gmail_draft_send_preflight_status": payload[
            "one_candidate_gmail_draft_send_preflight_status"
        ],
        "source_draft_create_status": payload["source_draft_create_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "gmail_draft_id_partial": payload["gmail_draft_id_partial"],
        "draft_created_confirmed": payload["draft_created_confirmed"],
        "would_send_gmail_draft": payload["would_send_gmail_draft"],
        "would_send_count": payload["would_send_count"],
        "real_gmail_send_allowed_now": payload["real_gmail_send_allowed_now"],
        "future_real_gmail_send_needs_next_phase": payload["future_real_gmail_send_needs_next_phase"],
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
    source_scan = payload["source_draft_create_privacy_scan"]
    self_scan = payload["self_privacy_scan"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot One-Candidate Gmail Draft Send Preflight</title>
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
  <h1>Trustpilot One-Candidate Gmail Draft Send Preflight</h1>
  <p class="{'safe' if payload['success'] else 'warning'}">Phase 4.7 is locked preflight only. It does not send the Gmail draft, write Shopify tags, call external review APIs, or add tracking.</p>
  <p>Status: <strong>{escape(payload["one_candidate_gmail_draft_send_preflight_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source draft create report: <code>{escape(payload["source_draft_create_report_path"])}</code></p>
  <p>Source draft create status: <strong>{escape(payload["source_draft_create_status"])}</strong></p>
  <p>Gmail draft id partial: <code>{escape(payload["gmail_draft_id_partial"])}</code></p>
  <h2>Preflight Decision</h2>
  <table><tbody>
    <tr><th>Draft created confirmed</th><td>{escape(str(payload["draft_created_confirmed"]))}</td></tr>
    <tr><th>Would send Gmail draft</th><td>{escape(str(payload["would_send_gmail_draft"]))}</td></tr>
    <tr><th>Would send count</th><td>{escape(str(payload["would_send_count"]))}</td></tr>
    <tr><th>Real Gmail send allowed now</th><td>{escape(str(payload["real_gmail_send_allowed_now"]))}</td></tr>
    <tr><th>Future real Gmail send needs next phase</th><td>{escape(str(payload["future_real_gmail_send_needs_next_phase"]))}</td></tr>
  </tbody></table>
  <h2>Privacy Scan</h2>
  <table><tbody>
    <tr><th>Source raw customer email count</th><td>{source_scan["raw_customer_email_count"]}</td></tr>
    <tr><th>Source token-like value count</th><td>{source_scan["token_secret_bearer_pattern_count"]}</td></tr>
    <tr><th>Report raw customer email count</th><td>{self_scan["raw_customer_email_count"]}</td></tr>
    <tr><th>Report token-like value count</th><td>{self_scan["token_secret_bearer_pattern_count"]}</td></tr>
  </tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if not self_scan["raw_customer_email_count"] and not self_scan["token_secret_bearer_pattern_count"]:
        return payload

    payload["one_candidate_gmail_draft_send_preflight_status"] = "blocked_privacy_scan_failed"
    payload["success"] = False
    payload["draft_created_confirmed"] = False
    payload["would_send_gmail_draft"] = False
    payload["would_send_count"] = 0
    payload["real_gmail_send_allowed_now"] = False
    payload["blocking_conditions"].append(
        {"status": "blocked_privacy_scan_failed", "detail": "Phase 4.7 report self privacy scan failed."}
    )
    payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    payload["detected_issue_summary"] = _issue_summary(
        payload["one_candidate_gmail_draft_send_preflight_status"],
        payload["blocking_conditions"],
    )
    return payload


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


def _full_draft_id_leak_risk(text: str) -> bool:
    return bool(re.search(r'"gmail_draft_id"\s*:', text or ""))


def _is_draft_id_partial(value) -> bool:
    return bool(DRAFT_ID_PARTIAL_RE.fullmatch(str(value or "").strip()))


def _safe_draft_id_partial(value) -> str:
    text = _safe_text(value).strip()
    if not text:
        return ""
    if _is_draft_id_partial(text):
        return text
    if len(text) <= 10:
        return "[present]"
    return f"{text[:4]}...{text[-4:]}"


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


def _safe_text(value) -> str:
    return _sanitize_text(str(value or ""))


def _sanitize_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _issue_summary(status: str, blocking_conditions: list[dict]) -> str:
    if status == SUCCESS_STATUS:
        return (
            "Phase 4.7 send preflight passed for selected order #22620; the existing Gmail draft would be "
            "eligible for a later separate send phase, but this task performed no send, Shopify write, external "
            "review API call, or tracking action."
        )
    return "Phase 4.7 Gmail draft send preflight blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 4.7 Trustpilot one-candidate Gmail draft send preflight finished.\n"
        f"Status: {payload.get('one_candidate_gmail_draft_send_preflight_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Source draft create status: {payload.get('source_draft_create_status')}\n"
        f"Draft created confirmed: {payload.get('draft_created_confirmed')}\n"
        f"Would send Gmail draft: {payload.get('would_send_gmail_draft')}\n"
        f"Would send count: {payload.get('would_send_count')}\n"
        f"Real Gmail send allowed now: {payload.get('real_gmail_send_allowed_now')}\n"
        f"Future real Gmail send needs next phase: {payload.get('future_real_gmail_send_needs_next_phase')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail send API call, no email sent, no Shopify write/tagsAdd/tagsRemove, no external review API call, and no tracking action.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
