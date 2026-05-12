import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_small_batch_post_write_audit_package"
COMMAND_LABEL = "shopify_translation_small_batch_post_write_audit_package"
SOURCE_SMALL_BATCH_EXECUTE_PATH = LOG_DIR / "shopify_translation_small_batch_apply_execute.json"
SOURCE_SMALL_BATCH_PLAN_PATH = LOG_DIR / "shopify_translation_small_batch_apply_plan_package.json"
SMALL_BATCH_POST_WRITE_AUDIT_JSON_PATH = LOG_DIR / "shopify_translation_small_batch_post_write_audit_package.json"
SMALL_BATCH_POST_WRITE_AUDIT_HTML_PATH = LOG_DIR / "shopify_translation_small_batch_post_write_audit_package.html"

EXPECTED_EXECUTE_TASK = "shopify_translation_small_batch_apply_execute"
EXPECTED_EXECUTION_STATUS = "small_batch_real_write_succeeded_and_verified"
EXPECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
EXPECTED_LOCALE = "ja"
EXPECTED_ENTRY_COUNT = 2
ALLOWED_SOURCE_MODES = {"real-run", "execute-real-write"}
ALLOWED_FIELDS = ["meta_title", "meta_description"]


def run_shopify_translation_small_batch_post_write_audit_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    execute_report = {}
    plan_report = {}

    try:
        execute_report = _read_json(SOURCE_SMALL_BATCH_EXECUTE_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Small batch execute JSON not found: {exc}")
        validation_errors.append("missing_small_batch_execute_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse small batch execute JSON: {exc}")
        validation_errors.append("small_batch_execute_json_invalid")

    try:
        plan_report = _read_json(SOURCE_SMALL_BATCH_PLAN_PATH)
    except FileNotFoundError:
        plan_report = {}
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse optional small batch apply plan JSON: {exc}")
        validation_errors.append("small_batch_apply_plan_json_invalid")

    if execute_report:
        validation_errors.extend(_validate_execute_report(execute_report))

    blocking_conditions = _blocking_conditions(validation_errors)
    audit_status = _audit_status(blocking_conditions, execute_report)
    success = audit_status == "small_batch_post_write_audit_passed"
    source_summary = _source_execution_summary(execute_report)
    proposed_values = _proposed_values(execute_report, plan_report)
    final_readback_values = _final_readback_values(execute_report)
    rollback_summary = _rollback_summary(success)
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "small-batch-post-write-audit-only",
        "command_label": COMMAND_LABEL,
        "source_small_batch_execute_path": str(SOURCE_SMALL_BATCH_EXECUTE_PATH),
        "source_small_batch_plan_path": str(SOURCE_SMALL_BATCH_PLAN_PATH),
        "json_small_batch_post_write_audit_package_path": str(SMALL_BATCH_POST_WRITE_AUDIT_JSON_PATH),
        "html_small_batch_post_write_audit_package_path": str(SMALL_BATCH_POST_WRITE_AUDIT_HTML_PATH),
        "success": success,
        "audit_status": audit_status,
        "product_id": source_summary["source_product_id"],
        "locale": source_summary["source_locale"],
        "entry_count": source_summary["source_entry_count"],
        "audited_fields": _audited_fields(execute_report, plan_report),
        "proposed_values": proposed_values,
        "final_readback_values": final_readback_values,
        "readback_all_entries_match": source_summary["source_readback_all_entries_match"],
        "rollback_needed": rollback_summary["rollback_needed"],
        "rollback_optional_restore_possible": rollback_summary["rollback_optional_restore_possible"],
        "rollback_optional_restore_requires_separate_approval": rollback_summary[
            "rollback_optional_restore_requires_separate_approval"
        ],
        "manual_review_completed": False,
        "source_execution_report_summary": source_summary,
        "source_plan_summary": _source_plan_summary(plan_report),
        "write_summary": _write_summary(execute_report),
        "readback_summary": _readback_summary(execute_report),
        "verification_summary": _verification_summary(execute_report),
        "rollback_summary": rollback_summary,
        "post_write_observations": _post_write_observations(success),
        "next_phase_recommendations": _next_phase_recommendations(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(source_summary),
        "audit_package_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
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
        "json_small_batch_post_write_audit_package_path": str(json_path),
        "html_small_batch_post_write_audit_package_path": str(html_path),
        "audit_status": audit_status,
        "audit_package_only": True,
        "source_execution_status": source_summary["source_execution_status"],
        "source_mode": source_summary["source_mode"],
        "source_shopify_write_performed": source_summary["source_shopify_write_performed"],
        "source_translations_register_called": source_summary["source_translations_register_called"],
        "source_mutation_performed": source_summary["source_mutation_performed"],
        "source_readback_performed": source_summary["source_readback_performed"],
        "source_entry_count": source_summary["source_entry_count"],
        "readback_all_entries_match": source_summary["source_readback_all_entries_match"],
        "rollback_needed": rollback_summary["rollback_needed"],
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "readback_performed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_execute_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != EXPECTED_EXECUTE_TASK:
        errors.append("small_batch_execute_report_task_mismatch")
    if report.get("mode") not in ALLOWED_SOURCE_MODES:
        errors.append("source_not_real_run")
    if report.get("execution_status") != EXPECTED_EXECUTION_STATUS:
        errors.append("small_batch_real_write_not_successful")
    if report.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.append("scope_mismatch")
    if report.get("locale") != EXPECTED_LOCALE:
        errors.append("scope_mismatch")
    if int(report.get("entry_count") or 0) != EXPECTED_ENTRY_COUNT:
        errors.append("unexpected_entry_count")

    fields = _audited_fields(report, {})
    if fields != ALLOWED_FIELDS:
        errors.append("invalid_field")

    if report.get("shopify_api_call_performed") is not True:
        errors.append("small_batch_real_write_not_successful")
    if report.get("shopify_write_performed") is not True:
        errors.append("small_batch_real_write_not_successful")
    if report.get("mutation_performed") is not True:
        errors.append("small_batch_real_write_not_successful")
    if report.get("translations_register_called") is not True:
        errors.append("small_batch_real_write_not_successful")
    if report.get("readback_performed") is not True:
        errors.append("small_batch_readback_mismatch")
    if report.get("readback_all_entries_match") is not True:
        errors.append("small_batch_readback_mismatch")
    if int(report.get("readback_matched_entry_count") or 0) != EXPECTED_ENTRY_COUNT:
        errors.append("small_batch_readback_mismatch")
    if report.get("rollback_approval_required") is not False:
        errors.append("small_batch_requires_rollback_review")
    if report.get("rollback_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("automatic_rollback_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("publish_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("bulk_write_performed") is not False:
        errors.append("unexpected_side_effects")
    if report.get("small_batch_write_performed") is not True:
        errors.append("small_batch_real_write_not_successful")
    if report.get("blocking_conditions") not in ([], None):
        errors.append("small_batch_real_write_not_successful")

    for item in _readback_results(report):
        if item.get("field") not in ALLOWED_FIELDS:
            errors.append("invalid_field")
        if item.get("matches_proposed_value") is not True:
            errors.append("small_batch_readback_mismatch")
    return _unique(errors)


def _source_execution_summary(report: dict) -> dict:
    return {
        "source_task": report.get("task", "") if report else "",
        "source_mode": report.get("mode", "") if report else "",
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_shopify_api_call_performed": bool(report.get("shopify_api_call_performed")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "source_readback_all_entries_match": bool(report.get("readback_all_entries_match")) if report else False,
        "source_readback_matched_entry_count": int(report.get("readback_matched_entry_count") or 0) if report else 0,
        "source_rollback_approval_required": bool(report.get("rollback_approval_required")) if report else False,
        "source_rollback_performed": bool(report.get("rollback_performed")) if report else False,
        "source_automatic_rollback_performed": bool(report.get("automatic_rollback_performed")) if report else False,
        "source_publish_performed": bool(report.get("publish_performed")) if report else False,
        "source_bulk_write_performed": bool(report.get("bulk_write_performed")) if report else False,
        "source_small_batch_write_performed": bool(report.get("small_batch_write_performed")) if report else False,
        "source_blocking_conditions": report.get("blocking_conditions", []) if report else [],
    }


def _source_plan_summary(report: dict) -> dict:
    return {
        "source_plan_loaded": bool(report),
        "source_plan_status": report.get("plan_status", "") if report else "",
        "source_plan_entry_count": int(report.get("entry_count") or 0) if report else 0,
        "source_plan_allowed_fields": report.get("allowed_fields", []) if report else [],
        "source_plan_product_id": report.get("product_id", "") if report else "",
        "source_plan_locale": report.get("locale", "") if report else "",
    }


def _write_summary(report: dict) -> dict:
    return {
        "source_execution_status": report.get("execution_status", "") if report else "",
        "source_translations_register_called": bool(report.get("translations_register_called")) if report else False,
        "source_shopify_write_performed": bool(report.get("shopify_write_performed")) if report else False,
        "source_mutation_performed": bool(report.get("mutation_performed")) if report else False,
        "source_small_batch_write_performed": bool(report.get("small_batch_write_performed")) if report else False,
        "source_bulk_write_performed": bool(report.get("bulk_write_performed")) if report else False,
        "write_scope_limited": bool(report.get("validated_execution_scope", {}).get("product_count") == 1)
        if report
        else False,
        "real_write_count": int((report.get("translations_register_execution_summary") or {}).get("real_write_count") or 0)
        if report
        else 0,
        "proposed_values": _proposed_values(report, {}),
    }


def _readback_summary(report: dict) -> dict:
    return {
        "source_readback_performed": bool(report.get("readback_performed")) if report else False,
        "readback_results": _readback_results(report),
        "readback_all_entries_match": bool(report.get("readback_all_entries_match")) if report else False,
        "readback_matched_entry_count": int(report.get("readback_matched_entry_count") or 0) if report else 0,
        "final_readback_values": _final_readback_values(report),
    }


def _verification_summary(report: dict) -> dict:
    verification = report.get("verification_summary") or {}
    return {
        "source_verification_passed": bool(verification.get("verification_passed")),
        "source_readback_all_entries_match": bool(report.get("readback_all_entries_match")) if report else False,
        "source_readback_matched_entry_count": int(report.get("readback_matched_entry_count") or 0) if report else 0,
        "audit_verification_passed": (
            report.get("execution_status") == EXPECTED_EXECUTION_STATUS
            and report.get("readback_all_entries_match") is True
            and int(report.get("readback_matched_entry_count") or 0) == EXPECTED_ENTRY_COUNT
        )
        if report
        else False,
    }


def _rollback_summary(audit_passed: bool) -> dict:
    return {
        "rollback_needed": not audit_passed,
        "rollback_optional_restore_possible": True,
        "rollback_optional_restore_requires_separate_approval": True,
        "rollback_approval_required": False if audit_passed else True,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "rollback_note": (
            "No rollback required because all small batch readback values matched proposed values."
            if audit_passed
            else "Rollback review would require a separate approval package."
        ),
    }


def _audited_fields(execute_report: dict, plan_report: dict) -> list[str]:
    fields = [item.get("field") for item in _readback_results(execute_report) if item.get("field")]
    if not fields:
        fields = [entry.get("field") for entry in execute_report.get("planned_entries", []) if entry.get("field")]
    if not fields and plan_report:
        fields = [entry.get("field") for entry in plan_report.get("entries", []) if entry.get("field")]
    return _unique(fields)


def _proposed_values(execute_report: dict, plan_report: dict) -> dict:
    entries = execute_report.get("planned_entries") or plan_report.get("entries") or []
    return {
        entry.get("field"): entry.get("proposed_value", "")
        for entry in entries
        if entry.get("field") in ALLOWED_FIELDS
    }


def _final_readback_values(execute_report: dict) -> dict:
    return {
        item.get("field"): item.get("readback_value", "")
        for item in _readback_results(execute_report)
        if item.get("field") in ALLOWED_FIELDS
    }


def _readback_results(report: dict) -> list[dict]:
    if not report:
        return []
    readback = report.get("readback_summary") or {}
    results = readback.get("readback_results")
    return results if isinstance(results, list) else []


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_small_batch_execute_report": "blocked_missing_small_batch_execute_report",
        "small_batch_real_write_not_successful": "blocked_small_batch_real_write_not_successful",
        "source_not_real_run": "blocked_source_not_real_run",
        "small_batch_readback_mismatch": "blocked_small_batch_readback_mismatch",
        "small_batch_requires_rollback_review": "blocked_small_batch_requires_rollback_review",
        "unexpected_entry_count": "blocked_unexpected_entry_count",
        "invalid_field": "blocked_invalid_field",
        "scope_mismatch": "blocked_scope_mismatch",
        "unexpected_side_effects": "blocked_unexpected_side_effects",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _audit_status(blocking_conditions: list[str], execute_report: dict) -> str:
    if not execute_report:
        return "blocked_missing_small_batch_execute_report"
    if not blocking_conditions:
        return "small_batch_post_write_audit_passed"
    for status in [
        "blocked_small_batch_real_write_not_successful",
        "blocked_source_not_real_run",
        "blocked_small_batch_readback_mismatch",
        "blocked_small_batch_requires_rollback_review",
        "blocked_unexpected_entry_count",
        "blocked_invalid_field",
        "blocked_scope_mismatch",
        "blocked_unexpected_side_effects",
    ]:
        if status in blocking_conditions:
            return status
    return "small_batch_post_write_audit_failed"


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
        "publish_allowed_in_this_phase": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _post_write_observations(audit_passed: bool) -> list[str]:
    if not audit_passed:
        return [
            "Small batch post-write audit did not pass.",
            "No new Shopify action was performed by this audit task.",
        ]
    return [
        "Small batch Shopify translation write succeeded.",
        "The write scope remained one product and one locale.",
        "Audited fields were limited to meta_title and meta_description.",
        "Every readback value matched the proposed value.",
        "No rollback, automatic rollback, publish, or bulk write was performed by the source task.",
    ]


def _next_phase_recommendations() -> list[str]:
    return [
        "Generate a small batch rollback approval package if optional restore is desired.",
        "Do not expand beyond 5 entries without a separate safety phase.",
        "Do not enable multi-product or multi-locale apply yet.",
        "Keep future small batch writes behind explicit ACK and immediate readback.",
    ]


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SMALL_BATCH_POST_WRITE_AUDIT_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SMALL_BATCH_POST_WRITE_AUDIT_JSON_PATH.read_text(encoding="utf-8"))
    return SMALL_BATCH_POST_WRITE_AUDIT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SMALL_BATCH_POST_WRITE_AUDIT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SMALL_BATCH_POST_WRITE_AUDIT_HTML_PATH


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
            ("Entry Count", "entry_count"),
            ("Audited Fields", "audited_fields"),
            ("Readback All Entries Match", "readback_all_entries_match"),
            ("Rollback Needed", "rollback_needed"),
            ("Manual Review Completed", "manual_review_completed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Source Execution Report Summary", payload.get("source_execution_report_summary", {})),
            ("Source Plan Summary", payload.get("source_plan_summary", {})),
            ("Proposed Values", payload.get("proposed_values", {})),
            ("Final Readback Values", payload.get("final_readback_values", {})),
            ("Write Summary", payload.get("write_summary", {})),
            ("Readback Summary", payload.get("readback_summary", {})),
            ("Verification Summary", payload.get("verification_summary", {})),
            ("Rollback Summary", payload.get("rollback_summary", {})),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Small Batch Post-Write Audit Package</title>
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
  <h1>Shopify Small Batch Post-Write Audit Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Audit Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads local reports only.</li>
    <li>No Shopify API call, write, mutation, translationsRegister, readback, rollback, publish, or apply was performed by this audit task.</li>
    <li>Prior source write facts are preserved separately under source summaries.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(audit_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Small batch post-write audit blocked: " + ", ".join(blocking_conditions)
    return f"Small batch post-write audit completed with status {audit_status}. No new Shopify action performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify small batch post-write audit package generated.\n"
        f"Audit status: {payload.get('audit_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Locale: {payload.get('locale')}\n"
        f"Entry count: {payload.get('entry_count')}\n"
        f"Audited fields: {payload.get('audited_fields')}\n"
        f"Readback all entries match: {payload.get('readback_all_entries_match')}\n"
        f"Rollback needed: {payload.get('rollback_needed')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Small batch post-write audit JSON:\n"
        f"{json_path}\n\n"
        "Small batch post-write audit HTML:\n"
        f"{html_path}\n"
        "Audit package only. No Shopify API call, mutation, translationsRegister, readback, rollback, publish, apply, or write was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep small batch post-write audit files\n"
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
