import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_batch_apply_execution_dry_run"
COMMAND_LABEL = "shopify_translation_batch_apply_execution_dry_run_from_command_validation"
SOURCE_COMMAND_VALIDATION_PATH = LOG_DIR / "shopify_translation_batch_apply_command_validation.json"
SOURCE_COMMAND_PLAN_PATH = LOG_DIR / "shopify_translation_batch_apply_command_plan.json"
EXECUTION_DRY_RUN_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_dry_run.json"
EXECUTION_DRY_RUN_HTML_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_dry_run.html"
EXPECTED_COMMAND_VALIDATION_TASK = "shopify_translation_batch_apply_command_validate"
EXPECTED_COMMAND_VALIDATION_MODE = "command-validation-only"
MAX_PRODUCTS = 3
MAX_LOCALES = 5
MAX_ITEMS = MAX_PRODUCTS * MAX_LOCALES
EXECUTION_ALLOWED_STATUSES = {"approved", "validated_for_future_command_execution"}
SHOPIFY_TOKEN_PREFIX_PATTERN = re.escape("sh" + "pat_") + r"[A-Za-z0-9_]+"
SECRET_MARKER_RE = re.compile(
    r"(access[_\s-]?token|api[_\s-]?key|password|credential|secret|" + SHOPIFY_TOKEN_PREFIX_PATTERN + r")",
    re.IGNORECASE,
)


def run_shopify_translation_batch_apply_execution_dry_run_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_error = ""
    command_validation = {}
    command_plan = {}

    try:
        command_validation = _read_json(SOURCE_COMMAND_VALIDATION_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        parse_error = f"Could not parse command validation JSON: {exc}"
        validation_errors.append("command_validation_json_invalid")

    if command_validation:
        errors, warnings = _validate_command_validation(command_validation)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)
        command_plan = _read_optional_command_plan(command_validation.get("source_command_plan_path", ""))

    execution_result = _execution_dry_run_result(command_validation, command_plan, validation_errors)
    validation_failures = _unique(validation_errors + execution_result["validation_failures"])
    validation_warnings = _unique(validation_warnings + execution_result["validation_warnings"])
    success = not validation_failures
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": "execution-dry-run-only",
        "command_label": COMMAND_LABEL,
        "source_command_validation_path": str(SOURCE_COMMAND_VALIDATION_PATH),
        "source_command_plan_path": str(SOURCE_COMMAND_PLAN_PATH),
        "json_execution_dry_run_path": str(EXECUTION_DRY_RUN_JSON_PATH),
        "html_execution_dry_run_path": str(EXECUTION_DRY_RUN_HTML_PATH),
        "success": success,
        "execution_dry_run_only": True,
        "command_validation_only": True,
        "command_generation_only": True,
        "preview_only": True,
        "plan_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(command_validation.get("all_no_write_confirmed"))
        if command_validation
        else False,
        "command_executed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "translations_register_performed": False,
        "source_command_validation_task": command_validation.get("task", "") if command_validation else "",
        "source_command_validation_mode": command_validation.get("mode", "") if command_validation else "",
        "source_command_validation_status": command_validation.get("command_validation_status", "")
        if command_validation
        else "",
        "execution_dry_run_status": execution_result["execution_dry_run_status"],
        "command_execution_allowed": execution_result["command_execution_allowed"],
        "generated_command_count": execution_result["generated_command_count"],
        "generated_payload_count": execution_result["generated_payload_count"],
        "eligible_command_execution_count": execution_result["eligible_command_execution_count"],
        "simulated_execution_count": len(execution_result["simulated_items"]),
        "simulated_payload_count": len(execution_result["simulated_payloads"]),
        "commands_executed": [],
        "simulated_items": execution_result["simulated_items"],
        "simulated_payloads": execution_result["simulated_payloads"],
        "blocked_items": execution_result["blocked_items"],
        "reason": execution_result["reason"],
        "validation_failures": validation_failures,
        "validation_warnings": validation_warnings,
        "parse_error": parse_error,
        "detected_issue_summary": _issue_summary(execution_result["execution_dry_run_status"], validation_failures),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
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
        "json_execution_dry_run_path": str(json_path),
        "html_execution_dry_run_path": str(html_path),
        "source_command_validation_path": str(SOURCE_COMMAND_VALIDATION_PATH),
        "execution_dry_run_only": True,
        "execution_dry_run_status": payload["execution_dry_run_status"],
        "command_execution_allowed": payload["command_execution_allowed"],
        "command_executed": False,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": payload["all_no_write_confirmed"],
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "generated_command_count": payload["generated_command_count"],
        "generated_payload_count": payload["generated_payload_count"],
        "eligible_command_execution_count": payload["eligible_command_execution_count"],
        "simulated_execution_count": payload["simulated_execution_count"],
        "simulated_payload_count": payload["simulated_payload_count"],
        "blocked_items_count": len(payload["blocked_items"]),
        "validation_failures_count": len(validation_failures),
        "validation_warnings_count": len(validation_warnings),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_optional_command_plan(path_value: str) -> dict:
    candidates = []
    if path_value:
        candidates.append(Path(path_value))
    candidates.append(SOURCE_COMMAND_PLAN_PATH)
    for path in candidates:
        try:
            if path.exists():
                return _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _validate_command_validation(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    unsafe_checks = [
        ("task", report.get("task") == EXPECTED_COMMAND_VALIDATION_TASK),
        ("mode", report.get("mode") == EXPECTED_COMMAND_VALIDATION_MODE),
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
        if name in {"apply_performed", "publish_performed", "translations_register_performed"}:
            errors.append("apply_or_publish_already_performed")
        elif name in {"shopify_write_performed", "no_shopify_writes_performed", "all_no_write_confirmed"}:
            errors.append("no_write_not_confirmed")
        else:
            errors.append(f"unsafe_command_validation_report_{name}")

    for field in [
        "command_validation_status",
        "command_execution_allowed",
        "eligible_command_execution_count",
        "generated_command_count",
        "generated_payload_count",
    ]:
        if field not in report:
            errors.append(f"unsafe_command_validation_report_{field}_missing")

    items = report.get("command_validation_items")
    if items is not None and not isinstance(items, list):
        errors.append("unsafe_command_validation_report_items")
        items = []
    if isinstance(items, list) and len(items) > MAX_ITEMS:
        errors.append("product_or_locale_limit_exceeded")
    product_count = len({str(item.get("product_id", "")) for item in items or [] if item.get("product_id")})
    locale_count = len({str(item.get("locale", "")) for item in items or [] if item.get("locale")})
    if product_count > MAX_PRODUCTS or locale_count > MAX_LOCALES:
        errors.append("product_or_locale_limit_exceeded")

    if report.get("command_execution_allowed") is True and report.get("command_validation_status") not in (
        "validated_for_future_command_execution",
        "approved",
    ):
        warnings.append("command_execution_allowed true but status is not approved; execution dry-run will recompute")
    return _unique(errors), _unique(warnings)


def _execution_dry_run_result(validation: dict, command_plan: dict, validation_errors: list[str]) -> dict:
    validation_items = validation.get("command_validation_items", []) if isinstance(
        validation.get("command_validation_items"), list
    ) else []
    commands_by_id = _commands_by_id(command_plan)
    command_execution_allowed = validation.get("command_execution_allowed") is True
    validation_status = str(validation.get("command_validation_status", ""))
    eligible_count = _safe_int(validation.get("eligible_command_execution_count"))
    generated_command_count = _safe_int(validation.get("generated_command_count"))
    generated_payload_count = _safe_int(validation.get("generated_payload_count"))

    if validation_errors:
        return {
            "execution_dry_run_status": "failed",
            "command_execution_allowed": False,
            "generated_command_count": generated_command_count,
            "generated_payload_count": generated_payload_count,
            "eligible_command_execution_count": eligible_count,
            "simulated_items": [],
            "simulated_payloads": [],
            "blocked_items": _blocked_items_from_validation(validation_items, validation_errors),
            "reason": _unique(validation_errors),
            "validation_failures": [],
            "validation_warnings": [],
        }

    if not command_execution_allowed:
        return {
            "execution_dry_run_status": "blocked",
            "command_execution_allowed": False,
            "generated_command_count": generated_command_count,
            "generated_payload_count": generated_payload_count,
            "eligible_command_execution_count": eligible_count,
            "simulated_items": [],
            "simulated_payloads": [],
            "blocked_items": _blocked_items_from_validation(validation_items, ["command_execution_allowed=false"]),
            "reason": [
                "command_execution_allowed=false",
                "Command approval validation has not approved execution.",
            ],
            "validation_failures": [],
            "validation_warnings": [],
        }

    if validation_status not in EXECUTION_ALLOWED_STATUSES:
        return {
            "execution_dry_run_status": "blocked",
            "command_execution_allowed": False,
            "generated_command_count": generated_command_count,
            "generated_payload_count": generated_payload_count,
            "eligible_command_execution_count": eligible_count,
            "simulated_items": [],
            "simulated_payloads": [],
            "blocked_items": _blocked_items_from_validation(
                validation_items, [f"command_validation_status={validation_status or '<missing>'}"]
            ),
            "reason": [
                f"command_validation_status={validation_status or '<missing>'}",
                "Command approval validation has not approved execution.",
            ],
            "validation_failures": [],
            "validation_warnings": [],
        }

    if eligible_count <= 0:
        return {
            "execution_dry_run_status": "blocked",
            "command_execution_allowed": False,
            "generated_command_count": generated_command_count,
            "generated_payload_count": generated_payload_count,
            "eligible_command_execution_count": eligible_count,
            "simulated_items": [],
            "simulated_payloads": [],
            "blocked_items": _blocked_items_from_validation(validation_items, ["eligible_command_execution_count <= 0"]),
            "reason": ["eligible_command_execution_count <= 0"],
            "validation_failures": [],
            "validation_warnings": [],
        }

    simulated_items = []
    simulated_payloads = []
    blocked_items = []
    for index, item in enumerate(validation_items):
        source_command = commands_by_id.get(str(item.get("command_id", "")), {})
        reasons = _item_not_simulatable_reasons(item, source_command)
        if reasons:
            blocked_items.append(_blocked_item(item, reasons))
            continue
        simulated_items.append(_simulated_item(item, source_command, index))
        simulated_payloads.append(_simulated_payload(item, source_command, index))

    status = "simulated" if simulated_items and len(simulated_items) == eligible_count else "blocked"
    reason = []
    if status == "simulated":
        reason.append("Execution dry-run simulated approved command items only. No commands executed.")
    else:
        reason.append("No command items passed execution dry-run simulation checks.")
    return {
        "execution_dry_run_status": status,
        "command_execution_allowed": True,
        "generated_command_count": generated_command_count,
        "generated_payload_count": generated_payload_count,
        "eligible_command_execution_count": eligible_count,
        "simulated_items": simulated_items,
        "simulated_payloads": simulated_payloads,
        "blocked_items": blocked_items,
        "reason": _unique(reason),
        "validation_failures": [],
        "validation_warnings": [],
    }


def _commands_by_id(command_plan: dict) -> dict[str, dict]:
    commands = command_plan.get("commands", []) if isinstance(command_plan.get("commands"), list) else []
    return {str(item.get("command_id", "")): item for item in commands}


def _item_not_simulatable_reasons(item: dict, source_command: dict) -> list[str]:
    reasons = []
    command_text = _command_text(source_command)
    if not _is_item_eligible(item):
        reasons.append("command item is not eligible for execution")
    if item.get("command_decision") != "approve":
        reasons.append("command_decision is not approve")
    if item.get("command_approval_ready") is not True:
        reasons.append("command_approval_ready is not true")
    if not source_command:
        reasons.append("source command plan item is missing")
    if source_command and not command_text:
        reasons.append("command preview is missing")
    if _contains_secret_marker(command_text):
        reasons.append("command preview contains secret-like marker")
    if source_command.get("shopify_write_performed") is not False:
        reasons.append("source command shopify_write_performed must be false")
    if source_command.get("apply_performed") is not False:
        reasons.append("source command apply_performed must be false")
    if source_command.get("publish_performed") is not False:
        reasons.append("source command publish_performed must be false")
    if source_command.get("translations_register_performed") is not False:
        reasons.append("source command translations_register_performed must be false")
    return _unique(reasons)


def _is_item_eligible(item: dict) -> bool:
    return item.get("eligible_for_command_execution") is True or item.get("eligible_for_future_execution") is True


def _simulated_item(item: dict, source_command: dict, index: int) -> dict:
    return {
        "simulation_id": f"simulated_execution_{index + 1}",
        "command_id": item.get("command_id", ""),
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "execution_dry_run_only": True,
        "command_would_execute_in_future_write_task": True,
        "command_executed": False,
        "command_preview_present": bool(_command_text(source_command)),
        "would_call_shopify_mutation": source_command.get("would_call_shopify_mutation", ""),
        "would_apply_fields": source_command.get("would_apply_fields", []),
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _simulated_payload(item: dict, source_command: dict, index: int) -> dict:
    return {
        "simulation_payload_id": f"simulated_payload_{index + 1}",
        "command_id": item.get("command_id", ""),
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "execution_dry_run_only": True,
        "payload_values_included": False,
        "would_apply_fields": source_command.get("would_apply_fields", []),
        "command_executed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _blocked_items_from_validation(items: list[dict], reasons: list[str]) -> list[dict]:
    return [_blocked_item(item, reasons) for item in items]


def _blocked_item(item: dict, reasons: list[str]) -> dict:
    return {
        "command_id": item.get("command_id", ""),
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "command_decision": item.get("command_decision", ""),
        "command_approval_ready": bool(item.get("command_approval_ready")),
        "eligible_for_command_execution": _is_item_eligible(item),
        "reason": _unique(reasons),
        "command_executed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _command_text(item: dict) -> str:
    return " ".join(
        str(item.get(field, "") or "")
        for field in ["command_string_preview", "command_preview", "command"]
    )


def _contains_secret_marker(text: str) -> bool:
    return bool(SECRET_MARKER_RE.search(text or ""))


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    EXECUTION_DRY_RUN_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(EXECUTION_DRY_RUN_JSON_PATH.read_text(encoding="utf-8"))
    return EXECUTION_DRY_RUN_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    EXECUTION_DRY_RUN_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return EXECUTION_DRY_RUN_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    simulated_rows = "\n".join(_render_simulated_row(item) for item in payload.get("simulated_items", []))
    blocked_rows = "\n".join(_render_blocked_row(item) for item in payload.get("blocked_items", []))
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Source Command Validation", "source_command_validation_path"),
            ("Execution Dry-Run Status", "execution_dry_run_status"),
            ("Command Execution Allowed", "command_execution_allowed"),
            ("Generated Command Count", "generated_command_count"),
            ("Eligible Command Execution Count", "eligible_command_execution_count"),
            ("Simulated Execution Count", "simulated_execution_count"),
            ("Simulated Payload Count", "simulated_payload_count"),
            ("Command Executed", "command_executed"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("No Shopify Writes Performed", "no_shopify_writes_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Apply Performed", "apply_performed"),
            ("Publish Performed", "publish_performed"),
            ("Translations Register Performed", "translations_register_performed"),
            ("Reason", "reason"),
            ("Validation Failures", "validation_failures"),
            ("Validation Warnings", "validation_warnings"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Translation Apply Execution Dry-Run</title>
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
  <h1>Shopify Translation Apply Execution Dry-Run</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Simulated Execution Items</h2>
  <table>
    <thead>
      <tr>
        <th>Simulation ID</th><th>Command ID</th><th>Product ID</th><th>Locale</th>
        <th>Command Executed</th><th>Would Call</th><th>Fields</th>
      </tr>
    </thead>
    <tbody>{simulated_rows or _empty_row(7, "No execution items simulated.")}</tbody>
  </table>
  <h2>Blocked Items</h2>
  <table>
    <thead>
      <tr><th>Command ID</th><th>Product ID</th><th>Locale</th><th>Eligible</th><th>Reason</th></tr>
    </thead>
    <tbody>{blocked_rows or _empty_row(5, "No blocked items.")}</tbody>
  </table>
  <h2>Safety</h2>
  <ul>
    <li>This task is execution-dry-run-only.</li>
    <li>No command was executed.</li>
    <li>No Shopify writes were performed.</li>
    <li>shopify_write_performed=false.</li>
    <li>apply_performed=false and publish_performed=false.</li>
    <li>translations_register_performed=false.</li>
    <li>Apply, publish, update, mutation, and translationsRegister execution are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _render_simulated_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('simulation_id', '')))}</td>"
        f"<td>{escape(str(item.get('command_id', '')))}</td>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{'true' if item.get('command_executed') else 'false'}</td>"
        f"<td>{escape(str(item.get('would_call_shopify_mutation', '')))}</td>"
        f"<td>{escape(', '.join(item.get('would_apply_fields') or []))}</td>"
        "</tr>"
    )


def _render_blocked_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('command_id', '')))}</td>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{'true' if item.get('eligible_for_command_execution') else 'false'}</td>"
        f"<td>{escape('; '.join(item.get('reason') or []))}</td>"
        "</tr>"
    )


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\" class=\"empty\">{escape(message)}</td></tr>"


def _issue_summary(execution_dry_run_status: str, validation_failures: list[str]) -> str:
    if validation_failures:
        return "Apply execution dry-run failed: " + ", ".join(_unique(validation_failures))
    return f"Apply execution dry-run completed with status {execution_dry_run_status}. No Shopify writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify batch translation apply execution dry-run completed.\n"
        f"Source command validation: {payload.get('source_command_validation_path')}\n"
        f"Execution dry-run status: {payload.get('execution_dry_run_status')}\n"
        f"Command execution allowed: {payload.get('command_execution_allowed')}\n"
        f"Generated commands: {payload.get('generated_command_count')}\n"
        f"Eligible command execution count: {payload.get('eligible_command_execution_count')}\n"
        f"Simulated executions: {payload.get('simulated_execution_count')}\n"
        f"Command executed: {payload.get('command_executed')}\n"
        f"Validation failures: {len(payload.get('validation_failures') or [])}\n"
        "Execution dry-run JSON:\n"
        f"{json_path}\n\n"
        "Execution dry-run HTML:\n"
        f"{html_path}\n"
        "Execution dry-run only. No Shopify writes performed by this task.\n"
        "command_executed=false.\n"
        "shopify_write_performed=false.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep execution dry-run files\n"
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
