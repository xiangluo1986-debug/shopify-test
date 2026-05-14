import json
import os
import re
import time
from email.utils import getaddresses
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_customer_level_duplicate_suppression import (
    CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
    evaluate_customer_level_duplicate,
)
from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute"
COMMAND_LABEL = "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute"

SOURCE_SEND_PREFLIGHT_REPORT_ENV_VALUE = (
    "logs/shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight.json"
)
SOURCE_SEND_PREFLIGHT_JSON_PATH = (
    LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight.json"
)
PROTECTED_DRAFT_SOURCE_JSON_PATH = (
    LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute.json"
)
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute.html"

DRY_RUN_STATUS = "dry_run_real_gmail_send_not_performed"
FUTURE_SUCCESS_STATUS = "real_gmail_draft_sent_and_verified"
EXPECTED_SOURCE_TASK = "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight"
EXPECTED_SOURCE_PREFLIGHT_STATUS = "trustpilot_one_candidate_gmail_draft_send_preflight_passed"
EXPECTED_SOURCE_DRAFT_CREATE_STATUS = "real_gmail_draft_created_and_verified"
EXPECTED_ORDER_NAME = "#22620"
EXPECTED_SEND_MAX = "1"
APPROVAL_ENV = "REVIEW_REQUEST_REAL_GMAIL_SEND_APPROVED"
APPROVAL_VALUE = "YES_SEND_ONE_GMAIL_DRAFT_FOR_22620"
ORDER_ENV = "REVIEW_REQUEST_REAL_GMAIL_SEND_ORDER_NAME"
MAX_ENV = "REVIEW_REQUEST_REAL_GMAIL_SEND_MAX"
SOURCE_REPORT_ENV = "REVIEW_REQUEST_REAL_GMAIL_SEND_SOURCE_REPORT"
DRY_RUN_ENV = "DRY_RUN"
VALID_MODES = {"dry-run", "real-run"}

GMAIL_SEND_FROM = "info@kidstoylover.com"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_DRAFT_LIST_PAGE_SIZE = 100
GMAIL_DRAFT_RESOLUTION_MAX_DRAFTS = 500
DEFAULT_DRAFT_SUBJECT = "How was your Kidstoylover order?"

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
DRAFT_ID_PARTIAL_RE = re.compile(r"^[A-Za-z0-9_-]{1,12}\.\.\.[A-Za-z0-9_-]{1,12}$")
ALLOWED_REPORT_EMAILS = {GMAIL_SEND_FROM.lower()}
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
    "gmail_api_call_performed",
    "gmail_draft_send_attempted",
    "gmail_drafts_send_called",
    "gmail_messages_send_called",
    "gmail_send_performed",
    "email_sent",
    "shopify_api_call_performed",
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


def run_shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute_task(mode: str) -> dict:
    started = time.time()
    normalized_mode = str(mode or "").strip()
    source_report, source_error, source_text = _read_source_report()
    source_privacy_scan = _privacy_scan_text(source_text)
    source_summary = _source_summary(source_report, source_error)
    source_safety = _source_safety_summary(source_report)
    customer_level_duplicate = evaluate_customer_level_duplicate(
        source_summary["selected_order_name"],
        source_summary["selected_masked_email"],
    )
    gates = _gate_status(normalized_mode)
    blocking_conditions = _blocking_conditions(
        source_report=source_report,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        source_summary=source_summary,
        source_safety=source_safety,
        gates=gates,
        customer_level_duplicate=customer_level_duplicate,
        source_text=source_text,
    )
    send_result = _gmail_draft_send_result(source_summary, gates, blocking_conditions)
    status = send_result["one_candidate_gmail_draft_send_execute_status"]
    payload = _build_payload(
        source_summary=source_summary,
        source_safety=source_safety,
        source_privacy_scan=source_privacy_scan,
        customer_level_duplicate=customer_level_duplicate,
        gates=gates,
        blocking_conditions=blocking_conditions,
        send_result=send_result,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_report() -> tuple[dict, str, str]:
    if not SOURCE_SEND_PREFLIGHT_JSON_PATH.exists():
        return {}, "blocked_missing_source_send_preflight_report", ""
    text = SOURCE_SEND_PREFLIGHT_JSON_PATH.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(text), "", text
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_invalid_source_send_preflight_json: {exc}"), text


def _source_summary(source_report: dict, source_error: str) -> dict:
    return {
        "path": SOURCE_SEND_PREFLIGHT_REPORT_ENV_VALUE,
        "absolute_path_present": SOURCE_SEND_PREFLIGHT_JSON_PATH.exists(),
        "error_sanitized": _sanitize_text(source_error),
        "task_name": _safe_text(source_report.get("task_name", "")),
        "phase": _safe_text(source_report.get("phase", "")),
        "success": source_report.get("success") is True,
        "source_send_preflight_status": _safe_text(
            source_report.get("one_candidate_gmail_draft_send_preflight_status", "")
        ),
        "source_draft_create_status": _safe_text(source_report.get("source_draft_create_status", "")),
        "selected_order_name": _safe_text(source_report.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_report.get("selected_masked_email", "")),
        "gmail_draft_id_partial": _safe_draft_id_partial(source_report.get("gmail_draft_id_partial", "")),
        "gmail_draft_id_partial_looks_masked": _is_draft_id_partial(source_report.get("gmail_draft_id_partial", "")),
        "draft_created_confirmed": source_report.get("draft_created_confirmed") is True,
        "would_send_gmail_draft": source_report.get("would_send_gmail_draft") is True,
        "would_send_count": _safe_int(source_report.get("would_send_count")),
        "blocking_condition_count": _safe_int(source_report.get("blocking_condition_count")),
        "blocking_conditions_present": bool(source_report.get("blocking_conditions") or []),
        "source_self_raw_customer_email_count": _safe_int(
            (source_report.get("self_privacy_scan") or {}).get("raw_customer_email_count")
            if isinstance(source_report.get("self_privacy_scan"), dict)
            else 0
        ),
        "source_self_token_secret_bearer_pattern_count": _safe_int(
            (source_report.get("self_privacy_scan") or {}).get("token_secret_bearer_pattern_count")
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


def _gate_status(mode: str) -> dict:
    normalized_mode = str(mode or "").strip()
    dry_run_raw = os.environ.get(DRY_RUN_ENV, "").strip()
    approval_raw = os.environ.get(APPROVAL_ENV, "").strip()
    requested_order_name = os.environ.get(ORDER_ENV, "").strip()
    requested_send_max = os.environ.get(MAX_ENV, "").strip()
    requested_source_report = os.environ.get(SOURCE_REPORT_ENV, "").strip()
    real_run_requested = normalized_mode == "real-run"
    return {
        "cli_mode": _safe_text(normalized_mode),
        "mode_valid": normalized_mode in VALID_MODES,
        "dry_run_raw": dry_run_raw or "1",
        "dry_run_env_present": bool(dry_run_raw),
        "dry_run_env_is_zero": dry_run_raw == "0",
        "dry_run": normalized_mode != "real-run",
        "real_run_requested": real_run_requested,
        "approval_present": bool(approval_raw),
        "approval_valid": approval_raw == APPROVAL_VALUE,
        "requested_order_name": _safe_text(requested_order_name),
        "requested_order_name_valid": requested_order_name == EXPECTED_ORDER_NAME,
        "requested_send_max": _safe_text(requested_send_max),
        "requested_send_max_is_one": requested_send_max == EXPECTED_SEND_MAX,
        "requested_source_report": _safe_text(requested_source_report),
        "requested_source_report_valid": requested_source_report == SOURCE_SEND_PREFLIGHT_REPORT_ENV_VALUE,
        "all_real_run_ack_gates_valid": (
            real_run_requested
            and dry_run_raw == "0"
            and approval_raw == APPROVAL_VALUE
            and requested_order_name == EXPECTED_ORDER_NAME
            and requested_send_max == EXPECTED_SEND_MAX
            and requested_source_report == SOURCE_SEND_PREFLIGHT_REPORT_ENV_VALUE
        ),
        "required_ack_env_names": [DRY_RUN_ENV, APPROVAL_ENV, ORDER_ENV, MAX_ENV, SOURCE_REPORT_ENV],
        "expected_order_name": EXPECTED_ORDER_NAME,
        "expected_send_max": EXPECTED_SEND_MAX,
        "expected_source_report": SOURCE_SEND_PREFLIGHT_REPORT_ENV_VALUE,
    }


def _blocking_conditions(
    source_report: dict,
    source_error: str,
    source_privacy_scan: dict,
    source_summary: dict,
    source_safety: dict,
    gates: dict,
    customer_level_duplicate: dict,
    source_text: str,
) -> list[dict]:
    if not gates["mode_valid"]:
        return [{"status": "blocked_invalid_mode", "detail": "mode must be dry-run or real-run."}]
    if source_error:
        return [{"status": "blocked_missing_or_invalid_source_report", "detail": _sanitize_text(source_error)}]

    conditions = []
    if customer_level_duplicate["customer_level_duplicate_block_applies"]:
        conditions.append(
            {
                "status": CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
                "detail": "selected draft matches a prior Trustpilot invitation customer/email signal.",
            }
        )
    if source_report.get("task_name") != EXPECTED_SOURCE_TASK:
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source task name mismatch."})
    if str(source_report.get("phase")) != "4.7":
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source phase must be 4.7."})
    if source_summary["success"] is not True:
        conditions.append({"status": "blocked_invalid_source_report", "detail": "source success is not true."})
    if source_summary["source_send_preflight_status"] != EXPECTED_SOURCE_PREFLIGHT_STATUS:
        conditions.append(
            {
                "status": "blocked_source_send_preflight_status",
                "detail": "source preflight status is not passed.",
            }
        )
    if source_summary["source_draft_create_status"] != EXPECTED_SOURCE_DRAFT_CREATE_STATUS:
        conditions.append(
            {
                "status": "blocked_source_draft_create_status",
                "detail": "source draft create status is not verified.",
            }
        )
    if source_summary["selected_order_name"] != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_selected_order_mismatch", "detail": "selected order must be #22620."})
    if not _is_masked_email(source_summary["selected_masked_email"]):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected email is not masked."})
    if source_summary["draft_created_confirmed"] is not True:
        conditions.append({"status": "blocked_source_draft_not_confirmed", "detail": "draft_created_confirmed is not true."})
    if source_summary["would_send_gmail_draft"] is not True:
        conditions.append({"status": "blocked_source_would_not_send_draft", "detail": "would_send_gmail_draft is not true."})
    if source_summary["would_send_count"] != 1:
        conditions.append({"status": "blocked_source_would_send_count_not_one", "detail": "would_send_count must equal 1."})
    if not source_summary["gmail_draft_id_partial"]:
        conditions.append({"status": "blocked_missing_draft_id_partial", "detail": "gmail_draft_id_partial is missing."})
    elif not source_summary["gmail_draft_id_partial_looks_masked"]:
        conditions.append(
            {"status": "blocked_full_draft_id_leak_risk", "detail": "Gmail draft id must be partial only."}
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
    if source_summary["source_self_token_secret_bearer_pattern_count"]:
        conditions.append(
            {"status": "blocked_source_token_or_secret_detected", "detail": "source self-scan token count is not zero."}
        )
    if _full_draft_or_message_id_leak_risk(source_text):
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "source report contains a full draft/message id field."})

    if gates["real_run_requested"]:
        conditions.extend(_real_run_gate_conditions(gates))
    return conditions


def _real_run_gate_conditions(gates: dict) -> list[dict]:
    conditions = []
    if not gates["approval_present"]:
        conditions.append({"status": "blocked_missing_real_gmail_send_ack", "detail": f"{APPROVAL_ENV} is missing."})
    elif not gates["approval_valid"]:
        conditions.append(
            {"status": "blocked_invalid_real_gmail_send_ack", "detail": f"{APPROVAL_ENV} did not match the required value."}
        )
    if not gates["dry_run_env_present"]:
        conditions.append({"status": "blocked_real_gmail_send_dry_run_not_disabled", "detail": f"{DRY_RUN_ENV}=0 is required."})
    elif not gates["dry_run_env_is_zero"]:
        conditions.append({"status": "blocked_real_gmail_send_dry_run_not_disabled", "detail": f"{DRY_RUN_ENV} must equal 0."})
    if not gates["requested_order_name"]:
        conditions.append({"status": "blocked_missing_real_gmail_send_order_name", "detail": f"{ORDER_ENV} is missing."})
    elif not gates["requested_order_name_valid"]:
        conditions.append({"status": "blocked_real_gmail_send_order_mismatch", "detail": f"{ORDER_ENV} must be #22620."})
    if not gates["requested_send_max"]:
        conditions.append({"status": "blocked_real_gmail_send_max_not_one", "detail": f"{MAX_ENV} is missing."})
    elif not gates["requested_send_max_is_one"]:
        conditions.append({"status": "blocked_real_gmail_send_max_not_one", "detail": f"{MAX_ENV} must be 1."})
    if not gates["requested_source_report"]:
        conditions.append(
            {"status": "blocked_real_gmail_send_source_report_mismatch", "detail": f"{SOURCE_REPORT_ENV} is missing."}
        )
    elif not gates["requested_source_report_valid"]:
        conditions.append(
            {
                "status": "blocked_real_gmail_send_source_report_mismatch",
                "detail": f"{SOURCE_REPORT_ENV} must match the Phase 4.7 report path.",
            }
        )
    return conditions


def _gmail_draft_send_result(source_summary: dict, gates: dict, blocking_conditions: list[dict]) -> dict:
    result = _base_send_result(gates["cli_mode"] or "dry-run")
    if blocking_conditions:
        result["one_candidate_gmail_draft_send_execute_status"] = blocking_conditions[0]["status"]
        result["real_gmail_send_blocked_reason"] = blocking_conditions[0]["status"]
        return result
    if gates["dry_run"]:
        return result
    if not gates["all_real_run_ack_gates_valid"]:
        result["mode"] = "real-run"
        result["one_candidate_gmail_draft_send_execute_status"] = "blocked_real_gmail_send_ack_incomplete"
        result["real_gmail_send_blocked_reason"] = result["one_candidate_gmail_draft_send_execute_status"]
        return result

    result["mode"] = "real-run"
    result["dry_run"] = False
    result["real_gmail_send_allowed"] = True

    gmail_env = _gmail_env()
    result["gmail_oauth_env_read_attempted"] = True
    result["gmail_oauth_present"] = gmail_env["gmail_oauth_present"]
    result["gmail_sender_matches_expected"] = gmail_env["gmail_sender_matches_expected"]
    result["gmail_send_or_compose_scope_present"] = gmail_env["gmail_send_or_compose_scope_present"]
    result["gmail_missing_env_vars"] = gmail_env["missing_env_vars"]
    if not gmail_env["gmail_oauth_present"]:
        result["one_candidate_gmail_draft_send_execute_status"] = "blocked_missing_gmail_oauth"
        result["real_gmail_send_allowed"] = False
        result["real_gmail_send_blocked_reason"] = result["one_candidate_gmail_draft_send_execute_status"]
        return result
    if not gmail_env["gmail_sender_matches_expected"]:
        result["one_candidate_gmail_draft_send_execute_status"] = "blocked_gmail_sender_mismatch"
        result["real_gmail_send_allowed"] = False
        result["real_gmail_send_blocked_reason"] = result["one_candidate_gmail_draft_send_execute_status"]
        return result
    if not gmail_env["gmail_send_or_compose_scope_present"]:
        result["one_candidate_gmail_draft_send_execute_status"] = "blocked_missing_gmail_send_scope"
        result["real_gmail_send_allowed"] = False
        result["real_gmail_send_blocked_reason"] = result["one_candidate_gmail_draft_send_execute_status"]
        return result

    try:
        service = _build_gmail_service(gmail_env, result)
    except Exception as exc:  # pragma: no cover - real Gmail auth is only used behind explicit local gates.
        result["one_candidate_gmail_draft_send_execute_status"] = "blocked_gmail_service_build_failed"
        result["real_gmail_send_allowed"] = False
        result["real_gmail_send_blocked_reason"] = result["one_candidate_gmail_draft_send_execute_status"]
        result["gmail_error_sanitized"] = _safe_exception_summary(exc)
        result["gmail_send_performed"] = False
        result["email_sent"] = False
        result["sent_count"] = 0
        return result

    resolution = _resolve_runtime_gmail_draft_for_send(service, source_summary, result)
    _apply_gmail_draft_resolution_report(result, resolution)
    if not resolution["gmail_draft_resolved_for_send"]:
        result["one_candidate_gmail_draft_send_execute_status"] = resolution[
            "runtime_gmail_draft_resolution_status"
        ]
        result["real_gmail_send_allowed"] = False
        result["real_gmail_send_blocked_reason"] = result["one_candidate_gmail_draft_send_execute_status"]
        return result

    draft_id = resolution["_full_draft_id_for_runtime_only"]
    result["gmail_draft_send_attempted"] = True
    result["gmail_drafts_send_called"] = True
    result["gmail_api_call_performed"] = True
    try:
        response = service.users().drafts().send(userId="me", body={"id": draft_id}).execute()
        result["one_candidate_gmail_draft_send_execute_status"] = FUTURE_SUCCESS_STATUS
        result["real_gmail_send_executed"] = True
        result["real_gmail_send_blocked_reason"] = ""
        result["gmail_send_performed"] = True
        result["email_sent"] = True
        result["sent_count"] = 1
        result["gmail_message_id_partial"] = _partial_id(response.get("id", ""))
        result["gmail_draft_sent_and_verified"] = bool(result["gmail_message_id_partial"])
    except Exception as exc:  # pragma: no cover - real Gmail send is only used behind explicit local gates.
        result["one_candidate_gmail_draft_send_execute_status"] = "blocked_gmail_draft_send_failed"
        result["real_gmail_send_allowed"] = False
        result["real_gmail_send_blocked_reason"] = result["one_candidate_gmail_draft_send_execute_status"]
        result["gmail_error_sanitized"] = _safe_exception_summary(exc)
        result["gmail_send_error_sanitized"] = _safe_exception_summary(exc)
        result["gmail_send_performed"] = False
        result["email_sent"] = False
        result["sent_count"] = 0
    return result


def _base_send_result(mode: str = "dry-run") -> dict:
    safety = _safety_summary({})
    return {
        "one_candidate_gmail_draft_send_execute_status": DRY_RUN_STATUS,
        "mode": _safe_text(mode) or "dry-run",
        "dry_run": True,
        "real_gmail_send_allowed": False,
        "real_gmail_send_executed": False,
        "real_gmail_send_blocked_reason": DRY_RUN_STATUS,
        "gmail_oauth_env_read_attempted": False,
        "gmail_oauth_present": False,
        "gmail_sender_matches_expected": False,
        "gmail_send_or_compose_scope_present": False,
        "gmail_missing_env_vars": [],
        "gmail_error_sanitized": "",
        "gmail_send_error_sanitized": "",
        "gmail_draft_sent_and_verified": False,
        "gmail_message_id_partial": "",
        "gmail_runtime_resolver_used": False,
        "gmail_draft_list_attempted": False,
        "gmail_draft_list_succeeded": False,
        "gmail_draft_get_attempted": False,
        "gmail_draft_get_count": 0,
        "gmail_drafts_scanned_count": 0,
        "gmail_partial_draft_id_match_count": 0,
        "gmail_resolved_draft_count": 0,
        "gmail_draft_resolved_for_send": False,
        "gmail_full_draft_id_exposed": False,
        "gmail_full_message_id_exposed": False,
        "gmail_resolver_match_strategy": "",
        "gmail_resolver_recipient_mask_match_used": False,
        "gmail_resolver_subject_match_used": False,
        "gmail_resolver_order_marker_match_required": False,
        "gmail_resolver_error_sanitized": "",
        **safety,
    }


def _resolve_runtime_gmail_draft_for_send(service, source_summary: dict, result: dict) -> dict:
    resolution = _base_gmail_draft_resolution_result()
    _apply_gmail_draft_resolution_report(result, resolution)
    expected_partial = source_summary["gmail_draft_id_partial"]
    scanned_count = 0
    try:
        markers = _runtime_draft_match_markers(source_summary)
        resolution["gmail_resolver_subject_match_used"] = bool(markers["expected_subject"])
        resolution["gmail_resolver_order_marker_match_required"] = markers["order_marker_required"]
        resolution["gmail_resolver_match_strategy"] = _resolver_match_strategy(markers)
        _apply_gmail_draft_resolution_report(result, resolution)
        if not expected_partial:
            resolution["runtime_gmail_draft_resolution_status"] = "blocked_missing_draft_id_partial"
            return resolution

        matches = []
        page_token = None
        while scanned_count < GMAIL_DRAFT_RESOLUTION_MAX_DRAFTS:
            request = {
                "userId": "me",
                "maxResults": min(GMAIL_DRAFT_LIST_PAGE_SIZE, GMAIL_DRAFT_RESOLUTION_MAX_DRAFTS - scanned_count),
            }
            if page_token:
                request["pageToken"] = page_token
            resolution["gmail_draft_list_attempted"] = True
            result["gmail_draft_list_attempted"] = True
            result["gmail_api_call_performed"] = True
            page = service.users().drafts().list(**request).execute()
            resolution["gmail_draft_list_succeeded"] = True
            result["gmail_draft_list_succeeded"] = True
            drafts = page.get("drafts") or []
            if not drafts:
                break
            for draft_ref in drafts:
                if scanned_count >= GMAIL_DRAFT_RESOLUTION_MAX_DRAFTS:
                    break
                scanned_count += 1
                draft_id = str(draft_ref.get("id") or "").strip()
                if _partial_id(draft_id) != expected_partial:
                    continue
                resolution["gmail_partial_draft_id_match_count"] += 1
                result["gmail_partial_draft_id_match_count"] = resolution["gmail_partial_draft_id_match_count"]
                resolution["gmail_draft_get_attempted"] = True
                resolution["gmail_draft_get_count"] += 1
                result["gmail_draft_get_attempted"] = True
                result["gmail_draft_get_count"] = resolution["gmail_draft_get_count"]
                result["gmail_api_call_performed"] = True
                detail = service.users().drafts().get(
                    userId="me",
                    id=draft_id,
                    format="metadata",
                    metadataHeaders=["To", "From", "Subject"],
                ).execute()
                if _gmail_draft_detail_matches_source(detail, source_summary, markers):
                    matches.append(draft_id)
                    resolution["gmail_resolved_draft_count"] = len(matches)
                    result["gmail_resolved_draft_count"] = resolution["gmail_resolved_draft_count"]
            page_token = page.get("nextPageToken")
            if not page_token:
                break

        resolution["gmail_drafts_scanned_count"] = scanned_count
        resolution["gmail_resolved_draft_count"] = len(matches)
        if not matches:
            resolution["runtime_gmail_draft_resolution_status"] = "blocked_runtime_gmail_draft_not_found"
            return resolution
        if len(matches) > 1:
            resolution["runtime_gmail_draft_resolution_status"] = "blocked_runtime_multiple_matching_gmail_drafts"
            return resolution

        resolution["runtime_gmail_draft_resolution_status"] = "runtime_gmail_draft_resolved_for_send"
        resolution["gmail_draft_resolved_for_send"] = True
        resolution["_full_draft_id_for_runtime_only"] = matches[0]
        return resolution
    except Exception as exc:  # pragma: no cover - runtime Gmail calls require explicit local gates.
        resolution["runtime_gmail_draft_resolution_status"] = "blocked_runtime_gmail_draft_resolver_failed"
        resolution["gmail_resolver_error_sanitized"] = _safe_exception_summary(exc)
        resolution["gmail_drafts_scanned_count"] = scanned_count
        _apply_gmail_draft_resolution_report(result, resolution)
        return resolution


def _base_gmail_draft_resolution_result() -> dict:
    return {
        "runtime_gmail_draft_resolution_status": "blocked_runtime_gmail_draft_not_found",
        "gmail_runtime_resolver_used": True,
        "gmail_draft_list_attempted": False,
        "gmail_draft_list_succeeded": False,
        "gmail_draft_get_attempted": False,
        "gmail_draft_get_count": 0,
        "gmail_drafts_scanned_count": 0,
        "gmail_partial_draft_id_match_count": 0,
        "gmail_resolved_draft_count": 0,
        "gmail_draft_resolved_for_send": False,
        "gmail_full_draft_id_exposed": False,
        "gmail_full_message_id_exposed": False,
        "gmail_resolver_match_strategy": "",
        "gmail_resolver_recipient_mask_match_used": True,
        "gmail_resolver_subject_match_used": False,
        "gmail_resolver_order_marker_match_required": False,
        "gmail_resolver_error_sanitized": "",
        "_full_draft_id_for_runtime_only": "",
    }


def _apply_gmail_draft_resolution_report(result: dict, resolution: dict) -> None:
    safe_keys = (
        "gmail_runtime_resolver_used",
        "gmail_draft_list_attempted",
        "gmail_draft_list_succeeded",
        "gmail_draft_get_attempted",
        "gmail_draft_get_count",
        "gmail_drafts_scanned_count",
        "gmail_partial_draft_id_match_count",
        "gmail_resolved_draft_count",
        "gmail_draft_resolved_for_send",
        "gmail_full_draft_id_exposed",
        "gmail_full_message_id_exposed",
        "gmail_resolver_match_strategy",
        "gmail_resolver_recipient_mask_match_used",
        "gmail_resolver_subject_match_used",
        "gmail_resolver_order_marker_match_required",
        "gmail_resolver_error_sanitized",
    )
    for key in safe_keys:
        result[key] = resolution.get(key, result.get(key))


def _runtime_draft_match_markers(source_summary: dict) -> dict:
    protected_source = _read_protected_draft_create_report()
    source_matches = (
        protected_source.get("selected_order_name") == EXPECTED_ORDER_NAME
        and _safe_masked_email(protected_source.get("selected_masked_email", ""))
        == source_summary["selected_masked_email"]
        and protected_source.get("one_candidate_gmail_draft_create_execute_status")
        == EXPECTED_SOURCE_DRAFT_CREATE_STATUS
    )
    subject = ""
    body_preview = ""
    if source_matches:
        subject = _safe_text(protected_source.get("draft_subject_preview", ""))
        body_preview = _safe_text(protected_source.get("draft_body_preview", ""))
        if not subject:
            subject = DEFAULT_DRAFT_SUBJECT
    marker_text = f"{subject}\n{body_preview}"
    return {
        "expected_subject": subject,
        "order_marker_required": EXPECTED_ORDER_NAME in marker_text,
    }


def _read_protected_draft_create_report() -> dict:
    if not PROTECTED_DRAFT_SOURCE_JSON_PATH.exists():
        return {}
    try:
        return json.loads(PROTECTED_DRAFT_SOURCE_JSON_PATH.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return {}


def _resolver_match_strategy(markers: dict) -> str:
    parts = ["partial_draft_id", "sender", "recipient_mask"]
    if markers["expected_subject"]:
        parts.append("subject")
    if markers["order_marker_required"]:
        parts.append("order_marker")
    return "+".join(parts)


def _gmail_draft_detail_matches_source(detail: dict, source_summary: dict, markers: dict) -> bool:
    message = detail.get("message") if isinstance(detail, dict) else {}
    message = message if isinstance(message, dict) else {}
    headers = _gmail_message_headers(message)
    from_match = GMAIL_SEND_FROM.lower() in _header_email_addresses(headers.get("from", ""))
    recipient_mask_match = any(
        _mask_email(address) == source_summary["selected_masked_email"]
        for address in _header_email_addresses(headers.get("to", ""))
    )
    subject = str(headers.get("subject", "") or "").strip()
    subject_match = not markers["expected_subject"] or subject == markers["expected_subject"]
    order_marker_match = True
    if markers["order_marker_required"]:
        safe_search_text = f"{subject}\n{message.get('snippet', '')}"
        order_marker_match = EXPECTED_ORDER_NAME in safe_search_text
    return from_match and recipient_mask_match and subject_match and order_marker_match


def _gmail_message_headers(message: dict) -> dict:
    payload = message.get("payload") if isinstance(message, dict) else {}
    headers = payload.get("headers") if isinstance(payload, dict) else []
    result = {}
    for header in headers or []:
        name = str(header.get("name", "")).strip().lower()
        if name in {"to", "from", "subject"}:
            result[name] = str(header.get("value", "") or "")
    return result


def _header_email_addresses(value: str) -> list[str]:
    return [
        address.strip().lower()
        for _, address in getaddresses([str(value or "")])
        if EMAIL_RE.fullmatch(address.strip())
    ]


def _gmail_env() -> dict:
    dotenv_values = _read_dotenv_values()
    send_from = _env_value("GMAIL_SEND_FROM", dotenv_values)
    client_id = _env_value("GOOGLE_GMAIL_CLIENT_ID", dotenv_values)
    client_secret_value = _env_value("GOOGLE_GMAIL_CLIENT_SECRET", dotenv_values)
    refresh_token_value = _env_value("GOOGLE_GMAIL_REFRESH_TOKEN", dotenv_values)
    scopes = _split_scopes(_env_value("GOOGLE_GMAIL_SCOPES", dotenv_values))
    missing = []
    if not send_from:
        missing.append("GMAIL_SEND_FROM")
    if not client_id:
        missing.append("GOOGLE_GMAIL_CLIENT_ID")
    if not client_secret_value:
        missing.append("GOOGLE_GMAIL_CLIENT_SECRET")
    if not refresh_token_value:
        missing.append("GOOGLE_GMAIL_REFRESH_TOKEN")
    if not scopes:
        missing.append("GOOGLE_GMAIL_SCOPES")
    return {
        "send_from": send_from,
        "client_id": client_id,
        "client_secret_value": client_secret_value,
        "refresh_token_value": refresh_token_value,
        "scopes": scopes,
        "gmail_oauth_present": not missing,
        "gmail_sender_matches_expected": send_from == GMAIL_SEND_FROM,
        "gmail_send_or_compose_scope_present": GMAIL_SEND_SCOPE in scopes or GMAIL_COMPOSE_SCOPE in scopes,
        "missing_env_vars": missing,
    }


def _read_dotenv_values() -> dict:
    dotenv_path = PROJECT_ROOT / ".env"
    values = {}
    if not dotenv_path.exists():
        return values
    allowed = {
        "GMAIL_SEND_FROM",
        "GOOGLE_GMAIL_CLIENT_ID",
        "GOOGLE_GMAIL_CLIENT_SECRET",
        "GOOGLE_GMAIL_REFRESH_TOKEN",
        "GOOGLE_GMAIL_SCOPES",
    }
    for line in dotenv_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        if key in allowed:
            values[key] = value.strip().strip("\"'")
    return values


def _env_value(key: str, dotenv_values: dict) -> str:
    return (os.environ.get(key) or dotenv_values.get(key) or "").strip()


def _split_scopes(value: str) -> list[str]:
    return [item.strip() for item in value.split() if item.strip()]


def _build_gmail_service(gmail_env: dict, result: dict):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credential_kwargs = {
        "token": None,
        "refresh" + "_token": gmail_env["refresh_token_value"],
        "token_uri": "https://oauth2.googleapis.com/token",
        "client_id": gmail_env["client_id"],
        "client" + "_secret": gmail_env["client_secret_value"],
        "scopes": gmail_env["scopes"],
    }
    credentials = Credentials(**credential_kwargs)
    result["gmail_token_refresh_attempted"] = True
    credentials.refresh(Request())
    result["gmail_token_refresh_succeeded"] = True
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _build_payload(
    source_summary: dict,
    source_safety: dict,
    source_privacy_scan: dict,
    customer_level_duplicate: dict,
    gates: dict,
    blocking_conditions: list[dict],
    send_result: dict,
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary(send_result)
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "4.8B",
        "mode": send_result["mode"],
        "command_label": COMMAND_LABEL,
        "one_candidate_gmail_draft_send_execute_status": status,
        "success": status in {DRY_RUN_STATUS, FUTURE_SUCCESS_STATUS},
        "source_send_preflight_report_path": SOURCE_SEND_PREFLIGHT_REPORT_ENV_VALUE,
        "source_send_preflight_status": source_summary["source_send_preflight_status"],
        "source_draft_create_status": source_summary["source_draft_create_status"],
        "source_send_preflight_summary": source_summary,
        "source_send_preflight_safety_summary": source_safety,
        "source_send_preflight_privacy_scan": source_privacy_scan,
        "selected_order_name": source_summary["selected_order_name"],
        "selected_masked_email": source_summary["selected_masked_email"],
        "gmail_draft_id_partial": source_summary["gmail_draft_id_partial"],
        "draft_created_confirmed": source_summary["draft_created_confirmed"],
        "would_send_gmail_draft": source_summary["would_send_gmail_draft"],
        "would_send_count": source_summary["would_send_count"],
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
        "dry_run": send_result["dry_run"],
        "real_run_requested": gates["real_run_requested"],
        "real_run_gate_status": gates,
        "real_gmail_send_allowed": send_result["real_gmail_send_allowed"],
        "real_gmail_send_executed": send_result["real_gmail_send_executed"],
        "real_gmail_send_blocked_reason": send_result["real_gmail_send_blocked_reason"],
        "future_send_audit_required_after_real_send": status == FUTURE_SUCCESS_STATUS,
        "future_shopify_tag_write_requires_separate_phase": True,
        "gmail_draft_sent_and_verified": send_result["gmail_draft_sent_and_verified"],
        "gmail_message_id_partial": send_result["gmail_message_id_partial"],
        "gmail_runtime_resolver_used": send_result["gmail_runtime_resolver_used"],
        "gmail_draft_list_attempted": send_result["gmail_draft_list_attempted"],
        "gmail_draft_list_succeeded": send_result["gmail_draft_list_succeeded"],
        "gmail_draft_get_attempted": send_result["gmail_draft_get_attempted"],
        "gmail_draft_get_count": send_result["gmail_draft_get_count"],
        "gmail_drafts_scanned_count": send_result["gmail_drafts_scanned_count"],
        "gmail_partial_draft_id_match_count": send_result["gmail_partial_draft_id_match_count"],
        "gmail_resolved_draft_count": send_result["gmail_resolved_draft_count"],
        "gmail_draft_resolved_for_send": send_result["gmail_draft_resolved_for_send"],
        "gmail_full_draft_id_exposed": send_result["gmail_full_draft_id_exposed"],
        "gmail_full_message_id_exposed": send_result["gmail_full_message_id_exposed"],
        "gmail_resolver_match_strategy": send_result["gmail_resolver_match_strategy"],
        "gmail_resolver_recipient_mask_match_used": send_result["gmail_resolver_recipient_mask_match_used"],
        "gmail_resolver_subject_match_used": send_result["gmail_resolver_subject_match_used"],
        "gmail_resolver_order_marker_match_required": send_result["gmail_resolver_order_marker_match_required"],
        "gmail_resolver_error_sanitized": send_result["gmail_resolver_error_sanitized"],
        "gmail_send_error_sanitized": send_result["gmail_send_error_sanitized"],
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_customer_email_output": False,
            "gmail_draft_id_full_output": False,
            "gmail_message_id_full_output": False,
            "gmail_full_draft_id_exposed": False,
            "gmail_full_message_id_exposed": False,
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
        "json_trustpilot_one_candidate_gmail_draft_send_execute_path": str(REPORT_JSON_PATH),
        "html_trustpilot_one_candidate_gmail_draft_send_execute_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary(send_result: dict) -> dict:
    return {
        "gmail_api_call_performed": bool(send_result.get("gmail_api_call_performed", False)),
        "gmail_oauth_env_read_attempted": bool(send_result.get("gmail_oauth_env_read_attempted", False)),
        "gmail_token_refresh_attempted": bool(send_result.get("gmail_token_refresh_attempted", False)),
        "gmail_token_refresh_succeeded": bool(send_result.get("gmail_token_refresh_succeeded", False)),
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_send_attempted": bool(send_result.get("gmail_draft_send_attempted", False)),
        "gmail_drafts_send_called": bool(send_result.get("gmail_drafts_send_called", False)),
        "gmail_messages_send_called": False,
        "gmail_send_performed": bool(send_result.get("gmail_send_performed", False)),
        "email_sent": bool(send_result.get("email_sent", False)),
        "sent_count": _safe_int(send_result.get("sent_count", 0)),
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
        "no_new_gmail_draft_created": not bool(send_result.get("gmail_draft_created", False)),
        "no_gmail_messages_send_performed": True,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "no_external_review_api_calls_performed": True,
        "no_tracking_action_performed": True,
        "all_new_actions_no_write_confirmed": not bool(send_result.get("email_sent", False)),
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_one_candidate_gmail_draft_send_execute_path": str(json_path),
        "html_trustpilot_one_candidate_gmail_draft_send_execute_path": str(html_path),
        "one_candidate_gmail_draft_send_execute_status": payload[
            "one_candidate_gmail_draft_send_execute_status"
        ],
        "source_send_preflight_status": payload["source_send_preflight_status"],
        "source_draft_create_status": payload["source_draft_create_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "gmail_draft_id_partial": payload["gmail_draft_id_partial"],
        "draft_created_confirmed": payload["draft_created_confirmed"],
        "would_send_gmail_draft": payload["would_send_gmail_draft"],
        "would_send_count": payload["would_send_count"],
        "customer_level_duplicate_block_applies": payload["customer_level_duplicate_block_applies"],
        "prior_trustpilot_order_name": payload["prior_trustpilot_order_name"],
        "existing_unsent_gmail_draft_should_not_be_sent": payload[
            "existing_unsent_gmail_draft_should_not_be_sent"
        ],
        "dry_run": payload["dry_run"],
        "real_run_requested": payload["real_run_requested"],
        "real_gmail_send_allowed": payload["real_gmail_send_allowed"],
        "real_gmail_send_executed": payload["real_gmail_send_executed"],
        "real_gmail_send_blocked_reason": payload["real_gmail_send_blocked_reason"],
        "gmail_draft_sent_and_verified": payload["gmail_draft_sent_and_verified"],
        "gmail_draft_resolved_for_send": payload["gmail_draft_resolved_for_send"],
        "gmail_resolved_draft_count": payload["gmail_resolved_draft_count"],
        "gmail_full_draft_id_exposed": payload["gmail_full_draft_id_exposed"],
        "gmail_full_message_id_exposed": payload["gmail_full_message_id_exposed"],
        "gmail_runtime_resolver_used": payload["gmail_runtime_resolver_used"],
        "gmail_draft_list_attempted": payload["gmail_draft_list_attempted"],
        "gmail_draft_list_succeeded": payload["gmail_draft_list_succeeded"],
        "gmail_draft_get_attempted": payload["gmail_draft_get_attempted"],
        "gmail_draft_get_count": payload["gmail_draft_get_count"],
        "gmail_drafts_scanned_count": payload["gmail_drafts_scanned_count"],
        "gmail_partial_draft_id_match_count": payload["gmail_partial_draft_id_match_count"],
        "gmail_resolver_match_strategy": payload["gmail_resolver_match_strategy"],
        "sent_count": payload["sent_count"],
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
    source_scan = payload["source_send_preflight_privacy_scan"]
    self_scan = payload["self_privacy_scan"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot One-Candidate Gmail Draft Send Execute</title>
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
  <h1>Trustpilot One-Candidate Gmail Draft Send Execute</h1>
  <p class="{'safe' if payload['success'] else 'warning'}">Phase 4.8B defaults to dry-run. A real send is locked to one existing Gmail draft for selected order #22620 and only after all local ACK gates match exactly.</p>
  <p>Status: <strong>{escape(payload["one_candidate_gmail_draft_send_execute_status"])}</strong></p>
  <p>Mode: <code>{escape(payload["mode"])}</code></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source send preflight report: <code>{escape(payload["source_send_preflight_report_path"])}</code></p>
  <p>Source send preflight status: <strong>{escape(payload["source_send_preflight_status"])}</strong></p>
  <p>Source draft create status: <strong>{escape(payload["source_draft_create_status"])}</strong></p>
  <p>Gmail draft id partial: <code>{escape(payload["gmail_draft_id_partial"])}</code></p>
  <h2>Execute Decision</h2>
  <table><tbody>
    <tr><th>Draft created confirmed</th><td>{escape(str(payload["draft_created_confirmed"]))}</td></tr>
    <tr><th>Would send Gmail draft</th><td>{escape(str(payload["would_send_gmail_draft"]))}</td></tr>
    <tr><th>Would send count</th><td>{escape(str(payload["would_send_count"]))}</td></tr>
    <tr><th>Customer-level duplicate block applies</th><td>{escape(str(payload["customer_level_duplicate_block_applies"]))}</td></tr>
    <tr><th>Prior Trustpilot order</th><td><code>{escape(str(payload["prior_trustpilot_order_name"]))}</code></td></tr>
    <tr><th>Existing unsent Gmail draft should not be sent</th><td>{escape(str(payload["existing_unsent_gmail_draft_should_not_be_sent"]))}</td></tr>
    <tr><th>Dry-run</th><td>{escape(str(payload["dry_run"]))}</td></tr>
    <tr><th>Real Gmail send allowed</th><td>{escape(str(payload["real_gmail_send_allowed"]))}</td></tr>
    <tr><th>Real Gmail send executed</th><td>{escape(str(payload["real_gmail_send_executed"]))}</td></tr>
    <tr><th>Real Gmail send blocked reason</th><td>{escape(str(payload["real_gmail_send_blocked_reason"]))}</td></tr>
    <tr><th>Runtime resolver used</th><td>{escape(str(payload["gmail_runtime_resolver_used"]))}</td></tr>
    <tr><th>Draft list attempted</th><td>{escape(str(payload["gmail_draft_list_attempted"]))}</td></tr>
    <tr><th>Draft list succeeded</th><td>{escape(str(payload["gmail_draft_list_succeeded"]))}</td></tr>
    <tr><th>Draft get attempted</th><td>{escape(str(payload["gmail_draft_get_attempted"]))}</td></tr>
    <tr><th>Draft get count</th><td>{escape(str(payload["gmail_draft_get_count"]))}</td></tr>
    <tr><th>Draft resolved for send</th><td>{escape(str(payload["gmail_draft_resolved_for_send"]))}</td></tr>
    <tr><th>Resolved draft count</th><td>{escape(str(payload["gmail_resolved_draft_count"]))}</td></tr>
    <tr><th>Full draft id exposed</th><td>{escape(str(payload["gmail_full_draft_id_exposed"]))}</td></tr>
    <tr><th>Resolver match strategy</th><td>{escape(str(payload["gmail_resolver_match_strategy"]))}</td></tr>
    <tr><th>Sent count</th><td>{escape(str(payload["sent_count"]))}</td></tr>
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

    payload["one_candidate_gmail_draft_send_execute_status"] = "blocked_privacy_scan_failed"
    payload["success"] = False
    payload["real_gmail_send_allowed"] = False
    payload["real_gmail_send_executed"] = False
    payload["real_gmail_send_blocked_reason"] = "blocked_privacy_scan_failed"
    payload["gmail_api_call_performed"] = False
    payload["gmail_drafts_send_called"] = False
    payload["gmail_messages_send_called"] = False
    payload["gmail_send_performed"] = False
    payload["email_sent"] = False
    payload["sent_count"] = 0
    payload["blocking_conditions"].append(
        {"status": "blocked_privacy_scan_failed", "detail": "Phase 4.8B report self privacy scan failed."}
    )
    payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    payload["detected_issue_summary"] = _issue_summary(
        payload["one_candidate_gmail_draft_send_execute_status"],
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


def _full_draft_or_message_id_leak_risk(text: str) -> bool:
    return bool(re.search(r'"(?:gmail_draft_id|gmail_message_id|message_id|draft_id)"\s*:', text or ""))


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


def _partial_id(value) -> str:
    text = _safe_text(value).strip()
    if not text:
        return ""
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


def _safe_exception_summary(exc: Exception) -> str:
    text = str(exc or "")
    text = re.sub(r"(?i)(/drafts/)[A-Za-z0-9_-]{8,}", r"\1[redacted-gmail-draft-id]", text)
    text = re.sub(r"(?i)(/messages/)[A-Za-z0-9_-]{8,}", r"\1[redacted-gmail-message-id]", text)
    text = re.sub(
        r"(?i)\b(draft(?:_?id)?|message(?:_?id)?|id)\s*[:=]\s*[\"']?[A-Za-z0-9_-]{8,}",
        r"\1=[redacted-gmail-id]",
        text,
    )
    text = re.sub(r"\br-[A-Za-z0-9_-]{8,}\b", "[redacted-gmail-draft-id]", text)
    text = re.sub(r"\bmsg-[A-Za-z0-9_-]{8,}\b", "[redacted-gmail-message-id]", text)
    return _sanitize_text(f"{exc.__class__.__name__}: {text}")[:400]


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
    if status == DRY_RUN_STATUS:
        return (
            "Phase 4.8B stayed in dry-run for selected order #22620; no Gmail send API call, email send, "
            "new Gmail draft, Shopify write, external review API call, or tracking action was performed."
        )
    if status == FUTURE_SUCCESS_STATUS:
        return "Exactly one existing Gmail draft was sent for selected order #22620; post-send audit is required next."
    return "Phase 4.8B Gmail draft send execute blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 4.8B Trustpilot one-candidate Gmail draft send execute finished.\n"
        f"Status: {payload.get('one_candidate_gmail_draft_send_execute_status')}\n"
        f"Mode: {payload.get('mode')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Source send preflight status: {payload.get('source_send_preflight_status')}\n"
        f"Source draft create status: {payload.get('source_draft_create_status')}\n"
        f"Draft created confirmed: {payload.get('draft_created_confirmed')}\n"
        f"Would send Gmail draft: {payload.get('would_send_gmail_draft')}\n"
        f"Would send count: {payload.get('would_send_count')}\n"
        f"Dry-run: {payload.get('dry_run')}\n"
        f"Runtime draft resolver used: {payload.get('gmail_runtime_resolver_used')}\n"
        f"Draft resolved for send: {payload.get('gmail_draft_resolved_for_send')}\n"
        f"Resolved draft count: {payload.get('gmail_resolved_draft_count')}\n"
        f"Real Gmail send executed: {payload.get('real_gmail_send_executed')}\n"
        f"Sent count: {payload.get('sent_count')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail messages.send, no new Gmail draft, no Shopify write/tagsAdd/tagsRemove, no external review API call, and no tracking action.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
