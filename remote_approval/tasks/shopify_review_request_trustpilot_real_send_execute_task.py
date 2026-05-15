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


TASK_NAME = "shopify_review_request_trustpilot_real_send_execute"
COMMAND_LABEL = TASK_NAME
PHASE = "5.14"

SOURCE_PREFLIGHT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_real_send_final_preflight.json"
SOURCE_PREFLIGHT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_real_send_final_preflight.html"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_real_send_execute.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_real_send_execute.html"

SIMULATOR_EXECUTE_ENV_VAR = "SHOPIFY_REVIEW_REQUEST_REAL_SEND_EXECUTE_USE_SIMULATOR"
SIMULATOR_EXECUTE_ACK = "YES_I_UNDERSTAND_THIS_IS_FAKE_DATA"

EXECUTE_ENV_VAR = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_REAL_SEND_EXECUTE"
EXECUTE_ENV_VALUE = "YES_I_APPROVE_REAL_TRUSTPILOT_GMAIL_SEND"
REQUIRED_EXECUTE_FLAG = f"{EXECUTE_ENV_VAR}={EXECUTE_ENV_VALUE}"

DEFAULT_REQUIRED_ACK = (
    "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_GMAIL_SEND_ACK="
    "YES_I_APPROVE_ONE_TRUSTPILOT_GMAIL_SEND"
)

PREFLIGHT_STATUS_READY = "ready_for_real_send_execute_next_phase"
PREFLIGHT_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"

EXECUTION_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
EXECUTION_STATUS_BLOCKED_MISSING_FLAG = "blocked_missing_real_send_execute_flag"
EXECUTION_STATUS_READY_BUT_DISABLED = "ready_but_real_send_implementation_not_enabled_in_this_phase"
EXECUTION_STATUS_BLOCKED_PREFLIGHT_NOT_READY = "blocked_final_preflight_not_ready"
EXECUTION_STATUS_BLOCKED_PREFLIGHT_INCONSISTENT = "blocked_final_preflight_inconsistent"

NEXT_ADMIN_ACTION_NO_CANDIDATE = (
    "Wait until final preflight reports exactly one real eligible candidate and "
    "`ready_for_real_send_execute_next_phase`."
)


def run_shopify_review_request_trustpilot_real_send_execute_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    simulator_allowed = _simulator_allowed()
    preflight_report = _load_preflight_report(simulator_allowed=simulator_allowed)
    payload = _build_payload(
        preflight_report=preflight_report,
        simulator_allowed=simulator_allowed,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _simulator_allowed() -> bool:
    return os.environ.get(SIMULATOR_EXECUTE_ENV_VAR) == SIMULATOR_EXECUTE_ACK


def _execute_env_var_present() -> bool:
    return EXECUTE_ENV_VAR in os.environ


def _execute_flag_present() -> bool:
    return os.environ.get(EXECUTE_ENV_VAR) == EXECUTE_ENV_VALUE


def _load_preflight_report(simulator_allowed: bool) -> dict:
    report = {
        "key": "trustpilot_real_send_final_preflight",
        "relative_path": f"logs/{SOURCE_PREFLIGHT_JSON_PATH.name}",
        "html_relative_path": f"logs/{SOURCE_PREFLIGHT_HTML_PATH.name}",
        "present": SOURCE_PREFLIGHT_JSON_PATH.exists(),
        "loaded": False,
        "usable": False,
        "simulator_report": False,
        "ignored_by_default": False,
        "status": "missing",
        "timestamp": "",
        "error_sanitized": "",
        "data": {},
    }
    if not SOURCE_PREFLIGHT_JSON_PATH.exists():
        return report
    try:
        data = json.loads(SOURCE_PREFLIGHT_JSON_PATH.read_text(encoding="utf-8", errors="replace"), strict=False)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error_sanitized"] = _safe_text(str(exc), max_length=300)
        return report
    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error_sanitized"] = "top_level_json_is_not_object"
        return report

    simulator_report = _is_simulator_preflight(data)
    ignored_by_default = simulator_report and not simulator_allowed
    report.update(
        {
            "loaded": True,
            "usable": not ignored_by_default,
            "simulator_report": simulator_report,
            "ignored_by_default": ignored_by_default,
            "status": "ignored_simulator_preflight_by_default"
            if ignored_by_default
            else _preflight_status_from_data(data),
            "timestamp": _first_text(
                data,
                ("report_generated_at", "timestamp", "generated_at", "created_at", "finished_at"),
            ),
            "data": {} if ignored_by_default else data,
        }
    )
    return report


def _is_simulator_preflight(data: dict) -> bool:
    return (
        data.get("simulator_reports_used") is True
        or data.get("simulator_fixture_enabled") is True
        or data.get("simulator_only") is True
        or data.get("source") == "trustpilot_candidate_simulator"
        or bool(data.get("fake_candidate_summary"))
    )


def _build_payload(preflight_report: dict, simulator_allowed: bool, duration_seconds: float) -> dict:
    data = preflight_report.get("data") if preflight_report.get("usable") else {}
    data = data if isinstance(data, dict) else {}
    simulator_used = _simulator_used(preflight_report, simulator_allowed)
    production_preflight_used = not simulator_used
    preflight_status = _preflight_status_from_data(data) if data else PREFLIGHT_STATUS_BLOCKED_NO_CANDIDATE
    eligible_count = _int_or_zero(data.get("eligible_candidate_count"))
    selected_order = _safe_text(data.get("selected_candidate_order_name"), max_length=80)
    ack_present = data.get("ack_present") is True
    required_ack = _safe_text(data.get("required_ack") or DEFAULT_REQUIRED_ACK, max_length=180)
    real_send_allowed_by_preflight = _real_send_allowed_by_preflight(
        preflight_status=preflight_status,
        eligible_count=eligible_count,
        selected_order=selected_order,
        ack_present=ack_present,
        source_allowed=data.get("real_send_execute_allowed_next_phase") is True,
    )
    real_send_execute_requested = _execute_env_var_present()
    real_send_execute_allowed_by_env = _execute_flag_present()
    execution_status = _execution_status(
        preflight_status=preflight_status,
        eligible_count=eligible_count,
        selected_order=selected_order,
        ack_present=ack_present,
        real_send_allowed_by_preflight=real_send_allowed_by_preflight,
        real_send_execute_allowed_by_env=real_send_execute_allowed_by_env,
    )
    blocking_conditions = _blocking_conditions(
        execution_status=execution_status,
        preflight_status=preflight_status,
        eligible_count=eligible_count,
        selected_order=selected_order,
        ack_present=ack_present,
        real_send_execute_requested=real_send_execute_requested,
        real_send_execute_allowed_by_env=real_send_execute_allowed_by_env,
        preflight_report=preflight_report,
    )
    generated_at = utc_now_iso()
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "real-send-execute-skeleton",
        "dry_run": True,
        "execute_skeleton_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "execution_status": execution_status,
        "production_preflight_used": production_preflight_used,
        "simulator_used": simulator_used,
        "simulator_execute_fixture_enabled": simulator_allowed,
        "preflight_status": preflight_status,
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order if selected_order else None,
        "ack_present": ack_present,
        "required_ack": required_ack,
        "required_execute_flag": REQUIRED_EXECUTE_FLAG,
        "real_send_execute_requested": real_send_execute_requested,
        "real_send_execute_allowed_by_preflight": real_send_allowed_by_preflight,
        "real_send_execute_allowed_by_env": real_send_execute_allowed_by_env,
        "gmail_send_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "blocking_conditions": blocking_conditions,
        "next_admin_action": _next_admin_action(execution_status),
        "current_state_message": _current_state_message(execution_status),
        "future_send_message": (
            "Even when future conditions are ready, real sending requires an explicit execute flag "
            "and a separate implementation step."
        ),
        "source_preflight_report": _source_preflight_summary(preflight_report),
        "safety_flags": _safety_flags(),
        "report_paths": {
            "json": str(REPORT_JSON_PATH),
            "html": str(REPORT_HTML_PATH),
            "source_preflight_json": str(SOURCE_PREFLIGHT_JSON_PATH),
            "source_preflight_html": str(SOURCE_PREFLIGHT_HTML_PATH),
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(
            execution_status=execution_status,
            preflight_status=preflight_status,
            eligible_count=eligible_count,
            selected_order=selected_order,
            simulator_used=simulator_used,
        ),
        **_safety_summary(),
        "gmail_draft_create_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
    }
    return _safe_payload(payload)


def _simulator_used(preflight_report: dict, simulator_allowed: bool) -> bool:
    return (
        simulator_allowed
        and preflight_report.get("usable") is True
        and preflight_report.get("simulator_report") is True
    )


def _real_send_allowed_by_preflight(
    preflight_status: str,
    eligible_count: int,
    selected_order: str,
    ack_present: bool,
    source_allowed: bool,
) -> bool:
    return (
        source_allowed
        and preflight_status == PREFLIGHT_STATUS_READY
        and eligible_count == 1
        and bool(selected_order)
        and ack_present
    )


def _execution_status(
    preflight_status: str,
    eligible_count: int,
    selected_order: str,
    ack_present: bool,
    real_send_allowed_by_preflight: bool,
    real_send_execute_allowed_by_env: bool,
) -> str:
    if not real_send_allowed_by_preflight:
        if preflight_status == PREFLIGHT_STATUS_BLOCKED_NO_CANDIDATE or eligible_count == 0:
            return EXECUTION_STATUS_BLOCKED_NO_CANDIDATE
        if preflight_status == PREFLIGHT_STATUS_READY and (eligible_count != 1 or not selected_order or not ack_present):
            return EXECUTION_STATUS_BLOCKED_PREFLIGHT_INCONSISTENT
        return preflight_status or EXECUTION_STATUS_BLOCKED_PREFLIGHT_NOT_READY
    if not real_send_execute_allowed_by_env:
        return EXECUTION_STATUS_BLOCKED_MISSING_FLAG
    return EXECUTION_STATUS_READY_BUT_DISABLED


def _blocking_conditions(
    execution_status: str,
    preflight_status: str,
    eligible_count: int,
    selected_order: str,
    ack_present: bool,
    real_send_execute_requested: bool,
    real_send_execute_allowed_by_env: bool,
    preflight_report: dict,
) -> list[dict]:
    conditions = []
    if preflight_report.get("ignored_by_default") is True:
        conditions.append(
            {
                "status": "ignored_simulator_preflight_by_default",
                "detail": (
                    "The final preflight report appears to be simulator data and was ignored because "
                    f"{SIMULATOR_EXECUTE_ENV_VAR} was not explicitly enabled."
                ),
            }
        )
    if execution_status == EXECUTION_STATUS_READY_BUT_DISABLED:
        return [
            *conditions,
            {
                "status": EXECUTION_STATUS_READY_BUT_DISABLED,
                "detail": (
                    "The explicit execute flag is present, but Phase 5.14 is a locked skeleton. "
                    "No real Gmail send implementation is enabled in this phase."
                ),
            },
        ]
    if execution_status == EXECUTION_STATUS_BLOCKED_MISSING_FLAG:
        return [
            *conditions,
            {
                "status": EXECUTION_STATUS_BLOCKED_MISSING_FLAG,
                "detail": f"Set {EXECUTE_ENV_VAR} only in a future approved real-send implementation phase.",
            },
        ]
    if execution_status == EXECUTION_STATUS_BLOCKED_NO_CANDIDATE:
        return [
            *conditions,
            {
                "status": EXECUTION_STATUS_BLOCKED_NO_CANDIDATE,
                "detail": "Final preflight has no eligible Trustpilot candidate for real send execute.",
            },
        ]
    details = [
        {
            "status": execution_status or EXECUTION_STATUS_BLOCKED_PREFLIGHT_NOT_READY,
            "detail": f"Final preflight status is `{preflight_status or 'missing'}`, not `{PREFLIGHT_STATUS_READY}`.",
        }
    ]
    if eligible_count != 1:
        details.append(
            {
                "status": "blocked_candidate_count_not_exactly_one",
                "detail": f"Eligible candidate count is {eligible_count}, not 1.",
            }
        )
    if not selected_order:
        details.append(
            {
                "status": "blocked_missing_selected_candidate",
                "detail": "No selected candidate order name is available from final preflight.",
            }
        )
    if not ack_present:
        details.append(
            {
                "status": "blocked_missing_ack",
                "detail": "Final preflight has not confirmed the required ACK.",
            }
        )
    if real_send_execute_requested and not real_send_execute_allowed_by_env:
        details.append(
            {
                "status": "blocked_invalid_execute_flag",
                "detail": f"{EXECUTE_ENV_VAR} is present but does not match the required locked value.",
            }
        )
    return [*conditions, *details]


def _next_admin_action(execution_status: str) -> str:
    if execution_status == EXECUTION_STATUS_READY_BUT_DISABLED:
        return (
            "Do not send from this phase. Build and review a separate real-send implementation step "
            "before any Gmail API call can be enabled."
        )
    if execution_status == EXECUTION_STATUS_BLOCKED_MISSING_FLAG:
        return (
            f"Final preflight is ready. A future approved implementation would require {REQUIRED_EXECUTE_FLAG} "
            "before any real send path is considered."
        )
    return NEXT_ADMIN_ACTION_NO_CANDIDATE


def _current_state_message(execution_status: str) -> str:
    if execution_status == EXECUTION_STATUS_READY_BUT_DISABLED:
        return (
            "Real send execute reached the locked skeleton ready state, but this phase cannot send email."
        )
    if execution_status == EXECUTION_STATUS_BLOCKED_MISSING_FLAG:
        return "Real send execute is installed but locked because the explicit execute flag is missing."
    return "Real send execute is installed but locked. No email can be sent because final preflight is blocked."


def _source_preflight_summary(preflight_report: dict) -> dict:
    return {
        "relative_path": _safe_text(preflight_report.get("relative_path"), max_length=160),
        "html_relative_path": _safe_text(preflight_report.get("html_relative_path"), max_length=160),
        "present": preflight_report.get("present") is True,
        "loaded": preflight_report.get("loaded") is True,
        "usable": preflight_report.get("usable") is True,
        "simulator_report": preflight_report.get("simulator_report") is True,
        "ignored_by_default": preflight_report.get("ignored_by_default") is True,
        "status": _safe_text(preflight_report.get("status"), max_length=120),
        "timestamp": _safe_text(preflight_report.get("timestamp"), max_length=120),
        "error_sanitized": _safe_text(preflight_report.get("error_sanitized"), max_length=300),
    }


def _safety_flags() -> dict:
    return {
        "real_send_execute_skeleton_only": True,
        "source_preflight_report_read_only": True,
        "real_send_implementation_enabled": False,
        "gmail_api_call_performed": False,
        "gmail_oauth_token_exchange_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_created": False,
        "gmail_draft_updated": False,
        "gmail_draft_deleted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "external_review_api_call_performed": False,
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
        json.dump(_safe_payload(payload), report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status_class = "ok" if payload["execution_status"] == EXECUTION_STATUS_READY_BUT_DISABLED else "warn"
    selected_candidate = payload.get("selected_candidate_order_name") or "-"
    blocking_rows = "\n".join(_render_condition_row(row) for row in payload["blocking_conditions"])
    if not blocking_rows:
        blocking_rows = '<tr><td colspan="2">No blocking conditions recorded.</td></tr>'
    safety_rows = "\n".join(
        f"<tr><td><code>{escape(key)}</code></td><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_flags"].items()
    )
    source = payload["source_preflight_report"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Real Send Execute Skeleton</title>
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
  <h1>Trustpilot Real Send Execute Skeleton</h1>
  <p class="status {status_class}">Execution status: <strong>{escape(payload["execution_status"])}</strong></p>
  <p>{escape(payload["current_state_message"])}</p>
  <p>{escape(payload["future_send_message"])}</p>
  <p>Mode: <code>real-send-execute-skeleton</code>. No Gmail API was called, no Gmail draft was created, updated, deleted, or sent, no email was sent, no Shopify tag was written, and no Trustpilot/Kudosi/Ali Reviews API was called.</p>
  <table>
    <tbody>
      <tr><th>Preflight status</th><td><code>{escape(payload["preflight_status"])}</code></td></tr>
      <tr><th>Production preflight used</th><td>{escape(_yes_no(payload["production_preflight_used"]))}</td></tr>
      <tr><th>Simulator used</th><td>{escape(_yes_no(payload["simulator_used"]))}</td></tr>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(selected_candidate)}</td></tr>
      <tr><th>ACK present</th><td>{escape(_yes_no(payload["ack_present"]))}</td></tr>
      <tr><th>Real send execute requested</th><td>{escape(_yes_no(payload["real_send_execute_requested"]))}</td></tr>
      <tr><th>Allowed by preflight</th><td>{escape(_yes_no(payload["real_send_execute_allowed_by_preflight"]))}</td></tr>
      <tr><th>Allowed by env</th><td>{escape(_yes_no(payload["real_send_execute_allowed_by_env"]))}</td></tr>
      <tr><th>Gmail send performed</th><td>No</td></tr>
      <tr><th>Gmail draft create performed</th><td>No</td></tr>
      <tr><th>Shopify tag write performed</th><td>No</td></tr>
      <tr><th>External review API call performed</th><td>No</td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
    </tbody>
  </table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>No-Write Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <details>
    <summary>Advanced debug details</summary>
    <p>JSON report: <code>{escape(str(REPORT_JSON_PATH))}</code></p>
    <p>HTML report: <code>{escape(str(REPORT_HTML_PATH))}</code></p>
    <p>Required ACK: <code>{escape(payload["required_ack"])}</code></p>
    <p>Required execute flag: <code>{escape(payload["required_execute_flag"])}</code></p>
    <p>Source final preflight JSON: <code>{escape(source["relative_path"])}</code></p>
    <p>Source final preflight status: <code>{escape(source["status"])}</code></p>
    <p>Source loaded: <strong>{escape(str(source["loaded"]))}</strong> | Usable: <strong>{escape(str(source["usable"]))}</strong> | Simulator: <strong>{escape(str(source["simulator_report"]))}</strong> | Ignored by default: <strong>{escape(str(source["ignored_by_default"]))}</strong></p>
    <p>Source error: {escape(source.get("error_sanitized") or "-")}</p>
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


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "json_trustpilot_real_send_execute_path": str(json_path),
        "html_trustpilot_real_send_execute_path": str(html_path),
        "execution_status": payload["execution_status"],
        "production_preflight_used": payload["production_preflight_used"],
        "simulator_used": payload["simulator_used"],
        "preflight_status": payload["preflight_status"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "ack_present": payload["ack_present"],
        "required_ack": payload["required_ack"],
        "required_execute_flag": payload["required_execute_flag"],
        "real_send_execute_requested": payload["real_send_execute_requested"],
        "real_send_execute_allowed_by_preflight": payload["real_send_execute_allowed_by_preflight"],
        "real_send_execute_allowed_by_env": payload["real_send_execute_allowed_by_env"],
        "gmail_send_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "blocking_conditions": payload["blocking_conditions"],
        "next_admin_action": payload["next_admin_action"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    selected = payload["selected_candidate_order_name"] or "None"
    return (
        "Shopify review request Phase 5.14 Trustpilot real send execute skeleton finished.\n"
        f"Execution status: {payload['execution_status']}\n"
        f"Production preflight used: {payload['production_preflight_used']}\n"
        f"Simulator used: {payload['simulator_used']}\n"
        f"Preflight status: {payload['preflight_status']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Selected candidate: {selected}\n"
        f"ACK present: {payload['ack_present']}\n"
        f"Real send execute requested: {payload['real_send_execute_requested']}\n"
        f"Allowed by preflight: {payload['real_send_execute_allowed_by_preflight']}\n"
        f"Allowed by env: {payload['real_send_execute_allowed_by_env']}\n"
        "Safety: no Gmail API, no draft creation/update/delete, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(
    execution_status: str,
    preflight_status: str,
    eligible_count: int,
    selected_order: str,
    simulator_used: bool,
) -> str:
    if execution_status == EXECUTION_STATUS_READY_BUT_DISABLED:
        return (
            f"Final preflight is ready for {selected_order}, but Phase 5.14 is a locked skeleton. "
            "No Gmail API call or email send was performed."
        )
    if execution_status == EXECUTION_STATUS_BLOCKED_MISSING_FLAG:
        data_source = "simulator" if simulator_used else "production"
        return (
            f"{data_source} final preflight is ready for {selected_order}, but the explicit real-send "
            "execute flag is missing. No send was performed."
        )
    if execution_status == EXECUTION_STATUS_BLOCKED_NO_CANDIDATE:
        return "No eligible Trustpilot candidate is available for real send execute. No send was performed."
    return (
        f"Real send execute is blocked because final preflight status is {preflight_status} "
        f"with eligible_candidate_count={eligible_count}. No send was performed."
    )


def _preflight_status_from_data(data: dict) -> str:
    return _first_text(data, ("preflight_status", "report_status", "status")) or PREFLIGHT_STATUS_BLOCKED_NO_CANDIDATE


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


def _yes_no(value: bool) -> str:
    return "Yes" if value else "No"
