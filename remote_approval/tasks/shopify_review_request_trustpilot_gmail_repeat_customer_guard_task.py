import json
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_repeat_customer_guard"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_repeat_customer_guard"

SOURCE_PRE_SEND_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send.json"
SOURCE_READINESS_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness.json"
SOURCE_PREFLIGHT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_repeat_customer_guard.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_repeat_customer_guard.html"

PASS_STATUS = "repeat_customer_guard_passed"
EXPECTED_PRE_SEND_STATUS = "trustpilot_gmail_draft_content_ready_for_send"
EXPECTED_READINESS_STATUS = "trustpilot_gmail_one_draft_real_send_ready_for_manual_execution"
EXPECTED_PREFLIGHT_STATUS = "trustpilot_gmail_one_draft_send_final_preflight_ready"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
PROTECTED_LOOKUP_TIMEOUT_SECONDS = 120
ALLOWED_REPORT_EMAILS = {"info@kidstoylover.com"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"shpat_[A-Za-z0-9_]+"),
    re.compile(r"(?i)access[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)refresh[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)client[_\s-]?secret\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
]


def run_shopify_review_request_trustpilot_gmail_repeat_customer_guard_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    pre_send_report, pre_send_error = _read_json_report(SOURCE_PRE_SEND_JSON_PATH, "blocked_missing_pre_send_report")
    readiness_report, readiness_error = _read_json_report(SOURCE_READINESS_JSON_PATH, "blocked_missing_real_run_readiness_report")
    preflight_report, preflight_error = _read_json_report(SOURCE_PREFLIGHT_JSON_PATH, "blocked_missing_final_preflight_report")
    source_reports = {
        "pre_send": pre_send_report,
        "readiness": readiness_report,
        "preflight": preflight_report,
    }
    source_errors = {
        "pre_send": pre_send_error,
        "readiness": readiness_error,
        "preflight": preflight_error,
    }
    base_conditions = _source_blocking_conditions(source_reports, source_errors)
    lookup = _repeat_customer_lookup(base_conditions)
    blocking_conditions = base_conditions + _guard_blocking_conditions(lookup) if not base_conditions else base_conditions
    status = blocking_conditions[0]["status"] if blocking_conditions else PASS_STATUS
    payload = _build_payload(
        source_reports=source_reports,
        source_errors=source_errors,
        lookup=lookup,
        blocking_conditions=blocking_conditions,
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
    if source_errors["pre_send"]:
        conditions.append({"status": "blocked_missing_pre_send_report", "detail": source_errors["pre_send"]})
    if source_errors["readiness"]:
        conditions.append({"status": "blocked_missing_real_run_readiness_report", "detail": source_errors["readiness"]})
    if source_errors["preflight"]:
        conditions.append({"status": "blocked_missing_final_preflight_report", "detail": source_errors["preflight"]})
    if conditions:
        return conditions
    if source_reports["pre_send"].get("draft_content_pre_send_status") != EXPECTED_PRE_SEND_STATUS:
        conditions.append({"status": "blocked_missing_pre_send_report", "detail": "Phase 3.16C pre-send content report is not ready."})
    if source_reports["readiness"].get("real_run_readiness_status") != EXPECTED_READINESS_STATUS:
        conditions.append({"status": "blocked_missing_real_run_readiness_report", "detail": "Phase 3.16B readiness report is not ready."})
    if source_reports["preflight"].get("final_preflight_status") != EXPECTED_PREFLIGHT_STATUS:
        conditions.append({"status": "blocked_missing_final_preflight_report", "detail": "Phase 3.15 final preflight is not ready."})
    for label, report in source_reports.items():
        if _safe_text(report.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
            conditions.append({"status": "blocked_selected_order_mismatch", "detail": f"{label} selected_order_name mismatch."})
        if _safe_text(report.get("selected_masked_email", "")) != EXPECTED_MASKED_EMAIL:
            conditions.append({"status": "blocked_unmasked_email_detected", "detail": f"{label} selected_masked_email mismatch."})
        partial = _safe_text(report.get("source_gmail_draft_id_partial", ""))
        if partial != EXPECTED_DRAFT_ID_PARTIAL:
            conditions.append({"status": "blocked_selected_order_mismatch", "detail": f"{label} draft id partial mismatch."})
        if any(report.get(flag) is True for flag in ("gmail_drafts_send_called", "gmail_messages_send_called", "gmail_send_performed", "email_sent")):
            conditions.append({"status": "blocked_pre_send_send_flag_detected", "detail": f"{label} send flag is true."})
        if any(report.get(flag) is True for flag in ("shopify_write_performed", "mutation_performed", "tags_add_performed", "tags_remove_performed")):
            conditions.append({"status": "blocked_shopify_write_flag_detected", "detail": f"{label} write/tag flag is true."})
    return conditions


def _repeat_customer_lookup(base_conditions: list[dict]) -> dict:
    lookup = {
        "shopify_api_call_performed": False,
        "read_only_shopify_lookup_performed": False,
        "docker_command_reached": False,
        "django_shell_reached": False,
        "shopify_installation_found": False,
        "shopify_credentials_found": False,
        "raw_email_available": False,
        "raw_email_source": "",
        "customer_id_available": False,
        "repeat_customer_confirmed": False,
        "valid_order_count_for_customer": 0,
        "matched_order_count_for_customer": 0,
        "first_order_customer": False,
        "successful_lookup_label": "",
        "lookup_error_sanitized": "",
    }
    if base_conditions:
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
        _repeat_customer_lookup_script(EXPECTED_ORDER_NAME),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=PROTECTED_LOOKUP_TIMEOUT_SECONDS,
            check=False,
        )
        lookup["docker_command_reached"] = True
    except subprocess.TimeoutExpired:
        lookup["lookup_error_sanitized"] = f"repeat customer lookup timed out after {PROTECTED_LOOKUP_TIMEOUT_SECONDS} seconds"
        return lookup
    except (FileNotFoundError, PermissionError) as exc:
        lookup["lookup_error_sanitized"] = _sanitize_text(str(exc))
        return lookup
    parsed = _parse_protected_lookup_stdout(completed.stdout)
    if parsed:
        lookup["django_shell_reached"] = bool(parsed.get("django_shell_reached"))
        lookup["shopify_installation_found"] = bool(parsed.get("shopify_installation_found"))
        lookup["shopify_credentials_found"] = bool(parsed.get("shopify_credentials_found"))
        lookup["shopify_api_call_performed"] = bool(parsed.get("shopify_api_call_performed"))
        lookup["read_only_shopify_lookup_performed"] = bool(parsed.get("shopify_api_call_performed"))
        lookup["raw_email_available"] = bool(parsed.get("raw_email_available"))
        lookup["raw_email_source"] = _safe_text(parsed.get("raw_email_source", ""))
        lookup["customer_id_available"] = bool(parsed.get("customer_id_available"))
        lookup["repeat_customer_confirmed"] = bool(parsed.get("repeat_customer_confirmed"))
        lookup["valid_order_count_for_customer"] = int(parsed.get("valid_order_count_for_customer") or 0)
        lookup["matched_order_count_for_customer"] = int(parsed.get("matched_order_count_for_customer") or 0)
        lookup["first_order_customer"] = bool(parsed.get("first_order_customer"))
        lookup["successful_lookup_label"] = _safe_text(parsed.get("successful_lookup_label", ""))
        lookup["lookup_error_sanitized"] = _sanitize_text(parsed.get("error_sanitized", ""))
    if completed.returncode != 0 and not lookup["lookup_error_sanitized"]:
        lookup["lookup_error_sanitized"] = _sanitize_text(completed.stderr or completed.stdout or "repeat customer lookup failed")
    return lookup


def _repeat_customer_lookup_script(order_name: str) -> str:
    template = r'''
import json
import re
import requests
from shopify_sync.models import ShopifyInstallation

shop = __SHOP_LITERAL__
api_version = __API_VERSION_LITERAL__
order_name = __ORDER_NAME_LITERAL__
email_re = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
risk_tag_re = re.compile(r"(?i)(refund|return|cancel|chargeback|dispute|shipping[_ -]?issue|failed[_ -]?delivery)")
result = {
    "django_shell_reached": True,
    "shopify_installation_found": False,
    "shopify_credentials_found": False,
    "shopify_api_call_performed": False,
    "raw_email_available": False,
    "raw_email_source": "",
    "customer_id_available": False,
    "repeat_customer_confirmed": False,
    "valid_order_count_for_customer": 0,
    "matched_order_count_for_customer": 0,
    "first_order_customer": False,
    "successful_lookup_label": "",
    "error_sanitized": "",
}

def sanitize(text):
    text = str(text or "")
    text = re.sub(r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)", "[redacted]", text)
    return email_re.sub("[masked-email]", text)

def selected_email(order):
    candidates = [
        ("email", order.get("email")),
        ("contactEmail", order.get("contactEmail")),
        ("contact_email", order.get("contact_email")),
    ]
    for source, value in candidates:
        value = str(value or "").strip()
        if value and email_re.fullmatch(value):
            return value.lower(), source
    return "", ""

def is_valid_order(order):
    if order.get("cancelledAt") or order.get("cancelled_at"):
        return False
    financial = str(order.get("displayFinancialStatus") or order.get("financial_status") or "").lower()
    if financial in {"refunded", "partially_refunded", "voided"}:
        return False
    if order.get("test") is True:
        return False
    tags = order.get("tags") or []
    if isinstance(tags, str):
        tags = [item.strip() for item in tags.split(",") if item.strip()]
    if any(risk_tag_re.search(str(tag or "")) for tag in tags):
        return False
    return True

def request_graphql(endpoint, headers, query, variables, label):
    response = requests.post(endpoint, json={"query": query, "variables": variables}, headers=headers, timeout=30)
    result["shopify_api_call_performed"] = True
    if response.status_code >= 400:
        result["error_sanitized"] = "Shopify GraphQL HTTP error " + str(response.status_code)
        return []
    try:
        data = response.json()
    except ValueError:
        result["error_sanitized"] = "Shopify GraphQL non-JSON response"
        return []
    errors = data.get("errors") or []
    if errors:
        result["error_sanitized"] = sanitize(errors[0].get("message") if isinstance(errors[0], dict) else errors[0])[:300]
        return []
    result["successful_lookup_label"] = label
    edges = ((((data.get("data") or {}).get("orders") or {}).get("edges")) or [])
    return [edge.get("node") or {} for edge in edges]

def rest_orders(rest_base, headers, params, label):
    response = requests.get(rest_base + "/orders.json", params=params, headers=headers, timeout=30)
    result["shopify_api_call_performed"] = True
    if response.status_code >= 400:
        result["error_sanitized"] = "Shopify REST HTTP error " + str(response.status_code)
        return []
    try:
        data = response.json()
    except ValueError:
        result["error_sanitized"] = "Shopify REST non-JSON response"
        return []
    result["successful_lookup_label"] = label
    return data.get("orders") or []

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
    order_query = "query RepeatGuardOrderByName($query: String!) { orders(first: 10, query: $query) { edges { node { id name email contactEmail cancelledAt displayFinancialStatus tags test } } } }"
    selected_orders = request_graphql(endpoint, headers, order_query, {"query": "name:" + order_name}, "graphql_selected_order_by_name")
    selected_order = next((order for order in selected_orders if order.get("name") == order_name), selected_orders[0] if selected_orders else {})
    raw_email, raw_email_source = selected_email(selected_order)
    if not raw_email:
        selected_rest_orders = rest_orders(
            rest_base,
            headers,
            {
                "status": "any",
                "limit": 10,
                "fields": "id,name,email,contact_email,cancelled_at,financial_status,tags,test",
                "name": order_name,
            },
            "rest_selected_order_by_name",
        )
        selected_order = next((order for order in selected_rest_orders if order.get("name") == order_name), selected_rest_orders[0] if selected_rest_orders else {})
        raw_email, raw_email_source = selected_email(selected_order)
    if not raw_email:
        result["error_sanitized"] = "selected order email was unavailable for repeat guard."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    result["raw_email_available"] = True
    result["raw_email_source"] = raw_email_source

    matched_orders = request_graphql(
        endpoint,
        headers,
        "query RepeatGuardOrdersByEmail($query: String!) { orders(first: 50, query: $query) { edges { node { id name email contactEmail cancelledAt displayFinancialStatus tags test } } } }",
        {"query": "email:" + raw_email},
        "graphql_orders_by_email",
    )
    if not matched_orders:
        rest_params = {
            "status": "any",
            "limit": 50,
            "fields": "id,name,email,contact_email,cancelled_at,financial_status,tags,test",
            "email": raw_email,
        }
        matched_orders = rest_orders(rest_base, headers, rest_params, "rest_orders_by_email")
    exact_orders = []
    for order in matched_orders:
        order_email, _source = selected_email(order)
        if order_email == raw_email:
            exact_orders.append(order)
    result["matched_order_count_for_customer"] = len(exact_orders)
    valid_orders = [order for order in exact_orders if is_valid_order(order)]
    result["valid_order_count_for_customer"] = len(valid_orders)
    result["repeat_customer_confirmed"] = len(valid_orders) >= 2
    result["first_order_customer"] = len(valid_orders) == 1
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(0 if result["repeat_customer_confirmed"] else 1)
except Exception as exc:
    result["error_sanitized"] = sanitize(str(exc))[:300]
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
'''
    script = template.replace("__SHOP_LITERAL__", json.dumps(SHOP_DOMAIN))
    script = script.replace("__API_VERSION_LITERAL__", json.dumps(SHOPIFY_API_VERSION))
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


def _guard_blocking_conditions(lookup: dict) -> list[dict]:
    if not lookup["shopify_api_call_performed"]:
        return [{"status": "blocked_shopify_read_lookup_failed", "detail": lookup["lookup_error_sanitized"] or "read-only Shopify lookup did not run."}]
    if not lookup["raw_email_available"]:
        return [{"status": "blocked_repeat_customer_not_confirmed", "detail": "protected email was unavailable for repeat-customer guard."}]
    if lookup["valid_order_count_for_customer"] >= 2 and lookup["repeat_customer_confirmed"]:
        return []
    if lookup["valid_order_count_for_customer"] == 1:
        return [{"status": "blocked_first_order_customer", "detail": "Only one valid order was found for this customer/email."}]
    return [{"status": "blocked_repeat_customer_not_confirmed", "detail": lookup["lookup_error_sanitized"] or "repeat customer could not be confirmed."}]


def _build_payload(
    source_reports: dict,
    source_errors: dict,
    lookup: dict,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary(lookup)
    repeat_confirmed = status == PASS_STATUS
    first_order = status == "blocked_first_order_customer"
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.16D",
        "mode": "read-only-repeat-customer-guard",
        "command_label": COMMAND_LABEL,
        "repeat_customer_guard_status": status,
        "success": repeat_confirmed,
        "selected_order_name": EXPECTED_ORDER_NAME,
        "selected_masked_email": EXPECTED_MASKED_EMAIL,
        "source_gmail_draft_id_partial": EXPECTED_DRAFT_ID_PARTIAL,
        "source_pre_send_status": _safe_text(source_reports["pre_send"].get("draft_content_pre_send_status", "")),
        "source_readiness_status": _safe_text(source_reports["readiness"].get("real_run_readiness_status", "")),
        "source_final_preflight_status": _safe_text(source_reports["preflight"].get("final_preflight_status", "")),
        "repeat_customer_confirmed": repeat_confirmed,
        "valid_order_count_for_customer": lookup["valid_order_count_for_customer"],
        "matched_order_count_for_customer": lookup["matched_order_count_for_customer"],
        "first_order_customer": first_order,
        "future_trustpilot_send_allowed": repeat_confirmed,
        "first_order_should_use_ali_reviews_path": not repeat_confirmed,
        "raw_email_report_storage_allowed": False,
        "raw_email_available_to_runtime": lookup["raw_email_available"],
        "raw_email_source": lookup["raw_email_source"],
        "successful_lookup_label": lookup["successful_lookup_label"],
        "lookup_error_sanitized": lookup["lookup_error_sanitized"],
        "source_reports_used": {
            "pre_send_json_path": str(SOURCE_PRE_SEND_JSON_PATH),
            "readiness_json_path": str(SOURCE_READINESS_JSON_PATH),
            "final_preflight_json_path": str(SOURCE_PREFLIGHT_JSON_PATH),
            "source_errors_sanitized": {key: _sanitize_text(value) for key, value in source_errors.items()},
        },
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_gmail_repeat_customer_guard_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_repeat_customer_guard_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "privacy_assertion_passed": True,
        "raw_email_leak_risk_detected": False,
        "safety_summary": safety,
        **safety,
        "detected_issue_summary": _issue_summary(status, lookup["valid_order_count_for_customer"]),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary(lookup: dict) -> dict:
    return {
        "gmail_api_call_performed": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": bool(lookup["shopify_api_call_performed"]),
        "read_only_shopify_lookup_performed": bool(lookup["read_only_shopify_lookup_performed"]),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_repeat_customer_guard_path": str(json_path),
        "html_trustpilot_gmail_repeat_customer_guard_path": str(html_path),
        "repeat_customer_guard_status": payload["repeat_customer_guard_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "repeat_customer_confirmed": payload["repeat_customer_confirmed"],
        "valid_order_count_for_customer": payload["valid_order_count_for_customer"],
        "first_order_customer": payload["first_order_customer"],
        "future_trustpilot_send_allowed": payload["future_trustpilot_send_allowed"],
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
  <title>Trustpilot Gmail Repeat Customer Guard</title>
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
  <h1>Trustpilot Gmail Repeat Customer Guard</h1>
  <p class="warning">Phase 3.16D is read/report-only. It does not send Gmail, write Shopify tags, or call Kudosi/Ali Reviews.</p>
  <p>Status: <strong>{escape(payload["repeat_customer_guard_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Repeat customer confirmed: <strong>{escape(str(payload["repeat_customer_confirmed"]))}</strong></p>
  <p>Valid order count for customer/email: <strong>{escape(str(payload["valid_order_count_for_customer"]))}</strong></p>
  <p>Future Trustpilot send allowed: <strong>{escape(str(payload["future_trustpilot_send_allowed"]))}</strong></p>
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
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["repeat_customer_guard_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["future_trustpilot_send_allowed"] = False
        payload["privacy_assertion_passed"] = False
        payload["raw_email_leak_risk_detected"] = bool(self_scan["raw_customer_email_count"])
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "repeat customer guard self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
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


def _safe_text(value) -> str:
    return _sanitize_text(str(value or ""))


def _sanitize_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _issue_summary(status: str, valid_order_count: int) -> str:
    if status == PASS_STATUS:
        return f"Repeat customer guard passed with {valid_order_count} valid orders; future Trustpilot send remains gated."
    if status == "blocked_first_order_customer":
        return "Repeat customer guard blocked because this appears to be a first-order customer; route to Ali Reviews/Kudosi path later."
    return f"Repeat customer guard blocked with status {status}."


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.16D Trustpilot Gmail repeat-customer guard finished.\n"
        f"Status: {payload.get('repeat_customer_guard_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Repeat customer confirmed: {payload.get('repeat_customer_confirmed')}\n"
        f"Valid order count: {payload.get('valid_order_count_for_customer')}\n"
        f"Future Trustpilot send allowed: {payload.get('future_trustpilot_send_allowed')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail send, no Shopify writes, no tagsAdd/tagsRemove, no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
