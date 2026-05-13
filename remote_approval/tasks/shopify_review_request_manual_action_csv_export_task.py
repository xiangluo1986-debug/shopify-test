import csv
import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_manual_action_csv_export"
COMMAND_LABEL = "shopify_review_request_manual_action_csv_export_no_write"
SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_manual_action_package.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_manual_action_csv_export.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_manual_action_csv_export.html"
CSV_EXPORT_PATH = LOG_DIR / "shopify_review_request_manual_action_export.csv"

CSV_COLUMNS = [
    "bucket",
    "order_name",
    "order_id_or_gid",
    "masked_email",
    "classification",
    "suggested_action",
    "ticket_risk_summary",
    "repeat_customer_count",
    "tags_summary",
    "source_reason",
    "manual_notes",
]

ACTION_BUCKETS = [
    "manual_ali_reviews_check_required",
    "repeat_customer_trustpilot_candidates",
    "blocked_by_ticket",
    "blocked_no_email",
    "blocked_returned_package",
    "blocked_refunded_or_partially_refunded",
    "existing_review_request_tag_present",
    "needs_manual_review",
]

SUGGESTED_ACTIONS = {
    "manual_ali_reviews_check_required": "Check Ali Reviews/Kudosi manually before sending product review request",
    "repeat_customer_trustpilot_candidates": "Review manually for future Trustpilot invitation; do not send automatically yet",
    "blocked_by_ticket": "Do not send; open/unresolved ticket risk",
    "blocked_no_email": "Do not send; no usable email",
    "blocked_returned_package": "Do not send; return/returned package tag blocks review request",
    "blocked_refunded_or_partially_refunded": "Do not send; refund/partial refund risk",
    "existing_review_request_tag_present": "Do not send automatically; existing Shopify review request tag present",
    "needs_manual_review": "Manual review required before any review request",
}

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\s-]?token|api[_\s-]?key|password|secret)"
)


def run_shopify_review_request_manual_action_csv_export_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error = _load_source_report()
    rows = _build_rows(source_report) if _source_ready(source_report, source_error) else []
    _write_csv(rows)
    csv_masking = _validate_csv_masking(CSV_EXPORT_PATH)
    payload = _build_payload(source_report, source_error, rows, csv_masking, round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_source_report() -> tuple[dict, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "source_manual_action_package_missing"
    try:
        return json.loads(SOURCE_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, f"source_manual_action_package_json_parse_error: {exc}"


def _source_ready(source_report: dict, source_error: str) -> bool:
    return (
        not source_error
        and source_report.get("task_name") == "shopify_review_request_manual_action_package"
        and str(source_report.get("phase")) == "1.2"
        and source_report.get("manual_action_package_status") == "manual_action_package_ready"
        and source_report.get("success") is True
    )


def _build_rows(source_report: dict) -> list[dict]:
    rows = []
    sections = source_report.get("manual_action_sections") or {}
    for bucket in ACTION_BUCKETS:
        entries = sections.get(bucket) if isinstance(sections.get(bucket), list) else []
        for entry in entries:
            rows.append(_row_from_entry(bucket, entry))
    return rows


def _row_from_entry(bucket: str, entry: dict) -> dict:
    return {
        "bucket": bucket,
        "order_name": _safe_text(entry.get("order_name", "")),
        "order_id_or_gid": _safe_text(entry.get("order_id", "")),
        "masked_email": _safe_masked_email(entry.get("masked_email", "")),
        "classification": _safe_text(entry.get("classification", "")),
        "suggested_action": SUGGESTED_ACTIONS[bucket],
        "ticket_risk_summary": _ticket_risk_summary_text(entry.get("ticket_risk_summary", {})),
        "repeat_customer_count": _repeat_count_text(entry),
        "tags_summary": _tags_summary_text(entry.get("tags_summary", {})),
        "source_reason": _source_reason_text(entry.get("classification_reasons", [])),
        "manual_notes": "",
    }


def _ticket_risk_summary_text(summary: dict) -> str:
    if not isinstance(summary, dict):
        return ""
    parts = [
        f"ticket_match_detected={bool(summary.get('ticket_match_detected'))}",
        f"ticket_blocked={bool(summary.get('ticket_blocked'))}",
    ]
    reason = _safe_text(summary.get("ticket_blocking_reason", ""))
    if reason:
        parts.append(f"reason={reason}")
    categories = [_safe_text(item) for item in summary.get("ticket_risk_categories", [])]
    if categories:
        parts.append("risk_categories=" + "|".join(categories))
    status_bits = []
    for item in summary.get("ticket_status_summary", [])[:5]:
        status_bits.append(
            "/".join(
                _safe_text(value)
                for value in [
                    item.get("ticket_id", ""),
                    item.get("status", ""),
                    item.get("status_category", ""),
                    item.get("priority", ""),
                ]
                if _safe_text(value)
            )
        )
    if status_bits:
        parts.append("tickets=" + ";".join(status_bits))
    return _safe_text("; ".join(parts))


def _repeat_count_text(entry: dict) -> str:
    count = entry.get("customer_repeat_count")
    if isinstance(count, int):
        return str(count)
    return "repeat_detected" if entry.get("repeat_customer_detected") else ""


def _tags_summary_text(summary: dict) -> str:
    if not isinstance(summary, dict):
        return ""
    tags = [_safe_text(tag) for tag in summary.get("safe_tags", [])]
    interest = [_safe_text(tag) for tag in summary.get("exact_tags_of_interest", [])]
    parts = [f"tag_count={len(tags)}"]
    if interest:
        parts.append("tags_of_interest=" + "|".join(interest))
    if tags:
        parts.append("safe_tags=" + "|".join(tags))
    return _safe_text("; ".join(parts))


def _source_reason_text(reasons: list) -> str:
    return _safe_text(" | ".join(_safe_text(reason) for reason in reasons))


def _build_payload(
    source_report: dict,
    source_error: str,
    rows: list[dict],
    csv_masking: dict,
    duration_seconds: float,
) -> dict:
    source_ready = _source_ready(source_report, source_error)
    rows_by_bucket = {bucket: 0 for bucket in ACTION_BUCKETS}
    for row in rows:
        rows_by_bucket[row["bucket"]] += 1
    status = "csv_export_ready" if source_ready and csv_masking["csv_contains_only_masked_emails"] else "blocked_csv_export_source_not_ready"
    safety = _safety_summary()
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "1.3",
        "mode": "no-write-manual-action-csv-export",
        "command_label": COMMAND_LABEL,
        "csv_export_status": status,
        "success": status == "csv_export_ready",
        "source_path": str(SOURCE_JSON_PATH),
        "source_manual_action_package_status": source_report.get("manual_action_package_status", ""),
        "source_scanner_version": source_report.get("source_scanner_version", ""),
        "source_error_sanitized": _sanitize_text(source_error),
        "total_rows_exported": len(rows),
        "rows_by_bucket": rows_by_bucket,
        "csv_columns": CSV_COLUMNS,
        "csv_path": str(CSV_EXPORT_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "csv_email_masking_validation": csv_masking,
        "preview_rows": rows[:25],
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_email_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
            "private_customer_notes_output": False,
        },
        "safety_summary": safety,
        **safety,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, len(rows), rows_by_bucket, source_error, csv_masking),
        "duration_seconds": duration_seconds,
    }


def _write_csv(rows: list[dict]) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with CSV_EXPORT_PATH.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in CSV_COLUMNS})
    return CSV_EXPORT_PATH


def _validate_csv_masking(path: Path) -> dict:
    if not path.exists():
        return {
            "csv_contains_only_masked_emails": False,
            "raw_email_like_value_count": 0,
            "masked_email_like_value_count": 0,
            "csv_validation_error_sanitized": "CSV file was not created.",
        }
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    email_like_values = EMAIL_RE.findall(text)
    raw_values = [value for value in email_like_values if "***" not in value]
    return {
        "csv_contains_only_masked_emails": not raw_values,
        "raw_email_like_value_count": len(raw_values),
        "masked_email_like_value_count": len(email_like_values) - len(raw_values),
        "csv_validation_error_sanitized": "",
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_manual_action_csv_export_path": str(json_path),
        "html_manual_action_csv_export_path": str(html_path),
        "csv_manual_action_export_path": str(CSV_EXPORT_PATH),
        "csv_export_status": payload["csv_export_status"],
        "source_manual_action_package_status": payload["source_manual_action_package_status"],
        "source_scanner_version": payload["source_scanner_version"],
        "total_rows_exported": payload["total_rows_exported"],
        "rows_by_bucket": payload["rows_by_bucket"],
        "csv_contains_only_masked_emails": payload["csv_email_masking_validation"]["csv_contains_only_masked_emails"],
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "ali_reviews_api_call_performed": False,
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
    bucket_rows = "\n".join(
        f"<tr><td><code>{escape(bucket)}</code></td><td>{count}</td></tr>"
        for bucket, count in payload["rows_by_bucket"].items()
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    preview_rows = "\n".join(_render_preview_row(row) for row in payload["preview_rows"])
    if not preview_rows:
        preview_rows = '<tr><td colspan="7">No preview rows available.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Manual Action CSV Export</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Review Request Manual Action CSV Export</h1>
  <p class="warning">Phase 1.3 is local export-only. No review request was sent and no Shopify tag was changed.</p>
  <p>Status: <strong>{escape(str(payload["csv_export_status"]))}</strong></p>
  <p>CSV path: <code>{escape(str(payload["csv_path"]))}</code></p>
  <p>Total rows exported: {payload["total_rows_exported"]}</p>
  <h2>Rows by Bucket</h2>
  <table><thead><tr><th>Bucket</th><th>Rows</th></tr></thead><tbody>{bucket_rows}</tbody></table>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <h2>Preview</h2>
  <table>
    <thead><tr><th>Bucket</th><th>Order</th><th>Masked email</th><th>Classification</th><th>Suggested action</th><th>Ticket risk</th><th>Reason</th></tr></thead>
    <tbody>{preview_rows}</tbody>
  </table>
</body>
</html>"""


def _render_preview_row(row: dict) -> str:
    return f"""<tr>
  <td><code>{escape(str(row.get("bucket", "")))}</code></td>
  <td>{escape(str(row.get("order_name", "")))}<br><code>{escape(str(row.get("order_id_or_gid", "")))}</code></td>
  <td>{escape(str(row.get("masked_email", "")))}</td>
  <td><code>{escape(str(row.get("classification", "")))}</code></td>
  <td>{escape(str(row.get("suggested_action", "")))}</td>
  <td>{escape(str(row.get("ticket_risk_summary", "")))}</td>
  <td>{escape(str(row.get("source_reason", "")))}</td>
</tr>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 1.3 manual action CSV export finished.\n"
        f"Status: {payload.get('csv_export_status')}\n"
        f"Rows exported: {payload.get('total_rows_exported')}\n"
        f"Rows by bucket: {json.dumps(payload.get('rows_by_bucket', {}), ensure_ascii=False)}\n"
        f"CSV masking valid: {payload.get('csv_email_masking_validation', {}).get('csv_contains_only_masked_emails')}\n"
        "Safety: local export only; no Shopify API call, no Shopify writes, no tagsAdd/tagsRemove, no Ali Reviews API, no Gmail API, and no email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n"
        f"CSV export: {CSV_EXPORT_PATH}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, row_count: int, rows_by_bucket: dict, source_error: str, csv_masking: dict) -> str:
    if status == "csv_export_ready":
        return f"Manual action CSV export created with {row_count} rows across {len(rows_by_bucket)} buckets."
    if not csv_masking.get("csv_contains_only_masked_emails", False):
        return "Manual action CSV export blocked because CSV email masking validation failed."
    return f"Manual action CSV export blocked because the Phase 1.2 source report is not ready: {_sanitize_text(source_error)}"


def _safety_summary() -> dict:
    return {
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
    }


def _safe_masked_email(value: str) -> str:
    value = _safe_text(value)
    if not value or "@" not in value:
        return ""
    if "***" in value:
        return value
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), value)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _safe_text(value) -> str:
    text = str(value or "")
    text = text.encode("utf-8", errors="replace").decode("utf-8", errors="replace")
    return _sanitize_text(text)


def _sanitize_text(text: str) -> str:
    redacted = SENSITIVE_TEXT_RE.sub("[redacted]", text or "")
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)
