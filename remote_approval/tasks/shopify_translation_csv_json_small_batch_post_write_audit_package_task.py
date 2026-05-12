import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_csv_json_small_batch_post_write_audit_package"
COMMAND_LABEL = "shopify_translation_csv_json_small_batch_post_write_audit_package"
SOURCE_CSV_JSON_PLAN_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_apply_plan_package.json"
SOURCE_SMALL_BATCH_EXECUTE_PATH = LOG_DIR / "shopify_translation_small_batch_apply_execute.json"
SOURCE_CSV_JSON_READINESS_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_real_write_readiness_package.json"
SOURCE_CSV_JSON_MANUAL_TEST_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_manual_real_run_test_package.json"
CSV_JSON_POST_WRITE_AUDIT_JSON_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_post_write_audit_package.json"
CSV_JSON_POST_WRITE_AUDIT_HTML_PATH = LOG_DIR / "shopify_translation_csv_json_small_batch_post_write_audit_package.html"

EXPECTED_EXECUTE_TASK = "shopify_translation_small_batch_apply_execute"
EXPECTED_EXECUTION_STATUS = "small_batch_real_write_succeeded_and_verified"
EXPECTED_PLAN_SOURCE = "csv_json"
READY_PLAN_STATUS = "csv_json_small_batch_apply_plan_ready_for_manual_review"
READY_READINESS_STATUS = "csv_json_small_batch_real_write_ready_for_human_approval"
READY_MANUAL_TEST_STATUS = "csv_json_small_batch_manual_real_run_test_ready"
READY_AUDIT_STATUS = "csv_json_small_batch_post_write_audit_passed"
ALLOWED_SOURCE_MODES = {"real-run", "execute-real-write"}
ALLOWED_FIELDS = ["meta_title", "meta_description"]
MAX_ENTRIES = 5


def run_shopify_translation_csv_json_small_batch_post_write_audit_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    plan_report = {}
    execute_report = {}
    readiness_report = {}
    manual_test_report = {}

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

    try:
        manual_test_report = _read_json(SOURCE_CSV_JSON_MANUAL_TEST_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"CSV/JSON manual test package JSON not found: {exc}")
        validation_errors.append("missing_csv_json_manual_test_package_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse CSV/JSON manual test package JSON: {exc}")
        validation_errors.append("csv_json_manual_test_package_json_invalid")

    if plan_report:
        validation_errors.extend(_validate_plan_report(plan_report))
    if execute_report:
        validation_errors.extend(_validate_execute_report(execute_report))
    if readiness_report:
        validation_errors.extend(_validate_readiness_report(readiness_report))
    if manual_test_report:
        validation_errors.extend(_validate_manual_test_report(manual_test_report))
    if plan_report and execute_report:
        validation_errors.extend(_validate_report_match(plan_report, execute_report))
    if plan_report and readiness_report:
        validation_errors.extend(_validate_report_match(plan_report, readiness_report))
    if plan_report and manual_test_report:
        validation_errors.extend(_validate_report_match(plan_report, manual_test_report))

    blocking_conditions = _blocking_conditions(validation_errors)
    audit_status = _audit_status(blocking_conditions, execute_report)
    success = audit_status == READY_AUDIT_STATUS
    source_summary = _source_execution_summary(execute_report)
    plan_summary = _source_plan_summary(plan_report)
    readiness_summary = _source_readiness_summary(readiness_report)
    manual_test_summary = _source_manual_test_summary(manual_test_report)
    audited_fields = _audited_fields(execute_report, plan_report)
    proposed_values = _proposed_values(execute_report, plan_report)
    final_readback_values = _final_readback_values(execute_report)
    restore_summary = _restore_values_summary(execute_report, plan_report)
    rollback_summary = _rollback_summary(success, restore_summary)
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "csv-json-small-batch-post-write-audit-only",
        "command_label": COMMAND_LABEL,
        "source_csv_json_small_batch_apply_plan_path": str(SOURCE_CSV_JSON_PLAN_PATH),
        "source_small_batch_apply_execute_path": str(SOURCE_SMALL_BATCH_EXECUTE_PATH),
        "source_csv_json_small_batch_real_write_readiness_path": str(SOURCE_CSV_JSON_READINESS_PATH),
        "source_csv_json_small_batch_manual_real_run_test_path": str(SOURCE_CSV_JSON_MANUAL_TEST_PATH),
        "json_csv_json_small_batch_post_write_audit_package_path": str(CSV_JSON_POST_WRITE_AUDIT_JSON_PATH),
        "html_csv_json_small_batch_post_write_audit_package_path": str(CSV_JSON_POST_WRITE_AUDIT_HTML_PATH),
        "success": success,
        "audit_status": audit_status,
        "product_id": source_summary["source_product_id"] or plan_summary["source_product_id"],
        "locale": source_summary["source_locale"] or plan_summary["source_locale"],
        "entry_count": source_summary["source_entry_count"] or plan_summary["source_entry_count"],
        "audited_fields": audited_fields,
        "fields": audited_fields,
        "plan_source": EXPECTED_PLAN_SOURCE,
        "proposed_values": proposed_values,
        "final_readback_values": final_readback_values,
        "readback_all_entries_match": source_summary["source_readback_all_entries_match"],
        "rollback_needed": rollback_summary["rollback_needed"],
        "rollback_optional_restore_possible": rollback_summary["rollback_optional_restore_possible"],
        "rollback_optional_restore_requires_separate_approval": rollback_summary[
            "rollback_optional_restore_requires_separate_approval"
        ],
        "manual_review_completed": False,
        "source_execution_report_summary": source_summary,
        "source_plan_summary": plan_summary,
        "source_readiness_summary": readiness_summary,
        "source_manual_test_package_summary": manual_test_summary,
        "write_summary": _write_summary(execute_report),
        "readback_summary": _readback_summary(execute_report),
        "verification_summary": _verification_summary(execute_report, success),
        "restore_values_summary": restore_summary,
        "rollback_summary": rollback_summary,
        "post_write_observations": _post_write_observations(success),
        "next_phase_recommendations": _next_phase_recommendations(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(source_summary),
        "audit_package_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "real_apply_performed": False,
        "automatic_rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(audit_status, blocking_conditions),
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
        "json_csv_json_small_batch_post_write_audit_package_path": str(json_path),
        "html_csv_json_small_batch_post_write_audit_package_path": str(html_path),
        "audit_status": audit_status,
        "audit_package_only": True,
        "product_id": payload["product_id"],
        "locale": payload["locale"],
        "entry_count": payload["entry_count"],
        "plan_source": EXPECTED_PLAN_SOURCE,
        "source_execution_status": source_summary["source_execution_status"],
        "source_mode": source_summary["source_mode"],
        "source_shopify_write_performed": source_summary["source_shopify_write_performed"],
        "source_translations_register_called": source_summary["source_translations_register_called"],
        "source_mutation_performed": source_summary["source_mutation_performed"],
        "source_readback_performed": source_summary["source_readback_performed"],
        "source_entry_count": source_summary["source_entry_count"],
        "readback_all_entries_match": source_summary["source_readback_all_entries_match"],
        "rollback_needed": rollback_summary["rollback_needed"],
        "rollback_optional_restore_possible": rollback_summary["rollback_optional_restore_possible"],
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
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
    if int(report.get("entry_count") or 0) < 1 or int(report.get("entry_count") or 0) > MAX_ENTRIES:
        errors.append("scope_mismatch")
    if report.get("blocking_conditions") not in ([], None):
        errors.append("csv_json_apply_plan_not_ready")
    if _report_has_side_effects(report):
        errors.append("unexpected_side_effects")
    return _unique(errors)


def _validate_readiness_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != "shopify_translation_csv_json_small_batch_real_write_readiness_package":
        errors.append("csv_json_readiness_not_ready")
    if report.get("readiness_status") != READY_READINESS_STATUS:
        errors.append("csv_json_readiness_not_ready")
    if report.get("plan_source") != EXPECTED_PLAN_SOURCE:
        errors.append("csv_json_readiness_not_ready")
    if report.get("blocking_conditions") not in ([], None):
        errors.append("csv_json_readiness_not_ready")
    if _report_has_side_effects(report):
        errors.append("unexpected_side_effects")
    return _unique(errors)


def _validate_manual_test_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != "shopify_translation_csv_json_small_batch_manual_real_run_test_package":
        errors.append("csv_json_manual_test_package_not_ready")
    if report.get("manual_test_package_status") != READY_MANUAL_TEST_STATUS:
        errors.append("csv_json_manual_test_package_not_ready")
    if report.get("plan_source") != EXPECTED_PLAN_SOURCE:
        errors.append("csv_json_manual_test_package_not_ready")
    if report.get("blocking_conditions") not in ([], None):
        errors.append("csv_json_manual_test_package_not_ready")
    if _report_has_side_effects(report):
        errors.append("unexpected_side_effects")
    return _unique(errors)


def _validate_execute_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_EXECUTE_TASK:
        errors.append("csv_json_small_batch_real_write_not_successful")
    if report.get("mode") not in ALLOWED_SOURCE_MODES:
        errors.append("source_not_real_run")
    if report.get("plan_source") != EXPECTED_PLAN_SOURCE:
        errors.append("execute_report_not_csv_json_plan_source")
    if report.get("execution_status") != EXPECTED_EXECUTION_STATUS:
        errors.append("csv_json_small_batch_real_write_not_successful")
    if not (0 < int(report.get("entry_count") or 0) <= MAX_ENTRIES):
        errors.append("scope_mismatch")
    fields = _audited_fields(report, {})
    if not fields or any(field not in ALLOWED_FIELDS for field in fields):
        errors.append("scope_mismatch")
    if report.get("shopify_api_call_performed") is not True:
        errors.append("csv_json_small_batch_real_write_not_successful")
    if report.get("shopify_write_performed") is not True:
        errors.append("csv_json_small_batch_real_write_not_successful")
    if report.get("mutation_performed") is not True:
        errors.append("csv_json_small_batch_real_write_not_successful")
    if report.get("translations_register_called") is not True:
        errors.append("csv_json_small_batch_real_write_not_successful")
    if report.get("readback_performed") is not True:
        errors.append("csv_json_small_batch_readback_mismatch")
    if report.get("readback_all_entries_match") is not True:
        errors.append("csv_json_small_batch_readback_mismatch")
    if int(report.get("readback_matched_entry_count") or 0) != int(report.get("entry_count") or 0):
        errors.append("csv_json_small_batch_readback_mismatch")
    if report.get("rollback_approval_required") is not False:
        errors.append("csv_json_small_batch_requires_rollback_review")
    if report.get("rollback_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("automatic_rollback_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("publish_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("bulk_write_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("small_batch_write_performed") is not True:
        errors.append("csv_json_small_batch_real_write_not_successful")
    if report.get("blocking_conditions") not in ([], None):
        errors.append("csv_json_small_batch_real_write_not_successful")
    if _real_write_count(report) not in (0, int(report.get("entry_count") or 0)):
        errors.append("scope_mismatch")
    for item in _readback_results(report):
        if item.get("field") not in ALLOWED_FIELDS:
            errors.append("scope_mismatch")
        if item.get("matches_proposed_value") is not True:
            errors.append("csv_json_small_batch_readback_mismatch")
    return _unique(errors)


def _validate_report_match(reference_report: dict, candidate_report: dict) -> list[str]:
    errors = []
    if reference_report.get("product_id") != candidate_report.get("product_id"):
        errors.append("scope_mismatch")
    if reference_report.get("locale") != candidate_report.get("locale"):
        errors.append("scope_mismatch")
    if int(reference_report.get("entry_count") or 0) != int(candidate_report.get("entry_count") or 0):
        errors.append("scope_mismatch")
    reference_fields = _fields_from_report(reference_report)
    candidate_fields = _fields_from_report(candidate_report)
    if reference_fields != candidate_fields:
        errors.append("scope_mismatch")
    reference_values = _proposed_values(reference_report, reference_report)
    candidate_values = _proposed_values(candidate_report, reference_report)
    if reference_values != candidate_values:
        errors.append("scope_mismatch")
    return _unique(errors)


def _report_has_side_effects(report: dict) -> bool:
    return any(
        report.get(flag) is True
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
            "small_batch_write_performed",
            "restore_performed",
        ]
    )


def _source_execution_summary(report: dict) -> dict:
    return {
        "source_task": report.get("task", "") if report else "",
        "source_mode": report.get("mode", "") if report else "",
        "source_plan_source": report.get("plan_source", "") if report else "",
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_shopify_api_call_performed": bool(report.get("shopify_api_call_performed")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "source_readback_all_entries_match": bool(report.get("readback_all_entries_match")) if report else False,
        "source_readback_matched_entry_count": int(report.get("readback_matched_entry_count") or 0) if report else 0,
        "source_rollback_approval_required": bool(report.get("rollback_approval_required")) if report else False,
        "source_rollback_performed": bool(report.get("rollback_performed")) if report else False,
        "source_automatic_rollback_performed": bool(report.get("automatic_rollback_performed")) if report else False,
        "source_publish_performed": bool(report.get("publish_performed")) if report else False,
        "source_bulk_write_performed": bool(report.get("bulk_write_performed")) if report else False,
        "source_small_batch_write_performed": bool(report.get("small_batch_write_performed")) if report else False,
        "source_real_write_count": _real_write_count(report),
        "source_blocking_conditions": report.get("blocking_conditions", []) if report else [],
    }


def _source_plan_summary(report: dict) -> dict:
    return {
        "source_plan_loaded": bool(report),
        "source_task": report.get("task", "") if report else "",
        "source_plan_status": report.get("plan_status", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_fields": _fields_from_report(report),
        "source_plan_source": report.get("plan_source", EXPECTED_PLAN_SOURCE) if report else "",
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
        "source_fields": _fields_from_report(report),
    }


def _source_manual_test_summary(report: dict) -> dict:
    return {
        "source_manual_test_loaded": bool(report),
        "source_task": report.get("task", "") if report else "",
        "source_manual_test_package_status": report.get("manual_test_package_status", "") if report else "",
        "source_plan_source": report.get("plan_source", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_fields": _fields_from_report(report),
    }


def _write_summary(report: dict) -> dict:
    return {
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_plan_source": report.get("plan_source", "") if report else "",
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "source_small_batch_write_performed": bool(report.get("small_batch_write_performed")) if report else False,
        "source_bulk_write_performed": bool(report.get("bulk_write_performed")) if report else False,
        "real_write_count": _real_write_count(report),
        "proposed_values": _proposed_values(report, {}),
    }


def _readback_summary(report: dict) -> dict:
    return {
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "readback_results": _readback_results(report),
        "readback_all_entries_match": bool(report.get("readback_all_entries_match")) if report else False,
        "readback_matched_entry_count": int(report.get("readback_matched_entry_count") or 0) if report else 0,
        "final_readback_values": _final_readback_values(report),
    }


def _verification_summary(report: dict, audit_passed: bool) -> dict:
    verification = report.get("verification_summary") or {}
    return {
        "source_verification_passed": bool(verification.get("verification_passed")) if report else False,
        "source_readback_all_entries_match": bool(report.get("readback_all_entries_match")) if report else False,
        "source_readback_matched_entry_count": int(report.get("readback_matched_entry_count") or 0) if report else 0,
        "audit_verification_passed": audit_passed,
    }


def _restore_values_summary(execute_report: dict, plan_report: dict) -> dict:
    restore_values = {}
    missing_fields = []
    for entry in _planned_entries(execute_report, plan_report):
        field = entry.get("field")
        restore_value = entry.get("current_value_if_known", "")
        if field in ALLOWED_FIELDS and restore_value:
            restore_values[field] = restore_value
        elif field in ALLOWED_FIELDS:
            missing_fields.append(field)
    complete = bool(restore_values) and not missing_fields
    return {
        "restore_value_source": "local_current_value_if_known" if complete else "missing_or_not_recorded",
        "restore_values": restore_values,
        "restore_values_complete": complete,
        "missing_restore_value_fields": _unique(missing_fields),
        "manual_backup_review_required": not complete,
    }


def _rollback_summary(audit_passed: bool, restore_summary: dict) -> dict:
    restore_possible = bool(restore_summary.get("restore_values_complete"))
    return {
        "rollback_needed": not audit_passed,
        "rollback_optional_restore_possible": restore_possible,
        "rollback_optional_restore_requires_separate_approval": True,
        "rollback_approval_required": False if audit_passed else True,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "restore_value_source": restore_summary.get("restore_value_source"),
        "rollback_note": (
            "No rollback required because all CSV/JSON small batch readback values matched proposed values."
            if audit_passed
            else "Rollback review would require a separate approval package after source write is verified."
        ),
    }


def _fields_from_report(report: dict) -> list[str]:
    if not report:
        return []
    if isinstance(report.get("audited_fields"), list):
        return _unique([field for field in report.get("audited_fields") if field])
    if isinstance(report.get("fields"), list):
        return _unique([field for field in report.get("fields") if field])
    entries = report.get("entries") or report.get("planned_entries") or []
    return _unique([entry.get("field") for entry in entries if entry.get("field")])


def _audited_fields(execute_report: dict, plan_report: dict) -> list[str]:
    fields = [item.get("field") for item in _readback_results(execute_report) if item.get("field")]
    if not fields:
        fields = _fields_from_report(execute_report)
    if not fields:
        fields = _fields_from_report(plan_report)
    return _unique(fields)


def _planned_entries(execute_report: dict, plan_report: dict) -> list[dict]:
    entries = execute_report.get("planned_entries") or execute_report.get("entries") or plan_report.get("entries") or []
    return entries if isinstance(entries, list) else []


def _proposed_values(execute_report: dict, plan_report: dict) -> dict:
    return {
        entry.get("field"): entry.get("proposed_value", "")
        for entry in _planned_entries(execute_report, plan_report)
        if entry.get("field") in ALLOWED_FIELDS
    }


def _final_readback_values(execute_report: dict) -> dict:
    return {
        item.get("field"): item.get("readback_value", "")
        for item in _readback_results(execute_report)
        if item.get("field") in ALLOWED_FIELDS
    }


def _readback_results(report: dict) -> list[dict]:
    if not report:
        return []
    readback = report.get("readback_summary") or {}
    results = readback.get("readback_results")
    return results if isinstance(results, list) else []


def _real_write_count(report: dict) -> int:
    if not report:
        return 0
    return int((report.get("translations_register_execution_summary") or {}).get("real_write_count") or 0)


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_csv_json_apply_plan_report": "blocked_missing_csv_json_apply_plan_report",
        "csv_json_apply_plan_json_invalid": "blocked_csv_json_apply_plan_not_ready",
        "csv_json_apply_plan_not_ready": "blocked_csv_json_apply_plan_not_ready",
        "missing_small_batch_execute_report": "blocked_missing_small_batch_execute_report",
        "small_batch_execute_json_invalid": "blocked_csv_json_small_batch_real_write_not_successful",
        "missing_csv_json_readiness_report": "blocked_missing_csv_json_readiness_report",
        "csv_json_readiness_json_invalid": "blocked_csv_json_readiness_not_ready",
        "csv_json_readiness_not_ready": "blocked_csv_json_readiness_not_ready",
        "missing_csv_json_manual_test_package_report": "blocked_missing_csv_json_manual_test_package_report",
        "csv_json_manual_test_package_json_invalid": "blocked_csv_json_manual_test_package_not_ready",
        "csv_json_manual_test_package_not_ready": "blocked_csv_json_manual_test_package_not_ready",
        "source_not_real_run": "blocked_source_not_real_run",
        "execute_report_not_csv_json_plan_source": "blocked_execute_report_not_csv_json_plan_source",
        "csv_json_small_batch_real_write_not_successful": (
            "blocked_csv_json_small_batch_real_write_not_successful"
        ),
        "csv_json_small_batch_readback_mismatch": "blocked_csv_json_small_batch_readback_mismatch",
        "csv_json_small_batch_requires_rollback_review": (
            "blocked_csv_json_small_batch_requires_rollback_review"
        ),
        "scope_mismatch": "blocked_scope_mismatch",
        "unexpected_side_effects": "blocked_unexpected_side_effects",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _audit_status(blocking_conditions: list[str], execute_report: dict) -> str:
    if not execute_report:
        return "blocked_missing_small_batch_execute_report"
    if not blocking_conditions:
        return READY_AUDIT_STATUS
    for status in [
        "blocked_missing_csv_json_apply_plan_report",
        "blocked_missing_small_batch_execute_report",
        "blocked_missing_csv_json_readiness_report",
        "blocked_missing_csv_json_manual_test_package_report",
        "blocked_execute_report_not_csv_json_plan_source",
        "blocked_csv_json_small_batch_real_write_not_successful",
        "blocked_csv_json_small_batch_readback_mismatch",
        "blocked_csv_json_small_batch_requires_rollback_review",
        "blocked_scope_mismatch",
        "blocked_unexpected_side_effects",
        "blocked_source_not_real_run",
    ]:
        if status in blocking_conditions:
            return status
    return "csv_json_small_batch_post_write_audit_failed"


def _safety_summary(source_summary: dict) -> dict:
    return {
        "audit_package_only": True,
        "source_plan_source": source_summary["source_plan_source"],
        "source_shopify_write_performed": source_summary["source_shopify_write_performed"],
        "source_translations_register_called": source_summary["source_translations_register_called"],
        "source_mutation_performed": source_summary["source_mutation_performed"],
        "source_readback_performed": source_summary["source_readback_performed"],
        "shopify_api_call_allowed_in_this_phase": False,
        "shopify_write_allowed_in_this_phase": False,
        "mutation_allowed_in_this_phase": False,
        "translations_register_allowed_in_this_phase": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
        "publish_allowed_in_this_phase": False,
        "real_apply_allowed_in_this_phase": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _post_write_observations(audit_passed: bool) -> list[str]:
    if not audit_passed:
        return [
            "CSV/JSON small batch post-write audit did not pass.",
            "No new Shopify action was performed by this audit task.",
        ]
    return [
        "CSV/JSON small batch Shopify translation write succeeded.",
        "The write scope remained one product and one locale.",
        "Audited fields were limited to meta_title and meta_description.",
        "Every readback value matched the proposed value.",
        "No rollback, automatic rollback, publish, or bulk write was performed by the source task.",
    ]


def _next_phase_recommendations() -> list[str]:
    return [
        "Generate a CSV/JSON small batch rollback approval package if optional restore is desired.",
        "Do not expand beyond 5 entries without a separate safety phase.",
        "Do not enable multi-product or multi-locale CSV/JSON apply yet.",
        "Keep future CSV/JSON small batch writes behind explicit ACK and immediate readback.",
    ]


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    CSV_JSON_POST_WRITE_AUDIT_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(CSV_JSON_POST_WRITE_AUDIT_JSON_PATH.read_text(encoding="utf-8"))
    return CSV_JSON_POST_WRITE_AUDIT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    CSV_JSON_POST_WRITE_AUDIT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return CSV_JSON_POST_WRITE_AUDIT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Audit Status", "audit_status"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Entry Count", "entry_count"),
            ("Audited Fields", "audited_fields"),
            ("Plan Source", "plan_source"),
            ("Readback All Entries Match", "readback_all_entries_match"),
            ("Rollback Needed", "rollback_needed"),
            ("Manual Review Completed", "manual_review_completed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Source Execution Report Summary", payload.get("source_execution_report_summary", {})),
            ("Source Plan Summary", payload.get("source_plan_summary", {})),
            ("Source Readiness Summary", payload.get("source_readiness_summary", {})),
            ("Source Manual Test Package Summary", payload.get("source_manual_test_package_summary", {})),
            ("Proposed Values", payload.get("proposed_values", {})),
            ("Final Readback Values", payload.get("final_readback_values", {})),
            ("Write Summary", payload.get("write_summary", {})),
            ("Readback Summary", payload.get("readback_summary", {})),
            ("Verification Summary", payload.get("verification_summary", {})),
            ("Restore Values Summary", payload.get("restore_values_summary", {})),
            ("Rollback Summary", payload.get("rollback_summary", {})),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify CSV/JSON Small Batch Post-Write Audit Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 340px; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify CSV/JSON Small Batch Post-Write Audit Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Audit Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local Phase 14 reports only.</li>
    <li>No Shopify API call, write, mutation, translationsRegister, readback, rollback, publish, or apply was performed by this audit task.</li>
    <li>Prior source write facts are preserved separately under source summaries.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(audit_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "CSV/JSON small batch post-write audit blocked: " + ", ".join(blocking_conditions)
    return f"CSV/JSON small batch post-write audit completed with status {audit_status}. No new Shopify action performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify CSV/JSON small batch post-write audit package generated.\n"
        f"Audit status: {payload.get('audit_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locale: {payload.get('locale')}\n"
        f"Entry count: {payload.get('entry_count')}\n"
        f"Audited fields: {payload.get('audited_fields')}\n"
        f"Plan source: {payload.get('plan_source')}\n"
        f"Readback all entries match: {payload.get('readback_all_entries_match')}\n"
        f"Rollback needed: {payload.get('rollback_needed')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "CSV/JSON small batch post-write audit JSON:\n"
        f"{json_path}\n\n"
        "CSV/JSON small batch post-write audit HTML:\n"
        f"{html_path}\n"
        "Audit package only. No Shopify API call, mutation, translationsRegister, readback, rollback, publish, apply, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep CSV/JSON small batch post-write audit files\n"
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
