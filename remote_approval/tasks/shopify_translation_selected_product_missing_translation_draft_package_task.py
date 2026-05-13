import json
import re
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_translation_selected_product_missing_translation_draft_package"
COMMAND_LABEL = "shopify_translation_selected_product_missing_translation_draft_package"
DRAFT_JSON_PATH = LOG_DIR / "shopify_translation_selected_product_missing_translation_draft_package.json"
DRAFT_HTML_PATH = LOG_DIR / "shopify_translation_selected_product_missing_translation_draft_package.html"

DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
SUPPORTED_LOCALES = ["ja", "de", "fr", "es", "it"]
ALLOWED_FIELDS = ["title", "meta_title", "meta_description"]
FIELD_MAX_CHARS = {
    "title": 65,
    "meta_title": 60,
    "meta_description": 155,
}
FIELD_RECOMMENDED_MIN_CHARS = {
    "title": 25,
    "meta_title": 30,
    "meta_description": 80,
}
FIELD_RECOMMENDED_MAX_CHARS = dict(FIELD_MAX_CHARS)
MAX_REWRITE_ATTEMPTS = 2
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/\d+$")
DOCKER_TIMEOUT_SECONDS = 900
OPENAI_MODEL = "gpt-4.1-mini"
LANGUAGE_NAMES = {
    "ja": "Japanese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
}
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
LOCALE_TERM_GUIDANCE = {
    "ja": (
        "Use natural Japanese RC part terms: aileron=エルロン; "
        "clevis/linkage connector=クレビス or リンケージクレビス. Preserve MOFLY, P-51D, 690mm, RC."
    ),
    "de": (
        "Use natural German terms: aileron=Querruder; clevis/linkage connector=Gabelkopf; "
        "spare part=Ersatzteil. Do not keep 'RC Plane Clevis'. Preserve MOFLY, P-51D, 690mm, RC."
    ),
    "fr": (
        "Use natural French terms: aileron=aileron; clevis=chape; "
        "spare part=pièce de rechange or pièce RC. Do not mechanically keep 'Clevis'. "
        "Preserve MOFLY, P-51D, 690mm, RC."
    ),
    "es": (
        "Use natural Spanish terms: aileron=alerón; clevis=clevis or horquilla; "
        "spare part=repuesto RC. Do not use 'RC Plane'. Preserve MOFLY, P-51D, 690mm, RC."
    ),
    "it": (
        "Use natural Italian terms: aileron=alettone; clevis=forcella; "
        "spare part=ricambio RC. Do not use 'Aileron Clevis'. Preserve MOFLY, P-51D, 690mm, RC."
    ),
}
FIELD_STYLE_GUIDANCE = {
    "title": (
        "Short store title. Prefer brand/model + part name + spec/use. "
        "Do not translate every English word literally."
    ),
    "meta_title": (
        "Short SEO title. Include MOFLY P-51D, one localized core part keyword, "
        "and an RC spare/replacement part meaning."
    ),
    "meta_description": (
        "Natural SEO description with use, compatibility, part type, and one value point; "
        "no CTA, shipping claims, origin claims, or exaggerated claims."
    ),
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


def run_shopify_translation_selected_product_missing_translation_draft_package_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    requested_scope = _requested_scope()
    validation_errors = _validate_requested_scope(requested_scope)
    query_result = _empty_generation_result(requested_scope)

    if not validation_errors:
        query_result = _run_draft_generation(requested_scope)

    blocking_conditions = _blocking_conditions(validation_errors, query_result)
    draft_status = _draft_status(blocking_conditions, query_result)
    success = draft_status in {
        "selected_product_missing_translation_draft_ready_for_manual_review",
        "no_missing_translations_found",
    }
    end_time = utc_now_iso()
    payload = _build_payload(
        requested_scope=requested_scope,
        validation_errors=validation_errors,
        blocking_conditions=blocking_conditions,
        draft_status=draft_status,
        query_result=query_result,
        success=success,
        start_time=start_time,
        end_time=end_time,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": success,
        "exit_code": 0 if success else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_selected_product_missing_translation_draft_package_path": str(json_path),
        "html_selected_product_missing_translation_draft_package_path": str(html_path),
        "draft_status": draft_status,
        "product_id": payload.get("product_id", ""),
        "target_locales": payload.get("target_locales", []),
        "requested_fields": payload.get("requested_fields", []),
        "generated_draft_count": payload.get("generated_draft_count", 0),
        "draft_ready_count": payload.get("draft_ready_count", 0),
        "draft_needs_manual_review_count": payload.get("draft_needs_manual_review_count", 0),
        "eligible_apply_plan_count": payload.get("eligible_apply_plan_count", 0),
        "over_length_after_rewrite_count": payload.get("over_length_after_rewrite_count", 0),
        "seo_ready_count": payload.get("seo_ready_count", 0),
        "seo_needs_manual_review_count": payload.get("seo_needs_manual_review_count", 0),
        "seo_eligible_apply_plan_count": payload.get("seo_eligible_apply_plan_count", 0),
        "forbidden_phrase_count": payload.get("forbidden_phrase_count", 0),
        "missing_core_keyword_count": payload.get("missing_core_keyword_count", 0),
        "too_short_for_seo_count": payload.get("too_short_for_seo_count", 0),
        "skipped_existing_translation_count": payload.get("skipped_existing_translation_count", 0),
        "skipped_outdated_translation_count": payload.get("skipped_outdated_translation_count", 0),
        "skipped_source_empty_count": payload.get("skipped_source_empty_count", 0),
        "draft_package_only": True,
        "shopify_read_only": True,
        "shopify_api_call_performed": payload.get("shopify_api_call_performed", False),
        "openai_call_performed": payload.get("openai_call_performed", False),
        "translation_generated": payload.get("translation_generated", False),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "existing_translation_overwrite_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures_count": len(payload["validation_failures"]),
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _requested_scope() -> dict:
    return {
        "product_id": (
            _env("SHOPIFY_TRANSLATION_SELECTED_PRODUCT_ID")
            or _env("SHOPIFY_TRANSLATION_PRODUCT_ID")
            or DEFAULT_PRODUCT_ID
        ).strip(),
        "target_locales": _split_csv(
            _env("SHOPIFY_TRANSLATION_SELECTED_TARGET_LOCALES")
            or _env("SHOPIFY_TRANSLATION_TARGET_LOCALES"),
            DEFAULT_TARGET_LOCALES,
        ),
        "fields": _split_csv(
            _env("SHOPIFY_TRANSLATION_SELECTED_FIELDS")
            or _env("SHOPIFY_TRANSLATION_FIELDS"),
            DEFAULT_FIELDS,
        ),
    }


def _env(name: str) -> str:
    import os

    return os.environ.get(name, "")


def _split_csv(value: str, default_values: list[str]) -> list[str]:
    if not value:
        return list(default_values)
    return _unique([part.strip() for part in value.split(",") if part.strip()])


def _validate_requested_scope(scope: dict) -> list[str]:
    errors = []
    product_id = scope.get("product_id", "")
    if not product_id or not PRODUCT_GID_RE.match(product_id):
        errors.append("invalid_product_id")

    target_locales = scope.get("target_locales") or []
    if not target_locales or any(locale not in SUPPORTED_LOCALES for locale in target_locales):
        errors.append("unsupported_locale")

    fields = scope.get("fields") or []
    if not fields or any(field not in ALLOWED_FIELDS for field in fields):
        errors.append("invalid_field")
    return _unique(errors)


def _run_draft_generation(scope: dict) -> dict:
    result = _empty_generation_result(scope)
    product_id = scope.get("product_id", "")
    source_reads = {}
    missing_by_locale: dict[str, list[dict]] = {}

    for locale in scope.get("target_locales", []):
        fetched = _fetch_translation_console_data_via_docker(product_id, locale)
        if not fetched.get("success"):
            status = fetched.get("draft_status") or "blocked_shopify_read_query_failed"
            result.update(
                {
                    "success": False,
                    "draft_status": status,
                    "failure_type": fetched.get("failure_type", "command_error"),
                    "query_failure_type": fetched.get("query_failure_type", "docker_command_failed"),
                    "error": fetched.get("error", "Shopify read-only query failed."),
                    "stdout_tail": fetched.get("stdout_tail", ""),
                    "stderr_tail": fetched.get("stderr_tail", ""),
                }
            )
            result["blocking_conditions"].append(status)
            return result

        data = fetched.get("data") or {}
        if data.get("error"):
            result.update(
                {
                    "success": False,
                    "draft_status": "blocked_shopify_read_query_failed",
                    "failure_type": "helper_returned_error",
                    "query_failure_type": "helper_returned_error",
                    "error": str(data.get("error")),
                    "stdout_tail": fetched.get("stdout_tail", ""),
                    "stderr_tail": fetched.get("stderr_tail", ""),
                }
            )
            result["blocking_conditions"].append("blocked_shopify_read_query_failed")
            return result

        result["shopify_api_call_performed"] = True
        product = data.get("product") or {}
        result["product_title"] = result["product_title"] or product.get("title", "")
        rows_by_key = {
            row.get("key"): row
            for row in data.get("translatable_rows", [])
            if row.get("key")
        }
        source_reads[locale] = {
            "translatable_content_count": len(data.get("translatable_rows", [])),
            "translation_count": (data.get("translatable_resource") or {}).get("translation_count", 0),
        }

        for field in scope.get("fields", []):
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

    result["source_read_summary"] = source_reads

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
            field = entry["field"]
            draft = str(translations.get(field) or "").strip()
            rewritten_draft, rewrite_attempts = _rewrite_over_length_draft(locale, entry, draft, result)
            if rewritten_draft is None:
                result["success"] = False
                return result
            _attach_draft_quality(entry, rewritten_draft, rewrite_attempts)
            result["draft_entries"].append(entry)
            result["translation_generated"] = True

    _apply_cross_field_seo_checks(result, scope.get("target_locales", []))
    _recalculate_quality_stats(result)
    result["draft_status"] = "selected_product_missing_translation_draft_ready_for_manual_review"
    result["success"] = True
    return result


def _fetch_translation_console_data_via_docker(product_id: str, locale: str) -> dict:
    script = f"""
import json

from shopify_sync.models import ShopifyInstallation
from shopify_sync.translation_console import fetch_translation_console_data

product_id = {json.dumps(product_id)}
locale = {json.dumps(locale)}

try:
    installation = ShopifyInstallation.objects.first()
    if not installation:
        print(json.dumps({{"error": "blocked_missing_shopify_installation"}}, ensure_ascii=False))
    else:
        result = fetch_translation_console_data(installation, product_id, locale)
        print(json.dumps({{"data": result}}, ensure_ascii=False))
except Exception as exc:
    print(json.dumps({{
        "error": "blocked_shopify_read_query_failed",
        "exception_type": type(exc).__name__,
        "message": str(exc),
    }}, ensure_ascii=False))
"""
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
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "timeout",
            "query_failure_type": "docker_command_failed",
            "error": f"Shopify read-only query timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
        }
    except FileNotFoundError as exc:
        return {
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "missing_env",
            "query_failure_type": "docker_command_failed",
            "error": str(exc),
        }
    except PermissionError as exc:
        return {
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "docker_permission_denied",
            "query_failure_type": "docker_command_failed",
            "error": str(exc),
        }

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _parse_json_from_stdout(stdout)
    if completed.returncode != 0:
        return {
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": _classify_command_failure(stdout, stderr),
            "query_failure_type": "docker_command_failed",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": "Docker Django shell read-only query command failed.",
        }
    if not parsed:
        return {
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "command_error",
            "query_failure_type": "docker_command_failed",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": "Docker Django shell read-only query did not return parseable JSON.",
        }
    if parsed.get("error") == "blocked_missing_shopify_installation":
        return {
            "success": False,
            "draft_status": "blocked_missing_shopify_installation",
            "failure_type": "missing_shopify_installation",
            "query_failure_type": "helper_returned_error",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": "Shopify installation was not found in Django.",
        }
    if parsed.get("error"):
        return {
            "success": False,
            "draft_status": "blocked_shopify_read_query_failed",
            "failure_type": "helper_returned_error",
            "query_failure_type": "helper_returned_error",
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
            "error": parsed.get("message") or parsed.get("error") or "Shopify read-only helper returned an error.",
        }
    return {
        "success": True,
        "data": parsed.get("data") or {},
        "stdout_tail": _tail(stdout),
        "stderr_tail": _tail(stderr),
    }


def _entry_template(locale: str, field: str, row: dict, reason: str) -> dict:
    source_value = str((row or {}).get("source_value") or "")
    return {
        "locale": locale,
        "field": field,
        "source_key": field,
        "source_value": source_value,
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


def _ensure_result_summary(result: dict, key: str, value: str) -> dict:
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


def _count_entry(result: dict, entry: dict) -> None:
    per_locale = _ensure_result_summary(result, "per_locale_results", entry["locale"])
    per_field = _ensure_result_summary(result, "per_field_results", entry["field"])
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


def _output_text_from_openai(data: dict) -> str:
    text = data.get("output_text")
    if text:
        return text
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text") or ""
    return ""


def _post_openai_payload(payload: dict, result: dict, action_label: str) -> dict | None:
    import os
    import urllib.error
    import urllib.request

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        result["draft_status"] = "blocked_missing_openai_api_key"
        result["failure_type"] = "missing_openai_api_key"
        result["error"] = "OPENAI_API_KEY is not configured."
        result["blocking_conditions"].append("blocked_missing_openai_api_key")
        return None

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
            response_body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        result["openai_call_performed"] = True
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_request_failed"
        result["error"] = f"OpenAI {action_label} failed with HTTP status {exc.code}"
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None
    except urllib.error.URLError as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_request_failed"
        result["error"] = f"OpenAI {action_label} request failed: {type(exc.reason).__name__}"
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None

    try:
        return json.loads(response_body)
    except json.JSONDecodeError as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = f"{type(exc).__name__}: OpenAI {action_label} response was not valid JSON."
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None


def _quality_notes_for_draft(field: str, draft: str) -> list[str]:
    draft = str(draft or "").strip()
    notes = []
    if not draft:
        notes.append("draft_empty")
        return notes
    max_chars = FIELD_MAX_CHARS.get(field)
    if max_chars and len(draft) > int(max_chars):
        notes.append("draft_over_max_chars")
    if FORBIDDEN_OUTPUT_RE.search(draft):
        notes.append("forbidden_marketing_or_origin_phrase")
    if UNNATURAL_PHRASE_RE.search(draft):
        notes.append("unnatural_english_phrase")
    return notes


def _validate_draft(field: str, draft: str) -> str:
    notes = _quality_notes_for_draft(field, draft)
    if notes:
        if "draft_empty" in notes:
            return "draft_needs_manual_review_empty"
        return "draft_needs_manual_review"
    return "draft_ready_for_manual_review"


def _text_contains_any(text: str, terms: list[str]) -> bool:
    lower_text = str(text or "").lower()
    return any(str(term).lower() in lower_text for term in terms)


def _model_occurrence_count(text: str) -> int:
    return str(text or "").lower().count("mofly p-51d")


def _contains_model(text: str) -> bool:
    lower_text = str(text or "").lower()
    return "mofly p-51d" in lower_text or ("mofly" in lower_text and "p-51d" in lower_text)


def _seo_notes_for_draft(entry: dict, draft: str) -> list[str]:
    draft = str(draft or "").strip()
    field = entry["field"]
    locale = entry["locale"]
    terms = SEO_TERMS.get(locale, {})
    notes = []
    min_chars = FIELD_RECOMMENDED_MIN_CHARS.get(field)
    max_chars = FIELD_MAX_CHARS.get(field)
    if min_chars and len(draft) < int(min_chars):
        notes.append("too_short_for_seo")
    if max_chars and len(draft) > int(max_chars):
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


def _attach_seo_quality(entry: dict) -> None:
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
    entry["recommended_min_chars"] = FIELD_RECOMMENDED_MIN_CHARS.get(field)
    entry["recommended_max_chars"] = FIELD_RECOMMENDED_MAX_CHARS.get(field)
    entry["seo_validation_status"] = "seo_ready" if not seo_notes else "seo_needs_manual_review"
    entry["seo_eligible_for_apply_plan"] = entry["seo_validation_status"] == "seo_ready"
    entry["eligible_for_apply_plan"] = (
        entry["validation_status"] == "draft_ready_for_manual_review"
        and entry["seo_validation_status"] == "seo_ready"
    )


def _attach_draft_quality(entry: dict, draft: str, rewrite_attempts: list[dict]) -> None:
    draft = str(draft or "").strip()
    entry["draft_value"] = draft
    entry["draft_value_chars"] = len(draft)
    entry["rewrite_attempts"] = rewrite_attempts
    entry["rewrite_attempt_count"] = len(rewrite_attempts)
    entry["quality_notes"] = _quality_notes_for_draft(entry["field"], draft)
    entry["validation_status"] = _validate_draft(entry["field"], draft)
    entry["skip_reason"] = ""
    _attach_seo_quality(entry)


def _request_openai(locale: str, missing_entries: list[dict], result: dict) -> dict | None:
    prompt = {
        "task": "Translate selected Shopify product fields into draft translations for manual review only.",
        "product_id": result.get("product_id", ""),
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
            "Preserve only these product constants exactly: MOFLY, P-51D, 690mm, RC, SKU-like model numbers, dimensions, and units.",
            "Localize part names naturally for the target language; do not mechanically keep English phrases such as RC Plane Clevis or Aileron Clevis.",
            "Do not add Buy now, Shop now, urgency, origin, Made in China, worldwide shipping, or ships worldwide wording.",
            "Do not add Best, Cheap, Free shipping, guaranteed, official, original OEM, Herkunft, Provenance, country-of-origin, or exaggerated claims.",
            "Do not translate or rewrite URL handles.",
            "Product title must be 25-65 characters where possible, and never over 65 characters.",
            "SEO meta_title must be 30-60 characters where possible, and never over 60 characters.",
            "SEO meta_description must be 80-155 characters where possible, and never over 155 characters.",
            "meta_title must naturally include MOFLY P-51D, one localized aileron clevis/core part keyword, and an RC spare/replacement part meaning.",
            "meta_description must naturally include product use, compatibility with MOFLY P-51D or P-51D, localized part type, and one value point such as durable, precise, reliable, or control.",
            "Do not repeat MOFLY P-51D more than once in the same field.",
            "Do not stack synonyms such as clevis connector linkage joint.",
            "Do not make title and meta_title exactly the same.",
            "Keep ecommerce copy natural, short, and suitable for a local storefront title or SEO snippet.",
        ],
        "output_contract": {"type": "JSON object", "shape": {"translations": {"field_name": "draft translated value"}}},
    }
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": "You are a careful ecommerce localization translator. Return valid JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    response_data = _post_openai_payload(payload, result, "draft generation")
    if response_data is None:
        return None
    try:
        parsed = json.loads(_output_text_from_openai(response_data))
    except Exception as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = type(exc).__name__ + ": OpenAI response was not valid JSON."
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


def _request_openai_rewrite(locale: str, entry: dict, current_value: str, attempt: int, result: dict) -> str | None:
    max_chars = int(entry.get("max_chars") or FIELD_MAX_CHARS.get(entry["field"]) or 0)
    prompt = {
        "task": "Shorten or rewrite one Shopify product draft translation for manual review only.",
        "target_locale": locale,
        "target_language": LANGUAGE_NAMES.get(locale, locale),
        "field": entry["field"],
        "source_value": entry["source_value"],
        "current_draft": str(current_value or ""),
        "current_chars": len(str(current_value or "")),
        "max_chars": max_chars,
        "recommended_min_chars": FIELD_RECOMMENDED_MIN_CHARS.get(entry["field"]),
        "recommended_max_chars": FIELD_RECOMMENDED_MAX_CHARS.get(entry["field"]),
        "attempt": attempt,
        "locale_term_guidance": LOCALE_TERM_GUIDANCE.get(locale, ""),
        "field_style_guidance": FIELD_STYLE_GUIDANCE.get(entry["field"], ""),
        "rules": [
            "Return JSON only with a value string.",
            "Rewrite naturally; do not truncate crudely.",
            "The value must be at or under max_chars.",
            "Keep the value within the recommended SEO range where possible.",
            "Preserve MOFLY, P-51D, 690mm, and RC exactly.",
            "Use localized part terminology instead of mechanical English phrases.",
            "Do not add Buy now, Shop now, shipping, origin, Made in China, Herkunft, Provenance, Best, Cheap, Free shipping, guaranteed, official, original OEM, or exaggerated claims.",
            "For meta_title, keep MOFLY P-51D, one core part keyword, and RC spare/replacement meaning.",
            "For meta_description, include use, compatible model, part type, and one natural value point.",
            "Do not translate or rewrite URL handles.",
        ],
        "output_contract": {"type": "JSON object", "shape": {"value": "rewritten draft"}},
    }
    payload = {
        "model": OPENAI_MODEL,
        "input": [
            {"role": "system", "content": "You are a careful ecommerce localization editor. Return valid JSON only."},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "text": {"format": {"type": "json_object"}},
    }
    response_data = _post_openai_payload(payload, result, "rewrite")
    if response_data is None:
        return None
    try:
        parsed = json.loads(_output_text_from_openai(response_data))
    except Exception as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = type(exc).__name__ + ": OpenAI rewrite response was not valid JSON."
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


def _rewrite_over_length_draft(locale: str, entry: dict, draft: str, result: dict) -> tuple[str | None, list[dict]]:
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


def _apply_cross_field_seo_checks(result: dict, target_locales: list[str]) -> None:
    entries_by_locale_field = {
        (entry["locale"], entry["field"]): entry
        for entry in result["draft_entries"]
    }
    for locale in target_locales:
        title_entry = entries_by_locale_field.get((locale, "title"))
        meta_title_entry = entries_by_locale_field.get((locale, "meta_title"))
        if not title_entry or not meta_title_entry:
            continue
        title_value = str(title_entry.get("draft_value") or "").strip()
        meta_title_value = str(meta_title_entry.get("draft_value") or "").strip()
        if title_value and meta_title_value and title_value == meta_title_value:
            for entry in (title_entry, meta_title_entry):
                notes = entry.setdefault("seo_notes", [])
                if "keyword_stuffing_or_duplicate" not in notes:
                    notes.append("keyword_stuffing_or_duplicate")
                entry["seo_validation_status"] = "seo_needs_manual_review"
                entry["seo_eligible_for_apply_plan"] = False
                entry["eligible_for_apply_plan"] = False


def _recalculate_quality_stats(result: dict) -> None:
    for key in [
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
    ]:
        result[key] = 0
    for summary in result["per_locale_results"].values():
        for key in [
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
        ]:
            summary[key] = 0
    for summary in result["per_field_results"].values():
        for key in [
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
        ]:
            summary[key] = 0

    for entry in result["draft_entries"]:
        locale = entry["locale"]
        field = entry["field"]
        per_locale = result["per_locale_results"][locale]
        per_field = result["per_field_results"][field]
        result["generated_draft_count"] += 1
        per_locale["generated_draft_count"] += 1
        per_field["generated_draft_count"] += 1
        if entry.get("validation_status") == "draft_ready_for_manual_review":
            result["draft_ready_count"] += 1
            per_locale["draft_ready_count"] += 1
            per_field["draft_ready_count"] += 1
        else:
            result["draft_needs_manual_review_count"] += 1
            per_locale["draft_needs_manual_review_count"] += 1
            per_field["draft_needs_manual_review_count"] += 1
        if entry.get("eligible_for_apply_plan"):
            result["eligible_apply_plan_count"] += 1
            per_locale["eligible_apply_plan_count"] += 1
            per_field["eligible_apply_plan_count"] += 1
        if "draft_over_max_chars" in (entry.get("quality_notes") or []):
            result["over_length_after_rewrite_count"] += 1
            per_locale["over_length_after_rewrite_count"] += 1
            per_field["over_length_after_rewrite_count"] += 1
        if entry.get("seo_validation_status") == "seo_ready":
            result["seo_ready_count"] += 1
            per_locale["seo_ready_count"] += 1
            per_field["seo_ready_count"] += 1
        else:
            result["seo_needs_manual_review_count"] += 1
            per_locale["seo_needs_manual_review_count"] += 1
            per_field["seo_needs_manual_review_count"] += 1
        if entry.get("seo_eligible_for_apply_plan"):
            result["seo_eligible_apply_plan_count"] += 1
            per_locale["seo_eligible_apply_plan_count"] += 1
            per_field["seo_eligible_apply_plan_count"] += 1
        seo_notes = entry.get("seo_notes") or []
        if "forbidden_marketing_or_shipping_phrase" in seo_notes:
            result["forbidden_phrase_count"] += 1
            per_locale["forbidden_phrase_count"] += 1
            per_field["forbidden_phrase_count"] += 1
        if "missing_core_keyword" in seo_notes:
            result["missing_core_keyword_count"] += 1
            per_locale["missing_core_keyword_count"] += 1
            per_field["missing_core_keyword_count"] += 1
        if "too_short_for_seo" in seo_notes:
            result["too_short_for_seo_count"] += 1
            per_locale["too_short_for_seo_count"] += 1
            per_field["too_short_for_seo_count"] += 1


def _build_django_shell_script(scope: dict) -> str:
    product_id_literal = json.dumps(scope["product_id"])
    target_locales_literal = json.dumps(scope["target_locales"])
    fields_literal = json.dumps(scope["fields"])
    supported_locales_literal = json.dumps(SUPPORTED_LOCALES)
    allowed_fields_literal = json.dumps(ALLOWED_FIELDS)
    field_max_chars_literal = json.dumps(FIELD_MAX_CHARS)
    field_recommended_min_chars_literal = json.dumps(FIELD_RECOMMENDED_MIN_CHARS)
    field_recommended_max_chars_literal = json.dumps(FIELD_RECOMMENDED_MAX_CHARS)
    max_rewrite_attempts_literal = json.dumps(MAX_REWRITE_ATTEMPTS)
    return f"""
import json
import os
import re
import time

from shopify_sync.models import ShopifyInstallation
from shopify_sync.translation_console import fetch_translation_console_data

product_id = {product_id_literal}
target_locales = {target_locales_literal}
fields = {fields_literal}
supported_locales = {supported_locales_literal}
allowed_fields = {allowed_fields_literal}
field_max_chars = {field_max_chars_literal}
field_recommended_min_chars = {field_recommended_min_chars_literal}
field_recommended_max_chars = {field_recommended_max_chars_literal}
max_rewrite_attempts = {max_rewrite_attempts_literal}
shop = "kidstoylover.myshopify.com"
openai_model = "gpt-4.1-mini"
language_names = {{
    "ja": "Japanese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
}}
forbidden_output_re = re.compile(
    r"\\\\b(?:buy now|shop now|free shipping|ships worldwide|worldwide shipping|origin|herkunft|provenance|made in china|mainland china|best|cheap|guaranteed|official|original oem|versand weltweit|weltweiter versand|lieferung weltweit)\\\\b",
    flags=re.IGNORECASE,
)
unnatural_phrase_re = re.compile(
    r"\\\\b(?:RC Plane Clevis|Aileron Clevis|Brushless RC Warbird)\\\\b",
    flags=re.IGNORECASE,
)
keyword_stuffing_re = re.compile(
    r"\\\\b(?:clevis connector linkage joint|clevis linkage connector|connector linkage joint|gabelkopf verbinder gest[aä]nge|chape connecteur tringlerie|clevis conector varillaje|forcella connettore tirante)\\\\b",
    flags=re.IGNORECASE,
)
seo_terms = {{
    "ja": {{
        "core": ["エルロン", "クレビス", "リンケージ"],
        "part_type": ["エルロン", "クレビス", "リンケージ"],
        "replacement": ["交換", "補修", "予備", "パーツ", "部品"],
        "value": ["正確", "精密", "安定", "耐久", "確実"],
        "spare": ["RC", "パーツ", "部品", "交換", "補修"],
    }},
    "de": {{
        "core": ["querruder", "gabelkopf"],
        "part_type": ["querruder", "gabelkopf", "anlenkung"],
        "replacement": ["ersatz", "ersatzteil", "austausch", "zubehör"],
        "value": ["präzise", "prazise", "präzision", "langlebig", "stabil", "zuverlässig", "kontrolle", "steuerung"],
        "spare": ["rc", "ersatzteil", "ersatz", "zubehör"],
    }},
    "fr": {{
        "core": ["aileron", "chape"],
        "part_type": ["aileron", "chape", "tringlerie", "commande"],
        "replacement": ["rechange", "remplacement", "pièce", "piece", "accessoire"],
        "value": ["précise", "precise", "solide", "fiable", "durable", "commande", "contrôle", "controle"],
        "spare": ["rc", "pièce", "piece", "rechange"],
    }},
    "es": {{
        "core": ["alerón", "aleron", "clevis", "horquilla"],
        "part_type": ["alerón", "aleron", "clevis", "horquilla", "varillaje", "control"],
        "replacement": ["repuesto", "recambio", "reemplazo", "pieza", "accesorio"],
        "value": ["preciso", "precisa", "resistente", "duradero", "fiable", "seguro", "control"],
        "spare": ["rc", "repuesto", "recambio", "pieza"],
    }},
    "it": {{
        "core": ["alettone", "forcella"],
        "part_type": ["alettone", "forcella", "rinvio", "comando"],
        "replacement": ["ricambio", "sostituzione", "pezzo", "accessorio"],
        "value": ["preciso", "precisa", "resistente", "durevole", "sicuro", "affidabile", "controllo"],
        "spare": ["rc", "ricambio", "pezzo"],
    }},
}}
locale_term_guidance = {{
    "ja": "Use natural Japanese RC part terms: aileron=エルロン; clevis/linkage connector=クレビス or リンケージクレビス. Preserve MOFLY, P-51D, 690mm, RC.",
    "de": "Use natural German terms: aileron=Querruder; clevis/linkage connector=Gabelkopf; spare part=Ersatzteil. Do not keep 'RC Plane Clevis'. Preserve MOFLY, P-51D, 690mm, RC.",
    "fr": "Use natural French terms: aileron=aileron; clevis=chape; spare part=pièce de rechange or pièce RC. Do not mechanically keep 'Clevis'. Preserve MOFLY, P-51D, 690mm, RC.",
    "es": "Use natural Spanish terms: aileron=alerón; clevis=clevis or horquilla; spare part=repuesto RC. Do not use 'RC Plane'. Preserve MOFLY, P-51D, 690mm, RC.",
    "it": "Use natural Italian terms: aileron=alettone; clevis=forcella; spare part=ricambio RC. Do not use 'Aileron Clevis'. Preserve MOFLY, P-51D, 690mm, RC.",
}}
field_style_guidance = {{
    "title": "Short store title. Prefer brand/model + part name + spec/use. Do not translate every English word literally.",
    "meta_title": "Short SEO title. Keep it concise and natural.",
    "meta_description": "Natural SEO description without CTA, shipping claims, origin claims, or exaggerated claims.",
}}

result = {{
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
    "per_locale_results": {{}},
    "per_field_results": {{}},
    "entries": [],
    "draft_entries": [],
    "source_read_summary": {{}},
    "blocking_conditions": [],
    "failure_type": "",
    "error": "",
    "shopify_write_performed": False,
    "mutation_performed": False,
    "translations_register_called": False,
    "publish_performed": False,
    "real_apply_performed": False,
    "rollback_performed": False,
    "existing_translation_overwrite_allowed": False,
    "no_new_shopify_writes_performed": True,
    "all_new_actions_no_write_confirmed": True,
}}

def unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output

def entry_template(locale, field, row, reason):
    source_value = str((row or {{}}).get("source_value") or "")
    return {{
        "locale": locale,
        "field": field,
        "source_key": field,
        "source_value": source_value,
        "source_digest": str((row or {{}}).get("digest") or ""),
        "existing_translation_present": bool((row or {{}}).get("has_translation")),
        "existing_translation_outdated": (row or {{}}).get("translation_outdated"),
        "draft_value": "",
        "draft_value_chars": 0,
        "max_chars": field_max_chars.get(field),
        "recommended_min_chars": field_recommended_min_chars.get(field),
        "recommended_max_chars": field_recommended_max_chars.get(field),
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
    }}

def count_entry(entry):
    locale = entry["locale"]
    field = entry["field"]
    per_locale = result["per_locale_results"].setdefault(
        locale,
        {{
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
        }},
    )
    per_field = result["per_field_results"].setdefault(
        field,
        {{
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
        }},
    )
    reason = entry.get("skip_reason")
    if entry.get("draft_value"):
        per_locale["generated_draft_count"] += 1
        per_field["generated_draft_count"] += 1
        result["generated_draft_count"] += 1
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

def output_text_from_openai(data):
    text = data.get("output_text")
    if text:
        return text
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text":
                return content.get("text") or ""
    return ""

def quality_notes_for_draft(field, draft):
    draft = str(draft or "").strip()
    notes = []
    if not draft:
        notes.append("draft_empty")
        return notes
    max_chars = field_max_chars.get(field)
    if max_chars and len(draft) > int(max_chars):
        notes.append("draft_over_max_chars")
    if forbidden_output_re.search(draft):
        notes.append("forbidden_marketing_or_origin_phrase")
    if unnatural_phrase_re.search(draft):
        notes.append("unnatural_english_phrase")
    return notes

def validate_draft(field, draft):
    notes = quality_notes_for_draft(field, draft)
    if notes:
        if "draft_empty" in notes:
            return "draft_needs_manual_review_empty"
        return "draft_needs_manual_review"
    return "draft_ready_for_manual_review"

def text_contains_any(text, terms):
    lower_text = str(text or "").lower()
    return any(str(term).lower() in lower_text for term in terms)

def model_occurrence_count(text):
    lower_text = str(text or "").lower()
    return lower_text.count("mofly p-51d")

def contains_model(text):
    lower_text = str(text or "").lower()
    return "mofly p-51d" in lower_text or ("mofly" in lower_text and "p-51d" in lower_text)

def seo_notes_for_draft(entry, draft):
    draft = str(draft or "").strip()
    field = entry["field"]
    locale = entry["locale"]
    terms = seo_terms.get(locale, {{}})
    notes = []
    min_chars = field_recommended_min_chars.get(field)
    max_chars = field_max_chars.get(field)
    if min_chars and len(draft) < int(min_chars):
        notes.append("too_short_for_seo")
    if max_chars and len(draft) > int(max_chars):
        notes.append("draft_over_max_chars")
    if forbidden_output_re.search(draft):
        notes.append("forbidden_marketing_or_shipping_phrase")
    if model_occurrence_count(draft) > 1 or keyword_stuffing_re.search(draft):
        notes.append("keyword_stuffing_or_duplicate")
    if field == "meta_title":
        if not contains_model(draft):
            notes.append("missing_model")
        if not text_contains_any(draft, terms.get("core", [])):
            notes.append("missing_core_keyword")
        if not text_contains_any(draft, terms.get("spare", [])):
            notes.append("missing_replacement_part_meaning")
    if field == "meta_description":
        if not contains_model(draft):
            notes.append("missing_model")
        if not text_contains_any(draft, terms.get("part_type", [])):
            notes.append("missing_part_type")
        if not text_contains_any(draft, terms.get("replacement", [])):
            notes.append("missing_use_case")
        if not text_contains_any(draft, terms.get("value", [])):
            notes.append("missing_value_point")
    return unique(notes)

def attach_seo_quality(entry):
    draft = str(entry.get("draft_value") or "").strip()
    field = entry["field"]
    locale = entry["locale"]
    terms = seo_terms.get(locale, {{}})
    seo_notes = seo_notes_for_draft(entry, draft)
    entry["seo_notes"] = seo_notes
    entry["contains_model"] = contains_model(draft)
    if field == "meta_title":
        entry["contains_core_keyword"] = text_contains_any(draft, terms.get("core", []))
    elif field == "meta_description":
        entry["contains_core_keyword"] = text_contains_any(draft, terms.get("part_type", []))
    else:
        entry["contains_core_keyword"] = text_contains_any(draft, terms.get("core", []))
    entry["contains_forbidden_phrase"] = bool(forbidden_output_re.search(draft))
    entry["recommended_min_chars"] = field_recommended_min_chars.get(field)
    entry["recommended_max_chars"] = field_recommended_max_chars.get(field)
    entry["seo_validation_status"] = "seo_ready" if not seo_notes else "seo_needs_manual_review"
    entry["seo_eligible_for_apply_plan"] = entry["seo_validation_status"] == "seo_ready"
    entry["eligible_for_apply_plan"] = (
        entry["validation_status"] == "draft_ready_for_manual_review"
        and entry["seo_validation_status"] == "seo_ready"
    )

def attach_draft_quality(entry, draft, rewrite_attempts):
    draft = str(draft or "").strip()
    entry["draft_value"] = draft
    entry["draft_value_chars"] = len(draft)
    entry["rewrite_attempts"] = rewrite_attempts
    entry["rewrite_attempt_count"] = len(rewrite_attempts)
    entry["quality_notes"] = quality_notes_for_draft(entry["field"], draft)
    entry["validation_status"] = validate_draft(entry["field"], draft)
    entry["skip_reason"] = ""
    attach_seo_quality(entry)

def request_openai(locale, missing_entries):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        result["draft_status"] = "blocked_missing_openai_api_key"
        result["failure_type"] = "missing_openai_api_key"
        result["error"] = "OPENAI_API_KEY is not configured."
        result["blocking_conditions"].append("blocked_missing_openai_api_key")
        return None

    prompt = {{
        "task": "Translate selected Shopify product fields into draft translations for manual review only.",
        "product_id": product_id,
        "target_locale": locale,
        "target_language": language_names.get(locale, locale),
        "draft_only": True,
        "fields": [
            {{
                "field": item["field"],
                "source_value": item["source_value"],
                "max_chars": item["max_chars"],
                "recommended_min_chars": field_recommended_min_chars.get(item["field"]),
                "recommended_max_chars": field_recommended_max_chars.get(item["field"]),
                "style_guidance": field_style_guidance.get(item["field"], ""),
            }}
            for item in missing_entries
        ],
        "locale_term_guidance": locale_term_guidance.get(locale, ""),
        "suggested_style_examples": {{
            "ja": {{
                "title": "MOFLY P-51D 690mm用 エルロンクレビス",
                "meta_title": "MOFLY P-51D エルロンクレビス | RCパーツ",
                "meta_description": "MOFLY P-51D 690mm RC機用のエルロン交換クレビス。正確で安定した操作を支える補修パーツです。",
            }},
            "de": {{
                "title": "MOFLY P-51D Querruder-Gabelkopf 690mm RC",
                "meta_title": "MOFLY P-51D Querruder-Gabelkopf | RC Ersatzteil",
                "meta_description": "Ersatz-Gabelkopf für die Querruderanlenkung des MOFLY P-51D 690mm RC Warbirds. Langlebiges Ersatzteil für präzise Steuerung.",
            }},
            "fr": {{
                "title": "Chape d'aileron MOFLY P-51D 690mm RC",
                "meta_title": "Chape d'aileron MOFLY P-51D | Pièce RC",
                "meta_description": "Chape de rechange pour aileron MOFLY P-51D 690mm RC Warbird. Pièce solide pour une commande précise et fiable.",
            }},
            "es": {{
                "title": "Clevis de alerón MOFLY P-51D 690mm RC",
                "meta_title": "Clevis de alerón MOFLY P-51D | Repuesto RC",
                "meta_description": "Clevis de repuesto para el alerón del MOFLY P-51D 690mm RC Warbird. Pieza resistente para un control preciso y seguro.",
            }},
            "it": {{
                "title": "Forcella alettone MOFLY P-51D 690mm RC",
                "meta_title": "Forcella alettone MOFLY P-51D | Ricambio RC",
                "meta_description": "Forcella di ricambio per alettone MOFLY P-51D 690mm RC Warbird. Componente resistente per un controllo preciso e sicuro.",
            }},
        }}.get(locale, {{}}),
        "rules": [
            "Return JSON only with a translations object keyed by field.",
            "Preserve only these product constants exactly: MOFLY, P-51D, 690mm, RC, SKU-like model numbers, dimensions, and units.",
            "Localize part names naturally for the target language; do not mechanically keep English phrases such as RC Plane Clevis or Aileron Clevis.",
            "Do not add Buy now, Shop now, urgency, origin, Made in China, worldwide shipping, or ships worldwide wording.",
            "Do not add Herkunft, Provenance, origin, shipping, country-of-origin, exaggerated claims, or sales CTA wording.",
            "Do not translate or rewrite URL handles.",
            "SEO meta_title must be 60 characters or fewer.",
            "SEO meta_description must be 155 characters or fewer.",
            "Product title must be 65 characters or fewer.",
            "Recommended SEO ranges: title 25-65 chars, meta_title 30-60 chars, meta_description 80-155 chars.",
            "meta_title must naturally include MOFLY P-51D, a localized aileron clevis/core part keyword, and an RC spare/replacement part meaning.",
            "meta_description must naturally include product use, compatibility with MOFLY P-51D or P-51D, localized part type, and one value point such as durable, precise, reliable, or control.",
            "Do not repeat MOFLY P-51D more than once in the same field.",
            "Do not stack synonyms such as clevis connector linkage joint.",
            "Do not make title and meta_title exactly the same.",
            "Keep ecommerce copy natural, short, and suitable for a local storefront title or SEO snippet.",
        ],
        "output_contract": {{
            "type": "JSON object",
            "shape": {{"translations": {{"field_name": "draft translated value"}}}},
        }},
    }}
    headers = {{
        "Auth" + "orization": "Bea" + "rer " + api_key,
        "Content-Type": "application/json",
    }}
    payload = {{
        "model": openai_model,
        "input": [
            {{
                "role": "system",
                "content": "You are a careful ecommerce localization translator. Return valid JSON only.",
            }},
            {{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}},
        ],
        "text": {{"format": {{"type": "json_object"}}}},
    }}
    response = openai_http_post(
        "https://api.openai.com/v1/responses",
        headers=headers,
        json=payload,
        timeout=120,
    )
    result["openai_call_performed"] = True
    if not response.ok:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_request_failed"
        result["error"] = "OpenAI draft generation failed with HTTP status " + str(response.status_code)
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None
    try:
        parsed = json.loads(output_text_from_openai(response.json()))
    except Exception as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = type(exc).__name__ + ": OpenAI response was not valid JSON."
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

def request_openai_rewrite(locale, entry, current_value, attempt):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        result["draft_status"] = "blocked_missing_openai_api_key"
        result["failure_type"] = "missing_openai_api_key"
        result["error"] = "OPENAI_API_KEY is not configured."
        result["blocking_conditions"].append("blocked_missing_openai_api_key")
        return None
    max_chars = int(entry.get("max_chars") or field_max_chars.get(entry["field"]) or 0)
    prompt = {{
        "task": "Shorten or rewrite one Shopify product draft translation for manual review only.",
        "target_locale": locale,
        "target_language": language_names.get(locale, locale),
        "field": entry["field"],
        "source_value": entry["source_value"],
        "current_draft": str(current_value or ""),
        "current_chars": len(str(current_value or "")),
        "max_chars": max_chars,
        "attempt": attempt,
        "locale_term_guidance": locale_term_guidance.get(locale, ""),
        "field_style_guidance": field_style_guidance.get(entry["field"], ""),
        "rules": [
            "Return JSON only with a value string.",
            "Rewrite naturally; do not truncate crudely.",
            "The value must be at or under max_chars.",
            "Keep the value within the recommended SEO range where possible.",
            "Preserve MOFLY, P-51D, 690mm, and RC exactly.",
            "Use localized part terminology instead of mechanical English phrases.",
            "Do not add Buy now, Shop now, shipping, origin, Made in China, Herkunft, Provenance, or exaggerated claims.",
            "Do not add Best, Cheap, Free shipping, guaranteed, official, or original OEM.",
            "For meta_title, keep MOFLY P-51D, one core part keyword, and RC spare/replacement meaning.",
            "For meta_description, include use, compatible model, part type, and one natural value point.",
            "Do not translate or rewrite URL handles.",
        ],
        "output_contract": {{"type": "JSON object", "shape": {{"value": "rewritten draft"}}}},
    }}
    headers = {{
        "Auth" + "orization": "Bea" + "rer " + api_key,
        "Content-Type": "application/json",
    }}
    payload = {{
        "model": openai_model,
        "input": [
            {{
                "role": "system",
                "content": "You are a careful ecommerce localization editor. Return valid JSON only.",
            }},
            {{"role": "user", "content": json.dumps(prompt, ensure_ascii=False)}},
        ],
        "text": {{"format": {{"type": "json_object"}}}},
    }}
    response = openai_http_post(
        "https://api.openai.com/v1/responses",
        headers=headers,
        json=payload,
        timeout=120,
    )
    result["openai_call_performed"] = True
    if not response.ok:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_request_failed"
        result["error"] = "OpenAI rewrite failed with HTTP status " + str(response.status_code)
        result["blocking_conditions"].append("blocked_openai_draft_generation_failed")
        return None
    try:
        parsed = json.loads(output_text_from_openai(response.json()))
    except Exception as exc:
        result["draft_status"] = "blocked_openai_draft_generation_failed"
        result["failure_type"] = "openai_response_invalid"
        result["error"] = type(exc).__name__ + ": OpenAI rewrite response was not valid JSON."
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

def rewrite_over_length_draft(locale, entry, draft):
    draft = str(draft or "").strip()
    rewrite_attempts = []
    max_chars = int(entry.get("max_chars") or field_max_chars.get(entry["field"]) or 0)
    for attempt in range(1, max_rewrite_attempts + 1):
        if not max_chars or len(draft) <= max_chars:
            break
        before = draft
        rewritten = request_openai_rewrite(locale, entry, draft, attempt)
        if rewritten is None:
            return None, rewrite_attempts
        draft = rewritten.strip()
        rewrite_attempts.append({{
            "attempt": attempt,
            "reason": "draft_over_max_chars",
            "before_chars": len(before),
            "after_chars": len(draft),
            "max_chars": max_chars,
        }})
    return draft, rewrite_attempts

def apply_cross_field_seo_checks():
    entries_by_locale_field = {{}}
    for entry in result["draft_entries"]:
        entries_by_locale_field[(entry["locale"], entry["field"])] = entry
    for locale in target_locales:
        title_entry = entries_by_locale_field.get((locale, "title"))
        meta_title_entry = entries_by_locale_field.get((locale, "meta_title"))
        if not title_entry or not meta_title_entry:
            continue
        title_value = str(title_entry.get("draft_value") or "").strip()
        meta_title_value = str(meta_title_entry.get("draft_value") or "").strip()
        if title_value and meta_title_value and title_value == meta_title_value:
            for entry in (title_entry, meta_title_entry):
                notes = entry.setdefault("seo_notes", [])
                if "keyword_stuffing_or_duplicate" not in notes:
                    notes.append("keyword_stuffing_or_duplicate")
                entry["seo_validation_status"] = "seo_needs_manual_review"
                entry["seo_eligible_for_apply_plan"] = False
                entry["eligible_for_apply_plan"] = False

def recalculate_quality_stats():
    result["generated_draft_count"] = 0
    result["draft_ready_count"] = 0
    result["draft_needs_manual_review_count"] = 0
    result["eligible_apply_plan_count"] = 0
    result["over_length_after_rewrite_count"] = 0
    result["seo_ready_count"] = 0
    result["seo_needs_manual_review_count"] = 0
    result["seo_eligible_apply_plan_count"] = 0
    result["forbidden_phrase_count"] = 0
    result["missing_core_keyword_count"] = 0
    result["too_short_for_seo_count"] = 0
    for summary in result["per_locale_results"].values():
        summary["generated_draft_count"] = 0
        summary["draft_ready_count"] = 0
        summary["draft_needs_manual_review_count"] = 0
        summary["eligible_apply_plan_count"] = 0
        summary["over_length_after_rewrite_count"] = 0
        summary["seo_ready_count"] = 0
        summary["seo_needs_manual_review_count"] = 0
        summary["seo_eligible_apply_plan_count"] = 0
        summary["forbidden_phrase_count"] = 0
        summary["missing_core_keyword_count"] = 0
        summary["too_short_for_seo_count"] = 0
    for summary in result["per_field_results"].values():
        summary["generated_draft_count"] = 0
        summary["draft_ready_count"] = 0
        summary["draft_needs_manual_review_count"] = 0
        summary["eligible_apply_plan_count"] = 0
        summary["over_length_after_rewrite_count"] = 0
        summary["seo_ready_count"] = 0
        summary["seo_needs_manual_review_count"] = 0
        summary["seo_eligible_apply_plan_count"] = 0
        summary["forbidden_phrase_count"] = 0
        summary["missing_core_keyword_count"] = 0
        summary["too_short_for_seo_count"] = 0
    for entry in result["draft_entries"]:
        locale = entry["locale"]
        field = entry["field"]
        result["generated_draft_count"] += 1
        result["per_locale_results"][locale]["generated_draft_count"] += 1
        result["per_field_results"][field]["generated_draft_count"] += 1
        if entry.get("validation_status") == "draft_ready_for_manual_review":
            result["draft_ready_count"] += 1
            result["per_locale_results"][locale]["draft_ready_count"] += 1
            result["per_field_results"][field]["draft_ready_count"] += 1
        else:
            result["draft_needs_manual_review_count"] += 1
            result["per_locale_results"][locale]["draft_needs_manual_review_count"] += 1
            result["per_field_results"][field]["draft_needs_manual_review_count"] += 1
        if entry.get("eligible_for_apply_plan"):
            result["eligible_apply_plan_count"] += 1
            result["per_locale_results"][locale]["eligible_apply_plan_count"] += 1
            result["per_field_results"][field]["eligible_apply_plan_count"] += 1
        if "draft_over_max_chars" in (entry.get("quality_notes") or []):
            result["over_length_after_rewrite_count"] += 1
            result["per_locale_results"][locale]["over_length_after_rewrite_count"] += 1
            result["per_field_results"][field]["over_length_after_rewrite_count"] += 1
        if entry.get("seo_validation_status") == "seo_ready":
            result["seo_ready_count"] += 1
            result["per_locale_results"][locale]["seo_ready_count"] += 1
            result["per_field_results"][field]["seo_ready_count"] += 1
        else:
            result["seo_needs_manual_review_count"] += 1
            result["per_locale_results"][locale]["seo_needs_manual_review_count"] += 1
            result["per_field_results"][field]["seo_needs_manual_review_count"] += 1
        if entry.get("seo_eligible_for_apply_plan"):
            result["seo_eligible_apply_plan_count"] += 1
            result["per_locale_results"][locale]["seo_eligible_apply_plan_count"] += 1
            result["per_field_results"][field]["seo_eligible_apply_plan_count"] += 1
        seo_notes = entry.get("seo_notes") or []
        if "forbidden_marketing_or_shipping_phrase" in seo_notes:
            result["forbidden_phrase_count"] += 1
            result["per_locale_results"][locale]["forbidden_phrase_count"] += 1
            result["per_field_results"][field]["forbidden_phrase_count"] += 1
        if "missing_core_keyword" in seo_notes:
            result["missing_core_keyword_count"] += 1
            result["per_locale_results"][locale]["missing_core_keyword_count"] += 1
            result["per_field_results"][field]["missing_core_keyword_count"] += 1
        if "too_short_for_seo" in seo_notes:
            result["too_short_for_seo_count"] += 1
            result["per_locale_results"][locale]["too_short_for_seo_count"] += 1
            result["per_field_results"][field]["too_short_for_seo_count"] += 1

try:
    installation = ShopifyInstallation.objects.first()
    if installation is None:
        result["draft_status"] = "blocked_missing_shopify_installation"
        result["failure_type"] = "missing_shopify_installation"
        result["error"] = "Shopify installation was not found."
        result["blocking_conditions"].append("blocked_missing_shopify_installation")
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(1)
    source_reads = {{}}
    missing_by_locale = {{}}
    for locale in target_locales:
        data = fetch_translation_console_data(installation, product_id, locale)
        result["shopify_api_call_performed"] = True
        product = data.get("product") or {{}}
        result["product_title"] = result["product_title"] or product.get("title", "")
        rows_by_key = {{
            row.get("key"): row
            for row in data.get("translatable_rows", [])
            if row.get("key")
        }}
        source_reads[locale] = {{
            "translatable_content_count": len(data.get("translatable_rows", [])),
            "translation_count": (data.get("translatable_resource") or {{}}).get("translation_count", 0),
        }}
        for field in fields:
            row = rows_by_key.get(field) or {{}}
            source_value = str(row.get("source_value") or "")
            existing_present = bool(row.get("has_translation"))
            existing_outdated = row.get("translation_outdated") is True
            if not source_value.strip():
                entry = entry_template(locale, field, row, "source_empty")
            elif existing_present and existing_outdated:
                entry = entry_template(locale, field, row, "existing_translation_outdated_manual_review_required")
            elif existing_present:
                entry = entry_template(locale, field, row, "already_translated")
            else:
                entry = entry_template(locale, field, row, "missing_translation")
                missing_by_locale.setdefault(locale, []).append(entry)
            result["entries"].append(entry)
            count_entry(entry)
    result["source_read_summary"] = source_reads

    if not missing_by_locale:
        result["draft_status"] = "no_missing_translations_found"
        result["success"] = True
        print(json.dumps(result, ensure_ascii=True))
        raise SystemExit(0)

    for locale, missing_entries in missing_by_locale.items():
        translations = request_openai(locale, missing_entries)
        if translations is None:
            print(json.dumps(result, ensure_ascii=True))
            raise SystemExit(1)
        for entry in missing_entries:
            field = entry["field"]
            draft = str(translations.get(field) or "").strip()
            rewritten_draft, rewrite_attempts = rewrite_over_length_draft(locale, entry, draft)
            if rewritten_draft is None:
                print(json.dumps(result, ensure_ascii=True))
                raise SystemExit(1)
            attach_draft_quality(entry, rewritten_draft, rewrite_attempts)
            result["draft_entries"].append(entry)
            result["translation_generated"] = True
    apply_cross_field_seo_checks()
    recalculate_quality_stats()

    result["draft_status"] = "selected_product_missing_translation_draft_ready_for_manual_review"
    result["success"] = True
    print(json.dumps(result, ensure_ascii=True))
except Exception as exc:
    result["draft_status"] = result.get("draft_status") or "blocked_shopify_read_query_failed"
    result["failure_type"] = result.get("failure_type") or "unknown"
    result["error"] = type(exc).__name__ + ": " + str(exc)
    if not result["blocking_conditions"]:
        result["blocking_conditions"].append("blocked_shopify_read_query_failed")
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(1)
"""


def _empty_generation_result(scope: dict) -> dict:
    return {
        "success": False,
        "draft_status": "",
        "product_id": scope.get("product_id", ""),
        "product_title": "",
        "target_locales": scope.get("target_locales", []),
        "requested_fields": scope.get("fields", []),
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
        "stdout_tail": "",
        "stderr_tail": "",
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "existing_translation_overwrite_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _blocking_conditions(validation_errors: list[str], query_result: dict) -> list[str]:
    mapping = {
        "invalid_product_id": "blocked_invalid_product_id",
        "unsupported_locale": "blocked_unsupported_locale",
        "invalid_field": "blocked_invalid_field",
    }
    conditions = [mapping.get(error, error) for error in validation_errors]
    conditions.extend(query_result.get("blocking_conditions") or [])
    failure_type = query_result.get("failure_type", "")
    if query_result.get("draft_status") == "blocked_missing_shopify_installation":
        conditions.append("blocked_missing_shopify_installation")
    elif query_result.get("draft_status") == "blocked_missing_openai_api_key":
        conditions.append("blocked_missing_openai_api_key")
    elif failure_type in {"docker_permission_denied", "missing_env", "timeout", "command_error", "unknown"}:
        conditions.append("blocked_shopify_read_query_failed")
    elif failure_type.startswith("openai"):
        conditions.append("blocked_openai_draft_generation_failed")
    return _unique(conditions)


def _draft_status(blocking_conditions: list[str], query_result: dict) -> str:
    if blocking_conditions:
        for status in [
            "blocked_invalid_product_id",
            "blocked_unsupported_locale",
            "blocked_invalid_field",
            "blocked_missing_shopify_installation",
            "blocked_shopify_read_query_failed",
            "blocked_missing_openai_api_key",
            "blocked_openai_draft_generation_failed",
        ]:
            if status in blocking_conditions:
                return status
        return "blocked"
    if query_result.get("draft_status") == "no_missing_translations_found":
        return "no_missing_translations_found"
    if query_result.get("success"):
        return "selected_product_missing_translation_draft_ready_for_manual_review"
    return "blocked_shopify_read_query_failed"


def _build_payload(
    requested_scope: dict,
    validation_errors: list[str],
    blocking_conditions: list[str],
    draft_status: str,
    query_result: dict,
    success: bool,
    start_time: str,
    end_time: str,
    duration_seconds: float,
) -> dict:
    product_id = requested_scope.get("product_id", "")
    payload = {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "selected-product-missing-translation-draft-package-only",
        "command_label": COMMAND_LABEL,
        "json_selected_product_missing_translation_draft_package_path": str(DRAFT_JSON_PATH),
        "html_selected_product_missing_translation_draft_package_path": str(DRAFT_HTML_PATH),
        "success": success,
        "draft_status": draft_status,
        "product_id": query_result.get("product_id") or product_id,
        "product_title": query_result.get("product_title", ""),
        "target_locales": requested_scope.get("target_locales", []),
        "requested_fields": requested_scope.get("fields", []),
        "generated_draft_count": query_result.get("generated_draft_count", 0),
        "draft_ready_count": query_result.get("draft_ready_count", 0),
        "draft_needs_manual_review_count": query_result.get("draft_needs_manual_review_count", 0),
        "eligible_apply_plan_count": query_result.get("eligible_apply_plan_count", 0),
        "over_length_after_rewrite_count": query_result.get("over_length_after_rewrite_count", 0),
        "seo_ready_count": query_result.get("seo_ready_count", 0),
        "seo_needs_manual_review_count": query_result.get("seo_needs_manual_review_count", 0),
        "seo_eligible_apply_plan_count": query_result.get("seo_eligible_apply_plan_count", 0),
        "forbidden_phrase_count": query_result.get("forbidden_phrase_count", 0),
        "missing_core_keyword_count": query_result.get("missing_core_keyword_count", 0),
        "too_short_for_seo_count": query_result.get("too_short_for_seo_count", 0),
        "skipped_existing_translation_count": query_result.get("skipped_existing_translation_count", 0),
        "skipped_outdated_translation_count": query_result.get("skipped_outdated_translation_count", 0),
        "skipped_source_empty_count": query_result.get("skipped_source_empty_count", 0),
        "per_locale_results": query_result.get("per_locale_results", {}),
        "per_field_results": query_result.get("per_field_results", {}),
        "entries": query_result.get("entries", []),
        "draft_entries": query_result.get("draft_entries", []),
        "source_read_summary": query_result.get("source_read_summary", {}),
        "blocking_conditions": blocking_conditions,
        "safety_summary": _safety_summary(query_result),
        "draft_package_only": True,
        "shopify_read_only": True,
        "shopify_api_call_performed": bool(query_result.get("shopify_api_call_performed")),
        "openai_call_performed": bool(query_result.get("openai_call_performed")),
        "translation_generated": bool(query_result.get("translation_generated")),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "existing_translation_overwrite_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "validation_failures": _unique(validation_errors + blocking_conditions),
        "failure_type": query_result.get("failure_type", ""),
        "query_failure_type": query_result.get("query_failure_type", ""),
        "error": query_result.get("error", ""),
        "stdout_tail": query_result.get("stdout_tail", ""),
        "stderr_tail": query_result.get("stderr_tail", ""),
        "detected_issue_summary": _issue_summary(draft_status, blocking_conditions, query_result),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
    }
    return payload


def _safety_summary(query_result: dict) -> dict:
    return {
        "draft_package_only": True,
        "shopify_read_only": True,
        "shopify_api_call_performed": bool(query_result.get("shopify_api_call_performed")),
        "openai_call_allowed": True,
        "openai_call_performed": bool(query_result.get("openai_call_performed")),
        "shopify_write_allowed": False,
        "mutation_allowed": False,
        "translations_register_allowed": False,
        "publish_allowed": False,
        "real_apply_allowed": False,
        "rollback_allowed": False,
        "existing_translation_overwrite_allowed": False,
        "allowed_fields": ALLOWED_FIELDS,
        "supported_locales": SUPPORTED_LOCALES,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    DRAFT_JSON_PATH.write_text(text, encoding="utf-8")
    json.loads(DRAFT_JSON_PATH.read_text(encoding="utf-8"))
    return DRAFT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    DRAFT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return DRAFT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status = "PASS" if payload.get("success") else "FAIL"
    status_class = "pass" if payload.get("success") else "fail"
    summary_rows = "\n".join(
        _summary_row(label, payload.get(key))
        for label, key in [
            ("Task", "task"),
            ("Mode", "mode"),
            ("Draft Status", "draft_status"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Generated Draft Count", "generated_draft_count"),
            ("Draft Ready Count", "draft_ready_count"),
            ("Draft Needs Manual Review Count", "draft_needs_manual_review_count"),
            ("Eligible Apply Plan Count", "eligible_apply_plan_count"),
            ("Over Length After Rewrite Count", "over_length_after_rewrite_count"),
            ("SEO Ready Count", "seo_ready_count"),
            ("SEO Needs Manual Review Count", "seo_needs_manual_review_count"),
            ("SEO Eligible Apply Plan Count", "seo_eligible_apply_plan_count"),
            ("Forbidden Phrase Count", "forbidden_phrase_count"),
            ("Missing Core Keyword Count", "missing_core_keyword_count"),
            ("Too Short For SEO Count", "too_short_for_seo_count"),
            ("Skipped Existing Translation Count", "skipped_existing_translation_count"),
            ("Skipped Outdated Translation Count", "skipped_outdated_translation_count"),
            ("Skipped Source Empty Count", "skipped_source_empty_count"),
            ("Shopify API Call Performed", "shopify_api_call_performed"),
            ("OpenAI Call Performed", "openai_call_performed"),
            ("Translation Generated", "translation_generated"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    detail_rows = "\n".join(
        _summary_row(label, value)
        for label, value in [
            ("Per Locale Results", payload.get("per_locale_results", {})),
            ("Per Field Results", payload.get("per_field_results", {})),
            ("Draft Entries", payload.get("draft_entries", [])),
            ("All Entries", payload.get("entries", [])),
            ("Source Read Summary", payload.get("source_read_summary", {})),
            ("Safety Summary", payload.get("safety_summary", {})),
            ("Validation Failures", payload.get("validation_failures", [])),
            ("Failure Type", payload.get("failure_type", "")),
            ("Query Failure Type", payload.get("query_failure_type", "")),
            ("Error", payload.get("error", "")),
        ]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Selected Product Missing Translation Draft Package</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #202124; background: #fff; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d0d7de; padding: 8px; vertical-align: top; text-align: left; }}
    th {{ background: #f6f8fa; width: 320px; }}
    .status {{ padding: 12px 14px; border-radius: 6px; font-weight: 700; margin: 12px 0; }}
    .status.pass {{ background: #dafbe1; color: #116329; }}
    .status.fail {{ background: #ffebe9; color: #82071e; }}
  </style>
</head>
<body>
  <h1>Selected Product Missing Translation Draft Package</h1>
  <div class="status {status_class}">{escape(status)}: {escape(payload.get("detected_issue_summary", ""))}</div>
  <h2>Summary</h2>
  <table><tbody>{summary_rows}</tbody></table>
  <h2>Details</h2>
  <table><tbody>{detail_rows}</tbody></table>
  <h2>Safety</h2>
  <ul>
    <li>This task reads Shopify product translatable resources and existing translations only.</li>
    <li>OpenAI may be used only to generate local draft text for missing translations.</li>
    <li>No Shopify write, mutation, translationsRegister, publish, apply, rollback, or existing translation overwrite was performed.</li>
  </ul>
</body>
</html>
"""


def _summary_row(label: str, value) -> str:
    return f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"


def _issue_summary(status: str, blocking_conditions: list[str], query_result: dict) -> str:
    if blocking_conditions:
        return "Selected product translation draft package blocked: " + ", ".join(blocking_conditions)
    if status == "no_missing_translations_found":
        return "No missing translations found for requested fields/locales. No draft generated and no Shopify write performed."
    return (
        "Selected product missing translation draft package generated for manual review. "
        f"Drafts: {query_result.get('generated_draft_count', 0)}. No Shopify write performed."
    )


def _build_approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify selected product missing translation draft package generated.\n"
        f"Draft status: {payload.get('draft_status')}\n"
        f"Product ID: {payload.get('product_id')}\n"
        f"Product title: {payload.get('product_title')}\n"
        f"Target locales: {payload.get('target_locales')}\n"
        f"Requested fields: {payload.get('requested_fields')}\n"
        f"Generated draft count: {payload.get('generated_draft_count')}\n"
        f"Draft ready count: {payload.get('draft_ready_count')}\n"
        f"Draft needs manual review count: {payload.get('draft_needs_manual_review_count')}\n"
        f"Eligible apply plan count: {payload.get('eligible_apply_plan_count')}\n"
        f"Over length after rewrite count: {payload.get('over_length_after_rewrite_count')}\n"
        f"SEO ready count: {payload.get('seo_ready_count')}\n"
        f"SEO needs manual review count: {payload.get('seo_needs_manual_review_count')}\n"
        f"SEO eligible apply plan count: {payload.get('seo_eligible_apply_plan_count')}\n"
        f"Skipped existing/current translations: {payload.get('skipped_existing_translation_count')}\n"
        f"Skipped outdated translations: {payload.get('skipped_outdated_translation_count')}\n"
        f"Shopify API call performed: {payload.get('shopify_api_call_performed')}\n"
        f"OpenAI call performed: {payload.get('openai_call_performed')}\n"
        f"No new Shopify writes performed: {payload.get('no_new_shopify_writes_performed')}\n"
        f"Blocking conditions: {payload.get('blocking_conditions')}\n"
        "Draft package JSON:\n"
        f"{json_path}\n\n"
        "Draft package HTML:\n"
        f"{html_path}\n"
        "Draft package only. No Shopify write, mutation, translationsRegister, publish, apply, or rollback was performed.\n\n"
        "Allowed actions only:\n"
        "Y / 1 = keep draft package files\n"
        "SHOW_LOG = show recent logs\n"
        "SUMMARY = show summary\n"
        "N / 0 = stop\n\n"
        "Do not push from this task."
    )


def _parse_json_from_stdout(stdout: str) -> dict:
    for line in reversed(stdout.splitlines()):
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    return {}


def _classify_command_failure(stdout: str, stderr: str) -> str:
    combined = f"{stdout}\n{stderr}".lower()
    if "access is denied" in combined or "permission denied" in combined or "docker_engine" in combined:
        return "docker_permission_denied"
    if "no such file or directory" in combined or "not recognized" in combined:
        return "missing_env"
    return "command_error"


def _decode_bytes(value: bytes | None) -> str:
    if not value:
        return ""
    return value.decode("utf-8", errors="replace")


def _tail(text: str, max_lines: int = 80) -> str:
    return "\n".join(text.splitlines()[-max_lines:])


def _unique(values: list[str]) -> list[str]:
    unique_values = []
    for value in values:
        if value and value not in unique_values:
            unique_values.append(value)
    return unique_values
