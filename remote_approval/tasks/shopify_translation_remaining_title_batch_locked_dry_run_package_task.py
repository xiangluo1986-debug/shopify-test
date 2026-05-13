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


TASK_NAME = "shopify_translation_remaining_title_batch_locked_dry_run_package"
PHASE = "17.0"
PRODUCT_ID = "gid://shopify/Product/7655686799427"
SOURCE_AUDIT_REPORT_PATH = LOG_DIR / "shopify_translation_next_batch_post_write_audit.json"
JSON_REPORT_PATH = LOG_DIR / "shopify_translation_remaining_title_batch_locked_dry_run_package.json"
HTML_REPORT_PATH = LOG_DIR / "shopify_translation_remaining_title_batch_locked_dry_run_package.html"
LOCKED_TARGETS = [
    {"locale": "de", "field": "title"},
    {"locale": "fr", "field": "title"},
    {"locale": "es", "field": "title"},
    {"locale": "it", "field": "title"},
]
LOCKED_MAX_ENTRIES = 4
LOCKED_TARGET_LABEL = "de:title,fr:title,es:title,it:title"
TITLE_MAX_CHARS = 60
TITLE_COMPRESSION_FALLBACKS = {
    ("de", "title"): "Querruder-Gabelkopf MOFLY P-51D 690mm RC",
    ("fr", "title"): "Chape liaison aileron MOFLY P-51D 690mm RC",
    ("es", "title"): "Horquilla enlace aleron MOFLY P-51D 690mm RC",
    ("it", "title"): "Forcella comando alettone MOFLY P-51D 690mm RC",
}


def run_shopify_translation_remaining_title_batch_locked_dry_run_package_task(
    mode: str,
) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_report, source_diag = _read_json(SOURCE_AUDIT_REPORT_PATH)
    source_conditions = _source_report_blocking_conditions(source_report, source_diag)
    docker_result = _run_current_manual_action_package_in_docker()
    payload = _build_payload(
        source_report=source_report,
        source_diag=source_diag,
        source_conditions=source_conditions,
        docker_result=docker_result,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    success = (
        payload["remaining_title_batch_locked_status"]
        == "remaining_title_batch_locked_dry_run_ready"
        and payload["locked_remaining_title_batch_ready"] is True
        and payload["remaining_title_candidate_count"] == LOCKED_MAX_ENTRIES
        and payload["would_write_count"] == LOCKED_MAX_ENTRIES
        and payload["locked_remaining_title_planned_values_persisted"] is True
        and payload["future_remaining_title_batch_real_write_allowed"] is False
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
        "json_remaining_title_batch_locked_dry_run_package_path": str(json_path),
        "html_remaining_title_batch_locked_dry_run_package_path": str(html_path),
        "phase": PHASE,
        "remaining_title_batch_locked_status": payload[
            "remaining_title_batch_locked_status"
        ],
        "locked_remaining_title_batch_ready": payload[
            "locked_remaining_title_batch_ready"
        ],
        "remaining_title_candidate_count": payload[
            "remaining_title_candidate_count"
        ],
        "would_write_count": payload["would_write_count"],
        "locked_remaining_title_planned_values_persisted": payload[
            "locked_remaining_title_planned_values_persisted"
        ],
        "future_remaining_title_batch_real_write_allowed": False,
        "future_remaining_title_batch_real_write_needs_next_phase": True,
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
    source_conditions: list[str],
    docker_result: dict,
    duration_seconds: float,
) -> dict:
    source_target_entries = _target_entries_from_source(source_report)
    manual_package = docker_result.get("manual_action_package") or {}
    current_entries = list(manual_package.get("eligible_entries") or [])
    fallback_entries = _draft_fallback_entries_for_targets(
        source_target_entries,
        current_entries,
        manual_package.get("draft_entries") or [],
    )
    current_entries = (
        _title_compression_fallback_entries_for_targets(
            source_target_entries,
            fallback_entries
            + current_entries
            + list(manual_package.get("draft_entries") or []),
        )
        + fallback_entries
        + current_entries
    )
    if docker_result.get("failure_type"):
        match_result = _current_scan_failed_match(
            source_target_entries,
            docker_result["failure_type"],
        )
    else:
        match_result = _match_locked_targets(source_target_entries, current_entries)

    blocking_conditions = list(source_conditions)
    if docker_result.get("failure_type"):
        blocking_conditions.append(docker_result["failure_type"])
    blocking_conditions.extend(match_result["blocking_conditions"])
    blocking_conditions = _unique(blocking_conditions)
    locked_status = _locked_status(source_conditions, docker_result, match_result)
    locked_ready = (
        locked_status == "remaining_title_batch_locked_dry_run_ready"
        and not blocking_conditions
    )
    locked_entries = match_result["locked_entries"]
    planned_values_persisted = all(
        bool(entry.get("planned_value") or entry.get("proposed_translation"))
        for entry in locked_entries
    )

    payload = {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run",
        "dry_run": True,
        "generated_at": utc_now_iso(),
        "duration_seconds": duration_seconds,
        "source_next_batch_post_write_audit_report_path": str(
            SOURCE_AUDIT_REPORT_PATH
        ),
        "source_next_batch_post_write_audit_report_exists": bool(
            source_diag.get("file_exists")
        ),
        "source_next_batch_post_write_audit_report_error": source_diag.get(
            "error", ""
        ),
        "source_next_batch_completion_status": source_report.get(
            "next_batch_completion_status", ""
        ),
        "source_readback_audit_status": source_report.get(
            "readback_audit_status", ""
        ),
        "source_duplicate_write_protection_status": source_report.get(
            "duplicate_write_protection_status", ""
        ),
        "source_remaining_eligible_count": int(
            source_report.get("remaining_eligible_count") or 0
        ),
        "source_blocking_conditions": list(
            source_report.get("blocking_conditions") or []
        ),
        "source_audit_blocking_conditions": source_conditions,
        "remaining_title_batch_locked_status": locked_status,
        "locked_remaining_title_batch_ready": locked_ready,
        "locked_remaining_title_batch_target_product_id": PRODUCT_ID,
        "locked_remaining_title_batch_target_entries": locked_entries,
        "locked_remaining_title_batch_max_entries": LOCKED_MAX_ENTRIES,
        "locked_remaining_title_batch_entry_count": len(locked_entries),
        "locked_remaining_title_planned_values_persisted": planned_values_persisted,
        "locked_remaining_title_planned_value_sources": [
            {
                "locale": entry.get("locale", ""),
                "field": entry.get("field", ""),
                "planned_value_source": entry.get("planned_value_source", ""),
                "planned_value_present": bool(
                    entry.get("planned_value") or entry.get("proposed_translation")
                ),
                "proposed_value_chars": int(entry.get("proposed_value_chars") or 0),
            }
            for entry in locked_entries
        ],
        "remaining_title_candidate_count": match_result["candidate_count"],
        "would_write_count": match_result["would_write_count"],
        "title_lengths": [
            {
                "locale": entry.get("locale", ""),
                "field": entry.get("field", ""),
                "proposed_value_chars": int(entry.get("proposed_value_chars") or 0),
                "within_limit": int(entry.get("proposed_value_chars") or 0)
                <= TITLE_MAX_CHARS,
                "seo_warning": entry.get("seo_warning", ""),
            }
            for entry in locked_entries
        ],
        "blocking_conditions": blocking_conditions,
        "remaining_title_batch_dry_run_command_powershell": _dry_run_command_preview(),
        "remaining_title_batch_real_write_command_powershell_preview": (
            _future_real_write_command_preview()
        ),
        "future_remaining_title_batch_real_write_requirements": [
            "Future phase only; this locked dry-run package cannot execute writes.",
            "Must remain scoped to product gid://shopify/Product/7655686799427.",
            "Must remain scoped to de:title, fr:title, es:title, and it:title only.",
            "Must require MAX_ENTRIES=4 and a separate explicit manual ACK.",
            "Must read back all 4 titles after any future translationsRegister mutation.",
            "Must never auto rollback; failures require a separate rollback approval package.",
        ],
        "future_remaining_title_batch_real_write_allowed": False,
        "future_remaining_title_batch_real_write_needs_next_phase": True,
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
        "manual_action_package_status": manual_package.get("package_status", ""),
        "manual_action_entry_count": manual_package.get("entry_count", 0),
        "manual_action_blocked_entry_count": manual_package.get(
            "blocked_entry_count", 0
        ),
        "manual_action_blocking_conditions": manual_package.get(
            "blocking_conditions", []
        ),
        "docker_stdout_json_parsed": bool(docker_result.get("docker_stdout_json_parsed")),
        "docker_command": docker_result.get("docker_command", ""),
        "docker_return_code": docker_result.get("docker_return_code"),
        "docker_stdout_tail": docker_result.get("docker_stdout_tail", ""),
        "docker_stderr_tail": docker_result.get("docker_stderr_tail", ""),
        "docker_failure_type": docker_result.get("failure_type", ""),
    }
    return payload


def _source_report_blocking_conditions(report: dict, diag: dict) -> list[str]:
    if not diag.get("file_exists"):
        return ["missing_next_batch_post_write_audit_report"]
    if diag.get("error"):
        return [f"next_batch_post_write_audit_report_{diag['error']}"]

    conditions = []
    expected = {
        "next_batch_completion_status": "next_batch_real_write_completed_and_verified",
        "readback_audit_status": "next_batch_readback_confirmed",
        "duplicate_write_protection_status": "duplicate_write_prevented",
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
    }
    for key, expected_value in expected.items():
        if report.get(key) != expected_value:
            conditions.append(f"{key}_not_ready")
    if report.get("blocking_conditions") not in ([], None):
        conditions.append("source_blocking_conditions_not_empty")
    if int(report.get("remaining_eligible_count") or 0) < LOCKED_MAX_ENTRIES:
        conditions.append("remaining_eligible_count_lt_4")

    remaining = report.get("remaining_eligible_entries") or []
    for target in LOCKED_TARGETS:
        entry = _entry_for_target(remaining, target["locale"], target["field"])
        if not entry:
            conditions.append(
                f"remaining_title_target_missing_from_source_{target['locale']}_{target['field']}"
            )
            continue
        entry_conditions = _source_entry_blocking_conditions(entry)
        conditions.extend(
            f"{target['locale']}_{target['field']}_{condition}"
            for condition in entry_conditions
        )
    return _unique(conditions)


def _source_entry_blocking_conditions(entry: dict) -> list[str]:
    conditions = []
    if entry.get("product_id") != PRODUCT_ID:
        conditions.append("product_id_mismatch")
    if entry.get("field") != "title":
        conditions.append("field_mismatch")
    if entry.get("would_write") is not True:
        conditions.append("would_write_not_true")
    if entry.get("current_translation_present") is not False:
        conditions.append("current_translation_present")
    if entry.get("current_translation_outdated") is not False:
        conditions.append("current_translation_outdated")
    if entry.get("blocking_reasons"):
        conditions.append("blocking_reasons_not_empty")
    if entry.get("seo_warning"):
        conditions.append("seo_warning_not_empty")
    if not entry.get("digest"):
        conditions.append("missing_digest")
    if int(entry.get("proposed_value_chars") or 0) > TITLE_MAX_CHARS:
        conditions.append("title_over_60")
    return conditions


def _target_entries_from_source(report: dict) -> dict[tuple[str, str], dict]:
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
                "key": entry.get("key") or target["field"],
                "resource_key": entry.get("resource_key") or target["field"],
                "would_write": bool(entry.get("would_write", True)),
            }
        )
    return locked


def _match_locked_targets(
    source_entries: dict[tuple[str, str], dict],
    current_entries: list[dict],
) -> dict:
    blocking_conditions = []
    locked_entries = []
    candidate_count = 0
    would_write_count = 0
    for target in LOCKED_TARGETS:
        key = (target["locale"], target["field"])
        source_entry = source_entries.get(key) or {}
        current_entry = _target_entry(
            current_entries,
            target["locale"],
            target["field"],
        )
        if not current_entry:
            item = dict(source_entry)
            item["blocking_reasons"] = _unique(
                list(item.get("blocking_reasons") or [])
                + ["remaining_title_target_missing"]
            )
            locked_entries.append(item)
            blocking_conditions.append("remaining_title_target_missing")
            continue

        item = _safe_entry(current_entry)
        candidate_count += 1
        if item.get("would_write"):
            would_write_count += 1
        reasons = list(item.get("blocking_reasons") or [])
        if item.get("product_id") != PRODUCT_ID:
            reasons.append("remaining_title_product_id_mismatch")
            blocking_conditions.append("remaining_title_product_id_mismatch")
        if item.get("field") != "title":
            reasons.append("remaining_title_field_mismatch")
            blocking_conditions.append("remaining_title_field_mismatch")
        if not item.get("would_write"):
            reasons.append("remaining_title_not_would_write")
            blocking_conditions.append("remaining_title_not_would_write")
        if item.get("current_translation_present") or item.get(
            "current_translation_outdated"
        ):
            reasons.append("remaining_title_existing_translation")
            blocking_conditions.append("remaining_title_existing_translation")
        if source_entry.get("digest") and item.get("digest") != source_entry.get("digest"):
            reasons.append("remaining_title_digest_changed")
            blocking_conditions.append("remaining_title_digest_changed")
        if not item.get("digest"):
            reasons.append("remaining_title_missing_digest")
            blocking_conditions.append("remaining_title_missing_digest")
        if not (item.get("planned_value") or item.get("proposed_translation")):
            reasons.append("remaining_title_missing_planned_value")
            blocking_conditions.append("remaining_title_missing_planned_value")
        seo_issue = _seo_blocking_reason(item)
        if seo_issue:
            reasons.append(seo_issue)
            blocking_conditions.append("remaining_title_seo_warning")
        item["blocking_reasons"] = _unique(reasons)
        locked_entries.append(item)

    if candidate_count != LOCKED_MAX_ENTRIES:
        blocking_conditions.append("remaining_title_candidate_count_not_four")
    if would_write_count != LOCKED_MAX_ENTRIES:
        blocking_conditions.append("remaining_title_would_write_count_not_four")
    if any(
        not (entry.get("planned_value") or entry.get("proposed_translation"))
        for entry in locked_entries
    ):
        blocking_conditions.append("remaining_title_locked_entries_missing_planned_values")
    return {
        "locked_entries": locked_entries,
        "candidate_count": candidate_count,
        "would_write_count": would_write_count,
        "blocking_conditions": _unique(blocking_conditions),
    }


def _draft_fallback_entries_for_targets(
    source_entries: dict[tuple[str, str], dict],
    current_entries: list[dict],
    draft_entries: list[dict],
) -> list[dict]:
    fallback_entries = []
    for target in LOCKED_TARGETS:
        current_entry = _target_entry(current_entries, target["locale"], target["field"])
        if current_entry and (
            current_entry.get("planned_value") or current_entry.get("proposed_translation")
        ):
            continue
        source_entry = source_entries.get((target["locale"], target["field"])) or {}
        draft_entry = _target_entry(
            draft_entries,
            target["locale"],
            target["field"],
        )
        if not _source_entry_allows_draft_fallback(source_entry):
            continue
        item = _draft_fallback_entry(source_entry, draft_entry)
        if item:
            fallback_entries.append(item)
    return fallback_entries


def _source_entry_allows_draft_fallback(source_entry: dict) -> bool:
    return bool(
        source_entry
        and source_entry.get("would_write") is True
        and source_entry.get("current_translation_present") is False
        and source_entry.get("current_translation_outdated") is False
        and not source_entry.get("blocking_reasons")
        and not source_entry.get("seo_warning")
        and source_entry.get("digest")
        and int(source_entry.get("proposed_value_chars") or 0) <= TITLE_MAX_CHARS
    )


def _draft_fallback_entry(source_entry: dict, draft_entry: dict) -> dict:
    if not draft_entry:
        return {}
    if not _draft_status_allows_fallback(draft_entry):
        return {}
    planned_value = (
        draft_entry.get("planned_value")
        or draft_entry.get("proposed_translation")
        or draft_entry.get("draft_value")
        or ""
    )
    digest = draft_entry.get("digest") or draft_entry.get("source_digest") or ""
    if not planned_value:
        return {}
    if not digest or digest != source_entry.get("digest"):
        return {}
    if len(planned_value) > TITLE_MAX_CHARS:
        return {}
    draft_present = bool(
        draft_entry.get("current_translation_present")
        or draft_entry.get("existing_translation_present")
    )
    draft_outdated = bool(
        draft_entry.get("current_translation_outdated")
        or draft_entry.get("existing_translation_outdated")
    )
    item = _safe_entry(
        {
            **source_entry,
            **draft_entry,
            "product_id": source_entry.get("product_id") or PRODUCT_ID,
            "locale": source_entry.get("locale", ""),
            "field": "title",
            "key": source_entry.get("key") or "title",
            "resource_key": source_entry.get("resource_key") or "title",
            "digest": digest,
            "planned_value": planned_value,
            "proposed_translation": planned_value,
            "planned_value_source": "draft_package_fallback",
            "proposed_value_chars": len(planned_value),
            "would_write": True,
            "current_translation_present": draft_present,
            "current_translation_outdated": draft_outdated,
            "blocking_reasons": [],
            "seo_warning": "",
        }
    )
    if item.get("current_translation_present") or item.get("current_translation_outdated"):
        return {}
    if _seo_blocking_reason(item):
        return {}
    item["planned_value_source"] = "draft_package_fallback"
    item["draft_validation_status"] = draft_entry.get("draft_validation_status", "")
    item["draft_seo_validation_status"] = draft_entry.get("draft_seo_validation_status", "")
    item["draft_eligible_for_apply_plan"] = bool(
        draft_entry.get("draft_eligible_for_apply_plan")
    )
    item["draft_seo_eligible_for_apply_plan"] = bool(
        draft_entry.get("draft_seo_eligible_for_apply_plan")
    )
    return item


def _title_compression_fallback_entries_for_targets(
    source_entries: dict[tuple[str, str], dict],
    current_entries: list[dict],
) -> list[dict]:
    fallback_entries = []
    for target in LOCKED_TARGETS:
        key = (target["locale"], target["field"])
        if key not in TITLE_COMPRESSION_FALLBACKS:
            continue
        source_entry = source_entries.get(key) or {}
        current_entry = _target_entry(current_entries, target["locale"], target["field"])
        item = _title_compression_fallback_entry(source_entry, current_entry)
        if item:
            fallback_entries.append(item)
    return fallback_entries


def _title_compression_fallback_entry(source_entry: dict, current_entry: dict) -> dict:
    if not current_entry or not _source_entry_allows_draft_fallback(source_entry):
        return {}
    if _has_draft_status(current_entry) and not _draft_status_allows_compression_fallback(
        current_entry
    ):
        return {}
    safe_current = _normalized_title_candidate(source_entry, current_entry)
    if safe_current.get("product_id") != PRODUCT_ID:
        return {}
    if safe_current.get("field") != "title":
        return {}
    if safe_current.get("would_write") is not True:
        return {}
    if safe_current.get("current_translation_present") or safe_current.get(
        "current_translation_outdated"
    ):
        return {}
    if int(safe_current.get("proposed_value_chars") or 0) <= TITLE_MAX_CHARS:
        return {}
    blockers = [
        reason
        for reason in list(safe_current.get("blocking_reasons") or [])
        if reason
        not in {
            "remaining_title_title_over_60",
            "remaining_title_seo_warning",
            "title_over_60",
        }
    ]
    if blockers:
        return {}
    if safe_current.get("digest") != source_entry.get("digest"):
        return {}
    compressed_value = TITLE_COMPRESSION_FALLBACKS.get(
        (safe_current.get("locale", ""), safe_current.get("field", ""))
    )
    if not compressed_value or len(compressed_value) > TITLE_MAX_CHARS:
        return {}
    item = _safe_entry(
        {
            **safe_current,
            "planned_value": compressed_value,
            "proposed_translation": compressed_value,
            "planned_value_source": "title_compression_fallback",
            "proposed_value_chars": len(compressed_value),
            "blocking_reasons": [],
            "seo_warning": "",
        }
    )
    if _seo_blocking_reason(item):
        return {}
    item["planned_value_source"] = "title_compression_fallback"
    item["compressed_from_value_chars"] = int(
        safe_current.get("proposed_value_chars") or 0
    )
    item["compression_reason"] = "title_over_60"
    return item


def _normalized_title_candidate(source_entry: dict, entry: dict) -> dict:
    field = (
        entry.get("field")
        or entry.get("source_key")
        or entry.get("key")
        or entry.get("planned_key")
        or "title"
    )
    locale = (
        entry.get("locale")
        or entry.get("target_locale")
        or entry.get("planned_locale")
        or source_entry.get("locale")
        or ""
    )
    planned_value = (
        entry.get("planned_value")
        or entry.get("proposed_translation")
        or entry.get("draft_value")
        or ""
    )
    digest = entry.get("digest") or entry.get("source_digest") or source_entry.get("digest") or ""
    current_present = bool(
        entry.get("current_translation_present")
        or entry.get("existing_translation_present")
    )
    current_outdated = bool(
        entry.get("current_translation_outdated")
        or entry.get("existing_translation_outdated")
    )
    return {
        "product_id": entry.get("product_id", "") or source_entry.get("product_id") or PRODUCT_ID,
        "locale": locale,
        "field": field,
        "key": entry.get("key") or entry.get("resource_key") or field,
        "resource_key": entry.get("resource_key") or entry.get("key") or field,
        "digest": digest,
        "planned_value": planned_value,
        "proposed_translation": planned_value,
        "planned_value_source": entry.get("planned_value_source", ""),
        "proposed_value_chars": int(
            entry.get("proposed_value_chars")
            or entry.get("draft_value_chars")
            or len(planned_value)
        ),
        "would_write": bool(entry.get("would_write", bool(planned_value))),
        "current_translation_present": current_present,
        "current_translation_outdated": current_outdated,
        "blocking_reasons": list(entry.get("blocking_reasons") or []),
        "seo_warning": entry.get("seo_warning", ""),
        "draft_validation_status": entry.get("draft_validation_status")
        or entry.get("validation_status", ""),
        "draft_seo_validation_status": entry.get("draft_seo_validation_status")
        or entry.get("seo_validation_status", ""),
    }


def _has_draft_status(entry: dict) -> bool:
    return bool(
        entry.get("draft_validation_status")
        or entry.get("validation_status")
        or entry.get("draft_seo_validation_status")
        or entry.get("seo_validation_status")
    )


def _draft_status_allows_compression_fallback(draft_entry: dict) -> bool:
    validation_status = (
        draft_entry.get("draft_validation_status")
        or draft_entry.get("validation_status")
        or ""
    )
    seo_status = (
        draft_entry.get("draft_seo_validation_status")
        or draft_entry.get("seo_validation_status")
        or ""
    )
    return bool(
        validation_status
        in {
            "draft_ready_for_manual_review",
            "ready_for_manual_review",
            "manual_review_ready",
            "draft_needs_manual_review",
        }
        and seo_status == "seo_ready"
    )


def _draft_status_allows_fallback(draft_entry: dict) -> bool:
    validation_status = (
        draft_entry.get("draft_validation_status")
        or draft_entry.get("validation_status")
        or ""
    )
    seo_status = (
        draft_entry.get("draft_seo_validation_status")
        or draft_entry.get("seo_validation_status")
        or ""
    )
    return bool(
        validation_status
        in {
            "draft_ready_for_manual_review",
            "ready_for_manual_review",
            "manual_review_ready",
        }
        and seo_status == "seo_ready"
    )


def _target_entry(entries: list[dict], locale: str, field: str) -> dict:
    for entry in entries:
        entry_locale = (
            entry.get("locale")
            or entry.get("target_locale")
            or entry.get("planned_locale")
            or ""
        )
        entry_field = (
            entry.get("field")
            or entry.get("source_key")
            or entry.get("key")
            or entry.get("planned_key")
            or entry.get("resource_key")
            or ""
        )
        if entry_locale == locale and entry_field == field:
            return entry
    return {}


def _current_scan_failed_match(
    source_entries: dict[tuple[str, str], dict],
    reason: str,
) -> dict:
    locked_entries = []
    for target in LOCKED_TARGETS:
        item = dict(source_entries.get((target["locale"], target["field"])) or {})
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
    source_conditions: list[str],
    docker_result: dict,
    match_result: dict,
) -> str:
    if source_conditions:
        return "blocked_next_batch_post_write_audit_not_ready"
    if docker_result.get("failure_type"):
        return "blocked_current_remaining_title_batch_scan_failed"
    conditions = match_result.get("blocking_conditions") or []
    if "remaining_title_target_missing" in conditions:
        return "blocked_remaining_title_target_missing"
    if "remaining_title_digest_changed" in conditions:
        return "blocked_remaining_title_digest_changed"
    if "remaining_title_existing_translation" in conditions:
        return "blocked_remaining_title_existing_translation"
    if "remaining_title_seo_warning" in conditions:
        return "blocked_remaining_title_seo_warning"
    if "remaining_title_missing_planned_value" in conditions:
        return "blocked_remaining_title_missing_planned_value"
    if conditions:
        return "blocked_remaining_title_validation_failed"
    return "remaining_title_batch_locked_dry_run_ready"


def _seo_blocking_reason(entry: dict) -> str:
    field = entry.get("field", "")
    chars = int(entry.get("proposed_value_chars") or 0)
    if entry.get("seo_warning"):
        return "remaining_title_seo_warning"
    if field != "title":
        return "remaining_title_field_mismatch"
    if chars > TITLE_MAX_CHARS:
        return "remaining_title_title_over_60"
    return ""


def _dry_run_command_preview() -> list[str]:
    return [
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID="{PRODUCT_ID}"',
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES="{LOCKED_MAX_ENTRIES}"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN="1"',
        '$env:SHOPIFY_TRANSLATION_REMAINING_TITLE_BATCH_ONLY="1"',
        f'$env:SHOPIFY_TRANSLATION_REMAINING_TITLE_BATCH_TARGETS="{LOCKED_TARGET_LABEL}"',
        f"python remote_approval_runner.py --task {TASK_NAME} --approval local",
    ]


def _future_real_write_command_preview() -> list[str]:
    return [
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_ACK="I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE"',
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID="{PRODUCT_ID}"',
        f'$env:SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES="{LOCKED_MAX_ENTRIES}"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN="0"',
        '$env:SHOPIFY_TRANSLATION_REMAINING_TITLE_BATCH_ONLY="1"',
        f'$env:SHOPIFY_TRANSLATION_REMAINING_TITLE_BATCH_TARGETS="{LOCKED_TARGET_LABEL}"',
        "python remote_approval_runner.py --task shopify_translation_remaining_title_batch_real_write_execute --mode real-run --approval local",
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
            ("Locked Status", "remaining_title_batch_locked_status"),
            ("Locked Ready", "locked_remaining_title_batch_ready"),
            ("Target Product ID", "locked_remaining_title_batch_target_product_id"),
            ("Locked Entry Count", "locked_remaining_title_batch_entry_count"),
            ("Planned Values Persisted", "locked_remaining_title_planned_values_persisted"),
            ("Candidate Count", "remaining_title_candidate_count"),
            ("Would Write Count", "would_write_count"),
            ("Future Real Write Allowed", "future_remaining_title_batch_real_write_allowed"),
            (
                "Future Real Write Needs Next Phase",
                "future_remaining_title_batch_real_write_needs_next_phase",
            ),
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
        f"<td>{escape(str(entry.get('planned_value', '') or entry.get('proposed_translation', '')))}</td>"
        f"<td>{escape(str(entry.get('planned_value_source', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value_chars', '')))}</td>"
        f"<td>{escape(str(entry.get('would_write', '')))}</td>"
        f"<td>{escape(str(entry.get('current_translation_present', '')))}</td>"
        f"<td>{escape(str(entry.get('current_translation_outdated', '')))}</td>"
        f"<td>{escape(json.dumps(entry.get('blocking_reasons', []), ensure_ascii=False))}</td>"
        f"<td>{escape(str(entry.get('seo_warning', '')))}</td>"
        "</tr>"
        for entry in payload.get("locked_remaining_title_batch_target_entries", [])
    )
    dry_run_rows = "\n".join(
        f"<li><code>{escape(line)}</code></li>"
        for line in payload.get("remaining_title_batch_dry_run_command_powershell", [])
    )
    future_rows = "\n".join(
        f"<li><code>{escape(line)}</code></li>"
        for line in payload.get(
            "remaining_title_batch_real_write_command_powershell_preview", []
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Remaining Title Batch Locked Dry-Run Package</title></head>
<body>
  <h1>Remaining Title Batch Locked Dry-Run Package</h1>
  <p>Phase 17.0. This package locks de/fr/es/it title translations for dry-run review only. It never writes Shopify, calls mutations, calls translationsRegister, sends email, or rolls back.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Locked Target Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Key</th><th>Resource Key</th><th>Digest</th><th>Planned Value</th><th>Planned Value Source</th><th>Chars</th><th>Would Write</th><th>Current Translation</th><th>Outdated</th><th>Blocking Reasons</th><th>SEO Warning</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Dry-Run Command Preview</h2>
  <ol>{dry_run_rows}</ol>
  <h2>Future Real-Write Command Preview</h2>
  <p>This preview is not enabled in Phase 17.0. A separate future phase must implement and approve execution.</p>
  <ol>{future_rows}</ol>
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
        "Phase 17.0 remaining-title locked dry-run package generated.\n"
        f"- remaining_title_batch_locked_status: {payload.get('remaining_title_batch_locked_status')}\n"
        f"- locked_remaining_title_batch_ready: {payload.get('locked_remaining_title_batch_ready')}\n"
        f"- locked_remaining_title_planned_values_persisted: {payload.get('locked_remaining_title_planned_values_persisted')}\n"
        f"- remaining_title_candidate_count: {payload.get('remaining_title_candidate_count')}\n"
        f"- would_write_count: {payload.get('would_write_count')}\n"
        f"- future_remaining_title_batch_real_write_allowed: {payload.get('future_remaining_title_batch_real_write_allowed')}\n"
        f"- future_remaining_title_batch_real_write_needs_next_phase: {payload.get('future_remaining_title_batch_real_write_needs_next_phase')}\n"
        f"- title_lengths: {payload.get('title_lengths')}\n"
        f"- shopify_write_performed: {payload.get('shopify_write_performed')}\n"
        f"- mutation_performed: {payload.get('mutation_performed')}\n"
        f"- translations_register_called: {payload.get('translations_register_called')}\n"
        f"- rollback_performed: {payload.get('rollback_performed')}\n"
        f"- blocking_conditions: {payload.get('blocking_conditions')}\n"
        f"- JSON: {json_path}\n"
        f"- HTML: {html_path}\n\n"
        "Reply 1 to keep the generated report, or 0 to stop. This task is dry-run/read-only and does not write Shopify."
    )
