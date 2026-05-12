import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_apply_sandbox_design"
COMMAND_LABEL = "shopify_translation_single_field_apply_sandbox_design"
SOURCE_LOCKED_RUNNER_PATH = LOG_DIR / "shopify_translation_batch_apply_locked_runner.json"
SANDBOX_DESIGN_JSON_PATH = LOG_DIR / "shopify_translation_single_field_apply_sandbox_design.json"
SANDBOX_DESIGN_HTML_PATH = LOG_DIR / "shopify_translation_single_field_apply_sandbox_design.html"
EXPECTED_LOCKED_RUNNER_TASK = "shopify_translation_batch_apply_locked_runner"
EXPECTED_LOCKED_RUNNER_MODE = "locked-apply-shell-only"
SANDBOX_SCOPE = {
    "max_products": 1,
    "max_locales": 1,
    "max_fields": 1,
    "allowed_fields": ["meta_title"],
    "default_field": "meta_title",
}


def run_shopify_translation_single_field_apply_sandbox_design_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_error = ""
    locked_runner = {}

    try:
        locked_runner = _read_json(SOURCE_LOCKED_RUNNER_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        parse_error = f"Could not parse locked runner JSON: {exc}"
        validation_errors.append("locked_runner_json_invalid")

    if locked_runner:
        errors, warnings = _validate_locked_runner(locked_runner)
        validation_errors.extend(errors)
        validation_warnings.extend(warnings)

    validation_failures = _unique(validation_errors)
    validation_warnings = _unique(validation_warnings)
    success = not validation_failures
    sandbox_design_status = "ready_for_review" if success else "blocked"
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": "sandbox-design-only",
        "command_label": COMMAND_LABEL,
        "source_locked_runner_path": str(SOURCE_LOCKED_RUNNER_PATH),
        "json_sandbox_design_path": str(SANDBOX_DESIGN_JSON_PATH),
        "html_sandbox_design_path": str(SANDBOX_DESIGN_HTML_PATH),
        "success": success,
        "sandbox_design_only": True,
        "sandbox_scope": SANDBOX_SCOPE,
        "allowed_mode": "sandbox-design-only",
        "allowed_fields": SANDBOX_SCOPE["allowed_fields"],
        "default_field": SANDBOX_SCOPE["default_field"],
        "max_products": SANDBOX_SCOPE["max_products"],
        "max_locales": SANDBOX_SCOPE["max_locales"],
        "max_fields": SANDBOX_SCOPE["max_fields"],
        "real_write_allowed": False,
        "translations_register_allowed": False,
        "requires_manual_product_id": True,
        "requires_manual_locale": True,
        "requires_manual_field": True,
        "requires_final_human_confirmation": True,
        "requires_backup_before_write": True,
        "requires_post_write_readback_verification": True,
        "sandbox_design_status": sandbox_design_status,
        "source_locked_runner_status": locked_runner.get("locked_runner_status", "") if locked_runner else "",
        "source_real_apply_allowed": bool(locked_runner.get("real_apply_allowed")) if locked_runner else False,
        "source_real_apply_performed": bool(locked_runner.get("real_apply_performed")) if locked_runner else False,
        "source_command_executed": bool(locked_runner.get("command_executed")) if locked_runner else False,
        "source_eligible_real_execution_count": _safe_int(locked_runner.get("eligible_real_execution_count"))
        if locked_runner
        else 0,
        "future_sandbox_rules": _future_sandbox_rules(),
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(locked_runner.get("all_no_write_confirmed")) if locked_runner else False,
        "command_executed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "translations_register_performed": False,
        "validation_failures": validation_failures,
        "validation_warnings": validation_warnings,
        "parse_error": parse_error,
        "detected_issue_summary": _issue_summary(sandbox_design_status, validation_failures),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
            "sandbox_design_only": True,
            "real_write_allowed": False,
            "translations_register_allowed": False,
            "command_executed": False,
            "shopify_writes_allowed": False,
            "register_translations_allowed": False,
            "publish_allowed": False,
            "apply_allowed": False,
            "update_allowed": False,
            "mutation_allowed": False,
            "database_writes_allowed": False,
            "git_push_allowed": False,
            "auto_scan_all_products_allowed": False,
            "max_products": SANDBOX_SCOPE["max_products"],
            "max_locales": SANDBOX_SCOPE["max_locales"],
            "max_fields": SANDBOX_SCOPE["max_fields"],
            "allowed_fields": SANDBOX_SCOPE["allowed_fields"],
        },
    }
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_sandbox_design_path": str(json_path),
        "html_sandbox_design_path": str(html_path),
        "source_locked_runner_path": str(SOURCE_LOCKED_RUNNER_PATH),
        "sandbox_design_only": True,
        "sandbox_design_status": sandbox_design_status,
        "real_write_allowed": False,
        "translations_register_allowed": False,
        "max_products": SANDBOX_SCOPE["max_products"],
        "max_locales": SANDBOX_SCOPE["max_locales"],
        "max_fields": SANDBOX_SCOPE["max_fields"],
        "default_field": SANDBOX_SCOPE["default_field"],
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": payload["all_no_write_confirmed"],
        "command_executed": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "validation_failures_count": len(validation_failures),
        "validation_warnings_count": len(validation_warnings),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_locked_runner(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    unsafe_checks = [
        ("task", report.get("task") == EXPECTED_LOCKED_RUNNER_TASK),
        ("mode", report.get("mode") == EXPECTED_LOCKED_RUNNER_MODE),
        ("real_apply_performed", report.get("real_apply_performed") is False),
        ("command_executed", report.get("command_executed") is False),
        ("apply_performed", report.get("apply_performed") is False),
        ("publish_performed", report.get("publish_performed") is False),
        ("translations_register_performed", report.get("translations_register_performed") is False),
        ("shopify_write_performed", report.get("shopify_write_performed") is False),
        ("no_shopify_writes_performed", report.get("no_shopify_writes_performed") is True),
        ("all_no_write_confirmed", report.get("all_no_write_confirmed") is True),
    ]
    for name, passed in unsafe_checks:
        if passed:
            continue
        if name in {
            "real_apply_performed",
            "command_executed",
            "apply_performed",
            "publish_performed",
            "translations_register_performed",
        }:
            errors.append("command_or_apply_already_performed")
        elif name in {"shopify_write_performed", "no_shopify_writes_performed", "all_no_write_confirmed"}:
            errors.append("no_write_not_confirmed")
        else:
            errors.append(f"unsafe_locked_runner_report_{name}")

    if report.get("real_apply_allowed") is True:
        warnings.append("source real_apply_allowed=true; sandbox design still keeps real_write_allowed=false")
    if report.get("translations_register_performed") is True:
        errors.append("command_or_apply_already_performed")
    return _unique(errors), _unique(warnings)


def _future_sandbox_rules() -> list[str]:
    return [
        "Future write task must be separate from this sandbox design task.",
        "Future sandbox write must require one manually supplied product_id.",
        "Future sandbox write must require one manually supplied locale.",
        "Future sandbox write must require exactly one field: meta_title.",
        "title, body_html, and meta_description writes are not allowed in the sandbox.",
        "Future sandbox write must require explicit final human confirmation.",
        "Future sandbox write must read and record a pre-write backup value.",
        "Future sandbox write must perform post-write readback verification.",
        "Future sandbox write must verify translationsRegister userErrors are empty.",
        "Future sandbox write must not publish translations.",
    ]


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SANDBOX_DESIGN_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SANDBOX_DESIGN_JSON_PATH.read_text(encoding="utf-8"))
    return SANDBOX_DESIGN_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SANDBOX_DESIGN_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SANDBOX_DESIGN_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    scope_rows = "\n".join(
        _summary_row(label, payload.get("sandbox_scope", {}).get(key))
        for label, key in [
            ("Max Products", "max_products"),
            ("Max Locales", "max_locales"),
            ("Max Fields", "max_fields"),
            ("Allowed Fields", "allowed_fields"),
            ("Default Field", "default_field"),
        ]
    )
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Source Locked Runner", "source_locked_runner_path"),
            ("Sandbox Design Status", "sandbox_design_status"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Translations Register Allowed", "translations_register_allowed"),
            ("Requires Manual Product ID", "requires_manual_product_id"),
            ("Requires Manual Locale", "requires_manual_locale"),
            ("Requires Manual Field", "requires_manual_field"),
            ("Requires Final Human Confirmation", "requires_final_human_confirmation"),
            ("Requires Backup Before Write", "requires_backup_before_write"),
            ("Requires Post-Write Readback Verification", "requires_post_write_readback_verification"),
            ("Command Executed", "command_executed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Apply Performed", "apply_performed"),
            ("Publish Performed", "publish_performed"),
            ("Translations Register Performed", "translations_register_performed"),
            ("No Shopify Writes Performed", "no_shopify_writes_performed"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("Validation Failures", "validation_failures"),
            ("Validation Warnings", "validation_warnings"),
        ]
    )
    rule_items = "\n".join(f"<li>{escape(rule)}</li>" for rule in payload.get("future_sandbox_rules", []))
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Apply Sandbox Design</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify Single-Field Apply Sandbox Design</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Sandbox Scope</h2>
  <table><tbody>{scope_rows}</tbody></table>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Future Sandbox Rules</h2>
  <ul>{rule_items}</ul>
  <h2>Safety</h2>
  <ul>
    <li>This task is sandbox-design-only.</li>
    <li>No command was executed.</li>
    <li>No Shopify API was called.</li>
    <li>No Shopify writes were performed.</li>
    <li>real_write_allowed=false.</li>
    <li>translations_register_allowed=false.</li>
    <li>Only meta_title is allowed in the future sandbox design.</li>
    <li>title, body_html, and meta_description writes are not allowed in this sandbox design.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(sandbox_design_status: str, validation_failures: list[str]) -> str:
    if validation_failures:
        return "Single-field apply sandbox design blocked: " + ", ".join(_unique(validation_failures))
    return f"Single-field apply sandbox design completed with status {sandbox_design_status}. No Shopify writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field apply sandbox design completed.\n"
        f"Source locked runner: {payload.get('source_locked_runner_path')}\n"
        f"Sandbox design status: {payload.get('sandbox_design_status')}\n"
        f"Allowed fields: {payload.get('allowed_fields')}\n"
        f"Default field: {payload.get('default_field')}\n"
        f"Real write allowed: {payload.get('real_write_allowed')}\n"
        f"translationsRegister allowed: {payload.get('translations_register_allowed')}\n"
        f"Validation failures: {len(payload.get('validation_failures') or [])}\n"
        "Sandbox design JSON:\n"
        f"{json_path}\n\n"
        "Sandbox design HTML:\n"
        f"{html_path}\n"
        "Sandbox design only. No Shopify writes performed by this task.\n"
        "command_executed=false.\n"
        "shopify_write_performed=false.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep sandbox design files\n"
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
