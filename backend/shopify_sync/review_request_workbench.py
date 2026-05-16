import json
import re
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from .review_request_history_ledger import build_review_request_history_ledger
from .models import ShopifyOrder, ShopifySyncState


CANONICAL_REVIEW_REQUEST_TAG = "1: review request"
TYPO_REVIEW_REQUEST_TAG = "1: reveiw request"
REVIEW_REQUEST_TAG_ALIASES = (
    CANONICAL_REVIEW_REQUEST_TAG,
    TYPO_REVIEW_REQUEST_TAG,
    "1:review request",
    "1 : review request",
    "1:reveiw request",
    "1 : reveiw request",
)
DELIVERED_TAG = "Delivered"
DELIVERED_TAG_ALIASES = (
    "Delivered",
    "delivered",
)
TRUSTPILOT_TAG_ALIASES = (
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
)
MANUAL_CONFIRMED_ORDER_EVIDENCE = {
    "#22562": {
        "order_name": "#22562",
        "source": "User-confirmed Shopify UI evidence",
        "source_section": "manual_confirmed_shopify_ui_evidence",
        "tags": [TYPO_REVIEW_REQUEST_TAG, DELIVERED_TAG, "express"],
        "delivered_tag_present": True,
        "canonical_review_request_tag_present": True,
        "review_request_tag_present": True,
        "matched_review_request_tag_value": TYPO_REVIEW_REQUEST_TAG,
        "eligible_for_trustpilot": True,
        "repeat_customer_detected": True,
        "customer_order_count": 2,
        "explicit_merge_evidence": False,
        "explicit_related_order_names": [],
        "related_order_names": [],
        "reason": "User confirmed Shopify UI tags for #22562; no explicit merge evidence was provided.",
    },
}
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
TRUSTPILOT_AUTO_REFRESH_REPORT_FILENAME = "shopify_review_request_trustpilot_auto_queue_refresh.json"
TRUSTPILOT_AUTO_REFRESH_HTML_FILENAME = "shopify_review_request_trustpilot_auto_queue_refresh.html"
REVIEW_AND_SEND_REPORT_FILENAME = "shopify_review_request_trustpilot_review_and_send_execute.json"
REVIEW_AND_SEND_HTML_FILENAME = "shopify_review_request_trustpilot_review_and_send_execute.html"
TRUSTPILOT_EMAIL_SUBJECT = "How was your Kidstoylover order?"
GMAIL_SEND_FROM = "info@kidstoylover.com"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_BROAD_SCOPE = "https://mail.google.com/"
LAST_60_DAY_SCAN_WINDOW_DAYS = 60
LAST_60_DAY_SCAN_TASK_NAME = "shopify_review_request_last_60_days_candidate_scan"
REVIEW_REQUEST_ORDER_SYNC_TASK_NAMES = (
    "orders_review_request_3",
    "orders_review_request_60",
    "orders_review_request_manual",
)
REVIEW_REQUEST_FOCUS_ORDER_NAMES = ("#22530", "#22562", "#22581", "#22582", "#22620", "#22621")
SHOPIFY_ORDER_TAGS_MISSING_SOURCE = "Shopify tags not stored in local ShopifyOrder model"
SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION = (
    "Update sync/model/report source to persist tags, or derive tags from an available local report source."
)
MERGED_ORDER_REFERENCE_RE = re.compile(r"#?\d{3,}")
MERGED_ORDER_KEYWORDS = (
    "combined",
    "merged",
    "same shipment",
    "shipped together",
    "ship together",
    "combined shipment",
    "\u5408\u5e76",
    "\u5408\u5e76\u53d1\u8d27",
    "合并",
    "合并发货",
)
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
    "scope_missing": "Gmail permission missing",
    "blocked_missing_requirements": "Setup not complete",
    "blocked_existing_trustpilot_invitation_tag": "Already sent to this order",
    "blocked_existing_trustpilot_invitation_customer_level": "Already sent to this customer",
    "blocked_missing_delivered_tag": "Not delivered yet",
    "blocked_missing_review_request_tag": "Missing review request tag",
    "blocked_merged_order_group_not_ready": "Related orders are not ready",
    "blocked_no_eligible_candidate": "No order ready",
    "blocked_missing_gmail_oauth_config": "Gmail setup is missing",
    "blocked_missing_ack": "Waiting for final approval",
    "blocked_multiple_candidates_require_manual_selection": "More than one order needs review",
    "blocked_candidate_safety_check_failed": "Safety check failed",
    "blocked_missing_vendor_api_documentation": "Waiting for API docs",
    "no_eligible_delivered_review_request_candidate": "No orders ready",
    "env_file_has_gmail_scope_but_runner_env_missing": "Runner cannot see .env Gmail settings",
    "env_file_loaded_but_scope_still_missing": "Gmail permission missing",
    "gmail_scope_loaded_but_unrecognized": "Gmail permission unrecognized",
    "gmail_scope_not_configured_anywhere_detected": "Gmail permission missing",
    "gmail_compose_scope_available_in_runner_env": "Gmail draft permission available",
    "gmail_send_scope_available_in_runner_env": "Gmail send permission available",
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
        "last_60_days_candidate_scan",
        "Last 60 days candidate scan",
        "shopify_review_request_last_60_days_candidate_scan.json",
        ("report_status", "status"),
    ),
    (
        "shopify_order_sync_coverage",
        "Shopify order sync coverage",
        "shopify_review_request_shopify_order_sync_coverage.json",
        ("report_status", "coverage_status", "status"),
    ),
    (
        "tag_alias_and_candidate_correction_audit",
        "Review-request tag alias and #22562 correction audit",
        "shopify_review_request_tag_alias_and_candidate_correction_audit.json",
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
        "trustpilot_gmail_env_loading_audit",
        "Trustpilot Gmail env loading audit",
        "shopify_review_request_trustpilot_gmail_env_loading_audit.json",
        ("env_loading_audit_status", "audit_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_scope_compatibility_resolver",
        "Trustpilot Gmail scope compatibility resolver",
        "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json",
        ("scope_resolver_status", "scope_compatibility_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_draft_only_preflight",
        "Trustpilot Gmail draft-only preflight",
        "shopify_review_request_trustpilot_gmail_draft_only_preflight.json",
        ("draft_preflight_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_one_draft_create_locked_runner",
        "Trustpilot Gmail one-draft create locked runner",
        "shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.json",
        ("locked_runner_status", "report_status", "status"),
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
        "trustpilot_review_and_send_execute",
        "Trustpilot Review & Send execute",
        REVIEW_AND_SEND_REPORT_FILENAME,
        ("execution_status", "report_status", "status"),
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
    "draft_only_preflight",
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
    trustpilot_gmail_env_loading_audit = _trustpilot_gmail_env_loading_audit_status(
        reports.get("trustpilot_gmail_env_loading_audit", {}),
    )
    trustpilot_gmail_scope_compatibility_resolver = _trustpilot_gmail_scope_compatibility_resolver_status(
        reports.get("trustpilot_gmail_scope_compatibility_resolver", {}),
    )
    trustpilot_gmail_draft_only_preflight = _trustpilot_gmail_draft_only_preflight_status(
        reports.get("trustpilot_gmail_draft_only_preflight", {}),
        trustpilot_gmail_scope_compatibility_resolver,
        trustpilot_auto_refresh,
        trustpilot_send_readiness,
    )
    trustpilot_gmail_one_draft_create_locked_runner = (
        _trustpilot_gmail_one_draft_create_locked_runner_status(
            reports.get("trustpilot_gmail_one_draft_create_locked_runner", {}),
            trustpilot_gmail_draft_only_preflight,
            trustpilot_gmail_scope_compatibility_resolver,
        )
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
        all_rows=all_rows,
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
        trustpilot_gmail_env_loading_audit=trustpilot_gmail_env_loading_audit,
        trustpilot_gmail_scope_compatibility_resolver=trustpilot_gmail_scope_compatibility_resolver,
        trustpilot_gmail_draft_only_preflight=trustpilot_gmail_draft_only_preflight,
        trustpilot_gmail_one_draft_create_locked_runner=trustpilot_gmail_one_draft_create_locked_runner,
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
            "trustpilot_gmail_env_loading_audit": trustpilot_gmail_env_loading_audit,
            "trustpilot_gmail_scope_compatibility_resolver": trustpilot_gmail_scope_compatibility_resolver,
            "trustpilot_gmail_draft_only_preflight": trustpilot_gmail_draft_only_preflight,
            "trustpilot_gmail_one_draft_create_locked_runner": trustpilot_gmail_one_draft_create_locked_runner,
            "trustpilot_email_records": trustpilot_email_records,
            "ali_reviews_status": ali_reviews_status,
            "trustpilot_aliases": TRUSTPILOT_TAG_ALIASES,
            "review_request_tag_aliases": REVIEW_REQUEST_TAG_ALIASES,
            "delivered_tag_aliases": DELIVERED_TAG_ALIASES,
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


def review_request_review_and_send(order_identifier, admin_username=""):
    state = _build_review_send_state()
    selected_order = _safe_text(order_identifier, max_length=80)
    result = _base_review_and_send_result(selected_order, admin_username, state)
    selected_rows = _review_send_selected_rows(state["approval_queue"], selected_order)
    matches = [
        row
        for row in state["approval_queue"]["needs_review_rows"]
        if row.get("candidate_id") == selected_order and row.get("action_state") == "review_send"
    ]
    if len(matches) != 1:
        blocker = _review_send_selection_blocker(selected_order, selected_rows)
        result["execution_status"] = blocker["status"]
        result["blocking_detail"] = blocker["detail"]
        result["blocking_conditions"].append(blocker)
        return _finalize_review_and_send_result(result)

    candidate = matches[0]
    result["candidate_verified"] = True
    result["selected_order"] = candidate["order"]
    result["selected_customer"] = candidate["customer"]
    result["selected_merged_group_order_names"] = candidate.get("group_order_names") or []
    result["selected_merged_group_size"] = _int_or_zero(candidate.get("group_size"))
    result["selected_merged_group_eligible_for_review_send"] = (
        candidate.get("group_eligible_for_review_send") is True
    )
    result["selected_merged_group_block_reasons"] = candidate.get("group_block_reasons") or []
    result["selected_merged_group_prior_trustpilot_sent"] = (
        candidate.get("group_prior_trustpilot_sent") is True
    )
    result["gmail_scope_status"] = state["gmail_setup"]["scope_status"]
    result["gmail_compose_send_supported"] = bool(
        state["gmail_setup"]["gmail_compose_send_supported"]
    )
    result["template_status"] = "approved_trustpilot_template"
    result["template_subject"] = TRUSTPILOT_EMAIL_SUBJECT

    group_blockers = _runtime_review_send_group_blockers(candidate)
    if group_blockers:
        result["execution_status"] = group_blockers[0]["status"]
        result["blocking_detail"] = group_blockers[0]["detail"]
        result["blocking_conditions"].extend(group_blockers)
        return _finalize_review_and_send_result(result)

    runtime_blockers = _runtime_review_send_blockers(candidate, state["gmail_setup"])
    if runtime_blockers:
        result["execution_status"] = runtime_blockers[0]["status"]
        result["blocking_detail"] = runtime_blockers[0]["detail"]
        result["blocking_conditions"].extend(runtime_blockers)
        return _finalize_review_and_send_result(result)

    result["execution_status"] = "blocked_phase_5_28a_scan_ui_report_only"
    result["blocking_status"] = "blocked_phase_5_28a_scan_ui_report_only"
    result["blocking_detail"] = (
        "No email was sent. Phase 5.28A is scan/UI/report only; Gmail draft and send paths are disabled."
    )
    result["blocking_conditions"].append(
        {
            "status": "blocked_phase_5_28a_scan_ui_report_only",
            "detail": result["blocking_detail"],
        }
    )
    result["next_admin_action"] = "Review the candidate on the page; sending remains locked."
    return _finalize_review_and_send_result(result)


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
        "Wait until an order is delivered, has a review-request tag alias, and passes "
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
        "explicit_related_order_names": [],
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
    review_request_tags = _matched_review_request_tags(tags)
    delivered_tags = _matched_delivered_tags(tags)
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

    explicit_related_order_names = _explicit_related_order_names_from_mapping(item)
    related_order_names = _related_order_names_from_mapping(item)
    return {
        "order_name": order_name or order_id,
        "order_id": order_id,
        "masked_email": mask_email(masked_email),
        "customer_display_name": _safe_text(
            _first_text(item, ("customer_display_name", "customer_name", "shipping_name")),
            max_length=120,
        ),
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
        "delivered_tag_present": item.get("delivered_tag_present") is True or bool(delivered_tags) or "妥投" in tags,
        "canonical_review_request_tag_present": (
            item.get("canonical_review_request_tag_present") is True or bool(review_request_tags)
        ),
        "matched_review_request_tag_value": review_request_tags[0] if review_request_tags else "",
        "typo_review_request_tag_present": bool(
            _matched_tag_alias_values(tags, (TYPO_REVIEW_REQUEST_TAG, "1:reveiw request", "1 : reveiw request"))
        ),
        "review_request_tag_present": item.get("review_request_tag_present") is True
        or item.get("canonical_review_request_tag_present") is True
        or bool(review_request_tags),
        "merged_or_related_order_guard_status": _safe_text(item.get("merged_or_related_order_guard_status")),
        "explicit_related_order_names": explicit_related_order_names,
        "related_order_names": related_order_names,
        "related_order_count": _int_or_zero(item.get("related_order_count")),
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
        "customer_order_count": _source_customer_order_count(item),
        "existing_unsent_gmail_draft_should_not_be_sent": (
            item.get("existing_unsent_gmail_draft_should_not_be_sent") is True
        ),
    }


def _explicit_related_order_names_from_mapping(item):
    names = []
    for key in (
        "verified_related_order_names",
        "verified_merged_order_names",
        "explicit_merged_order_names",
    ):
        names.extend(_collect_order_name_values(item.get(key)))
    if not _row_has_explicit_merge_evidence(item):
        return _dedupe_order_names(names)
    for key in (
        "related_order_names",
        "related_orders",
        "merged_order_names",
        "merged_order_group_order_names",
        "merged_group_order_names",
        "group_order_names",
        "explicit_related_order_names",
    ):
        names.extend(_collect_order_name_values(item.get(key)))
    for key in _MERGE_EVIDENCE_TEXT_KEYS:
        names.extend(_merged_order_names_from_text(item.get(key)))
    return _dedupe_order_names(names)


def _related_order_names_from_mapping(item):
    names = []
    for key in (
        "related_order_names",
        "related_orders",
        "merged_order_names",
        "merged_order_group_order_names",
        "merged_group_order_names",
        "group_order_names",
        "customer_order_names",
    ):
        names.extend(_collect_order_name_values(item.get(key)))
    return _dedupe_order_names(names)


def _collect_order_name_values(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        names = []
        for item in value:
            names.extend(_collect_order_name_values(item))
        return names
    text = _safe_text(value, max_length=500)
    if not text:
        return []
    numeric_names = re.findall(r"#?\d{3,}", text)
    if numeric_names:
        return [
            _canonical_order_name(name)
            for name in numeric_names
        ]
    return [_safe_text(part, max_length=80) for part in re.split(r"[,/|]+", text) if _safe_text(part, max_length=80)]


def _merged_order_names_from_text(value):
    text = _safe_text(value, max_length=1000)
    if not text or not _has_merged_order_keyword(text):
        return []
    return [_canonical_order_name(match) for match in MERGED_ORDER_REFERENCE_RE.findall(text)]


def _has_merged_order_keyword(value):
    text = _safe_text(value, max_length=1000).lower()
    return any(keyword in text for keyword in MERGED_ORDER_KEYWORDS)


_MERGE_EVIDENCE_TEXT_KEYS = (
    "evidence",
    "merge_evidence",
    "merged_group_evidence",
    "merged_order_evidence",
    "related_order_evidence",
    "order_note",
    "staff_note",
    "shopify_note",
    "warehouse_note",
    "transfer_note",
)


def _row_has_explicit_merge_evidence(row):
    if not isinstance(row, dict):
        return False
    for key in (
        "explicit_merge_evidence",
        "explicit_merge_evidence_present",
        "verified_related_order_evidence",
        "verified_merged_order_evidence",
    ):
        if row.get(key) is True:
            return True
    for key in (
        "verified_related_order_names",
        "verified_merged_order_names",
        "explicit_merged_order_names",
    ):
        names = _collect_order_name_values(row.get(key))
        own_order = _canonical_order_name(
            row.get("order")
            or row.get("order_name")
            or row.get("selected_order")
            or row.get("selected_order_name")
        )
        if own_order and names:
            names.append(own_order)
        if len(_dedupe_order_names(names)) >= 2:
            return True
    own_order = _canonical_order_name(
        row.get("order")
        or row.get("order_name")
        or row.get("selected_order")
        or row.get("selected_order_name")
    )
    for key in _MERGE_EVIDENCE_TEXT_KEYS:
        names = _merged_order_names_from_text(row.get(key))
        if own_order and own_order not in names and names:
            names.append(own_order)
        if len(_dedupe_order_names(names)) >= 2:
            return True
    return False


def _canonical_order_name(value):
    text = _safe_text(value, max_length=80).strip()
    if not text:
        return ""
    match = re.fullmatch(r"#?(\d{3,})", text)
    if match:
        return f"#{match.group(1)}"
    return text


def _dedupe_order_names(values):
    return _dedupe_text(_canonical_order_name(value) for value in values or [])


def _source_customer_order_count(item):
    for key in (
        "customer_order_count",
        "repeat_customer_count",
        "customer_repeat_count",
        "valid_order_count_for_customer",
        "matched_order_count_for_customer",
    ):
        count = _int_or_zero(item.get(key))
        if count > 0:
            return count
    return 0


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
        ("trustpilot_gmail_env_loading_audit", "Trustpilot Gmail env loading audit"),
        ("trustpilot_gmail_scope_compatibility_resolver", "Trustpilot Gmail scope compatibility resolver"),
        ("trustpilot_gmail_draft_only_preflight", "Trustpilot Gmail draft-only preflight"),
        ("trustpilot_gmail_one_draft_create_locked_runner", "Trustpilot Gmail one-draft create locked runner"),
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
        canonical = _canonical_order_name(name)
        for candidate in _dedupe_text((name, canonical)):
            order_names.add(candidate)
            stripped = candidate.lstrip("#")
            if stripped and stripped.isdigit():
                order_numbers.add(stripped)
                order_names.add(f"#{stripped}")
    shopify_order_id = _extract_shopify_order_id(order_id)
    if shopify_order_id:
        shopify_order_ids.add(shopify_order_id)


def _order_lookup_keys(order_name, order_number="", shopify_order_id=""):
    keys = []
    name = _safe_text(order_name, max_length=120)
    number = _safe_text(order_number, max_length=120)
    if name:
        canonical = _canonical_order_name(name)
        for candidate in _dedupe_text((name, canonical)):
            keys.append(f"name:{candidate}")
            stripped = candidate.lstrip("#")
            if stripped and stripped.isdigit():
                keys.append(f"number:{stripped}")
                keys.append(f"name:#{stripped}")
    if number:
        keys.append(f"number:{number}")
        stripped = number.lstrip("#")
        if stripped and stripped.isdigit():
            keys.append(f"number:{stripped}")
            keys.append(f"name:#{stripped}")
            keys.append(f"name:{stripped}")
    if shopify_order_id:
        keys.append(f"shopify_id:{shopify_order_id}")
    return _dedupe_text(keys)


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
            badges.append(_badge("Review request tag found", "rrw-badge-ok"))
        elif _row_text_contains(row, ("blocked_missing_review_request_tag", "canonical review")):
            badges.append(_badge("Blocked: missing review tag", "rrw-badge-bad"))
        if row.get("typo_review_request_tag_present"):
            matched = row.get("matched_review_request_tag_value") or TYPO_REVIEW_REQUEST_TAG
            badges.append(_badge(f"Matched legacy typo tag: {matched}", "rrw-badge-info"))
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
            "Review-request tag alias present",
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
            or "Wait until an eligible delivered order with a review-request tag alias appears and passes all duplicate/risk checks.",
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
            or "Wait until exactly one eligible delivered order with a review-request tag alias passes all duplicate/risk checks and gate is ready.",
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
                "Wait until auto refresh finds exactly one real eligible delivered order with a "
                "review-request tag alias, no duplicate/risk blockers, then re-run final preflight."
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
    gmail_send_scope_present = data.get("gmail_send_scope_present") is True
    gmail_compose_scope_present = data.get("gmail_compose_scope_present") is True
    gmail_broad_mail_scope_present = data.get("gmail_broad_mail_scope_present") is True
    real_send_scope_available = (
        data.get("real_send_scope_available") is True
        or gmail_send_scope_present
        or gmail_broad_mail_scope_present
    )
    draft_only_mode = data.get("draft_only_mode") is True or (
        gmail_compose_scope_present and not real_send_scope_available
    )
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
        "gmail_send_scope_present": gmail_send_scope_present,
        "gmail_compose_scope_present": gmail_compose_scope_present,
        "gmail_broad_mail_scope_present": gmail_broad_mail_scope_present,
        "draft_only_mode": draft_only_mode,
        "real_send_scope_available": real_send_scope_available,
        "future_real_send_scope_blocker": data.get("future_real_send_scope_blocker") is True
        or not real_send_scope_available,
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
    gmail_broad_mail_scope_present = data.get("gmail_broad_mail_scope_present") is True
    real_send_scope_available = (
        data.get("real_send_scope_available") is True
        or gmail_send_scope_present
        or gmail_broad_mail_scope_present
    )
    draft_only_mode = data.get("draft_only_mode") is True or (
        gmail_compose_scope_present and not real_send_scope_available
    )
    future_real_send_scope_blocker = data.get("future_real_send_scope_blocker")
    if future_real_send_scope_blocker is None:
        future_real_send_scope_blocker = not real_send_scope_available
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
        "gmail_broad_mail_scope_present": gmail_broad_mail_scope_present,
        "draft_only_mode": draft_only_mode,
        "real_send_scope_available": real_send_scope_available,
        "future_real_send_scope_blocker": future_real_send_scope_blocker is True,
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
        or scope_compatibility in {"send_scope_present", "gmail_send_scope_available"},
        "gmail_compose_scope_present": data.get("gmail_compose_scope_present") is True
        or scope_compatibility in {"compose_only_not_send_scope", "gmail_compose_only"},
        "gmail_broad_mail_scope_present": data.get("gmail_broad_mail_scope_present") is True
        or scope_compatibility == "broad_mail_scope_available",
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


def _trustpilot_gmail_env_loading_audit_status(report):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    audit_status = _safe_text(
        data.get("env_loading_audit_status")
        or data.get("audit_status")
        or report.get("status")
        or "missing",
        max_length=120,
    )
    message = _safe_text(
        data.get("dashboard_message")
        or _gmail_env_loading_plain_message(audit_status),
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_gmail_env_loading_audit.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_gmail_env_loading_audit.html",
        "audit_status": audit_status,
        "env_loading_audit_status": audit_status,
        "message": message,
        "dashboard_message": message,
        "dot_env_loader_enabled": data.get("dot_env_loader_enabled") is True,
        "dot_env_file_found": data.get("dot_env_file_found") is True,
        "dot_env_keys_loaded_count": _int_or_zero(data.get("dot_env_keys_loaded_count")),
        "dot_env_keys_skipped_existing_count": _int_or_zero(
            data.get("dot_env_keys_skipped_existing_count")
        ),
        "gmail_related_keys_loaded_count": _int_or_zero(data.get("gmail_related_keys_loaded_count")),
        "os_environ_legacy_gmail_key_count": _int_or_zero(
            data.get("os_environ_legacy_gmail_key_count")
        ),
        "os_environ_new_gmail_key_count": _int_or_zero(data.get("os_environ_new_gmail_key_count")),
        "dot_env_file_exists": data.get("dot_env_file_exists") is True,
        "dot_env_legacy_gmail_key_count": _int_or_zero(data.get("dot_env_legacy_gmail_key_count")),
        "dot_env_new_gmail_key_count": _int_or_zero(data.get("dot_env_new_gmail_key_count")),
        "scope_key_detected_in_os_environ": data.get("scope_key_detected_in_os_environ") is True,
        "scope_key_detected_in_dot_env": data.get("scope_key_detected_in_dot_env") is True,
        "os_environ_compose_scope_detected": data.get("os_environ_compose_scope_detected") is True
        or audit_status == "gmail_compose_scope_available_in_runner_env",
        "os_environ_send_scope_detected": data.get("os_environ_send_scope_detected") is True
        or audit_status == "gmail_send_scope_available_in_runner_env",
        "os_environ_broad_mail_scope_detected": data.get("os_environ_broad_mail_scope_detected") is True,
        "docker_compose_env_file_detected": data.get("docker_compose_env_file_detected") is True,
        "django_dotenv_loader_detected": data.get("django_dotenv_loader_detected") is True,
        "remote_approval_dotenv_loader_detected": data.get("remote_approval_dotenv_loader_detected") is True,
        "codex_runner_env_forwarding_detected": data.get("codex_runner_env_forwarding_detected") is True,
        "probable_missing_link": _safe_text(data.get("probable_missing_link"), max_length=160),
        "recommendation": _safe_text(data.get("recommendation"), max_length=500),
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
            "dot_env_value_read_or_printed": data.get("dot_env_value_read_or_printed") is True,
            "shopify_api_call_performed": data.get("shopify_api_call_performed") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
        },
    }


def _gmail_env_loading_plain_message(status):
    if status == "env_file_has_gmail_scope_but_runner_env_missing":
        return "Gmail settings may exist in `.env`, but the automation runner cannot see them yet."
    if status == "gmail_compose_scope_available_in_runner_env":
        return "Gmail draft permission is available. Staff can review drafts before sending."
    if status == "gmail_send_scope_available_in_runner_env":
        return "Gmail send permission is available. Final approval is still required before sending."
    if status == "env_file_loaded_but_scope_still_missing":
        return "Gmail settings loaded, but permission scope is missing."
    if status == "gmail_scope_loaded_but_unrecognized":
        return "Gmail settings loaded, but permission scope is not recognized."
    return "Gmail permission is not configured yet."


def _trustpilot_gmail_scope_compatibility_resolver_status(report):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    status = _safe_text(
        data.get("scope_resolver_status")
        or data.get("scope_compatibility_status")
        or report.get("status")
        or "missing",
        max_length=120,
    )
    compose_available = data.get("compose_scope_available") is True
    send_available = data.get("send_scope_available") is True
    broad_available = data.get("broad_mail_scope_available") is True
    real_send_available = data.get("real_send_scope_available") is True or send_available or broad_available
    draft_only = data.get("draft_only_mode") is True or (
        compose_available and not real_send_available
    )
    future_blocker = data.get("future_real_send_scope_blocker")
    if future_blocker is None:
        future_blocker = not real_send_available
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.html",
        "scope_resolver_status": status,
        "scope_compatibility_status": _safe_text(
            data.get("scope_compatibility_status") or status,
            max_length=120,
        ),
        "message": _safe_text(
            data.get("dashboard_message") or _gmail_scope_plain_message(status),
            max_length=300,
        ),
        "legacy_scope_env_present": data.get("legacy_scope_env_present") is True,
        "new_scope_env_present": data.get("new_scope_env_present") is True,
        "compose_scope_available": compose_available,
        "send_scope_available": send_available,
        "broad_mail_scope_available": broad_available,
        "draft_only_mode": draft_only,
        "real_send_scope_available": real_send_available,
        "future_real_send_scope_blocker": future_blocker is True,
        "compatibility_recommendation": _safe_text(
            data.get("compatibility_recommendation"),
            max_length=500,
        ),
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


def _trustpilot_gmail_draft_only_preflight_status(
    report,
    scope_resolver,
    trustpilot_auto_refresh,
    trustpilot_send_readiness,
):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    draft_preflight_status = _safe_text(
        data.get("draft_preflight_status") or report.get("status") or "missing",
        max_length=120,
    )
    scope_status = _safe_text(
        data.get("scope_status")
        or scope_resolver.get("scope_resolver_status")
        or "scope_missing",
        max_length=120,
    )
    draft_scope_available = (
        data.get("draft_scope_available") is True
        or scope_resolver.get("compose_scope_available") is True
        or scope_resolver.get("real_send_scope_available") is True
    )
    real_send_scope_available = (
        data.get("real_send_scope_available") is True
        or scope_resolver.get("real_send_scope_available") is True
    )
    eligible_candidate_count = _int_or_zero(
        data.get("eligible_candidate_count")
        if "eligible_candidate_count" in data
        else (
            trustpilot_auto_refresh.get("eligible_candidate_count")
            if trustpilot_auto_refresh.get("report_loaded")
            else trustpilot_send_readiness.get("eligible_candidate_count")
        )
    )
    selected_candidate_order_name = _safe_text(
        data.get("selected_candidate_order_name")
        or trustpilot_auto_refresh.get("selected_candidate_order_name")
        or trustpilot_send_readiness.get("selected_candidate_order_name"),
        max_length=80,
    )
    draft_create_allowed_next_phase = data.get("draft_create_allowed_next_phase") is True
    if not report_loaded:
        draft_preflight_status = (
            "missing"
            if eligible_candidate_count or draft_scope_available
            else "blocked_scope_missing"
        )
    message = _safe_text(
        data.get("dashboard_message")
        or _gmail_draft_path_plain_message(
            scope_status,
            eligible_candidate_count,
            draft_preflight_status,
        ),
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_gmail_draft_only_preflight.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_gmail_draft_only_preflight.html",
        "draft_preflight_status": draft_preflight_status,
        "message": message,
        "scope_status": scope_status,
        "draft_scope_available": draft_scope_available,
        "draft_scope_available_label": _plain_yes_no(draft_scope_available),
        "real_send_scope_available": real_send_scope_available,
        "real_send_scope_available_label": _plain_yes_no(real_send_scope_available),
        "eligible_candidate_count": eligible_candidate_count,
        "selected_candidate_order_name": selected_candidate_order_name,
        "selected_candidate_label": selected_candidate_order_name or "None",
        "exactly_one_candidate": data.get("exactly_one_candidate") is True,
        "duplicate_suppression_passed": data.get("duplicate_suppression_passed") is True,
        "related_order_guard_passed": data.get("related_order_guard_passed") is True,
        "risk_checks_passed": data.get("risk_checks_passed") is True,
        "draft_create_allowed_next_phase": draft_create_allowed_next_phase,
        "draft_create_allowed_next_phase_label": _plain_yes_no(draft_create_allowed_next_phase),
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or _gmail_draft_path_next_action(scope_status, eligible_candidate_count),
            max_length=500,
        ),
        "blocking_conditions": (
            data.get("blocking_conditions") if isinstance(data.get("blocking_conditions"), list) else []
        ),
        "privacy_scan_summary": (
            data.get("privacy_scan_summary") if isinstance(data.get("privacy_scan_summary"), dict) else {}
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "raw_flags": {
            "draft_create_performed": data.get("draft_create_performed") is True,
            "gmail_network_call_performed": data.get("gmail_network_call_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_send_performed": data.get("gmail_send_performed") is True,
            "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "shopify_tag_write_performed": data.get("shopify_tag_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
        },
    }


def _trustpilot_gmail_one_draft_create_locked_runner_status(
    report,
    draft_preflight,
    scope_resolver,
):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    report_loaded = bool(report.get("loaded"))
    locked_runner_status = _safe_text(
        data.get("locked_runner_status") or report.get("status") or "missing",
        max_length=120,
    )
    draft_preflight_status = _safe_text(
        data.get("draft_preflight_status")
        or draft_preflight.get("draft_preflight_status")
        or "blocked_scope_missing",
        max_length=120,
    )
    scope_status = _safe_text(
        data.get("scope_status")
        or draft_preflight.get("scope_status")
        or scope_resolver.get("scope_resolver_status")
        or "scope_missing",
        max_length=120,
    )
    draft_scope_available = (
        data.get("draft_scope_available") is True
        or draft_preflight.get("draft_scope_available") is True
        or scope_resolver.get("compose_scope_available") is True
        or scope_resolver.get("real_send_scope_available") is True
    )
    real_send_scope_available = (
        data.get("real_send_scope_available") is True
        or draft_preflight.get("real_send_scope_available") is True
        or scope_resolver.get("real_send_scope_available") is True
    )
    eligible_candidate_count = _int_or_zero(
        data.get("eligible_candidate_count")
        if "eligible_candidate_count" in data
        else draft_preflight.get("eligible_candidate_count")
    )
    selected_candidate_order_name = _safe_text(
        data.get("selected_candidate_order_name")
        or draft_preflight.get("selected_candidate_order_name"),
        max_length=80,
    )
    exactly_one_candidate = data.get("exactly_one_candidate") is True or (
        not report_loaded and draft_preflight.get("exactly_one_candidate") is True
    )
    draft_create_requested = data.get("draft_create_requested") is True
    draft_create_allowed_by_preflight = data.get("draft_create_allowed_by_preflight") is True
    draft_create_allowed_by_env = data.get("draft_create_allowed_by_env") is True
    draft_create_performed = data.get("draft_create_performed") is True
    if not report_loaded:
        locked_runner_status = "blocked_missing_requirements"
    missing_requirements_plain = (
        data.get("missing_requirements_plain")
        if isinstance(data.get("missing_requirements_plain"), list)
        else _draft_creation_missing_requirements_plain(
            draft_scope_available=draft_scope_available,
            eligible_candidate_count=eligible_candidate_count,
            exactly_one_candidate=exactly_one_candidate,
            draft_create_requested=draft_create_requested,
        )
    )
    missing_requirement_labels = _draft_creation_missing_labels(
        draft_scope_available=draft_scope_available,
        eligible_candidate_count=eligible_candidate_count,
        exactly_one_candidate=exactly_one_candidate,
        draft_create_requested=draft_create_requested,
    )
    message = _safe_text(
        data.get("dashboard_message")
        or _draft_creation_readiness_message(scope_status, eligible_candidate_count),
        max_length=300,
    )
    return {
        "report_present": bool(report.get("present")),
        "report_loaded": report_loaded,
        "relative_path": _safe_text(
            report.get("relative_path")
            or "logs/shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.json",
            max_length=160,
        ),
        "html_relative_path": "logs/shopify_review_request_trustpilot_gmail_one_draft_create_locked_runner.html",
        "locked_runner_status": locked_runner_status,
        "message": message,
        "can_create_draft_now": False,
        "can_create_draft_now_label": "No",
        "draft_preflight_status": draft_preflight_status,
        "scope_status": scope_status,
        "draft_scope_available": draft_scope_available,
        "draft_scope_available_label": _plain_yes_no(draft_scope_available),
        "real_send_scope_available": real_send_scope_available,
        "real_send_scope_available_label": _plain_yes_no(real_send_scope_available),
        "eligible_candidate_count": eligible_candidate_count,
        "selected_candidate_order_name": selected_candidate_order_name,
        "selected_candidate_label": selected_candidate_order_name or "None",
        "exactly_one_candidate": exactly_one_candidate,
        "draft_create_requested": draft_create_requested,
        "draft_create_allowed_by_preflight": draft_create_allowed_by_preflight,
        "draft_create_allowed_by_env": draft_create_allowed_by_env,
        "draft_create_performed": draft_create_performed,
        "required_future_env_flag_name": _safe_text(
            data.get("required_future_env_flag_name")
            or "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_DRAFT_CREATE",
            max_length=120,
        ),
        "missing_requirements_plain": [
            _safe_text(item, max_length=240) for item in missing_requirements_plain if item
        ],
        "missing_requirement_labels": missing_requirement_labels,
        "next_admin_action": _safe_text(
            data.get("next_admin_action")
            or _draft_creation_next_action(scope_status, eligible_candidate_count),
            max_length=500,
        ),
        "blocking_conditions": (
            data.get("blocking_conditions") if isinstance(data.get("blocking_conditions"), list) else []
        ),
        "privacy_scan_summary": (
            data.get("privacy_scan_summary") if isinstance(data.get("privacy_scan_summary"), dict) else {}
        ),
        "source_error": _safe_text(report.get("error", ""), max_length=300),
        "raw_flags": {
            "draft_create_performed": draft_create_performed,
            "gmail_network_call_performed": data.get("gmail_network_call_performed") is True,
            "gmail_api_call_performed": data.get("gmail_api_call_performed") is True,
            "gmail_send_performed": data.get("gmail_send_performed") is True,
            "gmail_draft_create_performed": data.get("gmail_draft_create_performed") is True,
            "shopify_write_performed": data.get("shopify_write_performed") is True,
            "shopify_tag_write_performed": data.get("shopify_tag_write_performed") is True,
            "external_review_api_call_performed": data.get("external_review_api_call_performed") is True,
        },
    }


def _draft_creation_missing_requirements_plain(
    draft_scope_available,
    eligible_candidate_count,
    exactly_one_candidate,
    draft_create_requested,
):
    missing = []
    if not draft_scope_available:
        missing.append("Gmail permission is not configured.")
    if eligible_candidate_count == 0:
        missing.append("No eligible order is available.")
    if not exactly_one_candidate:
        missing.append("The system needs exactly one safe order before creating a draft.")
    if not draft_create_requested:
        missing.append("Final approval is required before creating a draft.")
    return missing


def _draft_creation_missing_labels(
    draft_scope_available,
    eligible_candidate_count,
    exactly_one_candidate,
    draft_create_requested,
):
    labels = []
    if not draft_scope_available:
        labels.append("Gmail permission")
    if eligible_candidate_count == 0 or not exactly_one_candidate:
        labels.append("Eligible order")
    if not draft_create_requested:
        labels.append("Final approval")
    return labels


def _draft_creation_readiness_message(scope_status, eligible_candidate_count):
    if scope_status == "scope_missing" and eligible_candidate_count == 0:
        return "Draft creation is not ready yet. Gmail permission is not configured, and there is no eligible order."
    if scope_status == "scope_missing":
        return "Draft creation is not ready yet. Gmail permission is not configured."
    if eligible_candidate_count == 0:
        return "Draft creation is not ready yet. There is no eligible order."
    return "Draft creation is not ready yet."


def _draft_creation_next_action(scope_status, eligible_candidate_count):
    if scope_status == "scope_missing" and eligible_candidate_count == 0:
        return "Configure Gmail permission and wait for exactly one eligible safe order."
    if scope_status == "scope_missing":
        return "Configure Gmail compose or send permission before any future draft creation phase."
    if eligible_candidate_count == 0:
        return "Wait for exactly one eligible delivered Trustpilot candidate, then rerun the draft checks."
    return "Review missing requirements before any future Gmail draft creation phase."


def _gmail_draft_path_plain_message(scope_status, eligible_candidate_count, draft_preflight_status):
    if scope_status == "scope_missing" and eligible_candidate_count == 0:
        return "Draft path is not ready because there is no eligible order and Gmail permission is not configured."
    if scope_status == "scope_missing":
        return "Draft path is not ready because Gmail permission is not configured."
    if eligible_candidate_count == 0:
        return "Draft path is not ready because there is no eligible order."
    if draft_preflight_status == "blocked_multiple_candidates_require_manual_selection":
        return "Draft path is not ready because more than one order needs manual selection."
    if draft_preflight_status == "ready_for_one_draft_create_next_phase":
        return "Gmail draft path is ready for one locked draft create phase."
    if draft_preflight_status == "draft_path_available_but_send_scope_also_available":
        return "Gmail draft path is available, and send permission is also available."
    return "Draft path is not ready yet."


def _gmail_draft_path_next_action(scope_status, eligible_candidate_count):
    if scope_status == "scope_missing" and eligible_candidate_count == 0:
        return "Draft path is not ready because there is no eligible order and Gmail permission is not configured."
    if scope_status == "scope_missing":
        return "Configure Gmail compose or send permission before any future draft create phase."
    if eligible_candidate_count == 0:
        return "Wait for one eligible delivered Trustpilot candidate, then rerun draft-only preflight."
    return "Review the draft-only preflight report before any future draft create phase."


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
    all_rows,
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
    trustpilot_gmail_env_loading_audit,
    trustpilot_gmail_scope_compatibility_resolver,
    trustpilot_gmail_draft_only_preflight,
    trustpilot_gmail_one_draft_create_locked_runner,
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
        trustpilot_gmail_scope_compatibility_resolver,
        trustpilot_gmail_env_loading_audit,
    )
    last_60_days_scan = _last_60_days_candidate_scan(
        candidate_queue=candidate_queue,
        blocked_orders=blocked_orders,
        invitation_history=invitation_history,
        trustpilot_email_records=trustpilot_email_records,
        all_rows=all_rows,
        focus=focus,
        gmail_setup=gmail_setup,
    )
    ready_count = last_60_days_scan["eligible_candidate_count"]
    blocked_count = last_60_days_scan["blocked_count"]
    sent_count = last_60_days_scan["already_sent_count"]
    setup_checklist = _setup_checklist(
        ready_count=ready_count,
        trustpilot_send_readiness=trustpilot_send_readiness,
        trustpilot_auto_refresh=trustpilot_auto_refresh,
        trustpilot_gmail_scope_compatibility_resolver=trustpilot_gmail_scope_compatibility_resolver,
        trustpilot_gmail_draft_only_preflight=trustpilot_gmail_draft_only_preflight,
        trustpilot_gmail_one_draft_create_locked_runner=trustpilot_gmail_one_draft_create_locked_runner,
    )
    approval_queue = _approval_queue(
        candidate_queue=candidate_queue,
        blocked_orders=blocked_orders,
        invitation_history=invitation_history,
        trustpilot_email_records=trustpilot_email_records,
        focus=focus,
        gmail_setup=gmail_setup,
        last_60_days_scan=last_60_days_scan,
    )
    order_data_coverage = _dashboard_order_data_coverage(last_60_days_scan)
    return {
        "ready_to_send_count": ready_count,
        "blocked_count": blocked_count,
        "sent_trustpilot_count": sent_count,
        "approval_queue": approval_queue,
        "last_60_days_candidate_scan": last_60_days_scan,
        "order_data_coverage": order_data_coverage,
        "setup_checklist": setup_checklist,
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
        "gmail_draft_path": trustpilot_gmail_draft_only_preflight,
        "gmail_draft_creation_readiness": trustpilot_gmail_one_draft_create_locked_runner,
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
        "trustpilot_gmail_env_loading_audit": trustpilot_gmail_env_loading_audit,
        "trustpilot_gmail_scope_compatibility_resolver": trustpilot_gmail_scope_compatibility_resolver,
        "trustpilot_gmail_draft_only_preflight": trustpilot_gmail_draft_only_preflight,
        "trustpilot_gmail_one_draft_create_locked_runner": trustpilot_gmail_one_draft_create_locked_runner,
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


def _dashboard_order_data_coverage(scan):
    coverage = scan.get("order_data_coverage") or {}
    scan_source = _safe_text(scan.get("scan_source") or coverage.get("scan_source"), max_length=80)
    source_label = {
        "full_shopify_orders": "Full Shopify orders",
        "shenzhen_only_orders": "Shenzhen only",
        "fallback_report_only": "Fallback report only",
        "sqlite_report_fallback": "SQLite/report fallback",
    }.get(scan_source, "Unknown")
    warnings = _dedupe_text(scan.get("coverage_warnings") or coverage.get("coverage_warnings") or [])
    incomplete = scan_source != "full_shopify_orders"
    latest_sync = _safe_text(coverage.get("latest_review_request_sync_finished_at"), max_length=120)
    sync_window = _safe_text(coverage.get("last_shopify_order_sync_window"), max_length=120)
    freshness = _safe_text(scan.get("timestamp") or scan.get("scan_window_ended_at"), max_length=120)
    return {
        "scan_source": scan_source or "unknown",
        "local_data_source_label": source_label,
        "last_shopify_order_sync_window": sync_window or "Unknown",
        "latest_review_request_sync_finished_at": latest_sync or "Unknown",
        "order_22530_found_label": "Yes" if coverage.get("order_22530_found") is True else "No",
        "candidate_scan_freshness": freshness or "Unknown",
        "coverage_warnings": warnings,
        "warning_label": ", ".join(warnings) if warnings else "None",
        "incomplete": incomplete,
        "incomplete_message": (
            "Order data is incomplete. Run the 60-day Shopify sync before trusting the candidate list."
            if incomplete
            else ""
        ),
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


def _build_review_send_state():
    reports = _load_known_reports()
    history_ledger = build_review_request_history_ledger(_log_dir(), {})
    all_rows = _dedupe_rows(_collect_report_rows(reports))
    candidate_queue = _candidate_queue(reports)
    invitation_history = _rows_with_trustpilot_tags(all_rows)
    blocked_orders = _blocked_rows(reports, all_rows)
    trustpilot_email_records = _trustpilot_email_records(
        history_ledger["all_events"],
        history_ledger["filters"],
    )
    gmail_setup = _gmail_setup_from_reports(reports)
    last_60_days_scan = _last_60_days_candidate_scan(
        candidate_queue=candidate_queue,
        blocked_orders=blocked_orders,
        invitation_history=invitation_history,
        trustpilot_email_records=trustpilot_email_records,
        all_rows=all_rows,
        focus=history_ledger.get("focus") or {},
        gmail_setup=gmail_setup,
    )
    approval_queue = _approval_queue(
        candidate_queue=candidate_queue,
        blocked_orders=blocked_orders,
        invitation_history=invitation_history,
        trustpilot_email_records=trustpilot_email_records,
        focus=history_ledger.get("focus") or {},
        gmail_setup=gmail_setup,
        last_60_days_scan=last_60_days_scan,
    )
    return {
        "reports": reports,
        "history_ledger": history_ledger,
        "candidate_queue": candidate_queue,
        "invitation_history": invitation_history,
        "blocked_orders": blocked_orders,
        "trustpilot_email_records": trustpilot_email_records,
        "gmail_setup": gmail_setup,
        "last_60_days_scan": last_60_days_scan,
        "approval_queue": approval_queue,
    }


def build_review_request_last_60_days_candidate_scan_report(params=None):
    reports = _load_known_reports()
    history_ledger = build_review_request_history_ledger(_log_dir(), params or {})
    all_rows = _dedupe_rows(_collect_report_rows(reports))
    candidate_queue = _candidate_queue(reports)
    invitation_history = _rows_with_trustpilot_tags(all_rows)
    blocked_orders = _blocked_rows(reports, all_rows)
    trustpilot_email_records = _trustpilot_email_records(
        history_ledger["all_events"],
        history_ledger["filters"],
    )
    gmail_setup = _gmail_setup_from_reports(reports)
    scan = _last_60_days_candidate_scan(
        candidate_queue=candidate_queue,
        blocked_orders=blocked_orders,
        invitation_history=invitation_history,
        trustpilot_email_records=trustpilot_email_records,
        all_rows=all_rows,
        focus=history_ledger.get("focus") or {},
        gmail_setup=gmail_setup,
    )
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": LAST_60_DAY_SCAN_TASK_NAME,
        "task_name": LAST_60_DAY_SCAN_TASK_NAME,
        "phase": "5.28E",
        "mode": "dry-run-local-synced-order-scan",
        "window_days": LAST_60_DAY_SCAN_WINDOW_DAYS,
        "report_status": "last_60_days_candidate_scan_ready",
        "success": True,
        "scan_source": scan["scan_source"],
        "coverage_warnings": scan["coverage_warnings"],
        "order_data_coverage": scan["order_data_coverage"],
        "order_22530_diagnosis": scan["order_22530_diagnosis"],
        "scanned_order_count": scan["scanned_order_count"],
        "delivered_order_count": scan["delivered_order_count"],
        "eligible_candidate_count": scan["eligible_candidate_count"],
        "already_sent_count": scan["already_sent_count"],
        "blocked_count": scan["blocked_count"],
        "blocked_merged_group_count": scan["blocked_merged_group_count"],
        "blocked_duplicate_customer_count": scan["blocked_duplicate_customer_count"],
        "blocked_missing_review_request_tag_count": scan["blocked_missing_review_request_tag_count"],
        "blocked_not_delivered_count": scan["blocked_not_delivered_count"],
        "eligible_candidates_summary": scan["eligible_candidates_summary"],
        "blocked_candidates_summary": scan["blocked_candidates_summary"],
        "already_sent_summary": scan["already_sent_summary"],
        "scan_window_started_at": scan["scan_window_started_at"],
        "scan_window_ended_at": scan["scan_window_ended_at"],
        "date_fallback_order_count": scan["date_fallback_order_count"],
        "date_fallback_summary": scan["date_fallback_summary"],
        "candidate_22562_audit": _candidate_22562_alias_audit_from_scan(scan),
        "gmail_permission_status": scan["gmail_permission_status"],
        "template_available": scan["template_available"],
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": _last_60_days_issue_summary(scan),
    }


def build_review_request_tag_alias_and_candidate_correction_audit_report(params=None):
    state = _build_review_send_state()
    scan = state["last_60_days_scan"]
    candidate_audit = _candidate_22562_alias_audit_from_scan(scan)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_tag_alias_and_candidate_correction_audit",
        "task_name": "shopify_review_request_tag_alias_and_candidate_correction_audit",
        "phase": "5.28A",
        "mode": "dry-run-local-audit",
        "report_status": "tag_alias_and_candidate_correction_audit_ready",
        "success": True,
        "review_request_tag_aliases": list(REVIEW_REQUEST_TAG_ALIASES),
        "canonical_review_request_tag_for_future_writes": CANONICAL_REVIEW_REQUEST_TAG,
        "delivered_tag_aliases": list(DELIVERED_TAG_ALIASES),
        "trustpilot_sent_tag_aliases": list(TRUSTPILOT_TAG_ALIASES),
        "order_22562_tags_loaded": candidate_audit["tags_loaded"],
        "order_22562_review_request_tag_detected": candidate_audit["review_request_tag_detected"],
        "order_22562_matched_review_request_tag_value": candidate_audit["matched_review_request_tag_value"],
        "order_22562_delivered_detected": candidate_audit["delivered_detected"],
        "order_22562_merged_group_evidence_source": candidate_audit["merged_group_evidence_source"],
        "order_22562_explicit_merge_evidence": candidate_audit["explicit_merge_evidence"],
        "order_22562_final_eligibility_status": candidate_audit["final_eligibility_status"],
        "order_22562_final_blockers": candidate_audit["final_blockers"],
        "candidate_22562_audit": candidate_audit,
        "eligible_candidate_count_after_fix": scan.get("eligible_candidate_count", 0),
        "eligible_candidate_orders_after_fix": [
            row.get("order")
            for row in scan.get("eligible_queue_rows", [])
            if row.get("order")
        ],
        "blocked_merged_group_count_after_fix": scan.get("blocked_merged_group_count", 0),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": _candidate_22562_audit_issue_summary(candidate_audit, scan),
    }


def _candidate_22562_alias_audit_from_scan(scan):
    row, section = _find_scan_order_row(scan, "#22562")
    if not row:
        return {
            "order_name": "#22562",
            "row_found": False,
            "row_section": "not_scanned",
            "tags": [],
            "tags_loaded": False,
            "review_request_tag_detected": False,
            "matched_review_request_tag_value": "",
            "delivered_detected": False,
            "merged_group_evidence_source": "none",
            "explicit_merge_evidence": False,
            "final_eligibility_status": "not_scanned",
            "final_blockers": ["Order #22562 was not present in the local last-60-days scan."],
        }
    tags = _dedupe_text(row.get("order_tags_display") or row.get("tags") or [])
    matched_review_request_tags = _matched_review_request_tags(tags)
    matched_tag = (
        _safe_text(row.get("matched_review_request_tag_value"), max_length=120)
        or (matched_review_request_tags[0] if matched_review_request_tags else "")
    )
    action_state = _safe_text(row.get("action_state"), max_length=80)
    final_status = {
        "review_send": "eligible",
        "already_sent": "already_sent",
        "not_ready": "blocked",
    }.get(action_state, section)
    blockers = []
    if final_status == "blocked":
        blockers = _split_blocker_text(row.get("eligibility_reason_plain") or row.get("reason"))
    elif final_status == "already_sent":
        blockers = [_safe_text(row.get("trustpilot_history_label") or row.get("reason"), max_length=300)]
    explicit_merge = row.get("merged_order_group") is True
    evidence_source = (
        _safe_text(row.get("merged_group_evidence_source"), max_length=160)
        if explicit_merge
        else "none"
    )
    return {
        "order_name": "#22562",
        "row_found": True,
        "row_section": section,
        "tags": tags,
        "tags_loaded": bool(tags) or row.get("has_order_tags") is True,
        "review_request_tag_detected": row.get("review_request_tag_present") is True or bool(matched_tag),
        "matched_review_request_tag_value": matched_tag,
        "review_request_tag_match_detail": _review_request_tag_match_detail(matched_tag),
        "delivered_detected": row.get("delivered_status_label") == "Delivered",
        "merged_group_evidence_source": evidence_source,
        "explicit_merge_evidence": explicit_merge,
        "final_eligibility_status": final_status,
        "final_blockers": [blocker for blocker in blockers if blocker],
    }


def _find_scan_order_row(scan, order_name):
    for section_name, key in (
        ("eligible", "eligible_queue_rows"),
        ("blocked", "blocked_queue_rows"),
        ("already_sent", "already_sent_queue_rows"),
    ):
        for row in scan.get(key) or []:
            if row.get("order") == order_name:
                return row, section_name
    return None, "not_scanned"


def _split_blocker_text(value):
    text = _safe_text(value, max_length=500)
    if not text:
        return []
    return [
        _safe_text(part, max_length=240)
        for part in re.split(r";\s*", text)
        if _safe_text(part, max_length=240)
    ]


def _candidate_22562_audit_issue_summary(candidate_audit, scan):
    status = candidate_audit.get("final_eligibility_status", "unknown")
    matched = candidate_audit.get("matched_review_request_tag_value") or "none"
    return (
        f"#22562 status after alias and merge-evidence correction: {status}; "
        f"matched review request tag: {matched}; "
        f"eligible candidates after fix: {scan.get('eligible_candidate_count', 0)}. "
        "No Gmail, Shopify, Trustpilot, Kudosi, or Ali Reviews API calls were performed."
    )


def _gmail_setup_from_reports(reports):
    return _gmail_setup_summary(
        _trustpilot_gmail_oauth_config_helper_status(
            reports.get("trustpilot_gmail_oauth_config_helper", {}),
            {},
        ),
        _trustpilot_gmail_config_compatibility_audit_status(
            reports.get("trustpilot_gmail_config_compatibility_audit", {}),
        ),
        _trustpilot_gmail_scope_compatibility_resolver_status(
            reports.get("trustpilot_gmail_scope_compatibility_resolver", {}),
        ),
        _trustpilot_gmail_env_loading_audit_status(
            reports.get("trustpilot_gmail_env_loading_audit", {}),
        ),
    )


def _approval_queue(
    candidate_queue,
    blocked_orders,
    invitation_history,
    trustpilot_email_records,
    focus,
    gmail_setup,
    last_60_days_scan=None,
):
    if last_60_days_scan:
        return _approval_queue_from_last_60_days_scan(last_60_days_scan)

    already_sent_rows = _already_sent_rows(
        focus=focus,
        trustpilot_email_records=trustpilot_email_records,
        invitation_history=invitation_history,
        blocked_orders=blocked_orders,
    )
    local_order_contexts = _local_order_contexts(
        _approval_queue_order_names(
            candidate_queue=candidate_queue,
            blocked_orders=blocked_orders,
            invitation_history=invitation_history,
            trustpilot_email_records=trustpilot_email_records,
            already_sent_rows=already_sent_rows,
        )
    )
    for sent_row in already_sent_rows:
        _apply_queue_row_context(
            sent_row,
            _source_row_for_order(
                sent_row.get("order"),
                trustpilot_email_records,
                invitation_history,
                blocked_orders,
                candidate_queue,
            ),
            local_order_contexts.get(sent_row.get("order"), {}),
            action_state="already_sent",
        )
    already_sent_orders = {row["order"] for row in already_sent_rows if row.get("order")}
    already_sent_customers = {
        row["customer"]
        for row in already_sent_rows
        if _usable_masked_customer(row.get("customer"))
    }
    needs_review_rows = []
    seen_orders = set()
    for row in candidate_queue or []:
        order_name = _safe_text(row.get("order_name"), max_length=80)
        if not order_name or order_name in seen_orders:
            continue
        seen_orders.add(order_name)
        queue_row = _needs_review_queue_row(
            row,
            already_sent_orders=already_sent_orders,
            already_sent_customers=already_sent_customers,
            gmail_setup=gmail_setup,
            local_context=local_order_contexts.get(order_name, {}),
        )
        if queue_row["action_state"] == "already_sent":
            if queue_row["order"] not in already_sent_orders:
                queue_row["evidence"] = queue_row["reason"]
                already_sent_rows.append(queue_row)
                already_sent_orders.add(queue_row["order"])
        else:
            needs_review_rows.append(queue_row)

    if "#22582" not in seen_orders and "#22582" not in already_sent_orders:
        source_row = _source_row_for_order("#22582", blocked_orders, candidate_queue)
        needs_review_rows.append(
            _known_not_ready_queue_row(
                "#22582",
                _masked_customer_for_order("#22582", blocked_orders, trustpilot_email_records),
                source_row=source_row,
                local_context=local_order_contexts.get("#22582", {}),
            )
        )

    needs_review_rows, already_sent_rows, merged_group_summary = _apply_merged_order_group_guard(
        needs_review_rows=needs_review_rows,
        already_sent_rows=already_sent_rows,
        source_row_groups=(
            candidate_queue,
            blocked_orders,
            invitation_history,
            trustpilot_email_records,
        ),
    )
    needs_review_rows.sort(key=_approval_queue_sort_key)
    already_sent_rows = _collapse_merged_group_rows(_dedupe_queue_rows(already_sent_rows))
    ready_to_send_count = sum(1 for row in needs_review_rows if row["action_state"] == "review_send")
    not_ready_count = sum(1 for row in needs_review_rows if row["action_state"] == "not_ready")
    return {
        "needs_review_rows": needs_review_rows,
        "already_sent_rows": already_sent_rows,
        "needs_review_count": len(needs_review_rows),
        "already_sent_count": len(already_sent_rows),
        "ready_to_send_count": ready_to_send_count,
        "not_ready_count": not_ready_count,
        "duplicate_block_count": sum(
            1
            for row in needs_review_rows
            if "already received" in row.get("reason", "").lower()
        ),
        "review_send_action_enabled_count": ready_to_send_count,
        "email_sent_count": sum(
            1
            for row in already_sent_rows
            if "sent" in row.get("status", "").lower()
            or "sent" in row.get("evidence", "").lower()
        ),
        "merged_group_count": merged_group_summary["merged_group_count"],
        "merged_groups": merged_group_summary["merged_groups"],
        "shopify_tag_write_enabled_count": 0,
        "empty_message": "No orders need review email right now.",
    }


def _approval_queue_from_last_60_days_scan(scan):
    needs_review_rows = list(scan.get("eligible_queue_rows") or [])
    blocked_rows = list(scan.get("blocked_queue_rows") or [])
    already_sent_rows = list(scan.get("already_sent_queue_rows") or [])
    merged_groups = scan.get("merged_groups") or []
    ready_to_send_count = len(needs_review_rows)
    coverage_incomplete = scan.get("scan_source") != "full_shopify_orders"
    return {
        "needs_review_rows": needs_review_rows,
        "blocked_rows": blocked_rows,
        "already_sent_rows": already_sent_rows,
        "needs_review_count": ready_to_send_count,
        "already_sent_count": len(already_sent_rows),
        "ready_to_send_count": ready_to_send_count,
        "not_ready_count": len(blocked_rows),
        "blocked_count": len(blocked_rows),
        "duplicate_block_count": scan.get("blocked_duplicate_customer_count", 0),
        "review_send_action_enabled_count": ready_to_send_count,
        "email_sent_count": scan.get("already_sent_count", 0),
        "merged_group_count": scan.get("blocked_merged_group_count", 0),
        "merged_groups": merged_groups,
        "shopify_tag_write_enabled_count": 0,
        "empty_message": (
            "Order data is incomplete. Run the 60-day Shopify sync before trusting the candidate list."
            if coverage_incomplete
            else "No orders need review email right now."
        ),
        "scan_summary": {
            "scanned_order_count": scan.get("scanned_order_count", 0),
            "delivered_order_count": scan.get("delivered_order_count", 0),
            "eligible_candidate_count": scan.get("eligible_candidate_count", 0),
            "blocked_count": scan.get("blocked_count", 0),
            "already_sent_count": scan.get("already_sent_count", 0),
            "window_days": scan.get("window_days", LAST_60_DAY_SCAN_WINDOW_DAYS),
            "scan_source": scan.get("scan_source", "unknown"),
            "coverage_incomplete": coverage_incomplete,
        },
    }


def _last_60_days_candidate_scan(
    candidate_queue,
    blocked_orders,
    invitation_history,
    trustpilot_email_records,
    all_rows,
    focus,
    gmail_setup,
):
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=LAST_60_DAY_SCAN_WINDOW_DAYS)
    source_row_groups = (
        candidate_queue,
        blocked_orders,
        invitation_history,
        trustpilot_email_records,
        all_rows,
    )
    source_by_order = _source_rows_by_order(*source_row_groups)
    source_by_order = _apply_manual_confirmed_order_evidence(source_by_order)
    scan_contexts, local_db_error = _last_60_day_order_scan_contexts(source_by_order, cutoff)
    scan_contexts = _ensure_current_focus_scan_contexts(scan_contexts, source_by_order, cutoff)
    local_order_contexts = _local_order_contexts(scan_contexts.keys())

    already_sent_rows = _already_sent_rows(
        focus=focus,
        trustpilot_email_records=trustpilot_email_records,
        invitation_history=invitation_history,
        blocked_orders=blocked_orders,
    )
    for sent_row in already_sent_rows:
        order_name = sent_row.get("order")
        _apply_queue_row_context(
            sent_row,
            _source_row_for_order(
                order_name,
                trustpilot_email_records,
                invitation_history,
                blocked_orders,
                candidate_queue,
                all_rows,
            ),
            local_order_contexts.get(order_name, {}),
            action_state="already_sent",
        )

    already_sent_orders = {row["order"] for row in already_sent_rows if row.get("order")}
    already_sent_customers = {
        row["customer"]
        for row in already_sent_rows
        if _usable_masked_customer(row.get("customer"))
    }

    queue_rows = []
    scanned_contexts = sorted(
        scan_contexts.values(),
        key=lambda item: (
            item.get("scan_date") or "",
            item.get("order_name") or "",
        ),
        reverse=True,
    )
    limited_contexts = list(scanned_contexts[:MAX_SOURCE_ROWS])
    included_orders = {context.get("order_name") for context in limited_contexts}
    for context in scanned_contexts[MAX_SOURCE_ROWS:]:
        if context.get("order_name") in set(REVIEW_REQUEST_FOCUS_ORDER_NAMES):
            if context.get("order_name") not in included_orders:
                limited_contexts.append(context)
                included_orders.add(context.get("order_name"))
    for context in limited_contexts:
        order_name = context.get("order_name")
        if not order_name:
            continue
        if _is_simulator_order_name(order_name):
            continue
        source_row = _scan_queue_source_row(
            order_name,
            source_by_order.get(order_name) or {},
            context,
            local_order_contexts.get(order_name, {}),
        )
        queue_row = _needs_review_queue_row(
            source_row,
            already_sent_orders=already_sent_orders,
            already_sent_customers=already_sent_customers,
            gmail_setup=gmail_setup,
            local_context=local_order_contexts.get(order_name, {}),
        )
        _attach_scan_date_context(queue_row, context)
        if queue_row["action_state"] == "already_sent":
            if queue_row["order"] not in already_sent_orders:
                queue_row["evidence"] = queue_row["reason"]
                already_sent_rows.append(queue_row)
                already_sent_orders.add(queue_row["order"])
        else:
            queue_rows.append(queue_row)

    queue_rows, already_sent_rows, merged_group_summary = _apply_merged_order_group_guard(
        needs_review_rows=queue_rows,
        already_sent_rows=already_sent_rows,
        source_row_groups=source_row_groups,
    )
    queue_rows = _dedupe_queue_rows(queue_rows)
    already_sent_rows = _collapse_merged_group_rows(_dedupe_queue_rows(already_sent_rows))
    eligible_rows = [
        row for row in queue_rows if row.get("action_state") == "review_send"
    ]
    blocked_rows = [
        row for row in queue_rows if row.get("action_state") != "review_send"
    ]
    eligible_rows.sort(key=_approval_queue_sort_key)
    blocked_rows.sort(key=_blocked_queue_sort_key)
    already_sent_rows.sort(key=_already_sent_sort_key)

    delivered_count = sum(
        1
        for context in scan_contexts.values()
        if context.get("delivered_confirmed") is True
    )
    fallback_contexts = [
        context
        for context in scan_contexts.values()
        if context.get("scan_date_fallback_used") is True
    ]
    order_data_coverage = _order_data_coverage_summary(
        scan_contexts=scan_contexts,
        source_by_order=source_by_order,
        cutoff=cutoff,
        local_db_error=local_db_error,
    )
    order_22530_diagnosis = _focus_order_diagnosis("#22530", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    return {
        "window_days": LAST_60_DAY_SCAN_WINDOW_DAYS,
        "scan_window_started_at": cutoff.isoformat(),
        "scan_window_ended_at": now.isoformat(),
        "scan_source": order_data_coverage["scan_source"],
        "coverage_warnings": order_data_coverage["coverage_warnings"],
        "order_data_coverage": order_data_coverage,
        "order_22530_diagnosis": order_22530_diagnosis,
        "local_db_error_sanitized": local_db_error,
        "scanned_order_count": len(scan_contexts),
        "delivered_order_count": delivered_count,
        "eligible_candidate_count": len(eligible_rows),
        "already_sent_count": len(already_sent_rows),
        "blocked_count": len(blocked_rows),
        "blocked_merged_group_count": sum(1 for row in blocked_rows if _row_blocked_by_merged_group(row)),
        "blocked_duplicate_customer_count": sum(1 for row in blocked_rows if _row_blocked_by_duplicate(row)),
        "blocked_missing_review_request_tag_count": sum(
            1 for row in blocked_rows if _row_blocked_by_missing_review_request_tag(row)
        ),
        "blocked_not_delivered_count": sum(1 for row in blocked_rows if _row_blocked_by_not_delivered(row)),
        "eligible_queue_rows": eligible_rows,
        "blocked_queue_rows": blocked_rows,
        "already_sent_queue_rows": already_sent_rows,
        "eligible_candidates_summary": [_queue_candidate_summary(row) for row in eligible_rows],
        "blocked_candidates_summary": [_blocked_candidate_summary(row) for row in blocked_rows],
        "already_sent_summary": [_already_sent_summary(row) for row in already_sent_rows],
        "merged_groups": merged_group_summary["merged_groups"],
        "date_fallback_order_count": len(fallback_contexts),
        "date_fallback_summary": [_scan_date_summary(context) for context in fallback_contexts[:25]],
        "gmail_permission_status": gmail_setup.get("scope_status") or "scope_missing",
        "template_available": True,
    }


def _order_data_coverage_summary(scan_contexts, source_by_order, cutoff, local_db_error):
    coverage = {
        "scan_source": "fallback_report_only",
        "coverage_warnings": [],
        "last_shopify_order_sync_window": "Unknown",
        "latest_review_request_sync_finished_at": "",
        "latest_review_request_sync_task_name": "",
        "local_last_60_days_order_count": 0,
        "local_last_60_days_shenzhen_order_count": 0,
        "local_last_60_days_non_shenzhen_order_count": 0,
        "local_order_context_count": sum(
            1
            for context in scan_contexts.values()
            if context.get("local_order_source") == "ShopifyOrder"
        ),
        "report_only_context_count": sum(
            1
            for context in scan_contexts.values()
            if context.get("local_order_source") != "ShopifyOrder"
        ),
        "delivered_order_data_missing_count": sum(
            1 for context in scan_contexts.values() if context.get("delivered_confirmed") is None
        ),
        "order_22530_found": False,
        "order_22562_found": False,
        "local_db_error_sanitized": local_db_error,
    }
    try:
        query = (
            Q(order_created_at__gte=cutoff)
            | Q(fulfilled_at__gte=cutoff)
            | Q(updated_at__gte=cutoff)
        )
        local_queryset = ShopifyOrder.objects.filter(query)
        coverage["local_last_60_days_order_count"] = local_queryset.count()
        shenzhen_query = Q(is_shenzhen_order=True) | Q(current_location__in=["shenzhen", "mixed"])
        coverage["local_last_60_days_shenzhen_order_count"] = local_queryset.filter(shenzhen_query).count()
        coverage["local_last_60_days_non_shenzhen_order_count"] = max(
            coverage["local_last_60_days_order_count"]
            - coverage["local_last_60_days_shenzhen_order_count"],
            0,
        )
        local_orders = list(
            local_queryset.values(
                "order_name",
                "order_number",
                "current_location",
                "is_shenzhen_order",
                "last_order_synced_at",
            )[:MAX_SOURCE_ROWS]
        )
        synced_values = [order.get("last_order_synced_at") for order in local_orders if order.get("last_order_synced_at")]
        if synced_values:
            coverage["latest_local_order_synced_at"] = max(synced_values).isoformat()
        sync_state = (
            ShopifySyncState.objects.filter(task_name__in=REVIEW_REQUEST_ORDER_SYNC_TASK_NAMES)
            .order_by("-last_success_at", "-finished_at", "-updated_at")
            .first()
        )
        if sync_state and sync_state.last_success_at:
            coverage["latest_review_request_sync_finished_at"] = sync_state.last_success_at.isoformat()
            coverage["latest_review_request_sync_task_name"] = sync_state.task_name
            coverage["last_shopify_order_sync_window"] = _review_request_sync_window_label(sync_state.task_name)
        coverage["order_22530_found"] = _focus_order_found_locally("#22530")
        coverage["order_22562_found"] = _focus_order_found_locally("#22562")
    except Exception as exc:
        coverage["local_db_error_sanitized"] = _safe_exception_summary(exc)

    if coverage["latest_review_request_sync_finished_at"]:
        coverage["scan_source"] = "full_shopify_orders"
    elif coverage["local_last_60_days_order_count"] > 0:
        coverage["scan_source"] = (
            "shenzhen_only_orders"
            if coverage["local_last_60_days_non_shenzhen_order_count"] == 0
            else "full_shopify_orders"
        )
    elif source_by_order:
        coverage["scan_source"] = "fallback_report_only"
    else:
        coverage["scan_source"] = "fallback_report_only"

    warnings = []
    if coverage["scan_source"] != "full_shopify_orders":
        warnings.append("incomplete_local_order_source")
    if not coverage["order_22530_found"]:
        warnings.append("order_not_found_in_local_data")
    if coverage["delivered_order_data_missing_count"] > 0:
        warnings.append("delivered_order_data_missing")
    coverage["coverage_warnings"] = _dedupe_text(warnings)
    return coverage


def _review_request_sync_window_label(task_name):
    if task_name == "orders_review_request_3":
        return "latest 3 days"
    if task_name == "orders_review_request_60":
        return "last 60 days"
    if task_name == "orders_review_request_manual":
        return "manual Review Request window"
    return "Unknown"


def _focus_order_found_locally(order_name):
    query_names = set()
    query_numbers = set()
    query_shopify_ids = set()
    _collect_order_lookup_values(order_name, "", query_names, query_numbers, query_shopify_ids)
    query = Q()
    if query_names:
        query |= Q(order_name__in=query_names)
    if query_numbers:
        query |= Q(order_number__in=query_numbers)
    if query_shopify_ids:
        query |= Q(shopify_order_id__in=query_shopify_ids)
    if not query:
        return False
    return ShopifyOrder.objects.filter(query).exists()


def _focus_order_diagnosis(order_name, scan_contexts, eligible_rows, blocked_rows, already_sent_rows):
    context = scan_contexts.get(order_name) or {}
    row, section = _find_scan_order_row(
        {
            "eligible_queue_rows": eligible_rows,
            "blocked_queue_rows": blocked_rows,
            "already_sent_queue_rows": already_sent_rows,
        },
        order_name,
    )
    found_locally = context.get("local_order_source") == "ShopifyOrder"
    if not found_locally:
        message = f"{order_name} not found in local ShopifyOrder data. Run Review Request 60-day Shopify sync."
    else:
        message = f"{order_name} found in local ShopifyOrder data."
    tag_data_loaded = context.get("review_request_tag_data_loaded") is True or (row or {}).get(
        "review_request_tag_data_loaded"
    ) is True
    review_request_tag_present = (
        context.get("canonical_review_request_tag_present") is True
        or (row or {}).get("review_request_tag_present") is True
    )
    if not tag_data_loaded:
        review_request_tag_status = "unavailable"
    elif review_request_tag_present:
        review_request_tag_status = "present"
    else:
        review_request_tag_status = "missing"
    final_blockers = _focus_final_blockers(found_locally, row, tag_data_loaded)
    return {
        "order_name": order_name,
        "found_in_local_shopify_order": found_locally,
        "matched_field": _focus_matched_field(order_name, context) if found_locally else "",
        "matched_order_name": _safe_text(context.get("matched_order_name") or context.get("order_name"), max_length=80),
        "local_order_id": context.get("local_order_id", ""),
        "order_number": _safe_text(context.get("order_number"), max_length=120),
        "shopify_order_id": _safe_text(context.get("shopify_order_id"), max_length=120),
        "order_created_at": _safe_text(context.get("order_created_at"), max_length=80),
        "order_created_date": _date_part(context.get("order_created_at")),
        "fulfillment_status": _safe_text(context.get("fulfillment_status"), max_length=80),
        "shopify_note_present": context.get("shopify_note_present") is True,
        "included_in_candidate_scan": bool(row),
        "candidate_scan_section": section,
        "scan_date": _safe_text(context.get("scan_date"), max_length=120),
        "scan_date_basis": _safe_text(context.get("scan_date_basis"), max_length=80),
        "delivered_confirmed": context.get("delivered_confirmed"),
        "delivered_or_fulfilled_detected": context.get("delivered_confirmed") is True,
        "tag_data_available": tag_data_loaded,
        "review_request_tag_data_loaded": tag_data_loaded,
        "tag_data_missing_source": "" if tag_data_loaded else SHOPIFY_ORDER_TAGS_MISSING_SOURCE,
        "tag_data_recommended_action": "" if tag_data_loaded else SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
        "review_request_tag_status": review_request_tag_status,
        "review_request_tag_present": review_request_tag_present,
        "matched_review_request_tag_value": _safe_text(
            context.get("matched_review_request_tag_value")
            or (row or {}).get("matched_review_request_tag_value"),
            max_length=120,
        ),
        "final_eligibility_status": _focus_final_eligibility_status(found_locally, row, tag_data_loaded),
        "final_blockers": final_blockers,
        "message": message,
    }


def _focus_matched_field(order_name, context):
    target = _safe_text(order_name, max_length=120)
    target_canonical = _canonical_order_name(target)
    target_number = target_canonical.lstrip("#")
    if _canonical_order_name(context.get("matched_order_name") or context.get("order_name")) == target_canonical:
        return "order_name"
    if target_number and _safe_text(context.get("order_number"), max_length=120).lstrip("#") == target_number:
        return "order_number"
    if target_number and _safe_text(context.get("shopify_order_id"), max_length=120) == target_number:
        return "shopify_order_id"
    return ""


def _focus_final_eligibility_status(found_locally, row, tag_data_loaded):
    if not found_locally:
        return "not_found"
    action_state = _safe_text((row or {}).get("action_state"), max_length=80)
    if action_state == "review_send":
        return "eligible"
    if action_state == "already_sent":
        return "already_sent"
    if not tag_data_loaded:
        return "blocked"
    return "blocked" if row else "not_scanned"


def _focus_final_blockers(found_locally, row, tag_data_loaded):
    if not found_locally:
        return ["order_not_found_in_local_shopify_order"]
    blockers = _split_blocker_text((row or {}).get("eligibility_reason_plain") or (row or {}).get("reason"))
    if not tag_data_loaded:
        blockers.append("review_request_tag_data_unavailable")
    return _dedupe_text(blockers)


def _date_part(value):
    text = _safe_text(value, max_length=80)
    return text[:10] if len(text) >= 10 else text


def _last_60_day_order_scan_contexts(source_by_order, cutoff):
    source_order_names = sorted(_dedupe_order_names(list(source_by_order) + list(REVIEW_REQUEST_FOCUS_ORDER_NAMES)))
    query_names = set()
    query_numbers = set()
    query_shopify_ids = set()
    for order_name in source_order_names:
        _collect_order_lookup_values(order_name, "", query_names, query_numbers, query_shopify_ids)

    query = (
        Q(order_created_at__gte=cutoff)
        | Q(fulfilled_at__gte=cutoff)
        | Q(updated_at__gte=cutoff)
    )
    lookup_query = Q()
    if query_names:
        lookup_query |= Q(order_name__in=query_names)
    if query_numbers:
        lookup_query |= Q(order_number__in=query_numbers)
    if query_shopify_ids:
        lookup_query |= Q(shopify_order_id__in=query_shopify_ids)
    if lookup_query:
        query |= lookup_query

    contexts = {}
    local_db_error = ""
    value_fields = (
        "id",
        "order_name",
        "order_number",
        "shopify_order_id",
        "financial_status",
        "fulfillment_status",
        "customer_name",
        "customer_email",
        "order_created_at",
        "fulfilled_at",
        "fulfillment_status_raw",
        "updated_at",
        "settlement_status",
        "shopify_note",
        "shopify_note_attributes",
        "warehouse_note",
        "transfer_note",
    )
    try:
        orders = list(
            ShopifyOrder.objects.filter(query)
            .values(*value_fields)
            .order_by("-updated_at", "-order_created_at", "-id")[:MAX_SOURCE_ROWS]
        )
        if lookup_query:
            existing_ids = {order.get("id") for order in orders}
            for order in ShopifyOrder.objects.filter(lookup_query).values(*value_fields)[:MAX_SOURCE_ROWS]:
                if order.get("id") in existing_ids:
                    continue
                orders.append(order)
                existing_ids.add(order.get("id"))
    except Exception as exc:
        orders = []
        local_db_error = _safe_exception_summary(exc)

    for order in orders:
        order_name = _canonical_order_name(order.get("order_name") or order.get("order_number"))
        if not order_name:
            continue
        context = _scan_context_from_local_order(
            order,
            source_by_order.get(order_name) or {},
            cutoff,
        )
        if context.get("scan_date_in_window") or order_name in source_by_order:
            contexts[order_name] = context

    for order_name, source_row in source_by_order.items():
        if order_name in contexts:
            continue
        context = _scan_context_from_source_row(order_name, source_row, cutoff)
        if context.get("scan_date_in_window") or context.get("scan_date_missing"):
            contexts[order_name] = context
    return contexts, local_db_error


def _ensure_current_focus_scan_contexts(scan_contexts, source_by_order, cutoff):
    result = dict(scan_contexts)
    for order_name in REVIEW_REQUEST_FOCUS_ORDER_NAMES:
        if order_name in result:
            continue
        source_row = source_by_order.get(order_name) or {}
        if not source_row:
            continue
        result[order_name] = _scan_context_from_source_row(order_name, source_row, cutoff)
    return result


def _scan_context_from_local_order(order, source_row, cutoff):
    order_name = _canonical_order_name(order.get("order_name") or order.get("order_number"))
    date_context = _scan_date_context(order, source_row)
    delivered_confirmed = _scan_delivered_confirmed(source_row, order)
    canonical_tag_present = _scan_canonical_review_request_tag_present(source_row)
    tags = _dedupe_text(source_row.get("tags") or source_row.get("order_tags_display") or [])
    matched_review_request_tags = _matched_review_request_tags(tags)
    tag_data_loaded = _tag_data_loaded(source_row, tags)
    local_context = {
        "order_name": order_name,
        "matched_order_name": order_name,
        "local_order_id": order.get("id") or "",
        "order_number": _safe_text(order.get("order_number"), max_length=120),
        "shopify_order_id": _safe_text(order.get("shopify_order_id"), max_length=120),
        "customer_display_name": _safe_customer_display_name(order.get("customer_name")),
        "masked_email": mask_email(_safe_runtime_email(order.get("customer_email"))),
        "financial_status": _safe_text(order.get("financial_status"), max_length=80),
        "fulfillment_status": _safe_text(order.get("fulfillment_status"), max_length=80),
        "fulfillment_status_raw": _safe_text(order.get("fulfillment_status_raw"), max_length=120),
        "settlement_status": _safe_text(order.get("settlement_status"), max_length=80),
        "order_created_at": _safe_text(order.get("order_created_at"), max_length=80),
        "updated_at": _safe_text(order.get("updated_at"), max_length=80),
        "fulfilled_at": _safe_text(order.get("fulfilled_at"), max_length=80),
        "shopify_note_present": _order_note_present(order),
        "local_order_source": "ShopifyOrder",
        "delivered_confirmed": delivered_confirmed,
        "canonical_review_request_tag_present": canonical_tag_present,
        "tag_data_available": tag_data_loaded,
        "review_request_tag_data_loaded": tag_data_loaded,
        "tag_data_missing_source": "" if tag_data_loaded else SHOPIFY_ORDER_TAGS_MISSING_SOURCE,
        "tag_data_recommended_action": "" if tag_data_loaded else SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
        "matched_review_request_tag_value": matched_review_request_tags[0] if matched_review_request_tags else "",
        "scan_date_in_window": _datetime_in_window(date_context.get("scan_datetime"), cutoff),
        "scan_date_missing": date_context.get("scan_datetime") is None,
    }
    local_context.update(date_context)
    return local_context


def _scan_context_from_source_row(order_name, source_row, cutoff):
    date_context = _scan_date_context({}, source_row)
    tags = _dedupe_text(source_row.get("tags") or source_row.get("order_tags_display") or [])
    matched_review_request_tags = _matched_review_request_tags(tags)
    tag_data_loaded = _tag_data_loaded(source_row, tags)
    return {
        "order_name": order_name,
        "matched_order_name": order_name,
        "customer_display_name": _safe_customer_display_name(source_row.get("customer_display_name")),
        "masked_email": _safe_text(source_row.get("masked_email"), max_length=120),
        "financial_status": "",
        "fulfillment_status": "",
        "fulfillment_status_raw": "",
        "settlement_status": "",
        "local_order_source": "local_review_request_report",
        "delivered_confirmed": _scan_delivered_confirmed(source_row, {}),
        "canonical_review_request_tag_present": _scan_canonical_review_request_tag_present(source_row),
        "tag_data_available": tag_data_loaded,
        "review_request_tag_data_loaded": tag_data_loaded,
        "tag_data_missing_source": "" if tag_data_loaded else "Shopify tag data not loaded in local report source",
        "tag_data_recommended_action": "" if tag_data_loaded else SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
        "matched_review_request_tag_value": matched_review_request_tags[0] if matched_review_request_tags else "",
        "scan_date_in_window": _datetime_in_window(date_context.get("scan_datetime"), cutoff),
        "scan_date_missing": date_context.get("scan_datetime") is None,
        **date_context,
    }


def _order_note_present(order):
    if _safe_text(order.get("shopify_note"), max_length=20):
        return True
    note_attributes = order.get("shopify_note_attributes")
    return note_attributes not in (None, "", [], {})


def _scan_date_context(order, source_row):
    delivered_dt = _first_datetime_value(
        source_row,
        (
            "delivered_at",
            "delivered_date",
            "delivery_date",
            "deliveredAt",
            "delivered_time",
            "delivery_time",
        ),
    )
    if delivered_dt:
        return {
            "scan_datetime": delivered_dt,
            "scan_date": delivered_dt.isoformat(),
            "scan_date_basis": "delivered_date",
            "scan_date_fallback_used": False,
        }
    for basis, value in (
        ("fulfilled_at", order.get("fulfilled_at")),
        ("updated_at", order.get("updated_at")),
        ("order_created_at", order.get("order_created_at")),
        ("source_created_at", source_row.get("created_at")),
    ):
        parsed = _parse_datetime_value(value)
        if parsed:
            return {
                "scan_datetime": parsed,
                "scan_date": parsed.isoformat(),
                "scan_date_basis": basis,
                "scan_date_fallback_used": True,
            }
    return {
        "scan_datetime": None,
        "scan_date": "",
        "scan_date_basis": "unavailable",
        "scan_date_fallback_used": True,
    }


def _first_datetime_value(mapping, keys):
    if not isinstance(mapping, dict):
        return None
    for key in keys:
        parsed = _parse_datetime_value(mapping.get(key))
        if parsed:
            return parsed
    return None


def _parse_datetime_value(value):
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        text = _safe_text(value, max_length=80)
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _datetime_in_window(value, cutoff):
    return bool(value and value >= cutoff)


def _scan_delivered_confirmed(source_row, order):
    tags = _dedupe_text(source_row.get("tags") or source_row.get("order_tags_display") or [])
    if source_row.get("delivered_tag_present") is True or has_delivered_tag(tags) or "妥投" in tags:
        return True
    fulfillment_values = {
        _safe_text(order.get(key), max_length=160).lower()
        for key in ("fulfillment_status", "fulfillment_status_raw")
        if _safe_text(order.get(key), max_length=160)
    }
    if "fulfilled" in fulfillment_values:
        return True
    if source_row.get("delivered_tag_present") is False:
        return False
    status_text = " ".join(
        _safe_text(value, max_length=160).lower()
        for value in (
            source_row.get("status"),
            source_row.get("blocking_summary"),
            source_row.get("classification"),
            order.get("fulfillment_status"),
            order.get("fulfillment_status_raw"),
            order.get("warehouse_note"),
        )
    )
    if "not delivered" in status_text or "missing delivered" in status_text:
        return False
    if "delivered" in status_text or "妥投" in status_text:
        return True
    return None


def _scan_canonical_review_request_tag_present(source_row):
    tags = _dedupe_text(source_row.get("tags") or source_row.get("order_tags_display") or [])
    tags_loaded = _tag_data_loaded(source_row, tags)
    if source_row.get("canonical_review_request_tag_present") is True:
        return True
    if source_row.get("review_request_tag_present") is True:
        return True
    if has_review_request_tag(tags):
        return True
    if not tags_loaded:
        return None
    if source_row.get("canonical_review_request_tag_present") is False:
        return False
    reason_text = " ".join(
        _safe_text(source_row.get(key), max_length=240).lower()
        for key in ("reason", "blocking_summary", "status", "classification")
    )
    if "missing" in reason_text and CANONICAL_REVIEW_REQUEST_TAG in reason_text:
        return False
    if tags_loaded:
        return False
    return None


def _tag_data_loaded(source_row, tags):
    if tags:
        return True
    return any(
        _tag_payload_available(source_row.get(key))
        for key in (
            "tags",
            "order_tags_display",
            "safe_tags_summary",
            "tags_summary",
            "tags_of_interest",
            "exact_tags_of_interest",
        )
    )


def _tag_payload_available(value):
    if value in (None, "", [], {}):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = _safe_text(value, max_length=160).lower()
        return text not in {
            "no tag data",
            "no tag data in row",
            "tag data not loaded",
            "shopify tag data not loaded",
            "unavailable",
            "none",
            "[]",
        }
    if isinstance(value, dict):
        return any(_tag_payload_available(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_tag_payload_available(item) for item in value)
    return True


def _scan_queue_source_row(order_name, source_row, scan_context, local_context):
    row = dict(source_row or {})
    tags = _dedupe_text(row.get("tags") or row.get("order_tags_display") or [])
    trustpilot_tags = _matched_trustpilot_tags(row, tags)
    matched_review_request_tags = _matched_review_request_tags(tags)
    blocking_reasons = _dedupe_text(row.get("blocking_reasons") or [])
    if _scan_local_risk_detected(scan_context):
        blocking_reasons.append("blocked_risk_or_ticket")
    delivered = scan_context.get("delivered_confirmed")
    canonical_tag_present = scan_context.get("canonical_review_request_tag_present")
    blocking_reasons = _filtered_scan_blocking_reasons(
        blocking_reasons,
        canonical_tag_present,
        row,
        local_context,
    )
    row.update(
        {
            "order_name": order_name,
            "masked_email": (
                _safe_text(row.get("masked_email"), max_length=120)
                or _safe_text(scan_context.get("masked_email"), max_length=120)
                or _safe_text(local_context.get("masked_email"), max_length=120)
            ),
            "customer_display_name": (
                _safe_customer_display_name(local_context.get("customer_display_name"))
                or _safe_customer_display_name(scan_context.get("customer_display_name"))
                or _safe_customer_display_name(row.get("customer_display_name"))
            ),
            "customer_order_count": _int_or_zero(local_context.get("customer_order_count"))
            or _int_or_zero(row.get("customer_order_count")),
            "local_order_id": scan_context.get("local_order_id", ""),
            "matched_order_name": scan_context.get("matched_order_name") or order_name,
            "order_number": scan_context.get("order_number", ""),
            "shopify_order_id": scan_context.get("shopify_order_id", ""),
            "order_created_at": scan_context.get("order_created_at", ""),
            "fulfillment_status": scan_context.get("fulfillment_status", ""),
            "shopify_note_present": scan_context.get("shopify_note_present") is True,
            "tags": tags,
            "tag_data_available": scan_context.get("tag_data_available") is True,
            "tag_data_missing_source": _safe_text(scan_context.get("tag_data_missing_source"), max_length=240),
            "tag_data_recommended_action": _safe_text(scan_context.get("tag_data_recommended_action"), max_length=300),
            "trustpilot_tags": trustpilot_tags,
            "trustpilot_invitation_present": bool(trustpilot_tags)
            or row.get("trustpilot_invitation_present") is True,
            "delivered_tag_present": delivered is True,
            "canonical_review_request_tag_present": canonical_tag_present,
            "review_request_tag_present": canonical_tag_present,
            "review_request_tag_data_loaded": scan_context.get("review_request_tag_data_loaded") is True,
            "matched_review_request_tag_value": (
                scan_context.get("matched_review_request_tag_value")
                or (matched_review_request_tags[0] if matched_review_request_tags else "")
            ),
            "blocking_reasons": _dedupe_text(blocking_reasons),
            "source_section": "last_60_days_delivered_order_scan",
            "eligible_for_trustpilot": True,
            "scan_date": scan_context.get("scan_date", ""),
            "scan_date_basis": scan_context.get("scan_date_basis", ""),
            "scan_date_fallback_used": scan_context.get("scan_date_fallback_used") is True,
        }
    )
    return row


def _scan_local_risk_detected(scan_context):
    text = " ".join(
        _safe_text(scan_context.get(key), max_length=160).lower()
        for key in ("financial_status", "fulfillment_status", "settlement_status")
    )
    return any(
        keyword in text
        for keyword in ("refund", "returned", "return", "cancel", "cancelled", "void", "dispute", "chargeback")
    )


def _filtered_scan_blocking_reasons(blocking_reasons, review_request_tag_status, row, local_context=None):
    local_context = local_context or {}
    local_repeat_confirmed = _int_or_zero(local_context.get("customer_order_count")) > 1
    filtered = []
    for blocker in blocking_reasons or []:
        text = _safe_text(blocker, max_length=160).lower()
        if review_request_tag_status is True and "missing_review_request_tag" in text:
            continue
        if review_request_tag_status is True and "missing" in text and "review request" in text:
            continue
        if "merged_order_group_not_ready" in text and not _row_has_explicit_merge_evidence(row):
            continue
        if local_repeat_confirmed and (
            "repeat_customer_not_confirmed" in text
            or "first_order" in text
            or "first order" in text
        ):
            continue
        filtered.append(blocker)
    return _dedupe_text(filtered)


def _attach_scan_date_context(queue_row, scan_context):
    queue_row["scan_date"] = scan_context.get("scan_date", "")
    queue_row["scan_date_basis"] = scan_context.get("scan_date_basis", "")
    queue_row["scan_date_fallback_used"] = scan_context.get("scan_date_fallback_used") is True
    queue_row["scan_date_note"] = (
        f"Date fallback: {queue_row['scan_date_basis']}"
        if queue_row["scan_date_fallback_used"]
        else "Delivered date"
    )
    return queue_row


def _blocked_queue_sort_key(row):
    priority = 0 if "#22582" in [row.get("order"), *(row.get("group_order_names") or [])] else 1
    return (priority, row.get("order", ""))


def _already_sent_sort_key(row):
    preferred = {"#22621": 0, "#22620": 1}
    return (preferred.get(row.get("order"), 9), row.get("order", ""))


def _row_blocked_by_merged_group(row):
    text = _row_block_text(row)
    return bool(row.get("merged_order_group") or "merged" in text or "related order" in text)


def _row_blocked_by_duplicate(row):
    text = _row_block_text(row)
    return "already sent" in text or "duplicate" in text or "trustpilot invitation" in text


def _row_blocked_by_missing_review_request_tag(row):
    text = _row_block_text(row)
    if row.get("review_request_tag_present") is True:
        return False
    if row.get("review_request_tag_data_loaded") is False and "missing `1: review request`" not in text:
        return False
    status_label = _safe_text(row.get("review_request_tag_status_label"), max_length=160).lower()
    return status_label.startswith("missing") or "missing `1: review request`" in text


def _row_blocked_by_not_delivered(row):
    text = _row_block_text(row)
    return row.get("delivered_status_label") == "Not delivered" or "not delivered" in text or "missing delivered" in text


def _row_block_text(row):
    return " ".join(
        _safe_text(row.get(key), max_length=500).lower()
        for key in ("reason", "eligibility_reason_plain", "evidence", "status", "trustpilot_history_label")
    )


def _queue_candidate_summary(row):
    return {
        "order": _safe_text(row.get("order"), max_length=80),
        "customer": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Masked in reports",
        "masked_customer": _safe_text(row.get("masked_customer_label"), max_length=120),
        "customer_order_count": _int_or_zero(row.get("customer_order_count")),
        "tags": _dedupe_text(row.get("order_tags_display") or []),
        "tag_data_available": row.get("tag_data_available") is True,
        "review_request_tag_present": row.get("review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": _safe_text(row.get("matched_review_request_tag_value"), max_length=120),
        "review_request_tag_match_detail": _safe_text(row.get("review_request_tag_match_detail"), max_length=180),
        "delivered_status": _safe_text(row.get("delivered_status_label"), max_length=80),
        "trustpilot_history": _safe_text(row.get("trustpilot_history_label"), max_length=300),
        "reason": _safe_text(row.get("eligibility_reason_plain"), max_length=500),
        "action": "Review & Send",
        "scan_date": _safe_text(row.get("scan_date"), max_length=80),
        "scan_date_basis": _safe_text(row.get("scan_date_basis"), max_length=80),
        "scan_date_fallback_used": row.get("scan_date_fallback_used") is True,
    }


def _blocked_candidate_summary(row):
    return {
        "order_or_group": (
            _safe_text(row.get("merged_group_compact_label"), max_length=160)
            if row.get("merged_order_group")
            else _safe_text(row.get("order"), max_length=80)
        ),
        "order": _safe_text(row.get("order"), max_length=80),
        "group_order_names": row.get("group_order_names") or [],
        "customer": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Masked in reports",
        "tags": _dedupe_text(row.get("order_tags_display") or []),
        "tag_data_available": row.get("tag_data_available") is True,
        "tag_data_missing_source": _safe_text(row.get("tag_data_missing_source"), max_length=240),
        "tag_data_recommended_action": _safe_text(row.get("tag_data_recommended_action"), max_length=300),
        "review_request_tag_present": row.get("review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": _safe_text(row.get("matched_review_request_tag_value"), max_length=120),
        "review_request_tag_match_detail": _safe_text(row.get("review_request_tag_match_detail"), max_length=180),
        "delivered_status": _safe_text(row.get("delivered_status_label"), max_length=80),
        "merged_group_evidence_source": _safe_text(row.get("merged_group_evidence_source"), max_length=160),
        "block_reason": _safe_text(row.get("eligibility_reason_plain"), max_length=500),
        "missing_requirement": _blocked_missing_requirement(row),
        "evidence": _safe_text(row.get("evidence") or row.get("reason"), max_length=500),
        "scan_date": _safe_text(row.get("scan_date"), max_length=80),
        "scan_date_basis": _safe_text(row.get("scan_date_basis"), max_length=80),
        "scan_date_fallback_used": row.get("scan_date_fallback_used") is True,
    }


def _already_sent_summary(row):
    return {
        "order": _safe_text(row.get("order"), max_length=80),
        "customer": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Masked in reports",
        "trustpilot_email_status": _safe_text(row.get("trustpilot_email_status"), max_length=120),
        "evidence": _safe_text(row.get("evidence"), max_length=500),
        "tags": _dedupe_text(row.get("order_tags_display") or []),
        "tag_data_available": row.get("tag_data_available") is True,
        "review_request_tag_present": row.get("review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": _safe_text(row.get("matched_review_request_tag_value"), max_length=120),
        "delivered_status": _safe_text(row.get("delivered_status_label"), max_length=80),
    }


def _blocked_missing_requirement(row):
    missing = []
    if _row_blocked_by_not_delivered(row):
        missing.append("Delivered / 妥投")
    if row.get("review_request_tag_data_loaded") is not True and row.get("review_request_tag_present") is not True:
        missing.append("Shopify tag data loaded")
    if _row_blocked_by_missing_review_request_tag(row):
        missing.append(CANONICAL_REVIEW_REQUEST_TAG)
    if _row_blocked_by_merged_group(row):
        missing.append("Whole merged/related group ready")
    if _row_blocked_by_duplicate(row):
        missing.append("No prior Trustpilot send")
    text = _row_block_text(row)
    if "gmail" in text:
        missing.append("Gmail permission")
    if "risk" in text or "ticket" in text or "refund" in text or "dispute" in text:
        missing.append("No ticket/refund/risk")
    return ", ".join(_dedupe_text(missing)) or "Manual review"


def _scan_date_summary(context):
    return {
        "order": _safe_text(context.get("order_name"), max_length=80),
        "scan_date": _safe_text(context.get("scan_date"), max_length=80),
        "scan_date_basis": _safe_text(context.get("scan_date_basis"), max_length=80),
        "delivered_confirmed": context.get("delivered_confirmed") is True,
    }


def _last_60_days_issue_summary(scan):
    warnings = scan.get("coverage_warnings") or []
    warning_text = f" Coverage warnings: {', '.join(warnings)}." if warnings else ""
    return (
        f"Scan source: {scan.get('scan_source', 'unknown')}. "
        f"Scanned {scan.get('scanned_order_count', 0)} local/reported orders; "
        f"{scan.get('eligible_candidate_count', 0)} eligible, "
        f"{scan.get('already_sent_count', 0)} already sent, "
        f"{scan.get('blocked_count', 0)} blocked/not ready."
        f"{warning_text} "
        "No Gmail, Shopify, Trustpilot, Kudosi, or Ali Reviews API calls were performed."
    )


def _apply_merged_order_group_guard(needs_review_rows, already_sent_rows, source_row_groups):
    source_row_groups = tuple(source_row_groups or ())
    base_order_names = _queue_group_base_order_names(
        needs_review_rows,
        already_sent_rows,
        *source_row_groups,
    )
    order_to_group, groups = _merged_order_group_index(
        base_order_names,
        needs_review_rows,
        already_sent_rows,
        *source_row_groups,
    )
    if not groups:
        return needs_review_rows, already_sent_rows, _merged_group_summary([])

    already_sent_orders = {row.get("order") for row in already_sent_rows if row.get("order")}
    already_sent_customers = {
        row.get("customer")
        for row in already_sent_rows
        if _usable_masked_customer(row.get("customer"))
    }
    source_by_order = _source_rows_by_order(
        *source_row_groups,
        needs_review_rows,
        already_sent_rows,
    )
    group_states = {
        group["group_key"]: _merged_group_state(
            group,
            source_by_order,
            already_sent_orders,
            already_sent_customers,
        )
        for group in groups
    }

    guarded_needs_review_rows = []
    for row in needs_review_rows:
        order_name = _safe_text(row.get("order"), max_length=80)
        group = order_to_group.get(order_name)
        if group:
            group = group_states[group["group_key"]]
            _decorate_queue_row_with_merged_group(row, group)
            if row.get("action_state") == "already_sent":
                already_sent_rows.append(row)
                continue
        guarded_needs_review_rows.append(row)

    for row in already_sent_rows:
        order_name = _safe_text(row.get("order"), max_length=80)
        group = order_to_group.get(order_name)
        if group:
            _decorate_queue_row_with_merged_group(row, group_states[group["group_key"]])

    return (
        _collapse_merged_group_rows(guarded_needs_review_rows),
        _collapse_merged_group_rows(already_sent_rows),
        _merged_group_summary(group_states.values()),
    )


def _queue_group_base_order_names(*row_groups):
    names = []
    for rows in row_groups:
        for row in rows or []:
            order_name = _row_order_name(row)
            if order_name:
                names.append(order_name)
            names.extend(row.get("explicit_related_order_names") or [])
            if row.get("explicit_related_order_reference"):
                names.extend(row.get("related_order_names") or [])
            names.extend(_merged_order_names_from_row_text(row))
    return _dedupe_order_names(names)


def _merged_order_group_index(order_names, *row_groups):
    parent = {}

    def add(name):
        canonical = _canonical_order_name(name)
        if canonical and canonical not in parent:
            parent[canonical] = canonical
        return canonical

    def find(name):
        name = add(name)
        while parent[name] != name:
            parent[name] = parent[parent[name]]
            name = parent[name]
        return name

    def union(names):
        group_names = _dedupe_order_names(names)
        if len(group_names) < 2:
            return
        root = find(group_names[0])
        for name in group_names[1:]:
            parent[find(name)] = root

    for name in order_names or []:
        add(name)

    for rows in row_groups:
        for row in rows or []:
            group_names = _merged_order_group_names_from_row(row)
            if len(group_names) >= 2:
                union(group_names)

    local_references = _local_merged_order_reference_contexts(parent.keys())
    for order_name, context in local_references.items():
        related_names = context.get("related_order_names") or []
        if related_names:
            union([order_name] + related_names)

    components = {}
    for name in list(parent):
        components.setdefault(find(name), []).append(name)

    groups = []
    order_to_group = {}
    for names in components.values():
        group_order_names = _sort_order_names(names)
        if len(group_order_names) < 2:
            continue
        group = {
            "group_key": "merged:" + "|".join(group_order_names),
            "group_order_names": group_order_names,
            "group_size": len(group_order_names),
            "primary_order_name": group_order_names[0],
            "evidence_source": _merged_group_evidence_source(group_order_names, row_groups, local_references),
        }
        groups.append(group)
        for order_name in group_order_names:
            order_to_group[order_name] = group
    return order_to_group, groups


def _merged_order_group_names_from_row(row):
    order_name = _row_order_name(row)
    names = []
    if row.get("explicit_related_order_names"):
        names.extend(row.get("explicit_related_order_names") or [])
    elif row.get("explicit_related_order_reference"):
        names.extend(row.get("related_order_names") or [])
    names.extend(_merged_order_names_from_row_text(row))
    names = _dedupe_order_names(names)
    if order_name and names:
        names.append(order_name)
    return _dedupe_order_names(names)


def _merged_group_evidence_source(group_order_names, row_groups, local_references):
    group_set = set(_dedupe_order_names(group_order_names))
    for order_name, context in (local_references or {}).items():
        context_names = set(_dedupe_order_names([order_name] + (context.get("related_order_names") or [])))
        if len(group_set & context_names) >= 2:
            return context.get("reference_source") or "local_order_note_reference"
    for rows in row_groups or ():
        for row in rows or []:
            names = set(_merged_order_group_names_from_row(row))
            if len(group_set & names) < 2:
                continue
            if _row_has_explicit_merge_evidence(row):
                return _safe_text(row.get("source_path") or row.get("source"), max_length=160) or "explicit_report_merge_evidence"
            if row.get("explicit_related_order_reference"):
                return "runtime_explicit_related_order_reference"
    return "explicit_merge_evidence"


def _merged_order_names_from_row_text(row):
    text = " ".join(
        _safe_text(row.get(key), max_length=500)
        for key in _MERGE_EVIDENCE_TEXT_KEYS
    )
    return _merged_order_names_from_text(text)


def _row_order_name(row):
    return _canonical_order_name(
        row.get("order")
        or row.get("order_name")
        or row.get("selected_order")
        or row.get("selected_order_name")
    )


def _is_simulator_order_name(value):
    return _safe_text(value, max_length=80).upper().startswith("#SIM")


def _local_merged_order_reference_contexts(order_names):
    normalized_names = _dedupe_order_names(order_names or [])
    if not normalized_names:
        return {}

    query_names = set()
    query_numbers = set()
    query_shopify_ids = set()
    for order_name in normalized_names:
        _collect_order_lookup_values(order_name, "", query_names, query_numbers, query_shopify_ids)

    query = Q()
    if query_names:
        query |= Q(order_name__in=query_names)
    if query_numbers:
        query |= Q(order_number__in=query_numbers)
    if query_shopify_ids:
        query |= Q(shopify_order_id__in=query_shopify_ids)
    if not query:
        return {}

    try:
        local_orders = list(
            ShopifyOrder.objects.filter(query).values(
                "order_name",
                "order_number",
                "shopify_order_id",
                "shopify_note",
                "shopify_note_attributes",
                "warehouse_note",
                "transfer_note",
                "order_created_at",
                "customer_name",
                "customer_email",
            )[:MAX_SOURCE_ROWS]
        )
    except Exception:
        return {}

    contexts_by_lookup_key = {}
    for order in local_orders:
        order_name = _canonical_order_name(order.get("order_name") or order.get("order_number"))
        if not order_name:
            continue
        related_order_names = []
        for field in (
            "shopify_note",
            "shopify_note_attributes",
            "warehouse_note",
            "transfer_note",
        ):
            for fragment in _note_text_fragments(order.get(field)):
                related_order_names.extend(_merged_order_names_from_text(fragment))
        related_order_names = [
            name for name in _dedupe_order_names(related_order_names) if name != order_name
        ]
        if not related_order_names:
            continue
        context = {
            "order_name": order_name,
            "related_order_names": related_order_names,
            "customer_display_name": _safe_customer_display_name(order.get("customer_name")),
            "masked_email": mask_email(_safe_runtime_email(order.get("customer_email"))),
            "order_created_at": _safe_text(order.get("order_created_at"), max_length=80),
            "reference_source": "local_order_note_reference",
        }
        for key in _order_lookup_keys(
            order.get("order_name"),
            order.get("order_number"),
            order.get("shopify_order_id"),
        ):
            contexts_by_lookup_key[key] = context

    result = {}
    for order_name in normalized_names:
        for key in _order_lookup_keys(order_name):
            context = contexts_by_lookup_key.get(key)
            if context:
                result[order_name] = context
                break
    return result


def _note_text_fragments(value):
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        fragments = []
        for item in value.values():
            fragments.extend(_note_text_fragments(item))
        return fragments
    if isinstance(value, (list, tuple, set)):
        fragments = []
        for item in value:
            fragments.extend(_note_text_fragments(item))
        return fragments
    text = _safe_text(value, max_length=1000)
    return [text] if text else []


def _source_rows_by_order(*row_groups):
    rows_by_order = {}
    for rows in row_groups:
        for row in rows or []:
            order_name = _row_order_name(row)
            if not order_name:
                continue
            existing = rows_by_order.get(order_name)
            rows_by_order[order_name] = _merge_group_source_rows(existing, row)
    return rows_by_order


def _apply_manual_confirmed_order_evidence(rows_by_order):
    result = dict(rows_by_order or {})
    for order_name, evidence in MANUAL_CONFIRMED_ORDER_EVIDENCE.items():
        existing = result.get(order_name)
        result[order_name] = _merge_group_source_rows(existing, evidence)
    return result


def _merge_group_source_rows(existing, row):
    if not existing:
        return dict(row)
    merged = dict(existing)
    for key, value in (row or {}).items():
        if key in {"tags", "order_tags_display", "trustpilot_tags", "related_order_names", "explicit_related_order_names"}:
            merged[key] = _dedupe_text(_as_text_list(merged.get(key)) + _as_text_list(value))
        elif key not in merged or merged.get(key) in (None, "", [], False):
            merged[key] = value
    return merged


def _as_text_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return [value]


def _merged_group_state(group, source_by_order, already_sent_orders, already_sent_customers):
    order_states = [
        _merged_group_order_state(
            order_name,
            source_by_order.get(order_name) or {},
            already_sent_orders,
            already_sent_customers,
        )
        for order_name in group["group_order_names"]
    ]
    prior_sent_states = [state for state in order_states if state["prior_trustpilot_sent"]]
    risk_states = [state for state in order_states if state["risk_blocked"]]
    missing_readiness_states = [state for state in order_states if not state["readiness_source_present"]]
    delivered_ready = all(state["delivered_ready"] for state in order_states)
    review_request_tag_ready = all(state["review_request_tag_ready"] for state in order_states)
    related_order_ready = all(
        state["readiness_source_present"]
        and state["delivered_ready"]
        and state["review_request_tag_ready"]
        and not state["risk_blocked"]
        for state in order_states
    )
    prior_order_name = ""
    if prior_sent_states:
        prior_order_name = (
            prior_sent_states[0]["prior_trustpilot_order_name"]
            or prior_sent_states[0]["order_name"]
        )
    group_state = dict(group)
    group_state.update(
        {
            "group_customer_display": _merged_group_customer_display(order_states),
            "group_delivered_ready": delivered_ready,
            "group_review_request_tag_ready": review_request_tag_ready,
            "group_prior_trustpilot_sent": bool(prior_sent_states),
            "group_prior_trustpilot_order_name": prior_order_name,
            "group_risk_blocked": bool(risk_states),
            "group_related_order_ready": related_order_ready,
            "group_eligible_for_review_send": (
                related_order_ready and not prior_sent_states and not risk_states
            ),
            "group_order_states": order_states,
            "group_missing_readiness_order_names": [
                state["order_name"] for state in missing_readiness_states
            ],
        }
    )
    group_state["group_block_reasons"] = _merged_group_block_reasons(group_state)
    group_state["group_block_reason_plain"] = _merged_group_block_reason_plain(group_state)
    return group_state


def _merged_group_order_state(order_name, row, already_sent_orders, already_sent_customers):
    tags = _dedupe_text((row.get("tags") or []) + (row.get("order_tags_display") or []))
    reason = " ".join(
        _safe_text(row.get(key), max_length=300)
        for key in ("reason", "eligibility_reason_plain", "evidence", "blocking_summary", "status")
    )
    delivered = _queue_delivered_status(row, tags, reason)
    if delivered is None and row.get("delivered_status_label") == "Delivered":
        delivered = True
    if delivered is None and row.get("delivered_status_label") == "Not delivered":
        delivered = False
    review_request_tag_present = _queue_review_request_tag_present(row, tags, reason)
    if review_request_tag_present is None and row.get("review_request_tag_present") is True:
        review_request_tag_present = True
    if review_request_tag_present is None and "missing" in reason.lower() and CANONICAL_REVIEW_REQUEST_TAG in reason:
        review_request_tag_present = False
    customer = _safe_text(row.get("customer") or row.get("masked_email"), max_length=120)
    prior_order_name = _safe_text(row.get("prior_trustpilot_order_name"), max_length=80)
    trustpilot_sent = bool(
        row.get("action_state") == "already_sent"
        or order_name in already_sent_orders
        or (
            _usable_masked_customer(customer)
            and customer in already_sent_customers
        )
        or _queue_trustpilot_already_sent(
            row.get("action_state"),
            row,
            row.get("trustpilot_tags") or [],
            prior_order_name,
        )
    )
    if trustpilot_sent and not prior_order_name:
        prior_order_name = order_name
    risk_text = reason.lower()
    risk_blocked = bool(
        _row_has_returned_package(row)
        or _row_has_risk_or_ticket(row)
        or any(
            keyword in risk_text
            for keyword in ("risk", "ticket", "refund", "cancel", "cancelled", "dispute", "chargeback", "complaint")
        )
    )
    return {
        "order_name": order_name,
        "readiness_source_present": bool(row),
        "delivered_ready": delivered is True,
        "review_request_tag_ready": review_request_tag_present is True,
        "prior_trustpilot_sent": trustpilot_sent,
        "prior_trustpilot_order_name": prior_order_name,
        "risk_blocked": risk_blocked,
        "customer": customer,
        "customer_display_name": _safe_text(row.get("customer_display_name"), max_length=120),
    }


def _merged_group_customer_display(order_states):
    for state in order_states:
        if state.get("customer_display_name"):
            return state["customer_display_name"]
    for state in order_states:
        if _usable_masked_customer(state.get("customer")):
            return state["customer"]
    return "Masked in reports"


def _merged_group_block_reasons(group):
    reasons = []
    if group.get("group_prior_trustpilot_sent"):
        prior = group.get("group_prior_trustpilot_order_name") or "another order"
        reasons.append(f"This merged order group already received a Trustpilot email via {prior}.")
    missing_readiness = group.get("group_missing_readiness_order_names") or []
    if missing_readiness:
        reasons.append(f"Readiness evidence is missing for {_join_order_names(missing_readiness)}.")
    not_delivered = [
        state["order_name"]
        for state in group.get("group_order_states", [])
        if state["readiness_source_present"] and not state["delivered_ready"]
    ]
    if not_delivered:
        reasons.append(f"{_join_order_names(not_delivered)} not delivered.")
    missing_tag = [
        state["order_name"]
        for state in group.get("group_order_states", [])
        if state["readiness_source_present"] and not state["review_request_tag_ready"]
    ]
    if missing_tag:
        reasons.append(f"{_join_order_names(missing_tag)} missing a review-request tag alias.")
    risk_orders = [
        state["order_name"]
        for state in group.get("group_order_states", [])
        if state["risk_blocked"]
    ]
    if risk_orders:
        reasons.append(f"{_join_order_names(risk_orders)} has risk, ticket, refund, cancel, or dispute evidence.")
    return _dedupe_text(reasons)


def _merged_group_block_reason_plain(group):
    compact_names = _compact_order_names(group.get("group_order_names") or [])
    if group.get("group_prior_trustpilot_sent"):
        prior = group.get("group_prior_trustpilot_order_name") or "another order"
        return f"This merged order group already received a Trustpilot email via {prior}."
    prefix = (
        f"Merged order group is not ready. {compact_names} were shipped together, "
        "so the system will not send a separate Trustpilot email for only one order."
    )
    details = " ".join(group.get("group_block_reasons") or [])
    return f"{prefix} {details}".strip()


def _decorate_queue_row_with_merged_group(row, group):
    order_name = _safe_text(row.get("order"), max_length=80)
    row.update(
        {
            "merged_order_group": True,
            "merged_group_label": f"Merged group: {_join_order_names(group['group_order_names'])}",
            "merged_group_compact_label": _compact_order_names(group["group_order_names"]),
            "group_order_names": group["group_order_names"],
            "group_size": group["group_size"],
            "group_customer_display": group["group_customer_display"],
            "group_delivered_ready": group["group_delivered_ready"],
            "group_review_request_tag_ready": group["group_review_request_tag_ready"],
            "group_prior_trustpilot_sent": group["group_prior_trustpilot_sent"],
            "group_prior_trustpilot_order_name": group["group_prior_trustpilot_order_name"],
            "group_risk_blocked": group["group_risk_blocked"],
            "group_related_order_ready": group["group_related_order_ready"],
            "group_eligible_for_review_send": group["group_eligible_for_review_send"],
            "group_block_reasons": group["group_block_reasons"],
            "merged_group_key": group["group_key"],
            "merged_group_primary_order_name": group["primary_order_name"],
            "merged_group_evidence_source": group.get("evidence_source", "explicit_merge_evidence"),
            "customer_orders_display": f"Merged group: {_join_order_names(group['group_order_names'])}",
        }
    )
    row["customer_order_sequence_label"] = _merged_group_sequence_label(
        order_name,
        group["group_order_names"],
        row.get("customer_order_sequence_label"),
    )
    row["tag_chips"] = _dedupe_chip_rows(
        (row.get("tag_chips") or [])
        + [{"label": "Merged order group", "css_class": "rrw-badge-info"}]
    )
    if group["group_prior_trustpilot_sent"]:
        evidence = _merged_group_block_reason_plain(group)
        row.update(
            {
                "status": "Already sent",
                "status_class": "rrw-badge-ok",
                "reason": evidence,
                "evidence": evidence,
                "eligibility_reason_plain": evidence,
                "trustpilot_email_status": "Already sent",
                "trustpilot_history_label": evidence,
                "action_state": "already_sent",
            }
        )
    elif not group["group_eligible_for_review_send"]:
        reason = _merged_group_block_reason_plain(group)
        row.update(
            {
                "status": "Not ready",
                "status_class": "rrw-badge-warn",
                "reason": reason,
                "eligibility_reason_plain": reason,
                "action_state": "not_ready",
            }
        )
    elif order_name != group["primary_order_name"]:
        reason = (
            f"Merged order group will be handled once via {group['primary_order_name']}; "
            "this related order will not get a separate Trustpilot email."
        )
        row.update(
            {
                "status": "Not ready",
                "status_class": "rrw-badge-warn",
                "reason": reason,
                "eligibility_reason_plain": reason,
                "action_state": "not_ready",
            }
        )
    row["eligibility_status"] = _queue_eligibility_status(row.get("action_state"))
    row["eligibility_status_label"] = _queue_eligibility_status_label(row.get("action_state"))
    row["action_status"] = _queue_action_status(row.get("action_state"))


def _collapse_merged_group_rows(rows):
    result = []
    index_by_group = {}
    for row in rows or []:
        group_key = row.get("merged_group_key")
        if not group_key:
            result.append(row)
            continue
        existing_index = index_by_group.get(group_key)
        if existing_index is None:
            index_by_group[group_key] = len(result)
            result.append(row)
            continue
        existing = result[existing_index]
        if row.get("order") == row.get("merged_group_primary_order_name") and existing.get("order") != existing.get(
            "merged_group_primary_order_name"
        ):
            result[existing_index] = row
    return result


def _merged_group_summary(groups):
    group_rows = []
    for group in groups or []:
        group_rows.append(
            {
                "group_order_names": group.get("group_order_names") or [],
                "group_size": group.get("group_size") or 0,
                "group_eligible_for_review_send": group.get("group_eligible_for_review_send") is True,
                "group_block_reasons": group.get("group_block_reasons") or [],
                "group_prior_trustpilot_sent": group.get("group_prior_trustpilot_sent") is True,
                "evidence_source": group.get("evidence_source") or "explicit_merge_evidence",
            }
        )
    return {
        "merged_group_count": len(group_rows),
        "merged_groups": group_rows,
    }


def _sort_order_names(names):
    def key(value):
        text = _canonical_order_name(value)
        match = re.fullmatch(r"#(\d{3,})", text)
        if match:
            return (0, -int(match.group(1)))
        return (1, text)

    return sorted(_dedupe_order_names(names), key=key)


def _join_order_names(names):
    return " / ".join(_sort_order_names(names))


def _compact_order_names(names):
    return "/".join(_sort_order_names(names))


def _merged_group_sequence_label(order_name, group_order_names, current_label):
    current = _safe_text(current_label, max_length=80)
    if current and current != "Order count unknown":
        return current
    ascending_names = list(reversed(_sort_order_names(group_order_names)))
    if order_name in ascending_names:
        return f"{_ordinal(ascending_names.index(order_name) + 1)} order"
    return "Merged order group"


def _needs_review_queue_row(
    row,
    already_sent_orders,
    already_sent_customers,
    gmail_setup,
    local_context=None,
):
    order_name = _safe_text(row.get("order_name"), max_length=80)
    customer = (
        _safe_text(row.get("masked_email"), max_length=120)
        or _safe_text((local_context or {}).get("masked_email"), max_length=120)
        or "Masked in reports"
    )
    blockers = _candidate_send_blockers(
        row,
        already_sent_orders=already_sent_orders,
        already_sent_customers=already_sent_customers,
        gmail_setup=gmail_setup,
    )
    if order_name in already_sent_orders or (
        _usable_masked_customer(customer) and customer in already_sent_customers
    ):
        return _apply_queue_row_context(
            {
                "candidate_id": order_name,
                "order": order_name,
                "customer": customer,
                "status": "Already sent",
                "status_class": "rrw-badge-ok",
                "reason": _already_sent_reason(order_name),
                "action_state": "already_sent",
                "source": _safe_text(row.get("source"), max_length=120),
            },
            row,
            local_context or {},
            action_state="already_sent",
        )
    if blockers:
        return _apply_queue_row_context(
            {
                "candidate_id": order_name,
                "order": order_name,
                "customer": customer,
                "status": "Not ready",
                "status_class": "rrw-badge-warn",
                "reason": "; ".join(blockers),
                "action_state": "not_ready",
                "source": _safe_text(row.get("source"), max_length=120),
            },
            row,
            local_context or {},
            action_state="not_ready",
        )
    return _apply_queue_row_context(
        {
            "candidate_id": order_name,
            "order": order_name,
            "customer": customer,
            "status": "Ready",
            "status_class": "rrw-badge-ok",
            "reason": "Delivered, tagged, and no duplicate or risk found.",
            "action_state": "review_send",
            "source": _safe_text(row.get("source"), max_length=120),
        },
        row,
        local_context or {},
        action_state="review_send",
    )


def _candidate_send_blockers(row, already_sent_orders, already_sent_customers, gmail_setup):
    blockers = []
    order_name = _safe_text(row.get("order_name"), max_length=80)
    customer = _safe_text(row.get("masked_email"), max_length=120)
    algorithm_ready = (
        row.get("eligible_for_trustpilot") is True
        or row.get("source_section") == "ready_candidate_queue"
    )
    if not algorithm_ready:
        blockers.append("Not selected by the latest readiness check.")
    if order_name in already_sent_orders:
        blockers.append(_already_sent_reason(order_name))
    if _usable_masked_customer(customer) and customer in already_sent_customers:
        blockers.append("Already sent to this customer.")
    if row.get("trustpilot_invitation_present") is True:
        blockers.append("Already sent to this order.")
    if row.get("delivered_tag_present") is not True:
        blockers.append("Not delivered yet.")
    review_request_tag_status = row.get("canonical_review_request_tag_present")
    if review_request_tag_status is None and row.get("review_request_tag_data_loaded") is not True:
        blockers.append("Shopify tag data not loaded, cannot confirm review request tag.")
    elif review_request_tag_status is not True:
        blockers.append(f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`.")
    if row.get("blocking_reasons"):
        blockers.append(_plain_blocked_reason(row))
    if _row_has_returned_package(row):
        blockers.append("Return or returned-package risk found.")
    if _row_has_risk_or_ticket(row):
        blockers.append("Ticket, refund, cancel, dispute, or complaint risk found.")
    if row.get("customer_level_duplicate_block_applies") is True:
        blockers.append("Already sent to this customer.")
    if row.get("existing_unsent_gmail_draft_should_not_be_sent") is True:
        blockers.append("Already sent to this customer.")
    related_status = _safe_text(row.get("merged_or_related_order_guard_status"), max_length=80).lower()
    if (
        related_status
        and related_status not in {"passed", "ready", "ok"}
        and _row_has_explicit_merge_evidence(row)
    ):
        blockers.append("Related orders are not ready.")
    return _dedupe_text(blockers)


def _known_not_ready_queue_row(order_name, customer, source_row=None, local_context=None):
    return _apply_queue_row_context(
        {
            "candidate_id": order_name,
            "order": order_name,
            "customer": (
                _safe_text(customer, max_length=120)
                or _safe_text((local_context or {}).get("masked_email"), max_length=120)
                or "Masked in reports"
            ),
            "status": "Not ready",
            "status_class": "rrw-badge-warn",
            "reason": (
                "Not delivered, missing a review-request tag alias, "
                "related #22582/#22581 not ready."
            ),
            "action_state": "not_ready",
            "source": "Current operating rule",
        },
        source_row or {},
        local_context or {},
        action_state="not_ready",
        fallback_related_orders=["#22582", "#22581"],
    )


def _already_sent_rows(focus, trustpilot_email_records, invitation_history, blocked_orders):
    rows = []
    order_22620 = (focus.get("order_22620") or {}) if isinstance(focus, dict) else {}
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
            "status": "Already sent",
            "status_class": "rrw-badge-ok",
            "evidence": "Trustpilot email already sent and recorded.",
            "reason": "Trustpilot email already sent and recorded.",
            "action_state": "already_sent",
            "prior_trustpilot_order_name": prior_order,
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
            "status": "Already sent",
            "status_class": "rrw-badge-ok",
            "evidence": f"Already sent to this customer via {prior_order}.",
            "reason": f"Already sent to this customer via {prior_order}.",
            "action_state": "already_sent",
            "prior_trustpilot_order_name": prior_order,
        }
    )
    for record in trustpilot_email_records or []:
        if record.get("email_sent") is not True:
            continue
        order_name = _safe_text(record.get("order_name"), max_length=80)
        if not order_name:
            continue
        rows.append(
            {
                "order": order_name,
                "customer": record.get("masked_email") or "Masked in reports",
                "status": "Already sent",
                "status_class": "rrw-badge-ok",
                "evidence": _record_evidence_label(record),
                "reason": _record_evidence_label(record),
                "action_state": "already_sent",
                "prior_trustpilot_order_name": order_name,
            }
        )
    for row in invitation_history or []:
        order_name = _safe_text(row.get("order_name"), max_length=80)
        if not order_name:
            continue
        rows.append(
            {
                "order": order_name,
                "customer": row.get("masked_email") or "Masked in reports",
                "status": "Already sent",
                "status_class": "rrw-badge-ok",
                "evidence": "Trustpilot tag or invitation history found.",
                "reason": "Trustpilot tag or invitation history found.",
                "action_state": "already_sent",
                "prior_trustpilot_order_name": order_name,
            }
        )
    return _dedupe_queue_rows(rows)


def _approval_queue_order_names(
    candidate_queue,
    blocked_orders,
    invitation_history,
    trustpilot_email_records,
    already_sent_rows,
):
    names = {"#22581", "#22582", "#22620", "#22621"}
    for rows in (
        candidate_queue,
        blocked_orders,
        invitation_history,
        trustpilot_email_records,
        already_sent_rows,
    ):
        for row in rows or []:
            order_name = _safe_text(
                row.get("order_name") or row.get("order") or row.get("selected_order"),
                max_length=80,
            )
            if order_name:
                names.add(order_name)
            for related_order in (row.get("explicit_related_order_names") or []) + (
                row.get("related_order_names") or []
            ):
                related = _safe_text(related_order, max_length=80)
                if related:
                    names.add(_canonical_order_name(related))
    return sorted(names)


def _source_row_for_order(order_name, *row_groups):
    target = _safe_text(order_name, max_length=80)
    if not target:
        return {}
    for rows in row_groups:
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            if _safe_text(row.get("order_name") or row.get("order"), max_length=80) == target:
                return row
    return {}


def _local_order_contexts(order_names):
    normalized_names = sorted(
        {
            _safe_text(order_name, max_length=80)
            for order_name in order_names or []
            if _safe_text(order_name, max_length=80)
        }
    )
    if not normalized_names:
        return {}

    query_names = set()
    query_numbers = set()
    query_shopify_ids = set()
    for order_name in normalized_names:
        _collect_order_lookup_values(order_name, "", query_names, query_numbers, query_shopify_ids)

    query = Q()
    if query_names:
        query |= Q(order_name__in=query_names)
    if query_numbers:
        query |= Q(order_number__in=query_numbers)
    if query_shopify_ids:
        query |= Q(shopify_order_id__in=query_shopify_ids)
    if not query:
        return {}

    try:
        selected_orders = list(
            ShopifyOrder.objects.filter(query).values(
                "id",
                "order_name",
                "order_number",
                "shopify_order_id",
                "customer_name",
                "customer_email",
                "order_created_at",
            )[:MAX_SOURCE_ROWS]
        )
        customer_emails = sorted(
            {
                _safe_runtime_email(order.get("customer_email"))
                for order in selected_orders
                if _safe_runtime_email(order.get("customer_email"))
            }
        )
        customer_orders = []
        if customer_emails:
            customer_orders = list(
                ShopifyOrder.objects.filter(customer_email__in=customer_emails)
                .values("id", "order_name", "customer_email", "order_created_at")
                .order_by("customer_email", "order_created_at", "id")[:MAX_SOURCE_ROWS]
            )
    except Exception:
        return {}

    orders_by_email = {}
    for order in customer_orders:
        email = _safe_runtime_email(order.get("customer_email"))
        if email:
            orders_by_email.setdefault(email, []).append(order)

    contexts_by_lookup_key = {}
    for order in selected_orders:
        email = _safe_runtime_email(order.get("customer_email"))
        customer_orders_for_email = orders_by_email.get(email, []) if email else []
        sequence = _customer_order_sequence(order, customer_orders_for_email)
        order_count = len(customer_orders_for_email) if customer_orders_for_email else 0
        order_names_for_email = [
            _safe_text(item.get("order_name"), max_length=80)
            for item in customer_orders_for_email
            if _safe_text(item.get("order_name"), max_length=80)
        ]
        context = {
            "customer_display_name": _safe_customer_display_name(order.get("customer_name")),
            "masked_email": mask_email(email),
            "customer_order_count": order_count,
            "customer_order_sequence": sequence,
            "customer_order_sequence_label": _customer_order_sequence_label(
                order_count,
                sequence,
                repeat_detected=order_count > 1,
            ),
            "customer_order_names": order_names_for_email[:5],
        }
        for key in _order_lookup_keys(
            order.get("order_name"),
            order.get("order_number"),
            order.get("shopify_order_id"),
        ):
            contexts_by_lookup_key[key] = context

    contexts = {}
    for order_name in normalized_names:
        for key in _order_lookup_keys(order_name):
            if key in contexts_by_lookup_key:
                contexts[order_name] = contexts_by_lookup_key[key]
                break
    return contexts


def _customer_order_sequence(order, customer_orders):
    order_id = order.get("id")
    order_name = _safe_text(order.get("order_name"), max_length=80)
    for index, customer_order in enumerate(customer_orders or [], start=1):
        if customer_order.get("id") == order_id:
            return index
        if _safe_text(customer_order.get("order_name"), max_length=80) == order_name:
            return index
    return 0


def _apply_queue_row_context(
    row,
    source_row,
    local_context,
    action_state,
    fallback_related_orders=None,
):
    source_row = source_row or {}
    local_context = local_context or {}
    order_name = _safe_text(row.get("order"), max_length=80)
    masked_customer = (
        _safe_text(row.get("customer"), max_length=120)
        or _safe_text(source_row.get("masked_email"), max_length=120)
        or _safe_text(local_context.get("masked_email"), max_length=120)
        or "Masked in reports"
    )
    if masked_customer != "Masked in reports" and not _usable_masked_customer(masked_customer):
        masked_customer = _safe_text(local_context.get("masked_email"), max_length=120) or "Masked in reports"
    customer_display_name = (
        _safe_text(local_context.get("customer_display_name"), max_length=120)
        or _safe_text(source_row.get("customer_display_name"), max_length=120)
        or "Masked in reports"
    )
    source_count = _int_or_zero(source_row.get("customer_order_count"))
    local_count = _int_or_zero(local_context.get("customer_order_count"))
    customer_order_count = local_count or source_count
    sequence = _int_or_zero(local_context.get("customer_order_sequence"))
    repeat_detected = (
        source_row.get("repeat_customer_detected") is True
        or customer_order_count > 1
    )
    sequence_label = (
        _safe_text(local_context.get("customer_order_sequence_label"), max_length=80)
        or _customer_order_sequence_label(
            customer_order_count,
            sequence,
            repeat_detected=repeat_detected,
        )
    )
    explicit_related_order_names = (
        _dedupe_order_names(source_row.get("explicit_related_order_names") or [])
        or _dedupe_order_names(fallback_related_orders or [])
    )
    related_order_names = explicit_related_order_names or _dedupe_order_names(
        source_row.get("related_order_names") or []
    )
    tags = _dedupe_text(source_row.get("tags") or row.get("order_tags_display") or [])
    trustpilot_tags = _dedupe_text(source_row.get("trustpilot_tags") or [])
    delivered = _queue_delivered_status(source_row, tags, row.get("reason", ""))
    review_request_present = _queue_review_request_tag_present(source_row, tags, row.get("reason", ""))
    matched_review_request_tags = _matched_review_request_tags(tags)
    matched_review_request_tag_value = (
        _safe_text(source_row.get("matched_review_request_tag_value"), max_length=120)
        or (matched_review_request_tags[0] if matched_review_request_tags else "")
    )
    review_request_tag_data_loaded = (
        source_row.get("review_request_tag_data_loaded") is True
        or _tag_data_loaded(source_row, tags)
    )
    prior_order_name = (
        _safe_text(row.get("prior_trustpilot_order_name"), max_length=80)
        or _safe_text(source_row.get("prior_trustpilot_order_name"), max_length=80)
    )
    if order_name == "#22620" and not prior_order_name:
        prior_order_name = "#22621"
    trustpilot_sent = _queue_trustpilot_already_sent(
        action_state,
        source_row,
        trustpilot_tags,
        prior_order_name,
    )
    history_label = _trustpilot_history_label(
        order_name=order_name,
        action_state=action_state,
        prior_order_name=prior_order_name,
        trustpilot_sent=trustpilot_sent,
        source_row=source_row,
        evidence=row.get("evidence") or row.get("reason", ""),
    )

    row.update(
        {
            "order_name": order_name,
            "customer": masked_customer,
            "masked_customer": masked_customer,
            "masked_customer_label": masked_customer if _usable_masked_customer(masked_customer) else "",
            "customer_display_name": customer_display_name,
            "customer_order_count": customer_order_count,
            "customer_order_sequence_label": sequence_label,
            "customer_orders_display": _customer_orders_display(
                customer_order_count,
                sequence_label,
                related_order_names,
            ),
            "related_order_names": related_order_names,
            "explicit_related_order_names": explicit_related_order_names,
            "explicit_related_order_reference": bool(explicit_related_order_names),
            "order_tags_display": tags,
            "has_order_tags": bool(tags),
            "tag_data_available": review_request_tag_data_loaded,
            "tag_data_missing_source": (
                ""
                if review_request_tag_data_loaded
                else _safe_text(source_row.get("tag_data_missing_source"), max_length=240)
                or SHOPIFY_ORDER_TAGS_MISSING_SOURCE
            ),
            "tag_data_recommended_action": (
                ""
                if review_request_tag_data_loaded
                else _safe_text(source_row.get("tag_data_recommended_action"), max_length=300)
                or SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION
            ),
            "tag_chips": _queue_tag_chips(
                tags,
                delivered=delivered,
                review_request_present=review_request_present,
                trustpilot_sent=trustpilot_sent,
                action_state=action_state,
            ),
            "delivered_status_label": _queue_delivered_status_label(delivered),
            "delivered_status_class": _queue_status_css_class(delivered),
            "review_request_tag_present": review_request_present is True,
            "review_request_tag_data_loaded": review_request_tag_data_loaded,
            "matched_review_request_tag_value": matched_review_request_tag_value,
            "review_request_tag_match_detail": _review_request_tag_match_detail(matched_review_request_tag_value),
            "review_request_tag_status_label": (
                "Review request tag found"
                if review_request_present is True
                else (
                    f"Missing {CANONICAL_REVIEW_REQUEST_TAG}"
                    if review_request_present is False
                    else "Shopify tag data not loaded"
                )
            ),
            "review_request_tag_status_class": (
                _queue_status_css_class(review_request_present)
            ),
            "trustpilot_already_sent_to_customer": trustpilot_sent,
            "prior_trustpilot_order_name": prior_order_name,
            "trustpilot_history_label": history_label,
            "trustpilot_email_status": (
                "Already sent" if trustpilot_sent else "No previous Trustpilot email found"
            ),
            "eligibility_status": _queue_eligibility_status(action_state),
            "eligibility_status_label": _queue_eligibility_status_label(action_state),
            "eligibility_reason_plain": _safe_text(row.get("reason"), max_length=500),
            "action_status": _queue_action_status(action_state),
        }
    )
    row["evidence"] = _safe_text(row.get("evidence") or row.get("reason"), max_length=500)
    return row


def _safe_customer_display_name(value):
    text = _safe_text(value, max_length=120)
    if not text or EMAIL_RE.search(text):
        return ""
    return text


def _customer_order_sequence_label(order_count, sequence, repeat_detected=False):
    count = _int_or_zero(order_count)
    seq = _int_or_zero(sequence)
    if seq > 0:
        return f"{_ordinal(seq)} order"
    if count > 1 or repeat_detected:
        return "Repeat customer"
    if count == 1:
        return "1st order"
    return "Order count unknown"


def _customer_orders_display(order_count, sequence_label, related_order_names):
    related = [_safe_text(name, max_length=80) for name in related_order_names or [] if _safe_text(name, max_length=80)]
    if related:
        return "Related " + " / ".join(related)
    count = _int_or_zero(order_count)
    if count > 0:
        noun = "order" if count == 1 else "orders"
        return f"{count} {noun}; {sequence_label}"
    return sequence_label or "Order count unknown"


def _ordinal(value):
    number = _int_or_zero(value)
    if 10 <= number % 100 <= 20:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _queue_delivered_status(source_row, tags, reason):
    if source_row.get("delivered_tag_present") is True or has_delivered_tag(tags):
        return True
    text = " ".join(
        [
            _safe_text(reason, max_length=300).lower(),
            _safe_text(source_row.get("blocking_summary"), max_length=300).lower(),
            _safe_text(source_row.get("status"), max_length=300).lower(),
        ]
    )
    if "not delivered" in text or "missing delivered" in text:
        return False
    return None


def _queue_review_request_tag_present(source_row, tags, reason):
    tags_loaded = _tag_data_loaded(source_row, tags)
    if source_row.get("canonical_review_request_tag_present") is True:
        return True
    if source_row.get("review_request_tag_present") is True:
        return True
    if has_review_request_tag(tags):
        return True
    if tags_loaded:
        if source_row.get("canonical_review_request_tag_present") is False:
            return False
    else:
        return None
    text = _safe_text(reason, max_length=300).lower()
    if f"missing {CANONICAL_REVIEW_REQUEST_TAG}" in text or (
        "missing" in text and CANONICAL_REVIEW_REQUEST_TAG in text
    ):
        return False
    if tags_loaded:
        return False
    return None


def _queue_delivered_status_label(value):
    if value is True:
        return "Delivered"
    if value is False:
        return "Not delivered"
    return "Delivery status unknown"


def _review_request_tag_match_detail(matched_tag):
    tag = _safe_text(matched_tag, max_length=120)
    if not tag:
        return ""
    if _normalize_trustpilot_tag(tag) == _normalize_trustpilot_tag(TYPO_REVIEW_REQUEST_TAG):
        return f"Matched legacy typo tag: {tag}"
    return f"Matched review request tag: {tag}"


def _queue_status_css_class(value):
    if value is True:
        return "rrw-badge-ok"
    if value is False:
        return "rrw-badge-warn"
    return "rrw-badge-muted"


def _queue_trustpilot_already_sent(action_state, source_row, trustpilot_tags, prior_order_name):
    return bool(
        action_state == "already_sent"
        or trustpilot_tags
        or prior_order_name
        or source_row.get("trustpilot_invitation_present") is True
        or source_row.get("customer_level_duplicate_block_applies") is True
        or source_row.get("existing_unsent_gmail_draft_should_not_be_sent") is True
    )


def _trustpilot_history_label(
    order_name,
    action_state,
    prior_order_name,
    trustpilot_sent,
    source_row,
    evidence,
):
    if action_state == "already_sent":
        if prior_order_name and prior_order_name != order_name:
            return f"Already sent to this customer via {prior_order_name}"
        return _safe_text(evidence, max_length=300) or "Trustpilot email already sent and recorded"
    if prior_order_name:
        return f"Already sent to this customer via {prior_order_name}"
    if trustpilot_sent:
        return "Already sent to this customer"
    if source_row:
        return "No previous Trustpilot email found"
    return "Previous Trustpilot status unknown"


def _queue_tag_chips(tags, delivered, review_request_present, trustpilot_sent, action_state):
    chips = [
        {"label": tag, "css_class": _queue_tag_css_class(tag)}
        for tag in tags
    ]
    if not chips:
        chips.append({"label": "Shopify tag data not loaded", "css_class": "rrw-badge-muted"})
    if delivered is True:
        chips.append({"label": "Delivered", "css_class": "rrw-badge-ok"})
    elif delivered is False and action_state != "already_sent":
        chips.append({"label": "Missing Delivered", "css_class": "rrw-badge-warn"})
    if review_request_present is True:
        chips.append({"label": "Review request tag found", "css_class": "rrw-badge-ok"})
    elif review_request_present is False and action_state != "already_sent":
        chips.append(
            {
                "label": f"Missing {CANONICAL_REVIEW_REQUEST_TAG}",
                "css_class": "rrw-badge-warn",
            }
        )
    if trustpilot_sent:
        chips.append({"label": "Trustpilot sent", "css_class": "rrw-badge-info"})
    return _dedupe_chip_rows(chips)


def _queue_tag_css_class(tag):
    normalized = _normalize_trustpilot_tag(tag)
    if normalized in {_normalize_trustpilot_tag(alias) for alias in DELIVERED_TAG_ALIASES}:
        return "rrw-badge-ok"
    if normalized in {_normalize_trustpilot_tag(alias) for alias in REVIEW_REQUEST_TAG_ALIASES}:
        return "rrw-badge-ok"
    if normalized in {_normalize_trustpilot_tag(alias) for alias in TRUSTPILOT_TAG_ALIASES}:
        return "rrw-badge-info"
    if re.search(r"(?i)(return|refund|cancel|dispute|chargeback|ticket|complaint)", str(tag or "")):
        return "rrw-badge-bad"
    return "rrw-badge-muted"


def _dedupe_chip_rows(chips):
    seen = set()
    result = []
    for chip in chips:
        key = (chip.get("label"), chip.get("css_class"))
        if key in seen:
            continue
        seen.add(key)
        result.append(chip)
    return result


def _queue_eligibility_status(action_state):
    if action_state == "review_send":
        return "eligible"
    if action_state == "already_sent":
        return "already_sent"
    return "blocked"


def _queue_eligibility_status_label(action_state):
    if action_state == "review_send":
        return "Eligible"
    if action_state == "already_sent":
        return "Already sent"
    return "Not ready"


def _queue_action_status(action_state):
    if action_state == "review_send":
        return "Review & Send"
    if action_state == "already_sent":
        return "Already sent"
    return "Not ready"


def _dedupe_queue_rows(rows):
    seen = set()
    result = []
    for row in rows or []:
        key = (row.get("order") or "", row.get("customer") or "", row.get("status") or "")
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _approval_queue_sort_key(row):
    action_order = {"review_send": 0, "not_ready": 1, "already_sent": 2}
    return (action_order.get(row.get("action_state"), 9), row.get("order", ""))


def _usable_masked_customer(value):
    text = _safe_text(value, max_length=120)
    return bool(text and text != "Masked in reports" and "***" in text and "@" in text)


def _already_sent_reason(order_name):
    if order_name == "#22620":
        return "Already sent to this customer via #22621."
    return "Already sent to this customer."


def _review_send_selected_rows(approval_queue, selected_order):
    selected = _canonical_order_name(selected_order)
    if not selected:
        return []
    rows = []
    for row in (approval_queue.get("needs_review_rows") or []) + (
        approval_queue.get("already_sent_rows") or []
    ):
        if row.get("candidate_id") == selected or row.get("order") == selected:
            rows.append(row)
            continue
        if selected in (row.get("group_order_names") or []):
            rows.append(row)
    return rows


def _review_send_selection_blocker(selected_order, selected_rows):
    for row in selected_rows or []:
        if row.get("merged_order_group"):
            if row.get("group_prior_trustpilot_sent"):
                return {
                    "status": "blocked_merged_order_group_already_sent",
                    "detail": (
                        row.get("eligibility_reason_plain")
                        or "No email was sent. This merged order group already received a Trustpilot email."
                    ),
                }
            return {
                "status": "blocked_merged_order_group_not_ready",
                "detail": "No email was sent. This merged order group is not ready.",
            }
        if row.get("action_state") == "already_sent":
            return {
                "status": "blocked_order_already_sent",
                "detail": row.get("evidence") or row.get("reason") or "No email was sent. This order already received Trustpilot.",
            }
        if row.get("action_state") == "not_ready":
            return {
                "status": "blocked_order_not_ready",
                "detail": row.get("eligibility_reason_plain") or "No email was sent. This order is not ready.",
            }
    return {
        "status": "blocked_order_not_eligible",
        "detail": "No email was sent. This order is not eligible.",
    }


def _runtime_review_send_group_blockers(candidate):
    if not candidate.get("merged_order_group"):
        return []
    blockers = []
    if candidate.get("group_prior_trustpilot_sent") is True:
        blockers.append(
            {
                "status": "blocked_merged_order_group_already_sent",
                "detail": (
                    candidate.get("eligibility_reason_plain")
                    or "No email was sent. This merged order group already received a Trustpilot email."
                ),
            }
        )
    if candidate.get("group_eligible_for_review_send") is not True:
        blockers.append(
            {
                "status": "blocked_merged_order_group_not_ready",
                "detail": "No email was sent. This merged order group is not ready.",
            }
        )
    if candidate.get("order") != candidate.get("merged_group_primary_order_name"):
        blockers.append(
            {
                "status": "blocked_merged_order_group_non_primary_order",
                "detail": "No email was sent. This related order is not the merged group send row.",
            }
        )
    return blockers


def _base_review_and_send_result(selected_order, admin_username, state):
    queue = state["approval_queue"]
    gmail_setup = state["gmail_setup"]
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_trustpilot_review_and_send_execute",
        "task_name": "shopify_review_request_trustpilot_review_and_send_execute",
        "phase": "5.26",
        "mode": "admin_review_and_send",
        "execution_status": "blocked_not_started",
        "success": False,
        "selected_order": selected_order,
        "selected_customer": "",
        "selected_merged_group_order_names": [],
        "selected_merged_group_size": 0,
        "selected_merged_group_eligible_for_review_send": False,
        "selected_merged_group_block_reasons": [],
        "selected_merged_group_prior_trustpilot_sent": False,
        "candidate_verified": False,
        "review_and_send_requested": True,
        "admin_user": _safe_text(admin_username, max_length=120),
        "needs_review_count": queue["needs_review_count"],
        "already_sent_count": queue["already_sent_count"],
        "ready_to_send_count": queue["ready_to_send_count"],
        "not_ready_count": queue["not_ready_count"],
        "gmail_scope_status": gmail_setup.get("scope_status") or "scope_missing",
        "gmail_compose_send_supported": bool(gmail_setup.get("gmail_compose_send_supported")),
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_id_partial": "",
        "gmail_draft_send_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "gmail_message_id_partial": "",
        "email_sent": False,
        "sent_count": 0,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "template_status": "",
        "template_subject": "",
        "blocking_conditions": [],
        "blocking_condition_count": 0,
        "blocking_status": "",
        "blocking_detail": "",
        "next_admin_action": "No email was sent. Review the blocker message.",
        "privacy_scan_summary": {},
        "report_paths": {
            "json": f"logs/{REVIEW_AND_SEND_REPORT_FILENAME}",
            "html": f"logs/{REVIEW_AND_SEND_HTML_FILENAME}",
        },
    }


def _runtime_review_send_blockers(candidate, gmail_setup):
    blockers = []
    if not candidate.get("order") or candidate.get("action_state") != "review_send":
        blockers.append(
            {
                "status": "blocked_order_not_eligible",
                "detail": "No email was sent. This order is not eligible.",
            }
        )
    if str(candidate.get("order", "")).startswith("#SIM"):
        blockers.append(
            {
                "status": "blocked_simulator_candidate",
                "detail": "No email was sent. Simulator candidates cannot send real email.",
            }
        )
    if not gmail_setup.get("gmail_compose_send_supported"):
        blockers.append(
            {
                "status": "blocked_missing_gmail_compose_send_support",
                "detail": "No email was sent. Gmail sending permission is not ready.",
            }
        )
    if not gmail_setup.get("ready"):
        blockers.append(
            {
                "status": "blocked_gmail_setup_not_ready",
                "detail": "No email was sent. Gmail sending setup is not ready.",
            }
        )
    return blockers


def _split_runtime_scopes(value):
    return [item for item in re.split(r"[\s,]+", str(value or "").strip()) if item]


def _runtime_scope_status(compose_present, send_present, broad_present):
    if broad_present:
        return "broad_mail_scope_available"
    if send_present:
        return "gmail_send_scope_available"
    if compose_present:
        return "gmail_compose_only"
    return "scope_missing"


def _safe_runtime_email(value):
    text = str(value or "").strip().lower()
    if text and "***" not in text and EMAIL_RE.fullmatch(text):
        return text
    return ""


def _safe_exception_summary(exc):
    text = str(exc or "")
    text = re.sub(r"(?i)(/drafts/)[A-Za-z0-9_-]{8,}", r"\1[redacted-gmail-draft-id]", text)
    text = re.sub(r"(?i)(/messages/)[A-Za-z0-9_-]{8,}", r"\1[redacted-gmail-message-id]", text)
    text = re.sub(
        r"(?i)\b(draft(?:_?id)?|message(?:_?id)?|id)\s*[:=]\s*[\"']?[A-Za-z0-9_-]{8,}",
        r"\1=[redacted-gmail-id]",
        text,
    )
    return _safe_text(f"{exc.__class__.__name__}: {text}", max_length=400)


def _finalize_review_and_send_result(result):
    result["success"] = result.get("email_sent") is True
    result["blocking_condition_count"] = len(result.get("blocking_conditions") or [])
    if not result.get("blocking_status") and result.get("blocking_conditions"):
        result["blocking_status"] = result["blocking_conditions"][0].get("status", "")
    if not result.get("blocking_detail") and result.get("blocking_conditions"):
        result["blocking_detail"] = result["blocking_conditions"][0].get("detail", "")
    result["privacy_scan_summary"] = _review_send_privacy_scan(result)
    if not result["privacy_scan_summary"]["passed"] and not result.get("email_sent"):
        result["execution_status"] = "blocked_privacy_scan_failed"
        result["blocking_conditions"].append(
            {
                "status": "blocked_privacy_scan_failed",
                "detail": "No email was sent. The local report privacy scan failed.",
            }
        )
        result["blocking_condition_count"] = len(result["blocking_conditions"])
        result["success"] = False
    json_path = _write_review_and_send_json_report(result)
    html_path = _write_review_and_send_html_report(result)
    result["json_path"] = str(json_path)
    result["html_path"] = str(html_path)
    return result


def _write_review_and_send_json_report(payload):
    path = _log_dir() / REVIEW_AND_SEND_REPORT_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return path


def _write_review_and_send_html_report(payload):
    path = _log_dir() / REVIEW_AND_SEND_HTML_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_render_review_and_send_html(payload), encoding="utf-8")
    return path


def _render_review_and_send_html(payload):
    blocking_rows = "\n".join(
        (
            "<tr>"
            f"<td>{escape(item.get('status', ''))}</td>"
            f"<td>{escape(item.get('detail', ''))}</td>"
            "</tr>"
        )
        for item in payload.get("blocking_conditions", [])
    ) or '<tr><td colspan="2">None</td></tr>'
    safety_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td>{escape(str(payload.get(key)))}</td></tr>"
        for key in (
            "gmail_api_call_performed",
            "gmail_draft_create_attempted",
            "gmail_draft_send_attempted",
            "email_sent",
            "shopify_write_performed",
            "shopify_tag_write_performed",
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Review &amp; Send Execute</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Review &amp; Send Execute</h1>
  <p>Status: <strong>{escape(payload.get("execution_status", ""))}</strong></p>
  <table><tbody>
    <tr><th>Selected order</th><td>{escape(payload.get("selected_order", ""))}</td></tr>
    <tr><th>Selected customer</th><td>{escape(payload.get("selected_customer", ""))}</td></tr>
    <tr><th>Candidate verified</th><td>{escape(str(payload.get("candidate_verified") is True))}</td></tr>
    <tr><th>Gmail scope status</th><td><code>{escape(payload.get("gmail_scope_status", ""))}</code></td></tr>
    <tr><th>Email sent</th><td>{escape(str(payload.get("email_sent") is True))}</td></tr>
    <tr><th>Next admin action</th><td>{escape(payload.get("next_admin_action", ""))}</td></tr>
  </tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _review_send_privacy_scan(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = []
    for match in EMAIL_RE.finditer(text):
        value = match.group(0).lower()
        if value == GMAIL_SEND_FROM.lower() or "***" in value:
            continue
        raw_emails.append(mask_email(value))
    full_id_count = len(
        re.findall(r'"gmail_(?:draft|message)_id"\s*:\s*"[^"]+"', text)
    )
    token_count = 1 if SECRET_VALUE_RE.search(text) else 0
    return {
        "scan_performed": True,
        "passed": not raw_emails and not full_id_count and not token_count,
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "token_secret_bearer_pattern_count": token_count,
        "full_gmail_draft_or_message_id_field_count": full_id_count,
    }


def _order_count_text(count, suffix):
    noun = "order" if count == 1 else "orders"
    return f"{count} {noun} {suffix}"


def _gmail_setup_summary(gmail_helper, compatibility_audit=None, scope_resolver=None, env_loading_audit=None):
    compatibility_audit = compatibility_audit or {}
    scope_resolver = scope_resolver or {}
    env_loading_audit = env_loading_audit or {}
    dependencies_ready = (
        gmail_helper.get("gmail_dependencies_importable") is True
        or compatibility_audit.get("gmail_dependencies_importable") is True
    )
    new_file_paths_ready = (
        gmail_helper.get("gmail_send_from_email_configured") is True
        and gmail_helper.get("gmail_oauth_client_secret_path_exists") is True
        and gmail_helper.get("gmail_oauth_token_path_exists") is True
    )
    legacy_config_detected = (
        gmail_helper.get("legacy_gmail_oauth_config_present") is True
        or compatibility_audit.get("legacy_gmail_oauth_config_present") is True
    )
    send_scope_present = (
        gmail_helper.get("gmail_send_scope_present") is True
        or compatibility_audit.get("gmail_send_scope_present") is True
        or scope_resolver.get("send_scope_available") is True
        or env_loading_audit.get("os_environ_send_scope_detected") is True
    )
    broad_mail_scope_present = (
        gmail_helper.get("gmail_broad_mail_scope_present") is True
        or scope_resolver.get("broad_mail_scope_available") is True
        or env_loading_audit.get("os_environ_broad_mail_scope_detected") is True
    )
    real_send_scope_available = (
        gmail_helper.get("real_send_scope_available") is True
        or scope_resolver.get("real_send_scope_available") is True
        or send_scope_present
        or broad_mail_scope_present
    )
    compose_scope_present = (
        gmail_helper.get("gmail_compose_scope_present") is True
        or compatibility_audit.get("gmail_compose_scope_present") is True
        or scope_resolver.get("compose_scope_available") is True
        or env_loading_audit.get("os_environ_compose_scope_detected") is True
    )
    gmail_compose_send_supported = (
        compose_scope_present or real_send_scope_available or broad_mail_scope_present
    )
    new_config_ready = new_file_paths_ready and gmail_compose_send_supported
    legacy_config_ready = legacy_config_detected and gmail_compose_send_supported
    env_scope_ready = (
        env_loading_audit.get("scope_key_detected_in_os_environ") is True
        or env_loading_audit.get("scope_key_detected_in_dot_env") is True
    ) and gmail_compose_send_supported
    ready = dependencies_ready and (new_config_ready or legacy_config_ready or env_scope_ready)
    required_scope = _safe_text(
        gmail_helper.get("required_scope_expected") or "https://www.googleapis.com/auth/gmail.send",
        max_length=120,
    )
    scope_status = _safe_text(scope_resolver.get("scope_resolver_status"), max_length=120)
    env_audit_status = _safe_text(env_loading_audit.get("env_loading_audit_status"), max_length=120)
    env_audit_message = _safe_text(env_loading_audit.get("dashboard_message"), max_length=300)
    if env_audit_status == "env_file_has_gmail_scope_but_runner_env_missing":
        status_value = "Runner env missing"
        status_message = "Gmail settings may exist in `.env`, but the automation runner cannot see them yet."
    elif env_audit_status == "gmail_scope_not_configured_anywhere_detected":
        status_value = "Permission needed"
        status_message = "Gmail permission is not configured yet."
    elif env_audit_status == "gmail_compose_scope_available_in_runner_env":
        status_value = "Ready"
        status_message = "Gmail draft permission is available for Review & Send."
    elif env_audit_status == "gmail_send_scope_available_in_runner_env":
        status_value = "Ready"
        status_message = "Gmail send permission is available. Final approval is still required before sending."
    elif env_audit_status == "env_file_loaded_but_scope_still_missing":
        status_value = "Permission needed"
        status_message = "Gmail settings loaded, but permission scope is missing."
    elif env_audit_status == "gmail_scope_loaded_but_unrecognized":
        status_value = "Permission issue"
        status_message = "Gmail settings loaded, but permission scope is not recognized."
    elif env_audit_message:
        status_value = _admin_status_label(env_audit_status)
        status_message = env_audit_message
    elif scope_status == "scope_missing":
        status_value = "Permission needed"
        status_message = "Gmail permission is not configured yet."
    elif compose_scope_present and not real_send_scope_available:
        status_value = "Ready"
        status_message = "Gmail draft permission is available for Review & Send."
    elif real_send_scope_available:
        status_value = "Ready"
        status_message = "Gmail send permission is available. Final approval is still required before sending."
    elif legacy_config_detected:
        status_value = "Legacy config found"
        status_message = "Gmail permission is not configured yet."
    else:
        status_value = "Setup needed"
        status_message = "Gmail permission is not configured yet."
    return {
        "ready": ready,
        "gmail_compose_send_supported": gmail_compose_send_supported,
        "compose_scope_present": compose_scope_present,
        "send_scope_present": send_scope_present,
        "broad_mail_scope_present": broad_mail_scope_present,
        "real_send_scope_available": real_send_scope_available,
        "scope_status": (
            "gmail_compose_only"
            if compose_scope_present and not real_send_scope_available
            else (
                "gmail_send_scope_available"
                if real_send_scope_available
                else scope_status or env_audit_status or "scope_missing"
            )
        ),
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
                "value": _gmail_permission_label(
                    send_scope_present,
                    compose_scope_present,
                    required_scope,
                    broad_mail_scope_present,
                ),
            },
            {
                "label": "Env loading audit",
                "value": _admin_status_label(env_audit_status or "missing"),
            },
            {
                "label": "Runner scope key found",
                "value": _plain_yes_no(env_loading_audit.get("scope_key_detected_in_os_environ") is True),
            },
            {
                "label": ".env scope key found",
                "value": _plain_yes_no(env_loading_audit.get("scope_key_detected_in_dot_env") is True),
            },
            {
                "label": "Scope resolver",
                "value": _admin_status_label(scope_resolver.get("scope_resolver_status") or "missing"),
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


def _gmail_permission_label(send_scope_present, compose_scope_present, required_scope, broad_mail_scope_present=False):
    if send_scope_present:
        return "gmail.send"
    if broad_mail_scope_present:
        return "mail.google.com"
    if compose_scope_present:
        return "gmail.compose only"
    return "gmail.send" if required_scope.endswith("/gmail.send") else required_scope


def _gmail_scope_plain_message(status):
    if status == "scope_missing":
        return "Gmail permission is not configured yet."
    if status == "gmail_compose_only":
        return "Gmail draft permission is available. Staff can review drafts before sending."
    if status in {"gmail_send_scope_available", "broad_mail_scope_available"}:
        return "Gmail send permission is available. Final approval is still required before sending."
    return "Gmail permission is not configured yet."


def _setup_checklist(
    ready_count,
    trustpilot_send_readiness,
    trustpilot_auto_refresh,
    trustpilot_gmail_scope_compatibility_resolver,
    trustpilot_gmail_draft_only_preflight,
    trustpilot_gmail_one_draft_create_locked_runner,
):
    scope_checked = any(
        source.get("report_loaded") is True
        for source in (
            trustpilot_gmail_scope_compatibility_resolver,
            trustpilot_gmail_draft_only_preflight,
            trustpilot_gmail_one_draft_create_locked_runner,
        )
    )
    candidate_checked = any(
        source.get("report_loaded") is True
        for source in (
            trustpilot_send_readiness,
            trustpilot_auto_refresh,
            trustpilot_gmail_draft_only_preflight,
            trustpilot_gmail_one_draft_create_locked_runner,
        )
    )
    scope_status = _safe_text(
        trustpilot_gmail_one_draft_create_locked_runner.get("scope_status")
        or trustpilot_gmail_draft_only_preflight.get("scope_status")
        or trustpilot_gmail_scope_compatibility_resolver.get("scope_resolver_status"),
        max_length=120,
    )
    draft_scope_available = (
        trustpilot_gmail_one_draft_create_locked_runner.get("draft_scope_available") is True
        or trustpilot_gmail_draft_only_preflight.get("draft_scope_available") is True
        or trustpilot_gmail_scope_compatibility_resolver.get("compose_scope_available") is True
        or trustpilot_gmail_scope_compatibility_resolver.get("real_send_scope_available") is True
    )
    eligible_candidate_count = _setup_eligible_candidate_count(
        ready_count,
        trustpilot_send_readiness,
        trustpilot_auto_refresh,
        trustpilot_gmail_draft_only_preflight,
        trustpilot_gmail_one_draft_create_locked_runner,
    )
    exactly_one_candidate = (
        trustpilot_gmail_one_draft_create_locked_runner.get("exactly_one_candidate") is True
        or trustpilot_gmail_draft_only_preflight.get("exactly_one_candidate") is True
        or eligible_candidate_count == 1
    )
    selected_candidate_label = _safe_text(
        trustpilot_gmail_one_draft_create_locked_runner.get("selected_candidate_label")
        or trustpilot_gmail_draft_only_preflight.get("selected_candidate_label")
        or trustpilot_auto_refresh.get("selected_candidate_order_name")
        or trustpilot_send_readiness.get("selected_candidate_order_name")
        or "None",
        max_length=80,
    )
    gmail_status = _setup_gmail_status(scope_checked, draft_scope_available, scope_status)
    eligible_status = _setup_eligible_status(candidate_checked, eligible_candidate_count)
    safety_status = _setup_safety_status(candidate_checked, exactly_one_candidate, eligible_candidate_count)
    final_approval_status = "Required"
    current_answer = _setup_current_answer(
        scope_checked=scope_checked,
        candidate_checked=candidate_checked,
        gmail_ready=gmail_status == "Ready",
        eligible_candidate_count=eligible_candidate_count,
        exactly_one_candidate=exactly_one_candidate,
    )
    return {
        "current_answer": current_answer,
        "current_answer_class": "rrw-answer-ready" if current_answer.startswith("Ready") else "rrw-answer-blocked",
        "eligible_candidate_count": eligible_candidate_count,
        "eligible_candidate_count_label": _simple_order_count_text(eligible_candidate_count),
        "selected_candidate_label": selected_candidate_label,
        "next_plain_action": _setup_next_plain_action(
            gmail_status,
            eligible_status,
            safety_status,
        ),
        "items": [
            {
                "letter": "A",
                "label": "Gmail permission",
                "status": gmail_status,
                "status_class": _checklist_status_class(gmail_status),
                "text": (
                    "Gmail permission is not configured yet."
                    if gmail_status != "Not checked yet"
                    else "Gmail permission has not been checked yet."
                ),
                "action": (
                    "Add Gmail scope to the environment. Use `gmail.compose` for draft-only mode, "
                    "or `gmail.send` for direct sending later."
                ),
            },
            {
                "letter": "B",
                "label": "Eligible order",
                "status": eligible_status,
                "status_class": _checklist_status_class(eligible_status),
                "text": _setup_eligible_text(eligible_status, eligible_candidate_count),
                "action": f"Wait for an order to be delivered, then add Shopify tag `{CANONICAL_REVIEW_REQUEST_TAG}`.",
            },
            {
                "letter": "C",
                "label": "Safety checks",
                "status": safety_status,
                "status_class": _checklist_status_class(safety_status),
                "text": "The system needs exactly one safe order.",
                "action": (
                    "Orders with refunds, tickets, return risk, duplicate customers, "
                    "or related-order issues will stay blocked."
                ),
            },
            {
                "letter": "D",
                "label": "Final approval",
                "status": final_approval_status,
                "status_class": _checklist_status_class(final_approval_status),
                "text": "Draft creation will still need final approval.",
                "action": "Future draft creation requires a locked approval flag before any Gmail draft is created.",
            },
        ],
    }


def _setup_eligible_candidate_count(
    ready_count,
    trustpilot_send_readiness,
    trustpilot_auto_refresh,
    trustpilot_gmail_draft_only_preflight,
    trustpilot_gmail_one_draft_create_locked_runner,
):
    for source in (
        trustpilot_gmail_one_draft_create_locked_runner,
        trustpilot_gmail_draft_only_preflight,
        trustpilot_auto_refresh,
        trustpilot_send_readiness,
    ):
        if source.get("report_loaded") is True:
            return _int_or_zero(source.get("eligible_candidate_count"))
    return _int_or_zero(ready_count)


def _setup_gmail_status(scope_checked, draft_scope_available, scope_status):
    if not scope_checked:
        return "Not checked yet"
    if draft_scope_available:
        return "Ready"
    if scope_status in {"scope_missing", "missing"}:
        return "Missing"
    return "Missing"


def _setup_eligible_status(candidate_checked, eligible_candidate_count):
    if not candidate_checked:
        return "Not checked yet"
    if eligible_candidate_count == 0:
        return "Missing"
    if eligible_candidate_count == 1:
        return "Ready"
    return "Needs review"


def _setup_safety_status(candidate_checked, exactly_one_candidate, eligible_candidate_count):
    if not candidate_checked:
        return "Not checked yet"
    if exactly_one_candidate and eligible_candidate_count == 1:
        return "Ready"
    return "Waiting"


def _setup_eligible_text(status, eligible_candidate_count):
    if status == "Not checked yet":
        return "Order readiness has not been checked yet."
    if eligible_candidate_count == 0:
        return "No order is ready for review request yet."
    if eligible_candidate_count == 1:
        return "One order is ready for review request."
    return "More than one order needs review before a draft can be prepared."


def _setup_current_answer(
    scope_checked,
    candidate_checked,
    gmail_ready,
    eligible_candidate_count,
    exactly_one_candidate,
):
    if not scope_checked or not candidate_checked:
        return "Not checked yet - refresh the setup checks before preparing a Trustpilot email."
    if not gmail_ready and eligible_candidate_count == 0:
        return "No — Gmail permission is missing and there is no eligible order."
    if gmail_ready and eligible_candidate_count == 0:
        return "No — no eligible order."
    if not gmail_ready:
        return "No — Gmail permission missing."
    if not exactly_one_candidate or eligible_candidate_count != 1:
        return "No — more than one order needs review."
    return "Ready for final review before draft creation."


def _setup_next_plain_action(gmail_status, eligible_status, safety_status):
    if gmail_status in {"Missing", "Not checked yet"}:
        return "Finish Gmail permission setup."
    if eligible_status in {"Missing", "Not checked yet"}:
        return "Wait for one delivered order with the review request tag."
    if eligible_status == "Needs review" or safety_status != "Ready":
        return "Choose exactly one safe order before draft preparation."
    return "Complete final review before any draft is prepared."


def _checklist_status_class(status):
    if status == "Ready":
        return "rrw-badge-ok"
    if status in {"Missing", "Required", "Waiting", "Needs review"}:
        return "rrw-badge-warn"
    return "rrw-badge-muted"


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
            "label": "Staff adds review-request tag",
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
            "label": "Review request tag",
            "value": len(review_request_queue),
            "note": f"Accepts canonical {CANONICAL_REVIEW_REQUEST_TAG} and legacy typo {TYPO_REVIEW_REQUEST_TAG}.",
        },
        {
            "label": "Missing delivered",
            "value": blocked_missing_delivered,
            "note": "Trustpilot candidates now require Delivered / 妥投 before packaging.",
        },
        {
            "label": "Missing review tag",
            "value": blocked_missing_review_tag,
            "note": "Trustpilot candidates accept the canonical review-request tag and the legacy typo alias.",
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


def has_review_request_tag(tags):
    return bool(_matched_review_request_tags(tags))


def has_delivered_tag(tags):
    return bool(_matched_delivered_tags(tags))


def has_trustpilot_sent_tag(tags):
    return bool(_matched_trustpilot_tags({}, tags))


def _matched_review_request_tags(tags):
    return _matched_tag_alias_values(tags, REVIEW_REQUEST_TAG_ALIASES)


def _matched_delivered_tags(tags):
    return _matched_tag_alias_values(tags, DELIVERED_TAG_ALIASES)


def _matched_tag_alias_values(tags, aliases):
    normalized_aliases = {_normalize_trustpilot_tag(tag) for tag in aliases}
    return _dedupe_text(
        tag
        for tag in _as_text_list(tags)
        if _normalize_trustpilot_tag(tag) in normalized_aliases
    )


def _matched_trustpilot_tags(item, tags):
    matches = _matched_tag_alias_values(tags, TRUSTPILOT_TAG_ALIASES)
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
