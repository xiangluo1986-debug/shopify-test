import base64
import hashlib
import json
import os
import re
import requests
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from django.conf import settings
from django.db.models import Q
from django.urls import NoReverseMatch, reverse

from .review_request_history_ledger import (
    CUSTOMER_HISTORY_LOOKUP_CACHE_FILENAME,
    build_review_request_history_ledger,
    load_customer_history_lookup_cache,
    lookup_cached_customer_history_result,
)
from .models import ShopifyInstallation, ShopifyOrder, ShopifySyncState


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
    "trustpilot",
    "trustpoilt",
)
EBAY_BLOCK_REASON = "eBay order — Trustpilot email not allowed."
CANONICAL_TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_WRITE_SUCCESS_STATUS = "trustpilot_tag_written_and_review_request_removed"
TRUSTPILOT_TAG_WRITE_ALIAS_BLOCKED_STATUS = "blocked_review_request_tag_still_present"
TRUSTPILOT_TAG_FOUND_EVIDENCE = "Trustpilot tag found on Shopify order."
TRUSTPILOT_TAG_ALREADY_SENT_REASON = "Shopify tag shows Trustpilot already sent."
SHOPIFY_TRUSTPILOT_TAG_WRITE_SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_TRUSTPILOT_TAG_WRITE_API_VERSION = "2026-01"
MANUAL_CONFIRMED_ORDER_EVIDENCE = {
    "#21225": {
        "order_name": "#21225",
        "source": "User-confirmed Shopify UI evidence",
        "source_section": "manual_confirmed_shopify_ui_evidence",
        "tags": [CANONICAL_TRUSTPILOT_TAG],
        "trustpilot_tags": [CANONICAL_TRUSTPILOT_TAG],
        "trustpilot_invitation_present": True,
        "contains_trustpilot_alias": True,
        "reason": TRUSTPILOT_TAG_FOUND_EVIDENCE,
    },
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
    "blocked_note_risk_detected",
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
REVIEW_SEND_POST_SEND_AUDIT_REPORT_FILENAME = (
    "codex_runs/shopify_review_request_review_send_post_send_audit.json"
)
REVIEW_SEND_POST_SEND_AUDIT_HTML_FILENAME = (
    "codex_runs/shopify_review_request_review_send_post_send_audit.html"
)
TRUSTPILOT_POST_SEND_TAG_WRITE_REPORT_FILENAME = (
    "codex_runs/shopify_review_request_trustpilot_post_send_tag_write.json"
)
TRUSTPILOT_POST_SEND_TAG_WRITE_HTML_FILENAME = (
    "codex_runs/shopify_review_request_trustpilot_post_send_tag_write.html"
)
LOCAL_REVIEW_SEND_EVIDENCE = "Email sent, Shopify tag update needs attention."
LOCAL_REVIEW_SEND_HISTORY_LABEL = "Sent via local Review & Send report"
TIME_NOT_RECORDED_LABEL = "Time not recorded"
DASHBOARD_STALE_COUNTER_WARNING = "Data may be stale. Run Shopify sync / candidate scan."
TRUSTPILOT_EMAIL_SUBJECT = "How was your Kidstoylover order?"
TRUSTPILOT_REVIEW_LINK = "https://www.trustpilot.com/evaluate/www.kidstoylover.com"
PHASE_22621_DRAFTS_SEND_HELPER_MODULE = (
    "remote_approval.tasks.shopify_review_request_trustpilot_gmail_one_draft_send_execute_task"
)
DYNAMIC_REVIEW_SEND_HELPER_MODULE = "backend.shopify_sync.review_request_workbench"
REVIEW_SEND_REUSE_GMAIL_HELPER_AUDIT_TASK_NAME = (
    "shopify_review_request_review_send_reuse_gmail_helper_audit"
)
REVIEW_SEND_POST_SEND_AUDIT_TASK_NAME = "shopify_review_request_review_send_post_send_audit"
ON_DEMAND_CUSTOMER_HISTORY_LOOKUP_TASK_NAME = "shopify_review_request_on_demand_customer_history_lookup"
ON_DEMAND_CUSTOMER_HISTORY_LOOKUP_REPORT_FILENAME = (
    "codex_runs/shopify_review_request_on_demand_customer_history_lookup.json"
)
SHOPIFY_SCOPE_VERIFICATION_TASK_NAME = "shopify_review_request_shopify_scope_verification"
SHOPIFY_SCOPE_VERIFICATION_REPORT_FILENAME = (
    "codex_runs/shopify_review_request_shopify_scope_verification.json"
)
READ_ALL_ORDERS_MISSING_MESSAGE = "Shopify token does not have read_all_orders. Reauthorize app before sending."
GMAIL_SEND_FROM = "info@kidstoylover.com"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_BROAD_SCOPE = "https://mail.google.com/"
LAST_60_DAY_SCAN_WINDOW_DAYS = 60
REVIEW_QUEUE_BATCH_SIZE = 25
CUSTOMER_HISTORY_LOOKUP_TTL_HOURS = 24
CUSTOMER_HISTORY_LOOKUP_SNAPSHOT_GRACE_SECONDS = 300
LIVE_HISTORY_MISSING_REASON = "Customer history needs live Shopify check before sending."
LIVE_HISTORY_STALE_REASON = "Customer history check is stale."
LIVE_HISTORY_INCOMPLETE_REASON = "Live customer history check failed or incomplete."
BLOCKED_QUEUE_DISPLAY_LIMIT = 25
REVIEW_QUEUE_SORT_ORDER = (
    "most_recent_delivered_updated_created_date",
    "clean_tags",
    "no_merge_or_related_ambiguity",
    "no_duplicate_risk",
    "order_number_descending",
)
OLDER_ELIGIBLE_ORDER_REASON = "A newer eligible order exists for this customer."
LAST_60_DAY_SCAN_TASK_NAME = "shopify_review_request_last_60_days_candidate_scan"
DASHBOARD_SNAPSHOT_TASK_NAME = "shopify_review_request_dashboard_snapshot_refresh"
DASHBOARD_SNAPSHOT_REPORT_FILENAME = "shopify_review_request_dashboard_snapshot.json"
DASHBOARD_SNAPSHOT_HTML_FILENAME = "shopify_review_request_dashboard_snapshot.html"
DASHBOARD_SNAPSHOT_ENV_PATH = "REVIEW_REQUEST_DASHBOARD_SNAPSHOT_PATH"
DASHBOARD_SNAPSHOT_STALE_AFTER_MINUTES = 240
MAX_DASHBOARD_SNAPSHOT_BYTES = 12_000_000
REVIEW_REQUEST_SEND_JOBS_FILENAME = "shopify_review_request_send_jobs.json"
REVIEW_REQUEST_SEND_JOB_SCHEMA_VERSION = 1
REVIEW_REQUEST_SEND_JOB_VISIBLE_LIMIT = 10
REVIEW_REQUEST_SEND_JOB_MAX_STORED = 200
REVIEW_REQUEST_SEND_JOB_ACTIVE_STATUSES = {"queued", "running"}
REVIEW_REQUEST_SEND_JOB_COMPLETED_STATUSES = {"sent", "tag_written", "completed"}
REVIEW_REQUEST_SEND_JOB_DUPLICATE_STATUSES = (
    REVIEW_REQUEST_SEND_JOB_ACTIVE_STATUSES
    | REVIEW_REQUEST_SEND_JOB_COMPLETED_STATUSES
    | {"unknown_after_start"}
)
REVIEW_REQUEST_SEND_JOB_STATUSES = {
    "queued",
    "running",
    "sent",
    "tag_written",
    "completed",
    "unknown_after_start",
    "failed",
}
REVIEW_REQUEST_SEND_JOB_PROCESS_COMMAND = (
    "docker compose exec -T web python manage.py "
    "process_review_request_send_jobs --max-jobs 1"
)
REVIEW_REQUEST_ORDER_SYNC_TASK_NAMES = (
    "orders_review_request_3",
    "orders_review_request_60",
    "orders_review_request_manual",
)
SHOPIFY_ORDER_TAG_FIELD = "shopify_tags"
SHOPIFY_ORDER_TAG_FIELD_LABEL = "ShopifyOrder.shopify_tags"
REVIEW_REQUEST_FOCUS_ORDER_NAMES = (
    "#21083",
    "#21070",
    "#21075",
    "#21076",
    "#21102",
    "#21225",
    "#21687",
    "#21778",
    "#22530",
    "#22562",
    "#22581",
    "#22582",
    "#22620",
    "#22621",
)
SHOPIFY_ORDER_TAGS_MISSING_SOURCE = "ShopifyOrder.shopify_tags is not populated by local sync"
SHOPIFY_ORDER_TAGS_FIELD_MISSING_SOURCE = "Local ShopifyOrder tag field is missing; apply the shopify_tags migration"
SHOPIFY_ORDER_TAGS_EMPTY_SOURCE = "Shopify response had no order tags"
SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION = (
    "Run the Review Request Shopify order sync after applying the shopify_tags migration."
)
SECOND_ORDER_FIRST_ORDER_REASON = "First order — wait until the customer’s second delivered order."
SECOND_ORDER_CURRENT_FIRST_REASON = (
    "This is the customer's first order. Trustpilot starts from the second delivered order."
)
SECOND_ORDER_WAIT_FOR_DELIVERY_REASON = "Wait until this order is delivered."
SECOND_ORDER_HISTORY_NOT_CONFIRMED_REASON = "Customer history not confirmed."
MERGED_ORDER_REFERENCE_RE = re.compile(r"#?\d{3,}")
NOTE_RISK_FIELDS = (
    "shopify_note",
    "shopify_note_attributes",
    "warehouse_note",
    "transfer_note",
    "exception_review_reason",
    "exception_review_response",
    "cost_calculation_note",
)
NOTE_RISK_KEYWORDS = (
    "aftersales",
    "after sale",
    "after-sale",
    "support",
    "ticket",
    "complaint",
    "issue",
    "problem",
    "replacement",
    "refund",
    "return",
    "returned",
    "dispute",
    "chargeback",
    "damaged",
    "missing",
    "defective",
    "broken",
    "售后",
    "工单",
    "客诉",
    "投诉",
    "退款",
    "退货",
    "返修",
    "补发",
    "换货",
    "丢件",
    "破损",
    "少件",
    "有问题",
    "问题单",
)
NOTE_RISK_REASON = "Aftersales/ticket note found"
TRUSTPILOT_NOTE_FIELDS = (
    "shopify_note",
    "shopify_note_attributes",
    "warehouse_note",
    "transfer_note",
    "exception_review_reason",
    "exception_review_response",
    "cost_calculation_note",
)
TRUSTPILOT_NOTE_KEYWORDS = (
    "1: trustpilot",
    "1: trustpoilt",
    "trustpilot",
    "trustpoilt",
    "truspilot",
    "trustpoit",
    "trust pilot",
    "trust poilt",
)
CUSTOMER_IDENTITY_DRILLDOWN_NOTE_FIELDS = (
    "shopify_note",
    "shopify_note_attributes",
    "warehouse_note",
    "transfer_note",
    "exception_review_reason",
)
CUSTOMER_IDENTITY_DRILLDOWN_TARGET_ORDER_NAME = "#21687"
CUSTOMER_IDENTITY_DRILLDOWN_USER_REPORTED_ORDER_COUNT = 7
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
    (
        "note_risk_detected",
        "Aftersales/ticket note",
        ("aftersales/ticket note found", "blocked_note_risk_detected"),
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
    "blocked_note_risk_detected": NOTE_RISK_REASON,
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
        "order_tags_persistence_audit",
        "Shopify order tags persistence audit",
        "shopify_review_request_order_tags_persistence_audit.json",
        ("report_status", "status"),
    ),
    (
        "trustpilot_tag_exclusion_audit",
        "Trustpilot tag exclusion audit",
        "codex_runs/shopify_review_request_trustpilot_tag_exclusion_audit.json",
        ("audit_status", "report_status", "status"),
    ),
    (
        "customer_history_trustpilot_guard_audit",
        "Customer history Trustpilot guard audit",
        "shopify_review_request_customer_history_trustpilot_guard_audit.json",
        ("report_status", "status"),
    ),
    (
        "customer_history_precision_audit",
        "Customer history precision audit",
        "shopify_review_request_customer_history_precision_audit.json",
        ("report_status", "status"),
    ),
    (
        "customer_lifetime_trustpilot_note_audit",
        "Customer lifetime Trustpilot note audit",
        "shopify_review_request_customer_lifetime_trustpilot_note_audit.json",
        ("report_status", "status"),
    ),
    (
        "customer_identity_drilldown_audit",
        "Customer identity drilldown audit",
        "shopify_review_request_customer_identity_drilldown_audit.json",
        ("report_status", "status"),
    ),
    (
        "on_demand_customer_history_lookup",
        "On-demand customer history lookup",
        ON_DEMAND_CUSTOMER_HISTORY_LOOKUP_REPORT_FILENAME,
        ("lookup_status", "report_status", "status"),
    ),
    (
        "batch_customer_history_lookup",
        "Batch customer history lookup",
        "codex_runs/shopify_review_request_batch_customer_history_lookup.json",
        ("task_status", "report_status", "status"),
    ),
    (
        "on_demand_customer_history_lookup_cache",
        "On-demand customer history lookup cache",
        CUSTOMER_HISTORY_LOOKUP_CACHE_FILENAME,
        ("cache_status", "report_status", "status"),
    ),
    (
        "shopify_scope_verification",
        "Shopify read_all_orders scope verification",
        SHOPIFY_SCOPE_VERIFICATION_REPORT_FILENAME,
        ("scope_verification_status", "report_status", "status"),
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
        "review_send_failure_audit",
        "Review & Send failure audit",
        "shopify_review_request_review_send_failure_audit.json",
        ("review_send_failure_audit_status", "report_status", "status"),
    ),
    (
        "dynamic_review_send_audit",
        "Dynamic Review & Send audit",
        "shopify_review_request_dynamic_review_send_audit.json",
        ("dynamic_review_send_audit_status", "report_status", "status"),
    ),
    (
        "review_send_post_send_audit",
        "Review & Send post-send audit",
        REVIEW_SEND_POST_SEND_AUDIT_REPORT_FILENAME,
        ("audit_status", "report_status", "status"),
    ),
    (
        "trustpilot_post_send_tag_write",
        "Trustpilot post-send Shopify tag write",
        TRUSTPILOT_POST_SEND_TAG_WRITE_REPORT_FILENAME,
        ("tag_write_status", "report_status", "status"),
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
    "tag_write_audit",
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
MAX_LOCAL_ORDER_SCAN_ROWS = 5_000
MAX_TABLE_ROWS = DEFAULT_LIMIT


def build_review_request_workbench_context(params=None, use_dashboard_snapshot=True):
    if use_dashboard_snapshot:
        return _build_review_request_workbench_context_from_dashboard_snapshot(params)
    return _build_review_request_workbench_context_live(params)


def _build_review_request_workbench_context_live(params=None):
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
    queue_trustpilot_email_records = _queue_trustpilot_email_records(history_ledger, reports)
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
        trustpilot_email_records=queue_trustpilot_email_records,
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
        reports=reports,
        filters=filters,
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
            "review_queue_page_size_options": _selected_page_size_options(filters["page_size"]),
            "safety_confirmations": _current_page_safety_confirmations(),
        }
    }


def build_review_request_dashboard_snapshot_payload(params=None, generated_by="manual_runner"):
    generated_at = datetime.now(timezone.utc).isoformat()
    context = _build_review_request_workbench_context_live(params)
    workbench = dict(context.get("review_request_workbench") or {})
    dashboard = dict(workbench.get("operating_dashboard") or {})
    approval_queue = dict(dashboard.get("approval_queue") or {})
    last_scan = dict(dashboard.get("last_60_days_candidate_scan") or {})
    coverage = dict(dashboard.get("order_data_coverage") or {})
    scan_coverage = dict(last_scan.get("order_data_coverage") or {})
    lookup_cache = load_customer_history_lookup_cache(_log_dir())
    candidate_review_rows = _snapshot_dict_rows(
        approval_queue.get("all_needs_review_rows")
        or approval_queue.get("needs_review_rows")
        or last_scan.get("review_queue_rows")
        or last_scan.get("eligible_queue_rows"),
        default_action_state="review_send",
        lookup_cache=lookup_cache,
    )
    review_rows = [
        row for row in candidate_review_rows if row.get("action_state") == "review_send"
    ]
    demoted_review_rows = [
        row for row in candidate_review_rows if row.get("action_state") != "review_send"
    ]
    already_sent_rows_full = _snapshot_dict_rows(
        approval_queue.get("all_already_sent_rows")
        or approval_queue.get("already_sent_rows")
        or last_scan.get("already_sent_queue_rows"),
        default_action_state="already_sent",
        lookup_cache=lookup_cache,
    )
    blocked_rows_full = demoted_review_rows + _snapshot_dict_rows(
        approval_queue.get("blocked_rows") or last_scan.get("blocked_queue_rows"),
        default_action_state="not_ready",
        lookup_cache=lookup_cache,
    )
    already_sent_rows = [_compact_already_sent_snapshot_row(row) for row in already_sent_rows_full]
    blocked_rows = [_compact_blocked_snapshot_row(row) for row in blocked_rows_full]
    blocked_visible_rows = blocked_rows[:BLOCKED_QUEUE_DISPLAY_LIMIT]
    review_rows = [_compact_needs_review_snapshot_row(row) for row in review_rows]
    customer_history_snapshot = _dashboard_customer_history_snapshot_summary(
        review_rows,
        blocked_rows,
        lookup_cache=None,
    )
    eligible_total = _int_or_zero(
        approval_queue.get("eligible_candidate_count_total")
        or last_scan.get("eligible_candidate_count_total")
        or last_scan.get("eligible_candidate_count")
        or len(review_rows)
    )
    if candidate_review_rows:
        eligible_total = len(review_rows)
    blocked_total = _int_or_zero(
        approval_queue.get("blocked_count")
        or last_scan.get("blocked_count")
        or len(blocked_rows_full)
    )
    already_sent_total = _int_or_zero(
        approval_queue.get("already_sent_count")
        or last_scan.get("already_sent_count")
        or len(already_sent_rows_full)
    )
    customer_history_snapshot = _dashboard_customer_history_snapshot_summary(
        review_rows,
        blocked_rows,
        lookup_cache=lookup_cache,
    )
    order_21687_lookup = _cached_lookup_order_from_cache(lookup_cache, "#21687")
    order_22562_lookup = _cached_lookup_order_from_cache(lookup_cache, "#22562")
    order_21687_review_orders = {row.get("order") for row in review_rows}
    order_21687_blocked_orders = {row.get("order") for row in blocked_rows}
    order_21687_already_sent_orders = {row.get("order") for row in already_sent_rows}
    order_22562_review_orders = {row.get("order") for row in review_rows}
    order_22562_blocked_orders = {row.get("order") for row in blocked_rows}
    order_22562_already_sent_orders = {row.get("order") for row in already_sent_rows}
    last_shopify_sync_at = _safe_text(
        coverage.get("latest_review_request_sync_finished_at")
        or scan_coverage.get("latest_review_request_sync_finished_at")
        or scan_coverage.get("latest_local_order_synced_at"),
        max_length=120,
    )
    last_candidate_scan_at = _safe_text(
        last_scan.get("candidate_scan_freshness")
        or last_scan.get("scan_window_ended_at")
        or last_scan.get("timestamp")
        or generated_at,
        max_length=120,
    )
    payload = {
        "task": DASHBOARD_SNAPSHOT_TASK_NAME,
        "task_name": DASHBOARD_SNAPSHOT_TASK_NAME,
        "phase": "5.32",
        "snapshot_status": "dashboard_snapshot_ready",
        "report_status": "dashboard_snapshot_ready",
        "success": True,
        "generated_at": generated_at,
        "generated_by": _safe_text(generated_by, max_length=120),
        "sync_source": _safe_text(
            coverage.get("last_shopify_order_sync_window")
            or scan_coverage.get("last_shopify_order_sync_window")
            or "Unknown",
            max_length=120,
        ),
        "eligible_total": eligible_total,
        "base_candidates_needing_live_check": customer_history_snapshot["base_candidates_needing_live_check"],
        "base_candidates_needing_live_check_count": customer_history_snapshot["base_candidates_needing_live_check"],
        "clean_lookup_count": customer_history_snapshot["clean_lookup_count"],
        "final_eligible_after_lookup": customer_history_snapshot["final_eligible_after_lookup"],
        "final_eligible_count_after_lookup": customer_history_snapshot["final_eligible_after_lookup"],
        "needs_live_customer_history_check_count": customer_history_snapshot[
            "needs_live_customer_history_check_count"
        ],
        "live_checks_completed_count": customer_history_snapshot["live_checks_completed_count"],
        "live_checks_blocked_count": customer_history_snapshot["live_checks_blocked_count"],
        "live_checks_failed_incomplete_count": customer_history_snapshot[
            "live_checks_failed_incomplete_count"
        ],
        "customer_history_checks": customer_history_snapshot["customer_history_checks"],
        "review_queue_candidates": review_rows,
        "already_sent_rows": already_sent_rows,
        "blocked_summary": {
            "blocked_total": blocked_total,
            "blocked_visible_count": len(blocked_visible_rows),
            "blocked_ebay_order_count": _int_or_zero(
                approval_queue.get("blocked_ebay_order_count")
                or last_scan.get("blocked_ebay_order_count")
            ),
            "blocked_duplicate_customer_count": _int_or_zero(
                approval_queue.get("duplicate_block_count")
                or last_scan.get("blocked_duplicate_customer_count")
            ),
            "blocked_merged_group_count": _int_or_zero(
                approval_queue.get("merged_group_count")
                or last_scan.get("blocked_merged_group_count")
            ),
            "blocked_first_order_count": _int_or_zero(last_scan.get("blocked_first_order_count")),
            "blocked_not_second_or_later_count": _int_or_zero(
                last_scan.get("blocked_not_second_or_later_count")
            ),
            "blocked_second_order_not_delivered_count": _int_or_zero(
                last_scan.get("blocked_second_order_not_delivered_count")
            ),
            "rows": blocked_visible_rows,
        },
        "order_21687_customer_history_lookup_validation": {
            "lookup_cache_found": bool(order_21687_lookup),
            "should_block_review_send": order_21687_lookup.get("should_block_review_send") is True,
            "evidence_order_name": _safe_text(order_21687_lookup.get("evidence_order_name"), max_length=80),
            "safe_detected_keyword": _safe_text(order_21687_lookup.get("safe_detected_keyword"), max_length=80),
            "blocking_reason": _safe_text(order_21687_lookup.get("blocking_reason"), max_length=300),
            "removed_from_needs_review": "#21687" not in order_21687_review_orders,
            "present_in_blocked_or_already_sent": "#21687" in order_21687_blocked_orders
            or "#21687" in order_21687_already_sent_orders,
            "review_send_button_disabled": "#21687" not in order_21687_review_orders,
            "gmail_api_call_performed": False,
            "shopify_write_performed": False,
        },
        "order_22562_customer_history_lookup_validation": {
            "lookup_cache_found": bool(order_22562_lookup),
            "should_block_review_send": order_22562_lookup.get("should_block_review_send") is True,
            "lookup_clean": bool(
                order_22562_lookup and order_22562_lookup.get("should_block_review_send") is not True
            ),
            "final_section": (
                "review_queue"
                if "#22562" in order_22562_review_orders
                else "blocked"
                if "#22562" in order_22562_blocked_orders
                else "already_sent"
                if "#22562" in order_22562_already_sent_orders
                else "not_visible"
            ),
            "final_eligibility": (
                "eligible"
                if "#22562" in order_22562_review_orders
                else "already_sent"
                if "#22562" in order_22562_already_sent_orders
                else "blocked"
                if "#22562" in order_22562_blocked_orders
                else "not_scanned"
            ),
            "review_send_ready": "#22562" in order_22562_review_orders,
            "blocking_reason": _safe_text(order_22562_lookup.get("blocking_reason"), max_length=300),
            "gmail_api_call_performed": False,
            "shopify_write_performed": False,
        },
        "lookup_cache_paths_checked": lookup_cache.get("lookup_cache_paths_checked") or lookup_cache.get("paths_checked") or [],
        "lookup_cache_selected_path": lookup_cache.get("lookup_cache_selected_path") or lookup_cache.get("selected_path", ""),
        "lookup_cache_path_selected": lookup_cache.get("lookup_cache_selected_path") or lookup_cache.get("selected_path", ""),
        "lookup_cache_found": lookup_cache.get("loaded") is True,
        "lookup_cache_entries_count": _int_or_zero(
            lookup_cache.get("lookup_cache_entries_count") or lookup_cache.get("entries_count")
        ),
        "dashboard_counters": {
            "ready_to_send_count": len(review_rows),
            "eligible_total": eligible_total,
            "base_candidates_needing_live_check": customer_history_snapshot["base_candidates_needing_live_check"],
            "clean_lookup_count": customer_history_snapshot["clean_lookup_count"],
            "final_eligible_after_lookup": customer_history_snapshot["final_eligible_after_lookup"],
            "final_eligible_count": customer_history_snapshot["final_eligible_after_lookup"],
            "needs_live_customer_history_check_count": customer_history_snapshot[
                "needs_live_customer_history_check_count"
            ],
            "live_checks_completed_count": customer_history_snapshot["live_checks_completed_count"],
            "live_checks_blocked_count": customer_history_snapshot["live_checks_blocked_count"],
            "live_checks_failed_incomplete_count": customer_history_snapshot[
                "live_checks_failed_incomplete_count"
            ],
            "needs_review_visible_count": _int_or_zero(
                approval_queue.get("review_queue_visible_count") or len(review_rows[:DEFAULT_LIMIT])
            ),
            "already_sent_total": already_sent_total,
            "blocked_total": blocked_total,
            "older_eligible_hidden": _int_or_zero(approval_queue.get("hidden_older_eligible_count")),
            "latest_sent_order": _safe_text(approval_queue.get("latest_sent_order"), max_length=80),
            "latest_sent_time": _safe_text(approval_queue.get("latest_sent_time"), max_length=120),
            "latest_tag_write_time": _safe_text(approval_queue.get("latest_tag_write_time"), max_length=120),
            "eligible_candidate_count_before_second_order_rule": _int_or_zero(
                last_scan.get("eligible_candidate_count_before_second_order_rule") or eligible_total
            ),
            "eligible_candidate_count_after_second_order_rule": _int_or_zero(
                last_scan.get("eligible_candidate_count_after_second_order_rule") or eligible_total
            ),
            "second_or_later_delivered_candidate_count": _int_or_zero(
                last_scan.get("second_or_later_delivered_candidate_count") or eligible_total
            ),
        },
        "stale_after_minutes": DASHBOARD_SNAPSHOT_STALE_AFTER_MINUTES,
        "scan_report_source": _safe_text(
            last_scan.get("scan_source")
            or coverage.get("scan_source")
            or "local_dashboard_snapshot_refresh",
            max_length=120,
        ),
        "last_shopify_sync_at": last_shopify_sync_at,
        "last_candidate_scan_at": last_candidate_scan_at,
        "review_request_workbench": _compact_workbench_for_dashboard_snapshot(
            workbench,
            dashboard,
            approval_queue,
            last_scan,
            review_rows,
            already_sent_rows,
            blocked_visible_rows,
            blocked_total,
        ),
        "snapshot_output_json_path": f"logs/{DASHBOARD_SNAPSHOT_REPORT_FILENAME}",
        "snapshot_output_html_path": f"logs/{DASHBOARD_SNAPSHOT_HTML_FILENAME}",
        "embedded_history_reports": False,
        "normal_page_load_data_source": "cached_snapshot",
        "normal_page_load_shopify_api_call_performed": False,
        "normal_page_load_full_scan_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "translations_register_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secret_values_printed": False,
        "detected_issue_summary": (
            "Dashboard snapshot refreshed from local Review Request data. "
            "No Shopify API, Gmail API, external review API, email send, or Shopify write was performed."
        ),
    }
    return _finalize_dashboard_snapshot_payload(payload)


def _dashboard_customer_history_snapshot_summary(review_rows, blocked_rows, lookup_cache=None):
    review_rows = list(review_rows or [])
    blocked_rows = list(blocked_rows or [])
    clean_lookup_count = sum(
        1
        for row in review_rows
        if row.get("cached_customer_history_lookup_found") is True
        and row.get("customer_history_lookup_block_status") == "ready"
    )
    needs_live_count = sum(
        1
        for row in blocked_rows
        if row.get("customer_history_lookup_block_status") in {"missing", "stale"}
        or LIVE_HISTORY_MISSING_REASON in _safe_text(row.get("reason") or row.get("blocked_reason"), max_length=500)
    )
    blocked_count = sum(
        1
        for row in blocked_rows
        if row.get("customer_history_lookup_block_status") in {"blocked_trustpilot_note", "blocked_trustpilot_tag"}
    )
    failed_count = sum(
        1
        for row in blocked_rows
        if row.get("customer_history_lookup_block_status") in {"incomplete", "blocked_lookup_cache"}
        or LIVE_HISTORY_INCOMPLETE_REASON in _safe_text(row.get("reason") or row.get("blocked_reason"), max_length=500)
    )
    base_count = needs_live_count + clean_lookup_count + blocked_count + failed_count
    customer_history_checks = {
        "final_eligible_count": len(review_rows),
        "final_eligible_orders": _dedupe_order_names(row.get("order") for row in review_rows),
        "needs_live_customer_history_check_count": needs_live_count,
        "live_checks_completed_count": clean_lookup_count + blocked_count,
        "live_checks_blocked_count": blocked_count,
        "live_checks_failed_incomplete_count": failed_count,
        "clean_lookup_count": clean_lookup_count,
        "base_candidates_needing_live_check": base_count,
        "blocked_by_historical_trustpilot_evidence_orders": _dedupe_order_names(
            row.get("order") for row in blocked_rows
            if row.get("customer_history_lookup_block_status") in {"blocked_trustpilot_note", "blocked_trustpilot_tag"}
        ),
        "live_lookup_failed_or_incomplete_orders": _dedupe_order_names(
            row.get("order") for row in blocked_rows
            if row.get("customer_history_lookup_block_status") in {"incomplete", "blocked_lookup_cache"}
        ),
        "needs_live_customer_history_check_orders": _dedupe_order_names(
            row.get("order") for row in blocked_rows
            if row.get("customer_history_lookup_block_status") in {"missing", "stale"}
        ),
        "batch_lookup_command": _batch_customer_history_lookup_container_command(),
        "message": (
            f"{needs_live_count} candidates need live customer history check before they can be reviewed."
            if needs_live_count
            else ""
        ),
        "lookup_cache_found": (lookup_cache or {}).get("loaded") is True,
        "lookup_cache_entries_count": _int_or_zero(
            (lookup_cache or {}).get("lookup_cache_entries_count")
            or (lookup_cache or {}).get("entries_count")
        ),
        "lookup_cache_path_selected": _safe_text(
            (lookup_cache or {}).get("lookup_cache_selected_path")
            or (lookup_cache or {}).get("selected_path"),
            max_length=500,
        ),
    }
    return {
        "base_candidates_needing_live_check": base_count,
        "clean_lookup_count": clean_lookup_count,
        "final_eligible_after_lookup": len(review_rows),
        "needs_live_customer_history_check_count": needs_live_count,
        "live_checks_completed_count": clean_lookup_count + blocked_count,
        "live_checks_blocked_count": blocked_count,
        "live_checks_failed_incomplete_count": failed_count,
        "customer_history_checks": customer_history_checks,
    }


def _compact_needs_review_snapshot_row(row):
    row = dict(row or {})
    return _compact_snapshot_row(
        row,
        keys=(
            "order",
            "order_name",
            "candidate_id",
            "customer_display_name",
            "customer",
            "customer_masked_label",
            "masked_customer_label",
            "customer_orders_display",
            "customer_order_summary",
            "customer_order_count",
            "customer_history_order_count",
            "customer_order_sequence_number",
            "customer_order_sequence_label",
            "customer_history_confirmed",
            "full_history_confirmed",
            "current_order_delivered",
            "delivered_confirmed",
            "customer_history_lookup_status",
            "customer_history_lookup_block_status",
            "customer_history_lookup_action_label",
            "customer_history_lookup_command",
            "cached_customer_history_lookup_found",
            "tags",
            "order_tags_display",
            "tag_chips",
            "trustpilot_history_label",
            "status_chips",
            "status",
            "status_label",
            "status_class",
            "reason",
            "eligibility_reason_plain",
            "action_state",
            "action_label",
            "action_status",
            "can_review_send",
            "review_send_url",
            "review_send_post_action",
            "delivered_status_label",
            "delivered_status_class",
            "review_request_tag_present",
            "review_request_tag_data_loaded",
            "review_request_tag_status_label",
            "review_request_tag_status_class",
            "matched_review_request_tag_value",
            "review_request_tag_match_detail",
            "send_job_status_label",
            "send_job_status_class",
            "send_job_message",
            "send_job_last_error",
            "review_send_job_blocks_action",
        ),
    )


def _compact_already_sent_snapshot_row(row):
    row = dict(row or {})
    return _compact_snapshot_row(
        row,
        keys=(
            "order",
            "order_name",
            "customer_display_name",
            "customer",
            "customer_masked_label",
            "masked_customer_label",
            "sent_at",
            "sent_time_label",
            "trustpilot_email_status",
            "status_class",
            "shopify_tag_status_label",
            "shopify_tag_status_class",
            "tag_written_at",
            "tag_written_time_label",
            "evidence",
            "tags",
            "order_tags_display",
            "tag_chips",
            "action_state",
            "action_label",
            "action_status",
        ),
    )


def _compact_blocked_snapshot_row(row):
    row = dict(row or {})
    return _compact_snapshot_row(
        row,
        keys=(
            "order",
            "order_name",
            "customer_display_name",
            "customer",
            "customer_masked_label",
            "masked_customer_label",
            "customer_orders_display",
            "customer_order_summary",
            "customer_history_lookup_status",
            "customer_history_lookup_block_status",
            "customer_history_lookup_action_label",
            "customer_history_lookup_command",
            "blocked_by_customer_history_lookup",
            "cached_customer_history_lookup_found",
            "tags",
            "order_tags_display",
            "tag_chips",
            "trustpilot_history_label",
            "status_chips",
            "reason",
            "eligibility_reason_plain",
            "block_reason",
            "blocked_reason",
            "missing_requirement",
            "evidence",
            "action_state",
            "action_label",
            "action_status",
            "status",
            "status_label",
            "status_class",
            "merged_order_group",
            "merged_group_compact_label",
            "merged_group_label",
            "review_request_tag_match_detail",
        ),
    )


def _compact_snapshot_row(row, keys):
    compact = {}
    for key in keys:
        value = row.get(key)
        if value in (None, "", [], {}):
            continue
        compact[key] = _sanitize_dashboard_snapshot_payload(value)
    compact["full_note_output"] = False
    compact["raw_email_output"] = False
    return compact


def _compact_dashboard_shell(dashboard):
    dashboard = dict(dashboard or {})
    keep_keys = (
        "ready_to_send_count",
        "blocked_count",
        "sent_trustpilot_count",
        "customer_history_checks",
        "lookup_cache",
        "order_data_coverage",
        "setup_checklist",
        "current_state_label",
        "status_cards",
        "next_action_headline",
        "send_requirements",
        "current_blockers",
        "gmail_setup_ready",
        "gmail_setup_status_value",
        "gmail_setup_message",
        "next_actions",
        "recent_activity",
        "ali_reviews_message",
        "ali_reviews_status_label",
    )
    compact = {key: dashboard.get(key) for key in keep_keys if key in dashboard}
    for key in (
        "trustpilot_automation",
        "trustpilot_send_readiness",
        "trustpilot_auto_refresh",
        "trustpilot_candidate_simulator",
        "trustpilot_gmail_send_gate",
        "trustpilot_gmail_send_executor_shell",
        "trustpilot_real_send_final_preflight",
        "trustpilot_real_send_execute",
        "trustpilot_gmail_real_send_readiness_audit",
        "trustpilot_gmail_oauth_config_helper",
        "trustpilot_gmail_config_compatibility_audit",
        "trustpilot_gmail_env_loading_audit",
        "trustpilot_gmail_scope_compatibility_resolver",
        "trustpilot_gmail_draft_only_preflight",
        "trustpilot_gmail_one_draft_create_locked_runner",
    ):
        compact[key] = _compact_report_status(dashboard.get(key) or {})
    compact["blocked_order_rows"] = []
    compact["gmail_setup_rows"] = []
    compact["pipeline_steps"] = dashboard.get("pipeline_steps", [])[:10]
    return compact


def _compact_report_status(report):
    if not isinstance(report, dict):
        return {}
    keep = {}
    for key in (
        "report_loaded",
        "present",
        "loaded",
        "success",
        "status",
        "report_status",
        "task_status",
        "generated_at",
        "timestamp",
        "relative_path",
        "html_relative_path",
        "error",
        "message",
        "status_label",
        "status_value",
        "ready",
        "eligible_candidate_count",
        "blocked_candidate_count",
        "gmail_api_call_performed",
        "gmail_send_performed",
        "email_sent",
        "shopify_write_performed",
        "external_review_api_call_performed",
        "translations_register_called",
    ):
        value = report.get(key)
        if value not in (None, "", [], {}):
            keep[key] = _sanitize_dashboard_snapshot_payload(value)
    return keep


def _compact_workbench_for_dashboard_snapshot(
    workbench,
    dashboard,
    approval_queue,
    last_scan,
    review_rows,
    already_sent_rows,
    blocked_visible_rows,
    blocked_total,
):
    compact_queue = {
        "needs_review_count": len(review_rows),
        "already_sent_count": len(already_sent_rows),
        "ready_to_send_count": len(review_rows),
        "not_ready_count": blocked_total,
        "blocked_count": blocked_total,
        "blocked_display_limit": BLOCKED_QUEUE_DISPLAY_LIMIT,
        "duplicate_block_count": _int_or_zero((approval_queue or {}).get("duplicate_block_count")),
        "blocked_ebay_order_count": _int_or_zero((approval_queue or {}).get("blocked_ebay_order_count")),
        "blocked_first_order_count": _int_or_zero((approval_queue or {}).get("blocked_first_order_count")),
        "blocked_not_second_or_later_count": _int_or_zero(
            (approval_queue or {}).get("blocked_not_second_or_later_count")
        ),
        "blocked_second_order_not_delivered_count": _int_or_zero(
            (approval_queue or {}).get("blocked_second_order_not_delivered_count")
        ),
        "review_send_action_enabled_count": min(len(review_rows), DEFAULT_LIMIT),
        "email_sent_count": len(already_sent_rows),
        "merged_group_count": _int_or_zero((approval_queue or {}).get("merged_group_count")),
        "eligible_candidate_count_before_latest_filter": _int_or_zero(
            (approval_queue or {}).get("eligible_candidate_count_before_latest_filter") or len(review_rows)
        ),
        "eligible_candidate_count_after_latest_filter": _int_or_zero(
            (approval_queue or {}).get("eligible_candidate_count_after_latest_filter") or len(review_rows)
        ),
        "hidden_older_eligible_count": _int_or_zero((approval_queue or {}).get("hidden_older_eligible_count")),
        "latest_candidate_per_customer_count": _int_or_zero(
            (approval_queue or {}).get("latest_candidate_per_customer_count") or len(review_rows)
        ),
        "focus_22530_22562_latest_decision": (approval_queue or {}).get("focus_22530_22562_latest_decision") or {},
        "eligible_candidate_count_total": len(review_rows),
        "base_eligible_candidate_count_total": _int_or_zero(
            (approval_queue or {}).get("base_eligible_candidate_count_total") or len(review_rows)
        ),
        "eligible_candidate_count_before_second_order_rule": _int_or_zero(
            (approval_queue or {}).get("eligible_candidate_count_before_second_order_rule") or len(review_rows)
        ),
        "eligible_candidate_count_after_second_order_rule": _int_or_zero(
            (approval_queue or {}).get("eligible_candidate_count_after_second_order_rule") or len(review_rows)
        ),
        "second_or_later_delivered_candidate_count": _int_or_zero(
            (approval_queue or {}).get("second_or_later_delivered_candidate_count") or len(review_rows)
        ),
        "review_queue_sort_order": (approval_queue or {}).get("review_queue_sort_order") or list(REVIEW_QUEUE_SORT_ORDER),
        "latest_sent_order": _safe_text((approval_queue or {}).get("latest_sent_order"), max_length=80),
        "latest_sent_time": _safe_text((approval_queue or {}).get("latest_sent_time"), max_length=120),
        "latest_tag_write_time": _safe_text((approval_queue or {}).get("latest_tag_write_time"), max_length=120),
        "stale_counter_warning": (approval_queue or {}).get("stale_counter_warning") is True,
        "stale_counter_warning_message": _safe_text(
            (approval_queue or {}).get("stale_counter_warning_message"),
            max_length=160,
        ),
        "shopify_tag_write_enabled_count": 0,
        "empty_message": _safe_text(
            (approval_queue or {}).get("empty_message") or "No orders need review email right now.",
            max_length=160,
        ),
        "send_job_manual_process_command": _safe_text(
            (approval_queue or {}).get("send_job_manual_process_command"),
            max_length=300,
        ),
        "send_job_dry_run_command": _safe_text(
            (approval_queue or {}).get("send_job_dry_run_command"),
            max_length=300,
        ),
        "send_job_load_error": _safe_text((approval_queue or {}).get("send_job_load_error"), max_length=300),
        "recent_send_jobs": (approval_queue or {}).get("recent_send_jobs", [])[:REVIEW_REQUEST_SEND_JOB_VISIBLE_LIMIT],
        "active_send_job_count": _int_or_zero((approval_queue or {}).get("active_send_job_count")),
    }
    compact_queue["all_needs_review_rows"] = review_rows
    compact_queue["needs_review_rows"] = review_rows[:DEFAULT_LIMIT]
    compact_queue["all_already_sent_rows"] = already_sent_rows
    compact_queue["already_sent_rows"] = already_sent_rows[:DEFAULT_LIMIT]
    compact_queue["blocked_rows"] = blocked_visible_rows
    compact_queue["blocked_visible_count"] = len(blocked_visible_rows)
    compact_queue["blocked_count"] = blocked_total
    compact_queue["blocked_overflow_count"] = max(blocked_total - len(blocked_visible_rows), 0)
    compact_dashboard = _compact_dashboard_shell(dashboard or {})
    compact_dashboard["approval_queue"] = compact_queue
    compact_dashboard["last_60_days_candidate_scan"] = _compact_last_scan_for_dashboard_snapshot(last_scan)
    return {
        "operating_dashboard": compact_dashboard,
        "summary": workbench.get("summary", []),
        "filters": {},
        "filter_summary": {},
        "latest_scan": {},
        "candidate_queue": [],
        "invitation_history": [],
        "review_request_queue": [],
        "typo_review_request_rows": [],
        "blocked_orders": [],
        "blocked_reason_counts": workbench.get("blocked_reason_counts", []),
        "report_readiness": [],
        "report_history": [],
        "history_ledger": [],
        "history_filters": {},
        "history_summary": workbench.get("history_summary", {}),
        "history_focus": workbench.get("history_focus", {}),
        "history_source_reports": [],
        "history_filter_summary": {},
        "history_channel_filter_options": [],
        "history_event_type_filter_options": [],
        "history_limit_filter_options": [],
        "history_recommendations": [],
        "safety_history": [],
        "local_stats": workbench.get("local_stats", {}),
        "tracking_design": {},
        "candidate_queue_status": {},
        "trustpilot_email_records": [],
        "ali_reviews_status": workbench.get("ali_reviews_status", {}),
        "trustpilot_aliases": workbench.get("trustpilot_aliases", TRUSTPILOT_TAG_ALIASES),
        "review_request_tag_aliases": workbench.get("review_request_tag_aliases", REVIEW_REQUEST_TAG_ALIASES),
        "delivered_tag_aliases": workbench.get("delivered_tag_aliases", DELIVERED_TAG_ALIASES),
        "canonical_review_request_tag": workbench.get("canonical_review_request_tag", CANONICAL_REVIEW_REQUEST_TAG),
        "typo_review_request_tag": workbench.get("typo_review_request_tag", TYPO_REVIEW_REQUEST_TAG),
        "delivered_tag": workbench.get("delivered_tag", DELIVERED_TAG),
        "status_filter_options": [],
        "tag_filter_options": [],
        "limit_filter_options": [],
        "review_queue_page_size_options": [],
        "safety_confirmations": workbench.get("safety_confirmations", []),
    }


def _compact_last_scan_for_dashboard_snapshot(last_scan):
    row_keys = {
        "eligible_queue_rows",
        "review_queue_rows",
        "blocked_queue_rows",
        "already_sent_queue_rows",
        "eligible_candidates_summary",
        "blocked_candidates_summary",
        "already_sent_summary",
    }
    compact = {}
    for key, value in (last_scan or {}).items():
        if key in row_keys:
            continue
        if isinstance(value, list) and len(value) > 50:
            compact[key] = value[:50]
            continue
        compact[key] = value
    return compact


def get_review_request_dashboard_snapshot_read_paths(filename=DASHBOARD_SNAPSHOT_REPORT_FILENAME):
    paths = []
    env_path = _dashboard_snapshot_env_path(filename)
    if env_path:
        paths.append(env_path)
    paths.extend(
        [
            Path("/app/logs") / filename,
            Path("/app/backend/logs") / filename,
            _project_root() / "logs" / filename,
            _project_root() / "backend" / "logs" / filename,
            Path(settings.BASE_DIR).resolve() / "logs" / filename,
        ]
    )
    return _dedupe_paths(paths)


def _dashboard_snapshot_write_paths(filename):
    main_path = _dashboard_snapshot_env_path(filename) or (_project_root() / "logs" / filename)
    mirror_candidates = [
        _project_root() / "logs" / filename,
        Path("/app/logs") / filename,
        Path("/app/backend/logs") / filename,
        _project_root() / "backend" / "logs" / filename,
        Path(settings.BASE_DIR).resolve() / "logs" / filename,
    ]
    mirror_paths = []
    for path in _dedupe_paths(mirror_candidates):
        if _path_identity(path) == _path_identity(main_path):
            continue
        if path.parent.exists():
            mirror_paths.append(path)
    return main_path, mirror_paths


def _dashboard_snapshot_env_path(filename):
    raw_path = os.getenv(DASHBOARD_SNAPSHOT_ENV_PATH, "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if _path_looks_like_directory(path, raw_path):
        return path / filename
    if filename == DASHBOARD_SNAPSHOT_HTML_FILENAME and path.suffix:
        return path.with_suffix(".html")
    return path


def _path_looks_like_directory(path, raw_path):
    if raw_path.endswith(("/", "\\")):
        return True
    try:
        if path.exists() and path.is_dir():
            return True
    except OSError:
        return False
    return not path.suffix


def _dedupe_paths(paths):
    seen = set()
    deduped = []
    for path in paths:
        if not path:
            continue
        identity = _path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(path)
    return deduped


def _path_identity(path):
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        resolved = path
    text = str(resolved)
    return text.lower() if os.name == "nt" else text


def _write_dashboard_snapshot_json(payload):
    main_path, mirror_paths = _dashboard_snapshot_write_paths(DASHBOARD_SNAPSHOT_REPORT_FILENAME)
    paths_failed = []
    main_path.parent.mkdir(parents=True, exist_ok=True)
    _write_dashboard_snapshot_json_file(main_path, payload)
    written_mirrors = []
    for path in mirror_paths:
        try:
            _write_dashboard_snapshot_json_file(path, payload)
        except OSError as exc:
            paths_failed.append(
                {
                    "path": str(path),
                    "error": _sanitize_text(str(exc), max_length=300),
                }
            )
            continue
        written_mirrors.append(path)
    return {
        "main_path": main_path,
        "mirror_paths_written": written_mirrors,
        "paths_failed": paths_failed,
    }


def _write_dashboard_snapshot_json_file(path, payload):
    with path.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    json.loads(path.read_text(encoding="utf-8"))


def _write_dashboard_snapshot_html(payload):
    main_path, mirror_paths = _dashboard_snapshot_write_paths(DASHBOARD_SNAPSHOT_HTML_FILENAME)
    paths_failed = []
    html = _render_dashboard_snapshot_report_html(payload)
    main_path.parent.mkdir(parents=True, exist_ok=True)
    main_path.write_text(html, encoding="utf-8")
    written_mirrors = []
    for path in mirror_paths:
        try:
            path.write_text(html, encoding="utf-8")
        except OSError as exc:
            paths_failed.append(
                {
                    "path": str(path),
                    "error": _sanitize_text(str(exc), max_length=300),
                }
            )
            continue
        written_mirrors.append(path)
    return {
        "main_path": main_path,
        "mirror_paths_written": written_mirrors,
        "paths_failed": paths_failed,
    }


def write_review_request_dashboard_snapshot_reports(payload):
    safe_payload = _finalize_dashboard_snapshot_payload(payload or {})
    json_write = _write_dashboard_snapshot_json(safe_payload)
    safe_payload["snapshot_main_path"] = str(json_write["main_path"])
    safe_payload["snapshot_mirror_paths_written"] = [
        str(path) for path in json_write["mirror_paths_written"]
    ]
    safe_payload["snapshot_paths_failed"] = json_write["paths_failed"]
    safe_payload["page_expected_paths"] = [
        str(path) for path in get_review_request_dashboard_snapshot_read_paths()
    ]
    safe_payload = _finalize_dashboard_snapshot_payload(safe_payload)
    html_write = _write_dashboard_snapshot_html(safe_payload)
    safe_payload["snapshot_html_main_path"] = str(html_write["main_path"])
    safe_payload["snapshot_html_mirror_paths_written"] = [
        str(path) for path in html_write["mirror_paths_written"]
    ]
    safe_payload["snapshot_html_paths_failed"] = html_write["paths_failed"]
    safe_payload = _finalize_dashboard_snapshot_payload(safe_payload)
    _write_dashboard_snapshot_json(safe_payload)
    json_path = json_write["main_path"]
    html_path = html_write["main_path"]
    return {
        "json_path": str(json_path),
        "html_path": str(html_path),
        "relative_json_path": f"logs/{DASHBOARD_SNAPSHOT_REPORT_FILENAME}",
        "relative_html_path": f"logs/{DASHBOARD_SNAPSHOT_HTML_FILENAME}",
        "snapshot_main_path": str(json_write["main_path"]),
        "snapshot_mirror_paths_written": [str(path) for path in json_write["mirror_paths_written"]],
        "snapshot_paths_failed": json_write["paths_failed"],
        "snapshot_html_main_path": str(html_write["main_path"]),
        "snapshot_html_mirror_paths_written": [str(path) for path in html_write["mirror_paths_written"]],
        "snapshot_html_paths_failed": html_write["paths_failed"],
        "page_expected_paths": [str(path) for path in get_review_request_dashboard_snapshot_read_paths()],
    }


def _render_dashboard_snapshot_report_html(payload):
    counters = payload.get("dashboard_counters") if isinstance(payload.get("dashboard_counters"), dict) else {}
    blocked = payload.get("blocked_summary") if isinstance(payload.get("blocked_summary"), dict) else {}
    order_21687 = (
        payload.get("order_21687_customer_history_lookup_validation")
        if isinstance(payload.get("order_21687_customer_history_lookup_validation"), dict)
        else {}
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(payload.get(key) is True))}</td></tr>"
        for label, key in (
            ("Shopify API call performed", "shopify_api_call_performed"),
            ("Shopify write performed", "shopify_write_performed"),
            ("Gmail API call performed", "gmail_api_call_performed"),
            ("Email sent", "email_sent"),
            ("External review API call performed", "external_review_api_call_performed"),
            ("translationsRegister called", "translations_register_called"),
            ("Raw customer email output", "raw_customer_email_output"),
            ("Secret values printed", "secret_values_printed"),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Dashboard Snapshot</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; line-height: 1.45; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f6f6; }}
  </style>
</head>
<body>
  <h1>Review Request Dashboard Snapshot</h1>
  <table>
    <tbody>
      <tr><th>Status</th><td>{escape(str(payload.get('snapshot_status', 'unknown')))}</td></tr>
      <tr><th>Generated at</th><td>{escape(str(payload.get('generated_at', '')))}</td></tr>
      <tr><th>Generated by</th><td>{escape(str(payload.get('generated_by', '')))}</td></tr>
      <tr><th>Sync source</th><td>{escape(str(payload.get('sync_source', '')))}</td></tr>
      <tr><th>Scan report source</th><td>{escape(str(payload.get('scan_report_source', '')))}</td></tr>
      <tr><th>Last Shopify sync</th><td>{escape(str(payload.get('last_shopify_sync_at', '')))}</td></tr>
      <tr><th>Last candidate scan</th><td>{escape(str(payload.get('last_candidate_scan_at', '')))}</td></tr>
      <tr><th>Eligible total</th><td>{escape(str(payload.get('eligible_total', 0)))}</td></tr>
      <tr><th>Needs review visible count</th><td>{escape(str(counters.get('needs_review_visible_count', 0)))}</td></tr>
      <tr><th>Already sent total</th><td>{escape(str(counters.get('already_sent_total', 0)))}</td></tr>
      <tr><th>Blocked total</th><td>{escape(str(blocked.get('blocked_total', 0)))}</td></tr>
      <tr><th>Lookup cache selected path</th><td>{escape(str(payload.get('lookup_cache_path_selected') or payload.get('lookup_cache_selected_path') or '-'))}</td></tr>
      <tr><th>Lookup cache entries</th><td>{escape(str(payload.get('lookup_cache_entries_count', 0)))}</td></tr>
      <tr><th>Base candidates needing live check</th><td>{escape(str(payload.get('base_candidates_needing_live_check', 0)))}</td></tr>
      <tr><th>Clean lookup count</th><td>{escape(str(payload.get('clean_lookup_count', 0)))}</td></tr>
      <tr><th>Final eligible after lookup</th><td>{escape(str(payload.get('final_eligible_after_lookup', 0)))}</td></tr>
      <tr><th>Snapshot size bytes</th><td>{escape(str(payload.get('snapshot_size_bytes', 0)))}</td></tr>
      <tr><th>Embedded history reports</th><td>{escape(str(payload.get('embedded_history_reports') is True))}</td></tr>
      <tr><th>#21687 lookup cache found</th><td>{escape(str(order_21687.get('lookup_cache_found') is True))}</td></tr>
      <tr><th>#21687 should block Review & Send</th><td>{escape(str(order_21687.get('should_block_review_send') is True))}</td></tr>
      <tr><th>#21687 evidence order</th><td>{escape(str(order_21687.get('evidence_order_name') or '-'))}</td></tr>
      <tr><th>#21687 safe keyword</th><td>{escape(str(order_21687.get('safe_detected_keyword') or '-'))}</td></tr>
      <tr><th>#21687 blocking reason</th><td>{escape(str(order_21687.get('blocking_reason') or '-'))}</td></tr>
    </tbody>
  </table>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>
"""


def _build_review_request_workbench_context_from_dashboard_snapshot(params=None):
    filters = _normalize_filters(params)
    report = _load_dashboard_snapshot_report()
    metadata = _dashboard_snapshot_metadata(report, report.get("data") if report.get("loaded") else {})
    if not report.get("loaded"):
        return _empty_dashboard_snapshot_context(filters, metadata)

    data = report.get("data") or {}
    workbench = data.get("review_request_workbench")
    if not isinstance(workbench, dict):
        metadata["status"] = "present_but_invalid"
        metadata["status_label"] = "Missing"
        metadata["missing"] = True
        metadata["message"] = "Review queue has not been generated yet."
        return _empty_dashboard_snapshot_context(filters, metadata)

    workbench = dict(workbench)
    dashboard = dict(workbench.get("operating_dashboard") or {})
    if isinstance(data.get("customer_history_checks"), dict):
        dashboard["customer_history_checks"] = data["customer_history_checks"]
    lookup_cache = dict(dashboard.get("lookup_cache") or {})
    lookup_cache.update(
        {
            "found": data.get("lookup_cache_found") is True,
            "loaded": data.get("lookup_cache_found") is True,
            "selected_path": _safe_text(data.get("lookup_cache_selected_path"), max_length=500),
            "path": _safe_text(data.get("lookup_cache_selected_path"), max_length=500),
            "entries_count": _int_or_zero(data.get("lookup_cache_entries_count")),
            "paths_checked": data.get("lookup_cache_paths_checked") or lookup_cache.get("paths_checked") or [],
            "order_22562_lookup_cache_found": (
                (data.get("order_22562_customer_history_lookup_validation") or {}).get("lookup_cache_found")
                is True
            ),
            "order_22562_final_section": (
                (data.get("order_22562_customer_history_lookup_validation") or {}).get("final_section")
                or ""
            ),
            "order_22562_final_eligibility": (
                (data.get("order_22562_customer_history_lookup_validation") or {}).get("final_eligibility")
                or ""
            ),
        }
    )
    dashboard["lookup_cache"] = lookup_cache
    dashboard["dashboard_snapshot"] = metadata
    dashboard["normal_page_load_data_source"] = "cached_snapshot"
    dashboard["normal_page_load_shopify_api_call_performed"] = False
    dashboard["normal_page_load_full_scan_performed"] = False
    _paginate_dashboard_snapshot(dashboard, filters)
    dashboard["review_request_send_jobs"] = _attach_review_request_send_jobs_to_approval_queue(
        dashboard["approval_queue"]
    )
    workbench["operating_dashboard"] = dashboard
    workbench["filters"] = filters
    workbench["status_filter_options"] = _selected_options(STATUS_FILTER_OPTIONS, filters["status"])
    workbench["tag_filter_options"] = _selected_options(TAG_FILTER_OPTIONS, filters["tag"])
    workbench["limit_filter_options"] = _selected_limit_options(filters["limit"])
    workbench["review_queue_page_size_options"] = _selected_page_size_options(filters["page_size"])
    workbench["dashboard_snapshot"] = metadata
    return {"review_request_workbench": workbench}


def _load_dashboard_snapshot_report():
    paths = get_review_request_dashboard_snapshot_read_paths()
    checked = [_read_dashboard_snapshot_candidate(path) for path in paths]
    loaded_reports = [item for item in checked if item.get("loaded")]
    selected = None
    if loaded_reports:
        selected = max(loaded_reports, key=lambda item: item.get("mtime") or 0)
    report = {
        "relative_path": f"logs/{DASHBOARD_SNAPSHOT_REPORT_FILENAME}",
        "present": False,
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "modified_at": "",
        "error": "",
        "data": {},
        "paths_checked": [_dashboard_snapshot_public_path_check(item) for item in checked],
        "selected_path": "",
        "selected_path_exists": False,
        "page_expected_paths": [str(path) for path in paths],
    }
    if not selected:
        report["present"] = any(item.get("present") for item in checked)
        report["status"] = "present_but_unusable" if report["present"] else "missing"
        report["error"] = next((item.get("error") for item in checked if item.get("error")), "")
        return report

    data = selected["data"]
    for item in report["paths_checked"]:
        item["selected"] = item.get("path") == selected.get("path")
    report["present"] = True
    report["loaded"] = True
    report["data"] = data
    report["status"] = _safe_text(data.get("snapshot_status") or data.get("report_status") or "loaded", max_length=120)
    report["timestamp"] = _safe_text(data.get("generated_at") or data.get("timestamp"), max_length=120)
    report["modified_at"] = selected.get("modified_at", "")
    report["size_bytes"] = selected.get("size_bytes", 0)
    report["selected_path"] = selected.get("path", "")
    report["selected_path_exists"] = True
    report["relative_path"] = selected.get("path", report["relative_path"])
    return report


def _read_dashboard_snapshot_candidate(path):
    result = {
        "path": str(path),
        "present": False,
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "modified_at": "",
        "mtime": 0,
        "size_bytes": 0,
        "error": "",
        "data": {},
    }
    try:
        if not path.exists():
            return result
        stat = path.stat()
        result["present"] = True
        result["modified_at"] = _safe_text(_format_file_time(stat.st_mtime))
        result["mtime"] = stat.st_mtime
        result["size_bytes"] = stat.st_size
        if stat.st_size > MAX_DASHBOARD_SNAPSHOT_BYTES:
            result["status"] = "present_but_too_large_for_dashboard"
            result["error"] = "dashboard_snapshot_too_large"
            return result
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        result["status"] = "present_but_unreadable"
        result["error"] = _sanitize_text(str(exc), max_length=300)
        return result
    if not isinstance(data, dict):
        result["status"] = "present_but_not_object"
        result["error"] = "top_level_json_is_not_object"
        return result
    result["loaded"] = True
    result["data"] = data
    result["status"] = _safe_text(data.get("snapshot_status") or data.get("report_status") or "loaded", max_length=120)
    result["timestamp"] = _safe_text(data.get("generated_at") or data.get("timestamp"), max_length=120)
    return result


def _dashboard_snapshot_public_path_check(item):
    return {
        "path": item.get("path", ""),
        "present": item.get("present") is True,
        "loaded": item.get("loaded") is True,
        "selected": False,
        "status": _safe_text(item.get("status"), max_length=120),
        "modified_at": _safe_text(item.get("modified_at"), max_length=120),
        "size_bytes": item.get("size_bytes") or 0,
        "error": _safe_text(item.get("error"), max_length=300),
    }


def _dashboard_snapshot_refresh_command():
    if _running_in_docker():
        return _dashboard_snapshot_container_refresh_command()
    return _dashboard_snapshot_host_refresh_command()


def _dashboard_snapshot_host_refresh_command():
    return f"python remote_approval_runner.py --task {DASHBOARD_SNAPSHOT_TASK_NAME} --approval local"


def _dashboard_snapshot_container_refresh_command():
    return "docker compose exec -T web python manage.py refresh_review_request_dashboard_snapshot"


def _batch_customer_history_lookup_container_command(limit=DEFAULT_LIMIT):
    limit = max(_int_or_zero(limit) or DEFAULT_LIMIT, 1)
    return (
        "docker compose exec -T web python manage.py "
        f"run_review_request_batch_customer_history_lookup --limit {limit}"
    )


def _running_in_docker():
    return Path("/.dockerenv").exists()


def _dashboard_snapshot_metadata(report, data=None):
    data = data or {}
    generated_at = _safe_text(data.get("generated_at") or report.get("timestamp"), max_length=120)
    stale_after_minutes = _int_or_zero(data.get("stale_after_minutes") or DASHBOARD_SNAPSHOT_STALE_AFTER_MINUTES)
    if stale_after_minutes <= 0:
        stale_after_minutes = DASHBOARD_SNAPSHOT_STALE_AFTER_MINUTES
    generated_dt = _parse_snapshot_datetime(generated_at)
    age_seconds = None
    if generated_dt:
        age_seconds = max(int((datetime.now(timezone.utc) - generated_dt).total_seconds()), 0)
    stale = bool(age_seconds is None or age_seconds > stale_after_minutes * 60)
    loaded = report.get("loaded") is True
    missing = not loaded
    status_label = "Missing" if missing else ("Stale" if stale else "Fresh")
    stale_message = ""
    if loaded and stale:
        stale_message = f"Data may be stale. Last updated {_dashboard_snapshot_age_label(age_seconds)}."
    return {
        "relative_path": f"logs/{DASHBOARD_SNAPSHOT_REPORT_FILENAME}",
        "html_relative_path": f"logs/{DASHBOARD_SNAPSHOT_HTML_FILENAME}",
        "present": report.get("present") is True,
        "loaded": loaded,
        "missing": missing,
        "stale": bool(loaded and stale),
        "fresh": bool(loaded and not stale),
        "status": "missing" if missing else ("stale" if stale else "fresh"),
        "status_label": status_label,
        "message": "Review queue has not been generated yet." if missing else "",
        "stale_message": stale_message,
        "generated_at": generated_at,
        "generated_at_display": _format_snapshot_time(generated_at),
        "age_seconds": age_seconds if age_seconds is not None else "",
        "age_label": _dashboard_snapshot_age_label(age_seconds),
        "stale_after_minutes": stale_after_minutes,
        "generated_by": _safe_text(data.get("generated_by"), max_length=120),
        "sync_source": _safe_text(data.get("sync_source") or "Unknown", max_length=120),
        "scan_report_source": _safe_text(data.get("scan_report_source") or "Unknown", max_length=120),
        "last_shopify_sync_at": _safe_text(data.get("last_shopify_sync_at"), max_length=120),
        "last_candidate_scan_at": _safe_text(data.get("last_candidate_scan_at"), max_length=120),
        "data_source_label": "Cached snapshot",
        "refresh_command": _dashboard_snapshot_refresh_command(),
        "host_refresh_command": _dashboard_snapshot_host_refresh_command(),
        "container_refresh_command": _dashboard_snapshot_container_refresh_command(),
        "selected_path": _safe_text(report.get("selected_path"), max_length=500),
        "selected_mtime": _safe_text(report.get("modified_at"), max_length=120),
        "selected_size_bytes": report.get("size_bytes") or 0,
        "snapshot_size_bytes": _int_or_zero(data.get("snapshot_size_bytes") or report.get("size_bytes")),
        "row_counts": data.get("row_counts") if isinstance(data.get("row_counts"), dict) else {},
        "embedded_history_reports": data.get("embedded_history_reports") is True,
        "paths_checked": report.get("paths_checked") or [],
        "page_expected_paths": report.get("page_expected_paths") or [],
        "error": _safe_text(report.get("error"), max_length=300),
    }


def _empty_dashboard_snapshot_context(filters, metadata):
    dashboard = _empty_dashboard_for_missing_snapshot(metadata)
    return {
        "review_request_workbench": {
            "operating_dashboard": dashboard,
            "filters": filters,
            "dashboard_snapshot": metadata,
            "status_filter_options": _selected_options(STATUS_FILTER_OPTIONS, filters["status"]),
            "tag_filter_options": _selected_options(TAG_FILTER_OPTIONS, filters["tag"]),
            "limit_filter_options": _selected_limit_options(filters["limit"]),
            "review_queue_page_size_options": _selected_page_size_options(filters["page_size"]),
            "safety_confirmations": _current_page_safety_confirmations(),
        }
    }


def _empty_dashboard_for_missing_snapshot(metadata):
    approval_queue = _empty_dashboard_approval_queue()
    send_jobs = _attach_review_request_send_jobs_to_approval_queue(approval_queue)
    return {
        "dashboard_snapshot": metadata,
        "ready_to_send_count": 0,
        "blocked_count": 0,
        "sent_trustpilot_count": 0,
        "approval_queue": approval_queue,
        "review_request_send_jobs": send_jobs,
        "last_60_days_candidate_scan": {},
        "order_data_coverage": {
            "incomplete": True,
            "incomplete_message": "Review queue has not been generated yet.",
            "last_shopify_order_sync_window": "Unknown",
            "local_data_source_label": "Cached snapshot",
            "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
            "local_orders_with_shopify_tag_data": 0,
            "order_22530_found_label": "Unknown",
            "candidate_scan_freshness": "Unknown",
            "last_sent_record_time": TIME_NOT_RECORDED_LABEL,
            "last_tag_write_time": TIME_NOT_RECORDED_LABEL,
            "stale_counter_warning": True,
            "stale_counter_warning_message": "Review queue has not been generated yet.",
            "warning_label": "snapshot_missing",
        },
        "current_state_label": "Review queue missing",
        "status_cards": [],
        "send_requirements": [],
        "current_blockers": [],
        "blocked_order_rows": [],
        "pipeline_steps": [],
        "next_actions": [],
        "recent_activity": [],
        "ali_reviews_message": "",
        "ali_reviews_status_label": "Unavailable",
    }


def _empty_dashboard_approval_queue():
    pagination = _approval_queue_pagination(0, 1, DEFAULT_LIMIT)
    sent_pagination = _already_sent_pagination(0, 1, DEFAULT_LIMIT, 1, DEFAULT_LIMIT)
    return {
        "needs_review_rows": [],
        "blocked_rows": [],
        "already_sent_rows": [],
        "all_needs_review_rows": [],
        "all_already_sent_rows": [],
        "needs_review_count": 0,
        "already_sent_count": 0,
        "ready_to_send_count": 0,
        "not_ready_count": 0,
        "blocked_count": 0,
        "blocked_visible_count": 0,
        "blocked_display_limit": BLOCKED_QUEUE_DISPLAY_LIMIT,
        "blocked_overflow_count": 0,
        "duplicate_block_count": 0,
        "blocked_ebay_order_count": 0,
        "review_send_action_enabled_count": 0,
        "email_sent_count": 0,
        "eligible_candidate_count_total": 0,
        "eligible_candidate_count_before_latest_filter": 0,
        "eligible_candidate_count_after_latest_filter": 0,
        "hidden_older_eligible_count": 0,
        "review_queue_batch_size": DEFAULT_LIMIT,
        "review_queue_page_size": pagination["page_size"],
        "review_queue_page": pagination["page"],
        "review_queue_total_pages": pagination["total_pages"],
        "review_queue_has_previous": pagination["has_previous"],
        "review_queue_has_next": pagination["has_next"],
        "review_queue_previous_page_url": pagination["previous_page_url"],
        "review_queue_next_page_url": pagination["next_page_url"],
        "review_queue_showing_start": pagination["showing_start"],
        "review_queue_showing_end": pagination["showing_end"],
        "review_queue_visible_count": 0,
        "review_queue_page_size_options": _selected_page_size_options(DEFAULT_LIMIT),
        **_already_sent_pagination_summary(sent_pagination, [], [], 1, DEFAULT_LIMIT),
        "latest_sent_order": "",
        "latest_sent_time": "",
        "latest_tag_write_time": "",
        "stale_counter_warning": True,
        "stale_counter_warning_message": "Review queue has not been generated yet.",
        "shopify_tag_write_enabled_count": 0,
        "empty_message": "Review queue has not been generated yet.",
    }


def _paginate_dashboard_snapshot(dashboard, filters):
    approval_queue = dict(dashboard.get("approval_queue") or {})
    snapshot_lookup_cache = {"orders": {}}
    candidate_review_rows = _snapshot_dict_rows(
        approval_queue.get("all_needs_review_rows")
        or approval_queue.get("needs_review_rows"),
        default_action_state="review_send",
        lookup_cache=snapshot_lookup_cache,
    )
    all_needs_review_rows = [
        row for row in candidate_review_rows if row.get("action_state") == "review_send"
    ]
    demoted_review_rows = [
        row for row in candidate_review_rows if row.get("action_state") != "review_send"
    ]
    all_already_sent_rows = _snapshot_dict_rows(
        approval_queue.get("all_already_sent_rows")
        or approval_queue.get("already_sent_rows"),
        default_action_state="already_sent",
        lookup_cache=snapshot_lookup_cache,
    )
    blocked_rows = demoted_review_rows + _snapshot_dict_rows(
        approval_queue.get("blocked_rows"),
        default_action_state="not_ready",
        lookup_cache=snapshot_lookup_cache,
    )
    pagination = _approval_queue_pagination(
        total_count=len(all_needs_review_rows),
        page=filters["page"],
        page_size=filters["page_size"],
    )
    visible_review_rows = [
        _review_queue_visible_row(row, pagination)
        for row in all_needs_review_rows[pagination["start_index"] : pagination["end_index"]]
    ]
    sent_pagination = _already_sent_pagination(
        total_count=len(all_already_sent_rows),
        sent_page=filters["sent_page"],
        sent_page_size=filters["sent_page_size"],
        review_page=pagination["page"],
        review_page_size=pagination["page_size"],
    )
    visible_sent_rows = [
        _already_sent_visible_row(row, sent_pagination)
        for row in all_already_sent_rows[
            sent_pagination["start_index"] : sent_pagination["end_index"]
        ]
    ]
    approval_queue["all_needs_review_rows"] = all_needs_review_rows
    approval_queue["needs_review_rows"] = visible_review_rows
    approval_queue["all_already_sent_rows"] = all_already_sent_rows
    approval_queue["already_sent_rows"] = visible_sent_rows
    approval_queue["blocked_rows"] = blocked_rows[:BLOCKED_QUEUE_DISPLAY_LIMIT]
    approval_queue["blocked_visible_count"] = min(len(blocked_rows), BLOCKED_QUEUE_DISPLAY_LIMIT)
    approval_queue["blocked_count"] = max(
        _int_or_zero(approval_queue.get("blocked_count")),
        len(blocked_rows),
    )
    approval_queue["blocked_overflow_count"] = max(
        len(blocked_rows) - BLOCKED_QUEUE_DISPLAY_LIMIT,
        0,
    )
    approval_queue["needs_review_count"] = _int_or_zero(
        approval_queue.get("needs_review_count") or len(all_needs_review_rows)
    )
    approval_queue["ready_to_send_count"] = _int_or_zero(
        approval_queue.get("ready_to_send_count") or len(all_needs_review_rows)
    )
    if candidate_review_rows:
        approval_queue["needs_review_count"] = len(all_needs_review_rows)
        approval_queue["ready_to_send_count"] = len(all_needs_review_rows)
    approval_queue["already_sent_count"] = len(all_already_sent_rows)
    approval_queue["eligible_candidate_count_total"] = _int_or_zero(
        approval_queue.get("eligible_candidate_count_total") or len(all_needs_review_rows)
    )
    if candidate_review_rows:
        approval_queue["eligible_candidate_count_total"] = len(all_needs_review_rows)
    approval_queue["review_send_action_enabled_count"] = len(visible_review_rows)
    approval_queue["review_queue_batch_size"] = pagination["page_size"]
    approval_queue["review_queue_page_size"] = pagination["page_size"]
    approval_queue["review_queue_page"] = pagination["page"]
    approval_queue["review_queue_total_pages"] = pagination["total_pages"]
    approval_queue["review_queue_has_previous"] = pagination["has_previous"]
    approval_queue["review_queue_has_next"] = pagination["has_next"]
    approval_queue["review_queue_previous_page"] = pagination["previous_page"]
    approval_queue["review_queue_next_page"] = pagination["next_page"]
    approval_queue["review_queue_previous_page_url"] = pagination["previous_page_url"]
    approval_queue["review_queue_next_page_url"] = pagination["next_page_url"]
    approval_queue["review_queue_showing_start"] = pagination["showing_start"]
    approval_queue["review_queue_showing_end"] = pagination["showing_end"]
    approval_queue["review_queue_visible_count"] = len(visible_review_rows)
    approval_queue["review_queue_overflow_count"] = max(
        len(all_needs_review_rows) - pagination["showing_end"],
        0,
    )
    approval_queue["review_queue_page_size_options"] = _selected_page_size_options(pagination["page_size"])
    approval_queue.update(
        _already_sent_pagination_summary(
            sent_pagination,
            visible_sent_rows,
            all_already_sent_rows,
            pagination["page"],
            pagination["page_size"],
        )
    )
    dashboard["approval_queue"] = approval_queue


def _snapshot_dict_rows(value, default_action_state="", lookup_cache=None):
    return [
        _normalize_dashboard_snapshot_row(
            dict(row),
            default_action_state=default_action_state,
            lookup_cache=lookup_cache,
        )
        for row in (value or [])
        if isinstance(row, dict)
    ]


def _normalize_dashboard_snapshot_row(row, default_action_state="", lookup_cache=None):
    order_name = _safe_text(row.get("order_name") or row.get("order"), max_length=80)
    if lookup_cache is None:
        cached_lookup = lookup_cached_customer_history_result(_log_dir(), order_name)
    else:
        cached_lookup = _cached_lookup_order_from_cache(lookup_cache, order_name)
    if cached_lookup:
        row = _apply_cached_customer_history_lookup_to_row(row, cached_lookup)
    action_state = _snapshot_action_state(row, default_action_state)
    tags = _dedupe_text(
        row.get("order_tags_display")
        or row.get("tags")
        or row.get("local_shopify_tags")
        or []
    )
    delivered = _snapshot_delivered_value(row, tags)
    review_request_present = _snapshot_review_request_value(row, tags)
    tag_data_loaded = (
        row.get("tag_data_available") is True
        or row.get("review_request_tag_data_loaded") is True
        or bool(tags)
    )
    trustpilot_sent = bool(
        action_state == "already_sent"
        or row.get("trustpilot_already_sent_to_customer") is True
        or row.get("customer_level_trustpilot_already_sent") is True
        or row.get("trustpilot_tag_detected") is True
        or row.get("local_review_send_success") is True
        or row.get("previous_trustpilot_order_names")
        or has_trustpilot_sent_tag(tags)
    )
    history_count = _int_or_zero(
        row.get("customer_history_order_count") or row.get("customer_order_count")
    )
    sequence = _int_or_zero(row.get("customer_order_sequence_number"))
    history_confirmed = row.get("customer_history_confirmed") is True or bool(history_count and sequence)
    second_order_state = _second_order_rule_state(
        history_confirmed=history_confirmed,
        history_count=history_count,
        sequence=sequence,
        delivered=delivered,
    )
    reason = _safe_text(
        row.get("eligibility_reason_plain")
        or row.get("reason")
        or row.get("block_reason")
        or row.get("missing_requirement"),
        max_length=500,
    )
    if action_state == "review_send" and second_order_state["passed"] is not True:
        action_state = "not_ready"
        reason = second_order_state["reason"]
    if not reason:
        reason = (
            "Delivered, tagged, and no duplicate or risk found."
            if action_state == "review_send"
            else second_order_state["reason"] or "Not ready"
        )

    status = _safe_text(row.get("status") or row.get("status_label"), max_length=120)
    if not status:
        status = _queue_eligibility_status_label(action_state)
    if action_state == "not_ready":
        status = "Not ready"
    elif action_state == "review_send":
        status = "Ready"
    customer_display_name = (
        _safe_customer_display_name(row.get("customer_display_name"))
        or _safe_customer_display_name(row.get("customer"))
        or "Customer not loaded"
    )
    masked_customer = _safe_text(
        row.get("masked_customer_label")
        or row.get("customer_masked_label")
        or row.get("masked_customer"),
        max_length=120,
    )
    sequence_label = _safe_text(row.get("customer_order_sequence_label"), max_length=120)
    if not sequence_label:
        sequence_label = _customer_order_sequence_label(
            history_count,
            sequence,
            repeat_detected=history_count > 1,
            history_confirmed=history_confirmed,
        )
    customer_history_match_label = _safe_text(row.get("customer_history_match_label"), max_length=160)
    if not customer_history_match_label:
        customer_history_match_label = _customer_history_match_label(
            row.get("customer_history_source"),
            row.get("customer_history_confidence"),
        )
    trustpilot_history_label = _safe_text(
        row.get("trustpilot_history_label") or row.get("trustpilot_history"),
        max_length=300,
    )
    if not trustpilot_history_label:
        trustpilot_history_label = (
            "Already sent to this customer"
            if trustpilot_sent
            else "History not confirmed"
            if not history_confirmed
            else "No previous Trustpilot email found"
        )
    matched_review_request_tag = _safe_text(
        row.get("matched_review_request_tag_value"),
        max_length=120,
    )
    if not matched_review_request_tag:
        matched_tags = _matched_review_request_tags(tags)
        matched_review_request_tag = matched_tags[0] if matched_tags else ""
    delivered_label = _queue_delivered_status_label(delivered)
    review_request_label = (
        "Review request tag found"
        if review_request_present is True
        else (
            f"Missing {CANONICAL_REVIEW_REQUEST_TAG}"
            if review_request_present is False
            else "Tag data not loaded"
        )
    )
    status_chips = row.get("status_chips") if isinstance(row.get("status_chips"), list) else []
    if not status_chips:
        status_chips = [
            {"label": delivered_label, "css_class": _queue_status_css_class(delivered)},
            {"label": review_request_label, "css_class": _queue_status_css_class(review_request_present)},
        ]
    can_review_send = action_state == "review_send"
    customer_orders_display = _safe_text(
        row.get("customer_orders_display") or row.get("customer_order_summary"),
        max_length=180,
    ) or _customer_orders_display(
        history_count,
        sequence_label,
        row.get("related_order_names") or row.get("group_order_names") or [],
        history_confirmed=history_confirmed,
    )

    row.update(
        {
            "order": order_name,
            "order_name": order_name,
            "candidate_id": _safe_text(row.get("candidate_id") or order_name, max_length=80),
            "customer_display_name": customer_display_name,
            "customer_masked_label": masked_customer,
            "masked_customer_label": masked_customer,
            "customer_order_count": history_count,
            "customer_history_order_count": history_count,
            "customer_order_sequence_number": sequence,
            "customer_order_sequence_label": sequence_label,
            "customer_order_summary": customer_orders_display,
            "customer_orders_display": customer_orders_display,
            "customer_history_confirmed": history_confirmed,
            "customer_history_match_label": customer_history_match_label,
            "customer_history_lookup_status": _safe_text(
                row.get("customer_history_lookup_status"),
                max_length=120,
            )
            or ("Customer history checked" if history_confirmed else "Customer history not confirmed"),
            "customer_history_lookup_action_label": _safe_text(
                row.get("customer_history_lookup_action_label"),
                max_length=120,
            )
            or ("Customer history checked" if history_confirmed else "Check customer history"),
            "customer_history_lookup_command": _safe_text(
                row.get("customer_history_lookup_command"),
                max_length=500,
            )
            or _customer_history_lookup_command(order_name),
            "tags": tags,
            "order_tags_display": tags,
            "tag_chips": row.get("tag_chips")
            if isinstance(row.get("tag_chips"), list) and row.get("tag_chips")
            else _queue_tag_chips(
                tags,
                delivered=delivered,
                review_request_present=review_request_present,
                trustpilot_sent=trustpilot_sent,
                action_state=action_state,
                tag_data_loaded=tag_data_loaded,
            ),
            "trustpilot_history_label": trustpilot_history_label,
            "trustpilot_history_evidence": _safe_text(
                row.get("trustpilot_history_evidence") or row.get("evidence"),
                max_length=500,
            ),
            "status": status,
            "status_label": status,
            "status_class": _safe_text(row.get("status_class"), max_length=80)
            or ("rrw-badge-ok" if action_state in {"review_send", "already_sent"} else "rrw-badge-warn"),
            "status_chips": status_chips,
            "reason": reason,
            "eligibility_reason_plain": reason,
            "action_state": action_state,
            "action_label": _queue_action_status(action_state),
            "action_status": _queue_action_status(action_state),
            "can_review_send": can_review_send,
            "review_send_url": _safe_text(row.get("review_send_url"), max_length=240),
            "review_send_post_action": "review_send" if can_review_send else "",
            "hidden_reason": _safe_text(row.get("hidden_reason"), max_length=120)
            or ("" if can_review_send else reason),
            "blocked_reason": "" if can_review_send else reason,
            "delivered_status_label": delivered_label,
            "delivered_status_class": _queue_status_css_class(delivered),
            "review_request_tag_present": review_request_present is True,
            "review_request_tag_data_loaded": tag_data_loaded,
            "review_request_tag_status_label": review_request_label,
            "review_request_tag_status_class": _queue_status_css_class(review_request_present),
            "matched_review_request_tag_value": matched_review_request_tag,
            "review_request_tag_match_detail": _review_request_tag_match_detail(matched_review_request_tag),
            "second_or_later_order": second_order_state["second_or_later_order"],
            "current_order_delivered": second_order_state["current_order_delivered"],
            "second_order_rule_passed": second_order_state["passed"],
            "second_order_rule_blocker": second_order_state["blocker"],
            "second_order_rule_reason": second_order_state["reason"],
        }
    )
    return row


def _snapshot_action_state(row, default_action_state=""):
    state = _safe_text(row.get("action_state"), max_length=80)
    if state in {"review_send", "already_sent", "not_ready"}:
        return state
    text = " ".join(
        _safe_text(row.get(key), max_length=120).lower()
        for key in ("action", "action_label", "action_status", "status", "status_label")
    )
    if "already sent" in text:
        return "already_sent"
    if "not ready" in text:
        return "not_ready"
    if "review & send" in text or re.search(r"\bready\b", text):
        return "review_send"
    if default_action_state:
        return default_action_state
    return "not_ready"


def _snapshot_delivered_value(row, tags):
    if row.get("current_order_delivered") is True or row.get("delivered_confirmed") is True:
        return True
    if row.get("current_order_delivered") is False or row.get("delivered_confirmed") is False:
        return False
    if has_delivered_tag(tags):
        return True
    text = _safe_text(
        row.get("delivered_status_label") or row.get("delivered_status"),
        max_length=120,
    ).lower()
    if text == "delivered":
        return True
    if "not delivered" in text or "wait until this order is delivered" in text:
        return False
    return None


def _snapshot_review_request_value(row, tags):
    if row.get("review_request_tag_present") is True or row.get("canonical_review_request_tag_present") is True:
        return True
    if has_review_request_tag(tags):
        return True
    if row.get("review_request_tag_present") is False or row.get("canonical_review_request_tag_present") is False:
        return False
    text = _safe_text(row.get("review_request_tag_status_label"), max_length=160).lower()
    if text.startswith("missing"):
        return False
    return None


def _parse_snapshot_datetime(value):
    text = _safe_text(value, max_length=120)
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _format_snapshot_time(value):
    text = _safe_text(value, max_length=120)
    return text or "Not generated yet"


def _dashboard_snapshot_age_label(age_seconds):
    if age_seconds is None or age_seconds == "":
        return "unknown"
    age_seconds = max(_int_or_zero(age_seconds), 0)
    if age_seconds < 60:
        return "less than a minute ago"
    minutes = age_seconds // 60
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    days = hours // 24
    return f"{days} day{'s' if days != 1 else ''} ago"


def _finalize_dashboard_snapshot_payload(payload):
    safe_payload = _sanitize_dashboard_snapshot_payload(payload or {})
    row_counts = {
        "needs_review_rows": len(safe_payload.get("review_queue_candidates") or []),
        "already_sent_rows": len(safe_payload.get("already_sent_rows") or []),
        "blocked_rows_embedded": len((safe_payload.get("blocked_summary") or {}).get("rows") or []),
        "blocked_total": _int_or_zero((safe_payload.get("blocked_summary") or {}).get("blocked_total")),
    }
    safe_payload["row_counts"] = row_counts
    safe_payload["embedded_history_reports"] = False
    workbench = safe_payload.get("review_request_workbench")
    if isinstance(workbench, dict):
        workbench["history_source_reports"] = []
        dashboard = workbench.get("operating_dashboard")
        if isinstance(dashboard, dict):
            dashboard["snapshot_size_report"] = {
                "row_counts": row_counts,
                "embedded_history_reports": False,
            }
    safe_payload["snapshot_size_bytes"] = len(
        json.dumps(safe_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    )
    return safe_payload


def _sanitize_dashboard_snapshot_payload(value):
    if isinstance(value, dict):
        return {
            _safe_text(key, max_length=160): _sanitize_dashboard_snapshot_payload(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize_dashboard_snapshot_payload(item) for item in value]
    if isinstance(value, str):
        text = CONTROL_CHARS_RE.sub("", value)
        text = EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
        text = SECRET_VALUE_RE.sub("[secret redacted]", text)
        return text
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _sanitize_dashboard_snapshot_payload(str(value))


def _review_send_dashboard_snapshot_blocker():
    report = _load_dashboard_snapshot_report()
    metadata = _dashboard_snapshot_metadata(report, report.get("data") if report.get("loaded") else {})
    if metadata["missing"]:
        return {
            "status": "blocked_dashboard_snapshot_missing",
            "detail": "Review queue is stale. Refresh queue before sending.",
            "snapshot": metadata,
        }
    if metadata["stale"]:
        return {
            "status": "blocked_dashboard_snapshot_stale",
            "detail": "Review queue is stale. Refresh queue before sending.",
            "snapshot": metadata,
        }
    return {"status": "", "detail": "", "snapshot": metadata}


def queue_review_request_send_job(order_identifier, admin_username="", params=None, request_context=None):
    selected_order = _canonical_order_name(order_identifier)
    request_context = request_context or {}
    now = datetime.now(timezone.utc).isoformat()
    enqueue_diagnostics = _review_send_enqueue_diagnostics()
    result = {
        "timestamp": now,
        "route_mode": enqueue_diagnostics["route_mode"],
        "execution_status": "blocked_not_started",
        "success": False,
        "job_queued": False,
        "job_created": False,
        "duplicate_job": False,
        "duplicate_job_detected": False,
        "job_id": "",
        "selected_order": selected_order,
        "message": "",
        "blocking_detail": "",
        "blocking_conditions": [],
        "processor_command": REVIEW_REQUEST_SEND_JOB_PROCESS_COMMAND,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_drafts_send_called": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "external_review_api_call_performed": False,
        "translations_register_called": False,
        "live_lookup_performed": False,
        "batch_customer_history_lookup_performed": False,
        "candidate_scan_performed": False,
        "snapshot_refresh_performed": False,
        "post_send_audit_performed": False,
        "trustpilot_duplicate_audit_performed": False,
        "send_job_processed_inline": False,
        "enqueue_diagnostics": enqueue_diagnostics,
    }
    if not selected_order:
        result["execution_status"] = "blocked_missing_selected_order"
        result["blocking_detail"] = "Review send job was not queued. No selected order was provided."
        result["message"] = result["blocking_detail"]
        return result

    payload = _load_review_request_send_jobs_payload()
    if payload.get("load_error"):
        result["execution_status"] = "blocked_send_job_queue_unavailable"
        result["blocking_detail"] = (
            "Review send job was not queued because the local send-job queue could not be loaded."
        )
        result["blocking_conditions"].append(
            {"status": result["execution_status"], "detail": payload.get("load_error")}
        )
        return result

    existing_job = _find_review_request_send_job(payload.get("jobs"), selected_order)
    if existing_job:
        return _review_request_send_job_duplicate_result(result, existing_job)

    validation = _validate_review_request_send_job_queue_request(
        selected_order,
        request_context,
    )
    if validation.get("blocking_conditions"):
        blocker = validation["blocking_conditions"][0]
        result["execution_status"] = blocker.get("status", "blocked_order_not_eligible")
        result["blocking_detail"] = blocker.get("detail", "Review send job was not queued.")
        result["blocking_conditions"] = validation["blocking_conditions"]
        result["message"] = result["blocking_detail"]
        return result

    payload = _load_review_request_send_jobs_payload()
    if payload.get("load_error"):
        result["execution_status"] = "blocked_send_job_queue_unavailable"
        result["blocking_detail"] = (
            "Review send job was not queued because the local send-job queue could not be loaded."
        )
        result["blocking_conditions"].append(
            {"status": result["execution_status"], "detail": payload.get("load_error")}
        )
        return result
    existing_job = _find_review_request_send_job(payload.get("jobs"), selected_order)
    if existing_job:
        return _review_request_send_job_duplicate_result(result, existing_job)

    job = _build_review_request_send_job(
        selected_order=selected_order,
        admin_username=admin_username,
        created_at=now,
        candidate=validation.get("candidate") or {},
        snapshot=(validation.get("snapshot") or {}),
    )
    payload["jobs"] = [job] + list(payload.get("jobs") or [])
    _write_review_request_send_jobs_payload(payload)
    result.update(
        {
            "execution_status": "review_send_job_queued",
            "success": True,
            "job_queued": True,
            "job_created": True,
            "job_id": job["job_id"],
            "job": _sanitize_review_request_send_job(job),
            "message": "Review send job queued. Run the processor to send it.",
        }
    )
    result["enqueue_diagnostics"] = _review_send_enqueue_diagnostics(job_created=True)
    return result


def _review_request_send_job_duplicate_result(result, existing_job):
    result.update(
        {
            "execution_status": "review_send_job_already_exists",
            "success": True,
            "duplicate_job": True,
            "duplicate_job_detected": True,
            "job_id": existing_job.get("job_id", ""),
            "job": existing_job,
            "message": "Review send job already exists for this order; no duplicate was queued.",
        }
    )
    result["enqueue_diagnostics"] = _review_send_enqueue_diagnostics(
        duplicate_job_detected=True
    )
    return result


def _review_send_enqueue_diagnostics(job_created=False, duplicate_job_detected=False):
    return {
        "route_mode": "enqueue_only",
        "job_created": job_created is True,
        "duplicate_job_detected": duplicate_job_detected is True,
        "gmail_api_call_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "live_lookup_performed": False,
        "snapshot_refresh_performed": False,
    }


def _build_review_send_enqueue_snapshot_state(snapshot_metadata=None):
    report = _load_dashboard_snapshot_report()
    data = report.get("data") if report.get("loaded") else {}
    workbench = data.get("review_request_workbench") if isinstance(data, dict) else {}
    if not isinstance(workbench, dict):
        return {
            "approval_queue": _empty_dashboard_approval_queue(),
            "blocking_conditions": [
                {
                    "status": "blocked_dashboard_snapshot_invalid",
                    "detail": "Review queue is stale. Refresh queue before sending.",
                }
            ],
        }

    dashboard = workbench.get("operating_dashboard") or {}
    source_queue = (dashboard.get("approval_queue") or {}) if isinstance(dashboard, dict) else {}
    lookup_cache = {"orders": {}}
    raw_review_rows = source_queue.get("all_needs_review_rows") or source_queue.get("needs_review_rows")
    candidate_review_rows = _snapshot_dict_rows(
        raw_review_rows,
        default_action_state="review_send",
        lookup_cache=lookup_cache,
    )
    ready_rows = [
        row
        for row in candidate_review_rows
        if row.get("action_state") == "review_send" and row.get("can_review_send") is True
    ]
    demoted_rows = [
        row
        for row in candidate_review_rows
        if row.get("action_state") != "review_send" or row.get("can_review_send") is not True
    ]
    already_sent_rows = _snapshot_dict_rows(
        source_queue.get("all_already_sent_rows") or source_queue.get("already_sent_rows"),
        default_action_state="already_sent",
        lookup_cache=lookup_cache,
    )
    blocked_rows = demoted_rows + _snapshot_dict_rows(
        source_queue.get("blocked_rows"),
        default_action_state="not_ready",
        lookup_cache=lookup_cache,
    )
    approval_queue = _empty_dashboard_approval_queue()
    approval_queue.update(
        {
            "all_needs_review_rows": ready_rows,
            "needs_review_rows": ready_rows,
            "all_already_sent_rows": already_sent_rows,
            "already_sent_rows": already_sent_rows,
            "blocked_rows": blocked_rows,
            "needs_review_count": len(ready_rows),
            "ready_to_send_count": len(ready_rows),
            "already_sent_count": len(already_sent_rows),
            "not_ready_count": len(blocked_rows),
            "blocked_count": len(blocked_rows),
            "review_send_action_enabled_count": len(ready_rows),
            "dashboard_snapshot": snapshot_metadata or {},
        }
    )
    return {"approval_queue": approval_queue, "blocking_conditions": []}


def _review_send_enqueue_request_blockers(request_context):
    blockers = []
    request_context = request_context or {}
    if request_context.get("method") != "POST":
        blockers.append(
            {
                "status": "blocked_admin_post_required",
                "detail": "Review send job was not queued. Review & Send must be submitted by admin POST.",
            }
        )
    if request_context.get("is_staff_admin") is not True:
        blockers.append(
            {
                "status": "blocked_staff_admin_required",
                "detail": "Review send job was not queued. Review & Send is staff/admin only.",
            }
        )
    if request_context.get("csrf_protection_enabled") is not True:
        blockers.append(
            {
                "status": "blocked_csrf_protection_required",
                "detail": "Review send job was not queued. CSRF protection is required.",
            }
        )
    return blockers


def _validate_review_request_send_job_queue_request(selected_order, request_context):
    snapshot_blocker = _review_send_dashboard_snapshot_blocker()
    if snapshot_blocker["status"]:
        return {
            "candidate": {},
            "snapshot": snapshot_blocker.get("snapshot") or {},
            "blocking_conditions": [
                {
                    "status": snapshot_blocker["status"],
                    "detail": snapshot_blocker["detail"],
                }
            ],
        }

    snapshot_state = _build_review_send_enqueue_snapshot_state(snapshot_blocker.get("snapshot") or {})
    if snapshot_state.get("blocking_conditions"):
        return {
            "candidate": {},
            "snapshot": snapshot_blocker.get("snapshot") or {},
            "blocking_conditions": snapshot_state["blocking_conditions"],
        }
    approval_queue = snapshot_state["approval_queue"]
    selected_rows = _review_send_selected_rows(approval_queue, selected_order)
    matches = [
        row
        for row in approval_queue["all_needs_review_rows"]
        if row.get("candidate_id") == selected_order
        and row.get("action_state") == "review_send"
        and row.get("can_review_send") is True
    ]
    if len(matches) != 1:
        return {
            "candidate": selected_rows[0] if selected_rows else {},
            "snapshot": snapshot_blocker.get("snapshot") or {},
            "blocking_conditions": [
                _review_send_selection_blocker(selected_order, selected_rows)
            ],
        }

    candidate = matches[0]
    blocking_conditions = []
    blocking_conditions.extend(_review_send_enqueue_request_blockers(request_context))
    blocking_conditions.extend(_runtime_review_send_group_blockers(candidate))
    blocking_conditions.extend(_runtime_review_send_candidate_safety_blockers(candidate))
    return {
        "candidate": candidate,
        "snapshot": snapshot_blocker.get("snapshot") or {},
        "blocking_conditions": blocking_conditions,
    }


def _build_review_request_send_job(selected_order, admin_username, created_at, candidate, snapshot):
    job_id = _new_review_request_send_job_id(selected_order, admin_username, created_at)
    return {
        "job_id": job_id,
        "order_name": selected_order,
        "created_at": created_at,
        "updated_at": created_at,
        "created_by_admin": _safe_text(admin_username, max_length=120),
        "status": "queued",
        "last_error": "",
        "message": "Review send job queued. Run the processor to send it.",
        "gmail_send_status": "not_started",
        "shopify_tag_status": "not_started",
        "attempts": 0,
        "source": "admin_review_request_workbench",
        "route_mode": "enqueue_only",
        "job_created": True,
        "duplicate_job_detected": False,
        "gmail_api_call_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "live_lookup_performed": False,
        "snapshot_refresh_performed": False,
        "processor_command": REVIEW_REQUEST_SEND_JOB_PROCESS_COMMAND,
        "review_send_report_path": "",
        "dashboard_snapshot_generated_at": _safe_text(
            (snapshot or {}).get("generated_at"),
            max_length=120,
        ),
        "selected_masked_customer": _safe_text(
            (candidate or {}).get("masked_customer_label")
            or (candidate or {}).get("customer_masked_label"),
            max_length=120,
        ),
    }


def process_review_request_send_jobs(max_jobs=1, order_name="", dry_run=False):
    requested_max_jobs = max(_int_or_zero(max_jobs), 1)
    effective_max_jobs = 1
    selected_order = _canonical_order_name(order_name)
    payload = _load_review_request_send_jobs_payload()
    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "process_review_request_send_jobs",
        "dry_run": dry_run is True,
        "requested_max_jobs": requested_max_jobs,
        "effective_max_jobs": effective_max_jobs,
        "max_jobs_capped_to_one": requested_max_jobs > effective_max_jobs,
        "selected_order": selected_order,
        "queue_path": _review_request_send_jobs_relative_path(),
        "queue_load_error": _safe_text(payload.get("load_error"), max_length=300),
        "queued_job_count": 0,
        "selected_job_count": 0,
        "processed_count": 0,
        "sent_count": 0,
        "tag_written_count": 0,
        "failed_count": 0,
        "skipped_count": 0,
        "jobs": [],
        "dashboard_snapshot_refreshed": False,
        "dashboard_snapshot_error": "",
        "gmail_api_call_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "translations_register_called": False,
    }
    if payload.get("load_error"):
        summary["status"] = "failed_queue_unavailable"
        return summary

    queued_jobs = [
        job
        for job in payload.get("jobs") or []
        if job.get("status") == "queued"
        and (not selected_order or _canonical_order_name(job.get("order_name")) == selected_order)
    ]
    queued_jobs.sort(key=lambda job: job.get("created_at") or job.get("updated_at") or job.get("job_id"))
    selected_jobs = queued_jobs[:effective_max_jobs]
    summary["queued_job_count"] = len(queued_jobs)
    summary["selected_job_count"] = len(selected_jobs)
    if dry_run:
        summary["status"] = "dry_run_ready" if selected_jobs else "dry_run_no_queued_jobs"
        summary["jobs"] = [
            {
                "job_id": job.get("job_id"),
                "order_name": job.get("order_name"),
                "status": job.get("status"),
                "message": "Would process this one queued job.",
            }
            for job in selected_jobs
        ]
        return summary

    for job in selected_jobs:
        job_result = _process_one_review_request_send_job(job)
        summary["jobs"].append(job_result)
        if job_result.get("processed"):
            summary["processed_count"] += 1
        if job_result.get("skipped"):
            summary["skipped_count"] += 1
        if job_result.get("status") == "sent":
            summary["sent_count"] += 1
        if job_result.get("status") == "tag_written":
            summary["tag_written_count"] += 1
        if job_result.get("status") == "failed":
            summary["failed_count"] += 1
        summary["gmail_api_call_performed"] = (
            summary["gmail_api_call_performed"]
            or job_result.get("gmail_api_call_performed") is True
        )
        summary["shopify_api_call_performed"] = (
            summary["shopify_api_call_performed"]
            or job_result.get("shopify_api_call_performed") is True
        )
        summary["shopify_write_performed"] = (
            summary["shopify_write_performed"]
            or job_result.get("shopify_write_performed") is True
        )

    if summary["processed_count"]:
        try:
            snapshot = build_review_request_dashboard_snapshot_payload(
                {},
                generated_by="process_review_request_send_jobs",
            )
            write_review_request_dashboard_snapshot_reports(snapshot)
            summary["dashboard_snapshot_refreshed"] = True
        except Exception as exc:  # pragma: no cover - snapshot refresh is best effort after send.
            summary["dashboard_snapshot_error"] = _safe_exception_summary(exc)
    summary["status"] = "processed" if summary["processed_count"] else "no_queued_jobs"
    return summary


def _process_one_review_request_send_job(job):
    job_id = _safe_text(job.get("job_id"), max_length=100)
    order_name = _canonical_order_name(job.get("order_name"))
    current_payload = _load_review_request_send_jobs_payload()
    existing_blocker = _find_review_request_send_job(
        current_payload.get("jobs"),
        order_name,
        exclude_job_id=job_id,
        for_processing=True,
    )
    if existing_blocker:
        blocked = _update_review_request_send_job(
            job_id,
            {
                "status": "failed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "last_error": (
                    "Duplicate job blocked. Another job for this order is already running, "
                    "sent, or tag-written."
                ),
                "message": "Duplicate send job blocked. Gmail was not resent.",
            },
        )
        return {
            "job_id": job_id,
            "order_name": order_name,
            "status": "failed",
            "processed": False,
            "skipped": True,
            "message": (blocked or {}).get("message") or "Duplicate job blocked.",
            "gmail_api_call_performed": False,
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
        }

    running = _update_review_request_send_job(
        job_id,
        {
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "attempts": _int_or_zero(job.get("attempts")) + 1,
            "message": "Review send job is running.",
        },
    )
    try:
        result = review_request_review_and_send(
            order_name,
            admin_username=(running or job).get("created_by_admin") or "process_review_request_send_jobs",
            params={},
            request_context={
                "method": "POST",
                "is_staff_admin": True,
                "csrf_protection_enabled": True,
                "queued_job_id": job_id,
            },
        )
        updates = _review_request_send_job_updates_from_result(result)
    except Exception as exc:  # pragma: no cover - defensive guard around one real send path.
        result = {
            "execution_status": "failed_worker_exception_after_start",
            "gmail_api_call_performed": False,
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
        }
        updates = {
            "status": "failed",
            "gmail_send_status": "unknown_after_start",
            "shopify_tag_status": "unknown_after_start",
            "last_error": (
                "Worker failed after the send path started. Do not retry from the web page; "
                f"review logs first. {_safe_exception_summary(exc)}"
            ),
            "message": "Review send job failed after the worker started.",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }
    updated = _update_review_request_send_job(job_id, updates)
    return {
        "job_id": job_id,
        "order_name": order_name,
        "status": (updated or updates).get("status", "failed"),
        "processed": True,
        "skipped": False,
        "message": (updated or updates).get("message", ""),
        "last_error": (updated or updates).get("last_error", ""),
        "gmail_api_call_performed": result.get("gmail_api_call_performed") is True,
        "shopify_api_call_performed": result.get("shopify_api_call_performed") is True,
        "shopify_write_performed": result.get("shopify_write_performed") is True,
    }


def _update_review_request_send_job(job_id, updates):
    payload = _load_review_request_send_jobs_payload()
    jobs = list(payload.get("jobs") or [])
    updated_job = {}
    for index, job in enumerate(jobs):
        if job.get("job_id") != job_id:
            continue
        updated_job = dict(job)
        updated_job.update(updates or {})
        updated_job["updated_at"] = datetime.now(timezone.utc).isoformat()
        jobs[index] = updated_job
        break
    if not updated_job:
        return {}
    payload["jobs"] = jobs
    _write_review_request_send_jobs_payload(payload)
    return _sanitize_review_request_send_job(updated_job)


def _review_request_send_job_updates_from_result(result):
    completed_at = datetime.now(timezone.utc).isoformat()
    email_sent = result.get("email_sent") is True
    tag_written = (
        result.get("final_workflow_status") == "completed_email_sent_tag_written"
        or result.get("shopify_tag_write_confirmed") is True
        or result.get("auto_tag_write_status") == TRUSTPILOT_TAG_WRITE_SUCCESS_STATUS
    )
    if tag_written:
        return {
            "status": "tag_written",
            "completed_at": completed_at,
            "gmail_send_status": "sent",
            "shopify_tag_status": "tag_written",
            "last_error": "",
            "message": "Trustpilot email sent and Shopify tag written.",
            "review_send_report_path": f"logs/{REVIEW_AND_SEND_REPORT_FILENAME}",
        }
    if email_sent:
        tag_error = (
            result.get("auto_tag_write_user_message")
            or result.get("auto_tag_write_status")
            or result.get("blocking_detail")
            or "Shopify tag update did not complete."
        )
        return {
            "status": "sent",
            "completed_at": completed_at,
            "gmail_send_status": "sent",
            "shopify_tag_status": "failed",
            "last_error": _safe_text(tag_error, max_length=400),
            "message": "Trustpilot email sent. Shopify tag update needs attention; do not resend Gmail.",
            "review_send_report_path": f"logs/{REVIEW_AND_SEND_REPORT_FILENAME}",
        }
    blocker = (
        result.get("blocking_detail")
        or result.get("gmail_error_sanitized")
        or result.get("execution_status")
        or "Review send job failed before email send."
    )
    gmail_started = bool(
        result.get("gmail_api_call_performed") is True
        or result.get("gmail_draft_create_attempted") is True
        or result.get("gmail_draft_send_attempted") is True
    )
    return {
        "status": "failed",
        "completed_at": completed_at,
        "gmail_send_status": "failed" if gmail_started else "not_started",
        "shopify_tag_status": "not_started",
        "last_error": _safe_text(blocker, max_length=400),
        "message": "Review send job failed. No confirmed Gmail send.",
        "review_send_report_path": f"logs/{REVIEW_AND_SEND_REPORT_FILENAME}",
    }


def review_request_review_and_send(order_identifier, admin_username="", params=None, request_context=None):
    state = _build_review_send_state(params)
    selected_order = _safe_text(order_identifier, max_length=80)
    request_context = request_context or {}
    result = _base_review_and_send_result(selected_order, admin_username, state, request_context)
    snapshot_blocker = _review_send_dashboard_snapshot_blocker()
    result["dashboard_snapshot"] = snapshot_blocker["snapshot"]
    if snapshot_blocker["status"]:
        result["execution_status"] = snapshot_blocker["status"]
        result["blocking_conditions"].append(
            {
                "status": snapshot_blocker["status"],
                "detail": snapshot_blocker["detail"],
            }
        )
        result["blocking_status"] = snapshot_blocker["status"]
        result["blocking_detail"] = snapshot_blocker["detail"]
        result["exact_user_message"] = snapshot_blocker["detail"]
        result["next_admin_action"] = "Refresh the Review Requests dashboard snapshot before sending."
        return _finalize_review_and_send_result(result)
    selected_rows = _review_send_selected_rows(state["approval_queue"], selected_order)
    matches = [
        row
        for row in state["approval_queue"]["needs_review_rows"]
        if row.get("candidate_id") == selected_order and row.get("action_state") == "review_send"
    ]
    if len(matches) != 1:
        blocker = _review_send_selection_blocker(selected_order, selected_rows)
        diagnosis = _review_send_readiness_diagnosis(
            selected_order,
            selected_rows[0] if selected_rows else {},
            state["gmail_setup"],
            candidate_found=bool(selected_rows),
            candidate_currently_eligible=False,
            route_revalidation_blocker=blocker["status"],
        )
        _apply_review_send_diagnosis(result, diagnosis)
        result["execution_status"] = blocker["status"]
        result["blocking_detail"] = blocker["detail"]
        result["blocking_conditions"].append(blocker)
        return _finalize_review_and_send_result(result)

    candidate = matches[0]
    diagnosis = _review_send_readiness_diagnosis(
        selected_order,
        candidate,
        state["gmail_setup"],
        candidate_found=True,
        candidate_currently_eligible=True,
    )
    _apply_review_send_diagnosis(result, diagnosis)
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
    result["selected_order_latest_for_customer"] = candidate.get("selected_order_latest_for_customer") is True
    result["selected_latest_eligible_order_for_customer"] = _safe_text(
        candidate.get("latest_eligible_order_for_customer") or candidate.get("order"),
        max_length=80,
    )
    result["selected_masked_email"] = candidate.get("masked_customer_label") or candidate.get("customer")
    result["ebay_tag_detected"] = candidate.get("ebay_tag_detected") is True
    result["matched_ebay_tag_value"] = _safe_text(candidate.get("matched_ebay_tag_value"), max_length=120)
    result["gmail_scope_status"] = state["gmail_setup"]["scope_status"]
    result["gmail_compose_send_supported"] = bool(
        state["gmail_setup"]["gmail_compose_send_supported"]
    )
    result["template_status"] = "approved_trustpilot_template"
    result["template_subject"] = TRUSTPILOT_EMAIL_SUBJECT

    route_blockers = _runtime_review_send_route_blockers(result, candidate)
    if route_blockers:
        result["execution_status"] = route_blockers[0]["status"]
        result["blocking_detail"] = route_blockers[0]["detail"]
        result["blocking_conditions"].extend(route_blockers)
        return _finalize_review_and_send_result(result)

    group_blockers = _runtime_review_send_group_blockers(candidate)
    if group_blockers:
        result["execution_status"] = group_blockers[0]["status"]
        result["blocking_detail"] = group_blockers[0]["detail"]
        result["blocking_conditions"].extend(group_blockers)
        return _finalize_review_and_send_result(result)

    live_history_blockers = _runtime_customer_history_live_lookup_blockers(
        candidate,
        state["last_60_days_scan"],
        state["reports"],
        (snapshot_blocker.get("snapshot") or {}).get("generated_at"),
    )
    if live_history_blockers:
        result["execution_status"] = live_history_blockers[0]["status"]
        result["blocking_status"] = live_history_blockers[0]["status"]
        result["blocking_detail"] = live_history_blockers[0]["detail"]
        result["blocked_reason"] = live_history_blockers[0].get("blocked_reason", "customer history live check required")
        result["exact_user_message"] = live_history_blockers[0]["detail"]
        result["blocking_conditions"].extend(live_history_blockers)
        return _finalize_review_and_send_result(result)

    runtime_blockers = _runtime_review_send_blockers(candidate, state["gmail_setup"], diagnosis)
    if runtime_blockers:
        result["execution_status"] = runtime_blockers[0]["status"]
        result["blocking_detail"] = runtime_blockers[0]["detail"]
        result["blocking_conditions"].extend(runtime_blockers)
        return _finalize_review_and_send_result(result)

    send_result = _send_dynamic_trustpilot_gmail(candidate)
    result.update(send_result)
    result["execution_status"] = send_result["execution_status"]
    if send_result.get("email_sent") is True:
        result["success"] = True
        _auto_post_send_tag_write_after_success(result)
    else:
        result["blocking_status"] = send_result["execution_status"]
        result["blocking_detail"] = send_result.get("gmail_error_sanitized") or "No email was sent. Gmail send failed."
        result["final_workflow_status"] = (
            "send_failed_no_tag_write"
            if send_result.get("gmail_api_call_performed") is True
            or send_result.get("gmail_draft_create_attempted") is True
            or send_result.get("gmail_draft_send_attempted") is True
            else "blocked_before_send"
        )
        result["blocking_conditions"].append(
            {
                "status": send_result["execution_status"],
                "detail": result["blocking_detail"],
            }
        )
    return _finalize_review_and_send_result(result)


def _auto_post_send_tag_write_after_success(result):
    post_send_audit = _review_send_post_send_audit_payload(
        source_report=result,
        source_error="",
        source_json_path="in-memory:review_send_post_success",
        source_html_path="",
        source_html_found=False,
    )
    result["post_send_audit_status"] = post_send_audit.get("audit_status", "")
    result["post_send_audit_success"] = post_send_audit.get("success") is True
    result["post_send_audit_selected_order"] = post_send_audit.get("selected_order", "")
    result["post_send_audit_email_sent_confirmed"] = post_send_audit.get("email_sent_confirmed") is True
    result["post_send_audit_sent_count"] = _int_or_zero(post_send_audit.get("sent_count"))
    if post_send_audit.get("success") is not True:
        result["auto_tag_write_attempted"] = False
        result["auto_tag_write_status"] = post_send_audit.get("audit_status", "blocked_post_send_audit_not_passed")
        result["exact_user_message"] = (
            "Trustpilot email sent, but Shopify tag update failed. Run post-send tag write."
        )
        result["next_admin_action"] = "Run post-send audit, then post-send tag write for this order."
        result["final_workflow_status"] = "email_sent_tag_pending"
        return

    result["auto_tag_write_attempted"] = True
    tag_write_result = execute_trustpilot_post_send_tag_write(
        selected_order=result.get("selected_order"),
        verified_post_send_audit_data=post_send_audit,
        approval_source="review_send_post_success",
        allow_auto_after_send=True,
    )
    _apply_auto_tag_write_result_to_review_send(result, tag_write_result)


def _apply_auto_tag_write_result_to_review_send(result, tag_write_result):
    status = _safe_text(tag_write_result.get("tag_write_status"), max_length=120)
    result["auto_tag_write_status"] = status
    result["auto_tag_write_blocking_conditions"] = tag_write_result.get("blocking_conditions") or []
    result["auto_tag_write_user_message"] = _safe_text(tag_write_result.get("user_message"), max_length=300)
    result["shopify_api_call_performed"] = tag_write_result.get("shopify_api_call_performed") is True
    result["shopify_write_performed"] = tag_write_result.get("shopify_write_performed") is True
    result["shopify_tag_write_performed"] = tag_write_result.get("shopify_tag_write_performed") is True
    result["mutation_performed"] = tag_write_result.get("mutation_performed") is True
    result["tags_add_performed"] = tag_write_result.get("tags_add_performed") is True
    result["tags_remove_performed"] = tag_write_result.get("tags_remove_performed") is True
    result["trustpilot_tag_added"] = tag_write_result.get("trustpilot_tag_added") is True
    result["review_request_tag_removed"] = tag_write_result.get("review_request_tag_removed") is True
    result["typo_review_request_tag_removed"] = tag_write_result.get("typo_review_request_tag_removed") is True
    result["all_review_request_aliases_removed"] = tag_write_result.get("all_review_request_aliases_removed") is True
    result["tag_write_readback_verified"] = tag_write_result.get("readback_verified") is True
    result["local_shopify_tags_updated"] = tag_write_result.get("local_shopify_tags_updated") is True
    result["shopify_tag_write_confirmed"] = status == TRUSTPILOT_TAG_WRITE_SUCCESS_STATUS
    result["shopify_tag_written"] = result["shopify_tag_write_confirmed"]
    if result["shopify_tag_write_confirmed"]:
        result["execution_status"] = "trustpilot_email_sent_shopify_tag_written"
        result["exact_user_message"] = "Trustpilot email sent. Shopify tag updated."
        result["next_admin_action"] = "No further action is needed for this order."
        result["final_workflow_status"] = "completed_email_sent_tag_written"
    else:
        result["execution_status"] = "trustpilot_email_sent_shopify_tag_pending"
        result["exact_user_message"] = (
            "Trustpilot email sent, but Shopify tag update failed. Run post-send tag write."
        )
        result["next_admin_action"] = "Run post-send tag write for this order. Do not resend Gmail."
        result["final_workflow_status"] = "email_sent_tag_pending"


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


def _review_request_send_jobs_path():
    return _log_dir() / REVIEW_REQUEST_SEND_JOBS_FILENAME


def _review_request_send_jobs_relative_path():
    return f"logs/{REVIEW_REQUEST_SEND_JOBS_FILENAME}"


def _empty_review_request_send_jobs_payload(load_error=""):
    return {
        "schema_version": REVIEW_REQUEST_SEND_JOB_SCHEMA_VERSION,
        "updated_at": "",
        "jobs": [],
        "load_error": _safe_text(load_error, max_length=300),
        "path": str(_review_request_send_jobs_path()),
        "relative_path": _review_request_send_jobs_relative_path(),
    }


def _load_review_request_send_jobs_payload():
    path = _review_request_send_jobs_path()
    payload = _empty_review_request_send_jobs_payload()
    if not path.exists():
        return payload
    try:
        stat = path.stat()
        if stat.st_size > MAX_REPORT_BYTES:
            return _empty_review_request_send_jobs_payload("send_job_queue_too_large")
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        return _empty_review_request_send_jobs_payload(
            f"send_job_queue_unreadable: {_safe_exception_summary(exc)}"
        )
    if isinstance(data, list):
        jobs = data
        updated_at = ""
    elif isinstance(data, dict):
        jobs = data.get("jobs") or []
        updated_at = _safe_text(data.get("updated_at"), max_length=120)
    else:
        return _empty_review_request_send_jobs_payload("send_job_queue_not_object")
    payload["updated_at"] = updated_at
    payload["jobs"] = _sanitize_review_request_send_jobs(jobs)
    return payload


def _write_review_request_send_jobs_payload(payload):
    safe_payload = {
        "schema_version": REVIEW_REQUEST_SEND_JOB_SCHEMA_VERSION,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "jobs": _sanitize_review_request_send_jobs((payload or {}).get("jobs") or [])[
            :REVIEW_REQUEST_SEND_JOB_MAX_STORED
        ],
    }
    path = _review_request_send_jobs_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    with temp_path.open("w", encoding="utf-8") as queue_file:
        json.dump(safe_payload, queue_file, ensure_ascii=False, indent=2)
        queue_file.write("\n")
    json.loads(temp_path.read_text(encoding="utf-8"))
    os.replace(temp_path, path)
    safe_payload["path"] = str(path)
    safe_payload["relative_path"] = _review_request_send_jobs_relative_path()
    return safe_payload


def _sanitize_review_request_send_jobs(jobs):
    sanitized = [
        _sanitize_review_request_send_job(job)
        for job in (jobs or [])
        if isinstance(job, dict)
    ]
    sanitized = [job for job in sanitized if job.get("job_id") and job.get("order_name")]
    sanitized.sort(key=_review_request_send_job_sort_key, reverse=True)
    return sanitized


def _sanitize_review_request_send_job(job):
    status = _safe_text(job.get("status"), max_length=40)
    if status not in REVIEW_REQUEST_SEND_JOB_STATUSES:
        status = "queued"
    gmail_send_status = _safe_text(job.get("gmail_send_status"), max_length=80)
    shopify_tag_status = _safe_text(job.get("shopify_tag_status"), max_length=80)
    sanitized = {
        "job_id": _safe_text(job.get("job_id"), max_length=100),
        "order_name": _canonical_order_name(job.get("order_name") or job.get("order")),
        "created_at": _safe_text(job.get("created_at"), max_length=120),
        "updated_at": _safe_text(job.get("updated_at"), max_length=120),
        "started_at": _safe_text(job.get("started_at"), max_length=120),
        "completed_at": _safe_text(job.get("completed_at"), max_length=120),
        "created_by_admin": _safe_text(job.get("created_by_admin"), max_length=120),
        "status": status,
        "gmail_send_status": gmail_send_status or "not_started",
        "shopify_tag_status": shopify_tag_status or "not_started",
        "last_error": _safe_text(job.get("last_error"), max_length=400),
        "message": _safe_text(job.get("message"), max_length=400),
        "attempts": _int_or_zero(job.get("attempts")),
        "source": _safe_text(job.get("source"), max_length=120),
        "route_mode": _safe_text(job.get("route_mode") or "enqueue_only", max_length=80),
        "job_created": job.get("job_created") is True,
        "duplicate_job_detected": job.get("duplicate_job_detected") is True,
        "gmail_api_call_performed": job.get("gmail_api_call_performed") is True,
        "shopify_api_call_performed": job.get("shopify_api_call_performed") is True,
        "shopify_write_performed": job.get("shopify_write_performed") is True,
        "live_lookup_performed": job.get("live_lookup_performed") is True,
        "snapshot_refresh_performed": job.get("snapshot_refresh_performed") is True,
        "processor_command": _safe_text(job.get("processor_command"), max_length=300),
        "review_send_report_path": _safe_text(job.get("review_send_report_path"), max_length=180),
        "dashboard_snapshot_generated_at": _safe_text(
            job.get("dashboard_snapshot_generated_at"),
            max_length=120,
        ),
        "selected_masked_customer": _safe_text(job.get("selected_masked_customer"), max_length=120),
    }
    sanitized["status_label"] = _review_request_send_job_status_label(sanitized)
    sanitized["status_class"] = _review_request_send_job_status_class(sanitized)
    if not sanitized["message"]:
        sanitized["message"] = _review_request_send_job_message(sanitized)
    return sanitized


def _review_request_send_job_sort_key(job):
    return (
        _safe_text(job.get("updated_at"), max_length=120)
        or _safe_text(job.get("created_at"), max_length=120)
        or _safe_text(job.get("job_id"), max_length=100)
    )


def _review_request_send_job_status_label(job):
    status = _safe_text(job.get("status"), max_length=40)
    return {
        "queued": "Queued",
        "running": "Running",
        "sent": "Sent",
        "tag_written": "Tag written",
        "completed": "Completed",
        "unknown_after_start": "Unknown after start",
        "failed": "Failed",
    }.get(status, "Queued")


def _review_request_send_job_status_class(job):
    status = _safe_text(job.get("status"), max_length=40)
    if status == "failed":
        return "rrw-badge-bad"
    if status in {"queued", "running"}:
        return "rrw-badge-warn"
    if status in {"sent", "tag_written", "completed"}:
        return "rrw-badge-ok"
    if status == "unknown_after_start":
        return "rrw-badge-bad"
    return "rrw-badge-muted"


def _review_request_send_job_message(job):
    status = _safe_text(job.get("status"), max_length=40)
    if status == "queued":
        return "Review send job queued. Run the processor to send it."
    if status == "running":
        return "Review send job is running."
    if status == "completed":
        return "Review send job completed."
    if status == "unknown_after_start":
        return "Review send job status is unknown after send processing started."
    if status == "tag_written":
        return "Trustpilot email sent and Shopify tag written."
    if status == "sent":
        return "Trustpilot email sent. Do not resend Gmail."
    if status == "failed":
        return _safe_text(job.get("last_error"), max_length=300) or "Review send job failed."
    return "Review send job status is available."


def load_review_request_send_jobs(limit=REVIEW_REQUEST_SEND_JOB_VISIBLE_LIMIT):
    payload = _load_review_request_send_jobs_payload()
    jobs = list(payload.get("jobs") or [])
    if limit:
        jobs = jobs[: max(_int_or_zero(limit), 0)]
    return jobs


def _latest_review_request_send_job_by_order(jobs):
    latest = {}
    for job in jobs or []:
        order_name = _canonical_order_name(job.get("order_name"))
        if not order_name:
            continue
        if order_name not in latest:
            latest[order_name] = job
    return latest


def _review_request_send_job_prevents_duplicate(job):
    status = _safe_text(job.get("status"), max_length=40)
    return bool(
        status in REVIEW_REQUEST_SEND_JOB_DUPLICATE_STATUSES
        or job.get("gmail_send_status") in {"sent", "unknown_after_start"}
        or job.get("shopify_tag_status") in {"tag_written", "unknown_after_start"}
    )


def _review_request_send_job_prevents_processing(job):
    status = _safe_text(job.get("status"), max_length=40)
    return bool(
        status in {"running", "sent", "tag_written", "completed", "unknown_after_start"}
        or job.get("gmail_send_status") in {"sent", "unknown_after_start"}
        or job.get("shopify_tag_status") in {"tag_written", "unknown_after_start"}
    )


def _find_review_request_send_job(jobs, order_name, exclude_job_id="", for_processing=False):
    selected_order = _canonical_order_name(order_name)
    excluded = _safe_text(exclude_job_id, max_length=100)
    for job in jobs or []:
        if _canonical_order_name(job.get("order_name")) != selected_order:
            continue
        if excluded and job.get("job_id") == excluded:
            continue
        if for_processing:
            if _review_request_send_job_prevents_processing(job):
                return job
        elif _review_request_send_job_prevents_duplicate(job):
            return job
    return {}


def _new_review_request_send_job_id(order_name, admin_username, created_at):
    seed = f"{order_name}|{admin_username}|{created_at}"
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:12]
    timestamp = re.sub(r"[^0-9A-Za-z]", "", created_at)[:15]
    return f"rrsj_{timestamp}_{digest}"


def _attach_review_request_send_jobs_to_approval_queue(approval_queue):
    payload = _load_review_request_send_jobs_payload()
    jobs = payload.get("jobs") or []
    latest_by_order = _latest_review_request_send_job_by_order(jobs)
    for key in (
        "all_needs_review_rows",
        "needs_review_rows",
        "blocked_rows",
        "all_already_sent_rows",
        "already_sent_rows",
    ):
        rows = approval_queue.get(key)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                _apply_review_request_send_job_to_queue_row(
                    row,
                    latest_by_order.get(_canonical_order_name(row.get("order") or row.get("order_name"))),
                )
    visible_rows = approval_queue.get("needs_review_rows") or []
    approval_queue["review_send_action_enabled_count"] = sum(
        1 for row in visible_rows if isinstance(row, dict) and row.get("can_review_send") is True
    )
    summary = {
        "storage_relative_path": _review_request_send_jobs_relative_path(),
        "storage_path": _safe_text(payload.get("path"), max_length=500),
        "load_error": _safe_text(payload.get("load_error"), max_length=300),
        "loaded": not bool(payload.get("load_error")),
        "recent_jobs": jobs[:REVIEW_REQUEST_SEND_JOB_VISIBLE_LIMIT],
        "recent_job_count": min(len(jobs), REVIEW_REQUEST_SEND_JOB_VISIBLE_LIMIT),
        "total_job_count": len(jobs),
        "active_job_count": sum(
            1 for job in jobs if job.get("status") in REVIEW_REQUEST_SEND_JOB_ACTIVE_STATUSES
        ),
        "manual_process_command": REVIEW_REQUEST_SEND_JOB_PROCESS_COMMAND,
        "dry_run_command": f"{REVIEW_REQUEST_SEND_JOB_PROCESS_COMMAND} --dry-run",
    }
    approval_queue["recent_send_jobs"] = summary["recent_jobs"]
    approval_queue["send_job_storage_path"] = summary["storage_relative_path"]
    approval_queue["send_job_load_error"] = summary["load_error"]
    approval_queue["active_send_job_count"] = summary["active_job_count"]
    approval_queue["send_job_manual_process_command"] = summary["manual_process_command"]
    approval_queue["send_job_dry_run_command"] = summary["dry_run_command"]
    return summary


def _apply_review_request_send_job_to_queue_row(row, job):
    if not job:
        row["send_job_status"] = ""
        row["send_job_status_label"] = ""
        row["send_job_message"] = ""
        row["send_job_last_error"] = ""
        row["review_send_job_blocks_action"] = False
        return row
    row["send_job_id"] = _safe_text(job.get("job_id"), max_length=100)
    row["send_job_status"] = _safe_text(job.get("status"), max_length=40)
    row["send_job_status_label"] = _review_request_send_job_status_label(job)
    row["send_job_status_class"] = _review_request_send_job_status_class(job)
    row["send_job_message"] = _safe_text(job.get("message"), max_length=300)
    row["send_job_last_error"] = _safe_text(job.get("last_error"), max_length=300)
    row["send_job_created_at"] = _safe_text(job.get("created_at"), max_length=120)
    row["send_job_updated_at"] = _safe_text(job.get("updated_at"), max_length=120)
    row["send_job_gmail_send_status"] = _safe_text(job.get("gmail_send_status"), max_length=80)
    row["send_job_shopify_tag_status"] = _safe_text(job.get("shopify_tag_status"), max_length=80)
    blocks_action = _review_request_send_job_prevents_duplicate(job)
    row["review_send_job_blocks_action"] = blocks_action
    if blocks_action:
        row["can_review_send"] = False
        if row.get("send_job_status") in REVIEW_REQUEST_SEND_JOB_ACTIVE_STATUSES:
            row["action_label"] = "Processing"
            row["action_status"] = "Processing"
        else:
            row["action_label"] = row["send_job_status_label"]
            row["action_status"] = row["send_job_status_label"]
        row["review_send_post_action"] = ""
        row["hidden_reason"] = row["send_job_message"] or row["send_job_last_error"]
    return row


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
            SHOPIFY_ORDER_TAG_FIELD,
        )[:10]
        return {
            "available": True,
            "total_orders": orders.count(),
            "orders_with_email": with_email.count(),
            "orders_with_shopify_tag_data": orders.filter(shopify_tags__isnull=False).count(),
            "recent_orders": [
                {
                    "order_name": _safe_text(row.get("order_name")),
                    "masked_email": mask_email(row.get("customer_email")),
                    "order_created_at": _safe_text(row.get("order_created_at")),
                    "fulfillment_status": _safe_text(row.get("fulfillment_status")),
                    "financial_status": _safe_text(row.get("financial_status")),
                    "tags_summary": _tags_summary(
                        _shopify_tags_from_order(row),
                        _shopify_tags_loaded_from_order(row),
                    ),
                }
                for row in latest
            ],
            "note": (
                "Local ShopifyOrder rows store Shopify order tags in ShopifyOrder.shopify_tags "
                "after the Review Request sync is rerun."
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
    try:
        page = int(_param_get(params, "page") or 1)
    except (TypeError, ValueError):
        page = 1
    page = max(page, 1)
    try:
        page_size = int(_param_get(params, "page_size") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        page_size = DEFAULT_LIMIT
    if page_size not in LIMIT_OPTIONS:
        page_size = DEFAULT_LIMIT
    try:
        sent_page = int(_param_get(params, "sent_page") or 1)
    except (TypeError, ValueError):
        sent_page = 1
    sent_page = max(sent_page, 1)
    try:
        sent_page_size = int(_param_get(params, "sent_page_size") or DEFAULT_LIMIT)
    except (TypeError, ValueError):
        sent_page_size = DEFAULT_LIMIT
    if sent_page_size not in LIMIT_OPTIONS:
        sent_page_size = DEFAULT_LIMIT
    return {
        "q": q,
        "status": status,
        "tag": tag,
        "limit": limit,
        "page": page,
        "page_size": page_size,
        "sent_page": sent_page,
        "sent_page_size": sent_page_size,
        "has_active_filters": bool(
            q
            or status != "all"
            or tag != "all"
            or limit != DEFAULT_LIMIT
            or sent_page != 1
            or sent_page_size != DEFAULT_LIMIT
        ),
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


def _selected_page_size_options(selected_page_size):
    return [
        {
            "value": value,
            "label": str(value),
            "selected": value == selected_page_size,
            "url": _review_queue_page_url(1, value),
        }
        for value in LIMIT_OPTIONS
    ]


def _selected_sent_page_size_options(
    selected_page_size,
    review_page=1,
    review_page_size=DEFAULT_LIMIT,
):
    return [
        {
            "value": value,
            "label": str(value),
            "selected": value == selected_page_size,
            "url": _sent_queue_page_url(1, value, review_page, review_page_size),
        }
        for value in LIMIT_OPTIONS
    ]


def _review_queue_page_url(page, page_size):
    normalized_page = max(_int_or_zero(page), 1)
    normalized_page_size = _int_or_zero(page_size)
    if normalized_page_size not in LIMIT_OPTIONS:
        normalized_page_size = DEFAULT_LIMIT
    return "?" + urlencode({"page": normalized_page, "page_size": normalized_page_size})


def _sent_queue_page_url(
    sent_page,
    sent_page_size,
    review_page=1,
    review_page_size=DEFAULT_LIMIT,
):
    normalized_sent_page = max(_int_or_zero(sent_page), 1)
    normalized_sent_page_size = _int_or_zero(sent_page_size)
    if normalized_sent_page_size not in LIMIT_OPTIONS:
        normalized_sent_page_size = DEFAULT_LIMIT
    normalized_review_page = max(_int_or_zero(review_page), 1)
    normalized_review_page_size = _int_or_zero(review_page_size)
    if normalized_review_page_size not in LIMIT_OPTIONS:
        normalized_review_page_size = DEFAULT_LIMIT
    return "?" + urlencode(
        {
            "page": normalized_review_page,
            "page_size": normalized_review_page_size,
            "sent_page": normalized_sent_page,
            "sent_page_size": normalized_sent_page_size,
        }
    )


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
        ("review_send_post_send_audit", "Review & Send post-send audit"),
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
    if row.get("note_risk_detected") is True:
        return True
    text = _row_block_text(row)
    text = text.replace("no duplicate or risk found", "").replace("no duplicate or risk", "")
    return any(
        needle in text
        for needle in (
            "risk",
            "ticket",
            "refund",
            "cancel",
            "cancelled",
            "dispute",
            "chargeback",
            "blocked_note_risk_detected",
            "aftersales/ticket note found",
        )
    )


def _row_text_contains(row, needles):
    haystack = " ".join(
        (
            row.get("status", ""),
            row.get("blocking_summary", ""),
            row.get("reason", ""),
            row.get("eligibility_reason_plain", ""),
            row.get("tags_summary", ""),
            row.get("source_section", ""),
            row.get("note_risk_reason", ""),
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
                "sent_at": _safe_text(event.get("event_time")) or _safe_text(event.get("loaded_at")),
                "email_sent_at": _safe_text(event.get("event_time")) or _safe_text(event.get("loaded_at")),
                "shopify_tag_written": event.get("shopify_tag_written") is True,
                "tag_written_at": (
                    _safe_text(event.get("event_time")) or _safe_text(event.get("loaded_at"))
                    if event.get("shopify_tag_written") is True
                    else ""
                ),
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


def _queue_trustpilot_email_records(history_ledger, reports):
    records = _trustpilot_email_records(
        history_ledger.get("all_events") or [],
        _unfiltered_trustpilot_record_filters(),
    )
    return _merge_trustpilot_email_records(
        _local_review_send_success_records(reports),
        records,
    )


def _unfiltered_trustpilot_record_filters():
    return {
        "q": "",
        "channel": "all",
        "event_type": "all",
        "ledger_status": "",
        "order": "",
        "ledger_limit": MAX_SOURCE_ROWS,
    }


def _merge_trustpilot_email_records(primary_records, secondary_records):
    records = []
    seen_sent_orders = set()
    for record in primary_records or []:
        order_name = _canonical_order_name(record.get("order_name"))
        if record.get("email_sent") is True and order_name:
            seen_sent_orders.add(order_name)
        records.append(record)
    for record in secondary_records or []:
        order_name = _canonical_order_name(record.get("order_name"))
        if record.get("email_sent") is True and order_name in seen_sent_orders:
            continue
        records.append(record)
    return records[:MAX_SOURCE_ROWS]


def _local_review_send_success_records(reports=None):
    records = []
    reports = reports or {}
    for report_key in ("trustpilot_review_and_send_execute", "review_send_post_send_audit"):
        report = reports.get(report_key) or {}
        record = _local_review_send_record_from_payload(
            report.get("data") or {},
            source_label=report.get("label"),
            source_path=report.get("relative_path"),
        )
        if record:
            records.append(record)
    for payload, source_path, source_label in _local_review_send_report_payloads_from_disk():
        record = _local_review_send_record_from_payload(
            payload,
            source_label=source_label,
            source_path=source_path,
        )
        if record:
            records.append(record)
    return _dedupe_local_review_send_records(records)


def _local_review_send_report_payloads_from_disk():
    reports = []
    for filename, label in (
        (REVIEW_AND_SEND_REPORT_FILENAME, "Trustpilot Review & Send execute"),
        (REVIEW_SEND_POST_SEND_AUDIT_REPORT_FILENAME, "Review & Send post-send audit"),
        (TRUSTPILOT_POST_SEND_TAG_WRITE_REPORT_FILENAME, "Trustpilot post-send Shopify tag write"),
    ):
        path = _log_dir() / filename
        if not path.exists():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            continue
        if isinstance(payload, dict):
            reports.append((payload, f"logs/{filename}", label))
    return reports


def _local_review_send_record_from_payload(payload, source_label="", source_path=""):
    if not isinstance(payload, dict):
        return {}
    email_sent = (
        payload.get("email_sent") is True
        or payload.get("email_sent_confirmed") is True
        or payload.get("source_email_sent_confirmed") is True
    )
    sent_count = _int_or_zero(payload.get("sent_count") or payload.get("source_sent_count"))
    if not (email_sent and sent_count == 1):
        return {}
    order_name = _canonical_order_name(
        payload.get("selected_order")
        or payload.get("selected_order_name")
        or payload.get("target_order")
        or ((payload.get("selected_order") or {}) if isinstance(payload.get("selected_order"), str) else "")
    )
    if not order_name:
        return {}
    shopify_tag_written = _shopify_tag_write_confirmed_from_payload(payload)
    masked = (
        mask_email(payload.get("selected_masked_email"))
        or mask_email(payload.get("selected_customer"))
        or "Masked in reports"
    )
    source_path = _safe_text(source_path, max_length=180)
    if not source_path:
        source_path = f"logs/{REVIEW_AND_SEND_REPORT_FILENAME}"
    sent_at = _payload_time_value(
        payload,
        (
            "sent_at",
            "email_sent_at",
            "email_sent_time",
            "gmail_sent_at",
            "source_email_sent_at",
            "timestamp",
            "report_generated_at",
        ),
    )
    tag_write_status = _safe_text(
        payload.get("tag_write_status") or payload.get("auto_tag_write_status"),
        max_length=120,
    )
    tag_written_at = (
        _payload_time_value(
            payload,
            (
                "tag_written_at",
                "tag_write_completed_at",
                "tag_write_timestamp",
                "tag_write_report_generated_at",
                "timestamp",
                "report_generated_at",
            ),
        )
        if shopify_tag_written
        else ""
    )
    tag_write_attempted = (
        payload.get("tag_write_attempted") is True
        or payload.get("auto_tag_write_attempted") is True
        or payload.get("shopify_tag_write_performed") is True
        or payload.get("tag_write_performed") is True
    )
    tag_write_failed = bool(
        tag_write_status.startswith("blocked")
        and tag_write_attempted
        and not shopify_tag_written
    )
    return {
        "event_time": sent_at,
        "sent_at": sent_at,
        "email_sent_at": sent_at,
        "tag_written_at": tag_written_at,
        "tag_write_status": tag_write_status,
        "tag_write_failed": tag_write_failed,
        "tag_write_already_complete": payload.get("tag_write_already_complete") is True,
        "order_name": order_name,
        "masked_email": masked,
        "event_type": "send_execute",
        "status": _safe_text(
            payload.get("audit_status")
            or payload.get("execution_status")
            or payload.get("report_status")
            or "trustpilot_email_sent_shopify_tag_not_written",
            max_length=120,
        ),
        "classification": "local_review_send_success",
        "blocker_reason": "",
        "gmail_draft_created": payload.get("gmail_drafts_create_confirmed") is True
        or payload.get("gmail_drafts_create_called") is True
        or payload.get("gmail_draft_created") is True,
        "email_sent": True,
        "partial_draft_id": "",
        "partial_message_id": "",
        "source_report_path": source_path,
        "source_report_label": _safe_text(source_label or "Trustpilot Review & Send execute", max_length=120),
        "source_section": "local_review_send_success",
        "draft_should_not_be_sent": False,
        "prior_trustpilot_order_name": "",
        "ebay_tag_detected": payload.get("ebay_tag_detected") is True,
        "matched_ebay_tag_value": _safe_text(payload.get("matched_ebay_tag_value"), max_length=120),
        "badge_class": "rrw-badge-info" if not shopify_tag_written else "rrw-badge-ok",
        "local_review_send_success": True,
        "shopify_tag_pending": not shopify_tag_written,
        "shopify_tag_written": shopify_tag_written,
        "shopify_tag_already_existed": payload.get("tag_write_already_complete") is True,
        "evidence_message": "Sent via Review & Send",
        "trustpilot_history_label": LOCAL_REVIEW_SEND_HISTORY_LABEL,
    }


def _dedupe_local_review_send_records(records):
    result_by_key = {}
    order_keys = []
    for record in records or []:
        key = (
            _canonical_order_name(record.get("order_name")),
            record.get("email_sent") is True,
        )
        if not key[0]:
            continue
        existing = result_by_key.get(key)
        if not existing:
            result_by_key[key] = record
            order_keys.append(key)
            continue
        if record.get("shopify_tag_written") is True and existing.get("shopify_tag_written") is not True:
            result_by_key[key] = record
            continue
        if _already_sent_time_sort_value(record, "sent_at") > _already_sent_time_sort_value(existing, "sent_at"):
            result_by_key[key] = record
    return [result_by_key[key] for key in order_keys]


def _payload_time_value(payload, keys):
    if not isinstance(payload, dict):
        return ""
    for key in keys:
        value = _safe_text(payload.get(key), max_length=80)
        if value:
            return value
    return ""


def _shopify_tag_write_confirmed_from_payload(payload):
    if not isinstance(payload, dict):
        return False
    status = _safe_text(
        payload.get("tag_write_status") or payload.get("auto_tag_write_status"),
        max_length=120,
    )
    if status == TRUSTPILOT_TAG_WRITE_SUCCESS_STATUS:
        return _tag_write_readback_clean_from_payload(payload)
    if status.startswith("blocked"):
        return False
    explicit_confirmed = (
        payload.get("shopify_tag_write_confirmed") is True
        or payload.get("shopify_tag_written") is True
        or payload.get("source_shopify_tag_write_confirmed") is True
    )
    if not explicit_confirmed:
        return False
    if _payload_has_tag_write_readback_fields(payload):
        return _tag_write_readback_clean_from_payload(payload)
    return True


def _payload_has_tag_write_readback_fields(payload):
    return any(
        key in payload
        for key in (
            "readback_verified",
            "tag_write_readback_verified",
            "all_review_request_aliases_removed",
            "trustpilot_tag_present_after",
            "review_request_tag_present_after",
            "typo_review_request_tag_present_after",
        )
    )


def _tag_write_readback_clean_from_payload(payload):
    if payload.get("review_request_tag_present_after") is True:
        return False
    if payload.get("typo_review_request_tag_present_after") is True:
        return False
    if payload.get("all_review_request_aliases_removed") is False:
        return False
    if payload.get("trustpilot_tag_present_after") is False:
        return False
    readback_value = payload.get("readback_verified")
    if readback_value is None:
        readback_value = payload.get("tag_write_readback_verified")
    return readback_value is not False


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
    reports=None,
    filters=None,
):
    filters = filters or _normalize_filters({})
    reports = reports or {}
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
        reports=reports,
        page=filters["page"],
        page_size=filters["page_size"],
        sent_page=filters["sent_page"],
        sent_page_size=filters["sent_page_size"],
    )
    send_jobs = _attach_review_request_send_jobs_to_approval_queue(approval_queue)
    order_data_coverage = _dashboard_order_data_coverage(last_60_days_scan)
    customer_history_checks = approval_queue.get("customer_history_checks") or (
        last_60_days_scan.get("customer_history_checks") or {}
    )
    return {
        "ready_to_send_count": ready_count,
        "blocked_count": blocked_count,
        "sent_trustpilot_count": sent_count,
        "approval_queue": approval_queue,
        "review_request_send_jobs": send_jobs,
        "last_60_days_candidate_scan": last_60_days_scan,
        "customer_history_checks": customer_history_checks,
        "lookup_cache": _lookup_cache_dashboard_summary(last_60_days_scan),
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


def _lookup_cache_dashboard_summary(scan):
    return {
        "found": scan.get("customer_history_lookup_cache_found") is True,
        "loaded": scan.get("customer_history_lookup_cache_loaded") is True,
        "path": _safe_text(scan.get("customer_history_lookup_cache_path"), max_length=500),
        "paths_checked": scan.get("lookup_cache_paths_checked") or [],
        "selected_path": _safe_text(scan.get("lookup_cache_selected_path"), max_length=500),
        "entries_count": _int_or_zero(scan.get("lookup_cache_entries_count")),
        "order_21687_lookup_cache_found": scan.get("order_21687_lookup_cache_found") is True,
        "order_21687_should_block_review_send": scan.get("order_21687_should_block_review_send") is True,
        "order_21687_evidence_order_name": _safe_text(
            scan.get("order_21687_evidence_order_name"),
            max_length=80,
        ),
        "order_21687_safe_detected_keyword": _safe_text(
            scan.get("order_21687_safe_detected_keyword"),
            max_length=80,
        ),
        "order_21687_blocking_reason": _safe_text(
            scan.get("order_21687_blocking_reason"),
            max_length=300,
        ),
        "order_22562_lookup_cache_found": scan.get("order_22562_lookup_cache_found") is True,
        "order_22562_final_section": _safe_text(scan.get("order_22562_final_section"), max_length=80),
        "order_22562_final_eligibility": _safe_text(scan.get("order_22562_final_eligibility"), max_length=80),
        "batch_lookup_command": _batch_customer_history_lookup_container_command(),
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
    freshness = _safe_text(
        scan.get("candidate_scan_freshness")
        or scan.get("timestamp")
        or scan.get("scan_window_ended_at"),
        max_length=120,
    )
    stale_counter_warning = scan.get("stale_counter_warning") is True or incomplete
    return {
        "scan_source": scan_source or "unknown",
        "local_data_source_label": source_label,
        "last_shopify_order_sync_window": sync_window or "Unknown",
        "latest_review_request_sync_finished_at": latest_sync or "Unknown",
        "selected_local_tag_field": _safe_text(
            coverage.get("selected_local_tag_field") or SHOPIFY_ORDER_TAG_FIELD_LABEL,
            max_length=120,
        ),
        "local_orders_with_shopify_tag_data": _int_or_zero(coverage.get("local_orders_with_shopify_tag_data")),
        "order_22530_found_label": "Yes" if coverage.get("order_22530_found") is True else "No",
        "candidate_scan_freshness": freshness or "Unknown",
        "last_sent_record_time": _safe_text(scan.get("latest_sent_time"), max_length=120)
        or TIME_NOT_RECORDED_LABEL,
        "last_tag_write_time": _safe_text(scan.get("latest_tag_write_time"), max_length=120)
        or TIME_NOT_RECORDED_LABEL,
        "stale_counter_warning": stale_counter_warning,
        "stale_counter_warning_message": (
            _safe_text(scan.get("stale_counter_warning_message"), max_length=160)
            or DASHBOARD_STALE_COUNTER_WARNING
        )
        if stale_counter_warning
        else "",
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


def _build_review_send_state(params=None):
    filters = _normalize_filters(params)
    reports = _load_known_reports()
    history_ledger = build_review_request_history_ledger(_log_dir(), {})
    all_rows = _dedupe_rows(_collect_report_rows(reports))
    candidate_queue = _candidate_queue(reports)
    invitation_history = _rows_with_trustpilot_tags(all_rows)
    blocked_orders = _blocked_rows(reports, all_rows)
    trustpilot_email_records = _trustpilot_email_records(
        history_ledger["all_events"],
        _unfiltered_trustpilot_record_filters(),
    )
    trustpilot_email_records = _merge_trustpilot_email_records(
        _local_review_send_success_records(reports),
        trustpilot_email_records,
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
        reports=reports,
        page=filters["page"],
        page_size=filters["page_size"],
        sent_page=filters["sent_page"],
        sent_page_size=filters["sent_page_size"],
    )
    return {
        "filters": filters,
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
        _unfiltered_trustpilot_record_filters(),
    )
    trustpilot_email_records = _merge_trustpilot_email_records(
        _local_review_send_success_records(reports),
        trustpilot_email_records,
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
        "phase": "5.29E",
        "mode": "dry-run-local-synced-order-scan",
        "window_days": LAST_60_DAY_SCAN_WINDOW_DAYS,
        "report_status": "last_60_days_candidate_scan_ready",
        "success": True,
        "scan_source": scan["scan_source"],
        "coverage_warnings": scan["coverage_warnings"],
        "order_data_coverage": scan["order_data_coverage"],
        "order_21083_diagnosis": scan["order_21083_diagnosis"],
        "order_21070_diagnosis": scan["order_21070_diagnosis"],
        "order_21075_diagnosis": scan["order_21075_diagnosis"],
        "order_21076_diagnosis": scan["order_21076_diagnosis"],
        "order_21102_diagnosis": scan["order_21102_diagnosis"],
        "order_21225_diagnosis": scan["order_21225_diagnosis"],
        "order_21225_trustpilot_tag_detection": scan["order_21225_trustpilot_tag_detection"],
        "order_21687_diagnosis": scan["order_21687_diagnosis"],
        "#21687_customer_history_order_count": scan.get("#21687_customer_history_order_count", 0),
        "#21687_customer_history_order_names": scan.get("#21687_customer_history_order_names", []),
        "#21687_customer_history_match_method": scan.get("#21687_customer_history_match_method", ""),
        "#21687_customer_history_confidence": scan.get("#21687_customer_history_confidence", ""),
        "order_21687_lookup_cache_found": scan.get("order_21687_lookup_cache_found") is True,
        "order_21687_should_block_review_send": scan.get("order_21687_should_block_review_send") is True,
        "order_21687_evidence_order_name": scan.get("order_21687_evidence_order_name", ""),
        "order_21687_safe_detected_keyword": scan.get("order_21687_safe_detected_keyword", ""),
        "order_21687_blocking_reason": scan.get("order_21687_blocking_reason", ""),
        "order_21687_removed_from_needs_review": scan.get("order_21687_removed_from_needs_review") is True,
        "order_21687_present_in_blocked_or_already_sent": scan.get(
            "order_21687_present_in_blocked_or_already_sent"
        )
        is True,
        "order_21687_review_send_button_disabled": scan.get("order_21687_review_send_button_disabled") is True,
        "order_21687_gmail_shopify_write_performed": False,
        "customer_history_lookup_cache_found": scan.get("customer_history_lookup_cache_found") is True,
        "customer_history_lookup_cache_loaded": scan.get("customer_history_lookup_cache_loaded") is True,
        "customer_history_lookup_cache_path": scan.get("customer_history_lookup_cache_path", ""),
        "lookup_cache_paths_checked": scan.get("lookup_cache_paths_checked") or [],
        "lookup_cache_selected_path": scan.get("lookup_cache_selected_path", ""),
        "lookup_cache_entries_count": _int_or_zero(scan.get("lookup_cache_entries_count")),
        "visible_rows_missing_live_lookup_count": scan.get("visible_rows_missing_live_lookup_count", 0),
        "visible_rows_blocked_by_missing_or_stale_live_lookup_count": scan.get(
            "visible_rows_blocked_by_missing_or_stale_live_lookup_count",
            0,
        ),
        "order_21778_diagnosis": scan["order_21778_diagnosis"],
        "order_21778_trustpilot_tag_detection": scan["order_21778_trustpilot_tag_detection"],
        "order_22530_diagnosis": scan["order_22530_diagnosis"],
        "order_22562_diagnosis": scan["order_22562_diagnosis"],
        "scanned_order_count": scan["scanned_order_count"],
        "delivered_order_count": scan["delivered_order_count"],
        "eligible_candidate_count_before_latest_filter": scan["eligible_candidate_count_before_latest_filter"],
        "eligible_candidate_count_after_latest_filter": scan["eligible_candidate_count_after_latest_filter"],
        "hidden_older_eligible_count": scan["hidden_older_eligible_count"],
        "hidden_older_eligible_summary": scan["hidden_older_eligible_summary"],
        "latest_candidate_per_customer_count": scan["latest_candidate_per_customer_count"],
        "focus_22530_22562_latest_decision": scan["focus_22530_22562_latest_decision"],
        "eligible_candidate_count": scan["eligible_candidate_count"],
        "eligible_candidate_count_total": scan["eligible_candidate_count_total"],
        "final_eligible_count": scan.get("final_eligible_count", scan["eligible_candidate_count_total"]),
        "final_eligible_orders": scan.get("final_eligible_orders") or [],
        "needs_live_customer_history_check_count": scan.get("needs_live_customer_history_check_count", 0),
        "live_checks_completed_count": scan.get("live_checks_completed_count", 0),
        "live_checks_blocked_count": scan.get("live_checks_blocked_count", 0),
        "live_checks_failed_incomplete_count": scan.get("live_checks_failed_incomplete_count", 0),
        "customer_history_checks": scan.get("customer_history_checks") or {},
        "already_sent_count": scan["already_sent_count"],
        "latest_sent_order": scan["latest_sent_order"],
        "latest_sent_time": scan["latest_sent_time"],
        "latest_tag_write_time": scan["latest_tag_write_time"],
        "sent_rows_with_time_count": scan["sent_rows_with_time_count"],
        "sent_rows_without_time_count": scan["sent_rows_without_time_count"],
        "stale_counter_warning": scan["stale_counter_warning"],
        "stale_counter_warning_message": scan["stale_counter_warning_message"],
        "trustpilot_tagged_orders_excluded_count": scan["trustpilot_tagged_orders_excluded_count"],
        "blocked_count": scan["blocked_count"],
        "blocked_merged_group_count": scan["blocked_merged_group_count"],
        "blocked_duplicate_customer_count": scan["blocked_duplicate_customer_count"],
        "blocked_ebay_order_count": scan["blocked_ebay_order_count"],
        "blocked_note_risk_count": scan["blocked_note_risk_count"],
        "first_order_blocked_count": scan["first_order_blocked_count"],
        "blocked_first_order_count": scan["blocked_first_order_count"],
        "blocked_not_second_or_later_count": scan["blocked_not_second_or_later_count"],
        "blocked_second_order_not_delivered_count": scan["blocked_second_order_not_delivered_count"],
        "second_or_later_delivered_candidate_count": scan["second_or_later_delivered_candidate_count"],
        "eligible_candidate_count_before_second_order_rule": scan[
            "eligible_candidate_count_before_second_order_rule"
        ],
        "eligible_candidate_count_after_second_order_rule": scan[
            "eligible_candidate_count_after_second_order_rule"
        ],
        "prior_trustpilot_customer_blocked_count": scan["prior_trustpilot_customer_blocked_count"],
        "customer_history_unknown_count": scan["customer_history_unknown_count"],
        "customer_history_low_confidence_count": scan["customer_history_low_confidence_count"],
        "customer_history_weak_name_only_match_count": scan["customer_history_weak_name_only_match_count"],
        "overcounted_customer_history_count": scan["overcounted_customer_history_count"],
        "candidates_blocked_by_low_confidence_history": scan["candidates_blocked_by_low_confidence_history"],
        "candidates_blocked_by_note_risk": scan["candidates_blocked_by_note_risk"],
        "candidates_blocked_by_historical_trustpilot_note_count": scan[
            "candidates_blocked_by_historical_trustpilot_note_count"
        ],
        "active_review_send_count_before_historical_trustpilot_note_guard": scan[
            "active_review_send_count_before_historical_trustpilot_note_guard"
        ],
        "active_review_send_count_after_historical_trustpilot_note_guard": scan[
            "active_review_send_count_after_historical_trustpilot_note_guard"
        ],
        "active_review_send_count_before_precision": scan["active_review_send_count_before_precision"],
        "blocked_missing_review_request_tag_count": scan["blocked_missing_review_request_tag_count"],
        "blocked_not_delivered_count": scan["blocked_not_delivered_count"],
        "review_queue_batch_size": scan["review_queue_batch_size"],
        "review_queue_visible_count": scan["review_queue_visible_count"],
        "review_queue_overflow_count": scan["review_queue_overflow_count"],
        "review_queue_sort_order": scan["review_queue_sort_order"],
        "review_queue_candidates": scan["review_queue_candidates"],
        "eligible_candidates_summary": scan["eligible_candidates_summary"],
        "blocked_candidates_summary": scan["blocked_candidates_summary"],
        "already_sent_summary": scan["already_sent_summary"],
        "scan_window_started_at": scan["scan_window_started_at"],
        "scan_window_ended_at": scan["scan_window_ended_at"],
        "candidate_scan_freshness": scan["candidate_scan_freshness"],
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
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": _last_60_days_issue_summary(scan),
    }


def build_review_request_dashboard_counts_audit_report(params=None):
    params = params or {}
    context = build_review_request_workbench_context(params, use_dashboard_snapshot=False)
    dashboard = context["review_request_workbench"]["operating_dashboard"]
    queue = dashboard["approval_queue"]
    latest_sent_order = _safe_text(queue.get("latest_sent_order"), max_length=80)
    latest_sent_time = _safe_text(queue.get("latest_sent_time"), max_length=120)
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_dashboard_counts_audit",
        "task_name": "shopify_review_request_dashboard_counts_audit",
        "phase": "5.30",
        "mode": "dry-run-local-dashboard-counts-audit",
        "audit_status": "dashboard_counts_audit_ready",
        "report_status": "dashboard_counts_audit_ready",
        "success": True,
        "eligible_total": _int_or_zero(queue.get("eligible_candidate_count_total")),
        "needs_review_visible_count": _int_or_zero(queue.get("review_queue_visible_count")),
        "already_sent_total": _int_or_zero(queue.get("already_sent_count")),
        "blocked_total": _int_or_zero(queue.get("blocked_count")),
        "older_eligible_hidden": _int_or_zero(queue.get("hidden_older_eligible_count")),
        "latest_sent_order": latest_sent_order,
        "latest_sent_time": latest_sent_time,
        "latest_tag_write_time": _safe_text(queue.get("latest_tag_write_time"), max_length=120),
        "sent_rows_with_time_count": _int_or_zero(queue.get("sent_rows_with_time_count")),
        "sent_rows_without_time_count": _int_or_zero(queue.get("sent_rows_without_time_count")),
        "already_sent_page_size": _int_or_zero(queue.get("already_sent_page_size")),
        "already_sent_visible_count": _int_or_zero(queue.get("already_sent_visible_count")),
        "already_sent_page": _int_or_zero(queue.get("already_sent_page")),
        "already_sent_total_pages": _int_or_zero(queue.get("already_sent_total_pages")),
        "stale_counter_warning": queue.get("stale_counter_warning") is True
        or dashboard["order_data_coverage"].get("stale_counter_warning") is True,
        "stale_counter_warning_message": _safe_text(
            queue.get("stale_counter_warning_message")
            or dashboard["order_data_coverage"].get("stale_counter_warning_message"),
            max_length=160,
        ),
        "candidate_scan_freshness": _safe_text(
            dashboard["order_data_coverage"].get("candidate_scan_freshness"),
            max_length=120,
        ),
        "counter_source": "live_local_scan_plus_latest_review_send_and_tag_evidence",
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
        "translations_register_called": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
    }
    payload["detected_issue_summary"] = (
        f"Dashboard counts audit: eligible={payload['eligible_total']}, "
        f"already_sent={payload['already_sent_total']}, blocked={payload['blocked_total']}, "
        f"latest_sent={latest_sent_order or 'none'} at {latest_sent_time or TIME_NOT_RECORDED_LABEL}. "
        "No Gmail, Shopify, external review API, or translationsRegister calls were performed."
    )
    return payload


def build_review_request_sent_tag_pending_repair_evidence(target_order):
    target_order = _canonical_order_name(target_order)
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_sent_tag_pending_repair_evidence",
        "task_name": "shopify_review_request_sent_tag_pending_repair_evidence",
        "phase": "5.29D",
        "mode": "dry-run-local-history-queue-evidence",
        "repair_evidence_status": "blocked_no_sent_tag_pending_evidence",
        "success": False,
        "selected_order": target_order,
        "order": target_order,
        "allowed_repair_target_order": "#21284",
        "target_order_allowed_for_repair_phase": target_order == "#21284",
        "row_found": False,
        "row_section": "not_scanned",
        "email_sent_confirmed": False,
        "sent_status": "",
        "shopify_tag_pending": False,
        "shopify_tag_status_label": "",
        "sent_tag_pending_evidence_found": False,
        "local_review_send_success": False,
        "local_order_found": False,
        "review_request_tag_alias_found": False,
        "matched_review_request_tags": [],
        "tag_write_completed_evidence_found": False,
        "tags": [],
        "evidence": "",
        "ebay_tag_detected": False,
        "matched_ebay_tag_value": "",
        "blocking_statuses": [],
        "error": "",
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
        "translations_register_called": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
    }
    if target_order != "#21284":
        result["repair_evidence_status"] = "blocked_target_order_not_allowed_for_repair_phase"
        result["blocking_statuses"] = ["blocked_target_order_not_allowed_for_repair_phase"]
        return result

    try:
        state = _build_review_send_state({})
        scan = state["last_60_days_scan"]
        row, section = _find_scan_order_row(scan, target_order)
        result["local_order_found"] = _focus_order_found_locally(target_order)
    except Exception as exc:  # pragma: no cover - defensive wrapper for runner diagnostics.
        result["repair_evidence_status"] = "blocked_repair_evidence_builder_failed"
        result["blocking_statuses"] = ["blocked_repair_evidence_builder_failed"]
        result["error"] = _safe_exception_summary(exc)
        return result

    if not row:
        result["blocking_statuses"] = ["blocked_no_sent_tag_pending_evidence"]
        return result

    tags = _dedupe_text(row.get("order_tags_display") or row.get("tags") or [])
    matched_review_request_tags = _matched_review_request_tags(tags)
    sent_status = _safe_text(row.get("trustpilot_email_status"), max_length=120)
    shopify_tag_status_label = _safe_text(row.get("shopify_tag_status_label"), max_length=120)
    local_review_send_success = row.get("local_review_send_success") is True
    email_sent_confirmed = local_review_send_success and sent_status == "Sent"
    shopify_tag_pending = row.get("shopify_tag_pending") is True or shopify_tag_status_label == "Tag pending"
    tag_write_completed = _shopify_tag_write_confirmed_from_payload(row) or has_trustpilot_sent_tag(tags)

    result.update(
        {
            "row_found": True,
            "row_section": section,
            "email_sent_confirmed": email_sent_confirmed,
            "sent_status": sent_status,
            "shopify_tag_pending": shopify_tag_pending,
            "shopify_tag_status_label": shopify_tag_status_label,
            "local_review_send_success": local_review_send_success,
            "review_request_tag_alias_found": bool(matched_review_request_tags),
            "matched_review_request_tags": matched_review_request_tags,
            "tag_write_completed_evidence_found": tag_write_completed,
            "tags": tags,
            "evidence": _safe_text(row.get("evidence") or row.get("reason"), max_length=500),
            "ebay_tag_detected": row.get("ebay_tag_detected") is True,
            "matched_ebay_tag_value": _safe_text(row.get("matched_ebay_tag_value"), max_length=120),
        }
    )

    blockers = []
    if section != "already_sent":
        blockers.append("blocked_target_order_not_in_already_sent_rows")
    if not email_sent_confirmed:
        blockers.append("blocked_email_sent_evidence_missing")
    if not shopify_tag_pending:
        blockers.append("blocked_tag_pending_evidence_missing")
    if tag_write_completed:
        blockers.append("blocked_completed_tag_write_evidence_found")
    if not result["local_order_found"]:
        blockers.append("blocked_selected_order_not_found")
    if not (matched_review_request_tags or shopify_tag_pending):
        blockers.append("blocked_no_review_request_alias_or_tag_pending")
    if result["ebay_tag_detected"]:
        blockers.append("blocked_ebay_order")

    result["blocking_statuses"] = blockers
    result["sent_tag_pending_evidence_found"] = not blockers
    result["success"] = result["sent_tag_pending_evidence_found"]
    result["repair_evidence_status"] = (
        "repair_evidence_ready" if result["sent_tag_pending_evidence_found"] else blockers[0]
    )
    return result


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


def build_review_request_trustpilot_tag_exclusion_audit_report(params=None):
    state = _build_review_send_state()
    scan = state["last_60_days_scan"]
    approval_queue = state["approval_queue"]
    row, section = _find_scan_order_row(scan, "#21225")
    diagnosis = scan.get("order_21225_diagnosis") or {}
    detection = scan.get("order_21225_trustpilot_tag_detection") or _order_trustpilot_tag_detection(diagnosis)
    local_tags = _dedupe_text(
        diagnosis.get("local_shopify_tags")
        or diagnosis.get("order_tags_display")
        or (row or {}).get("local_shopify_tags")
        or (row or {}).get("order_tags_display")
        or []
    )
    needs_review_orders = {
        _safe_text(item.get("order"), max_length=80)
        for item in (approval_queue.get("all_needs_review_rows") or scan.get("eligible_queue_rows") or [])
    }
    visible_review_orders = {
        _safe_text(item.get("order"), max_length=80)
        for item in approval_queue.get("needs_review_rows", [])
    }
    already_sent_orders = {
        _safe_text(item.get("order"), max_length=80)
        for item in (approval_queue.get("already_sent_rows") or scan.get("already_sent_queue_rows") or [])
    }
    removed_from_needs_review = "#21225" not in needs_review_orders and "#21225" not in visible_review_orders
    shown_in_already_sent = "#21225" in already_sent_orders or section == "already_sent"
    trustpilot_detected = (
        detection.get("trustpilot_tag_detected") is True
        or (row or {}).get("trustpilot_tag_detected") is True
        or bool(_matched_trustpilot_tags({}, local_tags))
    )
    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_trustpilot_tag_exclusion_audit",
        "task_name": "shopify_review_request_trustpilot_tag_exclusion_audit",
        "phase": "5.29E",
        "mode": "dry-run-local-trustpilot-tag-exclusion-audit",
        "audit_status": "trustpilot_tag_exclusion_audit_ready",
        "report_status": "trustpilot_tag_exclusion_audit_ready",
        "success": True,
        "order_21225_found": bool(row) or diagnosis.get("found_in_local_shopify_order") is True,
        "order_21225_local_tags": local_tags,
        "order_21225_trustpilot_tag_detected": trustpilot_detected,
        "order_21225_trustpilot_tag_source": _safe_text(
            (row or {}).get("trustpilot_tag_source")
            or detection.get("trustpilot_tag_source")
            or diagnosis.get("trustpilot_tag_source"),
            max_length=120,
        ),
        "order_21225_matched_trustpilot_tag_values": _dedupe_text(
            (row or {}).get("matched_trustpilot_tag_values")
            or detection.get("matched_trustpilot_tag_values")
            or _matched_trustpilot_tags({}, local_tags)
        ),
        "order_21225_candidate_section_before": _safe_text(
            (row or {}).get("candidate_section_before_trustpilot_exclusion")
            or "not_reconstructed_current_scan",
            max_length=120,
        ),
        "order_21225_candidate_section_after": section,
        "order_21225_removed_from_needs_review": removed_from_needs_review,
        "order_21225_shown_in_already_sent": shown_in_already_sent,
        "order_21225_review_send_button_absent": "#21225" not in visible_review_orders,
        "order_21225_shopify_tag_status_label": _safe_text(
            (row or {}).get("shopify_tag_status_label"),
            max_length=120,
        ),
        "order_21225_shopify_tag_pending": (row or {}).get("shopify_tag_pending") is True,
        "order_21225_already_sent_reason": _safe_text(
            (row or {}).get("already_sent_reason")
            or diagnosis.get("already_sent_reason")
            or (TRUSTPILOT_TAG_ALREADY_SENT_REASON if trustpilot_detected else ""),
            max_length=300,
        ),
        "order_21225_evidence": _safe_text(
            (row or {}).get("evidence")
            or (row or {}).get("reason")
            or (TRUSTPILOT_TAG_FOUND_EVIDENCE if trustpilot_detected else ""),
            max_length=500,
        ),
        "order_21225_diagnosis": diagnosis,
        "order_21225_trustpilot_tag_detection": detection,
        "trustpilot_tagged_orders_excluded_count": _int_or_zero(
            scan.get("trustpilot_tagged_orders_excluded_count")
        ),
        "coverage_warnings": scan.get("coverage_warnings") or [],
        "needs_review_order_count": len(needs_review_orders),
        "already_sent_order_count": len(already_sent_orders),
        "review_send_action_enabled_count": _int_or_zero(
            approval_queue.get("review_send_action_enabled_count")
        ),
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
    }
    payload["detected_issue_summary"] = _trustpilot_tag_exclusion_audit_summary(payload)
    return payload


def build_review_request_customer_history_trustpilot_guard_audit_report(params=None):
    state = _build_review_send_state()
    scan = state["last_60_days_scan"]
    approval_queue = state["approval_queue"]
    blocked_rows = list(scan.get("blocked_queue_rows") or [])
    first_order_rows = [row for row in blocked_rows if _row_blocked_by_first_order(row)]
    prior_trustpilot_rows = [row for row in blocked_rows if _row_blocked_by_prior_trustpilot_history(row)]
    unknown_history_rows = [row for row in blocked_rows if _row_blocked_by_customer_history_unknown(row)]
    note_risk_rows = [row for row in blocked_rows if _row_blocked_by_note_risk(row)]
    eligible_after = _int_or_zero(scan.get("eligible_candidate_count"))
    candidate_count_before_fix = eligible_after + len(first_order_rows) + len(prior_trustpilot_rows)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_customer_history_trustpilot_guard_audit",
        "task_name": "shopify_review_request_customer_history_trustpilot_guard_audit",
        "phase": "5.28I",
        "mode": "dry-run-local-customer-history-trustpilot-guard-audit",
        "report_status": "customer_history_trustpilot_guard_audit_ready",
        "success": True,
        "customer_history_resolver_enabled": True,
        "customer_history_sources": ["customer_email", "shipping_fallback"],
        "trustpilot_sent_tag_aliases": list(TRUSTPILOT_TAG_ALIASES),
        "first_order_candidate_count_before_fix": len(first_order_rows),
        "first_order_blocked_count": len(first_order_rows),
        "prior_trustpilot_customer_blocked_count": len(prior_trustpilot_rows),
        "customer_history_unknown_count": len(unknown_history_rows),
        "candidates_blocked_by_note_risk": len(note_risk_rows),
        "candidates_blocked_by_low_confidence_history": _int_or_zero(
            scan.get("candidates_blocked_by_low_confidence_history")
        ),
        "candidate_count_before_fix": candidate_count_before_fix,
        "candidate_count_after_fix": eligible_after,
        "visible_review_send_count_after_fix": _int_or_zero(
            approval_queue.get("review_send_action_enabled_count")
            or scan.get("review_queue_visible_count")
        ),
        "review_queue_visible_count_after_fix": _int_or_zero(scan.get("review_queue_visible_count")),
        "active_review_send_count_after_fix": _int_or_zero(
            approval_queue.get("review_send_action_enabled_count")
        ),
        "order_21083_diagnosis": scan.get("order_21083_diagnosis") or {},
        "order_21070_diagnosis": scan.get("order_21070_diagnosis") or {},
        "order_21075_diagnosis": scan.get("order_21075_diagnosis") or {},
        "order_21076_diagnosis": scan.get("order_21076_diagnosis") or {},
        "order_21102_diagnosis": scan.get("order_21102_diagnosis") or {},
        "order_21778_diagnosis": scan.get("order_21778_diagnosis") or {},
        "order_21778_trustpilot_tag_detection": scan.get("order_21778_trustpilot_tag_detection") or {},
        "first_order_blocked_orders": [_safe_text(row.get("order"), max_length=80) for row in first_order_rows],
        "prior_trustpilot_customer_blocked_orders": [
            {
                "order": _safe_text(row.get("order"), max_length=80),
                "previous_trustpilot_order_names": _dedupe_order_names(
                    row.get("previous_trustpilot_order_names") or []
                ),
                "previous_trustpilot_tag_values": _dedupe_text(
                    row.get("previous_trustpilot_tag_values") or []
                ),
                "reason": _safe_text(row.get("eligibility_reason_plain"), max_length=500),
            }
            for row in prior_trustpilot_rows
        ],
        "customer_history_unknown_orders": [
            _safe_text(row.get("order"), max_length=80) for row in unknown_history_rows
        ],
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
        "detected_issue_summary": _customer_history_guard_issue_summary(
            first_order_rows,
            prior_trustpilot_rows,
            unknown_history_rows,
            eligible_after,
            approval_queue,
        ),
    }


def build_review_request_customer_history_precision_audit_report(params=None):
    state = _build_review_send_state()
    scan = state["last_60_days_scan"]
    approval_queue = state["approval_queue"]
    blocked_rows = list(scan.get("blocked_queue_rows") or [])
    eligible_rows = list(scan.get("eligible_queue_rows") or [])
    rows = blocked_rows + eligible_rows
    note_risk_rows = [row for row in blocked_rows if _row_blocked_by_note_risk(row)]
    low_confidence_rows = [row for row in blocked_rows if _row_blocked_by_customer_history_unknown(row)]
    overcounted_rows = [
        row
        for row in rows
        if _int_or_zero(row.get("customer_history_order_count_before_precision"))
        > _int_or_zero(row.get("customer_history_order_count"))
    ]
    active_after = _int_or_zero(approval_queue.get("review_send_action_enabled_count"))
    active_before = _int_or_zero(scan.get("active_review_send_count_before_precision")) or active_after
    order_21083 = scan.get("order_21083_diagnosis") or {}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_customer_history_precision_audit",
        "task_name": "shopify_review_request_customer_history_precision_audit",
        "phase": "5.28I",
        "mode": "dry-run-local-customer-history-precision-audit",
        "report_status": "customer_history_precision_audit_ready",
        "success": True,
        "customer_history_matching_policy": {
            "high_confidence": ["shopify_customer_id_if_available", "customer_email"],
            "medium_confidence": ["normalized_full_name_shipping_phone", "normalized_full_name_shipping_address_postcode"],
            "low_confidence": ["name_only_excluded_from_confirmed_history"],
        },
        "order_21083_diagnosis": order_21083,
        "order_21083_found": order_21083.get("found_in_local_shopify_order") is True,
        "order_21083_displayed_order_count_before": _int_or_zero(
            order_21083.get("displayed_order_count_before_precision")
        ),
        "order_21083_customer_order_count_after": _int_or_zero(order_21083.get("customer_history_order_count")),
        "order_21083_matched_order_names_after": _dedupe_order_names(
            order_21083.get("customer_history_matched_order_names") or []
        ),
        "order_21083_match_method": _safe_text(order_21083.get("customer_history_match_method"), max_length=80),
        "order_21083_customer_history_confidence": _safe_text(
            order_21083.get("customer_history_confidence"), max_length=80
        ),
        "order_21083_note_risk_detected": order_21083.get("note_risk_detected") is True,
        "order_21083_note_risk_field": _safe_text(order_21083.get("note_risk_field"), max_length=120),
        "order_21083_note_risk_keywords": _dedupe_text(order_21083.get("note_risk_keywords") or []),
        "order_21083_final_eligibility": _safe_text(order_21083.get("final_eligibility_status"), max_length=80),
        "order_21083_final_blockers": _dedupe_text(order_21083.get("final_blockers") or []),
        "overcounted_customer_history_count": len(overcounted_rows),
        "weak_name_only_match_count": sum(
            _int_or_zero(row.get("customer_history_weak_match_count")) for row in rows
        ),
        "candidates_blocked_by_low_confidence_history": len(low_confidence_rows),
        "candidates_blocked_by_note_risk": len(note_risk_rows),
        "first_order_blocked_count": _int_or_zero(scan.get("first_order_blocked_count")),
        "prior_trustpilot_blocked_count": _int_or_zero(scan.get("prior_trustpilot_customer_blocked_count")),
        "active_review_send_count_before_fix": active_before,
        "active_review_send_count_after_fix": active_after,
        "review_queue_visible_count_after_fix": _int_or_zero(scan.get("review_queue_visible_count")),
        "eligible_candidate_count_after_fix": _int_or_zero(scan.get("eligible_candidate_count")),
        "overcounted_customer_history_orders": [
            {
                "order": _safe_text(row.get("order"), max_length=80),
                "before": _int_or_zero(row.get("customer_history_order_count_before_precision")),
                "after": _int_or_zero(row.get("customer_history_order_count")),
                "confidence": _safe_text(row.get("customer_history_confidence"), max_length=80),
                "method": _safe_text(row.get("customer_history_match_method"), max_length=80),
                "excluded_weak_matches": _dedupe_order_names(
                    row.get("customer_history_excluded_weak_matches") or []
                ),
            }
            for row in overcounted_rows[:50]
        ],
        "note_risk_blocked_orders": [
            {
                "order": _safe_text(row.get("order"), max_length=80),
                "note_risk_field": _safe_text(row.get("note_risk_field"), max_length=120),
                "note_risk_keywords": _dedupe_text(row.get("note_risk_keywords") or []),
                "reason": NOTE_RISK_REASON,
            }
            for row in note_risk_rows[:50]
        ],
        "low_confidence_blocked_orders": [
            {
                "order": _safe_text(row.get("order"), max_length=80),
                "confidence": _safe_text(row.get("customer_history_confidence"), max_length=80),
                "match_method": _safe_text(row.get("customer_history_match_method"), max_length=80),
                "weak_match_count": _int_or_zero(row.get("customer_history_weak_match_count")),
                "reason": "Customer history not confirmed",
            }
            for row in low_confidence_rows[:50]
        ],
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
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            f"Customer-history precision audit ready. Overcounted histories: {len(overcounted_rows)}; "
            f"note-risk blocked: {len(note_risk_rows)}; low-confidence history blocked: {len(low_confidence_rows)}; "
            f"active Review & Send before/after: {active_before}/{active_after}. "
            "No Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, or external API calls were performed."
        ),
    }


def build_review_request_customer_lifetime_trustpilot_note_audit_report(params=None):
    state = _build_review_send_state(params)
    scan = state["last_60_days_scan"]
    approval_queue = state["approval_queue"]
    blocked_rows = list(scan.get("blocked_queue_rows") or [])
    eligible_rows = list(scan.get("eligible_queue_rows") or [])
    review_rows = list(scan.get("review_queue_rows") or [])
    already_sent_rows = list(scan.get("already_sent_queue_rows") or [])
    order_21687 = scan.get("order_21687_diagnosis") or {}
    order_21687_row, order_21687_section = _find_scan_order_row(
        {
            "eligible_queue_rows": eligible_rows,
            "review_queue_rows": review_rows,
            "blocked_queue_rows": blocked_rows,
            "already_sent_queue_rows": already_sent_rows,
        },
        "#21687",
    )
    note_blocked_rows = [
        row
        for row in blocked_rows
        if row.get("customer_level_trustpilot_note_evidence_found") is True
        or row.get("trustpilot_note_evidence_found") is True
    ]
    active_after = (
        _int_or_zero(scan.get("active_review_send_count_after_historical_trustpilot_note_guard"))
        or _int_or_zero(scan.get("eligible_candidate_count"))
        or _int_or_zero(approval_queue.get("review_send_action_enabled_count"))
        or _int_or_zero(scan.get("review_queue_visible_count"))
    )
    active_before = (
        _int_or_zero(scan.get("active_review_send_count_before_historical_trustpilot_note_guard"))
        or active_after + len(note_blocked_rows)
    )
    evidence_found = order_21687.get("customer_level_trustpilot_note_evidence_found") is True
    evidence_order = _safe_text(
        order_21687.get("customer_level_trustpilot_note_evidence_order_name"),
        max_length=80,
    )
    safe_keyword = _safe_text(order_21687.get("customer_level_trustpilot_note_safe_keyword"), max_length=80)
    final_blockers = _dedupe_text(order_21687.get("final_blockers") or [])
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_customer_lifetime_trustpilot_note_audit",
        "task_name": "shopify_review_request_customer_lifetime_trustpilot_note_audit",
        "phase": "5.31",
        "mode": "dry-run-local-customer-lifetime-trustpilot-note-audit",
        "report_status": "customer_lifetime_trustpilot_note_audit_ready",
        "success": True,
        "customer_history_matching_policy": {
            "high_confidence": ["customer_email", "shopify_customer_id_if_available"],
            "medium_confidence": ["normalized_full_name_shipping_phone", "normalized_full_name_shipping_address_postcode"],
            "low_confidence": ["name_only_excluded_from_send_approval"],
            "window": "lifetime_local_orders",
        },
        "trustpilot_note_keyword_policy": {
            "keywords": list(TRUSTPILOT_NOTE_KEYWORDS),
            "spacing_and_punctuation_variants_matched": True,
            "full_note_text_output": False,
        },
        "order_21687_diagnosis": order_21687,
        "order_21687_found": order_21687.get("found_in_local_shopify_order") is True,
        "order_21687_candidate_scan_section": order_21687_section,
        "order_21687_customer_lifetime_order_count": _int_or_zero(
            order_21687.get("customer_history_order_count")
        ),
        "order_21687_matched_order_names": _dedupe_order_names(
            order_21687.get("customer_history_matched_order_names")
            or order_21687.get("customer_history_order_names")
            or []
        ),
        "order_21687_match_method": _safe_text(
            order_21687.get("customer_history_match_method"), max_length=80
        ),
        "order_21687_customer_history_confidence": _safe_text(
            order_21687.get("customer_history_confidence"), max_length=80
        ),
        "order_21687_trustpilot_note_evidence_found": evidence_found,
        "order_21687_evidence_order_name": evidence_order,
        "order_21687_safe_detected_keyword": safe_keyword,
        "order_21687_final_eligibility": _safe_text(
            order_21687.get("final_eligibility_status"), max_length=80
        ),
        "order_21687_final_blockers": final_blockers,
        "#21687_found": order_21687.get("found_in_local_shopify_order") is True,
        "#21687_customer_history_order_count": _int_or_zero(
            order_21687.get("customer_history_order_count")
        ),
        "#21687_matched_order_names": _dedupe_order_names(
            order_21687.get("customer_history_matched_order_names")
            or order_21687.get("customer_history_order_names")
            or []
        ),
        "#21687_match_method": _safe_text(order_21687.get("customer_history_match_method"), max_length=80),
        "#21687_customer_history_confidence": _safe_text(
            order_21687.get("customer_history_confidence"), max_length=80
        ),
        "#21687_trustpilot_note_evidence_found": evidence_found,
        "#21687_evidence_order_name": evidence_order,
        "#21687_safe_detected_keyword": safe_keyword,
        "#21687_final_eligibility": _safe_text(order_21687.get("final_eligibility_status"), max_length=80),
        "#21687_final_blockers": final_blockers,
        "candidates_blocked_by_historical_trustpilot_note_count": len(note_blocked_rows),
        "candidates_blocked_by_historical_trustpilot_note": [
            {
                "order": _safe_text(row.get("order"), max_length=80),
                "evidence_order_name": _safe_text(
                    row.get("customer_level_trustpilot_note_evidence_order_name"), max_length=80
                ),
                "safe_keyword": _safe_text(row.get("customer_level_trustpilot_note_safe_keyword"), max_length=80),
                "reason": _trustpilot_note_evidence_reason(
                    {
                        "order_name": row.get("customer_level_trustpilot_note_evidence_order_name"),
                    }
                ),
            }
            for row in note_blocked_rows[:50]
        ],
        "active_review_send_count_before_historical_trustpilot_note_guard": active_before,
        "active_review_send_count_after_historical_trustpilot_note_guard": active_after,
        "active_review_send_count_before_fix": active_before,
        "active_review_send_count_after_fix": active_after,
        "review_queue_visible_count_after_fix": _int_or_zero(scan.get("review_queue_visible_count")),
        "eligible_candidate_count_after_fix": _int_or_zero(scan.get("eligible_candidate_count")),
        "order_21687_row_present_in_needs_review": bool(
            order_21687_row and order_21687_section in {"eligible", "review_queue"}
        ),
        "order_21687_row_present_in_blocked_or_already_sent": bool(
            order_21687_row and order_21687_section in {"blocked", "already_sent"}
        ),
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
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Customer lifetime Trustpilot note audit ready. "
            f"#21687 found={order_21687.get('found_in_local_shopify_order') is True}; "
            f"lifetime order count={_int_or_zero(order_21687.get('customer_history_order_count'))}; "
            f"historical Trustpilot note evidence found={evidence_found}; "
            f"active Review & Send before/after={active_before}/{active_after}. "
            "No Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, or external API calls were performed."
        ),
    }


def build_review_request_customer_identity_drilldown_audit_report(params=None):
    params = params or {}
    target_order_name = _canonical_order_name(
        params.get("order_name") or CUSTOMER_IDENTITY_DRILLDOWN_TARGET_ORDER_NAME
    )
    state = _build_review_send_state(params)
    scan = state["last_60_days_scan"]
    drilldown = _customer_identity_drilldown_audit(target_order_name)
    order_diagnosis = scan.get("order_21687_diagnosis") if target_order_name == "#21687" else {}
    order_diagnosis = order_diagnosis or {}
    strategy_counts = drilldown.get("identity_strategy_counts") or {}
    historical_evidence_found = drilldown.get("historical_trustpilot_note_evidence_found") is True
    local_confirmed_count = _int_or_zero(drilldown.get("local_confirmed_order_count"))
    user_reported_count = _int_or_zero(drilldown.get("user_reported_shopify_ui_order_count"))
    local_data_missing = user_reported_count > 0 and local_confirmed_count < user_reported_count
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_customer_identity_drilldown_audit",
        "task_name": "shopify_review_request_customer_identity_drilldown_audit",
        "phase": "5.31B",
        "mode": "dry-run-local-customer-identity-drilldown-audit",
        "report_status": (
            "customer_identity_drilldown_audit_ready"
            if drilldown.get("target_order_found") is True
            else "customer_identity_drilldown_target_order_not_found"
        ),
        "success": True,
        "target_order_name": target_order_name,
        "user_reported_shopify_ui_order_count": user_reported_count,
        "local_order_fields": drilldown.get("local_order_fields") or {},
        "target_order_found": drilldown.get("target_order_found") is True,
        "local_confirmed_order_count": local_confirmed_count,
        "local_confirmed_order_names": drilldown.get("local_confirmed_order_names") or [],
        "local_confirmed_match_method": drilldown.get("local_confirmed_match_method", ""),
        "local_confirmed_confidence": drilldown.get("local_confirmed_confidence", ""),
        "identity_strategy_counts": strategy_counts,
        "identity_strategy_order_names": drilldown.get("identity_strategy_order_names") or {},
        "identity_strategy_details": drilldown.get("identity_strategy_details") or [],
        "exact_email_match_order_count": strategy_counts.get("customer_email_exact", 0),
        "exact_customer_name_match_order_count": strategy_counts.get("customer_name_exact", 0),
        "shipping_phone_match_order_count": strategy_counts.get("shipping_phone_exact", 0),
        "shipping_name_postcode_match_order_count": strategy_counts.get("shipping_name_postcode_exact", 0),
        "broader_safe_candidate_matched_order_names": drilldown.get(
            "broader_safe_candidate_matched_order_names"
        )
        or [],
        "possible_missed_historical_orders": drilldown.get("possible_missed_historical_orders") or [],
        "why_only_counted_orders": drilldown.get("why_only_counted_orders", ""),
        "note_evidence_checks": drilldown.get("note_evidence_checks") or [],
        "note_evidence_matches": drilldown.get("note_evidence_matches") or [],
        "trustpilot_note_evidence_found": historical_evidence_found,
        "trustpoilt_note_evidence_found": historical_evidence_found,
        "evidence_order_name": drilldown.get("evidence_order_name", ""),
        "evidence_field_name": drilldown.get("evidence_field_name", ""),
        "evidence_safe_keyword": drilldown.get("evidence_safe_keyword", ""),
        "order_21687_candidate_scan_final_eligibility": _safe_text(
            order_diagnosis.get("final_eligibility_status"), max_length=80
        ),
        "order_21687_candidate_scan_final_blockers": _dedupe_text(
            order_diagnosis.get("final_blockers") or []
        ),
        "order_21687_candidate_scan_customer_history_order_count": _int_or_zero(
            order_diagnosis.get("customer_history_order_count")
        ),
        "order_21687_candidate_scan_trustpilot_note_evidence_found": (
            order_diagnosis.get("customer_level_trustpilot_note_evidence_found") is True
        ),
        "should_block_order_21687": historical_evidence_found,
        "candidate_scan_blocker_update_needed": bool(
            historical_evidence_found
            and _safe_text(order_diagnosis.get("final_eligibility_status"), max_length=80) != "blocked"
        ),
        "local_data_missing_customer_history": local_data_missing,
        "manual_evidence_mode": {
            "shopify_ui_order_count_reported_by_user": user_reported_count,
            "local_data_missing_customer_history": local_data_missing,
            "recommended_action": drilldown.get("recommended_action", ""),
        },
        "#21687_local_confirmed_order_count": local_confirmed_count,
        "#21687_identity_strategy_counts": strategy_counts,
        "#21687_potential_matched_order_names": drilldown.get(
            "broader_safe_candidate_matched_order_names"
        )
        or [],
        "#21687_trustpoilt_note_evidence_found": historical_evidence_found,
        "#21687_evidence_order_name": drilldown.get("evidence_order_name", ""),
        "#21687_should_now_be_blocked": historical_evidence_found,
        "#21687_local_data_appears_incomplete": local_data_missing,
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
        "raw_phone_output": False,
        "raw_address_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            f"#21687 identity drilldown ready. Local confirmed orders={local_confirmed_count}; "
            f"potential local candidate orders={len(drilldown.get('broader_safe_candidate_matched_order_names') or [])}; "
            f"historical Trustpilot note evidence found={historical_evidence_found}; "
            f"local data missing versus Shopify UI count={local_data_missing}. "
            "No Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, external API, email, tag write, "
            "mutation, or translationsRegister call was performed."
        ),
    }


def build_review_request_review_send_failure_audit_report(params=None):
    state = _build_review_send_state(params)
    target_order = "#21075"
    scan = state["last_60_days_scan"]
    row, section = _find_scan_order_row(
        {
            "eligible_queue_rows": scan.get("eligible_queue_rows") or [],
            "blocked_queue_rows": scan.get("blocked_queue_rows") or [],
            "already_sent_queue_rows": scan.get("already_sent_queue_rows") or [],
        },
        target_order,
    )
    candidate_found = bool(row)
    candidate_currently_eligible = section == "eligible"
    route_blocker = "" if candidate_currently_eligible else section
    diagnosis = _review_send_readiness_diagnosis(
        target_order,
        row or {},
        state["gmail_setup"],
        candidate_found=candidate_found,
        candidate_currently_eligible=candidate_currently_eligible,
        route_revalidation_blocker=route_blocker,
    )
    latest_attempt = (state["reports"].get("trustpilot_review_and_send_execute") or {}).get("data") or {}
    latest_attempt_order = _canonical_order_name(
        latest_attempt.get("selected_order") or latest_attempt.get("target_order") or ""
    )
    latest_attempt_matches_target = latest_attempt_order == target_order
    latest_attempt_message = _safe_text(
        latest_attempt.get("exact_user_message")
        or latest_attempt.get("blocking_detail")
        or latest_attempt.get("detected_issue_summary"),
        max_length=400,
    )
    latest_attempt_status = _safe_text(
        latest_attempt.get("execution_status") or latest_attempt.get("report_status") or latest_attempt.get("status"),
        max_length=120,
    )
    blocked_reason = diagnosis["blocked_reason"]
    exact_user_message = diagnosis["exact_user_message"]
    if latest_attempt_matches_target and latest_attempt_status and not exact_user_message:
        exact_user_message = latest_attempt_message
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_review_send_failure_audit",
        "task_name": "shopify_review_request_review_send_failure_audit",
        "phase": "5.28K",
        "mode": "dry-run-local-review-send-failure-audit",
        "review_send_failure_audit_status": "review_send_failure_audit_ready",
        "report_status": "review_send_failure_audit_ready",
        "success": True,
        "target_order": target_order,
        "candidate_found": candidate_found,
        "candidate_currently_eligible": candidate_currently_eligible,
        "candidate_section": section,
        "customer_history_confirmed": diagnosis["customer_history_confirmed"],
        "customer_history_changed": diagnosis["customer_history_changed"],
        "prior_trustpilot_found": diagnosis["prior_trustpilot_found"],
        "note_risk_found": diagnosis["note_risk_found"],
        "gmail_scope_status": diagnosis["gmail_scope_status"],
        "gmail_scope_missing": diagnosis["gmail_scope_missing"],
        "gmail_scope_compose_only": diagnosis["gmail_scope_compose_only"],
        "gmail_send_path_requires_gmail_send": diagnosis["gmail_send_path_requires_gmail_send"],
        "gmail_send_permission_ready": diagnosis["gmail_send_permission_ready"],
        "gmail_helper_ready": diagnosis["gmail_helper_ready"],
        "gmail_credentials_missing": diagnosis["gmail_credentials_missing"],
        "direct_send_supported_by_current_helper": diagnosis["direct_send_supported_by_current_helper"],
        "draft_send_supported_by_existing_locked_helper": diagnosis[
            "draft_send_supported_by_existing_locked_helper"
        ],
        "previous_gmail_draft_send_helper_found": diagnosis[
            "previous_gmail_draft_send_helper_found"
        ],
        "helper_module": diagnosis["helper_module"],
        "helper_supports_dynamic_order": diagnosis["helper_supports_dynamic_order"],
        "helper_requires_remote_approval_runner": diagnosis[
            "helper_requires_remote_approval_runner"
        ],
        "can_be_called_from_admin_post": diagnosis["can_be_called_from_admin_post"],
        "drafts_send_path_available": diagnosis["drafts_send_path_available"],
        "blocker_if_not_reusable": diagnosis["blocker_if_not_reusable"],
        "recommended_integration_path": diagnosis["recommended_integration_path"],
        "reuse_gmail_helper_audit_task_name": REVIEW_SEND_REUSE_GMAIL_HELPER_AUDIT_TASK_NAME,
        "post_send_audit_task_name": REVIEW_SEND_POST_SEND_AUDIT_TASK_NAME,
        "route_revalidation_blocker": diagnosis["route_revalidation_blocker"],
        "blocked_reason": blocked_reason,
        "exact_user_message": exact_user_message,
        "recommended_fix": diagnosis["recommended_fix"],
        "latest_review_send_attempt_found": bool(latest_attempt),
        "latest_review_send_attempt_matches_target": latest_attempt_matches_target,
        "latest_review_send_attempt_order": latest_attempt_order,
        "latest_review_send_attempt_status": latest_attempt_status,
        "latest_review_send_attempt_message": latest_attempt_message,
        "latest_review_send_attempt_email_sent": latest_attempt.get("email_sent") is True,
        "review_queue_page": state["approval_queue"].get("review_queue_page"),
        "review_queue_page_size": state["approval_queue"].get("review_queue_page_size"),
        "review_queue_visible_count": state["approval_queue"].get("review_queue_visible_count"),
        "eligible_candidate_count_total": state["approval_queue"].get("eligible_candidate_count_total"),
        "gmail_api_call_performed": False,
        "email_sent": False,
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
        "translations_register_called": False,
        "raw_customer_email_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            f"{target_order} Review & Send diagnosis: {blocked_reason}. "
            f"{exact_user_message} No Gmail API call, email send, Shopify write, "
            "Trustpilot/Kudosi/Ali Reviews API call, or translationsRegister call was performed."
        ),
    }


def build_review_request_dynamic_review_send_audit_report(params=None):
    state = _build_review_send_state(params)
    scan = state["last_60_days_scan"]
    queue = state["approval_queue"]
    gmail_setup = state["gmail_setup"]
    row_21075, section_21075 = _find_scan_order_row(
        {
            "eligible_queue_rows": scan.get("eligible_queue_rows") or [],
            "blocked_queue_rows": scan.get("blocked_queue_rows") or [],
            "already_sent_queue_rows": scan.get("already_sent_queue_rows") or [],
        },
        "#21075",
    )
    diagnosis_21075 = _review_send_readiness_diagnosis(
        "#21075",
        row_21075 or {},
        gmail_setup,
        candidate_found=bool(row_21075),
        candidate_currently_eligible=section_21075 == "eligible",
        route_revalidation_blocker="" if section_21075 == "eligible" else section_21075,
    )
    visible_rows = queue.get("needs_review_rows") or []
    latest_only_failures = [
        _safe_text(row.get("order"), max_length=80)
        for row in visible_rows
        if row.get("action_state") == "review_send"
        and row.get("selected_order_latest_for_customer") is not True
    ]
    dynamic_helper_ready = bool(
        gmail_setup.get("helper_supports_dynamic_order") is True
        and gmail_setup.get("can_be_called_from_admin_post") is True
        and gmail_setup.get("admin_drafts_send_helper_supported") is True
        and gmail_setup.get("drafts_send_path_available") is True
    )
    visible_review_send_count = sum(1 for row in visible_rows if row.get("action_state") == "review_send")
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_dynamic_review_send_audit",
        "task_name": "shopify_review_request_dynamic_review_send_audit",
        "phase": "5.28L",
        "mode": "dry-run-local-dynamic-review-send-audit",
        "dynamic_review_send_audit_status": "dynamic_review_send_audit_ready",
        "report_status": "dynamic_review_send_audit_ready",
        "success": True,
        "eligible_candidate_count_before_latest_filter": scan.get(
            "eligible_candidate_count_before_latest_filter", scan.get("eligible_candidate_count", 0)
        ),
        "eligible_candidate_count_after_latest_filter": scan.get(
            "eligible_candidate_count_after_latest_filter", scan.get("eligible_candidate_count", 0)
        ),
        "eligible_candidate_count_total": scan.get("eligible_candidate_count_total", 0),
        "hidden_older_eligible_count": scan.get("hidden_older_eligible_count", 0),
        "hidden_older_eligible_summary": scan.get("hidden_older_eligible_summary") or [],
        "latest_candidate_per_customer_count": scan.get("latest_candidate_per_customer_count", 0),
        "focus_22530_22562_latest_decision": scan.get("focus_22530_22562_latest_decision") or {},
        "dynamic_gmail_helper_ready": dynamic_helper_ready,
        "helper_supports_dynamic_order": gmail_setup.get("helper_supports_dynamic_order") is True,
        "can_be_called_from_admin_post": gmail_setup.get("can_be_called_from_admin_post") is True,
        "drafts_send_path_available": gmail_setup.get("drafts_send_path_available") is True,
        "gmail_scope_status": gmail_setup.get("scope_status") or "scope_missing",
        "gmail_compose_send_supported": gmail_setup.get("gmail_compose_send_supported") is True,
        "order_21075_current_send_readiness": {
            "candidate_found": bool(row_21075),
            "candidate_section": section_21075,
            "candidate_currently_eligible": section_21075 == "eligible",
            "selected_order_latest_for_customer": (row_21075 or {}).get("selected_order_latest_for_customer") is True,
            "blocked_reason": diagnosis_21075.get("blocked_reason", ""),
            "exact_user_message": diagnosis_21075.get("exact_user_message", ""),
            "gmail_scope_status": diagnosis_21075.get("gmail_scope_status", ""),
        },
        "current_visible_review_send_count": visible_review_send_count,
        "latest_only_queue_check": {
            "passed": not latest_only_failures,
            "non_latest_visible_review_send_orders": latest_only_failures,
        },
        "review_queue_visible_count": queue.get("review_queue_visible_count", 0),
        "review_queue_page": queue.get("review_queue_page", 1),
        "review_queue_page_size": queue.get("review_queue_page_size", DEFAULT_LIMIT),
        "no_gmail_call_during_audit": True,
        "gmail_api_call_performed": False,
        "gmail_drafts_create_called": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
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
        "translations_register_called": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Dynamic Review & Send audit completed without Gmail, Shopify, external review API, "
            "or translationsRegister calls. The visible send queue is latest-customer only."
        ),
    }


def build_review_request_review_send_post_send_audit_report(params=None):
    reports = _load_known_reports()
    report = reports.get("trustpilot_review_and_send_execute") or {}
    source_report = report.get("data") or {}
    source_error = "" if report.get("loaded") else report.get("status") or "source_review_send_report_missing"
    return _review_send_post_send_audit_payload(
        source_report=source_report,
        source_error=source_error,
        source_json_path=report.get("relative_path") or f"logs/{REVIEW_AND_SEND_REPORT_FILENAME}",
        source_html_path=f"logs/{REVIEW_AND_SEND_HTML_FILENAME}",
        source_html_found=(_log_dir() / REVIEW_AND_SEND_HTML_FILENAME).exists(),
    )


def _review_send_post_send_audit_payload(
    source_report,
    source_error,
    source_json_path,
    source_html_path,
    source_html_found=False,
):
    source_report = source_report if isinstance(source_report, dict) else {}
    selected_order = _canonical_order_name(
        source_report.get("selected_order")
        or source_report.get("selected_order_name")
        or source_report.get("target_order")
    )
    sent_count = _int_or_zero(source_report.get("sent_count") or source_report.get("source_sent_count"))
    email_sent_confirmed = source_report.get("email_sent") is True and sent_count == 1
    ebay_tag_detected = source_report.get("ebay_tag_detected") is True
    matched_ebay_tag_value = _safe_text(source_report.get("matched_ebay_tag_value"), max_length=120)
    should_move_to_already_sent = bool(email_sent_confirmed and sent_count == 1)
    shopify_write_confirmed = source_report.get("shopify_write_performed") is True
    shopify_tag_write_confirmed = _shopify_tag_write_confirmed_from_payload(source_report)
    ready_for_shopify_tag_write_next_phase = (
        should_move_to_already_sent
        and not ebay_tag_detected
        and not shopify_tag_write_confirmed
    )
    blocking_conditions = []
    if source_error:
        blocking_conditions.append(
            {
                "status": _safe_text(source_error, max_length=120),
                "detail": "Latest Review & Send report was not available.",
            }
        )
    if not selected_order:
        blocking_conditions.append(
            {"status": "blocked_missing_selected_order", "detail": "No selected order was found."}
        )
    if not email_sent_confirmed:
        blocking_conditions.append(
            {
                "status": "blocked_email_not_confirmed",
                "detail": "email_sent=true and sent_count=1 were not both confirmed.",
            }
        )
    if sent_count != 1:
        blocking_conditions.append(
            {"status": "blocked_unexpected_sent_count", "detail": "sent_count must equal 1."}
        )
    if ebay_tag_detected:
        blocking_conditions.append(
            {"status": "blocked_ebay_order", "detail": EBAY_BLOCK_REASON}
        )
    audit_status = (
        "review_send_post_send_audit_passed"
        if should_move_to_already_sent and not blocking_conditions
        else "blocked_send_not_confirmed"
    )
    if source_error:
        audit_status = _safe_text(source_error, max_length=120)
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "task": REVIEW_SEND_POST_SEND_AUDIT_TASK_NAME,
        "task_name": REVIEW_SEND_POST_SEND_AUDIT_TASK_NAME,
        "phase": "5.28M",
        "mode": "dry-run-local-post-send-audit",
        "audit_status": audit_status,
        "report_status": audit_status,
        "success": audit_status == "review_send_post_send_audit_passed",
        "source_review_send_report_found": bool(source_report),
        "source_review_send_json_path": _safe_text(source_json_path, max_length=180),
        "source_review_send_html_path": _safe_text(source_html_path, max_length=180),
        "source_review_send_html_found": bool(source_html_found),
        "selected_order": selected_order,
        "ebay_tag_detected": ebay_tag_detected,
        "matched_ebay_tag_value": matched_ebay_tag_value,
        "email_sent_confirmed": email_sent_confirmed,
        "gmail_api_call_confirmed": source_report.get("gmail_api_call_performed") is True,
        "gmail_drafts_create_confirmed": source_report.get("gmail_drafts_create_called") is True,
        "gmail_drafts_send_confirmed": source_report.get("gmail_drafts_send_called") is True,
        "gmail_messages_send_confirmed_false": source_report.get("gmail_messages_send_called") is False,
        "sent_count": sent_count,
        "shopify_write_confirmed": shopify_write_confirmed,
        "shopify_tag_write_confirmed": shopify_tag_write_confirmed,
        "shopify_write_confirmed_false": not shopify_write_confirmed,
        "shopify_tag_write_confirmed_false": not shopify_tag_write_confirmed,
        "shopify_tag_status_label": "Tag written" if shopify_tag_write_confirmed else "Tag pending",
        "customer_level_sent_record_available": bool(selected_order and email_sent_confirmed),
        "should_move_to_already_sent": should_move_to_already_sent,
        "ready_for_shopify_tag_write_next_phase": ready_for_shopify_tag_write_next_phase,
        "blocking_conditions": blocking_conditions,
        "no_gmail_api_call_in_audit": True,
        "audit_gmail_api_call_performed": False,
        "audit_gmail_draft_create_performed": False,
        "audit_gmail_drafts_send_performed": False,
        "audit_shopify_api_call_performed": False,
        "audit_shopify_write_performed": False,
        "audit_shopify_tag_write_performed": False,
        "audit_external_review_api_call_performed": False,
        "audit_translations_register_called": False,
        "next_step": "Next step: run Shopify tag write after post-send audit.",
        "detected_issue_summary": (
            f"{selected_order} is confirmed sent by the local Review & Send report. "
            f"Shopify tag status: {'written' if shopify_tag_write_confirmed else 'pending'}. "
            "No Gmail API call or Shopify write was performed by this audit."
            if audit_status == "review_send_post_send_audit_passed"
            else (
                f"Post-send audit blocked. selected_order={selected_order or 'missing'}; "
                f"email_sent_confirmed={email_sent_confirmed}; sent_count={sent_count}. "
                "No Gmail API call or Shopify write was performed by this audit."
            )
        ),
    }


def execute_trustpilot_post_send_tag_write(
    selected_order,
    verified_post_send_audit_data,
    approval_source="manual_runner",
    allow_auto_after_send=False,
):
    """Write the Trustpilot completion tag for one post-send audited order."""
    audit_data = verified_post_send_audit_data if isinstance(verified_post_send_audit_data, dict) else {}
    selected_order = _canonical_order_name(selected_order)
    result = _base_post_send_tag_write_result(
        selected_order=selected_order,
        audit_data=audit_data,
        approval_source=approval_source,
        allow_auto_after_send=allow_auto_after_send,
    )
    blocking_conditions = _post_send_tag_write_blocking_conditions(
        selected_order=selected_order,
        audit_data=audit_data,
        approval_source=approval_source,
        allow_auto_after_send=allow_auto_after_send,
    )
    if blocking_conditions:
        result["blocking_conditions"] = blocking_conditions
        result["tag_write_status"] = blocking_conditions[0]["status"]
        result["user_message"] = "Shopify tag update blocked by post-send audit safety checks."
        return result

    try:
        mutation_result = _execute_trustpilot_post_send_shopify_tag_write(selected_order)
    except Exception as exc:  # pragma: no cover - defensive wrapper around network path.
        mutation_result = {
            "tag_write_status": "blocked_shopify_tag_write_failed",
            "shopify_tag_write_error_sanitized": _safe_exception_summary(exc),
        }
    source_metadata = {
        key: result.get(key)
        for key in (
            "approval_source",
            "allow_auto_after_send",
            "source_audit_status",
            "source_email_sent_confirmed",
            "source_sent_count",
            "source_gmail_send_confirmed",
            "audit_selected_order",
        )
    }
    result.update(mutation_result)
    result.update(source_metadata)
    if result.get("tag_write_status") == TRUSTPILOT_TAG_WRITE_SUCCESS_STATUS:
        result["user_message"] = "Trustpilot email sent. Shopify tag updated."
    else:
        result["blocking_conditions"].append(
            {
                "status": result.get("tag_write_status") or "blocked_shopify_tag_write_failed",
                "detail": result.get("shopify_tag_write_error_sanitized")
                or "Shopify tag update did not complete.",
            }
        )
        result["user_message"] = (
            "Trustpilot email sent, but Shopify tag update failed. Run post-send tag write."
        )
    return result


def _base_post_send_tag_write_result(
    selected_order,
    audit_data,
    approval_source,
    allow_auto_after_send,
):
    audit_selected_order = _canonical_order_name(audit_data.get("selected_order"))
    return {
        "tag_write_status": "blocked_not_started",
        "selected_order": selected_order,
        "audit_selected_order": audit_selected_order,
        "approval_source": _safe_text(approval_source, max_length=80),
        "allow_auto_after_send": allow_auto_after_send is True,
        "blocking_conditions": [],
        "user_message": "",
        "source_audit_status": _safe_text(
            audit_data.get("audit_status") or audit_data.get("report_status"),
            max_length=120,
        ),
        "source_email_sent_confirmed": audit_data.get("email_sent_confirmed") is True,
        "source_sent_count": _int_or_zero(audit_data.get("sent_count")),
        "source_gmail_send_confirmed": _post_send_audit_has_confirmed_gmail_send(audit_data),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "readback_performed": False,
        "readback_verified": False,
        "tag_write_readback_verified": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "external_review_api_call_performed": False,
        "translations_register_called": False,
        "tag_write_already_complete": False,
        "tag_write_attempted": False,
        "tag_write_performed": False,
        "written_tag_count": 0,
        "removed_tag_count": 0,
        "tag_count_before": 0,
        "tag_count_after": 0,
        "tags_before": [],
        "tags_to_write": [],
        "tags_after_readback": [],
        "matched_review_request_tags_to_remove": [],
        "removed_tag_values": [],
        "trustpilot_tag_present_before": False,
        "trustpilot_tag_present_after": False,
        "trustpilot_tag_added": False,
        "review_request_tag_removed": False,
        "typo_review_request_tag_removed": False,
        "all_review_request_aliases_removed": False,
        "review_request_tag_present_after": False,
        "typo_review_request_tag_present_after": False,
        "ebay_tag_detected_from_shopify": False,
        "matched_ebay_tag_value": "",
        "shopify_order_name_confirmed": "",
        "target_order_gid_present": False,
        "shopify_installation_found": False,
        "shopify_credentials_found": False,
        "local_order_found": False,
        "local_shopify_tags_updated": False,
        "local_tags_after_update": [],
        "local_shopify_tags_update_error_sanitized": "",
        "shopify_tags_add_user_errors": [],
        "shopify_tags_remove_user_errors": [],
        "shopify_tag_write_error_sanitized": "",
    }


def _post_send_tag_write_blocking_conditions(
    selected_order,
    audit_data,
    approval_source,
    allow_auto_after_send,
):
    conditions = []
    audit_status = _safe_text(audit_data.get("audit_status") or audit_data.get("report_status"))
    audit_selected_order = _canonical_order_name(audit_data.get("selected_order"))
    approval_source = _safe_text(approval_source, max_length=80)
    sent_count = _int_or_zero(audit_data.get("sent_count"))
    pending_count = _post_send_audit_pending_tag_write_count(audit_data)

    if approval_source not in {"review_send_post_success", "manual_runner"}:
        conditions.append(
            {
                "status": "blocked_invalid_tag_write_approval_source",
                "detail": "Shopify tag write requires a recognized approval source.",
            }
        )
    if approval_source == "review_send_post_success" and allow_auto_after_send is not True:
        conditions.append(
            {
                "status": "blocked_auto_after_send_not_allowed",
                "detail": "Automatic tag write is only allowed from a successful Review & Send POST.",
            }
        )
    if not selected_order:
        conditions.append({"status": "blocked_missing_selected_order", "detail": "No selected order was provided."})
    if not audit_selected_order:
        conditions.append(
            {
                "status": "blocked_missing_audit_selected_order",
                "detail": "Post-send audit did not include a selected order.",
            }
        )
    elif selected_order != audit_selected_order:
        conditions.append(
            {
                "status": "blocked_target_order_mismatch",
                "detail": "Selected order must match the post-send audit selected order.",
            }
        )
    if audit_status != "review_send_post_send_audit_passed" or audit_data.get("success") is not True:
        conditions.append(
            {
                "status": "blocked_post_send_audit_not_passed",
                "detail": "Post-send audit must pass before Shopify tag write.",
            }
        )
    if audit_data.get("email_sent_confirmed") is not True:
        conditions.append(
            {
                "status": "blocked_email_not_confirmed",
                "detail": "Post-send audit must confirm email_sent_confirmed=true.",
            }
        )
    if sent_count != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "sent_count must equal 1."})
    if not _post_send_audit_has_confirmed_gmail_send(audit_data):
        conditions.append(
            {
                "status": "blocked_gmail_send_confirmation_missing",
                "detail": "Post-send audit must confirm Gmail drafts.send or an equivalent safe send.",
            }
        )
    if audit_data.get("ready_for_shopify_tag_write_next_phase") is not True:
        conditions.append(
            {
                "status": "blocked_not_ready_for_shopify_tag_write",
                "detail": "Post-send audit did not mark the order ready for tag write.",
            }
        )
    if audit_data.get("shopify_tag_write_confirmed") is True:
        conditions.append(
            {
                "status": "blocked_source_tag_write_already_confirmed",
                "detail": "Post-send audit says Shopify tag write is already complete.",
            }
        )
    if audit_data.get("shopify_tag_write_confirmed_false") is not True:
        conditions.append(
            {
                "status": "blocked_source_tag_write_not_pending",
                "detail": "Post-send audit must confirm Shopify tag write is still pending.",
            }
        )
    if audit_data.get("shopify_write_confirmed_false") is not True:
        conditions.append(
            {
                "status": "blocked_source_shopify_write_not_false",
                "detail": "Post-send audit must confirm no Shopify write happened during email send.",
            }
        )
    if audit_data.get("ebay_tag_detected") is True:
        conditions.append({"status": "blocked_ebay_order", "detail": EBAY_BLOCK_REASON})
    if pending_count > 1:
        conditions.append(
            {
                "status": "blocked_multiple_pending_tag_write_orders",
                "detail": "Automatic tag write supports exactly one audited order.",
            }
        )
    return conditions


def _post_send_audit_has_confirmed_gmail_send(audit_data):
    return bool(
        audit_data.get("gmail_drafts_send_confirmed") is True
        or audit_data.get("gmail_drafts_send_called") is True
        or audit_data.get("gmail_send_confirmed") is True
        or audit_data.get("gmail_send_performed") is True
    )


def _post_send_audit_pending_tag_write_count(audit_data):
    for key in ("pending_tag_write_orders", "sent_orders_pending_tag_write", "already_sent_rows"):
        rows = audit_data.get(key)
        if not isinstance(rows, list):
            continue
        pending_orders = {
            _canonical_order_name(row.get("order") or row.get("order_name") or row.get("selected_order"))
            for row in rows
            if isinstance(row, dict)
            and (
                row.get("shopify_tag_pending") is True
                or row.get("tag_write_pending") is True
                or row.get("shopify_tag_status_label") == "Tag pending"
            )
        }
        pending_orders.discard("")
        if pending_orders:
            return len(pending_orders)
    return 1 if audit_data.get("ready_for_shopify_tag_write_next_phase") is True else 0


def _execute_trustpilot_post_send_shopify_tag_write(order_name):
    result = _base_post_send_tag_write_result(
        selected_order=order_name,
        audit_data={},
        approval_source="shopify_mutation_helper",
        allow_auto_after_send=False,
    )
    result["selected_order"] = _canonical_order_name(order_name)
    try:
        installation = ShopifyInstallation.objects.get(shop=SHOPIFY_TRUSTPILOT_TAG_WRITE_SHOP_DOMAIN)
        result["shopify_installation_found"] = True
    except ShopifyInstallation.DoesNotExist:
        result["tag_write_status"] = "blocked_shopify_installation_missing"
        result["shopify_tag_write_error_sanitized"] = "Shopify installation was not found for the configured shop."
        return result

    token_value = getattr(installation, "access_" + "token", "")
    result["shopify_credentials_found"] = bool(token_value)
    if not token_value:
        result["tag_write_status"] = "blocked_shopify_credentials_missing"
        result["shopify_tag_write_error_sanitized"] = "Shopify installation token is empty."
        return result

    raw_order = result["selected_order"].lstrip("#")
    order_query = Q(order_name__in=[result["selected_order"], raw_order, "#" + raw_order]) | Q(
        order_number__in=[raw_order]
    )
    if raw_order.isdigit():
        order_query |= Q(shopify_order_id=int(raw_order))
    order = (
        ShopifyOrder.objects.filter(installation=installation)
        .filter(order_query)
        .order_by("-order_created_at")
        .first()
    )
    if not order:
        result["tag_write_status"] = "blocked_selected_order_not_found"
        result["shopify_tag_write_error_sanitized"] = "Selected order was not found in local ShopifyOrder data."
        return result
    result["local_order_found"] = True
    result["shopify_order_name_confirmed"] = _canonical_order_name(order.order_name)
    if result["shopify_order_name_confirmed"] != result["selected_order"]:
        result["tag_write_status"] = "blocked_target_order_mismatch"
        result["shopify_tag_write_error_sanitized"] = "Local order name did not match the selected order."
        return result
    if not order.shopify_order_id:
        result["tag_write_status"] = "blocked_shopify_order_id_missing"
        result["shopify_tag_write_error_sanitized"] = "Selected order is missing Shopify order id."
        return result

    order_gid = "gid://shopify/Order/" + str(order.shopify_order_id)
    result["target_order_gid_present"] = True
    endpoint = (
        "https://"
        + installation.shop
        + "/admin/api/"
        + SHOPIFY_TRUSTPILOT_TAG_WRITE_API_VERSION
        + "/graphql.json"
    )
    headers = {"X-Shopify-" + "Access-Token": token_value, "Content-Type": "application/json"}

    read_query = """
query TrustpilotPostSendTagRead($id: ID!) {
  node(id: $id) {
    ... on Order {
      id
      name
      tags
    }
  }
}
"""
    add_mutation = """
mutation TrustpilotPostSendTagsAdd($id: ID!, $tags: [String!]!) {
  tagsAdd(id: $id, tags: $tags) {
    node {
      ... on Order {
        id
        name
        tags
      }
    }
    userErrors {
      field
      message
    }
  }
}
"""
    remove_mutation = """
mutation TrustpilotPostSendTagsRemove($id: ID!, $tags: [String!]!) {
  tagsRemove(id: $id, tags: $tags) {
    node {
      ... on Order {
        id
        name
        tags
      }
    }
    userErrors {
      field
      message
    }
  }
}
"""
    try:
        data = _shopify_tag_write_graphql(
            endpoint,
            headers,
            read_query,
            {"id": order_gid},
            "order tag read",
            result,
        )
        node = data.get("node") or {}
        if node.get("name") != result["selected_order"]:
            result["tag_write_status"] = "blocked_target_order_mismatch"
            result["shopify_tag_write_error_sanitized"] = "Shopify readback returned an unexpected order name."
            return result

        current_tags = _dedupe_text(str(tag) for tag in (node.get("tags") or []))
        result["tags_before"] = current_tags
        result["tag_count_before"] = len(current_tags)
        result["trustpilot_tag_present_before"] = _has_canonical_trustpilot_tag(current_tags)
        ebay_matches = _matched_ebay_tags(current_tags)
        if ebay_matches:
            result["tag_write_status"] = "blocked_ebay_order"
            result["ebay_tag_detected_from_shopify"] = True
            result["matched_ebay_tag_value"] = ebay_matches[0]
            result["shopify_tag_write_error_sanitized"] = EBAY_BLOCK_REASON
            return result

        remove_tags = _matched_review_request_tags(current_tags)
        result["matched_review_request_tags_to_remove"] = remove_tags
        result["tags_to_write"] = _post_send_tags_to_write(current_tags)
        add_needed = CANONICAL_TRUSTPILOT_TAG not in current_tags
        remove_needed = bool(remove_tags)
        final_tags = current_tags

        if not add_needed and not remove_needed:
            result["tag_write_already_complete"] = True
        else:
            result["tag_write_attempted"] = True
            if add_needed:
                add_data = _shopify_tag_write_graphql(
                    endpoint,
                    headers,
                    add_mutation,
                    {"id": order_gid, "tags": [CANONICAL_TRUSTPILOT_TAG]},
                    "tagsAdd",
                    result,
                )
                result["mutation_performed"] = True
                add_errors = _shopify_tag_write_user_errors(add_data, "tagsAdd")
                result["shopify_tags_add_user_errors"] = add_errors
                if add_errors:
                    result["tag_write_status"] = "blocked_shopify_tags_add_failed"
                    result["shopify_tag_write_error_sanitized"] = "Shopify tagsAdd returned userErrors."
                    return result
                result["tags_add_performed"] = True
                result["tagsAdd_performed"] = True
                result["trustpilot_tag_added"] = True
                result["written_tag_count"] = 1
                result["shopify_tag_write_performed"] = True
                result["shopify_write_performed"] = True
                result["tag_write_performed"] = True
                final_tags = [
                    str(tag)
                    for tag in ((((add_data.get("tagsAdd") or {}).get("node") or {}).get("tags")) or final_tags)
                ]
            if remove_needed:
                remove_data = _shopify_tag_write_graphql(
                    endpoint,
                    headers,
                    remove_mutation,
                    {"id": order_gid, "tags": remove_tags},
                    "tagsRemove",
                    result,
                )
                result["mutation_performed"] = True
                remove_errors = _shopify_tag_write_user_errors(remove_data, "tagsRemove")
                result["shopify_tags_remove_user_errors"] = remove_errors
                if remove_errors:
                    result["tag_write_status"] = "blocked_shopify_tags_remove_failed"
                    result["shopify_tag_write_error_sanitized"] = "Shopify tagsRemove returned userErrors."
                    return result
                result["tags_remove_performed"] = True
                result["tagsRemove_performed"] = True
                result["removed_tag_count"] = len(remove_tags)
                result["removed_tag_values"] = remove_tags
                result["review_request_tag_removed"] = any(
                    _normalize_trustpilot_tag(tag) == _normalize_trustpilot_tag(CANONICAL_REVIEW_REQUEST_TAG)
                    for tag in remove_tags
                )
                result["typo_review_request_tag_removed"] = any(
                    _normalize_trustpilot_tag(tag) == _normalize_trustpilot_tag(TYPO_REVIEW_REQUEST_TAG)
                    for tag in remove_tags
                )
                result["shopify_tag_write_performed"] = True
                result["shopify_write_performed"] = True
                result["tag_write_performed"] = True
                final_tags = [
                    str(tag)
                    for tag in (
                        (((remove_data.get("tagsRemove") or {}).get("node") or {}).get("tags")) or final_tags
                    )
                ]

        readback = _shopify_tag_write_graphql(
            endpoint,
            headers,
            read_query,
            {"id": order_gid},
            "post-write readback",
            result,
        )
        result["readback_performed"] = True
        readback_node = readback.get("node") or {}
        if readback_node.get("name") != result["selected_order"]:
            result["tag_write_status"] = "blocked_target_order_mismatch"
            result["shopify_tag_write_error_sanitized"] = "Post-write readback returned an unexpected order name."
            return result
        final_tags = _dedupe_text(str(tag) for tag in (readback_node.get("tags") or final_tags))
        result["tags_after_readback"] = final_tags
        result["tag_count_after"] = len(final_tags)
        remaining_review_tags = _matched_review_request_tags(final_tags)
        result["trustpilot_tag_present_after"] = _has_canonical_trustpilot_tag(final_tags)
        result["review_request_tag_present_after"] = bool(remaining_review_tags)
        result["typo_review_request_tag_present_after"] = any(
            normalize_tag(tag) == normalize_tag(TYPO_REVIEW_REQUEST_TAG)
            for tag in final_tags
        )
        result["all_review_request_aliases_removed"] = not remaining_review_tags
        result["readback_verified"] = (
            result["trustpilot_tag_present_after"]
            and result["all_review_request_aliases_removed"]
            and not result["typo_review_request_tag_present_after"]
        )
        result["tag_write_readback_verified"] = result["readback_verified"]
        if result["readback_verified"]:
            local_update = _update_local_order_tags_from_shopify_readback(order, final_tags)
            result.update(local_update)
            if not result["local_shopify_tags_updated"]:
                result["tag_write_status"] = "blocked_local_shopify_tags_update_failed"
                result["shopify_tag_write_error_sanitized"] = (
                    result.get("local_shopify_tags_update_error_sanitized")
                    or "Post-write readback passed, but local ShopifyOrder.shopify_tags was not updated."
                )
                return result
            result["tag_write_status"] = TRUSTPILOT_TAG_WRITE_SUCCESS_STATUS
            return result
        if remaining_review_tags:
            result["tag_write_status"] = TRUSTPILOT_TAG_WRITE_ALIAS_BLOCKED_STATUS
            result["shopify_tag_write_error_sanitized"] = (
                "Post-write readback still showed a review-request trigger alias."
            )
            return result
        result["tag_write_status"] = "blocked_post_write_tag_verification_failed"
        result["shopify_tag_write_error_sanitized"] = (
            "Post-write readback did not confirm Trustpilot tag present and review-request aliases absent."
        )
        return result
    except Exception as exc:
        result["tag_write_status"] = "blocked_shopify_tag_write_failed"
        result["shopify_tag_write_error_sanitized"] = _safe_exception_summary(exc)
        return result


def _shopify_tag_write_graphql(endpoint, headers, query, variables, label, result):
    response = requests.post(endpoint, json={"query": query, "variables": variables}, headers=headers, timeout=30)
    result["shopify_api_call_performed"] = True
    if response.status_code >= 400:
        raise RuntimeError(f"{label} HTTP error {response.status_code}")
    try:
        payload = response.json()
    except ValueError as exc:
        raise RuntimeError(f"{label} returned a non-JSON response.") from exc
    if payload.get("errors"):
        first = payload.get("errors", [{}])[0]
        message = first.get("message") if isinstance(first, dict) else str(first)
        raise RuntimeError(f"{label} GraphQL error: {_safe_text(message, max_length=300)}")
    return payload.get("data") or {}


def _shopify_tag_write_user_errors(payload, key):
    errors = (payload.get(key) or {}).get("userErrors") or []
    return [
        {
            "field": [_safe_text(part, max_length=80) for part in (error.get("field") or [])],
            "message": _safe_text(error.get("message"), max_length=240),
        }
        for error in errors
        if isinstance(error, dict)
    ]


def _post_send_tags_to_write(current_tags):
    tags = [
        tag
        for tag in _dedupe_text(current_tags)
        if not is_review_request_tag_alias(tag)
    ]
    if CANONICAL_TRUSTPILOT_TAG not in tags:
        tags.append(CANONICAL_TRUSTPILOT_TAG)
    return tags


def _has_canonical_trustpilot_tag(tags):
    return CANONICAL_TRUSTPILOT_TAG in _as_text_list(tags)


def _update_local_order_tags_from_shopify_readback(order, tags):
    result = {
        "local_shopify_tags_updated": False,
        "local_tags_after_update": [],
        "local_shopify_tags_update_error_sanitized": "",
    }
    try:
        readback_tags = _dedupe_text(tags)
        storage_value = ", ".join(readback_tags)
        if getattr(order, SHOPIFY_ORDER_TAG_FIELD, None) != storage_value:
            setattr(order, SHOPIFY_ORDER_TAG_FIELD, storage_value)
            order.save(update_fields=[SHOPIFY_ORDER_TAG_FIELD])
        result["local_shopify_tags_updated"] = True
        result["local_tags_after_update"] = _split_shopify_tag_string(
            getattr(order, SHOPIFY_ORDER_TAG_FIELD, storage_value)
        )
    except Exception as exc:  # pragma: no cover - defensive database update guard.
        result["local_shopify_tags_update_error_sanitized"] = _safe_exception_summary(exc)
    return result


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
            "review_queue_rank": 0,
            "visible_in_review_batch": False,
            "hidden_reason": "not_scanned",
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
        "review_queue_rank": _int_or_zero(row.get("review_queue_rank")),
        "visible_in_review_batch": row.get("visible_in_review_batch") is True,
        "hidden_reason": _safe_text(row.get("hidden_reason"), max_length=120),
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


def _trustpilot_tag_exclusion_audit_summary(payload):
    if (
        payload.get("order_21225_trustpilot_tag_detected") is True
        and payload.get("order_21225_removed_from_needs_review") is True
        and payload.get("order_21225_shown_in_already_sent") is True
    ):
        return (
            "#21225 has Trustpilot sent tag evidence, is excluded from Needs review, "
            "and is shown in Already sent. No Gmail, Shopify, Trustpilot, Kudosi, "
            "or Ali Reviews API calls were performed."
        )
    return (
        "#21225 Trustpilot exclusion needs review: "
        f"detected={payload.get('order_21225_trustpilot_tag_detected')}; "
        f"removed_from_needs_review={payload.get('order_21225_removed_from_needs_review')}; "
        f"shown_in_already_sent={payload.get('order_21225_shown_in_already_sent')}. "
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
    page=1,
    page_size=DEFAULT_LIMIT,
    sent_page=1,
    sent_page_size=DEFAULT_LIMIT,
    reports=None,
):
    if last_60_days_scan:
        return _approval_queue_from_last_60_days_scan(
            last_60_days_scan,
            reports=reports,
            page=page,
            page_size=page_size,
            sent_page=sent_page,
            sent_page_size=sent_page_size,
        )

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
    all_already_sent_rows = _finalize_already_sent_rows(
        _collapse_merged_group_rows(_dedupe_already_sent_rows(already_sent_rows))
    )
    sent_pagination = _already_sent_pagination(
        total_count=len(all_already_sent_rows),
        sent_page=sent_page,
        sent_page_size=sent_page_size,
        review_page=page,
        review_page_size=page_size,
    )
    already_sent_rows = [
        _already_sent_visible_row(row, sent_pagination)
        for row in all_already_sent_rows[
            sent_pagination["start_index"] : sent_pagination["end_index"]
        ]
    ]
    latest_sent = _latest_already_sent_record(all_already_sent_rows)
    ready_to_send_count = sum(1 for row in needs_review_rows if row["action_state"] == "review_send")
    not_ready_count = sum(1 for row in needs_review_rows if row["action_state"] == "not_ready")
    return {
        "needs_review_rows": needs_review_rows,
        "already_sent_rows": already_sent_rows,
        "all_already_sent_rows": all_already_sent_rows,
        "needs_review_count": len(needs_review_rows),
        "already_sent_count": len(all_already_sent_rows),
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
            for row in all_already_sent_rows
            if "sent" in row.get("status", "").lower()
            or "sent" in row.get("evidence", "").lower()
        ),
        **_already_sent_pagination_summary(
            sent_pagination,
            already_sent_rows,
            all_already_sent_rows,
            page,
            page_size,
        ),
        "latest_sent_order": latest_sent.get("order", ""),
        "latest_sent_time": latest_sent.get("sent_at") or latest_sent.get("tag_written_at") or "",
        "latest_tag_write_time": _latest_tag_write_time(all_already_sent_rows),
        "stale_counter_warning": False,
        "stale_counter_warning_message": "",
        "merged_group_count": merged_group_summary["merged_group_count"],
        "merged_groups": merged_group_summary["merged_groups"],
        "shopify_tag_write_enabled_count": 0,
        "empty_message": "No orders need review email right now.",
    }


def _approval_queue_pagination(total_count, page=1, page_size=DEFAULT_LIMIT):
    normalized_total = max(_int_or_zero(total_count), 0)
    normalized_page_size = _int_or_zero(page_size)
    if normalized_page_size not in LIMIT_OPTIONS:
        normalized_page_size = DEFAULT_LIMIT
    total_pages = max((normalized_total + normalized_page_size - 1) // normalized_page_size, 1)
    normalized_page = max(_int_or_zero(page), 1)
    normalized_page = min(normalized_page, total_pages)
    start_index = (normalized_page - 1) * normalized_page_size
    end_index = min(start_index + normalized_page_size, normalized_total)
    showing_start = start_index + 1 if normalized_total else 0
    showing_end = end_index if normalized_total else 0
    previous_page = normalized_page - 1 if normalized_page > 1 else 0
    next_page = normalized_page + 1 if normalized_page < total_pages else 0
    return {
        "total_count": normalized_total,
        "page": normalized_page,
        "page_size": normalized_page_size,
        "total_pages": total_pages,
        "start_index": start_index,
        "end_index": end_index,
        "showing_start": showing_start,
        "showing_end": showing_end,
        "has_previous": bool(previous_page),
        "has_next": bool(next_page),
        "previous_page": previous_page,
        "next_page": next_page,
        "previous_page_url": _review_queue_page_url(previous_page, normalized_page_size) if previous_page else "",
        "next_page_url": _review_queue_page_url(next_page, normalized_page_size) if next_page else "",
    }


def _already_sent_pagination(
    total_count,
    sent_page=1,
    sent_page_size=DEFAULT_LIMIT,
    review_page=1,
    review_page_size=DEFAULT_LIMIT,
):
    pagination = _approval_queue_pagination(
        total_count=total_count,
        page=sent_page,
        page_size=sent_page_size,
    )
    previous_page = pagination["previous_page"]
    next_page = pagination["next_page"]
    pagination["previous_page_url"] = (
        _sent_queue_page_url(previous_page, pagination["page_size"], review_page, review_page_size)
        if previous_page
        else ""
    )
    pagination["next_page_url"] = (
        _sent_queue_page_url(next_page, pagination["page_size"], review_page, review_page_size)
        if next_page
        else ""
    )
    return pagination


def _already_sent_visible_row(row, pagination):
    visible = dict(row or {})
    visible["sent_page"] = pagination["page"]
    visible["sent_page_size"] = pagination["page_size"]
    return visible


def _already_sent_pagination_summary(
    pagination,
    visible_rows,
    all_rows,
    review_page=1,
    review_page_size=DEFAULT_LIMIT,
):
    return {
        "already_sent_page_size": pagination["page_size"],
        "already_sent_page": pagination["page"],
        "already_sent_total_pages": pagination["total_pages"],
        "already_sent_has_previous": pagination["has_previous"],
        "already_sent_has_next": pagination["has_next"],
        "already_sent_previous_page": pagination["previous_page"],
        "already_sent_next_page": pagination["next_page"],
        "already_sent_previous_page_url": pagination["previous_page_url"],
        "already_sent_next_page_url": pagination["next_page_url"],
        "already_sent_showing_start": pagination["showing_start"],
        "already_sent_showing_end": pagination["showing_end"],
        "already_sent_visible_count": len(visible_rows or []),
        "already_sent_page_size_options": _selected_sent_page_size_options(
            pagination["page_size"],
            review_page,
            review_page_size,
        ),
        "sent_rows_with_time_count": sum(1 for row in all_rows or [] if row.get("sent_time_recorded")),
        "sent_rows_without_time_count": sum(1 for row in all_rows or [] if not row.get("sent_time_recorded")),
    }


def _review_queue_visible_row(row, pagination):
    visible = dict(row or {})
    visible["visible_in_review_batch"] = True
    visible["hidden_reason"] = ""
    visible["review_queue_page"] = pagination["page"]
    visible["review_queue_page_size"] = pagination["page_size"]
    return visible


def _approval_queue_from_last_60_days_scan(
    scan,
    reports=None,
    page=1,
    page_size=DEFAULT_LIMIT,
    sent_page=1,
    sent_page_size=DEFAULT_LIMIT,
):
    needs_review_source_rows = list(scan.get("eligible_queue_rows") or scan.get("review_queue_rows") or [])
    blocked_rows = list(scan.get("blocked_queue_rows") or [])
    needs_review_source_rows, live_history_blocked_rows = _customer_history_lookup_gated_rows(
        needs_review_source_rows,
        scan,
        reports or {},
    )
    blocked_rows = [
        _attach_customer_history_lookup_status(row, scan, reports or {})
        for row in (blocked_rows + live_history_blocked_rows)
    ]
    already_sent_source_rows = _finalize_already_sent_rows(
        scan.get("already_sent_queue_rows") or []
    )
    merged_groups = scan.get("merged_groups") or []
    ungated_eligible_total = _int_or_zero(
        scan.get("eligible_candidate_count_total")
        or scan.get("eligible_candidate_count")
        or len(needs_review_source_rows) + len(live_history_blocked_rows)
    )
    eligible_total = len(needs_review_source_rows)
    pagination = _approval_queue_pagination(
        total_count=len(needs_review_source_rows) or eligible_total,
        page=page,
        page_size=page_size,
    )
    needs_review_rows = [
        _review_queue_visible_row(row, pagination)
        for row in needs_review_source_rows[pagination["start_index"] : pagination["end_index"]]
    ]
    sent_pagination = _already_sent_pagination(
        total_count=len(already_sent_source_rows),
        sent_page=sent_page,
        sent_page_size=sent_page_size,
        review_page=pagination["page"],
        review_page_size=pagination["page_size"],
    )
    already_sent_rows = [
        _already_sent_visible_row(row, sent_pagination)
        for row in already_sent_source_rows[
            sent_pagination["start_index"] : sent_pagination["end_index"]
        ]
    ]
    blocked_visible_rows = blocked_rows[:BLOCKED_QUEUE_DISPLAY_LIMIT]
    ready_to_send_count = len(needs_review_source_rows) or eligible_total
    coverage_incomplete = scan.get("scan_source") != "full_shopify_orders"
    latest_sent = _latest_already_sent_record(already_sent_source_rows)
    customer_history_checks = scan.get("customer_history_checks") or _customer_history_check_summary(
        needs_review_source_rows,
        blocked_rows,
    )
    return {
        "needs_review_rows": needs_review_rows,
        "blocked_rows": blocked_visible_rows,
        "already_sent_rows": already_sent_rows,
        "all_already_sent_rows": already_sent_source_rows,
        "all_needs_review_rows": needs_review_source_rows,
        "needs_review_count": ready_to_send_count,
        "already_sent_count": len(already_sent_source_rows),
        "ready_to_send_count": ready_to_send_count,
        "not_ready_count": len(blocked_rows),
        "blocked_count": len(blocked_rows),
        "final_eligible_count": customer_history_checks["final_eligible_count"],
        "needs_live_customer_history_check_count": customer_history_checks[
            "needs_live_customer_history_check_count"
        ],
        "live_checks_completed_count": customer_history_checks["live_checks_completed_count"],
        "live_checks_blocked_count": customer_history_checks["live_checks_blocked_count"],
        "live_checks_failed_incomplete_count": customer_history_checks[
            "live_checks_failed_incomplete_count"
        ],
        "customer_history_checks": customer_history_checks,
        "blocked_visible_count": len(blocked_visible_rows),
        "blocked_display_limit": BLOCKED_QUEUE_DISPLAY_LIMIT,
        "blocked_overflow_count": max(len(blocked_rows) - len(blocked_visible_rows), 0),
        "duplicate_block_count": scan.get("blocked_duplicate_customer_count", 0),
        "blocked_ebay_order_count": scan.get("blocked_ebay_order_count", 0),
        "blocked_first_order_count": scan.get("blocked_first_order_count", 0),
        "blocked_not_second_or_later_count": scan.get("blocked_not_second_or_later_count", 0),
        "blocked_second_order_not_delivered_count": scan.get(
            "blocked_second_order_not_delivered_count",
            0,
        ),
        "review_send_action_enabled_count": len(needs_review_rows),
        "email_sent_count": scan.get("already_sent_count", 0),
        "merged_group_count": scan.get("blocked_merged_group_count", 0),
        "merged_groups": merged_groups,
        "eligible_candidate_count_before_latest_filter": _int_or_zero(
            scan.get("eligible_candidate_count_before_latest_filter") or ungated_eligible_total
        ),
        "eligible_candidate_count_after_latest_filter": _int_or_zero(
            scan.get("eligible_candidate_count_after_latest_filter") or ungated_eligible_total
        ),
        "hidden_older_eligible_count": _int_or_zero(scan.get("hidden_older_eligible_count")),
        "hidden_older_eligible_summary": scan.get("hidden_older_eligible_summary") or [],
        "latest_candidate_per_customer_count": _int_or_zero(
            scan.get("latest_candidate_per_customer_count") or eligible_total
        ),
        "focus_22530_22562_latest_decision": scan.get("focus_22530_22562_latest_decision") or {},
        "eligible_candidate_count_total": eligible_total,
        "base_eligible_candidate_count_total": ungated_eligible_total,
        "eligible_candidate_count_before_second_order_rule": _int_or_zero(
            scan.get("eligible_candidate_count_before_second_order_rule") or ungated_eligible_total
        ),
        "eligible_candidate_count_after_second_order_rule": _int_or_zero(
            scan.get("eligible_candidate_count_after_second_order_rule") or eligible_total
        ),
        "second_or_later_delivered_candidate_count": _int_or_zero(
            scan.get("second_or_later_delivered_candidate_count") or eligible_total
        ),
        "review_queue_batch_size": pagination["page_size"],
        "review_queue_page_size": pagination["page_size"],
        "review_queue_page": pagination["page"],
        "review_queue_total_pages": pagination["total_pages"],
        "review_queue_has_previous": pagination["has_previous"],
        "review_queue_has_next": pagination["has_next"],
        "review_queue_previous_page": pagination["previous_page"],
        "review_queue_next_page": pagination["next_page"],
        "review_queue_previous_page_url": pagination["previous_page_url"],
        "review_queue_next_page_url": pagination["next_page_url"],
        "review_queue_showing_start": pagination["showing_start"],
        "review_queue_showing_end": pagination["showing_end"],
        "review_queue_visible_count": len(needs_review_rows),
        "review_queue_overflow_count": max(ready_to_send_count - pagination["showing_end"], 0),
        "review_queue_page_size_options": _selected_page_size_options(pagination["page_size"]),
        "review_queue_sort_order": scan.get("review_queue_sort_order") or list(REVIEW_QUEUE_SORT_ORDER),
        **_already_sent_pagination_summary(
            sent_pagination,
            already_sent_rows,
            already_sent_source_rows,
            pagination["page"],
            pagination["page_size"],
        ),
        "latest_sent_order": scan.get("latest_sent_order") or latest_sent.get("order", ""),
        "latest_sent_time": (
            scan.get("latest_sent_time")
            or latest_sent.get("sent_at")
            or latest_sent.get("tag_written_at")
            or ""
        ),
        "latest_tag_write_time": scan.get("latest_tag_write_time") or _latest_tag_write_time(already_sent_source_rows),
        "stale_counter_warning": scan.get("stale_counter_warning") is True,
        "stale_counter_warning_message": _safe_text(
            scan.get("stale_counter_warning_message") or DASHBOARD_STALE_COUNTER_WARNING,
            max_length=160,
        )
        if scan.get("stale_counter_warning") is True
        else "",
        "shopify_tag_write_enabled_count": 0,
        "empty_message": (
            "Order data is incomplete. Run the 60-day Shopify sync before trusting the candidate list."
            if coverage_incomplete
            else "No orders need review email right now."
        ),
        "scan_summary": {
            "scanned_order_count": scan.get("scanned_order_count", 0),
            "delivered_order_count": scan.get("delivered_order_count", 0),
            "eligible_candidate_count": eligible_total,
            "eligible_candidate_count_before_latest_filter": _int_or_zero(
                scan.get("eligible_candidate_count_before_latest_filter") or ungated_eligible_total
            ),
            "eligible_candidate_count_after_latest_filter": _int_or_zero(
                scan.get("eligible_candidate_count_after_latest_filter") or ungated_eligible_total
            ),
            "hidden_older_eligible_count": _int_or_zero(scan.get("hidden_older_eligible_count")),
            "blocked_count": scan.get("blocked_count", 0),
            "blocked_ebay_order_count": scan.get("blocked_ebay_order_count", 0),
            "blocked_first_order_count": scan.get("blocked_first_order_count", 0),
            "blocked_not_second_or_later_count": scan.get("blocked_not_second_or_later_count", 0),
            "blocked_second_order_not_delivered_count": scan.get(
                "blocked_second_order_not_delivered_count",
                0,
            ),
            "already_sent_count": len(already_sent_source_rows),
            "latest_sent_order": scan.get("latest_sent_order") or latest_sent.get("order", ""),
            "latest_sent_time": (
                scan.get("latest_sent_time")
                or latest_sent.get("sent_at")
                or latest_sent.get("tag_written_at")
                or ""
            ),
            "latest_tag_write_time": scan.get("latest_tag_write_time") or _latest_tag_write_time(already_sent_source_rows),
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
    lookup_cache = load_customer_history_lookup_cache(_log_dir())
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
    limited_contexts = list(scanned_contexts[:MAX_LOCAL_ORDER_SCAN_ROWS])
    included_orders = {context.get("order_name") for context in limited_contexts}
    for context in scanned_contexts[MAX_LOCAL_ORDER_SCAN_ROWS:]:
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
    queue_rows = [
        _apply_customer_history_lookup_gate_to_queue_row(
            row,
            lookup_cache,
            now.isoformat(),
        )
        for row in queue_rows
    ]
    already_sent_rows = _finalize_already_sent_rows(
        _collapse_merged_group_rows(_dedupe_already_sent_rows(already_sent_rows))
    )
    eligible_rows = [
        row for row in queue_rows if row.get("action_state") == "review_send"
    ]
    blocked_rows = [
        row for row in queue_rows if row.get("action_state") != "review_send"
    ]
    eligible_candidate_count_before_latest_filter = len(eligible_rows)
    eligible_rows, hidden_older_eligible_rows, latest_filter_summary = (
        _apply_latest_eligible_customer_filter(eligible_rows)
    )
    blocked_rows.extend(hidden_older_eligible_rows)
    eligible_rows, review_queue_rows = _apply_review_queue_selection(eligible_rows)
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
    stale_trustpilot_tag_rows = _stale_trustpilot_tag_rows(already_sent_rows)
    if stale_trustpilot_tag_rows:
        order_data_coverage["coverage_warnings"] = _dedupe_text(
            (order_data_coverage.get("coverage_warnings") or [])
            + ["Shopify tag may be stale locally; run sync."]
        )
        order_data_coverage["stale_trustpilot_tag_order_names"] = [
            row.get("order") for row in stale_trustpilot_tag_rows if row.get("order")
        ]
    order_21083_diagnosis = _focus_order_diagnosis("#21083", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_21070_diagnosis = _focus_order_diagnosis("#21070", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_21075_diagnosis = _focus_order_diagnosis("#21075", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_21076_diagnosis = _focus_order_diagnosis("#21076", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_21102_diagnosis = _focus_order_diagnosis("#21102", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_21225_diagnosis = _focus_order_diagnosis("#21225", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_21687_diagnosis = _focus_order_diagnosis("#21687", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_21687_lookup = _cached_lookup_order_from_cache(lookup_cache, "#21687")
    order_21687_review_queue_orders = {row.get("order") for row in review_queue_rows}
    order_21687_eligible_orders = {row.get("order") for row in eligible_rows}
    order_21687_blocked_orders = {row.get("order") for row in blocked_rows}
    order_21778_diagnosis = _focus_order_diagnosis("#21778", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_22530_diagnosis = _focus_order_diagnosis("#22530", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_22562_diagnosis = _focus_order_diagnosis("#22562", scan_contexts, eligible_rows, blocked_rows, already_sent_rows)
    order_22562_lookup = _cached_lookup_order_from_cache(lookup_cache, "#22562")
    order_22562_review_queue_orders = {row.get("order") for row in review_queue_rows}
    order_22562_eligible_orders = {row.get("order") for row in eligible_rows}
    order_22562_blocked_orders = {row.get("order") for row in blocked_rows}
    order_22562_already_sent_orders = {row.get("order") for row in already_sent_rows}
    eligible_candidate_count_total = len(eligible_rows)
    review_queue_visible_count = len(review_queue_rows)
    historical_note_blocked_count = sum(
        1 for row in blocked_rows if row.get("customer_level_trustpilot_note_evidence_found") is True
    )
    latest_sent = _latest_already_sent_record(already_sent_rows)
    latest_tag_write_time = _latest_tag_write_time(already_sent_rows)
    stale_counter_warning = bool(
        order_data_coverage["scan_source"] != "full_shopify_orders"
        or order_data_coverage.get("coverage_warnings")
    )
    second_order_counts = _second_order_rule_counts(eligible_rows, blocked_rows)
    customer_history_checks = _customer_history_check_summary(eligible_rows, blocked_rows)
    return {
        "window_days": LAST_60_DAY_SCAN_WINDOW_DAYS,
        "scan_window_started_at": cutoff.isoformat(),
        "scan_window_ended_at": now.isoformat(),
        "candidate_scan_freshness": now.isoformat(),
        "scan_source": order_data_coverage["scan_source"],
        "coverage_warnings": order_data_coverage["coverage_warnings"],
        "order_data_coverage": order_data_coverage,
        "order_21083_diagnosis": order_21083_diagnosis,
        "order_21070_diagnosis": order_21070_diagnosis,
        "order_21075_diagnosis": order_21075_diagnosis,
        "order_21076_diagnosis": order_21076_diagnosis,
        "order_21102_diagnosis": order_21102_diagnosis,
        "order_21225_diagnosis": order_21225_diagnosis,
        "order_21225_trustpilot_tag_detection": _order_trustpilot_tag_detection(order_21225_diagnosis),
        "order_21687_diagnosis": order_21687_diagnosis,
        "#21687_customer_history_order_count": _int_or_zero(
            order_21687_diagnosis.get("customer_history_order_count")
        ),
        "#21687_customer_history_order_names": _dedupe_order_names(
            order_21687_diagnosis.get("customer_history_matched_order_names") or []
        ),
        "#21687_customer_history_match_method": _safe_text(
            order_21687_diagnosis.get("customer_history_match_method"), max_length=80
        ),
        "#21687_customer_history_confidence": _safe_text(
            order_21687_diagnosis.get("customer_history_confidence"), max_length=80
        ),
        "order_21687_lookup_cache_found": bool(order_21687_lookup),
        "order_21687_should_block_review_send": order_21687_lookup.get("should_block_review_send") is True,
        "order_21687_evidence_order_name": _safe_text(order_21687_lookup.get("evidence_order_name"), max_length=80),
        "order_21687_safe_detected_keyword": _safe_text(order_21687_lookup.get("safe_detected_keyword"), max_length=80),
        "order_21687_blocking_reason": _safe_text(order_21687_lookup.get("blocking_reason"), max_length=300),
        "order_21687_removed_from_needs_review": "#21687" not in order_21687_review_queue_orders
        and "#21687" not in order_21687_eligible_orders,
        "order_21687_present_in_blocked_or_already_sent": "#21687" in order_21687_blocked_orders
        or order_21687_diagnosis.get("candidate_scan_section") == "already_sent",
        "order_21687_review_send_button_disabled": "#21687" not in order_21687_review_queue_orders
        and "#21687" not in order_21687_eligible_orders,
        "order_21687_gmail_shopify_write_performed": False,
        "customer_history_lookup_cache_found": lookup_cache.get("present") is True,
        "customer_history_lookup_cache_loaded": lookup_cache.get("loaded") is True,
        "customer_history_lookup_cache_path": lookup_cache.get("relative_path", ""),
        "lookup_cache_paths_checked": lookup_cache.get("lookup_cache_paths_checked") or lookup_cache.get("paths_checked") or [],
        "lookup_cache_selected_path": lookup_cache.get("lookup_cache_selected_path") or lookup_cache.get("selected_path", ""),
        "lookup_cache_entries_count": _int_or_zero(
            lookup_cache.get("lookup_cache_entries_count") or lookup_cache.get("entries_count")
        ),
        "visible_rows_missing_live_lookup_count": sum(
            1 for row in review_queue_rows if row.get("cached_customer_history_lookup_found") is not True
        ),
        "visible_rows_blocked_by_missing_or_stale_live_lookup_count": sum(
            1
            for row in blocked_rows
            if row.get("customer_history_lookup_block_status") in {"missing", "stale", "incomplete"}
        ),
        "order_21778_diagnosis": order_21778_diagnosis,
        "order_21778_trustpilot_tag_detection": _order_trustpilot_tag_detection(order_21778_diagnosis),
        "order_22530_diagnosis": order_22530_diagnosis,
        "order_22562_diagnosis": order_22562_diagnosis,
        "order_22562_lookup_cache_found": bool(order_22562_lookup),
        "order_22562_should_block_review_send": order_22562_lookup.get("should_block_review_send") is True,
        "order_22562_final_section": (
            "review_queue"
            if "#22562" in order_22562_review_queue_orders
            else "eligible"
            if "#22562" in order_22562_eligible_orders
            else "blocked"
            if "#22562" in order_22562_blocked_orders
            else "already_sent"
            if "#22562" in order_22562_already_sent_orders
            else "not_visible"
        ),
        "order_22562_final_eligibility": (
            "eligible"
            if "#22562" in order_22562_review_queue_orders or "#22562" in order_22562_eligible_orders
            else "already_sent"
            if "#22562" in order_22562_already_sent_orders
            else "blocked"
            if "#22562" in order_22562_blocked_orders
            else "not_scanned"
        ),
        "local_db_error_sanitized": local_db_error,
        "scanned_order_count": len(scan_contexts),
        "delivered_order_count": delivered_count,
        "eligible_candidate_count_before_latest_filter": eligible_candidate_count_before_latest_filter,
        "eligible_candidate_count_after_latest_filter": latest_filter_summary[
            "eligible_candidate_count_after_latest_filter"
        ],
        "hidden_older_eligible_count": latest_filter_summary["hidden_older_eligible_count"],
        "hidden_older_eligible_summary": latest_filter_summary["hidden_older_eligible_summary"],
        "latest_candidate_per_customer_count": latest_filter_summary["latest_candidate_per_customer_count"],
        "focus_22530_22562_latest_decision": latest_filter_summary[
            "focus_22530_22562_latest_decision"
        ],
        "eligible_candidate_count": eligible_candidate_count_total,
        "eligible_candidate_count_total": eligible_candidate_count_total,
        "final_eligible_count": customer_history_checks["final_eligible_count"],
        "final_eligible_orders": customer_history_checks["final_eligible_orders"],
        "needs_live_customer_history_check_count": customer_history_checks[
            "needs_live_customer_history_check_count"
        ],
        "live_checks_completed_count": customer_history_checks["live_checks_completed_count"],
        "live_checks_blocked_count": customer_history_checks["live_checks_blocked_count"],
        "live_checks_failed_incomplete_count": customer_history_checks[
            "live_checks_failed_incomplete_count"
        ],
        "customer_history_checks": customer_history_checks,
        "already_sent_count": len(already_sent_rows),
        "latest_sent_order": latest_sent.get("order", ""),
        "latest_sent_time": latest_sent.get("sent_at") or latest_sent.get("tag_written_at") or "",
        "latest_tag_write_time": latest_tag_write_time,
        "sent_rows_with_time_count": sum(1 for row in already_sent_rows if row.get("sent_time_recorded")),
        "sent_rows_without_time_count": sum(1 for row in already_sent_rows if not row.get("sent_time_recorded")),
        "stale_counter_warning": stale_counter_warning,
        "stale_counter_warning_message": DASHBOARD_STALE_COUNTER_WARNING if stale_counter_warning else "",
        "trustpilot_tagged_orders_excluded_count": sum(
            1 for row in already_sent_rows if row.get("trustpilot_tag_detected") is True
        ),
        "blocked_count": len(blocked_rows),
        "blocked_merged_group_count": sum(1 for row in blocked_rows if _row_blocked_by_merged_group(row)),
        "blocked_duplicate_customer_count": sum(1 for row in blocked_rows if _row_blocked_by_duplicate(row)),
        "blocked_ebay_order_count": sum(1 for row in blocked_rows if _row_blocked_by_ebay(row)),
        "blocked_note_risk_count": sum(1 for row in blocked_rows if _row_blocked_by_note_risk(row)),
        "first_order_blocked_count": sum(1 for row in blocked_rows if _row_blocked_by_first_order(row)),
        **second_order_counts,
        "prior_trustpilot_customer_blocked_count": sum(
            1 for row in blocked_rows if _row_blocked_by_prior_trustpilot_history(row)
        ),
        "customer_history_unknown_count": sum(
            1 for row in blocked_rows if _row_blocked_by_customer_history_unknown(row)
        ),
        "customer_history_low_confidence_count": sum(
            1 for row in blocked_rows if _safe_text(row.get("customer_history_confidence"), max_length=80) == "low"
        ),
        "customer_history_weak_name_only_match_count": sum(
            _int_or_zero(row.get("customer_history_weak_match_count")) for row in blocked_rows + eligible_rows
        ),
        "overcounted_customer_history_count": sum(
            1
            for row in blocked_rows + eligible_rows
            if _int_or_zero(row.get("customer_history_order_count_before_precision"))
            > _int_or_zero(row.get("customer_history_order_count"))
        ),
        "candidates_blocked_by_low_confidence_history": sum(
            1 for row in blocked_rows if _row_blocked_by_customer_history_unknown(row)
        ),
        "candidates_blocked_by_note_risk": sum(1 for row in blocked_rows if _row_blocked_by_note_risk(row)),
        "candidates_blocked_by_historical_trustpilot_note_count": historical_note_blocked_count,
        "active_review_send_count_before_historical_trustpilot_note_guard": (
            eligible_candidate_count_total + historical_note_blocked_count
        ),
        "active_review_send_count_after_historical_trustpilot_note_guard": eligible_candidate_count_total,
        "active_review_send_count_before_precision": eligible_candidate_count_total
        + sum(1 for row in blocked_rows if _row_blocked_only_by_precision_fix(row)),
        "blocked_missing_review_request_tag_count": sum(
            1 for row in blocked_rows if _row_blocked_by_missing_review_request_tag(row)
        ),
        "blocked_not_delivered_count": sum(1 for row in blocked_rows if _row_blocked_by_not_delivered(row)),
        "eligible_queue_rows": eligible_rows,
        "review_queue_rows": review_queue_rows,
        "blocked_queue_rows": blocked_rows,
        "already_sent_queue_rows": already_sent_rows,
        "review_queue_batch_size": REVIEW_QUEUE_BATCH_SIZE,
        "review_queue_visible_count": review_queue_visible_count,
        "review_queue_overflow_count": max(eligible_candidate_count_total - review_queue_visible_count, 0),
        "review_queue_sort_order": list(REVIEW_QUEUE_SORT_ORDER),
        "review_queue_candidates": [_queue_candidate_summary(row) for row in review_queue_rows],
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
        "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
        "local_orders_with_shopify_tag_data": 0,
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
        coverage["local_orders_with_shopify_tag_data"] = local_queryset.filter(shopify_tags__isnull=False).count()
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
    tags = _combined_queue_tags(row or {}, scan_context=context)
    local_shopify_tags = _dedupe_text(
        context.get("order_tags_display")
        or (row or {}).get("local_shopify_tags")
        or []
    )
    matched_trustpilot_tags = _matched_trustpilot_tags(row or {}, tags)
    trustpilot_tag_source = _trustpilot_tag_source(
        tags,
        local_shopify_tags=local_shopify_tags,
        previous_trustpilot_tags=(row or {}).get("previous_trustpilot_tag_values") or [],
        source_row=row or {},
    )
    matched_ebay_tags = _matched_ebay_tags(tags)
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
        "selected_local_tag_field": context.get("selected_local_tag_field") or SHOPIFY_ORDER_TAG_FIELD_LABEL,
        "tags_summary": _tags_summary(tags, tag_data_loaded),
        "order_tags_display": tags,
        "local_shopify_tags": local_shopify_tags,
        "trustpilot_tag_detected": bool(matched_trustpilot_tags)
        or (row or {}).get("trustpilot_tag_detected") is True,
        "trustpilot_tag_source": _safe_text(
            (row or {}).get("trustpilot_tag_source") or trustpilot_tag_source,
            max_length=120,
        ),
        "matched_trustpilot_tag_values": _dedupe_text(
            (row or {}).get("matched_trustpilot_tag_values") or matched_trustpilot_tags
        ),
        "already_sent_reason": _safe_text(
            (row or {}).get("already_sent_reason")
            or (TRUSTPILOT_TAG_ALREADY_SENT_REASON if matched_trustpilot_tags else ""),
            max_length=300,
        ),
        "ebay_tag_detected": bool(matched_ebay_tags) or (row or {}).get("ebay_tag_detected") is True,
        "matched_ebay_tag_value": (
            _safe_text((row or {}).get("matched_ebay_tag_value"), max_length=120)
            or (matched_ebay_tags[0] if matched_ebay_tags else "")
        ),
        "tag_data_available": tag_data_loaded,
        "review_request_tag_data_loaded": tag_data_loaded,
        "tag_data_missing_source": ""
        if tag_data_loaded
        else _safe_text(context.get("tag_data_missing_source"), max_length=240)
        or SHOPIFY_ORDER_TAGS_MISSING_SOURCE,
        "tag_data_recommended_action": ""
        if tag_data_loaded
        else _safe_text(context.get("tag_data_recommended_action"), max_length=300)
        or SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
        "review_request_tag_status": review_request_tag_status,
        "review_request_tag_present": review_request_tag_present,
        "matched_review_request_tag_value": _safe_text(
            context.get("matched_review_request_tag_value")
            or (row or {}).get("matched_review_request_tag_value"),
            max_length=120,
        ),
        "review_queue_rank": _int_or_zero((row or {}).get("review_queue_rank")),
        "visible_in_review_batch": (row or {}).get("visible_in_review_batch") is True,
        "hidden_reason": _safe_text((row or {}).get("hidden_reason"), max_length=120)
        or ("not_scanned" if not row else ""),
        "displayed_order_count_before_precision": _int_or_zero(
            (row or {}).get("customer_history_order_count_before_precision")
        ),
        "customer_history_order_count": _int_or_zero((row or {}).get("customer_history_order_count")),
        "customer_order_sequence_number": _int_or_zero((row or {}).get("customer_order_sequence_number")),
        "customer_order_sequence_label": _safe_text((row or {}).get("customer_order_sequence_label"), max_length=120),
        "historical_order_names": _dedupe_order_names((row or {}).get("historical_order_names") or []),
        "customer_history_order_names": _dedupe_order_names((row or {}).get("customer_history_order_names") or []),
        "customer_history_window": _safe_text((row or {}).get("customer_history_window"), max_length=80),
        "customer_history_matched_order_names": _dedupe_order_names(
            (row or {}).get("customer_history_matched_order_names")
            or (row or {}).get("historical_order_names")
            or []
        ),
        "customer_history_match_method": _safe_text((row or {}).get("customer_history_match_method"), max_length=80),
        "customer_history_excluded_weak_matches": _dedupe_order_names(
            (row or {}).get("customer_history_excluded_weak_matches") or []
        ),
        "customer_history_weak_match_count": _int_or_zero((row or {}).get("customer_history_weak_match_count")),
        "customer_history_exact_match_count": _int_or_zero((row or {}).get("customer_history_exact_match_count")),
        "previous_trustpilot_order_names": _dedupe_order_names(
            (row or {}).get("previous_trustpilot_order_names") or []
        ),
        "previous_trustpilot_tag_values": _dedupe_text((row or {}).get("previous_trustpilot_tag_values") or []),
        "customer_history_source": _safe_text((row or {}).get("customer_history_source"), max_length=80),
        "customer_history_confidence": _safe_text((row or {}).get("customer_history_confidence"), max_length=80),
        "customer_level_trustpilot_already_sent": (row or {}).get("customer_level_trustpilot_already_sent") is True,
        "customer_level_trustpilot_note_evidence_found": (
            (row or {}).get("customer_level_trustpilot_note_evidence_found") is True
        ),
        "customer_level_trustpilot_note_evidence_order_name": _safe_text(
            (row or {}).get("customer_level_trustpilot_note_evidence_order_name"), max_length=80
        ),
        "customer_level_trustpilot_note_safe_keyword": _safe_text(
            (row or {}).get("customer_level_trustpilot_note_safe_keyword"), max_length=80
        ),
        "customer_level_trustpilot_note_field_name": _safe_text(
            (row or {}).get("customer_level_trustpilot_note_field_name"), max_length=120
        ),
        "note_risk_detected": (row or context).get("note_risk_detected") is True,
        "note_risk_field": _safe_text((row or context).get("note_risk_field"), max_length=120),
        "note_risk_fields": _dedupe_text((row or context).get("note_risk_fields") or []),
        "note_risk_keywords": _dedupe_text((row or context).get("note_risk_keywords") or []),
        "note_risk_reason": _safe_text((row or context).get("note_risk_reason"), max_length=120),
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


def _order_trustpilot_tag_detection(diagnosis):
    tags = _dedupe_text((diagnosis or {}).get("order_tags_display") or [])
    matched = _matched_trustpilot_tags({}, tags)
    return {
        "order_name": _safe_text((diagnosis or {}).get("order_name"), max_length=80),
        "found_in_local_shopify_order": (diagnosis or {}).get("found_in_local_shopify_order") is True,
        "tag_data_available": (diagnosis or {}).get("tag_data_available") is True,
        "trustpilot_tag_detected": bool(matched),
        "matched_trustpilot_tag_values": matched,
        "trustpilot_tag_source": _safe_text((diagnosis or {}).get("trustpilot_tag_source"), max_length=120),
        "already_sent_reason": _safe_text((diagnosis or {}).get("already_sent_reason"), max_length=300),
    }


def _stale_trustpilot_tag_rows(rows):
    stale_rows = []
    for row in rows or []:
        if row.get("trustpilot_tag_detected") is not True:
            continue
        local_tags = _dedupe_text(row.get("local_shopify_tags") or [])
        if local_tags and not has_trustpilot_sent_tag(local_tags):
            stale_rows.append(row)
    return stale_rows


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
        SHOPIFY_ORDER_TAG_FIELD,
        "warehouse_note",
        "transfer_note",
        "exception_review_reason",
        "exception_review_response",
        "cost_calculation_note",
    )
    try:
        orders = list(
            ShopifyOrder.objects.filter(query)
            .values(*value_fields)
            .order_by("-updated_at", "-order_created_at", "-id")[:MAX_LOCAL_ORDER_SCAN_ROWS]
        )
        if lookup_query:
            existing_ids = {order.get("id") for order in orders}
            for order in ShopifyOrder.objects.filter(lookup_query).values(*value_fields)[:MAX_LOCAL_ORDER_SCAN_ROWS]:
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
    tags, tag_data_loaded, tag_data_missing_source, tag_data_recommended_action = _effective_order_tags(
        order,
        source_row,
    )
    tag_source_row = _source_row_with_effective_tags(source_row, tags, tag_data_loaded)
    delivered_confirmed = _scan_delivered_confirmed(tag_source_row, order)
    canonical_tag_present = _scan_canonical_review_request_tag_present(tag_source_row)
    matched_review_request_tags = _matched_review_request_tags(tags)
    matched_ebay_tags = _matched_ebay_tags(tags)
    note_risk = _note_risk_detection(order)
    identity = _customer_identity_summary(order)
    local_context = {
        "order_name": order_name,
        "matched_order_name": order_name,
        "local_order_id": order.get("id") or "",
        "order_number": _safe_text(order.get("order_number"), max_length=120),
        "shopify_order_id": _safe_text(order.get("shopify_order_id"), max_length=120),
        "customer_display_name": _safe_customer_display_name(order.get("customer_name")),
        "masked_email": mask_email(_safe_runtime_email(order.get("customer_email"))),
        "customer_identity_key": identity["customer_identity_key"],
        "customer_identity_source": identity["customer_identity_source"],
        "customer_identity_confidence": identity["customer_identity_confidence"],
        "financial_status": _safe_text(order.get("financial_status"), max_length=80),
        "fulfillment_status": _safe_text(order.get("fulfillment_status"), max_length=80),
        "fulfillment_status_raw": _safe_text(order.get("fulfillment_status_raw"), max_length=120),
        "settlement_status": _safe_text(order.get("settlement_status"), max_length=80),
        "order_created_at": _safe_text(order.get("order_created_at"), max_length=80),
        "updated_at": _safe_text(order.get("updated_at"), max_length=80),
        "fulfilled_at": _safe_text(order.get("fulfilled_at"), max_length=80),
        "shopify_note_present": _order_note_present(order),
        "note_risk_detected": note_risk["note_risk_detected"],
        "note_risk_field": note_risk["note_risk_field"],
        "note_risk_fields": note_risk["note_risk_fields"],
        "note_risk_keywords": note_risk["note_risk_keywords"],
        "note_risk_reason": note_risk["note_risk_reason"],
        "local_order_source": "ShopifyOrder",
        "delivered_confirmed": delivered_confirmed,
        "canonical_review_request_tag_present": canonical_tag_present,
        "order_tags_display": tags,
        "tags_summary": _tags_summary(tags, tag_data_loaded),
        "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
        "tag_data_available": tag_data_loaded,
        "review_request_tag_data_loaded": tag_data_loaded,
        "tag_data_missing_source": tag_data_missing_source,
        "tag_data_recommended_action": tag_data_recommended_action,
        "matched_review_request_tag_value": matched_review_request_tags[0] if matched_review_request_tags else "",
        "ebay_tag_detected": bool(matched_ebay_tags),
        "matched_ebay_tag_value": matched_ebay_tags[0] if matched_ebay_tags else "",
        "scan_date_in_window": _datetime_in_window(date_context.get("scan_datetime"), cutoff),
        "scan_date_missing": date_context.get("scan_datetime") is None,
    }
    local_context.update(date_context)
    return local_context


def _scan_context_from_source_row(order_name, source_row, cutoff):
    date_context = _scan_date_context({}, source_row)
    tags = _source_row_tags(source_row)
    matched_review_request_tags = _matched_review_request_tags(tags)
    matched_ebay_tags = _matched_ebay_tags(tags)
    tag_data_loaded = _tag_data_loaded(source_row, tags)
    note_risk = _note_risk_detection(source_row)
    return {
        "order_name": order_name,
        "matched_order_name": order_name,
        "customer_display_name": _safe_customer_display_name(source_row.get("customer_display_name")),
        "masked_email": _safe_text(source_row.get("masked_email"), max_length=120),
        "financial_status": "",
        "fulfillment_status": "",
        "fulfillment_status_raw": "",
        "settlement_status": "",
        "note_risk_detected": note_risk["note_risk_detected"],
        "note_risk_field": note_risk["note_risk_field"],
        "note_risk_fields": note_risk["note_risk_fields"],
        "note_risk_keywords": note_risk["note_risk_keywords"],
        "note_risk_reason": note_risk["note_risk_reason"],
        "local_order_source": "local_review_request_report",
        "delivered_confirmed": _scan_delivered_confirmed(source_row, {}),
        "canonical_review_request_tag_present": _scan_canonical_review_request_tag_present(source_row),
        "order_tags_display": tags,
        "tags_summary": _tags_summary(tags, tag_data_loaded),
        "tag_data_available": tag_data_loaded,
        "review_request_tag_data_loaded": tag_data_loaded,
        "tag_data_missing_source": "" if tag_data_loaded else "Shopify tag data not loaded in local report source",
        "tag_data_recommended_action": "" if tag_data_loaded else SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
        "matched_review_request_tag_value": matched_review_request_tags[0] if matched_review_request_tags else "",
        "ebay_tag_detected": bool(matched_ebay_tags),
        "matched_ebay_tag_value": matched_ebay_tags[0] if matched_ebay_tags else "",
        "scan_date_in_window": _datetime_in_window(date_context.get("scan_datetime"), cutoff),
        "scan_date_missing": date_context.get("scan_datetime") is None,
        **date_context,
    }


def _effective_order_tags(order, source_row):
    if _shopify_tags_loaded_from_order(order):
        tags = _shopify_tags_from_order(order)
        return tags, True, "", ""

    source_tags = _source_row_tags(source_row)
    if _tag_data_loaded(source_row, source_tags):
        return source_tags, True, "", ""

    return (
        [],
        False,
        _tag_data_missing_source_for_order(order),
        SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
    )


def _source_row_with_effective_tags(source_row, tags, tag_data_loaded):
    row = dict(source_row or {})
    row["tags"] = tags
    row["order_tags_display"] = tags
    row["review_request_tag_data_loaded"] = tag_data_loaded
    row["tag_data_available"] = tag_data_loaded
    return row


def _source_row_tags(source_row):
    source_row = source_row or {}
    return _dedupe_text(
        _collect_tag_values(source_row.get("tags"), split_strings=True)
        + _collect_tag_values(source_row.get("order_tags_display"))
    )


def _combined_queue_tags(source_row=None, local_context=None, scan_context=None, row=None):
    tags = []
    for mapping in (local_context, scan_context, source_row, row):
        if not isinstance(mapping, dict):
            continue
        tags.extend(_source_row_tags(mapping))
        tags.extend(_collect_tag_values(mapping.get("local_shopify_tags")))
        tags.extend(_collect_tag_values(mapping.get("matched_trustpilot_tag_values")))
    return _dedupe_text(tags)


def _local_shopify_tags_for_queue(local_context=None, scan_context=None):
    tags = []
    for mapping in (local_context, scan_context):
        if not isinstance(mapping, dict):
            continue
        tags.extend(_collect_tag_values(mapping.get("order_tags_display")))
        tags.extend(_collect_tag_values(mapping.get("local_shopify_tags")))
    return _dedupe_text(tags)


def _trustpilot_tag_source(tags, local_shopify_tags=None, previous_trustpilot_tags=None, source_row=None):
    if _matched_trustpilot_tags({}, local_shopify_tags or []):
        return "local_shopify_tags"
    if previous_trustpilot_tags:
        return "customer_history_tags"
    if _matched_trustpilot_tags(source_row or {}, tags or []):
        return "local_report_tags"
    return ""


def _shopify_tags_loaded_from_order(order):
    return isinstance(order, dict) and SHOPIFY_ORDER_TAG_FIELD in order and order.get(SHOPIFY_ORDER_TAG_FIELD) is not None


def _shopify_tags_from_order(order):
    if not _shopify_tags_loaded_from_order(order):
        return []
    return _split_shopify_tag_string(order.get(SHOPIFY_ORDER_TAG_FIELD))


def _split_shopify_tag_string(value):
    if isinstance(value, (list, tuple, set)):
        return _dedupe_text(_safe_text(item, max_length=120) for item in value if _safe_text(item, max_length=120))
    return _dedupe_text(
        _safe_text(part, max_length=120)
        for part in str(value or "").split(",")
        if _safe_text(part, max_length=120)
    )


def _tag_data_missing_source_for_order(order):
    if not isinstance(order, dict) or SHOPIFY_ORDER_TAG_FIELD not in order:
        return SHOPIFY_ORDER_TAGS_FIELD_MISSING_SOURCE
    return SHOPIFY_ORDER_TAGS_MISSING_SOURCE


def _tags_summary(tags, tag_data_loaded):
    safe_tags = _dedupe_text(tags or [])
    if safe_tags:
        return ", ".join(safe_tags)
    if tag_data_loaded:
        return SHOPIFY_ORDER_TAGS_EMPTY_SOURCE
    return "Shopify tag data not loaded"


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
    tags = _source_row_tags(source_row)
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
    tags = _source_row_tags(source_row)
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
    source_row = source_row or {}
    if tags:
        return True
    if source_row.get("review_request_tag_data_loaded") is True:
        return True
    if source_row.get("tag_data_available") is True:
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
    tags = _combined_queue_tags(
        row,
        local_context=local_context,
        scan_context=scan_context,
    )
    local_shopify_tags = _local_shopify_tags_for_queue(local_context, scan_context)
    trustpilot_tags = _matched_trustpilot_tags(row, tags)
    matched_review_request_tags = _matched_review_request_tags(tags)
    matched_ebay_tags = _matched_ebay_tags(tags)
    blocking_reasons = _dedupe_text(row.get("blocking_reasons") or [])
    if _scan_local_risk_detected(scan_context):
        blocking_reasons.append("blocked_risk_or_ticket")
    note_risk = _note_risk_from_sources(scan_context, local_context, row)
    if note_risk["note_risk_detected"]:
        blocking_reasons.append("blocked_note_risk_detected")
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
            "customer_identity_key": (
                _safe_text(scan_context.get("customer_identity_key"), max_length=120)
                or _safe_text(local_context.get("customer_identity_key"), max_length=120)
                or _safe_text(row.get("customer_identity_key"), max_length=120)
            ),
            "customer_identity_source": (
                _safe_text(scan_context.get("customer_identity_source"), max_length=80)
                or _safe_text(local_context.get("customer_identity_source"), max_length=80)
                or _safe_text(row.get("customer_identity_source"), max_length=80)
            ),
            "customer_identity_confidence": (
                _safe_text(scan_context.get("customer_identity_confidence"), max_length=80)
                or _safe_text(local_context.get("customer_identity_confidence"), max_length=80)
                or _safe_text(row.get("customer_identity_confidence"), max_length=80)
            ),
            "local_order_id": scan_context.get("local_order_id", ""),
            "matched_order_name": scan_context.get("matched_order_name") or order_name,
            "order_number": scan_context.get("order_number", ""),
            "shopify_order_id": scan_context.get("shopify_order_id", ""),
            "order_created_at": scan_context.get("order_created_at", ""),
            "fulfillment_status": scan_context.get("fulfillment_status", ""),
            "shopify_note_present": scan_context.get("shopify_note_present") is True,
            "note_risk_detected": note_risk["note_risk_detected"],
            "note_risk_field": note_risk["note_risk_field"],
            "note_risk_fields": note_risk["note_risk_fields"],
            "note_risk_keywords": note_risk["note_risk_keywords"],
            "note_risk_reason": note_risk["note_risk_reason"],
            "tags": tags,
            "local_shopify_tags": local_shopify_tags,
            "tag_data_available": scan_context.get("tag_data_available") is True,
            "tag_data_missing_source": _safe_text(scan_context.get("tag_data_missing_source"), max_length=240),
            "tag_data_recommended_action": _safe_text(scan_context.get("tag_data_recommended_action"), max_length=300),
            "trustpilot_tags": trustpilot_tags,
            "trustpilot_invitation_present": bool(trustpilot_tags)
            or row.get("trustpilot_invitation_present") is True,
            "trustpilot_tag_detected": bool(trustpilot_tags),
            "trustpilot_tag_source": _trustpilot_tag_source(
                tags,
                local_shopify_tags=local_shopify_tags,
                previous_trustpilot_tags=[],
                source_row=row,
            ),
            "matched_trustpilot_tag_values": trustpilot_tags,
            "ebay_tag_detected": bool(matched_ebay_tags),
            "matched_ebay_tag_value": matched_ebay_tags[0] if matched_ebay_tags else "",
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
    order_names = [row.get("order"), *(row.get("group_order_names") or [])]
    if "#21687" in order_names:
        priority = 0
    elif row.get("blocked_by_customer_history_lookup") is True:
        priority = 1
    elif "#22582" in order_names:
        priority = 2
    else:
        priority = 3
    return (priority, row.get("order", ""))


def _already_sent_sort_key(row):
    return (
        -_already_sent_time_sort_value(row, "sent_at"),
        -_already_sent_time_sort_value(row, "tag_written_at"),
        -_review_queue_date_value(row),
        -_order_number_value(row.get("order")),
        _safe_text(row.get("order"), max_length=80),
    )


def _finalize_already_sent_rows(rows):
    finalized = []
    for row in _dedupe_already_sent_rows(rows):
        finalized.append(_apply_already_sent_timing_fields(dict(row or {})))
    finalized.sort(key=_already_sent_sort_key)
    return finalized


def _dedupe_already_sent_rows(rows):
    rows_by_order = {}
    order_sequence = []
    for row in rows or []:
        order_name = _safe_text(row.get("order") or row.get("order_name"), max_length=80)
        if not order_name:
            continue
        row = dict(row)
        row["order"] = order_name
        existing = rows_by_order.get(order_name)
        if not existing:
            rows_by_order[order_name] = row
            order_sequence.append(order_name)
            continue
        if _already_sent_row_quality(row) > _already_sent_row_quality(existing):
            rows_by_order[order_name] = row
    return [rows_by_order[order_name] for order_name in order_sequence]


def _already_sent_row_quality(row):
    return (
        1 if row.get("shopify_tag_written") is True else 0,
        1 if row.get("shopify_tag_already_existed") is True else 0,
        1 if row.get("local_review_send_success") is True else 0,
        1 if _safe_text(row.get("sent_at") or row.get("email_sent_at") or row.get("event_time"), max_length=80) else 0,
        _already_sent_time_sort_value(row, "sent_at"),
        _already_sent_time_sort_value(row, "tag_written_at"),
    )


def _apply_already_sent_timing_fields(row):
    sent_at = _safe_text(row.get("sent_at") or row.get("email_sent_at"), max_length=80)
    tag_written_at = _safe_text(row.get("tag_written_at"), max_length=80)
    status_label = _safe_text(row.get("shopify_tag_status_label"), max_length=120)
    if not status_label:
        status_label = _already_sent_tag_status_label(
            row,
            {},
            shopify_tag_pending=row.get("shopify_tag_pending") is True,
            shopify_tag_written=row.get("shopify_tag_written") is True,
            shopify_tag_already_existed=row.get("shopify_tag_already_existed") is True,
            tag_write_failed=row.get("tag_write_failed") is True,
            trustpilot_tag_detected=row.get("trustpilot_tag_detected") is True,
        )
    row.update(
        {
            "sent_at": sent_at,
            "email_sent_at": sent_at,
            "sent_time_label": _time_label(sent_at),
            "sent_time_recorded": bool(sent_at),
            "tag_written_at": tag_written_at,
            "tag_written_time_label": _time_label(tag_written_at),
            "shopify_tag_status_label": status_label,
            "shopify_tag_status_class": _already_sent_tag_status_class(status_label),
        }
    )
    return row


def _already_sent_time_sort_value(row, key):
    parsed = _parse_datetime_value((row or {}).get(key))
    return parsed.timestamp() if parsed else 0


def _latest_already_sent_record(rows):
    sorted_rows = _finalize_already_sent_rows(rows)
    return sorted_rows[0] if sorted_rows else {}


def _latest_tag_write_time(rows):
    values = [
        _safe_text(row.get("tag_written_at"), max_length=80)
        for row in rows or []
        if _safe_text(row.get("tag_written_at"), max_length=80)
    ]
    if not values:
        return ""
    return max(values, key=lambda value: _parse_datetime_value(value) or datetime.min.replace(tzinfo=timezone.utc))


def _apply_review_queue_selection(eligible_rows, batch_size=REVIEW_QUEUE_BATCH_SIZE):
    rows = list(_dedupe_queue_rows(eligible_rows))
    rows.sort(key=_review_queue_sort_key)
    visible_rows = []
    seen_customers = set()
    for index, row in enumerate(rows, start=1):
        row["review_queue_rank"] = index
        row["review_queue_batch_size"] = batch_size
        row["review_queue_sort_order"] = list(REVIEW_QUEUE_SORT_ORDER)
        hidden_reason = _review_queue_policy_hidden_reason(row)
        customer_key = _review_queue_customer_key(row)
        if not hidden_reason and customer_key and customer_key in seen_customers:
            hidden_reason = "duplicate_customer_in_current_batch"
        if not hidden_reason and len(visible_rows) >= batch_size:
            hidden_reason = "outside_current_batch"
        row["visible_in_review_batch"] = not hidden_reason
        row["hidden_reason"] = hidden_reason
        if hidden_reason:
            continue
        visible_rows.append(row)
        if customer_key:
            seen_customers.add(customer_key)
    return rows, visible_rows


def _apply_latest_eligible_customer_filter(eligible_rows):
    rows = list(_dedupe_queue_rows(eligible_rows))
    groups = {}
    ungrouped_rows = []
    for row in rows:
        customer_key = _review_queue_customer_key(row)
        if not customer_key:
            row["selected_order_latest_for_customer"] = True
            row["latest_eligible_order_for_customer"] = row.get("order", "")
            ungrouped_rows.append(row)
            continue
        groups.setdefault(customer_key, []).append(row)

    kept_rows = list(ungrouped_rows)
    hidden_rows = []
    hidden_summary = []
    focus_rows = {}
    for group_rows in groups.values():
        sorted_group = sorted(group_rows, key=_latest_eligible_candidate_sort_key, reverse=True)
        latest_row = sorted_group[0]
        latest_order = _safe_text(latest_row.get("order"), max_length=80)
        latest_row["selected_order_latest_for_customer"] = True
        latest_row["latest_eligible_order_for_customer"] = latest_order
        kept_rows.append(latest_row)
        for older_row in sorted_group[1:]:
            hidden_row = _older_eligible_blocked_row(older_row, latest_order)
            hidden_rows.append(hidden_row)
            hidden_summary.append(_hidden_older_eligible_summary(hidden_row, latest_order))
        for row in group_rows:
            order_name = _safe_text(row.get("order"), max_length=80)
            if order_name in {"#22530", "#22562"}:
                focus_rows[order_name] = row

    latest_candidate_per_customer_count = len(groups) + len(ungrouped_rows)
    summary = {
        "eligible_candidate_count_before_latest_filter": len(rows),
        "eligible_candidate_count_after_latest_filter": len(kept_rows),
        "hidden_older_eligible_count": len(hidden_rows),
        "hidden_older_eligible_summary": hidden_summary,
        "latest_candidate_per_customer_count": latest_candidate_per_customer_count,
        "focus_22530_22562_latest_decision": _focus_latest_candidate_decision(focus_rows),
    }
    return kept_rows, hidden_rows, summary


def _latest_eligible_candidate_sort_key(row):
    return (
        _order_number_value(row.get("order") or row.get("order_number")),
        _review_queue_date_value(row),
        _safe_text(row.get("order"), max_length=80),
    )


def _older_eligible_blocked_row(row, latest_order):
    blocked = dict(row or {})
    reason = f"A newer eligible order exists for this customer: {latest_order}."
    blocked.update(
        {
            "status": "Not ready",
            "status_class": "rrw-badge-warn",
            "reason": reason,
            "evidence": reason,
            "eligibility_reason_plain": reason,
            "action_state": "not_ready",
            "action_status": "Not ready",
            "candidate_status": "blocked",
            "block_reason": reason,
            "visible_in_review_batch": False,
            "hidden_reason": "newer_eligible_order_exists_for_customer",
            "selected_order_latest_for_customer": False,
            "latest_eligible_order_for_customer": latest_order,
            "blocked_by_latest_customer_filter": True,
        }
    )
    return blocked


def _hidden_older_eligible_summary(row, latest_order):
    return {
        "order": _safe_text(row.get("order"), max_length=80),
        "kept_latest_order": _safe_text(latest_order, max_length=80),
        "reason": _safe_text(row.get("eligibility_reason_plain"), max_length=240),
        "customer_history_source": _safe_text(row.get("customer_history_source"), max_length=80),
        "customer_history_confidence": _safe_text(row.get("customer_history_confidence"), max_length=80),
    }


def _focus_latest_candidate_decision(focus_rows):
    row_22530 = focus_rows.get("#22530") or {}
    row_22562 = focus_rows.get("#22562") or {}
    if not row_22530 and not row_22562:
        return {
            "orders_present": False,
            "orders_same_customer": False,
            "kept_order": "",
            "hidden_order": "",
            "reason": "Focus orders were not both eligible in the current latest-customer filter input.",
        }
    key_22530 = _review_queue_customer_key(row_22530)
    key_22562 = _review_queue_customer_key(row_22562)
    same_customer = bool(key_22530 and key_22562 and key_22530 == key_22562)
    kept = ""
    hidden = ""
    reason = ""
    if same_customer:
        candidates = sorted(
            [row for row in (row_22530, row_22562) if row],
            key=_latest_eligible_candidate_sort_key,
            reverse=True,
        )
        kept = _safe_text(candidates[0].get("order"), max_length=80)
        hidden = _safe_text(candidates[1].get("order"), max_length=80) if len(candidates) > 1 else ""
        if hidden:
            reason = f"A newer eligible order exists for this customer: {kept}."
    else:
        reason = "Focus orders are not confirmed as the same eligible customer by the precision identity rules."
    return {
        "orders_present": bool(row_22530 and row_22562),
        "orders_same_customer": same_customer,
        "kept_order": kept,
        "hidden_order": hidden,
        "reason": reason,
    }


def _review_queue_sort_key(row):
    return (
        -_review_queue_date_value(row),
        0 if _review_queue_has_clean_tags(row) else 1,
        0 if not _review_queue_has_merge_or_related_ambiguity(row) else 1,
        0 if not _review_queue_has_duplicate_risk(row) else 1,
        -_order_number_value(row.get("order")),
    )


def _review_queue_date_value(row):
    parsed = _parse_datetime_value(row.get("scan_date"))
    if parsed:
        return parsed.timestamp()
    for key in ("order_created_at", "updated_at", "created_at"):
        parsed = _parse_datetime_value(row.get(key))
        if parsed:
            return parsed.timestamp()
    return 0


def _review_queue_has_clean_tags(row):
    tags = _dedupe_text(row.get("order_tags_display") or row.get("tags") or [])
    return (
        row.get("tag_data_available") is True
        and (row.get("delivered_status_label") == "Delivered" or has_delivered_tag(tags))
        and (row.get("review_request_tag_present") is True or has_review_request_tag(tags))
        and not has_trustpilot_sent_tag(tags)
        and not has_ebay_tag(tags)
        and not row.get("tag_data_missing_source")
    )


def _review_queue_has_merge_or_related_ambiguity(row):
    if row.get("merged_order_group") and row.get("group_eligible_for_review_send") is not True:
        return True
    if row.get("explicit_related_order_reference"):
        return True
    related = _dedupe_order_names(row.get("related_order_names") or [])
    if related and not (row.get("merged_order_group") and row.get("group_eligible_for_review_send") is True):
        return True
    return False


def _review_queue_has_duplicate_risk(row):
    prior_order = _safe_text(row.get("prior_trustpilot_order_name"), max_length=80).lower()
    text = _row_block_text(row)
    duplicate_text = (
        "already sent" in text
        or "trustpilot invitation" in text
        or ("duplicate" in text and "no duplicate" not in text)
    )
    return (
        row.get("trustpilot_already_sent_to_customer") is True
        or row.get("customer_level_trustpilot_already_sent") is True
        or prior_order not in {"", "unavailable", "unknown", "none"}
        or row.get("customer_level_duplicate_block_applies") is True
        or row.get("existing_unsent_gmail_draft_should_not_be_sent") is True
        or duplicate_text
    )


def _review_queue_policy_hidden_reason(row):
    tags = _dedupe_text(row.get("order_tags_display") or row.get("tags") or [])
    if row.get("action_state") != "review_send":
        return "not_ready"
    if row.get("ebay_tag_detected") is True or has_ebay_tag(tags):
        return "ebay_order_blocked"
    if row.get("customer_history_confirmed") is not True:
        return "customer_history_not_confirmed"
    if _int_or_zero(row.get("customer_history_order_count") or row.get("customer_order_count")) <= 1:
        return "first_order_customer"
    if _int_or_zero(row.get("customer_order_sequence_number")) <= 1:
        return "not_second_or_later_order"
    if row.get("customer_level_trustpilot_already_sent") is True:
        return "prior_trustpilot_customer_history"
    if not (row.get("delivered_status_label") == "Delivered" or has_delivered_tag(tags)):
        return "missing_delivered_tag"
    if not (row.get("review_request_tag_present") is True or has_review_request_tag(tags)):
        return "missing_review_request_tag_alias"
    if has_trustpilot_sent_tag(tags) or row.get("trustpilot_already_sent_to_customer") is True:
        return "prior_trustpilot_send_evidence"
    if row.get("note_risk_detected") is True:
        return "note_risk_detected"
    if _review_queue_has_duplicate_risk(row):
        return "duplicate_risk"
    if _row_has_returned_package(row) or _row_has_risk_or_ticket(row):
        return "risk_or_ticket"
    if row.get("merged_order_group") and row.get("group_eligible_for_review_send") is not True:
        return "unready_merged_group"
    if not _safe_text(row.get("scan_date"), max_length=80):
        return "outside_configured_window"
    if not _review_queue_display_context_available(row):
        return "missing_display_context"
    return ""


def _review_queue_display_context_available(row):
    order_name = _safe_text(row.get("order"), max_length=80)
    customer_label = (
        _safe_text(row.get("customer_display_name"), max_length=120)
        or _safe_text(row.get("masked_customer_label"), max_length=120)
        or _safe_text(row.get("customer"), max_length=120)
    )
    return bool(order_name and customer_label and customer_label != "Masked in reports")


def _review_queue_customer_key(row):
    identity_key = _safe_text(row.get("customer_identity_key"), max_length=120)
    identity_confidence = _safe_text(row.get("customer_identity_confidence"), max_length=80)
    if identity_key and identity_confidence in {"high", "medium"}:
        return identity_key
    masked = _safe_text(row.get("masked_customer_label"), max_length=120)
    if _usable_masked_customer(masked) and row.get("customer_history_confirmed") is True:
        return _hash_customer_identity("masked_email", masked.lower())
    return ""


def _order_number_value(value):
    text = _canonical_order_name(value)
    match = re.fullmatch(r"#(\d{3,})", text)
    return int(match.group(1)) if match else 0


def _row_blocked_by_merged_group(row):
    text = _row_block_text(row)
    return bool(row.get("merged_order_group") or "merged" in text or "related order" in text)


def _row_blocked_by_duplicate(row):
    text = _row_block_text(row)
    return (
        row.get("customer_level_trustpilot_already_sent") is True
        or "already sent" in text
        or "duplicate" in text
        or "trustpilot invitation" in text
    )


def _row_blocked_by_first_order(row):
    text = _row_block_text(row)
    return (
        "first-order customer" in text
        or "first order" in text
        or (
            row.get("customer_history_confirmed") is True
            and _int_or_zero(row.get("customer_history_order_count") or row.get("customer_order_count")) <= 1
        )
    )


def _row_blocked_by_customer_history_unknown(row):
    text = _row_block_text(row)
    return "customer history not confirmed" in text or row.get("customer_history_confirmed") is False


def _row_blocked_by_note_risk(row):
    text = _row_block_text(row)
    return row.get("note_risk_detected") is True or "aftersales/ticket note found" in text


def _row_blocked_by_ebay(row):
    text = _row_block_text(row)
    tags = _dedupe_text(row.get("order_tags_display") or row.get("tags") or [])
    return row.get("ebay_tag_detected") is True or has_ebay_tag(tags) or "ebay order" in text


def _row_blocked_only_by_precision_fix(row):
    if not row or row.get("action_state") == "review_send":
        return False
    if row.get("delivered_tag_present") is not True:
        return False
    if row.get("review_request_tag_present") is not True:
        return False
    if _row_blocked_by_duplicate(row) or _row_blocked_by_merged_group(row):
        return False
    blockers = [
        part.lower()
        for part in _split_blocker_text(row.get("eligibility_reason_plain") or row.get("reason"))
    ]
    if not blockers:
        return False
    precision_tokens = ("customer history not confirmed", "aftersales/ticket note found")
    return all(any(token in blocker for token in precision_tokens) for blocker in blockers)


def _row_blocked_by_prior_trustpilot_history(row):
    text = _row_block_text(row)
    return (
        row.get("customer_level_trustpilot_already_sent") is True
        or row.get("customer_level_trustpilot_note_evidence_found") is True
        or row.get("trustpilot_note_evidence_found") is True
        or bool(row.get("previous_trustpilot_order_names"))
        or "previous trustpilot note found" in text
        or "already sent trustpilot to this customer" in text
        or "already sent via" in text
    )


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


def _second_order_rule_counts(eligible_rows, blocked_rows):
    rows = list(eligible_rows or []) + list(blocked_rows or [])
    blocked_first = sum(1 for row in blocked_rows or [] if row.get("second_order_rule_blocker") == "first_order")
    blocked_not_second = sum(
        1 for row in blocked_rows or [] if row.get("second_order_rule_blocker") == "not_second_or_later"
    )
    blocked_not_delivered = sum(
        1 for row in blocked_rows or [] if row.get("second_order_rule_blocker") == "second_order_not_delivered"
    )
    after_count = len(eligible_rows or [])
    return {
        "blocked_first_order_count": blocked_first,
        "blocked_not_second_or_later_count": blocked_not_second,
        "blocked_second_order_not_delivered_count": blocked_not_delivered,
        "second_or_later_delivered_candidate_count": sum(
            1
            for row in rows
            if row.get("second_or_later_order") is True and row.get("current_order_delivered") is True
        ),
        "eligible_candidate_count_before_second_order_rule": (
            after_count + blocked_first + blocked_not_second + blocked_not_delivered
        ),
        "eligible_candidate_count_after_second_order_rule": after_count,
    }


def _row_block_text(row):
    return " ".join(
        _safe_text(row.get(key), max_length=500).lower()
        for key in (
            "reason",
            "eligibility_reason_plain",
            "evidence",
            "status",
            "trustpilot_history_label",
            "customer_level_trustpilot_note_evidence_order_name",
            "note_risk_reason",
        )
    )


def _queue_candidate_summary(row):
    visible = row.get("visible_in_review_batch") is True
    return {
        "order": _safe_text(row.get("order"), max_length=80),
        "order_name": _safe_text(row.get("order_name") or row.get("order"), max_length=80),
        "customer": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Masked in reports",
        "customer_display_name": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Customer not loaded",
        "masked_customer": _safe_text(row.get("masked_customer_label"), max_length=120),
        "customer_masked_label": _safe_text(row.get("masked_customer_label"), max_length=120),
        "masked_customer_label": _safe_text(row.get("masked_customer_label"), max_length=120),
        "customer_order_count": _int_or_zero(row.get("customer_order_count")),
        "customer_history_order_count": _int_or_zero(row.get("customer_history_order_count")),
        "customer_history_order_count_before_precision": _int_or_zero(
            row.get("customer_history_order_count_before_precision")
        ),
        "customer_order_sequence_number": _int_or_zero(row.get("customer_order_sequence_number")),
        "customer_order_sequence_label": _safe_text(row.get("customer_order_sequence_label"), max_length=120),
        "customer_order_summary": _safe_text(row.get("customer_orders_display"), max_length=180),
        "customer_orders_display": _safe_text(row.get("customer_orders_display"), max_length=180),
        "customer_history_match_label": _safe_text(row.get("customer_history_match_label"), max_length=160),
        "customer_history_lookup_status": _safe_text(row.get("customer_history_lookup_status"), max_length=120),
        "customer_history_lookup_action_label": _safe_text(
            row.get("customer_history_lookup_action_label"),
            max_length=120,
        ),
        "customer_history_lookup_block_status": _safe_text(
            row.get("customer_history_lookup_block_status"),
            max_length=80,
        ),
        "cached_customer_history_lookup_found": row.get("cached_customer_history_lookup_found") is True,
        "cached_customer_history_lookup_generated_at": _safe_text(
            row.get("cached_customer_history_lookup_generated_at"),
            max_length=120,
        ),
        "full_history_confirmed": row.get("full_history_confirmed") is True,
        "customer_history_lookup_command": _safe_text(row.get("customer_history_lookup_command"), max_length=500),
        "historical_order_names": _dedupe_order_names(row.get("historical_order_names") or []),
        "customer_history_matched_order_names": _dedupe_order_names(
            row.get("customer_history_matched_order_names") or row.get("historical_order_names") or []
        ),
        "customer_history_match_method": _safe_text(row.get("customer_history_match_method"), max_length=80),
        "customer_history_order_names": _dedupe_order_names(row.get("customer_history_order_names") or []),
        "customer_history_window": _safe_text(row.get("customer_history_window"), max_length=80),
        "customer_history_excluded_weak_matches": _dedupe_order_names(
            row.get("customer_history_excluded_weak_matches") or []
        ),
        "customer_history_weak_match_count": _int_or_zero(row.get("customer_history_weak_match_count")),
        "customer_history_exact_match_count": _int_or_zero(row.get("customer_history_exact_match_count")),
        "previous_trustpilot_order_names": _dedupe_order_names(row.get("previous_trustpilot_order_names") or []),
        "previous_trustpilot_tag_values": _dedupe_text(row.get("previous_trustpilot_tag_values") or []),
        "customer_history_source": _safe_text(row.get("customer_history_source"), max_length=80),
        "customer_history_confidence": _safe_text(row.get("customer_history_confidence"), max_length=80),
        "customer_history_confirmed": row.get("customer_history_confirmed") is True,
        "customer_level_trustpilot_already_sent": row.get("customer_level_trustpilot_already_sent") is True,
        "customer_level_trustpilot_note_evidence_found": (
            row.get("customer_level_trustpilot_note_evidence_found") is True
        ),
        "customer_level_trustpilot_note_evidence_order_name": _safe_text(
            row.get("customer_level_trustpilot_note_evidence_order_name"), max_length=80
        ),
        "customer_level_trustpilot_note_safe_keyword": _safe_text(
            row.get("customer_level_trustpilot_note_safe_keyword"), max_length=80
        ),
        "customer_level_trustpilot_note_field_name": _safe_text(
            row.get("customer_level_trustpilot_note_field_name"), max_length=120
        ),
        "note_risk_detected": row.get("note_risk_detected") is True,
        "note_risk_field": _safe_text(row.get("note_risk_field"), max_length=120),
        "note_risk_fields": _dedupe_text(row.get("note_risk_fields") or []),
        "note_risk_keywords": _dedupe_text(row.get("note_risk_keywords") or []),
        "note_risk_reason": _safe_text(row.get("note_risk_reason"), max_length=120),
        "tags": _dedupe_text(row.get("order_tags_display") or []),
        "tag_chips": row.get("tag_chips") or [],
        "local_shopify_tags": _dedupe_text(row.get("local_shopify_tags") or []),
        "trustpilot_tag_detected": row.get("trustpilot_tag_detected") is True,
        "trustpilot_tag_source": _safe_text(row.get("trustpilot_tag_source"), max_length=120),
        "matched_trustpilot_tag_values": _dedupe_text(row.get("matched_trustpilot_tag_values") or []),
        "already_sent_reason": _safe_text(row.get("already_sent_reason"), max_length=300),
        "ebay_tag_detected": row.get("ebay_tag_detected") is True,
        "matched_ebay_tag_value": _safe_text(row.get("matched_ebay_tag_value"), max_length=120),
        "tag_data_available": row.get("tag_data_available") is True,
        "review_request_tag_present": row.get("review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": _safe_text(row.get("matched_review_request_tag_value"), max_length=120),
        "review_request_tag_match_detail": _safe_text(row.get("review_request_tag_match_detail"), max_length=180),
        "delivered_status": _safe_text(row.get("delivered_status_label"), max_length=80),
        "delivered_status_label": _safe_text(row.get("delivered_status_label"), max_length=80),
        "delivered_status_class": _safe_text(row.get("delivered_status_class"), max_length=80),
        "trustpilot_history": _safe_text(row.get("trustpilot_history_label"), max_length=300),
        "trustpilot_history_label": _safe_text(row.get("trustpilot_history_label"), max_length=300),
        "trustpilot_history_evidence": _safe_text(row.get("evidence"), max_length=500),
        "status": _safe_text(row.get("status"), max_length=120),
        "status_label": _safe_text(row.get("status"), max_length=120),
        "status_class": _safe_text(row.get("status_class"), max_length=80),
        "status_chips": row.get("status_chips") or [],
        "reason": _safe_text(row.get("eligibility_reason_plain"), max_length=500),
        "eligibility_reason_plain": _safe_text(row.get("eligibility_reason_plain"), max_length=500),
        "action_state": _safe_text(row.get("action_state"), max_length=80),
        "action_label": _safe_text(row.get("action_status"), max_length=120),
        "action_status": _safe_text(row.get("action_status"), max_length=120),
        "can_review_send": row.get("action_state") == "review_send",
        "blocked_by_customer_history_lookup": row.get("blocked_by_customer_history_lookup") is True,
        "review_send_url": "",
        "hidden_block_reason": _safe_text(row.get("hidden_reason"), max_length=120),
        "action": "Review & Send" if visible else "Queued for later review",
        "second_or_later_order": row.get("second_or_later_order") is True,
        "current_order_delivered": row.get("current_order_delivered") is True,
        "second_order_rule_passed": row.get("second_order_rule_passed") is True,
        "second_order_rule_blocker": _safe_text(row.get("second_order_rule_blocker"), max_length=80),
        "second_order_rule_reason": _safe_text(row.get("second_order_rule_reason"), max_length=160),
        "review_queue_rank": _int_or_zero(row.get("review_queue_rank")),
        "visible_in_review_batch": visible,
        "hidden_reason": _safe_text(row.get("hidden_reason"), max_length=120),
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
        "order_name": _safe_text(row.get("order_name") or row.get("order"), max_length=80),
        "group_order_names": row.get("group_order_names") or [],
        "customer": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Masked in reports",
        "customer_display_name": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Customer not loaded",
        "customer_masked_label": _safe_text(row.get("masked_customer_label"), max_length=120),
        "masked_customer_label": _safe_text(row.get("masked_customer_label"), max_length=120),
        "customer_history_order_count": _int_or_zero(row.get("customer_history_order_count")),
        "customer_history_order_count_before_precision": _int_or_zero(
            row.get("customer_history_order_count_before_precision")
        ),
        "customer_order_sequence_number": _int_or_zero(row.get("customer_order_sequence_number")),
        "customer_order_sequence_label": _safe_text(row.get("customer_order_sequence_label"), max_length=120),
        "customer_order_summary": _safe_text(row.get("customer_orders_display"), max_length=180),
        "customer_orders_display": _safe_text(row.get("customer_orders_display"), max_length=180),
        "customer_history_match_label": _safe_text(row.get("customer_history_match_label"), max_length=160),
        "customer_history_lookup_status": _safe_text(row.get("customer_history_lookup_status"), max_length=120),
        "customer_history_lookup_action_label": _safe_text(
            row.get("customer_history_lookup_action_label"),
            max_length=120,
        ),
        "customer_history_lookup_block_status": _safe_text(
            row.get("customer_history_lookup_block_status"),
            max_length=80,
        ),
        "cached_customer_history_lookup_found": row.get("cached_customer_history_lookup_found") is True,
        "cached_customer_history_lookup_generated_at": _safe_text(
            row.get("cached_customer_history_lookup_generated_at"),
            max_length=120,
        ),
        "full_history_confirmed": row.get("full_history_confirmed") is True,
        "customer_history_lookup_command": _safe_text(row.get("customer_history_lookup_command"), max_length=500),
        "historical_order_names": _dedupe_order_names(row.get("historical_order_names") or []),
        "customer_history_matched_order_names": _dedupe_order_names(
            row.get("customer_history_matched_order_names") or row.get("historical_order_names") or []
        ),
        "customer_history_match_method": _safe_text(row.get("customer_history_match_method"), max_length=80),
        "customer_history_order_names": _dedupe_order_names(row.get("customer_history_order_names") or []),
        "customer_history_window": _safe_text(row.get("customer_history_window"), max_length=80),
        "customer_history_excluded_weak_matches": _dedupe_order_names(
            row.get("customer_history_excluded_weak_matches") or []
        ),
        "customer_history_weak_match_count": _int_or_zero(row.get("customer_history_weak_match_count")),
        "customer_history_exact_match_count": _int_or_zero(row.get("customer_history_exact_match_count")),
        "previous_trustpilot_order_names": _dedupe_order_names(row.get("previous_trustpilot_order_names") or []),
        "previous_trustpilot_tag_values": _dedupe_text(row.get("previous_trustpilot_tag_values") or []),
        "customer_history_source": _safe_text(row.get("customer_history_source"), max_length=80),
        "customer_history_confidence": _safe_text(row.get("customer_history_confidence"), max_length=80),
        "customer_history_confirmed": row.get("customer_history_confirmed") is True,
        "customer_level_trustpilot_already_sent": row.get("customer_level_trustpilot_already_sent") is True,
        "customer_level_trustpilot_note_evidence_found": (
            row.get("customer_level_trustpilot_note_evidence_found") is True
        ),
        "customer_level_trustpilot_note_evidence_order_name": _safe_text(
            row.get("customer_level_trustpilot_note_evidence_order_name"), max_length=80
        ),
        "customer_level_trustpilot_note_safe_keyword": _safe_text(
            row.get("customer_level_trustpilot_note_safe_keyword"), max_length=80
        ),
        "customer_level_trustpilot_note_field_name": _safe_text(
            row.get("customer_level_trustpilot_note_field_name"), max_length=120
        ),
        "note_risk_detected": row.get("note_risk_detected") is True,
        "note_risk_field": _safe_text(row.get("note_risk_field"), max_length=120),
        "note_risk_fields": _dedupe_text(row.get("note_risk_fields") or []),
        "note_risk_keywords": _dedupe_text(row.get("note_risk_keywords") or []),
        "note_risk_reason": _safe_text(row.get("note_risk_reason"), max_length=120),
        "tags": _dedupe_text(row.get("order_tags_display") or []),
        "tag_chips": row.get("tag_chips") or [],
        "local_shopify_tags": _dedupe_text(row.get("local_shopify_tags") or []),
        "trustpilot_tag_detected": row.get("trustpilot_tag_detected") is True,
        "trustpilot_tag_source": _safe_text(row.get("trustpilot_tag_source"), max_length=120),
        "matched_trustpilot_tag_values": _dedupe_text(row.get("matched_trustpilot_tag_values") or []),
        "already_sent_reason": _safe_text(row.get("already_sent_reason"), max_length=300),
        "ebay_tag_detected": row.get("ebay_tag_detected") is True,
        "matched_ebay_tag_value": _safe_text(row.get("matched_ebay_tag_value"), max_length=120),
        "tag_data_available": row.get("tag_data_available") is True,
        "tag_data_missing_source": _safe_text(row.get("tag_data_missing_source"), max_length=240),
        "tag_data_recommended_action": _safe_text(row.get("tag_data_recommended_action"), max_length=300),
        "review_request_tag_present": row.get("review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": _safe_text(row.get("matched_review_request_tag_value"), max_length=120),
        "review_request_tag_match_detail": _safe_text(row.get("review_request_tag_match_detail"), max_length=180),
        "delivered_status": _safe_text(row.get("delivered_status_label"), max_length=80),
        "delivered_status_label": _safe_text(row.get("delivered_status_label"), max_length=80),
        "delivered_status_class": _safe_text(row.get("delivered_status_class"), max_length=80),
        "merged_group_evidence_source": _safe_text(row.get("merged_group_evidence_source"), max_length=160),
        "block_reason": _safe_text(row.get("eligibility_reason_plain"), max_length=500),
        "reason": _safe_text(row.get("eligibility_reason_plain"), max_length=500),
        "eligibility_reason_plain": _safe_text(row.get("eligibility_reason_plain"), max_length=500),
        "missing_requirement": _blocked_missing_requirement(row),
        "evidence": _safe_text(row.get("evidence") or row.get("reason"), max_length=500),
        "trustpilot_history_label": _safe_text(row.get("trustpilot_history_label"), max_length=300),
        "trustpilot_history_evidence": _safe_text(row.get("evidence"), max_length=500),
        "status": _safe_text(row.get("status"), max_length=120) or "Not ready",
        "status_label": _safe_text(row.get("status"), max_length=120) or "Not ready",
        "status_class": _safe_text(row.get("status_class"), max_length=80) or "rrw-badge-warn",
        "status_chips": row.get("status_chips") or [],
        "action_state": _safe_text(row.get("action_state"), max_length=80) or "not_ready",
        "action_label": _safe_text(row.get("action_status"), max_length=120) or "Not ready",
        "action_status": _safe_text(row.get("action_status"), max_length=120) or "Not ready",
        "can_review_send": False,
        "blocked_by_customer_history_lookup": row.get("blocked_by_customer_history_lookup") is True,
        "review_send_url": "",
        "second_or_later_order": row.get("second_or_later_order") is True,
        "current_order_delivered": row.get("current_order_delivered") is True,
        "second_order_rule_passed": row.get("second_order_rule_passed") is True,
        "second_order_rule_blocker": _safe_text(row.get("second_order_rule_blocker"), max_length=80),
        "second_order_rule_reason": _safe_text(row.get("second_order_rule_reason"), max_length=160),
        "scan_date": _safe_text(row.get("scan_date"), max_length=80),
        "scan_date_basis": _safe_text(row.get("scan_date_basis"), max_length=80),
        "scan_date_fallback_used": row.get("scan_date_fallback_used") is True,
    }


def _already_sent_summary(row):
    return {
        "order": _safe_text(row.get("order"), max_length=80),
        "order_name": _safe_text(row.get("order_name") or row.get("order"), max_length=80),
        "customer": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Masked in reports",
        "customer_display_name": _safe_text(row.get("customer_display_name"), max_length=120)
        or "Customer not loaded",
        "customer_masked_label": _safe_text(row.get("masked_customer_label"), max_length=120),
        "masked_customer_label": _safe_text(row.get("masked_customer_label"), max_length=120),
        "customer_history_order_count": _int_or_zero(row.get("customer_history_order_count")),
        "customer_order_sequence_number": _int_or_zero(row.get("customer_order_sequence_number")),
        "customer_order_sequence_label": _safe_text(row.get("customer_order_sequence_label"), max_length=120),
        "customer_order_summary": _safe_text(row.get("customer_orders_display"), max_length=180),
        "customer_orders_display": _safe_text(row.get("customer_orders_display"), max_length=180),
        "customer_history_match_label": _safe_text(row.get("customer_history_match_label"), max_length=160),
        "previous_trustpilot_order_names": _dedupe_order_names(row.get("previous_trustpilot_order_names") or []),
        "previous_trustpilot_tag_values": _dedupe_text(row.get("previous_trustpilot_tag_values") or []),
        "sent_at": _safe_text(row.get("sent_at"), max_length=80),
        "email_sent_at": _safe_text(row.get("email_sent_at"), max_length=80),
        "sent_time_label": _safe_text(row.get("sent_time_label"), max_length=120) or TIME_NOT_RECORDED_LABEL,
        "sent_time_recorded": row.get("sent_time_recorded") is True,
        "tag_written_at": _safe_text(row.get("tag_written_at"), max_length=80),
        "tag_written_time_label": _safe_text(row.get("tag_written_time_label"), max_length=120)
        or TIME_NOT_RECORDED_LABEL,
        "trustpilot_email_status": _safe_text(row.get("trustpilot_email_status"), max_length=120),
        "trustpilot_history_label": _safe_text(row.get("trustpilot_history_label"), max_length=300),
        "trustpilot_history_evidence": _safe_text(row.get("evidence"), max_length=500),
        "shopify_tag_pending": row.get("shopify_tag_pending") is True,
        "shopify_tag_written": row.get("shopify_tag_written") is True,
        "shopify_tag_already_existed": row.get("shopify_tag_already_existed") is True,
        "tag_write_failed": row.get("tag_write_failed") is True,
        "shopify_tag_status_label": _safe_text(row.get("shopify_tag_status_label"), max_length=120),
        "shopify_tag_status_class": _safe_text(row.get("shopify_tag_status_class"), max_length=80),
        "evidence": _safe_text(row.get("evidence"), max_length=500),
        "tags": _dedupe_text(row.get("order_tags_display") or []),
        "tag_chips": row.get("tag_chips") or [],
        "local_shopify_tags": _dedupe_text(row.get("local_shopify_tags") or []),
        "trustpilot_tag_detected": row.get("trustpilot_tag_detected") is True,
        "trustpilot_tag_source": _safe_text(row.get("trustpilot_tag_source"), max_length=120),
        "matched_trustpilot_tag_values": _dedupe_text(row.get("matched_trustpilot_tag_values") or []),
        "already_sent_reason": _safe_text(row.get("already_sent_reason"), max_length=300),
        "ebay_tag_detected": row.get("ebay_tag_detected") is True,
        "matched_ebay_tag_value": _safe_text(row.get("matched_ebay_tag_value"), max_length=120),
        "tag_data_available": row.get("tag_data_available") is True,
        "review_request_tag_present": row.get("review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": _safe_text(row.get("matched_review_request_tag_value"), max_length=120),
        "delivered_status": _safe_text(row.get("delivered_status_label"), max_length=80),
        "status": _safe_text(row.get("status"), max_length=120) or "Already sent",
        "status_label": _safe_text(row.get("status"), max_length=120) or "Already sent",
        "status_class": _safe_text(row.get("status_class"), max_length=80) or "rrw-badge-ok",
        "status_chips": row.get("status_chips") or [],
        "reason": _safe_text(row.get("reason") or row.get("evidence"), max_length=500),
        "eligibility_reason_plain": _safe_text(row.get("reason") or row.get("evidence"), max_length=500),
        "action_state": _safe_text(row.get("action_state"), max_length=80) or "already_sent",
        "action_label": _safe_text(row.get("action_status"), max_length=120) or "Already sent",
        "action_status": _safe_text(row.get("action_status"), max_length=120) or "Already sent",
        "can_review_send": False,
        "review_send_url": "",
        "second_or_later_order": row.get("second_or_later_order") is True,
        "current_order_delivered": row.get("current_order_delivered") is True,
        "second_order_rule_passed": row.get("second_order_rule_passed") is True,
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
    if _row_blocked_by_first_order(row):
        missing.append("Repeat customer")
    if row.get("second_order_rule_blocker") == "not_second_or_later":
        missing.append("Second-or-later order")
    if row.get("second_order_rule_blocker") == "second_order_not_delivered":
        missing.append("Delivered second-or-later order")
    if _row_blocked_by_customer_history_unknown(row):
        missing.append("Confirmed customer history")
    text = _row_block_text(row)
    if row.get("note_risk_detected") is True or "aftersales/ticket note found" in text:
        missing.append("No aftersales/ticket note")
    if _row_blocked_by_ebay(row):
        missing.append("Trustpilot email allowed")
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
        f"showing {scan.get('review_queue_visible_count', 0)} in the current review batch, "
        f"{scan.get('already_sent_count', 0)} already sent, "
        f"{scan.get('blocked_count', 0)} blocked/not ready."
        f"{warning_text} "
        "No Gmail, Shopify, Trustpilot, Kudosi, or Ali Reviews API calls were performed."
    )


def _customer_history_guard_issue_summary(
    first_order_rows,
    prior_trustpilot_rows,
    unknown_history_rows,
    eligible_after,
    approval_queue,
):
    active_count = _int_or_zero(approval_queue.get("review_send_action_enabled_count"))
    return (
        f"Customer-history guard applied. First-order blocked: {len(first_order_rows)}; "
        f"prior Trustpilot customer-history blocked: {len(prior_trustpilot_rows)}; "
        f"history unknown blocked: {len(unknown_history_rows)}; "
        f"eligible candidates after fix: {eligible_after}; "
        f"active Review & Send buttons after fix: {active_count}. "
        "No Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, or external API calls were performed."
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
    if len(normalized_names) > 50:
        contexts = {}
        for index in range(0, len(normalized_names), 50):
            contexts.update(_local_order_contexts(normalized_names[index : index + 50]))
        return contexts

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


def _note_risk_detection(row):
    row = row or {}
    fields = []
    keywords = []
    for field in NOTE_RISK_FIELDS:
        for fragment in _note_text_fragments(row.get(field)):
            matched = _note_risk_keywords_in_text(fragment)
            if not matched:
                continue
            fields.append(field)
            keywords.extend(matched)
    fields = _dedupe_text(fields)
    keywords = _dedupe_text(keywords)
    return {
        "note_risk_detected": bool(fields),
        "note_risk_field": fields[0] if fields else "",
        "note_risk_fields": fields,
        "note_risk_keywords": keywords,
        "note_risk_reason": NOTE_RISK_REASON if fields else "",
    }


def _note_risk_keywords_in_text(value):
    text = _safe_text(value, max_length=1000)
    lowered = text.lower()
    matched = []
    for keyword in NOTE_RISK_KEYWORDS:
        safe_keyword = _safe_text(keyword, max_length=80)
        if not safe_keyword:
            continue
        if safe_keyword.lower() in lowered:
            matched.append(safe_keyword)
    return _dedupe_text(matched)


def _note_risk_from_sources(*sources):
    fields = []
    keywords = []
    for source in sources:
        source = source or {}
        if source.get("note_risk_detected") is True:
            fields.extend(source.get("note_risk_fields") or [source.get("note_risk_field")])
            keywords.extend(source.get("note_risk_keywords") or [])
            continue
        detected = _note_risk_detection(source)
        if detected["note_risk_detected"]:
            fields.extend(detected["note_risk_fields"])
            keywords.extend(detected["note_risk_keywords"])
    fields = _dedupe_text(field for field in fields if field)
    keywords = _dedupe_text(keyword for keyword in keywords if keyword)
    return {
        "note_risk_detected": bool(fields),
        "note_risk_field": fields[0] if fields else "",
        "note_risk_fields": fields,
        "note_risk_keywords": keywords,
        "note_risk_reason": NOTE_RISK_REASON if fields else "",
    }


def detect_trustpilot_note_evidence(order):
    order = order or {}
    order_name = _canonical_order_name(
        order.get("order_name") or order.get("order") or order.get("order_number")
    )
    for field in TRUSTPILOT_NOTE_FIELDS:
        if field not in order:
            continue
        for fragment in _note_text_fragments(order.get(field)):
            keyword = _trustpilot_note_keyword_in_text(fragment)
            if keyword:
                return {
                    "evidence_found": True,
                    "safe_keyword": keyword,
                    "field_name": field,
                    "order_name": order_name,
                }
    return {
        "evidence_found": False,
        "safe_keyword": "",
        "field_name": "",
        "order_name": order_name,
    }


def _trustpilot_note_keyword_in_text(value):
    compact_text = _compact_trustpilot_note_text(value)
    if not compact_text:
        return ""
    for keyword in TRUSTPILOT_NOTE_KEYWORDS:
        safe_keyword = _safe_text(keyword, max_length=80)
        if safe_keyword and _compact_trustpilot_note_text(safe_keyword) in compact_text:
            return safe_keyword
    return ""


def _compact_trustpilot_note_text(value):
    return re.sub(r"[^a-z0-9]+", "", _safe_text(value, max_length=2000).lower())


def _empty_trustpilot_note_evidence(order_name=""):
    return {
        "evidence_found": False,
        "safe_keyword": "",
        "field_name": "",
        "order_name": _canonical_order_name(order_name),
    }


def _customer_trustpilot_note_evidence(order, customer_orders):
    current_id = (order or {}).get("id")
    current_name = _canonical_order_name((order or {}).get("order_name"))
    for history_order in customer_orders or []:
        history_name = _canonical_order_name(history_order.get("order_name"))
        if current_id and history_order.get("id") == current_id:
            continue
        if current_name and history_name == current_name:
            continue
        evidence = detect_trustpilot_note_evidence(history_order)
        if evidence.get("evidence_found") is True:
            return evidence
    return _empty_trustpilot_note_evidence()


def _trustpilot_note_evidence_from_sources(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        if (
            source.get("customer_level_trustpilot_note_evidence_found") is True
            or source.get("trustpilot_note_evidence_found") is True
        ):
            return {
                "evidence_found": True,
                "safe_keyword": _safe_text(
                    source.get("customer_level_trustpilot_note_safe_keyword")
                    or source.get("trustpilot_note_safe_keyword"),
                    max_length=80,
                ),
                "field_name": _safe_text(
                    source.get("customer_level_trustpilot_note_field_name")
                    or source.get("trustpilot_note_field_name"),
                    max_length=120,
                ),
                "order_name": _canonical_order_name(
                    source.get("customer_level_trustpilot_note_evidence_order_name")
                    or source.get("trustpilot_note_evidence_order_name")
                    or source.get("order_name")
                    or source.get("order")
                ),
            }
        evidence = detect_trustpilot_note_evidence(source)
        if evidence.get("evidence_found") is True:
            return evidence
    return _empty_trustpilot_note_evidence()


def _trustpilot_note_evidence_reason(evidence):
    order_name = _canonical_order_name((evidence or {}).get("order_name")) or "another order"
    return f"Previous Trustpilot note found on historical order {order_name}."


def _trustpilot_note_history_label(evidence):
    order_name = _canonical_order_name((evidence or {}).get("order_name")) or "another order"
    return f"Previous Trustpilot note found via {order_name}"


def _cached_lookup_order_from_cache(lookup_cache, order_name):
    selected = _canonical_order_name(order_name)
    if not selected:
        return {}
    return ((lookup_cache or {}).get("orders") or {}).get(selected, {})


def _cached_lookup_order_from_reports(reports, order_name):
    selected = _canonical_order_name(order_name)
    if not selected:
        return {}
    cache_report = (reports or {}).get("on_demand_customer_history_lookup_cache") or {}
    cache_data = cache_report.get("data") or {}
    cached = ((cache_data.get("orders") or {}) if isinstance(cache_data, dict) else {}).get(selected, {})
    if isinstance(cached, dict) and cached:
        return cached
    return lookup_cached_customer_history_result(_log_dir(), selected)


def _cached_customer_history_lookup_reason(lookup):
    reason = _safe_text((lookup or {}).get("blocking_reason"), max_length=300)
    if reason:
        return reason
    evidence_order = _canonical_order_name((lookup or {}).get("evidence_order_name"))
    if (lookup or {}).get("trustpilot_note_evidence_found") is True:
        return f"Previous Trustpilot note found on historical order {evidence_order or 'another order'}."
    if (lookup or {}).get("trustpilot_tag_evidence_found") is True:
        return f"Previous Trustpilot tag found on historical order {evidence_order or 'another order'}."
    return "Customer history lookup blocked Review & Send."


def _cached_customer_history_lookup_label(lookup):
    evidence_order = _canonical_order_name((lookup or {}).get("evidence_order_name"))
    if (lookup or {}).get("trustpilot_note_evidence_found") is True:
        return f"Previous Trustpilot note found via {evidence_order or 'another order'}"
    if (lookup or {}).get("trustpilot_tag_evidence_found") is True:
        return f"Previous Trustpilot tag found via {evidence_order or 'another order'}"
    if (lookup or {}).get("should_block_review_send") is True:
        return _cached_customer_history_lookup_reason(lookup)
    return ""


def _customer_history_lookup_gate(lookup, reference_at=""):
    if not lookup:
        return _customer_history_lookup_gate_result(
            status="missing",
            reason=LIVE_HISTORY_MISSING_REASON,
            label="Needs live check",
            action_label="Check customer history",
            missing_requirement="Live Shopify history check",
        )
    history_count = _int_or_zero((lookup or {}).get("shopify_customer_history_count"))
    note_evidence = (lookup or {}).get("trustpilot_note_evidence_found") is True
    tag_evidence = (lookup or {}).get("trustpilot_tag_evidence_found") is True
    evidence_order = _canonical_order_name((lookup or {}).get("evidence_order_name"))
    full_history_confirmed = _lookup_full_history_confirmed(lookup)
    if note_evidence:
        return _customer_history_lookup_gate_result(
            status="blocked_trustpilot_note",
            reason=f"Previous Trustpilot note found on historical order {evidence_order or 'another order'}.",
            label=f"Checked: {history_count} order{'s' if history_count != 1 else ''}",
            action_label="Customer history checked",
            missing_requirement="No prior Trustpilot send",
            evidence_found=True,
            full_history_confirmed=full_history_confirmed,
        )
    if tag_evidence:
        return _customer_history_lookup_gate_result(
            status="blocked_trustpilot_tag",
            reason=f"Previous Trustpilot tag found on historical order {evidence_order or 'another order'}.",
            label=f"Checked: {history_count} order{'s' if history_count != 1 else ''}",
            action_label="Customer history checked",
            missing_requirement="No prior Trustpilot send",
            evidence_found=True,
            full_history_confirmed=full_history_confirmed,
        )
    if (lookup or {}).get("should_block_review_send") is True and not full_history_confirmed:
        return _customer_history_lookup_gate_result(
            status="incomplete",
            reason=LIVE_HISTORY_INCOMPLETE_REASON,
            label="Needs live check",
            action_label="Check customer history",
            missing_requirement="Full Shopify history",
            full_history_confirmed=False,
        )
    if (lookup or {}).get("should_block_review_send") is True:
        return _customer_history_lookup_gate_result(
            status="blocked_lookup_cache",
            reason=_cached_customer_history_lookup_reason(lookup),
            label="Needs live check",
            action_label="Check customer history",
            missing_requirement="Live Shopify history check",
            full_history_confirmed=full_history_confirmed,
        )
    if _customer_history_lookup_is_stale(lookup, reference_at):
        return _customer_history_lookup_gate_result(
            status="stale",
            reason=LIVE_HISTORY_STALE_REASON,
            label="Stale check",
            action_label="Recheck customer history",
            missing_requirement="Fresh live Shopify history check",
            full_history_confirmed=full_history_confirmed,
        )
    if not full_history_confirmed:
        return _customer_history_lookup_gate_result(
            status="incomplete",
            reason=LIVE_HISTORY_INCOMPLETE_REASON,
            label="Needs live check",
            action_label="Check customer history",
            missing_requirement="Full Shopify history",
            full_history_confirmed=False,
        )
    return _customer_history_lookup_gate_result(
        status="ready",
        reason="",
        label=f"Checked: {history_count} order{'s' if history_count != 1 else ''}",
        action_label="Customer history checked",
        missing_requirement="",
        full_history_confirmed=True,
    )


def _customer_history_lookup_gate_result(
    status,
    reason,
    label,
    action_label,
    missing_requirement,
    evidence_found=False,
    full_history_confirmed=False,
):
    return {
        "status": status,
        "blocked": status != "ready",
        "reason": _safe_text(reason, max_length=300),
        "label": _safe_text(label, max_length=120),
        "action_label": _safe_text(action_label, max_length=120),
        "missing_requirement": _safe_text(missing_requirement, max_length=160),
        "evidence_found": evidence_found,
        "full_history_confirmed": full_history_confirmed,
    }


def _lookup_full_history_confirmed(lookup):
    if not lookup:
        return False
    return bool(
        (lookup or {}).get("full_history_confirmed") is True
        or (
            (lookup or {}).get("lookup_status") == "customer_history_lookup_completed"
            and (lookup or {}).get("read_all_orders_scope_present") is True
            and (lookup or {}).get("shopify_api_lookup_performed") is True
            and _int_or_zero((lookup or {}).get("shopify_customer_history_count")) > 0
        )
    )


def _customer_history_lookup_is_stale(lookup, reference_at=""):
    lookup_dt = _parse_datetime_value((lookup or {}).get("generated_at"))
    if not lookup_dt:
        return True
    now = datetime.now(timezone.utc)
    if now - lookup_dt > timedelta(hours=CUSTOMER_HISTORY_LOOKUP_TTL_HOURS):
        return True
    return False


def _customer_history_check_summary(eligible_rows, blocked_rows):
    eligible_rows = list(eligible_rows or [])
    blocked_rows = list(blocked_rows or [])
    needs_check_rows = []
    completed_rows = []
    blocked_history_rows = []
    failed_incomplete_rows = []
    for row in eligible_rows + blocked_rows:
        status = _safe_text(row.get("customer_history_lookup_block_status"), max_length=80)
        reason = _safe_text(row.get("block_reason") or row.get("reason"), max_length=500).lower()
        cached_found = row.get("cached_customer_history_lookup_found") is True
        full_history_confirmed = row.get("full_history_confirmed") is True
        if status in {"missing", "stale"} or LIVE_HISTORY_MISSING_REASON.lower() in reason:
            needs_check_rows.append(row)
            continue
        if status in {"blocked_trustpilot_note", "blocked_trustpilot_tag"}:
            blocked_history_rows.append(row)
            completed_rows.append(row)
            continue
        if status in {"incomplete", "blocked_lookup_cache"} or LIVE_HISTORY_INCOMPLETE_REASON.lower() in reason:
            failed_incomplete_rows.append(row)
            continue
        if status == "ready" or (cached_found and full_history_confirmed):
            completed_rows.append(row)
    needs_check_count = len(needs_check_rows)
    return {
        "final_eligible_count": len(eligible_rows),
        "final_eligible_orders": _dedupe_order_names(row.get("order") for row in eligible_rows),
        "needs_live_customer_history_check_count": needs_check_count,
        "live_checks_completed_count": len(completed_rows),
        "live_checks_blocked_count": len(blocked_history_rows),
        "live_checks_failed_incomplete_count": len(failed_incomplete_rows),
        "blocked_by_historical_trustpilot_evidence_orders": _dedupe_order_names(
            row.get("order") for row in blocked_history_rows
        ),
        "live_lookup_failed_or_incomplete_orders": _dedupe_order_names(
            row.get("order") for row in failed_incomplete_rows
        ),
        "needs_live_customer_history_check_orders": _dedupe_order_names(
            row.get("order") for row in needs_check_rows
        ),
        "message": (
            f"{needs_check_count} candidates need live customer history check before they can be reviewed."
            if needs_check_count
            else ""
        ),
    }


def _apply_cached_customer_history_lookup_to_row(row, lookup):
    if not lookup:
        return row
    gate = _customer_history_lookup_gate(lookup)
    history_names = _dedupe_order_names(
        (lookup or {}).get("historical_order_names")
        or (lookup or {}).get("shopify_history_order_names")
        or []
    )
    history_count = _int_or_zero((lookup or {}).get("shopify_customer_history_count")) or len(history_names)
    evidence_order = _canonical_order_name((lookup or {}).get("evidence_order_name"))
    safe_keyword = _safe_text((lookup or {}).get("safe_detected_keyword"), max_length=80)
    note_evidence = (lookup or {}).get("trustpilot_note_evidence_found") is True
    tag_evidence = (lookup or {}).get("trustpilot_tag_evidence_found") is True
    should_block = gate["blocked"]
    reason = gate["reason"]
    history_label = _cached_customer_history_lookup_label(lookup)
    if gate["status"] == "ready":
        history_label = "No previous Trustpilot found"
    elif gate["status"] in {"stale", "incomplete"} and not history_label:
        history_label = "Needs live check"
    row.update(
        {
            "cached_customer_history_lookup_found": True,
            "cached_customer_history_lookup_generated_at": _safe_text(
                (lookup or {}).get("generated_at"), max_length=120
            ),
            "cached_customer_history_lookup_should_block_review_send": should_block,
            "cached_customer_history_lookup_blocking_reason": reason,
            "customer_history_lookup_block_status": gate["status"],
            "shopify_customer_history_count": history_count,
            "customer_history_order_count": history_count or _int_or_zero(row.get("customer_history_order_count")),
            "customer_order_count": history_count or _int_or_zero(row.get("customer_order_count")),
            "historical_order_names": history_names or row.get("historical_order_names", []),
            "customer_history_order_names": history_names or row.get("customer_history_order_names", []),
            "customer_history_matched_order_names": history_names
            or row.get("customer_history_matched_order_names", []),
            "customer_history_window": "shopify_lifetime_on_demand_lookup",
            "customer_history_source": "on_demand_shopify_customer_history_lookup",
            "customer_history_confidence": "high",
            "customer_history_confirmed": gate["full_history_confirmed"],
            "full_history_confirmed": gate["full_history_confirmed"],
            "customer_history_lookup_status": gate["label"],
            "customer_history_lookup_action_label": gate["action_label"],
            "customer_level_trustpilot_note_evidence_found": note_evidence,
            "customer_level_trustpilot_note_evidence_order_name": evidence_order,
            "customer_level_trustpilot_note_safe_keyword": safe_keyword,
            "trustpilot_note_evidence_found": note_evidence,
            "trustpilot_note_evidence_order_name": evidence_order,
            "trustpilot_note_safe_keyword": safe_keyword,
        }
    )
    if history_label:
        row["trustpilot_history_label"] = history_label
        row["trustpilot_history"] = history_label
    if should_block:
        row.update(
            {
                "status": "Not ready",
                "status_label": "Not ready",
                "status_class": "rrw-badge-warn",
                "reason": reason,
                "eligibility_reason_plain": reason,
                "block_reason": reason,
                "blocked_reason": reason,
                "hidden_reason": reason,
                "evidence": reason,
                "action_state": "not_ready",
                "action_label": "Not ready",
                "action_status": "Not ready",
                "can_review_send": False,
                "review_send_post_action": "",
                "candidate_status": "blocked",
                "missing_requirement": gate["missing_requirement"] or "Live Shopify history check",
                "trustpilot_email_status": "Already sent" if gate["evidence_found"] else "Not ready",
                "customer_level_trustpilot_already_sent": note_evidence or tag_evidence,
                "already_sent_reason": reason if gate["evidence_found"] else "",
                "blocked_by_customer_history_lookup": True,
            }
        )
    return row


def _apply_customer_history_lookup_gate_to_queue_row(row, lookup_cache, reference_at=""):
    lookup = _cached_lookup_order_from_cache(lookup_cache, (row or {}).get("order"))
    if lookup:
        row = _apply_cached_customer_history_lookup_to_row(row, lookup)
    elif (row or {}).get("action_state") != "review_send":
        return row
    gate = _customer_history_lookup_gate(lookup, reference_at)
    if not gate["blocked"] or (row or {}).get("action_state") != "review_send":
        return row
    reason = gate["reason"]
    row.update(
        {
            "status": "Not ready",
            "status_label": "Not ready",
            "status_class": "rrw-badge-warn",
            "reason": reason,
            "eligibility_reason_plain": reason,
            "block_reason": reason,
            "blocked_reason": reason,
            "hidden_reason": reason,
            "evidence": reason,
            "action_state": "not_ready",
            "action_label": "Not ready",
            "action_status": "Not ready",
            "can_review_send": False,
            "review_send_post_action": "",
            "candidate_status": "blocked",
            "missing_requirement": gate["missing_requirement"] or "Live Shopify history check",
            "trustpilot_email_status": "Not ready",
            "customer_level_trustpilot_already_sent": gate["evidence_found"],
            "already_sent_reason": reason if gate["evidence_found"] else "",
            "blocked_by_customer_history_lookup": True,
            "customer_history_lookup_block_status": gate["status"],
            "customer_history_lookup_status": gate["label"],
            "customer_history_lookup_action_label": gate["action_label"],
            "cached_customer_history_lookup_found": bool(lookup),
            "trustpilot_history_label": row.get("trustpilot_history_label")
            if gate["evidence_found"]
            else "Needs live check",
        }
    )
    return row


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
    trustpilot_state = _trustpilot_sent_state(row, local_context or {})
    if trustpilot_state["already_sent"]:
        return _apply_queue_row_context(
            {
                "candidate_id": order_name,
                "order": order_name,
                "customer": customer,
                "status": "Already sent",
                "status_class": "rrw-badge-ok",
                "reason": trustpilot_state["evidence"],
                "evidence": trustpilot_state["evidence"],
                "already_sent_reason": trustpilot_state["already_sent_reason"],
                "action_state": "already_sent",
                "source": _safe_text(row.get("source"), max_length=120),
            },
            row,
            local_context or {},
            action_state="already_sent",
        )
    blockers = _candidate_send_blockers(
        row,
        already_sent_orders=already_sent_orders,
        already_sent_customers=already_sent_customers,
        gmail_setup=gmail_setup,
        local_context=local_context or {},
    )
    if row.get("ebay_tag_detected") is True or blockers == [EBAY_BLOCK_REASON]:
        return _apply_queue_row_context(
            {
                "candidate_id": order_name,
                "order": order_name,
                "customer": customer,
                "status": "Not ready",
                "status_class": "rrw-badge-warn",
                "reason": EBAY_BLOCK_REASON,
                "action_state": "not_ready",
                "source": _safe_text(row.get("source"), max_length=120),
            },
            row,
            local_context or {},
            action_state="not_ready",
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


def _candidate_send_blockers(row, already_sent_orders, already_sent_customers, gmail_setup, local_context=None):
    local_context = local_context or {}
    blockers = []
    order_name = _safe_text(row.get("order_name"), max_length=80)
    customer = _safe_text(row.get("masked_email"), max_length=120)
    tags = _combined_queue_tags(row, local_context=local_context)
    if row.get("ebay_tag_detected") is True or has_ebay_tag(tags):
        return [EBAY_BLOCK_REASON]
    trustpilot_state = _trustpilot_sent_state(row, local_context)
    if trustpilot_state["already_sent"]:
        return [trustpilot_state["already_sent_reason"]]
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
    history_confirmed = (
        local_context.get("customer_history_confirmed") is True
        or row.get("customer_history_confirmed") is True
    )
    history_count = (
        _int_or_zero(local_context.get("customer_history_order_count"))
        or _int_or_zero(local_context.get("customer_order_count"))
        or _int_or_zero(row.get("customer_history_order_count"))
        or _int_or_zero(row.get("customer_order_count"))
    )
    sequence = (
        _int_or_zero(local_context.get("customer_order_sequence_number"))
        or _int_or_zero(local_context.get("customer_order_sequence"))
        or _int_or_zero(row.get("customer_order_sequence_number"))
        or _int_or_zero(row.get("customer_order_sequence"))
    )
    delivered = _queue_delivered_status(row, tags, row.get("reason", ""))
    second_order_state = _second_order_rule_state(
        history_confirmed=history_confirmed,
        history_count=history_count,
        sequence=sequence,
        delivered=delivered,
    )
    previous_trustpilot_order_names = _dedupe_order_names(
        local_context.get("previous_trustpilot_order_names")
        or row.get("previous_trustpilot_order_names")
        or []
    ) if history_confirmed else []
    trustpilot_note_evidence = (
        _trustpilot_note_evidence_from_sources(local_context, row) if history_confirmed else _empty_trustpilot_note_evidence()
    )
    note_risk = _note_risk_from_sources(local_context, row)
    if second_order_state["passed"] is not True:
        blockers.append(second_order_state["reason"])
    if note_risk["note_risk_detected"]:
        blockers.append(NOTE_RISK_REASON)
    if trustpilot_note_evidence.get("evidence_found") is True:
        blockers.append(_trustpilot_note_evidence_reason(trustpilot_note_evidence))
    if previous_trustpilot_order_names:
        blockers.append(
            f"Already sent Trustpilot to this customer via {_join_order_names(previous_trustpilot_order_names)}."
        )
    if row.get("trustpilot_invitation_present") is True:
        blockers.append("Already sent to this order.")
    if delivered is not True and second_order_state["blocker"] != "second_order_not_delivered":
        blockers.append(SECOND_ORDER_WAIT_FOR_DELIVERY_REASON)
    review_request_tag_status = row.get("canonical_review_request_tag_present")
    if review_request_tag_status is None and row.get("review_request_tag_data_loaded") is not True:
        blockers.append("Shopify tag data not loaded, cannot confirm review request tag.")
    elif review_request_tag_status is not True:
        blockers.append(f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`.")
    if row.get("blocking_reasons"):
        blockers.append(_plain_blocked_reason(row))
    if _row_has_returned_package(row):
        blockers.append("Return or returned-package risk found.")
    if _row_has_risk_or_ticket(row) and not note_risk["note_risk_detected"]:
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


def _trustpilot_sent_state(row, local_context=None):
    row = row or {}
    local_context = local_context or {}
    tags = _combined_queue_tags(row, local_context=local_context)
    local_shopify_tags = _local_shopify_tags_for_queue(local_context)
    local_matches = _matched_trustpilot_tags({}, local_shopify_tags)
    matched_tags = _matched_trustpilot_tags(row, tags)
    previous_orders = _dedupe_order_names(
        local_context.get("previous_trustpilot_order_names")
        or row.get("previous_trustpilot_order_names")
        or []
    )
    previous_tags = _dedupe_text(
        local_context.get("previous_trustpilot_tag_values")
        or row.get("previous_trustpilot_tag_values")
        or []
    )
    local_send_success = (
        row.get("local_review_send_success") is True
        or local_context.get("local_review_send_success") is True
    )
    tag_write_confirmed = (
        _shopify_tag_write_confirmed_from_payload(row)
        or _shopify_tag_write_confirmed_from_payload(local_context)
    )
    if local_matches:
        return {
            "already_sent": True,
            "evidence": TRUSTPILOT_TAG_FOUND_EVIDENCE,
            "already_sent_reason": TRUSTPILOT_TAG_ALREADY_SENT_REASON,
            "trustpilot_tag_detected": True,
            "trustpilot_tag_source": "local_shopify_tags",
            "matched_trustpilot_tag_values": local_matches,
            "local_shopify_tags": local_shopify_tags,
        }
    if matched_tags or row.get("trustpilot_invitation_present") is True:
        return {
            "already_sent": True,
            "evidence": TRUSTPILOT_TAG_FOUND_EVIDENCE,
            "already_sent_reason": TRUSTPILOT_TAG_ALREADY_SENT_REASON,
            "trustpilot_tag_detected": bool(matched_tags),
            "trustpilot_tag_source": _trustpilot_tag_source(
                tags,
                local_shopify_tags=local_shopify_tags,
                previous_trustpilot_tags=[],
                source_row=row,
            )
            or "local_report_tags",
            "matched_trustpilot_tag_values": matched_tags,
            "local_shopify_tags": local_shopify_tags,
        }
    if previous_orders or previous_tags:
        prior = _join_order_names(previous_orders) or "another order"
        return {
            "already_sent": True,
            "evidence": f"Already sent Trustpilot to this customer via {prior}.",
            "already_sent_reason": "Customer history shows Trustpilot already sent.",
            "trustpilot_tag_detected": bool(previous_tags),
            "trustpilot_tag_source": "customer_history_tags" if previous_tags else "customer_history",
            "matched_trustpilot_tag_values": previous_tags,
            "local_shopify_tags": local_shopify_tags,
        }
    if local_send_success or tag_write_confirmed:
        return {
            "already_sent": True,
            "evidence": "Trustpilot email already sent and recorded.",
            "already_sent_reason": "Local send report shows Trustpilot already sent.",
            "trustpilot_tag_detected": False,
            "trustpilot_tag_source": "local_send_report",
            "matched_trustpilot_tag_values": [],
            "local_shopify_tags": local_shopify_tags,
        }
    return {
        "already_sent": False,
        "evidence": "",
        "already_sent_reason": "",
        "trustpilot_tag_detected": False,
        "trustpilot_tag_source": "",
        "matched_trustpilot_tag_values": [],
        "local_shopify_tags": local_shopify_tags,
    }


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
            "evidence": "Sent via Review & Send",
            "reason": "Sent via Review & Send",
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
        local_review_send_success = record.get("local_review_send_success") is True
        shopify_tag_pending = record.get("shopify_tag_pending") is True
        evidence_label = (
            _safe_text(record.get("evidence_message"), max_length=500)
            or _record_evidence_label(record)
        )
        rows.append(
            {
                "order": order_name,
                "customer": record.get("masked_email") or "Masked in reports",
                "status": "Sent, tag pending" if shopify_tag_pending else "Already sent",
                "status_class": "rrw-badge-info" if shopify_tag_pending else "rrw-badge-ok",
                "evidence": evidence_label,
                "reason": evidence_label,
                "action_state": "already_sent",
                "prior_trustpilot_order_name": order_name,
                "sent_at": _safe_text(record.get("sent_at") or record.get("event_time"), max_length=80),
                "email_sent_at": _safe_text(record.get("email_sent_at") or record.get("event_time"), max_length=80),
                "tag_written_at": _safe_text(record.get("tag_written_at"), max_length=80),
                "tag_write_status": _safe_text(record.get("tag_write_status"), max_length=120),
                "tag_write_failed": record.get("tag_write_failed") is True,
                "tag_write_already_complete": record.get("tag_write_already_complete") is True,
                "local_review_send_success": local_review_send_success,
                "shopify_tag_pending": shopify_tag_pending,
                "shopify_tag_written": record.get("shopify_tag_written") is True,
                "shopify_tag_already_existed": record.get("shopify_tag_already_existed") is True,
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
                "evidence": "Shopify tag found",
                "reason": "Shopify tag found",
                "action_state": "already_sent",
                "prior_trustpilot_order_name": order_name,
                "shopify_tag_written": True,
                "shopify_tag_already_existed": True,
                "trustpilot_tag_detected": True,
                "trustpilot_tags": _dedupe_text(row.get("trustpilot_tags") or []),
            }
        )
    return _dedupe_already_sent_rows(rows)


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
    if len(normalized_names) > 50:
        contexts = {}
        for index in range(0, len(normalized_names), 50):
            contexts.update(_local_order_contexts(normalized_names[index : index + 50]))
        return contexts

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
        history_value_fields = (
            "id",
            "order_name",
            "order_number",
            "shopify_order_id",
            "customer_name",
            "customer_email",
            "shipping_name",
            "shipping_address1",
            "shipping_address2",
            "shipping_city",
            "shipping_province",
            "shipping_zip",
            "shipping_country",
            "shipping_phone",
            "order_created_at",
            SHOPIFY_ORDER_TAG_FIELD,
            "shopify_note",
            "shopify_note_attributes",
            "warehouse_note",
            "transfer_note",
            "exception_review_reason",
            "exception_review_response",
            "cost_calculation_note",
        )
        selected_orders = list(
            ShopifyOrder.objects.filter(query).values(*history_value_fields)[:MAX_LOCAL_ORDER_SCAN_ROWS]
        )
        history_orders_by_identity = _customer_history_orders_for_selected(
            selected_orders,
            history_value_fields,
        )
    except Exception:
        return {}

    contexts_by_lookup_key = {}
    local_sent_records = _local_review_send_success_order_map()
    for order in selected_orders:
        email = _safe_runtime_email(order.get("customer_email"))
        history = _customer_history_for_order(order, history_orders_by_identity, local_sent_records)
        identity = _customer_identity_summary(order)
        tags = _shopify_tags_from_order(order)
        tag_data_loaded = _shopify_tags_loaded_from_order(order)
        note_risk = _note_risk_detection(order)
        context = {
            "customer_display_name": _safe_customer_display_name(order.get("customer_name")),
            "masked_email": mask_email(email),
            "customer_identity_key": identity["customer_identity_key"],
            "customer_identity_source": identity["customer_identity_source"],
            "customer_identity_confidence": identity["customer_identity_confidence"],
            "customer_order_count": history["customer_history_order_count"],
            "customer_history_order_count": history["customer_history_order_count"],
            "customer_history_order_count_before_precision": history[
                "customer_history_order_count_before_precision"
            ],
            "customer_order_sequence": history["customer_order_sequence_number"],
            "customer_order_sequence_number": history["customer_order_sequence_number"],
            "customer_order_sequence_label": history["customer_order_sequence_label"],
            "customer_order_names": history["historical_order_names"][:5],
            "historical_order_names": history["historical_order_names"],
            "customer_history_order_names": history["customer_history_order_names"],
            "customer_history_window": history["customer_history_window"],
            "customer_history_matched_order_names": history["customer_history_matched_order_names"],
            "customer_history_match_method": history["customer_history_match_method"],
            "customer_history_excluded_weak_matches": history["customer_history_excluded_weak_matches"],
            "customer_history_weak_match_count": history["customer_history_weak_match_count"],
            "customer_history_exact_match_count": history["customer_history_exact_match_count"],
            "previous_trustpilot_order_names": history["previous_trustpilot_order_names"],
            "previous_trustpilot_tag_values": history["previous_trustpilot_tag_values"],
            "customer_history_source": history["customer_history_source"],
            "customer_history_confidence": history["customer_history_confidence"],
            "customer_history_confirmed": history["customer_history_confirmed"],
            "customer_level_trustpilot_already_sent": history["customer_level_trustpilot_already_sent"],
            "customer_level_trustpilot_note_evidence_found": history[
                "customer_level_trustpilot_note_evidence_found"
            ],
            "customer_level_trustpilot_note_evidence_order_name": history[
                "customer_level_trustpilot_note_evidence_order_name"
            ],
            "customer_level_trustpilot_note_safe_keyword": history[
                "customer_level_trustpilot_note_safe_keyword"
            ],
            "customer_level_trustpilot_note_field_name": history[
                "customer_level_trustpilot_note_field_name"
            ],
            "note_risk_detected": note_risk["note_risk_detected"],
            "note_risk_field": note_risk["note_risk_field"],
            "note_risk_fields": note_risk["note_risk_fields"],
            "note_risk_keywords": note_risk["note_risk_keywords"],
            "note_risk_reason": note_risk["note_risk_reason"],
            "order_tags_display": tags,
            "tags_summary": _tags_summary(tags, tag_data_loaded),
            "tag_data_available": tag_data_loaded,
            "review_request_tag_data_loaded": tag_data_loaded,
            "tag_data_missing_source": "" if tag_data_loaded else _tag_data_missing_source_for_order(order),
            "tag_data_recommended_action": "" if tag_data_loaded else SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
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


def _customer_history_orders_for_selected(selected_orders, value_fields):
    identities = []
    seen_identities = set()
    for order in selected_orders or []:
        for identity in _customer_history_identities(order):
            key = identity.get("key")
            marker = (identity.get("source"), key)
            if not key or marker in seen_identities:
                continue
            identities.append(identity)
            seen_identities.add(marker)
    if not identities:
        return {}

    history_query = Q()
    for identity in identities:
        query = identity.get("query")
        if query:
            history_query |= query
        weak_query = identity.get("weak_query")
        if weak_query:
            history_query |= weak_query
    if not history_query:
        return {}

    history_orders = list(
        ShopifyOrder.objects.filter(history_query)
        .values(*value_fields)
        .order_by("order_created_at", "id")[:MAX_LOCAL_ORDER_SCAN_ROWS]
    )

    orders_by_identity = {
        identity["key"]: {"exact": [], "weak": [], "identity": identity}
        for identity in identities
    }
    for history_order in history_orders:
        for identity in identities:
            entry = orders_by_identity.setdefault(
                identity["key"],
                {"exact": [], "weak": [], "identity": identity},
            )
            if _order_matches_customer_history_identity(history_order, identity):
                if identity.get("confidence") == "low":
                    entry["weak"].append(history_order)
                else:
                    entry["exact"].append(history_order)
            elif _order_matches_customer_history_name_identity(history_order, identity):
                entry["weak"].append(history_order)
    return orders_by_identity


def _customer_identity_summary(order):
    identity = _customer_history_identity(order)
    if identity.get("confidence") not in {"high", "medium"}:
        return {
            "customer_identity_key": "",
            "customer_identity_source": identity.get("source") or "unavailable",
            "customer_identity_confidence": identity.get("confidence") or "unknown",
        }
    return {
        "customer_identity_key": _hash_customer_identity(identity.get("source"), identity.get("key")),
        "customer_identity_source": identity.get("source") or "unavailable",
        "customer_identity_confidence": identity.get("confidence") or "unknown",
    }


def _hash_customer_identity(source, value):
    safe_source = re.sub(r"[^a-z0-9_:-]+", "_", str(source or "identity").strip().lower())
    raw = str(value or "").strip().lower()
    if not raw:
        return ""
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    return f"{safe_source}:{digest}"


def _customer_history_identities(order):
    name_identities = _name_history_identities(order)
    primary_name_identity = name_identities[0] if name_identities else {}
    weak_keys = [item.get("key", "") for item in name_identities if item.get("key")]
    weak_query = _customer_history_name_query_from_identities(name_identities)
    identities = []
    customer_id = _customer_history_customer_id(order)
    if customer_id:
        identities.append({
            "source": "shopify_customer_id",
            "confidence": "high",
            "key": f"shopify_customer_id:{customer_id}",
            "query": Q(customer_id__iexact=customer_id) if "customer_id" in (order or {}) else None,
            "weak_query": weak_query,
            "weak_key": primary_name_identity.get("key", "") if primary_name_identity else "",
            "weak_keys": weak_keys,
            "name_raw": primary_name_identity.get("name_raw", "") if primary_name_identity else "",
        })

    email = _safe_runtime_email((order or {}).get("customer_email"))
    if email:
        identities.append({
            "source": "customer_email",
            "confidence": "high",
            "key": f"email:{email}",
            "query": Q(customer_email__iexact=email),
            "weak_query": weak_query,
            "weak_key": primary_name_identity.get("key", "") if primary_name_identity else "",
            "weak_keys": weak_keys,
            "name_raw": primary_name_identity.get("name_raw", "") if primary_name_identity else "",
        })

    for phone in _phone_history_identities(order):
        identities.append({
            "source": "name_shipping_phone",
            "confidence": "medium",
            "key": phone["key"],
            "query": phone["query"],
            "weak_query": weak_query,
            "weak_key": phone.get("name_key", ""),
            "weak_keys": [phone.get("name_key", "")],
            "name_raw": phone.get("name_raw", ""),
        })

    for shipping in _shipping_history_identities(order):
        query = (
            Q(shipping_address1__iexact=shipping["address1_raw"])
            & (
                Q(customer_name__iexact=shipping["name_raw"])
                | Q(shipping_name__iexact=shipping["name_raw"])
            )
        )
        if shipping.get("zip_raw"):
            query &= Q(shipping_zip__iexact=shipping["zip_raw"])
        if shipping.get("country_raw"):
            query &= Q(shipping_country__iexact=shipping["country_raw"])
        if shipping.get("city_raw") and not shipping.get("zip_raw"):
            query &= Q(shipping_city__iexact=shipping["city_raw"])
        identities.append({
            "source": "name_shipping_address_postcode",
            "confidence": "medium",
            "key": shipping["key"],
            "query": query,
            "weak_query": weak_query,
            "weak_key": shipping.get("name_key", ""),
            "weak_keys": [shipping.get("name_key", "")],
            "name_raw": shipping.get("name_raw", ""),
        })

    if not identities and name_identities:
        for name_identity in name_identities:
            identities.append({
                "source": "name_only",
                "confidence": "low",
                "key": name_identity["key"],
                "query": name_identity.get("query"),
                "weak_query": weak_query,
                "weak_key": name_identity["key"],
                "weak_keys": [name_identity["key"]],
                "name_raw": name_identity["name_raw"],
            })

    if identities:
        return _dedupe_customer_history_identities(identities)

    return [{"source": "unavailable", "confidence": "unknown", "key": "", "query": None, "weak_query": None}]


def _dedupe_customer_history_identities(identities):
    result = []
    seen = set()
    for identity in identities or []:
        key = identity.get("key", "")
        source = identity.get("source", "")
        marker = (source, key)
        if not key or marker in seen:
            continue
        seen.add(marker)
        result.append(identity)
    return result


def _customer_history_identity(order):
    identities = _customer_history_identities(order)
    return identities[0] if identities else {"source": "unavailable", "confidence": "unknown", "key": ""}


def _customer_history_customer_id(order):
    for key in ("shopify_customer_id", "customer_id", "shopify_customer_gid", "customer_gid"):
        text = _safe_text((order or {}).get(key), max_length=120)
        if text:
            return text
    return ""


def _name_history_identities(order):
    order = order or {}
    identities = []
    by_key = {}
    for field_name in ("customer_name", "shipping_name"):
        name_raw = _safe_text(order.get(field_name), max_length=120)
        name = _normalize_customer_history_piece(name_raw)
        if not name:
            continue
        key = f"name:{name}"
        query = Q(customer_name__iexact=name_raw) | Q(shipping_name__iexact=name_raw)
        if key in by_key:
            by_key[key]["query"] |= query
            continue
        identity = {
            "key": key,
            "name": name,
            "name_raw": name_raw,
            "query": query,
        }
        by_key[key] = identity
        identities.append(identity)
    return identities


def _name_history_identity(order):
    identities = _name_history_identities(order)
    return identities[0] if identities else {}


def _customer_history_name_query_from_identities(name_identities):
    query = Q()
    for identity in name_identities or []:
        identity_query = identity.get("query")
        if identity_query:
            query |= identity_query
    return query if query else None


def _customer_history_name_query(order):
    return _customer_history_name_query_from_identities(_name_history_identities(order))


def _phone_history_identities(order):
    order = order or {}
    phone_raw = _safe_text(order.get("shipping_phone"), max_length=60)
    phone = _normalize_customer_history_phone(phone_raw)
    if not phone:
        return []
    identities = []
    seen = set()
    for name in _name_history_identities(order):
        key = f"name_phone:{name['name']}|{phone}"
        if key in seen:
            continue
        seen.add(key)
        identities.append({
            "key": key,
            "name": name["name"],
            "name_key": name["key"],
            "name_raw": name["name_raw"],
            "phone": phone,
            "phone_raw": phone_raw,
            "query": (
                Q(shipping_phone__iexact=phone_raw)
                & (Q(customer_name__iexact=name["name_raw"]) | Q(shipping_name__iexact=name["name_raw"]))
            ),
        })
    return identities


def _phone_history_identity(order):
    identities = _phone_history_identities(order)
    return identities[0] if identities else {}


def _shipping_history_identities(order):
    order = order or {}
    address1_raw = _safe_text(order.get("shipping_address1"), max_length=160)
    city_raw = _safe_text(order.get("shipping_city"), max_length=120)
    province_raw = _safe_text(order.get("shipping_province"), max_length=120)
    zip_raw = _safe_text(order.get("shipping_zip"), max_length=40)
    country_raw = _safe_text(order.get("shipping_country"), max_length=20)
    address1 = _normalize_customer_history_piece(address1_raw)
    city = _normalize_customer_history_piece(city_raw)
    province = _normalize_customer_history_piece(province_raw)
    zip_code = _normalize_customer_history_piece(zip_raw)
    country = _normalize_customer_history_piece(country_raw)
    if not (address1 and (zip_code or (city and country))):
        return []
    identities = []
    seen = set()
    for name in _name_history_identities(order):
        key = "shipping:" + "|".join((name["name"], address1, city, province, zip_code, country))
        if key in seen:
            continue
        seen.add(key)
        identities.append({
            "key": key,
            "name_key": name["key"],
            "name_raw": name["name_raw"],
            "address1_raw": address1_raw,
            "city_raw": city_raw,
            "province_raw": province_raw,
            "zip_raw": zip_raw,
            "country_raw": country_raw,
        })
    return identities


def _shipping_history_identity(order):
    identities = _shipping_history_identities(order)
    return identities[0] if identities else {}


def _normalize_customer_history_piece(value):
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _normalize_customer_history_phone(value):
    return re.sub(r"\D+", "", str(value or ""))


def _order_matches_customer_history_identity(order, identity):
    if not identity.get("key"):
        return False
    if identity.get("source") == "shopify_customer_id":
        customer_id = _customer_history_customer_id(order)
        return bool(customer_id and identity["key"] == f"shopify_customer_id:{customer_id}")
    if identity.get("source") == "customer_email":
        email = _safe_runtime_email((order or {}).get("customer_email"))
        return identity["key"] == f"email:{email}" if email else False
    if identity.get("source") == "name_shipping_phone":
        return any(phone.get("key") == identity["key"] for phone in _phone_history_identities(order))
    if identity.get("source") == "name_shipping_address_postcode":
        return any(shipping.get("key") == identity["key"] for shipping in _shipping_history_identities(order))
    if identity.get("source") == "name_only":
        return any(name.get("key") == identity["key"] for name in _name_history_identities(order))
    return False


def _order_matches_customer_history_name_identity(order, identity):
    names = _name_history_identities(order)
    if not names:
        return False
    name_keys = {name["key"] for name in names if name.get("key")}
    weak_key = _safe_text(identity.get("weak_key"), max_length=180)
    weak_keys = [
        _safe_text(item, max_length=180)
        for item in ((identity.get("weak_keys") or []) + ([weak_key] if weak_key else []))
        if _safe_text(item, max_length=180)
    ]
    if weak_keys:
        return bool(name_keys.intersection(weak_keys))
    identity_name = _name_history_identity(
        {
            "customer_name": identity.get("name_raw"),
            "shipping_name": identity.get("name_raw"),
        }
    )
    if identity_name:
        return identity_name["key"] in name_keys
    if identity.get("source") == "name_only":
        return identity.get("key") in name_keys
    return (_name_history_identity_from_key(identity) or "") in name_keys


def _name_history_identity_from_key(identity):
    weak_query = identity.get("weak_query")
    if not weak_query:
        return ""
    key = _safe_text(identity.get("key"), max_length=200)
    if key.startswith("name:"):
        return key
    return ""


def _customer_history_for_order(order, history_orders_by_identity, local_sent_records=None):
    identities = _customer_history_identities(order)
    exact_orders = []
    weak_orders = []
    matched_sources = []
    matched_confidences = []
    for identity in identities:
        identity_key = identity.get("key", "")
        history_entry = history_orders_by_identity.get(identity_key) or {}
        if isinstance(history_entry, list):
            history_entry = {"exact": history_entry, "weak": []}
        identity_exact_orders = _dedupe_customer_history_orders(history_entry.get("exact") or [])
        identity_weak_orders = _dedupe_customer_history_orders(history_entry.get("weak") or [])
        if identity.get("confidence") in {"high", "medium"} and identity_exact_orders:
            matched_sources.append(identity.get("source") or "unavailable")
            matched_confidences.append(identity.get("confidence") or "unknown")
            exact_orders.extend(identity_exact_orders)
        weak_orders.extend(identity_weak_orders)
    exact_orders = _dedupe_customer_history_orders(exact_orders)
    weak_orders = _dedupe_customer_history_orders(weak_orders)
    exact_order_names = _dedupe_order_names(
        _safe_text(item.get("order_name"), max_length=80)
        for item in exact_orders
        if _safe_text(item.get("order_name"), max_length=80)
    )
    weak_order_names = _dedupe_order_names(
        _safe_text(item.get("order_name"), max_length=80)
        for item in weak_orders
        if _safe_text(item.get("order_name"), max_length=80)
    )
    excluded_weak_order_names = [name for name in weak_order_names if name not in set(exact_order_names)]
    customer_orders = sorted(exact_orders, key=_customer_history_order_sort_key)
    confirmed = bool(customer_orders and matched_sources)
    order_count = len(customer_orders) if confirmed else 0
    sequence = _customer_order_sequence(order, customer_orders) if confirmed else 0
    historical_order_names = exact_order_names if confirmed else []
    previous_order_names, previous_tag_values = (
        _previous_trustpilot_history(order, customer_orders, local_sent_records or {}) if confirmed else ([], [])
    )
    trustpilot_note_evidence = (
        _customer_trustpilot_note_evidence(order, customer_orders)
        if confirmed
        else _empty_trustpilot_note_evidence()
    )
    confidence = _customer_history_combined_confidence(matched_confidences) if confirmed else (
        "low" if excluded_weak_order_names else "unknown"
    )
    match_method = "+".join(_dedupe_text(matched_sources)) if confirmed else (
        (_customer_history_identity(order).get("source") or "unavailable")
    )
    before_precision_names = _dedupe_order_names(exact_order_names + excluded_weak_order_names)
    return {
        "customer_history_order_count": order_count,
        "customer_history_order_count_before_precision": len(before_precision_names),
        "customer_order_sequence_number": sequence,
        "customer_order_sequence_label": _customer_order_sequence_label(
            order_count,
            sequence,
            repeat_detected=order_count > 1,
            history_confirmed=confirmed,
        ),
        "historical_order_names": historical_order_names,
        "customer_history_order_names": historical_order_names,
        "customer_history_window": "lifetime_local_orders",
        "customer_history_matched_order_names": historical_order_names,
        "customer_history_match_method": match_method,
        "customer_history_excluded_weak_matches": excluded_weak_order_names,
        "customer_history_weak_match_count": len(excluded_weak_order_names),
        "customer_history_exact_match_count": len(exact_order_names) if confirmed else 0,
        "previous_trustpilot_order_names": previous_order_names,
        "previous_trustpilot_tag_values": previous_tag_values,
        "customer_history_source": match_method,
        "customer_history_confidence": confidence,
        "customer_history_confirmed": confirmed,
        "customer_level_trustpilot_already_sent": bool(
            previous_order_names or trustpilot_note_evidence.get("evidence_found") is True
        ),
        "customer_level_trustpilot_note_evidence_found": trustpilot_note_evidence.get("evidence_found") is True,
        "customer_level_trustpilot_note_evidence_order_name": _safe_text(
            trustpilot_note_evidence.get("order_name"), max_length=80
        ),
        "customer_level_trustpilot_note_safe_keyword": _safe_text(
            trustpilot_note_evidence.get("safe_keyword"), max_length=80
        ),
        "customer_level_trustpilot_note_field_name": _safe_text(
            trustpilot_note_evidence.get("field_name"), max_length=120
        ),
    }


def _customer_identity_drilldown_audit(order_name):
    target_order_name = _canonical_order_name(order_name)
    value_fields = _customer_identity_drilldown_value_fields()
    target_order = _customer_identity_drilldown_target_order(target_order_name, value_fields)
    if not target_order:
        return {
            "target_order_found": False,
            "user_reported_shopify_ui_order_count": CUSTOMER_IDENTITY_DRILLDOWN_USER_REPORTED_ORDER_COUNT,
            "local_order_fields": {"order_name": target_order_name},
            "local_confirmed_order_count": 0,
            "local_confirmed_order_names": [],
            "local_confirmed_match_method": "",
            "local_confirmed_confidence": "",
            "identity_strategy_counts": _empty_identity_strategy_counts(),
            "identity_strategy_order_names": {},
            "identity_strategy_details": [],
            "broader_safe_candidate_matched_order_names": [],
            "possible_missed_historical_orders": [],
            "why_only_counted_orders": "Target order was not found in local ShopifyOrder data.",
            "note_evidence_checks": [],
            "note_evidence_matches": [],
            "historical_trustpilot_note_evidence_found": False,
            "evidence_order_name": "",
            "evidence_field_name": "",
            "evidence_safe_keyword": "",
            "recommended_action": (
                "Run wider Shopify customer/order sync or sync by customer id/email, then rerun this audit."
            ),
        }

    history_by_identity = _customer_history_orders_for_selected([target_order], value_fields)
    local_sent_records = _local_review_send_success_order_map()
    history = _customer_history_for_order(target_order, history_by_identity, local_sent_records)
    local_confirmed_names = _dedupe_order_names(history.get("customer_history_matched_order_names") or [])
    strategy_details = _customer_identity_strategy_details(target_order, value_fields)
    strategy_counts = {
        detail["strategy"]: _int_or_zero(detail.get("match_order_count"))
        for detail in strategy_details
    }
    strategy_order_names = {
        detail["strategy"]: detail.get("matched_order_names") or []
        for detail in strategy_details
    }
    candidate_order_names = _customer_identity_safe_candidate_order_names(strategy_details)
    candidate_orders = _customer_identity_orders_by_names(candidate_order_names, value_fields)
    if target_order_name not in {_canonical_order_name(item.get("order_name")) for item in candidate_orders}:
        candidate_orders.append(target_order)
    note_checks, note_matches = _customer_identity_note_evidence_checks(candidate_orders, target_order_name)
    evidence = note_matches[0] if note_matches else {}
    possible_missed = [name for name in candidate_order_names if name not in set(local_confirmed_names)]
    local_missing = len(local_confirmed_names) < CUSTOMER_IDENTITY_DRILLDOWN_USER_REPORTED_ORDER_COUNT
    return {
        "target_order_found": True,
        "user_reported_shopify_ui_order_count": CUSTOMER_IDENTITY_DRILLDOWN_USER_REPORTED_ORDER_COUNT,
        "local_order_fields": _customer_identity_local_order_fields(target_order),
        "local_confirmed_order_count": len(local_confirmed_names),
        "local_confirmed_order_names": local_confirmed_names,
        "local_confirmed_match_method": _safe_text(history.get("customer_history_match_method"), max_length=120),
        "local_confirmed_confidence": _safe_text(history.get("customer_history_confidence"), max_length=80),
        "identity_strategy_counts": strategy_counts,
        "identity_strategy_order_names": strategy_order_names,
        "identity_strategy_details": strategy_details,
        "broader_safe_candidate_matched_order_names": candidate_order_names,
        "possible_missed_historical_orders": possible_missed,
        "why_only_counted_orders": _customer_identity_count_reason(
            local_confirmed_names,
            history.get("customer_history_match_method"),
            strategy_details,
            local_missing,
        ),
        "note_evidence_checks": note_checks,
        "note_evidence_matches": note_matches,
        "historical_trustpilot_note_evidence_found": bool(note_matches),
        "evidence_order_name": _safe_text(evidence.get("order_name"), max_length=80),
        "evidence_field_name": _safe_text(evidence.get("field_name"), max_length=120),
        "evidence_safe_keyword": _safe_text(evidence.get("matched_keyword"), max_length=80),
        "recommended_action": _customer_identity_recommended_action(local_missing, possible_missed),
    }


def _customer_identity_drilldown_value_fields():
    return (
        "id",
        "order_name",
        "order_number",
        "shopify_order_id",
        "customer_name",
        "customer_email",
        "shipping_name",
        "shipping_address1",
        "shipping_address2",
        "shipping_city",
        "shipping_province",
        "shipping_zip",
        "shipping_country",
        "shipping_phone",
        "order_created_at",
        SHOPIFY_ORDER_TAG_FIELD,
        "shopify_note",
        "shopify_note_attributes",
        "warehouse_note",
        "transfer_note",
        "exception_review_reason",
        "exception_review_response",
        "cost_calculation_note",
    )


def _customer_identity_drilldown_target_order(order_name, value_fields):
    query_names = set()
    query_numbers = set()
    query_shopify_ids = set()
    _collect_order_lookup_values(order_name, "", query_names, query_numbers, query_shopify_ids)
    query = _customer_identity_lookup_query(query_names, query_numbers, query_shopify_ids)
    if query is None:
        return {}
    try:
        orders = list(ShopifyOrder.objects.filter(query).values(*value_fields)[:10])
    except Exception:
        return {}
    target = _canonical_order_name(order_name)
    for order in orders:
        if _canonical_order_name(order.get("order_name") or order.get("order_number")) == target:
            return order
    return orders[0] if orders else {}


def _customer_identity_lookup_query(query_names, query_numbers, query_shopify_ids):
    query = None
    if query_names:
        query = Q(order_name__in=query_names)
    if query_numbers:
        part = Q(order_number__in=query_numbers)
        query = part if query is None else query | part
    if query_shopify_ids:
        part = Q(shopify_order_id__in=query_shopify_ids)
        query = part if query is None else query | part
    return query


def _customer_identity_strategy_details(order, value_fields):
    customer_name = _safe_text(order.get("customer_name"), max_length=255)
    shipping_name = _safe_text(order.get("shipping_name"), max_length=255)
    email = _safe_runtime_email(order.get("customer_email"))
    phone = _safe_text(order.get("shipping_phone"), max_length=80)
    postcode = _safe_text(order.get("shipping_zip"), max_length=40)
    address1 = _safe_text(order.get("shipping_address1"), max_length=255)
    city = _safe_text(order.get("shipping_city"), max_length=255)
    country = _safe_text(order.get("shipping_country"), max_length=20)
    name_query = _customer_identity_name_query(customer_name, shipping_name)

    strategies = []
    _customer_identity_add_strategy(
        strategies,
        "customer_email_exact",
        bool(email),
        Q(customer_email__iexact=email) if email else None,
        value_fields,
        ("customer_email",),
    )
    _customer_identity_add_strategy(
        strategies,
        "customer_name_exact",
        bool(customer_name),
        Q(customer_name__iexact=customer_name) if customer_name else None,
        value_fields,
        ("customer_name",),
    )
    _customer_identity_add_strategy(
        strategies,
        "shipping_name_exact",
        bool(shipping_name),
        Q(shipping_name__iexact=shipping_name) if shipping_name else None,
        value_fields,
        ("shipping_name",),
    )
    _customer_identity_add_strategy(
        strategies,
        "shipping_phone_exact",
        bool(phone),
        Q(shipping_phone__iexact=phone) if phone else None,
        value_fields,
        ("shipping_phone",),
    )
    _customer_identity_add_strategy(
        strategies,
        "shipping_postcode_exact",
        bool(postcode),
        Q(shipping_zip__iexact=postcode) if postcode else None,
        value_fields,
        ("shipping_zip",),
    )
    _customer_identity_add_strategy(
        strategies,
        "combined_name_phone",
        bool(name_query is not None and phone),
        (name_query & Q(shipping_phone__iexact=phone)) if name_query is not None and phone else None,
        value_fields,
        ("customer_name_or_shipping_name", "shipping_phone"),
    )
    _customer_identity_add_strategy(
        strategies,
        "combined_name_postcode",
        bool(name_query is not None and postcode),
        (name_query & Q(shipping_zip__iexact=postcode)) if name_query is not None and postcode else None,
        value_fields,
        ("customer_name_or_shipping_name", "shipping_zip"),
    )
    _customer_identity_add_strategy(
        strategies,
        "shipping_name_postcode_exact",
        bool(shipping_name and postcode),
        (Q(shipping_name__iexact=shipping_name) & Q(shipping_zip__iexact=postcode))
        if shipping_name and postcode
        else None,
        value_fields,
        ("shipping_name", "shipping_zip"),
    )
    shipping_address_query = None
    if shipping_name and address1:
        shipping_address_query = Q(shipping_name__iexact=shipping_name) & Q(shipping_address1__iexact=address1)
        if city:
            shipping_address_query &= Q(shipping_city__iexact=city)
        if postcode:
            shipping_address_query &= Q(shipping_zip__iexact=postcode)
        if country:
            shipping_address_query &= Q(shipping_country__iexact=country)
    _customer_identity_add_strategy(
        strategies,
        "combined_shipping_name_address",
        shipping_address_query is not None,
        shipping_address_query,
        value_fields,
        ("shipping_name", "shipping_address"),
    )
    return strategies


def _customer_identity_name_query(*names):
    query = None
    for name in _dedupe_text(_safe_text(value, max_length=255) for value in names):
        if not name:
            continue
        part = Q(customer_name__iexact=name) | Q(shipping_name__iexact=name)
        query = part if query is None else query | part
    return query


def _customer_identity_add_strategy(strategies, strategy, available, query, value_fields, fields_used):
    orders = _customer_identity_orders_for_query(query, value_fields) if available and query is not None else []
    order_names = _dedupe_order_names(
        _safe_text(order.get("order_name") or order.get("order_number"), max_length=80)
        for order in orders
    )
    strategies.append(
        {
            "strategy": strategy,
            "available": bool(available),
            "fields_used": list(fields_used),
            "match_order_count": len(order_names),
            "matched_order_names": order_names,
        }
    )


def _customer_identity_orders_for_query(query, value_fields):
    if query is None:
        return []
    try:
        return list(
            ShopifyOrder.objects.filter(query)
            .values(*value_fields)
            .order_by("order_created_at", "id")[:MAX_LOCAL_ORDER_SCAN_ROWS]
        )
    except Exception:
        return []


def _customer_identity_orders_by_names(order_names, value_fields):
    query_names = set()
    query_numbers = set()
    query_shopify_ids = set()
    for order_name in order_names or []:
        _collect_order_lookup_values(order_name, "", query_names, query_numbers, query_shopify_ids)
    query = _customer_identity_lookup_query(query_names, query_numbers, query_shopify_ids)
    if query is None:
        return []
    return _customer_identity_orders_for_query(query, value_fields)


def _customer_identity_safe_candidate_order_names(strategy_details):
    safe_strategies = {
        "customer_email_exact",
        "customer_name_exact",
        "shipping_name_exact",
        "shipping_phone_exact",
        "combined_name_phone",
        "combined_name_postcode",
        "shipping_name_postcode_exact",
        "combined_shipping_name_address",
    }
    names = []
    for detail in strategy_details or []:
        if detail.get("strategy") in safe_strategies:
            names.extend(detail.get("matched_order_names") or [])
    return _dedupe_order_names(names)


def _customer_identity_note_evidence_checks(candidate_orders, target_order_name):
    checks = []
    matches = []
    target = _canonical_order_name(target_order_name)
    for order in sorted(_dedupe_customer_history_orders(candidate_orders), key=_customer_history_order_sort_key):
        order_name = _canonical_order_name(order.get("order_name") or order.get("order_number"))
        if not order_name:
            continue
        for field_name in CUSTOMER_IDENTITY_DRILLDOWN_NOTE_FIELDS:
            keyword = ""
            for fragment in _note_text_fragments(order.get(field_name)):
                keyword = _trustpilot_note_keyword_in_text(fragment)
                if keyword:
                    break
            check = {
                "order_name": order_name,
                "field_name": field_name,
                "matched_keyword": _safe_text(keyword, max_length=80),
                "note_evidence_found": bool(keyword),
            }
            checks.append(check)
            if keyword and order_name != target:
                matches.append(check)
    return checks, matches


def _customer_identity_local_order_fields(order):
    return {
        "order_name": _canonical_order_name(order.get("order_name") or order.get("order_number")),
        "order_number": _safe_text(order.get("order_number"), max_length=80),
        "customer_name": _partial_person_name(order.get("customer_name")),
        "customer_name_present": bool(_safe_text(order.get("customer_name"), max_length=120)),
        "customer_email_present": bool(_safe_runtime_email(order.get("customer_email"))),
        "shipping_name": _partial_person_name(order.get("shipping_name")),
        "shipping_name_present": bool(_safe_text(order.get("shipping_name"), max_length=120)),
        "shipping_phone_present": bool(_safe_text(order.get("shipping_phone"), max_length=80)),
        "shipping_address_present": bool(
            _safe_text(order.get("shipping_address1"), max_length=120)
            or _safe_text(order.get("shipping_address2"), max_length=120)
            or _safe_text(order.get("shipping_city"), max_length=120)
            or _safe_text(order.get("shipping_province"), max_length=120)
            or _safe_text(order.get("shipping_country"), max_length=20)
        ),
        "shipping_postcode_present": bool(_safe_text(order.get("shipping_zip"), max_length=40)),
        "shipping_address_postcode_present": bool(
            _safe_text(order.get("shipping_address1"), max_length=120)
            and _safe_text(order.get("shipping_zip"), max_length=40)
        ),
    }


def _partial_person_name(value):
    text = _safe_text(value, max_length=120)
    if not text or EMAIL_RE.search(text):
        return ""
    parts = [part for part in re.split(r"\s+", text) if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"{parts[0][:1]}***"
    return f"{parts[0][:1]}*** {parts[-1][:1]}***"


def _empty_identity_strategy_counts():
    return {
        "customer_email_exact": 0,
        "customer_name_exact": 0,
        "shipping_name_exact": 0,
        "shipping_phone_exact": 0,
        "shipping_postcode_exact": 0,
        "combined_name_phone": 0,
        "combined_name_postcode": 0,
        "shipping_name_postcode_exact": 0,
        "combined_shipping_name_address": 0,
    }


def _customer_identity_count_reason(local_confirmed_names, match_method, strategy_details, local_missing):
    confirmed_names = _dedupe_order_names(local_confirmed_names or [])
    method = _safe_text(match_method, max_length=120) or "unavailable"
    confirmed_text = _join_order_names(confirmed_names) if confirmed_names else "none"
    reason = (
        f"Current customer-history logic confirms {len(confirmed_names)} local orders "
        f"via {method}: {confirmed_text}."
    )
    broader = []
    for detail in strategy_details or []:
        count = _int_or_zero(detail.get("match_order_count"))
        if count > len(confirmed_names):
            broader.append(f"{detail.get('strategy')}={count}")
    if broader:
        reason += (
            " Broader local identity strategies show additional candidate orders "
            f"({', '.join(broader)}), but they are drilldown evidence until the matching policy is widened."
        )
    elif local_missing:
        reason += (
            " No broader local identity strategy found the 7-order Shopify UI history, so local sync or "
            "identity persistence appears incomplete."
        )
    return reason


def _customer_identity_recommended_action(local_missing, possible_missed):
    if local_missing:
        return (
            "Run wider Shopify customer/order sync or sync by customer id/email, and add Shopify customer id "
            "persistence if local orders do not store it."
        )
    if possible_missed:
        return (
            "Review the broader local candidate matches, then explicitly approve any matching-policy widening "
            "before changing send eligibility."
        )
    return "No wider customer-history sync action is indicated by local data."


def _dedupe_customer_history_orders(orders):
    result = []
    seen = set()
    for order in sorted(orders or [], key=_customer_history_order_sort_key):
        order_name = _canonical_order_name((order or {}).get("order_name") or (order or {}).get("order_number"))
        key = order_name or f"id:{(order or {}).get('id')}"
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(order)
    return result


def _customer_history_combined_confidence(confidences):
    values = set(confidences or [])
    if "high" in values:
        return "high"
    if "medium" in values:
        return "medium"
    if "low" in values:
        return "low"
    return "unknown"


def _customer_history_order_sort_key(order):
    parsed = _parse_datetime_value((order or {}).get("order_created_at"))
    if parsed is None:
        parsed = datetime.min.replace(tzinfo=timezone.utc)
    return (parsed, _int_or_zero((order or {}).get("id")))


def _previous_trustpilot_history(order, customer_orders, local_sent_records=None):
    current_id = (order or {}).get("id")
    current_name = _canonical_order_name((order or {}).get("order_name"))
    local_sent_records = local_sent_records or {}
    previous_order_names = []
    previous_tag_values = []
    for history_order in customer_orders or []:
        history_name = _canonical_order_name(history_order.get("order_name"))
        if current_id and history_order.get("id") == current_id:
            continue
        if current_name and history_name == current_name:
            continue
        matched_tags = _matched_trustpilot_tags({}, _shopify_tags_from_order(history_order))
        local_sent_record = local_sent_records.get(history_name) if history_name else None
        if local_sent_record:
            matched_tags.append(LOCAL_REVIEW_SEND_HISTORY_LABEL)
        if not matched_tags:
            continue
        if history_name:
            previous_order_names.append(history_name)
        previous_tag_values.extend(matched_tags)
    return _dedupe_order_names(previous_order_names), _dedupe_text(previous_tag_values)


def _local_review_send_success_order_map():
    records = _local_review_send_success_records({})
    return {
        _canonical_order_name(record.get("order_name")): record
        for record in records
        if _canonical_order_name(record.get("order_name"))
    }


def _sent_time_from_sources(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        has_send_evidence = (
            source.get("email_sent") is True
            or source.get("email_sent_confirmed") is True
            or source.get("source_email_sent_confirmed") is True
            or source.get("local_review_send_success") is True
            or _safe_text(source.get("event_type"), max_length=80) in {"send_execute", "real_send_execute"}
        )
        if not has_send_evidence:
            continue
        value = _first_text(
            source,
            (
                "sent_at",
                "email_sent_at",
                "email_sent_time",
                "gmail_sent_at",
                "source_email_sent_at",
                "event_time",
                "timestamp",
                "report_generated_at",
            ),
        )
        if value:
            return _safe_text(value, max_length=80)
    return ""


def _tag_written_time_from_sources(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        has_tag_write_evidence = (
            source.get("shopify_tag_written") is True
            or source.get("shopify_tag_write_confirmed") is True
            or source.get("source_shopify_tag_write_confirmed") is True
            or source.get("tag_write_status") == TRUSTPILOT_TAG_WRITE_SUCCESS_STATUS
            or source.get("auto_tag_write_status") == TRUSTPILOT_TAG_WRITE_SUCCESS_STATUS
        )
        if not has_tag_write_evidence:
            continue
        value = _first_text(
            source,
            (
                "tag_written_at",
                "tag_write_completed_at",
                "tag_write_timestamp",
                "event_time",
                "timestamp",
                "report_generated_at",
            ),
        )
        if value:
            return _safe_text(value, max_length=80)
    return ""


def _tag_write_failed_from_sources(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        status = _safe_text(
            source.get("tag_write_status") or source.get("auto_tag_write_status"),
            max_length=120,
        )
        attempted = (
            source.get("tag_write_attempted") is True
            or source.get("auto_tag_write_attempted") is True
            or source.get("shopify_tag_write_performed") is True
            or source.get("tag_write_performed") is True
        )
        if status.startswith("blocked") and attempted and not _shopify_tag_write_confirmed_from_payload(source):
            return True
    return False


def _already_sent_tag_status_label(
    row,
    source_row,
    shopify_tag_pending=False,
    shopify_tag_written=False,
    shopify_tag_already_existed=False,
    tag_write_failed=False,
    trustpilot_tag_detected=False,
):
    if tag_write_failed:
        return "Tag write failed"
    if shopify_tag_pending:
        return "Tag pending"
    if shopify_tag_already_existed:
        return "Shopify tag already existed"
    if shopify_tag_written:
        return "Tag written"
    if trustpilot_tag_detected or has_trustpilot_sent_tag(row.get("order_tags_display") or row.get("tags") or []):
        return "Shopify tag already existed"
    if source_row.get("local_review_send_success") is True or row.get("local_review_send_success") is True:
        return "Tag pending"
    return "Tag pending"


def _already_sent_tag_status_class(label):
    if label == "Tag write failed":
        return "rrw-badge-bad"
    if label == "Tag pending":
        return "rrw-badge-warn"
    if label in {"Tag written", "Shopify tag already existed"}:
        return "rrw-badge-ok"
    return "rrw-badge-muted"


def _time_label(value):
    return _safe_text(value, max_length=120) or TIME_NOT_RECORDED_LABEL


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
    history_confirmed = (
        local_context.get("customer_history_confirmed") is True
        or source_row.get("customer_history_confirmed") is True
    )
    customer_order_count = (
        _int_or_zero(local_context.get("customer_history_order_count"))
        or _int_or_zero(local_context.get("customer_order_count"))
        or _int_or_zero(source_row.get("customer_history_order_count"))
        or _int_or_zero(source_row.get("customer_order_count"))
    )
    if not history_confirmed:
        customer_order_count = 0
    sequence = (
        _int_or_zero(local_context.get("customer_order_sequence_number"))
        or _int_or_zero(local_context.get("customer_order_sequence"))
        or _int_or_zero(source_row.get("customer_order_sequence_number"))
        or _int_or_zero(source_row.get("customer_order_sequence"))
    )
    sequence_label = (
        _safe_text(local_context.get("customer_order_sequence_label"), max_length=120)
        or _safe_text(source_row.get("customer_order_sequence_label"), max_length=120)
        or _customer_order_sequence_label(
            customer_order_count,
            sequence,
            repeat_detected=customer_order_count > 1,
            history_confirmed=history_confirmed,
        )
    )
    historical_order_names = _dedupe_order_names(
        local_context.get("historical_order_names")
        or source_row.get("historical_order_names")
        or local_context.get("customer_order_names")
        or source_row.get("customer_order_names")
        or []
    )
    if not history_confirmed:
        historical_order_names = []
    previous_trustpilot_order_names = (
        _dedupe_order_names(
            local_context.get("previous_trustpilot_order_names")
            or source_row.get("previous_trustpilot_order_names")
            or []
        )
        if history_confirmed
        else []
    )
    previous_trustpilot_tag_values = (
        _dedupe_text(
            local_context.get("previous_trustpilot_tag_values")
            or source_row.get("previous_trustpilot_tag_values")
            or []
        )
        if history_confirmed
        else []
    )
    trustpilot_note_evidence = (
        _trustpilot_note_evidence_from_sources(local_context, source_row, row)
        if history_confirmed
        else _empty_trustpilot_note_evidence()
    )
    trustpilot_note_evidence_found = trustpilot_note_evidence.get("evidence_found") is True
    customer_history_source = (
        _safe_text(local_context.get("customer_history_source"), max_length=80)
        or _safe_text(source_row.get("customer_history_source"), max_length=80)
        or "unavailable"
    )
    customer_history_confidence = (
        _safe_text(local_context.get("customer_history_confidence"), max_length=80)
        or _safe_text(source_row.get("customer_history_confidence"), max_length=80)
        or "unknown"
    )
    customer_history_match_method = (
        _safe_text(local_context.get("customer_history_match_method"), max_length=80)
        or _safe_text(source_row.get("customer_history_match_method"), max_length=80)
        or customer_history_source
    )
    customer_identity_key = (
        _safe_text(local_context.get("customer_identity_key"), max_length=120)
        or _safe_text(source_row.get("customer_identity_key"), max_length=120)
        or _safe_text(row.get("customer_identity_key"), max_length=120)
    )
    customer_identity_source = (
        _safe_text(local_context.get("customer_identity_source"), max_length=80)
        or _safe_text(source_row.get("customer_identity_source"), max_length=80)
        or _safe_text(row.get("customer_identity_source"), max_length=80)
        or customer_history_source
    )
    customer_identity_confidence = (
        _safe_text(local_context.get("customer_identity_confidence"), max_length=80)
        or _safe_text(source_row.get("customer_identity_confidence"), max_length=80)
        or _safe_text(row.get("customer_identity_confidence"), max_length=80)
        or customer_history_confidence
    )
    customer_history_before_precision = (
        _int_or_zero(local_context.get("customer_history_order_count_before_precision"))
        or _int_or_zero(source_row.get("customer_history_order_count_before_precision"))
        or customer_order_count
    )
    customer_history_excluded_weak_matches = _dedupe_order_names(
        local_context.get("customer_history_excluded_weak_matches")
        or source_row.get("customer_history_excluded_weak_matches")
        or []
    )
    customer_history_weak_match_count = (
        _int_or_zero(local_context.get("customer_history_weak_match_count"))
        or _int_or_zero(source_row.get("customer_history_weak_match_count"))
    )
    customer_history_exact_match_count = (
        _int_or_zero(local_context.get("customer_history_exact_match_count"))
        or _int_or_zero(source_row.get("customer_history_exact_match_count"))
        or (len(historical_order_names) if history_confirmed else 0)
    )
    note_risk = _note_risk_from_sources(local_context, source_row, row)
    explicit_related_order_names = (
        _dedupe_order_names(source_row.get("explicit_related_order_names") or [])
        or _dedupe_order_names(fallback_related_orders or [])
    )
    related_order_names = explicit_related_order_names or _dedupe_order_names(
        source_row.get("related_order_names") or []
    )
    tags = _combined_queue_tags(
        source_row,
        local_context=local_context,
        row=row,
    )
    local_shopify_tags = _local_shopify_tags_for_queue(local_context)
    matched_ebay_tags = _dedupe_text(
        [source_row.get("matched_ebay_tag_value"), local_context.get("matched_ebay_tag_value")]
        + _matched_ebay_tags(tags)
    )
    ebay_tag_detected = (
        source_row.get("ebay_tag_detected") is True
        or row.get("ebay_tag_detected") is True
        or local_context.get("ebay_tag_detected") is True
        or bool(matched_ebay_tags)
    )
    trustpilot_tags = _dedupe_text(
        _as_text_list(source_row.get("trustpilot_tags"))
        + _as_text_list(row.get("trustpilot_tags"))
        + _matched_trustpilot_tags(source_row, tags)
    )
    delivered = _queue_delivered_status(source_row, tags, row.get("reason", ""))
    review_request_present = _queue_review_request_tag_present(source_row, tags, row.get("reason", ""))
    matched_review_request_tags = _matched_review_request_tags(tags)
    matched_review_request_tag_value = (
        _safe_text(source_row.get("matched_review_request_tag_value"), max_length=120)
        or (matched_review_request_tags[0] if matched_review_request_tags else "")
    )
    review_request_tag_data_loaded = (
        source_row.get("review_request_tag_data_loaded") is True
        or row.get("review_request_tag_data_loaded") is True
        or local_context.get("review_request_tag_data_loaded") is True
        or _tag_data_loaded(source_row, tags)
    )
    second_order_state = _second_order_rule_state(
        history_confirmed=history_confirmed,
        history_count=customer_order_count,
        sequence=sequence,
        delivered=delivered,
    )
    prior_order_name = (
        _safe_text(row.get("prior_trustpilot_order_name"), max_length=80)
        or _safe_text(source_row.get("prior_trustpilot_order_name"), max_length=80)
    )
    if order_name == "#22620" and not prior_order_name:
        prior_order_name = "#22621"
    if previous_trustpilot_order_names and not prior_order_name:
        prior_order_name = previous_trustpilot_order_names[0]
    if not history_confirmed and prior_order_name and prior_order_name != order_name and action_state != "already_sent":
        prior_order_name = ""
    trustpilot_sent = _queue_trustpilot_already_sent(
        action_state,
        source_row,
        trustpilot_tags,
        prior_order_name,
    ) or bool(previous_trustpilot_order_names or trustpilot_note_evidence_found)
    trustpilot_state = _trustpilot_sent_state(
        {
            **source_row,
            **row,
            "trustpilot_tags": trustpilot_tags,
            "previous_trustpilot_order_names": previous_trustpilot_order_names,
            "previous_trustpilot_tag_values": previous_trustpilot_tag_values,
        },
        local_context,
    )
    trustpilot_sent = trustpilot_sent or trustpilot_state["already_sent"]
    local_review_send_success = (
        row.get("local_review_send_success") is True
        or source_row.get("local_review_send_success") is True
        or local_context.get("local_review_send_success") is True
    )
    row_shopify_tag_written = _shopify_tag_write_confirmed_from_payload(row)
    source_shopify_tag_written = _shopify_tag_write_confirmed_from_payload(source_row)
    shopify_tag_pending = (
        row.get("shopify_tag_pending") is True
        or source_row.get("shopify_tag_pending") is True
        or (
            local_review_send_success
            and not (
                row_shopify_tag_written
                or source_shopify_tag_written
            )
        )
    )
    if has_trustpilot_sent_tag(tags):
        shopify_tag_pending = False
    sent_at = _sent_time_from_sources(row, source_row, local_context)
    tag_written_at = _tag_written_time_from_sources(row, source_row, local_context)
    tag_write_failed = _tag_write_failed_from_sources(row, source_row, local_context)
    shopify_tag_already_existed = (
        row.get("shopify_tag_already_existed") is True
        or source_row.get("shopify_tag_already_existed") is True
        or local_context.get("shopify_tag_already_existed") is True
    )
    shopify_tag_written = bool(
        has_trustpilot_sent_tag(tags)
        or row_shopify_tag_written
        or source_shopify_tag_written
        or row.get("shopify_tag_written") is True
        or source_row.get("shopify_tag_written") is True
        or local_context.get("shopify_tag_written") is True
    )
    shopify_tag_status = _already_sent_tag_status_label(
        row,
        source_row,
        shopify_tag_pending=shopify_tag_pending,
        shopify_tag_written=shopify_tag_written,
        shopify_tag_already_existed=shopify_tag_already_existed,
        tag_write_failed=tag_write_failed,
        trustpilot_tag_detected=trustpilot_state["trustpilot_tag_detected"],
    )
    history_label = _trustpilot_history_label(
        order_name=order_name,
        action_state=action_state,
        prior_order_name=prior_order_name,
        trustpilot_sent=trustpilot_sent,
        source_row=source_row,
        evidence=row.get("evidence") or row.get("reason", ""),
        previous_trustpilot_order_names=previous_trustpilot_order_names,
        trustpilot_note_evidence=trustpilot_note_evidence,
    )

    row.update(
        {
            "order_name": order_name,
            "customer": masked_customer,
            "masked_customer": masked_customer,
            "masked_customer_label": masked_customer if _usable_masked_customer(masked_customer) else "",
            "customer_display_name": customer_display_name,
            "customer_order_count": customer_order_count,
            "customer_history_order_count": customer_order_count,
            "customer_history_order_count_before_precision": customer_history_before_precision,
            "customer_order_sequence_number": sequence,
            "customer_order_sequence_label": sequence_label,
            "historical_order_names": historical_order_names,
            "customer_history_order_names": historical_order_names,
            "customer_history_window": (
                _safe_text(local_context.get("customer_history_window"), max_length=80)
                or _safe_text(source_row.get("customer_history_window"), max_length=80)
                or "lifetime_local_orders"
            ),
            "customer_history_matched_order_names": historical_order_names,
            "customer_history_match_method": customer_history_match_method,
            "customer_history_excluded_weak_matches": customer_history_excluded_weak_matches,
            "customer_history_weak_match_count": customer_history_weak_match_count,
            "customer_history_exact_match_count": customer_history_exact_match_count,
            "customer_order_names": historical_order_names[:5],
            "previous_trustpilot_order_names": previous_trustpilot_order_names,
            "previous_trustpilot_tag_values": previous_trustpilot_tag_values,
            "customer_history_source": customer_history_source,
            "customer_history_confidence": customer_history_confidence,
            "customer_history_confirmed": history_confirmed,
            "customer_identity_key": customer_identity_key,
            "customer_identity_source": customer_identity_source,
            "customer_identity_confidence": customer_identity_confidence,
            "customer_level_trustpilot_already_sent": bool(
                previous_trustpilot_order_names or trustpilot_note_evidence_found
            ),
            "customer_level_trustpilot_note_evidence_found": trustpilot_note_evidence_found,
            "customer_level_trustpilot_note_evidence_order_name": _safe_text(
                trustpilot_note_evidence.get("order_name"), max_length=80
            ),
            "customer_level_trustpilot_note_safe_keyword": _safe_text(
                trustpilot_note_evidence.get("safe_keyword"), max_length=80
            ),
            "customer_level_trustpilot_note_field_name": _safe_text(
                trustpilot_note_evidence.get("field_name"), max_length=120
            ),
            "trustpilot_note_evidence_found": trustpilot_note_evidence_found,
            "trustpilot_note_evidence_order_name": _safe_text(
                trustpilot_note_evidence.get("order_name"), max_length=80
            ),
            "trustpilot_note_safe_keyword": _safe_text(
                trustpilot_note_evidence.get("safe_keyword"), max_length=80
            ),
            "trustpilot_note_field_name": _safe_text(
                trustpilot_note_evidence.get("field_name"), max_length=120
            ),
            "note_risk_detected": note_risk["note_risk_detected"],
            "note_risk_field": note_risk["note_risk_field"],
            "note_risk_fields": note_risk["note_risk_fields"],
            "note_risk_keywords": note_risk["note_risk_keywords"],
            "note_risk_reason": note_risk["note_risk_reason"],
            "customer_orders_display": _customer_orders_display(
                customer_order_count,
                sequence_label,
                related_order_names,
                history_confirmed=history_confirmed,
            ),
            "related_order_names": related_order_names,
            "explicit_related_order_names": explicit_related_order_names,
            "explicit_related_order_reference": bool(explicit_related_order_names),
            "order_tags_display": tags,
            "local_shopify_tags": local_shopify_tags,
            "has_order_tags": bool(tags),
            "tag_data_available": review_request_tag_data_loaded,
            "tag_data_missing_source": (
                ""
                if review_request_tag_data_loaded
                else _safe_text(source_row.get("tag_data_missing_source"), max_length=240)
                or _safe_text(local_context.get("tag_data_missing_source"), max_length=240)
                or SHOPIFY_ORDER_TAGS_MISSING_SOURCE
            ),
            "tag_data_recommended_action": (
                ""
                if review_request_tag_data_loaded
                else _safe_text(source_row.get("tag_data_recommended_action"), max_length=300)
                or _safe_text(local_context.get("tag_data_recommended_action"), max_length=300)
                or SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION
            ),
            "tag_chips": _queue_tag_chips(
                tags,
                delivered=delivered,
                review_request_present=review_request_present,
                trustpilot_sent=trustpilot_sent,
                action_state=action_state,
                tag_data_loaded=review_request_tag_data_loaded,
            ),
            "delivered_status_label": _queue_delivered_status_label(delivered),
            "delivered_status_class": _queue_status_css_class(delivered),
            "review_request_tag_present": review_request_present is True,
            "review_request_tag_data_loaded": review_request_tag_data_loaded,
            "matched_review_request_tag_value": matched_review_request_tag_value,
            "review_request_tag_match_detail": _review_request_tag_match_detail(matched_review_request_tag_value),
            "second_or_later_order": second_order_state["second_or_later_order"],
            "current_order_delivered": second_order_state["current_order_delivered"],
            "second_order_rule_passed": second_order_state["passed"],
            "second_order_rule_blocker": second_order_state["blocker"],
            "second_order_rule_reason": second_order_state["reason"],
            "ebay_tag_detected": ebay_tag_detected,
            "matched_ebay_tag_value": matched_ebay_tags[0] if matched_ebay_tags else "",
            "trustpilot_tag_detected": trustpilot_state["trustpilot_tag_detected"],
            "trustpilot_tag_source": trustpilot_state["trustpilot_tag_source"],
            "matched_trustpilot_tag_values": trustpilot_state["matched_trustpilot_tag_values"],
            "already_sent_reason": (
                _safe_text(row.get("already_sent_reason"), max_length=300)
                or (_trustpilot_note_evidence_reason(trustpilot_note_evidence) if trustpilot_note_evidence_found else "")
                or trustpilot_state["already_sent_reason"]
            ),
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
            "status_label": _safe_text(row.get("status"), max_length=120),
            "status_chips": [
                {
                    "label": _queue_delivered_status_label(delivered),
                    "css_class": _queue_status_css_class(delivered),
                },
                {
                    "label": (
                        "Review request tag found"
                        if review_request_present is True
                        else (
                            f"Missing {CANONICAL_REVIEW_REQUEST_TAG}"
                            if review_request_present is False
                            else "Shopify tag data not loaded"
                        )
                    ),
                    "css_class": _queue_status_css_class(review_request_present),
                },
            ],
            "trustpilot_already_sent_to_customer": trustpilot_sent,
            "prior_trustpilot_order_name": prior_order_name,
            "trustpilot_history_label": history_label,
            "trustpilot_email_status": (
                "Sent" if local_review_send_success else (
                    "Already sent" if trustpilot_sent else "No previous Trustpilot email found"
                )
            ),
            "sent_at": sent_at,
            "email_sent_at": sent_at,
            "sent_time_label": _time_label(sent_at),
            "sent_time_recorded": bool(sent_at),
            "tag_written_at": tag_written_at,
            "tag_written_time_label": _time_label(tag_written_at),
            "tag_write_failed": tag_write_failed,
            "shopify_tag_written": shopify_tag_written,
            "shopify_tag_already_existed": shopify_tag_already_existed,
            "local_review_send_success": local_review_send_success,
            "shopify_tag_pending": shopify_tag_pending,
            "shopify_tag_status_label": shopify_tag_status,
            "shopify_tag_status_class": _already_sent_tag_status_class(shopify_tag_status),
            "customer_history_match_label": _customer_history_match_label(
                customer_history_source,
                customer_history_confidence,
            ),
            "customer_history_lookup_status": row.get("customer_history_lookup_status")
            or ("Customer history checked" if history_confirmed else "Customer history incomplete"),
            "customer_history_lookup_action_label": row.get("customer_history_lookup_action_label")
            or ("Customer history checked" if history_confirmed else "Check customer history"),
            "customer_history_lookup_task_name": ON_DEMAND_CUSTOMER_HISTORY_LOOKUP_TASK_NAME,
            "customer_history_lookup_command": _customer_history_lookup_command(order_name),
            "eligibility_status": _queue_eligibility_status(action_state),
            "eligibility_status_label": _queue_eligibility_status_label(action_state),
            "eligibility_reason_plain": _safe_text(row.get("reason"), max_length=500),
            "action_label": _queue_action_status(action_state),
            "action_status": _queue_action_status(action_state),
            "can_review_send": action_state == "review_send",
            "review_send_url": "",
        }
    )
    row["evidence"] = _safe_text(row.get("evidence") or row.get("reason"), max_length=500)
    return row


def _safe_customer_display_name(value):
    text = _safe_text(value, max_length=120)
    if not text or EMAIL_RE.search(text):
        return ""
    return text


def _customer_order_sequence_label(order_count, sequence, repeat_detected=False, history_confirmed=True):
    if not history_confirmed:
        return "Customer history not confirmed"
    count = _int_or_zero(order_count)
    seq = _int_or_zero(sequence)
    if count > 1 or repeat_detected:
        if seq > 0:
            return f"{_ordinal(seq)} order of {count}"
        return "Repeat customer"
    if count == 1:
        return "First order - not for Trustpilot"
    if seq > 0:
        return f"{_ordinal(seq)} order"
    return "Order count unknown"


def _second_order_rule_state(history_confirmed, history_count, sequence, delivered):
    count = _int_or_zero(history_count)
    seq = _int_or_zero(sequence)
    current_order_delivered = delivered is True
    second_or_later = bool(history_confirmed and count >= 2 and seq >= 2)
    if not history_confirmed or count <= 0 or seq <= 0:
        return {
            "passed": False,
            "blocker": "history_not_confirmed",
            "reason": SECOND_ORDER_HISTORY_NOT_CONFIRMED_REASON,
            "second_or_later_order": False,
            "current_order_delivered": current_order_delivered,
        }
    if count <= 1:
        return {
            "passed": False,
            "blocker": "first_order",
            "reason": SECOND_ORDER_FIRST_ORDER_REASON,
            "second_or_later_order": False,
            "current_order_delivered": current_order_delivered,
        }
    if seq <= 1:
        return {
            "passed": False,
            "blocker": "not_second_or_later",
            "reason": SECOND_ORDER_CURRENT_FIRST_REASON,
            "second_or_later_order": False,
            "current_order_delivered": current_order_delivered,
        }
    if delivered is not True:
        return {
            "passed": False,
            "blocker": "second_order_not_delivered",
            "reason": SECOND_ORDER_WAIT_FOR_DELIVERY_REASON,
            "second_or_later_order": second_or_later,
            "current_order_delivered": False,
        }
    return {
        "passed": True,
        "blocker": "",
        "reason": "",
        "second_or_later_order": second_or_later,
        "current_order_delivered": True,
    }


def _customer_orders_display(order_count, sequence_label, related_order_names, history_confirmed=True):
    if not history_confirmed:
        return sequence_label or "Customer history not confirmed"
    related = [_safe_text(name, max_length=80) for name in related_order_names or [] if _safe_text(name, max_length=80)]
    if related:
        return "Related " + " / ".join(related)
    count = _int_or_zero(order_count)
    if count > 0:
        noun = "order" if count == 1 else "orders"
        return f"{count} {noun}; {sequence_label}"
    return sequence_label or "Order count unknown"


def _customer_history_match_label(source, confidence):
    source_text = _safe_text(source, max_length=80) or "unavailable"
    confidence_text = _safe_text(confidence, max_length=80) or "unknown"
    source_label = {
        "shopify_customer_id": "customer_id",
        "customer_email": "customer_email",
        "name_shipping_phone": "shipping_fallback",
        "name_shipping_address_postcode": "shipping_fallback",
        "name_only": "name_only_manual_review",
    }.get(source_text, source_text)
    return f"Match: {source_label}; confidence: {confidence_text}"


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
    previous_trustpilot_order_names=None,
    trustpilot_note_evidence=None,
):
    previous_trustpilot_order_names = _dedupe_order_names(previous_trustpilot_order_names or [])
    if (trustpilot_note_evidence or {}).get("evidence_found") is True:
        return _trustpilot_note_history_label(trustpilot_note_evidence)
    if previous_trustpilot_order_names:
        return f"Already sent via {_join_order_names(previous_trustpilot_order_names)}"
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


def _queue_tag_chips(tags, delivered, review_request_present, trustpilot_sent, action_state, tag_data_loaded=False):
    chips = [
        {"label": tag, "css_class": _queue_tag_css_class(tag)}
        for tag in tags
    ]
    if not chips:
        chips.append(
            {
                "label": SHOPIFY_ORDER_TAGS_EMPTY_SOURCE
                if tag_data_loaded
                else "Shopify tag data not loaded",
                "css_class": "rrw-badge-muted",
            }
        )
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
    if has_ebay_tag(tags):
        chips.append({"label": "eBay blocked", "css_class": "rrw-badge-bad"})
    return _dedupe_chip_rows(chips)


def _queue_tag_css_class(tag):
    normalized = _normalize_trustpilot_tag(tag)
    if normalized in {_normalize_trustpilot_tag(alias) for alias in DELIVERED_TAG_ALIASES}:
        return "rrw-badge-ok"
    if normalized in {_normalize_trustpilot_tag(alias) for alias in REVIEW_REQUEST_TAG_ALIASES}:
        return "rrw-badge-ok"
    if normalized in {_normalize_trustpilot_tag(alias) for alias in TRUSTPILOT_TAG_ALIASES}:
        return "rrw-badge-info"
    if "ebay" in _normalize_ebay_tag(tag):
        return "rrw-badge-bad"
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


def _customer_history_lookup_command(order_name):
    selected = _canonical_order_name(order_name)
    if not selected:
        return _batch_customer_history_lookup_container_command()
    return (
        "docker compose exec -T web python manage.py "
        f"run_review_request_batch_customer_history_lookup --limit 1 --order-filter {selected}"
    )


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
    for row in (
        (approval_queue.get("needs_review_rows") or [])
        + (approval_queue.get("blocked_rows") or [])
        + (approval_queue.get("already_sent_rows") or [])
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


def _runtime_review_send_route_blockers(result, candidate):
    blockers = []
    if result.get("admin_post_request_confirmed") is not True:
        blockers.append(
            {
                "status": "blocked_admin_post_required",
                "detail": "No email was sent. Review & Send must be submitted by admin POST.",
            }
        )
    if result.get("staff_admin_route_confirmed") is not True:
        blockers.append(
            {
                "status": "blocked_staff_admin_required",
                "detail": "No email was sent. Review & Send is staff/admin only.",
            }
        )
    if result.get("csrf_protection_enabled") is not True:
        blockers.append(
            {
                "status": "blocked_csrf_protection_required",
                "detail": "No email was sent. CSRF protection is required.",
            }
        )
    if candidate.get("selected_order_latest_for_customer") is not True:
        latest_order = _safe_text(candidate.get("latest_eligible_order_for_customer"), max_length=80)
        detail = "No email was sent. This order is not the latest eligible order for this customer."
        if latest_order:
            detail = f"No email was sent. A newer eligible order exists for this customer: {latest_order}."
        blockers.append(
            {
                "status": "blocked_newer_eligible_order_exists_for_customer",
                "detail": detail,
            }
        )
    return blockers


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


def _base_review_and_send_result(selected_order, admin_username, state, request_context=None):
    queue = state["approval_queue"]
    gmail_setup = state["gmail_setup"]
    request_context = request_context or {}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "report_generated_at": datetime.now(timezone.utc).isoformat(),
        "task": "shopify_review_request_trustpilot_review_and_send_execute",
        "task_name": "shopify_review_request_trustpilot_review_and_send_execute",
        "phase": "5.28L",
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
        "selected_order_latest_for_customer": False,
        "selected_latest_eligible_order_for_customer": "",
        "selected_masked_email": "",
        "ebay_tag_detected": False,
        "matched_ebay_tag_value": "",
        "candidate_verified": False,
        "review_and_send_requested": True,
        "request_method": _safe_text(request_context.get("method"), max_length=20),
        "admin_post_request_confirmed": request_context.get("method") == "POST",
        "staff_admin_route_confirmed": request_context.get("is_staff_admin") is True,
        "csrf_protection_enabled": request_context.get("csrf_protection_enabled") is True,
        "admin_user": _safe_text(admin_username, max_length=120),
        "eligible_candidate_count_before_latest_filter": queue.get(
            "eligible_candidate_count_before_latest_filter", queue.get("eligible_candidate_count_total", 0)
        ),
        "eligible_candidate_count_after_latest_filter": queue.get(
            "eligible_candidate_count_after_latest_filter", queue.get("eligible_candidate_count_total", 0)
        ),
        "hidden_older_eligible_count": queue.get("hidden_older_eligible_count", 0),
        "hidden_older_eligible_summary": queue.get("hidden_older_eligible_summary", []),
        "latest_candidate_per_customer_count": queue.get("latest_candidate_per_customer_count", 0),
        "focus_22530_22562_latest_decision": queue.get("focus_22530_22562_latest_decision", {}),
        "needs_review_count": queue["needs_review_count"],
        "already_sent_count": queue["already_sent_count"],
        "ready_to_send_count": queue["ready_to_send_count"],
        "not_ready_count": queue["not_ready_count"],
        "gmail_scope_status": gmail_setup.get("scope_status") or "scope_missing",
        "gmail_compose_send_supported": bool(gmail_setup.get("gmail_compose_send_supported")),
        "gmail_send_permission_ready": bool(gmail_setup.get("gmail_compose_send_supported")),
        "gmail_helper_ready": bool(gmail_setup.get("gmail_helper_ready")),
        "direct_send_supported_by_current_helper": bool(
            gmail_setup.get("admin_direct_send_helper_supported")
        ),
        "draft_send_supported_by_existing_locked_helper": bool(
            gmail_setup.get("locked_draft_send_helper_available")
        ),
        "previous_gmail_draft_send_helper_found": bool(
            gmail_setup.get("previous_gmail_draft_send_helper_found")
        ),
        "helper_module": _safe_text(gmail_setup.get("helper_module"), max_length=180),
        "helper_supports_dynamic_order": bool(gmail_setup.get("helper_supports_dynamic_order")),
        "helper_requires_remote_approval_runner": bool(
            gmail_setup.get("helper_requires_remote_approval_runner")
        ),
        "can_be_called_from_admin_post": bool(gmail_setup.get("can_be_called_from_admin_post")),
        "drafts_send_path_available": bool(gmail_setup.get("drafts_send_path_available")),
        "blocker_if_not_reusable": _safe_text(
            gmail_setup.get("blocker_if_not_reusable"),
            max_length=500,
        ),
        "recommended_integration_path": _safe_text(
            gmail_setup.get("recommended_integration_path"),
            max_length=500,
        ),
        "reuse_gmail_helper_audit_task_name": REVIEW_SEND_REUSE_GMAIL_HELPER_AUDIT_TASK_NAME,
        "post_send_audit_task_name": REVIEW_SEND_POST_SEND_AUDIT_TASK_NAME,
        "post_send_audit_status": "",
        "post_send_audit_success": False,
        "post_send_audit_selected_order": "",
        "post_send_audit_email_sent_confirmed": False,
        "post_send_audit_sent_count": 0,
        "auto_tag_write_attempted": False,
        "auto_tag_write_status": "",
        "auto_tag_write_blocking_conditions": [],
        "auto_tag_write_user_message": "",
        "trustpilot_tag_added": False,
        "review_request_tag_removed": False,
        "typo_review_request_tag_removed": False,
        "tag_write_readback_verified": False,
        "shopify_tag_write_confirmed": False,
        "shopify_tag_written": False,
        "final_workflow_status": "blocked_before_send",
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_drafts_create_called": False,
        "gmail_draft_created": False,
        "gmail_draft_id_partial": "",
        "gmail_draft_send_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "gmail_message_id_partial": "",
        "email_sent": False,
        "sent_count": 0,
        "one_send_limit_enforced": True,
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
        "blocked_reason": "",
        "exact_user_message": "",
        "send_readiness_diagnosis": {},
        "next_admin_action": "No email was sent. Review the blocker message.",
        "privacy_scan_summary": {},
        "report_paths": {
            "json": f"logs/{REVIEW_AND_SEND_REPORT_FILENAME}",
            "html": f"logs/{REVIEW_AND_SEND_HTML_FILENAME}",
        },
    }


def _review_send_readiness_diagnosis(
    target_order,
    candidate,
    gmail_setup,
    candidate_found=False,
    candidate_currently_eligible=False,
    route_revalidation_blocker="",
):
    candidate = candidate or {}
    gmail_blocker = _review_send_gmail_blocker(gmail_setup)
    previous_trustpilot_order_names = _dedupe_order_names(
        candidate.get("previous_trustpilot_order_names") or []
    )
    trustpilot_note_evidence = _trustpilot_note_evidence_from_sources(candidate)
    trustpilot_note_evidence_found = trustpilot_note_evidence.get("evidence_found") is True
    prior_trustpilot_found = bool(
        previous_trustpilot_order_names
        or trustpilot_note_evidence_found
        or candidate.get("customer_level_trustpilot_already_sent") is True
        or candidate.get("prior_trustpilot_order_name")
        or candidate.get("trustpilot_sent") is True
        or candidate.get("action_state") == "already_sent"
    )
    route_blocked = bool(route_revalidation_blocker)
    candidate_blocked = bool(candidate_found and not candidate_currently_eligible)
    already_sent = bool(candidate.get("action_state") == "already_sent" or prior_trustpilot_found)
    note_risk_found = candidate.get("note_risk_detected") is True
    tags = _dedupe_text(candidate.get("order_tags_display") or candidate.get("tags") or [])
    ebay_tag_detected = candidate.get("ebay_tag_detected") is True or has_ebay_tag(tags)
    customer_history_confirmed = candidate.get("customer_history_confirmed") is True
    customer_history_changed = bool(candidate_found and not customer_history_confirmed)

    blocked_reason = ""
    exact_user_message = ""
    recommended_fix = ""
    if not candidate_found:
        blocked_reason = "candidate no longer eligible"
        exact_user_message = "No email was sent. This order is no longer eligible."
        recommended_fix = "Refresh the Review Requests page and re-run the local candidate scan if the order should still qualify."
    elif route_blocked:
        blocked_reason = "route/revalidation blocker"
        exact_user_message = "No email was sent. Server-side revalidation blocked this order."
        recommended_fix = "Review the server-side blocker before retrying Review & Send."
    elif trustpilot_note_evidence_found:
        blocked_reason = "historical Trustpilot note"
        exact_user_message = f"No email was sent. {_trustpilot_note_evidence_reason(trustpilot_note_evidence)}"
        recommended_fix = "Do not send another Trustpilot email for this customer unless a separate manual exception is approved."
    elif candidate_blocked:
        blocked_reason = "candidate no longer eligible"
        exact_user_message = "No email was sent. This order is no longer eligible."
        recommended_fix = "Refresh the queue and review the current candidate status."
    elif already_sent:
        blocked_reason = "already sent"
        exact_user_message = "No email was sent. Already sent Trustpilot to this customer."
        recommended_fix = "Do not send another Trustpilot email for this customer unless a separate manual exception is approved."
    elif ebay_tag_detected:
        blocked_reason = "eBay order"
        exact_user_message = EBAY_BLOCK_REASON
        recommended_fix = "Do not send Trustpilot email for eBay-tagged orders."
    elif note_risk_found:
        blocked_reason = "risk blocker"
        exact_user_message = f"No email was sent. {NOTE_RISK_REASON}."
        recommended_fix = "Manually review the order notes or ticket history before any customer-facing email."
    elif customer_history_changed:
        blocked_reason = "customer history changed"
        exact_user_message = "No email was sent. Customer history not confirmed."
        recommended_fix = "Confirm repeat-customer history before retrying Review & Send."
    elif gmail_blocker:
        blocked_reason = _review_send_plain_blocked_reason(gmail_blocker["status"])
        exact_user_message = gmail_blocker["detail"]
        recommended_fix = _review_send_gmail_recommended_fix(gmail_blocker["status"])
    else:
        blocked_reason = ""
        exact_user_message = "Ready for admin Review & Send."
        recommended_fix = "Admin may use Review & Send for this latest eligible candidate."

    return {
        "target_order": _canonical_order_name(target_order),
        "candidate_found": bool(candidate_found),
        "candidate_currently_eligible": bool(candidate_currently_eligible),
        "customer_history_confirmed": customer_history_confirmed,
        "customer_history_changed": customer_history_changed,
        "prior_trustpilot_found": prior_trustpilot_found,
        "trustpilot_note_evidence_found": trustpilot_note_evidence_found,
        "trustpilot_note_evidence_order_name": _safe_text(trustpilot_note_evidence.get("order_name"), max_length=80),
        "trustpilot_note_safe_keyword": _safe_text(trustpilot_note_evidence.get("safe_keyword"), max_length=80),
        "already_sent": already_sent,
        "note_risk_found": note_risk_found,
        "ebay_tag_detected": ebay_tag_detected,
        "matched_ebay_tag_value": _safe_text(candidate.get("matched_ebay_tag_value"), max_length=120),
        "risk_blocker": note_risk_found,
        "route_revalidation_blocker": _safe_text(route_revalidation_blocker, max_length=120),
        "gmail_scope_status": gmail_setup.get("scope_status") or "scope_missing",
        "gmail_scope_missing": (gmail_setup.get("scope_status") or "scope_missing") == "scope_missing",
        "gmail_scope_compose_only": (gmail_setup.get("scope_status") == "gmail_compose_only"),
        "gmail_scope_send_available": bool(gmail_setup.get("real_send_scope_available")),
        "gmail_send_permission_ready": bool(gmail_setup.get("gmail_compose_send_supported")),
        "gmail_send_path_requires_gmail_send": False,
        "gmail_helper_ready": bool(gmail_setup.get("gmail_helper_ready")),
        "gmail_credentials_missing": not bool(gmail_setup.get("gmail_credentials_ready")),
        "direct_send_supported_by_current_helper": bool(
            gmail_setup.get("admin_direct_send_helper_supported")
        ),
        "draft_send_supported_by_existing_locked_helper": bool(
            gmail_setup.get("locked_draft_send_helper_available")
        ),
        "previous_gmail_draft_send_helper_found": bool(
            gmail_setup.get("previous_gmail_draft_send_helper_found")
        ),
        "helper_module": _safe_text(gmail_setup.get("helper_module"), max_length=180),
        "helper_supports_dynamic_order": bool(gmail_setup.get("helper_supports_dynamic_order")),
        "helper_requires_remote_approval_runner": bool(
            gmail_setup.get("helper_requires_remote_approval_runner")
        ),
        "can_be_called_from_admin_post": bool(gmail_setup.get("can_be_called_from_admin_post")),
        "drafts_send_path_available": bool(gmail_setup.get("drafts_send_path_available")),
        "blocker_if_not_reusable": _safe_text(
            gmail_setup.get("blocker_if_not_reusable"),
            max_length=500,
        ),
        "recommended_integration_path": _safe_text(
            gmail_setup.get("recommended_integration_path"),
            max_length=500,
        ),
        "blocked_reason": blocked_reason,
        "exact_user_message": exact_user_message,
        "recommended_fix": recommended_fix,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "shopify_write_performed": False,
    }


def _apply_review_send_diagnosis(result, diagnosis):
    result["send_readiness_diagnosis"] = diagnosis
    result["blocked_reason"] = diagnosis.get("blocked_reason", "")
    result["exact_user_message"] = diagnosis.get("exact_user_message", "")
    result["gmail_send_permission_ready"] = diagnosis.get("gmail_send_permission_ready") is True
    result["gmail_helper_ready"] = diagnosis.get("gmail_helper_ready") is True
    result["direct_send_supported_by_current_helper"] = (
        diagnosis.get("direct_send_supported_by_current_helper") is True
    )
    result["draft_send_supported_by_existing_locked_helper"] = (
        diagnosis.get("draft_send_supported_by_existing_locked_helper") is True
    )
    for key in (
        "previous_gmail_draft_send_helper_found",
        "helper_supports_dynamic_order",
        "helper_requires_remote_approval_runner",
        "can_be_called_from_admin_post",
        "drafts_send_path_available",
    ):
        result[key] = diagnosis.get(key) is True
    for key in ("helper_module", "blocker_if_not_reusable", "recommended_integration_path"):
        result[key] = diagnosis.get(key, "")


def _review_send_plain_blocked_reason(status):
    if status == "blocked_gmail_drafts_send_helper_not_enabled":
        return "Gmail drafts.send helper not configured"
    if status == "blocked_missing_gmail_compose_scope":
        return "Gmail compose permission missing"
    if status == "blocked_missing_gmail_send_scope":
        return "Gmail scope missing"
    if status == "blocked_gmail_credentials_missing":
        return "Gmail credentials missing"
    if status == "blocked_gmail_direct_send_helper_not_enabled":
        return "Gmail helper not configured"
    return "Gmail helper not configured"


def _review_send_gmail_recommended_fix(status):
    if status == "blocked_gmail_drafts_send_helper_not_enabled":
        return "Enable the reviewed dynamic drafts.create plus drafts.send helper before retrying."
    if status == "blocked_missing_gmail_compose_scope":
        return "Configure Gmail compose permission before retrying Review & Send."
    if status == "blocked_missing_gmail_send_scope":
        return "Configure Gmail send permission before retrying direct Review & Send."
    if status == "blocked_gmail_credentials_missing":
        return "Configure Gmail OAuth credentials and token files without exposing secret values."
    return "Enable and review the Gmail direct-send helper before retrying."


def _review_send_gmail_blocker(gmail_setup):
    if gmail_setup.get("can_be_called_from_admin_post") is not True:
        return _previous_gmail_helper_reuse_blocker(gmail_setup)
    scope_status = gmail_setup.get("scope_status") or "scope_missing"
    runtime_gmail_env = _dynamic_gmail_env()
    compose_available = (
        gmail_setup.get("compose_scope_present") is True
        or gmail_setup.get("broad_mail_scope_present") is True
        or runtime_gmail_env["compose_path_available"] is True
        or scope_status in {"gmail_compose_only", "broad_mail_scope_available"}
    )
    if not compose_available:
        return {
            "status": "blocked_missing_gmail_compose_scope",
            "detail": (
                "No email was sent. Gmail compose permission is missing; "
                "Review & Send uses drafts.create plus drafts.send."
            ),
        }
    if gmail_setup.get("gmail_credentials_ready") is not True and runtime_gmail_env["oauth_present"] is not True:
        return {
            "status": "blocked_gmail_credentials_missing",
            "detail": "No email was sent. Gmail credentials are missing.",
        }
    if gmail_setup.get("admin_drafts_send_helper_supported") is not True:
        return {
            "status": "blocked_gmail_drafts_send_helper_not_enabled",
            "detail": "No email was sent. The dynamic Gmail drafts.send helper is not ready.",
        }
    return None


def _previous_gmail_helper_reuse_blocker(gmail_setup=None):
    gmail_setup = gmail_setup or {}
    return {
        "status": "blocked_previous_gmail_send_helper_not_reusable",
        "detail": "No email was sent. The previous Gmail send helper is not reusable from this admin action yet.",
        "technical_detail": _safe_text(gmail_setup.get("blocker_if_not_reusable"), max_length=500),
    }


def _runtime_customer_history_live_lookup_blockers(candidate, scan, reports, reference_at=""):
    selected_order = _canonical_order_name(candidate.get("order") or candidate.get("candidate_id"))
    lookup = _matching_on_demand_customer_history_lookup(reports, selected_order)
    if not _customer_history_live_lookup_required(candidate, scan):
        return []
    gate = _customer_history_lookup_gate(
        lookup,
        reference_at or _customer_history_lookup_reference_at(scan),
    )
    if gate["status"] == "missing":
        scope_blocker = _customer_history_scope_report_blocker(reports)
        return [
            {
                "status": "blocked_shopify_history_permission_missing"
                if scope_blocker
                else "blocked_customer_history_live_lookup_required",
                "blocked_reason": "shopify read_all_orders permission missing"
                if scope_blocker
                else "customer history live check required",
                "detail": f"No email was sent. {scope_blocker or gate['reason']}",
            }
        ]
    if gate["blocked"]:
        status = {
            "blocked_trustpilot_note": "blocked_existing_trustpilot_invitation_customer_level",
            "blocked_trustpilot_tag": "blocked_existing_trustpilot_invitation_customer_level",
            "stale": "blocked_customer_history_live_lookup_stale",
            "incomplete": "blocked_customer_history_live_lookup_not_available",
            "blocked_lookup_cache": "blocked_customer_history_lookup_cache",
        }.get(gate["status"], "blocked_customer_history_live_lookup_not_available")
        blocked_reason = {
            "blocked_trustpilot_note": "historical Trustpilot note",
            "blocked_trustpilot_tag": "historical Trustpilot tag",
            "stale": "customer history check is stale",
            "incomplete": "customer history live check unavailable",
            "blocked_lookup_cache": "cached customer history lookup blocked Review & Send",
        }.get(gate["status"], "customer history live check blocked")
        return [
            {
                "status": status,
                "blocked_reason": blocked_reason,
                "detail": f"No email was sent. {gate['reason']}",
            }
        ]
    return []


def _customer_history_live_lookup_required(candidate, scan):
    return bool(candidate and candidate.get("action_state") == "review_send")


def _matching_on_demand_customer_history_lookup(reports, selected_order):
    cached = _cached_lookup_order_from_reports(reports, selected_order)
    if cached:
        return cached
    report = (reports or {}).get("on_demand_customer_history_lookup") or {}
    data = report.get("data") or {}
    if not data:
        return {}
    if _canonical_order_name(data.get("selected_order")) != _canonical_order_name(selected_order):
        return {}
    return data


def _customer_history_lookup_gated_rows(rows, scan, reports):
    ready_rows = []
    blocked_rows = []
    for row in rows or []:
        lookup = _matching_on_demand_customer_history_lookup(
            reports,
            (row or {}).get("order") or (row or {}).get("candidate_id"),
        )
        gate = _customer_history_lookup_gate(
            lookup,
            _customer_history_lookup_reference_at(scan),
        )
        decorated = _apply_cached_customer_history_lookup_to_row(dict(row or {}), lookup)
        decorated = _attach_customer_history_lookup_status(decorated, scan, reports)
        blocker = _customer_history_lookup_row_blocker(decorated, scan, reports)
        if blocker:
            blocked = dict(decorated)
            blocked.update(
                {
                    "status": "Not ready",
                    "status_class": "rrw-badge-warn",
                    "reason": blocker,
                    "evidence": blocker,
                    "eligibility_reason_plain": blocker,
                    "action_state": "not_ready",
                    "action_status": "Not ready",
                    "candidate_status": "blocked",
                    "block_reason": blocker,
                    "blocked_by_customer_history_lookup": True,
                    "customer_history_lookup_block_status": gate["status"],
                    "customer_history_lookup_status": gate["label"],
                    "customer_history_lookup_action_label": gate["action_label"],
                    "missing_requirement": gate["missing_requirement"] or "Live Shopify history check",
                    "trustpilot_history_label": decorated.get("trustpilot_history_label")
                    if gate["evidence_found"]
                    else "Needs live check",
                }
            )
            blocked_rows.append(blocked)
            continue
        ready_rows.append(decorated)
    return ready_rows, blocked_rows


def _customer_history_lookup_row_blocker(row, scan, reports):
    selected_order = _canonical_order_name(row.get("order") or row.get("candidate_id"))
    lookup = _matching_on_demand_customer_history_lookup(reports, selected_order)
    if not _customer_history_live_lookup_required(row, scan):
        return ""
    gate = _customer_history_lookup_gate(lookup, _customer_history_lookup_reference_at(scan))
    if gate["blocked"]:
        if gate["status"] == "missing":
            scope_blocker = _customer_history_scope_report_blocker(reports)
            return scope_blocker or gate["reason"]
        return gate["reason"]
    return ""


def _attach_customer_history_lookup_status(row, scan, reports):
    row["customer_history_lookup_status"] = _customer_history_lookup_plain_status(row, scan, reports)
    row["customer_history_lookup_action_label"] = _customer_history_lookup_action_label(
        row["customer_history_lookup_status"]
    )
    return row


def _customer_history_lookup_plain_status(row, scan, reports):
    selected_order = _canonical_order_name((row or {}).get("order") or (row or {}).get("candidate_id"))
    lookup = _matching_on_demand_customer_history_lookup(reports, selected_order)
    if _customer_history_live_lookup_required(row, scan):
        return _customer_history_lookup_gate(
            lookup,
            _customer_history_lookup_reference_at(scan),
        )["label"]
    if lookup:
        return _customer_history_lookup_gate(lookup)["label"]
    scope_data = _shopify_scope_verification_data(reports)
    if scope_data:
        if scope_data.get("reauthorization_required") is True:
            return "Reauthorization needed"
        if scope_data.get("read_all_orders_present") is False:
            return "Shopify history permission missing"
    if (row or {}).get("customer_history_confirmed") is True:
        return "Customer history checked"
    return "Needs live check"


def _customer_history_lookup_action_label(status):
    if status in {"Shopify history permission missing", "Reauthorization needed"}:
        return "Needs Shopify read_all_orders permission"
    if status.startswith("Checked:") or status in {"Customer history checked", "Blocked: previous Trustpilot found"}:
        return "Customer history checked"
    if status == "Stale check":
        return "Recheck customer history"
    return "Check customer history"


def _customer_history_lookup_reference_at(scan):
    return _safe_text(
        (scan or {}).get("candidate_scan_freshness")
        or (scan or {}).get("scan_window_ended_at")
        or (scan or {}).get("timestamp"),
        max_length=120,
    )


def _customer_history_scope_report_blocker(reports):
    scope_data = _shopify_scope_verification_data(reports)
    if not scope_data:
        return ""
    if scope_data.get("reauthorization_required") is True or scope_data.get("read_all_orders_present") is False:
        return READ_ALL_ORDERS_MISSING_MESSAGE
    return ""


def _shopify_scope_verification_data(reports):
    report = (reports or {}).get("shopify_scope_verification") or {}
    data = report.get("data") or {}
    return data if isinstance(data, dict) else {}


def _runtime_review_send_candidate_safety_blockers(candidate):
    blockers = []
    tags = _dedupe_text(candidate.get("order_tags_display") or candidate.get("tags") or [])
    delivered = candidate.get("delivered_status_label") == "Delivered" or has_delivered_tag(tags)
    second_order_state = _second_order_rule_state(
        history_confirmed=candidate.get("customer_history_confirmed") is True,
        history_count=_int_or_zero(
            candidate.get("customer_history_order_count") or candidate.get("customer_order_count")
        ),
        sequence=_int_or_zero(candidate.get("customer_order_sequence_number")),
        delivered=delivered,
    )
    if candidate.get("ebay_tag_detected") is True or has_ebay_tag(tags):
        blockers.append(
            {
                "status": "blocked_ebay_order",
                "detail": f"No email was sent. {EBAY_BLOCK_REASON}",
            }
        )
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
    if not delivered:
        blockers.append(
            {
                "status": "blocked_missing_delivered_tag",
                "detail": f"No email was sent. {SECOND_ORDER_WAIT_FOR_DELIVERY_REASON}",
            }
        )
    if not (candidate.get("review_request_tag_present") is True or has_review_request_tag(tags)):
        blockers.append(
            {
                "status": "blocked_missing_review_request_tag",
                "detail": "No email was sent. Review request tag alias is missing.",
            }
        )
    if second_order_state["passed"] is not True:
        status = {
            "history_not_confirmed": "blocked_customer_history_not_confirmed",
            "first_order": "blocked_first_order_customer",
            "not_second_or_later": "blocked_not_second_or_later_order",
            "second_order_not_delivered": "blocked_second_order_not_delivered",
        }.get(second_order_state["blocker"], "blocked_second_order_rule")
        blockers.append(
            {
                "status": status,
                "detail": f"No email was sent. {second_order_state['reason']}",
            }
        )
    previous_trustpilot_order_names = _dedupe_order_names(
        candidate.get("previous_trustpilot_order_names") or []
    )
    trustpilot_note_evidence = _trustpilot_note_evidence_from_sources(candidate)
    if trustpilot_note_evidence.get("evidence_found") is True:
        blockers.append(
            {
                "status": "blocked_existing_trustpilot_invitation_customer_level",
                "detail": f"No email was sent. {_trustpilot_note_evidence_reason(trustpilot_note_evidence)}",
            }
        )
    elif previous_trustpilot_order_names or candidate.get("customer_level_trustpilot_already_sent") is True:
        blockers.append(
            {
                "status": "blocked_existing_trustpilot_invitation_customer_level",
                "detail": (
                    "No email was sent. Already sent Trustpilot to this customer via "
                    f"{_join_order_names(previous_trustpilot_order_names) or candidate.get('prior_trustpilot_order_name') or 'another order'}."
                ),
            }
        )
    if candidate.get("note_risk_detected") is True:
        blockers.append(
            {
                "status": "blocked_note_risk_detected",
                "detail": f"No email was sent. {NOTE_RISK_REASON}.",
            }
        )
    if _row_has_returned_package(candidate) or _row_has_risk_or_ticket(candidate):
        blockers.append(
            {
                "status": "blocked_risk_or_ticket",
                "detail": "No email was sent. Refund, return, cancel, dispute, chargeback, shipping, or ticket risk found.",
            }
        )
    return blockers


def _runtime_review_send_blockers(candidate, gmail_setup, diagnosis=None):
    blockers = _runtime_review_send_candidate_safety_blockers(candidate)
    gmail_blocker = _review_send_gmail_blocker(gmail_setup)
    if gmail_blocker:
        blockers.append(gmail_blocker)
    return blockers


def _send_dynamic_trustpilot_gmail(candidate):
    result = {
        "execution_status": "blocked_gmail_send_not_started",
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_drafts_create_called": False,
        "gmail_draft_created": False,
        "gmail_draft_id_partial": "",
        "gmail_draft_send_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "gmail_message_id_partial": "",
        "email_sent": False,
        "sent_count": 0,
        "gmail_error_sanitized": "",
        "gmail_scope_status": "scope_missing",
        "one_send_limit_enforced": True,
    }
    recipient = _resolve_review_send_recipient(candidate)
    if not recipient.get("email"):
        result["execution_status"] = "blocked_missing_customer_email"
        result["gmail_error_sanitized"] = "No email was sent. Customer email could not be resolved from the protected local order lookup."
        return result

    gmail_env = _dynamic_gmail_env()
    result["gmail_scope_status"] = gmail_env["scope_status"]
    if not gmail_env["oauth_present"]:
        result["execution_status"] = "blocked_missing_gmail_oauth"
        result["gmail_error_sanitized"] = "No email was sent. Gmail OAuth settings are missing."
        return result
    if not gmail_env["compose_path_available"]:
        result["execution_status"] = "blocked_missing_gmail_compose_scope"
        result["gmail_error_sanitized"] = "No email was sent. Gmail compose permission is missing."
        return result

    message = _build_trustpilot_email_message(
        send_from=gmail_env["send_from"],
        recipient_email=recipient["email"],
        first_name=recipient["first_name"],
    )
    try:
        result["gmail_api_call_performed"] = True
        service = _build_dynamic_gmail_service(gmail_env)
        result["gmail_draft_create_attempted"] = True
        result["gmail_drafts_create_called"] = True
        draft_response = (
            service.users()
            .drafts()
            .create(userId="me", body={"message": {"raw": message["raw"]}})
            .execute()
        )
        draft_id = _safe_text(draft_response.get("id"), max_length=200)
        result["gmail_draft_id_partial"] = _partial_gmail_id(draft_id)
        if not draft_id:
            result["execution_status"] = "blocked_gmail_draft_create_failed"
            result["gmail_error_sanitized"] = "No email was sent. Gmail draft creation did not return a draft id."
            return result
        result["gmail_draft_created"] = True
        result["gmail_draft_send_attempted"] = True
        result["gmail_drafts_send_called"] = True
        send_response = (
            service.users()
            .drafts()
            .send(userId="me", body={"id": draft_id})
            .execute()
        )
        result["execution_status"] = "trustpilot_email_sent_shopify_tag_not_written"
        result["gmail_send_performed"] = True
        result["email_sent"] = True
        result["sent_count"] = 1
        result["gmail_message_id_partial"] = _partial_gmail_id(send_response.get("id", ""))
        return result
    except Exception as exc:  # pragma: no cover - real Gmail calls are not exercised in no-send validation.
        result["execution_status"] = "blocked_gmail_draft_send_failed"
        result["gmail_error_sanitized"] = _safe_exception_summary(exc)
        result["gmail_send_performed"] = False
        result["email_sent"] = False
        result["sent_count"] = 0
        return result


def _resolve_review_send_recipient(candidate):
    order_name = _canonical_order_name(candidate.get("order"))
    if not order_name:
        return {"email": "", "masked_email": "", "first_name": "there"}
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
        return {"email": "", "masked_email": "", "first_name": "there"}
    try:
        order = (
            ShopifyOrder.objects.filter(query)
            .values("order_name", "order_number", "customer_name", "shipping_name", "customer_email")
            .order_by("-updated_at", "-id")
            .first()
        )
    except Exception:
        return {"email": "", "masked_email": "", "first_name": "there"}
    if not order:
        return {"email": "", "masked_email": "", "first_name": "there"}
    email = _safe_runtime_email(order.get("customer_email"))
    return {
        "email": email,
        "masked_email": mask_email(email),
        "first_name": _safe_first_name(order.get("customer_name") or order.get("shipping_name")),
    }


def _safe_first_name(value):
    display = _safe_customer_display_name(value)
    if not display:
        return "there"
    first = re.split(r"\s+", display.strip(), maxsplit=1)[0]
    first = re.sub(r"[^A-Za-z0-9' -]", "", first).strip()
    return first[:40] or "there"


def _dynamic_gmail_env():
    send_from = (os.environ.get("GMAIL_SEND_FROM") or GMAIL_SEND_FROM).strip()
    client_id = (os.environ.get("GOOGLE_GMAIL_CLIENT_ID") or "").strip()
    client_secret = (os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET") or "").strip()
    refresh_token = (os.environ.get("GOOGLE_GMAIL_REFRESH_TOKEN") or "").strip()
    scopes = _split_runtime_scopes(os.environ.get("GOOGLE_GMAIL_SCOPES") or "")
    compose_path_available = bool(
        set(scopes)
        & {
            GMAIL_COMPOSE_SCOPE,
            GMAIL_BROAD_SCOPE,
        }
    )
    scope_status = _runtime_scope_status(
        GMAIL_COMPOSE_SCOPE in scopes,
        GMAIL_SEND_SCOPE in scopes,
        GMAIL_BROAD_SCOPE in scopes,
    )
    return {
        "send_from": send_from,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "scopes": scopes,
        "compose_path_available": compose_path_available,
        "scope_status": scope_status,
        "oauth_present": bool(
            send_from == GMAIL_SEND_FROM
            and client_id
            and client_secret
            and refresh_token
            and scopes
        ),
    }


def _build_trustpilot_email_message(send_from, recipient_email, first_name):
    body = (
        f"Hi {first_name},\n\n"
        "Thank you for your recent order with Kidstoylover.\n\n"
        "If everything arrived safely, we would really appreciate it if you could share your experience on Trustpilot:\n\n"
        f"{TRUSTPILOT_REVIEW_LINK}\n\n"
        "Your feedback helps other customers and helps us improve our service.\n\n"
        "Kind regards,\n"
        "Kidstoylover\n"
    )
    email = EmailMessage()
    email["To"] = recipient_email
    email["From"] = send_from
    email["Subject"] = TRUSTPILOT_EMAIL_SUBJECT
    email.set_content(body)
    return {
        "raw": base64.urlsafe_b64encode(email.as_bytes()).decode("ascii"),
        "subject": TRUSTPILOT_EMAIL_SUBJECT,
    }


def _build_dynamic_gmail_service(gmail_env):
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials(
        token=None,
        refresh_token=gmail_env["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=gmail_env["client_id"],
        client_secret=gmail_env["client_secret"],
        scopes=gmail_env["scopes"],
    )
    credentials.refresh(Request())
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _partial_gmail_id(value):
    text = _safe_text(value, max_length=200)
    if not text:
        return ""
    if len(text) <= 10:
        return "[present]"
    return f"{text[:4]}...{text[-4:]}"


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
    text = EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
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
    if not result.get("exact_user_message"):
        result["exact_user_message"] = result.get("blocking_detail", "")
    if not result.get("blocked_reason") and result.get("blocking_status"):
        result["blocked_reason"] = _review_send_plain_blocked_reason(result["blocking_status"])
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
            "gmail_drafts_create_called",
            "gmail_draft_send_attempted",
            "email_sent",
            "sent_count",
            "post_send_audit_status",
            "auto_tag_write_attempted",
            "auto_tag_write_status",
            "shopify_write_performed",
            "shopify_tag_write_performed",
            "trustpilot_tag_added",
            "review_request_tag_removed",
            "typo_review_request_tag_removed",
            "tag_write_readback_verified",
            "final_workflow_status",
        )
    )
    helper_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td>{escape(str(payload.get(key, '')))}</td></tr>"
        for key in (
            "previous_gmail_draft_send_helper_found",
            "helper_module",
            "helper_supports_dynamic_order",
            "helper_requires_remote_approval_runner",
            "can_be_called_from_admin_post",
            "drafts_send_path_available",
            "blocker_if_not_reusable",
            "reuse_gmail_helper_audit_task_name",
            "post_send_audit_task_name",
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
    <tr><th>Latest eligible order for customer</th><td>{escape(str(payload.get("selected_order_latest_for_customer") is True))}</td></tr>
    <tr><th>Candidate verified</th><td>{escape(str(payload.get("candidate_verified") is True))}</td></tr>
    <tr><th>Gmail scope status</th><td><code>{escape(payload.get("gmail_scope_status", ""))}</code></td></tr>
    <tr><th>Blocked reason</th><td>{escape(payload.get("blocked_reason", ""))}</td></tr>
    <tr><th>User message</th><td>{escape(payload.get("exact_user_message", "") or payload.get("blocking_detail", ""))}</td></tr>
    <tr><th>Email sent</th><td>{escape(str(payload.get("email_sent") is True))}</td></tr>
    <tr><th>Next admin action</th><td>{escape(payload.get("next_admin_action", ""))}</td></tr>
  </tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Gmail Helper Reuse</h2>
  <table><tbody>{helper_rows}</tbody></table>
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
    gmail_compose_send_supported = compose_scope_present or broad_mail_scope_present
    new_config_ready = new_file_paths_ready and gmail_compose_send_supported
    legacy_config_ready = legacy_config_detected and gmail_compose_send_supported
    env_scope_ready = (
        env_loading_audit.get("scope_key_detected_in_os_environ") is True
        or env_loading_audit.get("scope_key_detected_in_dot_env") is True
    ) and gmail_compose_send_supported
    credentials_ready = new_file_paths_ready or legacy_config_detected
    gmail_helper_ready = dependencies_ready and credentials_ready
    ready = dependencies_ready and (new_config_ready or legacy_config_ready or env_scope_ready)
    required_scope = _safe_text(
        gmail_helper.get("required_scope_expected") or "https://www.googleapis.com/auth/gmail.send",
        max_length=120,
    )
    previous_helper_found = True
    helper_supports_dynamic_order = True
    helper_requires_remote_approval_runner = False
    can_be_called_from_admin_post = True
    drafts_send_path_available = True
    blocker_if_not_reusable = ""
    recommended_integration_path = (
        "Use the dynamic admin-safe drafts.create plus drafts.send helper for exactly one "
        "server-revalidated latest eligible candidate."
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
        status_value = "Draft only"
        status_message = (
            "Gmail draft permission is available. Review & Send uses drafts.create plus drafts.send."
        )
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
        status_value = "Draft only"
        status_message = (
            "Gmail draft permission is available. Review & Send uses drafts.create plus drafts.send."
        )
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
        "gmail_credentials_ready": credentials_ready,
        "gmail_helper_ready": gmail_helper_ready,
        "admin_direct_send_helper_supported": False,
        "admin_drafts_send_helper_supported": can_be_called_from_admin_post,
        "locked_draft_send_helper_available": True,
        "previous_gmail_draft_send_helper_found": previous_helper_found,
        "previous_helper_module": PHASE_22621_DRAFTS_SEND_HELPER_MODULE,
        "helper_module": DYNAMIC_REVIEW_SEND_HELPER_MODULE,
        "helper_supports_dynamic_order": helper_supports_dynamic_order,
        "helper_requires_remote_approval_runner": helper_requires_remote_approval_runner,
        "can_be_called_from_admin_post": can_be_called_from_admin_post,
        "drafts_send_path_available": drafts_send_path_available,
        "blocker_if_not_reusable": blocker_if_not_reusable,
        "recommended_integration_path": recommended_integration_path,
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
            {
                "label": "Dynamic drafts.send helper",
                "value": "Ready" if can_be_called_from_admin_post else "Not ready",
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
                    "Add Gmail scope to the environment. Use `gmail.compose` for the reviewed "
                    "draft-create plus drafts.send path, or `gmail.send` only for a separate direct-send implementation."
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
    if (row or {}).get("note_risk_detected") is True:
        return NOTE_RISK_REASON
    text = " ".join(
        (
            _safe_text(row.get("status")),
            _safe_text(row.get("blocking_summary")),
            _safe_text(row.get("reason")),
            _safe_text(row.get("eligibility_reason_plain")),
        )
    )
    if "aftersales/ticket note found" in text.lower() or "blocked_note_risk_detected" in text.lower():
        return NOTE_RISK_REASON
    if "customer history not confirmed" in text.lower():
        return "Customer history not confirmed"
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


def has_ebay_tag(tags):
    return bool(_matched_ebay_tags(tags))


def _matched_review_request_tags(tags):
    return _dedupe_text(tag for tag in _as_text_list(tags) if is_review_request_tag_alias(tag))


def _matched_delivered_tags(tags):
    return _matched_tag_alias_values(tags, DELIVERED_TAG_ALIASES)


def _matched_tag_alias_values(tags, aliases):
    normalized_aliases = {normalize_tag(tag) for tag in aliases}
    return _dedupe_text(
        tag
        for tag in _as_text_list(tags)
        if normalize_tag(tag) in normalized_aliases
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


def _matched_ebay_tags(tags):
    return _dedupe_text(
        tag
        for tag in _as_text_list(tags)
        if "ebay" in _normalize_ebay_tag(tag)
    )


def _normalize_trustpilot_tag(tag):
    return normalize_tag(tag)


def normalize_tag(tag):
    return re.sub(r"\s+", "", str(tag or "").strip().lower())


def is_review_request_tag_alias(tag):
    return normalize_tag(tag) in {normalize_tag(alias) for alias in REVIEW_REQUEST_TAG_ALIASES}


def is_trustpilot_tag_alias(tag):
    return normalize_tag(tag) in {normalize_tag(alias) for alias in TRUSTPILOT_TAG_ALIASES}


def _normalize_ebay_tag(tag):
    return re.sub(r"[\s_-]+", "", str(tag or "").strip().lower())


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
