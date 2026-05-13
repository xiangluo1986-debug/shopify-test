import hashlib
import json
import os
import re
import time
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_kudosi_api_403_diagnostics"
COMMAND_LABEL = "shopify_review_request_kudosi_api_403_diagnostics_read_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_kudosi_api_403_diagnostics.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_kudosi_api_403_diagnostics.html"

DEFAULT_KUDOSI_API_BASE_URL = "https://pub.kudosi.ai"
READ_ONLY_ENDPOINT = "/public/reviews"
REQUEST_TIMEOUT_SECONDS = 20

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|bearer\s+[A-Za-z0-9._-]+|access[_\s-]?token|api[_\s-]?key|password|secret)"
)
AUTOMATION_DECISION_STATUS = "blocked_until_review_request_send_and_status_api_confirmed"


def run_shopify_review_request_kudosi_api_403_diagnostics_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    config = _load_kudosi_config()
    probe = _run_read_only_diagnostics(config)
    payload = _build_payload(config, probe, round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_kudosi_config() -> dict:
    dotenv_values = _read_dotenv_values({"KUDOSI_API_BASE_URL", "KUDOSI_API_KEY"})
    base_url_raw = os.environ.get("KUDOSI_API_BASE_URL")
    if base_url_raw is None:
        base_url_raw = dotenv_values.get("KUDOSI_API_BASE_URL", "")
    base_url = (base_url_raw.strip() or DEFAULT_KUDOSI_API_BASE_URL).rstrip("/")

    key_ignored = _truthy(os.environ.get("KUDOSI_API_DIAGNOSTICS_IGNORE_KEY"))
    api_key_raw = ""
    if not key_ignored:
        api_key_raw = os.environ.get("KUDOSI_API_KEY")
        if api_key_raw is None:
            api_key_raw = dotenv_values.get("KUDOSI_API_KEY", "")

    return {
        "base_url": base_url,
        "base_url_present": bool(base_url_raw.strip()) if isinstance(base_url_raw, str) else False,
        "api_key_raw": api_key_raw,
        "api_key_ignored_for_test": key_ignored,
    }


def _read_dotenv_values(allowed_keys: set[str]) -> dict:
    dotenv_path = PROJECT_ROOT / ".env"
    values = {}
    if not dotenv_path.exists():
        return values
    try:
        for line in dotenv_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in allowed_keys:
                continue
            values[key] = value
    except OSError:
        return values
    return values


def _safe_key_diagnostics(api_key_raw: str) -> dict:
    key_present = bool(api_key_raw)
    return {
        "api_key_present": key_present,
        "api_key_length": len(api_key_raw) if key_present else 0,
        "api_key_has_leading_or_trailing_whitespace": bool(api_key_raw and api_key_raw != api_key_raw.strip()),
        "api_key_contains_spaces": " " in api_key_raw if key_present else False,
        "api_key_contains_quotes": any(char in api_key_raw for char in ['"', "'"]) if key_present else False,
        "api_key_safe_fingerprint_prefix": _fingerprint_prefix(api_key_raw) if key_present else "",
    }


def _fingerprint_prefix(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()[:8]


def _run_read_only_diagnostics(config: dict) -> dict:
    api_key_raw = config["api_key_raw"]
    if not api_key_raw:
        return {
            "diagnostics_status": "blocked_missing_kudosi_api_key",
            "kudosi_api_call_performed": False,
            "http_status": None,
            "response_content_type": "",
            "safe_error_summary": "",
            "response_top_level_shape": {},
        }

    endpoint_url = urljoin(config["base_url"] + "/", READ_ONLY_ENDPOINT.lstrip("/"))
    request_url = endpoint_url + "?" + urlencode({"limit": "1"})
    request = Request(
        request_url,
        headers={"Authorization": "Bearer " + api_key_raw, "Accept": "application/json"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
            response_info = {
                "status_code": int(response.status),
                "headers": dict(response.headers.items()),
                "content": response.read(),
            }
    except HTTPError as exc:
        response_info = {
            "status_code": int(exc.code),
            "headers": dict(exc.headers.items()) if exc.headers else {},
            "content": exc.read(),
        }
    except URLError as exc:
        return {
            "diagnostics_status": "kudosi_probe_error",
            "kudosi_api_call_performed": True,
            "http_status": None,
            "response_content_type": "",
            "safe_error_summary": _sanitize_text(type(exc).__name__ + ": " + str(exc)),
            "response_top_level_shape": {},
        }

    http_status = response_info["status_code"]
    return {
        "diagnostics_status": _diagnostics_status_from_http(http_status),
        "kudosi_api_call_performed": True,
        "http_status": http_status,
        "response_content_type": _sanitize_text((response_info.get("headers") or {}).get("content-type", "")[:120]),
        "safe_error_summary": _safe_error_summary(response_info),
        "response_top_level_shape": _safe_response_shape(response_info),
    }


def _diagnostics_status_from_http(http_status: int) -> str:
    if http_status == 403:
        return "kudosi_auth_or_permission_failed"
    if http_status in {401, 407}:
        return "kudosi_auth_or_permission_failed"
    if 200 <= http_status < 300:
        return "kudosi_read_only_diagnostics_succeeded"
    return "kudosi_endpoint_failed"


def _safe_error_summary(response_info: dict) -> str:
    status_code = int(response_info.get("status_code") or 0)
    content = response_info.get("content") or b""
    if 200 <= status_code < 300:
        return ""
    try:
        data = json.loads(content.decode("utf-8", errors="replace"))
    except ValueError:
        return f"HTTP {status_code}; non-json response; response_bytes={len(content)}"
    if isinstance(data, dict):
        keys = sorted(str(key) for key in data.keys())[:20]
        return _sanitize_text(f"HTTP {status_code}; json_error_shape_keys={','.join(keys)}")
    return f"HTTP {status_code}; json_root_type={type(data).__name__}"


def _safe_response_shape(response_info: dict) -> dict:
    content = response_info.get("content") or b""
    summary = {
        "response_bytes": len(content),
        "json_parseable": False,
        "root_type": "",
        "top_level_keys": [],
        "top_level_list_count": None,
        "nested_collection_counts": {},
        "first_item_keys": [],
    }
    try:
        data = json.loads(content.decode("utf-8", errors="replace"))
    except ValueError:
        return summary
    summary["json_parseable"] = True
    if isinstance(data, dict):
        summary["root_type"] = "object"
        summary["top_level_keys"] = sorted(str(key) for key in data.keys())[:30]
        nested_counts = {}
        first_item_keys = []
        for key, value in data.items():
            if isinstance(value, list):
                nested_counts[str(key)] = len(value)
                if value and isinstance(value[0], dict) and not first_item_keys:
                    first_item_keys = sorted(str(item_key) for item_key in value[0].keys())[:30]
        summary["nested_collection_counts"] = nested_counts
        summary["first_item_keys"] = first_item_keys
    elif isinstance(data, list):
        summary["root_type"] = "array"
        summary["top_level_list_count"] = len(data)
        if data and isinstance(data[0], dict):
            summary["first_item_keys"] = sorted(str(key) for key in data[0].keys())[:30]
    else:
        summary["root_type"] = type(data).__name__
    return summary


def _build_payload(config: dict, probe: dict, duration_seconds: float) -> dict:
    key_diagnostics = _safe_key_diagnostics(config["api_key_raw"])
    safety = _safety_summary(probe["kudosi_api_call_performed"])
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "2.1",
        "mode": "read-only-kudosi-api-403-diagnostics",
        "command_label": COMMAND_LABEL,
        "diagnostics_status": probe["diagnostics_status"],
        "base_url_present": config["base_url_present"],
        "base_url_value": config["base_url"],
        **key_diagnostics,
        "api_key_value_reported": False,
        "request_diagnostics": {
            "endpoint": READ_ONLY_ENDPOINT,
            "method": "GET",
            "query_params": {"limit": 1},
            "auth_header_mode": "token_scheme_value_omitted",
            "authorization_header_present": key_diagnostics["api_key_present"],
            "authorization_value_reported": False,
            "put_endpoints_called": False,
            "reaction_endpoints_called": False,
            "review_request_send_endpoint_called": False,
        },
        "http_status": probe["http_status"],
        "response_content_type": probe["response_content_type"],
        "safe_error_summary": probe["safe_error_summary"],
        "response_top_level_shape": probe["response_top_level_shape"],
        "likely_causes": _likely_causes(probe["diagnostics_status"]),
        "support_message_template": _support_message_template(),
        "automation_decision_status": AUTOMATION_DECISION_STATUS,
        "safe_output_policy": {
            "api_key_output": False,
            "authorization_value_output": False,
            "raw_payload_output": False,
            "personal_data_output": False,
            "contact_data_output": False,
            "location_data_output": False,
            "message_text_output": False,
            "shopper_identity_output": False,
            "network_identity_output": False,
        },
        "safety_summary": safety,
        **safety,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(probe["diagnostics_status"], probe["http_status"]),
        "duration_seconds": duration_seconds,
        "json_kudosi_api_403_diagnostics_path": str(REPORT_JSON_PATH),
        "html_kudosi_api_403_diagnostics_path": str(REPORT_HTML_PATH),
    }


def _likely_causes(status: str) -> list[str]:
    if status != "kudosi_auth_or_permission_failed":
        return []
    return [
        "API key invalid or expired.",
        "API key copied with extra characters.",
        "Public API not enabled for account.",
        "Endpoint not available for current plan/store.",
        "Different token format required.",
        "Kudosi account/store mismatch.",
    ]


def _support_message_template() -> str:
    return (
        "Hello Kudosi / Ali Reviews support,\n\n"
        "We are preparing a read-only review request automation audit for our Shopify store. "
        "A read-only GET request to /public/reviews returned HTTP 403. No write, reaction, or review-request send "
        "endpoint was called.\n\n"
        "Could you please confirm:\n"
        "1. Whether our API key has Public API access enabled.\n"
        "2. Whether GET /public/reviews is permitted for our current plan/store.\n"
        "3. The correct Authorization header format for Public API calls.\n"
        "4. Whether an API endpoint exists to send a review request for a specific Shopify order.\n"
        "5. Whether an API endpoint exists to check if a review request was already sent for a Shopify order.\n\n"
        "We are intentionally not including any API key or Authorization header value in this message."
    )


def _safety_summary(kudosi_api_call_performed: bool) -> dict:
    return {
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "kudosi_api_call_performed": bool(kudosi_api_call_performed),
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": bool(kudosi_api_call_performed),
        "gmail_api_call_performed": False,
        "email_sent": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["diagnostics_status"] in {
            "blocked_missing_kudosi_api_key",
            "kudosi_auth_or_permission_failed",
            "kudosi_endpoint_failed",
            "kudosi_probe_error",
            "kudosi_read_only_diagnostics_succeeded",
        },
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_kudosi_api_403_diagnostics_path": str(json_path),
        "html_kudosi_api_403_diagnostics_path": str(html_path),
        "diagnostics_status": payload["diagnostics_status"],
        "http_status": payload["http_status"],
        "endpoint_called": payload["request_diagnostics"]["endpoint"],
        "authorization_header_present": payload["request_diagnostics"]["authorization_header_present"],
        "api_key_present": payload["api_key_present"],
        "api_key_length": payload["api_key_length"],
        "api_key_has_leading_or_trailing_whitespace": payload["api_key_has_leading_or_trailing_whitespace"],
        "api_key_contains_spaces": payload["api_key_contains_spaces"],
        "api_key_contains_quotes": payload["api_key_contains_quotes"],
        "api_key_safe_fingerprint_prefix": payload["api_key_safe_fingerprint_prefix"],
        "automation_decision_status": payload["automation_decision_status"],
        "kudosi_api_call_performed": payload["kudosi_api_call_performed"],
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
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
    key_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td>{escape(str(payload.get(key)))}</td></tr>"
        for key in [
            "base_url_present",
            "base_url_value",
            "api_key_present",
            "api_key_length",
            "api_key_has_leading_or_trailing_whitespace",
            "api_key_contains_spaces",
            "api_key_contains_quotes",
            "api_key_safe_fingerprint_prefix",
        ]
    )
    request_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["request_diagnostics"].items()
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    causes = "".join(f"<li>{escape(item)}</li>" for item in payload["likely_causes"]) or "<li>No 403-specific cause list for this status.</li>"
    shape = escape(json.dumps(payload["response_top_level_shape"], ensure_ascii=False, indent=2))
    support_template = escape(payload["support_message_template"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Kudosi API 403 Diagnostics</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    pre {{ background: #f5f7fa; border: 1px solid #d9e2ec; padding: 12px; white-space: pre-wrap; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Kudosi API 403 Diagnostics</h1>
  <p class="warning">Phase 2.1 is read-only. No review request was sent and no write endpoint was called.</p>
  <p>Status: <strong>{escape(str(payload["diagnostics_status"]))}</strong></p>
  <p>HTTP status: {escape(str(payload["http_status"]))}</p>
  <h2>Safe Key Diagnostics</h2>
  <table><tbody>{key_rows}</tbody></table>
  <h2>Request Diagnostics</h2>
  <table><tbody>{request_rows}</tbody></table>
  <h2>Safe Error Summary</h2>
  <p>{escape(str(payload["safe_error_summary"]))}</p>
  <h2>Response Shape</h2>
  <pre>{shape}</pre>
  <h2>Likely 403 Causes</h2>
  <ul>{causes}</ul>
  <h2>Support Message Template</h2>
  <pre>{support_template}</pre>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 2.1 Kudosi API 403 diagnostics finished.\n"
        f"Status: {payload.get('diagnostics_status')}\n"
        f"Endpoint: GET {payload.get('request_diagnostics', {}).get('endpoint')}\n"
        f"HTTP status: {payload.get('http_status')}\n"
        f"Kudosi read-only API call performed: {payload.get('kudosi_api_call_performed')}\n"
        f"Decision: {payload.get('automation_decision_status')}\n"
        "Safety: no Shopify writes, no tagsAdd/tagsRemove, no Kudosi write/reaction/send endpoint, no Gmail API, and no email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, http_status: int | None) -> str:
    if status == "blocked_missing_kudosi_api_key":
        return "Kudosi 403 diagnostics blocked because KUDOSI_API_KEY is not configured."
    if status == "kudosi_auth_or_permission_failed":
        return f"Kudosi read-only GET returned HTTP {http_status}; auth, permission, plan, or store mismatch needs support confirmation."
    if status == "kudosi_read_only_diagnostics_succeeded":
        return "Kudosi read-only GET succeeded; review request send/status endpoints remain unconfirmed."
    return f"Kudosi diagnostics completed with status {status}; review request send/status endpoints remain unconfirmed."


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _sanitize_text(text: str) -> str:
    redacted = SENSITIVE_TEXT_RE.sub("[redacted]", text or "")
    return EMAIL_RE.sub("[redacted-email]", redacted)
