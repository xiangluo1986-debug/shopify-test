import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_manual_action_package"
COMMAND_LABEL = "shopify_review_request_manual_action_package_no_write"
SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_candidate_scan.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_manual_action_package.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_manual_action_package.html"

EXACT_REVIEW_REQUEST_TAG = "1: reveiw request"
EXACT_DELIVERED_TAG = "Delivered"
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\s-]?token|api[_\s-]?key|password|secret)"
)

ACTION_SECTIONS = [
    "manual_ali_reviews_check_required",
    "repeat_customer_trustpilot_candidates",
    "blocked_by_ticket",
    "blocked_no_email",
    "blocked_refunded_or_partially_refunded",
    "existing_review_request_tag_present",
    "needs_manual_review",
]


def run_shopify_review_request_manual_action_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_error = _load_source_report()
    package = _build_package(source_report, source_error, round(time.time() - started, 3))
    json_path = _write_json_report(package)
    html_path = _write_html_report(package)
    return _task_result(package, json_path, html_path)


def _load_source_report() -> tuple[dict, str]:
    if not SOURCE_JSON_PATH.exists():
        return {}, "source_report_missing"
    try:
        return json.loads(SOURCE_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, f"source_report_json_parse_error: {exc}"


def _build_package(source_report: dict, source_error: str, duration_seconds: float) -> dict:
    source_ok = (
        not source_error
        and source_report.get("task_name") == "shopify_review_request_candidate_scan"
        and str(source_report.get("phase")) == "1.1"
        and source_report.get("scanner_version") == "phase_1_1_ticket_filter"
        and source_report.get("success") is True
    )
    status = "manual_action_package_ready" if source_ok else "blocked_source_phase_1_1_report_not_ready"
    orders = source_report.get("orders") if isinstance(source_report.get("orders"), list) else []
    sections = {section: [] for section in ACTION_SECTIONS}
    if source_ok:
        for order in orders:
            for section in _sections_for_order(order):
                sections[section].append(_manual_action_entry(order, section))

    section_counts = {section: len(items) for section, items in sections.items()}
    safety_summary = _safety_summary()
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "1.2",
        "mode": "no-write-manual-action-package",
        "command_label": COMMAND_LABEL,
        "manual_action_package_status": status,
        "success": bool(source_ok),
        "source_report_path": str(SOURCE_JSON_PATH),
        "source_report_status": source_report.get("report_status", ""),
        "source_report_phase": source_report.get("phase", ""),
        "source_scanner_version": source_report.get("scanner_version", ""),
        "source_orders_queried": int(source_report.get("orders_queried") or 0),
        "source_success": bool(source_report.get("success")),
        "source_error_sanitized": _sanitize_text(source_error),
        "source_report_json_parse_error_sanitized": _sanitize_text(source_error) if source_error else "",
        "exact_existing_review_request_tag": EXACT_REVIEW_REQUEST_TAG,
        "exact_existing_delivered_tag": EXACT_DELIVERED_TAG,
        "manual_action_sections": sections,
        "section_counts": section_counts,
        "total_manual_action_items": sum(section_counts.values()),
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_email_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
            "private_customer_notes_output": False,
        },
        "safety_summary": safety_summary,
        **safety_summary,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, section_counts, source_error),
        "duration_seconds": duration_seconds,
        "json_manual_action_package_path": str(REPORT_JSON_PATH),
        "html_manual_action_package_path": str(REPORT_HTML_PATH),
    }


def _sections_for_order(order: dict) -> list[str]:
    buckets = set(str(bucket) for bucket in order.get("classification_buckets", []))
    sections = []
    if "ready_for_manual_ali_reviews_check" in buckets:
        sections.append("manual_ali_reviews_check_required")
    if "repeat_customer_trustpilot_candidate" in buckets:
        sections.append("repeat_customer_trustpilot_candidates")
    if order.get("ticket_blocked") or buckets.intersection(
        {
            "blocked_has_open_ticket",
            "blocked_has_refund_ticket",
            "blocked_has_shipping_issue_ticket",
            "blocked_has_complaint_ticket",
        }
    ):
        sections.append("blocked_by_ticket")
    if "blocked_no_email" in buckets:
        sections.append("blocked_no_email")
    if "blocked_refunded_or_partially_refunded" in buckets:
        sections.append("blocked_refunded_or_partially_refunded")
    if "existing_manual_review_request_tag_present" in buckets:
        sections.append("existing_review_request_tag_present")
    if "needs_manual_review" in buckets or "ticket_status_unknown_needs_manual_review" in buckets:
        sections.append("needs_manual_review")
    return _dedupe(sections) or ["needs_manual_review"]


def _manual_action_entry(order: dict, section: str) -> dict:
    return {
        "order_name": _safe_text(order.get("order_name", "")),
        "order_id": _safe_text(order.get("order_id", "")),
        "masked_email": _safe_masked_email(order.get("masked_email", "")),
        "customer_repeat_count": order.get("customer_repeat_count") if isinstance(order.get("customer_repeat_count"), int) else None,
        "repeat_customer_detected": bool(order.get("repeat_customer_detected")),
        "tags_summary": _tags_summary(order.get("tags", [])),
        "classification": _safe_text(order.get("classification", "")),
        "classification_reasons": [_safe_text(reason) for reason in order.get("classification_reasons", [])],
        "ticket_risk_summary": _ticket_risk_summary(order),
        "suggested_next_manual_action": _suggested_action(section),
        "action_planned": "manual_review_only",
        "shopify_write_planned": False,
        "email_send_planned": False,
        "ali_reviews_call_planned": False,
    }


def _tags_summary(tags: list) -> dict:
    safe_tags = [_safe_text(tag) for tag in tags if str(tag).strip()]
    return {
        "tag_count": len(safe_tags),
        "contains_exact_delivered_tag": EXACT_DELIVERED_TAG in safe_tags,
        "contains_exact_review_request_tag": EXACT_REVIEW_REQUEST_TAG in safe_tags,
        "exact_tags_of_interest": [tag for tag in safe_tags if tag in {EXACT_DELIVERED_TAG, EXACT_REVIEW_REQUEST_TAG}],
        "safe_tags": safe_tags,
    }


def _ticket_risk_summary(order: dict) -> dict:
    summaries = []
    for item in order.get("ticket_status_summary", [])[:5]:
        summaries.append(
            {
                "ticket_id": _safe_text(item.get("ticket_id", "")),
                "status": _safe_text(item.get("status", "")),
                "status_category": _safe_text(item.get("status_category", "")),
                "priority": _safe_text(item.get("priority", "")),
                "match_fields": [_safe_text(value) for value in item.get("match_fields", [])],
                "risk_categories": [_safe_text(value) for value in item.get("risk_categories", [])],
                "is_blocking": bool(item.get("is_blocking")),
            }
        )
    return {
        "ticket_match_detected": bool(order.get("ticket_match_detected")),
        "ticket_blocked": bool(order.get("ticket_blocked")),
        "ticket_blocking_reason": _safe_text(order.get("ticket_blocking_reason", "")),
        "ticket_risk_categories": [_safe_text(value) for value in order.get("ticket_risk_categories", [])],
        "ticket_status_summary": summaries,
    }


def _suggested_action(section: str) -> str:
    actions = {
        "manual_ali_reviews_check_required": (
            "Open Ali Reviews / Kudosi dashboard manually and check whether a review request has already been sent. "
            "Do not send from automation."
        ),
        "repeat_customer_trustpilot_candidates": (
            "Review customer/order manually for future Trustpilot preview eligibility. Do not send Gmail."
        ),
        "blocked_by_ticket": "Do not request a review; inspect the local ticket before any future action.",
        "blocked_no_email": "Do not request a review; no customer email is available in the scanned order data.",
        "blocked_refunded_or_partially_refunded": "Do not request a review; refund/dispute signal requires manual review.",
        "existing_review_request_tag_present": (
            "Leave the existing exact Shopify tag unchanged and check Ali Reviews / Kudosi manually if needed."
        ),
        "needs_manual_review": "Review manually before any future Ali Reviews, Trustpilot, or Shopify tag action.",
    }
    return actions.get(section, "Review manually; no automated action is approved.")


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


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_manual_action_package_path": str(json_path),
        "html_manual_action_package_path": str(html_path),
        "manual_action_package_status": payload["manual_action_package_status"],
        "source_report_status": payload["source_report_status"],
        "source_scanner_version": payload["source_scanner_version"],
        "section_counts": payload["section_counts"],
        "total_manual_action_items": payload["total_manual_action_items"],
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
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    section_rows = "\n".join(
        f"<tr><td><code>{escape(section)}</code></td><td>{count}</td></tr>"
        for section, count in payload["section_counts"].items()
    )
    sections = "\n".join(
        _render_section(section, payload["manual_action_sections"].get(section, []))
        for section in ACTION_SECTIONS
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Manual Action Package</title>
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
  <h1>Review Request Manual Action Package</h1>
  <p class="warning">Phase 1.2 is local report-only. No review request was sent and no Shopify tag was changed.</p>
  <p>Status: <strong>{escape(str(payload["manual_action_package_status"]))}</strong></p>
  <p>Source report: <code>{escape(str(payload["source_report_path"]))}</code></p>
  <p>Source status: <code>{escape(str(payload["source_report_status"]))}</code> | scanner: <code>{escape(str(payload["source_scanner_version"]))}</code></p>
  <h2>Section Counts</h2>
  <table><thead><tr><th>Section</th><th>Count</th></tr></thead><tbody>{section_rows}</tbody></table>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
  {sections}
</body>
</html>"""


def _render_section(section: str, entries: list[dict]) -> str:
    rows = "\n".join(_render_entry(entry) for entry in entries)
    if not rows:
        rows = '<tr><td colspan="7">No orders in this section.</td></tr>'
    return f"""<h2><code>{escape(section)}</code></h2>
<table>
  <thead><tr><th>Order</th><th>Masked email</th><th>Tags</th><th>Reasons</th><th>Ticket risk</th><th>Repeat</th><th>Suggested manual action</th></tr></thead>
  <tbody>{rows}</tbody>
</table>"""


def _render_entry(entry: dict) -> str:
    tags = ", ".join(f"<code>{escape(str(tag))}</code>" for tag in entry["tags_summary"].get("safe_tags", []))
    reasons = "<br>".join(escape(str(reason)) for reason in entry.get("classification_reasons", []))
    ticket = entry.get("ticket_risk_summary", {})
    ticket_bits = [
        f"match={escape(str(ticket.get('ticket_match_detected')))}",
        f"blocked={escape(str(ticket.get('ticket_blocked')))}",
    ]
    if ticket.get("ticket_blocking_reason"):
        ticket_bits.append(escape(str(ticket["ticket_blocking_reason"])))
    return f"""<tr>
  <td>{escape(str(entry.get("order_name", "")))}<br><code>{escape(str(entry.get("order_id", "")))}</code></td>
  <td>{escape(str(entry.get("masked_email", "")))}</td>
  <td>{tags}</td>
  <td>{reasons}</td>
  <td>{"<br>".join(ticket_bits)}</td>
  <td>{escape(str(entry.get("customer_repeat_count") or ""))}<br>detected={escape(str(entry.get("repeat_customer_detected")))}</td>
  <td>{escape(str(entry.get("suggested_next_manual_action", "")))}</td>
</tr>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 1.2 manual action package finished.\n"
        f"Status: {payload.get('manual_action_package_status')}\n"
        f"Source report status: {payload.get('source_report_status')}\n"
        f"Total manual action items: {payload.get('total_manual_action_items')}\n"
        f"Section counts: {json.dumps(payload.get('section_counts', {}), ensure_ascii=False)}\n"
        "Safety: local report only; no Shopify API call, no Shopify writes, no tagsAdd/tagsRemove, no Ali Reviews API, no Gmail API, and no email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, section_counts: dict, source_error: str) -> str:
    if status == "manual_action_package_ready":
        return f"Manual action package created with {sum(section_counts.values())} report-only action items."
    return f"Manual action package blocked because the Phase 1.1 source report is not ready: {_sanitize_text(source_error)}"


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


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
