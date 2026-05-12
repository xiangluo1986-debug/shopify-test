import json
import time
from html import escape
from pathlib import Path

from remote_approval.tasks import shopify_translation_single_field_real_write_one_shot_execute_task as execute
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_post_write_audit_package"
COMMAND_LABEL = "shopify_translation_single_field_post_write_audit_package"
SOURCE_PREFLIGHT_PACKAGE_PATH = LOG_DIR / "shopify_translation_single_field_apply_preflight_package.json"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
SOURCE_READBACK_ROLLBACK_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.json"
SOURCE_FINAL_WRITE_GATE_PATH = LOG_DIR / "shopify_translation_single_field_final_write_gate.json"
SOURCE_PRE_EXECUTION_VALIDATE_PATH = LOG_DIR / "shopify_translation_single_field_real_write_pre_execution_validate.json"
SOURCE_FINAL_HUMAN_APPROVAL_PATH = LOG_DIR / "shopify_translation_single_field_final_human_approval_package.json"
SOURCE_EXECUTION_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_real_write_execution_plan.json"
SOURCE_ONE_SHOT_EXECUTE_PATH = LOG_DIR / "shopify_translation_single_field_real_write_one_shot_execute.json"
POST_WRITE_AUDIT_JSON_PATH = LOG_DIR / "shopify_translation_single_field_post_write_audit_package.json"
POST_WRITE_AUDIT_HTML_PATH = LOG_DIR / "shopify_translation_single_field_post_write_audit_package.html"

EXPECTED_EXECUTION_TASK = "shopify_translation_single_field_real_write_one_shot_execute"
EXPECTED_EXECUTION_STATUS = "real_write_succeeded_and_verified"
EXPECTED_BACKUP_VALUE = "MOFLY P-51D Aileron Linkage Connector | RC Plane Clevis"


def run_shopify_translation_single_field_post_write_audit_package_task(mode: str) -> dict:
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

    prior_reports = {key: reports[key] for key in reports if key != "execution"}
    for source_name, report in prior_reports.items():
        if report:
            validation_errors.extend(_validate_prior_source_no_write_flags(report, source_name))

    execution_report = reports["execution"]
    if execution_report:
        validation_errors.extend(_validate_execution_report(execution_report))

    if all(reports.values()):
        validation_errors.extend(_validate_scope_match(reports))
        validation_errors.extend(_validate_proposed_value_match(reports))

    requested_scope = _requested_scope(reports)
    audited_scope = {
        "product_id": execute.EXPECTED_PRODUCT_ID,
        "locale": execute.EXPECTED_LOCALE,
        "field": execute.EXPECTED_FIELD,
    }
    backup_summary = _backup_summary(reports["backup"])
    source_execution_summary = _source_execution_report_summary(execution_report)
    write_summary = _write_summary(execution_report)
    readback_summary = _readback_summary(execution_report)
    verification_summary = _verification_summary(execution_report)
    rollback_summary = _rollback_summary(execution_report, verification_summary)
    blocking_conditions = _blocking_conditions(validation_errors, backup_summary, source_execution_summary)
    audit_status = _audit_status(blocking_conditions, reports["execution"])
    success = audit_status == "post_write_audit_passed"
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "post-write-audit-only",
        "command_label": COMMAND_LABEL,
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "source_readback_rollback_plan_path": str(SOURCE_READBACK_ROLLBACK_PLAN_PATH),
        "source_final_write_gate_path": str(SOURCE_FINAL_WRITE_GATE_PATH),
        "source_pre_execution_validate_path": str(SOURCE_PRE_EXECUTION_VALIDATE_PATH),
        "source_final_human_approval_path": str(SOURCE_FINAL_HUMAN_APPROVAL_PATH),
        "source_execution_plan_path": str(SOURCE_EXECUTION_PLAN_PATH),
        "source_execution_report_path": str(SOURCE_ONE_SHOT_EXECUTE_PATH),
        "json_post_write_audit_package_path": str(POST_WRITE_AUDIT_JSON_PATH),
        "html_post_write_audit_package_path": str(POST_WRITE_AUDIT_HTML_PATH),
        "success": success,
        "audit_status": audit_status,
        "audited_scope": audited_scope,
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if requested_scope.get("product_id") == execute.EXPECTED_PRODUCT_ID else 0,
            "locale_count": 1 if requested_scope.get("locale") == execute.EXPECTED_LOCALE else 0,
            "field_count": 1 if requested_scope.get("field") == execute.EXPECTED_FIELD else 0,
            "field": requested_scope.get("field", ""),
            "field_allowed": requested_scope.get("field") == execute.EXPECTED_FIELD,
            "scope_matches_fixed_audit_scope": _scope_matches_fixed(requested_scope),
            "scope_matches_all_sources": "scope_mismatch" not in validation_errors,
            "proposed_value_matches_all_sources": "proposed_value_mismatch" not in validation_errors,
        },
        "source_status_summary": _source_status_summary(reports),
        "source_execution_report_summary": source_execution_summary,
        "backup_summary": backup_summary,
        "write_summary": write_summary,
        "readback_summary": readback_summary,
        "verification_summary": verification_summary,
        "rollback_summary": rollback_summary,
        "safety_summary": _safety_summary(source_execution_summary),
        "post_write_observations": _post_write_observations(),
        "next_phase_recommendations": _next_phase_recommendations(),
        "blocking_conditions": blocking_conditions,
        "post_write_audit_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "real_apply_performed": False,
        "automatic_rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": execute.locked.plan.shell.base._unique(validation_errors),
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
        "json_post_write_audit_package_path": str(json_path),
        "html_post_write_audit_package_path": str(html_path),
        "audit_status": audit_status,
        "post_write_audit_only": True,
        "source_execution_status": source_execution_summary["source_execution_status"],
        "source_shopify_write_performed": source_execution_summary["source_shopify_write_performed"],
        "source_translations_register_called": source_execution_summary["source_translations_register_called"],
        "source_mutation_performed": source_execution_summary["source_mutation_performed"],
        "source_readback_performed": source_execution_summary["source_readback_performed"],
        "real_write_count": write_summary["real_write_count"],
        "readback_matches_proposed_value": readback_summary["readback_matches_proposed_value"],
        "audit_verification_passed": verification_summary["audit_verification_passed"],
        "rollback_needed": rollback_summary["rollback_needed"],
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _source_report_specs() -> list[tuple[str, str, Path, str, str]]:
    return [
        ("preflight", "preflight package", SOURCE_PREFLIGHT_PACKAGE_PATH, "missing_preflight_package", "preflight_package_json_invalid"),
        ("backup", "backup fetch report", SOURCE_BACKUP_FETCH_PATH, "missing_backup_fetch_report", "backup_fetch_json_invalid"),
        (
            "plan",
            "readback rollback plan",
            SOURCE_READBACK_ROLLBACK_PLAN_PATH,
            "missing_readback_rollback_plan",
            "readback_rollback_plan_json_invalid",
        ),
        ("gate", "final gate package", SOURCE_FINAL_WRITE_GATE_PATH, "missing_final_gate_package", "final_gate_json_invalid"),
        (
            "pre_execution",
            "pre-execution validation",
            SOURCE_PRE_EXECUTION_VALIDATE_PATH,
            "missing_pre_execution_validation_report",
            "pre_execution_validation_json_invalid",
        ),
        (
            "final_human",
            "final human approval package",
            SOURCE_FINAL_HUMAN_APPROVAL_PATH,
            "missing_final_human_approval_package",
            "final_human_approval_package_json_invalid",
        ),
        (
            "execution_plan",
            "execution plan",
            SOURCE_EXECUTION_PLAN_PATH,
            "missing_execution_plan_report",
            "execution_plan_json_invalid",
        ),
        (
            "execution",
            "one-shot execution report",
            SOURCE_ONE_SHOT_EXECUTE_PATH,
            "missing_execution_report",
            "execution_report_json_invalid",
        ),
    ]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_prior_source_no_write_flags(report: dict, source_name: str) -> list[str]:
    errors = []
    unsafe_true_fields = [
        "shopify_write_performed",
        "apply_performed",
        "publish_performed",
        "translations_register_performed",
        "translations_register_called",
        "command_executed",
        "mutation_performed",
        "readback_performed",
        "rollback_performed",
        "real_apply_performed",
    ]
    for field in unsafe_true_fields:
        if report.get(field) is True:
            if field in {"translations_register_performed", "translations_register_called"}:
                errors.append(f"{source_name}_indicates_translationsRegister")
            elif field == "mutation_performed":
                errors.append(f"{source_name}_indicates_mutation")
            elif field == "readback_performed":
                errors.append(f"{source_name}_indicates_readback")
            elif field == "rollback_performed":
                errors.append(f"{source_name}_indicates_rollback")
            else:
                errors.append(f"{source_name}_indicates_shopify_write")
    for field in [
        "real_write_allowed",
        "final_real_write_allowed",
        "write_execution_allowed",
        "phase_12_entry_allowed",
        "phase_12_1_entry_allowed",
        "phase_12_1b_entry_allowed",
        "phase_12_1b_real_execution_allowed",
    ]:
        if report.get(field) is True:
            errors.append(f"{source_name}_indicates_real_write_allowed")
    return execute.locked.plan.shell.base._unique(errors)


def _validate_execution_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_EXECUTION_TASK:
        errors.append("unsafe_execution_report")
    if report.get("execution_status") != EXPECTED_EXECUTION_STATUS:
        errors.append("execution_status_not_success")
        errors.append("source_execution_not_verified")
    if report.get("translations_register_called") is not True:
        errors.append("source_translations_register_not_called")
    if report.get("shopify_write_performed") is not True:
        errors.append("source_shopify_write_not_performed")
    if report.get("mutation_performed") is not True:
        errors.append("source_mutation_not_performed")
    if report.get("readback_performed") is not True:
        errors.append("source_readback_not_performed")
    if report.get("readback_matches_proposed_value") is not True:
        errors.append("source_readback_mismatch")
    if (report.get("verification_summary") or {}).get("verification_passed") is not True:
        errors.append("source_verification_not_passed")
    if report.get("rollback_approval_required") is not False:
        errors.append("source_rollback_approval_required")
    if report.get("rollback_performed") is not False:
        errors.append("source_rollback_performed")
    if report.get("automatic_rollback_performed") is not False:
        errors.append("source_automatic_rollback_performed")
    if report.get("real_write_scope_limited") is not True:
        errors.append("source_write_scope_not_limited")
    if int(report.get("real_write_count") or 0) != 1:
        errors.append("source_real_write_count_not_one")

    scope = report.get("requested_scope") or {}
    errors.extend(_validate_fixed_scope(scope))
    proposed_change = report.get("proposed_change") or {}
    errors.extend(_validate_fixed_scope({**scope, "proposed_value": proposed_change.get("proposed_value") or scope.get("proposed_value")}))

    backup = report.get("verified_backup_summary") or {}
    if str(backup.get("backup_value") or "") != EXPECTED_BACKUP_VALUE:
        errors.append("backup_value_mismatch")
    if backup.get("backup_source_is_verified") is not True:
        errors.append("backup_not_verified")
    if backup.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")

    readback = report.get("readback_summary") or {}
    if str(readback.get("readback_value") or "") != execute.EXPECTED_PROPOSED_VALUE:
        errors.append("readback_value_mismatch")
    if readback.get("readback_matches_proposed_value") is not True:
        errors.append("source_readback_mismatch")
    readback_scope = readback.get("readback_scope") or {}
    errors.extend(_validate_fixed_scope({**readback_scope, "proposed_value": execute.EXPECTED_PROPOSED_VALUE}))
    return execute.locked.plan.shell.base._unique(errors)


def _validate_fixed_scope(scope: dict) -> list[str]:
    errors = []
    if scope.get("product_id") != execute.EXPECTED_PRODUCT_ID:
        errors.append("invalid_product_id")
        errors.append("scope_mismatch")
    if scope.get("locale") != execute.EXPECTED_LOCALE:
        errors.append("invalid_locale")
        errors.append("scope_mismatch")
    if scope.get("field") != execute.EXPECTED_FIELD:
        errors.append("invalid_field")
        errors.append("scope_mismatch")
    proposed_value = str(scope.get("proposed_value") or execute.EXPECTED_PROPOSED_VALUE)
    if proposed_value != execute.EXPECTED_PROPOSED_VALUE:
        errors.append("proposed_value_mismatch")
    return execute.locked.plan.shell.base._unique(errors)


def _validate_scope_match(reports: dict) -> list[str]:
    errors = []
    scopes = _all_scopes(reports)
    first = scopes[0] if scopes else {}
    for scope in scopes:
        errors.extend(_validate_fixed_scope({**scope, "proposed_value": execute.EXPECTED_PROPOSED_VALUE}))
    for scope in scopes[1:]:
        for key in ["product_id", "locale", "field"]:
            if first.get(key) != scope.get(key):
                errors.append("scope_mismatch")
    return execute.locked.plan.shell.base._unique(errors)


def _validate_proposed_value_match(reports: dict) -> list[str]:
    values = _all_proposed_values(reports)
    nonempty = [value for value in values if value]
    if not nonempty:
        return ["proposed_value_empty"]
    if len(set(nonempty)) > 1:
        return ["proposed_value_mismatch"]
    if nonempty[0] != execute.EXPECTED_PROPOSED_VALUE:
        return ["proposed_value_mismatch"]
    return []


def _all_scopes(reports: dict) -> list[dict]:
    return [
        reports["preflight"].get("requested_scope") or {},
        {
            "product_id": reports["backup"].get("backup_product_id")
            or (reports["backup"].get("requested_scope") or {}).get("product_id", ""),
            "locale": reports["backup"].get("backup_locale")
            or (reports["backup"].get("requested_scope") or {}).get("locale", ""),
            "field": reports["backup"].get("backup_field")
            or (reports["backup"].get("requested_scope") or {}).get("field", ""),
        },
        reports["plan"].get("proposed_change") or reports["plan"].get("requested_scope") or {},
        reports["gate"].get("proposed_change") or reports["gate"].get("requested_scope") or {},
        reports["pre_execution"].get("proposed_change") or reports["pre_execution"].get("requested_scope") or {},
        reports["final_human"].get("proposed_change") or reports["final_human"].get("requested_scope") or {},
        reports["execution_plan"].get("proposed_change") or reports["execution_plan"].get("requested_scope") or {},
        reports["execution"].get("requested_scope") or {},
        reports["execution"].get("proposed_change") or {},
        (reports["execution"].get("readback_summary") or {}).get("readback_scope") or {},
    ]


def _all_proposed_values(reports: dict) -> list[str]:
    return [
        str((reports["preflight"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["plan"].get("proposed_change") or reports["plan"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["gate"].get("proposed_change") or reports["gate"].get("requested_scope") or {}).get("proposed_value") or ""),
        str(
            (reports["pre_execution"].get("proposed_change") or reports["pre_execution"].get("requested_scope") or {}).get(
                "proposed_value"
            )
            or ""
        ),
        str(
            (reports["final_human"].get("proposed_change") or reports["final_human"].get("requested_scope") or {}).get(
                "proposed_value"
            )
            or ""
        ),
        str(
            (reports["execution_plan"].get("proposed_change") or reports["execution_plan"].get("requested_scope") or {}).get(
                "proposed_value"
            )
            or ""
        ),
        str((reports["execution"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["execution"].get("proposed_change") or {}).get("proposed_value") or ""),
        str((reports["execution"].get("verification_summary") or {}).get("proposed_value") or ""),
    ]


def _requested_scope(reports: dict) -> dict:
    preflight_scope = reports.get("preflight", {}).get("requested_scope") or {}
    execution_scope = reports.get("execution", {}).get("requested_scope") or {}
    return {
        "product_id": execution_scope.get("product_id") or preflight_scope.get("product_id", ""),
        "locale": execution_scope.get("locale") or preflight_scope.get("locale", ""),
        "field": execution_scope.get("field") or preflight_scope.get("field", ""),
        "proposed_value": execution_scope.get("proposed_value") or preflight_scope.get("proposed_value", ""),
    }


def _scope_matches_fixed(scope: dict) -> bool:
    return (
        scope.get("product_id") == execute.EXPECTED_PRODUCT_ID
        and scope.get("locale") == execute.EXPECTED_LOCALE
        and scope.get("field") == execute.EXPECTED_FIELD
    )


def _source_status_summary(reports: dict) -> dict:
    return {
        "preflight_status": reports["preflight"].get("preflight_status", "") if reports["preflight"] else "",
        "backup_fetch_status": reports["backup"].get("backup_fetch_status", "") if reports["backup"] else "",
        "readback_rollback_plan_status": reports["plan"].get("plan_status", "") if reports["plan"] else "",
        "final_gate_status": reports["gate"].get("final_gate_status", "") if reports["gate"] else "",
        "pre_execution_validation_status": reports["pre_execution"].get("validation_status", "")
        if reports["pre_execution"]
        else "",
        "final_human_approval_status": reports["final_human"].get("approval_package_status", "")
        if reports["final_human"]
        else "",
        "execution_plan_status": reports["execution_plan"].get("execution_plan_status", "")
        if reports["execution_plan"]
        else "",
        "source_execution_status": reports["execution"].get("execution_status", "") if reports["execution"] else "",
        "source_reports_loaded": {key: bool(value) for key, value in reports.items()},
    }


def _source_execution_report_summary(report: dict) -> dict:
    return {
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_task": report.get("task", "") if report else "",
        "source_mode": report.get("mode", "") if report else "",
        "source_shopify_api_call_performed": bool(report.get("shopify_api_call_performed")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "source_readback_matches_proposed_value": bool(report.get("readback_matches_proposed_value")) if report else False,
        "source_verification_passed": bool((report.get("verification_summary") or {}).get("verification_passed"))
        if report
        else False,
        "source_rollback_approval_required": bool(report.get("rollback_approval_required")) if report else False,
        "source_rollback_performed": bool(report.get("rollback_performed")) if report else False,
        "source_automatic_rollback_performed": bool(report.get("automatic_rollback_performed")) if report else False,
        "source_real_write_count": int(report.get("real_write_count") or 0) if report else 0,
    }


def _backup_summary(backup: dict) -> dict:
    value = str(backup.get("backup_value") or "") if backup else ""
    return {
        "backup_source_is_verified": _backup_source_is_verified(backup),
        "backup_value_present": bool(backup.get("backup_value_present")) if backup else False,
        "backup_value": value,
        "backup_value_chars": len(value),
        "backup_locale": backup.get("backup_locale", "") if backup else "",
        "backup_field": backup.get("backup_field", "") if backup else "",
        "backup_product_id": backup.get("backup_product_id", "") if backup else "",
        "backup_generated_at": backup.get("backup_generated_at", "") if backup else "",
        "read_only_shopify_query_performed": bool(backup.get("read_only_shopify_query_performed")) if backup else False,
    }


def _backup_source_is_verified(backup: dict) -> bool:
    if not backup:
        return False
    return bool(backup.get("read_only_shopify_query_performed")) and all(
        key in backup
        for key in [
            "backup_value_present",
            "backup_value",
            "backup_locale",
            "backup_field",
            "backup_product_id",
            "backup_generated_at",
        ]
    )


def _write_summary(report: dict) -> dict:
    proposed_value = str((report.get("proposed_change") or {}).get("proposed_value") or "")
    if not proposed_value:
        proposed_value = str((report.get("requested_scope") or {}).get("proposed_value") or "")
    return {
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "written_value": proposed_value,
        "proposed_value": proposed_value,
        "write_scope_limited": bool(report.get("real_write_scope_limited")) if report else False,
        "real_write_count": int(report.get("real_write_count") or 0) if report else 0,
    }


def _readback_summary(report: dict) -> dict:
    readback = (report.get("readback_summary") or {}) if report else {}
    scope = readback.get("readback_scope") or {}
    return {
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "readback_value": str(readback.get("readback_value") or ""),
        "readback_matches_proposed_value": bool(readback.get("readback_matches_proposed_value")),
        "readback_locale": readback.get("readback_locale") or scope.get("locale", ""),
        "readback_field": scope.get("field", ""),
        "readback_product_id": scope.get("product_id", ""),
    }


def _verification_summary(report: dict) -> dict:
    verification = (report.get("verification_summary") or {}) if report else {}
    proposed_value = str(verification.get("proposed_value") or execute.EXPECTED_PROPOSED_VALUE)
    readback_value = str(verification.get("readback_value") or "")
    exact_match = proposed_value == readback_value
    return {
        "verification_passed": bool(verification.get("verification_passed")),
        "proposed_value": proposed_value,
        "readback_value": readback_value,
        "exact_match": exact_match,
        "audit_verification_passed": bool(verification.get("verification_passed")) and exact_match,
    }


def _rollback_summary(report: dict, verification_summary: dict) -> dict:
    rollback_requirement = (report.get("rollback_approval_requirement") or {}) if report else {}
    rollback_needed = not bool(verification_summary.get("audit_verification_passed"))
    return {
        "rollback_approval_required": bool(report.get("rollback_approval_required")) if report else False,
        "rollback_performed": bool(report.get("rollback_performed")) if report else False,
        "automatic_rollback_performed": bool(report.get("automatic_rollback_performed")) if report else False,
        "rollback_needed": rollback_needed,
        "rollback_note": (
            "No rollback required because readback matched proposed value."
            if not rollback_needed
            else "Rollback approval package is required before any rollback action."
        ),
        "verified_backup_value_available": bool(rollback_requirement.get("backup_value")),
        "verified_backup_value": rollback_requirement.get("backup_value", ""),
    }


def _blocking_conditions(validation_errors: list[str], backup_summary: dict, execution_summary: dict) -> list[str]:
    conditions = []
    mapping = {
        "missing_execution_report": "blocked_missing_execution_report",
        "execution_status_not_success": "execution_status_not_success",
        "source_execution_not_verified": "source_execution_not_verified",
        "scope_mismatch": "scope_mismatch",
        "invalid_product_id": "invalid_product_id",
        "invalid_locale": "invalid_locale",
        "invalid_field": "invalid_field",
        "proposed_value_mismatch": "proposed_value_mismatch",
        "backup_value_mismatch": "backup_value_mismatch",
        "backup_not_verified": "backup_not_verified",
        "read_only_backup_query_not_performed": "read_only_backup_query_not_performed",
        "readback_value_mismatch": "readback_value_mismatch",
        "source_readback_mismatch": "readback_value_mismatch",
        "source_rollback_performed": "rollback_performed_not_allowed",
        "source_automatic_rollback_performed": "automatic_rollback_not_allowed",
    }
    for error in validation_errors:
        conditions.append(mapping.get(error, error))
    if not backup_summary["backup_source_is_verified"]:
        conditions.append("backup_not_verified")
    if backup_summary["backup_value"] != EXPECTED_BACKUP_VALUE:
        conditions.append("backup_value_mismatch")
    if not execution_summary["source_shopify_write_performed"]:
        conditions.append("source_shopify_write_not_performed")
    if not execution_summary["source_translations_register_called"]:
        conditions.append("source_translations_register_not_called")
    if execution_summary["source_rollback_performed"]:
        conditions.append("rollback_performed_not_allowed")
    if execution_summary["source_automatic_rollback_performed"]:
        conditions.append("automatic_rollback_not_allowed")
    return execute.locked.plan.shell.base._unique(conditions)


def _audit_status(blocking_conditions: list[str], execution_report: dict) -> str:
    if not execution_report:
        return "blocked_missing_execution_report"
    if not blocking_conditions:
        return "post_write_audit_passed"
    return "post_write_audit_failed"


def _safety_summary(source_summary: dict) -> dict:
    return {
        "post_write_audit_only": True,
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
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": execute.EXPECTED_FIELD,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _post_write_observations() -> list[str]:
    return [
        "The first real single-field Shopify translation write succeeded.",
        "The write scope did not expand beyond one product, one locale, and field=meta_title.",
        "Immediate readback verification succeeded.",
        "No automatic rollback was performed.",
        "A future phase can consider a rollback approval package or a second single-field test while staying at 1 product x 1 locale x 1 field.",
    ]


def _next_phase_recommendations() -> list[str]:
    return [
        "Phase 12.3: optional rollback approval package / restore plan, still no automatic rollback.",
        "Phase 12.4: second single-field real write test using the same safety chain.",
        "Do not expand directly to batch yet.",
        "Do not open multi-product, multi-locale, or multi-field execution yet.",
        "Complete at least 1-2 more one-shot single-field tests before considering broader scope.",
    ]


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    POST_WRITE_AUDIT_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(POST_WRITE_AUDIT_JSON_PATH.read_text(encoding="utf-8"))
    return POST_WRITE_AUDIT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    POST_WRITE_AUDIT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return POST_WRITE_AUDIT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Audit Status", "audit_status"),
            ("Post-Write Audit Only", "post_write_audit_only"),
            ("Source Execution Status", "source_execution_report_summary"),
            ("Audited Scope", "audited_scope"),
            ("Backup Summary", "backup_summary"),
            ("Write Summary", "write_summary"),
            ("Readback Summary", "readback_summary"),
            ("Verification Summary", "verification_summary"),
            ("Rollback Summary", "rollback_summary"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Source Status Summary", payload.get("source_status_summary", {})),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Post-Write Observations", payload.get("post_write_observations", [])),
            ("Next Phase Recommendations", payload.get("next_phase_recommendations", [])),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Post-Write Audit Package</title>
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
  <h1>Shopify Single-Field Post-Write Audit Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Audit Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This audit reads local JSON reports only.</li>
    <li>No new Shopify API call was performed.</li>
    <li>No new mutation or translationsRegister call was performed.</li>
    <li>No readback or rollback was performed by this audit task.</li>
    <li>The source execution report is allowed to record the prior Phase 12.1B real write facts.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(audit_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Single-field post-write audit blocked: " + ", ".join(blocking_conditions)
    return f"Single-field post-write audit completed with status {audit_status}. No new Shopify actions performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field post-write audit package generated.\n"
        f"Audit status: {payload.get('audit_status')}\n"
        f"Audited scope: {payload.get('audited_scope')}\n"
        f"Source execution status: {payload.get('source_execution_report_summary', {}).get('source_execution_status')}\n"
        f"Source Shopify write performed: {payload.get('source_execution_report_summary', {}).get('source_shopify_write_performed')}\n"
        f"Source translationsRegister called: {payload.get('source_execution_report_summary', {}).get('source_translations_register_called')}\n"
        f"Audit verification passed: {payload.get('verification_summary', {}).get('audit_verification_passed')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Post-write audit JSON:\n"
        f"{json_path}\n\n"
        "Post-write audit HTML:\n"
        f"{html_path}\n"
        "Post-write audit only. No Shopify API call, mutation, translationsRegister, readback, rollback, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep post-write audit files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Do not push from this task."
    )
