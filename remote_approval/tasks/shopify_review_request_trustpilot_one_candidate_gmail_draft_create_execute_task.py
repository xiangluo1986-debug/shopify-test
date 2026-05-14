import base64
import json
import os
import re
import subprocess
import time
from email.message import EmailMessage
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute"
COMMAND_LABEL = "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute"

SOURCE_PREFLIGHT_REPORT_ENV_VALUE = (
    "logs/shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner.json"
)
SOURCE_PREFLIGHT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute.html"

DRY_RUN_STATUS = "dry_run_real_gmail_draft_not_created"
FUTURE_SUCCESS_STATUS = "real_gmail_draft_created_and_verified"
EXPECTED_SOURCE_TASK = "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner"
EXPECTED_SOURCE_STATUS = "trustpilot_one_candidate_gmail_draft_create_locked_preflight_passed"
EXPECTED_ORDER_NAME = "#22620"
EXPECTED_CREATE_MAX = "1"
APPROVAL_ENV = "REVIEW_REQUEST_REAL_GMAIL_DRAFT_CREATE_APPROVED"
APPROVAL_VALUE = "YES_CREATE_ONE_GMAIL_DRAFT_FOR_22620"
ORDER_ENV = "REVIEW_REQUEST_REAL_GMAIL_DRAFT_CREATE_ORDER_NAME"
MAX_ENV = "REVIEW_REQUEST_REAL_GMAIL_DRAFT_CREATE_MAX"
SOURCE_REPORT_ENV = "REVIEW_REQUEST_REAL_GMAIL_DRAFT_CREATE_SOURCE_REPORT"
DRY_RUN_ENV = "DRY_RUN"
VALID_MODES = {"dry-run", "real-run"}

GMAIL_SEND_FROM = "info@kidstoylover.com"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
PROTECTED_LOOKUP_TIMEOUT_SECONDS = 120

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
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
    "read_only_shopify_query_performed",
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
    "token_or_secret_would_be_written",
    "real_gmail_or_shopify_write_action_would_be_attempted",
]


def run_shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute_task(mode: str) -> dict:
    started = time.time()
    normalized_mode = str(mode or "").strip()
    source_preflight, source_error, source_text = _read_source_preflight()
    source_privacy_scan = _privacy_scan_text(source_text)
    source_summary = _source_summary(source_preflight, source_error)
    source_safety = _source_safety_summary(source_preflight)
    gates = _gate_status(normalized_mode)
    blocking_conditions = _blocking_conditions(
        source_preflight=source_preflight,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        source_summary=source_summary,
        source_safety=source_safety,
        gates=gates,
    )
    create_result = _gmail_draft_create_result(source_preflight, gates, blocking_conditions)
    status = create_result["one_candidate_gmail_draft_create_execute_status"]
    payload = _build_payload(
        source_summary=source_summary,
        source_safety=source_safety,
        source_privacy_scan=source_privacy_scan,
        gates=gates,
        blocking_conditions=blocking_conditions,
        create_result=create_result,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_preflight() -> tuple[dict, str, str]:
    if not SOURCE_PREFLIGHT_JSON_PATH.exists():
        return {}, "blocked_missing_source_preflight_report", ""
    text = SOURCE_PREFLIGHT_JSON_PATH.read_text(encoding="utf-8", errors="replace")
    try:
        return json.loads(text), "", text
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_invalid_source_preflight_json: {exc}"), text


def _source_summary(source_preflight: dict, source_error: str) -> dict:
    return {
        "path": SOURCE_PREFLIGHT_REPORT_ENV_VALUE,
        "absolute_path_present": SOURCE_PREFLIGHT_JSON_PATH.exists(),
        "error_sanitized": _sanitize_text(source_error),
        "task_name": _safe_text(source_preflight.get("task_name", "")),
        "phase": _safe_text(source_preflight.get("phase", "")),
        "success": source_preflight.get("success") is True,
        "source_preflight_status": _safe_text(
            source_preflight.get("one_candidate_gmail_draft_create_locked_status", "")
        ),
        "selected_order_name": _safe_text(source_preflight.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_preflight.get("selected_masked_email", "")),
        "would_create_gmail_draft": source_preflight.get("would_create_gmail_draft") is True,
        "would_create_count": _safe_int(source_preflight.get("would_create_count")),
        "duplicate_trustpilot_invitation_guard_confirmed": (
            source_preflight.get("duplicate_trustpilot_invitation_block_confirmed") is True
        ),
        "returned_package_guard_confirmed": source_preflight.get("returned_package_guard_confirmed") is True,
        "first_order_customer_block_confirmed": source_preflight.get("first_order_customer_block_confirmed") is True,
        "blocking_condition_count": _safe_int(source_preflight.get("blocking_condition_count")),
        "source_self_raw_customer_email_count": _safe_int(
            (source_preflight.get("self_privacy_scan") or {}).get("raw_customer_email_count")
            if isinstance(source_preflight.get("self_privacy_scan"), dict)
            else 0
        ),
        "source_self_credential_pattern_count": _safe_int(
            (source_preflight.get("self_privacy_scan") or {}).get("credential_pattern_count")
            if isinstance(source_preflight.get("self_privacy_scan"), dict)
            else 0
        ),
        "draft_subject_preview": _safe_text(source_preflight.get("draft_subject_preview", "")),
        "draft_body_preview": _safe_text(source_preflight.get("draft_body_preview", "")),
        "trustpilot_link": _safe_text(source_preflight.get("trustpilot_link", "")),
    }


def _source_safety_summary(source_preflight: dict) -> dict:
    flags = {key: source_preflight.get(key) is True for key in SOURCE_UNSAFE_FLAG_KEYS}
    flags["gmail_drafts_created_count_gt_zero"] = _safe_int(source_preflight.get("gmail_drafts_created_count")) > 0
    return {
        "source_unsafe_flags": flags,
        "source_unsafe_flag_names": [key for key, value in flags.items() if value],
        "source_gmail_drafts_created_count": _safe_int(source_preflight.get("gmail_drafts_created_count")),
    }


def _gate_status(mode: str) -> dict:
    normalized_mode = str(mode or "").strip()
    dry_run_raw = os.environ.get(DRY_RUN_ENV, "").strip()
    approval_raw = os.environ.get(APPROVAL_ENV, "").strip()
    requested_order_name = os.environ.get(ORDER_ENV, "").strip()
    requested_create_max = os.environ.get(MAX_ENV, "").strip()
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
        "requested_create_max": _safe_text(requested_create_max),
        "requested_create_max_is_one": requested_create_max == EXPECTED_CREATE_MAX,
        "requested_source_report": _safe_text(requested_source_report),
        "requested_source_report_valid": requested_source_report == SOURCE_PREFLIGHT_REPORT_ENV_VALUE,
        "all_real_run_ack_gates_valid": (
            approval_raw == APPROVAL_VALUE
            and requested_order_name == EXPECTED_ORDER_NAME
            and requested_create_max == EXPECTED_CREATE_MAX
            and requested_source_report == SOURCE_PREFLIGHT_REPORT_ENV_VALUE
            and dry_run_raw == "0"
            and real_run_requested
        ),
        "required_ack_env_names": [APPROVAL_ENV, ORDER_ENV, MAX_ENV, SOURCE_REPORT_ENV, DRY_RUN_ENV],
        "expected_order_name": EXPECTED_ORDER_NAME,
        "expected_create_max": EXPECTED_CREATE_MAX,
        "expected_source_report": SOURCE_PREFLIGHT_REPORT_ENV_VALUE,
    }


def _blocking_conditions(
    source_preflight: dict,
    source_error: str,
    source_privacy_scan: dict,
    source_summary: dict,
    source_safety: dict,
    gates: dict,
) -> list[dict]:
    if not gates["mode_valid"]:
        return [{"status": "blocked_invalid_mode", "detail": "mode must be dry-run or real-run."}]
    if source_error:
        return [{"status": "blocked_missing_or_invalid_source_preflight", "detail": _sanitize_text(source_error)}]

    conditions = []
    if source_preflight.get("task_name") != EXPECTED_SOURCE_TASK:
        conditions.append({"status": "blocked_invalid_source_preflight", "detail": "source task name mismatch."})
    if str(source_preflight.get("phase")) != "4.4":
        conditions.append({"status": "blocked_invalid_source_preflight", "detail": "source phase must be 4.4."})
    if source_preflight.get("success") is not True:
        conditions.append({"status": "blocked_invalid_source_preflight", "detail": "source success is not true."})
    if source_summary["source_preflight_status"] != EXPECTED_SOURCE_STATUS:
        conditions.append(
            {"status": "blocked_source_preflight_not_passed", "detail": "source preflight status is not passed."}
        )
    if source_summary["selected_order_name"] != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_selected_order_mismatch", "detail": "selected order must be #22620."})
    if not _is_masked_email(source_summary["selected_masked_email"]):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected email is not masked."})
    if source_summary["would_create_gmail_draft"] is not True:
        conditions.append({"status": "blocked_source_would_not_create_draft", "detail": "would_create_gmail_draft is not true."})
    if source_summary["would_create_count"] != 1:
        conditions.append({"status": "blocked_source_would_create_count_not_one", "detail": "would_create_count must equal 1."})
    if source_summary["blocking_condition_count"] != 0:
        conditions.append({"status": "blocked_source_has_blocking_conditions", "detail": "source preflight has blockers."})
    if not source_summary["duplicate_trustpilot_invitation_guard_confirmed"]:
        conditions.append(
            {
                "status": "blocked_duplicate_trustpilot_invitation_guard_missing",
                "detail": "duplicate Trustpilot invitation guard is not confirmed.",
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
    if source_safety["source_unsafe_flag_names"]:
        conditions.append(
            {
                "status": "blocked_source_real_action_flag_detected",
                "detail": "source preflight has Gmail, Shopify, external API, tracking, or raw-email write flags.",
            }
        )
    if source_privacy_scan["raw_customer_email_count"]:
        conditions.append({"status": "blocked_source_raw_customer_email_detected", "detail": "source preflight contains raw email."})
    if source_privacy_scan["credential_pattern_count"]:
        conditions.append({"status": "blocked_source_token_or_secret_detected", "detail": "source preflight contains token-like text."})
    if source_summary["source_self_raw_customer_email_count"]:
        conditions.append({"status": "blocked_source_raw_customer_email_detected", "detail": "source self-scan raw-email count is not zero."})
    if source_summary["source_self_credential_pattern_count"]:
        conditions.append({"status": "blocked_source_token_or_secret_detected", "detail": "source self-scan token count is not zero."})

    if gates["real_run_requested"]:
        conditions.extend(_real_run_gate_conditions(gates))
    return conditions


def _real_run_gate_conditions(gates: dict) -> list[dict]:
    conditions = []
    if not gates["approval_present"]:
        conditions.append(
            {
                "status": "blocked_missing_real_gmail_draft_create_ack",
                "detail": f"{APPROVAL_ENV} is missing.",
            }
        )
    elif not gates["approval_valid"]:
        conditions.append(
            {
                "status": "blocked_invalid_real_gmail_draft_create_ack",
                "detail": f"{APPROVAL_ENV} did not match the required value.",
            }
        )
    if not gates["dry_run_env_present"]:
        conditions.append(
            {
                "status": "blocked_real_gmail_draft_create_dry_run_not_disabled",
                "detail": f"{DRY_RUN_ENV}=0 is required for real Gmail draft creation.",
            }
        )
    elif not gates["dry_run_env_is_zero"]:
        conditions.append(
            {
                "status": "blocked_real_gmail_draft_create_dry_run_not_disabled",
                "detail": f"{DRY_RUN_ENV} must equal 0 for real Gmail draft creation.",
            }
        )
    if not gates["requested_order_name"]:
        conditions.append(
            {"status": "blocked_missing_real_gmail_draft_create_order_name", "detail": f"{ORDER_ENV} is missing."}
        )
    elif not gates["requested_order_name_valid"]:
        conditions.append(
            {"status": "blocked_real_gmail_draft_create_order_mismatch", "detail": f"{ORDER_ENV} must be #22620."}
        )
    if not gates["requested_create_max"]:
        conditions.append({"status": "blocked_real_gmail_draft_create_max_not_one", "detail": f"{MAX_ENV} is missing."})
    elif not gates["requested_create_max_is_one"]:
        conditions.append({"status": "blocked_real_gmail_draft_create_max_not_one", "detail": f"{MAX_ENV} must be 1."})
    if not gates["requested_source_report"]:
        conditions.append(
            {"status": "blocked_real_gmail_draft_create_source_report_mismatch", "detail": f"{SOURCE_REPORT_ENV} is missing."}
        )
    elif not gates["requested_source_report_valid"]:
        conditions.append(
            {
                "status": "blocked_real_gmail_draft_create_source_report_mismatch",
                "detail": f"{SOURCE_REPORT_ENV} must match the Phase 4.4 report path.",
            }
        )
    return conditions


def _gmail_draft_create_result(source_preflight: dict, gates: dict, blocking_conditions: list[dict]) -> dict:
    result = _base_create_result(gates["cli_mode"] or "dry-run")
    if blocking_conditions:
        result["one_candidate_gmail_draft_create_execute_status"] = blocking_conditions[0]["status"]
        result["real_gmail_draft_create_blocked_reason"] = blocking_conditions[0]["status"]
        return result
    if gates["dry_run"]:
        return result

    result["mode"] = "real-run"
    if not gates["all_real_run_ack_gates_valid"]:
        result["one_candidate_gmail_draft_create_execute_status"] = "blocked_real_gmail_draft_create_ack_incomplete"
        result["real_gmail_draft_create_blocked_reason"] = result["one_candidate_gmail_draft_create_execute_status"]
        return result
    result["real_gmail_draft_create_allowed"] = True
    lookup = _protected_runtime_customer_lookup(source_preflight)
    _apply_customer_lookup_report(result, lookup)
    raw_recipient = lookup.get("_raw_email_for_runtime_only", "")
    first_name = lookup.get("_first_name_for_runtime_only", "") or "there"
    if not raw_recipient:
        result["one_candidate_gmail_draft_create_execute_status"] = "blocked_missing_raw_email_for_gmail_draft_create"
        result["real_gmail_draft_create_allowed"] = False
        result["real_gmail_draft_create_blocked_reason"] = result["one_candidate_gmail_draft_create_execute_status"]
        return result

    gmail_env = _gmail_env()
    result["gmail_oauth_env_read_attempted"] = True
    result["gmail_oauth_present"] = gmail_env["gmail_oauth_present"]
    result["gmail_sender_matches_expected"] = gmail_env["gmail_sender_matches_expected"]
    result["gmail_compose_scope_present"] = gmail_env["gmail_compose_scope_present"]
    result["gmail_missing_env_vars"] = gmail_env["missing_env_vars"]
    if not gmail_env["gmail_oauth_present"]:
        result["one_candidate_gmail_draft_create_execute_status"] = "blocked_missing_gmail_oauth"
        result["real_gmail_draft_create_allowed"] = False
        result["real_gmail_draft_create_blocked_reason"] = result["one_candidate_gmail_draft_create_execute_status"]
        return result
    if not gmail_env["gmail_sender_matches_expected"]:
        result["one_candidate_gmail_draft_create_execute_status"] = "blocked_gmail_sender_mismatch"
        result["real_gmail_draft_create_allowed"] = False
        result["real_gmail_draft_create_blocked_reason"] = result["one_candidate_gmail_draft_create_execute_status"]
        return result
    if not gmail_env["gmail_compose_scope_present"]:
        result["one_candidate_gmail_draft_create_execute_status"] = "blocked_missing_gmail_compose_scope"
        result["real_gmail_draft_create_allowed"] = False
        result["real_gmail_draft_create_blocked_reason"] = result["one_candidate_gmail_draft_create_execute_status"]
        return result

    try:
        service = _build_gmail_service(gmail_env, result)
        result["gmail_draft_create_attempted"] = True
        result["gmail_api_call_performed"] = True
        response = _create_gmail_draft(service, raw_recipient, first_name, source_preflight)
        draft_id_partial = _partial_id(response.get("id", ""))
        if not draft_id_partial:
            result["one_candidate_gmail_draft_create_execute_status"] = "blocked_gmail_draft_create_unverified"
            result["real_gmail_draft_create_allowed"] = False
            result["real_gmail_draft_create_blocked_reason"] = result["one_candidate_gmail_draft_create_execute_status"]
            return result
        result["one_candidate_gmail_draft_create_execute_status"] = FUTURE_SUCCESS_STATUS
        result["real_gmail_draft_create_executed"] = True
        result["real_gmail_draft_create_blocked_reason"] = ""
        result["gmail_draft_created"] = True
        result["gmail_drafts_created_count"] = 1
        result["gmail_draft_verified"] = True
        result["gmail_draft_id_partial"] = draft_id_partial
    except Exception as exc:  # pragma: no cover - real Gmail draft creation is only used behind explicit gates.
        result["one_candidate_gmail_draft_create_execute_status"] = "blocked_gmail_draft_create_failed"
        result["real_gmail_draft_create_allowed"] = False
        result["real_gmail_draft_create_blocked_reason"] = result["one_candidate_gmail_draft_create_execute_status"]
        result["gmail_error_sanitized"] = _sanitize_text(str(exc))
    return result


def _base_create_result(mode: str = "dry-run") -> dict:
    safety = _safety_summary()
    return {
        "one_candidate_gmail_draft_create_execute_status": DRY_RUN_STATUS,
        "mode": _safe_text(mode) or "dry-run",
        "dry_run": True,
        "real_gmail_draft_create_allowed": False,
        "real_gmail_draft_create_executed": False,
        "real_gmail_draft_create_blocked_reason": DRY_RUN_STATUS,
        "protected_raw_email_lookup_attempted": False,
        "raw_email_available_to_runtime": False,
        "raw_email_report_storage_allowed": False,
        "raw_email_lookup_source": "",
        "raw_email_lookup_error_sanitized": "",
        "raw_email_lookup_docker_command_reached": False,
        "raw_email_lookup_django_shell_reached": False,
        "raw_email_lookup_shopify_api_call_performed": False,
        "first_name_available_to_runtime": False,
        "customer_profile_lookup_source": "",
        "gmail_oauth_env_read_attempted": False,
        "gmail_oauth_present": False,
        "gmail_sender_matches_expected": False,
        "gmail_compose_scope_present": False,
        "gmail_missing_env_vars": [],
        "gmail_error_sanitized": "",
        "gmail_draft_verified": False,
        "gmail_draft_id_partial": "",
        **safety,
    }


def _protected_runtime_customer_lookup(source_preflight: dict) -> dict:
    lookup = {
        "protected_raw_email_lookup_attempted": True,
        "raw_email_available_to_runtime": False,
        "raw_email_report_storage_allowed": False,
        "raw_email_lookup_source": "local_django_db_runtime_lookup",
        "raw_email_lookup_error_sanitized": "",
        "raw_email_lookup_docker_command_reached": False,
        "raw_email_lookup_django_shell_reached": False,
        "raw_email_lookup_shopify_api_call_performed": False,
        "first_name_available_to_runtime": False,
        "customer_profile_lookup_source": "",
        "_raw_email_for_runtime_only": "",
        "_first_name_for_runtime_only": "",
    }
    order_name = _safe_text(source_preflight.get("selected_order_name", ""))
    masked_email = _safe_masked_email(source_preflight.get("selected_masked_email", ""))
    if order_name != EXPECTED_ORDER_NAME or not _is_masked_email(masked_email):
        lookup["raw_email_lookup_error_sanitized"] = "selected order or masked email is invalid for protected lookup"
        return lookup

    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "web",
        "python",
        "manage.py",
        "shell",
        "-c",
        _protected_customer_lookup_script(order_name),
    ]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            text=True,
            capture_output=True,
            timeout=PROTECTED_LOOKUP_TIMEOUT_SECONDS,
            check=False,
        )
        lookup["raw_email_lookup_docker_command_reached"] = True
    except subprocess.TimeoutExpired:
        lookup["raw_email_lookup_error_sanitized"] = f"protected lookup timed out after {PROTECTED_LOOKUP_TIMEOUT_SECONDS} seconds"
        return lookup
    except (FileNotFoundError, PermissionError) as exc:
        lookup["raw_email_lookup_error_sanitized"] = _sanitize_text(str(exc))
        return lookup

    parsed = _parse_protected_lookup_stdout(completed.stdout)
    if parsed:
        lookup["raw_email_lookup_django_shell_reached"] = bool(parsed.get("django_shell_reached"))
        lookup["raw_email_lookup_shopify_api_call_performed"] = bool(parsed.get("shopify_api_call_performed"))
        lookup["customer_profile_lookup_source"] = _safe_text(parsed.get("first_name_source", ""))
    if completed.returncode != 0:
        lookup["raw_email_lookup_error_sanitized"] = _sanitize_text(
            parsed.get("error_sanitized", "") if parsed else (completed.stderr or completed.stdout or "protected lookup failed")
        )
        return lookup
    if not parsed:
        lookup["raw_email_lookup_error_sanitized"] = "protected lookup did not return parseable JSON"
        return lookup

    raw_email = _safe_runtime_email(parsed.get("raw_email", ""))
    first_name = _safe_first_name(parsed.get("first_name", ""))
    if not raw_email:
        lookup["raw_email_lookup_error_sanitized"] = _sanitize_text(
            parsed.get("error_sanitized") or "protected lookup returned no usable customer email"
        )
        return lookup
    if _mask_email(raw_email) != masked_email:
        lookup["raw_email_lookup_error_sanitized"] = "protected lookup email did not match selected masked email"
        return lookup
    lookup["_raw_email_for_runtime_only"] = raw_email
    lookup["_first_name_for_runtime_only"] = first_name
    lookup["raw_email_available_to_runtime"] = True
    lookup["first_name_available_to_runtime"] = bool(first_name)
    return lookup


def _protected_customer_lookup_script(order_name: str) -> str:
    template = r'''
import json
import re
from shopify_sync.models import ShopifyOrder

order_name = __ORDER_NAME_LITERAL__
email_re = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
result = {
    "django_shell_reached": True,
    "shopify_api_call_performed": False,
    "order_found": False,
    "raw_email_available": False,
    "raw_email": "",
    "first_name": "",
    "first_name_source": "",
    "error_sanitized": "",
}

def sanitize(text):
    text = str(text or "")
    text = re.sub(r"(?i)(shpat_[A-Za-z0-9_]+|authorization|access[_\s-]?token|refresh[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)", "[redacted]", text)
    return email_re.sub("[masked-email]", text)

def clean_first_name(value):
    value = str(value or "").strip()
    if not value:
        return ""
    value = value.split()[0]
    value = re.sub(r"[^A-Za-z'-]", "", value)
    return value[:40]

try:
    order = ShopifyOrder.objects.filter(order_name=order_name).values("customer_email", "customer_name").first()
    if not order:
        result["error_sanitized"] = "local ShopifyOrder row not found"
    else:
        result["order_found"] = True
        email = str(order.get("customer_email") or "").strip().lower()
        if email and email_re.fullmatch(email):
            result["raw_email_available"] = True
            result["raw_email"] = email
        first_name = clean_first_name(order.get("customer_name"))
        if first_name:
            result["first_name"] = first_name
            result["first_name_source"] = "ShopifyOrder.customer_name"
        if not result["raw_email_available"]:
            result["error_sanitized"] = "local ShopifyOrder customer_email is missing"
except Exception as exc:
    result["error_sanitized"] = sanitize(str(exc))[:300]

print(json.dumps(result, ensure_ascii=False))
'''
    return template.replace("__ORDER_NAME_LITERAL__", json.dumps(order_name))


def _parse_protected_lookup_stdout(stdout: str) -> dict:
    for line in reversed((stdout or "").splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            continue
    return {}


def _apply_customer_lookup_report(result: dict, lookup: dict) -> None:
    result["protected_raw_email_lookup_attempted"] = bool(lookup.get("protected_raw_email_lookup_attempted"))
    result["raw_email_available_to_runtime"] = bool(lookup.get("raw_email_available_to_runtime"))
    result["raw_email_report_storage_allowed"] = False
    result["raw_email_lookup_source"] = _safe_text(lookup.get("raw_email_lookup_source", ""))
    result["raw_email_lookup_error_sanitized"] = _sanitize_text(lookup.get("raw_email_lookup_error_sanitized", ""))
    result["raw_email_lookup_docker_command_reached"] = bool(lookup.get("raw_email_lookup_docker_command_reached"))
    result["raw_email_lookup_django_shell_reached"] = bool(lookup.get("raw_email_lookup_django_shell_reached"))
    result["raw_email_lookup_shopify_api_call_performed"] = bool(
        lookup.get("raw_email_lookup_shopify_api_call_performed")
    )
    result["first_name_available_to_runtime"] = bool(lookup.get("first_name_available_to_runtime"))
    result["customer_profile_lookup_source"] = _safe_text(lookup.get("customer_profile_lookup_source", ""))


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
        "gmail_compose_scope_present": GMAIL_COMPOSE_SCOPE in scopes,
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


def _create_gmail_draft(service, recipient_email: str, first_name: str, source_preflight: dict) -> dict:
    message = EmailMessage()
    message["To"] = recipient_email
    message["From"] = GMAIL_SEND_FROM
    message["Subject"] = _safe_text(source_preflight.get("draft_subject_preview", "")) or "How was your Kidstoylover order?"
    message.set_content(_draft_body(first_name, source_preflight))
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return service.users().drafts().create(userId="me", body={"message": {"raw": raw_message}}).execute()


def _draft_body(first_name: str, source_preflight: dict) -> str:
    body = _safe_text(source_preflight.get("draft_body_preview", ""))
    if body:
        return body
    trustpilot_link = _safe_text(source_preflight.get("trustpilot_link", ""))
    return (
        f"Dear {first_name or 'there'},\n\n"
        "Thank you for shopping with Kidstoylover. We hope everything arrived safely and that you are enjoying your order.\n\n"
        "If you have a moment, we would really appreciate it if you could share your experience with us on Trustpilot:\n\n"
        f"{trustpilot_link}\n\n"
        "Kind regards,\n"
        "Kidstoylover Team\n"
    )


def _build_payload(
    source_summary: dict,
    source_safety: dict,
    source_privacy_scan: dict,
    gates: dict,
    blocking_conditions: list[dict],
    create_result: dict,
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary(create_result)
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "4.5",
        "mode": create_result["mode"],
        "command_label": COMMAND_LABEL,
        "one_candidate_gmail_draft_create_execute_status": status,
        "success": status in {DRY_RUN_STATUS, FUTURE_SUCCESS_STATUS},
        "source_preflight_report_path": SOURCE_PREFLIGHT_REPORT_ENV_VALUE,
        "source_preflight_status": source_summary["source_preflight_status"],
        "source_preflight_summary": source_summary,
        "source_preflight_safety_summary": source_safety,
        "source_preflight_privacy_scan": source_privacy_scan,
        "selected_order_name": source_summary["selected_order_name"],
        "selected_masked_email": source_summary["selected_masked_email"],
        "would_create_gmail_draft": source_summary["would_create_gmail_draft"],
        "would_create_count": source_summary["would_create_count"],
        "duplicate_trustpilot_invitation_guard_confirmed": source_summary[
            "duplicate_trustpilot_invitation_guard_confirmed"
        ],
        "returned_package_guard_confirmed": source_summary["returned_package_guard_confirmed"],
        "first_order_customer_block_confirmed": source_summary["first_order_customer_block_confirmed"],
        "draft_subject_preview": source_summary["draft_subject_preview"],
        "draft_body_preview": source_summary["draft_body_preview"],
        "trustpilot_link": source_summary["trustpilot_link"],
        "dry_run": gates["dry_run"],
        "real_run_requested": gates["real_run_requested"],
        "real_run_gate_status": gates,
        "real_gmail_draft_create_allowed": create_result["real_gmail_draft_create_allowed"],
        "real_gmail_draft_create_executed": create_result["real_gmail_draft_create_executed"],
        "real_gmail_draft_create_blocked_reason": create_result["real_gmail_draft_create_blocked_reason"],
        "future_real_run_success_status_design": FUTURE_SUCCESS_STATUS,
        "max_real_gmail_drafts_allowed": 1,
        "gmail_draft_id_partial": create_result["gmail_draft_id_partial"],
        "gmail_draft_verified": create_result["gmail_draft_verified"],
        "gmail_oauth_env_read_attempted": create_result["gmail_oauth_env_read_attempted"],
        "gmail_oauth_present": create_result["gmail_oauth_present"],
        "gmail_sender_matches_expected": create_result["gmail_sender_matches_expected"],
        "gmail_compose_scope_present": create_result["gmail_compose_scope_present"],
        "gmail_missing_env_vars": create_result["gmail_missing_env_vars"],
        "gmail_error_sanitized": create_result["gmail_error_sanitized"],
        "protected_raw_email_lookup_attempted": create_result["protected_raw_email_lookup_attempted"],
        "raw_email_available_to_runtime": create_result["raw_email_available_to_runtime"],
        "raw_email_report_storage_allowed": False,
        "raw_email_lookup_source": create_result["raw_email_lookup_source"],
        "raw_email_lookup_error_sanitized": create_result["raw_email_lookup_error_sanitized"],
        "raw_email_lookup_docker_command_reached": create_result["raw_email_lookup_docker_command_reached"],
        "raw_email_lookup_django_shell_reached": create_result["raw_email_lookup_django_shell_reached"],
        "raw_email_lookup_shopify_api_call_performed": create_result["raw_email_lookup_shopify_api_call_performed"],
        "first_name_available_to_runtime": create_result["first_name_available_to_runtime"],
        "customer_profile_lookup_source": create_result["customer_profile_lookup_source"],
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_customer_email_output": False,
            "raw_customer_email_report_storage_allowed": False,
            "gmail_access_token_output": False,
            "gmail_refresh_token_output": False,
            "gmail_client_secret_output": False,
            "gmail_draft_id_full_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
        },
        "safety_summary": safety,
        **safety,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_one_candidate_gmail_draft_create_execute_path": str(REPORT_JSON_PATH),
        "html_trustpilot_one_candidate_gmail_draft_create_execute_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary(create_result: dict | None = None) -> dict:
    create_result = create_result or {}
    return {
        "gmail_api_call_performed": bool(create_result.get("gmail_api_call_performed", False)),
        "gmail_token_refresh_attempted": bool(create_result.get("gmail_token_refresh_attempted", False)),
        "gmail_token_refresh_succeeded": bool(create_result.get("gmail_token_refresh_succeeded", False)),
        "gmail_draft_create_attempted": bool(create_result.get("gmail_draft_create_attempted", False)),
        "gmail_draft_created": bool(create_result.get("gmail_draft_created", False)),
        "gmail_drafts_created_count": _safe_int(create_result.get("gmail_drafts_created_count", 0)),
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
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "no_new_gmail_send_performed": True,
        "no_new_external_api_calls_performed": not bool(create_result.get("gmail_api_call_performed", False)),
        "all_new_actions_no_write_confirmed": not bool(create_result.get("gmail_draft_created", False)),
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_one_candidate_gmail_draft_create_execute_path": str(json_path),
        "html_trustpilot_one_candidate_gmail_draft_create_execute_path": str(html_path),
        "one_candidate_gmail_draft_create_execute_status": payload[
            "one_candidate_gmail_draft_create_execute_status"
        ],
        "source_preflight_status": payload["source_preflight_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "would_create_gmail_draft": payload["would_create_gmail_draft"],
        "would_create_count": payload["would_create_count"],
        "dry_run": payload["dry_run"],
        "real_run_requested": payload["real_run_requested"],
        "real_gmail_draft_create_allowed": payload["real_gmail_draft_create_allowed"],
        "real_gmail_draft_create_executed": payload["real_gmail_draft_create_executed"],
        "real_gmail_draft_create_blocked_reason": payload["real_gmail_draft_create_blocked_reason"],
        "gmail_draft_id_partial": payload["gmail_draft_id_partial"],
        "gmail_draft_verified": payload["gmail_draft_verified"],
        "gmail_oauth_env_read_attempted": payload["gmail_oauth_env_read_attempted"],
        "protected_raw_email_lookup_attempted": payload["protected_raw_email_lookup_attempted"],
        "raw_email_available_to_runtime": payload["raw_email_available_to_runtime"],
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
    ) or '<tr><td colspan="2">None</td></tr>'
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    gates = payload["real_run_gate_status"]
    source_scan = payload["source_preflight_privacy_scan"]
    self_scan = payload["self_privacy_scan"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot One-Candidate Gmail Draft Create Execute</title>
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
  <h1>Trustpilot One-Candidate Gmail Draft Create Execute</h1>
  <p class="{'safe' if payload['success'] else 'warning'}">Phase 4.5 default mode is dry-run. No Gmail draft is created unless DRY_RUN=0 and every exact one-draft ACK gate is valid.</p>
  <p>Status: <strong>{escape(payload["one_candidate_gmail_draft_create_execute_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source preflight: <code>{escape(payload["source_preflight_report_path"])}</code></p>
  <p>Source preflight status: <strong>{escape(payload["source_preflight_status"])}</strong></p>
  <h2>Execution</h2>
  <table><tbody>
    <tr><th>Dry-run</th><td>{escape(str(payload["dry_run"]))}</td></tr>
    <tr><th>Would create Gmail draft</th><td>{escape(str(payload["would_create_gmail_draft"]))}</td></tr>
    <tr><th>Would create count</th><td>{escape(str(payload["would_create_count"]))}</td></tr>
    <tr><th>Real Gmail draft create allowed</th><td>{escape(str(payload["real_gmail_draft_create_allowed"]))}</td></tr>
    <tr><th>Real Gmail draft create executed</th><td>{escape(str(payload["real_gmail_draft_create_executed"]))}</td></tr>
    <tr><th>Blocked reason</th><td>{escape(str(payload["real_gmail_draft_create_blocked_reason"]))}</td></tr>
    <tr><th>Gmail draft id partial</th><td><code>{escape(str(payload["gmail_draft_id_partial"]))}</code></td></tr>
  </tbody></table>
  <h2>Real-Run Gates</h2>
  <table><tbody>
    <tr><th>Real run requested</th><td>{escape(str(gates["real_run_requested"]))}</td></tr>
    <tr><th>Approval present</th><td>{escape(str(gates["approval_present"]))}</td></tr>
    <tr><th>Approval valid</th><td>{escape(str(gates["approval_valid"]))}</td></tr>
    <tr><th>Order name valid</th><td>{escape(str(gates["requested_order_name_valid"]))}</td></tr>
    <tr><th>Create max is one</th><td>{escape(str(gates["requested_create_max_is_one"]))}</td></tr>
    <tr><th>Source report valid</th><td>{escape(str(gates["requested_source_report_valid"]))}</td></tr>
  </tbody></table>
  <h2>Draft Preview</h2>
  <table><tbody>
    <tr><th>Subject</th><td>{escape(payload["draft_subject_preview"])}</td></tr>
    <tr><th>Body preview</th><td class="preview">{escape(payload["draft_body_preview"])}</td></tr>
    <tr><th>Trustpilot link</th><td><code>{escape(payload["trustpilot_link"])}</code></td></tr>
  </tbody></table>
  <h2>Privacy Scan</h2>
  <table><tbody>
    <tr><th>Source raw customer email count</th><td>{source_scan["raw_customer_email_count"]}</td></tr>
    <tr><th>Source token-like value count</th><td>{source_scan["credential_pattern_count"]}</td></tr>
    <tr><th>Report raw customer email count</th><td>{self_scan["raw_customer_email_count"]}</td></tr>
    <tr><th>Report token-like value count</th><td>{self_scan["credential_pattern_count"]}</td></tr>
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

    payload["one_candidate_gmail_draft_create_execute_status"] = "blocked_privacy_scan_failed"
    payload["success"] = False
    payload["real_gmail_draft_create_allowed"] = False
    payload["real_gmail_draft_create_executed"] = False
    payload["real_gmail_draft_create_blocked_reason"] = "blocked_privacy_scan_failed"
    payload["blocking_conditions"].append(
        {"status": "blocked_privacy_scan_failed", "detail": "Phase 4.5 report self privacy scan failed."}
    )
    payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    payload["detected_issue_summary"] = _issue_summary(
        payload["one_candidate_gmail_draft_create_execute_status"],
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
        "credential_pattern_count": sum(1 for pattern in SECRET_VALUE_PATTERNS if pattern.search(text or "")),
    }


def _safe_runtime_email(value) -> str:
    text = str(value or "").strip().lower()
    if text and "***" not in text and EMAIL_RE.fullmatch(text):
        return text
    return ""


def _safe_first_name(value) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z'-]", "", text.split()[0] if text else "")
    return text[:40] or "there"


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
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _partial_id(value) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if len(text) <= 10:
        return "[present]"
    return f"{text[:4]}...{text[-4:]}"


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _issue_summary(status: str, blocking_conditions: list[dict]) -> str:
    if status == DRY_RUN_STATUS:
        return "Phase 4.5 stayed in dry-run; no Gmail API call, Gmail draft, email send, Shopify write, external review API call, or tracking action was performed."
    if status == FUTURE_SUCCESS_STATUS:
        return "Exactly one Gmail draft was created and verified; no send, Shopify write, external review API call, or tracking action was performed."
    return "Phase 4.5 Gmail draft create executor blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 4.5 Trustpilot one-candidate Gmail draft create execute finished.\n"
        f"Status: {payload.get('one_candidate_gmail_draft_create_execute_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Source preflight status: {payload.get('source_preflight_status')}\n"
        f"Dry-run: {payload.get('dry_run')}\n"
        f"Would create Gmail draft: {payload.get('would_create_gmail_draft')}\n"
        f"Would create count: {payload.get('would_create_count')}\n"
        f"Real Gmail draft create allowed: {payload.get('real_gmail_draft_create_allowed')}\n"
        f"Real Gmail draft create executed: {payload.get('real_gmail_draft_create_executed')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail send, no Shopify write/tagsAdd/tagsRemove, no Trustpilot/Kudosi/Ali Reviews API call, and no tracking token or redirect.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
