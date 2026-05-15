import json
import hashlib
from datetime import datetime, timezone
from html import escape
from pathlib import Path


APPLY_PLAN_JSON_PATH = Path("logs/shopify_translation_selected_product_apply_plan_package.json")
APPLY_PLAN_HTML_PATH = Path("logs/shopify_translation_selected_product_apply_plan_package.html")
SAFE_WRITE_READINESS_REPORT_DIR = Path("logs/shopify_translation_write_readiness")
READY_DRAFT_STATUS = "selected_product_missing_translation_draft_ready_for_manual_review"
TRANSLATE_ALL_READY_DRAFT_STATUS = "selected_product_all_content_translation_draft_ready_for_manual_review"
READY_DRAFT_STATUSES = {READY_DRAFT_STATUS, TRANSLATE_ALL_READY_DRAFT_STATUS}
SAFE_WRITE_READINESS_ACTION_NAME = "prepare_translation_safe_write_readiness_package"
SAFE_WRITE_READINESS_MAX_ENTRY_COUNT = 3
SAFE_WRITE_READINESS_FIELDS = ("title", "meta_title", "meta_description")
SAFE_WRITE_READINESS_FIELD_SET = set(SAFE_WRITE_READINESS_FIELDS)
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
        "resource_id": entry.get("resource_id", ""),
        "key": entry.get("key", ""),
        "digest": entry.get("digest", ""),
        "source_value": entry.get("source_value", ""),
        "existing_translation_value": entry.get("existing_translation_value", ""),
        "existing_translation_outdated": entry.get("existing_translation_outdated"),
        "proposed_translation_value": entry.get("proposed_translation_value", ""),
        "field_group": entry.get("field_group", ""),
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


def _unique_strings(values):
    return list(dict.fromkeys(str(value) for value in values if str(value or "").strip()))


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
