import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_one_candidate_gmail_draft_package"
COMMAND_LABEL = "shopify_review_request_trustpilot_one_candidate_gmail_draft_package"

SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_next_repeat_customer_candidate_scan.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_package.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_package.html"

SUCCESS_STATUS = "trustpilot_one_candidate_gmail_draft_package_ready"
EXPECTED_SOURCE_TASK = "shopify_review_request_next_repeat_customer_candidate_scan"
EXPECTED_SOURCE_STATUS = "next_repeat_customer_candidate_scan_ready"
EXPECTED_ORDER_NAME = "#22620"
EXPECTED_CANDIDATE_STATUS = "ready_next_trustpilot_repeat_customer_candidate"
TARGET_DECISION = "trustpilot_gmail_candidate_dry_run"
GMAIL_SEND_FROM = "info@kidstoylover.com"
TRUSTPILOT_LINK = "https://www.trustpilot.com/evaluate/www.kidstoylover.com"
TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]
ALLOWED_REPORT_EMAILS = {GMAIL_SEND_FROM}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
CREDENTIAL_VALUE_PATTERNS = [
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
RISK_TEXT_RE = re.compile(
    r"(?i)(refund|cancel|chargeback|dispute|complaint|shipping[_ -]?issue|delivery[_ -]?issue|return)"
)

SUBJECT = "Thank you for your support - we'd love your feedback"
BODY_TEMPLATE = """Hi there,

Thank you for choosing Kidstoylover again. If you have a moment, we would appreciate a quick review of your experience with us on Trustpilot.

{trustpilot_link}

Kind regards,
Xiang
Kidstoylover"""


def run_shopify_review_request_trustpilot_one_candidate_gmail_draft_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error, source_text = _read_source_report()
    source_privacy_scan = _privacy_scan_text(source_text)
    selected_candidate = _selected_candidate(source_report)
    source_summary = _source_summary(source_report, source_error)
    candidate_summary = _candidate_summary(selected_candidate)
    guard_summary = _guard_summary(selected_candidate)
    blocking_conditions = _blocking_conditions(
        source_report=source_report,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        selected_candidate=selected_candidate,
        source_summary=source_summary,
        candidate_summary=candidate_summary,
        guard_summary=guard_summary,
    )
    status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        status=status,
        source_summary=source_summary,
        source_privacy_scan=source_privacy_scan,
        candidate_summary=candidate_summary,
        guard_summary=guard_summary,
        blocking_conditions=blocking_conditions,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_report() -> tuple[dict, str, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "blocked_missing_source_report", ""
    text = SOURCE_JSON_PATH.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(text), "", text
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_invalid_source_report_json: {exc}"), text


def _selected_candidate(source_report: dict) -> dict:
    candidate = source_report.get("selected_candidate")
    return candidate if isinstance(candidate, dict) else {}


def _source_summary(source_report: dict, source_error: str) -> dict:
    return {
        "path": str(SOURCE_JSON_PATH),
        "present": SOURCE_JSON_PATH.exists(),
        "error_sanitized": _sanitize_text(source_error),
        "task_name": _safe_text(source_report.get("task_name", "")),
        "phase": _safe_text(source_report.get("phase", "")),
        "success": source_report.get("success") is True,
        "next_repeat_customer_candidate_scan_status": _safe_text(
            source_report.get("next_repeat_customer_candidate_scan_status", "")
        ),
        "next_candidate_selected": source_report.get("next_candidate_selected") is True,
        "next_candidate_count": _safe_int(source_report.get("next_candidate_count")),
        "candidate_selected_count": _safe_int(source_report.get("candidate_selected_count")),
        "selected_order_name": _safe_text(source_report.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_report.get("selected_masked_email", "")),
        "total_candidates_seen": _safe_int(source_report.get("total_candidates_seen")),
        "total_orders_evaluated": _safe_int(source_report.get("total_orders_evaluated")),
        "blocking_condition_count": _safe_int(source_report.get("blocking_condition_count")),
        "local_source_reports_only": source_report.get("local_source_reports_only") is True,
        "shopify_live_query_performed": source_report.get("shopify_live_query_performed") is True,
        "gmail_api_call_performed": source_report.get("gmail_api_call_performed") is True,
        "shopify_write_performed": source_report.get("shopify_write_performed") is True,
        "mutation_performed": source_report.get("mutation_performed") is True,
        "tags_add_performed": source_report.get("tags_add_performed") is True,
        "tags_remove_performed": source_report.get("tags_remove_performed") is True,
        "kudosi_api_call_performed": source_report.get("kudosi_api_call_performed") is True,
        "ali_reviews_api_call_performed": source_report.get("ali_reviews_api_call_performed") is True,
    }


def _candidate_summary(candidate: dict) -> dict:
    return {
        "order_name": _safe_text(candidate.get("order_name", "")),
        "order_id_or_gid": _safe_text(candidate.get("order_id_or_gid", "")),
        "masked_email": _safe_masked_email(candidate.get("masked_email", "")),
        "email_present": candidate.get("email_present") is True,
        "email_masking_applied": candidate.get("email_masking_applied") is not False,
        "repeat_customer_detected": candidate.get("repeat_customer_detected") is True,
        "source_decision": _safe_text(candidate.get("source_decision", "")),
        "candidate_status": _safe_text(candidate.get("candidate_status", "")),
        "classification_buckets": _safe_list(candidate.get("classification_buckets", [])),
        "tags_of_interest": _safe_list(candidate.get("tags_of_interest", [])),
        "matched_trustpilot_invitation_tags": _safe_list(
            candidate.get("matched_trustpilot_invitation_tags", [])
        ),
        "existing_trustpilot_invitation_tag_detected": (
            candidate.get("existing_trustpilot_invitation_tag_detected") is True
        ),
        "ticket_risk_detected": candidate.get("ticket_risk_detected") is True,
        "blocking_reasons": _safe_list(candidate.get("blocking_reasons", [])),
        "planned_action": _safe_text(candidate.get("planned_action", "")),
        "future_write_tag_if_later_approved": _safe_text(
            candidate.get("future_write_tag_if_later_approved", "")
        ),
        "gmail_draft_planned": candidate.get("gmail_draft_planned") is True,
        "email_send_planned": candidate.get("email_send_planned") is True,
        "shopify_tag_write_planned": candidate.get("shopify_tag_write_planned") is True,
        "kudosi_or_ali_reviews_call_planned": candidate.get("kudosi_or_ali_reviews_call_planned") is True,
    }


def _guard_summary(candidate: dict) -> dict:
    candidate_summary = _candidate_summary(candidate)
    alias_coverage = _trustpilot_alias_coverage()
    matched_aliases = _matched_trustpilot_aliases(candidate, candidate_summary)
    duplicate_detected = (
        candidate_summary["existing_trustpilot_invitation_tag_detected"]
        or bool(matched_aliases)
        or candidate_summary["source_decision"] == "blocked_existing_trustpilot_invitation_tag"
    )
    returned_triggered = _returned_package_guard_triggered(candidate_summary)
    risk_triggered = _risk_ticket_refund_cancel_dispute_blocker_detected(candidate_summary)
    repeat_confirmed = (
        candidate_summary["repeat_customer_detected"]
        and candidate_summary["candidate_status"] == EXPECTED_CANDIDATE_STATUS
        and candidate_summary["source_decision"] == TARGET_DECISION
    )
    first_order_triggered = not repeat_confirmed or "repeat_customer_not_confirmed" in candidate_summary["blocking_reasons"]
    no_real_action_planned = not any(
        candidate_summary[key]
        for key in (
            "gmail_draft_planned",
            "email_send_planned",
            "shopify_tag_write_planned",
            "kudosi_or_ali_reviews_call_planned",
        )
    )
    return {
        "repeat_customer_confirmed": repeat_confirmed,
        "duplicate_trustpilot_invitation_alias_detected": duplicate_detected,
        "duplicate_trustpilot_invitation_block_confirmed": (
            not duplicate_detected and alias_coverage["all_required_aliases_present"]
        ),
        "matched_trustpilot_invitation_tags": matched_aliases,
        "returned_package_guard_triggered": returned_triggered,
        "returned_package_guard_confirmed": not returned_triggered,
        "first_order_customer_guard_triggered": first_order_triggered,
        "first_order_customer_block_confirmed": not first_order_triggered,
        "risk_ticket_refund_cancel_dispute_blocker_detected": risk_triggered,
        "candidate_has_no_blocking_reasons": not candidate_summary["blocking_reasons"],
        "candidate_no_real_action_planned_in_source": no_real_action_planned,
        "trustpilot_tag_matching_policy": {
            "canonical_write_tag_for_future_real_write_only": TRUSTPILOT_TAG,
            "current_task_write_tag": "",
            "duplicate_detection_uses_tolerant_alias_matching": True,
            "legacy_tags_are_not_removed": True,
            **alias_coverage,
        },
    }


def _blocking_conditions(
    source_report: dict,
    source_error: str,
    source_privacy_scan: dict,
    selected_candidate: dict,
    source_summary: dict,
    candidate_summary: dict,
    guard_summary: dict,
) -> list[dict]:
    conditions = []
    if source_error:
        return [{"status": "blocked_missing_or_invalid_source_report", "detail": _sanitize_text(source_error)}]
    if source_report.get("task_name") != EXPECTED_SOURCE_TASK:
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source task name mismatch."})
    if str(source_report.get("phase")) != "4.0":
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source phase must be 4.0."})
    if source_report.get("success") is not True:
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source report success is not true."})
    if source_report.get("next_repeat_customer_candidate_scan_status") != EXPECTED_SOURCE_STATUS:
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source report status is not ready."})
    if source_report.get("next_candidate_selected") is not True:
        conditions.append({"status": "blocked_next_candidate_not_selected", "detail": "next_candidate_selected is not true."})
    if _safe_int(source_report.get("next_candidate_count")) != 1:
        conditions.append({"status": "blocked_invalid_next_candidate_count", "detail": "next_candidate_count must equal 1."})
    if source_summary["selected_order_name"] != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_selected_order_mismatch", "detail": "source selected order is not #22620."})
    if not selected_candidate:
        conditions.append({"status": "blocked_missing_selected_candidate", "detail": "selected_candidate is missing."})
    if candidate_summary["order_name"] != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_selected_order_mismatch", "detail": "candidate selected order is not #22620."})
    if not _is_masked_email(candidate_summary["masked_email"]):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "candidate email is missing or not masked."})
    if candidate_summary["candidate_status"] != EXPECTED_CANDIDATE_STATUS:
        conditions.append({"status": "blocked_candidate_not_ready", "detail": "candidate status is not ready."})
    if candidate_summary["source_decision"] != TARGET_DECISION:
        conditions.append({"status": "blocked_candidate_not_ready", "detail": "source decision is not Trustpilot draft dry-run."})
    if candidate_summary["blocking_reasons"]:
        conditions.append({"status": "blocked_candidate_has_blocking_reasons", "detail": "selected candidate has blockers."})
    if not guard_summary["repeat_customer_confirmed"]:
        conditions.append({"status": "blocked_repeat_customer_not_confirmed", "detail": "repeat customer is not confirmed."})
    if guard_summary["duplicate_trustpilot_invitation_alias_detected"]:
        conditions.append(
            {
                "status": "blocked_duplicate_trustpilot_invitation_alias_detected",
                "detail": "selected candidate already has a Trustpilot invitation alias.",
            }
        )
    if guard_summary["returned_package_guard_triggered"]:
        conditions.append({"status": "blocked_returned_package_guard_triggered", "detail": "returned package guard triggered."})
    if guard_summary["first_order_customer_guard_triggered"]:
        conditions.append({"status": "blocked_first_order_customer", "detail": "selected candidate is not confirmed repeat."})
    if guard_summary["risk_ticket_refund_cancel_dispute_blocker_detected"]:
        conditions.append(
            {
                "status": "blocked_candidate_risk_ticket_refund_cancel_dispute",
                "detail": "selected candidate has a risk, ticket, refund, cancel, return, or dispute blocker.",
            }
        )
    if not guard_summary["candidate_no_real_action_planned_in_source"]:
        conditions.append({"status": "blocked_real_action_plan_detected", "detail": "source candidate planned a real action."})
    for flag in (
        "shopify_live_query_performed",
        "gmail_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "tags_add_performed",
        "tags_remove_performed",
        "kudosi_api_call_performed",
        "ali_reviews_api_call_performed",
    ):
        if source_summary.get(flag) is True:
            conditions.append({"status": "blocked_source_real_action_detected", "detail": f"source flag {flag} was true."})
    if source_privacy_scan["raw_customer_email_count"] or source_privacy_scan["credential_pattern_count"]:
        conditions.append({"status": "blocked_source_privacy_scan_failed", "detail": "source report privacy scan failed."})
    return conditions


def _build_payload(
    status: str,
    source_summary: dict,
    source_privacy_scan: dict,
    candidate_summary: dict,
    guard_summary: dict,
    blocking_conditions: list[dict],
    duration_seconds: float,
) -> dict:
    success = status == SUCCESS_STATUS
    safety = _safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "4.1",
        "mode": "trustpilot-one-candidate-gmail-draft-package-dry-run",
        "command_label": COMMAND_LABEL,
        "one_candidate_gmail_draft_package_status": status,
        "success": success,
        "source_candidate_scan_report_path": str(SOURCE_JSON_PATH),
        "source_candidate_scan_summary": source_summary,
        "source_candidate_scan_privacy_scan": source_privacy_scan,
        "selected_order_name": candidate_summary["order_name"],
        "selected_masked_email": candidate_summary["masked_email"],
        "next_candidate_selected": source_summary["next_candidate_selected"],
        "next_candidate_count": source_summary["next_candidate_count"],
        "candidate_selected_count": source_summary["candidate_selected_count"],
        "selected_candidate_summary": candidate_summary,
        "repeat_customer_confirmed": guard_summary["repeat_customer_confirmed"],
        "duplicate_trustpilot_invitation_block_confirmed": guard_summary[
            "duplicate_trustpilot_invitation_block_confirmed"
        ],
        "duplicate_trustpilot_invitation_alias_detected": guard_summary[
            "duplicate_trustpilot_invitation_alias_detected"
        ],
        "matched_trustpilot_invitation_tags": guard_summary["matched_trustpilot_invitation_tags"],
        "returned_package_guard_confirmed": guard_summary["returned_package_guard_confirmed"],
        "returned_package_guard_triggered": guard_summary["returned_package_guard_triggered"],
        "first_order_customer_block_confirmed": guard_summary["first_order_customer_block_confirmed"],
        "first_order_customer_guard_triggered": guard_summary["first_order_customer_guard_triggered"],
        "risk_ticket_refund_cancel_dispute_blocker_detected": guard_summary[
            "risk_ticket_refund_cancel_dispute_blocker_detected"
        ],
        "candidate_has_no_blocking_reasons": guard_summary["candidate_has_no_blocking_reasons"],
        "candidate_no_real_action_planned_in_source": guard_summary["candidate_no_real_action_planned_in_source"],
        "trustpilot_tag_matching_policy": guard_summary["trustpilot_tag_matching_policy"],
        "draft_package_only": True,
        "preview_only": True,
        "gmail_draft_create_allowed_now": False,
        "gmail_send_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "trustpilot_invitation_preview": _draft_preview(candidate_summary["masked_email"]),
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_customer_email_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
            "private_customer_notes_output": False,
        },
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "raw_customer_email_would_be_written": False,
        "real_gmail_or_shopify_write_action_would_be_attempted": False,
        "safety_summary": safety,
        **safety,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_one_candidate_gmail_draft_package_path": str(REPORT_JSON_PATH),
        "html_trustpilot_one_candidate_gmail_draft_package_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions, candidate_summary),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _draft_preview(masked_email: str) -> dict:
    return {
        "from": GMAIL_SEND_FROM,
        "to_masked": _safe_masked_email(masked_email),
        "raw_recipient_available": False,
        "subject": SUBJECT,
        "body_preview": BODY_TEMPLATE.format(trustpilot_link=TRUSTPILOT_LINK),
        "trustpilot_link": TRUSTPILOT_LINK,
        "gmail_draft_created": False,
        "email_sent": False,
        "future_tag_after_later_approved_send": TRUSTPILOT_TAG,
        "future_tag_add_performed": False,
        "future_review_request_tag_remove_performed": False,
    }


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
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "all_new_external_api_calls_confirmed_false": True,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_one_candidate_gmail_draft_package_path": str(json_path),
        "html_trustpilot_one_candidate_gmail_draft_package_path": str(html_path),
        "one_candidate_gmail_draft_package_status": payload["one_candidate_gmail_draft_package_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "next_candidate_selected": payload["next_candidate_selected"],
        "next_candidate_count": payload["next_candidate_count"],
        "repeat_customer_confirmed": payload["repeat_customer_confirmed"],
        "duplicate_trustpilot_invitation_block_confirmed": payload[
            "duplicate_trustpilot_invitation_block_confirmed"
        ],
        "returned_package_guard_confirmed": payload["returned_package_guard_confirmed"],
        "first_order_customer_block_confirmed": payload["first_order_customer_block_confirmed"],
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
    preview = payload["trustpilot_invitation_preview"]
    blocking_rows = "\n".join(
        f"<tr><td>{escape(item.get('status', ''))}</td><td>{escape(item.get('detail', ''))}</td></tr>"
        for item in payload["blocking_conditions"]
    ) or "<tr><td colspan=\"2\">None</td></tr>"
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    guard_rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(payload[key]))}</td></tr>"
        for label, key in (
            ("Repeat customer confirmed", "repeat_customer_confirmed"),
            (
                "Duplicate Trustpilot invitation block confirmed",
                "duplicate_trustpilot_invitation_block_confirmed",
            ),
            ("Returned package guard confirmed", "returned_package_guard_confirmed"),
            ("First-order customer block confirmed", "first_order_customer_block_confirmed"),
            (
                "Risk/ticket/refund/cancel/dispute blocker detected",
                "risk_ticket_refund_cancel_dispute_blocker_detected",
            ),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot One-Candidate Gmail Draft Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
    .preview {{ white-space: pre-wrap; max-width: 720px; }}
  </style>
</head>
<body>
  <h1>Trustpilot One-Candidate Gmail Draft Package</h1>
  <p class="warning">Phase 4.1 is local preview only. It does not create a Gmail draft, send email, write Shopify tags, or call Kudosi/Ali Reviews.</p>
  <p>Status: <strong>{escape(payload["one_candidate_gmail_draft_package_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source report: <code>{escape(payload["source_candidate_scan_report_path"])}</code></p>
  <h2>Candidate Guards</h2>
  <table><tbody>{guard_rows}</tbody></table>
  <h2>Draft Preview</h2>
  <table><tbody>
    <tr><th>From</th><td><code>{escape(preview["from"])}</code></td></tr>
    <tr><th>To</th><td><code>{escape(preview["to_masked"])}</code></td></tr>
    <tr><th>Subject</th><td>{escape(preview["subject"])}</td></tr>
    <tr><th>Body preview</th><td class="preview">{escape(preview["body_preview"])}</td></tr>
    <tr><th>Gmail draft created</th><td>{escape(str(preview["gmail_draft_created"]))}</td></tr>
    <tr><th>Email sent</th><td>{escape(str(preview["email_sent"]))}</td></tr>
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
    if self_scan["raw_customer_email_count"] or self_scan["credential_pattern_count"]:
        payload["one_candidate_gmail_draft_package_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["raw_customer_email_would_be_written"] = bool(self_scan["raw_customer_email_count"])
        payload["blocking_conditions"].append(
            {
                "status": "blocked_privacy_scan_failed",
                "detail": "one-candidate draft package self privacy scan failed.",
            }
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
        payload["detected_issue_summary"] = _issue_summary(
            payload["one_candidate_gmail_draft_package_status"],
            payload["blocking_conditions"],
            payload["selected_candidate_summary"],
        )
    return payload


def _matched_trustpilot_aliases(candidate: dict, candidate_summary: dict) -> list[str]:
    tags = []
    tags.extend(candidate_summary["tags_of_interest"])
    tags.extend(candidate_summary["matched_trustpilot_invitation_tags"])
    for key in ("customer_history_tags", "customer_order_tags", "historical_order_tags"):
        tags.extend(_safe_list(candidate.get(key, [])))
    tag_summary = candidate.get("safe_tags_summary") if isinstance(candidate.get("safe_tags_summary"), dict) else {}
    for key in ("tags_of_interest", "safe_tags", "exact_tags_of_interest"):
        tags.extend(_safe_list(tag_summary.get(key, [])))
    aliases = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    return _dedupe([tag for tag in tags if _normalize_tag(tag) in aliases])


def _returned_package_guard_triggered(candidate_summary: dict) -> bool:
    text_values = [
        *candidate_summary["classification_buckets"],
        *candidate_summary["blocking_reasons"],
        *candidate_summary["tags_of_interest"],
    ]
    if any(value in {"blocked_returned_package", "blocked_shipping_or_delivery_issue"} for value in text_values):
        return True
    return any(_is_return_tag(value) for value in text_values)


def _risk_ticket_refund_cancel_dispute_blocker_detected(candidate_summary: dict) -> bool:
    if candidate_summary["ticket_risk_detected"]:
        return True
    values = [
        candidate_summary["source_decision"],
        *candidate_summary["classification_buckets"],
        *candidate_summary["blocking_reasons"],
        *candidate_summary["tags_of_interest"],
    ]
    if any(value.startswith("blocked_") for value in values if value):
        return True
    return any(RISK_TEXT_RE.search(value or "") for value in values)


def _trustpilot_alias_coverage() -> dict:
    required = {
        "1: trustpilot",
        "1: trustpoilt",
        "1:trustpilot",
        "1 : trustpilot",
        "1:trustpoilt",
        "1 : trustpoilt",
    }
    normalized_required = {_normalize_tag(tag) for tag in required}
    normalized_configured = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    return {
        "configured_aliases": TRUSTPILOT_TAG_ALIASES,
        "required_aliases": sorted(required),
        "normalized_required_aliases": sorted(normalized_required),
        "normalized_configured_aliases": sorted(normalized_configured),
        "all_required_aliases_present": normalized_required.issubset(normalized_configured),
        "canonical_tag": TRUSTPILOT_TAG,
    }


def _is_return_tag(tag: str) -> bool:
    normalized = re.sub(r"[\s_-]+", " ", str(tag or "").strip().lower())
    compact = normalized.replace(" ", "")
    return "return" in compact or "returned" in compact


def _normalize_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text)


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
    for pattern in CREDENTIAL_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _safe_list(values) -> list[str]:
    if not isinstance(values, list):
        return []
    return [_safe_text(value) for value in values if _safe_text(value)]


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


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
        "credential_pattern_count": sum(1 for pattern in CREDENTIAL_VALUE_PATTERNS if pattern.search(text or "")),
    }


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _issue_summary(status: str, blocking_conditions: list[dict], candidate_summary: dict) -> str:
    if status == SUCCESS_STATUS:
        return (
            f"Prepared a local Trustpilot Gmail draft preview for {candidate_summary.get('order_name', '')}; "
            "no Gmail draft, email send, Shopify write, tag change, or Kudosi/Ali Reviews call was performed."
        )
    return "One-candidate Trustpilot Gmail draft package blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 4.1 one-candidate Trustpilot Gmail draft package finished.\n"
        f"Status: {payload.get('one_candidate_gmail_draft_package_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Next candidate selected: {payload.get('next_candidate_selected')}\n"
        f"Next candidate count: {payload.get('next_candidate_count')}\n"
        f"Repeat customer confirmed: {payload.get('repeat_customer_confirmed')}\n"
        f"Duplicate Trustpilot block confirmed: {payload.get('duplicate_trustpilot_invitation_block_confirmed')}\n"
        f"Returned package guard confirmed: {payload.get('returned_package_guard_confirmed')}\n"
        f"First-order block confirmed: {payload.get('first_order_customer_block_confirmed')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail API/draft/send, no Shopify API/write/tagsAdd/tagsRemove, and no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
