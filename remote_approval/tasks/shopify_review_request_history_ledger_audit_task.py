import json
import sys
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from shopify_sync.review_request_history_ledger import (  # noqa: E402
    FALSE_REQUIRED_SAFETY_FLAGS,
    build_review_request_history_ledger,
    privacy_scan_text,
)


TASK_NAME = "shopify_review_request_history_ledger_audit"
COMMAND_LABEL = "shopify_review_request_history_ledger_audit_read_only_local_reports"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_history_ledger_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_history_ledger_audit.html"
SUCCESS_STATUS = "completed_read_only_history_ledger_audit"


def run_shopify_review_request_history_ledger_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    ledger = build_review_request_history_ledger(LOG_DIR, {"ledger_limit": "100"})
    payload = _build_payload(ledger, round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _build_payload(ledger: dict, duration_seconds: float) -> dict:
    focus = ledger["focus"]
    source_reports = ledger["source_reports"]
    safety = _safety_summary()
    event_rows = [_audit_event_row(event) for event in ledger["all_events"][:200]]
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.1",
        "mode": "read-only-history-ledger-audit",
        "command_label": COMMAND_LABEL,
        "history_ledger_audit_status": SUCCESS_STATUS,
        "success": True,
        "source_report_summary": {
            "source_report_count": ledger["summary"]["source_report_count"],
            "loaded_source_report_count": ledger["summary"]["loaded_source_report_count"],
            "missing_source_report_count": ledger["summary"]["missing_source_report_count"],
            "unavailable_source_report_count": ledger["summary"]["unavailable_source_report_count"],
            "reports": [_source_report_row(report) for report in source_reports],
        },
        "ledger_summary": {
            "total_event_count": ledger["summary"]["total_event_count"],
            "filtered_event_count": ledger["summary"]["filtered_event_count"],
            "counts_by_event_type": ledger["summary"]["by_event_type"],
            "counts_by_status": ledger["summary"]["by_status"],
            "counts_by_channel": ledger["summary"]["by_channel"],
        },
        "order_22620_audit": {
            "order_name": "#22620",
            "blocked_confirmed": focus["order_22620"]["blocked_confirmed"],
            "blocked_classification": focus["order_22620"]["blocked_classification"],
            "email_sent_confirmed_false": focus["order_22620"]["email_sent_confirmed_false"],
            "email_sent_source_value": "false"
            if focus["order_22620"]["email_sent_confirmed_false"]
            else "unavailable_or_true",
            "existing_unsent_gmail_draft_should_not_be_sent": focus["order_22620"][
                "existing_unsent_gmail_draft_should_not_be_sent"
            ],
            "source_reports_indicate_existing_gmail_draft": focus["order_22620"][
                "source_gmail_draft_created_detected"
            ],
            "prior_trustpilot_order_name": focus["order_22620"]["prior_trustpilot_order_name"],
            "evidence_report_paths": focus["order_22620"]["evidence_report_paths"],
        },
        "next_candidate_audit": {
            "next_candidate_order_name": focus["next_candidate"]["order_name"],
            "next_candidate_status": focus["next_candidate"]["status"],
            "evidence_report_path": focus["next_candidate"]["evidence_report_path"],
            "candidate_22582_confirmed": focus["next_candidate"]["order_name"] == "#22582",
        },
        "order_22582_audit": {
            "audit_order_name": "#22582",
            "evidence_available": focus["order_22582"]["evidence_available"],
            "delivered_tag_present": focus["order_22582"]["delivered_tag_present"],
            "canonical_review_request_tag_present": focus["order_22582"][
                "canonical_review_request_tag_present"
            ],
            "merged_or_related_order_guard_status": focus["order_22582"][
                "merged_or_related_order_guard_status"
            ],
            "eligible_for_trustpilot": focus["order_22582"]["eligible_for_trustpilot"],
            "classification": focus["order_22582"]["blocked_classification"],
            "evidence_report_paths": focus["order_22582"]["evidence_report_paths"],
        },
        "ali_reviews_api_audit": {
            "status": focus["ali_reviews_api"]["status"],
            "vendor_api_documentation_missing": focus["ali_reviews_api"]["vendor_docs_missing"],
            "evidence_report_path": focus["ali_reviews_api"]["evidence_report_path"],
            "report_present": focus["ali_reviews_api"]["present"],
            "report_loaded": focus["ali_reviews_api"]["loaded"],
        },
        "event_rows": event_rows,
        "event_rows_limited_to": 200,
        "recommendations": ledger["recommendations"],
        "privacy_and_output_policy": {
            "raw_customer_email_output": False,
            "masked_email_only": True,
            "gmail_draft_id_full_output": False,
            "gmail_message_id_full_output": False,
            "partial_gmail_ids_only": True,
            "token_or_secret_output": False,
        },
        "safety_summary": safety,
        **safety,
        "json_history_ledger_audit_path": str(REPORT_JSON_PATH),
        "html_history_ledger_audit_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(focus),
    }
    return _apply_self_privacy_assertion(payload)


def _audit_event_row(event: dict) -> dict:
    return {
        "event_time": event.get("event_time", ""),
        "source_report_path": event.get("source_report_path", ""),
        "task_name": event.get("task_name", ""),
        "phase": event.get("phase", ""),
        "channel": event.get("channel", ""),
        "event_type": event.get("event_type", ""),
        "order_name": event.get("order_name", ""),
        "masked_email": event.get("masked_email", ""),
        "status": event.get("status", ""),
        "classification": event.get("classification", ""),
        "blocker_reason": event.get("blocker_reason", ""),
        "success": event.get("success"),
        "source_email_sent_evidence": _bool_text(event.get("email_sent")),
        "source_draft_created_evidence": _bool_text(event.get("gmail_draft_created")),
        "source_shopify_tag_written_evidence": _bool_text(event.get("shopify_tag_written")),
        "partial_draft_id": event.get("partial_draft_id", ""),
        "partial_message_id": event.get("partial_message_id", ""),
        "next_candidate_order_name": event.get("next_candidate_order_name", ""),
        "prior_trustpilot_order_name": event.get("prior_trustpilot_order_name", ""),
        "draft_should_not_be_sent": event.get("draft_should_not_be_sent") is True,
        "delivered_tag_present": event.get("delivered_tag_present"),
        "canonical_review_request_tag_present": event.get("canonical_review_request_tag_present"),
        "merged_or_related_order_guard_status": event.get("merged_or_related_order_guard_status", ""),
        "eligible_for_trustpilot": event.get("eligible_for_trustpilot"),
    }


def _source_report_row(report: dict) -> dict:
    return {
        "label": report.get("label", ""),
        "relative_path": report.get("relative_path", ""),
        "present": report.get("present") is True,
        "loaded": report.get("loaded") is True,
        "status": report.get("status", ""),
        "timestamp": report.get("timestamp", ""),
        "modified_at": report.get("modified_at", ""),
        "error": report.get("error", ""),
    }


def _safety_summary() -> dict:
    safety = {flag: False for flag in FALSE_REQUIRED_SAFETY_FLAGS}
    safety.update(
        {
            "gmail_api_call_performed": False,
            "gmail_draft_deleted": False,
            "gmail_drafts_delete_called": False,
            "shopify_api_call_performed": False,
            "kudosi_write_api_call_performed": False,
            "ali_reviews_review_request_send_performed": False,
            "trustpilot_review_request_send_performed": False,
            "external_post_put_patch_delete_performed": False,
            "no_gmail_draft_created": True,
            "no_gmail_send_performed": True,
            "no_gmail_draft_deleted": True,
            "no_shopify_writes_performed": True,
            "no_shopify_tag_add_remove_performed": True,
            "no_external_review_api_calls_performed": True,
            "no_tracking_action_performed": True,
            "all_new_actions_no_write_confirmed": True,
        }
    )
    return safety


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=True, sort_keys=True)
    self_scan = privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if any(
        (
            self_scan["raw_customer_email_count"],
            self_scan["token_secret_bearer_pattern_count"],
            self_scan["full_gmail_draft_or_message_id_field_count"],
        )
    ):
        payload["history_ledger_audit_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["detected_issue_summary"] = "History ledger audit report privacy scan failed."
    return payload


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=True, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    order_audit = payload["order_22620_audit"]
    order_22582 = payload["order_22582_audit"]
    next_candidate = payload["next_candidate_audit"]
    ali = payload["ali_reviews_api_audit"]
    source_rows = "\n".join(
        "<tr>"
        f"<td>{escape(row['label'])}</td>"
        f"<td>{escape(str(row['loaded']))}</td>"
        f"<td>{escape(row['status'])}</td>"
        f"<td><code>{escape(row['relative_path'])}</code></td>"
        "</tr>"
        for row in payload["source_report_summary"]["reports"]
    )
    event_rows = "\n".join(
        "<tr>"
        f"<td>{escape(row['event_time'] or '-')}</td>"
        f"<td>{escape(row['channel'])}<br><code>{escape(row['event_type'])}</code></td>"
        f"<td>{escape(row['order_name'] or '-')}<br>{escape(row['masked_email'] or '')}</td>"
        f"<td><code>{escape(row['status'] or '-')}</code><br>{escape(row['classification'] or '')}</td>"
        f"<td>{escape(row['source_email_sent_evidence'])}</td>"
        f"<td>{escape(row['source_draft_created_evidence'])}</td>"
        f"<td>{escape(row['source_shopify_tag_written_evidence'])}</td>"
        f"<td><code>{escape(row['source_report_path'])}</code></td>"
        "</tr>"
        for row in payload["event_rows"]
    ) or '<tr><td colspan="8">No events loaded.</td></tr>'
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request History Ledger Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .safe {{ border-left: 4px solid #15803d; background: #f0fdf4; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Review Request History Ledger Audit</h1>
  <p class="safe">Phase 5.1 is read-only local report history only. It did not create, send, delete, write, call external review APIs, or enable tracking.</p>
  <p>Status: <strong>{escape(payload["history_ledger_audit_status"])}</strong></p>
  <h2>Key Facts</h2>
  <table><tbody>
    <tr><th>#22620 blocked classification</th><td><code>{escape(order_audit["blocked_classification"])}</code></td></tr>
    <tr><th>#22620 email sent confirmed false</th><td>{escape(str(order_audit["email_sent_confirmed_false"]))}</td></tr>
    <tr><th>#22620 draft should not be sent</th><td>{escape(str(order_audit["existing_unsent_gmail_draft_should_not_be_sent"]))}</td></tr>
    <tr><th>Prior Trustpilot order</th><td><code>{escape(order_audit["prior_trustpilot_order_name"])}</code></td></tr>
    <tr><th>#22582 delivered tag present</th><td>{escape(str(order_22582["delivered_tag_present"]))}</td></tr>
    <tr><th>#22582 canonical review tag present</th><td>{escape(str(order_22582["canonical_review_request_tag_present"]))}</td></tr>
    <tr><th>#22582 merged/related guard</th><td><code>{escape(order_22582["merged_or_related_order_guard_status"])}</code></td></tr>
    <tr><th>#22582 eligible for Trustpilot</th><td>{escape(str(order_22582["eligible_for_trustpilot"]))}</td></tr>
    <tr><th>#22582 classification</th><td><code>{escape(order_22582["classification"])}</code></td></tr>
    <tr><th>Next candidate</th><td><code>{escape(next_candidate["next_candidate_order_name"])}</code></td></tr>
    <tr><th>Ali Reviews API status</th><td><code>{escape(ali["status"])}</code></td></tr>
  </tbody></table>
  <h2>Source Reports</h2>
  <table><thead><tr><th>Report</th><th>Loaded</th><th>Status</th><th>Path</th></tr></thead><tbody>{source_rows}</tbody></table>
  <h2>Ledger Events</h2>
  <table>
    <thead><tr><th>Time</th><th>Event</th><th>Order</th><th>Status</th><th>Email sent evidence</th><th>Draft evidence</th><th>Tag evidence</th><th>Source</th></tr></thead>
    <tbody>{event_rows}</tbody>
  </table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    order_audit = payload["order_22620_audit"]
    order_22582 = payload["order_22582_audit"]
    next_candidate = payload["next_candidate_audit"]
    ali = payload["ali_reviews_api_audit"]
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_history_ledger_audit_path": str(json_path),
        "html_history_ledger_audit_path": str(html_path),
        "history_ledger_audit_status": payload["history_ledger_audit_status"],
        "ledger_event_count": payload["ledger_summary"]["total_event_count"],
        "loaded_source_report_count": payload["source_report_summary"]["loaded_source_report_count"],
        "missing_source_report_count": payload["source_report_summary"]["missing_source_report_count"],
        "unavailable_source_report_count": payload["source_report_summary"]["unavailable_source_report_count"],
        "order_22620_blocked_classification": order_audit["blocked_classification"],
        "order_22620_email_sent_confirmed_false": order_audit["email_sent_confirmed_false"],
        "order_22620_existing_unsent_draft_should_not_be_sent": order_audit[
            "existing_unsent_gmail_draft_should_not_be_sent"
        ],
        "order_22620_prior_trustpilot_order_name": order_audit["prior_trustpilot_order_name"],
        "order_22582_delivered_tag_present": order_22582["delivered_tag_present"],
        "order_22582_canonical_review_request_tag_present": order_22582[
            "canonical_review_request_tag_present"
        ],
        "order_22582_merged_or_related_order_guard_status": order_22582[
            "merged_or_related_order_guard_status"
        ],
        "order_22582_eligible_for_trustpilot": order_22582["eligible_for_trustpilot"],
        "order_22582_classification": order_22582["classification"],
        "next_candidate_order_name": next_candidate["next_candidate_order_name"],
        "candidate_22582_confirmed": next_candidate["candidate_22582_confirmed"],
        "ali_reviews_api_capability_discovery_status": ali["status"],
        "ali_reviews_vendor_api_documentation_missing": ali["vendor_api_documentation_missing"],
        **payload["safety_summary"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    order_audit = payload["order_22620_audit"]
    order_22582 = payload["order_22582_audit"]
    next_candidate = payload["next_candidate_audit"]
    ali = payload["ali_reviews_api_audit"]
    return (
        "Shopify review request Phase 5.1 history ledger audit finished.\n"
        f"Status: {payload['history_ledger_audit_status']}\n"
        f"#22620 classification: {order_audit['blocked_classification']}\n"
        f"#22620 email sent confirmed false: {order_audit['email_sent_confirmed_false']}\n"
        f"#22620 existing draft should not be sent: {order_audit['existing_unsent_gmail_draft_should_not_be_sent']}\n"
        f"Prior Trustpilot order: {order_audit['prior_trustpilot_order_name']}\n"
        f"#22582 eligibility: delivered={order_22582['delivered_tag_present']}, "
        f"canonical_review={order_22582['canonical_review_request_tag_present']}, "
        f"merged_guard={order_22582['merged_or_related_order_guard_status']}, "
        f"eligible={order_22582['eligible_for_trustpilot']}, "
        f"classification={order_22582['classification']}\n"
        f"Next candidate: {next_candidate['next_candidate_order_name']}\n"
        f"Ali Reviews API status: {ali['status']}\n"
        "Safety: no Gmail draft create/send/delete, no Shopify write/tag change, no Trustpilot/Kudosi/Ali Reviews API call, and no tracking action.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(focus: dict) -> str:
    order_audit = focus["order_22620"]
    order_22582 = focus["order_22582"]
    next_candidate = focus["next_candidate"]
    ali = focus["ali_reviews_api"]
    return (
        f"#22620 ledger status: {order_audit['blocked_classification']}; "
        f"email_sent={order_audit['email_sent']}; "
        f"draft_should_not_be_sent={order_audit['existing_unsent_gmail_draft_should_not_be_sent']}; "
        f"#22582={order_22582['blocked_classification']}; "
        f"next_candidate={next_candidate['order_name']}; "
        f"ali_reviews_api_status={ali['status']}."
    )


def _bool_text(value) -> str:
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "unknown"
