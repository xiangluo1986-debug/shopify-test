import json
import time
from html import escape
from pathlib import Path

from remote_approval.tasks import shopify_translation_single_field_post_write_audit_package_task as audit
from remote_approval.tasks import shopify_translation_single_field_real_write_one_shot_execute_task as execute
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_rollback_approval_package"
COMMAND_LABEL = "shopify_translation_single_field_rollback_approval_package"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
SOURCE_READBACK_ROLLBACK_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.json"
SOURCE_ONE_SHOT_EXECUTE_PATH = LOG_DIR / "shopify_translation_single_field_real_write_one_shot_execute.json"
SOURCE_POST_WRITE_AUDIT_PATH = LOG_DIR / "shopify_translation_single_field_post_write_audit_package.json"
ROLLBACK_APPROVAL_JSON_PATH = LOG_DIR / "shopify_translation_single_field_rollback_approval_package.json"
ROLLBACK_APPROVAL_HTML_PATH = LOG_DIR / "shopify_translation_single_field_rollback_approval_package.html"

EXPECTED_EXECUTION_STATUS = "real_write_succeeded_and_verified"
EXPECTED_AUDIT_STATUS = "post_write_audit_passed"
EXPECTED_BACKUP_VALUE = audit.EXPECTED_BACKUP_VALUE
EXPECTED_CURRENT_VALUE = execute.EXPECTED_PROPOSED_VALUE


def run_shopify_translation_single_field_rollback_approval_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    reports = {}

    for key, label, path, missing_code, invalid_code in _source_report_specs():
        try:
            reports[key] = _read_json(path)
        except FileNotFoundError as exc:
            parse_errors.append(f"{label} JSON not found: {exc}")
            validation_errors.append(missing_code)
            reports[key] = {}
        except (OSError, json.JSONDecodeError) as exc:
            parse_errors.append(f"Could not parse {label} JSON: {exc}")
            validation_errors.append(invalid_code)
            reports[key] = {}

    validation_errors.extend(_validate_backup_report(reports["backup"]))
    validation_errors.extend(_validate_plan_report(reports["plan"]))
    validation_errors.extend(_validate_execution_report(reports["execution"]))
    validation_errors.extend(_validate_audit_report(reports["audit"]))
    if all(reports.values()):
        validation_errors.extend(_validate_scope_match(reports))

    rollback_scope = {
        "product_id": execute.EXPECTED_PRODUCT_ID,
        "locale": execute.EXPECTED_LOCALE,
        "field": execute.EXPECTED_FIELD,
    }
    current_value_summary = _current_value_summary(reports["execution"])
    verified_backup_summary = _verified_backup_summary(reports["backup"])
    source_write_summary = _source_write_summary(reports["execution"])
    source_audit_summary = _source_audit_summary(reports["audit"])
    blocking_conditions = _blocking_conditions(validation_errors, current_value_summary, verified_backup_summary)
    rollback_approval_status = _rollback_approval_status(blocking_conditions)
    success = rollback_approval_status == "rollback_approval_package_ready_for_manual_review"
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "rollback-approval-package-only",
        "command_label": COMMAND_LABEL,
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "source_readback_rollback_plan_path": str(SOURCE_READBACK_ROLLBACK_PLAN_PATH),
        "source_execution_report_path": str(SOURCE_ONE_SHOT_EXECUTE_PATH),
        "source_post_write_audit_path": str(SOURCE_POST_WRITE_AUDIT_PATH),
        "json_rollback_approval_package_path": str(ROLLBACK_APPROVAL_JSON_PATH),
        "html_rollback_approval_package_path": str(ROLLBACK_APPROVAL_HTML_PATH),
        "success": success,
        "rollback_approval_status": rollback_approval_status,
        "rollback_scope": rollback_scope,
        "current_value_summary": current_value_summary,
        "verified_backup_summary": verified_backup_summary,
        "source_write_summary": source_write_summary,
        "source_audit_summary": source_audit_summary,
        "rollback_plan": _rollback_plan(verified_backup_summary),
        "rollback_required_status": _rollback_required_status(reports["audit"]),
        "rollback_manual_approval_checklist": _rollback_manual_approval_checklist(),
        "rollback_execution_requirements": _rollback_execution_requirements(),
        "rollback_readback_requirements": _rollback_readback_requirements(),
        "rollback_forbidden_actions": _rollback_forbidden_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(source_write_summary),
        "rollback_approval_package_only": True,
        "rollback_execution_allowed": False,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": execute.locked.plan.shell.base._unique(validation_errors),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(rollback_approval_status, blocking_conditions),
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
        "json_rollback_approval_package_path": str(json_path),
        "html_rollback_approval_package_path": str(html_path),
        "rollback_approval_status": rollback_approval_status,
        "rollback_approval_package_only": True,
        "rollback_needed": payload["rollback_required_status"]["rollback_needed"],
        "rollback_optional_restore_possible": payload["rollback_required_status"]["rollback_optional_restore_possible"],
        "rollback_optional_restore_requires_separate_approval": payload["rollback_required_status"][
            "rollback_optional_restore_requires_separate_approval"
        ],
        "current_value": current_value_summary["current_value"],
        "backup_value": verified_backup_summary["backup_value"],
        "source_shopify_write_performed": source_write_summary["source_shopify_write_performed"],
        "source_translations_register_called": source_write_summary["source_translations_register_called"],
        "rollback_execution_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _source_report_specs() -> list[tuple[str, str, Path, str, str]]:
    return [
        ("backup", "backup fetch report", SOURCE_BACKUP_FETCH_PATH, "missing_backup_fetch_report", "backup_fetch_json_invalid"),
        (
            "plan",
            "readback rollback plan",
            SOURCE_READBACK_ROLLBACK_PLAN_PATH,
            "missing_readback_rollback_plan",
            "readback_rollback_plan_json_invalid",
        ),
        (
            "execution",
            "real write execution report",
            SOURCE_ONE_SHOT_EXECUTE_PATH,
            "missing_real_write_execution_report",
            "real_write_execution_json_invalid",
        ),
        (
            "audit",
            "post-write audit report",
            SOURCE_POST_WRITE_AUDIT_PATH,
            "missing_post_write_audit_report",
            "post_write_audit_json_invalid",
        ),
    ]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_backup_report(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("backup_source_is_verified") is not True and not audit._backup_source_is_verified(report):
        errors.append("backup_not_verified")
    if report.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")
    if report.get("backup_value_present") is not True:
        errors.append("backup_value_missing")
    if str(report.get("backup_value") or "") != EXPECTED_BACKUP_VALUE:
        errors.append("backup_value_mismatch")
    errors.extend(_validate_fixed_scope(_scope_from_backup(report)))
    errors.extend(_validate_no_write_source(report, "backup"))
    return execute.locked.plan.shell.base._unique(errors)


def _validate_plan_report(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    errors.extend(_validate_fixed_scope(report.get("proposed_change") or report.get("requested_scope") or {}))
    if report.get("rollback_performed") is True:
        errors.append("rollback_already_performed_unexpectedly")
    errors.extend(_validate_no_write_source(report, "readback_rollback_plan"))
    return execute.locked.plan.shell.base._unique(errors)


def _validate_execution_report(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("execution_status") != EXPECTED_EXECUTION_STATUS:
        errors.append("source_execution_not_succeeded_and_verified")
    if report.get("readback_matches_proposed_value") is not True:
        errors.append("readback_mismatch_in_source_execution")
    if report.get("rollback_performed") is not False:
        errors.append("rollback_already_performed_unexpectedly")
    if report.get("automatic_rollback_performed") is not False:
        errors.append("automatic_rollback_already_performed")
    if report.get("translations_register_called") is not True:
        errors.append("source_translations_register_not_called")
    if report.get("shopify_write_performed") is not True:
        errors.append("source_shopify_write_not_performed")
    if report.get("mutation_performed") is not True:
        errors.append("source_mutation_not_performed")
    if report.get("readback_performed") is not True:
        errors.append("source_readback_not_performed")
    if (report.get("verification_summary") or {}).get("verification_passed") is not True:
        errors.append("source_verification_not_passed")
    if str((report.get("verified_backup_summary") or {}).get("backup_value") or "") != EXPECTED_BACKUP_VALUE:
        errors.append("source_report_missing_backup_value")
    current_value = _current_value_summary(report)["current_value"]
    if not current_value:
        errors.append("source_report_missing_current_value")
    if current_value != EXPECTED_CURRENT_VALUE:
        errors.append("source_current_value_mismatch")
    errors.extend(_validate_fixed_scope(report.get("requested_scope") or {}))
    errors.extend(_validate_fixed_scope(report.get("proposed_change") or {}))
    errors.extend(_validate_fixed_scope((report.get("readback_summary") or {}).get("readback_scope") or {}))
    return execute.locked.plan.shell.base._unique(errors)


def _validate_audit_report(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("audit_status") != EXPECTED_AUDIT_STATUS:
        errors.append("post_write_audit_not_passed")
        errors.append("audit_status_not_passed")
    if (report.get("verification_summary") or {}).get("audit_verification_passed") is not True:
        errors.append("post_write_audit_not_passed")
    if (report.get("rollback_summary") or {}).get("rollback_needed") is not False:
        errors.append("audit_rollback_needed_not_false")
    if report.get("shopify_write_performed") is not False:
        errors.append("audit_report_indicates_new_write")
    if report.get("mutation_performed") is not False:
        errors.append("audit_report_indicates_new_mutation")
    if report.get("translations_register_called") is not False:
        errors.append("audit_report_indicates_new_translationsRegister")
    if report.get("readback_performed") is not False:
        errors.append("audit_report_indicates_new_readback")
    if report.get("rollback_performed") is not False:
        errors.append("audit_report_indicates_new_rollback")
    if report.get("no_new_shopify_writes_performed") is not True:
        errors.append("audit_report_no_new_write_not_confirmed")
    errors.extend(_validate_fixed_scope(report.get("audited_scope") or report.get("requested_scope") or {}))
    return execute.locked.plan.shell.base._unique(errors)


def _validate_no_write_source(report: dict, source_name: str) -> list[str]:
    errors = []
    for field in [
        "shopify_write_performed",
        "apply_performed",
        "publish_performed",
        "translations_register_performed",
        "translations_register_called",
        "mutation_performed",
        "readback_performed",
        "rollback_performed",
        "real_apply_performed",
    ]:
        if report.get(field) is True:
            errors.append(f"{source_name}_indicates_unexpected_action")
    return execute.locked.plan.shell.base._unique(errors)


def _validate_scope_match(reports: dict) -> list[str]:
    errors = []
    scopes = [
        _scope_from_backup(reports["backup"]),
        reports["plan"].get("proposed_change") or reports["plan"].get("requested_scope") or {},
        reports["execution"].get("requested_scope") or {},
        reports["execution"].get("proposed_change") or {},
        (reports["execution"].get("readback_summary") or {}).get("readback_scope") or {},
        reports["audit"].get("audited_scope") or reports["audit"].get("requested_scope") or {},
    ]
    first = scopes[0]
    for scope in scopes:
        errors.extend(_validate_fixed_scope(scope))
    for scope in scopes[1:]:
        for key in ["product_id", "locale", "field"]:
            if first.get(key) != scope.get(key):
                errors.append("scope_mismatch")
    return execute.locked.plan.shell.base._unique(errors)


def _validate_fixed_scope(scope: dict) -> list[str]:
    errors = []
    if scope.get("product_id") != execute.EXPECTED_PRODUCT_ID:
        errors.append("scope_mismatch")
        errors.append("invalid_product_id")
    if scope.get("locale") != execute.EXPECTED_LOCALE:
        errors.append("scope_mismatch")
        errors.append("invalid_locale")
    if scope.get("field") != execute.EXPECTED_FIELD:
        errors.append("scope_mismatch")
        errors.append("invalid_field")
    proposed_value = str(scope.get("proposed_value") or "")
    if proposed_value and proposed_value != EXPECTED_CURRENT_VALUE:
        errors.append("current_value_mismatch")
    return execute.locked.plan.shell.base._unique(errors)


def _scope_from_backup(backup: dict) -> dict:
    return {
        "product_id": backup.get("backup_product_id") or (backup.get("requested_scope") or {}).get("product_id", ""),
        "locale": backup.get("backup_locale") or (backup.get("requested_scope") or {}).get("locale", ""),
        "field": backup.get("backup_field") or (backup.get("requested_scope") or {}).get("field", ""),
    }


def _current_value_summary(execution: dict) -> dict:
    readback = execution.get("readback_summary") or {}
    scope = readback.get("readback_scope") or execution.get("requested_scope") or {}
    current_value = str(readback.get("readback_value") or (execution.get("verification_summary") or {}).get("readback_value") or "")
    written_value = str((execution.get("proposed_change") or {}).get("proposed_value") or (execution.get("requested_scope") or {}).get("proposed_value") or "")
    return {
        "current_value_source": "Phase 12.1B real write readback",
        "current_value": current_value,
        "current_value_matches_written_value": bool(current_value and current_value == written_value),
        "locale": scope.get("locale", ""),
        "field": scope.get("field", ""),
        "product_id": scope.get("product_id", ""),
    }


def _verified_backup_summary(backup: dict) -> dict:
    value = str(backup.get("backup_value") or "") if backup else ""
    return {
        "backup_source_is_verified": audit._backup_source_is_verified(backup),
        "read_only_shopify_query_performed": bool(backup.get("read_only_shopify_query_performed")) if backup else False,
        "backup_value_present": bool(backup.get("backup_value_present")) if backup else False,
        "backup_value": value,
        "backup_value_chars": len(value),
        "backup_locale": backup.get("backup_locale", "") if backup else "",
        "backup_field": backup.get("backup_field", "") if backup else "",
        "backup_product_id": backup.get("backup_product_id", "") if backup else "",
    }


def _source_write_summary(execution: dict) -> dict:
    return {
        "source_execution_status": execution.get("execution_status", "") if execution else "",
        "source_shopify_write_performed": bool(execution.get("shopify_write_performed")) if execution else False,
        "source_translations_register_called": bool(execution.get("translations_register_called")) if execution else False,
        "source_mutation_performed": bool(execution.get("mutation_performed")) if execution else False,
        "source_readback_performed": bool(execution.get("readback_performed")) if execution else False,
        "source_readback_matches_proposed_value": bool(execution.get("readback_matches_proposed_value")) if execution else False,
        "source_real_write_count": int(execution.get("real_write_count") or 0) if execution else 0,
        "source_rollback_performed": bool(execution.get("rollback_performed")) if execution else False,
        "source_automatic_rollback_performed": bool(execution.get("automatic_rollback_performed")) if execution else False,
    }


def _source_audit_summary(report: dict) -> dict:
    rollback_summary = report.get("rollback_summary") or {}
    return {
        "source_audit_status": report.get("audit_status", "") if report else "",
        "source_audit_verification_passed": bool((report.get("verification_summary") or {}).get("audit_verification_passed"))
        if report
        else False,
        "source_rollback_needed": bool(rollback_summary.get("rollback_needed")) if report else False,
        "source_no_new_shopify_writes_performed": bool(report.get("no_new_shopify_writes_performed")) if report else False,
        "source_all_new_actions_no_write_confirmed": bool(report.get("all_new_actions_no_write_confirmed"))
        if report
        else False,
    }


def _rollback_plan(backup_summary: dict) -> dict:
    return {
        "rollback_plan_status": "restore_plan_ready_for_manual_review",
        "rollback_target_value_source": "verified backup value",
        "rollback_target_value": backup_summary["backup_value"],
        "rollback_target_value_chars": backup_summary["backup_value_chars"],
        "rollback_scope": {
            "product_id": execute.EXPECTED_PRODUCT_ID,
            "locale": execute.EXPECTED_LOCALE,
            "field": execute.EXPECTED_FIELD,
        },
        "future_shopify_mutation_required": "translationsRegister",
        "future_mutation_count": 1,
        "future_must_readback_same_scope": True,
        "future_readback_must_equal_backup_value": True,
        "rollback_cannot_be_marked_success_without_readback_match": True,
        "rollback_cannot_execute_in_this_phase": True,
        "rollback_must_execute_in_future_independent_task": True,
    }


def _rollback_required_status(audit_report: dict) -> dict:
    rollback_needed = bool((audit_report.get("rollback_summary") or {}).get("rollback_needed"))
    return {
        "rollback_needed": rollback_needed,
        "rollback_reason": (
            "requires_restore_because_source_audit_indicates_rollback_needed"
            if rollback_needed
            else "not_required_because_readback_matched_proposed_value"
        ),
        "rollback_optional_restore_possible": True,
        "rollback_optional_restore_requires_separate_approval": True,
    }


def _rollback_manual_approval_checklist() -> list[str]:
    return [
        "Human confirms whether restore is truly needed.",
        "Human confirms the current value.",
        "Human confirms the verified backup value.",
        "Human confirms the restore scope.",
        "Human confirms SEO/meta title will return to the old value after restore.",
        "Human confirms rollback is also a real Shopify write.",
        "Human confirms rollback requires a dangerous flag.",
        "Human confirms rollback must be immediately read back.",
        "Human confirms this phase does not execute rollback.",
    ]


def _rollback_execution_requirements() -> list[str]:
    return [
        "Rollback must be a future independent task.",
        "The future task must re-read the backup report.",
        "The future task must re-read the post-write audit report.",
        "The future task must re-validate scope.",
        "The future task must re-validate backup_source_is_verified=true.",
        "The future task must re-validate rollback target value equals backup value.",
        "The future task must require a new rollback dangerous flag.",
        "The future task must require a new rollback execution ack.",
        "The future task must limit execution to 1 product x 1 locale x 1 field=meta_title.",
        "The future task must execute exactly one translationsRegister mutation.",
        "The future task must immediately read back the same scope.",
    ]


def _rollback_readback_requirements() -> list[str]:
    return [
        "Read back the same product_id.",
        "Read back the same locale.",
        "Read back field=meta_title.",
        "Compare exact value with backup_value.",
        "Readback failure must block rollback success.",
        "Readback result must be recorded locally.",
    ]


def _rollback_forbidden_actions() -> list[str]:
    return [
        "automatic rollback",
        "rollback in this phase",
        "Shopify API call in this phase",
        "Shopify write in this phase",
        "mutation in this phase",
        "translationsRegister in this phase",
        "readback in this phase",
        "batch mode",
        "full-store scan",
        "multiple products",
        "multiple locales",
        "multiple fields",
        "rollback to any value other than verified backup value",
        "git push",
    ]


def _blocking_conditions(validation_errors: list[str], current_summary: dict, backup_summary: dict) -> list[str]:
    conditions = []
    mapping = {
        "missing_backup_fetch_report": "missing_backup_fetch_report",
        "missing_readback_rollback_plan": "missing_readback_rollback_plan",
        "missing_real_write_execution_report": "missing_real_write_execution_report",
        "missing_post_write_audit_report": "missing_post_write_audit_report",
        "backup_not_verified": "backup_not_verified",
        "backup_value_missing": "backup_value_missing",
        "backup_value_mismatch": "source_report_missing_backup_value",
        "source_execution_not_succeeded_and_verified": "source_execution_not_succeeded_and_verified",
        "post_write_audit_not_passed": "post_write_audit_not_passed",
        "audit_status_not_passed": "audit_status_not_passed",
        "scope_mismatch": "scope_mismatch",
        "invalid_field": "scope_mismatch",
        "readback_mismatch_in_source_execution": "readback_mismatch_in_source_execution",
        "automatic_rollback_already_performed": "automatic_rollback_already_performed",
        "rollback_already_performed_unexpectedly": "rollback_already_performed_unexpectedly",
        "source_report_missing_current_value": "source_report_missing_current_value",
        "source_report_missing_backup_value": "source_report_missing_backup_value",
    }
    for error in validation_errors:
        conditions.append(mapping.get(error, error))
    if not current_summary["current_value"]:
        conditions.append("source_report_missing_current_value")
    if not backup_summary["backup_value"]:
        conditions.append("source_report_missing_backup_value")
    return execute.locked.plan.shell.base._unique(conditions)


def _rollback_approval_status(blocking_conditions: list[str]) -> str:
    if not blocking_conditions:
        return "rollback_approval_package_ready_for_manual_review"
    if "post_write_audit_not_passed" in blocking_conditions or "audit_status_not_passed" in blocking_conditions:
        return "blocked_post_write_audit_not_passed"
    if "source_execution_not_succeeded_and_verified" in blocking_conditions:
        return "blocked_source_execution_not_verified"
    if "scope_mismatch" in blocking_conditions:
        return "blocked_scope_mismatch"
    return "blocked"


def _safety_summary(source_write_summary: dict) -> dict:
    return {
        "rollback_approval_package_only": True,
        "source_shopify_write_performed": source_write_summary["source_shopify_write_performed"],
        "source_translations_register_called": source_write_summary["source_translations_register_called"],
        "source_mutation_performed": source_write_summary["source_mutation_performed"],
        "source_readback_performed": source_write_summary["source_readback_performed"],
        "shopify_api_call_allowed_in_this_phase": False,
        "shopify_write_allowed_in_this_phase": False,
        "mutation_allowed_in_this_phase": False,
        "translations_register_allowed_in_this_phase": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
        "automatic_rollback_allowed": False,
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": execute.EXPECTED_FIELD,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    ROLLBACK_APPROVAL_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(ROLLBACK_APPROVAL_JSON_PATH.read_text(encoding="utf-8"))
    return ROLLBACK_APPROVAL_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ROLLBACK_APPROVAL_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return ROLLBACK_APPROVAL_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Rollback Approval Status", "rollback_approval_status"),
            ("Rollback Approval Package Only", "rollback_approval_package_only"),
            ("Rollback Scope", "rollback_scope"),
            ("Current Value Summary", "current_value_summary"),
            ("Verified Backup Summary", "verified_backup_summary"),
            ("Source Write Summary", "source_write_summary"),
            ("Source Audit Summary", "source_audit_summary"),
            ("Rollback Required Status", "rollback_required_status"),
            ("Rollback Execution Allowed", "rollback_execution_allowed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Rollback Plan", payload.get("rollback_plan", {})),
            ("Manual Approval Checklist", payload.get("rollback_manual_approval_checklist", [])),
            ("Rollback Execution Requirements", payload.get("rollback_execution_requirements", [])),
            ("Rollback Readback Requirements", payload.get("rollback_readback_requirements", [])),
            ("Rollback Forbidden Actions", payload.get("rollback_forbidden_actions", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Rollback Approval Package</title>
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
  <h1>Shopify Single-Field Rollback Approval Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Rollback Plan Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local JSON reports only.</li>
    <li>No Shopify API call was performed.</li>
    <li>No mutation or translationsRegister call was performed.</li>
    <li>No readback or rollback was performed by this task.</li>
    <li>Any future rollback must be a separate approved task and must read back the same scope.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Single-field rollback approval package blocked: " + ", ".join(blocking_conditions)
    return f"Single-field rollback approval package generated with status {status}. No rollback or Shopify action performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field rollback approval package generated.\n"
        f"Rollback approval status: {payload.get('rollback_approval_status')}\n"
        f"Rollback scope: {payload.get('rollback_scope')}\n"
        f"Current value: {payload.get('current_value_summary', {}).get('current_value')}\n"
        f"Verified backup value: {payload.get('verified_backup_summary', {}).get('backup_value')}\n"
        f"Rollback needed: {payload.get('rollback_required_status', {}).get('rollback_needed')}\n"
        f"Optional restore possible: {payload.get('rollback_required_status', {}).get('rollback_optional_restore_possible')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Rollback approval package JSON:\n"
        f"{json_path}\n\n"
        "Rollback approval package HTML:\n"
        f"{html_path}\n"
        "Rollback approval package only. No Shopify API call, mutation, translationsRegister, readback, rollback, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep rollback approval package files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Do not push from this task."
    )
