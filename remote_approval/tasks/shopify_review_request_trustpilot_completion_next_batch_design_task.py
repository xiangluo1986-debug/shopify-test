import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_completion_next_batch_design"
COMMAND_LABEL = "shopify_review_request_trustpilot_completion_next_batch_design"

SOURCE_SEND_EXECUTE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.json"
SOURCE_SEND_EXECUTE_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.html"
SOURCE_SEND_AUDIT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.json"
SOURCE_SEND_AUDIT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.html"
SOURCE_TAG_WRITE_EXECUTE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_execute.json"
SOURCE_TAG_WRITE_EXECUTE_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_execute.html"
SOURCE_TAG_WRITE_AUDIT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_audit.json"
SOURCE_TAG_WRITE_AUDIT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_audit.html"
PROTECTED_DRAFT_SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_completion_next_batch_design.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_completion_next_batch_design.html"

SUCCESS_STATUS = "trustpilot_single_order_workflow_completed_next_batch_design_ready"
EXPECTED_SEND_EXECUTE_STATUS = "one_gmail_draft_sent_and_needs_send_audit"
EXPECTED_SEND_AUDIT_STATUS = "trustpilot_gmail_one_draft_send_audit_passed"
EXPECTED_TAG_WRITE_EXECUTE_STATUS = "one_trustpilot_tag_written_and_needs_audit"
EXPECTED_TAG_WRITE_AUDIT_STATUS = "trustpilot_tag_write_audit_passed"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
CANONICAL_TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]
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


def run_shopify_review_request_trustpilot_completion_next_batch_design_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    send_execute, send_execute_error = _read_json_report(
        SOURCE_SEND_EXECUTE_JSON_PATH, "blocked_missing_send_execute_report"
    )
    send_audit, send_audit_error = _read_json_report(
        SOURCE_SEND_AUDIT_JSON_PATH, "blocked_missing_send_audit_report"
    )
    tag_write_execute, tag_write_execute_error = _read_json_report(
        SOURCE_TAG_WRITE_EXECUTE_JSON_PATH, "blocked_missing_tag_write_execute_report"
    )
    tag_write_audit, tag_write_audit_error = _read_json_report(
        SOURCE_TAG_WRITE_AUDIT_JSON_PATH, "blocked_missing_tag_write_audit_report"
    )
    source_reports = {
        "send_execute": send_execute,
        "send_audit": send_audit,
        "tag_write_execute": tag_write_execute,
        "tag_write_audit": tag_write_audit,
    }
    source_errors = {
        "send_execute": send_execute_error,
        "send_audit": send_audit_error,
        "tag_write_execute": tag_write_execute_error,
        "tag_write_audit": tag_write_audit_error,
    }
    source_privacy_scan = _source_privacy_scan()
    full_draft_id_leak = _source_full_draft_id_leak_detected()
    alias_coverage = _trustpilot_alias_coverage()
    blocking_conditions = _blocking_conditions(
        source_reports=source_reports,
        source_errors=source_errors,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        alias_coverage=alias_coverage,
    )
    status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        source_reports=source_reports,
        source_errors=source_errors,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        alias_coverage=alias_coverage,
        blocking_conditions=blocking_conditions,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_json_report(path: Path, missing_status: str) -> tuple[dict, str]:
    if not path.exists():
        return {}, missing_status
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"{missing_status}: source JSON parse failed: {exc}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _source_privacy_scan() -> dict:
    return {
        "send_execute_json": _privacy_scan_text(_read_text(SOURCE_SEND_EXECUTE_JSON_PATH)),
        "send_execute_html": _privacy_scan_text(_read_text(SOURCE_SEND_EXECUTE_HTML_PATH)),
        "send_audit_json": _privacy_scan_text(_read_text(SOURCE_SEND_AUDIT_JSON_PATH)),
        "send_audit_html": _privacy_scan_text(_read_text(SOURCE_SEND_AUDIT_HTML_PATH)),
        "tag_write_execute_json": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_EXECUTE_JSON_PATH)),
        "tag_write_execute_html": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_EXECUTE_HTML_PATH)),
        "tag_write_audit_json": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_AUDIT_JSON_PATH)),
        "tag_write_audit_html": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_AUDIT_HTML_PATH)),
    }


def _source_full_draft_id_leak_detected() -> bool:
    return _full_draft_id_leak_detected(
        _read_text(SOURCE_SEND_EXECUTE_JSON_PATH),
        _read_text(SOURCE_SEND_EXECUTE_HTML_PATH),
        _read_text(SOURCE_SEND_AUDIT_JSON_PATH),
        _read_text(SOURCE_SEND_AUDIT_HTML_PATH),
        _read_text(SOURCE_TAG_WRITE_EXECUTE_JSON_PATH),
        _read_text(SOURCE_TAG_WRITE_EXECUTE_HTML_PATH),
        _read_text(SOURCE_TAG_WRITE_AUDIT_JSON_PATH),
        _read_text(SOURCE_TAG_WRITE_AUDIT_HTML_PATH),
    )


def _blocking_conditions(
    source_reports: dict,
    source_errors: dict,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    alias_coverage: dict,
) -> list[dict]:
    conditions = []
    for source_name, source_error in source_errors.items():
        if source_error:
            conditions.append({"status": source_error.split(":", 1)[0], "detail": _sanitize_text(source_error)})
    if conditions:
        return conditions

    send_execute = source_reports["send_execute"]
    send_audit = source_reports["send_audit"]
    tag_write_execute = source_reports["tag_write_execute"]
    tag_write_audit = source_reports["tag_write_audit"]

    if send_execute.get("one_draft_send_execute_status") != EXPECTED_SEND_EXECUTE_STATUS:
        conditions.append({"status": "blocked_source_send_not_successful", "detail": "Gmail send execute status is not successful."})
    if send_audit.get("send_audit_status") != EXPECTED_SEND_AUDIT_STATUS or send_audit.get("success") is not True:
        conditions.append({"status": "blocked_send_audit_not_passed", "detail": "Gmail send audit did not pass."})
    if tag_write_execute.get("tag_write_execute_status") != EXPECTED_TAG_WRITE_EXECUTE_STATUS:
        conditions.append({"status": "blocked_tag_write_not_successful", "detail": "Shopify tag-write execute status is not successful."})
    if tag_write_audit.get("tag_write_audit_status") != EXPECTED_TAG_WRITE_AUDIT_STATUS or tag_write_audit.get("success") is not True:
        conditions.append({"status": "blocked_tag_write_audit_not_passed", "detail": "Shopify tag-write audit did not pass."})

    for source_name, report in source_reports.items():
        if _safe_text(report.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
            conditions.append({"status": "blocked_selected_order_mismatch", "detail": f"{source_name} selected_order_name mismatch."})
        masked_email = _safe_text(report.get("selected_masked_email", ""))
        if masked_email != EXPECTED_MASKED_EMAIL or not _is_masked_email(masked_email):
            conditions.append({"status": "blocked_unmasked_email_detected", "detail": f"{source_name} selected_masked_email mismatch or unmasked."})
        if _safe_text(report.get("source_gmail_draft_id_partial", "")) != EXPECTED_DRAFT_ID_PARTIAL:
            conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": f"{source_name} Gmail draft id partial mismatch."})

    if int(send_execute.get("sent_count") or 0) != 1 or int(send_audit.get("sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "Trustpilot Gmail sent count must equal 1."})
    if send_execute.get("email_sent") is not True or send_audit.get("email_sent_confirmed") is not True:
        conditions.append({"status": "blocked_email_not_sent", "detail": "email_sent confirmation is missing."})
    if send_execute.get("gmail_drafts_send_called") is not True or send_audit.get("gmail_drafts_send_confirmed") is not True:
        conditions.append({"status": "blocked_missing_drafts_send", "detail": "Gmail drafts.send was not confirmed."})
    if send_execute.get("gmail_messages_send_called") is not False or send_audit.get("gmail_messages_send_confirmed_false") is not True:
        conditions.append({"status": "blocked_messages_send_detected", "detail": "Gmail messages.send false confirmation failed."})

    if _safe_text(tag_write_execute.get("planned_shopify_tag", "")) != CANONICAL_TRUSTPILOT_TAG:
        conditions.append({"status": "blocked_tag_value_mismatch", "detail": "tag-write execute planned tag is not canonical."})
    if _safe_text(tag_write_audit.get("canonical_trustpilot_tag", "")) != CANONICAL_TRUSTPILOT_TAG:
        conditions.append({"status": "blocked_tag_value_mismatch", "detail": "tag-write audit canonical tag mismatch."})
    if int(tag_write_execute.get("written_tag_count") or 0) != 1 or int(tag_write_audit.get("source_written_tag_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_written_tag_count", "detail": "Shopify written_tag_count must equal 1."})
    if tag_write_execute.get("post_write_tag_present") is not True or tag_write_audit.get("source_post_write_tag_present") is not True:
        conditions.append({"status": "blocked_post_write_tag_not_confirmed", "detail": "post-write tag presence was not confirmed."})
    if tag_write_audit.get("canonical_trustpilot_tag_present") is not True:
        conditions.append({"status": "blocked_canonical_trustpilot_tag_missing", "detail": "canonical 1: trustpilot tag is not present."})
    if tag_write_audit.get("legacy_trustpilot_tag_detected") is not False:
        conditions.append({"status": "blocked_legacy_typo_tag_detected", "detail": "legacy Trustpilot tag was detected on the completed order."})
    if tag_write_execute.get("tags_remove_performed") is not False or tag_write_audit.get("tags_remove_performed") is not False:
        conditions.append({"status": "blocked_tags_remove_detected", "detail": "tagsRemove must remain false."})

    if any(tag_write_execute.get(flag) is True for flag in ("gmail_api_call_performed", "gmail_drafts_send_called", "gmail_messages_send_called", "email_sent")):
        conditions.append({"status": "blocked_gmail_second_send_detected", "detail": "tag-write execute report shows a Gmail action."})
    if any(tag_write_audit.get(flag) is True for flag in ("gmail_api_call_performed", "gmail_drafts_send_called", "gmail_messages_send_called", "email_sent")):
        conditions.append({"status": "blocked_gmail_second_send_detected", "detail": "tag-write audit report shows a Gmail action."})
    if any(report.get("kudosi_api_call_performed") is True or report.get("ali_reviews_api_call_performed") is True for report in source_reports.values()):
        conditions.append({"status": "blocked_kudosi_or_ali_reviews_detected", "detail": "Kudosi/Ali Reviews call was detected in source reports."})
    if any(int(report.get("blocking_condition_count") or 0) != 0 for report in source_reports.values()):
        conditions.append({"status": "blocked_source_has_blocking_conditions", "detail": "One source report has blocking conditions."})
    if not alias_coverage["all_required_aliases_present"]:
        conditions.append({"status": "blocked_trustpilot_alias_coverage_incomplete", "detail": "Trustpilot alias list does not cover all required legacy variants."})
    if _privacy_scan_failed(source_privacy_scan) or full_draft_id_leak_detected:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "Source report privacy scan failed."})
    return conditions


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
        "required_aliases": sorted(required),
        "configured_aliases": TRUSTPILOT_TAG_ALIASES,
        "normalized_required_aliases": sorted(normalized_required),
        "normalized_configured_aliases": sorted(normalized_configured),
        "all_required_aliases_present": normalized_required.issubset(normalized_configured),
        "trustpoilt_typo_covered": _normalize_tag("1: trustpoilt") in normalized_configured,
        "colon_spacing_variants_covered": all(
            _normalize_tag(tag) in normalized_configured
            for tag in ("1:trustpilot", "1 : trustpilot", "1:trustpoilt", "1 : trustpoilt")
        ),
    }


def _normalize_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text)


def _build_payload(
    source_reports: dict,
    source_errors: dict,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    alias_coverage: dict,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    send_execute = source_reports["send_execute"]
    send_audit = source_reports["send_audit"]
    tag_write_execute = source_reports["tag_write_execute"]
    tag_write_audit = source_reports["tag_write_audit"]
    success = status == SUCCESS_STATUS
    safety = _safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.24",
        "mode": "read-only-completion-next-batch-design",
        "command_label": COMMAND_LABEL,
        "completion_next_batch_design_status": status,
        "success": success,
        "selected_order_name": EXPECTED_ORDER_NAME,
        "selected_masked_email": EXPECTED_MASKED_EMAIL,
        "source_gmail_draft_id_partial": EXPECTED_DRAFT_ID_PARTIAL,
        "completion_summary": {
            "single_order_workflow_completed": success,
            "selected_order_name": EXPECTED_ORDER_NAME,
            "trustpilot_gmail_sent_count": int(send_audit.get("sent_count") or 0),
            "email_sent_confirmed": send_audit.get("email_sent_confirmed") is True,
            "gmail_drafts_send_confirmed": send_audit.get("gmail_drafts_send_confirmed") is True,
            "gmail_messages_send_confirmed_false": send_audit.get("gmail_messages_send_confirmed_false") is True,
            "shopify_tag_written": CANONICAL_TRUSTPILOT_TAG,
            "written_tag_count": int(tag_write_audit.get("source_written_tag_count") or 0),
            "post_write_audit_passed": tag_write_audit.get("tag_write_audit_status") == EXPECTED_TAG_WRITE_AUDIT_STATUS,
            "canonical_tag_present": tag_write_audit.get("canonical_trustpilot_tag_present") is True,
            "legacy_typo_tag_detected": tag_write_audit.get("legacy_trustpilot_tag_detected") is True,
            "already_completed_trustpilot_invitation": (
                send_audit.get("email_sent_confirmed") is True
                and tag_write_audit.get("canonical_trustpilot_tag_present") is True
                and tag_write_audit.get("tag_write_audit_status") == EXPECTED_TAG_WRITE_AUDIT_STATUS
            ),
            "current_order_duplicate_classification_if_reprocessed": "blocked_existing_trustpilot_invitation_tag",
            "existing_trustpilot_invitation_tag_alias_detected": (
                tag_write_audit.get("canonical_trustpilot_tag_present") is True
                or tag_write_audit.get("legacy_trustpilot_tag_detected") is True
            ),
            "no_gmail_second_send_performed": not any(
                report.get(flag) is True
                for report in (tag_write_execute, tag_write_audit)
                for flag in ("gmail_api_call_performed", "gmail_drafts_send_called", "gmail_messages_send_called", "email_sent")
            ),
            "no_tags_remove_performed": not any(
                report.get(flag) is True
                for report in (tag_write_execute, tag_write_audit)
                for flag in ("tags_remove_performed", "tagsRemove_performed")
            ),
            "no_kudosi_ali_reviews_call": not any(
                report.get(flag) is True
                for report in source_reports.values()
                for flag in ("kudosi_api_call_performed", "ali_reviews_api_call_performed")
            ),
            "no_other_orders_processed": _source_order_names_are_single_target(source_reports),
        },
        "source_statuses": {
            "send_execute_status": _safe_text(send_execute.get("one_draft_send_execute_status", "")),
            "send_audit_status": _safe_text(send_audit.get("send_audit_status", "")),
            "tag_write_execute_status": _safe_text(tag_write_execute.get("tag_write_execute_status", "")),
            "tag_write_audit_status": _safe_text(tag_write_audit.get("tag_write_audit_status", "")),
        },
        "source_reports_used": {
            "send_execute_json_path": str(SOURCE_SEND_EXECUTE_JSON_PATH),
            "send_audit_json_path": str(SOURCE_SEND_AUDIT_JSON_PATH),
            "tag_write_execute_json_path": str(SOURCE_TAG_WRITE_EXECUTE_JSON_PATH),
            "tag_write_audit_json_path": str(SOURCE_TAG_WRITE_AUDIT_JSON_PATH),
            "source_errors_sanitized": {key: _sanitize_text(value) for key, value in source_errors.items()},
        },
        "trustpilot_tag_matching_policy": {
            "canonical_write_tag": CANONICAL_TRUSTPILOT_TAG,
            "future_write_requires_exact_canonical_tag": True,
            "duplicate_search_uses_tolerant_normalized_alias_matching": True,
            "audit_uses_tolerant_normalized_alias_matching": True,
            "legacy_tags_are_never_auto_removed": True,
            **alias_coverage,
        },
        "next_batch_safety_design": _next_batch_safety_design(),
        "next_batch_phase_sequence": [
            "candidate scan",
            "local/dry-run package",
            "Gmail draft",
            "Gmail final preflight",
            "Gmail real send",
            "Gmail send audit",
            "Shopify tag write dry-run/final preflight",
            "Shopify tag real write",
            "Shopify tag audit",
        ],
        "source_privacy_scan": source_privacy_scan,
        "source_full_draft_id_leak_detected": full_draft_id_leak_detected,
        "privacy_scan_passed": not _privacy_scan_failed(source_privacy_scan) and not full_draft_id_leak_detected,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "safety_summary": safety,
        **safety,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_completion_next_batch_design_path": str(REPORT_JSON_PATH),
        "html_trustpilot_completion_next_batch_design_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _source_order_names_are_single_target(source_reports: dict) -> bool:
    return all(_safe_text(report.get("selected_order_name", "")) == EXPECTED_ORDER_NAME for report in source_reports.values())


def _next_batch_safety_design() -> dict:
    return {
        "trustpilot_customer_eligibility": {
            "repeat_customer_required": True,
            "multiple_purchase_customer_required": True,
            "first_order_customer_must_block": True,
            "unknown_repeat_status_must_block": True,
        },
        "risk_guards": {
            "return_or_returned_package_tag_must_block": True,
            "returned_to_warehouse_must_block": True,
            "support_ticket_or_refund_risk_must_block": True,
            "delivered_tag_does_not_override_return_block": True,
        },
        "duplicate_protection": {
            "existing_order_trustpilot_alias_must_block_duplicate_send": True,
            "customer_history_trustpilot_alias_must_block_duplicate_send": True,
            "existing_trustpilot_alias_must_block_duplicate_tag_write": True,
            "blocked_classification": "blocked_existing_trustpilot_invitation_tag",
            "when_blocked_create_gmail_draft": False,
            "when_blocked_send_gmail": False,
            "when_blocked_write_shopify_tag": False,
            "alias_matching_normalizes_colon_spacing": True,
            "alias_matching_tolerates_trustpoilt_typo": True,
            "current_phase_4_0_second_send_for_possible_missing_review_allowed": False,
        },
        "future_trustpilot_review_status_readback": {
            "not_in_current_phase_4_0_scope": True,
            "invitation_sent_and_reviewed": "permanently_block_future_trustpilot_invitation",
            "invitation_sent_but_not_reviewed": "future_follow_up_candidate_only_after_separate_design",
            "existing_invitation_tag_still_blocks_current_phase_duplicate_send": True,
        },
        "send_limits": {
            "max_gmail_sends_per_real_run": 1,
            "gmail_messages_send_forbidden": True,
            "new_draft_creation_forbidden_in_send_phase": True,
        },
        "tag_write_limits": {
            "future_write_tag_exact_value": CANONICAL_TRUSTPILOT_TAG,
            "max_orders_per_real_write": 1,
            "max_tags_per_real_write": 1,
            "tags_remove_forbidden": True,
            "overwrite_full_tags_field_forbidden": True,
        },
        "phase_separation": {
            "gmail_send_and_shopify_tag_write_must_remain_separate": True,
            "tag_write_allowed_only_after_send_audit_passes": True,
            "tag_write_audit_required_after_real_write": True,
            "if_tag_write_fails_do_not_resend_email": True,
        },
        "kudosi_ali_reviews": {
            "no_kudosi_or_ali_reviews_call_in_trustpilot_flow": True,
            "first_order_customer_should_use_ali_reviews_path_when_available": True,
        },
    }


def _safety_summary() -> dict:
    return {
        "shopify_api_call_performed": False,
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
        "email_sent": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    summary = payload["completion_summary"]
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_completion_next_batch_design_path": str(json_path),
        "html_trustpilot_completion_next_batch_design_path": str(html_path),
        "completion_next_batch_design_status": payload["completion_next_batch_design_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "trustpilot_gmail_sent_count": summary["trustpilot_gmail_sent_count"],
        "email_sent_confirmed": summary["email_sent_confirmed"],
        "shopify_tag_written": summary["shopify_tag_written"],
        "written_tag_count": summary["written_tag_count"],
        "post_write_audit_passed": summary["post_write_audit_passed"],
        "canonical_tag_present": summary["canonical_tag_present"],
        "legacy_typo_tag_detected": summary["legacy_typo_tag_detected"],
        "already_completed_trustpilot_invitation": summary["already_completed_trustpilot_invitation"],
        "current_order_duplicate_classification_if_reprocessed": summary["current_order_duplicate_classification_if_reprocessed"],
        "no_other_orders_processed": summary["no_other_orders_processed"],
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
    summary = payload["completion_summary"]
    blocking_rows = "\n".join(
        f"<tr><td>{escape(item.get('status', ''))}</td><td>{escape(item.get('detail', ''))}</td></tr>"
        for item in payload["blocking_conditions"]
    ) or "<tr><td colspan=\"2\">None</td></tr>"
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    sequence_rows = "\n".join(
        f"<tr><td>{index}</td><td>{escape(step)}</td></tr>"
        for index, step in enumerate(payload["next_batch_phase_sequence"], start=1)
    )
    alias_rows = "\n".join(
        f"<tr><td><code>{escape(alias)}</code></td><td><code>{escape(_normalize_tag(alias))}</code></td></tr>"
        for alias in payload["trustpilot_tag_matching_policy"]["configured_aliases"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Completion and Next Batch Safety Design</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #2563eb; background: #eff6ff; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Completion and Next Batch Safety Design</h1>
  <p class="warning">Phase 3.24 is read/report-only. It does not call Gmail, Shopify, Kudosi, or Ali Reviews, and performs no writes.</p>
  <p>Status: <strong>{escape(payload["completion_next_batch_design_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <h2>Completion Summary</h2>
  <table><tbody>
    <tr><th>Trustpilot Gmail sent count</th><td>{escape(str(summary["trustpilot_gmail_sent_count"]))}</td></tr>
    <tr><th>Email sent confirmed</th><td>{escape(str(summary["email_sent_confirmed"]))}</td></tr>
    <tr><th>Shopify tag written</th><td><code>{escape(summary["shopify_tag_written"])}</code></td></tr>
    <tr><th>Written tag count</th><td>{escape(str(summary["written_tag_count"]))}</td></tr>
    <tr><th>Post-write audit passed</th><td>{escape(str(summary["post_write_audit_passed"]))}</td></tr>
    <tr><th>Canonical tag present</th><td>{escape(str(summary["canonical_tag_present"]))}</td></tr>
    <tr><th>Legacy typo tag detected</th><td>{escape(str(summary["legacy_typo_tag_detected"]))}</td></tr>
    <tr><th>Already completed Trustpilot invitation</th><td>{escape(str(summary["already_completed_trustpilot_invitation"]))}</td></tr>
    <tr><th>Duplicate classification if reprocessed</th><td><code>{escape(summary["current_order_duplicate_classification_if_reprocessed"])}</code></td></tr>
    <tr><th>No other orders processed</th><td>{escape(str(summary["no_other_orders_processed"]))}</td></tr>
  </tbody></table>
  <h2>Trustpilot Tag Alias Matching</h2>
  <table><thead><tr><th>Alias</th><th>Normalized form</th></tr></thead><tbody>{alias_rows}</tbody></table>
  <h2>Next Batch Phase Sequence</h2>
  <table><thead><tr><th>#</th><th>Phase</th></tr></thead><tbody>{sequence_rows}</tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>This Task Safety Flags</h2>
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
        payload["completion_next_batch_design_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "completion summary self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    return payload


def _is_masked_email(value: str) -> bool:
    return "***@" in str(value or "") and not EMAIL_RE.fullmatch(str(value or ""))


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


def _issue_summary(status: str, blocking_conditions: list[dict]) -> str:
    if status == SUCCESS_STATUS:
        return "Trustpilot single-order workflow is complete and the next-batch safety design is ready."
    return "Trustpilot completion/next-batch design blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    summary = payload["completion_summary"]
    return (
        "Shopify review request Phase 3.24 Trustpilot completion / next-batch safety design finished.\n"
        f"Status: {payload.get('completion_next_batch_design_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Trustpilot Gmail sent count: {summary.get('trustpilot_gmail_sent_count')}\n"
        f"Shopify tag written: {summary.get('shopify_tag_written')}\n"
        f"Written tag count: {summary.get('written_tag_count')}\n"
        f"Canonical tag present: {summary.get('canonical_tag_present')}\n"
        f"Legacy typo tag detected: {summary.get('legacy_typo_tag_detected')}\n"
        f"Already completed Trustpilot invitation: {summary.get('already_completed_trustpilot_invitation')}\n"
        f"Duplicate classification if reprocessed: {summary.get('current_order_duplicate_classification_if_reprocessed')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail API/draft/send, no Shopify API/write/mutation/tagsAdd/tagsRemove, no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
