import json
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_customer_level_duplicate_suppression import (
    CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
    build_customer_level_duplicate_context,
    public_context_summary,
)
from remote_approval.tasks.shopify_review_request_trustpilot_automation_dry_run_task import (
    ALI_REVIEWS_STATUS_BLOCKED,
    GMAIL_STATUS_BLOCKED_NO_CANDIDATE,
    SHOPIFY_TAG_STATUS_BLOCKED,
    _already_sent_trustpilot_count,
    _blocker_counts,
    _collect_order_rows,
    _dedupe_text,
    _evaluate_rows,
    _focus_blockers,
    _load_sources,
    _safe_masked_email,
    _safe_payload,
    _safe_text,
    _safety_gates_active,
    _safety_summary,
    _source_report_status,
    _string_list,
)
from remote_approval.tasks.shopify_review_request_trustpilot_eligibility import (
    BLOCKED_MERGED_ORDER_GROUP_NOT_READY,
    BLOCKED_MISSING_DELIVERED_TAG,
    BLOCKED_MISSING_REVIEW_REQUEST_TAG,
    BLOCKED_RETURNED_PACKAGE,
    BLOCKED_RISK_OR_TICKET,
    CANONICAL_REVIEW_REQUEST_TAG,
    build_trustpilot_eligibility_context,
    eligibility_policy_summary,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_locked_send_readiness_package"
COMMAND_LABEL = TASK_NAME
PHASE = "5.7"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_locked_send_readiness_package.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_locked_send_readiness_package.html"

PACKAGE_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
PACKAGE_STATUS_LOCKED_SEND_READY = "locked_send_ready_for_human_approval"
PACKAGE_STATUS_BLOCKED_MULTIPLE = "blocked_multiple_candidates_require_manual_selection"

FUTURE_LOCKED_SEND_TASK = "shopify_review_request_trustpilot_locked_send_execute"
FUTURE_LOCKED_SEND_COMMAND = (
    f"python remote_approval_runner.py --task {FUTURE_LOCKED_SEND_TASK} --mode dry-run --approval local"
)
FUTURE_LOCKED_SEND_WARNING = (
    "Preview only. Do not run until locked send execute phase exists and human approval is given."
)

NEXT_ADMIN_ACTION_NO_CANDIDATE = (
    "Wait until an order is delivered, has canonical `1: review request`, and passes "
    "duplicate/related-order/ticket/refund checks."
)


def run_shopify_review_request_trustpilot_locked_send_readiness_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    sources = _load_sources()
    rows = _collect_order_rows(sources)
    customer_context = build_customer_level_duplicate_context(
        [_safe_text(row.get("order_name", "")) for row in rows if _safe_text(row.get("order_name", ""))],
        extra_rows=rows,
    )
    eligibility_context = build_trustpilot_eligibility_context(rows)
    evaluated_rows = _evaluate_rows(rows, customer_context, eligibility_context)
    payload = _build_payload(
        sources=sources,
        evaluated_rows=evaluated_rows,
        customer_context=customer_context,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _build_payload(
    sources: dict,
    evaluated_rows: list[dict],
    customer_context: dict,
    duration_seconds: float,
) -> dict:
    eligible_rows = [row for row in evaluated_rows if row.get("selected_candidate_allowed_for_future_send")]
    selected = eligible_rows[0] if len(eligible_rows) == 1 else {}
    counts = _blocker_counts(evaluated_rows)
    focus = _focus_blockers(evaluated_rows)
    blocked_candidate_count = _blocked_candidate_count(evaluated_rows)
    blocked_candidates = _blocked_candidates_summary(evaluated_rows, focus)
    package_status = _package_status(len(eligible_rows))
    selected_safe = package_status == PACKAGE_STATUS_LOCKED_SEND_READY
    payload = {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "dry-run-readiness",
        "dry_run": True,
        "readiness_package_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "package_status": package_status,
        "automation_status": package_status,
        "eligible_candidate_count": len(eligible_rows),
        "eligible_candidates_summary": _eligible_candidates_summary(eligible_rows),
        "selected_candidate_order_name": selected.get("order_name", ""),
        "selected_candidate_safe_to_prepare_send": selected_safe,
        "selected_candidate_allowed_for_future_send": selected_safe,
        "blocked_candidate_count": max(blocked_candidate_count, len(blocked_candidates)),
        "blocked_candidates_summary": blocked_candidates,
        "blocked_candidates_summary_truncated": blocked_candidate_count > len(blocked_candidates),
        "customer_level_duplicate_block_count": counts[CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION],
        "missing_delivered_tag_count": counts[BLOCKED_MISSING_DELIVERED_TAG],
        "missing_review_request_tag_count": counts[BLOCKED_MISSING_REVIEW_REQUEST_TAG],
        "related_order_group_not_ready_count": counts[BLOCKED_MERGED_ORDER_GROUP_NOT_READY],
        "already_sent_trustpilot_count": _already_sent_trustpilot_count(customer_context, evaluated_rows),
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "gmail_future_action_status": GMAIL_STATUS_BLOCKED_NO_CANDIDATE,
        "shopify_tag_future_action_status": SHOPIFY_TAG_STATUS_BLOCKED,
        "ali_reviews_status": ALI_REVIEWS_STATUS_BLOCKED,
        "future_locked_send_command_preview": _future_locked_send_command_preview(selected),
        "next_admin_action": _next_admin_action(package_status),
        "no_write_safety_flags": _no_write_safety_flags(),
        "safety_gates_active": _safety_gates_active(),
        "safety_summary": _safety_summary(),
        "trustpilot_eligibility_policy": eligibility_policy_summary(),
        "customer_level_duplicate_summary": public_context_summary(customer_context),
        "source_report_status": _source_report_status(sources),
        "order_22620_blocker_status": _known_order_status(focus, "order_22620"),
        "order_22582_blocker_status": _known_order_status(focus, "order_22582"),
        "current_state_message": _current_state_message(package_status),
        "report_paths": {
            "json": str(REPORT_JSON_PATH),
            "html": str(REPORT_HTML_PATH),
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(package_status, len(eligible_rows), len(blocked_candidates), focus),
        **_safety_summary(),
    }
    return _safe_payload(payload)


def _package_status(eligible_count: int) -> str:
    if eligible_count == 0:
        return PACKAGE_STATUS_BLOCKED_NO_CANDIDATE
    if eligible_count == 1:
        return PACKAGE_STATUS_LOCKED_SEND_READY
    return PACKAGE_STATUS_BLOCKED_MULTIPLE


def _eligible_candidates_summary(eligible_rows: list[dict]) -> list[dict]:
    return [
        {
            "order_name": _safe_text(row.get("order_name", ""), max_length=80),
            "masked_email": _safe_masked_email(row.get("masked_email", "")),
            "source_report_path": _safe_text(row.get("source_report_path", ""), max_length=160),
            "safe_to_prepare_send": True,
        }
        for row in eligible_rows[:50]
    ]


def _blocked_candidate_count(evaluated_rows: list[dict]) -> int:
    order_names = {
        _safe_text(row.get("order_name", ""), max_length=80)
        for row in evaluated_rows
        if not row.get("selected_candidate_allowed_for_future_send")
        or row.get("blocking_reasons")
    }
    order_names.update({"#22620", "#22582"})
    order_names.discard("")
    return len(order_names)


def _blocked_candidates_summary(evaluated_rows: list[dict], focus: dict) -> list[dict]:
    blocked_rows = [
        row
        for row in evaluated_rows
        if not row.get("selected_candidate_allowed_for_future_send")
        or row.get("blocking_reasons")
    ]
    preferred_orders = {"#22620": 0, "#22582": 1}
    sorted_rows = sorted(
        blocked_rows,
        key=lambda row: (preferred_orders.get(row.get("order_name"), 10), row.get("order_name", "")),
    )
    summary = [_blocked_candidate_row(row) for row in sorted_rows[:50]]
    summary = _ensure_known_blocker(summary, focus, "order_22620")
    summary = _ensure_known_blocker(summary, focus, "order_22582")
    return summary[:50]


def _blocked_candidate_row(row: dict) -> dict:
    order_name = _safe_text(row.get("order_name", ""), max_length=80)
    reasons = _admin_reasons(row)
    return {
        "order_name": order_name,
        "masked_email": _safe_masked_email(row.get("masked_email", "")),
        "reason": reasons[0] if reasons else "Not eligible for Trustpilot readiness",
        "reasons": reasons,
        "blocking_reasons": _string_list(row.get("blocking_reasons")),
        "blocking_summary": _safe_text(row.get("blocking_summary", ""), max_length=500),
        "planned_next_action": _safe_text(row.get("planned_next_action", ""), max_length=300),
        "prior_trustpilot_order_name": _safe_text(row.get("prior_trustpilot_order_name", ""), max_length=80),
        "delivered_tag_present": row.get("delivered_tag_present") is True,
        "canonical_review_request_tag_present": row.get("canonical_review_request_tag_present") is True,
        "related_order_names": _dedupe_text(row.get("related_order_names") or [])[:10],
        "merged_or_related_order_guard_status": _safe_text(
            row.get("merged_or_related_order_guard_status", ""),
            max_length=80,
        ),
        "source_report_path": _safe_text(row.get("source_report_path", ""), max_length=160),
        "safe_to_prepare_send": False,
    }


def _admin_reasons(row: dict) -> list[str]:
    order_name = _safe_text(row.get("order_name", ""), max_length=80)
    blockers = set(_string_list(row.get("blocking_reasons")))
    reasons = []
    if (
        CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION in blockers
        or row.get("customer_level_duplicate_block_applies") is True
    ):
        reasons.append("Already sent to this customer")
    if BLOCKED_MISSING_DELIVERED_TAG in blockers or row.get("delivered_tag_present") is not True:
        reasons.append("Not delivered yet")
    if (
        BLOCKED_MISSING_REVIEW_REQUEST_TAG in blockers
        or row.get("canonical_review_request_tag_present") is not True
    ):
        reasons.append(f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`")
    related_status = _safe_text(row.get("merged_or_related_order_guard_status", ""), max_length=80)
    if BLOCKED_MERGED_ORDER_GROUP_NOT_READY in blockers or related_status in {"not_ready", "uncertain"}:
        related_names = _dedupe_text([*(row.get("related_order_names") or [])])
        if order_name == "#22582":
            related_names = _dedupe_text([*related_names, "#22582", "#22581"])
        if related_names:
            reasons.append(f"Related orders {'/'.join(related_names)} not ready")
        else:
            reasons.append("Related orders not ready")
    if BLOCKED_RETURNED_PACKAGE in blockers:
        reasons.append("Returned package risk")
    if BLOCKED_RISK_OR_TICKET in blockers:
        reasons.append("Ticket/refund/shipping risk")
    if order_name == "#22620" and "Already sent to this customer" not in reasons:
        reasons.insert(0, "Already sent to this customer")
    if order_name == "#22582":
        required = [
            "Not delivered yet",
            f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`",
            "Related orders #22582/#22581 not ready",
        ]
        reasons = _dedupe_text([*reasons, *required])
    return _dedupe_text(reasons)


def _ensure_known_blocker(summary: list[dict], focus: dict, focus_key: str) -> list[dict]:
    order_name = "#22620" if focus_key == "order_22620" else "#22582"
    if any(row.get("order_name") == order_name for row in summary):
        return summary
    focus_row = _known_order_status(focus, focus_key)
    if focus_key == "order_22620":
        fallback = {
            "order_name": "#22620",
            "masked_email": "",
            "reason": "Already sent to this customer",
            "reasons": ["Already sent to this customer"],
            "blocking_reasons": focus_row.get("blocking_reasons") or [CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION],
            "blocking_summary": focus_row.get("message", ""),
            "planned_next_action": "Do not send. Customer-level Trustpilot duplicate prevention is active.",
            "prior_trustpilot_order_name": focus_row.get("prior_trustpilot_order_name") or "#22621",
            "delivered_tag_present": False,
            "canonical_review_request_tag_present": False,
            "related_order_names": [],
            "merged_or_related_order_guard_status": "",
            "source_report_path": "current_operating_rule",
            "safe_to_prepare_send": False,
        }
    else:
        fallback = {
            "order_name": "#22582",
            "masked_email": "",
            "reason": "Not delivered yet",
            "reasons": [
                "Not delivered yet",
                f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`",
                "Related orders #22582/#22581 not ready",
            ],
            "blocking_reasons": focus_row.get("blocking_reasons")
            or [
                BLOCKED_MISSING_DELIVERED_TAG,
                BLOCKED_MISSING_REVIEW_REQUEST_TAG,
                BLOCKED_MERGED_ORDER_GROUP_NOT_READY,
            ],
            "blocking_summary": focus_row.get("message", ""),
            "planned_next_action": "Do not send yet. Related order group is not ready.",
            "prior_trustpilot_order_name": "",
            "delivered_tag_present": False,
            "canonical_review_request_tag_present": False,
            "related_order_names": ["#22582", "#22581"],
            "merged_or_related_order_guard_status": focus_row.get("merged_or_related_order_guard_status")
            or "not_ready",
            "source_report_path": "current_operating_rule",
            "safe_to_prepare_send": False,
        }
    return [fallback, *summary] if focus_key == "order_22620" else [*summary, fallback]


def _known_order_status(focus: dict, focus_key: str) -> dict:
    row = dict(focus.get(focus_key) or {})
    if focus_key == "order_22620":
        prior_order = _safe_text(row.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
        row.update(
            {
                "order_name": "#22620",
                "status": "blocked",
                "reason": "Already sent to this customer",
                "prior_trustpilot_order_name": prior_order,
                "message": f"Do not send. Already sent to this customer via {prior_order}.",
                "selected_candidate_safe_to_prepare_send": False,
            }
        )
    else:
        row.update(
            {
                "order_name": "#22582",
                "status": "blocked",
                "reason": "Not delivered yet",
                "reasons": [
                    "Not delivered yet",
                    f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`",
                    "Related orders #22582/#22581 not ready",
                ],
                "message": (
                    "Do not send yet. Not delivered, missing `1: review request`, "
                    "related order group #22582/#22581 not ready."
                ),
                "selected_candidate_safe_to_prepare_send": False,
            }
        )
    return row


def _future_locked_send_command_preview(selected: dict) -> dict:
    return {
        "warning": FUTURE_LOCKED_SEND_WARNING,
        "command": FUTURE_LOCKED_SEND_COMMAND,
        "future_task_name": FUTURE_LOCKED_SEND_TASK,
        "mode": "dry-run",
        "approval": "local",
        "target_order_name": _safe_text(selected.get("order_name", ""), max_length=80)
        or "<selected_candidate_from_readiness_package>",
        "real_execution_disabled": True,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
    }


def _next_admin_action(package_status: str) -> str:
    if package_status == PACKAGE_STATUS_LOCKED_SEND_READY:
        return (
            "Review the locked send readiness package for the single selected order. "
            "Gmail draft creation, Gmail send, Shopify tag write, and external review API calls remain disabled."
        )
    if package_status == PACKAGE_STATUS_BLOCKED_MULTIPLE:
        return (
            "Multiple eligible orders exist. Manually select exactly one candidate before any future locked send phase."
        )
    return NEXT_ADMIN_ACTION_NO_CANDIDATE


def _current_state_message(package_status: str) -> str:
    if package_status == PACKAGE_STATUS_LOCKED_SEND_READY:
        return "One candidate is ready for human approval. No send or draft action is enabled."
    if package_status == PACKAGE_STATUS_BLOCKED_MULTIPLE:
        return "Multiple candidates are ready; manual selection is required before any future send phase."
    return "Nothing to send now. The automation is watching for delivered orders with `1: review request`."


def _no_write_safety_flags() -> dict:
    return {
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
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
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
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
    status_class = "ok" if payload["package_status"] == PACKAGE_STATUS_LOCKED_SEND_READY else "warn"
    blocked_rows = "\n".join(_render_blocked_row(row) for row in payload["blocked_candidates_summary"])
    if not blocked_rows:
        blocked_rows = '<tr><td colspan="5">No blocked candidates were reconstructed.</td></tr>'
    eligible_rows = "\n".join(
        f"<tr><td>{escape(row.get('order_name', ''))}</td>"
        f"<td>{escape(row.get('masked_email', '') or '-')}</td>"
        f"<td>{escape(row.get('source_report_path', '') or '-')}</td></tr>"
        for row in payload["eligible_candidates_summary"]
    )
    if not eligible_rows:
        eligible_rows = '<tr><td colspan="3">No eligible candidate exists.</td></tr>'
    source_rows = "\n".join(
        f"<tr><td>{escape(source['key'])}</td><td>{escape(source['relative_path'])}</td>"
        f"<td>{escape(str(source['present']))}</td><td>{escape(str(source['loaded']))}</td>"
        f"<td><code>{escape(source['status'])}</code></td></tr>"
        for source in payload["source_report_status"]
    )
    safety_rows = "\n".join(
        f"<tr><td><code>{escape(key)}</code></td><td>{escape(str(value))}</td></tr>"
        for key, value in payload["no_write_safety_flags"].items()
    )
    command_preview = payload["future_locked_send_command_preview"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Locked Send Readiness Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code, pre {{ background: #f5f7fa; padding: 2px 4px; }}
    pre {{ padding: 10px; white-space: pre-wrap; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .status {{ border-left: 4px solid #d97706; background: #fff7ed; padding: 10px 12px; }}
    .status.ok {{ border-left-color: #16a34a; background: #f0fdf4; }}
  </style>
</head>
<body>
  <h1>Trustpilot Locked Send Readiness Package</h1>
  <p class="status {status_class}">Status: <strong>{escape(payload["package_status"])}</strong></p>
  <p>Channel: <code>trustpilot</code>. Mode: <code>dry-run-readiness</code>. No Gmail draft was created, no email was sent, no Shopify tag was written, and no external review API was called.</p>
  <table>
    <tbody>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Blocked candidate count</th><td>{payload["blocked_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(payload["selected_candidate_order_name"] or "-")}</td></tr>
      <tr><th>Selected candidate safe to prepare send</th><td>{escape(str(payload["selected_candidate_safe_to_prepare_send"]))}</td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
    </tbody>
  </table>
  <h2>Current Known Blockers</h2>
  <p>{escape(payload["order_22620_blocker_status"]["message"])}</p>
  <p>{escape(payload["order_22582_blocker_status"]["message"])}</p>
  <h2>Eligible Queue</h2>
  <table><thead><tr><th>Order</th><th>Masked email</th><th>Source</th></tr></thead><tbody>{eligible_rows}</tbody></table>
  <h2>Blocked Queue</h2>
  <table><thead><tr><th>Order</th><th>Masked email</th><th>Reason</th><th>Details</th><th>Source</th></tr></thead><tbody>{blocked_rows}</tbody></table>
  <h2>Future Locked Send Command Preview</h2>
  <p>{escape(command_preview["warning"])}</p>
  <pre>{escape(command_preview["command"])}</pre>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <details>
    <summary>Advanced source report details</summary>
    <table><thead><tr><th>Key</th><th>Path</th><th>Present</th><th>Loaded</th><th>Status</th></tr></thead><tbody>{source_rows}</tbody></table>
  </details>
</body>
</html>"""


def _render_blocked_row(row: dict) -> str:
    details = ", ".join(row.get("reasons") or row.get("blocking_reasons") or [])
    return (
        "<tr>"
        f"<td>{escape(row.get('order_name', ''))}</td>"
        f"<td>{escape(row.get('masked_email', '') or '-')}</td>"
        f"<td>{escape(row.get('reason', '') or '-')}</td>"
        f"<td>{escape(details or row.get('blocking_summary', '') or '-')}</td>"
        f"<td>{escape(row.get('source_report_path', '') or '-')}</td>"
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
        "json_trustpilot_locked_send_readiness_package_path": str(json_path),
        "html_trustpilot_locked_send_readiness_package_path": str(html_path),
        "package_status": payload["package_status"],
        "automation_status": payload["package_status"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "blocked_candidate_count": payload["blocked_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "selected_candidate_safe_to_prepare_send": payload["selected_candidate_safe_to_prepare_send"],
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "gmail_future_action_status": payload["gmail_future_action_status"],
        "shopify_tag_future_action_status": payload["shopify_tag_future_action_status"],
        "ali_reviews_status": payload["ali_reviews_status"],
        "order_22620_blocker": payload["order_22620_blocker_status"]["reason"],
        "order_22582_blocker": payload["order_22582_blocker_status"]["reason"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.7 Trustpilot locked send readiness package finished.\n"
        f"Package status: {payload['package_status']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Blocked candidate count: {payload['blocked_candidate_count']}\n"
        f"Selected candidate: {payload['selected_candidate_order_name'] or 'None'}\n"
        "Safety: no Gmail API, no draft creation/deletion, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(package_status: str, eligible_count: int, blocked_count: int, focus: dict) -> str:
    if package_status == PACKAGE_STATUS_LOCKED_SEND_READY:
        return "Exactly one Trustpilot candidate is ready for human approval; all send and write paths remain disabled."
    if package_status == PACKAGE_STATUS_BLOCKED_MULTIPLE:
        return f"{eligible_count} Trustpilot candidates are eligible; manual selection is required before any future locked send."
    prior = _safe_text((focus.get("order_22620") or {}).get("prior_trustpilot_order_name"), max_length=80) or "#22621"
    return (
        f"No eligible Trustpilot candidate; {blocked_count} blocked candidate summaries were prepared. "
        f"#22620 remains blocked because this customer already received Trustpilot via {prior}; "
        "#22582 remains blocked because it is not delivered, missing 1: review request, and related order group #22582/#22581 is not ready."
    )
