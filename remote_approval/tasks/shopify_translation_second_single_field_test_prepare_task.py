import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_second_single_field_test_prepare"
COMMAND_LABEL = "shopify_translation_second_single_field_test_prepare"
SOURCE_POST_WRITE_AUDIT_PATH = LOG_DIR / "shopify_translation_single_field_post_write_audit_package.json"
SOURCE_ROLLBACK_APPROVAL_PATH = LOG_DIR / "shopify_translation_single_field_rollback_approval_package.json"
SOURCE_ONE_SHOT_EXECUTE_PATH = LOG_DIR / "shopify_translation_single_field_real_write_one_shot_execute.json"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
SECOND_TEST_PREPARE_JSON_PATH = LOG_DIR / "shopify_translation_second_single_field_test_prepare.json"
SECOND_TEST_PREPARE_HTML_PATH = LOG_DIR / "shopify_translation_second_single_field_test_prepare.html"

PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/[0-9]+$")
ALLOWED_FIELD = "meta_title"
ALLOWED_LOCALES = {"de", "fr", "es", "it", "ja"}
MAX_PROPOSED_VALUE_CHARS = 60
PREVIOUS_EXPECTED_STATUS = "real_write_succeeded_and_verified"
PREVIOUS_AUDIT_READY_STATUS = "post_write_audit_passed"
PREVIOUS_ROLLBACK_READY_STATUS = "rollback_approval_package_ready_for_manual_review"


def run_shopify_translation_second_single_field_test_prepare_task(mode: str) -> dict:
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

    requested_scope = _read_second_test_scope()
    validation_errors.extend(_validate_second_test_scope(requested_scope))
    validation_errors.extend(_validate_previous_execution(reports["execution"]))
    validation_errors.extend(_validate_previous_audit(reports["audit"]))
    validation_errors.extend(_validate_previous_rollback_package(reports["rollback"]))
    validation_errors.extend(_validate_previous_backup(reports["backup"]))

    blocking_conditions = _blocking_conditions(validation_errors)
    preparation_status = _preparation_status(blocking_conditions)
    success = preparation_status == "second_single_field_test_prepare_ready_for_manual_review"
    end_time = utc_now_iso()
    previous_real_write_summary = _previous_real_write_summary(reports["execution"])
    previous_post_write_audit_summary = _previous_post_write_audit_summary(reports["audit"])
    previous_rollback_package_summary = _previous_rollback_package_summary(reports["rollback"])

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "second-single-field-test-prepare-only",
        "command_label": COMMAND_LABEL,
        "source_post_write_audit_path": str(SOURCE_POST_WRITE_AUDIT_PATH),
        "source_rollback_approval_path": str(SOURCE_ROLLBACK_APPROVAL_PATH),
        "source_one_shot_execute_path": str(SOURCE_ONE_SHOT_EXECUTE_PATH),
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "json_second_test_prepare_path": str(SECOND_TEST_PREPARE_JSON_PATH),
        "html_second_test_prepare_path": str(SECOND_TEST_PREPARE_HTML_PATH),
        "success": success,
        "preparation_status": preparation_status,
        "requested_second_test_scope": requested_scope,
        "validated_second_test_scope": _validated_second_test_scope(requested_scope),
        "previous_real_write_summary": previous_real_write_summary,
        "previous_post_write_audit_summary": previous_post_write_audit_summary,
        "previous_rollback_package_summary": previous_rollback_package_summary,
        "second_test_constraints": _second_test_constraints(),
        "second_test_required_chain": _second_test_required_chain(),
        "second_test_required_reports": _second_test_required_reports(),
        "second_test_safety_requirements": _second_test_safety_requirements(),
        "second_test_forbidden_actions": _second_test_forbidden_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(),
        "second_test_prepare_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "real_apply_performed": False,
        "second_test_real_write_allowed": False,
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(preparation_status, blocking_conditions),
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
        "json_second_test_prepare_path": str(json_path),
        "html_second_test_prepare_path": str(html_path),
        "preparation_status": preparation_status,
        "second_test_prepare_only": True,
        "second_test_field": requested_scope["field"],
        "second_test_proposed_value_chars": len(requested_scope["proposed_value"]),
        "second_test_real_write_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "real_apply_performed": False,
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _source_report_specs() -> list[tuple[str, str, Path, str, str]]:
    return [
        ("audit", "post-write audit report", SOURCE_POST_WRITE_AUDIT_PATH, "previous_post_write_audit_missing", "post_write_audit_json_invalid"),
        (
            "rollback",
            "rollback approval package",
            SOURCE_ROLLBACK_APPROVAL_PATH,
            "previous_rollback_package_missing",
            "rollback_approval_package_json_invalid",
        ),
        (
            "execution",
            "real write execution report",
            SOURCE_ONE_SHOT_EXECUTE_PATH,
            "previous_real_write_execution_missing",
            "real_write_execution_json_invalid",
        ),
        ("backup", "backup fetch report", SOURCE_BACKUP_FETCH_PATH, "previous_backup_fetch_missing", "backup_fetch_json_invalid"),
    ]


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _read_second_test_scope() -> dict:
    return {
        "product_id": (os.environ.get("SHOPIFY_TRANSLATION_SECOND_TEST_PRODUCT_ID") or "").strip(),
        "locale": (os.environ.get("SHOPIFY_TRANSLATION_SECOND_TEST_LOCALE") or "").strip(),
        "field": (os.environ.get("SHOPIFY_TRANSLATION_SECOND_TEST_FIELD") or "").strip(),
        "proposed_value": (os.environ.get("SHOPIFY_TRANSLATION_SECOND_TEST_PROPOSED_VALUE") or "").strip(),
    }


def _validate_second_test_scope(scope: dict) -> list[str]:
    errors = []
    product_id = scope["product_id"]
    locale = scope["locale"]
    field = scope["field"]
    proposed_value = scope["proposed_value"]

    if not product_id:
        errors.append("missing_second_test_product_id")
    elif "," in product_id or ";" in product_id:
        errors.append("multiple_products_detected")
    elif not PRODUCT_GID_RE.match(product_id):
        errors.append("invalid_product_id")

    if not locale:
        errors.append("missing_second_test_locale")
    elif "," in locale or ";" in locale:
        errors.append("multiple_locales_detected")
    elif locale not in ALLOWED_LOCALES:
        errors.append("invalid_locale")

    if not field:
        errors.append("missing_second_test_field")
    elif "," in field or ";" in field:
        errors.append("multiple_fields_detected")
    elif field != ALLOWED_FIELD:
        errors.append("invalid_field")

    if not proposed_value:
        errors.append("missing_second_test_proposed_value")
        errors.append("proposed_value_empty")
    elif len(proposed_value) > MAX_PROPOSED_VALUE_CHARS:
        errors.append("proposed_value_over_60_chars")

    return _unique(errors)


def _validate_previous_execution(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("execution_status") != PREVIOUS_EXPECTED_STATUS:
        errors.append("previous_source_execution_not_succeeded_and_verified")
    if report.get("readback_matches_proposed_value") is not True:
        errors.append("previous_source_readback_mismatch")
    if report.get("rollback_approval_required") is not False:
        errors.append("previous_source_rollback_required_not_false")
    if report.get("rollback_performed") is True or report.get("automatic_rollback_performed") is True:
        errors.append("previous_source_rollback_already_performed")
    return _unique(errors)


def _validate_previous_audit(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("audit_status") != PREVIOUS_AUDIT_READY_STATUS:
        errors.append("previous_post_write_audit_not_passed")
    if (report.get("verification_summary") or {}).get("audit_verification_passed") is not True:
        errors.append("previous_post_write_audit_not_passed")
    if (report.get("rollback_summary") or {}).get("rollback_needed") is not False:
        errors.append("previous_audit_rollback_needed_not_false")
    return _unique(errors)


def _validate_previous_rollback_package(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("rollback_approval_status") != PREVIOUS_ROLLBACK_READY_STATUS:
        errors.append("previous_rollback_package_not_ready")
    if (report.get("rollback_required_status") or {}).get("rollback_needed") is not False:
        errors.append("previous_rollback_needed_not_false")
    if (report.get("rollback_required_status") or {}).get("rollback_optional_restore_possible") is not True:
        errors.append("previous_optional_restore_not_possible")
    if report.get("rollback_execution_allowed") is not False:
        errors.append("previous_rollback_execution_allowed")
    return _unique(errors)


def _validate_previous_backup(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("read_only_shopify_query_performed") is not True:
        errors.append("previous_backup_not_verified")
    if not (report.get("backup_value_present") and report.get("backup_value")):
        errors.append("previous_backup_value_missing")
    return _unique(errors)


def _validated_second_test_scope(scope: dict) -> dict:
    proposed_value = scope["proposed_value"]
    return {
        "product_count": 1 if PRODUCT_GID_RE.match(scope["product_id"]) else 0,
        "locale_count": 1 if scope["locale"] in ALLOWED_LOCALES and "," not in scope["locale"] and ";" not in scope["locale"] else 0,
        "field_count": 1 if scope["field"] == ALLOWED_FIELD else 0,
        "field": scope["field"],
        "field_allowed": scope["field"] == ALLOWED_FIELD,
        "proposed_value_chars": len(proposed_value),
        "proposed_value_length_allowed": 0 < len(proposed_value) <= MAX_PROPOSED_VALUE_CHARS,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": ALLOWED_FIELD,
    }


def _previous_real_write_summary(report: dict) -> dict:
    requested = report.get("requested_scope") or {}
    proposed = report.get("proposed_change") or requested
    readback = report.get("readback_summary") or {}
    return {
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_product_id": requested.get("product_id", ""),
        "source_locale": requested.get("locale", ""),
        "source_field": requested.get("field", ""),
        "source_written_value": proposed.get("proposed_value", ""),
        "source_readback_value": readback.get("readback_value", ""),
        "source_readback_matched": bool(report.get("readback_matches_proposed_value")) if report else False,
        "source_rollback_required_false": report.get("rollback_approval_required") is False if report else False,
    }


def _previous_post_write_audit_summary(report: dict) -> dict:
    return {
        "audit_status": report.get("audit_status", "") if report else "",
        "real_write_count": int((report.get("write_summary") or {}).get("real_write_count") or 0) if report else 0,
        "audit_verification_passed": bool((report.get("verification_summary") or {}).get("audit_verification_passed"))
        if report
        else False,
        "rollback_needed": bool((report.get("rollback_summary") or {}).get("rollback_needed")) if report else False,
    }


def _previous_rollback_package_summary(report: dict) -> dict:
    required = report.get("rollback_required_status") or {}
    return {
        "rollback_approval_status": report.get("rollback_approval_status", "") if report else "",
        "rollback_needed": bool(required.get("rollback_needed")) if report else False,
        "rollback_optional_restore_possible": bool(required.get("rollback_optional_restore_possible")) if report else False,
        "rollback_execution_allowed": bool(report.get("rollback_execution_allowed")) if report else False,
    }


def _second_test_constraints() -> dict:
    return {
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": ALLOWED_FIELD,
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "automatic_rollback_allowed": False,
    }


def _second_test_required_chain() -> list[str]:
    return [
        "second-test preflight package",
        "read-only backup fetch",
        "readback/rollback plan",
        "final write gate",
        "real write runner design",
        "locked shell",
        "pre-execution validator",
        "final human approval package",
        "final-safe shell",
        "execution plan",
        "one-shot locked shell",
        "one-shot real write + immediate readback",
        "post-write audit",
        "rollback approval package",
    ]


def _second_test_required_reports() -> list[str]:
    return [
        "A new second-test preflight report for the requested scope.",
        "A new read-only backup report from current Shopify online value.",
        "A new readback/rollback plan based on the new verified backup.",
        "A new final write gate report.",
        "A new final human approval package.",
        "A new execution plan and one-shot locked shell.",
        "A new post-write audit and rollback approval package after the second write.",
        "Do not reuse the first test backup as the second test backup.",
    ]


def _second_test_safety_requirements() -> list[str]:
    return [
        "Second test must generate a fresh verified backup.",
        "Second test must generate a fresh approval package.",
        "Second test must require the dangerous flag again.",
        "Second test must immediately read back after any future real write.",
        "Readback mismatch must fail.",
        "Automatic rollback is not allowed.",
        "Rollback must be separately approved.",
        "Batch mode is not allowed.",
        "Expanding to multiple locales or fields is not allowed.",
    ]


def _second_test_forbidden_actions() -> list[str]:
    return [
        "Shopify API call in this phase",
        "Shopify write in this phase",
        "mutation in this phase",
        "translationsRegister in this phase",
        "readback in this phase",
        "rollback in this phase",
        "batch mode",
        "full-store scan",
        "multiple products",
        "multiple locales",
        "multiple fields",
        "reusing old backup as new backup",
        "git push",
    ]


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_second_test_product_id": "missing_second_test_product_id",
        "missing_second_test_locale": "missing_second_test_locale",
        "missing_second_test_field": "missing_second_test_field",
        "missing_second_test_proposed_value": "missing_second_test_proposed_value",
        "invalid_product_id": "invalid_product_id",
        "invalid_locale": "invalid_locale",
        "invalid_field": "invalid_field",
        "proposed_value_empty": "proposed_value_empty",
        "proposed_value_over_60_chars": "proposed_value_over_60_chars",
        "multiple_products_detected": "multiple_products_detected",
        "multiple_locales_detected": "multiple_locales_detected",
        "multiple_fields_detected": "multiple_fields_detected",
        "previous_post_write_audit_missing": "previous_post_write_audit_missing",
        "previous_post_write_audit_not_passed": "previous_post_write_audit_not_passed",
        "previous_rollback_package_missing": "previous_rollback_package_missing",
        "previous_rollback_package_not_ready": "previous_rollback_package_not_ready",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _preparation_status(blocking_conditions: list[str]) -> str:
    missing_scope = {
        "missing_second_test_product_id",
        "missing_second_test_locale",
        "missing_second_test_field",
        "missing_second_test_proposed_value",
    }
    if any(condition in blocking_conditions for condition in missing_scope):
        return "blocked_missing_second_test_scope"
    if not blocking_conditions:
        return "second_single_field_test_prepare_ready_for_manual_review"
    return "blocked"


def _safety_summary() -> dict:
    return {
        "second_test_prepare_only": True,
        "shopify_api_call_allowed": False,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
        "second_test_real_write_allowed": False,
        "batch_mode_allowed": False,
        "full_store_scan_allowed": False,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
        "allowed_field": ALLOWED_FIELD,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SECOND_TEST_PREPARE_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SECOND_TEST_PREPARE_JSON_PATH.read_text(encoding="utf-8"))
    return SECOND_TEST_PREPARE_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SECOND_TEST_PREPARE_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SECOND_TEST_PREPARE_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Preparation Status", "preparation_status"),
            ("Requested Second Test Scope", "requested_second_test_scope"),
            ("Validated Second Test Scope", "validated_second_test_scope"),
            ("Previous Real Write Summary", "previous_real_write_summary"),
            ("Previous Post-Write Audit Summary", "previous_post_write_audit_summary"),
            ("Previous Rollback Package Summary", "previous_rollback_package_summary"),
            ("Second Test Constraints", "second_test_constraints"),
            ("Second Test Real Write Allowed", "second_test_real_write_allowed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Second Test Required Chain", payload.get("second_test_required_chain", [])),
            ("Second Test Required Reports", payload.get("second_test_required_reports", [])),
            ("Second Test Safety Requirements", payload.get("second_test_safety_requirements", [])),
            ("Second Test Forbidden Actions", payload.get("second_test_forbidden_actions", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Second Single-Field Test Prepare</title>
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
  <h1>Shopify Second Single-Field Test Prepare</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Preparation Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local reports and environment variables only.</li>
    <li>No Shopify API call, mutation, translationsRegister, readback, rollback, or write was performed.</li>
    <li>The second test must generate a fresh verified backup before any future write.</li>
    <li>Batch mode, full-store scans, multiple products, multiple locales, and multiple fields are forbidden.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Second single-field test preparation blocked: " + ", ".join(blocking_conditions)
    return f"Second single-field test preparation package generated with status {status}. No Shopify action performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify second single-field test preparation package generated.\n"
        f"Preparation status: {payload.get('preparation_status')}\n"
        f"Requested second test scope: {payload.get('requested_second_test_scope')}\n"
        f"Previous audit status: {payload.get('previous_post_write_audit_summary', {}).get('audit_status')}\n"
        f"Previous rollback package status: {payload.get('previous_rollback_package_summary', {}).get('rollback_approval_status')}\n"
        f"Second test real write allowed: {payload.get('second_test_real_write_allowed')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Second test prepare JSON:\n"
        f"{json_path}\n\n"
        "Second test prepare HTML:\n"
        f"{html_path}\n"
        "Second-test preparation only. No Shopify API call, mutation, translationsRegister, readback, rollback, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep second-test preparation files\n"
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
