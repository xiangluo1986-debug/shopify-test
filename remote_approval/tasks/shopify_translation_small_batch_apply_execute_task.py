import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_small_batch_apply_execute"
COMMAND_LABEL = "shopify_translation_small_batch_apply_execute"
SOURCE_SMALL_BATCH_PLAN_PATH = LOG_DIR / "shopify_translation_small_batch_apply_plan_package.json"
SMALL_BATCH_APPLY_EXECUTE_JSON_PATH = LOG_DIR / "shopify_translation_small_batch_apply_execute.json"
SMALL_BATCH_APPLY_EXECUTE_HTML_PATH = LOG_DIR / "shopify_translation_small_batch_apply_execute.html"

EXECUTION_ACK_ENV = "SHOPIFY_TRANSLATION_SMALL_BATCH_EXECUTION_ACK"
EXECUTION_ACK_VALUE = "YES_I_APPROVE_SMALL_BATCH_SHOPIFY_TRANSLATION_WRITE"
SUPPORTED_MODES = {"dry-run", "real-run", "execute-real-write"}
REAL_RUN_MODES = {"real-run", "execute-real-write"}

READY_PLAN_STATUS = "small_batch_apply_plan_ready_for_manual_review"
EXPECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
EXPECTED_LOCALE = "ja"
ALLOWED_FIELDS = ["meta_title", "meta_description"]
FIELD_MAX_CHARS = {
    "meta_title": 60,
    "meta_description": 160,
}
MAX_ENTRIES = 5


def run_shopify_translation_small_batch_apply_execute_task(mode: str) -> dict:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"{TASK_NAME} only supports dry-run, real-run, or execute-real-write mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    plan_report = {}

    try:
        plan_report = _read_json(SOURCE_SMALL_BATCH_PLAN_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Small batch apply plan JSON not found: {exc}")
        validation_errors.append("missing_small_batch_apply_plan_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse small batch apply plan JSON: {exc}")
        validation_errors.append("small_batch_apply_plan_json_invalid")

    ack_value = os.environ.get(EXECUTION_ACK_ENV, "").strip()
    ack_present = bool(ack_value)
    ack_valid = ack_value == EXECUTION_ACK_VALUE
    if mode in REAL_RUN_MODES:
        if not ack_present:
            validation_errors.append("missing_small_batch_execution_ack")
        elif not ack_valid:
            validation_errors.append("invalid_small_batch_execution_ack")
        else:
            validation_errors.append("real_run_disabled_in_phase_13_1")

    if plan_report:
        validation_errors.extend(_validate_plan_report(plan_report))

    blocking_conditions = _blocking_conditions(validation_errors)
    execution_status = _execution_status(mode, blocking_conditions)
    success = execution_status == "dry_run_small_batch_write_not_executed"
    entries = plan_report.get("entries", []) if isinstance(plan_report.get("entries"), list) else []
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "source_small_batch_apply_plan_path": str(SOURCE_SMALL_BATCH_PLAN_PATH),
        "json_small_batch_apply_execute_path": str(SMALL_BATCH_APPLY_EXECUTE_JSON_PATH),
        "html_small_batch_apply_execute_path": str(SMALL_BATCH_APPLY_EXECUTE_HTML_PATH),
        "success": success,
        "execution_status": execution_status,
        "plan_status": plan_report.get("plan_status", ""),
        "product_id": plan_report.get("product_id", ""),
        "locale": plan_report.get("locale", ""),
        "entry_count": len(entries),
        "allowed_fields": ALLOWED_FIELDS,
        "source_plan_summary": _source_plan_summary(plan_report, entries),
        "validated_execution_scope": _validated_execution_scope(plan_report, entries),
        "planned_entries": _planned_entries(entries),
        "small_batch_execution_ack_summary": {
            "ack_env": EXECUTION_ACK_ENV,
            "ack_present": ack_present,
            "ack_value_matches_required_phrase": ack_valid,
            "ack_required_value": EXECUTION_ACK_VALUE,
            "ack_effective": False,
            "ack_note": "ACK is only checked for future real-run eligibility; Phase 13.1 never writes Shopify.",
        },
        "dry_run_execution_summary": {
            "dry_run_only": mode == "dry-run",
            "would_attempt_real_write": False,
            "would_call_shopify_api": False,
            "would_call_mutation": False,
            "would_call_translations_register": False,
            "would_publish": False,
            "would_readback": False,
            "would_rollback": False,
            "entries_validated": len(entries),
            "future_mutation_name": "translationsRegister",
        },
        "future_real_run_requirements": _future_real_run_requirements(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(mode),
        "small_batch_execute_task": True,
        "small_batch_execute_dry_run_only": True,
        "small_batch_execution_ack_present": ack_present,
        "small_batch_execution_ack_valid": ack_valid,
        "real_write_allowed": False,
        "write_execution_allowed": False,
        "translations_register_allowed": False,
        "translations_register_called": False,
        "translations_register_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "shopify_mutations_called": [],
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "real_apply_performed": False,
        "command_executed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(execution_status, blocking_conditions),
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
        "json_small_batch_apply_execute_path": str(json_path),
        "html_small_batch_apply_execute_path": str(html_path),
        "execution_status": execution_status,
        "plan_status": plan_report.get("plan_status", ""),
        "small_batch_execute_task": True,
        "small_batch_execute_dry_run_only": True,
        "small_batch_execution_ack_present": ack_present,
        "small_batch_execution_ack_valid": ack_valid,
        "entry_count": len(entries),
        "real_write_allowed": False,
        "write_execution_allowed": False,
        "translations_register_allowed": False,
        "translations_register_called": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
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


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_plan_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != "shopify_translation_small_batch_apply_plan_package":
        errors.append("small_batch_apply_plan_not_ready")
    if report.get("plan_status") != READY_PLAN_STATUS:
        errors.append("small_batch_apply_plan_not_ready")
    if report.get("plan_package_only") is not True:
        errors.append("small_batch_apply_plan_not_ready")
    if report.get("real_write_allowed") is not False:
        errors.append("unexpected_side_effect_risk")
    if report.get("next_step_requires_separate_execute_task") is not True:
        errors.append("small_batch_apply_plan_not_ready")

    entries = report.get("entries")
    if not isinstance(entries, list):
        errors.append("small_batch_apply_plan_not_ready")
        entries = []
    if len(entries) > MAX_ENTRIES:
        errors.append("too_many_entries")
    if int(report.get("entry_count") or len(entries)) > MAX_ENTRIES:
        errors.append("too_many_entries")

    product_ids = {entry.get("product_id") for entry in entries if entry.get("product_id")}
    locales = {entry.get("locale") for entry in entries if entry.get("locale")}
    if len(product_ids) != 1 or product_ids != {EXPECTED_PRODUCT_ID} or report.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.append("multiple_products")
    if len(locales) != 1 or locales != {EXPECTED_LOCALE} or report.get("locale") != EXPECTED_LOCALE:
        errors.append("multiple_locales")

    for entry in entries:
        field = entry.get("field")
        value = str(entry.get("proposed_value") or "")
        if field not in ALLOWED_FIELDS:
            errors.append("invalid_field")
            continue
        if entry.get("field_allowed") is not True:
            errors.append("invalid_field")
        if not value or entry.get("value_non_empty") is not True:
            errors.append("empty_proposed_value")
        if len(value) > FIELD_MAX_CHARS[field] or entry.get("value_length_allowed") is not True:
            errors.append("value_too_long")
        if entry.get("validation_status") != "valid":
            errors.append("small_batch_apply_plan_not_ready")

    for flag in [
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "readback_performed",
        "rollback_performed",
        "publish_performed",
        "bulk_write_performed",
        "real_apply_performed",
    ]:
        if report.get(flag) is True:
            errors.append("unexpected_side_effect_risk")
    if report.get("no_new_shopify_writes_performed") is not True:
        errors.append("unexpected_side_effect_risk")
    if report.get("all_new_actions_no_write_confirmed") is not True:
        errors.append("unexpected_side_effect_risk")
    return _unique(errors)


def _source_plan_summary(report: dict, entries: list[dict]) -> dict:
    return {
        "source_plan_loaded": bool(report),
        "source_plan_status": report.get("plan_status", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": len(entries),
        "source_allowed_fields": report.get("allowed_fields", []) if report else [],
        "source_manual_review_required": report.get("manual_review_required") is True if report else False,
        "source_real_write_allowed": report.get("real_write_allowed") is True if report else False,
        "source_next_step_requires_separate_execute_task": (
            report.get("next_step_requires_separate_execute_task") is True if report else False
        ),
    }


def _validated_execution_scope(report: dict, entries: list[dict]) -> dict:
    product_ids = {entry.get("product_id") for entry in entries if entry.get("product_id")}
    locales = {entry.get("locale") for entry in entries if entry.get("locale")}
    fields = [entry.get("field") for entry in entries]
    return {
        "product_count": len(product_ids),
        "locale_count": len(locales),
        "entry_count": len(entries),
        "max_entries": MAX_ENTRIES,
        "allowed_fields": ALLOWED_FIELDS,
        "product_id": report.get("product_id", "") if report else "",
        "locale": report.get("locale", "") if report else "",
        "all_fields_allowed": all(field in ALLOWED_FIELDS for field in fields),
        "has_publish_risk": False,
        "has_rollback_risk": False,
        "has_non_translation_field": any(field not in ALLOWED_FIELDS for field in fields),
    }


def _planned_entries(entries: list[dict]) -> list[dict]:
    planned = []
    for entry in entries:
        planned.append(
            {
                "entry_index": entry.get("entry_index"),
                "product_id": entry.get("product_id", ""),
                "locale": entry.get("locale", ""),
                "field": entry.get("field", ""),
                "current_value_if_known": entry.get("current_value_if_known", ""),
                "proposed_value": entry.get("proposed_value", ""),
                "proposed_value_chars": int(entry.get("proposed_value_chars") or len(str(entry.get("proposed_value") or ""))),
                "max_chars": int(entry.get("max_chars") or FIELD_MAX_CHARS.get(entry.get("field"), 0)),
                "validation_status": entry.get("validation_status", ""),
                "would_write_in_this_phase": False,
                "future_mutation_name": "translationsRegister",
            }
        )
    return planned


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_small_batch_apply_plan_report": "blocked_missing_small_batch_apply_plan_report",
        "small_batch_apply_plan_not_ready": "blocked_small_batch_apply_plan_not_ready",
        "missing_small_batch_execution_ack": "blocked_missing_small_batch_execution_ack",
        "invalid_small_batch_execution_ack": "blocked_invalid_small_batch_execution_ack",
        "too_many_entries": "blocked_too_many_entries",
        "multiple_products": "blocked_multiple_products",
        "multiple_locales": "blocked_multiple_locales",
        "invalid_field": "blocked_invalid_field",
        "unexpected_side_effect_risk": "blocked_unexpected_side_effect_risk",
        "real_run_disabled_in_phase_13_1": "blocked_real_run_disabled_in_phase_13_1",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _execution_status(mode: str, blocking_conditions: list[str]) -> str:
    if not blocking_conditions and mode == "dry-run":
        return "dry_run_small_batch_write_not_executed"
    for status in [
        "blocked_missing_small_batch_apply_plan_report",
        "blocked_small_batch_apply_plan_not_ready",
        "blocked_missing_small_batch_execution_ack",
        "blocked_invalid_small_batch_execution_ack",
        "blocked_too_many_entries",
        "blocked_multiple_products",
        "blocked_multiple_locales",
        "blocked_invalid_field",
        "blocked_unexpected_side_effect_risk",
        "blocked_real_run_disabled_in_phase_13_1",
    ]:
        if status in blocking_conditions:
            return status
    return "blocked"


def _future_real_run_requirements() -> list[str]:
    return [
        "A separate future execution phase must explicitly enable real small-batch writes.",
        f"{EXECUTION_ACK_ENV} must exactly equal {EXECUTION_ACK_VALUE}.",
        "The source plan must still be ready for manual review.",
        "The execution scope must remain one product, one locale, at most five entries.",
        "Only meta_title and meta_description are allowed.",
        "No publish, rollback, non-translation field, full-store scan, or batch expansion is allowed.",
        "Immediate readback and separate rollback approval must be implemented before real execution.",
    ]


def _safety_summary(mode: str) -> dict:
    return {
        "mode": mode,
        "small_batch_execute_task": True,
        "phase_13_1_dry_run_blocking_only": True,
        "real_run_disabled_in_this_phase": True,
        "real_write_allowed": False,
        "write_execution_allowed": False,
        "translations_register_allowed": False,
        "shopify_api_call_allowed": False,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
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
    SMALL_BATCH_APPLY_EXECUTE_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SMALL_BATCH_APPLY_EXECUTE_JSON_PATH.read_text(encoding="utf-8"))
    return SMALL_BATCH_APPLY_EXECUTE_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SMALL_BATCH_APPLY_EXECUTE_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SMALL_BATCH_APPLY_EXECUTE_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Execution Status", "execution_status"),
            ("Plan Status", "plan_status"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Entry Count", "entry_count"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Translations Register Called", "translations_register_called"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("Readback Performed", "readback_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("Publish Performed", "publish_performed"),
            ("Bulk Write Performed", "bulk_write_performed"),
            ("Real Apply Performed", "real_apply_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    entry_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(entry.get('entry_index')))}</td>"
        f"<td>{escape(str(entry.get('field')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars')))} / {escape(str(entry.get('max_chars')))}</td>"
        f"<td>{escape(str(entry.get('would_write_in_this_phase')))}</td>"
        "</tr>"
        for entry in payload.get("planned_entries", [])
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Source Plan Summary", payload.get("source_plan_summary", {})),
            ("Validated Execution Scope", payload.get("validated_execution_scope", {})),
            ("Small Batch Execution Ack Summary", payload.get("small_batch_execution_ack_summary", {})),
            ("Dry Run Execution Summary", payload.get("dry_run_execution_summary", {})),
            ("Future Real Run Requirements", payload.get("future_real_run_requirements", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Small Batch Apply Execute Dry-run</title>
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
  <h1>Shopify Small Batch Apply Execute Dry-run</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Planned Entries</h2>
  <table>
    <thead>
      <tr><th>Index</th><th>Field</th><th>Proposed Value</th><th>Chars</th><th>Would Write In This Phase</th></tr>
    </thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Execution Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>Phase 13.1 is dry-run / blocking only.</li>
    <li>No Shopify API call, write, mutation, translationsRegister, readback, rollback, publish, or apply was performed.</li>
    <li>Any future real execution must be a separate phase.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(execution_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Small batch apply execute blocked: " + ", ".join(blocking_conditions)
    return f"Small batch apply execute dry-run completed with status {execution_status}. No Shopify action performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify small batch apply execute dry-run report generated.\n"
        f"Mode: {payload.get('mode')}\n"
        f"Execution status: {payload.get('execution_status')}\n"
        f"Plan status: {payload.get('plan_status')}\n"
        f"Entry count: {payload.get('entry_count')}\n"
        f"Real write allowed: {payload.get('real_write_allowed')}\n"
        f"Translations register called: {payload.get('translations_register_called')}\n"
        f"Shopify write performed: {payload.get('shopify_write_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Small batch execute JSON:\n"
        f"{json_path}\n\n"
        "Small batch execute HTML:\n"
        f"{html_path}\n"
        "Phase 13.1 is dry-run / blocking only. No Shopify API call, mutation, translationsRegister, readback, rollback, publish, apply, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep small batch execute dry-run files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Do not push from this task."
    )


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
