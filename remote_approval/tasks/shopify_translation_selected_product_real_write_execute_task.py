import base64
import json
import os
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_selected_product_real_write_execute"
COMMAND_LABEL = TASK_NAME
PHASE = "16.2B"
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_selected_product_real_write_execute.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_selected_product_real_write_execute.html"
SMOKE_JSON_REPORT_PATH = LOG_DIR / "translation_console_manual_action_smoke_test.json"
MANUAL_ACTION_JSON_REPORT_PATH = LOG_DIR / "shopify_translation_selected_product_real_write_manual_action_package.json"

ACK_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_ACK"
ACK_VALUE = "I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE"
PRODUCT_ID_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID"
MAX_ENTRIES_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES"
LOCALES_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_LOCALES"
FIELDS_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_FIELDS"
DRY_RUN_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN"
SINGLE_ENTRY_ONLY_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_SINGLE_ENTRY_ONLY"
SINGLE_ENTRY_LOCALE_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_LOCALE"
SINGLE_ENTRY_FIELD_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_FIELD"

DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
SUPPORTED_MODES = {"dry-run", "real-run", "execute-real-write"}
REAL_RUN_MODES = {"real-run", "execute-real-write"}
DOCKER_TIMEOUT_SECONDS = 1200
SMOKE_MANAGEMENT_COMMAND = [
    "docker",
    "compose",
    "exec",
    "-T",
    "web",
    "python",
    "manage.py",
    "smoke_test_translation_console_manual_action_package",
    "--live-dry-run",
]


def run_shopify_translation_selected_product_real_write_execute_task(mode: str) -> dict:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"{TASK_NAME} only supports dry-run, real-run, or execute-real-write mode.")

    started = time.time()
    settings = _read_settings(mode)
    docker_result = _run_execute_helper_in_docker(settings)
    payload = _build_payload(settings, docker_result, round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = payload.get("execution_status") in {
        "dry_run_real_write_not_executed",
        "single_entry_real_write_succeeded_and_verified",
        "real_write_completed_and_verified",
    } and not payload.get("blocking_conditions")

    return {
        "task_type": TASK_NAME,
        "success": bool(success),
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_real_write_execute_path": str(json_path),
        "html_real_write_execute_path": str(html_path),
        "phase": PHASE,
        "execution_status": payload.get("execution_status", ""),
        "mode": payload.get("mode", ""),
        "dry_run": payload.get("dry_run", True),
        "product_id": payload.get("product_id", ""),
        "entry_count": payload.get("entry_count", 0),
        "would_write_count": payload.get("would_write_count", 0),
        "single_entry_only": payload.get("single_entry_only", False),
        "requested_locale": payload.get("requested_locale", ""),
        "requested_field": payload.get("requested_field", ""),
        "single_entry_candidate_count": payload.get("single_entry_candidate_count", 0),
        "single_entry_selected": payload.get("single_entry_selected", False),
        "preflight_status": payload.get("preflight_status", ""),
        "manual_real_write_allowed_next_step": payload.get("manual_real_write_allowed_next_step", False),
        "verified_count": payload.get("verified_count", 0),
        "ack_present": payload.get("ack_present", False),
        "ack_matches": payload.get("ack_matches", False),
        "real_run_requested": payload.get("real_run_requested", False),
        "real_write_allowed": payload.get("real_write_allowed", False),
        "pre_write_readback_performed": payload.get("pre_write_readback_performed", False),
        "pre_write_digest_verified": payload.get("pre_write_digest_verified", False),
        "shopify_write_performed": payload.get("shopify_write_performed", False),
        "mutation_performed": payload.get("mutation_performed", False),
        "translations_register_called": payload.get("translations_register_called", False),
        "post_write_readback_performed": payload.get("post_write_readback_performed", False),
        "post_write_verified": payload.get("post_write_verified", False),
        "rollback_required": payload.get("rollback_required", False),
        "rollback_approval_required": payload.get("rollback_approval_required", False),
        "rollback_performed": False,
        "no_new_shopify_writes_performed": payload.get("no_new_shopify_writes_performed", False),
        "all_new_actions_no_write_confirmed": payload.get("all_new_actions_no_write_confirmed", False),
        "no_unverified_write": payload.get("no_unverified_write", False),
        "blocking_conditions": payload.get("blocking_conditions", []),
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _read_settings(mode: str) -> dict:
    ack = os.environ.get(ACK_ENV, "")
    product_id = os.environ.get(PRODUCT_ID_ENV, "").strip()
    dry_run_raw = os.environ.get(DRY_RUN_ENV, "1").strip()
    return {
        "mode": mode,
        "dry_run": dry_run_raw != "0",
        "dry_run_env_value": dry_run_raw,
        "ack_present": bool(ack),
        "ack_matches": ack == ACK_VALUE,
        "env_product_id": product_id,
        "product_id": product_id or DEFAULT_PRODUCT_ID,
        "env_max_entries": _parse_int(os.environ.get(MAX_ENTRIES_ENV, "").strip()),
        "env_locales": _split_csv(os.environ.get(LOCALES_ENV, "")),
        "env_fields": _split_csv(os.environ.get(FIELDS_ENV, "")),
        "single_entry_only": os.environ.get(SINGLE_ENTRY_ONLY_ENV, "").strip() == "1",
        "single_entry_only_raw": os.environ.get(SINGLE_ENTRY_ONLY_ENV, "").strip(),
        "requested_locale": os.environ.get(SINGLE_ENTRY_LOCALE_ENV, "").strip(),
        "requested_field": os.environ.get(SINGLE_ENTRY_FIELD_ENV, "").strip(),
        "target_locales": _split_csv(os.environ.get(LOCALES_ENV, "")) or DEFAULT_TARGET_LOCALES,
        "requested_fields": _split_csv(os.environ.get(FIELDS_ENV, "")) or DEFAULT_FIELDS,
    }


def _run_execute_helper_in_docker(settings: dict) -> dict:
    if settings.get("dry_run", True):
        return _run_real_write_helper_in_docker(settings)
    return _run_real_write_helper_in_docker(settings)


def _single_entry_dry_run_requested(settings: dict) -> bool:
    return bool(
        settings.get("single_entry_only")
        or settings.get("requested_locale")
        or settings.get("requested_field")
    )


def _run_dry_run_via_manual_action_smoke(settings: dict) -> dict:
    command = list(SMOKE_MANAGEMENT_COMMAND)
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
        return _docker_failure(
            settings,
            "subprocess_exception",
            command=command,
            command_exception_type=exc.__class__.__name__,
            command_exception_message=str(exc),
            stdout=_decode_bytes(getattr(exc, "stdout", b"") or b""),
            stderr=_decode_bytes(getattr(exc, "stderr", b"") or b""),
        )

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    if completed.returncode != 0:
        return _docker_failure(
            settings,
            "docker_command_failed",
            command=command,
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )

    smoke_stdout = _parse_json_from_stdout(stdout)
    if smoke_stdout:
        smoke_report = {}
        smoke_diag = _stdout_json_diag()
        manual_report, manual_diag = _read_report(MANUAL_ACTION_JSON_REPORT_PATH)
        manual_action_package_source = "docker_stdout_json"
        smoke_payload = smoke_stdout
    else:
        smoke_report, smoke_diag = _read_report(SMOKE_JSON_REPORT_PATH)
        manual_report, manual_diag = _read_report(MANUAL_ACTION_JSON_REPORT_PATH)
        manual_action_package_source = "host_report_file"
        smoke_payload = smoke_report
    if not smoke_payload:
        return _docker_failure(
            settings,
            "manual_action_package_report_read_failed",
            command=command,
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
            manual_action_diag=manual_diag,
            smoke_diag=smoke_diag,
        )
    return _build_dry_run_payload_from_manual_package(
        settings=settings,
        command=command,
        completed_return_code=completed.returncode,
        stdout=stdout,
        stderr=stderr,
        smoke_payload=smoke_payload,
        smoke_diag=smoke_diag,
        manual_report=manual_report,
        manual_diag=manual_diag,
        manual_action_package_source=manual_action_package_source,
    )


def _run_real_write_helper_in_docker(settings: dict) -> dict:
    script = _build_real_write_shell_script(settings)
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
        return _docker_failure(
            settings,
            "subprocess_exception",
            command=command,
            command_exception_type=exc.__class__.__name__,
            command_exception_message=str(exc),
            stdout=_decode_bytes(getattr(exc, "stdout", b"") or b""),
            stderr=_decode_bytes(getattr(exc, "stderr", b"") or b""),
        )

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        if parsed:
            parsed.setdefault("docker_return_code", completed.returncode)
            parsed.setdefault("stdout_tail", _tail(stdout))
            parsed.setdefault("stderr_tail", _tail(stderr))
            return parsed
        return _docker_failure(
            settings,
            "docker_command_failed",
            command=command,
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    if not parsed:
        return _docker_failure(
            settings,
            "docker_json_result_missing",
            command=command,
            return_code=completed.returncode,
            stdout=stdout,
            stderr=stderr,
        )
    parsed["docker_return_code"] = completed.returncode
    parsed["stdout_tail"] = _tail(stdout)
    parsed["stderr_tail"] = _tail(stderr)
    parsed["docker_stdout_tail"] = _tail(stdout)
    parsed["docker_stderr_tail"] = _tail(stderr)
    parsed["docker_command"] = _command_for_report(command)
    return parsed


def _build_real_write_shell_script(settings: dict) -> str:
    settings_json_b64 = _settings_json_b64(settings)
    return f"""
import base64
import json

from shopify_sync.translation_real_write_execute import execute_selected_product_translation_real_write

settings_json = base64.b64decode({settings_json_b64!r}).decode("utf-8")
settings = json.loads(settings_json)
result = execute_selected_product_translation_real_write(settings)
print(json.dumps(result, ensure_ascii=False))
"""


def _build_dry_run_payload_from_manual_package(
    settings,
    command,
    completed_return_code,
    stdout,
    stderr,
    smoke_payload,
    smoke_diag,
    manual_report,
    manual_diag,
    manual_action_package_source,
):
    manual_summary = smoke_payload.get("manual_action_package_summary") or {}
    manual_report = manual_report or {}
    manual_entries = list(manual_report.get("manual_action_entries") or [])
    entry_count = int(
        manual_report.get("entry_count")
        or smoke_payload.get("entry_count")
        or manual_summary.get("entry_count")
        or 0
    )
    blocked_entry_count = int(
        manual_report.get("blocked_entry_count")
        or smoke_payload.get("blocked_entry_count")
        or manual_summary.get("blocked_entry_count")
        or 0
    )
    package_status = (
        manual_report.get("package_status")
        or smoke_payload.get("package_status")
        or manual_summary.get("package_status")
        or ""
    )
    blocking_conditions = []
    blocking_conditions.extend(smoke_payload.get("blocking_conditions") or [])
    blocking_conditions.extend(manual_report.get("blocking_conditions") or [])
    if smoke_payload.get("validation_status") and smoke_payload.get("validation_status") != "passed":
        blocking_conditions.append("manual_action_package_not_ready")
    if package_status != "selected_product_translation_real_write_manual_action_package_ready_for_manual_review":
        blocking_conditions.append("manual_action_package_not_ready")
    if entry_count <= 0:
        blocking_conditions.append("manual_action_package_entry_count_zero")
    if blocked_entry_count > 0:
        blocking_conditions.append("manual_action_package_has_blocked_entries")
    if smoke_payload.get("no_write_confirmed") is not True:
        blocking_conditions.append("manual_action_package_no_write_not_confirmed")
    if manual_action_package_source != "docker_stdout_json" and manual_diag.get("error"):
        blocking_conditions.append("manual_action_package_report_read_failed")

    entries = [_entry_from_manual_action_entry(entry) for entry in manual_entries]
    would_write_count = (
        sum(1 for entry in entries if entry.get("would_write"))
        if entries
        else entry_count
    )
    report_path = smoke_payload.get("json_report_path") or str(SMOKE_JSON_REPORT_PATH)
    return {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run",
        "requested_mode": settings.get("mode", "dry-run"),
        "dry_run": True,
        "execution_status": "dry_run_real_write_not_executed",
        "product_id": manual_report.get("product_id") or smoke_payload.get("product_id") or settings.get("product_id") or DEFAULT_PRODUCT_ID,
        "product_title": manual_report.get("product_title", "") or smoke_payload.get("product_title", ""),
        "entry_count": entry_count,
        "blocked_entry_count": blocked_entry_count,
        "would_write_count": would_write_count,
        "verified_count": 0,
        "user_errors_count": 0,
        "ack_present": bool(settings.get("ack_present")),
        "ack_matches": bool(settings.get("ack_matches")),
        "real_run_requested": False,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "manual_ack_required": True,
        "manual_ack_phrase_required": ACK_VALUE,
        "validation_status": "",
        "no_write_confirmed": False,
        "preflight_status": "single_entry_real_write_preflight_not_requested",
        "manual_real_write_allowed_next_step": False,
        "real_write_next_command_preview": [],
        "real_write_target_product_id": DEFAULT_PRODUCT_ID,
        "real_write_target_locale": "de",
        "real_write_target_field": "meta_title",
        "real_write_target_max_entries": 1,
        "first_real_write_target_mismatch": False,
        "preflight_warnings": [],
        "single_entry_only": bool(settings.get("single_entry_only")),
        "requested_locale": settings.get("requested_locale", ""),
        "requested_field": settings.get("requested_field", ""),
        "single_entry_candidate_count": 0,
        "single_entry_selected": False,
        "single_entry_blocking_conditions": [],
        "target_locales": list(manual_report.get("target_locales") or smoke_payload.get("target_locales") or DEFAULT_TARGET_LOCALES),
        "requested_fields": list(manual_report.get("requested_fields") or smoke_payload.get("requested_fields") or smoke_payload.get("fields") or DEFAULT_FIELDS),
        "locked_executor_report_path": "logs/shopify_translation_selected_product_locked_executor_shell.json",
        "real_write_executor_report_path": str(JSON_REPORT_PATH),
        "manual_action_package_status": package_status,
        "manual_action_package_report_path": report_path,
        "manual_action_package_source": manual_action_package_source,
        "manual_action_package_json_exists": True if manual_action_package_source == "docker_stdout_json" else bool(manual_diag.get("file_exists")),
        "manual_action_package_json_error": "" if manual_action_package_source == "docker_stdout_json" else manual_diag.get("error", ""),
        "host_report_file_exists": bool(manual_diag.get("file_exists")),
        "smoke_test_report_path": report_path,
        "smoke_test_json_exists": True if manual_action_package_source == "docker_stdout_json" else bool(smoke_diag.get("file_exists")),
        "smoke_test_json_error": smoke_diag.get("error", ""),
        "pre_write_readback_checked": False,
        "pre_write_readback_performed": False,
        "pre_write_existing_current_translation": False,
        "pre_write_existing_outdated_translation": False,
        "pre_write_digest": "",
        "pre_write_digest_verified": False,
        "translations_register_payload_count": 0,
        "shopify_api_call_performed": bool(smoke_payload.get("no_write_confirmed")),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "translations_register_user_errors": [],
        "post_write_readback_performed": False,
        "post_write_readback_checked": False,
        "post_write_verified": False,
        "post_write_readback_matches": False,
        "rollback_required": False,
        "rollback_approval_required": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "no_unverified_write": True,
        "entries": entries,
        "blocking_conditions": _unique(blocking_conditions),
        "failure_type": "manual_action_package_report_read_failed" if manual_action_package_source != "docker_stdout_json" and manual_diag.get("error") else "",
        "docker_command": _command_for_report(command),
        "docker_return_code": completed_return_code,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "docker_stdout_tail": _tail(stdout),
        "docker_stderr_tail": _tail(stderr),
        "command_exception_type": "",
        "command_exception_message": "",
        "manual_action_package_summary": manual_summary,
        "smoke_validation_status": smoke_payload.get("validation_status", ""),
        "no_write_confirmed": bool(smoke_payload.get("no_write_confirmed")),
    }


def _entry_from_manual_action_entry(entry):
    key = entry.get("planned_key") or entry.get("field", "")
    planned_value = entry.get("planned_value") or entry.get("proposed_translation", "")
    blocking_reasons = list(entry.get("blocking_reasons") or [])
    return {
        "product_id": entry.get("product_id", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "key": key,
        "resource_key": key,
        "translatable_content_key": key,
        "digest": entry.get("digest", ""),
        "pre_write_digest": "",
        "digest_matches": False,
        "proposed_value_chars": len(planned_value),
        "blocked": bool(blocking_reasons),
        "pre_existing_translation_state": entry.get("current_translation_state", {}),
        "pre_existing_translation_value": "",
        "pre_outdated": None,
        "write_performed": False,
        "mutation_user_error": None,
        "post_write_value": "",
        "post_write_outdated": None,
        "verified": False,
        "would_write": bool(entry.get("would_write")),
        "blocking_reasons": blocking_reasons,
        "blocking_conditions": blocking_reasons,
    }


def _read_report(path: Path) -> tuple[dict, dict]:
    diag = {
        "report_path": str(path),
        "file_exists": path.exists(),
        "error": "",
        "json_decode_error": "",
    }
    if not path.exists():
        diag["error"] = "file_not_found"
        return {}, diag
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), diag
    except json.JSONDecodeError as exc:
        diag["error"] = "json_decode_error"
        diag["json_decode_error"] = str(exc)
        return {}, diag
    except OSError as exc:
        diag["error"] = f"{exc.__class__.__name__}: {exc}"
        return {}, diag


def _stdout_json_diag() -> dict:
    return {
        "report_path": "docker_stdout_json",
        "file_exists": True,
        "error": "",
        "json_decode_error": "",
    }


def _docker_failure(
    settings,
    failure_type,
    return_code=None,
    stdout="",
    stderr="",
    command=None,
    command_exception_type="",
    command_exception_message="",
    manual_action_diag=None,
    smoke_diag=None,
):
    real_run_requested = settings.get("mode") in REAL_RUN_MODES and settings.get("dry_run") is False
    manual_action_diag = manual_action_diag or {}
    smoke_diag = smoke_diag or {}
    return {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run" if settings.get("dry_run") else settings.get("mode", "dry-run"),
        "requested_mode": settings.get("mode", "dry-run"),
        "dry_run": bool(settings.get("dry_run", True)),
        "execution_status": "dry_run_real_write_not_executed" if settings.get("dry_run", True) else "real_write_failed_needs_manual_review",
        "product_id": settings.get("product_id") or DEFAULT_PRODUCT_ID,
        "entry_count": 0,
        "blocked_entry_count": 0,
        "would_write_count": 0,
        "verified_count": 0,
        "user_errors_count": 0,
        "ack_present": bool(settings.get("ack_present")),
        "ack_matches": bool(settings.get("ack_matches")),
        "real_run_requested": bool(real_run_requested),
        "real_write_allowed": False,
        "future_write_allowed": False,
        "manual_ack_required": True,
        "manual_ack_phrase_required": ACK_VALUE,
        "validation_status": "",
        "no_write_confirmed": False,
        "preflight_status": "single_entry_real_write_preflight_not_requested",
        "manual_real_write_allowed_next_step": False,
        "real_write_next_command_preview": [],
        "real_write_target_product_id": DEFAULT_PRODUCT_ID,
        "real_write_target_locale": "de",
        "real_write_target_field": "meta_title",
        "real_write_target_max_entries": 1,
        "first_real_write_target_mismatch": False,
        "preflight_warnings": [],
        "single_entry_only": bool(settings.get("single_entry_only")),
        "requested_locale": settings.get("requested_locale", ""),
        "requested_field": settings.get("requested_field", ""),
        "single_entry_candidate_count": 0,
        "single_entry_selected": False,
        "single_entry_blocking_conditions": [],
        "pre_write_readback_checked": False,
        "pre_write_readback_performed": False,
        "pre_write_existing_current_translation": False,
        "pre_write_existing_outdated_translation": False,
        "pre_write_digest": "",
        "pre_write_digest_verified": False,
        "translations_register_payload_count": 0,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "translations_register_user_errors": [],
        "manual_action_package_status": "",
        "manual_action_package_report_path": str(MANUAL_ACTION_JSON_REPORT_PATH),
        "manual_action_package_json_exists": bool(manual_action_diag.get("file_exists", False)),
        "manual_action_package_json_error": manual_action_diag.get("error", ""),
        "smoke_test_report_path": str(SMOKE_JSON_REPORT_PATH),
        "smoke_test_json_exists": bool(smoke_diag.get("file_exists", False)),
        "smoke_test_json_error": smoke_diag.get("error", ""),
        "post_write_readback_performed": False,
        "post_write_readback_checked": False,
        "post_write_verified": False,
        "post_write_readback_matches": False,
        "rollback_required": bool(real_run_requested),
        "rollback_approval_required": bool(real_run_requested),
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": not real_run_requested,
        "all_new_actions_no_write_confirmed": not real_run_requested,
        "no_unverified_write": not real_run_requested,
        "entries": [],
        "blocking_conditions": [failure_type],
        "failure_type": failure_type,
        "execution_failure_type": failure_type,
        "docker_command": _command_for_report(command or []),
        "docker_return_code": return_code,
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
        "docker_stdout_tail": _tail(stdout),
        "docker_stderr_tail": _tail(stderr),
        "command_exception_type": command_exception_type,
        "command_exception_message": command_exception_message,
    }


def _build_payload(settings: dict, result: dict, duration_seconds: float) -> dict:
    payload = dict(result or {})
    payload.setdefault("phase", PHASE)
    payload.setdefault("task", TASK_NAME)
    payload.setdefault("task_name", TASK_NAME)
    payload.setdefault("mode", "dry-run" if settings.get("dry_run") else settings.get("mode", "dry-run"))
    payload.setdefault("dry_run", bool(settings.get("dry_run", True)))
    payload.setdefault("execution_status", "dry_run_real_write_not_executed")
    payload.setdefault("blocking_conditions", [])
    payload.setdefault("entries", [])
    payload.setdefault("failure_type", "")
    payload.setdefault("docker_command", "")
    payload.setdefault("docker_return_code", None)
    payload.setdefault("stdout_tail", "")
    payload.setdefault("stderr_tail", "")
    payload.setdefault("docker_stdout_tail", "")
    payload.setdefault("docker_stderr_tail", "")
    payload.setdefault("command_exception_type", "")
    payload.setdefault("command_exception_message", "")
    payload.setdefault("manual_action_package_status", "")
    payload.setdefault("manual_action_package_report_path", str(MANUAL_ACTION_JSON_REPORT_PATH))
    payload.setdefault("manual_action_package_source", "")
    payload.setdefault("manual_action_package_json_exists", MANUAL_ACTION_JSON_REPORT_PATH.exists())
    payload.setdefault("manual_action_package_json_error", "")
    payload.setdefault("host_report_file_exists", MANUAL_ACTION_JSON_REPORT_PATH.exists())
    payload.setdefault("single_entry_only", bool(settings.get("single_entry_only")))
    payload.setdefault("requested_locale", settings.get("requested_locale", ""))
    payload.setdefault("requested_field", settings.get("requested_field", ""))
    payload.setdefault("single_entry_candidate_count", 0)
    payload.setdefault("single_entry_selected", False)
    payload.setdefault("single_entry_blocking_conditions", [])
    payload.setdefault("validation_status", "")
    payload.setdefault("no_write_confirmed", False)
    payload.setdefault("preflight_status", "single_entry_real_write_preflight_not_requested")
    payload.setdefault("manual_real_write_allowed_next_step", False)
    payload.setdefault("real_write_next_command_preview", [])
    payload.setdefault("real_write_target_product_id", DEFAULT_PRODUCT_ID)
    payload.setdefault("real_write_target_locale", "de")
    payload.setdefault("real_write_target_field", "meta_title")
    payload.setdefault("real_write_target_max_entries", 1)
    payload.setdefault("first_real_write_target_mismatch", False)
    payload.setdefault("preflight_warnings", [])
    payload.setdefault("pre_write_readback_checked", payload.get("pre_write_readback_performed", False))
    payload.setdefault("pre_write_existing_current_translation", False)
    payload.setdefault("pre_write_existing_outdated_translation", False)
    payload.setdefault("pre_write_digest", "")
    payload.setdefault("translations_register_payload_count", 0)
    payload.setdefault("post_write_readback_checked", payload.get("post_write_readback_performed", False))
    payload.setdefault("post_write_readback_matches", payload.get("post_write_verified", False))
    payload.update(
        {
            "timestamp": utc_now_iso(),
            "json_real_write_execute_path": str(JSON_REPORT_PATH),
            "html_real_write_execute_path": str(HTML_REPORT_PATH),
            "required_env": {
                ACK_ENV: ACK_VALUE,
                PRODUCT_ID_ENV: DEFAULT_PRODUCT_ID,
                MAX_ENTRIES_ENV: "1 required for the single-entry real-run branch",
                DRY_RUN_ENV: "0 required for any real-run branch",
                SINGLE_ENTRY_ONLY_ENV: "1 required for any real-run branch",
                SINGLE_ENTRY_LOCALE_ENV: ",".join(DEFAULT_TARGET_LOCALES),
                SINGLE_ENTRY_FIELD_ENV: ",".join(DEFAULT_FIELDS),
            },
            "optional_env": {
                LOCALES_ENV: ",".join(DEFAULT_TARGET_LOCALES),
                FIELDS_ENV: ",".join(DEFAULT_FIELDS),
            },
            "env_summary": {
                "ack_present": bool(settings.get("ack_present")),
                "ack_matches": bool(settings.get("ack_matches")),
                "product_id_env_present": bool(settings.get("env_product_id")),
                "max_entries_env": settings.get("env_max_entries"),
                "dry_run_env_value": settings.get("dry_run_env_value"),
                "locales_env": settings.get("env_locales"),
                "fields_env": settings.get("env_fields"),
                "single_entry_only_env_value": settings.get("single_entry_only_raw"),
                "single_entry_only": bool(settings.get("single_entry_only")),
                "requested_locale": settings.get("requested_locale"),
                "requested_field": settings.get("requested_field"),
            },
            "duration_seconds": duration_seconds,
            "rollback_performed": False,
        }
    )
    payload["stdout_tail"] = payload.get("stdout_tail") or ""
    payload["stderr_tail"] = payload.get("stderr_tail") or ""
    payload["docker_stdout_tail"] = payload.get("docker_stdout_tail") or ""
    payload["docker_stderr_tail"] = payload.get("docker_stderr_tail") or ""
    payload["command_exception_type"] = payload.get("command_exception_type") or ""
    payload["command_exception_message"] = payload.get("command_exception_message") or ""
    payload["manual_action_package_json_error"] = payload.get("manual_action_package_json_error") or ""
    return payload


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
            ("Execution Status", "execution_status"),
            ("Mode", "mode"),
            ("Dry Run", "dry_run"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Would Write Count", "would_write_count"),
            ("Verified Count", "verified_count"),
            ("User Errors Count", "user_errors_count"),
            ("ACK Present", "ack_present"),
            ("ACK Matches", "ack_matches"),
            ("Real Run Requested", "real_run_requested"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Validation Status", "validation_status"),
            ("No Write Confirmed", "no_write_confirmed"),
            ("Preflight Status", "preflight_status"),
            ("Manual Real Write Allowed Next Step", "manual_real_write_allowed_next_step"),
            ("Real Write Target Product ID", "real_write_target_product_id"),
            ("Real Write Target Locale", "real_write_target_locale"),
            ("Real Write Target Field", "real_write_target_field"),
            ("Real Write Target Max Entries", "real_write_target_max_entries"),
            ("First Real Write Target Mismatch", "first_real_write_target_mismatch"),
            ("Preflight Warnings", "preflight_warnings"),
            ("Real Write Next Command Preview", "real_write_next_command_preview"),
            ("Single Entry Only", "single_entry_only"),
            ("Requested Locale", "requested_locale"),
            ("Requested Field", "requested_field"),
            ("Single Entry Candidate Count", "single_entry_candidate_count"),
            ("Single Entry Selected", "single_entry_selected"),
            ("Single Entry Blocking Conditions", "single_entry_blocking_conditions"),
            ("Failure Type", "failure_type"),
            ("Docker Command", "docker_command"),
            ("Docker Return Code", "docker_return_code"),
            ("Docker Stdout Tail", "docker_stdout_tail"),
            ("Docker Stderr Tail", "docker_stderr_tail"),
            ("Manual Action Package Status", "manual_action_package_status"),
            ("Manual Action Package Report Path", "manual_action_package_report_path"),
            ("Manual Action Package Source", "manual_action_package_source"),
            ("Manual Action Package JSON Exists", "manual_action_package_json_exists"),
            ("Manual Action Package JSON Error", "manual_action_package_json_error"),
            ("Host Report File Exists", "host_report_file_exists"),
            ("Command Exception Type", "command_exception_type"),
            ("Command Exception Message", "command_exception_message"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    safety_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Pre-write Readback Checked", "pre_write_readback_checked"),
            ("Pre-write Readback Performed", "pre_write_readback_performed"),
            ("Pre-write Existing Current Translation", "pre_write_existing_current_translation"),
            ("Pre-write Existing Outdated Translation", "pre_write_existing_outdated_translation"),
            ("Pre-write Digest", "pre_write_digest"),
            ("Pre-write Digest Verified", "pre_write_digest_verified"),
            ("translationsRegister Payload Count", "translations_register_payload_count"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Post-write Readback Checked", "post_write_readback_checked"),
            ("Post-write Readback Performed", "post_write_readback_performed"),
            ("Post-write Verified", "post_write_verified"),
            ("Post-write Readback Matches", "post_write_readback_matches"),
            ("Rollback Required", "rollback_required"),
            ("Rollback Approval Required", "rollback_approval_required"),
            ("Rollback Performed", "rollback_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("No Unverified Write", "no_unverified_write"),
        ]
    )
    entry_rows = "\n".join(
        f"<tr><td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field') or entry.get('key', '')))}</td>"
        f"<td>{escape(str(entry.get('key', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars', '')))}</td>"
        f"<td>{escape(str(entry.get('blocked', False)))}</td>"
        f"<td>{escape(str(entry.get('write_performed', False)))}</td>"
        f"<td>{escape(str(entry.get('verified', False)))}</td>"
        f"<td>{escape(str(entry.get('blocking_conditions') or entry.get('blocking_reasons', [])))}</td></tr>"
        for entry in payload.get("entries", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Real Write Execute</title></head>
<body>
  <h1>Selected Product Translation Real Write Execute</h1>
  <p>Phase 16.2B. Dry-run is the default. Real writes require exact environment ACK, exact product scope, single-entry targeting, pre-write digest verification, and post-write readback. Rollback is never automatic.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Key</th><th>Digest</th><th>Proposed Value Chars</th><th>Blocked</th><th>Write Performed</th><th>Verified</th><th>Blocking Conditions</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
</body>
</html>
"""


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Phase 16.2B selected product translation real write execute package generated.\n"
        f"- execution_status: {payload.get('execution_status')}\n"
        f"- mode: {payload.get('mode')}\n"
        f"- dry_run: {payload.get('dry_run')}\n"
        f"- product_id: {payload.get('product_id')}\n"
        f"- entry_count: {payload.get('entry_count')}\n"
        f"- would_write_count: {payload.get('would_write_count')}\n"
        f"- single_entry_only: {payload.get('single_entry_only')}\n"
        f"- requested_locale: {payload.get('requested_locale')}\n"
        f"- requested_field: {payload.get('requested_field')}\n"
        f"- single_entry_candidate_count: {payload.get('single_entry_candidate_count')}\n"
        f"- single_entry_selected: {payload.get('single_entry_selected')}\n"
        f"- preflight_status: {payload.get('preflight_status')}\n"
        f"- manual_real_write_allowed_next_step: {payload.get('manual_real_write_allowed_next_step')}\n"
        f"- verified_count: {payload.get('verified_count')}\n"
        f"- real_write_allowed: {payload.get('real_write_allowed')}\n"
        f"- shopify_write_performed: {payload.get('shopify_write_performed')}\n"
        f"- mutation_performed: {payload.get('mutation_performed')}\n"
        f"- translations_register_called: {payload.get('translations_register_called')}\n"
        f"- rollback_performed: {payload.get('rollback_performed')}\n"
        f"- blocking_conditions: {payload.get('blocking_conditions')}\n"
        f"- JSON: {json_path}\n"
        f"- HTML: {html_path}\n\n"
        "Reply 1 to keep the generated report, or 0 to stop. This approval reply does not execute extra writes."
    )


def _parse_int(value: str):
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _split_csv(value: str) -> list[str]:
    return [part.strip() for part in (value or "").split(",") if part.strip()]


def _parse_json_from_stdout(stdout: str) -> dict:
    decoder = json.JSONDecoder()
    last_obj = {}
    last_end = -1
    for index, char in enumerate(stdout or ""):
        if char != "{":
            continue
        try:
            obj, end = decoder.raw_decode(stdout[index:])
        except json.JSONDecodeError:
            continue
        absolute_end = index + end
        if isinstance(obj, dict) and absolute_end >= last_end:
            last_obj = obj
            last_end = absolute_end
    return last_obj


def _settings_json_b64(settings: dict) -> str:
    settings_json = json.dumps(settings or {}, ensure_ascii=False)
    return base64.b64encode(settings_json.encode("utf-8")).decode("ascii")


def _decode_bytes(value: bytes) -> str:
    return value.decode("utf-8", errors="replace") if isinstance(value, bytes) else str(value or "")


def _tail(value: str, limit: int = 4000) -> str:
    return (value or "")[-limit:]


def _command_for_report(command) -> str:
    return " ".join(str(part) for part in (command or []))


def _unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output


def _row(label, value):
    return f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"
