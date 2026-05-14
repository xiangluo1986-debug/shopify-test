import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_customer_level_duplicate_suppression import (
    CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
    build_customer_level_duplicate_context,
    compare_order_customer_identity,
    evaluate_customer_level_duplicate,
    public_context_summary,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_customer_level_trustpilot_duplicate_audit"
COMMAND_LABEL = "shopify_review_request_customer_level_trustpilot_duplicate_audit_local_db_and_reports_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_customer_level_trustpilot_duplicate_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_customer_level_trustpilot_duplicate_audit.html"

SUCCESS_STATUS = "customer_level_duplicate_audit_completed"
AUDIT_ORDER_A = "#22620"
AUDIT_ORDER_B = "#22621"
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
    re.compile(r"(?i)api[_\s-]?key\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)password\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{8,}"),
]


def run_shopify_review_request_customer_level_trustpilot_duplicate_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    context = build_customer_level_duplicate_context([AUDIT_ORDER_A, AUDIT_ORDER_B])
    pair_audit = compare_order_customer_identity(AUDIT_ORDER_A, AUDIT_ORDER_B, context)
    duplicate_audit = evaluate_customer_level_duplicate(
        AUDIT_ORDER_A,
        pair_audit["order_a_identity"].get("masked_email", ""),
        context,
    )
    payload = _build_payload(
        context=context,
        pair_audit=pair_audit,
        duplicate_audit=duplicate_audit,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _build_payload(context: dict, pair_audit: dict, duplicate_audit: dict, duration_seconds: float) -> dict:
    safety = _safety_summary()
    prior_order_name = duplicate_audit.get("prior_trustpilot_order_name", "")
    prior_for_order_b = [
        record
        for record in duplicate_audit.get("prior_trustpilot_invitation_matches", [])
        if record.get("order_name") == AUDIT_ORDER_B
    ]
    customer_level_duplicate_block_applies = duplicate_audit["customer_level_duplicate_block_applies"]
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "4.8C",
        "mode": "local-db-and-existing-reports-only",
        "command_label": COMMAND_LABEL,
        "customer_level_duplicate_audit_status": SUCCESS_STATUS,
        "success": True,
        "audit_order_a": AUDIT_ORDER_A,
        "audit_order_b": AUDIT_ORDER_B,
        "same_customer_detected": duplicate_audit["same_customer_detected"] or pair_audit["same_customer_detected"],
        "same_email_detected": duplicate_audit["same_email_detected"] or pair_audit["same_email_detected"],
        "same_masked_email_detected": duplicate_audit["same_masked_email_detected"]
        or pair_audit["same_masked_email_detected"],
        "same_customer_id_detected": duplicate_audit["same_customer_id_detected"]
        or pair_audit["same_customer_id_detected"],
        "same_customer_detection_basis": _dedupe(
            [
                *duplicate_audit.get("same_customer_detection_basis", []),
                *pair_audit.get("same_customer_detection_basis", []),
            ]
        ),
        "selected_masked_email": duplicate_audit["selected_masked_email"],
        "order_identity_a": pair_audit["order_a_identity"],
        "order_identity_b": pair_audit["order_b_identity"],
        "prior_trustpilot_invitation_detected": duplicate_audit["prior_trustpilot_invitation_detected"],
        "prior_trustpilot_order_name": prior_order_name,
        "prior_trustpilot_order_b_detected": bool(prior_for_order_b),
        "prior_trustpilot_invitation_sources": duplicate_audit["prior_trustpilot_invitation_sources"],
        "prior_trustpilot_invitation_matches": duplicate_audit["prior_trustpilot_invitation_matches"],
        "customer_level_duplicate_block_applies": customer_level_duplicate_block_applies,
        "classification": (
            CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION
            if customer_level_duplicate_block_applies
            else duplicate_audit["classification"]
        ),
        "do_not_send_order_a": customer_level_duplicate_block_applies,
        "do_not_write_shopify_tag_for_order_a": customer_level_duplicate_block_applies,
        "existing_unsent_gmail_draft_should_not_be_sent": duplicate_audit[
            "existing_unsent_gmail_draft_should_not_be_sent"
        ],
        "future_optional_draft_cleanup_needs_separate_locked_phase": duplicate_audit[
            "future_optional_draft_cleanup_needs_separate_locked_phase"
        ],
        "customer_level_duplicate_summary": public_context_summary(context),
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_customer_email_output": False,
            "email_hash_output": False,
            "gmail_draft_id_full_output": False,
            "gmail_message_id_full_output": False,
            "token_or_secret_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
        },
        "blocking_conditions": [
            {
                "status": CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
                "detail": "Order #22620 matches a prior Trustpilot invitation customer signal and must not be sent.",
            }
        ]
        if customer_level_duplicate_block_applies
        else [],
        "blocking_condition_count": 1 if customer_level_duplicate_block_applies else 0,
        "safety_summary": safety,
        **safety,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_customer_level_trustpilot_duplicate_audit_path": str(REPORT_JSON_PATH),
        "html_customer_level_trustpilot_duplicate_audit_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(customer_level_duplicate_block_applies, prior_order_name),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary() -> dict:
    return {
        "shopify_api_call_performed": False,
        "read_only_shopify_query_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "no_new_gmail_actions_performed": True,
        "no_new_external_api_calls_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "all_new_external_api_calls_confirmed_false": True,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_customer_level_trustpilot_duplicate_audit_path": str(json_path),
        "html_customer_level_trustpilot_duplicate_audit_path": str(html_path),
        "customer_level_duplicate_audit_status": payload["customer_level_duplicate_audit_status"],
        "audit_order_a": payload["audit_order_a"],
        "audit_order_b": payload["audit_order_b"],
        "same_customer_detected": payload["same_customer_detected"],
        "same_email_detected": payload["same_email_detected"],
        "same_masked_email_detected": payload["same_masked_email_detected"],
        "selected_masked_email": payload["selected_masked_email"],
        "prior_trustpilot_invitation_detected": payload["prior_trustpilot_invitation_detected"],
        "prior_trustpilot_order_name": payload["prior_trustpilot_order_name"],
        "customer_level_duplicate_block_applies": payload["customer_level_duplicate_block_applies"],
        "classification": payload["classification"],
        "existing_unsent_gmail_draft_should_not_be_sent": payload[
            "existing_unsent_gmail_draft_should_not_be_sent"
        ],
        "future_optional_draft_cleanup_needs_separate_locked_phase": payload[
            "future_optional_draft_cleanup_needs_separate_locked_phase"
        ],
        "blocking_condition_count": payload["blocking_condition_count"],
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
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    match_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(match.get('order_name', '')))}</td>"
        f"<td>{escape(str(match.get('masked_email', '')))}</td>"
        f"<td>{escape(str(match.get('source_key', '')))}</td>"
        f"<td>{escape(str(match.get('signal_type', '')))}</td>"
        f"<td>{escape(', '.join(match.get('match_basis', [])))}</td>"
        "</tr>"
        for match in payload["prior_trustpilot_invitation_matches"]
    ) or '<tr><td colspan="5">No prior Trustpilot invitation match.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Customer-Level Trustpilot Duplicate Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #b91c1c; background: #fef2f2; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Customer-Level Trustpilot Duplicate Audit</h1>
  <p class="warning">Phase 4.8C is local DB and existing-report audit only. It did not call Shopify, Gmail, Trustpilot, Kudosi, or Ali Reviews, and did not create/send/delete any Gmail draft.</p>
  <p>Status: <strong>{escape(payload["customer_level_duplicate_audit_status"])}</strong></p>
  <p>Order A: <code>{escape(payload["audit_order_a"])}</code> | Order B: <code>{escape(payload["audit_order_b"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Classification: <code>{escape(payload["classification"])}</code></p>
  <p>Block applies: <strong>{escape(str(payload["customer_level_duplicate_block_applies"]))}</strong></p>
  <p>Existing unsent Gmail draft should not be sent: <strong>{escape(str(payload["existing_unsent_gmail_draft_should_not_be_sent"]))}</strong></p>
  <h2>Identity Signals</h2>
  <table><tbody>
    <tr><th>Same customer detected</th><td>{escape(str(payload["same_customer_detected"]))}</td></tr>
    <tr><th>Same email detected</th><td>{escape(str(payload["same_email_detected"]))}</td></tr>
    <tr><th>Same masked email detected</th><td>{escape(str(payload["same_masked_email_detected"]))}</td></tr>
    <tr><th>Same customer ID detected</th><td>{escape(str(payload["same_customer_id_detected"]))}</td></tr>
    <tr><th>Detection basis</th><td>{escape(", ".join(payload["same_customer_detection_basis"]))}</td></tr>
    <tr><th>Prior Trustpilot order</th><td><code>{escape(payload["prior_trustpilot_order_name"])}</code></td></tr>
  </tbody></table>
  <h2>Prior Trustpilot Matches</h2>
  <table><thead><tr><th>Order</th><th>Masked email</th><th>Source</th><th>Signal</th><th>Match basis</th></tr></thead><tbody>{match_rows}</tbody></table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["customer_level_duplicate_audit_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "audit report self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
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
        "token_secret_bearer_pattern_count": sum(
            1 for pattern in SECRET_VALUE_PATTERNS if pattern.search(text or "")
        ),
    }


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def _issue_summary(blocked: bool, prior_order_name: str) -> str:
    if blocked:
        return (
            f"{AUDIT_ORDER_A} is blocked by customer-level Trustpilot duplicate suppression"
            f" from prior order {prior_order_name or 'unknown'}."
        )
    return f"No customer-level Trustpilot duplicate suppression match was found for {AUDIT_ORDER_A}."


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 4.8C customer-level Trustpilot duplicate audit finished.\n"
        f"Status: {payload.get('customer_level_duplicate_audit_status')}\n"
        f"Audit order A: {payload.get('audit_order_a')}\n"
        f"Audit order B: {payload.get('audit_order_b')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Prior Trustpilot order: {payload.get('prior_trustpilot_order_name')}\n"
        f"Classification: {payload.get('classification')}\n"
        f"Customer-level duplicate block applies: {payload.get('customer_level_duplicate_block_applies')}\n"
        f"Existing unsent Gmail draft should not be sent: {payload.get('existing_unsent_gmail_draft_should_not_be_sent')}\n"
        "Safety: no Gmail draft created, no Gmail send, no Shopify write/tag change, no Trustpilot/Kudosi/Ali Reviews API call, and no tracking token or redirect.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
