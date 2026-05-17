import json
import re
import sqlite3
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_order_tags_persistence_audit"
COMMAND_LABEL = "shopify_review_request_order_tags_persistence_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_order_tags_persistence_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_order_tags_persistence_audit.html"
MIGRATION_PATH = PROJECT_ROOT / "backend" / "shopify_sync" / "migrations" / "0029_shopifyorder_shopify_tags.py"
SQLITE_DB_PATH = PROJECT_ROOT / "backend" / "db.sqlite3"
LAST_60_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_ORDER_TAGS_PERSISTENCE_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_ORDER_TAGS_PERSISTENCE_AUDIT_JSON_END"

SHOPIFY_ORDER_TAG_FIELD = "shopify_tags"
SHOPIFY_ORDER_TAG_FIELD_LABEL = "ShopifyOrder.shopify_tags"
SHOPIFY_ORDER_TAGS_EMPTY_SOURCE = "Shopify response had no order tags"
SHOPIFY_ORDER_TAGS_MISSING_SOURCE = "ShopifyOrder.shopify_tags is not populated by local sync"
SHOPIFY_ORDER_TAGS_FIELD_MISSING_SOURCE = "Local ShopifyOrder tag field is missing; apply the shopify_tags migration"

REVIEW_REQUEST_TAG_ALIASES = [
    "1: review request",
    "1: reveiw request",
    "1:review request",
    "1 : review request",
    "1:reveiw request",
    "1 : reveiw request",
]
DELIVERED_TAG_ALIASES = ["Delivered", "delivered"]
TRUSTPILOT_SENT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=])"
)


def run_shopify_review_request_order_tags_persistence_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_audit()
    if completed["success"]:
        payload = completed["payload"]
        payload["django_audit_source"] = "django"
    else:
        payload = _fallback_payload(completed)

    payload["migration_added"] = MIGRATION_PATH.exists()
    payload["migration_path"] = str(MIGRATION_PATH.relative_to(PROJECT_ROOT))
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["tag_alias_detection_results"] = _tag_alias_detection_results()
    payload.update(_safety_flags())
    payload["privacy_scan_summary"] = _privacy_scan(payload)
    payload["detected_issue_summary"] = _issue_summary(payload)

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_audit() -> dict:
    script = "\n".join(
        [
            "import json",
            "import re",
            "from django.db import connection",
            "from django.db.models import Q",
            "from shopify_sync.models import ShopifyOrder",
            "from shopify_sync.review_request_workbench import build_review_request_last_60_days_candidate_scan_report",
            f"TAG_FIELD = '{SHOPIFY_ORDER_TAG_FIELD}'",
            "REVIEW_ALIASES = ['1: review request', '1: reveiw request', '1:review request', '1 : review request', '1:reveiw request', '1 : reveiw request']",
            "DELIVERED_ALIASES = ['Delivered', 'delivered']",
            "TRUSTPILOT_ALIASES = ['1: trustpilot', '1: trustpoilt', '1:trustpilot', '1 : trustpilot', '1:trustpoilt', '1 : trustpoilt']",
            "def norm(value):",
            "    return re.sub(r'\\s+', '', str(value or '').strip().lower())",
            "def split_tags(value):",
            "    return [part.strip()[:120] for part in str(value or '').split(',') if part.strip()]",
            "def has_alias(tags, aliases):",
            "    normalized = {norm(alias) for alias in aliases}",
            "    return any(norm(tag) in normalized for tag in tags)",
            "def matched_alias(tags, aliases):",
            "    normalized = {norm(alias) for alias in aliases}",
            "    for tag in tags:",
            "        if norm(tag) in normalized:",
            "            return tag",
            "    return ''",
            "columns = {column.name for column in connection.introspection.get_table_description(connection.cursor(), ShopifyOrder._meta.db_table)}",
            "db_tag_field_exists = TAG_FIELD in columns",
            "model_tag_field_exists = any(field.name == TAG_FIELD for field in ShopifyOrder._meta.fields)",
            "def lookup_order(order_name):",
            "    raw = str(order_name).strip().lstrip('#')",
            "    query = Q(order_name__in=[order_name, raw, '#' + raw]) | Q(order_number__in=[raw])",
            "    if raw.isdigit():",
            "        query |= Q(shopify_order_id=int(raw))",
            "    values = ['id', 'order_name', 'order_number', 'shopify_order_id']",
            "    if db_tag_field_exists:",
            "        values.append(TAG_FIELD)",
            "    row = ShopifyOrder.objects.filter(query).values(*values).first()",
            "    if not row:",
            "        return {'order_name': order_name, 'found': False, 'tag_field_data_available': False, 'tag_field_value_present': False, 'tags': [], 'tags_summary': 'Order not found in local ShopifyOrder data', 'tag_data_missing_source': 'order_not_found_in_local_shopify_order', 'review_request_tag_detected': False, 'matched_review_request_tag_value': ''}",
            "    raw_tags = row.get(TAG_FIELD) if db_tag_field_exists else None",
            "    tag_data_available = db_tag_field_exists and raw_tags is not None",
            "    tags = split_tags(raw_tags) if tag_data_available else []",
            "    missing_source = '' if tag_data_available else ('Local ShopifyOrder tag field is missing; apply the shopify_tags migration' if not db_tag_field_exists else 'ShopifyOrder.shopify_tags is not populated by local sync')",
            "    tags_summary = ', '.join(tags) if tags else ('Shopify response had no order tags' if tag_data_available else 'Shopify tag data not loaded')",
            "    return {'order_name': order_name, 'found': True, 'matched_order_name': row.get('order_name') or '', 'local_order_id': row.get('id') or '', 'tag_field_data_available': tag_data_available, 'tag_field_value_present': bool(str(raw_tags or '').strip()), 'tags': tags, 'tags_summary': tags_summary, 'tag_data_missing_source': missing_source, 'review_request_tag_detected': has_alias(tags, REVIEW_ALIASES), 'matched_review_request_tag_value': matched_alias(tags, REVIEW_ALIASES), 'delivered_tag_detected': has_alias(tags, DELIVERED_ALIASES), 'trustpilot_sent_tag_detected': has_alias(tags, TRUSTPILOT_ALIASES)}",
            "scan = build_review_request_last_60_days_candidate_scan_report({})",
            "payload = {'timestamp': __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat(), 'task': 'shopify_review_request_order_tags_persistence_audit', 'task_name': 'shopify_review_request_order_tags_persistence_audit', 'phase': '5.28F', 'mode': 'dry-run-local-order-tags-persistence-audit', 'command_label': 'shopify_review_request_order_tags_persistence_audit_local_only', 'report_status': 'order_tags_persistence_audit_ready', 'success': True, 'selected_local_tag_field': 'ShopifyOrder.shopify_tags', 'model_tag_field_exists': model_tag_field_exists, 'database_tag_field_exists': db_tag_field_exists, 'order_22530': lookup_order('#22530'), 'order_22562': lookup_order('#22562'), 'order_22530_diagnosis': scan.get('order_22530_diagnosis') or {}, 'eligible_candidate_count_after_tag_availability': int(scan.get('eligible_candidate_count') or 0), 'blocked_count_after_tag_availability': int(scan.get('blocked_count') or 0), 'scan_source': scan.get('scan_source', ''), 'coverage_warnings': scan.get('coverage_warnings') or []}",
            f"print('{JSON_BEGIN}')",
            "print(json.dumps(payload, ensure_ascii=False, sort_keys=True))",
            f"print('{JSON_END}')",
        ]
    )
    command = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", script]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=False,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
    except FileNotFoundError:
        return _failed_run("docker_command_not_found", 127, "", "Docker command was not found.")
    except PermissionError:
        return _failed_run("docker_permission_denied", 126, "", "Docker permission denied.")
    except subprocess.TimeoutExpired as exc:
        return _failed_run("timeout", 124, _to_text(exc.stdout), _to_text(exc.stderr))

    stdout = _to_text(completed.stdout)
    stderr = _to_text(completed.stderr)
    payload = _extract_payload(stdout)
    if completed.returncode != 0:
        return _failed_run("django_local_audit_failed", completed.returncode, stdout, stderr)
    if not payload:
        return _failed_run("audit_payload_missing", 1, stdout, stderr)
    return {"success": True, "exit_code": 0, "payload": payload}


def _fallback_payload(result: dict) -> dict:
    sqlite_payload = _sqlite_fallback_payload(result)
    if sqlite_payload:
        return sqlite_payload
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28F",
        "mode": "dry-run-local-order-tags-persistence-audit-fallback",
        "command_label": COMMAND_LABEL,
        "report_status": "blocked_order_tags_persistence_audit_failed",
        "success": False,
        "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
        "model_tag_field_exists": None,
        "database_tag_field_exists": None,
        "order_22530": _empty_order_audit("#22530"),
        "order_22562": _empty_order_audit("#22562"),
        "order_22530_diagnosis": {
            "order_name": "#22530",
            "found_in_local_shopify_order": False,
            "tag_data_available": False,
            "message": "Local Django audit failed before #22530 tag persistence could be checked.",
        },
        "eligible_candidate_count_after_tag_availability": 0,
        "blocked_count_after_tag_availability": 0,
        "scan_source": "unavailable",
        "coverage_warnings": ["order_tags_persistence_audit_failed"],
        "django_audit_failure_type": _safe_text(result.get("failure_type", "")),
        "django_audit_exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(_sanitize_text(result.get("stdout", ""))),
        "stderr_tail_sanitized": _tail(_sanitize_text(result.get("stderr", ""))),
    }


def _sqlite_fallback_payload(result: dict) -> dict:
    if not SQLITE_DB_PATH.exists():
        return {}
    try:
        connection = sqlite3.connect(SQLITE_DB_PATH)
        connection.row_factory = sqlite3.Row
        try:
            columns = {row[1] for row in connection.execute("PRAGMA table_info(shopify_sync_shopifyorder)").fetchall()}
            if not columns:
                return {}
            db_tag_field_exists = SHOPIFY_ORDER_TAG_FIELD in columns
            selected_columns = ["id", "order_name", "order_number", "shopify_order_id"]
            if db_tag_field_exists:
                selected_columns.append(SHOPIFY_ORDER_TAG_FIELD)
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT " + ", ".join(selected_columns) + " FROM shopify_sync_shopifyorder"
                ).fetchall()
            ]
        finally:
            connection.close()
    except Exception:
        return {}

    scan = _read_json(LAST_60_SCAN_JSON_PATH)
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28F",
        "mode": "dry-run-local-order-tags-persistence-audit-sqlite-fallback",
        "command_label": COMMAND_LABEL,
        "report_status": "order_tags_persistence_audit_ready_sqlite_fallback",
        "success": True,
        "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
        "model_tag_field_exists": MIGRATION_PATH.exists(),
        "database_tag_field_exists": db_tag_field_exists,
        "order_22530": _sqlite_order_audit("#22530", rows, db_tag_field_exists),
        "order_22562": _sqlite_order_audit("#22562", rows, db_tag_field_exists),
        "order_22530_diagnosis": scan.get("order_22530_diagnosis") or {},
        "eligible_candidate_count_after_tag_availability": int(scan.get("eligible_candidate_count") or 0),
        "blocked_count_after_tag_availability": int(scan.get("blocked_count") or 0),
        "scan_source": scan.get("scan_source", "sqlite_fallback_no_scan_report"),
        "coverage_warnings": scan.get("coverage_warnings") or ["django_audit_unavailable_sqlite_fallback_used"],
        "django_audit_failure_type": _safe_text(result.get("failure_type", "")),
        "django_audit_exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(_sanitize_text(result.get("stdout", ""))),
        "stderr_tail_sanitized": _tail(_sanitize_text(result.get("stderr", ""))),
    }


def _sqlite_order_audit(order_name: str, rows: list[dict], db_tag_field_exists: bool) -> dict:
    row = _find_sqlite_order(order_name, rows)
    if not row:
        return {
            "order_name": order_name,
            "found": False,
            "tag_field_data_available": False,
            "tag_field_value_present": False,
            "tags": [],
            "tags_summary": "Order not found in local ShopifyOrder data",
            "tag_data_missing_source": "order_not_found_in_local_shopify_order",
            "review_request_tag_detected": False,
            "matched_review_request_tag_value": "",
            "delivered_tag_detected": False,
            "trustpilot_sent_tag_detected": False,
        }

    raw_tags = row.get(SHOPIFY_ORDER_TAG_FIELD) if db_tag_field_exists else None
    tag_data_available = db_tag_field_exists and raw_tags is not None
    tags = _split_tag_string(raw_tags) if tag_data_available else []
    return {
        "order_name": order_name,
        "found": True,
        "matched_order_name": _safe_text(row.get("order_name"), 80),
        "local_order_id": row.get("id", ""),
        "tag_field_data_available": tag_data_available,
        "tag_field_value_present": bool(str(raw_tags or "").strip()),
        "tags": tags,
        "tags_summary": _tags_summary(tags, tag_data_available),
        "tag_data_missing_source": ""
        if tag_data_available
        else (
            SHOPIFY_ORDER_TAGS_FIELD_MISSING_SOURCE
            if not db_tag_field_exists
            else SHOPIFY_ORDER_TAGS_MISSING_SOURCE
        ),
        "review_request_tag_detected": _has_alias(tags, REVIEW_REQUEST_TAG_ALIASES),
        "matched_review_request_tag_value": _matched_alias(tags, REVIEW_REQUEST_TAG_ALIASES),
        "delivered_tag_detected": _has_alias(tags, DELIVERED_TAG_ALIASES),
        "trustpilot_sent_tag_detected": _has_alias(tags, TRUSTPILOT_SENT_TAG_ALIASES),
    }


def _find_sqlite_order(order_name: str, rows: list[dict]) -> dict:
    canonical = _canonical_order_name(order_name)
    raw = canonical.lstrip("#")
    for row in rows:
        if _canonical_order_name(row.get("order_name")) == canonical:
            return row
        if raw and str(row.get("order_number") or "").lstrip("#") == raw:
            return row
        if raw and str(row.get("shopify_order_id") or "") == raw:
            return row
    return {}


def _empty_order_audit(order_name: str) -> dict:
    return {
        "order_name": order_name,
        "found": False,
        "tag_field_data_available": False,
        "tag_field_value_present": False,
        "tags": [],
        "tags_summary": "Shopify tag data not loaded",
        "tag_data_missing_source": SHOPIFY_ORDER_TAGS_MISSING_SOURCE,
        "review_request_tag_detected": False,
        "matched_review_request_tag_value": "",
        "delivered_tag_detected": False,
        "trustpilot_sent_tag_detected": False,
    }


def _extract_payload(stdout: str) -> dict:
    if JSON_BEGIN not in stdout or JSON_END not in stdout:
        return {}
    fragment = stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0].strip()
    try:
        payload = json.loads(fragment)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _failed_run(failure_type: str, exit_code: int, stdout: str, stderr: str) -> dict:
    return {
        "success": False,
        "exit_code": exit_code,
        "failure_type": failure_type,
        "stdout": _sanitize_text(stdout),
        "stderr": _sanitize_text(stderr),
    }


def _tag_alias_detection_results() -> dict:
    return {
        "review_request_aliases": _alias_rows(REVIEW_REQUEST_TAG_ALIASES, REVIEW_REQUEST_TAG_ALIASES),
        "delivered_aliases": _alias_rows(DELIVERED_TAG_ALIASES, DELIVERED_TAG_ALIASES),
        "trustpilot_sent_aliases": _alias_rows(TRUSTPILOT_SENT_TAG_ALIASES, TRUSTPILOT_SENT_TAG_ALIASES),
    }


def _alias_rows(values: list[str], aliases: list[str]) -> list[dict]:
    normalized_aliases = {_normalize_tag(alias) for alias in aliases}
    return [
        {
            "tag_value": _safe_text(value, 120),
            "detected": _normalize_tag(value) in normalized_aliases,
        }
        for value in values
    ]


def _normalize_tag(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _has_alias(tags: list[str], aliases: list[str]) -> bool:
    normalized_aliases = {_normalize_tag(alias) for alias in aliases}
    return any(_normalize_tag(tag) in normalized_aliases for tag in tags)


def _matched_alias(tags: list[str], aliases: list[str]) -> str:
    normalized_aliases = {_normalize_tag(alias) for alias in aliases}
    for tag in tags:
        if _normalize_tag(tag) in normalized_aliases:
            return tag
    return ""


def _split_tag_string(value) -> list[str]:
    return [_safe_text(part, 120) for part in str(value or "").split(",") if _safe_text(part, 120)]


def _tags_summary(tags: list[str], tag_data_available: bool) -> str:
    if tags:
        return ", ".join(tags)
    if tag_data_available:
        return SHOPIFY_ORDER_TAGS_EMPTY_SOURCE
    return "Shopify tag data not loaded"


def _canonical_order_name(value) -> str:
    text = _safe_text(value, 80)
    match = re.fullmatch(r"#?(\d{3,})", text)
    return f"#{match.group(1)}" if match else text


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _safety_flags() -> dict:
    return {
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=True, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    order_22530 = payload.get("order_22530") or {}
    order_22562 = payload.get("order_22562") or {}
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "exit_code": 0 if payload.get("success") is True else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "report_status": payload.get("report_status", ""),
        "selected_local_tag_field": payload.get("selected_local_tag_field", ""),
        "migration_added": payload.get("migration_added") is True,
        "order_22530_tag_field_value_present": order_22530.get("tag_field_value_present") is True,
        "order_22530_review_request_tag_detected": order_22530.get("review_request_tag_detected") is True,
        "order_22562_review_request_tag_detected": order_22562.get("review_request_tag_detected") is True,
        "eligible_candidate_count_after_tag_availability": int(
            payload.get("eligible_candidate_count_after_tag_availability") or 0
        ),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    order_22530 = payload.get("order_22530") or {}
    order_22562 = payload.get("order_22562") or {}
    return (
        "Review Request Shopify order tag persistence audit completed.\n"
        f"Result: {payload.get('report_status')}\n"
        f"Local tag field: {payload.get('selected_local_tag_field')}\n"
        f"Migration added: {payload.get('migration_added') is True}\n"
        f"#22530 tags: {order_22530.get('tags_summary', '')}\n"
        f"#22530 review request tag detected: {order_22530.get('review_request_tag_detected') is True}\n"
        f"#22562 tags: {order_22562.get('tags_summary', '')}\n"
        f"Eligible candidates after tag availability: {payload.get('eligible_candidate_count_after_tag_availability', 0)}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "0 = stop"
    )


def _render_html(payload: dict) -> str:
    order_22530 = payload.get("order_22530") or {}
    order_22562 = payload.get("order_22562") or {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Order Tags Persistence Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
  </style>
</head>
<body>
  <h1>Review Request Order Tags Persistence Audit</h1>
  <table><tbody>
    <tr><th>Status</th><td>{escape(str(payload.get("report_status", "")))}</td></tr>
    <tr><th>Local tag field</th><td>{escape(str(payload.get("selected_local_tag_field", "")))}</td></tr>
    <tr><th>Migration added</th><td>{escape(str(payload.get("migration_added") is True))}</td></tr>
    <tr><th>#22530 tag field value present</th><td>{escape(str(order_22530.get("tag_field_value_present") is True))}</td></tr>
    <tr><th>#22530 tags summary</th><td>{escape(str(order_22530.get("tags_summary", "")))}</td></tr>
    <tr><th>#22530 review request tag detected</th><td>{escape(str(order_22530.get("review_request_tag_detected") is True))}</td></tr>
    <tr><th>#22562 tags summary</th><td>{escape(str(order_22562.get("tags_summary", "")))}</td></tr>
    <tr><th>#22562 review request tag detected</th><td>{escape(str(order_22562.get("review_request_tag_detected") is True))}</td></tr>
    <tr><th>Eligible candidate count</th><td>{escape(str(payload.get("eligible_candidate_count_after_tag_availability", 0)))}</td></tr>
  </tbody></table>
  <h2>Safety</h2>
  <table><tbody>
    <tr><th>Shopify API call performed</th><td>{escape(str(payload.get("shopify_api_call_performed") is True))}</td></tr>
    <tr><th>Shopify write performed</th><td>{escape(str(payload.get("shopify_write_performed") is True))}</td></tr>
    <tr><th>Gmail API call performed</th><td>{escape(str(payload.get("gmail_api_call_performed") is True))}</td></tr>
    <tr><th>Email sent</th><td>{escape(str(payload.get("email_sent") is True))}</td></tr>
    <tr><th>External review API call performed</th><td>{escape(str(payload.get("external_review_api_call_performed") is True))}</td></tr>
  </tbody></table>
</body>
</html>"""


def _issue_summary(payload: dict) -> str:
    order_22530 = payload.get("order_22530") or {}
    order_22562 = payload.get("order_22562") or {}
    return (
        f"Selected local tag field: {payload.get('selected_local_tag_field')}; "
        f"migration added: {payload.get('migration_added') is True}; "
        f"#22530 tag data available: {order_22530.get('tag_field_data_available') is True}; "
        f"#22530 review tag detected: {order_22530.get('review_request_tag_detected') is True}; "
        f"#22562 review tag detected: {order_22562.get('review_request_tag_detected') is True}; "
        f"eligible candidates after tag availability: {payload.get('eligible_candidate_count_after_tag_availability', 0)}. "
        "No Shopify, Gmail, Trustpilot, Kudosi, or Ali Reviews API calls or writes were performed."
    )


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = []
    for match in EMAIL_RE.finditer(text):
        value = match.group(0)
        if "***" not in value:
            raw_emails.append(_mask_email(value))
    secret_count = 1 if SECRET_RE.search(text) else 0
    return {
        "scan_performed": True,
        "passed": not raw_emails and not secret_count,
        "raw_customer_email_count": len(set(raw_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_emails))[:5],
        "secret_pattern_count": secret_count,
    }


def _tail(value: str, max_lines: int = 80) -> str:
    return "\n".join(str(value or "").splitlines()[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _safe_text(value, max_length: int = 300) -> str:
    text = str(value or "").replace("\x00", "")
    text = EMAIL_RE.sub(lambda match: _mask_email(match.group(0)), text)
    text = SECRET_RE.sub("[redacted-secret-marker]", text)
    text = " ".join(text.split())
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _sanitize_text(value, max_length: int = 1000) -> str:
    return _safe_text(value, max_length=max_length)


def _mask_email(email: str) -> str:
    value = str(email or "").strip()
    if "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    return f"{local[:2]}***@{domain}"
