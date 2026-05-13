import json
import os
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_translation_small_batch_locked_dry_run_package_task import (
    _parse_json_from_stdout,
    _read_json,
    _tail,
    _unique,
)
from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_next_batch_real_write_execute"
PHASE = "16.8"
PRODUCT_ID = "gid://shopify/Product/7655686799427"
LOCKED_TARGETS = [
    {"locale": "it", "field": "meta_description"},
    {"locale": "ja", "field": "title"},
]
LOCKED_TARGET_LABEL = "it:meta_description,ja:title"
LOCKED_MAX_ENTRIES = 2
LOCKED_TARGET_LOCALES = ["it", "ja"]
TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
REQUESTED_FIELDS = ["title", "meta_title", "meta_description"]
ACK_VALUE = "I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE"
SUPPORTED_MODES = {"dry-run", "real-run", "execute-real-write"}
REAL_RUN_MODES = {"real-run", "execute-real-write"}
LOCKED_DRY_RUN_REPORT_PATH = (
    LOG_DIR / "shopify_translation_next_batch_locked_dry_run_package.json"
)
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_next_batch_real_write_execute.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_next_batch_real_write_execute.html"
DOCKER_TIMEOUT_SECONDS = 1200

ACK_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_ACK"
PRODUCT_ID_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID"
MAX_ENTRIES_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES"
DRY_RUN_ENV = "SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN"
NEXT_BATCH_ONLY_ENV = "SHOPIFY_TRANSLATION_NEXT_BATCH_ONLY"
NEXT_BATCH_TARGETS_ENV = "SHOPIFY_TRANSLATION_NEXT_BATCH_TARGETS"


def run_shopify_translation_next_batch_real_write_execute_task(mode: str) -> dict:
    if mode not in SUPPORTED_MODES:
        raise ValueError(
            f"{TASK_NAME} only supports dry-run, real-run, or execute-real-write mode."
        )

    started = time.time()
    settings = _read_settings(mode)
    locked_report, locked_diag = _read_json(LOCKED_DRY_RUN_REPORT_PATH)
    locked_conditions = _locked_report_blocking_conditions(locked_report, locked_diag)
    settings["locked_target_entries"] = _locked_entries_from_locked_report(locked_report)
    env_conditions = list(settings.get("env_blocking_conditions") or [])

    if locked_conditions:
        docker_result = {
            "success": False,
            "failure_type": "locked_dry_run_not_ready",
            "execution_status": "blocked_next_batch_locked_dry_run_not_ready",
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
        }
    elif env_conditions and settings["mode"] in REAL_RUN_MODES:
        docker_result = {
            "success": False,
            "failure_type": "next_batch_env_scope_mismatch",
            "execution_status": "blocked_next_batch_env_scope_mismatch",
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
        }
    elif env_conditions and settings.get("env_next_batch_targets"):
        docker_result = {
            "success": False,
            "failure_type": "next_batch_env_scope_mismatch",
            "execution_status": "blocked_next_batch_env_scope_mismatch",
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
        }
    else:
        docker_result = _run_executor_in_docker(settings)

    payload = _build_payload(
        settings=settings,
        locked_report=locked_report,
        locked_diag=locked_diag,
        locked_conditions=locked_conditions,
        docker_result=docker_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = (
        payload["execution_status"] == "next_batch_real_write_dry_run_ready"
        if payload["dry_run"]
        else payload["execution_status"] == "next_batch_real_write_succeeded_and_verified"
    ) and not payload["blocking_conditions"]
    return {
        "task_type": TASK_NAME,
        "success": bool(success),
        "exit_code": 0 if success else 1,
        "command_label": TASK_NAME,
        "review_path": str(json_path),
        "json_next_batch_real_write_execute_path": str(json_path),
        "html_next_batch_real_write_execute_path": str(html_path),
        "phase": PHASE,
        "execution_status": payload["execution_status"],
        "audit_status": payload["audit_status"],
        "mode": payload["mode"],
        "dry_run": payload["dry_run"],
        "product_id": payload["product_id"],
        "requested_next_batch_targets": payload["requested_next_batch_targets"],
        "next_batch_selected_count": payload["next_batch_selected_count"],
        "translations_register_payload_count": payload["translations_register_payload_count"],
        "write_attempted_count": payload["write_attempted_count"],
        "write_succeeded_count": payload["write_succeeded_count"],
        "verified_count": payload["verified_count"],
        "manual_next_batch_real_write_allowed_next_step": payload[
            "manual_next_batch_real_write_allowed_next_step"
        ],
        "shopify_api_call_performed": payload["shopify_api_call_performed"],
        "shopify_write_performed": payload["shopify_write_performed"],
        "mutation_performed": payload["mutation_performed"],
        "translations_register_called": payload["translations_register_called"],
        "rollback_performed": payload["rollback_performed"],
        "blocking_conditions": payload["blocking_conditions"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _read_settings(mode: str) -> dict:
    dry_run_raw = os.environ.get(DRY_RUN_ENV, "1").strip()
    max_entries_raw = os.environ.get(MAX_ENTRIES_ENV, "").strip()
    next_batch_only_raw = os.environ.get(NEXT_BATCH_ONLY_ENV, "").strip()
    next_batch_targets_raw = os.environ.get(NEXT_BATCH_TARGETS_ENV, "").strip()
    product_id_raw = os.environ.get(PRODUCT_ID_ENV, "").strip()
    ack = os.environ.get(ACK_ENV, "")
    settings = {
        "mode": mode,
        "dry_run": dry_run_raw != "0",
        "dry_run_env_value": dry_run_raw,
        "ack_present": bool(ack),
        "ack_matches": ack == ACK_VALUE,
        "product_id": product_id_raw or PRODUCT_ID,
        "env_product_id": product_id_raw,
        "max_entries": _parse_int(max_entries_raw) if max_entries_raw else LOCKED_MAX_ENTRIES,
        "env_max_entries": _parse_int(max_entries_raw) if max_entries_raw else None,
        "next_batch_only": next_batch_only_raw == "1" if next_batch_only_raw else False,
        "next_batch_only_raw": next_batch_only_raw,
        "requested_next_batch_targets": next_batch_targets_raw or LOCKED_TARGET_LABEL,
        "env_next_batch_targets_raw": next_batch_targets_raw,
        "env_next_batch_targets": _parse_targets(next_batch_targets_raw),
    }
    settings["env_blocking_conditions"] = _settings_blocking_conditions(settings)
    return settings


def _settings_blocking_conditions(settings: dict) -> list[str]:
    conditions = []
    real_run_requested = settings["mode"] in REAL_RUN_MODES and settings["dry_run"] is False
    if settings.get("env_product_id") and settings["env_product_id"] != PRODUCT_ID:
        conditions.append("next_batch_product_id_mismatch")
    if settings.get("env_max_entries") is not None and settings["env_max_entries"] != LOCKED_MAX_ENTRIES:
        conditions.append("next_batch_max_entries_not_two")
    if settings.get("next_batch_only_raw") and not settings.get("next_batch_only"):
        conditions.append("next_batch_only_not_enabled")
    if settings.get("env_next_batch_targets_raw") and settings["env_next_batch_targets_raw"] != LOCKED_TARGET_LABEL:
        conditions.append("next_batch_targets_mismatch")

    if real_run_requested:
        if not settings.get("ack_matches"):
            conditions.append("next_batch_ack_missing_or_invalid")
        if settings.get("env_product_id") != PRODUCT_ID:
            conditions.append("next_batch_product_id_required")
        if settings.get("env_max_entries") != LOCKED_MAX_ENTRIES:
            conditions.append("next_batch_max_entries_not_two")
        if settings.get("next_batch_only") is not True:
            conditions.append("next_batch_only_not_enabled")
        if settings.get("env_next_batch_targets_raw") != LOCKED_TARGET_LABEL:
            conditions.append("next_batch_targets_mismatch")
    return _unique(conditions)


def _target_key(locale: str, field: str) -> str:
    return f"{locale}:{field}"


def _target_keys_from_targets(targets: list[dict]) -> list[str]:
    return [
        _target_key(str(target.get("locale", "")), str(target.get("field", "")))
        for target in targets
        if target.get("locale") and target.get("field")
    ]


def _requested_target_keys(settings: dict) -> list[str]:
    parsed_targets = (
        settings.get("env_next_batch_targets")
        or _parse_targets(settings.get("requested_next_batch_targets") or LOCKED_TARGET_LABEL)
        or LOCKED_TARGETS
    )
    return _target_keys_from_targets(parsed_targets)


def _selected_target_keys(entries: list[dict]) -> list[str]:
    return _target_keys_from_targets(
        [
            {"locale": entry.get("locale", ""), "field": entry.get("field", "")}
            for entry in entries
        ]
    )


def _build_payload(
    settings: dict,
    locked_report: dict,
    locked_diag: dict,
    locked_conditions: list[str],
    docker_result: dict,
    duration_seconds: float,
) -> dict:
    env_conditions = list(settings.get("env_blocking_conditions") or [])
    docker_conditions = list(docker_result.get("blocking_conditions") or [])
    failure_type = docker_result.get("failure_type", "")
    blocking_conditions = _unique(locked_conditions + env_conditions + docker_conditions)
    if failure_type and failure_type not in {"locked_dry_run_not_ready", "next_batch_env_scope_mismatch"}:
        blocking_conditions = _unique(blocking_conditions + [failure_type])

    if locked_conditions:
        execution_status = "blocked_next_batch_locked_dry_run_not_ready"
    elif env_conditions:
        execution_status = "blocked_next_batch_env_scope_mismatch"
    elif failure_type:
        execution_status = "blocked_current_next_batch_executor_scan_failed"
    else:
        execution_status = docker_result.get("execution_status", "")

    dry_run = bool(settings.get("dry_run", True))
    if dry_run and not blocking_conditions and execution_status == "next_batch_real_write_dry_run_ready":
        audit_status = "next_batch_real_write_audit_not_run_dry_run"
    else:
        audit_status = docker_result.get("audit_status", "")
        if not audit_status:
            audit_status = "next_batch_real_write_audit_not_run_dry_run" if dry_run else "next_batch_real_write_audit_not_run"

    selected_entries = list(docker_result.get("next_batch_selected_entries") or [])
    requested_target_keys = list(
        docker_result.get("next_batch_requested_target_keys")
        or _requested_target_keys(settings)
    )
    selected_target_keys = list(
        docker_result.get("next_batch_selected_target_keys")
        or _selected_target_keys(selected_entries)
    )
    missing_target_keys = list(docker_result.get("next_batch_missing_target_keys") or [])
    missing_target_diagnostics = list(
        docker_result.get("next_batch_missing_target_diagnostics") or []
    )

    payload = {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run" if dry_run else settings["mode"],
        "requested_mode": settings["mode"],
        "dry_run": dry_run,
        "generated_at": utc_now_iso(),
        "duration_seconds": duration_seconds,
        "execution_status": execution_status,
        "audit_status": audit_status,
        "product_id": settings["product_id"],
        "next_batch_only": bool(settings.get("next_batch_only")),
        "requested_next_batch_targets": settings["requested_next_batch_targets"],
        "next_batch_requested_target_keys": requested_target_keys,
        "next_batch_selected_target_keys": selected_target_keys,
        "next_batch_missing_target_keys": missing_target_keys,
        "next_batch_missing_target_diagnostics": missing_target_diagnostics,
        "max_entries": int(settings.get("max_entries") or 0),
        "source_locked_dry_run_report_path": str(LOCKED_DRY_RUN_REPORT_PATH),
        "source_locked_dry_run_report_exists": bool(locked_diag.get("file_exists")),
        "source_locked_dry_run_report_error": locked_diag.get("error", ""),
        "source_next_batch_locked_status": locked_report.get("next_batch_locked_status", ""),
        "source_locked_next_batch_ready": locked_report.get("locked_next_batch_ready"),
        "locked_next_batch_real_write_ready": bool(
            locked_report.get("locked_next_batch_ready") is True
            and not locked_conditions
        ),
        "next_batch_selected_entries": selected_entries,
        "next_batch_selected_count": int(docker_result.get("next_batch_selected_count") or 0),
        "translations_register_payload_count": int(
            docker_result.get("translations_register_payload_count") or 0
        ),
        "write_attempted_count": int(docker_result.get("write_attempted_count") or 0),
        "write_succeeded_count": int(docker_result.get("write_succeeded_count") or 0),
        "verified_count": int(docker_result.get("verified_count") or 0),
        "post_write_readback_required": True,
        "post_write_readback_expected_count": LOCKED_MAX_ENTRIES,
        "post_write_readback_checked": bool(docker_result.get("post_write_readback_checked")),
        "post_write_readback_verified_count": int(
            docker_result.get("post_write_readback_verified_count") or 0
        ),
        "post_write_readback_mismatches": list(
            docker_result.get("post_write_readback_mismatches") or []
        ),
        "manual_next_batch_real_write_allowed_next_step": bool(
            dry_run
            and execution_status == "next_batch_real_write_dry_run_ready"
            and not blocking_conditions
            and int(docker_result.get("next_batch_selected_count") or 0) == LOCKED_MAX_ENTRIES
            and int(docker_result.get("translations_register_payload_count") or 0) == LOCKED_MAX_ENTRIES
        ),
        "blocking_conditions": blocking_conditions,
        "env_blocking_conditions": env_conditions,
        "locked_dry_run_blocking_conditions": locked_conditions,
        "next_batch_real_write_command_powershell": _real_write_command_preview(),
        "post_next_batch_real_write_check_command_powershell": _post_write_check_command(),
        "rollback_approval_required": bool(docker_result.get("rollback_approval_required")),
        "rollback_performed": False,
        "shopify_api_call_performed": bool(docker_result.get("shopify_api_call_performed")),
        "shopify_write_performed": bool(docker_result.get("shopify_write_performed")),
        "mutation_performed": bool(docker_result.get("mutation_performed")),
        "translations_register_called": bool(docker_result.get("translations_register_called")),
        "email_sent": False,
        "gmail_api_call_performed": False,
        "no_new_shopify_writes_performed": not bool(docker_result.get("shopify_write_performed")),
        "all_new_actions_no_write_confirmed": not bool(
            docker_result.get("shopify_write_performed")
            or docker_result.get("mutation_performed")
            or docker_result.get("translations_register_called")
        ),
        "safety_flags": {
            "shopify_api_call_performed": bool(docker_result.get("shopify_api_call_performed")),
            "shopify_write_performed": bool(docker_result.get("shopify_write_performed")),
            "mutation_performed": bool(docker_result.get("mutation_performed")),
            "translations_register_called": bool(docker_result.get("translations_register_called")),
            "rollback_performed": False,
            "email_sent": False,
            "gmail_api_call_performed": False,
            "no_new_shopify_writes_performed": not bool(docker_result.get("shopify_write_performed")),
        },
        "docker_command": docker_result.get("docker_command", ""),
        "docker_return_code": docker_result.get("docker_return_code"),
        "docker_stdout_tail": docker_result.get("docker_stdout_tail", ""),
        "docker_stderr_tail": docker_result.get("docker_stderr_tail", ""),
        "docker_failure_type": failure_type,
    }
    return payload


def _run_executor_in_docker(settings: dict) -> dict:
    script = _docker_python_script(settings)
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
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
        }
    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        if parsed:
            parsed.setdefault("failure_type", "docker_command_failed")
            parsed["docker_return_code"] = completed.returncode
            parsed["docker_stdout_tail"] = _tail(stdout)
            parsed["docker_stderr_tail"] = _tail(stderr)
            parsed["docker_command"] = _command_for_report(command)
            return parsed
        return {
            "success": False,
            "failure_type": "docker_command_failed",
            "docker_command": _command_for_report(command),
            "docker_return_code": completed.returncode,
            "docker_stdout_tail": _tail(stdout),
            "docker_stderr_tail": _tail(stderr),
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
        }
    if not parsed:
        return {
            "success": False,
            "failure_type": "docker_stdout_json_parse_error",
            "docker_command": _command_for_report(command),
            "docker_return_code": completed.returncode,
            "docker_stdout_tail": _tail(stdout),
            "docker_stderr_tail": _tail(stderr),
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
        }
    parsed["docker_command"] = _command_for_report(command)
    parsed["docker_return_code"] = completed.returncode
    parsed["docker_stdout_tail"] = _tail(stdout)
    parsed["docker_stderr_tail"] = _tail(stderr)
    return parsed


def _docker_python_script(settings: dict) -> str:
    settings_json = json.dumps(settings, ensure_ascii=False)
    return f"""
import json

from shopify_sync.models import ShopifyInstallation
from shopify_sync.translation_real_write_execute import (
    _manual_entries,
    _manual_package_blocking_conditions,
    _post_write_readback,
    _pre_write_readback,
    _regenerate_manual_action_package,
    _translations_register,
    _unique,
)
from shopify_sync.translation_real_write_manual_action_package import PACKAGE_READY_STATUS

settings = json.loads({settings_json!r})
PRODUCT_ID = {PRODUCT_ID!r}
LOCKED_TARGETS = {LOCKED_TARGETS!r}
LOCKED_TARGET_LABEL = {LOCKED_TARGET_LABEL!r}
LOCKED_MAX_ENTRIES = {LOCKED_MAX_ENTRIES!r}
LOCKED_TARGET_LOCALES = {LOCKED_TARGET_LOCALES!r}
TARGET_LOCALES = {TARGET_LOCALES!r}
REQUESTED_FIELDS = {REQUESTED_FIELDS!r}
REAL_RUN_MODES = {sorted(REAL_RUN_MODES)!r}

def safe_entry(entry):
    planned_value = entry.get("planned_value") or entry.get("proposed_translation") or ""
    state = entry.get("pre_existing_translation_state") or {{}}
    return {{
        "product_id": entry.get("product_id", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "key": entry.get("key", ""),
        "digest": entry.get("digest", ""),
        "pre_write_digest": entry.get("pre_write_digest", ""),
        "digest_matches": bool(entry.get("digest_matches")),
        "proposed_value_chars": len(planned_value),
        "seo_warning": seo_warning(entry.get("field", ""), len(planned_value)),
        "would_write": bool(entry.get("would_write")),
        "current_translation_present": bool(state.get("existing_translation_present")),
        "current_translation_outdated": bool(state.get("existing_translation_outdated")),
        "write_performed": bool(entry.get("write_performed")),
        "verified": bool(entry.get("verified")),
        "post_write_readback_value_digest": entry.get("post_write_readback_value_digest", ""),
        "post_write_readback_value_chars": int(entry.get("post_write_readback_value_chars") or 0),
        "post_write_outdated": entry.get("post_write_outdated"),
        "blocking_conditions": list(entry.get("blocking_reasons") or []),
    }}

def seo_warning(field, chars):
    if field == "meta_description" and chars > 160:
        return "meta_description_over_160"
    if field == "title" and chars > 60:
        return "title_over_60"
    return ""

def entry_matches_target(entry, target):
    return (
        entry.get("locale") == target.get("locale")
        and (entry.get("field") == target.get("field") or entry.get("key") == target.get("field"))
        and entry.get("would_write")
    )

def scan_entry_matches_target(entry, target):
    return (
        entry.get("locale") == target.get("locale")
        and (entry.get("field") == target.get("field") or entry.get("key") == target.get("field"))
    )

def target_key(locale, field):
    return str(locale or "") + ":" + str(field or "")

def target_key_for_target(target):
    return target_key(target.get("locale", ""), target.get("field", ""))

def target_key_for_entry(entry):
    return target_key(entry.get("locale", ""), entry.get("field") or entry.get("key", ""))

def first_scan_entry(entries, target):
    for entry in entries:
        if scan_entry_matches_target(entry, target):
            return entry
    return {{}}

def locked_digest(locale, field):
    for entry in settings.get("locked_target_entries") or []:
        if entry.get("locale") == locale and entry.get("field") == field:
            return entry.get("digest", "")
    return ""

def locked_entry(locale, field):
    for entry in settings.get("locked_target_entries") or []:
        if entry.get("locale") == locale and entry.get("field") == field:
            return entry
    return {{}}

def missing_target_diagnostic(target, scan_entries, readback_entries):
    scan_entry = first_scan_entry(scan_entries, target)
    readback_entry = first_scan_entry(readback_entries, target)
    locked = locked_entry(target.get("locale"), target.get("field"))
    planned_value = (
        scan_entry.get("planned_value")
        or scan_entry.get("proposed_translation")
        or readback_entry.get("planned_value")
        or readback_entry.get("proposed_translation")
        or ""
    )
    proposed_value_chars = len(planned_value) if planned_value else int(locked.get("proposed_value_chars") or 0)
    state = {{}}
    state.update(scan_entry.get("current_translation_state") or {{}})
    state.update(readback_entry.get("pre_existing_translation_state") or {{}})
    current_translation_present = bool(
        state.get("existing_translation_present")
        or state.get("current_translation_present")
    )
    current_translation_outdated = (
        state.get("existing_translation_outdated") is True
        or state.get("current_translation_outdated") is True
    )
    locked_report_digest = locked.get("digest", "")
    current_scan_digest = (
        scan_entry.get("digest")
        or readback_entry.get("pre_write_digest")
        or readback_entry.get("digest")
        or ""
    )
    digest_matches = bool(
        locked_report_digest
        and current_scan_digest
        and locked_report_digest == current_scan_digest
    )
    blocking_reasons = []
    blocking_reasons.extend(scan_entry.get("blocking_reasons") or [])
    blocking_reasons.extend(readback_entry.get("blocking_reasons") or [])
    warning = seo_warning(target.get("field", ""), proposed_value_chars)
    if warning:
        blocking_reasons.append(warning)
    if current_translation_present:
        blocking_reasons.append("current_translation_present")
    if current_translation_outdated:
        blocking_reasons.append("current_translation_outdated")
    if current_scan_digest and locked_report_digest and current_scan_digest != locked_report_digest:
        blocking_reasons.append("next_batch_digest_changed")
    found_in_current_scan = bool(scan_entry)
    would_write = bool(scan_entry.get("would_write")) if found_in_current_scan else False
    if current_translation_present:
        exclusion_reason = "current_translation_present"
    elif current_translation_outdated:
        exclusion_reason = "current_translation_outdated"
    elif not found_in_current_scan:
        exclusion_reason = "not_found_in_manual_action_entries"
    elif not digest_matches:
        exclusion_reason = "digest_changed"
    elif warning:
        exclusion_reason = "seo_warning"
    elif not would_write:
        exclusion_reason = "would_write_false"
    else:
        exclusion_reason = "not_selected"
    return {{
        "locale": target.get("locale", ""),
        "field": target.get("field", ""),
        "found_in_current_scan": found_in_current_scan,
        "current_translation_present": current_translation_present,
        "current_translation_outdated": current_translation_outdated,
        "digest_matches": digest_matches,
        "seo_warning": warning,
        "would_write": would_write,
        "blocking_conditions": _unique(blocking_reasons),
        "skipped_reason": exclusion_reason,
        "exclusion_reason": exclusion_reason,
        "locked_report_entry_found": bool(locked),
        "locked_report_digest": locked_report_digest,
        "current_scan_digest": current_scan_digest,
        "proposed_value_chars": proposed_value_chars,
    }}

result = {{
    "success": False,
    "execution_status": "",
    "audit_status": "",
    "blocking_conditions": [],
    "next_batch_selected_entries": [],
    "next_batch_selected_count": 0,
    "next_batch_requested_target_keys": [target_key_for_target(target) for target in LOCKED_TARGETS],
    "next_batch_selected_target_keys": [],
    "next_batch_missing_target_keys": [],
    "next_batch_missing_target_diagnostics": [],
    "translations_register_payload_count": 0,
    "write_attempted_count": 0,
    "write_succeeded_count": 0,
    "verified_count": 0,
    "post_write_readback_checked": False,
    "post_write_readback_verified_count": 0,
    "post_write_readback_mismatches": [],
    "rollback_approval_required": False,
    "rollback_performed": False,
    "shopify_api_call_performed": False,
    "shopify_write_performed": False,
    "mutation_performed": False,
    "translations_register_called": False,
}}
installation = ShopifyInstallation.objects.first()
if not installation:
    result["failure_type"] = "blocked_missing_shopify_installation"
    result["blocking_conditions"].append("blocked_missing_shopify_installation")
    result["execution_status"] = "blocked_current_next_batch_executor_scan_failed"
    result["audit_status"] = "next_batch_real_write_audit_not_run"
    print(json.dumps(result, ensure_ascii=False))
else:
    product_id = settings.get("product_id") or PRODUCT_ID
    manual = _regenerate_manual_action_package(
        installation,
        product_id,
        TARGET_LOCALES,
        REQUESTED_FIELDS,
    )
    blocking = []
    blocking.extend(_manual_package_blocking_conditions(manual))
    if manual.get("package_status") != PACKAGE_READY_STATUS:
        blocking.append("manual_action_package_not_ready")
    entries = _manual_entries(manual)
    selected = []
    missing_targets = []
    for target in LOCKED_TARGETS:
        candidates = [entry for entry in entries if entry_matches_target(entry, target)]
        if len(candidates) == 0:
            blocking.append("next_batch_target_missing")
            missing_targets.append(target)
        elif len(candidates) > 1:
            blocking.append("next_batch_target_not_unique")
        else:
            selected.append(candidates[0])
    if missing_targets:
        missing_readback_entries = []
        for target in missing_targets:
            locked = locked_entry(target.get("locale"), target.get("field"))
            missing_readback_entries.append({{
                "product_id": product_id,
                "locale": target.get("locale", ""),
                "field": target.get("field", ""),
                "key": target.get("field", ""),
                "digest": locked.get("digest", ""),
                "planned_value": "",
                "proposed_translation": "",
                "would_write": False,
                "blocking_reasons": [],
            }})
        missing_precheck = _pre_write_readback(
            installation,
            product_id,
            LOCKED_TARGET_LOCALES,
            missing_readback_entries,
        )
        result["shopify_api_call_performed"] = bool(missing_precheck.get("performed"))
        result["next_batch_missing_target_diagnostics"] = [
            missing_target_diagnostic(
                target,
                entries,
                missing_precheck.get("entries") or [],
            )
            for target in missing_targets
        ]
        result["next_batch_missing_target_keys"] = [
            target_key_for_target(target) for target in missing_targets
        ]
    if len(selected) != LOCKED_MAX_ENTRIES:
        blocking.append("next_batch_selected_count_not_two")

    for entry in selected:
        locked = locked_digest(entry.get("locale"), entry.get("field"))
        if entry.get("product_id") != product_id:
            entry["blocking_reasons"] = _unique(list(entry.get("blocking_reasons") or []) + ["next_batch_product_id_mismatch"])
            blocking.append("next_batch_product_id_mismatch")
        if not locked or entry.get("digest") != locked:
            entry["blocking_reasons"] = _unique(list(entry.get("blocking_reasons") or []) + ["next_batch_digest_changed"])
            blocking.append("next_batch_digest_changed")
        if {{"locale": entry.get("locale"), "field": entry.get("field")}} not in LOCKED_TARGETS:
            entry["blocking_reasons"] = _unique(list(entry.get("blocking_reasons") or []) + ["next_batch_unexpected_target"])
            blocking.append("next_batch_unexpected_target")
        planned_value = entry.get("planned_value") or entry.get("proposed_translation") or ""
        seo = seo_warning(entry.get("field", ""), len(planned_value))
        if seo:
            entry["blocking_reasons"] = _unique(list(entry.get("blocking_reasons") or []) + ["next_batch_seo_warning", seo])
            blocking.append("next_batch_seo_warning")
        if entry.get("blocking_reasons"):
            blocking.extend(entry.get("blocking_reasons") or [])

    precheck = _pre_write_readback(installation, product_id, LOCKED_TARGET_LOCALES, selected)
    result["shopify_api_call_performed"] = bool(precheck.get("performed"))
    selected = precheck.get("entries") or selected
    blocking.extend(precheck.get("blocking_conditions") or [])
    for entry in selected:
        state = entry.get("pre_existing_translation_state") or {{}}
        if state.get("existing_translation_present"):
            blocking.append("next_batch_existing_translation")
        if state.get("existing_translation_outdated"):
            blocking.append("next_batch_existing_translation")
        if not entry.get("digest_matches"):
            blocking.append("next_batch_digest_changed")
    selected_count = len(selected)
    payload_count = sum(1 for entry in selected if entry.get("would_write"))
    if selected_count != LOCKED_MAX_ENTRIES:
        blocking.append("next_batch_selected_count_not_two")
    if payload_count != LOCKED_MAX_ENTRIES:
        blocking.append("next_batch_payload_count_not_two")

    real_run_requested = settings.get("mode") in REAL_RUN_MODES and settings.get("dry_run") is False
    env_blocking = list(settings.get("env_blocking_conditions") or [])
    blocking.extend(env_blocking)
    real_write_allowed = bool(
        real_run_requested
        and not blocking
        and settings.get("ack_matches") is True
        and settings.get("env_product_id") == PRODUCT_ID
        and settings.get("next_batch_only") is True
        and settings.get("env_max_entries") == LOCKED_MAX_ENTRIES
        and settings.get("env_next_batch_targets_raw") == LOCKED_TARGET_LABEL
        and selected_count == LOCKED_MAX_ENTRIES
        and payload_count == LOCKED_MAX_ENTRIES
    )
    if real_run_requested and not real_write_allowed:
        blocking.append("next_batch_real_write_preconditions_not_met")

    mutation_called = False
    if real_write_allowed:
        mutation = _translations_register(installation, product_id, selected)
        mutation_called = bool(mutation.get("called"))
        result["translations_register_called"] = mutation_called
        result["mutation_performed"] = mutation_called
        result["shopify_write_performed"] = mutation_called
        result["translations_register_user_errors"] = mutation.get("user_errors") or []
        result["write_attempted_count"] = payload_count if mutation_called else 0
        if mutation.get("user_errors"):
            blocking.append("translations_register_user_errors_present")
        if mutation.get("request_failed"):
            blocking.append("translations_register_request_failed")
        result["write_succeeded_count"] = payload_count if mutation_called and not mutation.get("user_errors") and not mutation.get("request_failed") else 0
        for entry in selected:
            entry["write_performed"] = mutation_called and entry.get("would_write")
        postcheck = _post_write_readback(installation, product_id, LOCKED_TARGET_LOCALES, selected)
        result["post_write_readback_checked"] = bool(postcheck.get("performed"))
        selected = postcheck.get("entries") or selected
        result["verified_count"] = int(postcheck.get("verified_count") or 0)
        result["post_write_readback_verified_count"] = result["verified_count"]
        mismatches = [
            {{
                "locale": entry.get("locale", ""),
                "field": entry.get("field", ""),
                "key": entry.get("key", ""),
                "post_write_readback_value_chars": int(entry.get("post_write_readback_value_chars") or 0),
            }}
            for entry in selected
            if entry.get("write_performed") and not entry.get("verified")
        ]
        result["post_write_readback_mismatches"] = mismatches
        blocking.extend(postcheck.get("blocking_conditions") or [])

    result["blocking_conditions"] = _unique(blocking)
    result["next_batch_selected_entries"] = [safe_entry(entry) for entry in selected]
    result["next_batch_selected_target_keys"] = [
        target_key_for_entry(entry) for entry in selected
    ]
    result["next_batch_selected_count"] = selected_count
    result["translations_register_payload_count"] = payload_count
    if settings.get("dry_run") is True:
        result["execution_status"] = (
            "next_batch_real_write_dry_run_ready"
            if not result["blocking_conditions"] and selected_count == LOCKED_MAX_ENTRIES and payload_count == LOCKED_MAX_ENTRIES
            else "blocked_next_batch_real_write_dry_run_not_ready"
        )
        result["audit_status"] = "next_batch_real_write_audit_not_run_dry_run"
    elif mutation_called and result["verified_count"] == LOCKED_MAX_ENTRIES and not result["blocking_conditions"]:
        result["execution_status"] = "next_batch_real_write_succeeded_and_verified"
        result["audit_status"] = "next_batch_real_write_audit_passed"
    elif mutation_called:
        result["execution_status"] = "next_batch_real_write_failed_or_unverified"
        result["audit_status"] = "next_batch_real_write_audit_failed_or_needs_review"
        result["rollback_approval_required"] = True
    else:
        result["execution_status"] = "blocked_next_batch_real_write_preconditions_failed"
        result["audit_status"] = "next_batch_real_write_audit_not_run"
    result["success"] = result["execution_status"] in {{
        "next_batch_real_write_dry_run_ready",
        "next_batch_real_write_succeeded_and_verified",
    }}
    result["rollback_performed"] = False
    print(json.dumps(result, ensure_ascii=False))
"""


def _locked_report_blocking_conditions(report: dict, diag: dict) -> list[str]:
    if not diag.get("file_exists"):
        return ["missing_next_batch_locked_dry_run_report"]
    if diag.get("error"):
        return [f"next_batch_locked_dry_run_report_{diag['error']}"]
    expected = {
        "next_batch_locked_status": "next_batch_locked_dry_run_ready",
        "locked_next_batch_ready": True,
        "locked_next_batch_target_product_id": PRODUCT_ID,
        "locked_next_batch_max_entries": LOCKED_MAX_ENTRIES,
        "next_batch_candidate_count": LOCKED_MAX_ENTRIES,
        "would_write_count": LOCKED_MAX_ENTRIES,
        "future_next_batch_real_write_allowed": False,
        "future_next_batch_real_write_needs_next_phase": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "blocking_conditions": [],
    }
    conditions = []
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            conditions.append(f"{key}_not_ready")
    target_entries = report.get("locked_next_batch_target_entries") or []
    target_pairs = [(entry.get("locale"), entry.get("field")) for entry in target_entries]
    expected_pairs = [(target["locale"], target["field"]) for target in LOCKED_TARGETS]
    if target_pairs != expected_pairs or len(target_entries) != LOCKED_MAX_ENTRIES:
        conditions.append("locked_next_batch_target_entries_mismatch")
    return _unique(conditions)


def _locked_entries_from_locked_report(report: dict) -> list[dict]:
    entries = []
    source_entries = report.get("locked_next_batch_target_entries") or []
    for target in LOCKED_TARGETS:
        match = next(
            (
                entry
                for entry in source_entries
                if entry.get("locale") == target["locale"]
                and entry.get("field") == target["field"]
            ),
            {},
        )
        entries.append(
            {
                "product_id": match.get("product_id") or PRODUCT_ID,
                "locale": target["locale"],
                "field": target["field"],
                "key": match.get("key") or target["field"],
                "digest": match.get("digest", ""),
                "proposed_value_chars": int(match.get("proposed_value_chars") or 0),
            }
        )
    return entries


def _real_write_command_preview() -> list[str]:
    return [
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_ACK="I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE"',
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID="{PRODUCT_ID}"',
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES="{LOCKED_MAX_ENTRIES}"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN="0"',
        '$env:SHOPIFY_TRANSLATION_NEXT_BATCH_ONLY="1"',
        f'$env:SHOPIFY_TRANSLATION_NEXT_BATCH_TARGETS="{LOCKED_TARGET_LABEL}"',
        f"python remote_approval_runner.py --task {TASK_NAME} --mode real-run --approval local",
    ]


def _post_write_check_command() -> str:
    keys = [
        "execution_status",
        "audit_status",
        "mode",
        "dry_run",
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "translations_register_payload_count",
        "write_attempted_count",
        "write_succeeded_count",
        "verified_count",
        "post_write_readback_checked",
        "post_write_readback_verified_count",
        "post_write_readback_mismatches",
        "rollback_approval_required",
        "rollback_performed",
        "blocking_conditions",
        "requested_next_batch_targets",
        "next_batch_requested_target_keys",
        "next_batch_selected_target_keys",
        "next_batch_missing_target_keys",
        "next_batch_missing_target_diagnostics",
        "next_batch_selected_count",
    ]
    keys_literal = repr(keys)
    return (
        "python -c \"import json; "
        "p='logs/shopify_translation_next_batch_real_write_execute.json'; "
        "d=json.load(open(p,encoding='utf-8')); "
        f"keys={keys_literal}; "
        "print(json.dumps({k:d.get(k) for k in keys}, ensure_ascii=False, indent=2))\""
    )


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
            ("Execution Status", "execution_status"),
            ("Audit Status", "audit_status"),
            ("Mode", "mode"),
            ("Dry Run", "dry_run"),
            ("Product ID", "product_id"),
            ("Requested Targets", "requested_next_batch_targets"),
            ("Requested Target Keys", "next_batch_requested_target_keys"),
            ("Selected Target Keys", "next_batch_selected_target_keys"),
            ("Missing Target Keys", "next_batch_missing_target_keys"),
            ("Selected Count", "next_batch_selected_count"),
            ("Payload Count", "translations_register_payload_count"),
            ("Manual Next Step Allowed", "manual_next_batch_real_write_allowed_next_step"),
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
            ("Email Sent", "email_sent"),
            ("Gmail API Call Performed", "gmail_api_call_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
        ]
    )
    entry_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('key', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('pre_write_digest', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars', '')))}</td>"
        f"<td>{escape(str(entry.get('seo_warning', '')))}</td>"
        f"<td>{escape(str(entry.get('would_write', '')))}</td>"
        f"<td>{escape(str(entry.get('write_performed', '')))}</td>"
        f"<td>{escape(str(entry.get('verified', '')))}</td>"
        f"<td>{escape(json.dumps(entry.get('blocking_conditions', []), ensure_ascii=False))}</td>"
        "</tr>"
        for entry in payload.get("next_batch_selected_entries", [])
    )
    missing_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(item.get('locale', '')))}</td>"
        f"<td>{escape(str(item.get('field', '')))}</td>"
        f"<td>{escape(str(item.get('found_in_current_scan', '')))}</td>"
        f"<td>{escape(str(item.get('current_translation_present', '')))}</td>"
        f"<td>{escape(str(item.get('current_translation_outdated', '')))}</td>"
        f"<td>{escape(str(item.get('digest_matches', '')))}</td>"
        f"<td>{escape(str(item.get('seo_warning', '')))}</td>"
        f"<td>{escape(str(item.get('would_write', '')))}</td>"
        f"<td>{escape(str(item.get('locked_report_entry_found', '')))}</td>"
        f"<td>{escape(str(item.get('locked_report_digest', '')))}</td>"
        f"<td>{escape(str(item.get('current_scan_digest', '')))}</td>"
        f"<td>{escape(str(item.get('proposed_value_chars', '')))}</td>"
        f"<td>{escape(str(item.get('exclusion_reason', '')))}</td>"
        f"<td>{escape(json.dumps(item.get('blocking_conditions', []), ensure_ascii=False))}</td>"
        "</tr>"
        for item in payload.get("next_batch_missing_target_diagnostics", [])
    )
    command_rows = "\n".join(
        f"<li><code>{escape(line)}</code></li>"
        for line in payload.get("next_batch_real_write_command_powershell", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Next Batch Real-Write Execute</title></head>
<body>
  <h1>Next Batch Real-Write Execute</h1>
  <p>Phase 16.8. Dry-run mode is no-write. Real-run is gated by exact ACK, product, target list, digest, SEO, and count checks, then requires immediate readback verification.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Selected Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Key</th><th>Digest</th><th>Pre-Write Digest</th><th>Chars</th><th>SEO Warning</th><th>Would Write</th><th>Write Performed</th><th>Verified</th><th>Blocking Conditions</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Missing Target Diagnostics</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Found In Current Scan</th><th>Current Translation Present</th><th>Current Translation Outdated</th><th>Digest Matches</th><th>SEO Warning</th><th>Would Write</th><th>Locked Entry Found</th><th>Locked Digest</th><th>Current Digest</th><th>Chars</th><th>Exclusion Reason</th><th>Blocking Conditions</th></tr></thead>
    <tbody>{missing_rows}</tbody>
  </table>
  <h2>Future Real-Write Command Preview</h2>
  <p>Do not run this in Phase 16.8 validation. It is a preview for a later explicit manual real-run.</p>
  <ol>{command_rows}</ol>
</body>
</html>
"""


def _row(label: str, value) -> str:
    rendered = (
        json.dumps(value, ensure_ascii=False)
        if isinstance(value, (dict, list))
        else str(value)
    )
    return f"<tr><th>{escape(label)}</th><td>{escape(rendered)}</td></tr>"


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Phase 16.8 next-batch real-write executor report generated.\n"
        f"- execution_status: {payload.get('execution_status')}\n"
        f"- audit_status: {payload.get('audit_status')}\n"
        f"- dry_run: {payload.get('dry_run')}\n"
        f"- next_batch_missing_target_keys: {payload.get('next_batch_missing_target_keys')}\n"
        f"- next_batch_selected_count: {payload.get('next_batch_selected_count')}\n"
        f"- translations_register_payload_count: {payload.get('translations_register_payload_count')}\n"
        f"- manual_next_batch_real_write_allowed_next_step: {payload.get('manual_next_batch_real_write_allowed_next_step')}\n"
        f"- shopify_write_performed: {payload.get('shopify_write_performed')}\n"
        f"- mutation_performed: {payload.get('mutation_performed')}\n"
        f"- translations_register_called: {payload.get('translations_register_called')}\n"
        f"- rollback_performed: {payload.get('rollback_performed')}\n"
        f"- blocking_conditions: {payload.get('blocking_conditions')}\n"
        f"- JSON: {json_path}\n"
        f"- HTML: {html_path}\n\n"
        "Reply 1 to keep the generated report, or 0 to stop. Do not run real-run unless explicitly requested in a later step."
    )


def _parse_targets(value: str) -> list[dict]:
    targets = []
    for part in (value or "").split(","):
        if ":" not in part:
            continue
        locale, field = [piece.strip() for piece in part.split(":", 1)]
        if locale and field:
            targets.append({"locale": locale, "field": field})
    return targets


def _parse_int(value: str):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _decode_bytes(value: bytes) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _command_for_report(command: list[str]) -> str:
    if command and command[-2:-1] == ["-c"]:
        return " ".join(command[:-1] + ["<python shell script omitted>"])
    return " ".join(command)
