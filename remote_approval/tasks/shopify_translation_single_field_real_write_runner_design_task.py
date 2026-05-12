import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_real_write_runner_design"
COMMAND_LABEL = "shopify_translation_single_field_real_write_runner_design"
SOURCE_PREFLIGHT_PACKAGE_PATH = LOG_DIR / "shopify_translation_single_field_apply_preflight_package.json"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
SOURCE_READBACK_ROLLBACK_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.json"
SOURCE_FINAL_WRITE_GATE_PATH = LOG_DIR / "shopify_translation_single_field_final_write_gate.json"
REAL_WRITE_RUNNER_DESIGN_JSON_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_design.json"
REAL_WRITE_RUNNER_DESIGN_HTML_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_design.html"
EXPECTED_PREFLIGHT_TASK = "shopify_translation_single_field_apply_preflight_package"
EXPECTED_PREFLIGHT_MODE = "single-field-preflight-only"
EXPECTED_BACKUP_TASK = "shopify_translation_single_field_backup_fetch"
EXPECTED_BACKUP_MODE = "read-only-backup-fetch"
EXPECTED_PLAN_TASK = "shopify_translation_single_field_readback_rollback_plan"
EXPECTED_PLAN_MODE = "readback-rollback-plan-only"
EXPECTED_GATE_TASK = "shopify_translation_single_field_final_write_gate"
EXPECTED_GATE_MODE = "final-write-gate-package-only"
ALLOWED_FIELD = "meta_title"
ALLOWED_LOCALES = {"de", "fr", "es", "it", "ja"}
READY_PLAN_STATUSES = {"ready_for_manual_review", "verified_backup_ready", "ready_for_final_write_gate"}
READY_GATE_STATUSES = {"ready_for_human_final_approval", "ready_for_final_write_gate_review"}
SAFE_BACKUP_STATUSES = {"completed", "backup_ready", "ready_for_manual_review"}
MAX_PROPOSED_VALUE_CHARS = 60
FUTURE_REQUIRED_FLAG = "--i-understand-this-writes-shopify"
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/[0-9]+$")


def run_shopify_translation_single_field_real_write_runner_design_task(mode: str) -> dict:
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
    if preflight and backup and plan and gate:
        validation_errors.extend(_validate_scope_match(preflight, backup, plan, gate))

    requested_scope = _requested_scope(preflight, backup, plan, gate)
    proposed_change = _proposed_change(preflight, requested_scope)
    verified_backup_summary = _verified_backup_summary(backup)
    final_gate_summary = _final_gate_summary(gate)
    blocking_conditions = _blocking_conditions(
        validation_errors,
        proposed_change,
        verified_backup_summary,
        final_gate_summary,
    )
    design_status = "design_ready_for_manual_review" if not blocking_conditions else _blocked_status(blocking_conditions)
    success = not blocking_conditions
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "real-write-runner-design-only",
        "command_label": COMMAND_LABEL,
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "source_readback_rollback_plan_path": str(SOURCE_READBACK_ROLLBACK_PLAN_PATH),
        "source_final_write_gate_path": str(SOURCE_FINAL_WRITE_GATE_PATH),
        "json_real_write_runner_design_path": str(REAL_WRITE_RUNNER_DESIGN_JSON_PATH),
        "html_real_write_runner_design_path": str(REAL_WRITE_RUNNER_DESIGN_HTML_PATH),
        "success": success,
        "design_status": design_status,
        "design_only": True,
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if _valid_product_id(requested_scope.get("product_id", "")) else 0,
            "locale_count": 1 if requested_scope.get("locale") in ALLOWED_LOCALES else 0,
            "field_count": 1 if requested_scope.get("field") == ALLOWED_FIELD else 0,
            "field_allowed": requested_scope.get("field") == ALLOWED_FIELD,
            "scope_matches_all_sources": "scope_mismatch" not in validation_errors,
            "allowed_field": ALLOWED_FIELD,
            "allowed_locales": sorted(ALLOWED_LOCALES),
        },
        "source_status_summary": {
            "preflight_status": preflight.get("preflight_status", "") if preflight else "",
            "backup_fetch_status": backup.get("backup_fetch_status", "") if backup else "",
            "readback_rollback_plan_status": plan.get("plan_status", "") if plan else "",
            "final_gate_status": gate.get("final_gate_status", "") if gate else "",
            "preflight_source_loaded": bool(preflight),
            "backup_source_loaded": bool(backup),
            "readback_rollback_plan_loaded": bool(plan),
            "final_gate_loaded": bool(gate),
        },
        "proposed_change": proposed_change,
        "verified_backup_summary": verified_backup_summary,
        "final_gate_summary": final_gate_summary,
        "future_runner_design": _future_runner_design(),
        "future_execution_sequence": _future_execution_sequence(),
        "future_required_arguments": _future_required_arguments(),
        "future_required_dangerous_flag": {
            "flag": FUTURE_REQUIRED_FLAG,
            "this_phase_accepts_flag_for_write": False,
            "this_phase_writes_if_flag_present": False,
            "future_write_phase_uses_flag_as_necessary_but_not_sufficient_condition": True,
        },
        "future_readback_requirements": _future_readback_requirements(),
        "future_rollback_requirements": _future_rollback_requirements(),
        "future_failure_handling": _future_failure_handling(),
        "forbidden_actions": _forbidden_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(),
        "future_required_flag": FUTURE_REQUIRED_FLAG,
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
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "validation_warnings": _unique(validation_warnings),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(design_status, blocking_conditions),
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
        "json_real_write_runner_design_path": str(json_path),
        "html_real_write_runner_design_path": str(html_path),
        "design_status": design_status,
        "design_only": True,
        "backup_source_is_verified": verified_backup_summary["backup_source_is_verified"],
        "final_gate_status": final_gate_summary["final_gate_status"],
        "future_required_dangerous_flag": FUTURE_REQUIRED_FLAG,
        "final_real_write_allowed": False,
        "real_write_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "all_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "validation_warnings_count": len(payload["validation_warnings"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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
    errors.extend(_validate_no_write_flags(report, "preflight"))
    if report.get("shopify_api_called") is True:
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
    errors.extend(_validate_no_write_flags(report, "backup"))
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
    if report.get("plan_status") not in READY_PLAN_STATUSES:
        errors.append("readback_rollback_plan_not_ready")
    if report.get("plan_status") in {"ready_for_real_write", "write_allowed", "execution_allowed"}:
        errors.append("unsafe_readback_rollback_plan_status")
    errors.extend(_validate_scope(report.get("proposed_change") or {}))
    backup_completeness = report.get("backup_completeness") or {}
    if backup_completeness.get("backup_source_is_verified") is not True:
        errors.append("backup_not_verified")
    if backup_completeness.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")
    errors.extend(_validate_no_write_flags(report, "readback_rollback_plan"))
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
    if report.get("final_gate_status") in {"ready_for_real_write", "write_allowed", "execution_allowed", "real_write_allowed"}:
        errors.append("unsafe_final_gate_status")
    if report.get("final_real_write_allowed") is not False:
        errors.append("source_report_indicates_real_write_allowed")
    errors.extend(_validate_scope(report.get("proposed_change") or report.get("requested_scope") or {}))
    backup_summary = report.get("verified_backup_summary") or {}
    if backup_summary.get("backup_source_is_verified") is not True:
        errors.append("backup_not_verified")
    if backup_summary.get("read_only_shopify_query_performed") is not True:
        errors.append("read_only_backup_query_not_performed")
    errors.extend(_validate_no_write_flags(report, "final_gate"))
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


def _validate_no_write_flags(report: dict, source_name: str) -> list[str]:
    errors = []
    unsafe_true_fields = [
        "shopify_write_performed",
        "apply_performed",
        "publish_performed",
        "translations_register_performed",
        "translations_register_called",
        "command_executed",
        "mutation_performed",
    ]
    for field in unsafe_true_fields:
        if report.get(field) is True:
            if field in {"translations_register_performed", "translations_register_called"}:
                errors.append("source_report_indicates_translations_register")
            elif field == "mutation_performed":
                errors.append("source_report_indicates_mutation")
            else:
                errors.append("source_report_indicates_shopify_write")
    if report.get("real_write_allowed") is True:
        errors.append("source_report_indicates_real_write_allowed")
    if report.get("translations_register_allowed") is True:
        errors.append("source_report_indicates_translations_register")
    if report.get("no_shopify_writes_performed") is not True:
        errors.append("no_write_not_confirmed")
    if report.get("all_no_write_confirmed") is not True:
        errors.append("no_write_not_confirmed")
    return _unique(errors)


def _validate_scope_match(preflight: dict, backup: dict, plan: dict, gate: dict) -> list[str]:
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
    ]
    first = scopes[0]
    for scope in scopes[1:]:
        for key in ["product_id", "locale", "field"]:
            if first.get(key) != scope.get(key):
                errors.append("scope_mismatch")
    return _unique(errors)


def _requested_scope(preflight: dict, backup: dict, plan: dict, gate: dict) -> dict:
    preflight_scope = preflight.get("requested_scope") or {}
    backup_scope = backup.get("requested_scope") or {}
    plan_scope = plan.get("proposed_change") or plan.get("requested_scope") or {}
    gate_scope = gate.get("proposed_change") or gate.get("requested_scope") or {}
    return {
        "product_id": preflight_scope.get("product_id")
        or backup.get("backup_product_id")
        or backup_scope.get("product_id")
        or plan_scope.get("product_id")
        or gate_scope.get("product_id", ""),
        "locale": preflight_scope.get("locale")
        or backup.get("backup_locale")
        or backup_scope.get("locale")
        or plan_scope.get("locale")
        or gate_scope.get("locale", ""),
        "field": preflight_scope.get("field")
        or backup.get("backup_field")
        or backup_scope.get("field")
        or plan_scope.get("field")
        or gate_scope.get("field", ""),
    }


def _proposed_change(preflight: dict, scope: dict) -> dict:
    value = str((preflight.get("requested_scope") or {}).get("proposed_value") or "")
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
        "blocking_conditions": gate.get("blocking_conditions", []) if gate else [],
        "future_required_flag": gate.get("future_required_flag", "") if gate else "",
    }


def _future_runner_design() -> dict:
    return {
        "scope": "1 product x 1 locale x 1 field=meta_title",
        "batch_mode_allowed": False,
        "multiple_products_allowed": False,
        "multiple_locales_allowed": False,
        "multiple_fields_allowed": False,
        "non_meta_title_field_allowed": False,
        "requires_verified_backup": True,
        "requires_final_gate_ready": True,
        "requires_manual_dangerous_flag": True,
        "must_readback_immediately_after_write": True,
        "readback_failure_can_succeed_silently": False,
        "rollback_auto_execution_allowed": False,
        "rollback_requires_separate_approval": True,
        "this_phase_executes_runner": False,
        "this_phase_generates_executable_command": False,
    }


def _future_execution_sequence() -> list[str]:
    return [
        "Read the final gate package.",
        "Verify scope consistency.",
        "Verify backup_source_is_verified=true.",
        "Verify field=meta_title.",
        "Verify proposed_value is no longer than 60 characters.",
        f"Verify the manual dangerous flag is present: {FUTURE_REQUIRED_FLAG}.",
        "Perform exactly one Shopify translationsRegister write.",
        "Immediately read back the same product x locale x field.",
        "Compare the readback value exactly to proposed_value.",
        "If successful, generate a success report.",
        "If failed, generate a failure report and enter rollback approval flow.",
        "Rollback may only use verified backup_value and requires separate human approval.",
    ]


def _future_required_arguments() -> list[str]:
    return [
        "--product-id",
        "--locale",
        "--field meta_title",
        "--proposed-value",
        "--final-gate-file",
        "--backup-file",
        "--readback-rollback-plan-file",
        FUTURE_REQUIRED_FLAG,
    ]


def _future_readback_requirements() -> dict:
    return {
        "must_readback_same_product_id": True,
        "must_readback_same_locale": True,
        "must_readback_field": ALLOWED_FIELD,
        "scope_expansion_allowed": False,
        "whole_store_scan_allowed": False,
        "readback_value_must_equal_proposed_value": True,
        "readback_result_must_be_written_to_local_report": True,
        "readback_failure_must_block_success_status": True,
    }


def _future_rollback_requirements() -> dict:
    return {
        "automatic_rollback_allowed": False,
        "rollback_requires_separate_approval": True,
        "rollback_value_source": "verified backup_value only",
        "rollback_scope": "same product_id x locale x meta_title",
        "rollback_forbidden_without_verified_backup": True,
        "rollback_requires_post_rollback_readback": True,
    }


def _future_failure_handling() -> dict:
    return {
        "write_failure_status": "write_failed",
        "readback_mismatch_status": "write_verification_failed",
        "success_requires_exact_readback_match": True,
        "rollback_flow_status": "rollback_approval_required",
        "silent_success_on_failure_allowed": False,
    }


def _forbidden_actions() -> list[str]:
    return [
        "Shopify write in this phase",
        "Shopify API call in this phase",
        "mutation in this phase",
        "translationsRegister in this phase",
        "publish/apply/update in this phase",
        "automatic rollback",
        "automatic readback",
        "batch mode",
        "whole-store scan",
        "multiple products",
        "multiple locales",
        "multiple fields",
        "git push",
    ]


def _blocking_conditions(
    validation_errors: list[str],
    proposed_change: dict,
    backup_summary: dict,
    final_gate_summary: dict,
) -> list[str]:
    conditions = []
    mapping = {
        "missing_preflight_package": "missing_preflight_package",
        "missing_backup_fetch_report": "missing_backup_fetch_report",
        "missing_readback_rollback_plan": "missing_readback_rollback_plan",
        "missing_final_gate_package": "missing_final_gate_package",
        "scope_mismatch": "scope_mismatch",
        "invalid_product_id": "invalid_product_id",
        "invalid_sandbox_field": "invalid_field",
        "proposed_value_empty": "proposed_value_empty",
        "proposed_value_over_60_chars": "proposed_value_over_60_chars",
        "backup_not_verified": "backup_not_verified",
        "read_only_backup_query_not_performed": "read-only backup query not performed",
        "final_gate_not_ready": "final_gate_not_ready",
        "source_report_indicates_real_write_allowed": "source report indicates real write allowed",
    }
    for error in validation_errors:
        if error in mapping:
            conditions.append(mapping[error])
        if error == "source_report_indicates_shopify_write":
            conditions.append("source report indicates Shopify write")
        if error == "source_report_indicates_mutation":
            conditions.append("source report indicates mutation")
        if error == "source_report_indicates_translations_register":
            conditions.append("source report indicates translationsRegister")
        if error == "source_report_indicates_shopify_api_call":
            conditions.append("source report indicates Shopify API call")
    if not proposed_change["proposed_value"]:
        conditions.append("proposed_value_empty")
    if proposed_change["proposed_value_chars"] > MAX_PROPOSED_VALUE_CHARS:
        conditions.append("proposed_value_over_60_chars")
    if not backup_summary["backup_source_is_verified"]:
        conditions.append("backup_not_verified")
    if not backup_summary["read_only_shopify_query_performed"]:
        conditions.append("read-only backup query not performed")
    if final_gate_summary["final_gate_status"] not in READY_GATE_STATUSES:
        conditions.append("final_gate_not_ready")
    if final_gate_summary["final_real_write_allowed"] is not False:
        conditions.append("source report indicates real write allowed")
    return _unique(conditions)


def _blocked_status(blocking_conditions: list[str]) -> str:
    if "final_gate_not_ready" in blocking_conditions:
        return "blocked_final_gate_not_ready"
    if "backup_not_verified" in blocking_conditions:
        return "blocked_backup_not_verified"
    if "scope_mismatch" in blocking_conditions:
        return "blocked_scope_mismatch"
    if "invalid_field" in blocking_conditions:
        return "blocked_invalid_field"
    return "blocked"


def _safety_summary() -> dict:
    return {
        "design_only": True,
        "generates_executable_command": False,
        "shopify_api_call_allowed": False,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
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
    REAL_WRITE_RUNNER_DESIGN_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(REAL_WRITE_RUNNER_DESIGN_JSON_PATH.read_text(encoding="utf-8"))
    return REAL_WRITE_RUNNER_DESIGN_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REAL_WRITE_RUNNER_DESIGN_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REAL_WRITE_RUNNER_DESIGN_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Design Status", "design_status"),
            ("Design Only", "design_only"),
            ("Future Required Flag", "future_required_flag"),
            ("Final Real Write Allowed", "final_real_write_allowed"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("Translations Register Called", "translations_register_called"),
            ("Readback Performed", "readback_performed"),
            ("Rollback Performed", "rollback_performed"),
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
            ("Future Runner Design", payload.get("future_runner_design", {})),
            ("Future Execution Sequence", payload.get("future_execution_sequence", [])),
            ("Future Required Arguments", payload.get("future_required_arguments", [])),
            ("Future Readback Requirements", payload.get("future_readback_requirements", {})),
            ("Future Rollback Requirements", payload.get("future_rollback_requirements", {})),
            ("Future Failure Handling", payload.get("future_failure_handling", {})),
            ("Forbidden Actions", payload.get("forbidden_actions", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Real Write Runner Design</title>
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
  <h1>Shopify Single-Field Real Write Runner Design</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Design Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local JSON reports only.</li>
    <li>No executable Shopify write command is generated.</li>
    <li>No Shopify API call was performed.</li>
    <li>No Shopify mutations were called.</li>
    <li>No translationsRegister call was performed.</li>
    <li>No readback, rollback, or Shopify write was performed in this phase.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(design_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Single-field real write runner design blocked: " + ", ".join(blocking_conditions)
    return (
        f"Single-field real write runner design generated with status {design_status}. "
        "No Shopify API calls, executable commands, or writes performed."
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field real write runner design package generated.\n"
        f"Design status: {payload.get('design_status')}\n"
        f"Requested scope: {payload.get('requested_scope')}\n"
        f"Backup verified: {payload.get('verified_backup_summary', {}).get('backup_source_is_verified')}\n"
        f"Final gate status: {payload.get('final_gate_summary', {}).get('final_gate_status')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Runner design JSON:\n"
        f"{json_path}\n\n"
        "Runner design HTML:\n"
        f"{html_path}\n"
        "Design only. No Shopify API call, executable command, readback, rollback, mutation, translationsRegister, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep runner design files\n"
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
