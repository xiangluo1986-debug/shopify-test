import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_batch_apply_command_validate"
COMMAND_LABEL = "shopify_translation_batch_apply_command_approval_validation"
SOURCE_COMMAND_PLAN_PATH = LOG_DIR / "shopify_translation_batch_apply_command_plan.json"
COMMAND_VALIDATION_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_command_validation.json"
COMMAND_VALIDATION_HTML_PATH = LOG_DIR / "shopify_translation_batch_apply_command_validation.html"
EXPECTED_COMMAND_PLAN_TASK = "shopify_translation_batch_apply_command_generate"
EXPECTED_COMMAND_PLAN_MODE = "command-generation-only"
MAX_PRODUCTS = 3
MAX_LOCALES = 5
MAX_ITEMS = MAX_PRODUCTS * MAX_LOCALES
ALLOWED_COMMAND_APPROVAL_STATUSES = ["pending", "approved", "rejected"]
SHOPIFY_TOKEN_PREFIX_PATTERN = re.escape("sh" + "pat_") + r"[A-Za-z0-9_]+"
SECRET_MARKER_RE = re.compile(
    r"(access[_\s-]?token|api[_\s-]?key|password|credential|secret|" + SHOPIFY_TOKEN_PREFIX_PATTERN + r")",
    re.IGNORECASE,
)


def run_shopify_translation_batch_apply_command_validate_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_error = ""
    command_plan = {}

    try:
        command_plan = _read_json(SOURCE_COMMAND_PLAN_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        parse_error = f"Could not parse command plan JSON: {exc}"
        validation_errors.append("command_plan_json_invalid")

    if command_plan:
        errors, warnings = _validate_command_plan(command_plan)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)

    command_result = _command_validation_result(command_plan, validation_errors)
    validation_failures = _unique(validation_errors + command_result["validation_failures"])
    validation_warnings = _unique(validation_warnings + command_result["validation_warnings"])
    success = not validation_failures
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": "command-validation-only",
        "command_label": COMMAND_LABEL,
        "source_command_plan_path": str(SOURCE_COMMAND_PLAN_PATH),
        "json_command_validation_path": str(COMMAND_VALIDATION_JSON_PATH),
        "html_command_validation_path": str(COMMAND_VALIDATION_HTML_PATH),
        "success": success,
        "command_validation_only": True,
        "command_generation_only": True,
        "preview_only": True,
        "plan_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(command_plan.get("all_no_write_confirmed")) if command_plan else False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "translations_register_performed": False,
        "source_command_plan_task": command_plan.get("task", "") if command_plan else "",
        "source_command_plan_mode": command_plan.get("mode", "") if command_plan else "",
        "source_command_generation_status": command_plan.get("command_generation_status", "")
        if command_plan
        else "",
        "command_approval_summary": command_plan.get("command_approval_summary", {}) if command_plan else {},
        "command_validation_status": command_result["command_validation_status"],
        "command_execution_allowed": command_result["command_execution_allowed"],
        "generated_command_count": command_result["generated_command_count"],
        "generated_payload_count": command_result["generated_payload_count"],
        "eligible_command_execution_count": command_result["eligible_command_execution_count"],
        "blocked_count": command_result["blocked_count"],
        "pending_count": command_result["pending_count"],
        "rejected_count": command_result["rejected_count"],
        "command_validation_items": command_result["command_validation_items"],
        "validation_failures": validation_failures,
        "validation_warnings": validation_warnings,
        "parse_error": parse_error,
        "detected_issue_summary": _issue_summary(command_result["command_validation_status"], validation_failures),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
            "command_validation_only": True,
            "command_generation_only": True,
            "preview_only": True,
            "plan_only": True,
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
        "json_command_validation_path": str(json_path),
        "html_command_validation_path": str(html_path),
        "source_command_plan_path": str(SOURCE_COMMAND_PLAN_PATH),
        "command_validation_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": payload["all_no_write_confirmed"],
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "command_validation_status": payload["command_validation_status"],
        "command_execution_allowed": payload["command_execution_allowed"],
        "generated_command_count": payload["generated_command_count"],
        "generated_payload_count": payload["generated_payload_count"],
        "eligible_command_execution_count": payload["eligible_command_execution_count"],
        "blocked_count": payload["blocked_count"],
        "pending_count": payload["pending_count"],
        "validation_failures_count": len(validation_failures),
        "validation_warnings_count": len(validation_warnings),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_command_plan(plan: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    unsafe_checks = [
        ("task", plan.get("task") == EXPECTED_COMMAND_PLAN_TASK),
        ("mode", plan.get("mode") == EXPECTED_COMMAND_PLAN_MODE),
        ("apply_performed", plan.get("apply_performed") is False),
        ("publish_performed", plan.get("publish_performed") is False),
        ("translations_register_performed", plan.get("translations_register_performed") is False),
        ("shopify_write_performed", plan.get("shopify_write_performed") is False),
        ("no_shopify_writes_performed", plan.get("no_shopify_writes_performed") is True),
        ("all_no_write_confirmed", plan.get("all_no_write_confirmed") is True),
    ]
    for name, passed in unsafe_checks:
        if passed:
            continue
        if name in {"apply_performed", "publish_performed", "translations_register_performed"}:
            errors.append("apply_or_publish_already_performed")
        elif name in {"shopify_write_performed", "no_shopify_writes_performed", "all_no_write_confirmed"}:
            errors.append("no_write_not_confirmed")
        else:
            errors.append(f"unsafe_command_plan_{name}")

    if "generated_command_count" not in plan or "generated_payload_count" not in plan:
        errors.append("unsafe_command_plan_count_missing")

    commands = plan.get("commands")
    payload_previews = plan.get("payload_previews")
    if not isinstance(commands, list):
        errors.append("unsafe_command_plan_commands")
        commands = []
    if not isinstance(payload_previews, list):
        errors.append("unsafe_command_plan_payload_previews")
        payload_previews = []

    if _safe_int(plan.get("generated_command_count")) != len(commands) or _safe_int(
        plan.get("generated_payload_count")
    ) != len(payload_previews):
        errors.append("unsafe_command_plan_count_mismatch")

    if len(commands) > MAX_ITEMS or len(payload_previews) > MAX_ITEMS:
        errors.append("product_or_locale_limit_exceeded")

    product_count = len({str(item.get("product_id", "")) for item in commands if item.get("product_id")})
    locale_count = len({str(item.get("locale", "")) for item in commands if item.get("locale")})
    if product_count > MAX_PRODUCTS or locale_count > MAX_LOCALES:
        errors.append("product_or_locale_limit_exceeded")

    approval_summary = plan.get("command_approval_summary")
    if not isinstance(approval_summary, dict):
        errors.append("command_approval_missing")
    else:
        status = str(approval_summary.get("command_approval_status", ""))
        if status not in ALLOWED_COMMAND_APPROVAL_STATUSES:
            errors.append("invalid_command_approval_status")
        if approval_summary.get("command_execution_allowed") is True:
            warnings.append("source command_execution_allowed was true; command validation recomputed it")

    if _has_secret_in_command_text(commands):
        errors.append("secret_in_command_preview")

    return _unique(errors), _unique(warnings)


def _command_validation_result(plan: dict, validation_errors: list[str]) -> dict:
    commands = plan.get("commands", []) if isinstance(plan.get("commands"), list) else []
    payload_previews = plan.get("payload_previews", []) if isinstance(plan.get("payload_previews"), list) else []
    approval_summary = plan.get("command_approval_summary", {}) if isinstance(
        plan.get("command_approval_summary"), dict
    ) else {}
    approval_status = str(approval_summary.get("command_approval_status", "pending"))
    approved_by = str(approval_summary.get("command_approved_by", "") or "").strip()
    item_results = [_validate_command_item(item) for item in commands]
    item_failures = [
        f"{item.get('command_id', '')}: {failure}"
        for item in item_results
        for failure in item.get("validation_failures", [])
    ]
    validation_failures = []
    validation_warnings = []
    command_validation_status = "blocked"
    command_execution_allowed = False
    eligible_count = 0
    blocked_count = 0
    pending_count = 0
    rejected_count = 0

    if validation_errors:
        command_validation_status = "blocked"
        blocked_count = len(commands)
    elif approval_status == "pending":
        command_validation_status = "pending"
        pending_count = len(commands)
    elif approval_status == "rejected":
        command_validation_status = "rejected"
        rejected_count = len(commands)
    elif approval_status == "approved":
        if not approved_by:
            validation_failures.append("command_approval_status=approved requires command_approved_by")
        if len(commands) == 0:
            validation_failures.append("command_approval_status=approved requires generated_command_count > 0")
        validation_failures.extend(item_failures)
        if validation_failures:
            command_validation_status = "blocked"
            blocked_count = max(len(commands), 1)
        else:
            command_validation_status = "validated_for_future_command_execution"
            command_execution_allowed = True
            eligible_count = len(commands)
    else:
        validation_failures.append("invalid_command_approval_status")
        command_validation_status = "blocked"
        blocked_count = len(commands)

    return {
        "command_validation_status": command_validation_status,
        "command_execution_allowed": command_execution_allowed,
        "generated_command_count": len(commands),
        "generated_payload_count": len(payload_previews),
        "eligible_command_execution_count": eligible_count,
        "blocked_count": blocked_count,
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "command_validation_items": item_results,
        "validation_failures": _unique(validation_failures),
        "validation_warnings": _unique(validation_warnings),
    }


def _validate_command_item(item: dict) -> dict:
    failures = []
    command_text = _command_text(item)
    if item.get("command_decision") != "approve":
        failures.append("command_decision must be approve")
    if item.get("command_approval_ready") is not True:
        failures.append("command_approval_ready must be true")
    if item.get("preview_only") is not True:
        failures.append("preview_only must be true")
    if item.get("shopify_write_performed") is not False:
        failures.append("shopify_write_performed must be false")
    if item.get("apply_performed") is not False:
        failures.append("apply_performed must be false")
    if item.get("publish_performed") is not False:
        failures.append("publish_performed must be false")
    if item.get("translations_register_performed") is not False:
        failures.append("translations_register_performed must be false")
    if _contains_secret_marker(command_text):
        failures.append("command preview contains secret-like marker")
    if item.get("would_call_shopify_mutation") and item.get("would_call_shopify_mutation") != "translationsRegister":
        failures.append("would_call_shopify_mutation must only be translationsRegister text")
    if not item.get("product_id"):
        failures.append("product_id is missing")
    if not item.get("locale"):
        failures.append("locale is missing")

    return {
        "command_id": item.get("command_id", ""),
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "command_decision": item.get("command_decision", ""),
        "command_approval_ready": bool(item.get("command_approval_ready")),
        "preview_only": bool(item.get("preview_only")),
        "would_call_shopify_mutation": item.get("would_call_shopify_mutation", ""),
        "eligible_for_future_execution": not failures,
        "validation_failures": failures,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _has_secret_in_command_text(commands: list[dict]) -> bool:
    return any(_contains_secret_marker(_command_text(item)) for item in commands)


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
    COMMAND_VALIDATION_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(COMMAND_VALIDATION_JSON_PATH.read_text(encoding="utf-8"))
    return COMMAND_VALIDATION_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    COMMAND_VALIDATION_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return COMMAND_VALIDATION_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    item_rows = "\n".join(_render_item_row(item) for item in payload.get("command_validation_items", []))
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Source Command Plan", "source_command_plan_path"),
            ("Command Validation Status", "command_validation_status"),
            ("Command Execution Allowed", "command_execution_allowed"),
            ("Generated Command Count", "generated_command_count"),
            ("Generated Payload Count", "generated_payload_count"),
            ("Eligible Command Execution Count", "eligible_command_execution_count"),
            ("Blocked Count", "blocked_count"),
            ("Pending Count", "pending_count"),
            ("Rejected Count", "rejected_count"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("No Shopify Writes Performed", "no_shopify_writes_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Apply Performed", "apply_performed"),
            ("Publish Performed", "publish_performed"),
            ("Translations Register Performed", "translations_register_performed"),
            ("Validation Failures", "validation_failures"),
            ("Validation Warnings", "validation_warnings"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Translation Command Approval Validation</title>
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
  <h1>Shopify Translation Command Approval Validation</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Command Item Validation</h2>
  <table>
    <thead>
      <tr>
        <th>Command ID</th><th>Product ID</th><th>Locale</th><th>Decision</th>
        <th>Ready</th><th>Preview Only</th><th>Would Call</th><th>Eligible</th><th>Failures</th>
      </tr>
    </thead>
    <tbody>{item_rows or _empty_row(9, "No command items to validate.")}</tbody>
  </table>
  <h2>Safety</h2>
  <ul>
    <li>This task is command-validation-only.</li>
    <li>No Shopify writes were performed.</li>
    <li>No command was executed by this task.</li>
    <li>shopify_write_performed=false.</li>
    <li>apply_performed=false and publish_performed=false.</li>
    <li>translations_register_performed=false.</li>
    <li>Apply, publish, update, mutation, and translationsRegister execution are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _render_item_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('command_id', '')))}</td>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('command_decision', '')))}</td>"
        f"<td>{'true' if item.get('command_approval_ready') else 'false'}</td>"
        f"<td>{'true' if item.get('preview_only') else 'false'}</td>"
        f"<td>{escape(str(item.get('would_call_shopify_mutation', '')))}</td>"
        f"<td>{'true' if item.get('eligible_for_future_execution') else 'false'}</td>"
        f"<td>{escape('; '.join(item.get('validation_failures') or []))}</td>"
        "</tr>"
    )


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\" class=\"empty\">{escape(message)}</td></tr>"


def _issue_summary(command_validation_status: str, validation_failures: list[str]) -> str:
    if validation_failures:
        return "Command approval validation blocked: " + ", ".join(_unique(validation_failures))
    return f"Command approval validation completed with status {command_validation_status}. No Shopify writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify batch translation command approval validation completed.\n"
        f"Source command plan: {payload.get('source_command_plan_path')}\n"
        f"Command validation status: {payload.get('command_validation_status')}\n"
        f"Command execution allowed: {payload.get('command_execution_allowed')}\n"
        f"Generated commands: {payload.get('generated_command_count')}\n"
        f"Eligible command execution count: {payload.get('eligible_command_execution_count')}\n"
        f"Validation failures: {len(payload.get('validation_failures') or [])}\n"
        "Command validation JSON:\n"
        f"{json_path}\n\n"
        "Command validation HTML:\n"
        f"{html_path}\n"
        "Command validation only. No Shopify writes performed by this task.\n"
        "shopify_write_performed=false.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep command validation files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Write, publish, apply, update, mutation, translationsRegister, commit, and push are not allowed."
    )


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
