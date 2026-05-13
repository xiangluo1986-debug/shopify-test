import json
import re
import subprocess
import time
from collections import Counter
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_candidate_scan"
COMMAND_LABEL = "shopify_review_request_candidate_scan_read_only"
JSON_PATH = LOG_DIR / "shopify_review_request_candidate_scan.json"
HTML_PATH = LOG_DIR / "shopify_review_request_candidate_scan.html"

SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
ORDER_LIMIT = 100
DOCKER_TIMEOUT_SECONDS = 180

EXACT_REVIEW_REQUEST_TAG = "1: reveiw request"
EXACT_DELIVERED_TAG = "Delivered"
EMAIL_SOURCES = ["email", "customer.email", "customer.defaultEmailAddress.emailAddress", "contactEmail"]
TICKET_BLOCKING_STATUSES = [
    "new",
    "in_progress",
    "reopened",
    "open",
    "pending",
    "waiting_customer",
    "unresolved",
    "complaint",
    "refund_request",
    "return_request",
    "shipping_issue",
    "dispute",
    "chargeback",
]
TICKET_WARNING_STATUSES = ["resolved", "closed", "done", "finished"]
BUCKETS = [
    "ready_for_manual_ali_reviews_check",
    "existing_manual_review_request_tag_present",
    "delivered_but_ali_status_unknown",
    "repeat_customer_trustpilot_candidate",
    "blocked_cancelled",
    "blocked_refunded_or_partially_refunded",
    "blocked_no_email",
    "blocked_shipping_or_delivery_issue",
    "blocked_has_open_ticket",
    "blocked_has_refund_ticket",
    "blocked_has_shipping_issue_ticket",
    "blocked_has_complaint_ticket",
    "ticket_status_unknown_needs_manual_review",
    "needs_manual_review",
]
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\s-]?token|api[_\s-]?key|password|secret)"
)
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")


def run_shopify_review_request_candidate_scan_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    query_result = _query_recent_orders()
    classified_orders = _classify_orders(query_result.get("orders", []))
    grouped = _group_orders(classified_orders)
    counts = {bucket: len(grouped[bucket]) for bucket in BUCKETS}
    blocked_orders = [
        _compact_order(order)
        for order in classified_orders
        if any(bucket.startswith("blocked_") for bucket in order["classification_buckets"])
    ]
    repeat_candidates = [
        _compact_order(order)
        for order in classified_orders
        if "repeat_customer_trustpilot_candidate" in order["classification_buckets"]
    ]
    needs_manual_review = [
        _compact_order(order)
        for order in classified_orders
        if "needs_manual_review" in order["classification_buckets"]
    ]
    success = bool(query_result.get("success"))
    report_status = "completed_read_only_candidate_scan" if success else "blocked_read_only_shopify_query_failed"

    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "1.1",
        "scanner_version": "phase_1_1_ticket_filter",
        "mode": "dry-run-read-only-candidate-scan",
        "command_label": COMMAND_LABEL,
        "shop_domain": SHOP_DOMAIN,
        "shopify_api_version": SHOPIFY_API_VERSION,
        "order_query_limit": ORDER_LIMIT,
        "orders_queried": int(query_result.get("orders_queried") or 0),
        "exact_existing_review_request_tag": EXACT_REVIEW_REQUEST_TAG,
        "exact_existing_delivered_tag": EXACT_DELIVERED_TAG,
        "ticket_status_check": query_result.get("ticket_status_check", "blocked_ticket_filter_error"),
        "ticket_model_detected": bool(query_result.get("ticket_model_detected")),
        "ticket_query_performed": bool(query_result.get("ticket_query_performed")),
        "ticket_matches_found_count": int(query_result.get("ticket_matches_found_count") or 0),
        "orders_with_ticket_match_count": int(query_result.get("orders_with_ticket_match_count") or 0),
        "orders_blocked_by_ticket_count": int(query_result.get("orders_blocked_by_ticket_count") or 0),
        "ticket_blocking_statuses": query_result.get("ticket_blocking_statuses", TICKET_BLOCKING_STATUSES),
        "ticket_warning_statuses": query_result.get("ticket_warning_statuses", TICKET_WARNING_STATUSES),
        "ticket_filter_error_sanitized": _sanitize_text(query_result.get("ticket_filter_error_sanitized", "")),
        "ticket_filter_summary": query_result.get("ticket_filter_summary", {}),
        "ali_reviews_sent_status_check": "not_implemented_in_phase_1",
        "report_status": report_status,
        "success": success,
        "classification_counts": counts,
        "classification_buckets": {
            bucket: [_compact_order(order) for order in bucket_orders]
            for bucket, bucket_orders in grouped.items()
        },
        "repeat_customer_candidates": repeat_candidates,
        "blocked_orders": blocked_orders,
        "needs_manual_review": needs_manual_review,
        "orders": [_compact_order(order) for order in classified_orders],
        "email_field_sources_attempted": query_result.get("email_field_sources_attempted", EMAIL_SOURCES),
        "email_parse_source_counts": _email_parse_source_counts(classified_orders),
        "orders_with_email_count": sum(1 for order in classified_orders if order.get("email_present")),
        "orders_without_email_count": sum(1 for order in classified_orders if not order.get("email_present")),
        "email_masking_applied": True,
        "query_failure_type": query_result.get("failure_type", ""),
        "query_failure_message_sanitized": _sanitize_text(
            query_result.get("query_failure_message_sanitized") or query_result.get("error", "")
        ),
        "command_attempted_sanitized": _safe_command_attempt(),
        "docker_command_reached": bool(query_result.get("docker_command_reached")),
        "django_shell_reached": bool(query_result.get("django_shell_reached")),
        "shopify_installation_found": bool(query_result.get("shopify_installation_found")),
        "shopify_credentials_found": bool(query_result.get("shopify_credentials_found")),
        "shopify_api_response_error_count": int(query_result.get("shopify_api_response_error_count") or 0),
        "shopify_api_response_errors_sanitized": query_result.get("shopify_api_response_errors_sanitized", []),
        "query_attempts": query_result.get("query_attempts", []),
        "successful_query_label": query_result.get("successful_query_label", ""),
        "successful_fallback_query_label": query_result.get("successful_query_label", ""),
        "query_warning_summary": query_result.get("query_warning_summary", ""),
        "shopify_api_call_performed": bool(query_result.get("shopify_api_call_performed")),
        "read_only_shopify_query_performed": bool(query_result.get("read_only_shopify_query_performed")),
        "shopify_query_type": query_result.get("shopify_query_type", ""),
        "shopify_http_status": query_result.get("http_status"),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "logs_committed": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "stdout_tail": _sanitize_text(query_result.get("stdout_tail", "")),
        "stderr_tail": _sanitize_text(query_result.get("stderr_tail", "")),
        "detected_issue_summary": _issue_summary(success, query_result, classified_orders),
        "duration_seconds": round(time.time() - started, 3),
    }
    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    counts = payload["classification_counts"]
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_candidate_scan_path": str(json_path),
        "html_candidate_scan_path": str(html_path),
        "scanner_version": payload["scanner_version"],
        "report_status": payload["report_status"],
        "orders_queried": payload["orders_queried"],
        "classification_counts": counts,
        "ready_for_manual_ali_reviews_check_count": counts["ready_for_manual_ali_reviews_check"],
        "existing_manual_review_request_tag_present_count": counts["existing_manual_review_request_tag_present"],
        "delivered_but_ali_status_unknown_count": counts["delivered_but_ali_status_unknown"],
        "repeat_customer_candidate_count": len(payload["repeat_customer_candidates"]),
        "blocked_order_count": len(payload["blocked_orders"]),
        "needs_manual_review_count": len(payload["needs_manual_review"]),
        "email_field_sources_attempted": payload["email_field_sources_attempted"],
        "email_parse_source_counts": payload["email_parse_source_counts"],
        "orders_with_email_count": payload["orders_with_email_count"],
        "orders_without_email_count": payload["orders_without_email_count"],
        "email_masking_applied": True,
        "query_failure_type": payload["query_failure_type"],
        "query_failure_message_sanitized": payload["query_failure_message_sanitized"],
        "command_attempted_sanitized": payload["command_attempted_sanitized"],
        "docker_command_reached": payload["docker_command_reached"],
        "django_shell_reached": payload["django_shell_reached"],
        "shopify_installation_found": payload["shopify_installation_found"],
        "shopify_credentials_found": payload["shopify_credentials_found"],
        "shopify_api_response_error_count": payload["shopify_api_response_error_count"],
        "successful_query_label": payload["successful_query_label"],
        "successful_fallback_query_label": payload["successful_fallback_query_label"],
        "query_warning_summary": payload["query_warning_summary"],
        "exact_existing_review_request_tag": EXACT_REVIEW_REQUEST_TAG,
        "exact_existing_delivered_tag": EXACT_DELIVERED_TAG,
        "ticket_status_check": payload["ticket_status_check"],
        "ticket_model_detected": payload["ticket_model_detected"],
        "ticket_query_performed": payload["ticket_query_performed"],
        "ticket_matches_found_count": payload["ticket_matches_found_count"],
        "orders_with_ticket_match_count": payload["orders_with_ticket_match_count"],
        "orders_blocked_by_ticket_count": payload["orders_blocked_by_ticket_count"],
        "ticket_blocking_statuses": payload["ticket_blocking_statuses"],
        "ticket_warning_statuses": payload["ticket_warning_statuses"],
        "ticket_filter_error_sanitized": payload["ticket_filter_error_sanitized"],
        "shopify_api_call_performed": payload["shopify_api_call_performed"],
        "read_only_shopify_query_performed": payload["read_only_shopify_query_performed"],
        "shopify_query_type": payload["shopify_query_type"],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _query_recent_orders() -> dict:
    command = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", _django_shell_script()]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=False,
            timeout=DOCKER_TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            **_empty_query_result(),
            "failure_type": "timeout",
            "docker_command_reached": True,
            "query_failure_message_sanitized": f"Timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
        }
    except FileNotFoundError as exc:
        return {
            **_empty_query_result(),
            "failure_type": "missing_env",
            "query_failure_message_sanitized": _sanitize_text(str(exc)),
            "error": str(exc),
        }
    except PermissionError as exc:
        return {
            **_empty_query_result(),
            "failure_type": "docker_permission_denied",
            "query_failure_message_sanitized": _sanitize_text(str(exc)),
            "error": str(exc),
        }

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        failure_type = parsed.get("failure_type") if parsed else _classify_command_failure(stdout, stderr)
        return {
            **_empty_query_result(),
            **parsed,
            "success": False,
            "exit_code": completed.returncode,
            "failure_type": failure_type,
            "docker_command_reached": True,
            "django_shell_reached": bool(parsed.get("django_shell_reached") or parsed),
            "query_failure_message_sanitized": _sanitize_text(
                parsed.get("query_failure_message_sanitized")
                or parsed.get("error")
                or "Read-only Shopify candidate scan command failed."
            ),
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": parsed.get("error") or "Read-only Shopify candidate scan command failed.",
        }
    if not parsed:
        return {
            **_empty_query_result(),
            "success": False,
            "exit_code": completed.returncode,
            "failure_type": "command_error",
            "docker_command_reached": True,
            "django_shell_reached": "objects imported automatically" in stdout,
            "query_failure_message_sanitized": "Read-only Shopify candidate scan did not return parseable JSON.",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": "Read-only Shopify candidate scan did not return parseable JSON.",
        }
    return {
        **_empty_query_result(),
        **parsed,
        "success": bool(parsed.get("success")),
        "exit_code": completed.returncode,
        "docker_command_reached": True,
        "django_shell_reached": bool(parsed.get("django_shell_reached") or parsed),
        "stdout_tail": "" if parsed.get("success") else _tail(stdout),
        "stderr_tail": "" if parsed.get("success") else _tail(stderr),
    }


def _django_shell_script() -> str:
    template = r'''
import json
import requests
from django.apps import apps
from shopify_sync.models import ShopifyInstallation

shop = __SHOP_LITERAL__
api_version = __API_VERSION_LITERAL__
order_limit = __ORDER_LIMIT_LITERAL__
email_sources = __EMAIL_SOURCES_LITERAL__
ticket_blocking_statuses = __TICKET_BLOCKING_STATUSES_LITERAL__
ticket_warning_statuses = __TICKET_WARNING_STATUSES_LITERAL__
queries = [
    ("email", """
query CandidateScanOrderEmail($first: Int!) {
  orders(first: $first, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges { node { id name email createdAt updatedAt cancelledAt displayFulfillmentStatus displayFinancialStatus tags } }
  }
}
""", ["id", "name", "email", "createdAt", "updatedAt", "cancelledAt", "displayFulfillmentStatus", "displayFinancialStatus", "tags"], ["email"]),
    ("customer_email", """
query CandidateScanCustomerEmail($first: Int!) {
  orders(first: $first, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id name createdAt updatedAt cancelledAt displayFulfillmentStatus displayFinancialStatus tags
      customer { id email firstName lastName }
    } }
  }
}
""", ["id", "name", "createdAt", "updatedAt", "cancelledAt", "displayFulfillmentStatus", "displayFinancialStatus", "tags", "customer.id", "customer.email", "customer.firstName", "customer.lastName"], ["customer.email"]),
    ("customer_default_email_address", """
query CandidateScanCustomerDefaultEmail($first: Int!) {
  orders(first: $first, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id name createdAt updatedAt cancelledAt displayFulfillmentStatus displayFinancialStatus tags
      customer { id firstName lastName defaultEmailAddress { emailAddress } }
    } }
  }
}
""", ["id", "name", "createdAt", "updatedAt", "cancelledAt", "displayFulfillmentStatus", "displayFinancialStatus", "tags", "customer.id", "customer.firstName", "customer.lastName", "customer.defaultEmailAddress.emailAddress"], ["customer.defaultEmailAddress.emailAddress"]),
    ("contact_email", """
query CandidateScanContactEmail($first: Int!) {
  orders(first: $first, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges { node { id name contactEmail createdAt updatedAt cancelledAt displayFulfillmentStatus displayFinancialStatus tags } }
  }
}
""", ["id", "name", "contactEmail", "createdAt", "updatedAt", "cancelledAt", "displayFulfillmentStatus", "displayFinancialStatus", "tags"], ["contactEmail"]),
    ("with_customer_id", """
query CandidateScanWithCustomerId($first: Int!) {
  orders(first: $first, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      id name createdAt updatedAt cancelledAt displayFulfillmentStatus displayFinancialStatus tags
      customer { id }
    } }
  }
}
""", ["id", "name", "createdAt", "updatedAt", "cancelledAt", "displayFulfillmentStatus", "displayFinancialStatus", "tags", "customer.id"], []),
    ("tag_discovery_fields", """
query CandidateScanTagsOnly($first: Int!) {
  orders(first: $first, sortKey: CREATED_AT, reverse: true) {
    pageInfo { hasNextPage endCursor }
    edges { node { id name tags createdAt updatedAt } }
  }
}
""", ["id", "name", "tags", "createdAt", "updatedAt"], []),
]

result = {
    "success": False,
    "django_shell_reached": True,
    "command_attempted_sanitized": "docker compose exec -T web python manage.py shell -c <phase1 read-only script>",
    "docker_command_reached": True,
    "shopify_installation_found": False,
    "shopify_credentials_found": False,
    "shopify_api_call_performed": False,
    "read_only_shopify_query_performed": False,
    "shopify_query_type": "GraphQL orders candidate scan read-only query with email-source fallback attempts",
    "http_status": None,
    "orders_queried": 0,
    "orders": [],
    "has_next_page": False,
    "end_cursor_present": False,
    "successful_query_label": "",
    "queried_fields": [],
    "shopify_api_response_error_count": 0,
    "shopify_api_response_errors_sanitized": [],
    "query_attempts": [],
    "query_warning_summary": "",
    "email_field_sources_attempted": email_sources,
    "ticket_status_check": "model_not_found",
    "ticket_model_detected": False,
    "ticket_query_performed": False,
    "ticket_matches_found_count": 0,
    "orders_with_ticket_match_count": 0,
    "orders_blocked_by_ticket_count": 0,
    "ticket_blocking_statuses": ticket_blocking_statuses,
    "ticket_warning_statuses": ticket_warning_statuses,
    "ticket_filter_error_sanitized": "",
    "ticket_filter_summary": {},
    "failure_type": "",
    "error": "",
    "query_failure_message_sanitized": "",
}

def sanitize_errors(errors):
    sanitized = []
    for error in (errors or [])[:10]:
        if not isinstance(error, dict):
            sanitized.append({"message": str(error)[:400], "path": [], "code": ""})
            continue
        extensions = error.get("extensions") or {}
        sanitized.append({
            "message": str(error.get("message") or "GraphQL error")[:400],
            "path": [str(part) for part in (error.get("path") or [])],
            "code": str(extensions.get("code") or ""),
        })
    return sanitized

def selected_email(node, customer):
    default_email_address = customer.get("defaultEmailAddress") or {}
    candidates = [
        ("email", node.get("email")),
        ("customer.email", customer.get("email")),
        ("customer.defaultEmailAddress.emailAddress", default_email_address.get("emailAddress")),
        ("contactEmail", node.get("contactEmail")),
    ]
    for source, value in candidates:
        value = str(value or "").strip()
        if value:
            return value, source
    return "", "none"

def build_orders(connection):
    orders = []
    for edge in connection.get("edges") or []:
        node = (edge or {}).get("node") or {}
        customer = node.get("customer") or {}
        email, source = selected_email(node, customer)
        orders.append({
            "id": str(node.get("id") or ""),
            "name": str(node.get("name") or ""),
            "created_at": str(node.get("createdAt") or ""),
            "updated_at": str(node.get("updatedAt") or ""),
            "cancelled_at": str(node.get("cancelledAt") or ""),
            "display_fulfillment_status": str(node.get("displayFulfillmentStatus") or ""),
            "display_financial_status": str(node.get("displayFinancialStatus") or ""),
            "tags": [str(tag) for tag in (node.get("tags") or [])],
            "customer": {"id": str(customer.get("id") or ""), "email": email, "email_source": source},
        })
    return orders

def normalize_email(value):
    return str(value or "").strip().lower()

def find_ticket_model():
    try:
        return apps.get_model("tickets", "Ticket")
    except LookupError:
        pass
    for model in apps.get_models():
        label = str(model._meta.label_lower)
        model_name = str(model.__name__).lower()
        field_names = {field.name for field in model._meta.fields}
        has_ticket_name = model_name == "ticket" or "ticket" in label
        has_status = "status" in field_names
        has_match_field = bool({"order_no", "order_number", "order_name", "customer_email", "email"} & field_names)
        if has_ticket_name and has_status and has_match_field:
            return model
    return None

def first_field(field_names, candidates):
    for candidate in candidates:
        if candidate in field_names:
            return candidate
    return ""

def order_match_tokens(order):
    tokens = set()
    name = str(order.get("name") or "").strip()
    if name:
        tokens.add(name)
        tokens.add(name.lstrip("#"))
    oid = str(order.get("id") or "").strip()
    if oid:
        tokens.add(oid)
        tokens.add(oid.rsplit("/", 1)[-1])
    return {token for token in tokens if token}

def ticket_status_category(status):
    value = str(status or "").strip().lower()
    if value in ticket_blocking_statuses:
        return "blocking"
    if value in ticket_warning_statuses:
        return "warning"
    if value:
        return "unknown"
    return "unknown"

def risk_categories_for_ticket(ticket, field_roles):
    text = " ".join([
        str(ticket.get(field_roles.get("status", "")) or ""),
        str(ticket.get(field_roles.get("order_no", "")) or ""),
        str(ticket.get(field_roles.get("title", "")) or ""),
    ]).lower()
    categories = []
    if any(word in text for word in ["refund", "return", "rma", "chargeback"]):
        categories.append("refund")
    if any(word in text for word in ["shipping", "delivery", "delivered", "lost", "damaged", "undeliverable"]):
        categories.append("shipping_issue")
    if any(word in text for word in ["complaint", "dispute", "claim", "bad review", "negative"]):
        categories.append("complaint")
    return categories

def safe_ticket_summary(ticket, field_roles, match_fields, risk_categories, status_category):
    return {
        "ticket_id": str(ticket.get(field_roles.get("id", "")) or ""),
        "status": str(ticket.get(field_roles.get("status", "")) or ""),
        "status_category": status_category,
        "priority": str(ticket.get(field_roles.get("priority", "")) or ""),
        "is_pinned": bool(ticket.get(field_roles.get("is_pinned", ""))),
        "match_fields": sorted(match_fields),
        "risk_categories": risk_categories,
        "created_at": str(ticket.get(field_roles.get("created_at", "")) or ""),
        "updated_at": str(ticket.get(field_roles.get("updated_at", "")) or ""),
    }

def apply_ticket_filter(orders):
    TicketModel = find_ticket_model()
    if TicketModel is None:
        result["ticket_status_check"] = "model_not_found"
        result["ticket_model_detected"] = False
        return orders

    result["ticket_model_detected"] = True
    field_names = {field.name for field in TicketModel._meta.fields}
    field_roles = {
        "id": first_field(field_names, ["id", TicketModel._meta.pk.name]),
        "status": first_field(field_names, ["status"]),
        "priority": first_field(field_names, ["priority"]),
        "order_no": first_field(field_names, ["order_no", "order_number", "order_name"]),
        "customer_email": first_field(field_names, ["customer_email", "email"]),
        "title": first_field(field_names, ["title", "subject"]),
        "is_pinned": first_field(field_names, ["is_pinned", "pinned"]),
        "created_at": first_field(field_names, ["created_at", "created", "created_on"]),
        "updated_at": first_field(field_names, ["updated_at", "updated", "modified_at"]),
    }
    safe_fields = sorted({name for name in field_roles.values() if name})
    if not field_roles["status"] or not safe_fields:
        result["ticket_status_check"] = "blocked_ticket_filter_error"
        result["ticket_filter_error_sanitized"] = "Ticket model found but safe status fields could not be inspected."
        return orders

    order_by = "-" + field_roles["updated_at"] if field_roles["updated_at"] else "-" + field_roles["id"]
    try:
        tickets = list(TicketModel.objects.all().order_by(order_by).values(*safe_fields)[:2000])
        result["ticket_query_performed"] = True
        result["ticket_status_check"] = "implemented_read_only"
    except Exception as exc:
        result["ticket_status_check"] = "blocked_ticket_filter_error"
        result["ticket_filter_error_sanitized"] = type(exc).__name__ + ": " + str(exc)
        return orders

    unique_ticket_ids = set()
    orders_with_match = 0
    orders_blocked = 0
    total_match_count = 0

    for order in orders:
        tokens = order_match_tokens(order)
        email = normalize_email((order.get("customer") or {}).get("email"))
        matches = []
        order_blocked = False
        for ticket in tickets:
            match_fields = set()
            ticket_order_no = str(ticket.get(field_roles.get("order_no", "")) or "").strip()
            ticket_email = normalize_email(ticket.get(field_roles.get("customer_email", "")))
            title = str(ticket.get(field_roles.get("title", "")) or "")
            if ticket_order_no and (ticket_order_no in tokens or ticket_order_no.lstrip("#") in tokens):
                match_fields.add("order_no")
            if email and ticket_email and email == ticket_email:
                match_fields.add("customer_email")
            if title and any(token and token in title for token in tokens):
                match_fields.add("title_order_reference")
            if not match_fields:
                continue

            status_category = ticket_status_category(ticket.get(field_roles.get("status", "")))
            risk_categories = risk_categories_for_ticket(ticket, field_roles)
            is_blocking = status_category == "blocking"
            if risk_categories and status_category != "warning":
                is_blocking = True

            summary = safe_ticket_summary(ticket, field_roles, match_fields, risk_categories, status_category)
            summary["is_blocking"] = bool(is_blocking)
            summary["is_warning"] = bool(status_category in {"warning", "unknown"} and not is_blocking)
            matches.append(summary)
            unique_ticket_ids.add(str(ticket.get(field_roles.get("id", "")) or ""))
            total_match_count += 1
            order_blocked = order_blocked or is_blocking

        order["ticket"] = {
            "ticket_match_detected": bool(matches),
            "ticket_match_count": len(matches),
            "ticket_blocked": bool(order_blocked),
            "ticket_status_summary": matches,
            "ticket_blocking_reason": "",
            "ticket_risk_categories": sorted({cat for match in matches for cat in match.get("risk_categories", [])}),
        }
        if matches:
            orders_with_match += 1
            blocking_matches = [match for match in matches if match.get("is_blocking")]
            if blocking_matches:
                orders_blocked += 1
                categories = sorted({cat for match in blocking_matches for cat in match.get("risk_categories", [])})
                status_values = sorted({str(match.get("status") or "") for match in blocking_matches})
                reason_bits = []
                if status_values:
                    reason_bits.append("blocking_status=" + ",".join(status_values))
                if categories:
                    reason_bits.append("risk_category=" + ",".join(categories))
                order["ticket"]["ticket_blocking_reason"] = "; ".join(reason_bits) or "blocking_ticket_match"

    result["ticket_matches_found_count"] = len(unique_ticket_ids)
    result["orders_with_ticket_match_count"] = orders_with_match
    result["orders_blocked_by_ticket_count"] = orders_blocked
    result["ticket_filter_summary"] = {
        "tickets_scanned_count": len(tickets),
        "order_ticket_match_events_count": total_match_count,
        "unique_ticket_matches_count": len(unique_ticket_ids),
        "orders_with_ticket_match_count": orders_with_match,
        "orders_blocked_by_ticket_count": orders_blocked,
    }
    return orders

try:
    installation = ShopifyInstallation.objects.get(shop=shop)
    result["shopify_installation_found"] = True
    token_value = getattr(installation, "access_" + "token")
    result["shopify_credentials_found"] = bool(token_value)
    if not token_value:
        result["failure_type"] = "missing_env"
        result["error"] = "Shopify installation exists, but the access token is empty."
        result["query_failure_message_sanitized"] = result["error"]
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)

    endpoint = "https://" + installation.shop + "/admin/api/" + api_version + "/graphql.json"
    token_header = "X-Shopify-" + "Access-Token"
    headers = {token_header: token_value, "Content-Type": "application/json"}
    for label, query, fields, query_email_sources in queries:
        response = requests.post(endpoint, json={"query": query, "variables": {"first": order_limit}}, headers=headers, timeout=30)
        result["shopify_api_call_performed"] = True
        result["read_only_shopify_query_performed"] = True
        result["http_status"] = response.status_code
        attempt = {
            "label": label,
            "http_status": response.status_code,
            "queried_fields": fields,
            "email_sources": query_email_sources,
            "graphql_error_count": 0,
            "errors_sanitized": [],
            "query_succeeded": False,
            "email_values_found": 0,
            "succeeded": False,
        }
        try:
            data = response.json()
        except ValueError:
            attempt["failure_type"] = "non_json_response"
            result["query_attempts"].append(attempt)
            result["failure_type"] = "command_error"
            result["error"] = "Shopify read-only candidate scan returned non-JSON response."
            result["query_failure_message_sanitized"] = result["error"]
            print(json.dumps(result, ensure_ascii=True))
            raise SystemExit(1)
        if response.status_code >= 400:
            attempt["failure_type"] = "http_error"
            result["query_attempts"].append(attempt)
            result["failure_type"] = "command_error"
            result["error"] = "Shopify read-only candidate scan failed with HTTP status " + str(response.status_code)
            result["query_failure_message_sanitized"] = result["error"]
            print(json.dumps(result, ensure_ascii=True))
            raise SystemExit(1)
        errors = data.get("errors") or []
        if errors:
            sanitized = sanitize_errors(errors)
            attempt["graphql_error_count"] = len(errors)
            attempt["errors_sanitized"] = sanitized
            result["shopify_api_response_error_count"] += len(errors)
            result["shopify_api_response_errors_sanitized"].append({"attempt_label": label, "error_count": len(errors), "errors_sanitized": sanitized})
            result["query_attempts"].append(attempt)
            continue
        connection = ((data.get("data") or {}).get("orders") or {})
        page_info = connection.get("pageInfo") or {}
        orders = build_orders(connection)
        email_values_found = sum(1 for order in orders if (order.get("customer") or {}).get("email"))
        attempt["query_succeeded"] = True
        attempt["email_values_found"] = email_values_found
        if query_email_sources and email_values_found == 0:
            attempt["not_selected_reason"] = "query_succeeded_but_no_email_values_found"
            result["query_attempts"].append(attempt)
            result["query_warning_summary"] = "An email-source query succeeded but returned no email values; trying the next read-only email source."
            continue
        result["has_next_page"] = bool(page_info.get("hasNextPage"))
        result["end_cursor_present"] = bool(page_info.get("endCursor"))
        result["orders"] = apply_ticket_filter(orders)
        result["orders_queried"] = len(orders)
        result["success"] = True
        result["successful_query_label"] = label
        result["queried_fields"] = fields
        attempt["succeeded"] = True
        result["query_attempts"].append(attempt)
        if result["shopify_api_response_error_count"]:
            result["query_warning_summary"] = "Optional richer order fields returned GraphQL errors; the task used a narrower read-only fallback query."
        break
    if not result["success"]:
        result["failure_type"] = "command_error"
        result["error"] = "All read-only Shopify candidate scan query attempts returned GraphQL errors or no selectable result."
        result["query_failure_message_sanitized"] = result["error"]
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    print(json.dumps(result, ensure_ascii=True))
except ShopifyInstallation.DoesNotExist:
    result["failure_type"] = "missing_env"
    result["error"] = "Shopify installation was not found for the configured shop."
    result["query_failure_message_sanitized"] = result["error"]
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
except Exception as exc:
    result["failure_type"] = "unknown"
    result["error"] = type(exc).__name__ + ": " + str(exc)
    result["query_failure_message_sanitized"] = result["error"]
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
'''
    return (
        template.replace("__SHOP_LITERAL__", json.dumps(SHOP_DOMAIN))
        .replace("__API_VERSION_LITERAL__", json.dumps(SHOPIFY_API_VERSION))
        .replace("__ORDER_LIMIT_LITERAL__", str(ORDER_LIMIT))
        .replace("__EMAIL_SOURCES_LITERAL__", json.dumps(EMAIL_SOURCES))
        .replace("__TICKET_BLOCKING_STATUSES_LITERAL__", json.dumps(TICKET_BLOCKING_STATUSES))
        .replace("__TICKET_WARNING_STATUSES_LITERAL__", json.dumps(TICKET_WARNING_STATUSES))
    )


def _classify_orders(orders: list[dict]) -> list[dict]:
    repeat_counts = _repeat_counts(orders)
    return [_classify_order(order, repeat_counts) for order in orders]


def _repeat_counts(orders: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for order in orders:
        if _is_cancelled(order):
            continue
        customer = order.get("customer") or {}
        customer_id = str(customer.get("id") or "").strip()
        email = _normalize_email(customer.get("email"))
        if customer_id:
            counts[f"customer_id:{customer_id}"] += 1
        if email:
            counts[f"email:{email}"] += 1
    return dict(counts)


def _email_parse_source_counts(orders: list[dict]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for order in orders:
        counts[str(order.get("email_parse_source") or "none")] += 1
    return dict(counts)


def _classify_order(order: dict, repeat_counts: dict[str, int]) -> dict:
    tags = [str(tag) for tag in order.get("tags") or []]
    customer = order.get("customer") or {}
    customer_id = str(customer.get("id") or "").strip()
    email = _normalize_email(customer.get("email"))
    email_source = str(customer.get("email_source") or ("detected_in_memory" if email else "none"))
    has_delivered = EXACT_DELIVERED_TAG in tags
    has_review_request = EXACT_REVIEW_REQUEST_TAG in tags
    ticket = order.get("ticket") or {}
    ticket_match_detected = bool(ticket.get("ticket_match_detected"))
    ticket_blocked = bool(ticket.get("ticket_blocked"))
    ticket_status_unknown = any(
        str(item.get("status_category") or "") == "unknown"
        for item in ticket.get("ticket_status_summary", [])
    )
    ticket_risk_categories = set(ticket.get("ticket_risk_categories") or [])
    cancelled = _is_cancelled(order)
    refunded = _has_any(order, ("refund", "refunded", "chargeback", "dispute"))
    shipping_issue = _has_any(order, ("shipping issue", "delivery issue", "failed delivery", "undeliverable", "lost", "return", "returned", "rma", "damaged"))
    repeat = _is_repeat(customer_id, email, repeat_counts)
    buckets = []
    reasons = []
    if has_review_request:
        buckets.append("existing_manual_review_request_tag_present")
        reasons.append("Exact existing manual review-request workflow tag is present.")
    if has_delivered:
        buckets.append("delivered_but_ali_status_unknown")
        reasons.append("Exact Delivered tag is present; Ali Reviews sent-status is not confirmed in Phase 1.")
    if cancelled:
        buckets.append("blocked_cancelled")
        reasons.append("Order appears cancelled from cancelledAt, status, or tags.")
    if refunded:
        buckets.append("blocked_refunded_or_partially_refunded")
        reasons.append("Order appears refunded, partially refunded, disputed, or chargeback-related.")
    if shipping_issue:
        buckets.append("blocked_shipping_or_delivery_issue")
        reasons.append("Order tags or status indicate possible shipping, return, or delivery issue.")
    if ticket_blocked:
        buckets.append("blocked_has_open_ticket")
        reasons.append("Read-only ticket filter found a blocking unresolved or risk ticket match.")
        if "refund" in ticket_risk_categories:
            buckets.append("blocked_has_refund_ticket")
            reasons.append("Matched ticket summary indicates a refund, return, dispute, or chargeback risk.")
        if "shipping_issue" in ticket_risk_categories:
            buckets.append("blocked_has_shipping_issue_ticket")
            reasons.append("Matched ticket summary indicates a shipping or delivery issue risk.")
        if "complaint" in ticket_risk_categories:
            buckets.append("blocked_has_complaint_ticket")
            reasons.append("Matched ticket summary indicates a complaint, dispute, claim, or negative-feedback risk.")
    if ticket_status_unknown and not ticket_blocked:
        buckets.append("ticket_status_unknown_needs_manual_review")
        reasons.append("Matched ticket status could not be confidently mapped; human review is required.")
    if not email:
        buckets.append("blocked_no_email")
        reasons.append("No customer email is available in the read-only order data.")
    blocked = any(bucket.startswith("blocked_") for bucket in buckets)
    readiness_blocked = blocked or ticket_status_unknown
    if repeat and not readiness_blocked:
        buckets.append("repeat_customer_trustpilot_candidate")
        reasons.append("Same customer ID or masked email appears in at least two completed, non-cancelled scanned orders.")
    if has_delivered and not readiness_blocked and email and not has_review_request:
        buckets.append("ready_for_manual_ali_reviews_check")
        reasons.append("Delivered order with customer email and no obvious cancel/refund/shipping block.")
    if has_delivered and readiness_blocked:
        buckets.append("needs_manual_review")
        reasons.append("Delivered order also has a blocking or warning signal.")
    if not buckets:
        buckets.append("needs_manual_review")
        reasons.append("Order does not match a ready, repeat-customer, delivered, existing-tag, or blocked bucket.")
    buckets = _dedupe(buckets)
    return {
        "order_id": str(order.get("id") or ""),
        "order_name": str(order.get("name") or ""),
        "createdAt": str(order.get("created_at") or ""),
        "updatedAt": str(order.get("updated_at") or ""),
        "cancelledAt": str(order.get("cancelled_at") or ""),
        "displayFulfillmentStatus": str(order.get("display_fulfillment_status") or ""),
        "displayFinancialStatus": str(order.get("display_financial_status") or ""),
        "tags": tags,
        "classification": _primary_bucket(buckets),
        "classification_buckets": buckets,
        "classification_reasons": _dedupe(reasons),
        "customer_id": customer_id,
        "masked_email": _mask_email(email),
        "email_present": bool(email),
        "email_parse_source": email_source,
        "email_masking_applied": True,
        "ticket_match_detected": ticket_match_detected,
        "ticket_blocked": ticket_blocked,
        "ticket_blocking_reason": str(ticket.get("ticket_blocking_reason") or ""),
        "ticket_status_summary": ticket.get("ticket_status_summary", []),
        "ticket_risk_categories": sorted(ticket_risk_categories),
        "repeat_customer_detected": repeat,
        "ali_reviews_sent_status": "unknown_not_checked_in_phase_1",
        "ticket_status": "ticket_blocked" if ticket_blocked else ("ticket_match_detected" if ticket_match_detected else "no_ticket_match"),
        "ticket_status_check": "implemented_read_only",
        "action_planned": "report_only",
        "shopify_write_planned": False,
        "email_send_planned": False,
        "ali_reviews_call_planned": False,
    }


def _group_orders(orders: list[dict]) -> dict[str, list[dict]]:
    grouped = {bucket: [] for bucket in BUCKETS}
    for order in orders:
        for bucket in order.get("classification_buckets", []):
            grouped.setdefault(bucket, []).append(order)
    return grouped


def _compact_order(order: dict) -> dict:
    return {
        "order_id": order.get("order_id", ""),
        "order_name": order.get("order_name", ""),
        "createdAt": order.get("createdAt", ""),
        "tags": order.get("tags", []),
        "classification": order.get("classification", ""),
        "classification_buckets": order.get("classification_buckets", []),
        "classification_reasons": order.get("classification_reasons", []),
        "customer_id": order.get("customer_id", ""),
        "masked_email": order.get("masked_email", ""),
        "email_present": bool(order.get("email_present")),
        "email_parse_source": order.get("email_parse_source", ""),
        "email_masking_applied": True,
        "ticket_match_detected": bool(order.get("ticket_match_detected")),
        "ticket_blocked": bool(order.get("ticket_blocked")),
        "ticket_blocking_reason": order.get("ticket_blocking_reason", ""),
        "ticket_status_summary": order.get("ticket_status_summary", []),
        "ticket_risk_categories": order.get("ticket_risk_categories", []),
        "repeat_customer_detected": bool(order.get("repeat_customer_detected")),
        "action_planned": "report_only",
        "shopify_write_planned": False,
        "email_send_planned": False,
        "ali_reviews_call_planned": False,
    }


def _primary_bucket(buckets: list[str]) -> str:
    priority = [
        "blocked_cancelled",
        "blocked_refunded_or_partially_refunded",
        "blocked_shipping_or_delivery_issue",
        "blocked_has_open_ticket",
        "blocked_has_refund_ticket",
        "blocked_has_shipping_issue_ticket",
        "blocked_has_complaint_ticket",
        "existing_manual_review_request_tag_present",
        "blocked_no_email",
        "ticket_status_unknown_needs_manual_review",
        "needs_manual_review",
        "ready_for_manual_ali_reviews_check",
        "repeat_customer_trustpilot_candidate",
        "delivered_but_ali_status_unknown",
    ]
    return next((bucket for bucket in priority if bucket in buckets), "needs_manual_review")


def _is_repeat(customer_id: str, email: str, repeat_counts: dict[str, int]) -> bool:
    return bool(customer_id and repeat_counts.get(f"customer_id:{customer_id}", 0) >= 2) or bool(
        email and repeat_counts.get(f"email:{email}", 0) >= 2
    )


def _is_cancelled(order: dict) -> bool:
    return bool(str(order.get("cancelled_at") or "").strip()) or _has_any(order, ("cancel", "cancelled", "canceled"))


def _has_any(order: dict, indicators: tuple[str, ...]) -> bool:
    text = " ".join(
        [
            str(order.get("display_fulfillment_status") or ""),
            str(order.get("display_financial_status") or ""),
            " ".join(str(tag) for tag in (order.get("tags") or [])),
        ]
    ).lower()
    return any(indicator in text for indicator in indicators)


def _normalize_email(email: str | None) -> str:
    return str(email or "").strip().lower()


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _write_json(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return JSON_PATH


def _write_html(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return HTML_PATH


def _render_html(payload: dict) -> str:
    safety_rows = "\n".join(
        f"<tr><td>{escape(key)}</td><td>{escape(str(payload.get(key)))}</td></tr>"
        for key in [
            "shopify_write_performed",
            "mutation_performed",
            "tags_add_performed",
            "tags_remove_performed",
            "ali_reviews_api_call_performed",
            "gmail_api_call_performed",
            "email_sent",
        ]
    )
    count_rows = "\n".join(
        f"<tr><td><code>{escape(bucket)}</code></td><td>{int(payload.get('classification_counts', {}).get(bucket, 0))}</td></tr>"
        for bucket in BUCKETS
    )
    bucket_sections = "\n".join(
        _render_bucket(bucket, payload.get("classification_buckets", {}).get(bucket, []))
        for bucket in BUCKETS
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Shopify Review Request Candidate Scan</title>
<style>body{{font-family:Arial,sans-serif;margin:24px;color:#1f2933}}table{{border-collapse:collapse;width:100%;margin:12px 0 24px}}th,td{{border:1px solid #d9e2ec;padding:8px;vertical-align:top}}th{{background:#f0f4f8;text-align:left}}code{{background:#f5f7fa;padding:1px 3px}}.warning{{border-left:4px solid #c2410c;background:#fff7ed;padding:10px 12px}}</style></head>
<body>
<h1>Shopify Review Request Candidate Scan</h1>
<p class="warning">Phase 1.1 is report-only. No review request was sent and no Shopify tag was changed.</p>
<p>Status: <strong>{escape(str(payload.get("report_status", "")))}</strong></p>
<p>Orders queried: {payload.get("orders_queried", 0)} | Limit: {payload.get("order_query_limit", 0)}</p>
<p>Exact tags: <code>{escape(EXACT_DELIVERED_TAG)}</code> and <code>{escape(EXACT_REVIEW_REQUEST_TAG)}</code></p>
<h2>Query Diagnostics</h2>
<table><tbody>
<tr><th>Successful query label</th><td><code>{escape(str(payload.get("successful_query_label", "")))}</code></td></tr>
<tr><th>Email sources attempted</th><td>{escape(", ".join(str(item) for item in payload.get("email_field_sources_attempted", [])))}</td></tr>
<tr><th>Email source counts</th><td><code>{escape(json.dumps(payload.get("email_parse_source_counts", {}), ensure_ascii=False))}</code></td></tr>
<tr><th>Orders with email</th><td>{int(payload.get("orders_with_email_count") or 0)}</td></tr>
<tr><th>Orders without email</th><td>{int(payload.get("orders_without_email_count") or 0)}</td></tr>
<tr><th>Email masking applied</th><td>{escape(str(payload.get("email_masking_applied")))}</td></tr>
<tr><th>Failure message</th><td>{escape(str(payload.get("query_failure_message_sanitized", "")))}</td></tr>
</tbody></table>
<h2>Ticket / Risk Filter</h2>
<table><tbody>
<tr><th>Ticket status check</th><td>{escape(str(payload.get("ticket_status_check", "")))}</td></tr>
<tr><th>Ticket model detected</th><td>{escape(str(payload.get("ticket_model_detected")))}</td></tr>
<tr><th>Ticket query performed</th><td>{escape(str(payload.get("ticket_query_performed")))}</td></tr>
<tr><th>Ticket matches found</th><td>{int(payload.get("ticket_matches_found_count") or 0)}</td></tr>
<tr><th>Orders with ticket match</th><td>{int(payload.get("orders_with_ticket_match_count") or 0)}</td></tr>
<tr><th>Orders blocked by ticket</th><td>{int(payload.get("orders_blocked_by_ticket_count") or 0)}</td></tr>
<tr><th>Blocking statuses</th><td>{escape(", ".join(str(item) for item in payload.get("ticket_blocking_statuses", [])))}</td></tr>
<tr><th>Warning statuses</th><td>{escape(", ".join(str(item) for item in payload.get("ticket_warning_statuses", [])))}</td></tr>
<tr><th>Ticket filter error</th><td>{escape(str(payload.get("ticket_filter_error_sanitized", "")))}</td></tr>
</tbody></table>
<h2>Safety</h2><table><tbody>{safety_rows}</tbody></table>
<h2>Classification Counts</h2><table><thead><tr><th>Bucket</th><th>Count</th></tr></thead><tbody>{count_rows}</tbody></table>
{bucket_sections}
</body></html>"""


def _render_bucket(bucket: str, orders: list[dict]) -> str:
    rows = "\n".join(_render_order_row(order) for order in orders)
    if not rows:
        rows = '<tr><td colspan="8">No orders in this bucket.</td></tr>'
    return f"""<h2><code>{escape(bucket)}</code></h2>
<table><thead><tr><th>Order</th><th>Created</th><th>Masked email</th><th>Email source</th><th>Customer ID</th><th>Tags</th><th>Classification</th><th>Ticket summary</th></tr></thead><tbody>{rows}</tbody></table>"""


def _render_order_row(order: dict) -> str:
    tags = ", ".join(f"<code>{escape(str(tag))}</code>" for tag in order.get("tags", []))
    ticket_summary = _render_ticket_summary(order.get("ticket_status_summary", []), order.get("ticket_blocking_reason", ""))
    return f"""<tr><td>{escape(str(order.get("order_name", "")))}<br><code>{escape(str(order.get("order_id", "")))}</code></td><td>{escape(str(order.get("createdAt", "")))}</td><td>{escape(str(order.get("masked_email", "")))}</td><td>{escape(str(order.get("email_parse_source", "")))}</td><td><code>{escape(str(order.get("customer_id", "")))}</code></td><td>{tags}</td><td><code>{escape(str(order.get("classification", "")))}</code></td><td>{ticket_summary}</td></tr>"""


def _render_ticket_summary(ticket_summaries: list[dict], blocking_reason: str) -> str:
    if not ticket_summaries:
        return "-"
    rows = []
    if blocking_reason:
        rows.append(f"<strong>{escape(str(blocking_reason))}</strong>")
    for item in ticket_summaries[:5]:
        parts = [
            f"Ticket {escape(str(item.get('ticket_id', '')))}",
            f"status={escape(str(item.get('status', '')))}",
            f"priority={escape(str(item.get('priority', '')))}",
            f"category={escape(str(item.get('status_category', '')))}",
        ]
        risks = item.get("risk_categories") or []
        if risks:
            parts.append("risk=" + escape(",".join(str(risk) for risk in risks)))
        rows.append("<br>".join(parts))
    return "<hr>".join(rows)


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    counts = payload.get("classification_counts") or {}
    return (
        "Shopify review request Phase 1.1 candidate scan finished.\n"
        f"Status: {payload.get('report_status')}\n"
        f"Orders queried: {payload.get('orders_queried')}\n"
        f"Orders with masked email: {payload.get('orders_with_email_count')}\n"
        f"Ticket query performed: {payload.get('ticket_query_performed')}\n"
        f"Orders blocked by ticket: {payload.get('orders_blocked_by_ticket_count')}\n"
        f"Ready for manual Ali Reviews check: {counts.get('ready_for_manual_ali_reviews_check', 0)}\n"
        f"Blocked orders: {len(payload.get('blocked_orders', []))}\n"
        "Safety: read-only Shopify order query only; no Shopify writes, tagsAdd, tagsRemove, Ali Reviews API, Gmail API, or email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _empty_query_result() -> dict:
    return {
        "success": False,
        "shopify_api_call_performed": False,
        "read_only_shopify_query_performed": False,
        "shopify_query_type": "",
        "http_status": None,
        "orders_queried": 0,
        "orders": [],
        "email_field_sources_attempted": EMAIL_SOURCES,
        "ticket_status_check": "blocked_ticket_filter_error",
        "ticket_model_detected": False,
        "ticket_query_performed": False,
        "ticket_matches_found_count": 0,
        "orders_with_ticket_match_count": 0,
        "orders_blocked_by_ticket_count": 0,
        "ticket_blocking_statuses": TICKET_BLOCKING_STATUSES,
        "ticket_warning_statuses": TICKET_WARNING_STATUSES,
        "ticket_filter_error_sanitized": "Django shell was not reached; ticket model inspection did not run.",
        "ticket_filter_summary": {},
        "command_attempted_sanitized": _safe_command_attempt(),
        "docker_command_reached": False,
        "django_shell_reached": False,
        "shopify_installation_found": False,
        "shopify_credentials_found": False,
        "shopify_api_response_error_count": 0,
        "shopify_api_response_errors_sanitized": [],
        "query_attempts": [],
        "successful_query_label": "",
        "query_warning_summary": "",
        "query_failure_message_sanitized": "",
        "failure_type": "",
        "error": "",
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _issue_summary(success: bool, query_result: dict, orders: list[dict]) -> str:
    if success:
        return f"Read-only Phase 1.1 candidate scan classified {len(orders)} orders. No writes or sends were performed."
    error = query_result.get("query_failure_message_sanitized") or query_result.get("failure_type") or "unknown"
    return f"Read-only Shopify candidate scan did not complete: {_sanitize_text(str(error))}"


def _parse_json_from_stdout(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _classify_command_failure(stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if "access is denied" in combined or "permission denied" in combined or "docker_engine" in combined:
        return "docker_permission_denied"
    if "no such file or directory" in combined or "not recognized" in combined:
        return "missing_env"
    return "command_error"


def _safe_command_attempt() -> str:
    return "docker compose exec -T web python manage.py shell -c <phase1 read-only script>"


def _tail(text: str, max_lines: int = 80) -> str:
    return "\n".join(text.splitlines()[-max_lines:])


def _decode_bytes(value: bytes | None) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _sanitize_text(text: str) -> str:
    redacted = SENSITIVE_TEXT_RE.sub("[redacted]", text or "")
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)
