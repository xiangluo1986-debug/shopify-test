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
ALLOWED_FIELDS = ["title", "meta_title", "meta_description"]
FIELD_MAX_CHARS = {"title": 65, "meta_title": 60, "meta_description": 155}
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

LANGUAGE_NAMES = {
    "ja": "Japanese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
}
LOCALE_TERM_GUIDANCE = {
    "ja": "Use natural Japanese RC part terms. Preserve MOFLY, P-51D, 690mm, and RC.",
    "de": "Use natural German terms: Querruder, Gabelkopf, Ersatzteil. Do not keep 'RC Plane Clevis'.",
    "fr": "Use natural French terms: aileron, chape, piece de rechange, piece RC.",
    "es": "Use natural Spanish terms: aleron, clevis or horquilla, repuesto RC.",
    "it": "Use natural Italian terms: alettone, forcella, ricambio RC.",
}
FIELD_STYLE_GUIDANCE = {
    "title": "Short store title. Prefer brand/model + part name + spec/use.",
    "meta_title": "Short SEO title with MOFLY P-51D, one core part keyword, and RC spare/replacement meaning.",
    "meta_description": "Natural SEO description with use, compatibility, part type, and one value point; no CTA.",
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
    fields = list(fields or DEFAULT_FIELDS)
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
        rows_by_key = {row.get("key"): row for row in data.get("translatable_rows", []) if row.get("key")}
        result["source_read_summary"][locale] = {
            "translatable_content_count": len(data.get("translatable_rows", [])),
            "translation_count": (data.get("translatable_resource") or {}).get("translation_count", 0),
        }

        for field in fields:
            row = rows_by_key.get(field) or {}
            source_value = str(row.get("source_value") or "")
            existing_present = bool(row.get("has_translation"))
            existing_outdated = row.get("translation_outdated") is True
            if not source_value.strip():
                entry = _entry_template(locale, field, row, "source_empty")
            elif existing_present and existing_outdated:
                entry = _entry_template(locale, field, row, "existing_translation_outdated_manual_review_required")
            elif existing_present:
                entry = _entry_template(locale, field, row, "already_translated")
            else:
                entry = _entry_template(locale, field, row, "missing_translation")
                missing_by_locale.setdefault(locale, []).append(entry)
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
            draft = str(translations.get(entry["field"]) or "").strip()
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
    if not fields or any(field not in ALLOWED_FIELDS for field in fields):
        errors.append("blocked_invalid_field")
    return errors


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
        "per_locale_results": {},
        "per_field_results": {},
        "entries": [],
        "draft_entries": [],
        "source_read_summary": {},
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


def _entry_template(locale, field, row, reason):
    return {
        "locale": locale,
        "field": field,
        "source_key": field,
        "source_value": str((row or {}).get("source_value") or ""),
        "source_digest": str((row or {}).get("digest") or ""),
        "existing_translation_present": bool((row or {}).get("has_translation")),
        "existing_translation_outdated": (row or {}).get("translation_outdated"),
        "draft_value": "",
        "draft_value_chars": 0,
        "max_chars": FIELD_MAX_CHARS.get(field),
        "recommended_min_chars": FIELD_RECOMMENDED_MIN_CHARS.get(field),
        "recommended_max_chars": FIELD_RECOMMENDED_MAX_CHARS.get(field),
        "validation_status": "skipped",
        "seo_validation_status": "skipped",
        "skip_reason": reason,
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


def _summary_bucket(result, key, value):
    return result[key].setdefault(
        value,
        {
            "generated_draft_count": 0,
            "draft_ready_count": 0,
            "draft_needs_manual_review_count": 0,
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
            "missing_translation_count": 0,
        },
    )


def _count_entry(result, entry):
    per_locale = _summary_bucket(result, "per_locale_results", entry["locale"])
    per_field = _summary_bucket(result, "per_field_results", entry["field"])
    reason = entry.get("skip_reason")
    if reason == "already_translated":
        per_locale["skipped_existing_translation_count"] += 1
        per_field["skipped_existing_translation_count"] += 1
        result["skipped_existing_translation_count"] += 1
    elif reason == "existing_translation_outdated_manual_review_required":
        per_locale["skipped_outdated_translation_count"] += 1
        per_field["skipped_outdated_translation_count"] += 1
        result["skipped_outdated_translation_count"] += 1
    elif reason == "source_empty":
        per_locale["skipped_source_empty_count"] += 1
        per_field["skipped_source_empty_count"] += 1
        result["skipped_source_empty_count"] += 1
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
    return {
        "task": "Translate selected Shopify product fields into draft translations for manual review only.",
        "target_locale": locale,
        "target_language": LANGUAGE_NAMES.get(locale, locale),
        "draft_only": True,
        "fields": [
            {
                "field": item["field"],
                "source_value": item["source_value"],
                "max_chars": item["max_chars"],
                "recommended_min_chars": FIELD_RECOMMENDED_MIN_CHARS.get(item["field"]),
                "recommended_max_chars": FIELD_RECOMMENDED_MAX_CHARS.get(item["field"]),
                "style_guidance": FIELD_STYLE_GUIDANCE.get(item["field"], ""),
            }
            for item in missing_entries
        ],
        "locale_term_guidance": LOCALE_TERM_GUIDANCE.get(locale, ""),
        "rules": [
            "Return JSON only with a translations object keyed by field.",
            "Preserve MOFLY, P-51D, 690mm, RC, dimensions, and model numbers exactly.",
            "Localize part names naturally; do not mechanically keep English phrases such as RC Plane Clevis.",
            "Do not add Buy now, Shop now, Free shipping, Worldwide shipping, Made in China, Best, Cheap, guaranteed, official, original OEM, Herkunft, or Provenance.",
            "Product title must be 25-65 characters where possible, and never over 65 characters.",
            "SEO meta_title must be 30-60 characters where possible, and never over 60 characters.",
            "SEO meta_description must be 80-155 characters where possible, and never over 155 characters.",
            "meta_title must naturally include MOFLY P-51D, one localized aileron clevis/core part keyword, and RC spare/replacement meaning.",
            "meta_description must include use, compatibility with MOFLY P-51D or P-51D, localized part type, and one value point such as durable, precise, reliable, or control.",
            "Do not repeat MOFLY P-51D more than once in the same field.",
            "Do not make title and meta_title exactly the same.",
        ],
        "output_contract": {"type": "JSON object", "shape": {"translations": {"field_name": "draft translated value"}}},
    }


def _request_openai_rewrite(locale, entry, current_value, attempt, result):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        result["draft_status"] = "blocked_missing_openai_api_key"
        result["failure_type"] = "missing_openai_api_key"
        result["error"] = "OPENAI_API_KEY is not configured."
        result["blocking_conditions"].append("blocked_missing_openai_api_key")
        return None
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
                        "source_value": entry["source_value"],
                        "current_draft": str(current_value or ""),
                        "current_chars": len(str(current_value or "")),
                        "max_chars": entry.get("max_chars"),
                        "recommended_min_chars": FIELD_RECOMMENDED_MIN_CHARS.get(entry["field"]),
                        "recommended_max_chars": FIELD_RECOMMENDED_MAX_CHARS.get(entry["field"]),
                        "attempt": attempt,
                        "locale_term_guidance": LOCALE_TERM_GUIDANCE.get(locale, ""),
                        "field_style_guidance": FIELD_STYLE_GUIDANCE.get(entry["field"], ""),
                        "rules": [
                            "Return JSON only with a value string.",
                            "Rewrite naturally; do not truncate crudely.",
                            "The value must be at or under max_chars.",
                            "Preserve MOFLY, P-51D, 690mm, and RC exactly.",
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
    entry["quality_notes"] = _quality_notes_for_draft(entry["field"], draft)
    entry["validation_status"] = _validate_draft(entry["field"], draft)
    entry["skip_reason"] = ""
    _attach_seo_quality(entry)


def _quality_notes_for_draft(field, draft):
    draft = str(draft or "").strip()
    notes = []
    if not draft:
        notes.append("draft_empty")
        return notes
    if len(draft) > int(FIELD_MAX_CHARS.get(field) or 0):
        notes.append("draft_over_max_chars")
    if FORBIDDEN_OUTPUT_RE.search(draft):
        notes.append("forbidden_marketing_or_origin_phrase")
    if UNNATURAL_PHRASE_RE.search(draft):
        notes.append("unnatural_english_phrase")
    return notes


def _validate_draft(field, draft):
    notes = _quality_notes_for_draft(field, draft)
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
    entry["contains_model"] = _contains_model(draft)
    if field == "meta_title":
        entry["contains_core_keyword"] = _text_contains_any(draft, terms.get("core", []))
    elif field == "meta_description":
        entry["contains_core_keyword"] = _text_contains_any(draft, terms.get("part_type", []))
    else:
        entry["contains_core_keyword"] = _text_contains_any(draft, terms.get("core", []))
    entry["contains_forbidden_phrase"] = bool(FORBIDDEN_OUTPUT_RE.search(draft))
    entry["seo_validation_status"] = "seo_ready" if not seo_notes else "seo_needs_manual_review"
    entry["seo_eligible_for_apply_plan"] = entry["seo_validation_status"] == "seo_ready"
    entry["eligible_for_apply_plan"] = (
        entry["validation_status"] == "draft_ready_for_manual_review"
        and entry["seo_validation_status"] == "seo_ready"
    )


def _seo_notes_for_draft(entry, draft):
    draft = str(draft or "").strip()
    field = entry["field"]
    locale = entry["locale"]
    terms = SEO_TERMS.get(locale, {})
    notes = []
    if len(draft) < int(FIELD_RECOMMENDED_MIN_CHARS.get(field) or 0):
        notes.append("too_short_for_seo")
    if len(draft) > int(FIELD_MAX_CHARS.get(field) or 0):
        notes.append("draft_over_max_chars")
    if FORBIDDEN_OUTPUT_RE.search(draft):
        notes.append("forbidden_marketing_or_shipping_phrase")
    if _model_occurrence_count(draft) > 1 or KEYWORD_STUFFING_RE.search(draft):
        notes.append("keyword_stuffing_or_duplicate")
    if field == "meta_title":
        if not _contains_model(draft):
            notes.append("missing_model")
        if not _text_contains_any(draft, terms.get("core", [])):
            notes.append("missing_core_keyword")
        if not _text_contains_any(draft, terms.get("spare", [])):
            notes.append("missing_replacement_part_meaning")
    if field == "meta_description":
        if not _contains_model(draft):
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
        if entry.get("validation_status") == "draft_ready_for_manual_review":
            _increment(result, per_locale, per_field, "draft_ready_count")
        else:
            _increment(result, per_locale, per_field, "draft_needs_manual_review_count")
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


def _increment(result, per_locale, per_field, key):
    result[key] += 1
    per_locale[key] += 1
    per_field[key] += 1


def _text_contains_any(text, terms):
    lower_text = str(text or "").lower()
    return any(str(term).lower() in lower_text for term in terms)


def _model_occurrence_count(text):
    return str(text or "").lower().count("mofly p-51d")


def _contains_model(text):
    lower_text = str(text or "").lower()
    return "mofly p-51d" in lower_text or ("mofly" in lower_text and "p-51d" in lower_text)


def _unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
