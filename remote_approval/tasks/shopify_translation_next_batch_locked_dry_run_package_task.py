import json
import time
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_translation_small_batch_locked_dry_run_package_task import (
    _entry_for_target,
    _read_json,
    _run_current_manual_action_package_in_docker,
    _safe_entry,
    _unique,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_translation_next_batch_locked_dry_run_package"
PHASE = "16.7"
PRODUCT_ID = "gid://shopify/Product/7655686799427"
POST_WRITE_AUDIT_REPORT_PATH = LOG_DIR / "shopify_translation_small_batch_post_write_audit.json"
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_next_batch_locked_dry_run_package.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_next_batch_locked_dry_run_package.html"
LOCKED_TARGETS = [
    {"locale": "it", "field": "meta_description"},
    {"locale": "ja", "field": "title"},
]
LOCKED_MAX_ENTRIES = 2
LOCKED_TARGET_LABEL = "it:meta_description,ja:title"


def run_shopify_translation_next_batch_locked_dry_run_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    audit_report, audit_diag = _read_json(POST_WRITE_AUDIT_REPORT_PATH)
    audit_conditions = _audit_report_blocking_conditions(audit_report, audit_diag)
    docker_result = _run_current_manual_action_package_in_docker()
    payload = _build_payload(
        audit_report=audit_report,
        audit_diag=audit_diag,
        audit_conditions=audit_conditions,
        docker_result=docker_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = (
        payload["next_batch_locked_status"] == "next_batch_locked_dry_run_ready"
        and payload["locked_next_batch_ready"] is True
        and payload["next_batch_candidate_count"] == LOCKED_MAX_ENTRIES
        and payload["would_write_count"] == LOCKED_MAX_ENTRIES
        and payload["future_next_batch_real_write_allowed"] is False
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
        "json_next_batch_locked_dry_run_package_path": str(json_path),
        "html_next_batch_locked_dry_run_package_path": str(html_path),
        "phase": PHASE,
        "next_batch_locked_status": payload["next_batch_locked_status"],
        "locked_next_batch_ready": payload["locked_next_batch_ready"],
        "next_batch_candidate_count": payload["next_batch_candidate_count"],
        "would_write_count": payload["would_write_count"],
        "future_next_batch_real_write_allowed": False,
        "future_next_batch_real_write_needs_next_phase": True,
        "shopify_api_call_performed": payload["shopify_api_call_performed"],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "blocking_conditions": payload["blocking_conditions"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _build_payload(
    audit_report: dict,
    audit_diag: dict,
    audit_conditions: list[str],
    docker_result: dict,
    duration_seconds: float,
) -> dict:
    audit_target_entries = _target_entries_from_audit(audit_report)
    current_entries = list(
        (docker_result.get("manual_action_package") or {}).get("eligible_entries") or []
    )
    if docker_result.get("failure_type"):
        match_result = _current_scan_failed_match(
            audit_target_entries, docker_result["failure_type"]
        )
    else:
        match_result = _match_locked_targets(audit_target_entries, current_entries)

    blocking_conditions = list(audit_conditions)
    if docker_result.get("failure_type"):
        blocking_conditions.append(docker_result["failure_type"])
    blocking_conditions.extend(match_result["blocking_conditions"])
    blocking_conditions = _unique(blocking_conditions)
    locked_status = _locked_status(audit_conditions, docker_result, match_result)
    locked_ready = locked_status == "next_batch_locked_dry_run_ready" and not blocking_conditions

    payload = {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run",
        "dry_run": True,
        "generated_at": utc_now_iso(),
        "duration_seconds": duration_seconds,
        "source_small_batch_post_write_audit_report_path": str(
            POST_WRITE_AUDIT_REPORT_PATH
        ),
        "source_small_batch_post_write_audit_report_exists": bool(
            audit_diag.get("file_exists")
        ),
        "source_small_batch_post_write_audit_report_error": audit_diag.get(
            "error", ""
        ),
        "source_small_batch_completion_status": audit_report.get(
            "small_batch_completion_status", ""
        ),
        "source_readback_audit_status": audit_report.get("readback_audit_status", ""),
        "source_duplicate_write_protection_status": audit_report.get(
            "duplicate_write_protection_status", ""
        ),
        "source_remaining_eligible_count": int(
            audit_report.get("remaining_eligible_count") or 0
        ),
        "source_next_batch_readiness_status": audit_report.get(
            "next_batch_readiness_status", ""
        ),
        "post_write_audit_blocking_conditions": audit_conditions,
        "next_batch_locked_status": locked_status,
        "locked_next_batch_ready": locked_ready,
        "locked_next_batch_target_product_id": PRODUCT_ID,
        "locked_next_batch_target_entries": match_result["locked_entries"],
        "locked_next_batch_max_entries": LOCKED_MAX_ENTRIES,
        "locked_next_batch_entry_count": len(match_result["locked_entries"]),
        "next_batch_candidate_count": match_result["candidate_count"],
        "would_write_count": match_result["would_write_count"],
        "blocking_conditions": blocking_conditions,
        "next_batch_dry_run_command_powershell": _dry_run_command_preview(),
        "future_next_batch_real_write_requirements": [
            "Future phase only; this package never enables real writes.",
            "Must remain scoped to one product and the locked it/meta_description plus ja/title entries.",
            "Must require a separate explicit manual ACK and a new post-write readback audit.",
            "Must call translationsRegister only in a later real-run phase.",
        ],
        "future_next_batch_real_write_allowed": False,
        "future_next_batch_real_write_needs_next_phase": True,
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


def _audit_report_blocking_conditions(report: dict, diag: dict) -> list[str]:
    if not diag.get("file_exists"):
        return ["missing_small_batch_post_write_audit_report"]
    if diag.get("error"):
        return [f"small_batch_post_write_audit_report_{diag['error']}"]
    conditions = []
    expected = {
        "small_batch_completion_status": "small_batch_real_write_completed_and_verified",
        "readback_audit_status": "small_batch_readback_confirmed",
        "duplicate_write_protection_status": "duplicate_write_prevented",
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            conditions.append(f"{key}_not_ready")
    if int(report.get("remaining_eligible_count") or 0) < LOCKED_MAX_ENTRIES:
        conditions.append("remaining_eligible_count_lt_2")
    remaining = report.get("remaining_eligible_entries") or []
    for target in LOCKED_TARGETS:
        if not _entry_for_target(remaining, target["locale"], target["field"]):
            conditions.append(
                f"locked_next_batch_target_missing_from_audit_{target['locale']}_{target['field']}"
            )
    return conditions


def _target_entries_from_audit(report: dict) -> dict[tuple[str, str], dict]:
    remaining = report.get("remaining_eligible_entries") or []
    locked = {}
    for target in LOCKED_TARGETS:
        entry = _entry_for_target(remaining, target["locale"], target["field"]) or {}
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
    audit_entries: dict[tuple[str, str], dict],
    current_entries: list[dict],
) -> dict:
    blocking_conditions = []
    locked_entries = []
    candidate_count = 0
    would_write_count = 0
    for target in LOCKED_TARGETS:
        key = (target["locale"], target["field"])
        audit_entry = audit_entries.get(key) or {}
        current_entry = _entry_for_target(
            current_entries, target["locale"], target["field"]
        )
        if not current_entry:
            item = dict(audit_entry)
            item["blocking_reasons"] = _unique(
                list(item.get("blocking_reasons") or []) + ["next_batch_target_missing"]
            )
            locked_entries.append(item)
            blocking_conditions.append("next_batch_target_missing")
            continue

        item = _safe_entry(current_entry)
        candidate_count += 1
        if item.get("would_write"):
            would_write_count += 1
        reasons = list(item.get("blocking_reasons") or [])
        if not item.get("would_write"):
            reasons.append("next_batch_not_would_write")
        if item.get("current_translation_present") or item.get("current_translation_outdated"):
            reasons.append("next_batch_existing_translation")
            blocking_conditions.append("next_batch_existing_translation")
        if audit_entry.get("digest") and item.get("digest") != audit_entry.get("digest"):
            reasons.append("next_batch_digest_changed")
            blocking_conditions.append("next_batch_digest_changed")
        seo_issue = _seo_blocking_reason(item)
        if seo_issue:
            reasons.append(seo_issue)
            blocking_conditions.append("next_batch_seo_warning")
        if reasons:
            blocking_conditions.extend(reasons)
        item["blocking_reasons"] = _unique(reasons)
        locked_entries.append(item)

    if candidate_count != LOCKED_MAX_ENTRIES:
        blocking_conditions.append("next_batch_candidate_count_not_two")
    if would_write_count != LOCKED_MAX_ENTRIES:
        blocking_conditions.append("next_batch_would_write_count_not_two")
    return {
        "locked_entries": locked_entries,
        "candidate_count": candidate_count,
        "would_write_count": would_write_count,
        "blocking_conditions": _unique(blocking_conditions),
    }


def _current_scan_failed_match(
    audit_entries: dict[tuple[str, str], dict],
    reason: str,
) -> dict:
    locked_entries = []
    for target in LOCKED_TARGETS:
        item = dict(audit_entries.get((target["locale"], target["field"])) or {})
        item["blocking_reasons"] = _unique(
            list(item.get("blocking_reasons") or []) + [reason]
        )
        locked_entries.append(item)
    return {
        "locked_entries": locked_entries,
        "candidate_count": 0,
        "would_write_count": 0,
        "blocking_conditions": [reason],
    }


def _locked_status(
    audit_conditions: list[str],
    docker_result: dict,
    match_result: dict,
) -> str:
    if audit_conditions:
        return "blocked_previous_audit_not_ready"
    if docker_result.get("failure_type"):
        return "blocked_current_next_batch_dry_run_scan_failed"
    conditions = match_result.get("blocking_conditions") or []
    if "next_batch_target_missing" in conditions:
        return "blocked_next_batch_target_missing"
    if "next_batch_digest_changed" in conditions:
        return "blocked_next_batch_digest_changed"
    if "next_batch_existing_translation" in conditions:
        return "blocked_next_batch_existing_translation"
    if "next_batch_seo_warning" in conditions:
        return "blocked_next_batch_seo_warning"
    if conditions:
        return "blocked_next_batch_validation_failed"
    return "next_batch_locked_dry_run_ready"


def _seo_blocking_reason(entry: dict) -> str:
    field = entry.get("field", "")
    chars = int(entry.get("proposed_value_chars") or 0)
    if entry.get("seo_warning"):
        return "next_batch_seo_warning"
    if field == "meta_description" and chars > 160:
        return "next_batch_seo_warning"
    if field == "title" and chars > 60:
        return "next_batch_seo_warning"
    return ""


def _dry_run_command_preview() -> list[str]:
    return [
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID="{PRODUCT_ID}"',
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES="{LOCKED_MAX_ENTRIES}"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN="1"',
        '$env:SHOPIFY_TRANSLATION_NEXT_BATCH_ONLY="1"',
        f'$env:SHOPIFY_TRANSLATION_NEXT_BATCH_TARGETS="{LOCKED_TARGET_LABEL}"',
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
            ("Next Batch Locked Status", "next_batch_locked_status"),
            ("Locked Next Batch Ready", "locked_next_batch_ready"),
            ("Target Product ID", "locked_next_batch_target_product_id"),
            ("Locked Entry Count", "locked_next_batch_entry_count"),
            ("Next Batch Candidate Count", "next_batch_candidate_count"),
            ("Would Write Count", "would_write_count"),
            ("Future Real Write Allowed", "future_next_batch_real_write_allowed"),
            ("Future Real Write Needs Next Phase", "future_next_batch_real_write_needs_next_phase"),
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
        f"<td>{escape(str(entry.get('resource_key', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars', '')))}</td>"
        f"<td>{escape(str(entry.get('would_write', '')))}</td>"
        f"<td>{escape(str(entry.get('current_translation_present', '')))}</td>"
        f"<td>{escape(str(entry.get('current_translation_outdated', '')))}</td>"
        f"<td>{escape(json.dumps(entry.get('blocking_reasons', []), ensure_ascii=False))}</td>"
        f"<td>{escape(str(entry.get('seo_warning', '')))}</td>"
        "</tr>"
        for entry in payload.get("locked_next_batch_target_entries", [])
    )
    command_rows = "\n".join(
        f"<li><code>{escape(line)}</code></li>"
        for line in payload.get("next_batch_dry_run_command_powershell", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Next Batch Locked Dry-Run Package</title></head>
<body>
  <h1>Next Batch Locked Dry-Run Package</h1>
  <p>Phase 16.7. This package locks it/meta_description and ja/title for dry-run review only. It never writes Shopify, calls mutations, calls translationsRegister, sends email, or rolls back.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Locked Target Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Key</th><th>Resource Key</th><th>Digest</th><th>Proposed Value Chars</th><th>Would Write</th><th>Current Translation</th><th>Outdated</th><th>Blocking Reasons</th><th>SEO Warning</th></tr></thead>
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
        "Phase 16.7 next-batch locked dry-run package generated.\n"
        f"- next_batch_locked_status: {payload.get('next_batch_locked_status')}\n"
        f"- locked_next_batch_ready: {payload.get('locked_next_batch_ready')}\n"
        f"- next_batch_candidate_count: {payload.get('next_batch_candidate_count')}\n"
        f"- would_write_count: {payload.get('would_write_count')}\n"
        f"- future_next_batch_real_write_allowed: {payload.get('future_next_batch_real_write_allowed')}\n"
        f"- future_next_batch_real_write_needs_next_phase: {payload.get('future_next_batch_real_write_needs_next_phase')}\n"
        f"- shopify_write_performed: {payload.get('shopify_write_performed')}\n"
        f"- mutation_performed: {payload.get('mutation_performed')}\n"
        f"- translations_register_called: {payload.get('translations_register_called')}\n"
        f"- rollback_performed: {payload.get('rollback_performed')}\n"
        f"- blocking_conditions: {payload.get('blocking_conditions')}\n"
        f"- JSON: {json_path}\n"
        f"- HTML: {html_path}\n\n"
        "Reply 1 to keep the generated report, or 0 to stop. This task is dry-run/read-only and does not write Shopify."
    )
