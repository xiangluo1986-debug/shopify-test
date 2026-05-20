import json
import re
import time
from datetime import datetime, timezone
from html import escape

from backend.shopify_sync.review_request_history_ledger import load_customer_history_lookup_cache
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_live_history_gate_audit"
COMMAND_LABEL = "shopify_review_request_live_history_gate_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_live_history_gate_audit.json"
REPORT_HTML_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_live_history_gate_audit.html"
LAST_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
DASHBOARD_SNAPSHOT_JSON_PATH = LOG_DIR / "shopify_review_request_dashboard_snapshot.json"
TARGET_ORDER = "#21687"
MAX_REPORT_BYTES = 8 * 1024 * 1024

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


def run_shopify_review_request_live_history_gate_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    payload = _build_payload()
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["privacy_scan_summary"] = _privacy_scan(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["audit_status"] = "blocked_privacy_scan_failed"
        payload["report_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["detected_issue_summary"] = "Live history gate audit privacy scan failed."

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _build_payload() -> dict:
    cache = load_customer_history_lookup_cache(LOG_DIR)
    lookup = (cache.get("orders") or {}).get(TARGET_ORDER, {})
    scan = _read_json(LAST_SCAN_JSON_PATH)
    snapshot = _read_json(DASHBOARD_SNAPSHOT_JSON_PATH)

    scan_review_rows = _safe_rows(scan.get("review_queue_candidates") or scan.get("eligible_candidates_summary"))
    scan_blocked_rows = _safe_rows(scan.get("blocked_candidates_summary"))
    snapshot_review_rows = _snapshot_review_rows(snapshot)
    snapshot_blocked_rows = _snapshot_blocked_rows(snapshot)
    review_rows = snapshot_review_rows or scan_review_rows
    blocked_rows = snapshot_blocked_rows or scan_blocked_rows

    target_review_rows = [row for row in review_rows if _row_order(row) == TARGET_ORDER]
    target_blocked_rows = [row for row in blocked_rows if _row_order(row) == TARGET_ORDER]
    evidence_found = bool(
        lookup.get("trustpilot_note_evidence_found") is True
        or lookup.get("trustpilot_tag_evidence_found") is True
    )
    live_shopify_count = _int_value(lookup.get("shopify_customer_history_count"))
    local_order_count = _int_value(
        scan.get("#21687_customer_history_order_count")
        or ((scan.get("order_21687_diagnosis") or {}).get("customer_history_order_count"))
    )
    visible_missing_live_lookup_count = _visible_missing_live_lookup_count(review_rows)
    blocked_missing_stale_count = _blocked_missing_stale_count(blocked_rows)

    removed_from_needs_review = not target_review_rows
    review_send_disabled = removed_from_needs_review
    payload = {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.32E",
        "mode": "dry-run-local-live-history-gate-audit",
        "command_label": COMMAND_LABEL,
        "audit_status": "live_history_gate_audit_ready",
        "report_status": "live_history_gate_audit_ready",
        "success": True,
        "target_order": TARGET_ORDER,
        "order_21687_live_lookup_cache_found": bool(lookup),
        "order_21687_live_shopify_order_count": live_shopify_count,
        "order_21687_local_order_count": local_order_count,
        "order_21687_evidence_found": evidence_found,
        "order_21687_trustpilot_note_evidence_found": lookup.get("trustpilot_note_evidence_found") is True,
        "order_21687_trustpilot_tag_evidence_found": lookup.get("trustpilot_tag_evidence_found") is True,
        "order_21687_evidence_order": _safe_text(lookup.get("evidence_order_name"), 80),
        "order_21687_safe_keyword": _safe_text(lookup.get("safe_detected_keyword"), 80),
        "order_21687_blocking_reason": _safe_text(lookup.get("blocking_reason"), 300),
        "order_21687_removed_from_needs_review": removed_from_needs_review,
        "order_21687_present_in_blocked_or_not_ready": bool(target_blocked_rows),
        "order_21687_review_send_disabled": review_send_disabled,
        "visible_rows_missing_live_lookup_count": visible_missing_live_lookup_count,
        "visible_rows_blocked_by_stale_or_missing_live_lookup_count": blocked_missing_stale_count,
        "visible_review_send_count": len(review_rows),
        "blocked_or_not_ready_visible_count": len(blocked_rows),
        "scan_report_loaded": bool(scan),
        "dashboard_snapshot_loaded": bool(snapshot),
        "lookup_cache_loaded": cache.get("loaded") is True,
        "lookup_cache_found": cache.get("present") is True,
        "lookup_cache_path": cache.get("relative_path", ""),
        "last_scan_path": f"logs/{LAST_SCAN_JSON_PATH.name}",
        "dashboard_snapshot_path": f"logs/{DASHBOARD_SNAPSHOT_JSON_PATH.name}",
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "translations_register_called": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
    }
    payload["detected_issue_summary"] = (
        f"{TARGET_ORDER} live lookup cache found={payload['order_21687_live_lookup_cache_found']}; "
        f"live Shopify order count={live_shopify_count}; evidence found={evidence_found}; "
        f"removed from Needs review={removed_from_needs_review}; "
        f"Review & Send disabled={review_send_disabled}. "
        "Audit read local reports only and performed no Gmail, Shopify, external review API, mutation, or translationsRegister call."
    )
    return payload


def _snapshot_review_rows(snapshot: dict) -> list[dict]:
    if not snapshot:
        return []
    rows = _safe_rows(snapshot.get("review_queue_candidates"))
    if rows:
        return rows
    workbench = (snapshot.get("review_request_workbench") or {}) if isinstance(snapshot, dict) else {}
    dashboard = (workbench.get("operating_dashboard") or {}) if isinstance(workbench, dict) else {}
    queue = (dashboard.get("approval_queue") or {}) if isinstance(dashboard, dict) else {}
    return _safe_rows(queue.get("needs_review_rows") or queue.get("all_needs_review_rows"))


def _snapshot_blocked_rows(snapshot: dict) -> list[dict]:
    if not snapshot:
        return []
    blocked_summary = snapshot.get("blocked_summary") or {}
    rows = _safe_rows(blocked_summary.get("rows"))
    if rows:
        return rows
    workbench = (snapshot.get("review_request_workbench") or {}) if isinstance(snapshot, dict) else {}
    dashboard = (workbench.get("operating_dashboard") or {}) if isinstance(workbench, dict) else {}
    queue = (dashboard.get("approval_queue") or {}) if isinstance(dashboard, dict) else {}
    return _safe_rows(queue.get("blocked_rows"))


def _visible_missing_live_lookup_count(rows: list[dict]) -> int:
    count = 0
    for row in rows:
        if row.get("cached_customer_history_lookup_found") is True and row.get("full_history_confirmed") is True:
            continue
        count += 1
    return count


def _blocked_missing_stale_count(rows: list[dict]) -> int:
    blocked_statuses = {"missing", "stale", "incomplete"}
    return sum(
        1
        for row in rows
        if row.get("customer_history_lookup_block_status") in blocked_statuses
        or (
            row.get("blocked_by_customer_history_lookup") is True
            and _safe_text(row.get("reason") or row.get("block_reason"), 300)
            in {
                "Customer history needs live Shopify check before sending.",
                "Customer history check is stale.",
                "Customer history could not be fully verified.",
            }
        )
    )


def _row_order(row: dict) -> str:
    return _safe_text(row.get("order") or row.get("order_name") or row.get("candidate_id"), 80)


def _read_json(path) -> dict:
    try:
        if not path.exists() or path.stat().st_size > MAX_REPORT_BYTES:
            return {}
        value = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _safe_rows(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [dict(row) for row in value if isinstance(row, dict)]


def _write_json(payload: dict):
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report:
        json.dump(payload, report, ensure_ascii=False, indent=2, sort_keys=True)
        report.write("\n")
    return REPORT_JSON_PATH


def _write_html(payload: dict):
    REPORT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html(payload: dict) -> str:
    rows = [
        ("Audit status", payload.get("audit_status")),
        ("#21687 cache found", payload.get("order_21687_live_lookup_cache_found")),
        ("#21687 live Shopify count", payload.get("order_21687_live_shopify_order_count")),
        ("#21687 local count", payload.get("order_21687_local_order_count")),
        ("Evidence found", payload.get("order_21687_evidence_found")),
        ("Evidence order", payload.get("order_21687_evidence_order")),
        ("Safe keyword", payload.get("order_21687_safe_keyword")),
        ("Removed from Needs review", payload.get("order_21687_removed_from_needs_review")),
        ("Review & Send disabled", payload.get("order_21687_review_send_disabled")),
        ("Visible rows missing live lookup", payload.get("visible_rows_missing_live_lookup_count")),
        (
            "Rows blocked by stale/missing lookup",
            payload.get("visible_rows_blocked_by_stale_or_missing_live_lookup_count"),
        ),
    ]
    table = "\n".join(
        f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Shopify Review Request Live History Gate Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; line-height: 1.45; }}
    table {{ border-collapse: collapse; width: 100%; max-width: 960px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px 10px; text-align: left; }}
    th {{ width: 320px; background: #f6f8fa; }}
    .note {{ margin: 0 0 16px; padding: 10px 12px; background: #f6f8fa; border-left: 4px solid #0969da; }}
  </style>
</head>
<body>
  <h1>Live History Gate Audit</h1>
  <p class="note">Local report audit only. No Gmail API, Shopify API, Shopify write, mutation, external review API, or translationsRegister call was performed.</p>
  <table><tbody>{table}</tbody></table>
</body>
</html>
"""


def _task_result(payload: dict, json_path, html_path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "status": payload.get("audit_status", "unknown"),
        "command_label": COMMAND_LABEL,
        "review_file_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "order_21687_live_shopify_order_count": payload.get("order_21687_live_shopify_order_count"),
        "order_21687_evidence_order": payload.get("order_21687_evidence_order"),
        "order_21687_safe_keyword": payload.get("order_21687_safe_keyword"),
        "order_21687_removed_from_needs_review": payload.get("order_21687_removed_from_needs_review"),
        "order_21687_review_send_disabled": payload.get("order_21687_review_send_disabled"),
        "visible_rows_missing_live_lookup_count": payload.get("visible_rows_missing_live_lookup_count"),
        "visible_rows_blocked_by_stale_or_missing_live_lookup_count": payload.get(
            "visible_rows_blocked_by_stale_or_missing_live_lookup_count"
        ),
        "gmail_api_call_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
    }


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return {
        "passed": not EMAIL_RE.search(text) and not SECRET_RE.search(text),
        "raw_email_found": bool(EMAIL_RE.search(text)),
        "secret_marker_found": bool(SECRET_RE.search(text)),
    }


def _safe_text(value, max_length: int = 300) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:max_length]


def _int_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
