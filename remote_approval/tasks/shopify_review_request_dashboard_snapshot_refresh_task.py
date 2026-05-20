import json
import os
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_dashboard_snapshot_refresh"
COMMAND_LABEL = "shopify_review_request_dashboard_snapshot_refresh_local_snapshot"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_dashboard_snapshot.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_dashboard_snapshot.html"
SNAPSHOT_ENV_PATH = "REVIEW_REQUEST_DASHBOARD_SNAPSHOT_PATH"
TIMEOUT_SECONDS = 300
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_DASHBOARD_SNAPSHOT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_DASHBOARD_SNAPSHOT_JSON_END"

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


def run_shopify_review_request_dashboard_snapshot_refresh_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_snapshot_builder()
    if not completed["success"]:
        fallback = _run_sqlite_snapshot_builder(completed)
        if fallback["success"]:
            completed = fallback
    if completed["success"]:
        payload = completed["payload"]
        payload["duration_seconds"] = round(time.time() - started, 3)
    else:
        payload = _failure_payload(completed, round(time.time() - started, 3))

    payload["privacy_scan_summary"] = _privacy_scan(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload = _redact_payload_for_privacy(payload)
        payload["privacy_scan_summary"] = _privacy_scan(payload)
        payload["snapshot_status"] = "blocked_privacy_scan_failed"
        payload["report_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["detected_issue_summary"] = "Dashboard snapshot privacy scan failed."

    write_result = _write_reports(payload)
    return _task_result(payload, write_result["json_path"], write_result["html_path"])


def _run_django_snapshot_builder() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_dashboard_snapshot_payload, "
        "write_review_request_dashboard_snapshot_reports; "
        f"payload = build_review_request_dashboard_snapshot_payload({{}}, generated_by='{TASK_NAME}'); "
        "payload['container_snapshot_paths'] = write_review_request_dashboard_snapshot_reports(payload); "
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
        return _failed_run("django_snapshot_builder_failed", completed.returncode, stdout, stderr)
    if not payload:
        return _failed_run("snapshot_payload_missing", 1, stdout, stderr)
    return {"success": True, "exit_code": 0, "payload": payload, "stdout": stdout, "stderr": stderr}


def _run_sqlite_snapshot_builder(django_result: dict) -> dict:
    try:
        from remote_approval.tasks.shopify_review_request_last_60_days_candidate_scan_task import (
            _run_sqlite_local_scan,
        )
    except Exception as exc:
        return _failed_run(
            "sqlite_snapshot_builder_import_failed",
            1,
            "",
            _safe_text(f"{exc.__class__.__name__}: {exc}"),
        )

    scan_result = _run_sqlite_local_scan()
    if not scan_result.get("success"):
        return _failed_run(
            scan_result.get("failure_type") or "sqlite_snapshot_builder_failed",
            int(scan_result.get("exit_code") or 1),
            scan_result.get("stdout", ""),
            scan_result.get("stderr", ""),
        )

    payload = _snapshot_payload_from_scan(
        scan_result.get("payload") or {},
        django_result=django_result,
    )
    return {"success": True, "exit_code": 0, "payload": payload, "stdout": "", "stderr": ""}


def _snapshot_payload_from_scan(scan: dict, django_result: dict) -> dict:
    generated_at = utc_now_iso()
    coverage = scan.get("order_data_coverage") if isinstance(scan.get("order_data_coverage"), dict) else {}
    review_rows = _safe_rows(
        scan.get("eligible_queue_rows") or scan.get("review_queue_rows") or scan.get("eligible_candidates_summary")
    )
    already_sent_rows = _safe_rows(scan.get("already_sent_queue_rows") or scan.get("already_sent_summary"))
    blocked_rows = _safe_rows(scan.get("blocked_queue_rows") or scan.get("blocked_candidates_summary"))
    eligible_total = _int_value(
        scan.get("eligible_candidate_count_total")
        or scan.get("eligible_candidate_count")
        or len(review_rows)
    )
    blocked_total = _int_value(scan.get("blocked_count") or len(blocked_rows))
    already_sent_total = _int_value(scan.get("already_sent_count") or len(already_sent_rows))
    approval_queue = _approval_queue_from_scan(scan, review_rows, already_sent_rows, blocked_rows)
    dashboard = _dashboard_from_scan(scan, coverage, approval_queue, eligible_total, blocked_total, already_sent_total)
    workbench = {
        "operating_dashboard": dashboard,
        "summary": [],
        "filters": {},
        "filter_summary": {},
        "latest_scan": {},
        "candidate_queue": [],
        "invitation_history": [],
        "review_request_queue": [],
        "typo_review_request_rows": [],
        "blocked_orders": [],
        "blocked_reason_counts": [],
        "report_readiness": [],
        "report_history": [],
        "history_ledger": [],
        "history_filters": {},
        "history_summary": {},
        "history_focus": {},
        "history_source_reports": [],
        "history_filter_summary": {},
        "history_channel_filter_options": [],
        "history_event_type_filter_options": [],
        "history_limit_filter_options": [],
        "history_recommendations": [],
        "safety_history": [],
        "local_stats": {"note": "Snapshot generated from local SQLite/report fallback.", "total_orders": 0, "orders_with_email": 0},
        "tracking_design": {},
        "candidate_queue_status": {},
        "trustpilot_email_records": [],
        "ali_reviews_status": {},
        "trustpilot_aliases": [],
        "review_request_tag_aliases": [],
        "delivered_tag_aliases": [],
        "canonical_review_request_tag": "1: review request",
        "typo_review_request_tag": "1: reveiw request",
        "delivered_tag": "Delivered",
        "status_filter_options": [],
        "tag_filter_options": [],
        "limit_filter_options": [],
        "review_queue_page_size_options": [],
        "safety_confirmations": _snapshot_safety_confirmations(),
    }
    return _redact_payload_for_privacy(
        {
            "task": TASK_NAME,
            "task_name": TASK_NAME,
            "phase": "5.32",
            "snapshot_status": "dashboard_snapshot_ready_sqlite_fallback",
            "report_status": "dashboard_snapshot_ready_sqlite_fallback",
            "success": True,
            "generated_at": generated_at,
            "generated_by": TASK_NAME,
            "sync_source": _safe_text(
                coverage.get("last_shopify_order_sync_window") or "SQLite/report fallback",
                max_length=120,
            ),
            "eligible_total": eligible_total,
            "review_queue_candidates": review_rows,
            "already_sent_rows": already_sent_rows,
            "blocked_summary": {
                "blocked_total": blocked_total,
                "blocked_visible_count": len(blocked_rows[:50]),
                "blocked_ebay_order_count": _int_value(scan.get("blocked_ebay_order_count")),
                "blocked_duplicate_customer_count": _int_value(scan.get("blocked_duplicate_customer_count")),
            "blocked_merged_group_count": _int_value(scan.get("blocked_merged_group_count")),
            "blocked_first_order_count": _int_value(scan.get("blocked_first_order_count")),
            "blocked_not_second_or_later_count": _int_value(
                scan.get("blocked_not_second_or_later_count")
            ),
            "blocked_second_order_not_delivered_count": _int_value(
                scan.get("blocked_second_order_not_delivered_count")
            ),
            "rows": blocked_rows[:50],
        },
            "dashboard_counters": {
                "ready_to_send_count": eligible_total,
                "eligible_total": eligible_total,
                "needs_review_visible_count": min(25, len(review_rows)),
                "already_sent_total": already_sent_total,
                "blocked_total": blocked_total,
                "older_eligible_hidden": _int_value(scan.get("hidden_older_eligible_count")),
                "latest_sent_order": _safe_text(scan.get("latest_sent_order"), max_length=80),
                "latest_sent_time": _safe_text(scan.get("latest_sent_time"), max_length=120),
                "latest_tag_write_time": _safe_text(scan.get("latest_tag_write_time"), max_length=120),
                "eligible_candidate_count_before_second_order_rule": _int_value(
                    scan.get("eligible_candidate_count_before_second_order_rule") or eligible_total
                ),
                "eligible_candidate_count_after_second_order_rule": _int_value(
                    scan.get("eligible_candidate_count_after_second_order_rule") or eligible_total
                ),
                "second_or_later_delivered_candidate_count": _int_value(
                    scan.get("second_or_later_delivered_candidate_count") or eligible_total
                ),
            },
            "stale_after_minutes": 240,
            "scan_report_source": _safe_text(scan.get("scan_source") or "sqlite_report_fallback", max_length=120),
            "last_shopify_sync_at": _safe_text(
                coverage.get("latest_review_request_sync_finished_at")
                or coverage.get("latest_local_order_synced_at"),
                max_length=120,
            ),
            "last_candidate_scan_at": _safe_text(
                scan.get("candidate_scan_freshness")
                or scan.get("scan_window_ended_at")
                or generated_at,
                max_length=120,
            ),
            "review_request_workbench": workbench,
            "snapshot_output_json_path": f"logs/{REPORT_JSON_PATH.name}",
            "snapshot_output_html_path": f"logs/{REPORT_HTML_PATH.name}",
            "django_snapshot_failure_type": _safe_text(django_result.get("failure_type"), max_length=120),
            "django_snapshot_stdout_tail": _tail_text(django_result.get("stdout", "")),
            "django_snapshot_stderr_tail": _tail_text(django_result.get("stderr", "")),
            "sqlite_fallback_used": True,
            "normal_page_load_data_source": "cached_snapshot",
            "normal_page_load_shopify_api_call_performed": False,
            "normal_page_load_full_scan_performed": False,
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "translations_register_performed": False,
            "gmail_api_call_performed": False,
            "gmail_draft_create_attempted": False,
            "gmail_send_performed": False,
            "email_sent": False,
            "external_review_api_call_performed": False,
            "trustpilot_api_call_performed": False,
            "kudosi_api_call_performed": False,
            "ali_reviews_api_call_performed": False,
            "raw_customer_email_output": False,
            "secret_values_printed": False,
            "detected_issue_summary": (
                "Dashboard snapshot refreshed from local SQLite/report fallback because Docker was unavailable. "
                "No Shopify API, Gmail API, external review API, email send, or Shopify write was performed."
            ),
        }
    )


def _approval_queue_from_scan(scan: dict, review_rows: list[dict], already_sent_rows: list[dict], blocked_rows: list[dict]) -> dict:
    page_size = 25
    visible_review_rows = review_rows[:page_size]
    visible_sent_rows = already_sent_rows[:page_size]
    eligible_total = _int_value(
        scan.get("eligible_candidate_count_total")
        or scan.get("eligible_candidate_count")
        or len(review_rows)
    )
    return {
        "needs_review_rows": visible_review_rows,
        "blocked_rows": blocked_rows[:50],
        "already_sent_rows": visible_sent_rows,
        "all_needs_review_rows": review_rows,
        "all_already_sent_rows": already_sent_rows,
        "needs_review_count": eligible_total,
        "already_sent_count": _int_value(scan.get("already_sent_count") or len(already_sent_rows)),
        "ready_to_send_count": eligible_total,
        "not_ready_count": _int_value(scan.get("blocked_count") or len(blocked_rows)),
        "blocked_count": _int_value(scan.get("blocked_count") or len(blocked_rows)),
        "blocked_visible_count": min(50, len(blocked_rows)),
        "blocked_display_limit": 50,
        "blocked_overflow_count": max(len(blocked_rows) - 50, 0),
        "duplicate_block_count": _int_value(scan.get("blocked_duplicate_customer_count")),
        "blocked_ebay_order_count": _int_value(scan.get("blocked_ebay_order_count")),
        "blocked_first_order_count": _int_value(scan.get("blocked_first_order_count")),
        "blocked_not_second_or_later_count": _int_value(scan.get("blocked_not_second_or_later_count")),
        "blocked_second_order_not_delivered_count": _int_value(
            scan.get("blocked_second_order_not_delivered_count")
        ),
        "review_send_action_enabled_count": len(visible_review_rows),
        "email_sent_count": _int_value(scan.get("already_sent_count") or len(already_sent_rows)),
        "merged_group_count": _int_value(scan.get("blocked_merged_group_count")),
        "merged_groups": _safe_rows(scan.get("merged_groups")),
        "eligible_candidate_count_before_latest_filter": _int_value(
            scan.get("eligible_candidate_count_before_latest_filter") or eligible_total
        ),
        "eligible_candidate_count_after_latest_filter": _int_value(
            scan.get("eligible_candidate_count_after_latest_filter") or eligible_total
        ),
        "hidden_older_eligible_count": _int_value(scan.get("hidden_older_eligible_count")),
        "hidden_older_eligible_summary": _safe_rows(scan.get("hidden_older_eligible_summary")),
        "latest_candidate_per_customer_count": _int_value(
            scan.get("latest_candidate_per_customer_count") or eligible_total
        ),
        "focus_22530_22562_latest_decision": scan.get("focus_22530_22562_latest_decision") or {},
        "eligible_candidate_count_total": eligible_total,
        "eligible_candidate_count_before_second_order_rule": _int_value(
            scan.get("eligible_candidate_count_before_second_order_rule") or eligible_total
        ),
        "eligible_candidate_count_after_second_order_rule": _int_value(
            scan.get("eligible_candidate_count_after_second_order_rule") or eligible_total
        ),
        "second_or_later_delivered_candidate_count": _int_value(
            scan.get("second_or_later_delivered_candidate_count") or eligible_total
        ),
        "review_queue_batch_size": page_size,
        "review_queue_page_size": page_size,
        "review_queue_page": 1,
        "review_queue_total_pages": max((len(review_rows) + page_size - 1) // page_size, 1),
        "review_queue_has_previous": False,
        "review_queue_has_next": len(review_rows) > page_size,
        "review_queue_previous_page": 0,
        "review_queue_next_page": 2 if len(review_rows) > page_size else 0,
        "review_queue_previous_page_url": "",
        "review_queue_next_page_url": "?page=2&page_size=25" if len(review_rows) > page_size else "",
        "review_queue_showing_start": 1 if review_rows else 0,
        "review_queue_showing_end": min(page_size, len(review_rows)),
        "review_queue_visible_count": len(visible_review_rows),
        "review_queue_overflow_count": max(len(review_rows) - page_size, 0),
        "review_queue_page_size_options": [],
        "already_sent_page_size": page_size,
        "already_sent_page": 1,
        "already_sent_total_pages": max((len(already_sent_rows) + page_size - 1) // page_size, 1),
        "already_sent_has_previous": False,
        "already_sent_has_next": len(already_sent_rows) > page_size,
        "already_sent_previous_page": 0,
        "already_sent_next_page": 2 if len(already_sent_rows) > page_size else 0,
        "already_sent_previous_page_url": "",
        "already_sent_next_page_url": "?sent_page=2&sent_page_size=25" if len(already_sent_rows) > page_size else "",
        "already_sent_showing_start": 1 if already_sent_rows else 0,
        "already_sent_showing_end": min(page_size, len(already_sent_rows)),
        "already_sent_visible_count": len(visible_sent_rows),
        "already_sent_page_size_options": [],
        "sent_rows_with_time_count": _int_value(scan.get("sent_rows_with_time_count")),
        "sent_rows_without_time_count": _int_value(scan.get("sent_rows_without_time_count")),
        "latest_sent_order": _safe_text(scan.get("latest_sent_order"), max_length=80),
        "latest_sent_time": _safe_text(scan.get("latest_sent_time"), max_length=120),
        "latest_tag_write_time": _safe_text(scan.get("latest_tag_write_time"), max_length=120),
        "stale_counter_warning": scan.get("stale_counter_warning") is True,
        "stale_counter_warning_message": _safe_text(scan.get("stale_counter_warning_message"), max_length=160),
        "shopify_tag_write_enabled_count": 0,
        "empty_message": "No orders need review email right now.",
    }


def _dashboard_from_scan(
    scan: dict,
    coverage: dict,
    approval_queue: dict,
    eligible_total: int,
    blocked_total: int,
    already_sent_total: int,
) -> dict:
    order_data_coverage = {
        "incomplete": (scan.get("scan_source") != "full_shopify_orders"),
        "incomplete_message": "Order data is incomplete. Run the 60-day Shopify sync before trusting the candidate list.",
        "last_shopify_order_sync_window": coverage.get("last_shopify_order_sync_window") or "Unknown",
        "local_data_source_label": coverage.get("scan_source") or scan.get("scan_source") or "SQLite/report fallback",
        "selected_local_tag_field": coverage.get("selected_local_tag_field") or "ShopifyOrder.shopify_tags",
        "local_orders_with_shopify_tag_data": _int_value(coverage.get("local_orders_with_shopify_tag_data")),
        "order_22530_found_label": "Yes" if coverage.get("order_22530_found") is True else "No",
        "candidate_scan_freshness": scan.get("candidate_scan_freshness") or scan.get("scan_window_ended_at") or "Unknown",
        "last_sent_record_time": scan.get("latest_sent_time") or "Time not recorded",
        "last_tag_write_time": scan.get("latest_tag_write_time") or "Time not recorded",
        "stale_counter_warning": scan.get("stale_counter_warning") is True,
        "stale_counter_warning_message": scan.get("stale_counter_warning_message") or "",
        "warning_label": ", ".join(coverage.get("coverage_warnings") or []) or "None",
    }
    return {
        "ready_to_send_count": eligible_total,
        "blocked_count": blocked_total,
        "sent_trustpilot_count": already_sent_total,
        "approval_queue": approval_queue,
        "last_60_days_candidate_scan": _compact_scan_for_snapshot(scan),
        "order_data_coverage": order_data_coverage,
        "setup_checklist": {"items": []},
        "current_state_label": "Ready for final review" if eligible_total else "Waiting for eligible orders",
        "status_cards": [
            {
                "label": "Ready to send",
                "value": str(eligible_total),
                "message": "Cached snapshot queue.",
                "tone": "info",
            },
            {
                "label": "Blocked orders",
                "value": str(blocked_total),
                "message": "These orders are not safe to send yet.",
                "tone": "warn",
            },
            {
                "label": "Sent Trustpilot emails",
                "value": str(already_sent_total),
                "message": "Already sent",
                "tone": "ok",
            },
        ],
        "next_action_headline": "Nothing to send right now." if eligible_total == 0 else "Review the ready order before sending.",
        "send_requirements": [],
        "current_blockers": [],
        "blocked_order_rows": approval_queue.get("blocked_rows", []),
        "gmail_setup_ready": False,
        "gmail_setup_status_value": "Not checked in SQLite fallback",
        "gmail_setup_message": "Snapshot fallback did not evaluate Gmail setup.",
        "gmail_setup_rows": [],
        "gmail_draft_path": {},
        "gmail_draft_creation_readiness": {},
        "pipeline_steps": [],
        "trustpilot_automation": {},
        "trustpilot_send_readiness": {},
        "trustpilot_auto_refresh": {},
        "trustpilot_candidate_simulator": {},
        "trustpilot_gmail_send_gate": {},
        "trustpilot_gmail_send_executor_shell": {},
        "trustpilot_real_send_final_preflight": {},
        "trustpilot_real_send_execute": {},
        "trustpilot_gmail_real_send_readiness_audit": {},
        "trustpilot_gmail_oauth_config_helper": {},
        "trustpilot_gmail_config_compatibility_audit": {},
        "trustpilot_gmail_env_loading_audit": {},
        "trustpilot_gmail_scope_compatibility_resolver": {},
        "trustpilot_gmail_draft_only_preflight": {},
        "trustpilot_gmail_one_draft_create_locked_runner": {},
        "next_actions": [],
        "recent_activity": [],
        "ali_reviews_message": "Ali Reviews API is not connected yet.",
        "ali_reviews_status_label": "Unavailable",
    }


def _compact_scan_for_snapshot(scan: dict) -> dict:
    row_keys = {
        "eligible_queue_rows",
        "review_queue_rows",
        "blocked_queue_rows",
        "already_sent_queue_rows",
        "review_queue_candidates",
        "eligible_candidates_summary",
        "blocked_candidates_summary",
        "already_sent_summary",
    }
    compact = {}
    for key, value in (scan or {}).items():
        if key in row_keys:
            continue
        if isinstance(value, list) and len(value) > 50:
            compact[key] = value[:50]
            continue
        compact[key] = value
    return compact


def _snapshot_safety_confirmations() -> list[dict]:
    return [
        {"name": "Normal page load uses cached snapshot", "value": True},
        {"name": "Normal page load Shopify API call", "value": False},
        {"name": "Normal page load full scan", "value": False},
        {"name": "Gmail API call", "value": False},
        {"name": "External review API call", "value": False},
    ]


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
    for key in ("DOCKER_HOST", "DOCKER_TLS_VERIFY", "DOCKER_CERT_PATH", "DOCKER_CONFIG"):
        env.pop(key, None)
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
    failure_type = _safe_text(result.get("failure_type") or "dashboard_snapshot_refresh_failed")
    return {
        "timestamp": utc_now_iso(),
        "generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.32",
        "mode": "dry-run-local-dashboard-snapshot-refresh",
        "command_label": COMMAND_LABEL,
        "snapshot_status": failure_type,
        "report_status": failure_type,
        "success": False,
        "eligible_total": 0,
        "review_queue_candidates": [],
        "already_sent_rows": [],
        "blocked_summary": {"blocked_total": 0, "rows": []},
        "dashboard_counters": {},
        "stale_after_minutes": 240,
        "scan_report_source": "unavailable",
        "last_shopify_sync_at": "",
        "last_candidate_scan_at": "",
        "django_snapshot_exit_code": int(result.get("exit_code") or 1),
        "django_snapshot_failure_type": failure_type,
        "django_snapshot_stdout_tail": _tail_text(result.get("stdout", "")),
        "django_snapshot_stderr_tail": _tail_text(result.get("stderr", "")),
        "normal_page_load_shopify_api_call_performed": False,
        "normal_page_load_full_scan_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "translations_register_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secret_values_printed": False,
        "duration_seconds": duration_seconds,
        "detected_issue_summary": (
            f"Dashboard snapshot refresh failed before writing a usable cache: {failure_type}. "
            "No Shopify API, Gmail API, external review API, email send, or Shopify write was performed."
        ),
    }


def _write_reports(payload: dict) -> dict:
    json_main_path, json_mirror_paths = _snapshot_write_paths(REPORT_JSON_PATH.name)
    html_main_path, html_mirror_paths = _snapshot_write_paths(REPORT_HTML_PATH.name)
    payload["snapshot_main_path"] = str(json_main_path)
    payload["snapshot_mirror_paths_written"] = []
    payload["snapshot_paths_failed"] = []
    payload["snapshot_html_main_path"] = str(html_main_path)
    payload["snapshot_html_mirror_paths_written"] = []
    payload["snapshot_html_paths_failed"] = []
    payload["page_expected_paths"] = [
        _display_path(path) for path in _snapshot_read_candidate_paths(REPORT_JSON_PATH.name)
    ]

    json_result = _write_json_to_paths(payload, json_main_path, json_mirror_paths)
    html_result = _write_html_to_paths(payload, html_main_path, html_mirror_paths)
    payload["snapshot_mirror_paths_written"] = [str(path) for path in json_result["mirror_paths_written"]]
    payload["snapshot_paths_failed"] = json_result["paths_failed"]
    payload["snapshot_html_mirror_paths_written"] = [
        str(path) for path in html_result["mirror_paths_written"]
    ]
    payload["snapshot_html_paths_failed"] = html_result["paths_failed"]
    json_result = _write_json_to_paths(payload, json_main_path, json_mirror_paths)
    payload["snapshot_mirror_paths_written"] = [str(path) for path in json_result["mirror_paths_written"]]
    payload["snapshot_paths_failed"] = json_result["paths_failed"]
    return {"json_path": json_main_path, "html_path": html_main_path}


def _snapshot_read_candidate_paths(filename: str) -> list[Path]:
    paths = []
    env_path = _snapshot_env_path(filename)
    if env_path:
        paths.append(env_path)
    paths.extend(
        [
            Path("/app/logs") / filename,
            Path("/app/backend/logs") / filename,
            PROJECT_ROOT / "logs" / filename,
            PROJECT_ROOT / "backend" / "logs" / filename,
        ]
    )
    return _dedupe_paths(paths)


def _snapshot_write_paths(filename: str) -> tuple[Path, list[Path]]:
    main_path = _snapshot_env_path(filename) or (PROJECT_ROOT / "logs" / filename)
    mirror_candidates = [
        PROJECT_ROOT / "logs" / filename,
        Path("/app/logs") / filename,
        Path("/app/backend/logs") / filename,
        PROJECT_ROOT / "backend" / "logs" / filename,
    ]
    mirrors = []
    for path in _dedupe_paths(mirror_candidates):
        if _path_identity(path) == _path_identity(main_path):
            continue
        if path.parent.exists():
            mirrors.append(path)
    return main_path, mirrors


def _snapshot_env_path(filename: str) -> Path | None:
    raw_path = os.environ.get(SNAPSHOT_ENV_PATH, "").strip()
    if not raw_path:
        return None
    path = Path(raw_path).expanduser()
    if _path_looks_like_directory(path, raw_path):
        return path / filename
    if filename == REPORT_HTML_PATH.name and path.suffix:
        return path.with_suffix(".html")
    return path


def _path_looks_like_directory(path: Path, raw_path: str) -> bool:
    if raw_path.endswith(("/", "\\")):
        return True
    try:
        if path.exists() and path.is_dir():
            return True
    except OSError:
        return False
    return not path.suffix


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen = set()
    deduped = []
    for path in paths:
        identity = _path_identity(path)
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(path)
    return deduped


def _path_identity(path: Path) -> str:
    try:
        resolved = path.expanduser().resolve(strict=False)
    except OSError:
        resolved = path
    text = str(resolved)
    return text.lower() if os.name == "nt" else text


def _display_path(path: Path) -> str:
    text = str(path)
    normalized = text.replace("\\", "/")
    if normalized.startswith("/app/") or normalized.startswith("/logs/"):
        return normalized
    return text


def _write_json_to_paths(payload: dict, main_path: Path, mirror_paths: list[Path]) -> dict:
    main_path.parent.mkdir(parents=True, exist_ok=True)
    _write_json_file(main_path, payload)
    paths_failed = []
    written_mirrors = []
    for path in mirror_paths:
        try:
            _write_json_file(path, payload)
        except OSError as exc:
            paths_failed.append({"path": str(path), "error": _safe_text(str(exc), max_length=300)})
            continue
        written_mirrors.append(path)
    return {"mirror_paths_written": written_mirrors, "paths_failed": paths_failed}


def _write_json_file(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    json.loads(path.read_text(encoding="utf-8"))


def _write_html_to_paths(payload: dict, main_path: Path, mirror_paths: list[Path]) -> dict:
    html = _render_html(payload)
    main_path.parent.mkdir(parents=True, exist_ok=True)
    main_path.write_text(html, encoding="utf-8")
    paths_failed = []
    written_mirrors = []
    for path in mirror_paths:
        try:
            path.write_text(html, encoding="utf-8")
        except OSError as exc:
            paths_failed.append({"path": str(path), "error": _safe_text(str(exc), max_length=300)})
            continue
        written_mirrors.append(path)
    return {"mirror_paths_written": written_mirrors, "paths_failed": paths_failed}


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    counters = payload.get("dashboard_counters") if isinstance(payload.get("dashboard_counters"), dict) else {}
    blocked = payload.get("blocked_summary") if isinstance(payload.get("blocked_summary"), dict) else {}
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "status": payload.get("snapshot_status") or payload.get("report_status"),
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "review_file_path": str(json_path),
        "json_report_path": str(json_path),
        "html_report_path": str(html_path),
        "snapshot_main_path": payload.get("snapshot_main_path") or str(json_path),
        "snapshot_mirror_paths_written": payload.get("snapshot_mirror_paths_written") or [],
        "snapshot_paths_failed": payload.get("snapshot_paths_failed") or [],
        "snapshot_html_main_path": payload.get("snapshot_html_main_path") or str(html_path),
        "snapshot_html_mirror_paths_written": payload.get("snapshot_html_mirror_paths_written") or [],
        "snapshot_html_paths_failed": payload.get("snapshot_html_paths_failed") or [],
        "page_expected_paths": payload.get("page_expected_paths") or [],
        "eligible_total": _int_value(payload.get("eligible_total")),
        "eligible_candidate_count_before_second_order_rule": _int_value(
            counters.get("eligible_candidate_count_before_second_order_rule")
        ),
        "eligible_candidate_count_after_second_order_rule": _int_value(
            counters.get("eligible_candidate_count_after_second_order_rule")
        ),
        "needs_review_visible_count": _int_value(counters.get("needs_review_visible_count")),
        "already_sent_total": _int_value(counters.get("already_sent_total")),
        "blocked_total": _int_value(blocked.get("blocked_total")),
        "blocked_first_order_count": _int_value(blocked.get("blocked_first_order_count")),
        "blocked_not_second_or_later_count": _int_value(blocked.get("blocked_not_second_or_later_count")),
        "blocked_second_order_not_delivered_count": _int_value(
            blocked.get("blocked_second_order_not_delivered_count")
        ),
        "stale_counter_warning": False,
        "shopify_api_call_performed": payload.get("shopify_api_call_performed") is True,
        "shopify_write_performed": payload.get("shopify_write_performed") is True,
        "gmail_api_call_performed": payload.get("gmail_api_call_performed") is True,
        "external_review_api_call_performed": payload.get("external_review_api_call_performed") is True,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    counters = payload.get("dashboard_counters") if isinstance(payload.get("dashboard_counters"), dict) else {}
    mirror_paths = payload.get("snapshot_mirror_paths_written") or []
    page_paths = payload.get("page_expected_paths") or []
    return (
        "Review Request dashboard snapshot refresh complete.\n\n"
        f"Status: {payload.get('snapshot_status')}\n"
        f"Eligible total: {payload.get('eligible_total', 0)}\n"
        f"Eligible before second-order rule: {counters.get('eligible_candidate_count_before_second_order_rule', 0)}\n"
        f"Eligible after second-order rule: {counters.get('eligible_candidate_count_after_second_order_rule', payload.get('eligible_total', 0))}\n"
        f"Needs review visible count: {counters.get('needs_review_visible_count', 0)}\n"
        f"Already sent total: {counters.get('already_sent_total', 0)}\n"
        f"Last Shopify sync: {payload.get('last_shopify_sync_at') or 'Unknown'}\n"
        f"Last candidate scan: {payload.get('last_candidate_scan_at') or 'Unknown'}\n\n"
        "Safety: no Shopify API call, no Shopify write, no Gmail API call, no email send, "
        "no Trustpilot/Kudosi/Ali Reviews API call, no translationsRegister.\n\n"
        f"JSON snapshot: {json_path}\n"
        f"HTML snapshot: {html_path}\n"
        f"JSON mirrors written: {', '.join(mirror_paths) if mirror_paths else 'None'}\n"
        f"Page expected paths: {', '.join(page_paths) if page_paths else 'None'}\n\n"
        "Choose Y/1 to keep the snapshot report, or N/0 to stop."
    )


def _render_html(payload: dict) -> str:
    counters = payload.get("dashboard_counters") if isinstance(payload.get("dashboard_counters"), dict) else {}
    blocked = payload.get("blocked_summary") if isinstance(payload.get("blocked_summary"), dict) else {}
    safety_rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(payload.get(key) is True))}</td></tr>"
        for label, key in (
            ("Shopify API call performed", "shopify_api_call_performed"),
            ("Shopify write performed", "shopify_write_performed"),
            ("Gmail API call performed", "gmail_api_call_performed"),
            ("Email sent", "email_sent"),
            ("External review API call performed", "external_review_api_call_performed"),
            ("translationsRegister called", "translations_register_called"),
            ("Raw customer email output", "raw_customer_email_output"),
            ("Secret values printed", "secret_values_printed"),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Dashboard Snapshot</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; line-height: 1.45; }}
    table {{ border-collapse: collapse; width: 100%; margin: 16px 0; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f6f6; }}
    .ok {{ color: #166534; font-weight: 700; }}
    .warn {{ color: #92400e; font-weight: 700; }}
  </style>
</head>
<body>
  <h1>Review Request Dashboard Snapshot</h1>
  <p class="{'ok' if payload.get('success') is True else 'warn'}">{escape(str(payload.get('snapshot_status', 'unknown')))}</p>
  <table>
    <tbody>
      <tr><th>Generated at</th><td>{escape(str(payload.get('generated_at', '')))}</td></tr>
      <tr><th>Generated by</th><td>{escape(str(payload.get('generated_by', '')))}</td></tr>
      <tr><th>Sync source</th><td>{escape(str(payload.get('sync_source', '')))}</td></tr>
      <tr><th>Scan report source</th><td>{escape(str(payload.get('scan_report_source', '')))}</td></tr>
      <tr><th>Last Shopify sync</th><td>{escape(str(payload.get('last_shopify_sync_at', '')))}</td></tr>
      <tr><th>Last candidate scan</th><td>{escape(str(payload.get('last_candidate_scan_at', '')))}</td></tr>
      <tr><th>Eligible total</th><td>{escape(str(payload.get('eligible_total', 0)))}</td></tr>
      <tr><th>Eligible before second-order rule</th><td>{escape(str(counters.get('eligible_candidate_count_before_second_order_rule', 0)))}</td></tr>
      <tr><th>Eligible after second-order rule</th><td>{escape(str(counters.get('eligible_candidate_count_after_second_order_rule', payload.get('eligible_total', 0))))}</td></tr>
      <tr><th>Needs review visible count</th><td>{escape(str(counters.get('needs_review_visible_count', 0)))}</td></tr>
      <tr><th>Already sent total</th><td>{escape(str(counters.get('already_sent_total', 0)))}</td></tr>
      <tr><th>Blocked total</th><td>{escape(str(blocked.get('blocked_total', 0)))}</td></tr>
      <tr><th>Blocked first-order count</th><td>{escape(str(blocked.get('blocked_first_order_count', 0)))}</td></tr>
      <tr><th>Blocked not second-or-later count</th><td>{escape(str(blocked.get('blocked_not_second_or_later_count', 0)))}</td></tr>
      <tr><th>Blocked second-order not delivered count</th><td>{escape(str(blocked.get('blocked_second_order_not_delivered_count', 0)))}</td></tr>
      <tr><th>Stale after minutes</th><td>{escape(str(payload.get('stale_after_minutes', '')))}</td></tr>
    </tbody>
  </table>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>
"""


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_email_count = len(EMAIL_RE.findall(text))
    secret_marker_count = len(SECRET_RE.findall(text))
    return {
        "passed": raw_email_count == 0 and secret_marker_count == 0,
        "raw_email_count": raw_email_count,
        "secret_marker_count": secret_marker_count,
        "raw_email_output": raw_email_count > 0,
        "secret_output": secret_marker_count > 0,
    }


def _redact_payload_for_privacy(value):
    if isinstance(value, dict):
        return {str(key): _redact_payload_for_privacy(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact_payload_for_privacy(item) for item in value]
    if isinstance(value, str):
        text = EMAIL_RE.sub("[masked-email]", value)
        text = SECRET_RE.sub("[secret-redacted]", text)
        return text
    return value


def _safe_rows(value) -> list[dict]:
    return [dict(row) for row in (value or []) if isinstance(row, dict)]


def _safe_text(value, max_length: int = 1000) -> str:
    if value is None:
        return ""
    text = str(value).replace("\x00", "")
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _tail_text(value, max_lines: int = 80) -> str:
    text = _safe_text(value, max_length=12000)
    return "\n".join(text.splitlines()[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _int_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
