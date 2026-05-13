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


TASK_NAME = "shopify_review_request_kudosi_api_capability_probe"
COMMAND_LABEL = "shopify_review_request_kudosi_api_capability_probe_read_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_kudosi_api_capability_probe.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_kudosi_api_capability_probe.html"

DEFAULT_KUDOSI_API_BASE_URL = "https://pub.kudosi.ai"
READ_ONLY_ENDPOINT = "/public/reviews"
AUTOMATION_DECISION_STATUS = "blocked_until_review_request_send_and_status_api_confirmed"
REQUEST_TIMEOUT_SECONDS = 20

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|bearer\s+[A-Za-z0-9._-]+|access[_\s-]?token|api[_\s-]?key|password|secret)"
)


def run_shopify_review_request_kudosi_api_capability_probe_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    config = _load_kudosi_config()
    probe = _run_probe(config)
    payload = _build_payload(config, probe, round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_kudosi_config() -> dict:
    dotenv_values = _read_dotenv_values({"KUDOSI_API_BASE_URL", "KUDOSI_API_KEY"})
    base_url = (
        os.environ.get("KUDOSI_API_BASE_URL")
        or dotenv_values.get("KUDOSI_API_BASE_URL")
        or DEFAULT_KUDOSI_API_BASE_URL
    ).strip()
    key_ignored = _truthy(os.environ.get("KUDOSI_API_PROBE_IGNORE_KEY"))
    api_key = "" if key_ignored else (os.environ.get("KUDOSI_API_KEY") or dotenv_values.get("KUDOSI_API_KEY") or "").strip()
    return {
        "base_url": base_url.rstrip("/") or DEFAULT_KUDOSI_API_BASE_URL,
        "api_key_present": bool(api_key),
        "api_key": api_key,
        "api_key_source": "ignored_for_missing_key_test" if key_ignored else ("configured" if api_key else "missing"),
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
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key not in allowed_keys:
                continue
            values[key] = value.strip().strip('"').strip("'")
    except OSError:
        return values
    return values


def _run_probe(config: dict) -> dict:
    if not config["api_key_present"]:
        return {
            "capability_probe_status": "blocked_missing_kudosi_api_key",
            "kudosi_api_call_performed": False,
            "http_status": None,
            "endpoint_called": READ_ONLY_ENDPOINT,
            "response_shape_summary": {},
            "probe_error_sanitized": "",
        }

    endpoint_url = urljoin(config["base_url"] + "/", READ_ONLY_ENDPOINT.lstrip("/"))
    params = {"limit": "1"}
    url = endpoint_url + "?" + urlencode(params)
    request = Request(
        url,
        headers={"Authorization": "Bearer " + config["api_key"], "Accept": "application/json"},
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
            "capability_probe_status": "kudosi_probe_error",
            "kudosi_api_call_performed": True,
            "http_status": None,
            "endpoint_called": READ_ONLY_ENDPOINT,
            "response_shape_summary": {},
            "probe_error_sanitized": _sanitize_text(type(exc).__name__ + ": " + str(exc)),
        }

    status = _status_from_http(response_info["status_code"])
    shape = _safe_response_shape(response_info)
    return {
        "capability_probe_status": status,
        "kudosi_api_call_performed": True,
        "http_status": response_info["status_code"],
        "endpoint_called": READ_ONLY_ENDPOINT,
        "response_shape_summary": shape,
        "probe_error_sanitized": "" if status == "kudosi_read_only_probe_succeeded" else _sanitize_text(_safe_http_error(response_info)),
    }


def _status_from_http(http_status: int) -> str:
    if http_status in {401, 403}:
        return "kudosi_auth_failed"
    if 200 <= http_status < 300:
        return "kudosi_read_only_probe_succeeded"
    return "kudosi_endpoint_failed"


def _safe_response_shape(response_info: dict) -> dict:
    content_type = response_info.get("headers", {}).get("content-type", "")
    content = response_info.get("content") or b""
    summary = {
        "content_type": _sanitize_text(content_type[:120]),
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


def _safe_http_error(response_info: dict) -> str:
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
        return f"HTTP {status_code}; json_error_shape_keys={','.join(keys)}"
    return f"HTTP {status_code}; json_root_type={type(data).__name__}"


def _build_payload(config: dict, probe: dict, duration_seconds: float) -> dict:
    safety = _safety_summary(probe["kudosi_api_call_performed"])
    list_reviews_available = probe["capability_probe_status"] == "kudosi_read_only_probe_succeeded"
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "2.0",
        "mode": "read-only-kudosi-api-capability-probe",
        "command_label": COMMAND_LABEL,
        "kudosi_api_base_url": config["base_url"],
        "kudosi_api_key_present": config["api_key_present"],
        "kudosi_api_key_value_reported": False,
        "capability_probe_status": probe["capability_probe_status"],
        "http_status": probe["http_status"],
        "endpoint_called": probe["endpoint_called"],
        "http_method": "GET",
        "request_params_used": {"limit": 1},
        "put_endpoints_called": False,
        "reaction_endpoints_called": False,
        "review_request_send_endpoint_called": False,
        "response_shape_summary": probe["response_shape_summary"],
        "probe_error_sanitized": probe["probe_error_sanitized"],
        "capability_conclusions": {
            "list_reviews_available": list_reviews_available,
            "product_ratings_available": "unknown_from_probe",
            "list_questions_available": "unknown_from_probe",
            "review_request_send_available": False,
            "review_request_sent_status_available": False,
            "review_request_send_endpoint_documented": False,
            "review_request_sent_status_endpoint_documented": False,
        },
        "automation_decision_status": AUTOMATION_DECISION_STATUS,
        "safe_output_policy": {
            "api_key_output": False,
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
        "detected_issue_summary": _issue_summary(probe["capability_probe_status"], list_reviews_available),
        "duration_seconds": duration_seconds,
        "json_kudosi_api_capability_probe_path": str(REPORT_JSON_PATH),
        "html_kudosi_api_capability_probe_path": str(REPORT_HTML_PATH),
    }


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
        "success": payload["capability_probe_status"] in {
            "blocked_missing_kudosi_api_key",
            "kudosi_read_only_probe_succeeded",
            "kudosi_auth_failed",
            "kudosi_endpoint_failed",
            "kudosi_probe_error",
        },
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_kudosi_api_capability_probe_path": str(json_path),
        "html_kudosi_api_capability_probe_path": str(html_path),
        "capability_probe_status": payload["capability_probe_status"],
        "http_status": payload["http_status"],
        "endpoint_called": payload["endpoint_called"],
        "automation_decision_status": payload["automation_decision_status"],
        "list_reviews_available": payload["capability_conclusions"]["list_reviews_available"],
        "review_request_send_available": False,
        "review_request_sent_status_available": False,
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
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    conclusions = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["capability_conclusions"].items()
    )
    shape = escape(json.dumps(payload["response_shape_summary"], ensure_ascii=False, indent=2))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Kudosi API Capability Probe</title>
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
  <h1>Kudosi API Capability Probe</h1>
  <p class="warning">Phase 2.0 is read-only. No review request was sent and no write endpoint was called.</p>
  <p>Status: <strong>{escape(str(payload["capability_probe_status"]))}</strong></p>
  <p>Endpoint called: <code>GET {escape(str(payload["endpoint_called"]))}</code></p>
  <p>HTTP status: {escape(str(payload["http_status"]))}</p>
  <h2>Response Shape Summary</h2>
  <pre>{shape}</pre>
  <h2>Capability Conclusions</h2>
  <table><tbody>{conclusions}</tbody></table>
  <h2>Decision</h2>
  <p><code>{escape(str(payload["automation_decision_status"]))}</code></p>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 2.0 Kudosi API capability probe finished.\n"
        f"Status: {payload.get('capability_probe_status')}\n"
        f"Endpoint: GET {payload.get('endpoint_called')}\n"
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


def _issue_summary(status: str, list_reviews_available: bool) -> str:
    if status == "blocked_missing_kudosi_api_key":
        return "Kudosi read-only probe blocked because KUDOSI_API_KEY is not configured."
    if list_reviews_available:
        return "Kudosi GET /public/reviews is reachable, but review request send/status endpoints remain unconfirmed."
    return f"Kudosi capability probe completed with status {status}; review request send/status endpoints remain unconfirmed."


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _sanitize_text(text: str) -> str:
    redacted = SENSITIVE_TEXT_RE.sub("[redacted]", text or "")
    return EMAIL_RE.sub("[redacted-email]", redacted)
