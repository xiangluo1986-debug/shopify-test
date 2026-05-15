import json
import os
import time
from html import escape
from importlib.util import find_spec
from pathlib import Path

from remote_approval.tasks.shopify_review_request_trustpilot_automation_dry_run_task import (
    _safe_payload,
    _safe_text,
    _safety_summary,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_real_send_readiness_audit"
COMMAND_LABEL = TASK_NAME
PHASE = "5.15"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_real_send_readiness_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_real_send_readiness_audit.html"

SOURCE_REPORTS = {
    "auto_queue_refresh": LOG_DIR / "shopify_review_request_trustpilot_auto_queue_refresh.json",
    "locked_send_readiness_package": (
        LOG_DIR / "shopify_review_request_trustpilot_locked_send_readiness_package.json"
    ),
    "locked_gmail_send_gate": LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate.json",
    "gmail_send_executor_shell": LOG_DIR / "shopify_review_request_trustpilot_gmail_send_executor_shell.json",
    "real_send_final_preflight": LOG_DIR / "shopify_review_request_trustpilot_real_send_final_preflight.json",
    "real_send_execute": LOG_DIR / "shopify_review_request_trustpilot_real_send_execute.json",
}

GMAIL_DEPENDENCY_MODULES = (
    "google.oauth2.credentials",
    "googleapiclient.discovery",
    "google.auth.transport.requests",
)

GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
NEW_GMAIL_OAUTH_ENV_NAMES = (
    "GMAIL_SEND_FROM_EMAIL",
    "GMAIL_OAUTH_CLIENT_SECRET_FILE",
    "GMAIL_OAUTH_TOKEN_FILE",
    "GMAIL_REQUIRED_SCOPE",
)
GMAIL_OAUTH_ENV_NAMES = (
    "GMAIL_SEND_FROM",
    "GOOGLE_GMAIL_CLIENT_ID",
    "GOOGLE_GMAIL_CLIENT_SECRET",
    "GOOGLE_GMAIL_SCOPES",
)
GMAIL_TOKEN_ENV_NAMES = (
    "GOOGLE_GMAIL_REFRESH_TOKEN",
    "GOOGLE_GMAIL_TOKEN_PATH",
    "GMAIL_TOKEN_PATH",
)
GMAIL_CREDENTIAL_PATH_ENV_NAMES = (
    "GOOGLE_GMAIL_CREDENTIALS_PATH",
    "GMAIL_CREDENTIALS_PATH",
)

REQUIRED_ACK_NAME = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK"
REQUIRED_REAL_SEND_EXECUTE_FLAG_NAME = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE"

READY_PREFLIGHT_STATUS = "ready_for_real_send_execute_next_phase"
BLOCKED_NO_CANDIDATE_STATUS = "blocked_no_eligible_candidate"

NEXT_ADMIN_ACTION_NO_CANDIDATE = (
    "Wait for exactly one real eligible candidate, then rerun final preflight and readiness audit "
    "before enabling real send implementation."
)

FORBIDDEN_TRUE_FLAGS = {
    "send_allowed_now",
    "draft_create_allowed_now",
    "gmail_api_allowed_now",
    "gmail_send_allowed_now",
    "gmail_draft_create_allowed_now",
    "gmail_api_call_performed",
    "gmail_network_call_performed",
    "gmail_draft_create_attempted",
    "gmail_draft_create_performed",
    "gmail_draft_created",
    "gmail_draft_updated",
    "gmail_draft_deleted",
    "gmail_drafts_send_called",
    "gmail_messages_send_called",
    "gmail_send_performed",
    "email_sent",
    "shopify_api_call_performed",
    "shopify_write_performed",
    "shopify_tag_write_allowed_now",
    "shopify_tag_write_performed",
    "mutation_performed",
    "tags_add_performed",
    "tags_remove_performed",
    "tagsAdd_performed",
    "tagsRemove_performed",
    "external_review_api_call_allowed_now",
    "external_review_api_call_performed",
    "trustpilot_api_call_performed",
    "kudosi_api_call_performed",
    "kudosi_write_api_call_performed",
    "ali_reviews_api_call_performed",
    "ali_reviews_write_api_call_performed",
    "tracking_redirect_enabled",
    "tracking_token_generated",
    "raw_customer_email_output",
    "full_gmail_draft_or_message_id_output",
}


def run_shopify_review_request_trustpilot_gmail_real_send_readiness_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    sources = _load_source_reports()
    payload = _build_payload(
        sources=sources,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_source_reports() -> dict:
    return {key: _load_json_report(key, path) for key, path in SOURCE_REPORTS.items()}


def _load_json_report(key: str, path: Path) -> dict:
    report = {
        "key": key,
        "relative_path": f"logs/{path.name}",
        "present": path.exists(),
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "error_sanitized": "",
        "data": {},
    }
    if not path.exists():
        return report
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"), strict=False)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error_sanitized"] = _safe_text(str(exc), max_length=300)
        return report
    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error_sanitized"] = "top_level_json_is_not_object"
        return report
    report.update(
        {
            "loaded": True,
            "status": _report_status(data),
            "timestamp": _first_text(
                data,
                ("report_generated_at", "timestamp", "refreshed_at", "generated_at", "created_at", "finished_at"),
            ),
            "data": data,
        }
    )
    return report


def _build_payload(sources: dict, duration_seconds: float) -> dict:
    auto_data = _source_data(sources.get("auto_queue_refresh"))
    readiness_data = _source_data(sources.get("locked_send_readiness_package"))
    gate_data = _source_data(sources.get("locked_gmail_send_gate"))
    executor_data = _source_data(sources.get("gmail_send_executor_shell"))
    preflight_data = _source_data(sources.get("real_send_final_preflight"))
    execute_data = _source_data(sources.get("real_send_execute"))

    latest_auto_refresh_status = _source_status(
        sources.get("auto_queue_refresh"),
        auto_data,
        ("refresh_status", "report_status", "status"),
        "refreshed_no_eligible_candidate",
    )
    latest_preflight_status = _source_status(
        sources.get("real_send_final_preflight"),
        preflight_data,
        ("preflight_status", "report_status", "status"),
        BLOCKED_NO_CANDIDATE_STATUS,
    )
    latest_execute_status = _source_status(
        sources.get("real_send_execute"),
        execute_data,
        ("execution_status", "report_status", "status"),
        BLOCKED_NO_CANDIDATE_STATUS,
    )
    eligible_count = _candidate_count(execute_data, preflight_data, executor_data, gate_data, readiness_data, auto_data)
    selected_order = _selected_candidate_order_name(
        eligible_count,
        execute_data,
        preflight_data,
        executor_data,
        gate_data,
        readiness_data,
        auto_data,
    )
    dependency_status = _gmail_dependency_status()
    env_status = _gmail_env_status()
    source_safety_findings = _source_safety_findings(sources)
    known_blockers = _known_blockers_summary(readiness_data, gate_data, executor_data, preflight_data, auto_data)
    readiness_status = _readiness_status(
        eligible_count=eligible_count,
        selected_order=selected_order,
        latest_preflight_status=latest_preflight_status,
        latest_execute_status=latest_execute_status,
        source_safety_findings=source_safety_findings,
    )
    blocking_conditions = _blocking_conditions(
        readiness_status=readiness_status,
        eligible_count=eligible_count,
        selected_order=selected_order,
        latest_preflight_status=latest_preflight_status,
        latest_execute_status=latest_execute_status,
        source_safety_findings=source_safety_findings,
        known_blockers=known_blockers,
    )
    generated_at = utc_now_iso()
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "real-send-readiness-audit",
        "dry_run": True,
        "readiness_audit_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "readiness_audit_status": readiness_status,
        "gmail_dependencies_importable": dependency_status["all_importable"],
        "gmail_dependency_status": dependency_status,
        "gmail_oauth_config_present": env_status["oauth_config_present"],
        "gmail_oauth_config_status": env_status["oauth_config_status"],
        "gmail_token_config_present": env_status["token_config_present"],
        "gmail_token_config_status": env_status["token_config_status"],
        "legacy_gmail_oauth_config_present": env_status["legacy_oauth_config_present"],
        "new_gmail_file_path_config_present": env_status["new_file_path_config_present"],
        "gmail_scope_compatibility_result": env_status["scope_compatibility"],
        "gmail_send_scope_present": env_status["gmail_send_scope_present"],
        "gmail_compose_scope_present": env_status["gmail_compose_scope_present"],
        "gmail_local_config_name_audit": env_status,
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_update_performed": False,
        "gmail_draft_delete_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "latest_auto_refresh_status": latest_auto_refresh_status,
        "latest_preflight_status": latest_preflight_status,
        "latest_execute_status": latest_execute_status,
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order if selected_order else None,
        "required_ack_name": REQUIRED_ACK_NAME,
        "required_real_send_execute_flag_name": REQUIRED_REAL_SEND_EXECUTE_FLAG_NAME,
        "required_ack_name_documented": True,
        "required_real_send_execute_flag_name_documented": True,
        "single_send_limit_enforced": True,
        "single_send_limit_status": "required_exactly_one_candidate_for_future_implementation",
        "duplicate_suppression_required": True,
        "duplicate_suppression_status": "required_before_any_future_send",
        "raw_email_output_blocked": True,
        "full_gmail_id_output_blocked": True,
        "privacy_masking_status": "raw_email_and_full_gmail_id_output_blocked",
        "current_blocking_conditions": blocking_conditions,
        "known_blockers_summary": known_blockers,
        "next_admin_action": _next_admin_action(readiness_status),
        "readiness_checklist": _readiness_checklist(
            readiness_status=readiness_status,
            eligible_count=eligible_count,
            selected_order=selected_order,
            latest_preflight_status=latest_preflight_status,
            latest_execute_status=latest_execute_status,
            dependency_status=dependency_status,
            env_status=env_status,
            source_safety_findings=source_safety_findings,
        ),
        "dashboard_message": _dashboard_message(readiness_status),
        "safety_message": (
            "No Gmail network call was made. No email was sent. No Shopify tag was written."
        ),
        "source_report_status": _source_report_status(sources),
        "report_paths": {
            "json": f"logs/{REPORT_JSON_PATH.name}",
            "html": f"logs/{REPORT_HTML_PATH.name}",
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(readiness_status, known_blockers),
        **_safety_summary(),
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
    }
    return _safe_payload(payload)


def _gmail_dependency_status() -> dict:
    modules = []
    for module_name in GMAIL_DEPENDENCY_MODULES:
        try:
            importable = find_spec(module_name) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            importable = False
        modules.append(
            {
                "module": module_name,
                "importable": importable,
                "status": "ready" if importable else "missing",
            }
        )
    all_importable = all(item["importable"] for item in modules)
    return {
        "all_importable": all_importable,
        "status": "ready" if all_importable else "missing",
        "modules": modules,
        "network_call_performed": False,
    }


def _gmail_env_status() -> dict:
    legacy_oauth_present_by_role = {
        "sender_name": _any_env_present(("GMAIL_SEND_FROM",)),
        "client_id_name": _any_env_present(("GOOGLE_GMAIL_CLIENT_ID",)),
        "client_credential_name": _any_env_present(("GOOGLE_GMAIL_CLIENT_SECRET",)),
        "scope_name": _any_env_present(("GOOGLE_GMAIL_SCOPES",)),
    }
    legacy_token_present_by_role = {
        "refresh_credential_name": _any_env_present(("GOOGLE_GMAIL_REFRESH_TOKEN",)),
        "token_file_path_name": _any_env_present(("GOOGLE_GMAIL_TOKEN_PATH", "GMAIL_TOKEN_PATH")),
        "credential_file_path_name": _any_env_present(
            ("GOOGLE_GMAIL_CREDENTIALS_PATH", "GMAIL_CREDENTIALS_PATH")
        ),
    }
    new_name_presence = {name: _any_env_present((name,)) for name in NEW_GMAIL_OAUTH_ENV_NAMES}
    legacy_scope_status = _scope_status(os.environ.get("GOOGLE_GMAIL_SCOPES", ""))
    new_scope_status = _scope_status(os.environ.get("GMAIL_REQUIRED_SCOPE", ""))
    legacy_oauth_config_present = (
        legacy_oauth_present_by_role["client_credential_name"]
        and legacy_token_present_by_role["refresh_credential_name"]
    )
    new_file_path_config_present = all(new_name_presence.values()) and new_scope_status[
        "gmail_send_scope_present"
    ]
    oauth_present = legacy_oauth_config_present or new_file_path_config_present
    token_present = (
        legacy_token_present_by_role["refresh_credential_name"]
        or new_name_presence["GMAIL_OAUTH_TOKEN_FILE"]
        or legacy_token_present_by_role["token_file_path_name"]
    )
    configured_legacy_oauth_name_count = sum(1 for value in legacy_oauth_present_by_role.values() if value)
    configured_legacy_token_name_count = sum(1 for value in legacy_token_present_by_role.values() if value)
    configured_new_name_count = sum(1 for value in new_name_presence.values() if value)
    gmail_send_scope_present = legacy_scope_status["gmail_send_scope_present"] or new_scope_status[
        "gmail_send_scope_present"
    ]
    gmail_compose_scope_present = legacy_scope_status["gmail_compose_scope_present"] or new_scope_status[
        "gmail_compose_scope_present"
    ]
    scope_compatibility = _combined_scope_compatibility(gmail_send_scope_present, gmail_compose_scope_present)
    return {
        "presence_only": True,
        "process_environment_only": True,
        "dotenv_read": False,
        "values_reported": False,
        "oauth_config_present": oauth_present,
        "oauth_config_status": _oauth_config_status(new_file_path_config_present, legacy_oauth_config_present),
        "oauth_config_name_count": len(legacy_oauth_present_by_role) + len(new_name_presence),
        "configured_oauth_name_count": configured_legacy_oauth_name_count + configured_new_name_count,
        "token_config_present": token_present,
        "token_config_status": _token_config_status(
            new_name_presence["GMAIL_OAUTH_TOKEN_FILE"],
            legacy_token_present_by_role["refresh_credential_name"],
        ),
        "token_config_name_count": len(legacy_token_present_by_role) + 1,
        "configured_token_name_count": configured_legacy_token_name_count
        + (1 if new_name_presence["GMAIL_OAUTH_TOKEN_FILE"] else 0),
        "legacy_oauth_config_present": legacy_oauth_config_present,
        "new_file_path_config_present": new_file_path_config_present,
        "legacy_oauth_name_presence_by_role": legacy_oauth_present_by_role,
        "legacy_token_name_presence_by_role": legacy_token_present_by_role,
        "new_name_presence": {
            name: {
                "present": present,
                "status": "present" if present else "missing",
                "value_reported": False,
            }
            for name, present in new_name_presence.items()
        },
        "oauth_name_presence_by_role": legacy_oauth_present_by_role,
        "token_name_presence_by_role": legacy_token_present_by_role,
        "credential_path_name_config_present": any(
            legacy_token_present_by_role[key]
            for key in ("token_file_path_name", "credential_file_path_name")
        ),
        "gmail_send_scope_present": gmail_send_scope_present,
        "gmail_compose_scope_present": gmail_compose_scope_present,
        "legacy_scope_compatibility": legacy_scope_status["scope_compatibility"],
        "new_scope_compatibility": new_scope_status["scope_compatibility"],
        "scope_compatibility": scope_compatibility,
    }


def _any_env_present(names: tuple[str, ...]) -> bool:
    return any(bool((os.environ.get(name) or "").strip()) for name in names)


def _scope_status(raw_value: str) -> dict:
    scopes = {item.strip() for item in str(raw_value or "").replace(",", " ").split() if item.strip()}
    send_present = GMAIL_SEND_SCOPE in scopes
    compose_present = GMAIL_COMPOSE_SCOPE in scopes
    return {
        "scope_configured": bool(scopes),
        "gmail_send_scope_present": send_present,
        "gmail_compose_scope_present": compose_present,
        "scope_compatibility": _combined_scope_compatibility(send_present, compose_present),
        "scope_values_reported": False,
    }


def _combined_scope_compatibility(send_present: bool, compose_present: bool) -> str:
    if send_present:
        return "send_scope_present"
    if compose_present:
        return "compose_only_not_send_scope"
    return "scope_missing"


def _oauth_config_status(new_file_path_config_present: bool, legacy_oauth_config_present: bool) -> str:
    if new_file_path_config_present:
        return "new_file_path_config_present"
    if legacy_oauth_config_present:
        return "legacy_config_present"
    return "missing"


def _token_config_status(new_token_file_present: bool, legacy_refresh_token_present: bool) -> str:
    if new_token_file_present:
        return "new_token_file_present"
    if legacy_refresh_token_present:
        return "legacy_refresh_token_present"
    return "missing"


def _source_data(report: dict | None) -> dict:
    if not isinstance(report, dict) or not report.get("loaded"):
        return {}
    data = report.get("data")
    return data if isinstance(data, dict) else {}


def _source_status(report: dict | None, data: dict, keys: tuple[str, ...], fallback: str) -> str:
    if isinstance(report, dict) and report.get("loaded"):
        return _first_text(data, keys) or _safe_text(report.get("status"), max_length=120) or fallback
    return fallback


def _candidate_count(*data_sources: dict) -> int:
    for data in data_sources:
        if not isinstance(data, dict):
            continue
        if "eligible_candidate_count" in data:
            return _int_or_zero(data.get("eligible_candidate_count"))
    return 0


def _selected_candidate_order_name(eligible_count: int, *data_sources: dict) -> str:
    if eligible_count != 1:
        return ""
    for data in data_sources:
        if not isinstance(data, dict):
            continue
        selected = _safe_text(data.get("selected_candidate_order_name"), max_length=80)
        if selected:
            return selected
        eligible_candidates = data.get("eligible_candidates_summary")
        if isinstance(eligible_candidates, list) and eligible_candidates:
            first = eligible_candidates[0] if isinstance(eligible_candidates[0], dict) else {}
            selected = _safe_text(first.get("order_name"), max_length=80)
            if selected:
                return selected
    return ""


def _readiness_status(
    eligible_count: int,
    selected_order: str,
    latest_preflight_status: str,
    latest_execute_status: str,
    source_safety_findings: list[str],
) -> str:
    if source_safety_findings:
        return "blocked_source_safety_flags_detected"
    if eligible_count == 0 or latest_preflight_status == BLOCKED_NO_CANDIDATE_STATUS:
        return BLOCKED_NO_CANDIDATE_STATUS
    if eligible_count != 1:
        return "blocked_candidate_count_not_exactly_one"
    if not selected_order:
        return "blocked_missing_selected_candidate"
    if latest_preflight_status != READY_PREFLIGHT_STATUS:
        return latest_preflight_status or "blocked_final_preflight_not_ready"
    if latest_execute_status not in {
        "blocked_missing_real_send_execute_flag",
        "ready_but_real_send_implementation_not_enabled_in_this_phase",
    }:
        return latest_execute_status or "blocked_real_send_execute_not_ready"
    return "ready_for_future_real_send_implementation_audit_only"


def _blocking_conditions(
    readiness_status: str,
    eligible_count: int,
    selected_order: str,
    latest_preflight_status: str,
    latest_execute_status: str,
    source_safety_findings: list[str],
    known_blockers: list[dict],
) -> list[dict]:
    conditions = []
    if readiness_status == BLOCKED_NO_CANDIDATE_STATUS:
        conditions.append(
            {
                "status": BLOCKED_NO_CANDIDATE_STATUS,
                "detail": "No eligible real Trustpilot candidate is available for future Gmail real send.",
            }
        )
    elif readiness_status == "ready_for_future_real_send_implementation_audit_only":
        return []
    else:
        conditions.append(
            {
                "status": readiness_status,
                "detail": (
                    f"Readiness audit is blocked with eligible_candidate_count={eligible_count}, "
                    f"selected_candidate={selected_order or 'None'}, "
                    f"latest_preflight_status={latest_preflight_status}, "
                    f"latest_execute_status={latest_execute_status}."
                ),
            }
        )
    for blocker in known_blockers:
        conditions.append(
            {
                "status": _safe_text(blocker.get("status"), max_length=120),
                "order_name": _safe_text(blocker.get("order_name"), max_length=80),
                "detail": _safe_text(blocker.get("summary") or blocker.get("message"), max_length=300),
            }
        )
    for finding in source_safety_findings:
        conditions.append(
            {
                "status": "blocked_source_safety_flag",
                "detail": _safe_text(finding, max_length=300),
            }
        )
    return conditions


def _known_blockers_summary(*data_sources: dict) -> list[dict]:
    return [
        _known_blocker(
            data_sources=data_sources,
            order_name="#22620",
            fallback_status="blocked_existing_trustpilot_invitation_customer_level",
            fallback_summary="Already sent to this customer via #22621",
            fallback_message="Do not send. Already sent to this customer via #22621.",
            fallback_reasons=["blocked_existing_trustpilot_invitation_customer_level"],
        ),
        _known_blocker(
            data_sources=data_sources,
            order_name="#22582",
            fallback_status="blocked_candidate_safety_check_failed",
            fallback_summary=(
                "Not delivered, missing `1: review request`, related orders #22582/#22581 not ready"
            ),
            fallback_message=(
                "Do not send yet. Not delivered, missing `1: review request`, "
                "related order group #22582/#22581 not ready."
            ),
            fallback_reasons=[
                "blocked_missing_delivered_tag",
                "blocked_missing_review_request_tag",
                "blocked_merged_order_group_not_ready",
            ],
        ),
    ]


def _known_blocker(
    data_sources,
    order_name: str,
    fallback_status: str,
    fallback_summary: str,
    fallback_message: str,
    fallback_reasons: list[str],
) -> dict:
    source = _known_blocker_source(data_sources, order_name)
    source_status = _safe_text(source.get("status"), max_length=120)
    if source_status in {"", "blocked"}:
        source_status = fallback_status
    if order_name == "#22620":
        prior_order = _safe_text(source.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
        fallback_summary = f"Already sent to this customer via {prior_order}"
        fallback_message = f"Do not send. Already sent to this customer via {prior_order}."
    return {
        "order_name": order_name,
        "status": source_status,
        "blocker": _safe_text(source.get("blocker") or fallback_status, max_length=120),
        "summary": _safe_text(source.get("summary") or fallback_summary, max_length=240),
        "message": _safe_text(source.get("message") or fallback_message, max_length=300),
        "blocking_reasons": _dedupe_text(_string_list(source.get("blocking_reasons")) or fallback_reasons),
        "selected_candidate_safe_for_future_send": False,
    }


def _known_blocker_source(data_sources, order_name: str) -> dict:
    direct_key = "order_22620_blocker_status" if order_name == "#22620" else "order_22582_blocker_status"
    for data in data_sources:
        if not isinstance(data, dict):
            continue
        direct = data.get(direct_key)
        if isinstance(direct, dict):
            return direct
        for list_key in ("known_blockers_summary", "blocked_candidates_summary", "blocking_conditions"):
            for row in _dict_rows(data.get(list_key)):
                if _safe_text(row.get("order_name"), max_length=80) == order_name:
                    return row
    return {}


def _readiness_checklist(
    readiness_status: str,
    eligible_count: int,
    selected_order: str,
    latest_preflight_status: str,
    latest_execute_status: str,
    dependency_status: dict,
    env_status: dict,
    source_safety_findings: list[str],
) -> list[dict]:
    rows = [
        _checklist_row(
            "exactly_one_candidate",
            eligible_count == 1 and bool(selected_order),
            f"eligible_candidate_count={eligible_count}; selected_candidate={selected_order or 'None'}",
        ),
        _checklist_row(
            "final_preflight_ready",
            latest_preflight_status == READY_PREFLIGHT_STATUS,
            latest_preflight_status,
        ),
        _checklist_row(
            "execute_skeleton_safe",
            latest_execute_status
            in {
                BLOCKED_NO_CANDIDATE_STATUS,
                "blocked_missing_real_send_execute_flag",
                "ready_but_real_send_implementation_not_enabled_in_this_phase",
            },
            latest_execute_status,
        ),
        _checklist_row("gmail_dependencies_importable", dependency_status["all_importable"], dependency_status["status"]),
        _checklist_row("gmail_oauth_config_present", env_status["oauth_config_present"], env_status["oauth_config_status"]),
        _checklist_row("gmail_token_config_present", env_status["token_config_present"], env_status["token_config_status"]),
        _checklist_row("gmail_send_scope_present", env_status["gmail_send_scope_present"], env_status["scope_compatibility"]),
        _checklist_row("explicit_ack_required", True, REQUIRED_ACK_NAME),
        _checklist_row("explicit_real_send_execute_flag_required", True, REQUIRED_REAL_SEND_EXECUTE_FLAG_NAME),
        _checklist_row("single_send_limit_required", True, "exactly one candidate only"),
        _checklist_row("duplicate_suppression_required", True, "required before any future send"),
        _checklist_row("privacy_masking_required", True, "raw emails and full Gmail IDs blocked"),
        _checklist_row("post_send_audit_required_before_shopify_tag_write", True, "required in future phase"),
        _checklist_row("source_safety_flags_clear", not source_safety_findings, f"{len(source_safety_findings)} finding(s)"),
    ]
    if readiness_status == BLOCKED_NO_CANDIDATE_STATUS:
        rows.append(
            _checklist_row(
                "current_production_state",
                False,
                "blocked because no eligible Trustpilot candidate exists",
            )
        )
    return rows


def _checklist_row(name: str, passed: bool, detail: str) -> dict:
    return {
        "name": name,
        "passed": passed,
        "status": "pass" if passed else "blocked",
        "detail": _safe_text(detail, max_length=300),
    }


def _source_safety_findings(sources: dict) -> list[str]:
    findings = []
    for report in sources.values():
        if not isinstance(report, dict) or not report.get("loaded"):
            continue
        data = _source_data(report)
        findings.extend(_mapping_safety_findings(data, f"source_report:{report.get('key')}"))
        safety_flags = data.get("safety_flags")
        if isinstance(safety_flags, dict):
            findings.extend(_mapping_safety_findings(safety_flags, f"safety_flags:{report.get('key')}"))
        no_write_flags = data.get("no_write_safety_flags")
        if isinstance(no_write_flags, dict):
            findings.extend(_mapping_safety_findings(no_write_flags, f"no_write_safety_flags:{report.get('key')}"))
    return _dedupe_text(findings)


def _mapping_safety_findings(mapping: dict, prefix: str) -> list[str]:
    return [
        f"{prefix}:{key}"
        for key in sorted(FORBIDDEN_TRUE_FLAGS)
        if mapping.get(key) is True
    ]


def _source_report_status(sources: dict) -> list[dict]:
    return [_source_summary(report) for report in sources.values()]


def _source_summary(report: dict) -> dict:
    return {
        "key": _safe_text(report.get("key"), max_length=80),
        "relative_path": _safe_text(report.get("relative_path"), max_length=160),
        "present": report.get("present") is True,
        "loaded": report.get("loaded") is True,
        "status": _safe_text(report.get("status"), max_length=120),
        "timestamp": _safe_text(report.get("timestamp"), max_length=120),
        "error_sanitized": _safe_text(report.get("error_sanitized"), max_length=300),
    }


def _next_admin_action(readiness_status: str) -> str:
    if readiness_status == "ready_for_future_real_send_implementation_audit_only":
        return (
            "Before enabling a real Gmail implementation, rerun final preflight and this readiness audit, "
            "then require explicit ACK and execute flag."
        )
    return NEXT_ADMIN_ACTION_NO_CANDIDATE


def _dashboard_message(readiness_status: str) -> str:
    if readiness_status == BLOCKED_NO_CANDIDATE_STATUS:
        return "Gmail real-send implementation is not enabled yet. Current blocker: no eligible Trustpilot candidate."
    if readiness_status == "ready_for_future_real_send_implementation_audit_only":
        return "Readiness audit is green for a future separately approved real-send implementation."
    return "Gmail real-send implementation is not enabled yet. Review the readiness audit blockers."


def _issue_summary(readiness_status: str, known_blockers: list[dict]) -> str:
    if readiness_status == BLOCKED_NO_CANDIDATE_STATUS:
        return (
            "No eligible Trustpilot candidate. "
            f"#22620 remains blocked: {known_blockers[0]['summary']}. "
            f"#22582 remains blocked: {known_blockers[1]['summary']}."
        )
    if readiness_status == "ready_for_future_real_send_implementation_audit_only":
        return "Readiness audit passed for a future implementation, but this task sent no email and called no Gmail API."
    return f"Readiness audit is blocked: {readiness_status}."


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(_safe_payload(payload), report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status_class = (
        "ok"
        if payload["readiness_audit_status"] == "ready_for_future_real_send_implementation_audit_only"
        else "warn"
    )
    selected_candidate = payload.get("selected_candidate_order_name") or "-"
    blocking_rows = "\n".join(_render_condition_row(row) for row in payload["current_blocking_conditions"])
    if not blocking_rows:
        blocking_rows = '<tr><td colspan="3">No blocking conditions recorded.</td></tr>'
    checklist_rows = "\n".join(_render_checklist_row(row) for row in payload["readiness_checklist"])
    source_rows = "\n".join(_render_source_row(row) for row in payload["source_report_status"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Real-Send Readiness Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .status {{ border-left: 4px solid #d97706; background: #fff7ed; padding: 10px 12px; }}
    .status.ok {{ border-left-color: #16a34a; background: #f0fdf4; }}
  </style>
</head>
<body>
  <h1>Trustpilot Gmail Real-Send Readiness Audit</h1>
  <p class="status {status_class}">Readiness audit status: <strong>{escape(payload["readiness_audit_status"])}</strong></p>
  <p>{escape(payload["dashboard_message"])}</p>
  <p>{escape(payload["safety_message"])}</p>
  <p>Mode: <code>real-send-readiness-audit</code>. This task audits local readiness only; it cannot send email, create Gmail drafts, write Shopify tags, or call Trustpilot/Kudosi/Ali Reviews APIs.</p>
  <table>
    <tbody>
      <tr><th>Gmail dependencies</th><td>{escape(payload["gmail_dependency_status"]["status"])}</td></tr>
      <tr><th>Gmail OAuth config</th><td>{escape(payload["gmail_oauth_config_status"])}</td></tr>
      <tr><th>Gmail token config</th><td>{escape(payload["gmail_token_config_status"])}</td></tr>
      <tr><th>Legacy Gmail config</th><td>{payload["legacy_gmail_oauth_config_present"]}</td></tr>
      <tr><th>New Gmail file-path config</th><td>{payload["new_gmail_file_path_config_present"]}</td></tr>
      <tr><th>Gmail scope compatibility</th><td><code>{escape(payload["gmail_scope_compatibility_result"])}</code></td></tr>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(selected_candidate)}</td></tr>
      <tr><th>Latest auto refresh status</th><td><code>{escape(payload["latest_auto_refresh_status"])}</code></td></tr>
      <tr><th>Latest preflight status</th><td><code>{escape(payload["latest_preflight_status"])}</code></td></tr>
      <tr><th>Latest execute status</th><td><code>{escape(payload["latest_execute_status"])}</code></td></tr>
      <tr><th>Single-send limit</th><td>{escape(payload["single_send_limit_status"])}</td></tr>
      <tr><th>Duplicate suppression</th><td>{escape(payload["duplicate_suppression_status"])}</td></tr>
      <tr><th>Privacy checks</th><td>{escape(payload["privacy_masking_status"])}</td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
    </tbody>
  </table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Order</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Readiness Checklist</h2>
  <table><thead><tr><th>Check</th><th>Status</th><th>Detail</th></tr></thead><tbody>{checklist_rows}</tbody></table>
  <details>
    <summary>Advanced debug details</summary>
    <p>JSON report: <code>logs/{escape(REPORT_JSON_PATH.name)}</code></p>
    <p>HTML report: <code>logs/{escape(REPORT_HTML_PATH.name)}</code></p>
    <p>Required ACK name: <code>{escape(payload["required_ack_name"])}</code></p>
    <p>Required real-send execute flag name: <code>{escape(payload["required_real_send_execute_flag_name"])}</code></p>
    <p>Environment audit policy: process environment presence only; values are not reported.</p>
    <table>
      <thead><tr><th>Source</th><th>Path</th><th>Present</th><th>Loaded</th><th>Status</th></tr></thead>
      <tbody>{source_rows}</tbody>
    </table>
  </details>
</body>
</html>"""


def _render_condition_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(row.get('status', ''))}</code></td>"
        f"<td>{escape(row.get('order_name', '') or '-')}</td>"
        f"<td>{escape(row.get('detail', ''))}</td>"
        "</tr>"
    )


def _render_checklist_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(row.get('name', ''))}</code></td>"
        f"<td>{escape(row.get('status', ''))}</td>"
        f"<td>{escape(row.get('detail', ''))}</td>"
        "</tr>"
    )


def _render_source_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(row.get('key', ''))}</td>"
        f"<td><code>{escape(row.get('relative_path', ''))}</code></td>"
        f"<td>{escape(str(row.get('present') is True))}</td>"
        f"<td>{escape(str(row.get('loaded') is True))}</td>"
        f"<td><code>{escape(row.get('status', ''))}</code></td>"
        "</tr>"
    )


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "json_trustpilot_gmail_real_send_readiness_audit_path": str(json_path),
        "html_trustpilot_gmail_real_send_readiness_audit_path": str(html_path),
        "readiness_audit_status": payload["readiness_audit_status"],
        "gmail_dependencies_importable": payload["gmail_dependencies_importable"],
        "gmail_oauth_config_present": payload["gmail_oauth_config_present"],
        "gmail_oauth_config_status": payload["gmail_oauth_config_status"],
        "gmail_token_config_present": payload["gmail_token_config_present"],
        "gmail_token_config_status": payload["gmail_token_config_status"],
        "legacy_gmail_oauth_config_present": payload["legacy_gmail_oauth_config_present"],
        "new_gmail_file_path_config_present": payload["new_gmail_file_path_config_present"],
        "gmail_scope_compatibility_result": payload["gmail_scope_compatibility_result"],
        "gmail_send_scope_present": payload["gmail_send_scope_present"],
        "gmail_compose_scope_present": payload["gmail_compose_scope_present"],
        "latest_auto_refresh_status": payload["latest_auto_refresh_status"],
        "latest_preflight_status": payload["latest_preflight_status"],
        "latest_execute_status": payload["latest_execute_status"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "required_ack_name": payload["required_ack_name"],
        "required_real_send_execute_flag_name": payload["required_real_send_execute_flag_name"],
        "single_send_limit_enforced": payload["single_send_limit_enforced"],
        "single_send_limit_status": payload["single_send_limit_status"],
        "duplicate_suppression_required": payload["duplicate_suppression_required"],
        "duplicate_suppression_status": payload["duplicate_suppression_status"],
        "raw_email_output_blocked": payload["raw_email_output_blocked"],
        "full_gmail_id_output_blocked": payload["full_gmail_id_output_blocked"],
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "current_blocking_conditions": payload["current_blocking_conditions"],
        "next_admin_action": payload["next_admin_action"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    selected = payload["selected_candidate_order_name"] or "None"
    return (
        "Shopify review request Phase 5.15 Trustpilot Gmail real-send readiness audit finished.\n"
        f"Readiness audit status: {payload['readiness_audit_status']}\n"
        f"Gmail dependencies importable: {payload['gmail_dependencies_importable']}\n"
        f"Gmail OAuth config status: {payload['gmail_oauth_config_status']}\n"
        f"Gmail token config status: {payload['gmail_token_config_status']}\n"
        f"Legacy Gmail config present: {payload['legacy_gmail_oauth_config_present']}\n"
        f"Scope compatibility: {payload['gmail_scope_compatibility_result']}\n"
        f"Latest preflight status: {payload['latest_preflight_status']}\n"
        f"Latest execute status: {payload['latest_execute_status']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Selected candidate: {selected}\n"
        "Safety: no Gmail network/API call, no draft creation/update/delete, no email send, "
        "no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _report_status(data: dict) -> str:
    return _first_text(
        data,
        (
            "readiness_audit_status",
            "execution_status",
            "preflight_status",
            "executor_status",
            "gate_status",
            "refresh_status",
            "package_status",
            "automation_status",
            "report_status",
            "status",
        ),
    ) or "loaded"


def _first_text(mapping: dict, keys: tuple[str, ...]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _safe_text(value, max_length=300)
    return ""


def _int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dict_rows(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        return [_safe_text(value)] if _safe_text(value) else []
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            if isinstance(item, dict):
                result.append(_first_text(item, ("status", "reason", "detail", "summary")))
            else:
                result.append(_safe_text(item))
        return _dedupe_text(result)
    return []


def _dedupe_text(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = _safe_text(value, max_length=300)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _status_label(value: bool) -> str:
    return "present" if value else "missing"
