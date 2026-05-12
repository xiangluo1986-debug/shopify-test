import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_batch_apply_execution_approval_validate"
COMMAND_LABEL = "shopify_translation_batch_apply_execution_approval_validation"
SOURCE_EXECUTION_DRY_RUN_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_dry_run.json"
EXECUTION_APPROVAL_VALIDATION_JSON_PATH = (
    LOG_DIR / "shopify_translation_batch_apply_execution_approval_validation.json"
)
EXECUTION_APPROVAL_VALIDATION_HTML_PATH = (
    LOG_DIR / "shopify_translation_batch_apply_execution_approval_validation.html"
)
EXPECTED_EXECUTION_DRY_RUN_TASK = "shopify_translation_batch_apply_execution_dry_run"
EXPECTED_EXECUTION_DRY_RUN_MODE = "execution-dry-run-only"
MAX_PRODUCTS = 3
MAX_LOCALES = 5
MAX_ITEMS = MAX_PRODUCTS * MAX_LOCALES
ALLOWED_EXECUTION_APPROVAL_STATUSES = ["pending", "approved", "rejected"]


def run_shopify_translation_batch_apply_execution_approval_validate_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_error = ""
    execution_dry_run = {}

    try:
        execution_dry_run = _read_json(SOURCE_EXECUTION_DRY_RUN_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        parse_error = f"Could not parse execution dry-run JSON: {exc}"
        validation_errors.append("execution_dry_run_json_invalid")

    if execution_dry_run:
        errors, warnings = _validate_execution_dry_run(execution_dry_run)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)

    execution_result = _execution_validation_result(execution_dry_run, validation_errors)
    validation_failures = _unique(validation_errors + execution_result["validation_failures"])
    validation_warnings = _unique(validation_warnings + execution_result["validation_warnings"])
    success = not validation_failures
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": "execution-approval-validation-only",
        "command_label": COMMAND_LABEL,
        "source_execution_dry_run_path": str(SOURCE_EXECUTION_DRY_RUN_PATH),
        "json_execution_approval_validation_path": str(EXECUTION_APPROVAL_VALIDATION_JSON_PATH),
        "html_execution_approval_validation_path": str(EXECUTION_APPROVAL_VALIDATION_HTML_PATH),
        "success": success,
        "execution_approval_validation_only": True,
        "execution_dry_run_only": True,
        "command_validation_only": True,
        "command_generation_only": True,
        "preview_only": True,
        "plan_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(execution_dry_run.get("all_no_write_confirmed"))
        if execution_dry_run
        else False,
        "command_executed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "translations_register_performed": False,
        "source_execution_dry_run_task": execution_dry_run.get("task", "") if execution_dry_run else "",
        "source_execution_dry_run_mode": execution_dry_run.get("mode", "") if execution_dry_run else "",
        "source_execution_approval_summary": execution_dry_run.get("execution_approval_summary", {})
        if execution_dry_run
        else {},
        "execution_validation_status": execution_result["execution_validation_status"],
        "real_execution_allowed": execution_result["real_execution_allowed"],
        "execution_dry_run_status": execution_result["execution_dry_run_status"],
        "simulated_execution_count": execution_result["simulated_execution_count"],
        "simulated_payload_count": execution_result["simulated_payload_count"],
        "eligible_real_execution_count": execution_result["eligible_real_execution_count"],
        "blocked_count": execution_result["blocked_count"],
        "pending_count": execution_result["pending_count"],
        "rejected_count": execution_result["rejected_count"],
        "execution_validation_items": execution_result["execution_validation_items"],
        "validation_failures": validation_failures,
        "validation_warnings": validation_warnings,
        "parse_error": parse_error,
        "detected_issue_summary": _issue_summary(
            execution_result["execution_validation_status"], validation_failures
        ),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
            "execution_approval_validation_only": True,
            "execution_dry_run_only": True,
            "command_executed": False,
            "shopify_writes_allowed": False,
            "register_translations_allowed": False,
            "publish_allowed": False,
            "apply_allowed": False,
            "update_allowed": False,
            "mutation_allowed": False,
            "database_writes_allowed": False,
            "git_push_allowed": False,
            "auto_scan_all_products_allowed": False,
            "max_products": MAX_PRODUCTS,
            "max_locales": MAX_LOCALES,
            "max_items": MAX_ITEMS,
        },
    }
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_execution_approval_validation_path": str(json_path),
        "html_execution_approval_validation_path": str(html_path),
        "source_execution_dry_run_path": str(SOURCE_EXECUTION_DRY_RUN_PATH),
        "execution_approval_validation_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": payload["all_no_write_confirmed"],
        "command_executed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "execution_validation_status": payload["execution_validation_status"],
        "real_execution_allowed": payload["real_execution_allowed"],
        "execution_dry_run_status": payload["execution_dry_run_status"],
        "simulated_execution_count": payload["simulated_execution_count"],
        "simulated_payload_count": payload["simulated_payload_count"],
        "eligible_real_execution_count": payload["eligible_real_execution_count"],
        "blocked_count": payload["blocked_count"],
        "pending_count": payload["pending_count"],
        "validation_failures_count": len(validation_failures),
        "validation_warnings_count": len(validation_warnings),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_execution_dry_run(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    unsafe_checks = [
        ("task", report.get("task") == EXPECTED_EXECUTION_DRY_RUN_TASK),
        ("mode", report.get("mode") == EXPECTED_EXECUTION_DRY_RUN_MODE),
        ("command_executed", report.get("command_executed") is False),
        ("apply_performed", report.get("apply_performed") is False),
        ("publish_performed", report.get("publish_performed") is False),
        ("translations_register_performed", report.get("translations_register_performed") is False),
        ("shopify_write_performed", report.get("shopify_write_performed") is False),
        ("no_shopify_writes_performed", report.get("no_shopify_writes_performed") is True),
        ("all_no_write_confirmed", report.get("all_no_write_confirmed") is True),
    ]
    for name, passed in unsafe_checks:
        if passed:
            continue
        if name in {"command_executed", "apply_performed", "publish_performed", "translations_register_performed"}:
            errors.append("command_or_apply_already_performed")
        elif name in {"shopify_write_performed", "no_shopify_writes_performed", "all_no_write_confirmed"}:
            errors.append("no_write_not_confirmed")
        else:
            errors.append(f"unsafe_execution_dry_run_{name}")

    for field in [
        "execution_dry_run_status",
        "simulated_execution_count",
        "simulated_payload_count",
        "execution_approval_summary",
    ]:
        if field not in report:
            errors.append(f"unsafe_execution_dry_run_{field}_missing")

    simulated_items = report.get("simulated_items")
    simulated_payloads = report.get("simulated_payloads")
    blocked_items = report.get("blocked_items")
    if not isinstance(simulated_items, list):
        errors.append("unsafe_execution_dry_run_simulated_items")
        simulated_items = []
    if not isinstance(simulated_payloads, list):
        errors.append("unsafe_execution_dry_run_simulated_payloads")
        simulated_payloads = []
    if blocked_items is not None and not isinstance(blocked_items, list):
        errors.append("unsafe_execution_dry_run_blocked_items")
        blocked_items = []

    if _safe_int(report.get("simulated_execution_count")) != len(simulated_items):
        errors.append("unsafe_execution_dry_run_simulated_execution_count_mismatch")
    if _safe_int(report.get("simulated_payload_count")) != len(simulated_payloads):
        errors.append("unsafe_execution_dry_run_simulated_payload_count_mismatch")

    all_items = simulated_items + (blocked_items or [])
    if len(all_items) > MAX_ITEMS:
        errors.append("product_or_locale_limit_exceeded")
    product_count = len({str(item.get("product_id", "")) for item in all_items if item.get("product_id")})
    locale_count = len({str(item.get("locale", "")) for item in all_items if item.get("locale")})
    if product_count > MAX_PRODUCTS or locale_count > MAX_LOCALES:
        errors.append("product_or_locale_limit_exceeded")

    approval_summary = report.get("execution_approval_summary")
    if not isinstance(approval_summary, dict):
        errors.append("execution_approval_missing")
        return _unique(errors), _unique(warnings)

    status = str(approval_summary.get("execution_approval_status", ""))
    if status not in ALLOWED_EXECUTION_APPROVAL_STATUSES:
        errors.append("invalid_execution_approval_status")
    if approval_summary.get("real_execution_allowed") is True or report.get("real_execution_allowed") is True:
        warnings.append("source real_execution_allowed was true; execution approval validation recomputed it")
    return _unique(errors), _unique(warnings)


def _execution_validation_result(report: dict, validation_errors: list[str]) -> dict:
    simulated_items = report.get("simulated_items", []) if isinstance(report.get("simulated_items"), list) else []
    simulated_payloads = report.get("simulated_payloads", []) if isinstance(report.get("simulated_payloads"), list) else []
    approval_summary = report.get("execution_approval_summary", {}) if isinstance(
        report.get("execution_approval_summary"), dict
    ) else {}
    approval_status = str(approval_summary.get("execution_approval_status", "pending"))
    approved_by = str(approval_summary.get("execution_approved_by", "") or "").strip()
    item_results = [_validate_simulated_item(item, simulated_payloads) for item in simulated_items]
    item_failures = [
        f"{item.get('simulation_id', '')}: {failure}"
        for item in item_results
        for failure in item.get("validation_failures", [])
    ]
    validation_failures = []
    validation_warnings = []
    execution_validation_status = "blocked"
    real_execution_allowed = False
    eligible_count = 0
    blocked_count = 0
    pending_count = 0
    rejected_count = 0

    if validation_errors:
        execution_validation_status = "blocked"
        blocked_count = len(simulated_items)
    elif approval_status == "pending":
        execution_validation_status = "pending"
        pending_count = len(simulated_items)
    elif approval_status == "rejected":
        execution_validation_status = "rejected"
        rejected_count = len(simulated_items)
    elif approval_status == "approved":
        if not approved_by:
            validation_failures.append("execution_approval_status=approved requires execution_approved_by")
        if len(simulated_items) == 0:
            validation_failures.append("execution_approval_status=approved requires simulated_execution_count > 0")
        validation_failures.extend(item_failures)
        if validation_failures:
            execution_validation_status = "blocked"
            blocked_count = max(len(simulated_items), 1)
        else:
            execution_validation_status = "validated_for_real_execution"
            real_execution_allowed = True
            eligible_count = len(simulated_items)
    else:
        validation_failures.append("invalid_execution_approval_status")
        execution_validation_status = "blocked"
        blocked_count = len(simulated_items)

    return {
        "execution_validation_status": execution_validation_status,
        "real_execution_allowed": real_execution_allowed,
        "execution_dry_run_status": report.get("execution_dry_run_status", ""),
        "simulated_execution_count": len(simulated_items),
        "simulated_payload_count": len(simulated_payloads),
        "eligible_real_execution_count": eligible_count,
        "blocked_count": blocked_count,
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "execution_validation_items": item_results,
        "validation_failures": _unique(validation_failures),
        "validation_warnings": _unique(validation_warnings),
    }


def _validate_simulated_item(item: dict, simulated_payloads: list[dict]) -> dict:
    failures = []
    payload_available = _payload_preview_available(item, simulated_payloads)
    if item.get("execution_decision") != "approve":
        failures.append("execution_decision must be approve")
    if item.get("execution_approval_ready") is not True:
        failures.append("execution_approval_ready must be true")
    if item.get("command_executed") is not False:
        failures.append("command_executed must be false")
    if item.get("apply_performed") is not False:
        failures.append("apply_performed must be false")
    if item.get("publish_performed") is not False:
        failures.append("publish_performed must be false")
    if item.get("shopify_write_performed") is not False:
        failures.append("shopify_write_performed must be false")
    if item.get("translations_register_performed") is not False:
        failures.append("translations_register_performed must be false")
    if item.get("would_call_shopify_mutation") and item.get("would_call_shopify_mutation") != "translationsRegister":
        failures.append("would_call_shopify_mutation must only be translationsRegister text")
    if not payload_available:
        failures.append("payload_preview_available must be true")

    return {
        "simulation_id": item.get("simulation_id", ""),
        "command_id": item.get("command_id", ""),
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "execution_decision": item.get("execution_decision", ""),
        "execution_approval_ready": bool(item.get("execution_approval_ready")),
        "payload_preview_available": payload_available,
        "would_call_shopify_mutation": item.get("would_call_shopify_mutation", ""),
        "eligible_for_real_execution": not failures,
        "validation_failures": failures,
        "command_executed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _payload_preview_available(item: dict, simulated_payloads: list[dict]) -> bool:
    if item.get("payload_preview_available") is True:
        return True
    command_id = str(item.get("command_id", "") or "")
    product_id = str(item.get("product_id", "") or "")
    locale = str(item.get("locale", "") or "")
    for payload in simulated_payloads:
        if command_id and str(payload.get("command_id", "") or "") == command_id:
            return True
        if product_id and locale and payload.get("product_id") == product_id and payload.get("locale") == locale:
            return True
    return False


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    EXECUTION_APPROVAL_VALIDATION_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(EXECUTION_APPROVAL_VALIDATION_JSON_PATH.read_text(encoding="utf-8"))
    return EXECUTION_APPROVAL_VALIDATION_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    EXECUTION_APPROVAL_VALIDATION_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return EXECUTION_APPROVAL_VALIDATION_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    item_rows = "\n".join(_render_item_row(item) for item in payload.get("execution_validation_items", []))
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Source Execution Dry-Run", "source_execution_dry_run_path"),
            ("Execution Validation Status", "execution_validation_status"),
            ("Real Execution Allowed", "real_execution_allowed"),
            ("Execution Dry-Run Status", "execution_dry_run_status"),
            ("Simulated Execution Count", "simulated_execution_count"),
            ("Simulated Payload Count", "simulated_payload_count"),
            ("Eligible Real Execution Count", "eligible_real_execution_count"),
            ("Blocked Count", "blocked_count"),
            ("Pending Count", "pending_count"),
            ("Rejected Count", "rejected_count"),
            ("Command Executed", "command_executed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Apply Performed", "apply_performed"),
            ("Publish Performed", "publish_performed"),
            ("Translations Register Performed", "translations_register_performed"),
            ("No Shopify Writes Performed", "no_shopify_writes_performed"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("Validation Failures", "validation_failures"),
            ("Validation Warnings", "validation_warnings"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Translation Execution Approval Validation</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
    .path {{ font-family: Consolas, monospace; overflow-wrap: anywhere; }}
    .empty {{ color: #57606a; }}
  </style>
</head>
<body>
  <h1>Shopify Translation Execution Approval Validation</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Simulated Item Validation</h2>
  <table>
    <thead>
      <tr>
        <th>Simulation ID</th><th>Command ID</th><th>Product ID</th><th>Locale</th>
        <th>Decision</th><th>Ready</th><th>Payload Preview</th><th>Would Call</th><th>Eligible</th><th>Failures</th>
      </tr>
    </thead>
    <tbody>{item_rows or _empty_row(10, "No simulated execution items to validate.")}</tbody>
  </table>
  <h2>Safety</h2>
  <ul>
    <li>This task is execution-approval-validation-only.</li>
    <li>No command was executed.</li>
    <li>No Shopify writes were performed.</li>
    <li>shopify_write_performed=false.</li>
    <li>apply_performed=false and publish_performed=false.</li>
    <li>translations_register_performed=false.</li>
    <li>Apply, publish, update, mutation, translationsRegister, and command execution are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _render_item_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('simulation_id', '')))}</td>"
        f"<td>{escape(str(item.get('command_id', '')))}</td>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('execution_decision', '')))}</td>"
        f"<td>{'true' if item.get('execution_approval_ready') else 'false'}</td>"
        f"<td>{'true' if item.get('payload_preview_available') else 'false'}</td>"
        f"<td>{escape(str(item.get('would_call_shopify_mutation', '')))}</td>"
        f"<td>{'true' if item.get('eligible_for_real_execution') else 'false'}</td>"
        f"<td>{escape('; '.join(item.get('validation_failures') or []))}</td>"
        "</tr>"
    )


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\" class=\"empty\">{escape(message)}</td></tr>"


def _issue_summary(execution_validation_status: str, validation_failures: list[str]) -> str:
    if validation_failures:
        return "Execution approval validation blocked: " + ", ".join(_unique(validation_failures))
    return f"Execution approval validation completed with status {execution_validation_status}. No Shopify writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify batch translation execution approval validation completed.\n"
        f"Source execution dry-run: {payload.get('source_execution_dry_run_path')}\n"
        f"Execution validation status: {payload.get('execution_validation_status')}\n"
        f"Real execution allowed: {payload.get('real_execution_allowed')}\n"
        f"Execution dry-run status: {payload.get('execution_dry_run_status')}\n"
        f"Simulated executions: {payload.get('simulated_execution_count')}\n"
        f"Eligible real execution count: {payload.get('eligible_real_execution_count')}\n"
        f"Validation failures: {len(payload.get('validation_failures') or [])}\n"
        "Execution approval validation JSON:\n"
        f"{json_path}\n\n"
        "Execution approval validation HTML:\n"
        f"{html_path}\n"
        "Execution approval validation only. No Shopify writes performed by this task.\n"
        "command_executed=false.\n"
        "shopify_write_performed=false.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep execution approval validation files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Write, publish, apply, update, mutation, translationsRegister, command execution, commit, and push are not allowed."
    )


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
