import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_trustpilot_automation_dry_run_task import (
    _safe_payload,
    _safe_text,
    _safety_summary,
    _string_list,
)
from remote_approval.tasks.shopify_review_request_trustpilot_eligibility import (
    CANONICAL_REVIEW_REQUEST_TAG,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner"
COMMAND_LABEL = TASK_NAME
PHASE = "5.19B"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.html"

REQUIRED_FUTURE_ENV_FLAG_NAME = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_DRAFT_CREATE"
REQUIRED_FUTURE_ENV_FLAG_VALUE = "YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_DRAFT_CREATE"
SIMULATOR_FIXTURE_ENV_NAME = "SHOPIFY_REVIEW_REQUEST_USE_SIMULATOR_FIXTURE"
SIMULATOR_FIXTURE_ENV_VALUE = "YES_I_UNDERSTAND_THIS_IS_FAKE_DATA"

SOURCE_REPORTS = {
    "draft_only_preflight": LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_only_preflight.json",
    "scope_compatibility_resolver": (
        LOG_DIR / "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json"
    ),
    "auto_queue_refresh": LOG_DIR / "shopify_review_request_trustpilot_auto_queue_refresh.json",
    "locked_send_readiness_package": (
        LOG_DIR / "shopify_review_request_trustpilot_locked_send_readiness_package.json"
    ),
    "locked_gmail_send_gate": LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate.json",
    "real_send_final_preflight": LOG_DIR / "shopify_review_request_trustpilot_real_send_final_preflight.json",
}

SIMULATOR_SOURCE_REPORTS = {
    "simulator_locked_gmail_send_gate": (
        LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate_simulator_fixture.json"
    ),
    "simulator_gmail_send_executor_shell": (
        LOG_DIR / "shopify_review_request_trustpilot_gmail_send_executor_shell_simulator_fixture.json"
    ),
    "simulator_candidate_report": LOG_DIR / "shopify_review_request_trustpilot_candidate_simulator.json",
}

BLOCKED_MISSING_REQUIREMENTS = "blocked_missing_requirements"
BLOCKED_MISSING_DRAFT_CREATE_APPROVAL = "blocked_missing_draft_create_approval"
READY_BUT_DISABLED = "ready_but_draft_creation_not_enabled_in_this_phase"
BLOCKED_PRIVACY = "blocked_privacy_scan_failed"

BLOCKED_SCOPE_MISSING = "blocked_scope_missing"
BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
READY_DRAFT_ONLY = "ready_for_one_draft_create_next_phase"
READY_SEND_SCOPE = "draft_path_available_but_send_scope_also_available"
SCOPE_MISSING = "scope_missing"
SCOPE_COMPOSE_ONLY = "gmail_compose_only"
SCOPE_SEND_AVAILABLE = "gmail_send_scope_available"
SCOPE_BROAD_AVAILABLE = "broad_mail_scope_available"

CURRENT_BLOCKED_MESSAGE = (
    "Draft creation is not ready yet. Gmail permission is not configured, and there is no eligible order."
)

READY_SOURCE_STATUSES = {
    "ready_for_real_send_execute_next_phase",
    "ready_but_real_send_implementation_not_enabled_in_this_phase",
    "refreshed_locked_send_candidate_ready",
    "locked_send_ready_for_human_approval",
    "locked_send_gate_ready_for_ack",
    READY_DRAFT_ONLY,
    READY_SEND_SCOPE,
}

FORBIDDEN_SOURCE_TRUE_FLAGS = {
    "send_allowed_now",
    "draft_create_allowed_now",
    "gmail_api_allowed_now",
    "gmail_send_allowed_now",
    "gmail_draft_create_allowed_now",
    "gmail_network_call_performed",
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
    "token_file_read",
    "credential_file_read",
    "secret_value_printed",
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
    "raw_customer_email_output",
    "full_gmail_draft_or_message_id_output",
}

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}")
ACCESS_TOKEN_VALUE_RE = re.compile(r"(?i)\baccess[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
REFRESH_TOKEN_VALUE_RE = re.compile(r"(?i)\brefresh[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
CLIENT_SECRET_VALUE_RE = re.compile(r"(?i)\bclient[_-]?secret\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
PRIVATE_KEY_RE = re.compile(r"(?i)-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----|\bprivate[_-]?key\b\s*[:=]")
FULL_GMAIL_ID_RE = re.compile(
    r"(?i)\"(?:gmail_)?(?:draft|message)_id\"\s*:\s*\"[A-Za-z0-9_-]{16,}\""
)
ALLOWED_EMAILS = {"info@kidstoylover.com"}
ALLOWED_EMAIL_DOMAINS = {"example.invalid"}


def run_shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    simulator_fixture_enabled = _simulator_fixture_enabled()
    sources = _load_source_reports(simulator_fixture_enabled=simulator_fixture_enabled)
    payload = _build_payload(
        sources=sources,
        simulator_fixture_enabled=simulator_fixture_enabled,
        duration_seconds=round(time.time() - started, 3),
    )
    payload["privacy_scan_summary"] = _privacy_scan_for_payload(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["locked_runner_status"] = BLOCKED_PRIVACY
        payload["draft_create_allowed_by_preflight"] = False
        payload["draft_create_allowed_by_env"] = False
        payload["next_admin_action"] = "Inspect privacy scan counters before any future draft creation phase."
        payload["dashboard_message"] = "Draft creation is blocked because the generated report privacy scan failed."
    payload = _safe_payload(payload)
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_source_reports(simulator_fixture_enabled: bool) -> dict:
    sources = {
        key: _load_json_report(key=key, path=path, simulator_allowed=False)
        for key, path in SOURCE_REPORTS.items()
    }
    if simulator_fixture_enabled:
        sources.update(
            {
                key: _load_json_report(key=key, path=path, simulator_allowed=True)
                for key, path in SIMULATOR_SOURCE_REPORTS.items()
            }
        )
    return sources


def _load_json_report(key: str, path: Path, simulator_allowed: bool) -> dict:
    report = {
        "key": key,
        "relative_path": f"logs/{path.name}",
        "present": path.exists(),
        "loaded": False,
        "usable": False,
        "simulator_report": False,
        "status": "missing",
        "timestamp": "",
        "modified_at": 0.0,
        "error_sanitized": "",
        "data": {},
    }
    if not path.exists():
        return report
    try:
        report["modified_at"] = path.stat().st_mtime
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
    usable = not simulator_report or simulator_allowed
    report.update(
        {
            "loaded": True,
            "usable": usable,
            "simulator_report": simulator_report,
            "status": _report_status(data) if usable else "ignored_simulator_report",
            "timestamp": _first_text(
                data,
                ("report_generated_at", "timestamp", "refreshed_at", "generated_at", "created_at", "finished_at"),
            ),
            "data": data if usable else {},
        }
    )
    return report


def _build_payload(sources: dict, simulator_fixture_enabled: bool, duration_seconds: float) -> dict:
    generated_at = utc_now_iso()
    scope_summary = _scope_summary(sources)
    candidate = _candidate_snapshot(sources, simulator_fixture_enabled=simulator_fixture_enabled)
    source_safety_findings = _source_safety_findings(sources)
    known_blockers = _known_blockers_summary(sources)
    draft_preflight_status = _draft_preflight_status(
        sources=sources,
        scope_summary=scope_summary,
        candidate=candidate,
        simulator_fixture_enabled=simulator_fixture_enabled,
    )

    exactly_one_candidate = candidate["eligible_candidate_count"] == 1 and bool(
        candidate["selected_candidate_order_name"]
    )
    selected_candidate_safe = exactly_one_candidate and candidate["selected_candidate_safe"] and not source_safety_findings
    simulated_ready = (
        simulator_fixture_enabled
        and candidate["source_key"].startswith("simulator_")
        and scope_summary["draft_scope_available"]
        and selected_candidate_safe
    )
    draft_create_allowed_by_preflight = (
        _draft_preflight_allowed(sources, draft_preflight_status)
        or simulated_ready
    )
    requirements_ready = (
        scope_summary["draft_scope_available"]
        and exactly_one_candidate
        and selected_candidate_safe
        and draft_create_allowed_by_preflight
        and not source_safety_findings
    )
    draft_create_requested = _draft_create_requested()
    draft_create_allowed_by_env = requirements_ready and draft_create_requested
    missing_requirements_plain = _missing_requirements_plain(
        draft_scope_available=scope_summary["draft_scope_available"],
        eligible_candidate_count=candidate["eligible_candidate_count"],
        exactly_one_candidate=exactly_one_candidate,
        selected_candidate_safe=selected_candidate_safe,
        draft_create_requested=draft_create_requested,
        draft_create_allowed_by_preflight=draft_create_allowed_by_preflight,
        source_safety_findings=source_safety_findings,
    )
    locked_runner_status = _locked_runner_status(
        requirements_ready=requirements_ready,
        draft_create_requested=draft_create_requested,
    )
    blocking_conditions = _blocking_conditions(
        missing_requirements_plain=missing_requirements_plain,
        source_safety_findings=source_safety_findings,
        known_blockers=known_blockers,
    )
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "gmail-one-draft-create-locked-runner",
        "dry_run": True,
        "locked_runner_shell_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "locked_runner_status": locked_runner_status,
        "draft_preflight_status": draft_preflight_status,
        "scope_status": scope_summary["scope_status"],
        "draft_scope_available": scope_summary["draft_scope_available"],
        "compose_scope_available": scope_summary["compose_scope_available"],
        "send_scope_available": scope_summary["send_scope_available"],
        "broad_mail_scope_available": scope_summary["broad_mail_scope_available"],
        "draft_only_mode": scope_summary["draft_only_mode"],
        "real_send_scope_available": scope_summary["real_send_scope_available"],
        "eligible_candidate_count": candidate["eligible_candidate_count"],
        "selected_candidate_order_name": candidate["selected_candidate_order_name"] or None,
        "exactly_one_candidate": exactly_one_candidate,
        "selected_candidate_safe": selected_candidate_safe,
        "draft_create_requested": draft_create_requested,
        "draft_create_allowed_by_preflight": draft_create_allowed_by_preflight,
        "draft_create_allowed_by_env": draft_create_allowed_by_env,
        "draft_create_performed": False,
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_created": False,
        "gmail_draft_updated": False,
        "gmail_draft_deleted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "required_future_env_flag_name": REQUIRED_FUTURE_ENV_FLAG_NAME,
        "required_future_env_flag_value_documented": REQUIRED_FUTURE_ENV_FLAG_VALUE,
        "missing_requirements_plain": missing_requirements_plain,
        "blocking_conditions": blocking_conditions,
        "known_blockers_summary": known_blockers,
        "next_admin_action": _next_admin_action(
            locked_runner_status=locked_runner_status,
            scope_status=scope_summary["scope_status"],
            eligible_candidate_count=candidate["eligible_candidate_count"],
        ),
        "dashboard_message": _dashboard_message(
            locked_runner_status=locked_runner_status,
            scope_status=scope_summary["scope_status"],
            eligible_candidate_count=candidate["eligible_candidate_count"],
        ),
        "privacy_scan_summary": _empty_privacy_scan_summary(),
        "source_candidate_summary": candidate,
        "source_report_status": _source_report_status(sources),
        "source_safety_findings": source_safety_findings,
        "simulator_fixture_enabled": simulator_fixture_enabled,
        "no_write_safety_flags": _no_write_safety_flags(),
        "report_paths": {
            "json": f"logs/{REPORT_JSON_PATH.name}",
            "html": f"logs/{REPORT_HTML_PATH.name}",
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(
            locked_runner_status=locked_runner_status,
            scope_status=scope_summary["scope_status"],
            eligible_candidate_count=candidate["eligible_candidate_count"],
            selected_order=candidate["selected_candidate_order_name"],
            missing_requirements_plain=missing_requirements_plain,
            known_blockers=known_blockers,
        ),
        **_safety_summary(),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
    }
    return payload


def _scope_summary(sources: dict) -> dict:
    draft_data = _source_data(sources, "draft_only_preflight")
    resolver_data = _source_data(sources, "scope_compatibility_resolver")
    scope_status = _safe_text(
        draft_data.get("scope_status")
        or resolver_data.get("scope_resolver_status")
        or resolver_data.get("scope_compatibility_status")
        or SCOPE_MISSING,
        max_length=120,
    )
    if scope_status in {"missing", "present_but_unreadable", "present_but_not_object"}:
        scope_status = SCOPE_MISSING
    compose_scope_available = (
        draft_data.get("compose_scope_available") is True
        or resolver_data.get("compose_scope_available") is True
        or scope_status == SCOPE_COMPOSE_ONLY
    )
    send_scope_available = (
        draft_data.get("send_scope_available") is True
        or resolver_data.get("send_scope_available") is True
        or scope_status == SCOPE_SEND_AVAILABLE
    )
    broad_mail_scope_available = (
        draft_data.get("broad_mail_scope_available") is True
        or resolver_data.get("broad_mail_scope_available") is True
        or scope_status == SCOPE_BROAD_AVAILABLE
    )
    real_send_scope_available = (
        draft_data.get("real_send_scope_available") is True
        or resolver_data.get("real_send_scope_available") is True
        or send_scope_available
        or broad_mail_scope_available
    )
    draft_only_mode = (
        draft_data.get("draft_only_mode") is True
        or resolver_data.get("draft_only_mode") is True
        or (compose_scope_available and not real_send_scope_available)
    )
    draft_scope_available = (
        draft_data.get("draft_scope_available") is True
        or compose_scope_available
        or real_send_scope_available
    )
    if not draft_scope_available and scope_status not in {SCOPE_COMPOSE_ONLY, SCOPE_SEND_AVAILABLE, SCOPE_BROAD_AVAILABLE}:
        scope_status = SCOPE_MISSING
    return {
        "scope_status": scope_status,
        "compose_scope_available": compose_scope_available,
        "send_scope_available": send_scope_available,
        "broad_mail_scope_available": broad_mail_scope_available,
        "draft_only_mode": draft_only_mode,
        "real_send_scope_available": real_send_scope_available,
        "draft_scope_available": draft_scope_available,
    }


def _candidate_snapshot(sources: dict, simulator_fixture_enabled: bool) -> dict:
    if simulator_fixture_enabled:
        simulator_candidate = _candidate_from_first_source(
            sources,
            (
                "simulator_locked_gmail_send_gate",
                "simulator_gmail_send_executor_shell",
                "simulator_candidate_report",
            ),
        )
        if simulator_candidate["source_key"]:
            return simulator_candidate
    production_candidate = _candidate_from_first_source(
        sources,
        (
            "draft_only_preflight",
            "real_send_final_preflight",
            "auto_queue_refresh",
            "locked_gmail_send_gate",
            "locked_send_readiness_package",
        ),
    )
    if production_candidate["source_key"]:
        return production_candidate
    return _empty_candidate_snapshot()


def _candidate_from_first_source(sources: dict, source_keys: tuple[str, ...]) -> dict:
    for key in source_keys:
        report = sources.get(key) or {}
        data = report.get("data") if report.get("usable") else {}
        if not isinstance(data, dict) or "eligible_candidate_count" not in data:
            continue
        eligible_count = _int_or_zero(data.get("eligible_candidate_count"))
        selected_order = _selected_candidate_order_name(data, eligible_count)
        source_status = _safe_text(report.get("status"), max_length=120)
        return {
            "source_key": key,
            "source_status": source_status,
            "source_relative_path": _safe_text(report.get("relative_path"), max_length=160),
            "source_timestamp": _safe_text(report.get("timestamp"), max_length=120),
            "eligible_candidate_count": eligible_count,
            "selected_candidate_order_name": selected_order if eligible_count == 1 else "",
            "selected_candidate_safe": _selected_candidate_safe(data, selected_order, source_status),
            "selected_candidate_risks": _selected_candidate_risks(data, selected_order),
        }
    return _empty_candidate_snapshot()


def _empty_candidate_snapshot() -> dict:
    return {
        "source_key": "",
        "source_status": "missing",
        "source_relative_path": "",
        "source_timestamp": "",
        "eligible_candidate_count": 0,
        "selected_candidate_order_name": "",
        "selected_candidate_safe": False,
        "selected_candidate_risks": [],
    }


def _selected_candidate_order_name(data: dict, eligible_count: int) -> str:
    if eligible_count != 1:
        return ""
    for key in ("selected_candidate_order_name", "selected_order_name", "next_candidate_order_name"):
        selected_order = _safe_text(data.get(key), max_length=80)
        if selected_order:
            return selected_order
    for list_key in ("eligible_candidates_summary", "ready_candidate_queue", "draft_candidates"):
        rows = data.get(list_key)
        if isinstance(rows, list) and rows:
            first = rows[0] if isinstance(rows[0], dict) else {}
            selected_order = _safe_text(first.get("order_name") or first.get("name"), max_length=80)
            if selected_order:
                return selected_order
    selected_candidate = data.get("selected_candidate")
    if isinstance(selected_candidate, dict):
        return _safe_text(selected_candidate.get("order_name"), max_length=80)
    fake_summary = data.get("fake_candidate_summary")
    if isinstance(fake_summary, dict):
        return _safe_text(fake_summary.get("selected_order_name"), max_length=80)
    return ""


def _selected_candidate_safe(data: dict, selected_order: str, source_status: str) -> bool:
    if not selected_order:
        return False
    for key in (
        "selected_candidate_safe_to_prepare_send",
        "selected_candidate_allowed_for_future_send",
        "selected_candidate_safe_for_future_ack",
        "selected_candidate_safe_for_future_draft",
        "duplicate_suppression_passed",
        "draft_create_allowed_next_phase",
        "real_send_execute_allowed_next_phase",
    ):
        if data.get(key) is True:
            return True
    if source_status in READY_SOURCE_STATUSES:
        return True
    return not _selected_candidate_risks(data, selected_order)


def _selected_candidate_risks(data: dict, selected_order: str) -> list[str]:
    if not selected_order:
        return []
    risks = []
    for key in ("blocked_candidates_summary", "blocked_orders_summary", "blocking_conditions"):
        for row in _dict_rows(data.get(key)):
            if _safe_text(row.get("order_name"), max_length=80) == selected_order:
                risks.extend(_string_list(row.get("blocking_reasons")))
                risks.extend(_string_list(row.get("reasons")))
                risks.append(_safe_text(row.get("reason"), max_length=120))
                risks.append(_safe_text(row.get("detail"), max_length=240))
    return _dedupe_text(risks)


def _draft_preflight_status(
    sources: dict,
    scope_summary: dict,
    candidate: dict,
    simulator_fixture_enabled: bool,
) -> str:
    draft_data = _source_data(sources, "draft_only_preflight")
    status = _safe_text(draft_data.get("draft_preflight_status"), max_length=120)
    if (
        simulator_fixture_enabled
        and candidate["source_key"].startswith("simulator_")
        and scope_summary["draft_scope_available"]
        and candidate["eligible_candidate_count"] == 1
        and candidate["selected_candidate_safe"]
    ):
        return READY_DRAFT_ONLY
    if status:
        return status
    if not scope_summary["draft_scope_available"] or scope_summary["scope_status"] == SCOPE_MISSING:
        return BLOCKED_SCOPE_MISSING
    if candidate["eligible_candidate_count"] == 0:
        return BLOCKED_NO_CANDIDATE
    if candidate["eligible_candidate_count"] > 1:
        return "blocked_multiple_candidates_require_manual_selection"
    return "blocked_candidate_safety_check_failed"


def _draft_preflight_allowed(sources: dict, draft_preflight_status: str) -> bool:
    draft_data = _source_data(sources, "draft_only_preflight")
    return (
        draft_data.get("draft_create_allowed_next_phase") is True
        or draft_preflight_status in {READY_DRAFT_ONLY, READY_SEND_SCOPE}
    )


def _source_safety_findings(sources: dict) -> list[str]:
    findings = []
    for report in sources.values():
        data = report.get("data") if isinstance(report, dict) else {}
        if not isinstance(data, dict):
            continue
        source_key = _safe_text(report.get("key"), max_length=80)
        findings.extend(_mapping_safety_findings(data, f"source_report:{source_key}"))
        for nested_key in ("safety_flags", "no_write_safety_flags", "raw_flags"):
            nested = data.get(nested_key)
            if isinstance(nested, dict):
                findings.extend(_mapping_safety_findings(nested, f"{nested_key}:{source_key}"))
    return _dedupe_text(findings)


def _mapping_safety_findings(mapping: dict, prefix: str) -> list[str]:
    return [
        f"{prefix}:{key}"
        for key in sorted(FORBIDDEN_SOURCE_TRUE_FLAGS)
        if mapping.get(key) is True
    ]


def _known_blockers_summary(sources: dict) -> list[dict]:
    source_data = [
        report.get("data")
        for report in sources.values()
        if isinstance(report, dict) and isinstance(report.get("data"), dict)
    ]
    return [
        _known_blocker(
            source_data,
            order_name="#22620",
            fallback_status="blocked_existing_trustpilot_invitation_customer_level",
            fallback_summary="Already received Trustpilot via #22621",
            fallback_reasons=["blocked_existing_trustpilot_invitation_customer_level"],
        ),
        _known_blocker(
            source_data,
            order_name="#22582",
            fallback_status="blocked_candidate_safety_check_failed",
            fallback_summary=(
                f"Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, related #22582/#22581 not ready"
            ),
            fallback_reasons=[
                "blocked_missing_delivered_tag",
                "blocked_missing_review_request_tag",
                "blocked_merged_order_group_not_ready",
            ],
        ),
    ]


def _known_blocker(
    source_data: list[dict],
    order_name: str,
    fallback_status: str,
    fallback_summary: str,
    fallback_reasons: list[str],
) -> dict:
    source = _known_blocker_source(source_data, order_name)
    if order_name == "#22620":
        prior_order = _safe_text(source.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
        summary = f"Already received Trustpilot via {prior_order}"
    else:
        summary = source.get("summary") or source.get("message") or fallback_summary
    return {
        "order_name": order_name,
        "status": _safe_text(source.get("status") or fallback_status, max_length=120),
        "summary": _safe_text(summary, max_length=300),
        "blocking_reasons": _dedupe_text(_string_list(source.get("blocking_reasons")) or fallback_reasons),
        "selected_candidate_safe_for_future_draft": False,
    }


def _known_blocker_source(data_sources: list[dict], order_name: str) -> dict:
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


def _missing_requirements_plain(
    draft_scope_available: bool,
    eligible_candidate_count: int,
    exactly_one_candidate: bool,
    selected_candidate_safe: bool,
    draft_create_requested: bool,
    draft_create_allowed_by_preflight: bool,
    source_safety_findings: list[str],
) -> list[str]:
    missing = []
    if not draft_scope_available:
        missing.append("Gmail permission is not configured.")
    if eligible_candidate_count == 0:
        missing.append("No eligible order is available.")
    if not exactly_one_candidate or not selected_candidate_safe:
        missing.append("The system needs exactly one safe order before creating a draft.")
    if not draft_create_requested:
        missing.append("Final approval is required before creating a draft.")
    if source_safety_findings:
        missing.append("A source report safety flag must be cleared before creating a draft.")
    if draft_scope_available and eligible_candidate_count == 1 and not draft_create_allowed_by_preflight:
        missing.append("The draft-only preflight must pass before creating a draft.")
    return _dedupe_text(missing)


def _locked_runner_status(requirements_ready: bool, draft_create_requested: bool) -> str:
    if not requirements_ready:
        return BLOCKED_MISSING_REQUIREMENTS
    if not draft_create_requested:
        return BLOCKED_MISSING_DRAFT_CREATE_APPROVAL
    return READY_BUT_DISABLED


def _blocking_conditions(
    missing_requirements_plain: list[str],
    source_safety_findings: list[str],
    known_blockers: list[dict],
) -> list[dict]:
    rows = [
        {
            "status": _requirement_status(requirement),
            "detail": requirement,
        }
        for requirement in missing_requirements_plain
    ]
    for finding in source_safety_findings:
        rows.append(
            {
                "status": "blocked_source_safety_flag",
                "detail": finding,
            }
        )
    for blocker in known_blockers:
        rows.append(
            {
                "status": _safe_text(blocker.get("status"), max_length=120),
                "order_name": _safe_text(blocker.get("order_name"), max_length=80),
                "detail": _safe_text(blocker.get("summary"), max_length=300),
            }
        )
    return rows


def _requirement_status(requirement: str) -> str:
    if requirement.startswith("Gmail permission"):
        return BLOCKED_SCOPE_MISSING
    if requirement.startswith("No eligible"):
        return BLOCKED_NO_CANDIDATE
    if requirement.startswith("The system needs exactly one"):
        return "blocked_exactly_one_safe_order_required"
    if requirement.startswith("Final approval"):
        return BLOCKED_MISSING_DRAFT_CREATE_APPROVAL
    if requirement.startswith("The draft-only preflight"):
        return "blocked_draft_only_preflight_not_ready"
    return "blocked_missing_requirement"


def _next_admin_action(locked_runner_status: str, scope_status: str, eligible_candidate_count: int) -> str:
    if locked_runner_status == READY_BUT_DISABLED:
        return (
            "All preconditions are ready, but this phase is locked. A later explicit phase must create only one draft."
        )
    if locked_runner_status == BLOCKED_MISSING_DRAFT_CREATE_APPROVAL:
        return (
            f"Set {REQUIRED_FUTURE_ENV_FLAG_NAME} to the exact approval value only in a later draft-create phase."
        )
    if scope_status == SCOPE_MISSING and eligible_candidate_count == 0:
        return CURRENT_BLOCKED_MESSAGE
    if scope_status == SCOPE_MISSING:
        return "Configure Gmail compose or send permission before any future draft creation phase."
    if eligible_candidate_count == 0:
        return "Wait for exactly one eligible delivered Trustpilot candidate, then rerun the draft preflight."
    return "Resolve the missing draft creation requirements, then rerun this locked shell."


def _dashboard_message(locked_runner_status: str, scope_status: str, eligible_candidate_count: int) -> str:
    if locked_runner_status == READY_BUT_DISABLED:
        return "Draft creation prerequisites are ready, but this phase still creates no draft."
    if locked_runner_status == BLOCKED_MISSING_DRAFT_CREATE_APPROVAL:
        return "Draft creation needs final local approval before the next phase can proceed."
    if scope_status == SCOPE_MISSING and eligible_candidate_count == 0:
        return CURRENT_BLOCKED_MESSAGE
    if scope_status == SCOPE_MISSING:
        return "Draft creation is not ready yet. Gmail permission is not configured."
    if eligible_candidate_count == 0:
        return "Draft creation is not ready yet. There is no eligible order."
    return "Draft creation is not ready yet. Resolve the listed missing requirements."


def _source_report_status(sources: dict) -> list[dict]:
    return [
        {
            "key": _safe_text(report.get("key"), max_length=80),
            "relative_path": _safe_text(report.get("relative_path"), max_length=160),
            "present": report.get("present") is True,
            "loaded": report.get("loaded") is True,
            "usable": report.get("usable") is True,
            "simulator_report": report.get("simulator_report") is True,
            "status": _safe_text(report.get("status"), max_length=120),
            "timestamp": _safe_text(report.get("timestamp"), max_length=120),
            "error_sanitized": _safe_text(report.get("error_sanitized"), max_length=300),
        }
        for report in sources.values()
    ]


def _no_write_safety_flags() -> dict:
    return {
        "locked_runner_shell_only": True,
        "source_reports_read_only": True,
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
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
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
        "all_new_actions_no_write_confirmed": True,
    }


def _empty_privacy_scan_summary() -> dict:
    return {
        "scan_performed": False,
        "passed": False,
        "raw_email_like_disallowed_count": 0,
        "allowed_placeholder_email_count": 0,
        "bearer_token_count": 0,
        "access_token_value_count": 0,
        "refresh_token_value_count": 0,
        "client_secret_value_count": 0,
        "private_key_pattern_count": 0,
        "full_gmail_id_pattern_count": 0,
        "sensitive_matches_reported": False,
    }


def _privacy_scan_for_payload(payload: dict) -> dict:
    safe_payload = _safe_payload(payload)
    json_text = json.dumps(safe_payload, ensure_ascii=False, indent=2)
    html_text = _render_html_report(safe_payload)
    content = f"{json_text}\n{html_text}"
    email_matches = EMAIL_RE.findall(content)
    disallowed_email_count = 0
    allowed_email_count = 0
    for email in email_matches:
        normalized = email.lower()
        domain = normalized.rsplit("@", 1)[-1]
        if normalized in ALLOWED_EMAILS or domain in ALLOWED_EMAIL_DOMAINS:
            allowed_email_count += 1
        else:
            disallowed_email_count += 1
    counts = {
        "raw_email_like_disallowed_count": disallowed_email_count,
        "allowed_placeholder_email_count": allowed_email_count,
        "bearer_token_count": len(BEARER_TOKEN_RE.findall(content)),
        "access_token_value_count": len(ACCESS_TOKEN_VALUE_RE.findall(content)),
        "refresh_token_value_count": len(REFRESH_TOKEN_VALUE_RE.findall(content)),
        "client_secret_value_count": len(CLIENT_SECRET_VALUE_RE.findall(content)),
        "private_key_pattern_count": len(PRIVATE_KEY_RE.findall(content)),
        "full_gmail_id_pattern_count": len(FULL_GMAIL_ID_RE.findall(content)),
    }
    passed = all(value == 0 for key, value in counts.items() if key != "allowed_placeholder_email_count")
    return {
        "scan_performed": True,
        "passed": passed,
        **counts,
        "sensitive_matches_reported": False,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(_safe_payload(payload), report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(_safe_payload(payload)), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status_class = "ok" if payload["locked_runner_status"] == READY_BUT_DISABLED else "warn"
    selected_candidate = payload.get("selected_candidate_order_name") or "-"
    missing_rows = "".join(f"<li>{escape(str(item))}</li>" for item in payload["missing_requirements_plain"])
    if not missing_rows:
        missing_rows = "<li>No missing requirements recorded.</li>"
    blocking_rows = "\n".join(_render_condition_row(row) for row in payload["blocking_conditions"])
    source_rows = "\n".join(_render_source_row(row) for row in payload["source_report_status"])
    privacy_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["privacy_scan_summary"].items()
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["no_write_safety_flags"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail One-Draft Create Locked Runner</title>
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
  <h1>Trustpilot Gmail One-Draft Create Locked Runner</h1>
  <p class="status {status_class}">Locked runner status: <strong>{escape(payload["locked_runner_status"])}</strong></p>
  <p>{escape(payload["dashboard_message"])}</p>
  <p>Mode: <code>{escape(payload["mode"])}</code>. This task is a locked shell only. It does not call Gmail, create a draft, send email, write Shopify tags, or call Trustpilot/Kudosi/Ali Reviews APIs.</p>
  <h2>What is still missing before draft creation</h2>
  <ul>{missing_rows}</ul>
  <table>
    <tbody>
      <tr><th>Can create draft now</th><td>No</td></tr>
      <tr><th>Draft preflight status</th><td><code>{escape(payload["draft_preflight_status"])}</code></td></tr>
      <tr><th>Scope status</th><td><code>{escape(payload["scope_status"])}</code></td></tr>
      <tr><th>Draft scope available</th><td>{payload["draft_scope_available"]}</td></tr>
      <tr><th>Real-send scope available</th><td>{payload["real_send_scope_available"]}</td></tr>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(selected_candidate)}</td></tr>
      <tr><th>Exactly one candidate</th><td>{payload["exactly_one_candidate"]}</td></tr>
      <tr><th>Draft create requested</th><td>{payload["draft_create_requested"]}</td></tr>
      <tr><th>Draft create allowed by preflight</th><td>{payload["draft_create_allowed_by_preflight"]}</td></tr>
      <tr><th>Draft create allowed by env</th><td>{payload["draft_create_allowed_by_env"]}</td></tr>
      <tr><th>Draft create performed</th><td>false</td></tr>
      <tr><th>Required future env flag</th><td><code>{escape(payload["required_future_env_flag_name"])}</code></td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
    </tbody>
  </table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Order</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>No-Write Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <details>
    <summary>Advanced technical details</summary>
    <p>JSON report: <code>logs/{escape(REPORT_JSON_PATH.name)}</code></p>
    <p>HTML report: <code>logs/{escape(REPORT_HTML_PATH.name)}</code></p>
    <p>Candidate source: <code>{escape(payload["source_candidate_summary"]["source_key"] or "missing")}</code></p>
    <h2>Source Reports</h2>
    <table><thead><tr><th>Key</th><th>Path</th><th>Present</th><th>Loaded</th><th>Usable</th><th>Status</th></tr></thead><tbody>{source_rows}</tbody></table>
    <h2>Privacy Scan</h2>
    <table><tbody>{privacy_rows}</tbody></table>
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


def _render_source_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(row.get('key', ''))}</td>"
        f"<td><code>{escape(row.get('relative_path', ''))}</code></td>"
        f"<td>{escape(str(row.get('present') is True))}</td>"
        f"<td>{escape(str(row.get('loaded') is True))}</td>"
        f"<td>{escape(str(row.get('usable') is True))}</td>"
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
        "json_trustpilot_gmail_one_draft_create_locked_runner_path": str(json_path),
        "html_trustpilot_gmail_one_draft_create_locked_runner_path": str(html_path),
        "locked_runner_status": payload["locked_runner_status"],
        "draft_preflight_status": payload["draft_preflight_status"],
        "scope_status": payload["scope_status"],
        "draft_scope_available": payload["draft_scope_available"],
        "real_send_scope_available": payload["real_send_scope_available"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "exactly_one_candidate": payload["exactly_one_candidate"],
        "draft_create_requested": payload["draft_create_requested"],
        "draft_create_allowed_by_preflight": payload["draft_create_allowed_by_preflight"],
        "draft_create_allowed_by_env": payload["draft_create_allowed_by_env"],
        "draft_create_performed": False,
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "required_future_env_flag_name": payload["required_future_env_flag_name"],
        "missing_requirements_plain": payload["missing_requirements_plain"],
        "blocking_conditions": payload["blocking_conditions"],
        "privacy_scan_summary": payload["privacy_scan_summary"],
        "next_admin_action": payload["next_admin_action"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    selected = payload["selected_candidate_order_name"] or "None"
    missing = "\n".join(f"- {item}" for item in payload["missing_requirements_plain"]) or "- None"
    return (
        "Shopify review request Phase 5.19B Trustpilot Gmail one-draft create locked runner finished.\n"
        f"Locked runner status: {payload['locked_runner_status']}\n"
        f"Draft preflight status: {payload['draft_preflight_status']}\n"
        f"Scope status: {payload['scope_status']}\n"
        f"Draft scope available: {payload['draft_scope_available']}\n"
        f"Real-send scope available: {payload['real_send_scope_available']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Selected candidate: {selected}\n"
        f"Draft create requested: {payload['draft_create_requested']}\n"
        f"Draft create allowed by preflight: {payload['draft_create_allowed_by_preflight']}\n"
        f"Draft create allowed by env: {payload['draft_create_allowed_by_env']}\n"
        "Draft create performed: False\n"
        f"Missing requirements:\n{missing}\n"
        f"Required future env flag: {payload['required_future_env_flag_name']}\n"
        "Safety: no Gmail network/API call, no draft create/update/delete, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no token or credential files read.\n"
        f"Privacy scan passed: {payload['privacy_scan_summary'].get('passed')}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(
    locked_runner_status: str,
    scope_status: str,
    eligible_candidate_count: int,
    selected_order: str,
    missing_requirements_plain: list[str],
    known_blockers: list[dict],
) -> str:
    if locked_runner_status == READY_BUT_DISABLED:
        return f"One-draft creation prerequisites are ready for {selected_order}; this locked phase still created no draft."
    if locked_runner_status == BLOCKED_MISSING_DRAFT_CREATE_APPROVAL:
        return "One-draft creation prerequisites are ready, but the future draft-create approval flag is missing."
    order_22620 = _safe_text((known_blockers[0] if known_blockers else {}).get("summary"), max_length=160)
    order_22582 = _safe_text((known_blockers[1] if len(known_blockers) > 1 else {}).get("summary"), max_length=200)
    if scope_status == SCOPE_MISSING and eligible_candidate_count == 0:
        return (
            "Draft creation is blocked because Gmail permission is not configured and no eligible candidate exists. "
            f"#22620 remains blocked: {order_22620}. #22582 remains blocked: {order_22582}."
        )
    return f"Draft creation locked runner is blocked: {'; '.join(missing_requirements_plain)}"


def _source_data(sources: dict, key: str) -> dict:
    report = sources.get(key) or {}
    data = report.get("data") if report.get("usable") else {}
    return data if isinstance(data, dict) else {}


def _source_report_status_value(report: dict) -> str:
    data = report.get("data") if report.get("usable") else {}
    return _report_status(data) if isinstance(data, dict) and data else _safe_text(report.get("status"), max_length=120)


def _report_status(data: dict) -> str:
    return _first_text(
        data,
        (
            "locked_runner_status",
            "draft_preflight_status",
            "scope_resolver_status",
            "scope_compatibility_status",
            "readiness_audit_status",
            "execution_status",
            "preflight_status",
            "gate_status",
            "refresh_status",
            "package_status",
            "simulator_status",
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


def _is_simulator_report(data: dict) -> bool:
    return (
        data.get("simulator_reports_used") is True
        or data.get("simulator_used") is True
        or data.get("simulator_fixture_enabled") is True
        or data.get("simulator_only") is True
        or data.get("source") == "trustpilot_candidate_simulator"
        or bool(data.get("fake_candidate_summary"))
    )


def _simulator_fixture_enabled() -> bool:
    return os.environ.get(SIMULATOR_FIXTURE_ENV_NAME, "").strip() == SIMULATOR_FIXTURE_ENV_VALUE


def _draft_create_requested() -> bool:
    return os.environ.get(REQUIRED_FUTURE_ENV_FLAG_NAME, "").strip() == REQUIRED_FUTURE_ENV_FLAG_VALUE
