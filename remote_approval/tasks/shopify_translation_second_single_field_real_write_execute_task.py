import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.tasks import shopify_translation_second_single_field_real_write_readiness_task as readiness
from remote_approval.tasks import shopify_translation_second_single_field_test_prepare_task as prepare
from remote_approval.tasks import shopify_translation_single_field_real_write_one_shot_execute_task as first_execute
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_second_single_field_real_write_execute"
COMMAND_LABEL = "shopify_translation_second_single_field_real_write_execute"
SOURCE_SECOND_TEST_PREPARE_PATH = LOG_DIR / "shopify_translation_second_single_field_test_prepare.json"
SOURCE_SECOND_VERIFIED_BACKUP_PATH = LOG_DIR / "shopify_translation_second_single_field_verified_backup_fetch.json"
SOURCE_SECOND_READINESS_PATH = LOG_DIR / "shopify_translation_second_single_field_real_write_readiness.json"
SECOND_REAL_WRITE_EXECUTE_JSON_PATH = LOG_DIR / "shopify_translation_second_single_field_real_write_execute.json"
SECOND_REAL_WRITE_EXECUTE_HTML_PATH = LOG_DIR / "shopify_translation_second_single_field_real_write_execute.html"

REAL_EXECUTION_ACK_ENV = "SHOPIFY_TRANSLATION_SECOND_TEST_REAL_EXECUTION_ACK"
REAL_EXECUTION_ACK_VALUE = "YES_I_APPROVE_SECOND_REAL_SHOPIFY_TRANSLATION_WRITE"
SUPPORTED_MODES = {"dry-run", "real-run", "execute-real-write"}
REAL_RUN_MODES = {"real-run", "execute-real-write"}

EXPECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
EXPECTED_LOCALE = "ja"
EXPECTED_FIELD = "meta_title"
EXPECTED_PROPOSED_VALUE = "MOFLY P-51D Aileron Link Connector Test"
EXPECTED_BACKUP_VALUE = "MOFLY P-51D Aileron Link Connector"

READY_PREPARE_STATUS = "second_single_field_test_prepare_ready_for_manual_review"
READY_BACKUP_STATUS = "second_verified_backup_ready"
READY_READINESS_STATUS = "second_real_write_ready_for_human_approval"


def run_shopify_translation_second_single_field_real_write_execute_task(mode: str) -> dict:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"{TASK_NAME} only supports dry-run, real-run, or execute-real-write mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    reports = {}

    for key, label, path, missing_code, invalid_code in [
        ("prepare", "second test prepare report", SOURCE_SECOND_TEST_PREPARE_PATH, "missing_second_test_prepare_report", "second_test_prepare_json_invalid"),
        (
            "backup",
            "second verified backup report",
            SOURCE_SECOND_VERIFIED_BACKUP_PATH,
            "missing_second_verified_backup_report",
            "second_verified_backup_json_invalid",
        ),
        (
            "readiness",
            "second real write readiness report",
            SOURCE_SECOND_READINESS_PATH,
            "missing_second_real_write_readiness_report",
            "second_real_write_readiness_json_invalid",
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

    env_scope = _read_second_test_scope()
    ack_value = os.environ.get(REAL_EXECUTION_ACK_ENV, "").strip()
    ack_present = bool(ack_value)
    ack_valid = ack_value == REAL_EXECUTION_ACK_VALUE
    approval_mode = os.environ.get("REMOTE_APPROVAL_MODE", "")

    validation_errors.extend(_validate_env_scope(env_scope))
    validation_errors.extend(_validate_fixed_scope(env_scope))
    if not ack_present:
        validation_errors.append("missing_second_real_execution_ack")
    elif not ack_valid:
        validation_errors.append("invalid_second_real_execution_ack")
    if mode in REAL_RUN_MODES and approval_mode and approval_mode != "local":
        validation_errors.append("approval_not_local")

    validation_errors.extend(_validate_prepare_report(reports["prepare"]))
    validation_errors.extend(_validate_backup_report(reports["backup"]))
    validation_errors.extend(_validate_readiness_report(reports["readiness"]))
    if reports["prepare"]:
        validation_errors.extend(_validate_scope_match("prepare", reports["prepare"].get("requested_second_test_scope") or {}, env_scope))
    if reports["backup"]:
        validation_errors.extend(_validate_scope_match("backup", _backup_scope(reports["backup"]), env_scope))
    if reports["readiness"]:
        validation_errors.extend(_validate_scope_match("readiness", _readiness_scope(reports["readiness"]), env_scope))

    blocking_conditions = _blocking_conditions(validation_errors)
    execution_result = _empty_execution_result(env_scope)
    real_run_attempted = mode in REAL_RUN_MODES and not blocking_conditions
    if real_run_attempted:
        execution_result = first_execute._execute_real_write_and_readback(env_scope)

    execution_status = _execution_status(mode, blocking_conditions, execution_result)
    translations_register_called = bool(execution_result.get("translations_register_called"))
    mutation_performed = bool(execution_result.get("mutation_performed"))
    shopify_write_performed = bool(execution_result.get("shopify_write_performed"))
    shopify_api_call_performed = bool(execution_result.get("shopify_api_call_performed"))
    readback_performed = bool(execution_result.get("readback_performed"))
    readback_matches_proposed_value = bool(execution_result.get("readback_matches_proposed_value"))
    rollback_approval_required = _rollback_approval_required(execution_status, execution_result)
    no_new_shopify_writes_performed = not (
        translations_register_called or mutation_performed or shopify_write_performed
    )
    all_new_actions_no_write_confirmed = no_new_shopify_writes_performed
    success = (
        execution_status == "dry_run_second_real_write_not_executed"
        if mode == "dry-run"
        else execution_status == "second_real_write_succeeded_and_verified"
    )
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "source_second_test_prepare_path": str(SOURCE_SECOND_TEST_PREPARE_PATH),
        "source_second_verified_backup_path": str(SOURCE_SECOND_VERIFIED_BACKUP_PATH),
        "source_second_readiness_path": str(SOURCE_SECOND_READINESS_PATH),
        "json_second_real_write_execute_path": str(SECOND_REAL_WRITE_EXECUTE_JSON_PATH),
        "html_second_real_write_execute_path": str(SECOND_REAL_WRITE_EXECUTE_HTML_PATH),
        "success": success,
        "execution_status": execution_status,
        "requested_scope": env_scope,
        "validated_scope": _validated_scope(env_scope, reports),
        "environment_scope": env_scope,
        "source_status_summary": _source_status_summary(reports),
        "proposed_change": _proposed_change(env_scope),
        "verified_backup_summary": _verified_backup_summary(reports["backup"]),
        "readiness_summary": _readiness_summary(reports["readiness"]),
        "real_execution_ack_summary": {
            "ack_env": REAL_EXECUTION_ACK_ENV,
            "ack_present": ack_present,
            "ack_value_matches_required_phrase": ack_valid,
            "ack_required_value": REAL_EXECUTION_ACK_VALUE,
            "ack_effective": bool(real_run_attempted),
            "ack_note": "ACK is required, but dry-run never writes Shopify.",
        },
        "translations_register_execution_summary": {
            "mode": mode,
            "real_run_attempted": real_run_attempted,
            "translations_register_allowed": real_run_attempted,
            "translations_register_called": translations_register_called,
            "mutation_performed": mutation_performed,
            "shopify_write_performed": shopify_write_performed,
            "shopify_api_call_performed": shopify_api_call_performed,
            "shopify_api_call_count": int(execution_result.get("shopify_api_call_count") or 0),
            "real_write_count": int(execution_result.get("real_write_count") or 0),
            "mutation_name": "translationsRegister",
            "user_errors": execution_result.get("user_errors") or [],
            "http_statuses": execution_result.get("http_statuses") or [],
        },
        "readback_summary": _readback_summary(execution_result, env_scope),
        "verification_summary": {
            "readback_required": True,
            "readback_performed": readback_performed,
            "readback_value": execution_result.get("readback_value", ""),
            "proposed_value": env_scope.get("proposed_value", ""),
            "readback_matches_proposed_value": readback_matches_proposed_value,
            "verification_passed": execution_status == "second_real_write_succeeded_and_verified",
        },
        "failure_summary": _failure_summary(execution_status, execution_result, blocking_conditions),
        "rollback_approval_requirement": {
            "rollback_approval_required": rollback_approval_required,
            "rollback_performed": False,
            "automatic_rollback_performed": False,
            "automatic_rollback_allowed": False,
            "rollback_value_source": "second verified backup report",
            "backup_value": EXPECTED_BACKUP_VALUE,
            "backup_value_chars": len(EXPECTED_BACKUP_VALUE),
            "rollback_scope": {
                "product_id": EXPECTED_PRODUCT_ID,
                "locale": EXPECTED_LOCALE,
                "field": EXPECTED_FIELD,
            },
        },
        "safety_summary": _safety_summary(mode, real_run_attempted, execution_result),
        "blocking_conditions": blocking_conditions,
        "second_real_write_execute_task": True,
        "second_real_write_scope_limited": True,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": EXPECTED_FIELD,
        "batch_mode_allowed": False,
        "bulk_write_performed": False,
        "full_store_scan_allowed": False,
        "automatic_rollback_allowed": False,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "command_executed": False,
        "real_write_allowed": bool(real_run_attempted),
        "write_execution_allowed": bool(real_run_attempted),
        "translations_register_allowed": bool(real_run_attempted),
        "translations_register_called": translations_register_called,
        "translations_register_performed": translations_register_called,
        "shopify_write_performed": shopify_write_performed,
        "mutation_performed": mutation_performed,
        "shopify_mutations_called": ["translationsRegister"] if translations_register_called else [],
        "shopify_api_call_performed": shopify_api_call_performed,
        "readback_performed": readback_performed,
        "readback_matches_proposed_value": readback_matches_proposed_value,
        "rollback_approval_required": rollback_approval_required,
        "real_apply_performed": False,
        "real_write_count": int(execution_result.get("real_write_count") or 0),
        "no_new_shopify_writes_performed": no_new_shopify_writes_performed,
        "all_new_actions_no_write_confirmed": all_new_actions_no_write_confirmed,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "execution_failure_type": execution_result.get("failure_type", ""),
        "execution_failure_reason": execution_result.get("failure_reason", ""),
        "stdout_tail": execution_result.get("stdout_tail", ""),
        "stderr_tail": execution_result.get("stderr_tail", ""),
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
        "json_second_real_write_execute_path": str(json_path),
        "html_second_real_write_execute_path": str(html_path),
        "execution_status": execution_status,
        "second_real_write_execute_task": True,
        "second_real_execution_ack_present": ack_present,
        "second_real_execution_ack_valid": ack_valid,
        "second_real_write_scope_limited": True,
        "real_write_count": int(execution_result.get("real_write_count") or 0),
        "translations_register_called": translations_register_called,
        "shopify_write_performed": shopify_write_performed,
        "mutation_performed": mutation_performed,
        "shopify_api_call_performed": shopify_api_call_performed,
        "readback_performed": readback_performed,
        "readback_matches_proposed_value": readback_matches_proposed_value,
        "rollback_approval_required": rollback_approval_required,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "no_new_shopify_writes_performed": no_new_shopify_writes_performed,
        "all_new_actions_no_write_confirmed": all_new_actions_no_write_confirmed,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_second_test_scope() -> dict:
    return {
        "product_id": (os.environ.get("SHOPIFY_TRANSLATION_SECOND_TEST_PRODUCT_ID") or "").strip(),
        "locale": (os.environ.get("SHOPIFY_TRANSLATION_SECOND_TEST_LOCALE") or "").strip(),
        "field": (os.environ.get("SHOPIFY_TRANSLATION_SECOND_TEST_FIELD") or "").strip(),
        "proposed_value": (os.environ.get("SHOPIFY_TRANSLATION_SECOND_TEST_PROPOSED_VALUE") or "").strip(),
    }


def _validate_env_scope(scope: dict) -> list[str]:
    errors = []
    product_id = scope["product_id"]
    locale = scope["locale"]
    field = scope["field"]
    proposed_value = scope["proposed_value"]

    if not product_id:
        errors.append("missing_second_test_product_id")
    elif "," in product_id or ";" in product_id:
        errors.append("multiple_products_detected")
    elif not prepare.PRODUCT_GID_RE.match(product_id):
        errors.append("invalid_product_id")

    if not locale:
        errors.append("missing_second_test_locale")
    elif "," in locale or ";" in locale:
        errors.append("multiple_locales_detected")
    elif locale not in prepare.ALLOWED_LOCALES:
        errors.append("invalid_locale")

    if not field:
        errors.append("missing_second_test_field")
    elif "," in field or ";" in field:
        errors.append("multiple_fields_detected")
    elif field != EXPECTED_FIELD:
        errors.append("invalid_field")

    if not proposed_value:
        errors.append("missing_second_test_proposed_value")
        errors.append("empty_proposed_value")
    elif len(proposed_value) > prepare.MAX_PROPOSED_VALUE_CHARS:
        errors.append("proposed_value_too_long")
    return _unique(errors)


def _validate_fixed_scope(scope: dict) -> list[str]:
    errors = []
    if scope.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.append("scope_mismatch")
    if scope.get("locale") != EXPECTED_LOCALE:
        errors.append("scope_mismatch")
    if scope.get("field") != EXPECTED_FIELD:
        errors.append("invalid_field")
    if scope.get("proposed_value") != EXPECTED_PROPOSED_VALUE:
        errors.append("proposed_value_mismatch")
    return _unique(errors)


def _validate_prepare_report(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("task") != prepare.TASK_NAME:
        errors.append("unsafe_second_test_prepare_report")
    if report.get("preparation_status") != READY_PREPARE_STATUS:
        errors.append("second_test_prepare_not_ready")
    if report.get("second_test_real_write_allowed") is not False:
        errors.append("unsafe_second_test_prepare_report")
    if report.get("no_new_shopify_writes_performed") is not True:
        errors.append("unsafe_second_test_prepare_report")
    for flag in [
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "readback_performed",
        "rollback_performed",
    ]:
        if report.get(flag) is True:
            errors.append("unsafe_second_test_prepare_report")
    return _unique(errors)


def _validate_backup_report(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("task") != "shopify_translation_second_single_field_verified_backup_fetch":
        errors.append("unsafe_second_verified_backup_report")
    if report.get("backup_fetch_status") != READY_BACKUP_STATUS:
        errors.append("second_verified_backup_not_ready")
    if not _backup_source_verified(report):
        errors.append("unverified_backup")
    if report.get("read_only_shopify_query_performed") is not True:
        errors.append("unverified_backup")
    if str(report.get("second_backup_value") or "") != EXPECTED_BACKUP_VALUE:
        errors.append("backup_value_mismatch")
    if report.get("second_test_real_write_allowed") is not False:
        errors.append("unsafe_second_verified_backup_report")
    for flag in [
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "rollback_performed",
    ]:
        if report.get(flag) is True:
            errors.append("unsafe_second_verified_backup_report")
    return _unique(errors)


def _validate_readiness_report(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("task") != readiness.TASK_NAME:
        errors.append("unsafe_second_real_write_readiness_report")
    if report.get("readiness_status") != READY_READINESS_STATUS:
        errors.append("second_real_write_readiness_not_ready")
    if report.get("backup_source_verified") is not True:
        errors.append("unverified_backup")
    if report.get("read_only_backup_query_performed") is not True:
        errors.append("unverified_backup")
    if report.get("second_test_real_write_allowed") is not False:
        errors.append("unsafe_second_real_write_readiness_report")
    if report.get("current_backup_value") != EXPECTED_BACKUP_VALUE:
        errors.append("backup_value_mismatch")
    for flag in [
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "readback_performed",
        "rollback_performed",
    ]:
        if report.get(flag) is True:
            errors.append("unsafe_second_real_write_readiness_report")
    return _unique(errors)


def _validate_scope_match(label: str, report_scope: dict, env_scope: dict) -> list[str]:
    errors = []
    for key in ["product_id", "locale", "field", "proposed_value"]:
        if report_scope.get(key) != env_scope.get(key):
            errors.append(f"{label}_scope_mismatch")
    return _unique(errors)


def _backup_scope(report: dict) -> dict:
    return {
        "product_id": report.get("second_backup_product_id", ""),
        "locale": report.get("second_backup_locale", ""),
        "field": report.get("second_backup_field", ""),
        "proposed_value": report.get("second_test_proposed_value", ""),
    }


def _readiness_scope(report: dict) -> dict:
    return {
        "product_id": report.get("product_id", ""),
        "locale": report.get("locale", ""),
        "field": report.get("field", ""),
        "proposed_value": report.get("proposed_value", ""),
    }


def _backup_source_verified(report: dict) -> bool:
    return report.get("second_backup_source_verified") is True or report.get("second_backup_source_is_verified") is True


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_second_real_execution_ack": "blocked_missing_second_real_execution_ack",
        "invalid_second_real_execution_ack": "blocked_invalid_second_real_execution_ack",
        "scope_mismatch": "blocked_scope_mismatch",
        "prepare_scope_mismatch": "blocked_scope_mismatch",
        "backup_scope_mismatch": "blocked_scope_mismatch",
        "readiness_scope_mismatch": "blocked_scope_mismatch",
        "proposed_value_mismatch": "blocked_scope_mismatch",
        "invalid_field": "blocked_invalid_field",
        "missing_second_real_write_readiness_report": "blocked_missing_second_real_write_readiness_report",
        "second_real_write_readiness_not_ready": "blocked_second_real_write_readiness_not_ready",
        "second_test_prepare_not_ready": "blocked_second_test_prepare_not_ready",
        "second_verified_backup_not_ready": "blocked_unverified_backup",
        "unverified_backup": "blocked_unverified_backup",
        "backup_value_mismatch": "blocked_unverified_backup",
        "empty_proposed_value": "blocked_scope_mismatch",
        "proposed_value_too_long": "blocked_scope_mismatch",
        "missing_second_test_product_id": "blocked_scope_mismatch",
        "missing_second_test_locale": "blocked_scope_mismatch",
        "missing_second_test_field": "blocked_scope_mismatch",
        "missing_second_test_proposed_value": "blocked_scope_mismatch",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _execution_status(mode: str, blocking_conditions: list[str], execution_result: dict) -> str:
    if blocking_conditions:
        for status in [
            "blocked_missing_second_real_execution_ack",
            "blocked_invalid_second_real_execution_ack",
            "blocked_invalid_field",
            "blocked_scope_mismatch",
            "blocked_missing_second_real_write_readiness_report",
            "blocked_second_real_write_readiness_not_ready",
            "blocked_unverified_backup",
        ]:
            if status in blocking_conditions:
                return status
        return "blocked"
    if mode == "dry-run":
        return "dry_run_second_real_write_not_executed"
    if execution_result.get("success") and execution_result.get("readback_matches_proposed_value"):
        return "second_real_write_succeeded_and_verified"
    if execution_result.get("shopify_write_performed") and not execution_result.get("readback_matches_proposed_value"):
        return "second_real_write_completed_but_readback_mismatch"
    return "second_real_write_failed"


def _empty_execution_result(scope: dict) -> dict:
    return {
        "success": False,
        "execution_attempted": False,
        "product_id": scope.get("product_id", ""),
        "locale": scope.get("locale", ""),
        "field": scope.get("field", ""),
        "proposed_value": scope.get("proposed_value", ""),
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
        "failure_type": "",
        "failure_reason": "",
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _validated_scope(scope: dict, reports: dict) -> dict:
    return {
        "product_count": 1 if scope.get("product_id") == EXPECTED_PRODUCT_ID else 0,
        "locale_count": 1 if scope.get("locale") == EXPECTED_LOCALE else 0,
        "field_count": 1 if scope.get("field") == EXPECTED_FIELD else 0,
        "field": scope.get("field", ""),
        "field_allowed": scope.get("field") == EXPECTED_FIELD,
        "product_id_matches_fixed_scope": scope.get("product_id") == EXPECTED_PRODUCT_ID,
        "locale_matches_fixed_scope": scope.get("locale") == EXPECTED_LOCALE,
        "proposed_value_matches_fixed_scope": scope.get("proposed_value") == EXPECTED_PROPOSED_VALUE,
        "scope_matches_prepare_report": _scopes_equal((reports.get("prepare") or {}).get("requested_second_test_scope") or {}, scope),
        "scope_matches_verified_backup_report": _scopes_equal(_backup_scope(reports.get("backup") or {}), scope),
        "scope_matches_readiness_report": _scopes_equal(_readiness_scope(reports.get("readiness") or {}), scope),
        "allowed_field": EXPECTED_FIELD,
        "allowed_locale": EXPECTED_LOCALE,
        "allowed_product_id": EXPECTED_PRODUCT_ID,
        "proposed_value_chars": len(scope.get("proposed_value", "")),
        "proposed_value_length_allowed": 0 < len(scope.get("proposed_value", "")) <= prepare.MAX_PROPOSED_VALUE_CHARS,
    }


def _source_status_summary(reports: dict) -> dict:
    return {
        "second_test_prepare_status": (reports.get("prepare") or {}).get("preparation_status", ""),
        "second_verified_backup_status": (reports.get("backup") or {}).get("backup_fetch_status", ""),
        "second_real_write_readiness_status": (reports.get("readiness") or {}).get("readiness_status", ""),
        "backup_source_verified": _backup_source_verified(reports.get("backup") or {}),
        "read_only_shopify_query_performed": (reports.get("backup") or {}).get("read_only_shopify_query_performed") is True,
    }


def _proposed_change(scope: dict) -> dict:
    value = scope.get("proposed_value", "")
    return {
        "product_id": scope.get("product_id", ""),
        "locale": scope.get("locale", ""),
        "field": scope.get("field", ""),
        "proposed_value": value,
        "proposed_value_chars": len(value),
        "proposed_value_length_allowed": 0 < len(value) <= prepare.MAX_PROPOSED_VALUE_CHARS,
    }


def _verified_backup_summary(report: dict) -> dict:
    return {
        "backup_fetch_status": report.get("backup_fetch_status", "") if report else "",
        "backup_source_verified": _backup_source_verified(report) if report else False,
        "read_only_shopify_query_performed": report.get("read_only_shopify_query_performed") is True if report else False,
        "backup_value": report.get("second_backup_value", "") if report else "",
        "backup_value_chars": int(report.get("second_backup_value_chars") or 0) if report else 0,
        "backup_locale": report.get("second_backup_locale", "") if report else "",
        "backup_field": report.get("second_backup_field", "") if report else "",
        "backup_product_id": report.get("second_backup_product_id", "") if report else "",
    }


def _readiness_summary(report: dict) -> dict:
    return {
        "readiness_status": report.get("readiness_status", "") if report else "",
        "readiness_package_only": report.get("readiness_package_only") is True if report else False,
        "backup_source_verified": report.get("backup_source_verified") is True if report else False,
        "read_only_backup_query_performed": report.get("read_only_backup_query_performed") is True if report else False,
        "human_approval_required_before_real_write": report.get("human_approval_required_before_real_write") is True
        if report
        else False,
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
        "failure": execution_status not in {
            "dry_run_second_real_write_not_executed",
            "second_real_write_succeeded_and_verified",
        },
        "failure_reason": execution_result.get("failure_reason", ""),
        "failure_type": execution_result.get("failure_type", ""),
        "blocking_conditions": blocking_conditions,
        "rollback_approval_required": _rollback_approval_required(execution_status, execution_result),
        "verified_backup_preserved": True,
    }


def _rollback_approval_required(execution_status: str, execution_result: dict) -> bool:
    if execution_status in {"second_real_write_completed_but_readback_mismatch", "second_real_write_failed"}:
        return bool(
            execution_result.get("translations_register_called")
            or execution_result.get("mutation_performed")
            or execution_result.get("shopify_write_performed")
        )
    return False


def _safety_summary(mode: str, real_run_attempted: bool, execution_result: dict) -> dict:
    return {
        "mode": mode,
        "second_real_write_execute_task": True,
        "real_run_attempted": real_run_attempted,
        "dry_run_never_writes": mode == "dry-run",
        "scope_limited": True,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_product_id": EXPECTED_PRODUCT_ID,
        "allowed_locale": EXPECTED_LOCALE,
        "allowed_field": EXPECTED_FIELD,
        "allowed_proposed_value": EXPECTED_PROPOSED_VALUE,
        "batch_mode_allowed": False,
        "bulk_write_performed": False,
        "full_store_scan_allowed": False,
        "automatic_rollback_allowed": False,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "publish_performed": False,
        "shopify_api_call_performed": bool(execution_result.get("shopify_api_call_performed")),
        "translations_register_called": bool(execution_result.get("translations_register_called")),
        "shopify_write_performed": bool(execution_result.get("shopify_write_performed")),
        "readback_performed": bool(execution_result.get("readback_performed")),
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SECOND_REAL_WRITE_EXECUTE_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SECOND_REAL_WRITE_EXECUTE_JSON_PATH.read_text(encoding="utf-8"))
    return SECOND_REAL_WRITE_EXECUTE_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SECOND_REAL_WRITE_EXECUTE_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SECOND_REAL_WRITE_EXECUTE_HTML_PATH


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
            ("Bulk Write Performed", "bulk_write_performed"),
            ("Publish Performed", "publish_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
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
            ("Readiness Summary", payload.get("readiness_summary", {})),
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
  <title>Shopify Second Single-Field Real Write Execute</title>
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
  <h1>Shopify Second Single-Field Real Write Execute</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>Dry-run mode never calls Shopify APIs or writes Shopify.</li>
    <li>Real-run mode is limited to one product, one locale, and field=meta_title.</li>
    <li>Real-run mode requires the exact second real execution ACK phrase.</li>
    <li>Rollback is never automatic.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(execution_status: str, blocking_conditions: list[str], execution_result: dict) -> str:
    if blocking_conditions:
        return "Second single-field real write execute blocked: " + ", ".join(blocking_conditions)
    if execution_status == "dry_run_second_real_write_not_executed":
        return "Dry-run completed. Second real Shopify write was not executed."
    if execution_status == "second_real_write_succeeded_and_verified":
        return "Second Shopify translationsRegister write succeeded and immediate readback matched proposed value."
    if execution_status == "second_real_write_completed_but_readback_mismatch":
        return "Second Shopify write completed but readback did not match proposed value; rollback approval is required."
    return "Second Shopify one-shot write failed: " + (
        execution_result.get("failure_reason") or execution_result.get("failure_type") or "unknown"
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify second single-field real write execute report generated.\n"
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
        "Dry-run mode is no-write. Real-run mode requires a separate explicit command and the exact second ACK variable.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep execution report files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Do not push from this task."
    )


def _scopes_equal(left: dict, right: dict) -> bool:
    return all(left.get(key) == right.get(key) for key in ["product_id", "locale", "field", "proposed_value"])


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
