import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.tasks import shopify_translation_second_single_field_test_prepare_task as prepare
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_second_single_field_real_write_readiness"
COMMAND_LABEL = "shopify_translation_second_single_field_real_write_readiness"
SOURCE_SECOND_TEST_PREPARE_PATH = LOG_DIR / "shopify_translation_second_single_field_test_prepare.json"
SOURCE_SECOND_VERIFIED_BACKUP_PATH = LOG_DIR / "shopify_translation_second_single_field_verified_backup_fetch.json"
READINESS_JSON_PATH = LOG_DIR / "shopify_translation_second_single_field_real_write_readiness.json"
READINESS_HTML_PATH = LOG_DIR / "shopify_translation_second_single_field_real_write_readiness.html"

READY_PREPARE_STATUS = "second_single_field_test_prepare_ready_for_manual_review"
READY_BACKUP_STATUS = "second_verified_backup_ready"
READY_READINESS_STATUS = "second_real_write_ready_for_human_approval"
ALLOWED_FIELD = "meta_title"


def run_shopify_translation_second_single_field_real_write_readiness_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    prepare_report = {}
    backup_report = {}

    try:
        prepare_report = _read_json(SOURCE_SECOND_TEST_PREPARE_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Second test prepare JSON not found: {exc}")
        validation_errors.append("missing_second_test_prepare_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse second test prepare JSON: {exc}")
        validation_errors.append("second_test_prepare_json_invalid")

    try:
        backup_report = _read_json(SOURCE_SECOND_VERIFIED_BACKUP_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Second verified backup JSON not found: {exc}")
        validation_errors.append("missing_second_verified_backup_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse second verified backup JSON: {exc}")
        validation_errors.append("second_verified_backup_json_invalid")

    env_scope = _read_second_test_scope()
    validation_errors.extend(_validate_env_scope(env_scope))
    validation_errors.extend(_validate_prepare_report(prepare_report))
    validation_errors.extend(_validate_backup_report(backup_report))
    if prepare_report:
        validation_errors.extend(_validate_scope_match("prepare", prepare_report.get("requested_second_test_scope") or {}, env_scope))
    if backup_report:
        validation_errors.extend(_validate_scope_match("backup", _backup_scope(backup_report), env_scope))

    blocking_conditions = _blocking_conditions(validation_errors)
    readiness_status = _readiness_status(blocking_conditions)
    success = readiness_status == READY_READINESS_STATUS
    backup_value = str(backup_report.get("second_backup_value") or "")
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "second-single-field-real-write-readiness-only",
        "command_label": COMMAND_LABEL,
        "source_second_test_prepare_path": str(SOURCE_SECOND_TEST_PREPARE_PATH),
        "source_second_verified_backup_path": str(SOURCE_SECOND_VERIFIED_BACKUP_PATH),
        "json_readiness_path": str(READINESS_JSON_PATH),
        "html_readiness_path": str(READINESS_HTML_PATH),
        "success": success,
        "readiness_status": readiness_status,
        "product_id": env_scope["product_id"],
        "locale": env_scope["locale"],
        "field": env_scope["field"],
        "current_backup_value": backup_value,
        "current_backup_value_chars": len(backup_value),
        "proposed_value": env_scope["proposed_value"],
        "proposed_value_chars": len(env_scope["proposed_value"]),
        "backup_source_verified": _backup_source_verified(backup_report),
        "second_backup_source_verified": _backup_source_verified(backup_report),
        "read_only_backup_query_performed": backup_report.get("read_only_shopify_query_performed") is True,
        "requested_scope": env_scope,
        "validated_scope": _validated_scope(env_scope, prepare_report, backup_report),
        "source_status_summary": _source_status_summary(prepare_report, backup_report),
        "prepare_report_summary": _prepare_report_summary(prepare_report),
        "verified_backup_summary": _verified_backup_summary(backup_report),
        "human_approval_checklist": _human_approval_checklist(env_scope, backup_value),
        "second_real_write_requirements": _second_real_write_requirements(),
        "forbidden_actions": _forbidden_actions(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(),
        "readiness_package_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "real_apply_performed": False,
        "second_test_real_write_allowed": False,
        "human_approval_required_before_real_write": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "detected_issue_summary": _issue_summary(readiness_status, blocking_conditions),
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
        "json_second_real_write_readiness_path": str(json_path),
        "html_second_real_write_readiness_path": str(html_path),
        "readiness_status": readiness_status,
        "readiness_package_only": True,
        "product_id": env_scope["product_id"],
        "locale": env_scope["locale"],
        "field": env_scope["field"],
        "current_backup_value_chars": len(backup_value),
        "proposed_value_chars": len(env_scope["proposed_value"]),
        "backup_source_verified": payload["backup_source_verified"],
        "read_only_backup_query_performed": payload["read_only_backup_query_performed"],
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "second_test_real_write_allowed": False,
        "human_approval_required_before_real_write": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
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
    elif field != ALLOWED_FIELD:
        errors.append("invalid_field")

    if not proposed_value:
        errors.append("missing_second_test_proposed_value")
        errors.append("empty_proposed_value")
    elif len(proposed_value) > prepare.MAX_PROPOSED_VALUE_CHARS:
        errors.append("proposed_value_too_long")
    return _unique(errors)


def _validate_prepare_report(report: dict) -> list[str]:
    errors = []
    if not report:
        return errors
    if report.get("task") != prepare.TASK_NAME or report.get("mode") != "second-single-field-test-prepare-only":
        errors.append("unsafe_second_test_prepare_report")
    if report.get("preparation_status") != READY_PREPARE_STATUS:
        errors.append("second_test_prepare_not_ready")
    if report.get("second_test_prepare_only") is not True:
        errors.append("unsafe_second_test_prepare_report")
    if report.get("second_test_real_write_allowed") is not False:
        errors.append("unsafe_second_test_prepare_report")
    for field in [
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "readback_performed",
        "rollback_performed",
        "real_apply_performed",
    ]:
        if report.get(field) is True:
            errors.append("unsafe_second_test_prepare_report")
    if report.get("no_new_shopify_writes_performed") is not True:
        errors.append("no_new_write_not_confirmed")
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
    for field in [
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "readback_performed",
        "rollback_performed",
        "real_apply_performed",
    ]:
        if report.get(field) is True:
            errors.append("unsafe_second_verified_backup_report")
    if report.get("second_test_real_write_allowed") is not False:
        errors.append("unsafe_second_verified_backup_report")
    if report.get("no_new_shopify_writes_performed") is not True:
        errors.append("no_new_write_not_confirmed")
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


def _backup_source_verified(report: dict) -> bool:
    return report.get("second_backup_source_verified") is True or report.get("second_backup_source_is_verified") is True


def _validated_scope(env_scope: dict, prepare_report: dict, backup_report: dict) -> dict:
    proposed_value = env_scope["proposed_value"]
    prepare_scope = prepare_report.get("requested_second_test_scope") or {}
    backup_scope = _backup_scope(backup_report) if backup_report else {}
    return {
        "product_count": 1 if prepare.PRODUCT_GID_RE.match(env_scope["product_id"]) else 0,
        "locale_count": 1 if env_scope["locale"] in prepare.ALLOWED_LOCALES else 0,
        "field_count": 1 if env_scope["field"] == ALLOWED_FIELD else 0,
        "field": env_scope["field"],
        "field_allowed": env_scope["field"] == ALLOWED_FIELD,
        "proposed_value_chars": len(proposed_value),
        "proposed_value_length_allowed": 0 < len(proposed_value) <= prepare.MAX_PROPOSED_VALUE_CHARS,
        "scope_matches_prepare_report": _scopes_equal(prepare_scope, env_scope),
        "scope_matches_verified_backup_report": _scopes_equal(backup_scope, env_scope),
        "allowed_field": ALLOWED_FIELD,
        "max_products": 1,
        "max_locales": 1,
        "max_fields": 1,
    }


def _source_status_summary(prepare_report: dict, backup_report: dict) -> dict:
    return {
        "second_test_prepare_status": prepare_report.get("preparation_status", "") if prepare_report else "",
        "second_verified_backup_status": backup_report.get("backup_fetch_status", "") if backup_report else "",
        "second_backup_source_is_verified": _backup_source_verified(backup_report) if backup_report else False,
        "read_only_shopify_query_performed": backup_report.get("read_only_shopify_query_performed") is True
        if backup_report
        else False,
    }


def _prepare_report_summary(report: dict) -> dict:
    return {
        "preparation_status": report.get("preparation_status", "") if report else "",
        "requested_second_test_scope": report.get("requested_second_test_scope", {}) if report else {},
        "second_test_prepare_only": report.get("second_test_prepare_only") is True if report else False,
        "second_test_real_write_allowed": report.get("second_test_real_write_allowed") is True if report else False,
    }


def _verified_backup_summary(report: dict) -> dict:
    return {
        "backup_fetch_status": report.get("backup_fetch_status", "") if report else "",
        "backup_source_verified": _backup_source_verified(report) if report else False,
        "read_only_shopify_query_performed": report.get("read_only_shopify_query_performed") is True if report else False,
        "current_backup_value": report.get("second_backup_value", "") if report else "",
        "current_backup_value_chars": int(report.get("second_backup_value_chars") or 0) if report else 0,
        "backup_locale": report.get("second_backup_locale", "") if report else "",
        "backup_field": report.get("second_backup_field", "") if report else "",
        "backup_product_id": report.get("second_backup_product_id", "") if report else "",
        "backup_generated_at": report.get("second_backup_generated_at", "") if report else "",
    }


def _human_approval_checklist(scope: dict, backup_value: str) -> list[str]:
    return [
        f"Confirm product_id is {scope['product_id']}.",
        f"Confirm locale is {scope['locale']}.",
        f"Confirm field is {ALLOWED_FIELD}.",
        f"Confirm current verified backup value is: {backup_value}",
        f"Confirm proposed value is: {scope['proposed_value']}",
        f"Confirm proposed value length is {len(scope['proposed_value'])} chars and <= 60.",
        "Confirm the next real-write task is a separate phase.",
        "Confirm the next real-write task must require an explicit dangerous flag and execution ack.",
        "Confirm the next real-write task must perform exactly one translationsRegister mutation.",
        "Confirm the next real-write task must immediately read back the same product / locale / field.",
        "Confirm rollback is not automatic and must be separately approved.",
    ]


def _second_real_write_requirements() -> list[str]:
    return [
        "Use a future independent real-write task only.",
        "Re-read this readiness package and the second verified backup report.",
        "Require explicit human approval before real write.",
        "Require a future dangerous flag and execution ack.",
        "Limit scope to exactly one product, one locale, one field=meta_title.",
        "Write only the prepared proposed value.",
        "Immediately read back the same product / locale / field after write.",
        "Mark failure if readback does not exactly match proposed value.",
        "Do not perform automatic rollback.",
    ]


def _forbidden_actions() -> list[str]:
    return [
        "Shopify API call in this phase",
        "Shopify write in this phase",
        "mutation in this phase",
        "translationsRegister in this phase",
        "readback in this phase",
        "rollback in this phase",
        "execution preview",
        "locked shell",
        "batch mode",
        "full-store scan",
        "multiple products",
        "multiple locales",
        "multiple fields",
        "git push",
    ]


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_second_test_prepare_report": "blocked_missing_second_test_prepare_report",
        "missing_second_verified_backup_report": "blocked_missing_second_verified_backup_report",
        "second_test_prepare_not_ready": "blocked_second_test_prepare_not_ready",
        "second_verified_backup_not_ready": "blocked_second_verified_backup_not_ready",
        "missing_second_test_product_id": "blocked_missing_second_test_scope",
        "missing_second_test_locale": "blocked_missing_second_test_scope",
        "missing_second_test_field": "blocked_missing_second_test_scope",
        "missing_second_test_proposed_value": "blocked_missing_second_test_scope",
        "prepare_scope_mismatch": "blocked_scope_mismatch",
        "backup_scope_mismatch": "blocked_scope_mismatch",
        "invalid_field": "blocked_invalid_field",
        "empty_proposed_value": "blocked_empty_proposed_value",
        "proposed_value_too_long": "blocked_proposed_value_too_long",
        "unverified_backup": "blocked_unverified_backup",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _readiness_status(blocking_conditions: list[str]) -> str:
    if not blocking_conditions:
        return READY_READINESS_STATUS
    for status in [
        "blocked_missing_second_test_prepare_report",
        "blocked_missing_second_verified_backup_report",
        "blocked_second_test_prepare_not_ready",
        "blocked_second_verified_backup_not_ready",
        "blocked_missing_second_test_scope",
        "blocked_invalid_field",
        "blocked_empty_proposed_value",
        "blocked_proposed_value_too_long",
        "blocked_unverified_backup",
        "blocked_scope_mismatch",
    ]:
        if status in blocking_conditions:
            return status
    return "blocked"


def _safety_summary() -> dict:
    return {
        "readiness_package_only": True,
        "shopify_api_call_allowed": False,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
        "second_test_real_write_allowed": False,
        "human_approval_required_before_real_write": True,
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
    READINESS_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(READINESS_JSON_PATH.read_text(encoding="utf-8"))
    return READINESS_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    READINESS_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return READINESS_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Readiness Status", "readiness_status"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Field", "field"),
            ("Current Backup Value", "current_backup_value"),
            ("Current Backup Value Chars", "current_backup_value_chars"),
            ("Proposed Value", "proposed_value"),
            ("Proposed Value Chars", "proposed_value_chars"),
            ("Backup Source Verified", "backup_source_verified"),
            ("Read-Only Backup Query Performed", "read_only_backup_query_performed"),
            ("Second Test Real Write Allowed", "second_test_real_write_allowed"),
            ("Human Approval Required Before Real Write", "human_approval_required_before_real_write"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Validated Scope", payload.get("validated_scope", {})),
            ("Source Status Summary", payload.get("source_status_summary", {})),
            ("Verified Backup Summary", payload.get("verified_backup_summary", {})),
            ("Human Approval Checklist", payload.get("human_approval_checklist", [])),
            ("Second Real Write Requirements", payload.get("second_real_write_requirements", [])),
            ("Forbidden Actions", payload.get("forbidden_actions", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Second Single-Field Real Write Readiness</title>
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
  <h1>Shopify Second Single-Field Real Write Readiness</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local reports and environment variables only.</li>
    <li>No Shopify API call, write, mutation, translationsRegister, readback, or rollback was performed.</li>
    <li>Only one product, one locale, and field=meta_title are accepted.</li>
    <li>A future real-write task must require separate human approval.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Second single-field real write readiness blocked: " + ", ".join(blocking_conditions)
    return "Second single-field real write readiness package generated. No Shopify action performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify second single-field real write readiness package generated.\n"
        f"Readiness status: {payload.get('readiness_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locale: {payload.get('locale')}\n"
        f"Field: {payload.get('field')}\n"
        f"Current backup value chars: {payload.get('current_backup_value_chars')}\n"
        f"Proposed value chars: {payload.get('proposed_value_chars')}\n"
        f"Backup source verified: {payload.get('backup_source_verified')}\n"
        f"Read-only backup query performed: {payload.get('read_only_backup_query_performed')}\n"
        f"Second test real write allowed: {payload.get('second_test_real_write_allowed')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Readiness JSON:\n"
        f"{json_path}\n\n"
        "Readiness HTML:\n"
        f"{html_path}\n"
        "Readiness package only. No Shopify API call, write, mutation, translationsRegister, readback, or rollback was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep readiness package files\n"
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
