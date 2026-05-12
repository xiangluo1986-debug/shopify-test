import json
import os
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_small_batch_apply_execute"
COMMAND_LABEL = "shopify_translation_small_batch_apply_execute"
SOURCE_SMALL_BATCH_PLAN_PATH = LOG_DIR / "shopify_translation_small_batch_apply_plan_package.json"
SMALL_BATCH_APPLY_EXECUTE_JSON_PATH = LOG_DIR / "shopify_translation_small_batch_apply_execute.json"
SMALL_BATCH_APPLY_EXECUTE_HTML_PATH = LOG_DIR / "shopify_translation_small_batch_apply_execute.html"

EXECUTION_ACK_ENV = "SHOPIFY_TRANSLATION_SMALL_BATCH_EXECUTION_ACK"
EXECUTION_ACK_VALUE = "YES_I_APPROVE_SMALL_BATCH_SHOPIFY_TRANSLATION_WRITE"
SUPPORTED_MODES = {"dry-run", "real-run", "execute-real-write"}
REAL_RUN_MODES = {"real-run", "execute-real-write"}

READY_PLAN_STATUS = "small_batch_apply_plan_ready_for_manual_review"
EXPECTED_PRODUCT_ID = "gid://shopify/Product/7655686799427"
EXPECTED_LOCALE = "ja"
ALLOWED_FIELDS = ["meta_title", "meta_description"]
FIELD_MAX_CHARS = {
    "meta_title": 60,
    "meta_description": 160,
}
MAX_ENTRIES = 5
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
DOCKER_TIMEOUT_SECONDS = 120


def run_shopify_translation_small_batch_apply_execute_task(mode: str) -> dict:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"{TASK_NAME} only supports dry-run, real-run, or execute-real-write mode.")

    started = time.time()
    start_time = utc_now_iso()
    validation_errors = []
    parse_errors = []
    plan_report = {}

    try:
        plan_report = _read_json(SOURCE_SMALL_BATCH_PLAN_PATH)
    except FileNotFoundError as exc:
        parse_errors.append(f"Small batch apply plan JSON not found: {exc}")
        validation_errors.append("missing_small_batch_apply_plan_report")
    except (OSError, json.JSONDecodeError) as exc:
        parse_errors.append(f"Could not parse small batch apply plan JSON: {exc}")
        validation_errors.append("small_batch_apply_plan_json_invalid")

    ack_value = os.environ.get(EXECUTION_ACK_ENV, "").strip()
    ack_present = bool(ack_value)
    ack_valid = ack_value == EXECUTION_ACK_VALUE
    approval_mode = os.environ.get("REMOTE_APPROVAL_MODE", "")
    if mode in REAL_RUN_MODES:
        if not ack_present:
            validation_errors.append("missing_small_batch_execution_ack")
        elif not ack_valid:
            validation_errors.append("invalid_small_batch_execution_ack")
        if approval_mode and approval_mode != "local":
            validation_errors.append("approval_not_local")

    if plan_report:
        validation_errors.extend(_validate_plan_report(plan_report))

    blocking_conditions = _blocking_conditions(validation_errors)
    entries = plan_report.get("entries", []) if isinstance(plan_report.get("entries"), list) else []
    real_run_attempted = mode in REAL_RUN_MODES and not blocking_conditions
    execution_result = _empty_execution_result(plan_report, entries)
    if real_run_attempted:
        execution_result = _execute_real_write_and_readback(plan_report, entries)

    execution_status = _execution_status(mode, blocking_conditions, execution_result)
    translations_register_called = bool(execution_result.get("translations_register_called"))
    mutation_performed = bool(execution_result.get("mutation_performed"))
    shopify_write_performed = bool(execution_result.get("shopify_write_performed"))
    shopify_api_call_performed = bool(execution_result.get("shopify_api_call_performed"))
    readback_performed = bool(execution_result.get("readback_performed"))
    readback_all_entries_match = bool(execution_result.get("readback_all_entries_match"))
    readback_matched_entry_count = int(execution_result.get("readback_matched_entry_count") or 0)
    rollback_approval_required = _rollback_approval_required(execution_status, execution_result)
    small_batch_write_performed = bool(execution_result.get("small_batch_write_performed"))
    real_apply_performed = bool(translations_register_called or mutation_performed or shopify_write_performed)
    no_new_shopify_writes_performed = not (translations_register_called or mutation_performed or shopify_write_performed)
    all_new_actions_no_write_confirmed = no_new_shopify_writes_performed
    success = (
        execution_status == "dry_run_small_batch_write_not_executed"
        if mode == "dry-run"
        else execution_status == "small_batch_real_write_succeeded_and_verified"
    )
    end_time = utc_now_iso()

    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": mode,
        "command_label": COMMAND_LABEL,
        "source_small_batch_apply_plan_path": str(SOURCE_SMALL_BATCH_PLAN_PATH),
        "json_small_batch_apply_execute_path": str(SMALL_BATCH_APPLY_EXECUTE_JSON_PATH),
        "html_small_batch_apply_execute_path": str(SMALL_BATCH_APPLY_EXECUTE_HTML_PATH),
        "success": success,
        "execution_status": execution_status,
        "plan_status": plan_report.get("plan_status", ""),
        "product_id": plan_report.get("product_id", ""),
        "locale": plan_report.get("locale", ""),
        "entry_count": len(entries),
        "allowed_fields": ALLOWED_FIELDS,
        "source_plan_summary": _source_plan_summary(plan_report, entries),
        "validated_execution_scope": _validated_execution_scope(plan_report, entries),
        "planned_entries": _planned_entries(entries),
        "small_batch_execution_ack_summary": {
            "ack_env": EXECUTION_ACK_ENV,
            "ack_present": ack_present,
            "ack_value_matches_required_phrase": ack_valid,
            "ack_required_value": EXECUTION_ACK_VALUE,
            "ack_effective": bool(real_run_attempted),
            "ack_note": "ACK is required for real-run. Dry-run never writes Shopify.",
        },
        "dry_run_execution_summary": {
            "dry_run_only": mode == "dry-run",
            "would_attempt_real_write": mode in REAL_RUN_MODES,
            "would_call_shopify_api": bool(real_run_attempted),
            "would_call_mutation": bool(real_run_attempted),
            "would_call_translations_register": bool(real_run_attempted),
            "would_publish": False,
            "would_readback": bool(real_run_attempted),
            "would_rollback": False,
            "entries_validated": len(entries),
            "future_mutation_name": "translationsRegister",
        },
        "translations_register_execution_summary": _translations_register_execution_summary(
            execution_result, mode, real_run_attempted
        ),
        "readback_summary": _readback_summary(execution_result, entries),
        "verification_summary": _verification_summary(execution_result, entries),
        "failure_summary": _failure_summary(execution_status, execution_result, blocking_conditions),
        "rollback_approval_requirement": _rollback_approval_requirement(execution_status, execution_result),
        "future_real_run_requirements": _future_real_run_requirements(),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(mode, real_run_attempted, execution_result),
        "small_batch_execute_task": True,
        "small_batch_execute_dry_run_only": mode == "dry-run",
        "small_batch_execution_ack_present": ack_present,
        "small_batch_execution_ack_valid": ack_valid,
        "real_write_allowed": bool(real_run_attempted),
        "write_execution_allowed": bool(real_run_attempted),
        "translations_register_allowed": bool(real_run_attempted),
        "translations_register_called": translations_register_called,
        "translations_register_performed": translations_register_called,
        "shopify_api_call_performed": shopify_api_call_performed,
        "shopify_write_performed": shopify_write_performed,
        "mutation_performed": mutation_performed,
        "shopify_mutations_called": ["translationsRegister"] if translations_register_called else [],
        "readback_performed": readback_performed,
        "readback_all_entries_match": readback_all_entries_match,
        "readback_matched_entry_count": readback_matched_entry_count,
        "rollback_approval_required": rollback_approval_required,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "small_batch_write_performed": small_batch_write_performed,
        "real_apply_performed": real_apply_performed,
        "command_executed": False,
        "no_new_shopify_writes_performed": no_new_shopify_writes_performed,
        "all_new_actions_no_write_confirmed": all_new_actions_no_write_confirmed,
        "validation_failures": _unique(validation_errors),
        "parse_errors": parse_errors,
        "execution_failure_type": execution_result.get("failure_type", ""),
        "execution_failure_reason": execution_result.get("failure_reason", ""),
        "stdout_tail": execution_result.get("stdout_tail", ""),
        "stderr_tail": execution_result.get("stderr_tail", ""),
        "detected_issue_summary": _issue_summary(execution_status, blocking_conditions),
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
        "json_small_batch_apply_execute_path": str(json_path),
        "html_small_batch_apply_execute_path": str(html_path),
        "execution_status": execution_status,
        "plan_status": plan_report.get("plan_status", ""),
        "small_batch_execute_task": True,
        "small_batch_execute_dry_run_only": mode == "dry-run",
        "small_batch_execution_ack_present": ack_present,
        "small_batch_execution_ack_valid": ack_valid,
        "entry_count": len(entries),
        "real_write_allowed": bool(real_run_attempted),
        "write_execution_allowed": bool(real_run_attempted),
        "translations_register_allowed": bool(real_run_attempted),
        "translations_register_called": translations_register_called,
        "shopify_api_call_performed": shopify_api_call_performed,
        "shopify_write_performed": shopify_write_performed,
        "mutation_performed": mutation_performed,
        "readback_performed": readback_performed,
        "readback_all_entries_match": readback_all_entries_match,
        "readback_matched_entry_count": readback_matched_entry_count,
        "rollback_approval_required": rollback_approval_required,
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "small_batch_write_performed": small_batch_write_performed,
        "real_apply_performed": real_apply_performed,
        "no_new_shopify_writes_performed": no_new_shopify_writes_performed,
        "all_new_actions_no_write_confirmed": all_new_actions_no_write_confirmed,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def _validate_plan_report(report: dict) -> list[str]:
    errors = []
    if report.get("task") != "shopify_translation_small_batch_apply_plan_package":
        errors.append("small_batch_apply_plan_not_ready")
    if report.get("plan_status") != READY_PLAN_STATUS:
        errors.append("small_batch_apply_plan_not_ready")
    if report.get("plan_package_only") is not True:
        errors.append("small_batch_apply_plan_not_ready")
    if report.get("real_write_allowed") is not False:
        errors.append("unexpected_side_effect_risk")
    if report.get("next_step_requires_separate_execute_task") is not True:
        errors.append("small_batch_apply_plan_not_ready")

    entries = report.get("entries")
    if not isinstance(entries, list):
        errors.append("small_batch_apply_plan_not_ready")
        entries = []
    if len(entries) > MAX_ENTRIES:
        errors.append("too_many_entries")
    if int(report.get("entry_count") or len(entries)) > MAX_ENTRIES:
        errors.append("too_many_entries")

    product_ids = {entry.get("product_id") for entry in entries if entry.get("product_id")}
    locales = {entry.get("locale") for entry in entries if entry.get("locale")}
    if len(product_ids) != 1 or product_ids != {EXPECTED_PRODUCT_ID} or report.get("product_id") != EXPECTED_PRODUCT_ID:
        errors.append("multiple_products")
    if len(locales) != 1 or locales != {EXPECTED_LOCALE} or report.get("locale") != EXPECTED_LOCALE:
        errors.append("multiple_locales")

    for entry in entries:
        field = entry.get("field")
        value = str(entry.get("proposed_value") or "")
        if field not in ALLOWED_FIELDS:
            errors.append("invalid_field")
            continue
        if entry.get("field_allowed") is not True:
            errors.append("invalid_field")
        if not value or entry.get("value_non_empty") is not True:
            errors.append("empty_proposed_value")
        if len(value) > FIELD_MAX_CHARS[field] or entry.get("value_length_allowed") is not True:
            errors.append("value_too_long")
        if entry.get("validation_status") != "valid":
            errors.append("small_batch_apply_plan_not_ready")

    for flag in [
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "readback_performed",
        "rollback_performed",
        "publish_performed",
        "bulk_write_performed",
        "real_apply_performed",
    ]:
        if report.get(flag) is True:
            errors.append("unexpected_side_effect_risk")
    if report.get("no_new_shopify_writes_performed") is not True:
        errors.append("unexpected_side_effect_risk")
    if report.get("all_new_actions_no_write_confirmed") is not True:
        errors.append("unexpected_side_effect_risk")
    return _unique(errors)


def _source_plan_summary(report: dict, entries: list[dict]) -> dict:
    return {
        "source_plan_loaded": bool(report),
        "source_plan_status": report.get("plan_status", "") if report else "",
        "source_product_id": report.get("product_id", "") if report else "",
        "source_locale": report.get("locale", "") if report else "",
        "source_entry_count": len(entries),
        "source_allowed_fields": report.get("allowed_fields", []) if report else [],
        "source_manual_review_required": report.get("manual_review_required") is True if report else False,
        "source_real_write_allowed": report.get("real_write_allowed") is True if report else False,
        "source_next_step_requires_separate_execute_task": (
            report.get("next_step_requires_separate_execute_task") is True if report else False
        ),
    }


def _validated_execution_scope(report: dict, entries: list[dict]) -> dict:
    product_ids = {entry.get("product_id") for entry in entries if entry.get("product_id")}
    locales = {entry.get("locale") for entry in entries if entry.get("locale")}
    fields = [entry.get("field") for entry in entries]
    return {
        "product_count": len(product_ids),
        "locale_count": len(locales),
        "entry_count": len(entries),
        "max_entries": MAX_ENTRIES,
        "allowed_fields": ALLOWED_FIELDS,
        "product_id": report.get("product_id", "") if report else "",
        "locale": report.get("locale", "") if report else "",
        "all_fields_allowed": all(field in ALLOWED_FIELDS for field in fields),
        "has_publish_risk": False,
        "has_rollback_risk": False,
        "has_non_translation_field": any(field not in ALLOWED_FIELDS for field in fields),
    }


def _planned_entries(entries: list[dict]) -> list[dict]:
    planned = []
    for entry in entries:
        planned.append(
            {
                "entry_index": entry.get("entry_index"),
                "product_id": entry.get("product_id", ""),
                "locale": entry.get("locale", ""),
                "field": entry.get("field", ""),
                "current_value_if_known": entry.get("current_value_if_known", ""),
                "proposed_value": entry.get("proposed_value", ""),
                "proposed_value_chars": int(entry.get("proposed_value_chars") or len(str(entry.get("proposed_value") or ""))),
                "max_chars": int(entry.get("max_chars") or FIELD_MAX_CHARS.get(entry.get("field"), 0)),
                "validation_status": entry.get("validation_status", ""),
                "would_write_in_this_phase": False,
                "future_mutation_name": "translationsRegister",
            }
        )
    return planned


def _blocking_conditions(validation_errors: list[str]) -> list[str]:
    mapping = {
        "missing_small_batch_apply_plan_report": "blocked_missing_small_batch_apply_plan_report",
        "small_batch_apply_plan_not_ready": "blocked_small_batch_apply_plan_not_ready",
        "missing_small_batch_execution_ack": "blocked_missing_small_batch_execution_ack",
        "invalid_small_batch_execution_ack": "blocked_invalid_small_batch_execution_ack",
        "approval_not_local": "blocked_approval_not_local",
        "too_many_entries": "blocked_too_many_entries",
        "multiple_products": "blocked_multiple_products",
        "multiple_locales": "blocked_multiple_locales",
        "invalid_field": "blocked_invalid_field",
        "empty_proposed_value": "blocked_empty_proposed_value",
        "value_too_long": "blocked_value_too_long",
        "unexpected_side_effect_risk": "blocked_unexpected_side_effect_risk",
    }
    return _unique([mapping.get(error, error) for error in validation_errors])


def _execution_status(mode: str, blocking_conditions: list[str], execution_result: dict) -> str:
    if not blocking_conditions and mode == "dry-run":
        return "dry_run_small_batch_write_not_executed"
    for status in [
        "blocked_missing_small_batch_apply_plan_report",
        "blocked_small_batch_apply_plan_not_ready",
        "blocked_missing_small_batch_execution_ack",
        "blocked_invalid_small_batch_execution_ack",
        "blocked_approval_not_local",
        "blocked_too_many_entries",
        "blocked_multiple_products",
        "blocked_multiple_locales",
        "blocked_invalid_field",
        "blocked_empty_proposed_value",
        "blocked_value_too_long",
        "blocked_unexpected_side_effect_risk",
    ]:
        if status in blocking_conditions:
            return status
    if execution_result.get("success") and execution_result.get("readback_all_entries_match"):
        return "small_batch_real_write_succeeded_and_verified"
    if execution_result.get("shopify_write_performed") and not execution_result.get("readback_all_entries_match"):
        return "small_batch_real_write_completed_but_readback_mismatch"
    return "small_batch_real_write_failed" if mode in REAL_RUN_MODES else "blocked"


def _future_real_run_requirements() -> list[str]:
    return [
        f"{EXECUTION_ACK_ENV} must exactly equal {EXECUTION_ACK_VALUE}.",
        "Mode must be real-run or execute-real-write.",
        "Approval mode must be local.",
        "The source plan must still be ready for manual review.",
        "The execution scope must remain one product, one locale, at most five entries.",
        "Only meta_title and meta_description are allowed.",
        "No publish, rollback, non-translation field, full-store scan, or batch expansion is allowed.",
        "Real execution performs one translationsRegister mutation containing the approved entries.",
        "Immediate readback must verify every entry.",
        "Rollback is never automatic and requires separate approval.",
    ]


def _empty_execution_result(plan_report: dict, entries: list[dict]) -> dict:
    return {
        "success": False,
        "execution_attempted": False,
        "product_id": plan_report.get("product_id", "") if plan_report else "",
        "locale": plan_report.get("locale", "") if plan_report else "",
        "entry_count": len(entries),
        "shopify_api_call_performed": False,
        "shopify_api_call_count": 0,
        "translations_register_called": False,
        "mutation_performed": False,
        "shopify_write_performed": False,
        "small_batch_write_performed": False,
        "readback_performed": False,
        "readback_results": [],
        "readback_all_entries_match": False,
        "readback_matched_entry_count": 0,
        "real_write_count": 0,
        "shopify_mutations_called": [],
        "http_statuses": [],
        "user_errors": [],
        "graphql_errors_count": 0,
        "translatable_content_digest_available_count": 0,
        "failure_type": "",
        "failure_reason": "",
        "stdout_tail": "",
        "stderr_tail": "",
    }


def _execute_real_write_and_readback(plan_report: dict, entries: list[dict]) -> dict:
    script = _build_django_shell_script(plan_report, entries)
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
            **_empty_execution_result(plan_report, entries),
            "execution_attempted": True,
            "failure_type": "timeout",
            "failure_reason": f"Small batch real write command timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
        }
    except FileNotFoundError as exc:
        return {
            **_empty_execution_result(plan_report, entries),
            "execution_attempted": True,
            "failure_type": "missing_env",
            "failure_reason": str(exc),
        }
    except PermissionError as exc:
        return {
            **_empty_execution_result(plan_report, entries),
            "execution_attempted": True,
            "failure_type": "docker_permission_denied",
            "failure_reason": str(exc),
        }

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if not parsed:
        parsed = {
            **_empty_execution_result(plan_report, entries),
            "execution_attempted": True,
            "failure_type": "command_error",
            "failure_reason": "Small batch real write command did not return parseable JSON.",
        }
    parsed.setdefault("success", completed.returncode == 0 and bool(parsed.get("readback_all_entries_match")))
    parsed.setdefault("exit_code", completed.returncode)
    parsed["stdout_tail"] = _tail(stdout)
    parsed["stderr_tail"] = _tail(stderr)
    if completed.returncode != 0 and not parsed.get("failure_type"):
        parsed["failure_type"] = _classify_command_failure(stdout, stderr)
    if completed.returncode != 0 and not parsed.get("failure_reason"):
        parsed["failure_reason"] = "Small batch real write command failed."
    return {**_empty_execution_result(plan_report, entries), **parsed}


def _build_django_shell_script(plan_report: dict, entries: list[dict]) -> str:
    product_id_literal = json.dumps(plan_report["product_id"])
    locale_literal = json.dumps(plan_report["locale"])
    entries_literal = json.dumps(
        [
            {
                "field": entry["field"],
                "proposed_value": entry["proposed_value"],
            }
            for entry in entries
        ],
        ensure_ascii=True,
    )
    shop_literal = json.dumps(SHOP_DOMAIN)
    api_version_literal = json.dumps(SHOPIFY_API_VERSION)
    return f"""
import json
import requests
from shopify_sync.models import ShopifyInstallation

product_id = {product_id_literal}
locale = {locale_literal}
entries = {entries_literal}
shop = {shop_literal}
api_version = {api_version_literal}

read_query = '''
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

mutation = '''
mutation($resourceId: ID!, $translations: [TranslationInput!]!) {{
  translationsRegister(resourceId: $resourceId, translations: $translations) {{
    userErrors {{
      field
      message
    }}
    translations {{
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
    "execution_attempted": True,
    "product_id": product_id,
    "locale": locale,
    "entry_count": len(entries),
    "shopify_api_call_performed": False,
    "shopify_api_call_count": 0,
    "translations_register_called": False,
    "mutation_performed": False,
    "shopify_write_performed": False,
    "small_batch_write_performed": False,
    "readback_performed": False,
    "readback_results": [],
    "readback_all_entries_match": False,
    "readback_matched_entry_count": 0,
    "real_write_count": 0,
    "shopify_mutations_called": [],
    "http_statuses": [],
    "user_errors": [],
    "graphql_errors_count": 0,
    "translatable_content_digest_available_count": 0,
    "failure_type": "",
    "failure_reason": "",
}}

def finish(code):
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(code)

def fail(failure_type, reason, code=1):
    result["failure_type"] = failure_type
    result["failure_reason"] = reason
    finish(code)

try:
    installation = ShopifyInstallation.objects.get(shop=shop)
    token_value = getattr(installation, "access_" + "token")
    endpoint = "https://" + installation.shop + "/admin/api/" + api_version + "/graphql.json"
    token_header = "X-Shopify-" + "Access-Token"
    headers = {{token_header: token_value, "Content-Type": "application/json"}}

    def post_graphql(query, variables):
        response = requests.post(endpoint, json={{"query": query, "variables": variables}}, headers=headers, timeout=30)
        result["shopify_api_call_performed"] = True
        result["shopify_api_call_count"] += 1
        result["http_statuses"].append(response.status_code)
        try:
            data = response.json()
        except ValueError:
            fail("shopify_api_error", "Shopify GraphQL response was not JSON.")
        if response.status_code >= 400:
            fail("shopify_api_error", "Shopify GraphQL request failed with HTTP status " + str(response.status_code))
        if data.get("errors"):
            result["graphql_errors_count"] = len(data.get("errors") or [])
            fail("shopify_graphql_errors", "Shopify GraphQL returned errors.")
        return data.get("data") or {{}}

    read_data = post_graphql(read_query, {{"id": product_id, "locale": locale}})
    resource = read_data.get("translatableResource") or {{}}
    if not resource:
        fail("readback_missing_resource", "Shopify translatableResource was empty before mutation.")
    content_by_key = {{item.get("key"): item for item in (resource.get("translatableContent") or [])}}
    translations_payload = []
    for entry in entries:
        field = entry["field"]
        source_item = content_by_key.get(field) or {{}}
        digest = source_item.get("digest")
        if not digest:
            fail("missing_translatable_content_digest", field + " translatableContent digest was not available.")
        result["translatable_content_digest_available_count"] += 1
        translations_payload.append(
            {{
                "locale": locale,
                "key": field,
                "value": entry["proposed_value"],
                "translatableContentDigest": digest,
            }}
        )

    result["translations_register_called"] = True
    result["mutation_performed"] = True
    result["shopify_mutations_called"] = ["translationsRegister"]
    mutation_data = post_graphql(mutation, {{"resourceId": product_id, "translations": translations_payload}})
    register_result = mutation_data.get("translationsRegister") or {{}}
    user_errors = register_result.get("userErrors") or []
    result["user_errors"] = user_errors
    if user_errors:
        fail("translations_register_user_errors", "translationsRegister returned userErrors.")
    result["shopify_write_performed"] = True
    result["small_batch_write_performed"] = True
    result["real_write_count"] = len(entries)

    result["readback_performed"] = True
    readback_data = post_graphql(read_query, {{"id": product_id, "locale": locale}})
    readback_resource = readback_data.get("translatableResource") or {{}}
    translations_by_key = {{item.get("key"): item for item in (readback_resource.get("translations") or [])}}
    matched = 0
    readback_results = []
    for entry in entries:
        field = entry["field"]
        item = translations_by_key.get(field) or {{}}
        readback_value = str(item.get("value") or "")
        matches = readback_value == entry["proposed_value"]
        if matches:
            matched += 1
        readback_results.append(
            {{
                "field": field,
                "expected_value": entry["proposed_value"],
                "readback_value": readback_value,
                "readback_value_present": bool(readback_value),
                "readback_locale": item.get("locale"),
                "readback_outdated": item.get("outdated"),
                "matches_proposed_value": matches,
            }}
        )
    result["readback_results"] = readback_results
    result["readback_matched_entry_count"] = matched
    result["readback_all_entries_match"] = matched == len(entries)
    if matched != len(entries):
        fail("readback_mismatch", "At least one small batch entry readback value did not match proposed_value.")

    result["success"] = True
    finish(0)
except ShopifyInstallation.DoesNotExist:
    fail("missing_env", "Shopify installation was not found for the configured shop.")
except SystemExit:
    raise
except Exception as exc:
    fail("unknown", type(exc).__name__ + ": " + str(exc))
"""


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


def _translations_register_execution_summary(execution_result: dict, mode: str, real_run_attempted: bool) -> dict:
    return {
        "mode": mode,
        "real_run_attempted": real_run_attempted,
        "translations_register_allowed": real_run_attempted,
        "translations_register_called": bool(execution_result.get("translations_register_called")),
        "mutation_performed": bool(execution_result.get("mutation_performed")),
        "shopify_write_performed": bool(execution_result.get("shopify_write_performed")),
        "small_batch_write_performed": bool(execution_result.get("small_batch_write_performed")),
        "shopify_api_call_performed": bool(execution_result.get("shopify_api_call_performed")),
        "shopify_api_call_count": int(execution_result.get("shopify_api_call_count") or 0),
        "real_write_count": int(execution_result.get("real_write_count") or 0),
        "mutation_name": "translationsRegister",
        "user_errors": execution_result.get("user_errors") or [],
        "http_statuses": execution_result.get("http_statuses") or [],
    }


def _readback_summary(execution_result: dict, entries: list[dict]) -> dict:
    return {
        "readback_required": True,
        "readback_performed": bool(execution_result.get("readback_performed")),
        "readback_entry_count": len(entries),
        "readback_results": execution_result.get("readback_results") or [],
        "readback_all_entries_match": bool(execution_result.get("readback_all_entries_match")),
        "readback_matched_entry_count": int(execution_result.get("readback_matched_entry_count") or 0),
    }


def _verification_summary(execution_result: dict, entries: list[dict]) -> dict:
    return {
        "verification_required": True,
        "entry_count": len(entries),
        "readback_performed": bool(execution_result.get("readback_performed")),
        "readback_all_entries_match": bool(execution_result.get("readback_all_entries_match")),
        "readback_matched_entry_count": int(execution_result.get("readback_matched_entry_count") or 0),
        "verification_passed": bool(execution_result.get("success"))
        and bool(execution_result.get("readback_all_entries_match")),
    }


def _failure_summary(execution_status: str, execution_result: dict, blocking_conditions: list[str]) -> dict:
    return {
        "failure": execution_status
        not in {"dry_run_small_batch_write_not_executed", "small_batch_real_write_succeeded_and_verified"},
        "failure_reason": execution_result.get("failure_reason", ""),
        "failure_type": execution_result.get("failure_type", ""),
        "blocking_conditions": blocking_conditions,
        "rollback_approval_required": _rollback_approval_required(execution_status, execution_result),
    }


def _rollback_approval_required(execution_status: str, execution_result: dict) -> bool:
    if execution_status in {"small_batch_real_write_completed_but_readback_mismatch", "small_batch_real_write_failed"}:
        return bool(
            execution_result.get("translations_register_called")
            or execution_result.get("mutation_performed")
            or execution_result.get("shopify_write_performed")
        )
    return False


def _rollback_approval_requirement(execution_status: str, execution_result: dict) -> dict:
    return {
        "rollback_approval_required": _rollback_approval_required(execution_status, execution_result),
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "automatic_rollback_allowed": False,
        "rollback_requires_separate_approval": True,
        "rollback_note": "Rollback is never automatic for small batch execution.",
    }


def _safety_summary(mode: str, real_run_attempted: bool, execution_result: dict) -> dict:
    return {
        "mode": mode,
        "small_batch_execute_task": True,
        "real_run_attempted": real_run_attempted,
        "dry_run_never_writes": mode == "dry-run",
        "real_write_allowed": real_run_attempted,
        "write_execution_allowed": real_run_attempted,
        "translations_register_allowed": real_run_attempted,
        "shopify_api_call_allowed": real_run_attempted,
        "shopify_write_allowed": real_run_attempted,
        "mutation_allowed": real_run_attempted,
        "readback_allowed": real_run_attempted,
        "rollback_allowed": False,
        "publish_allowed": False,
        "bulk_write_allowed": False,
        "real_apply_allowed": real_run_attempted,
        "shopify_api_call_performed": bool(execution_result.get("shopify_api_call_performed")),
        "shopify_write_performed": bool(execution_result.get("shopify_write_performed")),
        "mutation_performed": bool(execution_result.get("mutation_performed")),
        "translations_register_called": bool(execution_result.get("translations_register_called")),
        "readback_performed": bool(execution_result.get("readback_performed")),
        "rollback_performed": False,
        "automatic_rollback_performed": False,
        "publish_performed": False,
        "bulk_write_performed": False,
        "max_entries": MAX_ENTRIES,
        "max_products": 1,
        "max_locales": 1,
        "allowed_fields": ALLOWED_FIELDS,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    SMALL_BATCH_APPLY_EXECUTE_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(SMALL_BATCH_APPLY_EXECUTE_JSON_PATH.read_text(encoding="utf-8"))
    return SMALL_BATCH_APPLY_EXECUTE_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    SMALL_BATCH_APPLY_EXECUTE_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return SMALL_BATCH_APPLY_EXECUTE_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Execution Status", "execution_status"),
            ("Plan Status", "plan_status"),
            ("Product ID", "product_id"),
            ("Locale", "locale"),
            ("Entry Count", "entry_count"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Translations Register Called", "translations_register_called"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("Readback Performed", "readback_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("Publish Performed", "publish_performed"),
            ("Bulk Write Performed", "bulk_write_performed"),
            ("Real Apply Performed", "real_apply_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No-Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    entry_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(entry.get('entry_index')))}</td>"
        f"<td>{escape(str(entry.get('field')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars')))} / {escape(str(entry.get('max_chars')))}</td>"
        f"<td>{escape(str(entry.get('would_write_in_this_phase')))}</td>"
        "</tr>"
        for entry in payload.get("planned_entries", [])
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Source Plan Summary", payload.get("source_plan_summary", {})),
            ("Validated Execution Scope", payload.get("validated_execution_scope", {})),
            ("Small Batch Execution Ack Summary", payload.get("small_batch_execution_ack_summary", {})),
            ("Dry Run Execution Summary", payload.get("dry_run_execution_summary", {})),
            ("Translations Register Execution Summary", payload.get("translations_register_execution_summary", {})),
            ("Readback Summary", payload.get("readback_summary", {})),
            ("Verification Summary", payload.get("verification_summary", {})),
            ("Failure Summary", payload.get("failure_summary", {})),
            ("Rollback Approval Requirement", payload.get("rollback_approval_requirement", {})),
            ("Future Real Run Requirements", payload.get("future_real_run_requirements", [])),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Small Batch Apply Execute</title>
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
  <h1>Shopify Small Batch Apply Execute</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Planned Entries</h2>
  <table>
    <thead>
      <tr><th>Index</th><th>Field</th><th>Proposed Value</th><th>Chars</th><th>Would Write In This Phase</th></tr>
    </thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Execution Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>Dry-run mode never calls Shopify APIs or writes Shopify.</li>
    <li>Real-run mode requires the exact small batch execution ACK and local approval.</li>
    <li>Rollback is never automatic.</li>
    <li>Bulk write, publish, full-store scan, unsupported fields, and scope expansion are forbidden.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(execution_status: str, blocking_conditions: list[str]) -> str:
    if blocking_conditions:
        return "Small batch apply execute blocked: " + ", ".join(blocking_conditions)
    if execution_status == "dry_run_small_batch_write_not_executed":
        return "Small batch apply execute dry-run completed. No Shopify action performed."
    if execution_status == "small_batch_real_write_succeeded_and_verified":
        return "Small batch Shopify translationsRegister write succeeded and all readback entries matched."
    if execution_status == "small_batch_real_write_completed_but_readback_mismatch":
        return "Small batch Shopify write completed but readback mismatch requires rollback approval."
    return f"Small batch apply execute completed with status {execution_status}."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify small batch apply execute report generated.\n"
        f"Mode: {payload.get('mode')}\n"
        f"Execution status: {payload.get('execution_status')}\n"
        f"Plan status: {payload.get('plan_status')}\n"
        f"Entry count: {payload.get('entry_count')}\n"
        f"Real write allowed: {payload.get('real_write_allowed')}\n"
        f"Translations register called: {payload.get('translations_register_called')}\n"
        f"Shopify write performed: {payload.get('shopify_write_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Small batch execute JSON:\n"
        f"{json_path}\n\n"
        "Small batch execute HTML:\n"
        f"{html_path}\n"
        "Dry-run is no-write. Real-run requires the exact small batch ACK and local approval, then must immediately read back every entry.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep small batch execute dry-run files\n"
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
