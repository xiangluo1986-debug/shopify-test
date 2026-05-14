import json
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_suppress_ali_reviews_design"
COMMAND_LABEL = "shopify_review_request_trustpilot_suppress_ali_reviews_design"

SOURCE_COMPLETION_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_completion_next_batch_design.json"
SOURCE_COMPLETION_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_completion_next_batch_design.html"
SOURCE_TAG_WRITE_AUDIT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_audit.json"
SOURCE_TAG_WRITE_AUDIT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_audit.html"
SOURCE_CANDIDATE_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_candidate_scan.json"
PROTECTED_DRAFT_SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_suppress_ali_reviews_design.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_suppress_ali_reviews_design.html"

SUCCESS_STATUS = "trustpilot_completed_order_ali_reviews_suppression_designed"
EXPECTED_COMPLETION_STATUS = "trustpilot_single_order_workflow_completed_next_batch_design_ready"
EXPECTED_TAG_WRITE_AUDIT_STATUS = "trustpilot_tag_write_audit_passed"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
CANONICAL_TRUSTPILOT_TAG = "1: trustpilot"
REVIEW_REQUEST_TAG_TO_REMOVE = "1: review request"
SUPPRESSION_CLASSIFICATION = "blocked_trustpilot_invitation_already_sent"
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


def run_shopify_review_request_trustpilot_suppress_ali_reviews_design_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completion_report, completion_error = _read_json_report(
        SOURCE_COMPLETION_JSON_PATH, "blocked_missing_completion_report"
    )
    tag_write_audit, tag_write_audit_error = _read_json_report(
        SOURCE_TAG_WRITE_AUDIT_JSON_PATH, "blocked_missing_tag_write_audit_report"
    )
    target_order_gid, target_order_gid_error = _target_order_gid_from_candidate_scan()
    source_privacy_scan = _source_privacy_scan()
    full_draft_id_leak = _source_full_draft_id_leak_detected()
    alias_coverage = _trustpilot_alias_coverage()
    base_conditions = _source_blocking_conditions(
        completion_report=completion_report,
        completion_error=completion_error,
        tag_write_audit=tag_write_audit,
        tag_write_audit_error=tag_write_audit_error,
        target_order_gid=target_order_gid,
        target_order_gid_error=target_order_gid_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        alias_coverage=alias_coverage,
    )
    readback = _shopify_tag_readback(base_conditions, target_order_gid)
    blocking_conditions = base_conditions if base_conditions else _readback_blocking_conditions(readback)
    status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        completion_report=completion_report,
        completion_error=completion_error,
        tag_write_audit=tag_write_audit,
        tag_write_audit_error=tag_write_audit_error,
        target_order_gid=target_order_gid,
        target_order_gid_error=target_order_gid_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        alias_coverage=alias_coverage,
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
    return "", "blocked_missing_order_gid_for_suppression_design"


def _walk_order_dicts(value):
    if isinstance(value, dict):
        if "order_name" in value:
            yield value
        for nested in value.values():
            yield from _walk_order_dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_order_dicts(item)


def _source_privacy_scan() -> dict:
    return {
        "completion_json": _privacy_scan_text(_read_text(SOURCE_COMPLETION_JSON_PATH)),
        "completion_html": _privacy_scan_text(_read_text(SOURCE_COMPLETION_HTML_PATH)),
        "tag_write_audit_json": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_AUDIT_JSON_PATH)),
        "tag_write_audit_html": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_AUDIT_HTML_PATH)),
    }


def _source_full_draft_id_leak_detected() -> bool:
    return _full_draft_id_leak_detected(
        _read_text(SOURCE_COMPLETION_JSON_PATH),
        _read_text(SOURCE_COMPLETION_HTML_PATH),
        _read_text(SOURCE_TAG_WRITE_AUDIT_JSON_PATH),
        _read_text(SOURCE_TAG_WRITE_AUDIT_HTML_PATH),
    )


def _source_blocking_conditions(
    completion_report: dict,
    completion_error: str,
    tag_write_audit: dict,
    tag_write_audit_error: str,
    target_order_gid: str,
    target_order_gid_error: str,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    alias_coverage: dict,
) -> list[dict]:
    conditions = []
    if completion_error:
        conditions.append({"status": "blocked_missing_completion_report", "detail": _sanitize_text(completion_error)})
    if tag_write_audit_error:
        conditions.append({"status": "blocked_missing_tag_write_audit_report", "detail": _sanitize_text(tag_write_audit_error)})
    if conditions:
        return conditions

    completion_summary = completion_report.get("completion_summary") if isinstance(completion_report.get("completion_summary"), dict) else {}
    if completion_report.get("completion_next_batch_design_status") != EXPECTED_COMPLETION_STATUS or completion_report.get("success") is not True:
        conditions.append({"status": "blocked_completion_report_not_ready", "detail": "Phase 3.24 completion report is not ready."})
    if completion_summary.get("already_completed_trustpilot_invitation") is not True:
        conditions.append({"status": "blocked_trustpilot_completion_not_confirmed", "detail": "Trustpilot invitation completion was not confirmed."})
    if int(completion_summary.get("trustpilot_gmail_sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "Trustpilot Gmail sent count must equal 1."})
    if completion_summary.get("email_sent_confirmed") is not True:
        conditions.append({"status": "blocked_email_not_sent", "detail": "email_sent_confirmed was not true."})
    if completion_summary.get("canonical_tag_present") is not True:
        conditions.append({"status": "blocked_canonical_trustpilot_tag_missing", "detail": "completion report does not confirm canonical Trustpilot tag."})
    if completion_summary.get("post_write_audit_passed") is not True:
        conditions.append({"status": "blocked_tag_write_audit_not_passed", "detail": "completion report does not confirm post-write audit."})
    if completion_summary.get("shopify_tag_written") != CANONICAL_TRUSTPILOT_TAG:
        conditions.append({"status": "blocked_trustpilot_tag_value_mismatch", "detail": "completion report Shopify tag is not canonical."})
    if int(completion_summary.get("written_tag_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_written_tag_count", "detail": "written_tag_count must equal 1."})
    if completion_summary.get("no_gmail_second_send_performed") is not True:
        conditions.append({"status": "blocked_gmail_second_send_detected", "detail": "completion report does not confirm no second Gmail send."})
    if completion_summary.get("no_kudosi_ali_reviews_call") is not True:
        conditions.append({"status": "blocked_kudosi_or_ali_reviews_detected", "detail": "completion report does not confirm no Kudosi/Ali Reviews call."})

    if tag_write_audit.get("tag_write_audit_status") != EXPECTED_TAG_WRITE_AUDIT_STATUS or tag_write_audit.get("success") is not True:
        conditions.append({"status": "blocked_tag_write_audit_not_passed", "detail": "Phase 3.23 tag-write audit did not pass."})
    if tag_write_audit.get("canonical_trustpilot_tag_present") is not True:
        conditions.append({"status": "blocked_canonical_trustpilot_tag_missing", "detail": "tag-write audit does not confirm canonical Trustpilot tag."})
    if tag_write_audit.get("trustpilot_tag_detected") is not True:
        conditions.append({"status": "blocked_trustpilot_invitation_tag_not_detected", "detail": "tag-write audit did not detect a Trustpilot tag alias."})

    for label, report in {"completion": completion_report, "tag_write_audit": tag_write_audit}.items():
        if _safe_text(report.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
            conditions.append({"status": "blocked_selected_order_mismatch", "detail": f"{label} selected_order_name mismatch."})
        masked_email = _safe_text(report.get("selected_masked_email", ""))
        if masked_email != EXPECTED_MASKED_EMAIL or not _is_masked_email(masked_email):
            conditions.append({"status": "blocked_unmasked_email_detected", "detail": f"{label} selected_masked_email mismatch or unmasked."})
        if _safe_text(report.get("source_gmail_draft_id_partial", "")) != EXPECTED_DRAFT_ID_PARTIAL:
            conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": f"{label} Gmail draft id partial mismatch."})

    if int(completion_report.get("blocking_condition_count") or 0) != 0 or int(tag_write_audit.get("blocking_condition_count") or 0) != 0:
        conditions.append({"status": "blocked_source_has_blocking_conditions", "detail": "A source report has blocking conditions."})
    if not target_order_gid or target_order_gid_error:
        conditions.append({"status": "blocked_missing_order_gid_for_suppression_design", "detail": _sanitize_text(target_order_gid_error)})
    if not alias_coverage["all_required_aliases_present"]:
        conditions.append({"status": "blocked_trustpilot_alias_coverage_incomplete", "detail": "Trustpilot alias list is incomplete."})
    if _privacy_scan_failed(source_privacy_scan) or full_draft_id_leak_detected:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source JSON/HTML privacy scan failed."})
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
        "trustpilot_tag_detected": False,
        "canonical_trustpilot_tag_present": False,
        "legacy_trustpilot_tag_detected": False,
        "matched_trustpilot_tags": [],
        "matched_legacy_trustpilot_tags": [],
        "review_request_tag_present": False,
        "review_request_tag_to_remove": REVIEW_REQUEST_TAG_TO_REMOVE,
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
                "trustpilot_tag_detected": bool(parsed.get("trustpilot_tag_detected")),
                "canonical_trustpilot_tag_present": bool(parsed.get("canonical_trustpilot_tag_present")),
                "legacy_trustpilot_tag_detected": bool(parsed.get("legacy_trustpilot_tag_detected")),
                "matched_trustpilot_tags": [_safe_text(tag) for tag in parsed.get("matched_trustpilot_tags", [])],
                "matched_legacy_trustpilot_tags": [
                    _safe_text(tag) for tag in parsed.get("matched_legacy_trustpilot_tags", [])
                ],
                "review_request_tag_present": bool(parsed.get("review_request_tag_present")),
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
review_request_tag = __REVIEW_REQUEST_TAG_LITERAL__
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
    "trustpilot_tag_detected": False,
    "canonical_trustpilot_tag_present": False,
    "legacy_trustpilot_tag_detected": False,
    "matched_trustpilot_tags": [],
    "matched_legacy_trustpilot_tags": [],
    "review_request_tag_present": False,
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
    node = fetch_by_gid(endpoint, headers)
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
    result["review_request_tag_present"] = review_request_tag in tags
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
    script = script.replace("__REVIEW_REQUEST_TAG_LITERAL__", json.dumps(REVIEW_REQUEST_TAG_TO_REMOVE))
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
    if readback["trustpilot_tag_detected"] is not True or readback["canonical_trustpilot_tag_present"] is not True:
        conditions.append({"status": "blocked_trustpilot_invitation_tag_not_detected", "detail": "Shopify readback did not confirm canonical Trustpilot tag."})
    return conditions


def _trustpilot_alias_coverage() -> dict:
    required = {
        "1: trustpilot",
        "1: trustpoilt",
        "1:trustpilot",
        "1 : trustpilot",
        "1:trustpoilt",
        "1 : trustpoilt",
    }
    normalized_required = {_normalize_tag(tag) for tag in required}
    normalized_configured = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    return {
        "required_aliases": sorted(required),
        "configured_aliases": TRUSTPILOT_TAG_ALIASES,
        "normalized_required_aliases": sorted(normalized_required),
        "normalized_configured_aliases": sorted(normalized_configured),
        "all_required_aliases_present": normalized_required.issubset(normalized_configured),
        "trustpoilt_typo_covered": _normalize_tag("1: trustpoilt") in normalized_configured,
        "colon_spacing_variants_covered": all(
            _normalize_tag(tag) in normalized_configured
            for tag in ("1:trustpilot", "1 : trustpilot", "1:trustpoilt", "1 : trustpoilt")
        ),
    }


def _normalize_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text)


def _build_payload(
    completion_report: dict,
    completion_error: str,
    tag_write_audit: dict,
    tag_write_audit_error: str,
    target_order_gid: str,
    target_order_gid_error: str,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    alias_coverage: dict,
    readback: dict,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    success = status == SUCCESS_STATUS
    safety = _safety_summary(readback)
    review_request_tag_present = bool(readback["review_request_tag_present"])
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "4.0A",
        "mode": "trustpilot-suppresses-ali-reviews-design-dry-run",
        "command_label": COMMAND_LABEL,
        "trustpilot_suppress_ali_reviews_design_status": status,
        "success": success,
        "selected_order_name": EXPECTED_ORDER_NAME,
        "selected_masked_email": EXPECTED_MASKED_EMAIL,
        "source_gmail_draft_id_partial": EXPECTED_DRAFT_ID_PARTIAL,
        "classification": SUPPRESSION_CLASSIFICATION,
        "trustpilot_completed_order": success,
        "trustpilot_invitation_sent": success,
        "canonical_trustpilot_tag": CANONICAL_TRUSTPILOT_TAG,
        "trustpilot_tag_alias_detected": bool(readback["trustpilot_tag_detected"]),
        "canonical_trustpilot_tag_present": bool(readback["canonical_trustpilot_tag_present"]),
        "legacy_trustpilot_tag_detected": bool(readback["legacy_trustpilot_tag_detected"]),
        "matched_trustpilot_tags": readback["matched_trustpilot_tags"],
        "matched_legacy_trustpilot_tags": readback["matched_legacy_trustpilot_tags"],
        "ali_reviews_invitation_allowed": False,
        "kudosi_invitation_allowed": False,
        "ali_reviews_request_created": False,
        "kudosi_request_created": False,
        "product_review_invitation_sent": False,
        "review_request_tag_present": review_request_tag_present,
        "would_remove_review_request_tag": review_request_tag_present,
        "planned_remove_tag": REVIEW_REQUEST_TAG_TO_REMOVE,
        "planned_shopify_tag_cleanup_action": (
            f'remove tag "{REVIEW_REQUEST_TAG_TO_REMOVE}", dry-run only'
            if review_request_tag_present
            else "no cleanup needed; exact review request tag is absent"
        ),
        "future_real_remove_tag_gates": {
            "TRUSTPILOT_SUPPRESS_ALI_REVIEWS_REMOVE_TAG": "1",
            "TRUSTPILOT_SUPPRESS_ALI_REVIEWS_REMOVE_TAG_MAX": "1",
            "TRUSTPILOT_SUPPRESS_ALI_REVIEWS_REMOVE_TAG_ACK": "YES_I_APPROVE_REMOVING_ONE_REVIEW_REQUEST_TAG",
            "DRY_RUN": "0",
            "target_order_name": EXPECTED_ORDER_NAME,
            "exact_tag_to_remove": REVIEW_REQUEST_TAG_TO_REMOVE,
        },
        "future_real_remove_constraints": {
            "max_orders": 1,
            "max_tags": 1,
            "tagsRemove_only_for_exact_planned_tag": True,
            "no_tagsAdd": True,
            "no_gmail_send": True,
            "no_kudosi_or_ali_reviews_call": True,
            "post_remove_audit_required": True,
        },
        "trustpilot_tag_matching_policy": {
            "canonical_write_tag": CANONICAL_TRUSTPILOT_TAG,
            "future_write_requires_exact_canonical_tag": True,
            "matching_normalizes_whitespace_around_colon": True,
            "matching_tolerates_legacy_trustpoilt_typo": True,
            "legacy_tags_are_not_removed_automatically": True,
            **alias_coverage,
        },
        "source_reports_used": {
            "completion_json_path": str(SOURCE_COMPLETION_JSON_PATH),
            "tag_write_audit_json_path": str(SOURCE_TAG_WRITE_AUDIT_JSON_PATH),
            "completion_error_sanitized": _sanitize_text(completion_error),
            "tag_write_audit_error_sanitized": _sanitize_text(tag_write_audit_error),
        },
        "source_statuses": {
            "completion_next_batch_design_status": _safe_text(completion_report.get("completion_next_batch_design_status", "")),
            "tag_write_audit_status": _safe_text(tag_write_audit.get("tag_write_audit_status", "")),
        },
        "target_order_gid_present": bool(target_order_gid),
        "target_order_gid_error_sanitized": _sanitize_text(target_order_gid_error),
        "shopify_readback_performed": bool(readback["read_only_shopify_lookup_performed"]),
        "shopify_readback_successful_lookup_label": readback["successful_lookup_label"],
        "shopify_order_name_confirmed": readback["shopify_order_name_confirmed"],
        "shopify_tag_count": readback["tag_count"],
        "source_privacy_scan": source_privacy_scan,
        "source_full_draft_id_leak_detected": full_draft_id_leak_detected,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "privacy_scan_passed": not _privacy_scan_failed(source_privacy_scan) and not full_draft_id_leak_detected,
        "safety_summary": safety,
        **safety,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_suppress_ali_reviews_design_path": str(REPORT_JSON_PATH),
        "html_trustpilot_suppress_ali_reviews_design_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions, review_request_tag_present),
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
        "ali_reviews_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_suppress_ali_reviews_design_path": str(json_path),
        "html_trustpilot_suppress_ali_reviews_design_path": str(html_path),
        "trustpilot_suppress_ali_reviews_design_status": payload["trustpilot_suppress_ali_reviews_design_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "classification": payload["classification"],
        "trustpilot_completed_order": payload["trustpilot_completed_order"],
        "trustpilot_invitation_sent": payload["trustpilot_invitation_sent"],
        "canonical_trustpilot_tag_present": payload["canonical_trustpilot_tag_present"],
        "matched_trustpilot_tags": payload["matched_trustpilot_tags"],
        "ali_reviews_invitation_allowed": payload["ali_reviews_invitation_allowed"],
        "kudosi_invitation_allowed": payload["kudosi_invitation_allowed"],
        "review_request_tag_present": payload["review_request_tag_present"],
        "would_remove_review_request_tag": payload["would_remove_review_request_tag"],
        "planned_remove_tag": payload["planned_remove_tag"],
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
    gate_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td><code>{escape(str(value))}</code></td></tr>"
        for key, value in payload["future_real_remove_tag_gates"].items()
    )
    alias_rows = "\n".join(
        f"<tr><td><code>{escape(alias)}</code></td><td><code>{escape(_normalize_tag(alias))}</code></td></tr>"
        for alias in payload["trustpilot_tag_matching_policy"]["configured_aliases"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Suppresses Ali Reviews Design</title>
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
  <h1>Trustpilot Suppresses Ali Reviews Design</h1>
  <p class="warning">Phase 4.0A is dry-run/design only. No Ali Reviews/Kudosi request, Gmail action, Shopify mutation, tagsAdd, or tagsRemove was performed.</p>
  <p>Status: <strong>{escape(payload["trustpilot_suppress_ali_reviews_design_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Classification: <code>{escape(payload["classification"])}</code></p>
  <p>Ali Reviews invitation allowed: <strong>{escape(str(payload["ali_reviews_invitation_allowed"]))}</strong></p>
  <p>Kudosi invitation allowed: <strong>{escape(str(payload["kudosi_invitation_allowed"]))}</strong></p>
  <p>Review request tag present: <strong>{escape(str(payload["review_request_tag_present"]))}</strong></p>
  <p>Would remove review request tag: <strong>{escape(str(payload["would_remove_review_request_tag"]))}</strong></p>
  <p>Planned remove tag: <code>{escape(payload["planned_remove_tag"])}</code></p>
  <h2>Future Remove Tag Gates</h2>
  <table><tbody>{gate_rows}</tbody></table>
  <h2>Trustpilot Alias Matching</h2>
  <table><thead><tr><th>Alias</th><th>Normalized form</th></tr></thead><tbody>{alias_rows}</tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>This Task Safety Flags</h2>
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
        payload["trustpilot_suppress_ali_reviews_design_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["ali_reviews_invitation_allowed"] = False
        payload["kudosi_invitation_allowed"] = False
        payload["would_remove_review_request_tag"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "suppression design self privacy scan failed."}
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


def _issue_summary(status: str, blocking_conditions: list[dict], review_request_tag_present: bool) -> str:
    if status == SUCCESS_STATUS:
        if review_request_tag_present:
            return "Trustpilot completion blocks Ali/Kudosi; exact review request tag cleanup is designed but not performed."
        return "Trustpilot completion blocks Ali/Kudosi; exact review request tag is absent, so no cleanup is needed."
    return "Trustpilot suppress Ali Reviews design blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 4.0A Trustpilot suppresses Ali Reviews design finished.\n"
        f"Status: {payload.get('trustpilot_suppress_ali_reviews_design_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Classification: {payload.get('classification')}\n"
        f"Ali Reviews allowed: {payload.get('ali_reviews_invitation_allowed')}\n"
        f"Kudosi allowed: {payload.get('kudosi_invitation_allowed')}\n"
        f"Review request tag present: {payload.get('review_request_tag_present')}\n"
        f"Would remove review request tag: {payload.get('would_remove_review_request_tag')}\n"
        f"Planned remove tag: {payload.get('planned_remove_tag')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Ali Reviews/Kudosi request, no Gmail action, no Shopify mutation/tagsAdd/tagsRemove.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
