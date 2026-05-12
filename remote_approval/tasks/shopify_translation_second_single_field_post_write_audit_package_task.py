import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_second_single_field_post_write_audit_package"
COMMAND_LABEL = "shopify_translation_second_single_field_post_write_audit_package"
SOURCE_SECOND_EXECUTE_PATH = LOG_DIR / "shopify_translation_second_single_field_real_write_execute.json"
SOURCE_SECOND_VERIFIED_BACKUP_PATH = LOG_DIR / "shopify_translation_second_single_field_verified_backup_fetch.json"
SOURCE_SECOND_READINESS_PATH = LOG_DIR / "shopify_translation_second_single_field_real_write_readiness.json"
SECOND_POST_WRITE_AUDIT_JSON_PATH = LOG_DIR / "shopify_translation_second_single_field_post_write_audit_package.json"
SECOND_POST_WRITE_AUDIT_HTML_PATH = LOG_DIR / "shopify_translation_second_single_field_post_write_audit_package.html"

EXPECTED_EXECUTION_TASK = "shopify_translation_second_single_field_real_write_execute"
EXPECTED_EXECUTION_STATUS = "second_real_write_succeeded_and_verified"
EXPECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
EXPECTED_LOCALE = "ja"
EXPECTED_FIELD = "meta_title"
EXPECTED_PROPOSED_VALUE = "MOFLY P-51D Aileron Link Connector Test"
EXPECTED_BACKUP_VALUE = "MOFLY P-51D Aileron Link Connector"


def run_shopify_translation_second_single_field_post_write_audit_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    execution_report = {}
    backup_report = {}
    readiness_report = {}

    try:
        execution_report = _read_json(SOURCE_SECOND_EXECUTE_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Second real write execution JSON not found: {exc}")
        validation_errors.append("missing_second_real_write_execution_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse second real write execution JSON: {exc}")
        validation_errors.append("second_real_write_execution_json_invalid")

    try:
        backup_report = _read_json(SOURCE_SECOND_VERIFIED_BACKUP_PATH)
    except FileNotFoundError:
        backup_report = {}
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse optional second verified backup JSON: {exc}")
        validation_errors.append("second_verified_backup_json_invalid")

    try:
        readiness_report = _read_json(SOURCE_SECOND_READINESS_PATH)
    except FileNotFoundError:
        readiness_report = {}
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse optional second readiness JSON: {exc}")
        validation_errors.append("second_readiness_json_invalid")

    if execution_report:
        validation_errors.extend(_validate_execution_report(execution_report))

    source_summary = _source_execution_report_summary(execution_report)
    audited_scope = _audited_scope(execution_report)
    backup_summary = _backup_summary(execution_report, backup_report)
    write_summary = _write_summary(execution_report)
    readback_summary = _readback_summary(execution_report)
    verification_summary = _verification_summary(execution_report)
    rollback_summary = _rollback_summary(execution_report, verification_summary)
    blocking_conditions = _blocking_conditions(validation_errors, source_summary)
    audit_status = _audit_status(blocking_conditions, execution_report)
    success = audit_status == "second_post_write_audit_passed"
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "second-post-write-audit-only",
        "command_label": COMMAND_LABEL,
        "source_second_real_write_execution_path": str(SOURCE_SECOND_EXECUTE_PATH),
        "source_second_verified_backup_path": str(SOURCE_SECOND_VERIFIED_BACKUP_PATH),
        "source_second_readiness_path": str(SOURCE_SECOND_READINESS_PATH),
        "json_second_post_write_audit_package_path": str(SECOND_POST_WRITE_AUDIT_JSON_PATH),
        "html_second_post_write_audit_package_path": str(SECOND_POST_WRITE_AUDIT_HTML_PATH),
        "success": success,
        "audit_status": audit_status,
        "product_id": audited_scope["product_id"],
        "locale": audited_scope["locale"],
        "field": audited_scope["field"],
        "backup_value_before_second_write": backup_summary["backup_value"],
        "final_value_after_second_write": readback_summary["readback_value"],
        "proposed_value": write_summary["proposed_value"],
        "readback_matches_proposed_value": readback_summary["readback_matches_proposed_value"],
        "rollback_needed": rollback_summary["rollback_needed"],
        "rollback_optional_restore_possible": rollback_summary["rollback_optional_restore_possible"],
        "rollback_optional_restore_requires_separate_approval": (
            rollback_summary["rollback_optional_restore_requires_separate_approval"]
        ),
        "audited_scope": audited_scope,
        "source_execution_report_summary": source_summary,
        "backup_summary": backup_summary,
        "write_summary": write_summary,
        "readback_summary": readback_summary,
        "verification_summary": verification_summary,
        "rollback_summary": rollback_summary,
        "safety_summary": _safety_summary(source_summary),
        "post_write_observations": _post_write_observations(),
        "next_phase_recommendations": _next_phase_recommendations(),
        "source_optional_report_summary": _optional_report_summary(backup_report, readiness_report),
        "blocking_conditions": blocking_conditions,
        "audit_package_only": True,
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
        "validation_failures": _unique(validation_errors),
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
        "json_second_post_write_audit_package_path": str(json_path),
        "html_second_post_write_audit_package_path": str(html_path),
        "audit_status": audit_status,
        "audit_package_only": True,
        "source_execution_status": source_summary["source_execution_status"],
        "source_shopify_write_performed": source_summary["source_shopify_write_performed"],
        "source_translations_register_called": source_summary["source_translations_register_called"],
        "source_mutation_performed": source_summary["source_mutation_performed"],
        "source_readback_performed": source_summary["source_readback_performed"],
        "source_real_write_count": source_summary["source_real_write_count"],
        "readback_matches_proposed_value": readback_summary["readback_matches_proposed_value"],
        "audit_verification_passed": verification_summary["audit_verification_passed"],
        "rollback_needed": rollback_summary["rollback_needed"],
        "rollback_optional_restore_possible": rollback_summary["rollback_optional_restore_possible"],
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


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_execution_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_EXECUTION_TASK:
        errors.append("source_task_mismatch")
    if report.get("mode") != "real-run":
        errors.append("source_mode_not_real_run")
    if report.get("execution_status") != EXPECTED_EXECUTION_STATUS:
        errors.append("second_real_write_not_successful")
    if report.get("translations_register_called") is not True:
        errors.append("source_translations_register_not_called")
    if report.get("shopify_write_performed") is not True:
        errors.append("source_shopify_write_not_performed")
    if report.get("mutation_performed") is not True:
        errors.append("source_mutation_not_performed")
    if report.get("readback_performed") is not True:
        errors.append("source_readback_not_performed")
    if report.get("readback_matches_proposed_value") is not True:
        errors.append("second_real_write_readback_mismatch")
    if report.get("rollback_approval_required") is not False:
        errors.append("second_real_write_requires_rollback_review")
    if report.get("blocking_conditions") not in ([], None):
        errors.append("source_has_blocking_conditions")
    if int(report.get("real_write_count") or 0) != 1:
        errors.append("unexpected_write_count")
    if report.get("bulk_write_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("publish_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("automatic_rollback_performed") is not False:
        errors.append("unexpected_side_effects")

    scope = report.get("requested_scope") or {}
    errors.extend(_validate_fixed_scope(scope))
    proposed_change = report.get("proposed_change") or {}
    if proposed_change.get("proposed_value") != EXPECTED_PROPOSED_VALUE:
        errors.append("scope_mismatch")

    backup = report.get("verified_backup_summary") or {}
    if str(backup.get("backup_value") or "") != EXPECTED_BACKUP_VALUE:
        errors.append("scope_mismatch")

    readback = report.get("readback_summary") or {}
    if str(readback.get("readback_value") or "") != EXPECTED_PROPOSED_VALUE:
        errors.append("second_real_write_readback_mismatch")
    readback_scope = readback.get("readback_scope") or {}
    errors.extend(_validate_fixed_scope({**readback_scope, "proposed_value": EXPECTED_PROPOSED_VALUE}))
    return _unique(errors)


def _validate_fixed_scope(scope: dict) -> list[str]:
    errors = []
    if scope.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.append("scope_mismatch")
    if scope.get("locale") != EXPECTED_LOCALE:
        errors.append("scope_mismatch")
    if scope.get("field") != EXPECTED_FIELD:
        errors.append("scope_mismatch")
    if scope.get("proposed_value", EXPECTED_PROPOSED_VALUE) != EXPECTED_PROPOSED_VALUE:
        errors.append("scope_mismatch")
    return _unique(errors)


def _source_execution_report_summary(report: dict) -> dict:
    return {
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_task": report.get("task", "") if report else "",
        "source_mode": report.get("mode", "") if report else "",
        "source_product_id": (report.get("requested_scope") or {}).get("product_id", "") if report else "",
        "source_locale": (report.get("requested_scope") or {}).get("locale", "") if report else "",
        "source_field": (report.get("requested_scope") or {}).get("field", "") if report else "",
        "source_proposed_value": (report.get("proposed_change") or report.get("requested_scope") or {}).get(
            "proposed_value", ""
        )
        if report
        else "",
        "source_shopify_api_call_performed": bool(report.get("shopify_api_call_performed")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "source_readback_matches_proposed_value": bool(report.get("readback_matches_proposed_value")) if report else False,
        "source_rollback_approval_required": bool(report.get("rollback_approval_required")) if report else False,
        "source_rollback_performed": bool(report.get("rollback_performed")) if report else False,
        "source_automatic_rollback_performed": bool(report.get("automatic_rollback_performed")) if report else False,
        "source_real_write_count": int(report.get("real_write_count") or 0) if report else 0,
        "source_bulk_write_performed": bool(report.get("bulk_write_performed")) if report else False,
        "source_publish_performed": bool(report.get("publish_performed")) if report else False,
        "source_blocking_conditions": report.get("blocking_conditions", []) if report else [],
    }


def _audited_scope(report: dict) -> dict:
    scope = report.get("requested_scope") or {}
    return {
        "product_id": scope.get("product_id", ""),
        "locale": scope.get("locale", ""),
        "field": scope.get("field", ""),
    }


def _backup_summary(execution_report: dict, backup_report: dict) -> dict:
    source_backup = execution_report.get("verified_backup_summary") or {}
    value = str(source_backup.get("backup_value") or backup_report.get("second_backup_value") or "")
    return {
        "backup_value_before_second_write": value,
        "backup_value": value,
        "backup_value_chars": len(value),
        "backup_source_verified": bool(source_backup.get("backup_source_verified") or backup_report.get("second_backup_source_is_verified")),
        "read_only_shopify_query_performed": bool(
            source_backup.get("read_only_shopify_query_performed") or backup_report.get("read_only_shopify_query_performed")
        ),
        "backup_locale": source_backup.get("backup_locale") or backup_report.get("second_backup_locale", ""),
        "backup_field": source_backup.get("backup_field") or backup_report.get("second_backup_field", ""),
        "backup_product_id": source_backup.get("backup_product_id") or backup_report.get("second_backup_product_id", ""),
    }


def _write_summary(report: dict) -> dict:
    proposed_value = str((report.get("proposed_change") or report.get("requested_scope") or {}).get("proposed_value") or "")
    return {
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "written_value": proposed_value,
        "proposed_value": proposed_value,
        "write_scope_limited": bool(report.get("second_real_write_scope_limited")) if report else False,
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
    proposed_value = str(verification.get("proposed_value") or EXPECTED_PROPOSED_VALUE)
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
    rollback_needed = not bool(verification_summary.get("audit_verification_passed"))
    return {
        "rollback_approval_required": bool(report.get("rollback_approval_required")) if report else False,
        "rollback_performed": bool(report.get("rollback_performed")) if report else False,
        "automatic_rollback_performed": bool(report.get("automatic_rollback_performed")) if report else False,
        "rollback_needed": rollback_needed,
        "rollback_optional_restore_possible": True,
        "rollback_optional_restore_requires_separate_approval": True,
        "rollback_note": (
            "No rollback required because readback matched proposed value."
            if not rollback_needed
            else "Rollback approval package is required before any rollback action."
        ),
        "verified_backup_value": EXPECTED_BACKUP_VALUE,
    }


def _optional_report_summary(backup_report: dict, readiness_report: dict) -> dict:
    return {
        "backup_report_loaded": bool(backup_report),
        "backup_fetch_status": backup_report.get("backup_fetch_status", "") if backup_report else "",
        "readiness_report_loaded": bool(readiness_report),
        "readiness_status": readiness_report.get("readiness_status", "") if readiness_report else "",
    }


def _blocking_conditions(validation_errors: list[str], source_summary: dict) -> list[str]:
    mapping = {
        "missing_second_real_write_execution_report": "blocked_missing_second_real_write_execution_report",
        "second_real_write_not_successful": "blocked_second_real_write_not_successful",
        "second_real_write_readback_mismatch": "blocked_second_real_write_readback_mismatch",
        "second_real_write_requires_rollback_review": "blocked_second_real_write_requires_rollback_review",
        "scope_mismatch": "blocked_scope_mismatch",
        "unexpected_write_count": "blocked_unexpected_write_count",
        "unexpected_side_effects": "blocked_unexpected_side_effects",
    }
    conditions = [mapping.get(error, error) for error in validation_errors]
    if source_summary["source_real_write_count"] not in {0, 1}:
        conditions.append("blocked_unexpected_write_count")
    return _unique(conditions)


def _audit_status(blocking_conditions: list[str], execution_report: dict) -> str:
    if not execution_report:
        return "blocked_missing_second_real_write_execution_report"
    if not blocking_conditions:
        return "second_post_write_audit_passed"
    return "second_post_write_audit_failed"


def _safety_summary(source_summary: dict) -> dict:
    return {
        "audit_package_only": True,
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
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _post_write_observations() -> list[str]:
    return [
        "The second real single-field Shopify translation write succeeded.",
        "The write scope remained one product, one locale, and field=meta_title.",
        "Immediate readback matched the proposed value.",
        "No rollback was required.",
        "No automatic rollback was performed.",
    ]


def _next_phase_recommendations() -> list[str]:
    return [
        "Generate a second rollback approval package / restore plan if an optional restore is desired.",
        "Do not start a third write without a fresh backup and explicit approval chain.",
        "Do not expand directly to batch yet.",
        "Keep future tests at 1 product x 1 locale x 1 field until several one-shot writes are audited.",
    ]


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SECOND_POST_WRITE_AUDIT_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SECOND_POST_WRITE_AUDIT_JSON_PATH.read_text(encoding="utf-8"))
    return SECOND_POST_WRITE_AUDIT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SECOND_POST_WRITE_AUDIT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SECOND_POST_WRITE_AUDIT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Audit Status", "audit_status"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Field", "field"),
            ("Backup Value Before Second Write", "backup_value_before_second_write"),
            ("Final Value After Second Write", "final_value_after_second_write"),
            ("Proposed Value", "proposed_value"),
            ("Readback Matches Proposed Value", "readback_matches_proposed_value"),
            ("Rollback Needed", "rollback_needed"),
            ("Rollback Optional Restore Possible", "rollback_optional_restore_possible"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Source Execution Report Summary", payload.get("source_execution_report_summary", {})),
            ("Backup Summary", payload.get("backup_summary", {})),
            ("Write Summary", payload.get("write_summary", {})),
            ("Readback Summary", payload.get("readback_summary", {})),
            ("Verification Summary", payload.get("verification_summary", {})),
            ("Rollback Summary", payload.get("rollback_summary", {})),
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
  <title>Shopify Second Single-Field Post-Write Audit Package</title>
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
  <h1>Shopify Second Single-Field Post-Write Audit Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Audit Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local JSON reports only.</li>
    <li>No new Shopify API call, write, mutation, translationsRegister, readback, or rollback was performed.</li>
    <li>The source execution report is allowed to record the prior Phase 12.7 real write facts.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(audit_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Second single-field post-write audit blocked: " + ", ".join(blocking_conditions)
    return f"Second single-field post-write audit completed with status {audit_status}. No new Shopify actions performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify second single-field post-write audit package generated.\n"
        f"Audit status: {payload.get('audit_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locale: {payload.get('locale')}\n"
        f"Field: {payload.get('field')}\n"
        f"Source execution status: {payload.get('source_execution_report_summary', {}).get('source_execution_status')}\n"
        f"Source Shopify write performed: {payload.get('source_execution_report_summary', {}).get('source_shopify_write_performed')}\n"
        f"Source translationsRegister called: {payload.get('source_execution_report_summary', {}).get('source_translations_register_called')}\n"
        f"Rollback needed: {payload.get('rollback_needed')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Second post-write audit JSON:\n"
        f"{json_path}\n\n"
        "Second post-write audit HTML:\n"
        f"{html_path}\n"
        "Audit package only. No Shopify API call, mutation, translationsRegister, readback, rollback, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep second post-write audit files\n"
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
