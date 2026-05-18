import json
import os
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_dashboard_counts_audit"
COMMAND_LABEL = "shopify_review_request_dashboard_counts_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_dashboard_counts_audit.json"
REPORT_HTML_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_dashboard_counts_audit.html"
LAST_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
REVIEW_SEND_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_review_and_send_execute.json"
POST_SEND_AUDIT_JSON_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_review_send_post_send_audit.json"
POST_SEND_TAG_WRITE_JSON_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_trustpilot_post_send_tag_write.json"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_DASHBOARD_COUNTS_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_DASHBOARD_COUNTS_AUDIT_JSON_END"

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)("
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"shpat_[A-Za-z0-9_]+|"
    r"x-shopify-access-token\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=]|secret\s*[:=]"
    r")"
)


def run_shopify_review_request_dashboard_counts_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_audit()
    if completed["success"]:
        payload = completed["payload"]
        payload["duration_seconds"] = round(time.time() - started, 3)
    else:
        payload = _fallback_payload_from_local_reports(completed, round(time.time() - started, 3))

    payload["privacy_scan_summary"] = _privacy_scan(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["audit_status"] = "blocked_privacy_scan_failed"
        payload["report_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["detected_issue_summary"] = "Dashboard counts audit privacy scan failed."

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_audit() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_dashboard_counts_audit_report; "
        "payload = build_review_request_dashboard_counts_audit_report({}); "
        f"print('{JSON_BEGIN}'); "
        "print(json.dumps(payload, ensure_ascii=False, sort_keys=True)); "
        f"print('{JSON_END}')"
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
            env=_docker_subprocess_env(),
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
    return {"success": True, "exit_code": 0, "payload": payload, "stdout": stdout, "stderr": stderr}


def _extract_payload(stdout: str) -> dict:
    if JSON_BEGIN not in stdout or JSON_END not in stdout:
        return {}
    fragment = stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0].strip()
    try:
        payload = json.loads(fragment)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _docker_subprocess_env() -> dict:
    env = os.environ.copy()
    for key in (
        "DOCKER_CONTEXT",
        "DOCKER_HOST",
        "DOCKER_TLS_VERIFY",
        "DOCKER_CERT_PATH",
    ):
        env.pop(key, None)
    docker_config = REPORT_JSON_PATH.parent / "docker_config_empty"
    docker_config.mkdir(parents=True, exist_ok=True)
    env["DOCKER_CONFIG"] = str(docker_config)
    return env


def _failed_run(failure_type: str, exit_code: int, stdout: str, stderr: str) -> dict:
    return {
        "success": False,
        "exit_code": exit_code,
        "failure_type": failure_type,
        "stdout": _safe_text(stdout),
        "stderr": _safe_text(stderr),
    }


def _failure_payload(result: dict, duration_seconds: float) -> dict:
    failure_type = _safe_text(result.get("failure_type") or "dashboard_counts_audit_failed")
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.30",
        "mode": "dry-run-local-dashboard-counts-audit",
        "command_label": COMMAND_LABEL,
        "audit_status": failure_type,
        "report_status": failure_type,
        "success": False,
        "eligible_total": 0,
        "needs_review_visible_count": 0,
        "already_sent_total": 0,
        "blocked_total": 0,
        "older_eligible_hidden": 0,
        "latest_sent_order": "",
        "latest_sent_time": "",
        "sent_rows_with_time_count": 0,
        "sent_rows_without_time_count": 0,
        "already_sent_page_size": 25,
        "already_sent_visible_count": 0,
        "stale_counter_warning": True,
        "django_audit_exit_code": int(result.get("exit_code") or 1),
        "django_audit_failure_type": failure_type,
        "django_audit_stdout_tail": _tail_text(result.get("stdout", "")),
        "django_audit_stderr_tail": _tail_text(result.get("stderr", "")),
        **_safety_flags(),
        "duration_seconds": duration_seconds,
    }
    payload["detected_issue_summary"] = (
        f"Dashboard counts audit failed before reading counts: {failure_type}. "
        "No Gmail, Shopify, external review API, or translationsRegister calls were performed."
    )
    return payload


def _fallback_payload_from_local_reports(result: dict, duration_seconds: float) -> dict:
    scan = _read_json(LAST_SCAN_JSON_PATH)
    if not scan:
        return _failure_payload(result, duration_seconds)

    eligible_rows = _safe_rows(scan.get("eligible_queue_rows") or scan.get("eligible_candidates_summary"))
    already_sent_rows = _safe_rows(scan.get("already_sent_queue_rows") or scan.get("already_sent_summary"))
    sent_records = _local_sent_records()
    eligible_orders = {_safe_text(row.get("order") or row.get("order_name"), max_length=80) for row in eligible_rows}
    already_sent_orders = {
        _safe_text(row.get("order") or row.get("order_name"), max_length=80)
        for row in already_sent_rows
    }
    eligible_orders.discard("")
    already_sent_orders.discard("")
    local_sent_orders = {_safe_text(row.get("order"), max_length=80) for row in sent_records}
    local_sent_orders.discard("")
    newly_sent_orders = local_sent_orders - already_sent_orders

    eligible_total = _int_value(
        scan.get("eligible_candidate_count_total")
        or scan.get("eligible_candidate_count")
        or len(eligible_rows)
    )
    eligible_total = max(eligible_total - len(newly_sent_orders & eligible_orders), 0)
    already_sent_total = max(
        _int_value(scan.get("already_sent_count")),
        len(already_sent_orders | local_sent_orders),
    )
    latest_sent = _latest_sent_record([*_sent_rows_from_scan(already_sent_rows), *sent_records])
    sent_rows_with_time = sum(1 for row in [*_sent_rows_from_scan(already_sent_rows), *sent_records] if row.get("sent_time"))
    sent_rows_without_time = max(already_sent_total - sent_rows_with_time, 0)
    page_size = 25
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.30",
        "mode": "dry-run-local-dashboard-counts-audit-fallback",
        "command_label": COMMAND_LABEL,
        "audit_status": "dashboard_counts_audit_fallback_ready",
        "report_status": "dashboard_counts_audit_fallback_ready",
        "success": True,
        "eligible_total": eligible_total,
        "needs_review_visible_count": min(page_size, len(eligible_rows) or eligible_total),
        "already_sent_total": already_sent_total,
        "blocked_total": _int_value(scan.get("blocked_count") or len(_safe_rows(scan.get("blocked_queue_rows")))),
        "older_eligible_hidden": _int_value(scan.get("hidden_older_eligible_count")),
        "latest_sent_order": latest_sent.get("order", ""),
        "latest_sent_time": latest_sent.get("sent_time", ""),
        "latest_tag_write_time": latest_sent.get("tag_written_time", ""),
        "sent_rows_with_time_count": sent_rows_with_time,
        "sent_rows_without_time_count": sent_rows_without_time,
        "already_sent_page_size": page_size,
        "already_sent_visible_count": min(page_size, already_sent_total),
        "already_sent_page": 1,
        "already_sent_total_pages": max((already_sent_total + page_size - 1) // page_size, 1),
        "stale_counter_warning": True,
        "stale_counter_warning_message": "Data may be stale. Run Shopify sync / candidate scan.",
        "candidate_scan_freshness": _safe_text(scan.get("timestamp") or scan.get("scan_window_ended_at"), max_length=120),
        "counter_source": "fallback_local_scan_json_plus_latest_review_send_and_tag_reports",
        "source_scan_report_path": str(LAST_SCAN_JSON_PATH),
        "django_audit_exit_code": int(result.get("exit_code") or 1),
        "django_audit_failure_type": _safe_text(result.get("failure_type", "")),
        "django_audit_stdout_tail": _tail_text(result.get("stdout", "")),
        "django_audit_stderr_tail": _tail_text(result.get("stderr", "")),
        **_safety_flags(),
        "duration_seconds": duration_seconds,
    }
    payload["detected_issue_summary"] = (
        f"Dashboard counts fallback audit: eligible={payload['eligible_total']}, "
        f"already_sent={payload['already_sent_total']}, blocked={payload['blocked_total']}, "
        f"latest_sent={payload['latest_sent_order'] or 'none'} at "
        f"{payload['latest_sent_time'] or 'Time not recorded'}. "
        "Primary Django audit was unavailable, so stale-data warning is true. "
        "No Gmail, Shopify, external review API, or translationsRegister calls were performed."
    )
    return payload


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _safe_rows(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [row for row in value if isinstance(row, dict)]


def _local_sent_records() -> list[dict]:
    records = []
    for path in (REVIEW_SEND_JSON_PATH, POST_SEND_AUDIT_JSON_PATH, POST_SEND_TAG_WRITE_JSON_PATH):
        payload = _read_json(path)
        if not payload:
            continue
        record = _sent_record_from_payload(payload)
        if record:
            records.append(record)
    return _dedupe_sent_records(records)


def _sent_record_from_payload(payload: dict) -> dict:
    email_sent = (
        payload.get("email_sent") is True
        or payload.get("email_sent_confirmed") is True
        or payload.get("source_email_sent_confirmed") is True
    )
    sent_count = _int_value(payload.get("sent_count") or payload.get("source_sent_count"))
    order = _safe_text(
        payload.get("selected_order")
        or payload.get("selected_order_name")
        or payload.get("target_order"),
        max_length=80,
    )
    if not (email_sent and sent_count == 1 and order):
        return {}
    tag_status = _safe_text(payload.get("tag_write_status") or payload.get("auto_tag_write_status"), max_length=120)
    tag_written = (
        tag_status == "trustpilot_tag_written_and_review_request_removed"
        or payload.get("shopify_tag_write_confirmed") is True
        or payload.get("shopify_tag_written") is True
        or payload.get("source_shopify_tag_write_confirmed") is True
    )
    sent_time = _first_payload_text(
        payload,
        (
            "sent_at",
            "email_sent_at",
            "email_sent_time",
            "gmail_sent_at",
            "source_email_sent_at",
            "timestamp",
            "report_generated_at",
        ),
    )
    tag_written_time = (
        _first_payload_text(
            payload,
            (
                "tag_written_at",
                "tag_write_completed_at",
                "tag_write_timestamp",
                "timestamp",
                "report_generated_at",
            ),
        )
        if tag_written
        else ""
    )
    return {
        "order": order,
        "sent_time": sent_time,
        "tag_written_time": tag_written_time,
        "tag_written": tag_written,
    }


def _sent_rows_from_scan(rows: list[dict]) -> list[dict]:
    result = []
    for row in rows:
        order = _safe_text(row.get("order") or row.get("order_name"), max_length=80)
        if not order:
            continue
        result.append(
            {
                "order": order,
                "sent_time": _safe_text(row.get("sent_at") or row.get("email_sent_at"), max_length=80),
                "tag_written_time": _safe_text(row.get("tag_written_at"), max_length=80),
                "tag_written": row.get("shopify_tag_written") is True,
            }
        )
    return result


def _latest_sent_record(records: list[dict]) -> dict:
    if not records:
        return {}
    return sorted(records, key=_sent_record_sort_key, reverse=True)[0]


def _sent_record_sort_key(record: dict) -> tuple[str, str, int]:
    order = _safe_text(record.get("order"), max_length=80)
    return (
        _safe_text(record.get("sent_time"), max_length=80),
        _safe_text(record.get("tag_written_time"), max_length=80),
        _order_number_value(order),
    )


def _dedupe_sent_records(records: list[dict]) -> list[dict]:
    by_order = {}
    for record in records:
        order = _safe_text(record.get("order"), max_length=80)
        if not order:
            continue
        existing = by_order.get(order)
        if not existing or _sent_record_sort_key(record) > _sent_record_sort_key(existing):
            by_order[order] = record
    return list(by_order.values())


def _first_payload_text(payload: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _safe_text(payload.get(key), max_length=80)
        if value:
            return value
    return ""


def _order_number_value(value: str) -> int:
    match = re.fullmatch(r"#?(\d{3,})", _safe_text(value, max_length=80))
    return int(match.group(1)) if match else 0


def _int_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _write_json(payload: dict) -> Path:
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    REPORT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("Audit status", payload.get("audit_status")),
        ("Eligible total", payload.get("eligible_total")),
        ("Needs review visible", payload.get("needs_review_visible_count")),
        ("Already sent total", payload.get("already_sent_total")),
        ("Blocked total", payload.get("blocked_total")),
        ("Older eligible hidden", payload.get("older_eligible_hidden")),
        ("Latest sent order", payload.get("latest_sent_order") or "-"),
        ("Latest sent time", payload.get("latest_sent_time") or "Time not recorded"),
        ("Sent rows with time", payload.get("sent_rows_with_time_count")),
        ("Sent rows without time", payload.get("sent_rows_without_time_count")),
        ("Already sent page size", payload.get("already_sent_page_size")),
        ("Already sent visible", payload.get("already_sent_visible_count")),
        ("Stale warning", payload.get("stale_counter_warning")),
        ("No Gmail/Shopify writes/API calls", payload.get("all_new_actions_no_write_confirmed")),
    ]
    table_rows = "\n".join(
        f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Review Request Dashboard Counts Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #111827; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 920px; }}
    th, td {{ border: 1px solid #d1d5db; padding: 8px; text-align: left; }}
    th {{ background: #f3f4f6; width: 280px; }}
  </style>
</head>
<body>
  <h1>Review Request Dashboard Counts Audit</h1>
  <table>
    {table_rows}
  </table>
  <p>{escape(str(payload.get("detected_issue_summary", "")))}</p>
</body>
</html>
"""
    REPORT_HTML_PATH.write_text(html, encoding="utf-8")
    return REPORT_HTML_PATH


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "eligible_total": payload.get("eligible_total"),
        "needs_review_visible_count": payload.get("needs_review_visible_count"),
        "already_sent_total": payload.get("already_sent_total"),
        "blocked_total": payload.get("blocked_total"),
        "older_eligible_hidden": payload.get("older_eligible_hidden"),
        "latest_sent_order": payload.get("latest_sent_order"),
        "latest_sent_time": payload.get("latest_sent_time"),
        "already_sent_page_size": payload.get("already_sent_page_size"),
        "already_sent_visible_count": payload.get("already_sent_visible_count"),
        "stale_counter_warning": payload.get("stale_counter_warning") is True,
        "all_new_actions_no_write_confirmed": payload.get("all_new_actions_no_write_confirmed") is True,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
    }


def _safety_flags() -> dict:
    return {
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "translations_register_called": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
    }


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    raw_email_count = len(set(EMAIL_RE.findall(text)))
    secret_pattern_count = 1 if SECRET_RE.search(text) else 0
    return {
        "passed": raw_email_count == 0 and secret_pattern_count == 0,
        "raw_email_count": raw_email_count,
        "secret_pattern_count": secret_pattern_count,
    }


def _safe_text(value, max_length=300):
    text = str(value or "")
    text = EMAIL_RE.sub("[masked-email]", text)
    text = SECRET_RE.sub("[redacted]", text)
    text = "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32)
    text = text.strip()
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def _tail_text(value, max_length=1200):
    text = _safe_text(value, max_length=max_length)
    return text[-max_length:]


def _to_text(value):
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
