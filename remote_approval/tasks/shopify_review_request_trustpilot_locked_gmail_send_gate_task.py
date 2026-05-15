import json
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_trustpilot_automation_dry_run_task import (
    _safe_payload,
    _safe_text,
    _safety_summary,
    _string_list,
)
from remote_approval.tasks.shopify_review_request_trustpilot_eligibility import (
    CANONICAL_REVIEW_REQUEST_TAG,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_locked_gmail_send_gate"
COMMAND_LABEL = TASK_NAME
PHASE = "5.10"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate.html"

SOURCE_REPORTS = {
    "auto_queue_refresh": LOG_DIR / "shopify_review_request_trustpilot_auto_queue_refresh.json",
    "locked_send_readiness_package": (
        LOG_DIR / "shopify_review_request_trustpilot_locked_send_readiness_package.json"
    ),
    "automation_dry_run": LOG_DIR / "shopify_review_request_trustpilot_automation_dry_run.json",
    "history_ledger_audit": LOG_DIR / "shopify_review_request_history_ledger_audit.json",
}

GATE_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
GATE_STATUS_READY_FOR_ACK = "locked_send_gate_ready_for_ack"
GATE_STATUS_BLOCKED_MULTIPLE = "blocked_multiple_candidates_require_manual_selection"
GATE_STATUS_BLOCKED_SAFETY = "blocked_candidate_safety_check_failed"

REQUIRED_ACK_FOR_FUTURE_REAL_SEND = (
    "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK="
    "YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND"
)
NEXT_ADMIN_ACTION_NO_CANDIDATE = (
    "Wait until an eligible delivered order with canonical `1: review request` appears "
    "and passes all duplicate/risk checks."
)
CURRENT_NO_CANDIDATE_MESSAGE = "No email can be sent now. There is no eligible Trustpilot candidate."
FUTURE_ACK_MESSAGE = "Future sending will require a locked ACK and exactly one safe candidate."

FORBIDDEN_SOURCE_TRUE_FLAGS = {
    "send_allowed_now",
    "draft_create_allowed_now",
    "gmail_api_allowed_now",
    "gmail_send_allowed_now",
    "gmail_draft_create_allowed_now",
    "gmail_api_call_performed",
    "gmail_draft_create_attempted",
    "gmail_draft_created",
    "gmail_draft_updated",
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
    "kudosi_write_api_call_performed",
    "ali_reviews_api_call_performed",
    "ali_reviews_write_api_call_performed",
    "tracking_redirect_enabled",
    "tracking_token_generated",
    "raw_customer_email_output",
    "full_gmail_draft_or_message_id_output",
}


def run_shopify_review_request_trustpilot_locked_gmail_send_gate_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    sources = _load_sources()
    primary_source = _primary_source(sources)
    payload = _build_payload(
        sources=sources,
        primary_source=primary_source,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_sources() -> dict:
    return {key: _load_json_report(key, path) for key, path in SOURCE_REPORTS.items()}


def _load_json_report(key: str, path: Path) -> dict:
    report = {
        "key": key,
        "relative_path": f"logs/{path.name}",
        "present": path.exists(),
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "error_sanitized": "",
        "data": {},
    }
    if not path.exists():
        return report
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"), strict=False)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error_sanitized"] = _safe_text(str(exc), max_length=300)
        return report
    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error_sanitized"] = "top_level_json_is_not_object"
        return report
    report["loaded"] = True
    report["data"] = data
    report["status"] = _report_status(data)
    report["timestamp"] = _first_text(
        data,
        ("report_generated_at", "timestamp", "refreshed_at", "generated_at", "created_at", "finished_at"),
    )
    return report


def _primary_source(sources: dict) -> dict:
    for key in ("auto_queue_refresh", "locked_send_readiness_package", "automation_dry_run"):
        report = sources.get(key) or {}
        if report.get("loaded"):
            return {
                "key": key,
                "relative_path": report.get("relative_path", ""),
                "status": report.get("status", "loaded"),
                "data": report.get("data") if isinstance(report.get("data"), dict) else {},
            }
    return {"key": "", "relative_path": "", "status": "missing", "data": {}}


def _build_payload(sources: dict, primary_source: dict, duration_seconds: float) -> dict:
    data = primary_source.get("data") if isinstance(primary_source.get("data"), dict) else {}
    eligible_count = _int_or_zero(data.get("eligible_candidate_count"))
    blocked_count = _int_or_zero(data.get("blocked_candidate_count"))
    selected_order = _selected_candidate_order_name(data, eligible_count)
    safety_findings = _source_safety_findings(data)
    selected_candidate_risks = _selected_candidate_risks(data, selected_order)
    selected_candidate_safe = _selected_candidate_safe(data, selected_order)
    gate_status = _gate_status(
        eligible_count=eligible_count,
        selected_order=selected_order,
        selected_candidate_safe=selected_candidate_safe,
        selected_candidate_risks=selected_candidate_risks,
        safety_findings=safety_findings,
    )
    known_blockers = _known_blockers_summary(data)
    block_reasons = _block_reasons(
        gate_status=gate_status,
        safety_findings=safety_findings,
        selected_candidate_risks=selected_candidate_risks,
    )
    payload = {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "dry-run-locked-gmail-send-gate",
        "dry_run": True,
        "locked_gmail_send_gate_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "gate_status": gate_status,
        "send_allowed_now": False,
        "draft_create_allowed_now": False,
        "gmail_api_allowed_now": False,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "future_real_send_requires_ack": True,
        "required_ack_for_future_real_send": REQUIRED_ACK_FOR_FUTURE_REAL_SEND,
        "selected_candidate_order_name": selected_order if selected_order else None,
        "selected_candidate_safe_for_future_ack": gate_status == GATE_STATUS_READY_FOR_ACK,
        "eligible_candidate_count": eligible_count,
        "blocked_candidate_count": blocked_count,
        "block_reasons": block_reasons,
        "selected_candidate_risks": selected_candidate_risks,
        "next_admin_action": _next_admin_action(gate_status),
        "current_state_message": _current_state_message(gate_status),
        "future_ack_message": FUTURE_ACK_MESSAGE,
        "known_blockers_summary": known_blockers,
        "order_22620_blocker_status": known_blockers[0],
        "order_22582_blocker_status": known_blockers[1],
        "source_gate_basis": {
            "source_key": _safe_text(primary_source.get("key"), max_length=80),
            "source_relative_path": _safe_text(primary_source.get("relative_path"), max_length=160),
            "source_status": _safe_text(primary_source.get("status"), max_length=120),
        },
        "source_report_status": _source_report_status(sources),
        "no_write_safety_flags": _no_write_safety_flags(),
        "report_paths": {
            "json": str(REPORT_JSON_PATH),
            "html": str(REPORT_HTML_PATH),
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(gate_status, eligible_count, selected_order, known_blockers),
        **_safety_summary(),
    }
    return _safe_payload(payload)


def _gate_status(
    eligible_count: int,
    selected_order: str,
    selected_candidate_safe: bool,
    selected_candidate_risks: list[str],
    safety_findings: list[str],
) -> str:
    if safety_findings:
        return GATE_STATUS_BLOCKED_SAFETY
    if eligible_count == 0:
        return GATE_STATUS_BLOCKED_NO_CANDIDATE
    if eligible_count > 1:
        return GATE_STATUS_BLOCKED_MULTIPLE
    if not selected_order or not selected_candidate_safe or selected_candidate_risks:
        return GATE_STATUS_BLOCKED_SAFETY
    return GATE_STATUS_READY_FOR_ACK


def _selected_candidate_order_name(data: dict, eligible_count: int) -> str:
    if eligible_count != 1:
        return ""
    selected_order = _safe_text(data.get("selected_candidate_order_name"), max_length=80)
    if selected_order:
        return selected_order
    eligible_candidates = data.get("eligible_candidates_summary")
    if isinstance(eligible_candidates, list) and eligible_candidates:
        first = eligible_candidates[0] if isinstance(eligible_candidates[0], dict) else {}
        return _safe_text(first.get("order_name"), max_length=80)
    selected_candidate = data.get("selected_candidate")
    if isinstance(selected_candidate, dict):
        return _safe_text(selected_candidate.get("order_name"), max_length=80)
    return ""


def _selected_candidate_safe(data: dict, selected_order: str) -> bool:
    if not selected_order:
        return False
    if data.get("selected_candidate_safe_to_prepare_send") is True:
        return True
    if data.get("selected_candidate_allowed_for_future_send") is True:
        return True
    if data.get("next_real_step") == "prepare_locked_send_package":
        return True
    if data.get("refresh_status") == "refreshed_locked_send_candidate_ready":
        return True
    if data.get("package_status") == "locked_send_ready_for_human_approval":
        return True
    return False


def _selected_candidate_risks(data: dict, selected_order: str) -> list[str]:
    if not selected_order:
        return []
    risks = []
    for row in _dict_rows(data.get("blocked_candidates_summary")):
        if _safe_text(row.get("order_name"), max_length=80) == selected_order:
            risks.extend(_string_list(row.get("blocking_reasons")))
            risks.extend(_string_list(row.get("reasons")))
            risks.append(_safe_text(row.get("reason"), max_length=120))
    for row in _dict_rows(data.get("blocked_orders_summary")):
        if _safe_text(row.get("order_name"), max_length=80) == selected_order:
            risks.extend(_string_list(row.get("blocking_reasons")))
            risks.append(_safe_text(row.get("blocking_summary"), max_length=300))
    return _dedupe_text(risks)


def _source_safety_findings(data: dict) -> list[str]:
    findings = []
    for key in sorted(FORBIDDEN_SOURCE_TRUE_FLAGS):
        if data.get(key) is True:
            findings.append(f"source_report_flag_true:{key}")
    safety_flags = data.get("safety_flags")
    if isinstance(safety_flags, dict):
        for key in sorted(FORBIDDEN_SOURCE_TRUE_FLAGS):
            if safety_flags.get(key) is True:
                findings.append(f"source_safety_flag_true:{key}")
    no_write_flags = data.get("no_write_safety_flags")
    if isinstance(no_write_flags, dict):
        for key in sorted(FORBIDDEN_SOURCE_TRUE_FLAGS):
            if no_write_flags.get(key) is True:
                findings.append(f"source_no_write_flag_true:{key}")
    return _dedupe_text(findings)


def _block_reasons(
    gate_status: str,
    safety_findings: list[str],
    selected_candidate_risks: list[str],
) -> list[str]:
    if gate_status == GATE_STATUS_BLOCKED_NO_CANDIDATE:
        return ["no_eligible_trustpilot_candidate"]
    if gate_status == GATE_STATUS_BLOCKED_MULTIPLE:
        return ["multiple_eligible_candidates_require_manual_selection"]
    if gate_status == GATE_STATUS_BLOCKED_SAFETY:
        return _dedupe_text([*safety_findings, *selected_candidate_risks, "selected_candidate_safety_check_failed"])
    return []


def _next_admin_action(gate_status: str) -> str:
    if gate_status == GATE_STATUS_READY_FOR_ACK:
        return (
            "Review the single safe candidate. A future real send still requires the locked ACK; "
            "this phase does not call Gmail or send email."
        )
    if gate_status == GATE_STATUS_BLOCKED_MULTIPLE:
        return "Manually select exactly one safe Trustpilot candidate before any future locked Gmail send ACK."
    if gate_status == GATE_STATUS_BLOCKED_SAFETY:
        return "Stop and review the candidate safety failure before any future Gmail send ACK."
    return NEXT_ADMIN_ACTION_NO_CANDIDATE


def _current_state_message(gate_status: str) -> str:
    if gate_status == GATE_STATUS_READY_FOR_ACK:
        return "One safe Trustpilot candidate is present, but no email can be sent in this phase."
    if gate_status == GATE_STATUS_BLOCKED_MULTIPLE:
        return "No email can be sent now. Multiple eligible Trustpilot candidates require manual selection."
    if gate_status == GATE_STATUS_BLOCKED_SAFETY:
        return "No email can be sent now. The selected Trustpilot candidate did not pass the safety gate."
    return CURRENT_NO_CANDIDATE_MESSAGE


def _known_blockers_summary(data: dict) -> list[dict]:
    return [
        _known_blocker(
            data=data,
            order_name="#22620",
            fallback_status="blocked_existing_trustpilot_invitation_customer_level",
            fallback_summary="Already sent to this customer via #22621",
            fallback_message="Do not send. Already sent to this customer via #22621.",
            fallback_reasons=["blocked_existing_trustpilot_invitation_customer_level"],
        ),
        _known_blocker(
            data=data,
            order_name="#22582",
            fallback_status="blocked_candidate_safety_check_failed",
            fallback_summary=(
                f"Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
                "related orders #22582/#22581 not ready"
            ),
            fallback_message=(
                f"Do not send yet. Not delivered, missing `{CANONICAL_REVIEW_REQUEST_TAG}`, "
                "related order group #22582/#22581 not ready."
            ),
            fallback_reasons=[
                "blocked_missing_delivered_tag",
                "blocked_missing_review_request_tag",
                "blocked_merged_order_group_not_ready",
            ],
        ),
    ]


def _known_blocker(
    data: dict,
    order_name: str,
    fallback_status: str,
    fallback_summary: str,
    fallback_message: str,
    fallback_reasons: list[str],
) -> dict:
    source = _known_blocker_source(data, order_name)
    if order_name == "#22620":
        prior_order = _safe_text(source.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
        fallback_summary = f"Already sent to this customer via {prior_order}"
        fallback_message = f"Do not send. Already sent to this customer via {prior_order}."
    source_status = _safe_text(source.get("status"), max_length=120)
    if source_status in {"", "blocked"}:
        source_status = fallback_status
    return {
        "order_name": order_name,
        "status": source_status,
        "blocker": _safe_text(source.get("blocker") or fallback_status, max_length=120),
        "summary": _safe_text(source.get("summary") or fallback_summary, max_length=240),
        "message": _safe_text(source.get("message") or fallback_message, max_length=300),
        "blocking_reasons": _dedupe_text(_string_list(source.get("blocking_reasons")) or fallback_reasons),
        "selected_candidate_safe_for_future_ack": False,
    }


def _known_blocker_source(data: dict, order_name: str) -> dict:
    key = "order_22620_blocker_status" if order_name == "#22620" else "order_22582_blocker_status"
    direct = data.get(key)
    if isinstance(direct, dict):
        return direct
    for row in _dict_rows(data.get("known_blockers_summary")):
        if _safe_text(row.get("order_name"), max_length=80) == order_name:
            return row
    for row in _dict_rows(data.get("blocked_candidates_summary")):
        if _safe_text(row.get("order_name"), max_length=80) == order_name:
            return row
    return {}


def _source_report_status(sources: dict) -> list[dict]:
    return [
        {
            "key": _safe_text(report.get("key"), max_length=80),
            "relative_path": _safe_text(report.get("relative_path"), max_length=160),
            "present": report.get("present") is True,
            "loaded": report.get("loaded") is True,
            "status": _safe_text(report.get("status"), max_length=120),
            "timestamp": _safe_text(report.get("timestamp"), max_length=120),
            "error_sanitized": _safe_text(report.get("error_sanitized"), max_length=300),
        }
        for report in sources.values()
    ]


def _no_write_safety_flags() -> dict:
    return {
        "locked_gmail_send_gate_only": True,
        "source_reports_read_only": True,
        "send_allowed_now": False,
        "draft_create_allowed_now": False,
        "gmail_api_allowed_now": False,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "gmail_api_call_performed": False,
        "gmail_oauth_token_exchange_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_updated": False,
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
        "kudosi_write_api_call_performed": False,
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
    status_class = "ok" if payload["gate_status"] == GATE_STATUS_READY_FOR_ACK else "warn"
    selected_candidate = payload.get("selected_candidate_order_name") or "-"
    block_reasons = ", ".join(payload.get("block_reasons") or []) or "-"
    blocker_rows = "\n".join(_render_blocker_row(row) for row in payload["known_blockers_summary"])
    safety_rows = "\n".join(
        f"<tr><td><code>{escape(key)}</code></td><td>{escape(str(value))}</td></tr>"
        for key, value in payload["no_write_safety_flags"].items()
    )
    source_rows = "\n".join(
        f"<tr><td>{escape(source['key'])}</td><td>{escape(source['relative_path'])}</td>"
        f"<td>{escape(str(source['present']))}</td><td>{escape(str(source['loaded']))}</td>"
        f"<td><code>{escape(source['status'])}</code></td>"
        f"<td>{escape(source.get('timestamp', '') or '-')}</td></tr>"
        for source in payload["source_report_status"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Locked Gmail Send Gate</title>
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
  <h1>Trustpilot Locked Gmail Send Gate</h1>
  <p class="status {status_class}">Gate status: <strong>{escape(payload["gate_status"])}</strong></p>
  <p>{escape(payload["current_state_message"])}</p>
  <p>{escape(payload["future_ack_message"])}</p>
  <p>Mode: <code>dry-run-locked-gmail-send-gate</code>. No Gmail API was called, no Gmail draft was created or updated, no email was sent, no Shopify tag was written, and no Trustpilot/Kudosi/Ali Reviews API was called.</p>
  <table>
    <tbody>
      <tr><th>Send allowed now</th><td>No</td></tr>
      <tr><th>Draft create allowed now</th><td>No</td></tr>
      <tr><th>Gmail API allowed now</th><td>No</td></tr>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Blocked candidate count</th><td>{payload["blocked_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(selected_candidate)}</td></tr>
      <tr><th>Block reasons</th><td>{escape(block_reasons)}</td></tr>
      <tr><th>Required future ACK</th><td><code>{escape(payload["required_ack_for_future_real_send"])}</code></td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
    </tbody>
  </table>
  <h2>Known Blockers</h2>
  <table><thead><tr><th>Order</th><th>Status</th><th>Summary</th><th>Message</th></tr></thead><tbody>{blocker_rows}</tbody></table>
  <h2>No-Write Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <details>
    <summary>Advanced source report details</summary>
    <p>JSON report: <code>{escape(str(REPORT_JSON_PATH))}</code></p>
    <p>HTML report: <code>{escape(str(REPORT_HTML_PATH))}</code></p>
    <p>Source basis: <code>{escape(payload["source_gate_basis"]["source_key"] or "none")}</code></p>
    <table><thead><tr><th>Key</th><th>Path</th><th>Present</th><th>Loaded</th><th>Status</th><th>Timestamp</th></tr></thead><tbody>{source_rows}</tbody></table>
  </details>
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
        "json_trustpilot_locked_gmail_send_gate_path": str(json_path),
        "html_trustpilot_locked_gmail_send_gate_path": str(html_path),
        "gate_status": payload["gate_status"],
        "send_allowed_now": False,
        "draft_create_allowed_now": False,
        "gmail_api_allowed_now": False,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "future_real_send_requires_ack": payload["future_real_send_requires_ack"],
        "required_ack_for_future_real_send": payload["required_ack_for_future_real_send"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "blocked_candidate_count": payload["blocked_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "block_reasons": payload["block_reasons"],
        "next_admin_action": payload["next_admin_action"],
        "order_22620_blocker_status": payload["order_22620_blocker_status"]["status"],
        "order_22582_blocker_status": payload["order_22582_blocker_status"]["status"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    selected = payload["selected_candidate_order_name"] or "None"
    return (
        "Shopify review request Phase 5.10 Trustpilot locked Gmail send gate finished.\n"
        f"Gate status: {payload['gate_status']}\n"
        f"Send allowed now: {payload['send_allowed_now']}\n"
        f"Draft create allowed now: {payload['draft_create_allowed_now']}\n"
        f"Gmail API allowed now: {payload['gmail_api_allowed_now']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Selected candidate: {selected}\n"
        f"Required future ACK: {payload['required_ack_for_future_real_send']}\n"
        "Safety: no Gmail API, no draft creation/update/delete, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(gate_status: str, eligible_count: int, selected_order: str, known_blockers: list[dict]) -> str:
    if gate_status == GATE_STATUS_READY_FOR_ACK:
        return (
            f"Exactly one Trustpilot candidate ({selected_order}) is ready for a future locked ACK; "
            "this phase still sent no email and called no Gmail API."
        )
    if gate_status == GATE_STATUS_BLOCKED_MULTIPLE:
        return f"{eligible_count} Trustpilot candidates are eligible; manual selection is required before any Gmail send gate can proceed."
    if gate_status == GATE_STATUS_BLOCKED_SAFETY:
        return "Trustpilot Gmail send gate is blocked by candidate or source safety checks."
    return (
        "No eligible Trustpilot candidate. "
        f"#22620 remains blocked: {known_blockers[0]['summary']}. "
        f"#22582 remains blocked: {known_blockers[1]['summary']}."
    )


def _report_status(data: dict) -> str:
    return _first_text(
        data,
        (
            "gate_status",
            "refresh_status",
            "package_status",
            "automation_status",
            "history_ledger_audit_status",
            "report_status",
            "status",
        ),
    ) or "loaded"


def _first_text(mapping: dict, keys: tuple[str, ...]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _safe_text(value, max_length=300)
    return ""


def _int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dict_rows(value) -> list[dict]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _dedupe_text(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = _safe_text(value, max_length=300)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
