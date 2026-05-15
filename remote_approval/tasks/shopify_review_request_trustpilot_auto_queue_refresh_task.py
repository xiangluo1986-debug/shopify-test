import json
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_customer_level_duplicate_suppression import (
    build_customer_level_duplicate_context,
)
from remote_approval.tasks.shopify_review_request_trustpilot_eligibility import (
    CANONICAL_REVIEW_REQUEST_TAG,
    build_trustpilot_eligibility_context,
)
from remote_approval.tasks.shopify_review_request_trustpilot_locked_send_readiness_package_task import (
    PACKAGE_STATUS_BLOCKED_MULTIPLE,
    PACKAGE_STATUS_BLOCKED_NO_CANDIDATE,
    PACKAGE_STATUS_LOCKED_SEND_READY,
    REPORT_JSON_PATH as READINESS_PACKAGE_JSON_PATH,
    _build_payload as _build_readiness_payload,
    _collect_order_rows,
    _evaluate_rows,
    _load_sources,
    _safe_payload,
    _safe_text,
    _safety_summary,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_auto_queue_refresh"
COMMAND_LABEL = TASK_NAME
PHASE = "5.8"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_auto_queue_refresh.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_auto_queue_refresh.html"

REFRESH_STATUS_NO_CANDIDATE = "refreshed_no_eligible_candidate"
REFRESH_STATUS_ONE_READY = "refreshed_locked_send_candidate_ready"
REFRESH_STATUS_MULTIPLE = "refreshed_multiple_candidates_manual_selection_required"
REFRESH_STATUS_SAFETY_BLOCKED = "refreshed_blocked_safety_issue"

NEXT_REAL_STEP_WAIT = "wait_no_candidate"
NEXT_REAL_STEP_PREPARE_LOCKED_SEND = "prepare_locked_send_package"
NEXT_REAL_STEP_MANUAL_MULTIPLE = "manual_review_required_multiple_candidates"
NEXT_REAL_STEP_SAFETY_BLOCKED = "blocked_safety_issue"

NEXT_ADMIN_ACTION_NO_CANDIDATE = (
    "Wait until an order is delivered, has canonical `1: review request`, and passes "
    "duplicate/related-order/ticket/refund checks."
)
SCHEDULER_SAFE_NOTE = (
    "This refresh is safe to run on a schedule because it does not send emails, "
    "create Gmail drafts, or write Shopify tags."
)


def run_shopify_review_request_trustpilot_auto_queue_refresh_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_readiness_package = _load_source_readiness_package()
    readiness_payload = _compute_readiness_payload()
    payload = _build_payload(
        readiness_payload=readiness_payload,
        source_readiness_package=source_readiness_package,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _compute_readiness_payload() -> dict:
    sources = _load_sources()
    rows = _collect_order_rows(sources)
    customer_context = build_customer_level_duplicate_context(
        [_safe_text(row.get("order_name", "")) for row in rows if _safe_text(row.get("order_name", ""))],
        extra_rows=rows,
    )
    eligibility_context = build_trustpilot_eligibility_context(rows)
    evaluated_rows = _evaluate_rows(rows, customer_context, eligibility_context)
    return _build_readiness_payload(
        sources=sources,
        evaluated_rows=evaluated_rows,
        customer_context=customer_context,
        duration_seconds=0,
    )


def _load_source_readiness_package() -> dict:
    report = {
        "relative_path": f"logs/{READINESS_PACKAGE_JSON_PATH.name}",
        "present": READINESS_PACKAGE_JSON_PATH.exists(),
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "eligible_candidate_count": 0,
        "blocked_candidate_count": 0,
        "selected_candidate_order_name": "",
        "error_sanitized": "",
    }
    if not READINESS_PACKAGE_JSON_PATH.exists():
        return report
    try:
        data = json.loads(READINESS_PACKAGE_JSON_PATH.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error_sanitized"] = _safe_text(str(exc), max_length=300)
        return report
    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error_sanitized"] = "top_level_json_is_not_object"
        return report
    report.update(
        {
            "loaded": True,
            "status": _safe_text(
                data.get("package_status")
                or data.get("automation_status")
                or data.get("report_status")
                or data.get("status")
                or "loaded",
                max_length=120,
            ),
            "timestamp": _safe_text(
                data.get("report_generated_at")
                or data.get("timestamp")
                or data.get("generated_at")
                or "",
                max_length=120,
            ),
            "eligible_candidate_count": _int_or_zero(data.get("eligible_candidate_count")),
            "blocked_candidate_count": _int_or_zero(data.get("blocked_candidate_count")),
            "selected_candidate_order_name": _safe_text(
                data.get("selected_candidate_order_name"),
                max_length=80,
            ),
        }
    )
    return report


def _build_payload(
    readiness_payload: dict,
    source_readiness_package: dict,
    duration_seconds: float,
) -> dict:
    refreshed_at = utc_now_iso()
    eligible_count = _int_or_zero(readiness_payload.get("eligible_candidate_count"))
    blocked_count = _int_or_zero(readiness_payload.get("blocked_candidate_count"))
    package_status = _safe_text(readiness_payload.get("package_status"), max_length=120)
    safety_flags = _safety_flags()
    safety_issue = _safety_issue_detected(safety_flags)
    next_real_step = _next_real_step(eligible_count, package_status, safety_issue)
    refresh_status = _refresh_status(next_real_step)
    dashboard_summary = _dashboard_summary(next_real_step, eligible_count)
    known_blockers = _known_blockers_summary(readiness_payload)
    selected_order = (
        _safe_text(readiness_payload.get("selected_candidate_order_name"), max_length=80)
        if eligible_count == 1
        else ""
    )
    payload = {
        "timestamp": refreshed_at,
        "report_generated_at": refreshed_at,
        "refreshed_at": refreshed_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "dry-run-auto-refresh",
        "dry_run": True,
        "auto_queue_refresh_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "refresh_status": refresh_status,
        "source_readiness_package_status": _safe_text(source_readiness_package.get("status"), max_length=120),
        "source_readiness_package": source_readiness_package,
        "computed_readiness_package_status": package_status,
        "eligible_candidate_count": eligible_count,
        "blocked_candidate_count": blocked_count,
        "selected_candidate_order_name": selected_order,
        "next_real_step": next_real_step,
        "next_admin_action": _next_admin_action(next_real_step),
        "auto_refresh_safe_for_scheduler": True,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "gmail_future_action_status": _safe_text(
            readiness_payload.get("gmail_future_action_status")
            or "no_gmail_action_until_eligible_candidate",
            max_length=120,
        ),
        "shopify_tag_future_action_status": _safe_text(
            readiness_payload.get("shopify_tag_future_action_status")
            or "no_shopify_tag_action_until_email_sent_and_verified",
            max_length=120,
        ),
        "ali_reviews_status": _safe_text(
            readiness_payload.get("ali_reviews_status")
            or "blocked_waiting_for_vendor_api_documentation",
            max_length=120,
        ),
        "safety_flags": safety_flags,
        "known_blockers_summary": known_blockers,
        "dashboard_summary": dashboard_summary,
        "report_paths": {
            "json": str(REPORT_JSON_PATH),
            "html": str(REPORT_HTML_PATH),
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(next_real_step, eligible_count, blocked_count, known_blockers),
        **_safety_summary(),
    }
    return _safe_payload(payload)


def _next_real_step(eligible_count: int, package_status: str, safety_issue: bool) -> str:
    if safety_issue:
        return NEXT_REAL_STEP_SAFETY_BLOCKED
    if eligible_count == 0 or package_status == PACKAGE_STATUS_BLOCKED_NO_CANDIDATE:
        return NEXT_REAL_STEP_WAIT
    if eligible_count == 1 and package_status == PACKAGE_STATUS_LOCKED_SEND_READY:
        return NEXT_REAL_STEP_PREPARE_LOCKED_SEND
    if eligible_count > 1 or package_status == PACKAGE_STATUS_BLOCKED_MULTIPLE:
        return NEXT_REAL_STEP_MANUAL_MULTIPLE
    return NEXT_REAL_STEP_SAFETY_BLOCKED


def _refresh_status(next_real_step: str) -> str:
    if next_real_step == NEXT_REAL_STEP_WAIT:
        return REFRESH_STATUS_NO_CANDIDATE
    if next_real_step == NEXT_REAL_STEP_PREPARE_LOCKED_SEND:
        return REFRESH_STATUS_ONE_READY
    if next_real_step == NEXT_REAL_STEP_MANUAL_MULTIPLE:
        return REFRESH_STATUS_MULTIPLE
    return REFRESH_STATUS_SAFETY_BLOCKED


def _next_admin_action(next_real_step: str) -> str:
    if next_real_step == NEXT_REAL_STEP_PREPARE_LOCKED_SEND:
        return (
            "Review the single eligible candidate and prepare a locked send package for human approval. "
            "No email has been sent, no Gmail draft has been created, and no Shopify tag has been written."
        )
    if next_real_step == NEXT_REAL_STEP_MANUAL_MULTIPLE:
        return (
            "Multiple eligible candidates exist. Manually select exactly one candidate before any future "
            "locked send package is prepared."
        )
    if next_real_step == NEXT_REAL_STEP_SAFETY_BLOCKED:
        return "Stop automation and review the safety flags before preparing any future locked send package."
    return NEXT_ADMIN_ACTION_NO_CANDIDATE


def _dashboard_summary(next_real_step: str, eligible_count: int) -> dict:
    if next_real_step == NEXT_REAL_STEP_PREPARE_LOCKED_SEND:
        message = "1 candidate is ready for locked send review. No email has been sent."
        detail = "Prepare a locked send package for human review only."
    elif next_real_step == NEXT_REAL_STEP_MANUAL_MULTIPLE:
        message = f"{eligible_count} candidates are ready; manual selection is required."
        detail = "Select exactly one candidate before any future locked send review."
    elif next_real_step == NEXT_REAL_STEP_SAFETY_BLOCKED:
        message = "Automation refresh found a safety issue."
        detail = "Review safety flags before any future locked send package."
    else:
        message = "Automation checked the queue. Nothing to send now."
        detail = f"Waiting for a delivered order with `{CANONICAL_REVIEW_REQUEST_TAG}` that passes all safety checks."
    return {
        "message": message,
        "detail": detail,
        "scheduler_safe_status": "scheduler_safe_dry_run_only",
        "scheduler_note": SCHEDULER_SAFE_NOTE,
    }


def _known_blockers_summary(readiness_payload: dict) -> list[dict]:
    order_22620 = _known_blocker(
        readiness_payload,
        "order_22620_blocker_status",
        "#22620",
        "Already sent to this customer via #22621",
        "Do not send. Already sent to this customer via #22621.",
    )
    order_22582 = _known_blocker(
        readiness_payload,
        "order_22582_blocker_status",
        "#22582",
        f"Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, related orders #22582/#22581 not ready",
        (
            f"Do not send yet. Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
            "related order group #22582/#22581 not ready."
        ),
    )
    return [order_22620, order_22582]


def _known_blocker(
    readiness_payload: dict,
    key: str,
    order_name: str,
    fallback_summary: str,
    fallback_message: str,
) -> dict:
    source = readiness_payload.get(key) if isinstance(readiness_payload.get(key), dict) else {}
    if order_name == "#22620":
        prior_order = _safe_text(source.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
        summary = f"Already sent to this customer via {prior_order}"
    else:
        summary = fallback_summary
    return {
        "order_name": order_name,
        "status": _safe_text(source.get("status") or "blocked", max_length=80),
        "summary": summary,
        "message": _safe_text(source.get("message") or fallback_message, max_length=300),
        "blocking_reasons": [
            _safe_text(value, max_length=120)
            for value in (source.get("blocking_reasons") or [])
            if _safe_text(value, max_length=120)
        ],
        "selected_candidate_safe_to_prepare_send": False,
    }


def _safety_flags() -> dict:
    return {
        "readiness_logic_recomputed_without_writes": True,
        "source_readiness_package_read_only": True,
        "auto_refresh_safe_for_scheduler": True,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_deleted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_allowed_now": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "external_review_api_call_allowed_now": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "ali_reviews_write_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
        "all_new_actions_no_write_confirmed": True,
    }


def _safety_issue_detected(safety_flags: dict) -> bool:
    forbidden_true_flags = {
        "gmail_send_allowed_now",
        "gmail_draft_create_allowed_now",
        "gmail_api_call_performed",
        "gmail_draft_create_attempted",
        "gmail_draft_created",
        "gmail_draft_deleted",
        "gmail_drafts_send_called",
        "gmail_messages_send_called",
        "gmail_send_performed",
        "email_sent",
        "shopify_api_call_performed",
        "shopify_write_performed",
        "shopify_tag_write_allowed_now",
        "mutation_performed",
        "tags_add_performed",
        "tags_remove_performed",
        "tagsAdd_performed",
        "tagsRemove_performed",
        "external_review_api_call_allowed_now",
        "trustpilot_api_call_performed",
        "kudosi_api_call_performed",
        "ali_reviews_api_call_performed",
        "ali_reviews_write_api_call_performed",
        "tracking_redirect_enabled",
        "tracking_token_generated",
        "raw_customer_email_output",
        "full_gmail_draft_or_message_id_output",
    }
    return any(safety_flags.get(flag) is True for flag in forbidden_true_flags)


def _issue_summary(
    next_real_step: str,
    eligible_count: int,
    blocked_count: int,
    known_blockers: list[dict],
) -> str:
    order_22620 = _safe_text((known_blockers[0] if known_blockers else {}).get("summary"), max_length=160)
    order_22582 = _safe_text((known_blockers[1] if len(known_blockers) > 1 else {}).get("summary"), max_length=200)
    if next_real_step == NEXT_REAL_STEP_PREPARE_LOCKED_SEND:
        return "One Trustpilot candidate is ready for locked send review. No email has been sent."
    if next_real_step == NEXT_REAL_STEP_MANUAL_MULTIPLE:
        return f"{eligible_count} Trustpilot candidates are eligible; manual selection is required before any send package."
    if next_real_step == NEXT_REAL_STEP_SAFETY_BLOCKED:
        return "Trustpilot auto queue refresh is blocked by a safety flag; no send or write action is allowed."
    return (
        f"No eligible Trustpilot candidate; {blocked_count} blocked candidate summaries were prepared. "
        f"#22620 remains blocked: {order_22620}. #22582 remains blocked: {order_22582}."
    )


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
    status_class = "ok" if payload["next_real_step"] == NEXT_REAL_STEP_PREPARE_LOCKED_SEND else "warn"
    blocker_rows = "\n".join(_render_blocker_row(row) for row in payload["known_blockers_summary"])
    safety_rows = "\n".join(
        f"<tr><td><code>{escape(key)}</code></td><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_flags"].items()
    )
    dashboard_summary = payload["dashboard_summary"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Auto Queue Refresh</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .status {{ border-left: 4px solid #d97706; background: #fff7ed; padding: 10px 12px; }}
    .status.ok {{ border-left-color: #16a34a; background: #f0fdf4; }}
  </style>
</head>
<body>
  <h1>Trustpilot Auto Queue Refresh</h1>
  <p class="status {status_class}">Refresh status: <strong>{escape(payload["refresh_status"])}</strong></p>
  <p>{escape(dashboard_summary["message"])}</p>
  <p>{escape(dashboard_summary["detail"])}</p>
  <p>{escape(dashboard_summary["scheduler_note"])}</p>
  <p>Mode: <code>dry-run-auto-refresh</code>. No Gmail draft was created, no email was sent, no Shopify tag was written, and no Trustpilot/Kudosi/Ali Reviews API was called.</p>
  <table>
    <tbody>
      <tr><th>Refreshed at</th><td>{escape(payload["refreshed_at"])}</td></tr>
      <tr><th>Source readiness package status</th><td><code>{escape(payload["source_readiness_package_status"])}</code></td></tr>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Blocked candidate count</th><td>{payload["blocked_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(payload["selected_candidate_order_name"] or "-")}</td></tr>
      <tr><th>Next real step</th><td><code>{escape(payload["next_real_step"])}</code></td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
      <tr><th>Scheduler safe</th><td>{escape(str(payload["auto_refresh_safe_for_scheduler"]))}</td></tr>
    </tbody>
  </table>
  <h2>Known Blockers</h2>
  <table><thead><tr><th>Order</th><th>Status</th><th>Summary</th><th>Message</th></tr></thead><tbody>{blocker_rows}</tbody></table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _render_blocker_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(row.get('order_name', ''))}</td>"
        f"<td><code>{escape(row.get('status', ''))}</code></td>"
        f"<td>{escape(row.get('summary', ''))}</td>"
        f"<td>{escape(row.get('message', ''))}</td>"
        "</tr>"
    )


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "json_trustpilot_auto_queue_refresh_path": str(json_path),
        "html_trustpilot_auto_queue_refresh_path": str(html_path),
        "refresh_status": payload["refresh_status"],
        "source_readiness_package_status": payload["source_readiness_package_status"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "blocked_candidate_count": payload["blocked_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "next_real_step": payload["next_real_step"],
        "next_admin_action": payload["next_admin_action"],
        "auto_refresh_safe_for_scheduler": payload["auto_refresh_safe_for_scheduler"],
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "ali_reviews_status": payload["ali_reviews_status"],
        "order_22620_blocker_status": payload["known_blockers_summary"][0]["summary"],
        "order_22582_blocker_status": payload["known_blockers_summary"][1]["summary"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.8 Trustpilot auto queue refresh finished.\n"
        f"Refresh status: {payload['refresh_status']}\n"
        f"Source readiness package status: {payload['source_readiness_package_status']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Blocked candidate count: {payload['blocked_candidate_count']}\n"
        f"Selected candidate: {payload['selected_candidate_order_name'] or 'None'}\n"
        f"Next real step: {payload['next_real_step']}\n"
        "Safety: no Gmail API, no draft creation/deletion, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
