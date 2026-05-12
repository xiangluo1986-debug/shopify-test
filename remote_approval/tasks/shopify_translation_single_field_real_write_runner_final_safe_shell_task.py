import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.tasks import shopify_translation_single_field_final_human_approval_package_task as base
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_real_write_runner_final_safe_shell"
COMMAND_LABEL = "shopify_translation_single_field_real_write_runner_final_safe_shell"
SOURCE_PREFLIGHT_PACKAGE_PATH = LOG_DIR / "shopify_translation_single_field_apply_preflight_package.json"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
SOURCE_READBACK_ROLLBACK_PLAN_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.json"
SOURCE_FINAL_WRITE_GATE_PATH = LOG_DIR / "shopify_translation_single_field_final_write_gate.json"
SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_design.json"
SOURCE_REAL_WRITE_LOCKED_RUNNER_PATH = LOG_DIR / "shopify_translation_single_field_real_write_locked_runner.json"
SOURCE_PRE_EXECUTION_VALIDATE_PATH = LOG_DIR / "shopify_translation_single_field_real_write_pre_execution_validate.json"
SOURCE_FINAL_HUMAN_APPROVAL_PATH = LOG_DIR / "shopify_translation_single_field_final_human_approval_package.json"
FINAL_SAFE_SHELL_JSON_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_final_safe_shell.json"
FINAL_SAFE_SHELL_HTML_PATH = LOG_DIR / "shopify_translation_single_field_real_write_runner_final_safe_shell.html"

EXPECTED_FINAL_HUMAN_APPROVAL_TASK = "shopify_translation_single_field_final_human_approval_package"
EXPECTED_FINAL_HUMAN_APPROVAL_MODE = "final-human-approval-package-only"
READY_FINAL_HUMAN_APPROVAL_STATUSES = {
    "ready_for_final_human_review",
    "ready_for_phase_12_manual_approval_review",
}
ACK_ENV = "SHOPIFY_TRANSLATION_PHASE_12_FINAL_SAFE_SHELL_ACK"


def run_shopify_translation_single_field_real_write_runner_final_safe_shell_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

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
    ]:
        try:
            reports[key] = base._read_json(path)
        except FileNotFoundError as exc:
            parse_errors.append(f"{label} JSON not found: {exc}")
            validation_errors.append(missing_code)
            reports[key] = {}
        except (OSError, json.JSONDecodeError) as exc:
            parse_errors.append(f"Could not parse {label} JSON: {exc}")
            validation_errors.append(invalid_code)
            reports[key] = {}

    env_scope = base._env_requested_scope()
    dangerous_flag_value = os.environ.get(base.DANGEROUS_FLAG_ENV, "").strip()
    dangerous_flag_present = bool(dangerous_flag_value)
    dangerous_flag_valid = dangerous_flag_value.lower() == "true"
    ack_value = os.environ.get(ACK_ENV, "").strip()
    ack_present = bool(ack_value)

    validation_errors.extend(base._validate_env_scope(env_scope))
    if not dangerous_flag_present:
        validation_errors.append("missing_dangerous_flag")
    elif not dangerous_flag_valid:
        validation_errors.append("invalid_dangerous_flag_value")

    validators = [
        ("preflight", base._validate_preflight),
        ("backup", base._validate_backup),
        ("plan", base._validate_plan),
        ("gate", base._validate_gate),
        ("design", base._validate_design),
        ("locked", base._validate_locked),
        ("pre_execution", base._validate_pre_execution),
        ("final_human", _validate_final_human_approval),
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
    proposed_change = base._proposed_change(requested_scope)
    verified_backup_summary = base._verified_backup_summary(reports["backup"])
    final_gate_summary = base._final_gate_summary(reports["gate"])
    design_summary = base._design_summary(reports["design"])
    locked_runner_summary = base._locked_runner_summary(reports["locked"])
    pre_execution_validation_summary = base._pre_execution_validation_summary(reports["pre_execution"])
    final_human_approval_summary = _final_human_approval_summary(reports["final_human"])
    blocking_conditions = _blocking_conditions(
        validation_errors,
        proposed_change,
        verified_backup_summary,
        final_gate_summary,
        design_summary,
        locked_runner_summary,
        pre_execution_validation_summary,
        final_human_approval_summary,
    )
    final_safe_shell_status = _final_safe_shell_status(blocking_conditions)
    success = not blocking_conditions
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "final-safe-shell-only",
        "command_label": COMMAND_LABEL,
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "source_readback_rollback_plan_path": str(SOURCE_READBACK_ROLLBACK_PLAN_PATH),
        "source_final_write_gate_path": str(SOURCE_FINAL_WRITE_GATE_PATH),
        "source_real_write_runner_design_path": str(SOURCE_REAL_WRITE_RUNNER_DESIGN_PATH),
        "source_real_write_locked_runner_path": str(SOURCE_REAL_WRITE_LOCKED_RUNNER_PATH),
        "source_pre_execution_validate_path": str(SOURCE_PRE_EXECUTION_VALIDATE_PATH),
        "source_final_human_approval_path": str(SOURCE_FINAL_HUMAN_APPROVAL_PATH),
        "json_final_safe_shell_path": str(FINAL_SAFE_SHELL_JSON_PATH),
        "html_final_safe_shell_path": str(FINAL_SAFE_SHELL_HTML_PATH),
        "success": success,
        "final_safe_shell_status": final_safe_shell_status,
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if base._valid_product_id(requested_scope.get("product_id", "")) else 0,
            "locale_count": 1 if requested_scope.get("locale") in base.ALLOWED_LOCALES else 0,
            "field_count": 1 if requested_scope.get("field") == base.ALLOWED_FIELD else 0,
            "field": requested_scope.get("field", ""),
            "field_allowed": requested_scope.get("field") == base.ALLOWED_FIELD,
            "scope_matches_all_sources": "scope_mismatch" not in validation_errors,
            "environment_scope_matches_reports": "environment_scope_mismatch" not in validation_errors,
            "proposed_value_matches_all_sources": "proposed_value_mismatch" not in validation_errors,
            "allowed_field": base.ALLOWED_FIELD,
            "allowed_locales": sorted(base.ALLOWED_LOCALES),
        },
        "environment_scope": env_scope,
        "source_status_summary": _source_status_summary(reports),
        "proposed_change": proposed_change,
        "verified_backup_summary": verified_backup_summary,
        "final_gate_summary": final_gate_summary,
        "design_summary": design_summary,
        "locked_runner_summary": locked_runner_summary,
        "pre_execution_validation_summary": pre_execution_validation_summary,
        "final_human_approval_summary": final_human_approval_summary,
        "dangerous_flag_summary": {
            "dangerous_flag_name": base.FUTURE_REQUIRED_FLAG,
            "dangerous_flag_env": base.DANGEROUS_FLAG_ENV,
            "dangerous_flag_present": dangerous_flag_present,
            "dangerous_flag_value": dangerous_flag_value,
            "dangerous_flag_required": True,
            "dangerous_flag_effective": False,
            "dangerous_flag_note": (
                "This phase only validates that the dangerous flag exists; it does not trigger any real Shopify write."
            ),
        },
        "final_safe_shell_ack_summary": {
            "ack_env": ACK_ENV,
            "ack_present": ack_present,
            "ack_value": ack_value,
            "ack_effective": False,
            "ack_note": (
                "Even when this ack is true, Phase 12.0 only generates a final-safe shell report and cannot write Shopify."
            ),
        },
        "phase_12_1_entry_preview": _phase_12_1_entry_preview(),
        "phase_12_1_required_inputs": _phase_12_1_required_inputs(),
        "phase_12_1_execution_sequence_preview": _phase_12_1_execution_sequence_preview(),
        "phase_12_1_forbidden_actions": _phase_12_1_forbidden_actions(),
        "readback_requirements": _readback_requirements(),
        "rollback_requirements": _rollback_requirements(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(dangerous_flag_present, ack_present),
        "future_required_flag": base.FUTURE_REQUIRED_FLAG,
        "final_safe_shell_only": True,
        "phase_12_1_entry_allowed": False,
        "phase_12_entry_allowed": False,
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
        "validation_failures": base._unique(validation_errors),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(final_safe_shell_status, blocking_conditions),
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
        "json_final_safe_shell_path": str(json_path),
        "html_final_safe_shell_path": str(html_path),
        "final_safe_shell_status": final_safe_shell_status,
        "final_safe_shell_only": True,
        "phase_12_1_entry_allowed": False,
        "phase_12_entry_allowed": False,
        "dangerous_flag_present": dangerous_flag_present,
        "dangerous_flag_effective": False,
        "final_safe_shell_ack_present": ack_present,
        "final_safe_shell_ack_effective": False,
        "backup_source_is_verified": verified_backup_summary["backup_source_is_verified"],
        "final_gate_status": final_gate_summary["final_gate_status"],
        "design_status": design_summary["design_status"],
        "locked_runner_status": locked_runner_summary["locked_runner_status"],
        "validation_status": pre_execution_validation_summary["validation_status"],
        "approval_package_status": final_human_approval_summary["approval_package_status"],
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
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _validate_final_human_approval(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_FINAL_HUMAN_APPROVAL_TASK or report.get("mode") != EXPECTED_FINAL_HUMAN_APPROVAL_MODE:
        errors.append("unsafe_final_human_approval_package")
    if report.get("approval_package_status") not in READY_FINAL_HUMAN_APPROVAL_STATUSES:
        errors.append("final_human_approval_not_ready")
    if report.get("final_human_approval_package_only") is not True:
        errors.append("unsafe_final_human_approval_package")
    if report.get("phase_12_entry_allowed") is not False:
        errors.append("source_report_indicates_phase_12_entry_allowed")
    dangerous = report.get("dangerous_flag_summary") or {}
    if dangerous.get("dangerous_flag_effective") is not False:
        errors.append("unsafe_dangerous_flag_effective")
    scope = report.get("proposed_change") or report.get("requested_scope") or {}
    errors.extend(base._validate_scope(scope))
    errors.extend(base._validate_proposed_value(scope))
    errors.extend(base._validate_no_write_flags(report))
    for field in ["shopify_api_call_performed", "readback_performed", "rollback_performed"]:
        if report.get(field) is True:
            errors.append("source_report_indicates_shopify_write")
    return base._unique(errors)


def _validate_source_unlock_flags(report: dict) -> list[str]:
    errors = []
    if report.get("phase_12_entry_allowed") is True or report.get("phase_12_1_entry_allowed") is True:
        errors.append("source_report_indicates_phase_12_entry_allowed")
    if report.get("real_write_allowed") is True or report.get("final_real_write_allowed") is True:
        errors.append("source_report_indicates_real_write_allowed")
    if report.get("write_execution_allowed") is True:
        errors.append("source_report_indicates_write_execution_allowed")
    if report.get("translations_register_allowed") is True:
        errors.append("source_report_indicates_translations_register")
    return base._unique(errors)


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
    return base._unique(errors)


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
        reports["pre_execution"].get("proposed_change") or reports["pre_execution"].get("requested_scope") or {},
        reports["final_human"].get("proposed_change") or reports["final_human"].get("requested_scope") or {},
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
    return {
        "preflight_status": reports["preflight"].get("preflight_status", "") if reports["preflight"] else "",
        "backup_fetch_status": reports["backup"].get("backup_fetch_status", "") if reports["backup"] else "",
        "readback_rollback_plan_status": reports["plan"].get("plan_status", "") if reports["plan"] else "",
        "final_gate_status": reports["gate"].get("final_gate_status", "") if reports["gate"] else "",
        "real_write_runner_design_status": reports["design"].get("design_status", "") if reports["design"] else "",
        "locked_runner_status": reports["locked"].get("locked_runner_status", "") if reports["locked"] else "",
        "pre_execution_validation_status": reports["pre_execution"].get("validation_status", "") if reports["pre_execution"] else "",
        "final_human_approval_status": reports["final_human"].get("approval_package_status", "")
        if reports["final_human"]
        else "",
        "all_sources_loaded": all(bool(value) for value in reports.values()),
    }


def _final_human_approval_summary(report: dict) -> dict:
    dangerous = (report.get("dangerous_flag_summary") or {}) if report else {}
    return {
        "approval_package_status": report.get("approval_package_status", "") if report else "",
        "final_human_approval_package_only": bool(report.get("final_human_approval_package_only")) if report else False,
        "phase_12_entry_allowed": bool(report.get("phase_12_entry_allowed")) if report else False,
        "dangerous_flag_present": bool(dangerous.get("dangerous_flag_present")) if report else False,
        "dangerous_flag_effective": bool(dangerous.get("dangerous_flag_effective")) if report else False,
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
        "pre_execution_validation_not_ready": "pre_execution_validation_not_ready",
        "final_human_approval_not_ready": "final_human_approval_not_ready",
        "source_report_indicates_real_write_allowed": "source_report_indicates_real_write_allowed",
        "source_report_indicates_write_execution_allowed": "source_report_indicates_write_execution_allowed",
        "source_report_indicates_phase_12_entry_allowed": "source_report_indicates_phase_12_entry_allowed",
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
    if proposed_change["proposed_value_chars"] > base.MAX_PROPOSED_VALUE_CHARS:
        conditions.append("proposed_value_over_60_chars")
    if not backup_summary["backup_source_is_verified"]:
        conditions.append("backup_not_verified")
    if not backup_summary["read_only_shopify_query_performed"]:
        conditions.append("read_only_backup_query_not_performed")
    if final_gate_summary["final_gate_status"] not in base.READY_GATE_STATUSES:
        conditions.append("final_gate_not_ready")
    if design_summary["design_status"] not in base.READY_DESIGN_STATUSES:
        conditions.append("design_not_ready")
    if locked_runner_summary["locked_runner_status"] not in base.READY_LOCKED_STATUSES:
        conditions.append("locked_runner_not_locked")
    if pre_execution_summary["validation_status"] not in base.READY_PRE_EXECUTION_STATUSES:
        conditions.append("pre_execution_validation_not_ready")
    if final_human_summary["approval_package_status"] not in READY_FINAL_HUMAN_APPROVAL_STATUSES:
        conditions.append("final_human_approval_not_ready")
    if final_human_summary["phase_12_entry_allowed"] is not False:
        conditions.append("source_report_indicates_phase_12_entry_allowed")
    return base._unique(conditions)


def _final_safe_shell_status(blocking_conditions: list[str]) -> str:
    if not blocking_conditions:
        return "final_safe_shell_ready_for_manual_review"
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
    if "final_human_approval_not_ready" in blocking_conditions:
        return "blocked_final_human_approval_not_ready"
    return "blocked"


def _phase_12_1_entry_preview() -> list[str]:
    return [
        "Phase 12.1 is the candidate phase for the first real single-field write test.",
        "Phase 12.1 must be an independent task.",
        "Phase 12.1 must re-read the final human approval package.",
        "Phase 12.1 must re-validate pre-execution validation.",
        "Phase 12.1 must re-validate the verified backup.",
        f"Phase 12.1 must re-validate the dangerous flag: {base.FUTURE_REQUIRED_FLAG}.",
        "Phase 12.1 must stay limited to 1 product x 1 locale x 1 field=meta_title.",
        "Phase 12.1 must immediately read back after the real write.",
        "Phase 12.1 must not automatically rollback.",
        "Phase 12.1 must not allow batch mode.",
        "Phase 12.1 must not scan the whole store.",
        "Phase 12.1 must not allow multiple locales or fields.",
    ]


def _phase_12_1_required_inputs() -> list[str]:
    return [
        "product_id",
        "locale",
        "field=meta_title",
        "proposed_value",
        "verified backup report",
        "readback rollback plan",
        "final write gate",
        "pre-execution validation report",
        "final human approval package",
        f"dangerous flag: {base.FUTURE_REQUIRED_FLAG}",
        "an explicit Phase 12.1 command parameter that Phase 12.0 does not accept",
    ]


def _phase_12_1_execution_sequence_preview() -> list[str]:
    return [
        "Load all source reports.",
        "Re-validate scope consistency.",
        "Re-validate verified backup.",
        "Re-validate final human approval package.",
        "Re-validate dangerous flag.",
        "Execute exactly one Shopify translationsRegister mutation for meta_title.",
        "Immediately read back the same product x locale x meta_title.",
        "Compare readback value exactly with proposed_value.",
        "If match, generate success report.",
        "If mismatch, generate failure report.",
        "Do not automatically rollback.",
        "Create separate rollback approval requirement if needed.",
    ]


def _phase_12_1_forbidden_actions() -> list[str]:
    return [
        "batch mode",
        "full-store scan",
        "multiple products",
        "multiple locales",
        "multiple fields",
        "publish/apply/update outside translationsRegister",
        "automatic rollback",
        "skipping readback",
        "skipping verified backup",
        "skipping final human approval",
        "skipping dangerous flag",
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


def _safety_summary(dangerous_flag_present: bool, ack_present: bool) -> dict:
    return {
        "final_safe_shell_only": True,
        "dangerous_flag_present": dangerous_flag_present,
        "dangerous_flag_effective": False,
        "final_safe_shell_ack_present": ack_present,
        "final_safe_shell_ack_effective": False,
        "phase_12_1_entry_allowed": False,
        "phase_12_entry_allowed": False,
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
        "allowed_field": base.ALLOWED_FIELD,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    FINAL_SAFE_SHELL_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(FINAL_SAFE_SHELL_JSON_PATH.read_text(encoding="utf-8"))
    return FINAL_SAFE_SHELL_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    FINAL_SAFE_SHELL_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return FINAL_SAFE_SHELL_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Final Safe Shell Status", "final_safe_shell_status"),
            ("Final Safe Shell Only", "final_safe_shell_only"),
            ("Phase 12.1 Entry Allowed", "phase_12_1_entry_allowed"),
            ("Phase 12 Entry Allowed", "phase_12_entry_allowed"),
            ("Dangerous Flag", "dangerous_flag_summary"),
            ("Final Safe Shell Ack", "final_safe_shell_ack_summary"),
            ("Final Real Write Allowed", "final_real_write_allowed"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Write Execution Allowed", "write_execution_allowed"),
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
            ("Pre-Execution Validation Summary", payload.get("pre_execution_validation_summary", {})),
            ("Final Human Approval Summary", payload.get("final_human_approval_summary", {})),
            ("Phase 12.1 Entry Preview", payload.get("phase_12_1_entry_preview", [])),
            ("Phase 12.1 Required Inputs", payload.get("phase_12_1_required_inputs", [])),
            ("Phase 12.1 Execution Sequence Preview", payload.get("phase_12_1_execution_sequence_preview", [])),
            ("Phase 12.1 Forbidden Actions", payload.get("phase_12_1_forbidden_actions", [])),
            ("Readback Requirements", payload.get("readback_requirements", [])),
            ("Rollback Requirements", payload.get("rollback_requirements", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Real Write Runner Final-Safe Shell</title>
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
  <h1>Shopify Single-Field Real Write Runner Final-Safe Shell</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Final-Safe Shell Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local JSON reports and environment variables only.</li>
    <li>No Shopify API call was performed.</li>
    <li>No Shopify mutations were called.</li>
    <li>No translationsRegister call was performed.</li>
    <li>No readback, rollback, command execution, or Shopify write was performed in this phase.</li>
    <li>The dangerous flag and Phase 12 ack are both ineffective for writing in this phase.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(final_safe_shell_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Single-field final-safe shell blocked: " + ", ".join(blocking_conditions)
    return (
        f"Single-field final-safe shell generated with status {final_safe_shell_status}. "
        "No Shopify API calls, readback, rollback, mutations, translationsRegister, or writes performed."
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field real write runner final-safe shell report generated.\n"
        f"Final-safe shell status: {payload.get('final_safe_shell_status')}\n"
        f"Requested scope: {payload.get('requested_scope')}\n"
        f"Dangerous flag present: {payload.get('dangerous_flag_summary', {}).get('dangerous_flag_present')}\n"
        f"Dangerous flag effective: {payload.get('dangerous_flag_summary', {}).get('dangerous_flag_effective')}\n"
        f"Final safe shell ack present: {payload.get('final_safe_shell_ack_summary', {}).get('ack_present')}\n"
        f"Final safe shell ack effective: {payload.get('final_safe_shell_ack_summary', {}).get('ack_effective')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Final-safe shell JSON:\n"
        f"{json_path}\n\n"
        "Final-safe shell HTML:\n"
        f"{html_path}\n"
        "Final-safe shell only. No Shopify API call, command execution, readback, rollback, mutation, translationsRegister, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep final-safe shell files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Write, publish, apply, update, mutation, translationsRegister, command execution, commit, and push are not allowed."
    )
