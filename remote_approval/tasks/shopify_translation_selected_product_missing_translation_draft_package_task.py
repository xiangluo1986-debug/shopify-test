import json
import os
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_selected_product_missing_translation_draft_package"
COMMAND_LABEL = TASK_NAME
DRAFT_JSON_PATH = LOG_DIR / "shopify_translation_selected_product_missing_translation_draft_package.json"
DRAFT_HTML_PATH = LOG_DIR / "shopify_translation_selected_product_missing_translation_draft_package.html"

DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
SUPPORTED_LOCALES = ["ja", "de", "fr", "es", "it"]
ALLOWED_FIELDS = ["title", "meta_title", "meta_description"]
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/\d+$")
DOCKER_TIMEOUT_SECONDS = 900


def run_shopify_translation_selected_product_missing_translation_draft_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    requested_scope = _requested_scope()
    validation_errors = _validate_requested_scope(requested_scope)
    query_result = _empty_generation_result(requested_scope)

    if validation_errors:
        query_result["blocking_conditions"] = list(validation_errors)
        query_result["draft_status"] = validation_errors[0]
    else:
        query_result = _run_draft_generation(requested_scope)

    payload = _build_payload(
        requested_scope=requested_scope,
        query_result=query_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = payload["draft_status"] in {
        "selected_product_missing_translation_draft_ready_for_manual_review",
        "no_missing_translations_found",
    }

    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_selected_product_missing_translation_draft_package_path": str(json_path),
        "html_selected_product_missing_translation_draft_package_path": str(html_path),
        "draft_status": payload["draft_status"],
        "product_id": payload.get("product_id", ""),
        "product_title": payload.get("product_title", ""),
        "target_locales": payload.get("target_locales", []),
        "requested_fields": payload.get("requested_fields", []),
        "generated_draft_count": payload.get("generated_draft_count", 0),
        "draft_ready_count": payload.get("draft_ready_count", 0),
        "draft_needs_manual_review_count": payload.get("draft_needs_manual_review_count", 0),
        "eligible_apply_plan_count": payload.get("eligible_apply_plan_count", 0),
        "over_length_after_rewrite_count": payload.get("over_length_after_rewrite_count", 0),
        "seo_ready_count": payload.get("seo_ready_count", 0),
        "seo_needs_manual_review_count": payload.get("seo_needs_manual_review_count", 0),
        "seo_eligible_apply_plan_count": payload.get("seo_eligible_apply_plan_count", 0),
        "forbidden_phrase_count": payload.get("forbidden_phrase_count", 0),
        "missing_core_keyword_count": payload.get("missing_core_keyword_count", 0),
        "too_short_for_seo_count": payload.get("too_short_for_seo_count", 0),
        "skipped_existing_translation_count": payload.get("skipped_existing_translation_count", 0),
        "skipped_outdated_translation_count": payload.get("skipped_outdated_translation_count", 0),
        "skipped_source_empty_count": payload.get("skipped_source_empty_count", 0),
        "draft_package_only": True,
        "shopify_read_only": True,
        "shopify_api_call_performed": payload.get("shopify_api_call_performed", False),
        "openai_call_performed": payload.get("openai_call_performed", False),
        "translation_generated": payload.get("translation_generated", False),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "existing_translation_overwrite_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures_count": len(payload.get("validation_failures", [])),
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
        "blocking_conditions": payload.get("blocking_conditions", []),
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _requested_scope() -> dict:
    return {
        "product_id": (
            os.environ.get("SHOPIFY_TRANSLATION_SELECTED_PRODUCT_ID")
            or os.environ.get("SHOPIFY_TRANSLATION_PRODUCT_ID")
            or DEFAULT_PRODUCT_ID
        ).strip(),
        "target_locales": _split_csv(
            os.environ.get("SHOPIFY_TRANSLATION_SELECTED_TARGET_LOCALES")
            or os.environ.get("SHOPIFY_TRANSLATION_TARGET_LOCALES", ""),
            DEFAULT_TARGET_LOCALES,
        ),
        "fields": _split_csv(
            os.environ.get("SHOPIFY_TRANSLATION_SELECTED_FIELDS")
            or os.environ.get("SHOPIFY_TRANSLATION_FIELDS", ""),
            DEFAULT_FIELDS,
        ),
    }


def _split_csv(value: str, default_values: list[str]) -> list[str]:
    if not value:
        return list(default_values)
    return _unique([part.strip() for part in value.split(",") if part.strip()])


def _validate_requested_scope(scope: dict) -> list[str]:
    errors = []
    product_id = scope.get("product_id", "")
    if not product_id or not PRODUCT_GID_RE.match(product_id):
        errors.append("blocked_invalid_product_id")

    target_locales = scope.get("target_locales") or []
    if not target_locales or any(locale not in SUPPORTED_LOCALES for locale in target_locales):
        errors.append("blocked_unsupported_locale")

    fields = scope.get("fields") or []
    if not fields or any(field not in ALLOWED_FIELDS for field in fields):
        errors.append("blocked_invalid_field")
    return _unique(errors)


def _run_draft_generation(scope: dict) -> dict:
    script = f"""
import json

from shopify_sync.translation_drafts import generate_selected_product_missing_translation_draft_package

result = generate_selected_product_missing_translation_draft_package(
    product_id={json.dumps(scope["product_id"])},
    target_locales={json.dumps(scope["target_locales"])},
    fields={json.dumps(scope["fields"])},
)
print(json.dumps(result, ensure_ascii=False))
"""
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
            **_empty_generation_result(scope),
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "timeout",
            "query_failure_type": "docker_command_failed",
            "error": f"Draft generation timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
            "blocking_conditions": ["blocked_shopify_read_query_failed"],
        }
    except FileNotFoundError as exc:
        return {
            **_empty_generation_result(scope),
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "missing_env",
            "query_failure_type": "docker_command_failed",
            "error": str(exc),
            "blocking_conditions": ["blocked_shopify_read_query_failed"],
        }
    except PermissionError as exc:
        return {
            **_empty_generation_result(scope),
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "docker_permission_denied",
            "query_failure_type": "docker_command_failed",
            "error": str(exc),
            "blocking_conditions": ["blocked_shopify_read_query_failed"],
        }

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        return {
            **_empty_generation_result(scope),
            **parsed,
            "success": False,
            "exit_code": completed.returncode,
            "draft_status": parsed.get("draft_status") or "blocked_shopify_read_query_failed",
            "failure_type": parsed.get("failure_type") or _classify_command_failure(stdout, stderr),
            "query_failure_type": parsed.get("query_failure_type") or "docker_command_failed",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": parsed.get("error") or "Docker draft helper command failed.",
            "blocking_conditions": parsed.get("blocking_conditions") or ["blocked_shopify_read_query_failed"],
        }
    if not parsed:
        return {
            **_empty_generation_result(scope),
            "success": False,
            "exit_code": completed.returncode,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "command_error",
            "query_failure_type": "docker_command_failed",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": "Docker draft helper did not return parseable JSON.",
            "blocking_conditions": ["blocked_shopify_read_query_failed"],
        }
    return {
        **_empty_generation_result(scope),
        **parsed,
        "success": bool(parsed.get("success")),
        "exit_code": completed.returncode,
        "failure_type": parsed.get("failure_type", ""),
        "query_failure_type": parsed.get("query_failure_type", ""),
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def _empty_generation_result(scope: dict) -> dict:
    return {
        "success": False,
        "draft_status": "",
        "product_id": scope.get("product_id", ""),
        "product_title": "",
        "target_locales": list(scope.get("target_locales") or []),
        "requested_fields": list(scope.get("fields") or []),
        "shopify_read_only": True,
        "shopify_api_call_performed": False,
        "openai_call_performed": False,
        "translation_generated": False,
        "generated_draft_count": 0,
        "draft_ready_count": 0,
        "draft_needs_manual_review_count": 0,
        "eligible_apply_plan_count": 0,
        "over_length_after_rewrite_count": 0,
        "seo_ready_count": 0,
        "seo_needs_manual_review_count": 0,
        "seo_eligible_apply_plan_count": 0,
        "forbidden_phrase_count": 0,
        "missing_core_keyword_count": 0,
        "too_short_for_seo_count": 0,
        "skipped_existing_translation_count": 0,
        "skipped_outdated_translation_count": 0,
        "skipped_source_empty_count": 0,
        "per_locale_results": {},
        "per_field_results": {},
        "entries": [],
        "draft_entries": [],
        "source_read_summary": {},
        "blocking_conditions": [],
        "failure_type": "",
        "query_failure_type": "",
        "error": "",
        "draft_package_only": True,
        "existing_translation_overwrite_allowed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _build_payload(requested_scope: dict, query_result: dict, duration_seconds: float) -> dict:
    payload = {
        **_empty_generation_result(requested_scope),
        **query_result,
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "command_label": COMMAND_LABEL,
        "mode": "draft-package-only",
        "requested_scope": requested_scope,
        "start_time": utc_now_iso(),
        "end_time": utc_now_iso(),
        "duration_seconds": duration_seconds,
        "json_selected_product_missing_translation_draft_package_path": str(DRAFT_JSON_PATH),
        "html_selected_product_missing_translation_draft_package_path": str(DRAFT_HTML_PATH),
    }
    payload["draft_status"] = payload.get("draft_status") or _status_from_payload(payload)
    payload["blocking_conditions"] = _unique(payload.get("blocking_conditions") or [])
    payload["success"] = payload["draft_status"] in {
        "selected_product_missing_translation_draft_ready_for_manual_review",
        "no_missing_translations_found",
    }
    payload["validation_failures"] = _validation_failures(payload)
    payload["detected_issue_summary"] = _issue_summary(payload)
    payload["safety_summary"] = _safety_summary(payload)

    # These flags describe this remote approval task itself. The helper may call
    # Shopify read-only GraphQL and OpenAI, but this task never writes Shopify.
    for key in [
        "draft_package_only",
        "shopify_read_only",
        "existing_translation_overwrite_allowed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "publish_performed",
        "apply_performed",
        "real_apply_performed",
        "rollback_performed",
        "no_new_shopify_writes_performed",
        "all_new_actions_no_write_confirmed",
    ]:
        if key in {"existing_translation_overwrite_allowed", "shopify_write_performed", "mutation_performed", "translations_register_called", "publish_performed", "apply_performed", "real_apply_performed", "rollback_performed"}:
            payload[key] = False
        else:
            payload[key] = True
    return payload


def _status_from_payload(payload: dict) -> str:
    blocking_conditions = payload.get("blocking_conditions") or []
    if blocking_conditions:
        return blocking_conditions[0]
    if not payload.get("entries"):
        return "no_missing_translations_found"
    return "selected_product_missing_translation_draft_ready_for_manual_review"


def _validation_failures(payload: dict) -> list[str]:
    failures = []
    for entry in payload.get("draft_entries", []):
        if entry.get("eligible_for_apply_plan"):
            if entry.get("validation_status") != "draft_ready_for_manual_review":
                failures.append(f"{entry.get('locale')}:{entry.get('field')}:eligible_without_quality_ready")
            if entry.get("seo_validation_status") != "seo_ready":
                failures.append(f"{entry.get('locale')}:{entry.get('field')}:eligible_without_seo_ready")
            if entry.get("draft_value_chars", 0) > int(entry.get("max_chars") or 0):
                failures.append(f"{entry.get('locale')}:{entry.get('field')}:eligible_over_max_chars")
    return failures


def _safety_summary(payload: dict) -> dict:
    return {
        "draft_package_only": True,
        "shopify_read_only": True,
        "shopify_api_call_performed": payload.get("shopify_api_call_performed", False),
        "openai_call_performed": payload.get("openai_call_performed", False),
        "translation_generated": payload.get("translation_generated", False),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "existing_translation_overwrite_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    DRAFT_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(DRAFT_JSON_PATH.read_text(encoding="utf-8"))
    return DRAFT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DRAFT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return DRAFT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Draft Status", "draft_status"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Generated Draft Count", "generated_draft_count"),
            ("Draft Ready Count", "draft_ready_count"),
            ("Draft Needs Manual Review Count", "draft_needs_manual_review_count"),
            ("Eligible Apply Plan Count", "eligible_apply_plan_count"),
            ("SEO Ready Count", "seo_ready_count"),
            ("SEO Needs Manual Review Count", "seo_needs_manual_review_count"),
            ("SEO Eligible Apply Plan Count", "seo_eligible_apply_plan_count"),
            ("Skipped Existing Translation Count", "skipped_existing_translation_count"),
            ("Skipped Outdated Translation Count", "skipped_outdated_translation_count"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("OpenAI Call Performed", "openai_call_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Publish Performed", "publish_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("Blocking Conditions", "blocking_conditions"),
            ("Validation Failures", "validation_failures"),
            ("Issue Summary", "detected_issue_summary"),
        ]
    )
    entries = "\n".join(_entry_row(entry) for entry in payload.get("entries", []))
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Missing Translation Draft Package</title></head>
<body>
  <h1>Selected Product Missing Translation Draft Package</h1>
  <p>Draft only. No Shopify write, mutation, translationsRegister, publish, apply, rollback, or existing translation overwrite was performed.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{rows}</tbody></table>
  <h2>Draft and Skipped Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Draft value</th><th>Validation</th><th>Quality notes</th><th>SEO validation</th><th>SEO notes</th><th>Eligible</th><th>Skip reason</th></tr></thead>
    <tbody>{entries}</tbody>
  </table>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _entry_row(entry: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('source_value', '')))}</td>"
        f"<td>{escape(str(entry.get('draft_value', '')))}</td>"
        f"<td>{escape(str(entry.get('validation_status', '')))}</td>"
        f"<td>{escape(str(entry.get('quality_notes', [])))}</td>"
        f"<td>{escape(str(entry.get('seo_validation_status', '')))}</td>"
        f"<td>{escape(str(entry.get('seo_notes', [])))}</td>"
        f"<td>{escape(str(entry.get('eligible_for_apply_plan', False)))}</td>"
        f"<td>{escape(str(entry.get('skip_reason', '')))}</td>"
        "</tr>"
    )


def _issue_summary(payload: dict) -> str:
    status = payload.get("draft_status", "")
    blocking_conditions = payload.get("blocking_conditions") or []
    if blocking_conditions:
        return f"Draft package blocked: {', '.join(blocking_conditions)}"
    if status == "no_missing_translations_found":
        return "No missing translations were found for the selected product fields."
    if payload.get("validation_failures"):
        return "Draft package generated, but internal eligibility validation found issues."
    return "Draft package generated for manual review only; no Shopify write was performed."


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify selected product missing translation draft package completed.\n"
        f"Draft status: {payload.get('draft_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Product title: {payload.get('product_title')}\n"
        f"Generated drafts: {payload.get('generated_draft_count')}\n"
        f"Eligible apply-plan drafts: {payload.get('eligible_apply_plan_count')}\n"
        f"SEO ready drafts: {payload.get('seo_ready_count')}\n"
        f"Shopify API call performed: {payload.get('shopify_api_call_performed')}\n"
        f"OpenAI call performed: {payload.get('openai_call_performed')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n"
    )


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


def _unique(values: list[str]) -> list[str]:
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
