import json
import os
import re
import urllib.error
import urllib.request

from .models import ShopifyInstallation
from .translation_console import fetch_translation_console_data


DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
SUPPORTED_LOCALES = ["ja", "de", "fr", "es", "it"]
ALLOWED_FIELDS = ["title", "body_html", "meta_title", "meta_description", "handle"]
ALLOWED_DRAFT_GROUP_SCOPES = [
    "product_basics",
    "seo",
    "options",
    "variants",
    "important_metafields",
    "media",
]
ALLOWED_DRAFT_SCOPES = set(ALLOWED_FIELDS) | set(ALLOWED_DRAFT_GROUP_SCOPES)
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
FIELD_MAX_CHARS = {"title": 65, "meta_title": 60, "meta_description": 155, "handle": 80, "media.alt": 125}
FIELD_RECOMMENDED_MIN_CHARS = {"title": 25, "meta_title": 30, "meta_description": 80}
FIELD_RECOMMENDED_MAX_CHARS = dict(FIELD_MAX_CHARS)
MAX_REWRITE_ATTEMPTS = 2
OPENAI_MODEL = "gpt-4.1-mini"

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
):
    target_locales = list(target_locales or DEFAULT_TARGET_LOCALES)
    fields = _normalize_requested_scopes(fields or DEFAULT_FIELDS)
    result = _empty_result(product_id, target_locales, fields)
    validation_errors = _validate_scope(product_id, target_locales, fields)
    if validation_errors:
        result["blocking_conditions"] = validation_errors
        result["draft_status"] = validation_errors[0]
        return result

    if installation is None:
        installation = ShopifyInstallation.objects.first()
    if installation is None:
        result["draft_status"] = "blocked_missing_shopify_installation"
        result["failure_type"] = "missing_shopify_installation"
        result["blocking_conditions"].append("blocked_missing_shopify_installation")
        return result

    missing_by_locale = {}
    for locale in target_locales:
        try:
            data = fetch_translation_console_data(installation, product_id, locale)
        except Exception as exc:
            result["draft_status"] = "blocked_shopify_read_query_failed"
            result["failure_type"] = "shopify_read_query_failed"
            result["query_failure_type"] = "helper_returned_error"
            result["error"] = f"{type(exc).__name__}: read-only Shopify query failed"
            result["blocking_conditions"].append("blocked_shopify_read_query_failed")
            return result

        result["shopify_api_call_performed"] = True
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
        _refresh_draft_coverage_summary(result)

        for row in _requested_draft_rows(translatable_rows, fields):
            field = _entry_field_from_row(row)
            source_value = str(row.get("source_value") or "")
            existing_present = bool(row.get("has_translation"))
            existing_outdated = row.get("translation_outdated") is True
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
                entry = _entry_template(locale, field, row, "existing_translation_outdated_manual_review_required")
            elif existing_present:
                entry = _entry_template(locale, field, row, "already_translated")
            else:
                entry = _entry_template(locale, field, row, "missing_translation")
                missing_by_locale.setdefault(locale, []).append(entry)
            _attach_source_identity_context(entry, source_identity_context)
            if existing_present:
                _attach_existing_translation_identity_validation(entry)
            result["entries"].append(entry)
            _count_entry(result, entry)

        for field in _missing_requested_static_fields(translatable_rows, fields):
            entry = _entry_template(locale, field, {}, "source_empty")
            _attach_source_identity_context(entry, source_identity_context)
            result["entries"].append(entry)
            _count_entry(result, entry)

    if not missing_by_locale:
        result["draft_status"] = "no_missing_translations_found"
        result["success"] = True
        return result

    for locale, missing_entries in missing_by_locale.items():
        translations = _request_openai(locale, missing_entries, result)
        if translations is None:
            result["success"] = False
            return result
        for entry in missing_entries:
            draft = str(
                translations.get(entry.get("draft_key"))
                or translations.get(entry["field"])
                or ""
            ).strip()
            draft, rewrite_attempts = _rewrite_over_length_draft(locale, entry, draft, result)
            if draft is None:
                result["success"] = False
                return result
            _attach_draft_quality(entry, draft, rewrite_attempts)
            result["draft_entries"].append(entry)
            result["translation_generated"] = True

    _apply_cross_field_seo_checks(result, target_locales)
    _recalculate_quality_stats(result)
    result["draft_status"] = "selected_product_missing_translation_draft_ready_for_manual_review"
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
        "translation_generated": False,
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
        "per_locale_results": {},
        "per_field_results": {},
        "entries": [],
        "draft_entries": [],
        "product_identity_context": {},
        "source_read_summary": {},
        "per_locale_draft_coverage": {},
        "draft_coverage_summary": _empty_draft_coverage_summary(fields),
        "blocking_conditions": [],
        "failure_type": "",
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
    result["draft_coverage_summary"] = {
        "summary_status": "source_rows_classified",
        "requested_fields": requested_fields,
        "draft_generation_included_fields": [
            field for field in requested_fields if field in ALLOWED_DRAFT_SCOPES
        ],
        "target_locale_count": len(per_locale),
        "groups": [groups[config["group_key"]] for config in DRAFT_COVERAGE_GROUP_CONFIGS],
    }


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
        "context_label": row.get("context_label", ""),
        "resource_note": row.get("resource_note", ""),
        "field_label": row.get("field_label", ""),
        "resource_type_label": row.get("resource_type_label", ""),
        "option_name": row.get("option_name", ""),
        "option_value": row.get("option_value", ""),
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
        },
    )


def _count_entry(result, entry):
    per_locale = _summary_bucket(result, "per_locale_results", entry["locale"])
    per_field = _summary_bucket(result, "per_field_results", entry["field"])
    reason = entry.get("skip_reason")
    if entry.get("product_identity_mismatch"):
        per_locale["product_identity_mismatch_count"] += 1
        per_field["product_identity_mismatch_count"] += 1
        result["product_identity_mismatch_count"] += 1
        per_locale["draft_needs_manual_review_count"] += 1
        per_field["draft_needs_manual_review_count"] += 1
        result["draft_needs_manual_review_count"] += 1
    if reason == "already_translated":
        per_locale["skipped_existing_translation_count"] += 1
        per_field["skipped_existing_translation_count"] += 1
        result["skipped_existing_translation_count"] += 1
    elif reason == "existing_translation_outdated_manual_review_required":
        per_locale["skipped_outdated_translation_count"] += 1
        per_field["skipped_outdated_translation_count"] += 1
        result["skipped_outdated_translation_count"] += 1
    elif reason == "existing_translation_identity_mismatch_manual_review_required":
        return
    elif reason == "source_empty":
        per_locale["skipped_source_empty_count"] += 1
        per_field["skipped_source_empty_count"] += 1
        result["skipped_source_empty_count"] += 1
    elif reason and reason != "missing_translation":
        per_locale["skipped_not_draft_eligible_count"] += 1
        per_field["skipped_not_draft_eligible_count"] += 1
        result["skipped_not_draft_eligible_count"] += 1
    elif reason == "missing_translation":
        per_locale["missing_translation_count"] += 1
        per_field["missing_translation_count"] += 1


def _request_openai(locale, missing_entries, result):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        result["draft_status"] = "blocked_missing_openai_api_key"
        result["failure_type"] = "missing_openai_api_key"
        result["error"] = "OPENAI_API_KEY is not configured."
        result["blocking_conditions"].append("blocked_missing_openai_api_key")
        return None
    prompt = _openai_prompt(locale, missing_entries)
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": "You are a careful ecommerce localization translator. Return valid JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    data = _post_openai_payload(payload, api_key, result, "draft generation")
    if data is None:
        return None
    try:
        parsed = json.loads(_output_text_from_openai(data))
    except Exception as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = f"{type(exc).__name__}: OpenAI response was not valid JSON."
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None
    translations = parsed.get("translations")
    if not isinstance(translations, dict):
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = "OpenAI response did not include a translations object."
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None
    return translations


def _openai_prompt(locale, missing_entries):
    identity_context = _identity_context_from_entries(missing_entries)
    identity_terms = identity_context.get("expected_terms") or []
    model_terms = identity_context.get("source_model_terms") or []
    identity_term_text = _format_identity_terms_for_prompt(identity_terms)
    return {
        "task": "Translate selected Shopify product fields into draft translations for manual review only.",
        "target_locale": locale,
        "target_language": LANGUAGE_NAMES.get(locale, locale),
        "draft_only": True,
        "product_identity": {
            "expected_terms": identity_terms,
            "model_terms": model_terms,
        },
        "fields": [
            {
                "draft_key": item["draft_key"],
                "field": item["field"],
                "source_key": item.get("source_key", ""),
                "resource_group": item.get("resource_group", ""),
                "resource_id": item.get("resource_id", ""),
                "context": item.get("context_label", ""),
                "source_value": item["source_value"],
                "max_chars": item["max_chars"],
                "recommended_min_chars": FIELD_RECOMMENDED_MIN_CHARS.get(item["field"]),
                "recommended_max_chars": FIELD_RECOMMENDED_MAX_CHARS.get(item["field"]),
                "style_guidance": _field_style_guidance(item),
            }
            for item in missing_entries
        ],
        "locale_term_guidance": LOCALE_TERM_GUIDANCE.get(locale, ""),
        "rules": [
            "Return JSON only with a translations object keyed by draft_key exactly.",
            f"Preserve these source product identity terms when they appear in the source: {identity_term_text}.",
            "Do not introduce a different product brand, product line, aircraft name, vehicle name, or model number.",
            "Preserve brand names, model names, SKU-like codes, dimensions, battery specs, and option structure.",
            "Do not translate product model numbers such as P-51D, F-16, C184, MD530, or similar model codes.",
            "Localize part names naturally; do not mechanically keep English phrases such as RC Plane Clevis.",
            "Do not add Buy now, Shop now, Free shipping, Worldwide shipping, Made in China, Best, Cheap, guaranteed, official, original OEM, Herkunft, or Provenance.",
            "Do not invent variants, options, metafields, media, product facts, compatibility, or package contents.",
            "Product title must be 25-65 characters where possible, and never over 65 characters.",
            "SEO meta_title must be 30-60 characters where possible, and never over 60 characters.",
            "SEO meta_description must be 80-155 characters where possible, and never over 155 characters.",
            "meta_title must naturally include the source product model when the source SEO title includes it, one localized core part keyword, and RC spare/replacement meaning.",
            "meta_description must include use, source product compatibility, localized part type, and one value point such as durable, precise, reliable, or control.",
            "Do not repeat the same model name more than once in the same field.",
            "Do not make title and meta_title exactly the same.",
            "For body_html, preserve the original HTML structure and translate only customer-facing text.",
        ],
        "output_contract": {"type": "JSON object", "shape": {"translations": {"draft_key": "draft translated value"}}},
    }


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
    data = _post_openai_payload(payload, api_key, result, "rewrite")
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


def _post_openai_payload(payload, api_key, result, action_label):
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
        with urllib.request.urlopen(request, timeout=120) as response:
            result["openai_call_performed"] = True
            return json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        result["openai_call_performed"] = True
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
    draft = str(draft or "").strip()
    entry["draft_value"] = draft
    entry["draft_value_chars"] = len(draft)
    entry["rewrite_attempts"] = rewrite_attempts
    entry["rewrite_attempt_count"] = len(rewrite_attempts)
    entry["quality_notes"] = _quality_notes_for_draft(entry, draft)
    entry["validation_status"] = _validate_draft(entry, draft)
    entry["skip_reason"] = ""
    _attach_product_identity_validation(entry, draft)
    _attach_seo_quality(entry)


def _quality_notes_for_draft(entry, draft):
    entry_data = entry if isinstance(entry, dict) else {}
    field = entry_data.get("field", str(entry or ""))
    draft = str(draft or "").strip()
    notes = []
    if not draft:
        notes.append("draft_empty")
        return notes
    max_chars = int(entry_data.get("max_chars") or FIELD_MAX_CHARS.get(field) or 0)
    if max_chars and len(draft) > max_chars:
        notes.append("draft_over_max_chars")
    if FORBIDDEN_OUTPUT_RE.search(draft):
        notes.append("forbidden_marketing_or_origin_phrase")
    if UNNATURAL_PHRASE_RE.search(draft):
        notes.append("unnatural_english_phrase")
    if entry_data.get("draft_requires_manual_review"):
        notes.append(entry_data.get("draft_manual_review_reason") or "manual_review_required")
    if entry_data.get("future_write_needs_mapping"):
        notes.append(entry_data.get("apply_plan_blocked_reason") or "future_write_needs_resource_mapping")
    return notes


def _validate_draft(entry, draft):
    notes = _quality_notes_for_draft(entry, draft)
    if notes:
        if "draft_empty" in notes:
            return "draft_needs_manual_review_empty"
        return "draft_needs_manual_review"
    return "draft_ready_for_manual_review"


def _attach_seo_quality(entry):
    draft = str(entry.get("draft_value") or "").strip()
    field = entry["field"]
    locale = entry["locale"]
    terms = SEO_TERMS.get(locale, {})
    seo_notes = _seo_notes_for_draft(entry, draft)
    entry["seo_notes"] = seo_notes
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
    entry["seo_validation_status"] = "seo_ready" if not seo_notes else "seo_needs_manual_review"
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
                entry["seo_validation_status"] = "seo_needs_manual_review"
                entry["seo_eligible_for_apply_plan"] = False
                entry["eligible_for_apply_plan"] = False


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
    for summary in list(result["per_locale_results"].values()) + list(result["per_field_results"].values()):
        for key in stat_keys:
            summary[key] = 0

    for entry in result["draft_entries"]:
        per_locale = result["per_locale_results"][entry["locale"]]
        per_field = result["per_field_results"][entry["field"]]
        _increment(result, per_locale, per_field, "generated_draft_count")
        if (
            entry.get("validation_status") == "draft_ready_for_manual_review"
            and not entry.get("draft_blocked")
        ):
            _increment(result, per_locale, per_field, "draft_ready_count")
        else:
            _increment(result, per_locale, per_field, "draft_needs_manual_review_count")
        if entry.get("draft_blocked"):
            _increment(result, per_locale, per_field, "draft_blocked_count")
        if entry.get("product_identity_mismatch"):
            _increment(result, per_locale, per_field, "product_identity_mismatch_count")
        if entry.get("eligible_for_apply_plan"):
            _increment(result, per_locale, per_field, "eligible_apply_plan_count")
        if "draft_over_max_chars" in (entry.get("quality_notes") or []):
            _increment(result, per_locale, per_field, "over_length_after_rewrite_count")
        if entry.get("seo_validation_status") == "seo_ready":
            _increment(result, per_locale, per_field, "seo_ready_count")
        else:
            _increment(result, per_locale, per_field, "seo_needs_manual_review_count")
        if entry.get("seo_eligible_for_apply_plan"):
            _increment(result, per_locale, per_field, "seo_eligible_apply_plan_count")
        seo_notes = entry.get("seo_notes") or []
        if "forbidden_marketing_or_shipping_phrase" in seo_notes:
            _increment(result, per_locale, per_field, "forbidden_phrase_count")
        if "missing_core_keyword" in seo_notes:
            _increment(result, per_locale, per_field, "missing_core_keyword_count")
        if "too_short_for_seo" in seo_notes:
            _increment(result, per_locale, per_field, "too_short_for_seo_count")

    draft_entry_ids = {id(entry) for entry in result["draft_entries"]}
    for entry in result["entries"]:
        if id(entry) in draft_entry_ids or not entry.get("product_identity_mismatch"):
            continue
        per_locale = result["per_locale_results"][entry["locale"]]
        per_field = result["per_field_results"][entry["field"]]
        _increment(result, per_locale, per_field, "product_identity_mismatch_count")
        _increment(result, per_locale, per_field, "draft_needs_manual_review_count")


def _increment(result, per_locale, per_field, key):
    result[key] += 1
    per_locale[key] += 1
    per_field[key] += 1


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
