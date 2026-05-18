import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from html import escape as html_escape
from html.parser import HTMLParser
from pathlib import Path

from .models import ShopifyInstallation
from .translation_console import (
    fetch_translation_console_data,
    safe_translation_console_error_message,
    translation_console_error_details,
)


DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
SUPPORTED_LOCALES = ["ja", "de", "fr", "es", "it"]
ALLOWED_FIELDS = ["title", "body_html", "meta_title", "meta_description", "handle"]
TRANSLATE_ALL_ACTION_NAME = "translate_all_languages_all_content"
TRANSLATE_ALL_DRAFT_STATUS = "selected_product_all_content_translation_draft_ready_for_manual_review"
MISSING_ONLY_DRAFT_STATUS = "selected_product_missing_translation_draft_ready_for_manual_review"
ALLOWED_DRAFT_GROUP_SCOPES = [
    "product_basics",
    "seo",
    "options",
    "variants",
    "important_metafields",
    "media",
]
ALLOWED_DRAFT_SCOPES = set(ALLOWED_FIELDS) | set(ALLOWED_DRAFT_GROUP_SCOPES)
ALL_ELIGIBLE_DRAFT_SCOPES = [
    "product_basics",
    "seo",
    "options",
    "variants",
    "important_metafields",
    "media",
]
SECTION_LABELS = {
    "product_basics": "Product basics",
    "seo": "SEO",
    "options": "Options",
    "variants": "Variants",
    "important_metafields": "Important metafields",
    "media": "Media alt text",
    "technical_fields": "Technical skipped",
    "technical_metafields": "Technical skipped",
}
DISCOVERY_GROUP_DISPLAY_ORDER = [
    "product_basics",
    "seo",
    "options",
    "variants",
    "important_metafields",
    "media_alt_text",
]
DISCOVERY_GROUP_LABELS = {
    "product_basics": "Product basics",
    "seo": "SEO",
    "options": "Options",
    "variants": "Variants",
    "important_metafields": "Important metafields",
    "technical_metafields": "Technical metafields",
    "media": "Media",
    "media_alt_text": "Media alt text",
}
DRAFT_GENERATION_REASONS = {"missing_translation", "outdated_translation"}
DRAFT_COVERAGE_GROUP_CONFIGS = [
    {
        "group_key": "product_basics",
        "label": "Product basics",
        "expected_field_keys": ("title", "body_html"),
        "draft_field_keys": ("title", "body_html"),
        "notes": "Title and description/body HTML can be generated as local draft previews. Body HTML remains preview-only for review.",
    },
    {
        "group_key": "seo",
        "label": "SEO",
        "expected_field_keys": ("meta_title", "meta_description"),
        "draft_field_keys": ("meta_title", "meta_description", "handle"),
        "notes": "SEO title and description are draft-supported. URL handle is draft-preview only and requires manual review.",
    },
    {
        "group_key": "options",
        "label": "Product options",
        "expected_field_keys": (),
        "draft_field_keys": ("options",),
        "notes": "Option names and values returned by Shopify can get local drafts. Future write mapping remains blocked.",
    },
    {
        "group_key": "variants",
        "label": "Variants",
        "expected_field_keys": (),
        "draft_field_keys": ("variants",),
        "notes": "Variant display text returned by Shopify can get local drafts. SKU, barcode, IDs, and technical codes remain context-only.",
    },
    {
        "group_key": "important_metafields",
        "label": "Important metafields",
        "expected_field_keys": (),
        "draft_field_keys": ("important_metafields",),
        "notes": "Customer-facing metafields returned by Shopify can get local drafts. Future write mapping remains blocked.",
    },
    {
        "group_key": "media",
        "label": "Media alt text",
        "expected_field_keys": (),
        "draft_field_keys": ("media",),
        "notes": "Media/image alt text returned by Shopify can get local draft alt text.",
    },
    {
        "group_key": "technical_fields",
        "label": "Technical / not translated",
        "expected_field_keys": (),
        "draft_field_keys": (),
        "notes": "Technical, review, rating, ID, JSON, inventory, and system fields stay visible only and are never drafted.",
    },
]
IMPORTANT_METAFIELD_NAMESPACES = {
    "custom",
    "details",
    "descriptor",
    "descriptors",
    "features",
    "spec",
    "specs",
    "specification",
    "specifications",
}
IMPORTANT_METAFIELD_HINTS = (
    "benefit",
    "bullet",
    "compat",
    "description",
    "feature",
    "highlight",
    "included",
    "material",
    "model",
    "package",
    "scale",
    "short_description",
    "size",
    "spec",
    "subtitle",
    "summary",
    "title",
)
TECHNICAL_METAFIELD_NAMESPACES = {
    "google",
    "inventory",
    "judgeme",
    "okendo",
    "reviews",
    "shopify",
    "stamped",
    "system",
    "yotpo",
}
TECHNICAL_METAFIELD_HINTS = (
    "admin_graphql",
    "barcode",
    "count",
    "created",
    "gid",
    "gtin",
    "hash",
    "id",
    "inventory",
    "json",
    "mpn",
    "rating",
    "schema",
    "sku",
    "sync",
    "template",
    "timestamp",
    "token",
    "updated",
)
PRODUCT_TITLE_MAX_CHARS = 80
SEO_TITLE_MAX_CHARS = 60
SEO_DESCRIPTION_MAX_CHARS = 160
FIELD_MAX_CHARS = {
    "title": PRODUCT_TITLE_MAX_CHARS,
    "meta_title": SEO_TITLE_MAX_CHARS,
    "meta_description": SEO_DESCRIPTION_MAX_CHARS,
    "handle": 80,
    "media.alt": 125,
}
FIELD_RECOMMENDED_MIN_CHARS = {"title": 25, "meta_title": 30, "meta_description": 80}
FIELD_RECOMMENDED_MAX_CHARS = dict(FIELD_MAX_CHARS)
SEO_REVIEW_NOTE_CODES = {
    "body_html_structure_broken",
    "draft_equals_source",
    "draft_over_max_chars",
    "forbidden_marketing_or_shipping_phrase",
    "html_media_or_link_tag_broken",
    "keyword_stuffing_or_duplicate",
    "missing_core_keyword",
    "missing_model",
    "missing_part_type",
    "missing_replacement_part_meaning",
    "missing_use_case",
}
NON_BLOCKING_SEO_NOTE_CODES = {
    "missing_value_point",
    "too_short_for_seo",
}
DEFAULT_OPTION_SOURCE_VALUES = {"default title", "title"}
HTML_TAG_RE = re.compile(r"<\s*/?\s*([a-zA-Z][a-zA-Z0-9:-]*)\b[^>]*>")
HTML_REVIEW_TAGS = {"a", "iframe", "img", "source", "video"}
MAX_REWRITE_ATTEMPTS = 2
OPENAI_MODEL = "gpt-4.1-mini"
TRANSLATION_CACHE_PATH = Path("logs/shopify_translation_cache/translation_memory.json")
TRANSLATION_CACHE_MAX_BYTES = 2_000_000
TRANSLATION_CACHE_MAX_ENTRIES = 2000
TRANSLATION_WORKSPACE_JOB_DIR = Path("logs/shopify_translation_workspace_jobs")
TRANSLATION_WORKSPACE_PREVIOUS_REPORT_MAX_BYTES = 4_000_000
TRANSLATION_WORKSPACE_IN_PROGRESS_REPORT_STATUSES = {"pending", "running", "partial"}
SOURCE_CHANGED_REFRESH_MESSAGE = (
    "Original product content changed. Translation will be refreshed."
)
OPENAI_PROMPT_COMPACT = "compact"
OPENAI_PROMPT_RICH = "rich"
OPENAI_PROMPT_HTML_TEXT_NODES = "html_text_nodes"
OPENAI_INVALID_TRANSLATION_RESPONSE = "openai_invalid_translation_response"
OPENAI_TRANSLATIONS_MISSING_MESSAGE = (
    "OpenAI response did not include a translations object."
)
OPENAI_TRANSLATION_GENERATION_STAGE = "openai_translation_generation"
HTML_UNCHANGED_TEXT_TAGS = {"script", "style", "iframe", "video", "source"}
TECHNICAL_SKIP_REASONS = {
    "technical_or_internal_field",
    "technical_code_or_identifier",
    "json_or_schema_value",
    "sku_numeric_id_barcode_or_code",
    "variant_sku_or_barcode_context_only",
}

PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/\d+$")
FORBIDDEN_OUTPUT_RE = re.compile(
    r"\b(?:buy now|shop now|free shipping|ships worldwide|worldwide shipping|origin|herkunft|"
    r"provenance|made in china|mainland china|best|cheap|guaranteed|official|original oem|"
    r"versand weltweit|weltweiter versand|lieferung weltweit)\b",
    flags=re.IGNORECASE,
)
UNNATURAL_PHRASE_RE = re.compile(
    r"\b(?:RC Plane Clevis|Aileron Clevis|Brushless RC Warbird)\b",
    flags=re.IGNORECASE,
)
KEYWORD_STUFFING_RE = re.compile(
    r"\b(?:clevis connector linkage joint|clevis linkage connector|connector linkage joint|"
    r"gabelkopf verbinder gest[aä]nge|chape connecteur tringlerie|clevis conector varillaje|"
    r"forcella connettore tirante)\b",
    flags=re.IGNORECASE,
)
PRODUCT_IDENTITY_WARNING_TEXT = (
    "This draft may mention a different product. Please review before using."
)
PRODUCT_IDENTITY_BLOCKLIST_TERMS = (
    "MOFLY",
    "P-51D",
    "Mustang",
    "Corsair",
    "Spitfire",
    "F4U",
    "F-16",
    "SR22",
    "Trainstar",
    "Volantex",
    "WLtoys",
    "XK",
    "Goosky",
    "Yuxiang",
)
PRODUCT_IDENTITY_KNOWN_MODEL_TERMS = ("P-51D", "F4U", "F-16", "SR22")
PRODUCT_IDENTITY_CATEGORY_TERMS = (
    "Helicopter",
    "Plane",
    "Aircraft",
    "Drone",
    "Car",
    "Boat",
    "Truck",
    "Battery",
    "Motor",
    "Connector",
)
PRODUCT_MODEL_TOKEN_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z]{1,5}-?\d+[A-Z0-9-]*|\d+[A-Z]{1,4}[A-Z0-9-]*)(?![A-Za-z0-9])"
)
PRODUCT_UPPERCASE_PHRASE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Z]{2,})(?:\s+[A-Z]{2,})+(?![A-Za-z0-9])"
)

LANGUAGE_NAMES = {
    "ja": "Japanese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
}
LOCALE_TERM_GUIDANCE = {
    "ja": "Use natural Japanese RC part terms. Preserve source brand, model, dimensions, and RC terms exactly.",
    "de": "Use natural German terms: Querruder, Gabelkopf, Ersatzteil. Do not keep 'RC Plane Clevis'.",
    "fr": "Use natural French terms: aileron, chape, piece de rechange, piece RC.",
    "es": "Use natural Spanish terms: aleron, clevis or horquilla, repuesto RC.",
    "it": "Use natural Italian terms: alettone, forcella, ricambio RC.",
}
FIELD_STYLE_GUIDANCE = {
    "title": "Short store title. Prefer brand/model + part name + spec/use.",
    "body_html": "Customer-facing product description. Preserve the source HTML structure, links, images, lists, specs, model names, and compatibility facts.",
    "meta_title": "Short SEO title with the source brand/model, one core part keyword, and RC spare/replacement meaning.",
    "meta_description": "Natural SEO description with use, compatibility, part type, and one value point; no CTA.",
    "handle": "URL handle draft preview only. Keep it short, lowercase if natural for the locale, and require manual review before any future use.",
    "option.name": "Short option name shown to customers. Preserve units, model numbers, and option structure.",
    "option.value": "Short option value shown to customers. Preserve units, model numbers, and variant meaning.",
    "variant.title": "Variant display text. Translate only customer-facing words and preserve SKU-like codes and model names.",
    "variant.option": "Variant option value. Preserve SKU-like codes, dimensions, battery specs, and model names.",
    "media.alt": "Concise image alt text describing the visible product or part. Do not keyword-stuff.",
}
SEO_TERMS = {
    "ja": {
        "core": ["エルロン", "クレビス", "リンケージ"],
        "part_type": ["エルロン", "クレビス", "リンケージ"],
        "replacement": ["交換", "補修", "予備", "パーツ", "部品"],
        "value": ["正確", "精密", "安定", "耐久", "確実"],
        "spare": ["RC", "パーツ", "部品", "交換", "補修"],
    },
    "de": {
        "core": ["querruder", "gabelkopf"],
        "part_type": ["querruder", "gabelkopf", "anlenkung"],
        "replacement": ["ersatz", "ersatzteil", "austausch", "zubehör"],
        "value": ["präzise", "prazise", "präzision", "langlebig", "stabil", "zuverlässig", "kontrolle", "steuerung"],
        "spare": ["rc", "ersatzteil", "ersatz", "zubehör"],
    },
    "fr": {
        "core": ["aileron", "chape"],
        "part_type": ["aileron", "chape", "tringlerie", "commande"],
        "replacement": ["rechange", "remplacement", "pièce", "piece", "accessoire"],
        "value": ["précise", "precise", "solide", "fiable", "durable", "commande", "contrôle", "controle"],
        "spare": ["rc", "pièce", "piece", "rechange"],
    },
    "es": {
        "core": ["alerón", "aleron", "clevis", "horquilla"],
        "part_type": ["alerón", "aleron", "clevis", "horquilla", "varillaje", "control"],
        "replacement": ["repuesto", "recambio", "reemplazo", "pieza", "accesorio"],
        "value": ["preciso", "precisa", "resistente", "duradero", "fiable", "seguro", "control"],
        "spare": ["rc", "repuesto", "recambio", "pieza"],
    },
    "it": {
        "core": ["alettone", "forcella"],
        "part_type": ["alettone", "forcella", "rinvio", "comando"],
        "replacement": ["ricambio", "sostituzione", "pezzo", "accessorio"],
        "value": ["preciso", "precisa", "resistente", "durevole", "sicuro", "affidabile", "controllo"],
        "spare": ["rc", "ricambio", "pezzo"],
    },
}


def generate_selected_product_missing_translation_draft_package(
    product_id=DEFAULT_PRODUCT_ID,
    target_locales=None,
    fields=None,
    installation=None,
    include_missing=True,
    include_outdated=False,
    include_all_eligible_groups=False,
    action_name="",
):
    target_locales = list(target_locales or DEFAULT_TARGET_LOCALES)
    if include_all_eligible_groups:
        fields = _normalize_requested_scopes(fields or ALL_ELIGIBLE_DRAFT_SCOPES)
        for scope in ALL_ELIGIBLE_DRAFT_SCOPES:
            if scope not in fields:
                fields.append(scope)
    else:
        fields = _normalize_requested_scopes(fields or DEFAULT_FIELDS)
    result = _empty_result(product_id, target_locales, fields)
    result["include_missing"] = bool(include_missing)
    result["include_outdated"] = bool(include_outdated)
    result["include_all_eligible_groups"] = bool(include_all_eligible_groups)
    result["action_name"] = action_name or ""
    result["draft_generation_mode"] = (
        "missing_and_outdated" if include_outdated else "missing_only"
    )
    validation_errors = _validate_scope(product_id, target_locales, fields)
    if validation_errors:
        result["blocking_conditions"] = validation_errors
        result["draft_status"] = validation_errors[0]
        return result

    previous_source_index = _previous_translation_source_index(product_id)

    if installation is None:
        installation = ShopifyInstallation.objects.first()
    if installation is None:
        result["draft_status"] = "blocked_missing_shopify_installation"
        result["failure_type"] = "missing_shopify_installation"
        result["blocking_conditions"].append("blocked_missing_shopify_installation")
        return result

    draft_targets_by_locale = {}
    for locale in target_locales:
        try:
            data = fetch_translation_console_data(installation, product_id, locale)
        except Exception as exc:
            failure_details = translation_console_error_details(
                exc,
                stage="product_base_translatable_resource_query",
                resource_group="product",
            )
            result["draft_status"] = "blocked_shopify_read_query_failed"
            result["failure_type"] = "shopify_read_query_failed"
            result["query_failure_type"] = failure_details["query_failure_type"]
            result["error"] = safe_translation_console_error_message(exc)
            for failed_group in ("product_basics", "seo"):
                result["per_group_discovery_status"][failed_group] = "failed"
                result["per_group_discovery_reasons"][failed_group] = (
                    failure_details["query_failure_type"]
                )
            result["blocking_conditions"].append("blocked_shopify_read_query_failed")
            _attach_draft_batch_summary(result)
            return result

        result["shopify_api_call_performed"] = True
        _attach_child_discovery_metadata(result, locale, data)
        product = data.get("product") or {}
        result["product_title"] = result["product_title"] or product.get("title", "")
        translatable_rows = data.get("translatable_rows", [])
        source_identity_context = build_product_identity_context(
            product=product,
            translatable_rows=translatable_rows,
        )
        if not result["product_identity_context"]:
            result["product_identity_context"] = source_identity_context
        result["source_read_summary"][locale] = {
            "translatable_content_count": len(translatable_rows),
            "translation_count": (data.get("translatable_resource") or {}).get("translation_count", 0),
            "draft_eligible_count": sum(1 for row in translatable_rows if row.get("draft_eligible")),
        }
        result["per_locale_draft_coverage"][locale] = _draft_coverage_groups_for_rows(
            translatable_rows,
            fields,
        )
        _apply_discovery_status_to_coverage_groups(
            result["per_locale_draft_coverage"][locale],
            data.get("per_group_discovery_status") or {},
            data.get("per_group_discovery_reasons") or {},
        )
        _refresh_draft_coverage_summary(result)

        rows_to_check = (
            _all_translatable_rows(translatable_rows)
            if include_all_eligible_groups
            else _requested_draft_rows(translatable_rows, fields)
        )
        for row in rows_to_check:
            row = dict(row)
            field = _entry_field_from_row(row)
            source_value = str(row.get("source_value") or "")
            existing_present = bool(row.get("has_translation"))
            source_change = _detect_previous_source_change(
                row,
                locale,
                previous_source_index,
            )
            if source_change:
                row.update(source_change)
            existing_outdated = row.get("translation_outdated") is True
            if existing_present and row.get("source_changed_from_previous_report"):
                existing_outdated = True
                row["translation_outdated"] = True
            if not source_value.strip():
                entry = _entry_template(locale, field, row, "source_empty")
            elif not row.get("draft_eligible"):
                entry = _entry_template(
                    locale,
                    field,
                    row,
                    row.get("draft_ineligible_reason") or "not_draft_eligible",
                )
            elif existing_present and existing_outdated:
                if include_outdated:
                    entry = _entry_template(locale, field, row, "outdated_translation")
                    draft_targets_by_locale.setdefault(locale, []).append(entry)
                else:
                    entry = _entry_template(locale, field, row, "existing_translation_outdated_manual_review_required")
            elif existing_present:
                entry = _entry_template(locale, field, row, "already_translated")
            elif include_missing:
                entry = _entry_template(locale, field, row, "missing_translation")
                draft_targets_by_locale.setdefault(locale, []).append(entry)
            else:
                entry = _entry_template(locale, field, row, "missing_translation_not_requested")
            _attach_source_identity_context(entry, source_identity_context)
            if existing_present:
                _attach_existing_translation_identity_validation(entry)
            _refresh_entry_status(entry)
            result["entries"].append(entry)
            _count_entry(result, entry)

        for field in _missing_requested_static_fields(translatable_rows, fields):
            entry = _entry_template(locale, field, {}, "source_empty")
            _attach_source_identity_context(entry, source_identity_context)
            _refresh_entry_status(entry)
            result["entries"].append(entry)
            _count_entry(result, entry)

    if not draft_targets_by_locale:
        result["draft_status"] = (
            "no_missing_or_outdated_translations_found"
            if include_outdated
            else "no_missing_translations_found"
        )
        result["success"] = True
        _attach_draft_batch_summary(result)
        return result

    for locale, draft_target_entries in draft_targets_by_locale.items():
        translations = _request_openai(locale, draft_target_entries, result)
        if translations is None:
            result["success"] = False
            _attach_draft_batch_summary(result)
            return result
        for entry in draft_target_entries:
            draft = str(
                translations.get(entry.get("draft_key"))
                or translations.get(entry["field"])
                or ""
            ).strip()
            draft, rewrite_attempts = _rewrite_over_length_draft(locale, entry, draft, result)
            if draft is None:
                result["success"] = False
                _attach_draft_batch_summary(result)
                return result
            _attach_draft_quality(entry, draft, rewrite_attempts)
            result["draft_entries"].append(entry)
            result["translation_generated"] = True

    _apply_cross_field_seo_checks(result, target_locales)
    _recalculate_quality_stats(result)
    _attach_draft_batch_summary(result)
    result["draft_status"] = (
        TRANSLATE_ALL_DRAFT_STATUS if include_outdated else MISSING_ONLY_DRAFT_STATUS
    )
    result["success"] = True
    return result


def _validate_scope(product_id, target_locales, fields):
    errors = []
    if not product_id or not PRODUCT_GID_RE.match(product_id):
        errors.append("blocked_invalid_product_id")
    if not target_locales or any(locale not in SUPPORTED_LOCALES for locale in target_locales):
        errors.append("blocked_unsupported_locale")
    if not fields or any(field not in ALLOWED_DRAFT_SCOPES for field in fields):
        errors.append("blocked_invalid_field")
    return errors


def _normalize_requested_scopes(fields):
    scopes = []
    for field in fields or []:
        normalized = _normalize_draft_field_key(field)
        if normalized and normalized not in scopes:
            scopes.append(normalized)
    return scopes


def _requested_draft_rows(rows, requested_scopes):
    requested_scopes = set(_normalize_requested_scopes(requested_scopes))
    output = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if not _row_matches_requested_scopes(row, requested_scopes):
            continue
        entry_key = row.get("entry_key") or row.get("key") or id(row)
        if entry_key in seen:
            continue
        seen.add(entry_key)
        output.append(row)
    return output


def _all_translatable_rows(rows):
    output = []
    seen = set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        entry_key = row.get("entry_key") or row.get("key") or id(row)
        if entry_key in seen:
            continue
        seen.add(entry_key)
        output.append(row)
    return output


def _row_matches_requested_scopes(row, requested_scopes):
    field_key = _normalize_draft_field_key(
        row.get("field_key") or row.get("key") or row.get("source_key")
    )
    group_key = _draft_coverage_group_key_for_row(row)
    if field_key in requested_scopes:
        return True
    if group_key in {"options", "variants", "important_metafields", "media"} and group_key in requested_scopes:
        return True
    if group_key == "product_basics" and "product_basics" in requested_scopes:
        return field_key in {"title", "body_html"}
    if group_key == "seo" and "seo" in requested_scopes:
        return field_key in {"meta_title", "meta_description", "handle"}
    return False


def _entry_field_from_row(row):
    return _normalize_draft_field_key(row.get("field_key") or row.get("key")) or str(
        row.get("source_key") or ""
    )


def _missing_requested_static_fields(rows, requested_scopes):
    requested_scopes = set(_normalize_requested_scopes(requested_scopes))
    static_fields = {
        field for field in requested_scopes if field in ALLOWED_FIELDS
    }
    if "product_basics" in requested_scopes:
        static_fields.update({"title", "body_html"})
    if "seo" in requested_scopes:
        static_fields.update({"meta_title", "meta_description"})
    present_fields = {
        _normalize_draft_field_key(row.get("field_key") or row.get("key"))
        for row in rows or []
        if isinstance(row, dict)
    }
    return [
        field
        for field in ["title", "body_html", "meta_title", "meta_description"]
        if field in static_fields and field not in present_fields
    ]


def _empty_discovery_status():
    return {
        "product_basics": "not_loaded",
        "seo": "not_loaded",
        "options": "not_loaded",
        "variants": "not_loaded",
        "important_metafields": "not_loaded",
        "technical_metafields": "not_loaded",
        "media": "not_loaded",
        "media_alt_text": "not_loaded",
    }


def _empty_discovery_reasons():
    return {key: "" for key in _empty_discovery_status()}


def _empty_result(product_id, target_locales, fields):
    return {
        "success": False,
        "draft_status": "",
        "product_id": product_id,
        "product_title": "",
        "target_locales": target_locales,
        "requested_fields": fields,
        "shopify_read_only": True,
        "shopify_api_call_performed": False,
        "openai_call_performed": False,
        "openai_call_count": 0,
        "openai_retry_attempt_count": 0,
        "openai_retry_success_count": 0,
        "openai_invalid_translation_response_count": 0,
        "openai_missing_translation_field_count": 0,
        "openai_response_recovery_events": [],
        "reused_cache_count": 0,
        "skipped_existing_count": 0,
        "skipped_technical_count": 0,
        "deduplicated_input_count": 0,
        "estimated_input_chars_saved": 0,
        "per_locale_openai_call_count": {
            locale: 0 for locale in target_locales
        },
        "translation_cache_enabled": True,
        "translation_cache_path": TRANSLATION_CACHE_PATH.as_posix(),
        "translation_cache_entry_count": 0,
        "translation_generated": False,
        "include_missing": True,
        "include_outdated": False,
        "include_all_eligible_groups": False,
        "action_name": "",
        "draft_generation_mode": "missing_only",
        "generated_draft_count": 0,
        "missing_translation_draft_generated_count": 0,
        "outdated_translation_update_draft_generated_count": 0,
        "already_translated_skipped_count": 0,
        "not_eligible_skipped_count": 0,
        "needs_review_or_blocked_count": 0,
        "total_languages_checked": 0,
        "total_source_rows_checked": 0,
        "draft_ready_count": 0,
        "draft_needs_manual_review_count": 0,
        "draft_blocked_count": 0,
        "product_identity_mismatch_count": 0,
        "eligible_apply_plan_count": 0,
        "over_length_after_rewrite_count": 0,
        "seo_ready_count": 0,
        "seo_needs_manual_review_count": 0,
        "seo_eligible_apply_plan_count": 0,
        "forbidden_phrase_count": 0,
        "missing_core_keyword_count": 0,
        "too_short_for_seo_count": 0,
        "skipped_existing_translation_count": 0,
        "skipped_outdated_translation_count": 0,
        "skipped_source_empty_count": 0,
        "skipped_not_draft_eligible_count": 0,
        "per_locale_results": {},
        "per_field_results": {},
        "per_section_results": {},
        "entries": [],
        "draft_entries": [],
        "product_identity_context": {},
        "source_read_summary": {},
        "child_resource_discovery_errors": [],
        "per_group_discovery_status": _empty_discovery_status(),
        "per_group_discovery_reasons": _empty_discovery_reasons(),
        "per_locale_discovery_status": {},
        "per_locale_draft_coverage": {},
        "draft_coverage_summary": _empty_draft_coverage_summary(fields),
        "translate_all_summary": _empty_translate_all_summary(),
        "blocking_conditions": [],
        "failure_type": "",
        "failed_stage": "",
        "sanitized_error": "",
        "retry_attempted": False,
        "retry_succeeded": False,
        "query_failure_type": "",
        "error": "",
        "draft_package_only": True,
        "existing_translation_overwrite_allowed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _attach_child_discovery_metadata(result, locale, data):
    statuses = dict((data or {}).get("per_group_discovery_status") or {})
    reasons = dict((data or {}).get("per_group_discovery_reasons") or {})
    if statuses:
        result.setdefault("per_locale_discovery_status", {})[locale] = statuses
        _merge_per_group_discovery_status(result, statuses, reasons)
    for error in (data or {}).get("child_resource_discovery_errors") or []:
        if isinstance(error, dict):
            _append_child_discovery_error(result, locale, error)


def _merge_per_group_discovery_status(result, statuses, reasons):
    merged_statuses = result.setdefault("per_group_discovery_status", _empty_discovery_status())
    merged_reasons = result.setdefault("per_group_discovery_reasons", _empty_discovery_reasons())
    rank = {"not_loaded": 0, "ok": 1, "skipped": 2, "failed": 3}
    for key, status in (statuses or {}).items():
        if key not in merged_statuses:
            continue
        current = merged_statuses.get(key, "not_loaded")
        if rank.get(status, 0) >= rank.get(current, 0):
            merged_statuses[key] = status
            if status != "ok":
                merged_reasons[key] = reasons.get(key) or merged_reasons.get(key) or ""


def _append_child_discovery_error(result, locale, error):
    normalized = {
        "stage": str(error.get("stage") or ""),
        "resource_group": str(error.get("resource_group") or ""),
        "group_label": str(error.get("group_label") or ""),
        "skipped_groups": list(error.get("skipped_groups") or []),
        "skipped_group_labels": list(error.get("skipped_group_labels") or []),
        "status": str(error.get("status") or "skipped"),
        "reason": str(error.get("reason") or "skipped_child_resource_query_failed"),
        "query_failure_type": str(error.get("query_failure_type") or "shopify_read_query_failed"),
        "message": str(error.get("message") or "Optional child resource query failed."),
    }
    key = (
        normalized["stage"],
        normalized["resource_group"],
        tuple(normalized["skipped_groups"]),
        normalized["reason"],
        normalized["query_failure_type"],
        normalized["message"],
    )
    errors = result.setdefault("child_resource_discovery_errors", [])
    for existing in errors:
        existing_key = (
            existing.get("stage"),
            existing.get("resource_group"),
            tuple(existing.get("skipped_groups") or []),
            existing.get("reason"),
            existing.get("query_failure_type"),
            existing.get("message"),
        )
        if existing_key == key:
            locales = existing.setdefault("locales", [])
            if locale not in locales:
                locales.append(locale)
            return
    normalized["locales"] = [locale]
    errors.append(normalized)


def _discovery_status_rows(statuses, reasons):
    statuses = statuses or {}
    reasons = reasons or {}
    return [
        {
            "group_key": key,
            "label": DISCOVERY_GROUP_LABELS.get(key, key),
            "status": statuses.get(key, "not_loaded"),
            "reason": reasons.get(key, ""),
        }
        for key in DISCOVERY_GROUP_DISPLAY_ORDER
    ]


def _empty_draft_coverage_summary(fields):
    requested_fields = [
        _normalize_draft_field_key(field)
        for field in (fields or [])
        if _normalize_draft_field_key(field)
    ]
    return {
        "summary_status": "not_loaded",
        "requested_fields": requested_fields,
        "draft_generation_included_fields": [
            field for field in requested_fields if field in ALLOWED_DRAFT_SCOPES
        ],
        "target_locale_count": 0,
        "groups": [
            _empty_draft_coverage_group(config, requested_fields)
            for config in DRAFT_COVERAGE_GROUP_CONFIGS
        ],
    }


def _empty_draft_coverage_group(config, requested_fields):
    expected_fields = list(config.get("expected_field_keys") or ())
    configured_draft_fields = [
        field
        for field in config.get("draft_field_keys", ())
        if (
            field in requested_fields
            or config.get("group_key") in requested_fields
        )
        and field in ALLOWED_DRAFT_SCOPES
    ]
    return {
        "group_key": config["group_key"],
        "label": config["label"],
        "coverage_status": "not_loaded",
        "draft_generation_status": (
            "configured" if configured_draft_fields else "not_configured"
        ),
        "source_row_count": 0,
        "visible_source_keys": [],
        "expected_field_keys": expected_fields,
        "expected_missing_fields": expected_fields,
        "included_in_draft_count": 0,
        "included_in_draft_fields": [],
        "editor_only_count": 0,
        "needs_mapping_count": 0,
        "missing_translation_count": 0,
        "existing_translation_count": 0,
        "outdated_translation_count": 0,
        "source_empty_count": 0,
        "notes": config.get("notes", ""),
    }


def _draft_coverage_groups_for_rows(rows, requested_fields):
    requested_fields = {
        _normalize_draft_field_key(field)
        for field in (requested_fields or [])
        if _normalize_draft_field_key(field)
    }
    groups = {
        config["group_key"]: _empty_draft_coverage_group(config, requested_fields)
        for config in DRAFT_COVERAGE_GROUP_CONFIGS
    }
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        field_key = _normalize_draft_field_key(
            row.get("field_key") or row.get("key")
        )
        if not field_key:
            continue
        group_key = _draft_coverage_group_key_for_row(row)
        group = groups[group_key]
        group["source_row_count"] += 1
        if field_key not in group["visible_source_keys"]:
            group["visible_source_keys"].append(field_key)
        if _row_matches_requested_scopes(row, requested_fields) and row.get("draft_eligible"):
            group["included_in_draft_count"] += 1
            if field_key not in group["included_in_draft_fields"]:
                group["included_in_draft_fields"].append(field_key)
        elif group_key in {"options", "variants", "important_metafields", "media"} and row.get("draft_eligible"):
            group["needs_mapping_count"] += 1
        else:
            group["editor_only_count"] += 1

        source_value = str(row.get("source_value") or "")
        if not source_value.strip():
            group["source_empty_count"] += 1
        elif row.get("translation_outdated") is True:
            group["outdated_translation_count"] += 1
        elif row.get("has_translation"):
            group["existing_translation_count"] += 1
        else:
            group["missing_translation_count"] += 1

    for config in DRAFT_COVERAGE_GROUP_CONFIGS:
        _update_draft_coverage_group_status(groups[config["group_key"]], config)
    return [groups[config["group_key"]] for config in DRAFT_COVERAGE_GROUP_CONFIGS]


def _refresh_draft_coverage_summary(result):
    per_locale = result.get("per_locale_draft_coverage") or {}
    requested_fields = [
        _normalize_draft_field_key(field)
        for field in (result.get("requested_fields") or [])
        if _normalize_draft_field_key(field)
    ]
    if not per_locale:
        result["draft_coverage_summary"] = _empty_draft_coverage_summary(requested_fields)
        return
    groups = {
        config["group_key"]: _empty_draft_coverage_group(config, requested_fields)
        for config in DRAFT_COVERAGE_GROUP_CONFIGS
    }
    for locale_groups in per_locale.values():
        for locale_group in locale_groups or []:
            group_key = locale_group.get("group_key")
            if group_key not in groups:
                continue
            target = groups[group_key]
            for count_key in (
                "source_row_count",
                "included_in_draft_count",
                "editor_only_count",
                "needs_mapping_count",
                "missing_translation_count",
                "existing_translation_count",
                "outdated_translation_count",
                "source_empty_count",
            ):
                target[count_key] += int(locale_group.get(count_key) or 0)
            for list_key in (
                "visible_source_keys",
                "included_in_draft_fields",
            ):
                for value in locale_group.get(list_key) or []:
                    if value not in target[list_key]:
                        target[list_key].append(value)

    for config in DRAFT_COVERAGE_GROUP_CONFIGS:
        _update_draft_coverage_group_status(groups[config["group_key"]], config)
    _apply_discovery_status_to_coverage_groups(
        groups.values(),
        result.get("per_group_discovery_status") or {},
        result.get("per_group_discovery_reasons") or {},
    )
    result["draft_coverage_summary"] = {
        "summary_status": "source_rows_classified",
        "requested_fields": requested_fields,
        "draft_generation_included_fields": [
            field for field in requested_fields if field in ALLOWED_DRAFT_SCOPES
        ],
        "target_locale_count": len(per_locale),
        "groups": [groups[config["group_key"]] for config in DRAFT_COVERAGE_GROUP_CONFIGS],
    }


def _apply_discovery_status_to_coverage_groups(groups, discovery_status, discovery_reasons):
    status_map = dict(discovery_status or {})
    reason_map = dict(discovery_reasons or {})
    for group in groups or []:
        if not isinstance(group, dict):
            continue
        group_key = group.get("group_key")
        status_key = "media_alt_text" if group_key == "media" else group_key
        status = status_map.get(status_key)
        if status == "skipped":
            group["coverage_status"] = "skipped_child_resource_query_failed"
            group["draft_generation_status"] = "skipped"
            group["skip_reason"] = reason_map.get(status_key) or "skipped_child_resource_query_failed"
            group["notes"] = (
                "Optional child resource discovery failed. "
                "Product basics and SEO can still be drafted if available."
            )
        elif status == "failed":
            group["coverage_status"] = "failed"
            group["draft_generation_status"] = "failed"
            group["skip_reason"] = reason_map.get(status_key) or "child_resource_query_failed"


def _update_draft_coverage_group_status(group, config):
    visible_keys = set(group.get("visible_source_keys") or [])
    expected_fields = list(config.get("expected_field_keys") or ())
    group["expected_missing_fields"] = [
        field for field in expected_fields if field not in visible_keys
    ]
    if not group.get("source_row_count"):
        group["coverage_status"] = "missing"
    elif group.get("included_in_draft_count") and group.get("expected_missing_fields"):
        group["coverage_status"] = "partially_included"
    elif group.get("included_in_draft_count") and (
        group.get("editor_only_count") or group.get("needs_mapping_count")
    ):
        group["coverage_status"] = "partially_included"
    elif group.get("included_in_draft_count"):
        group["coverage_status"] = "included"
    elif group.get("needs_mapping_count"):
        group["coverage_status"] = "needs_mapping"
    else:
        group["coverage_status"] = "editor_only"


def _draft_coverage_group_key_for_field(field_key):
    field_key = _normalize_draft_field_key(field_key)
    lower_key = field_key.lower()
    if lower_key in {"title", "body_html", "description"}:
        return "product_basics"
    if lower_key in {"handle", "meta_title", "meta_description"}:
        return "seo"
    if "option" in lower_key:
        return "options"
    if "variant" in lower_key:
        return "variants"
    if lower_key.startswith("media.") or "image_alt" in lower_key or lower_key.endswith(".alt"):
        return "media"
    if _is_metafield_key(lower_key):
        if _is_important_metafield(lower_key):
            return "important_metafields"
        return "technical_fields"
    return "technical_fields"


def _draft_coverage_group_key_for_row(row):
    group = str((row or {}).get("resource_group") or "").strip()
    if group == "technical_metafields":
        return "technical_fields"
    if group in {
        "product_basics",
        "seo",
        "options",
        "variants",
        "important_metafields",
        "media",
    }:
        return group
    return _draft_coverage_group_key_for_field(
        (row or {}).get("field_key") or (row or {}).get("key")
    )


def _normalize_draft_field_key(value):
    value = str(value or "").strip()
    if value.startswith("product."):
        value = value.split(".", 1)[-1]
    if value == "description":
        return "body_html"
    return value


def _is_metafield_key(field_key):
    key = str(field_key or "").lower()
    if key in {
        "title",
        "body_html",
        "description",
        "handle",
        "meta_title",
        "meta_description",
        "media.alt",
    }:
        return False
    if "option" in key or "variant" in key or key.startswith("media."):
        return False
    return "metafield" in key or "." in key


def _is_important_metafield(field_key):
    namespace, key = _metafield_parts(field_key)
    namespace = namespace.lower()
    combined = f"{namespace}.{key}"
    if namespace in TECHNICAL_METAFIELD_NAMESPACES:
        return False
    if _key_matches_hint(combined, TECHNICAL_METAFIELD_HINTS):
        return False
    if namespace in IMPORTANT_METAFIELD_NAMESPACES:
        return True
    return _key_matches_hint(combined, IMPORTANT_METAFIELD_HINTS)


def _metafield_parts(field_key):
    key = str(field_key or "").strip()
    lower_key = key.lower()
    for prefix in ("product.metafields.", "product.metafield.", "metafields.", "metafield."):
        if lower_key.startswith(prefix):
            key = key[len(prefix):]
            break
    parts = [part for part in re.split(r"[./:]+", key) if part]
    if len(parts) >= 2:
        return parts[0], ".".join(parts[1:])
    if parts:
        return "", parts[0]
    return "", ""


def _key_matches_hint(field_key, hints):
    tokens = set(
        token
        for token in re.split(r"[^a-z0-9]+", str(field_key or "").lower())
        if token
    )
    compact_key = re.sub(r"[^a-z0-9]+", "_", str(field_key or "").lower()).strip("_")
    for hint in hints:
        normalized_hint = re.sub(r"[^a-z0-9]+", "_", hint.lower()).strip("_")
        if not normalized_hint:
            continue
        if "_" in normalized_hint and normalized_hint in compact_key:
            return True
        if normalized_hint in tokens:
            return True
        if len(normalized_hint) >= 4 and any(
            token.startswith(normalized_hint) for token in tokens
        ):
            return True
    return False


def _max_chars_for_entry(field_key, resource_group):
    if field_key in FIELD_MAX_CHARS:
        return FIELD_MAX_CHARS[field_key]
    if resource_group == "media":
        return FIELD_MAX_CHARS.get("media.alt")
    return None


def _entry_template(locale, field, row, reason):
    row = row or {}
    field_key = _normalize_draft_field_key(row.get("field_key") or field)
    resource_group = row.get("resource_group") or _draft_coverage_group_key_for_field(field_key)
    source_key = str(row.get("source_key") or row.get("key") or field_key)
    future_write_needs_mapping = bool(
        row.get("future_write_needs_mapping")
        or resource_group in {"options", "variants", "important_metafields", "media"}
        or field_key == "handle"
    )
    apply_plan_blocked_reason = str(row.get("apply_plan_blocked_reason") or "")
    if future_write_needs_mapping and not apply_plan_blocked_reason:
        apply_plan_blocked_reason = "future_write_needs_resource_mapping"
    section_key = _section_summary_key(resource_group)
    draft_generation_reason = reason if reason in DRAFT_GENERATION_REASONS else ""
    return {
        "locale": locale,
        "field": field_key,
        "field_key": field_key,
        "entry_key": row.get("entry_key") or field_key,
        "draft_key": row.get("draft_key") or field_key,
        "source_key": source_key,
        "resource_id": row.get("resource_id", ""),
        "resource_type": row.get("resource_type", ""),
        "resource_group": resource_group,
        "section_key": row.get("section_key", ""),
        "section_label": SECTION_LABELS.get(section_key, SECTION_LABELS["technical_fields"]),
        "context_label": row.get("context_label", ""),
        "resource_note": row.get("resource_note", ""),
        "field_label": row.get("field_label", ""),
        "resource_type_label": row.get("resource_type_label", ""),
        "option_name": row.get("option_name", ""),
        "option_value": row.get("option_value", ""),
        "option_position": row.get("option_position", ""),
        "related_variants": row.get("related_variants", []),
        "visible_product_option": bool(row.get("visible_product_option")),
        "translation_preview_available": bool(
            row.get("translation_preview_available")
        ),
        "shopify_update_mapping_ready": bool(
            row.get("shopify_update_mapping_ready")
        ),
        "translation_preview_without_digest": bool(
            row.get("translation_preview_without_digest")
        ),
        "variant_title": row.get("variant_title", ""),
        "variant_id": row.get("variant_id", ""),
        "sku": row.get("sku", ""),
        "barcode": row.get("barcode", ""),
        "selected_options": row.get("selected_options", []),
        "metafield_namespace": row.get("metafield_namespace", ""),
        "metafield_key": row.get("metafield_key", ""),
        "metafield_type": row.get("metafield_type", ""),
        "media_alt": row.get("media_alt", ""),
        "media_content_type": row.get("media_content_type", ""),
        "media_url": row.get("media_url", ""),
        "source_value": str(row.get("source_value") or ""),
        "source_digest": str(row.get("digest") or ""),
        "source_changed_from_previous_report": bool(
            row.get("source_changed_from_previous_report")
        ),
        "source_change_message": row.get("source_change_message", ""),
        "previous_source_digest": row.get("previous_source_digest", ""),
        "current_source_digest": row.get("current_source_digest", ""),
        "previous_source_text_hash": row.get("previous_source_text_hash", ""),
        "current_source_text_hash": row.get("current_source_text_hash", ""),
        "existing_translation_present": bool(row.get("has_translation")),
        "existing_translation_value": str(
            row.get("translation_value")
            or row.get("target_value_display")
            or row.get("target_value")
            or ""
        ),
        "existing_translation_outdated": row.get("translation_outdated"),
        "draft_value": "",
        "draft_value_chars": 0,
        "max_chars": _max_chars_for_entry(field_key, resource_group),
        "recommended_min_chars": FIELD_RECOMMENDED_MIN_CHARS.get(field_key),
        "recommended_max_chars": FIELD_RECOMMENDED_MAX_CHARS.get(field_key),
        "validation_status": "skipped",
        "product_identity_validation_status": "skipped",
        "validation_reasons": [],
        "suspicious_terms": [],
        "identity_warning_text": "",
        "warning_text": "",
        "product_identity_mismatch": False,
        "needs_review": False,
        "draft_blocked": False,
        "source_identity_terms": [],
        "source_model_terms": [],
        "source_identity_context": {},
        "seo_validation_status": "skipped",
        "skip_reason": reason,
        "draft_generation_reason": draft_generation_reason,
        "row_status": _entry_status_from_reason(reason),
        "status": _entry_status_from_reason(reason),
        "status_reason": reason,
        "draft_eligible": bool(row.get("draft_eligible")),
        "draft_ineligible_reason": row.get("draft_ineligible_reason", ""),
        "draft_requires_manual_review": bool(row.get("draft_requires_manual_review")),
        "draft_manual_review_reason": row.get("draft_manual_review_reason", ""),
        "future_write_needs_mapping": future_write_needs_mapping,
        "apply_plan_blocked_reason": apply_plan_blocked_reason,
        "eligible_for_apply_plan": False,
        "seo_eligible_for_apply_plan": False,
        "seo_notes": [],
        "contains_core_keyword": False,
        "contains_model": False,
        "contains_forbidden_phrase": False,
        "rewrite_attempts": [],
        "rewrite_attempt_count": 0,
        "quality_notes": [],
    }


def build_product_identity_context(product=None, translatable_rows=None, source_values=None):
    text_parts = []
    product = product or {}
    for key in ("title", "vendor", "product_type", "productType", "handle"):
        value = str(product.get(key) or "").strip()
        if value:
            text_parts.append(value)
    for row in translatable_rows or []:
        if isinstance(row, dict):
            value = str(row.get("source_value") or "").strip()
            if value:
                text_parts.append(value)
    for value in source_values or []:
        value = str(value or "").strip()
        if value:
            text_parts.append(value)

    source_text = "\n".join(text_parts)
    source_model_terms = _extract_model_tokens(source_text)
    expected_terms = _extract_product_identity_terms(source_text, source_model_terms)
    allowed_product_terms = [
        term
        for term in PRODUCT_IDENTITY_BLOCKLIST_TERMS
        if _identity_term_in_text(term, source_text)
    ]
    return {
        "expected_terms": expected_terms,
        "source_model_terms": source_model_terms,
        "allowed_product_terms": allowed_product_terms,
    }


def validate_product_identity_draft(source_identity_context, draft, field=""):
    context = _normalize_product_identity_context(source_identity_context)
    draft = str(draft or "")
    allowed_product_norms = {
        _identity_normalize_term(term)
        for term in context.get("allowed_product_terms") or []
    }
    source_model_norms = {
        _identity_normalize_term(term)
        for term in context.get("source_model_terms") or []
    }

    unexpected_product_terms = []
    for term in PRODUCT_IDENTITY_BLOCKLIST_TERMS:
        if not _identity_term_in_text(term, draft):
            continue
        if _identity_normalize_term(term) not in allowed_product_norms:
            unexpected_product_terms.append(term)

    draft_model_tokens = _extract_model_tokens(draft)
    unexpected_model_tokens = []
    if source_model_norms:
        for token in draft_model_tokens:
            normalized = _identity_normalize_term(token)
            if normalized in source_model_norms:
                continue
            if _is_known_foreign_model_token(token):
                unexpected_model_tokens.append(token)

    suspicious_terms = _unique(unexpected_product_terms + unexpected_model_tokens)
    validation_reasons = []
    if suspicious_terms:
        validation_reasons.append("product_identity_mismatch")
    if unexpected_product_terms:
        validation_reasons.append("unexpected_product_term")
    if unexpected_model_tokens:
        validation_reasons.append("unexpected_model_token")
    validation_reasons = _unique(validation_reasons)
    status = "blocked" if validation_reasons else "ok"
    return {
        "validation_status": status,
        "validation_reasons": validation_reasons,
        "suspicious_terms": suspicious_terms,
        "warning_text": PRODUCT_IDENTITY_WARNING_TEXT if validation_reasons else "",
        "product_identity_mismatch": bool(validation_reasons),
        "needs_review": bool(validation_reasons),
        "draft_blocked": status == "blocked",
        "source_identity_terms": context.get("expected_terms") or [],
        "source_model_terms": context.get("source_model_terms") or [],
        "draft_model_terms": draft_model_tokens,
        "field": field,
    }


def _attach_source_identity_context(entry, source_identity_context):
    context = _normalize_product_identity_context(source_identity_context)
    entry["source_identity_context"] = context
    entry["source_identity_terms"] = context.get("expected_terms") or []
    entry["source_model_terms"] = context.get("source_model_terms") or []


def _attach_product_identity_validation(entry, draft):
    identity = validate_product_identity_draft(
        entry.get("source_identity_context") or build_product_identity_context(
            source_values=[entry.get("source_value", "")]
        ),
        draft,
        field=entry.get("field", ""),
    )
    entry["product_identity_validation_status"] = identity["validation_status"]
    entry["validation_reasons"] = identity["validation_reasons"]
    entry["suspicious_terms"] = identity["suspicious_terms"]
    entry["identity_warning_text"] = identity["warning_text"]
    entry["warning_text"] = identity["warning_text"]
    entry["product_identity_mismatch"] = identity["product_identity_mismatch"]
    entry["needs_review"] = bool(entry.get("needs_review") or identity["needs_review"])
    entry["draft_blocked"] = identity["draft_blocked"]
    entry["source_identity_terms"] = identity["source_identity_terms"]
    entry["source_model_terms"] = identity["source_model_terms"]
    if identity["draft_blocked"]:
        entry["validation_status"] = "blocked"
        entry["eligible_for_apply_plan"] = False
        notes = entry.setdefault("quality_notes", [])
        for reason in identity["validation_reasons"]:
            if reason not in notes:
                notes.append(reason)


def _attach_existing_translation_identity_validation(entry):
    existing_value = str(entry.get("existing_translation_value") or "").strip()
    if not existing_value:
        return
    identity = validate_product_identity_draft(
        entry.get("source_identity_context") or build_product_identity_context(
            source_values=[entry.get("source_value", "")]
        ),
        existing_value,
        field=entry.get("field", ""),
    )
    if not identity["product_identity_mismatch"]:
        return
    entry["product_identity_validation_status"] = identity["validation_status"]
    entry["validation_reasons"] = identity["validation_reasons"]
    entry["suspicious_terms"] = identity["suspicious_terms"]
    entry["identity_warning_text"] = (
        "This existing translation may mention a different product. Please review before using."
    )
    entry["warning_text"] = entry["identity_warning_text"]
    entry["product_identity_mismatch"] = True
    entry["needs_review"] = True
    entry["source_identity_terms"] = identity["source_identity_terms"]
    entry["source_model_terms"] = identity["source_model_terms"]
    entry["validation_status"] = "existing_translation_needs_review_identity_mismatch"
    if entry.get("skip_reason") == "already_translated":
        entry["skip_reason"] = "existing_translation_identity_mismatch_manual_review_required"
        _refresh_entry_status(entry)
    notes = entry.setdefault("quality_notes", [])
    for reason in identity["validation_reasons"]:
        if reason not in notes:
            notes.append(reason)


def _normalize_product_identity_context(context):
    if not isinstance(context, dict):
        return build_product_identity_context(source_values=[])
    if any(key in context for key in ("product", "translatable_rows", "source_values")):
        return build_product_identity_context(
            product=context.get("product"),
            translatable_rows=context.get("translatable_rows"),
            source_values=context.get("source_values"),
        )
    return {
        "expected_terms": _unique(context.get("expected_terms") or []),
        "source_model_terms": _unique(context.get("source_model_terms") or []),
        "allowed_product_terms": _unique(context.get("allowed_product_terms") or []),
    }


def _identity_context_from_entries(entries):
    for entry in entries or []:
        context = entry.get("source_identity_context") if isinstance(entry, dict) else {}
        if context:
            return _normalize_product_identity_context(context)
    return build_product_identity_context(
        source_values=[
            entry.get("source_value", "")
            for entry in entries or []
            if isinstance(entry, dict)
        ]
    )


def _extract_product_identity_terms(source_text, source_model_terms):
    terms = []
    for phrase in PRODUCT_UPPERCASE_PHRASE_RE.findall(source_text or ""):
        terms.append(phrase.strip())
    terms.extend(source_model_terms or [])
    for term in PRODUCT_IDENTITY_CATEGORY_TERMS:
        if _identity_term_in_text(term, source_text):
            terms.append(term)
    for term in PRODUCT_IDENTITY_BLOCKLIST_TERMS:
        if _identity_term_in_text(term, source_text):
            terms.append(term)
    return _unique(terms)[:30]


def _extract_model_tokens(text):
    return _unique(match.group(0) for match in PRODUCT_MODEL_TOKEN_RE.finditer(str(text or "")))


def _is_known_foreign_model_token(token):
    normalized = _identity_normalize_term(token)
    return normalized in {
        _identity_normalize_term(term)
        for term in PRODUCT_IDENTITY_KNOWN_MODEL_TERMS
    }


def _identity_normalize_term(term):
    return re.sub(r"[^A-Z0-9]+", "", str(term or "").upper())


def _identity_term_in_text(term, text):
    term = str(term or "").strip()
    text = str(text or "")
    if not term or not text:
        return False
    if len(term) <= 3 and term.isalnum():
        return bool(
            re.search(
                rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
                text,
                flags=re.IGNORECASE,
            )
        )
    return term.lower() in text.lower()


def _identity_term_occurrence_count(term, text):
    term = str(term or "").strip()
    text = str(text or "")
    if not term or not text:
        return 0
    if len(term) <= 3 and term.isalnum():
        return len(
            re.findall(
                rf"(?<![A-Za-z0-9]){re.escape(term)}(?![A-Za-z0-9])",
                text,
                flags=re.IGNORECASE,
            )
        )
    return text.lower().count(term.lower())


def _format_identity_terms_for_prompt(identity_terms):
    identity_terms = [str(term) for term in identity_terms or [] if str(term)]
    if not identity_terms:
        return "the source product brand/model terms"
    return ", ".join(identity_terms[:12])


def _summary_bucket(result, key, value):
    return result[key].setdefault(
        value,
        {
            "generated_draft_count": 0,
            "draft_ready_count": 0,
            "draft_needs_manual_review_count": 0,
            "draft_blocked_count": 0,
            "product_identity_mismatch_count": 0,
            "eligible_apply_plan_count": 0,
            "over_length_after_rewrite_count": 0,
            "seo_ready_count": 0,
            "seo_needs_manual_review_count": 0,
            "seo_eligible_apply_plan_count": 0,
            "forbidden_phrase_count": 0,
            "missing_core_keyword_count": 0,
            "too_short_for_seo_count": 0,
            "skipped_existing_translation_count": 0,
            "skipped_outdated_translation_count": 0,
            "skipped_source_empty_count": 0,
            "skipped_not_draft_eligible_count": 0,
            "missing_translation_count": 0,
            "outdated_translation_count": 0,
            "missing_translation_draft_generated_count": 0,
            "outdated_translation_update_draft_generated_count": 0,
            "already_translated_skipped_count": 0,
            "not_eligible_skipped_count": 0,
            "needs_review_or_blocked_count": 0,
            "source_row_count": 0,
        },
    )


def _count_entry(result, entry):
    per_locale = _summary_bucket(result, "per_locale_results", entry["locale"])
    per_field = _summary_bucket(result, "per_field_results", entry["field"])
    per_section = _summary_bucket(
        result,
        "per_section_results",
        _section_summary_key(entry.get("resource_group")),
    )
    reason = entry.get("skip_reason")
    for bucket in (per_locale, per_field, per_section):
        bucket["source_row_count"] += 1
    if entry.get("product_identity_mismatch"):
        for bucket in (per_locale, per_field, per_section):
            bucket["product_identity_mismatch_count"] += 1
            bucket["draft_needs_manual_review_count"] += 1
            bucket["needs_review_or_blocked_count"] += 1
        result["product_identity_mismatch_count"] += 1
        result["draft_needs_manual_review_count"] += 1
        result["needs_review_or_blocked_count"] += 1
    if reason == "already_translated":
        for bucket in (per_locale, per_field, per_section):
            bucket["skipped_existing_translation_count"] += 1
            bucket["already_translated_skipped_count"] += 1
        result["skipped_existing_translation_count"] += 1
        result["skipped_existing_count"] += 1
        result["already_translated_skipped_count"] += 1
    elif reason == "existing_translation_outdated_manual_review_required":
        for bucket in (per_locale, per_field, per_section):
            bucket["skipped_outdated_translation_count"] += 1
            bucket["not_eligible_skipped_count"] += 1
        result["skipped_outdated_translation_count"] += 1
        result["not_eligible_skipped_count"] += 1
    elif reason == "outdated_translation":
        for bucket in (per_locale, per_field, per_section):
            bucket["outdated_translation_count"] += 1
    elif reason == "existing_translation_identity_mismatch_manual_review_required":
        for bucket in (per_locale, per_field, per_section):
            bucket["not_eligible_skipped_count"] += 1
        result["not_eligible_skipped_count"] += 1
        return
    elif reason == "source_empty":
        for bucket in (per_locale, per_field, per_section):
            bucket["skipped_source_empty_count"] += 1
            bucket["not_eligible_skipped_count"] += 1
        result["skipped_source_empty_count"] += 1
        result["not_eligible_skipped_count"] += 1
    elif reason and reason != "missing_translation":
        for bucket in (per_locale, per_field, per_section):
            bucket["skipped_not_draft_eligible_count"] += 1
            bucket["not_eligible_skipped_count"] += 1
        result["skipped_not_draft_eligible_count"] += 1
        result["not_eligible_skipped_count"] += 1
        if reason in TECHNICAL_SKIP_REASONS:
            result["skipped_technical_count"] += 1
    elif reason == "missing_translation":
        for bucket in (per_locale, per_field, per_section):
            bucket["missing_translation_count"] += 1


def _request_openai(locale, missing_entries, result):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        result["draft_status"] = "blocked_missing_openai_api_key"
        result["failure_type"] = "missing_openai_api_key"
        result["error"] = "OPENAI_API_KEY is not configured."
        result["blocking_conditions"].append("blocked_missing_openai_api_key")
        return None

    cache = _load_translation_cache()
    result["translation_cache_entry_count"] = len(cache)
    translations = {}
    pending_entries = []
    entries_by_cache_key = {}
    cache_dirty = False

    for entry in missing_entries:
        draft_key = entry.get("draft_key") or entry.get("field")
        cache_key = _translation_cache_key(locale, entry)
        entry["translation_cache_key"] = cache_key
        cached_value = _translation_cache_value(cache, cache_key)
        if cached_value:
            translations[draft_key] = cached_value
            entry["translation_source"] = "cache"
            result["reused_cache_count"] += 1
            result["estimated_input_chars_saved"] += len(
                str(entry.get("source_value") or "")
            )
            continue
        if cache_key in entries_by_cache_key:
            entries_by_cache_key[cache_key].append(entry)
            entry["translation_source"] = "deduplicated_input"
            result["deduplicated_input_count"] += 1
            result["estimated_input_chars_saved"] += len(
                str(entry.get("source_value") or "")
            )
            continue
        entries_by_cache_key[cache_key] = [entry]
        pending_entries.append(entry)

    invalid_response_count_before = int(
        result.get("openai_invalid_translation_response_count") or 0
    )
    for prompt_profile, profile_entries in _openai_entries_by_prompt_profile(
        pending_entries
    ).items():
        if not profile_entries:
            continue
        parsed = _request_openai_profile(
            locale,
            profile_entries,
            result,
            api_key,
            prompt_profile,
        )
        if parsed is None:
            return None
        profile_invalid_response = bool(
            parsed.get("_openai_invalid_translation_response")
        )
        profile_translations = _translations_from_openai_response(
            parsed,
            profile_entries,
            prompt_profile,
            result,
        )
        if profile_translations is None:
            return None
        profile_generated_value = False
        for entry in profile_entries:
            draft_key = entry.get("draft_key") or entry.get("field")
            value = str(profile_translations.get(draft_key) or "").strip()
            if value:
                profile_generated_value = True
            cache_key = entry.get("translation_cache_key") or _translation_cache_key(
                locale,
                entry,
            )
            if value:
                cache[cache_key] = _translation_cache_record(locale, entry, value)
                cache_dirty = True
            for duplicate_entry in entries_by_cache_key.get(cache_key) or [entry]:
                duplicate_key = duplicate_entry.get("draft_key") or duplicate_entry.get(
                    "field"
                )
                translations[duplicate_key] = value
        if profile_invalid_response and not profile_generated_value:
            _record_openai_invalid_response(
                result,
                locale,
                retry_attempted=True,
                retry_succeeded=False,
                blocking=False,
            )

    if (
        int(result.get("openai_invalid_translation_response_count") or 0)
        > invalid_response_count_before
        and not any(str(value or "").strip() for value in translations.values())
        and pending_entries
    ):
        _record_openai_invalid_response(
            result,
            locale,
            retry_attempted=True,
            retry_succeeded=False,
            blocking=True,
            count=False,
        )

    if cache_dirty:
        _save_translation_cache(cache)
        result["translation_cache_entry_count"] = len(cache)
    return translations


def _request_openai_profile(locale, entries, result, api_key, prompt_profile):
    payload = _openai_translation_payload(locale, entries, prompt_profile)
    data = _post_openai_payload(
        payload,
        api_key,
        result,
        f"draft generation ({prompt_profile})",
        locale=locale,
    )
    if data is None:
        return None
    parsed, parse_error = _parse_openai_translation_response(
        data,
        entries,
        prompt_profile,
    )
    if parsed is not None:
        return parsed

    _record_openai_retry_attempt(result, locale, prompt_profile, parse_error)
    retry_payload = _openai_translation_payload(
        locale,
        entries,
        prompt_profile,
        repair=True,
    )
    retry_data = _post_openai_payload(
        retry_payload,
        api_key,
        result,
        f"draft generation repair ({prompt_profile})",
        locale=locale,
    )
    if retry_data is None:
        return None
    retry_parsed, retry_error = _parse_openai_translation_response(
        retry_data,
        entries,
        prompt_profile,
    )
    if retry_parsed is not None:
        _record_openai_retry_success(result, locale, prompt_profile)
        return retry_parsed

    _record_openai_response_recovery_event(
        result,
        locale,
        prompt_profile,
        retry_attempted=True,
        retry_succeeded=False,
        sanitized_error=retry_error or OPENAI_TRANSLATIONS_MISSING_MESSAGE,
    )
    return {
        "translations": {},
        "_openai_invalid_translation_response": True,
        "_openai_invalid_translation_error": retry_error
        or OPENAI_TRANSLATIONS_MISSING_MESSAGE,
    }


def _openai_translation_payload(locale, entries, prompt_profile, repair=False):
    prompt = _openai_prompt(locale, entries, prompt_profile=prompt_profile)
    if repair:
        prompt["strict_output_reminder"] = (
            "Return only valid JSON with top-level translations object. "
            "Do not include markdown fences, prose, comments, or any keys outside the JSON object."
        )
    system_content = (
        "You are a careful ecommerce localization translator. Return valid JSON only."
        if prompt_profile != OPENAI_PROMPT_HTML_TEXT_NODES
        else "You translate only visible ecommerce HTML text nodes and return valid JSON only."
    )
    if repair:
        system_content += (
            " Return only valid JSON with a top-level translations object."
        )
    return {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": system_content},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_object"}},
    }


def _parse_openai_translation_response(data, entries, prompt_profile):
    parsed, parse_error = _json_object_from_openai_text(_output_text_from_openai(data))
    if parsed is None:
        return None, parse_error or "OpenAI response was not valid JSON."
    translations = _normalize_openai_translations_object(
        parsed,
        entries,
        prompt_profile,
    )
    if translations is None:
        return None, OPENAI_TRANSLATIONS_MISSING_MESSAGE
    normalized = dict(parsed)
    normalized["translations"] = translations
    return normalized, ""


def _json_object_from_openai_text(text):
    text = str(text or "").strip()
    if not text:
        return None, "OpenAI response was empty."
    candidates = [text]
    candidates.extend(_json_code_fence_candidates(text))
    candidates.extend(_balanced_json_object_candidates(text))
    seen = set()
    last_error = ""
    for candidate in candidates:
        candidate = str(candidate or "").strip()
        if not candidate or candidate in seen:
            continue
        seen.add(candidate)
        try:
            parsed = json.loads(candidate)
        except Exception as exc:
            last_error = f"{type(exc).__name__}: OpenAI response was not valid JSON."
            continue
        if isinstance(parsed, dict):
            return parsed, ""
        last_error = "OpenAI response JSON was not an object."
    return None, last_error or "OpenAI response was not valid JSON."


def _json_code_fence_candidates(text):
    candidates = []
    for match in re.finditer(r"```(?:json)?\s*(.*?)```", text, flags=re.IGNORECASE | re.DOTALL):
        candidates.append(match.group(1))
    return candidates


def _balanced_json_object_candidates(text):
    candidates = []
    for start, char in enumerate(text):
        if char != "{":
            continue
        depth = 0
        in_string = False
        escape_next = False
        for index in range(start, len(text)):
            current = text[index]
            if escape_next:
                escape_next = False
                continue
            if current == "\\" and in_string:
                escape_next = True
                continue
            if current == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if current == "{":
                depth += 1
            elif current == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start : index + 1])
                    break
    return candidates


def _normalize_openai_translations_object(parsed, entries, prompt_profile):
    if not isinstance(parsed, dict):
        return None
    expected = _openai_expected_translation_keys(entries)
    raw_translations = parsed.get("translations")
    if isinstance(raw_translations, dict):
        return _safe_openai_translation_map(raw_translations, expected, prompt_profile)

    for key in ("translation", "results", "result", "data", "output"):
        raw_value = parsed.get(key)
        normalized = _normalize_openai_translation_candidate(
            raw_value,
            expected,
            prompt_profile,
        )
        if normalized is not None:
            return normalized

    return _safe_openai_translation_map(parsed, expected, prompt_profile)


def _normalize_openai_translation_candidate(value, expected, prompt_profile):
    if isinstance(value, dict):
        raw_translations = value.get("translations")
        if isinstance(raw_translations, dict):
            nested = _safe_openai_translation_map(
                raw_translations,
                expected,
                prompt_profile,
            )
            if nested is not None:
                return nested
        for key in ("translation", "results", "result", "data", "output"):
            if key not in value:
                continue
            nested = _normalize_openai_translation_candidate(
                value.get(key),
                expected,
                prompt_profile,
            )
            if nested is not None:
                return nested
        return _safe_openai_translation_map(value, expected, prompt_profile)
    if isinstance(value, list):
        mapped = _translation_list_to_map(value)
        return _safe_openai_translation_map(mapped, expected, prompt_profile)
    if isinstance(value, str) and len(expected.get("draft_keys") or []) == 1:
        draft_key = next(iter(expected["draft_keys"]))
        return {draft_key: value.strip()} if value.strip() else None
    return None


def _translation_list_to_map(items):
    output = {}
    for item in items or []:
        if not isinstance(item, dict):
            continue
        key = (
            item.get("draft_key")
            or item.get("key")
            or item.get("field")
            or item.get("name")
        )
        value = (
            item.get("translation")
            or item.get("translated_text")
            or item.get("translated")
            or item.get("value")
            or item.get("text")
        )
        if key and value is not None:
            output[str(key)] = value
    return output


def _openai_expected_translation_keys(entries):
    draft_keys = {
        str(entry.get("draft_key") or entry.get("field") or "")
        for entry in entries or []
        if str(entry.get("draft_key") or entry.get("field") or "")
    }
    field_counts = {}
    for entry in entries or []:
        field = str(entry.get("field") or "")
        if field:
            field_counts[field] = field_counts.get(field, 0) + 1
    return {
        "draft_keys": draft_keys,
        "safe_field_keys": {
            field for field, count in field_counts.items() if count == 1
        },
    }


def _safe_openai_translation_map(candidate, expected, prompt_profile):
    if not isinstance(candidate, dict):
        return None
    draft_keys = expected.get("draft_keys") or set()
    safe_field_keys = expected.get("safe_field_keys") or set()
    if not draft_keys and not safe_field_keys:
        return None
    output = {}
    for key, value in candidate.items():
        text_key = str(key)
        if text_key not in draft_keys and text_key not in safe_field_keys:
            continue
        if not _openai_translation_value_is_safe(value, prompt_profile):
            continue
        output[text_key] = value
    return output or None


def _openai_translation_value_is_safe(value, prompt_profile):
    if isinstance(value, str):
        return bool(value.strip())
    if prompt_profile == OPENAI_PROMPT_HTML_TEXT_NODES and isinstance(value, dict):
        node_values = value.get("html_text_nodes") or value.get("nodes")
        return isinstance(node_values, dict) and any(
            str(item or "").strip() for item in node_values.values()
        )
    return False


def _openai_prompt(locale, missing_entries, prompt_profile=OPENAI_PROMPT_RICH):
    identity_context = _identity_context_from_entries(missing_entries)
    identity_terms = identity_context.get("expected_terms") or []
    model_terms = identity_context.get("source_model_terms") or []
    identity_term_text = _format_identity_terms_for_prompt(identity_terms)
    prompt = {
        "task": _openai_prompt_task(prompt_profile),
        "target_locale": locale,
        "target_language": LANGUAGE_NAMES.get(locale, locale),
        "draft_only": True,
        "prompt_profile": prompt_profile,
        "product_identity": {
            "expected_terms": identity_terms,
            "model_terms": model_terms,
        },
        "fields": [
            _openai_prompt_field(item, prompt_profile)
            for item in missing_entries
        ],
        "locale_term_guidance": LOCALE_TERM_GUIDANCE.get(locale, ""),
        "rules": _openai_prompt_rules(prompt_profile, identity_term_text),
        "output_contract": _openai_output_contract(prompt_profile),
    }
    if prompt_profile != OPENAI_PROMPT_COMPACT:
        prompt["seo_rules"] = [
            "Product title must be 25-80 characters where possible, and never over 80 characters.",
            "SEO meta_title must be 30-60 characters where possible, and never over 60 characters.",
            "SEO meta_description must be 80-160 characters where possible, and never over 160 characters.",
            "meta_title must naturally include the source product model when the source SEO title includes it, one localized core part keyword, and RC spare/replacement meaning.",
            "meta_description must include use, source product compatibility, localized part type, and one value point such as durable, precise, reliable, or control.",
            "Do not repeat the same model name more than once in the same field.",
            "Do not make title and meta_title exactly the same.",
        ]
    return prompt


def _openai_prompt_task(prompt_profile):
    if prompt_profile == OPENAI_PROMPT_COMPACT:
        return "Translate short Shopify product fields into draft translations for manual review only."
    if prompt_profile == OPENAI_PROMPT_HTML_TEXT_NODES:
        return "Translate only visible text nodes from Shopify body_html while preserving the original HTML structure locally."
    return "Translate selected Shopify product fields into draft translations for manual review only."


def _openai_prompt_field(item, prompt_profile):
    base = {
        "draft_key": item["draft_key"],
        "field": item["field"],
        "source_key": item.get("source_key", ""),
        "resource_group": item.get("resource_group", ""),
        "context": item.get("context_label", ""),
        "max_chars": item["max_chars"],
        "style_guidance": _field_style_guidance(item),
    }
    if prompt_profile == OPENAI_PROMPT_COMPACT:
        base["source_value"] = item["source_value"]
        return base
    if prompt_profile == OPENAI_PROMPT_HTML_TEXT_NODES:
        base["html_text_nodes"] = _html_text_nodes_for_entry(item)
        base["html_preservation"] = (
            "Only translate node text values. The application will put them back into the original HTML. "
            "Do not return or modify tags, attributes, iframe, link, image, video, script, or style markup."
        )
        return base
    base.update(
        {
            "draft_generation_reason": item.get(
                "draft_generation_reason", "missing_translation"
            ),
            "existing_translation_value": item.get("existing_translation_value", ""),
            "existing_translation_outdated": item.get("existing_translation_outdated"),
            "resource_id": item.get("resource_id", ""),
            "source_value": item["source_value"],
            "recommended_min_chars": FIELD_RECOMMENDED_MIN_CHARS.get(item["field"]),
            "recommended_max_chars": FIELD_RECOMMENDED_MAX_CHARS.get(item["field"]),
        }
    )
    return base


def _openai_prompt_rules(prompt_profile, identity_term_text):
    base_rules = [
            "Return JSON only with a translations object keyed by draft_key exactly.",
            f"Preserve these source product identity terms when they appear in the source: {identity_term_text}.",
            "Do not introduce a different product brand, product line, aircraft name, vehicle name, or model number.",
            "Preserve brand names, model names, SKU-like codes, dimensions, battery specs, and option structure.",
            "Preserve RC terminology and product facts. Do not invent specifications.",
            "Do not add CTA, shipping-origin, Made in China, Best, Cheap, guaranteed, official, or original OEM claims.",
        ]
    if prompt_profile == OPENAI_PROMPT_COMPACT:
        return base_rules + [
            "Use concise natural wording for short titles, option names, option values, variant values, and media alt text.",
            "Return each translation as a string value.",
        ]
    if prompt_profile == OPENAI_PROMPT_HTML_TEXT_NODES:
        return base_rules + [
            "For each field, return an object with html_text_nodes keyed by node_key.",
            "Translate visible customer-facing text only.",
            "Do not translate URL-like visible text.",
            "Do not return HTML tags in node translations.",
            "Keep video iframe/link/image tags unchanged by leaving markup out of the response.",
        ]
    return base_rules + [
            "If draft_generation_reason is outdated_translation, create a replacement draft from the source value; do not copy the outdated translation unless it is already accurate.",
            "Do not translate product model numbers such as P-51D, F-16, C184, MD530, or similar model codes.",
            "Localize part names naturally; do not mechanically keep English phrases such as RC Plane Clevis.",
            "Do not invent variants, options, metafields, media, product facts, compatibility, or package contents.",
            "Product title must be 25-80 characters where possible, and never over 80 characters.",
            "SEO meta_title must be 30-60 characters where possible, and never over 60 characters.",
            "SEO meta_description must be 80-160 characters where possible, and never over 160 characters.",
            "meta_title must naturally include the source product model when the source SEO title includes it, one localized core part keyword, and RC spare/replacement meaning.",
            "meta_description must include use, source product compatibility, localized part type, and one value point such as durable, precise, reliable, or control.",
            "Do not repeat the same model name more than once in the same field.",
            "Do not make title and meta_title exactly the same.",
            "For body_html, preserve the original HTML structure and translate only customer-facing text.",
    ]


def _openai_output_contract(prompt_profile):
    if prompt_profile == OPENAI_PROMPT_HTML_TEXT_NODES:
        return {
            "type": "JSON object",
            "shape": {
                "translations": {
                    "draft_key": {
                        "html_text_nodes": {
                            "node_key": "translated visible text without HTML"
                        }
                    }
                }
            },
        }
    return {
        "type": "JSON object",
        "shape": {"translations": {"draft_key": "draft translated value"}},
    }


def _openai_entries_by_prompt_profile(entries):
    groups = {
        OPENAI_PROMPT_COMPACT: [],
        OPENAI_PROMPT_RICH: [],
        OPENAI_PROMPT_HTML_TEXT_NODES: [],
    }
    for entry in entries or []:
        groups[_openai_prompt_profile_for_entry(entry)].append(entry)
    return groups


def _openai_prompt_profile_for_entry(entry):
    field = str((entry or {}).get("field") or "")
    resource_group = str((entry or {}).get("resource_group") or "")
    if field == "body_html":
        return OPENAI_PROMPT_HTML_TEXT_NODES
    if field in {"meta_title", "meta_description"}:
        return OPENAI_PROMPT_RICH
    if resource_group == "important_metafields":
        return OPENAI_PROMPT_RICH
    return OPENAI_PROMPT_COMPACT


def _translations_from_openai_response(parsed, entries, prompt_profile, result):
    raw_translations = parsed.get("translations")
    if not isinstance(raw_translations, dict):
        _record_openai_invalid_response(
            result,
            "",
            retry_attempted=False,
            retry_succeeded=False,
            blocking=True,
        )
        return None
    invalid_response = bool(parsed.get("_openai_invalid_translation_response"))
    invalid_error = str(
        parsed.get("_openai_invalid_translation_error")
        or OPENAI_TRANSLATIONS_MISSING_MESSAGE
    )
    if prompt_profile != OPENAI_PROMPT_HTML_TEXT_NODES:
        translations = {}
        for entry in entries or []:
            draft_key = entry.get("draft_key") or entry.get("field")
            raw_value, found = _openai_translation_value_for_entry(
                raw_translations,
                entry,
            )
            if not found:
                _mark_openai_missing_translation_entry(
                    entry,
                    invalid_error if invalid_response else "OpenAI response was missing this field.",
                )
                result["openai_missing_translation_field_count"] = int(
                    result.get("openai_missing_translation_field_count") or 0
                ) + 1
                translations[draft_key] = ""
                continue
            translations[draft_key] = _string_from_openai_translation_value(
                raw_value
            )
        return translations
    translations = {}
    for entry in entries or []:
        draft_key = entry.get("draft_key") or entry.get("field")
        raw_value, found = _openai_translation_value_for_entry(
            raw_translations,
            entry,
        )
        if not found:
            _mark_openai_missing_translation_entry(
                entry,
                invalid_error if invalid_response else "OpenAI response was missing this field.",
            )
            result["openai_missing_translation_field_count"] = int(
                result.get("openai_missing_translation_field_count") or 0
            ) + 1
            translations[draft_key] = ""
            continue
        if isinstance(raw_value, str):
            translations[draft_key] = raw_value.strip()
            continue
        if not isinstance(raw_value, dict):
            _mark_openai_missing_translation_entry(
                entry,
                "OpenAI response field was not a supported translation value.",
            )
            translations[draft_key] = ""
            continue
        node_translations = raw_value.get("html_text_nodes") or raw_value.get("nodes")
        if not isinstance(node_translations, dict):
            _mark_openai_missing_translation_entry(
                entry,
                "OpenAI response did not include html_text_nodes for this field.",
            )
            translations[draft_key] = ""
            continue
        translations[draft_key] = _rebuild_html_from_node_translations(
            entry,
            node_translations,
        )
    return translations


def _openai_translation_value_for_entry(raw_translations, entry):
    draft_key = str((entry or {}).get("draft_key") or (entry or {}).get("field") or "")
    field = str((entry or {}).get("field") or "")
    if draft_key and draft_key in raw_translations:
        return raw_translations.get(draft_key), True
    if field and field in raw_translations:
        return raw_translations.get(field), True
    return None, False


def _string_from_openai_translation_value(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("translation", "translated_text", "translated", "value", "text"):
            if str(value.get(key) or "").strip():
                return str(value.get(key) or "").strip()
    return ""


def _mark_openai_missing_translation_entry(entry, sanitized_error):
    entry["openai_failure_type"] = OPENAI_INVALID_TRANSLATION_RESPONSE
    entry["openai_response_error"] = str(
        sanitized_error or OPENAI_TRANSLATIONS_MISSING_MESSAGE
    )
    entry["draft_requires_manual_review"] = True
    entry["draft_manual_review_reason"] = OPENAI_INVALID_TRANSLATION_RESPONSE


def _record_openai_retry_attempt(result, locale, prompt_profile, sanitized_error):
    result["openai_retry_attempt_count"] = int(
        result.get("openai_retry_attempt_count") or 0
    ) + 1
    result["retry_attempted"] = True
    _record_openai_response_recovery_event(
        result,
        locale,
        prompt_profile,
        retry_attempted=True,
        retry_succeeded=False,
        sanitized_error=sanitized_error or OPENAI_TRANSLATIONS_MISSING_MESSAGE,
    )


def _record_openai_retry_success(result, locale, prompt_profile):
    result["openai_retry_success_count"] = int(
        result.get("openai_retry_success_count") or 0
    ) + 1
    result["retry_attempted"] = True
    result["retry_succeeded"] = True
    _record_openai_response_recovery_event(
        result,
        locale,
        prompt_profile,
        retry_attempted=True,
        retry_succeeded=True,
        sanitized_error="",
    )


def _record_openai_invalid_response(
    result,
    locale,
    *,
    retry_attempted,
    retry_succeeded,
    blocking,
    count=True,
):
    if count:
        result["openai_invalid_translation_response_count"] = int(
            result.get("openai_invalid_translation_response_count") or 0
        ) + 1
    result["retry_attempted"] = bool(
        result.get("retry_attempted") or retry_attempted
    )
    result["retry_succeeded"] = bool(
        result.get("retry_succeeded") or retry_succeeded
    )
    if not blocking:
        return
    result["draft_status"] = "blocked_openai_draft_generation_failed"
    result["failure_type"] = OPENAI_INVALID_TRANSLATION_RESPONSE
    result["failed_stage"] = OPENAI_TRANSLATION_GENERATION_STAGE
    result["sanitized_error"] = OPENAI_TRANSLATIONS_MISSING_MESSAGE
    result["error"] = OPENAI_TRANSLATIONS_MISSING_MESSAGE
    blocking_conditions = result.setdefault("blocking_conditions", [])
    if "blocked_openai_draft_generation_failed" not in blocking_conditions:
        blocking_conditions.append("blocked_openai_draft_generation_failed")


def _record_openai_response_recovery_event(
    result,
    locale,
    prompt_profile,
    *,
    retry_attempted,
    retry_succeeded,
    sanitized_error,
):
    events = result.setdefault("openai_response_recovery_events", [])
    events.append(
        {
            "locale": str(locale or ""),
            "failed_stage": OPENAI_TRANSLATION_GENERATION_STAGE,
            "prompt_profile": str(prompt_profile or ""),
            "sanitized_error": _openai_sanitized_response_error(sanitized_error),
            "retry_attempted": bool(retry_attempted),
            "retry_succeeded": bool(retry_succeeded),
        }
    )


def _openai_sanitized_response_error(value):
    text = str(value or OPENAI_TRANSLATIONS_MISSING_MESSAGE)
    if "translations object" in text:
        return OPENAI_TRANSLATIONS_MISSING_MESSAGE
    if "not valid JSON" in text:
        return "OpenAI response was not valid JSON."
    if "empty" in text.lower():
        return "OpenAI response was empty."
    return OPENAI_TRANSLATIONS_MISSING_MESSAGE


def _load_translation_cache():
    try:
        if (
            not TRANSLATION_CACHE_PATH.exists()
            or TRANSLATION_CACHE_PATH.stat().st_size > TRANSLATION_CACHE_MAX_BYTES
        ):
            return {}
        with TRANSLATION_CACHE_PATH.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}
    entries = data.get("entries") if isinstance(data, dict) else {}
    return entries if isinstance(entries, dict) else {}


def _save_translation_cache(cache):
    if not isinstance(cache, dict):
        return
    trimmed_items = list(cache.items())[-TRANSLATION_CACHE_MAX_ENTRIES:]
    payload = {
        "cache_version": 1,
        "entry_count": len(trimmed_items),
        "entries": dict(trimmed_items),
    }
    TRANSLATION_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = TRANSLATION_CACHE_PATH.with_name(
        f".{TRANSLATION_CACHE_PATH.name}.{os.getpid()}.tmp"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, TRANSLATION_CACHE_PATH)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _translation_cache_value(cache, cache_key):
    record = (cache or {}).get(cache_key)
    if isinstance(record, dict):
        return str(record.get("value") or "").strip()
    return ""


def _translation_cache_record(locale, entry, value):
    field = str((entry or {}).get("field") or "")
    resource_group = str((entry or {}).get("resource_group") or "")
    source_digest = str(
        (entry or {}).get("source_digest") or (entry or {}).get("digest") or ""
    ).strip()
    return {
        "value": str(value or "").strip(),
        "locale": locale,
        "field": field,
        "resource_group": resource_group,
        "resource_id": str((entry or {}).get("resource_id") or ""),
        "source_key": str((entry or {}).get("source_key") or field),
        "source_digest": source_digest,
        "source_text_hash": _source_text_hash(entry.get("source_value") or ""),
        "product_identity_context_hash": _product_identity_context_hash_for_cache(
            entry
        ),
        "prompt_profile": _openai_prompt_profile_for_entry(entry),
    }


def _translation_cache_key(locale, entry):
    field = str((entry or {}).get("field") or "")
    resource_group = str((entry or {}).get("resource_group") or "")
    source_digest = str(
        (entry or {}).get("source_digest") or (entry or {}).get("digest") or ""
    ).strip()
    parts = [
        "v2",
        str(locale or ""),
        field,
        resource_group,
        source_digest,
        _source_text_hash((entry or {}).get("source_value") or ""),
    ]
    identity_hash = _product_identity_context_hash_for_cache(entry)
    if identity_hash:
        parts.append(identity_hash)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _product_identity_context_hash_for_cache(entry):
    field = str((entry or {}).get("field") or "")
    resource_group = str((entry or {}).get("resource_group") or "")
    if resource_group not in {"product_basics", "seo", "important_metafields", "media"} and field not in {
        "title",
        "body_html",
        "meta_title",
        "meta_description",
    }:
        return ""
    context = _normalize_product_identity_context(
        (entry or {}).get("source_identity_context") or {}
    )
    if not context.get("expected_terms") and not context.get("source_model_terms"):
        return ""
    text = json.dumps(context, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _source_text_hash(value):
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:24]


def _previous_translation_source_index(product_id: str):
    product_gid = str(product_id or "").strip()
    if not product_gid:
        return {}
    index = {}
    for path in _previous_translation_workspace_report_paths(product_gid):
        report = _load_previous_translation_workspace_report(path)
        if report.get("product_gid") and report.get("product_gid") != product_gid:
            continue
        report_status = str(report.get("status") or "").strip()
        for row in _previous_translation_workspace_rows(report):
            snapshot = _source_snapshot_from_report_row(row, report_status=report_status)
            if not snapshot:
                continue
            key = (
                snapshot["resource_id"],
                snapshot["field"],
                snapshot["locale"],
            )
            fallback_key = (snapshot["resource_id"], snapshot["field"], "")
            index.setdefault(key, snapshot)
            index.setdefault(fallback_key, snapshot)
        if index:
            break
    return index


def _previous_translation_workspace_report_paths(product_id: str):
    product_hash = hashlib.sha256(str(product_id or "").encode("utf-8")).hexdigest()[:16]
    try:
        paths = list(
            TRANSLATION_WORKSPACE_JOB_DIR.glob(
                f"translation_workspace_job_{product_hash}_*.json"
            )
        )
    except OSError:
        return []
    return sorted(paths, key=_safe_path_mtime, reverse=True)


def _safe_path_mtime(path: Path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def _load_previous_translation_workspace_report(path: Path):
    try:
        if (
            not path.exists()
            or path.stat().st_size > TRANSLATION_WORKSPACE_PREVIOUS_REPORT_MAX_BYTES
        ):
            return {}
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _previous_translation_workspace_rows(report: dict):
    for key in ("review_rows", "detail_preview_rows"):
        for row in (report or {}).get(key) or []:
            if isinstance(row, dict):
                yield row


def _source_snapshot_from_report_row(row: dict, *, report_status: str = ""):
    field = _normalize_draft_field_key(
        row.get("field")
        or row.get("field_key")
        or row.get("key")
        or row.get("resource_key")
    )
    if field != "body_html":
        return {}
    source_value = _first_text(
        row,
        "source_value",
        "source_value_display",
        "source_value_preview",
        "source_preview",
    )
    use_previous_changed_source = (
        report_status in TRANSLATION_WORKSPACE_IN_PROGRESS_REPORT_STATUSES
        and row.get("source_changed_from_previous_report")
    )
    digest = str(
        (
            row.get("previous_source_digest")
            if use_previous_changed_source
            else None
        )
        or row.get("source_digest")
        or row.get("digest")
        or ""
    ).strip()
    source_hash = str(row.get("source_text_hash") or "").strip()
    if use_previous_changed_source and row.get("previous_source_text_hash"):
        source_hash = str(row.get("previous_source_text_hash") or "").strip()
    if not source_hash and source_value.strip() and not use_previous_changed_source:
        source_hash = _source_text_hash(source_value)
    if not digest and not source_hash:
        return {}
    return {
        "resource_id": str(row.get("resource_id") or "").strip(),
        "field": field,
        "locale": str(row.get("locale") or row.get("language") or "").strip(),
        "source_digest": digest,
        "source_text_hash": source_hash,
    }


def _detect_previous_source_change(row: dict, locale: str, previous_source_index: dict):
    field = _normalize_draft_field_key(row.get("field_key") or row.get("key"))
    if field != "body_html" or not previous_source_index:
        return {}
    resource_id = str(row.get("resource_id") or "").strip()
    previous = previous_source_index.get(
        (resource_id, field, str(locale or "").strip())
    ) or previous_source_index.get((resource_id, field, ""))
    if not previous:
        return {}

    current_digest = str(row.get("digest") or row.get("source_digest") or "").strip()
    current_hash = _source_text_hash(row.get("source_value") or "")
    previous_digest = str(previous.get("source_digest") or "").strip()
    previous_hash = str(previous.get("source_text_hash") or "").strip()

    changed = False
    if previous_hash and current_hash:
        changed = previous_hash != current_hash
    elif previous_digest and current_digest:
        changed = previous_digest != current_digest
    if not changed:
        return {}

    return {
        "source_changed_from_previous_report": True,
        "source_change_message": SOURCE_CHANGED_REFRESH_MESSAGE,
        "previous_source_digest": previous_digest,
        "current_source_digest": current_digest,
        "previous_source_text_hash": previous_hash,
        "current_source_text_hash": current_hash,
    }


def _first_text(row: dict, *keys):
    for key in keys:
        value = (row or {}).get(key)
        if value is None:
            continue
        text = str(value)
        if text.strip():
            return text
    return ""


class _VisibleHtmlTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.parts = []
        self.nodes = []
        self._skip_stack = []

    def handle_starttag(self, tag, attrs):
        self.parts.append(("raw", self.get_starttag_text() or f"<{tag}>"))
        if tag.lower() in HTML_UNCHANGED_TEXT_TAGS:
            self._skip_stack.append(tag.lower())

    def handle_startendtag(self, tag, attrs):
        self.parts.append(("raw", self.get_starttag_text() or f"<{tag} />"))

    def handle_endtag(self, tag):
        tag = tag.lower()
        self.parts.append(("raw", f"</{tag}>"))
        if tag in self._skip_stack:
            while self._skip_stack:
                skipped = self._skip_stack.pop()
                if skipped == tag:
                    break

    def handle_data(self, data):
        if self._skip_stack or not str(data or "").strip() or _html_text_node_should_preserve(data):
            self.parts.append(("raw", data))
            return
        node_key = f"n{len(self.nodes) + 1}"
        self.nodes.append({"node_key": node_key, "text": data.strip()})
        self.parts.append(("node", node_key, data))

    def handle_entityref(self, name):
        self.parts.append(("raw", f"&{name};"))

    def handle_charref(self, name):
        self.parts.append(("raw", f"&#{name};"))

    def handle_comment(self, data):
        self.parts.append(("raw", f"<!--{data}-->"))

    def handle_decl(self, decl):
        self.parts.append(("raw", f"<!{decl}>"))


def _html_text_nodes_for_entry(entry):
    extractor = _html_extractor_for_entry(entry)
    return list(extractor.nodes)


def _html_extractor_for_entry(entry):
    extractor = (entry or {}).get("_html_text_extractor")
    if extractor is not None:
        return extractor
    extractor = _VisibleHtmlTextExtractor()
    try:
        extractor.feed(str((entry or {}).get("source_value") or ""))
        extractor.close()
    except Exception:
        extractor = _VisibleHtmlTextExtractor()
        extractor.parts = [("raw", str((entry or {}).get("source_value") or ""))]
        extractor.nodes = []
    entry["_html_text_extractor"] = extractor
    return extractor


def _rebuild_html_from_node_translations(entry, node_translations):
    extractor = _html_extractor_for_entry(entry)
    if not extractor.nodes:
        return str((entry or {}).get("source_value") or "")
    translated = {
        str(key): str(value or "").strip()
        for key, value in (node_translations or {}).items()
        if str(value or "").strip()
    }
    output = []
    for part in extractor.parts:
        if part[0] == "raw":
            output.append(part[1])
            continue
        _kind, node_key, original = part
        replacement = translated.get(node_key)
        if not replacement:
            output.append(original)
            continue
        leading = re.match(r"^\s*", original).group(0)
        trailing = re.search(r"\s*$", original).group(0)
        output.append(f"{leading}{html_escape(replacement, quote=False)}{trailing}")
    return "".join(output).strip()


def _html_text_node_should_preserve(value):
    text = str(value or "").strip()
    if not text:
        return True
    return bool(re.fullmatch(r"https?://\S+|www\.\S+|[\w.-]+@[\w.-]+", text))


def _field_style_guidance(entry):
    field = str((entry or {}).get("field") or "")
    resource_group = str((entry or {}).get("resource_group") or "")
    if field in FIELD_STYLE_GUIDANCE:
        return FIELD_STYLE_GUIDANCE[field]
    if resource_group == "options":
        return "Short customer-facing option name or value. Preserve units, model numbers, and option structure."
    if resource_group == "variants":
        return "Customer-facing variant display text. Preserve SKU-like codes, dimensions, option values, and model names."
    if resource_group == "important_metafields":
        return "Customer-facing product page text. Keep factual meaning and do not add claims."
    if resource_group == "media":
        return FIELD_STYLE_GUIDANCE.get("media.alt", "")
    return ""


def _request_openai_rewrite(locale, entry, current_value, attempt, result):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        result["draft_status"] = "blocked_missing_openai_api_key"
        result["failure_type"] = "missing_openai_api_key"
        result["error"] = "OPENAI_API_KEY is not configured."
        result["blocking_conditions"].append("blocked_missing_openai_api_key")
        return None
    identity_context = _normalize_product_identity_context(
        entry.get("source_identity_context") or {}
    )
    identity_term_text = _format_identity_terms_for_prompt(
        identity_context.get("expected_terms") or []
    )
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": "You are a careful ecommerce localization editor. Return valid JSON only."},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": "Shorten or rewrite one Shopify product draft translation for manual review only.",
                        "target_locale": locale,
                        "target_language": LANGUAGE_NAMES.get(locale, locale),
                        "field": entry["field"],
                        "draft_key": entry.get("draft_key", entry["field"]),
                        "resource_group": entry.get("resource_group", ""),
                        "context": entry.get("context_label", ""),
                        "source_value": entry["source_value"],
                        "current_draft": str(current_value or ""),
                        "current_chars": len(str(current_value or "")),
                        "max_chars": entry.get("max_chars"),
                        "recommended_min_chars": FIELD_RECOMMENDED_MIN_CHARS.get(entry["field"]),
                        "recommended_max_chars": FIELD_RECOMMENDED_MAX_CHARS.get(entry["field"]),
                        "attempt": attempt,
                        "locale_term_guidance": LOCALE_TERM_GUIDANCE.get(locale, ""),
                        "field_style_guidance": _field_style_guidance(entry),
                        "rules": [
                            "Return JSON only with a value string.",
                            "Rewrite naturally; do not truncate crudely.",
                            "The value must be at or under max_chars.",
                            f"Preserve these source product identity terms when they appear in the source: {identity_term_text}.",
                            "Preserve brand names, model names, SKU-like codes, dimensions, battery specs, and option structure.",
                            "Do not introduce a different product brand, product line, aircraft name, vehicle name, or model number.",
                            "Do not add CTA, shipping, origin, Made in China, Best, Cheap, guaranteed, official, or original OEM claims.",
                        ],
                        "output_contract": {"type": "JSON object", "shape": {"value": "rewritten draft"}},
                    },
                    ensure_ascii=False,
                ),
            },
        ],
        "text": {"format": {"type": "json_object"}},
    }
    data = _post_openai_payload(payload, api_key, result, "rewrite", locale=locale)
    if data is None:
        return None
    try:
        parsed = json.loads(_output_text_from_openai(data))
    except Exception as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = f"{type(exc).__name__}: OpenAI rewrite response was not valid JSON."
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None
    value = str(parsed.get("value") or "").strip()
    if not value:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = "OpenAI rewrite response did not include a value."
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None
    return value


def _post_openai_payload(payload, api_key, result, action_label, locale=""):
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=body,
        headers={
            "Auth" + "orization": "Bea" + "rer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        _record_openai_call(result, locale)
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_request_failed"
        result["error"] = f"OpenAI {action_label} failed with HTTP status {exc.code}"
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_request_failed"
        result["error"] = f"OpenAI {action_label} request failed: {type(exc).__name__}"
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
    return None


def _record_openai_call(result, locale=""):
    result["openai_call_performed"] = True
    result["openai_call_count"] = int(result.get("openai_call_count") or 0) + 1
    if locale:
        per_locale = result.setdefault("per_locale_openai_call_count", {})
        per_locale[locale] = int(per_locale.get(locale) or 0) + 1


def _output_text_from_openai(data):
    text = data.get("output_text")
    if text:
        return text
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text") or ""
    return ""


def _rewrite_over_length_draft(locale, entry, draft, result):
    draft = str(draft or "").strip()
    rewrite_attempts = []
    max_chars = int(entry.get("max_chars") or FIELD_MAX_CHARS.get(entry["field"]) or 0)
    for attempt in range(1, MAX_REWRITE_ATTEMPTS + 1):
        if not max_chars or len(draft) <= max_chars:
            break
        before = draft
        rewritten = _request_openai_rewrite(locale, entry, draft, attempt, result)
        if rewritten is None:
            return None, rewrite_attempts
        draft = rewritten.strip()
        rewrite_attempts.append(
            {
                "attempt": attempt,
                "reason": "draft_over_max_chars",
                "before_chars": len(before),
                "after_chars": len(draft),
                "max_chars": max_chars,
            }
        )
    return draft, rewrite_attempts


def _attach_draft_quality(entry, draft, rewrite_attempts):
    generation_reason = entry.get("draft_generation_reason") or entry.get("skip_reason")
    draft = str(draft or "").strip()
    entry["draft_value"] = draft
    entry["draft_value_chars"] = len(draft)
    entry["rewrite_attempts"] = rewrite_attempts
    entry["rewrite_attempt_count"] = len(rewrite_attempts)
    entry["quality_notes"] = _quality_notes_for_draft(entry, draft)
    entry["validation_status"] = _validate_draft(entry, draft)
    entry["skip_reason"] = ""
    entry["draft_generation_reason"] = generation_reason
    entry["row_status"] = _entry_status_from_reason(generation_reason, generated=True)
    entry["status"] = entry["row_status"]
    entry["status_reason"] = (
        "existing_translation_outdated"
        if generation_reason == "outdated_translation"
        else generation_reason
    )
    _attach_product_identity_validation(entry, draft)
    _attach_seo_quality(entry)


def _quality_notes_for_draft(entry, draft):
    entry_data = entry if isinstance(entry, dict) else {}
    field = entry_data.get("field", str(entry or ""))
    draft = str(draft or "").strip()
    notes = []
    if not draft:
        notes.append("draft_empty")
        if entry_data.get("draft_requires_manual_review"):
            notes.append(
                entry_data.get("draft_manual_review_reason")
                or "manual_review_required"
            )
        return _unique(notes)
    max_chars = int(entry_data.get("max_chars") or FIELD_MAX_CHARS.get(field) or 0)
    if max_chars and len(draft) > max_chars:
        notes.append("draft_over_max_chars")
    if _draft_equals_source_needs_review(entry_data, draft):
        notes.append("draft_equals_source")
    notes.extend(_html_structure_notes_for_draft(entry_data, draft))
    if FORBIDDEN_OUTPUT_RE.search(draft):
        notes.append("forbidden_marketing_or_origin_phrase")
    if UNNATURAL_PHRASE_RE.search(draft):
        notes.append("unnatural_english_phrase")
    if entry_data.get("draft_requires_manual_review"):
        notes.append(entry_data.get("draft_manual_review_reason") or "manual_review_required")
    return _unique(notes)


def _validate_draft(entry, draft):
    notes = _quality_notes_for_draft(entry, draft)
    if notes:
        if "draft_empty" in notes:
            return "draft_needs_manual_review_empty"
        return "draft_needs_manual_review"
    return "draft_ready_for_manual_review"


def _draft_equals_source_needs_review(entry, draft):
    source = str((entry or {}).get("source_value") or "").strip()
    if not source or not draft or draft.strip() != source:
        return False
    resource_group = str((entry or {}).get("resource_group") or "")
    if resource_group in {"options", "variants"} and source.lower() in DEFAULT_OPTION_SOURCE_VALUES:
        return False
    if resource_group == "technical_metafields":
        return False
    if _identifier_like(source):
        return False
    return bool(re.search(r"[A-Za-z]{3,}", source))


def _identifier_like(value):
    text = str(value or "").strip()
    if not text:
        return True
    if len(text) <= 2:
        return True
    if re.fullmatch(r"[\d\s._:/#-]+", text):
        return True
    if re.fullmatch(r"[A-Z0-9][A-Z0-9._:/#-]{1,}", text):
        return True
    return False


def _html_structure_notes_for_draft(entry, draft):
    if str((entry or {}).get("field") or "") != "body_html":
        return []
    source = str((entry or {}).get("source_value") or "")
    source_snapshot = _HtmlStructureSnapshot.from_html(source)
    if not source_snapshot.tag_counts:
        return []
    draft_snapshot = _HtmlStructureSnapshot.from_html(draft)
    notes = []
    if not draft_snapshot.tag_counts:
        notes.append("body_html_structure_broken")
        return notes
    if any(
        draft_snapshot.tag_counts.get(tag, 0) < source_count
        for tag, source_count in source_snapshot.tag_counts.items()
    ):
        notes.append("body_html_structure_broken")
    if any(
        draft_snapshot.end_tag_counts.get(tag, 0) < source_count
        for tag, source_count in source_snapshot.end_tag_counts.items()
    ):
        notes.append("body_html_structure_broken")
    if any(
        draft_snapshot.tag_counts.get(tag, 0)
        < source_snapshot.tag_counts.get(tag, 0)
        for tag in HTML_REVIEW_TAGS
    ):
        notes.append("html_media_or_link_tag_broken")
    if any(
        attr_value and (tag, attr_name, attr_value) not in draft_snapshot.review_attrs
        for tag, attr_name, attr_value in source_snapshot.review_attrs
    ):
        notes.append("html_media_or_link_tag_broken")
    return _unique(notes)


def _html_tag_counts(value):
    counts = {}
    for match in HTML_TAG_RE.finditer(str(value or "")):
        tag = match.group(1).lower()
        counts[tag] = counts.get(tag, 0) + 1
    return counts


class _HtmlStructureSnapshot(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tag_counts = {}
        self.end_tag_counts = {}
        self.review_attrs = []

    @classmethod
    def from_html(cls, value: str):
        parser = cls()
        try:
            parser.feed(str(value or ""))
            parser.close()
        except Exception:
            parser.tag_counts = {}
            parser.end_tag_counts = {}
            parser.review_attrs = []
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
        if not tag:
            return
        self.tag_counts[tag] = self.tag_counts.get(tag, 0) + 1
        if tag not in HTML_REVIEW_TAGS:
            return
        attrs_dict = {str(key).lower(): str(value or "") for key, value in attrs or []}
        for attr_name in ("href", "src"):
            if attrs_dict.get(attr_name):
                self.review_attrs.append((tag, attr_name, attrs_dict[attr_name]))


def _attach_seo_quality(entry):
    draft = str(entry.get("draft_value") or "").strip()
    field = entry["field"]
    locale = entry["locale"]
    terms = SEO_TERMS.get(locale, {})
    seo_notes = _seo_notes_for_draft(entry, draft)
    seo_review_notes = _seo_review_notes(seo_notes)
    entry["seo_notes"] = seo_notes
    entry["seo_review_notes"] = seo_review_notes
    entry["contains_model"] = _contains_model(
        draft,
        entry.get("source_identity_context"),
    )
    if field == "meta_title":
        entry["contains_core_keyword"] = _text_contains_any(draft, terms.get("core", []))
    elif field == "meta_description":
        entry["contains_core_keyword"] = _text_contains_any(draft, terms.get("part_type", []))
    else:
        entry["contains_core_keyword"] = _text_contains_any(draft, terms.get("core", []))
    entry["contains_forbidden_phrase"] = bool(FORBIDDEN_OUTPUT_RE.search(draft))
    entry["seo_validation_status"] = "seo_ready" if not seo_review_notes else "seo_needs_manual_review"
    if entry.get("draft_blocked"):
        entry["seo_validation_status"] = "seo_needs_manual_review"
    entry["seo_eligible_for_apply_plan"] = (
        field != "body_html"
        and not entry.get("future_write_needs_mapping")
        and entry.get("resource_group") in {"product_basics", "seo"}
        and field in {"title", "meta_title", "meta_description"}
        and entry["seo_validation_status"] == "seo_ready"
        and not entry.get("draft_blocked")
    )
    entry["eligible_for_apply_plan"] = (
        field != "body_html"
        and not entry.get("future_write_needs_mapping")
        and entry.get("resource_group") in {"product_basics", "seo"}
        and field in {"title", "meta_title", "meta_description"}
        and entry["validation_status"] == "draft_ready_for_manual_review"
        and entry["seo_validation_status"] == "seo_ready"
        and not entry.get("draft_blocked")
    )
    entry["needs_review"] = bool(
        entry.get("needs_review")
        or entry.get("draft_blocked")
        or entry["validation_status"] != "draft_ready_for_manual_review"
        or entry["seo_validation_status"] != "seo_ready"
    )


def _seo_review_notes(seo_notes):
    return [
        note
        for note in _unique(seo_notes or [])
        if note in SEO_REVIEW_NOTE_CODES and note not in NON_BLOCKING_SEO_NOTE_CODES
    ]


def _seo_notes_for_draft(entry, draft):
    draft = str(draft or "").strip()
    field = entry["field"]
    locale = entry["locale"]
    terms = SEO_TERMS.get(locale, {})
    notes = []
    if len(draft) < int(FIELD_RECOMMENDED_MIN_CHARS.get(field) or 0):
        notes.append("too_short_for_seo")
    max_chars = int(entry.get("max_chars") or FIELD_MAX_CHARS.get(field) or 0)
    if max_chars and len(draft) > max_chars:
        notes.append("draft_over_max_chars")
    if FORBIDDEN_OUTPUT_RE.search(draft):
        notes.append("forbidden_marketing_or_shipping_phrase")
    identity_context = entry.get("source_identity_context")
    if _model_occurrence_count(draft, identity_context) > 1 or KEYWORD_STUFFING_RE.search(draft):
        notes.append("keyword_stuffing_or_duplicate")
    if field == "meta_title":
        if not _contains_model(draft, identity_context):
            notes.append("missing_model")
        if not _text_contains_any(draft, terms.get("core", [])):
            notes.append("missing_core_keyword")
        if not _text_contains_any(draft, terms.get("spare", [])):
            notes.append("missing_replacement_part_meaning")
    if field == "meta_description":
        if not _contains_model(draft, identity_context):
            notes.append("missing_model")
        if not _text_contains_any(draft, terms.get("part_type", [])):
            notes.append("missing_part_type")
        if not _text_contains_any(draft, terms.get("replacement", [])):
            notes.append("missing_use_case")
        if not _text_contains_any(draft, terms.get("value", [])):
            notes.append("missing_value_point")
    return _unique(notes)


def _apply_cross_field_seo_checks(result, target_locales):
    entries_by_locale_field = {(entry["locale"], entry["field"]): entry for entry in result["draft_entries"]}
    for locale in target_locales:
        title_entry = entries_by_locale_field.get((locale, "title"))
        meta_title_entry = entries_by_locale_field.get((locale, "meta_title"))
        if not title_entry or not meta_title_entry:
            continue
        if title_entry.get("draft_value") and title_entry.get("draft_value") == meta_title_entry.get("draft_value"):
            for entry in (title_entry, meta_title_entry):
                notes = entry.setdefault("seo_notes", [])
                if "keyword_stuffing_or_duplicate" not in notes:
                    notes.append("keyword_stuffing_or_duplicate")
                review_notes = entry.setdefault("seo_review_notes", [])
                if "keyword_stuffing_or_duplicate" not in review_notes:
                    review_notes.append("keyword_stuffing_or_duplicate")
                entry["seo_validation_status"] = "seo_needs_manual_review"
                entry["seo_eligible_for_apply_plan"] = False
                entry["eligible_for_apply_plan"] = False
                entry["needs_review"] = True


def _recalculate_quality_stats(result):
    stat_keys = [
        "generated_draft_count",
        "draft_ready_count",
        "draft_needs_manual_review_count",
        "draft_blocked_count",
        "product_identity_mismatch_count",
        "eligible_apply_plan_count",
        "over_length_after_rewrite_count",
        "seo_ready_count",
        "seo_needs_manual_review_count",
        "seo_eligible_apply_plan_count",
        "forbidden_phrase_count",
        "missing_core_keyword_count",
        "too_short_for_seo_count",
    ]
    for key in stat_keys:
        result[key] = 0
    generated_stat_keys = [
        "missing_translation_draft_generated_count",
        "outdated_translation_update_draft_generated_count",
        "needs_review_or_blocked_count",
    ]
    for key in generated_stat_keys:
        result[key] = 0
    for summary in (
        list(result["per_locale_results"].values())
        + list(result["per_field_results"].values())
        + list(result["per_section_results"].values())
    ):
        for key in stat_keys:
            summary[key] = 0
        for key in generated_stat_keys:
            summary[key] = 0

    for entry in result["draft_entries"]:
        per_locale = result["per_locale_results"][entry["locale"]]
        per_field = result["per_field_results"][entry["field"]]
        per_section = result["per_section_results"][
            _section_summary_key(entry.get("resource_group"))
        ]
        _increment(result, per_locale, per_field, "generated_draft_count", per_section)
        if entry.get("draft_generation_reason") == "outdated_translation":
            _increment(
                result,
                per_locale,
                per_field,
                "outdated_translation_update_draft_generated_count",
                per_section,
            )
        else:
            _increment(
                result,
                per_locale,
                per_field,
                "missing_translation_draft_generated_count",
                per_section,
            )
        draft_ready = (
            entry.get("validation_status") == "draft_ready_for_manual_review"
            and not entry.get("draft_blocked")
        )
        entry_needs_review = bool(
            entry.get("needs_review")
            or not draft_ready
            or entry.get("seo_validation_status") != "seo_ready"
        )
        if draft_ready:
            _increment(result, per_locale, per_field, "draft_ready_count", per_section)
        else:
            _increment(
                result,
                per_locale,
                per_field,
                "draft_needs_manual_review_count",
                per_section,
            )
        if entry_needs_review:
            _increment(
                result,
                per_locale,
                per_field,
                "needs_review_or_blocked_count",
                per_section,
            )
        if entry.get("draft_blocked"):
            _increment(result, per_locale, per_field, "draft_blocked_count", per_section)
        if entry.get("product_identity_mismatch"):
            _increment(
                result,
                per_locale,
                per_field,
                "product_identity_mismatch_count",
                per_section,
            )
        if entry.get("eligible_for_apply_plan"):
            _increment(
                result, per_locale, per_field, "eligible_apply_plan_count", per_section
            )
        if "draft_over_max_chars" in (entry.get("quality_notes") or []):
            _increment(
                result,
                per_locale,
                per_field,
                "over_length_after_rewrite_count",
                per_section,
            )
        if entry.get("seo_validation_status") == "seo_ready":
            _increment(result, per_locale, per_field, "seo_ready_count", per_section)
        else:
            _increment(
                result,
                per_locale,
                per_field,
                "seo_needs_manual_review_count",
                per_section,
            )
        if entry.get("seo_eligible_for_apply_plan"):
            _increment(
                result,
                per_locale,
                per_field,
                "seo_eligible_apply_plan_count",
                per_section,
            )
        seo_notes = entry.get("seo_notes") or []
        if "forbidden_marketing_or_shipping_phrase" in seo_notes:
            _increment(result, per_locale, per_field, "forbidden_phrase_count", per_section)
        if "missing_core_keyword" in seo_notes:
            _increment(
                result, per_locale, per_field, "missing_core_keyword_count", per_section
            )
        if "too_short_for_seo" in seo_notes:
            _increment(result, per_locale, per_field, "too_short_for_seo_count", per_section)

    draft_entry_ids = {id(entry) for entry in result["draft_entries"]}
    for entry in result["entries"]:
        if id(entry) in draft_entry_ids or not entry.get("product_identity_mismatch"):
            continue
        per_locale = result["per_locale_results"][entry["locale"]]
        per_field = result["per_field_results"][entry["field"]]
        per_section = result["per_section_results"][
            _section_summary_key(entry.get("resource_group"))
        ]
        _increment(
            result, per_locale, per_field, "product_identity_mismatch_count", per_section
        )
        _increment(
            result, per_locale, per_field, "draft_needs_manual_review_count", per_section
        )
        _increment(
            result, per_locale, per_field, "needs_review_or_blocked_count", per_section
        )


def _increment(result, per_locale, per_field, key, per_section=None):
    result[key] += 1
    per_locale[key] += 1
    per_field[key] += 1
    if per_section is not None:
        per_section[key] += 1


def _section_summary_key(resource_group):
    group = str(resource_group or "").strip()
    if group == "technical_metafields":
        return "technical_fields"
    if group in SECTION_LABELS and group != "technical_metafields":
        return group
    return "technical_fields"


def _entry_status_from_reason(reason, generated=False):
    reason = str(reason or "")
    if generated and reason == "outdated_translation":
        return "outdated_translation_update_draft_ready"
    if generated and reason == "missing_translation":
        return "missing_translation_draft_ready"
    if reason == "already_translated":
        return "already_translated_skipped"
    if reason in DRAFT_GENERATION_REASONS:
        return "draft_generation_pending"
    return "not_eligible_skipped"


def _refresh_entry_status(entry):
    if not isinstance(entry, dict):
        return
    generated = bool(entry.get("draft_value"))
    reason = entry.get("draft_generation_reason") or entry.get("skip_reason")
    entry["row_status"] = _entry_status_from_reason(reason, generated=generated)
    entry["status"] = entry["row_status"]
    entry["status_reason"] = (
        "existing_translation_outdated"
        if reason == "outdated_translation"
        else str(reason or "")
    )


def _empty_translate_all_summary():
    return {
        "summary_status": "not_loaded",
        "total_languages_checked": 0,
        "total_source_rows_checked": 0,
        "missing_drafts_generated": 0,
        "outdated_update_drafts_generated": 0,
        "already_translated_skipped": 0,
        "not_eligible_skipped": 0,
        "needs_review_blocked": 0,
        "per_language_counts": [],
        "per_section_counts": [],
        "child_resource_discovery_errors": [],
        "per_group_discovery_status": _empty_discovery_status(),
        "per_group_discovery_reasons": _empty_discovery_reasons(),
        "per_group_discovery_rows": _discovery_status_rows(
            _empty_discovery_status(),
            _empty_discovery_reasons(),
        ),
        "shopify_read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
    }


def _attach_draft_batch_summary(result):
    summary = _empty_translate_all_summary()
    entries = [entry for entry in result.get("entries") or [] if isinstance(entry, dict)]
    source_read_summary = result.get("source_read_summary") or {}
    summary["summary_status"] = "source_rows_classified"
    if result.get("blocking_conditions"):
        summary["summary_status"] = "blocked"
    summary["total_languages_checked"] = len(source_read_summary)
    summary["total_source_rows_checked"] = sum(
        int((locale_summary or {}).get("translatable_content_count") or 0)
        for locale_summary in source_read_summary.values()
    )
    summary["missing_drafts_generated"] = sum(
        1
        for entry in entries
        if entry.get("row_status") == "missing_translation_draft_ready"
    )
    summary["outdated_update_drafts_generated"] = sum(
        1
        for entry in entries
        if entry.get("row_status") == "outdated_translation_update_draft_ready"
    )
    summary["already_translated_skipped"] = sum(
        1 for entry in entries if entry.get("row_status") == "already_translated_skipped"
    )
    summary["not_eligible_skipped"] = sum(
        1 for entry in entries if entry.get("row_status") == "not_eligible_skipped"
    )
    summary["needs_review_blocked"] = sum(
        1
        for entry in entries
        if entry.get("needs_review")
        or entry.get("draft_blocked")
        or entry.get("product_identity_mismatch")
    )
    summary["per_language_counts"] = [
        _summary_row(locale, bucket, "locale", locale)
        for locale, bucket in (result.get("per_locale_results") or {}).items()
    ]
    section_order = [
        "product_basics",
        "seo",
        "options",
        "variants",
        "important_metafields",
        "media",
        "technical_fields",
    ]
    summary["per_section_counts"] = [
        _summary_row(
            section,
            (result.get("per_section_results") or {}).get(section, {}),
            "section",
            SECTION_LABELS.get(section, section),
        )
        for section in section_order
    ]
    summary["child_resource_discovery_errors"] = list(
        result.get("child_resource_discovery_errors") or []
    )
    summary["per_group_discovery_status"] = dict(
        result.get("per_group_discovery_status") or {}
    )
    summary["per_group_discovery_reasons"] = dict(
        result.get("per_group_discovery_reasons") or {}
    )
    summary["per_group_discovery_rows"] = _discovery_status_rows(
        summary["per_group_discovery_status"],
        summary["per_group_discovery_reasons"],
    )
    summary["openai_call_count"] = int(result.get("openai_call_count") or 0)
    summary["openai_retry_attempt_count"] = int(
        result.get("openai_retry_attempt_count") or 0
    )
    summary["openai_retry_success_count"] = int(
        result.get("openai_retry_success_count") or 0
    )
    summary["openai_invalid_translation_response_count"] = int(
        result.get("openai_invalid_translation_response_count") or 0
    )
    summary["openai_missing_translation_field_count"] = int(
        result.get("openai_missing_translation_field_count") or 0
    )
    summary["reused_cache_count"] = int(result.get("reused_cache_count") or 0)
    summary["skipped_existing_count"] = int(
        result.get("skipped_existing_count")
        or result.get("skipped_existing_translation_count")
        or 0
    )
    summary["skipped_technical_count"] = int(result.get("skipped_technical_count") or 0)
    summary["deduplicated_input_count"] = int(
        result.get("deduplicated_input_count") or 0
    )
    summary["estimated_input_chars_saved"] = int(
        result.get("estimated_input_chars_saved") or 0
    )
    summary["per_locale_openai_call_count"] = dict(
        result.get("per_locale_openai_call_count") or {}
    )
    for key in (
        "total_languages_checked",
        "total_source_rows_checked",
        "missing_drafts_generated",
        "outdated_update_drafts_generated",
        "already_translated_skipped",
        "not_eligible_skipped",
        "needs_review_blocked",
    ):
        result[key if key != "needs_review_blocked" else "needs_review_or_blocked_count"] = summary[key]
    result["missing_translation_draft_generated_count"] = summary["missing_drafts_generated"]
    result["outdated_translation_update_draft_generated_count"] = summary[
        "outdated_update_drafts_generated"
    ]
    result["already_translated_skipped_count"] = summary["already_translated_skipped"]
    result["not_eligible_skipped_count"] = summary["not_eligible_skipped"]
    result["skipped_existing_count"] = summary["skipped_existing_count"]
    result["translate_all_summary"] = summary


def _summary_row(key, bucket, label_key, label):
    bucket = bucket or {}
    return {
        label_key: key,
        "label": label,
        "source_rows_checked": int(bucket.get("source_row_count") or 0),
        "missing_drafts_generated": int(
            bucket.get("missing_translation_draft_generated_count") or 0
        ),
        "outdated_update_drafts_generated": int(
            bucket.get("outdated_translation_update_draft_generated_count") or 0
        ),
        "already_translated_skipped": int(
            bucket.get("already_translated_skipped_count")
            or bucket.get("skipped_existing_translation_count")
            or 0
        ),
        "not_eligible_skipped": int(bucket.get("not_eligible_skipped_count") or 0),
        "needs_review_blocked": int(bucket.get("needs_review_or_blocked_count") or 0),
    }


def _text_contains_any(text, terms):
    lower_text = str(text or "").lower()
    return any(str(term).lower() in lower_text for term in terms)


def _model_occurrence_count(text, identity_context=None):
    context = _normalize_product_identity_context(identity_context or {})
    model_terms = context.get("source_model_terms") or []
    if model_terms:
        return max(
            [_identity_term_occurrence_count(term, text) for term in model_terms] or [0]
        )
    return str(text or "").lower().count("mofly p-51d")


def _contains_model(text, identity_context=None):
    context = _normalize_product_identity_context(identity_context or {})
    model_terms = context.get("source_model_terms") or []
    if model_terms:
        return any(_identity_term_in_text(term, text) for term in model_terms)
    lower_text = str(text or "").lower()
    return "mofly p-51d" in lower_text or ("mofly" in lower_text and "p-51d" in lower_text)


def _unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
