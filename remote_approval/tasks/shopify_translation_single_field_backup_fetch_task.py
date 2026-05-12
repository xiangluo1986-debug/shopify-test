import json
import os
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_single_field_backup_fetch"
COMMAND_LABEL = "shopify_translation_single_field_backup_fetch_read_only"
SOURCE_PREFLIGHT_PACKAGE_PATH = LOG_DIR / "shopify_translation_single_field_apply_preflight_package.json"
BACKUP_FETCH_JSON_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.json"
BACKUP_FETCH_HTML_PATH = LOG_DIR / "shopify_translation_single_field_backup_fetch.html"
EXPECTED_PREFLIGHT_TASK = "shopify_translation_single_field_apply_preflight_package"
EXPECTED_PREFLIGHT_MODE = "single-field-preflight-only"
ALLOWED_FIELD = "meta_title"
ALLOWED_LOCALES = {"de", "fr", "es", "it", "ja"}
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/[0-9]+$")
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
DOCKER_TIMEOUT_SECONDS = 120


def run_shopify_translation_single_field_backup_fetch_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    validation_warnings = []
    parse_error = ""
    preflight_package = {}

    try:
        preflight_package = _read_json(SOURCE_PREFLIGHT_PACKAGE_PATH)
    except FileNotFoundError as exc:
        parse_error = f"Preflight package JSON not found: {exc}"
        validation_errors.append("preflight_package_missing")
    except (OSError, json.JSONDecodeError) as exc:
        parse_error = f"Could not parse preflight package JSON: {exc}"
        validation_errors.append("preflight_package_json_invalid")

    requested_scope = _read_requested_scope()
    scope_errors = _validate_requested_scope(requested_scope)
    validation_errors.extend(scope_errors)

    proposed_value = ""
    if preflight_package:
        package_errors, package_warnings = _validate_preflight_package(preflight_package, requested_scope)
        validation_errors.extend(package_errors)
        validation_warnings.extend(package_warnings)
        proposed_value = str((preflight_package.get("requested_scope") or {}).get("proposed_value") or "")

    validation_failures = _unique(validation_errors)
    validation_warnings = _unique(validation_warnings)
    query_result = _empty_query_result(requested_scope)
    if not validation_failures:
        query_result = _fetch_backup_from_shopify(requested_scope)
        if not query_result.get("success"):
            validation_failures.append(query_result.get("failure_type") or "shopify_read_query_failed")

    backup_fetch_status = "backup_ready" if not validation_failures else "blocked"
    backup_value = str(query_result.get("backup_value") or "")
    backup_value_present = bool(query_result.get("backup_value_present"))
    backup_value_chars = len(backup_value)
    end_time = utc_now_iso()
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "read-only-backup-fetch",
        "command_label": COMMAND_LABEL,
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "json_backup_fetch_path": str(BACKUP_FETCH_JSON_PATH),
        "html_backup_fetch_path": str(BACKUP_FETCH_HTML_PATH),
        "success": not validation_failures,
        "backup_fetch_status": backup_fetch_status,
        "requested_scope": requested_scope,
        "validated_scope": {
            "product_count": 1 if _valid_product_id(requested_scope["product_id"]) else 0,
            "locale_count": 1 if requested_scope["locale"] in ALLOWED_LOCALES else 0,
            "field_count": 1 if requested_scope["field"] == ALLOWED_FIELD else 0,
            "field_allowed": requested_scope["field"] == ALLOWED_FIELD,
            "allowed_field": ALLOWED_FIELD,
            "allowed_locales": sorted(ALLOWED_LOCALES),
            "scope_matches_preflight": not bool(
                preflight_package and "requested_scope_mismatch" in validation_failures
            ),
        },
        "source_preflight_status": preflight_package.get("preflight_status", "") if preflight_package else "",
        "source_proposed_value": proposed_value,
        "read_only_shopify_query_performed": bool(query_result.get("read_only_shopify_query_performed")),
        "shopify_query_type": "GraphQL translatableResource read-only query" if query_result else "",
        "shopify_http_status": query_result.get("http_status"),
        "backup_value_summary": {
            "backup_value_present": backup_value_present,
            "backup_value_chars": backup_value_chars,
            "backup_value_source": query_result.get("backup_value_source", ""),
            "target_translation_present": bool(query_result.get("target_translation_present")),
            "source_value_present": bool(query_result.get("source_value_present")),
            "target_translation_chars": int(query_result.get("target_translation_chars") or 0),
            "source_value_chars": int(query_result.get("source_value_chars") or 0),
            "note": _backup_summary_note(query_result),
        },
        "backup_value": backup_value,
        "backup_value_present": backup_value_present,
        "backup_value_chars": backup_value_chars,
        "backup_value_source": query_result.get("backup_value_source", ""),
        "backup_locale": requested_scope["locale"],
        "backup_field": requested_scope["field"],
        "backup_product_id": requested_scope["product_id"],
        "backup_generated_at": end_time,
        "readback_plan": {
            "readback_required": True,
            "readback_scope": {
                "product_id": requested_scope["product_id"],
                "locale": requested_scope["locale"],
                "field": requested_scope["field"],
            },
            "future_expected_value_source": "preflight requested_scope.proposed_value",
            "future_expected_value_chars": len(proposed_value),
            "future_must_compare_written_value_to_proposed_value": True,
            "readback_not_performed_in_this_phase": True,
        },
        "rollback_plan": {
            "rollback_required": True,
            "rollback_scope": {
                "product_id": requested_scope["product_id"],
                "locale": requested_scope["locale"],
                "field": requested_scope["field"],
            },
            "rollback_value_source": "backup_value from this report",
            "rollback_value_present": backup_value_present,
            "rollback_value_chars": backup_value_chars,
            "rollback_not_performed_in_this_phase": True,
        },
        "safety_summary": {
            "read_only_shopify_query_allowed": True,
            "single_product_only": True,
            "single_locale_only": True,
            "single_field_only": True,
            "allowed_field": ALLOWED_FIELD,
            "automatic_shopify_product_scan_allowed": False,
            "batch_product_read_allowed": False,
            "batch_locale_read_allowed": False,
            "batch_field_read_allowed": False,
            "shopify_write_allowed": False,
            "mutation_allowed": False,
            "translations_register_allowed": False,
            "database_write_allowed": False,
            "git_push_allowed": False,
        },
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
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": True,
        "validation_failures": _unique(validation_failures),
        "validation_warnings": validation_warnings,
        "parse_error": parse_error,
        "query_failure_type": query_result.get("failure_type", ""),
        "query_error": query_result.get("error", ""),
        "stdout_tail": query_result.get("stdout_tail", ""),
        "stderr_tail": query_result.get("stderr_tail", ""),
        "detected_issue_summary": _issue_summary(backup_fetch_status, validation_failures, query_result),
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
        "json_backup_fetch_path": str(json_path),
        "html_backup_fetch_path": str(html_path),
        "source_preflight_package_path": str(SOURCE_PREFLIGHT_PACKAGE_PATH),
        "backup_fetch_status": backup_fetch_status,
        "read_only_shopify_query_performed": payload["read_only_shopify_query_performed"],
        "shopify_query_type": payload["shopify_query_type"],
        "backup_value_present": backup_value_present,
        "backup_value_chars": backup_value_chars,
        "backup_value_source": payload["backup_value_source"],
        "backup_locale": payload["backup_locale"],
        "backup_field": payload["backup_field"],
        "backup_product_id": payload["backup_product_id"],
        "real_write_allowed": False,
        "translations_register_allowed": False,
        "translations_register_called": False,
        "shopify_write_performed": False,
        "apply_performed": False,
        "publish_performed": False,
        "translations_register_performed": False,
        "command_executed": False,
        "mutation_performed": False,
        "no_shopify_writes_performed": True,
        "all_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "validation_warnings_count": len(validation_warnings),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


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
    elif not _valid_product_id(product_id):
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


def _validate_preflight_package(report: dict, requested_scope: dict) -> tuple[list[str], list[str]]:
    errors = []
    warnings = []
    unsafe_checks = [
        ("task", report.get("task") == EXPECTED_PREFLIGHT_TASK),
        ("mode", report.get("mode") == EXPECTED_PREFLIGHT_MODE),
        ("preflight_status", report.get("preflight_status") == "ready_for_manual_review"),
        ("real_write_allowed", report.get("real_write_allowed") is False),
        ("real_write_attempted", report.get("real_write_attempted") is False),
        ("translations_register_allowed", report.get("translations_register_allowed") is False),
        ("translations_register_called", report.get("translations_register_called") is False),
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
        if name == "preflight_status":
            errors.append("preflight_not_ready")
        elif name in {
            "command_executed",
            "apply_performed",
            "publish_performed",
            "translations_register_performed",
        }:
            errors.append("command_or_apply_already_performed")
        elif name in {"shopify_write_performed", "all_no_write_confirmed"}:
            errors.append("no_write_not_confirmed")
        else:
            errors.append("unsafe_preflight_package")

    report_scope = report.get("requested_scope") or {}
    for key in ["product_id", "locale", "field"]:
        if report_scope.get(key) != requested_scope.get(key):
            errors.append("requested_scope_mismatch")

    validated_scope = report.get("validated_scope") or {}
    scope_valid = (
        validated_scope.get("product_count") == 1
        and validated_scope.get("locale_count") == 1
        and validated_scope.get("field_count") == 1
        and validated_scope.get("field_allowed") is True
        and report_scope.get("field") == ALLOWED_FIELD
    )
    if not scope_valid:
        errors.append("invalid_sandbox_scope")

    if report.get("no_shopify_writes_performed") is not True:
        warnings.append("source no_shopify_writes_performed is not true; backup fetch still performs no writes")

    return _unique(errors), _unique(warnings)


def _fetch_backup_from_shopify(scope: dict) -> dict:
    script = _build_django_shell_script(scope["product_id"], scope["locale"])
    command = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", script]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=False,
            timeout=DOCKER_TIMEOUT_SECONDS,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            **_empty_query_result(scope),
            "success": False,
            "failure_type": "timeout",
            "error": f"Read-only Shopify backup query timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
        }
    except FileNotFoundError as exc:
        return {
            **_empty_query_result(scope),
            "success": False,
            "failure_type": "missing_env",
            "error": str(exc),
        }
    except PermissionError as exc:
        return {
            **_empty_query_result(scope),
            "success": False,
            "failure_type": "docker_permission_denied",
            "error": str(exc),
        }

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        failure_type = parsed.get("failure_type") if parsed else ""
        if not failure_type:
            failure_type = _classify_command_failure(stdout, stderr)
        return {
            **_empty_query_result(scope),
            **parsed,
            "success": False,
            "exit_code": completed.returncode,
            "failure_type": failure_type,
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": parsed.get("error") or "Read-only Shopify backup query command failed.",
        }

    if not parsed:
        return {
            **_empty_query_result(scope),
            "success": False,
            "exit_code": completed.returncode,
            "failure_type": "command_error",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": "Read-only Shopify backup query did not return parseable JSON.",
        }

    return {
        **_empty_query_result(scope),
        **parsed,
        "success": bool(parsed.get("success")),
        "exit_code": completed.returncode,
        "failure_type": parsed.get("failure_type", ""),
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def _build_django_shell_script(product_id: str, locale: str) -> str:
    product_id_literal = json.dumps(product_id)
    locale_literal = json.dumps(locale)
    shop_literal = json.dumps(SHOP_DOMAIN)
    api_version_literal = json.dumps(SHOPIFY_API_VERSION)
    field_literal = json.dumps(ALLOWED_FIELD)
    return f"""
import json
import requests
from shopify_sync.models import ShopifyInstallation

product_id = {product_id_literal}
locale = {locale_literal}
shop = {shop_literal}
api_version = {api_version_literal}
field = {field_literal}

query = '''
query($id: ID!, $locale: String!) {{
  translatableResource(resourceId: $id) {{
    resourceId
    translatableContent {{
      key
      value
      digest
      locale
    }}
    translations(locale: $locale) {{
      key
      value
      locale
      outdated
    }}
  }}
}}
'''

result = {{
    "success": False,
    "read_only_shopify_query_performed": False,
    "shopify_query_type": "GraphQL translatableResource read-only query",
    "backup_product_id": product_id,
    "backup_locale": locale,
    "backup_field": field,
    "backup_value": "",
    "backup_value_present": False,
    "backup_value_source": "missing",
    "target_translation_present": False,
    "source_value_present": False,
    "target_translation_chars": 0,
    "source_value_chars": 0,
    "failure_type": "",
    "error": "",
}}

try:
    installation = ShopifyInstallation.objects.get(shop=shop)
    token_value = getattr(installation, "access_" + "token")
    endpoint = "https://" + installation.shop + "/admin/api/" + api_version + "/graphql.json"
    token_header = "X-Shopify-" + "Access-Token"
    headers = {{token_header: token_value, "Content-Type": "application/json"}}
    response = requests.post(
        endpoint,
        json={{"query": query, "variables": {{"id": product_id, "locale": locale}}}},
        headers=headers,
        timeout=30,
    )
    result["read_only_shopify_query_performed"] = True
    result["http_status"] = response.status_code
    try:
        data = response.json()
    except ValueError:
        result["failure_type"] = "command_error"
        result["error"] = "Shopify read-only query returned non-JSON response."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)

    if response.status_code >= 400:
        result["failure_type"] = "command_error"
        result["error"] = "Shopify read-only query failed with HTTP status " + str(response.status_code)
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    if data.get("errors"):
        result["failure_type"] = "command_error"
        result["error"] = "Shopify read-only query returned GraphQL errors."
        result["graphql_errors_count"] = len(data.get("errors") or [])
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)

    resource = ((data.get("data") or {{}}).get("translatableResource") or {{}})
    if not resource:
        result["failure_type"] = "command_error"
        result["error"] = "Shopify translatableResource was empty."
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)

    translations = resource.get("translations") or []
    content = resource.get("translatableContent") or []
    translation_item = next((item for item in translations if item.get("key") == field), {{}})
    source_item = next((item for item in content if item.get("key") == field), {{}})
    translation_value = str(translation_item.get("value") or "")
    source_value = str(source_item.get("value") or "")
    result["target_translation_present"] = bool(translation_value)
    result["source_value_present"] = bool(source_value)
    result["target_translation_chars"] = len(translation_value)
    result["source_value_chars"] = len(source_value)

    if translation_value:
        result["backup_value"] = translation_value
        result["backup_value_present"] = True
        result["backup_value_source"] = "translation"
    elif source_value:
        result["backup_value"] = source_value
        result["backup_value_present"] = True
        result["backup_value_source"] = "translatable_content"

    result["success"] = True
    print(json.dumps(result, ensure_ascii=True))
except ShopifyInstallation.DoesNotExist:
    result["failure_type"] = "missing_env"
    result["error"] = "Shopify installation was not found for the configured shop."
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
except Exception as exc:
    result["failure_type"] = "unknown"
    result["error"] = type(exc).__name__ + ": " + str(exc)
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
"""


def _empty_query_result(scope: dict) -> dict:
    return {
        "success": False,
        "read_only_shopify_query_performed": False,
        "shopify_query_type": "",
        "backup_product_id": scope.get("product_id", ""),
        "backup_locale": scope.get("locale", ""),
        "backup_field": scope.get("field", ""),
        "backup_value": "",
        "backup_value_present": False,
        "backup_value_source": "missing",
        "target_translation_present": False,
        "source_value_present": False,
        "target_translation_chars": 0,
        "source_value_chars": 0,
        "http_status": None,
        "failure_type": "",
        "error": "",
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _parse_json_from_stdout(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _classify_command_failure(stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if "access is denied" in combined or "permission denied" in combined or "docker_engine" in combined:
        return "docker_permission_denied"
    if "no such file or directory" in combined or "not recognized" in combined:
        return "missing_env"
    return "command_error"


def _decode_bytes(value: bytes | None) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _tail(text: str, max_lines: int = 80) -> str:
    return "\n".join(text.splitlines()[-max_lines:])


def _valid_product_id(product_id: str) -> bool:
    return bool(PRODUCT_GID_RE.match(product_id))


def _backup_summary_note(query_result: dict) -> str:
    if query_result.get("backup_value_present"):
        source = query_result.get("backup_value_source") or "unknown"
        chars = len(str(query_result.get("backup_value") or ""))
        return f"Current online meta_title backup value exists from {source}; {chars} chars."
    return "Current online meta_title backup value is empty or missing; empty backup generated."


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    BACKUP_FETCH_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(BACKUP_FETCH_JSON_PATH.read_text(encoding="utf-8"))
    return BACKUP_FETCH_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_FETCH_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return BACKUP_FETCH_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    scope_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Product ID", payload.get("requested_scope", {}).get("product_id", "")),
            ("Locale", payload.get("requested_scope", {}).get("locale", "")),
            ("Field", payload.get("requested_scope", {}).get("field", "")),
            ("Field Allowed", payload.get("validated_scope", {}).get("field_allowed", "")),
            ("Scope Matches Preflight", payload.get("validated_scope", {}).get("scope_matches_preflight", "")),
        ]
    )
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Timestamp", "timestamp"),
            ("Backup Fetch Status", "backup_fetch_status"),
            ("Source Preflight Status", "source_preflight_status"),
            ("Read-Only Shopify Query Performed", "read_only_shopify_query_performed"),
            ("Shopify Query Type", "shopify_query_type"),
            ("HTTP Status", "shopify_http_status"),
            ("Backup Value Present", "backup_value_present"),
            ("Backup Value Chars", "backup_value_chars"),
            ("Backup Value Source", "backup_value_source"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Translations Register Allowed", "translations_register_allowed"),
            ("Translations Register Called", "translations_register_called"),
            ("Mutation Performed", "mutation_performed"),
            ("Shopify Mutations Called", "shopify_mutations_called"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Apply Performed", "apply_performed"),
            ("Publish Performed", "publish_performed"),
            ("Translations Register Performed", "translations_register_performed"),
            ("Command Executed", "command_executed"),
            ("No Shopify Writes Performed", "no_shopify_writes_performed"),
            ("All No-Write Confirmed", "all_no_write_confirmed"),
            ("Future Required Flag", "future_required_flag"),
            ("Validation Failures", "validation_failures"),
            ("Validation Warnings", "validation_warnings"),
        ]
    )
    plans_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Readback Plan", payload.get("readback_plan", {})),
            ("Rollback Plan", payload.get("rollback_plan", {})),
            ("Safety Summary", payload.get("safety_summary", {})),
        ]
    )
    backup_value = payload.get("backup_value", "")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Single-Field Backup Fetch</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 280px; }}
    pre {{ white-space: pre-wrap; overflow-wrap: anywhere; background: #f6f8fa; padding: 12px; border: 1px solid #d0d7de; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Shopify Single-Field Backup Fetch</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Requested Scope</h2>
  <table><tbody>{scope_rows}</tbody></table>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Backup Value</h2>
  <pre>{escape(str(backup_value))}</pre>
  <h2>Plans</h2>
  <table><tbody>{plans_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task performs at most one read-only Shopify GraphQL query.</li>
    <li>No Shopify mutations were called.</li>
    <li>No translationsRegister call was performed.</li>
    <li>No Shopify writes were performed.</li>
    <li>Only one product, one locale, and the meta_title field are accepted.</li>
    <li>Future rollback must use this backup only for the same product / locale / field.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(backup_fetch_status: str, validation_failures: list[str], query_result: dict) -> str:
    if validation_failures:
        return "Single-field backup fetch blocked: " + ", ".join(_unique(validation_failures))
    if query_result.get("backup_value_present"):
        return "Single-field read-only backup fetch completed. No Shopify writes performed."
    return "Single-field read-only backup fetch completed with empty backup value. No Shopify writes performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify single-field read-only backup fetch completed.\n"
        f"Source preflight package: {payload.get('source_preflight_package_path')}\n"
        f"Backup fetch status: {payload.get('backup_fetch_status')}\n"
        f"Requested scope: {payload.get('requested_scope')}\n"
        f"Read-only Shopify query performed: {payload.get('read_only_shopify_query_performed')}\n"
        f"Backup value present: {payload.get('backup_value_present')}\n"
        f"Backup value chars: {payload.get('backup_value_chars')}\n"
        f"Backup value source: {payload.get('backup_value_source')}\n"
        f"Validation failures: {len(payload.get('validation_failures') or [])}\n"
        "Backup fetch JSON:\n"
        f"{json_path}\n\n"
        "Backup fetch HTML:\n"
        f"{html_path}\n"
        "Read-only backup fetch only. No Shopify writes performed by this task.\n"
        "mutation_performed=false; shopify_mutations_called=[]; translationsRegister_called=false.\n"
        "shopify_write_performed=false; apply_performed=false; publish_performed=false.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep backup fetch files\n"
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
