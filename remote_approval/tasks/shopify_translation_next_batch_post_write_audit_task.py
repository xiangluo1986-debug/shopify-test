import json
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


TASK_NAME = "shopify_translation_next_batch_post_write_audit"
PHASE = "16.9"
PRODUCT_ID = "gid://shopify/Product/7655686799427"
NEXT_BATCH_TARGETS = [
    {"locale": "it", "field": "meta_description"},
    {"locale": "ja", "field": "title"},
]
WRITTEN_TARGETS = [
    {"locale": "de", "field": "meta_title"},
    {"locale": "fr", "field": "meta_title"},
    {"locale": "es", "field": "meta_title"},
    {"locale": "it", "field": "meta_title"},
    *NEXT_BATCH_TARGETS,
]
TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
REQUESTED_FIELDS = ["title", "meta_title", "meta_description"]
SOURCE_REPORT_PATH = LOG_DIR / "shopify_translation_next_batch_real_write_execute.json"
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_next_batch_post_write_audit.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_next_batch_post_write_audit.html"
DOCKER_TIMEOUT_SECONDS = 1200


def run_shopify_translation_next_batch_post_write_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_diag = _read_json(SOURCE_REPORT_PATH)
    completion_conditions = _completion_blocking_conditions(
        source_report,
        source_diag,
    )
    docker_result = (
        _source_blocked_docker_result()
        if completion_conditions
        else _run_readonly_audit_in_docker()
    )
    payload = _build_payload(
        source_report=source_report,
        source_diag=source_diag,
        completion_conditions=completion_conditions,
        docker_result=docker_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = (
        payload["next_batch_completion_status"]
        == "next_batch_real_write_completed_and_verified"
        and payload["readback_audit_status"] == "next_batch_readback_confirmed"
        and payload["duplicate_write_protection_status"] == "duplicate_write_prevented"
        and payload["readback_verified_count"] == len(NEXT_BATCH_TARGETS)
        and payload["written_entries_count"] == len(NEXT_BATCH_TARGETS)
        and not payload["completion_blocking_conditions"]
        and not payload["blocking_conditions"]
        and payload["shopify_write_performed"] is False
        and payload["mutation_performed"] is False
        and payload["translations_register_called"] is False
        and payload["rollback_performed"] is False
    )
    return {
        "task_type": TASK_NAME,
        "success": bool(success),
        "exit_code": 0 if success else 1,
        "command_label": TASK_NAME,
        "review_path": str(json_path),
        "json_next_batch_post_write_audit_path": str(json_path),
        "html_next_batch_post_write_audit_path": str(html_path),
        "phase": PHASE,
        "next_batch_completion_status": payload["next_batch_completion_status"],
        "readback_audit_status": payload["readback_audit_status"],
        "duplicate_write_protection_status": payload[
            "duplicate_write_protection_status"
        ],
        "remaining_eligible_count": payload["remaining_eligible_count"],
        "next_recommended_batch_status": payload["next_recommended_batch_status"],
        "next_recommended_batch_count": payload["next_recommended_batch_count"],
        "shopify_api_call_performed": payload["shopify_api_call_performed"],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "blocking_conditions": payload["blocking_conditions"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _build_payload(
    source_report: dict,
    source_diag: dict,
    completion_conditions: list[str],
    docker_result: dict,
    duration_seconds: float,
) -> dict:
    completion_conditions = list(completion_conditions)
    blocking_conditions = list(completion_conditions)
    if docker_result.get("failure_type"):
        blocking_conditions.append(docker_result["failure_type"])

    readback_entries = [
        _attach_source_report_match(entry, source_report)
        for entry in list(docker_result.get("readback_entries") or [])
    ]
    readback_mismatches = _readback_mismatches(readback_entries, docker_result)
    if readback_mismatches:
        blocking_conditions.append("next_batch_readback_needs_review")

    manual_package = docker_result.get("manual_action_package") or {}
    eligible_entries = list(manual_package.get("eligible_entries") or [])
    duplicate_still_eligible = _duplicate_targets_still_eligible(eligible_entries)
    if duplicate_still_eligible:
        blocking_conditions.append("duplicate_targets_still_eligible_after_successful_write")

    remaining_entries = _remaining_eligible_entries(eligible_entries)
    recommended_entries = _next_batch_recommendations(remaining_entries)
    readback_verified_count = sum(
        1
        for entry in readback_entries
        if entry.get("current_translation_exists") is True
        and entry.get("translation_outdated") is not True
        and entry.get("matches_source_report") is True
    )
    source_ready = not completion_conditions
    readback_status = (
        "next_batch_readback_confirmed"
        if source_ready
        and docker_result.get("success")
        and readback_verified_count == len(NEXT_BATCH_TARGETS)
        and not readback_mismatches
        else "next_batch_readback_needs_review"
    )
    duplicate_status = (
        "duplicate_write_prevented"
        if source_ready and docker_result.get("success") and not duplicate_still_eligible
        else "duplicate_write_protection_needs_review"
    )
    next_status = (
        "next_candidates_ready_for_locked_dry_run"
        if recommended_entries
        and all(not entry.get("seo_warning") for entry in recommended_entries)
        else (
            "next_candidates_need_seo_rewrite"
            if recommended_entries
            else "next_candidates_insufficient"
        )
    )

    payload = {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run",
        "dry_run": True,
        "generated_at": utc_now_iso(),
        "duration_seconds": duration_seconds,
        "source_next_batch_real_write_report_path": str(SOURCE_REPORT_PATH),
        "source_next_batch_real_write_report_exists": bool(
            source_diag.get("file_exists")
        ),
        "source_next_batch_real_write_report_error": source_diag.get("error", ""),
        "source_execution_status": source_report.get("execution_status", ""),
        "source_audit_status": source_report.get("audit_status", ""),
        "source_mode": source_report.get("mode", ""),
        "source_dry_run": source_report.get("dry_run"),
        "source_shopify_write_performed": bool(
            source_report.get("shopify_write_performed")
        ),
        "source_mutation_performed": bool(source_report.get("mutation_performed")),
        "source_translations_register_called": bool(
            source_report.get("translations_register_called")
        ),
        "next_batch_completion_status": (
            "next_batch_real_write_completed_and_verified"
            if source_ready
            else "next_batch_completion_needs_review"
        ),
        "completion_blocking_conditions": _unique(completion_conditions),
        "written_target_entries": NEXT_BATCH_TARGETS,
        "written_entries_count": len(NEXT_BATCH_TARGETS) if source_ready else 0,
        "readback_audit_performed": bool(docker_result.get("success")),
        "readback_audit_status": readback_status,
        "readback_verified_count": readback_verified_count,
        "readback_mismatches": readback_mismatches,
        "readback_entries": readback_entries,
        "duplicate_write_protection_checked": bool(docker_result.get("success")),
        "duplicate_target_entries": NEXT_BATCH_TARGETS,
        "duplicate_targets_still_eligible": duplicate_still_eligible,
        "duplicate_write_protection_status": duplicate_status,
        "remaining_eligible_count": len(remaining_entries),
        "remaining_eligible_entries": remaining_entries,
        "next_recommended_batch_count": len(recommended_entries),
        "next_recommended_batch_entries": recommended_entries,
        "next_recommended_batch_status": next_status,
        "next_locked_dry_run_command_powershell": _next_locked_dry_run_command_preview(
            recommended_entries
        ),
        "rollback_needed": False,
        "rollback_performed": False,
        "shopify_api_call_performed": bool(docker_result.get("shopify_api_call_performed")),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "email_sent": False,
        "gmail_api_call_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "safety_flags": {
            "shopify_api_call_performed": bool(
                docker_result.get("shopify_api_call_performed")
            ),
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
            "email_sent": False,
            "gmail_api_call_performed": False,
            "no_new_shopify_writes_performed": True,
            "all_new_actions_no_write_confirmed": True,
        },
        "manual_action_package_status": manual_package.get("package_status", ""),
        "manual_action_entry_count": int(manual_package.get("entry_count") or 0),
        "manual_action_blocked_entry_count": int(
            manual_package.get("blocked_entry_count") or 0
        ),
        "manual_action_blocking_conditions": list(
            manual_package.get("blocking_conditions") or []
        ),
        "docker_stdout_json_parsed": bool(docker_result.get("docker_stdout_json_parsed")),
        "docker_command": docker_result.get("docker_command", ""),
        "docker_return_code": docker_result.get("docker_return_code"),
        "docker_stdout_tail": docker_result.get("docker_stdout_tail", ""),
        "docker_stderr_tail": docker_result.get("docker_stderr_tail", ""),
        "docker_failure_type": docker_result.get("failure_type", ""),
        "blocking_conditions": _unique(blocking_conditions),
    }
    return payload


def _completion_blocking_conditions(report: dict, diag: dict) -> list[str]:
    if not diag.get("file_exists"):
        return ["missing_next_batch_real_write_execute_report"]
    if diag.get("error"):
        return [f"next_batch_real_write_execute_report_{diag['error']}"]

    conditions = []
    expected_values = {
        "execution_status": "next_batch_real_write_succeeded_and_verified",
        "audit_status": "next_batch_real_write_audit_passed",
        "mode": "real-run",
        "dry_run": False,
        "product_id": PRODUCT_ID,
        "requested_next_batch_targets": "it:meta_description,ja:title",
        "next_batch_selected_count": 2,
        "translations_register_payload_count": 2,
        "write_attempted_count": 2,
        "write_succeeded_count": 2,
        "verified_count": 2,
        "post_write_readback_checked": True,
        "post_write_readback_verified_count": 2,
        "post_write_readback_mismatches": [],
        "rollback_approval_required": False,
        "rollback_performed": False,
        "blocking_conditions": [],
    }
    for key, expected_value in expected_values.items():
        if report.get(key) != expected_value:
            conditions.append(f"{key}_mismatch")

    for key in [
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
    ]:
        if report.get(key) is not bool(1):
            conditions.append(f"source_{key}_not_confirmed")
    return _unique(conditions)


def _source_blocked_docker_result() -> dict:
    return {
        "success": False,
        "failure_type": "",
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
    }


def _run_readonly_audit_in_docker() -> dict:
    script = _docker_python_script()
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
            "shopify_api_call_performed": False,
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
            parsed["docker_command"] = _command_for_report(command)
            parsed["docker_return_code"] = completed.returncode
            parsed["docker_stdout_tail"] = _tail(stdout)
            parsed["docker_stderr_tail"] = _tail(stderr)
            return parsed
        return {
            "success": False,
            "failure_type": "docker_command_failed",
            "docker_command": _command_for_report(command),
            "docker_return_code": completed.returncode,
            "docker_stdout_tail": _tail(stdout),
            "docker_stderr_tail": _tail(stderr),
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
        }
    if not parsed:
        return {
            "success": False,
            "failure_type": "docker_stdout_json_parse_error",
            "docker_stdout_json_parsed": False,
            "docker_command": _command_for_report(command),
            "docker_return_code": completed.returncode,
            "docker_stdout_tail": _tail(stdout),
            "docker_stderr_tail": _tail(stderr),
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
        }
    parsed["success"] = parsed.get("success") is True
    parsed["docker_stdout_json_parsed"] = True
    parsed["docker_command"] = _command_for_report(command)
    parsed["docker_return_code"] = completed.returncode
    parsed["docker_stdout_tail"] = _tail(stdout)
    parsed["docker_stderr_tail"] = _tail(stderr)
    return parsed


def _docker_python_script() -> str:
    return f"""
import json

from shopify_sync.models import ShopifyInstallation
from shopify_sync.translation_console import fetch_translation_console_data
from shopify_sync.translation_real_write_execute import (
    _manual_entries,
    _regenerate_manual_action_package,
    _row_for_key,
    _value_digest,
)

PRODUCT_ID = {PRODUCT_ID!r}
NEXT_BATCH_TARGETS = {NEXT_BATCH_TARGETS!r}
TARGET_LOCALES = {TARGET_LOCALES!r}
REQUESTED_FIELDS = {REQUESTED_FIELDS!r}

def seo_warning(field, chars):
    if field == "meta_description" and chars > 160:
        return "meta_description_over_160"
    if field in {{"title", "meta_title"}} and chars > 60:
        return field + "_over_60"
    return ""

def safe_entry(entry):
    planned_value = entry.get("planned_value") or entry.get("proposed_translation") or ""
    state = entry.get("current_translation_state") or entry.get("pre_existing_translation_state") or {{}}
    key = entry.get("key") or entry.get("resource_key") or entry.get("field") or ""
    present = bool(
        state.get("existing_translation_present")
        or state.get("current_translation_present")
        or entry.get("current_translation_present")
    )
    outdated = bool(
        state.get("existing_translation_outdated")
        or state.get("current_translation_outdated")
        or entry.get("current_translation_outdated")
    )
    return {{
        "product_id": entry.get("product_id", "") or PRODUCT_ID,
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "key": key,
        "resource_key": key,
        "digest": entry.get("digest", ""),
        "proposed_value_chars": len(planned_value),
        "would_write": bool(entry.get("would_write")),
        "current_translation_present": present,
        "current_translation_outdated": outdated,
        "blocking_reasons": list(entry.get("blocking_reasons") or []),
        "seo_warning": seo_warning(entry.get("field", ""), len(planned_value)),
    }}

def readback_entry(installation, target):
    locale = target.get("locale", "")
    field = target.get("field", "")
    data = fetch_translation_console_data(installation, PRODUCT_ID, locale)
    row = _row_for_key(data, field)
    value = row.get("translation_value", "") or ""
    exists = bool(row.get("has_translation") or value)
    return {{
        "product_id": PRODUCT_ID,
        "locale": locale,
        "field": field,
        "current_translation_exists": exists,
        "current_translation_digest": _value_digest(value) if exists else "",
        "current_translation_chars": len(value) if exists else 0,
        "source_digest": row.get("digest", ""),
        "translation_outdated": row.get("translation_outdated") is True,
    }}

result = {{
    "success": False,
    "readback_entries": [],
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
    try:
        result["shopify_api_call_performed"] = True
        result["readback_entries"] = [
            readback_entry(installation, target) for target in NEXT_BATCH_TARGETS
        ]
        manual = _regenerate_manual_action_package(
            installation,
            PRODUCT_ID,
            TARGET_LOCALES,
            REQUESTED_FIELDS,
        )
        entries = [safe_entry(entry) for entry in _manual_entries(manual)]
        result["manual_action_package"] = {{
            "package_status": manual.get("package_status", ""),
            "entry_count": manual.get("entry_count", 0),
            "blocked_entry_count": manual.get("blocked_entry_count", 0),
            "blocking_conditions": list(manual.get("blocking_conditions") or []),
            "eligible_entries": [entry for entry in entries if entry.get("would_write")],
        }}
        result["success"] = True
    except Exception as exc:
        result["failure_type"] = "readonly_audit_exception"
        result["command_exception_type"] = exc.__class__.__name__
        result["command_exception_message"] = str(exc)
    print(json.dumps(result, ensure_ascii=False))
"""


def _attach_source_report_match(entry: dict, source_report: dict) -> dict:
    output = dict(entry)
    report_entry = _entry_for_target(
        source_report.get("next_batch_selected_entries") or [],
        output.get("locale", ""),
        output.get("field", ""),
    )
    report_digest = report_entry.get("post_write_readback_value_digest", "")
    report_chars = int(report_entry.get("post_write_readback_value_chars") or 0)
    if report_digest:
        output["matches_source_report"] = (
            output.get("current_translation_exists") is True
            and output.get("current_translation_digest") == report_digest
            and (not report_chars or output.get("current_translation_chars") == report_chars)
        )
        output["match_basis"] = "post_write_readback_value_digest_and_chars"
    elif (
        source_report.get("verified_count") == len(NEXT_BATCH_TARGETS)
        and source_report.get("post_write_readback_verified_count")
        == len(NEXT_BATCH_TARGETS)
        and source_report.get("post_write_readback_mismatches") == []
        and output.get("current_translation_exists") is True
    ):
        output["matches_source_report"] = True
        output["match_basis"] = "verified_source_report_and_current_translation_exists"
    else:
        output["matches_source_report"] = False
        output["match_basis"] = "insufficient_source_digest_or_verification"
    return output


def _readback_mismatches(readback_entries: list[dict], docker_result: dict) -> list[dict]:
    if not docker_result.get("success"):
        if docker_result.get("failure_type"):
            return [{"reason": docker_result["failure_type"]}]
        return []
    mismatches = []
    for target in NEXT_BATCH_TARGETS:
        entry = _entry_for_target(readback_entries, target["locale"], target["field"])
        if not entry:
            mismatches.append({**target, "reason": "readback_target_missing"})
            continue
        if entry.get("current_translation_exists") is not True:
            mismatches.append({**target, "reason": "current_translation_missing"})
        if entry.get("translation_outdated") is True:
            mismatches.append({**target, "reason": "current_translation_outdated"})
        if entry.get("matches_source_report") is not True:
            mismatches.append({**target, "reason": "source_report_mismatch"})
    return mismatches


def _duplicate_targets_still_eligible(eligible_entries: list[dict]) -> list[dict]:
    still_eligible = []
    for target in NEXT_BATCH_TARGETS:
        entry = _entry_for_target(eligible_entries, target["locale"], target["field"])
        if entry and entry.get("would_write") is True:
            still_eligible.append(_safe_report_entry(entry))
    return still_eligible


def _remaining_eligible_entries(eligible_entries: list[dict]) -> list[dict]:
    written = {(target["locale"], target["field"]) for target in WRITTEN_TARGETS}
    remaining = []
    for entry in eligible_entries:
        key = (entry.get("locale", ""), entry.get("field", ""))
        if key in written:
            continue
        remaining.append(_safe_report_entry(entry))
    return remaining


def _next_batch_recommendations(remaining_entries: list[dict]) -> list[dict]:
    clean = [
        entry
        for entry in remaining_entries
        if entry.get("would_write") is True
        and not entry.get("current_translation_present")
        and not entry.get("current_translation_outdated")
        and not entry.get("blocking_reasons")
        and not entry.get("seo_warning")
    ]
    if clean:
        return sorted(clean, key=_recommendation_sort_key)[:3]
    review_candidates = [
        entry
        for entry in remaining_entries
        if entry.get("would_write") is True
        and not entry.get("current_translation_present")
        and not entry.get("current_translation_outdated")
        and not entry.get("blocking_reasons")
    ]
    return sorted(review_candidates, key=_recommendation_sort_key)[:3]


def _recommendation_sort_key(entry: dict) -> tuple[int, int, int]:
    field = entry.get("field", "")
    chars = int(entry.get("proposed_value_chars") or 0)
    field_priority = {"meta_description": 0, "meta_title": 1, "title": 2}.get(field, 9)
    seo_penalty = 1 if entry.get("seo_warning") else 0
    locale_priority = (
        TARGET_LOCALES.index(entry.get("locale", ""))
        if entry.get("locale", "") in TARGET_LOCALES
        else 99
    )
    return (seo_penalty, field_priority, locale_priority, chars)


def _safe_report_entry(entry: dict) -> dict:
    field = entry.get("field", "")
    chars = int(entry.get("proposed_value_chars") or 0)
    return {
        "product_id": entry.get("product_id", "") or PRODUCT_ID,
        "locale": entry.get("locale", ""),
        "field": field,
        "key": entry.get("key", "") or entry.get("resource_key", "") or field,
        "resource_key": entry.get("resource_key", "") or entry.get("key", "") or field,
        "digest": entry.get("digest", ""),
        "proposed_value_chars": chars,
        "would_write": bool(entry.get("would_write")),
        "current_translation_present": bool(entry.get("current_translation_present")),
        "current_translation_outdated": bool(entry.get("current_translation_outdated")),
        "blocking_reasons": list(entry.get("blocking_reasons") or []),
        "seo_warning": entry.get("seo_warning", "") or _seo_warning(field, chars),
    }


def _seo_warning(field: str, chars: int) -> str:
    if field == "meta_description" and chars > 160:
        return "meta_description_over_160"
    if field == "title" and chars > 60:
        return "title_over_60"
    if field == "meta_title" and chars > 60:
        return "meta_title_over_60"
    return ""


def _entry_for_target(entries: list[dict], locale: str, field: str) -> dict:
    for entry in entries:
        if entry.get("locale") == locale and (
            entry.get("field") == field or entry.get("key") == field
        ):
            return entry
    return {}


def _next_locked_dry_run_command_preview(recommended_entries: list[dict]) -> list[str]:
    targets = ",".join(
        f"{entry.get('locale')}:{entry.get('field')}" for entry in recommended_entries
    )
    return [
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID="{PRODUCT_ID}"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN="1"',
        '$env:SHOPIFY_TRANSLATION_NEXT_BATCH_ONLY="1"',
        f'$env:SHOPIFY_TRANSLATION_NEXT_BATCH_TARGETS="{targets}"',
        "python remote_approval_runner.py --task shopify_translation_next_batch_locked_dry_run_package --approval local",
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
            ("Completion Status", "next_batch_completion_status"),
            ("Readback Audit Status", "readback_audit_status"),
            ("Written Entries Count", "written_entries_count"),
            ("Readback Verified Count", "readback_verified_count"),
            ("Duplicate Protection Status", "duplicate_write_protection_status"),
            ("Remaining Eligible Count", "remaining_eligible_count"),
            ("Next Recommended Batch Status", "next_recommended_batch_status"),
            ("Next Recommended Batch Count", "next_recommended_batch_count"),
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
            ("Translations Register Called", "translations_register_called"),
            ("Rollback Performed", "rollback_performed"),
            ("Email Sent", "email_sent"),
            ("Gmail API Call Performed", "gmail_api_call_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
        ]
    )
    readback_rows = _entry_rows(
        payload.get("readback_entries", []),
        [
            "locale",
            "field",
            "current_translation_exists",
            "current_translation_chars",
            "current_translation_digest",
            "translation_outdated",
            "matches_source_report",
            "match_basis",
        ],
    )
    remaining_rows = _entry_rows(
        payload.get("remaining_eligible_entries", []),
        [
            "locale",
            "field",
            "key",
            "digest",
            "proposed_value_chars",
            "would_write",
            "current_translation_present",
            "current_translation_outdated",
            "blocking_reasons",
            "seo_warning",
        ],
    )
    recommendation_rows = _entry_rows(
        payload.get("next_recommended_batch_entries", []),
        ["locale", "field", "key", "digest", "proposed_value_chars", "seo_warning"],
    )
    command_rows = "\n".join(
        f"<li><code>{escape(line)}</code></li>"
        for line in payload.get("next_locked_dry_run_command_powershell", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Next Batch Post-Write Audit</title></head>
<body>
  <h1>Next Batch Post-Write Audit</h1>
  <p>Phase 16.9. This audit is read-only/no-write. It validates the previous real-run report, confirms duplicate protection, scans remaining eligible entries, and suggests a future dry-run batch only.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Readback Audit</h2>
  <table border="1" cellspacing="0" cellpadding="6">{readback_rows}</table>
  <h2>Remaining Eligible Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">{remaining_rows}</table>
  <h2>Next Recommendation</h2>
  <table border="1" cellspacing="0" cellpadding="6">{recommendation_rows}</table>
  <h2>Future Dry-Run Command Preview</h2>
  <ol>{command_rows}</ol>
</body>
</html>
"""


def _entry_rows(entries: list[dict], fields: list[str]) -> str:
    header = "".join(f"<th>{escape(field)}</th>" for field in fields)
    rows = []
    for entry in entries:
        cells = []
        for field in fields:
            value = entry.get(field, "")
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False)
            cells.append(f"<td>{escape(str(value))}</td>")
        rows.append(f"<tr>{''.join(cells)}</tr>")
    return f"<thead><tr>{header}</tr></thead><tbody>{''.join(rows)}</tbody>"


def _row(label: str, value) -> str:
    rendered = (
        json.dumps(value, ensure_ascii=False)
        if isinstance(value, (dict, list))
        else str(value)
    )
    return f"<tr><th>{escape(label)}</th><td>{escape(rendered)}</td></tr>"


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Phase 16.9 next-batch post-write audit generated.\n"
        f"- next_batch_completion_status: {payload.get('next_batch_completion_status')}\n"
        f"- readback_audit_status: {payload.get('readback_audit_status')}\n"
        f"- duplicate_write_protection_status: {payload.get('duplicate_write_protection_status')}\n"
        f"- remaining_eligible_count: {payload.get('remaining_eligible_count')}\n"
        f"- next_recommended_batch_status: {payload.get('next_recommended_batch_status')}\n"
        f"- next_recommended_batch_count: {payload.get('next_recommended_batch_count')}\n"
        f"- shopify_write_performed: {payload.get('shopify_write_performed')}\n"
        f"- mutation_performed: {payload.get('mutation_performed')}\n"
        f"- translations_register_called: {payload.get('translations_register_called')}\n"
        f"- rollback_performed: {payload.get('rollback_performed')}\n"
        f"- blocking_conditions: {payload.get('blocking_conditions')}\n"
        f"- JSON: {json_path}\n"
        f"- HTML: {html_path}\n\n"
        "Reply 1 to keep the generated report, or 0 to stop. This task is read-only/no-write."
    )


def _decode_bytes(value: bytes) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _command_for_report(command: list[str]) -> str:
    if command and command[-2:-1] == ["-c"]:
        return " ".join(command[:-1] + ["<python shell script omitted>"])
    return " ".join(command)
