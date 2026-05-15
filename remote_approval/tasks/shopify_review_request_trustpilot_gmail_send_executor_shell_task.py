import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_trustpilot_automation_dry_run_task import (
    _safe_payload,
    _safe_text,
    _safety_summary,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_send_executor_shell"
COMMAND_LABEL = TASK_NAME
PHASE = "5.11"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_executor_shell.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_executor_shell.html"

GATE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate.json"
GATE_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate.html"

REQUIRED_ACK_ENV_VAR = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK"
REQUIRED_ACK_VALUE = "YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND"
REQUIRED_ACK = f"{REQUIRED_ACK_ENV_VAR}={REQUIRED_ACK_VALUE}"

GATE_STATUS_READY_FOR_ACK = "locked_send_gate_ready_for_ack"
GATE_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"

EXECUTOR_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
EXECUTOR_STATUS_BLOCKED_MISSING_ACK = "blocked_missing_ack"
EXECUTOR_STATUS_BLOCKED_GATE_NOT_READY = "blocked_gate_not_ready"
EXECUTOR_STATUS_READY_FOR_FUTURE_REAL_SEND = "ready_for_future_real_send_execute"

NEXT_ADMIN_ACTION_NO_CANDIDATE = (
    "Wait until exactly one eligible delivered order with canonical `1: review request` "
    "passes all duplicate/risk checks and gate is ready."
)
NO_CANDIDATE_MESSAGE = (
    "Send executor is installed but locked. No email can be sent because there is no eligible candidate."
)
FUTURE_SEND_MESSAGE = "Future real sending will require exactly one safe candidate and the locked ACK."


def run_shopify_review_request_trustpilot_gmail_send_executor_shell_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    gate_report = _load_gate_report()
    payload = _build_payload(
        gate_report=gate_report,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_gate_report() -> dict:
    report = {
        "key": "trustpilot_locked_gmail_send_gate",
        "relative_path": f"logs/{GATE_JSON_PATH.name}",
        "html_relative_path": f"logs/{GATE_HTML_PATH.name}",
        "present": GATE_JSON_PATH.exists(),
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "error_sanitized": "",
        "data": {},
    }
    if not GATE_JSON_PATH.exists():
        return report
    try:
        data = json.loads(GATE_JSON_PATH.read_text(encoding="utf-8", errors="replace"), strict=False)
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
    report["status"] = _first_text(data, ("gate_status", "report_status", "status")) or "loaded"
    report["timestamp"] = _first_text(
        data,
        ("report_generated_at", "timestamp", "generated_at", "created_at", "finished_at"),
    )
    return report


def _build_payload(gate_report: dict, duration_seconds: float) -> dict:
    data = gate_report.get("data") if gate_report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    gate_status = _safe_text(data.get("gate_status") or gate_report.get("status") or "missing", max_length=120)
    eligible_count = _int_or_zero(data.get("eligible_candidate_count"))
    selected_order = _safe_text(data.get("selected_candidate_order_name"), max_length=80)
    ack_present = os.environ.get(REQUIRED_ACK_ENV_VAR) == REQUIRED_ACK_VALUE
    ack_variable_present = REQUIRED_ACK_ENV_VAR in os.environ
    executor_status = _executor_status(
        gate_status=gate_status,
        eligible_count=eligible_count,
        selected_order=selected_order,
        ack_present=ack_present,
    )
    future_allowed = executor_status == EXECUTOR_STATUS_READY_FOR_FUTURE_REAL_SEND
    known_blockers = _known_blockers_summary(data)
    blocking_conditions = _blocking_conditions(
        executor_status=executor_status,
        gate_status=gate_status,
        eligible_count=eligible_count,
        selected_order=selected_order,
        ack_present=ack_present,
    )
    generated_at = utc_now_iso()
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "no-send-executor-shell",
        "dry_run": True,
        "no_send_executor_shell_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "executor_status": executor_status,
        "gate_status": gate_status,
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order if selected_order else None,
        "ack_present": ack_present,
        "ack_variable_present": ack_variable_present,
        "required_ack": REQUIRED_ACK,
        "required_ack_env_var": REQUIRED_ACK_ENV_VAR,
        "future_real_send_allowed_if_implemented": future_allowed,
        "next_admin_action": _next_admin_action(executor_status),
        "current_state_message": _current_state_message(executor_status),
        "future_send_message": FUTURE_SEND_MESSAGE,
        "blocking_conditions": blocking_conditions,
        "known_blockers_summary": known_blockers,
        "order_22620_blocker_status": known_blockers[0],
        "order_22582_blocker_status": known_blockers[1],
        "source_gate_report": _source_gate_report_summary(gate_report),
        "report_paths": {
            "json": str(REPORT_JSON_PATH),
            "html": str(REPORT_HTML_PATH),
            "source_gate_json": str(GATE_JSON_PATH),
            "source_gate_html": str(GATE_HTML_PATH),
        },
        "safety_flags": _safety_flags(),
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(
            executor_status=executor_status,
            gate_status=gate_status,
            eligible_count=eligible_count,
            selected_order=selected_order,
            ack_present=ack_present,
            known_blockers=known_blockers,
        ),
        **_safety_summary(),
        "gmail_draft_create_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
    }
    return _safe_payload(payload)


def _executor_status(gate_status: str, eligible_count: int, selected_order: str, ack_present: bool) -> str:
    if gate_status == GATE_STATUS_BLOCKED_NO_CANDIDATE:
        return EXECUTOR_STATUS_BLOCKED_NO_CANDIDATE
    if gate_status != GATE_STATUS_READY_FOR_ACK or eligible_count != 1 or not selected_order:
        return EXECUTOR_STATUS_BLOCKED_GATE_NOT_READY
    if not ack_present:
        return EXECUTOR_STATUS_BLOCKED_MISSING_ACK
    return EXECUTOR_STATUS_READY_FOR_FUTURE_REAL_SEND


def _blocking_conditions(
    executor_status: str,
    gate_status: str,
    eligible_count: int,
    selected_order: str,
    ack_present: bool,
) -> list[dict]:
    if executor_status == EXECUTOR_STATUS_READY_FOR_FUTURE_REAL_SEND:
        return []
    if executor_status == EXECUTOR_STATUS_BLOCKED_NO_CANDIDATE:
        return [
            {
                "status": EXECUTOR_STATUS_BLOCKED_NO_CANDIDATE,
                "detail": "The locked Gmail send gate has zero eligible Trustpilot candidates.",
            }
        ]
    if executor_status == EXECUTOR_STATUS_BLOCKED_MISSING_ACK:
        return [
            {
                "status": EXECUTOR_STATUS_BLOCKED_MISSING_ACK,
                "detail": "Exactly one candidate is gate-ready, but the required locked ACK is absent.",
            }
        ]
    conditions = [
        {
            "status": EXECUTOR_STATUS_BLOCKED_GATE_NOT_READY,
            "detail": f"Gate status is `{gate_status or 'missing'}`, not `{GATE_STATUS_READY_FOR_ACK}`.",
        }
    ]
    if eligible_count != 1:
        conditions.append(
            {
                "status": "blocked_candidate_count_not_exactly_one",
                "detail": f"Eligible candidate count is {eligible_count}, not 1.",
            }
        )
    if not selected_order:
        conditions.append(
            {
                "status": "blocked_missing_selected_candidate",
                "detail": "No selected candidate order name is available from the gate report.",
            }
        )
    if not ack_present:
        conditions.append(
            {
                "status": EXECUTOR_STATUS_BLOCKED_MISSING_ACK,
                "detail": "Required locked ACK is absent.",
            }
        )
    return conditions


def _next_admin_action(executor_status: str) -> str:
    if executor_status == EXECUTOR_STATUS_READY_FOR_FUTURE_REAL_SEND:
        return (
            "This no-send shell is ready for a future separately implemented real-send task. "
            "This phase still calls no Gmail API and sends no email."
        )
    if executor_status == EXECUTOR_STATUS_BLOCKED_MISSING_ACK:
        return (
            "Review the single gate-ready candidate and provide the locked ACK only in a future "
            "explicit real-send phase."
        )
    if executor_status == EXECUTOR_STATUS_BLOCKED_GATE_NOT_READY:
        return "Refresh and review the locked Gmail send gate until exactly one safe candidate is ready."
    return NEXT_ADMIN_ACTION_NO_CANDIDATE


def _current_state_message(executor_status: str) -> str:
    if executor_status == EXECUTOR_STATUS_READY_FOR_FUTURE_REAL_SEND:
        return "Send executor shell is ready for a future real-send implementation, but this phase sends nothing."
    if executor_status == EXECUTOR_STATUS_BLOCKED_MISSING_ACK:
        return "Send executor is installed but locked. The required ACK is missing."
    if executor_status == EXECUTOR_STATUS_BLOCKED_GATE_NOT_READY:
        return "Send executor is installed but locked. The locked Gmail send gate is not ready."
    return NO_CANDIDATE_MESSAGE


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
                "Not delivered, missing `1: review request`, related orders #22582/#22581 not ready"
            ),
            fallback_message=(
                "Do not send yet. Not delivered, missing `1: review request`, "
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
    source_status = _safe_text(source.get("status"), max_length=120)
    if source_status in {"", "blocked"}:
        source_status = fallback_status
    if order_name == "#22620":
        prior_order = _safe_text(source.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
        fallback_summary = f"Already sent to this customer via {prior_order}"
        fallback_message = f"Do not send. Already sent to this customer via {prior_order}."
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
    return {}


def _source_gate_report_summary(gate_report: dict) -> dict:
    return {
        "relative_path": _safe_text(gate_report.get("relative_path"), max_length=160),
        "html_relative_path": _safe_text(gate_report.get("html_relative_path"), max_length=160),
        "present": gate_report.get("present") is True,
        "loaded": gate_report.get("loaded") is True,
        "status": _safe_text(gate_report.get("status"), max_length=120),
        "timestamp": _safe_text(gate_report.get("timestamp"), max_length=120),
        "error_sanitized": _safe_text(gate_report.get("error_sanitized"), max_length=300),
    }


def _safety_flags() -> dict:
    return {
        "no_send_executor_shell_only": True,
        "source_gate_report_read_only": True,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_updated": False,
        "gmail_draft_deleted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "mutation_performed": False,
        "external_review_api_call_performed": False,
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
    status_class = "ok" if payload["executor_status"] == EXECUTOR_STATUS_READY_FOR_FUTURE_REAL_SEND else "warn"
    selected_candidate = payload.get("selected_candidate_order_name") or "-"
    blocking_rows = "\n".join(_render_condition_row(row) for row in payload["blocking_conditions"])
    if not blocking_rows:
        blocking_rows = '<tr><td colspan="2">No blocking conditions for future implementation.</td></tr>'
    blocker_rows = "\n".join(_render_blocker_row(row) for row in payload["known_blockers_summary"])
    safety_rows = "\n".join(
        f"<tr><td><code>{escape(key)}</code></td><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_flags"].items()
    )
    ack_label = "Yes" if payload.get("ack_present") else "No"
    future_allowed_label = "Yes" if payload.get("future_real_send_allowed_if_implemented") else "No"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Send Executor Shell</title>
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
  <h1>Trustpilot Gmail Send Executor Shell</h1>
  <p class="status {status_class}">Executor status: <strong>{escape(payload["executor_status"])}</strong></p>
  <p>{escape(payload["current_state_message"])}</p>
  <p>{escape(payload["future_send_message"])}</p>
  <p>Mode: <code>no-send-executor-shell</code>. No Gmail API was called, no Gmail draft was created or updated, no email was sent, no Shopify tag was written, and no Trustpilot/Kudosi/Ali Reviews API was called.</p>
  <table>
    <tbody>
      <tr><th>Gate status</th><td><code>{escape(payload["gate_status"])}</code></td></tr>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(selected_candidate)}</td></tr>
      <tr><th>ACK present</th><td>{ack_label}</td></tr>
      <tr><th>Required ACK</th><td><code>{escape(payload["required_ack"])}</code></td></tr>
      <tr><th>Future real send allowed if implemented</th><td>{future_allowed_label}</td></tr>
      <tr><th>Gmail send performed</th><td>No</td></tr>
      <tr><th>Gmail draft create performed</th><td>No</td></tr>
      <tr><th>Shopify tag write performed</th><td>No</td></tr>
      <tr><th>External review API call performed</th><td>No</td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
    </tbody>
  </table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Known Blockers</h2>
  <table><thead><tr><th>Order</th><th>Status</th><th>Summary</th><th>Message</th></tr></thead><tbody>{blocker_rows}</tbody></table>
  <h2>No-Send Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <details>
    <summary>Advanced source report details</summary>
    <p>JSON report: <code>{escape(str(REPORT_JSON_PATH))}</code></p>
    <p>HTML report: <code>{escape(str(REPORT_HTML_PATH))}</code></p>
    <p>Source gate JSON: <code>{escape(payload["source_gate_report"]["relative_path"])}</code></p>
    <p>Source gate loaded: <strong>{escape(str(payload["source_gate_report"]["loaded"]))}</strong></p>
    <p>Source gate error: {escape(payload["source_gate_report"].get("error_sanitized") or "-")}</p>
  </details>
</body>
</html>"""


def _render_condition_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td><code>{escape(row.get('status', ''))}</code></td>"
        f"<td>{escape(row.get('detail', ''))}</td>"
        "</tr>"
    )


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
        "json_trustpilot_gmail_send_executor_shell_path": str(json_path),
        "html_trustpilot_gmail_send_executor_shell_path": str(html_path),
        "executor_status": payload["executor_status"],
        "gate_status": payload["gate_status"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "ack_present": payload["ack_present"],
        "required_ack": payload["required_ack"],
        "future_real_send_allowed_if_implemented": payload["future_real_send_allowed_if_implemented"],
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "next_admin_action": payload["next_admin_action"],
        "blocking_conditions": payload["blocking_conditions"],
        "order_22620_blocker_status": payload["order_22620_blocker_status"]["status"],
        "order_22582_blocker_status": payload["order_22582_blocker_status"]["status"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    selected = payload["selected_candidate_order_name"] or "None"
    return (
        "Shopify review request Phase 5.11 Trustpilot Gmail send executor shell finished.\n"
        f"Executor status: {payload['executor_status']}\n"
        f"Gate status: {payload['gate_status']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Selected candidate: {selected}\n"
        f"ACK present: {payload['ack_present']}\n"
        f"Future real send allowed if implemented: {payload['future_real_send_allowed_if_implemented']}\n"
        "Safety: no Gmail API, no draft creation/update/delete, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(
    executor_status: str,
    gate_status: str,
    eligible_count: int,
    selected_order: str,
    ack_present: bool,
    known_blockers: list[dict],
) -> str:
    if executor_status == EXECUTOR_STATUS_READY_FOR_FUTURE_REAL_SEND:
        return (
            f"Exactly one Trustpilot candidate ({selected_order}) is ready and the locked ACK is present; "
            "this shell still sent no email and called no Gmail API."
        )
    if executor_status == EXECUTOR_STATUS_BLOCKED_MISSING_ACK:
        return (
            f"Exactly one Trustpilot candidate ({selected_order}) is gate-ready, but the locked ACK is missing; "
            "this shell sent no email."
        )
    if executor_status == EXECUTOR_STATUS_BLOCKED_GATE_NOT_READY:
        return (
            f"Trustpilot Gmail send executor is blocked because gate_status={gate_status}, "
            f"eligible_candidate_count={eligible_count}, ack_present={ack_present}."
        )
    return (
        "No eligible Trustpilot candidate. "
        f"#22620 remains blocked: {known_blockers[0]['summary']}. "
        f"#22582 remains blocked: {known_blockers[1]['summary']}."
    )


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


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        return [_safe_text(value)] if _safe_text(value) else []
    if isinstance(value, (list, tuple, set)):
        return _dedupe_text(
            _safe_text(item.get("status") or item.get("reason") or item.get("detail"))
            if isinstance(item, dict)
            else _safe_text(item)
            for item in value
        )
    return []


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
