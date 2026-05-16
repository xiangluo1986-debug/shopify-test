import json
import hashlib
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import requests

from .translation_console import SHOPIFY_API_VERSION


APPLY_PLAN_JSON_PATH = Path("logs/shopify_translation_selected_product_apply_plan_package.json")
APPLY_PLAN_HTML_PATH = Path("logs/shopify_translation_selected_product_apply_plan_package.html")
SAFE_WRITE_READINESS_REPORT_DIR = Path("logs/shopify_translation_write_readiness")
LOCKED_EXECUTION_REPORT_DIR = Path("logs/shopify_translation_locked_execution")
REAL_WRITE_REPORT_DIR = Path("logs/shopify_translation_real_write")
READY_DRAFT_STATUS = "selected_product_missing_translation_draft_ready_for_manual_review"
TRANSLATE_ALL_READY_DRAFT_STATUS = "selected_product_all_content_translation_draft_ready_for_manual_review"
READY_DRAFT_STATUSES = {READY_DRAFT_STATUS, TRANSLATE_ALL_READY_DRAFT_STATUS}
SAFE_WRITE_READINESS_ACTION_NAME = "prepare_translation_safe_write_readiness_package"
LOCKED_EXECUTION_ACTION_NAME = "prepare_translation_locked_execution_shell"
REAL_WRITE_ACTION_NAME = "execute_translation_single_locked_write"
LOCKED_EXECUTION_ACK_PHRASE = "I UNDERSTAND THIS WILL WRITE ONE SHOPIFY TRANSLATION"
LOCKED_EXECUTION_READY_STATUS = "locked_execution_ready_for_manual_ack"
LOCKED_EXECUTION_BLOCKED_STATUS = "locked_execution_blocked"
REAL_WRITE_BLOCKED_STATUS = "write_blocked"
REAL_WRITE_MUTATION_FAILED_STATUS = "write_mutation_failed"
REAL_WRITE_AUDIT_PASSED_STATUS = "write_audit_passed"
REAL_WRITE_AUDIT_FAILED_STATUS = "write_audit_failed"
SAFE_WRITE_READINESS_MAX_ENTRY_COUNT = 3
SAFE_WRITE_READINESS_FIELDS = ("title", "meta_title", "meta_description")
SAFE_WRITE_READINESS_FIELD_SET = set(SAFE_WRITE_READINESS_FIELDS)
LOCKED_EXECUTION_ALLOWED_FIELDS = SAFE_WRITE_READINESS_FIELDS
LOCKED_EXECUTION_ALLOWED_FIELD_SET = set(LOCKED_EXECUTION_ALLOWED_FIELDS)
LOCKED_EXECUTION_SUPPORTED_LOCALES = {"de", "es", "fr", "it", "ja"}
LOCKED_EXECUTION_EXCLUDED_SCOPE_GROUPS = (
    "body_html",
    "options",
    "variants",
    "metafields",
    "important_metafields",
    "media",
    "media_alt_text",
    "technical_fields",
    "technical_metafields",
)
LOCKED_EXECUTION_FORBIDDEN_PHRASES = (
    "buy now",
    "order now",
    "shop now",
    "worldwide shipping",
    "ships worldwide",
    "free shipping",
    "made in china",
    "china origin",
    "mainland china",
    "shipped from china",
    "ships from china",
    "factory direct",
)
SAFE_WRITE_READINESS_GROUPS = ("product_basics", "seo")
SAFE_WRITE_READINESS_GROUP_SET = set(SAFE_WRITE_READINESS_GROUPS)
SAFE_WRITE_READINESS_READY_JOB_STATUSES = {"completed", "partial"}
SAFE_WRITE_MAPPING_REQUIRED_GROUPS = {
    "options",
    "variants",
    "important_metafields",
    "media",
    "media_alt_text",
}
SAFE_WRITE_TECHNICAL_GROUPS = {"technical_fields", "technical_metafields"}
SAFE_WRITE_SAFETY_FLAGS = {
    "shopify_read_only": True,
    "shopify_write_performed": False,
    "mutation_performed": False,
    "translations_register_called": False,
    "publish_performed": False,
    "apply_performed": False,
    "rollback_performed": False,
    "no_new_shopify_writes_performed": True,
}


def build_translation_workspace_safe_write_readiness_state(
    background_report: dict | None,
    *,
    selected_product_gid: str = "",
    selected_locale: str = "",
):
    report = dict(background_report or {})
    product_gid = str(selected_product_gid or report.get("product_gid") or "").strip()
    report_product_gid = str(report.get("product_gid") or "").strip()
    report_detail_summary = report.get("report_detail_summary") or {}
    locale = str(selected_locale or "").strip()
    rows = [
        _safe_write_entry_from_row(row, product_gid=product_gid)
        for row in (report.get("review_rows") or [])
        if isinstance(row, dict)
    ]
    locale_options = _safe_write_locale_options(rows, locale)
    locale_rows = [row for row in rows if row.get("locale") == locale] if locale else []
    eligible_entries = [row for row in locale_rows if row.get("selectable")]
    blocked_entries = [row for row in locale_rows if not row.get("selectable")]
    blocking_conditions = _safe_write_state_blocking_conditions(
        report=report,
        product_gid=product_gid,
        report_product_gid=report_product_gid,
        locale=locale,
        locale_rows=locale_rows,
        eligible_entries=eligible_entries,
    )
    state = {
        "package_status": "write_readiness_not_prepared",
        "report_exists": bool(report.get("exists") or report.get("job_id")),
        "report_status": report.get("status", ""),
        "report_status_label": report.get("status_label") or report.get("status", ""),
        "report_path": report.get("report_path", ""),
        "product_gid": product_gid,
        "report_product_gid": report_product_gid,
        "product_title": report.get("product_title")
        or report_detail_summary.get("product_title", ""),
        "locale": locale,
        "locale_options": locale_options,
        "eligible_entries": eligible_entries,
        "blocked_entries": blocked_entries,
        "eligible_entries_count": len(eligible_entries),
        "blocked_entries_count": len(blocked_entries),
        "selected_entry_count": 0,
        "max_entry_count": SAFE_WRITE_READINESS_MAX_ENTRY_COUNT,
        "json_report_path": "",
        "html_report_path": "",
        "blocked_entries_summary": _safe_write_blocked_entries_summary(blocked_entries),
        "blocking_conditions": blocking_conditions,
        "can_prepare": not blocking_conditions and bool(eligible_entries),
        "eligible_fields": list(SAFE_WRITE_READINESS_FIELDS),
        "safe_scope_note": (
            "This package does not write Shopify. It only prepares a locked review for future ACK."
        ),
        **SAFE_WRITE_SAFETY_FLAGS,
    }
    return state


def build_translation_workspace_safe_write_readiness_package(
    background_report: dict | None,
    *,
    selected_product_gid: str = "",
    selected_locale: str = "",
    selected_entry_ids=None,
    write_reports: bool = True,
):
    selected_entry_ids = [
        str(entry_id or "").strip()
        for entry_id in (selected_entry_ids or [])
        if str(entry_id or "").strip()
    ]
    state = build_translation_workspace_safe_write_readiness_state(
        background_report,
        selected_product_gid=selected_product_gid,
        selected_locale=selected_locale,
    )
    blocking_conditions = list(state.get("blocking_conditions") or [])
    if not selected_entry_ids:
        blocking_conditions.append("blocked_no_entries_selected")
    if len(selected_entry_ids) > SAFE_WRITE_READINESS_MAX_ENTRY_COUNT:
        blocking_conditions.append("blocked_selected_entry_count_exceeds_3")

    eligible_by_id = {
        entry.get("entry_id"): entry
        for entry in state.get("eligible_entries") or []
        if entry.get("entry_id")
    }
    unknown_entry_ids = [
        entry_id for entry_id in selected_entry_ids if entry_id not in eligible_by_id
    ]
    if unknown_entry_ids:
        blocking_conditions.append("blocked_selected_entries_not_eligible")

    if len(selected_entry_ids) > SAFE_WRITE_READINESS_MAX_ENTRY_COUNT:
        selected_entries = []
    else:
        selected_entries = [
            _safe_write_package_entry(eligible_by_id[entry_id])
            for entry_id in selected_entry_ids
            if entry_id in eligible_by_id
        ]

    if not selected_entries and "blocked_no_entries_selected" not in blocking_conditions:
        blocking_conditions.append("blocked_no_eligible_selected_entries")

    blocking_conditions = _unique_strings(blocking_conditions)
    package_status = (
        "write_readiness_ready"
        if selected_entries and not blocking_conditions
        else "write_readiness_blocked"
    )
    generated_at = _utc_now()
    json_path, html_path = _safe_write_readiness_report_paths(
        state.get("product_gid", ""),
        state.get("locale", ""),
        generated_at,
    )
    payload = {
        "package_status": package_status,
        "generated_at": generated_at,
        "product_gid": state.get("product_gid", ""),
        "product_title": state.get("product_title", ""),
        "locale": state.get("locale", ""),
        "selected_entry_count": len(selected_entries),
        "max_entry_count": SAFE_WRITE_READINESS_MAX_ENTRY_COUNT,
        "selected_entries": selected_entries,
        "eligible_entries_count": state.get("eligible_entries_count", 0),
        "blocked_entries_count": state.get("blocked_entries_count", 0),
        "blocked_entries_summary": state.get("blocked_entries_summary", []),
        "blocking_conditions": blocking_conditions,
        "source_background_report_path": state.get("report_path", ""),
        "json_report_path": json_path.as_posix(),
        "html_report_path": html_path.as_posix(),
        "safe_scope_note": state.get("safe_scope_note", ""),
        **SAFE_WRITE_SAFETY_FLAGS,
    }
    if write_reports:
        _write_safe_write_readiness_reports(payload, json_path, html_path)
    return payload


def build_translation_workspace_locked_execution_package(
    safe_write_readiness_package: dict | None,
    *,
    latest_background_report: dict | None = None,
    selected_product_gid: str = "",
    selected_locale: str = "",
    selected_entry_ids=None,
    ack_preview_text: str = "",
    write_reports: bool = True,
):
    readiness_package = dict(safe_write_readiness_package or {})
    selected_entry_ids = [
        str(entry_id or "").strip()
        for entry_id in (selected_entry_ids or [])
        if str(entry_id or "").strip()
    ]
    selected_entries = [
        dict(entry)
        for entry in (readiness_package.get("selected_entries") or [])
        if isinstance(entry, dict)
    ]
    product_gid = str(
        selected_product_gid or readiness_package.get("product_gid") or ""
    ).strip()
    locale = str(selected_locale or readiness_package.get("locale") or "").strip()
    generated_at = _utc_now()
    json_path, html_path = _locked_execution_report_paths(
        product_gid,
        locale,
        generated_at,
    )

    selected_entry = selected_entries[0] if len(selected_entries) == 1 else {}
    risk_checks, blocking_conditions = _locked_execution_risk_checks(
        readiness_package=readiness_package,
        latest_background_report=latest_background_report or {},
        product_gid=product_gid,
        locale=locale,
        selected_entry_ids=selected_entry_ids,
        selected_entries=selected_entries,
        selected_entry=selected_entry,
    )
    locked_entry = (
        _locked_execution_entry_snapshot(selected_entry, product_gid=product_gid, locale=locale)
        if selected_entry
        else {}
    )
    package_status = (
        LOCKED_EXECUTION_READY_STATUS
        if locked_entry and not blocking_conditions
        else LOCKED_EXECUTION_BLOCKED_STATUS
    )
    dangerous_ack_present = bool(str(ack_preview_text or "").strip())
    payload = {
        "package_status": package_status,
        "generated_at": generated_at,
        "locked_execution_package_only": True,
        "locked_preparation_only": True,
        "locked_execution_locked": True,
        "product_gid": product_gid,
        "product_title": readiness_package.get("product_title", ""),
        "locale": locale,
        "selected_entry_count": len(selected_entries),
        "requested_selected_entry_count": len(selected_entry_ids),
        "selected_entry": locked_entry,
        "selected_entries": [locked_entry] if locked_entry else [],
        "resource_id": locked_entry.get("resource_id", ""),
        "key": locked_entry.get("key", ""),
        "digest": locked_entry.get("digest", ""),
        "source_value": locked_entry.get("source_value", ""),
        "existing_translation_value": locked_entry.get(
            "existing_translation_value", ""
        ),
        "existing_translation_outdated": locked_entry.get(
            "existing_translation_outdated"
        ),
        "proposed_translation_value": locked_entry.get(
            "proposed_translation_value", ""
        ),
        "locked_entry_hash": locked_entry.get("locked_entry_hash", ""),
        "locked_entry_checksum": locked_entry.get("locked_entry_checksum", ""),
        "risk_checks": risk_checks,
        "blocking_conditions": _unique_strings(blocking_conditions),
        "allowed_fields": list(LOCKED_EXECUTION_ALLOWED_FIELDS),
        "blocked_fields": [
            "body_html",
            "options",
            "variants",
            "metafields",
            "media_alt_text",
            "technical_fields",
        ],
        "blocked_scope_groups": list(LOCKED_EXECUTION_EXCLUDED_SCOPE_GROUPS),
        "manual_ack_phrase_required": LOCKED_EXECUTION_ACK_PHRASE,
        "manual_ack_phrase_shown": True,
        "manual_ack_can_be_copied": True,
        "manual_ack_preview_entered": dangerous_ack_present,
        "manual_ack_preview_value_recorded": False,
        "manual_ack_effective": False,
        "manual_ack_required_for_future_write": True,
        "future_write_requires_separate_phase": True,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "source_safe_write_readiness_status": readiness_package.get(
            "package_status", ""
        ),
        "source_safe_write_readiness_json_report_path": readiness_package.get(
            "json_report_path", ""
        ),
        "source_safe_write_readiness_html_report_path": readiness_package.get(
            "html_report_path", ""
        ),
        "source_background_report_path": readiness_package.get(
            "source_background_report_path", ""
        ),
        "latest_background_report_path": str(
            (latest_background_report or {}).get("report_path") or ""
        ),
        "json_report_path": json_path.as_posix(),
        "html_report_path": html_path.as_posix(),
        "shopify_api_call_performed": False,
        "all_new_actions_no_write_confirmed": True,
        **SAFE_WRITE_SAFETY_FLAGS,
    }
    payload["safety_summary"] = {
        "locked_execution_package_only": True,
        "locked_preparation_only": True,
        "locked_execution_locked": True,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "manual_ack_effective": False,
        "manual_ack_required_for_future_write": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }
    if write_reports:
        _write_locked_execution_reports(payload, json_path, html_path)
    return payload


def load_translation_workspace_locked_execution_package(locked_package_path: str):
    path_text = str(locked_package_path or "").strip()
    if not path_text:
        return {}, ["blocked_locked_package_path_missing"], ""

    raw_path = Path(path_text)
    candidate_path = raw_path if raw_path.is_absolute() else Path.cwd() / raw_path
    try:
        resolved_path = candidate_path.resolve()
        allowed_root = (Path.cwd() / LOCKED_EXECUTION_REPORT_DIR).resolve()
    except OSError:
        return {}, ["blocked_locked_package_path_invalid"], path_text

    if allowed_root != resolved_path and allowed_root not in resolved_path.parents:
        return {}, ["blocked_locked_package_path_not_allowed"], resolved_path.as_posix()
    if resolved_path.suffix.lower() != ".json":
        return {}, ["blocked_locked_package_path_not_json"], resolved_path.as_posix()
    if not resolved_path.name.startswith("translation_locked_execution_"):
        return {}, ["blocked_locked_package_filename_not_allowed"], resolved_path.as_posix()
    if not resolved_path.exists():
        return {}, ["blocked_locked_package_file_missing"], resolved_path.as_posix()

    try:
        payload = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}, ["blocked_locked_package_json_invalid"], resolved_path.as_posix()
    if not isinstance(payload, dict):
        return {}, ["blocked_locked_package_json_not_object"], resolved_path.as_posix()
    return payload, [], resolved_path.as_posix()


def execute_translation_workspace_single_locked_write(
    locked_execution_package: dict | None,
    *,
    installation=None,
    locked_package_path: str = "",
    selected_entry_id: str = "",
    selected_entry_checksum: str = "",
    manual_ack_text: str = "",
    load_blocking_conditions=None,
    write_reports: bool = True,
):
    locked_execution_package = dict(locked_execution_package or {})
    load_blocking_conditions = list(load_blocking_conditions or [])
    selected_entry_id = str(selected_entry_id or "").strip()
    selected_entry_checksum = str(selected_entry_checksum or "").strip()
    manual_ack_text = str(manual_ack_text or "")
    entry = _real_write_package_entry(locked_execution_package)
    product_gid = str(locked_execution_package.get("product_gid") or "").strip()
    locale = str(locked_execution_package.get("locale") or "").strip()
    key = str(entry.get("key") or locked_execution_package.get("key") or "").strip()
    resource_id = str(
        entry.get("resource_id") or locked_execution_package.get("resource_id") or ""
    ).strip()
    digest = str(entry.get("digest") or locked_execution_package.get("digest") or "").strip()
    source_value = str(
        entry.get("source_value") or locked_execution_package.get("source_value") or ""
    )
    previous_translation_value = str(
        entry.get("existing_translation_value")
        or locked_execution_package.get("existing_translation_value")
        or ""
    )
    proposed_translation_value = str(
        entry.get("proposed_translation_value")
        or locked_execution_package.get("proposed_translation_value")
        or ""
    )
    generated_at = _utc_now()
    json_path, html_path = _real_write_report_paths(product_gid, locale, generated_at)
    ack_matched = manual_ack_text == LOCKED_EXECUTION_ACK_PHRASE
    expected_checksum = str(
        entry.get("locked_entry_checksum")
        or entry.get("locked_entry_hash")
        or locked_execution_package.get("locked_entry_checksum")
        or locked_execution_package.get("locked_entry_hash")
        or ""
    ).strip()
    payload = {
        "action": REAL_WRITE_ACTION_NAME,
        "execution_status": "",
        "generated_at": generated_at,
        "locked_package_path": str(locked_package_path or ""),
        "product_gid": product_gid,
        "locale": locale,
        "key": key,
        "resource_id": resource_id,
        "digest": digest,
        "source_value": source_value,
        "previous_translation_value": previous_translation_value,
        "previous_translation_existed": bool(previous_translation_value.strip()),
        "proposed_translation_value": proposed_translation_value,
        "selected_entry_id": selected_entry_id,
        "selected_entry_checksum": selected_entry_checksum,
        "expected_entry_id": str(entry.get("entry_id") or "").strip(),
        "expected_entry_checksum": expected_checksum,
        "selected_entry_count": _real_write_int(
            locked_execution_package.get("selected_entry_count")
        ),
        "selected_entries_count": len(
            locked_execution_package.get("selected_entries") or []
        ),
        "locked_package_status": locked_execution_package.get("package_status", ""),
        "source_package_real_write_allowed": locked_execution_package.get(
            "real_write_allowed"
        ),
        "executor_validated_locked_real_write_override": False,
        "allowed_fields": list(LOCKED_EXECUTION_ALLOWED_FIELDS),
        "blocked_fields": [
            "body_html",
            "options",
            "variants",
            "metafields",
            "media_alt_text",
            "technical_fields",
        ],
        "blocked_scope_groups": list(LOCKED_EXECUTION_EXCLUDED_SCOPE_GROUPS),
        "manual_ack_required": True,
        "ack_matched": ack_matched,
        "mutation_called": False,
        "translations_register_called": False,
        "shopify_write_performed": False,
        "shopify_api_call_performed": False,
        "mutation_performed": False,
        "readback_performed": False,
        "readback_matched": False,
        "rollback_needed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "restore_candidate": previous_translation_value,
        "blocking_conditions": [],
        "sanitized_errors": [],
        "audit_summary": {},
        "mutation_summary": {},
        "readback_summary": {},
        "json_report_path": json_path.as_posix(),
        "html_report_path": html_path.as_posix(),
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }

    blocking_conditions = []
    blocking_conditions.extend(load_blocking_conditions)
    blocking_conditions.extend(
        _real_write_blocking_conditions(
            locked_execution_package=locked_execution_package,
            entry=entry,
            selected_entry_id=selected_entry_id,
            selected_entry_checksum=selected_entry_checksum,
            expected_checksum=expected_checksum,
            ack_matched=ack_matched,
            installation=installation,
        )
    )
    payload["executor_validated_locked_real_write_override"] = bool(
        locked_execution_package
        and locked_execution_package.get("real_write_allowed") is False
        and not blocking_conditions
    )
    payload["blocking_conditions"] = _unique_strings(blocking_conditions)
    if payload["blocking_conditions"]:
        payload["execution_status"] = REAL_WRITE_BLOCKED_STATUS
        return _finalize_real_write_payload(payload, json_path, html_path, write_reports)

    translation_input = {
        "locale": locale,
        "key": key,
        "value": proposed_translation_value,
        "translatableContentDigest": digest,
    }
    mutation_result = _real_write_translations_register(
        installation,
        resource_id,
        translation_input,
    )
    payload["mutation_called"] = mutation_result.get("called", False)
    payload["translations_register_called"] = mutation_result.get("called", False)
    payload["mutation_performed"] = mutation_result.get("called", False)
    payload["shopify_api_call_performed"] = mutation_result.get("called", False)
    payload["sanitized_errors"].extend(mutation_result.get("sanitized_errors") or [])
    payload["mutation_summary"] = {
        "http_status": mutation_result.get("http_status"),
        "request_failed": mutation_result.get("request_failed", False),
        "user_errors_count": len(mutation_result.get("user_errors") or []),
        "translation_count": len(mutation_result.get("translations") or []),
    }
    if (
        mutation_result.get("request_failed")
        or mutation_result.get("user_errors")
    ):
        payload["execution_status"] = REAL_WRITE_MUTATION_FAILED_STATUS
        return _finalize_real_write_payload(payload, json_path, html_path, write_reports)

    payload["shopify_write_performed"] = True
    payload["real_apply_performed"] = True
    readback_result = _real_write_readback(installation, resource_id, locale)
    payload["readback_performed"] = readback_result.get("called", False)
    payload["shopify_api_call_performed"] = True
    payload["sanitized_errors"].extend(readback_result.get("sanitized_errors") or [])
    readback_match = _real_write_readback_match(
        readback_result.get("translations") or [],
        key=key,
        locale=locale,
        proposed_translation_value=proposed_translation_value,
    )
    payload["readback_matched"] = readback_match["matched"]
    payload["rollback_needed"] = not readback_match["matched"]
    payload["readback_summary"] = readback_match
    payload["audit_summary"] = {
        "status": (
            REAL_WRITE_AUDIT_PASSED_STATUS
            if readback_match["matched"]
            else REAL_WRITE_AUDIT_FAILED_STATUS
        ),
        "key_exists": readback_match["key_exists"],
        "locale_matches": readback_match["locale_matches"],
        "value_matches": readback_match["value_matches"],
        "outdated_acceptable": readback_match["outdated_acceptable"],
        "rollback_needed": not readback_match["matched"],
    }
    payload["execution_status"] = (
        REAL_WRITE_AUDIT_PASSED_STATUS
        if readback_match["matched"] and not readback_result.get("request_failed")
        else REAL_WRITE_AUDIT_FAILED_STATUS
    )
    return _finalize_real_write_payload(payload, json_path, html_path, write_reports)


def build_selected_product_translation_apply_plan(draft_result, write_reports=True):
    draft_result = dict(draft_result or {})
    payload = _empty_apply_plan(draft_result)
    if not draft_result:
        payload["apply_plan_status"] = "blocked_missing_draft_package"
        payload["blocking_conditions"].append("blocked_missing_draft_package")
    elif draft_result.get("draft_status") not in READY_DRAFT_STATUSES:
        payload["apply_plan_status"] = "blocked_draft_package_not_ready"
        payload["blocking_conditions"].append("blocked_draft_package_not_ready")
    else:
        _collect_entries(payload, draft_result)
        if payload["entry_count"]:
            payload["apply_plan_status"] = "selected_product_translation_apply_plan_ready_for_manual_review"
            payload["success"] = True
        else:
            payload["apply_plan_status"] = "no_eligible_draft_entries_for_apply_plan"
            payload["success"] = True

    payload["timestamp"] = _utc_now()
    payload["generated_at"] = payload["timestamp"]
    payload["json_selected_product_apply_plan_package_path"] = str(APPLY_PLAN_JSON_PATH)
    payload["html_selected_product_apply_plan_package_path"] = str(APPLY_PLAN_HTML_PATH)

    if write_reports:
        _write_reports(payload)
    return payload


def _empty_apply_plan(draft_result):
    return {
        "success": False,
        "apply_plan_status": "",
        "apply_plan_only": True,
        "product_id": draft_result.get("product_id", ""),
        "product_title": draft_result.get("product_title", ""),
        "target_locales": list(draft_result.get("target_locales") or []),
        "requested_fields": list(draft_result.get("requested_fields") or []),
        "entry_count": 0,
        "skipped_count": 0,
        "apply_plan_entries": [],
        "skipped_entries": [],
        "source_draft_status": draft_result.get("draft_status", ""),
        "source_generated_draft_count": draft_result.get("generated_draft_count", 0),
        "source_eligible_apply_plan_count": draft_result.get("eligible_apply_plan_count", 0),
        "source_skipped_existing_translation_count": draft_result.get("skipped_existing_translation_count", 0),
        "source_skipped_outdated_translation_count": draft_result.get("skipped_outdated_translation_count", 0),
        "source_shopify_api_call_performed": draft_result.get("shopify_api_call_performed", False),
        "source_openai_call_performed": draft_result.get("openai_call_performed", False),
        "manual_review_required": True,
        "next_step_requires_separate_execute_task": True,
        "existing_translation_overwrite_allowed": False,
        "outdated_translation_overwrite_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "blocking_conditions": [],
        "safety_summary": {
            "apply_plan_only": True,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "publish_performed": False,
            "apply_performed": False,
            "real_apply_performed": False,
            "rollback_performed": False,
            "existing_translation_overwrite_allowed": False,
            "outdated_translation_overwrite_allowed": False,
            "no_new_shopify_writes_performed": True,
            "all_new_actions_no_write_confirmed": True,
        },
    }


def _collect_entries(payload, draft_result):
    for entry in draft_result.get("entries", []):
        if _entry_is_apply_eligible(entry):
            payload["apply_plan_entries"].append(_apply_entry(payload, entry))
        else:
            payload["skipped_entries"].append(_skipped_entry(entry))
    payload["entry_count"] = len(payload["apply_plan_entries"])
    payload["skipped_count"] = len(payload["skipped_entries"])


def _entry_is_apply_eligible(entry):
    return (
        entry.get("eligible_for_apply_plan") is True
        and entry.get("validation_status") == "draft_ready_for_manual_review"
        and entry.get("seo_validation_status") == "seo_ready"
        and not entry.get("existing_translation_present")
        and entry.get("existing_translation_outdated") is not True
        and not entry.get("skip_reason")
        and not entry.get("future_write_needs_mapping")
        and entry.get("resource_group") in {"product_basics", "seo"}
        and entry.get("field") in {"title", "meta_title", "meta_description"}
        and bool(str(entry.get("draft_value") or "").strip())
    )


def _apply_entry(payload, entry):
    return {
        "product_id": payload.get("product_id", ""),
        "product_title": payload.get("product_title", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "source_key": entry.get("source_key", entry.get("field", "")),
        "resource_id": entry.get("resource_id", ""),
        "resource_group": entry.get("resource_group", ""),
        "source_value": entry.get("source_value", ""),
        "proposed_translation": entry.get("draft_value", ""),
        "proposed_value": entry.get("draft_value", ""),
        "proposed_value_chars": entry.get("draft_value_chars", len(str(entry.get("draft_value") or ""))),
        "digest": entry.get("source_digest", ""),
        "source_digest": entry.get("source_digest", ""),
        "current_translation_state": {
            "existing_translation_present": entry.get("existing_translation_present", False),
            "existing_translation_outdated": entry.get("existing_translation_outdated"),
            "skip_reason": entry.get("skip_reason", ""),
        },
        "validation_status": entry.get("validation_status", ""),
        "quality_notes": entry.get("quality_notes", []),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "seo_notes": entry.get("seo_notes", []),
        "eligible_for_apply_plan": True,
        "manual_review_required": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _skipped_entry(entry):
    reason = entry.get("skip_reason") or "not_eligible_for_apply_plan"
    if entry.get("existing_translation_present"):
        reason = "already_translated"
    if entry.get("existing_translation_outdated") is True:
        reason = "existing_translation_outdated_manual_review_required"
    if entry.get("validation_status") != "draft_ready_for_manual_review" and not entry.get("skip_reason"):
        reason = "draft_not_ready_for_manual_review"
    if entry.get("seo_validation_status") != "seo_ready" and not entry.get("skip_reason"):
        reason = "seo_not_ready_for_apply_plan"
    if entry.get("future_write_needs_mapping"):
        reason = entry.get("apply_plan_blocked_reason") or "future_write_needs_resource_mapping"
    return {
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "resource_id": entry.get("resource_id", ""),
        "resource_group": entry.get("resource_group", ""),
        "source_value": entry.get("source_value", ""),
        "draft_value": entry.get("draft_value", ""),
        "validation_status": entry.get("validation_status", ""),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "eligible_for_apply_plan": bool(entry.get("eligible_for_apply_plan")),
        "skip_reason": reason,
        "existing_translation_present": entry.get("existing_translation_present", False),
        "existing_translation_outdated": entry.get("existing_translation_outdated"),
    }


def _write_reports(payload):
    APPLY_PLAN_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    APPLY_PLAN_JSON_PATH.write_text(text, encoding="utf-8")
    APPLY_PLAN_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Apply Plan Status", "apply_plan_status"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Skipped Count", "skipped_count"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Source Draft Status", "source_draft_status"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Publish Performed", "publish_performed"),
            ("Apply Performed", "apply_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    entry_rows = "\n".join(_entry_row(entry) for entry in payload.get("apply_plan_entries", []))
    skipped_rows = "\n".join(_skipped_row(entry) for entry in payload.get("skipped_entries", []))
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Apply Plan</title></head>
<body>
  <h1>Selected Product Translation Apply Plan</h1>
  <p>Apply plan only. No Shopify write, mutation, translationsRegister, publish, apply, rollback, or existing translation overwrite was performed.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Apply Plan Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Proposed translation</th><th>Digest</th><th>Validation</th><th>SEO validation</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Skipped Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Skip reason</th><th>Validation</th><th>SEO validation</th></tr></thead>
    <tbody>{skipped_rows}</tbody>
  </table>
</body>
</html>
"""


def _row(label, value):
    return f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"


def _entry_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('source_value', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_translation', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('validation_status', '')))}</td>"
        f"<td>{escape(str(entry.get('seo_validation_status', '')))}</td>"
        "</tr>"
    )


def _skipped_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('skip_reason', '')))}</td>"
        f"<td>{escape(str(entry.get('validation_status', '')))}</td>"
        f"<td>{escape(str(entry.get('seo_validation_status', '')))}</td>"
        "</tr>"
    )


def _safe_write_entry_from_row(row: dict, *, product_gid: str):
    field_key = _safe_write_field_key(row)
    group_key = _safe_write_group_key(row, field_key)
    source_value = _safe_write_text_value(
        row,
        "source_value",
        "source_value_display",
        "source_value_preview",
        "source_preview",
    )
    proposed_value = _safe_write_text_value(
        row,
        "manual_edit_value",
        "manual_translation_override_value",
        "proposed_translation",
        "proposed_translation_display",
        "generated_draft_display",
        "generated_draft_summary",
        "proposed_translation_preview",
        "planned_value",
    )
    existing_value = _safe_write_text_value(
        row,
        "existing_translation_value",
        "existing_translation",
        "existing_translation_display",
        "existing_translation_preview",
    )
    digest = str(row.get("source_digest") or row.get("digest") or "").strip()
    locale = str(row.get("locale") or row.get("language") or "").strip()
    resource_id = str(row.get("resource_id") or "").strip()
    existing_present = _safe_write_bool(
        row.get("current_translation_present", row.get("existing_translation_present"))
    ) or bool(existing_value.strip())
    existing_outdated = _safe_write_bool(
        row.get("existing_translation_outdated", row.get("outdated"))
    )
    entry_id = str(row.get("safe_write_entry_id") or row.get("entry_id") or "").strip()
    if not entry_id:
        entry_id = _safe_write_entry_id(resource_id, field_key, locale, digest)
    entry = {
        "entry_id": entry_id,
        "locale": locale,
        "resource_id": resource_id,
        "key": field_key,
        "source_key": str(row.get("source_key") or row.get("resource_key") or field_key),
        "digest": digest,
        "source_value": source_value,
        "existing_translation_value": existing_value,
        "existing_translation_present": existing_present,
        "existing_translation_outdated": existing_outdated,
        "proposed_translation_value": proposed_value,
        "using_manual_edit": _safe_write_bool(row.get("using_manual_edit"))
        or bool(str(row.get("manual_edit_value") or "").strip()),
        "manual_edit_value": row.get("manual_edit_value")
        or row.get("manual_translation_override_value")
        or "",
        "openai_original_proposed_translation": row.get(
            "openai_original_proposed_translation"
        )
        or row.get("original_openai_translation", ""),
        "field_group": group_key,
        "context_label": row.get("context_label", ""),
        "validation_status": row.get("validation_status", ""),
        "seo_validation_status": row.get("seo_validation_status")
        or row.get("seo_status", ""),
        "seo_warning": row.get("seo_warning", ""),
        "blocking_reasons": row.get("blocking_reasons", ""),
        "status": row.get("status", ""),
        "draft_blocked": _safe_write_bool(row.get("draft_blocked")),
        "product_identity_mismatch": _safe_write_bool(
            row.get("product_identity_mismatch")
        ),
        "has_generated_draft": _safe_write_bool(row.get("has_generated_draft"))
        or bool(proposed_value.strip()),
    }
    reason = _safe_write_block_reason(entry, product_gid=product_gid)
    entry["eligibility_status"] = reason or "eligible_safe_write_readiness"
    entry["selectable"] = not reason
    entry["blocked_reason"] = reason
    entry["safe_write_entry_id"] = entry["entry_id"]
    return entry


def _safe_write_field_key(row: dict):
    raw_key = str(
        row.get("field") or row.get("key") or row.get("resource_key") or ""
    ).strip()
    normalized = raw_key.lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "body": "body_html",
        "description": "body_html",
        "seo_title": "meta_title",
        "seo_description": "meta_description",
    }
    return aliases.get(normalized, normalized)


def _safe_write_group_key(row: dict, field_key: str):
    group = str(row.get("resource_group") or row.get("group_key") or "").strip()
    if group:
        return group
    if field_key in {"title", "body_html"}:
        return "product_basics"
    if field_key in {"meta_title", "meta_description", "handle"}:
        return "seo"
    return "technical_fields"


def _safe_write_text_value(row: dict, *keys):
    for key in keys:
        value = row.get(key)
        if value is None:
            continue
        text = str(value)
        if text.strip():
            return text
    return ""


def _safe_write_bool(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _safe_write_block_reason(entry: dict, *, product_gid: str):
    field_key = entry.get("key", "")
    group_key = entry.get("field_group", "")
    if group_key in SAFE_WRITE_MAPPING_REQUIRED_GROUPS:
        return "blocked_future_write_needs_resource_mapping"
    if group_key in SAFE_WRITE_TECHNICAL_GROUPS:
        return "blocked_not_customer_write_safe"
    if field_key == "body_html":
        return "blocked_body_html_manual_review_required"
    if group_key not in SAFE_WRITE_READINESS_GROUP_SET:
        return "blocked_not_customer_write_safe"
    if field_key not in SAFE_WRITE_READINESS_FIELD_SET:
        return "blocked_not_customer_write_safe"
    if not entry.get("has_generated_draft"):
        return "blocked_missing_generated_draft"
    if not str(entry.get("source_value") or "").strip():
        return "blocked_source_empty"
    if (
        not entry.get("resource_id")
        or not entry.get("digest")
        or not product_gid
        or entry.get("resource_id") != product_gid
    ):
        return "blocked_missing_write_mapping"
    if entry.get("existing_translation_present") and not entry.get(
        "existing_translation_outdated"
    ):
        return "blocked_existing_current_translation"
    if entry.get("product_identity_mismatch"):
        return "blocked_identity_review_required"
    if entry.get("draft_blocked"):
        return "blocked_draft_status"
    notes = _safe_write_issue_text(entry)
    if "forbidden" in notes:
        return "blocked_forbidden_phrase_issue"
    if field_key in {"meta_title", "meta_description"} and _safe_write_has_over_length_issue(notes):
        return "blocked_over_length_issue"
    if entry.get("validation_status") not in {"", "draft_ready_for_manual_review"}:
        return "blocked_draft_manual_review_required"
    if (
        field_key in {"meta_title", "meta_description"}
        and entry.get("seo_validation_status")
        and entry.get("seo_validation_status") != "seo_ready"
    ):
        return "blocked_seo_manual_review_required"
    return ""


def _safe_write_issue_text(entry: dict):
    return " ".join(
        str(entry.get(key) or "").lower()
        for key in (
            "seo_warning",
            "blocking_reasons",
            "validation_status",
            "seo_validation_status",
            "status",
        )
    )


def _safe_write_has_over_length_issue(notes: str):
    return any(
        marker in notes
        for marker in (
            "over_length",
            "over-length",
            "over max",
            "over_max",
            "too_long",
            "draft_over_max_chars",
            "max_chars",
        )
    )


def _safe_write_entry_id(resource_id: str, key: str, locale: str, digest: str):
    raw = "|".join([resource_id or "", key or "", locale or "", digest or ""])
    return "swr_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


def _safe_write_locale_options(rows: list[dict], selected_locale: str):
    seen = []
    for row in rows or []:
        locale = row.get("locale", "")
        if locale and locale not in seen:
            seen.append(locale)
    if selected_locale and selected_locale not in seen:
        seen.insert(0, selected_locale)
    return [{"value": locale, "label": locale} for locale in seen]


def _safe_write_state_blocking_conditions(
    *,
    report: dict,
    product_gid: str,
    report_product_gid: str,
    locale: str,
    locale_rows: list[dict],
    eligible_entries: list[dict],
):
    conditions = []
    if not (report.get("exists") or report.get("job_id")):
        conditions.append("blocked_missing_background_draft_report")
    if report.get("status") not in SAFE_WRITE_READINESS_READY_JOB_STATUSES:
        conditions.append("blocked_background_draft_report_not_completed_or_partial")
    if not product_gid:
        conditions.append("blocked_missing_selected_product")
    if report_product_gid and product_gid and report_product_gid != product_gid:
        conditions.append("blocked_selected_product_report_mismatch")
    if not locale:
        conditions.append("blocked_missing_selected_locale")
    if locale and not locale_rows:
        conditions.append("blocked_no_report_rows_for_selected_locale")
    if locale_rows and not eligible_entries:
        conditions.append("blocked_no_safe_write_eligible_entries")
    return _unique_strings(conditions)


def _safe_write_blocked_entries_summary(blocked_entries: list[dict]):
    counts = {}
    for entry in blocked_entries or []:
        reason = entry.get("blocked_reason") or entry.get("eligibility_status") or "blocked"
        counts[reason] = counts.get(reason, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _safe_write_package_entry(entry: dict):
    return {
        "entry_id": entry.get("entry_id", ""),
        "locale": entry.get("locale", ""),
        "resource_id": entry.get("resource_id", ""),
        "key": entry.get("key", ""),
        "digest": entry.get("digest", ""),
        "source_value": entry.get("source_value", ""),
        "existing_translation_present": entry.get("existing_translation_present"),
        "existing_translation_value": entry.get("existing_translation_value", ""),
        "existing_translation_outdated": entry.get("existing_translation_outdated"),
        "proposed_translation_value": entry.get("proposed_translation_value", ""),
        "using_manual_edit": entry.get("using_manual_edit", False),
        "manual_edit_value": entry.get("manual_edit_value", ""),
        "openai_original_proposed_translation": entry.get(
            "openai_original_proposed_translation", ""
        ),
        "field_group": entry.get("field_group", ""),
        "context_label": entry.get("context_label", ""),
        "validation_status": entry.get("validation_status", ""),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "seo_warning": entry.get("seo_warning", ""),
        "blocking_reasons": entry.get("blocking_reasons", ""),
        "product_identity_mismatch": entry.get("product_identity_mismatch", False),
        "eligibility_status": entry.get("eligibility_status", ""),
    }


def _safe_write_readiness_report_paths(product_gid: str, locale: str, generated_at: str):
    product_token = _safe_write_product_token(product_gid)
    locale_token = _safe_write_filename_token(locale or "locale")
    stamp = _safe_write_timestamp_token(generated_at)
    base = f"translation_write_readiness_{product_token}_{locale_token}_{stamp}"
    return (
        SAFE_WRITE_READINESS_REPORT_DIR / f"{base}.json",
        SAFE_WRITE_READINESS_REPORT_DIR / f"{base}.html",
    )


def _safe_write_product_token(product_gid: str):
    text = str(product_gid or "").strip()
    if "/" in text:
        text = text.rsplit("/", 1)[-1]
    token = _safe_write_filename_token(text)
    if token:
        return token[:80]
    return "product_" + hashlib.sha256(str(product_gid or "").encode("utf-8")).hexdigest()[:12]


def _safe_write_filename_token(value: str):
    token = "".join(
        char if char.isalnum() or char in {"_", "-"} else "_"
        for char in str(value or "").strip()
    ).strip("_")
    return token or "unknown"


def _safe_write_timestamp_token(generated_at: str):
    return (
        str(generated_at or "")
        .replace("+00:00", "Z")
        .replace("-", "")
        .replace(":", "")
        .replace(".", "")
        .replace("Z", "Z")
    )


def _write_safe_write_readiness_reports(payload: dict, json_path: Path, html_path: Path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    json.loads(text)
    json_path.write_text(text, encoding="utf-8")
    html_path.write_text(_render_safe_write_readiness_html(payload), encoding="utf-8")


def _render_safe_write_readiness_html(payload: dict):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Package Status", "package_status"),
            ("Product GID", "product_gid"),
            ("Product Title", "product_title"),
            ("Locale", "locale"),
            ("Selected Entry Count", "selected_entry_count"),
            ("Max Entry Count", "max_entry_count"),
            ("Eligible Entries Count", "eligible_entries_count"),
            ("Blocked Entries Count", "blocked_entries_count"),
            ("JSON Report Path", "json_report_path"),
            ("HTML Report Path", "html_report_path"),
            ("Blocking Conditions", "blocking_conditions"),
            ("Shopify Read Only", "shopify_read_only"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Publish Performed", "publish_performed"),
            ("Apply Performed", "apply_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
        ]
    )
    selected_rows = "\n".join(
        _safe_write_selected_entry_row(entry)
        for entry in payload.get("selected_entries", [])
    ) or "<tr><td colspan='8'>No selected entries</td></tr>"
    blocked_rows = "\n".join(
        _safe_write_blocked_summary_row(item)
        for item in payload.get("blocked_entries_summary", [])
    ) or "<tr><td colspan='2'>No blocked entries</td></tr>"
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Translation Write Readiness Package</title></head>
<body>
  <h1>Translation Write Readiness Package</h1>
  <p>This package does not write Shopify. It only prepares a locked review for future ACK.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Selected Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Resource ID</th><th>Key</th><th>Digest</th><th>Source value</th><th>Existing translation</th><th>Outdated</th><th>Proposed translation</th><th>Eligibility</th></tr></thead>
    <tbody>{selected_rows}</tbody>
  </table>
  <h2>Blocked Entries Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Reason</th><th>Count</th></tr></thead>
    <tbody>{blocked_rows}</tbody>
  </table>
</body>
</html>
"""


def _safe_write_selected_entry_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('resource_id', '')))}</td>"
        f"<td>{escape(str(entry.get('key', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('source_value', '')))}</td>"
        f"<td>{escape(str(entry.get('existing_translation_value', '')))}</td>"
        f"<td>{escape(str(entry.get('existing_translation_outdated', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_translation_value', '')))}</td>"
        f"<td>{escape(str(entry.get('eligibility_status', '')))}</td>"
        "</tr>"
    )


def _safe_write_blocked_summary_row(item):
    return (
        "<tr>"
        f"<td>{escape(str(item.get('reason', '')))}</td>"
        f"<td>{escape(str(item.get('count', '')))}</td>"
        "</tr>"
    )


def _locked_execution_risk_checks(
    *,
    readiness_package: dict,
    latest_background_report: dict,
    product_gid: str,
    locale: str,
    selected_entry_ids: list[str],
    selected_entries: list[dict],
    selected_entry: dict,
):
    checks = []
    blocking_conditions = []

    def add_check(name, passed, blocked_reason, detail=""):
        status = "passed" if passed else "blocked"
        checks.append(
            {
                "name": name,
                "status": status,
                "blocking_condition": "" if passed else blocked_reason,
                "detail": detail,
            }
        )
        if not passed:
            blocking_conditions.append(blocked_reason)

    add_check(
        "safe_write_readiness_package_ready",
        bool(readiness_package)
        and readiness_package.get("package_status") == "write_readiness_ready",
        "blocked_safe_write_readiness_package_not_ready",
        readiness_package.get("package_status", ""),
    )
    add_check(
        "selected_entry_count_exactly_one",
        len(selected_entries) == 1
        and (not selected_entry_ids or len(selected_entry_ids) == 1),
        "blocked_selected_entry_count_not_exactly_1",
        f"selected_entries={len(selected_entries)} requested={len(selected_entry_ids)}",
    )

    field_key = str(selected_entry.get("key") or "").strip()
    field_group = str(selected_entry.get("field_group") or "").strip()
    resource_id = str(selected_entry.get("resource_id") or "").strip()
    digest = str(selected_entry.get("digest") or "").strip()
    source_value = str(selected_entry.get("source_value") or "")
    proposed_value = str(selected_entry.get("proposed_translation_value") or "")
    existing_value = str(selected_entry.get("existing_translation_value") or "")
    existing_present = _safe_write_bool(
        selected_entry.get("existing_translation_present")
    ) or bool(existing_value.strip())
    existing_outdated = _safe_write_bool(
        selected_entry.get("existing_translation_outdated")
    )
    forbidden_phrases = _locked_execution_forbidden_phrase_matches(proposed_value)
    latest_report_path = str(latest_background_report.get("report_path") or "").strip()
    source_report_path = str(
        readiness_package.get("source_background_report_path") or ""
    ).strip()
    latest_report_product_gid = str(
        latest_background_report.get("product_gid") or ""
    ).strip()

    add_check(
        "field_allowed",
        field_key in LOCKED_EXECUTION_ALLOWED_FIELD_SET,
        "blocked_field_not_allowed_for_locked_execution",
        field_key,
    )
    add_check(
        "field_group_allowed",
        field_group in SAFE_WRITE_READINESS_GROUP_SET,
        "blocked_field_group_not_locked_execution_scope",
        field_group,
    )
    add_check(
        "resource_key_digest_present",
        bool(resource_id and field_key and digest),
        "blocked_missing_resource_id_key_or_digest",
        f"resource_id={bool(resource_id)} key={bool(field_key)} digest={bool(digest)}",
    )
    add_check(
        "proposed_translation_present",
        bool(proposed_value.strip()),
        "blocked_proposed_translation_empty",
        "",
    )
    add_check(
        "proposed_translation_differs_from_source",
        bool(proposed_value.strip())
        and proposed_value.strip() != source_value.strip(),
        "blocked_proposed_translation_equals_source_value",
        "",
    )
    add_check(
        "forbidden_phrase_absent",
        not forbidden_phrases,
        "blocked_forbidden_cta_shipping_origin_phrase",
        ", ".join(forbidden_phrases),
    )
    add_check(
        "seo_title_length",
        field_key != "meta_title" or len(proposed_value) <= 60,
        "blocked_seo_title_over_60_chars",
        str(len(proposed_value)) if field_key == "meta_title" else "",
    )
    add_check(
        "seo_description_length",
        field_key != "meta_description" or len(proposed_value) <= 160,
        "blocked_seo_description_over_160_chars",
        str(len(proposed_value)) if field_key == "meta_description" else "",
    )
    add_check(
        "product_identity_matches",
        bool(product_gid)
        and bool(resource_id)
        and product_gid == resource_id
        and not _safe_write_bool(selected_entry.get("product_identity_mismatch")),
        "blocked_product_identity_mismatch",
        f"product_gid={product_gid} resource_id={resource_id}",
    )
    add_check(
        "entry_from_latest_selected_product_report",
        bool(latest_report_path)
        and bool(source_report_path)
        and latest_report_path == source_report_path
        and (
            not latest_report_product_gid
            or not product_gid
            or latest_report_product_gid == product_gid
        ),
        "blocked_entry_not_from_latest_selected_product_report",
        f"source={source_report_path} latest={latest_report_path}",
    )
    add_check(
        "readiness_package_safety_flags_safe",
        not _locked_execution_safety_flag_blocking_conditions(readiness_package),
        "blocked_readiness_package_safety_flags_not_safe",
        ", ".join(_locked_execution_safety_flag_blocking_conditions(readiness_package)),
    )
    add_check(
        "target_locale_supported",
        locale in LOCKED_EXECUTION_SUPPORTED_LOCALES,
        "blocked_target_locale_unsupported",
        locale,
    )
    add_check(
        "existing_translation_not_current",
        not existing_present or existing_outdated is True,
        "blocked_existing_translation_current_not_outdated",
        f"existing_present={existing_present} existing_outdated={existing_outdated}",
    )

    return checks, _unique_strings(blocking_conditions)


def _locked_execution_safety_flag_blocking_conditions(readiness_package: dict):
    conditions = []
    for key, expected in SAFE_WRITE_SAFETY_FLAGS.items():
        if readiness_package.get(key) is not expected:
            conditions.append(f"readiness_safety_{key}_not_confirmed")
    if readiness_package.get("shopify_api_call_performed") is True:
        conditions.append("readiness_safety_shopify_api_call_performed_not_false")
    return conditions


def _locked_execution_forbidden_phrase_matches(value: str):
    normalized = str(value or "").lower()
    return [
        phrase
        for phrase in LOCKED_EXECUTION_FORBIDDEN_PHRASES
        if phrase in normalized
    ]


def _locked_execution_entry_snapshot(entry: dict, *, product_gid: str, locale: str):
    snapshot = {
        "entry_id": entry.get("entry_id", ""),
        "product_gid": product_gid,
        "locale": locale,
        "resource_id": entry.get("resource_id", ""),
        "key": entry.get("key", ""),
        "digest": entry.get("digest", ""),
        "source_value": entry.get("source_value", ""),
        "existing_translation_value": entry.get("existing_translation_value", ""),
        "existing_translation_outdated": entry.get("existing_translation_outdated"),
        "proposed_translation_value": entry.get("proposed_translation_value", ""),
        "using_manual_edit": entry.get("using_manual_edit", False),
        "manual_edit_value": entry.get("manual_edit_value", ""),
        "openai_original_proposed_translation": entry.get(
            "openai_original_proposed_translation", ""
        ),
        "field_group": entry.get("field_group", ""),
        "context_label": entry.get("context_label", ""),
    }
    checksum = _locked_execution_entry_checksum(snapshot)
    snapshot["locked_entry_hash"] = checksum
    snapshot["locked_entry_checksum"] = checksum
    return snapshot


def _locked_execution_entry_checksum(snapshot: dict):
    locked_fields = {
        key: snapshot.get(key)
        for key in (
            "product_gid",
            "locale",
            "resource_id",
            "key",
            "digest",
            "source_value",
            "existing_translation_value",
            "existing_translation_outdated",
            "proposed_translation_value",
        )
    }
    text = json.dumps(locked_fields, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _locked_execution_report_paths(product_gid: str, locale: str, generated_at: str):
    product_token = _safe_write_product_token(product_gid)
    locale_token = _safe_write_filename_token(locale or "locale")
    stamp = _safe_write_timestamp_token(generated_at)
    base = f"translation_locked_execution_{product_token}_{locale_token}_{stamp}"
    return (
        LOCKED_EXECUTION_REPORT_DIR / f"{base}.json",
        LOCKED_EXECUTION_REPORT_DIR / f"{base}.html",
    )


def _write_locked_execution_reports(payload: dict, json_path: Path, html_path: Path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    json.loads(text)
    json_path.write_text(text, encoding="utf-8")
    html_path.write_text(_render_locked_execution_html(payload), encoding="utf-8")


def _render_locked_execution_html(payload: dict):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Package Status", "package_status"),
            ("Product GID", "product_gid"),
            ("Product Title", "product_title"),
            ("Locale", "locale"),
            ("Selected Entry Count", "selected_entry_count"),
            ("Resource ID", "resource_id"),
            ("Key", "key"),
            ("Digest", "digest"),
            ("Locked Entry Checksum", "locked_entry_checksum"),
            ("ACK Phrase", "manual_ack_phrase_required"),
            ("ACK Effective", "manual_ack_effective"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Future Write Allowed", "future_write_allowed"),
            ("JSON Report Path", "json_report_path"),
            ("HTML Report Path", "html_report_path"),
            ("Blocking Conditions", "blocking_conditions"),
            ("shopify_write_performed", "shopify_write_performed"),
            ("mutation_performed", "mutation_performed"),
            ("translations_register_called", "translations_register_called"),
        ]
    )
    entry = payload.get("selected_entry") or {}
    entry_rows = "\n".join(
        _row(label, entry.get(key))
        for label, key in [
            ("Source Value", "source_value"),
            ("Existing Translation", "existing_translation_value"),
            ("Existing Translation Outdated", "existing_translation_outdated"),
            ("Proposed Translation", "proposed_translation_value"),
        ]
    )
    risk_rows = "\n".join(
        _locked_execution_risk_check_row(item)
        for item in payload.get("risk_checks", [])
    ) or "<tr><td colspan='4'>No risk checks recorded</td></tr>"
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Translation Locked Execution Package</title></head>
<body>
  <h1>Final Shopify Update Preparation</h1>
  <p><strong>Locked preparation only &mdash; Shopify will not be updated in this step.</strong></p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Selected Entry</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{entry_rows}</tbody></table>
  <h2>Risk Checks</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Check</th><th>Status</th><th>Blocking condition</th><th>Detail</th></tr></thead>
    <tbody>{risk_rows}</tbody>
  </table>
</body>
</html>
"""


def _locked_execution_risk_check_row(item):
    return (
        "<tr>"
        f"<td>{escape(str(item.get('name', '')))}</td>"
        f"<td>{escape(str(item.get('status', '')))}</td>"
        f"<td>{escape(str(item.get('blocking_condition', '')))}</td>"
        f"<td>{escape(str(item.get('detail', '')))}</td>"
        "</tr>"
    )


def _real_write_package_entry(locked_execution_package: dict):
    entry = locked_execution_package.get("selected_entry") or {}
    if isinstance(entry, dict) and entry:
        return dict(entry)
    selected_entries = locked_execution_package.get("selected_entries") or []
    if len(selected_entries) == 1 and isinstance(selected_entries[0], dict):
        return dict(selected_entries[0])
    return {}


def _real_write_blocking_conditions(
    *,
    locked_execution_package: dict,
    entry: dict,
    selected_entry_id: str,
    selected_entry_checksum: str,
    expected_checksum: str,
    ack_matched: bool,
    installation,
):
    conditions = []
    if not locked_execution_package:
        conditions.append("blocked_locked_package_missing")
    if (
        locked_execution_package.get("package_status")
        != LOCKED_EXECUTION_READY_STATUS
    ):
        conditions.append("blocked_locked_package_status_not_ready")

    selected_entry_count = _real_write_int(
        locked_execution_package.get("selected_entry_count")
    )
    if selected_entry_count != 1:
        conditions.append("blocked_selected_entry_count_not_exactly_1")
    selected_entries = locked_execution_package.get("selected_entries") or []
    if len(selected_entries) != 1:
        conditions.append("blocked_selected_entries_payload_not_exactly_1")
    if not entry:
        conditions.append("blocked_locked_package_selected_entry_missing")

    expected_entry_id = str(entry.get("entry_id") or "").strip()
    if (
        not selected_entry_id
        or not expected_entry_id
        or selected_entry_id != expected_entry_id
    ):
        conditions.append("blocked_selected_entry_id_mismatch")
    if (
        not selected_entry_checksum
        or not expected_checksum
        or selected_entry_checksum != expected_checksum
    ):
        conditions.append("blocked_entry_checksum_mismatch")

    recalculated_checksum = _locked_execution_entry_checksum(entry) if entry else ""
    if expected_checksum and recalculated_checksum and expected_checksum != recalculated_checksum:
        conditions.append("blocked_locked_entry_checksum_recalculation_mismatch")

    product_gid = str(locked_execution_package.get("product_gid") or "").strip()
    package_locale = str(locked_execution_package.get("locale") or "").strip()
    entry_product_gid = str(entry.get("product_gid") or "").strip()
    entry_locale = str(entry.get("locale") or "").strip()
    key = str(entry.get("key") or locked_execution_package.get("key") or "").strip()
    resource_id = str(
        entry.get("resource_id") or locked_execution_package.get("resource_id") or ""
    ).strip()
    digest = str(entry.get("digest") or locked_execution_package.get("digest") or "").strip()
    source_value = str(
        entry.get("source_value") or locked_execution_package.get("source_value") or ""
    )
    proposed_value = str(
        entry.get("proposed_translation_value")
        or locked_execution_package.get("proposed_translation_value")
        or ""
    )

    if not product_gid or not entry_product_gid or product_gid != entry_product_gid:
        conditions.append("blocked_product_gid_mismatch")
    if not package_locale or not entry_locale or package_locale != entry_locale:
        conditions.append("blocked_locale_mismatch")
    if package_locale not in LOCKED_EXECUTION_SUPPORTED_LOCALES:
        conditions.append("blocked_target_locale_unsupported")
    if key not in LOCKED_EXECUTION_ALLOWED_FIELD_SET:
        conditions.append("blocked_field_not_allowed_for_real_write")
    if not resource_id:
        conditions.append("blocked_resource_id_missing")
    if not digest:
        conditions.append("blocked_digest_missing")
    if not proposed_value.strip():
        conditions.append("blocked_proposed_translation_empty")
    if proposed_value.strip() and proposed_value.strip() == source_value.strip():
        conditions.append("blocked_proposed_translation_equals_source")
    if _locked_execution_forbidden_phrase_matches(proposed_value):
        conditions.append("blocked_forbidden_phrase_detected")
    if key == "meta_title" and len(proposed_value) > 60:
        conditions.append("blocked_seo_title_over_60_chars")
    if key == "meta_description" and len(proposed_value) > 160:
        conditions.append("blocked_seo_description_over_160_chars")
    if not product_gid or not resource_id or product_gid != resource_id:
        conditions.append("blocked_product_identity_mismatch")
    if not ack_matched:
        conditions.append("blocked_manual_ack_phrase_not_exact")
    if installation is None:
        conditions.append("blocked_shopify_installation_missing")
    elif not getattr(installation, "shop", "") or not getattr(
        installation, "access_token", ""
    ):
        conditions.append("blocked_shopify_installation_incomplete")
    return _unique_strings(conditions)


def _real_write_translations_register(installation, resource_id: str, translation_input: dict):
    query = """
    mutation translationsRegister($resourceId: ID!, $translations: [TranslationInput!]!) {
      translationsRegister(resourceId: $resourceId, translations: $translations) {
        translations {
          key
          locale
          value
          outdated
        }
        userErrors {
          field
          message
          code
        }
      }
    }
    """
    url = f"https://{installation.shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    result = {
        "called": True,
        "request_failed": False,
        "http_status": None,
        "translations": [],
        "user_errors": [],
        "sanitized_errors": [],
    }
    try:
        response = requests.post(
            url,
            headers={
                "X-Shopify-Access-Token": installation.access_token,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "variables": {
                    "resourceId": resource_id,
                    "translations": [translation_input],
                },
            },
            timeout=45,
        )
        result["http_status"] = response.status_code
        response.raise_for_status()
        data = response.json()
    except requests.HTTPError:
        result["request_failed"] = True
        result["sanitized_errors"].append(
            _real_write_error(
                "translations_register",
                f"Shopify HTTP {result['http_status']} returned for translationsRegister.",
                "shopify_http_error",
            )
        )
        return result
    except requests.RequestException as exc:
        result["request_failed"] = True
        result["sanitized_errors"].append(
            _real_write_error(
                "translations_register",
                "Shopify request failed during translationsRegister.",
                exc.__class__.__name__,
            )
        )
        return result
    except ValueError:
        result["request_failed"] = True
        result["sanitized_errors"].append(
            _real_write_error(
                "translations_register",
                "Shopify returned non-JSON during translationsRegister.",
                "shopify_invalid_json_response",
            )
        )
        return result

    graphql_errors = data.get("errors") or []
    mutation_payload = (data.get("data") or {}).get("translationsRegister") or {}
    user_errors = mutation_payload.get("userErrors") or []
    result["request_failed"] = bool(graphql_errors)
    result["translations"] = mutation_payload.get("translations") or []
    result["user_errors"] = user_errors
    for error in graphql_errors:
        result["sanitized_errors"].append(
            _real_write_error(
                "translations_register",
                _real_write_graphql_error_message(error),
                "shopify_graphql_error",
            )
        )
    for error in user_errors:
        result["sanitized_errors"].append(
            _real_write_error(
                "translations_register",
                _real_write_user_error_message(error),
                "shopify_user_error",
            )
        )
    return result


def _real_write_readback(installation, resource_id: str, locale: str):
    query = """
    query($id: ID!, $locale: String!) {
      translatableResource(resourceId: $id) {
        resourceId
        translations(locale: $locale) {
          key
          value
          locale
          outdated
        }
      }
    }
    """
    url = f"https://{installation.shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    result = {
        "called": True,
        "request_failed": False,
        "http_status": None,
        "translations": [],
        "sanitized_errors": [],
    }
    try:
        response = requests.post(
            url,
            headers={
                "X-Shopify-Access-Token": installation.access_token,
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": {"id": resource_id, "locale": locale}},
            timeout=30,
        )
        result["http_status"] = response.status_code
        response.raise_for_status()
        data = response.json()
    except requests.HTTPError:
        result["request_failed"] = True
        result["sanitized_errors"].append(
            _real_write_error(
                "readback",
                f"Shopify HTTP {result['http_status']} returned for readback.",
                "shopify_http_error",
            )
        )
        return result
    except requests.RequestException as exc:
        result["request_failed"] = True
        result["sanitized_errors"].append(
            _real_write_error(
                "readback",
                "Shopify request failed during readback.",
                exc.__class__.__name__,
            )
        )
        return result
    except ValueError:
        result["request_failed"] = True
        result["sanitized_errors"].append(
            _real_write_error(
                "readback",
                "Shopify returned non-JSON during readback.",
                "shopify_invalid_json_response",
            )
        )
        return result

    graphql_errors = data.get("errors") or []
    result["request_failed"] = bool(graphql_errors)
    resource = (data.get("data") or {}).get("translatableResource") or {}
    result["translations"] = resource.get("translations") or []
    for error in graphql_errors:
        result["sanitized_errors"].append(
            _real_write_error(
                "readback",
                _real_write_graphql_error_message(error),
                "shopify_graphql_error",
            )
        )
    return result


def _real_write_readback_match(
    translations: list[dict],
    *,
    key: str,
    locale: str,
    proposed_translation_value: str,
):
    matching_key = [item for item in translations if item.get("key") == key]
    matching = [
        item
        for item in matching_key
        if item.get("locale") == locale
    ]
    item = matching[0] if matching else {}
    outdated = item.get("outdated") if item else None
    outdated_acceptable = outdated is False or outdated is None
    if isinstance(outdated, str):
        outdated_acceptable = outdated.strip().lower() in {"", "0", "false", "none"}
    value_matches = bool(item) and item.get("value") == proposed_translation_value
    locale_matches = bool(item) and item.get("locale") == locale
    return {
        "matched": bool(item)
        and value_matches
        and locale_matches
        and outdated_acceptable,
        "key_exists": bool(matching_key),
        "locale_matches": locale_matches,
        "value_matches": value_matches,
        "outdated": outdated,
        "outdated_acceptable": outdated_acceptable,
        "readback_value": item.get("value", "") if item else "",
    }


def _finalize_real_write_payload(
    payload: dict,
    json_path: Path,
    html_path: Path,
    write_reports: bool,
):
    payload["blocking_conditions"] = _unique_strings(payload.get("blocking_conditions") or [])
    payload["sanitized_errors"] = _real_write_unique_errors(
        payload.get("sanitized_errors") or []
    )
    mutation_called = bool(payload.get("mutation_called"))
    payload["shopify_read_only"] = not mutation_called
    payload["no_new_shopify_writes_performed"] = not mutation_called
    payload["all_new_actions_no_write_confirmed"] = not mutation_called
    if write_reports:
        _write_real_write_reports(payload, json_path, html_path)
    return payload


def _real_write_report_paths(product_gid: str, locale: str, generated_at: str):
    product_token = _safe_write_product_token(product_gid)
    locale_token = _safe_write_filename_token(locale or "locale")
    stamp = _safe_write_timestamp_token(generated_at)
    base = f"translation_real_write_{product_token}_{locale_token}_{stamp}"
    return (
        REAL_WRITE_REPORT_DIR / f"{base}.json",
        REAL_WRITE_REPORT_DIR / f"{base}.html",
    )


def _write_real_write_reports(payload: dict, json_path: Path, html_path: Path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    json.loads(text)
    json_path.write_text(text, encoding="utf-8")
    html_path.write_text(_render_real_write_html(payload), encoding="utf-8")


def _render_real_write_html(payload: dict):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Execution Status", "execution_status"),
            ("Product GID", "product_gid"),
            ("Locale", "locale"),
            ("Key", "key"),
            ("Resource ID", "resource_id"),
            ("Digest", "digest"),
            ("ACK Matched", "ack_matched"),
            ("Mutation Called", "mutation_called"),
            ("translationsRegister Called", "translations_register_called"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Readback Performed", "readback_performed"),
            ("Readback Matched", "readback_matched"),
            ("Rollback Needed", "rollback_needed"),
            ("Blocking Conditions", "blocking_conditions"),
            ("JSON Report Path", "json_report_path"),
            ("HTML Report Path", "html_report_path"),
        ]
    )
    value_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Source Value", "source_value"),
            ("Previous Translation Value", "previous_translation_value"),
            ("Proposed Translation Value", "proposed_translation_value"),
            ("Restore Candidate", "restore_candidate"),
        ]
    )
    error_rows = "\n".join(
        _real_write_error_row(error)
        for error in payload.get("sanitized_errors", [])
    ) or "<tr><td colspan='3'>No sanitized errors recorded</td></tr>"
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Translation Real Write Audit</title></head>
<body>
  <h1>Translation Real Write Audit</h1>
  <p><strong>Manual single-entry executor. No publish, apply, or automatic rollback is performed.</strong></p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Values</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{value_rows}</tbody></table>
  <h2>Sanitized Errors</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Stage</th><th>Type</th><th>Message</th></tr></thead>
    <tbody>{error_rows}</tbody>
  </table>
</body>
</html>
"""


def _real_write_error(stage: str, message: str, error_type: str):
    return {
        "stage": str(stage or ""),
        "type": str(error_type or ""),
        "message": str(message or "")[:500],
    }


def _real_write_error_row(error):
    return (
        "<tr>"
        f"<td>{escape(str(error.get('stage', '')))}</td>"
        f"<td>{escape(str(error.get('type', '')))}</td>"
        f"<td>{escape(str(error.get('message', '')))}</td>"
        "</tr>"
    )


def _real_write_graphql_error_message(error):
    if isinstance(error, dict):
        message = str(error.get("message") or "Shopify GraphQL error")
        path = ".".join(str(part) for part in (error.get("path") or []) if part is not None)
        return f"{message} (path: {path})" if path else message
    return "Shopify GraphQL error"


def _real_write_user_error_message(error):
    if isinstance(error, dict):
        message = str(error.get("message") or "Shopify user error")
        code = str(error.get("code") or "").strip()
        return f"{message} ({code})" if code else message
    return "Shopify user error"


def _real_write_unique_errors(errors):
    seen = set()
    unique = []
    for error in errors:
        if not isinstance(error, dict):
            continue
        key = (
            str(error.get("stage") or ""),
            str(error.get("type") or ""),
            str(error.get("message") or ""),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(error)
    return unique


def _real_write_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _unique_strings(values):
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
