import base64
import json
import os
import re
import subprocess
import time
from email import message_from_bytes, policy
from email.message import EmailMessage
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send"

SOURCE_READINESS_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness.json"
SOURCE_EXECUTOR_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.json"
SOURCE_PREFLIGHT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight.json"
SOURCE_LOCKED_DRAFT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send.html"

READY_STATUS = "trustpilot_gmail_draft_content_ready_for_send"
EXPECTED_READINESS_STATUS = "trustpilot_gmail_one_draft_real_send_ready_for_manual_execution"
EXPECTED_EXECUTOR_STATUS = "dry_run_real_send_not_executed"
EXPECTED_PREFLIGHT_STATUS = "trustpilot_gmail_one_draft_send_final_preflight_ready"
EXPECTED_LOCKED_DRAFT_STATUS = "gmail_one_draft_created_locked_runner"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
GMAIL_SEND_FROM = "info@kidstoylover.com"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
SUBJECT = "How was your Kidstoylover experience?"
TRUSTPILOT_URL = "https://www.trustpilot.com/evaluate/www.kidstoylover.com"
TRUSTPILOT_LINK_TEXT = "Leave us a review on Trustpilot"
PROTECTED_LOOKUP_TIMEOUT_SECONDS = 120
ALLOWED_REPORT_EMAILS = {GMAIL_SEND_FROM.lower()}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
FULL_DRAFT_ID_RE = re.compile(r"\br-[A-Za-z0-9_-]{10,}\b")
SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"shpat_[A-Za-z0-9_]+"),
    re.compile(r"(?i)access[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)refresh[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)client[_\s-]?secret\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
]


def run_shopify_review_request_trustpilot_gmail_draft_content_update_pre_send_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    readiness_report, readiness_error = _read_json_report(
        SOURCE_READINESS_JSON_PATH, "blocked_missing_real_run_readiness_report"
    )
    executor_report, executor_error = _read_json_report(
        SOURCE_EXECUTOR_JSON_PATH, "blocked_missing_executor_dry_run_report"
    )
    preflight_report, preflight_error = _read_json_report(
        SOURCE_PREFLIGHT_JSON_PATH, "blocked_missing_final_preflight_report"
    )
    locked_draft_report, locked_draft_error = _read_json_report(
        SOURCE_LOCKED_DRAFT_JSON_PATH, "blocked_missing_locked_draft_report"
    )
    source_reports = {
        "readiness": readiness_report,
        "executor": executor_report,
        "preflight": preflight_report,
        "locked_draft": locked_draft_report,
    }
    source_errors = {
        "readiness": readiness_error,
        "executor": executor_error,
        "preflight": preflight_error,
        "locked_draft": locked_draft_error,
    }
    base_conditions = _source_blocking_conditions(source_reports, source_errors)
    operation = _draft_content_operation(source_reports, base_conditions)
    status = _status_from_operation(base_conditions, operation)
    payload = _build_payload(
        source_reports=source_reports,
        source_errors=source_errors,
        base_conditions=base_conditions,
        operation=operation,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_json_report(path: Path, missing_status: str) -> tuple[dict, str]:
    if not path.exists():
        return {}, missing_status
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"{missing_status}: source JSON parse failed: {exc}")


def _source_blocking_conditions(source_reports: dict, source_errors: dict) -> list[dict]:
    conditions = []
    if source_errors["readiness"]:
        conditions.append({"status": "blocked_missing_real_run_readiness_report", "detail": source_errors["readiness"]})
    if source_errors["executor"]:
        conditions.append({"status": "blocked_missing_executor_dry_run_report", "detail": source_errors["executor"]})
    if source_errors["preflight"]:
        conditions.append({"status": "blocked_missing_final_preflight_report", "detail": source_errors["preflight"]})
    if source_errors["locked_draft"]:
        conditions.append({"status": "blocked_missing_locked_draft_report", "detail": source_errors["locked_draft"]})
    if conditions:
        return conditions

    readiness = source_reports["readiness"]
    executor = source_reports["executor"]
    preflight = source_reports["preflight"]
    locked_draft = source_reports["locked_draft"]
    if readiness.get("real_run_readiness_status") != EXPECTED_READINESS_STATUS:
        conditions.append({"status": "blocked_real_run_readiness_not_ready", "detail": "Phase 3.16B readiness is not ready."})
    if executor.get("one_draft_send_execute_status") != EXPECTED_EXECUTOR_STATUS:
        conditions.append({"status": "blocked_executor_dry_run_not_ready", "detail": "Phase 3.16 executor is not a clean no-send dry-run."})
    if preflight.get("final_preflight_status") != EXPECTED_PREFLIGHT_STATUS:
        conditions.append({"status": "blocked_final_preflight_not_ready", "detail": "Phase 3.15 final preflight is not ready."})
    if locked_draft.get("one_draft_status") != EXPECTED_LOCKED_DRAFT_STATUS:
        conditions.append({"status": "blocked_locked_draft_not_created", "detail": "Phase 3.11 locked draft report does not show one created draft."})
    if int(locked_draft.get("gmail_drafts_created_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_draft_count", "detail": "locked draft count is not exactly one."})
    for report_name, report in source_reports.items():
        _check_expected_identity(report_name, report, conditions)
        _check_no_send_or_write_flags(report_name, report, conditions)
    return conditions


def _check_expected_identity(report_name: str, report: dict, conditions: list[dict]) -> None:
    if _safe_text(report.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_source_identity_mismatch", "detail": f"{report_name} selected_order_name mismatch."})
    if _safe_text(report.get("selected_masked_email", "")) != EXPECTED_MASKED_EMAIL:
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": f"{report_name} selected_masked_email mismatch."})
    partial = _safe_text(
        report.get("source_gmail_draft_id_partial")
        or report.get("gmail_draft_id_partial")
        or _partial_id(report.get("gmail_draft_id", ""))
    )
    if partial != EXPECTED_DRAFT_ID_PARTIAL:
        conditions.append({"status": "blocked_draft_identity_mismatch", "detail": f"{report_name} draft id partial mismatch."})


def _check_no_send_or_write_flags(report_name: str, report: dict, conditions: list[dict]) -> None:
    if any(report.get(flag) is True for flag in ("gmail_drafts_send_called", "gmail_messages_send_called", "gmail_send_performed", "email_sent")):
        conditions.append({"status": "blocked_gmail_send_flag_detected", "detail": f"{report_name} send flag is true."})
    if any(report.get(flag) is True for flag in ("shopify_write_performed", "mutation_performed")):
        conditions.append({"status": "blocked_shopify_write_flag_detected", "detail": f"{report_name} Shopify write flag is true."})
    if any(report.get(flag) is True for flag in ("tags_add_performed", "tags_remove_performed", "tagsAdd_performed", "tagsRemove_performed")):
        conditions.append({"status": "blocked_tag_write_flag_detected", "detail": f"{report_name} Shopify tag write flag is true."})
    if any(report.get(flag) is True for flag in ("kudosi_api_call_performed", "ali_reviews_api_call_performed")):
        conditions.append({"status": "blocked_kudosi_flag_detected", "detail": f"{report_name} Kudosi/Ali Reviews flag is true."})


def _draft_content_operation(source_reports: dict, base_conditions: list[dict]) -> dict:
    result = _operation_defaults()
    if base_conditions:
        return result

    selected = _selected_order_context(source_reports)
    draft_id = _protected_runtime_draft_id(source_reports["locked_draft"])
    if not draft_id:
        result["draft_content_pre_send_status"] = "blocked_missing_draft_id_for_update"
        result["blocking_conditions"].append({"status": "blocked_missing_draft_id_for_update", "detail": "Full draft id is unavailable from protected source."})
        return result

    lookup = _protected_runtime_customer_lookup(selected)
    _apply_customer_lookup_report(result, lookup)
    raw_recipient = lookup.get("_raw_email_for_runtime_only", "")
    first_name = lookup.get("_first_name_for_runtime_only", "")
    if not raw_recipient:
        result["draft_content_pre_send_status"] = "blocked_missing_raw_email_for_draft_update"
        result["blocking_conditions"].append({"status": "blocked_missing_raw_email_for_draft_update", "detail": "Protected lookup did not return a runtime recipient."})
        return result
    if not first_name:
        result["draft_content_pre_send_status"] = "blocked_missing_customer_first_name"
        result["blocking_conditions"].append({"status": "blocked_missing_customer_first_name", "detail": "Protected lookup did not return a customer first name."})
        return result
    result["customer_first_name_detected"] = True

    gmail_env = _gmail_env()
    result["gmail_oauth_present"] = gmail_env["gmail_oauth_present"]
    result["gmail_compose_scope_present"] = gmail_env["gmail_compose_scope_present"]
    result["gmail_sender_matches_expected"] = gmail_env["gmail_sender_matches_expected"]
    if not gmail_env["gmail_oauth_present"]:
        result["draft_content_pre_send_status"] = "blocked_missing_gmail_oauth"
        result["blocking_conditions"].append({"status": "blocked_missing_gmail_oauth", "detail": "Gmail OAuth environment is missing."})
        return result
    if not gmail_env["gmail_sender_matches_expected"]:
        result["draft_content_pre_send_status"] = "blocked_sender_mismatch"
        result["blocking_conditions"].append({"status": "blocked_sender_mismatch", "detail": "Gmail sender does not match expected sender."})
        return result
    if not gmail_env["gmail_compose_scope_present"]:
        result["draft_content_pre_send_status"] = "blocked_missing_gmail_compose_scope"
        result["blocking_conditions"].append({"status": "blocked_missing_gmail_compose_scope", "detail": "Gmail compose scope is not configured."})
        return result

    try:
        service = _build_gmail_service(gmail_env, result)
        _get_and_update_draft_if_needed(service, draft_id, raw_recipient, first_name, result)
    except Exception as exc:  # pragma: no cover - exercised only with live Gmail.
        if not result["draft_content_pre_send_status"].startswith("blocked"):
            result["draft_content_pre_send_status"] = "blocked_gmail_draft_content_update_failed"
        result["gmail_error_sanitized"] = _sanitize_text(str(exc))
    return result


def _operation_defaults() -> dict:
    return {
        "draft_content_pre_send_status": "blocked_source_reports_not_ready",
        "gmail_api_call_performed": False,
        "gmail_token_refresh_attempted": False,
        "gmail_token_refresh_succeeded": False,
        "gmail_oauth_present": False,
        "gmail_compose_scope_present": False,
        "gmail_sender_matches_expected": False,
        "gmail_drafts_get_called": False,
        "gmail_draft_get_attempted": False,
        "gmail_draft_get_succeeded": False,
        "gmail_drafts_update_called": False,
        "gmail_draft_update_attempted": False,
        "gmail_draft_updated": False,
        "gmail_draft_update_needed": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "customer_first_name_detected": False,
        "first_name_output_suppressed": True,
        "greeting_uses_dear_first_name": False,
        "trustpilot_link_present": False,
        "trustpilot_link_is_html_anchor": False,
        "subject_matches_expected": False,
        "draft_content_ready_after_update": False,
        "raw_email_lookup_attempted": False,
        "raw_email_available": False,
        "raw_email_source": "",
        "first_name_lookup_attempted": False,
        "first_name_available": False,
        "customer_profile_lookup_source": "",
        "successful_fallback_query_label": "",
        "raw_email_lookup_error_sanitized": "",
        "raw_email_lookup_docker_command_reached": False,
        "raw_email_lookup_django_shell_reached": False,
        "raw_email_lookup_shopify_api_call_performed": False,
        "gmail_error_sanitized": "",
        "privacy_assertion_passed": True,
        "raw_email_leak_risk_detected": False,
        "blocking_conditions": [],
    }


def _selected_order_context(source_reports: dict) -> dict:
    locked_draft = source_reports["locked_draft"]
    return {
        "order_name": EXPECTED_ORDER_NAME,
        "order_id_or_gid": _safe_text(locked_draft.get("selected_order_id_or_gid", "")),
        "masked_email": EXPECTED_MASKED_EMAIL,
    }


def _protected_runtime_draft_id(locked_draft_report: dict) -> str:
    draft_id = _safe_text(locked_draft_report.get("gmail_draft_id", ""))
    if not draft_id:
        return ""
    if _partial_id(draft_id) != EXPECTED_DRAFT_ID_PARTIAL:
        return ""
    return draft_id


def _protected_runtime_customer_lookup(selected: dict) -> dict:
    lookup = {
        "raw_email_lookup_attempted": True,
        "raw_email_available": False,
        "raw_email_source": "protected_runtime_lookup",
        "first_name_lookup_attempted": True,
        "first_name_available": False,
        "customer_profile_lookup_source": "",
        "successful_fallback_query_label": "",
        "raw_email_lookup_error_sanitized": "",
        "raw_email_lookup_docker_command_reached": False,
        "raw_email_lookup_django_shell_reached": False,
        "raw_email_lookup_shopify_api_call_performed": False,
        "_raw_email_for_runtime_only": "",
        "_first_name_for_runtime_only": "",
    }
    order_id_or_gid = _safe_text(selected.get("order_id_or_gid", ""))
    order_name = _safe_text(selected.get("order_name", ""))
    if not order_id_or_gid and not order_name:
        lookup["raw_email_lookup_error_sanitized"] = "missing_stable_order_identifier_for_protected_lookup"
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
        _protected_customer_lookup_script(order_id_or_gid, order_name),
    ]
    try:
        completed = subprocess.run(
            command,
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
        lookup["successful_fallback_query_label"] = _safe_text(parsed.get("successful_fallback_query_label", ""))
        raw_email = _safe_runtime_email(parsed.get("raw_email", ""))
        first_name = _safe_first_name(parsed.get("first_name", ""))
        lookup["_raw_email_for_runtime_only"] = raw_email
        lookup["_first_name_for_runtime_only"] = first_name
        lookup["raw_email_available"] = bool(raw_email)
        lookup["first_name_available"] = bool(first_name)
        lookup["customer_profile_lookup_source"] = _safe_text(parsed.get("first_name_source", ""))
    if completed.returncode != 0:
        lookup["raw_email_lookup_error_sanitized"] = _sanitize_text(
            parsed.get("error_sanitized", "") if parsed else (completed.stderr or completed.stdout or "protected lookup failed")
        )
    return lookup


def _protected_customer_lookup_script(order_id_or_gid: str, order_name: str) -> str:
    template = r'''
import json
import re
import requests
from shopify_sync.models import ShopifyInstallation

shop = __SHOP_LITERAL__
api_version = __API_VERSION_LITERAL__
order_id_or_gid = __ORDER_ID_LITERAL__
order_name = __ORDER_NAME_LITERAL__
email_re = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
result = {
    "django_shell_reached": True,
    "shopify_installation_found": False,
    "shopify_credentials_found": False,
    "shopify_api_call_performed": False,
    "raw_email_available": False,
    "first_name_available": False,
    "raw_email": "",
    "raw_email_source": "",
    "first_name": "",
    "first_name_source": "",
    "successful_fallback_query_label": "",
    "error_sanitized": "",
}

def sanitize(text):
    text = str(text or "")
    text = re.sub(r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)", "[redacted]", text)
    return email_re.sub("[masked-email]", text)

def clean_name(value):
    value = str(value or "").strip()
    value = re.sub(r"[^A-Za-z][\s\S]*$", "", value)
    return value[:40]

def selected_email(order):
    customer = order.get("customer") or {}
    candidates = [
        ("email", order.get("email")),
        ("customer.email", customer.get("email")),
        ("contactEmail", order.get("contactEmail")),
        ("contact_email", order.get("contact_email")),
    ]
    for source, value in candidates:
        value = str(value or "").strip()
        if value and email_re.fullmatch(value):
            return value.lower(), source
    return "", ""

def selected_first_name(order):
    customer = order.get("customer") or {}
    shipping = order.get("shippingAddress") or order.get("shipping_address") or {}
    billing = order.get("billingAddress") or order.get("billing_address") or {}
    candidates = [
        ("customer.firstName", customer.get("firstName")),
        ("customer.first_name", customer.get("first_name")),
        ("shippingAddress.firstName", shipping.get("firstName")),
        ("shipping_address.first_name", shipping.get("first_name")),
        ("billingAddress.firstName", billing.get("firstName")),
        ("billing_address.first_name", billing.get("first_name")),
        ("shippingAddress.name", shipping.get("name")),
        ("billingAddress.name", billing.get("name")),
    ]
    for source, value in candidates:
        first = clean_name(value)
        if first:
            return first, source
    return "", ""

def request_graphql(label, endpoint, headers, query, variables, kind):
    response = requests.post(endpoint, json={"query": query, "variables": variables}, headers=headers, timeout=30)
    result["shopify_api_call_performed"] = True
    if response.status_code >= 400:
        result["error_sanitized"] = "Shopify GraphQL HTTP error " + str(response.status_code)
        return None
    try:
        data = response.json()
    except ValueError:
        result["error_sanitized"] = "Shopify GraphQL non-JSON response"
        return None
    errors = data.get("errors") or []
    if errors:
        result["error_sanitized"] = sanitize(errors[0].get("message") if isinstance(errors[0], dict) else errors[0])[:300]
        return None
    data = data.get("data") or {}
    if kind == "node":
        node = data.get("node") or {}
        return node or None
    edges = (((data.get("orders") or {}).get("edges")) or [])
    nodes = [edge.get("node") or {} for edge in edges]
    if order_name:
        exact = [node for node in nodes if node.get("name") == order_name]
        if exact:
            return exact[0]
    if order_id_or_gid:
        exact = [node for node in nodes if node.get("id") == order_id_or_gid]
        if exact:
            return exact[0]
    return nodes[0] if nodes else None

def try_rest_order(rest_id, rest_base, headers):
    if not rest_id:
        return False
    url = rest_base + "/orders/" + rest_id + ".json"
    params = {"fields": "id,name,email,contact_email,shipping_address,billing_address,customer"}
    response = requests.get(url, params=params, headers=headers, timeout=30)
    result["shopify_api_call_performed"] = True
    if response.status_code >= 400:
        result["error_sanitized"] = "Shopify REST HTTP error " + str(response.status_code)
        return False
    try:
        data = response.json()
    except ValueError:
        result["error_sanitized"] = "Shopify REST non-JSON response"
        return False
    order = data.get("order") or {}
    if not order:
        return False
    raw_email, email_source = selected_email(order)
    first_name, first_name_source = selected_first_name(order)
    if raw_email and first_name:
        result["raw_email_available"] = True
        result["first_name_available"] = True
        result["raw_email"] = raw_email
        result["raw_email_source"] = email_source
        result["first_name"] = first_name
        result["first_name_source"] = first_name_source
        result["successful_fallback_query_label"] = "rest_order_profile"
        return True
    return False

try:
    installation = ShopifyInstallation.objects.get(shop=shop)
    result["shopify_installation_found"] = True
    token_value = getattr(installation, "access_" + "token")
    result["shopify_credentials_found"] = bool(token_value)
    if not token_value:
        result["error_sanitized"] = "Shopify installation exists, but the access token is empty."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    rest_base = "https://" + installation.shop + "/admin/api/" + api_version
    endpoint = rest_base + "/graphql.json"
    token_header = "X-Shopify-" + "Access-Token"
    headers = {token_header: token_value, "Content-Type": "application/json"}
    rest_id = ""
    if order_id_or_gid.startswith("gid://shopify/Order/"):
        rest_id = order_id_or_gid.rsplit("/", 1)[-1]
    if try_rest_order(rest_id, rest_base, headers):
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(0)
    attempts = []
    if order_name:
        attempts.append((
            "name_order_contact_profile",
            "query ProtectedOrderContactProfile($query: String!) { orders(first: 10, query: $query) { edges { node { id name email contactEmail shippingAddress { firstName name } billingAddress { firstName name } } } } }",
            {"query": "name:" + order_name},
            "orders",
        ))
        attempts.append((
            "name_customer_profile",
            "query ProtectedOrderCustomerProfile($query: String!) { orders(first: 10, query: $query) { edges { node { id name email contactEmail customer { id email firstName } shippingAddress { firstName name } billingAddress { firstName name } } } } }",
            {"query": "name:" + order_name},
            "orders",
        ))
        attempts.append((
            "name_customer_email",
            "query ProtectedOrderCustomerEmail($query: String!) { orders(first: 10, query: $query) { edges { node { id name customer { id email firstName } } } } }",
            {"query": "name:" + order_name},
            "orders",
        ))
    if order_id_or_gid.startswith("gid://shopify/Order/"):
        attempts.append((
            "id_order_contact_profile",
            "query ProtectedOrderContactProfileById($id: ID!) { node(id: $id) { ... on Order { id name email contactEmail shippingAddress { firstName name } billingAddress { firstName name } } } }",
            {"id": order_id_or_gid},
            "node",
        ))
        attempts.append((
            "id_customer_profile",
            "query ProtectedOrderCustomerProfileById($id: ID!) { node(id: $id) { ... on Order { id name email contactEmail customer { id email firstName } shippingAddress { firstName name } billingAddress { firstName name } } } }",
            {"id": order_id_or_gid},
            "node",
        ))
        attempts.append((
            "id_customer_email",
            "query ProtectedOrderCustomerEmailById($id: ID!) { node(id: $id) { ... on Order { id name customer { id email firstName } } } }",
            {"id": order_id_or_gid},
            "node",
        ))
    for label, query, variables, kind in attempts:
        order = request_graphql(label, endpoint, headers, query, variables, kind)
        if not order:
            continue
        raw_email, email_source = selected_email(order)
        first_name, first_name_source = selected_first_name(order)
        if raw_email and first_name:
            result["raw_email_available"] = True
            result["first_name_available"] = True
            result["raw_email"] = raw_email
            result["raw_email_source"] = email_source
            result["first_name"] = first_name
            result["first_name_source"] = first_name_source
            result["successful_fallback_query_label"] = label
            print(json.dumps(result, ensure_ascii=True))
            raise SystemExit(0)
    result["error_sanitized"] = result["error_sanitized"] or "protected customer lookup did not return both email and first name."
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
except Exception as exc:
    result["error_sanitized"] = sanitize(str(exc))[:300]
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
'''
    script = template.replace("__SHOP_LITERAL__", json.dumps(SHOP_DOMAIN))
    script = script.replace("__API_VERSION_LITERAL__", json.dumps(SHOPIFY_API_VERSION))
    script = script.replace("__ORDER_ID_LITERAL__", json.dumps(order_id_or_gid))
    script = script.replace("__ORDER_NAME_LITERAL__", json.dumps(order_name))
    return script


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
    result["raw_email_lookup_attempted"] = bool(lookup.get("raw_email_lookup_attempted"))
    result["raw_email_available"] = bool(lookup.get("raw_email_available"))
    result["raw_email_source"] = _safe_text(lookup.get("raw_email_source", "protected_runtime_lookup"))
    result["first_name_lookup_attempted"] = bool(lookup.get("first_name_lookup_attempted"))
    result["first_name_available"] = bool(lookup.get("first_name_available"))
    result["customer_profile_lookup_source"] = _safe_text(lookup.get("customer_profile_lookup_source", ""))
    result["successful_fallback_query_label"] = _safe_text(lookup.get("successful_fallback_query_label", ""))
    result["raw_email_lookup_error_sanitized"] = _sanitize_text(lookup.get("raw_email_lookup_error_sanitized", ""))
    result["raw_email_lookup_docker_command_reached"] = bool(lookup.get("raw_email_lookup_docker_command_reached"))
    result["raw_email_lookup_django_shell_reached"] = bool(lookup.get("raw_email_lookup_django_shell_reached"))
    result["raw_email_lookup_shopify_api_call_performed"] = bool(lookup.get("raw_email_lookup_shopify_api_call_performed"))


def _gmail_env() -> dict:
    dotenv_values = _read_dotenv_values()
    send_from = _env_value("GMAIL_SEND_FROM", dotenv_values)
    client_id = _env_value("GOOGLE_GMAIL_CLIENT_ID", dotenv_values)
    client_secret = _env_value("GOOGLE_GMAIL_CLIENT_SECRET", dotenv_values)
    refresh_token = _env_value("GOOGLE_GMAIL_REFRESH_TOKEN", dotenv_values)
    scopes = _split_scopes(_env_value("GOOGLE_GMAIL_SCOPES", dotenv_values))
    missing = []
    if not send_from:
        missing.append("GMAIL_SEND_FROM")
    if not client_id:
        missing.append("GOOGLE_GMAIL_CLIENT_ID")
    if not client_secret:
        missing.append("GOOGLE_GMAIL_CLIENT_SECRET")
    if not refresh_token:
        missing.append("GOOGLE_GMAIL_REFRESH_TOKEN")
    if not scopes:
        missing.append("GOOGLE_GMAIL_SCOPES")
    return {
        "send_from": send_from,
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "scopes": scopes,
        "gmail_oauth_present": not missing,
        "gmail_compose_scope_present": GMAIL_COMPOSE_SCOPE in scopes,
        "gmail_sender_matches_expected": send_from == GMAIL_SEND_FROM,
    }


def _read_dotenv_values() -> dict:
    dotenv_path = Path.cwd() / ".env"
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

    credentials = Credentials(
        token=None,
        refresh_token=gmail_env["refresh_token"],
        token_uri="https://oauth2.googleapis.com/token",
        client_id=gmail_env["client_id"],
        client_secret=gmail_env["client_secret"],
        scopes=gmail_env["scopes"],
    )
    result["gmail_api_call_performed"] = True
    result["gmail_token_refresh_attempted"] = True
    credentials.refresh(Request())
    result["gmail_token_refresh_succeeded"] = True
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _get_and_update_draft_if_needed(service, draft_id: str, raw_recipient: str, first_name: str, result: dict) -> None:
    result["gmail_draft_get_attempted"] = True
    result["gmail_drafts_get_called"] = True
    result["gmail_api_call_performed"] = True
    draft = service.users().drafts().get(userId="me", id=draft_id, format="raw").execute()
    result["gmail_draft_get_succeeded"] = True
    existing_subject, existing_html = _decode_draft_subject_and_html(draft)
    checks = _content_checks(existing_subject, existing_html, first_name)
    _apply_content_checks(result, checks)
    needs_update = not _all_content_checks_pass(checks)
    result["gmail_draft_update_needed"] = needs_update
    if not needs_update:
        result["draft_content_pre_send_status"] = READY_STATUS
        result["draft_content_ready_after_update"] = True
        return

    message = _build_updated_message(raw_recipient, first_name)
    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    result["gmail_draft_update_attempted"] = True
    result["gmail_drafts_update_called"] = True
    result["gmail_api_call_performed"] = True
    service.users().drafts().update(userId="me", id=draft_id, body={"message": {"raw": encoded}}).execute()
    result["gmail_draft_updated"] = True
    updated_checks = _content_checks(SUBJECT, _html_body(first_name), first_name)
    _apply_content_checks(result, updated_checks)
    result["draft_content_ready_after_update"] = _all_content_checks_pass(updated_checks)
    result["draft_content_pre_send_status"] = READY_STATUS if result["draft_content_ready_after_update"] else "blocked_content_validation_failed"


def _decode_draft_subject_and_html(draft: dict) -> tuple[str, str]:
    raw = (((draft.get("message") or {}).get("raw")) or "").strip()
    if not raw:
        return "", ""
    padding = "=" * (-len(raw) % 4)
    message_bytes = base64.urlsafe_b64decode((raw + padding).encode("ascii"))
    message = message_from_bytes(message_bytes, policy=policy.default)
    subject = str(message.get("Subject", ""))
    html = ""
    plain = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/html" and not html:
                html = str(part.get_content())
            elif content_type == "text/plain" and not plain:
                plain = str(part.get_content())
    else:
        content_type = message.get_content_type()
        if content_type == "text/html":
            html = str(message.get_content())
        elif content_type == "text/plain":
            plain = str(message.get_content())
    return subject, html or plain


def _content_checks(subject: str, body: str, first_name: str) -> dict:
    body_text = re.sub(r"<[^>]+>", " ", body or "")
    body_text = re.sub(r"\s+", " ", body_text)
    greeting_pattern = re.compile(rf"\bDear\s+{re.escape(first_name)}\s*,", re.IGNORECASE)
    anchor_pattern = re.compile(
        rf"<a\s+[^>]*href=[\"']{re.escape(TRUSTPILOT_URL)}[\"'][^>]*>\s*{re.escape(TRUSTPILOT_LINK_TEXT)}\s*</a>",
        re.IGNORECASE,
    )
    return {
        "subject_matches_expected": str(subject or "").strip() == SUBJECT,
        "greeting_uses_dear_first_name": bool(greeting_pattern.search(body_text)),
        "trustpilot_link_present": TRUSTPILOT_URL in (body or ""),
        "trustpilot_link_is_html_anchor": bool(anchor_pattern.search(body or "")),
    }


def _apply_content_checks(result: dict, checks: dict) -> None:
    result["subject_matches_expected"] = checks["subject_matches_expected"]
    result["greeting_uses_dear_first_name"] = checks["greeting_uses_dear_first_name"]
    result["trustpilot_link_present"] = checks["trustpilot_link_present"]
    result["trustpilot_link_is_html_anchor"] = checks["trustpilot_link_is_html_anchor"]


def _all_content_checks_pass(checks: dict) -> bool:
    return all(checks.values())


def _build_updated_message(raw_recipient: str, first_name: str) -> EmailMessage:
    message = EmailMessage()
    message["To"] = raw_recipient
    message["From"] = GMAIL_SEND_FROM
    message["Subject"] = SUBJECT
    message.set_content(_plain_body(first_name))
    message.add_alternative(_html_body(first_name), subtype="html")
    return message


def _plain_body(first_name: str) -> str:
    return (
        f"Dear {first_name},\n\n"
        "Thank you for shopping with Kidstoylover. We hope everything arrived safely and that you are enjoying your order.\n\n"
        "If you have a moment, we would really appreciate it if you could share your experience with us on Trustpilot:\n\n"
        f"{TRUSTPILOT_LINK_TEXT}: {TRUSTPILOT_URL}\n\n"
        "Your feedback helps our small business improve and helps other RC hobby customers shop with confidence.\n\n"
        "Kind regards,\n"
        "Kidstoylover Team\n"
    )


def _html_body(first_name: str) -> str:
    safe_first_name = escape(first_name)
    return (
        "<html><body>"
        f"<p>Dear {safe_first_name},</p>"
        "<p>Thank you for shopping with Kidstoylover. We hope everything arrived safely and that you are enjoying your order.</p>"
        "<p>If you have a moment, we would really appreciate it if you could share your experience with us on Trustpilot:</p>"
        f'<p><a href="{TRUSTPILOT_URL}">{TRUSTPILOT_LINK_TEXT}</a></p>'
        "<p>Your feedback helps our small business improve and helps other RC hobby customers shop with confidence.</p>"
        "<p>Kind regards,<br>Kidstoylover Team</p>"
        "</body></html>"
    )


def _status_from_operation(base_conditions: list[dict], operation: dict) -> str:
    if base_conditions:
        return base_conditions[0]["status"]
    if operation["blocking_conditions"]:
        return operation["blocking_conditions"][0]["status"]
    return operation["draft_content_pre_send_status"]


def _build_payload(
    source_reports: dict,
    source_errors: dict,
    base_conditions: list[dict],
    operation: dict,
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary(operation)
    blocking_conditions = base_conditions + operation["blocking_conditions"]
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.16C",
        "mode": "draft-content-update-pre-send",
        "command_label": COMMAND_LABEL,
        "draft_content_pre_send_status": status,
        "success": status == READY_STATUS,
        "selected_order_name": EXPECTED_ORDER_NAME,
        "selected_masked_email": EXPECTED_MASKED_EMAIL,
        "source_gmail_draft_id_partial": EXPECTED_DRAFT_ID_PARTIAL,
        "source_real_run_readiness_status": _safe_text(source_reports["readiness"].get("real_run_readiness_status", "")),
        "source_executor_status": _safe_text(source_reports["executor"].get("one_draft_send_execute_status", "")),
        "source_final_preflight_status": _safe_text(source_reports["preflight"].get("final_preflight_status", "")),
        "source_locked_draft_status": _safe_text(source_reports["locked_draft"].get("one_draft_status", "")),
        "customer_first_name_detected": operation["customer_first_name_detected"],
        "first_name_output_suppressed": True,
        "greeting_uses_dear_first_name": operation["greeting_uses_dear_first_name"],
        "trustpilot_link_present": operation["trustpilot_link_present"],
        "trustpilot_link_is_html_anchor": operation["trustpilot_link_is_html_anchor"],
        "subject_matches_expected": operation["subject_matches_expected"],
        "expected_subject": SUBJECT,
        "expected_greeting_format": "Dear [first name],",
        "expected_trustpilot_link_text": TRUSTPILOT_LINK_TEXT,
        "expected_trustpilot_url": TRUSTPILOT_URL,
        "gmail_draft_get_attempted": operation["gmail_draft_get_attempted"],
        "gmail_draft_get_succeeded": operation["gmail_draft_get_succeeded"],
        "gmail_draft_update_needed": operation["gmail_draft_update_needed"],
        "gmail_draft_update_attempted": operation["gmail_draft_update_attempted"],
        "gmail_draft_updated": operation["gmail_draft_updated"],
        "draft_content_ready_after_update": operation["draft_content_ready_after_update"],
        "raw_email_report_storage_allowed": False,
        "raw_email_lookup_attempted": operation["raw_email_lookup_attempted"],
        "raw_email_available": operation["raw_email_available"],
        "raw_email_source": operation["raw_email_source"],
        "first_name_lookup_attempted": operation["first_name_lookup_attempted"],
        "first_name_available": operation["first_name_available"],
        "customer_profile_lookup_source": operation["customer_profile_lookup_source"],
        "successful_fallback_query_label": operation["successful_fallback_query_label"],
        "raw_email_lookup_error_sanitized": operation["raw_email_lookup_error_sanitized"],
        "source_reports_used": {
            "real_run_readiness_json_path": str(SOURCE_READINESS_JSON_PATH),
            "executor_json_path": str(SOURCE_EXECUTOR_JSON_PATH),
            "final_preflight_json_path": str(SOURCE_PREFLIGHT_JSON_PATH),
            "locked_draft_json_path": str(SOURCE_LOCKED_DRAFT_JSON_PATH),
            "source_errors_sanitized": {key: _sanitize_text(value) for key, value in source_errors.items()},
        },
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_gmail_draft_content_update_pre_send_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_draft_content_update_pre_send_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "privacy_assertion_passed": operation["privacy_assertion_passed"],
        "raw_email_leak_risk_detected": operation["raw_email_leak_risk_detected"],
        "safety_summary": safety,
        **safety,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary(operation: dict) -> dict:
    return {
        "gmail_api_call_performed": bool(operation["gmail_api_call_performed"]),
        "gmail_token_refresh_attempted": bool(operation["gmail_token_refresh_attempted"]),
        "gmail_token_refresh_succeeded": bool(operation["gmail_token_refresh_succeeded"]),
        "gmail_drafts_get_called": bool(operation["gmail_drafts_get_called"]),
        "gmail_drafts_update_called": bool(operation["gmail_drafts_update_called"]),
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": bool(operation["raw_email_lookup_shopify_api_call_performed"]),
        "read_only_shopify_customer_lookup_performed": bool(operation["raw_email_lookup_shopify_api_call_performed"]),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_draft_content_update_pre_send_path": str(json_path),
        "html_trustpilot_gmail_draft_content_update_pre_send_path": str(html_path),
        "draft_content_pre_send_status": payload["draft_content_pre_send_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "customer_first_name_detected": payload["customer_first_name_detected"],
        "greeting_uses_dear_first_name": payload["greeting_uses_dear_first_name"],
        "trustpilot_link_present": payload["trustpilot_link_present"],
        "trustpilot_link_is_html_anchor": payload["trustpilot_link_is_html_anchor"],
        "gmail_draft_update_attempted": payload["gmail_draft_update_attempted"],
        "gmail_draft_updated": payload["gmail_draft_updated"],
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
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Draft Content Pre-Send Check</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Gmail Draft Content Pre-Send Check</h1>
  <p class="warning">Phase 3.16C may inspect or update one existing Gmail draft only. No Gmail send, new draft creation, Shopify write, or Kudosi call was performed.</p>
  <p>Status: <strong>{escape(payload["draft_content_pre_send_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Expected greeting: <code>Dear [first name],</code></p>
  <p>Expected link: <a href="{TRUSTPILOT_URL}">{TRUSTPILOT_LINK_TEXT}</a></p>
  <p>Customer first name detected: <strong>{escape(str(payload["customer_first_name_detected"]))}</strong></p>
  <p>Greeting uses Dear + first name: <strong>{escape(str(payload["greeting_uses_dear_first_name"]))}</strong></p>
  <p>Trustpilot link is HTML anchor: <strong>{escape(str(payload["trustpilot_link_is_html_anchor"]))}</strong></p>
  <p>Draft update attempted: <strong>{escape(str(payload["gmail_draft_update_attempted"]))}</strong></p>
  <p>Draft updated: <strong>{escape(str(payload["gmail_draft_updated"]))}</strong></p>
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
    full_draft_leak = _full_draft_id_leak_risk(text)
    payload["full_draft_id_leak_risk_detected"] = full_draft_leak
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"] or full_draft_leak:
        payload["draft_content_pre_send_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["privacy_assertion_passed"] = False
        payload["raw_email_leak_risk_detected"] = bool(self_scan["raw_customer_email_count"])
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "pre-send content report self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
        payload["detected_issue_summary"] = _issue_summary(payload["draft_content_pre_send_status"], payload["blocking_conditions"])
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


def _full_draft_id_leak_risk(text: str) -> bool:
    return any("..." not in match.group(0) for match in FULL_DRAFT_ID_RE.finditer(text or ""))


def _safe_runtime_email(value: str) -> str:
    text = str(value or "").strip().lower()
    return text if EMAIL_RE.fullmatch(text) else ""


def _safe_first_name(value: str) -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z].*$", "", text)
    return text[:40]


def _safe_masked_email(value: str) -> str:
    text = _safe_text(value)
    if not text or "@" not in text:
        return ""
    if "***" in text:
        return text
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)


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


def _safe_text(value) -> str:
    return _sanitize_text(str(value or ""))


def _sanitize_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _issue_summary(status: str, blocking_conditions: list[dict]) -> str:
    if status == READY_STATUS:
        return "The existing Trustpilot Gmail draft content is ready for manual pre-send review; no send or Shopify tag write was performed."
    return "Trustpilot Gmail draft content pre-send check blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.16C Trustpilot Gmail draft content pre-send check finished.\n"
        f"Status: {payload.get('draft_content_pre_send_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Customer first name detected: {payload.get('customer_first_name_detected')}\n"
        f"Greeting uses Dear + first name: {payload.get('greeting_uses_dear_first_name')}\n"
        f"Trustpilot HTML anchor present: {payload.get('trustpilot_link_is_html_anchor')}\n"
        f"Draft update attempted: {payload.get('gmail_draft_update_attempted')}\n"
        f"Draft updated: {payload.get('gmail_draft_updated')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail send, no new draft, no Shopify tag write, no Kudosi call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
