import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_csv_json_small_batch_manual_real_run_test_package"
COMMAND_LABEL = "shopify_translation_csv_json_small_batch_manual_real_run_test_package"
SOURCE_CSV_JSON_PLAN_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_apply_plan_package.json"
SOURCE_SMALL_BATCH_EXECUTE_PATH = LOG_DIR / "shopify_translation_small_batch_apply_execute.json"
SOURCE_CSV_JSON_READINESS_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_real_write_readiness_package.json"
MANUAL_TEST_JSON_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_manual_real_run_test_package.json"
MANUAL_TEST_HTML_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_manual_real_run_test_package.html"

READY_PLAN_STATUS = "csv_json_small_batch_apply_plan_ready_for_manual_review"
READY_EXECUTE_STATUS = "dry_run_small_batch_write_not_executed"
READY_READINESS_STATUS = "csv_json_small_batch_real_write_ready_for_human_approval"
READY_MANUAL_TEST_STATUS = "csv_json_small_batch_manual_real_run_test_ready"
EXPECTED_PLAN_SOURCE = "csv_json"
ACK_ENV_NAME = "SHOPIFY_TRANSLATION_SMALL_BATCH_EXECUTION_ACK"
ACK_VALUE = "YES_I_APPROVE_SMALL_BATCH_SHOPIFY_TRANSLATION_WRITE"
ALLOWED_FIELDS = ["meta_title", "meta_description"]
FIELD_MAX_CHARS = {"meta_title": 60, "meta_description": 160}
MAX_ENTRIES = 5
SUPPORTED_LOCALE = "ja"
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/\d+$")


def run_shopify_translation_csv_json_small_batch_manual_real_run_test_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    plan_report = {}
    execute_report = {}
    readiness_report = {}

    try:
        plan_report = _read_json(SOURCE_CSV_JSON_PLAN_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"CSV/JSON small batch apply plan JSON not found: {exc}")
        validation_errors.append("missing_csv_json_apply_plan_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse CSV/JSON small batch apply plan JSON: {exc}")
        validation_errors.append("csv_json_apply_plan_json_invalid")

    try:
        execute_report = _read_json(SOURCE_SMALL_BATCH_EXECUTE_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Small batch execute JSON not found: {exc}")
        validation_errors.append("missing_small_batch_execute_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse small batch execute JSON: {exc}")
        validation_errors.append("small_batch_execute_json_invalid")

    try:
        readiness_report = _read_json(SOURCE_CSV_JSON_READINESS_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"CSV/JSON readiness JSON not found: {exc}")
        validation_errors.append("missing_csv_json_readiness_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse CSV/JSON readiness JSON: {exc}")
        validation_errors.append("csv_json_readiness_json_invalid")

    if plan_report:
        validation_errors.extend(_validate_plan_report(plan_report))
    if execute_report:
        validation_errors.extend(_validate_execute_report(execute_report))
    if readiness_report:
        validation_errors.extend(_validate_readiness_report(readiness_report))
    if plan_report and execute_report:
        validation_errors.extend(_validate_plan_execute_match(plan_report, execute_report))
    if plan_report and readiness_report:
        validation_errors.extend(_validate_plan_readiness_match(plan_report, readiness_report))
    if execute_report and readiness_report:
        validation_errors.extend(_validate_execute_readiness_match(execute_report, readiness_report))

    entries = _normalized_entries(plan_report)
    blocking_conditions = _blocking_conditions(validation_errors)
    manual_test_package_status = _manual_test_package_status(blocking_conditions)
    success = manual_test_package_status == READY_MANUAL_TEST_STATUS
    product_id = _single_value([entry.get("product_id", "") for entry in entries])
    locale = _single_value([entry.get("locale", "") for entry in entries])
    fields = [entry.get("field", "") for entry in entries if entry.get("field")]
    proposed_values = {entry["field"]: entry["proposed_value"] for entry in entries if entry.get("field")}
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "csv-json-small-batch-manual-real-run-test-package-only",
        "command_label": COMMAND_LABEL,
        "source_csv_json_small_batch_apply_plan_path": str(SOURCE_CSV_JSON_PLAN_PATH),
        "source_small_batch_apply_execute_path": str(SOURCE_SMALL_BATCH_EXECUTE_PATH),
        "source_csv_json_small_batch_real_write_readiness_path": str(SOURCE_CSV_JSON_READINESS_PATH),
        "json_csv_json_small_batch_manual_real_run_test_package_path": str(MANUAL_TEST_JSON_PATH),
        "html_csv_json_small_batch_manual_real_run_test_package_path": str(MANUAL_TEST_HTML_PATH),
        "success": success,
        "manual_test_package_status": manual_test_package_status,
        "product_id": product_id,
        "locale": locale,
        "entry_count": len(entries),
        "fields": fields,
        "entries": entries,
        "proposed_values": proposed_values,
        "plan_source": EXPECTED_PLAN_SOURCE,
        "manual_test_required": True,
        "real_run_not_executed_by_this_task": True,
        "required_ack_env_name": ACK_ENV_NAME,
        "required_ack_env_value": ACK_VALUE,
        "manual_real_run_command_preview": _manual_real_run_command_preview(),
        "real_run_success_fields_to_check": _real_run_success_fields_to_check(),
        "audit_success_fields_to_check": _audit_success_fields_to_check(),
        "source_plan_summary": _source_plan_summary(plan_report),
        "source_execute_dry_run_summary": _source_execute_dry_run_summary(execute_report),
        "source_readiness_summary": _source_readiness_summary(readiness_report),
        "manual_test_checks": _manual_test_checks(plan_report, execute_report, readiness_report, entries),
        "manual_review_checklist": _manual_review_checklist(entries),
        "future_real_run_safety_notes": _future_real_run_safety_notes(),
        "forbidden_actions": _forbidden_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(),
        "manual_test_package_only": True,
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
        "detected_issue_summary": _issue_summary(manual_test_package_status, blocking_conditions),
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
        "json_csv_json_small_batch_manual_real_run_test_package_path": str(json_path),
        "html_csv_json_small_batch_manual_real_run_test_package_path": str(html_path),
        "manual_test_package_status": manual_test_package_status,
        "manual_test_package_only": True,
        "product_id": product_id,
        "locale": locale,
        "entry_count": len(entries),
        "plan_source": EXPECTED_PLAN_SOURCE,
        "manual_test_required": True,
        "real_run_not_executed_by_this_task": True,
        "required_ack_env_name": ACK_ENV_NAME,
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


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_plan_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != "shopify_translation_csv_json_small_batch_apply_plan_package":
        errors.append("csv_json_apply_plan_not_ready")
    if report.get("plan_status") != READY_PLAN_STATUS:
        errors.append("csv_json_apply_plan_not_ready")
    if report.get("plan_package_only") is not True:
        errors.append("csv_json_apply_plan_not_ready")
    if report.get("manual_review_required") is not True:
        errors.append("csv_json_apply_plan_not_ready")
    if report.get("real_write_allowed") is not False:
        errors.append("precondition_not_no_write")
    if report.get("next_step_requires_separate_execute_task") is not True:
        errors.append("csv_json_apply_plan_not_ready")
    if _report_has_write_or_external_action(report):
        errors.append("precondition_not_no_write")
    entries = _normalized_entries(report)
    errors.extend(_validate_entries(entries))
    return _unique(errors)


def _validate_execute_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != "shopify_translation_small_batch_apply_execute":
        errors.append("execute_report_not_csv_json_dry_run")
    if report.get("mode") != "dry-run" or report.get("execution_status") != READY_EXECUTE_STATUS:
        errors.append("execute_report_not_csv_json_dry_run")
    if report.get("plan_source") != EXPECTED_PLAN_SOURCE:
        errors.append("execute_report_not_csv_json_dry_run")
    if report.get("plan_status") != READY_PLAN_STATUS:
        errors.append("execute_report_not_csv_json_dry_run")
    if report.get("blocking_conditions") not in ([], None):
        errors.append("execute_report_not_csv_json_dry_run")
    if _report_has_write_or_external_action(report):
        errors.append("precondition_not_no_write")
    for flag in ["real_write_allowed", "write_execution_allowed", "translations_register_allowed"]:
        if report.get(flag) is not False:
            errors.append("precondition_not_no_write")
    entries = _normalized_entries({"entries": report.get("entries") or report.get("planned_entries") or []})
    errors.extend(_validate_entries(entries))
    return _unique(errors)


def _validate_readiness_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != "shopify_translation_csv_json_small_batch_real_write_readiness_package":
        errors.append("csv_json_readiness_not_ready")
    if report.get("readiness_status") != READY_READINESS_STATUS:
        errors.append("csv_json_readiness_not_ready")
    if report.get("readiness_package_only") is not True:
        errors.append("csv_json_readiness_not_ready")
    if report.get("plan_source") != EXPECTED_PLAN_SOURCE:
        errors.append("csv_json_readiness_not_ready")
    if report.get("manual_human_approval_required") is not True:
        errors.append("csv_json_readiness_not_ready")
    if report.get("real_write_allowed") is not False:
        errors.append("precondition_not_no_write")
    if _report_has_write_or_external_action(report):
        errors.append("precondition_not_no_write")
    entries = _normalized_entries({"entries": report.get("entries") or []})
    errors.extend(_validate_entries(entries))
    return _unique(errors)


def _validate_plan_execute_match(plan_report: dict, execute_report: dict) -> list[str]:
    plan_entries = _normalized_entries(plan_report)
    execute_entries = _normalized_entries({"entries": execute_report.get("entries") or execute_report.get("planned_entries") or []})
    return _validate_matching_reports(plan_report, execute_report, plan_entries, execute_entries)


def _validate_plan_readiness_match(plan_report: dict, readiness_report: dict) -> list[str]:
    plan_entries = _normalized_entries(plan_report)
    readiness_entries = _normalized_entries({"entries": readiness_report.get("entries") or []})
    return _validate_matching_reports(plan_report, readiness_report, plan_entries, readiness_entries)


def _validate_execute_readiness_match(execute_report: dict, readiness_report: dict) -> list[str]:
    execute_entries = _normalized_entries({"entries": execute_report.get("entries") or execute_report.get("planned_entries") or []})
    readiness_entries = _normalized_entries({"entries": readiness_report.get("entries") or []})
    return _validate_matching_reports(execute_report, readiness_report, execute_entries, readiness_entries)


def _validate_matching_reports(left_report: dict, right_report: dict, left_entries: list[dict], right_entries: list[dict]) -> list[str]:
    errors = []
    if left_report.get("product_id") != right_report.get("product_id"):
        errors.append("multiple_products")
    if left_report.get("locale") != right_report.get("locale"):
        errors.append("multiple_locales")
    if int(left_report.get("entry_count") or len(left_entries)) != int(right_report.get("entry_count") or len(right_entries)):
        errors.append("csv_json_apply_plan_not_ready")
    if _entry_signature(left_entries) != _entry_signature(right_entries):
        errors.append("csv_json_apply_plan_not_ready")
    return _unique(errors)


def _validate_entries(entries: list[dict]) -> list[str]:
    errors = []
    if not entries:
        errors.append("csv_json_apply_plan_not_ready")
    if len(entries) > MAX_ENTRIES:
        errors.append("too_many_entries")
    product_ids = {entry.get("product_id") for entry in entries if entry.get("product_id")}
    locales = {entry.get("locale") for entry in entries if entry.get("locale")}
    if len(product_ids) != 1:
        errors.append("multiple_products")
    if len(locales) != 1:
        errors.append("multiple_locales")
    for product_id in product_ids:
        if not PRODUCT_GID_RE.match(product_id or ""):
            errors.append("multiple_products")
    for locale in locales:
        if locale != SUPPORTED_LOCALE:
            errors.append("multiple_locales")
    for entry in entries:
        field = entry.get("field", "")
        value = entry.get("proposed_value", "")
        if field not in ALLOWED_FIELDS:
            errors.append("invalid_field")
            continue
        if not value:
            errors.append("empty_proposed_value")
        if len(value) > FIELD_MAX_CHARS[field]:
            errors.append("value_too_long")
        if entry.get("validation_status") not in ("", "valid"):
            errors.append("csv_json_apply_plan_not_ready")
    return _unique(errors)


def _report_has_write_or_external_action(report: dict) -> bool:
    true_flags = [
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "readback_performed",
        "rollback_performed",
        "publish_performed",
        "bulk_write_performed",
        "real_apply_performed",
        "small_batch_write_performed",
        "restore_performed",
    ]
    if any(report.get(flag) is True for flag in true_flags):
        return True
    for flag in ["no_new_shopify_writes_performed", "all_new_actions_no_write_confirmed"]:
        if flag in report and report.get(flag) is not True:
            return True
    return False


def _normalized_entries(report: dict) -> list[dict]:
    raw_entries = report.get("entries") if isinstance(report.get("entries"), list) else []
    entries = []
    for index, entry in enumerate(raw_entries, start=1):
        field = str(entry.get("field") or "")
        value = str(entry.get("proposed_value") or "")
        entries.append(
            {
                "entry_index": int(entry.get("entry_index") or index),
                "row_number": int(entry.get("row_number") or entry.get("entry_index") or index),
                "product_id": str(entry.get("product_id") or report.get("product_id") or ""),
                "locale": str(entry.get("locale") or report.get("locale") or ""),
                "field": field,
                "proposed_value": value,
                "proposed_value_chars": int(entry.get("proposed_value_chars") or len(value)),
                "max_chars": int(entry.get("max_chars") or FIELD_MAX_CHARS.get(field, 0)),
                "validation_status": str(entry.get("validation_status") or ""),
            }
        )
    return entries


def _entry_signature(entries: list[dict]) -> list[tuple[str, str, str, str]]:
    return [
        (
            entry.get("product_id", ""),
            entry.get("locale", ""),
            entry.get("field", ""),
            entry.get("proposed_value", ""),
        )
        for entry in entries
    ]


def _single_value(values: list[str]) -> str:
    unique_values = _unique([value for value in values if value])
    return unique_values[0] if len(unique_values) == 1 else ""


def _source_plan_summary(report: dict) -> dict:
    return {
        "source_plan_loaded": bool(report),
        "source_task": report.get("task", "") if report else "",
        "source_plan_status": report.get("plan_status", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_input_source": report.get("input_source", "") if report else "",
        "source_manual_review_required": report.get("manual_review_required") is True if report else False,
        "source_real_write_allowed": report.get("real_write_allowed") is True if report else False,
    }


def _source_execute_dry_run_summary(report: dict) -> dict:
    return {
        "source_execute_loaded": bool(report),
        "source_task": report.get("task", "") if report else "",
        "source_mode": report.get("mode", "") if report else "",
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_plan_source": report.get("plan_source", "") if report else "",
        "source_plan_status": report.get("plan_status", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_shopify_api_call_performed": bool(report.get("shopify_api_call_performed")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "source_rollback_performed": bool(report.get("rollback_performed")) if report else False,
        "source_blocking_conditions": report.get("blocking_conditions", []) if report else [],
    }


def _source_readiness_summary(report: dict) -> dict:
    return {
        "source_readiness_loaded": bool(report),
        "source_task": report.get("task", "") if report else "",
        "source_readiness_status": report.get("readiness_status", "") if report else "",
        "source_plan_source": report.get("plan_source", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_manual_human_approval_required": report.get("manual_human_approval_required") is True
        if report
        else False,
        "source_real_write_allowed": report.get("real_write_allowed") is True if report else False,
        "source_blocking_conditions": report.get("blocking_conditions", []) if report else [],
    }


def _manual_test_checks(plan_report: dict, execute_report: dict, readiness_report: dict, entries: list[dict]) -> dict:
    return {
        "csv_json_plan_ready": plan_report.get("plan_status") == READY_PLAN_STATUS if plan_report else False,
        "execute_report_is_csv_json_dry_run": (
            execute_report.get("plan_source") == EXPECTED_PLAN_SOURCE
            and execute_report.get("execution_status") == READY_EXECUTE_STATUS
        )
        if execute_report
        else False,
        "readiness_report_ready": readiness_report.get("readiness_status") == READY_READINESS_STATUS
        if readiness_report
        else False,
        "preconditions_no_write": all(
            not _report_has_write_or_external_action(report)
            for report in [plan_report, execute_report, readiness_report]
            if report
        ),
        "entry_count": len(entries),
        "entry_count_allowed": 0 < len(entries) <= MAX_ENTRIES,
        "product_count": len({entry.get("product_id") for entry in entries if entry.get("product_id")}),
        "locale_count": len({entry.get("locale") for entry in entries if entry.get("locale")}),
        "fields_allowed": all(entry.get("field") in ALLOWED_FIELDS for entry in entries),
        "values_non_empty": all(bool(entry.get("proposed_value")) for entry in entries),
        "value_lengths_allowed": all(
            entry.get("field") in FIELD_MAX_CHARS
            and len(entry.get("proposed_value", "")) <= FIELD_MAX_CHARS[entry.get("field")]
            for entry in entries
        ),
    }


def _manual_review_checklist(entries: list[dict]) -> list[str]:
    fields = ", ".join([entry.get("field", "") for entry in entries])
    return [
        "Review the CSV/JSON plan report before running any real command.",
        "Confirm the product_id is correct.",
        "Confirm the locale is ja.",
        f"Confirm fields are limited to: {fields}.",
        "Confirm every proposed value is correct.",
        "Confirm the dry-run execute report is from plan_source=csv_json.",
        "Confirm the readiness package is ready for human approval.",
        "Set the exact ACK only in the manual shell used for the real-run.",
        "Run the post-write audit immediately after the manual real-run.",
        "Do not run rollback automatically; rollback requires a separate approval package.",
    ]


def _future_real_run_safety_notes() -> list[str]:
    return [
        "This package does not execute the real-run command.",
        "The real-run command may call Shopify only when manually run later with the exact ACK.",
        "The execute task must immediately read back every entry after the mutation.",
        "Success is allowed only when every readback value exactly matches the proposed value.",
        "Rollback is never automatic.",
        "Audit must be run after the manual real-run.",
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
        "automatic rollback",
        "batch expansion",
        "full-store scan",
        "multiple products",
        "multiple locales",
        "unsupported fields",
        "git push",
    ]


def _manual_real_run_command_preview() -> list[str]:
    workspace = Path.cwd()
    return [
        f'cd "{workspace}"',
        "",
        f'$env:{ACK_ENV_NAME}="{ACK_VALUE}"',
        "",
        "python remote_approval_runner.py --task shopify_translation_small_batch_apply_execute --mode real-run --approval local",
        "",
        f"Remove-Item Env:{ACK_ENV_NAME}",
        "",
        "python remote_approval_runner.py --task shopify_translation_small_batch_post_write_audit_package --approval local",
    ]


def _real_run_success_fields_to_check() -> dict:
    return {
        "execution_status": "small_batch_real_write_succeeded_and_verified",
        "plan_source": EXPECTED_PLAN_SOURCE,
        "entry_count": 2,
        "shopify_write_performed": True,
        "mutation_performed": True,
        "translations_register_called": True,
        "readback_performed": True,
        "readback_all_entries_match": True,
        "rollback_approval_required": False,
        "blocking_conditions": [],
    }


def _audit_success_fields_to_check() -> dict:
    return {
        "audit_status": "small_batch_post_write_audit_passed",
        "readback_all_entries_match": True,
        "rollback_needed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_csv_json_apply_plan_report": "blocked_missing_csv_json_apply_plan_report",
        "csv_json_apply_plan_json_invalid": "blocked_csv_json_apply_plan_not_ready",
        "csv_json_apply_plan_not_ready": "blocked_csv_json_apply_plan_not_ready",
        "missing_small_batch_execute_report": "blocked_missing_small_batch_execute_report",
        "small_batch_execute_json_invalid": "blocked_execute_report_not_csv_json_dry_run",
        "execute_report_not_csv_json_dry_run": "blocked_execute_report_not_csv_json_dry_run",
        "missing_csv_json_readiness_report": "blocked_missing_csv_json_readiness_report",
        "csv_json_readiness_json_invalid": "blocked_csv_json_readiness_not_ready",
        "csv_json_readiness_not_ready": "blocked_csv_json_readiness_not_ready",
        "too_many_entries": "blocked_too_many_entries",
        "multiple_products": "blocked_multiple_products",
        "multiple_locales": "blocked_multiple_locales",
        "invalid_field": "blocked_invalid_field",
        "empty_proposed_value": "blocked_empty_proposed_value",
        "value_too_long": "blocked_value_too_long",
        "precondition_not_no_write": "blocked_precondition_not_no_write",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _manual_test_package_status(blocking_conditions: list[str]) -> str:
    if not blocking_conditions:
        return READY_MANUAL_TEST_STATUS
    for status in [
        "blocked_missing_csv_json_apply_plan_report",
        "blocked_missing_small_batch_execute_report",
        "blocked_missing_csv_json_readiness_report",
        "blocked_csv_json_apply_plan_not_ready",
        "blocked_execute_report_not_csv_json_dry_run",
        "blocked_csv_json_readiness_not_ready",
        "blocked_too_many_entries",
        "blocked_multiple_products",
        "blocked_multiple_locales",
        "blocked_invalid_field",
        "blocked_precondition_not_no_write",
    ]:
        if status in blocking_conditions:
            return status
    return "csv_json_small_batch_manual_real_run_test_package_blocked"


def _safety_summary() -> dict:
    return {
        "manual_test_package_only": True,
        "manual_test_required": True,
        "real_run_not_executed_by_this_task": True,
        "shopify_api_call_allowed_in_this_phase": False,
        "shopify_write_allowed_in_this_phase": False,
        "mutation_allowed_in_this_phase": False,
        "translations_register_allowed_in_this_phase": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
        "publish_allowed_in_this_phase": False,
        "bulk_write_allowed_in_this_phase": False,
        "real_apply_allowed_in_this_phase": False,
        "max_entries": MAX_ENTRIES,
        "max_products": 1,
        "max_locales": 1,
        "allowed_fields": ALLOWED_FIELDS,
        "required_ack_env_name": ACK_ENV_NAME,
        "required_ack_env_value": ACK_VALUE,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    MANUAL_TEST_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(MANUAL_TEST_JSON_PATH.read_text(encoding="utf-8"))
    return MANUAL_TEST_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    MANUAL_TEST_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return MANUAL_TEST_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Manual Test Package Status", "manual_test_package_status"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Entry Count", "entry_count"),
            ("Fields", "fields"),
            ("Plan Source", "plan_source"),
            ("Manual Test Required", "manual_test_required"),
            ("Real Run Not Executed By This Task", "real_run_not_executed_by_this_task"),
            ("Required ACK Env Name", "required_ack_env_name"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Entries", payload.get("entries", [])),
            ("Proposed Values", payload.get("proposed_values", {})),
            ("Manual Real Run Command Preview", payload.get("manual_real_run_command_preview", [])),
            ("Real Run Success Fields To Check", payload.get("real_run_success_fields_to_check", {})),
            ("Audit Success Fields To Check", payload.get("audit_success_fields_to_check", {})),
            ("Source Plan Summary", payload.get("source_plan_summary", {})),
            ("Source Execute Dry Run Summary", payload.get("source_execute_dry_run_summary", {})),
            ("Source Readiness Summary", payload.get("source_readiness_summary", {})),
            ("Manual Test Checks", payload.get("manual_test_checks", {})),
            ("Manual Review Checklist", payload.get("manual_review_checklist", [])),
            ("Future Real Run Safety Notes", payload.get("future_real_run_safety_notes", [])),
            ("Forbidden Actions", payload.get("forbidden_actions", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
            ("Parse Errors", payload.get("parse_errors", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify CSV/JSON Small Batch Manual Real-Run Test Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 360px; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify CSV/JSON Small Batch Manual Real-Run Test Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Manual Test Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local Phase 14 reports only.</li>
    <li>No Shopify API call, write, mutation, translationsRegister, readback, rollback, publish, bulk write, or apply was performed.</li>
    <li>The real-run command preview is for manual execution later and is not executed by this task.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(manual_test_package_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "CSV/JSON small batch manual real-run test package blocked: " + ", ".join(blocking_conditions)
    return (
        "CSV/JSON small batch manual real-run test package generated with status "
        f"{manual_test_package_status}. No Shopify action performed."
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify CSV/JSON small batch manual real-run test package generated.\n"
        f"Manual test package status: {payload.get('manual_test_package_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locale: {payload.get('locale')}\n"
        f"Entry count: {payload.get('entry_count')}\n"
        f"Fields: {payload.get('fields')}\n"
        f"Plan source: {payload.get('plan_source')}\n"
        f"Real run not executed by this task: {payload.get('real_run_not_executed_by_this_task')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Manual test package JSON:\n"
        f"{json_path}\n\n"
        "Manual test package HTML:\n"
        f"{html_path}\n"
        "Manual test package only. No Shopify API call, mutation, translationsRegister, readback, rollback, publish, bulk write, apply, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep CSV/JSON small batch manual test package files\n"
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
