import json
import os
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.tasks import shopify_translation_single_field_real_write_one_shot_locked_shell_task as locked
from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_single_field_real_write_one_shot_execute"
COMMAND_LABEL = "shopify_translation_single_field_real_write_one_shot_execute"
SOURCE_PREFLIGHT_PACKAGE_PATH = LOG_DIR / "shopify_translation_single_field_apply_preflight_package.json"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
SOURCE_READBACK_ROLLBACK_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.json"
SOURCE_FINAL_WRITE_GATE_PATH = LOG_DIR / "shopify_translation_single_field_final_write_gate.json"
SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_design.json"
SOURCE_REAL_WRITE_LOCKED_RUNNER_PATH = LOG_DIR / "shopify_translation_single_field_real_write_locked_runner.json"
SOURCE_PRE_EXECUTION_VALIDATE_PATH = LOG_DIR / "shopify_translation_single_field_real_write_pre_execution_validate.json"
SOURCE_FINAL_HUMAN_APPROVAL_PATH = LOG_DIR / "shopify_translation_single_field_final_human_approval_package.json"
SOURCE_FINAL_SAFE_SHELL_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_final_safe_shell.json"
SOURCE_EXECUTION_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_real_write_execution_plan.json"
SOURCE_ONE_SHOT_LOCKED_SHELL_PATH = LOG_DIR / "shopify_translation_single_field_real_write_one_shot_locked_shell.json"
ONE_SHOT_EXECUTE_JSON_PATH = LOG_DIR / "shopify_translation_single_field_real_write_one_shot_execute.json"
ONE_SHOT_EXECUTE_HTML_PATH = LOG_DIR / "shopify_translation_single_field_real_write_one_shot_execute.html"

EXPECTED_ONE_SHOT_LOCKED_SHELL_TASK = "shopify_translation_single_field_real_write_one_shot_locked_shell"
EXPECTED_ONE_SHOT_LOCKED_SHELL_MODE = "one-shot-locked-shell-only"
READY_ONE_SHOT_LOCKED_SHELL_STATUSES = {
    "one_shot_locked_ready_for_manual_review",
    "ready_for_real_write_shell_review_but_locked",
}

REAL_EXECUTION_ACK_ENV = "SHOPIFY_TRANSLATION_PHASE_12_1B_REAL_EXECUTION_ACK"
REAL_EXECUTION_ACK_VALUE = "YES_I_APPROVE_ONE_REAL_SHOPIFY_TRANSLATION_WRITE"
SUPPORTED_MODES = {"dry-run", "real-run", "execute-real-write"}
REAL_RUN_MODES = {"real-run", "execute-real-write"}

EXPECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
EXPECTED_LOCALE = "ja"
EXPECTED_FIELD = "meta_title"
EXPECTED_PROPOSED_VALUE = "MOFLY P-51D Aileron Link Connector"
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
DOCKER_TIMEOUT_SECONDS = 120


def run_shopify_translation_single_field_real_write_one_shot_execute_task(mode: str) -> dict:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"{TASK_NAME} only supports dry-run, real-run, or execute-real-write mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    reports = {}

    for key, label, path, missing_code, invalid_code in [
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
            "design",
            "real write runner design",
            SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH,
            "missing_real_write_runner_design_package",
            "real_write_runner_design_json_invalid",
        ),
        (
            "locked",
            "real write locked runner",
            SOURCE_REAL_WRITE_LOCKED_RUNNER_PATH,
            "missing_locked_runner_report",
            "real_write_locked_runner_json_invalid",
        ),
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
            "final_safe_shell",
            "final safe shell report",
            SOURCE_FINAL_SAFE_SHELL_PATH,
            "missing_final_safe_shell_report",
            "final_safe_shell_json_invalid",
        ),
        (
            "execution_plan",
            "execution plan report",
            SOURCE_EXECUTION_PLAN_PATH,
            "missing_execution_plan_report",
            "execution_plan_json_invalid",
        ),
        (
            "one_shot_locked_shell",
            "one-shot locked shell report",
            SOURCE_ONE_SHOT_LOCKED_SHELL_PATH,
            "missing_one_shot_locked_shell_report",
            "one_shot_locked_shell_json_invalid",
        ),
    ]:
        try:
            reports[key] = locked.plan.shell.base._read_json(path)
        except FileNotFoundError as exc:
            parse_errors.append(f"{label} JSON not found: {exc}")
            validation_errors.append(missing_code)
            reports[key] = {}
        except (OSError, json.JSONDecodeError) as exc:
            parse_errors.append(f"Could not parse {label} JSON: {exc}")
            validation_errors.append(invalid_code)
            reports[key] = {}

    env_scope = locked.plan.shell.base._env_requested_scope()
    dangerous_flag_value = os.environ.get(locked.plan.shell.base.DANGEROUS_FLAG_ENV, "").strip()
    dangerous_flag_present = bool(dangerous_flag_value)
    dangerous_flag_valid = dangerous_flag_value.lower() == "true"
    final_safe_ack_value = os.environ.get(locked.plan.shell.ACK_ENV, "").strip()
    final_safe_ack_present = bool(final_safe_ack_value)
    final_safe_ack_valid = final_safe_ack_value.lower() == "true"
    plan_ack_value = os.environ.get(locked.plan.PLAN_ACK_ENV, "").strip()
    plan_ack_present = bool(plan_ack_value)
    plan_ack_valid = plan_ack_value.lower() == "true"
    locked_shell_ack_value = os.environ.get(locked.LOCKED_SHELL_ACK_ENV, "").strip()
    locked_shell_ack_present = bool(locked_shell_ack_value)
    locked_shell_ack_valid = locked_shell_ack_value.lower() == "true"
    real_execution_ack_value = os.environ.get(REAL_EXECUTION_ACK_ENV, "").strip()
    real_execution_ack_present = bool(real_execution_ack_value)
    real_execution_ack_valid = real_execution_ack_value == REAL_EXECUTION_ACK_VALUE

    validation_errors.extend(locked.plan.shell.base._validate_env_scope(env_scope))
    validation_errors.extend(_validate_fixed_scope(env_scope))
    if not dangerous_flag_present:
        validation_errors.append("missing_dangerous_flag")
    elif not dangerous_flag_valid:
        validation_errors.append("invalid_dangerous_flag_value")
    if not final_safe_ack_present:
        validation_errors.append("missing_final_safe_shell_ack")
    elif not final_safe_ack_valid:
        validation_errors.append("invalid_final_safe_shell_ack_value")
    if not plan_ack_present:
        validation_errors.append("missing_plan_ack")
    elif not plan_ack_valid:
        validation_errors.append("invalid_plan_ack_value")
    if not locked_shell_ack_present:
        validation_errors.append("missing_locked_shell_ack")
    elif not locked_shell_ack_valid:
        validation_errors.append("invalid_locked_shell_ack_value")
    if not real_execution_ack_present:
        validation_errors.append("missing_real_execution_ack")
    elif not real_execution_ack_valid:
        validation_errors.append("invalid_real_execution_ack_value")

    validators = [
        ("preflight", locked.plan.shell.base._validate_preflight),
        ("backup", locked.plan.shell.base._validate_backup),
        ("plan", locked.plan.shell.base._validate_plan),
        ("gate", locked.plan.shell.base._validate_gate),
        ("design", locked.plan.shell.base._validate_design),
        ("locked", locked.plan.shell.base._validate_locked),
        ("pre_execution", locked.plan.shell.base._validate_pre_execution),
        ("final_human", locked.plan.shell._validate_final_human_approval),
        ("final_safe_shell", locked.plan._validate_final_safe_shell),
        ("execution_plan", locked._validate_execution_plan),
        ("one_shot_locked_shell", _validate_one_shot_locked_shell),
    ]
    for key, validator in validators:
        if reports[key]:
            validation_errors.extend(validator(reports[key]))

    for report in reports.values():
        if report:
            validation_errors.extend(_validate_source_unlock_flags(report))

    if all(reports.values()):
        validation_errors.extend(_validate_scope_match(reports, env_scope))
        validation_errors.extend(_validate_proposed_value_match(reports, env_scope))

    requested_scope = _requested_scope(reports, env_scope)
    proposed_change = locked.plan.shell.base._proposed_change(requested_scope)
    validation_errors.extend(_validate_fixed_scope(requested_scope))
    verified_backup_summary = locked.plan.shell.base._verified_backup_summary(reports["backup"])
    final_gate_summary = locked.plan.shell.base._final_gate_summary(reports["gate"])
    design_summary = locked.plan.shell.base._design_summary(reports["design"])
    locked_runner_summary = locked.plan.shell.base._locked_runner_summary(reports["locked"])
    pre_execution_validation_summary = locked.plan.shell.base._pre_execution_validation_summary(reports["pre_execution"])
    final_human_approval_summary = locked.plan.shell._final_human_approval_summary(reports["final_human"])
    final_safe_shell_summary = locked.plan._final_safe_shell_summary(reports["final_safe_shell"])
    execution_plan_summary = locked._execution_plan_summary(reports["execution_plan"])
    one_shot_locked_shell_summary = _one_shot_locked_shell_summary(reports["one_shot_locked_shell"])
    blocking_conditions = _blocking_conditions(
        validation_errors,
        proposed_change,
        verified_backup_summary,
        final_gate_summary,
        design_summary,
        locked_runner_summary,
        pre_execution_validation_summary,
        final_human_approval_summary,
        final_safe_shell_summary,
        execution_plan_summary,
        one_shot_locked_shell_summary,
    )

    execution_result = _empty_execution_result(requested_scope)
    if mode in REAL_RUN_MODES and not blocking_conditions:
        execution_result = _execute_real_write_and_readback(requested_scope)

    execution_status = _execution_status(mode, blocking_conditions, execution_result)
    real_run_attempted = mode in REAL_RUN_MODES and not blocking_conditions
    translations_register_called = bool(execution_result.get("translations_register_called"))
    mutation_performed = bool(execution_result.get("mutation_performed"))
    shopify_write_performed = bool(execution_result.get("shopify_write_performed"))
    readback_performed = bool(execution_result.get("readback_performed"))
    shopify_api_call_performed = bool(execution_result.get("shopify_api_call_performed"))
    readback_matches_proposed_value = bool(execution_result.get("readback_matches_proposed_value"))
    rollback_approval_required = _rollback_approval_required(execution_status, execution_result)
    no_shopify_writes_performed = not (shopify_write_performed or mutation_performed or translations_register_called)
    all_no_write_confirmed = no_shopify_writes_performed

    success = (
        not blocking_conditions
        if mode == "dry-run"
        else execution_status == "real_write_succeeded_and_verified"
    )
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "source_readback_rollback_plan_path": str(SOURCE_READBACK_ROLLBACK_PLAN_PATH),
        "source_final_write_gate_path": str(SOURCE_FINAL_WRITE_GATE_PATH),
        "source_real_write_runner_design_path": str(SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH),
        "source_real_write_locked_runner_path": str(SOURCE_REAL_WRITE_LOCKED_RUNNER_PATH),
        "source_pre_execution_validate_path": str(SOURCE_PRE_EXECUTION_VALIDATE_PATH),
        "source_final_human_approval_path": str(SOURCE_FINAL_HUMAN_APPROVAL_PATH),
        "source_final_safe_shell_path": str(SOURCE_FINAL_SAFE_SHELL_PATH),
        "source_execution_plan_path": str(SOURCE_EXECUTION_PLAN_PATH),
        "source_one_shot_locked_shell_path": str(SOURCE_ONE_SHOT_LOCKED_SHELL_PATH),
        "json_one_shot_execute_path": str(ONE_SHOT_EXECUTE_JSON_PATH),
        "html_one_shot_execute_path": str(ONE_SHOT_EXECUTE_HTML_PATH),
        "success": success,
        "execution_status": execution_status,
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if requested_scope.get("product_id") == EXPECTED_PRODUCT_ID else 0,
            "locale_count": 1 if requested_scope.get("locale") == EXPECTED_LOCALE else 0,
            "field_count": 1 if requested_scope.get("field") == EXPECTED_FIELD else 0,
            "field": requested_scope.get("field", ""),
            "field_allowed": requested_scope.get("field") == EXPECTED_FIELD,
            "product_id_matches_fixed_scope": requested_scope.get("product_id") == EXPECTED_PRODUCT_ID,
            "locale_matches_fixed_scope": requested_scope.get("locale") == EXPECTED_LOCALE,
            "proposed_value_matches_fixed_scope": requested_scope.get("proposed_value") == EXPECTED_PROPOSED_VALUE,
            "scope_matches_all_sources": "scope_mismatch" not in validation_errors,
            "environment_scope_matches_reports": "environment_scope_mismatch" not in validation_errors,
            "proposed_value_matches_all_sources": "proposed_value_mismatch" not in validation_errors,
            "allowed_field": EXPECTED_FIELD,
            "allowed_locale": EXPECTED_LOCALE,
            "allowed_product_id": EXPECTED_PRODUCT_ID,
        },
        "environment_scope": env_scope,
        "source_status_summary": _source_status_summary(reports),
        "proposed_change": proposed_change,
        "verified_backup_summary": verified_backup_summary,
        "real_execution_ack_summary": {
            "ack_env": REAL_EXECUTION_ACK_ENV,
            "ack_present": real_execution_ack_present,
            "ack_value_matches_required_phrase": real_execution_ack_valid,
            "ack_required_value": REAL_EXECUTION_ACK_VALUE,
            "ack_effective_for_dry_run": False,
            "ack_effective_for_real_run": bool(mode in REAL_RUN_MODES and not blocking_conditions),
            "ack_note": "This ack is required but only real-run / execute-real-write mode may use it.",
        },
        "dangerous_flag_summary": {
            "dangerous_flag_name": locked.plan.shell.base.FUTURE_REQUIRED_FLAG,
            "dangerous_flag_env": locked.plan.shell.base.DANGEROUS_FLAG_ENV,
            "dangerous_flag_present": dangerous_flag_present,
            "dangerous_flag_value": dangerous_flag_value,
            "dangerous_flag_required": True,
            "dangerous_flag_effective": bool(mode in REAL_RUN_MODES and not blocking_conditions),
        },
        "phase_12_final_safe_shell_ack_summary": _ack_summary(
            locked.plan.shell.ACK_ENV,
            final_safe_ack_present,
            final_safe_ack_value,
            final_safe_ack_valid,
            mode in REAL_RUN_MODES and not blocking_conditions,
        ),
        "phase_12_1a_plan_ack_summary": _ack_summary(
            locked.plan.PLAN_ACK_ENV,
            plan_ack_present,
            plan_ack_value,
            plan_ack_valid,
            mode in REAL_RUN_MODES and not blocking_conditions,
        ),
        "phase_12_1b_locked_shell_ack_summary": _ack_summary(
            locked.LOCKED_SHELL_ACK_ENV,
            locked_shell_ack_present,
            locked_shell_ack_value,
            locked_shell_ack_valid,
            mode in REAL_RUN_MODES and not blocking_conditions,
        ),
        "translations_register_execution_summary": _translations_register_execution_summary(
            execution_result,
            mode,
            real_run_attempted,
        ),
        "readback_summary": _readback_summary(execution_result, requested_scope),
        "verification_summary": {
            "readback_required": True,
            "readback_performed": readback_performed,
            "readback_value": execution_result.get("readback_value", ""),
            "proposed_value": requested_scope.get("proposed_value", ""),
            "readback_matches_proposed_value": readback_matches_proposed_value,
            "verification_passed": execution_status == "real_write_succeeded_and_verified",
        },
        "failure_summary": _failure_summary(execution_status, execution_result, blocking_conditions),
        "rollback_approval_requirement": {
            "rollback_approval_required": rollback_approval_required,
            "rollback_performed": False,
            "automatic_rollback_performed": False,
            "automatic_rollback_allowed": False,
            "rollback_scope": {
                "product_id": EXPECTED_PRODUCT_ID,
                "locale": EXPECTED_LOCALE,
                "field": EXPECTED_FIELD,
            },
            "rollback_value_source": "verified backup report",
            "backup_value": verified_backup_summary.get("backup_value", ""),
            "backup_value_chars": verified_backup_summary.get("backup_value_chars", 0),
        },
        "safety_summary": _safety_summary(mode, real_run_attempted, execution_result),
        "blocking_conditions": blocking_conditions,
        "future_required_flag": locked.plan.shell.base.FUTURE_REQUIRED_FLAG,
        "one_shot_real_execution_task": True,
        "real_write_scope_limited": True,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": EXPECTED_FIELD,
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "automatic_rollback_allowed": False,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "real_write_allowed": bool(real_run_attempted),
        "write_execution_allowed": bool(real_run_attempted),
        "translations_register_allowed": bool(real_run_attempted),
        "translations_register_called": translations_register_called,
        "translations_register_performed": translations_register_called,
        "shopify_write_performed": shopify_write_performed,
        "apply_performed": False,
        "publish_performed": False,
        "command_executed": False,
        "mutation_performed": mutation_performed,
        "shopify_mutations_called": ["translationsRegister"] if translations_register_called else [],
        "shopify_api_call_performed": shopify_api_call_performed,
        "readback_performed": readback_performed,
        "real_apply_performed": shopify_write_performed,
        "real_write_count": int(execution_result.get("real_write_count") or 0),
        "readback_matches_proposed_value": readback_matches_proposed_value,
        "rollback_approval_required": rollback_approval_required,
        "no_shopify_writes_performed": no_shopify_writes_performed,
        "all_no_write_confirmed": all_no_write_confirmed,
        "validation_failures": locked.plan.shell.base._unique(validation_errors),
        "parse_errors": parse_errors,
        "execution_result": execution_result,
        "detected_issue_summary": _issue_summary(execution_status, blocking_conditions, execution_result),
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
        "json_one_shot_execute_path": str(json_path),
        "html_one_shot_execute_path": str(html_path),
        "execution_status": execution_status,
        "one_shot_real_execution_task": True,
        "real_write_scope_limited": True,
        "real_execution_ack_present": real_execution_ack_present,
        "real_execution_ack_valid": real_execution_ack_valid,
        "translations_register_allowed": bool(real_run_attempted),
        "translations_register_called": translations_register_called,
        "shopify_write_performed": shopify_write_performed,
        "mutation_performed": mutation_performed,
        "shopify_api_call_performed": shopify_api_call_performed,
        "readback_performed": readback_performed,
        "readback_matches_proposed_value": readback_matches_proposed_value,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "rollback_approval_required": rollback_approval_required,
        "real_apply_performed": shopify_write_performed,
        "real_write_count": int(execution_result.get("real_write_count") or 0),
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": EXPECTED_FIELD,
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "automatic_rollback_allowed": False,
        "real_write_allowed": bool(real_run_attempted),
        "write_execution_allowed": bool(real_run_attempted),
        "no_shopify_writes_performed": no_shopify_writes_performed,
        "all_no_write_confirmed": all_no_write_confirmed,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _validate_one_shot_locked_shell(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_ONE_SHOT_LOCKED_SHELL_TASK or report.get("mode") != EXPECTED_ONE_SHOT_LOCKED_SHELL_MODE:
        errors.append("unsafe_one_shot_locked_shell_report")
    if report.get("one_shot_locked_shell_status") not in READY_ONE_SHOT_LOCKED_SHELL_STATUSES:
        errors.append("one_shot_locked_shell_not_ready")
    if report.get("one_shot_locked_shell_only") is not True:
        errors.append("unsafe_one_shot_locked_shell_report")
    if (
        report.get("phase_12_1b_real_execution_allowed") is not False
        or report.get("phase_12_1b_entry_allowed") is not False
        or report.get("phase_12_1_entry_allowed") is not False
        or report.get("phase_12_entry_allowed") is not False
    ):
        errors.append("source_report_indicates_phase_12_1b_entry_allowed")
    locked_ack = report.get("phase_12_1b_locked_shell_ack_summary") or {}
    if locked_ack.get("ack_present") is not True or str(locked_ack.get("ack_value") or "").lower() != "true":
        errors.append("missing_locked_shell_ack")
    if locked_ack.get("ack_effective") is not False:
        errors.append("unsafe_locked_shell_ack_effective")
    dangerous = report.get("dangerous_flag_summary") or {}
    if dangerous.get("dangerous_flag_effective") is not False:
        errors.append("unsafe_dangerous_flag_effective")
    scope = report.get("proposed_change") or report.get("requested_scope") or {}
    errors.extend(locked.plan.shell.base._validate_scope(scope))
    errors.extend(locked.plan.shell.base._validate_proposed_value(scope))
    errors.extend(locked.plan.shell.base._validate_no_write_flags(report))
    for field in ["shopify_api_call_performed", "readback_performed", "rollback_performed"]:
        if report.get(field) is True:
            errors.append("source_report_indicates_shopify_write")
    return locked.plan.shell.base._unique(errors)


def _validate_source_unlock_flags(report: dict) -> list[str]:
    errors = locked._validate_source_unlock_flags(report)
    if report.get("phase_12_1b_entry_allowed") is True or report.get("phase_12_1b_real_execution_allowed") is True:
        errors.append("source_report_indicates_phase_12_1b_entry_allowed")
    return locked.plan.shell.base._unique(errors)


def _validate_scope_match(reports: dict, env_scope: dict) -> list[str]:
    errors = []
    scopes = _all_scopes(reports) + [env_scope]
    first = scopes[0] if scopes else {}
    for scope in scopes[1:]:
        for key in ["product_id", "locale", "field"]:
            if first.get(key) != scope.get(key):
                errors.append("scope_mismatch")
            if env_scope.get(key) != scope.get(key):
                errors.append("environment_scope_mismatch")
    return locked.plan.shell.base._unique(errors)


def _validate_proposed_value_match(reports: dict, env_scope: dict) -> list[str]:
    values = _all_proposed_values(reports) + [str(env_scope.get("proposed_value") or "")]
    nonempty = [value for value in values if value]
    if not nonempty:
        return ["proposed_value_empty"]
    if len(set(nonempty)) > 1:
        return ["proposed_value_mismatch"]
    return []


def _validate_fixed_scope(scope: dict) -> list[str]:
    errors = []
    if scope.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.extend(["invalid_fixed_product_id", "scope_mismatch"])
    if scope.get("locale") != EXPECTED_LOCALE:
        errors.extend(["invalid_fixed_locale", "scope_mismatch"])
    if scope.get("field") != EXPECTED_FIELD:
        errors.extend(["invalid_sandbox_field", "scope_mismatch"])
    proposed_value = str(scope.get("proposed_value") or "")
    if proposed_value != EXPECTED_PROPOSED_VALUE:
        errors.append("proposed_value_mismatch")
    return locked.plan.shell.base._unique(errors)


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
        reports["design"].get("proposed_change") or reports["design"].get("requested_scope") or {},
        reports["locked"].get("proposed_change") or reports["locked"].get("requested_scope") or {},
        reports["pre_execution"].get("proposed_change") or reports["pre_execution"].get("requested_scope") or {},
        reports["final_human"].get("proposed_change") or reports["final_human"].get("requested_scope") or {},
        reports["final_safe_shell"].get("proposed_change") or reports["final_safe_shell"].get("requested_scope") or {},
        reports["execution_plan"].get("proposed_change") or reports["execution_plan"].get("requested_scope") or {},
        reports["one_shot_locked_shell"].get("proposed_change")
        or reports["one_shot_locked_shell"].get("requested_scope")
        or {},
    ]


def _all_proposed_values(reports: dict) -> list[str]:
    return [
        str((reports["preflight"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["plan"].get("proposed_change") or reports["plan"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["gate"].get("proposed_change") or reports["gate"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["design"].get("proposed_change") or reports["design"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["locked"].get("proposed_change") or reports["locked"].get("requested_scope") or {}).get("proposed_value") or ""),
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
            (reports["final_safe_shell"].get("proposed_change") or reports["final_safe_shell"].get("requested_scope") or {}).get(
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
        str(
            (
                reports["one_shot_locked_shell"].get("proposed_change")
                or reports["one_shot_locked_shell"].get("requested_scope")
                or {}
            ).get("proposed_value")
            or ""
        ),
    ]


def _requested_scope(reports: dict, env_scope: dict) -> dict:
    first = reports["preflight"].get("requested_scope") or {}
    return {
        "product_id": env_scope.get("product_id") or first.get("product_id", ""),
        "locale": env_scope.get("locale") or first.get("locale", ""),
        "field": env_scope.get("field") or first.get("field", ""),
        "proposed_value": env_scope.get("proposed_value") or first.get("proposed_value", ""),
    }


def _source_status_summary(reports: dict) -> dict:
    summary = locked._source_status_summary(
        {
            key: reports[key]
            for key in [
                "preflight",
                "backup",
                "plan",
                "gate",
                "design",
                "locked",
                "pre_execution",
                "final_human",
                "final_safe_shell",
                "execution_plan",
            ]
        }
    )
    summary["one_shot_locked_shell_status"] = (
        reports["one_shot_locked_shell"].get("one_shot_locked_shell_status", "")
        if reports["one_shot_locked_shell"]
        else ""
    )
    summary["one_shot_locked_shell_loaded"] = bool(reports["one_shot_locked_shell"])
    return summary


def _one_shot_locked_shell_summary(report: dict) -> dict:
    ack = (report.get("phase_12_1b_locked_shell_ack_summary") or {}) if report else {}
    return {
        "one_shot_locked_shell_status": report.get("one_shot_locked_shell_status", "") if report else "",
        "one_shot_locked_shell_only": bool(report.get("one_shot_locked_shell_only")) if report else False,
        "phase_12_1b_real_execution_allowed": bool(report.get("phase_12_1b_real_execution_allowed")) if report else False,
        "phase_12_1b_entry_allowed": bool(report.get("phase_12_1b_entry_allowed")) if report else False,
        "phase_12_1_entry_allowed": bool(report.get("phase_12_1_entry_allowed")) if report else False,
        "phase_12_entry_allowed": bool(report.get("phase_12_entry_allowed")) if report else False,
        "phase_12_1b_locked_shell_ack_present": bool(ack.get("ack_present")) if report else False,
        "phase_12_1b_locked_shell_ack_effective": bool(ack.get("ack_effective")) if report else False,
        "final_real_write_allowed": bool(report.get("final_real_write_allowed")) if report else False,
        "real_write_allowed": bool(report.get("real_write_allowed")) if report else False,
        "write_execution_allowed": bool(report.get("write_execution_allowed")) if report else False,
    }


def _blocking_conditions(
    validation_errors: list[str],
    proposed_change: dict,
    backup_summary: dict,
    final_gate_summary: dict,
    design_summary: dict,
    locked_runner_summary: dict,
    pre_execution_summary: dict,
    final_human_summary: dict,
    final_safe_shell_summary: dict,
    execution_plan_summary: dict,
    one_shot_locked_shell_summary: dict,
) -> list[str]:
    conditions = []
    mapping = {
        "missing_preflight_package": "missing_preflight_package",
        "missing_backup_fetch_report": "missing_backup_fetch_report",
        "missing_readback_rollback_plan": "missing_readback_rollback_plan",
        "missing_final_gate_package": "missing_final_gate_package",
        "missing_real_write_runner_design_package": "missing_real_write_runner_design_package",
        "missing_locked_runner_report": "missing_locked_runner_report",
        "missing_pre_execution_validation_report": "missing_pre_execution_validation_report",
        "missing_final_human_approval_package": "missing_final_human_approval_package",
        "missing_final_safe_shell_report": "missing_final_safe_shell_report",
        "missing_execution_plan_report": "missing_execution_plan_report",
        "missing_one_shot_locked_shell_report": "missing_one_shot_locked_shell_report",
        "missing_dangerous_flag": "missing_dangerous_flag",
        "missing_final_safe_shell_ack": "missing_final_safe_shell_ack",
        "missing_plan_ack": "missing_phase_12_1a_plan_ack",
        "missing_locked_shell_ack": "missing_locked_shell_ack",
        "missing_real_execution_ack": "missing_real_execution_ack",
        "invalid_dangerous_flag_value": "invalid_dangerous_flag_value",
        "invalid_final_safe_shell_ack_value": "invalid_final_safe_shell_ack_value",
        "invalid_plan_ack_value": "invalid_phase_12_1a_plan_ack_value",
        "invalid_locked_shell_ack_value": "invalid_locked_shell_ack_value",
        "invalid_real_execution_ack_value": "invalid_real_execution_ack_value",
        "scope_mismatch": "scope_mismatch",
        "environment_scope_mismatch": "environment_scope_mismatch",
        "invalid_product_id": "invalid_product_id",
        "invalid_fixed_product_id": "invalid_product_id",
        "invalid_fixed_locale": "invalid_locale",
        "invalid_sandbox_field": "invalid_field",
        "proposed_value_empty": "proposed_value_empty",
        "proposed_value_over_60_chars": "proposed_value_over_60_chars",
        "proposed_value_mismatch": "proposed_value_mismatch",
        "backup_not_verified": "backup_not_verified",
        "read_only_backup_query_not_performed": "read_only_backup_query_not_performed",
        "final_gate_not_ready": "final_gate_not_ready",
        "design_not_ready": "design_not_ready",
        "locked_runner_not_locked": "locked_runner_not_locked",
        "pre_execution_validation_not_ready": "pre_execution_validation_not_ready",
        "final_human_approval_not_ready": "final_human_approval_not_ready",
        "final_safe_shell_not_ready": "final_safe_shell_not_ready",
        "execution_plan_not_ready": "execution_plan_not_ready",
        "one_shot_locked_shell_not_ready": "one_shot_locked_shell_not_ready",
        "source_report_indicates_real_write_allowed": "source_report_indicates_real_write_allowed",
        "source_report_indicates_write_execution_allowed": "source_report_indicates_write_execution_allowed",
        "source_report_indicates_phase_12_entry_allowed": "source_report_indicates_phase_12_entry_allowed",
        "source_report_indicates_phase_12_1b_entry_allowed": "source_report_indicates_phase_12_1b_entry_allowed",
    }
    for error in validation_errors:
        if error in mapping:
            conditions.append(mapping[error])
        if error == "source_report_indicates_shopify_write":
            conditions.append("source_report_indicates_shopify_write")
        if error == "source_report_indicates_mutation":
            conditions.append("source_report_indicates_mutation")
        if error == "source_report_indicates_translations_register":
            conditions.append("source_report_indicates_translationsRegister")
        if error == "source_report_indicates_shopify_api_call":
            conditions.append("source_report_indicates_shopify_api_call")
    if not proposed_change["proposed_value"]:
        conditions.append("proposed_value_empty")
    if proposed_change["proposed_value_chars"] > locked.plan.shell.base.MAX_PROPOSED_VALUE_CHARS:
        conditions.append("proposed_value_over_60_chars")
    if not backup_summary["backup_source_is_verified"]:
        conditions.append("backup_not_verified")
    if not backup_summary["read_only_shopify_query_performed"]:
        conditions.append("read_only_backup_query_not_performed")
    if final_gate_summary["final_gate_status"] not in locked.plan.shell.base.READY_GATE_STATUSES:
        conditions.append("final_gate_not_ready")
    if design_summary["design_status"] not in locked.plan.shell.base.READY_DESIGN_STATUSES:
        conditions.append("design_not_ready")
    if locked_runner_summary["locked_runner_status"] not in locked.plan.shell.base.READY_LOCKED_STATUSES:
        conditions.append("locked_runner_not_locked")
    if pre_execution_summary["validation_status"] not in locked.plan.shell.base.READY_PRE_EXECUTION_STATUSES:
        conditions.append("pre_execution_validation_not_ready")
    if final_human_summary["approval_package_status"] not in locked.plan.shell.READY_FINAL_HUMAN_APPROVAL_STATUSES:
        conditions.append("final_human_approval_not_ready")
    if final_safe_shell_summary["final_safe_shell_status"] not in locked.plan.READY_FINAL_SAFE_SHELL_STATUSES:
        conditions.append("final_safe_shell_not_ready")
    if execution_plan_summary["execution_plan_status"] not in locked.READY_EXECUTION_PLAN_STATUSES:
        conditions.append("execution_plan_not_ready")
    if one_shot_locked_shell_summary["one_shot_locked_shell_status"] not in READY_ONE_SHOT_LOCKED_SHELL_STATUSES:
        conditions.append("one_shot_locked_shell_not_ready")
    if one_shot_locked_shell_summary["phase_12_1b_real_execution_allowed"] is not False:
        conditions.append("source_report_indicates_phase_12_1b_entry_allowed")
    if one_shot_locked_shell_summary["phase_12_1b_entry_allowed"] is not False:
        conditions.append("source_report_indicates_phase_12_1b_entry_allowed")
    return locked.plan.shell.base._unique(conditions)


def _execution_status(mode: str, blocking_conditions: list[str], execution_result: dict) -> str:
    if blocking_conditions:
        if "missing_real_execution_ack" in blocking_conditions:
            return "blocked_missing_real_execution_ack"
        if "invalid_real_execution_ack_value" in blocking_conditions:
            return "blocked_invalid_real_execution_ack"
        if "scope_mismatch" in blocking_conditions or "environment_scope_mismatch" in blocking_conditions:
            return "blocked_scope_mismatch"
        if "invalid_field" in blocking_conditions:
            return "blocked_invalid_field"
        if "proposed_value_mismatch" in blocking_conditions:
            return "blocked_proposed_value_mismatch"
        return "blocked"
    if mode == "dry-run":
        return "dry_run_real_write_not_executed"
    if execution_result.get("success") and execution_result.get("readback_matches_proposed_value"):
        return "real_write_succeeded_and_verified"
    if execution_result.get("translations_register_called") and execution_result.get("readback_performed"):
        return "real_write_verification_failed"
    return "real_write_failed"


def _empty_execution_result(scope: dict) -> dict:
    return {
        "success": False,
        "execution_attempted": False,
        "shopify_api_call_performed": False,
        "shopify_api_call_count": 0,
        "translations_register_called": False,
        "mutation_performed": False,
        "shopify_write_performed": False,
        "readback_performed": False,
        "readback_value": "",
        "readback_value_present": False,
        "readback_matches_proposed_value": False,
        "real_write_count": 0,
        "failure_type": "",
        "failure_reason": "",
        "user_errors": [],
        "graphql_errors_count": 0,
        "http_statuses": [],
        "product_id": scope.get("product_id", ""),
        "locale": scope.get("locale", ""),
        "field": scope.get("field", ""),
        "proposed_value": scope.get("proposed_value", ""),
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _execute_real_write_and_readback(scope: dict) -> dict:
    script = _build_django_shell_script(scope)
    command = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", script]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=False,
            timeout=DOCKER_TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            **_empty_execution_result(scope),
            "execution_attempted": True,
            "failure_type": "timeout",
            "failure_reason": f"Real write command timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
        }
    except FileNotFoundError as exc:
        return {
            **_empty_execution_result(scope),
            "execution_attempted": True,
            "failure_type": "missing_env",
            "failure_reason": str(exc),
        }
    except PermissionError as exc:
        return {
            **_empty_execution_result(scope),
            "execution_attempted": True,
            "failure_type": "docker_permission_denied",
            "failure_reason": str(exc),
        }

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if not parsed:
        parsed = {
            **_empty_execution_result(scope),
            "execution_attempted": True,
            "failure_type": "command_error",
            "failure_reason": "Real write command did not return parseable JSON.",
        }
    parsed.setdefault("success", completed.returncode == 0 and bool(parsed.get("readback_matches_proposed_value")))
    parsed.setdefault("exit_code", completed.returncode)
    parsed["stdout_tail"] = _tail(stdout)
    parsed["stderr_tail"] = _tail(stderr)
    if completed.returncode != 0 and not parsed.get("failure_type"):
        parsed["failure_type"] = _classify_command_failure(stdout, stderr)
    if completed.returncode != 0 and not parsed.get("failure_reason"):
        parsed["failure_reason"] = "Real write command failed."
    return {**_empty_execution_result(scope), **parsed}


def _build_django_shell_script(scope: dict) -> str:
    product_id_literal = json.dumps(scope["product_id"])
    locale_literal = json.dumps(scope["locale"])
    field_literal = json.dumps(scope["field"])
    proposed_value_literal = json.dumps(scope["proposed_value"])
    shop_literal = json.dumps(SHOP_DOMAIN)
    api_version_literal = json.dumps(SHOPIFY_API_VERSION)
    return f"""
import json
import requests
from shopify_sync.models import ShopifyInstallation

product_id = {product_id_literal}
locale = {locale_literal}
field = {field_literal}
proposed_value = {proposed_value_literal}
shop = {shop_literal}
api_version = {api_version_literal}

read_query = '''
query($id: ID!, $locale: String!) {{
  translatableResource(resourceId: $id) {{
    resourceId
    translatableContent {{
      key
      value
      digest
      locale
    }}
    translations(locale: $locale) {{
      key
      value
      locale
      outdated
    }}
  }}
}}
'''

mutation = '''
mutation($resourceId: ID!, $translations: [TranslationInput!]!) {{
  translationsRegister(resourceId: $resourceId, translations: $translations) {{
    userErrors {{
      field
      message
    }}
    translations {{
      key
      value
      locale
      outdated
    }}
  }}
}}
'''

result = {{
    "success": False,
    "execution_attempted": True,
    "product_id": product_id,
    "locale": locale,
    "field": field,
    "proposed_value": proposed_value,
    "shopify_api_call_performed": False,
    "shopify_api_call_count": 0,
    "translations_register_called": False,
    "mutation_performed": False,
    "shopify_write_performed": False,
    "readback_performed": False,
    "readback_value": "",
    "readback_value_present": False,
    "readback_matches_proposed_value": False,
    "real_write_count": 0,
    "shopify_mutations_called": [],
    "http_statuses": [],
    "user_errors": [],
    "graphql_errors_count": 0,
    "translatable_content_digest_available": False,
    "failure_type": "",
    "failure_reason": "",
}}

def finish(code):
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(code)

def fail(failure_type, reason, code=1):
    result["failure_type"] = failure_type
    result["failure_reason"] = reason
    finish(code)

try:
    installation = ShopifyInstallation.objects.get(shop=shop)
    token_value = getattr(installation, "access_" + "token")
    endpoint = "https://" + installation.shop + "/admin/api/" + api_version + "/graphql.json"
    token_header = "X-Shopify-" + "Access-Token"
    headers = {{token_header: token_value, "Content-Type": "application/json"}}

    def post_graphql(query, variables):
        response = requests.post(endpoint, json={{"query": query, "variables": variables}}, headers=headers, timeout=30)
        result["shopify_api_call_performed"] = True
        result["shopify_api_call_count"] += 1
        result["http_statuses"].append(response.status_code)
        try:
            data = response.json()
        except ValueError:
            fail("shopify_api_error", "Shopify GraphQL response was not JSON.")
        if response.status_code >= 400:
            fail("shopify_api_error", "Shopify GraphQL request failed with HTTP status " + str(response.status_code))
        if data.get("errors"):
            result["graphql_errors_count"] = len(data.get("errors") or [])
            fail("shopify_graphql_errors", "Shopify GraphQL returned errors.")
        return data.get("data") or {{}}

    read_data = post_graphql(read_query, {{"id": product_id, "locale": locale}})
    resource = (read_data.get("translatableResource") or {{}})
    if not resource:
        fail("readback_missing_resource", "Shopify translatableResource was empty before mutation.")
    source_item = next((item for item in (resource.get("translatableContent") or []) if item.get("key") == field), {{}})
    digest = source_item.get("digest")
    if not digest:
        fail("missing_translatable_content_digest", "meta_title translatableContent digest was not available.")
    result["translatable_content_digest_available"] = True

    result["translations_register_called"] = True
    result["mutation_performed"] = True
    result["shopify_mutations_called"] = ["translationsRegister"]
    mutation_data = post_graphql(
        mutation,
        {{
            "resourceId": product_id,
            "translations": [
                {{
                    "locale": locale,
                    "key": field,
                    "value": proposed_value,
                    "translatableContentDigest": digest,
                }}
            ],
        }},
    )
    register_result = mutation_data.get("translationsRegister") or {{}}
    user_errors = register_result.get("userErrors") or []
    result["user_errors"] = user_errors
    if user_errors:
        fail("translations_register_user_errors", "translationsRegister returned userErrors.")
    result["shopify_write_performed"] = True
    result["real_write_count"] = 1

    result["readback_performed"] = True
    readback_data = post_graphql(read_query, {{"id": product_id, "locale": locale}})
    readback_resource = (readback_data.get("translatableResource") or {{}})
    readback_item = next((item for item in (readback_resource.get("translations") or []) if item.get("key") == field), {{}})
    readback_value = str(readback_item.get("value") or "")
    result["readback_value"] = readback_value
    result["readback_value_present"] = bool(readback_value)
    result["readback_locale"] = readback_item.get("locale")
    result["readback_outdated"] = readback_item.get("outdated")
    result["readback_matches_proposed_value"] = readback_value == proposed_value
    if not readback_value:
        fail("readback_missing", "Readback did not return a meta_title value.")
    if readback_value != proposed_value:
        fail("readback_mismatch", "Readback value did not match proposed_value.")

    result["success"] = True
    finish(0)
except ShopifyInstallation.DoesNotExist:
    fail("missing_env", "Shopify installation was not found for the configured shop.")
except SystemExit:
    raise
except Exception as exc:
    fail("unknown", type(exc).__name__ + ": " + str(exc))
"""


def _parse_json_from_stdout(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _classify_command_failure(stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if "access is denied" in combined or "permission denied" in combined or "docker_engine" in combined:
        return "docker_permission_denied"
    if "no such file or directory" in combined or "not recognized" in combined:
        return "missing_env"
    return "command_error"


def _decode_bytes(value: bytes | None) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _tail(text: str, max_lines: int = 80) -> str:
    return "\n".join(text.splitlines()[-max_lines:])


def _translations_register_execution_summary(execution_result: dict, mode: str, real_run_attempted: bool) -> dict:
    return {
        "mode": mode,
        "real_run_attempted": real_run_attempted,
        "translations_register_allowed": real_run_attempted,
        "translations_register_called": bool(execution_result.get("translations_register_called")),
        "mutation_performed": bool(execution_result.get("mutation_performed")),
        "shopify_write_performed": bool(execution_result.get("shopify_write_performed")),
        "shopify_api_call_performed": bool(execution_result.get("shopify_api_call_performed")),
        "shopify_api_call_count": int(execution_result.get("shopify_api_call_count") or 0),
        "real_write_count": int(execution_result.get("real_write_count") or 0),
        "mutation_name": "translationsRegister",
        "user_errors": execution_result.get("user_errors") or [],
        "http_statuses": execution_result.get("http_statuses") or [],
    }


def _readback_summary(execution_result: dict, scope: dict) -> dict:
    return {
        "readback_required": True,
        "readback_performed": bool(execution_result.get("readback_performed")),
        "readback_scope": {
            "product_id": scope.get("product_id", ""),
            "locale": scope.get("locale", ""),
            "field": scope.get("field", ""),
        },
        "readback_value": execution_result.get("readback_value", ""),
        "readback_value_present": bool(execution_result.get("readback_value_present")),
        "readback_matches_proposed_value": bool(execution_result.get("readback_matches_proposed_value")),
        "readback_locale": execution_result.get("readback_locale"),
        "readback_outdated": execution_result.get("readback_outdated"),
    }


def _failure_summary(execution_status: str, execution_result: dict, blocking_conditions: list[str]) -> dict:
    return {
        "failure": execution_status not in {"dry_run_real_write_not_executed", "real_write_succeeded_and_verified"},
        "failure_reason": execution_result.get("failure_reason", ""),
        "failure_type": execution_result.get("failure_type", ""),
        "blocking_conditions": blocking_conditions,
        "rollback_approval_required": _rollback_approval_required(execution_status, execution_result),
        "verified_backup_preserved": True,
    }


def _rollback_approval_required(execution_status: str, execution_result: dict) -> bool:
    if execution_status in {"real_write_failed", "real_write_verification_failed"}:
        return bool(
            execution_result.get("translations_register_called")
            or execution_result.get("mutation_performed")
            or execution_result.get("shopify_write_performed")
        )
    return False


def _safety_summary(mode: str, real_run_attempted: bool, execution_result: dict) -> dict:
    return {
        "mode": mode,
        "one_shot_real_execution_task": True,
        "real_run_attempted": real_run_attempted,
        "dry_run_never_writes": mode == "dry-run",
        "real_write_scope_limited": True,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_product_id": EXPECTED_PRODUCT_ID,
        "allowed_locale": EXPECTED_LOCALE,
        "allowed_field": EXPECTED_FIELD,
        "allowed_proposed_value": EXPECTED_PROPOSED_VALUE,
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "automatic_rollback_allowed": False,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "shopify_api_call_performed": bool(execution_result.get("shopify_api_call_performed")),
        "translations_register_called": bool(execution_result.get("translations_register_called")),
        "shopify_write_performed": bool(execution_result.get("shopify_write_performed")),
        "readback_performed": bool(execution_result.get("readback_performed")),
    }


def _ack_summary(env_name: str, present: bool, value: str, valid: bool, effective: bool) -> dict:
    return {
        "ack_env": env_name,
        "ack_present": present,
        "ack_value": value,
        "ack_valid": valid,
        "ack_effective": effective,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    ONE_SHOT_EXECUTE_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(ONE_SHOT_EXECUTE_JSON_PATH.read_text(encoding="utf-8"))
    return ONE_SHOT_EXECUTE_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    ONE_SHOT_EXECUTE_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return ONE_SHOT_EXECUTE_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Execution Status", "execution_status"),
            ("One-Shot Real Execution Task", "one_shot_real_execution_task"),
            ("Real Write Scope Limited", "real_write_scope_limited"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Write Execution Allowed", "write_execution_allowed"),
            ("Translations Register Allowed", "translations_register_allowed"),
            ("Translations Register Called", "translations_register_called"),
            ("Mutation Performed", "mutation_performed"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Readback Performed", "readback_performed"),
            ("Readback Matches Proposed Value", "readback_matches_proposed_value"),
            ("Rollback Performed", "rollback_performed"),
            ("Automatic Rollback Performed", "automatic_rollback_performed"),
            ("Rollback Approval Required", "rollback_approval_required"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Requested Scope", payload.get("requested_scope", {})),
            ("Environment Scope", payload.get("environment_scope", {})),
            ("Source Status Summary", payload.get("source_status_summary", {})),
            ("Proposed Change", payload.get("proposed_change", {})),
            ("Verified Backup Summary", payload.get("verified_backup_summary", {})),
            ("Real Execution Ack Summary", payload.get("real_execution_ack_summary", {})),
            ("Translations Register Execution Summary", payload.get("translations_register_execution_summary", {})),
            ("Readback Summary", payload.get("readback_summary", {})),
            ("Verification Summary", payload.get("verification_summary", {})),
            ("Failure Summary", payload.get("failure_summary", {})),
            ("Rollback Approval Requirement", payload.get("rollback_approval_requirement", {})),
            ("Safety Summary", payload.get("safety_summary", {})),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Real Write One-Shot Execute</title>
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
  <h1>Shopify Single-Field Real Write One-Shot Execute</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Execution Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>Dry-run mode never calls Shopify APIs or writes Shopify.</li>
    <li>Real-run mode is limited to one product, one locale, and field=meta_title.</li>
    <li>Real-run mode requires the exact final execution ack phrase.</li>
    <li>Rollback is never automatic.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(execution_status: str, blocking_conditions: list[str], execution_result: dict) -> str:
    if blocking_conditions:
        return "Single-field one-shot real write execute blocked: " + ", ".join(blocking_conditions)
    if execution_status == "dry_run_real_write_not_executed":
        return "Dry-run completed. Real Shopify write was not executed."
    if execution_status == "real_write_succeeded_and_verified":
        return "Real Shopify translationsRegister write succeeded and immediate readback matched proposed_value."
    return "Real Shopify one-shot write failed: " + (execution_result.get("failure_reason") or execution_result.get("failure_type") or "unknown")


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field real write one-shot execute report generated.\n"
        f"Mode: {payload.get('mode')}\n"
        f"Execution status: {payload.get('execution_status')}\n"
        f"Requested scope: {payload.get('requested_scope')}\n"
        f"Translations register called: {payload.get('translations_register_called')}\n"
        f"Shopify write performed: {payload.get('shopify_write_performed')}\n"
        f"Readback performed: {payload.get('readback_performed')}\n"
        f"Readback matches proposed value: {payload.get('readback_matches_proposed_value')}\n"
        f"Rollback approval required: {payload.get('rollback_approval_required')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Execution report JSON:\n"
        f"{json_path}\n\n"
        "Execution report HTML:\n"
        f"{html_path}\n"
        "Dry-run mode is no-write. Real-run mode requires a separate explicit command and all required ack variables.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep execution report files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Do not push from this task."
    )
