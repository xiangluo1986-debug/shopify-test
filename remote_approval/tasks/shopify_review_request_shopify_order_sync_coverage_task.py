import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_last_60_days_candidate_scan_task import (
    run_shopify_review_request_last_60_days_candidate_scan_task,
)
from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_shopify_order_sync_coverage"
COMMAND_LABEL = "shopify_review_request_shopify_order_sync_coverage_local_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_shopify_order_sync_coverage.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_shopify_order_sync_coverage.html"
SQLITE_DB_PATH = PROJECT_ROOT / "backend" / "db.sqlite3"
TIMEOUT_SECONDS = 120
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_ORDER_SYNC_COVERAGE_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_ORDER_SYNC_COVERAGE_JSON_END"
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token|refresh[_\s-]?token|client[_\s-]?secret|api[_\s-]?key|password|secret)"
)


def run_shopify_review_request_shopify_order_sync_coverage_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    before = _load_local_coverage()
    candidate_result = run_shopify_review_request_last_60_days_candidate_scan_task("dry-run")
    candidate_payload = _read_json(Path(candidate_result.get("review_path", "")))
    after = _load_local_coverage()
    payload = _build_payload(
        before=before,
        after=after,
        candidate_result=candidate_result,
        candidate_payload=candidate_payload,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _load_local_coverage() -> dict:
    django_result = _load_coverage_via_django()
    if django_result.get("success"):
        return django_result["payload"]
    sqlite_result = _load_coverage_via_sqlite()
    if sqlite_result.get("success"):
        payload = sqlite_result["payload"]
        payload["fallback_reason"] = django_result.get("failure_type", "")
        return payload
    return {
        "coverage_status": "coverage_check_failed",
        "scan_source": "fallback_report_only",
        "local_last_60_days_order_count": 0,
        "order_22530_found": False,
        "order_22562_found": False,
        "failure_type": django_result.get("failure_type") or sqlite_result.get("failure_type") or "unknown",
        "error_sanitized": _sanitize_text(django_result.get("stderr") or sqlite_result.get("stderr") or ""),
    }


def _load_coverage_via_django() -> dict:
    script = "\n".join(
        [
            "import json",
            "from datetime import timedelta",
            "from django.db.models import Q",
            "from django.utils import timezone",
            "from shopify_sync.models import ShopifyOrder, ShopifySyncState",
            "cutoff = timezone.now() - timedelta(days=60)",
            "query = Q(order_created_at__gte=cutoff) | Q(fulfilled_at__gte=cutoff) | Q(updated_at__gte=cutoff)",
            "qs = ShopifyOrder.objects.filter(query)",
            "shenzhen_q = Q(is_shenzhen_order=True) | Q(current_location__in=['shenzhen','mixed'])",
            "def found(name):",
            "    text = str(name).strip()",
            "    raw = text.lstrip('#')",
            "    names = {text}",
            "    numbers = set()",
            "    shopify_ids = set()",
            "    if raw.isdigit():",
            "        names.add(raw)",
            "        names.add('#' + raw)",
            "        numbers.add(raw)",
            "        shopify_ids.add(raw)",
            "    query = Q(order_name__in=names)",
            "    if numbers:",
            "        query |= Q(order_number__in=numbers)",
            "    if shopify_ids:",
            "        query |= Q(shopify_order_id__in=shopify_ids)",
            "    return ShopifyOrder.objects.filter(query).exists()",
            "state = ShopifySyncState.objects.filter(task_name__in=['orders_review_request_3','orders_review_request_60','orders_review_request_manual']).order_by('-last_success_at','-finished_at','-updated_at').first()",
            "payload = {",
            "    'coverage_status': 'coverage_checked',",
            "    'coverage_check_source': 'django',",
            "    'scan_source': 'full_shopify_orders' if state and state.last_success_at else ('shenzhen_only_orders' if qs.count() and qs.exclude(shenzhen_q).count() == 0 else 'fallback_report_only'),",
            "    'local_last_60_days_order_count': qs.count(),",
            "    'local_last_60_days_shenzhen_order_count': qs.filter(shenzhen_q).count(),",
            "    'local_last_60_days_non_shenzhen_order_count': qs.exclude(shenzhen_q).count(),",
            "    'order_22530_found': found('#22530'),",
            "    'order_22562_found': found('#22562'),",
            "    'latest_review_request_sync_task_name': state.task_name if state else '',",
            "    'latest_review_request_sync_finished_at': state.last_success_at.isoformat() if state and state.last_success_at else '',",
            "    'shopify_api_call_performed': False,",
            "    'shopify_write_performed': False,",
            "    'gmail_api_call_performed': False,",
            "}",
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
        return {"success": False, "failure_type": "docker_command_not_found", "stderr": "Docker command was not found."}
    except PermissionError:
        return {"success": False, "failure_type": "docker_permission_denied", "stderr": "Docker permission denied."}
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "failure_type": "timeout",
            "stdout": _to_text(exc.stdout),
            "stderr": _to_text(exc.stderr),
        }

    stdout = _to_text(completed.stdout)
    stderr = _to_text(completed.stderr)
    payload = _extract_payload(stdout)
    if completed.returncode != 0:
        return {
            "success": False,
            "failure_type": "django_coverage_check_failed",
            "stdout": stdout,
            "stderr": stderr,
        }
    if not payload:
        return {
            "success": False,
            "failure_type": "coverage_payload_missing",
            "stdout": stdout,
            "stderr": stderr,
        }
    return {"success": True, "payload": payload}


def _extract_payload(stdout: str) -> dict:
    if JSON_BEGIN not in stdout or JSON_END not in stdout:
        return {}
    fragment = stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0].strip()
    try:
        payload = json.loads(fragment)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _load_coverage_via_sqlite() -> dict:
    if not SQLITE_DB_PATH.exists():
        return {"success": False, "failure_type": "sqlite_db_missing", "stderr": "SQLite database not found."}
    try:
        connection = sqlite3.connect(SQLITE_DB_PATH)
        connection.row_factory = sqlite3.Row
        try:
            columns = _table_columns(connection, "shopify_sync_shopifyorder")
            if "order_created_at" not in columns:
                return {"success": False, "failure_type": "sqlite_order_columns_missing", "stderr": "Order date column missing."}
            cutoff = datetime.now(timezone.utc) - timedelta(days=60)
            rows = [
                dict(row)
                for row in connection.execute(
                    "SELECT order_name, order_number, shopify_order_id, order_created_at, fulfilled_at, updated_at, current_location, is_shenzhen_order "
                    "FROM shopify_sync_shopifyorder"
                ).fetchall()
            ]
        finally:
            connection.close()
    except Exception as exc:
        return {"success": False, "failure_type": "sqlite_coverage_check_failed", "stderr": _sanitize_text(str(exc))}

    window_rows = [row for row in rows if _row_in_window(row, cutoff)]
    shenzhen_rows = [
        row
        for row in window_rows
        if bool(row.get("is_shenzhen_order")) or str(row.get("current_location") or "") in {"shenzhen", "mixed"}
    ]
    order_names = {_canonical_order_name(row.get("order_name") or row.get("order_number")) for row in rows}
    order_numbers = {str(row.get("order_number") or "").lstrip("#") for row in rows if row.get("order_number")}
    shopify_order_ids = {str(row.get("shopify_order_id") or "") for row in rows if row.get("shopify_order_id")}
    payload = {
        "coverage_status": "coverage_checked",
        "coverage_check_source": "sqlite",
        "scan_source": "sqlite_report_fallback",
        "local_last_60_days_order_count": len(window_rows),
        "local_last_60_days_shenzhen_order_count": len(shenzhen_rows),
        "local_last_60_days_non_shenzhen_order_count": max(len(window_rows) - len(shenzhen_rows), 0),
        "order_22530_found": _sqlite_order_found("#22530", order_names, order_numbers, shopify_order_ids),
        "order_22562_found": _sqlite_order_found("#22562", order_names, order_numbers, shopify_order_ids),
        "latest_review_request_sync_task_name": "",
        "latest_review_request_sync_finished_at": "",
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "gmail_api_call_performed": False,
    }
    return {"success": True, "payload": payload}


def _build_payload(before, after, candidate_result, candidate_payload, duration_seconds):
    scan_source = _safe_text(candidate_payload.get("scan_source") or after.get("scan_source") or "unknown")
    coverage_warnings = _dedupe(
        (candidate_payload.get("coverage_warnings") or [])
        + _coverage_warnings_from_coverage(after, scan_source)
    )
    sync_commands = _sync_commands()
    order_22530_diagnosis = candidate_payload.get("order_22530_diagnosis") or {
        "order_name": "#22530",
        "found_in_local_shopify_order": after.get("order_22530_found") is True,
        "included_in_candidate_scan": False,
        "candidate_scan_section": "not_scanned",
        "message": (
            "#22530 found in local ShopifyOrder data."
            if after.get("order_22530_found") is True
            else "#22530 not found in local ShopifyOrder data. Run Review Request 60-day Shopify sync."
        ),
    }
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28E",
        "mode": "dry-run-local-coverage-check",
        "command_label": COMMAND_LABEL,
        "report_status": "shopify_order_sync_coverage_checked",
        "success": True,
        "sync_run": False,
        "sync_not_run_reason": "Current task instructions prohibit Shopify API calls; prepared safe manual commands instead.",
        "sync_command_prepared": sync_commands["initial_60_day_apply_command"],
        "sync_dry_run_command_prepared": sync_commands["initial_60_day_dry_run_command"],
        "daily_3_day_sync_command": sync_commands["daily_3_day_apply_command"],
        "daily_3_day_dry_run_command": sync_commands["daily_3_day_dry_run_command"],
        "coverage_before": before,
        "coverage_after": after,
        "local_order_source_before": before.get("scan_source", "unknown"),
        "local_order_source_after": after.get("scan_source", "unknown"),
        "last_60_days_local_order_count_before": int(before.get("local_last_60_days_order_count") or 0),
        "last_60_days_local_order_count_after": int(after.get("local_last_60_days_order_count") or 0),
        "order_22530_found_before": before.get("order_22530_found") is True,
        "order_22530_found_after": after.get("order_22530_found") is True,
        "order_22562_found_before": before.get("order_22562_found") is True,
        "order_22562_found_after": after.get("order_22562_found") is True,
        "order_22530_diagnosis": order_22530_diagnosis,
        "candidate_scan_ran": candidate_result.get("success") is True,
        "candidate_scan_report_path": candidate_result.get("review_path", ""),
        "candidate_scan_html_path": candidate_result.get("html_review_path", ""),
        "candidate_scan_source": scan_source,
        "candidate_scan_source_is_full_shopify_order_data": scan_source == "full_shopify_orders",
        "order_22530_included_after_candidate_scan": order_22530_diagnosis.get("included_in_candidate_scan") is True,
        "eligible_candidate_count": int(candidate_payload.get("eligible_candidate_count") or 0),
        "blocked_count": int(candidate_payload.get("blocked_count") or 0),
        "already_sent_count": int(candidate_payload.get("already_sent_count") or 0),
        "coverage_warnings": coverage_warnings,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
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
        "duration_seconds": duration_seconds,
    }
    payload["privacy_scan_summary"] = _privacy_scan(payload)
    payload["detected_issue_summary"] = (
        f"Coverage source after check: {payload['local_order_source_after']}; "
        f"last-60-days local orders: {payload['last_60_days_local_order_count_after']}; "
        f"#22530 found: {payload['order_22530_found_after']}; "
        f"#22562 found: {payload['order_22562_found_after']}; "
        f"candidate scan source: {payload['candidate_scan_source']}; "
        f"eligible candidates: {payload['eligible_candidate_count']}; "
        f"warnings: {', '.join(coverage_warnings) or 'none'}. "
        "No Shopify API, Shopify write, Gmail, or external review API call was performed."
    )
    return payload


def _coverage_warnings_from_coverage(coverage, scan_source):
    warnings = []
    if scan_source != "full_shopify_orders":
        warnings.append("incomplete_local_order_source")
    if coverage.get("order_22530_found") is not True:
        warnings.append("order_not_found_in_local_data")
    return warnings


def _sync_commands():
    base = "docker compose exec -T web python manage.py sync_review_request_shopify_orders"
    return {
        "initial_60_day_dry_run_command": f"{base} --days 60 --dry-run",
        "initial_60_day_apply_command": f"{base} --days 60 --apply-local",
        "daily_3_day_dry_run_command": f"{base} --days 3 --dry-run",
        "daily_3_day_apply_command": f"{base} --days 3 --apply-local",
    }


def _write_json(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "report_status": payload.get("report_status", ""),
        "sync_run": payload.get("sync_run") is True,
        "local_order_source_after": payload.get("local_order_source_after", ""),
        "last_60_days_local_order_count_after": payload.get("last_60_days_local_order_count_after", 0),
        "order_22530_found_after": payload.get("order_22530_found_after") is True,
        "order_22562_found_after": payload.get("order_22562_found_after") is True,
        "candidate_scan_source": payload.get("candidate_scan_source", ""),
        "eligible_candidate_count": payload.get("eligible_candidate_count", 0),
        "coverage_warnings": payload.get("coverage_warnings", []),
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
    return (
        "Review Request Shopify order sync coverage check completed.\n"
        f"Result: {payload.get('report_status')}\n"
        f"Sync run: {payload.get('sync_run') is True}\n"
        f"Local source after: {payload.get('local_order_source_after')}\n"
        f"Last 60 days local orders: {payload.get('last_60_days_local_order_count_after', 0)}\n"
        f"#22530 found: {payload.get('order_22530_found_after') is True}\n"
        f"#22562 found: {payload.get('order_22562_found_after') is True}\n"
        f"Candidate scan source: {payload.get('candidate_scan_source')}\n"
        f"Eligible candidates: {payload.get('eligible_candidate_count', 0)}\n"
        f"Coverage warnings: {', '.join(payload.get('coverage_warnings') or []) or 'none'}\n"
        f"Manual 60-day sync command: {payload.get('sync_command_prepared')}\n"
        f"Manual daily 3-day sync command: {payload.get('daily_3_day_sync_command')}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "0 = stop"
    )


def _render_html(payload: dict) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Shopify Order Sync Coverage</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
  </style>
</head>
<body>
  <h1>Review Request Shopify Order Sync Coverage</h1>
  <table><tbody>
    <tr><th>Status</th><td>{escape(str(payload.get("report_status", "")))}</td></tr>
    <tr><th>Sync run</th><td>{escape(str(payload.get("sync_run") is True))}</td></tr>
    <tr><th>Sync not run reason</th><td>{escape(str(payload.get("sync_not_run_reason", "")))}</td></tr>
    <tr><th>Local source after</th><td>{escape(str(payload.get("local_order_source_after", "")))}</td></tr>
    <tr><th>Last 60 days local order count</th><td>{escape(str(payload.get("last_60_days_local_order_count_after", 0)))}</td></tr>
    <tr><th>#22530 found</th><td>{escape(str(payload.get("order_22530_found_after") is True))}</td></tr>
    <tr><th>#22562 found</th><td>{escape(str(payload.get("order_22562_found_after") is True))}</td></tr>
    <tr><th>#22530 diagnosis</th><td>{escape(str((payload.get("order_22530_diagnosis") or {}).get("message", "")))}</td></tr>
    <tr><th>Candidate scan source</th><td>{escape(str(payload.get("candidate_scan_source", "")))}</td></tr>
    <tr><th>Eligible candidates</th><td>{escape(str(payload.get("eligible_candidate_count", 0)))}</td></tr>
    <tr><th>Coverage warnings</th><td>{escape(", ".join(payload.get("coverage_warnings") or []) or "none")}</td></tr>
    <tr><th>60-day sync command</th><td><code>{escape(str(payload.get("sync_command_prepared", "")))}</code></td></tr>
    <tr><th>Daily 3-day sync command</th><td><code>{escape(str(payload.get("daily_3_day_sync_command", "")))}</code></td></tr>
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


def _read_json(path: Path) -> dict:
    try:
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _table_columns(connection, table_name: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _row_in_window(row: dict, cutoff: datetime) -> bool:
    for key in ("fulfilled_at", "updated_at", "order_created_at"):
        parsed = _parse_datetime(row.get(key))
        if parsed and parsed >= cutoff:
            return True
    return False


def _sqlite_order_found(identifier, order_names, order_numbers, shopify_order_ids):
    canonical = _canonical_order_name(identifier)
    raw = str(identifier or "").strip().lstrip("#")
    return (
        canonical in order_names
        or raw in order_numbers
        or raw in shopify_order_ids
    )


def _parse_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _canonical_order_name(value):
    text = str(value or "").strip()
    if not text:
        return ""
    match = re.fullmatch(r"#?(\d{3,})", text)
    if match:
        return f"#{match.group(1)}"
    return text


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _safe_text(value: object, max_length: int = 300) -> str:
    text = str(value or "")
    text = EMAIL_RE.sub(lambda match: _mask_email(match.group(0)), text)
    text = SECRET_RE.sub("[redacted-secret-marker]", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:max_length]


def _sanitize_text(value: object) -> str:
    return _safe_text(value, 1000)


def _mask_email(email: str) -> str:
    value = str(email or "").strip()
    if "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    return f"{local[:2]}***@{domain}"


def _dedupe(values) -> list:
    result = []
    seen = set()
    for value in values or []:
        text = _safe_text(value, 120)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


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
