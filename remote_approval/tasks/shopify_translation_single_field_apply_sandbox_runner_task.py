import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_single_field_apply_sandbox_runner"
COMMAND_LABEL = "shopify_translation_single_field_apply_sandbox_runner"
SOURCE_SANDBOX_DESIGN_PATH = LOG_DIR / "shopify_translation_single_field_apply_sandbox_design.json"
SANDBOX_RUNNER_JSON_PATH = LOG_DIR / "shopify_translation_single_field_apply_sandbox_runner.json"
SANDBOX_RUNNER_HTML_PATH = LOG_DIR / "shopify_translation_single_field_apply_sandbox_runner.html"
EXPECTED_DESIGN_TASK = "shopify_translation_single_field_apply_sandbox_design"
EXPECTED_DESIGN_MODE = "sandbox-design-only"
ALLOWED_FIELD = "meta_title"
ALLOWED_LOCALES = {"de", "fr", "es", "it", "ja"}
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/[0-9]+$")


def run_shopify_translation_single_field_apply_sandbox_runner_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_error = ""
    sandbox_design = {}

    try:
        sandbox_design = _read_json(SOURCE_SANDBOX_DESIGN_PATH)
    except (OSError, json.JSONDecodeError) as exc:
        parse_error = f"Could not parse sandbox design JSON: {exc}"
        validation_errors.append("sandbox_design_json_invalid")

    if sandbox_design:
        design_errors, design_warnings = _validate_sandbox_design(sandbox_design)
        validation_errors.extend(design_errors)
        validation_warnings.extend(design_warnings)

    requested_scope = _read_requested_scope()
    scope_errors = _validate_requested_scope(requested_scope)
    validation_errors.extend(scope_errors)

    validation_failures = _unique(validation_errors)
    validation_warnings = _unique(validation_warnings)
    success = not validation_failures
    sandbox_runner_status = "dry_run_ready" if success else "blocked"
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "mode": "sandbox-runner-dry-run-only",
        "runner_mode": "sandbox-runner-dry-run-only",
        "command_label": COMMAND_LABEL,
        "source_sandbox_design_path": str(SOURCE_SANDBOX_DESIGN_PATH),
        "json_sandbox_runner_path": str(SANDBOX_RUNNER_JSON_PATH),
        "html_sandbox_runner_path": str(SANDBOX_RUNNER_HTML_PATH),
        "success": success,
        "sandbox_runner_dry_run_only": True,
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if requested_scope["product_id"] and "invalid_product_id" not in scope_errors else 0,
            "locale_count": 1 if requested_scope["locale"] and "invalid_sandbox_locale" not in scope_errors else 0,
            "field_count": 1 if requested_scope["field"] == ALLOWED_FIELD else 0,
            "field_allowed": requested_scope["field"] == ALLOWED_FIELD,
            "allowed_field": ALLOWED_FIELD,
            "allowed_locales": sorted(ALLOWED_LOCALES),
        },
        "sandbox_runner_status": sandbox_runner_status,
        "would_apply_field": requested_scope["field"] if requested_scope["field"] == ALLOWED_FIELD else "",
        "would_call_shopify_mutation": "translationsRegister" if success else "",
        "real_write_allowed": False,
        "real_write_attempted": False,
        "translations_register_allowed": False,
        "translations_register_called": False,
        "command_executed": False,
        "shopify_api_called": False,
        "apply_performed": False,
        "publish_performed": False,
        "update_performed": False,
        "mutation_performed": False,
        "shopify_write_performed": False,
        "translations_register_performed": False,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": bool(sandbox_design.get("all_no_write_confirmed")) if sandbox_design else False,
        "validation_failures": validation_failures,
        "validation_warnings": validation_warnings,
        "parse_error": parse_error,
        "detected_issue_summary": _issue_summary(sandbox_runner_status, validation_failures),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": round(time.time() - started, 3),
        "safety": {
            "sandbox_runner_dry_run_only": True,
            "real_write_allowed": False,
            "real_write_attempted": False,
            "translations_register_allowed": False,
            "translations_register_called": False,
            "command_executed": False,
            "shopify_api_called": False,
            "shopify_writes_allowed": False,
            "publish_allowed": False,
            "apply_allowed": False,
            "update_allowed": False,
            "mutation_allowed": False,
            "database_writes_allowed": False,
            "git_push_allowed": False,
            "auto_scan_all_products_allowed": False,
            "product_file_fallback_allowed": False,
            "max_products": 1,
            "max_locales": 1,
            "max_fields": 1,
            "allowed_fields": [ALLOWED_FIELD],
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
        "json_sandbox_runner_path": str(json_path),
        "html_sandbox_runner_path": str(html_path),
        "source_sandbox_design_path": str(SOURCE_SANDBOX_DESIGN_PATH),
        "sandbox_runner_dry_run_only": True,
        "sandbox_runner_status": sandbox_runner_status,
        "would_apply_field": payload["would_apply_field"],
        "would_call_shopify_mutation": payload["would_call_shopify_mutation"],
        "real_write_allowed": False,
        "real_write_attempted": False,
        "translations_register_allowed": False,
        "translations_register_called": False,
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


def _validate_sandbox_design(report: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    unsafe_checks = [
        ("task", report.get("task") == EXPECTED_DESIGN_TASK),
        ("mode", report.get("mode") == EXPECTED_DESIGN_MODE),
        ("real_write_allowed", report.get("real_write_allowed") is False),
        ("translations_register_allowed", report.get("translations_register_allowed") is False),
        ("command_executed", report.get("command_executed") is False),
        ("apply_performed", report.get("apply_performed") is False),
        ("publish_performed", report.get("publish_performed") is False),
        ("translations_register_performed", report.get("translations_register_performed") is False),
        ("shopify_write_performed", report.get("shopify_write_performed") is False),
        ("all_no_write_confirmed", report.get("all_no_write_confirmed") is True),
    ]
    for name, passed in unsafe_checks:
        if passed:
            continue
        if name in {
            "command_executed",
            "apply_performed",
            "publish_performed",
            "translations_register_performed",
        }:
            errors.append("command_or_apply_already_performed")
        elif name in {"shopify_write_performed", "all_no_write_confirmed"}:
            errors.append("no_write_not_confirmed")
        else:
            errors.append("unsafe_sandbox_design")

    scope = report.get("sandbox_scope") or {}
    allowed_fields = scope.get("allowed_fields")
    scope_valid = (
        scope.get("max_products") == 1
        and scope.get("max_locales") == 1
        and scope.get("max_fields") == 1
        and allowed_fields == [ALLOWED_FIELD]
        and scope.get("default_field") == ALLOWED_FIELD
    )
    if not scope_valid:
        errors.append("invalid_sandbox_scope")

    if report.get("real_write_allowed") is True:
        errors.append("unsafe_sandbox_design")
    if report.get("translations_register_allowed") is True:
        errors.append("unsafe_sandbox_design")
    if report.get("no_shopify_writes_performed") is not True:
        warnings.append("source no_shopify_writes_performed is not true; runner still performs no writes")

    return _unique(errors), _unique(warnings)


def _read_requested_scope() -> dict:
    return {
        "product_id": (os.environ.get("SHOPIFY_TRANSLATION_SANDBOX_PRODUCT_ID") or "").strip(),
        "locale": (os.environ.get("SHOPIFY_TRANSLATION_SANDBOX_LOCALE") or "").strip(),
        "field": (os.environ.get("SHOPIFY_TRANSLATION_SANDBOX_FIELD") or "").strip(),
    }


def _validate_requested_scope(scope: dict) -> list[str]:
    errors = []
    product_id = scope["product_id"]
    locale = scope["locale"]
    field = scope["field"]

    if not product_id:
        errors.append("missing_sandbox_product_id")
    elif not PRODUCT_GID_RE.match(product_id):
        errors.append("invalid_product_id")

    if not locale:
        errors.append("missing_sandbox_locale")
    elif "," in locale or locale not in ALLOWED_LOCALES:
        errors.append("invalid_sandbox_locale")

    if not field:
        errors.append("missing_sandbox_field")
    elif field != ALLOWED_FIELD:
        errors.append("invalid_sandbox_field")

    return _unique(errors)


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SANDBOX_RUNNER_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SANDBOX_RUNNER_JSON_PATH.read_text(encoding="utf-8"))
    return SANDBOX_RUNNER_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SANDBOX_RUNNER_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SANDBOX_RUNNER_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    scope_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Product ID", payload.get("requested_scope", {}).get("product_id", "")),
            ("Locale", payload.get("requested_scope", {}).get("locale", "")),
            ("Field", payload.get("requested_scope", {}).get("field", "")),
            ("Product Count", payload.get("validated_scope", {}).get("product_count", "")),
            ("Locale Count", payload.get("validated_scope", {}).get("locale_count", "")),
            ("Field Count", payload.get("validated_scope", {}).get("field_count", "")),
            ("Field Allowed", payload.get("validated_scope", {}).get("field_allowed", "")),
            ("Allowed Field", ALLOWED_FIELD),
        ]
    )
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Runner Mode", "runner_mode"),
            ("Timestamp", "timestamp"),
            ("Source Sandbox Design", "source_sandbox_design_path"),
            ("Sandbox Runner Status", "sandbox_runner_status"),
            ("Would Apply Field", "would_apply_field"),
            ("Would Call Shopify Mutation", "would_call_shopify_mutation"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Real Write Attempted", "real_write_attempted"),
            ("Translations Register Allowed", "translations_register_allowed"),
            ("Translations Register Called", "translations_register_called"),
            ("Command Executed", "command_executed"),
            ("Shopify API Called", "shopify_api_called"),
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
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Apply Sandbox Runner</title>
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
  <h1>Shopify Single-Field Apply Sandbox Runner</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Requested Scope</h2>
  <table><tbody>{scope_rows}</tbody></table>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task is sandbox-runner-dry-run-only.</li>
    <li>No command was executed.</li>
    <li>No Shopify API was called.</li>
    <li>No Shopify writes were performed.</li>
    <li>real_write_allowed=false.</li>
    <li>translations_register_allowed=false.</li>
    <li>Only meta_title is accepted as the sandbox field.</li>
    <li>No product file fallback or automatic Shopify product scan is allowed.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(sandbox_runner_status: str, validation_failures: list[str]) -> str:
    if validation_failures:
        return "Single-field apply sandbox runner blocked: " + ", ".join(_unique(validation_failures))
    return (
        f"Single-field apply sandbox runner completed with status {sandbox_runner_status}. "
        "Dry-run only; no Shopify writes performed."
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field apply sandbox runner completed.\n"
        f"Source sandbox design: {payload.get('source_sandbox_design_path')}\n"
        f"Sandbox runner status: {payload.get('sandbox_runner_status')}\n"
        f"Requested scope: {payload.get('requested_scope')}\n"
        f"Would apply field: {payload.get('would_apply_field')}\n"
        f"Would call Shopify mutation: {payload.get('would_call_shopify_mutation')}\n"
        f"Real write allowed: {payload.get('real_write_allowed')}\n"
        f"Real write attempted: {payload.get('real_write_attempted')}\n"
        f"translationsRegister allowed: {payload.get('translations_register_allowed')}\n"
        f"translationsRegister called: {payload.get('translations_register_called')}\n"
        f"Validation failures: {len(payload.get('validation_failures') or [])}\n"
        "Sandbox runner JSON:\n"
        f"{json_path}\n\n"
        "Sandbox runner HTML:\n"
        f"{html_path}\n"
        "Sandbox runner dry-run only. No Shopify writes performed by this task.\n"
        "command_executed=false.\n"
        "shopify_write_performed=false.\n"
        "apply_performed=false; publish_performed=false; translationsRegister_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep sandbox runner files\n"
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
