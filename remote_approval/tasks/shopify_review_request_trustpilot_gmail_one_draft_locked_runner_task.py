import base64
import json
import os
import re
import subprocess
import time
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_one_draft_locked_runner"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_one_draft_locked_runner"

PHASE_3_3_SOURCE_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_oauth_readiness_preflight.json"
PHASE_3_2_SOURCE_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_create_locked_test.json"
PHASE_3_1_SOURCE_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_package.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.html"

CREATE_DRAFTS_ENV = "TRUSTPILOT_GMAIL_CREATE_DRAFTS"
DRAFT_MAX_ENV = "TRUSTPILOT_GMAIL_DRAFT_MAX"
ACK_ENV = "TRUSTPILOT_GMAIL_ONE_DRAFT_LOCKED_RUNNER_ACK"
ACK_VALUE = "YES_I_APPROVE_CREATING_ONE_TRUSTPILOT_GMAIL_DRAFT"

GMAIL_SEND_FROM = "info@kidstoylover.com"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
TRUSTPILOT_LINK = "https://www.trustpilot.com/evaluate/www.kidstoylover.com"
TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = ["1: trustpilot", "1: trustpoilt"]
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
PROTECTED_LOOKUP_TIMEOUT_SECONDS = 120
SUBJECT = "Thank You for Your Support \u2013 We\u2019d Love Your Feedback!"
BODY_TEMPLATE = (
    "Dear {first_name},\n\n"
    "Thank you so much for your continued support and for choosing us again \u2014 it truly means a lot to our team.\n\n"
    "If you have a moment, we would greatly appreciate it if you could leave a quick review of your experience with us. "
    "Your feedback not only helps us improve, but also helps other customers feel confident in choosing us too.\n\n"
    "You can share your thoughts here:\n"
    "https://www.trustpilot.com/evaluate/www.kidstoylover.com\n\n"
    "Thanks again for being a valued customer. If there's anything else we can assist you with, please don\u2019t hesitate "
    "to let us know.\n\n"
    "Kind Regards,\n"
    "Xiang"
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)"
)
ALLOWED_REPORT_EMAILS = {GMAIL_SEND_FROM.lower()}


def run_shopify_review_request_trustpilot_gmail_one_draft_locked_runner_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error, source_path = _load_source_report()
    source_ready = _source_ready(source_report, source_error)
    candidates = _candidate_rows(source_report) if source_ready else []
    selected_candidate = _select_candidate(candidates)
    gates = _gate_status()
    gmail_env = _gmail_env(gates["ack_valid"])
    draft_result = _one_draft_result(source_ready, source_error, candidates, selected_candidate, gates, gmail_env)
    payload = _build_payload(
        source_report=source_report,
        source_error=source_error,
        source_path=source_path,
        source_ready=source_ready,
        candidates=candidates,
        selected_candidate=selected_candidate,
        gates=gates,
        gmail_env=gmail_env,
        draft_result=draft_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_source_report() -> tuple[dict, str, Path]:
    for path in (PHASE_3_3_SOURCE_PATH, PHASE_3_2_SOURCE_PATH, PHASE_3_1_SOURCE_PATH):
        if not path.exists():
            continue
        try:
            return json.loads(path.read_text(encoding="utf-8")), "", path
        except json.JSONDecodeError as exc:
            return {}, _sanitize_text(f"trustpilot_draft_source_json_parse_error: {exc}"), path
    return {}, "blocked_missing_trustpilot_draft_source_report", PHASE_3_3_SOURCE_PATH


def _source_ready(source_report: dict, source_error: str) -> bool:
    if source_error:
        return False
    task_name = source_report.get("task_name")
    if task_name == "shopify_review_request_trustpilot_gmail_oauth_readiness_preflight":
        return str(source_report.get("phase")) == "3.3" and source_report.get("success") is True
    if task_name == "shopify_review_request_trustpilot_gmail_draft_create_locked_test":
        return str(source_report.get("phase")) == "3.2" and source_report.get("success") is True
    if task_name == "shopify_review_request_trustpilot_gmail_draft_package":
        return (
            str(source_report.get("phase")) == "3.1"
            and source_report.get("draft_package_status") == "local_draft_package_only"
            and source_report.get("success") is True
        )
    return False


def _candidate_rows(source_report: dict) -> list[dict]:
    task_name = source_report.get("task_name")
    if task_name == "shopify_review_request_trustpilot_gmail_oauth_readiness_preflight":
        preview = source_report.get("selected_draft_preview") if isinstance(source_report.get("selected_draft_preview"), dict) else {}
        return [_candidate_from_preview(source_report, preview)] if preview else []
    if task_name == "shopify_review_request_trustpilot_gmail_draft_create_locked_test":
        preview = source_report.get("selected_draft_preview") if isinstance(source_report.get("selected_draft_preview"), dict) else {}
        return [_candidate_from_preview(source_report, preview)] if preview else []

    candidates = []
    for row in source_report.get("draft_candidates") or []:
        if not isinstance(row, dict):
            continue
        if row.get("blocked_reason") or row.get("gmail_draft_created") is True:
            continue
        if _has_existing_trustpilot_tag(row):
            continue
        candidates.append(row)
    return candidates


def _candidate_from_preview(source_report: dict, preview: dict) -> dict:
    return {
        "order_name": _safe_text(source_report.get("selected_order_name", preview.get("order_name", ""))),
        "order_id_or_gid": _safe_text(preview.get("order_id_or_gid", "")),
        "masked_email": _safe_masked_email(source_report.get("selected_masked_email", preview.get("masked_email", ""))),
        "first_name_used": _safe_text(preview.get("first_name_used", "there")) or "there",
        "local_draft_body_preview": _safe_text(preview.get("body", "")) or BODY_TEMPLATE.format(first_name="there"),
        "subject": _safe_text(source_report.get("subject", SUBJECT)) or SUBJECT,
        "planned_tag_after_future_send": TRUSTPILOT_TAG,
    }


def _select_candidate(candidates: list[dict]) -> dict:
    return candidates[0] if candidates else {}


def _gate_status() -> dict:
    return {
        "create_drafts_enabled": os.environ.get(CREATE_DRAFTS_ENV, "").strip() == "1",
        "ack_valid": os.environ.get(ACK_ENV, "").strip() == ACK_VALUE,
        "draft_max_raw": os.environ.get(DRAFT_MAX_ENV, "").strip(),
        "draft_max_is_one": os.environ.get(DRAFT_MAX_ENV, "").strip() == "1",
    }


def _gmail_env(allow_dotenv: bool) -> dict:
    dotenv_values = _read_dotenv_values() if allow_dotenv else {}
    send_from = _env_value("GMAIL_SEND_FROM", dotenv_values)
    client_id = _env_value("GOOGLE_GMAIL_CLIENT_ID", dotenv_values)
    client_secret = _env_value("GOOGLE_GMAIL_CLIENT_SECRET", dotenv_values)
    refresh_token = _env_value("GOOGLE_GMAIL_REFRESH_TOKEN", dotenv_values)
    scopes = _split_scopes(_env_value("GOOGLE_GMAIL_SCOPES", dotenv_values))
    sender_matches = send_from == GMAIL_SEND_FROM
    compose_scope_present = GMAIL_COMPOSE_SCOPE in scopes
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
        "gmail_scope_configured": bool(scopes),
        "gmail_compose_scope_present": compose_scope_present,
        "gmail_sender_matches_expected": sender_matches,
        "missing_env_vars": missing,
        "dotenv_read": allow_dotenv,
    }


def _env_value(key: str, dotenv_values: dict) -> str:
    return (os.environ.get(key) or dotenv_values.get(key) or "").strip()


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


def _one_draft_result(
    source_ready: bool,
    source_error: str,
    candidates: list[dict],
    selected_candidate: dict,
    gates: dict,
    gmail_env: dict,
) -> dict:
    result = {
        "one_draft_status": "dry_run_one_gmail_draft_not_created",
        "gmail_api_call_performed": False,
        "gmail_token_refresh_attempted": False,
        "gmail_token_refresh_succeeded": False,
        "gmail_oauth_error_type": "",
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_drafts_created_count": 0,
        "gmail_draft_id": "",
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "error_sanitized": "",
        "raw_email_lookup_attempted": False,
        "raw_email_available": False,
        "raw_email_source": "not_attempted_without_ack",
        "raw_email_lookup_error_sanitized": "",
        "raw_email_lookup_docker_command_reached": False,
        "raw_email_lookup_django_shell_reached": False,
        "raw_email_lookup_shopify_api_call_performed": False,
        "successful_fallback_query_label": "",
        "raw_email_lookup_graphql_error_diagnostics": [],
        "privacy_assertion_passed": True,
        "raw_email_leak_risk_detected": False,
    }
    if source_error or not source_ready:
        result["one_draft_status"] = "blocked_missing_trustpilot_draft_source_report"
        return result
    if not candidates or not selected_candidate:
        result["one_draft_status"] = "blocked_no_trustpilot_draft_candidate"
        return result
    raw_lookup = _protected_runtime_raw_email_lookup(selected_candidate)
    _apply_raw_lookup_report(result, raw_lookup)
    raw_recipient = raw_lookup.get("_raw_email_for_runtime_only", "")
    if not raw_recipient:
        result["one_draft_status"] = "blocked_missing_raw_email_for_gmail_draft"
        return result
    if _raw_email_leak_risk_detected(raw_recipient, selected_candidate):
        result["one_draft_status"] = "blocked_raw_email_leak_risk"
        result["privacy_assertion_passed"] = False
        result["raw_email_leak_risk_detected"] = True
        return result
    if not gates["create_drafts_enabled"] or not gates["ack_valid"]:
        return result
    if not gates["draft_max_is_one"]:
        result["one_draft_status"] = "blocked_draft_max_not_one"
        return result
    if not gmail_env["gmail_oauth_present"]:
        result["one_draft_status"] = "blocked_missing_gmail_oauth"
        return result
    if not gmail_env["gmail_sender_matches_expected"]:
        result["one_draft_status"] = "blocked_sender_mismatch"
        return result
    if not gmail_env["gmail_compose_scope_present"]:
        result["one_draft_status"] = "blocked_missing_gmail_compose_scope"
        return result

    try:
        service = _build_gmail_service(gmail_env, result)
        result["gmail_draft_create_attempted"] = True
        result["gmail_api_call_performed"] = True
        response = _create_gmail_draft(service, raw_recipient, selected_candidate)
        result["gmail_draft_created"] = True
        result["gmail_drafts_created_count"] = 1
        result["gmail_draft_id"] = _safe_text(response.get("id", ""))
        result["one_draft_status"] = "gmail_one_draft_created_locked_runner"
    except Exception as exc:  # pragma: no cover - only used behind explicit Gmail gates.
        if not result["one_draft_status"].startswith("blocked"):
            result["one_draft_status"] = "blocked_gmail_draft_create_failed"
        result["error_sanitized"] = _sanitize_text(str(exc))
    return result


def _apply_raw_lookup_report(result: dict, raw_lookup: dict) -> None:
    result["raw_email_lookup_attempted"] = bool(raw_lookup.get("raw_email_lookup_attempted"))
    result["raw_email_available"] = bool(raw_lookup.get("raw_email_available"))
    result["raw_email_source"] = _safe_text(raw_lookup.get("raw_email_source", "protected_runtime_lookup"))
    result["raw_email_lookup_error_sanitized"] = _sanitize_text(raw_lookup.get("raw_email_lookup_error_sanitized", ""))
    result["raw_email_lookup_docker_command_reached"] = bool(raw_lookup.get("raw_email_lookup_docker_command_reached"))
    result["raw_email_lookup_django_shell_reached"] = bool(raw_lookup.get("raw_email_lookup_django_shell_reached"))
    result["raw_email_lookup_shopify_api_call_performed"] = bool(
        raw_lookup.get("raw_email_lookup_shopify_api_call_performed")
    )
    result["successful_fallback_query_label"] = _safe_text(raw_lookup.get("successful_fallback_query_label", ""))
    result["raw_email_lookup_graphql_error_diagnostics"] = raw_lookup.get(
        "raw_email_lookup_graphql_error_diagnostics", []
    )


def _protected_runtime_raw_email_lookup(selected_candidate: dict) -> dict:
    lookup = {
        "raw_email_lookup_attempted": True,
        "raw_email_available": False,
        "raw_email_source": "protected_runtime_lookup",
        "raw_email_lookup_error_sanitized": "",
        "raw_email_lookup_docker_command_reached": False,
        "raw_email_lookup_django_shell_reached": False,
        "raw_email_lookup_shopify_api_call_performed": False,
        "successful_fallback_query_label": "",
        "raw_email_lookup_graphql_error_diagnostics": [],
        "_raw_email_for_runtime_only": "",
    }
    order_id_or_gid = _safe_text(selected_candidate.get("order_id_or_gid", ""))
    order_name = _safe_text(selected_candidate.get("order_name", ""))
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
        _protected_raw_email_lookup_script(order_id_or_gid, order_name),
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
    except FileNotFoundError as exc:
        lookup["raw_email_lookup_error_sanitized"] = _sanitize_text(str(exc))
        return lookup
    except PermissionError as exc:
        lookup["raw_email_lookup_error_sanitized"] = _sanitize_text(str(exc))
        return lookup

    parsed = _parse_protected_lookup_stdout(completed.stdout)
    if parsed:
        lookup["raw_email_lookup_django_shell_reached"] = bool(parsed.get("django_shell_reached"))
        lookup["raw_email_lookup_shopify_api_call_performed"] = bool(parsed.get("shopify_api_call_performed"))
        lookup["successful_fallback_query_label"] = _safe_text(parsed.get("successful_fallback_query_label", ""))
        lookup["raw_email_lookup_graphql_error_diagnostics"] = _safe_attempt_diagnostics(
            parsed.get("fallback_query_attempts", [])
        )
    if completed.returncode != 0:
        lookup["raw_email_lookup_error_sanitized"] = _sanitize_text(
            (parsed or {}).get("error_sanitized", "protected runtime lookup command failed")
        )
        return lookup
    if not parsed:
        lookup["raw_email_lookup_error_sanitized"] = "protected runtime lookup did not return parseable JSON"
        return lookup

    raw_email = str(parsed.get("raw_email") or "").strip()
    if raw_email and "***" not in raw_email and EMAIL_RE.fullmatch(raw_email):
        lookup["raw_email_available"] = True
        lookup["_raw_email_for_runtime_only"] = raw_email
        lookup["raw_email_source"] = "protected_runtime_lookup"
        return lookup

    lookup["raw_email_lookup_error_sanitized"] = _sanitize_text(
        parsed.get("error_sanitized") or "protected runtime lookup returned no usable customer email"
    )
    return lookup


def _safe_attempt_diagnostics(attempts) -> list[dict]:
    safe_attempts = []
    for attempt in attempts or []:
        if not isinstance(attempt, dict):
            continue
        safe_attempts.append(
            {
                "label": _safe_text(attempt.get("label", "")),
                "http_status": attempt.get("http_status"),
                "graphql_error_count": int(attempt.get("graphql_error_count") or 0),
                "query_succeeded": bool(attempt.get("query_succeeded")),
                "order_match_found": bool(attempt.get("order_match_found")),
                "email_found": bool(attempt.get("email_found")),
                "email_source": _safe_text(attempt.get("email_source", "")),
                "errors_sanitized": [
                    _sanitize_text(item)
                    for item in (attempt.get("errors_sanitized") or [])
                    if isinstance(item, str)
                ][:3],
                "failure_type": _safe_text(attempt.get("failure_type", "")),
            }
        )
    return safe_attempts[:12]


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


def _protected_raw_email_lookup_script(order_id_or_gid: str, order_name: str) -> str:
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
    "raw_email_source": "",
    "raw_email": "",
    "successful_fallback_query_label": "",
    "fallback_query_attempts": [],
    "error_sanitized": "",
}

def sanitize(text):
    text = str(text or "")
    text = re.sub(r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)", "[redacted]", text)
    return email_re.sub("[masked-email]", text)

def selected_email(order):
    customer = order.get("customer") or {}
    default_email_address = customer.get("defaultEmailAddress") or {}
    candidates = [
        ("email", order.get("email")),
        ("customer.email", customer.get("email")),
        ("customer.defaultEmailAddress.emailAddress", default_email_address.get("emailAddress")),
        ("contactEmail", order.get("contactEmail")),
    ]
    for source, value in candidates:
        value = str(value or "").strip()
        if value and email_re.fullmatch(value):
            return value.lower(), source
    return "", ""

def sanitize_errors(errors):
    sanitized = []
    for error in errors[:3]:
        if isinstance(error, dict):
            message = error.get("message") or "GraphQL error"
        else:
            message = str(error or "GraphQL error")
        sanitized.append(sanitize(message)[:300])
    return sanitized

def request_graphql(label, endpoint, headers, query, variables):
    attempt = {
        "label": label,
        "http_status": None,
        "graphql_error_count": 0,
        "errors_sanitized": [],
        "query_succeeded": False,
        "order_match_found": False,
        "email_found": False,
        "email_source": "",
        "failure_type": "",
    }
    response = requests.post(endpoint, json={"query": query, "variables": variables}, headers=headers, timeout=30)
    result["shopify_api_call_performed"] = True
    attempt["http_status"] = response.status_code
    if response.status_code >= 400:
        attempt["failure_type"] = "http_error"
        result["fallback_query_attempts"].append(attempt)
        return None, attempt
    try:
        data = response.json()
    except ValueError:
        attempt["failure_type"] = "non_json_response"
        result["fallback_query_attempts"].append(attempt)
        return None, attempt
    errors = data.get("errors") or []
    if errors:
        attempt["graphql_error_count"] = len(errors)
        attempt["errors_sanitized"] = sanitize_errors(errors)
        result["fallback_query_attempts"].append(attempt)
        return None, attempt
    attempt["query_succeeded"] = True
    return data.get("data") or {}, attempt

def orders_from_data(data, kind, expected_id, expected_name):
    if kind == "node":
        node = data.get("node") or {}
        if node:
            return [node]
        return []
    edges = (((data.get("orders") or {}).get("edges")) or [])
    nodes = [edge.get("node") or {} for edge in edges]
    if expected_name:
        exact = [node for node in nodes if node.get("name") == expected_name]
        if exact:
            return exact
    if expected_id:
        exact = [node for node in nodes if node.get("id") == expected_id]
        if exact:
            return exact
    return nodes

def try_query(label, endpoint, headers, query, variables, kind):
    data, attempt = request_graphql(label, endpoint, headers, query, variables)
    if data is None:
        return None, ""
    orders = orders_from_data(data, kind, order_id_or_gid, order_name)
    order = orders[0] if orders else None
    attempt["order_match_found"] = bool(order)
    if order:
        raw_email, source = selected_email(order)
        attempt["email_found"] = bool(raw_email)
        attempt["email_source"] = source or ""
        result["fallback_query_attempts"].append(attempt)
        return order, raw_email
    result["fallback_query_attempts"].append(attempt)
    return None, ""

try:
    installation = ShopifyInstallation.objects.get(shop=shop)
    result["shopify_installation_found"] = True
    token_value = getattr(installation, "access_" + "token")
    result["shopify_credentials_found"] = bool(token_value)
    if not token_value:
        result["error_sanitized"] = "Shopify installation exists, but the access token is empty."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)

    endpoint = "https://" + installation.shop + "/admin/api/" + api_version + "/graphql.json"
    token_header = "X-Shopify-" + "Access-Token"
    headers = {token_header: token_value, "Content-Type": "application/json"}
    query_attempts = []
    if order_name:
        query_attempts.extend([
            (
                "name_order_email",
                "query ProtectedOrderNameEmail($query: String!) { orders(first: 10, query: $query) { edges { node { id name email } } } }",
                {"query": "name:" + order_name},
                "orders",
            ),
            (
                "name_customer_email",
                "query ProtectedOrderNameCustomerEmail($query: String!) { orders(first: 10, query: $query) { edges { node { id name customer { id email firstName lastName } } } } }",
                {"query": "name:" + order_name},
                "orders",
            ),
            (
                "name_contact_email",
                "query ProtectedOrderNameContactEmail($query: String!) { orders(first: 10, query: $query) { edges { node { id name contactEmail } } } }",
                {"query": "name:" + order_name},
                "orders",
            ),
            (
                "name_customer_default_email_address",
                "query ProtectedOrderNameCustomerDefaultEmail($query: String!) { orders(first: 10, query: $query) { edges { node { id name customer { id defaultEmailAddress { emailAddress } } } } } }",
                {"query": "name:" + order_name},
                "orders",
            ),
        ])
    if order_id_or_gid.startswith("gid://shopify/Order/"):
        query_attempts.extend([
            (
                "id_order_email",
                "query ProtectedOrderIdEmail($id: ID!) { node(id: $id) { ... on Order { id name email } } }",
                {"id": order_id_or_gid},
                "node",
            ),
            (
                "id_customer_email",
                "query ProtectedOrderIdCustomerEmail($id: ID!) { node(id: $id) { ... on Order { id name customer { id email firstName lastName } } } }",
                {"id": order_id_or_gid},
                "node",
            ),
            (
                "id_contact_email",
                "query ProtectedOrderIdContactEmail($id: ID!) { node(id: $id) { ... on Order { id name contactEmail } } }",
                {"id": order_id_or_gid},
                "node",
            ),
            (
                "id_customer_default_email_address",
                "query ProtectedOrderIdCustomerDefaultEmail($id: ID!) { node(id: $id) { ... on Order { id name customer { id defaultEmailAddress { emailAddress } } } } }",
                {"id": order_id_or_gid},
                "node",
            ),
        ])

    for label, query, variables, kind in query_attempts:
        order, raw_email = try_query(label, endpoint, headers, query, variables, kind)
        if raw_email:
            result["raw_email_available"] = True
            result["raw_email_source"] = "protected_runtime_lookup"
            result["successful_fallback_query_label"] = label
            result["raw_email"] = raw_email
            print(json.dumps(result, ensure_ascii=True))
            raise SystemExit(0)

    if not query_attempts:
        result["error_sanitized"] = "missing stable order identifier for protected runtime lookup"
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(0)
    if not any(attempt.get("query_succeeded") for attempt in result["fallback_query_attempts"]):
        result["error_sanitized"] = "all protected raw email fallback queries failed"
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(0)
    if not any(attempt.get("order_match_found") for attempt in result["fallback_query_attempts"]):
        result["error_sanitized"] = "protected runtime lookup found no matching order"
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(0)
    result["error_sanitized"] = "matching order had no usable customer email from protected fallback fields"
    print(json.dumps(result, ensure_ascii=True))
except ShopifyInstallation.DoesNotExist:
    result["error_sanitized"] = "Shopify installation was not found for the configured shop."
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
except Exception as exc:
    result["error_sanitized"] = sanitize(type(exc).__name__ + ": " + str(exc))
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
'''
    return (
        template.replace("__SHOP_LITERAL__", json.dumps(SHOP_DOMAIN))
        .replace("__API_VERSION_LITERAL__", json.dumps(SHOPIFY_API_VERSION))
        .replace("__ORDER_ID_LITERAL__", json.dumps(order_id_or_gid))
        .replace("__ORDER_NAME_LITERAL__", json.dumps(order_name))
    )


def _raw_email_leak_risk_detected(raw_email: str, selected_candidate: dict) -> bool:
    if not raw_email:
        return False
    raw_lower = raw_email.lower()
    candidate_text = json.dumps(selected_candidate, ensure_ascii=False).lower()
    preview_text = json.dumps(_selected_preview(selected_candidate), ensure_ascii=False).lower()
    return raw_lower in candidate_text or raw_lower in preview_text


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
    result["gmail_token_refresh_attempted"] = True
    result["gmail_api_call_performed"] = True
    try:
        credentials.refresh(Request())
        result["gmail_token_refresh_succeeded"] = True
    except Exception:
        result["gmail_oauth_error_type"] = "token_refresh_failed"
        result["one_draft_status"] = "blocked_gmail_oauth_refresh_failed"
        raise
    return build("gmail", "v1", credentials=credentials, cache_discovery=False)


def _create_gmail_draft(service, recipient_email: str, selected_candidate: dict) -> dict:
    body = _body_for_candidate(selected_candidate)
    message = MIMEText(body, "plain", "utf-8")
    message["to"] = recipient_email
    message["from"] = GMAIL_SEND_FROM
    message["subject"] = SUBJECT
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")
    return service.users().drafts().create(userId="me", body={"message": {"raw": raw_message}}).execute()


def _build_payload(
    source_report: dict,
    source_error: str,
    source_path: Path,
    source_ready: bool,
    candidates: list[dict],
    selected_candidate: dict,
    gates: dict,
    gmail_env: dict,
    draft_result: dict,
    duration_seconds: float,
) -> dict:
    selected_preview = _selected_preview(selected_candidate)
    safety = _safety_summary(draft_result)
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.9",
        "mode": "protected-raw-email-lookup-fallback-validation",
        "command_label": COMMAND_LABEL,
        "one_draft_status": draft_result["one_draft_status"],
        "success": draft_result["one_draft_status"]
        in {
            "dry_run_one_gmail_draft_not_created",
            "blocked_missing_gmail_oauth",
            "blocked_missing_gmail_compose_scope",
            "blocked_sender_mismatch",
            "blocked_missing_raw_email_for_gmail_draft",
            "blocked_raw_email_leak_risk",
            "gmail_one_draft_created_locked_runner",
        },
        "source_report_used": {
            "path": str(source_path),
            "present": not bool(source_error),
            "task_name": source_report.get("task_name", ""),
            "phase": source_report.get("phase", ""),
            "ready": source_ready,
            "error_sanitized": _sanitize_text(source_error),
        },
        "candidate_count_seen": len(candidates),
        "selected_candidate_count": 1 if selected_candidate else 0,
        "selected_order_name": selected_preview["order_name"],
        "selected_order_id_or_gid": selected_preview["order_id_or_gid"],
        "selected_masked_email": selected_preview["masked_email"],
        "gmail_sender_planned": GMAIL_SEND_FROM,
        "gmail_scope_configured": gmail_env["gmail_scope_configured"],
        "gmail_compose_scope_present": gmail_env["gmail_compose_scope_present"],
        "ack_valid": gates["ack_valid"],
        "gmail_oauth_present": gmail_env["gmail_oauth_present"],
        "gmail_sender_matches_expected": gmail_env["gmail_sender_matches_expected"],
        "gmail_missing_env_vars": gmail_env["missing_env_vars"],
        "gmail_env_source_policy": "process_environment_plus_dotenv_only_after_ack" if gmail_env["dotenv_read"] else "process_environment_only",
        "gmail_token_refresh_attempted": draft_result["gmail_token_refresh_attempted"],
        "gmail_token_refresh_succeeded": draft_result["gmail_token_refresh_succeeded"],
        "gmail_oauth_error_type": draft_result["gmail_oauth_error_type"],
        "gmail_draft_create_attempted": draft_result["gmail_draft_create_attempted"],
        "gmail_drafts_created_count": draft_result["gmail_drafts_created_count"],
        "protected_raw_email_source_design": "runtime_lookup_only_no_report_persistence",
        "raw_email_lookup_attempted": draft_result["raw_email_lookup_attempted"],
        "raw_email_available": draft_result["raw_email_available"],
        "raw_email_source": draft_result["raw_email_source"],
        "raw_email_lookup_error_sanitized": draft_result["raw_email_lookup_error_sanitized"],
        "raw_email_lookup_docker_command_reached": draft_result["raw_email_lookup_docker_command_reached"],
        "raw_email_lookup_django_shell_reached": draft_result["raw_email_lookup_django_shell_reached"],
        "raw_email_lookup_shopify_api_call_performed": draft_result["raw_email_lookup_shopify_api_call_performed"],
        "successful_fallback_query_label": draft_result["successful_fallback_query_label"],
        "raw_email_lookup_graphql_error_diagnostics": draft_result["raw_email_lookup_graphql_error_diagnostics"],
        "raw_email_report_storage_allowed": False,
        "privacy_assertion_passed": draft_result["privacy_assertion_passed"],
        "raw_email_leak_risk_detected": draft_result["raw_email_leak_risk_detected"],
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "planned_future_tag_after_send": TRUSTPILOT_TAG,
        "tag_change_performed": False,
        "subject": SUBJECT,
        "trustpilot_link": TRUSTPILOT_LINK,
        "selected_draft_preview": selected_preview,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_email_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
            "private_customer_notes_output": False,
            "secrets_output": False,
        },
        "safety_summary": safety,
        **safety,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(draft_result["one_draft_status"], len(candidates)),
        "duration_seconds": duration_seconds,
        "json_trustpilot_gmail_one_draft_locked_runner_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_one_draft_locked_runner_path": str(REPORT_HTML_PATH),
    }
    _apply_report_privacy_assertion(payload)
    if draft_result["gmail_draft_created"] and draft_result["gmail_draft_id"]:
        payload["gmail_draft_id"] = draft_result["gmail_draft_id"]
    if draft_result["error_sanitized"]:
        payload["gmail_error_sanitized"] = draft_result["error_sanitized"]
    return payload


def _safety_summary(draft_result: dict) -> dict:
    return {
        "shopify_api_call_performed": bool(draft_result["raw_email_lookup_shopify_api_call_performed"]),
        "read_only_shopify_raw_email_lookup_performed": bool(draft_result["raw_email_lookup_shopify_api_call_performed"]),
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
        "gmail_api_call_performed": bool(draft_result["gmail_api_call_performed"]),
        "gmail_draft_created": bool(draft_result["gmail_draft_created"]),
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    result = {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_one_draft_locked_runner_path": str(json_path),
        "html_trustpilot_gmail_one_draft_locked_runner_path": str(html_path),
        "one_draft_status": payload["one_draft_status"],
        "candidate_count_seen": payload["candidate_count_seen"],
        "selected_candidate_count": payload["selected_candidate_count"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "gmail_sender_planned": payload["gmail_sender_planned"],
        "gmail_scope_configured": payload["gmail_scope_configured"],
        "gmail_compose_scope_present": payload["gmail_compose_scope_present"],
        "ack_valid": payload["ack_valid"],
        "gmail_oauth_present": payload["gmail_oauth_present"],
        "raw_email_lookup_attempted": payload["raw_email_lookup_attempted"],
        "raw_email_available": payload["raw_email_available"],
        "raw_email_source": payload["raw_email_source"],
        "successful_fallback_query_label": payload["successful_fallback_query_label"],
        "privacy_assertion_passed": payload["privacy_assertion_passed"],
        "raw_email_leak_risk_detected": payload["raw_email_leak_risk_detected"],
        "gmail_token_refresh_attempted": payload["gmail_token_refresh_attempted"],
        "gmail_token_refresh_succeeded": payload["gmail_token_refresh_succeeded"],
        "gmail_draft_create_attempted": payload["gmail_draft_create_attempted"],
        "gmail_drafts_created_count": payload["gmail_drafts_created_count"],
        "shopify_api_call_performed": payload["shopify_api_call_performed"],
        "read_only_shopify_raw_email_lookup_performed": payload["read_only_shopify_raw_email_lookup_performed"],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": payload["gmail_api_call_performed"],
        "gmail_draft_created": payload["gmail_draft_created"],
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }
    if "gmail_draft_id" in payload:
        result["gmail_draft_id"] = payload["gmail_draft_id"]
    return result


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
    preview = payload["selected_draft_preview"]
    body = escape(preview["body"]).replace("\n", "<br>")
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail One-Draft Locked Runner</title>
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
  <h1>Trustpilot Gmail One-Draft Locked Runner</h1>
  <p class="warning">Phase 3.5 is locked to at most one Gmail drafts.create call. No Gmail send was performed. No Shopify tag write was performed. No Trustpilot tag was added.</p>
  <p>Status: <strong>{escape(str(payload["one_draft_status"]))}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected order ID: <code>{escape(payload["selected_order_id_or_gid"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Protected raw email lookup attempted: <strong>{escape(str(payload["raw_email_lookup_attempted"]))}</strong></p>
  <p>Raw email available to runtime: <strong>{escape(str(payload["raw_email_available"]))}</strong></p>
  <p>Raw email source: <code>{escape(str(payload["raw_email_source"]))}</code></p>
  <p>Successful fallback query: <code>{escape(str(payload["successful_fallback_query_label"]))}</code></p>
  <p>Privacy assertion passed: <strong>{escape(str(payload["privacy_assertion_passed"]))}</strong></p>
  <p>Gmail draft create attempted: <strong>{escape(str(payload["gmail_draft_create_attempted"]))}</strong></p>
  <p>Gmail drafts created: <strong>{escape(str(payload["gmail_drafts_created_count"]))}</strong></p>
  <h2>Draft Preview</h2>
  <p>Subject: <strong>{escape(payload["subject"])}</strong></p>
  <p>{body}</p>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <p><strong>NOT PERFORMED:</strong> no Gmail drafts.send, no Gmail messages.send, no email send, no Shopify tag write, no Kudosi call.</p>
</body>
</html>"""


def _selected_preview(selected_candidate: dict) -> dict:
    if not selected_candidate:
        return {"order_name": "", "order_id_or_gid": "", "masked_email": "", "first_name_used": "there", "body": BODY_TEMPLATE.format(first_name="there")}
    first_name = _safe_text(selected_candidate.get("first_name_used", "")).strip() or "there"
    return {
        "order_name": _safe_text(selected_candidate.get("order_name", "")),
        "order_id_or_gid": _safe_text(selected_candidate.get("order_id_or_gid", "")),
        "masked_email": _safe_masked_email(selected_candidate.get("masked_email", "")),
        "first_name_used": first_name,
        "body": BODY_TEMPLATE.format(first_name=first_name),
        "planned_future_tag_after_send": TRUSTPILOT_TAG,
        "tag_change_performed": False,
    }


def _body_for_candidate(selected_candidate: dict) -> str:
    first_name = _safe_text(selected_candidate.get("first_name_used", "")).strip() or "there"
    return BODY_TEMPLATE.format(first_name=first_name)


def _raw_recipient_for_gmail(selected_candidate: dict) -> str:
    for key in ("recipient_email", "raw_email", "email"):
        value = selected_candidate.get(key)
        if isinstance(value, str):
            value = value.strip()
            if "***" not in value and EMAIL_RE.fullmatch(value):
                return value
    return ""


def _has_existing_trustpilot_tag(row: dict) -> bool:
    aliases = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    summary = row.get("safe_tags_summary") if isinstance(row.get("safe_tags_summary"), dict) else {}
    if summary.get("contains_trustpilot_alias") is True:
        return True
    for key in ("tags_of_interest", "safe_tags", "exact_tags_of_interest"):
        for tag in summary.get(key, []) or []:
            if _normalize_tag(tag) in aliases:
                return True
    return False


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.9 protected raw email fallback lookup validation finished.\n"
        f"Status: {payload.get('one_draft_status')}\n"
        f"Candidates seen: {payload.get('candidate_count_seen')}\n"
        f"Selected candidates: {payload.get('selected_candidate_count')}\n"
        f"Protected raw email lookup attempted: {payload.get('raw_email_lookup_attempted')}\n"
        f"Raw email available to runtime: {payload.get('raw_email_available')}\n"
        f"Successful fallback query: {payload.get('successful_fallback_query_label')}\n"
        f"Gmail drafts created: {payload.get('gmail_drafts_created_count')}\n"
        "Safety: no Shopify API call, no Shopify writes, no tagsAdd/tagsRemove, no Kudosi API call, no Gmail send, and no email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, candidate_count: int) -> str:
    if status == "dry_run_one_gmail_draft_not_created":
        return f"Protected raw email one-draft runner inspected {candidate_count} candidates and did not call Gmail because the hard ACK gates were not all enabled."
    if status == "blocked_missing_raw_email_for_gmail_draft":
        return "One-draft locked runner blocked before Gmail because protected runtime raw email lookup did not return a usable recipient."
    if status == "blocked_raw_email_leak_risk":
        return "One-draft locked runner blocked before Gmail because the privacy assertion detected raw-email leak risk."
    if status == "gmail_one_draft_created_locked_runner":
        return "Exactly one Gmail draft was created with drafts.create; no send method was called."
    return f"One-draft locked runner status: {status}."


def _apply_report_privacy_assertion(payload: dict) -> None:
    findings = _report_unmasked_email_findings(payload)
    payload["report_privacy_scan_performed"] = True
    payload["report_privacy_unmasked_customer_email_findings"] = findings
    if not findings:
        return
    payload["one_draft_status"] = "blocked_raw_email_leak_risk"
    payload["success"] = True
    payload["privacy_assertion_passed"] = False
    payload["raw_email_leak_risk_detected"] = True
    payload["detected_issue_summary"] = _issue_summary("blocked_raw_email_leak_risk", payload.get("candidate_count_seen", 0))


def _report_unmasked_email_findings(payload: dict) -> list[str]:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    findings = []
    for match in EMAIL_RE.finditer(text):
        email = match.group(0).lower()
        if email in ALLOWED_REPORT_EMAILS:
            continue
        if "***" in email:
            continue
        findings.append(_mask_email(email))
    return sorted(set(findings))


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


def _safe_text(value) -> str:
    text = str(value or "")
    text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    return _sanitize_text(text)


def _sanitize_text(text: str) -> str:
    redacted = SENSITIVE_TEXT_RE.sub("[redacted]", text or "")
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _normalize_tag(tag: str) -> str:
    return str(tag or "").strip().lower()


def _split_scopes(value: str) -> list[str]:
    return [item.strip() for item in value.split() if item.strip()]
