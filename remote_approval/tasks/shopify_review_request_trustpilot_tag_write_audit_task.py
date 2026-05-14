import json
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_tag_write_audit"
COMMAND_LABEL = "shopify_review_request_trustpilot_tag_write_audit"

SOURCE_EXECUTE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_execute.json"
SOURCE_EXECUTE_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_execute.html"
SOURCE_CANDIDATE_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_candidate_scan.json"
PROTECTED_DRAFT_SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_audit.html"

SUCCESS_STATUS = "trustpilot_tag_write_audit_passed"
EXPECTED_EXECUTE_STATUS = "one_trustpilot_tag_written_and_needs_audit"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
CANONICAL_TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
SHOPIFY_READBACK_TIMEOUT_SECONDS = 120
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


def run_shopify_review_request_trustpilot_tag_write_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    execute_report, execute_error = _read_json_report(
        SOURCE_EXECUTE_JSON_PATH, "blocked_missing_tag_write_execute_report"
    )
    target_order_gid, target_order_gid_error = _target_order_gid_from_candidate_scan()
    source_privacy_scan = {
        "execute_json": _privacy_scan_text(_read_text(SOURCE_EXECUTE_JSON_PATH)),
        "execute_html": _privacy_scan_text(_read_text(SOURCE_EXECUTE_HTML_PATH)),
    }
    full_draft_id_leak = _full_draft_id_leak_detected(
        _read_text(SOURCE_EXECUTE_JSON_PATH),
        _read_text(SOURCE_EXECUTE_HTML_PATH),
    )
    base_conditions = _source_blocking_conditions(
        execute_report=execute_report,
        execute_error=execute_error,
        target_order_gid=target_order_gid,
        target_order_gid_error=target_order_gid_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
    )
    readback = _shopify_tag_readback(base_conditions, target_order_gid)
    blocking_conditions = base_conditions if base_conditions else _readback_blocking_conditions(readback)
    status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        execute_report=execute_report,
        execute_error=execute_error,
        target_order_gid=target_order_gid,
        target_order_gid_error=target_order_gid_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        readback=readback,
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


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _target_order_gid_from_candidate_scan() -> tuple[str, str]:
    if not SOURCE_CANDIDATE_SCAN_JSON_PATH.exists():
        return "", "blocked_missing_candidate_scan_report"
    try:
        candidate_scan = json.loads(SOURCE_CANDIDATE_SCAN_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return "", _sanitize_text(f"blocked_missing_candidate_scan_report: source JSON parse failed: {exc}")
    for order in _walk_order_dicts(candidate_scan):
        if _safe_text(order.get("order_name", "")) != EXPECTED_ORDER_NAME:
            continue
        order_gid = _safe_text(order.get("order_id") or order.get("order_id_or_gid") or order.get("id") or "")
        if order_gid.startswith("gid://shopify/Order/"):
            return order_gid, ""
    return "", "blocked_missing_order_gid_for_tag_audit"


def _walk_order_dicts(value):
    if isinstance(value, dict):
        if "order_name" in value:
            yield value
        for nested in value.values():
            yield from _walk_order_dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_order_dicts(item)


def _source_blocking_conditions(
    execute_report: dict,
    execute_error: str,
    target_order_gid: str,
    target_order_gid_error: str,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
) -> list[dict]:
    conditions = []
    if execute_error:
        return [{"status": "blocked_missing_tag_write_execute_report", "detail": _sanitize_text(execute_error)}]
    if execute_report.get("tag_write_execute_status") != EXPECTED_EXECUTE_STATUS or execute_report.get("success") is not True:
        conditions.append({"status": "blocked_source_tag_write_not_successful", "detail": "Phase 3.22 tag-write execute report did not succeed."})
    if execute_report.get("mode") != "real-run" or execute_report.get("dry_run") is not False:
        conditions.append({"status": "blocked_source_not_real_run", "detail": "Phase 3.22 source report is not a real-run."})
    if _safe_text(execute_report.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_selected_order_mismatch", "detail": "selected_order_name must equal #22621."})
    masked_email = _safe_text(execute_report.get("selected_masked_email", ""))
    if masked_email != EXPECTED_MASKED_EMAIL or not _is_masked_email(masked_email):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected_masked_email mismatch or unmasked."})
    if _safe_text(execute_report.get("source_gmail_draft_id_partial", "")) != EXPECTED_DRAFT_ID_PARTIAL:
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "Gmail draft id partial mismatch."})
    if _safe_text(execute_report.get("planned_shopify_tag", "")) != CANONICAL_TRUSTPILOT_TAG:
        conditions.append({"status": "blocked_tag_value_mismatch", "detail": "planned Shopify tag must exactly equal 1: trustpilot."})
    if int(execute_report.get("source_sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "source_sent_count must equal 1."})
    if int(execute_report.get("written_tag_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_written_tag_count", "detail": "written_tag_count must equal 1."})
    if execute_report.get("tag_write_performed") is not True or execute_report.get("post_write_tag_present") is not True:
        conditions.append({"status": "blocked_source_tag_write_not_successful", "detail": "source report did not confirm tag write and post-write tag presence."})
    if execute_report.get("shopify_write_performed") is not True or execute_report.get("mutation_performed") is not True:
        conditions.append({"status": "blocked_missing_source_shopify_write_confirmation", "detail": "source report did not confirm the expected prior Shopify write."})
    if execute_report.get("tags_add_performed") is not True or execute_report.get("tagsAdd_performed") is not True:
        conditions.append({"status": "blocked_missing_source_tags_add_confirmation", "detail": "source report did not confirm tagsAdd."})
    if execute_report.get("tags_remove_performed") is not False or execute_report.get("tagsRemove_performed") is not False:
        conditions.append({"status": "blocked_tags_remove_detected", "detail": "source report indicates tagsRemove."})
    if any(execute_report.get(flag) is True for flag in ("gmail_api_call_performed", "gmail_drafts_send_called", "gmail_messages_send_called", "email_sent")):
        conditions.append({"status": "blocked_unexpected_gmail_action_detected", "detail": "Phase 3.22 source should not perform Gmail actions."})
    if any(execute_report.get(flag) is True for flag in ("kudosi_api_call_performed", "ali_reviews_api_call_performed")):
        conditions.append({"status": "blocked_kudosi_or_ali_reviews_detected", "detail": "Phase 3.22 source should not call Kudosi/Ali Reviews."})
    if int(execute_report.get("blocking_condition_count") or 0) != 0:
        conditions.append({"status": "blocked_source_has_blocking_conditions", "detail": "source blocking_condition_count must be 0."})
    if not target_order_gid or target_order_gid_error:
        conditions.append({"status": "blocked_missing_order_gid_for_tag_audit", "detail": _sanitize_text(target_order_gid_error)})
    if _privacy_scan_failed(source_privacy_scan) or full_draft_id_leak_detected:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source report privacy scan failed."})
    return conditions


def _shopify_tag_readback(base_conditions: list[dict], target_order_gid: str) -> dict:
    readback = {
        "shopify_api_call_performed": False,
        "read_only_shopify_lookup_performed": False,
        "docker_command_reached": False,
        "django_shell_reached": False,
        "shopify_installation_found": False,
        "shopify_credentials_found": False,
        "selected_order_found": False,
        "successful_lookup_label": "",
        "shopify_order_name_confirmed": "",
        "tag_count": 0,
        "canonical_trustpilot_tag": CANONICAL_TRUSTPILOT_TAG,
        "canonical_trustpilot_tag_present": False,
        "trustpilot_tag_detected": False,
        "legacy_trustpilot_tag_detected": False,
        "matched_trustpilot_tags": [],
        "matched_legacy_trustpilot_tags": [],
        "readback_error_sanitized": "",
    }
    if base_conditions:
        return readback
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
        _shopify_tag_readback_script(target_order_gid, EXPECTED_ORDER_NAME),
    ]
    try:
        completed = subprocess.run(
            command,
            text=True,
            capture_output=True,
            timeout=SHOPIFY_READBACK_TIMEOUT_SECONDS,
            check=False,
        )
        readback["docker_command_reached"] = True
    except subprocess.TimeoutExpired:
        readback["readback_error_sanitized"] = f"Shopify tag readback timed out after {SHOPIFY_READBACK_TIMEOUT_SECONDS} seconds."
        return readback
    except (FileNotFoundError, PermissionError) as exc:
        readback["readback_error_sanitized"] = _sanitize_text(str(exc))
        return readback
    parsed = _parse_json_from_stdout(completed.stdout)
    if parsed:
        readback.update(
            {
                "django_shell_reached": bool(parsed.get("django_shell_reached")),
                "shopify_installation_found": bool(parsed.get("shopify_installation_found")),
                "shopify_credentials_found": bool(parsed.get("shopify_credentials_found")),
                "shopify_api_call_performed": bool(parsed.get("shopify_api_call_performed")),
                "read_only_shopify_lookup_performed": bool(parsed.get("shopify_api_call_performed")),
                "selected_order_found": bool(parsed.get("selected_order_found")),
                "successful_lookup_label": _safe_text(parsed.get("successful_lookup_label", "")),
                "shopify_order_name_confirmed": _safe_text(parsed.get("shopify_order_name_confirmed", "")),
                "tag_count": int(parsed.get("tag_count") or 0),
                "canonical_trustpilot_tag_present": bool(parsed.get("canonical_trustpilot_tag_present")),
                "trustpilot_tag_detected": bool(parsed.get("trustpilot_tag_detected")),
                "legacy_trustpilot_tag_detected": bool(parsed.get("legacy_trustpilot_tag_detected")),
                "matched_trustpilot_tags": [_safe_text(tag) for tag in parsed.get("matched_trustpilot_tags", [])],
                "matched_legacy_trustpilot_tags": [
                    _safe_text(tag) for tag in parsed.get("matched_legacy_trustpilot_tags", [])
                ],
                "readback_error_sanitized": _sanitize_text(parsed.get("error_sanitized", "")),
            }
        )
    if completed.returncode != 0 and not readback["readback_error_sanitized"]:
        readback["readback_error_sanitized"] = _sanitize_text(completed.stderr or completed.stdout or "Shopify tag readback failed.")
    return readback


def _shopify_tag_readback_script(order_gid: str, order_name: str) -> str:
    template = r'''
import json
import re
import requests
from shopify_sync.models import ShopifyInstallation

shop = __SHOP_LITERAL__
api_version = __API_VERSION_LITERAL__
order_gid = __ORDER_GID_LITERAL__
order_name = __ORDER_NAME_LITERAL__
canonical_tag = __CANONICAL_TAG_LITERAL__
alias_tags = __ALIAS_TAGS_LITERAL__
email_re = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
result = {
    "django_shell_reached": True,
    "shopify_installation_found": False,
    "shopify_credentials_found": False,
    "shopify_api_call_performed": False,
    "selected_order_found": False,
    "successful_lookup_label": "",
    "shopify_order_name_confirmed": "",
    "tag_count": 0,
    "canonical_trustpilot_tag_present": False,
    "trustpilot_tag_detected": False,
    "legacy_trustpilot_tag_detected": False,
    "matched_trustpilot_tags": [],
    "matched_legacy_trustpilot_tags": [],
    "error_sanitized": "",
}

def sanitize(text):
    text = str(text or "")
    text = re.sub(r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|api[_\s-]?key|password|secret|bearer\s+[A-Za-z0-9._-]+)", "[redacted]", text)
    return email_re.sub("[masked-email]", text)

def normalize_tag(tag):
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    text = re.sub(r"\s+", " ", text)
    return text

def fetch_by_gid(endpoint, headers):
    query = """
    query($id: ID!) {
      node(id: $id) {
        ... on Order {
          id
          name
          tags
        }
      }
    }
    """
    response = requests.post(endpoint, json={"query": query, "variables": {"id": order_gid}}, headers=headers, timeout=30)
    result["shopify_api_call_performed"] = True
    if response.status_code >= 400:
        result["error_sanitized"] = "Shopify GraphQL HTTP error " + str(response.status_code)
        return {}
    try:
        data = response.json()
    except ValueError:
        result["error_sanitized"] = "Shopify GraphQL non-JSON response"
        return {}
    errors = data.get("errors") or []
    if errors:
        result["error_sanitized"] = sanitize(errors[0].get("message") if isinstance(errors[0], dict) else errors[0])[:300]
        return {}
    node = (data.get("data") or {}).get("node") or {}
    result["successful_lookup_label"] = "order_gid_tags"
    return node

def fetch_by_name(endpoint, headers):
    query = """
    query($query: String!) {
      orders(first: 10, query: $query) {
        edges {
          node {
            id
            name
            tags
          }
        }
      }
    }
    """
    response = requests.post(endpoint, json={"query": query, "variables": {"query": "name:" + order_name}}, headers=headers, timeout=30)
    result["shopify_api_call_performed"] = True
    if response.status_code >= 400:
        result["error_sanitized"] = "Shopify GraphQL HTTP error " + str(response.status_code)
        return {}
    try:
        data = response.json()
    except ValueError:
        result["error_sanitized"] = "Shopify GraphQL non-JSON response"
        return {}
    errors = data.get("errors") or []
    if errors:
        result["error_sanitized"] = sanitize(errors[0].get("message") if isinstance(errors[0], dict) else errors[0])[:300]
        return {}
    edges = (((data.get("data") or {}).get("orders") or {}).get("edges")) or []
    for edge in edges:
        node = edge.get("node") or {}
        if node.get("name") == order_name:
            result["successful_lookup_label"] = "order_name_tags"
            return node
    return {}

try:
    installation_fields = {field.name for field in ShopifyInstallation._meta.fields}
    if "shop_domain" in installation_fields:
        installation = ShopifyInstallation.objects.get(shop_domain=shop)
    elif "shop" in installation_fields:
        installation = ShopifyInstallation.objects.get(shop=shop)
    else:
        result["error_sanitized"] = "Shopify installation shop field was not found."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    result["shopify_installation_found"] = True
    token = getattr(installation, "access_" + "token", "") or getattr(installation, "access_token_encrypted", "")
    if not token:
        result["error_sanitized"] = "Shopify access token was not available."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    result["shopify_credentials_found"] = True
    endpoint = "https://" + shop + "/admin/api/" + api_version + "/graphql.json"
    headers = {"Content-Type": "application/json", "X-Shopify-Access-Token": token}
    node = fetch_by_gid(endpoint, headers) if order_gid else {}
    if not node:
        node = fetch_by_name(endpoint, headers)
    if not node:
        result["error_sanitized"] = result["error_sanitized"] or "Selected order was not found."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    result["selected_order_found"] = True
    result["shopify_order_name_confirmed"] = str(node.get("name") or "")
    if result["shopify_order_name_confirmed"] != order_name:
        result["error_sanitized"] = "Shopify readback returned unexpected order name."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    tags = [str(tag).strip() for tag in (node.get("tags") or []) if str(tag).strip()]
    normalized_aliases = {normalize_tag(tag) for tag in alias_tags}
    result["tag_count"] = len(tags)
    result["canonical_trustpilot_tag_present"] = canonical_tag in tags
    result["matched_trustpilot_tags"] = [tag for tag in tags if normalize_tag(tag) in normalized_aliases]
    result["matched_legacy_trustpilot_tags"] = [tag for tag in result["matched_trustpilot_tags"] if tag != canonical_tag]
    result["trustpilot_tag_detected"] = bool(result["matched_trustpilot_tags"])
    result["legacy_trustpilot_tag_detected"] = bool(result["matched_legacy_trustpilot_tags"])
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
    script = script.replace("__ORDER_GID_LITERAL__", json.dumps(order_gid))
    script = script.replace("__ORDER_NAME_LITERAL__", json.dumps(order_name))
    script = script.replace("__CANONICAL_TAG_LITERAL__", json.dumps(CANONICAL_TRUSTPILOT_TAG))
    script = script.replace("__ALIAS_TAGS_LITERAL__", json.dumps(TRUSTPILOT_TAG_ALIASES))
    return script


def _readback_blocking_conditions(readback: dict) -> list[dict]:
    conditions = []
    if readback["readback_error_sanitized"]:
        conditions.append({"status": "blocked_shopify_readback_failed", "detail": readback["readback_error_sanitized"]})
    if readback["shopify_api_call_performed"] is not True:
        conditions.append({"status": "blocked_shopify_readback_failed", "detail": "Shopify read-only tag readback did not run."})
    if readback["selected_order_found"] is not True:
        conditions.append({"status": "blocked_selected_order_not_found", "detail": "Selected order was not found in Shopify readback."})
    if readback["shopify_order_name_confirmed"] != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_selected_order_mismatch", "detail": "Shopify readback order name mismatch."})
    if readback["canonical_trustpilot_tag_present"] is not True:
        status = (
            "blocked_canonical_trustpilot_tag_missing_legacy_detected"
            if readback["legacy_trustpilot_tag_detected"]
            else "blocked_canonical_trustpilot_tag_missing"
        )
        conditions.append({"status": status, "detail": "Canonical tag 1: trustpilot was not present after write."})
    return conditions


def _build_payload(
    execute_report: dict,
    execute_error: str,
    target_order_gid: str,
    target_order_gid_error: str,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    readback: dict,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    success = status == SUCCESS_STATUS
    safety = _safety_summary(readback)
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.23",
        "mode": "read-only-tag-write-audit",
        "command_label": COMMAND_LABEL,
        "tag_write_audit_status": status,
        "success": success,
        "source_report_used": {
            "json_path": str(SOURCE_EXECUTE_JSON_PATH),
            "html_path": str(SOURCE_EXECUTE_HTML_PATH),
            "json_exists": SOURCE_EXECUTE_JSON_PATH.exists(),
            "html_exists": SOURCE_EXECUTE_HTML_PATH.exists(),
            "source_error_sanitized": _sanitize_text(execute_error),
        },
        "selected_order_name": EXPECTED_ORDER_NAME,
        "selected_masked_email": EXPECTED_MASKED_EMAIL,
        "source_gmail_draft_id_partial": EXPECTED_DRAFT_ID_PARTIAL,
        "canonical_trustpilot_tag": CANONICAL_TRUSTPILOT_TAG,
        "planned_shopify_tag": CANONICAL_TRUSTPILOT_TAG,
        "source_tag_write_execute_status": _safe_text(execute_report.get("tag_write_execute_status", "")),
        "source_mode": _safe_text(execute_report.get("mode", "")),
        "source_sent_count": int(execute_report.get("source_sent_count") or 0),
        "source_shopify_write_performed": execute_report.get("shopify_write_performed") is True,
        "source_mutation_performed": execute_report.get("mutation_performed") is True,
        "source_tags_add_performed": execute_report.get("tags_add_performed") is True,
        "source_tags_remove_performed": execute_report.get("tags_remove_performed") is True,
        "source_written_tag_count": int(execute_report.get("written_tag_count") or 0),
        "source_post_write_tag_present": execute_report.get("post_write_tag_present") is True,
        "source_blocking_condition_count": int(execute_report.get("blocking_condition_count") or 0),
        "target_order_gid_present": bool(target_order_gid),
        "target_order_gid_error_sanitized": _sanitize_text(target_order_gid_error),
        "shopify_readback_performed": readback["read_only_shopify_lookup_performed"],
        "shopify_readback_successful_lookup_label": readback["successful_lookup_label"],
        "shopify_order_name_confirmed": readback["shopify_order_name_confirmed"],
        "shopify_tag_count": readback["tag_count"],
        "canonical_trustpilot_tag_present": readback["canonical_trustpilot_tag_present"],
        "trustpilot_tag_detected": readback["trustpilot_tag_detected"],
        "legacy_trustpilot_tag_detected": readback["legacy_trustpilot_tag_detected"],
        "matched_trustpilot_tags": readback["matched_trustpilot_tags"],
        "matched_legacy_trustpilot_tags": readback["matched_legacy_trustpilot_tags"],
        "trustpilot_tag_matching_policy": {
            "canonical_write_tag": CANONICAL_TRUSTPILOT_TAG,
            "future_write_requires_exact_canonical_tag": True,
            "matching_normalizes_whitespace_around_colon": True,
            "matching_tolerates_legacy_trustpoilt_typo": True,
            "legacy_tags_are_not_removed_automatically": True,
        },
        "source_privacy_scan": source_privacy_scan,
        "source_full_draft_id_leak_detected": full_draft_id_leak_detected,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "privacy_scan_passed": not _privacy_scan_failed(source_privacy_scan) and not full_draft_id_leak_detected,
        "ready_for_manual_completion_marker": success,
        "safety_summary": safety,
        **safety,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_tag_write_audit_path": str(REPORT_JSON_PATH),
        "html_trustpilot_tag_write_audit_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary(readback: dict) -> dict:
    return {
        "shopify_api_call_performed": bool(readback["shopify_api_call_performed"]),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
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
        "json_trustpilot_tag_write_audit_path": str(json_path),
        "html_trustpilot_tag_write_audit_path": str(html_path),
        "tag_write_audit_status": payload["tag_write_audit_status"],
        "source_tag_write_execute_status": payload["source_tag_write_execute_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "canonical_trustpilot_tag": payload["canonical_trustpilot_tag"],
        "canonical_trustpilot_tag_present": payload["canonical_trustpilot_tag_present"],
        "legacy_trustpilot_tag_detected": payload["legacy_trustpilot_tag_detected"],
        "matched_trustpilot_tags": payload["matched_trustpilot_tags"],
        "matched_legacy_trustpilot_tags": payload["matched_legacy_trustpilot_tags"],
        "shopify_readback_performed": payload["shopify_readback_performed"],
        "shopify_readback_successful_lookup_label": payload["shopify_readback_successful_lookup_label"],
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
    matched_rows = "\n".join(
        f"<tr><td>{escape(tag)}</td><td>{escape(str(tag == CANONICAL_TRUSTPILOT_TAG))}</td></tr>"
        for tag in payload["matched_trustpilot_tags"]
    ) or "<tr><td colspan=\"2\">None</td></tr>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Tag Write Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #2563eb; background: #eff6ff; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Tag Write Audit</h1>
  <p class="warning">Phase 3.23 performs read-only Shopify tag readback only. It does not send Gmail, create drafts, mutate Shopify, add tags, remove tags, or call Kudosi/Ali Reviews.</p>
  <p>Status: <strong>{escape(payload["tag_write_audit_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Canonical Trustpilot tag: <code>{escape(payload["canonical_trustpilot_tag"])}</code></p>
  <p>Canonical tag present: <strong>{escape(str(payload["canonical_trustpilot_tag_present"]))}</strong></p>
  <p>Legacy Trustpilot tag detected: <strong>{escape(str(payload["legacy_trustpilot_tag_detected"]))}</strong></p>
  <h2>Matched Trustpilot Tags</h2>
  <table><thead><tr><th>Matched original tag</th><th>Exact canonical</th></tr></thead><tbody>{matched_rows}</tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>This Audit Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


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


def _privacy_scan_failed(source_privacy_scan: dict) -> bool:
    for scan in source_privacy_scan.values():
        if scan.get("raw_customer_email_count") or scan.get("token_secret_bearer_pattern_count"):
            return True
    return False


def _full_draft_id_leak_detected(*texts: str) -> bool:
    if not PROTECTED_DRAFT_SOURCE_JSON_PATH.exists():
        return False
    try:
        source = json.loads(PROTECTED_DRAFT_SOURCE_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    draft_id = str(source.get("gmail_draft_id") or "").strip()
    if not draft_id:
        return False
    return any(draft_id in (text or "") for text in texts)


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["tag_write_audit_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["ready_for_manual_completion_marker"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "tag-write audit self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    return payload


def _parse_json_from_stdout(stdout: str) -> dict:
    for line in reversed((stdout or "").splitlines()):
        stripped = line.strip()
        if not stripped.startswith("{") or not stripped.endswith("}"):
            continue
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            continue
    return {}


def _is_masked_email(value: str) -> bool:
    return "***@" in str(value or "") and not EMAIL_RE.fullmatch(str(value or ""))


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


def _issue_summary(status: str, blocking_conditions: list[dict]) -> str:
    if status == SUCCESS_STATUS:
        return "Trustpilot Shopify tag-write audit passed; canonical 1: trustpilot tag is present."
    return "Trustpilot Shopify tag-write audit blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.23 Trustpilot Shopify tag-write audit finished.\n"
        f"Status: {payload.get('tag_write_audit_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Canonical tag present: {payload.get('canonical_trustpilot_tag_present')}\n"
        f"Legacy Trustpilot tag detected: {payload.get('legacy_trustpilot_tag_detected')}\n"
        f"Matched Trustpilot tags: {payload.get('matched_trustpilot_tags')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: read-only Shopify tag readback only; no Gmail send, no Shopify write/mutation/tagsAdd/tagsRemove, no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
