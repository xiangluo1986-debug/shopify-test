import json
import re
import subprocess
import time
import unicodedata
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_tag_discovery"
COMMAND_LABEL = "shopify_review_request_tag_discovery_read_only"
TAG_DISCOVERY_JSON_PATH = LOG_DIR / "shopify_review_request_tag_discovery.json"
TAG_DISCOVERY_HTML_PATH = LOG_DIR / "shopify_review_request_tag_discovery.html"

SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
ORDER_LIMIT = 100
MAX_EXAMPLES_PER_TAG = 5
DOCKER_TIMEOUT_SECONDS = 180
TAG_PATTERNS = ["review", "reveiw", "request", "Delivered"]

SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\s-]?token|api[_\s-]?key|password|secret)"
)


def run_shopify_review_request_tag_discovery_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    query_result = _query_recent_order_tags()
    candidate_tags = _build_candidate_tag_records(query_result.get("orders", []))
    discovery_status = _discovery_status(query_result, candidate_tags)
    success = bool(query_result.get("success"))
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run-read-only-report",
        "phase": "0.1",
        "command_label": COMMAND_LABEL,
        "shop_domain": SHOP_DOMAIN,
        "shopify_api_version": SHOPIFY_API_VERSION,
        "order_query_limit": ORDER_LIMIT,
        "tag_candidate_patterns": TAG_PATTERNS,
        "json_tag_discovery_path": str(TAG_DISCOVERY_JSON_PATH),
        "html_tag_discovery_path": str(TAG_DISCOVERY_HTML_PATH),
        "success": success,
        "discovery_status": discovery_status,
        "orders_queried": int(query_result.get("orders_queried") or 0),
        "candidate_tag_count": len(candidate_tags),
        "exact_tag_strings": [item["exact_tag_string"] for item in candidate_tags],
        "candidate_tags": candidate_tags,
        "recommendation": "use_exact_shopify_api_value_only",
        "safety_summary": {
            "query_recent_shopify_orders_read_only": bool(query_result.get("read_only_shopify_query_performed")),
            "queried_fields": ["id", "name", "tags", "createdAt", "updatedAt"],
            "customer_fields_queried": False,
            "customer_email_queried": False,
            "sending_logic_added": False,
            "shopify_write_allowed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "tags_add_performed": False,
            "tags_remove_performed": False,
            "ali_reviews_api_call_performed": False,
            "gmail_api_call_performed": False,
            "email_sent": False,
        },
        "read_only_shopify_query_performed": bool(query_result.get("read_only_shopify_query_performed")),
        "shopify_query_type": query_result.get("shopify_query_type", ""),
        "shopify_http_status": query_result.get("http_status"),
        "shopify_api_call_performed": bool(query_result.get("shopify_api_call_performed")),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "query_failure_type": query_result.get("failure_type", ""),
        "query_error": _sanitize_text(query_result.get("error", "")),
        "stdout_tail": _sanitize_text(query_result.get("stdout_tail", "")),
        "stderr_tail": _sanitize_text(query_result.get("stderr_tail", "")),
        "detected_issue_summary": _issue_summary(discovery_status, query_result, candidate_tags),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
    }

    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_tag_discovery_path": str(json_path),
        "html_tag_discovery_path": str(html_path),
        "discovery_status": discovery_status,
        "orders_queried": payload["orders_queried"],
        "candidate_tag_count": payload["candidate_tag_count"],
        "exact_tag_strings": payload["exact_tag_strings"],
        "read_only_shopify_query_performed": payload["read_only_shopify_query_performed"],
        "shopify_query_type": payload["shopify_query_type"],
        "shopify_api_call_performed": payload["shopify_api_call_performed"],
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
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _query_recent_order_tags() -> dict:
    script = _build_django_shell_script()
    command = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", script]
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
            "error": f"Read-only Shopify order tag query timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
        }
    except FileNotFoundError as exc:
        return {**_empty_query_result(), "failure_type": "missing_env", "error": str(exc)}
    except PermissionError as exc:
        return {**_empty_query_result(), "failure_type": "docker_permission_denied", "error": str(exc)}

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        failure_type = parsed.get("failure_type") if parsed else ""
        if not failure_type:
            failure_type = _classify_command_failure(stdout, stderr)
        return {
            **_empty_query_result(),
            **parsed,
            "success": False,
            "exit_code": completed.returncode,
            "failure_type": failure_type,
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": parsed.get("error") or "Read-only Shopify order tag query command failed.",
        }

    if not parsed:
        return {
            **_empty_query_result(),
            "success": False,
            "exit_code": completed.returncode,
            "failure_type": "command_error",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": "Read-only Shopify order tag query did not return parseable JSON.",
        }

    return {
        **_empty_query_result(),
        **parsed,
        "success": bool(parsed.get("success")),
        "exit_code": completed.returncode,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def _build_django_shell_script() -> str:
    template = r'''
import json
import requests
from shopify_sync.models import ShopifyInstallation

shop = __SHOP_LITERAL__
api_version = __API_VERSION_LITERAL__
order_limit = __ORDER_LIMIT_LITERAL__

query = """
query ReviewRequestTagDiscovery($first: Int!) {
  orders(first: $first, sortKey: CREATED_AT, reverse: true) {
    pageInfo {
      hasNextPage
      endCursor
    }
    edges {
      node {
        id
        name
        tags
        createdAt
        updatedAt
      }
    }
  }
}
"""

result = {
    "success": False,
    "shopify_api_call_performed": False,
    "read_only_shopify_query_performed": False,
    "shopify_query_type": "GraphQL orders tags read-only query",
    "http_status": None,
    "orders_queried": 0,
    "orders": [],
    "has_next_page": False,
    "end_cursor_present": False,
    "failure_type": "",
    "error": "",
}

try:
    installation = ShopifyInstallation.objects.get(shop=shop)
    token_value = getattr(installation, "access_" + "token")
    endpoint = "https://" + installation.shop + "/admin/api/" + api_version + "/graphql.json"
    token_header = "X-Shopify-" + "Access-Token"
    headers = {token_header: token_value, "Content-Type": "application/json"}
    response = requests.post(
        endpoint,
        json={"query": query, "variables": {"first": order_limit}},
        headers=headers,
        timeout=30,
    )
    result["shopify_api_call_performed"] = True
    result["read_only_shopify_query_performed"] = True
    result["http_status"] = response.status_code

    try:
        data = response.json()
    except ValueError:
        result["failure_type"] = "command_error"
        result["error"] = "Shopify read-only order tag query returned non-JSON response."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)

    if response.status_code >= 400:
        result["failure_type"] = "command_error"
        result["error"] = "Shopify read-only order tag query failed with HTTP status " + str(response.status_code)
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    if data.get("errors"):
        result["failure_type"] = "command_error"
        result["error"] = "Shopify read-only order tag query returned GraphQL errors."
        result["graphql_errors_count"] = len(data.get("errors") or [])
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)

    orders_connection = ((data.get("data") or {}).get("orders") or {})
    page_info = orders_connection.get("pageInfo") or {}
    result["has_next_page"] = bool(page_info.get("hasNextPage"))
    result["end_cursor_present"] = bool(page_info.get("endCursor"))

    orders = []
    for edge in orders_connection.get("edges") or []:
        node = (edge or {}).get("node") or {}
        tags = [str(tag) for tag in (node.get("tags") or [])]
        orders.append(
            {
                "id": str(node.get("id") or ""),
                "name": str(node.get("name") or ""),
                "created_at": str(node.get("createdAt") or ""),
                "updated_at": str(node.get("updatedAt") or ""),
                "tags": tags,
            }
        )
    result["orders"] = orders
    result["orders_queried"] = len(orders)
    result["success"] = True
    print(json.dumps(result, ensure_ascii=True))
except ShopifyInstallation.DoesNotExist:
    result["failure_type"] = "missing_env"
    result["error"] = "Shopify installation was not found for the configured shop."
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
except Exception as exc:
    result["failure_type"] = "unknown"
    result["error"] = type(exc).__name__ + ": " + str(exc)
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
'''
    return (
        template.replace("__SHOP_LITERAL__", json.dumps(SHOP_DOMAIN))
        .replace("__API_VERSION_LITERAL__", json.dumps(SHOPIFY_API_VERSION))
        .replace("__ORDER_LIMIT_LITERAL__", str(ORDER_LIMIT))
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
        "failure_type": "",
        "error": "",
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _build_candidate_tag_records(orders: list[dict]) -> list[dict]:
    by_tag: dict[str, dict] = {}
    for order in orders:
        order_id = str(order.get("id") or "")
        order_name = str(order.get("name") or "")
        for tag in order.get("tags") or []:
            exact_tag = str(tag)
            matched_patterns = _matched_patterns(exact_tag)
            if not matched_patterns:
                continue
            if exact_tag not in by_tag:
                by_tag[exact_tag] = {
                    "exact_tag_string": exact_tag,
                    "unicode_codepoints": _unicode_codepoints(exact_tag),
                    "contains_half_width_colon": ":" in exact_tag,
                    "contains_full_width_colon": "\uff1a" in exact_tag,
                    "spelling_detected": _spelling_detected(exact_tag),
                    "matched_patterns": matched_patterns,
                    "order_ids": [],
                    "example_order_names": [],
                    "example_order_ids": [],
                    "recommendation": "use_exact_shopify_api_value_only",
                }
            record = by_tag[exact_tag]
            if order_id and order_id not in record["order_ids"]:
                record["order_ids"].append(order_id)
            if order_name and order_name not in record["example_order_names"]:
                record["example_order_names"].append(order_name)
            if order_id and order_id not in record["example_order_ids"]:
                record["example_order_ids"].append(order_id)

    records = []
    for record in by_tag.values():
        record["order_count"] = len(record["order_ids"])
        record["example_order_names"] = record["example_order_names"][:MAX_EXAMPLES_PER_TAG]
        record["example_order_ids"] = record["example_order_ids"][:MAX_EXAMPLES_PER_TAG]
        record.pop("order_ids", None)
        records.append(record)
    return sorted(records, key=lambda item: (-item["order_count"], item["exact_tag_string"].casefold()))


def _matched_patterns(tag: str) -> list[str]:
    lowered = tag.lower()
    matches = []
    for pattern in TAG_PATTERNS:
        if pattern.lower() in lowered:
            matches.append(pattern)
    return matches


def _unicode_codepoints(value: str) -> list[dict]:
    return [
        {
            "char": char,
            "codepoint": f"U+{ord(char):04X}",
            "name": unicodedata.name(char, "UNKNOWN"),
        }
        for char in value
    ]


def _spelling_detected(tag: str) -> str:
    lowered = tag.lower()
    if "reveiw" in lowered:
        return "reveiw"
    if "review" in lowered:
        return "review"
    return "other"


def _discovery_status(query_result: dict, candidate_tags: list[dict]) -> str:
    if not query_result.get("success"):
        return "blocked_read_only_shopify_query_failed"
    if candidate_tags:
        return "completed_candidate_tags_found"
    return "completed_no_matching_candidate_tags_found"


def _issue_summary(discovery_status: str, query_result: dict, candidate_tags: list[dict]) -> str:
    if discovery_status == "completed_candidate_tags_found":
        return f"Read-only discovery found {len(candidate_tags)} candidate tag strings. Use exact Shopify API values only."
    if discovery_status == "completed_no_matching_candidate_tags_found":
        return "Read-only discovery completed, but no tags matched review/reveiw/request/Delivered patterns."
    error = query_result.get("error") or query_result.get("failure_type") or "unknown query failure"
    return f"Read-only Shopify tag discovery did not complete: {_sanitize_text(str(error))}"


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with TAG_DISCOVERY_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return TAG_DISCOVERY_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    TAG_DISCOVERY_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return TAG_DISCOVERY_HTML_PATH


def _render_html_report(payload: dict) -> str:
    rows = "\n".join(_render_candidate_row(item) for item in payload.get("candidate_tags", []))
    if not rows:
        rows = '<tr><td colspan="8">No candidate tags matched the configured patterns.</td></tr>'
    safety = payload.get("safety_summary") or {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Review Request Tag Discovery</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 16px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; vertical-align: top; }}
    th {{ background: #f0f4f8; text-align: left; }}
    code {{ background: #f5f7fa; padding: 1px 3px; }}
    .status {{ font-weight: 700; }}
    .safety {{ display: grid; grid-template-columns: repeat(2, minmax(220px, 1fr)); gap: 6px 18px; }}
  </style>
</head>
<body>
  <h1>Shopify Review Request Tag Discovery</h1>
  <p class="status">Status: {escape(str(payload.get("discovery_status", "")))}</p>
  <p>Recommendation: <code>{escape(str(payload.get("recommendation", "")))}</code></p>
  <p>Orders queried: {payload.get("orders_queried", 0)} | Candidate tags: {payload.get("candidate_tag_count", 0)}</p>

  <h2>Safety</h2>
  <div class="safety">
    <div>Shopify read-only query: <strong>{escape(str(safety.get("query_recent_shopify_orders_read_only")))}</strong></div>
    <div>Shopify write performed: <strong>{escape(str(safety.get("shopify_write_performed")))}</strong></div>
    <div>Mutation performed: <strong>{escape(str(safety.get("mutation_performed")))}</strong></div>
    <div>tagsAdd performed: <strong>{escape(str(safety.get("tags_add_performed")))}</strong></div>
    <div>tagsRemove performed: <strong>{escape(str(safety.get("tags_remove_performed")))}</strong></div>
    <div>Email sent: <strong>{escape(str(safety.get("email_sent")))}</strong></div>
    <div>Ali Reviews API call: <strong>{escape(str(safety.get("ali_reviews_api_call_performed")))}</strong></div>
    <div>Gmail API call: <strong>{escape(str(safety.get("gmail_api_call_performed")))}</strong></div>
  </div>

  <h2>Candidate Tags</h2>
  <table>
    <thead>
      <tr>
        <th>Exact tag string</th>
        <th>Order count</th>
        <th>Spelling</th>
        <th>Half-width colon</th>
        <th>Full-width colon</th>
        <th>Matched patterns</th>
        <th>Unicode code points</th>
        <th>Example orders</th>
      </tr>
    </thead>
    <tbody>
      {rows}
    </tbody>
  </table>
</body>
</html>
"""


def _render_candidate_row(item: dict) -> str:
    codepoints = " ".join(
        f"{escape(part.get('codepoint', ''))} {escape(part.get('name', ''))}"
        for part in item.get("unicode_codepoints", [])
    )
    examples = ", ".join(escape(str(name)) for name in item.get("example_order_names", []))
    patterns = ", ".join(escape(str(pattern)) for pattern in item.get("matched_patterns", []))
    return f"""<tr>
  <td><code>{escape(str(item.get("exact_tag_string", "")))}</code></td>
  <td>{item.get("order_count", 0)}</td>
  <td>{escape(str(item.get("spelling_detected", "")))}</td>
  <td>{escape(str(item.get("contains_half_width_colon", "")))}</td>
  <td>{escape(str(item.get("contains_full_width_colon", "")))}</td>
  <td>{patterns}</td>
  <td>{codepoints}</td>
  <td>{examples}</td>
</tr>"""


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request tag discovery report finished.\n"
        f"Status: {payload.get('discovery_status')}\n"
        f"Orders queried: {payload.get('orders_queried')}\n"
        f"Candidate tags: {payload.get('candidate_tag_count')}\n"
        "Safety: read-only query only; no Shopify writes, tagsAdd, tagsRemove, Ali Reviews API, Gmail API, or email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


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


def _tail(text: str, max_lines: int = 80) -> str:
    return "\n".join(text.splitlines()[-max_lines:])


def _decode_bytes(value: bytes | None) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _sanitize_text(text: str) -> str:
    return SENSITIVE_TEXT_RE.sub("[redacted]", text or "")
