import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_readback_rollback_plan"
COMMAND_LABEL = "shopify_translation_single_field_readback_rollback_plan"
SOURCE_PREFLIGHT_PACKAGE_PATH = LOG_DIR / "shopify_translation_single_field_apply_preflight_package.json"
SOURCE_BACKUP_FETCH_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
READBACK_ROLLBACK_PLAN_JSON_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.json"
READBACK_ROLLBACK_PLAN_HTML_PATH = LOG_DIR / "shopify_translation_single_field_readback_rollback_plan.html"
EXPECTED_PREFLIGHT_TASK = "shopify_translation_single_field_apply_preflight_package"
EXPECTED_PREFLIGHT_MODE = "single-field-preflight-only"
EXPECTED_BACKUP_TASK = "shopify_translation_single_field_backup_fetch"
EXPECTED_BACKUP_MODE = "read-only-backup-fetch"
ALLOWED_FIELD = "meta_title"
ALLOWED_LOCALES = {"de", "fr", "es", "it", "ja"}
SAFE_BACKUP_STATUSES = {"completed", "backup_ready", "ready_for_manual_review", "blocked_with_no_write", "blocked"}
MAX_PROPOSED_VALUE_CHARS = 60
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/[0-9]+$")


def run_shopify_translation_single_field_readback_rollback_plan_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_errors = []
    preflight_package = {}
    backup_fetch = {}

    try:
        preflight_package = _read_json(SOURCE_PREFLIGHT_PACKAGE_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Preflight package JSON not found: {exc}")
        validation_errors.append("missing_preflight_package")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse preflight package JSON: {exc}")
        validation_errors.append("preflight_package_json_invalid")

    try:
        backup_fetch = _read_json(SOURCE_BACKUP_FETCH_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Backup fetch JSON not found: {exc}")
        validation_errors.append("missing_backup_fetch_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse backup fetch JSON: {exc}")
        validation_errors.append("backup_fetch_json_invalid")

    if preflight_package:
        preflight_errors, preflight_warnings = _validate_preflight_package(preflight_package)
        validation_errors.extend(preflight_errors)
        validation_warnings.extend(preflight_warnings)
    if backup_fetch:
        backup_errors, backup_warnings = _validate_backup_fetch(backup_fetch)
        validation_errors.extend(backup_errors)
        validation_warnings.extend(backup_warnings)
    if preflight_package and backup_fetch:
        validation_errors.extend(_validate_scope_match(preflight_package, backup_fetch))

    requested_scope = _requested_scope(preflight_package, backup_fetch)
    proposed_value = str((preflight_package.get("requested_scope") or {}).get("proposed_value") or "")
    backup_summary = _backup_summary(backup_fetch)
    backup_completeness = _backup_completeness(backup_fetch)
    blocking_conditions = _blocking_conditions(validation_errors, proposed_value, backup_completeness)
    plan_status = _plan_status(validation_errors, backup_completeness)
    success = not _hard_failures(validation_errors)
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "readback-rollback-plan-only",
        "command_label": COMMAND_LABEL,
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "source_backup_fetch_path": str(SOURCE_BACKUP_FETCH_PATH),
        "json_readback_rollback_plan_path": str(READBACK_ROLLBACK_PLAN_JSON_PATH),
        "html_readback_rollback_plan_path": str(READBACK_ROLLBACK_PLAN_HTML_PATH),
        "success": success,
        "plan_status": plan_status,
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if _valid_product_id(requested_scope.get("product_id", "")) else 0,
            "locale_count": 1 if requested_scope.get("locale") in ALLOWED_LOCALES else 0,
            "field_count": 1 if requested_scope.get("field") == ALLOWED_FIELD else 0,
            "field_allowed": requested_scope.get("field") == ALLOWED_FIELD,
            "scope_matches_preflight_and_backup": "scope_mismatch" not in validation_errors,
            "allowed_field": ALLOWED_FIELD,
            "allowed_locales": sorted(ALLOWED_LOCALES),
        },
        "source_preflight_status": preflight_package.get("preflight_status", "") if preflight_package else "",
        "source_backup_fetch_status": backup_fetch.get("backup_fetch_status", "") if backup_fetch else "",
        "proposed_change": {
            "product_id": requested_scope.get("product_id", ""),
            "locale": requested_scope.get("locale", ""),
            "field": requested_scope.get("field", ""),
            "proposed_value": proposed_value,
            "proposed_value_chars": len(proposed_value),
            "proposed_value_length_allowed": 0 < len(proposed_value) <= MAX_PROPOSED_VALUE_CHARS,
        },
        "backup_summary": backup_summary,
        "backup_completeness": backup_completeness,
        "readback_plan": _readback_plan(requested_scope, proposed_value),
        "rollback_plan": _rollback_plan(requested_scope, backup_summary, backup_completeness),
        "write_preconditions": _write_preconditions(
            preflight_package,
            requested_scope,
            proposed_value,
            backup_completeness,
            validation_errors,
        ),
        "blocking_conditions": blocking_conditions,
        "future_manual_checklist": _future_manual_checklist(),
        "safety_summary": _safety_summary(),
        "future_required_flag": "--i-understand-this-writes-shopify",
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
        "detected_issue_summary": _issue_summary(plan_status, validation_errors, backup_completeness),
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
        "json_readback_rollback_plan_path": str(json_path),
        "html_readback_rollback_plan_path": str(html_path),
        "plan_status": plan_status,
        "backup_source_is_verified": backup_completeness["backup_source_is_verified"],
        "source_preflight_status": payload["source_preflight_status"],
        "source_backup_fetch_status": payload["source_backup_fetch_status"],
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


def _validate_preflight_package(report: dict) -> tuple[list[str], list[str]]:
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
        warnings.append("source preflight names a future mutation text; no mutation was performed")
    return _unique(errors), _unique(warnings)


def _validate_backup_fetch(report: dict) -> tuple[list[str], list[str]]:
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
    if report.get("shopify_api_call_performed") is True:
        errors.append("source_report_indicates_shopify_api_call")
    if report.get("mutation_performed") is True:
        errors.append("source_report_indicates_mutation")
    if report.get("shopify_mutations_called") not in ([], None):
        errors.append("source_report_indicates_mutation")
    if report.get("read_only_shopify_query_performed") is not True:
        warnings.append("backup_source_not_verified")
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


def _validate_scope_match(preflight: dict, backup: dict) -> list[str]:
    errors = []
    preflight_scope = preflight.get("requested_scope") or {}
    backup_scope = {
        "product_id": backup.get("backup_product_id") or (backup.get("requested_scope") or {}).get("product_id", ""),
        "locale": backup.get("backup_locale") or (backup.get("requested_scope") or {}).get("locale", ""),
        "field": backup.get("backup_field") or (backup.get("requested_scope") or {}).get("field", ""),
    }
    for key in ["product_id", "locale", "field"]:
        if preflight_scope.get(key) != backup_scope.get(key):
            errors.append("scope_mismatch")
    return _unique(errors)


def _validate_no_write_flags(report: dict, source_name: str) -> list[str]:
    errors = []
    unsafe_false_fields = [
        "shopify_write_performed",
        "apply_performed",
        "publish_performed",
        "translations_register_performed",
        "translations_register_called",
        "command_executed",
        "mutation_performed",
    ]
    for field in unsafe_false_fields:
        if report.get(field) is True:
            errors.append(f"{source_name}_report_indicates_write_or_mutation")
    if report.get("real_write_allowed") is True:
        errors.append(f"{source_name}_report_indicates_write_or_mutation")
    if report.get("translations_register_allowed") is True:
        errors.append(f"{source_name}_report_indicates_write_or_mutation")
    if report.get("no_shopify_writes_performed") is not True:
        errors.append("no_write_not_confirmed")
    if report.get("all_no_write_confirmed") is not True:
        errors.append("no_write_not_confirmed")
    return _unique(errors)


def _requested_scope(preflight: dict, backup: dict) -> dict:
    preflight_scope = preflight.get("requested_scope") or {}
    backup_scope = backup.get("requested_scope") or {}
    return {
        "product_id": preflight_scope.get("product_id") or backup.get("backup_product_id") or backup_scope.get("product_id", ""),
        "locale": preflight_scope.get("locale") or backup.get("backup_locale") or backup_scope.get("locale", ""),
        "field": preflight_scope.get("field") or backup.get("backup_field") or backup_scope.get("field", ""),
    }


def _backup_summary(backup: dict) -> dict:
    value = "" if not backup else str(backup.get("backup_value") or "")
    return {
        "backup_value_present": bool(backup.get("backup_value_present")) if backup else False,
        "backup_value": value,
        "backup_value_chars": len(value),
        "backup_locale": backup.get("backup_locale", "") if backup else "",
        "backup_field": backup.get("backup_field", "") if backup else "",
        "backup_product_id": backup.get("backup_product_id", "") if backup else "",
        "backup_generated_at": backup.get("backup_generated_at", "") if backup else "",
        "read_only_shopify_query_performed": bool(backup.get("read_only_shopify_query_performed")) if backup else False,
        "backup_fetch_status": backup.get("backup_fetch_status", "") if backup else "",
        "backup_value_source": backup.get("backup_value_source", "") if backup else "",
        "backup_source_is_verified": _backup_source_is_verified(backup),
    }


def _backup_completeness(backup: dict) -> dict:
    verified = _backup_source_is_verified(backup)
    return {
        "backup_source_is_verified": verified,
        "read_only_shopify_query_performed": bool(backup.get("read_only_shopify_query_performed")) if backup else False,
        "backup_report_structure_complete": _backup_report_structure_complete(backup),
        "verified_empty_backup": verified and not bool(backup.get("backup_value_present")),
        "future_write_blocked_until_verified_backup": not verified,
        "reason": [] if verified else ["backup not verified by a completed read-only Shopify query"],
    }


def _backup_source_is_verified(backup: dict) -> bool:
    return bool(backup) and bool(backup.get("read_only_shopify_query_performed")) and _backup_report_structure_complete(backup)


def _backup_report_structure_complete(backup: dict) -> bool:
    if not isinstance(backup, dict) or not backup:
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
    return all(key in backup for key in required)


def _blocking_conditions(validation_errors: list[str], proposed_value: str, backup_completeness: dict) -> list[str]:
    conditions = []
    possible = [
        "missing_preflight_package",
        "missing_backup_fetch_report",
        "scope_mismatch",
        "invalid_sandbox_field",
        "proposed_value_empty",
        "proposed_value_over_60_chars",
    ]
    for condition in possible:
        if condition in validation_errors:
            conditions.append(condition)
    if not proposed_value:
        conditions.append("proposed_value_empty")
    elif len(proposed_value) > MAX_PROPOSED_VALUE_CHARS:
        conditions.append("proposed_value_over_60_chars")
    if not backup_completeness["backup_source_is_verified"]:
        conditions.append("backup_not_verified")
    for condition in validation_errors:
        if "write_or_mutation" in condition or condition in {
            "source_report_indicates_mutation",
            "source_report_indicates_shopify_api_call",
            "no_write_not_confirmed",
        }:
            conditions.append(condition)
    return _unique(conditions)


def _hard_failures(validation_errors: list[str]) -> list[str]:
    non_hard = {"backup_source_not_verified"}
    return [error for error in validation_errors if error not in non_hard]


def _plan_status(validation_errors: list[str], backup_completeness: dict) -> str:
    hard_failures = _hard_failures(validation_errors)
    if hard_failures:
        if "scope_mismatch" in hard_failures:
            return "blocked_scope_mismatch"
        if "invalid_sandbox_field" in hard_failures:
            return "blocked_invalid_field"
        return "blocked"
    if not backup_completeness["backup_source_is_verified"]:
        return "needs_verified_backup"
    return "ready_for_manual_review"


def _readback_plan(scope: dict, proposed_value: str) -> dict:
    return {
        "readback_required": True,
        "readback_scope": {
            "product_id": scope.get("product_id", ""),
            "locale": scope.get("locale", ""),
            "field": ALLOWED_FIELD,
        },
        "future_expected_value": proposed_value,
        "future_expected_value_chars": len(proposed_value),
        "future_must_compare_shopify_value_to_proposed_value": True,
        "comparison_failure_status": "write_verification_failed",
        "no_scope_expansion_allowed": True,
        "no_full_store_scan_allowed": True,
        "readback_performed_in_this_phase": False,
    }


def _rollback_plan(scope: dict, backup_summary: dict, backup_completeness: dict) -> dict:
    verified = backup_completeness["backup_source_is_verified"]
    return {
        "rollback_required": True,
        "rollback_plan_status": "ready_for_future_review" if verified else "blocked_no_verified_backup",
        "rollback_scope": {
            "product_id": scope.get("product_id", ""),
            "locale": scope.get("locale", ""),
            "field": ALLOWED_FIELD,
        },
        "rollback_value": backup_summary["backup_value"],
        "rollback_value_present": backup_summary["backup_value_present"],
        "rollback_value_chars": backup_summary["backup_value_chars"],
        "rollback_uses_verified_backup_value_only": verified,
        "verified_empty_backup_requires_future_delete_or_empty_restore_review": verified
        and not backup_summary["backup_value_present"],
        "rollback_performed_in_this_phase": False,
    }


def _write_preconditions(
    preflight: dict,
    scope: dict,
    proposed_value: str,
    backup_completeness: dict,
    validation_errors: list[str],
) -> dict:
    return {
        "preflight_status_ready_for_manual_review": preflight.get("preflight_status") == "ready_for_manual_review",
        "backup_source_is_verified": backup_completeness["backup_source_is_verified"],
        "scope_consistent": "scope_mismatch" not in validation_errors,
        "proposed_value_non_empty": bool(proposed_value),
        "proposed_value_chars": len(proposed_value),
        "proposed_value_length_allowed": 0 < len(proposed_value) <= MAX_PROPOSED_VALUE_CHARS,
        "field_is_meta_title": scope.get("field") == ALLOWED_FIELD,
        "final_human_approval_required": True,
        "future_dangerous_flag_required": "--i-understand-this-writes-shopify",
        "all_preconditions_met_for_future_review": (
            preflight.get("preflight_status") == "ready_for_manual_review"
            and backup_completeness["backup_source_is_verified"]
            and "scope_mismatch" not in validation_errors
            and bool(proposed_value)
            and len(proposed_value) <= MAX_PROPOSED_VALUE_CHARS
            and scope.get("field") == ALLOWED_FIELD
        ),
    }


def _future_manual_checklist() -> list[str]:
    return [
        "Confirm verified backup exists for the same product_id, locale, and meta_title field.",
        "Confirm proposed_value is the exact value intended for Shopify.",
        "Confirm proposed_value is no longer than 60 characters.",
        "Confirm final human approval is recorded before any future write task.",
        "Confirm the future write task requires --i-understand-this-writes-shopify.",
        "After any future write, read back the same product_id, locale, and meta_title only.",
        "If readback fails, mark write_verification_failed and use the verified backup for rollback review.",
    ]


def _safety_summary() -> dict:
    return {
        "local_json_plan_only": True,
        "shopify_api_call_allowed": False,
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "readback_allowed_in_this_phase": False,
        "rollback_allowed_in_this_phase": False,
        "automatic_shopify_product_scan_allowed": False,
        "batch_product_read_allowed": False,
        "batch_locale_read_allowed": False,
        "batch_field_read_allowed": False,
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
    READBACK_ROLLBACK_PLAN_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(READBACK_ROLLBACK_PLAN_JSON_PATH.read_text(encoding="utf-8"))
    return READBACK_ROLLBACK_PLAN_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    READBACK_ROLLBACK_PLAN_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return READBACK_ROLLBACK_PLAN_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    if payload.get("plan_status") in {"needs_verified_backup", "blocked_backup_not_verified"}:
        status = "REVIEW"
    status_class = "pass" if status == "PASS" else "warn" if status == "REVIEW" else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Plan Status", "plan_status"),
            ("Source Preflight Status", "source_preflight_status"),
            ("Source Backup Fetch Status", "source_backup_fetch_status"),
            ("Future Required Flag", "future_required_flag"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("Translations Register Called", "translations_register_called"),
            ("Readback Performed", "readback_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("Validation Failures", "validation_failures"),
            ("Validation Warnings", "validation_warnings"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    scope_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Product ID", payload.get("requested_scope", {}).get("product_id", "")),
            ("Locale", payload.get("requested_scope", {}).get("locale", "")),
            ("Field", payload.get("requested_scope", {}).get("field", "")),
            ("Scope Matches", payload.get("validated_scope", {}).get("scope_matches_preflight_and_backup", "")),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Proposed Change", payload.get("proposed_change", {})),
            ("Backup Summary", payload.get("backup_summary", {})),
            ("Backup Completeness", payload.get("backup_completeness", {})),
            ("Readback Plan", payload.get("readback_plan", {})),
            ("Rollback Plan", payload.get("rollback_plan", {})),
            ("Write Preconditions", payload.get("write_preconditions", {})),
            ("Safety Summary", payload.get("safety_summary", {})),
        ]
    )
    checklist_items = "\n".join(
        f"<li>{escape(str(item))}</li>" for item in payload.get("future_manual_checklist", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Readback Rollback Plan</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 280px; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.warn {{ background: #fff8c5; color: #7d4e00; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify Single-Field Readback Rollback Plan</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Scope</h2>
  <table><tbody>{scope_rows}</tbody></table>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Plan Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Future Manual Checklist</h2>
  <ul>{checklist_items}</ul>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local JSON reports only.</li>
    <li>No Shopify API call was performed.</li>
    <li>No Shopify mutations were called.</li>
    <li>No translationsRegister call was performed.</li>
    <li>No readback or rollback was performed in this phase.</li>
    <li>No Shopify writes were performed.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(plan_status: str, validation_errors: list[str], backup_completeness: dict) -> str:
    if _hard_failures(validation_errors):
        return "Single-field readback/rollback plan blocked: " + ", ".join(_unique(_hard_failures(validation_errors)))
    if not backup_completeness["backup_source_is_verified"]:
        return "Single-field readback/rollback plan needs a verified backup before any future write."
    return f"Single-field readback/rollback plan generated with status {plan_status}. No Shopify API calls or writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field readback/rollback plan generated.\n"
        f"Plan status: {payload.get('plan_status')}\n"
        f"Requested scope: {payload.get('requested_scope')}\n"
        f"Backup source verified: {payload.get('backup_completeness', {}).get('backup_source_is_verified')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Readback/Rollback plan JSON:\n"
        f"{json_path}\n\n"
        "Readback/Rollback plan HTML:\n"
        f"{html_path}\n"
        "Plan only. No Shopify API call, readback, rollback, mutation, translationsRegister, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep readback/rollback plan files\n"
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
