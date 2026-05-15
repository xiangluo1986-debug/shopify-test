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


TASK_NAME = "shopify_review_request_trustpilot_candidate_simulator"
COMMAND_LABEL = TASK_NAME
PHASE = "5.12"

SIMULATOR_MODE_ENV_VAR = "SHOPIFY_REVIEW_REQUEST_SIMULATOR_MODE"
DEFAULT_SIMULATOR_MODE = "no_candidate"
SUPPORTED_SIMULATOR_MODES = {
    "no_candidate",
    "one_eligible_candidate",
    "multiple_eligible_candidates",
    "unsafe_candidate",
}

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_candidate_simulator.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_candidate_simulator.html"
GATE_FIXTURE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_locked_gmail_send_gate_simulator_fixture.json"
EXECUTOR_FIXTURE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_executor_shell_simulator_fixture.json"

SIMULATOR_ORDER_NAME = "#SIM-TRUSTPILOT-001"
SIMULATOR_SECOND_ORDER_NAME = "#SIM-TRUSTPILOT-002"
SIMULATOR_CUSTOMER_NAME = "Simulated Trustpilot Customer"
SIMULATOR_MASKED_EMAIL = "s***@example.invalid"
SIMULATOR_TAGS = ["delivered", "1: review request"]

GATE_STATUS_BLOCKED_NO_CANDIDATE = "blocked_no_eligible_candidate"
GATE_STATUS_READY_FOR_ACK = "locked_send_gate_ready_for_ack"
GATE_STATUS_BLOCKED_MULTIPLE = "blocked_multiple_candidates_require_manual_selection"
GATE_STATUS_BLOCKED_SAFETY = "blocked_candidate_safety_check_failed"


def run_shopify_review_request_trustpilot_candidate_simulator_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    simulator_mode = _simulator_mode_from_env()
    payload = _build_payload(
        simulator_mode=simulator_mode,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(REPORT_JSON_PATH, payload)
    html_path = _write_html_report(payload)
    gate_fixture_path = _write_json_report(GATE_FIXTURE_JSON_PATH, _build_gate_fixture(payload))
    executor_fixture_path = _write_json_report(EXECUTOR_FIXTURE_JSON_PATH, _build_executor_fixture(payload))
    payload["generated_downstream_fixture_reports"] = [
        _fixture_report_summary("locked_gmail_send_gate", gate_fixture_path),
        _fixture_report_summary("gmail_send_executor_shell", executor_fixture_path),
    ]
    payload["report_paths"]["gate_simulator_fixture_json"] = str(gate_fixture_path)
    payload["report_paths"]["executor_shell_simulator_fixture_json"] = str(executor_fixture_path)
    _write_json_report(REPORT_JSON_PATH, payload)
    _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _simulator_mode_from_env() -> str:
    simulator_mode = os.environ.get(SIMULATOR_MODE_ENV_VAR, DEFAULT_SIMULATOR_MODE).strip()
    if not simulator_mode:
        return DEFAULT_SIMULATOR_MODE
    if simulator_mode not in SUPPORTED_SIMULATOR_MODES:
        raise ValueError(
            f"{SIMULATOR_MODE_ENV_VAR} must be one of: "
            f"{', '.join(sorted(SUPPORTED_SIMULATOR_MODES))}"
        )
    return simulator_mode


def _build_payload(simulator_mode: str, duration_seconds: float) -> dict:
    generated_at = utc_now_iso()
    eligible_count = _eligible_candidate_count(simulator_mode)
    selected_order = _selected_candidate_order_name(simulator_mode)
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "local-only-candidate-simulator",
        "dry_run": True,
        "simulator_status": _simulator_status(simulator_mode),
        "simulator_mode": simulator_mode,
        "simulator_only": True,
        "sandbox_fixture": True,
        "real_customer_data_used": False,
        "shopify_api_call_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "shopify_write_performed": False,
        "external_review_api_call_performed": False,
        "eligible_candidate_count": eligible_count,
        "selected_candidate_order_name": selected_order,
        "fake_candidate_summary": _fake_candidate_summary(simulator_mode),
        "generated_downstream_fixture_reports": [],
        "next_test_command_suggestions": _next_test_command_suggestions(),
        "simulator_warning": (
            "Sandbox simulator is for testing only. It never uses real customer data "
            "and never sends emails."
        ),
        "report_paths": {
            "json": str(REPORT_JSON_PATH),
            "html": str(REPORT_HTML_PATH),
        },
        "duration_seconds": duration_seconds,
        **_safety_summary(),
        "draft_create_allowed_now": False,
        "gmail_api_allowed_now": False,
        "send_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "gmail_draft_create_performed": False,
        "shopify_tag_write_performed": False,
        "real_send_allowed": False,
        "send_allowed_now_reason": "simulator_fixture_is_never_allowed_to_send",
    }
    return _safe_payload(payload)


def _build_gate_fixture(payload: dict) -> dict:
    simulator_mode = _safe_text(payload.get("simulator_mode"), max_length=80)
    gate_status = _gate_status_for_mode(simulator_mode)
    selected_order = _selected_candidate_order_name(simulator_mode)
    selected_safe = simulator_mode == "one_eligible_candidate"
    fixture = {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "source": "trustpilot_candidate_simulator",
        "source_report": str(REPORT_JSON_PATH),
        "simulator_only": True,
        "sandbox_fixture": True,
        "simulator_mode": simulator_mode,
        "real_customer_data_used": False,
        "gate_status": gate_status,
        "eligible_candidate_count": _eligible_candidate_count(simulator_mode),
        "blocked_candidate_count": _blocked_candidate_count(simulator_mode),
        "selected_candidate_order_name": selected_order,
        "selected_candidate_safe_to_prepare_send": selected_safe,
        "selected_candidate_allowed_for_future_send": selected_safe,
        "next_real_step": "prepare_locked_send_package" if selected_safe else "do_not_send",
        "refresh_status": "refreshed_locked_send_candidate_ready" if selected_safe else gate_status,
        "eligible_candidates_summary": _eligible_candidates_summary(simulator_mode),
        "blocked_candidates_summary": _blocked_candidates_summary(simulator_mode),
        "fake_candidate_summary": payload.get("fake_candidate_summary"),
        "real_send_allowed": False,
        "gmail_api_allowed_now": False,
        "send_allowed_now": False,
        "draft_create_allowed_now": False,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "no_write_safety_flags": _fixture_no_write_flags(),
        **_safety_summary(),
    }
    return _safe_payload(fixture)


def _build_executor_fixture(payload: dict) -> dict:
    simulator_mode = _safe_text(payload.get("simulator_mode"), max_length=80)
    selected_order = _selected_candidate_order_name(simulator_mode)
    fixture = {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "source": "trustpilot_candidate_simulator",
        "source_report": str(REPORT_JSON_PATH),
        "simulator_only": True,
        "sandbox_fixture": True,
        "simulator_mode": simulator_mode,
        "real_customer_data_used": False,
        "gate_status": _gate_status_for_mode(simulator_mode),
        "eligible_candidate_count": _eligible_candidate_count(simulator_mode),
        "selected_candidate_order_name": selected_order,
        "real_send_allowed": False,
        "gmail_api_allowed_now": False,
        "send_allowed_now": False,
        "draft_create_allowed_now": False,
        "shopify_tag_write_allowed_now": False,
        "external_review_api_call_allowed_now": False,
        "fake_candidate_summary": payload.get("fake_candidate_summary"),
        **_safety_summary(),
        "gmail_draft_create_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
    }
    return _safe_payload(fixture)


def _eligible_candidate_count(simulator_mode: str) -> int:
    if simulator_mode == "one_eligible_candidate":
        return 1
    if simulator_mode == "multiple_eligible_candidates":
        return 2
    if simulator_mode == "unsafe_candidate":
        return 1
    return 0


def _blocked_candidate_count(simulator_mode: str) -> int:
    if simulator_mode == "unsafe_candidate":
        return 1
    if simulator_mode == "no_candidate":
        return 0
    return 0


def _selected_candidate_order_name(simulator_mode: str):
    if simulator_mode in {"one_eligible_candidate", "unsafe_candidate"}:
        return SIMULATOR_ORDER_NAME
    return None


def _simulator_status(simulator_mode: str) -> str:
    return {
        "no_candidate": "simulator_no_candidate",
        "one_eligible_candidate": "simulator_one_eligible_candidate_ready",
        "multiple_eligible_candidates": "simulator_multiple_eligible_candidates",
        "unsafe_candidate": "simulator_unsafe_candidate_blocked",
    }.get(simulator_mode, "simulator_invalid_mode")


def _gate_status_for_mode(simulator_mode: str) -> str:
    return {
        "no_candidate": GATE_STATUS_BLOCKED_NO_CANDIDATE,
        "one_eligible_candidate": GATE_STATUS_READY_FOR_ACK,
        "multiple_eligible_candidates": GATE_STATUS_BLOCKED_MULTIPLE,
        "unsafe_candidate": GATE_STATUS_BLOCKED_SAFETY,
    }.get(simulator_mode, GATE_STATUS_BLOCKED_NO_CANDIDATE)


def _fake_candidate_summary(simulator_mode: str) -> dict:
    candidates = _fake_candidates_for_mode(simulator_mode)
    return {
        "simulator_only": True,
        "data_source": "synthetic_fixture_only",
        "real_customer_data_used": False,
        "raw_customer_email_output": False,
        "candidate_count": len(candidates),
        "selected_order_name": _selected_candidate_order_name(simulator_mode),
        "candidates": candidates,
        "safety_note": "All customer and order values are synthetic sandbox data.",
    }


def _fake_candidates_for_mode(simulator_mode: str) -> list[dict]:
    if simulator_mode == "no_candidate":
        return []
    if simulator_mode == "multiple_eligible_candidates":
        return [
            _fake_candidate(SIMULATOR_ORDER_NAME, safe=True),
            _fake_candidate(SIMULATOR_SECOND_ORDER_NAME, safe=True),
        ]
    if simulator_mode == "unsafe_candidate":
        return [_fake_candidate(SIMULATOR_ORDER_NAME, safe=False)]
    return [_fake_candidate(SIMULATOR_ORDER_NAME, safe=True)]


def _fake_candidate(order_name: str, safe: bool) -> dict:
    return {
        "order_name": order_name,
        "customer_name": SIMULATOR_CUSTOMER_NAME,
        "masked_email": SIMULATOR_MASKED_EMAIL,
        "tags": SIMULATOR_TAGS,
        "duplicate_block": False,
        "related_order_group_ready": safe,
        "ticket_risk": not safe,
        "refund_risk": False,
        "cancel_risk": False,
        "safety_status": "safe_synthetic_candidate" if safe else "unsafe_synthetic_candidate",
        "blocking_reasons": [] if safe else ["simulated_ticket_risk"],
        "simulator_only": True,
    }


def _eligible_candidates_summary(simulator_mode: str) -> list[dict]:
    if simulator_mode not in {"one_eligible_candidate", "multiple_eligible_candidates"}:
        return []
    return [
        {
            "order_name": candidate["order_name"],
            "customer_name": candidate["customer_name"],
            "masked_email": candidate["masked_email"],
            "simulator_only": True,
            "tags": candidate["tags"],
        }
        for candidate in _fake_candidates_for_mode(simulator_mode)
    ]


def _blocked_candidates_summary(simulator_mode: str) -> list[dict]:
    if simulator_mode != "unsafe_candidate":
        return []
    candidate = _fake_candidate(SIMULATOR_ORDER_NAME, safe=False)
    return [
        {
            "order_name": candidate["order_name"],
            "status": GATE_STATUS_BLOCKED_SAFETY,
            "reason": "simulated_ticket_risk",
            "blocking_reasons": candidate["blocking_reasons"],
            "simulator_only": True,
        }
    ]


def _fixture_no_write_flags() -> dict:
    return {
        "simulator_fixture_read_only": True,
        "real_customer_data_used": False,
        "real_send_allowed": False,
        "send_allowed_now": False,
        "draft_create_allowed_now": False,
        "gmail_api_allowed_now": False,
        "gmail_send_allowed_now": False,
        "gmail_draft_create_allowed_now": False,
        "gmail_api_call_performed": False,
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
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "external_review_api_call_allowed_now": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
        "all_new_actions_no_write_confirmed": True,
    }


def _next_test_command_suggestions() -> list[str]:
    return [
        (
            "python remote_approval_runner.py --task "
            "shopify_review_request_trustpilot_candidate_simulator --approval local"
        ),
        (
            "$env:SHOPIFY_REVIEW_REQUEST_SIMULATOR_MODE=\"one_eligible_candidate\"; "
            "python remote_approval_runner.py --task "
            "shopify_review_request_trustpilot_candidate_simulator --approval local"
        ),
        (
            "$env:SHOPIFY_REVIEW_REQUEST_USE_SIMULATOR_FIXTURE="
            "\"YES_I_UNDERSTAND_THIS_IS_FAKE_DATA\"; "
            "python remote_approval_runner.py --task "
            "shopify_review_request_trustpilot_locked_gmail_send_gate --approval local"
        ),
    ]


def _fixture_report_summary(key: str, path: Path) -> dict:
    return {
        "key": key,
        "relative_path": f"logs/{path.name}",
        "present": path.exists(),
        "simulator_only": True,
    }


def _write_json_report(path: Path, payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as report_file:
        json.dump(_safe_payload(payload), report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return path


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    fixture_rows = "\n".join(
        f"<tr><td>{escape(row.get('key', ''))}</td>"
        f"<td><code>{escape(row.get('relative_path', ''))}</code></td>"
        f"<td>{escape(str(row.get('present') is True))}</td></tr>"
        for row in payload.get("generated_downstream_fixture_reports") or []
    )
    if not fixture_rows:
        fixture_rows = '<tr><td colspan="3">Fixture files are being generated.</td></tr>'
    candidate_rows = "\n".join(
        _render_candidate_row(candidate)
        for candidate in (payload.get("fake_candidate_summary") or {}).get("candidates", [])
    )
    if not candidate_rows:
        candidate_rows = '<tr><td colspan="6">No synthetic candidate in this mode.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Candidate Simulator</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .status {{ border-left: 4px solid #2563eb; background: #eff6ff; padding: 10px 12px; }}
    .warning {{ border-left: 4px solid #d97706; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Candidate Simulator</h1>
  <p class="warning">Sandbox simulator is for testing only. It never uses real customer data and never sends emails.</p>
  <p class="status">Simulator status: <strong>{escape(payload["simulator_status"])}</strong></p>
  <table>
    <tbody>
      <tr><th>Simulator mode</th><td><code>{escape(payload["simulator_mode"])}</code></td></tr>
      <tr><th>Simulator only</th><td>True</td></tr>
      <tr><th>Real customer data used</th><td>False</td></tr>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(str(payload.get("selected_candidate_order_name") or "-"))}</td></tr>
      <tr><th>Gmail API call performed</th><td>False</td></tr>
      <tr><th>Email sent</th><td>False</td></tr>
      <tr><th>Shopify write performed</th><td>False</td></tr>
      <tr><th>External review API call performed</th><td>False</td></tr>
    </tbody>
  </table>
  <h2>Synthetic Candidates</h2>
  <table>
    <thead><tr><th>Order</th><th>Customer</th><th>Masked email</th><th>Tags</th><th>Safe</th><th>Blocking reasons</th></tr></thead>
    <tbody>{candidate_rows}</tbody>
  </table>
  <h2>Simulator Fixtures</h2>
  <table><thead><tr><th>Key</th><th>Path</th><th>Present</th></tr></thead><tbody>{fixture_rows}</tbody></table>
  <details>
    <summary>Advanced debug details</summary>
    <p>JSON report: <code>{escape(str(REPORT_JSON_PATH))}</code></p>
    <p>HTML report: <code>{escape(str(REPORT_HTML_PATH))}</code></p>
    <p>Gate/executor must ignore these fixtures unless <code>SHOPIFY_REVIEW_REQUEST_USE_SIMULATOR_FIXTURE=YES_I_UNDERSTAND_THIS_IS_FAKE_DATA</code> is set.</p>
  </details>
</body>
</html>"""


def _render_candidate_row(candidate: dict) -> str:
    tags = ", ".join(candidate.get("tags") or [])
    blocking_reasons = ", ".join(candidate.get("blocking_reasons") or []) or "-"
    safe = candidate.get("safety_status") == "safe_synthetic_candidate"
    return (
        "<tr>"
        f"<td><code>{escape(candidate.get('order_name', ''))}</code></td>"
        f"<td>{escape(candidate.get('customer_name', ''))}</td>"
        f"<td>{escape(candidate.get('masked_email', ''))}</td>"
        f"<td>{escape(tags)}</td>"
        f"<td>{escape(str(safe))}</td>"
        f"<td>{escape(blocking_reasons)}</td>"
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
        "json_trustpilot_candidate_simulator_path": str(json_path),
        "html_trustpilot_candidate_simulator_path": str(html_path),
        "simulator_status": payload["simulator_status"],
        "simulator_mode": payload["simulator_mode"],
        "simulator_only": True,
        "real_customer_data_used": False,
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "generated_downstream_fixture_reports": payload["generated_downstream_fixture_reports"],
        "shopify_api_call_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "shopify_write_performed": False,
        "external_review_api_call_performed": False,
        **_safety_summary(),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    selected = payload["selected_candidate_order_name"] or "None"
    return (
        "Shopify review request Phase 5.12 Trustpilot candidate simulator finished.\n"
        f"Simulator status: {payload['simulator_status']}\n"
        f"Simulator mode: {payload['simulator_mode']}\n"
        "Simulator only: True\n"
        "Real customer data used: False\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Selected candidate: {selected}\n"
        "Safety: no Gmail API, no draft creation/update/delete, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
