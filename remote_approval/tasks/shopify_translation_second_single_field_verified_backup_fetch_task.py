import json
import os
import time
from html import escape
from pathlib import Path

from remote_approval.tasks import shopify_translation_second_single_field_test_prepare_task as prepare
from remote_approval.tasks import shopify_translation_single_field_backup_fetch_task as first_backup
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_second_single_field_verified_backup_fetch"
COMMAND_LABEL = "shopify_translation_second_single_field_verified_backup_fetch"
SOURCE_SECOND_TEST_PREPARE_PATH = LOG_DIR / "shopify_translation_second_single_field_test_prepare.json"
SECOND_VERIFIED_BACKUP_JSON_PATH = LOG_DIR / "shopify_translation_second_single_field_verified_backup_fetch.json"
SECOND_VERIFIED_BACKUP_HTML_PATH = LOG_DIR / "shopify_translation_second_single_field_verified_backup_fetch.html"

READY_PREPARE_STATUS = "second_single_field_test_prepare_ready_for_manual_review"
ALLOWED_FIELD = "meta_title"


def run_shopify_translation_second_single_field_verified_backup_fetch_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    prepare_report = {}

    try:
        prepare_report = _read_json(SOURCE_SECOND_TEST_PREPARE_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Second test prepare JSON not found: {exc}")
        validation_errors.append("missing_second_test_prepare_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse second test prepare JSON: {exc}")
        validation_errors.append("second_test_prepare_json_invalid")

    env_scope = _read_second_test_scope()
    validation_errors.extend(_validate_env_scope(env_scope))
    validation_errors.extend(_validate_prepare_report(prepare_report))
    if prepare_report:
        validation_errors.extend(_validate_scope_match(prepare_report, env_scope))

    blocking_conditions = _blocking_conditions(validation_errors)
    query_result = _empty_query_result(env_scope)
    if not blocking_conditions:
        query_result = first_backup._fetch_backup_from_shopify(
            {
                "product_id": env_scope["product_id"],
                "locale": env_scope["locale"],
                "field": env_scope["field"],
            }
        )
        if not query_result.get("success"):
            validation_errors.append("backup_query_failed")
            blocking_conditions = _blocking_conditions(validation_errors)

    backup_fetch_status = _backup_fetch_status(blocking_conditions)
    second_backup_value = str(query_result.get("backup_value") or "")
    read_only_performed = bool(query_result.get("read_only_shopify_query_performed"))
    second_backup_source_is_verified = backup_fetch_status == "second_verified_backup_ready" and read_only_performed
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "second-verified-backup-fetch-read-only",
        "command_label": COMMAND_LABEL,
        "source_second_test_prepare_path": str(SOURCE_SECOND_TEST_PREPARE_PATH),
        "json_second_verified_backup_path": str(SECOND_VERIFIED_BACKUP_JSON_PATH),
        "html_second_verified_backup_path": str(SECOND_VERIFIED_BACKUP_HTML_PATH),
        "success": backup_fetch_status == "second_verified_backup_ready",
        "backup_fetch_status": backup_fetch_status,
        "requested_second_test_scope": env_scope,
        "source_prepare_scope": (prepare_report.get("requested_second_test_scope") or {}) if prepare_report else {},
        "validated_second_test_scope": _validated_scope(
            env_scope,
            _scopes_match(prepare_report.get("requested_second_test_scope") or {}, env_scope)
            if prepare_report
            else False,
        ),
        "source_second_test_prepare_status": prepare_report.get("preparation_status", "") if prepare_report else "",
        "read_only_shopify_query_performed": read_only_performed,
        "shopify_query_type": "GraphQL translatableResource read-only query" if read_only_performed else "",
        "shopify_http_status": query_result.get("http_status"),
        "second_backup_source_is_verified": second_backup_source_is_verified,
        "second_backup_value": second_backup_value,
        "second_backup_value_chars": len(second_backup_value),
        "second_backup_value_present": bool(query_result.get("backup_value_present")),
        "second_backup_value_source": query_result.get("backup_value_source", ""),
        "second_backup_locale": env_scope.get("locale", ""),
        "second_backup_field": env_scope.get("field", ""),
        "second_backup_product_id": env_scope.get("product_id", ""),
        "second_backup_generated_at": end_time,
        "second_test_proposed_value": env_scope.get("proposed_value", ""),
        "second_test_proposed_value_chars": len(env_scope.get("proposed_value", "")),
        "safety_summary": _safety_summary(read_only_performed),
        "blocking_conditions": blocking_conditions,
        "second_test_real_write_allowed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "translations_register_performed": False,
        "rollback_performed": False,
        "readback_performed": False,
        "real_apply_performed": False,
        "shopify_mutations_called": [],
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "query_failure_type": query_result.get("failure_type", ""),
        "query_error": query_result.get("error", "") or query_result.get("failure_reason", ""),
        "stdout_tail": query_result.get("stdout_tail", ""),
        "stderr_tail": query_result.get("stderr_tail", ""),
        "detected_issue_summary": _issue_summary(backup_fetch_status, blocking_conditions),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
    }
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_second_verified_backup_path": str(json_path),
        "html_second_verified_backup_path": str(html_path),
        "backup_fetch_status": backup_fetch_status,
        "source_second_test_prepare_status": payload["source_second_test_prepare_status"],
        "second_backup_source_is_verified": second_backup_source_is_verified,
        "second_backup_value_present": payload["second_backup_value_present"],
        "second_backup_value_chars": len(second_backup_value),
        "second_backup_locale": env_scope.get("locale", ""),
        "second_backup_field": env_scope.get("field", ""),
        "second_backup_product_id": env_scope.get("product_id", ""),
        "read_only_shopify_query_performed": read_only_performed,
        "shopify_query_type": payload["shopify_query_type"],
        "second_test_real_write_allowed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "readback_performed": False,
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
    if not scope["product_id"]:
        errors.append("missing_second_test_product_id")
    elif "," in scope["product_id"] or ";" in scope["product_id"]:
        errors.append("multiple_products_detected")
    elif not prepare.PRODUCT_GID_RE.match(scope["product_id"]):
        errors.append("invalid_product_id")

    if not scope["locale"]:
        errors.append("missing_second_test_locale")
    elif "," in scope["locale"] or ";" in scope["locale"]:
        errors.append("multiple_locales_detected")
    elif scope["locale"] not in prepare.ALLOWED_LOCALES:
        errors.append("invalid_locale")

    if not scope["field"]:
        errors.append("missing_second_test_field")
    elif "," in scope["field"] or ";" in scope["field"]:
        errors.append("multiple_fields_detected")
    elif scope["field"] != ALLOWED_FIELD:
        errors.append("invalid_field")

    if not scope["proposed_value"]:
        errors.append("missing_second_test_proposed_value")
    elif len(scope["proposed_value"]) > prepare.MAX_PROPOSED_VALUE_CHARS:
        errors.append("proposed_value_over_60_chars")
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


def _validate_scope_match(report: dict, env_scope: dict) -> list[str]:
    errors = []
    report_scope = report.get("requested_second_test_scope") or {}
    for key in ["product_id", "locale", "field", "proposed_value"]:
        if report_scope.get(key) != env_scope.get(key):
            errors.append("scope_mismatch")
    return _unique(errors)


def _validated_scope(scope: dict, scope_matches_prepare: bool) -> dict:
    proposed_value = scope.get("proposed_value", "")
    return {
        "product_count": 1 if prepare.PRODUCT_GID_RE.match(scope.get("product_id", "")) else 0,
        "locale_count": 1 if scope.get("locale") in prepare.ALLOWED_LOCALES else 0,
        "field_count": 1 if scope.get("field") == ALLOWED_FIELD else 0,
        "field": scope.get("field", ""),
        "field_allowed": scope.get("field") == ALLOWED_FIELD,
        "scope_matches_prepare": scope_matches_prepare,
        "proposed_value_chars": len(proposed_value),
        "proposed_value_length_allowed": 0 < len(proposed_value) <= prepare.MAX_PROPOSED_VALUE_CHARS,
        "allowed_field": ALLOWED_FIELD,
    }


def _scopes_match(report_scope: dict, env_scope: dict) -> bool:
    return all(report_scope.get(key) == env_scope.get(key) for key in ["product_id", "locale", "field", "proposed_value"])


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_second_test_prepare_report": "blocked_missing_second_test_prepare_report",
        "second_test_prepare_not_ready": "blocked_second_test_prepare_not_ready",
        "missing_second_test_product_id": "blocked_missing_second_test_scope",
        "missing_second_test_locale": "blocked_missing_second_test_scope",
        "missing_second_test_field": "blocked_missing_second_test_scope",
        "missing_second_test_proposed_value": "blocked_missing_second_test_scope",
        "scope_mismatch": "blocked_scope_mismatch",
        "invalid_field": "blocked_invalid_field",
        "backup_query_failed": "blocked_backup_query_failed",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _backup_fetch_status(blocking_conditions: list[str]) -> str:
    if not blocking_conditions:
        return "second_verified_backup_ready"
    for status in [
        "blocked_missing_second_test_prepare_report",
        "blocked_second_test_prepare_not_ready",
        "blocked_missing_second_test_scope",
        "blocked_invalid_field",
        "blocked_scope_mismatch",
        "blocked_backup_query_failed",
    ]:
        if status in blocking_conditions:
            return status
    return "blocked"


def _empty_query_result(scope: dict) -> dict:
    return {
        "success": False,
        "read_only_shopify_query_performed": False,
        "backup_product_id": scope.get("product_id", ""),
        "backup_locale": scope.get("locale", ""),
        "backup_field": scope.get("field", ""),
        "backup_value": "",
        "backup_value_present": False,
        "backup_value_source": "missing",
        "http_status": None,
        "failure_type": "",
        "error": "",
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _safety_summary(read_only_performed: bool) -> dict:
    return {
        "read_only_shopify_query_allowed": True,
        "read_only_shopify_query_performed": read_only_performed,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "rollback_allowed": False,
        "readback_allowed_in_this_phase": False,
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
    SECOND_VERIFIED_BACKUP_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SECOND_VERIFIED_BACKUP_JSON_PATH.read_text(encoding="utf-8"))
    return SECOND_VERIFIED_BACKUP_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SECOND_VERIFIED_BACKUP_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SECOND_VERIFIED_BACKUP_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Backup Fetch Status", "backup_fetch_status"),
            ("Requested Second Test Scope", "requested_second_test_scope"),
            ("Source Prepare Scope", "source_prepare_scope"),
            ("Validated Second Test Scope", "validated_second_test_scope"),
            ("Read-Only Shopify Query Performed", "read_only_shopify_query_performed"),
            ("Second Backup Source Is Verified", "second_backup_source_is_verified"),
            ("Second Backup Value", "second_backup_value"),
            ("Second Backup Value Chars", "second_backup_value_chars"),
            ("Second Test Real Write Allowed", "second_test_real_write_allowed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
            ("Query Failure Type", payload.get("query_failure_type", "")),
            ("Query Error", payload.get("query_error", "")),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Second Single-Field Verified Backup Fetch</title>
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
  <h1>Shopify Second Single-Field Verified Backup Fetch</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task may perform one read-only Shopify GraphQL query.</li>
    <li>No Shopify write, mutation, translationsRegister, rollback, or readback was performed.</li>
    <li>The scope must match the Phase 12.4 preparation package exactly.</li>
    <li>Only field=meta_title is allowed.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Second single-field verified backup fetch blocked: " + ", ".join(blocking_conditions)
    return "Second single-field verified backup fetch completed with read-only Shopify query. No writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify second single-field verified backup fetch report generated.\n"
        f"Backup fetch status: {payload.get('backup_fetch_status')}\n"
        f"Requested second test scope: {payload.get('requested_second_test_scope')}\n"
        f"Read-only Shopify query performed: {payload.get('read_only_shopify_query_performed')}\n"
        f"Second backup source verified: {payload.get('second_backup_source_is_verified')}\n"
        f"Second backup value chars: {payload.get('second_backup_value_chars')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Second verified backup JSON:\n"
        f"{json_path}\n\n"
        "Second verified backup HTML:\n"
        f"{html_path}\n"
        "Read-only backup fetch only. No Shopify write, mutation, translationsRegister, rollback, or readback was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep second verified backup files\n"
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
