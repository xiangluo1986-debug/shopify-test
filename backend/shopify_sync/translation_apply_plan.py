import json
import hashlib
import re
from datetime import datetime, timezone
from html import escape
from html.parser import HTMLParser
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
SELECTED_TRANSLATIONS_REAL_WRITE_ACTION_NAME = "apply_selected_translations_to_shopify"
ALL_LANGUAGES_REAL_WRITE_ACTION_NAME = "validate_and_update_all_languages_to_shopify"
LOCKED_EXECUTION_ACK_PHRASE = "I UNDERSTAND THIS WILL WRITE ONE SHOPIFY TRANSLATION"
SELECTED_TRANSLATIONS_REAL_WRITE_ACK_PHRASE = (
    "I UNDERSTAND THIS WILL WRITE SELECTED SHOPIFY TRANSLATIONS"
)
LOCKED_EXECUTION_READY_STATUS = "locked_execution_ready_for_manual_ack"
LOCKED_EXECUTION_BLOCKED_STATUS = "locked_execution_blocked"
REAL_WRITE_BLOCKED_STATUS = "write_blocked"
REAL_WRITE_MUTATION_FAILED_STATUS = "write_mutation_failed"
REAL_WRITE_AUDIT_PASSED_STATUS = "write_audit_passed"
REAL_WRITE_AUDIT_FAILED_STATUS = "write_audit_failed"
SELECTED_TRANSLATIONS_WRITTEN_AND_VERIFIED_STATUS = (
    "selected_shopify_translations_written_and_verified"
)
SELECTED_TRANSLATIONS_WRITE_PARTIAL_STATUS = "selected_shopify_translations_write_partial"
SELECTED_TRANSLATIONS_WRITE_FAILED_STATUS = "selected_shopify_translations_write_failed"
SELECTED_TRANSLATIONS_BLOCKED_STATUS = "selected_shopify_translations_blocked"
ALL_LANGUAGES_WRITTEN_AND_VERIFIED_STATUS = (
    "all_languages_shopify_translations_written_and_verified"
)
ALL_LANGUAGES_WRITE_PARTIAL_STATUS = "all_languages_shopify_translations_write_partial"
ALL_LANGUAGES_WRITE_FAILED_STATUS = "all_languages_shopify_translations_write_failed"
ALL_LANGUAGES_BLOCKED_STATUS = "all_languages_shopify_translations_blocked"
SAFE_WRITE_READINESS_MAX_ENTRY_COUNT = 3
SAFE_WRITE_READINESS_FIELDS = ("title", "meta_title", "meta_description")
SAFE_WRITE_READINESS_FIELD_SET = set(SAFE_WRITE_READINESS_FIELDS)
ALL_LANGUAGES_OPTION_AUTO_WRITE_FIELDS = ("option.name", "option.value")
ALL_LANGUAGES_MEDIA_ALT_AUTO_WRITE_FIELDS = ("media.alt",)
ALL_LANGUAGES_AUTO_WRITE_FIELDS = (
    SAFE_WRITE_READINESS_FIELDS
    + ("body_html",)
    + ALL_LANGUAGES_OPTION_AUTO_WRITE_FIELDS
    + ALL_LANGUAGES_MEDIA_ALT_AUTO_WRITE_FIELDS
)
ALL_LANGUAGES_AUTO_WRITE_FIELD_SET = set(ALL_LANGUAGES_AUTO_WRITE_FIELDS)
LOCKED_EXECUTION_ALLOWED_FIELDS = SAFE_WRITE_READINESS_FIELDS
LOCKED_EXECUTION_ALLOWED_FIELD_SET = set(LOCKED_EXECUTION_ALLOWED_FIELDS)
ALL_LANGUAGES_SUPPORTED_LOCALES = ("ja", "de", "fr", "es", "it")
ALL_LANGUAGES_LOCALE_LABELS = {
    "ja": "Japanese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
}
LOCKED_EXECUTION_SUPPORTED_LOCALES = set(ALL_LANGUAGES_SUPPORTED_LOCALES)
LOCKED_EXECUTION_LOCALE_LABEL_ALIASES = {
    "japanese": "ja",
    "german": "de",
    "french": "fr",
    "spanish": "es",
    "italian": "it",
}
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
ALL_LANGUAGES_MAPPING_BLOCKED_GROUPS = {
    "variants",
    "important_metafields",
    "metafields",
}
ALL_LANGUAGES_MAPPING_BLOCKED_REASON = (
    "Can review now; Shopify update support needs extra mapping."
)
ALL_LANGUAGES_TECHNICAL_METAFIELD_MARKERS = (
    "google",
    "google_product_category",
    "product_seo_template",
    "json",
    "schema",
    "system",
    "rating",
    "review",
    "reviews",
    "inventory",
    " id",
    "_id",
    "sku",
    "barcode",
    "gid://",
    "_gid",
    "token",
    "sync",
    "feed",
    "feeds",
    "internal",
    "technical",
    "wishlist",
    "count",
)
ALL_LANGUAGES_CUSTOMER_FACING_METAFIELD_MARKERS = (
    "benefit",
    "bullet",
    "compat",
    "compatibility",
    "description",
    "feature",
    "features",
    "highlight",
    "highlights",
    "included",
    "material",
    "model",
    "package",
    "package_included",
    "package included",
    "scale",
    "short_description",
    "size",
    "spec",
    "specification",
    "specifications",
    "subtitle",
    "summary",
)
ALL_LANGUAGES_BODY_HTML_LINK_MEDIA_TAGS = {"a", "img", "iframe", "source", "video"}
ALL_LANGUAGES_SAFE_FIELD_LABELS = {
    "title": "Product title",
    "meta_title": "SEO title",
    "meta_description": "SEO description",
    "body_html": "Product description",
    "media.alt": "Media alt text",
}
ALL_LANGUAGES_OPTION_FIELD_LABELS = {
    "option.name": "Product option name",
    "option.value": "Product option value",
}
ALL_LANGUAGES_FORBIDDEN_PHRASE_LABELS = (
    ("buy now", "buy now"),
    ("shop now", "shop now"),
    ("free shipping", "free shipping"),
    ("ships worldwide", "ships worldwide"),
    ("worldwide shipping", "worldwide shipping"),
    ("made in china", "Made in China"),
    ("mainland china", "mainland China"),
    ("versand weltweit", "Versand weltweit"),
    ("weltweiter versand", "Weltweiter Versand"),
    ("lieferung weltweit", "Lieferung weltweit"),
)
ALL_LANGUAGES_BODY_HTML_REPAIRABLE_FORBIDDEN_PHRASE_LABELS = (
    ("buy now", "buy now"),
    ("shop now", "shop now"),
    ("free shipping", "free shipping"),
    ("ships worldwide", "ships worldwide"),
    ("worldwide shipping", "worldwide shipping"),
    ("versand weltweit", "Versand weltweit"),
    ("weltweiter versand", "Weltweiter Versand"),
    ("lieferung weltweit", "Lieferung weltweit"),
)
ALL_LANGUAGES_BODY_HTML_REPAIRABLE_BLOCKING_REASONS = {
    "blocked_forbidden_phrase_detected",
    "blocked_needs_review_status",
}
ALL_LANGUAGES_BODY_HTML_REPAIRABLE_REVIEW_CODES = {
    "blocked",
    "draft_needs_manual_review",
    "forbidden_marketing_or_origin_phrase",
    "forbidden_marketing_or_shipping_phrase",
    "needs_review",
}
ALL_LANGUAGES_NEUTRAL_REVIEW_CODES = {
    "already_translated_skipped",
    "draft_ready_for_manual_review",
    "existing_translation_current",
    "missing_translation",
    "missing_translation_draft_ready",
    "outdated_translation",
    "outdated_translation_update_draft_ready",
    "preview_only",
    "seo_ready",
    "skipped",
}
ALL_LANGUAGES_SOFT_WARNING_CODES = {
    "existing_translation_outdated",
    "future_write_needs_resource_mapping",
    "keyword_stuffing_or_duplicate",
    "missing_core_keyword",
    "missing_model",
    "missing_part_type",
    "missing_replacement_part_meaning",
    "missing_use_case",
    "missing_value_point",
    "needs_review",
    "outdated",
    "seo_could_be_improved",
    "seo_needs_manual_review",
    "seo_not_ready",
    "seo_warning",
    "too_short_for_seo",
}
ALL_LANGUAGES_HARD_REVIEW_REASON_MAP = {
    "body_html_structure_broken": "blocked_body_html_structure_broken",
    "blocked": "blocked_needs_review_status",
    "draft_blocked": "blocked_needs_review_status",
    "draft_empty": "blocked_proposed_translation_empty",
    "draft_equals_source": "blocked_proposed_translation_equals_source",
    "draft_needs_manual_review_empty": "blocked_proposed_translation_empty",
    "forbidden_marketing_or_origin_phrase": "blocked_forbidden_phrase_detected",
    "forbidden_marketing_or_shipping_phrase": "blocked_forbidden_phrase_detected",
    "html_media_or_link_tag_broken": "blocked_html_media_or_link_tag_broken",
    "manual_review_required": "blocked_needs_review_status",
    "openai_invalid_translation_response": "blocked_needs_review_status",
    "product_identity_mismatch": "blocked_identity_review_required",
    "product_title_over_80_chars": "blocked_product_title_over_80_chars",
    "seo_description_over_160_chars": "blocked_seo_description_over_160_chars",
    "seo_title_over_60_chars": "blocked_seo_title_over_60_chars",
}
ALL_LANGUAGES_STATUS_LABELS = {
    "all_languages_shopify_update_not_submitted": "No Shopify update has been run yet.",
    ALL_LANGUAGES_WRITTEN_AND_VERIFIED_STATUS: "Shopify updated successfully",
    ALL_LANGUAGES_WRITE_PARTIAL_STATUS: "Shopify was partly updated",
    ALL_LANGUAGES_WRITE_FAILED_STATUS: "Shopify update failed",
    ALL_LANGUAGES_BLOCKED_STATUS: "No safe translations were updated",
}
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
    locale = _safe_write_canonical_locale(selected_locale)
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


def build_translation_workspace_selected_apply_state(
    background_report: dict | None,
    *,
    selected_product_gid: str = "",
    selected_locale: str = "",
):
    report = dict(background_report or {})
    product_gid = str(selected_product_gid or report.get("product_gid") or "").strip()
    report_product_gid = str(report.get("product_gid") or "").strip()
    report_detail_summary = report.get("report_detail_summary") or {}
    locale = _safe_write_canonical_locale(selected_locale)
    rows = [
        _selected_apply_entry_from_row(row, product_gid=product_gid)
        for row in (report.get("review_rows") or [])
        if isinstance(row, dict)
    ]
    locale_options = _safe_write_locale_options(rows, locale)
    locale_rows = [row for row in rows if row.get("locale") == locale] if locale else []
    eligible_entries = [row for row in locale_rows if row.get("selectable")]
    blocked_entries = [row for row in locale_rows if not row.get("selectable")]
    blocking_conditions = _selected_apply_state_blocking_conditions(
        report=report,
        product_gid=product_gid,
        report_product_gid=report_product_gid,
        locale=locale,
        locale_rows=locale_rows,
        eligible_entries=eligible_entries,
    )
    return {
        "status": "selected_shopify_translations_not_submitted",
        "report_exists": bool(report.get("exists") or report.get("job_id")),
        "report_status": report.get("status", ""),
        "report_status_label": report.get("status_label") or report.get("status", ""),
        "report_path": report.get("report_path", ""),
        "product_gid": product_gid,
        "report_product_gid": report_product_gid,
        "product_title": report.get("product_title")
        or report_detail_summary.get("product_title", ""),
        "locale": locale,
        "all_entries": rows,
        "locale_options": locale_options,
        "eligible_entries": eligible_entries,
        "blocked_entries": blocked_entries,
        "eligible_entries_count": len(eligible_entries),
        "blocked_entries_count": len(blocked_entries),
        "selected_entry_count": 0,
        "max_entry_count": SAFE_WRITE_READINESS_MAX_ENTRY_COUNT,
        "allowed_fields": list(SAFE_WRITE_READINESS_FIELDS),
        "blocked_fields": [
            "body_html",
            "options",
            "variants",
            "metafields",
            "media_alt_text",
            "technical_fields",
        ],
        "blocked_scope_groups": list(LOCKED_EXECUTION_EXCLUDED_SCOPE_GROUPS),
        "blocked_entries_summary": _safe_write_blocked_entries_summary(blocked_entries),
        "blocking_conditions": blocking_conditions,
        "can_submit": not blocking_conditions and bool(eligible_entries),
        "manual_ack_phrase_required": SELECTED_TRANSLATIONS_REAL_WRITE_ACK_PHRASE,
        "json_report_path": "",
        "html_report_path": "",
        "mutation_called": False,
        "translations_register_called": False,
        "shopify_write_performed": False,
        "shopify_api_call_performed": False,
        "mutation_performed": False,
        "readback_performed": False,
        "readback_verified_count": 0,
        "readback_failed_count": 0,
        "rollback_needed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "shopify_read_only": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def apply_selected_translations_to_shopify(
    background_report: dict | None,
    *,
    installation=None,
    selected_product_gid: str = "",
    selected_locale: str = "",
    selected_entry_ids=None,
    manual_ack_text: str = "",
    write_reports: bool = True,
):
    selected_entry_ids = _unique_strings(
        str(entry_id or "").strip()
        for entry_id in (selected_entry_ids or [])
        if str(entry_id or "").strip()
    )
    manual_ack_text = str(manual_ack_text or "")
    state = build_translation_workspace_selected_apply_state(
        background_report,
        selected_product_gid=selected_product_gid,
        selected_locale=selected_locale,
    )
    product_gid = str(state.get("product_gid") or "").strip()
    locale = str(state.get("locale") or "").strip()
    generated_at = _utc_now()
    json_path, html_path = _selected_translations_report_paths(
        product_gid,
        locale,
        generated_at,
    )
    ack_matched = manual_ack_text == SELECTED_TRANSLATIONS_REAL_WRITE_ACK_PHRASE
    eligible_by_id = {
        entry.get("entry_id"): entry
        for entry in state.get("eligible_entries") or []
        if entry.get("entry_id")
    }
    selected_entries = [
        _selected_apply_report_entry(eligible_by_id[entry_id])
        for entry_id in selected_entry_ids
        if entry_id in eligible_by_id
    ]
    blocking_conditions = list(state.get("blocking_conditions") or [])
    blocking_conditions.extend(
        _selected_apply_request_blocking_conditions(
            selected_entry_ids=selected_entry_ids,
            selected_entries=selected_entries,
            eligible_by_id=eligible_by_id,
            ack_matched=ack_matched,
            installation=installation,
        )
    )
    selected_fields = [entry.get("key", "") for entry in selected_entries]
    payload = {
        "action": SELECTED_TRANSLATIONS_REAL_WRITE_ACTION_NAME,
        "status": "",
        "audit_status": "",
        "generated_at": generated_at,
        "product_gid": product_gid,
        "product_title": state.get("product_title", ""),
        "locale": locale,
        "locale_options": state.get("locale_options", []),
        "selected_entry_count": len(selected_entries),
        "requested_selected_entry_count": len(selected_entry_ids),
        "max_entry_count": SAFE_WRITE_READINESS_MAX_ENTRY_COUNT,
        "selected_fields": selected_fields,
        "allowed_fields": list(SAFE_WRITE_READINESS_FIELDS),
        "blocked_fields": state.get("blocked_fields", []),
        "blocked_scope_groups": state.get("blocked_scope_groups", []),
        "selected_entries": selected_entries,
        "previous_translation_values": {
            entry.get("entry_id", ""): entry.get("previous_translation_value", "")
            for entry in selected_entries
        },
        "proposed_translation_values": {
            entry.get("entry_id", ""): entry.get("proposed_translation_value", "")
            for entry in selected_entries
        },
        "manual_edit_used": any(
            bool(entry.get("manual_edit_used")) for entry in selected_entries
        ),
        "manual_ack_required": True,
        "manual_ack_phrase_required": SELECTED_TRANSLATIONS_REAL_WRITE_ACK_PHRASE,
        "ack_matched": ack_matched,
        "mutation_called": False,
        "translations_register_called": False,
        "shopify_write_performed": False,
        "shopify_api_call_performed": False,
        "mutation_performed": False,
        "readback_performed": False,
        "readback_verified_count": 0,
        "readback_failed_count": 0,
        "rollback_needed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "blocking_conditions": _unique_strings(blocking_conditions),
        "sanitized_errors": [],
        "mutation_summary": {},
        "readback_summary": {},
        "translations_register_payload_preview": (
            _selected_apply_payload_preview(selected_entries)
        ),
        "json_report_path": json_path.as_posix(),
        "html_report_path": html_path.as_posix(),
        "shopify_read_only": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }
    if payload["blocking_conditions"]:
        payload["status"] = (
            "blocked_manual_ack_phrase_not_exact"
            if not ack_matched
            else SELECTED_TRANSLATIONS_BLOCKED_STATUS
        )
        payload["audit_status"] = SELECTED_TRANSLATIONS_BLOCKED_STATUS
        return _finalize_selected_translations_payload(
            payload,
            json_path,
            html_path,
            write_reports,
        )

    by_resource_id = {}
    for entry in selected_entries:
        by_resource_id.setdefault(entry.get("resource_id", ""), []).append(entry)

    mutation_summaries = {}
    for resource_id, resource_entries in by_resource_id.items():
        mutation_result = _real_write_translations_register(
            installation,
            resource_id,
            [
                {
                    "locale": locale,
                    "key": entry.get("key", ""),
                    "value": entry.get("proposed_translation_value", ""),
                    "translatableContentDigest": entry.get("digest", ""),
                }
                for entry in resource_entries
            ],
        )
        payload["mutation_called"] = (
            payload["mutation_called"] or mutation_result.get("called", False)
        )
        payload["translations_register_called"] = (
            payload["translations_register_called"]
            or mutation_result.get("called", False)
        )
        payload["mutation_performed"] = (
            payload["mutation_performed"] or mutation_result.get("called", False)
        )
        payload["shopify_api_call_performed"] = (
            payload["shopify_api_call_performed"]
            or mutation_result.get("called", False)
        )
        payload["sanitized_errors"].extend(
            mutation_result.get("sanitized_errors") or []
        )
        mutation_summaries[resource_id] = {
            "http_status": mutation_result.get("http_status"),
            "request_failed": mutation_result.get("request_failed", False),
            "user_errors_count": len(mutation_result.get("user_errors") or []),
            "translation_count": len(mutation_result.get("translations") or []),
            "selected_entry_count": len(resource_entries),
        }
        if mutation_result.get("request_failed") or mutation_result.get("user_errors"):
            payload["status"] = SELECTED_TRANSLATIONS_WRITE_FAILED_STATUS
            payload["audit_status"] = SELECTED_TRANSLATIONS_WRITE_FAILED_STATUS
            payload["mutation_summary"] = mutation_summaries
            return _finalize_selected_translations_payload(
                payload,
                json_path,
                html_path,
                write_reports,
            )

    payload["shopify_write_performed"] = True
    payload["real_apply_performed"] = True
    payload["mutation_summary"] = mutation_summaries
    readback_summaries = {}
    verified_count = 0
    failed_count = 0
    for resource_id, resource_entries in by_resource_id.items():
        readback_result = _real_write_readback(installation, resource_id, locale)
        payload["readback_performed"] = (
            payload["readback_performed"] or readback_result.get("called", False)
        )
        payload["shopify_api_call_performed"] = True
        payload["sanitized_errors"].extend(readback_result.get("sanitized_errors") or [])
        resource_summary = {
            "resource_id": resource_id,
            "readback_resource_id": readback_result.get("resource_id", ""),
            "request_failed": readback_result.get("request_failed", False),
            "http_status": readback_result.get("http_status"),
            "entries": [],
        }
        for entry in resource_entries:
            match = _real_write_readback_match(
                readback_result.get("translations") or [],
                key=entry.get("key", ""),
                locale=locale,
                proposed_translation_value=entry.get("proposed_translation_value", ""),
                expected_resource_id=resource_id,
                readback_resource_id=readback_result.get("resource_id", ""),
            )
            readback_verified = bool(match.get("matched")) and not readback_result.get(
                "request_failed"
            )
            if readback_verified:
                verified_count += 1
            else:
                failed_count += 1
            entry["readback"] = match
            entry["readback_verified"] = readback_verified
            entry["rollback_needed"] = not readback_verified
            resource_summary["entries"].append(
                {
                    "entry_id": entry.get("entry_id", ""),
                    "key": entry.get("key", ""),
                    "readback_verified": readback_verified,
                    "key_exists": match.get("key_exists", False),
                    "locale_matches": match.get("locale_matches", False),
                    "value_matches": match.get("value_matches", False),
                    "resource_id_matches": match.get("resource_id_matches", False),
                    "outdated_acceptable": match.get("outdated_acceptable", False),
                }
            )
        readback_summaries[resource_id] = resource_summary

    payload["readback_verified_count"] = verified_count
    payload["readback_failed_count"] = failed_count
    payload["rollback_needed"] = failed_count > 0
    payload["readback_summary"] = readback_summaries
    if verified_count == len(selected_entries) and failed_count == 0:
        payload["status"] = SELECTED_TRANSLATIONS_WRITTEN_AND_VERIFIED_STATUS
    elif verified_count:
        payload["status"] = SELECTED_TRANSLATIONS_WRITE_PARTIAL_STATUS
    else:
        payload["status"] = SELECTED_TRANSLATIONS_WRITE_FAILED_STATUS
    payload["audit_status"] = payload["status"]
    return _finalize_selected_translations_payload(
        payload,
        json_path,
        html_path,
        write_reports,
    )


def build_translation_workspace_all_languages_update_state(
    background_report: dict | None,
    *,
    selected_product_gid: str = "",
):
    report = dict(background_report or {})
    product_gid = str(selected_product_gid or "").strip()
    report_product_gid = str(report.get("product_gid") or "").strip()
    report_detail_summary = report.get("report_detail_summary") or {}
    entries = [
        _all_languages_update_entry_from_row(row, product_gid=product_gid)
        for row in (report.get("review_rows") or [])
        if isinstance(row, dict)
    ]
    blocking_conditions = _all_languages_state_blocking_conditions(
        report=report,
        product_gid=product_gid,
        report_product_gid=report_product_gid,
    )
    if blocking_conditions:
        _all_languages_apply_global_blockers(entries, blocking_conditions)
    write_ready_entries = [
        entry for entry in entries if entry.get("status") == "write_ready"
    ]
    if not write_ready_entries:
        blocking_conditions.append("blocked_no_write_ready_candidates")
    blocking_conditions = _unique_strings(blocking_conditions)
    state = {
        "status": "all_languages_shopify_update_not_submitted",
        "report_exists": bool(report.get("exists") or report.get("job_id")),
        "report_status": report.get("status", ""),
        "report_status_label": report.get("status_label") or report.get("status", ""),
        "report_path": report.get("report_path", ""),
        "job_id": report.get("job_id", ""),
        "product_gid": product_gid,
        "report_product_gid": report_product_gid,
        "product_title": report.get("product_title")
        or report_detail_summary.get("product_title", ""),
        "locales": list(ALL_LANGUAGES_SUPPORTED_LOCALES),
        "allowed_fields": list(ALL_LANGUAGES_AUTO_WRITE_FIELDS),
        "blocked_fields": [
            "variants",
            "metafields",
            "technical_fields",
        ],
        "entries": entries,
        "candidate_count": len(entries),
        "write_ready_count": len(write_ready_entries),
        "updated_count": 0,
        "verified_count": 0,
        "skipped_count": _all_languages_entry_status_count(entries, "skipped"),
        "blocked_count": _all_languages_entry_status_count(entries, "blocked"),
        "review_note_count": _all_languages_entry_soft_warning_count(entries),
        "failed_count": 0,
        "per_locale_summary": _all_languages_per_locale_summary(entries, report),
        "per_field_summary": _all_languages_per_field_summary(entries),
        "blocking_conditions": blocking_conditions,
        "can_submit": not blocking_conditions and bool(write_ready_entries),
        "mutation_called": False,
        "translations_register_called": False,
        "shopify_write_performed": False,
        "shopify_api_call_performed": False,
        "mutation_performed": False,
        "readback_performed": False,
        "rollback_needed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "json_report_path": "",
        "html_report_path": "",
        "sanitized_errors": [],
    }
    return _all_languages_attach_plain_language(state)


def load_latest_all_languages_update_report(product_gid: str):
    product_gid = str(product_gid or "").strip()
    if not product_gid:
        return {}
    product_token = _safe_write_product_token(product_gid)
    report_paths = []
    for report_dir in _all_languages_update_report_search_dirs():
        try:
            report_paths.extend(
                report_dir.glob(
                    f"translation_all_languages_update_{product_token}_*.json"
                )
            )
        except OSError:
            continue
    try:
        report_paths = sorted(
            report_paths,
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return {}
    for report_path in report_paths:
        try:
            payload = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        if payload.get("action_name") != ALL_LANGUAGES_REAL_WRITE_ACTION_NAME:
            continue
        report_product_gid = str(payload.get("product_gid") or "").strip()
        if report_product_gid and report_product_gid != product_gid:
            continue
        payload = dict(payload)
        payload["report_exists"] = True
        payload["latest_update_report_loaded"] = True
        payload["json_report_path"] = (
            payload.get("json_report_path") or report_path.as_posix()
        )
        payload["html_report_path"] = (
            payload.get("html_report_path") or report_path.with_suffix(".html").as_posix()
        )
        _all_languages_backfill_entry_metadata_from_source_report(payload)
        _all_languages_recount_payload(payload)
        return _all_languages_attach_plain_language(payload)
    return {}


def _all_languages_update_report_search_dirs():
    dirs = [REAL_WRITE_REPORT_DIR, Path("backend") / REAL_WRITE_REPORT_DIR]
    unique_dirs = []
    seen = set()
    for report_dir in dirs:
        key = str(report_dir)
        if key in seen:
            continue
        seen.add(key)
        unique_dirs.append(report_dir)
    return unique_dirs


def _all_languages_backfill_entry_metadata_from_source_report(payload: dict):
    report_path = _all_languages_resolve_source_report_path(
        payload.get("source_background_report_path", "")
    )
    if not report_path:
        return
    try:
        source_report = json.loads(report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(source_report, dict):
        return
    product_gid = str(payload.get("product_gid") or "").strip()
    source_entries = [
        _safe_write_entry_from_row(row, product_gid=product_gid)
        for row in source_report.get("review_rows") or []
        if isinstance(row, dict)
    ]
    by_entry_id = {
        entry.get("entry_id"): entry
        for entry in source_entries
        if entry.get("entry_id")
    }
    by_identity = {
        _all_languages_entry_metadata_identity(entry): entry
        for entry in source_entries
    }
    for entry in payload.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        source_entry = by_entry_id.get(entry.get("entry_id")) or by_identity.get(
            _all_languages_entry_metadata_identity(entry)
        )
        if source_entry:
            _all_languages_merge_entry_metadata(entry, source_entry)


def _all_languages_resolve_source_report_path(path_text: str):
    path_text = str(path_text or "").strip()
    if not path_text:
        return None
    candidates = [Path(path_text)]
    if not Path(path_text).is_absolute():
        candidates.append(Path("backend") / path_text)
    for path in candidates:
        if path.suffix.lower() != ".json":
            continue
        try:
            if path.exists() and path.is_file():
                return path
        except OSError:
            continue
    return None


def _all_languages_entry_metadata_identity(entry: dict):
    return (
        _safe_write_canonical_locale(entry.get("locale")),
        str(entry.get("resource_id") or "").strip(),
        str(entry.get("key") or "").strip(),
        str(entry.get("digest") or entry.get("source_digest") or "").strip(),
    )


def _all_languages_merge_entry_metadata(entry: dict, source_entry: dict):
    metadata_keys = (
        "source_key",
        "shopify_key",
        "source_digest",
        "resource_type",
        "resource_note",
        "field_label",
        "context_label",
        "option_name",
        "option_value",
        "option_position",
        "visible_product_option",
        "translation_preview_available",
        "shopify_update_mapping_ready",
        "translation_preview_without_digest",
        "selected_options",
        "media_alt",
        "media_content_type",
        "media_url",
    )
    for key in metadata_keys:
        value = source_entry.get(key)
        if value in (None, "", [], {}):
            continue
        if entry.get(key) in (None, "", [], {}):
            entry[key] = value


def validate_and_update_all_languages_to_shopify(
    background_report: dict | None,
    *,
    installation=None,
    selected_product_gid: str = "",
    write_reports: bool = True,
):
    state = build_translation_workspace_all_languages_update_state(
        background_report,
        selected_product_gid=selected_product_gid,
    )
    product_gid = str(state.get("product_gid") or "").strip()
    generated_at = _utc_now()
    json_path, html_path = _all_languages_update_report_paths(
        product_gid,
        generated_at,
    )
    write_ready_entries = [
        dict(entry)
        for entry in state.get("entries") or []
        if entry.get("status") == "write_ready"
    ]
    request_blockers = _all_languages_request_blocking_conditions(
        write_ready_entries=write_ready_entries,
        installation=installation,
    )
    blocking_conditions = _unique_strings(
        list(state.get("blocking_conditions") or []) + request_blockers
    )
    if request_blockers:
        _all_languages_apply_global_blockers(
            state.get("entries") or [],
            request_blockers,
        )
        write_ready_entries = []
    payload = {
        "action_name": ALL_LANGUAGES_REAL_WRITE_ACTION_NAME,
        "status": "",
        "audit_status": "",
        "generated_at": generated_at,
        "product_gid": product_gid,
        "product_title": state.get("product_title", ""),
        "report_exists": state.get("report_exists", False),
        "locales": list(ALL_LANGUAGES_SUPPORTED_LOCALES),
        "allowed_auto_write_fields": list(ALL_LANGUAGES_AUTO_WRITE_FIELDS),
        "blocked_auto_write_fields": state.get("blocked_fields", []),
        "source_background_report_path": state.get("report_path", ""),
        "source_background_report_status": state.get("report_status", ""),
        "candidate_count": state.get("candidate_count", 0),
        "write_ready_count": len(write_ready_entries),
        "updated_count": 0,
        "verified_count": 0,
        "skipped_count": 0,
        "blocked_count": 0,
        "review_note_count": state.get("review_note_count", 0),
        "failed_count": 0,
        "per_locale_summary": [],
        "per_field_summary": [],
        "preflight_summary": {
            "candidate_count": state.get("candidate_count", 0),
            "write_ready_count": len(write_ready_entries),
            "blocked_count": state.get("blocked_count", 0),
            "review_note_count": state.get("review_note_count", 0),
            "skipped_count": state.get("skipped_count", 0),
            "per_locale_summary": state.get("per_locale_summary", []),
            "per_field_summary": state.get("per_field_summary", []),
            "blocking_conditions": blocking_conditions,
        },
        "entries": [dict(entry) for entry in state.get("entries") or []],
        "mutation_called": False,
        "translations_register_called": False,
        "shopify_write_performed": False,
        "shopify_api_call_performed": False,
        "mutation_performed": False,
        "readback_performed": False,
        "rollback_needed": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "blocking_conditions": blocking_conditions,
        "sanitized_errors": [],
        "mutation_summary": {},
        "readback_summary": {},
        "json_report_path": json_path.as_posix(),
        "html_report_path": html_path.as_posix(),
        "shopify_read_only": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }
    if blocking_conditions:
        payload["status"] = ALL_LANGUAGES_BLOCKED_STATUS
        payload["audit_status"] = ALL_LANGUAGES_BLOCKED_STATUS
        return _finalize_all_languages_update_payload(
            payload,
            background_report or {},
            json_path,
            html_path,
            write_reports,
        )

    entries_by_id = {
        entry.get("entry_id", ""): entry
        for entry in payload["entries"]
        if entry.get("entry_id")
    }
    by_resource_id = {}
    for entry in write_ready_entries:
        by_resource_id.setdefault(entry.get("resource_id", ""), []).append(entry)

    mutation_summaries = {}
    successful_resource_entries = {}
    for resource_id, resource_entries in by_resource_id.items():
        mutation_result = _real_write_translations_register(
            installation,
            resource_id,
            [
                {
                    "locale": entry.get("locale", ""),
                    "key": _all_languages_shopify_write_key(entry),
                    "value": entry.get("proposed_translation_value", ""),
                    "translatableContentDigest": entry.get("digest", ""),
                }
                for entry in resource_entries
            ],
        )
        payload["mutation_called"] = (
            payload["mutation_called"] or mutation_result.get("called", False)
        )
        payload["translations_register_called"] = (
            payload["translations_register_called"]
            or mutation_result.get("called", False)
        )
        payload["mutation_performed"] = (
            payload["mutation_performed"] or mutation_result.get("called", False)
        )
        payload["shopify_api_call_performed"] = (
            payload["shopify_api_call_performed"]
            or mutation_result.get("called", False)
        )
        payload["sanitized_errors"].extend(
            mutation_result.get("sanitized_errors") or []
        )
        mutation_failed = bool(
            mutation_result.get("request_failed")
            or mutation_result.get("user_errors")
            or mutation_result.get("sanitized_errors")
        )
        mutation_summaries[resource_id] = {
            "http_status": mutation_result.get("http_status"),
            "request_failed": mutation_result.get("request_failed", False),
            "user_errors_count": len(mutation_result.get("user_errors") or []),
            "translation_count": len(mutation_result.get("translations") or []),
            "write_ready_entry_count": len(resource_entries),
            "mutation_failed": mutation_failed,
        }
        if mutation_failed:
            for entry in resource_entries:
                payload_entry = entries_by_id.get(entry.get("entry_id", ""))
                if payload_entry:
                    payload_entry["status"] = "write_failed"
                    payload_entry["blocking_reason"] = "translationsRegister failed"
                    payload_entry["blocking_reasons"] = ["translations_register_failed"]
            continue
        payload["shopify_write_performed"] = True
        payload["real_apply_performed"] = True
        successful_resource_entries[resource_id] = resource_entries

    payload["mutation_summary"] = mutation_summaries
    readback_summaries = {}
    for resource_id, resource_entries in successful_resource_entries.items():
        entries_by_locale = {}
        for entry in resource_entries:
            entries_by_locale.setdefault(entry.get("locale", ""), []).append(entry)
        for locale, locale_entries in entries_by_locale.items():
            readback_result = _real_write_readback(installation, resource_id, locale)
            payload["readback_performed"] = (
                payload["readback_performed"] or readback_result.get("called", False)
            )
            payload["shopify_api_call_performed"] = True
            payload["sanitized_errors"].extend(
                readback_result.get("sanitized_errors") or []
            )
            summary_key = f"{resource_id}|{locale}"
            readback_summaries[summary_key] = {
                "resource_id": resource_id,
                "readback_resource_id": readback_result.get("resource_id", ""),
                "locale": locale,
                "request_failed": readback_result.get("request_failed", False),
                "http_status": readback_result.get("http_status"),
                "entries": [],
            }
            for entry in locale_entries:
                match = _real_write_readback_match(
                    readback_result.get("translations") or [],
                    key=_all_languages_shopify_write_key(entry),
                    locale=locale,
                    proposed_translation_value=entry.get("proposed_translation_value", ""),
                    expected_resource_id=resource_id,
                    readback_resource_id=readback_result.get("resource_id", ""),
                )
                matched = bool(match.get("matched")) and not readback_result.get(
                    "request_failed"
                )
                payload_entry = entries_by_id.get(entry.get("entry_id", ""))
                if payload_entry:
                    payload_entry["readback_value"] = match.get("readback_value", "")
                    payload_entry["readback_matched"] = matched
                    payload_entry["status"] = (
                        "written_verified" if matched else "readback_mismatch"
                    )
                    payload_entry["blocking_reason"] = (
                        "" if matched else "Readback did not match proposed translation"
                    )
                    payload_entry["rollback_needed"] = not matched
                readback_summaries[summary_key]["entries"].append(
                    {
                        "entry_id": entry.get("entry_id", ""),
                        "key": entry.get("key", ""),
                        "shopify_key": _all_languages_shopify_write_key(entry),
                        "readback_matched": matched,
                        "key_exists": match.get("key_exists", False),
                        "locale_matches": match.get("locale_matches", False),
                        "value_matches": match.get("value_matches", False),
                        "resource_id_matches": match.get("resource_id_matches", False),
                        "outdated_acceptable": match.get("outdated_acceptable", False),
                    }
                )
    payload["readback_summary"] = readback_summaries
    payload["rollback_needed"] = any(
        bool(entry.get("rollback_needed")) for entry in payload["entries"]
    )
    payload["updated_count"] = _all_languages_entry_status_count(
        payload["entries"],
        "written_verified",
        "readback_mismatch",
    )
    payload["verified_count"] = _all_languages_entry_status_count(
        payload["entries"],
        "written_verified",
    )
    payload["failed_count"] = _all_languages_entry_status_count(
        payload["entries"],
        "write_failed",
        "readback_mismatch",
    )
    if (
        payload["updated_count"]
        and payload["verified_count"] == payload["updated_count"]
        and payload["failed_count"] == 0
    ):
        payload["status"] = ALL_LANGUAGES_WRITTEN_AND_VERIFIED_STATUS
    elif payload["updated_count"] or payload["verified_count"]:
        payload["status"] = ALL_LANGUAGES_WRITE_PARTIAL_STATUS
    elif payload["mutation_called"]:
        payload["status"] = ALL_LANGUAGES_WRITE_FAILED_STATUS
    else:
        payload["status"] = ALL_LANGUAGES_BLOCKED_STATUS
    payload["audit_status"] = payload["status"]
    return _finalize_all_languages_update_payload(
        payload,
        background_report or {},
        json_path,
        html_path,
        write_reports,
    )


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
        expected_resource_id=resource_id,
        readback_resource_id=readback_result.get("resource_id", ""),
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
        "resource_id_matches": readback_match["resource_id_matches"],
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
    source_key = str(row.get("source_key") or row.get("resource_key") or field_key)
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
    locale = _safe_write_canonical_locale(row.get("locale") or row.get("language"))
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
        "product_gid": row.get("product_gid") or product_gid,
        "resource_id": resource_id,
        "key": field_key,
        "source_key": source_key,
        "shopify_key": source_key,
        "digest": digest,
        "source_digest": digest,
        "resource_type": row.get("resource_type", ""),
        "resource_note": row.get("resource_note", ""),
        "field_label": row.get("field_label", ""),
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
        "option_name": row.get("option_name", ""),
        "option_value": row.get("option_value", ""),
        "option_position": row.get("option_position", ""),
        "visible_product_option": _safe_write_bool(row.get("visible_product_option")),
        "translation_preview_available": _safe_write_bool(
            row.get("translation_preview_available")
        ),
        "shopify_update_mapping_ready": _safe_write_bool(
            row.get("shopify_update_mapping_ready")
        ),
        "translation_preview_without_digest": _safe_write_bool(
            row.get("translation_preview_without_digest")
        ),
        "selected_options": row.get("selected_options", []),
        "media_alt": row.get("media_alt", ""),
        "media_content_type": row.get("media_content_type", ""),
        "media_url": row.get("media_url", ""),
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


def _selected_apply_entry_from_row(row: dict, *, product_gid: str):
    entry = _safe_write_entry_from_row(row, product_gid=product_gid)
    reason = _selected_apply_block_reason(entry, product_gid=product_gid)
    entry["eligibility_status"] = reason or "eligible_selected_shopify_translation"
    entry["selectable"] = not reason
    entry["blocked_reason"] = reason
    return entry


def _selected_apply_block_reason(entry: dict, *, product_gid: str):
    field_key = entry.get("key", "")
    group_key = entry.get("field_group", "")
    proposed_value = str(entry.get("proposed_translation_value") or "").strip()
    source_value = str(entry.get("source_value") or "").strip()
    locale = _safe_write_canonical_locale(entry.get("locale"))
    if group_key in SAFE_WRITE_MAPPING_REQUIRED_GROUPS:
        return "blocked_future_write_needs_resource_mapping"
    if group_key in SAFE_WRITE_TECHNICAL_GROUPS:
        return "blocked_not_customer_write_safe"
    if field_key == "body_html":
        return "blocked_body_html_forbidden_in_selected_apply"
    if group_key not in SAFE_WRITE_READINESS_GROUP_SET:
        return "blocked_scope_group_not_allowed"
    if field_key not in SAFE_WRITE_READINESS_FIELD_SET:
        return "blocked_field_not_allowed_for_selected_apply"
    if not (entry.get("has_generated_draft") or proposed_value):
        return "blocked_missing_generated_or_manual_translation"
    if not proposed_value:
        return "blocked_proposed_translation_empty"
    if (
        not entry.get("resource_id")
        or not field_key
        or not entry.get("digest")
    ):
        return "blocked_missing_resource_id_key_or_digest"
    if not product_gid or entry.get("resource_id") != product_gid:
        return "blocked_product_identity_mismatch"
    if locale and locale not in LOCKED_EXECUTION_SUPPORTED_LOCALES:
        return "blocked_target_locale_unsupported"
    if locale != "en" and source_value and proposed_value == source_value:
        return "blocked_proposed_translation_equals_source"
    if field_key == "title" and len(proposed_value) > 80:
        return "blocked_product_title_over_80_chars"
    if field_key == "meta_title" and len(proposed_value) > 60:
        return "blocked_seo_title_over_60_chars"
    if field_key == "meta_description" and len(proposed_value) > 160:
        return "blocked_seo_description_over_160_chars"
    if _locked_execution_forbidden_phrase_matches(proposed_value):
        return "blocked_forbidden_phrase_detected"
    if "forbidden" in _safe_write_issue_text(entry):
        return "blocked_forbidden_phrase_detected"
    if entry.get("product_identity_mismatch"):
        return "blocked_identity_review_required"
    if entry.get("draft_blocked"):
        return "blocked_draft_status"
    if entry.get("validation_status") not in {"", "draft_ready_for_manual_review"}:
        return "blocked_draft_manual_review_required"
    if (
        field_key in {"meta_title", "meta_description"}
        and entry.get("seo_validation_status")
        and entry.get("seo_validation_status") != "seo_ready"
    ):
        return "blocked_seo_manual_review_required"
    return ""


def _selected_apply_state_blocking_conditions(
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
    if locale and locale not in LOCKED_EXECUTION_SUPPORTED_LOCALES:
        conditions.append("blocked_target_locale_unsupported")
    if locale and not locale_rows:
        conditions.append("blocked_no_report_rows_for_selected_locale")
    if locale_rows and not eligible_entries:
        conditions.append("blocked_no_selected_apply_eligible_entries")
    return _unique_strings(conditions)


def _selected_apply_request_blocking_conditions(
    *,
    selected_entry_ids: list[str],
    selected_entries: list[dict],
    eligible_by_id: dict,
    ack_matched: bool,
    installation,
):
    conditions = []
    if not selected_entry_ids:
        conditions.append("blocked_selected_entry_count_less_than_1")
    if len(selected_entry_ids) > SAFE_WRITE_READINESS_MAX_ENTRY_COUNT:
        conditions.append("blocked_selected_entry_count_exceeds_3")
    unknown_entry_ids = [
        entry_id for entry_id in selected_entry_ids if entry_id not in eligible_by_id
    ]
    if unknown_entry_ids:
        conditions.append("blocked_selected_entries_not_eligible")
    if not selected_entries and selected_entry_ids:
        conditions.append("blocked_no_eligible_selected_entries")
    if not ack_matched:
        conditions.append("blocked_manual_ack_phrase_not_exact")
    if installation is None:
        conditions.append("blocked_shopify_installation_missing")
    elif not getattr(installation, "shop", "") or not getattr(
        installation,
        "access_token",
        "",
    ):
        conditions.append("blocked_shopify_installation_incomplete")
    return _unique_strings(conditions)


def _selected_apply_report_entry(entry: dict):
    return {
        "entry_id": entry.get("entry_id", ""),
        "locale": entry.get("locale", ""),
        "resource_id": entry.get("resource_id", ""),
        "key": entry.get("key", ""),
        "digest": entry.get("digest", ""),
        "source_value": entry.get("source_value", ""),
        "previous_translation_value": entry.get("existing_translation_value", ""),
        "previous_translation_existed": bool(
            str(entry.get("existing_translation_value") or "").strip()
        ),
        "previous_translation_outdated": entry.get("existing_translation_outdated"),
        "proposed_translation_value": entry.get("proposed_translation_value", ""),
        "manual_edit_used": bool(entry.get("using_manual_edit")),
        "manual_edit_value": entry.get("manual_edit_value", ""),
        "openai_original_proposed_translation": entry.get(
            "openai_original_proposed_translation",
            "",
        ),
        "restore_candidate": entry.get("existing_translation_value", ""),
        "field_group": entry.get("field_group", ""),
        "context_label": entry.get("context_label", ""),
        "eligibility_status": entry.get("eligibility_status", ""),
        "readback_verified": False,
        "rollback_needed": False,
    }


def _selected_apply_payload_preview(selected_entries: list[dict]):
    grouped = {}
    for entry in selected_entries:
        resource_id = entry.get("resource_id", "")
        grouped.setdefault(resource_id, []).append(
            {
                "locale": entry.get("locale", ""),
                "key": entry.get("key", ""),
                "value": entry.get("proposed_translation_value", ""),
                "translatableContentDigest": entry.get("digest", ""),
            }
        )
    return [
        {"resource_id": resource_id, "translations": translations}
        for resource_id, translations in grouped.items()
    ]


def _all_languages_update_entry_from_row(row: dict, *, product_gid: str):
    entry = _safe_write_entry_from_row(row, product_gid=product_gid)
    _all_languages_maybe_repair_body_html_forbidden_phrase(
        entry,
        product_gid=product_gid,
    )
    field_key = entry.get("key", "")
    group_key = entry.get("field_group", "")
    source_key = str(entry.get("source_key") or field_key)
    shopify_key = _all_languages_shopify_write_key(entry)
    existing_value = str(entry.get("existing_translation_value") or "")
    proposed_value = str(entry.get("proposed_translation_value") or "")
    existing_current_same = (
        bool(entry.get("existing_translation_present"))
        and not _safe_write_bool(entry.get("existing_translation_outdated"))
        and existing_value.strip()
        and proposed_value.strip()
        and existing_value.strip() == proposed_value.strip()
    )
    if existing_current_same:
        status = "skipped"
        blocking_reasons = ["existing_translation_current_same_value"]
        human_blocking_reasons = ["This field is already up to date."]
        blocking_reason = human_blocking_reasons[0]
    elif _all_languages_media_alt_write_candidate(entry) and (
        not str(entry.get("source_value") or "").strip()
        or not str(entry.get("proposed_translation_value") or "").strip()
    ):
        status = "skipped"
        blocking_reasons = ["media_alt_text_empty"]
        human_blocking_reasons = ["Media alt text is empty."]
        blocking_reason = human_blocking_reasons[0]
    else:
        blocking_reasons = _all_languages_update_blocking_reasons(
            entry,
            product_gid=product_gid,
        )
        human_blocking_reasons = [
            _all_languages_blocking_reason_label_for_entry(reason, entry)
            for reason in blocking_reasons
        ]
        if blocking_reasons:
            status = "blocked"
            blocking_reason = human_blocking_reasons[0]
        else:
            status = "write_ready"
            blocking_reason = ""
            human_blocking_reasons = []
    soft_warning_reasons = _all_languages_update_soft_warning_reasons(entry)
    human_soft_warnings = [
        _all_languages_soft_warning_label(reason)
        for reason in soft_warning_reasons
    ]
    return {
        "entry_id": entry.get("entry_id", ""),
        "locale": entry.get("locale", ""),
        "product_gid": entry.get("product_gid", ""),
        "key": field_key,
        "source_key": source_key,
        "shopify_key": shopify_key,
        "field_group": group_key,
        "resource_id": entry.get("resource_id", ""),
        "resource_type": entry.get("resource_type", ""),
        "digest": entry.get("digest", ""),
        "source_digest": entry.get("source_digest") or entry.get("digest", ""),
        "source_value": entry.get("source_value", ""),
        "previous_translation_value": existing_value,
        "previous_translation_existed": bool(existing_value.strip()),
        "previous_translation_outdated": entry.get("existing_translation_outdated"),
        "proposed_translation_value": proposed_value,
        "manual_edit_used": bool(entry.get("using_manual_edit")),
        "manual_edit_value": entry.get("manual_edit_value", ""),
        "openai_original_proposed_translation": entry.get(
            "openai_original_proposed_translation",
            "",
        ),
        "status": status,
        "blocking_reason": blocking_reason,
        "blocking_reasons": blocking_reasons,
        "human_blocking_reasons": human_blocking_reasons,
        "soft_warning_reasons": soft_warning_reasons,
        "human_soft_warnings": human_soft_warnings,
        "readback_value": "",
        "readback_matched": False,
        "rollback_needed": False,
        "restore_candidate": existing_value,
        "context_label": entry.get("context_label", ""),
        "resource_note": entry.get("resource_note", ""),
        "field_label": entry.get("field_label", ""),
        "option_name": entry.get("option_name", ""),
        "option_value": entry.get("option_value", ""),
        "option_position": entry.get("option_position", ""),
        "visible_product_option": bool(entry.get("visible_product_option")),
        "translation_preview_available": bool(
            entry.get("translation_preview_available")
        ),
        "shopify_update_mapping_ready": bool(
            entry.get("shopify_update_mapping_ready")
        ),
        "translation_preview_without_digest": bool(
            entry.get("translation_preview_without_digest")
        ),
        "selected_options": entry.get("selected_options", []),
        "media_alt": entry.get("media_alt", ""),
        "media_content_type": entry.get("media_content_type", ""),
        "media_url": entry.get("media_url", ""),
        "validation_status": entry.get("validation_status", ""),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "seo_warning": entry.get("seo_warning", ""),
        "source_status": entry.get("status", ""),
        "draft_blocked": bool(entry.get("draft_blocked")),
        "product_identity_mismatch": bool(entry.get("product_identity_mismatch")),
        "body_html_repair_applied": bool(entry.get("body_html_repair_applied")),
        "body_html_repair_attempted": bool(entry.get("body_html_repair_attempted")),
        "body_html_repair_failed_reason": entry.get(
            "body_html_repair_failed_reason",
            "",
        ),
        "body_html_repaired_forbidden_phrases": entry.get(
            "body_html_repaired_forbidden_phrases",
            [],
        ),
        "original_proposed_translation_value": entry.get(
            "original_proposed_translation_value",
            "",
        ),
    }


def _all_languages_update_blocking_reasons(entry: dict, *, product_gid: str):
    reasons = []
    field_key = str(entry.get("key") or "").strip()
    group_key = str(entry.get("field_group") or "").strip()
    locale = _safe_write_canonical_locale(entry.get("locale"))
    resource_id = str(entry.get("resource_id") or "").strip()
    digest = str(entry.get("digest") or "").strip()
    source_value = str(entry.get("source_value") or "").strip()
    proposed_value = str(entry.get("proposed_translation_value") or "").strip()
    option_write_candidate = _all_languages_option_write_candidate(entry)
    media_alt_write_candidate = _all_languages_media_alt_write_candidate(entry)

    if group_key in ALL_LANGUAGES_MAPPING_BLOCKED_GROUPS:
        reasons.append("blocked_future_write_needs_resource_mapping")
    if group_key in SAFE_WRITE_TECHNICAL_GROUPS:
        reasons.append("blocked_not_customer_write_safe")
    if not product_gid:
        reasons.append("blocked_missing_selected_product")
    elif (
        resource_id
        and resource_id != product_gid
        and not option_write_candidate
        and not media_alt_write_candidate
    ):
        reasons.append("blocked_product_gid_mismatch")
    if locale not in LOCKED_EXECUTION_SUPPORTED_LOCALES:
        reasons.append("blocked_target_locale_unsupported")
    if not source_value:
        reasons.append(
            "media_alt_text_empty"
            if media_alt_write_candidate
            else "blocked_source_empty"
        )
    if not proposed_value:
        reasons.append(
            "media_alt_text_empty"
            if media_alt_write_candidate
            else "blocked_proposed_translation_empty"
        )
    if proposed_value and source_value and locale != "en" and proposed_value == source_value:
        reasons.append("blocked_proposed_translation_equals_source")
    if not resource_id:
        reasons.append("blocked_resource_id_missing")
    if not field_key:
        reasons.append("blocked_key_missing")
    if not digest:
        reasons.append("blocked_digest_missing")
    if field_key not in ALL_LANGUAGES_AUTO_WRITE_FIELD_SET:
        reasons.append("blocked_field_not_allowed_for_all_languages_update")
    if not _all_languages_auto_write_group_allowed(group_key):
        reasons.append("blocked_scope_group_not_allowed")
    if option_write_candidate:
        reasons.extend(_all_languages_option_write_blocking_reasons(entry))
    if media_alt_write_candidate:
        reasons.extend(_all_languages_media_alt_write_blocking_reasons(entry))
    if field_key == "title" and len(proposed_value) > 80:
        reasons.append("blocked_product_title_over_80_chars")
    if field_key == "meta_title" and len(proposed_value) > 60:
        reasons.append("blocked_seo_title_over_60_chars")
    if field_key == "meta_description" and len(proposed_value) > 160:
        reasons.append("blocked_seo_description_over_160_chars")
    if (
        _locked_execution_forbidden_phrase_matches(proposed_value)
        or _all_languages_forbidden_phrase_matches(proposed_value)
    ):
        reasons.append("blocked_forbidden_phrase_detected")
    if "forbidden" in _safe_write_issue_text(entry):
        reasons.append("blocked_forbidden_phrase_detected")
    if entry.get("product_identity_mismatch"):
        reasons.append("blocked_identity_review_required")
    reasons.extend(_all_languages_hard_review_blocking_reasons(entry))
    if field_key == "body_html":
        reasons.extend(_all_languages_body_html_blocking_reasons(entry))
    return _unique_strings(reasons)


def _all_languages_auto_write_group_allowed(group_key: str):
    return str(group_key or "").strip() in (
        SAFE_WRITE_READINESS_GROUP_SET | {"options", "media", "media_alt_text"}
    )


def _all_languages_option_write_candidate(entry: dict):
    return (
        str((entry or {}).get("field_group") or "").strip() == "options"
        and str((entry or {}).get("key") or "").strip()
        in ALL_LANGUAGES_OPTION_AUTO_WRITE_FIELDS
    )


def _all_languages_media_alt_write_candidate(entry: dict):
    return (
        str((entry or {}).get("field_group") or "").strip()
        in {"media", "media_alt_text"}
        and str((entry or {}).get("key") or "").strip()
        in ALL_LANGUAGES_MEDIA_ALT_AUTO_WRITE_FIELDS
    )


def _all_languages_option_write_blocking_reasons(entry: dict):
    reasons = []
    resource_id = str(entry.get("resource_id") or "").strip()
    digest = str(entry.get("digest") or entry.get("source_digest") or "").strip()
    field_key = str(entry.get("key") or "").strip()
    shopify_key = _all_languages_option_shopify_key(entry)
    source_value = str(entry.get("source_value") or "").strip()
    proposed_value = str(entry.get("proposed_translation_value") or "").strip()

    if field_key not in ALL_LANGUAGES_OPTION_AUTO_WRITE_FIELDS:
        reasons.append("blocked_field_not_allowed_for_all_languages_update")
    if not resource_id or resource_id.startswith("visible://"):
        reasons.append("blocked_resource_id_missing")
    if shopify_key not in {"name", "value"}:
        reasons.append("blocked_key_missing")
    if not digest or entry.get("translation_preview_without_digest"):
        reasons.append("blocked_digest_missing")
    if field_key == "option.name" and not (
        str(entry.get("option_name") or "").strip()
        or str(entry.get("context_label") or "").strip()
    ):
        reasons.append("blocked_option_context_missing")
    if field_key == "option.value" and not (
        (
            str(entry.get("option_name") or "").strip()
            and str(entry.get("option_value") or "").strip()
        )
        or str(entry.get("context_label") or "").strip()
    ):
        reasons.append("blocked_option_context_missing")
    if source_value and _all_languages_option_translation_code_only(proposed_value):
        reasons.append("blocked_option_translation_code_only")
    return _unique_strings(reasons)


def _all_languages_media_alt_write_blocking_reasons(entry: dict):
    reasons = []
    resource_id = str(entry.get("resource_id") or "").strip()
    digest = str(entry.get("digest") or entry.get("source_digest") or "").strip()
    source_value = str(entry.get("source_value") or "").strip()
    proposed_value = str(entry.get("proposed_translation_value") or "").strip()
    shopify_key = _all_languages_media_alt_shopify_key(entry)

    if not resource_id or resource_id.startswith("visible://"):
        reasons.append("blocked_resource_id_missing")
    if resource_id and not resource_id.startswith("gid://shopify/"):
        reasons.append("blocked_resource_id_missing")
    if shopify_key != "alt":
        reasons.append("blocked_key_missing")
    if not digest or entry.get("translation_preview_without_digest"):
        reasons.append("blocked_digest_missing")
    if not source_value or not proposed_value:
        reasons.append("media_alt_text_empty")
    if proposed_value and not _all_languages_media_alt_customer_facing_value(
        proposed_value
    ):
        reasons.append("blocked_media_alt_not_customer_facing")
    if proposed_value and len(proposed_value) > 125:
        reasons.append("blocked_media_alt_over_125_chars")
    return _unique_strings(reasons)


def _all_languages_option_translation_code_only(value: str):
    text = str(value or "").strip()
    if not text:
        return False
    if len(text) <= 2:
        return True
    if re.fullmatch(r"[\d\s._:/#-]+", text):
        return True
    if re.fullmatch(r"[A-Z0-9][A-Z0-9._:/#-]{1,}", text):
        return True
    return not any(char.isalpha() for char in text)


def _all_languages_media_alt_customer_facing_value(value: str):
    text = str(value or "").strip()
    if not text:
        return False
    lower = text.lower()
    if lower.startswith(("{", "[")) or lower.endswith((".json", ".schema")):
        return False
    if lower in {"sku", "barcode", "id", "image", "img"}:
        return False
    if re.fullmatch(r"[\d\s._:/#-]+", text):
        return False
    return any(char.isalpha() for char in text)


def _all_languages_media_alt_shopify_key(entry: dict):
    source_key = str(
        (entry or {}).get("source_key") or (entry or {}).get("shopify_key") or ""
    ).strip()
    if source_key == "alt":
        return "alt"
    if str((entry or {}).get("key") or "").strip() == "media.alt":
        return "alt"
    return source_key


def _all_languages_shopify_write_key(entry: dict):
    if _all_languages_option_write_candidate(entry):
        return _all_languages_option_shopify_key(entry)
    if _all_languages_media_alt_write_candidate(entry):
        return _all_languages_media_alt_shopify_key(entry)
    return str(
        (entry or {}).get("shopify_key")
        or (entry or {}).get("source_key")
        or (entry or {}).get("key")
        or ""
    ).strip()


def _all_languages_entry_needs_review(entry: dict):
    return bool(_all_languages_hard_review_blocking_reasons(entry))


def _all_languages_hard_review_blocking_reasons(entry: dict):
    field_key = str(entry.get("key") or "").strip()
    codes = _all_languages_entry_review_codes(entry)
    reasons = []
    for code in codes:
        if code == "draft_over_max_chars":
            if field_key == "title":
                reasons.append("blocked_product_title_over_80_chars")
            elif field_key == "meta_title":
                reasons.append("blocked_seo_title_over_60_chars")
            elif field_key == "meta_description":
                reasons.append("blocked_seo_description_over_160_chars")
            else:
                reasons.append("blocked_needs_review_status")
            continue
        mapped_reason = ALL_LANGUAGES_HARD_REVIEW_REASON_MAP.get(code)
        if mapped_reason:
            reasons.append(mapped_reason)
            continue
        if code in ALL_LANGUAGES_SOFT_WARNING_CODES or code in ALL_LANGUAGES_NEUTRAL_REVIEW_CODES:
            continue
        if code in {"draft_needs_manual_review", "draft_needs_review"}:
            reasons.append("blocked_needs_review_status")
            continue
        if code.startswith("blocked_"):
            reasons.append("blocked_needs_review_status")
    validation_status = _all_languages_normalize_review_code(
        entry.get("validation_status")
    )
    if (
        validation_status
        and validation_status not in ALL_LANGUAGES_NEUTRAL_REVIEW_CODES
        and validation_status != "draft_ready_for_manual_review"
        and not _all_languages_review_codes_are_soft_only(codes)
    ):
        reasons.append("blocked_needs_review_status")
    if entry.get("draft_blocked"):
        reasons.append("blocked_needs_review_status")
    return _unique_strings(reasons)


def _all_languages_update_soft_warning_reasons(entry: dict):
    reasons = []
    field_key = str(entry.get("key") or "").strip()
    group_key = str(entry.get("field_group") or "").strip()
    codes = _all_languages_entry_review_codes(entry)
    for code in codes:
        if code in ALL_LANGUAGES_SOFT_WARNING_CODES:
            if code == "future_write_needs_resource_mapping" and group_key in SAFE_WRITE_READINESS_GROUP_SET:
                continue
            reasons.append(code)
    if _safe_write_bool(entry.get("existing_translation_outdated")):
        reasons.append("existing_translation_outdated")
    seo_validation_status = _all_languages_normalize_review_code(
        entry.get("seo_validation_status")
    )
    if (
        field_key in {"meta_title", "meta_description"}
        and seo_validation_status
        and seo_validation_status != "seo_ready"
        and not _all_languages_hard_review_blocking_reasons(entry)
    ):
        reasons.append("seo_could_be_improved")
    if (
        _all_languages_entry_has_needs_review_label(entry)
        and not _all_languages_hard_review_blocking_reasons(entry)
    ):
        reasons.append("needs_review")
    return _unique_strings(reasons)


def _all_languages_review_codes_are_soft_only(codes: list[str]):
    useful_codes = [
        code
        for code in codes or []
        if code and code not in ALL_LANGUAGES_NEUTRAL_REVIEW_CODES
    ]
    if not useful_codes:
        return False
    return all(code in ALL_LANGUAGES_SOFT_WARNING_CODES for code in useful_codes)


def _all_languages_entry_has_needs_review_label(entry: dict):
    for key in ("status", "blocking_reasons", "seo_warning", "seo_validation_status"):
        text = str(entry.get(key) or "").lower()
        if "needs_review" in text or "needs review" in text:
            return True
    return False


def _all_languages_entry_review_codes(entry: dict):
    codes = []
    for key in (
        "seo_warning",
        "blocking_reasons",
        "validation_reasons",
        "validation_status",
        "seo_validation_status",
        "status",
    ):
        for value in _all_languages_split_review_values(entry.get(key)):
            code = _all_languages_normalize_review_code(value)
            if code:
                codes.append(code)
    return _unique_strings(codes)


def _all_languages_split_review_values(value):
    if not value:
        return []
    if isinstance(value, (list, tuple, set)):
        values = []
        for item in value:
            values.extend(_all_languages_split_review_values(item))
        return values
    return [
        item.strip()
        for item in str(value).replace(";", ",").split(",")
        if item.strip()
    ]


def _all_languages_normalize_review_code(value):
    text = str(value or "").strip().lower()
    if not text:
        return ""
    return text.replace("-", "_").replace(" ", "_")


def _all_languages_body_html_blocking_reasons(entry: dict):
    reasons = []
    source_html = str(entry.get("source_value") or "")
    proposed_html = str(entry.get("proposed_translation_value") or "")
    issue_text = _safe_write_issue_text(entry)
    if "body_html_structure_broken" in issue_text:
        reasons.append("blocked_body_html_structure_broken")
    if "html_media_or_link_tag_broken" in issue_text:
        reasons.append("blocked_html_media_or_link_tag_broken")
    html_notes = _all_languages_html_structure_notes(source_html, proposed_html)
    if "body_html_structure_broken" in html_notes:
        reasons.append("blocked_body_html_structure_broken")
    if "html_media_or_link_tag_broken" in html_notes:
        reasons.append("blocked_html_media_or_link_tag_broken")
    return _unique_strings(reasons)


def _all_languages_maybe_repair_body_html_forbidden_phrase(
    entry: dict,
    *,
    product_gid: str,
):
    if str(entry.get("key") or "") != "body_html":
        return
    proposed_html = str(entry.get("proposed_translation_value") or "")
    phrases = _all_languages_repairable_body_html_forbidden_phrase_matches(
        proposed_html
    )
    if not phrases:
        return
    if not _all_languages_body_html_forbidden_phrase_is_only_blocker(
        entry,
        product_gid=product_gid,
    ):
        return

    entry["body_html_repair_attempted"] = True
    repaired_html, repaired_phrases = _all_languages_repair_body_html_html_text(
        proposed_html
    )
    if repaired_html == proposed_html or not repaired_html.strip():
        entry["body_html_repair_failed_reason"] = (
            "Forbidden phrase could not be removed safely."
        )
        return

    repaired_entry = dict(entry)
    repaired_entry["original_proposed_translation_value"] = proposed_html
    repaired_entry["proposed_translation_value"] = repaired_html
    repaired_entry["body_html_repaired_forbidden_phrases"] = repaired_phrases
    _all_languages_clear_repaired_body_html_review_flags(repaired_entry)

    validation_reasons = _all_languages_repaired_body_html_validation_reasons(
        repaired_entry
    )
    if validation_reasons:
        entry["body_html_repair_failed_reason"] = (
            _all_languages_blocking_reason_label(validation_reasons[0])
        )
        return

    final_reasons = _all_languages_update_blocking_reasons(
        repaired_entry,
        product_gid=product_gid,
    )
    if final_reasons:
        entry["body_html_repair_failed_reason"] = (
            _all_languages_blocking_reason_label(final_reasons[0])
        )
        return

    repaired_entry["body_html_repair_applied"] = True
    repaired_entry["body_html_repair_validation_passed"] = True
    repaired_entry["body_html_repair_reason"] = (
        "Forbidden shipping/CTA wording was removed before validation."
    )
    entry.update(repaired_entry)


def _all_languages_body_html_forbidden_phrase_is_only_blocker(
    entry: dict,
    *,
    product_gid: str,
):
    blocking_reasons = _all_languages_update_blocking_reasons(
        entry,
        product_gid=product_gid,
    )
    if not blocking_reasons:
        return False
    if any(
        reason not in ALL_LANGUAGES_BODY_HTML_REPAIRABLE_BLOCKING_REASONS
        for reason in blocking_reasons
    ):
        return False
    return all(
        _all_languages_body_html_review_code_is_repairable(code)
        for code in _all_languages_entry_review_codes(entry)
    )


def _all_languages_body_html_review_code_is_repairable(code: str):
    code = _all_languages_normalize_review_code(code)
    if not code:
        return True
    if code in ALL_LANGUAGES_BODY_HTML_REPAIRABLE_REVIEW_CODES:
        return True
    if code in ALL_LANGUAGES_NEUTRAL_REVIEW_CODES:
        return True
    if code in ALL_LANGUAGES_SOFT_WARNING_CODES:
        return True
    return False


def _all_languages_repair_body_html_html_text(value: str):
    parts = re.split(r"(<[^>]+>)", str(value or ""))
    repaired_parts = []
    repaired_phrases = []
    for index, part in enumerate(parts):
        if index % 2:
            repaired_parts.append(part)
            continue
        repaired_text, phrases = _all_languages_repair_body_html_text_node(part)
        repaired_parts.append(repaired_text)
        for phrase in phrases:
            if phrase not in repaired_phrases:
                repaired_phrases.append(phrase)
    return "".join(repaired_parts), repaired_phrases


def _all_languages_repair_body_html_text_node(value: str):
    text = str(value or "")
    repaired_phrases = []
    for needle, label in ALL_LANGUAGES_BODY_HTML_REPAIRABLE_FORBIDDEN_PHRASE_LABELS:
        while needle in text.lower():
            text = _all_languages_remove_text_around_phrase(text, needle)
            if label not in repaired_phrases:
                repaired_phrases.append(label)
    return _all_languages_normalize_repaired_text_node(text), repaired_phrases


def _all_languages_remove_text_around_phrase(text: str, needle: str):
    lower_text = text.lower()
    start = lower_text.find(needle)
    if start < 0:
        return text
    end = start + len(needle)
    boundaries = ".!?;:\n\r。！？"
    previous = max(text.rfind(boundary, 0, start) for boundary in boundaries)
    next_positions = [
        text.find(boundary, end)
        for boundary in boundaries
        if text.find(boundary, end) >= 0
    ]
    if previous < 0 and not next_positions:
        remove_start = start
        remove_end = end
    else:
        remove_start = previous + 1 if previous >= 0 else 0
        remove_end = (min(next_positions) + 1) if next_positions else end
    return f"{text[:remove_start]} {text[remove_end:]}"


def _all_languages_normalize_repaired_text_node(value: str):
    text = re.sub(r"[ \t]{2,}", " ", str(value or ""))
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    text = re.sub(r"([(\[{])\s+", r"\1", text)
    text = re.sub(r"\s+([)\]}])", r"\1", text)
    return text


def _all_languages_clear_repaired_body_html_review_flags(entry: dict):
    for key in ("blocking_reasons", "seo_warning", "validation_reasons"):
        entry[key] = _all_languages_remove_repaired_forbidden_review_codes(
            entry.get(key)
        )
    for key, ready_value in (
        ("status", "draft_ready_for_manual_review"),
        ("validation_status", "draft_ready_for_manual_review"),
        ("seo_validation_status", "seo_ready"),
    ):
        code = _all_languages_normalize_review_code(entry.get(key))
        if (
            code in ALL_LANGUAGES_BODY_HTML_REPAIRABLE_REVIEW_CODES
            or "forbidden" in code
        ):
            entry[key] = ready_value
    entry["draft_blocked"] = False


def _all_languages_remove_repaired_forbidden_review_codes(value):
    if not value:
        return value
    values = _all_languages_split_review_values(value)
    kept = [
        item
        for item in values
        if not _all_languages_repaired_forbidden_review_code(item)
    ]
    if isinstance(value, (list, tuple, set)):
        return kept
    return ", ".join(kept)


def _all_languages_repaired_forbidden_review_code(value: str):
    code = _all_languages_normalize_review_code(value)
    return code in ALL_LANGUAGES_BODY_HTML_REPAIRABLE_REVIEW_CODES or "forbidden" in code


def _all_languages_repaired_body_html_validation_reasons(entry: dict):
    reasons = []
    proposed_html = str(entry.get("proposed_translation_value") or "")
    if not proposed_html.strip():
        reasons.append("blocked_proposed_translation_empty")
    if _all_languages_forbidden_phrase_matches(proposed_html):
        reasons.append("blocked_forbidden_phrase_detected")
    if _all_languages_repairable_body_html_forbidden_phrase_matches(proposed_html):
        reasons.append("blocked_forbidden_phrase_detected")
    reasons.extend(_all_languages_body_html_blocking_reasons(entry))
    return _unique_strings(reasons)


def _all_languages_html_structure_notes(source_html: str, proposed_html: str):
    source_snapshot = _AllLanguagesHtmlSnapshot.from_html(source_html)
    if not source_snapshot.tag_counts:
        return []
    proposed_snapshot = _AllLanguagesHtmlSnapshot.from_html(proposed_html)
    notes = []
    if not proposed_snapshot.tag_counts:
        return ["body_html_structure_broken"]
    for tag, source_count in source_snapshot.tag_counts.items():
        if proposed_snapshot.tag_counts.get(tag, 0) < source_count:
            notes.append("body_html_structure_broken")
            break
    for tag, source_count in source_snapshot.end_tag_counts.items():
        if proposed_snapshot.end_tag_counts.get(tag, 0) < source_count:
            notes.append("body_html_structure_broken")
            break
    for tag in ALL_LANGUAGES_BODY_HTML_LINK_MEDIA_TAGS:
        if proposed_snapshot.tag_counts.get(tag, 0) < source_snapshot.tag_counts.get(tag, 0):
            notes.append("html_media_or_link_tag_broken")
            break
    for tag, attr_name, attr_value in source_snapshot.link_media_attrs:
        if attr_value and (tag, attr_name, attr_value) not in proposed_snapshot.link_media_attrs:
            notes.append("html_media_or_link_tag_broken")
            break
    return _unique_strings(notes)


class _AllLanguagesHtmlSnapshot(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tag_counts = {}
        self.end_tag_counts = {}
        self.link_media_attrs = []

    @classmethod
    def from_html(cls, value: str):
        parser = cls()
        try:
            parser.feed(str(value or ""))
            parser.close()
        except Exception:
            parser.tag_counts = {}
            parser.end_tag_counts = {}
            parser.link_media_attrs = []
        return parser

    def handle_starttag(self, tag, attrs):
        self._record_tag(tag, attrs)

    def handle_startendtag(self, tag, attrs):
        self._record_tag(tag, attrs)

    def handle_endtag(self, tag):
        tag = str(tag or "").lower()
        if tag:
            self.end_tag_counts[tag] = self.end_tag_counts.get(tag, 0) + 1

    def _record_tag(self, tag, attrs):
        tag = str(tag or "").lower()
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        if tag not in ALL_LANGUAGES_BODY_HTML_LINK_MEDIA_TAGS:
            return
        attrs_dict = {str(key).lower(): str(value or "") for key, value in attrs or []}
        for attr_name in ("href", "src"):
            if attrs_dict.get(attr_name):
                self.link_media_attrs.append((tag, attr_name, attrs_dict[attr_name]))


def _all_languages_blocking_reason_label_for_entry(reason: str, entry: dict | None = None):
    entry = entry or {}
    field_key = str(entry.get("key") or "").strip()
    group_key = str(entry.get("field_group") or "").strip()
    if field_key == "media.alt" and reason == "media_alt_text_empty":
        return "Media alt text is empty."
    if (
        field_key == "body_html"
        and reason not in {"existing_translation_current_same_value"}
    ):
        if reason == "blocked_html_media_or_link_tag_broken":
            return (
                "Product description video, link, or image structure did not match "
                "the original. Review before update."
            )
        if reason == "blocked_body_html_structure_broken":
            return (
                "Product description HTML structure did not match the original. "
                "Review before update."
            )
        return "Product description needs review before automatic Shopify update."
    if reason in {
        "blocked_future_write_needs_resource_mapping",
        "blocked_scope_group_not_allowed",
        "blocked_field_not_allowed_for_all_languages_update",
    }:
        if group_key == "options":
            return "Missing Shopify mapping."
        if group_key == "variants":
            return "Variants are not enabled yet."
        if group_key in {"important_metafields", "metafields", "technical_metafields"}:
            return "This is a technical field and is not updated automatically."
        if group_key in {"media", "media_alt_text"}:
            return "Missing Shopify mapping."
    if (
        field_key in ALL_LANGUAGES_AUTO_WRITE_FIELD_SET
        and reason in {
            "blocked_resource_id_missing",
            "blocked_key_missing",
            "blocked_digest_missing",
            "blocked_option_context_missing",
        }
    ):
        return "Missing Shopify mapping."
    if reason == "blocked_option_translation_code_only":
        return "This is a technical field and is not updated automatically."
    if reason == "blocked_media_alt_not_customer_facing":
        return "Needs review before update."
    if reason == "blocked_media_alt_over_125_chars":
        return "Translation is too long."
    return _all_languages_blocking_reason_label(reason)


def _all_languages_blocking_reason_label(reason: str):
    if reason == "blocked_future_write_needs_resource_mapping":
        return "Missing Shopify mapping."
    labels = {
        "blocked_background_draft_report_not_completed_or_partial": "Needs review before update.",
        "blocked_body_html_auto_update_disabled": "Product description needs review before automatic Shopify update.",
        "blocked_body_html_structure_broken": "Product description HTML structure did not match the original. Review before update.",
        "blocked_digest_missing": "Missing Shopify mapping.",
        "blocked_existing_current_translation": "Already up to date.",
        "blocked_field_not_allowed_for_all_languages_update": "Missing Shopify mapping.",
        "blocked_forbidden_phrase_detected": "Contains blocked wording.",
        "blocked_html_media_or_link_tag_broken": "Product description video, link, or image structure did not match the original. Review before update.",
        "blocked_identity_review_required": "Product/model check failed.",
        "blocked_key_missing": "Missing Shopify mapping.",
        "blocked_media_alt_not_customer_facing": "Needs review before update.",
        "blocked_media_alt_over_125_chars": "Translation is too long.",
        "blocked_missing_background_draft_report": "Needs review before update.",
        "blocked_missing_selected_product": "Select one product before updating Shopify.",
        "blocked_needs_review_status": "Needs review before update.",
        "blocked_no_write_ready_candidates": "Needs review before update.",
        "blocked_not_customer_write_safe": "This is a technical field and is not updated automatically.",
        "blocked_option_context_missing": "Missing Shopify mapping.",
        "blocked_option_translation_code_only": "This is a technical field and is not updated automatically.",
        "blocked_product_gid_mismatch": "Product/model check failed.",
        "blocked_proposed_translation_empty": "Translation is empty.",
        "blocked_proposed_translation_equals_source": "Needs review before update.",
        "blocked_resource_id_missing": "Missing Shopify mapping.",
        "blocked_scope_group_not_allowed": "Missing Shopify mapping.",
        "blocked_selected_product_report_mismatch": "Product/model check failed.",
        "blocked_target_locale_unsupported": "This language is not supported.",
        "blocked_product_title_over_80_chars": "Translation is too long.",
        "blocked_seo_title_over_60_chars": "Translation is too long.",
        "blocked_seo_description_over_160_chars": "Translation is too long.",
        "blocked_shopify_installation_missing": "Shopify installation is missing.",
        "blocked_shopify_installation_incomplete": "Shopify installation is incomplete.",
        "blocked_source_empty": "Translation is empty.",
        "existing_translation_current_same_value": "Already up to date.",
        "media_alt_text_empty": "Media alt text is empty.",
        "readback_mismatch": "Shopify confirmation check did not match.",
        "translations_register_failed": "Needs review before update.",
    }
    return labels.get(reason, reason)


def _all_languages_state_blocking_conditions(
    *,
    report: dict,
    product_gid: str,
    report_product_gid: str,
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
    return _unique_strings(conditions)


def _all_languages_apply_global_blockers(entries: list[dict], blockers: list[str]):
    blocker = _unique_strings(blockers)[0] if blockers else ""
    if not blocker:
        return
    for entry in entries or []:
        if entry.get("status") != "write_ready":
            continue
        entry["status"] = "blocked"
        entry["blocking_reasons"] = _unique_strings(
            list(entry.get("blocking_reasons") or []) + [blocker]
        )
        entry["human_blocking_reasons"] = [
            _all_languages_blocking_reason_label_for_entry(reason, entry)
            for reason in entry.get("blocking_reasons") or []
        ]
        entry["blocking_reason"] = (
            entry["human_blocking_reasons"][0]
            if entry["human_blocking_reasons"]
            else _all_languages_blocking_reason_label(blocker)
        )


def _all_languages_request_blocking_conditions(*, write_ready_entries: list[dict], installation):
    conditions = []
    if not write_ready_entries:
        conditions.append("blocked_no_write_ready_candidates")
    if installation is None:
        conditions.append("blocked_shopify_installation_missing")
    elif not getattr(installation, "shop", "") or not getattr(
        installation,
        "access_token",
        "",
    ):
        conditions.append("blocked_shopify_installation_incomplete")
    return _unique_strings(conditions)


def _all_languages_entry_status_count(entries: list[dict], *statuses: str):
    status_set = set(statuses)
    return sum(1 for entry in entries or [] if entry.get("status") in status_set)


def _all_languages_entry_soft_warning_count(entries: list[dict]):
    return sum(1 for entry in entries or [] if entry.get("soft_warning_reasons"))


def _all_languages_per_locale_summary(entries: list[dict], report: dict | None = None):
    report = report or {}
    locale_statuses = {
        _safe_write_canonical_locale(row.get("locale")): row
        for row in (report.get("per_locale_status") or [])
        if isinstance(row, dict)
    }
    summary = []
    for locale in ALL_LANGUAGES_SUPPORTED_LOCALES:
        locale_entries = [entry for entry in entries or [] if entry.get("locale") == locale]
        locale_status = locale_statuses.get(locale) or {}
        row = {
            "locale": locale,
            "language_label": _all_languages_locale_label(locale),
            "candidate_count": len(locale_entries),
            "write_ready_count": _all_languages_entry_status_count(
                locale_entries,
                "write_ready",
            ),
            "updated_count": _all_languages_entry_status_count(
                locale_entries,
                "written_verified",
                "readback_mismatch",
            ),
            "verified_count": _all_languages_entry_status_count(
                locale_entries,
                "written_verified",
            ),
            "skipped_count": _all_languages_entry_status_count(
                locale_entries,
                "skipped",
            ),
            "blocked_count": _all_languages_entry_status_count(
                locale_entries,
                "blocked",
            ),
            "review_note_count": _all_languages_entry_soft_warning_count(locale_entries),
            "failed_count": _all_languages_entry_status_count(
                locale_entries,
                "write_failed",
                "readback_mismatch",
            ),
            "report_locale_status": locale_status.get("status", ""),
            "blocking_reasons": _all_languages_reason_counts(locale_entries),
        }
        updated_field_labels = _all_languages_updated_field_labels(locale_entries)
        confirmed_field_labels = _all_languages_updated_field_labels(
            locale_entries,
            confirmed_only=True,
        )
        row["updated_field_labels"] = updated_field_labels
        row["confirmed_field_labels"] = confirmed_field_labels
        row["updated_fields_label"] = _all_languages_join_labels(updated_field_labels)
        row["confirmed_fields_label"] = _all_languages_join_labels(confirmed_field_labels)
        row["all_updated_fields_confirmed"] = bool(updated_field_labels) and (
            row["updated_count"] == row["verified_count"]
        )
        row["success_summary_text"] = _all_languages_locale_success_summary_text(row)
        if not locale_entries:
            row["blocking_reasons"].append(
                {"reason": "blocked_no_report_rows_for_locale", "count": 1}
            )
        elif (
            locale_status
            and locale_status.get("status") not in {"completed", "partial", "skipped"}
            and not row["write_ready_count"]
        ):
            row["blocking_reasons"].append(
                {"reason": "blocked_locale_report_not_complete", "count": 1}
            )
        summary.append(row)
    return summary


def _all_languages_per_field_summary(entries: list[dict]):
    field_order = list(ALL_LANGUAGES_AUTO_WRITE_FIELDS) + [
        "options",
        "variants",
        "metafields",
        "media_alt_text",
        "technical_fields",
    ]
    grouped = {}
    for entry in entries or []:
        key = entry.get("key") or entry.get("field_group") or "unknown"
        if entry.get("field_group") in ALL_LANGUAGES_MAPPING_BLOCKED_GROUPS:
            key = entry.get("field_group")
        grouped.setdefault(key, []).append(entry)
    fields = list(dict.fromkeys(field_order + sorted(grouped)))
    return [
        {
            "field": field,
            "candidate_count": len(grouped.get(field) or []),
            "write_ready_count": _all_languages_entry_status_count(
                grouped.get(field) or [],
                "write_ready",
            ),
            "updated_count": _all_languages_entry_status_count(
                grouped.get(field) or [],
                "written_verified",
                "readback_mismatch",
            ),
            "verified_count": _all_languages_entry_status_count(
                grouped.get(field) or [],
                "written_verified",
            ),
            "skipped_count": _all_languages_entry_status_count(
                grouped.get(field) or [],
                "skipped",
            ),
            "blocked_count": _all_languages_entry_status_count(
                grouped.get(field) or [],
                "blocked",
            ),
            "review_note_count": _all_languages_entry_soft_warning_count(
                grouped.get(field) or []
            ),
            "failed_count": _all_languages_entry_status_count(
                grouped.get(field) or [],
                "write_failed",
                "readback_mismatch",
            ),
        }
        for field in fields
        if grouped.get(field)
    ]


def _all_languages_reason_counts(entries: list[dict]):
    counts = {}
    for entry in entries or []:
        for reason in entry.get("blocking_reasons") or []:
            if not reason:
                continue
            counts[reason] = counts.get(reason, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _all_languages_attach_plain_language(payload: dict):
    _all_languages_recount_payload(payload)
    entries = payload.get("entries") or []
    for entry in entries:
        _all_languages_refresh_entry_human_reasons(entry)
        entry["field_label"] = entry.get("field_label") or _all_languages_field_label(
            entry.get("key", "")
        )
        entry["language_label"] = _all_languages_locale_label(entry.get("locale", ""))
        entry["confirmed_label"] = (
            "Yes" if _all_languages_entry_confirmed(entry) else "No"
        )
        _all_languages_attach_entry_diagnostic_flags(entry)
    payload["status_label"] = _all_languages_status_label(payload)
    payload["result_message"] = _all_languages_result_message(payload)
    payload["shopify_update_label"] = (
        "Shopify was updated"
        if payload.get("shopify_write_performed")
        else "Shopify was not updated"
    )
    payload["shopify_confirmation_check_label"] = (
        "Confirmation check was run"
        if payload.get("readback_performed")
        else "Confirmation check was not run"
    )
    payload["restore_needed_label"] = (
        "Restore may be needed"
        if payload.get("rollback_needed")
        else "Restore is not needed"
    )
    payload["blocked_reason_summary"] = _all_languages_blocked_reason_summary(
        entries,
        payload.get("blocking_conditions") or [],
    )
    payload["is_successfully_updated"] = _all_languages_successfully_updated(payload)
    payload["ready_count_label"] = (
        "Ready before update"
        if int(payload.get("updated_count") or 0) > 0
        else "Ready to update"
    )
    payload["show_ready_count_in_main_summary"] = (
        int(payload.get("updated_count") or 0) <= 0
    )
    payload["not_updated_explanation"] = _all_languages_not_updated_explanation(payload)
    payload["not_updated_breakdown"] = _all_languages_not_updated_breakdown(entries)
    payload["german_body_html_diagnostic"] = (
        _all_languages_german_body_html_diagnostic(entries)
    )
    payload["needs_review_rows"] = _all_languages_needs_review_rows(entries)
    payload["option_mapping_audit"] = _all_languages_option_mapping_audit(entries)
    payload["media_alt_mapping_audit"] = _all_languages_media_alt_mapping_audit(
        entries
    )
    payload["translation_readiness_audit"] = (
        _all_languages_translation_readiness_audit(
            entries,
            payload.get("option_mapping_audit") or {},
            payload.get("media_alt_mapping_audit") or {},
        )
    )
    payload["next_enablement_summary"] = _all_languages_next_enablement_summary(
        entries,
        payload.get("option_mapping_audit") or {},
        payload.get("german_body_html_diagnostic") or {},
    )
    payload["updated_entries"] = _all_languages_updated_entries_display(entries)
    payload["updated_field_labels"] = _all_languages_updated_field_labels(entries)
    payload["successful_locale_summaries"] = (
        _all_languages_successful_locale_summaries(entries)
    )
    safe_diagnostics, safe_summary = _all_languages_safe_field_diagnostics(entries)
    payload["safe_field_diagnostics"] = safe_diagnostics
    payload["safe_field_diagnostic_summary"] = safe_summary
    return payload


def _all_languages_recount_payload(payload: dict):
    entries = payload.get("entries") or []
    if not isinstance(entries, list):
        entries = []
        payload["entries"] = entries
    payload["candidate_count"] = len(entries)
    payload["write_ready_count"] = _all_languages_entry_status_count(
        entries,
        "write_ready",
    )
    payload["updated_count"] = _all_languages_entry_status_count(
        entries,
        "written_verified",
        "readback_mismatch",
    )
    payload["verified_count"] = _all_languages_entry_status_count(
        entries,
        "written_verified",
    )
    payload["skipped_count"] = _all_languages_entry_status_count(entries, "skipped")
    payload["blocked_count"] = _all_languages_entry_status_count(entries, "blocked")
    payload["review_note_count"] = _all_languages_entry_soft_warning_count(entries)
    payload["failed_count"] = _all_languages_entry_status_count(
        entries,
        "write_failed",
        "readback_mismatch",
    )
    payload["write_failed_count"] = _all_languages_entry_status_count(
        entries,
        "write_failed",
    )
    payload["not_updated_count"] = (
        int(payload.get("skipped_count") or 0)
        + int(payload.get("blocked_count") or 0)
        + int(payload.get("write_failed_count") or 0)
    )
    payload["readback_verified_count"] = payload.get("verified_count", 0)
    payload["product_title_updated_count"] = sum(
        1
        for entry in entries
        if entry.get("key") == "title" and _all_languages_entry_updated(entry)
    )
    payload["product_title_confirmed_count"] = sum(
        1
        for entry in entries
        if entry.get("key") == "title" and _all_languages_entry_confirmed(entry)
    )
    payload["seo_updated_count"] = sum(
        1
        for entry in entries
        if entry.get("key") in {"meta_title", "meta_description"}
        and _all_languages_entry_updated(entry)
    )
    payload["seo_confirmed_count"] = sum(
        1
        for entry in entries
        if entry.get("key") in {"meta_title", "meta_description"}
        and _all_languages_entry_confirmed(entry)
    )
    payload["product_options_updated_count"] = sum(
        1
        for entry in entries
        if _all_languages_option_write_candidate(entry)
        and _all_languages_entry_updated(entry)
    )
    payload["product_options_confirmed_count"] = sum(
        1
        for entry in entries
        if _all_languages_option_write_candidate(entry)
        and _all_languages_entry_confirmed(entry)
    )
    payload["options_updated_count"] = payload["product_options_updated_count"]
    payload["options_confirmed_count"] = payload["product_options_confirmed_count"]
    payload["product_descriptions_updated_count"] = sum(
        1
        for entry in entries
        if entry.get("key") == "body_html" and _all_languages_entry_updated(entry)
    )
    payload["product_descriptions_confirmed_count"] = sum(
        1
        for entry in entries
        if entry.get("key") == "body_html" and _all_languages_entry_confirmed(entry)
    )
    payload["body_html_updated_count"] = payload["product_descriptions_updated_count"]
    payload["body_html_confirmed_count"] = payload[
        "product_descriptions_confirmed_count"
    ]
    payload["media_alt_updated_count"] = sum(
        1
        for entry in entries
        if _all_languages_media_alt_write_candidate(entry)
        and _all_languages_entry_updated(entry)
    )
    payload["media_alt_confirmed_count"] = sum(
        1
        for entry in entries
        if _all_languages_media_alt_write_candidate(entry)
        and _all_languages_entry_confirmed(entry)
    )
    payload["skipped_empty_count"] = sum(
        1
        for entry in entries
        if entry.get("status") == "skipped"
        and "media_alt_text_empty" in (entry.get("blocking_reasons") or [])
    )
    payload["per_locale_summary"] = _all_languages_per_locale_summary(entries)
    payload["per_field_summary"] = _all_languages_per_field_summary(entries)
    return payload


def _all_languages_status_label(payload: dict):
    status = str(payload.get("status") or "")
    return ALL_LANGUAGES_STATUS_LABELS.get(status, _all_languages_blocking_reason_label(status))


def _all_languages_result_message(payload: dict):
    if payload.get("status") == "all_languages_shopify_update_not_submitted":
        return "No Shopify update has been run yet."
    if not payload.get("report_exists"):
        return "No Shopify update has been run yet."
    updated_count = int(payload.get("updated_count") or 0)
    verified_count = int(payload.get("verified_count") or 0)
    failed_count = int(payload.get("failed_count") or 0)
    blocked_count = int(payload.get("blocked_count") or 0)
    skipped_count = int(payload.get("skipped_count") or 0)
    if updated_count > 0 and verified_count == updated_count and failed_count == 0:
        return (
            f"Shopify updated successfully. {verified_count} translations updated "
            "and confirmed."
        )
    if updated_count > 0 and (failed_count > 0 or verified_count != updated_count):
        return (
            "Some translations were not updated because they need review or are not "
            "enabled for automatic update yet."
        )
    if updated_count == 0 and blocked_count > 0:
        return (
            "Some translations were not updated because they need review or are not "
            "enabled for automatic update yet."
        )
    if updated_count == 0 and skipped_count > 0:
        return "No Shopify update was needed. Safe translations are already up to date."
    return "No Shopify update has been run yet."


def _all_languages_successfully_updated(payload: dict):
    updated_count = int(payload.get("updated_count") or 0)
    verified_count = int(payload.get("verified_count") or 0)
    return (
        payload.get("status") == ALL_LANGUAGES_WRITTEN_AND_VERIFIED_STATUS
        and bool(payload.get("shopify_write_performed"))
        and bool(payload.get("readback_performed"))
        and updated_count > 0
        and verified_count == updated_count
        and not payload.get("rollback_needed")
    )


def _all_languages_not_updated_explanation(payload: dict):
    not_updated_count = int(payload.get("not_updated_count") or 0)
    if not_updated_count <= 0:
        return ""
    return (
        "Some translations were not updated because they need review or are not "
        "enabled for automatic update yet."
    )


def _all_languages_not_updated_breakdown(entries: list[dict]):
    counts = {}
    for entry in entries or []:
        if entry.get("status") not in {"blocked", "skipped", "write_failed"}:
            continue
        labels = entry.get("human_blocking_reasons") or []
        label = str(labels[0] if labels else entry.get("blocking_reason") or "").strip()
        if not label:
            label = "Needs review before update."
        counts[label] = counts.get(label, 0) + 1
    return [
        {
            "label": label,
            "count": count,
            "plain_reason": _all_languages_not_updated_category_reason(label),
        }
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _all_languages_not_updated_category_reason(label: str):
    label = str(label or "")
    if label == "Product description needs review before automatic Shopify update.":
        return "The proposed product description needs manual review before it can be written."
    if label == "Missing Shopify mapping.":
        return "Rows update only when resource ID, key, digest, and readback mapping are present."
    if label == "This is a technical field and is not updated automatically.":
        return "Technical fields are skipped by the automatic Shopify update."
    if label == "Variants are not enabled yet.":
        return "Variant translations stay preview-only until real variant rows and mapping are proven safe."
    if label == "Media alt text is empty.":
        return "Empty media alt text is skipped and is not treated as an error."
    if label == "Translation is empty.":
        return "No proposed translation was generated for this field."
    if label == "Needs review before update.":
        return "This row is outside the automatic customer-facing write scope or needs manual review."
    if label == "Already up to date.":
        return "Shopify already has the same current value."
    return label


def _all_languages_attach_entry_diagnostic_flags(entry: dict):
    if entry.get("field_group") != "options":
        return
    audit = _all_languages_option_mapping_row(entry)
    entry["option_mapping_safe"] = audit.get("mapping_safe", False)
    entry["option_future_update_ready"] = audit.get("future_update_ready", False)
    entry["option_mapping_plain_reason"] = audit.get("plain_reason", "")


def _all_languages_german_body_html_diagnostic(entries: list[dict]):
    entry = next(
        (
            item
            for item in entries or []
            if _safe_write_canonical_locale(item.get("locale")) == "de"
            and str(item.get("key") or "") == "body_html"
        ),
        None,
    )
    if not entry:
        return {
            "exists": False,
            "plain_reason": "German product description was not found in this report.",
            "blocker_category_label": "Other",
            "blocker_categories": ["other"],
        }
    categories = _all_languages_body_html_blocker_categories(entry)
    labels = [
        _all_languages_body_html_blocker_label(category) for category in categories
    ]
    forbidden_phrases = _all_languages_forbidden_phrase_matches(
        entry.get("proposed_translation_value", "")
    )
    primary = labels[0] if labels else "Other"
    plain_reason = _all_languages_german_body_html_plain_reason(
        entry,
        categories,
        forbidden_phrases,
    )
    return {
        "exists": True,
        "locale": "de",
        "language_label": _all_languages_locale_label("de"),
        "key": "body_html",
        "field_label": _all_languages_field_label("body_html"),
        "status": entry.get("status", ""),
        "blocking_reason": entry.get("blocking_reason", ""),
        "blocking_reasons": entry.get("blocking_reasons") or [],
        "human_blocking_reasons": entry.get("human_blocking_reasons") or [],
        "soft_warning_reasons": entry.get("soft_warning_reasons") or [],
        "human_soft_warnings": entry.get("human_soft_warnings") or [],
        "validation_status": entry.get("validation_status", ""),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "digest_present": bool(str(entry.get("digest") or "").strip()),
        "proposed_translation_present": bool(
            str(entry.get("proposed_translation_value") or "").strip()
        ),
        "blocker_categories": categories,
        "blocker_category_labels": labels,
        "blocker_category_label": primary,
        "html_structure_issue": "html_structure_issue" in categories,
        "link_image_video_mismatch": "link_image_video_mismatch" in categories,
        "forbidden_phrase": "forbidden_phrase" in categories,
        "identity_mismatch": "identity_mismatch" in categories,
        "empty_or_missing_digest": "empty_or_missing_digest" in categories,
        "other": "other" in categories,
        "found_forbidden_phrases": forbidden_phrases,
        "repair_applied": bool(entry.get("body_html_repair_applied")),
        "repair_attempted": bool(entry.get("body_html_repair_attempted")),
        "repair_failed_reason": entry.get("body_html_repair_failed_reason", ""),
        "repaired_forbidden_phrases": entry.get(
            "body_html_repaired_forbidden_phrases",
            [],
        ),
        "plain_reason": plain_reason,
    }


def _all_languages_body_html_blocker_categories(entry: dict):
    reasons = set(entry.get("blocking_reasons") or [])
    codes = set(_all_languages_entry_review_codes(entry))
    categories = []
    if (
        "blocked_body_html_structure_broken" in reasons
        or "body_html_structure_broken" in codes
    ):
        categories.append("html_structure_issue")
    if (
        "blocked_html_media_or_link_tag_broken" in reasons
        or "html_media_or_link_tag_broken" in codes
    ):
        categories.append("link_image_video_mismatch")
    if (
        "blocked_forbidden_phrase_detected" in reasons
        or "forbidden_marketing_or_origin_phrase" in codes
        or "forbidden_marketing_or_shipping_phrase" in codes
        or _all_languages_forbidden_phrase_matches(
            entry.get("proposed_translation_value", "")
        )
    ):
        categories.append("forbidden_phrase")
    if (
        "blocked_identity_review_required" in reasons
        or "product_identity_mismatch" in codes
        or entry.get("product_identity_mismatch")
    ):
        categories.append("identity_mismatch")
    if (
        "blocked_proposed_translation_empty" in reasons
        or "blocked_digest_missing" in reasons
        or not str(entry.get("proposed_translation_value") or "").strip()
        or not str(entry.get("digest") or "").strip()
    ):
        categories.append("empty_or_missing_digest")
    if not categories and entry.get("status") in {"blocked", "write_failed"}:
        categories.append("other")
    if not categories and entry.get("body_html_repair_applied"):
        categories.append("repaired")
    return _unique_strings(categories)


def _all_languages_body_html_blocker_label(category: str):
    labels = {
        "html_structure_issue": "HTML structure issue",
        "link_image_video_mismatch": "Link/image/video mismatch",
        "forbidden_phrase": "Forbidden phrase",
        "identity_mismatch": "Identity mismatch",
        "empty_or_missing_digest": "Empty translation or missing digest",
        "repaired": "Forbidden phrase repaired",
        "other": "Other",
    }
    return labels.get(category, "Other")


def _all_languages_german_body_html_plain_reason(
    entry: dict,
    categories: list[str],
    forbidden_phrases: list[str],
):
    if entry.get("body_html_repair_applied"):
        repaired = entry.get("body_html_repaired_forbidden_phrases") or forbidden_phrases
        phrase_text = f": {', '.join(repaired)}" if repaired else ""
        if entry.get("status") == "written_verified":
            return (
                "German product description had forbidden shipping/CTA wording removed "
                f"before update{phrase_text}; Shopify confirmed the repaired HTML."
            )
        return (
            "German product description had forbidden shipping/CTA wording removed "
            f"and HTML validation passed{phrase_text}."
        )
    if "forbidden_phrase" in categories:
        phrase_text = (
            f": {', '.join(forbidden_phrases)}" if forbidden_phrases else ""
        )
        return (
            "German product description was blocked for forbidden marketing, "
            f"shipping, or origin wording{phrase_text}."
        )
    if "html_structure_issue" in categories:
        return "German product description was blocked because the HTML structure did not match the source."
    if "link_image_video_mismatch" in categories:
        return "German product description was blocked because links, images, or video tags did not match the source."
    if "identity_mismatch" in categories:
        return "German product description was blocked because the product/model identity check failed."
    if "empty_or_missing_digest" in categories:
        return "German product description was blocked because the translation or Shopify digest was missing."
    return (
        entry.get("blocking_reason")
        or "German product description was blocked for manual review."
    )


def _all_languages_forbidden_phrase_matches(value: str):
    text = str(value or "").lower()
    matches = []
    for needle, label in ALL_LANGUAGES_FORBIDDEN_PHRASE_LABELS:
        if needle in text and label not in matches:
            matches.append(label)
    return matches


def _all_languages_repairable_body_html_forbidden_phrase_matches(value: str):
    text = str(value or "").lower()
    matches = []
    for needle, label in ALL_LANGUAGES_BODY_HTML_REPAIRABLE_FORBIDDEN_PHRASE_LABELS:
        if needle in text and label not in matches:
            matches.append(label)
    return matches


def _all_languages_needs_review_rows(entries: list[dict]):
    rows = []
    for entry in entries or []:
        if entry.get("status") != "blocked":
            continue
        labels = entry.get("human_blocking_reasons") or []
        first_label = str(
            labels[0] if labels else entry.get("blocking_reason") or ""
        ).strip()
        if first_label != "Needs review before update.":
            continue
        rows.append(
            {
                "locale": entry.get("locale", ""),
                "language_label": _all_languages_locale_label(entry.get("locale", "")),
                "key": entry.get("key", ""),
                "field_label": entry.get("field_label")
                or _all_languages_field_label(entry.get("key", "")),
                "context_label": entry.get("context_label", ""),
                "field_group": entry.get("field_group", ""),
                "resource_id": entry.get("resource_id", ""),
                "digest": entry.get("digest", ""),
                "plain_reason": _all_languages_needs_review_plain_reason(entry),
                "blocking_reasons": entry.get("blocking_reasons") or [],
            }
        )
    return rows


def _all_languages_needs_review_plain_reason(entry: dict):
    group_key = str(entry.get("field_group") or "")
    key = str(entry.get("key") or "")
    proposed_value = str(entry.get("proposed_translation_value") or "").strip()
    if group_key == "technical_metafields":
        if not proposed_value:
            return "Technical/internal metafield; no automatic translation was generated, so it stays manual-review only."
        return "This is a technical field and is not updated automatically."
    if group_key in {"important_metafields", "metafields"}:
        return "Metafield update support needs explicit mapping before Shopify writes are safe."
    if key == "product_type":
        return "Product type is outside the current automatic all-language write scope."
    if key == "handle":
        return "URL handle updates require manual review and are outside the automatic write scope."
    if not proposed_value:
        return "No proposed translation was generated for this row."
    return entry.get("blocking_reason") or "Manual review is required before update."


def _all_languages_option_mapping_audit(entries: list[dict]):
    rows = [
        _all_languages_option_mapping_row(entry)
        for entry in entries or []
        if entry.get("field_group") == "options"
    ]
    mapping_safe_count = sum(1 for row in rows if row.get("mapping_safe"))
    future_ready_count = sum(1 for row in rows if row.get("future_update_ready"))
    blocked_count = len(rows) - future_ready_count
    all_future_ready = bool(rows) and future_ready_count == len(rows)
    if all_future_ready:
        plain_summary = (
            f"Options mapping is safe for {future_ready_count} row(s). "
            "They are included in the automatic Shopify update."
        )
    elif rows:
        plain_summary = (
            f"Options mapping is incomplete for {blocked_count} of {len(rows)} row(s); "
            "keep option writes blocked until those rows have resource ID, key, digest, and option context."
        )
    else:
        plain_summary = "No option rows were found in this report."
    return {
        "row_count": len(rows),
        "mapping_safe_count": mapping_safe_count,
        "future_update_ready_count": future_ready_count,
        "blocked_count": blocked_count,
        "all_future_update_ready": all_future_ready,
        "plain_summary": plain_summary,
        "rows": rows,
    }


def _all_languages_option_mapping_row(entry: dict):
    display_key = str(entry.get("key") or "")
    shopify_key = _all_languages_option_shopify_key(entry)
    resource_id = str(entry.get("resource_id") or "").strip()
    digest = str(entry.get("digest") or entry.get("source_digest") or "").strip()
    option_name = str(entry.get("option_name") or "").strip()
    option_value = str(entry.get("option_value") or "").strip()
    context_label = str(entry.get("context_label") or "").strip()
    missing = []
    if not resource_id or resource_id.startswith("visible://"):
        missing.append("resource_id")
    if shopify_key not in {"name", "value"}:
        missing.append("key")
    if not digest or entry.get("translation_preview_without_digest"):
        missing.append("digest")
    if display_key == "option.name" and not (option_name or context_label):
        missing.append("option name context")
    if display_key == "option.value" and not (
        (option_name and option_value) or context_label
    ):
        missing.append("option value context")
    mapping_safe = not missing
    status_ready = entry.get("status") in {
        "write_ready",
        "written_verified",
        "readback_mismatch",
    }
    draft_ready = (
        (
            status_ready
            or str(entry.get("validation_status") or "")
            == "draft_ready_for_manual_review"
        )
        and str(entry.get("seo_validation_status") or "") in {"", "seo_ready"}
        and bool(str(entry.get("proposed_translation_value") or "").strip())
        and not entry.get("draft_blocked")
        and not entry.get("product_identity_mismatch")
        and not _all_languages_option_translation_code_only(
            entry.get("proposed_translation_value", "")
        )
        and not _all_languages_forbidden_phrase_matches(
            entry.get("proposed_translation_value", "")
        )
    )
    future_update_ready = mapping_safe and draft_ready
    if future_update_ready:
        plain_reason = (
            "Mapping exists: resource_id, Shopify key, digest, and option context are present."
        )
    elif missing:
        plain_reason = f"Keep blocked: missing {', '.join(missing)}."
    elif _all_languages_option_translation_code_only(
        entry.get("proposed_translation_value", "")
    ):
        plain_reason = "Keep blocked: proposed option translation is technical/code-only."
    elif _all_languages_forbidden_phrase_matches(
        entry.get("proposed_translation_value", "")
    ):
        plain_reason = "Keep blocked: proposed option translation contains blocked wording."
    else:
        plain_reason = "Keep blocked: translation draft still needs review."
    return {
        "locale": entry.get("locale", ""),
        "language_label": _all_languages_locale_label(entry.get("locale", "")),
        "field": display_key,
        "field_label": ALL_LANGUAGES_OPTION_FIELD_LABELS.get(
            display_key,
            entry.get("field_label") or _all_languages_field_label(display_key),
        ),
        "resource_id": resource_id,
        "key": shopify_key,
        "display_key": display_key,
        "digest": digest,
        "option_name": option_name,
        "option_value": option_value,
        "option_position": entry.get("option_position", ""),
        "context_label": context_label,
        "resource_note": entry.get("resource_note", ""),
        "mapping_safe": mapping_safe,
        "future_update_ready": future_update_ready,
        "mapping_status_label": "Safe mapping" if mapping_safe else "Mapping incomplete",
        "future_update_ready_label": "Update-ready" if future_update_ready else "Keep blocked",
        "missing_mapping_parts": missing,
        "validation_status": entry.get("validation_status", ""),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "plain_reason": plain_reason,
    }


def _all_languages_media_alt_mapping_audit(entries: list[dict]):
    rows = [
        _all_languages_media_alt_mapping_row(entry)
        for entry in entries or []
        if _all_languages_media_alt_entry(entry)
    ]
    classification_counts = {}
    for row in rows:
        classification = row.get("classification", "")
        classification_counts[classification] = classification_counts.get(classification, 0) + 1
    safe_mapping_count = sum(1 for row in rows if row.get("mapping_safe"))
    write_ready_count = sum(
        1 for row in rows if row.get("classification") == "media_alt_write_ready"
    )
    skipped_empty_count = sum(
        1 for row in rows if row.get("classification") == "media_alt_empty_translation"
    )
    registration_input_ready_count = sum(
        1 for row in rows if row.get("registration_input_ready")
    )
    readback_method_available_count = sum(
        1 for row in rows if row.get("readback_method_available")
    )
    all_mapping_safe = bool(rows) and safe_mapping_count == len(rows)
    if not rows:
        plain_summary = "No media alt text rows were found in this update report."
        recommendation = "Keep Media alt text preview-only until real rows are sampled."
    elif (
        write_ready_count + skipped_empty_count == len(rows)
        and registration_input_ready_count == write_ready_count
        and readback_method_available_count >= write_ready_count
    ):
        plain_summary = (
            f"{write_ready_count} media alt row(s) have real media resource IDs, "
            "alt keys, digests, source text, proposed text, and a readback path. "
            f"{skipped_empty_count} empty row(s) will be skipped."
        )
        recommendation = "Media alt text is enabled for automatic Shopify update when validation passes."
    else:
        plain_summary = (
            "Keep unsafe Media alt text rows preview-only: at least one row is missing "
            "safe mapping, digest, proposed text, or readback mapping."
        )
        recommendation = "Only mapped, non-empty media alt rows are enabled."
    return {
        "row_count": len(rows),
        "classification_counts": [
            {"classification": key, "count": value}
            for key, value in sorted(
                classification_counts.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ],
        "safe_mapping_count": safe_mapping_count,
        "write_ready_count": write_ready_count,
        "skipped_empty_count": skipped_empty_count,
        "registration_input_ready_count": registration_input_ready_count,
        "readback_method_available_count": readback_method_available_count,
        "all_sampled_rows_mapping_safe": all_mapping_safe,
        "plain_summary": plain_summary,
        "recommendation": recommendation,
        "rows": rows,
    }


def _all_languages_media_alt_mapping_row(entry: dict):
    resource_id = str(entry.get("resource_id") or "").strip()
    source_key = str(
        entry.get("source_key") or entry.get("shopify_key") or entry.get("key") or ""
    ).strip()
    digest = str(entry.get("digest") or entry.get("source_digest") or "").strip()
    source_value = str(entry.get("source_value") or "").strip()
    proposed_value = str(entry.get("proposed_translation_value") or "").strip()
    resource_type = _all_languages_shopify_gid_type(resource_id) or str(
        entry.get("resource_type") or ""
    ).strip()
    key_exists = source_key == "alt" or str(entry.get("key") or "") == "media.alt"
    real_gid = resource_id.startswith("gid://shopify/")
    maps_to_media = resource_type in {"MediaImage", "Image"} and key_exists
    mapping_safe = real_gid and maps_to_media
    registration_input_ready = (
        mapping_safe and bool(digest) and key_exists and bool(source_value) and bool(proposed_value)
    )
    readback_method_available = (
        mapping_safe
        and _safe_write_canonical_locale(entry.get("locale"))
        in LOCKED_EXECUTION_SUPPORTED_LOCALES
    )
    if not mapping_safe or not key_exists:
        classification = "media_alt_missing_mapping"
    elif not digest:
        classification = "media_alt_missing_digest"
    elif not source_value or not proposed_value:
        classification = "media_alt_empty_translation"
    elif _all_languages_entry_needs_review(entry):
        classification = "media_alt_needs_review"
    elif str(entry.get("status") or "") == "blocked":
        classification = "media_alt_update_not_enabled"
    else:
        classification = "media_alt_write_ready"
    return {
        "locale": entry.get("locale", ""),
        "language_label": _all_languages_locale_label(entry.get("locale", "")),
        "media_resource_type": resource_type,
        "resource_id": resource_id,
        "resource_id_exists": bool(resource_id),
        "resource_id_is_real_shopify_gid": real_gid,
        "resource_id_is_visible_or_local_only": resource_id.startswith("visible://"),
        "key": "alt" if key_exists else source_key,
        "key_exists": key_exists,
        "digest": digest,
        "digest_exists": bool(digest),
        "source_alt_text_exists": bool(source_value),
        "proposed_translation_exists": bool(proposed_value),
        "existing_translation_state": _all_languages_existing_translation_state(entry),
        "readback_method_available": readback_method_available,
        "registration_input_ready": registration_input_ready,
        "maps_to_correct_media_object": maps_to_media,
        "mapping_safe": mapping_safe,
        "classification": classification,
        "plain_reason": _all_languages_media_alt_plain_reason(
            classification,
            mapping_safe=mapping_safe,
        ),
    }


def _all_languages_translation_readiness_audit(
    entries: list[dict],
    option_audit: dict,
    media_alt_audit: dict,
):
    more_fields = _all_languages_more_fields_enablement(entries)
    variant_summary = more_fields["variants"]
    customer_metafield_summary = more_fields["customer_facing_metafields"]
    technical_summary = more_fields["technical_fields"]
    missing_mapping_summary = more_fields["missing_mapping"]
    empty_values_summary = more_fields["empty_values"]
    ready_now = [
        _all_languages_readiness_area("Product title", entries, key="title"),
        _all_languages_readiness_area("SEO title", entries, key="meta_title"),
        _all_languages_readiness_area("SEO description", entries, key="meta_description"),
        _all_languages_readiness_area("Product description", entries, key="body_html"),
        {
            "area": "Product options",
            "status": (
                "Ready now"
                if option_audit.get("all_future_update_ready")
                else "Needs mapping review"
            ),
            "plain_reason": option_audit.get("plain_summary", ""),
            "checked_count": int(option_audit.get("row_count") or 0),
        },
        {
            "area": "Media alt text",
            "status": (
                "Ready now"
                if int(media_alt_audit.get("write_ready_count") or 0) > 0
                else "Ready now"
                if int(media_alt_audit.get("skipped_empty_count") or 0) > 0
                else "Not present"
                if int(media_alt_audit.get("row_count") or 0) == 0
                else "Needs mapping review"
            ),
            "plain_reason": media_alt_audit.get("plain_summary", ""),
            "checked_count": int(media_alt_audit.get("row_count") or 0),
        },
    ]
    needs_review = [
        {
            "area": "Fields needing review",
            "status": "Needs review",
            "plain_reason": (
                f"{len(_all_languages_needs_review_rows(entries))} row(s) have manual review notes."
            ),
            "checked_count": len(_all_languages_needs_review_rows(entries)),
        }
    ]
    preview_only = [
        {
            "area": "Variants",
            "status": variant_summary["status"],
            "plain_reason": variant_summary["plain_reason"],
            "checked_count": variant_summary["row_count"],
        },
        {
            "area": "Customer-facing metafields",
            "status": customer_metafield_summary["status"],
            "plain_reason": customer_metafield_summary["plain_reason"],
            "checked_count": customer_metafield_summary["row_count"],
        },
        {
            "area": "Technical fields",
            "status": technical_summary["status"],
            "plain_reason": technical_summary["plain_reason"],
            "checked_count": technical_summary["row_count"],
        },
        {
            "area": "Missing mapping",
            "status": missing_mapping_summary["status"],
            "plain_reason": missing_mapping_summary["plain_reason"],
            "checked_count": missing_mapping_summary["row_count"],
        },
        {
            "area": "Empty values",
            "status": empty_values_summary["status"],
            "plain_reason": empty_values_summary["plain_reason"],
            "checked_count": empty_values_summary["row_count"],
        },
    ]
    future_candidate = []
    for item in more_fields["ready_for_next_enablement_items"]:
        future_candidate.append(
            {
                "area": item["label"],
                "status": "Ready for next enablement task",
                "plain_reason": item["plain_reason"],
            }
        )
    for item in more_fields["blocked_customer_facing_items"]:
        future_candidate.append(
            {
                "area": item["label"],
                "status": "Blocked",
                "plain_reason": item["plain_reason"],
            }
        )
    return {
        "ready_now": ready_now,
        "needs_review": needs_review,
        "preview_only": preview_only,
        "future_candidate": future_candidate,
        "more_fields_enablement": {
            "title": "Future fields audit",
            "plain_summary": _all_languages_more_fields_plain_summary(more_fields),
            "variants": variant_summary,
            "customer_facing_metafields": customer_metafield_summary,
            "technical_fields": technical_summary,
            "missing_mapping": missing_mapping_summary,
            "empty_values": empty_values_summary,
            "ready_for_next_enablement_count": more_fields[
                "ready_for_next_enablement_count"
            ],
            "ready_for_next_enablement_labels": [
                item["label"]
                for item in more_fields["ready_for_next_enablement_items"]
            ],
        },
        "blocked_technical_fields": [
            {
                "area": item["label"],
                "status": "Blocked technical field",
                "plain_reason": item["plain_reason"],
            }
            for item in more_fields["blocked_technical_items"]
        ],
    }


def _all_languages_more_fields_plain_summary(more_fields: dict):
    variant_summary = more_fields["variants"]
    customer_summary = more_fields["customer_facing_metafields"]
    technical_summary = more_fields["technical_fields"]
    empty_summary = more_fields["empty_values"]
    ready_count = int(more_fields.get("ready_for_next_enablement_count") or 0)
    if ready_count:
        labels = ", ".join(
            item["label"] for item in more_fields["ready_for_next_enablement_items"]
        )
        return f"Ready for next enablement: {labels}."
    return (
        f"Variants: {variant_summary['status'].lower()} / not ready. "
        f"Customer-facing metafields: {customer_summary['ready_count']} ready / "
        f"{customer_summary['blocked_count']} blocked. "
        f"Technical fields: {technical_summary['status'].lower()}. "
        f"Empty fields: {empty_summary['status'].lower()}."
    )


def _all_languages_more_fields_enablement(entries: list[dict]):
    variant_rows = [
        _all_languages_variant_enablement_row(entry)
        for entry in entries or []
        if str(entry.get("field_group") or "") == "variants"
        or str(entry.get("key") or "").startswith("variant.")
    ]
    metafield_rows = [
        _all_languages_metafield_enablement_row(entry)
        for entry in entries or []
        if "metafield" in str(entry.get("field_group") or "")
    ]
    customer_metafield_rows = [
        row for row in metafield_rows if row["customer_facing_candidate"]
    ]
    technical_rows = [row for row in metafield_rows if row["technical_or_internal"]]
    all_rows = variant_rows + metafield_rows
    option_value_rows = [
        entry
        for entry in entries or []
        if str(entry.get("field_group") or "") == "options"
        and str(entry.get("key") or "") == "option.value"
    ]
    selected_option_rows = [
        entry
        for entry in entries or []
        if str(entry.get("field_group") or "") == "options"
        and (
            entry.get("selected_options")
            or entry.get("related_variants")
            or entry.get("visible_product_option")
        )
    ]
    variant_title_rows = [
        row
        for row in variant_rows
        if "title" in str(row.get("label") or "").lower()
    ]
    ready_items = _all_languages_unique_enablement_items(
        [
            row
            for row in variant_rows + customer_metafield_rows
            if row["ready_for_next_enablement_task"]
        ]
    )
    blocked_customer_items = _all_languages_unique_enablement_items(
        [
            row
            for row in customer_metafield_rows
            if not row["ready_for_next_enablement_task"]
            and not row["empty_value_skipped"]
            and not row["already_current"]
        ]
    )
    blocked_technical_items = _all_languages_unique_enablement_items(technical_rows)
    variant_summary = _all_languages_enablement_summary(
        "Variants",
        variant_rows,
        no_rows_status="No safe rows found",
        no_rows_reason=(
            "No variant rows were present in this report. Selected option values "
            "are handled by the Product options path."
        ),
    )
    variant_summary.update(
        {
            "variant_title_row_count": len(variant_title_rows),
            "selected_options_option_rows_checked_count": len(selected_option_rows),
            "option_value_rows_already_handled_count": len(option_value_rows),
        }
    )
    return {
        "variants": variant_summary,
        "customer_facing_metafields": _all_languages_enablement_summary(
            "Customer-facing metafields",
            customer_metafield_rows,
            no_rows_status="No ready rows found",
            no_rows_reason="No customer-facing metafield rows were found in this report.",
        ),
        "technical_fields": _all_languages_blocked_summary(
            "Technical fields",
            technical_rows,
            status_when_rows="Blocked",
            no_rows_status="No rows found",
            no_rows_reason="No technical/internal metafields were found in this report.",
            rows_reason="Technical/internal metafields stay blocked.",
        ),
        "missing_mapping": _all_languages_blocked_summary(
            "Missing mapping",
            [row for row in all_rows if row["missing_mapping"]],
            status_when_rows="Blocked",
            no_rows_status="No missing mapping found",
            no_rows_reason="No variant or metafield rows are missing required mapping in this report.",
            rows_reason=(
                "Rows without resource_id, key, digest, locale, proposed text, "
                "or readback path stay blocked."
            ),
        ),
        "empty_values": _all_languages_blocked_summary(
            "Empty values",
            [row for row in all_rows if row["empty_value_skipped"]],
            status_when_rows="Skipped",
            no_rows_status="No empty values found",
            no_rows_reason="No empty variant or metafield values were found in this report.",
            rows_reason="Empty values are skipped, not treated as Shopify update errors.",
        ),
        "ready_for_next_enablement_count": len(ready_items),
        "ready_for_next_enablement_items": ready_items,
        "blocked_customer_facing_items": blocked_customer_items,
        "blocked_technical_items": blocked_technical_items,
    }


def _all_languages_enablement_summary(
    label: str,
    rows: list[dict],
    *,
    no_rows_reason: str,
    no_rows_status: str = "No rows found",
):
    row_count = len(rows)
    ready_count = sum(1 for row in rows if row["ready_for_next_enablement_task"])
    empty_count = sum(1 for row in rows if row["empty_value_skipped"])
    already_current_count = sum(1 for row in rows if row["already_current"])
    blocked_count = max(0, row_count - ready_count - empty_count - already_current_count)
    if not row_count:
        status = no_rows_status
        reason = no_rows_reason
    elif ready_count:
        status = "Ready for next enablement task"
        reason = (
            f"{ready_count} {label.lower()} row(s) have resource_id, key, digest, "
            "locale, proposed text, and a readback path. Writes remain disabled "
            "until a dedicated enablement task."
        )
    else:
        status = "Not ready"
        reason = (
            f"{blocked_count} row(s) are blocked, {empty_count} empty row(s) are "
            f"skipped, and {already_current_count} row(s) are already current."
        )
    return {
        "area": label,
        "status": status,
        "plain_reason": reason,
        "row_count": row_count,
        "ready_count": ready_count,
        "blocked_count": blocked_count,
        "empty_skipped_count": empty_count,
        "already_current_count": already_current_count,
        "write_enabled_now": False,
    }


def _all_languages_blocked_summary(
    label: str,
    rows: list[dict],
    *,
    status_when_rows: str,
    no_rows_status: str,
    no_rows_reason: str,
    rows_reason: str,
):
    row_count = len(rows)
    return {
        "area": label,
        "status": status_when_rows if row_count else no_rows_status,
        "plain_reason": f"{row_count} row(s). {rows_reason}" if row_count else no_rows_reason,
        "row_count": row_count,
        "ready_count": 0,
        "blocked_count": row_count,
        "empty_skipped_count": (
            row_count if status_when_rows.lower() == "skipped" else 0
        ),
        "already_current_count": 0,
        "write_enabled_now": False,
    }


def _all_languages_variant_enablement_row(entry: dict):
    base = _all_languages_enablement_base_row(entry)
    resource_id = str(entry.get("resource_id") or "").strip()
    maps_to_variant = _all_languages_shopify_gid_type(resource_id) == "ProductVariant"
    base["maps_to_correct_shopify_object"] = maps_to_variant
    if resource_id and not maps_to_variant:
        base["missing_requirements"] = _unique_strings(
            base["missing_requirements"] + ["ProductVariant resource_id"]
        )
        base["missing_mapping"] = True
    marker_text = " ".join(
        str(value or "").lower()
        for value in (
            entry.get("key"),
            entry.get("source_key"),
            entry.get("field_label"),
            entry.get("context_label"),
            entry.get("resource_note"),
        )
    )
    technical = any(marker in marker_text for marker in ("sku", "barcode"))
    customer_facing = not technical
    label = entry.get("field_label") or entry.get("key") or "Variant field"
    return _all_languages_finish_enablement_row(
        base,
        label=f"Variant: {label}",
        customer_facing_candidate=customer_facing,
        technical_or_internal=technical,
        technical_reason="Variant SKU/barcode fields stay blocked.",
    )


def _all_languages_metafield_enablement_row(entry: dict):
    base = _all_languages_enablement_base_row(entry)
    namespace_key = _all_languages_metafield_namespace_key(entry) or "metafield"
    marker_text = " ".join(
        str(value or "").lower()
        for value in (
            namespace_key,
            entry.get("context_label"),
            entry.get("resource_note"),
            entry.get("key"),
        )
    )
    technical = any(marker in marker_text for marker in ALL_LANGUAGES_TECHNICAL_METAFIELD_MARKERS)
    customer_facing = (
        not technical
        and any(
            marker in marker_text
            for marker in ALL_LANGUAGES_CUSTOMER_FACING_METAFIELD_MARKERS
        )
    )
    return _all_languages_finish_enablement_row(
        base,
        label=f"Metafield: {namespace_key}",
        customer_facing_candidate=customer_facing,
        technical_or_internal=technical,
        technical_reason="Technical/internal metafield; do not enable automatic translation writes.",
    )


def _all_languages_enablement_base_row(entry: dict):
    resource_id = str(entry.get("resource_id") or "").strip()
    key = str(entry.get("key") or entry.get("source_key") or "").strip()
    digest = str(entry.get("digest") or entry.get("source_digest") or "").strip()
    locale = _safe_write_canonical_locale(entry.get("locale")) or str(
        entry.get("locale") or ""
    ).strip()
    proposed = str(entry.get("proposed_translation_value") or "").strip()
    missing = []
    if not resource_id:
        missing.append("resource_id")
    if not key:
        missing.append("key")
    if not digest:
        missing.append("digest")
    if not locale:
        missing.append("locale")
    readback_path_available = bool(resource_id and locale)
    if not readback_path_available:
        missing.append("readback path")
    mapping_missing = list(missing)
    if not proposed:
        missing.append("proposed translation")
    already_current = (
        entry.get("status") == "written_verified"
        or "existing_translation_current_same_value"
        in (entry.get("blocking_reasons") or [])
    )
    return {
        "resource_id_exists": bool(resource_id),
        "key_exists": bool(key),
        "digest_exists": bool(digest),
        "locale_exists": bool(locale),
        "proposed_translation_exists": bool(proposed),
        "readback_path_available": readback_path_available,
        "missing_requirements": _unique_strings(missing),
        "missing_mapping": bool(mapping_missing),
        "empty_value_skipped": not bool(proposed),
        "already_current": already_current,
    }


def _all_languages_finish_enablement_row(
    row: dict,
    *,
    label: str,
    customer_facing_candidate: bool,
    technical_or_internal: bool,
    technical_reason: str,
):
    row.update(
        {
            "label": label,
            "customer_facing_candidate": customer_facing_candidate,
            "technical_or_internal": technical_or_internal,
            "safe_to_write_now": False,
            "write_enabled_now": False,
        }
    )
    ready = (
        customer_facing_candidate
        and not technical_or_internal
        and not row["missing_mapping"]
        and not row["empty_value_skipped"]
    )
    row["ready_for_next_enablement_task"] = ready
    if ready:
        row["classification"] = "ready_for_next_enablement_task"
        row["plain_reason"] = (
            "Ready for next enablement task: resource_id, key, digest, locale, "
            "proposed text, and readback path are present. Writes remain disabled "
            "in this task."
        )
    elif row["already_current"]:
        row["classification"] = "already_current_skipped"
        row["plain_reason"] = "Already updated or already current."
    elif row["empty_value_skipped"]:
        row["classification"] = "empty_value_skipped"
        row["plain_reason"] = "Empty value; skipped rather than treated as an error."
    elif technical_or_internal:
        row["classification"] = "technical_or_internal_blocked"
        row["plain_reason"] = technical_reason
    elif row["missing_requirements"]:
        row["classification"] = "missing_mapping_blocked"
        row["plain_reason"] = (
            "Blocked: missing "
            + ", ".join(row["missing_requirements"])
            + "."
        )
    else:
        row["classification"] = "not_ready"
        row["plain_reason"] = "Blocked until a dedicated mapping/readback audit approves it."
    return row


def _all_languages_unique_enablement_items(rows: list[dict]):
    items = []
    seen = set()
    for row in rows:
        label = row.get("label") or ""
        if not label or label in seen:
            continue
        seen.add(label)
        items.append(
            {
                "label": label,
                "plain_reason": row.get("plain_reason", ""),
            }
        )
    return items


def _all_languages_media_alt_entry(entry: dict):
    return (
        str(entry.get("field_group") or "") in {"media", "media_alt_text"}
        or str(entry.get("key") or "") == "media.alt"
    )


def _all_languages_media_alt_plain_reason(classification: str, *, mapping_safe: bool):
    if classification == "media_alt_update_not_enabled":
        return "Needs review before update."
    if classification == "media_alt_missing_mapping":
        return "Missing a real Shopify media resource ID or alt key."
    if classification == "media_alt_missing_digest":
        return "Missing digest for the media alt source text."
    if classification == "media_alt_empty_translation":
        return "Media alt text is empty."
    if classification == "media_alt_needs_review":
        return "Translation row still needs manual review."
    if classification == "media_alt_write_ready" and mapping_safe:
        return "Mapping is safe and media alt text is enabled for automatic update."
    return "Media alt row needs review."


def _all_languages_existing_translation_state(entry: dict):
    existing_value = str(
        entry.get("previous_translation_value")
        or entry.get("existing_translation_value")
        or ""
    ).strip()
    outdated = entry.get("previous_translation_outdated")
    if outdated is None:
        outdated = entry.get("existing_translation_outdated")
    if existing_value and outdated is True:
        return "existing_outdated"
    if existing_value:
        return "existing_current_or_unknown"
    return "missing"


def _all_languages_readiness_area(label: str, entries: list[dict], *, key: str):
    key_entries = [entry for entry in entries or [] if entry.get("key") == key]
    updated = _all_languages_entry_status_count(
        key_entries,
        "written_verified",
        "readback_mismatch",
    )
    verified = _all_languages_entry_status_count(key_entries, "written_verified")
    ready = _all_languages_entry_status_count(key_entries, "write_ready")
    blocked = _all_languages_entry_status_count(key_entries, "blocked")
    skipped = _all_languages_entry_status_count(key_entries, "skipped")
    if updated:
        status = "Ready now"
        reason = f"{verified} of {updated} updated row(s) were confirmed."
    elif ready:
        status = "Ready now"
        reason = f"{ready} row(s) are ready to update."
    elif skipped and not blocked:
        status = "Ready now"
        reason = "Rows are already up to date."
    else:
        status = "Needs review" if blocked else "Not present"
        reason = f"{blocked} row(s) are blocked." if blocked else "No rows found."
    return {
        "area": label,
        "status": status,
        "plain_reason": reason,
        "checked_count": len(key_entries),
    }


def _all_languages_metafield_readiness(entries: list[dict]):
    technical = set()
    future = set()
    for entry in entries or []:
        if "metafield" not in str(entry.get("field_group") or ""):
            continue
        namespace_key = _all_languages_metafield_namespace_key(entry)
        marker_text = " ".join(
            str(value or "").lower()
            for value in (
                namespace_key,
                entry.get("context_label"),
                entry.get("resource_note"),
                entry.get("key"),
            )
        )
        if any(marker in marker_text for marker in ALL_LANGUAGES_TECHNICAL_METAFIELD_MARKERS):
            technical.add(namespace_key or "metafield")
        elif any(
            marker in marker_text
            for marker in ALL_LANGUAGES_CUSTOMER_FACING_METAFIELD_MARKERS
        ):
            future.add(namespace_key or "metafield")
    return sorted(technical), sorted(future)


def _all_languages_metafield_namespace_key(entry: dict):
    context = str(entry.get("context_label") or "").strip()
    if "|" in context:
        namespace, key = [part.strip() for part in context.split("|", 1)]
        return f"{namespace}.{key}".strip(".")
    key = str(entry.get("key") or "").strip()
    if key.startswith("metafield."):
        return key.removeprefix("metafield.")
    return context or key


def _all_languages_shopify_gid_type(resource_id: str):
    prefix = "gid://shopify/"
    resource_id = str(resource_id or "").strip()
    if not resource_id.startswith(prefix):
        return ""
    return resource_id[len(prefix) :].split("/", 1)[0]


def _all_languages_option_shopify_key(entry: dict):
    source_key = str(entry.get("source_key") or entry.get("shopify_key") or "").strip()
    if source_key:
        return source_key
    display_key = str(entry.get("key") or "")
    if display_key == "option.name":
        return "name"
    if display_key == "option.value":
        return "value"
    return display_key


def _all_languages_next_enablement_summary(
    entries: list[dict],
    option_audit: dict,
    german_body_html_diagnostic: dict,
):
    rows = []
    if option_audit.get("row_count"):
        if option_audit.get("all_future_update_ready"):
            rows.append(
                {
                    "area": "Product options",
                    "status": "Enabled for update",
                    "plain_reason": option_audit.get("plain_summary", ""),
                }
            )
        else:
            rows.append(
                {
                    "area": "Product options",
                    "status": "Keep blocked",
                    "plain_reason": option_audit.get("plain_summary", ""),
                }
            )
    if german_body_html_diagnostic.get("exists"):
        if german_body_html_diagnostic.get("repair_applied"):
            rows.append(
                {
                    "area": "German product description",
                    "status": "Forbidden phrase repaired",
                    "plain_reason": german_body_html_diagnostic.get(
                        "plain_reason",
                        "",
                    ),
                }
            )
        elif german_body_html_diagnostic.get("forbidden_phrase"):
            rows.append(
                {
                    "area": "German product description",
                    "status": "Manual review first",
                    "plain_reason": (
                        "Can be retried after removing the forbidden phrase and rechecking the draft."
                    ),
                }
            )
        elif german_body_html_diagnostic.get("status") == "written_verified":
            rows.append(
                {
                    "area": "German product description",
                    "status": "Already updated",
                    "plain_reason": "No enablement needed for this field.",
                }
            )
    media_entries = [
        entry for entry in entries or [] if entry.get("field_group") in {"media", "media_alt_text"}
    ]
    if media_entries:
        ready_count = sum(
            1
            for entry in media_entries
            if entry.get("status") in {"write_ready", "written_verified"}
        )
        empty_count = sum(
            1
            for entry in media_entries
            if "media_alt_text_empty" in (entry.get("blocking_reasons") or [])
        )
        rows.append(
            {
                "area": "Media alt text",
                "status": "Enabled for update",
                "plain_reason": (
                    f"{ready_count} media row(s) are ready for automatic update; "
                    f"{empty_count} empty row(s) will be skipped."
                ),
            }
        )
    return rows


def _all_languages_successful_locale_summaries(entries: list[dict]):
    rows = []
    for locale in ALL_LANGUAGES_SUPPORTED_LOCALES:
        locale_entries = [entry for entry in entries or [] if entry.get("locale") == locale]
        updated_entries = [
            entry for entry in locale_entries if _all_languages_entry_updated(entry)
        ]
        if not updated_entries:
            continue
        field_labels = _all_languages_updated_field_labels(locale_entries)
        confirmed_count = sum(
            1 for entry in updated_entries if _all_languages_entry_confirmed(entry)
        )
        all_confirmed = confirmed_count == len(updated_entries)
        status_text = (
            "updated and confirmed"
            if all_confirmed
            else "updated; confirmation needs review"
        )
        rows.append(
            {
                "locale": locale,
                "language_label": _all_languages_locale_label(locale),
                "field_labels": field_labels,
                "fields_label": _all_languages_join_labels(field_labels),
                "updated_count": len(updated_entries),
                "confirmed_count": confirmed_count,
                "all_confirmed": all_confirmed,
                "summary_text": (
                    f"{_all_languages_locale_label(locale)}: "
                    f"{_all_languages_join_labels(field_labels)} {status_text}"
                ),
            }
        )
    return rows


def _all_languages_updated_entries_display(entries: list[dict]):
    rows = []
    for entry in entries or []:
        if not _all_languages_entry_updated(entry):
            continue
        confirmed = _all_languages_entry_confirmed(entry)
        rows.append(
            {
                "locale": entry.get("locale", ""),
                "language_label": _all_languages_locale_label(entry.get("locale", "")),
                "field": entry.get("key", ""),
                "field_label": _all_languages_field_label(entry.get("key", "")),
                "proposed_value": entry.get("proposed_translation_value", ""),
                "confirmed": confirmed,
                "confirmed_label": "Yes" if confirmed else "No",
            }
        )
    return rows


def _all_languages_locale_success_summary_text(row: dict):
    fields_label = row.get("updated_fields_label") or ""
    if not fields_label:
        return ""
    status_text = (
        "updated and confirmed"
        if row.get("all_updated_fields_confirmed")
        else "updated; confirmation needs review"
    )
    return f"{row.get('language_label') or row.get('locale')}: {fields_label} {status_text}"


def _all_languages_updated_field_labels(
    entries: list[dict],
    *,
    confirmed_only: bool = False,
):
    labels = []
    for field in ALL_LANGUAGES_AUTO_WRITE_FIELDS:
        field_entries = [entry for entry in entries or [] if entry.get("key") == field]
        if confirmed_only:
            has_field = any(_all_languages_entry_confirmed(entry) for entry in field_entries)
        else:
            has_field = any(_all_languages_entry_updated(entry) for entry in field_entries)
        if has_field:
            labels.append(_all_languages_field_label(field))
    return labels


def _all_languages_join_labels(labels: list[str]):
    return ", ".join(label for label in labels or [] if label)


def _all_languages_entry_updated(entry: dict):
    return entry.get("status") in {"written_verified", "readback_mismatch"}


def _all_languages_entry_confirmed(entry: dict):
    return entry.get("status") == "written_verified"


def _all_languages_field_label(field: str):
    field = str(field or "")
    if field in ALL_LANGUAGES_OPTION_FIELD_LABELS:
        return ALL_LANGUAGES_OPTION_FIELD_LABELS[field]
    return ALL_LANGUAGES_SAFE_FIELD_LABELS.get(
        field,
        field.replace("_", " ").strip().capitalize() or "Field",
    )


def _all_languages_locale_label(locale: str):
    locale = _safe_write_canonical_locale(locale)
    return ALL_LANGUAGES_LOCALE_LABELS.get(locale, locale or "Locale")


def _all_languages_refresh_entry_human_reasons(entry: dict):
    reasons = list(entry.get("blocking_reasons") or [])
    status = entry.get("status")
    if status == "skipped" and not reasons:
        reasons = ["existing_translation_current_same_value"]
    elif status == "write_failed" and not reasons:
        reasons = ["translations_register_failed"]
    elif status == "readback_mismatch" and not reasons:
        reasons = ["readback_mismatch"]
    labels = [
        _all_languages_blocking_reason_label_for_entry(reason, entry)
        for reason in reasons
        if reason
    ]
    if not labels and entry.get("blocking_reason"):
        labels = [str(entry.get("blocking_reason"))]
    entry["human_blocking_reasons"] = _unique_strings(labels)
    if entry.get("status") in {"blocked", "skipped", "write_failed", "readback_mismatch"}:
        entry["blocking_reason"] = (
            entry["human_blocking_reasons"][0]
            if entry["human_blocking_reasons"]
            else entry.get("blocking_reason", "")
        )
    entry["soft_warning_reasons"] = _unique_strings(
        entry.get("soft_warning_reasons") or []
    )
    entry["human_soft_warnings"] = [
        _all_languages_soft_warning_label(reason)
        for reason in entry.get("soft_warning_reasons") or []
        if reason
    ]


def _all_languages_blocked_reason_summary(entries: list[dict], blocking_conditions: list[str]):
    counts = {}
    raw_reasons = {}
    for entry in entries or []:
        if entry.get("status") != "blocked":
            continue
        labels = entry.get("human_blocking_reasons") or []
        if not labels and entry.get("blocking_reason"):
            labels = [entry.get("blocking_reason")]
        if not labels:
            continue
        label = str(labels[0])
        counts[label] = counts.get(label, 0) + 1
        raw_reasons.setdefault(label, [])
        raw_reasons[label].extend(entry.get("blocking_reasons") or [])
    if not counts:
        for condition in blocking_conditions or []:
            label = _all_languages_blocking_reason_label(condition)
            counts[label] = counts.get(label, 0) + 1
            raw_reasons.setdefault(label, []).append(condition)
    return [
        {
            "label": label,
            "count": count,
            "raw_reasons": _unique_strings(raw_reasons.get(label) or []),
        }
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _all_languages_safe_field_diagnostics(entries: list[dict]):
    diagnostics = []
    safe_entries = [
        entry
        for entry in entries or []
        if entry.get("key") in ALL_LANGUAGES_AUTO_WRITE_FIELD_SET
    ]
    for field in ALL_LANGUAGES_AUTO_WRITE_FIELDS:
        field_entries = [entry for entry in safe_entries if entry.get("key") == field]
        reason_summary = _all_languages_safe_field_reason_summary(field_entries)
        soft_warning_summary = _all_languages_safe_field_soft_warning_summary(field_entries)
        diagnostics.append(
            {
                "field": field,
                "label": _all_languages_field_label(field),
                "candidates_found": len(field_entries),
                "ready_count": _all_languages_entry_status_count(
                    field_entries,
                    "write_ready",
                ),
                "blocked_count": _all_languages_entry_status_count(
                    field_entries,
                    "blocked",
                ),
                "hard_blocked_count": _all_languages_entry_status_count(
                    field_entries,
                    "blocked",
                ),
                "soft_warning_count": _all_languages_entry_soft_warning_count(
                    field_entries
                ),
                "already_up_to_date_count": _all_languages_entry_status_count(
                    field_entries,
                    "skipped",
                ),
                "top_block_reason": (
                    reason_summary[0]["label"] if reason_summary else "No blocked fields."
                ),
                "reason_summary_text": _all_languages_reason_summary_text(
                    reason_summary,
                    empty="No blocked fields.",
                ),
                "reason_summary": reason_summary,
                "top_soft_warning": (
                    soft_warning_summary[0]["label"]
                    if soft_warning_summary
                    else "No review notes."
                ),
                "soft_warning_summary_text": _all_languages_reason_summary_text(
                    soft_warning_summary,
                    empty="No review notes.",
                ),
                "soft_warning_summary": soft_warning_summary,
                "plain_reason": _all_languages_safe_field_plain_reason(
                    field_entries,
                    field,
                    reason_summary,
                    soft_warning_summary,
                ),
            }
        )
    safe_blocked_reason_summary = _all_languages_safe_field_reason_summary(safe_entries)
    safe_soft_warning_summary = _all_languages_safe_field_soft_warning_summary(safe_entries)
    ready_count = _all_languages_entry_status_count(safe_entries, "write_ready")
    blocked_count = _all_languages_entry_status_count(safe_entries, "blocked")
    soft_warning_count = _all_languages_entry_soft_warning_count(safe_entries)
    already_up_to_date_count = _all_languages_entry_status_count(safe_entries, "skipped")
    if safe_blocked_reason_summary:
        top_reason = safe_blocked_reason_summary[0]["label"]
    elif not safe_entries:
        top_reason = "No automatic update fields were found in this report."
    elif already_up_to_date_count and not ready_count and not blocked_count:
        top_reason = "All safe fields are already up to date."
    else:
        top_reason = "No blocked safe fields."
    if safe_soft_warning_summary:
        top_soft_warning = safe_soft_warning_summary[0]["label"]
    else:
        top_soft_warning = "No review notes."
    summary = {
        "product_title_candidates_found": next(
            item["candidates_found"] for item in diagnostics if item["field"] == "title"
        ),
        "seo_title_candidates_found": next(
            item["candidates_found"] for item in diagnostics if item["field"] == "meta_title"
        ),
        "seo_description_candidates_found": next(
            item["candidates_found"]
            for item in diagnostics
            if item["field"] == "meta_description"
        ),
        "product_description_candidates_found": next(
            item["candidates_found"]
            for item in diagnostics
            if item["field"] == "body_html"
        ),
        "media_alt_candidates_found": next(
            item["candidates_found"]
            for item in diagnostics
            if item["field"] == "media.alt"
        ),
        "product_options_candidates_found": sum(
            item["candidates_found"]
            for item in diagnostics
            if item["field"] in ALL_LANGUAGES_OPTION_AUTO_WRITE_FIELDS
        ),
        "safe_fields_ready": ready_count,
        "safe_fields_blocked": blocked_count,
        "safe_fields_hard_blocked": blocked_count,
        "safe_fields_soft_warning": soft_warning_count,
        "safe_fields_already_up_to_date": already_up_to_date_count,
        "top_block_reason_for_safe_fields": top_reason,
        "top_hard_block_reason_for_safe_fields": top_reason,
        "top_soft_warning_reason_for_safe_fields": top_soft_warning,
        "safe_field_plain_reasons": [
            item["plain_reason"] for item in diagnostics if item.get("plain_reason")
        ],
    }
    return diagnostics, summary


def _all_languages_reason_summary_text(reason_summary: list[dict], *, empty: str):
    if not reason_summary:
        return empty
    return "; ".join(
        f"{item.get('label', '')} ({item.get('count', 0)})"
        for item in reason_summary
        if item.get("label")
    )


def _all_languages_safe_field_reason_summary(entries: list[dict]):
    counts = {}
    raw_reasons = {}
    for entry in entries or []:
        if entry.get("status") != "blocked":
            continue
        labels = entry.get("human_blocking_reasons") or []
        if not labels and entry.get("blocking_reason"):
            labels = [entry.get("blocking_reason")]
        for label in labels:
            counts[label] = counts.get(label, 0) + 1
            raw_reasons.setdefault(label, [])
            raw_reasons[label].extend(entry.get("blocking_reasons") or [])
    return [
        {
            "label": label,
            "count": count,
            "raw_reasons": _unique_strings(raw_reasons.get(label) or []),
        }
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _all_languages_safe_field_soft_warning_summary(entries: list[dict]):
    counts = {}
    raw_reasons = {}
    for entry in entries or []:
        labels = entry.get("human_soft_warnings") or [
            _all_languages_soft_warning_label(reason)
            for reason in entry.get("soft_warning_reasons") or []
        ]
        for label in labels:
            if not label:
                continue
            counts[label] = counts.get(label, 0) + 1
            raw_reasons.setdefault(label, [])
            raw_reasons[label].extend(entry.get("soft_warning_reasons") or [])
    return [
        {
            "label": label,
            "count": count,
            "raw_reasons": _unique_strings(raw_reasons.get(label) or []),
        }
        for label, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _all_languages_safe_field_plain_reason(
    entries: list[dict],
    field: str,
    reason_summary: list[dict],
    soft_warning_summary: list[dict],
):
    label = _all_languages_field_label(field)
    if not entries:
        return f"{label}: blocked because no candidate rows were found."
    ready_count = _all_languages_entry_status_count(entries, "write_ready")
    if ready_count:
        return f"{label}: ready to update for {ready_count} row(s)."
    skipped_count = _all_languages_entry_status_count(entries, "skipped")
    if skipped_count and skipped_count == len(entries):
        if any(
            "media_alt_text_empty" in (entry.get("blocking_reasons") or [])
            for entry in entries
        ):
            return f"{label}: skipped because media alt text is empty."
        return f"{label}: not updated because Shopify already has the same current value."
    if reason_summary:
        return (
            f"{label}: blocked because "
            f"{_all_languages_reason_summary_text(reason_summary, empty='no hard blockers')}"
            "."
        )
    if soft_warning_summary:
        return (
            f"{label}: not blocked; review notes only: "
            f"{_all_languages_reason_summary_text(soft_warning_summary, empty='no review notes')}"
            "."
        )
    return f"{label}: blocked because no ready row was found."


def _all_languages_soft_warning_label(reason: str):
    labels = {
        "existing_translation_outdated": "Existing Shopify translation is outdated.",
        "future_write_needs_resource_mapping": "Mapping notice applies to non-writable groups.",
        "keyword_stuffing_or_duplicate": "SEO wording could be improved.",
        "missing_core_keyword": "SEO could include a stronger keyword.",
        "missing_model": "SEO could include the model more clearly.",
        "missing_part_type": "SEO could include the part type more clearly.",
        "missing_replacement_part_meaning": "SEO could make the replacement-part meaning clearer.",
        "missing_use_case": "SEO could describe the use case more clearly.",
        "missing_value_point": "SEO may be missing a value point.",
        "needs_review": "Needs review label is only a soft review note.",
        "outdated": "Existing Shopify translation is outdated.",
        "seo_could_be_improved": "SEO could be improved.",
        "seo_needs_manual_review": "SEO review note.",
        "seo_not_ready": "SEO review note.",
        "seo_warning": "SEO review note.",
        "too_short_for_seo": "SEO text is shorter than recommended.",
    }
    return labels.get(reason, reason)


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
        locale = _safe_write_canonical_locale(row.get("locale", ""))
        if locale and locale not in seen:
            seen.append(locale)
    selected_locale = _safe_write_canonical_locale(selected_locale)
    if selected_locale and selected_locale not in seen:
        seen.insert(0, selected_locale)
    return [{"value": locale, "label": locale} for locale in seen]


def _safe_write_canonical_locale(locale: str) -> str:
    text = str(locale or "").strip()
    if not text:
        return ""
    normalized = text.lower().replace("_", "-")
    candidates = [normalized]
    if "(" in normalized and ")" in normalized:
        candidates.append(normalized.rsplit("(", 1)[1].split(")", 1)[0].strip())
    if " " in normalized:
        candidates.append(normalized.split(" ", 1)[0].strip())
    if "-" in normalized:
        candidates.append(normalized.split("-", 1)[0].strip())
    alias = LOCKED_EXECUTION_LOCALE_LABEL_ALIASES.get(normalized)
    if alias:
        candidates.append(alias)
    for candidate in candidates:
        candidate = str(candidate or "").strip().lower()
        if candidate in LOCKED_EXECUTION_SUPPORTED_LOCALES:
            return candidate
        base_locale = candidate.split("-", 1)[0]
        if base_locale in LOCKED_EXECUTION_SUPPORTED_LOCALES:
            return base_locale
    return text


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


def _real_write_translations_register(installation, resource_id: str, translation_input):
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
    translation_inputs = (
        [item for item in translation_input if isinstance(item, dict)]
        if isinstance(translation_input, list)
        else [translation_input]
    )
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
                    "translations": translation_inputs,
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
        "resource_id": "",
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
    result["resource_id"] = resource.get("resourceId", "")
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
    expected_resource_id: str = "",
    readback_resource_id: str = "",
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
    resource_id_matches = (
        not expected_resource_id
        or not readback_resource_id
        or expected_resource_id == readback_resource_id
    )
    return {
        "matched": bool(item)
        and value_matches
        and locale_matches
        and resource_id_matches
        and outdated_acceptable,
        "key_exists": bool(matching_key),
        "resource_id_matches": resource_id_matches,
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


def _finalize_selected_translations_payload(
    payload: dict,
    json_path: Path,
    html_path: Path,
    write_reports: bool,
):
    payload["blocking_conditions"] = _unique_strings(
        payload.get("blocking_conditions") or []
    )
    payload["sanitized_errors"] = _real_write_unique_errors(
        payload.get("sanitized_errors") or []
    )
    mutation_called = bool(payload.get("mutation_called"))
    payload["shopify_read_only"] = not mutation_called
    payload["no_new_shopify_writes_performed"] = not mutation_called
    payload["all_new_actions_no_write_confirmed"] = not mutation_called
    if write_reports:
        _write_selected_translations_reports(payload, json_path, html_path)
    return payload


def _finalize_all_languages_update_payload(
    payload: dict,
    background_report: dict,
    json_path: Path,
    html_path: Path,
    write_reports: bool,
):
    payload["blocking_conditions"] = _unique_strings(
        payload.get("blocking_conditions") or []
    )
    payload["sanitized_errors"] = _real_write_unique_errors(
        payload.get("sanitized_errors") or []
    )
    entries = payload.get("entries") or []
    payload["candidate_count"] = len(entries)
    payload["write_ready_count"] = _all_languages_entry_status_count(
        entries,
        "write_ready",
    )
    payload["updated_count"] = _all_languages_entry_status_count(
        entries,
        "written_verified",
        "readback_mismatch",
    )
    payload["verified_count"] = _all_languages_entry_status_count(
        entries,
        "written_verified",
    )
    payload["skipped_count"] = _all_languages_entry_status_count(entries, "skipped")
    payload["blocked_count"] = _all_languages_entry_status_count(entries, "blocked")
    payload["review_note_count"] = _all_languages_entry_soft_warning_count(entries)
    payload["failed_count"] = _all_languages_entry_status_count(
        entries,
        "write_failed",
        "readback_mismatch",
    )
    payload["per_locale_summary"] = _all_languages_per_locale_summary(
        entries,
        background_report,
    )
    payload["per_field_summary"] = _all_languages_per_field_summary(entries)
    payload["rollback_needed"] = bool(
        payload.get("rollback_needed")
        or any(bool(entry.get("rollback_needed")) for entry in entries)
    )
    mutation_called = bool(payload.get("mutation_called"))
    payload["shopify_read_only"] = not mutation_called
    payload["no_new_shopify_writes_performed"] = not mutation_called
    payload["all_new_actions_no_write_confirmed"] = not mutation_called
    _all_languages_attach_plain_language(payload)
    if write_reports:
        _write_all_languages_update_reports(payload, json_path, html_path)
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


def _selected_translations_report_paths(
    product_gid: str,
    locale: str,
    generated_at: str,
):
    product_token = _safe_write_product_token(product_gid)
    locale_token = _safe_write_filename_token(locale or "locale")
    stamp = _safe_write_timestamp_token(generated_at)
    base = f"selected_translation_real_write_{product_token}_{locale_token}_{stamp}"
    return (
        REAL_WRITE_REPORT_DIR / f"{base}.json",
        REAL_WRITE_REPORT_DIR / f"{base}.html",
    )


def _all_languages_update_report_paths(product_gid: str, generated_at: str):
    product_token = _safe_write_product_token(product_gid)
    stamp = _safe_write_timestamp_token(generated_at)
    base = f"translation_all_languages_update_{product_token}_{stamp}"
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


def _write_selected_translations_reports(payload: dict, json_path: Path, html_path: Path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    json.loads(text)
    json_path.write_text(text, encoding="utf-8")
    html_path.write_text(_render_selected_translations_html(payload), encoding="utf-8")


def _write_all_languages_update_reports(payload: dict, json_path: Path, html_path: Path):
    json_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    json.loads(text)
    json_path.write_text(text, encoding="utf-8")
    html_path.write_text(_render_all_languages_update_html(payload), encoding="utf-8")


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


def _render_selected_translations_html(payload: dict):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Status", "status"),
            ("Audit Status", "audit_status"),
            ("Product GID", "product_gid"),
            ("Product Title", "product_title"),
            ("Locale", "locale"),
            ("Selected Entry Count", "selected_entry_count"),
            ("Selected Fields", "selected_fields"),
            ("ACK Matched", "ack_matched"),
            ("Mutation Called", "mutation_called"),
            ("translationsRegister Called", "translations_register_called"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Readback Performed", "readback_performed"),
            ("Readback Verified Count", "readback_verified_count"),
            ("Readback Failed Count", "readback_failed_count"),
            ("Rollback Needed", "rollback_needed"),
            ("Blocking Conditions", "blocking_conditions"),
            ("JSON Report Path", "json_report_path"),
            ("HTML Report Path", "html_report_path"),
        ]
    )
    entry_rows = "\n".join(
        _selected_translations_entry_row(entry)
        for entry in payload.get("selected_entries", [])
    ) or "<tr><td colspan='9'>No selected entries</td></tr>"
    error_rows = "\n".join(
        _real_write_error_row(error)
        for error in payload.get("sanitized_errors", [])
    ) or "<tr><td colspan='3'>No sanitized errors recorded</td></tr>"
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Translation Shopify Update Audit</title></head>
<body>
  <h1>Selected Translation Shopify Update Audit</h1>
  <p><strong>No automatic rollback is performed. Restore candidates are included for manual rollback planning if needed.</strong></p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Selected Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Resource ID</th><th>Key</th><th>Digest</th><th>Previous translation</th><th>Proposed translation</th><th>Manual edit used</th><th>Readback verified</th><th>Rollback needed</th><th>Restore candidate</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Sanitized Errors</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Stage</th><th>Type</th><th>Message</th></tr></thead>
    <tbody>{error_rows}</tbody>
  </table>
</body>
</html>
"""


def _render_all_languages_update_html(payload: dict):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Action Name", "action_name"),
            ("Raw Status", "status"),
            ("Product GID", "product_gid"),
            ("Product Title", "product_title"),
            ("Locales", "locales"),
            ("Checked Items", "candidate_count"),
            ("Raw write_ready_count", "write_ready_count"),
            ("Updated in Shopify", "updated_count"),
            ("Confirmed After Update", "verified_count"),
            ("Product Titles Updated", "product_title_updated_count"),
            ("Product Descriptions Updated", "body_html_updated_count"),
            ("SEO Fields Updated", "seo_updated_count"),
            ("Product Options Updated", "product_options_updated_count"),
            ("Media Alt Text Updated", "media_alt_updated_count"),
            ("Already Up To Date", "skipped_count"),
            ("Skipped Empty", "skipped_empty_count"),
            ("Not Updated", "not_updated_count"),
            ("Review Notes", "review_note_count"),
            ("Failed", "failed_count"),
            ("Mutation Called", "mutation_called"),
            ("translationsRegister Called", "translations_register_called"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Readback Performed", "readback_performed"),
            ("Restore May Be Needed", "rollback_needed"),
            ("Blocking Conditions", "blocking_conditions"),
            ("JSON Report Path", "json_report_path"),
            ("HTML Report Path", "html_report_path"),
        ]
    )
    success_summary = ""
    if payload.get("is_successfully_updated"):
        success_summary = f"""
  <h2>Success</h2>
  <ul>
    <li>Shopify updated successfully</li>
    <li>{escape(str(payload.get('verified_count', 0)))} translations updated and confirmed</li>
    <li>Product titles updated: {escape(str(payload.get('product_title_updated_count', 0)))}</li>
    <li>Product descriptions updated: {escape(str(payload.get('body_html_updated_count', 0)))}</li>
    <li>SEO fields updated: {escape(str(payload.get('seo_updated_count', 0)))}</li>
    <li>Product options updated: {escape(str(payload.get('product_options_updated_count', 0)))}</li>
    <li>Media alt text updated: {escape(str(payload.get('media_alt_updated_count', 0)))}</li>
    <li>Not updated: {escape(str(payload.get('not_updated_count', 0)))}</li>
    <li>Restore not needed</li>
  </ul>
"""
    entry_rows = "\n".join(
        _all_languages_update_entry_row(entry)
        for entry in payload.get("entries", [])
    ) or "<tr><td colspan='9'>No entries</td></tr>"
    updated_entry_rows = "\n".join(
        _all_languages_updated_entry_html_row(entry)
        for entry in payload.get("updated_entries", [])
    ) or "<tr><td colspan='4'>No updated entries</td></tr>"
    locale_rows = "\n".join(
        _all_languages_summary_row(item, "locale")
        for item in payload.get("per_locale_summary", [])
    ) or "<tr><td colspan='9'>No locale summary</td></tr>"
    field_rows = "\n".join(
        _all_languages_summary_row(item, "field")
        for item in payload.get("per_field_summary", [])
    ) or "<tr><td colspan='9'>No field summary</td></tr>"
    error_rows = "\n".join(
        _real_write_error_row(error)
        for error in payload.get("sanitized_errors", [])
    ) or "<tr><td colspan='3'>No sanitized errors recorded</td></tr>"
    diagnostic_html = _all_languages_update_diagnostic_html(payload)
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>All Languages Shopify Translation Update Audit</title></head>
<body>
  <h1>All Languages Shopify Translation Update Audit</h1>
  <p><strong>No automatic rollback is performed. Restore candidates are included for manual rollback planning if needed.</strong></p>
  {success_summary}
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Per Locale Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Checked Items</th><th>Raw Ready Count</th><th>Updated in Shopify</th><th>Confirmed After Update</th><th>Already Up To Date</th><th>Not Updated</th><th>Review Notes</th><th>Failed</th></tr></thead>
    <tbody>{locale_rows}</tbody>
  </table>
  <h2>Per Field Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Field</th><th>Checked Items</th><th>Raw Ready Count</th><th>Updated in Shopify</th><th>Confirmed After Update</th><th>Already Up To Date</th><th>Not Updated</th><th>Review Notes</th><th>Failed</th></tr></thead>
    <tbody>{field_rows}</tbody>
  </table>
  {diagnostic_html}
  <h2>Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Proposed value</th><th>Confirmed</th></tr></thead>
    <tbody>{updated_entry_rows}</tbody>
  </table>
  <h2>Technical Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Key</th><th>Resource ID</th><th>Digest</th><th>Manual edit</th><th>Status</th><th>Blocking reason</th><th>Readback matched</th><th>Rollback needed</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
  <h2>Sanitized Errors</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Stage</th><th>Type</th><th>Message</th></tr></thead>
    <tbody>{error_rows}</tbody>
  </table>
</body>
</html>
"""


def _all_languages_update_diagnostic_html(payload: dict):
    german = payload.get("german_body_html_diagnostic") or {}
    needs_review_rows = "\n".join(
        _all_languages_needs_review_html_row(row)
        for row in payload.get("needs_review_rows", [])
    ) or "<tr><td colspan='4'>No generic Needs review rows</td></tr>"
    option_audit = payload.get("option_mapping_audit") or {}
    option_rows = "\n".join(
        _all_languages_option_mapping_html_row(row)
        for row in option_audit.get("rows", [])
    ) or "<tr><td colspan='8'>No option rows</td></tr>"
    next_rows = "\n".join(
        _all_languages_next_enablement_html_row(row)
        for row in payload.get("next_enablement_summary", [])
    ) or "<tr><td colspan='3'>No next enablement candidates</td></tr>"
    german_phrases = ", ".join(german.get("found_forbidden_phrases") or [])
    return f"""
  <h2>Plain-Language Diagnostics</h2>
  <h3>German Body HTML</h3>
  <table border="1" cellspacing="0" cellpadding="6">
    <tbody>
      <tr><th>Blocker</th><td>{escape(str(german.get('blocker_category_label', '')))}</td></tr>
      <tr><th>Plain Reason</th><td>{escape(str(german.get('plain_reason', '')))}</td></tr>
      <tr><th>Forbidden Phrase(s)</th><td>{escape(german_phrases or 'None detected')}</td></tr>
      <tr><th>Forbidden Phrase Repair</th><td>{escape('Applied' if german.get('repair_applied') else ('Not applied' if german.get('repair_attempted') else 'Not needed'))}</td></tr>
      <tr><th>HTML Structure Issue</th><td>{escape(str(german.get('html_structure_issue', False)))}</td></tr>
      <tr><th>Link/Image/Video Mismatch</th><td>{escape(str(german.get('link_image_video_mismatch', False)))}</td></tr>
      <tr><th>Identity Mismatch</th><td>{escape(str(german.get('identity_mismatch', False)))}</td></tr>
      <tr><th>Empty/Missing Digest</th><td>{escape(str(german.get('empty_or_missing_digest', False)))}</td></tr>
    </tbody>
  </table>
  <h3>Needs Review Rows</h3>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Key</th><th>Context</th><th>Plain Reason</th></tr></thead>
    <tbody>{needs_review_rows}</tbody>
  </table>
  <h3>Option Mapping Audit</h3>
  <p>{escape(str(option_audit.get('plain_summary', '')))}</p>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Resource ID</th><th>Key</th><th>Digest</th><th>Option Context</th><th>Mapping</th><th>Future Status</th></tr></thead>
    <tbody>{option_rows}</tbody>
  </table>
  <h3>Next Enablement</h3>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Area</th><th>Status</th><th>Reason</th></tr></thead>
    <tbody>{next_rows}</tbody>
  </table>
"""


def _all_languages_needs_review_html_row(row):
    return (
        "<tr>"
        f"<td>{escape(str(row.get('language_label') or row.get('locale') or ''))}</td>"
        f"<td>{escape(str(row.get('key', '')))}</td>"
        f"<td>{escape(str(row.get('context_label', '')))}</td>"
        f"<td>{escape(str(row.get('plain_reason', '')))}</td>"
        "</tr>"
    )


def _all_languages_option_mapping_html_row(row):
    context = " | ".join(
        str(part)
        for part in (
            row.get("option_name", ""),
            row.get("option_value", ""),
            row.get("context_label", ""),
        )
        if str(part or "").strip()
    )
    return (
        "<tr>"
        f"<td>{escape(str(row.get('language_label') or row.get('locale') or ''))}</td>"
        f"<td>{escape(str(row.get('field_label') or row.get('field') or ''))}</td>"
        f"<td>{escape(str(row.get('resource_id', '')))}</td>"
        f"<td>{escape(str(row.get('key', '')))}</td>"
        f"<td>{escape(str(row.get('digest', '')))}</td>"
        f"<td>{escape(context)}</td>"
        f"<td>{escape(str(row.get('mapping_status_label', '')))}</td>"
        f"<td>{escape(str(row.get('future_update_ready_label', '')))}</td>"
        "</tr>"
    )


def _all_languages_next_enablement_html_row(row):
    return (
        "<tr>"
        f"<td>{escape(str(row.get('area', '')))}</td>"
        f"<td>{escape(str(row.get('status', '')))}</td>"
        f"<td>{escape(str(row.get('plain_reason', '')))}</td>"
        "</tr>"
    )


def _all_languages_update_entry_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('key', '')))}</td>"
        f"<td>{escape(str(entry.get('resource_id', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('manual_edit_used', '')))}</td>"
        f"<td>{escape(str(entry.get('status', '')))}</td>"
        f"<td>{escape(str(entry.get('blocking_reason', '')))}</td>"
        f"<td>{escape(str(entry.get('readback_matched', '')))}</td>"
        f"<td>{escape(str(entry.get('rollback_needed', '')))}</td>"
        "</tr>"
    )


def _all_languages_updated_entry_html_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('language_label', '')))}"
        f"{' (' + escape(str(entry.get('locale', ''))) + ')' if entry.get('locale') else ''}</td>"
        f"<td>{escape(str(entry.get('field_label', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_value', '')))}</td>"
        f"<td>{escape(str(entry.get('confirmed_label', '')))}</td>"
        "</tr>"
    )


def _all_languages_summary_row(item, key_name):
    return (
        "<tr>"
        f"<td>{escape(str(item.get(key_name, '')))}</td>"
        f"<td>{escape(str(item.get('candidate_count', 0)))}</td>"
        f"<td>{escape(str(item.get('write_ready_count', 0)))}</td>"
        f"<td>{escape(str(item.get('updated_count', 0)))}</td>"
        f"<td>{escape(str(item.get('verified_count', 0)))}</td>"
        f"<td>{escape(str(item.get('skipped_count', 0)))}</td>"
        f"<td>{escape(str(item.get('blocked_count', 0)))}</td>"
        f"<td>{escape(str(item.get('review_note_count', 0)))}</td>"
        f"<td>{escape(str(item.get('failed_count', 0)))}</td>"
        "</tr>"
    )


def _selected_translations_entry_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('resource_id', '')))}</td>"
        f"<td>{escape(str(entry.get('key', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('previous_translation_value', '')))}</td>"
        f"<td>{escape(str(entry.get('proposed_translation_value', '')))}</td>"
        f"<td>{escape(str(entry.get('manual_edit_used', '')))}</td>"
        f"<td>{escape(str(entry.get('readback_verified', '')))}</td>"
        f"<td>{escape(str(entry.get('rollback_needed', '')))}</td>"
        f"<td>{escape(str(entry.get('restore_candidate', '')))}</td>"
        "</tr>"
    )


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
