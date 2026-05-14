import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_customer_level_duplicate_suppression import (
    CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
    evaluate_customer_level_duplicate,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner"
COMMAND_LABEL = "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner"

SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_package.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner.html"

SUCCESS_STATUS = "trustpilot_one_candidate_gmail_draft_create_locked_preflight_passed"
EXPECTED_SOURCE_TASK = "shopify_review_request_trustpilot_one_candidate_gmail_draft_package"
EXPECTED_SOURCE_STATUS = "trustpilot_one_candidate_gmail_draft_package_ready"
EXPECTED_ORDER_NAME = "#22620"
TRUSTPILOT_LINK = "https://www.trustpilot.com/evaluate/www.kidstoylover.com"
GMAIL_SEND_FROM = "info@kidstoylover.com"

FUTURE_APPROVAL_ENV_NAMES = [
    "REVIEW_REQUEST_REAL_GMAIL_DRAFT_CREATE_APPROVED",
    "REVIEW_REQUEST_REAL_GMAIL_DRAFT_CREATE_ORDER_NAME",
    "REVIEW_REQUEST_REAL_GMAIL_DRAFT_CREATE_SOURCE_REPORT",
]

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
ALLOWED_REPORT_EMAILS = {GMAIL_SEND_FROM.lower()}
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

SOURCE_UNSAFE_FLAG_KEYS = [
    "gmail_api_call_performed",
    "gmail_oauth_token_exchange_performed",
    "gmail_oauth_token_refresh_attempted",
    "gmail_token_refresh_attempted",
    "gmail_draft_create_attempted",
    "gmail_draft_created",
    "gmail_drafts_send_called",
    "gmail_messages_send_called",
    "gmail_send_performed",
    "email_sent",
    "shopify_api_call_performed",
    "shopify_live_query_performed",
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
    "raw_customer_email_would_be_written",
    "real_gmail_or_shopify_write_action_would_be_attempted",
]


def run_shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error, source_text = _read_source_report()
    source_privacy_scan = _privacy_scan_text(source_text)
    source_summary = _source_summary(source_report, source_error)
    source_safety = _source_safety_summary(source_report)
    customer_level_duplicate = evaluate_customer_level_duplicate(
        source_summary["selected_order_name"],
        source_summary["selected_masked_email"],
    )
    draft_preview = _draft_preview(source_report, source_summary)
    blocking_conditions = _blocking_conditions(
        source_report=source_report,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        source_summary=source_summary,
        source_safety=source_safety,
        customer_level_duplicate=customer_level_duplicate,
        draft_preview=draft_preview,
    )
    status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        status=status,
        source_summary=source_summary,
        source_safety=source_safety,
        source_privacy_scan=source_privacy_scan,
        customer_level_duplicate=customer_level_duplicate,
        draft_preview=draft_preview,
        blocking_conditions=blocking_conditions,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_report() -> tuple[dict, str, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "blocked_missing_source_package_report", ""
    text = SOURCE_JSON_PATH.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(text), "", text
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_invalid_source_package_json: {exc}"), text


def _source_summary(source_report: dict, source_error: str) -> dict:
    return {
        "path": str(SOURCE_JSON_PATH),
        "present": SOURCE_JSON_PATH.exists(),
        "error_sanitized": _sanitize_text(source_error),
        "task_name": _safe_text(source_report.get("task_name", "")),
        "phase": _safe_text(source_report.get("phase", "")),
        "success": source_report.get("success") is True,
        "source_package_status": _safe_text(source_report.get("one_candidate_gmail_draft_package_status", "")),
        "selected_order_name": _safe_text(source_report.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_report.get("selected_masked_email", "")),
        "next_candidate_selected": source_report.get("next_candidate_selected") is True,
        "next_candidate_count": _safe_int(source_report.get("next_candidate_count")),
        "candidate_selected_count": _safe_int(source_report.get("candidate_selected_count")),
        "repeat_customer_confirmed": source_report.get("repeat_customer_confirmed") is True,
        "duplicate_trustpilot_invitation_block_confirmed": (
            source_report.get("duplicate_trustpilot_invitation_block_confirmed") is True
        ),
        "returned_package_guard_confirmed": source_report.get("returned_package_guard_confirmed") is True,
        "first_order_customer_block_confirmed": source_report.get("first_order_customer_block_confirmed") is True,
        "candidate_has_no_blocking_reasons": source_report.get("candidate_has_no_blocking_reasons") is True,
        "candidate_no_real_action_planned_in_source": (
            source_report.get("candidate_no_real_action_planned_in_source") is True
        ),
        "blocking_condition_count": _safe_int(source_report.get("blocking_condition_count")),
        "source_self_privacy_raw_customer_email_count": _safe_int(
            (source_report.get("self_privacy_scan") or {}).get("raw_customer_email_count")
            if isinstance(source_report.get("self_privacy_scan"), dict)
            else 0
        ),
        "source_self_privacy_credential_pattern_count": _safe_int(
            (source_report.get("self_privacy_scan") or {}).get("credential_pattern_count")
            if isinstance(source_report.get("self_privacy_scan"), dict)
            else 0
        ),
    }


def _source_safety_summary(source_report: dict) -> dict:
    flags = {key: source_report.get(key) is True for key in SOURCE_UNSAFE_FLAG_KEYS}
    flags["gmail_drafts_created_count_gt_zero"] = _safe_int(source_report.get("gmail_drafts_created_count")) > 0
    return {
        "source_unsafe_flags": flags,
        "source_unsafe_flag_names": [key for key, value in flags.items() if value],
        "source_gmail_drafts_created_count": _safe_int(source_report.get("gmail_drafts_created_count")),
    }


def _draft_preview(source_report: dict, source_summary: dict) -> dict:
    preview = source_report.get("trustpilot_invitation_preview")
    if not isinstance(preview, dict):
        preview = {}
    subject = _safe_text(preview.get("subject") or source_report.get("subject", ""))
    body = _safe_text(preview.get("body_preview") or preview.get("body") or "")
    link = _safe_text(preview.get("trustpilot_link") or source_report.get("trustpilot_link") or TRUSTPILOT_LINK)
    return {
        "source_preview_present": bool(preview),
        "to_masked": _safe_masked_email(preview.get("to_masked") or source_summary["selected_masked_email"]),
        "raw_recipient_available": False,
        "subject": subject,
        "body_preview": body,
        "trustpilot_link": link,
        "gmail_draft_created": False,
        "email_sent": False,
    }


def _blocking_conditions(
    source_report: dict,
    source_error: str,
    source_privacy_scan: dict,
    source_summary: dict,
    source_safety: dict,
    customer_level_duplicate: dict,
    draft_preview: dict,
) -> list[dict]:
    if source_error:
        return [{"status": "blocked_missing_or_invalid_source_package", "detail": _sanitize_text(source_error)}]

    conditions = []
    if source_report.get("task_name") != EXPECTED_SOURCE_TASK:
        conditions.append({"status": "blocked_invalid_source_package", "detail": "source task name mismatch."})
    if str(source_report.get("phase")) != "4.1":
        conditions.append({"status": "blocked_invalid_source_package", "detail": "source phase must be 4.1."})
    if source_report.get("success") is not True:
        conditions.append({"status": "blocked_invalid_source_package", "detail": "source success is not true."})
    if source_summary["source_package_status"] != EXPECTED_SOURCE_STATUS:
        conditions.append({"status": "blocked_invalid_source_package_status", "detail": "source package status is not ready."})
    if source_summary["selected_order_name"] != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_selected_order_mismatch", "detail": "selected order must be #22620."})
    if not _is_masked_email(source_summary["selected_masked_email"]):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected email is missing or not masked."})
    if source_summary["next_candidate_selected"] is not True:
        conditions.append({"status": "blocked_next_candidate_not_selected", "detail": "next_candidate_selected is not true."})
    if source_summary["next_candidate_count"] != 1:
        conditions.append({"status": "blocked_invalid_next_candidate_count", "detail": "next_candidate_count must equal 1."})
    if not source_summary["repeat_customer_confirmed"]:
        conditions.append({"status": "blocked_repeat_customer_not_confirmed", "detail": "repeat customer confirmation missing."})
    if not source_summary["duplicate_trustpilot_invitation_block_confirmed"]:
        conditions.append(
            {
                "status": "blocked_duplicate_trustpilot_invitation_guard_missing",
                "detail": "duplicate Trustpilot invitation guard is not confirmed.",
            }
        )
    if customer_level_duplicate["customer_level_duplicate_block_applies"]:
        conditions.append(
            {
                "status": CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
                "detail": "selected candidate matches a prior Trustpilot invitation customer/email signal.",
            }
        )
    if not source_summary["returned_package_guard_confirmed"]:
        conditions.append(
            {"status": "blocked_returned_package_guard_missing", "detail": "returned package guard is not confirmed."}
        )
    if not source_summary["first_order_customer_block_confirmed"]:
        conditions.append(
            {"status": "blocked_first_order_customer_block_missing", "detail": "first-order customer block is not confirmed."}
        )
    if source_summary["blocking_condition_count"] != 0:
        conditions.append({"status": "blocked_source_has_blocking_conditions", "detail": "source package has blockers."})
    if not source_summary["candidate_no_real_action_planned_in_source"]:
        conditions.append({"status": "blocked_source_real_action_plan_detected", "detail": "source candidate planned a real action."})
    if source_safety["source_unsafe_flag_names"]:
        conditions.append(
            {
                "status": "blocked_source_real_action_flag_detected",
                "detail": "source package has Gmail, Shopify, external API, tracking, or raw-email write flags.",
            }
        )
    if source_privacy_scan["raw_customer_email_count"] or source_privacy_scan["credential_pattern_count"]:
        conditions.append({"status": "blocked_source_privacy_scan_failed", "detail": "source package privacy scan failed."})
    if source_summary["source_self_privacy_raw_customer_email_count"]:
        conditions.append({"status": "blocked_source_privacy_scan_failed", "detail": "source self raw-email scan is not zero."})
    if source_summary["source_self_privacy_credential_pattern_count"]:
        conditions.append({"status": "blocked_source_privacy_scan_failed", "detail": "source self credential scan is not zero."})
    if not draft_preview["source_preview_present"] or not draft_preview["subject"] or not draft_preview["body_preview"]:
        conditions.append({"status": "blocked_missing_draft_preview", "detail": "source package draft subject/body preview is missing."})
    if draft_preview["to_masked"] != source_summary["selected_masked_email"]:
        conditions.append({"status": "blocked_draft_preview_email_mismatch", "detail": "draft preview masked email mismatch."})
    return conditions


def _build_payload(
    status: str,
    source_summary: dict,
    source_safety: dict,
    source_privacy_scan: dict,
    customer_level_duplicate: dict,
    draft_preview: dict,
    blocking_conditions: list[dict],
    duration_seconds: float,
) -> dict:
    success = status == SUCCESS_STATUS
    would_create_count = 1 if success else 0
    safety = _safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "4.4",
        "mode": "trustpilot-one-candidate-gmail-draft-create-locked-preflight",
        "command_label": COMMAND_LABEL,
        "one_candidate_gmail_draft_create_locked_status": status,
        "success": success,
        "source_package_report_path": str(SOURCE_JSON_PATH),
        "source_package_status": source_summary["source_package_status"],
        "source_package_summary": source_summary,
        "source_package_safety_summary": source_safety,
        "source_package_privacy_scan": source_privacy_scan,
        "selected_order_name": source_summary["selected_order_name"],
        "selected_masked_email": source_summary["selected_masked_email"],
        "next_candidate_selected": source_summary["next_candidate_selected"],
        "next_candidate_count": source_summary["next_candidate_count"],
        "repeat_customer_confirmed": source_summary["repeat_customer_confirmed"],
        "duplicate_trustpilot_invitation_block_confirmed": source_summary[
            "duplicate_trustpilot_invitation_block_confirmed"
        ],
        "customer_level_duplicate_block_applies": customer_level_duplicate[
            "customer_level_duplicate_block_applies"
        ],
        "customer_level_duplicate_classification": customer_level_duplicate["classification"],
        "prior_trustpilot_invitation_detected": customer_level_duplicate[
            "prior_trustpilot_invitation_detected"
        ],
        "prior_trustpilot_order_name": customer_level_duplicate["prior_trustpilot_order_name"],
        "customer_level_duplicate_match_basis": customer_level_duplicate[
            "same_customer_detection_basis"
        ],
        "same_customer_detected": customer_level_duplicate["same_customer_detected"],
        "same_email_detected": customer_level_duplicate["same_email_detected"],
        "same_masked_email_detected": customer_level_duplicate["same_masked_email_detected"],
        "existing_unsent_gmail_draft_should_not_be_sent": customer_level_duplicate[
            "existing_unsent_gmail_draft_should_not_be_sent"
        ],
        "future_optional_draft_cleanup_needs_separate_locked_phase": customer_level_duplicate[
            "future_optional_draft_cleanup_needs_separate_locked_phase"
        ],
        "returned_package_guard_confirmed": source_summary["returned_package_guard_confirmed"],
        "first_order_customer_block_confirmed": source_summary["first_order_customer_block_confirmed"],
        "draft_subject_preview": draft_preview["subject"],
        "draft_body_preview": draft_preview["body_preview"],
        "trustpilot_link": draft_preview["trustpilot_link"],
        "selected_draft_preview": draft_preview,
        "gmail_draft_create_plan": {
            "would_create_gmail_draft": success,
            "would_create_count": would_create_count,
            "max_drafts_in_future_phase": 1,
            "selected_order_name": source_summary["selected_order_name"],
            "to_masked": source_summary["selected_masked_email"],
            "raw_recipient_report_storage_allowed": False,
            "real_gmail_draft_create_allowed_now": False,
            "future_real_gmail_draft_create_needs_next_phase": True,
        },
        "would_create_gmail_draft": success,
        "would_create_count": would_create_count,
        "real_gmail_draft_create_allowed_now": False,
        "future_real_gmail_draft_create_needs_next_phase": True,
        "future_real_run_gate_design": {
            "design_only": True,
            "approval_env_names": FUTURE_APPROVAL_ENV_NAMES,
            "expected_order_name": EXPECTED_ORDER_NAME,
            "expected_source_report": str(REPORT_JSON_PATH),
            "real_execution_in_this_phase": False,
        },
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_customer_email_output": False,
            "raw_customer_email_report_storage_allowed": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
            "private_customer_notes_output": False,
            "credential_or_token_output": False,
        },
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "readiness_status": "ready_for_future_phase" if success else "blocked",
        "locked_preflight_only": True,
        "dry_run_preflight_only": True,
        "real_run_supported_in_this_phase": False,
        "gmail_draft_create_code_path_present": False,
        "protected_raw_email_lookup_attempted": False,
        "raw_customer_email_would_be_written": False,
        "token_or_secret_would_be_written": False,
        "tracking_redirect_allowed": False,
        "tracking_token_allowed": False,
        "safety_summary": safety,
        **safety,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_one_candidate_gmail_draft_create_locked_runner_path": str(REPORT_JSON_PATH),
        "html_trustpilot_one_candidate_gmail_draft_create_locked_runner_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
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
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_token_refresh_attempted": False,
        "gmail_token_refresh_succeeded": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_drafts_created_count": 0,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
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
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_one_candidate_gmail_draft_create_locked_runner_path": str(json_path),
        "html_trustpilot_one_candidate_gmail_draft_create_locked_runner_path": str(html_path),
        "one_candidate_gmail_draft_create_locked_status": payload[
            "one_candidate_gmail_draft_create_locked_status"
        ],
        "source_package_status": payload["source_package_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "next_candidate_selected": payload["next_candidate_selected"],
        "next_candidate_count": payload["next_candidate_count"],
        "repeat_customer_confirmed": payload["repeat_customer_confirmed"],
        "duplicate_trustpilot_invitation_block_confirmed": payload[
            "duplicate_trustpilot_invitation_block_confirmed"
        ],
        "customer_level_duplicate_block_applies": payload["customer_level_duplicate_block_applies"],
        "prior_trustpilot_order_name": payload["prior_trustpilot_order_name"],
        "existing_unsent_gmail_draft_should_not_be_sent": payload[
            "existing_unsent_gmail_draft_should_not_be_sent"
        ],
        "returned_package_guard_confirmed": payload["returned_package_guard_confirmed"],
        "first_order_customer_block_confirmed": payload["first_order_customer_block_confirmed"],
        "would_create_gmail_draft": payload["would_create_gmail_draft"],
        "would_create_count": payload["would_create_count"],
        "real_gmail_draft_create_allowed_now": payload["real_gmail_draft_create_allowed_now"],
        "future_real_gmail_draft_create_needs_next_phase": payload[
            "future_real_gmail_draft_create_needs_next_phase"
        ],
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
    source_scan = payload["source_package_privacy_scan"]
    self_scan = payload["self_privacy_scan"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot One-Candidate Gmail Draft Create Locked Runner</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .safe {{ border-left: 4px solid #15803d; background: #f0fdf4; padding: 10px 12px; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
    .preview {{ white-space: pre-wrap; max-width: 760px; }}
  </style>
</head>
<body>
  <h1>Trustpilot One-Candidate Gmail Draft Create Locked Runner</h1>
  <p class="{'safe' if payload['success'] else 'warning'}">Phase 4.4 is locked preflight only. It did not call Gmail, create a draft, send email, write Shopify tags, call Trustpilot/Kudosi/Ali Reviews, or enable tracking.</p>
  <p>Status: <strong>{escape(payload["one_candidate_gmail_draft_create_locked_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source package: <code>{escape(payload["source_package_report_path"])}</code></p>
  <p>Source package status: <strong>{escape(payload["source_package_status"])}</strong></p>
  <h2>Draft Create Plan</h2>
  <table><tbody>
    <tr><th>Would create Gmail draft</th><td>{escape(str(payload["would_create_gmail_draft"]))}</td></tr>
    <tr><th>Would create count</th><td>{escape(str(payload["would_create_count"]))}</td></tr>
    <tr><th>Real Gmail draft create allowed now</th><td>{escape(str(payload["real_gmail_draft_create_allowed_now"]))}</td></tr>
    <tr><th>Future real Gmail draft create needs next phase</th><td>{escape(str(payload["future_real_gmail_draft_create_needs_next_phase"]))}</td></tr>
  </tbody></table>
  <h2>Draft Preview</h2>
  <table><tbody>
    <tr><th>To</th><td><code>{escape(payload["selected_draft_preview"]["to_masked"])}</code></td></tr>
    <tr><th>Subject</th><td>{escape(payload["draft_subject_preview"])}</td></tr>
    <tr><th>Body preview</th><td class="preview">{escape(payload["draft_body_preview"])}</td></tr>
    <tr><th>Trustpilot link</th><td><code>{escape(payload["trustpilot_link"])}</code></td></tr>
  </tbody></table>
  <h2>Source Guards</h2>
  <table><tbody>
    <tr><th>Next candidate selected</th><td>{escape(str(payload["next_candidate_selected"]))}</td></tr>
    <tr><th>Next candidate count</th><td>{escape(str(payload["next_candidate_count"]))}</td></tr>
    <tr><th>Repeat customer confirmed</th><td>{escape(str(payload["repeat_customer_confirmed"]))}</td></tr>
    <tr><th>Duplicate Trustpilot invitation block confirmed</th><td>{escape(str(payload["duplicate_trustpilot_invitation_block_confirmed"]))}</td></tr>
    <tr><th>Customer-level duplicate block applies</th><td>{escape(str(payload["customer_level_duplicate_block_applies"]))}</td></tr>
    <tr><th>Prior Trustpilot order</th><td><code>{escape(str(payload["prior_trustpilot_order_name"]))}</code></td></tr>
    <tr><th>Existing unsent Gmail draft should not be sent</th><td>{escape(str(payload["existing_unsent_gmail_draft_should_not_be_sent"]))}</td></tr>
    <tr><th>Returned package guard confirmed</th><td>{escape(str(payload["returned_package_guard_confirmed"]))}</td></tr>
    <tr><th>First-order customer block confirmed</th><td>{escape(str(payload["first_order_customer_block_confirmed"]))}</td></tr>
  </tbody></table>
  <h2>Privacy Scan</h2>
  <table><tbody>
    <tr><th>Source raw customer email count</th><td>{source_scan["raw_customer_email_count"]}</td></tr>
    <tr><th>Source token/secret/Bearer value pattern count</th><td>{source_scan["credential_pattern_count"]}</td></tr>
    <tr><th>Report raw customer email count</th><td>{self_scan["raw_customer_email_count"]}</td></tr>
    <tr><th>Report token/secret/Bearer value pattern count</th><td>{self_scan["credential_pattern_count"]}</td></tr>
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
    if not self_scan["raw_customer_email_count"] and not self_scan["credential_pattern_count"]:
        return payload

    payload["one_candidate_gmail_draft_create_locked_status"] = "blocked_privacy_scan_failed"
    payload["success"] = False
    payload["would_create_gmail_draft"] = False
    payload["would_create_count"] = 0
    payload["gmail_draft_create_plan"]["would_create_gmail_draft"] = False
    payload["gmail_draft_create_plan"]["would_create_count"] = 0
    payload["readiness_status"] = "blocked"
    payload["raw_customer_email_would_be_written"] = bool(self_scan["raw_customer_email_count"])
    payload["token_or_secret_would_be_written"] = bool(self_scan["credential_pattern_count"])
    payload["blocking_conditions"].append(
        {"status": "blocked_privacy_scan_failed", "detail": "Phase 4.4 report self privacy scan failed."}
    )
    payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    payload["detected_issue_summary"] = _issue_summary(
        payload["one_candidate_gmail_draft_create_locked_status"],
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
        "credential_pattern_count": sum(1 for pattern in CREDENTIAL_VALUE_PATTERNS if pattern.search(text or "")),
    }


def _safe_masked_email(value) -> str:
    text = _safe_text(value)
    if not text or "@" not in text:
        return ""
    if "***" in text:
        return text
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)


def _is_masked_email(value) -> bool:
    text = str(value or "")
    return bool(text and "@" in text and "***" in text and not EMAIL_RE.fullmatch(text))


def _safe_text(value) -> str:
    return _sanitize_text(str(value or ""))


def _sanitize_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in CREDENTIAL_VALUE_PATTERNS:
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
            "Prepared the locked Phase 4.4 Gmail draft creation preflight for #22620; no Gmail API call, draft "
            "creation, email send, Shopify write, Trustpilot/Kudosi/Ali Reviews API call, or tracking action was performed."
        )
    return "Phase 4.4 Gmail draft creation locked preflight blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 4.4 Trustpilot one-candidate Gmail draft create locked preflight finished.\n"
        f"Status: {payload.get('one_candidate_gmail_draft_create_locked_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Source package status: {payload.get('source_package_status')}\n"
        f"Would create Gmail draft in a future phase: {payload.get('would_create_gmail_draft')}\n"
        f"Would create count: {payload.get('would_create_count')}\n"
        f"Real Gmail draft create allowed now: {payload.get('real_gmail_draft_create_allowed_now')}\n"
        f"Future real Gmail draft create needs next phase: {payload.get('future_real_gmail_draft_create_needs_next_phase')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail API/draft/send, no Shopify API/write/tagsAdd/tagsRemove, no Trustpilot/Kudosi/Ali Reviews API call, and no tracking token or redirect.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
