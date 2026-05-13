import json
import re
import time
from collections import Counter
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_unified_decision_engine_dry_run"
COMMAND_LABEL = "shopify_review_request_unified_decision_engine_dry_run"

CANDIDATE_SCAN_PATH = LOG_DIR / "shopify_review_request_candidate_scan.json"
MANUAL_ACTION_PACKAGE_PATH = LOG_DIR / "shopify_review_request_manual_action_package.json"
MANUAL_ACTION_CSV_EXPORT_PATH = LOG_DIR / "shopify_review_request_manual_action_csv_export.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_unified_decision_engine_dry_run.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_unified_decision_engine_dry_run.html"

HISTORICAL_ALI_MANUAL_TAG = "1: reveiw request"
ALI_REVIEW_PENDING_TAG = "1: Review request"
ALI_REVIEW_SENT_TAG = "Review sent"
TRUSTPILOT_TAG_ALIASES = ["1: trustpilot", "1: trustpoilt"]
GMAIL_SENDER_PLANNED = "info@kidstoylover.com"
TRUSTPILOT_LINK = "https://www.trustpilot.com/evaluate/www.kidstoylover.com"

DECISION_BUCKETS = [
    "blocked_returned_package",
    "blocked_no_email",
    "blocked_refund_or_cancelled",
    "blocked_ticket_risk",
    "trustpilot_gmail_candidate_dry_run",
    "trustpilot_already_requested_route_to_ali_if_eligible",
    "ali_reviews_candidate_waiting_for_send_api",
    "already_review_sent_skip",
    "existing_manual_review_request_tag_present",
    "needs_manual_review",
]

TRUSTPILOT_EMAIL_SUBJECT = "Thank You for Your Support - We'd Love Your Feedback!"
TRUSTPILOT_EMAIL_BODY = """Dear {first_name},

Thank you so much for your continued support and for choosing us again - it truly means a lot to our team.

If you have a moment, we would greatly appreciate it if you could leave a quick review of your experience with us. Your feedback not only helps us improve, but also helps other customers feel confident in choosing us too.

You can share your thoughts here:
https://www.trustpilot.com/evaluate/www.kidstoylover.com

Thanks again for being a valued customer. If there's anything else we can assist you with, please don't hesitate to let us know.

Kind Regards,
Xiang"""

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|x-shopify-access-token|access[_\s-]?token|api[_\s-]?key|password|secret)"
)


def run_shopify_review_request_unified_decision_engine_dry_run_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    sources, source_errors = _load_sources()
    payload = _build_payload(sources, source_errors, round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_sources() -> tuple[dict, dict]:
    source_paths = {
        "candidate_scan": CANDIDATE_SCAN_PATH,
        "manual_action_package": MANUAL_ACTION_PACKAGE_PATH,
        "manual_action_csv_export": MANUAL_ACTION_CSV_EXPORT_PATH,
    }
    sources = {}
    errors = {}
    for name, path in source_paths.items():
        if not path.exists():
            errors[name] = "missing_source_report"
            continue
        try:
            sources[name] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors[name] = _sanitize_text(f"source_report_json_parse_error: {exc}")
    return sources, errors


def _build_payload(sources: dict, source_errors: dict, duration_seconds: float) -> dict:
    source_status = _source_report_status(sources, source_errors)
    source_ready = not source_errors and all(item["ready"] for item in source_status.values())
    decisions = []
    if source_ready:
        orders = sources["candidate_scan"].get("orders") or []
        decisions = [_decision_row(order) for order in orders if isinstance(order, dict)]
    counts = Counter(row["decision"] for row in decisions)
    counts = {bucket: int(counts.get(bucket, 0)) for bucket in DECISION_BUCKETS}
    safety = _safety_summary()
    status = "decision_engine_dry_run_ready" if source_ready else "blocked_missing_source_report"
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.0",
        "mode": "unified-review-request-decision-engine-dry-run",
        "command_label": COMMAND_LABEL,
        "decision_engine_status": status,
        "success": source_ready,
        "source_reports_used": source_status,
        "source_errors_sanitized": source_errors,
        "total_orders_evaluated": len(decisions),
        "counts": counts,
        "trustpilot_tag_aliases": TRUSTPILOT_TAG_ALIASES,
        "ali_review_pending_tag": ALI_REVIEW_PENDING_TAG,
        "ali_review_sent_tag": ALI_REVIEW_SENT_TAG,
        "historical_ali_manual_tag": HISTORICAL_ALI_MANUAL_TAG,
        "gmail_sender_planned": GMAIL_SENDER_PLANNED,
        "trustpilot_link": TRUSTPILOT_LINK,
        "decisions": decisions,
        "trustpilot_template_preview": {
            "subject": TRUSTPILOT_EMAIL_SUBJECT,
            "body_template": TRUSTPILOT_EMAIL_BODY,
            "preview_for_masked_email": _first_trustpilot_preview_email(decisions),
            "gmail_draft_created": False,
            "email_sent": False,
        },
        "decision_notes": [
            "Ali Reviews / Kudosi send remains blocked pending confirmed send/status API support.",
            "Trustpilot Gmail flow is dry-run only; no Gmail API call or draft creation was performed.",
            "Planned tag transitions are report-only and were not performed.",
        ],
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
        "detected_issue_summary": _issue_summary(status, counts, source_errors),
        "duration_seconds": duration_seconds,
        "json_unified_decision_engine_dry_run_path": str(REPORT_JSON_PATH),
        "html_unified_decision_engine_dry_run_path": str(REPORT_HTML_PATH),
    }


def _source_report_status(sources: dict, source_errors: dict) -> dict:
    expected = {
        "candidate_scan": {
            "path": str(CANDIDATE_SCAN_PATH),
            "task_name": "shopify_review_request_candidate_scan",
            "ready": lambda data: data.get("success") is True and str(data.get("phase")) == "1.1",
            "status": lambda data: data.get("report_status", ""),
        },
        "manual_action_package": {
            "path": str(MANUAL_ACTION_PACKAGE_PATH),
            "task_name": "shopify_review_request_manual_action_package",
            "ready": lambda data: data.get("manual_action_package_status") == "manual_action_package_ready",
            "status": lambda data: data.get("manual_action_package_status", ""),
        },
        "manual_action_csv_export": {
            "path": str(MANUAL_ACTION_CSV_EXPORT_PATH),
            "task_name": "shopify_review_request_manual_action_csv_export",
            "ready": lambda data: data.get("csv_export_status") == "csv_export_ready",
            "status": lambda data: data.get("csv_export_status", ""),
        },
    }
    result = {}
    for name, meta in expected.items():
        data = sources.get(name) or {}
        missing = name in source_errors
        task_matches = data.get("task_name") == meta["task_name"]
        ready = (not missing) and task_matches and bool(meta["ready"](data))
        result[name] = {
            "path": meta["path"],
            "present": not missing,
            "task_name": data.get("task_name", ""),
            "task_name_matches": task_matches,
            "status": meta["status"](data) if data else "",
            "ready": ready,
            "error_sanitized": source_errors.get(name, ""),
        }
    return result


def _decision_row(order: dict) -> dict:
    tags = [_safe_text(tag) for tag in order.get("tags", []) if str(tag).strip()]
    tag_set = set(tags)
    normalized_tags = {_normalize_tag(tag) for tag in tags}
    masked_email = _safe_masked_email(order.get("masked_email", ""))
    repeat_detected = bool(order.get("repeat_customer_detected"))
    has_no_email = not bool(order.get("email_present")) or not masked_email
    has_refund_or_cancelled = _has_bucket(order, {"blocked_cancelled", "blocked_refunded_or_partially_refunded"})
    has_ticket_risk = _has_ticket_risk(order)
    has_trustpilot_tag = any(_normalize_tag(alias) in normalized_tags for alias in TRUSTPILOT_TAG_ALIASES)
    has_returned_package_tag = _has_returned_package_tag(tags)
    has_review_sent = ALI_REVIEW_SENT_TAG in tag_set
    has_historical_manual = HISTORICAL_ALI_MANUAL_TAG in tag_set
    has_ali_pending = ALI_REVIEW_PENDING_TAG in tag_set
    has_delivered = "Delivered" in tag_set

    if has_returned_package_tag:
        decision = "blocked_returned_package"
    elif has_no_email:
        decision = "blocked_no_email"
    elif has_refund_or_cancelled:
        decision = "blocked_refund_or_cancelled"
    elif has_ticket_risk:
        decision = "blocked_ticket_risk"
    elif has_review_sent:
        decision = "already_review_sent_skip"
    elif repeat_detected and has_trustpilot_tag:
        decision = "trustpilot_already_requested_route_to_ali_if_eligible"
    elif repeat_detected and not has_trustpilot_tag:
        decision = "trustpilot_gmail_candidate_dry_run"
    elif has_delivered and has_ali_pending:
        decision = "ali_reviews_candidate_waiting_for_send_api"
    elif has_historical_manual:
        decision = "existing_manual_review_request_tag_present"
    else:
        decision = "needs_manual_review"

    return {
        "order_name": _safe_text(order.get("order_name", "")),
        "order_id_or_gid": _safe_text(order.get("order_id", "")),
        "masked_email": masked_email,
        "repeat_customer_count": order.get("customer_repeat_count") if isinstance(order.get("customer_repeat_count"), int) else None,
        "repeat_customer_detected": repeat_detected,
        "safe_tags_summary": _tags_summary(tags),
        "risk_summary": _risk_summary(order),
        "decision": decision,
        "planned_next_action": _planned_next_action(decision),
        "tag_changes_planned_but_not_performed": _tag_plan(decision),
        "email_planned_but_not_sent": decision == "trustpilot_gmail_candidate_dry_run",
    }


def _has_bucket(order: dict, buckets: set[str]) -> bool:
    return bool(buckets.intersection(set(str(bucket) for bucket in order.get("classification_buckets", []))))


def _has_ticket_risk(order: dict) -> bool:
    if order.get("ticket_blocked"):
        return True
    buckets = {
        "blocked_has_open_ticket",
        "blocked_has_refund_ticket",
        "blocked_has_shipping_issue_ticket",
        "blocked_has_complaint_ticket",
    }
    if _has_bucket(order, buckets):
        return True
    risk_categories = {str(item) for item in order.get("ticket_risk_categories", [])}
    return bool(risk_categories.intersection({"refund", "shipping_issue", "complaint", "dispute", "chargeback"}))


def _tags_summary(tags: list[str]) -> dict:
    return {
        "tag_count": len(tags),
        "contains_historical_ali_manual_tag": HISTORICAL_ALI_MANUAL_TAG in tags,
        "contains_ali_review_pending_tag": ALI_REVIEW_PENDING_TAG in tags,
        "contains_ali_review_sent_tag": ALI_REVIEW_SENT_TAG in tags,
        "contains_trustpilot_alias": any(_normalize_tag(alias) in {_normalize_tag(tag) for tag in tags} for alias in TRUSTPILOT_TAG_ALIASES),
        "tags_of_interest": [
            tag
            for tag in tags
            if tag in {HISTORICAL_ALI_MANUAL_TAG, ALI_REVIEW_PENDING_TAG, ALI_REVIEW_SENT_TAG}
            or _normalize_tag(tag) in {_normalize_tag(alias) for alias in TRUSTPILOT_TAG_ALIASES}
            or _has_returned_package_tag([tag])
        ],
    }


def _risk_summary(order: dict) -> dict:
    ticket_summaries = []
    for item in order.get("ticket_status_summary", [])[:5]:
        ticket_summaries.append(
            {
                "ticket_id": _safe_text(item.get("ticket_id", "")),
                "status": _safe_text(item.get("status", "")),
                "status_category": _safe_text(item.get("status_category", "")),
                "priority": _safe_text(item.get("priority", "")),
                "risk_categories": [_safe_text(value) for value in item.get("risk_categories", [])],
                "is_blocking": bool(item.get("is_blocking")),
            }
        )
    return {
        "classification_reasons": [_safe_text(reason) for reason in order.get("classification_reasons", [])],
        "ticket_match_detected": bool(order.get("ticket_match_detected")),
        "ticket_blocked": bool(order.get("ticket_blocked")),
        "ticket_blocking_reason": _safe_text(order.get("ticket_blocking_reason", "")),
        "ticket_risk_categories": [_safe_text(value) for value in order.get("ticket_risk_categories", [])],
        "ticket_status_summary": ticket_summaries,
    }


def _planned_next_action(decision: str) -> str:
    actions = {
        "blocked_no_email": "Do not send; no usable email.",
        "blocked_returned_package": "Do not send any review request; return/returned package tag indicates return-to-warehouse risk.",
        "blocked_refund_or_cancelled": "Do not send; refund, partial refund, dispute, or cancellation risk.",
        "blocked_ticket_risk": "Do not send; ticket/risk case requires resolution first.",
        "trustpilot_gmail_candidate_dry_run": "Dry-run only: future Gmail Trustpilot invitation preview; no email sent.",
        "trustpilot_already_requested_route_to_ali_if_eligible": "Do not send another Trustpilot request; route to Ali Reviews path if otherwise eligible.",
        "ali_reviews_candidate_waiting_for_send_api": "Wait for confirmed Ali Reviews/Kudosi send API before any product review request.",
        "already_review_sent_skip": "Skip; Review sent tag already present.",
        "existing_manual_review_request_tag_present": "Keep historical manual tag unchanged; manual Ali Reviews status check may be needed.",
        "needs_manual_review": "Manual review required before any review request.",
    }
    return actions.get(decision, "Manual review required.")


def _tag_plan(decision: str) -> dict:
    if decision == "ali_reviews_candidate_waiting_for_send_api":
        return {
            "future_after_success_only": True,
            "remove": [ALI_REVIEW_PENDING_TAG],
            "add": [ALI_REVIEW_SENT_TAG],
            "performed": False,
        }
    if decision == "trustpilot_gmail_candidate_dry_run":
        return {
            "future_after_success_only": True,
            "remove": [],
            "add": [TRUSTPILOT_TAG_ALIASES[0]],
            "performed": False,
        }
    return {"future_after_success_only": False, "remove": [], "add": [], "performed": False}


def _first_trustpilot_preview_email(decisions: list[dict]) -> dict:
    for row in decisions:
        if row["decision"] == "trustpilot_gmail_candidate_dry_run":
            return {
                "masked_email": row["masked_email"],
                "first_name_used": "there",
                "subject": TRUSTPILOT_EMAIL_SUBJECT,
                "body": TRUSTPILOT_EMAIL_BODY.format(first_name="there"),
            }
    return {
        "masked_email": "",
        "first_name_used": "there",
        "subject": TRUSTPILOT_EMAIL_SUBJECT,
        "body": TRUSTPILOT_EMAIL_BODY.format(first_name="there"),
    }


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
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_created": False,
        "email_sent": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_unified_decision_engine_dry_run_path": str(json_path),
        "html_unified_decision_engine_dry_run_path": str(html_path),
        "decision_engine_status": payload["decision_engine_status"],
        "total_orders_evaluated": payload["total_orders_evaluated"],
        "counts": payload["counts"],
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "ali_reviews_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_created": False,
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
    count_rows = "\n".join(
        f"<tr><td><code>{escape(bucket)}</code></td><td>{count}</td></tr>"
        for bucket, count in payload["counts"].items()
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    decision_rows = "\n".join(_render_decision_row(row) for row in payload["decisions"][:150])
    if not decision_rows:
        decision_rows = '<tr><td colspan="7">No decision rows available.</td></tr>'
    preview = payload["trustpilot_template_preview"]["preview_for_masked_email"]
    template = escape(preview["body"]).replace("\n", "<br>")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Unified Review Request Decision Engine Dry Run</title>
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
  <h1>Unified Review Request Decision Engine Dry Run</h1>
  <p class="warning">Phase 3.0 is dry-run only. No review request was sent and no Shopify tag was changed.</p>
  <p>Status: <strong>{escape(str(payload["decision_engine_status"]))}</strong></p>
  <p>Ali Reviews / Kudosi sending is blocked pending confirmed send/status API support.</p>
  <p>Trustpilot Gmail flow is dry-run only; no Gmail draft or email was created.</p>
  <h2>Summary Counts</h2>
  <table><thead><tr><th>Decision</th><th>Count</th></tr></thead><tbody>{count_rows}</tbody></table>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <h2>Decision Rows</h2>
  <table>
    <thead><tr><th>Order</th><th>Masked email</th><th>Decision</th><th>Planned next action</th><th>Tags of interest</th><th>Risk</th><th>Planned tag changes</th></tr></thead>
    <tbody>{decision_rows}</tbody>
  </table>
  <h2>Trustpilot Email Template Preview</h2>
  <p>Preview masked email: <code>{escape(str(preview["masked_email"]))}</code></p>
  <p>Subject: <strong>{escape(TRUSTPILOT_EMAIL_SUBJECT)}</strong></p>
  <p>{template}</p>
  <p><strong>NOT PERFORMED:</strong> no Gmail draft was created and no email was sent.</p>
</body>
</html>"""


def _render_decision_row(row: dict) -> str:
    tags = ", ".join(f"<code>{escape(str(tag))}</code>" for tag in row["safe_tags_summary"].get("tags_of_interest", []))
    risk = row["risk_summary"]
    risk_bits = [
        f"ticket_match={risk.get('ticket_match_detected')}",
        f"ticket_blocked={risk.get('ticket_blocked')}",
    ]
    if risk.get("ticket_blocking_reason"):
        risk_bits.append(str(risk.get("ticket_blocking_reason")))
    tag_plan = row["tag_changes_planned_but_not_performed"]
    tag_plan_text = f"add={tag_plan.get('add', [])}; remove={tag_plan.get('remove', [])}; NOT PERFORMED"
    return f"""<tr>
  <td>{escape(str(row.get("order_name", "")))}<br><code>{escape(str(row.get("order_id_or_gid", "")))}</code></td>
  <td>{escape(str(row.get("masked_email", "")))}</td>
  <td><code>{escape(str(row.get("decision", "")))}</code></td>
  <td>{escape(str(row.get("planned_next_action", "")))}</td>
  <td>{tags}</td>
  <td>{escape("; ".join(risk_bits))}</td>
  <td>{escape(tag_plan_text)}</td>
</tr>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.0 unified decision engine dry-run finished.\n"
        f"Status: {payload.get('decision_engine_status')}\n"
        f"Orders evaluated: {payload.get('total_orders_evaluated')}\n"
        f"Counts: {json.dumps(payload.get('counts', {}), ensure_ascii=False)}\n"
        "Safety: no Shopify API call, no Shopify writes, no tagsAdd/tagsRemove, no Kudosi API call, no Gmail API, no draft, and no email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, counts: dict, source_errors: dict) -> str:
    if status != "decision_engine_dry_run_ready":
        return "Unified decision engine blocked because one or more source reports are missing or not ready: " + _sanitize_text(json.dumps(source_errors, ensure_ascii=False))
    return f"Unified decision engine classified {sum(counts.values())} orders without writes or sends."


def _normalize_tag(tag: str) -> str:
    return str(tag or "").strip().lower()


def _has_returned_package_tag(tags: list[str]) -> bool:
    for tag in tags:
        normalized = re.sub(r"[\s_-]+", " ", str(tag or "").strip().lower())
        compact = normalized.replace(" ", "")
        if "return" in compact or "returned" in compact:
            return True
    return False


def _safe_masked_email(value: str) -> str:
    text = _safe_text(value)
    if not text or "@" not in text:
        return ""
    if "***" in text:
        return text
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)


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
