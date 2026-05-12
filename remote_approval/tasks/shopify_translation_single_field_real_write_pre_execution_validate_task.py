import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_real_write_pre_execution_validate"
COMMAND_LABEL = "shopify_translation_single_field_real_write_pre_execution_validate"
SOURCE_PREFLIGHT_PACKAGE_PATH = LOG_DIR / "shopify_translation_single_field_apply_preflight_package.json"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
SOURCE_READBACK_ROLLBACK_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.json"
SOURCE_FINAL_WRITE_GATE_PATH = LOG_DIR / "shopify_translation_single_field_final_write_gate.json"
SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_design.json"
SOURCE_REAL_WRITE_LOCKED_RUNNER_PATH = LOG_DIR / "shopify_translation_single_field_real_write_locked_runner.json"
PRE_EXECUTION_VALIDATE_JSON_PATH = LOG_DIR / "shopify_translation_single_field_real_write_pre_execution_validate.json"
PRE_EXECUTION_VALIDATE_HTML_PATH = LOG_DIR / "shopify_translation_single_field_real_write_pre_execution_validate.html"
EXPECTED_PREFLIGHT_TASK = "shopify_translation_single_field_apply_preflight_package"
EXPECTED_PREFLIGHT_MODE = "single-field-preflight-only"
EXPECTED_BACKUP_TASK = "shopify_translation_single_field_backup_fetch"
EXPECTED_BACKUP_MODE = "read-only-backup-fetch"
EXPECTED_PLAN_TASK = "shopify_translation_single_field_readback_rollback_plan"
EXPECTED_PLAN_MODE = "readback-rollback-plan-only"
EXPECTED_GATE_TASK = "shopify_translation_single_field_final_write_gate"
EXPECTED_GATE_MODE = "final-write-gate-package-only"
EXPECTED_DESIGN_TASK = "shopify_translation_single_field_real_write_runner_design"
EXPECTED_DESIGN_MODE = "real-write-runner-design-only"
EXPECTED_LOCKED_TASK = "shopify_translation_single_field_real_write_locked_runner"
EXPECTED_LOCKED_MODE = "locked-real-write-runner-shell-only"
ALLOWED_FIELD = "meta_title"
ALLOWED_LOCALES = {"de", "fr", "es", "it", "ja"}
READY_PLAN_STATUSES = {"ready_for_manual_review", "verified_backup_ready", "ready_for_final_write_gate"}
READY_GATE_STATUSES = {"ready_for_human_final_approval"}
READY_DESIGN_STATUSES = {"design_ready_for_manual_review", "ready_for_runner_design_review"}
READY_LOCKED_STATUSES = {"ready_but_locked", "locked_not_executed"}
SAFE_BACKUP_STATUSES = {"completed", "backup_ready", "ready_for_manual_review"}
MAX_PROPOSED_VALUE_CHARS = 60
FUTURE_REQUIRED_FLAG = "--i-understand-this-writes-shopify"
DANGEROUS_FLAG_ENV = "SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY"
ENV_PRODUCT_ID = "SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID"
ENV_LOCALE = "SHOPIFY_TRANSLATION_SANDBOX_LOCALE"
ENV_FIELD = "SHOPIFY_TRANSLATION_SANDBOX_FIELD"
ENV_PROPOSED_VALUE = "SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE"
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/[0-9]+$")


def run_shopify_translation_single_field_real_write_pre_execution_validate_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
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
    ]:
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

    env_scope = _env_requested_scope()
    dangerous_flag_value = os.environ.get(DANGEROUS_FLAG_ENV, "").strip()
    dangerous_flag_present = bool(dangerous_flag_value)
    dangerous_flag_valid = dangerous_flag_value.lower() == "true"
    validation_errors.extend(_validate_env_scope(env_scope))
    if not dangerous_flag_present:
        validation_errors.append("missing_dangerous_flag")
    elif not dangerous_flag_valid:
        validation_errors.append("invalid_dangerous_flag_value")

    if reports["preflight"]:
        validation_errors.extend(_validate_preflight(reports["preflight"]))
    if reports["backup"]:
        validation_errors.extend(_validate_backup(reports["backup"]))
    if reports["plan"]:
        validation_errors.extend(_validate_plan(reports["plan"]))
    if reports["gate"]:
        validation_errors.extend(_validate_gate(reports["gate"]))
    if reports["design"]:
        validation_errors.extend(_validate_design(reports["design"]))
    if reports["locked"]:
        validation_errors.extend(_validate_locked(reports["locked"]))
    if all(reports.values()):
        validation_errors.extend(_validate_scope_match(reports, env_scope))
        validation_errors.extend(_validate_proposed_value_match(reports, env_scope))

    requested_scope = _requested_scope(reports, env_scope)
    proposed_change = _proposed_change(requested_scope)
    verified_backup_summary = _verified_backup_summary(reports["backup"])
    final_gate_summary = _final_gate_summary(reports["gate"])
    design_summary = _design_summary(reports["design"])
    locked_runner_summary = _locked_runner_summary(reports["locked"])
    pre_execution_checks = _pre_execution_checks(
        requested_scope,
        env_scope,
        reports,
        dangerous_flag_present,
        dangerous_flag_valid,
        validation_errors,
        verified_backup_summary,
        final_gate_summary,
        design_summary,
        locked_runner_summary,
    )
    blocking_conditions = _blocking_conditions(
        validation_errors,
        proposed_change,
        verified_backup_summary,
        final_gate_summary,
        design_summary,
        locked_runner_summary,
    )
    validation_status = _validation_status(blocking_conditions)
    success = not blocking_conditions
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "pre-execution-validation-only",
        "command_label": COMMAND_LABEL,
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "source_readback_rollback_plan_path": str(SOURCE_READBACK_ROLLBACK_PLAN_PATH),
        "source_final_write_gate_path": str(SOURCE_FINAL_WRITE_GATE_PATH),
        "source_real_write_runner_design_path": str(SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH),
        "source_real_write_locked_runner_path": str(SOURCE_REAL_WRITE_LOCKED_RUNNER_PATH),
        "json_pre_execution_validate_path": str(PRE_EXECUTION_VALIDATE_JSON_PATH),
        "html_pre_execution_validate_path": str(PRE_EXECUTION_VALIDATE_HTML_PATH),
        "success": success,
        "validation_status": validation_status,
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if _valid_product_id(requested_scope.get("product_id", "")) else 0,
            "locale_count": 1 if requested_scope.get("locale") in ALLOWED_LOCALES else 0,
            "field_count": 1 if requested_scope.get("field") == ALLOWED_FIELD else 0,
            "field": requested_scope.get("field", ""),
            "field_allowed": requested_scope.get("field") == ALLOWED_FIELD,
            "scope_matches_all_sources": "scope_mismatch" not in validation_errors,
            "environment_scope_matches_reports": "environment_scope_mismatch" not in validation_errors,
            "proposed_value_matches_all_sources": "proposed_value_mismatch" not in validation_errors,
            "allowed_field": ALLOWED_FIELD,
            "allowed_locales": sorted(ALLOWED_LOCALES),
        },
        "environment_scope": env_scope,
        "source_status_summary": _source_status_summary(reports),
        "proposed_change": proposed_change,
        "verified_backup_summary": verified_backup_summary,
        "final_gate_summary": final_gate_summary,
        "design_summary": design_summary,
        "locked_runner_summary": locked_runner_summary,
        "dangerous_flag_validation": {
            "dangerous_flag_name": FUTURE_REQUIRED_FLAG,
            "dangerous_flag_env": DANGEROUS_FLAG_ENV,
            "dangerous_flag_present": dangerous_flag_present,
            "dangerous_flag_value": dangerous_flag_value,
            "dangerous_flag_required": True,
            "dangerous_flag_effective": False,
            "dangerous_flag_note": (
                "This phase only validates that the dangerous flag exists and equals true; "
                "it does not trigger any real Shopify write."
            ),
        },
        "pre_execution_checks": pre_execution_checks,
        "manual_approval_requirements": _manual_approval_requirements(),
        "future_execution_constraints": _future_execution_constraints(),
        "readback_requirements": _readback_requirements(),
        "rollback_requirements": _rollback_requirements(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(),
        "future_required_flag": FUTURE_REQUIRED_FLAG,
        "pre_execution_validation_only": True,
        "final_real_write_allowed": False,
        "real_write_allowed": False,
        "write_execution_allowed": False,
        "translations_register_allowed": False,
        "translations_register_called": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "command_executed": False,
        "mutation_performed": False,
        "shopify_mutations_called": [],
        "shopify_api_call_performed": False,
        "readback_performed": False,
        "rollback_performed": False,
        "real_apply_performed": False,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "validation_warnings": _unique(validation_warnings),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(validation_status, blocking_conditions),
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
        "json_pre_execution_validate_path": str(json_path),
        "html_pre_execution_validate_path": str(html_path),
        "validation_status": validation_status,
        "dangerous_flag_present": dangerous_flag_present,
        "dangerous_flag_effective": False,
        "pre_execution_validation_only": True,
        "backup_source_is_verified": verified_backup_summary["backup_source_is_verified"],
        "final_gate_status": final_gate_summary["final_gate_status"],
        "design_status": design_summary["design_status"],
        "locked_runner_status": locked_runner_summary["locked_runner_status"],
        "final_real_write_allowed": False,
        "real_write_allowed": False,
        "write_execution_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "real_apply_performed": False,
        "all_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "validation_warnings_count": len(payload["validation_warnings"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _env_requested_scope() -> dict:
    return {
        "product_id": os.environ.get(ENV_PRODUCT_ID, "").strip(),
        "locale": os.environ.get(ENV_LOCALE, "").strip(),
        "field": os.environ.get(ENV_FIELD, "").strip(),
        "proposed_value": os.environ.get(ENV_PROPOSED_VALUE, "").strip(),
    }


def _validate_env_scope(scope: dict) -> list[str]:
    errors = []
    if not scope.get("product_id"):
        errors.append("missing_sandbox_product_id")
    if not scope.get("locale"):
        errors.append("missing_sandbox_locale")
    if not scope.get("field"):
        errors.append("missing_sandbox_field")
    if not scope.get("proposed_value"):
        errors.append("proposed_value_empty")
    elif len(str(scope.get("proposed_value") or "")) > MAX_PROPOSED_VALUE_CHARS:
        errors.append("proposed_value_over_60_chars")
    errors.extend(_validate_scope(scope))
    return _unique(errors)


def _validate_preflight(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_PREFLIGHT_TASK or report.get("mode") != EXPECTED_PREFLIGHT_MODE:
        errors.append("unsafe_preflight_package")
    if report.get("preflight_status") != "ready_for_manual_review":
        errors.append("preflight_not_ready")
    scope = report.get("requested_scope") or {}
    errors.extend(_validate_scope(scope))
    errors.extend(_validate_proposed_value(scope))
    errors.extend(_validate_no_write_flags(report))
    if report.get("shopify_api_called") is True or report.get("shopify_api_call_performed") is True:
        errors.append("source_report_indicates_shopify_api_call")
    return _unique(errors)


def _validate_backup(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_BACKUP_TASK or report.get("mode") != EXPECTED_BACKUP_MODE:
        errors.append("unsafe_backup_fetch_report")
    if report.get("backup_fetch_status") not in SAFE_BACKUP_STATUSES:
        errors.append("unsafe_backup_fetch_status")
    scope = {
        "product_id": report.get("backup_product_id") or (report.get("requested_scope") or {}).get("product_id", ""),
        "locale": report.get("backup_locale") or (report.get("requested_scope") or {}).get("locale", ""),
        "field": report.get("backup_field") or (report.get("requested_scope") or {}).get("field", ""),
    }
    errors.extend(_validate_scope(scope))
    if report.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")
    errors.extend(_validate_no_write_flags(report))
    if report.get("shopify_mutations_called") not in ([], None):
        errors.append("source_report_indicates_mutation")
    return _unique(errors)


def _validate_plan(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_PLAN_TASK or report.get("mode") != EXPECTED_PLAN_MODE:
        errors.append("unsafe_readback_rollback_plan")
    plan_status = report.get("plan_status")
    if plan_status not in READY_PLAN_STATUSES:
        errors.append("readback_rollback_plan_not_ready")
    if plan_status in {"ready_for_real_write", "write_allowed", "execution_allowed"}:
        errors.append("unsafe_readback_rollback_plan_status")
    scope = report.get("proposed_change") or report.get("requested_scope") or {}
    errors.extend(_validate_scope(scope))
    errors.extend(_validate_proposed_value(scope))
    backup_completeness = report.get("backup_completeness") or {}
    if backup_completeness.get("backup_source_is_verified") is not True:
        errors.append("backup_not_verified")
    if backup_completeness.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")
    errors.extend(_validate_no_write_flags(report))
    for field in ["shopify_api_call_performed", "readback_performed", "rollback_performed"]:
        if report.get(field) is True:
            errors.append("source_report_indicates_shopify_write")
    return _unique(errors)


def _validate_gate(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_GATE_TASK or report.get("mode") != EXPECTED_GATE_MODE:
        errors.append("unsafe_final_gate_package")
    if report.get("final_gate_status") not in READY_GATE_STATUSES:
        errors.append("final_gate_not_ready")
    scope = report.get("proposed_change") or report.get("requested_scope") or {}
    errors.extend(_validate_scope(scope))
    errors.extend(_validate_proposed_value(scope))
    backup_summary = report.get("verified_backup_summary") or {}
    if backup_summary.get("backup_source_is_verified") is not True:
        errors.append("backup_not_verified")
    if backup_summary.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")
    if report.get("final_real_write_allowed") is not False:
        errors.append("source_report_indicates_real_write_allowed")
    errors.extend(_validate_no_write_flags(report))
    for field in ["shopify_api_call_performed", "readback_performed", "rollback_performed"]:
        if report.get(field) is True:
            errors.append("source_report_indicates_shopify_write")
    return _unique(errors)


def _validate_design(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_DESIGN_TASK or report.get("mode") != EXPECTED_DESIGN_MODE:
        errors.append("unsafe_real_write_runner_design")
    if report.get("design_status") not in READY_DESIGN_STATUSES:
        errors.append("design_not_ready")
    if report.get("design_only") is not True:
        errors.append("design_not_ready")
    scope = report.get("proposed_change") or report.get("requested_scope") or {}
    errors.extend(_validate_scope(scope))
    errors.extend(_validate_proposed_value(scope))
    if report.get("final_real_write_allowed") is not False or report.get("real_write_allowed") is True:
        errors.append("source_report_indicates_real_write_allowed")
    errors.extend(_validate_no_write_flags(report))
    for field in ["shopify_api_call_performed", "readback_performed", "rollback_performed"]:
        if report.get(field) is True:
            errors.append("source_report_indicates_shopify_write")
    return _unique(errors)


def _validate_locked(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_LOCKED_TASK or report.get("mode") != EXPECTED_LOCKED_MODE:
        errors.append("unsafe_locked_runner_report")
    if report.get("locked_runner_status") not in READY_LOCKED_STATUSES:
        errors.append("locked_runner_not_locked")
    if report.get("locked_shell") is not True:
        errors.append("locked_runner_not_locked")
    if report.get("dangerous_flag_effective") is not False:
        errors.append("unsafe_dangerous_flag_effective")
    dangerous = report.get("dangerous_flag_summary") or {}
    if dangerous.get("dangerous_flag_effective") is not False:
        errors.append("unsafe_dangerous_flag_effective")
    scope = report.get("proposed_change") or report.get("requested_scope") or {}
    errors.extend(_validate_scope(scope))
    errors.extend(_validate_proposed_value(scope))
    if report.get("final_real_write_allowed") is not False or report.get("real_write_allowed") is True:
        errors.append("source_report_indicates_real_write_allowed")
    errors.extend(_validate_no_write_flags(report))
    for field in ["shopify_api_call_performed", "readback_performed", "rollback_performed"]:
        if report.get(field) is True:
            errors.append("source_report_indicates_shopify_write")
    return _unique(errors)


def _validate_scope(scope: dict) -> list[str]:
    errors = []
    product_id = str(scope.get("product_id") or "")
    locale = str(scope.get("locale") or "")
    field = str(scope.get("field") or "")
    if not PRODUCT_GID_RE.match(product_id):
        errors.append("invalid_product_id")
    if not locale or "," in locale or locale not in ALLOWED_LOCALES:
        errors.append("invalid_sandbox_locale")
    if field != ALLOWED_FIELD:
        errors.append("invalid_sandbox_field")
    return _unique(errors)


def _validate_proposed_value(scope: dict) -> list[str]:
    value = str(scope.get("proposed_value") or "")
    if not value:
        return ["proposed_value_empty"]
    if len(value) > MAX_PROPOSED_VALUE_CHARS:
        return ["proposed_value_over_60_chars"]
    return []


def _validate_no_write_flags(report: dict) -> list[str]:
    errors = []
    unsafe_true_fields = [
        "shopify_write_performed",
        "apply_performed",
        "publish_performed",
        "translations_register_performed",
        "translations_register_called",
        "command_executed",
        "mutation_performed",
        "real_apply_performed",
    ]
    for field in unsafe_true_fields:
        if report.get(field) is True:
            if field in {"translations_register_performed", "translations_register_called"}:
                errors.append("source_report_indicates_translations_register")
            elif field == "mutation_performed":
                errors.append("source_report_indicates_mutation")
            else:
                errors.append("source_report_indicates_shopify_write")
    if report.get("real_write_allowed") is True or report.get("final_real_write_allowed") is True:
        errors.append("source_report_indicates_real_write_allowed")
    if report.get("translations_register_allowed") is True:
        errors.append("source_report_indicates_translations_register")
    if report.get("shopify_mutations_called") not in ([], None):
        errors.append("source_report_indicates_mutation")
    if report.get("no_shopify_writes_performed") is not True:
        errors.append("no_write_not_confirmed")
    if report.get("all_no_write_confirmed") is not True:
        errors.append("no_write_not_confirmed")
    return _unique(errors)


def _validate_scope_match(reports: dict, env_scope: dict) -> list[str]:
    errors = []
    scopes = _all_scopes(reports) + [env_scope]
    first = scopes[0] if scopes else {}
    for scope in scopes[1:]:
        for key in ["product_id", "locale", "field"]:
            if first.get(key) != scope.get(key):
                errors.append("scope_mismatch")
        for key in ["product_id", "locale", "field"]:
            if env_scope.get(key) != scope.get(key):
                errors.append("environment_scope_mismatch")
    return _unique(errors)


def _validate_proposed_value_match(reports: dict, env_scope: dict) -> list[str]:
    values = _all_proposed_values(reports) + [str(env_scope.get("proposed_value") or "")]
    nonempty = [value for value in values if value]
    if not nonempty:
        return ["proposed_value_empty"]
    if len(set(nonempty)) > 1:
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
        reports["design"].get("proposed_change") or reports["design"].get("requested_scope") or {},
        reports["locked"].get("proposed_change") or reports["locked"].get("requested_scope") or {},
    ]


def _all_proposed_values(reports: dict) -> list[str]:
    return [
        str((reports["preflight"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["plan"].get("proposed_change") or reports["plan"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["gate"].get("proposed_change") or reports["gate"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["design"].get("proposed_change") or reports["design"].get("requested_scope") or {}).get("proposed_value") or ""),
        str((reports["locked"].get("proposed_change") or reports["locked"].get("requested_scope") or {}).get("proposed_value") or ""),
    ]


def _requested_scope(reports: dict, env_scope: dict) -> dict:
    first = reports["preflight"].get("requested_scope") or {}
    return {
        "product_id": env_scope.get("product_id") or first.get("product_id", ""),
        "locale": env_scope.get("locale") or first.get("locale", ""),
        "field": env_scope.get("field") or first.get("field", ""),
        "proposed_value": env_scope.get("proposed_value") or first.get("proposed_value", ""),
    }


def _proposed_change(scope: dict) -> dict:
    value = str(scope.get("proposed_value") or "")
    return {
        "product_id": scope.get("product_id", ""),
        "locale": scope.get("locale", ""),
        "field": scope.get("field", ""),
        "proposed_value": value,
        "proposed_value_chars": len(value),
        "proposed_value_length_allowed": 0 < len(value) <= MAX_PROPOSED_VALUE_CHARS,
    }


def _verified_backup_summary(backup: dict) -> dict:
    value = str(backup.get("backup_value") or "") if backup else ""
    return {
        "backup_source_is_verified": _backup_source_is_verified(backup),
        "read_only_shopify_query_performed": bool(backup.get("read_only_shopify_query_performed")) if backup else False,
        "backup_value_present": bool(backup.get("backup_value_present")) if backup else False,
        "backup_value": value,
        "backup_value_chars": len(value),
        "backup_locale": backup.get("backup_locale", "") if backup else "",
        "backup_field": backup.get("backup_field", "") if backup else "",
        "backup_product_id": backup.get("backup_product_id", "") if backup else "",
        "backup_generated_at": backup.get("backup_generated_at", "") if backup else "",
        "backup_value_source": backup.get("backup_value_source", "") if backup else "",
    }


def _backup_source_is_verified(backup: dict) -> bool:
    if not backup:
        return False
    required = [
        "backup_value_present",
        "backup_value",
        "backup_locale",
        "backup_field",
        "backup_product_id",
        "backup_generated_at",
        "read_only_shopify_query_performed",
    ]
    return bool(backup.get("read_only_shopify_query_performed")) and all(key in backup for key in required)


def _final_gate_summary(gate: dict) -> dict:
    return {
        "final_gate_status": gate.get("final_gate_status", "") if gate else "",
        "final_real_write_allowed": bool(gate.get("final_real_write_allowed")) if gate else False,
        "real_write_allowed": bool(gate.get("real_write_allowed")) if gate else False,
    }


def _design_summary(design: dict) -> dict:
    return {
        "design_status": design.get("design_status", "") if design else "",
        "design_only": bool(design.get("design_only")) if design else False,
        "final_real_write_allowed": bool(design.get("final_real_write_allowed")) if design else False,
        "real_write_allowed": bool(design.get("real_write_allowed")) if design else False,
    }


def _locked_runner_summary(locked: dict) -> dict:
    return {
        "locked_runner_status": locked.get("locked_runner_status", "") if locked else "",
        "locked_shell": bool(locked.get("locked_shell")) if locked else False,
        "dangerous_flag_effective": bool(locked.get("dangerous_flag_effective")) if locked else False,
        "final_real_write_allowed": bool(locked.get("final_real_write_allowed")) if locked else False,
        "real_write_allowed": bool(locked.get("real_write_allowed")) if locked else False,
    }


def _source_status_summary(reports: dict) -> dict:
    return {
        "preflight_status": reports["preflight"].get("preflight_status", "") if reports["preflight"] else "",
        "backup_fetch_status": reports["backup"].get("backup_fetch_status", "") if reports["backup"] else "",
        "readback_rollback_plan_status": reports["plan"].get("plan_status", "") if reports["plan"] else "",
        "final_gate_status": reports["gate"].get("final_gate_status", "") if reports["gate"] else "",
        "real_write_runner_design_status": reports["design"].get("design_status", "") if reports["design"] else "",
        "locked_runner_status": reports["locked"].get("locked_runner_status", "") if reports["locked"] else "",
        "preflight_source_loaded": bool(reports["preflight"]),
        "backup_source_loaded": bool(reports["backup"]),
        "readback_rollback_plan_loaded": bool(reports["plan"]),
        "final_gate_loaded": bool(reports["gate"]),
        "real_write_runner_design_loaded": bool(reports["design"]),
        "locked_runner_loaded": bool(reports["locked"]),
    }


def _pre_execution_checks(
    requested_scope: dict,
    env_scope: dict,
    reports: dict,
    dangerous_flag_present: bool,
    dangerous_flag_valid: bool,
    validation_errors: list[str],
    backup_summary: dict,
    final_gate_summary: dict,
    design_summary: dict,
    locked_runner_summary: dict,
) -> dict:
    return {
        "product_id_valid": _check(_valid_product_id(requested_scope.get("product_id", ""))),
        "locale_single": _check(requested_scope.get("locale") in ALLOWED_LOCALES and "," not in requested_scope.get("locale", "")),
        "field_is_meta_title": _check(requested_scope.get("field") == ALLOWED_FIELD),
        "proposed_value_non_empty": _check(bool(requested_scope.get("proposed_value"))),
        "proposed_value_within_60_chars": _check(len(str(requested_scope.get("proposed_value") or "")) <= MAX_PROPOSED_VALUE_CHARS),
        "scope_consistent_across_all_source_reports": _check("scope_mismatch" not in validation_errors),
        "environment_scope_matches_reports": _check("environment_scope_mismatch" not in validation_errors),
        "proposed_value_matches_all_source_reports": _check("proposed_value_mismatch" not in validation_errors),
        "backup_verified": _check(backup_summary["backup_source_is_verified"]),
        "read_only_backup_query_performed": _check(backup_summary["read_only_shopify_query_performed"]),
        "final_gate_ready": _check(final_gate_summary["final_gate_status"] in READY_GATE_STATUSES),
        "design_ready": _check(design_summary["design_status"] in READY_DESIGN_STATUSES and design_summary["design_only"]),
        "locked_runner_remains_locked": _check(
            locked_runner_summary["locked_runner_status"] in READY_LOCKED_STATUSES and locked_runner_summary["locked_shell"]
        ),
        "dangerous_flag_present": _check(dangerous_flag_present),
        "dangerous_flag_value_is_true": _check(dangerous_flag_valid),
        "no_source_write_detected": _check("source_report_indicates_shopify_write" not in validation_errors),
        "no_source_mutation_detected": _check("source_report_indicates_mutation" not in validation_errors),
        "no_source_translations_register_detected": _check(
            "source_report_indicates_translations_register" not in validation_errors
        ),
        "no_real_write_allowed_detected": _check("source_report_indicates_real_write_allowed" not in validation_errors),
        "environment_scope": env_scope,
        "source_reports_loaded": {
            key: bool(value) for key, value in reports.items()
        },
    }


def _check(condition: bool) -> str:
    return "pass" if condition else "fail"


def _blocking_conditions(
    validation_errors: list[str],
    proposed_change: dict,
    backup_summary: dict,
    final_gate_summary: dict,
    design_summary: dict,
    locked_runner_summary: dict,
) -> list[str]:
    conditions = []
    mapping = {
        "missing_preflight_package": "missing_preflight_package",
        "missing_backup_fetch_report": "missing_backup_fetch_report",
        "missing_readback_rollback_plan": "missing_readback_rollback_plan",
        "missing_final_gate_package": "missing_final_gate_package",
        "missing_real_write_runner_design_package": "missing_real_write_runner_design_package",
        "missing_locked_runner_report": "missing_locked_runner_report",
        "missing_dangerous_flag": "missing_dangerous_flag",
        "invalid_dangerous_flag_value": "invalid_dangerous_flag_value",
        "scope_mismatch": "scope_mismatch",
        "environment_scope_mismatch": "environment_scope_mismatch",
        "invalid_product_id": "invalid_product_id",
        "invalid_sandbox_field": "invalid_field",
        "proposed_value_empty": "proposed_value_empty",
        "proposed_value_over_60_chars": "proposed_value_over_60_chars",
        "proposed_value_mismatch": "proposed_value_mismatch",
        "backup_not_verified": "backup_not_verified",
        "read_only_backup_query_not_performed": "read_only_backup_query_not_performed",
        "final_gate_not_ready": "final_gate_not_ready",
        "design_not_ready": "design_not_ready",
        "locked_runner_not_locked": "locked_runner_not_locked",
        "source_report_indicates_real_write_allowed": "source_report_indicates_real_write_allowed",
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
    if proposed_change["proposed_value_chars"] > MAX_PROPOSED_VALUE_CHARS:
        conditions.append("proposed_value_over_60_chars")
    if not backup_summary["backup_source_is_verified"]:
        conditions.append("backup_not_verified")
    if not backup_summary["read_only_shopify_query_performed"]:
        conditions.append("read_only_backup_query_not_performed")
    if final_gate_summary["final_gate_status"] not in READY_GATE_STATUSES:
        conditions.append("final_gate_not_ready")
    if design_summary["design_status"] not in READY_DESIGN_STATUSES:
        conditions.append("design_not_ready")
    if locked_runner_summary["locked_runner_status"] not in READY_LOCKED_STATUSES:
        conditions.append("locked_runner_not_locked")
    return _unique(conditions)


def _validation_status(blocking_conditions: list[str]) -> str:
    if not blocking_conditions:
        return "ready_for_manual_write_approval"
    if "missing_dangerous_flag" in blocking_conditions:
        return "blocked_missing_dangerous_flag"
    if "invalid_dangerous_flag_value" in blocking_conditions:
        return "blocked_invalid_dangerous_flag"
    if "scope_mismatch" in blocking_conditions or "environment_scope_mismatch" in blocking_conditions:
        return "blocked_scope_mismatch"
    if "invalid_field" in blocking_conditions:
        return "blocked_invalid_field"
    if "proposed_value_mismatch" in blocking_conditions:
        return "blocked_proposed_value_mismatch"
    if "backup_not_verified" in blocking_conditions:
        return "blocked_backup_not_verified"
    if "final_gate_not_ready" in blocking_conditions:
        return "blocked_final_gate_not_ready"
    if "design_not_ready" in blocking_conditions:
        return "blocked_design_not_ready"
    if "locked_runner_not_locked" in blocking_conditions:
        return "blocked_locked_runner_not_locked"
    return "blocked"


def _manual_approval_requirements() -> list[str]:
    return [
        "Human must review this validation report.",
        "Human must confirm product_id.",
        "Human must confirm locale.",
        "Human must confirm field=meta_title.",
        "Human must confirm proposed_value.",
        "Human must confirm backup_value.",
        "Human must confirm rollback plan.",
        "Human must confirm readback plan.",
        "Human must explicitly approve a later independent real-write phase.",
        "This task does not approve or execute a real write.",
    ]


def _future_execution_constraints() -> list[str]:
    return [
        "Future real write must be a separate task/phase.",
        f"Future real write must require {FUTURE_REQUIRED_FLAG} again.",
        "Future real write must still limit to 1 product x 1 locale x 1 field=meta_title.",
        "Future real write must immediately perform readback.",
        "Future rollback must be separately approved.",
        "Future task must not allow batch mode.",
        "Future task must not allow full-store scan.",
        "Future task must not allow multiple locales or fields.",
    ]


def _readback_requirements() -> list[str]:
    return [
        "Read back the same product_id.",
        "Read back the same locale.",
        "Read back field=meta_title.",
        "Compare exact value with proposed_value.",
        "Failure must block success status.",
        "Readback result must be recorded locally.",
    ]


def _rollback_requirements() -> list[str]:
    return [
        "Rollback must not be automatic.",
        "Rollback requires separate approval.",
        "Rollback can only use verified backup_value.",
        "Rollback scope must be same product_id x locale x meta_title.",
        "Rollback must also be readback verified.",
    ]


def _safety_summary() -> dict:
    return {
        "pre_execution_validation_only": True,
        "shopify_api_call_allowed": False,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
        "command_execution_allowed": False,
        "automatic_shopify_product_scan_allowed": False,
        "batch_mode_allowed": False,
        "database_write_allowed": False,
        "git_push_allowed": False,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": ALLOWED_FIELD,
    }


def _valid_product_id(product_id: str) -> bool:
    return bool(PRODUCT_GID_RE.match(product_id))


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    PRE_EXECUTION_VALIDATE_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(PRE_EXECUTION_VALIDATE_JSON_PATH.read_text(encoding="utf-8"))
    return PRE_EXECUTION_VALIDATE_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    PRE_EXECUTION_VALIDATE_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return PRE_EXECUTION_VALIDATE_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Validation Status", "validation_status"),
            ("Dangerous Flag", "dangerous_flag_validation"),
            ("Pre-Execution Validation Only", "pre_execution_validation_only"),
            ("Write Execution Allowed", "write_execution_allowed"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("Translations Register Called", "translations_register_called"),
            ("Readback Performed", "readback_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("Real Apply Performed", "real_apply_performed"),
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
            ("Final Gate Summary", payload.get("final_gate_summary", {})),
            ("Design Summary", payload.get("design_summary", {})),
            ("Locked Runner Summary", payload.get("locked_runner_summary", {})),
            ("Pre-Execution Checks", payload.get("pre_execution_checks", {})),
            ("Manual Approval Requirements", payload.get("manual_approval_requirements", [])),
            ("Future Execution Constraints", payload.get("future_execution_constraints", [])),
            ("Readback Requirements", payload.get("readback_requirements", [])),
            ("Rollback Requirements", payload.get("rollback_requirements", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Real Write Pre-Execution Validation</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 300px; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify Single-Field Real Write Pre-Execution Validation</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Validation Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local JSON reports and environment variables only.</li>
    <li>No Shopify API call was performed.</li>
    <li>No Shopify mutations were called.</li>
    <li>No translationsRegister call was performed.</li>
    <li>No readback, rollback, command execution, or Shopify write was performed in this phase.</li>
    <li>The dangerous flag is validated as a precondition only and is not effective for writing in this phase.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(validation_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Single-field real write pre-execution validation blocked: " + ", ".join(blocking_conditions)
    return (
        f"Single-field real write pre-execution validation generated with status {validation_status}. "
        "No Shopify API calls, readback, rollback, mutations, or writes performed."
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field real write pre-execution validation report generated.\n"
        f"Validation status: {payload.get('validation_status')}\n"
        f"Requested scope: {payload.get('requested_scope')}\n"
        f"Dangerous flag present: {payload.get('dangerous_flag_validation', {}).get('dangerous_flag_present')}\n"
        f"Dangerous flag effective: {payload.get('dangerous_flag_validation', {}).get('dangerous_flag_effective')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Pre-execution validation JSON:\n"
        f"{json_path}\n\n"
        "Pre-execution validation HTML:\n"
        f"{html_path}\n"
        "Validation only. No Shopify API call, command execution, readback, rollback, mutation, translationsRegister, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep validation files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Write, publish, apply, update, mutation, translationsRegister, command execution, commit, and push are not allowed."
    )


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
