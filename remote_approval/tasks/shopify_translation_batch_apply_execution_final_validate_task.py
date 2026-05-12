import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_batch_apply_execution_final_validate"
COMMAND_LABEL = "shopify_translation_batch_apply_execution_final_validation"
SOURCE_PREVIEW_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_preview.json"
FINAL_VALIDATION_JSON_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_final_validation.json"
FINAL_VALIDATION_HTML_PATH = LOG_DIR / "shopify_translation_batch_apply_execution_final_validation.html"
EXPECTED_PREVIEW_TASK = "shopify_translation_batch_apply_execution_preview"
MAX_PRODUCTS = 3
MAX_LOCALES = 5
MAX_ITEMS = MAX_PRODUCTS * MAX_LOCALES
ALLOWED_FINAL_APPROVAL_STATUSES = ["pending", "approved", "rejected"]


def run_shopify_translation_batch_apply_execution_final_validate_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_error = ""
    preview = {}

    try:
        preview = _read_json(SOURCE_PREVIEW_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        parse_error = f"Could not parse execution preview JSON: {exc}"
        validation_errors.append("execution_preview_json_invalid")

    if preview:
        errors, warnings = _validate_execution_preview(preview)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)

    final_result = _final_validation_result(preview, validation_errors)
    validation_failures = _unique(validation_errors + final_result["validation_failures"])
    validation_warnings = _unique(validation_warnings + final_result["validation_warnings"])
    success = not validation_failures
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": "final-validation-only",
        "command_label": COMMAND_LABEL,
        "source_preview_path": str(SOURCE_PREVIEW_PATH),
        "json_final_validation_path": str(FINAL_VALIDATION_JSON_PATH),
        "html_final_validation_path": str(FINAL_VALIDATION_HTML_PATH),
        "success": success,
        "validation_only": True,
        "preview_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(preview.get("all_no_write_confirmed")) if preview else False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "translations_register_performed": False,
        "source_preview_task": preview.get("task", "") if preview else "",
        "source_preview_mode": preview.get("mode", "") if preview else "",
        "source_preview_only": bool(preview.get("preview_only")) if preview else False,
        "final_approval_summary": preview.get("final_approval_summary", {}) if preview else {},
        "final_validation_status": final_result["final_validation_status"],
        "final_apply_allowed": final_result["final_apply_allowed"],
        "total_preview_items": final_result["total_preview_items"],
        "preview_apply_count": final_result["preview_apply_count"],
        "not_apply_count": final_result["not_apply_count"],
        "eligible_for_real_apply_count": final_result["eligible_for_real_apply_count"],
        "blocked_count": final_result["blocked_count"],
        "pending_count": final_result["pending_count"],
        "rejected_count": final_result["rejected_count"],
        "item_validation_results": final_result["item_validation_results"],
        "validation_failures": validation_failures,
        "validation_warnings": validation_warnings,
        "parse_error": parse_error,
        "detected_issue_summary": _issue_summary(final_result["final_validation_status"], validation_failures),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
            "final_validation_only": True,
            "validation_only": True,
            "preview_only": True,
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
        "json_final_validation_path": str(json_path),
        "html_final_validation_path": str(html_path),
        "source_preview_path": str(SOURCE_PREVIEW_PATH),
        "validation_only": True,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": payload["all_no_write_confirmed"],
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "final_validation_status": payload["final_validation_status"],
        "final_apply_allowed": payload["final_apply_allowed"],
        "eligible_for_real_apply_count": payload["eligible_for_real_apply_count"],
        "preview_apply_count": payload["preview_apply_count"],
        "not_apply_count": payload["not_apply_count"],
        "total_preview_items": payload["total_preview_items"],
        "blocked_count": payload["blocked_count"],
        "pending_count": payload["pending_count"],
        "validation_failures_count": len(validation_failures),
        "validation_warnings_count": len(validation_warnings),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_execution_preview(preview: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    unsafe_checks = [
        ("task", preview.get("task") == EXPECTED_PREVIEW_TASK),
        ("preview_only", preview.get("preview_only") is True),
        ("apply_performed", preview.get("apply_performed") is False),
        ("publish_performed", preview.get("publish_performed") is False),
        ("translations_register_performed", preview.get("translations_register_performed") is False),
        ("shopify_write_performed", preview.get("shopify_write_performed") is False),
        ("no_shopify_writes_performed", preview.get("no_shopify_writes_performed") is True),
        ("all_no_write_confirmed", preview.get("all_no_write_confirmed") is True),
    ]
    for name, passed in unsafe_checks:
        if passed:
            continue
        if name in {"apply_performed", "publish_performed", "translations_register_performed"}:
            errors.append("apply_or_publish_already_performed")
        elif name in {"shopify_write_performed", "no_shopify_writes_performed", "all_no_write_confirmed"}:
            errors.append("no_write_not_confirmed")
        else:
            errors.append(f"unsafe_execution_preview_{name}")

    if preview.get("mode") not in {"dry-run", "preview-only"}:
        errors.append("unsafe_execution_preview_mode")

    preview_apply_items = preview.get("preview_apply_items")
    not_apply_items = preview.get("not_apply_items")
    if not isinstance(preview_apply_items, list) or not isinstance(not_apply_items, list):
        errors.append("unsafe_execution_preview_items")
        preview_apply_items = preview_apply_items if isinstance(preview_apply_items, list) else []
        not_apply_items = not_apply_items if isinstance(not_apply_items, list) else []

    if "preview_apply_count" not in preview or "not_apply_count" not in preview:
        errors.append("unsafe_execution_preview_count_missing")
    elif int(preview.get("preview_apply_count") or 0) != len(preview_apply_items) or int(
        preview.get("not_apply_count") or 0
    ) != len(not_apply_items):
        errors.append("unsafe_execution_preview_count_mismatch")

    total_items = _total_preview_items(preview)
    product_count = _product_count(preview, preview_apply_items, not_apply_items)
    locale_count = _locale_count(preview, preview_apply_items, not_apply_items)
    if total_items > MAX_ITEMS or product_count > MAX_PRODUCTS or locale_count > MAX_LOCALES:
        errors.append("product_or_locale_limit_exceeded")

    final_summary = preview.get("final_approval_summary")
    if not isinstance(final_summary, dict):
        errors.append("final_approval_missing")
        return _unique(errors), _unique(warnings)

    status = str(final_summary.get("final_approval_status", ""))
    if status not in ALLOWED_FINAL_APPROVAL_STATUSES:
        errors.append("invalid_final_approval_status")
    if final_summary.get("final_apply_allowed") is True:
        warnings.append("source preview final_apply_allowed was true; final validation recomputed it")
    return _unique(errors), _unique(warnings)


def _final_validation_result(preview: dict, validation_errors: list[str]) -> dict:
    preview_apply_items = preview.get("preview_apply_items", []) if isinstance(preview.get("preview_apply_items"), list) else []
    not_apply_items = preview.get("not_apply_items", []) if isinstance(preview.get("not_apply_items"), list) else []
    total_items = len(preview_apply_items) + len(not_apply_items)
    final_summary = preview.get("final_approval_summary", {}) if isinstance(preview.get("final_approval_summary"), dict) else {}
    status = str(final_summary.get("final_approval_status", "pending"))
    approved_by = str(final_summary.get("final_approved_by", "") or "").strip()
    item_results = [_validate_preview_apply_item(item) for item in preview_apply_items]
    item_failures = [
        f"{item.get('product_id', '')} {item.get('locale', '')}: {failure}"
        for item in item_results
        for failure in item.get("validation_failures", [])
    ]
    validation_failures = []
    validation_warnings = []
    final_validation_status = "blocked"
    final_apply_allowed = False
    eligible_count = 0
    blocked_count = 0
    pending_count = 0
    rejected_count = 0

    if validation_errors:
        final_validation_status = "blocked"
        blocked_count = total_items
    elif status == "pending":
        final_validation_status = "pending"
        pending_count = total_items
    elif status == "rejected":
        final_validation_status = "rejected"
        rejected_count = total_items
    elif status == "approved":
        if not approved_by:
            validation_failures.append("final_approval_status=approved requires final_approved_by")
        if len(preview_apply_items) == 0:
            validation_failures.append("final_approval_status=approved requires preview_apply_count > 0")
        validation_failures.extend(item_failures)
        if validation_failures:
            final_validation_status = "blocked"
            blocked_count = max(total_items, 1)
        else:
            final_validation_status = "validated_for_real_apply"
            final_apply_allowed = True
            eligible_count = len(preview_apply_items)
    else:
        validation_failures.append("invalid_final_approval_status")
        final_validation_status = "blocked"
        blocked_count = total_items

    return {
        "final_validation_status": final_validation_status,
        "final_apply_allowed": final_apply_allowed,
        "total_preview_items": total_items,
        "preview_apply_count": len(preview_apply_items),
        "not_apply_count": len(not_apply_items),
        "eligible_for_real_apply_count": eligible_count,
        "blocked_count": blocked_count,
        "pending_count": pending_count,
        "rejected_count": rejected_count,
        "item_validation_results": item_results,
        "validation_failures": _unique(validation_failures),
        "validation_warnings": _unique(validation_warnings),
    }


def _validate_preview_apply_item(item: dict) -> dict:
    failures = []
    if item.get("final_decision") != "approve":
        failures.append("final_decision must be approve")
    if item.get("final_approval_ready") is not True:
        failures.append("final_approval_ready must be true")
    if item.get("manual_decision") != "approve":
        failures.append("manual_decision must be approve")
    if item.get("validation_status") != "validated_for_future_apply":
        failures.append("validation_status must be validated_for_future_apply")
    if item.get("eligible_for_future_apply") is not True:
        failures.append("eligible_for_future_apply must be true")
    if item.get("qa_status") != "pass":
        failures.append("qa_status must be pass")
    if item.get("apply_performed") is not False:
        failures.append("apply_performed must be false")
    if item.get("publish_performed") is not False:
        failures.append("publish_performed must be false")
    if item.get("shopify_write_performed") is not False:
        failures.append("shopify_write_performed must be false")
    if item.get("translations_register_performed") is not False:
        failures.append("translations_register_performed must be false")

    return {
        "product_id": item.get("product_id", ""),
        "locale": item.get("locale", ""),
        "final_decision": item.get("final_decision", ""),
        "final_approval_ready": bool(item.get("final_approval_ready")),
        "manual_decision": item.get("manual_decision", ""),
        "validation_status": item.get("validation_status", ""),
        "eligible_for_real_apply": not failures,
        "validation_failures": failures,
        "would_apply_fields": item.get("would_apply_fields", []),
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
    }


def _total_preview_items(preview: dict) -> int:
    if "total_items" in preview:
        try:
            return int(preview.get("total_items") or 0)
        except (TypeError, ValueError):
            return 0
    return len(preview.get("preview_apply_items") or []) + len(preview.get("not_apply_items") or [])


def _product_count(preview: dict, preview_apply_items: list[dict], not_apply_items: list[dict]) -> int:
    try:
        explicit = int(preview.get("product_count") or 0)
    except (TypeError, ValueError):
        explicit = 0
    if explicit:
        return explicit
    return len({str(item.get("product_id", "")) for item in preview_apply_items + not_apply_items if item.get("product_id")})


def _locale_count(preview: dict, preview_apply_items: list[dict], not_apply_items: list[dict]) -> int:
    try:
        explicit = int(preview.get("locale_count") or 0)
    except (TypeError, ValueError):
        explicit = 0
    if explicit:
        return explicit
    return len({str(item.get("locale", "")) for item in preview_apply_items + not_apply_items if item.get("locale")})


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    FINAL_VALIDATION_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(FINAL_VALIDATION_JSON_PATH.read_text(encoding="utf-8"))
    return FINAL_VALIDATION_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_VALIDATION_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return FINAL_VALIDATION_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    item_rows = "\n".join(_render_item_row(item) for item in payload.get("item_validation_results", []))
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Source Preview", "source_preview_path"),
            ("Final Validation Status", "final_validation_status"),
            ("Final Apply Allowed", "final_apply_allowed"),
            ("Total Preview Items", "total_preview_items"),
            ("Preview Apply Count", "preview_apply_count"),
            ("Not Apply Count", "not_apply_count"),
            ("Eligible For Real Apply", "eligible_for_real_apply_count"),
            ("Blocked Count", "blocked_count"),
            ("Pending Count", "pending_count"),
            ("Rejected Count", "rejected_count"),
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
  <title>Shopify Translation Final Approval Validation</title>
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
  <h1>Shopify Translation Final Approval Validation</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Preview Apply Item Checks</h2>
  <table>
    <thead>
      <tr>
        <th>Product ID</th><th>Locale</th><th>Final Decision</th><th>Final Ready</th>
        <th>Manual Decision</th><th>Validation Status</th><th>Eligible</th><th>Failures</th>
      </tr>
    </thead>
    <tbody>{item_rows or _empty_row(8, "No preview apply items to validate.")}</tbody>
  </table>
  <h2>Safety</h2>
  <ul>
    <li>This task is final-validation-only.</li>
    <li>No Shopify writes were performed.</li>
    <li>shopify_write_performed=false.</li>
    <li>apply_performed=false and publish_performed=false.</li>
    <li>translations_register_performed=false.</li>
    <li>Apply, publish, update, mutation, and translationsRegister are not available in this task.</li>
  </ul>
</body>
</html>
"""


def _render_item_row(item: dict) -> str:
    return (
        "<tr>"
        f"<td class=\"path\">{escape(str(item.get('product_id', '')))}</td>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('final_decision', '')))}</td>"
        f"<td>{'true' if item.get('final_approval_ready') else 'false'}</td>"
        f"<td>{escape(str(item.get('manual_decision', '')))}</td>"
        f"<td>{escape(str(item.get('validation_status', '')))}</td>"
        f"<td>{'true' if item.get('eligible_for_real_apply') else 'false'}</td>"
        f"<td>{escape('; '.join(item.get('validation_failures') or []))}</td>"
        "</tr>"
    )


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _empty_row(colspan: int, message: str) -> str:
    return f"<tr><td colspan=\"{colspan}\" class=\"empty\">{escape(message)}</td></tr>"


def _issue_summary(final_validation_status: str, validation_failures: list[str]) -> str:
    if validation_failures:
        return "Final approval validation blocked: " + ", ".join(_unique(validation_failures))
    return f"Final approval validation completed with status {final_validation_status}. No Shopify writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify batch translation final approval validation completed.\n"
        f"Source preview: {payload.get('source_preview_path')}\n"
        f"Final validation status: {payload.get('final_validation_status')}\n"
        f"Final apply allowed: {payload.get('final_apply_allowed')}\n"
        f"Eligible for real apply: {payload.get('eligible_for_real_apply_count')}\n"
        f"Preview apply count: {payload.get('preview_apply_count')}\n"
        f"Not apply count: {payload.get('not_apply_count')}\n"
        f"Validation failures: {len(payload.get('validation_failures') or [])}\n"
        "Final validation JSON:\n"
        f"{json_path}\n\n"
        "Final validation HTML:\n"
        f"{html_path}\n"
        "Validation only. No Shopify writes performed by this task.\n"
        "shopify_write_performed=false.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep final validation files\n"
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
