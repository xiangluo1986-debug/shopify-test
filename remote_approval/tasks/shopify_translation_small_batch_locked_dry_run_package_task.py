import json
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_small_batch_locked_dry_run_package"
PHASE = "16.3"
PRODUCT_ID = "gid://shopify/Product/7655686799427"
TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
REQUESTED_FIELDS = ["title", "meta_title", "meta_description"]
LOCKED_TARGETS = [
    {"locale": "fr", "field": "meta_title"},
    {"locale": "es", "field": "meta_title"},
    {"locale": "it", "field": "meta_title"},
]
LOCKED_BATCH_LOCALES = ["fr", "es", "it"]
LOCKED_BATCH_FIELD = "meta_title"
LOCKED_BATCH_MAX_ENTRIES = 3
FIRST_AUDIT_REPORT_PATH = LOG_DIR / "shopify_translation_first_real_write_completion_audit.json"
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_small_batch_locked_dry_run_package.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_small_batch_locked_dry_run_package.html"
DOCKER_TIMEOUT_SECONDS = 1200


def run_shopify_translation_small_batch_locked_dry_run_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    first_audit, first_audit_diag = _read_json(FIRST_AUDIT_REPORT_PATH)
    first_audit_conditions = _first_audit_blocking_conditions(
        first_audit, first_audit_diag
    )
    docker_result = _run_current_manual_action_package_in_docker()
    payload = _build_payload(
        first_audit=first_audit,
        first_audit_diag=first_audit_diag,
        first_audit_conditions=first_audit_conditions,
        docker_result=docker_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = (
        payload["small_batch_locked_status"] == "small_batch_locked_dry_run_ready"
        and payload["locked_small_batch_ready"] is True
        and payload["small_batch_candidate_count"] == LOCKED_BATCH_MAX_ENTRIES
        and payload["would_write_count"] == LOCKED_BATCH_MAX_ENTRIES
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
        "json_small_batch_locked_dry_run_package_path": str(json_path),
        "html_small_batch_locked_dry_run_package_path": str(html_path),
        "phase": PHASE,
        "small_batch_locked_status": payload["small_batch_locked_status"],
        "locked_small_batch_ready": payload["locked_small_batch_ready"],
        "small_batch_candidate_count": payload["small_batch_candidate_count"],
        "would_write_count": payload["would_write_count"],
        "future_small_batch_real_write_allowed": False,
        "future_small_batch_real_write_needs_next_phase": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "blocking_conditions": payload["blocking_conditions"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _build_payload(
    first_audit: dict,
    first_audit_diag: dict,
    first_audit_conditions: list[str],
    docker_result: dict,
    duration_seconds: float,
) -> dict:
    first_audit_entries = _target_entries_from_first_audit(first_audit)
    current_entries = list(
        (docker_result.get("manual_action_package") or {}).get("eligible_entries") or []
    )
    if docker_result.get("failure_type"):
        match_result = _current_scan_failed_match(first_audit_entries, docker_result["failure_type"])
    else:
        match_result = _match_locked_targets(first_audit_entries, current_entries)
    blocking_conditions = list(first_audit_conditions)
    if docker_result.get("failure_type"):
        blocking_conditions.append(docker_result["failure_type"])
    blocking_conditions.extend(match_result["blocking_conditions"])
    blocking_conditions = _unique(blocking_conditions)

    small_batch_locked_status = _small_batch_status(
        first_audit_conditions=first_audit_conditions,
        docker_result=docker_result,
        match_result=match_result,
    )
    locked_ready = (
        small_batch_locked_status == "small_batch_locked_dry_run_ready"
        and not blocking_conditions
    )
    payload = {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run",
        "dry_run": True,
        "generated_at": utc_now_iso(),
        "duration_seconds": duration_seconds,
        "source_first_real_write_completion_audit_report_path": str(
            FIRST_AUDIT_REPORT_PATH
        ),
        "source_first_real_write_completion_audit_report_exists": bool(
            first_audit_diag.get("file_exists")
        ),
        "source_first_real_write_completion_audit_report_error": first_audit_diag.get(
            "error", ""
        ),
        "source_first_real_write_completion_audit_status": first_audit.get(
            "first_real_write_completion_status", ""
        ),
        "source_readback_audit_status": first_audit.get("readback_audit_status", ""),
        "source_duplicate_write_protection_status": first_audit.get(
            "duplicate_write_protection_status", ""
        ),
        "source_small_batch_readiness_status": first_audit.get(
            "small_batch_readiness_status", ""
        ),
        "source_small_batch_recommended_count": int(
            first_audit.get("small_batch_recommended_count") or 0
        ),
        "first_write_audit_blocking_conditions": first_audit_conditions,
        "small_batch_locked_status": small_batch_locked_status,
        "locked_small_batch_ready": locked_ready,
        "locked_small_batch_target_product_id": PRODUCT_ID,
        "locked_small_batch_target_entries": match_result["locked_entries"],
        "locked_small_batch_max_entries": LOCKED_BATCH_MAX_ENTRIES,
        "locked_small_batch_entry_count": len(match_result["locked_entries"]),
        "small_batch_candidate_count": match_result["candidate_count"],
        "would_write_count": match_result["would_write_count"],
        "blocking_conditions": blocking_conditions,
        "small_batch_dry_run_command_powershell": _dry_run_command_preview(),
        "future_small_batch_real_write_requirements": [
            "Future phase only; this package never enables real writes.",
            "Must remain scoped to one product and the locked fr/es/it meta_title entries.",
            "Must require a separate explicit manual ACK and a new post-write readback audit.",
            "Must call translationsRegister at most once and only in a later real-run phase.",
        ],
        "future_small_batch_real_write_allowed": False,
        "future_small_batch_real_write_needs_next_phase": True,
        "shopify_api_call_performed": bool(docker_result.get("success")),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "email_sent": False,
        "gmail_api_call_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "safety_flags": {
            "shopify_api_call_performed": bool(docker_result.get("success")),
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "rollback_performed": False,
            "email_sent": False,
            "gmail_api_call_performed": False,
            "no_new_shopify_writes_performed": True,
            "all_new_actions_no_write_confirmed": True,
        },
        "manual_action_package_status": (docker_result.get("manual_action_package") or {}).get(
            "package_status", ""
        ),
        "manual_action_entry_count": (docker_result.get("manual_action_package") or {}).get(
            "entry_count", 0
        ),
        "manual_action_blocked_entry_count": (
            docker_result.get("manual_action_package") or {}
        ).get("blocked_entry_count", 0),
        "manual_action_blocking_conditions": (
            docker_result.get("manual_action_package") or {}
        ).get("blocking_conditions", []),
        "docker_stdout_json_parsed": bool(docker_result.get("docker_stdout_json_parsed")),
        "docker_command": docker_result.get("docker_command", ""),
        "docker_return_code": docker_result.get("docker_return_code"),
        "docker_stdout_tail": docker_result.get("docker_stdout_tail", ""),
        "docker_stderr_tail": docker_result.get("docker_stderr_tail", ""),
        "docker_failure_type": docker_result.get("failure_type", ""),
    }
    return payload


def _first_audit_blocking_conditions(report: dict, diag: dict) -> list[str]:
    if not diag.get("file_exists"):
        return ["missing_first_real_write_completion_audit_report"]
    if diag.get("error"):
        return [f"first_real_write_completion_audit_report_{diag['error']}"]
    conditions = []
    expected = {
        "first_real_write_completion_status": "first_real_write_completed_and_verified",
        "readback_audit_status": "first_real_write_readback_confirmed",
        "duplicate_write_protection_status": "duplicate_write_prevented",
        "small_batch_readiness_status": "small_batch_candidates_ready_for_dry_run",
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            conditions.append(f"{key}_not_ready")
    if int(report.get("small_batch_recommended_count") or 0) < LOCKED_BATCH_MAX_ENTRIES:
        conditions.append("small_batch_recommended_count_lt_3")
    recommended = report.get("small_batch_recommended_entries") or []
    for target in LOCKED_TARGETS:
        if not _entry_for_target(recommended, target["locale"], target["field"]):
            conditions.append(
                f"locked_small_batch_target_missing_from_first_audit_{target['locale']}_{target['field']}"
            )
    return conditions


def _target_entries_from_first_audit(report: dict) -> dict[tuple[str, str], dict]:
    recommended = report.get("small_batch_recommended_entries") or []
    locked = {}
    for target in LOCKED_TARGETS:
        entry = _entry_for_target(recommended, target["locale"], target["field"]) or {}
        locked[(target["locale"], target["field"])] = _safe_entry(
            {
                **entry,
                "product_id": entry.get("product_id") or PRODUCT_ID,
                "locale": target["locale"],
                "field": target["field"],
                "would_write": bool(entry.get("would_write", True)),
            }
        )
    return locked


def _match_locked_targets(
    first_audit_entries: dict[tuple[str, str], dict],
    current_entries: list[dict],
) -> dict:
    blocking_conditions = []
    locked_entries = []
    candidate_count = 0
    would_write_count = 0
    for target in LOCKED_TARGETS:
        key = (target["locale"], target["field"])
        first_entry = first_audit_entries.get(key) or {}
        current_entry = _entry_for_target(
            current_entries, target["locale"], target["field"]
        )
        if not current_entry:
            target_entry = {
                **first_entry,
                "product_id": first_entry.get("product_id") or PRODUCT_ID,
                "locale": target["locale"],
                "field": target["field"],
                "would_write": False,
                "blocking_reasons": _unique(
                    list(first_entry.get("blocking_reasons") or [])
                    + ["locked_small_batch_target_missing"]
                ),
                "digest_matches_first_audit": False,
                "current_scan_present": False,
            }
            blocking_conditions.append("locked_small_batch_target_missing")
            locked_entries.append(target_entry)
            continue

        current_safe = _safe_entry(current_entry)
        first_digest = first_entry.get("digest", "")
        current_digest = current_safe.get("digest", "")
        digest_matches = bool(first_digest and current_digest and first_digest == current_digest)
        current_safe["digest_matches_first_audit"] = digest_matches
        current_safe["current_scan_present"] = True
        current_safe["first_audit_digest"] = first_digest
        candidate_count += 1

        entry_blockers = list(current_safe.get("blocking_reasons") or [])
        if current_safe.get("would_write") is not True:
            entry_blockers.append("locked_small_batch_entry_not_marked_would_write")
        if current_safe.get("current_translation_present"):
            entry_blockers.append("locked_small_batch_existing_translation")
            blocking_conditions.append("locked_small_batch_existing_translation")
        if current_safe.get("current_translation_outdated"):
            entry_blockers.append("locked_small_batch_existing_translation")
            blocking_conditions.append("locked_small_batch_existing_translation")
        if not digest_matches:
            entry_blockers.append("locked_small_batch_digest_changed")
            blocking_conditions.append("locked_small_batch_digest_changed")
        if int(current_safe.get("proposed_value_chars") or 0) > 60:
            entry_blockers.append("locked_small_batch_meta_title_over_60_chars")
        if not current_safe.get("digest"):
            entry_blockers.append("locked_small_batch_missing_digest")
        current_safe["blocking_reasons"] = _unique(entry_blockers)
        current_safe["seo_warning"] = (
            "over_ideal_seo_chars"
            if int(current_safe.get("proposed_value_chars") or 0) > 60
            else ""
        )
        if current_safe.get("would_write") and not current_safe["blocking_reasons"]:
            would_write_count += 1
        elif current_safe["blocking_reasons"]:
            blocking_conditions.append("locked_small_batch_candidate_not_ready")
        locked_entries.append(current_safe)
    return {
        "locked_entries": locked_entries,
        "candidate_count": candidate_count,
        "would_write_count": would_write_count,
        "blocking_conditions": _unique(blocking_conditions),
    }


def _current_scan_failed_match(
    first_audit_entries: dict[tuple[str, str], dict], failure_type: str
) -> dict:
    locked_entries = []
    for target in LOCKED_TARGETS:
        first_entry = first_audit_entries.get((target["locale"], target["field"])) or {}
        locked_entries.append(
            {
                **first_entry,
                "product_id": first_entry.get("product_id") or PRODUCT_ID,
                "locale": target["locale"],
                "field": target["field"],
                "would_write": False,
                "blocking_reasons": _unique(
                    list(first_entry.get("blocking_reasons") or [])
                    + [failure_type, "current_small_batch_scan_not_performed"]
                ),
                "digest_matches_first_audit": False,
                "current_scan_present": False,
            }
        )
    return {
        "locked_entries": locked_entries,
        "candidate_count": 0,
        "would_write_count": 0,
        "blocking_conditions": [],
    }


def _small_batch_status(
    first_audit_conditions: list[str],
    docker_result: dict,
    match_result: dict,
) -> str:
    blockers = match_result.get("blocking_conditions") or []
    if first_audit_conditions:
        return "blocked_first_write_audit_not_ready"
    if docker_result.get("failure_type"):
        return "blocked_current_small_batch_scan_failed"
    if "locked_small_batch_target_missing" in blockers:
        return "blocked_locked_target_missing"
    if "locked_small_batch_digest_changed" in blockers:
        return "blocked_locked_target_digest_changed"
    if "locked_small_batch_existing_translation" in blockers:
        return "blocked_locked_target_existing_translation"
    if blockers:
        return "blocked_locked_target_not_ready"
    if (
        match_result.get("candidate_count") == LOCKED_BATCH_MAX_ENTRIES
        and match_result.get("would_write_count") == LOCKED_BATCH_MAX_ENTRIES
    ):
        return "small_batch_locked_dry_run_ready"
    return "blocked_locked_target_not_ready"


def _run_current_manual_action_package_in_docker() -> dict:
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
            "docker_stdout_json_parse_error": "No complete top-level JSON object found in Docker stdout.",
            "docker_command": _command_for_report(command),
            "docker_return_code": completed.returncode,
            "docker_stdout_tail": _tail(stdout),
            "docker_stderr_tail": _tail(stderr),
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
from shopify_sync.translation_apply_plan import build_selected_product_translation_apply_plan
from shopify_sync.translation_drafts import generate_selected_product_missing_translation_draft_package
from shopify_sync.translation_final_review import build_selected_product_translation_final_review
from shopify_sync.translation_locked_execution_plan import build_selected_product_translation_locked_execution_plan
from shopify_sync.translation_locked_executor import build_selected_product_translation_locked_executor_shell
from shopify_sync.translation_real_write_executor import build_selected_product_translation_real_write_executor_dry_run
from shopify_sync.translation_real_write_manual_action_package import build_selected_product_translation_real_write_manual_action_package
from shopify_sync.translation_real_write_readiness import build_selected_product_translation_real_write_readiness

PRODUCT_ID = {PRODUCT_ID!r}
TARGET_LOCALES = {TARGET_LOCALES!r}
REQUESTED_FIELDS = {REQUESTED_FIELDS!r}

def safe_entry(entry):
    planned_value = entry.get("planned_value") or entry.get("proposed_translation") or ""
    state = entry.get("current_translation_state") or {{}}
    key = entry.get("planned_key") or entry.get("key") or entry.get("field") or ""
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
        "digest": entry.get("digest", "") or entry.get("planned_translatable_content_digest", ""),
        "planned_value": planned_value,
        "proposed_translation": planned_value,
        "planned_value_source": "manual_action_entries" if planned_value else "",
        "proposed_value_chars": len(planned_value),
        "would_write": bool(entry.get("would_write")),
        "current_translation_present": present,
        "current_translation_outdated": outdated,
        "blocking_reasons": list(entry.get("blocking_reasons") or []),
        "seo_warning": "",
    }}

def safe_draft_entry(entry):
    field = entry.get("field") or entry.get("source_key") or ""
    planned_value = entry.get("draft_value") or entry.get("proposed_translation") or ""
    return {{
        "product_id": PRODUCT_ID,
        "locale": entry.get("locale", ""),
        "field": field,
        "key": field,
        "resource_key": field,
        "digest": entry.get("source_digest", "") or entry.get("digest", ""),
        "planned_value": planned_value,
        "proposed_translation": planned_value,
        "planned_value_source": "draft_package_fallback" if planned_value else "",
        "source_value": entry.get("source_value", ""),
        "proposed_value_chars": len(planned_value),
        "would_write": bool(planned_value),
        "current_translation_present": bool(entry.get("existing_translation_present")),
        "current_translation_outdated": entry.get("existing_translation_outdated") is True,
        "blocking_reasons": [],
        "seo_warning": "",
        "draft_validation_status": entry.get("validation_status", ""),
        "draft_seo_validation_status": entry.get("seo_validation_status", ""),
        "draft_eligible_for_apply_plan": bool(entry.get("eligible_for_apply_plan")),
        "draft_seo_eligible_for_apply_plan": bool(entry.get("seo_eligible_for_apply_plan")),
    }}

result = {{
    "success": False,
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
    draft_entries = [safe_draft_entry(entry) for entry in draft.get("draft_entries", [])]
    result["manual_action_package"] = {{
        "package_status": manual.get("package_status", ""),
        "entry_count": manual.get("entry_count", 0),
        "blocked_entry_count": manual.get("blocked_entry_count", 0),
        "blocking_conditions": list(manual.get("blocking_conditions") or []),
        "eligible_entries": [entry for entry in entries if entry.get("would_write")],
        "draft_entries": draft_entries,
    }}
    result["shopify_api_call_performed"] = True
    result["success"] = True
    print(json.dumps(result, ensure_ascii=False))
"""


def _safe_entry(entry: dict) -> dict:
    chars = int(entry.get("proposed_value_chars") or 0)
    field = entry.get("field", "")
    return {
        "product_id": entry.get("product_id", "") or PRODUCT_ID,
        "locale": entry.get("locale", ""),
        "field": field,
        "key": entry.get("key", "") or entry.get("resource_key", "") or field,
        "resource_key": entry.get("resource_key", "") or entry.get("key", "") or field,
        "digest": entry.get("digest", ""),
        "planned_value": entry.get("planned_value", ""),
        "proposed_translation": entry.get("proposed_translation", ""),
        "planned_value_source": entry.get("planned_value_source", ""),
        "proposed_value_chars": chars,
        "would_write": bool(entry.get("would_write")),
        "current_translation_present": bool(entry.get("current_translation_present")),
        "current_translation_outdated": bool(entry.get("current_translation_outdated")),
        "blocking_reasons": list(entry.get("blocking_reasons") or []),
        "seo_warning": entry.get("seo_warning", ""),
    }


def _entry_for_target(entries: list[dict], locale: str, field: str) -> dict:
    for entry in entries:
        if entry.get("locale") == locale and entry.get("field") == field:
            return entry
    return {}


def _dry_run_command_preview() -> list[str]:
    return [
        "$env:SHOPIFY_TRANSLATION_REAL_WRITE_ACK=\"I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID=\"{PRODUCT_ID}\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES=\"{LOCKED_BATCH_MAX_ENTRIES}\"",
        "$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN=\"1\"",
        "$env:SHOPIFY_TRANSLATION_REAL_WRITE_SMALL_BATCH_ONLY=\"1\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_BATCH_LOCALES=\"{','.join(LOCKED_BATCH_LOCALES)}\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_BATCH_FIELD=\"{LOCKED_BATCH_FIELD}\"",
        f"python remote_approval_runner.py --task {TASK_NAME} --approval local",
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
            ("Locked Small Batch Status", "small_batch_locked_status"),
            ("Locked Small Batch Ready", "locked_small_batch_ready"),
            ("Target Product ID", "locked_small_batch_target_product_id"),
            ("Locked Entry Count", "locked_small_batch_entry_count"),
            ("Small Batch Candidate Count", "small_batch_candidate_count"),
            ("Would Write Count", "would_write_count"),
            ("Future Real Write Allowed", "future_small_batch_real_write_allowed"),
            ("Future Real Write Needs Next Phase", "future_small_batch_real_write_needs_next_phase"),
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
            ("All New Actions No Write Confirmed", "all_new_actions_no_write_confirmed"),
        ]
    )
    entry_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('key', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars', '')))}</td>"
        f"<td>{escape(str(entry.get('would_write', '')))}</td>"
        f"<td>{escape(str(entry.get('current_translation_present', '')))}</td>"
        f"<td>{escape(str(entry.get('current_translation_outdated', '')))}</td>"
        f"<td>{escape(json.dumps(entry.get('blocking_reasons', []), ensure_ascii=False))}</td>"
        f"<td>{escape(str(entry.get('seo_warning', '')))}</td>"
        "</tr>"
        for entry in payload.get("locked_small_batch_target_entries", [])
    )
    command_rows = "\n".join(
        f"<li><code>{escape(line)}</code></li>"
        for line in payload.get("small_batch_dry_run_command_powershell", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Locked Small Batch Dry-Run Package</title></head>
<body>
  <h1>Locked Small Batch Dry-Run Package</h1>
  <p>Phase 16.3. This package locks fr/es/it meta_title candidates for dry-run review only. It never writes Shopify, calls mutations, calls translationsRegister, sends email, or rolls back.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Locked Target Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Key</th><th>Digest</th><th>Proposed Value Chars</th><th>Would Write</th><th>Current Translation</th><th>Outdated</th><th>Blocking Reasons</th><th>SEO Warning</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Dry-Run Command Preview</h2>
  <ol>{command_rows}</ol>
</body>
</html>
"""


def _row(label: str, value) -> str:
    rendered = json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)
    return f"<tr><th>{escape(label)}</th><td>{escape(rendered)}</td></tr>"


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Phase 16.3 locked small-batch dry-run package generated.\n"
        f"- small_batch_locked_status: {payload.get('small_batch_locked_status')}\n"
        f"- locked_small_batch_ready: {payload.get('locked_small_batch_ready')}\n"
        f"- small_batch_candidate_count: {payload.get('small_batch_candidate_count')}\n"
        f"- would_write_count: {payload.get('would_write_count')}\n"
        f"- future_small_batch_real_write_allowed: {payload.get('future_small_batch_real_write_allowed')}\n"
        f"- future_small_batch_real_write_needs_next_phase: {payload.get('future_small_batch_real_write_needs_next_phase')}\n"
        f"- shopify_write_performed: {payload.get('shopify_write_performed')}\n"
        f"- mutation_performed: {payload.get('mutation_performed')}\n"
        f"- translations_register_called: {payload.get('translations_register_called')}\n"
        f"- rollback_performed: {payload.get('rollback_performed')}\n"
        f"- blocking_conditions: {payload.get('blocking_conditions')}\n"
        f"- JSON: {json_path}\n"
        f"- HTML: {html_path}\n\n"
        "Reply 1 to keep the generated report, or 0 to stop. This task is dry-run/read-only and does not write Shopify."
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
