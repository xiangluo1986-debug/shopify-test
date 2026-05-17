import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_HISTORY_LIMIT = 50
HISTORY_LIMIT_OPTIONS = (25, 50, 100)
MAX_REPORT_BYTES = 4_000_000
MAX_EVENTS = 700

HISTORY_REPORT_DEFINITIONS = (
    {
        "key": "candidate_scan",
        "label": "Candidate scan",
        "filename": "shopify_review_request_candidate_scan.json",
        "channel": "trustpilot",
        "event_type": "candidate_scan",
        "status_keys": ("report_status", "status"),
    },
    {
        "key": "next_candidate_scan",
        "label": "Next repeat customer candidate scan",
        "filename": "shopify_review_request_next_repeat_customer_candidate_scan.json",
        "channel": "trustpilot",
        "event_type": "candidate_scan",
        "status_keys": ("next_repeat_customer_candidate_scan_status", "report_status", "status"),
    },
    {
        "key": "last_60_days_candidate_scan",
        "label": "Last 60 days candidate scan",
        "filename": "shopify_review_request_last_60_days_candidate_scan.json",
        "channel": "trustpilot",
        "event_type": "candidate_scan",
        "status_keys": ("report_status", "status"),
    },
    {
        "key": "shopify_order_sync_coverage",
        "label": "Shopify order sync coverage",
        "filename": "shopify_review_request_shopify_order_sync_coverage.json",
        "channel": "trustpilot",
        "event_type": "coverage_check",
        "status_keys": ("report_status", "coverage_status", "status"),
    },
    {
        "key": "tag_alias_and_candidate_correction_audit",
        "label": "Review-request tag alias and #22562 correction audit",
        "filename": "shopify_review_request_tag_alias_and_candidate_correction_audit.json",
        "channel": "trustpilot",
        "event_type": "candidate_scan",
        "status_keys": ("report_status", "status"),
    },
    {
        "key": "order_tags_persistence_audit",
        "label": "Shopify order tags persistence audit",
        "filename": "shopify_review_request_order_tags_persistence_audit.json",
        "channel": "trustpilot",
        "event_type": "coverage_check",
        "status_keys": ("report_status", "status"),
    },
    {
        "key": "customer_history_trustpilot_guard_audit",
        "label": "Customer history Trustpilot guard audit",
        "filename": "shopify_review_request_customer_history_trustpilot_guard_audit.json",
        "channel": "trustpilot",
        "event_type": "duplicate_block",
        "status_keys": ("report_status", "status"),
    },
    {
        "key": "customer_history_precision_audit",
        "label": "Customer history precision audit",
        "filename": "shopify_review_request_customer_history_precision_audit.json",
        "channel": "trustpilot",
        "event_type": "duplicate_block",
        "status_keys": ("report_status", "status"),
    },
    {
        "key": "customer_level_duplicate_audit",
        "label": "Customer-level Trustpilot duplicate audit",
        "filename": "shopify_review_request_customer_level_trustpilot_duplicate_audit.json",
        "channel": "trustpilot",
        "event_type": "duplicate_block",
        "status_keys": ("customer_level_duplicate_audit_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_one_candidate_gmail_draft_package",
        "label": "Trustpilot one-candidate Gmail draft package",
        "filename": "shopify_review_request_trustpilot_one_candidate_gmail_draft_package.json",
        "channel": "trustpilot",
        "event_type": "draft_package",
        "status_keys": ("one_candidate_gmail_draft_package_status", "draft_package_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_automation_dry_run",
        "label": "Trustpilot automation dry-run",
        "filename": "shopify_review_request_trustpilot_automation_dry_run.json",
        "channel": "trustpilot",
        "event_type": "automation_dry_run",
        "status_keys": ("automation_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_locked_send_readiness_package",
        "label": "Trustpilot locked send readiness package",
        "filename": "shopify_review_request_trustpilot_locked_send_readiness_package.json",
        "channel": "trustpilot",
        "event_type": "readiness_package",
        "status_keys": ("package_status", "automation_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_auto_queue_refresh",
        "label": "Trustpilot auto queue refresh",
        "filename": "shopify_review_request_trustpilot_auto_queue_refresh.json",
        "channel": "trustpilot",
        "event_type": "automation_refresh",
        "status_keys": ("refresh_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_locked_gmail_send_gate",
        "label": "Trustpilot locked Gmail send gate",
        "filename": "shopify_review_request_trustpilot_locked_gmail_send_gate.json",
        "channel": "trustpilot",
        "event_type": "send_gate",
        "status_keys": ("gate_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_gmail_send_executor_shell",
        "label": "Trustpilot Gmail send executor shell",
        "filename": "shopify_review_request_trustpilot_gmail_send_executor_shell.json",
        "channel": "trustpilot",
        "event_type": "send_executor_shell",
        "status_keys": ("executor_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_real_send_final_preflight",
        "label": "Trustpilot real send final preflight",
        "filename": "shopify_review_request_trustpilot_real_send_final_preflight.json",
        "channel": "trustpilot",
        "event_type": "final_preflight",
        "status_keys": ("preflight_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_real_send_execute",
        "label": "Trustpilot real send execute skeleton",
        "filename": "shopify_review_request_trustpilot_real_send_execute.json",
        "channel": "trustpilot",
        "event_type": "real_send_execute",
        "status_keys": ("execution_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_gmail_real_send_readiness_audit",
        "label": "Trustpilot Gmail real-send readiness audit",
        "filename": "shopify_review_request_trustpilot_gmail_real_send_readiness_audit.json",
        "channel": "trustpilot",
        "event_type": "real_send_readiness_audit",
        "status_keys": ("readiness_audit_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_gmail_oauth_config_helper",
        "label": "Trustpilot Gmail OAuth/config helper",
        "filename": "shopify_review_request_trustpilot_gmail_oauth_config_helper.json",
        "channel": "trustpilot",
        "event_type": "gmail_oauth_config_helper",
        "status_keys": ("config_helper_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_gmail_config_compatibility_audit",
        "label": "Trustpilot Gmail config compatibility audit",
        "filename": "shopify_review_request_trustpilot_gmail_config_compatibility_audit.json",
        "channel": "trustpilot",
        "event_type": "gmail_config_compatibility_audit",
        "status_keys": ("compatibility_audit_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_gmail_scope_compatibility_resolver",
        "label": "Trustpilot Gmail scope compatibility resolver",
        "filename": "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json",
        "channel": "trustpilot",
        "event_type": "gmail_scope_compatibility_resolver",
        "status_keys": ("scope_resolver_status", "scope_compatibility_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_gmail_draft_only_preflight",
        "label": "Trustpilot Gmail draft-only preflight",
        "filename": "shopify_review_request_trustpilot_gmail_draft_only_preflight.json",
        "channel": "trustpilot",
        "event_type": "draft_only_preflight",
        "status_keys": ("draft_preflight_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_gmail_one_draft_create_locked_runner",
        "label": "Trustpilot Gmail one-draft create locked runner",
        "filename": "shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.json",
        "channel": "trustpilot",
        "event_type": "draft_create_locked_runner",
        "status_keys": ("locked_runner_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_one_candidate_gmail_draft_create_locked_runner",
        "label": "Trustpilot one-candidate Gmail draft create locked runner",
        "filename": "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner.json",
        "channel": "trustpilot",
        "event_type": "draft_create_preflight",
        "status_keys": ("one_candidate_gmail_draft_create_locked_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_one_candidate_gmail_draft_create_execute",
        "label": "Trustpilot one-candidate Gmail draft create execute",
        "filename": "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute.json",
        "channel": "trustpilot",
        "event_type": "draft_created",
        "status_keys": ("one_candidate_gmail_draft_create_execute_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_one_candidate_gmail_draft_send_preflight",
        "label": "Trustpilot one-candidate Gmail draft send preflight",
        "filename": "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight.json",
        "channel": "trustpilot",
        "event_type": "send_preflight",
        "status_keys": ("one_candidate_gmail_draft_send_preflight_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_one_candidate_gmail_draft_send_execute",
        "label": "Trustpilot one-candidate Gmail draft send execute",
        "filename": "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute.json",
        "channel": "trustpilot",
        "event_type": "send_execute",
        "status_keys": ("one_candidate_gmail_draft_send_execute_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_review_and_send_execute",
        "label": "Trustpilot Review & Send execute",
        "filename": "shopify_review_request_trustpilot_review_and_send_execute.json",
        "channel": "trustpilot",
        "event_type": "send_execute",
        "status_keys": ("execution_status", "report_status", "status"),
    },
    {
        "key": "review_send_failure_audit",
        "label": "Review & Send failure audit",
        "filename": "shopify_review_request_review_send_failure_audit.json",
        "channel": "trustpilot",
        "event_type": "send_execute",
        "status_keys": ("review_send_failure_audit_status", "report_status", "status"),
    },
    {
        "key": "dynamic_review_send_audit",
        "label": "Dynamic Review & Send audit",
        "filename": "shopify_review_request_dynamic_review_send_audit.json",
        "channel": "trustpilot",
        "event_type": "send_execute",
        "status_keys": ("dynamic_review_send_audit_status", "report_status", "status"),
    },
    {
        "key": "review_send_post_send_audit",
        "label": "Review & Send post-send audit",
        "filename": "codex_runs/shopify_review_request_review_send_post_send_audit.json",
        "channel": "trustpilot",
        "event_type": "send_execute",
        "status_keys": ("audit_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_post_send_tag_write",
        "label": "Trustpilot post-send Shopify tag write",
        "filename": "codex_runs/shopify_review_request_trustpilot_post_send_tag_write.json",
        "channel": "trustpilot",
        "event_type": "tag_write_audit",
        "status_keys": ("tag_write_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_tag_write_design_dry_run",
        "label": "Trustpilot Shopify tag write design dry-run",
        "filename": "shopify_review_request_trustpilot_tag_write_design_dry_run.json",
        "channel": "trustpilot",
        "event_type": "tag_write_preflight",
        "status_keys": ("tag_write_design_status", "report_status", "status"),
    },
    {
        "key": "trustpilot_tag_write_audit",
        "label": "Trustpilot Shopify tag write audit",
        "filename": "shopify_review_request_trustpilot_tag_write_audit.json",
        "channel": "trustpilot",
        "event_type": "tag_write_audit",
        "status_keys": ("tag_write_audit_status", "report_status", "status"),
    },
    {
        "key": "ali_reviews_api_capability_discovery",
        "label": "Ali Reviews API capability discovery",
        "filename": "shopify_review_request_ali_reviews_api_capability_discovery.json",
        "channel": "ali_reviews",
        "event_type": "api_capability_discovery",
        "status_keys": ("ali_reviews_api_capability_discovery_status", "automation_decision_status", "report_status", "status"),
    },
)

CHANNEL_OPTIONS = (
    ("all", "All channels"),
    ("trustpilot", "Trustpilot"),
    ("ali_reviews", "Ali Reviews"),
    ("system", "System"),
)

EVENT_TYPE_OPTIONS = (
    ("all", "All event types"),
    ("candidate_scan", "Candidate scan"),
    ("candidate_selected", "Candidate selected"),
    ("candidate_blocked", "Candidate blocked"),
    ("duplicate_block", "Duplicate block"),
    ("automation_dry_run", "Automation dry-run"),
    ("automation_refresh", "Automation refresh"),
    ("readiness_package", "Readiness package"),
    ("send_gate", "Send gate"),
    ("send_executor_shell", "Send executor shell"),
    ("final_preflight", "Final preflight"),
    ("real_send_execute", "Real send execute"),
    ("real_send_readiness_audit", "Real send readiness audit"),
    ("gmail_oauth_config_helper", "Gmail OAuth/config helper"),
    ("gmail_config_compatibility_audit", "Gmail config compatibility audit"),
    ("gmail_scope_compatibility_resolver", "Gmail scope compatibility resolver"),
    ("draft_only_preflight", "Draft-only preflight"),
    ("draft_create_locked_runner", "Draft create locked runner"),
    ("draft_package", "Draft package"),
    ("draft_create_preflight", "Draft create preflight"),
    ("draft_created", "Draft created"),
    ("send_preflight", "Send preflight"),
    ("send_execute", "Send execute"),
    ("tag_write_preflight", "Tag write preflight"),
    ("tag_write_audit", "Tag write audit"),
    ("api_capability_discovery", "API capability discovery"),
)

FALSE_REQUIRED_SAFETY_FLAGS = (
    "gmail_draft_created",
    "gmail_draft_create_attempted",
    "gmail_draft_create_performed",
    "gmail_drafts_send_called",
    "gmail_messages_send_called",
    "gmail_send_performed",
    "email_sent",
    "shopify_write_performed",
    "shopify_tag_write_performed",
    "mutation_performed",
    "tags_add_performed",
    "tags_remove_performed",
    "external_review_api_call_performed",
    "trustpilot_api_call_performed",
    "kudosi_api_call_performed",
    "ali_reviews_api_call_performed",
    "ali_reviews_write_api_call_performed",
    "tracking_redirect_enabled",
    "tracking_token_generated",
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"shpat_[A-Za-z0-9_]+|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"x-shopify-access-token\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"access[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"refresh[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"client[_\s-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"api[_\s-]?key\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"password\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}"
    r")"
)
PARTIAL_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}\.\.\.[A-Za-z0-9_-]{1,16}$")


def build_review_request_history_ledger(log_dir, params=None):
    filters = normalize_history_filters(params)
    source_reports = load_history_source_reports(log_dir)
    events = _dedupe_events(
        event
        for report in source_reports
        for event in _events_from_report(report)
    )
    events = events[:MAX_EVENTS]
    filtered_events = _filter_events(events, filters)
    visible_events = filtered_events[: filters["ledger_limit"]]
    summary = _summary(events, filtered_events, source_reports)
    focus = _focus_status(events, source_reports)
    return {
        "filters": filters,
        "filter_summary": {
            "visible_history_rows": len(visible_events),
            "matched_history_rows": len(filtered_events),
            "total_history_rows": len(events),
            "missing_source_count": sum(1 for report in source_reports if not report["present"]),
            "unavailable_source_count": sum(
                1 for report in source_reports if report["present"] and not report["loaded"]
            ),
            "limit": filters["ledger_limit"],
        },
        "events": visible_events,
        "all_events": events,
        "source_reports": source_reports,
        "summary": summary,
        "focus": focus,
        "channel_filter_options": _selected_options(CHANNEL_OPTIONS, filters["channel"]),
        "event_type_filter_options": _selected_options(EVENT_TYPE_OPTIONS, filters["event_type"]),
        "limit_filter_options": _selected_limit_options(filters["ledger_limit"]),
        "recommendations": _recommendations(source_reports),
    }


def normalize_history_filters(params=None):
    params = params or {}
    q = _safe_text(_param_get(params, "q"), max_length=80)
    channel = _param_get(params, "channel") or _param_get(params, "history_channel") or "all"
    event_type = _param_get(params, "event_type") or _param_get(params, "history_event_type") or "all"
    status = _param_get(params, "ledger_status") or _param_get(params, "history_status") or ""
    order = _param_get(params, "order") or _param_get(params, "history_order") or ""
    try:
        ledger_limit = int(
            _param_get(params, "ledger_limit")
            or _param_get(params, "history_limit")
            or DEFAULT_HISTORY_LIMIT
        )
    except (TypeError, ValueError):
        ledger_limit = DEFAULT_HISTORY_LIMIT

    if channel not in {value for value, _label in CHANNEL_OPTIONS}:
        channel = "all"
    if event_type not in {value for value, _label in EVENT_TYPE_OPTIONS}:
        event_type = "all"
    if ledger_limit not in HISTORY_LIMIT_OPTIONS:
        ledger_limit = DEFAULT_HISTORY_LIMIT
    return {
        "q": q,
        "channel": channel,
        "event_type": event_type,
        "ledger_status": _safe_text(status, max_length=80),
        "order": _safe_text(order, max_length=80),
        "ledger_limit": ledger_limit,
        "has_active_history_filters": bool(
            q
            or channel != "all"
            or event_type != "all"
            or status
            or order
            or ledger_limit != DEFAULT_HISTORY_LIMIT
        ),
    }


def load_history_source_reports(log_dir):
    log_path = Path(log_dir)
    return [_load_report(log_path, definition) for definition in HISTORY_REPORT_DEFINITIONS]


def _load_report(log_dir, definition):
    path = log_dir / definition["filename"]
    report = {
        **definition,
        "relative_path": f"logs/{definition['filename']}",
        "present": False,
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "modified_at": "",
        "size_bytes": 0,
        "error": "",
        "data": {},
    }
    if not path.exists():
        return report

    report["present"] = True
    try:
        stat = path.stat()
        report["size_bytes"] = stat.st_size
        report["modified_at"] = datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S")
        if stat.st_size > MAX_REPORT_BYTES:
            report["status"] = "present_but_too_large_for_history_ledger"
            report["error"] = "report_too_large"
            return report
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error"] = _safe_text(str(exc), max_length=300)
        return report

    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error"] = "top_level_json_is_not_object"
        return report

    report["loaded"] = True
    report["data"] = data
    report["status"] = _first_text(data, definition["status_keys"]) or _first_status_value(data) or "loaded"
    report["timestamp"] = _first_text(data, ("timestamp", "generated_at", "created_at", "started_at", "finished_at"))
    return report


def _events_from_report(report):
    if not report.get("loaded"):
        return []

    data = report["data"]
    key = report["key"]
    event_type = report["event_type"]
    events = [_event_from_mapping(report, data, event_type, "report_summary")]

    if key in {"candidate_scan", "next_candidate_scan", "last_60_days_candidate_scan"}:
        events.extend(_candidate_scan_events(report))
    elif key == "customer_level_duplicate_audit":
        events.extend(_duplicate_audit_events(report))
    elif key == "trustpilot_locked_send_readiness_package":
        events.extend(_readiness_package_events(report))
    elif key == "trustpilot_auto_queue_refresh":
        events.extend(_auto_refresh_events(report))
    elif key in {
        "trustpilot_locked_gmail_send_gate",
        "trustpilot_gmail_send_executor_shell",
        "trustpilot_real_send_final_preflight",
        "trustpilot_real_send_execute",
        "trustpilot_gmail_real_send_readiness_audit",
        "trustpilot_gmail_scope_compatibility_resolver",
        "trustpilot_gmail_draft_only_preflight",
        "trustpilot_gmail_one_draft_create_locked_runner",
    }:
        events.extend(_gate_executor_events(report))

    return [event for event in events if event]


def _candidate_scan_events(report):
    data = report["data"]
    events = []
    selected_order = _first_text(data, ("selected_order_name", "next_candidate_order_name"))
    if selected_order:
        selected_event = _event_from_mapping(report, data, "candidate_selected", "selected_candidate_summary")
        if selected_event:
            selected_event["order_name"] = selected_order
            selected_event["status"] = selected_event["status"] or "candidate_selected"
            events.append(selected_event)

    selected_candidate = data.get("selected_candidate")
    if isinstance(selected_candidate, dict):
        event = _event_from_mapping(report, selected_candidate, "candidate_selected", "selected_candidate")
        if event:
            event["next_candidate_order_name"] = selected_order or event["next_candidate_order_name"]
            events.append(event)

    for list_key, section in (
        ("evaluated_orders", "evaluated_orders"),
        ("blocked_orders", "blocked_orders"),
        ("needs_manual_review", "needs_manual_review"),
    ):
        value = data.get(list_key)
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            if _is_blocked_mapping(item):
                row_type = "duplicate_block" if _looks_like_duplicate_block(item) else "candidate_blocked"
                event = _event_from_mapping(report, item, row_type, section)
                if event:
                    events.append(event)

    for list_key, section in (
        ("ready_candidate_queue", "ready_candidate_queue"),
        ("repeat_customer_candidates", "repeat_customer_candidates"),
        ("review_queue_candidates", "review_queue_candidates"),
    ):
        value = data.get(list_key)
        if not isinstance(value, list):
            continue
        for item in value[:50]:
            if isinstance(item, dict):
                event = _event_from_mapping(report, item, "candidate_scan", section)
                if event:
                    events.append(event)
    return events


def _duplicate_audit_events(report):
    data = report["data"]
    events = []
    for item in data.get("prior_trustpilot_invitation_matches") or []:
        if isinstance(item, dict):
            event = _event_from_mapping(report, item, "duplicate_block", "prior_trustpilot_invitation_match")
            if event:
                event["blocker_reason"] = (
                    event["blocker_reason"]
                    or _safe_text(data.get("classification"))
                    or "prior_trustpilot_invitation_detected"
                )
                events.append(event)
    return events


def _readiness_package_events(report):
    data = report["data"]
    events = []
    for item in data.get("blocked_candidates_summary") or []:
        if isinstance(item, dict):
            event = _event_from_mapping(report, item, "candidate_blocked", "blocked_candidates_summary")
            if event:
                events.append(event)
    for item in data.get("eligible_candidates_summary") or []:
        if isinstance(item, dict):
            event = _event_from_mapping(report, item, "candidate_selected", "eligible_candidates_summary")
            if event:
                event["status"] = event["status"] or "eligible_for_locked_send_readiness"
                events.append(event)
    return events


def _auto_refresh_events(report):
    data = report["data"]
    events = []
    for item in data.get("known_blockers_summary") or []:
        if isinstance(item, dict):
            event = _event_from_mapping(report, item, "candidate_blocked", "known_blockers_summary")
            if event:
                events.append(event)
    return events


def _gate_executor_events(report):
    data = report["data"]
    events = []
    for item in data.get("known_blockers_summary") or []:
        if isinstance(item, dict):
            event = _event_from_mapping(report, item, "candidate_blocked", "known_blockers_summary")
            if event:
                events.append(event)
    for item in data.get("blocking_conditions") or []:
        if isinstance(item, dict):
            event = _event_from_mapping(report, item, report["event_type"], "blocking_conditions")
            if event:
                events.append(event)
    return events


def _event_from_mapping(report, item, event_type, source_section):
    if not isinstance(item, dict):
        return None
    data = report["data"]
    order_name = _first_text(
        item,
        (
            "order_name",
            "name",
            "selected_order",
            "selected_candidate_order_name",
            "selected_order_name",
            "next_candidate_order_name",
            "audit_order_a",
        ),
    )
    if not order_name and source_section == "report_summary":
        order_name = _first_text(
            data,
            (
                "selected_order",
                "selected_candidate_order_name",
                "selected_order_name",
                "next_candidate_order_name",
                "audit_order_a",
            ),
        )
    masked_email = _first_text(
        item,
        (
            "masked_email",
            "selected_masked_email",
            "next_candidate_masked_email",
            "customer_email",
            "email",
        ),
    )
    if not masked_email and source_section == "report_summary":
        masked_email = _first_text(data, ("selected_masked_email", "next_candidate_masked_email"))

    status = _first_text(
        item,
        (
            "candidate_status",
            "package_status",
            "reason",
            "classification",
            "decision",
            "source_decision",
            "suggested_next_manual_action",
            "status",
        ),
    )
    if not status:
        status = report.get("status", "")
    classification = _first_text(
        item,
        ("classification", "customer_level_duplicate_classification", "candidate_classification"),
    ) or _first_text(data, ("classification", "customer_level_duplicate_classification"))
    blocker_reason = _blocker_reason(item) or _blocker_reason(data)
    partial_draft_id = _safe_partial_id(
        _first_text(
            item,
            ("gmail_draft_id_partial", "source_gmail_draft_id_partial", "partial_draft_id", "gmail_draft_id"),
        )
        or _first_text(data, ("gmail_draft_id_partial", "source_gmail_draft_id_partial", "partial_draft_id", "gmail_draft_id"))
    )
    partial_message_id = _safe_partial_id(
        _first_text(
            item,
            ("gmail_message_id_partial", "message_id_partial", "partial_message_id", "gmail_message_id"),
        )
        or _first_text(data, ("gmail_message_id_partial", "message_id_partial", "partial_message_id", "gmail_message_id"))
    )
    event_time = _first_text(item, ("timestamp", "created_at", "processed_at", "event_time")) or report.get("timestamp")
    event = {
        "event_time": _safe_text(event_time),
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "source_report_path": report["relative_path"],
        "source_report_label": report["label"],
        "source_section": source_section,
        "task_name": _first_text(data, ("task_name", "task")) or report["key"],
        "phase": _first_text(data, ("phase",)),
        "channel": report["channel"],
        "event_type": event_type,
        "order_name": _safe_text(order_name, max_length=80),
        "masked_email": mask_email(masked_email),
        "status": _safe_text(status),
        "classification": _safe_text(classification),
        "blocker_reason": _safe_text(blocker_reason),
        "success": _bool_or_none(item.get("success") if "success" in item else data.get("success")),
        "email_sent": _source_bool(
            item,
            data,
            ("email_sent", "email_sent_confirmed", "gmail_send_performed"),
        ),
        "gmail_draft_created": _source_bool(
            item,
            data,
            (
                "gmail_draft_created",
                "gmail_drafts_create_confirmed",
                "draft_created_confirmed",
                "real_gmail_draft_create_executed",
            ),
        ),
        "shopify_tag_written": _source_bool(
            item,
            data,
            (
                "shopify_tag_written",
                "shopify_tag_write_confirmed",
                "shopify_write_performed",
                "shopify_tag_write_performed",
                "source_shopify_write_performed",
                "tags_add_performed",
                "source_tags_add_performed",
                "tagsAdd_performed",
            ),
        ),
        "partial_draft_id": partial_draft_id,
        "partial_message_id": partial_message_id,
        "next_candidate_order_name": _safe_text(
            _first_text(data, ("next_candidate_order_name", "selected_order_name")),
            max_length=80,
        ),
        "draft_should_not_be_sent": (
            item.get("existing_unsent_gmail_draft_should_not_be_sent") is True
            or data.get("existing_unsent_gmail_draft_should_not_be_sent") is True
        ),
        "prior_trustpilot_order_name": _safe_text(
            _first_text(item, ("prior_trustpilot_order_name",))
            or _first_text(data, ("prior_trustpilot_order_name",)),
            max_length=80,
        ),
        "delivered_tag_present": _source_bool(item, data, ("delivered_tag_present",)),
        "canonical_review_request_tag_present": _source_bool(
            item,
            data,
            ("canonical_review_request_tag_present",),
        ),
        "eligible_for_trustpilot": _source_bool(item, data, ("eligible_for_trustpilot",)),
        "merged_or_related_order_guard_status": _safe_text(
            _first_text(item, ("merged_or_related_order_guard_status",))
            or _first_text(data, ("merged_or_related_order_guard_status",)),
            max_length=80,
        ),
    }
    if not any(
        (
            event["order_name"],
            event["masked_email"],
            event["status"],
            event["classification"],
            event["blocker_reason"],
            event["partial_draft_id"],
            event["partial_message_id"],
            event["next_candidate_order_name"],
        )
    ):
        return None
    event["badge_class"] = _badge_class(event)
    return event


def _filter_events(events, filters):
    result = []
    query = filters["q"].lower()
    order_query = filters["order"].lower()
    status_query = filters["ledger_status"].lower()
    for event in events:
        if filters["channel"] != "all" and event["channel"] != filters["channel"]:
            continue
        if filters["event_type"] != "all" and event["event_type"] != filters["event_type"]:
            continue
        haystack = _event_search_text(event)
        if query and query not in haystack:
            continue
        if order_query and order_query not in _safe_text(event.get("order_name")).lower():
            continue
        if status_query and status_query not in " ".join(
            (
                _safe_text(event.get("status")).lower(),
                _safe_text(event.get("classification")).lower(),
                _safe_text(event.get("blocker_reason")).lower(),
            )
        ):
            continue
        result.append(event)
    return result


def _summary(events, filtered_events, source_reports):
    return {
        "total_event_count": len(events),
        "filtered_event_count": len(filtered_events),
        "source_report_count": len(source_reports),
        "loaded_source_report_count": sum(1 for report in source_reports if report["loaded"]),
        "missing_source_report_count": sum(1 for report in source_reports if not report["present"]),
        "unavailable_source_report_count": sum(1 for report in source_reports if report["present"] and not report["loaded"]),
        "by_event_type": _counter_rows(Counter(event["event_type"] for event in events)),
        "by_status": _counter_rows(Counter(event["status"] or "missing_status" for event in events)),
        "by_channel": _counter_rows(Counter(event["channel"] for event in events)),
    }


def _focus_status(events, source_reports):
    order_22620_events = [event for event in events if event.get("order_name") == "#22620"]
    order_22582_events = [event for event in events if event.get("order_name") == "#22582"]
    order_22620_block_events = [
        event
        for event in order_22620_events
        if "blocked_existing_trustpilot_invitation_customer_level" in _event_search_text(event)
    ]
    order_22620_evidence_paths = _dedupe_text(event["source_report_path"] for event in order_22620_events)
    order_22620_email_sent_values = [
        event["email_sent"] for event in order_22620_events if event["email_sent"] is not None
    ]
    order_22620_draft_values = [
        event["gmail_draft_created"] for event in order_22620_events if event["gmail_draft_created"] is not None
    ]
    next_candidate_event = _first_event(
        event for event in events if event["event_type"] == "candidate_selected" and event["next_candidate_order_name"]
    )
    next_candidate = (next_candidate_event or {}).get("next_candidate_order_name", "")
    ali_report = _source_by_key(source_reports, "ali_reviews_api_capability_discovery")
    ali_status = _safe_text((ali_report.get("data") or {}).get("ali_reviews_api_capability_discovery_status", ""))
    if not ali_status:
        ali_status = _safe_text(ali_report.get("status", "missing"))
    blocked_classification = _first_text(
        order_22620_block_events[0] if order_22620_block_events else {},
        ("classification", "status", "blocker_reason"),
    )
    prior_trustpilot_order = _first_text(
        next(
            (event for event in order_22620_events if event.get("prior_trustpilot_order_name")),
            {},
        ),
        ("prior_trustpilot_order_name",),
    )
    draft_should_not_send = any(event.get("draft_should_not_be_sent") for event in order_22620_events)
    order_22582_block_event = _first_event(
        event
        for event in order_22582_events
        if str(event.get("classification", "")).startswith("blocked")
        or str(event.get("status", "")).startswith("blocked")
        or str(event.get("blocker_reason", "")).startswith("blocked")
    ) or _first_event(
        event
        for event in order_22582_events
        if event.get("classification") or event.get("status") or event.get("blocker_reason")
    )
    return {
        "order_22620": {
            "order_name": "#22620",
            "evidence_available": bool(order_22620_events),
            "blocked_confirmed": bool(order_22620_block_events),
            "blocked_classification": blocked_classification or "unavailable",
            "email_sent": any(value is True for value in order_22620_email_sent_values),
            "email_sent_confirmed_false": bool(order_22620_email_sent_values)
            and not any(value is True for value in order_22620_email_sent_values),
            "source_gmail_draft_created_detected": any(value is True for value in order_22620_draft_values),
            "existing_unsent_gmail_draft_should_not_be_sent": draft_should_not_send,
            "prior_trustpilot_order_name": prior_trustpilot_order or "unavailable",
            "evidence_report_paths": order_22620_evidence_paths,
        },
        "next_candidate": {
            "order_name": next_candidate or "unavailable",
            "evidence_report_path": (next_candidate_event or {}).get("source_report_path", ""),
            "status": (next_candidate_event or {}).get("status", "unavailable"),
        },
        "order_22582": {
            "order_name": "#22582",
            "evidence_available": bool(order_22582_events),
            "blocked_classification": _first_text(
                order_22582_block_event or {},
                ("classification", "status", "blocker_reason"),
            )
            or "unavailable",
            "delivered_tag_present": any(event.get("delivered_tag_present") is True for event in order_22582_events),
            "canonical_review_request_tag_present": any(
                event.get("canonical_review_request_tag_present") is True for event in order_22582_events
            ),
            "eligible_for_trustpilot": any(event.get("eligible_for_trustpilot") is True for event in order_22582_events),
            "merged_or_related_order_guard_status": _first_text(
                next((event for event in order_22582_events if event.get("merged_or_related_order_guard_status")), {}),
                ("merged_or_related_order_guard_status",),
            )
            or "unavailable",
            "evidence_report_paths": _dedupe_text(event["source_report_path"] for event in order_22582_events),
        },
        "ali_reviews_api": {
            "status": ali_status or "unavailable",
            "vendor_docs_missing": ali_status == "blocked_missing_vendor_api_documentation",
            "evidence_report_path": ali_report.get("relative_path", ""),
            "present": bool(ali_report.get("present")),
            "loaded": bool(ali_report.get("loaded")),
        },
    }


def _recommendations(source_reports):
    missing = [report["relative_path"] for report in source_reports if not report["present"]]
    unavailable = [report["relative_path"] for report in source_reports if report["present"] and not report["loaded"]]
    recommendations = []
    if missing or unavailable:
        recommendations.append(
            "Some local reports are missing or unavailable; the ledger shows only reconstructable events."
        )
    recommendations.append(
        "Future improvement: add an append-only DB event model after the read-only report-ledger phase is reviewed."
    )
    recommendations.append(
        "Future improvement: add a report importer that records normalized events without storing raw emails or full Gmail IDs."
    )
    return recommendations


def privacy_scan_text(text):
    raw_emails = []
    for match in EMAIL_RE.finditer(text or ""):
        value = match.group(0).lower()
        if "***" in value or value == "info@kidstoylover.com":
            continue
        raw_emails.append(mask_email(value))
    return {
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "token_secret_bearer_pattern_count": 1 if SECRET_VALUE_RE.search(text or "") else 0,
        "full_gmail_draft_or_message_id_field_count": _full_gmail_id_field_count(text or ""),
    }


def mask_email(email):
    value = str(email or "").strip()
    if not value or "@" not in value:
        return ""
    if "***" in value:
        return _safe_text(value, max_length=120)
    local, domain = value.rsplit("@", 1)
    if not local or not domain:
        return ""
    domain_parts = domain.split(".")
    domain_mask = f"{domain_parts[0][:1]}***.{domain_parts[-1]}" if len(domain_parts) >= 2 and domain_parts[0] else "***"
    return f"{local[:1]}***@{domain_mask}"


def _full_gmail_id_field_count(text):
    count = 0
    try:
        data = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return len(re.findall(r'"gmail_(?:draft|message)_id"\s*:\s*"[^"]+"', text or ""))
    for key, value in _walk_items(data):
        lowered = str(key).lower()
        if lowered in {"gmail_draft_id", "gmail_message_id"} and _safe_text(value):
            count += 1
    return count


def _walk_items(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key, nested
            yield from _walk_items(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_items(nested)


def _source_bool(item, data, keys):
    for mapping in (item, data):
        if not isinstance(mapping, dict):
            continue
        for key in keys:
            if key in mapping:
                return mapping.get(key) is True
    return None


def _bool_or_none(value):
    if isinstance(value, bool):
        return value
    return None


def _blocker_reason(item):
    for key in ("blocker_reason", "blocking_reason", "blocked_reason", "decision_reason"):
        value = _safe_text(item.get(key, ""))
        if value:
            return value
    reasons = []
    for key in ("blocking_reasons", "classification_reasons", "blocking_conditions"):
        value = item.get(key)
        if isinstance(value, str):
            reasons.append(value)
        elif isinstance(value, list):
            for entry in value:
                if isinstance(entry, dict):
                    reasons.append(_first_text(entry, ("status", "detail", "reason")))
                else:
                    reasons.append(_safe_text(entry))
    reasons = _dedupe_text(reasons)
    if reasons:
        return ", ".join(reasons[:5])
    classification = _safe_text(item.get("classification", ""))
    return classification if classification.startswith("blocked") else ""


def _is_blocked_mapping(item):
    text = " ".join(
        _safe_text(item.get(key, ""))
        for key in ("candidate_status", "classification", "decision", "status", "suggested_next_manual_action")
    ).lower()
    return (
        "blocked" in text
        or bool(item.get("blocking_reasons"))
        or bool(item.get("blocking_conditions"))
        or item.get("customer_level_duplicate_block_applies") is True
    )


def _looks_like_duplicate_block(item):
    text = json.dumps(_safe_json_fragment(item), ensure_ascii=True, sort_keys=True).lower()
    return any(
        needle in text
        for needle in (
            "duplicate",
            "existing_trustpilot",
            "trustpilot_invitation",
            "customer_level",
            "same_customer",
            "same_email",
            "prior_trustpilot",
        )
    )


def _safe_json_fragment(value):
    if isinstance(value, dict):
        return {str(key): _safe_json_fragment(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_safe_json_fragment(nested) for nested in value]
    return _safe_text(value)


def _badge_class(event):
    text = _event_search_text(event)
    if "blocked" in text or event.get("success") is False:
        return "rrw-badge-bad"
    if event.get("email_sent") or event.get("gmail_draft_created") or event.get("shopify_tag_written"):
        return "rrw-badge-ok"
    if "missing" in text or "unavailable" in text:
        return "rrw-badge-warn"
    return "rrw-badge-info"


def _event_search_text(event):
    return " ".join(
        _safe_text(event.get(key, "")).lower()
        for key in (
            "source_report_path",
            "source_report_label",
            "source_section",
            "task_name",
            "phase",
            "channel",
            "event_type",
            "order_name",
            "masked_email",
            "status",
            "classification",
            "blocker_reason",
            "next_candidate_order_name",
            "prior_trustpilot_order_name",
        )
    )


def _counter_rows(counter):
    return [{"key": _safe_text(key), "count": count} for key, count in counter.most_common()]


def _source_by_key(source_reports, key):
    for report in source_reports:
        if report.get("key") == key:
            return report
    return {}


def _first_event(events):
    for event in events:
        return event
    return {}


def _first_status_value(data):
    for key, value in data.items():
        if key.endswith("_status") and value not in (None, ""):
            return _safe_text(value)
    return ""


def _first_text(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _safe_text(value)
    return ""


def _safe_partial_id(value):
    text = _safe_text(value, max_length=200)
    if not text:
        return ""
    if PARTIAL_ID_RE.fullmatch(text):
        return text
    if len(text) <= 10:
        return "[present]"
    return f"{text[:4]}...{text[-4:]}"


def _safe_text(value, max_length=300):
    text = str(value or "")
    text = CONTROL_CHARS_RE.sub("", text)
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
    text = text.strip()
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def _dedupe_text(values):
    seen = set()
    result = []
    for value in values:
        text = _safe_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _dedupe_events(events):
    seen = set()
    result = []
    for event in events:
        if not event:
            continue
        key = (
            event.get("source_report_path", ""),
            event.get("source_section", ""),
            event.get("event_type", ""),
            event.get("order_name", ""),
            event.get("status", ""),
            event.get("classification", ""),
            event.get("partial_draft_id", ""),
            event.get("partial_message_id", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def _param_get(params, key):
    getter = getattr(params, "get", None)
    if getter:
        return getter(key, "")
    return ""


def _selected_options(options, selected_value):
    return [
        {"value": value, "label": label, "selected": value == selected_value}
        for value, label in options
    ]


def _selected_limit_options(selected_limit):
    return [
        {"value": value, "label": str(value), "selected": value == selected_limit}
        for value in HISTORY_LIMIT_OPTIONS
    ]
