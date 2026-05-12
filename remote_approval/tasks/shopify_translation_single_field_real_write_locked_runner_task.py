import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_real_write_locked_runner"
COMMAND_LABEL = "shopify_translation_single_field_real_write_locked_runner"
SOURCE_PREFLIGHT_PACKAGE_PATH = LOG_DIR / "shopify_translation_single_field_apply_preflight_package.json"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
SOURCE_READBACK_ROLLBACK_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.json"
SOURCE_FINAL_WRITE_GATE_PATH = LOG_DIR / "shopify_translation_single_field_final_write_gate.json"
SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_design.json"
REAL_WRITE_LOCKED_RUNNER_JSON_PATH = LOG_DIR / "shopify_translation_single_field_real_write_locked_runner.json"
REAL_WRITE_LOCKED_RUNNER_HTML_PATH = LOG_DIR / "shopify_translation_single_field_real_write_locked_runner.html"
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
ALLOWED_FIELD = "meta_title"
ALLOWED_LOCALES = {"de", "fr", "es", "it", "ja"}
READY_PLAN_STATUSES = {"ready_for_manual_review", "verified_backup_ready", "ready_for_final_write_gate"}
READY_GATE_STATUSES = {"ready_for_human_final_approval"}
READY_DESIGN_STATUSES = {"design_ready_for_manual_review", "ready_for_runner_design_review"}
SAFE_BACKUP_STATUSES = {"completed", "backup_ready", "ready_for_manual_review"}
MAX_PROPOSED_VALUE_CHARS = 60
FUTURE_REQUIRED_FLAG = "--i-understand-this-writes-shopify"
DANGEROUS_FLAG_ENV = "SHOPIFY_TRANSLATION_I_UNDERSTAND_THIS_WRITES_SHOPIFY"
ENV_PRODUCT_ID = "SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID"
ENV_LOCALE = "SHOPIFY_TRANSLATION_SANDBOX_LOCALE"
ENV_FIELD = "SHOPIFY_TRANSLATION_SANDBOX_FIELD"
ENV_PROPOSED_VALUE = "SHOPIFY_TRANSLATION_SANDBOX_PROPOSED_VALUE"
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/[0-9]+$")


def run_shopify_translation_single_field_real_write_locked_runner_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_errors = []
    preflight = {}
    backup = {}
    plan = {}
    gate = {}
    design = {}

    for label, path, target, missing_code, invalid_code in [
        ("preflight package", SOURCE_PREFLIGHT_PACKAGE_PATH, "preflight", "missing_preflight_package", "preflight_package_json_invalid"),
        ("backup fetch report", SOURCE_BACKUP_FETCH_PATH, "backup", "missing_backup_fetch_report", "backup_fetch_json_invalid"),
        (
            "readback rollback plan",
            SOURCE_READBACK_ROLLBACK_PLAN_PATH,
            "plan",
            "missing_readback_rollback_plan",
            "readback_rollback_plan_json_invalid",
        ),
        ("final gate package", SOURCE_FINAL_WRITE_GATE_PATH, "gate", "missing_final_gate_package", "final_gate_json_invalid"),
        (
            "real write runner design",
            SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH,
            "design",
            "missing_real_write_runner_design",
            "real_write_runner_design_json_invalid",
        ),
    ]:
        try:
            data = _read_json(path)
        except FileNotFoundError as exc:
            parse_errors.append(f"{label} JSON not found: {exc}")
            validation_errors.append(missing_code)
            data = {}
        except (OSError, json.JSONDecodeError) as exc:
            parse_errors.append(f"Could not parse {label} JSON: {exc}")
            validation_errors.append(invalid_code)
            data = {}
        if target == "preflight":
            preflight = data
        elif target == "backup":
            backup = data
        elif target == "plan":
            plan = data
        elif target == "gate":
            gate = data
        elif target == "design":
            design = data

    env_scope = _env_requested_scope()
    validation_errors.extend(_validate_env_scope(env_scope))

    if preflight:
        errors, warnings = _validate_preflight(preflight)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)
    if backup:
        errors, warnings = _validate_backup(backup)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)
    if plan:
        errors, warnings = _validate_plan(plan)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)
    if gate:
        errors, warnings = _validate_gate(gate)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)
    if design:
        errors, warnings = _validate_design(design)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)
    if preflight and backup and plan and gate and design:
        validation_errors.extend(_validate_scope_match(preflight, backup, plan, gate, design, env_scope))

    source_scope = _source_scope(preflight, backup, plan, gate, design)
    source_proposed_value = _source_proposed_value(preflight, plan, gate, design)
    env_proposed_value = str(env_scope.get("proposed_value") or "")
    if source_proposed_value and env_proposed_value and source_proposed_value != env_proposed_value:
        validation_warnings.append("proposed_value_differs_from_source_report")

    requested_scope = {
        "product_id": env_scope.get("product_id") or source_scope.get("product_id", ""),
        "locale": env_scope.get("locale") or source_scope.get("locale", ""),
        "field": env_scope.get("field") or source_scope.get("field", ""),
        "proposed_value": env_proposed_value or source_proposed_value,
    }
    proposed_change = _proposed_change(requested_scope, source_proposed_value)
    verified_backup_summary = _verified_backup_summary(backup)
    final_gate_summary = _final_gate_summary(gate)
    design_summary = _design_summary(design)
    dangerous_flag_present = _dangerous_flag_present()
    blocking_conditions = _blocking_conditions(
        validation_errors,
        proposed_change,
        verified_backup_summary,
        final_gate_summary,
        design_summary,
    )
    locked_runner_status = "ready_but_locked" if not blocking_conditions else _blocked_status(blocking_conditions)
    success = not blocking_conditions
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "locked-real-write-runner-shell-only",
        "command_label": COMMAND_LABEL,
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "source_readback_rollback_plan_path": str(SOURCE_READBACK_ROLLBACK_PLAN_PATH),
        "source_final_write_gate_path": str(SOURCE_FINAL_WRITE_GATE_PATH),
        "source_real_write_runner_design_path": str(SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH),
        "json_real_write_locked_runner_path": str(REAL_WRITE_LOCKED_RUNNER_JSON_PATH),
        "html_real_write_locked_runner_path": str(REAL_WRITE_LOCKED_RUNNER_HTML_PATH),
        "success": success,
        "locked_runner_status": locked_runner_status,
        "locked_shell": True,
        "lock_reason": _lock_reason(blocking_conditions),
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if _valid_product_id(requested_scope.get("product_id", "")) else 0,
            "locale_count": 1 if requested_scope.get("locale") in ALLOWED_LOCALES else 0,
            "field_count": 1 if requested_scope.get("field") == ALLOWED_FIELD else 0,
            "field_allowed": requested_scope.get("field") == ALLOWED_FIELD,
            "scope_matches_all_sources": "scope_mismatch" not in validation_errors,
            "proposed_value_matches_source_reports": (
                not source_proposed_value or requested_scope.get("proposed_value") == source_proposed_value
            ),
            "allowed_field": ALLOWED_FIELD,
            "allowed_locales": sorted(ALLOWED_LOCALES),
        },
        "source_status_summary": {
            "preflight_status": preflight.get("preflight_status", "") if preflight else "",
            "backup_fetch_status": backup.get("backup_fetch_status", "") if backup else "",
            "readback_rollback_plan_status": plan.get("plan_status", "") if plan else "",
            "final_gate_status": gate.get("final_gate_status", "") if gate else "",
            "real_write_runner_design_status": design.get("design_status", "") if design else "",
            "preflight_source_loaded": bool(preflight),
            "backup_source_loaded": bool(backup),
            "readback_rollback_plan_loaded": bool(plan),
            "final_gate_loaded": bool(gate),
            "real_write_runner_design_loaded": bool(design),
            "source_proposed_value": source_proposed_value,
        },
        "proposed_change": proposed_change,
        "verified_backup_summary": verified_backup_summary,
        "final_gate_summary": final_gate_summary,
        "design_summary": design_summary,
        "dangerous_flag_summary": {
            "dangerous_flag_name": FUTURE_REQUIRED_FLAG,
            "dangerous_flag_env": DANGEROUS_FLAG_ENV,
            "dangerous_flag_present": dangerous_flag_present,
            "dangerous_flag_effective": False,
            "dangerous_flag_note": (
                "This locked shell never writes Shopify, even when the dangerous flag is present. "
                "A later separate phase must implement and approve any real write."
            ),
        },
        "future_execution_requirements": _future_execution_requirements(),
        "future_unlock_requirements": _future_unlock_requirements(),
        "blocked_actions": _blocked_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(dangerous_flag_present),
        "future_required_flag": FUTURE_REQUIRED_FLAG,
        "dangerous_flag_effective": False,
        "design_only": False,
        "final_real_write_allowed": False,
        "real_write_allowed": False,
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
        "detected_issue_summary": _issue_summary(locked_runner_status, blocking_conditions, dangerous_flag_present),
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
        "json_real_write_locked_runner_path": str(json_path),
        "html_real_write_locked_runner_path": str(html_path),
        "locked_runner_status": locked_runner_status,
        "locked_shell": True,
        "dangerous_flag_present": dangerous_flag_present,
        "dangerous_flag_effective": False,
        "backup_source_is_verified": verified_backup_summary["backup_source_is_verified"],
        "final_gate_status": final_gate_summary["final_gate_status"],
        "design_status": design_summary["design_status"],
        "final_real_write_allowed": False,
        "real_write_allowed": False,
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


def _dangerous_flag_present() -> bool:
    value = os.environ.get(DANGEROUS_FLAG_ENV, "").strip().lower()
    return value in {"1", "true", "yes", "y"}


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


def _validate_preflight(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    if report.get("task") != EXPECTED_PREFLIGHT_TASK:
        errors.append("unsafe_preflight_package")
    if report.get("mode") != EXPECTED_PREFLIGHT_MODE:
        errors.append("unsafe_preflight_package")
    if report.get("preflight_status") != "ready_for_manual_review":
        errors.append("preflight_not_ready")
    scope = report.get("requested_scope") or {}
    errors.extend(_validate_scope(scope))
    proposed_value = str(scope.get("proposed_value") or "")
    if not proposed_value:
        errors.append("proposed_value_empty")
    elif len(proposed_value) > MAX_PROPOSED_VALUE_CHARS:
        errors.append("proposed_value_over_60_chars")
    errors.extend(_validate_no_write_flags(report))
    if report.get("shopify_api_called") is True or report.get("shopify_api_call_performed") is True:
        errors.append("source_report_indicates_shopify_api_call")
    if report.get("would_call_shopify_mutation"):
        warnings.append("preflight references future translationsRegister text only; no mutation was performed")
    return _unique(errors), _unique(warnings)


def _validate_backup(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    if report.get("task") != EXPECTED_BACKUP_TASK:
        errors.append("unsafe_backup_fetch_report")
    if report.get("mode") != EXPECTED_BACKUP_MODE:
        errors.append("unsafe_backup_fetch_report")
    if report.get("backup_fetch_status") not in SAFE_BACKUP_STATUSES:
        errors.append("unsafe_backup_fetch_status")
    scope = {
        "product_id": report.get("backup_product_id") or (report.get("requested_scope") or {}).get("product_id", ""),
        "locale": report.get("backup_locale") or (report.get("requested_scope") or {}).get("locale", ""),
        "field": report.get("backup_field") or (report.get("requested_scope") or {}).get("field", ""),
    }
    errors.extend(_validate_scope(scope))
    errors.extend(_validate_no_write_flags(report))
    if report.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")
    if report.get("mutation_performed") is True:
        errors.append("source_report_indicates_mutation")
    if report.get("shopify_mutations_called") not in ([], None):
        errors.append("source_report_indicates_mutation")
    return _unique(errors), _unique(warnings)


def _validate_plan(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    if report.get("task") != EXPECTED_PLAN_TASK:
        errors.append("unsafe_readback_rollback_plan")
    if report.get("mode") != EXPECTED_PLAN_MODE:
        errors.append("unsafe_readback_rollback_plan")
    plan_status = report.get("plan_status")
    if plan_status not in READY_PLAN_STATUSES:
        errors.append("readback_rollback_plan_not_ready")
    if plan_status in {"ready_for_real_write", "write_allowed", "execution_allowed"}:
        errors.append("unsafe_readback_rollback_plan_status")
    errors.extend(_validate_scope(report.get("proposed_change") or report.get("requested_scope") or {}))
    backup_completeness = report.get("backup_completeness") or {}
    if backup_completeness.get("backup_source_is_verified") is not True:
        errors.append("backup_not_verified")
    if backup_completeness.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")
    errors.extend(_validate_no_write_flags(report))
    for field in ["shopify_api_call_performed", "readback_performed", "rollback_performed"]:
        if report.get(field) is True:
            errors.append("source_report_indicates_shopify_write")
    return _unique(errors), _unique(warnings)


def _validate_gate(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    if report.get("task") != EXPECTED_GATE_TASK:
        errors.append("unsafe_final_gate_package")
    if report.get("mode") != EXPECTED_GATE_MODE:
        errors.append("unsafe_final_gate_package")
    if report.get("final_gate_status") not in READY_GATE_STATUSES:
        errors.append("final_gate_not_ready")
    errors.extend(_validate_scope(report.get("proposed_change") or report.get("requested_scope") or {}))
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
    return _unique(errors), _unique(warnings)


def _validate_design(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    if report.get("task") != EXPECTED_DESIGN_TASK:
        errors.append("unsafe_real_write_runner_design")
    if report.get("mode") != EXPECTED_DESIGN_MODE:
        errors.append("unsafe_real_write_runner_design")
    if report.get("design_status") not in READY_DESIGN_STATUSES:
        errors.append("design_package_not_ready")
    if report.get("design_only") is not True:
        errors.append("unsafe_real_write_runner_design")
    if report.get("final_real_write_allowed") is not False:
        errors.append("source_report_indicates_real_write_allowed")
    errors.extend(_validate_scope(report.get("proposed_change") or report.get("requested_scope") or {}))
    backup_summary = report.get("verified_backup_summary") or {}
    if backup_summary.get("backup_source_is_verified") is not True:
        errors.append("backup_not_verified")
    final_gate = report.get("final_gate_summary") or {}
    if final_gate.get("final_gate_status") not in READY_GATE_STATUSES:
        errors.append("final_gate_not_ready")
    runner_design = report.get("future_runner_design") or {}
    if runner_design.get("this_phase_generates_executable_command") is True:
        errors.append("source_report_indicates_executable_command")
    errors.extend(_validate_no_write_flags(report))
    for field in ["shopify_api_call_performed", "readback_performed", "rollback_performed"]:
        if report.get(field) is True:
            errors.append("source_report_indicates_shopify_write")
    return _unique(errors), _unique(warnings)


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


def _validate_scope_match(
    preflight: dict,
    backup: dict,
    plan: dict,
    gate: dict,
    design: dict,
    env_scope: dict,
) -> list[str]:
    errors = []
    scopes = [
        preflight.get("requested_scope") or {},
        {
            "product_id": backup.get("backup_product_id") or (backup.get("requested_scope") or {}).get("product_id", ""),
            "locale": backup.get("backup_locale") or (backup.get("requested_scope") or {}).get("locale", ""),
            "field": backup.get("backup_field") or (backup.get("requested_scope") or {}).get("field", ""),
        },
        plan.get("proposed_change") or plan.get("requested_scope") or {},
        gate.get("proposed_change") or gate.get("requested_scope") or {},
        design.get("proposed_change") or design.get("requested_scope") or {},
        env_scope,
    ]
    first = scopes[0]
    for scope in scopes[1:]:
        for key in ["product_id", "locale", "field"]:
            if first.get(key) != scope.get(key):
                errors.append("scope_mismatch")
    return _unique(errors)


def _source_scope(preflight: dict, backup: dict, plan: dict, gate: dict, design: dict) -> dict:
    preflight_scope = preflight.get("requested_scope") or {}
    backup_scope = backup.get("requested_scope") or {}
    plan_scope = plan.get("proposed_change") or plan.get("requested_scope") or {}
    gate_scope = gate.get("proposed_change") or gate.get("requested_scope") or {}
    design_scope = design.get("proposed_change") or design.get("requested_scope") or {}
    return {
        "product_id": preflight_scope.get("product_id")
        or backup.get("backup_product_id")
        or backup_scope.get("product_id")
        or plan_scope.get("product_id")
        or gate_scope.get("product_id")
        or design_scope.get("product_id", ""),
        "locale": preflight_scope.get("locale")
        or backup.get("backup_locale")
        or backup_scope.get("locale")
        or plan_scope.get("locale")
        or gate_scope.get("locale")
        or design_scope.get("locale", ""),
        "field": preflight_scope.get("field")
        or backup.get("backup_field")
        or backup_scope.get("field")
        or plan_scope.get("field")
        or gate_scope.get("field")
        or design_scope.get("field", ""),
    }


def _source_proposed_value(preflight: dict, plan: dict, gate: dict, design: dict) -> str:
    for scope in [
        preflight.get("requested_scope") or {},
        plan.get("proposed_change") or plan.get("requested_scope") or {},
        gate.get("proposed_change") or gate.get("requested_scope") or {},
        design.get("proposed_change") or design.get("requested_scope") or {},
    ]:
        value = str(scope.get("proposed_value") or "")
        if value:
            return value
    return ""


def _proposed_change(scope: dict, source_proposed_value: str) -> dict:
    value = str(scope.get("proposed_value") or "")
    return {
        "product_id": scope.get("product_id", ""),
        "locale": scope.get("locale", ""),
        "field": scope.get("field", ""),
        "proposed_value": value,
        "proposed_value_chars": len(value),
        "proposed_value_length_allowed": 0 < len(value) <= MAX_PROPOSED_VALUE_CHARS,
        "source_report_proposed_value": source_proposed_value,
        "proposed_value_matches_source_reports": (not source_proposed_value or value == source_proposed_value),
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
        "blocking_conditions": gate.get("blocking_conditions", []) if gate else [],
        "future_required_flag": gate.get("future_required_flag", "") if gate else "",
    }


def _design_summary(design: dict) -> dict:
    return {
        "design_status": design.get("design_status", "") if design else "",
        "design_only": bool(design.get("design_only")) if design else False,
        "final_real_write_allowed": bool(design.get("final_real_write_allowed")) if design else False,
        "real_write_allowed": bool(design.get("real_write_allowed")) if design else False,
        "future_required_flag": design.get("future_required_flag", "") if design else "",
        "future_required_dangerous_flag": design.get("future_required_dangerous_flag", {}) if design else {},
    }


def _blocking_conditions(
    validation_errors: list[str],
    proposed_change: dict,
    backup_summary: dict,
    final_gate_summary: dict,
    design_summary: dict,
) -> list[str]:
    conditions = []
    mapping = {
        "missing_preflight_package": "missing_preflight_package",
        "missing_backup_fetch_report": "missing_backup_fetch_report",
        "missing_readback_rollback_plan": "missing_readback_rollback_plan",
        "missing_final_gate_package": "missing_final_gate_package",
        "missing_real_write_runner_design": "missing_real_write_runner_design",
        "scope_mismatch": "scope_mismatch",
        "invalid_product_id": "invalid_product_id",
        "invalid_sandbox_locale": "invalid_sandbox_locale",
        "invalid_sandbox_field": "invalid_sandbox_field",
        "proposed_value_empty": "proposed_value_empty",
        "proposed_value_over_60_chars": "proposed_value_over_60_chars",
        "backup_not_verified": "backup_not_verified",
        "read_only_backup_query_not_performed": "read_only_backup_query_not_performed",
        "final_gate_not_ready": "final_gate_not_ready",
        "design_package_not_ready": "design_package_not_ready",
        "source_report_indicates_real_write_allowed": "source_report_indicates_real_write_allowed",
        "source_report_indicates_executable_command": "source_report_indicates_executable_command",
        "missing_sandbox_product_id": "missing_sandbox_product_id",
        "missing_sandbox_locale": "missing_sandbox_locale",
        "missing_sandbox_field": "missing_sandbox_field",
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
    if final_gate_summary["final_real_write_allowed"] is not False:
        conditions.append("source_report_indicates_real_write_allowed")
    if design_summary["design_status"] not in READY_DESIGN_STATUSES:
        conditions.append("design_package_not_ready")
    if design_summary["design_only"] is not True:
        conditions.append("design_package_not_ready")
    if design_summary["real_write_allowed"] is not False or design_summary["final_real_write_allowed"] is not False:
        conditions.append("source_report_indicates_real_write_allowed")
    return _unique(conditions)


def _blocked_status(blocking_conditions: list[str]) -> str:
    if "scope_mismatch" in blocking_conditions:
        return "blocked_scope_mismatch"
    if "invalid_sandbox_field" in blocking_conditions:
        return "blocked_invalid_sandbox_field"
    if "backup_not_verified" in blocking_conditions:
        return "blocked_backup_not_verified"
    if "final_gate_not_ready" in blocking_conditions:
        return "blocked_final_gate_not_ready"
    if "design_package_not_ready" in blocking_conditions:
        return "blocked_design_package_not_ready"
    return "blocked"


def _lock_reason(blocking_conditions: list[str]) -> list[str]:
    if blocking_conditions:
        return [
            "The locked runner shell is blocked because one or more safety preconditions failed.",
            "No Shopify API call, mutation, translationsRegister call, readback, rollback, command, or write was executed.",
            "Blocking conditions: " + ", ".join(blocking_conditions),
        ]
    return [
        "Current phase is a locked shell only.",
        "Even if the dangerous flag is present, this phase will not write Shopify.",
        "Real Shopify write must enter a later separate phase.",
        "The later real-write phase must require another explicit human confirmation.",
        "The later real-write phase must separately implement readback and rollback safety.",
    ]


def _future_execution_requirements() -> list[str]:
    return [
        "Re-read the final gate package.",
        "Re-verify the verified backup.",
        "Re-verify product_id, locale, field, and proposed_value.",
        f"Require the dangerous flag: {FUTURE_REQUIRED_FLAG}.",
        "Read back the same product x locale x meta_title immediately after any future write.",
        "Do not mark success if readback fails or differs from proposed_value.",
        "Require separate approval for rollback.",
        "Reject batch mode.",
        "Reject multiple products.",
        "Reject multiple locales.",
        "Reject multiple fields.",
        "Reject whole-store scans.",
    ]


def _future_unlock_requirements() -> list[str]:
    return [
        "Create a new independent Phase 11.9 or Phase 12 before considering unlock.",
        "Obtain explicit human approval for a real Shopify write.",
        "Reconfirm product_id, locale, field, proposed_value, and backup_value.",
        "Confirm the final gate is still ready.",
        "Confirm the verified backup is still available.",
        "Confirm the readback plan is explicit.",
        "Confirm the rollback approval plan is explicit.",
        f"Require the dangerous flag: {FUTURE_REQUIRED_FLAG}.",
        "This phase cannot automatically unlock real execution.",
    ]


def _blocked_actions() -> list[str]:
    return [
        "Shopify API call",
        "Shopify write",
        "Shopify mutation",
        "translationsRegister",
        "publish/apply/update",
        "readback execution",
        "rollback execution",
        "command execution",
        "batch execution",
        "full-store scan",
        "git push",
    ]


def _safety_summary(dangerous_flag_present: bool) -> dict:
    return {
        "locked_shell": True,
        "dangerous_flag_present": dangerous_flag_present,
        "dangerous_flag_effective": False,
        "local_json_package_only": True,
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
    REAL_WRITE_LOCKED_RUNNER_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(REAL_WRITE_LOCKED_RUNNER_JSON_PATH.read_text(encoding="utf-8"))
    return REAL_WRITE_LOCKED_RUNNER_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REAL_WRITE_LOCKED_RUNNER_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REAL_WRITE_LOCKED_RUNNER_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Locked Runner Status", "locked_runner_status"),
            ("Locked Shell", "locked_shell"),
            ("Dangerous Flag Present", "dangerous_flag_summary"),
            ("Future Required Flag", "future_required_flag"),
            ("Final Real Write Allowed", "final_real_write_allowed"),
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
            ("Source Status Summary", payload.get("source_status_summary", {})),
            ("Proposed Change", payload.get("proposed_change", {})),
            ("Verified Backup Summary", payload.get("verified_backup_summary", {})),
            ("Final Gate Summary", payload.get("final_gate_summary", {})),
            ("Design Summary", payload.get("design_summary", {})),
            ("Dangerous Flag Summary", payload.get("dangerous_flag_summary", {})),
            ("Lock Reason", payload.get("lock_reason", [])),
            ("Future Execution Requirements", payload.get("future_execution_requirements", [])),
            ("Future Unlock Requirements", payload.get("future_unlock_requirements", [])),
            ("Blocked Actions", payload.get("blocked_actions", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Real Write Locked Runner</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 280px; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify Single-Field Real Write Locked Runner</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Locked Runner Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local JSON reports and environment variables only.</li>
    <li>No Shopify API call was performed.</li>
    <li>No Shopify mutations were called.</li>
    <li>No translationsRegister call was performed.</li>
    <li>No readback, rollback, command execution, or Shopify write was performed in this phase.</li>
    <li>The dangerous flag is ineffective in this phase and cannot unlock writes.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(locked_runner_status: str, blocking_conditions: list[str], dangerous_flag_present: bool) -> str:
    if blocking_conditions:
        return "Single-field real write locked runner blocked: " + ", ".join(blocking_conditions)
    flag_text = "present but ineffective" if dangerous_flag_present else "not present"
    return (
        f"Single-field real write locked runner generated with status {locked_runner_status}. "
        f"Dangerous flag is {flag_text}. No Shopify API calls, readback, rollback, mutations, or writes performed."
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field real write locked runner report generated.\n"
        f"Locked runner status: {payload.get('locked_runner_status')}\n"
        f"Requested scope: {payload.get('requested_scope')}\n"
        f"Dangerous flag present: {payload.get('dangerous_flag_summary', {}).get('dangerous_flag_present')}\n"
        f"Dangerous flag effective: {payload.get('dangerous_flag_summary', {}).get('dangerous_flag_effective')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Locked runner JSON:\n"
        f"{json_path}\n\n"
        "Locked runner HTML:\n"
        f"{html_path}\n"
        "Locked shell only. No Shopify API call, command execution, readback, rollback, mutation, translationsRegister, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep locked runner files\n"
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
