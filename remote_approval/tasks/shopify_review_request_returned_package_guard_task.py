import json
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_returned_package_guard"
COMMAND_LABEL = "shopify_review_request_returned_package_guard"

SOURCE_PRE_SEND_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_draft_content_update_pre_send.json"
SOURCE_READINESS_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness.json"
SOURCE_PREFLIGHT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_returned_package_guard.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_returned_package_guard.html"

PASS_STATUS = "returned_package_guard_passed"
BLOCKED_RETURN_STATUS = "blocked_returned_package_tag_detected"
EXPECTED_PRE_SEND_STATUS = "trustpilot_gmail_draft_content_ready_for_send"
EXPECTED_READINESS_STATUS = "trustpilot_gmail_one_draft_real_send_ready_for_manual_execution"
EXPECTED_PREFLIGHT_STATUS = "trustpilot_gmail_one_draft_send_final_preflight_ready"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
EXACT_DELIVERED_TAG = "Delivered"
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


def run_shopify_review_request_returned_package_guard_task(mode: str) -> dict:
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
    offline_tests = _offline_return_tag_tests()
    base_conditions = _source_blocking_conditions(source_reports, source_errors, offline_tests)
    lookup = _returned_package_lookup(base_conditions)
    blocking_conditions = base_conditions + _guard_blocking_conditions(lookup) if not base_conditions else base_conditions
    status = blocking_conditions[0]["status"] if blocking_conditions else PASS_STATUS
    payload = _build_payload(
        source_reports=source_reports,
        source_errors=source_errors,
        lookup=lookup,
        offline_tests=offline_tests,
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


def _source_blocking_conditions(source_reports: dict, source_errors: dict, offline_tests: dict) -> list[dict]:
    conditions = []
    if source_errors["pre_send"]:
        conditions.append({"status": "blocked_missing_selected_order", "detail": source_errors["pre_send"]})
    if source_errors["readiness"]:
        conditions.append({"status": "blocked_missing_selected_order", "detail": source_errors["readiness"]})
    if source_errors["preflight"]:
        conditions.append({"status": "blocked_missing_selected_order", "detail": source_errors["preflight"]})
    if conditions:
        return conditions
    if source_reports["pre_send"].get("draft_content_pre_send_status") != EXPECTED_PRE_SEND_STATUS:
        conditions.append({"status": "blocked_missing_selected_order", "detail": "Phase 3.16C pre-send report is not ready."})
    if source_reports["readiness"].get("real_run_readiness_status") != EXPECTED_READINESS_STATUS:
        conditions.append({"status": "blocked_missing_selected_order", "detail": "Phase 3.16B readiness report is not ready."})
    if source_reports["preflight"].get("final_preflight_status") != EXPECTED_PREFLIGHT_STATUS:
        conditions.append({"status": "blocked_missing_selected_order", "detail": "Phase 3.15 final preflight is not ready."})
    for label, report in source_reports.items():
        if _safe_text(report.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
            conditions.append({"status": "blocked_missing_selected_order", "detail": f"{label} selected_order_name mismatch."})
        if _safe_text(report.get("selected_masked_email", "")) != EXPECTED_MASKED_EMAIL:
            conditions.append({"status": "blocked_unmasked_email_detected", "detail": f"{label} selected_masked_email mismatch."})
        if _safe_text(report.get("source_gmail_draft_id_partial", "")) != EXPECTED_DRAFT_ID_PARTIAL:
            conditions.append({"status": "blocked_missing_selected_order", "detail": f"{label} Gmail draft id partial mismatch."})
        if any(report.get(flag) is True for flag in ("gmail_drafts_send_called", "gmail_messages_send_called", "gmail_send_performed", "email_sent")):
            conditions.append({"status": "blocked_return_guard_not_confirmed", "detail": f"{label} send flag is true."})
        if any(report.get(flag) is True for flag in ("shopify_write_performed", "mutation_performed", "tags_add_performed", "tags_remove_performed")):
            conditions.append({"status": "blocked_return_guard_not_confirmed", "detail": f"{label} write/tag flag is true."})
    if not offline_tests["all_passed"]:
        conditions.append({"status": "blocked_return_guard_not_confirmed", "detail": "offline return tag matching tests failed."})
    return conditions


def _returned_package_lookup(base_conditions: list[dict]) -> dict:
    lookup = {
        "shopify_api_call_performed": False,
        "read_only_shopify_lookup_performed": False,
        "docker_command_reached": False,
        "django_shell_reached": False,
        "shopify_installation_found": False,
        "shopify_credentials_found": False,
        "selected_order_found": False,
        "successful_lookup_label": "",
        "return_tag_detected": False,
        "matched_return_tags_masked_or_names": [],
        "delivered_tag_present": False,
        "tag_count": 0,
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
        _returned_package_lookup_script(EXPECTED_ORDER_NAME),
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
        lookup["lookup_error_sanitized"] = f"returned package guard lookup timed out after {PROTECTED_LOOKUP_TIMEOUT_SECONDS} seconds"
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
        lookup["selected_order_found"] = bool(parsed.get("selected_order_found"))
        lookup["successful_lookup_label"] = _safe_text(parsed.get("successful_lookup_label", ""))
        lookup["return_tag_detected"] = bool(parsed.get("return_tag_detected"))
        lookup["matched_return_tags_masked_or_names"] = [
            _safe_text(tag) for tag in parsed.get("matched_return_tags_masked_or_names", [])
        ]
        lookup["delivered_tag_present"] = bool(parsed.get("delivered_tag_present"))
        lookup["tag_count"] = int(parsed.get("tag_count") or 0)
        lookup["lookup_error_sanitized"] = _sanitize_text(parsed.get("error_sanitized", ""))
    if completed.returncode != 0 and not lookup["lookup_error_sanitized"]:
        lookup["lookup_error_sanitized"] = _sanitize_text(completed.stderr or completed.stdout or "returned package guard lookup failed")
    return lookup


def _returned_package_lookup_script(order_name: str) -> str:
    template = r'''
import json
import re
import requests
from shopify_sync.models import ShopifyInstallation

shop = __SHOP_LITERAL__
api_version = __API_VERSION_LITERAL__
order_name = __ORDER_NAME_LITERAL__
email_re = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
result = {
    "django_shell_reached": True,
    "shopify_installation_found": False,
    "shopify_credentials_found": False,
    "shopify_api_call_performed": False,
    "selected_order_found": False,
    "successful_lookup_label": "",
    "return_tag_detected": False,
    "matched_return_tags_masked_or_names": [],
    "delivered_tag_present": False,
    "tag_count": 0,
    "error_sanitized": "",
}

def sanitize(text):
    text = str(text or "")
    text = re.sub(r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)", "[redacted]", text)
    return email_re.sub("[masked-email]", text)

def normalize_tag(tag):
    text = str(tag or "").strip().lower()
    text = re.sub(r"[\s_-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()

def is_return_tag(tag):
    normalized = normalize_tag(tag)
    compact = normalized.replace(" ", "")
    return "return" in compact or "returned" in compact

def normalize_tags(raw_tags):
    if isinstance(raw_tags, list):
        return [str(tag).strip() for tag in raw_tags if str(tag).strip()]
    if isinstance(raw_tags, str):
        return [item.strip() for item in raw_tags.split(",") if item.strip()]
    return []

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
    query = "query ReturnedPackageGuardOrderByName($query: String!) { orders(first: 10, query: $query) { edges { node { id name tags } } } }"
    selected_orders = request_graphql(endpoint, headers, query, {"query": "name:" + order_name}, "graphql_order_tags_by_name")
    selected_order = next((order for order in selected_orders if order.get("name") == order_name), selected_orders[0] if selected_orders else {})
    if not selected_order:
        rest_selected = rest_orders(
            rest_base,
            headers,
            {"status": "any", "limit": 10, "fields": "id,name,tags", "name": order_name},
            "rest_order_tags_by_name",
        )
        selected_order = next((order for order in rest_selected if order.get("name") == order_name), rest_selected[0] if rest_selected else {})
    if not selected_order:
        result["error_sanitized"] = "selected order was unavailable for returned package guard."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    result["selected_order_found"] = True
    tags = normalize_tags(selected_order.get("tags") or [])
    result["tag_count"] = len(tags)
    result["delivered_tag_present"] = "Delivered" in tags
    matched = [tag for tag in tags if is_return_tag(tag)]
    result["matched_return_tags_masked_or_names"] = [sanitize(tag) for tag in matched]
    result["return_tag_detected"] = bool(matched)
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(0)
except ShopifyInstallation.DoesNotExist:
    result["error_sanitized"] = "Shopify installation was not found for the configured shop."
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
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
    if not lookup["selected_order_found"]:
        return [{"status": "blocked_missing_selected_order", "detail": lookup["lookup_error_sanitized"] or "selected order was not found."}]
    if lookup["return_tag_detected"]:
        return [{"status": BLOCKED_RETURN_STATUS, "detail": "Return/returned package tag was detected; Delivered does not override this block."}]
    return []


def _build_payload(
    source_reports: dict,
    source_errors: dict,
    lookup: dict,
    offline_tests: dict,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    guard_passed = status == PASS_STATUS
    safety = _safety_summary(lookup)
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.16E",
        "mode": "read-only-returned-package-tag-guard",
        "command_label": COMMAND_LABEL,
        "return_guard_status": status,
        "success": guard_passed,
        "selected_order_name": EXPECTED_ORDER_NAME,
        "selected_masked_email": EXPECTED_MASKED_EMAIL,
        "source_gmail_draft_id_partial": EXPECTED_DRAFT_ID_PARTIAL,
        "source_pre_send_status": _safe_text(source_reports["pre_send"].get("draft_content_pre_send_status", "")),
        "source_readiness_status": _safe_text(source_reports["readiness"].get("real_run_readiness_status", "")),
        "source_final_preflight_status": _safe_text(source_reports["preflight"].get("final_preflight_status", "")),
        "return_tag_detected": bool(lookup["return_tag_detected"]),
        "matched_return_tags_masked_or_names": lookup["matched_return_tags_masked_or_names"],
        "delivered_tag_present": bool(lookup["delivered_tag_present"]),
        "delivered_does_not_override_return_block": True,
        "future_tracking_api_upgrade_note": True,
        "review_request_allowed": guard_passed,
        "trustpilot_send_allowed": guard_passed,
        "ali_reviews_send_allowed": guard_passed,
        "kudosi_send_allowed": guard_passed,
        "manual_review_request_allowed": guard_passed,
        "selected_order_found": bool(lookup["selected_order_found"]),
        "tag_count": int(lookup["tag_count"]),
        "successful_lookup_label": lookup["successful_lookup_label"],
        "lookup_error_sanitized": lookup["lookup_error_sanitized"],
        "offline_return_tag_tests": offline_tests,
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
        "json_returned_package_guard_path": str(REPORT_JSON_PATH),
        "html_returned_package_guard_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "privacy_assertion_passed": True,
        "raw_email_leak_risk_detected": False,
        "safety_summary": safety,
        **safety,
        "detected_issue_summary": _issue_summary(status, lookup),
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
        "json_returned_package_guard_path": str(json_path),
        "html_returned_package_guard_path": str(html_path),
        "return_guard_status": payload["return_guard_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "return_tag_detected": payload["return_tag_detected"],
        "matched_return_tags_masked_or_names": payload["matched_return_tags_masked_or_names"],
        "review_request_allowed": payload["review_request_allowed"],
        "trustpilot_send_allowed": payload["trustpilot_send_allowed"],
        "ali_reviews_send_allowed": payload["ali_reviews_send_allowed"],
        "kudosi_send_allowed": payload["kudosi_send_allowed"],
        "manual_review_request_allowed": payload["manual_review_request_allowed"],
        "delivered_tag_present": payload["delivered_tag_present"],
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
    matched = ", ".join(f"<code>{escape(tag)}</code>" for tag in payload["matched_return_tags_masked_or_names"]) or "None"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Returned Package Guard</title>
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
  <h1>Review Request Returned Package Guard</h1>
  <p class="warning">Phase 3.16E is read/report-only. It does not send Gmail, write Shopify tags, or call Kudosi/Ali Reviews.</p>
  <p>Status: <strong>{escape(payload["return_guard_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Return tag detected: <strong>{escape(str(payload["return_tag_detected"]))}</strong></p>
  <p>Matched return tags: {matched}</p>
  <p>Delivered tag present: <strong>{escape(str(payload["delivered_tag_present"]))}</strong></p>
  <p>Delivered overrides return block: <strong>False</strong></p>
  <p>Review request allowed by this guard: <strong>{escape(str(payload["review_request_allowed"]))}</strong></p>
  <p>Trustpilot send allowed by this guard: <strong>{escape(str(payload["trustpilot_send_allowed"]))}</strong></p>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _offline_return_tag_tests() -> dict:
    cases = [
        {"name": "returned_exact", "tags": ["Returned"], "expected_block": True},
        {"name": "return_to_warehouse", "tags": ["return to warehouse"], "expected_block": True},
        {"name": "delivered_plus_returned", "tags": ["Delivered", "Returned"], "expected_block": True},
        {"name": "delivered_only", "tags": ["Delivered"], "expected_block": False},
    ]
    results = []
    for case in cases:
        matched = [tag for tag in case["tags"] if _is_return_tag(tag)]
        blocked = bool(matched)
        results.append(
            {
                "name": case["name"],
                "expected_block": case["expected_block"],
                "actual_block": blocked,
                "passed": blocked == case["expected_block"],
            }
        )
    return {
        "all_passed": all(item["passed"] for item in results),
        "cases": results,
    }


def _is_return_tag(tag: str) -> bool:
    normalized = _normalize_return_tag_text(tag)
    compact = normalized.replace(" ", "")
    return "return" in compact or "returned" in compact


def _normalize_return_tag_text(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"[\s_-]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["return_guard_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["review_request_allowed"] = False
        payload["trustpilot_send_allowed"] = False
        payload["ali_reviews_send_allowed"] = False
        payload["kudosi_send_allowed"] = False
        payload["manual_review_request_allowed"] = False
        payload["privacy_assertion_passed"] = False
        payload["raw_email_leak_risk_detected"] = bool(self_scan["raw_customer_email_count"])
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "returned package guard self privacy scan failed."}
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


def _issue_summary(status: str, lookup: dict) -> str:
    if status == PASS_STATUS:
        return "Returned package guard passed; no return/returned tag was found on the selected order."
    if status == BLOCKED_RETURN_STATUS:
        return "Returned package guard blocked all review requests because a return/returned tag was found."
    return f"Returned package guard blocked with status {status}: {_safe_text(lookup.get('lookup_error_sanitized', ''))}"


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.16E returned package guard finished.\n"
        f"Status: {payload.get('return_guard_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Return tag detected: {payload.get('return_tag_detected')}\n"
        f"Review request allowed: {payload.get('review_request_allowed')}\n"
        f"Trustpilot send allowed: {payload.get('trustpilot_send_allowed')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail send, no Shopify writes, no tagsAdd/tagsRemove, no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
