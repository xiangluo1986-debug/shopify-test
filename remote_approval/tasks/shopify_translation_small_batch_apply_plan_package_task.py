import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_small_batch_apply_plan_package"
COMMAND_LABEL = "shopify_translation_small_batch_apply_plan_package"
SOURCE_SECOND_POST_WRITE_AUDIT_PATH = LOG_DIR / "shopify_translation_second_single_field_post_write_audit_package.json"
SOURCE_SECOND_REAL_WRITE_EXECUTE_PATH = LOG_DIR / "shopify_translation_second_single_field_real_write_execute.json"
SOURCE_SECOND_VERIFIED_BACKUP_PATH = LOG_DIR / "shopify_translation_second_single_field_verified_backup_fetch.json"
SMALL_BATCH_APPLY_PLAN_JSON_PATH = LOG_DIR / "shopify_translation_small_batch_apply_plan_package.json"
SMALL_BATCH_APPLY_PLAN_HTML_PATH = LOG_DIR / "shopify_translation_small_batch_apply_plan_package.html"

EXPECTED_SECOND_AUDIT_STATUS = "second_post_write_audit_passed"
EXPECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
EXPECTED_LOCALE = "ja"
CURRENT_META_TITLE_VALUE = "MOFLY P-51D Aileron Link Connector Test"
ALLOWED_FIELDS = ["meta_title", "meta_description"]
FIELD_MAX_CHARS = {
    "meta_title": 60,
    "meta_description": 160,
}
MAX_ENTRIES = 5


def run_shopify_translation_small_batch_apply_plan_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    source_reports = {}

    for key, label, path, missing_code, invalid_code, required in _source_report_specs():
        try:
            source_reports[key] = _read_json(path)
        except FileNotFoundError as exc:
            source_reports[key] = {}
            if required:
                parse_errors.append(f"{label} JSON not found: {exc}")
                validation_errors.append(missing_code)
        except (OSError, json.JSONDecodeError) as exc:
            source_reports[key] = {}
            parse_errors.append(f"Could not parse {label} JSON: {exc}")
            validation_errors.append(invalid_code)

    audit_report = source_reports["second_audit"]
    if audit_report:
        validation_errors.extend(_validate_second_audit_report(audit_report))

    test_scenario = (os.environ.get("SHOPIFY_TRANSLATION_SMALL_BATCH_PLAN_TEST_SCENARIO") or "").strip()
    entries = _build_plan_entries(audit_report, test_scenario)
    validation_errors.extend(_validate_entries(entries))

    blocking_conditions = _blocking_conditions(validation_errors)
    plan_status = _plan_status(blocking_conditions)
    success = plan_status == "small_batch_apply_plan_ready_for_manual_review"
    end_time = utc_now_iso()
    product_id = _single_value([entry["product_id"] for entry in entries])
    locale = _single_value([entry["locale"] for entry in entries])
    validated_entries = _validated_entries(entries)

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "small-batch-apply-plan-package-only",
        "command_label": COMMAND_LABEL,
        "source_second_post_write_audit_path": str(SOURCE_SECOND_POST_WRITE_AUDIT_PATH),
        "source_second_real_write_execute_path": str(SOURCE_SECOND_REAL_WRITE_EXECUTE_PATH),
        "source_second_verified_backup_path": str(SOURCE_SECOND_VERIFIED_BACKUP_PATH),
        "json_small_batch_apply_plan_package_path": str(SMALL_BATCH_APPLY_PLAN_JSON_PATH),
        "html_small_batch_apply_plan_package_path": str(SMALL_BATCH_APPLY_PLAN_HTML_PATH),
        "success": success,
        "plan_status": plan_status,
        "product_id": product_id,
        "locale": locale,
        "entry_count": len(entries),
        "allowed_fields": ALLOWED_FIELDS,
        "max_entries": MAX_ENTRIES,
        "max_products": 1,
        "max_locales": 1,
        "entries": validated_entries,
        "manual_review_required": True,
        "real_write_allowed": False,
        "next_step_requires_separate_execute_task": True,
        "source_report_summary": _source_report_summary(source_reports),
        "plan_constraints": _plan_constraints(),
        "manual_review_checklist": _manual_review_checklist(),
        "forbidden_actions": _forbidden_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(),
        "plan_package_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "test_scenario": test_scenario,
        "detected_issue_summary": _issue_summary(plan_status, blocking_conditions),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
    }
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_small_batch_apply_plan_package_path": str(json_path),
        "html_small_batch_apply_plan_package_path": str(html_path),
        "plan_status": plan_status,
        "plan_package_only": True,
        "entry_count": len(entries),
        "allowed_fields": ALLOWED_FIELDS,
        "manual_review_required": True,
        "real_write_allowed": False,
        "next_step_requires_separate_execute_task": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _source_report_specs() -> list[tuple[str, str, Path, str, str, bool]]:
    return [
        (
            "second_audit",
            "second post-write audit report",
            SOURCE_SECOND_POST_WRITE_AUDIT_PATH,
            "missing_second_post_write_audit_report",
            "second_post_write_audit_json_invalid",
            True,
        ),
        (
            "second_execute",
            "second real write execution report",
            SOURCE_SECOND_REAL_WRITE_EXECUTE_PATH,
            "missing_second_real_write_execute_report",
            "second_real_write_execute_json_invalid",
            False,
        ),
        (
            "second_backup",
            "second verified backup report",
            SOURCE_SECOND_VERIFIED_BACKUP_PATH,
            "missing_second_verified_backup_report",
            "second_verified_backup_json_invalid",
            False,
        ),
    ]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_second_audit_report(report: dict) -> list[str]:
    errors = []
    if report.get("audit_status") != EXPECTED_SECOND_AUDIT_STATUS:
        errors.append("second_post_write_audit_not_passed")
    if report.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.append("multiple_products")
    if report.get("locale") != EXPECTED_LOCALE:
        errors.append("multiple_locales")
    if report.get("field") != "meta_title":
        errors.append("invalid_field")
    if report.get("final_value_after_second_write") != CURRENT_META_TITLE_VALUE:
        errors.append("second_post_write_audit_not_passed")
    if report.get("readback_matches_proposed_value") is not True:
        errors.append("second_post_write_audit_not_passed")
    if report.get("rollback_needed") is not False:
        errors.append("second_post_write_audit_not_passed")
    return _unique(errors)


def _build_plan_entries(audit_report: dict, test_scenario: str) -> list[dict]:
    product_id = audit_report.get("product_id") or EXPECTED_PRODUCT_ID
    locale = audit_report.get("locale") or EXPECTED_LOCALE
    current_meta_title = audit_report.get("final_value_after_second_write") or CURRENT_META_TITLE_VALUE
    entries = [
        {
            "product_id": product_id,
            "locale": locale,
            "field": "meta_title",
            "current_value_if_known": current_meta_title,
            "current_value_known": bool(current_meta_title),
            "proposed_value": "MOFLY P-51D Aileron Link Connector",
        },
        {
            "product_id": product_id,
            "locale": locale,
            "field": "meta_description",
            "current_value_if_known": "",
            "current_value_known": False,
            "proposed_value": (
                "High-quality replacement aileron linkage connector for MOFLY P-51D RC airplane repairs and maintenance."
            ),
        },
    ]
    if test_scenario == "invalid-field":
        entries[1]["field"] = "title"
    elif test_scenario == "too-many-entries":
        entries = entries + [
            {
                "product_id": product_id,
                "locale": locale,
                "field": "meta_description",
                "current_value_if_known": "",
                "current_value_known": False,
                "proposed_value": f"MOFLY P-51D maintenance note {index}",
            }
            for index in range(3, 7)
        ]
    return entries


def _validate_entries(entries: list[dict]) -> list[str]:
    errors = []
    if len(entries) > MAX_ENTRIES:
        errors.append("too_many_entries")

    product_ids = {entry.get("product_id") for entry in entries if entry.get("product_id")}
    locales = {entry.get("locale") for entry in entries if entry.get("locale")}
    if len(product_ids) != 1 or product_ids != {EXPECTED_PRODUCT_ID}:
        errors.append("multiple_products")
    if len(locales) != 1 or locales != {EXPECTED_LOCALE}:
        errors.append("multiple_locales")

    for entry in entries:
        field = entry.get("field")
        value = str(entry.get("proposed_value") or "")
        if field not in ALLOWED_FIELDS:
            errors.append("invalid_field")
            continue
        if not value:
            errors.append("empty_proposed_value")
            continue
        if len(value) > FIELD_MAX_CHARS[field]:
            errors.append("value_too_long")
    return _unique(errors)


def _validated_entries(entries: list[dict]) -> list[dict]:
    validated = []
    for index, entry in enumerate(entries, start=1):
        field = entry.get("field")
        proposed_value = str(entry.get("proposed_value") or "")
        max_chars = FIELD_MAX_CHARS.get(field, 0)
        field_allowed = field in ALLOWED_FIELDS
        value_non_empty = bool(proposed_value)
        value_length_allowed = field_allowed and len(proposed_value) <= max_chars
        validation_status = "valid" if field_allowed and value_non_empty and value_length_allowed else "blocked"
        validated.append(
            {
                "entry_index": index,
                "product_id": entry.get("product_id", ""),
                "locale": entry.get("locale", ""),
                "field": field,
                "current_value_if_known": entry.get("current_value_if_known", ""),
                "current_value_known": bool(entry.get("current_value_known")),
                "proposed_value": proposed_value,
                "proposed_value_chars": len(proposed_value),
                "max_chars": max_chars,
                "field_allowed": field_allowed,
                "value_non_empty": value_non_empty,
                "value_length_allowed": value_length_allowed,
                "validation_status": validation_status,
            }
        )
    return validated


def _source_report_summary(reports: dict) -> dict:
    audit = reports.get("second_audit") or {}
    execute = reports.get("second_execute") or {}
    backup = reports.get("second_backup") or {}
    return {
        "second_post_write_audit_loaded": bool(audit),
        "second_post_write_audit_status": audit.get("audit_status", ""),
        "source_product_id": audit.get("product_id", ""),
        "source_locale": audit.get("locale", ""),
        "source_field": audit.get("field", ""),
        "source_final_value_after_second_write": audit.get("final_value_after_second_write", ""),
        "second_real_write_execute_loaded": bool(execute),
        "second_real_write_execution_status": execute.get("execution_status", ""),
        "second_verified_backup_loaded": bool(backup),
        "second_verified_backup_status": backup.get("backup_fetch_status", ""),
        "second_verified_backup_value": backup.get("second_backup_value", ""),
    }


def _plan_constraints() -> dict:
    return {
        "max_entries": MAX_ENTRIES,
        "max_products": 1,
        "max_locales": 1,
        "allowed_fields": ALLOWED_FIELDS,
        "disallowed_fields": [
            "title",
            "body_html",
            "description",
            "handle",
            "tags",
            "image alt",
            "variants",
            "collections",
            "publish",
            "inventory",
            "price",
            "any non-translation field",
        ],
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
    }


def _manual_review_checklist() -> list[str]:
    return [
        "Confirm the plan is limited to gid://shopify/Product/7655686799427.",
        "Confirm the locale is ja.",
        "Confirm each field is either meta_title or meta_description.",
        "Confirm the meta_title proposed value is <= 60 chars.",
        "Confirm the meta_description proposed value is <= 160 chars.",
        "Confirm the current meta_title value is from the second post-write audit.",
        "Confirm a separate execute task is required before any Shopify write.",
    ]


def _forbidden_actions() -> list[str]:
    return [
        "Shopify API call in this phase",
        "Shopify write in this phase",
        "mutation in this phase",
        "translationsRegister in this phase",
        "readback in this phase",
        "rollback in this phase",
        "publish in this phase",
        "real apply in this phase",
        "batch execution",
        "full-store scan",
        "multiple products",
        "multiple locales",
        "unsupported fields",
        "git push",
    ]


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_second_post_write_audit_report": "blocked_missing_second_post_write_audit_report",
        "second_post_write_audit_not_passed": "blocked_second_post_write_audit_not_passed",
        "too_many_entries": "blocked_too_many_entries",
        "multiple_products": "blocked_multiple_products",
        "multiple_locales": "blocked_multiple_locales",
        "invalid_field": "blocked_invalid_field",
        "empty_proposed_value": "blocked_empty_proposed_value",
        "value_too_long": "blocked_value_too_long",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _plan_status(blocking_conditions: list[str]) -> str:
    if not blocking_conditions:
        return "small_batch_apply_plan_ready_for_manual_review"
    for status in [
        "blocked_missing_second_post_write_audit_report",
        "blocked_second_post_write_audit_not_passed",
        "blocked_too_many_entries",
        "blocked_multiple_products",
        "blocked_multiple_locales",
        "blocked_invalid_field",
        "blocked_empty_proposed_value",
        "blocked_value_too_long",
    ]:
        if status in blocking_conditions:
            return status
    return "blocked"


def _safety_summary() -> dict:
    return {
        "plan_package_only": True,
        "manual_review_required": True,
        "real_write_allowed": False,
        "next_step_requires_separate_execute_task": True,
        "shopify_api_call_allowed": False,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "readback_allowed": False,
        "rollback_allowed": False,
        "publish_allowed": False,
        "bulk_write_allowed": False,
        "real_apply_allowed": False,
        "max_entries": MAX_ENTRIES,
        "max_products": 1,
        "max_locales": 1,
        "allowed_fields": ALLOWED_FIELDS,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SMALL_BATCH_APPLY_PLAN_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SMALL_BATCH_APPLY_PLAN_JSON_PATH.read_text(encoding="utf-8"))
    return SMALL_BATCH_APPLY_PLAN_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SMALL_BATCH_APPLY_PLAN_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SMALL_BATCH_APPLY_PLAN_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Plan Status", "plan_status"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Entry Count", "entry_count"),
            ("Allowed Fields", "allowed_fields"),
            ("Manual Review Required", "manual_review_required"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Next Step Requires Separate Execute Task", "next_step_requires_separate_execute_task"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    entry_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(entry.get('entry_index')))}</td>"
        f"<td>{escape(str(entry.get('field')))}</td>"
        f"<td>{escape(str(entry.get('current_value_if_known')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars')))} / {escape(str(entry.get('max_chars')))}</td>"
        f"<td>{escape(str(entry.get('validation_status')))}</td>"
        "</tr>"
        for entry in payload.get("entries", [])
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Source Report Summary", payload.get("source_report_summary", {})),
            ("Plan Constraints", payload.get("plan_constraints", {})),
            ("Manual Review Checklist", payload.get("manual_review_checklist", [])),
            ("Forbidden Actions", payload.get("forbidden_actions", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Small Batch Apply Plan Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 320px; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify Small Batch Apply Plan Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Entries</h2>
  <table>
    <thead>
      <tr><th>Index</th><th>Field</th><th>Current Value If Known</th><th>Proposed Value</th><th>Chars</th><th>Status</th></tr>
    </thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Plan Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local reports and writes local JSON/HTML only.</li>
    <li>No Shopify API call, write, mutation, translationsRegister, readback, rollback, publish, or apply was performed.</li>
    <li>The next step must be a separate execute task after manual review.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(plan_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Small batch apply plan blocked: " + ", ".join(blocking_conditions)
    return f"Small batch apply plan generated with status {plan_status}. No Shopify action performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify small batch apply plan package generated.\n"
        f"Plan status: {payload.get('plan_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locale: {payload.get('locale')}\n"
        f"Entry count: {payload.get('entry_count')}\n"
        f"Allowed fields: {payload.get('allowed_fields')}\n"
        f"Real write allowed: {payload.get('real_write_allowed')}\n"
        f"Manual review required: {payload.get('manual_review_required')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Small batch apply plan JSON:\n"
        f"{json_path}\n\n"
        "Small batch apply plan HTML:\n"
        f"{html_path}\n"
        "Plan package only. No Shopify API call, mutation, translationsRegister, readback, rollback, publish, apply, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep small batch apply plan files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Do not push from this task."
    )


def _single_value(values: list[str]) -> str:
    unique_values = [value for value in _unique(values) if value]
    return unique_values[0] if len(unique_values) == 1 else ""


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
