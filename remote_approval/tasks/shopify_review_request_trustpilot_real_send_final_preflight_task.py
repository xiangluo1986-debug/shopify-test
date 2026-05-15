import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_trustpilot_automation_dry_run_task import (
    _safe_payload,
    _safe_text,
    _safety_summary,
)
from remote_approval.tasks.shopify_review_request_trustpilot_eligibility import (
    CANONICAL_REVIEW_REQUEST_TAG,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_real_send_final_preflight"
COMMAND_LABEL = TASK_NAME
PHASE = "5.13"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_real_send_final_preflight.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_real_send_final_preflight.html"

SIMULATOR_PREFLIGHT_ENV_VAR = "SHOPIFY_REVIEW_REQUEST_REAL_PREFLIGHT_USE_SIMULATOR"
SIMULATOR_PREFLIGHT_ACK = "YES_I_UNDERSTAND_THIS_IS_FAKE_DATA"

REQUIRED_ACK_ENV_VAR = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK"
REQUIRED_ACK_VALUE = "YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND"
REQUIRED_ACK = f"{REQUIRED_ACK_ENV_VAR}={REQUIRED_ACK_VALUE}"

PRODUCTION_REPORTS = {
    "auto_queue_refresh": LOG_DIR / "shopify_review_request_trustpilot_auto_queue_refresh.json",
    "locked_send_readiness_package": (
        LOG_DIR / "shopify_review_request_trustpilot_locked_send_readiness_package.json"
    ),
    "locked_gmail_send_gate": LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate.json",
    "gmail_send_executor_shell": LOG_DIR / "shopify_review_request_trustpilot_gmail_send_executor_shell.json",
}

SIMULATOR_REPORTS = {
    "locked_gmail_send_gate_simulator_fixture": (
        LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate_simulator_fixture.json"
    ),
    "gmail_send_executor_shell_simulator_fixture": (
        LOG_DIR / "shopify_review_request_trustpilot_gmail_send_executor_shell_simulator_fixture.json"
    ),
}

PREFLIGHT_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
PREFLIGHT_STATUS_READY = "ready_for_real_send_execute_next_phase"
PREFLIGHT_STATUS_BLOCKED_MISSING_ACK = "blocked_missing_ack"
PREFLIGHT_STATUS_BLOCKED_MULTIPLE = "blocked_multiple_candidates_require_manual_selection"
PREFLIGHT_STATUS_BLOCKED_SAFETY = "blocked_candidate_safety_check_failed"
PREFLIGHT_STATUS_BLOCKED_GATE_NOT_READY = "blocked_gate_not_ready"
PREFLIGHT_STATUS_BLOCKED_EXECUTOR_NOT_READY = "blocked_executor_not_ready"

AUTO_REFRESH_STATUS_NO_CANDIDATE = "refreshed_no_eligible_candidate"
READINESS_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
GATE_STATUS_READY_FOR_ACK = "locked_send_gate_ready_for_ack"
GATE_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
EXECUTOR_STATUS_READY = "ready_for_future_real_send_execute"
EXECUTOR_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"

NEXT_ADMIN_ACTION_NO_CANDIDATE = (
    "Wait until auto refresh finds exactly one real eligible delivered order with canonical "
    f"`{CANONICAL_REVIEW_REQUEST_TAG}`, no duplicate/risk blockers, then re-run final preflight."
)

FORBIDDEN_SOURCE_TRUE_FLAGS = {
    "send_allowed_now",
    "draft_create_allowed_now",
    "gmail_api_allowed_now",
    "gmail_send_allowed_now",
    "gmail_draft_create_allowed_now",
    "gmail_api_call_performed",
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


def run_shopify_review_request_trustpilot_real_send_final_preflight_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    simulator_allowed = _simulator_allowed()
    sources = _load_sources(simulator_allowed=simulator_allowed)
    payload = _build_payload(
        sources=sources,
        simulator_allowed=simulator_allowed,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _simulator_allowed() -> bool:
    return os.environ.get(SIMULATOR_PREFLIGHT_ENV_VAR) == SIMULATOR_PREFLIGHT_ACK


def _load_sources(simulator_allowed: bool) -> dict:
    sources = {
        key: _load_json_report(key, path, production_report=True, simulator_allowed=simulator_allowed)
        for key, path in PRODUCTION_REPORTS.items()
    }
    if simulator_allowed:
        sources.update(
            {
                key: _load_json_report(key, path, production_report=False, simulator_allowed=True)
                for key, path in SIMULATOR_REPORTS.items()
            }
        )
    return sources


def _load_json_report(
    key: str,
    path: Path,
    production_report: bool,
    simulator_allowed: bool,
) -> dict:
    report = {
        "key": key,
        "relative_path": f"logs/{path.name}",
        "present": path.exists(),
        "loaded": False,
        "usable": False,
        "production_report": production_report,
        "simulator_report": False,
        "ignored_by_default": False,
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

    simulator_report = _is_simulator_report(data)
    ignored_by_default = simulator_report and not simulator_allowed
    report.update(
        {
            "loaded": True,
            "usable": not ignored_by_default,
            "simulator_report": simulator_report,
            "ignored_by_default": ignored_by_default,
            "status": "ignored_simulator_report_by_default"
            if ignored_by_default
            else _report_status(data),
            "timestamp": _first_text(
                data,
                ("report_generated_at", "timestamp", "refreshed_at", "generated_at", "created_at", "finished_at"),
            ),
            "data": {} if ignored_by_default else data,
        }
    )
    return report


def _is_simulator_report(data: dict) -> bool:
    return (
        data.get("simulator_only") is True
        or data.get("sandbox_fixture") is True
        or data.get("source") == "trustpilot_candidate_simulator"
        or bool(data.get("fake_candidate_summary"))
    )


def _build_payload(sources: dict, simulator_allowed: bool, duration_seconds: float) -> dict:
    auto_report = sources.get("auto_queue_refresh") or {}
    readiness_report = sources.get("locked_send_readiness_package") or {}
    gate_report = _select_gate_report(sources)
    executor_report = _select_executor_report(sources)

    auto_data = _report_data(auto_report)
    readiness_data = _report_data(readiness_report)
    gate_data = _report_data(gate_report)
    executor_data = _report_data(executor_report)

    auto_refresh_status = _source_status(
        auto_report,
        auto_data,
        ("refresh_status", "report_status", "status"),
        AUTO_REFRESH_STATUS_NO_CANDIDATE,
    )
    readiness_status = _source_status(
        readiness_report,
        readiness_data,
        ("package_status", "automation_status", "report_status", "status"),
        READINESS_STATUS_BLOCKED_NO_CANDIDATE,
    )
    gate_status = _source_status(
        gate_report,
        gate_data,
        ("gate_status", "report_status", "status"),
        _fallback_gate_status(auto_refresh_status, readiness_status),
    )
    executor_status = _source_status(
        executor_report,
        executor_data,
        ("executor_status", "report_status", "status"),
        _fallback_executor_status(gate_status),
    )

    eligible_count = _candidate_count(executor_data, gate_data, readiness_data, auto_data)
    selected_order = _selected_candidate_order_name(executor_data, gate_data, readiness_data, auto_data, eligible_count)
    exactly_one_candidate = eligible_count == 1
    gate_ready = gate_status == GATE_STATUS_READY_FOR_ACK
    executor_ready = executor_status == EXECUTOR_STATUS_READY
    ack_present = os.environ.get(REQUIRED_ACK_ENV_VAR) == REQUIRED_ACK_VALUE
    source_safety_findings = _source_safety_findings(sources)
    preflight_status = _preflight_status(
        eligible_count=eligible_count,
        gate_ready=gate_ready,
        executor_ready=executor_ready,
        ack_present=ack_present,
        source_safety_findings=source_safety_findings,
    )
    real_send_execute_allowed_next_phase = preflight_status == PREFLIGHT_STATUS_READY
    known_blockers = _known_blockers_summary(readiness_data, gate_data, executor_data, auto_data)
    blocking_conditions = _blocking_conditions(
        preflight_status=preflight_status,
        eligible_count=eligible_count,
        gate_status=gate_status,
        executor_status=executor_status,
        ack_present=ack_present,
        selected_order=selected_order,
        source_safety_findings=source_safety_findings,
        known_blockers=known_blockers,
    )
    simulator_reports_used = _simulator_reports_used(gate_report, executor_report, sources, simulator_allowed)
    generated_at = utc_now_iso()
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "real-send-final-preflight",
        "dry_run": True,
        "final_preflight_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "preflight_status": preflight_status,
        "production_reports_used": True,
        "simulator_reports_used": simulator_reports_used,
        "simulator_fixture_enabled": simulator_allowed,
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order if selected_order else None,
        "auto_refresh_status": auto_refresh_status,
        "readiness_status": readiness_status,
        "gate_status": gate_status,
        "executor_status": executor_status,
        "exactly_one_candidate": exactly_one_candidate,
        "gate_ready": gate_ready,
        "executor_ready": executor_ready,
        "ack_required": True,
        "ack_present": ack_present,
        "required_ack": REQUIRED_ACK,
        "real_send_execute_allowed_next_phase": real_send_execute_allowed_next_phase,
        "blocking_conditions": blocking_conditions,
        "next_admin_action": _next_admin_action(preflight_status, simulator_reports_used),
        "current_state_message": _current_state_message(preflight_status),
        "safety_message": (
            "No email has been sent. No Gmail draft has been created. "
            "No Shopify tag has been written."
        ),
        "known_blockers_summary": known_blockers,
        "order_22620_blocker_status": known_blockers[0],
        "order_22582_blocker_status": known_blockers[1],
        "source_report_status": _source_report_status(sources),
        "selected_source_reports": {
            "auto_queue_refresh": _source_summary(auto_report),
            "locked_send_readiness_package": _source_summary(readiness_report),
            "locked_gmail_send_gate": _source_summary(gate_report),
            "gmail_send_executor_shell": _source_summary(executor_report),
        },
        "no_write_safety_flags": _no_write_safety_flags(),
        "report_paths": {
            "json": str(REPORT_JSON_PATH),
            "html": str(REPORT_HTML_PATH),
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(
            preflight_status=preflight_status,
            eligible_count=eligible_count,
            selected_order=selected_order,
            known_blockers=known_blockers,
        ),
        **_safety_summary(),
        "gmail_draft_create_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
    }
    return _safe_payload(payload)


def _select_gate_report(sources: dict) -> dict:
    primary = sources.get("locked_gmail_send_gate") or {}
    fixture = sources.get("locked_gmail_send_gate_simulator_fixture") or {}
    if fixture.get("usable"):
        return fixture
    if primary.get("usable"):
        return primary
    return primary


def _select_executor_report(sources: dict) -> dict:
    primary = sources.get("gmail_send_executor_shell") or {}
    primary_data = _report_data(primary)
    if primary.get("usable") and primary.get("simulator_report") and primary_data.get("executor_status"):
        return primary
    fixture = sources.get("gmail_send_executor_shell_simulator_fixture") or {}
    if fixture.get("usable"):
        return fixture
    if primary.get("usable"):
        return primary
    return primary


def _report_data(report: dict) -> dict:
    data = report.get("data") if report.get("usable") else {}
    return data if isinstance(data, dict) else {}


def _source_status(report: dict, data: dict, keys: tuple[str, ...], fallback: str) -> str:
    if report.get("usable"):
        return _first_text(data, keys) or _safe_text(report.get("status"), max_length=120) or fallback
    status = _safe_text(report.get("status"), max_length=120)
    if status == "ignored_simulator_report_by_default":
        return fallback
    return fallback


def _fallback_gate_status(auto_refresh_status: str, readiness_status: str) -> str:
    if auto_refresh_status == AUTO_REFRESH_STATUS_NO_CANDIDATE:
        return GATE_STATUS_BLOCKED_NO_CANDIDATE
    if readiness_status == READINESS_STATUS_BLOCKED_NO_CANDIDATE:
        return GATE_STATUS_BLOCKED_NO_CANDIDATE
    return GATE_STATUS_BLOCKED_NO_CANDIDATE


def _fallback_executor_status(gate_status: str) -> str:
    if gate_status == GATE_STATUS_BLOCKED_NO_CANDIDATE:
        return EXECUTOR_STATUS_BLOCKED_NO_CANDIDATE
    return "blocked_gate_not_ready"


def _candidate_count(*data_sources: dict) -> int:
    for data in data_sources:
        if not isinstance(data, dict):
            continue
        if "eligible_candidate_count" in data:
            return _int_or_zero(data.get("eligible_candidate_count"))
    return 0


def _selected_candidate_order_name(*data_sources_and_count) -> str:
    eligible_count = data_sources_and_count[-1]
    data_sources = data_sources_and_count[:-1]
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
        selected_candidate = data.get("selected_candidate")
        if isinstance(selected_candidate, dict):
            selected = _safe_text(selected_candidate.get("order_name"), max_length=80)
            if selected:
                return selected
    return ""


def _preflight_status(
    eligible_count: int,
    gate_ready: bool,
    executor_ready: bool,
    ack_present: bool,
    source_safety_findings: list[str],
) -> str:
    if source_safety_findings:
        return PREFLIGHT_STATUS_BLOCKED_SAFETY
    if eligible_count == 0:
        return PREFLIGHT_STATUS_BLOCKED_NO_CANDIDATE
    if eligible_count > 1:
        return PREFLIGHT_STATUS_BLOCKED_MULTIPLE
    if not gate_ready:
        return PREFLIGHT_STATUS_BLOCKED_GATE_NOT_READY
    if not ack_present:
        return PREFLIGHT_STATUS_BLOCKED_MISSING_ACK
    if not executor_ready:
        return PREFLIGHT_STATUS_BLOCKED_EXECUTOR_NOT_READY
    return PREFLIGHT_STATUS_READY


def _source_safety_findings(sources: dict) -> list[str]:
    findings = []
    for report in sources.values():
        if not report.get("usable"):
            continue
        data = report.get("data") if isinstance(report.get("data"), dict) else {}
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
        for key in sorted(FORBIDDEN_SOURCE_TRUE_FLAGS)
        if mapping.get(key) is True
    ]


def _blocking_conditions(
    preflight_status: str,
    eligible_count: int,
    gate_status: str,
    executor_status: str,
    ack_present: bool,
    selected_order: str,
    source_safety_findings: list[str],
    known_blockers: list[dict],
) -> list[dict]:
    if preflight_status == PREFLIGHT_STATUS_READY:
        return []
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_NO_CANDIDATE:
        conditions = [
            {
                "status": PREFLIGHT_STATUS_BLOCKED_NO_CANDIDATE,
                "detail": "There is no real eligible Trustpilot candidate in the production queue.",
            }
        ]
        for blocker in known_blockers:
            conditions.append(
                {
                    "status": _safe_text(blocker.get("status"), max_length=120),
                    "order_name": _safe_text(blocker.get("order_name"), max_length=80),
                    "detail": _safe_text(blocker.get("summary") or blocker.get("message"), max_length=300),
                }
            )
        return conditions
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_MULTIPLE:
        return [
            {
                "status": PREFLIGHT_STATUS_BLOCKED_MULTIPLE,
                "detail": f"Eligible candidate count is {eligible_count}; exactly one must be selected.",
            }
        ]
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_MISSING_ACK:
        return [
            {
                "status": PREFLIGHT_STATUS_BLOCKED_MISSING_ACK,
                "detail": "The locked ACK for one Trustpilot Gmail send is not present.",
            }
        ]
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_GATE_NOT_READY:
        return [
            {
                "status": PREFLIGHT_STATUS_BLOCKED_GATE_NOT_READY,
                "detail": f"Gate status is `{gate_status}`, not `{GATE_STATUS_READY_FOR_ACK}`.",
            }
        ]
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_EXECUTOR_NOT_READY:
        return [
            {
                "status": PREFLIGHT_STATUS_BLOCKED_EXECUTOR_NOT_READY,
                "detail": f"Executor status is `{executor_status}`, not `{EXECUTOR_STATUS_READY}`.",
            }
        ]
    conditions = [
        {
            "status": PREFLIGHT_STATUS_BLOCKED_SAFETY,
            "detail": "A source report contains a true safety flag that is forbidden for this phase.",
        }
    ]
    for finding in source_safety_findings:
        conditions.append(
            {
                "status": "source_safety_finding",
                "detail": finding,
                "selected_candidate_order_name": selected_order or "",
                "ack_present": ack_present,
            }
        )
    return conditions


def _next_admin_action(preflight_status: str, simulator_reports_used: bool) -> str:
    if preflight_status == PREFLIGHT_STATUS_READY:
        if simulator_reports_used:
            return (
                "Simulator branch is ready only for fake-data validation. Re-run production final preflight "
                "without simulator mode before any future real-send execute task."
            )
        return (
            "Proceed only to a separate explicitly approved real-send execute task. "
            "This final preflight does not send email."
        )
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_MISSING_ACK:
        return "Review the single gate-ready candidate, set the locked ACK only when approved, then re-run final preflight."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_MULTIPLE:
        return "Manually select exactly one safe Trustpilot candidate, then re-run gate, executor, and final preflight."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_GATE_NOT_READY:
        return "Re-run the production locked Gmail send gate after exactly one real safe candidate is available."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_EXECUTOR_NOT_READY:
        return "Re-run the production Gmail send executor shell after gate readiness and locked ACK are confirmed."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_SAFETY:
        return "Stop and review source report safety flags before any future real-send execute task."
    return NEXT_ADMIN_ACTION_NO_CANDIDATE


def _current_state_message(preflight_status: str) -> str:
    if preflight_status == PREFLIGHT_STATUS_READY:
        return "Real send preflight is ready for a future separate execute task."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_MISSING_ACK:
        return "Real send preflight is blocked because the locked ACK is missing."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_MULTIPLE:
        return "Real send preflight is blocked because multiple candidates require manual selection."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_GATE_NOT_READY:
        return "Real send preflight is blocked because the locked Gmail send gate is not ready."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_EXECUTOR_NOT_READY:
        return "Real send preflight is blocked because the executor shell is not ready."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_SAFETY:
        return "Real send preflight is blocked by a source safety check."
    return "Real send preflight is blocked because there is no eligible Trustpilot candidate."


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
            fallback_status=PREFLIGHT_STATUS_BLOCKED_SAFETY,
            fallback_summary=(
                f"Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
                "related orders #22582/#22581 not ready"
            ),
            fallback_message=(
                f"Do not send yet. Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
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
    if order_name == "#22620":
        prior_order = _safe_text(source.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
        fallback_summary = f"Already sent to this customer via {prior_order}"
        fallback_message = f"Do not send. Already sent to this customer via {prior_order}."
    source_status = _safe_text(source.get("status"), max_length=120)
    if source_status in {"", "blocked"}:
        source_status = fallback_status
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
    key = "order_22620_blocker_status" if order_name == "#22620" else "order_22582_blocker_status"
    for data in data_sources:
        if not isinstance(data, dict):
            continue
        direct = data.get(key)
        if isinstance(direct, dict):
            return direct
        for list_key in ("known_blockers_summary", "blocked_candidates_summary", "blocking_conditions"):
            for row in _dict_rows(data.get(list_key)):
                if _safe_text(row.get("order_name"), max_length=80) == order_name:
                    return row
    return {}


def _simulator_reports_used(gate_report: dict, executor_report: dict, sources: dict, simulator_allowed: bool) -> bool:
    if not simulator_allowed:
        return False
    selected_uses_simulator = (
        gate_report.get("usable")
        and gate_report.get("simulator_report")
        or executor_report.get("usable")
        and executor_report.get("simulator_report")
    )
    fixture_usable = any(
        report.get("usable") and report.get("simulator_report")
        for key, report in sources.items()
        if key in SIMULATOR_REPORTS
    )
    return bool(selected_uses_simulator or fixture_usable)


def _source_report_status(sources: dict) -> list[dict]:
    return [_source_summary(report) for report in sources.values()]


def _source_summary(report: dict) -> dict:
    return {
        "key": _safe_text(report.get("key"), max_length=80),
        "relative_path": _safe_text(report.get("relative_path"), max_length=160),
        "present": report.get("present") is True,
        "loaded": report.get("loaded") is True,
        "usable": report.get("usable") is True,
        "production_report": report.get("production_report") is True,
        "simulator_report": report.get("simulator_report") is True,
        "ignored_by_default": report.get("ignored_by_default") is True,
        "status": _safe_text(report.get("status"), max_length=120),
        "timestamp": _safe_text(report.get("timestamp"), max_length=120),
        "error_sanitized": _safe_text(report.get("error_sanitized"), max_length=300),
    }


def _no_write_safety_flags() -> dict:
    return {
        "final_preflight_only": True,
        "source_reports_read_only": True,
        "production_reports_used": True,
        "gmail_api_call_performed": False,
        "gmail_oauth_token_exchange_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_created": False,
        "gmail_draft_updated": False,
        "gmail_draft_deleted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_allowed_now": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "external_review_api_call_allowed_now": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "ali_reviews_write_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
        "all_new_actions_no_write_confirmed": True,
    }


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
    status_class = "ok" if payload["preflight_status"] == PREFLIGHT_STATUS_READY else "warn"
    selected_candidate = payload.get("selected_candidate_order_name") or "-"
    source_rows = "\n".join(
        "<tr>"
        f"<td>{escape(source['key'])}</td>"
        f"<td><code>{escape(source['relative_path'])}</code></td>"
        f"<td>{escape(str(source['present']))}</td>"
        f"<td>{escape(str(source['loaded']))}</td>"
        f"<td>{escape(str(source['usable']))}</td>"
        f"<td>{escape(str(source['simulator_report']))}</td>"
        f"<td>{escape(str(source['ignored_by_default']))}</td>"
        f"<td><code>{escape(source['status'])}</code></td>"
        "</tr>"
        for source in payload["source_report_status"]
    )
    blocking_rows = "\n".join(_render_condition_row(row) for row in payload["blocking_conditions"])
    if not blocking_rows:
        blocking_rows = '<tr><td colspan="3">No blocking conditions for the next phase.</td></tr>'
    blocker_rows = "\n".join(_render_blocker_row(row) for row in payload["known_blockers_summary"])
    safety_rows = "\n".join(
        f"<tr><td><code>{escape(key)}</code></td><td>{escape(str(value))}</td></tr>"
        for key, value in payload["no_write_safety_flags"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Real Send Final Preflight</title>
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
  <h1>Trustpilot Real Send Final Preflight</h1>
  <p class="status {status_class}">Preflight status: <strong>{escape(payload["preflight_status"])}</strong></p>
  <p>{escape(payload["current_state_message"])}</p>
  <p>{escape(payload["safety_message"])}</p>
  <p>Mode: <code>real-send-final-preflight</code>. No Gmail API was called, no Gmail draft was created or updated, no email was sent, no Shopify tag was written, and no Trustpilot/Kudosi/Ali Reviews API was called.</p>
  <table>
    <tbody>
      <tr><th>Production reports used</th><td>{escape(_yes_no(payload["production_reports_used"]))}</td></tr>
      <tr><th>Simulator reports used</th><td>{escape(_yes_no(payload["simulator_reports_used"]))}</td></tr>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(selected_candidate)}</td></tr>
      <tr><th>Auto refresh status</th><td><code>{escape(payload["auto_refresh_status"])}</code></td></tr>
      <tr><th>Readiness status</th><td><code>{escape(payload["readiness_status"])}</code></td></tr>
      <tr><th>Gate status</th><td><code>{escape(payload["gate_status"])}</code></td></tr>
      <tr><th>Executor status</th><td><code>{escape(payload["executor_status"])}</code></td></tr>
      <tr><th>ACK present</th><td>{escape(_yes_no(payload["ack_present"]))}</td></tr>
      <tr><th>Real send execute allowed next phase</th><td>{escape(_yes_no(payload["real_send_execute_allowed_next_phase"]))}</td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
    </tbody>
  </table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Order</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Known Blockers</h2>
  <table><thead><tr><th>Order</th><th>Status</th><th>Summary</th><th>Message</th></tr></thead><tbody>{blocker_rows}</tbody></table>
  <h2>No-Write Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <details>
    <summary>Advanced debug details</summary>
    <p>JSON report: <code>{escape(str(REPORT_JSON_PATH))}</code></p>
    <p>HTML report: <code>{escape(str(REPORT_HTML_PATH))}</code></p>
    <p>Required ACK: <code>{escape(payload["required_ack"])}</code></p>
    <table>
      <thead><tr><th>Key</th><th>Path</th><th>Present</th><th>Loaded</th><th>Usable</th><th>Simulator</th><th>Ignored</th><th>Status</th></tr></thead>
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


def _render_blocker_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(row.get('order_name', ''))}</td>"
        f"<td><code>{escape(row.get('status', ''))}</code></td>"
        f"<td>{escape(row.get('summary', ''))}</td>"
        f"<td>{escape(row.get('message', ''))}</td>"
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
        "json_trustpilot_real_send_final_preflight_path": str(json_path),
        "html_trustpilot_real_send_final_preflight_path": str(html_path),
        "preflight_status": payload["preflight_status"],
        "production_reports_used": payload["production_reports_used"],
        "simulator_reports_used": payload["simulator_reports_used"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "auto_refresh_status": payload["auto_refresh_status"],
        "readiness_status": payload["readiness_status"],
        "gate_status": payload["gate_status"],
        "executor_status": payload["executor_status"],
        "exactly_one_candidate": payload["exactly_one_candidate"],
        "gate_ready": payload["gate_ready"],
        "executor_ready": payload["executor_ready"],
        "ack_required": payload["ack_required"],
        "ack_present": payload["ack_present"],
        "real_send_execute_allowed_next_phase": payload["real_send_execute_allowed_next_phase"],
        "blocking_conditions": payload["blocking_conditions"],
        "next_admin_action": payload["next_admin_action"],
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_created": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "order_22620_blocker_status": payload["order_22620_blocker_status"]["status"],
        "order_22582_blocker_status": payload["order_22582_blocker_status"]["status"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    selected = payload["selected_candidate_order_name"] or "None"
    return (
        "Shopify review request Phase 5.13 Trustpilot real send final preflight finished.\n"
        f"Preflight status: {payload['preflight_status']}\n"
        f"Production reports used: {payload['production_reports_used']}\n"
        f"Simulator reports used: {payload['simulator_reports_used']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Selected candidate: {selected}\n"
        f"Gate status: {payload['gate_status']}\n"
        f"Executor status: {payload['executor_status']}\n"
        f"ACK present: {payload['ack_present']}\n"
        f"Real send execute allowed next phase: {payload['real_send_execute_allowed_next_phase']}\n"
        "Safety: no Gmail API, no draft creation/update/delete, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(preflight_status: str, eligible_count: int, selected_order: str, known_blockers: list[dict]) -> str:
    if preflight_status == PREFLIGHT_STATUS_READY:
        return (
            f"Exactly one Trustpilot candidate ({selected_order}) passed final preflight for a future separate "
            "real-send execute task; this task still sent no email and called no Gmail API."
        )
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_MULTIPLE:
        return f"{eligible_count} Trustpilot candidates are eligible; manual selection is required before final preflight can pass."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_MISSING_ACK:
        return "Exactly one Trustpilot candidate is gate-ready, but the locked ACK is missing."
    if preflight_status in {PREFLIGHT_STATUS_BLOCKED_GATE_NOT_READY, PREFLIGHT_STATUS_BLOCKED_EXECUTOR_NOT_READY}:
        return "Trustpilot final preflight is blocked because the upstream real gate/executor reports are not ready."
    if preflight_status == PREFLIGHT_STATUS_BLOCKED_SAFETY:
        return "Trustpilot final preflight is blocked by source safety flags."
    return (
        "No eligible Trustpilot candidate. "
        f"#22620 remains blocked: {known_blockers[0]['summary']}. "
        f"#22582 remains blocked: {known_blockers[1]['summary']}."
    )


def _report_status(data: dict) -> str:
    return _first_text(
        data,
        (
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


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"
