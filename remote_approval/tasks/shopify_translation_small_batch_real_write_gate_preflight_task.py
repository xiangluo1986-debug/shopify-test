import json
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_translation_small_batch_locked_dry_run_package_task import (
    LOCKED_BATCH_FIELD,
    LOCKED_BATCH_LOCALES,
    LOCKED_BATCH_MAX_ENTRIES,
    LOCKED_TARGETS,
    PRODUCT_ID,
    _entry_for_target,
    _read_json,
    _run_current_manual_action_package_in_docker,
    _safe_entry,
    _unique,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_small_batch_real_write_gate_preflight"
PHASE = "16.4"
LOCKED_DRY_RUN_REPORT_PATH = (
    LOG_DIR / "shopify_translation_small_batch_locked_dry_run_package.json"
)
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_small_batch_real_write_gate_preflight.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_small_batch_real_write_gate_preflight.html"


def run_shopify_translation_small_batch_real_write_gate_preflight_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    locked_report, locked_diag = _read_json(LOCKED_DRY_RUN_REPORT_PATH)
    locked_report_conditions = _locked_report_blocking_conditions(
        locked_report, locked_diag
    )
    docker_result = _run_current_manual_action_package_in_docker()
    payload = _build_payload(
        locked_report=locked_report,
        locked_diag=locked_diag,
        locked_report_conditions=locked_report_conditions,
        docker_result=docker_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = (
        payload["small_batch_real_write_gate_status"]
        == "small_batch_real_write_preflight_ready"
        and payload["manual_small_batch_real_write_allowed_next_step"] is True
        and payload["locked_small_batch_real_write_ready"] is True
        and payload["small_batch_candidate_count"] == LOCKED_BATCH_MAX_ENTRIES
        and payload["would_write_count"] == LOCKED_BATCH_MAX_ENTRIES
        and payload["future_small_batch_real_write_allowed"] is False
        and payload["shopify_write_performed"] is False
        and payload["mutation_performed"] is False
        and payload["translations_register_called"] is False
        and payload["rollback_performed"] is False
        and not payload["blocking_conditions"]
    )
    return {
        "task_type": TASK_NAME,
        "success": bool(success),
        "exit_code": 0 if success else 1,
        "command_label": TASK_NAME,
        "review_path": str(json_path),
        "json_small_batch_real_write_gate_preflight_path": str(json_path),
        "html_small_batch_real_write_gate_preflight_path": str(html_path),
        "phase": PHASE,
        "small_batch_real_write_gate_status": payload[
            "small_batch_real_write_gate_status"
        ],
        "manual_small_batch_real_write_allowed_next_step": payload[
            "manual_small_batch_real_write_allowed_next_step"
        ],
        "locked_small_batch_real_write_ready": payload[
            "locked_small_batch_real_write_ready"
        ],
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
    locked_report: dict,
    locked_diag: dict,
    locked_report_conditions: list[str],
    docker_result: dict,
    duration_seconds: float,
) -> dict:
    locked_report_entries = _target_entries_from_locked_report(locked_report)
    if docker_result.get("failure_type"):
        match_result = _current_scan_failed_match(
            locked_report_entries, docker_result["failure_type"]
        )
    else:
        current_entries = list(
            (docker_result.get("manual_action_package") or {}).get("eligible_entries")
            or []
        )
        match_result = _match_locked_targets(locked_report_entries, current_entries)

    blocking_conditions = list(locked_report_conditions)
    if docker_result.get("failure_type"):
        blocking_conditions.append(docker_result["failure_type"])
    blocking_conditions.extend(match_result["blocking_conditions"])
    blocking_conditions = _unique(blocking_conditions)

    gate_status = _gate_status(locked_report_conditions, docker_result, match_result)
    preflight_ready = (
        gate_status == "small_batch_real_write_preflight_ready"
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
        "source_locked_dry_run_report_path": str(LOCKED_DRY_RUN_REPORT_PATH),
        "source_locked_dry_run_report_exists": bool(locked_diag.get("file_exists")),
        "source_locked_dry_run_report_error": locked_diag.get("error", ""),
        "source_small_batch_locked_status": locked_report.get(
            "small_batch_locked_status", ""
        ),
        "source_locked_small_batch_ready": locked_report.get(
            "locked_small_batch_ready"
        ),
        "source_small_batch_candidate_count": locked_report.get(
            "small_batch_candidate_count", 0
        ),
        "source_would_write_count": locked_report.get("would_write_count", 0),
        "locked_dry_run_blocking_conditions": locked_report_conditions,
        "small_batch_real_write_gate_status": gate_status,
        "manual_small_batch_real_write_allowed_next_step": preflight_ready,
        "locked_small_batch_real_write_ready": preflight_ready,
        "locked_small_batch_target_product_id": PRODUCT_ID,
        "locked_small_batch_target_entries": match_result["locked_entries"],
        "locked_small_batch_max_entries": LOCKED_BATCH_MAX_ENTRIES,
        "small_batch_candidate_count": match_result["candidate_count"],
        "would_write_count": match_result["would_write_count"],
        "blocking_conditions": blocking_conditions,
        "small_batch_real_write_gate_requirements": _gate_requirements(),
        "small_batch_real_write_abort_conditions": _abort_conditions(),
        "locked_small_batch_real_write_command_powershell_preview": _future_real_write_command_preview(),
        "future_small_batch_real_write_allowed": False,
        "future_small_batch_real_write_needs_next_phase": True,
        "small_batch_post_write_audit_expected_fields": _post_write_audit_expected_fields(),
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


def _locked_report_blocking_conditions(report: dict, diag: dict) -> list[str]:
    if not diag.get("file_exists"):
        return ["missing_small_batch_locked_dry_run_report"]
    if diag.get("error"):
        return [f"small_batch_locked_dry_run_report_{diag['error']}"]
    conditions = []
    expected = {
        "small_batch_locked_status": "small_batch_locked_dry_run_ready",
        "locked_small_batch_ready": True,
        "locked_small_batch_target_product_id": PRODUCT_ID,
        "locked_small_batch_max_entries": LOCKED_BATCH_MAX_ENTRIES,
        "small_batch_candidate_count": LOCKED_BATCH_MAX_ENTRIES,
        "would_write_count": LOCKED_BATCH_MAX_ENTRIES,
        "future_small_batch_real_write_allowed": False,
        "future_small_batch_real_write_needs_next_phase": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            conditions.append(f"{key}_not_ready")
    entries = report.get("locked_small_batch_target_entries") or []
    target_pairs = [(entry.get("locale"), entry.get("field")) for entry in entries]
    expected_pairs = [(target["locale"], target["field"]) for target in LOCKED_TARGETS]
    if sorted(target_pairs) != sorted(expected_pairs) or len(entries) != LOCKED_BATCH_MAX_ENTRIES:
        conditions.append("locked_small_batch_target_entries_mismatch")
    for target in LOCKED_TARGETS:
        if not _entry_for_target(entries, target["locale"], target["field"]):
            conditions.append(
                f"locked_small_batch_target_missing_{target['locale']}_{target['field']}"
            )
    return _unique(conditions)


def _target_entries_from_locked_report(report: dict) -> dict[tuple[str, str], dict]:
    entries = report.get("locked_small_batch_target_entries") or []
    locked = {}
    for target in LOCKED_TARGETS:
        entry = _entry_for_target(entries, target["locale"], target["field"]) or {}
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
    locked_report_entries: dict[tuple[str, str], dict],
    current_entries: list[dict],
) -> dict:
    blocking_conditions = []
    locked_entries = []
    candidate_count = 0
    would_write_count = 0
    for target in LOCKED_TARGETS:
        key = (target["locale"], target["field"])
        locked_entry = locked_report_entries.get(key) or {}
        current_entry = _entry_for_target(
            current_entries, target["locale"], target["field"]
        )
        if not current_entry:
            target_entry = {
                **locked_entry,
                "product_id": locked_entry.get("product_id") or PRODUCT_ID,
                "locale": target["locale"],
                "field": target["field"],
                "would_write": False,
                "blocking_reasons": _unique(
                    list(locked_entry.get("blocking_reasons") or [])
                    + ["small_batch_target_missing"]
                ),
                "digest_matches_locked_report": False,
                "current_scan_present": False,
            }
            blocking_conditions.append("small_batch_target_missing")
            locked_entries.append(target_entry)
            continue

        current_safe = _safe_entry(current_entry)
        locked_digest = locked_entry.get("digest", "")
        current_digest = current_safe.get("digest", "")
        digest_matches = bool(
            locked_digest and current_digest and locked_digest == current_digest
        )
        current_safe["digest_matches_locked_report"] = digest_matches
        current_safe["locked_report_digest"] = locked_digest
        current_safe["current_scan_present"] = True
        candidate_count += 1

        entry_blockers = list(current_safe.get("blocking_reasons") or [])
        if current_safe.get("would_write") is not True:
            entry_blockers.append("small_batch_entry_not_marked_would_write")
        if current_safe.get("current_translation_present"):
            entry_blockers.append("small_batch_existing_translation")
            blocking_conditions.append("small_batch_existing_translation")
        if current_safe.get("current_translation_outdated"):
            entry_blockers.append("small_batch_existing_translation")
            blocking_conditions.append("small_batch_existing_translation")
        if not digest_matches:
            entry_blockers.append("small_batch_digest_changed")
            blocking_conditions.append("small_batch_digest_changed")
        if int(current_safe.get("proposed_value_chars") or 0) > 60:
            entry_blockers.append("small_batch_meta_title_over_60_chars")
        if not current_safe.get("digest"):
            entry_blockers.append("small_batch_missing_digest")
        current_safe["blocking_reasons"] = _unique(entry_blockers)
        current_safe["seo_warning"] = (
            "over_ideal_seo_chars"
            if int(current_safe.get("proposed_value_chars") or 0) > 60
            else ""
        )
        if current_safe.get("would_write") and not current_safe["blocking_reasons"]:
            would_write_count += 1
        elif current_safe["blocking_reasons"]:
            blocking_conditions.append("small_batch_candidate_not_ready")
        locked_entries.append(current_safe)
    return {
        "locked_entries": locked_entries,
        "candidate_count": candidate_count,
        "would_write_count": would_write_count,
        "blocking_conditions": _unique(blocking_conditions),
    }


def _current_scan_failed_match(
    locked_report_entries: dict[tuple[str, str], dict], failure_type: str
) -> dict:
    locked_entries = []
    for target in LOCKED_TARGETS:
        locked_entry = locked_report_entries.get((target["locale"], target["field"])) or {}
        locked_entries.append(
            {
                **locked_entry,
                "product_id": locked_entry.get("product_id") or PRODUCT_ID,
                "locale": target["locale"],
                "field": target["field"],
                "would_write": False,
                "blocking_reasons": _unique(
                    list(locked_entry.get("blocking_reasons") or [])
                    + [failure_type, "current_small_batch_preflight_scan_not_performed"]
                ),
                "digest_matches_locked_report": False,
                "current_scan_present": False,
            }
        )
    return {
        "locked_entries": locked_entries,
        "candidate_count": 0,
        "would_write_count": 0,
        "blocking_conditions": [],
    }


def _gate_status(
    locked_report_conditions: list[str], docker_result: dict, match_result: dict
) -> str:
    blockers = match_result.get("blocking_conditions") or []
    if locked_report_conditions:
        return "blocked_locked_dry_run_not_ready"
    if docker_result.get("failure_type"):
        return "blocked_current_small_batch_preflight_scan_failed"
    if "small_batch_target_missing" in blockers:
        return "blocked_small_batch_target_missing"
    if "small_batch_digest_changed" in blockers:
        return "blocked_small_batch_digest_changed"
    if "small_batch_existing_translation" in blockers:
        return "blocked_small_batch_existing_translation"
    if blockers:
        return "blocked_small_batch_target_not_ready"
    if (
        match_result.get("candidate_count") == LOCKED_BATCH_MAX_ENTRIES
        and match_result.get("would_write_count") == LOCKED_BATCH_MAX_ENTRIES
    ):
        return "small_batch_real_write_preflight_ready"
    return "blocked_small_batch_target_not_ready"


def _gate_requirements() -> list[str]:
    return [
        "mode must be real-run or execute-real-write in a future phase.",
        "SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN must be 0 in that future phase.",
        "ACK must exactly equal I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE.",
        f"PRODUCT_ID must exactly equal {PRODUCT_ID}.",
        "SHOPIFY_TRANSLATION_REAL_WRITE_SMALL_BATCH_ONLY must be 1.",
        f"SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES must be {LOCKED_BATCH_MAX_ENTRIES}.",
        "SHOPIFY_TRANSLATION_REAL_WRITE_BATCH_LOCALES must exactly equal fr,es,it.",
        f"SHOPIFY_TRANSLATION_REAL_WRITE_BATCH_FIELD must exactly equal {LOCKED_BATCH_FIELD}.",
        "Locked target count and selected entry count must both be exactly 3.",
        "All fields must be meta_title and locales must be exactly fr/es/it with no extras.",
        "All digest values must match this locked preflight report.",
        "No current or outdated translations may exist before write.",
        "Read-only/manual package must be ready and unblocked.",
        "translationsRegister payload count must be exactly 3.",
        "Post-write readback must verify all 3 entries.",
        "Failure must never trigger automatic rollback.",
    ]


def _abort_conditions() -> list[str]:
    return [
        "DRY_RUN is not 0 in a future real-run phase.",
        "ACK missing or mismatched.",
        "product_id mismatch.",
        "SMALL_BATCH_ONLY is not 1.",
        "MAX_ENTRIES is not 3.",
        "BATCH_LOCALES is not exactly fr,es,it.",
        "BATCH_FIELD is not meta_title.",
        "locked target count is not exactly 3.",
        "selected entries count is not exactly 3.",
        "any target is missing from current eligible entries.",
        "any digest changed from the locked report.",
        "any current translation exists.",
        "any outdated translation exists.",
        "any package blocking condition is present.",
        "translationsRegister payload count is not exactly 3.",
    ]


def _future_real_write_command_preview() -> list[str]:
    return [
        "$env:SHOPIFY_TRANSLATION_REAL_WRITE_ACK=\"I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID=\"{PRODUCT_ID}\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES=\"{LOCKED_BATCH_MAX_ENTRIES}\"",
        "$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN=\"0\"",
        "$env:SHOPIFY_TRANSLATION_REAL_WRITE_SMALL_BATCH_ONLY=\"1\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_BATCH_LOCALES=\"{','.join(LOCKED_BATCH_LOCALES)}\"",
        f"$env:SHOPIFY_TRANSLATION_REAL_WRITE_BATCH_FIELD=\"{LOCKED_BATCH_FIELD}\"",
        "python remote_approval_runner.py --task shopify_translation_small_batch_real_write_execute --mode real-run --approval local",
        "# Preview only in Phase 16.4: future_small_batch_real_write_allowed=False and a separate future phase is required.",
    ]


def _post_write_audit_expected_fields() -> list[str]:
    return [
        "execution_status=small_batch_real_write_succeeded_and_verified",
        "audit_status=small_batch_real_write_audit_passed",
        "translations_register_payload_count=3",
        "write_attempted_count=3",
        "write_succeeded_count=3",
        "verified_count=3",
        "post_write_readback_checked=True",
        "post_write_readback_verified_count=3",
        "post_write_readback_mismatches=[]",
        "rollback_approval_required=False",
        "rollback_performed=False",
        "On failure: execution_status=small_batch_real_write_failed_or_unverified",
        "On failure: audit_status=small_batch_real_write_audit_failed_or_needs_review",
        "On failure: rollback_approval_required=True and rollback_performed=False",
        "Automatic rollback must never run.",
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
            ("Gate Status", "small_batch_real_write_gate_status"),
            ("Manual Next Step Allowed", "manual_small_batch_real_write_allowed_next_step"),
            ("Locked Real Write Ready", "locked_small_batch_real_write_ready"),
            ("Target Product ID", "locked_small_batch_target_product_id"),
            ("Candidate Count", "small_batch_candidate_count"),
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
        f"<td>{escape(str(entry.get('digest_matches_locked_report', '')))}</td>"
        f"<td>{escape(json.dumps(entry.get('blocking_reasons', []), ensure_ascii=False))}</td>"
        "</tr>"
        for entry in payload.get("locked_small_batch_target_entries", [])
    )
    command_rows = "\n".join(
        f"<li><code>{escape(line)}</code></li>"
        for line in payload.get("locked_small_batch_real_write_command_powershell_preview", [])
    )
    requirements = "\n".join(
        f"<li>{escape(item)}</li>"
        for item in payload.get("small_batch_real_write_gate_requirements", [])
    )
    audit_plan = "\n".join(
        f"<li>{escape(item)}</li>"
        for item in payload.get("small_batch_post_write_audit_expected_fields", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Small Batch Real-Write Gate Preflight</title></head>
<body>
  <h1>Small Batch Real-Write Gate Preflight</h1>
  <p>Phase 16.4. This is a dry-run/read-only preflight. It does not write Shopify, call mutations, call translationsRegister, send email, or perform rollback.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Locked Target Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Key</th><th>Digest</th><th>Chars</th><th>Would Write</th><th>Current Translation</th><th>Outdated</th><th>Digest Match</th><th>Blocking Reasons</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Future Real-Write Command Preview</h2>
  <p>This preview remains disabled in Phase 16.4. A separate future phase is required before it can be used.</p>
  <ol>{command_rows}</ol>
  <h2>Gate Requirements</h2>
  <ul>{requirements}</ul>
  <h2>Post-Write Audit Plan</h2>
  <ul>{audit_plan}</ul>
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
        "Phase 16.4 locked small-batch real-write gate preflight generated.\n"
        f"- small_batch_real_write_gate_status: {payload.get('small_batch_real_write_gate_status')}\n"
        f"- manual_small_batch_real_write_allowed_next_step: {payload.get('manual_small_batch_real_write_allowed_next_step')}\n"
        f"- locked_small_batch_real_write_ready: {payload.get('locked_small_batch_real_write_ready')}\n"
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
