import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_small_batch_rollback_approval_package"
COMMAND_LABEL = "shopify_translation_small_batch_rollback_approval_package"
SOURCE_SMALL_BATCH_PLAN_PATH = LOG_DIR / "shopify_translation_small_batch_apply_plan_package.json"
SOURCE_SMALL_BATCH_EXECUTE_PATH = LOG_DIR / "shopify_translation_small_batch_apply_execute.json"
SOURCE_SMALL_BATCH_POST_WRITE_AUDIT_PATH = LOG_DIR / "shopify_translation_small_batch_post_write_audit_package.json"
SMALL_BATCH_ROLLBACK_APPROVAL_JSON_PATH = LOG_DIR / "shopify_translation_small_batch_rollback_approval_package.json"
SMALL_BATCH_ROLLBACK_APPROVAL_HTML_PATH = LOG_DIR / "shopify_translation_small_batch_rollback_approval_package.html"

EXPECTED_EXECUTE_TASK = "shopify_translation_small_batch_apply_execute"
EXPECTED_AUDIT_TASK = "shopify_translation_small_batch_post_write_audit_package"
EXPECTED_EXECUTION_STATUS = "small_batch_real_write_succeeded_and_verified"
EXPECTED_AUDIT_STATUS = "small_batch_post_write_audit_passed"
EXPECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
EXPECTED_LOCALE = "ja"
EXPECTED_ENTRY_COUNT = 2
ALLOWED_SOURCE_MODES = {"real-run", "execute-real-write"}
ALLOWED_FIELDS = ["meta_title", "meta_description"]


def run_shopify_translation_small_batch_rollback_approval_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    plan_report = {}
    execute_report = {}
    audit_report = {}

    try:
        execute_report = _read_json(SOURCE_SMALL_BATCH_EXECUTE_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Small batch execute JSON not found: {exc}")
        validation_errors.append("missing_small_batch_execute_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse small batch execute JSON: {exc}")
        validation_errors.append("small_batch_execute_json_invalid")

    try:
        audit_report = _read_json(SOURCE_SMALL_BATCH_POST_WRITE_AUDIT_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Small batch post-write audit JSON not found: {exc}")
        validation_errors.append("missing_small_batch_post_write_audit_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse small batch post-write audit JSON: {exc}")
        validation_errors.append("small_batch_post_write_audit_json_invalid")

    try:
        plan_report = _read_json(SOURCE_SMALL_BATCH_PLAN_PATH)
    except FileNotFoundError:
        plan_report = {}
        parse_errors.append("Optional small batch apply plan JSON not found; restore values may be incomplete.")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse optional small batch apply plan JSON: {exc}")
        plan_report = {}

    if execute_report:
        validation_errors.extend(_validate_execute_report(execute_report))
    if audit_report:
        validation_errors.extend(_validate_audit_report(audit_report, execute_report))

    blocking_conditions = _blocking_conditions(validation_errors)
    rollback_approval_status = _rollback_approval_status(blocking_conditions, execute_report, audit_report)
    success = rollback_approval_status == "small_batch_rollback_approval_package_ready_for_manual_review"
    fields = _fields(execute_report, audit_report, plan_report)
    restore_summary = _restore_values(plan_report, execute_report, fields)
    current_values_after_write = _current_values_after_write(execute_report, audit_report)
    proposed_values = _proposed_values(execute_report, audit_report, plan_report)
    restore_plan_status = (
        "restore_plan_ready_for_manual_review"
        if success and restore_summary["restore_values_complete"]
        else "restore_values_incomplete_manual_review_required"
    )
    rollback_optional_restore_possible = bool(success and restore_summary["restore_values_complete"])
    rollback_summary = _rollback_required_status(success, rollback_optional_restore_possible)
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "small-batch-rollback-approval-package-only",
        "command_label": COMMAND_LABEL,
        "source_small_batch_plan_path": str(SOURCE_SMALL_BATCH_PLAN_PATH),
        "source_small_batch_execute_path": str(SOURCE_SMALL_BATCH_EXECUTE_PATH),
        "source_small_batch_post_write_audit_path": str(SOURCE_SMALL_BATCH_POST_WRITE_AUDIT_PATH),
        "json_small_batch_rollback_approval_package_path": str(SMALL_BATCH_ROLLBACK_APPROVAL_JSON_PATH),
        "html_small_batch_rollback_approval_package_path": str(SMALL_BATCH_ROLLBACK_APPROVAL_HTML_PATH),
        "success": success,
        "rollback_approval_status": rollback_approval_status,
        "restore_plan_status": restore_plan_status,
        "product_id": _source_product_id(execute_report, audit_report),
        "locale": _source_locale(execute_report, audit_report),
        "entry_count": _source_entry_count(execute_report, audit_report),
        "fields": fields,
        "before_values": restore_summary["before_values"],
        "restore_values": restore_summary["restore_values"],
        "restore_value_source": restore_summary["restore_value_source"],
        "missing_restore_value_fields": restore_summary["missing_restore_value_fields"],
        "manual_backup_review_required": not restore_summary["restore_values_complete"],
        "current_values_after_write": current_values_after_write,
        "final_values": current_values_after_write,
        "proposed_values": proposed_values,
        "rollback_needed": False,
        "rollback_optional_restore_possible": rollback_optional_restore_possible,
        "rollback_optional_restore_requires_separate_approval": True,
        "restore_execution_task_required": True,
        "manual_human_approval_required_before_restore": True,
        "automatic_rollback_performed": False,
        "automatic_restore_performed": False,
        "rollback_scope": _rollback_scope(execute_report, audit_report, fields),
        "current_values_summary": _current_values_summary(current_values_after_write),
        "source_write_summary": _source_write_summary(execute_report),
        "source_audit_summary": _source_audit_summary(audit_report),
        "rollback_plan": _rollback_plan(restore_summary),
        "rollback_required_status": rollback_summary,
        "rollback_manual_approval_checklist": _rollback_manual_approval_checklist(),
        "rollback_execution_requirements": _rollback_execution_requirements(),
        "rollback_readback_requirements": _rollback_readback_requirements(),
        "rollback_forbidden_actions": _rollback_forbidden_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(),
        "rollback_approval_package_only": True,
        "rollback_execution_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "restore_performed": False,
        "publish_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(
            rollback_approval_status,
            blocking_conditions,
            restore_plan_status,
        ),
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
        "json_small_batch_rollback_approval_package_path": str(json_path),
        "html_small_batch_rollback_approval_package_path": str(html_path),
        "rollback_approval_status": rollback_approval_status,
        "restore_plan_status": restore_plan_status,
        "restore_value_source": restore_summary["restore_value_source"],
        "manual_backup_review_required": not restore_summary["restore_values_complete"],
        "rollback_approval_package_only": True,
        "rollback_needed": False,
        "rollback_optional_restore_possible": rollback_optional_restore_possible,
        "rollback_optional_restore_requires_separate_approval": True,
        "restore_execution_task_required": True,
        "manual_human_approval_required_before_restore": True,
        "source_execution_status": (execute_report or {}).get("execution_status", ""),
        "audit_status": (audit_report or {}).get("audit_status", ""),
        "product_id": payload["product_id"],
        "locale": payload["locale"],
        "entry_count": payload["entry_count"],
        "rollback_execution_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "restore_performed": False,
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


def _validate_execute_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_EXECUTE_TASK:
        errors.append("small_batch_execute_report_task_mismatch")
    if report.get("mode") not in ALLOWED_SOURCE_MODES:
        errors.append("small_batch_real_write_not_successful")
    if report.get("execution_status") != EXPECTED_EXECUTION_STATUS:
        errors.append("small_batch_real_write_not_successful")
    if report.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.append("scope_mismatch")
    if report.get("locale") != EXPECTED_LOCALE:
        errors.append("scope_mismatch")
    if int(report.get("entry_count") or 0) != EXPECTED_ENTRY_COUNT:
        errors.append("scope_mismatch")
    if _fields(report, {}, {}) != ALLOWED_FIELDS:
        errors.append("scope_mismatch")
    if report.get("readback_all_entries_match") is not True:
        errors.append("small_batch_readback_mismatch")
    if int(report.get("readback_matched_entry_count") or 0) != EXPECTED_ENTRY_COUNT:
        errors.append("small_batch_readback_mismatch")
    if report.get("rollback_approval_required") is not False:
        errors.append("small_batch_requires_rollback_review")
    if report.get("shopify_write_performed") is not True:
        errors.append("small_batch_real_write_not_successful")
    if report.get("translations_register_called") is not True:
        errors.append("small_batch_real_write_not_successful")
    if report.get("mutation_performed") is not True:
        errors.append("small_batch_real_write_not_successful")
    if report.get("readback_performed") is not True:
        errors.append("small_batch_readback_mismatch")
    if report.get("blocking_conditions") not in ([], None):
        errors.append("small_batch_real_write_not_successful")
    if _has_unexpected_side_effects(report):
        errors.append("unexpected_side_effects")
    return _unique(errors)


def _validate_audit_report(audit_report: dict, execute_report: dict) -> list[str]:
    errors = []
    if audit_report.get("task") != EXPECTED_AUDIT_TASK:
        errors.append("small_batch_post_write_audit_not_passed")
    if audit_report.get("audit_status") != EXPECTED_AUDIT_STATUS:
        errors.append("small_batch_post_write_audit_not_passed")
    if audit_report.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.append("scope_mismatch")
    if audit_report.get("locale") != EXPECTED_LOCALE:
        errors.append("scope_mismatch")
    if int(audit_report.get("entry_count") or 0) != EXPECTED_ENTRY_COUNT:
        errors.append("scope_mismatch")
    if _fields(execute_report, audit_report, {}) != ALLOWED_FIELDS:
        errors.append("scope_mismatch")
    if audit_report.get("readback_all_entries_match") is not True:
        errors.append("small_batch_readback_mismatch")
    if audit_report.get("rollback_needed") is not False:
        errors.append("small_batch_requires_rollback_review")
    if audit_report.get("blocking_conditions") not in ([], None):
        errors.append("small_batch_post_write_audit_not_passed")
    if audit_report.get("publish_performed") is True:
        errors.append("unexpected_side_effects")
    if audit_report.get("rollback_performed") is True:
        errors.append("unexpected_side_effects")
    if audit_report.get("automatic_rollback_performed") is True:
        errors.append("unexpected_side_effects")
    return _unique(errors)


def _has_unexpected_side_effects(report: dict) -> bool:
    return any(
        report.get(key) is True
        for key in [
            "publish_performed",
            "rollback_performed",
            "automatic_rollback_performed",
            "restore_performed",
            "automatic_restore_performed",
            "bulk_write_performed",
        ]
    )


def _fields(execute_report: dict, audit_report: dict, plan_report: dict) -> list[str]:
    fields = [item.get("field") for item in _readback_results(execute_report) if item.get("field")]
    if not fields:
        fields = audit_report.get("audited_fields") or []
    if not fields:
        fields = [entry.get("field") for entry in execute_report.get("planned_entries", []) if entry.get("field")]
    if not fields:
        fields = [entry.get("field") for entry in plan_report.get("entries", []) if entry.get("field")]
    return _unique(fields)


def _restore_values(plan_report: dict, execute_report: dict, fields: list[str]) -> dict:
    entries = plan_report.get("entries") or execute_report.get("planned_entries") or []
    before_values = {}
    restore_values = {}
    missing_fields = []
    sources = []

    for field in fields:
        entry = _find_entry(entries, field)
        current_value = "" if not entry else str(entry.get("current_value_if_known") or "")
        current_known = bool(entry.get("current_value_known")) if entry else False
        if current_known and current_value:
            before_values[field] = current_value
            restore_values[field] = current_value
            source = "small_batch_apply_plan.current_value_if_known"
            if source not in sources:
                sources.append(source)
        else:
            before_values[field] = ""
            restore_values[field] = ""
            missing_fields.append(field)

    restore_values_complete = bool(fields) and not missing_fields and sorted(fields) == sorted(ALLOWED_FIELDS)
    return {
        "before_values": before_values,
        "restore_values": restore_values,
        "restore_values_complete": restore_values_complete,
        "restore_value_source": "local_reports_current_value_if_known" if restore_values_complete else "missing_or_not_recorded",
        "restore_value_sources": sources,
        "missing_restore_value_fields": missing_fields,
    }


def _find_entry(entries: list[dict], field: str) -> dict:
    for entry in entries:
        if entry.get("field") == field:
            return entry
    return {}


def _current_values_after_write(execute_report: dict, audit_report: dict) -> dict:
    values = audit_report.get("final_readback_values") or {}
    if values:
        return {field: values.get(field, "") for field in ALLOWED_FIELDS if field in values}
    return {
        item.get("field"): item.get("readback_value", "")
        for item in _readback_results(execute_report)
        if item.get("field") in ALLOWED_FIELDS
    }


def _proposed_values(execute_report: dict, audit_report: dict, plan_report: dict) -> dict:
    values = audit_report.get("proposed_values") or {}
    if values:
        return {field: values.get(field, "") for field in ALLOWED_FIELDS if field in values}
    entries = execute_report.get("planned_entries") or plan_report.get("entries") or []
    return {
        entry.get("field"): entry.get("proposed_value", "")
        for entry in entries
        if entry.get("field") in ALLOWED_FIELDS
    }


def _readback_results(report: dict) -> list[dict]:
    if not report:
        return []
    readback = report.get("readback_summary") or {}
    results = readback.get("readback_results")
    return results if isinstance(results, list) else []


def _source_product_id(execute_report: dict, audit_report: dict) -> str:
    return execute_report.get("product_id") or audit_report.get("product_id") or ""


def _source_locale(execute_report: dict, audit_report: dict) -> str:
    return execute_report.get("locale") or audit_report.get("locale") or ""


def _source_entry_count(execute_report: dict, audit_report: dict) -> int:
    return int(execute_report.get("entry_count") or audit_report.get("entry_count") or 0)


def _rollback_scope(execute_report: dict, audit_report: dict, fields: list[str]) -> dict:
    return {
        "product_id": _source_product_id(execute_report, audit_report),
        "locale": _source_locale(execute_report, audit_report),
        "entry_count": _source_entry_count(execute_report, audit_report),
        "fields": fields,
        "max_products": 1,
        "max_locales": 1,
        "allowed_fields": ALLOWED_FIELDS,
    }


def _current_values_summary(current_values: dict) -> dict:
    return {
        "current_value_source": "small batch Phase 13 real write readback",
        "current_values_after_write": current_values,
        "current_values_match_proposed_values": True,
    }


def _source_write_summary(report: dict) -> dict:
    execution = report.get("translations_register_execution_summary") or {}
    return {
        "source_task": report.get("task", ""),
        "source_mode": report.get("mode", ""),
        "source_execution_status": report.get("execution_status", ""),
        "source_product_id": report.get("product_id", ""),
        "source_locale": report.get("locale", ""),
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_fields": _fields(report, {}, {}),
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "source_readback_all_entries_match": bool(report.get("readback_all_entries_match")) if report else False,
        "source_rollback_approval_required": bool(report.get("rollback_approval_required")) if report else False,
        "source_rollback_performed": bool(report.get("rollback_performed")) if report else False,
        "source_automatic_rollback_performed": bool(report.get("automatic_rollback_performed")) if report else False,
        "source_publish_performed": bool(report.get("publish_performed")) if report else False,
        "source_bulk_write_performed": bool(report.get("bulk_write_performed")) if report else False,
        "source_small_batch_write_performed": bool(report.get("small_batch_write_performed")) if report else False,
        "source_real_write_count": int(execution.get("real_write_count") or 0) if report else 0,
        "source_blocking_conditions": report.get("blocking_conditions", []) if report else [],
    }


def _source_audit_summary(report: dict) -> dict:
    return {
        "source_task": report.get("task", ""),
        "source_audit_status": report.get("audit_status", ""),
        "source_product_id": report.get("product_id", ""),
        "source_locale": report.get("locale", ""),
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_audited_fields": report.get("audited_fields", []) if report else [],
        "source_readback_all_entries_match": bool(report.get("readback_all_entries_match")) if report else False,
        "source_rollback_needed": bool(report.get("rollback_needed")) if report else False,
        "source_blocking_conditions": report.get("blocking_conditions", []) if report else [],
    }


def _rollback_plan(restore_summary: dict) -> dict:
    return {
        "restore_target_source": restore_summary["restore_value_source"],
        "restore_values": restore_summary["restore_values"],
        "restore_values_complete": restore_summary["restore_values_complete"],
        "missing_restore_value_fields": restore_summary["missing_restore_value_fields"],
        "plan_notes": [
            "A future restore may only target the same product, locale, and fields from this package.",
            "A future restore must call exactly one approved Shopify translationsRegister mutation for the recorded restore values.",
            "A future restore must immediately read back every restored field.",
            "Restore success may only be marked when all readback values match the approved restore values.",
            "This task does not execute restore, rollback, Shopify API calls, mutations, readback, or publish.",
        ],
    }


def _rollback_required_status(success: bool, optional_restore_possible: bool) -> dict:
    return {
        "rollback_needed": False,
        "rollback_reason": "not_required_because_small_batch_readback_matched_proposed_values" if success else "",
        "rollback_optional_restore_possible": optional_restore_possible,
        "rollback_optional_restore_requires_separate_approval": True,
        "restore_execution_task_required": True,
        "manual_human_approval_required_before_restore": True,
    }


def _rollback_manual_approval_checklist() -> list[str]:
    return [
        "Human confirms whether optional restore is actually needed.",
        "Human confirms the current values after the small-batch write.",
        "Human confirms every restore value is present and correct.",
        "Human confirms the restore scope is one product, one locale, and fields meta_title/meta_description only.",
        "Human confirms restore is also a real Shopify write.",
        "Human confirms restore requires a separate dangerous flag and execution ACK.",
        "Human confirms restore must be readback verified.",
        "Human confirms this phase does not execute rollback or restore.",
    ]


def _rollback_execution_requirements() -> list[str]:
    return [
        "Restore must be implemented as a future independent task.",
        "Restore must reload the small batch execute and post-write audit reports.",
        "Restore must validate product_id, locale, entry count, and fields again.",
        "Restore must require complete locally recorded restore values or a new verified backup package.",
        "Restore must require a new restore dangerous flag.",
        "Restore must require a new restore execution ACK.",
        "Restore must remain limited to one product, one locale, and allowed fields only.",
        "Restore must execute exactly one translationsRegister mutation if later approved.",
        "Restore must immediately read back all restored fields.",
    ]


def _rollback_readback_requirements() -> list[str]:
    return [
        "Read back the same product_id.",
        "Read back the same locale.",
        "Read back only meta_title and meta_description.",
        "Compare every readback value exactly with the approved restore value.",
        "Readback failure must block restore success.",
        "Readback result must be recorded locally.",
    ]


def _rollback_forbidden_actions() -> list[str]:
    return [
        "automatic rollback",
        "automatic restore",
        "rollback in this phase",
        "restore in this phase",
        "Shopify API call in this phase",
        "Shopify write in this phase",
        "mutation in this phase",
        "translationsRegister in this phase",
        "readback in this phase",
        "publish in this phase",
        "batch expansion",
        "full-store scan",
        "multiple products",
        "multiple locales",
        "unsupported fields",
        "restore to guessed values",
        "git push",
    ]


def _safety_summary() -> dict:
    return {
        "rollback_approval_package_only": True,
        "shopify_api_call_allowed_in_this_phase": False,
        "shopify_write_allowed_in_this_phase": False,
        "mutation_allowed_in_this_phase": False,
        "translations_register_allowed_in_this_phase": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
        "restore_allowed_in_this_phase": False,
        "publish_allowed_in_this_phase": False,
        "real_apply_allowed_in_this_phase": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_small_batch_execute_report": "blocked_missing_small_batch_execute_report",
        "missing_small_batch_post_write_audit_report": "blocked_missing_small_batch_post_write_audit_report",
        "small_batch_real_write_not_successful": "blocked_small_batch_real_write_not_successful",
        "small_batch_post_write_audit_not_passed": "blocked_small_batch_post_write_audit_not_passed",
        "small_batch_readback_mismatch": "blocked_small_batch_readback_mismatch",
        "small_batch_requires_rollback_review": "blocked_small_batch_requires_rollback_review",
        "scope_mismatch": "blocked_scope_mismatch",
        "unexpected_side_effects": "blocked_unexpected_side_effects",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _rollback_approval_status(blocking_conditions: list[str], execute_report: dict, audit_report: dict) -> str:
    if not execute_report:
        return "blocked_missing_small_batch_execute_report"
    if not audit_report:
        return "blocked_missing_small_batch_post_write_audit_report"
    if not blocking_conditions:
        return "small_batch_rollback_approval_package_ready_for_manual_review"
    for status in [
        "blocked_small_batch_real_write_not_successful",
        "blocked_small_batch_post_write_audit_not_passed",
        "blocked_small_batch_readback_mismatch",
        "blocked_small_batch_requires_rollback_review",
        "blocked_scope_mismatch",
        "blocked_unexpected_side_effects",
    ]:
        if status in blocking_conditions:
            return status
    return "small_batch_rollback_approval_package_failed"


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SMALL_BATCH_ROLLBACK_APPROVAL_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SMALL_BATCH_ROLLBACK_APPROVAL_JSON_PATH.read_text(encoding="utf-8"))
    return SMALL_BATCH_ROLLBACK_APPROVAL_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SMALL_BATCH_ROLLBACK_APPROVAL_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SMALL_BATCH_ROLLBACK_APPROVAL_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Rollback Approval Status", "rollback_approval_status"),
            ("Restore Plan Status", "restore_plan_status"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Entry Count", "entry_count"),
            ("Fields", "fields"),
            ("Rollback Needed", "rollback_needed"),
            ("Optional Restore Possible", "rollback_optional_restore_possible"),
            ("Restore Value Source", "restore_value_source"),
            ("Manual Backup Review Required", "manual_backup_review_required"),
            ("Restore Execution Task Required", "restore_execution_task_required"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Before Values", payload.get("before_values", {})),
            ("Restore Values", payload.get("restore_values", {})),
            ("Current Values After Write", payload.get("current_values_after_write", {})),
            ("Proposed Values", payload.get("proposed_values", {})),
            ("Source Write Summary", payload.get("source_write_summary", {})),
            ("Source Audit Summary", payload.get("source_audit_summary", {})),
            ("Rollback Plan", payload.get("rollback_plan", {})),
            ("Rollback Required Status", payload.get("rollback_required_status", {})),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Small Batch Rollback Approval Package</title>
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
  <h1>Shopify Small Batch Rollback Approval Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Restore Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local reports only.</li>
    <li>No Shopify API call, write, mutation, translationsRegister, readback, rollback, restore, publish, or apply was performed.</li>
    <li>Any future restore requires a separate task and separate human approval.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(rollback_approval_status: str, blocking_conditions: list[str], restore_plan_status: str) -> str:
    if blocking_conditions:
        return "Small batch rollback approval package blocked: " + ", ".join(blocking_conditions)
    return (
        "Small batch rollback approval package generated with status "
        f"{rollback_approval_status}; restore plan status {restore_plan_status}. "
        "No Shopify action performed."
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify small batch rollback approval package generated.\n"
        f"Rollback approval status: {payload.get('rollback_approval_status')}\n"
        f"Restore plan status: {payload.get('restore_plan_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locale: {payload.get('locale')}\n"
        f"Entry count: {payload.get('entry_count')}\n"
        f"Fields: {payload.get('fields')}\n"
        f"Rollback needed: {payload.get('rollback_needed')}\n"
        f"Optional restore possible: {payload.get('rollback_optional_restore_possible')}\n"
        f"Restore value source: {payload.get('restore_value_source')}\n"
        f"Manual backup review required: {payload.get('manual_backup_review_required')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Rollback approval JSON:\n"
        f"{json_path}\n\n"
        "Rollback approval HTML:\n"
        f"{html_path}\n"
        "Approval package only. No Shopify API call, mutation, translationsRegister, readback, rollback, restore, publish, apply, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep small batch rollback approval files\n"
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
