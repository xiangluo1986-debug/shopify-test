import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_batch_apply_command_generate"
COMMAND_LABEL = "shopify_translation_batch_apply_command_plan_from_final_validation"
SOURCE_FINAL_VALIDATION_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_final_validation.json"
COMMAND_PLAN_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_command_plan.json"
COMMAND_PLAN_HTML_PATH = LOG_DIR / "shopify_translation_batch_apply_command_plan.html"
EXPECTED_FINAL_VALIDATION_TASK = "shopify_translation_batch_apply_execution_final_validate"
EXPECTED_FINAL_VALIDATION_MODE = "final-validation-only"
MAX_PRODUCTS = 3
MAX_LOCALES = 5
MAX_ITEMS = MAX_PRODUCTS * MAX_LOCALES
FINAL_APPROVED_STATUSES = {"approved", "validated_for_real_apply"}
DEFAULT_FIELDS = ["title", "body_html", "meta_title", "meta_description"]


def run_shopify_translation_batch_apply_command_generate_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_error = ""
    final_validation = {}

    try:
        final_validation = _read_json(SOURCE_FINAL_VALIDATION_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        parse_error = f"Could not parse final validation JSON: {exc}"
        validation_errors.append("final_validation_json_invalid")

    if final_validation:
        validation_errors.extend(_validate_final_validation(final_validation))

    command_result = _build_command_generation_result(final_validation, validation_errors)
    success = not validation_errors
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": "command-generation-only",
        "command_label": COMMAND_LABEL,
        "source_final_validation_path": str(SOURCE_FINAL_VALIDATION_PATH),
        "json_command_plan_path": str(COMMAND_PLAN_JSON_PATH),
        "html_command_plan_path": str(COMMAND_PLAN_HTML_PATH),
        "success": success,
        "command_generation_only": True,
        "preview_only": True,
        "plan_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(final_validation.get("all_no_write_confirmed")) if final_validation else False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "translations_register_performed": False,
        "source_final_validation_task": final_validation.get("task", "") if final_validation else "",
        "source_final_validation_mode": final_validation.get("mode", "") if final_validation else "",
        "source_final_validation_status": final_validation.get("final_validation_status", "")
        if final_validation
        else "",
        "final_apply_allowed": bool(final_validation.get("final_apply_allowed")) if final_validation else False,
        "total_final_validation_items": command_result["total_final_validation_items"],
        "eligible_for_real_apply_count": command_result["eligible_for_real_apply_count"],
        "generated_command_count": len(command_result["commands"]),
        "generated_payload_count": len(command_result["payload_previews"]),
        "command_generation_status": command_result["command_generation_status"],
        "commands": command_result["commands"],
        "payload_previews": command_result["payload_previews"],
        "blocked_items": command_result["blocked_items"],
        "reason": command_result["reason"],
        "validation_errors": validation_errors,
        "parse_error": parse_error,
        "detected_issue_summary": _issue_summary(command_result["command_generation_status"], validation_errors),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
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
        "json_command_plan_path": str(json_path),
        "html_command_plan_path": str(html_path),
        "source_final_validation_path": str(SOURCE_FINAL_VALIDATION_PATH),
        "command_generation_only": True,
        "command_generation_status": payload["command_generation_status"],
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": payload["all_no_write_confirmed"],
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "final_apply_allowed": payload["final_apply_allowed"],
        "total_final_validation_items": payload["total_final_validation_items"],
        "eligible_for_real_apply_count": payload["eligible_for_real_apply_count"],
        "generated_command_count": payload["generated_command_count"],
        "generated_payload_count": payload["generated_payload_count"],
        "blocked_items_count": len(payload["blocked_items"]),
        "validation_errors_count": len(validation_errors),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_final_validation(report: dict) -> list[str]:
    errors = []
    unsafe_checks = [
        ("task", report.get("task") == EXPECTED_FINAL_VALIDATION_TASK),
        ("mode", report.get("mode") == EXPECTED_FINAL_VALIDATION_MODE),
        ("validation_only", report.get("validation_only") is True),
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
            errors.append(f"unsafe_final_validation_report_{name}")

    if "total_preview_items" not in report:
        errors.append("unsafe_final_validation_total_items_missing")
    elif _safe_int(report.get("total_preview_items")) > MAX_ITEMS:
        errors.append("product_or_locale_limit_exceeded")

    for field in ["final_validation_status", "final_apply_allowed", "eligible_for_real_apply_count"]:
        if field not in report:
            errors.append(f"unsafe_final_validation_report_{field}_missing")

    items = report.get("item_validation_results")
    if items is not None and not isinstance(items, list):
        errors.append("unsafe_final_validation_report_items")
    if isinstance(items, list) and len(items) > MAX_ITEMS:
        errors.append("product_or_locale_limit_exceeded")
    return _unique(errors)


def _build_command_generation_result(report: dict, validation_errors: list[str]) -> dict:
    items = report.get("item_validation_results", []) if isinstance(report.get("item_validation_results"), list) else []
    total_items = _safe_int(report.get("total_preview_items"))
    eligible_count = _safe_int(report.get("eligible_for_real_apply_count"))
    final_apply_allowed = report.get("final_apply_allowed") is True
    final_status = str(report.get("final_validation_status", ""))

    if validation_errors:
        return {
            "command_generation_status": "failed",
            "total_final_validation_items": total_items,
            "eligible_for_real_apply_count": eligible_count,
            "commands": [],
            "payload_previews": [],
            "blocked_items": _blocked_items_from_items(items, validation_errors),
            "reason": _unique(validation_errors),
        }

    if not final_apply_allowed:
        return {
            "command_generation_status": "blocked",
            "total_final_validation_items": total_items,
            "eligible_for_real_apply_count": eligible_count,
            "commands": [],
            "payload_previews": [],
            "blocked_items": _blocked_items_from_items(items, ["final_apply_allowed=false"]),
            "reason": [
                "final_apply_allowed=false",
                "final validation has not approved real apply",
                "No items are eligible for real apply.",
            ],
        }

    if final_status not in FINAL_APPROVED_STATUSES:
        return {
            "command_generation_status": "blocked",
            "total_final_validation_items": total_items,
            "eligible_for_real_apply_count": eligible_count,
            "commands": [],
            "payload_previews": [],
            "blocked_items": _blocked_items_from_items(items, [f"final_validation_status={final_status or '<missing>'}"]),
            "reason": [
                f"final_validation_status={final_status or '<missing>'}",
                "final validation has not approved real apply",
            ],
        }

    commands = []
    payload_previews = []
    blocked_items = []
    for index, item in enumerate(items):
        reasons = _item_not_eligible_reasons(item)
        if reasons:
            blocked_items.append(_blocked_item(item, reasons))
            continue
        command = _command_plan_item(item, index)
        payload_preview = _payload_preview_item(item, index)
        commands.append(command)
        payload_previews.append(payload_preview)

    status = "ready" if commands and len(commands) == eligible_count else "blocked"
    reason = []
    if status == "ready":
        reason.append("Command and payload plans generated for final-approved items only.")
    else:
        reason.append("No final-approved items passed command generation checks.")
    return {
        "command_generation_status": status,
        "total_final_validation_items": total_items,
        "eligible_for_real_apply_count": eligible_count,
        "commands": commands,
        "payload_previews": payload_previews,
        "blocked_items": blocked_items,
        "reason": _unique(reason),
    }


def _item_not_eligible_reasons(item: dict) -> list[str]:
    reasons = []
    if item.get("eligible_for_real_apply") is not True:
        reasons.append("eligible_for_real_apply is not true")
    if item.get("final_decision") != "approve":
        reasons.append("final_decision is not approve")
    if item.get("final_approval_ready") is not True:
        reasons.append("final_approval_ready is not true")
    if item.get("manual_decision") != "approve":
        reasons.append("manual_decision is not approve")
    if item.get("validation_status") != "validated_for_future_apply":
        reasons.append("validation_status is not validated_for_future_apply")
    if item.get("shopify_write_performed") is not False:
        reasons.append("shopify_write_performed must be false")
    if item.get("apply_performed") is not False:
        reasons.append("apply_performed must be false")
    if item.get("publish_performed") is not False:
        reasons.append("publish_performed must be false")
    if item.get("translations_register_performed") is not False:
        reasons.append("translations_register_performed must be false")
    if not item.get("product_id"):
        reasons.append("product_id is missing")
    if not item.get("locale"):
        reasons.append("locale is missing")
    fields = _raw_fields_for_item(item)
    if not fields:
        reasons.append("would_apply_fields is missing")
    return _unique(reasons)


def _command_plan_item(item: dict, index: int) -> dict:
    product_id = str(item.get("product_id", ""))
    locale = str(item.get("locale", ""))
    return {
        "command_id": f"future_apply_{index + 1}",
        "product_id": product_id,
        "locale": locale,
        "preview_only": True,
        "command_generation_only": True,
        "executable_in_phase9": False,
        "requires_separate_write_task": True,
        "future_task_required": "A separate explicitly confirmed Shopify write task must be created before execution.",
        "command_preview": f"FUTURE_WRITE_TASK_REQUIRED translationsRegister product_id={product_id} locale={locale}",
        "would_call_shopify_mutation": "translationsRegister",
        "would_apply_fields": _fields_for_item(item),
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _payload_preview_item(item: dict, index: int) -> dict:
    return {
        "payload_id": f"future_payload_{index + 1}",
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "preview_only": True,
        "command_generation_only": True,
        "resource_id": item.get("product_id", ""),
        "would_call_shopify_mutation": "translationsRegister",
        "would_apply_fields": _fields_for_item(item),
        "field_payload_values_included": False,
        "payload_source_trace": [
            str(SOURCE_FINAL_VALIDATION_PATH),
            "reviewed batch dry-run review",
            "manual apply plan",
            "manual apply plan validation",
            "execution preview",
            "final approval validation",
        ],
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _blocked_items_from_items(items: list[dict], reasons: list[str]) -> list[dict]:
    return [_blocked_item(item, reasons) for item in items]


def _blocked_item(item: dict, reasons: list[str]) -> dict:
    return {
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "eligible_for_real_apply": bool(item.get("eligible_for_real_apply")),
        "final_decision": item.get("final_decision", ""),
        "validation_status": item.get("validation_status", ""),
        "reason": _unique(reasons),
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _fields_for_item(item: dict) -> list[str]:
    fields = _raw_fields_for_item(item)
    return fields or DEFAULT_FIELDS[:]


def _raw_fields_for_item(item: dict) -> list[str]:
    return [str(value) for value in item.get("would_apply_fields") or [] if value]


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    COMMAND_PLAN_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(COMMAND_PLAN_JSON_PATH.read_text(encoding="utf-8"))
    return COMMAND_PLAN_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    COMMAND_PLAN_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return COMMAND_PLAN_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    command_rows = "\n".join(_render_command_row(item) for item in payload.get("commands", []))
    payload_rows = "\n".join(_render_payload_row(item) for item in payload.get("payload_previews", []))
    blocked_rows = "\n".join(_render_blocked_row(item) for item in payload.get("blocked_items", []))
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Source Final Validation", "source_final_validation_path"),
            ("Command Generation Status", "command_generation_status"),
            ("Final Apply Allowed", "final_apply_allowed"),
            ("Total Final Validation Items", "total_final_validation_items"),
            ("Eligible For Real Apply", "eligible_for_real_apply_count"),
            ("Generated Command Count", "generated_command_count"),
            ("Generated Payload Count", "generated_payload_count"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("No Shopify Writes Performed", "no_shopify_writes_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Apply Performed", "apply_performed"),
            ("Publish Performed", "publish_performed"),
            ("Translations Register Performed", "translations_register_performed"),
            ("Reason", "reason"),
            ("Validation Errors", "validation_errors"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Translation Apply Command Plan</title>
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
  <h1>Shopify Translation Apply Command Plan</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Generated Command Plans</h2>
  <table>
    <thead>
      <tr>
        <th>Command ID</th><th>Product ID</th><th>Locale</th><th>Executable In Phase 9</th>
        <th>Requires Separate Write Task</th><th>Fields</th><th>Command Preview</th>
      </tr>
    </thead>
    <tbody>{command_rows or _empty_row(7, "No executable or future command plans generated.")}</tbody>
  </table>
  <h2>Payload Previews</h2>
  <table>
    <thead>
      <tr>
        <th>Payload ID</th><th>Product ID</th><th>Locale</th><th>Fields</th>
        <th>Field Values Included</th><th>Would Call</th>
      </tr>
    </thead>
    <tbody>{payload_rows or _empty_row(6, "No payload previews generated.")}</tbody>
  </table>
  <h2>Blocked Items</h2>
  <table>
    <thead>
      <tr><th>Product ID</th><th>Locale</th><th>Eligible</th><th>Final Decision</th><th>Status</th><th>Reason</th></tr>
    </thead>
    <tbody>{blocked_rows or _empty_row(6, "No blocked items.")}</tbody>
  </table>
  <h2>Safety</h2>
  <ul>
    <li>This task is command-generation-only.</li>
    <li>No Shopify writes were performed.</li>
    <li>No command generated by this phase is executed by this task.</li>
    <li>shopify_write_performed=false.</li>
    <li>apply_performed=false and publish_performed=false.</li>
    <li>translations_register_performed=false.</li>
    <li>Apply, publish, update, mutation, and translationsRegister execution are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _render_command_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('command_id', '')))}</td>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{'true' if item.get('executable_in_phase9') else 'false'}</td>"
        f"<td>{'true' if item.get('requires_separate_write_task') else 'false'}</td>"
        f"<td>{escape(', '.join(item.get('would_apply_fields') or []))}</td>"
        f"<td class=\"path\">{escape(str(item.get('command_preview', '')))}</td>"
        "</tr>"
    )


def _render_payload_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(item.get('payload_id', '')))}</td>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(', '.join(item.get('would_apply_fields') or []))}</td>"
        f"<td>{'true' if item.get('field_payload_values_included') else 'false'}</td>"
        f"<td>{escape(str(item.get('would_call_shopify_mutation', '')))}</td>"
        "</tr>"
    )


def _render_blocked_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{'true' if item.get('eligible_for_real_apply') else 'false'}</td>"
        f"<td>{escape(str(item.get('final_decision', '')))}</td>"
        f"<td>{escape(str(item.get('validation_status', '')))}</td>"
        f"<td>{escape('; '.join(item.get('reason') or []))}</td>"
        "</tr>"
    )


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\" class=\"empty\">{escape(message)}</td></tr>"


def _issue_summary(status: str, validation_errors: list[str]) -> str:
    if validation_errors:
        return "Apply command generation failed: " + ", ".join(_unique(validation_errors))
    if status == "blocked":
        return "Apply command generation blocked by final validation. No Shopify writes performed."
    return f"Apply command generation completed with status {status}. No Shopify writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify batch translation apply command plan generated.\n"
        f"Source final validation: {payload.get('source_final_validation_path')}\n"
        f"Command generation status: {payload.get('command_generation_status')}\n"
        f"Final apply allowed: {payload.get('final_apply_allowed')}\n"
        f"Eligible for real apply: {payload.get('eligible_for_real_apply_count')}\n"
        f"Generated commands: {payload.get('generated_command_count')}\n"
        f"Generated payload previews: {payload.get('generated_payload_count')}\n"
        f"Validation errors: {len(payload.get('validation_errors') or [])}\n"
        "Command plan JSON:\n"
        f"{json_path}\n\n"
        "Command plan HTML:\n"
        f"{html_path}\n"
        "Command generation only. No Shopify writes performed by this task.\n"
        "shopify_write_performed=false.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep command plan files\n"
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
