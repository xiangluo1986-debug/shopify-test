import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_batch_apply_execution_preview"
COMMAND_LABEL = "shopify_translation_batch_apply_execution_preview_from_validation"
VALIDATION_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_plan_validation.json"
APPLY_PLAN_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_plan.json"
PREVIEW_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_preview.json"
PREVIEW_HTML_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_preview.html"
EXPECTED_VALIDATION_TASK = "shopify_translation_batch_apply_plan_validate"
REQUIRED_MODE = "dry-run"
MAX_PRODUCTS = 3
MAX_LOCALES = 5
MAX_ITEMS = MAX_PRODUCTS * MAX_LOCALES
EXPECTED_FIELDS = ["title", "body_html", "meta_title", "meta_description"]
READY_RECOMMENDATIONS = {"ready_for_human_approval", "ready_for_apply"}
FINAL_APPROVAL_ALLOWED_VALUES = ["pending", "approved", "rejected"]
DEFAULT_FINAL_APPROVAL_STATUS = "pending"


def run_shopify_translation_batch_apply_execution_preview_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_parse_error = ""
    validation_report = {}
    source_plan = {}

    try:
        validation_report = _read_json(VALIDATION_JSON_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        validation_parse_error = f"Could not parse validation JSON: {exc}"
        validation_errors.append("validation_json_invalid")

    if validation_report:
        validation_errors.extend(_validate_validation_report(validation_report))
        source_plan = _read_optional_source_plan(validation_report.get("source_apply_plan_path", ""))

    validation_items = (
        validation_report.get("items", []) if isinstance(validation_report.get("items"), list) else []
    )
    plan_item_index = _plan_item_index(source_plan)
    preview_apply_items = []
    not_apply_items = []
    if validation_report and not validation_errors:
        for item in validation_items:
            plan_item = plan_item_index.get(_item_key(item), {})
            preview_item, reasons = _preview_or_not_apply_item(item, plan_item)
            if preview_item:
                preview_apply_items.append(preview_item)
            else:
                not_apply_items.append(_not_apply_item(item, reasons, plan_item))

    end_time = utc_now_iso()
    final_approval_summary = _final_approval_summary()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "source_validation_path": str(VALIDATION_JSON_PATH),
        "source_apply_plan_path": str(APPLY_PLAN_JSON_PATH),
        "json_preview_path": str(PREVIEW_JSON_PATH),
        "html_preview_path": str(PREVIEW_HTML_PATH),
        "success": not validation_errors,
        "preview_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(validation_report.get("all_no_write_confirmed"))
        if validation_report
        else False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "translations_register_performed": False,
        "source_validation_task": validation_report.get("task", "") if validation_report else "",
        "source_validation_mode": validation_report.get("mode", "") if validation_report else "",
        "source_validation_success": bool(validation_report.get("success")) if validation_report else False,
        "product_count": _product_count(validation_report, validation_items) if validation_report else 0,
        "locale_count": _locale_count(validation_report, validation_items) if validation_report else 0,
        "total_items": len(validation_items),
        "validated_for_future_apply_count": validation_report.get("validated_for_future_apply_count", 0)
        if validation_report
        else 0,
        "preview_apply_count": len(preview_apply_items),
        "not_apply_count": len(not_apply_items),
        "final_approval_summary": final_approval_summary,
        "final_approval_required": final_approval_summary["final_approval_required"],
        "final_approval_status": final_approval_summary["final_approval_status"],
        "final_approval_ready_count": final_approval_summary["final_approval_ready_count"],
        "final_apply_allowed": final_approval_summary["final_apply_allowed"],
        "preview_apply_items": preview_apply_items,
        "not_apply_items": not_apply_items,
        "validation_errors": validation_errors,
        "validation_parse_error": validation_parse_error,
        "detected_issue_summary": _issue_summary(validation_errors, preview_apply_items, not_apply_items),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
            "preview_only": True,
            "validation_only": True,
            "plan_only": True,
            "dry_run_only": True,
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
    json_preview_path = _write_json_preview(payload)
    html_preview_path = _write_html_preview(payload)
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_preview_path),
        "json_preview_path": str(json_preview_path),
        "html_preview_path": str(html_preview_path),
        "source_validation_path": str(VALIDATION_JSON_PATH),
        "preview_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": payload["all_no_write_confirmed"],
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "total_items": len(validation_items),
        "preview_apply_count": len(preview_apply_items),
        "not_apply_count": len(not_apply_items),
        "final_approval_status": final_approval_summary["final_approval_status"],
        "final_approval_required": final_approval_summary["final_approval_required"],
        "final_approval_ready_count": final_approval_summary["final_approval_ready_count"],
        "final_apply_allowed": final_approval_summary["final_apply_allowed"],
        "validation_errors_count": len(validation_errors),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_preview_path, html_preview_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_optional_source_plan(path_value: str) -> dict:
    candidates = []
    if path_value:
        candidates.append(Path(path_value))
    candidates.append(APPLY_PLAN_JSON_PATH)
    for path in candidates:
        try:
            if path.exists():
                return _read_json(path)
        except (OSError, json.JSONDecodeError):
            continue
    return {}


def _validate_validation_report(report: dict) -> list[str]:
    errors = []
    unsafe_checks = [
        ("task", report.get("task") == EXPECTED_VALIDATION_TASK),
        ("mode", report.get("mode") == REQUIRED_MODE),
        ("validation_only", report.get("validation_only") is True),
        ("apply_performed", report.get("apply_performed") is False),
        ("publish_performed", report.get("publish_performed") is False),
        ("translations_register_performed", report.get("translations_register_performed") is False),
        ("no_shopify_writes_performed", report.get("no_shopify_writes_performed") is True),
        ("all_no_write_confirmed", report.get("all_no_write_confirmed") is True),
    ]
    for name, passed in unsafe_checks:
        if passed:
            continue
        if name in {"apply_performed", "publish_performed", "translations_register_performed"}:
            errors.append("apply_or_publish_already_performed")
        elif name in {"no_shopify_writes_performed", "all_no_write_confirmed"}:
            errors.append("no_write_not_confirmed")
        else:
            errors.append(f"unsafe_validation_report_{name}")

    items = report.get("items")
    if not isinstance(items, list):
        errors.append("unsafe_validation_report_items")
        items = []
    if "validated_for_future_apply_count" not in report:
        errors.append("unsafe_validation_report_validated_count_missing")
    product_count = _product_count(report, items)
    locale_count = _locale_count(report, items)
    if product_count > MAX_PRODUCTS or locale_count > MAX_LOCALES or len(items) > MAX_ITEMS:
        errors.append("product_or_locale_limit_exceeded")
    for item in items:
        missing = [
            field
            for field in [
                "product_id",
                "locale",
                "validation_status",
                "eligible_for_future_apply",
                "manual_decision",
                "recommendation",
                "qa_status",
            ]
            if field not in item
        ]
        if missing:
            errors.append("unsafe_validation_report_item_missing_fields")
            break
    return _unique(errors)


def _preview_or_not_apply_item(item: dict, plan_item: dict) -> tuple[dict | None, list[str]]:
    reasons = _not_apply_reasons(item)
    if reasons:
        return None, reasons
    fields = _fields_for_item(plan_item)
    return {
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "manual_decision": item.get("manual_decision", ""),
        "validation_status": item.get("validation_status", ""),
        "eligible_for_future_apply": bool(item.get("eligible_for_future_apply")),
        "recommendation": item.get("recommendation", ""),
        "qa_status": item.get("qa_status", ""),
        "preview_only": True,
        "would_apply_fields": fields,
        "would_call_shopify_mutation": "translationsRegister",
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "no_shopify_writes_confirmed": bool(item.get("no_shopify_writes_confirmed")),
        "review_file_path": item.get("review_file_path", ""),
    }, []


def _not_apply_reasons(item: dict) -> list[str]:
    reasons = []
    if item.get("manual_decision") != "approve":
        reasons.append(f"manual_decision is {item.get('manual_decision') or '<missing>'}")
    if item.get("validation_status") != "validated_for_future_apply":
        reasons.append(f"validation_status is {item.get('validation_status') or '<missing>'}")
    if item.get("eligible_for_future_apply") is not True:
        reasons.append("eligible_for_future_apply is not true")
    if item.get("qa_status") != "pass":
        reasons.append(f"qa_status is {item.get('qa_status') or '<missing>'}")
    if item.get("recommendation") not in READY_RECOMMENDATIONS:
        reasons.append(f"recommendation is {item.get('recommendation') or '<missing>'}")
    if item.get("no_shopify_writes_confirmed") is not True:
        reasons.append("no_shopify_writes_confirmed is not true")
    if item.get("validation_failures"):
        reasons.append("validation_failures is not empty")
    return _unique(reasons)


def _not_apply_item(item: dict, reasons: list[str], plan_item: dict) -> dict:
    return {
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "manual_decision": item.get("manual_decision", ""),
        "validation_status": item.get("validation_status", ""),
        "eligible_for_future_apply": bool(item.get("eligible_for_future_apply")),
        "recommendation": item.get("recommendation", ""),
        "qa_status": item.get("qa_status", ""),
        "preview_only": True,
        "not_apply_reason": reasons,
        "would_apply_fields_if_approved": _fields_for_item(plan_item),
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "no_shopify_writes_confirmed": bool(item.get("no_shopify_writes_confirmed")),
        "review_file_path": item.get("review_file_path", ""),
    }


def _final_approval_summary() -> dict:
    return {
        "final_approval_required": True,
        "final_approval_status": DEFAULT_FINAL_APPROVAL_STATUS,
        "final_approval_allowed_values": FINAL_APPROVAL_ALLOWED_VALUES,
        "final_approved_by": "",
        "final_approval_notes": "",
        "final_approval_ready_count": 0,
        "final_apply_allowed": False,
    }


def _plan_item_index(plan: dict) -> dict[tuple[str, str], dict]:
    items = plan.get("plan_items", []) if isinstance(plan.get("plan_items"), list) else []
    return {_item_key(item): item for item in items}


def _item_key(item: dict) -> tuple[str, str]:
    return (str(item.get("product_id", "")), str(item.get("locale", "")))


def _fields_for_item(plan_item: dict) -> list[str]:
    fields = [str(value) for value in plan_item.get("fields_included") or [] if value]
    if not fields:
        fields = [str(value) for value in plan_item.get("expected_fields") or [] if value]
    return fields or EXPECTED_FIELDS[:]


def _product_count(report: dict, items: list[dict]) -> int:
    explicit = report.get("product_count")
    try:
        explicit_count = int(explicit)
    except (TypeError, ValueError):
        explicit_count = 0
    if explicit_count:
        return explicit_count
    return len({str(item.get("product_id", "")) for item in items if item.get("product_id")})


def _locale_count(report: dict, items: list[dict]) -> int:
    explicit = report.get("locale_count")
    try:
        explicit_count = int(explicit)
    except (TypeError, ValueError):
        explicit_count = 0
    if explicit_count:
        return explicit_count
    return len({str(item.get("locale", "")) for item in items if item.get("locale")})


def _write_json_preview(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    PREVIEW_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(PREVIEW_JSON_PATH.read_text(encoding="utf-8"))
    return PREVIEW_JSON_PATH


def _write_html_preview(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PREVIEW_HTML_PATH.write_text(_render_html_preview(payload), encoding="utf-8")
    return PREVIEW_HTML_PATH


def _render_html_preview(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    preview_rows = "\n".join(_render_preview_row(item) for item in payload.get("preview_apply_items", []))
    not_apply_rows = "\n".join(_render_not_apply_row(item) for item in payload.get("not_apply_items", []))
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Timestamp", "timestamp"),
            ("Source Validation", "source_validation_path"),
            ("Source Apply Plan", "source_apply_plan_path"),
            ("Product Count", "product_count"),
            ("Locale Count", "locale_count"),
            ("Total Items", "total_items"),
            ("Validated For Future Apply", "validated_for_future_apply_count"),
            ("Preview Apply Count", "preview_apply_count"),
            ("Not Apply Count", "not_apply_count"),
            ("Final Approval Required", "final_approval_required"),
            ("Final Approval Status", "final_approval_status"),
            ("Final Approval Ready Count", "final_approval_ready_count"),
            ("Final Apply Allowed", "final_apply_allowed"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("No Shopify Writes Performed", "no_shopify_writes_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Apply Performed", "apply_performed"),
            ("Publish Performed", "publish_performed"),
            ("Translations Register Performed", "translations_register_performed"),
            ("Validation Errors", "validation_errors"),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Translation Apply Execution Preview</title>
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
  <h1>Shopify Translation Apply Execution Preview</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Final Approval Template</h2>
  { _render_final_approval_summary(payload.get("final_approval_summary", {})) }
  <h2>Would Apply Items</h2>
  <table>
    <thead>
      <tr>
        <th>Product ID</th><th>Locale</th><th>Manual Decision</th><th>Validation Status</th>
        <th>Would Apply Fields</th><th>Would Call</th><th>Write Performed</th><th>Review File</th>
      </tr>
    </thead>
    <tbody>{preview_rows or _empty_row(8, "No items are approved for future apply preview.")}</tbody>
  </table>
  <h2>Not Apply Items</h2>
  <table>
    <thead>
      <tr>
        <th>Product ID</th><th>Locale</th><th>Manual Decision</th><th>Validation Status</th>
        <th>Recommendation</th><th>QA Status</th><th>Reasons</th><th>Fields If Approved</th>
      </tr>
    </thead>
    <tbody>{not_apply_rows or _empty_row(8, "No excluded items.")}</tbody>
  </table>
  <h2>Safety</h2>
  <ul>
    <li>This task is preview-only.</li>
    <li>No Shopify writes were performed.</li>
    <li>shopify_write_performed=false.</li>
    <li>apply_performed=false and publish_performed=false.</li>
    <li>translations_register_performed=false.</li>
    <li>Apply, publish, update, mutation, and translationsRegister are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _render_preview_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('manual_decision', '')))}</td>"
        f"<td>{escape(str(item.get('validation_status', '')))}</td>"
        f"<td>{escape(', '.join(item.get('would_apply_fields') or []))}</td>"
        f"<td>{escape(str(item.get('would_call_shopify_mutation', '')))}</td>"
        f"<td>{'true' if item.get('shopify_write_performed') else 'false'}</td>"
        f"<td>{_link_for_path(item.get('review_file_path', ''))}</td>"
        "</tr>"
    )


def _render_not_apply_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('manual_decision', '')))}</td>"
        f"<td>{escape(str(item.get('validation_status', '')))}</td>"
        f"<td>{escape(str(item.get('recommendation', '')))}</td>"
        f"<td>{escape(str(item.get('qa_status', '')))}</td>"
        f"<td>{escape('; '.join(item.get('not_apply_reason') or []))}</td>"
        f"<td>{escape(', '.join(item.get('would_apply_fields_if_approved') or []))}</td>"
        "</tr>"
    )


def _render_final_approval_summary(summary: dict) -> str:
    rows = "\n".join(
        _summary_row(label, summary.get(key))
        for label, key in [
            ("Final Approval Required", "final_approval_required"),
            ("Final Approval Status", "final_approval_status"),
            ("Allowed Values", "final_approval_allowed_values"),
            ("Final Approved By", "final_approved_by"),
            ("Final Approval Notes", "final_approval_notes"),
            ("Final Approval Ready Count", "final_approval_ready_count"),
            ("Final Apply Allowed", "final_apply_allowed"),
        ]
    )
    return (
        "<table><tbody>"
        f"{rows}"
        "</tbody></table>"
        "<p>The final approval template is review-only. Editing it does not write to Shopify.</p>"
    )


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\" class=\"empty\">{escape(message)}</td></tr>"


def _link_for_path(path: str) -> str:
    if not path:
        return ""
    label = _project_relative_path(path)
    href = _html_relative_href(path)
    return f"<a class=\"path\" href=\"{escape(href)}\">{escape(label)}</a>"


def _project_relative_path(path: str) -> str:
    try:
        absolute = Path(path)
        if not absolute.is_absolute():
            absolute = PROJECT_ROOT / absolute
        return absolute.resolve().relative_to(PROJECT_ROOT).as_posix()
    except (OSError, ValueError):
        return str(path).replace("\\", "/")


def _html_relative_href(path: str) -> str:
    try:
        absolute = Path(path)
        if not absolute.is_absolute():
            absolute = PROJECT_ROOT / absolute
        return absolute.resolve().relative_to(PREVIEW_HTML_PATH.parent.resolve()).as_posix()
    except (OSError, ValueError):
        return _project_relative_path(path)


def _issue_summary(validation_errors: list[str], preview_items: list[dict], not_apply_items: list[dict]) -> str:
    if validation_errors:
        return "Apply execution preview failed: " + ", ".join(_unique(validation_errors))
    return (
        "Apply execution preview generated. "
        f"Would apply: {len(preview_items)}, not apply: {len(not_apply_items)}. "
        "Preview only; no Shopify writes performed."
    )


def _build_approval_message(payload: dict, json_preview_path: Path, html_preview_path: Path) -> str:
    return (
        "Shopify batch translation apply execution preview generated.\n"
        f"Source validation: {payload.get('source_validation_path')}\n"
        f"Total items: {payload.get('total_items')}\n"
        f"Preview apply items: {payload.get('preview_apply_count')}\n"
        f"Not apply items: {payload.get('not_apply_count')}\n"
        f"Final approval status: {payload.get('final_approval_summary', {}).get('final_approval_status')}\n"
        f"Final apply allowed: {payload.get('final_approval_summary', {}).get('final_apply_allowed')}\n"
        f"Validation errors: {len(payload.get('validation_errors') or [])}\n"
        "Preview JSON:\n"
        f"{json_preview_path}\n\n"
        "Preview HTML:\n"
        f"{html_preview_path}\n"
        "Preview only. No Shopify writes performed by this task.\n"
        "shopify_write_performed=false.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep preview files\n"
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
