import json
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_first_real_write_completion_audit"
PHASE = "16.2E"
PRODUCT_ID = "gid://shopify/Product/7655686799427"
TARGET_LOCALE = "de"
TARGET_FIELD = "meta_title"
TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
REQUESTED_FIELDS = ["title", "meta_title", "meta_description"]
FIRST_WRITE_REPORT_PATH = LOG_DIR / "shopify_translation_selected_product_real_write_execute.json"
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_first_real_write_completion_audit.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_first_real_write_completion_audit.html"
DOCKER_TIMEOUT_SECONDS = 1200


def run_shopify_translation_first_real_write_completion_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    first_report, report_diag = _read_json(FIRST_WRITE_REPORT_PATH)
    completion_conditions = _completion_blocking_conditions(first_report, report_diag)
    docker_result = _run_readonly_audit_in_docker(first_report)
    payload = _build_payload(
        first_report=first_report,
        report_diag=report_diag,
        completion_conditions=completion_conditions,
        docker_result=docker_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = (
        payload["first_real_write_completion_status"]
        == "first_real_write_completed_and_verified"
        and payload["readback_audit_status"] == "first_real_write_readback_confirmed"
        and payload["duplicate_write_protection_status"] == "duplicate_write_prevented"
        and not payload["completion_blocking_conditions"]
        and not payload["blocking_conditions"]
    )
    return {
        "task_type": TASK_NAME,
        "success": bool(success),
        "exit_code": 0 if success else 1,
        "command_label": TASK_NAME,
        "review_path": str(json_path),
        "json_completion_audit_path": str(json_path),
        "html_completion_audit_path": str(html_path),
        "phase": PHASE,
        "first_real_write_completion_status": payload["first_real_write_completion_status"],
        "readback_audit_status": payload["readback_audit_status"],
        "duplicate_write_protection_status": payload["duplicate_write_protection_status"],
        "small_batch_readiness_status": payload["small_batch_readiness_status"],
        "remaining_eligible_count": payload["remaining_eligible_count"],
        "small_batch_recommended_count": payload["small_batch_recommended_count"],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "blocking_conditions": payload["blocking_conditions"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _build_payload(
    first_report: dict,
    report_diag: dict,
    completion_conditions: list[str],
    docker_result: dict,
    duration_seconds: float,
) -> dict:
    completion_conditions = list(completion_conditions)
    blocking_conditions = []
    if docker_result.get("failure_type"):
        blocking_conditions.append(docker_result["failure_type"])

    readback = docker_result.get("readback") or {}
    manual = docker_result.get("manual_action_package") or {}
    eligible_entries = list(manual.get("eligible_entries") or [])
    readback_status, readback_matches, readback_match_basis = _readback_status(
        first_report, readback, docker_result
    )
    if docker_result.get("success") and readback.get("current_translation_exists") is not True:
        completion_conditions.append("first_real_write_translation_not_found_on_readback")
    duplicate_still_eligible = any(
        entry.get("locale") == TARGET_LOCALE
        and entry.get("field") == TARGET_FIELD
        and entry.get("would_write") is True
        for entry in eligible_entries
    )
    duplicate_status = (
        "duplicate_write_prevented"
        if docker_result.get("success") and not duplicate_still_eligible
        else "duplicate_write_protection_needs_review"
    )
    if duplicate_still_eligible:
        completion_conditions.append("duplicate_target_still_eligible_after_successful_write")
        blocking_conditions.append("duplicate_target_still_eligible_after_successful_write")

    recommended_entries = _small_batch_recommendations(eligible_entries)
    small_batch_status = (
        "small_batch_candidates_ready_for_dry_run"
        if 2 <= len(recommended_entries) <= 3
        else "small_batch_candidates_insufficient"
    )
    payload = {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run",
        "dry_run": True,
        "generated_at": utc_now_iso(),
        "duration_seconds": duration_seconds,
        "source_real_write_report_path": str(FIRST_WRITE_REPORT_PATH),
        "source_real_write_report_exists": bool(report_diag.get("file_exists")),
        "source_real_write_report_error": report_diag.get("error", ""),
        "first_real_write_completion_status": (
            "first_real_write_completed_and_verified"
            if not completion_conditions
            else "first_real_write_completion_needs_review"
        ),
        "completion_blocking_conditions": completion_conditions,
        "readback_audit_performed": bool(docker_result.get("success")),
        "readback_target_product_id": PRODUCT_ID,
        "readback_target_locale": TARGET_LOCALE,
        "readback_target_field": TARGET_FIELD,
        "readback_current_translation_exists": bool(
            readback.get("current_translation_exists")
        ),
        "readback_current_translation_digest": readback.get("current_translation_digest", ""),
        "readback_current_translation_chars": int(
            readback.get("current_translation_chars") or 0
        ),
        "readback_matches_first_write_report": readback_matches,
        "readback_match_basis": readback_match_basis,
        "readback_audit_status": readback_status,
        "readback_audit_source": docker_result.get("readback_audit_source", ""),
        "docker_stdout_json_parsed": bool(docker_result.get("docker_stdout_json_parsed")),
        "readback_audit_error": docker_result.get("readback_audit_error", ""),
        "docker_stdout_json_parse_error": docker_result.get("docker_stdout_json_parse_error", ""),
        "duplicate_write_protection_checked": bool(docker_result.get("success")),
        "duplicate_target_locale": TARGET_LOCALE,
        "duplicate_target_field": TARGET_FIELD,
        "duplicate_target_still_eligible": duplicate_still_eligible,
        "duplicate_write_protection_status": duplicate_status,
        "remaining_eligible_count": len(eligible_entries),
        "small_batch_recommended_count": len(recommended_entries),
        "small_batch_recommended_entries": recommended_entries,
        "small_batch_readiness_status": small_batch_status,
        "small_batch_dry_run_command_powershell": _small_batch_dry_run_command_preview(
            recommended_entries
        ),
        "shopify_api_call_performed": bool(docker_result.get("success")),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "email_sent": False,
        "gmail_api_call_performed": False,
        "safety_flags": {
            "shopify_api_call_performed": bool(docker_result.get("success")),
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
            "no_new_shopify_writes_performed": True,
            "all_new_actions_no_write_confirmed": True,
            "email_sent": False,
            "gmail_api_call_performed": False,
        },
        "blocking_conditions": _unique(blocking_conditions),
        "docker_command": docker_result.get("docker_command", ""),
        "docker_return_code": docker_result.get("docker_return_code"),
        "docker_stdout_tail": docker_result.get("docker_stdout_tail", ""),
        "docker_stderr_tail": docker_result.get("docker_stderr_tail", ""),
        "docker_failure_type": docker_result.get("failure_type", ""),
        "manual_action_package_status": manual.get("package_status", ""),
        "manual_action_entry_count": manual.get("entry_count", 0),
        "manual_action_blocked_entry_count": manual.get("blocked_entry_count", 0),
        "manual_action_blocking_conditions": manual.get("blocking_conditions", []),
    }
    return payload


def _completion_blocking_conditions(report: dict, diag: dict) -> list[str]:
    conditions = []
    if not diag.get("file_exists"):
        return ["missing_first_real_write_execute_report"]
    if diag.get("error"):
        return [f"first_real_write_execute_report_{diag['error']}"]
    expected = {
        "execution_status": "single_entry_real_write_succeeded_and_verified",
        "audit_status": "single_entry_real_write_audit_passed",
        "requested_locale": TARGET_LOCALE,
        "requested_field": TARGET_FIELD,
        "translations_register_payload_count": 1,
        "write_attempted_count": 1,
        "write_succeeded_count": 1,
        "verified_count": 1,
        "post_write_readback_checked": True,
        "post_write_readback_matches": True,
        "rollback_approval_required": False,
        "rollback_performed": False,
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            conditions.append(f"{key}_mismatch")
    if report.get("blocking_conditions") not in ([], None):
        conditions.append("source_blocking_conditions_not_empty")
    if report.get("product_id") != PRODUCT_ID:
        conditions.append("product_id_mismatch")
    return conditions


def _readback_status(first_report: dict, readback: dict, docker_result: dict) -> tuple[str, bool, str]:
    if not docker_result.get("success"):
        return "first_real_write_readback_needs_review", False, "docker_audit_not_successful"
    current_exists = readback.get("current_translation_exists") is True
    outdated = readback.get("translation_outdated") is True
    digest = readback.get("current_translation_digest", "")
    chars = int(readback.get("current_translation_chars") or 0)
    report_digest = first_report.get("post_write_readback_value_digest", "")
    report_chars = int(first_report.get("post_write_readback_value_chars") or 0)
    if report_digest:
        digest_matches = bool(digest and digest == report_digest)
        chars_match = bool(report_chars and chars == report_chars) if report_chars else True
        matches = bool(current_exists and digest_matches and chars_match)
        basis = "post_write_readback_value_digest_and_chars"
    elif (
        first_report.get("verified_count") == 1
        and first_report.get("post_write_readback_matches") is True
        and current_exists
    ):
        matches = True
        basis = "verified_write_report_and_current_translation_exists"
    else:
        matches = False
        basis = "insufficient_first_write_digest_or_verification"
    status = (
        "first_real_write_readback_confirmed"
        if current_exists and not outdated
        else "first_real_write_readback_needs_review"
    )
    return status, matches, basis


def _run_readonly_audit_in_docker(first_report: dict) -> dict:
    script = _docker_python_script(first_report)
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
    except Exception as exc:
        return {
            "success": False,
            "failure_type": "subprocess_exception",
            "docker_command": _command_for_report(command),
            "docker_return_code": None,
            "docker_stdout_tail": _tail(_decode_bytes(getattr(exc, "stdout", b"") or b"")),
            "docker_stderr_tail": _tail(_decode_bytes(getattr(exc, "stderr", b"") or b"")),
            "command_exception_type": exc.__class__.__name__,
            "command_exception_message": str(exc),
        }
    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        return {
            "success": False,
            "failure_type": "docker_command_failed",
            "docker_command": _command_for_report(command),
            "docker_return_code": completed.returncode,
            "docker_stdout_tail": _tail(stdout),
            "docker_stderr_tail": _tail(stderr),
        }
    if not parsed:
        return {
            "success": False,
            "failure_type": "docker_stdout_json_parse_error",
            "docker_stdout_json_parsed": False,
            "readback_audit_error": "docker_stdout_json_parse_error",
            "docker_stdout_json_parse_error": "No complete top-level JSON object found in Docker stdout.",
            "docker_command": _command_for_report(command),
            "docker_return_code": completed.returncode,
            "docker_stdout_tail": _tail(stdout),
            "docker_stderr_tail": _tail(stderr),
        }
    parsed["success"] = parsed.get("success") is True
    parsed["docker_stdout_json_parsed"] = True
    parsed["readback_audit_source"] = "docker_stdout_json"
    parsed["docker_command"] = _command_for_report(command)
    parsed["docker_return_code"] = completed.returncode
    parsed["docker_stdout_tail"] = _tail(stdout)
    parsed["docker_stderr_tail"] = _tail(stderr)
    return parsed


def _docker_python_script(first_report: dict) -> str:
    return f"""
import hashlib
import json

from shopify_sync.models import ShopifyInstallation
from shopify_sync.translation_apply_plan import build_selected_product_translation_apply_plan
from shopify_sync.translation_console import fetch_translation_console_data
from shopify_sync.translation_drafts import generate_selected_product_missing_translation_draft_package
from shopify_sync.translation_final_review import build_selected_product_translation_final_review
from shopify_sync.translation_locked_execution_plan import build_selected_product_translation_locked_execution_plan
from shopify_sync.translation_locked_executor import build_selected_product_translation_locked_executor_shell
from shopify_sync.translation_real_write_executor import build_selected_product_translation_real_write_executor_dry_run
from shopify_sync.translation_real_write_manual_action_package import build_selected_product_translation_real_write_manual_action_package
from shopify_sync.translation_real_write_readiness import build_selected_product_translation_real_write_readiness

PRODUCT_ID = {PRODUCT_ID!r}
TARGET_LOCALE = {TARGET_LOCALE!r}
TARGET_FIELD = {TARGET_FIELD!r}
TARGET_LOCALES = {TARGET_LOCALES!r}
REQUESTED_FIELDS = {REQUESTED_FIELDS!r}

def digest_value(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest() if value else ""

def row_for_key(console_data, key):
    for row in console_data.get("translatable_rows", []) or []:
        if row.get("key") == key:
            return row
    return {{}}

def safe_entry(entry):
    planned_value = entry.get("planned_value") or entry.get("proposed_translation") or ""
    state = entry.get("current_translation_state") or {{}}
    key = entry.get("planned_key") or entry.get("field") or ""
    return {{
        "product_id": entry.get("product_id", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "key": key,
        "digest": entry.get("digest", ""),
        "proposed_value_chars": len(planned_value),
        "would_write": bool(entry.get("would_write")),
        "current_translation_present": bool(state.get("existing_translation_present")),
        "current_translation_outdated": bool(state.get("existing_translation_outdated")),
        "blocking_reasons": list(entry.get("blocking_reasons") or []),
    }}

result = {{
    "success": False,
    "readback": {{}},
    "manual_action_package": {{}},
    "shopify_api_call_performed": False,
    "shopify_write_performed": False,
    "mutation_performed": False,
    "translations_register_called": False,
    "rollback_performed": False,
}}
installation = ShopifyInstallation.objects.first()
if not installation:
    result["failure_type"] = "blocked_missing_shopify_installation"
    print(json.dumps(result, ensure_ascii=False))
else:
    console_data = fetch_translation_console_data(installation, PRODUCT_ID, TARGET_LOCALE)
    row = row_for_key(console_data, TARGET_FIELD)
    translation_value = row.get("translation_value", "")
    result["readback"] = {{
        "product_id": PRODUCT_ID,
        "locale": TARGET_LOCALE,
        "field": TARGET_FIELD,
        "current_translation_exists": bool(row.get("has_translation")),
        "current_translation_digest": digest_value(translation_value),
        "current_translation_chars": len(translation_value or ""),
        "source_digest": row.get("digest", ""),
        "translation_outdated": row.get("translation_outdated"),
    }}
    draft = generate_selected_product_missing_translation_draft_package(
        product_id=PRODUCT_ID,
        target_locales=TARGET_LOCALES,
        fields=REQUESTED_FIELDS,
        installation=installation,
    )
    apply_plan = build_selected_product_translation_apply_plan(draft)
    final_review = build_selected_product_translation_final_review(apply_plan)
    readiness = build_selected_product_translation_real_write_readiness(final_review)
    locked_plan = build_selected_product_translation_locked_execution_plan(readiness)
    locked_executor = build_selected_product_translation_locked_executor_shell(locked_plan)
    real_write_dry_run = build_selected_product_translation_real_write_executor_dry_run(
        locked_executor,
        selected_product_id=PRODUCT_ID,
    )
    manual = build_selected_product_translation_real_write_manual_action_package(
        real_write_dry_run,
        selected_product_id=PRODUCT_ID,
    )
    entries = [safe_entry(entry) for entry in manual.get("manual_action_entries", [])]
    result["manual_action_package"] = {{
        "package_status": manual.get("package_status", ""),
        "entry_count": manual.get("entry_count", 0),
        "blocked_entry_count": manual.get("blocked_entry_count", 0),
        "blocking_conditions": list(manual.get("blocking_conditions") or []),
        "eligible_entries": [entry for entry in entries if entry.get("would_write")],
    }}
    result["shopify_api_call_performed"] = True
    result["success"] = True
    print(json.dumps(result, ensure_ascii=False))
"""


def _small_batch_recommendations(entries: list[dict]) -> list[dict]:
    candidates = []
    for index, entry in enumerate(entries):
        if entry.get("locale") == TARGET_LOCALE and entry.get("field") == TARGET_FIELD:
            continue
        if entry.get("would_write") is not True:
            continue
        if entry.get("current_translation_present") or entry.get("current_translation_outdated"):
            continue
        if entry.get("blocking_reasons"):
            continue
        field = entry.get("field", "")
        chars = int(entry.get("proposed_value_chars") or 0)
        limit = {"title": 60, "meta_title": 60, "meta_description": 160}.get(field, 0)
        seo_warning = "over_ideal_seo_chars" if limit and chars > limit else ""
        candidates.append(
            {
                "product_id": entry.get("product_id", ""),
                "locale": entry.get("locale", ""),
                "field": field,
                "key": entry.get("key", ""),
                "digest": entry.get("digest", ""),
                "proposed_value_chars": chars,
                "would_write": bool(entry.get("would_write")),
                "current_translation_present": bool(entry.get("current_translation_present")),
                "current_translation_outdated": bool(entry.get("current_translation_outdated")),
                "blocking_reasons": list(entry.get("blocking_reasons") or []),
                "seo_warning": seo_warning,
                "_source_index": index,
            }
        )
    candidates.sort(key=_recommendation_sort_key)
    return [{k: v for k, v in entry.items() if k != "_source_index"} for entry in candidates[:3]]


def _recommendation_sort_key(entry: dict) -> tuple[int, int, str]:
    field = entry.get("field", "")
    chars = int(entry.get("proposed_value_chars") or 0)
    priority = {"meta_title": 0, "meta_description": 1, "title": 2}.get(field, 99)
    limit = {"title": 60, "meta_title": 60, "meta_description": 160}.get(field, 0)
    fits = 0 if limit and chars <= limit else 1
    return (priority, fits, int(entry.get("_source_index") or 0))


def _small_batch_dry_run_command_preview(entries: list[dict]) -> list[str]:
    locales = ",".join(_unique([entry["locale"] for entry in entries]))
    fields = ",".join(_unique([entry["field"] for entry in entries]))
    return [
        "$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN=\"1\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID=\"{PRODUCT_ID}\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_LOCALES=\"{locales}\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_FIELDS=\"{fields}\"",
        "python remote_approval_runner.py --task shopify_translation_first_real_write_completion_audit --approval local",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_LOCALES",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_FIELDS",
    ]


def _write_json_report(payload: dict) -> Path:
    JSON_REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    JSON_REPORT_PATH.write_text(text, encoding="utf-8")
    return JSON_REPORT_PATH


def _write_html_report(payload: dict) -> Path:
    HTML_REPORT_PATH.write_text(_render_html(payload), encoding="utf-8")
    return HTML_REPORT_PATH


def _render_html(payload: dict) -> str:
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Phase", "phase"),
            ("Task", "task"),
            ("Completion Status", "first_real_write_completion_status"),
            ("Readback Audit Status", "readback_audit_status"),
            ("Duplicate Write Protection Status", "duplicate_write_protection_status"),
            ("Small Batch Readiness Status", "small_batch_readiness_status"),
            ("Remaining Eligible Count", "remaining_eligible_count"),
            ("Small Batch Recommended Count", "small_batch_recommended_count"),
            ("Completion Blocking Conditions", "completion_blocking_conditions"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    safety_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Rollback Performed", "rollback_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No Write Confirmed", "all_new_actions_no_write_confirmed"),
            ("Email Sent", "email_sent"),
            ("Gmail API Call Performed", "gmail_api_call_performed"),
        ]
    )
    entry_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('key', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars', '')))}</td>"
        f"<td>{escape(str(entry.get('seo_warning', '')))}</td>"
        "</tr>"
        for entry in payload.get("small_batch_recommended_entries", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>First Real Write Completion Audit</title></head>
<body>
  <h1>First Real Write Completion Audit</h1>
  <p>Phase 16.2E. This report is no-write. It verifies the first controlled real write, confirms duplicate protection, and prepares dry-run-only small batch candidates.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Small Batch Recommended Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Key</th><th>Digest</th><th>Proposed Value Chars</th><th>SEO Warning</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
</body>
</html>
"""


def _row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value))}</td></tr>"


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Phase 16.2E first real write completion audit generated.\n"
        f"- first_real_write_completion_status: {payload.get('first_real_write_completion_status')}\n"
        f"- readback_audit_status: {payload.get('readback_audit_status')}\n"
        f"- duplicate_write_protection_status: {payload.get('duplicate_write_protection_status')}\n"
        f"- small_batch_readiness_status: {payload.get('small_batch_readiness_status')}\n"
        f"- remaining_eligible_count: {payload.get('remaining_eligible_count')}\n"
        f"- small_batch_recommended_count: {payload.get('small_batch_recommended_count')}\n"
        f"- shopify_write_performed: {payload.get('shopify_write_performed')}\n"
        f"- mutation_performed: {payload.get('mutation_performed')}\n"
        f"- translations_register_called: {payload.get('translations_register_called')}\n"
        f"- rollback_performed: {payload.get('rollback_performed')}\n"
        f"- no_new_shopify_writes_performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"- blocking_conditions: {payload.get('blocking_conditions')}\n"
        f"- JSON: {json_path}\n"
        f"- HTML: {html_path}\n\n"
        "Reply 1 to keep the generated report, or 0 to stop. This task does not write Shopify."
    )


def _read_json(path: Path) -> tuple[dict, dict]:
    diag = {"path": str(path), "file_exists": path.exists(), "error": ""}
    if not path.exists():
        diag["error"] = "missing"
        return {}, diag
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), diag
    except json.JSONDecodeError as exc:
        diag["error"] = f"json_decode_error: {exc}"
        return {}, diag
    except OSError as exc:
        diag["error"] = f"{exc.__class__.__name__}: {exc}"
        return {}, diag


def _parse_json_from_stdout(stdout: str) -> dict:
    last_obj = {}
    start = None
    depth = 0
    in_string = False
    escaped = False
    for index, char in enumerate(stdout or ""):
        if start is None:
            if char == "{":
                start = index
                depth = 1
                in_string = False
                escaped = False
            continue
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = stdout[start : index + 1]
                try:
                    obj = json.loads(candidate)
                except json.JSONDecodeError:
                    obj = None
                if isinstance(obj, dict):
                    last_obj = obj
                start = None
    return last_obj


def _decode_bytes(value: bytes) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _tail(value: str, limit: int = 4000) -> str:
    return (value or "")[-limit:]


def _command_for_report(command: list[str]) -> str:
    if command and command[-2:-1] == ["-c"]:
        return " ".join(command[:-1] + ["<python shell script omitted>"])
    return " ".join(command)


def _unique(values: list[str]) -> list[str]:
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
