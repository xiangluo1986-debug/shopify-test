import json
import re
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from .review_request_history_ledger import build_review_request_history_ledger
from .models import ShopifyOrder


CANONICAL_REVIEW_REQUEST_TAG = "1: review request"
TYPO_REVIEW_REQUEST_TAG = "1: reveiw request"
DELIVERED_TAG = "Delivered"
TRUSTPILOT_TAG_ALIASES = (
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
)
FUTURE_TRACKING_STATUSES = (
    "invitation_draft_prepared",
    "invitation_sent",
    "shopify_tag_written",
    "clicked",
    "review_detected",
    "blocked_existing_trustpilot_invitation_tag",
    "blocked_existing_trustpilot_invitation_customer_level",
    "blocked_missing_delivered_tag",
    "blocked_missing_review_request_tag",
    "blocked_merged_order_group_not_ready",
    "blocked_returned_package",
    "blocked_first_order_customer",
    "blocked_risk_or_ticket",
)
STATUS_FILTER_OPTIONS = (
    ("all", "All"),
    ("queue", "Queue"),
    ("trustpilot_sent", "Trustpilot sent"),
    ("blocked", "Blocked"),
    ("report_ready", "Report ready"),
)
TAG_FILTER_OPTIONS = (
    ("all", "All tags"),
    ("review_request", "Review request tag"),
    ("trustpilot_alias", "Trustpilot alias"),
    ("returned_package", "Returned package"),
)
LIMIT_OPTIONS = (25, 50, 100)
DEFAULT_LIMIT = 25
BLOCKED_REASON_DEFINITIONS = (
    (
        "missing_delivered_tag",
        "Missing delivered tag",
        ("blocked_missing_delivered_tag", "missing delivered", "delivered tag is missing"),
    ),
    (
        "missing_review_request_tag",
        "Missing canonical review-request tag",
        ("blocked_missing_review_request_tag", "canonical review", "review request tag is missing"),
    ),
    (
        "merged_order_group_not_ready",
        "Merged/related group not ready",
        ("blocked_merged_order_group_not_ready", "merged", "related order group"),
    ),
    (
        "returned_package",
        "Returned package",
        ("returned package", "returned_package", "return package", "returned"),
    ),
    (
        "duplicate_trustpilot_invitation",
        "Duplicate Trustpilot invitation",
        ("duplicate trustpilot", "existing_trustpilot", "trustpilot invitation"),
    ),
    (
        "customer_level_duplicate_trustpilot",
        "Customer-level duplicate Trustpilot",
        ("customer_level", "same_customer", "same_email", "prior_trustpilot"),
    ),
    ("first_order", "First order", ("first order", "first_order")),
    (
        "risk_ticket_refund_cancel_dispute",
        "Risk / ticket / refund / cancel / dispute",
        ("risk", "ticket", "refund", "cancel", "cancelled", "dispute", "chargeback"),
    ),
)
ADMIN_STATUS_LABELS = {
    "blocked_existing_trustpilot_invitation_tag": "Already sent to this order",
    "blocked_existing_trustpilot_invitation_customer_level": "Already sent to this customer",
    "blocked_missing_delivered_tag": "Not delivered yet",
    "blocked_missing_review_request_tag": "Missing review request tag",
    "blocked_merged_order_group_not_ready": "Related orders are not ready",
    "blocked_no_eligible_candidate": "No order ready to send",
    "blocked_missing_gmail_oauth_config": "Gmail setup is missing",
    "blocked_missing_ack": "Waiting for final approval",
    "blocked_multiple_candidates_require_manual_selection": "More than one order needs review",
    "blocked_candidate_safety_check_failed": "Safety check failed",
    "blocked_missing_vendor_api_documentation": "Waiting for API docs",
    "no_eligible_delivered_review_request_candidate": "No orders ready",
}

REPORT_DEFINITIONS = (
    (
        "next_candidate_scan",
        "Next repeat customer candidate scan",
        "shopify_review_request_next_repeat_customer_candidate_scan.json",
        (
            "next_repeat_customer_candidate_scan_status",
            "report_status",
            "status",
        ),
    ),
    (
        "candidate_scan",
        "Candidate scan",
        "shopify_review_request_candidate_scan.json",
        ("report_status", "status"),
    ),
    (
        "customer_level_duplicate_audit",
        "Customer-level Trustpilot duplicate audit",
        "shopify_review_request_customer_level_trustpilot_duplicate_audit.json",
        ("customer_level_duplicate_audit_status", "report_status", "status"),
    ),
    (
        "manual_action_package",
        "Manual action package",
        "shopify_review_request_manual_action_package.json",
        ("manual_action_package_status", "report_status", "status"),
    ),
    (
        "unified_decision_engine",
        "Unified decision engine dry-run",
        "shopify_review_request_unified_decision_engine_dry_run.json",
        ("decision_engine_status", "report_status", "status"),
    ),
    (
        "trustpilot_automation_dry_run",
        "Trustpilot automation dry-run",
        "shopify_review_request_trustpilot_automation_dry_run.json",
        ("automation_status", "report_status", "status"),
    ),
    (
        "trustpilot_locked_send_readiness_package",
        "Trustpilot locked send readiness package",
        "shopify_review_request_trustpilot_locked_send_readiness_package.json",
        ("package_status", "automation_status", "report_status", "status"),
    ),
    (
        "trustpilot_auto_queue_refresh",
        "Trustpilot auto queue refresh",
        "shopify_review_request_trustpilot_auto_queue_refresh.json",
        ("refresh_status", "report_status", "status"),
    ),
    (
        "trustpilot_candidate_simulator",
        "Trustpilot candidate simulator",
        "shopify_review_request_trustpilot_candidate_simulator.json",
        ("simulator_status", "report_status", "status"),
    ),
    (
        "trustpilot_locked_gmail_send_gate",
        "Trustpilot locked Gmail send gate",
        "shopify_review_request_trustpilot_locked_gmail_send_gate.json",
        ("gate_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_send_executor_shell",
        "Trustpilot Gmail send executor shell",
        "shopify_review_request_trustpilot_gmail_send_executor_shell.json",
        ("executor_status", "report_status", "status"),
    ),
    (
        "trustpilot_real_send_final_preflight",
        "Trustpilot real send final preflight",
        "shopify_review_request_trustpilot_real_send_final_preflight.json",
        ("preflight_status", "report_status", "status"),
    ),
    (
        "trustpilot_real_send_execute",
        "Trustpilot real send execute skeleton",
        "shopify_review_request_trustpilot_real_send_execute.json",
        ("execution_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_real_send_readiness_audit",
        "Trustpilot Gmail real-send readiness audit",
        "shopify_review_request_trustpilot_gmail_real_send_readiness_audit.json",
        ("readiness_audit_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_oauth_config_helper",
        "Trustpilot Gmail OAuth/config helper",
        "shopify_review_request_trustpilot_gmail_oauth_config_helper.json",
        ("config_helper_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_config_compatibility_audit",
        "Trustpilot Gmail config compatibility audit",
        "shopify_review_request_trustpilot_gmail_config_compatibility_audit.json",
        ("compatibility_audit_status", "report_status", "status"),
    ),
    (
        "returned_package_guard",
        "Returned package guard",
        "shopify_review_request_returned_package_guard.json",
        ("returned_package_guard_status", "report_status", "status"),
    ),
    (
        "trustpilot_one_candidate_draft_package",
        "Trustpilot one-candidate draft package",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_package.json",
        ("one_candidate_gmail_draft_package_status", "draft_package_status", "report_status", "status"),
    ),
    (
        "trustpilot_one_candidate_draft_create_locked_runner",
        "Trustpilot one-candidate draft create locked runner",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_locked_runner.json",
        ("one_candidate_gmail_draft_create_locked_status", "report_status", "status"),
    ),
    (
        "trustpilot_one_candidate_draft_create_execute",
        "Trustpilot one-candidate draft create execute",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_create_execute.json",
        ("one_candidate_gmail_draft_create_execute_status", "report_status", "status"),
    ),
    (
        "trustpilot_one_candidate_draft_send_preflight",
        "Trustpilot one-candidate draft send preflight",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_preflight.json",
        ("one_candidate_gmail_draft_send_preflight_status", "report_status", "status"),
    ),
    (
        "trustpilot_one_candidate_draft_send_execute",
        "Trustpilot one-candidate draft send execute",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute.json",
        ("one_candidate_gmail_draft_send_execute_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_draft_package",
        "Trustpilot Gmail draft package",
        "shopify_review_request_trustpilot_gmail_draft_package.json",
        ("draft_package_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_draft_locked_test",
        "Trustpilot Gmail draft create locked test",
        "shopify_review_request_trustpilot_gmail_draft_create_locked_test.json",
        ("draft_create_locked_test_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_first_draft_audit",
        "Trustpilot Gmail first draft audit",
        "shopify_review_request_trustpilot_gmail_first_draft_audit.json",
        ("first_draft_audit_status", "report_status", "status"),
    ),
    (
        "trustpilot_completion_next_batch_design",
        "Trustpilot completion next batch design",
        "shopify_review_request_trustpilot_completion_next_batch_design.json",
        ("completion_next_batch_design_status", "report_status", "status"),
    ),
    (
        "trustpilot_suppress_ali_reviews_design",
        "Trustpilot suppress Ali Reviews design",
        "shopify_review_request_trustpilot_suppress_ali_reviews_design.json",
        ("trustpilot_suppress_ali_reviews_design_status", "report_status", "status"),
    ),
    (
        "trustpilot_tag_write_design",
        "Trustpilot tag write design dry-run",
        "shopify_review_request_trustpilot_tag_write_design_dry_run.json",
        ("tag_write_design_status", "report_status", "status"),
    ),
    (
        "trustpilot_tag_write_audit",
        "Trustpilot tag write audit",
        "shopify_review_request_trustpilot_tag_write_audit.json",
        ("tag_write_audit_status", "report_status", "status"),
    ),
    (
        "trustpilot_send_audit",
        "Trustpilot invitation audit",
        "shopify_review_request_trustpilot_gmail_send_audit.json",
        ("send_audit_status", "report_status", "status"),
    ),
    (
        "ali_reviews_api_capability_discovery",
        "Ali Reviews API capability discovery",
        "shopify_review_request_ali_reviews_api_capability_discovery.json",
        ("ali_reviews_api_capability_discovery_status", "report_status", "status"),
    ),
)

SAFETY_FLAGS = (
    "shopify_write_performed",
    "mutation_performed",
    "tags_add_performed",
    "tags_remove_performed",
    "gmail_api_call_performed",
    "gmail_draft_create_attempted",
    "gmail_draft_created",
    "gmail_drafts_send_called",
    "gmail_messages_send_called",
    "gmail_send_performed",
    "gmail_draft_create_performed",
    "email_sent",
    "kudosi_api_call_performed",
    "ali_reviews_api_call_performed",
    "ali_reviews_write_api_call_performed",
    "trustpilot_api_call_performed",
    "shopify_tag_write_performed",
    "external_review_api_call_performed",
    "tracking_redirect_enabled",
    "tracking_token_generated",
)
TRUSTPILOT_EMAIL_EVENT_TYPES = {
    "candidate_selected",
    "candidate_blocked",
    "duplicate_block",
    "readiness_package",
    "send_gate",
    "send_executor_shell",
    "final_preflight",
    "draft_package",
    "draft_create_preflight",
    "draft_created",
    "send_preflight",
    "send_execute",
}

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
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
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

MAX_REPORT_BYTES = 4_000_000
MAX_SOURCE_ROWS = 500
MAX_TABLE_ROWS = DEFAULT_LIMIT
TRUSTPILOT_AUTO_REFRESH_REPORT_FILENAME = "shopify_review_request_trustpilot_auto_queue_refresh.json"
TRUSTPILOT_AUTO_REFRESH_HTML_FILENAME = "shopify_review_request_trustpilot_auto_queue_refresh.html"


def build_review_request_workbench_context(params=None):
    filters = _normalize_filters(params)
    reports = _load_known_reports()
    history_ledger = build_review_request_history_ledger(_log_dir(), params)
    all_rows = _dedupe_rows(_collect_report_rows(reports))
    latest_scan = _latest_scan_summary(reports.get("next_candidate_scan", {}))
    candidate_queue = _candidate_queue(reports)
    invitation_history = _rows_with_trustpilot_tags(all_rows)
    review_request_queue = _rows_with_canonical_review_request_tag(all_rows)
    typo_review_request_rows = _rows_with_typo_review_request_tag(all_rows)
    blocked_orders = _blocked_rows(reports, all_rows)
    local_order_links = _local_order_link_map(
        _dedupe_rows(
            all_rows
            + candidate_queue
            + invitation_history
            + review_request_queue
            + typo_review_request_rows
            + blocked_orders
        ),
        latest_scan,
    )
    for rows in (
        all_rows,
        candidate_queue,
        invitation_history,
        review_request_queue,
        typo_review_request_rows,
        blocked_orders,
    ):
        _attach_local_order_links(rows, local_order_links)
        _attach_status_badges(rows, latest_scan)
    _attach_latest_scan_local_order_link(latest_scan, local_order_links)

    visible_candidate_queue = _filter_rows(candidate_queue, filters, "queue")
    visible_invitation_history = _filter_rows(
        invitation_history,
        filters,
        "trustpilot_sent",
    )
    visible_review_request_queue = _filter_rows(review_request_queue, filters, "queue")
    visible_typo_review_request_rows = _filter_rows(
        typo_review_request_rows,
        filters,
        "queue",
    )
    visible_blocked_orders = _filter_rows(blocked_orders, filters, "blocked")
    report_readiness = _filter_report_readiness(_report_readiness(reports), filters)
    report_history = _report_history(reports)
    safety_history = _safety_history(reports)
    local_stats = _local_order_stats()
    blocked_reason_counts = _blocked_reason_counts(blocked_orders)
    module_overview = _module_overview(
        latest_scan=latest_scan,
        candidate_queue=candidate_queue,
        blocked_orders=blocked_orders,
        history_ledger=history_ledger,
    )
    candidate_queue_status = _candidate_queue_status(
        latest_scan=latest_scan,
        candidate_queue=candidate_queue,
        history_focus=history_ledger["focus"],
    )
    trustpilot_automation_status = _trustpilot_automation_status(
        reports.get("trustpilot_automation_dry_run", {}),
        candidate_queue_status,
    )
    trustpilot_send_readiness = _trustpilot_send_readiness_status(
        reports.get("trustpilot_locked_send_readiness_package", {}),
        trustpilot_automation_status,
    )
    trustpilot_auto_refresh = _trustpilot_auto_refresh_status(
        reports.get("trustpilot_auto_queue_refresh", {}),
        trustpilot_send_readiness,
    )
    trustpilot_candidate_simulator = _trustpilot_candidate_simulator_status(
        reports.get("trustpilot_candidate_simulator", {}),
    )
    trustpilot_gmail_send_gate = _trustpilot_gmail_send_gate_status(
        reports.get("trustpilot_locked_gmail_send_gate", {}),
        trustpilot_auto_refresh,
    )
    trustpilot_gmail_send_executor_shell = _trustpilot_gmail_send_executor_shell_status(
        reports.get("trustpilot_gmail_send_executor_shell", {}),
        trustpilot_gmail_send_gate,
    )
    trustpilot_real_send_final_preflight = _trustpilot_real_send_final_preflight_status(
        reports.get("trustpilot_real_send_final_preflight", {}),
        trustpilot_gmail_send_executor_shell,
    )
    trustpilot_real_send_execute = _trustpilot_real_send_execute_status(
        reports.get("trustpilot_real_send_execute", {}),
        trustpilot_real_send_final_preflight,
    )
    trustpilot_gmail_real_send_readiness_audit = _trustpilot_gmail_real_send_readiness_audit_status(
        reports.get("trustpilot_gmail_real_send_readiness_audit", {}),
        trustpilot_auto_refresh,
        trustpilot_real_send_final_preflight,
        trustpilot_real_send_execute,
    )
    trustpilot_gmail_oauth_config_helper = _trustpilot_gmail_oauth_config_helper_status(
        reports.get("trustpilot_gmail_oauth_config_helper", {}),
        trustpilot_gmail_real_send_readiness_audit,
    )
    trustpilot_gmail_config_compatibility_audit = _trustpilot_gmail_config_compatibility_audit_status(
        reports.get("trustpilot_gmail_config_compatibility_audit", {}),
    )
    trustpilot_email_records = _trustpilot_email_records(
        history_ledger["all_events"],
        history_ledger["filters"],
    )
    ali_reviews_status = _ali_reviews_status(history_ledger["focus"])
    operating_dashboard = _operating_dashboard(
        latest_scan=latest_scan,
        candidate_queue=candidate_queue,
        invitation_history=invitation_history,
        blocked_orders=blocked_orders,
        history_ledger=history_ledger,
        trustpilot_email_records=trustpilot_email_records,
        ali_reviews_status=ali_reviews_status,
        trustpilot_automation_status=trustpilot_automation_status,
        trustpilot_send_readiness=trustpilot_send_readiness,
        trustpilot_auto_refresh=trustpilot_auto_refresh,
        trustpilot_candidate_simulator=trustpilot_candidate_simulator,
        trustpilot_gmail_send_gate=trustpilot_gmail_send_gate,
        trustpilot_gmail_send_executor_shell=trustpilot_gmail_send_executor_shell,
        trustpilot_real_send_final_preflight=trustpilot_real_send_final_preflight,
        trustpilot_real_send_execute=trustpilot_real_send_execute,
        trustpilot_gmail_real_send_readiness_audit=trustpilot_gmail_real_send_readiness_audit,
        trustpilot_gmail_oauth_config_helper=trustpilot_gmail_oauth_config_helper,
        trustpilot_gmail_config_compatibility_audit=trustpilot_gmail_config_compatibility_audit,
    )

    return {
        "review_request_workbench": {
            "operating_dashboard": operating_dashboard,
            "module_overview": module_overview,
            "summary": _summary(
                latest_scan=latest_scan,
                candidate_queue=candidate_queue,
                invitation_history=invitation_history,
                review_request_queue=review_request_queue,
                blocked_orders=blocked_orders,
                reports=reports,
                local_stats=local_stats,
                blocked_reason_counts=blocked_reason_counts,
            ),
            "filters": filters,
            "filter_summary": _filter_summary(
                filters,
                visible_candidate_queue,
                visible_invitation_history,
                visible_review_request_queue,
                visible_typo_review_request_rows,
                visible_blocked_orders,
                report_readiness,
                history_ledger["events"],
            ),
            "latest_scan": latest_scan,
            "candidate_queue": visible_candidate_queue,
            "invitation_history": visible_invitation_history,
            "review_request_queue": visible_review_request_queue,
            "typo_review_request_rows": visible_typo_review_request_rows,
            "blocked_orders": visible_blocked_orders,
            "blocked_reason_counts": blocked_reason_counts,
            "report_readiness": report_readiness,
            "report_history": report_history,
            "history_ledger": history_ledger["events"],
            "history_filters": history_ledger["filters"],
            "history_summary": history_ledger["summary"],
            "history_focus": history_ledger["focus"],
            "history_source_reports": history_ledger["source_reports"],
            "history_filter_summary": history_ledger["filter_summary"],
            "history_channel_filter_options": history_ledger["channel_filter_options"],
            "history_event_type_filter_options": history_ledger["event_type_filter_options"],
            "history_limit_filter_options": history_ledger["limit_filter_options"],
            "history_recommendations": history_ledger["recommendations"],
            "safety_history": safety_history,
            "local_stats": local_stats,
            "tracking_design": _tracking_design(),
            "candidate_queue_status": candidate_queue_status,
            "trustpilot_automation_status": trustpilot_automation_status,
            "trustpilot_send_readiness": trustpilot_send_readiness,
            "trustpilot_auto_refresh": trustpilot_auto_refresh,
            "trustpilot_candidate_simulator": trustpilot_candidate_simulator,
            "trustpilot_gmail_send_gate": trustpilot_gmail_send_gate,
            "trustpilot_gmail_send_executor_shell": trustpilot_gmail_send_executor_shell,
            "trustpilot_real_send_final_preflight": trustpilot_real_send_final_preflight,
            "trustpilot_real_send_execute": trustpilot_real_send_execute,
            "trustpilot_gmail_real_send_readiness_audit": trustpilot_gmail_real_send_readiness_audit,
            "trustpilot_gmail_oauth_config_helper": trustpilot_gmail_oauth_config_helper,
            "trustpilot_gmail_config_compatibility_audit": trustpilot_gmail_config_compatibility_audit,
            "trustpilot_email_records": trustpilot_email_records,
            "ali_reviews_status": ali_reviews_status,
            "trustpilot_aliases": TRUSTPILOT_TAG_ALIASES,
            "canonical_review_request_tag": CANONICAL_REVIEW_REQUEST_TAG,
            "typo_review_request_tag": TYPO_REVIEW_REQUEST_TAG,
            "delivered_tag": DELIVERED_TAG,
            "status_filter_options": _selected_options(
                STATUS_FILTER_OPTIONS,
                filters["status"],
            ),
            "tag_filter_options": _selected_options(TAG_FILTER_OPTIONS, filters["tag"]),
            "limit_filter_options": _selected_limit_options(filters["limit"]),
            "safety_confirmations": _current_page_safety_confirmations(),
        }
    }


def mask_email(email):
    value = str(email or "").strip()
    if not value or "@" not in value:
        return ""
    if "*" in value:
        return _sanitize_text(value, max_length=120)
    local, domain = value.rsplit("@", 1)
    if not local or not domain:
        return ""
    local_mask = f"{local[:1]}***"
    domain_parts = domain.split(".")
    if len(domain_parts) >= 2 and domain_parts[0]:
        domain_mask = f"{domain_parts[0][:1]}***.{domain_parts[-1]}"
    else:
        domain_mask = "***"
    return f"{local_mask}@{domain_mask}"


def _project_root():
    return Path(settings.BASE_DIR).resolve().parent


def _log_dir():
    return _project_root() / "logs"


def _load_known_reports():
    reports = {}
    for key, label, filename, status_keys in REPORT_DEFINITIONS:
        reports[key] = _load_json_report(key, label, filename, status_keys)
    return reports


def _load_json_report(key, label, filename, status_keys):
    path = _log_dir() / filename
    report = {
        "key": key,
        "label": label,
        "filename": filename,
        "relative_path": f"logs/{filename}",
        "present": False,
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "modified_at": "",
        "success": None,
        "error": "",
        "data": {},
    }
    if not path.exists():
        return report
    report["present"] = True
    try:
        stat = path.stat()
        report["modified_at"] = _safe_text(_format_file_time(stat.st_mtime))
        report["size_bytes"] = stat.st_size
        if stat.st_size > MAX_REPORT_BYTES:
            report["status"] = "present_but_too_large_for_workbench"
            report["error"] = "report_too_large"
            return report
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error"] = _sanitize_text(str(exc), max_length=300)
        return report

    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error"] = "top_level_json_is_not_object"
        return report

    report["loaded"] = True
    report["data"] = data
    report["status"] = _first_text(data, status_keys) or "loaded"
    report["timestamp"] = _first_text(
        data,
        ("timestamp", "generated_at", "created_at", "started_at", "finished_at"),
    )
    if "success" in data:
        report["success"] = bool(data.get("success"))
    return report


def run_trustpilot_auto_queue_refresh_after_shopify_order_sync():
    return run_trustpilot_auto_queue_refresh_hook(trigger="shopify_order_sync")


def run_trustpilot_auto_queue_refresh_hook(trigger="shopify_order_sync"):
    try:
        from remote_approval.tasks.shopify_review_request_trustpilot_auto_queue_refresh_task import (
            run_shopify_review_request_trustpilot_auto_queue_refresh_hook,
        )
    except ImportError:
        try:
            return _write_auto_refresh_hook_fallback_report(trigger)
        except Exception as exc:
            return _safe_auto_refresh_hook_failure_result(trigger, exc)

    try:
        result = run_shopify_review_request_trustpilot_auto_queue_refresh_hook(trigger=trigger)
    except Exception as exc:
        try:
            return _write_auto_refresh_hook_failure_report(trigger, exc)
        except Exception as failure_exc:
            return _safe_auto_refresh_hook_failure_result(trigger, failure_exc)

    return {
        "success": bool(result.get("success", True)),
        "hook_mode": _safe_text(result.get("hook_mode") or "post_sync_best_effort", max_length=80),
        "auto_hook_invoked": True,
        "hook_safe_no_write": result.get("hook_safe_no_write") is not False,
        "last_auto_refresh_trigger": _safe_text(
            result.get("last_auto_refresh_trigger") or trigger,
            max_length=80,
        ),
        "last_auto_refresh_status": _safe_text(result.get("last_auto_refresh_status"), max_length=120),
        "last_auto_refresh_at": _safe_text(result.get("last_auto_refresh_at"), max_length=120),
        "last_auto_refresh_error": _safe_text(result.get("last_auto_refresh_error"), max_length=300),
        "json_review_path": _safe_text(result.get("json_review_path"), max_length=300),
        "html_review_path": _safe_text(result.get("html_review_path"), max_length=300),
    }


def _safe_auto_refresh_hook_failure_result(trigger, exc):
    return {
        "success": False,
        "hook_mode": "post_sync_best_effort",
        "auto_hook_invoked": True,
        "hook_safe_no_write": True,
        "last_auto_refresh_trigger": _safe_text(trigger, max_length=80),
        "last_auto_refresh_status": "auto_refresh_failed_non_blocking",
        "last_auto_refresh_at": _utc_now_iso(),
        "last_auto_refresh_error": _safe_text(f"{exc.__class__.__name__}: {exc}", max_length=300),
    }


def _write_auto_refresh_hook_fallback_report(trigger):
    payload = _build_auto_refresh_hook_fallback_payload(trigger)
    json_path, html_path = _write_auto_refresh_hook_reports(payload)
    return {
        "success": True,
        "hook_mode": payload["hook_mode"],
        "auto_hook_invoked": True,
        "hook_safe_no_write": True,
        "last_auto_refresh_trigger": payload["last_auto_refresh_trigger"],
        "last_auto_refresh_status": payload["last_auto_refresh_status"],
        "last_auto_refresh_at": payload["last_auto_refresh_at"],
        "last_auto_refresh_error": "",
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
    }


def _build_auto_refresh_hook_fallback_payload(trigger):
    refreshed_at = _utc_now_iso()
    reports = _load_known_reports()
    readiness_report = reports.get("trustpilot_locked_send_readiness_package", {})
    readiness_data = readiness_report.get("data") if readiness_report.get("loaded") else {}
    readiness_data = readiness_data if isinstance(readiness_data, dict) else {}
    eligible_count = _int_or_zero(readiness_data.get("eligible_candidate_count"))
    blocked_count = _int_or_zero(readiness_data.get("blocked_candidate_count"))
    source_status = _safe_text(
        readiness_data.get("package_status")
        or readiness_data.get("automation_status")
        or readiness_report.get("status")
        or "missing",
        max_length=120,
    )
    next_real_step = _auto_refresh_hook_next_real_step(eligible_count, source_status)
    refresh_status = _auto_refresh_hook_status(next_real_step)
    known_blockers = _auto_refresh_hook_known_blockers(readiness_data)
    payload = {
        "timestamp": refreshed_at,
        "report_generated_at": refreshed_at,
        "refreshed_at": refreshed_at,
        "task": "shopify_review_request_trustpilot_auto_queue_refresh",
        "task_name": "shopify_review_request_trustpilot_auto_queue_refresh",
        "phase": "5.9",
        "channel": "trustpilot",
        "mode": "dry-run-auto-refresh",
        "dry_run": True,
        "success": True,
        "auto_queue_refresh_only": True,
        "trigger": _safe_text(trigger, max_length=80),
        "auto_hook_invoked": True,
        "hook_mode": "post_sync_best_effort",
        "hook_safe_no_write": True,
        "hook_wired_to_sync_completion": True,
        "last_auto_refresh_trigger": _safe_text(trigger, max_length=80),
        "last_auto_refresh_status": refresh_status,
        "last_auto_refresh_at": refreshed_at,
        "last_auto_refresh_error": "",
        "refresh_status": refresh_status,
        "source_readiness_package_status": source_status,
        "computed_readiness_package_status": source_status,
        "eligible_candidate_count": eligible_count,
        "blocked_candidate_count": blocked_count,
        "selected_candidate_order_name": _safe_text(
            readiness_data.get("selected_candidate_order_name"),
            max_length=80,
        ),
        "next_real_step": next_real_step,
        "next_admin_action": _auto_refresh_hook_next_admin_action(next_real_step),
        "auto_refresh_safe_for_scheduler": True,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "gmail_future_action_status": "no_gmail_action_until_eligible_candidate",
        "shopify_tag_future_action_status": "no_shopify_tag_action_until_email_sent_and_verified",
        "ali_reviews_status": "blocked_waiting_for_vendor_api_documentation",
        "safety_flags": _auto_refresh_hook_safety_flags(),
        "known_blockers_summary": known_blockers,
        "dashboard_summary": _auto_refresh_hook_dashboard_summary(next_real_step, eligible_count),
        "report_paths": {
            "json": str(_log_dir() / TRUSTPILOT_AUTO_REFRESH_REPORT_FILENAME),
            "html": str(_log_dir() / TRUSTPILOT_AUTO_REFRESH_HTML_FILENAME),
        },
        "duration_seconds": 0,
        "detected_issue_summary": _auto_refresh_hook_issue_summary(
            next_real_step,
            eligible_count,
            blocked_count,
            known_blockers,
        ),
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "ali_reviews_write_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
        "all_new_actions_no_write_confirmed": True,
    }
    return _sanitize_auto_refresh_hook_payload(payload)


def _write_auto_refresh_hook_failure_report(trigger, exc):
    refreshed_at = _utc_now_iso()
    sanitized_error = _safe_text(f"{exc.__class__.__name__}: {exc}", max_length=300)
    payload = _sanitize_auto_refresh_hook_payload(
        {
            "timestamp": refreshed_at,
            "report_generated_at": refreshed_at,
            "refreshed_at": refreshed_at,
            "task": "shopify_review_request_trustpilot_auto_queue_refresh",
            "task_name": "shopify_review_request_trustpilot_auto_queue_refresh",
            "phase": "5.9",
            "channel": "trustpilot",
            "mode": "dry-run-auto-refresh",
            "dry_run": True,
            "success": False,
            "auto_queue_refresh_only": True,
            "trigger": _safe_text(trigger, max_length=80),
            "auto_hook_invoked": True,
            "hook_mode": "post_sync_best_effort",
            "hook_safe_no_write": True,
            "hook_wired_to_sync_completion": True,
            "last_auto_refresh_trigger": _safe_text(trigger, max_length=80),
            "last_auto_refresh_status": "auto_refresh_failed_non_blocking",
            "last_auto_refresh_at": refreshed_at,
            "last_auto_refresh_error": sanitized_error,
            "refresh_status": "auto_refresh_failed_non_blocking",
            "source_readiness_package_status": "unknown_after_hook_failure",
            "eligible_candidate_count": 0,
            "blocked_candidate_count": 0,
            "selected_candidate_order_name": "",
            "next_real_step": "wait_no_candidate",
            "next_admin_action": "Review the sanitized hook failure. Shopify order sync was not blocked.",
            "auto_refresh_safe_for_scheduler": True,
            "gmail_send_allowed_now": False,
            "gmail_draft_create_allowed_now": False,
            "shopify_tag_write_allowed_now": False,
            "external_review_api_call_allowed_now": False,
            "ali_reviews_status": "blocked_waiting_for_vendor_api_documentation",
            "safety_flags": _auto_refresh_hook_safety_flags(),
            "known_blockers_summary": _auto_refresh_hook_known_blockers({}),
            "dashboard_summary": {
                "message": "Automation refresh after Shopify sync failed without blocking order sync.",
                "detail": "Review Advanced debug details. No email, draft, Shopify tag write, or external review API call was performed.",
                "scheduler_safe_status": "scheduler_safe_dry_run_only",
                "scheduler_note": "This hook is best-effort and keeps Shopify sync non-blocking.",
            },
            "report_paths": {
                "json": str(_log_dir() / TRUSTPILOT_AUTO_REFRESH_REPORT_FILENAME),
                "html": str(_log_dir() / TRUSTPILOT_AUTO_REFRESH_HTML_FILENAME),
            },
            "duration_seconds": 0,
            "detected_issue_summary": "Trustpilot auto queue refresh hook failed after Shopify order sync; sync was not blocked.",
            "gmail_api_call_performed": False,
            "gmail_draft_create_attempted": False,
            "gmail_draft_created": False,
            "gmail_drafts_send_called": False,
            "gmail_messages_send_called": False,
            "gmail_send_performed": False,
            "email_sent": False,
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "tags_add_performed": False,
            "tags_remove_performed": False,
            "tagsAdd_performed": False,
            "tagsRemove_performed": False,
            "trustpilot_api_call_performed": False,
            "kudosi_api_call_performed": False,
            "ali_reviews_api_call_performed": False,
            "ali_reviews_write_api_call_performed": False,
            "tracking_redirect_enabled": False,
            "tracking_token_generated": False,
            "raw_customer_email_output": False,
            "full_gmail_draft_or_message_id_output": False,
            "all_new_actions_no_write_confirmed": True,
        }
    )
    json_path, html_path = _write_auto_refresh_hook_reports(payload)
    return {
        "success": False,
        "hook_mode": payload["hook_mode"],
        "auto_hook_invoked": True,
        "hook_safe_no_write": True,
        "last_auto_refresh_trigger": payload["last_auto_refresh_trigger"],
        "last_auto_refresh_status": payload["last_auto_refresh_status"],
        "last_auto_refresh_at": payload["last_auto_refresh_at"],
        "last_auto_refresh_error": payload["last_auto_refresh_error"],
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
    }


def _auto_refresh_hook_next_real_step(eligible_count, source_status):
    if eligible_count == 0 or source_status == "blocked_no_eligible_candidate":
        return "wait_no_candidate"
    if eligible_count == 1 and source_status == "locked_send_ready_for_human_approval":
        return "prepare_locked_send_package"
    if eligible_count > 1 or source_status == "blocked_multiple_candidates_require_manual_selection":
        return "manual_review_required_multiple_candidates"
    return "blocked_safety_issue"


def _auto_refresh_hook_status(next_real_step):
    if next_real_step == "wait_no_candidate":
        return "refreshed_no_eligible_candidate"
    if next_real_step == "prepare_locked_send_package":
        return "refreshed_locked_send_candidate_ready"
    if next_real_step == "manual_review_required_multiple_candidates":
        return "refreshed_multiple_candidates_manual_selection_required"
    return "refreshed_blocked_safety_issue"


def _auto_refresh_hook_next_admin_action(next_real_step):
    if next_real_step == "prepare_locked_send_package":
        return "Review the single eligible candidate and prepare a locked send package for human approval."
    if next_real_step == "manual_review_required_multiple_candidates":
        return "Multiple eligible candidates exist. Manually select exactly one candidate before any future send package."
    if next_real_step == "blocked_safety_issue":
        return "Stop automation and review safety flags before preparing any future locked send package."
    return (
        "Wait until an order is delivered, has canonical `1: review request`, and passes "
        "duplicate/related-order/ticket/refund checks."
    )


def _auto_refresh_hook_dashboard_summary(next_real_step, eligible_count):
    if next_real_step == "prepare_locked_send_package":
        message = "1 candidate is ready for locked send review. No email has been sent."
        detail = "Prepare a locked send package for human review only."
    elif next_real_step == "manual_review_required_multiple_candidates":
        message = f"{eligible_count} candidates are ready; manual selection is required."
        detail = "Select exactly one candidate before any future locked send review."
    elif next_real_step == "blocked_safety_issue":
        message = "Automation refresh found a safety issue."
        detail = "Review safety flags before any future locked send package."
    else:
        message = "Automation checked the queue. Nothing to send now."
        detail = f"Waiting for a delivered order with `{CANONICAL_REVIEW_REQUEST_TAG}` that passes all safety checks."
    return {
        "message": message,
        "detail": detail,
        "scheduler_safe_status": "scheduler_safe_dry_run_only",
        "scheduler_note": (
            "This refresh is safe to run on a schedule because it does not send emails, "
            "create Gmail drafts, or write Shopify tags."
        ),
    }


def _auto_refresh_hook_known_blockers(readiness_data):
    order_22620 = readiness_data.get("order_22620_blocker_status")
    order_22620 = order_22620 if isinstance(order_22620, dict) else {}
    order_22582 = readiness_data.get("order_22582_blocker_status")
    order_22582 = order_22582 if isinstance(order_22582, dict) else {}
    prior_order = _safe_text(order_22620.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
    return [
        {
            "order_name": "#22620",
            "status": _safe_text(order_22620.get("status") or "blocked", max_length=80),
            "summary": f"Already sent to this customer via {prior_order}",
            "message": _safe_text(
                order_22620.get("message") or f"Do not send. Already sent to this customer via {prior_order}.",
                max_length=300,
            ),
            "blocking_reasons": [
                _safe_text(value, max_length=120)
                for value in (order_22620.get("blocking_reasons") or [])
                if _safe_text(value, max_length=120)
            ],
            "selected_candidate_safe_to_prepare_send": False,
        },
        {
            "order_name": "#22582",
            "status": _safe_text(order_22582.get("status") or "blocked", max_length=80),
            "summary": f"Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, related orders #22582/#22581 not ready",
            "message": _safe_text(
                order_22582.get("message")
                or (
                    f"Do not send yet. Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
                    "related order group #22582/#22581 not ready."
                ),
                max_length=300,
            ),
            "blocking_reasons": [
                _safe_text(value, max_length=120)
                for value in (order_22582.get("blocking_reasons") or [])
                if _safe_text(value, max_length=120)
            ],
            "selected_candidate_safe_to_prepare_send": False,
        },
    ]


def _auto_refresh_hook_issue_summary(next_real_step, eligible_count, blocked_count, known_blockers):
    if next_real_step == "prepare_locked_send_package":
        return "One Trustpilot candidate is ready for locked send review. No email has been sent."
    if next_real_step == "manual_review_required_multiple_candidates":
        return f"{eligible_count} Trustpilot candidates are eligible; manual selection is required before any send package."
    if next_real_step == "blocked_safety_issue":
        return "Trustpilot auto queue refresh is blocked by a safety flag; no send or write action is allowed."
    order_22620 = _safe_text((known_blockers[0] if known_blockers else {}).get("summary"), max_length=160)
    order_22582 = _safe_text((known_blockers[1] if len(known_blockers) > 1 else {}).get("summary"), max_length=200)
    return (
        f"No eligible Trustpilot candidate; {blocked_count} blocked candidate summaries were prepared. "
        f"#22620 remains blocked: {order_22620}. #22582 remains blocked: {order_22582}."
    )


def _auto_refresh_hook_safety_flags():
    return {
        "readiness_package_read_from_local_report_only": True,
        "auto_refresh_safe_for_scheduler": True,
        "hook_safe_no_write": True,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_deleted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_allowed_now": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "external_review_api_call_allowed_now": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "ali_reviews_write_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_auto_refresh_hook_reports(payload):
    log_dir = _log_dir()
    log_dir.mkdir(parents=True, exist_ok=True)
    json_path = log_dir / TRUSTPILOT_AUTO_REFRESH_REPORT_FILENAME
    html_path = log_dir / TRUSTPILOT_AUTO_REFRESH_HTML_FILENAME
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    html_path.write_text(_render_auto_refresh_hook_html(payload), encoding="utf-8")
    return json_path, html_path


def _render_auto_refresh_hook_html(payload):
    safety_rows = "\n".join(
        f"<tr><td><code>{escape(str(key))}</code></td><td>{escape(str(value))}</td></tr>"
        for key, value in (payload.get("safety_flags") or {}).items()
    )
    known_blockers = payload.get("known_blockers_summary") if isinstance(payload.get("known_blockers_summary"), list) else []
    blocker_rows = "\n".join(
        "<tr>"
        f"<td>{escape(_safe_text(row.get('order_name'), max_length=80))}</td>"
        f"<td><code>{escape(_safe_text(row.get('status'), max_length=80))}</code></td>"
        f"<td>{escape(_safe_text(row.get('summary'), max_length=200))}</td>"
        f"<td>{escape(_safe_text(row.get('message'), max_length=300))}</td>"
        "</tr>"
        for row in known_blockers
        if isinstance(row, dict)
    )
    error_html = ""
    if payload.get("last_auto_refresh_error"):
        error_html = f"<p>Sanitized error: {escape(_safe_text(payload.get('last_auto_refresh_error'), max_length=300))}</p>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Auto Queue Refresh</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Trustpilot Auto Queue Refresh</h1>
  <p>Refresh status: <strong>{escape(_safe_text(payload.get("refresh_status"), max_length=120))}</strong></p>
  <p>After Shopify order sync, this dashboard refreshes the Trustpilot review queue automatically. It does not send emails, create Gmail drafts, or write Shopify tags.</p>
  {error_html}
  <table>
    <tbody>
      <tr><th>Last trigger</th><td><code>{escape(_safe_text(payload.get("last_auto_refresh_trigger"), max_length=80))}</code></td></tr>
      <tr><th>Last refresh time</th><td>{escape(_safe_text(payload.get("last_auto_refresh_at"), max_length=120))}</td></tr>
      <tr><th>Source readiness package status</th><td><code>{escape(_safe_text(payload.get("source_readiness_package_status"), max_length=120))}</code></td></tr>
      <tr><th>Eligible candidate count</th><td>{_int_or_zero(payload.get("eligible_candidate_count"))}</td></tr>
      <tr><th>Blocked candidate count</th><td>{_int_or_zero(payload.get("blocked_candidate_count"))}</td></tr>
      <tr><th>Next real step</th><td><code>{escape(_safe_text(payload.get("next_real_step"), max_length=120))}</code></td></tr>
    </tbody>
  </table>
  <h2>Known Blockers</h2>
  <table><thead><tr><th>Order</th><th>Status</th><th>Summary</th><th>Message</th></tr></thead><tbody>{blocker_rows}</tbody></table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _sanitize_auto_refresh_hook_payload(value):
    if isinstance(value, dict):
        return {_safe_text(key, max_length=120): _sanitize_auto_refresh_hook_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_sanitize_auto_refresh_hook_payload(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value, max_length=1000)
    return value


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _format_file_time(timestamp):
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _local_order_stats():
    try:
        orders = ShopifyOrder.objects.all()
        with_email = orders.exclude(customer_email__isnull=True).exclude(customer_email="")
        latest = orders.order_by("-order_created_at").values(
            "order_name",
            "customer_email",
            "order_created_at",
            "fulfillment_status",
            "financial_status",
        )[:10]
        return {
            "available": True,
            "total_orders": orders.count(),
            "orders_with_email": with_email.count(),
            "recent_orders": [
                {
                    "order_name": _safe_text(row.get("order_name")),
                    "masked_email": mask_email(row.get("customer_email")),
                    "order_created_at": _safe_text(row.get("order_created_at")),
                    "fulfillment_status": _safe_text(row.get("fulfillment_status")),
                    "financial_status": _safe_text(row.get("financial_status")),
                }
                for row in latest
            ],
            "note": (
                "Local ShopifyOrder rows do not store Shopify order tags; tag sections "
                "come from local review-request reports when present."
            ),
        }
    except Exception as exc:  # pragma: no cover - defensive admin display path.
        return {
            "available": False,
            "total_orders": 0,
            "orders_with_email": 0,
            "recent_orders": [],
            "error": _sanitize_text(str(exc), max_length=300),
            "note": "Local order summary could not be loaded.",
        }


def _collect_report_rows(reports):
    rows = []
    for report in reports.values():
        data = report.get("data") if report.get("loaded") else {}
        if not isinstance(data, dict):
            continue
        rows.extend(_rows_from_report(data, report["label"], report["relative_path"]))
        if len(rows) >= MAX_SOURCE_ROWS:
            break
    return rows[:MAX_SOURCE_ROWS]


def _rows_from_report(data, source_label, source_path):
    rows = []
    selected = data.get("selected_candidate")
    if isinstance(selected, dict):
        rows.append(_row_from_mapping(selected, source_label, source_path, "selected_candidate"))

    for list_key, section in (
        ("ready_candidate_queue", "ready_candidate_queue"),
        ("eligible_candidates_summary", "eligible_candidates_summary"),
        ("evaluated_orders", "evaluated_orders"),
        ("orders", "orders"),
        ("blocked_orders", "blocked_orders"),
        ("blocked_candidates_summary", "blocked_candidates_summary"),
        ("repeat_customer_candidates", "repeat_customer_candidates"),
        ("needs_manual_review", "needs_manual_review"),
        ("decisions", "decisions"),
    ):
        value = data.get(list_key)
        if isinstance(value, list):
            rows.extend(
                _row_from_mapping(item, source_label, source_path, section)
                for item in value
                if isinstance(item, dict)
            )

    classification_buckets = data.get("classification_buckets")
    if isinstance(classification_buckets, dict):
        for bucket, items in classification_buckets.items():
            if isinstance(items, list):
                rows.extend(
                    _row_from_mapping(
                        item,
                        source_label,
                        source_path,
                        f"classification:{bucket}",
                    )
                    for item in items
                    if isinstance(item, dict)
                )

    manual_sections = data.get("manual_action_sections")
    if isinstance(manual_sections, dict):
        for section, items in manual_sections.items():
            if isinstance(items, list):
                rows.extend(
                    _row_from_mapping(
                        item,
                        source_label,
                        source_path,
                        f"manual_action:{section}",
                    )
                    for item in items
                    if isinstance(item, dict)
                )

    top_level_row = _row_from_top_level_report(data, source_label, source_path)
    if top_level_row:
        rows.append(top_level_row)
    return [row for row in rows if row]


def _row_from_top_level_report(data, source_label, source_path):
    order_name = _first_text(data, ("selected_candidate_order_name", "selected_order_name", "next_candidate_order_name"))
    masked_email = _first_text(data, ("selected_masked_email", "next_candidate_masked_email"))
    if not order_name and not masked_email:
        return None
    return {
        "order_name": order_name,
        "order_id": "",
        "masked_email": mask_email(masked_email),
        "created_at": _first_text(data, ("timestamp", "created_at")),
        "status": _first_text(
            data,
            (
                "next_repeat_customer_candidate_scan_status",
                "package_status",
                "automation_status",
                "report_status",
                "status",
            ),
        ),
        "source": source_label,
        "source_path": source_path,
        "source_section": "report_summary",
        "tags": [],
        "tags_summary": "No tag data in this summary row",
        "trustpilot_tags": [],
        "trustpilot_invitation_present": False,
        "delivered_tag_present": False,
        "canonical_review_request_tag_present": False,
        "typo_review_request_tag_present": False,
        "review_request_tag_present": False,
        "merged_or_related_order_guard_status": "",
        "eligible_for_trustpilot": False,
        "blocking_reasons": [],
        "blocking_summary": "",
        "repeat_customer_detected": "",
    }


def _row_from_mapping(item, source_label, source_path, source_section):
    order_name = _first_text(
        item,
        (
            "order_name",
            "name",
            "selected_candidate_order_name",
            "selected_order_name",
            "next_candidate_order_name",
        ),
    )
    order_id = _first_text(item, ("order_id", "order_id_or_gid", "id"))
    masked_email = _first_text(
        item,
        ("masked_email", "selected_masked_email", "next_candidate_masked_email", "email"),
    )
    tags = _collect_tags(item)
    trustpilot_tags = _matched_trustpilot_tags(item, tags)
    blocking_reasons = _collect_string_list(item, "blocking_reasons")
    if not blocking_reasons:
        blocking_reasons = _collect_string_list(item, "classification_reasons")
    if not blocking_reasons:
        blocking_reasons = _collect_string_list(item, "reasons")
    status = _first_text(
        item,
        (
            "reason",
            "candidate_status",
            "classification",
            "decision",
            "source_decision",
            "suggested_next_manual_action",
            "package_status",
            "status",
        ),
    )
    if not any((order_name, order_id, masked_email, tags, trustpilot_tags, status)):
        return None

    return {
        "order_name": order_name or order_id,
        "order_id": order_id,
        "masked_email": mask_email(masked_email),
        "created_at": _first_text(
            item,
            ("createdAt", "created_at", "order_created_at", "processed_at", "timestamp"),
        ),
        "status": status or source_section,
        "source": source_label,
        "source_path": source_path,
        "source_section": source_section,
        "tags": tags,
        "tags_summary": ", ".join(tags) if tags else "No tag data in row",
        "trustpilot_tags": trustpilot_tags,
        "trustpilot_invitation_present": bool(trustpilot_tags),
        "delivered_tag_present": item.get("delivered_tag_present") is True or DELIVERED_TAG in tags or "妥投" in tags,
        "canonical_review_request_tag_present": (
            item.get("canonical_review_request_tag_present") is True or CANONICAL_REVIEW_REQUEST_TAG in tags
        ),
        "typo_review_request_tag_present": TYPO_REVIEW_REQUEST_TAG in tags,
        "review_request_tag_present": item.get("canonical_review_request_tag_present") is True or CANONICAL_REVIEW_REQUEST_TAG in tags,
        "merged_or_related_order_guard_status": _safe_text(item.get("merged_or_related_order_guard_status")),
        "eligible_for_trustpilot": (
            item.get("eligible_for_trustpilot") is True
            or item.get("safe_to_prepare_send") is True
        ),
        "blocking_reasons": blocking_reasons,
        "blocking_summary": ", ".join(blocking_reasons),
        "repeat_customer_detected": _safe_text(item.get("repeat_customer_detected")),
        "customer_level_duplicate_block_applies": item.get("customer_level_duplicate_block_applies") is True,
        "prior_trustpilot_order_name": _safe_text(item.get("prior_trustpilot_order_name")),
        "same_customer_detected": item.get("same_customer_detected") is True,
        "same_email_detected": item.get("same_email_detected") is True,
        "existing_unsent_gmail_draft_should_not_be_sent": (
            item.get("existing_unsent_gmail_draft_should_not_be_sent") is True
        ),
    }


def _candidate_queue(reports):
    next_data = (reports.get("next_candidate_scan") or {}).get("data") or {}
    queue = next_data.get("ready_candidate_queue") if isinstance(next_data, dict) else []
    rows = [
        _row_from_mapping(
            item,
            "Next repeat customer candidate scan",
            "logs/shopify_review_request_next_repeat_customer_candidate_scan.json",
            "ready_candidate_queue",
        )
        for item in queue or []
        if isinstance(item, dict)
    ]
    rows = [row for row in rows if row]
    if rows:
        return rows

    candidate_data = (reports.get("candidate_scan") or {}).get("data") or {}
    fallback = candidate_data.get("repeat_customer_candidates") if isinstance(candidate_data, dict) else []
    return [
        row
        for row in (
            _row_from_mapping(
                item,
                "Candidate scan",
                "logs/shopify_review_request_candidate_scan.json",
                "repeat_customer_candidates",
            )
            for item in fallback or []
            if isinstance(item, dict)
        )
        if row
    ]


def _blocked_rows(reports, all_rows):
    next_data = (reports.get("next_candidate_scan") or {}).get("data") or {}
    rows = []
    if isinstance(next_data, dict):
        for item in next_data.get("evaluated_orders") or []:
            if not isinstance(item, dict):
                continue
            row = _row_from_mapping(
                item,
                "Next repeat customer candidate scan",
                "logs/shopify_review_request_next_repeat_customer_candidate_scan.json",
                "evaluated_orders",
            )
            if row and (row["blocking_reasons"] or row["status"] == "blocked"):
                rows.append(row)
    if rows:
        return _dedupe_rows(rows)

    candidate_data = (reports.get("candidate_scan") or {}).get("data") or {}
    if isinstance(candidate_data, dict):
        for item in candidate_data.get("blocked_orders") or []:
            if isinstance(item, dict):
                row = _row_from_mapping(
                    item,
                    "Candidate scan",
                    "logs/shopify_review_request_candidate_scan.json",
                    "blocked_orders",
                )
                if row:
                    rows.append(row)
    if rows:
        return _dedupe_rows(rows)
    return [
        row
        for row in all_rows
        if row.get("blocking_reasons") or str(row.get("status", "")).startswith("blocked")
    ]


def _rows_with_trustpilot_tags(rows):
    return [row for row in rows if row.get("trustpilot_invitation_present")]


def _rows_with_canonical_review_request_tag(rows):
    return [row for row in rows if row.get("canonical_review_request_tag_present")]


def _rows_with_typo_review_request_tag(rows):
    return [row for row in rows if row.get("typo_review_request_tag_present")]


def _latest_scan_summary(report):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    return {
        "present": bool(report.get("present")),
        "loaded": bool(report.get("loaded")),
        "relative_path": report.get("relative_path", "logs/shopify_review_request_next_repeat_customer_candidate_scan.json"),
        "status": report.get("status", "missing"),
        "timestamp": _first_text(data, ("timestamp",)) or report.get("modified_at", ""),
        "generated_time": _first_text(data, ("timestamp",)) or report.get("modified_at", ""),
        "selected_order_name": _first_text(
            data,
            ("selected_order_name", "next_candidate_order_name"),
        ),
        "selected_masked_email": mask_email(
            _first_text(data, ("selected_masked_email", "next_candidate_masked_email"))
        ),
        "eligible_candidate_count": _int_or_zero(
            data.get("eligible_candidate_count")
            or data.get("eligible_repeat_customer_candidate_count")
        ),
        "next_candidate_count": _int_or_zero(data.get("next_candidate_count")),
        "next_candidate_blocked_reason": _first_text(data, ("next_candidate_blocked_reason",)),
        "candidate_22582_audit": data.get("candidate_22582_audit") if isinstance(data.get("candidate_22582_audit"), dict) else {},
        "report_status": _first_text(
            data,
            ("next_repeat_customer_candidate_scan_status", "report_status", "status"),
        )
        or report.get("status", "missing"),
    }


def _normalize_filters(params):
    params = params or {}
    q = _safe_text(_param_get(params, "q"), max_length=80)
    status = _param_get(params, "status") or "all"
    tag = _param_get(params, "tag") or "all"
    if status not in {value for value, _label in STATUS_FILTER_OPTIONS}:
        status = "all"
    if tag not in {value for value, _label in TAG_FILTER_OPTIONS}:
        tag = "all"
    try:
        limit = int(_param_get(params, "limit") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        limit = DEFAULT_LIMIT
    if limit not in LIMIT_OPTIONS:
        limit = DEFAULT_LIMIT
    return {
        "q": q,
        "status": status,
        "tag": tag,
        "limit": limit,
        "has_active_filters": bool(q or status != "all" or tag != "all" or limit != DEFAULT_LIMIT),
    }


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
        for value in LIMIT_OPTIONS
    ]


def _filter_rows(rows, filters, section_status):
    matched = [
        row
        for row in rows
        if _row_matches_query(row, filters["q"])
        and _row_matches_status(row, filters["status"], section_status)
        and _row_matches_tag(row, filters["tag"])
    ]
    return matched[: filters["limit"]]


def _row_matches_query(row, query):
    if not query:
        return True
    query = query.lower()
    return query in " ".join(
        (
            _safe_text(row.get("order_name")).lower(),
            _safe_text(row.get("masked_email")).lower(),
        )
    )


def _row_matches_status(row, status, section_status):
    if status == "all":
        return True
    if status == "queue":
        return section_status == "queue" or row.get("canonical_review_request_tag_present")
    if status == "trustpilot_sent":
        return row.get("trustpilot_invitation_present")
    if status == "blocked":
        return section_status == "blocked" or _row_has_blocker(row)
    if status == "report_ready":
        return False
    return True


def _row_matches_tag(row, tag):
    if tag == "all":
        return True
    if tag == "review_request":
        return row.get("canonical_review_request_tag_present") or row.get(
            "typo_review_request_tag_present"
        )
    if tag == "trustpilot_alias":
        return row.get("trustpilot_invitation_present")
    if tag == "returned_package":
        return _row_has_returned_package(row)
    return True


def _filter_report_readiness(rows, filters):
    if filters["status"] not in {"all", "report_ready"}:
        return []
    if filters["tag"] != "all":
        return []
    query = filters["q"].lower()
    filtered = []
    for row in rows:
        haystack = " ".join(
            (
                row.get("label", ""),
                row.get("relative_path", ""),
                row.get("status", ""),
            )
        ).lower()
        if query and query not in haystack:
            continue
        if filters["status"] == "report_ready" and not row.get("present"):
            continue
        filtered.append(row)
    return filtered[: filters["limit"]]


def _filter_summary(
    filters,
    candidate_queue,
    invitation_history,
    review_request_queue,
    typo_review_request_rows,
    blocked_orders,
    report_readiness,
    history_ledger,
):
    return {
        "active": filters["has_active_filters"],
        "visible_queue_rows": len(candidate_queue)
        + len(review_request_queue)
        + len(typo_review_request_rows),
        "visible_trustpilot_history_rows": len(invitation_history),
        "visible_blocked_rows": len(blocked_orders),
        "visible_report_rows": len(report_readiness),
        "visible_history_rows": len(history_ledger),
        "limit": filters["limit"],
    }


def _report_readiness(reports):
    focus = (
        ("next_candidate_scan", "Latest candidate scan"),
        ("candidate_scan", "Candidate scan"),
        ("trustpilot_automation_dry_run", "Trustpilot automation dry-run"),
        ("trustpilot_locked_send_readiness_package", "Trustpilot locked send readiness package"),
        ("trustpilot_auto_queue_refresh", "Trustpilot auto queue refresh"),
        ("trustpilot_candidate_simulator", "Trustpilot candidate simulator (sandbox)"),
        ("trustpilot_locked_gmail_send_gate", "Trustpilot locked Gmail send gate"),
        ("trustpilot_gmail_send_executor_shell", "Trustpilot Gmail send executor shell"),
        ("trustpilot_real_send_final_preflight", "Trustpilot real send final preflight"),
        ("trustpilot_real_send_execute", "Trustpilot real send execute skeleton"),
        ("trustpilot_gmail_real_send_readiness_audit", "Trustpilot Gmail real-send readiness audit"),
        ("trustpilot_gmail_oauth_config_helper", "Trustpilot Gmail OAuth/config helper"),
        ("trustpilot_gmail_config_compatibility_audit", "Trustpilot Gmail config compatibility audit"),
        ("trustpilot_one_candidate_draft_package", "One-candidate Gmail draft package"),
        ("trustpilot_one_candidate_draft_create_execute", "One-candidate Gmail draft create execute"),
        ("trustpilot_one_candidate_draft_send_preflight", "One-candidate Gmail send preflight"),
        ("trustpilot_one_candidate_draft_send_execute", "One-candidate Gmail send execute"),
        ("customer_level_duplicate_audit", "Customer-level duplicate audit"),
        ("ali_reviews_api_capability_discovery", "Ali Reviews API capability discovery"),
        ("trustpilot_send_audit", "Future send audit"),
        ("trustpilot_tag_write_audit", "Future tag audit"),
    )
    rows = []
    for key, display_label in focus:
        report = reports.get(key) or {}
        present = bool(report.get("present"))
        loaded = bool(report.get("loaded"))
        rows.append(
            {
                "key": key,
                "label": display_label,
                "relative_path": report.get("relative_path", ""),
                "present": present,
                "loaded": loaded,
                "status": _safe_text(report.get("status") or "missing"),
                "timestamp": _safe_text(report.get("timestamp")),
                "modified_at": _safe_text(report.get("modified_at")),
                "readiness_label": (
                    "Local report ready"
                    if present and loaded
                    else "Present but not loaded"
                    if present
                    else "Missing"
                ),
                "badge_class": (
                    "rrw-badge-ok"
                    if present and loaded
                    else "rrw-badge-warn"
                    if present
                    else "rrw-badge-muted"
                ),
            }
        )
    return rows


def _local_order_link_map(rows, latest_scan):
    order_names = set()
    order_numbers = set()
    shopify_order_ids = set()
    for row in rows:
        _collect_order_lookup_values(
            row.get("order_name"),
            row.get("order_id"),
            order_names,
            order_numbers,
            shopify_order_ids,
        )
    _collect_order_lookup_values(
        latest_scan.get("selected_order_name"),
        "",
        order_names,
        order_numbers,
        shopify_order_ids,
    )
    if not (order_names or order_numbers or shopify_order_ids):
        return {}

    query = Q()
    if order_names:
        query |= Q(order_name__in=order_names)
    if order_numbers:
        query |= Q(order_number__in=order_numbers)
    if shopify_order_ids:
        query |= Q(shopify_order_id__in=shopify_order_ids)
    if not query:
        return {}

    links = {}
    try:
        for order in ShopifyOrder.objects.filter(query).values(
            "id",
            "order_name",
            "order_number",
            "shopify_order_id",
        )[: MAX_SOURCE_ROWS]:
            try:
                url = reverse("admin:shopify_sync_shopifyorder_change", args=[order["id"]])
            except NoReverseMatch:
                continue
            link = {
                "id": order["id"],
                "url": url,
                "label": "Open local order",
            }
            for key in _order_lookup_keys(
                order.get("order_name"),
                order.get("order_number"),
                order.get("shopify_order_id"),
            ):
                links[key] = link
    except Exception:
        return {}
    return links


def _collect_order_lookup_values(order_name, order_id, order_names, order_numbers, shopify_order_ids):
    name = _safe_text(order_name, max_length=120)
    if name:
        order_names.add(name)
        stripped = name.lstrip("#")
        if stripped and stripped != name:
            order_numbers.add(stripped)
    shopify_order_id = _extract_shopify_order_id(order_id)
    if shopify_order_id:
        shopify_order_ids.add(shopify_order_id)


def _order_lookup_keys(order_name, order_number="", shopify_order_id=""):
    keys = []
    name = _safe_text(order_name, max_length=120)
    number = _safe_text(order_number, max_length=120)
    if name:
        keys.append(f"name:{name}")
        stripped = name.lstrip("#")
        if stripped and stripped != name:
            keys.append(f"number:{stripped}")
    if number:
        keys.append(f"number:{number}")
        if not number.startswith("#"):
            keys.append(f"name:#{number}")
    if shopify_order_id:
        keys.append(f"shopify_id:{shopify_order_id}")
    return keys


def _extract_shopify_order_id(value):
    text = _safe_text(value, max_length=120)
    if not text:
        return ""
    match = re.search(r"Order/(\d+)$", text)
    if match:
        return match.group(1)
    if text.isdigit():
        return text
    return ""


def _attach_local_order_links(rows, local_order_links):
    for row in rows:
        link = _find_local_order_link(row, local_order_links)
        row["local_order_url"] = link.get("url", "") if link else ""
        row["local_order_id"] = link.get("id", "") if link else ""
        row["local_order_link_label"] = link.get("label", "") if link else ""


def _attach_latest_scan_local_order_link(latest_scan, local_order_links):
    link = _find_local_order_link(
        {
            "order_name": latest_scan.get("selected_order_name"),
            "order_id": "",
        },
        local_order_links,
    )
    latest_scan["local_order_url"] = link.get("url", "") if link else ""
    latest_scan["local_order_id"] = link.get("id", "") if link else ""
    latest_scan["local_order_link_label"] = link.get("label", "") if link else ""


def _find_local_order_link(row, local_order_links):
    for key in _row_order_lookup_keys(row):
        link = local_order_links.get(key)
        if link:
            return link
    return None


def _row_order_lookup_keys(row):
    keys = _order_lookup_keys(row.get("order_name"))
    shopify_order_id = _extract_shopify_order_id(row.get("order_id"))
    if shopify_order_id:
        keys.append(f"shopify_id:{shopify_order_id}")
    return keys


def _attach_status_badges(rows, latest_scan):
    selected_order = latest_scan.get("selected_order_name")
    for row in rows:
        badges = []
        if selected_order and row.get("order_name") == selected_order:
            badges.append(_badge("Next candidate", "rrw-badge-ok"))
        if row.get("delivered_tag_present"):
            badges.append(_badge("Delivered", "rrw-badge-ok"))
        elif _row_text_contains(row, ("blocked_missing_delivered_tag", "missing delivered")):
            badges.append(_badge("Blocked: missing delivered", "rrw-badge-bad"))
        if row.get("canonical_review_request_tag_present"):
            badges.append(_badge("In review request queue", "rrw-badge-ok"))
        elif _row_text_contains(row, ("blocked_missing_review_request_tag", "canonical review")):
            badges.append(_badge("Blocked: missing review tag", "rrw-badge-bad"))
        if row.get("typo_review_request_tag_present"):
            badges.append(_badge("Typo tag: not canonical", "rrw-badge-warn"))
        if _row_text_contains(row, ("blocked_merged_order_group_not_ready", "merged", "related order group")):
            badges.append(_badge("Blocked: related group", "rrw-badge-bad"))
        if row.get("trustpilot_invitation_present"):
            badges.append(_badge("Trustpilot already sent", "rrw-badge-info"))
        if _row_has_returned_package(row):
            badges.append(_badge("Blocked: returned package", "rrw-badge-bad"))
        if _row_has_duplicate_trustpilot(row):
            badges.append(_badge("Blocked: duplicate Trustpilot invitation", "rrw-badge-bad"))
        if _row_has_customer_level_duplicate_trustpilot(row):
            badges.append(_badge("Blocked: customer duplicate Trustpilot", "rrw-badge-bad"))
        if _row_has_first_order(row):
            badges.append(_badge("Blocked: first order", "rrw-badge-warn"))
        if _row_has_risk_or_ticket(row):
            badges.append(_badge("Blocked: risk/ticket/refund/cancel/dispute", "rrw-badge-bad"))
        if not badges and row.get("source_section") in {
            "ready_candidate_queue",
            "repeat_customer_candidates",
        }:
            badges.append(_badge("In candidate scan queue", "rrw-badge-info"))
        row["status_badges"] = badges


def _badge(label, css_class):
    return {"label": label, "css_class": css_class}


def _blocked_reason_counts(blocked_orders):
    counts = []
    for key, label, needles in BLOCKED_REASON_DEFINITIONS:
        count = sum(
            1
            for row in blocked_orders
            if _row_text_contains(row, needles)
            or (key == "duplicate_trustpilot_invitation" and row.get("trustpilot_invitation_present"))
        )
        counts.append({"key": key, "label": label, "count": count})
    return counts


def _row_has_blocker(row):
    return bool(row.get("blocking_reasons")) or str(row.get("status", "")).startswith("blocked")


def _row_has_returned_package(row):
    return _row_text_contains(row, ("returned package", "returned_package", "return package", "returned"))


def _row_has_duplicate_trustpilot(row):
    return row.get("trustpilot_invitation_present") and (
        _row_has_blocker(row)
        or _row_text_contains(row, ("duplicate", "existing_trustpilot", "trustpilot invitation"))
    )


def _row_has_customer_level_duplicate_trustpilot(row):
    return row.get("customer_level_duplicate_block_applies") or _row_text_contains(
        row,
        (
            "blocked_existing_trustpilot_invitation_customer_level",
            "customer_level",
            "same_customer",
            "same_email",
            "prior_trustpilot",
        ),
    )


def _row_has_first_order(row):
    return _row_text_contains(row, ("first order", "first_order"))


def _row_has_risk_or_ticket(row):
    return _row_text_contains(
        row,
        ("risk", "ticket", "refund", "cancel", "cancelled", "dispute", "chargeback"),
    )


def _row_text_contains(row, needles):
    haystack = " ".join(
        (
            row.get("status", ""),
            row.get("blocking_summary", ""),
            row.get("tags_summary", ""),
            row.get("source_section", ""),
        )
    ).lower()
    return any(needle in haystack for needle in needles)


def _report_history(reports):
    rows = []
    for report in reports.values():
        rows.append(
            {
                "label": report["label"],
                "relative_path": report["relative_path"],
                "present": report["present"],
                "loaded": report["loaded"],
                "status": _safe_text(report.get("status")),
                "timestamp": _safe_text(report.get("timestamp")),
                "modified_at": _safe_text(report.get("modified_at")),
                "success": report.get("success"),
                "error": _safe_text(report.get("error")),
            }
        )
    return rows


def _safety_history(reports):
    rows = []
    for report in reports.values():
        data = report.get("data") if report.get("loaded") else {}
        if not isinstance(data, dict):
            continue
        flags = []
        true_flags = []
        for flag in SAFETY_FLAGS:
            if flag in data:
                value = bool(data.get(flag))
                flags.append({"name": flag, "value": value})
                if value:
                    true_flags.append(flag)
        safety_summary = data.get("safety_summary")
        if isinstance(safety_summary, dict):
            for flag in SAFETY_FLAGS:
                if flag in safety_summary and flag not in {item["name"] for item in flags}:
                    value = bool(safety_summary.get(flag))
                    flags.append({"name": flag, "value": value})
                    if value:
                        true_flags.append(flag)
        rows.append(
            {
                "label": report["label"],
                "relative_path": report["relative_path"],
                "status": _safe_text(report.get("status")),
                "timestamp": _safe_text(report.get("timestamp")),
                "flags": flags,
                "true_flags": true_flags,
                "true_flag_count": len(true_flags),
            }
        )
    return rows


def _module_overview(latest_scan, candidate_queue, blocked_orders, history_ledger):
    history_summary = history_ledger.get("summary") or {}
    history_focus = history_ledger.get("focus") or {}
    source_reports = history_ledger.get("source_reports") or []
    eligible_count = _int_or_zero(latest_scan.get("eligible_candidate_count")) or len(candidate_queue)
    next_candidate = _current_next_candidate(latest_scan, candidate_queue, history_focus)
    blocked_count = len(blocked_orders) or _history_event_count(
        history_summary,
        {"candidate_blocked", "duplicate_block"},
    )
    ali_status = ((history_focus.get("ali_reviews_api") or {}).get("status")) or "unavailable"
    last_update = _latest_source_update_time(source_reports) or latest_scan.get("generated_time") or "-"
    return [
        {
            "label": "Total Ledger Events",
            "value": history_summary.get("total_event_count", 0),
            "note": "Normalized from local review-request reports.",
        },
        {
            "label": "Eligible Candidates",
            "value": eligible_count,
            "note": "Current scan count after delivered, tag, duplicate, and risk gates.",
        },
        {
            "label": "Next Candidate",
            "value": next_candidate or "None",
            "note": "No action is available from this read-only workbench.",
        },
        {
            "label": "Blocked / Not Eligible",
            "value": blocked_count,
            "note": "Current local report rows or reconstructed blocked ledger events.",
        },
        {
            "label": "Ali Reviews API",
            "value": ali_status,
            "note": "Vendor API documentation is required before any API automation.",
        },
        {
            "label": "Last Audit / Update",
            "value": last_update,
            "note": "Latest modified local source report loaded by the ledger.",
        },
    ]


def _candidate_queue_status(latest_scan, candidate_queue, history_focus):
    next_candidate = _current_next_candidate(latest_scan, candidate_queue, history_focus)
    eligible_count = _int_or_zero(latest_scan.get("eligible_candidate_count")) or len(candidate_queue)
    blocked_reason = latest_scan.get("next_candidate_blocked_reason") or ""
    if not next_candidate and eligible_count == 0:
        blocked_reason = blocked_reason or "no_eligible_delivered_review_request_candidate"
    return {
        "status": "eligible_candidate_available" if next_candidate else "no_eligible_candidate",
        "order_name": next_candidate or "None",
        "eligible_candidate_count": eligible_count,
        "reason": blocked_reason,
        "requirements": [
            f"Delivered tag present ({DELIVERED_TAG})",
            f"Exact canonical review-request tag present ({CANONICAL_REVIEW_REQUEST_TAG})",
            "Merged or related order group ready",
            "No duplicate Trustpilot invitation at order or customer level",
            "No unresolved ticket, refund, return, shipping, dispute, or chargeback risk",
        ],
    }


def _trustpilot_email_records(events, filters):
    records = []
    if filters.get("channel") not in {"all", "trustpilot"}:
        return records
    for event in events:
        if event.get("channel") != "trustpilot":
            continue
        if not _is_trustpilot_email_record(event):
            continue
        if not _event_matches_trustpilot_record_filters(event, filters):
            continue
        records.append(
            {
                "event_time": _safe_text(event.get("event_time")) or _safe_text(event.get("loaded_at")),
                "order_name": _safe_text(event.get("order_name"), max_length=80),
                "masked_email": mask_email(event.get("masked_email")),
                "event_type": _safe_text(event.get("event_type")),
                "status": _safe_text(event.get("status")),
                "classification": _safe_text(event.get("classification")),
                "blocker_reason": _safe_text(event.get("blocker_reason")),
                "gmail_draft_created": event.get("gmail_draft_created"),
                "email_sent": event.get("email_sent"),
                "partial_draft_id": _safe_text(event.get("partial_draft_id"), max_length=80),
                "partial_message_id": _safe_text(event.get("partial_message_id"), max_length=80),
                "source_report_path": _safe_text(event.get("source_report_path")),
                "source_report_label": _safe_text(event.get("source_report_label")),
                "source_section": _safe_text(event.get("source_section")),
                "draft_should_not_be_sent": bool(event.get("draft_should_not_be_sent")),
                "prior_trustpilot_order_name": _safe_text(
                    event.get("prior_trustpilot_order_name"),
                    max_length=80,
                ),
                "badge_class": event.get("badge_class") or "rrw-badge-info",
            }
        )
    return records[: filters.get("ledger_limit", DEFAULT_LIMIT)]


def _ali_reviews_status(history_focus):
    status = (history_focus.get("ali_reviews_api") or {}) if isinstance(history_focus, dict) else {}
    api_status = status.get("status") or "unavailable"
    return {
        "status": api_status,
        "vendor_docs_needed": api_status == "blocked_missing_vendor_api_documentation",
        "evidence_report_path": status.get("evidence_report_path") or "",
        "loaded": bool(status.get("loaded")),
        "manual_policy": (
            "Do not manually manage Ali Reviews blocklists or dashboard suppression from this module. "
            "If API support is unavailable, any manual fallback needs a later explicit approval."
        ),
    }


def _trustpilot_automation_status(report, candidate_queue_status):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    eligible_count = _int_or_zero(data.get("eligible_candidate_count"))
    selected_order = _safe_text(data.get("selected_candidate_order_name"), max_length=80)
    automation_status = _safe_text(data.get("automation_status") or report.get("status") or "missing")
    report_present = bool(report.get("present"))
    report_loaded = bool(report.get("loaded"))
    if report_loaded and eligible_count > 0:
        message = (
            f"{eligible_count} order is ready for Trustpilot email dry-run. "
            "Review the locked send package before any real email is sent."
            if eligible_count == 1
            else (
                f"{eligible_count} orders are ready for Trustpilot email dry-run. "
                "Review the locked send package before any real email is sent."
            )
        )
        next_step = "Review the locked send package before any real email is sent."
    else:
        message = (
            "No Trustpilot email will be sent now. Waiting for an order that is delivered, "
            f"has {CANONICAL_REVIEW_REQUEST_TAG}, and has no duplicate/customer risk."
        )
        next_step = "Nothing to send now."
    order_22620 = (
        data.get("order_22620_blocker_status")
        if isinstance(data.get("order_22620_blocker_status"), dict)
        else {}
    )
    order_22582 = (
        data.get("order_22582_blocker_status")
        if isinstance(data.get("order_22582_blocker_status"), dict)
        else {}
    )
    return {
        "report_present": report_present,
        "report_loaded": report_loaded,
        "relative_path": _safe_text(report.get("relative_path") or "logs/shopify_review_request_trustpilot_automation_dry_run.json"),
        "status": automation_status,
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order,
        "selected_candidate_allowed_for_future_send": data.get("selected_candidate_allowed_for_future_send") is True,
        "message": message,
        "next_step": next_step,
        "order_22620_message": _safe_text(
            order_22620.get("message")
            or "Do not send. This customer already received a Trustpilot invitation via #22621.",
            max_length=300,
        ),
        "order_22582_message": _safe_text(
            order_22582.get("message")
            or (
                "Do not send yet. Order is not delivered, missing 1: review request, "
                "and related order group #22582/#22581 is not ready."
            ),
            max_length=300,
        ),
        "gmail_future_action_status": _safe_text(
            data.get("gmail_future_action_status") or "no_gmail_action_until_eligible_candidate"
        ),
        "shopify_tag_future_action_status": _safe_text(
            data.get("shopify_tag_future_action_status")
            or "no_shopify_tag_action_until_email_sent_and_verified"
        ),
        "ali_reviews_status": _safe_text(
            data.get("ali_reviews_status") or "blocked_waiting_for_vendor_api_documentation"
        ),
        "blocking_reason": _safe_text(
            data.get("blocking_reason") or candidate_queue_status.get("reason") or ""
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "raw_flags": {
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_draft_created": data.get("gmail_draft_created") is True,
            "email_sent": data.get("email_sent") is True,
            "trustpilot_api_call_performed": data.get("trustpilot_api_call_performed") is True,
            "kudosi_api_call_performed": data.get("kudosi_api_call_performed") is True,
            "ali_reviews_api_call_performed": data.get("ali_reviews_api_call_performed") is True,
        },
    }


def _trustpilot_send_readiness_status(report, trustpilot_automation_status):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    command_preview = data.get("future_locked_send_command_preview")
    command_preview = command_preview if isinstance(command_preview, dict) else {}
    order_22620 = data.get("order_22620_blocker_status") if isinstance(data.get("order_22620_blocker_status"), dict) else {}
    order_22582 = data.get("order_22582_blocker_status") if isinstance(data.get("order_22582_blocker_status"), dict) else {}
    report_loaded = bool(report.get("loaded"))
    eligible_count = _int_or_zero(data.get("eligible_candidate_count"))
    blocked_count = _int_or_zero(data.get("blocked_candidate_count"))
    package_status = _safe_text(data.get("package_status") or report.get("status") or "missing")
    if report_loaded:
        message = _safe_text(
            data.get("current_state_message")
            or "Nothing to send now. The automation is watching for delivered orders with `1: review request`.",
            max_length=300,
        )
    else:
        message = "No locked send readiness package has been generated yet."
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_locked_send_readiness_package.json"
        ),
        "status": package_status,
        "package_status": package_status,
        "message": message,
        "eligible_candidate_count": eligible_count,
        "blocked_candidate_count": blocked_count,
        "selected_candidate_order_name": _safe_text(
            data.get("selected_candidate_order_name"),
            max_length=80,
        ),
        "selected_candidate_safe_to_prepare_send": data.get("selected_candidate_safe_to_prepare_send") is True,
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or trustpilot_automation_status.get("next_step")
            or "Nothing to send now.",
            max_length=500,
        ),
        "future_locked_send_command": _safe_text(command_preview.get("command"), max_length=300),
        "future_locked_send_command_warning": _safe_text(command_preview.get("warning"), max_length=300),
        "order_22620_message": _safe_text(
            order_22620.get("message")
            or trustpilot_automation_status.get("order_22620_message")
            or "Do not send. Already sent to this customer via #22621.",
            max_length=300,
        ),
        "order_22582_message": _safe_text(
            order_22582.get("message")
            or trustpilot_automation_status.get("order_22582_message")
            or (
                "Do not send yet. Not delivered, missing `1: review request`, "
                "related order group #22582/#22581 not ready."
            ),
            max_length=300,
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "raw_flags": {
            "gmail_send_allowed_now": data.get("gmail_send_allowed_now") is True,
            "gmail_draft_create_allowed_now": data.get("gmail_draft_create_allowed_now") is True,
            "shopify_tag_write_allowed_now": data.get("shopify_tag_write_allowed_now") is True,
            "external_review_api_call_allowed_now": data.get("external_review_api_call_allowed_now") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_draft_created": data.get("gmail_draft_created") is True,
            "email_sent": data.get("email_sent") is True,
            "trustpilot_api_call_performed": data.get("trustpilot_api_call_performed") is True,
            "kudosi_api_call_performed": data.get("kudosi_api_call_performed") is True,
            "ali_reviews_api_call_performed": data.get("ali_reviews_api_call_performed") is True,
        },
    }


def _trustpilot_auto_refresh_status(report, trustpilot_send_readiness):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    dashboard_summary = data.get("dashboard_summary") if isinstance(data.get("dashboard_summary"), dict) else {}
    known_blockers = data.get("known_blockers_summary") if isinstance(data.get("known_blockers_summary"), list) else []
    blocker_by_order = {
        _safe_text(item.get("order_name"), max_length=80): item
        for item in known_blockers
        if isinstance(item, dict)
    }
    order_22620 = blocker_by_order.get("#22620") or {}
    order_22582 = blocker_by_order.get("#22582") or {}
    report_loaded = bool(report.get("loaded"))
    eligible_count = _int_or_zero(
        data.get("eligible_candidate_count")
        if report_loaded
        else trustpilot_send_readiness.get("eligible_candidate_count")
    )
    blocked_count = _int_or_zero(
        data.get("blocked_candidate_count")
        if report_loaded
        else trustpilot_send_readiness.get("blocked_candidate_count")
    )
    refresh_status = _safe_text(data.get("refresh_status") or report.get("status") or "missing")
    message = _safe_text(
        dashboard_summary.get("message")
        or (
            "Automation checked the queue. Nothing to send now."
            if report_loaded and eligible_count == 0
            else "No automation refresh report has been generated yet."
        ),
        max_length=300,
    )
    detail = _safe_text(
        dashboard_summary.get("detail")
        or f"Waiting for a delivered order with `{CANONICAL_REVIEW_REQUEST_TAG}` that passes all safety checks.",
        max_length=300,
    )
    scheduler_note = _safe_text(
        dashboard_summary.get("scheduler_note")
        or "This refresh is safe to run on a schedule because it does not send emails, create Gmail drafts, or write Shopify tags.",
        max_length=300,
    )
    last_trigger = _safe_text(
        data.get("last_auto_refresh_trigger") or data.get("trigger") or "unknown",
        max_length=80,
    )
    last_refresh_status = _safe_text(
        data.get("last_auto_refresh_status") or refresh_status,
        max_length=120,
    )
    last_refresh_at = _safe_text(
        data.get("last_auto_refresh_at")
        or data.get("refreshed_at")
        or report.get("timestamp")
        or report.get("modified_at"),
        max_length=120,
    )
    last_refresh_error = _safe_text(
        data.get("last_auto_refresh_error") or report.get("error", ""),
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_auto_queue_refresh.json"
        ),
        "refresh_status": refresh_status,
        "last_refresh_time": last_refresh_at,
        "last_auto_refresh_trigger": last_trigger,
        "last_auto_refresh_trigger_label": _auto_refresh_trigger_label(last_trigger),
        "last_auto_refresh_status": last_refresh_status,
        "last_auto_refresh_at": last_refresh_at,
        "last_auto_refresh_error": last_refresh_error,
        "auto_hook_invoked": data.get("auto_hook_invoked") is True,
        "hook_mode": _safe_text(data.get("hook_mode") or "post_sync_best_effort", max_length=80),
        "hook_safe_no_write": data.get("hook_safe_no_write") is not False,
        "hook_status": "enabled",
        "hook_status_message": "Auto refresh after Shopify sync is enabled",
        "hook_explainer": (
            "After Shopify order sync, this dashboard refreshes the Trustpilot review queue automatically. "
            "It does not send emails, create Gmail drafts, or write Shopify tags."
        ),
        "source_readiness_package_status": _safe_text(
            data.get("source_readiness_package_status")
            or trustpilot_send_readiness.get("package_status")
            or "missing",
            max_length=120,
        ),
        "eligible_candidate_count": eligible_count,
        "blocked_candidate_count": blocked_count,
        "selected_candidate_order_name": _safe_text(data.get("selected_candidate_order_name"), max_length=80),
        "next_real_step": _safe_text(data.get("next_real_step") or "wait_no_candidate", max_length=120),
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or trustpilot_send_readiness.get("next_admin_action")
            or "Nothing to send now.",
            max_length=500,
        ),
        "message": message,
        "detail": detail,
        "scheduler_note": scheduler_note,
        "auto_refresh_safe_for_scheduler": data.get("auto_refresh_safe_for_scheduler") is True,
        "scheduler_safe_status": (
            "Scheduler-safe dry run"
            if data.get("auto_refresh_safe_for_scheduler") is True
            else "No scheduler-safe refresh loaded"
        ),
        "order_22620_message": _safe_text(
            order_22620.get("message")
            or trustpilot_send_readiness.get("order_22620_message")
            or "Do not send. Already sent to this customer via #22621.",
            max_length=300,
        ),
        "order_22582_message": _safe_text(
            order_22582.get("message")
            or trustpilot_send_readiness.get("order_22582_message")
            or (
                "Do not send yet. Not delivered, missing `1: review request`, "
                "related order group #22582/#22581 not ready."
            ),
            max_length=300,
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "raw_flags": {
            "gmail_send_allowed_now": data.get("gmail_send_allowed_now") is True,
            "gmail_draft_create_allowed_now": data.get("gmail_draft_create_allowed_now") is True,
            "shopify_tag_write_allowed_now": data.get("shopify_tag_write_allowed_now") is True,
            "external_review_api_call_allowed_now": data.get("external_review_api_call_allowed_now") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_draft_created": data.get("gmail_draft_created") is True,
            "email_sent": data.get("email_sent") is True,
            "trustpilot_api_call_performed": data.get("trustpilot_api_call_performed") is True,
            "kudosi_api_call_performed": data.get("kudosi_api_call_performed") is True,
            "ali_reviews_api_call_performed": data.get("ali_reviews_api_call_performed") is True,
        },
    }


def _trustpilot_candidate_simulator_status(report):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    generated_fixture_reports = (
        data.get("generated_downstream_fixture_reports")
        if isinstance(data.get("generated_downstream_fixture_reports"), list)
        else []
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_candidate_simulator.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_candidate_simulator.html",
        "simulator_status": _safe_text(
            data.get("simulator_status") or report.get("status") or "missing",
            max_length=120,
        ),
        "simulator_mode": _safe_text(data.get("simulator_mode") or "no_candidate", max_length=80),
        "simulator_only": data.get("simulator_only") is True,
        "simulator_only_label": "Yes" if data.get("simulator_only") is True else "No",
        "real_customer_data_used": data.get("real_customer_data_used") is True,
        "real_customer_data_used_label": "Yes" if data.get("real_customer_data_used") is True else "No",
        "eligible_candidate_count": _int_or_zero(data.get("eligible_candidate_count")),
        "selected_candidate_order_name": _safe_text(data.get("selected_candidate_order_name"), max_length=80),
        "message": _safe_text(
            data.get("simulator_warning")
            or "Sandbox simulator is for testing only. It never uses real customer data and never sends emails.",
            max_length=300,
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "generated_downstream_fixture_reports": [
            {
                "key": _safe_text(item.get("key"), max_length=80),
                "relative_path": _safe_text(item.get("relative_path"), max_length=160),
                "present": item.get("present") is True,
            }
            for item in generated_fixture_reports
            if isinstance(item, dict)
        ],
        "raw_flags": {
            "simulator_only": data.get("simulator_only") is True,
            "real_customer_data_used": data.get("real_customer_data_used") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "email_sent": data.get("email_sent") is True,
            "shopify_api_call_performed": data.get("shopify_api_call_performed") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
        },
    }


def _trustpilot_gmail_send_gate_status(report, trustpilot_auto_refresh):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    known_blockers = data.get("known_blockers_summary") if isinstance(data.get("known_blockers_summary"), list) else []
    blocker_by_order = {
        _safe_text(item.get("order_name"), max_length=80): item
        for item in known_blockers
        if isinstance(item, dict)
    }
    order_22620 = blocker_by_order.get("#22620") or {}
    order_22582 = blocker_by_order.get("#22582") or {}
    report_loaded = bool(report.get("loaded"))
    eligible_count = _int_or_zero(
        data.get("eligible_candidate_count")
        if report_loaded
        else trustpilot_auto_refresh.get("eligible_candidate_count")
    )
    gate_status = _safe_text(data.get("gate_status") or report.get("status") or "missing", max_length=120)
    selected_order = _safe_text(data.get("selected_candidate_order_name"), max_length=80)
    send_allowed_now = data.get("send_allowed_now") is True
    draft_create_allowed_now = data.get("draft_create_allowed_now") is True
    gmail_api_allowed_now = data.get("gmail_api_allowed_now") is True
    current_message = _safe_text(
        data.get("current_state_message")
        or (
            "No email can be sent now. There is no eligible Trustpilot candidate."
            if eligible_count == 0
            else "No email can be sent now. Review the locked Gmail send gate."
        ),
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_locked_gmail_send_gate.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_locked_gmail_send_gate.html",
        "gate_status": gate_status,
        "message": current_message,
        "future_ack_message": _safe_text(
            data.get("future_ack_message")
            or "Future sending will require a locked ACK and exactly one safe candidate.",
            max_length=300,
        ),
        "send_allowed_now": send_allowed_now,
        "draft_create_allowed_now": draft_create_allowed_now,
        "gmail_api_allowed_now": gmail_api_allowed_now,
        "send_allowed_now_label": "Yes" if send_allowed_now else "No",
        "draft_create_allowed_now_label": "Yes" if draft_create_allowed_now else "No",
        "gmail_api_allowed_now_label": "Yes" if gmail_api_allowed_now else "No",
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order,
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or trustpilot_auto_refresh.get("next_admin_action")
            or "Wait until an eligible delivered order with canonical `1: review request` appears and passes all duplicate/risk checks.",
            max_length=500,
        ),
        "required_ack_for_future_real_send": _safe_text(
            data.get("required_ack_for_future_real_send")
            or "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK=YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND",
            max_length=180,
        ),
        "order_22620_message": _safe_text(
            order_22620.get("message")
            or trustpilot_auto_refresh.get("order_22620_message")
            or "Do not send. Already sent to this customer via #22621.",
            max_length=300,
        ),
        "order_22620_status": _safe_text(
            order_22620.get("status") or "blocked_existing_trustpilot_invitation_customer_level",
            max_length=120,
        ),
        "order_22582_message": _safe_text(
            order_22582.get("message")
            or trustpilot_auto_refresh.get("order_22582_message")
            or (
                "Do not send yet. Not delivered, missing `1: review request`, "
                "related order group #22582/#22581 not ready."
            ),
            max_length=300,
        ),
        "order_22582_status": _safe_text(
            order_22582.get("status") or "blocked_candidate_safety_check_failed",
            max_length=120,
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "source_gate_basis": data.get("source_gate_basis") if isinstance(data.get("source_gate_basis"), dict) else {},
        "raw_flags": {
            "send_allowed_now": send_allowed_now,
            "draft_create_allowed_now": draft_create_allowed_now,
            "gmail_api_allowed_now": gmail_api_allowed_now,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_draft_created": data.get("gmail_draft_created") is True,
            "email_sent": data.get("email_sent") is True,
            "trustpilot_api_call_performed": data.get("trustpilot_api_call_performed") is True,
            "kudosi_api_call_performed": data.get("kudosi_api_call_performed") is True,
            "ali_reviews_api_call_performed": data.get("ali_reviews_api_call_performed") is True,
        },
    }


def _trustpilot_gmail_send_executor_shell_status(report, trustpilot_gmail_send_gate):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    eligible_count = _int_or_zero(
        data.get("eligible_candidate_count")
        if report_loaded
        else trustpilot_gmail_send_gate.get("eligible_candidate_count")
    )
    executor_status = _safe_text(data.get("executor_status") or report.get("status") or "missing", max_length=120)
    gate_status = _safe_text(
        data.get("gate_status") or trustpilot_gmail_send_gate.get("gate_status") or "missing",
        max_length=120,
    )
    selected_order = _safe_text(
        data.get("selected_candidate_order_name")
        if report_loaded
        else trustpilot_gmail_send_gate.get("selected_candidate_order_name"),
        max_length=80,
    )
    ack_present = data.get("ack_present") is True
    future_allowed = data.get("future_real_send_allowed_if_implemented") is True
    current_message = _safe_text(
        data.get("current_state_message")
        or (
            "Send executor is installed but locked. No email can be sent because there is no eligible candidate."
            if eligible_count == 0
            else "Send executor is installed but locked. Review the no-send executor shell."
        ),
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_gmail_send_executor_shell.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_gmail_send_executor_shell.html",
        "executor_status": executor_status,
        "gate_status": gate_status,
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order,
        "ack_present": ack_present,
        "ack_present_label": "Yes" if ack_present else "No",
        "future_real_send_allowed_if_implemented": future_allowed,
        "future_real_send_allowed_if_implemented_label": "Yes" if future_allowed else "No",
        "gmail_send_performed": data.get("gmail_send_performed") is True,
        "gmail_send_performed_label": "Yes" if data.get("gmail_send_performed") is True else "No",
        "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
        "gmail_draft_create_performed_label": (
            "Yes" if data.get("gmail_draft_create_performed") is True else "No"
        ),
        "shopify_tag_write_performed": data.get("shopify_tag_write_performed") is True,
        "shopify_tag_write_performed_label": (
            "Yes" if data.get("shopify_tag_write_performed") is True else "No"
        ),
        "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
        "external_review_api_call_performed_label": (
            "Yes" if data.get("external_review_api_call_performed") is True else "No"
        ),
        "message": current_message,
        "future_send_message": _safe_text(
            data.get("future_send_message")
            or "Future real sending will require exactly one safe candidate and the locked ACK.",
            max_length=300,
        ),
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or "Wait until exactly one eligible delivered order with canonical `1: review request` passes all duplicate/risk checks and gate is ready.",
            max_length=500,
        ),
        "required_ack": _safe_text(
            data.get("required_ack")
            or "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK=YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND",
            max_length=180,
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "source_gate_report": data.get("source_gate_report") if isinstance(data.get("source_gate_report"), dict) else {},
        "raw_flags": {
            "future_real_send_allowed_if_implemented": future_allowed,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_send_performed": data.get("gmail_send_performed") is True,
            "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
            "gmail_draft_created": data.get("gmail_draft_created") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "shopify_tag_write_performed": data.get("shopify_tag_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
            "trustpilot_api_call_performed": data.get("trustpilot_api_call_performed") is True,
            "kudosi_api_call_performed": data.get("kudosi_api_call_performed") is True,
            "ali_reviews_api_call_performed": data.get("ali_reviews_api_call_performed") is True,
        },
    }


def _trustpilot_real_send_final_preflight_status(report, trustpilot_gmail_send_executor_shell):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    eligible_count = _int_or_zero(
        data.get("eligible_candidate_count")
        if report_loaded
        else trustpilot_gmail_send_executor_shell.get("eligible_candidate_count")
    )
    preflight_status = _safe_text(
        data.get("preflight_status") or report.get("status") or "missing",
        max_length=120,
    )
    selected_order = _safe_text(
        data.get("selected_candidate_order_name")
        if report_loaded
        else trustpilot_gmail_send_executor_shell.get("selected_candidate_order_name"),
        max_length=80,
    )
    gate_status = _safe_text(
        data.get("gate_status") or trustpilot_gmail_send_executor_shell.get("gate_status") or "missing",
        max_length=120,
    )
    executor_status = _safe_text(
        data.get("executor_status")
        or trustpilot_gmail_send_executor_shell.get("executor_status")
        or "missing",
        max_length=120,
    )
    production_reports_used = data.get("production_reports_used") is True if report_loaded else True
    simulator_reports_used = data.get("simulator_reports_used") is True
    ack_present = data.get("ack_present") is True
    real_send_allowed = data.get("real_send_execute_allowed_next_phase") is True
    current_message = _safe_text(
        data.get("current_state_message")
        or (
            "Real send preflight is blocked because there is no eligible Trustpilot candidate."
            if eligible_count == 0
            else "Real send preflight needs review before any future execute phase."
        ),
        max_length=300,
    )
    safety_message = _safe_text(
        data.get("safety_message")
        or "No email has been sent. No Gmail draft has been created. No Shopify tag has been written.",
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_real_send_final_preflight.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_real_send_final_preflight.html",
        "preflight_status": preflight_status,
        "message": current_message,
        "safety_message": safety_message,
        "production_reports_used": production_reports_used,
        "production_reports_used_label": "Yes" if production_reports_used else "No",
        "simulator_reports_used": simulator_reports_used,
        "simulator_reports_used_label": "Yes" if simulator_reports_used else "No",
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order,
        "gate_status": gate_status,
        "executor_status": executor_status,
        "ack_present": ack_present,
        "ack_present_label": "Yes" if ack_present else "No",
        "real_send_execute_allowed_next_phase": real_send_allowed,
        "real_send_execute_allowed_next_phase_label": "Yes" if real_send_allowed else "No",
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or (
                "Wait until auto refresh finds exactly one real eligible delivered order with canonical "
                "`1: review request`, no duplicate/risk blockers, then re-run final preflight."
            ),
            max_length=500,
        ),
        "auto_refresh_status": _safe_text(data.get("auto_refresh_status"), max_length=120),
        "readiness_status": _safe_text(data.get("readiness_status"), max_length=120),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "source_report_status": (
            data.get("source_report_status")
            if isinstance(data.get("source_report_status"), list)
            else []
        ),
        "raw_flags": {
            "production_reports_used": production_reports_used,
            "simulator_reports_used": simulator_reports_used,
            "real_send_execute_allowed_next_phase": real_send_allowed,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_send_performed": data.get("gmail_send_performed") is True,
            "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
            "gmail_draft_created": data.get("gmail_draft_created") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "shopify_tag_write_performed": data.get("shopify_tag_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
            "trustpilot_api_call_performed": data.get("trustpilot_api_call_performed") is True,
            "kudosi_api_call_performed": data.get("kudosi_api_call_performed") is True,
            "ali_reviews_api_call_performed": data.get("ali_reviews_api_call_performed") is True,
        },
    }


def _trustpilot_real_send_execute_status(report, trustpilot_real_send_final_preflight):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    eligible_count = _int_or_zero(
        data.get("eligible_candidate_count")
        if report_loaded
        else trustpilot_real_send_final_preflight.get("eligible_candidate_count")
    )
    execution_status = _safe_text(
        data.get("execution_status") or report.get("status") or "missing",
        max_length=120,
    )
    preflight_status = _safe_text(
        data.get("preflight_status")
        or trustpilot_real_send_final_preflight.get("preflight_status")
        or "missing",
        max_length=120,
    )
    selected_order = _safe_text(
        data.get("selected_candidate_order_name")
        if report_loaded
        else trustpilot_real_send_final_preflight.get("selected_candidate_order_name"),
        max_length=80,
    )
    production_preflight_used = data.get("production_preflight_used") is True if report_loaded else True
    simulator_used = data.get("simulator_used") is True
    ack_present = (
        data.get("ack_present") is True
        if report_loaded
        else trustpilot_real_send_final_preflight.get("ack_present") is True
    )
    real_send_execute_requested = data.get("real_send_execute_requested") is True
    allowed_by_preflight = data.get("real_send_execute_allowed_by_preflight") is True
    allowed_by_env = data.get("real_send_execute_allowed_by_env") is True
    current_message = _safe_text(
        data.get("current_state_message")
        or (
            "Real send execute is installed but locked. No email can be sent because final preflight is blocked."
            if preflight_status != "ready_for_real_send_execute_next_phase"
            else "Real send execute is installed but locked because the explicit execute flag is missing."
        ),
        max_length=300,
    )
    future_send_message = _safe_text(
        data.get("future_send_message")
        or (
            "Even when future conditions are ready, real sending requires an explicit execute flag "
            "and a separate implementation step."
        ),
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_real_send_execute.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_real_send_execute.html",
        "execution_status": execution_status,
        "preflight_status": preflight_status,
        "message": current_message,
        "future_send_message": future_send_message,
        "production_preflight_used": production_preflight_used,
        "production_preflight_used_label": "Yes" if production_preflight_used else "No",
        "simulator_used": simulator_used,
        "simulator_used_label": "Yes" if simulator_used else "No",
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order,
        "ack_present": ack_present,
        "ack_present_label": "Yes" if ack_present else "No",
        "real_send_execute_requested": real_send_execute_requested,
        "real_send_execute_requested_label": "Yes" if real_send_execute_requested else "No",
        "real_send_execute_allowed_by_preflight": allowed_by_preflight,
        "real_send_execute_allowed_by_preflight_label": "Yes" if allowed_by_preflight else "No",
        "real_send_execute_allowed_by_env": allowed_by_env,
        "real_send_execute_allowed_by_env_label": "Yes" if allowed_by_env else "No",
        "gmail_send_performed": data.get("gmail_send_performed") is True,
        "gmail_send_performed_label": "Yes" if data.get("gmail_send_performed") is True else "No",
        "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
        "gmail_api_call_performed_label": "Yes" if data.get("gmail_api_call_performed") is True else "No",
        "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
        "gmail_draft_create_performed_label": (
            "Yes" if data.get("gmail_draft_create_performed") is True else "No"
        ),
        "shopify_tag_write_performed": data.get("shopify_tag_write_performed") is True,
        "shopify_tag_write_performed_label": (
            "Yes" if data.get("shopify_tag_write_performed") is True else "No"
        ),
        "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
        "external_review_api_call_performed_label": (
            "Yes" if data.get("external_review_api_call_performed") is True else "No"
        ),
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or "Wait until final preflight reports exactly one real eligible candidate and `ready_for_real_send_execute_next_phase`.",
            max_length=500,
        ),
        "required_ack": _safe_text(
            data.get("required_ack")
            or trustpilot_real_send_final_preflight.get("required_ack")
            or "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK=YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND",
            max_length=180,
        ),
        "required_execute_flag": _safe_text(
            data.get("required_execute_flag")
            or "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE=YES_I_APPROVE_REAL_TRUSTPILOT_GMAIL_SEND",
            max_length=180,
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "source_preflight_report": (
            data.get("source_preflight_report")
            if isinstance(data.get("source_preflight_report"), dict)
            else {}
        ),
        "raw_flags": {
            "production_preflight_used": production_preflight_used,
            "simulator_used": simulator_used,
            "real_send_execute_requested": real_send_execute_requested,
            "real_send_execute_allowed_by_preflight": allowed_by_preflight,
            "real_send_execute_allowed_by_env": allowed_by_env,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_send_performed": data.get("gmail_send_performed") is True,
            "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
            "gmail_draft_created": data.get("gmail_draft_created") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "shopify_tag_write_performed": data.get("shopify_tag_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
            "trustpilot_api_call_performed": data.get("trustpilot_api_call_performed") is True,
            "kudosi_api_call_performed": data.get("kudosi_api_call_performed") is True,
            "ali_reviews_api_call_performed": data.get("ali_reviews_api_call_performed") is True,
        },
    }


def _trustpilot_gmail_real_send_readiness_audit_status(
    report,
    trustpilot_auto_refresh,
    trustpilot_real_send_final_preflight,
    trustpilot_real_send_execute,
):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    eligible_count = _int_or_zero(
        data.get("eligible_candidate_count")
        if report_loaded
        else trustpilot_real_send_execute.get("eligible_candidate_count")
    )
    readiness_status = _safe_text(
        data.get("readiness_audit_status") or report.get("status") or "missing",
        max_length=120,
    )
    latest_preflight_status = _safe_text(
        data.get("latest_preflight_status")
        or trustpilot_real_send_execute.get("preflight_status")
        or trustpilot_real_send_final_preflight.get("preflight_status")
        or "missing",
        max_length=120,
    )
    latest_execute_status = _safe_text(
        data.get("latest_execute_status")
        or trustpilot_real_send_execute.get("execution_status")
        or "missing",
        max_length=120,
    )
    latest_auto_refresh_status = _safe_text(
        data.get("latest_auto_refresh_status")
        or trustpilot_auto_refresh.get("refresh_status")
        or "missing",
        max_length=120,
    )
    selected_order = _safe_text(
        data.get("selected_candidate_order_name")
        if report_loaded
        else trustpilot_real_send_execute.get("selected_candidate_order_name"),
        max_length=80,
    )
    gmail_dependencies_importable = data.get("gmail_dependencies_importable") is True
    gmail_oauth_config_present = data.get("gmail_oauth_config_present") is True
    gmail_token_config_present = data.get("gmail_token_config_present") is True
    single_send_limit_enforced = data.get("single_send_limit_enforced") is True
    duplicate_suppression_required = data.get("duplicate_suppression_required") is not False
    raw_email_output_blocked = data.get("raw_email_output_blocked") is not False
    full_gmail_id_output_blocked = data.get("full_gmail_id_output_blocked") is not False
    dashboard_message = _safe_text(
        data.get("dashboard_message")
        or (
            "Gmail real-send implementation is not enabled yet. Current blocker: no eligible Trustpilot candidate."
            if eligible_count == 0
            else "Gmail real-send implementation is not enabled yet. Review the readiness audit."
        ),
        max_length=300,
    )
    safety_message = _safe_text(
        data.get("safety_message")
        or "No Gmail network call was made. No email was sent. No Shopify tag was written.",
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_gmail_real_send_readiness_audit.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_gmail_real_send_readiness_audit.html",
        "readiness_audit_status": readiness_status,
        "message": dashboard_message,
        "safety_message": safety_message,
        "gmail_dependencies_importable": gmail_dependencies_importable,
        "gmail_dependencies_status": _present_missing_label(gmail_dependencies_importable, report_loaded),
        "gmail_oauth_config_present": gmail_oauth_config_present,
        "gmail_oauth_config_status": _present_missing_label(gmail_oauth_config_present, report_loaded),
        "gmail_token_config_present": gmail_token_config_present,
        "gmail_token_config_status": _present_missing_label(gmail_token_config_present, report_loaded),
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order,
        "latest_auto_refresh_status": latest_auto_refresh_status,
        "latest_preflight_status": latest_preflight_status,
        "latest_execute_status": latest_execute_status,
        "single_send_limit_enforced": single_send_limit_enforced,
        "single_send_limit_status": _safe_text(
            data.get("single_send_limit_status") or "required_exactly_one_candidate_for_future_implementation",
            max_length=160,
        ),
        "single_send_limit_label": "Yes" if single_send_limit_enforced else "Required",
        "duplicate_suppression_required": duplicate_suppression_required,
        "duplicate_suppression_status": _safe_text(
            data.get("duplicate_suppression_status") or "required_before_any_future_send",
            max_length=160,
        ),
        "duplicate_suppression_label": "Required" if duplicate_suppression_required else "Missing",
        "raw_email_output_blocked": raw_email_output_blocked,
        "full_gmail_id_output_blocked": full_gmail_id_output_blocked,
        "privacy_masking_status": _safe_text(
            data.get("privacy_masking_status") or "raw_email_and_full_gmail_id_output_blocked",
            max_length=160,
        ),
        "privacy_checks_label": (
            "Pass" if raw_email_output_blocked and full_gmail_id_output_blocked else "Review"
        ),
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or (
                "Wait for exactly one real eligible candidate, then rerun final preflight and readiness audit "
                "before enabling real send implementation."
            ),
            max_length=500,
        ),
        "required_ack_name": _safe_text(
            data.get("required_ack_name")
            or _safe_text(trustpilot_real_send_execute.get("required_ack"), max_length=180).split("=", 1)[0]
            or "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK",
            max_length=120,
        ),
        "required_real_send_execute_flag_name": _safe_text(
            data.get("required_real_send_execute_flag_name")
            or _safe_text(trustpilot_real_send_execute.get("required_execute_flag"), max_length=180).split("=", 1)[0]
            or "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE",
            max_length=120,
        ),
        "current_blocking_conditions": (
            data.get("current_blocking_conditions")
            if isinstance(data.get("current_blocking_conditions"), list)
            else []
        ),
        "readiness_checklist": (
            data.get("readiness_checklist") if isinstance(data.get("readiness_checklist"), list) else []
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "raw_flags": {
            "gmail_network_call_performed": data.get("gmail_network_call_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_send_performed": data.get("gmail_send_performed") is True,
            "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
            "shopify_api_call_performed": data.get("shopify_api_call_performed") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "shopify_tag_write_performed": data.get("shopify_tag_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
            "raw_email_output_blocked": raw_email_output_blocked,
            "full_gmail_id_output_blocked": full_gmail_id_output_blocked,
        },
    }


def _trustpilot_gmail_oauth_config_helper_status(report, trustpilot_gmail_real_send_readiness_audit):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    config_status = _safe_text(
        data.get("config_helper_status") or report.get("status") or "missing",
        max_length=120,
    )
    dependencies_importable = data.get("gmail_dependencies_importable") is True
    gmail_oauth_config_status = _safe_text(data.get("gmail_oauth_config_status") or "missing", max_length=120)
    gmail_token_config_status = _safe_text(data.get("gmail_token_config_status") or "missing", max_length=120)
    from_configured = data.get("gmail_send_from_email_configured") is True
    client_secret_configured = data.get("gmail_oauth_client_secret_file_configured") is True
    client_secret_exists = data.get("gmail_oauth_client_secret_path_exists") is True
    token_configured = data.get("gmail_oauth_token_file_configured") is True
    token_exists = data.get("gmail_oauth_token_path_exists") is True
    scope_configured = data.get("gmail_required_scope_configured") is True
    scope_matches = data.get("gmail_required_scope_matches_expected") is True
    legacy_config_present = data.get("legacy_gmail_oauth_config_present") is True
    legacy_scope_compatibility = _safe_text(
        data.get("legacy_gmail_scope_compatibility") or "unknown",
        max_length=120,
    )
    scope_compatibility_result = _safe_text(
        data.get("gmail_scope_compatibility_result") or legacy_scope_compatibility,
        max_length=120,
    )
    gmail_send_scope_present = data.get("gmail_send_scope_present") is True
    gmail_compose_scope_present = data.get("gmail_compose_scope_present") is True
    required_scope = _safe_text(
        data.get("required_scope_expected") or "https://www.googleapis.com/auth/gmail.send",
        max_length=120,
    )
    required_ack_documented = data.get("required_ack_name_documented") is True
    required_execute_documented = data.get("required_execute_flag_name_documented") is True
    dashboard_message = _safe_text(
        data.get("dashboard_message")
        or "Gmail OAuth is not fully configured yet. No Gmail network call was made.",
        max_length=300,
    )
    safety_message = _safe_text(
        data.get("safety_message")
        or "Do not enable real sending until OAuth config, final preflight, and readiness audit all pass.",
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_gmail_oauth_config_helper.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_gmail_oauth_config_helper.html",
        "config_helper_status": config_status,
        "message": dashboard_message,
        "safety_message": safety_message,
        "gmail_dependencies_importable": dependencies_importable,
        "gmail_dependencies_status": _present_missing_label(dependencies_importable, report_loaded),
        "gmail_oauth_config_status": gmail_oauth_config_status,
        "gmail_token_config_status": gmail_token_config_status,
        "gmail_send_from_email_configured": from_configured,
        "gmail_send_from_email_configured_label": _yes_no_unknown(from_configured, report_loaded),
        "gmail_oauth_client_secret_file_configured": client_secret_configured,
        "gmail_oauth_client_secret_file_configured_label": _yes_no_unknown(
            client_secret_configured,
            report_loaded,
        ),
        "gmail_oauth_client_secret_path_exists": client_secret_exists,
        "gmail_oauth_client_secret_path_exists_label": _yes_no_unknown(client_secret_exists, report_loaded),
        "gmail_oauth_token_file_configured": token_configured,
        "gmail_oauth_token_file_configured_label": _yes_no_unknown(token_configured, report_loaded),
        "gmail_oauth_token_path_exists": token_exists,
        "gmail_oauth_token_path_exists_label": _yes_no_unknown(token_exists, report_loaded),
        "gmail_required_scope_configured": scope_configured,
        "gmail_required_scope_configured_label": _yes_no_unknown(scope_configured, report_loaded),
        "gmail_required_scope_matches_expected": scope_matches,
        "gmail_required_scope_matches_expected_label": _yes_no_unknown(scope_matches, report_loaded),
        "required_scope_expected": required_scope,
        "required_scope_status": _scope_status(scope_configured, scope_matches, report_loaded),
        "legacy_gmail_oauth_config_present": legacy_config_present,
        "legacy_gmail_oauth_config_present_label": _yes_no_unknown(legacy_config_present, report_loaded),
        "legacy_gmail_scope_compatibility": legacy_scope_compatibility,
        "gmail_scope_compatibility_result": scope_compatibility_result,
        "gmail_send_scope_present": gmail_send_scope_present,
        "gmail_compose_scope_present": gmail_compose_scope_present,
        "required_ack_name_documented": required_ack_documented,
        "required_ack_name_documented_label": _yes_no_unknown(required_ack_documented, report_loaded),
        "required_execute_flag_name_documented": required_execute_documented,
        "required_execute_flag_name_documented_label": _yes_no_unknown(required_execute_documented, report_loaded),
        "blocking_conditions": (
            data.get("blocking_conditions") if isinstance(data.get("blocking_conditions"), list) else []
        ),
        "setup_steps": data.get("setup_steps") if isinstance(data.get("setup_steps"), list) else [],
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or (
                "Configure Gmail OAuth client secret file path and token file path, then rerun the helper. "
                "Do not enable real send until final preflight and real-send readiness pass."
            ),
            max_length=500,
        ),
        "readiness_audit_status": _safe_text(
            trustpilot_gmail_real_send_readiness_audit.get("readiness_audit_status"),
            max_length=120,
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "privacy_scan_summary": (
            data.get("privacy_scan_summary") if isinstance(data.get("privacy_scan_summary"), dict) else {}
        ),
        "raw_flags": {
            "gmail_network_call_performed": data.get("gmail_network_call_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_send_performed": data.get("gmail_send_performed") is True,
            "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
            "token_file_read": data.get("token_file_read") is True,
            "credential_file_read": data.get("credential_file_read") is True,
            "secret_value_printed": data.get("secret_value_printed") is True,
            "shopify_api_call_performed": data.get("shopify_api_call_performed") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
        },
    }


def _trustpilot_gmail_config_compatibility_audit_status(report):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    status = _safe_text(
        data.get("compatibility_audit_status") or report.get("status") or "missing",
        max_length=120,
    )
    legacy_names = data.get("legacy_config_names_detected")
    new_names = data.get("new_config_names_detected")
    legacy_names = legacy_names if isinstance(legacy_names, list) else []
    new_names = new_names if isinstance(new_names, list) else []
    legacy_env = data.get("legacy_env_presence_summary") if isinstance(data.get("legacy_env_presence_summary"), dict) else {}
    new_env = data.get("new_env_presence_summary") if isinstance(data.get("new_env_presence_summary"), dict) else {}
    scope_compatibility = _safe_text(
        data.get("scope_compatibility_result")
        or legacy_env.get("scope_compatibility")
        or new_env.get("scope_compatibility")
        or "unknown",
        max_length=120,
    )
    legacy_env_config_present = (
        data.get("legacy_gmail_oauth_config_present") is True
        or legacy_env.get("legacy_gmail_oauth_config_present") is True
    )
    legacy_names_detected = bool(legacy_names)
    new_config_present = (
        data.get("new_gmail_file_path_config_present") is True
        or new_env.get("new_gmail_file_path_config_present") is True
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_gmail_config_compatibility_audit.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_gmail_config_compatibility_audit.html",
        "compatibility_audit_status": status,
        "previous_gmail_flow_detected": data.get("previous_gmail_flow_detected") is True,
        "previous_successful_send_reference_detected": data.get(
            "previous_successful_send_reference_detected"
        )
        is True,
        "legacy_config_detected": legacy_names_detected,
        "new_config_detected": new_config_present,
        "legacy_config_names_detected": [_safe_text(item, max_length=120) for item in legacy_names],
        "new_config_names_detected": [_safe_text(item, max_length=120) for item in new_names],
        "legacy_gmail_oauth_config_present": legacy_env_config_present,
        "new_gmail_file_path_config_present": new_config_present,
        "gmail_dependencies_importable": data.get("gmail_dependencies_importable") is True,
        "scope_compatibility_result": scope_compatibility,
        "gmail_send_scope_present": data.get("gmail_send_scope_present") is True
        or scope_compatibility == "send_scope_present",
        "gmail_compose_scope_present": data.get("gmail_compose_scope_present") is True
        or scope_compatibility == "compose_only_not_send_scope",
        "compatibility_recommendation": _safe_text(
            data.get("compatibility_recommendation"),
            max_length=500,
        ),
        "suggested_helper_change": _safe_text(data.get("suggested_helper_change"), max_length=500),
        "next_admin_action": _safe_text(data.get("next_admin_action"), max_length=500),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "privacy_scan_summary": (
            data.get("privacy_scan_summary") if isinstance(data.get("privacy_scan_summary"), dict) else {}
        ),
        "raw_flags": {
            "gmail_network_call_performed": data.get("gmail_network_call_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_send_performed": data.get("gmail_send_performed") is True,
            "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
            "token_file_read": data.get("token_file_read") is True,
            "credential_file_read": data.get("credential_file_read") is True,
            "secret_value_printed": data.get("secret_value_printed") is True,
        },
    }


def _present_missing_label(value, report_loaded):
    if not report_loaded:
        return "unknown"
    return "ready" if value else "missing"


def _yes_no_unknown(value, report_loaded):
    if not report_loaded:
        return "Unknown"
    return "Yes" if value else "No"


def _scope_status(configured, matches_expected, report_loaded):
    if not report_loaded:
        return "unknown"
    if not configured:
        return "missing"
    if not matches_expected:
        return "configured_wrong_scope"
    return "configured"


def _auto_refresh_trigger_label(trigger):
    if trigger == "shopify_order_sync":
        return "Shopify order sync"
    if trigger == "manual_runner":
        return "Manual runner"
    return "unknown"


def _operating_dashboard(
    latest_scan,
    candidate_queue,
    invitation_history,
    blocked_orders,
    history_ledger,
    trustpilot_email_records,
    ali_reviews_status,
    trustpilot_automation_status,
    trustpilot_send_readiness,
    trustpilot_auto_refresh,
    trustpilot_candidate_simulator,
    trustpilot_gmail_send_gate,
    trustpilot_gmail_send_executor_shell,
    trustpilot_real_send_final_preflight,
    trustpilot_real_send_execute,
    trustpilot_gmail_real_send_readiness_audit,
    trustpilot_gmail_oauth_config_helper,
    trustpilot_gmail_config_compatibility_audit,
):
    focus = history_ledger.get("focus") or {}
    summary = history_ledger.get("summary") or {}
    events = history_ledger.get("all_events") or []
    if trustpilot_auto_refresh.get("report_loaded"):
        ready_count = _int_or_zero(trustpilot_auto_refresh.get("eligible_candidate_count"))
        blocked_count = _int_or_zero(trustpilot_auto_refresh.get("blocked_candidate_count"))
    elif trustpilot_send_readiness.get("report_loaded"):
        ready_count = _int_or_zero(trustpilot_send_readiness.get("eligible_candidate_count"))
        blocked_count = _int_or_zero(trustpilot_send_readiness.get("blocked_candidate_count"))
    elif trustpilot_automation_status.get("report_loaded"):
        ready_count = _int_or_zero(trustpilot_automation_status.get("eligible_candidate_count"))
        blocked_count = _blocked_order_count(blocked_orders, summary, focus)
    else:
        ready_count = _ready_to_send_count(latest_scan, candidate_queue)
        blocked_count = _blocked_order_count(blocked_orders, summary, focus)
    sent_count = _trustpilot_sent_count(events, invitation_history, focus)
    gmail_setup = _gmail_setup_summary(
        trustpilot_gmail_oauth_config_helper,
        trustpilot_gmail_config_compatibility_audit,
    )
    return {
        "ready_to_send_count": ready_count,
        "blocked_count": blocked_count,
        "sent_trustpilot_count": sent_count,
        "current_state_label": (
            "Waiting for eligible orders" if ready_count == 0 else "Ready for final review"
        ),
        "status_cards": [
            {
                "label": "Ready to send",
                "value": _ready_to_send_value(ready_count),
                "message": _ready_to_send_message(ready_count),
                "tone": "info",
            },
            {
                "label": "Blocked orders",
                "value": _simple_order_count_text(blocked_count),
                "message": "These orders are not safe to send yet.",
                "tone": "warn",
            },
            {
                "label": "Gmail setup",
                "value": gmail_setup["status_value"],
                "message": gmail_setup["status_message"],
                "tone": "ok" if gmail_setup["ready"] else "warn",
            },
            {
                "label": "Sent Trustpilot emails",
                "value": str(sent_count),
                "message": "Already sent",
                "tone": "ok",
            },
        ],
        "next_action_headline": (
            "Nothing to send right now."
            if ready_count == 0
            else "Review the ready order before sending."
        ),
        "send_requirements": [
            "An order marked as delivered",
            f"The Shopify tag `{CANONICAL_REVIEW_REQUEST_TAG}`",
            "No previous Trustpilot email sent to the same customer",
            "Gmail setup completed",
        ],
        "current_blockers": _current_blockers(ready_count, gmail_setup["ready"]),
        "blocked_order_rows": _blocked_order_rows(
            focus=focus,
            blocked_orders=blocked_orders,
            trustpilot_email_records=trustpilot_email_records,
            invitation_history=invitation_history,
        ),
        "gmail_setup_ready": gmail_setup["ready"],
        "gmail_setup_status_value": gmail_setup["status_value"],
        "gmail_setup_message": gmail_setup["status_message"],
        "gmail_setup_rows": gmail_setup["rows"],
        "pipeline_steps": _pipeline_steps(ready_count),
        "trustpilot_automation": trustpilot_automation_status,
        "trustpilot_send_readiness": trustpilot_send_readiness,
        "trustpilot_auto_refresh": trustpilot_auto_refresh,
        "trustpilot_candidate_simulator": trustpilot_candidate_simulator,
        "trustpilot_gmail_send_gate": trustpilot_gmail_send_gate,
        "trustpilot_gmail_send_executor_shell": trustpilot_gmail_send_executor_shell,
        "trustpilot_real_send_final_preflight": trustpilot_real_send_final_preflight,
        "trustpilot_real_send_execute": trustpilot_real_send_execute,
        "trustpilot_gmail_real_send_readiness_audit": trustpilot_gmail_real_send_readiness_audit,
        "trustpilot_gmail_oauth_config_helper": trustpilot_gmail_oauth_config_helper,
        "trustpilot_gmail_config_compatibility_audit": trustpilot_gmail_config_compatibility_audit,
        "next_actions": _next_actions(focus, ready_count),
        "recent_activity": _recent_activity(
            focus=focus,
            trustpilot_email_records=trustpilot_email_records,
            blocked_orders=blocked_orders,
            invitation_history=invitation_history,
        ),
        "ali_reviews_message": (
            "Ali Reviews API is not connected yet. We are waiting for vendor API documentation "
            "for sending requests and checking request status."
        ),
        "ali_reviews_status_label": _admin_status_label(ali_reviews_status.get("status")),
    }


def _ready_to_send_value(count):
    if count == 0:
        return "0 orders"
    if count == 1:
        return "1 order"
    return "Multiple orders"


def _ready_to_send_message(count):
    if count == 0:
        return "Nothing to send now."
    if count == 1:
        return "Ready for final review before sending."
    return "Manual review needed."


def _simple_order_count_text(count):
    noun = "order" if count == 1 else "orders"
    return f"{count} {noun}"


def _ready_to_send_count(latest_scan, candidate_queue):
    selected = _safe_text(latest_scan.get("selected_order_name"), max_length=80)
    eligible_count = _int_or_zero(latest_scan.get("eligible_candidate_count"))
    blocked_reason = _safe_text(latest_scan.get("next_candidate_blocked_reason"), max_length=120)
    if eligible_count:
        return eligible_count
    if selected and not blocked_reason:
        return 1
    return len(candidate_queue)


def _blocked_order_count(blocked_orders, history_summary, focus):
    count = len(blocked_orders) or _history_event_count(
        history_summary,
        {"candidate_blocked", "duplicate_block"},
    )
    focus_count = 0
    if (focus.get("order_22620") or {}).get("blocked_confirmed"):
        focus_count += 1
    order_22582_classification = _safe_text(
        (focus.get("order_22582") or {}).get("blocked_classification"),
        max_length=120,
    )
    if order_22582_classification and order_22582_classification != "unavailable":
        focus_count += 1
    return max(count, focus_count)


def _trustpilot_sent_count(events, invitation_history, focus):
    sent_orders = {
        _safe_text(event.get("order_name"), max_length=80)
        for event in events
        if event.get("channel") == "trustpilot" and event.get("email_sent") is True
    }
    sent_orders.discard("")
    prior_order = _safe_text(
        (focus.get("order_22620") or {}).get("prior_trustpilot_order_name"),
        max_length=80,
    )
    if prior_order and prior_order != "unavailable":
        sent_orders.add(prior_order)
    return max(len(sent_orders), len(invitation_history))


def _order_count_text(count, suffix):
    noun = "order" if count == 1 else "orders"
    return f"{count} {noun} {suffix}"


def _gmail_setup_summary(gmail_helper, compatibility_audit=None):
    compatibility_audit = compatibility_audit or {}
    dependencies_ready = (
        gmail_helper.get("gmail_dependencies_importable") is True
        or compatibility_audit.get("gmail_dependencies_importable") is True
    )
    new_config_ready = (
        gmail_helper.get("gmail_send_from_email_configured") is True
        and gmail_helper.get("gmail_oauth_client_secret_path_exists") is True
        and gmail_helper.get("gmail_oauth_token_path_exists") is True
        and gmail_helper.get("gmail_required_scope_matches_expected") is True
    )
    legacy_config_detected = (
        gmail_helper.get("legacy_gmail_oauth_config_present") is True
        or compatibility_audit.get("legacy_gmail_oauth_config_present") is True
    )
    send_scope_present = (
        gmail_helper.get("gmail_send_scope_present") is True
        or compatibility_audit.get("gmail_send_scope_present") is True
    )
    compose_scope_present = (
        gmail_helper.get("gmail_compose_scope_present") is True
        or compatibility_audit.get("gmail_compose_scope_present") is True
    )
    ready = dependencies_ready and (new_config_ready or (legacy_config_detected and send_scope_present))
    required_scope = _safe_text(
        gmail_helper.get("required_scope_expected") or "https://www.googleapis.com/auth/gmail.send",
        max_length=120,
    )
    if legacy_config_detected and not send_scope_present and compose_scope_present:
        status_value = "Draft-only config"
        status_message = "Gmail can create drafts, but real sending may need gmail.send permission."
    elif legacy_config_detected:
        status_value = "Legacy config found"
        status_message = (
            "Gmail configuration was found from the older email flow. It still needs final "
            "send-scope verification before real sending."
        )
    elif ready:
        status_value = "Ready"
        status_message = "Gmail setup looks complete."
    else:
        status_value = "Setup needed"
        status_message = "Gmail setup is not complete yet."
    return {
        "ready": ready,
        "status_value": status_value,
        "status_message": status_message,
        "rows": [
            {
                "label": "Gmail tools installed",
                "value": _plain_yes_no(dependencies_ready),
            },
            {
                "label": "From email added",
                "value": _plain_yes_no(gmail_helper.get("gmail_send_from_email_configured") is True),
            },
            {
                "label": "Older Gmail config found",
                "value": _plain_yes_no(legacy_config_detected),
            },
            {
                "label": "Gmail login file added",
                "value": _plain_yes_no(gmail_helper.get("gmail_oauth_client_secret_path_exists") is True),
            },
            {
                "label": "Gmail token file added",
                "value": _plain_yes_no(gmail_helper.get("gmail_oauth_token_path_exists") is True),
            },
            {
                "label": "Required permission",
                "value": _gmail_permission_label(send_scope_present, compose_scope_present, required_scope),
            },
            {
                "label": "Compatibility audit",
                "value": _admin_status_label(
                    compatibility_audit.get("compatibility_audit_status") or "missing"
                ),
            },
        ],
    }


def _plain_yes_no(value):
    return "Yes" if value else "No"


def _gmail_permission_label(send_scope_present, compose_scope_present, required_scope):
    if send_scope_present:
        return "gmail.send"
    if compose_scope_present:
        return "gmail.compose only"
    return "gmail.send" if required_scope.endswith("/gmail.send") else required_scope


def _current_blockers(ready_count, gmail_ready):
    blockers = []
    if ready_count == 0:
        blockers.append("No eligible order is available.")
    if not gmail_ready:
        blockers.append("Gmail setup is not complete.")
    return blockers


def _blocked_order_rows(focus, blocked_orders, trustpilot_email_records, invitation_history):
    order_22620 = (focus.get("order_22620") or {}) if isinstance(focus, dict) else {}
    prior_order = _safe_text(order_22620.get("prior_trustpilot_order_name"), max_length=80)
    if not prior_order or prior_order == "unavailable":
        prior_order = "#22621"

    rows = [
        {
            "order": "#22620",
            "status": "Already sent to this customer",
            "status_class": "rrw-badge-bad",
            "reason": f"Do not send. This customer already received a Trustpilot email via {prior_order}.",
            "evidence": "Duplicate customer check",
        },
        {
            "order": "#22582",
            "status": "Related orders are not ready",
            "status_class": "rrw-badge-warn",
            "reason": (
                f"Do not send yet. This order is not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
                "and related orders #22582/#22581 are not ready."
            ),
            "evidence": "Delivery, tag, and related-order check",
        },
    ]

    seen_orders = {row["order"] for row in rows}
    for row in blocked_orders or []:
        order_name = _safe_text(row.get("order_name"), max_length=80)
        if not order_name or order_name in seen_orders:
            continue
        rows.append(
            {
                "order": order_name,
                "status": _plain_blocked_status(row),
                "status_class": "rrw-badge-warn",
                "reason": _plain_blocked_reason(row),
                "evidence": "Local safety check",
            }
        )
        seen_orders.add(order_name)
        if len(rows) >= 8:
            break

    return rows


def _plain_blocked_status(row):
    return _admin_status_label(
        row.get("status")
        or row.get("blocking_summary")
        or "blocked_candidate_safety_check_failed"
    )


def _plain_blocked_reason(row):
    text = " ".join(
        (
            _safe_text(row.get("status")),
            _safe_text(row.get("blocking_summary")),
        )
    )
    label = _admin_status_label(text)
    if label and label != "-":
        return label
    return "Do not send yet. This order needs manual review."


def _pipeline_steps(ready_count):
    return [
        {
            "number": 1,
            "label": "Order is delivered",
            "detail": "The order has reached the customer.",
            "state_label": "Needed",
            "state_class": "rrw-step-muted",
        },
        {
            "number": 2,
            "label": f"Staff adds `{CANONICAL_REVIEW_REQUEST_TAG}`",
            "detail": "Staff marks the order for a Trustpilot request.",
            "state_label": "Needed",
            "state_class": "rrw-step-muted",
        },
        {
            "number": 3,
            "label": "System checks for duplicates and risks",
            "detail": "Customers who already received an email stay blocked.",
            "state_label": "Checking",
            "state_class": "rrw-step-active",
        },
        {
            "number": 4,
            "label": "Gmail setup is checked",
            "detail": "The sender account must be connected first.",
            "state_label": "Setup needed",
            "state_class": "rrw-step-muted",
        },
        {
            "number": 5,
            "label": "Email can be reviewed before sending",
            "detail": "A staff member reviews the final email first.",
            "state_label": "Not ready" if ready_count == 0 else "Ready for review",
            "state_class": "rrw-step-muted",
        },
    ]


def _next_actions(focus, ready_count):
    prior_order = _safe_text(
        (focus.get("order_22620") or {}).get("prior_trustpilot_order_name"),
        max_length=80,
    )
    if not prior_order or prior_order == "unavailable":
        prior_order = "#22621"
    actions = []
    if ready_count == 0:
        actions.append(
            {
                "title": "Nothing to send right now",
                "description": "Wait for a delivered order with the review request tag and complete Gmail setup.",
                "items": [],
            }
        )
    else:
        actions.append(
            {
                "title": "Review the eligible order",
                "description": "Keep this page read-only. Draft and send actions are still locked.",
                "items": [],
            }
        )
    actions.extend(
        [
            {
                "title": "#22582 is not ready",
                "description": (
                    f"Do not send yet. This order is not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
                    "and related orders #22582/#22581 are not ready."
                ),
                "items": [
                    "Not delivered",
                    f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`",
                    "Related orders #22582/#22581 are not ready",
                ],
            },
            {
                "title": "#22620 should not be sent",
                "description": (
                    f"Do not send. This customer already received a Trustpilot email via {prior_order}."
                ),
                "items": [],
            },
            {
                "title": "Ali Reviews is still paused",
                "description": "Wait for vendor API documentation before any Ali Reviews automation.",
                "items": [],
            },
        ]
    )
    return actions


def _recent_activity(focus, trustpilot_email_records, blocked_orders, invitation_history):
    rows = []
    order_22620 = focus.get("order_22620") or {}
    order_22582 = focus.get("order_22582") or {}
    prior_order = _safe_text(order_22620.get("prior_trustpilot_order_name"), max_length=80)
    if not prior_order or prior_order == "unavailable":
        prior_order = "#22621"

    rows.append(
        {
            "order": prior_order,
            "customer": _masked_customer_for_order(
                prior_order,
                trustpilot_email_records,
                invitation_history,
                blocked_orders,
            ),
            "status": "Sent Trustpilot",
            "status_class": "rrw-badge-ok",
            "reason": "Trustpilot email already sent and recorded.",
            "last_evidence": "Send record found",
        }
    )
    rows.append(
        {
            "order": "#22620",
            "customer": _masked_customer_for_order(
                "#22620",
                trustpilot_email_records,
                invitation_history,
                blocked_orders,
            ),
            "status": "Already sent to this customer",
            "status_class": "rrw-badge-bad",
            "reason": (
                f"Do not send. This customer already received a Trustpilot email via {prior_order}."
            ),
            "last_evidence": "Duplicate customer check",
        }
    )
    rows.append(
        {
            "order": "#22582",
            "customer": _masked_customer_for_order(
                "#22582",
                trustpilot_email_records,
                invitation_history,
                blocked_orders,
            ),
            "status": "Not ready",
            "status_class": "rrw-badge-warn",
            "reason": (
                f"Do not send yet. This order is not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
                "and related orders #22582/#22581 are not ready."
            ),
            "last_evidence": "Delivery, tag, and related-order check",
        }
    )

    seen_orders = {row["order"] for row in rows}
    for record in trustpilot_email_records:
        order_name = _safe_text(record.get("order_name"), max_length=80)
        if not order_name or order_name in seen_orders:
            continue
        status_text = _admin_status_label(
            record.get("status") or record.get("classification") or record.get("event_type")
        )
        rows.append(
            {
                "order": order_name,
                "customer": record.get("masked_email") or "Masked in reports",
                "status": status_text,
                "status_class": record.get("badge_class") or "rrw-badge-info",
                "reason": _admin_status_label(
                    record.get("blocker_reason") or record.get("classification") or record.get("status")
                ),
                "last_evidence": "Local history record",
            }
        )
        seen_orders.add(order_name)
        if len(rows) >= 8:
            break
    return rows


def _masked_customer_for_order(order_name, *row_groups):
    for rows in row_groups:
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows or []:
            if row.get("order_name") == order_name or row.get("order") == order_name:
                masked = row.get("masked_email") or row.get("customer")
                if masked:
                    return _safe_text(masked, max_length=120)
    return "Masked in reports"


def _evidence_for_order(order_name, records, rows, focus_row):
    for row_group in (records, rows):
        for row in row_group or []:
            if row.get("order_name") == order_name or row.get("order") == order_name:
                return _record_evidence_label(row)
    if (focus_row or {}).get("evidence_available"):
        return "Local report evidence loaded"
    return "Current operating rule"


def _record_evidence_label(row):
    label = _safe_text(row.get("source_report_label") or row.get("source") or "Local report")
    event_time = _safe_text(row.get("event_time") or row.get("created_at"), max_length=80)
    if event_time:
        return f"{label} - {event_time}"
    return label


def _admin_status_label(value):
    text = _safe_text(value)
    if not text:
        return "-"
    lowered = text.lower()
    for key, label in ADMIN_STATUS_LABELS.items():
        if key in lowered:
            return label
    cleaned = text.replace("_", " ").strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "-"


def _current_next_candidate(latest_scan, candidate_queue, history_focus):
    next_candidate = latest_scan.get("selected_order_name") or (
        candidate_queue[0].get("order_name") if candidate_queue else ""
    )
    if next_candidate:
        return next_candidate
    focus_candidate = ((history_focus or {}).get("next_candidate") or {}).get("order_name", "")
    if focus_candidate and focus_candidate != "unavailable":
        return focus_candidate
    return ""


def _history_event_count(history_summary, event_types):
    count = 0
    for row in history_summary.get("by_event_type", []) or []:
        if row.get("key") in event_types:
            count += _int_or_zero(row.get("count"))
    return count


def _latest_source_update_time(source_reports):
    values = [
        _safe_text(report.get("modified_at") or report.get("timestamp"))
        for report in source_reports
        if report.get("modified_at") or report.get("timestamp")
    ]
    return max(values) if values else ""


def _is_trustpilot_email_record(event):
    return (
        event.get("event_type") in TRUSTPILOT_EMAIL_EVENT_TYPES
        or event.get("email_sent") is not None
        or event.get("gmail_draft_created") is not None
        or bool(event.get("partial_draft_id"))
        or bool(event.get("partial_message_id"))
        or bool(event.get("draft_should_not_be_sent"))
        or bool(event.get("prior_trustpilot_order_name"))
    )


def _event_matches_trustpilot_record_filters(event, filters):
    event_type = filters.get("event_type") or "all"
    if event_type != "all" and event.get("event_type") != event_type:
        return False
    query = (filters.get("q") or "").lower()
    if query and query not in _trustpilot_record_search_text(event):
        return False
    order_query = (filters.get("order") or "").lower()
    if order_query and order_query not in _safe_text(event.get("order_name")).lower():
        return False
    status_query = (filters.get("ledger_status") or "").lower()
    if status_query and status_query not in " ".join(
        (
            _safe_text(event.get("status")).lower(),
            _safe_text(event.get("classification")).lower(),
            _safe_text(event.get("blocker_reason")).lower(),
        )
    ):
        return False
    return True


def _trustpilot_record_search_text(event):
    return " ".join(
        _safe_text(event.get(key, "")).lower()
        for key in (
            "event_time",
            "source_report_path",
            "source_report_label",
            "source_section",
            "event_type",
            "order_name",
            "masked_email",
            "status",
            "classification",
            "blocker_reason",
            "partial_draft_id",
            "partial_message_id",
            "prior_trustpilot_order_name",
        )
    )


def _summary(
    latest_scan,
    candidate_queue,
    invitation_history,
    review_request_queue,
    blocked_orders,
    reports,
    local_stats,
    blocked_reason_counts,
):
    candidate_data = (reports.get("candidate_scan") or {}).get("data") or {}
    next_data = (reports.get("next_candidate_scan") or {}).get("data") or {}
    classification_counts = (
        candidate_data.get("classification_counts")
        if isinstance(candidate_data.get("classification_counts"), dict)
        else {}
    )
    blocked_counts = (
        next_data.get("blocked_counts")
        if isinstance(next_data.get("blocked_counts"), dict)
        else {}
    )
    total_candidate_like = (
        _int_or_zero(candidate_data.get("orders_queried"))
        or _int_or_zero(next_data.get("total_orders_evaluated"))
        or local_stats.get("orders_with_email", 0)
    )
    blocked_returned = (
        _int_or_zero(classification_counts.get("blocked_returned_package"))
        or _int_or_zero(blocked_counts.get("returned_package_tag_detected"))
        or _count_for_blocker(blocked_reason_counts, "returned_package")
    )
    blocked_duplicate = (
        _int_or_zero(blocked_counts.get("existing_trustpilot_invitation_tag_or_alias_detected"))
        or _int_or_zero(blocked_counts.get("blocked_existing_trustpilot_invitation_customer_level"))
        or _count_for_blocker(blocked_reason_counts, "duplicate_trustpilot_invitation")
        or _count_for_blocker(blocked_reason_counts, "customer_level_duplicate_trustpilot")
    )
    blocked_missing_delivered = _int_or_zero(blocked_counts.get("blocked_missing_delivered_tag")) or _count_for_blocker(
        blocked_reason_counts,
        "missing_delivered_tag",
    )
    blocked_missing_review_tag = _int_or_zero(
        blocked_counts.get("blocked_missing_review_request_tag")
    ) or _count_for_blocker(blocked_reason_counts, "missing_review_request_tag")
    blocked_merged_group = _int_or_zero(
        blocked_counts.get("blocked_merged_order_group_not_ready")
    ) or _count_for_blocker(blocked_reason_counts, "merged_order_group_not_ready")
    next_candidate = latest_scan.get("selected_order_name") or (
        candidate_queue[0]["order_name"] if candidate_queue else ""
    )
    next_candidate_email = latest_scan.get("selected_masked_email") or (
        candidate_queue[0]["masked_email"] if candidate_queue else ""
    )
    return [
        {
            "label": "Candidate-like orders",
            "value": total_candidate_like,
            "note": "From latest scan report, else local orders with email.",
        },
        {
            "label": "Trustpilot sent/tagged",
            "value": len(invitation_history),
            "note": "Detected from Trustpilot alias tags in local reports.",
        },
        {
            "label": f"Canonical {CANONICAL_REVIEW_REQUEST_TAG}",
            "value": len(review_request_queue),
            "note": f"Exact canonical tag only; {TYPO_REVIEW_REQUEST_TAG} is listed separately as typo/not canonical.",
        },
        {
            "label": "Missing delivered",
            "value": blocked_missing_delivered,
            "note": "Trustpilot candidates now require Delivered / 妥投 before packaging.",
        },
        {
            "label": "Missing review tag",
            "value": blocked_missing_review_tag,
            "note": f"Trustpilot candidates now require exact {CANONICAL_REVIEW_REQUEST_TAG}.",
        },
        {
            "label": "Merged group blocked",
            "value": blocked_merged_group,
            "note": "Related or merged order groups must be fully ready.",
        },
        {
            "label": "Blocked returned package",
            "value": blocked_returned,
            "note": "From scan classification or blocking reasons if available.",
        },
        {
            "label": "Blocked duplicate Trustpilot",
            "value": blocked_duplicate,
            "note": "Trustpilot invitation alias already present.",
        },
        {
            "label": "Next candidate",
            "value": next_candidate or "None",
            "note": next_candidate_email or "No selected candidate in latest report.",
        },
    ]


def _count_for_blocker(blocked_reason_counts, key):
    for item in blocked_reason_counts:
        if item.get("key") == key:
            return item.get("count", 0)
    return 0


def _tracking_design():
    return {
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "limitations": (
            "Gmail alone cannot reliably confirm whether a customer clicked a "
            "Trustpilot link or left a review.",
        ),
        "future_click_tracking": (
            "A future write phase could create a local invitation record and a "
            "unique redirect token per invitation. That redirect route is not "
            "enabled in Phase 5.3."
        ),
        "future_review_detection": (
            "A future phase would need Trustpilot Business/API/export support "
            "or Kudosi/Ali Reviews API, webhook, or export support to detect "
            "reviews."
        ),
        "future_statuses": FUTURE_TRACKING_STATUSES,
    }


def _current_page_safety_confirmations():
    return [
        {"name": "shopify_write_performed", "value": False},
        {"name": "mutation_performed", "value": False},
        {"name": "tags_add_performed", "value": False},
        {"name": "tags_remove_performed", "value": False},
        {"name": "gmail_api_call_performed", "value": False},
        {"name": "gmail_draft_create_attempted", "value": False},
        {"name": "gmail_draft_created", "value": False},
        {"name": "gmail_drafts_send_called", "value": False},
        {"name": "gmail_messages_send_called", "value": False},
        {"name": "gmail_send_performed", "value": False},
        {"name": "gmail_draft_deleted", "value": False},
        {"name": "email_sent", "value": False},
        {"name": "kudosi_api_call_performed", "value": False},
        {"name": "ali_reviews_api_call_performed", "value": False},
        {"name": "ali_reviews_write_api_call_performed", "value": False},
        {"name": "trustpilot_api_call_performed", "value": False},
        {"name": "tracking_redirect_enabled", "value": False},
        {"name": "tracking_token_generated", "value": False},
    ]


def _collect_tags(item):
    tags = []
    for key in (
        "tags",
        "tags_of_interest",
        "matched_trustpilot_invitation_tags",
        "customer_history_tags",
        "customer_order_tags",
        "historical_order_tags",
        "exact_tags_of_interest",
    ):
        tags.extend(_collect_tag_values(item.get(key), split_strings=(key == "tags")))

    for dict_key in ("safe_tags_summary", "tags_summary"):
        summary = item.get(dict_key)
        if not isinstance(summary, dict):
            continue
        for key in (
            "safe_tags",
            "tags_of_interest",
            "exact_tags_of_interest",
            "matched_trustpilot_invitation_tags",
        ):
            tags.extend(_collect_tag_values(summary.get(key)))
    return _dedupe_text(tags)


def _collect_tag_values(value, split_strings=False):
    if value is None:
        return []
    if isinstance(value, str):
        values = value.split(",") if split_strings else [value]
        return [_safe_tag(item) for item in values if _safe_tag(item)]
    if isinstance(value, (list, tuple, set)):
        return [_safe_tag(item) for item in value if _safe_tag(item)]
    return []


def _matched_trustpilot_tags(item, tags):
    normalized_aliases = {_normalize_trustpilot_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    matches = [
        tag
        for tag in tags
        if _normalize_trustpilot_tag(tag) in normalized_aliases
    ]
    for key in ("matched_trustpilot_invitation_tags",):
        matches.extend(_collect_string_list(item, key))
    for key in (
        "existing_trustpilot_invitation_tag_detected",
        "customer_historical_trustpilot_tag_detected",
        "contains_trustpilot_alias",
    ):
        if item.get(key) is True:
            matches.append(key)
    for dict_key in ("safe_tags_summary", "tags_summary"):
        summary = item.get(dict_key)
        if isinstance(summary, dict) and summary.get("contains_trustpilot_alias") is True:
            matches.append("contains_trustpilot_alias")
    return _dedupe_text(matches)


def _normalize_trustpilot_tag(tag):
    return re.sub(r"\s+", "", str(tag or "").strip().lower())


def _collect_string_list(item, key):
    value = item.get(key)
    if isinstance(value, str):
        return [_safe_text(value)] if value else []
    if isinstance(value, (list, tuple, set)):
        return [_safe_text(item) for item in value if _safe_text(item)]
    return []


def _first_text(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _safe_text(value)
    return ""


def _safe_tag(value):
    return _sanitize_text(value, max_length=120)


def _safe_text(value, max_length=300):
    return _sanitize_text(value, max_length=max_length)


def _sanitize_text(value, max_length=300):
    text = str(value or "")
    text = CONTROL_CHARS_RE.sub("", text)
    text = EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = text.strip()
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def _int_or_zero(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe_text(values):
    seen = set()
    result = []
    for value in values:
        text = _safe_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _dedupe_rows(rows):
    seen = set()
    result = []
    for row in rows:
        if not row:
            continue
        key = (
            row.get("order_name") or "",
            row.get("order_id") or "",
            row.get("source_section") or "",
            row.get("status") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result
