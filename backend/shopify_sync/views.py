import json
import hmac
import os
import re
import secrets
import hashlib
import threading
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path
from urllib.error import HTTPError, URLError

import requests
from django.contrib import admin, messages
from django.core.exceptions import FieldDoesNotExist
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db import close_old_connections
from django.db.models import Count, F, Max, Q
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotAllowed,
    HttpResponseRedirect,
    HttpResponseServerError,
    JsonResponse,
)
from django.shortcuts import render
from django.utils.html import escape
from django.utils.safestring import mark_safe

from .models import ShopifyInstallation, ShopifyOrder, ShopifyProduct, ShopifyOrderItem, ShopifySyncState
from .review_request_workbench import (
    build_review_request_workbench_context,
    review_request_review_and_send,
    run_trustpilot_auto_queue_refresh_after_shopify_order_sync,
)
from .sync_helpers import (
    ORDER_SYNC_TASK_NAMES,
    run_shopify_sync_task,
    sync_products_for_installation,
    sync_shenzhen_orders_for_installation,
    update_shenzhen_tracking_for_installation,
)
from .translation_console import (
    SUPPORTED_TRANSLATION_LOCALES,
    ShopifyTranslationConsoleError,
    fetch_translation_console_data,
    normalize_product_gid,
    safe_translation_console_error_message,
)
from .translation_apply_plan import (
    APPLY_PLAN_HTML_PATH,
    APPLY_PLAN_JSON_PATH,
    LOCKED_EXECUTION_ACK_PHRASE,
    LOCKED_EXECUTION_ACTION_NAME,
    ALL_LANGUAGES_REAL_WRITE_ACTION_NAME,
    REAL_WRITE_ACTION_NAME,
    SELECTED_TRANSLATIONS_REAL_WRITE_ACK_PHRASE,
    SELECTED_TRANSLATIONS_REAL_WRITE_ACTION_NAME,
    SAFE_WRITE_READINESS_ACTION_NAME,
    apply_selected_translations_to_shopify,
    build_translation_workspace_all_languages_update_state,
    build_translation_workspace_selected_apply_state,
    build_translation_workspace_locked_execution_package,
    build_translation_workspace_safe_write_readiness_package,
    build_translation_workspace_safe_write_readiness_state,
    build_selected_product_translation_apply_plan,
    execute_translation_workspace_single_locked_write,
    load_latest_all_languages_update_report,
    load_translation_workspace_locked_execution_package,
    validate_and_update_all_languages_to_shopify,
)
from .translation_drafts import (
    ALL_ELIGIBLE_DRAFT_SCOPES,
    DEFAULT_FIELDS as TRANSLATION_DRAFT_FIELDS,
    DEFAULT_TARGET_LOCALES as TRANSLATION_DRAFT_TARGET_LOCALES,
    FORBIDDEN_OUTPUT_RE,
    OPENAI_INVALID_TRANSLATION_RESPONSE,
    OPENAI_TRANSLATION_GENERATION_STAGE,
    OPENAI_TRANSLATIONS_MISSING_MESSAGE,
    TRANSLATE_ALL_ACTION_NAME,
    build_product_identity_context,
    generate_selected_product_missing_translation_draft_package,
    validate_product_identity_draft,
)
from .translation_final_review import (
    FINAL_REVIEW_HTML_PATH,
    FINAL_REVIEW_JSON_PATH,
    build_selected_product_translation_final_review,
)
from .translation_locked_execution_plan import (
    LOCKED_EXECUTION_PLAN_HTML_PATH,
    LOCKED_EXECUTION_PLAN_JSON_PATH,
    build_selected_product_translation_locked_execution_plan,
)
from .translation_locked_executor import (
    LOCKED_EXECUTOR_HTML_PATH,
    LOCKED_EXECUTOR_JSON_PATH,
    build_selected_product_translation_locked_executor_shell,
)
from .translation_real_write_readiness import (
    REAL_WRITE_READINESS_HTML_PATH,
    REAL_WRITE_READINESS_JSON_PATH,
    build_selected_product_translation_real_write_readiness,
)
from .translation_real_write_executor import (
    MANUAL_ACK_PHRASE_REQUIRED as REAL_WRITE_MANUAL_ACK_PHRASE_REQUIRED,
    REAL_WRITE_EXECUTOR_HTML_PATH,
    REAL_WRITE_EXECUTOR_JSON_PATH,
    build_selected_product_translation_real_write_executor_dry_run,
)
from .translation_real_write_manual_action_package import (
    REAL_WRITE_MANUAL_ACTION_HTML_PATH,
    REAL_WRITE_MANUAL_ACTION_JSON_PATH,
    build_selected_product_translation_real_write_manual_action_package,
)
from .translation_workflow_status import (
    DEFAULT_SELECTED_PRODUCT_ID as TRANSLATION_WORKFLOW_DEFAULT_PRODUCT_ID,
    load_translation_workflow_status,
)
from .translation_console_locked_package_report import (
    build_translation_console_manual_command_package,
    generate_translation_console_locked_package_dry_run_report,
    load_latest_translation_console_locked_package_report,
)


SHOPIFY_OAUTH_STATE_SESSION_KEY = "shopify_oauth_states"
SHOPIFY_SHOP_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com$"
)
TRANSLATION_CONSOLE_PRODUCT_SELECTOR_LIMIT = 50
TRANSLATION_CONSOLE_PRODUCT_SEARCH_SCAN_LIMIT = 5000
TRANSLATION_CONSOLE_PRODUCT_SYNC_TASK_NAME = "products_daily"
TRANSLATION_CONSOLE_PRODUCT_MODEL_QUERY_RE = re.compile(
    r"[A-Za-z]+(?:[\s_-]*\d+[A-Za-z0-9]*)+"
)
TRANSLATION_CONSOLE_PRODUCT_SPARE_PART_TERMS = (
    "spare",
    "replacement",
    "propeller",
    "battery",
    "motor",
    "esc",
    "landing gear",
    "wheel",
    "wheels",
    "led",
    "light",
    "charger",
    "connector",
)
TRANSLATION_CONSOLE_PRODUCT_MAIN_PRODUCT_PHRASES = (
    "rc plane",
    "airplane",
    "helicopter",
    "jet",
    "rtf",
    "aircraft",
)
TRANSLATION_CONSOLE_PRODUCT_SELECTOR_SORT_FIELDS = [
    "shopify_published_at",
    "shopify_created_at",
    "shopify_product_created_at",
    "created_at",
    "updated_at",
    "id",
]
TRANSLATION_CONSOLE_PRODUCT_SEARCH_FIELDS = [
    "product_title",
    "shopify_product_id",
    "shopify_variant_id",
    "sku",
    "variant_title",
    "handle",
    "vendor",
    "product_type",
    "status",
]
TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS = 50
TRANSLATION_CONSOLE_TRANSLATE_ALL_DETAIL_MAX_ROWS = 1000
TRANSLATION_CONSOLE_DRAFT_PREVIEW_CHARS = 120
TRANSLATION_CONSOLE_REVIEW_TEXT_CHARS = 900
TRANSLATION_CONSOLE_REVIEW_SUMMARY_CHARS = 160
TRANSLATION_CONSOLE_EDITOR_PREVIEW_CHARS = 1200
TRANSLATION_CONSOLE_HTML_PREVIEW_ALLOWED_TAGS = {
    "a",
    "b",
    "br",
    "em",
    "h1",
    "h2",
    "h3",
    "hr",
    "i",
    "iframe",
    "li",
    "ol",
    "p",
    "strong",
    "ul",
}
TRANSLATION_CONSOLE_HTML_PREVIEW_VOID_TAGS = {"br", "hr"}
TRANSLATION_CONSOLE_HTML_PREVIEW_DROP_CONTENT_TAGS = {
    "embed",
    "object",
    "script",
    "style",
}
TRANSLATION_CONSOLE_HTML_PREVIEW_IFRAME_ATTRS = {
    "allow",
    "allowfullscreen",
    "frameborder",
    "height",
    "loading",
    "referrerpolicy",
    "src",
    "title",
    "width",
}
TRANSLATION_CONSOLE_HTML_PREVIEW_VIDEO_HOSTS = {
    "player.vimeo.com",
    "www.youtube-nocookie.com",
    "www.youtube.com",
    "youtu.be",
    "youtube-nocookie.com",
    "youtube.com",
}
TRANSLATION_CONSOLE_HTML_PREVIEW_BLOCKED_IFRAME_PLACEHOLDER = (
    '<div class="tw-video-embed-placeholder">Video embed hidden for safety</div>'
)
TRANSLATION_CONSOLE_HTML_PREVIEW_SAFE_URL_SCHEMES = {
    "",
    "http",
    "https",
    "mailto",
    "tel",
}
TRANSLATION_WORKSPACE_DRAFT_FIELDS = [
    "title",
    "body_html",
    "meta_title",
    "meta_description",
    "handle",
]
TRANSLATION_WORKSPACE_DRAFT_GROUPS = [
    {
        "value": "product_basics",
        "label": "Product basics",
        "description": "Title and product description/body HTML",
    },
    {
        "value": "seo",
        "label": "SEO",
        "description": "SEO title, SEO description, and cautious URL handle preview",
    },
    {
        "value": "options",
        "label": "Options",
        "description": "Product option names and values",
    },
    {
        "value": "variants",
        "label": "Variants",
        "description": "Variant display text and option values when Shopify exposes them",
    },
    {
        "value": "important_metafields",
        "label": "Important metafields",
        "description": "Customer-facing product page metafields",
    },
    {
        "value": "media",
        "label": "Media alt text",
        "description": "Image/media alt text when Shopify exposes it",
    },
]
TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS = [
    option["value"] for option in TRANSLATION_WORKSPACE_DRAFT_GROUPS
]
TRANSLATION_WORKSPACE_RESULT_VISIBLE_STATUSES = {"completed", "partial"}
TRANSLATION_WORKSPACE_RESULT_PRIMARY_GROUPS = {"product_basics", "seo"}
TRANSLATION_EDITOR_LOCALE_LABELS = {
    "ja": "Japanese",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "it": "Italian",
}
TRANSLATION_EDITOR_LOCALE_LABEL_ALIASES = {
    label.lower(): code for code, label in TRANSLATION_EDITOR_LOCALE_LABELS.items()
}
TRANSLATION_WORKSPACE_RESULT_GROUP_ORDER = {
    "product_basics": 0,
    "seo": 1,
    "options": 2,
    "variants": 3,
    "important_metafields": 4,
    "media": 5,
}
TRANSLATION_WORKSPACE_RESULT_FIELD_ORDER = {
    "title": 0,
    "body_html": 1,
    "description": 1,
    "meta_title": 2,
    "meta_description": 3,
    "option.name": 4,
    "option.value": 4,
    "variant.title": 5,
    "media.alt": 7,
    "alt": 7,
}
TRANSLATION_WORKSPACE_RESULT_REASON_LABELS = {
    "existing_translation_outdated": "Existing translation is outdated",
    "existing_translation_outdated_manual_review_required": "Existing translation is outdated",
    "seo_needs_manual_review": "SEO text needs review",
    "seo_not_ready": "SEO text needs review",
    "missing_part_type": "SEO may be missing the part type",
    "missing_use_case": "SEO may be missing the use case",
    "missing_value_point": "SEO may be missing a value point",
    "future_write_needs_resource_mapping": "Can review now; Shopify update support needs extra mapping",
    "source_empty": "Original source is empty",
    "not_eligible_technical_field": "Technical field, not translated automatically",
    "not_draft_eligible": "Technical field, not translated automatically",
    "already_translated": "Already up to date",
    "existing_translation_current": "Already up to date",
    "manual_review_required": "Needs manual review",
    "no_generated_draft": "No automatic translation was generated",
    "openai_invalid_translation_response": "OpenAI returned an invalid response format",
    "body_html_structure_broken": "Product description HTML structure needs review",
    "draft_equals_source": "Translation is unchanged from the source",
    "missing_translation_not_requested": "Not translated automatically in this run",
    "child_resource_query_failed": "Some Shopify content could not be read",
    "skipped_child_resource_query_failed": "Some Shopify content could not be read",
    "product_identity_mismatch": "Possible wrong product text",
    "draft_blocked": "Translation was blocked for review",
    "not_eligible_for_apply_plan": "Not ready for Shopify update preparation",
    "current_translation_outdated": "Existing translation is outdated",
    "draft_over_max_chars": "Translation is too long",
    "forbidden_marketing_or_origin_phrase": "Forbidden CTA, shipping, or origin phrase",
    "forbidden_marketing_or_shipping_phrase": "Forbidden CTA, shipping, or origin phrase",
    "html_media_or_link_tag_broken": "HTML, video, link, or image tag needs review",
    "keyword_stuffing_or_duplicate": "SEO text needs review",
    "product_title_over_80_chars": "Product title is over 80 characters",
    "seo_title_over_60_chars": "SEO title is over 60 characters",
    "seo_description_over_160_chars": "SEO description is over 160 characters",
}
TRANSLATION_WORKSPACE_SHOPIFY_APPLY_BLOCK_LABELS = {
    "blocked_body_html_forbidden_in_selected_apply": "Product description update is not enabled yet.",
    "blocked_body_html_manual_review_required": "Product description update is not enabled yet.",
    "blocked_field_not_allowed_for_selected_apply": "Only title, SEO title, and SEO description can be updated in this phase.",
    "blocked_future_write_needs_resource_mapping": "Missing Shopify write mapping.",
    "blocked_missing_generated_or_manual_translation": "No translation result is available for Shopify update.",
    "blocked_missing_generated_draft": "No translation result is available for Shopify update.",
    "blocked_missing_resource_id_key_or_digest": "Missing Shopify write mapping.",
    "blocked_missing_write_mapping": "Missing Shopify write mapping.",
    "blocked_no_selected_apply_eligible_entries": "Select title, SEO title, or SEO description to update Shopify.",
    "blocked_not_customer_write_safe": "This row is not enabled for Shopify update.",
    "blocked_product_identity_mismatch": "This row belongs to another product and cannot be selected.",
    "blocked_scope_group_not_allowed": "This row is not enabled for Shopify update.",
    "blocked_selected_product_report_mismatch": "Previous report belongs to another product and was hidden.",
    "blocked_existing_current_translation": "Already up to date.",
    "blocked_proposed_translation_empty": "No translation result is available for Shopify update.",
    "blocked_proposed_translation_equals_source": "Translation matches the source text and cannot be selected.",
    "blocked_product_title_over_80_chars": "Product title is over 80 characters.",
    "blocked_seo_title_over_60_chars": "SEO title is over 60 characters.",
    "blocked_seo_description_over_160_chars": "SEO description is over 160 characters.",
    "blocked_forbidden_phrase_detected": "Translation contains a blocked phrase.",
    "blocked_identity_review_required": "This translation needs product identity review first.",
    "blocked_draft_status": "This translation needs review before Shopify update.",
    "blocked_draft_manual_review_required": "This translation needs review before Shopify update.",
    "blocked_seo_manual_review_required": "SEO text needs review before Shopify update.",
    "not_in_selected_locale": "Switch to this language tab to select this row.",
}
TRANSLATION_WORKSPACE_REVIEW_REASON_CODES = {
    "body_html_structure_broken",
    "blocked",
    "draft_blocked",
    "draft_empty",
    "draft_equals_source",
    "draft_needs_manual_review",
    "draft_needs_manual_review_empty",
    "draft_over_max_chars",
    "existing_translation_outdated",
    "existing_translation_outdated_manual_review_required",
    "forbidden_marketing_or_origin_phrase",
    "forbidden_marketing_or_shipping_phrase",
    "html_media_or_link_tag_broken",
    "keyword_stuffing_or_duplicate",
    "manual_review_required",
    "missing_core_keyword",
    "missing_model",
    "missing_part_type",
    "missing_replacement_part_meaning",
    "missing_use_case",
    "needs_review",
    "openai_invalid_translation_response",
    "product_identity_mismatch",
    "product_title_over_80_chars",
    "seo_description_over_160_chars",
    "seo_needs_manual_review",
    "seo_not_ready",
    "seo_title_over_60_chars",
}
TRANSLATION_WORKSPACE_MAPPING_NOTICE_REASONS = {
    "future_write_needs_resource_mapping",
}
TRANSLATION_WORKSPACE_NON_BLOCKING_REASON_CODES = {
    "missing_translation",
    "missing_translation_draft_ready",
    "missing_value_point",
    "outdated_translation_update_draft_ready",
    "too_short_for_seo",
}
TRANSLATION_WORKSPACE_RESULT_FIELD_LABELS = {
    "title": "Product title",
    "body_html": "Product description",
    "meta_title": "SEO title",
    "meta_description": "SEO description",
    "handle": "URL handle",
    "option.name": "Option name",
    "option.value": "Option value",
    "variant.title": "Variant title",
    "media.alt": "Media alt text",
    "alt": "Media alt text",
}
TRANSLATION_WORKSPACE_APPLY_SUPPORTED_FIELDS = {
    "title",
    "meta_title",
    "meta_description",
}
TRANSLATION_WORKSPACE_MAPPING_REQUIRED_GROUPS = {
    "options",
    "variants",
    "important_metafields",
    "media",
}
TRANSLATION_WORKSPACE_JOB_DIR = Path("logs/shopify_translation_workspace_jobs")
TRANSLATION_WORKSPACE_JOB_STALE_SECONDS = 15 * 60
TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES = {"pending", "running"}
TRANSLATION_WORKSPACE_LOCALE_TERMINAL_STATUSES = {
    "completed",
    "failed",
    "skipped",
    "stale",
}
TRANSLATION_WORKSPACE_JOB_TERMINAL_STATUSES = {
    "completed",
    "partial",
    "failed",
    "cancelled",
    "stale",
}
TRANSLATION_WORKSPACE_JOB_ID_RE = re.compile(
    r"^translation_workspace_job_[a-f0-9]{16}_\d{8}T\d{6}Z_[a-f0-9]{8}$"
)
TRANSLATION_WORKSPACE_MANUAL_EDIT_ACTION_NAME = "save_translation_manual_edit"
TRANSLATION_WORKSPACE_RETRY_LOCALE_ACTION_NAME = "retry_failed_translation_language"
TRANSLATION_WORKSPACE_JOB_DETAIL_PREVIEW_LIMIT = 60
TRANSLATION_WORKSPACE_JOB_REVIEW_ROW_LIMIT = 1000
TRANSLATION_WORKSPACE_JOB_ERROR_LIMIT = 20
TRANSLATION_WORKSPACE_JOB_SECRET_RE = re.compile(
    r"\b(?:shpat_|shpca_|shppa_|shpss_|sk-)[A-Za-z0-9_\-]+\b"
    r"|\b[A-Za-z0-9_\-]{48,}\b"
    r"|\b(?:token|secret|password|api[_-]?key|authorization)\s*[:=]\s*[^,\s;]+",
    flags=re.IGNORECASE,
)
TRANSLATION_CONSOLE_EDITOR_FILTERS = {
    "all",
    "untranslated",
    "needs_translation",
    "outdated",
    "translated",
    "needs_review",
    "draft_only",
    "seo",
    "variants_options",
    "metafields",
    "media",
}
TRANSLATION_CONSOLE_EDITOR_SECTIONS = [
    {
        "section_key": "basic",
        "section_label": "Product basics",
        "section_hint": "Product title and product description/body HTML.",
        "collapsible": False,
        "collapsed_by_default": False,
    },
    {
        "section_key": "seo",
        "section_label": "SEO",
        "section_hint": "Search preview fields and URL handle.",
        "collapsible": False,
        "collapsed_by_default": False,
    },
    {
        "section_key": "options",
        "section_label": "Product options",
        "section_hint": "Option names and option values returned by Shopify translation data.",
        "collapsible": False,
        "collapsed_by_default": False,
    },
    {
        "section_key": "variants",
        "section_label": "Variants",
        "section_hint": "Variant titles, option values, and variant-level fields when available.",
        "collapsible": False,
        "collapsed_by_default": False,
    },
    {
        "section_key": "important_metafields",
        "section_label": "Important metafields",
        "section_hint": "Customer-facing metafields likely to matter in translation review.",
        "collapsible": True,
        "collapsed_by_default": True,
    },
    {
        "section_key": "media",
        "section_label": "Media alt text",
        "section_hint": "Image/media alt text when Shopify exposes it as translatable content.",
        "collapsible": False,
        "collapsed_by_default": False,
    },
    {
        "section_key": "technical_metafields",
        "section_label": "Technical / not translated",
        "section_hint": "System, review, rating, ID, JSON, inventory, and unclear fields stay view-only.",
        "collapsible": True,
        "collapsed_by_default": True,
    },
]
TRANSLATION_CONSOLE_EDITOR_SEO_LIMITS = {
    "title": 80,
    "meta_title": 60,
    "meta_description": 160,
}
TRANSLATION_WORKSPACE_FIELD_COVERAGE_CORE_AREAS = [
    {
        "area_key": "title",
        "area_label": "Product title",
        "group_label": "Basic",
        "field_keys": ("title",),
        "note": "Main Shopify product title.",
    },
    {
        "area_key": "body_html",
        "area_label": "Product description",
        "group_label": "Basic",
        "field_keys": ("body_html", "description"),
        "note": "Full product description HTML for visual review.",
    },
    {
        "area_key": "meta_title",
        "area_label": "SEO title",
        "group_label": "SEO",
        "field_keys": ("meta_title",),
        "note": "SEO title translation field.",
    },
    {
        "area_key": "meta_description",
        "area_label": "SEO description",
        "group_label": "SEO",
        "field_keys": ("meta_description",),
        "note": "SEO description translation field.",
    },
    {
        "area_key": "handle",
        "area_label": "URL handle",
        "group_label": "SEO",
        "field_keys": ("handle",),
        "note": "URL handle is shown when Shopify returns it. Any draft is cautious/manual-review only.",
    },
]
TRANSLATION_WORKSPACE_FIELD_COVERAGE_EXTRA_SECTIONS = [
    ("options", "Product options"),
    ("variants", "Variants"),
    ("important_metafields", "Important metafields"),
    ("media", "Media alt text"),
    ("technical_metafields", "Technical / not translated"),
]
TRANSLATION_EDITOR_IMPORTANT_METAFIELD_NAMESPACES = {
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
TRANSLATION_EDITOR_IMPORTANT_METAFIELD_HINTS = (
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
TRANSLATION_EDITOR_TECHNICAL_METAFIELD_NAMESPACES = {
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
TRANSLATION_EDITOR_TECHNICAL_METAFIELD_HINTS = (
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


def _shopify_configured():
    return bool(
        os.getenv("SHOPIFY_CLIENT_ID")
        and os.getenv("SHOPIFY_CLIENT_SECRET")
        and os.getenv("SHOPIFY_SCOPES")
        and os.getenv("SHOPIFY_REDIRECT_URI")
    )


def _normalize_shop_domain(shop):
    shop = (shop or "").strip().lower()
    if not SHOPIFY_SHOP_DOMAIN_RE.fullmatch(shop):
        return ""
    return shop


def _hmac_digest(message, client_secret):
    return hmac.new(
        client_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _verify_shopify_hmac(query_params, raw_query_string=""):
    provided_hmac = query_params.get("hmac", "")
    client_secret = os.getenv("SHOPIFY_CLIENT_SECRET", "")
    if not provided_hmac or not client_secret:
        return False

    decoded_params = []
    for key in sorted(query_params.keys()):
        if key in {"hmac", "signature"}:
            continue
        for value in query_params.getlist(key):
            decoded_params.append((key, value))

    messages = [
        "&".join(f"{key}={value}" for key, value in decoded_params),
        urllib.parse.urlencode(decoded_params, doseq=True, safe=":/"),
    ]

    if raw_query_string:
        raw_params = urllib.parse.parse_qsl(raw_query_string, keep_blank_values=True)
        raw_params = [
            (key, value)
            for key, value in raw_params
            if key not in {"hmac", "signature"}
        ]
        raw_params.sort(key=lambda item: item[0])
        messages.extend(
            [
                "&".join(f"{key}={value}" for key, value in raw_params),
                urllib.parse.urlencode(raw_params, doseq=True, safe=":/"),
            ]
        )

    for message in dict.fromkeys(messages):
        digest = _hmac_digest(message, client_secret)
        if hmac.compare_digest(digest, provided_hmac):
            return True

    print(
        "[SHOPIFY OAUTH] HMAC verification failed. "
        f"shop={query_params.get('shop', '')} "
        f"timestamp={query_params.get('timestamp', '')} "
        f"secret_configured={bool(client_secret)} "
        f"candidate_count={len(dict.fromkeys(messages))}"
    )
    return False


def _save_oauth_state(request, shop):
    state = secrets.token_urlsafe(32)
    states = request.session.get(SHOPIFY_OAUTH_STATE_SESSION_KEY, {})
    states[shop] = state
    request.session[SHOPIFY_OAUTH_STATE_SESSION_KEY] = states
    request.session.modified = True
    return state


def _pop_oauth_state(request, shop):
    states = request.session.get(SHOPIFY_OAUTH_STATE_SESSION_KEY, {})
    expected_state = states.pop(shop, "")
    request.session[SHOPIFY_OAUTH_STATE_SESSION_KEY] = states
    request.session.modified = True
    return expected_state


def _fetch_official_access_scopes(shop, access_token):
    scopes_url = f"https://{shop}/admin/oauth/access_scopes.json"
    request_obj = urllib.request.Request(
        scopes_url,
        headers={"X-Shopify-Access-Token": access_token},
    )
    response = urllib.request.urlopen(request_obj, timeout=10)
    data = json.loads(response.read().decode("utf-8"))
    return ",".join(
        scope.get("handle", "")
        for scope in data.get("access_scopes", [])
        if scope.get("handle")
    )


@login_required
def sync_dashboard(request):
    if not _user_has_shopify_sync_access(request):
        return HttpResponseForbidden("Only authorized Shopify sync users can view the Shopify sync dashboard.")

    rows = []
    for state in ShopifySyncState.objects.all():
        rows.append(
            "<tr>"
            f"<td>{escape(state.task_name)}</td>"
            f"<td>{'Running' if state.is_running else 'Idle'}</td>"
            f"<td>{state.started_at or ''}</td>"
            f"<td>{state.finished_at or ''}</td>"
            f"<td>{state.last_success_at or ''}</td>"
            f"<td>{escape(state.last_error[:300])}</td>"
            f"<td>{escape(state.last_result[:500])}</td>"
            "</tr>"
        )
    state_rows = "".join(rows) or "<tr><td colspan='7'>No sync state recorded yet.</td></tr>"

    return HttpResponse(
        "<html><head><meta charset='utf-8'><title>Shopify Sync Dashboard</title></head>"
        "<body style='font-family: Arial, sans-serif; padding: 24px; color:#222;'>"
        "<h1>Shopify 同步仪表盘</h1>"
        "<p>手动同步会使用同步锁；如果同类任务正在运行，会返回跳过提示。</p>"
        "<div style='display: flex; flex-wrap: wrap; gap: 12px; margin: 20px 0;'>"
        "<a style='display:inline-block;padding:10px 16px;background:#198754;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/sync-shenzhen-orders/?days=3'>同步最近 3 天订单</a>"
        "<a style='display:inline-block;padding:10px 16px;background:#198754;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/sync-shenzhen-orders/?days=7'>同步最近 7 天订单</a>"
        "<a style='display:inline-block;padding:10px 16px;background:#198754;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/sync-shenzhen-orders/?days=30'>同步最近 30 天订单</a>"
        "<a style='display:inline-block;padding:10px 16px;background:#198754;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/sync-shenzhen-orders/?days=60'>同步最近 60 天订单</a>"
        "<a style='display:inline-block;padding:10px 16px;background:#0b5ed7;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/sync-products/'>同步 Shopify 产品</a>"
        "<a style='display:inline-block;padding:10px 16px;background:#fd7e14;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/update-shenzhen-tracking/'>更新深圳仓物流</a>"
        "</div>"
        "<h2>同步状态</h2>"
        "<table style='border-collapse:collapse;width:100%;font-size:13px;'>"
        "<thead><tr>"
        "<th style='border:1px solid #ddd;padding:6px;text-align:left;'>Task</th>"
        "<th style='border:1px solid #ddd;padding:6px;text-align:left;'>Status</th>"
        "<th style='border:1px solid #ddd;padding:6px;text-align:left;'>Started</th>"
        "<th style='border:1px solid #ddd;padding:6px;text-align:left;'>Finished</th>"
        "<th style='border:1px solid #ddd;padding:6px;text-align:left;'>Last Success</th>"
        "<th style='border:1px solid #ddd;padding:6px;text-align:left;'>Last Error</th>"
        "<th style='border:1px solid #ddd;padding:6px;text-align:left;'>Last Result</th>"
        "</tr></thead>"
        f"<tbody>{state_rows}</tbody>"
        "</table>"
        "</body></html>",
        content_type="text/html; charset=utf-8",
    )
@login_required
def install(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Only superusers can install Shopify apps.")

    shop = _normalize_shop_domain(request.GET.get("shop"))
    if not shop:
        return HttpResponseBadRequest("Missing or invalid shop parameter.")

    client_id = os.getenv("SHOPIFY_CLIENT_ID", "")
    scopes = os.getenv("SHOPIFY_SCOPES", "")
    redirect_uri = os.getenv("SHOPIFY_REDIRECT_URI", "")
    if not (client_id and scopes and redirect_uri):
        return HttpResponseServerError("Shopify OAuth is not configured.")

    params = {
        "client_id": client_id,
        "scope": scopes,
        "redirect_uri": redirect_uri,
        "state": _save_oauth_state(request, shop),
    }
    install_url = f"https://{shop}/admin/oauth/authorize?{urllib.parse.urlencode(params)}"
    print(
        "[SHOPIFY OAUTH] Install authorization URL generated "
        f"shop={shop} scopes={scopes} "
        f"contains_read_translations={'read_translations' in scopes.split(',')}"
    )
    return HttpResponseRedirect(install_url)


def callback(request):
    shop = _normalize_shop_domain(request.GET.get("shop"))
    code = request.GET.get("code")
    state = request.GET.get("state", "")
    if not shop or not code:
        return HttpResponseBadRequest("Missing or invalid shop/code.")

    if not _shopify_configured():
        return HttpResponseServerError("Shopify OAuth is not configured.")

    hmac_valid = _verify_shopify_hmac(request.GET, request.META.get("QUERY_STRING", ""))
    expected_state = _pop_oauth_state(request, shop)
    if not expected_state or not hmac.compare_digest(expected_state, state):
        return HttpResponseForbidden("Invalid Shopify OAuth state.")
    if not hmac_valid:
        print(
            "[SHOPIFY OAUTH] Continuing callback after valid state despite "
            "HMAC mismatch. Check SHOPIFY_CLIENT_SECRET if token exchange fails."
        )

    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = urllib.parse.urlencode(
        {
            "client_id": os.getenv("SHOPIFY_CLIENT_ID", ""),
            "client_secret": os.getenv("SHOPIFY_CLIENT_SECRET", ""),
            "code": code,
        }
    ).encode("utf-8")

    request_obj = urllib.request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    try:
        response = urllib.request.urlopen(request_obj, timeout=10)
        output = response.read().decode("utf-8")
        token_data = json.loads(output)
    except (HTTPError, URLError, ValueError) as exc:
        return HttpResponseServerError(f"Shopify token exchange failed: {exc}")

    access_token = token_data.get("access_token")
    scope = token_data.get("scope", "")
    if not access_token:
        return HttpResponseServerError("Failed to obtain Shopify access token.")

    token_exchange_scope = scope
    try:
        official_scope = _fetch_official_access_scopes(shop, access_token)
        if official_scope:
            scope = official_scope
    except (HTTPError, URLError, ValueError, json.JSONDecodeError) as exc:
        print(f"[CALLBACK] Failed to fetch official access scopes: {exc}")

    # Debug: Print token info
    token_preview = f"{access_token[:5]}...{access_token[-5:]}"
    print(f"[CALLBACK] OAuth callback received for shop: {shop}")
    print(f"[CALLBACK] New access_token (preview): {token_preview}")
    print(f"[CALLBACK] Token exchange scope: {token_exchange_scope}")
    print(f"[CALLBACK] Stored official scope: {scope}")
    print(
        "[CALLBACK] Stored official scope contains read_translations: "
        f"{'read_translations' in scope.split(',')}"
    )

    # Update or create
    obj, created = ShopifyInstallation.objects.update_or_create(
        shop=shop,
        defaults={
            "access_token": access_token,
            "scope": scope,
        },
    )
    print(f"[CALLBACK] Database update result - Created: {created}, Shop: {obj.shop}")
    
    # Verify saved data
    verification = ShopifyInstallation.objects.get(shop=shop)
    saved_token_preview = f"{verification.access_token[:5]}...{verification.access_token[-5:]}"
    print(f"[CALLBACK] Verification - Saved token (preview): {saved_token_preview}")
    print(f"[CALLBACK] Token match after save: {verification.access_token == access_token}")

    return HttpResponse(f"Shopify installation completed for {shop}.")


@login_required
def test_orders(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Only superusers can access this page.")

    shop_domain = "kidstoylover.myshopify.com"
    try:
        installation = ShopifyInstallation.objects.get(shop=shop_domain)
    except ShopifyInstallation.DoesNotExist:
        return HttpResponseServerError(
            f"Shopify installation not found for {shop_domain}"
        )

    access_token = installation.access_token
    api_url = f"https://{shop_domain}/admin/api/2024-01/orders.json?limit=5&status=any"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(api_url, headers=headers, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        return HttpResponseServerError(
            f"API request failed: {exc.__class__.__name__}"
        )

    orders = data.get("orders", [])
    html_content = "<html><head><meta charset='utf-8'><title>Shopify Orders Test</title></head><body>"
    html_content += f"<h1>Shopify Orders (Last 5) - {shop_domain}</h1>"
    html_content += f"<p>Total orders returned: {len(orders)}</p>"
    html_content += "<table border='1' cellpadding='5' cellspacing='0'>"
    html_content += "<tr><th>Order ID</th><th>Order Name</th><th>Created At</th><th>Financial Status</th><th>Fulfillment Status</th><th>Total Price</th><th>Currency</th></tr>"

    for order in orders:
        order_id = order.get("id", "N/A")
        order_name = order.get("name", "N/A")
        created_at = order.get("created_at", "N/A")
        financial_status = order.get("financial_status", "N/A")
        fulfillment_status = order.get("fulfillment_status", "N/A")
        total_price = order.get("total_price", "N/A")
        currency = order.get("currency", "N/A")

        html_content += f"<tr><td>{order_id}</td><td>{order_name}</td><td>{created_at}</td><td>{financial_status}</td><td>{fulfillment_status}</td><td>{total_price}</td><td>{currency}</td></tr>"

    html_content += "</table>"
    html_content += "</body></html>"

    return HttpResponse(html_content, content_type="text/html; charset=utf-8")


@login_required
def sync_orders(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Only superusers can sync orders.")

    shop_domain = "kidstoylover.myshopify.com"
    try:
        installation = ShopifyInstallation.objects.get(shop=shop_domain)
    except ShopifyInstallation.DoesNotExist:
        return JsonResponse(
            {"error": f"Shopify installation not found for {shop_domain}"},
            status=400,
        )

    access_token = installation.access_token
    api_url = f"https://{shop_domain}/admin/api/2024-01/orders.json?limit=250&status=any"
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as exc:
        return JsonResponse(
            {"error": f"API request failed: {exc.__class__.__name__}"}, status=500
        )

    orders = data.get("orders", [])
    created_count = 0
    updated_count = 0

    for order in orders:
        shopify_order_id = order.get("id")
        if not shopify_order_id:
            continue

        order_name = order.get("name", "")
        created_at = order.get("created_at", "")
        financial_status = order.get("financial_status", "")
        fulfillment_status = order.get("fulfillment_status", "")
        total_price = order.get("total_price", 0)
        currency = order.get("currency", "USD")

        if created_at:
            created_at = datetime.fromisoformat(created_at.replace("Z", "+00:00"))

        obj, created = ShopifyOrder.objects.update_or_create(
            installation=installation,
            shopify_order_id=shopify_order_id,
            defaults={
                "order_name": order_name,
                "created_at": created_at,
                "financial_status": financial_status,
                "fulfillment_status": fulfillment_status,
                "total_price": total_price,
                "currency": currency,
            },
        )

        if created:
            created_count += 1
        else:
            updated_count += 1

    return JsonResponse(
        {
            "success": True,
            "created": created_count,
            "updated": updated_count,
            "total": len(orders),
        }
    )


@login_required
def orders_search(request):
    if not request.user.is_superuser:
        return HttpResponseForbidden("Only superusers can search orders.")

    search_query = request.GET.get("q", "").strip()
    shop_domain = "kidstoylover.myshopify.com"

    try:
        installation = ShopifyInstallation.objects.get(shop=shop_domain)
    except ShopifyInstallation.DoesNotExist:
        html_content = "<html><head><meta charset='utf-8'><title>Order Search</title></head><body>"
        html_content += f"<p>Shopify installation not found for {shop_domain}</p>"
        html_content += "</body></html>"
        return HttpResponse(html_content, content_type="text/html; charset=utf-8")

    if search_query:
        orders = ShopifyOrder.objects.filter(
            installation=installation
        ).filter(
            Q(order_name__icontains=search_query)
            | Q(shopify_order_id__icontains=search_query)
        )
    else:
        orders = ShopifyOrder.objects.filter(installation=installation)[:50]

    html_content = "<html><head><meta charset='utf-8'><title>Order Search</title><style>body { font-family: Arial; } form { margin-bottom: 20px; } table { border-collapse: collapse; } th, td { border: 1px solid #ccc; padding: 8px; text-align: left; } th { background-color: #f2f2f2; }</style></head><body>"
    html_content += "<h1>Order Search</h1>"
    html_content += '<form method="get"><input type="text" name="q" value="%s" placeholder="Search by order name or ID"><button type="submit">Search</button></form>' % (
        search_query or ""
    )
    html_content += f"<p><a href='/auth/shopify/sync-orders'>Sync Orders from Shopify</a></p>"
    html_content += f"<p>Total orders: {orders.count()}</p>"
    html_content += "<table>"
    html_content += "<tr><th>Order Name</th><th>Order ID</th><th>Total Price</th><th>Financial Status</th><th>Fulfillment Status</th><th>Created At</th></tr>"

    for order in orders:
        html_content += f"<tr><td>{order.order_name}</td><td>{order.shopify_order_id}</td><td>{order.total_price} {order.currency}</td><td>{order.financial_status}</td><td>{order.fulfillment_status or 'N/A'}</td><td>{order.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td></tr>"

    html_content += "</table>"
    html_content += "</body></html>"

    return HttpResponse(html_content, content_type="text/html; charset=utf-8")


def _user_has_shopify_sync_access(request):
    if not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    allowed_groups = {"Finance", "Admin", "Shenzhen Warehouse"}
    return bool(set(request.user.groups.values_list("name", flat=True)) & allowed_groups)


def _user_has_review_request_admin_access(request):
    if not request.user.is_authenticated:
        return False
    if request.user.is_superuser:
        return True
    if not request.user.is_staff:
        return False
    return request.user.groups.filter(name="Admin").exists()


def _translation_console_editor_redirect_url(
    request,
    *,
    selected_product_gid: str = "",
    product_search_text: str = "",
    locale: str = "",
    editor_filter: str = "",
    editor_search_query: str = "",
):
    params = {
        "ui_mode": "editor",
        "selected_product_gid": selected_product_gid or "",
        "product_search": product_search_text or "",
        "target_locale": locale or "",
        "editor_filter": editor_filter or "",
        "editor_search": editor_search_query or "",
    }
    return f"{request.path}?{urllib.parse.urlencode(params)}"


@staff_member_required
def review_request_workbench(request):
    if not _user_has_review_request_admin_access(request):
        return HttpResponseForbidden("Only admins can view Review Requests.")
    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()
        if action != "review_send":
            return HttpResponseBadRequest("Unknown Review Request action.")
        result = review_request_review_and_send(
            request.POST.get("candidate_id"),
            admin_username=request.user.get_username(),
            params=request.GET,
        )
        if result.get("email_sent") is True:
            messages.success(
                request,
                "Email sent. Shopify tag write will happen after post-send audit.",
            )
        else:
            messages.warning(
                request,
                result.get("blocking_detail")
                or "No email was sent. This order is not eligible.",
            )
        return HttpResponseRedirect(request.path)
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD", "POST"])

    context = admin.site.each_context(request)
    context.update(build_review_request_workbench_context(request.GET))
    context["title"] = "Review Requests"
    return render(request, "admin/shopify_sync/review_request_workbench.html", context)


@staff_member_required
def translation_console(request):
    post_action = (request.POST.get("action") or "").strip() if request.method == "POST" else ""
    is_refresh_status_post = post_action == "refresh_status"
    is_translation_job_refresh_post = post_action == "refresh_translation_job_status"
    is_safe_write_readiness_package_post = post_action == SAFE_WRITE_READINESS_ACTION_NAME
    is_workspace_locked_execution_post = post_action == LOCKED_EXECUTION_ACTION_NAME
    is_workspace_real_write_post = post_action == REAL_WRITE_ACTION_NAME
    is_selected_translations_real_write_post = (
        post_action == SELECTED_TRANSLATIONS_REAL_WRITE_ACTION_NAME
    )
    is_all_languages_real_write_post = (
        post_action == ALL_LANGUAGES_REAL_WRITE_ACTION_NAME
    )
    is_manual_translation_edit_post = (
        post_action == TRANSLATION_WORKSPACE_MANUAL_EDIT_ACTION_NAME
    )
    is_locked_package_preview_post = post_action in {
        "generate_locked_package_dry_run_placeholder",
        "generate_locked_package_dry_run_preview",
        "generate_locked_package_dry_run_report",
    }
    is_locked_package_report_post = post_action == "generate_locked_package_dry_run_report"
    is_status_only_safe_action_post = (
        is_refresh_status_post
        or is_translation_job_refresh_post
        or is_manual_translation_edit_post
        or is_safe_write_readiness_package_post
        or is_workspace_locked_execution_post
    )
    is_multi_locale_draft_post = post_action == "generate_multi_locale_drafts"
    is_translate_all_post = post_action == TRANSLATE_ALL_ACTION_NAME
    is_retry_failed_language_post = (
        post_action == TRANSLATION_WORKSPACE_RETRY_LOCALE_ACTION_NAME
    )
    is_draft_post = post_action in {
        "generate_missing_translation_drafts",
        "generate_draft_dry_run",
    }
    is_apply_plan_post = post_action == "generate_translation_apply_plan"
    is_final_review_post = post_action == "generate_translation_final_review"
    is_readiness_post = (
        request.method == "POST"
        and post_action == "generate_translation_real_write_readiness"
    )
    is_locked_execution_plan_post = post_action == "generate_translation_locked_execution_plan"
    is_locked_executor_post = post_action == "generate_translation_locked_executor_shell"
    is_real_write_executor_post = post_action == "generate_translation_real_write_executor_dry_run"
    is_real_write_manual_action_package_post = (
        post_action == "generate_translation_real_write_manual_action_package"
    )
    is_post_action = (
        is_draft_post
        or is_multi_locale_draft_post
        or is_translate_all_post
        or is_retry_failed_language_post
        or is_apply_plan_post
        or is_final_review_post
        or is_readiness_post
        or is_locked_execution_plan_post
        or is_locked_executor_post
        or is_real_write_executor_post
        or is_real_write_manual_action_package_post
        or is_safe_write_readiness_package_post
        or is_workspace_locked_execution_post
        or is_workspace_real_write_post
        or is_selected_translations_real_write_post
        or is_all_languages_real_write_post
        or is_manual_translation_edit_post
        or is_status_only_safe_action_post
        or is_locked_package_preview_post
    )
    request_params = request.POST if is_post_action else request.GET
    translation_console_warnings = []
    translation_console_warnings.extend(
        _translation_console_product_gid_conflict_warnings(request, is_post_action)
    )
    product_search_text = _translation_console_request_product_search_text(
        request_params,
        is_post_action=is_post_action,
    )
    raw_product_url_parameter = _translation_console_last_request_value(
        request_params, ("product_gid", "product_id")
    )
    normalized_product_url_parameter = (
        normalize_product_gid(raw_product_url_parameter or "") or ""
    )
    invalid_product_url_parameter = bool(
        raw_product_url_parameter and not normalized_product_url_parameter
    )
    if invalid_product_url_parameter:
        translation_console_warnings.append(
            "The product_gid/product_id URL parameter was not a valid Shopify product gid or numeric product id."
        )
    raw_selected_product_gid = (
        _translation_console_last_request_value(request_params, ("selected_product_gid",))
        or raw_product_url_parameter
    )
    raw_manual_product_gid = _translation_console_last_request_value(
        request_params, ("manual_product_gid",)
    )
    raw_post_product_query = (
        _translation_console_last_request_value(request.POST, ("q",))
        if is_post_action
        else ""
    )
    raw_locale = (
        request_params.get("target_locale", "") or request_params.get("locale", "ja")
    )
    requested_action_locale = _translation_editor_canonical_locale(raw_locale or "ja") or "ja"
    locale = requested_action_locale
    if locale not in SUPPORTED_TRANSLATION_LOCALES:
        translation_console_warnings.append(
            f"Unsupported locale '{raw_locale}' was ignored; using {SUPPORTED_TRANSLATION_LOCALES[0]}."
        )
        locale = SUPPORTED_TRANSLATION_LOCALES[0]
    raw_ui_mode = request_params.get("ui_mode", "") or request_params.get("view_mode", "")
    if raw_ui_mode and raw_ui_mode not in {"workbench", "editor"}:
        translation_console_warnings.append(
            "Unsupported ui_mode was ignored; using editor."
        )
    ui_mode = "workbench" if raw_ui_mode == "workbench" else "editor"
    editor_filter = request_params.get("editor_filter", "").strip()
    if editor_filter not in TRANSLATION_CONSOLE_EDITOR_FILTERS:
        if editor_filter:
            translation_console_warnings.append(
                "Unsupported editor_filter was ignored; using all."
            )
        editor_filter = "all"
    editor_search_query = (
        request_params.get("editor_search", "") or request_params.get("editor_q", "")
    ).strip()
    requested_draft_locales, invalid_draft_locales = _translation_workspace_requested_draft_locales(
        request,
        is_multi_locale_draft_post=is_multi_locale_draft_post,
        is_translate_all_post=is_translate_all_post,
    )
    draft_locale_options = _translation_workspace_draft_locale_options(
        selected_locale=locale,
        requested_locales=(
            requested_draft_locales
            if (is_multi_locale_draft_post or is_translate_all_post)
            else [locale]
        ),
    )
    requested_draft_groups, invalid_draft_groups = _translation_workspace_requested_draft_groups(
        request,
        is_multi_locale_draft_post=is_multi_locale_draft_post,
        is_translate_all_post=is_translate_all_post,
    )
    draft_group_options = _translation_workspace_draft_group_options(
        requested_draft_groups
    )
    product_selector = _build_translation_console_product_selector(
        product_search_text=product_search_text,
        requested_product_gid=(
            "" if invalid_product_url_parameter else raw_selected_product_gid or raw_manual_product_gid
        ),
    )
    product_library_status = _build_translation_console_product_library_status()
    selected_product_gid = product_selector.get("selected_product_gid", "")
    if (
        raw_product_url_parameter
        and normalized_product_url_parameter
        and not product_selector.get("selected_product")
    ):
        translation_console_warnings.append(
            "The requested product is not in the local product selector; Editor View will only show rows if the read-only lookup can find it."
        )
    if invalid_product_url_parameter:
        product_selector = {
            **product_selector,
            "selected_product_gid": "",
            "selected_product": {},
        }
        selected_product_gid = ""
    explicit_selected_product_gid = normalize_product_gid(raw_selected_product_gid or "") or ""
    manual_product_gid = normalize_product_gid(raw_manual_product_gid or "") or ""
    explicit_post_product_gid = normalize_product_gid(raw_post_product_query or "") or ""
    action_product_query = ""
    if is_post_action:
        action_product_query = (
            explicit_selected_product_gid or manual_product_gid or explicit_post_product_gid
        )
    else:
        action_product_query = (
            explicit_selected_product_gid or manual_product_gid or selected_product_gid
        )
    if invalid_product_url_parameter:
        action_product_query = ""
    search_text = action_product_query if is_post_action else product_search_text
    shop_domain = "kidstoylover.myshopify.com"
    result = {
        "shopify_read_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "product": {},
        "search_results": [],
        "translatable_resource": {},
        "translatable_rows": [],
        "locale": locale,
        "search_text": product_search_text,
    }
    error_message = ""
    draft_result = None
    multi_locale_draft_result = None
    translate_all_result = None
    translation_background_job = {}
    translation_report_guard = {
        "selected_product_gid": "",
        "report_product_gid": "",
        "report_visible": False,
        "hidden_previous_report": False,
        "warning": "",
        "empty_message": "Select this product and click Translate all languages.",
    }
    draft_error_message = ""
    apply_plan_result = None
    apply_plan_error_message = ""
    final_review_result = None
    final_review_error_message = ""
    real_write_readiness_result = None
    real_write_readiness_error_message = ""
    locked_execution_plan_result = None
    locked_execution_plan_error_message = ""
    locked_executor_result = None
    locked_executor_error_message = ""
    real_write_executor_result = None
    real_write_executor_error_message = ""
    manual_action_package_result = None
    manual_action_package_error_message = ""
    safe_action_result = None
    apply_plan_preview_result = None
    locked_package_report_result = None
    safe_write_readiness_state = {}
    safe_write_readiness_result = None
    safe_write_readiness_error_message = ""
    selected_translations_apply_state = {}
    selected_translations_apply_result = None
    selected_translations_apply_error_message = ""
    all_languages_update_state = {}
    all_languages_update_result = None
    all_languages_update_error_message = ""
    workspace_locked_execution_result = None
    workspace_locked_execution_error_message = ""
    workspace_real_write_result = None
    workspace_real_write_error_message = ""
    manual_translation_edit_result = None
    workflow_product_id = (
        selected_product_gid
        if selected_product_gid.startswith("gid://shopify/Product/")
        else TRANSLATION_WORKFLOW_DEFAULT_PRODUCT_ID
    )

    should_run_translation_lookup = bool(action_product_query) and (
        (
            request.method == "POST"
            and not is_status_only_safe_action_post
            and not is_translate_all_post
            and not is_retry_failed_language_post
            and not is_workspace_real_write_post
            and not is_selected_translations_real_write_post
            and not is_all_languages_real_write_post
        )
        or request.GET.get("fetch_read_only") == "1"
        or (request.method == "GET" and ui_mode == "editor")
    )

    if should_run_translation_lookup:
        try:
            installation = ShopifyInstallation.objects.first()
            if installation is None:
                error_message = f"Shopify installation not found for {shop_domain}."
            elif is_translate_all_post:
                selected_product_id = _resolve_translation_console_product_id(
                    installation, action_product_query, locale
                )
                if selected_product_id:
                    workflow_product_id = selected_product_id
                    result.update(
                        fetch_translation_console_data(
                            installation, selected_product_id, locale
                        )
                    )
                    translate_all_result = _generate_translation_workspace_translate_all_drafts(
                        installation=installation,
                        product_id=selected_product_id,
                        selected_locale=locale,
                        product_search_text=product_search_text,
                        editor_filter=editor_filter,
                        editor_search_query=editor_search_query,
                    )
                    draft_result = translate_all_result.get("draft_result")
                    if translate_all_result.get("blocking_conditions"):
                        draft_error_message = translate_all_result["message"]
                    safe_action_result = _translation_console_safe_action_result(
                        action=post_action,
                        action_status=translate_all_result["action_status"],
                        message=translate_all_result["message"],
                        summary=_translation_workspace_translate_all_safe_summary(
                            translate_all_result
                        ),
                    )
                else:
                    translate_all_result = _translation_workspace_empty_translate_all_result(
                        product_id=action_product_query,
                        selected_locale=locale,
                        message="Select one product before translating all languages.",
                        blocking_conditions=["missing_selected_product"],
                    )
                    draft_error_message = translate_all_result["message"]
                    safe_action_result = _translation_console_safe_action_result(
                        action=post_action,
                        action_status=translate_all_result["action_status"],
                        message=translate_all_result["message"],
                        summary=_translation_workspace_translate_all_safe_summary(
                            translate_all_result
                        ),
                    )
            elif is_multi_locale_draft_post:
                if not requested_draft_locales or not requested_draft_groups:
                    multi_locale_draft_result = _translation_workspace_empty_multi_locale_result(
                        product_id=action_product_query,
                        selected_locale=locale,
                        requested_locales=requested_draft_locales,
                        invalid_locales=invalid_draft_locales,
                        requested_groups=requested_draft_groups,
                        invalid_groups=invalid_draft_groups,
                    )
                    draft_error_message = multi_locale_draft_result["message"]
                    safe_action_result = _translation_console_safe_action_result(
                        action=post_action,
                        action_status=multi_locale_draft_result["action_status"],
                        message=multi_locale_draft_result["message"],
                        summary=multi_locale_draft_result["summary"],
                    )
                else:
                    selected_product_id = _resolve_translation_console_product_id(
                        installation, action_product_query, locale
                    )
                    if selected_product_id:
                        workflow_product_id = selected_product_id
                        result.update(
                            fetch_translation_console_data(
                                installation, selected_product_id, locale
                            )
                        )
                        multi_locale_draft_result = _generate_translation_workspace_multi_locale_drafts(
                            installation=installation,
                            product_id=selected_product_id,
                            selected_locale=locale,
                            target_locales=requested_draft_locales,
                            invalid_locales=invalid_draft_locales,
                            draft_groups=requested_draft_groups,
                            invalid_groups=invalid_draft_groups,
                            product_search_text=product_search_text,
                            editor_filter=editor_filter,
                            editor_search_query=editor_search_query,
                        )
                        draft_result = multi_locale_draft_result.get(
                            "selected_locale_draft_result"
                        )
                        if multi_locale_draft_result.get("blocking_conditions"):
                            draft_error_message = multi_locale_draft_result["message"]
                        safe_action_result = _translation_console_safe_action_result(
                            action=post_action,
                            action_status=multi_locale_draft_result["action_status"],
                            message=multi_locale_draft_result["message"],
                            summary=multi_locale_draft_result["summary"],
                        )
                    else:
                        blocked_message = (
                            _translation_workspace_multi_locale_blocked_message(
                                has_product=False,
                                requested_locales=requested_draft_locales,
                                invalid_locales=invalid_draft_locales,
                                requested_groups=requested_draft_groups,
                                invalid_groups=invalid_draft_groups,
                            )
                        )
                        multi_locale_draft_result = _translation_workspace_empty_multi_locale_result(
                            product_id=action_product_query,
                            selected_locale=locale,
                            requested_locales=requested_draft_locales,
                            invalid_locales=invalid_draft_locales,
                            requested_groups=requested_draft_groups,
                            invalid_groups=invalid_draft_groups,
                            message=blocked_message,
                            action_status="multi_locale_draft_blocked",
                            blocking_conditions=["missing_selected_product"],
                        )
                        draft_error_message = multi_locale_draft_result["message"]
                        safe_action_result = _translation_console_safe_action_result(
                            action=post_action,
                            action_status=multi_locale_draft_result["action_status"],
                            message=multi_locale_draft_result["message"],
                            summary=multi_locale_draft_result["summary"],
                        )
            elif (
                is_draft_post
                or is_locked_package_preview_post
                or is_apply_plan_post
                or is_final_review_post
                or is_readiness_post
                or is_locked_execution_plan_post
                or is_locked_executor_post
                or is_real_write_executor_post
                or is_real_write_manual_action_package_post
            ):
                selected_product_id = _resolve_translation_console_product_id(
                    installation, action_product_query, locale
                )
                if selected_product_id:
                    workflow_product_id = selected_product_id
                    result.update(fetch_translation_console_data(installation, selected_product_id, locale))
                if selected_product_id:
                    draft_result = generate_selected_product_missing_translation_draft_package(
                        product_id=selected_product_id,
                        target_locales=TRANSLATION_DRAFT_TARGET_LOCALES,
                        fields=TRANSLATION_DRAFT_FIELDS,
                        installation=installation,
                    )
                    _attach_translation_console_draft_detail(draft_result)
                    if draft_result.get("blocking_conditions"):
                        draft_error_message = (
                            "Translation blocked: "
                            + ", ".join(draft_result.get("blocking_conditions") or [])
                        )
                    if post_action == "generate_draft_dry_run":
                        safe_action_result = _translation_console_safe_action_result(
                            action=post_action,
                            action_status=(
                                "draft_dry_run_blocked"
                                if draft_result.get("blocking_conditions")
                                else "draft_dry_run_completed"
                            ),
                            message=(
                                "Draft dry-run completed without Shopify writes."
                                if not draft_result.get("blocking_conditions")
                                else "Draft dry-run stayed no-write but has blocking conditions."
                            ),
                            summary=_translation_console_draft_summary(draft_result),
                        )
                    apply_plan_preview_result = build_apply_plan_preview_from_draft_result(
                        draft_result
                    )
                    if is_locked_package_preview_post:
                        if is_locked_package_report_post:
                            if apply_plan_preview_result.get("apply_plan_candidate_count"):
                                locked_package_report_result = (
                                    generate_translation_console_locked_package_dry_run_report(
                                        apply_plan_preview_result
                                    )
                                )
                            else:
                                locked_package_report_result = (
                                    _empty_locked_package_report_result(
                                        "no_apply_plan_preview_candidates"
                                    )
                                )
                        safe_action_result = _translation_console_safe_action_result(
                            action=post_action,
                            action_status=(
                                locked_package_report_result.get("report_status")
                                if locked_package_report_result
                                else apply_plan_preview_result.get(
                                    "preview_status", "apply_plan_preview_ready"
                                )
                            ),
                            message=(
                                "Locked package dry-run report generated only. No Shopify write performed."
                                if locked_package_report_result
                                and locked_package_report_result.get("json_report_path")
                                else (
                                    "Locked package / apply-plan preview generated in memory only."
                                    if not apply_plan_preview_result.get("blocking_conditions")
                                    else "Locked package / apply-plan preview stayed no-write but needs review."
                                )
                            ),
                            summary={
                                "apply_plan_candidate_count": apply_plan_preview_result.get(
                                    "apply_plan_candidate_count", 0
                                ),
                                "blocked_or_needs_review_count": apply_plan_preview_result.get(
                                    "blocked_or_needs_review_count", 0
                                ),
                                "blocking_conditions": (
                                    locked_package_report_result.get(
                                        "blocking_conditions", []
                                    )
                                    if locked_package_report_result
                                    else apply_plan_preview_result.get(
                                        "blocking_conditions", []
                                    )
                                ),
                                "report_status": (
                                    locked_package_report_result.get("report_status")
                                    if locked_package_report_result
                                    else ""
                                ),
                                "json_report_path": (
                                    locked_package_report_result.get("json_report_path")
                                    if locked_package_report_result
                                    else ""
                                ),
                                "html_report_path": (
                                    locked_package_report_result.get("html_report_path")
                                    if locked_package_report_result
                                    else ""
                                ),
                                "preview_only": True,
                            },
                        )
                    if (
                        is_apply_plan_post
                        or is_final_review_post
                        or is_readiness_post
                        or is_locked_execution_plan_post
                        or is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        apply_plan_result = build_selected_product_translation_apply_plan(draft_result)
                        if apply_plan_result.get("blocking_conditions"):
                            apply_plan_error_message = (
                                "Apply plan generation blocked: "
                                + ", ".join(apply_plan_result.get("blocking_conditions") or [])
                            )
                    if (
                        is_final_review_post
                        or is_readiness_post
                        or is_locked_execution_plan_post
                        or is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        final_review_result = build_selected_product_translation_final_review(apply_plan_result)
                        if final_review_result.get("blocking_conditions"):
                            final_review_error_message = (
                                "Final review generation blocked: "
                                + ", ".join(final_review_result.get("blocking_conditions") or [])
                            )
                    if (
                        is_readiness_post
                        or is_locked_execution_plan_post
                        or is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        real_write_readiness_result = (
                            build_selected_product_translation_real_write_readiness(final_review_result)
                        )
                        if real_write_readiness_result.get("blocking_conditions"):
                            real_write_readiness_error_message = (
                                "Real write readiness generation blocked: "
                                + ", ".join(
                                    real_write_readiness_result.get("blocking_conditions") or []
                                )
                            )
                    if (
                        is_locked_execution_plan_post
                        or is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        locked_execution_plan_result = (
                            build_selected_product_translation_locked_execution_plan(
                                real_write_readiness_result
                            )
                        )
                        if locked_execution_plan_result.get("blocking_conditions"):
                            locked_execution_plan_error_message = (
                                "Locked execution plan generation blocked: "
                                + ", ".join(
                                    locked_execution_plan_result.get("blocking_conditions")
                                    or []
                                )
                            )
                    if (
                        is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        locked_executor_result = (
                            build_selected_product_translation_locked_executor_shell(
                                locked_execution_plan_result,
                                ack_preview_text=request.POST.get("manual_ack_preview", ""),
                            )
                        )
                        if locked_executor_result.get("blocking_conditions"):
                            locked_executor_error_message = (
                                "Locked executor shell generation blocked: "
                                + ", ".join(
                                    locked_executor_result.get("blocking_conditions") or []
                                )
                            )
                    if is_real_write_executor_post or is_real_write_manual_action_package_post:
                        real_write_executor_result = (
                            build_selected_product_translation_real_write_executor_dry_run(
                                locked_executor_result,
                                selected_product_id=selected_product_id,
                                manual_ack_text=request.POST.get("real_write_manual_ack", ""),
                            )
                        )
                        if real_write_executor_result.get("blocking_conditions"):
                            real_write_executor_error_message = (
                                "Real write executor dry-run blocked: "
                                + ", ".join(
                                    real_write_executor_result.get("blocking_conditions") or []
                                )
                            )
                    if is_real_write_manual_action_package_post:
                        manual_action_package_result = (
                            build_selected_product_translation_real_write_manual_action_package(
                                real_write_executor_result,
                                selected_product_id=selected_product_id,
                            )
                        )
                        if manual_action_package_result.get("blocking_conditions"):
                            manual_action_package_error_message = (
                                "Real write manual action package blocked: "
                                + ", ".join(
                                    manual_action_package_result.get("blocking_conditions")
                                    or []
                                )
                            )
                else:
                    draft_error_message = "Select a single Shopify product before translating."
                    if post_action == "generate_draft_dry_run":
                        safe_action_result = _translation_console_safe_action_result(
                            action=post_action,
                            action_status="draft_dry_run_blocked",
                            message="Select a single Shopify product before running the translation dry-run package.",
                            summary={"blocking_conditions": ["missing_selected_product"]},
                        )
                    if is_locked_package_preview_post:
                        apply_plan_preview_result = _empty_apply_plan_preview_result(
                            "generate_draft_dry_run_first"
                        )
                        if is_locked_package_report_post:
                            locked_package_report_result = (
                                _empty_locked_package_report_result(
                                    "generate_draft_dry_run_first"
                                )
                            )
                        safe_action_result = _translation_console_safe_action_result(
                            action=post_action,
                            action_status=(
                                locked_package_report_result.get("report_status")
                                if locked_package_report_result
                                else apply_plan_preview_result["preview_status"]
                            ),
                            message="Generate draft dry-run first.",
                            summary={
                                "blocking_conditions": apply_plan_preview_result.get(
                                    "blocking_conditions", []
                                ),
                                "report_status": (
                                    locked_package_report_result.get("report_status")
                                    if locked_package_report_result
                                    else ""
                                ),
                                "preview_only": True,
                            },
                        )
                    if (
                        is_apply_plan_post
                        or is_readiness_post
                        or is_locked_execution_plan_post
                        or is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        apply_plan_error_message = "Select a single Shopify product before generating an apply plan."
                    if (
                        is_final_review_post
                        or is_readiness_post
                        or is_locked_execution_plan_post
                        or is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        final_review_error_message = "Select a single Shopify product before generating a final review."
                    if (
                        is_readiness_post
                        or is_locked_execution_plan_post
                        or is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        real_write_readiness_error_message = (
                            "Select a single Shopify product before generating a real write readiness package."
                        )
                    if (
                        is_locked_execution_plan_post
                        or is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        locked_execution_plan_error_message = (
                            "Select a single Shopify product before generating a locked execution plan."
                        )
                    if (
                        is_locked_executor_post
                        or is_real_write_executor_post
                        or is_real_write_manual_action_package_post
                    ):
                        locked_executor_error_message = (
                            "Select a single Shopify product before generating a locked executor shell."
                        )
                    if is_real_write_executor_post or is_real_write_manual_action_package_post:
                        real_write_executor_error_message = (
                            "Select a single Shopify product before generating a real write executor dry-run package."
                        )
                    if is_real_write_manual_action_package_post:
                        manual_action_package_error_message = (
                            "Select a single Shopify product before generating a real write manual action package."
                        )
            else:
                result.update(fetch_translation_console_data(installation, action_product_query, locale))
                product = result.get("product") or {}
                if product.get("id"):
                    workflow_product_id = product["id"]
        except ShopifyInstallation.DoesNotExist:
            error_message = f"Shopify installation not found for {shop_domain}."
        except (ShopifyTranslationConsoleError, requests.RequestException, ValueError) as exc:
            error_message = safe_translation_console_error_message(exc)

    workflow_status = load_translation_workflow_status(workflow_product_id)
    translation_job_product_id = (
        normalize_product_gid(action_product_query or selected_product_gid or "") or ""
    )
    translation_background_job = load_translation_workspace_background_job_status(
        translation_job_product_id
    )
    translation_report_guard = _translation_workspace_report_guard(
        translation_background_job,
        selected_product_gid=translation_job_product_id,
    )
    if translation_report_guard["hidden_previous_report"]:
        translation_background_job = {}
    if is_manual_translation_edit_post:
        manual_translation_edit_result = save_translation_workspace_manual_edit(
            product_gid=translation_job_product_id,
            job_id=request.POST.get("translation_job_id", ""),
            entry_id=request.POST.get("manual_edit_entry_id", ""),
            edited_value=request.POST.get("manual_edit_value", ""),
        )
        translation_background_job = load_translation_workspace_background_job_status(
            translation_job_product_id
        )
        translation_report_guard = _translation_workspace_report_guard(
            translation_background_job,
            selected_product_gid=translation_job_product_id,
        )
        if translation_report_guard["hidden_previous_report"]:
            translation_background_job = {}
    safe_write_readiness_state = build_translation_workspace_safe_write_readiness_state(
        translation_background_job,
        selected_product_gid=translation_job_product_id,
        selected_locale=locale,
    )
    selected_apply_locale = (
        requested_action_locale
        if is_selected_translations_real_write_post
        else locale
    )
    selected_translations_apply_state = build_translation_workspace_selected_apply_state(
        translation_background_job,
        selected_product_gid=translation_job_product_id,
        selected_locale=selected_apply_locale,
    )
    all_languages_update_state = build_translation_workspace_all_languages_update_state(
        translation_background_job,
        selected_product_gid=translation_job_product_id,
    )
    _attach_translation_workspace_safe_write_ui(
        translation_background_job,
        safe_write_readiness_state,
        selected_translations_apply_state,
    )
    if is_manual_translation_edit_post:
        blocking_conditions = list(
            (manual_translation_edit_result or {}).get("blocking_conditions") or []
        )
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status=(
                (manual_translation_edit_result or {}).get("edit_status")
                or "manual_translation_edit_blocked"
            ),
            message=(
                "Manual translation edit saved locally. Shopify was not updated."
                if not blocking_conditions
                else "Manual translation edit was not saved. No Shopify write performed."
            ),
            summary={
                "product_gid": (manual_translation_edit_result or {}).get(
                    "product_gid", ""
                ),
                "job_id": (manual_translation_edit_result or {}).get("job_id", ""),
                "entry_id": (manual_translation_edit_result or {}).get(
                    "entry_id", ""
                ),
                "locale": (manual_translation_edit_result or {}).get("locale", ""),
                "field": (manual_translation_edit_result or {}).get("field", ""),
                "using_manual_edit": (manual_translation_edit_result or {}).get(
                    "using_manual_edit", False
                ),
                "validation_status": (manual_translation_edit_result or {}).get(
                    "validation_status", ""
                ),
                "seo_validation_status": (manual_translation_edit_result or {}).get(
                    "seo_validation_status", ""
                ),
                "blocking_conditions": blocking_conditions,
                "report_path": (manual_translation_edit_result or {}).get(
                    "report_path", ""
                ),
                "shopify_write_performed": False,
                "mutation_performed": False,
                "translations_register_called": False,
            },
        )
    elif is_refresh_status_post:
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status="workflow_status_refreshed",
            message="Workflow status refreshed from local audit reports only.",
            summary={
                "workflow_status": workflow_status.get("workflow_status"),
                "latest_audit_report_filename": workflow_status.get(
                    "latest_audit_report_filename"
                ),
                "latest_audit_report_source": workflow_status.get(
                    "latest_audit_report_source"
                ),
                "workflow_status_loaded_at": workflow_status.get(
                    "workflow_status_loaded_at"
                ),
            },
        )
    elif is_translation_job_refresh_post:
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status="translation_draft_job_status_refreshed",
            message="Translation status refreshed from the local report only.",
            summary=_translation_workspace_job_safe_summary(
                translation_background_job
            ),
        )
    elif is_safe_write_readiness_package_post:
        selected_entry_ids = request.POST.getlist("safe_write_entry_ids")
        safe_write_readiness_result = (
            build_translation_workspace_safe_write_readiness_package(
                translation_background_job,
                selected_product_gid=translation_job_product_id,
                selected_locale=locale,
                selected_entry_ids=selected_entry_ids,
            )
        )
        if safe_write_readiness_result.get("blocking_conditions"):
            safe_write_readiness_error_message = (
                "Safe write readiness package blocked: "
                + ", ".join(safe_write_readiness_result.get("blocking_conditions") or [])
            )
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status=safe_write_readiness_result.get("package_status", ""),
            message=(
                "Safe write-readiness package generated locally. No Shopify write performed."
                if safe_write_readiness_result.get("package_status")
                == "write_readiness_ready"
                else "Safe write-readiness package stayed no-write and is blocked for review."
            ),
            summary={
                "product_gid": safe_write_readiness_result.get("product_gid", ""),
                "locale": safe_write_readiness_result.get("locale", ""),
                "selected_entry_count": safe_write_readiness_result.get(
                    "selected_entry_count", 0
                ),
                "max_entry_count": safe_write_readiness_result.get(
                    "max_entry_count", 3
                ),
                "json_report_path": safe_write_readiness_result.get(
                    "json_report_path", ""
                ),
                "html_report_path": safe_write_readiness_result.get(
                    "html_report_path", ""
                ),
                "blocking_conditions": safe_write_readiness_result.get(
                    "blocking_conditions", []
                ),
                "shopify_write_performed": False,
                "mutation_performed": False,
                "translations_register_called": False,
            },
        )
    elif is_workspace_locked_execution_post:
        selected_entry_ids = request.POST.getlist("safe_write_entry_ids")
        safe_write_readiness_result = (
            build_translation_workspace_safe_write_readiness_package(
                translation_background_job,
                selected_product_gid=translation_job_product_id,
                selected_locale=locale,
                selected_entry_ids=selected_entry_ids,
            )
        )
        if safe_write_readiness_result.get("blocking_conditions"):
            safe_write_readiness_error_message = (
                "Safe write readiness package blocked before locked preparation: "
                + ", ".join(safe_write_readiness_result.get("blocking_conditions") or [])
            )
        workspace_locked_execution_result = (
            build_translation_workspace_locked_execution_package(
                safe_write_readiness_result,
                latest_background_report=translation_background_job,
                selected_product_gid=translation_job_product_id,
                selected_locale=locale,
                selected_entry_ids=selected_entry_ids,
                ack_preview_text=request.POST.get("locked_execution_ack_preview", ""),
            )
        )
        if workspace_locked_execution_result.get("blocking_conditions"):
            workspace_locked_execution_error_message = (
                "Locked Shopify update preparation blocked: "
                + ", ".join(
                    workspace_locked_execution_result.get("blocking_conditions") or []
                )
            )
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status=workspace_locked_execution_result.get("package_status", ""),
            message=(
                "Locked Shopify update preparation generated locally. Shopify was not updated."
                if workspace_locked_execution_result.get("package_status")
                == "locked_execution_ready_for_manual_ack"
                else "Locked Shopify update preparation stayed no-write and is blocked for review."
            ),
            summary={
                "product_gid": workspace_locked_execution_result.get("product_gid", ""),
                "locale": workspace_locked_execution_result.get("locale", ""),
                "key": workspace_locked_execution_result.get("key", ""),
                "selected_entry_count": workspace_locked_execution_result.get(
                    "selected_entry_count", 0
                ),
                "package_status": workspace_locked_execution_result.get(
                    "package_status", ""
                ),
                "json_report_path": workspace_locked_execution_result.get(
                    "json_report_path", ""
                ),
                "html_report_path": workspace_locked_execution_result.get(
                    "html_report_path", ""
                ),
                "blocking_conditions": workspace_locked_execution_result.get(
                    "blocking_conditions", []
                ),
                "manual_ack_phrase_required": workspace_locked_execution_result.get(
                    "manual_ack_phrase_required", ""
                ),
                "manual_ack_effective": False,
                "shopify_write_performed": False,
                "mutation_performed": False,
                "translations_register_called": False,
            },
        )
    elif is_workspace_real_write_post:
        locked_package_path = request.POST.get("locked_execution_package_path", "")
        locked_package, load_blockers, resolved_locked_package_path = (
            load_translation_workspace_locked_execution_package(locked_package_path)
        )
        installation = ShopifyInstallation.objects.first()
        workspace_real_write_result = execute_translation_workspace_single_locked_write(
            locked_package,
            installation=installation,
            locked_package_path=resolved_locked_package_path or locked_package_path,
            selected_entry_id=request.POST.get("selected_entry_id", ""),
            selected_entry_checksum=request.POST.get("selected_entry_checksum", ""),
            manual_ack_text=request.POST.get("real_write_manual_ack", ""),
            load_blocking_conditions=load_blockers,
        )
        if workspace_real_write_result.get("blocking_conditions"):
            workspace_real_write_error_message = (
                "Real Shopify update blocked: "
                + ", ".join(workspace_real_write_result.get("blocking_conditions") or [])
            )
        real_write_status = workspace_real_write_result.get("execution_status", "")
        if real_write_status == "write_audit_passed":
            real_write_message = (
                "One Shopify translation was updated and the immediate readback audit passed."
            )
        elif real_write_status == "write_audit_failed":
            real_write_message = (
                "One Shopify translation update ran, but the readback audit did not confirm the expected value."
            )
        elif real_write_status == "write_mutation_failed":
            real_write_message = (
                "translationsRegister was called for one translation but returned a failure. No rollback was run."
            )
        else:
            real_write_message = (
                "Real Shopify update blocked before any mutation. No Shopify write was performed."
            )
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status=real_write_status,
            message=real_write_message,
            summary={
                "product_gid": workspace_real_write_result.get("product_gid", ""),
                "locale": workspace_real_write_result.get("locale", ""),
                "key": workspace_real_write_result.get("key", ""),
                "resource_id": workspace_real_write_result.get("resource_id", ""),
                "ack_matched": workspace_real_write_result.get("ack_matched", False),
                "mutation_called": workspace_real_write_result.get(
                    "mutation_called", False
                ),
                "translations_register_called": workspace_real_write_result.get(
                    "translations_register_called", False
                ),
                "shopify_write_performed": workspace_real_write_result.get(
                    "shopify_write_performed", False
                ),
                "readback_performed": workspace_real_write_result.get(
                    "readback_performed", False
                ),
                "readback_matched": workspace_real_write_result.get(
                    "readback_matched", False
                ),
                "rollback_needed": workspace_real_write_result.get(
                    "rollback_needed", False
                ),
                "json_report_path": workspace_real_write_result.get(
                    "json_report_path", ""
                ),
                "html_report_path": workspace_real_write_result.get(
                    "html_report_path", ""
                ),
                "blocking_conditions": workspace_real_write_result.get(
                    "blocking_conditions", []
                ),
            },
        )
        mutation_called = workspace_real_write_result.get("mutation_called", False)
        safe_action_result.update(
            {
                "read_only": not mutation_called,
                "no_write_from_page": not mutation_called,
                "shopify_write_performed": workspace_real_write_result.get(
                    "shopify_write_performed", False
                ),
                "mutation_performed": workspace_real_write_result.get(
                    "mutation_performed", False
                ),
                "translations_register_called": workspace_real_write_result.get(
                    "translations_register_called", False
                ),
                "rollback_performed": False,
                "publish_performed": False,
                "apply_performed": False,
                "real_apply_performed": workspace_real_write_result.get(
                    "real_apply_performed", False
                ),
            }
        )
    elif is_selected_translations_real_write_post:
        selected_entry_ids = (
            request.POST.getlist("selected_shopify_entry_ids")
            + request.POST.getlist("safe_write_entry_ids")
        )
        installation = ShopifyInstallation.objects.first()
        selected_translations_apply_result = apply_selected_translations_to_shopify(
            translation_background_job,
            installation=installation,
            selected_product_gid=translation_job_product_id,
            selected_locale=selected_apply_locale,
            selected_entry_ids=selected_entry_ids,
            manual_ack_text=request.POST.get("selected_shopify_apply_ack", ""),
        )
        if selected_translations_apply_result.get("blocking_conditions"):
            selected_translations_apply_error_message = (
                "Selected Shopify translation update blocked: "
                + ", ".join(
                    selected_translations_apply_result.get("blocking_conditions") or []
                )
            )
        selected_translations_apply_state = selected_translations_apply_result
        apply_status = selected_translations_apply_result.get("status", "")
        if apply_status == "selected_shopify_translations_written_and_verified":
            apply_message = (
                "Shopify update completed. Selected translations were written and verified."
            )
        elif apply_status == "selected_shopify_translations_write_partial":
            apply_message = (
                "Shopify was updated, but one or more selected translations failed readback verification."
            )
        elif apply_status == "selected_shopify_translations_write_failed":
            apply_message = (
                "Selected Shopify translation update failed. No automatic rollback was run."
            )
        else:
            apply_message = (
                "Selected Shopify translation update blocked before any mutation. No Shopify write was performed."
            )
        mutation_called = selected_translations_apply_result.get(
            "mutation_called",
            False,
        )
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status=apply_status,
            message=apply_message,
            summary={
                "product_gid": selected_translations_apply_result.get(
                    "product_gid",
                    "",
                ),
                "product_title": selected_translations_apply_result.get(
                    "product_title",
                    "",
                ),
                "locale": selected_translations_apply_result.get("locale", ""),
                "selected_entry_count": selected_translations_apply_result.get(
                    "selected_entry_count",
                    0,
                ),
                "selected_fields": selected_translations_apply_result.get(
                    "selected_fields",
                    [],
                ),
                "ack_matched": selected_translations_apply_result.get(
                    "ack_matched",
                    False,
                ),
                "mutation_called": selected_translations_apply_result.get(
                    "mutation_called",
                    False,
                ),
                "translations_register_called": selected_translations_apply_result.get(
                    "translations_register_called",
                    False,
                ),
                "shopify_write_performed": selected_translations_apply_result.get(
                    "shopify_write_performed",
                    False,
                ),
                "readback_performed": selected_translations_apply_result.get(
                    "readback_performed",
                    False,
                ),
                "readback_verified_count": selected_translations_apply_result.get(
                    "readback_verified_count",
                    0,
                ),
                "readback_failed_count": selected_translations_apply_result.get(
                    "readback_failed_count",
                    0,
                ),
                "rollback_needed": selected_translations_apply_result.get(
                    "rollback_needed",
                    False,
                ),
                "json_report_path": selected_translations_apply_result.get(
                    "json_report_path",
                    "",
                ),
                "html_report_path": selected_translations_apply_result.get(
                    "html_report_path",
                    "",
                ),
                "blocking_conditions": selected_translations_apply_result.get(
                    "blocking_conditions",
                    [],
                ),
            },
        )
        safe_action_result.update(
            {
                "read_only": not mutation_called,
                "no_write_from_page": not mutation_called,
                "shopify_write_performed": selected_translations_apply_result.get(
                    "shopify_write_performed",
                    False,
                ),
                "mutation_performed": selected_translations_apply_result.get(
                    "mutation_performed",
                    False,
                ),
                "translations_register_called": selected_translations_apply_result.get(
                    "translations_register_called",
                    False,
                ),
                "rollback_performed": False,
                "publish_performed": False,
                "apply_performed": False,
                "real_apply_performed": selected_translations_apply_result.get(
                    "real_apply_performed",
                    False,
                ),
            }
        )
    elif is_all_languages_real_write_post:
        installation = ShopifyInstallation.objects.first()
        all_languages_update_result = validate_and_update_all_languages_to_shopify(
            translation_background_job,
            installation=installation,
            selected_product_gid=translation_job_product_id,
        )
        if all_languages_update_result.get("blocking_conditions"):
            reason_summary = all_languages_update_result.get("blocked_reason_summary") or []
            first_reason = (
                reason_summary[0].get("label", "")
                if reason_summary and isinstance(reason_summary[0], dict)
                else ""
            )
            all_languages_update_error_message = (
                all_languages_update_result.get("result_message")
                or first_reason
                or "No translations were updated."
            )
        all_languages_update_state = all_languages_update_result
        update_status = all_languages_update_result.get("status", "")
        update_message = all_languages_update_result.get("result_message") or (
            "Shopify updated successfully. All updated fields were confirmed."
            if update_status
            == "all_languages_shopify_translations_written_and_verified"
            else "No translations were updated. The system did not find any safe fields to update."
        )
        mutation_called = all_languages_update_result.get("mutation_called", False)
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status=update_status,
            message=update_message,
            summary={
                "product_gid": all_languages_update_result.get("product_gid", ""),
                "product_title": all_languages_update_result.get("product_title", ""),
                "locales": all_languages_update_result.get("locales", []),
                "candidate_count": all_languages_update_result.get(
                    "candidate_count",
                    0,
                ),
                "write_ready_count": all_languages_update_result.get(
                    "write_ready_count",
                    0,
                ),
                "updated_count": all_languages_update_result.get("updated_count", 0),
                "verified_count": all_languages_update_result.get("verified_count", 0),
                "skipped_count": all_languages_update_result.get("skipped_count", 0),
                "blocked_count": all_languages_update_result.get("blocked_count", 0),
                "review_note_count": all_languages_update_result.get(
                    "review_note_count",
                    0,
                ),
                "failed_count": all_languages_update_result.get("failed_count", 0),
                "status_label": all_languages_update_result.get("status_label", ""),
                "result_message": all_languages_update_result.get("result_message", ""),
                "shopify_update_label": all_languages_update_result.get(
                    "shopify_update_label",
                    "",
                ),
                "safe_field_diagnostic_summary": all_languages_update_result.get(
                    "safe_field_diagnostic_summary",
                    {},
                ),
                "safe_field_diagnostics": all_languages_update_result.get(
                    "safe_field_diagnostics",
                    [],
                ),
                "blocked_reason_summary": all_languages_update_result.get(
                    "blocked_reason_summary",
                    [],
                ),
                "mutation_called": all_languages_update_result.get(
                    "mutation_called",
                    False,
                ),
                "translations_register_called": all_languages_update_result.get(
                    "translations_register_called",
                    False,
                ),
                "shopify_write_performed": all_languages_update_result.get(
                    "shopify_write_performed",
                    False,
                ),
                "readback_performed": all_languages_update_result.get(
                    "readback_performed",
                    False,
                ),
                "rollback_needed": all_languages_update_result.get(
                    "rollback_needed",
                    False,
                ),
                "json_report_path": all_languages_update_result.get(
                    "json_report_path",
                    "",
                ),
                "html_report_path": all_languages_update_result.get(
                    "html_report_path",
                    "",
                ),
                "blocking_conditions": all_languages_update_result.get(
                    "blocking_conditions",
                    [],
                ),
            },
        )
        safe_action_result.update(
            {
                "read_only": not mutation_called,
                "no_write_from_page": not mutation_called,
                "shopify_write_performed": all_languages_update_result.get(
                    "shopify_write_performed",
                    False,
                ),
                "mutation_performed": all_languages_update_result.get(
                    "mutation_performed",
                    False,
                ),
                "translations_register_called": all_languages_update_result.get(
                    "translations_register_called",
                    False,
                ),
                "rollback_performed": False,
                "publish_performed": False,
                "apply_performed": False,
                "real_apply_performed": all_languages_update_result.get(
                    "real_apply_performed",
                    False,
                ),
            }
        )
    elif is_locked_package_preview_post and safe_action_result is None:
        apply_plan_preview_result = _empty_apply_plan_preview_result(
            "generate_draft_dry_run_first"
        )
        if is_locked_package_report_post:
            locked_package_report_result = _empty_locked_package_report_result(
                "generate_draft_dry_run_first"
            )
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status=(
                locked_package_report_result.get("report_status")
                if locked_package_report_result
                else apply_plan_preview_result["preview_status"]
            ),
            message="Generate draft dry-run first.",
            summary={
                "workflow_status": workflow_status.get("workflow_status"),
                "blocking_conditions": apply_plan_preview_result.get(
                    "blocking_conditions", []
                ),
                "report_status": (
                    locked_package_report_result.get("report_status")
                    if locked_package_report_result
                    else ""
                ),
                "preview_only": True,
            },
        )
    elif post_action == TRANSLATE_ALL_ACTION_NAME and safe_action_result is None:
        selected_background_product_gid = normalize_product_gid(
            action_product_query or selected_product_gid or ""
        ) or ""
        if not selected_background_product_gid:
            translate_all_result = _translation_workspace_empty_translate_all_result(
                product_id=action_product_query,
                selected_locale=locale,
                message="Select one product before starting background translation.",
                blocking_conditions=["missing_selected_product"],
            )
            safe_action_result = _translation_console_safe_action_result(
                action=post_action,
                action_status="translation_draft_job_blocked",
                message=translate_all_result["message"],
                summary=_translation_workspace_translate_all_safe_summary(
                    translate_all_result
                ),
            )
        else:
            installation = ShopifyInstallation.objects.first()
            if installation is None:
                safe_action_result = _translation_console_safe_action_result(
                    action=post_action,
                    action_status="translation_draft_job_blocked",
                    message=f"Shopify installation not found for {shop_domain}.",
                    summary={
                        "blocking_conditions": ["missing_shopify_installation"],
                        "shopify_write_performed": False,
                        "mutation_performed": False,
                        "translations_register_called": False,
                    },
                )
            else:
                start_result = start_translation_workspace_background_job(
                    installation_id=installation.pk,
                    product_gid=selected_background_product_gid,
                    product_title=(
                        (product_selector.get("selected_product") or {}).get("title", "")
                    ),
                    product_search_text=product_search_text,
                    selected_locale=locale,
                    editor_filter=editor_filter,
                    editor_search_query=editor_search_query,
                )
                translation_background_job = start_result["job_status"]
                safe_action_result = _translation_console_safe_action_result(
                    action=post_action,
                    action_status=start_result["action_status"],
                    message=start_result["message"],
                    summary=_translation_workspace_job_safe_summary(
                        translation_background_job
                    ),
                )
                return HttpResponseRedirect(
                    _translation_console_editor_redirect_url(
                        request,
                        selected_product_gid=selected_background_product_gid,
                        product_search_text=product_search_text,
                        locale=locale,
                        editor_filter=editor_filter,
                        editor_search_query=editor_search_query,
                    )
                )
    elif is_retry_failed_language_post and safe_action_result is None:
        selected_background_product_gid = normalize_product_gid(
            action_product_query or selected_product_gid or ""
        ) or ""
        retry_locale = locale if locale in SUPPORTED_TRANSLATION_LOCALES else ""
        if not selected_background_product_gid:
            safe_action_result = _translation_console_safe_action_result(
                action=post_action,
                action_status="translation_draft_job_blocked",
                message="Select one product before retrying this language.",
                summary={
                    "blocking_conditions": ["missing_selected_product"],
                    "shopify_write_performed": False,
                    "mutation_performed": False,
                    "translations_register_called": False,
                },
            )
        elif not retry_locale:
            safe_action_result = _translation_console_safe_action_result(
                action=post_action,
                action_status="translation_draft_job_blocked",
                message="Choose a supported language before retrying.",
                summary={
                    "blocking_conditions": ["unsupported_target_language"],
                    "shopify_write_performed": False,
                    "mutation_performed": False,
                    "translations_register_called": False,
                },
            )
        else:
            installation = ShopifyInstallation.objects.first()
            if installation is None:
                safe_action_result = _translation_console_safe_action_result(
                    action=post_action,
                    action_status="translation_draft_job_blocked",
                    message=f"Shopify installation not found for {shop_domain}.",
                    summary={
                        "blocking_conditions": ["missing_shopify_installation"],
                        "shopify_write_performed": False,
                        "mutation_performed": False,
                        "translations_register_called": False,
                    },
                )
            else:
                start_result = start_translation_workspace_background_job(
                    installation_id=installation.pk,
                    product_gid=selected_background_product_gid,
                    product_title=(
                        (product_selector.get("selected_product") or {}).get("title", "")
                    ),
                    product_search_text=product_search_text,
                    selected_locale=retry_locale,
                    selected_locales=[retry_locale],
                    editor_filter=editor_filter,
                    editor_search_query=editor_search_query,
                )
                translation_background_job = start_result["job_status"]
                safe_action_result = _translation_console_safe_action_result(
                    action=post_action,
                    action_status=start_result["action_status"],
                    message=start_result["message"],
                    summary=_translation_workspace_job_safe_summary(
                        translation_background_job
                    ),
                )
                return HttpResponseRedirect(
                    _translation_console_editor_redirect_url(
                        request,
                        selected_product_gid=selected_background_product_gid,
                        product_search_text=product_search_text,
                        locale=retry_locale,
                        editor_filter=editor_filter,
                        editor_search_query=editor_search_query,
                    )
                )
    elif post_action == "generate_multi_locale_drafts" and safe_action_result is None:
        blocked_message = _translation_workspace_multi_locale_blocked_message(
            has_product=bool(action_product_query),
            requested_locales=requested_draft_locales,
            invalid_locales=invalid_draft_locales,
            requested_groups=requested_draft_groups,
            invalid_groups=invalid_draft_groups,
        )
        multi_locale_draft_result = _translation_workspace_empty_multi_locale_result(
            product_id=action_product_query,
            selected_locale=locale,
            requested_locales=requested_draft_locales,
            invalid_locales=invalid_draft_locales,
            requested_groups=requested_draft_groups,
            invalid_groups=invalid_draft_groups,
            message=(
                draft_error_message
                or error_message
                or blocked_message
            ),
            action_status="multi_locale_draft_blocked",
            blocking_conditions=["missing_or_unavailable_selected_product"],
        )
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status=multi_locale_draft_result["action_status"],
            message=multi_locale_draft_result["message"],
            summary=multi_locale_draft_result["summary"],
        )
    elif post_action == "generate_draft_dry_run" and safe_action_result is None:
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status="draft_dry_run_blocked",
            message=(
                draft_error_message
                or error_message
                or "Select a single Shopify product before generating a draft dry-run package."
            ),
            summary={"blocking_conditions": ["missing_or_unavailable_selected_product"]},
        )

    locked_report_approval_checklist = (
        load_latest_translation_console_locked_package_report(
            selected_product_gid=workflow_product_id,
            preferred_json_path=(
                locked_package_report_result.get("json_report_path", "")
                if locked_package_report_result
                else ""
            ),
        )
    )
    manual_command_package = build_translation_console_manual_command_package(
        locked_report_approval_checklist
    )
    workbench_summary = build_translation_console_workbench_summary(
        product_selector=product_selector,
        workflow_status=workflow_status,
        draft_result=draft_result,
        apply_plan_preview_result=apply_plan_preview_result,
        locked_package_report_result=locked_package_report_result,
        locked_report_approval_checklist=locked_report_approval_checklist,
        manual_command_package=manual_command_package,
    )
    editor_view = build_translation_console_editor_view(
        product_selector=product_selector,
        result=result,
        draft_result=draft_result,
        apply_plan_preview_result=apply_plan_preview_result,
        locale=locale,
        editor_filter=editor_filter,
        editor_search_query=editor_search_query,
    )
    single_product_mvp = build_translation_workspace_single_product_mvp(
        product_selector=product_selector,
        result=result,
        editor_view=editor_view,
        draft_result=draft_result,
        apply_plan_preview_result=apply_plan_preview_result,
        locale=locale,
        supported_locales=SUPPORTED_TRANSLATION_LOCALES,
    )
    safe_write_readiness_display = (
        safe_write_readiness_result or safe_write_readiness_state
    )
    selected_translations_apply_display = (
        selected_translations_apply_result or selected_translations_apply_state
    )
    all_languages_update_display = all_languages_update_result or all_languages_update_state
    all_languages_update_report_display = all_languages_update_result or {}
    if not all_languages_update_report_display:
        all_languages_update_report_display = load_latest_all_languages_update_report(
            translation_job_product_id
        )
    if all_languages_update_report_display:
        all_languages_update_display = all_languages_update_report_display
    workspace_locked_execution_display = workspace_locked_execution_result or {}
    workspace_real_write_display = workspace_real_write_result or {}
    workspace_real_write_can_submit = (
        workspace_locked_execution_display.get("package_status")
        == "locked_execution_ready_for_manual_ack"
        and workspace_locked_execution_display.get("selected_entry_count") == 1
        and bool(workspace_locked_execution_display.get("locked_entry_checksum"))
    )

    return render(
        request,
        "admin/shopify_sync/translation_console.html",
        {
            "title": "Shopify Product Translation Console",
            "search_text": search_text,
            "product_search_text": product_search_text,
            "product_selector": product_selector,
            "product_library_status": product_library_status,
            "selected_product_gid": selected_product_gid,
            "manual_product_gid": manual_product_gid,
            "selected_locale": locale,
            "supported_locales": SUPPORTED_TRANSLATION_LOCALES,
            "supported_locale_options": [
                {
                    "value": supported_locale,
                    "label": _translation_editor_locale_label(supported_locale),
                }
                for supported_locale in SUPPORTED_TRANSLATION_LOCALES
            ],
            "draft_locale_options": draft_locale_options,
            "draft_group_options": draft_group_options,
            "requested_draft_groups": requested_draft_groups,
            "ui_mode": ui_mode,
            "editor_filter": editor_filter,
            "editor_search_query": editor_search_query,
            "translation_console_warnings": translation_console_warnings,
            "editor_view": editor_view,
            "single_product_mvp": single_product_mvp,
            "shop_domain": shop_domain,
            "result": result,
            "workflow_status": workflow_status,
            "safe_action_result": safe_action_result,
            "apply_plan_preview_result": apply_plan_preview_result,
            "locked_package_report_result": locked_package_report_result,
            "locked_report_approval_checklist": locked_report_approval_checklist,
            "manual_command_package": manual_command_package,
            "workbench_summary": workbench_summary,
            "error_message": error_message,
            "draft_result": draft_result,
            "multi_locale_draft_result": multi_locale_draft_result,
            "translate_all_result": translate_all_result,
            "translation_background_job": translation_background_job,
            "translation_report_guard": translation_report_guard,
            "draft_error_message": draft_error_message,
            "apply_plan_result": apply_plan_result,
            "apply_plan_error_message": apply_plan_error_message,
            "final_review_result": final_review_result,
            "final_review_error_message": final_review_error_message,
            "real_write_readiness_result": real_write_readiness_result,
            "real_write_readiness_error_message": real_write_readiness_error_message,
            "readiness_result": real_write_readiness_result,
            "readiness_error_message": real_write_readiness_error_message,
            "locked_execution_plan_result": locked_execution_plan_result,
            "locked_execution_plan_error_message": locked_execution_plan_error_message,
            "locked_executor_result": locked_executor_result,
            "locked_executor_error_message": locked_executor_error_message,
            "real_write_executor_result": real_write_executor_result,
            "real_write_executor_error_message": real_write_executor_error_message,
            "manual_action_package_result": manual_action_package_result,
            "manual_action_package_error_message": manual_action_package_error_message,
            "safe_write_readiness_state": safe_write_readiness_state,
            "safe_write_readiness_result": safe_write_readiness_result,
            "safe_write_readiness_display": safe_write_readiness_display,
            "safe_write_readiness_error_message": safe_write_readiness_error_message,
            "selected_translations_apply_state": selected_translations_apply_state,
            "selected_translations_apply_result": selected_translations_apply_result,
            "selected_translations_apply_display": selected_translations_apply_display,
            "selected_translations_apply_error_message": selected_translations_apply_error_message,
            "all_languages_update_state": all_languages_update_state,
            "all_languages_update_result": all_languages_update_result,
            "all_languages_update_report_display": all_languages_update_report_display,
            "all_languages_update_display": all_languages_update_display,
            "all_languages_update_error_message": all_languages_update_error_message,
            "workspace_locked_execution_result": workspace_locked_execution_result,
            "workspace_locked_execution_display": workspace_locked_execution_display,
            "workspace_locked_execution_error_message": workspace_locked_execution_error_message,
            "workspace_real_write_result": workspace_real_write_result,
            "workspace_real_write_display": workspace_real_write_display,
            "workspace_real_write_error_message": workspace_real_write_error_message,
            "workspace_real_write_can_submit": workspace_real_write_can_submit,
            "locked_execution_ack_phrase": LOCKED_EXECUTION_ACK_PHRASE,
            "translation_single_locked_write_action_name": REAL_WRITE_ACTION_NAME,
            "selected_translations_real_write_action_name": SELECTED_TRANSLATIONS_REAL_WRITE_ACTION_NAME,
            "all_languages_real_write_action_name": ALL_LANGUAGES_REAL_WRITE_ACTION_NAME,
            "translation_workspace_retry_locale_action_name": TRANSLATION_WORKSPACE_RETRY_LOCALE_ACTION_NAME,
            "selected_translations_real_write_ack_phrase": SELECTED_TRANSLATIONS_REAL_WRITE_ACK_PHRASE,
            "manual_translation_edit_action_name": TRANSLATION_WORKSPACE_MANUAL_EDIT_ACTION_NAME,
            "draft_target_locales": TRANSLATION_DRAFT_TARGET_LOCALES,
            "draft_fields": TRANSLATION_DRAFT_FIELDS,
            "draft_json_report_path": "logs/shopify_translation_selected_product_missing_translation_draft_package.json",
            "draft_html_report_path": "logs/shopify_translation_selected_product_missing_translation_draft_package.html",
            "apply_plan_json_report_path": str(APPLY_PLAN_JSON_PATH),
            "apply_plan_html_report_path": str(APPLY_PLAN_HTML_PATH),
            "final_review_json_report_path": str(FINAL_REVIEW_JSON_PATH),
            "final_review_html_report_path": str(FINAL_REVIEW_HTML_PATH),
            "real_write_readiness_json_report_path": str(REAL_WRITE_READINESS_JSON_PATH),
            "real_write_readiness_html_report_path": str(REAL_WRITE_READINESS_HTML_PATH),
            "readiness_json_report_path": str(REAL_WRITE_READINESS_JSON_PATH),
            "readiness_html_report_path": str(REAL_WRITE_READINESS_HTML_PATH),
            "locked_execution_plan_json_report_path": str(LOCKED_EXECUTION_PLAN_JSON_PATH),
            "locked_execution_plan_html_report_path": str(LOCKED_EXECUTION_PLAN_HTML_PATH),
            "locked_executor_json_report_path": str(LOCKED_EXECUTOR_JSON_PATH),
            "locked_executor_html_report_path": str(LOCKED_EXECUTOR_HTML_PATH),
            "real_write_executor_json_report_path": str(REAL_WRITE_EXECUTOR_JSON_PATH),
            "real_write_executor_html_report_path": str(REAL_WRITE_EXECUTOR_HTML_PATH),
            "manual_action_package_json_report_path": str(REAL_WRITE_MANUAL_ACTION_JSON_PATH),
            "manual_action_package_html_report_path": str(REAL_WRITE_MANUAL_ACTION_HTML_PATH),
            "real_write_manual_ack_phrase_required": REAL_WRITE_MANUAL_ACK_PHRASE_REQUIRED,
        },
    )


@staff_member_required
def translation_console_product_search(request):
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])

    query = _translation_console_request_product_search_text(
        request.GET,
        is_post_action=False,
    )
    if not query:
        return JsonResponse(
            {
                "query": "",
                "count": 0,
                "limit": TRANSLATION_CONSOLE_PRODUCT_SELECTOR_LIMIT,
                "results": [],
                "local_db_only": True,
            }
        )

    product_selector = _build_translation_console_product_selector(
        product_search_text=query,
        requested_product_gid="",
        limit=TRANSLATION_CONSOLE_PRODUCT_SELECTOR_LIMIT,
    )
    results = [
        _translation_console_product_search_json_result(product)
        for product in product_selector.get("product_options", [])
    ]
    return JsonResponse(
        {
            "query": query,
            "count": len(results),
            "limit": TRANSLATION_CONSOLE_PRODUCT_SELECTOR_LIMIT,
            "results": results,
            "local_db_only": True,
        }
    )


@staff_member_required
def translation_console_job_status(request):
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])

    raw_job_id = (request.GET.get("job_id") or "").strip()
    raw_product_gid = (
        request.GET.get("product_gid") or request.GET.get("product_id") or ""
    ).strip()
    product_gid = normalize_product_gid(raw_product_gid) if raw_product_gid else ""
    if raw_product_gid and not product_gid:
        return HttpResponseBadRequest("Invalid product_gid.")
    if raw_job_id and not _translation_workspace_valid_job_id(raw_job_id):
        return HttpResponseBadRequest("Invalid job_id.")
    if raw_job_id and not product_gid:
        return HttpResponseBadRequest("product_gid is required with job_id.")

    status = {}
    if raw_job_id:
        status = _translation_workspace_load_job_status(raw_job_id)
        if product_gid and status.get("product_gid") != product_gid:
            status = {}
    elif product_gid:
        status = _translation_workspace_latest_job_status(product_gid)

    if status:
        status = _translation_workspace_mark_stale_if_needed(status, persist=False)
    else:
        status = _translation_workspace_not_started_job_status(product_gid)

    response = JsonResponse(_translation_workspace_job_status_for_json(status))
    response["Cache-Control"] = "no-store"
    return response


def _build_translation_console_product_selector(
    product_search_text: str,
    requested_product_gid: str = "",
    limit: int = TRANSLATION_CONSOLE_PRODUCT_SELECTOR_LIMIT,
):
    query = (product_search_text or "").strip()
    requested_gid = normalize_product_gid((requested_product_gid or "").strip()) or ""
    supported_fields = _translation_console_supported_product_search_fields()
    order_by_fields, supported_sort_fields = _translation_console_product_ordering()

    product_options = []
    selected_option = (
        _translation_console_selector_option_for_gid(requested_gid) if requested_gid else {}
    )
    if query:
        queryset = ShopifyProduct.objects.all()
        for term in _translation_console_product_query_filter_terms(query):
            queryset = queryset.filter(
                _translation_console_product_search_q(term, supported_fields)
            )
        product_options = _translation_console_distinct_ranked_product_options(
            queryset.order_by(*order_by_fields),
            query=query,
            limit=limit,
        )

    included_selected_product = False
    selected_product = _find_selector_option(product_options, requested_gid) or selected_option
    if selected_option and not _find_selector_option(product_options, requested_gid):
        if not query or _translation_console_product_matches_query(selected_option, query):
            product_options.insert(0, selected_option)
            included_selected_product = True

    selected_gid = requested_gid
    matching_result_count = len(product_options) if query else 0

    return {
        "product_options": product_options,
        "selected_product_gid": selected_gid,
        "selected_product": selected_product,
        "product_search_text": query,
        "result_count": matching_result_count,
        "matching_result_count": matching_result_count,
        "limit": limit,
        "has_products": bool(product_options),
        "included_selected_product": included_selected_product,
        "no_matching_products": bool(query) and matching_result_count == 0,
        "no_products_available": not ShopifyProduct.objects.exists(),
        "sort_fields": supported_sort_fields,
        "search_supported_fields": supported_fields,
    }


def _translation_console_product_search_json_result(option: dict):
    fields = (
        "gid",
        "numeric_id",
        "title",
        "handle",
        "variant_title",
        "sku",
        "thumbnail_url",
        "has_thumbnail",
        "status",
        "product_type",
        "vendor",
        "variant_numeric_id",
        "searchable_text",
        "searchable_normalized",
    )
    return {field: option.get(field, "") for field in fields}


def _translation_console_distinct_ranked_product_options(queryset, *, query: str, limit: int):
    product_options_by_id = {}
    relevance_by_id = {}
    candidate_limit = max(TRANSLATION_CONSOLE_PRODUCT_SEARCH_SCAN_LIMIT, limit)
    for product in queryset[:candidate_limit]:
        product_id = getattr(product, "shopify_product_id", None)
        if not product_id:
            continue
        option = _translation_console_selector_option_from_product(product)
        if not _translation_console_product_matches_query(option, query):
            continue
        relevance = _translation_console_product_search_relevance(option, query)
        if relevance <= 0:
            continue
        if (
            product_id not in product_options_by_id
            or relevance > relevance_by_id.get(product_id, -1)
        ):
            product_options_by_id[product_id] = option
            relevance_by_id[product_id] = relevance

    product_options = list(product_options_by_id.values())
    product_options.sort(
        key=lambda option: (
            _translation_console_product_search_relevance(option, query),
            option.get("sort_timestamp", ""),
            option.get("numeric_id", ""),
        ),
        reverse=True,
    )
    return product_options[:limit]


def _build_translation_console_product_library_status():
    aggregates = ShopifyProduct.objects.aggregate(
        product_variant_count=Count("id"),
        distinct_product_count=Count("shopify_product_id", distinct=True),
        latest_shopify_product_updated_at=Max("shopify_product_updated_at"),
        latest_local_updated_at=Max("updated_at"),
    )
    sync_state = ShopifySyncState.objects.filter(
        task_name=TRANSLATION_CONSOLE_PRODUCT_SYNC_TASK_NAME
    ).first()
    return {
        "source": "shared ShopifyProduct local product library",
        "sync": "maintained by existing Shopify product sync / Shenzhen settlement product library",
        "search_note": (
            "Search uses shared local ShopifyProduct rows, ranked by "
            "model/title/SKU/handle relevance. No Shopify API call is made."
        ),
        "product_variant_count": aggregates.get("product_variant_count") or 0,
        "distinct_product_count": aggregates.get("distinct_product_count") or 0,
        "latest_shopify_product_updated_at": _format_optional_datetime(
            aggregates.get("latest_shopify_product_updated_at")
        ),
        "latest_local_updated_at": _format_optional_datetime(
            aggregates.get("latest_local_updated_at")
        ),
        "sync_task_name": TRANSLATION_CONSOLE_PRODUCT_SYNC_TASK_NAME,
        "sync_state_available": bool(sync_state),
        "sync_last_success_at": _format_optional_datetime(
            sync_state.last_success_at if sync_state else None
        ),
        "sync_last_error": _safe_sync_state_error_preview(
            sync_state.last_error if sync_state else ""
        ),
    }


def _safe_sync_state_error_preview(value: str) -> str:
    text = re.sub(r"\s+", " ", (value or "").strip())
    if not text:
        return ""
    text = re.sub(
        r"(?i)\b(access[_-]?token|api[_-]?key|secret[_-]?key|secret|password|authorization|bearer)\b\s*[:=]\s*\S+",
        r"\1=[redacted]",
        text,
    )
    text = re.sub(r"shpat_[A-Za-z0-9_]+", "shpat_[redacted]", text)
    if len(text) > 180:
        return f"{text[:180]}..."
    return text


def _translation_console_request_product_search_text(
    request_params,
    *,
    is_post_action: bool,
) -> str:
    field_names = (
        ("product_search", "product_search_q")
        if is_post_action
        else ("product_search", "product_search_q", "q")
    )
    for field_name in field_names:
        if field_name in request_params:
            return (request_params.get(field_name, "") or "").strip()
    return ""


def _translation_console_selector_option_from_product(product):
    product_id = getattr(product, "shopify_product_id", None)
    variant_id = getattr(product, "shopify_variant_id", None)
    product_gid = f"gid://shopify/Product/{product_id}"
    title = product.product_title or "(untitled product)"
    variant_title = product.variant_title or ""
    sku = product.sku or ""
    handle = product.handle or ""
    product_type = product.product_type or ""
    vendor = product.vendor or ""
    thumbnail_url = (getattr(product, "image_url", "") or "").strip()
    created_at_value = (
        getattr(product, "shopify_created_at", None)
        or getattr(product, "shopify_product_created_at", None)
        or getattr(product, "created_at", None)
    )
    updated_at_value = getattr(product, "updated_at", None)
    sort_timestamp_value = (
        getattr(product, "shopify_published_at", None)
        or created_at_value
        or updated_at_value
    )
    searchable_text = " ".join(
        str(value)
        for value in (
            title,
            variant_title,
            sku,
            handle,
            product_type,
            vendor,
            product_id,
            variant_id,
            product_gid,
        )
        if value
    )
    return {
        "gid": product_gid,
        "numeric_id": str(product_id),
        "variant_numeric_id": str(variant_id) if variant_id else "",
        "title": title,
        "handle": handle,
        "vendor": vendor,
        "product_type": product_type,
        "variant_title": variant_title,
        "sku": sku,
        "thumbnail_url": thumbnail_url,
        "has_thumbnail": bool(thumbnail_url),
        "searchable_text": searchable_text,
        "searchable_normalized": _translation_console_normalize_search_text(searchable_text),
        "status": product.status or "",
        "published_at": _format_optional_datetime(product.shopify_published_at),
        "created_at": _format_optional_datetime(created_at_value),
        "updated_at": _format_optional_datetime(updated_at_value),
        "sort_timestamp": _format_optional_datetime(sort_timestamp_value),
    }


def _translation_console_selector_option_for_gid(product_gid: str):
    product_id = _extract_shopify_numeric_id(product_gid)
    if not product_id:
        return {}
    order_by_fields, _supported_sort_fields = _translation_console_product_ordering()
    product = (
        ShopifyProduct.objects.filter(shopify_product_id=product_id)
        .order_by(*order_by_fields)
        .first()
    )
    if not product:
        return {}
    return _translation_console_selector_option_from_product(product)


def _translation_console_product_ordering():
    supported_sort_fields = [
        field_name
        for field_name in TRANSLATION_CONSOLE_PRODUCT_SELECTOR_SORT_FIELDS
        if _model_has_field(ShopifyProduct, field_name)
    ]
    if "id" not in supported_sort_fields:
        supported_sort_fields.append("id")
    order_by_fields = [
        F(field_name).desc(nulls_last=True)
        for field_name in supported_sort_fields
    ]
    return order_by_fields, supported_sort_fields


def _translation_console_supported_product_search_fields():
    supported = []
    for field_name in TRANSLATION_CONSOLE_PRODUCT_SEARCH_FIELDS:
        if _model_has_field(ShopifyProduct, field_name):
            supported.append(field_name)
    return supported


def _translation_console_product_query_filter_terms(query: str):
    model_terms = _translation_console_model_query_terms(query)
    if model_terms:
        return _translation_console_unique_terms(
            [*model_terms, *_translation_console_non_model_query_terms(query)]
        )
    return [part for part in query.split() if part.strip()]


def _translation_console_product_search_q(term: str, supported_fields: list[str]):
    value = (term or "").strip()
    query = Q()
    if not value:
        return query
    term_variants = _translation_console_product_search_variants(value)
    for field_name in supported_fields:
        if field_name in {"shopify_product_id", "shopify_variant_id"}:
            continue
        for term_variant in term_variants:
            query |= Q(**{f"{field_name}__icontains": term_variant})
    product_id, variant_id = _extract_shopify_search_ids(value)
    if product_id:
        if "shopify_product_id" in supported_fields:
            query |= Q(shopify_product_id=product_id)
    if variant_id:
        if "shopify_variant_id" in supported_fields:
            query |= Q(shopify_variant_id=variant_id)
    return query


def _translation_console_product_search_variants(value: str):
    raw_value = (value or "").strip()
    compact_value = re.sub(r"[^0-9A-Za-z]+", "", raw_value)
    variants = []

    def add_variant(candidate):
        candidate = (candidate or "").strip()
        if candidate and candidate.lower() not in {item.lower() for item in variants}:
            variants.append(candidate)

    add_variant(raw_value)
    add_variant(compact_value)

    parts = re.findall(r"[A-Za-z]+|\d+", compact_value)
    if len(parts) > 1:
        for separator in ("-", " ", "_"):
            add_variant(separator.join(parts))

    model_match = re.match(r"^([A-Za-z]+)(\d+)([A-Za-z]+)?$", compact_value)
    if model_match:
        letters, digits, suffix = model_match.groups()
        suffix = suffix or ""
        for separator in ("-", " ", "_"):
            add_variant(f"{letters}{separator}{digits}{suffix}")

    return variants


def _translation_console_normalize_search_text(value: str):
    return re.sub(r"[^0-9a-z]+", "", (value or "").lower())


def _translation_console_model_query_terms(query: str):
    terms = []
    for match in TRANSLATION_CONSOLE_PRODUCT_MODEL_QUERY_RE.finditer(query or ""):
        normalized = _translation_console_normalize_search_text(match.group(0))
        if _translation_console_is_model_term(normalized):
            terms.append(normalized)
    compact_query = _translation_console_normalize_search_text(query)
    if (
        _translation_console_is_model_term(compact_query)
        and len(terms) <= 1
        and TRANSLATION_CONSOLE_PRODUCT_MODEL_QUERY_RE.fullmatch((query or "").strip())
    ):
        terms.append(compact_query)
    return _translation_console_unique_terms(terms)


def _translation_console_non_model_query_terms(query: str):
    without_model_terms = TRANSLATION_CONSOLE_PRODUCT_MODEL_QUERY_RE.sub(" ", query or "")
    return _translation_console_unique_terms(
        _translation_console_normalize_search_text(term)
        for term in re.findall(r"[A-Za-z0-9]+", without_model_terms)
    )


def _translation_console_unique_terms(values):
    terms = []
    seen = set()
    for value in values:
        term = (value or "").strip().lower()
        if term and term not in seen:
            terms.append(term)
            seen.add(term)
    return terms


def _translation_console_is_model_term(value: str) -> bool:
    return bool(
        value
        and re.search(r"[a-z]", value)
        and re.search(r"\d", value)
    )


def _translation_console_product_matches_query(option: dict, query: str) -> bool:
    normalized_query = _translation_console_normalize_search_text(query)
    if not normalized_query:
        return False

    model_terms = _translation_console_model_query_terms(query)
    searchable_normalized = _translation_console_option_searchable_normalized(option)
    if model_terms:
        if not _translation_console_product_has_strong_model_match(option, model_terms):
            return False
        extra_terms = _translation_console_non_model_query_terms(query)
        return all(term in searchable_normalized for term in extra_terms)

    product_id, variant_id = _extract_shopify_search_ids(query)
    if product_id and str(product_id) == str(option.get("numeric_id", "")):
        return True
    if variant_id and str(variant_id) == str(option.get("variant_numeric_id", "")):
        return True

    raw_query = (query or "").strip().lower()
    raw_search = (option.get("searchable_text") or "").lower()
    if raw_query and raw_query in raw_search:
        return True
    if normalized_query in searchable_normalized:
        return True
    tokens = [
        _translation_console_normalize_search_text(part)
        for part in re.split(r"[\s_-]+", query or "")
    ]
    tokens = [token for token in tokens if token]
    return bool(tokens and all(token in searchable_normalized for token in tokens))


def _translation_console_product_has_strong_model_match(
    option: dict, model_terms
) -> bool:
    normalized_fields = _translation_console_option_normalized_match_fields(option)
    return all(
        any(model_term in field_value for field_value in normalized_fields)
        for model_term in model_terms
    )


def _translation_console_option_searchable_normalized(option: dict):
    return (
        option.get("searchable_normalized")
        or _translation_console_normalize_search_text(option.get("searchable_text", ""))
    )


def _translation_console_option_normalized_match_fields(option: dict):
    return [
        _translation_console_normalize_search_text(option.get("title", "")),
        _translation_console_normalize_search_text(option.get("variant_title", "")),
        _translation_console_normalize_search_text(option.get("sku", "")),
        _translation_console_normalize_search_text(option.get("handle", "")),
        _translation_console_normalize_search_text(option.get("numeric_id", "")),
        _translation_console_normalize_search_text(option.get("variant_numeric_id", "")),
    ]


def _translation_console_product_search_relevance(option: dict, query: str) -> int:
    normalized_query = _translation_console_normalize_search_text(query)
    if not normalized_query:
        return 0
    model_terms = _translation_console_model_query_terms(query)
    if model_terms and not _translation_console_product_has_strong_model_match(
        option, model_terms
    ):
        return 0

    searchable_normalized = _translation_console_option_searchable_normalized(option)
    title_normalized = _translation_console_normalize_search_text(option.get("title", ""))
    sku_normalized = _translation_console_normalize_search_text(option.get("sku", ""))
    variant_normalized = _translation_console_normalize_search_text(
        option.get("variant_title", "")
    )
    handle_normalized = _translation_console_normalize_search_text(option.get("handle", ""))
    product_id_normalized = _translation_console_normalize_search_text(
        option.get("numeric_id", "")
    )
    variant_id_normalized = _translation_console_normalize_search_text(
        option.get("variant_numeric_id", "")
    )
    tokens = [
        token
        for token in (
            _translation_console_normalize_search_text(part)
            for part in re.split(r"[\s_-]+", query)
        )
        if token
    ]

    score = 0
    if title_normalized == normalized_query:
        score += 1000
    if variant_normalized == normalized_query:
        score += 900
    if sku_normalized == normalized_query:
        score += 850
    if handle_normalized == normalized_query:
        score += 750
    if normalized_query in {product_id_normalized, variant_id_normalized}:
        score += 700

    if model_terms:
        for model_term in model_terms:
            if title_normalized == model_term:
                score += 950
            elif title_normalized.startswith(model_term):
                score += 700
            elif model_term in title_normalized:
                score += 560

            if variant_normalized == model_term:
                score += 700
            elif variant_normalized.startswith(model_term):
                score += 520
            elif model_term in variant_normalized:
                score += 360

            if sku_normalized == model_term:
                score += 680
            elif sku_normalized.startswith(model_term):
                score += 500
            elif model_term in sku_normalized:
                score += 340

            if handle_normalized == model_term:
                score += 600
            elif handle_normalized.startswith(model_term):
                score += 430
            elif model_term in handle_normalized:
                score += 260

            if model_term in {product_id_normalized, variant_id_normalized}:
                score += 550
            elif model_term in searchable_normalized:
                score += 120
    elif title_normalized.startswith(normalized_query):
        score += 90
    elif normalized_query in title_normalized:
        score += 70
    elif sku_normalized.startswith(normalized_query):
        score += 65
    elif variant_normalized.startswith(normalized_query):
        score += 60
    elif handle_normalized.startswith(normalized_query):
        score += 45
    elif normalized_query in searchable_normalized:
        score += 35

    if tokens and all(token in searchable_normalized for token in tokens):
        score += 20 + len(tokens)

    searchable_raw = (option.get("searchable_text") or "").lower()
    if model_terms:
        for phrase in TRANSLATION_CONSOLE_PRODUCT_MAIN_PRODUCT_PHRASES:
            if _translation_console_raw_text_contains_term(searchable_raw, phrase):
                score += 70
        for term in TRANSLATION_CONSOLE_PRODUCT_SPARE_PART_TERMS:
            if _translation_console_raw_text_contains_term(searchable_raw, term):
                score -= 55
    return max(score, 0)


def _translation_console_raw_text_contains_term(value: str, term: str) -> bool:
    escaped_term = re.escape((term or "").lower()).replace(r"\ ", r"[\s_-]+")
    if not escaped_term:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){escaped_term}(?![a-z0-9])", value or ""))


def _extract_shopify_numeric_id(value: str):
    normalized_gid = normalize_product_gid(value)
    if normalized_gid:
        return int(normalized_gid.rsplit("/", 1)[-1])
    numeric = (value or "").strip()
    if numeric.isdigit():
        return int(numeric)
    return None


def _extract_shopify_search_ids(value: str):
    raw_value = (value or "").strip()
    product_gid = normalize_product_gid(raw_value)
    if product_gid:
        return int(product_gid.rsplit("/", 1)[-1]), None
    variant_gid_match = re.fullmatch(r"gid://shopify/ProductVariant/(\d+)", raw_value)
    if variant_gid_match:
        return None, int(variant_gid_match.group(1))
    if raw_value.isdigit():
        numeric_id = int(raw_value)
        return numeric_id, numeric_id
    return None, None


def _find_selector_option(product_options, selected_gid: str):
    for option in product_options:
        if option.get("gid") == selected_gid:
            return option
    return {}


def _format_optional_datetime(value):
    if not value:
        return ""
    return value.isoformat()


def _translation_console_last_request_value(params, names):
    for name in names:
        values = [
            str(value).strip()
            for value in params.getlist(name)
            if str(value or "").strip()
        ]
        if values:
            return values[-1]
    return ""


def _translation_console_product_gid_conflict_warnings(request, is_post_action: bool):
    warnings = []
    query_product_values = _translation_console_normalized_product_values(
        request.GET, ("product_gid", "product_id")
    )
    if len(set(query_product_values)) > 1:
        warnings.append(
            "Duplicate product_gid/product_id URL parameters were detected; the explicit selected product field is used for POST actions, otherwise the newest URL value is used."
        )
    if not is_post_action:
        return warnings

    form_product_values = _translation_console_normalized_product_values(
        request.POST, ("product_gid", "product_id")
    )
    if len(set(form_product_values)) > 1:
        warnings.append(
            "Duplicate product_gid/product_id form values were detected; the newest form value is used unless selected_product_gid is present."
        )
    selected_product_gid = _translation_console_last_normalized_product_value(
        request.POST, ("selected_product_gid",)
    )
    form_product_gid = _translation_console_last_normalized_product_value(
        request.POST, ("product_gid", "product_id")
    )
    if selected_product_gid and form_product_gid and selected_product_gid != form_product_gid:
        warnings.append(
            "Conflicting selected_product_gid and product_gid were submitted; selected_product_gid was used."
        )
    return warnings


def _translation_console_normalized_product_values(params, names):
    values = []
    for name in names:
        for raw_value in params.getlist(name):
            normalized = normalize_product_gid(str(raw_value or "").strip())
            if normalized:
                values.append(normalized)
    return values


def _translation_console_last_normalized_product_value(params, names):
    values = _translation_console_normalized_product_values(params, names)
    return values[-1] if values else ""


def _model_has_field(model, field_name: str) -> bool:
    try:
        model._meta.get_field(field_name)
    except FieldDoesNotExist:
        return False
    return True


def _resolve_translation_console_product_id(installation, search_text, locale):
    fetched = fetch_translation_console_data(installation, search_text, locale)
    product = fetched.get("product") or {}
    if product.get("id"):
        return product["id"]
    search_results = fetched.get("search_results") or []
    if len(search_results) == 1 and search_results[0].get("id"):
        return search_results[0]["id"]
    return ""


def _translation_console_safe_action_result(
    action: str,
    action_status: str,
    message: str,
    summary: dict | None = None,
):
    return {
        "action": action,
        "action_status": action_status,
        "message": message,
        "summary": summary or {},
        "read_only": True,
        "no_write_from_page": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
    }


def _translation_workspace_requested_draft_locales(
    request,
    is_multi_locale_draft_post: bool,
    is_translate_all_post: bool = False,
):
    if is_translate_all_post:
        return list(SUPPORTED_TRANSLATION_LOCALES), []
    if not is_multi_locale_draft_post:
        return [], []

    raw_locales = request.POST.getlist("draft_target_locales")
    if not raw_locales:
        raw_locales = request.POST.getlist("target_locales")
    allowed_locales = set(SUPPORTED_TRANSLATION_LOCALES)
    requested = []
    invalid = []
    for raw_locale in raw_locales:
        locale = _translation_editor_canonical_locale(raw_locale)
        if not locale:
            continue
        if locale not in allowed_locales:
            if locale not in invalid:
                invalid.append(locale)
            continue
        if locale not in requested:
            requested.append(locale)
    return requested, invalid


def _translation_workspace_draft_locale_options(
    selected_locale: str,
    requested_locales: list[str] | None = None,
):
    checked_locales = {
        _translation_editor_canonical_locale(locale)
        for locale in (requested_locales or [selected_locale])
    }
    return [
        {
            "value": locale,
            "label": _translation_editor_locale_label(locale),
            "checked": locale in checked_locales,
        }
        for locale in SUPPORTED_TRANSLATION_LOCALES
    ]


def _translation_workspace_requested_draft_groups(
    request,
    is_multi_locale_draft_post: bool,
    is_translate_all_post: bool = False,
):
    allowed = {option["value"] for option in TRANSLATION_WORKSPACE_DRAFT_GROUPS}
    if is_translate_all_post:
        return list(TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS), []
    if not is_multi_locale_draft_post:
        return list(TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS), []

    raw_groups = request.POST.getlist("draft_groups")
    requested = []
    invalid = []
    for raw_group in raw_groups:
        group = str(raw_group or "").strip()
        if not group:
            continue
        if group not in allowed:
            if group not in invalid:
                invalid.append(group)
            continue
        if group not in requested:
            requested.append(group)
    return requested, invalid


def _translation_workspace_draft_group_options(
    requested_groups: list[str] | None = None,
):
    selected = set(requested_groups or TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS)
    return [
        {
            **option,
            "checked": option["value"] in selected,
        }
        for option in TRANSLATION_WORKSPACE_DRAFT_GROUPS
    ]


def _translation_workspace_draft_scopes(draft_groups: list[str] | None):
    groups = list(draft_groups or TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS)
    scopes = []
    group_fields = {
        "product_basics": ["title", "body_html"],
        "seo": ["meta_title", "meta_description", "handle"],
        "options": ["options"],
        "variants": ["variants"],
        "important_metafields": ["important_metafields"],
        "media": ["media"],
    }
    for group in groups:
        for scope in group_fields.get(group, []):
            if scope not in scopes:
                scopes.append(scope)
    return scopes


def _translation_workspace_empty_multi_locale_result(
    product_id: str,
    selected_locale: str,
    requested_locales: list[str] | None,
    invalid_locales: list[str] | None,
    requested_groups: list[str] | None = None,
    invalid_groups: list[str] | None = None,
    message: str = "",
    action_status: str = "multi_locale_draft_blocked",
    blocking_conditions: list[str] | None = None,
):
    requested_locales = list(requested_locales or [])
    invalid_locales = list(invalid_locales or [])
    requested_groups = list(requested_groups or [])
    invalid_groups = list(invalid_groups or [])
    blocking_conditions = list(blocking_conditions or [])
    locale_results = []
    if invalid_locales and "unsupported_target_language" not in blocking_conditions:
        blocking_conditions.append("unsupported_target_language")
    if invalid_groups and "unsupported_draft_group" not in blocking_conditions:
        blocking_conditions.append("unsupported_draft_group")
    if not requested_locales and not invalid_locales:
        blocking_conditions.append("no_target_language_selected")
    if not requested_groups and not invalid_groups:
        blocking_conditions.append("no_draft_group_selected")
    for invalid_locale in invalid_locales:
        locale_results.append(
            {
                "locale": invalid_locale,
                "locale_label": invalid_locale,
                "status": "skipped",
                "status_key": "skipped",
                "status_label": "skipped",
                "draft_field_count": 0,
                "skipped_existing_field_count": 0,
                "skipped_field_count": 0,
                "message": "This target language is not supported.",
                "failure_reason": "Choose Japanese, German, French, Spanish, or Italian.",
                "blocking_conditions": ["unsupported_target_language"],
                "preview_url": "",
            }
        )
    if not message:
        if invalid_groups:
            message = "Choose only supported draft coverage groups."
        elif invalid_locales:
            message = "Choose only supported target languages."
        elif not requested_groups:
            message = "Choose at least one draft coverage group."
        else:
            message = "Choose at least one target language."
    summary = _translation_workspace_multi_locale_summary(locale_results)
    summary["blocking_conditions"] = blocking_conditions
    return {
        "action_status": action_status,
        "message": message,
        "product_id": product_id,
        "selected_locale": selected_locale,
        "requested_locales": requested_locales,
        "invalid_locales": invalid_locales,
        "requested_groups": requested_groups,
        "invalid_groups": invalid_groups,
        "locale_results": locale_results,
        "selected_locale_draft_result": None,
        "draft_fields": _translation_workspace_draft_scopes(requested_groups),
        "field_scope_labels": _translation_workspace_draft_field_labels(requested_groups),
        "summary": summary,
        "blocking_conditions": blocking_conditions,
        "read_only": True,
        "shopify_write_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _translation_workspace_empty_translate_all_result(
    product_id: str,
    selected_locale: str,
    message: str = "",
    blocking_conditions: list[str] | None = None,
    product_title: str = "",
    started_at: str = "",
    finished_at: str = "",
):
    blocking_conditions = list(blocking_conditions or [])
    if not blocking_conditions:
        blocking_conditions.append("missing_selected_product")
    finished_at = finished_at or _translation_workspace_now_iso()
    started_at = started_at or finished_at
    summary = {
        "summary_status": "blocked",
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
        "per_group_discovery_status": {},
        "per_group_discovery_reasons": {},
        "per_group_discovery_rows": [],
        "blocking_conditions": blocking_conditions,
        "shopify_read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
    }
    error_count = _translation_workspace_translate_all_error_count(
        summary, blocking_conditions
    )
    summary["errors_count"] = error_count
    return {
        "action_status": "translate_all_languages_all_content_blocked",
        "action_name": TRANSLATE_ALL_ACTION_NAME,
        "status_key": "failed",
        "status_label": "Failed",
        "message": message or "Select one product before translating all languages.",
        "product_id": product_id,
        "product_title": product_title,
        "selected_locale": selected_locale,
        "requested_locales": list(SUPPORTED_TRANSLATION_LOCALES),
        "locales_requested_count": len(SUPPORTED_TRANSLATION_LOCALES),
        "locales_processed_count": 0,
        "locales_processed_label": f"0 / {len(SUPPORTED_TRANSLATION_LOCALES)}",
        "generated_drafts_count": 0,
        "errors_count": error_count,
        "started_at": started_at,
        "finished_at": finished_at,
        "requested_groups": list(TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS),
        "draft_fields": list(ALL_ELIGIBLE_DRAFT_SCOPES),
        "field_scope_labels": _translation_workspace_draft_field_labels(
            list(TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS)
        ),
        "locale_results": [],
        "draft_result": None,
        "summary": summary,
        "blocking_conditions": blocking_conditions,
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _generate_translation_workspace_translate_all_drafts(
    installation,
    product_id: str,
    selected_locale: str,
    product_search_text: str = "",
    editor_filter: str = "all",
    editor_search_query: str = "",
):
    started_at = _translation_workspace_now_iso()
    draft_groups = list(TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS)
    draft_scopes = _translation_workspace_draft_scopes(draft_groups)
    try:
        draft_result = generate_selected_product_missing_translation_draft_package(
            product_id=product_id,
            target_locales=list(SUPPORTED_TRANSLATION_LOCALES),
            fields=draft_scopes,
            installation=installation,
            include_missing=True,
            include_outdated=True,
            include_all_eligible_groups=True,
            action_name=TRANSLATE_ALL_ACTION_NAME,
        )
        _attach_translation_console_draft_detail(
            draft_result,
            max_rows=TRANSLATION_CONSOLE_TRANSLATE_ALL_DETAIL_MAX_ROWS,
        )
    except Exception as exc:
        if isinstance(exc, (ShopifyTranslationConsoleError, requests.RequestException, ValueError)):
            message = safe_translation_console_error_message(exc)
        else:
            message = "Translate all languages failed before translation results were completed."
        return _translation_workspace_empty_translate_all_result(
            product_id=product_id,
            selected_locale=selected_locale,
            message=message,
            blocking_conditions=["translate_all_draft_generation_failed", type(exc).__name__],
            started_at=started_at,
            finished_at=_translation_workspace_now_iso(),
        )

    summary = dict(draft_result.get("translate_all_summary") or {})
    summary["blocking_conditions"] = list(draft_result.get("blocking_conditions") or [])
    summary["errors_count"] = _translation_workspace_translate_all_error_count(
        summary, summary["blocking_conditions"]
    )
    locale_results = [
        _translation_workspace_translate_all_locale_result(
            locale=locale,
            draft_result=draft_result,
            product_id=product_id,
            product_search_text=product_search_text,
            editor_filter=editor_filter,
            editor_search_query=editor_search_query,
        )
        for locale in SUPPORTED_TRANSLATION_LOCALES
    ]
    action_status, message = _translation_workspace_translate_all_status(draft_result, summary)
    status_key, status_label = _translation_workspace_translate_all_display_status(
        action_status, summary
    )
    locales_requested_count = len(SUPPORTED_TRANSLATION_LOCALES)
    locales_processed_count = int(summary.get("total_languages_checked") or 0)
    generated_drafts_count = int(summary.get("missing_drafts_generated") or 0) + int(
        summary.get("outdated_update_drafts_generated") or 0
    )
    return {
        "action_status": action_status,
        "action_name": TRANSLATE_ALL_ACTION_NAME,
        "status_key": status_key,
        "status_label": status_label,
        "message": message,
        "product_id": product_id,
        "product_title": draft_result.get("product_title", ""),
        "selected_locale": selected_locale,
        "requested_locales": list(SUPPORTED_TRANSLATION_LOCALES),
        "locales_requested_count": locales_requested_count,
        "locales_processed_count": locales_processed_count,
        "locales_processed_label": (
            f"{locales_processed_count} / {locales_requested_count}"
        ),
        "generated_drafts_count": generated_drafts_count,
        "errors_count": summary["errors_count"],
        "started_at": started_at,
        "finished_at": _translation_workspace_now_iso(),
        "requested_groups": draft_groups,
        "draft_fields": list(draft_scopes),
        "field_scope_labels": _translation_workspace_draft_field_labels(draft_groups),
        "locale_results": locale_results,
        "draft_result": draft_result,
        "summary": summary,
        "blocking_conditions": list(draft_result.get("blocking_conditions") or []),
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _translation_workspace_now_iso():
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _translation_workspace_translate_all_error_count(
    summary: dict, blocking_conditions: list[str]
):
    return len(blocking_conditions or []) + len(
        (summary or {}).get("child_resource_discovery_errors") or []
    )


def _translation_workspace_translate_all_display_status(
    action_status: str, summary: dict
):
    blocking_conditions = (summary or {}).get("blocking_conditions") or []
    if (
        blocking_conditions
        or "blocked" in str(action_status or "")
        or "needs_configuration" in str(action_status or "")
    ):
        return "failed", "Failed"
    if (summary or {}).get("child_resource_discovery_errors") or int(
        (summary or {}).get("needs_review_blocked") or 0
    ):
        return "partial", "Partial"
    return "completed", "Completed"


def _translation_workspace_translate_all_safe_summary(translate_all_result: dict | None):
    result = translate_all_result or {}
    summary = result.get("summary") or {}
    return {
        "status": result.get("status_label", ""),
        "product_gid": result.get("product_id", ""),
        "product_title": result.get("product_title", ""),
        "locales_processed": result.get("locales_processed_label", ""),
        "generated_drafts": result.get("generated_drafts_count", 0),
        "skipped_existing_translations": summary.get("already_translated_skipped", 0),
        "skipped_not_eligible": summary.get("not_eligible_skipped", 0),
        "errors_count": result.get("errors_count", summary.get("errors_count", 0)),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def load_translation_workspace_background_job_status(product_gid: str):
    normalized_gid = normalize_product_gid(product_gid or "") or ""
    if not normalized_gid:
        return {}
    status = _translation_workspace_latest_job_status(normalized_gid)
    if not status:
        return {}
    status = _translation_workspace_mark_stale_if_needed(status)
    return _translation_workspace_job_status_for_view(status)


def _translation_workspace_report_guard(report: dict | None, *, selected_product_gid: str):
    selected_gid = normalize_product_gid(selected_product_gid or "") or ""
    report_gid = normalize_product_gid((report or {}).get("product_gid") or "") or ""
    hidden_previous_report = bool(report_gid and selected_gid and report_gid != selected_gid)
    return {
        "selected_product_gid": selected_gid,
        "report_product_gid": report_gid,
        "report_visible": bool(report) and not hidden_previous_report,
        "hidden_previous_report": hidden_previous_report,
        "warning": (
            "Previous report belongs to another product and was hidden."
            if hidden_previous_report
            else ""
        ),
        "empty_message": "Select this product and click Translate all languages.",
    }


def save_translation_workspace_manual_edit(
    *,
    product_gid: str,
    job_id: str,
    entry_id: str,
    edited_value: str,
):
    normalized_gid = normalize_product_gid(product_gid or "") or ""
    job_id = str(job_id or "").strip()
    entry_id = str(entry_id or "").strip()
    edited_value = str(edited_value or "").strip()
    result = {
        "edit_status": "manual_translation_edit_blocked",
        "product_gid": normalized_gid,
        "job_id": job_id,
        "entry_id": entry_id,
        "locale": "",
        "field": "",
        "using_manual_edit": False,
        "validation_status": "",
        "seo_validation_status": "",
        "blocking_conditions": [],
        "manual_validation_reasons": [],
        "report_path": "",
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
    }
    if not normalized_gid:
        result["blocking_conditions"].append("blocked_missing_selected_product")
    if not job_id or not _translation_workspace_valid_job_id(job_id):
        result["blocking_conditions"].append("blocked_invalid_translation_job_id")
    if not entry_id:
        result["blocking_conditions"].append("blocked_missing_manual_edit_entry_id")
    if not edited_value:
        result["blocking_conditions"].append("blocked_manual_edit_empty")
    if result["blocking_conditions"]:
        return result

    latest_status = _translation_workspace_latest_job_status(normalized_gid)
    if not latest_status:
        result["blocking_conditions"].append("blocked_missing_latest_translation_report")
        return result
    if latest_status.get("job_id") != job_id:
        result["blocking_conditions"].append("blocked_manual_edit_not_latest_report")
        result["job_id"] = latest_status.get("job_id", job_id)
        result["report_path"] = latest_status.get("report_path", "")
        return result

    status = latest_status
    if normalize_product_gid(status.get("product_gid") or "") != normalized_gid:
        result["blocking_conditions"].append("blocked_selected_product_report_mismatch")
        return result

    row = _translation_workspace_find_review_row(status, entry_id)
    if not row:
        result["blocking_conditions"].append("blocked_manual_edit_entry_not_found")
        result["report_path"] = status.get("report_path", "")
        return result

    validation = _translation_workspace_validate_manual_edit(row, edited_value)
    now = _translation_workspace_now_iso()
    original_openai_value = (
        row.get("openai_original_proposed_translation")
        or row.get("original_openai_translation")
        or row.get("proposed_translation")
        or row.get("generated_draft_display")
        or row.get("proposed_translation_preview")
        or ""
    )
    row.update(
        {
            "manual_edit_value": edited_value,
            "manual_translation_override_value": edited_value,
            "manual_edit_saved_at": now,
            "manual_edit_source": "local_translation_workspace_report",
            "manual_edit_status": "edited_manually",
            "manual_edit_label": "Edited manually",
            "manual_edit_usage_label": "Using manual edit",
            "manual_edit_original_label": "OpenAI original available in Technical details",
            "has_manual_edit": True,
            "using_manual_edit": True,
            "openai_original_proposed_translation": original_openai_value,
            "original_openai_translation": original_openai_value,
            "proposed_translation": edited_value,
            "proposed_translation_preview": _preview_text(edited_value),
            "proposed_translation_display": edited_value,
            "generated_draft_display": edited_value,
            "generated_draft_summary": _preview_text(edited_value),
            "has_generated_draft": True,
            "proposed_chars": len(edited_value),
            "validation_status": validation["validation_status"],
            "seo_validation_status": validation["seo_validation_status"],
            "validation_reasons": ", ".join(validation["reasons"]),
            "seo_warning": ", ".join(validation["seo_reasons"]),
            "blocking_reasons": ", ".join(validation["reasons"]),
            "draft_blocked": validation["draft_blocked"],
            "product_identity_mismatch": validation["product_identity_mismatch"],
            "manual_edit_validation_reasons": validation["reasons"],
            "manual_edit_validation_message": validation["message"],
        }
    )
    overrides = status.setdefault("manual_translation_overrides", {})
    overrides[entry_id] = {
        "entry_id": entry_id,
        "locale": row.get("locale") or row.get("language", ""),
        "field": row.get("field") or row.get("key", ""),
        "resource_id": row.get("resource_id", ""),
        "digest": row.get("digest") or row.get("source_digest", ""),
        "edited_value": edited_value,
        "openai_original_proposed_translation": original_openai_value,
        "saved_at": now,
        "validation_status": validation["validation_status"],
        "seo_validation_status": validation["seo_validation_status"],
        "validation_reasons": validation["reasons"],
        "source": "local_translation_workspace_report",
    }
    status["manual_translation_override_count"] = len(overrides)
    status["updated_at"] = now
    _translation_workspace_recalculate_manual_edit_counts(status)
    _translation_workspace_save_job_status(status)

    result.update(
        {
            "edit_status": "manual_translation_edit_saved",
            "locale": row.get("locale") or row.get("language", ""),
            "field": row.get("field") or row.get("key", ""),
            "using_manual_edit": True,
            "validation_status": validation["validation_status"],
            "seo_validation_status": validation["seo_validation_status"],
            "manual_validation_reasons": validation["reasons"],
            "report_path": status.get("report_path", ""),
        }
    )
    return result


def _translation_workspace_find_review_row(status: dict, entry_id: str):
    for row in status.get("review_rows") or []:
        if not isinstance(row, dict):
            continue
        raw_locale = row.get("locale") or row.get("language", "")
        row_entry_ids = [
            row.get("safe_write_entry_id"),
            row.get("entry_id"),
            _translation_workspace_safe_write_entry_id(
                row.get("resource_id", ""),
                row.get("field") or row.get("key", ""),
                raw_locale,
                row.get("digest") or row.get("source_digest", ""),
            ),
            _translation_workspace_safe_write_entry_id(
                row.get("resource_id", ""),
                row.get("field") or row.get("key", ""),
                _translation_editor_canonical_locale(raw_locale),
                row.get("digest") or row.get("source_digest", ""),
            ),
        ]
        if entry_id in {str(row_entry_id or "").strip() for row_entry_id in row_entry_ids}:
            return row
    return None


def _translation_workspace_validate_manual_edit(row: dict, edited_value: str):
    edited_value = str(edited_value or "").strip()
    field = _translation_editor_normalize_field_key(
        (row or {}).get("field") or (row or {}).get("key") or ""
    )
    reasons = []
    seo_reasons = []
    draft_blocked = False
    product_identity_mismatch = False
    if not edited_value:
        reasons.append("draft_empty")
        draft_blocked = True
    if field == "title" and len(edited_value) > 80:
        reasons.append("product_title_over_80_chars")
    if field == "meta_title" and len(edited_value) > 60:
        reasons.append("seo_title_over_60_chars")
        seo_reasons.append("seo_title_over_60_chars")
    if field == "meta_description" and len(edited_value) > 160:
        reasons.append("seo_description_over_160_chars")
        seo_reasons.append("seo_description_over_160_chars")
    if FORBIDDEN_OUTPUT_RE.search(edited_value):
        reasons.append("forbidden_marketing_or_origin_phrase")
        seo_reasons.append("forbidden_marketing_or_shipping_phrase")
        draft_blocked = True

    identity_context = (row or {}).get("source_identity_context") or build_product_identity_context(
        source_values=[
            (row or {}).get("source_value")
            or (row or {}).get("source_value_display")
            or "",
        ]
    )
    identity = validate_product_identity_draft(identity_context, edited_value, field)
    if identity.get("draft_blocked"):
        reasons.append("product_identity_mismatch")
        product_identity_mismatch = True
        draft_blocked = True

    reasons = _translation_editor_unique_list(reasons)
    seo_reasons = _translation_editor_unique_list(seo_reasons)
    validation_status = (
        "draft_ready_for_manual_review"
        if not reasons and not draft_blocked
        else "draft_needs_manual_review"
    )
    seo_validation_status = "seo_needs_manual_review" if seo_reasons else "seo_ready"
    if draft_blocked:
        seo_validation_status = "seo_needs_manual_review"
    labels = _translation_workspace_human_reason_labels(reasons, row=row)
    return {
        "validation_status": validation_status,
        "seo_validation_status": seo_validation_status,
        "reasons": reasons,
        "seo_reasons": seo_reasons,
        "draft_blocked": draft_blocked,
        "product_identity_mismatch": product_identity_mismatch,
        "message": ", ".join(labels) if labels else "Manual edit is ready for review.",
    }


def _translation_workspace_recalculate_manual_edit_counts(status: dict):
    rows = [
        _translation_workspace_job_review_row(row)
        for row in (status.get("review_rows") or [])
        if isinstance(row, dict)
    ]
    blocked_by_locale = {}
    for row in rows:
        status_key, _status_label = _translation_workspace_result_row_status(row)
        if status_key == "needs_review":
            locale = row.get("locale") or row.get("language") or ""
            blocked_by_locale[locale] = blocked_by_locale.get(locale, 0) + 1
    counts = status.setdefault(
        "counts",
        _translation_workspace_empty_job_counts(status.get("selected_locales") or []),
    )
    counts["blocked_count"] = sum(blocked_by_locale.values())
    for locale_row in status.get("per_locale_status") or []:
        locale = locale_row.get("locale", "")
        if locale in blocked_by_locale:
            locale_row["blocked_count"] = blocked_by_locale[locale]


def start_translation_workspace_background_job(
    *,
    installation_id,
    product_gid: str,
    product_title: str = "",
    product_search_text: str = "",
    selected_locale: str = "",
    selected_locales: list[str] | tuple[str, ...] | None = None,
    editor_filter: str = "all",
    editor_search_query: str = "",
):
    normalized_gid = normalize_product_gid(product_gid or "") or ""
    if not normalized_gid:
        blocked_status = _translation_workspace_empty_job_status(
            product_gid="",
            product_title=product_title,
            status="failed",
            message="Select one product before starting background translation.",
        )
        return {
            "started": False,
            "duplicate": False,
            "action_status": "translation_draft_job_blocked",
            "message": blocked_status["status_message"],
            "job_status": _translation_workspace_job_status_for_view(blocked_status),
        }

    existing_status = _translation_workspace_active_job_status(normalized_gid)
    if existing_status:
        return {
            "started": False,
            "duplicate": True,
            "action_status": "translation_draft_job_already_running",
            "message": "A background translation is already running for this product.",
            "job_status": _translation_workspace_job_status_for_view(existing_status),
        }
    _translation_workspace_release_inactive_job_lock(normalized_gid)

    job_id = build_translation_job_id(normalized_gid)
    status = _translation_workspace_initial_job_status(
        job_id=job_id,
        product_gid=normalized_gid,
        product_title=product_title,
        product_search_text=product_search_text,
        selected_locale=selected_locale,
        selected_locales=selected_locales,
        editor_filter=editor_filter,
        editor_search_query=editor_search_query,
    )
    if not _translation_workspace_acquire_job_lock(status):
        existing_status = _translation_workspace_active_job_status(normalized_gid)
        if existing_status:
            return {
                "started": False,
                "duplicate": True,
                "action_status": "translation_draft_job_already_running",
                "message": "A background translation is already running for this product.",
                "job_status": _translation_workspace_job_status_for_view(existing_status),
            }
        status["status"] = "failed"
        status["finished_at"] = _translation_workspace_now_iso()
        status["current_step"] = "lock acquisition failed"
        status["status_message"] = "Could not acquire the local translation job lock."
        status["errors"].append(
            {
                "stage": "job_lock",
                "message": "Could not acquire the local translation job lock.",
            }
        )
        _translation_workspace_save_job_status(status)
        return {
            "started": False,
            "duplicate": False,
            "action_status": "translation_draft_job_blocked",
            "message": status["status_message"],
            "job_status": _translation_workspace_job_status_for_view(status),
        }

    try:
        _translation_workspace_save_job_status(status)
    except Exception:
        _translation_workspace_release_job_lock(normalized_gid, job_id)
        raise

    worker = threading.Thread(
        target=run_translation_workspace_background_job,
        kwargs={"installation_id": installation_id, "job_id": job_id},
        name=f"translation_workspace_{job_id}",
        daemon=False,
    )
    worker.start()
    return {
        "started": True,
        "duplicate": False,
        "action_status": "translation_draft_job_started",
        "message": (
            "Background translation started. You can leave this page and refresh status later."
        ),
        "job_status": _translation_workspace_job_status_for_view(status),
    }


def run_translation_workspace_background_job(*, installation_id, job_id: str):
    close_old_connections()
    status = _translation_workspace_load_job_status(job_id)
    if not status:
        close_old_connections()
        return
    product_gid = status.get("product_gid", "")
    try:
        installation = ShopifyInstallation.objects.filter(pk=installation_id).first()
        if installation is None:
            raise ShopifyTranslationConsoleError(
                "Shopify installation not found for background translation job."
            )

        status["status"] = "running"
        status["current_step"] = "starting"
        status["status_message"] = "Translation is running."
        _translation_workspace_touch_job(status)
        _translation_workspace_save_job_status(status)

        for locale in status.get("selected_locales") or []:
            _translation_workspace_mark_locale_running(status, locale)
            _translation_workspace_save_job_status(status)
            try:
                draft_result = generate_selected_product_missing_translation_draft_package(
                    product_id=product_gid,
                    target_locales=[locale],
                    fields=list(ALL_ELIGIBLE_DRAFT_SCOPES),
                    installation=installation,
                    include_missing=True,
                    include_outdated=True,
                    include_all_eligible_groups=True,
                    action_name=TRANSLATE_ALL_ACTION_NAME,
                )
                _attach_translation_console_draft_detail(
                    draft_result,
                    max_rows=TRANSLATION_CONSOLE_TRANSLATE_ALL_DETAIL_MAX_ROWS,
                )
                _translation_workspace_apply_locale_job_result(
                    status,
                    locale,
                    draft_result,
                )
            except Exception as exc:
                _translation_workspace_apply_locale_job_exception(
                    status,
                    locale,
                    exc,
                )
            _translation_workspace_refresh_job_progress(status)
            _translation_workspace_save_job_status(status)

        _translation_workspace_finalize_job_status(status)
    except Exception as exc:
        status["status"] = "failed"
        status["finished_at"] = _translation_workspace_now_iso()
        status["current_locale"] = ""
        status["current_group"] = ""
        status["current_step"] = "failed"
        status["status_message"] = "Translation failed before completion."
        _translation_workspace_append_job_error(
            status,
            "job_runner",
            _translation_workspace_safe_error_message(exc),
        )
    finally:
        status["updated_at"] = _translation_workspace_now_iso()
        _translation_workspace_refresh_job_progress(status)
        _translation_workspace_save_job_status(status)
        _translation_workspace_release_job_lock(product_gid, status.get("job_id", ""))
        close_old_connections()


def build_translation_job_id(product_gid: str):
    product_hash = _translation_workspace_product_hash(product_gid)
    timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    return f"translation_workspace_job_{product_hash}_{timestamp}_{secrets.token_hex(4)}"


def _translation_workspace_initial_job_status(
    *,
    job_id: str,
    product_gid: str,
    product_title: str = "",
    product_search_text: str = "",
    selected_locale: str = "",
    selected_locales: list[str] | tuple[str, ...] | None = None,
    editor_filter: str = "all",
    editor_search_query: str = "",
):
    now = _translation_workspace_now_iso()
    status = _translation_workspace_empty_job_status(
        product_gid=product_gid,
        product_title=product_title,
        status="pending",
        message="Translation is pending.",
        selected_locales=selected_locales,
    )
    status.update(
        {
            "job_id": job_id,
            "started_at": now,
            "updated_at": now,
            "finished_at": "",
            "selected_locale": selected_locale,
            "product_search_text": product_search_text,
            "editor_filter": editor_filter,
            "editor_search_query": editor_search_query,
            "report_path": _translation_workspace_display_path(
                _translation_workspace_job_report_path(job_id)
            ),
            "lock_path": _translation_workspace_display_path(
                _translation_workspace_job_lock_path(product_gid)
            ),
        }
    )
    return status


def _translation_workspace_empty_job_status(
    *,
    product_gid: str,
    product_title: str = "",
    status: str = "pending",
    message: str = "",
    selected_locales: list[str] | tuple[str, ...] | None = None,
):
    selected_locales = _translation_workspace_normalized_job_locales(selected_locales)
    selected_groups = list(TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS)
    return {
        "job_id": "",
        "product_gid": product_gid,
        "product_title": _translation_workspace_safe_text(product_title, 200),
        "selected_locales": selected_locales,
        "selected_groups": selected_groups,
        "status": status,
        "status_message": message,
        "started_at": "",
        "updated_at": "",
        "finished_at": "",
        "current_locale": "",
        "current_group": "",
        "current_step": "pending",
        "per_locale_status": [
            _translation_workspace_empty_locale_status(locale)
            for locale in selected_locales
        ],
        "per_group_status": [
            _translation_workspace_empty_group_status(group)
            for group in selected_groups
        ],
        "counts": _translation_workspace_empty_job_counts(selected_locales),
        "errors": [],
        "detail_preview_rows": [],
        "review_rows": [],
        "review_rows_truncated": False,
        "report_path": "",
        "lock_path": "",
        "safety_flags": _translation_workspace_job_safety_flags(),
        **_translation_workspace_job_safety_flags(),
    }


def _translation_workspace_normalized_job_locales(selected_locales):
    locales = []
    for raw_locale in selected_locales or SUPPORTED_TRANSLATION_LOCALES:
        locale = _translation_editor_canonical_locale(raw_locale)
        if locale in SUPPORTED_TRANSLATION_LOCALES and locale not in locales:
            locales.append(locale)
    return locales or list(SUPPORTED_TRANSLATION_LOCALES)


def _translation_workspace_empty_job_counts(selected_locales):
    return {
        "total_locales": len(selected_locales or []),
        "completed_locales": 0,
        "failed_locales": 0,
        "skipped_locales": 0,
        "stale_locales": 0,
        "processed_locales": 0,
        "total_rows_checked": 0,
        "missing_draft_count": 0,
        "outdated_update_draft_count": 0,
        "already_translated_skipped_count": 0,
        "not_eligible_skipped_count": 0,
        "blocked_count": 0,
        "generated_draft_count": 0,
        "skipped_count": 0,
        "openai_call_count": 0,
        "reused_cache_count": 0,
        "skipped_existing_count": 0,
        "skipped_technical_count": 0,
        "deduplicated_input_count": 0,
        "estimated_input_chars_saved": 0,
        "per_locale_openai_call_count": {},
    }


def _translation_workspace_empty_locale_status(locale: str):
    return {
        "locale": locale,
        "locale_label": _translation_editor_locale_label(locale),
        "status": "pending",
        "status_label": "Waiting",
        "current_step": "",
        "started_at": "",
        "updated_at": "",
        "finished_at": "",
        "heartbeat_at": "",
        "source_rows_checked": 0,
        "missing_draft_count": 0,
        "outdated_update_draft_count": 0,
        "already_translated_skipped_count": 0,
        "not_eligible_skipped_count": 0,
        "blocked_count": 0,
        "generated_draft_count": 0,
        "message": "Waiting to start.",
        "error_message": "",
        "failure_type": "",
        "failed_stage": "",
        "sanitized_error": "",
        "retry_attempted": False,
        "retry_succeeded": False,
        "blocking_conditions": [],
    }


def _translation_workspace_empty_group_status(group_key: str):
    return {
        "group_key": group_key,
        "label": _translation_workspace_group_label(group_key),
        "status": "pending",
        "status_label": "Pending",
        "source_rows_checked": 0,
        "missing_draft_count": 0,
        "outdated_update_draft_count": 0,
        "already_translated_skipped_count": 0,
        "not_eligible_skipped_count": 0,
        "blocked_count": 0,
        "generated_draft_count": 0,
        "message": "",
    }


def _translation_workspace_job_safety_flags():
    return {
        "job_started_by": "user_action",
        "polling_read_only": True,
        "auto_start_blocked": True,
        "shopify_read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _translation_workspace_mark_locale_running(status: dict, locale: str):
    now = _translation_workspace_now_iso()
    status["status"] = "running"
    status["current_locale"] = locale
    status["current_group"] = "all eligible content"
    status["current_step"] = "reading source rows and preparing translation results"
    status["status_message"] = "Translation is running."
    status["updated_at"] = now
    locale_row = _translation_workspace_locale_row(status, locale)
    locale_row.update(
        {
            "status": "running",
            "status_label": "Translating now",
            "current_step": status["current_step"],
            "started_at": locale_row.get("started_at") or now,
            "updated_at": now,
            "heartbeat_at": now,
            "message": "Translation is still running for this language.",
            "error_message": "",
        }
    )
    for group_row in status.get("per_group_status") or []:
        if group_row.get("status") in {"pending", "completed"}:
            group_row["status"] = "running"
            group_row["status_label"] = "Running"


def _translation_workspace_apply_locale_job_result(
    status: dict,
    locale: str,
    draft_result: dict,
):
    now = _translation_workspace_now_iso()
    summary = dict((draft_result or {}).get("translate_all_summary") or {})
    blocking_conditions = [
        _translation_workspace_safe_text(item, 120)
        for item in (draft_result or {}).get("blocking_conditions") or []
        if item
    ]
    locale_failed = bool(blocking_conditions) or not bool(
        (draft_result or {}).get("success")
    )
    locale_row = _translation_workspace_locale_row(status, locale)
    locale_label = _translation_editor_locale_label(locale)
    source_rows_checked = int(summary.get("total_source_rows_checked") or 0)
    missing_count = int(summary.get("missing_drafts_generated") or 0)
    outdated_count = int(summary.get("outdated_update_drafts_generated") or 0)
    blocked_count = int(summary.get("needs_review_blocked") or 0)
    openai_call_count = int(
        summary.get("openai_call_count")
        or (draft_result or {}).get("openai_call_count")
        or 0
    )
    reused_cache_count = int(
        summary.get("reused_cache_count")
        or (draft_result or {}).get("reused_cache_count")
        or 0
    )
    skipped_existing_count = int(
        summary.get("skipped_existing_count")
        or (draft_result or {}).get("skipped_existing_count")
        or 0
    )
    skipped_technical_count = int(
        summary.get("skipped_technical_count")
        or (draft_result or {}).get("skipped_technical_count")
        or 0
    )
    deduplicated_input_count = int(
        summary.get("deduplicated_input_count")
        or (draft_result or {}).get("deduplicated_input_count")
        or 0
    )
    estimated_input_chars_saved = int(
        summary.get("estimated_input_chars_saved")
        or (draft_result or {}).get("estimated_input_chars_saved")
        or 0
    )
    locale_status = (
        "failed"
        if locale_failed
        else ("skipped" if source_rows_checked == 0 else "completed")
    )
    failure_type = str((draft_result or {}).get("failure_type") or "")
    failed_stage = str((draft_result or {}).get("failed_stage") or "")
    sanitized_error = _translation_workspace_safe_text(
        (draft_result or {}).get("sanitized_error") or "",
        500,
    )
    retry_attempted = bool((draft_result or {}).get("retry_attempted"))
    retry_succeeded = bool((draft_result or {}).get("retry_succeeded"))
    locale_error_message = ""
    if locale_status == "failed":
        if failure_type == OPENAI_INVALID_TRANSLATION_RESPONSE:
            locale_error_message = (
                f"{locale_label} translation failed because OpenAI returned an invalid response format. "
                "Retry this language."
            )
            failed_stage = failed_stage or OPENAI_TRANSLATION_GENERATION_STAGE
            sanitized_error = sanitized_error or OPENAI_TRANSLATIONS_MISSING_MESSAGE
        else:
            locale_error_message = _translation_workspace_safe_text(
                (draft_result or {}).get("error")
                or ", ".join(blocking_conditions)
                or f"Translation failed for {locale_label}.",
                500,
            )
    locale_row.update(
        {
            "status": locale_status,
            "status_label": _translation_workspace_locale_status_label(locale_status),
            "current_step": locale_status,
            "updated_at": now,
            "finished_at": now,
            "heartbeat_at": now,
            "source_rows_checked": source_rows_checked,
            "missing_draft_count": missing_count,
            "outdated_update_draft_count": outdated_count,
            "already_translated_skipped_count": int(
                summary.get("already_translated_skipped") or 0
            ),
            "not_eligible_skipped_count": int(
                summary.get("not_eligible_skipped") or 0
            ),
            "blocked_count": blocked_count,
            "generated_draft_count": missing_count + outdated_count,
            "openai_call_count": openai_call_count,
            "openai_retry_attempt_count": int(
                summary.get("openai_retry_attempt_count")
                or (draft_result or {}).get("openai_retry_attempt_count")
                or 0
            ),
            "openai_retry_success_count": int(
                summary.get("openai_retry_success_count")
                or (draft_result or {}).get("openai_retry_success_count")
                or 0
            ),
            "reused_cache_count": reused_cache_count,
            "skipped_existing_count": skipped_existing_count,
            "skipped_technical_count": skipped_technical_count,
            "deduplicated_input_count": deduplicated_input_count,
            "estimated_input_chars_saved": estimated_input_chars_saved,
            "blocking_conditions": blocking_conditions,
            "message": _translation_workspace_locale_status_message(
                locale_status,
                locale_label=locale_label,
            ),
            "error_message": locale_error_message,
            "failure_type": failure_type,
            "failed_stage": failed_stage,
            "sanitized_error": sanitized_error,
            "retry_attempted": retry_attempted,
            "retry_succeeded": retry_succeeded,
        }
    )
    if (draft_result or {}).get("product_title") and not status.get("product_title"):
        status["product_title"] = _translation_workspace_safe_text(
            draft_result.get("product_title"), 200
        )
    _translation_workspace_add_counts(status, locale_row)
    _translation_workspace_apply_group_counts(status, summary)
    _translation_workspace_append_child_discovery_errors(status, locale, summary)
    _translation_workspace_append_locale_preview_rows(status, draft_result)
    if locale_failed:
        _translation_workspace_append_job_error(
            status,
            failed_stage or f"locale_{locale}",
            locale_error_message or "Locale draft generation failed.",
            locale=locale,
            reason=failure_type,
        )
    _translation_workspace_touch_job(status)


def _translation_workspace_apply_locale_job_exception(status: dict, locale: str, exc):
    now = _translation_workspace_now_iso()
    message = _translation_workspace_safe_error_message(exc)
    locale_label = _translation_editor_locale_label(locale)
    locale_row = _translation_workspace_locale_row(status, locale)
    locale_row.update(
        {
            "status": "failed",
            "status_label": _translation_workspace_locale_status_label("failed"),
            "current_step": "failed",
            "updated_at": now,
            "finished_at": now,
            "heartbeat_at": now,
            "message": _translation_workspace_locale_status_message(
                "failed",
                locale_label=locale_label,
            ),
            "error_message": message,
            "blocking_conditions": [type(exc).__name__],
        }
    )
    _translation_workspace_append_job_error(status, f"locale_{locale}", message)
    for group_row in status.get("per_group_status") or []:
        if group_row.get("status") == "running":
            group_row["status"] = "partial"
            group_row["status_label"] = "Partial"
            group_row["message"] = "At least one locale failed for this group."
    _translation_workspace_touch_job(status)


def _translation_workspace_add_counts(status: dict, locale_row: dict):
    counts = status.setdefault(
        "counts",
        _translation_workspace_empty_job_counts(status.get("selected_locales") or []),
    )
    counts["total_rows_checked"] += int(locale_row.get("source_rows_checked") or 0)
    counts["missing_draft_count"] += int(locale_row.get("missing_draft_count") or 0)
    counts["outdated_update_draft_count"] += int(
        locale_row.get("outdated_update_draft_count") or 0
    )
    counts["already_translated_skipped_count"] += int(
        locale_row.get("already_translated_skipped_count") or 0
    )
    counts["not_eligible_skipped_count"] += int(
        locale_row.get("not_eligible_skipped_count") or 0
    )
    counts["blocked_count"] += int(locale_row.get("blocked_count") or 0)
    counts["generated_draft_count"] = (
        counts["missing_draft_count"] + counts["outdated_update_draft_count"]
    )
    counts["skipped_count"] = (
        counts["already_translated_skipped_count"]
        + counts["not_eligible_skipped_count"]
    )
    counts["openai_call_count"] += int(locale_row.get("openai_call_count") or 0)
    counts["reused_cache_count"] += int(locale_row.get("reused_cache_count") or 0)
    counts["skipped_existing_count"] += int(
        locale_row.get("skipped_existing_count") or 0
    )
    counts["skipped_technical_count"] += int(
        locale_row.get("skipped_technical_count") or 0
    )
    counts["deduplicated_input_count"] += int(
        locale_row.get("deduplicated_input_count") or 0
    )
    counts["estimated_input_chars_saved"] += int(
        locale_row.get("estimated_input_chars_saved") or 0
    )
    per_locale_openai = counts.setdefault("per_locale_openai_call_count", {})
    locale = locale_row.get("locale", "")
    if locale:
        per_locale_openai[locale] = int(locale_row.get("openai_call_count") or 0)


def _translation_workspace_apply_group_counts(status: dict, summary: dict):
    discovery_status = dict(summary.get("per_group_discovery_status") or {})
    section_rows = {
        row.get("section"): row
        for row in (summary.get("per_section_counts") or [])
        if isinstance(row, dict)
    }
    for group_row in status.get("per_group_status") or []:
        group_key = group_row.get("group_key")
        section = section_rows.get(group_key) or {}
        missing_count = int(section.get("missing_drafts_generated") or 0)
        outdated_count = int(section.get("outdated_update_drafts_generated") or 0)
        group_row["source_rows_checked"] += int(
            section.get("source_rows_checked") or 0
        )
        group_row["missing_draft_count"] += missing_count
        group_row["outdated_update_draft_count"] += outdated_count
        group_row["already_translated_skipped_count"] += int(
            section.get("already_translated_skipped") or 0
        )
        group_row["not_eligible_skipped_count"] += int(
            section.get("not_eligible_skipped") or 0
        )
        group_row["blocked_count"] += int(section.get("needs_review_blocked") or 0)
        group_row["generated_draft_count"] = (
            group_row["missing_draft_count"] + group_row["outdated_update_draft_count"]
        )
        discovery_key = "media_alt_text" if group_key == "media" else group_key
        if discovery_status.get(discovery_key) in {"skipped", "failed"}:
            group_row["status"] = "partial"
            group_row["status_label"] = "Partial"
            group_row["message"] = "Optional read-only discovery failed for this group."
        elif group_row.get("status") == "running":
            group_row["status"] = "completed"
            group_row["status_label"] = "Completed"


def _translation_workspace_append_child_discovery_errors(
    status: dict,
    locale: str,
    summary: dict,
):
    for error in summary.get("child_resource_discovery_errors") or []:
        if len(status.setdefault("errors", [])) >= TRANSLATION_WORKSPACE_JOB_ERROR_LIMIT:
            return
        if not isinstance(error, dict):
            continue
        _translation_workspace_append_job_error(
            status,
            error.get("stage") or f"locale_{locale}_discovery",
            error.get("message") or error.get("reason") or "Child discovery failed.",
            locale=locale,
            reason=error.get("reason", ""),
            query_failure_type=error.get("query_failure_type", ""),
        )


def _translation_workspace_append_locale_preview_rows(status: dict, draft_result: dict):
    detail = (draft_result or {}).get("translation_console_detail") or {}
    all_rows = [
        row for row in (detail.get("all_entries") or []) if isinstance(row, dict)
    ]

    review_rows = status.setdefault("review_rows", [])
    review_remaining = TRANSLATION_WORKSPACE_JOB_REVIEW_ROW_LIMIT - len(review_rows)
    if review_remaining > 0:
        for row in all_rows[:review_remaining]:
            review_rows.append(_translation_workspace_job_review_row(row))
    if len(all_rows) > review_remaining or detail.get("all_entries_truncated"):
        status["review_rows_truncated"] = True

    preview_rows = status.setdefault("detail_preview_rows", [])
    remaining = TRANSLATION_WORKSPACE_JOB_DETAIL_PREVIEW_LIMIT - len(preview_rows)
    if remaining <= 0:
        status["detail_preview_truncated"] = True
        return
    for row in all_rows[:remaining]:
        preview_rows.append(
            {
                "locale": row.get("locale", ""),
                "section": row.get("section", ""),
                "key": row.get("key", ""),
                "status": row.get("status", ""),
                "reason": row.get("reason", ""),
                "source_value_preview": row.get("source_value_preview", ""),
                "existing_translation_preview": row.get(
                    "existing_translation_preview", ""
                ),
                "proposed_translation_preview": row.get(
                    "proposed_translation_preview", ""
                ),
            }
        )
    if detail.get("all_entries_truncated") or len(all_rows) > remaining:
        status["detail_preview_truncated"] = True


def _translation_workspace_finalize_job_status(status: dict):
    _translation_workspace_refresh_job_progress(status)
    counts = status.get("counts") or {}
    failed = int(counts.get("failed_locales") or 0)
    completed = int(counts.get("completed_locales") or 0)
    skipped = int(counts.get("skipped_locales") or 0)
    stale = int(counts.get("stale_locales") or 0)
    total = int(counts.get("total_locales") or 0)
    has_errors = bool(status.get("errors"))
    has_blocked = int(counts.get("blocked_count") or 0) > 0
    if total and failed == total:
        final_status = "failed"
        message = "Translation failed. Preview only - Shopify has not been updated yet."
    elif failed or skipped or stale or has_errors or has_blocked:
        final_status = "partial"
        message = "Translation completed with warnings. Preview only - Shopify has not been updated yet."
    else:
        final_status = "completed"
        message = "Translation completed. Preview only - Shopify has not been updated yet."
    status["status"] = final_status
    status["finished_at"] = _translation_workspace_now_iso()
    status["current_locale"] = ""
    status["current_group"] = ""
    status["current_step"] = final_status
    status["status_message"] = message
    for group_row in status.get("per_group_status") or []:
        if group_row.get("status") in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES:
            group_row["status"] = (
                "completed" if final_status == "completed" else final_status
            )
            group_row["status_label"] = (
                "Completed"
                if final_status == "completed"
                else _translation_workspace_job_status_label(final_status)
            )
    counts["completed_locales"] = min(completed, total)


def _translation_workspace_refresh_job_progress(status: dict):
    counts = status.setdefault(
        "counts",
        _translation_workspace_empty_job_counts(status.get("selected_locales") or []),
    )
    locale_rows = status.get("per_locale_status") or []
    counts["total_locales"] = len(status.get("selected_locales") or locale_rows)
    counts["completed_locales"] = sum(
        1 for row in locale_rows if row.get("status") == "completed"
    )
    counts["failed_locales"] = sum(
        1 for row in locale_rows if row.get("status") == "failed"
    )
    counts["skipped_locales"] = sum(
        1 for row in locale_rows if row.get("status") == "skipped"
    )
    counts["stale_locales"] = sum(
        1 for row in locale_rows if row.get("status") == "stale"
    )
    counts["processed_locales"] = sum(
        1
        for row in locale_rows
        if row.get("status") in TRANSLATION_WORKSPACE_LOCALE_TERMINAL_STATUSES
    )
    counts["total_rows_checked"] = sum(
        int(row.get("source_rows_checked") or 0) for row in locale_rows
    )
    counts["missing_draft_count"] = sum(
        int(row.get("missing_draft_count") or 0) for row in locale_rows
    )
    counts["outdated_update_draft_count"] = sum(
        int(row.get("outdated_update_draft_count") or 0) for row in locale_rows
    )
    counts["already_translated_skipped_count"] = sum(
        int(row.get("already_translated_skipped_count") or 0) for row in locale_rows
    )
    counts["not_eligible_skipped_count"] = sum(
        int(row.get("not_eligible_skipped_count") or 0) for row in locale_rows
    )
    counts["blocked_count"] = sum(
        int(row.get("blocked_count") or 0) for row in locale_rows
    )
    counts["generated_draft_count"] = (
        int(counts.get("missing_draft_count") or 0)
        + int(counts.get("outdated_update_draft_count") or 0)
    )
    counts["skipped_count"] = (
        int(counts.get("already_translated_skipped_count") or 0)
        + int(counts.get("not_eligible_skipped_count") or 0)
    )
    processed = counts["processed_locales"]
    total = counts["total_locales"] or 0
    status["progress_percent"] = int((processed / total) * 100) if total else 0
    status.update(_translation_workspace_job_safety_flags())
    status["safety_flags"] = _translation_workspace_job_safety_flags()


def _translation_workspace_touch_job(status: dict):
    status["updated_at"] = _translation_workspace_now_iso()


def _translation_workspace_locale_row(status: dict, locale: str):
    for row in status.setdefault("per_locale_status", []):
        if row.get("locale") == locale:
            return row
    row = _translation_workspace_empty_locale_status(locale)
    status["per_locale_status"].append(row)
    return row


def _translation_workspace_group_label(group_key: str):
    for option in TRANSLATION_WORKSPACE_DRAFT_GROUPS:
        if option.get("value") == group_key:
            return option.get("label", group_key)
    return group_key


def _translation_workspace_job_safe_summary(job_status: dict | None):
    status = job_status or {}
    counts = status.get("counts") or {}
    return {
        "job_id": status.get("job_id", ""),
        "product_gid": status.get("product_gid", ""),
        "product_title": status.get("product_title", ""),
        "status": status.get("status", ""),
        "progress_percent": status.get("progress_percent", 0),
        "completed_locales": counts.get("completed_locales", 0),
        "failed_locales": counts.get("failed_locales", 0),
        "skipped_locales": counts.get("skipped_locales", 0),
        "stale_locales": counts.get("stale_locales", 0),
        "generated_draft_count": counts.get("generated_draft_count", 0),
        "skipped_count": counts.get("skipped_count", 0),
        "report_path": status.get("report_path", ""),
        "job_started_by": status.get("job_started_by", "user_action"),
        "polling_read_only": bool(status.get("polling_read_only", True)),
        "auto_start_blocked": bool(status.get("auto_start_blocked", True)),
        "shopify_read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _translation_workspace_job_status_for_view(status: dict):
    if not status:
        return {}
    _translation_workspace_refresh_job_progress(status)
    view = dict(status)
    view["exists"] = bool(status.get("job_id"))
    view["is_active"] = status.get("status") in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES
    view["status_label"] = _translation_workspace_job_status_label(status.get("status"))
    view["status_key"] = str(status.get("status") or "unknown").replace(" ", "_")
    view["detail_anchor"] = "translation-background-job-details"
    view["current_locale_label"] = (
        _translation_editor_locale_label(view.get("current_locale", ""))
        if view.get("current_locale")
        else ""
    )
    view["current_group_label"] = (
        _translation_workspace_group_label(view.get("current_group", ""))
        if view.get("current_group")
        else ""
    )
    for index, row in enumerate(view.get("per_locale_status") or []):
        view["per_locale_status"][index] = _translation_workspace_locale_status_view(row)
    for row in view.get("per_group_status") or []:
        row["status_label"] = _translation_workspace_title_status(row.get("status"))
        row["status_key"] = str(row.get("status") or "unknown").replace(" ", "_")
    _translation_workspace_attach_report_detail_view(view)
    compact_status = _translation_workspace_compact_job_status(view)
    view["compact_status_key"] = compact_status["key"]
    view["compact_status_label"] = compact_status["label"]
    return view


def _translation_workspace_job_status_for_json(status: dict):
    if not status:
        status = _translation_workspace_not_started_job_status("")
    _translation_workspace_refresh_job_progress(status)
    view = dict(status)
    view["exists"] = bool(status.get("job_id"))
    view["is_active"] = status.get("status") in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES
    view["status_label"] = _translation_workspace_job_status_label(status.get("status"))
    view["status_key"] = str(status.get("status") or "unknown").replace(" ", "_")
    counts = dict(view.get("counts") or {})
    locale_rows = _translation_workspace_progress_rows(
        view.get("per_locale_status") or [],
        row_type="locale",
    )
    group_rows = _translation_workspace_progress_rows(
        view.get("per_group_status") or [],
        row_type="group",
    )
    safety_flags = {
        **_translation_workspace_job_safety_flags(),
        **dict(view.get("safety_flags") or {}),
    }
    status_value = view.get("status") or "not_started"
    translation_result_count = _translation_workspace_translation_result_count(
        _translation_workspace_job_review_rows(view)
    )
    view["translation_result_count"] = translation_result_count
    compact_status = _translation_workspace_compact_job_status(view)
    return {
        "exists": bool(view.get("exists")),
        "job_id": view.get("job_id", ""),
        "product_gid": view.get("product_gid", ""),
        "product_title": view.get("product_title", ""),
        "status": status_value,
        "status_label": view.get("status_label")
        or _translation_workspace_job_status_label(status_value),
        "status_key": view.get("status_key")
        or str(status_value).replace(" ", "_"),
        "compact_status_label": compact_status["label"],
        "compact_status_key": compact_status["key"],
        "status_message": view.get("status_message", ""),
        "progress_percent": _translation_workspace_int(
            view.get("progress_percent"), 0
        ),
        "current_locale": view.get("current_locale", ""),
        "current_locale_label": _translation_editor_locale_label(
            view.get("current_locale", "")
        )
        if view.get("current_locale")
        else "",
        "current_group": view.get("current_group", ""),
        "current_group_label": _translation_workspace_group_label(
            view.get("current_group", "")
        )
        if view.get("current_group")
        else "",
        "completed_locales": _translation_workspace_int(
            counts.get("completed_locales"), 0
        ),
        "total_locales": _translation_workspace_int(counts.get("total_locales"), 0),
        "failed_locales": _translation_workspace_int(counts.get("failed_locales"), 0),
        "skipped_locales": _translation_workspace_int(
            counts.get("skipped_locales"), 0
        ),
        "stale_locales": _translation_workspace_int(counts.get("stale_locales"), 0),
        "processed_locales": _translation_workspace_int(
            counts.get("processed_locales"), 0
        ),
        "generated_draft_count": _translation_workspace_int(
            counts.get("generated_draft_count"), 0
        ),
        "skipped_count": _translation_workspace_int(counts.get("skipped_count"), 0),
        "blocked_count": _translation_workspace_int(counts.get("blocked_count"), 0),
        "updated_at": view.get("updated_at", ""),
        "finished_at": view.get("finished_at", ""),
        "report_path": view.get("report_path", ""),
        "counts": counts,
        "per_locale_progress": locale_rows,
        "per_group_progress": group_rows,
        "per_locale_status": locale_rows,
        "per_group_status": group_rows,
        "safety_flags": safety_flags,
        "job_started_by": safety_flags["job_started_by"],
        "polling_read_only": safety_flags["polling_read_only"],
        "auto_start_blocked": safety_flags["auto_start_blocked"],
        "shopify_read_only": safety_flags["shopify_read_only"],
        "shopify_write_performed": safety_flags["shopify_write_performed"],
        "mutation_performed": safety_flags["mutation_performed"],
        "translations_register_called": safety_flags["translations_register_called"],
        "publish_performed": safety_flags["publish_performed"],
        "apply_performed": safety_flags["apply_performed"],
        "rollback_performed": safety_flags["rollback_performed"],
        "polling_should_continue": status_value
        in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES,
        "terminal": status_value in TRANSLATION_WORKSPACE_JOB_TERMINAL_STATUSES,
        "local_report_read_only": True,
        "translation_result_count": translation_result_count,
    }


def _translation_workspace_progress_rows(rows: list[dict], *, row_type: str):
    progress_rows = []
    for row in rows:
        item = dict(row)
        status_value = item.get("status") or "pending"
        item["status_label"] = item.get("status_label") or _translation_workspace_title_status(
            status_value
        )
        item["status_key"] = item.get("status_key") or str(status_value).replace(
            " ", "_"
        )
        skipped_count = _translation_workspace_int(
            item.get("already_translated_skipped_count"), 0
        ) + _translation_workspace_int(item.get("not_eligible_skipped_count"), 0)
        item["skipped_count"] = skipped_count
        if row_type == "locale":
            item = _translation_workspace_locale_status_view(item)
        elif row_type == "group":
            item["label"] = item.get("label") or _translation_workspace_group_label(
                item.get("group_key", "")
            )
        progress_rows.append(item)
    return progress_rows


def _translation_workspace_not_started_job_status(product_gid: str):
    status = _translation_workspace_empty_job_status(
        product_gid=product_gid,
        status="not_started",
        message="No background translation has been recorded for this product.",
    )
    status["current_step"] = "not_started"
    status["progress_percent"] = 0
    status["selected_locales"] = []
    status["selected_groups"] = []
    status["per_locale_status"] = []
    status["per_group_status"] = []
    status["counts"] = _translation_workspace_empty_job_counts([])
    return status


def _translation_workspace_valid_job_id(job_id: str):
    return bool(TRANSLATION_WORKSPACE_JOB_ID_RE.match(str(job_id or "")))


def _translation_workspace_int(value, default: int = 0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _translation_workspace_attach_report_detail_view(view: dict):
    review_rows = _translation_workspace_job_review_rows(view)
    translation_result_count = _translation_workspace_translation_result_count(
        review_rows
    )
    translation_result_groups = _translation_workspace_translation_result_groups(
        review_rows,
        SUPPORTED_TRANSLATION_LOCALES,
        view.get("per_locale_status") or [],
    )
    view["review_rows"] = review_rows
    view["review_row_count"] = len(review_rows)
    view["translation_result_groups"] = translation_result_groups
    view["translation_result_count"] = translation_result_count
    view["show_translation_results"] = bool(view.get("exists")) or translation_result_count > 0
    view["translation_result_status_label"] = _translation_workspace_job_status_label(
        view.get("status")
    )
    view["report_detail_summary"] = _translation_workspace_report_detail_summary(view)
    view["review_filter_options"] = _translation_workspace_review_filter_options(
        review_rows
    )
    view["blocked_reason_summary"] = _translation_workspace_reason_summary(review_rows)
    view["apply_readiness_summary"] = _translation_workspace_apply_readiness_summary(
        review_rows
    )
    view["report_diagnostics"] = _translation_workspace_report_diagnostics(
        view,
        review_rows,
    )


def _translation_workspace_translation_result_count(review_rows: list[dict]):
    return sum(
        1 for row in review_rows or [] if _translation_workspace_should_show_result_row(row)
    )


def _translation_workspace_translation_result_groups(
    review_rows: list[dict],
    locales: list[str] | tuple[str, ...] | None = None,
    locale_status_rows: list[dict] | tuple[dict, ...] | None = None,
):
    language_groups = []
    language_lookup = {}
    locale_status_lookup = {
        _translation_editor_canonical_locale(row.get("locale")): _translation_workspace_locale_status_view(row)
        for row in (locale_status_rows or [])
        if isinstance(row, dict) and _translation_editor_canonical_locale(row.get("locale"))
    }

    def language_group_for(language: str):
        language = _translation_editor_canonical_locale(language) or "-"
        language_group = language_lookup.get(language)
        if language_group:
            return language_group
        locale_status = locale_status_lookup.get(language) or _translation_workspace_locale_status_view(
            {"locale": language}
        )
        locale_skipped_count = _translation_workspace_int(
            locale_status.get("skipped_count"), 0
        ) or (
            _translation_workspace_int(
                locale_status.get("already_translated_skipped_count"), 0
            )
            + _translation_workspace_int(
                locale_status.get("not_eligible_skipped_count"), 0
            )
        )
        language_group = {
            "language": language,
            "language_label": _translation_editor_locale_label(language),
            "count": 0,
            "translated_count": 0,
            "needs_review_count": 0,
            "skipped_count": 0,
            "source_rows_checked": int(locale_status.get("source_rows_checked") or 0),
            "openai_call_count": _translation_workspace_int(
                locale_status.get("openai_call_count"), 0
            ),
            "reused_cache_count": _translation_workspace_int(
                locale_status.get("reused_cache_count"), 0
            ),
            "skipped_existing_count": _translation_workspace_int(
                locale_status.get("skipped_existing_count"), 0
            ),
            "skipped_technical_count": _translation_workspace_int(
                locale_status.get("skipped_technical_count"), 0
            ),
            "deduplicated_input_count": _translation_workspace_int(
                locale_status.get("deduplicated_input_count"), 0
            ),
            "estimated_input_chars_saved": _translation_workspace_int(
                locale_status.get("estimated_input_chars_saved"), 0
            ),
            "status_key": locale_status.get("status_key") or "pending",
            "status_label": locale_status.get("status_label") or "Waiting",
            "lifecycle_status": locale_status.get("status") or "pending",
            "is_default": False,
            "empty_message": _translation_workspace_language_empty_message(
                locale_status
            ),
            "error_message": locale_status.get("error_message", ""),
            "retry_allowed": bool(locale_status.get("retry_allowed")),
            "groups": [],
            "_status_counts": {
                "translated_count": _translation_workspace_int(
                    locale_status.get("generated_draft_count"), 0
                )
                or (
                    _translation_workspace_int(
                        locale_status.get("missing_draft_count"), 0
                    )
                    + _translation_workspace_int(
                        locale_status.get("outdated_update_draft_count"), 0
                    )
                ),
                "needs_review_count": _translation_workspace_int(
                    locale_status.get("blocked_count"), 0
                ),
                "skipped_count": locale_skipped_count,
            },
            "_group_lookup": {},
        }
        language_lookup[language] = language_group
        language_groups.append(language_group)
        return language_group

    for locale in locales or []:
        language_group_for(locale)

    for row in review_rows or []:
        if not _translation_workspace_should_show_result_row(row):
            continue
        language = (
            _translation_editor_canonical_locale(row.get("language") or row.get("locale"))
            or "-"
        )
        language_group = language_group_for(language)
        group_key = str(row.get("group_key") or "").strip() or "other"
        group_lookup = language_group["_group_lookup"]
        content_group = group_lookup.get(group_key)
        if not content_group:
            content_group = {
                "group_key": group_key,
                "group_label": row.get("group_label")
                or _translation_workspace_group_label(group_key),
                "tab_label": _translation_workspace_result_group_tab_label(group_key),
                "is_primary": group_key in TRANSLATION_WORKSPACE_RESULT_PRIMARY_GROUPS,
                "count": 0,
                "translated_count": 0,
                "needs_review_count": 0,
                "skipped_count": 0,
                "rows": [],
            }
            group_lookup[group_key] = content_group
            language_group["groups"].append(content_group)
        display_row = _translation_workspace_result_card_row(row)
        is_translated = bool(display_row.get("has_generated_draft"))
        is_needs_review = display_row.get("result_status_key") == "needs_review"
        is_skipped = (
            not is_translated
            or display_row.get("result_status_key")
            in {"already_up_to_date", "not_translated_automatically"}
        )
        content_group["rows"].append(display_row)
        content_group["count"] += 1
        content_group["translated_count"] += 1 if is_translated else 0
        content_group["needs_review_count"] += 1 if is_needs_review else 0
        content_group["skipped_count"] += 1 if is_skipped else 0
        language_group["count"] += 1
        language_group["translated_count"] += 1 if is_translated else 0
        language_group["needs_review_count"] += 1 if is_needs_review else 0
        language_group["skipped_count"] += 1 if is_skipped else 0
    for language_group in language_groups:
        status_counts = language_group.pop("_status_counts", {})
        if int(language_group.get("count") or 0) == 0:
            language_group["translated_count"] = int(
                status_counts.get("translated_count") or 0
            )
            language_group["needs_review_count"] = int(
                status_counts.get("needs_review_count") or 0
            )
            language_group["skipped_count"] = int(
                status_counts.get("skipped_count") or 0
            )
        language_group.pop("_group_lookup", None)
        if int(language_group.get("count") or 0) > 0 and language_group.get(
            "lifecycle_status"
        ) not in {"failed", "stale", "running"}:
            language_group.update(
                _translation_workspace_language_group_status(language_group)
            )
        language_group["tab_summary"] = _translation_workspace_language_tab_summary(
            language_group
        )
        language_group["groups"].sort(
            key=lambda group: (
                TRANSLATION_WORKSPACE_RESULT_GROUP_ORDER.get(
                    group["group_key"],
                    999,
                ),
                group["group_label"],
            )
        )
        for group in language_group["groups"]:
            group["rows"].sort(key=_translation_workspace_result_row_order_key)
            group.update(_translation_workspace_language_group_status(group))
    default_language_group = next(
        (
            language_group
            for language_group in language_groups
            if int(language_group.get("count") or 0) > 0
        ),
        language_groups[0] if language_groups else None,
    )
    if default_language_group:
        default_language_group["is_default"] = True
    return language_groups


def _translation_workspace_result_row_order_key(row: dict):
    field = str(row.get("field") or row.get("key") or "").strip()
    normalized_field = _translation_editor_normalize_field_key(field)
    field_order = TRANSLATION_WORKSPACE_RESULT_FIELD_ORDER.get(
        normalized_field,
        TRANSLATION_WORKSPACE_RESULT_FIELD_ORDER.get(field, 999),
    )
    group_order = TRANSLATION_WORKSPACE_RESULT_GROUP_ORDER.get(
        row.get("group_key", ""),
        999,
    )
    return (
        group_order,
        field_order,
        row.get("field_label", ""),
        row.get("context_label", ""),
        row.get("key", ""),
    )


def _translation_workspace_language_group_status(group: dict):
    if int(group.get("needs_review_count") or 0):
        return {"status_key": "needs_review", "status_label": "Needs review"}
    if int(group.get("count") or 0) or int(group.get("translated_count") or 0):
        return {"status_key": "completed", "status_label": "Completed"}
    if int(group.get("skipped_count") or 0):
        return {
            "status_key": "skipped",
            "status_label": "No translatable content found",
        }
    return {"status_key": "pending", "status_label": "Waiting"}


def _translation_workspace_language_empty_message(locale_status: dict):
    status_value = str((locale_status or {}).get("status") or "pending")
    locale_label = (locale_status or {}).get("locale_label") or _translation_editor_locale_label(
        _translation_editor_canonical_locale((locale_status or {}).get("locale", ""))
    )
    if status_value == "running":
        return "Translation is still running for this language."
    if status_value == "failed":
        if (locale_status or {}).get("failure_type") == OPENAI_INVALID_TRANSLATION_RESPONSE:
            return (
                f"{locale_label} translation failed because OpenAI returned an invalid response format. "
                "Retry this language."
            )
        return f"Translation failed for {locale_label}. Retry this language."
    if status_value == "stale":
        return (
            f"Translation timed out for {locale_label} after 15 minutes without an update."
        )
    if status_value == "skipped":
        return "No translatable content found."
    if status_value == "completed":
        if int((locale_status or {}).get("source_rows_checked") or 0) == 0:
            return "No translatable content found."
        return "Completed. No translation comparison cards were recorded for this language."
    return "Translation is waiting for this language."


def _translation_workspace_language_tab_summary(language_group: dict):
    return (
        f"{int(language_group.get('translated_count') or 0)} translated"
        f" / {int(language_group.get('needs_review_count') or 0)} needs review"
        f" / {int(language_group.get('skipped_count') or 0)} skipped"
    )


def _translation_workspace_result_group_tab_label(group_key: str):
    labels = {
        "product_basics": "Product basics",
        "seo": "SEO",
        "options": "Options",
        "variants": "Variants",
        "important_metafields": "Important metafields",
        "media": "Media alt text",
    }
    return labels.get(group_key, _translation_workspace_group_label(group_key))


def _translation_workspace_should_show_result_row(row: dict):
    return bool(
        row.get("has_generated_draft")
        or row.get("existing_translation_present")
        or row.get("current_translation_present")
        or row.get("existing_translation_outdated")
        or row.get("reason")
        or row.get("block_reason")
        or row.get("status")
    )


def _translation_workspace_result_card_row(row: dict):
    display_row = dict(row)
    locale = _translation_editor_canonical_locale(
        row.get("language") or row.get("locale", "")
    )
    status_key, status_label = _translation_workspace_result_row_status(row)
    raw_reasons = _translation_workspace_result_raw_reason_codes(row)
    reason_labels = _translation_workspace_human_reason_labels(raw_reasons, row=row)
    visible_raw_reasons = [
        reason
        for reason in raw_reasons
        if reason not in TRANSLATION_WORKSPACE_NON_BLOCKING_REASON_CODES
    ]
    visible_reason_label_candidates = _translation_workspace_human_reason_labels(
        visible_raw_reasons,
        row=row,
    )
    visible_reason_labels = (
        [
            label
            for label in reason_labels
            if label
            == TRANSLATION_WORKSPACE_RESULT_REASON_LABELS[
                "future_write_needs_resource_mapping"
            ]
        ]
        if status_key == "ready" and row.get("needs_mapping")
        else (
            []
            if status_key in {"ready", "already_up_to_date"}
            else visible_reason_label_candidates
        )
    )
    main_value = _translation_workspace_result_main_value(
        row,
        status_label=status_label,
        reason_labels=reason_labels,
    )
    display_row.update(
        {
            "language_label": _translation_editor_locale_label(
                locale
            ),
            "language": locale,
            "locale": locale,
            "field_label": _translation_workspace_result_field_label(row),
            "result_status_key": status_key,
            "result_status_label": status_label,
            "result_reason_labels": visible_reason_labels,
            "result_reason_text": ", ".join(visible_reason_labels),
            "raw_reason_codes": raw_reasons,
            "raw_reason_text": ", ".join(raw_reasons),
            "main_value_label": main_value["label"],
            "main_value_display": main_value["display"],
            "main_value_summary": main_value["summary"],
            "main_value_is_long": main_value["is_long"],
            "main_value_is_reason": main_value["is_reason"],
            "comparison_translation_label": (
                "Using manual edit"
                if row.get("using_manual_edit")
                else (
                    "Translation result"
                    if row.get("has_generated_draft")
                    else (
                        "Current Shopify translation"
                        if (
                            row.get("existing_translation_present")
                            or row.get("current_translation_present")
                        )
                        else "Translation"
                    )
                )
            ),
            "comparison_translation_display": (
                row.get("generated_draft_display")
                or row.get("existing_translation_display")
                or row.get("main_value_display")
                or ""
            ),
            "comparison_translation_html_preview": (
                row.get("generated_draft_html_preview")
                or row.get("existing_translation_html_preview")
                or ""
            ),
        }
    )
    return display_row


def _translation_workspace_result_row_status(row: dict):
    raw_reasons = set(_translation_workspace_result_raw_reason_codes(row))
    review_reasons = TRANSLATION_WORKSPACE_REVIEW_REASON_CODES
    has_review_issue = bool(
        (raw_reasons & review_reasons)
        or row.get("draft_blocked")
        or row.get("product_identity_mismatch")
        or row.get("existing_translation_outdated")
    )
    if row.get("has_generated_draft"):
        if has_review_issue:
            return "needs_review", "Needs review"
        return "ready", "Ready"
    if row.get("existing_translation_present") or row.get("current_translation_present"):
        if has_review_issue:
            return "needs_review", "Needs review"
        return "already_up_to_date", "Already up to date"
    if has_review_issue:
        return "needs_review", "Needs review"
    return "not_translated_automatically", "Not translated automatically"


def _translation_workspace_result_field_label(row: dict):
    group_key = str(row.get("group_key") or row.get("resource_group") or "").strip()
    field = str(row.get("field") or row.get("key") or "").strip()
    normalized_field = _translation_editor_normalize_field_key(field)
    if group_key == "options":
        option_name = str(row.get("option_name") or "").strip()
        option_value = str(row.get("option_value") or "").strip()
        source_value = str(row.get("source_value") or "").strip()
        if normalized_field == "option.name":
            return f"Option name: {option_name or source_value or '-'}"
        if normalized_field == "option.value":
            return f"Option value: {option_value or source_value or '-'}"
    context_label = str(row.get("context_label") or "").strip()
    if context_label:
        return context_label
    if normalized_field in TRANSLATION_WORKSPACE_RESULT_FIELD_LABELS:
        return TRANSLATION_WORKSPACE_RESULT_FIELD_LABELS[normalized_field]
    if field in TRANSLATION_WORKSPACE_RESULT_FIELD_LABELS:
        return TRANSLATION_WORKSPACE_RESULT_FIELD_LABELS[field]
    return _translation_workspace_title_status(field)


def _translation_workspace_option_context_line(row: dict):
    option_name = str((row or {}).get("option_name") or "").strip()
    option_value = str((row or {}).get("option_value") or "").strip()
    option_position = str((row or {}).get("option_position") or "").strip()
    parts = []
    if option_name:
        parts.append(f"Option: {option_name}")
    if option_position:
        parts.append(f"Position: {option_position}")
    if option_value:
        parts.append(f"Value: {option_value}")
    return " | ".join(parts)


def _translation_workspace_related_variants_label(related_variants):
    labels = []
    for item in related_variants or []:
        if not isinstance(item, dict):
            continue
        label = " / ".join(
            part
            for part in (
                str(item.get("title") or "").strip(),
                f"SKU {item.get('sku')}" if item.get("sku") else "",
            )
            if part
        )
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return ""
    suffix = ""
    if len(labels) > 4:
        suffix = f" and {len(labels) - 4} more"
    return "; ".join(labels[:4]) + suffix


def _translation_workspace_result_main_value(
    row: dict,
    *,
    status_label: str,
    reason_labels: list[str],
):
    if row.get("has_generated_draft"):
        return {
            "label": "Translation result",
            "display": row.get("generated_draft_display") or row.get("proposed_translation") or "-",
            "summary": row.get("generated_draft_summary") or "",
            "is_long": bool(row.get("generated_draft_is_long")),
            "is_reason": False,
        }
    existing_current = bool(
        (row.get("existing_translation_present") or row.get("current_translation_present"))
        and not row.get("existing_translation_outdated")
    )
    if existing_current:
        return {
            "label": "Existing translation",
            "display": row.get("existing_translation_display")
            or row.get("existing_translation_value")
            or "-",
            "summary": row.get("existing_translation_summary") or "",
            "is_long": bool(row.get("existing_translation_is_long")),
            "is_reason": False,
        }
    reason_text = ", ".join(reason_labels) if reason_labels else status_label
    return {
        "label": "Reason",
        "display": reason_text or "-",
        "summary": reason_text or "-",
        "is_long": False,
        "is_reason": True,
    }


def _translation_workspace_result_raw_reason_codes(row: dict):
    raw_reasons = []
    for value in (
        row.get("block_reason"),
        row.get("reason"),
        row.get("blocking_reasons"),
        row.get("validation_reasons"),
        row.get("seo_warning"),
        row.get("seo_validation_status"),
        row.get("status"),
    ):
        raw_reasons.extend(_translation_workspace_split_reasons(value))
    if row.get("needs_mapping") and row.get("has_generated_draft"):
        raw_reasons.append("future_write_needs_resource_mapping")
    if row.get("existing_translation_outdated"):
        raw_reasons.append("existing_translation_outdated")
    if row.get("draft_blocked"):
        raw_reasons.append("draft_blocked")
    if row.get("product_identity_mismatch"):
        raw_reasons.append("product_identity_mismatch")
    normalized_reasons = []
    for item in raw_reasons:
        normalized = _translation_workspace_normalized_reason(item)
        if normalized:
            normalized_reasons.append(normalized)
    if not row.get("has_generated_draft"):
        normalized_reasons = [
            reason
            for reason in normalized_reasons
            if reason != "future_write_needs_resource_mapping"
        ]
    return list(dict.fromkeys(normalized_reasons))


def _translation_workspace_human_reason_labels(raw_reasons: list[str], row: dict | None = None):
    labels = []
    for reason in raw_reasons or []:
        normalized = _translation_workspace_normalized_reason(reason)
        if not normalized:
            continue
        label = _translation_workspace_reason_label(normalized, row or {})
        if label not in labels:
            labels.append(label)
    return labels


def _translation_workspace_reason_label(reason: str, row: dict):
    field = _translation_editor_normalize_field_key(
        (row or {}).get("field") or (row or {}).get("key") or ""
    )
    if reason == "draft_over_max_chars":
        if field == "title":
            return TRANSLATION_WORKSPACE_RESULT_REASON_LABELS["product_title_over_80_chars"]
        if field == "meta_title":
            return TRANSLATION_WORKSPACE_RESULT_REASON_LABELS["seo_title_over_60_chars"]
        if field == "meta_description":
            return TRANSLATION_WORKSPACE_RESULT_REASON_LABELS[
                "seo_description_over_160_chars"
            ]
    return TRANSLATION_WORKSPACE_RESULT_REASON_LABELS.get(
        reason,
        _translation_workspace_title_status(reason),
    )


def _attach_translation_workspace_safe_write_ui(
    translation_background_job: dict,
    safe_write_readiness_state: dict,
    selected_translations_apply_state: dict | None = None,
):
    if not isinstance(translation_background_job, dict):
        return
    entries_by_id = {
        entry.get("entry_id"): entry
        for entry in (
            list((safe_write_readiness_state or {}).get("eligible_entries") or [])
            + list((safe_write_readiness_state or {}).get("blocked_entries") or [])
        )
        if entry.get("entry_id")
    }
    selected_apply_entries = list(
        (selected_translations_apply_state or {}).get("all_entries") or []
    )
    if not selected_apply_entries:
        selected_apply_entries = (
            list((selected_translations_apply_state or {}).get("eligible_entries") or [])
            + list((selected_translations_apply_state or {}).get("blocked_entries") or [])
        )
    selected_apply_entries_by_id = {
        entry.get("entry_id"): entry
        for entry in selected_apply_entries
        if entry.get("entry_id")
    }
    for row in translation_background_job.get("review_rows") or []:
        entry_id = row.get("safe_write_entry_id") or row.get("entry_id")
        entry = entries_by_id.get(entry_id)
        selected_apply_entry = selected_apply_entries_by_id.get(entry_id)
        apply_field = (
            (selected_apply_entry or {}).get("key")
            or _translation_editor_normalize_field_key(row.get("field") or row.get("key"))
        )
        row["shopify_apply_field"] = apply_field
        row["shopify_apply_supported_field"] = (
            apply_field in TRANSLATION_WORKSPACE_APPLY_SUPPORTED_FIELDS
        )
        if not entry:
            row["safe_write_entry_id"] = (selected_apply_entry or {}).get("entry_id", "")
            row["safe_write_selectable"] = False
            row["safe_write_eligibility_status"] = "not_in_selected_locale"
            row["safe_write_block_reason"] = "not_in_selected_locale"
            row["shopify_apply_selectable"] = bool(
                selected_apply_entry and selected_apply_entry.get("selectable")
            )
            row["shopify_apply_eligibility_status"] = (
                (selected_apply_entry or {}).get("eligibility_status")
                or "not_in_selected_locale"
            )
            row["shopify_apply_block_reason"] = (
                (selected_apply_entry or {}).get("blocked_reason")
                or "not_in_selected_locale"
            )
            row["shopify_apply_block_reason_label"] = (
                _translation_workspace_shopify_apply_block_reason_label(row)
            )
            continue
        row["safe_write_entry_id"] = entry.get("entry_id", "")
        row["safe_write_selectable"] = bool(entry.get("selectable"))
        row["safe_write_eligibility_status"] = entry.get("eligibility_status", "")
        row["safe_write_block_reason"] = entry.get("blocked_reason", "")
        if not selected_apply_entry:
            row["shopify_apply_selectable"] = False
            row["shopify_apply_eligibility_status"] = "not_in_selected_locale"
            row["shopify_apply_block_reason"] = "not_in_selected_locale"
            row["shopify_apply_block_reason_label"] = (
                _translation_workspace_shopify_apply_block_reason_label(row)
            )
            continue
        row["shopify_apply_selectable"] = bool(selected_apply_entry.get("selectable"))
        row["shopify_apply_eligibility_status"] = selected_apply_entry.get(
            "eligibility_status",
            "",
        )
        row["shopify_apply_block_reason"] = selected_apply_entry.get(
            "blocked_reason",
            "",
        )
        row["shopify_apply_block_reason_label"] = (
            _translation_workspace_shopify_apply_block_reason_label(row)
        )


def _translation_workspace_shopify_apply_block_reason_label(row: dict):
    if row.get("shopify_apply_selectable"):
        return ""
    field = _translation_editor_normalize_field_key(row.get("field") or row.get("key"))
    group_key = str(row.get("group_key") or row.get("resource_group") or "").strip()
    reason = str(row.get("shopify_apply_block_reason") or "").strip()
    if field == "body_html":
        return "Product description update is not enabled yet."
    if group_key == "options":
        return "Options need extra Shopify mapping before update."
    if group_key == "variants":
        return "Variants need extra Shopify mapping before update."
    if group_key in {"important_metafields", "technical_metafields", "metafields"}:
        return "Metafields need extra Shopify mapping before update."
    if group_key in {"media", "media_alt_text"}:
        return "Media alt text update is not enabled yet."
    return TRANSLATION_WORKSPACE_SHOPIFY_APPLY_BLOCK_LABELS.get(
        reason,
        _translation_workspace_title_status(reason or "Not eligible for Shopify update"),
    )


def _translation_workspace_report_detail_summary(status: dict):
    counts = status.get("counts") or {}
    return {
        "product_title": status.get("product_title", ""),
        "product_gid": status.get("product_gid", ""),
        "job_status": status.get("status_label") or status.get("status", ""),
        "locales": status.get("selected_locales") or [],
        "generated_draft_count": int(counts.get("generated_draft_count") or 0),
        "skipped_count": int(counts.get("skipped_count") or 0),
        "blocked_count": int(counts.get("blocked_count") or 0),
        "openai_call_count": int(counts.get("openai_call_count") or 0),
        "reused_cache_count": int(counts.get("reused_cache_count") or 0),
        "skipped_existing_count": int(counts.get("skipped_existing_count") or 0),
        "skipped_technical_count": int(counts.get("skipped_technical_count") or 0),
        "deduplicated_input_count": int(counts.get("deduplicated_input_count") or 0),
        "estimated_input_chars_saved": int(
            counts.get("estimated_input_chars_saved") or 0
        ),
        "per_locale_openai_call_count": counts.get("per_locale_openai_call_count") or {},
        "manual_translation_override_count": int(
            status.get("manual_translation_override_count") or 0
        ),
        "no_shopify_write_performed": not bool(status.get("shopify_write_performed")),
        "report_path": status.get("report_path", ""),
        "job_started_by": status.get("job_started_by", "user_action"),
        "polling_read_only": bool(status.get("polling_read_only", True)),
        "auto_start_blocked": bool(status.get("auto_start_blocked", True)),
    }


def _translation_workspace_job_review_rows(status: dict):
    rows = [
        _translation_workspace_job_review_row(row)
        for row in (status.get("review_rows") or [])
        if isinstance(row, dict)
    ]
    if not rows:
        rows = [
            _translation_workspace_job_review_row(row)
            for row in (status.get("detail_preview_rows") or [])
            if isinstance(row, dict)
        ]
    group_order = {
        value: index for index, value in enumerate(TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS)
    }
    locale_order = {
        locale: index for index, locale in enumerate(status.get("selected_locales") or [])
    }
    rows.sort(
        key=lambda row: (
            locale_order.get(row.get("language", ""), 999),
            TRANSLATION_WORKSPACE_RESULT_GROUP_ORDER.get(
                row.get("group_key", ""),
                group_order.get(row.get("group_key", ""), 999),
            ),
            TRANSLATION_WORKSPACE_RESULT_FIELD_ORDER.get(
                _translation_editor_normalize_field_key(row.get("field", "")),
                TRANSLATION_WORKSPACE_RESULT_FIELD_ORDER.get(row.get("field", ""), 999),
            ),
            row.get("key", ""),
            row.get("context_label", ""),
        )
    )
    for index, row in enumerate(rows):
        row["row_id"] = f"translation-report-row-{index}"
    return rows


def _translation_workspace_job_review_row(row: dict):
    group_key = _translation_workspace_review_group_key(row)
    field = str(row.get("field") or row.get("key") or "").strip()
    normalized_field = _translation_editor_normalize_field_key(field)
    resource_key = str(row.get("key") or row.get("resource_key") or field).strip()
    locale = _translation_editor_canonical_locale(row.get("locale") or row.get("language"))
    resource_id = str(row.get("resource_id") or "").strip()
    digest = str(row.get("source_digest") or row.get("digest") or "").strip()
    safe_write_entry_id = _translation_workspace_safe_write_entry_id(
        resource_id,
        field,
        locale,
        digest,
    )
    has_generated_draft = bool(
        row.get("has_generated_draft")
        or str(row.get("proposed_translation_display") or "").strip()
        or str(row.get("proposed_translation_preview") or "").strip()
        or str(row.get("proposed_translation") or "").strip()
    )
    needs_mapping = bool(
        row.get("future_write_needs_mapping")
        or group_key in TRANSLATION_WORKSPACE_MAPPING_REQUIRED_GROUPS
    )
    apply_eligible = bool(
        has_generated_draft
        and row.get("eligible_for_apply_plan") is True
        and field in TRANSLATION_WORKSPACE_APPLY_SUPPORTED_FIELDS
        and row.get("validation_status") in {"", "draft_ready_for_manual_review"}
        and (
            not row.get("seo_validation_status")
            or row.get("seo_validation_status") == "seo_ready"
        )
        and not row.get("draft_blocked")
        and not row.get("product_identity_mismatch")
        and not needs_mapping
    )
    write_eligibility = _translation_workspace_review_write_eligibility(
        row,
        field=field,
        has_generated_draft=has_generated_draft,
        needs_mapping=needs_mapping,
        apply_eligible=apply_eligible,
    )
    block_reason = _translation_workspace_review_block_reason(
        row,
        has_generated_draft=has_generated_draft,
        needs_mapping=needs_mapping,
        apply_eligible=apply_eligible,
    )
    review_block_reasons = _translation_workspace_review_reason_codes_from_text(
        block_reason,
        row,
    )
    is_blocked = bool(
        has_generated_draft
        and (
            review_block_reasons
            or row.get("draft_blocked")
            or row.get("product_identity_mismatch")
        )
    )
    source_value_raw = row.get("source_value") or row.get("source_value_display") or ""
    existing_translation_raw = (
        row.get("existing_translation_value")
        or row.get("existing_translation")
        or row.get("existing_translation_display")
        or ""
    )
    original_openai_translation = (
        row.get("openai_original_proposed_translation")
        or row.get("original_openai_translation")
        or ""
    )
    manual_edit_value = str(
        row.get("manual_edit_value")
        or row.get("manual_translation_override_value")
        or ""
    ).strip()
    using_manual_edit = bool(row.get("using_manual_edit") or manual_edit_value)
    proposed_translation_raw = (
        row.get("proposed_translation")
        or row.get("proposed_translation_display")
        or ""
    )
    if using_manual_edit:
        if not original_openai_translation:
            original_openai_translation = proposed_translation_raw
        proposed_translation_raw = manual_edit_value
        has_generated_draft = True
    is_html_field = normalized_field == "body_html"
    generated_differs_from_existing = bool(
        str(existing_translation_raw or "").strip()
        and str(proposed_translation_raw or "").strip()
        and str(existing_translation_raw or "").strip()
        != str(proposed_translation_raw or "").strip()
    )
    source_fields = _translation_workspace_existing_or_review_text_fields(
        row,
        "source_value",
        row.get("source_value_preview", ""),
        field,
    )
    existing_fields = _translation_workspace_existing_or_review_text_fields(
        row,
        "existing_translation",
        row.get("existing_translation_preview", ""),
        field,
    )
    draft_fields = _translation_workspace_review_text_fields(
        "proposed_translation",
        proposed_translation_raw,
        field,
        unprefixed=True,
    )
    return {
        "language": locale,
        "locale": locale,
        "group_key": group_key,
        "resource_group": row.get("resource_group") or group_key,
        "group_label": _translation_workspace_group_label(group_key),
        "resource_id": resource_id,
        "field": field,
        "key": resource_key,
        "source_key": row.get("source_key") or resource_key,
        "resource_key": resource_key,
        "digest": digest,
        "source_digest": digest,
        "entry_id": safe_write_entry_id,
        "safe_write_entry_id": safe_write_entry_id,
        "context_label": row.get("context_label", ""),
        "resource_note": row.get("resource_note", ""),
        "option_name": row.get("option_name", ""),
        "option_value": row.get("option_value", ""),
        "option_position": row.get("option_position", ""),
        "related_variants": list(row.get("related_variants") or []),
        "option_context_line": _translation_workspace_option_context_line(row),
        "related_variants_label": _translation_workspace_related_variants_label(
            row.get("related_variants") or []
        ),
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
        "source_value": source_value_raw,
        "source_identity_context": row.get("source_identity_context") or {},
        "source_value_summary": source_fields["summary"],
        "source_value_display": source_fields["display"],
        "source_value_is_long": source_fields["is_long"],
        "source_value_truncated": source_fields["truncated"],
        "source_value_html_preview": (
            _translation_editor_sanitize_html_preview(source_value_raw)
            if is_html_field
            else ""
        ),
        "existing_translation_value": existing_translation_raw,
        "existing_translation_present": row.get(
            "current_translation_present",
            row.get("existing_translation_present"),
        ),
        "current_translation_present": row.get(
            "current_translation_present",
            row.get("existing_translation_present"),
        ),
        "existing_translation_outdated": row.get(
            "existing_translation_outdated",
            row.get("outdated"),
        ),
        "existing_translation_summary": existing_fields["summary"],
        "existing_translation_display": existing_fields["display"],
        "existing_translation_is_long": existing_fields["is_long"],
        "existing_translation_truncated": existing_fields["truncated"],
        "existing_translation_html_preview": (
            _translation_editor_sanitize_html_preview(existing_translation_raw)
            if is_html_field and existing_translation_raw
            else ""
        ),
        "generated_differs_from_existing": generated_differs_from_existing,
        "outdated": row.get("outdated"),
        "proposed_translation": proposed_translation_raw,
        "manual_edit_value": manual_edit_value,
        "manual_translation_override_value": manual_edit_value,
        "has_manual_edit": using_manual_edit,
        "using_manual_edit": using_manual_edit,
        "manual_edit_saved_at": row.get("manual_edit_saved_at", ""),
        "manual_edit_label": "Edited manually" if using_manual_edit else "",
        "manual_edit_usage_label": "Using manual edit" if using_manual_edit else "",
        "manual_edit_original_label": (
            "OpenAI original available in Technical details"
            if using_manual_edit
            else ""
        ),
        "manual_edit_validation_message": row.get(
            "manual_edit_validation_message", ""
        ),
        "openai_original_proposed_translation": original_openai_translation,
        "original_openai_translation": original_openai_translation,
        "generated_draft_summary": draft_fields["summary"],
        "generated_draft_display": draft_fields["display"],
        "generated_draft_is_long": draft_fields["is_long"],
        "generated_draft_truncated": draft_fields["truncated"],
        "generated_draft_html_preview": (
            _translation_editor_sanitize_html_preview(proposed_translation_raw)
            if is_html_field and proposed_translation_raw
            else ""
        ),
        "is_html_field": is_html_field,
        "status": row.get("status", ""),
        "validation_status": row.get("validation_status", ""),
        "seo_validation_status": row.get("seo_validation_status")
        or row.get("seo_status", ""),
        "seo_warning": row.get("seo_warning", ""),
        "draft_blocked": bool(row.get("draft_blocked")),
        "product_identity_mismatch": bool(row.get("product_identity_mismatch")),
        "write_eligibility": write_eligibility,
        "block_reason": block_reason,
        "reason": row.get("reason", ""),
        "blocking_reasons": row.get("blocking_reasons", ""),
        "has_generated_draft": has_generated_draft,
        "is_blocked": is_blocked,
        "apply_eligible": apply_eligible,
        "needs_mapping": needs_mapping,
        "has_generated_draft_flag": _translation_workspace_bool_flag(
            has_generated_draft
        ),
        "is_blocked_flag": _translation_workspace_bool_flag(is_blocked),
        "apply_eligible_flag": _translation_workspace_bool_flag(apply_eligible),
        "needs_mapping_flag": _translation_workspace_bool_flag(needs_mapping),
    }


def _translation_workspace_review_reason_codes_from_text(value: str, row: dict | None = None):
    reasons = set()
    for reason in _translation_workspace_split_reasons(value):
        normalized = _translation_workspace_normalized_reason(reason)
        if normalized in TRANSLATION_WORKSPACE_REVIEW_REASON_CODES:
            reasons.add(normalized)
    if row and row.get("existing_translation_outdated"):
        reasons.add("existing_translation_outdated")
    return reasons


def _translation_workspace_review_group_key(row: dict):
    group = str(row.get("resource_group") or "").strip()
    if group == "technical_metafields":
        return "important_metafields"
    if group in TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS:
        return group
    section = str(row.get("section") or row.get("section_label") or "").strip().lower()
    section_map = {
        "product basics": "product_basics",
        "seo": "seo",
        "options": "options",
        "product options": "options",
        "variants": "variants",
        "important metafields": "important_metafields",
        "media": "media",
        "media alt text": "media",
    }
    if section in section_map:
        return section_map[section]
    section_key = _translation_editor_section_key(row.get("field") or row.get("key") or "")
    if section_key == "basic":
        return "product_basics"
    if section_key == "technical_metafields":
        return "important_metafields"
    return section_key


def _translation_workspace_review_write_eligibility(
    row: dict,
    *,
    field: str,
    has_generated_draft: bool,
    needs_mapping: bool,
    apply_eligible: bool,
):
    if not has_generated_draft:
        return "not applicable"
    if apply_eligible:
        return "apply eligible"
    if needs_mapping:
        return "needs mapping"
    if field == "body_html":
        return "manual review"
    if row.get("draft_blocked") or row.get("product_identity_mismatch"):
        return "blocked"
    return "manual review"


def _translation_workspace_review_block_reason(
    row: dict,
    *,
    has_generated_draft: bool,
    needs_mapping: bool,
    apply_eligible: bool,
):
    reasons = []
    if needs_mapping:
        reasons.append(
            row.get("apply_plan_blocked_reason")
            or "future_write_needs_resource_mapping"
        )
    reasons.extend(_translation_workspace_split_reasons(row.get("blocking_reasons")))
    if row.get("reason"):
        reasons.append(_translation_workspace_normalized_reason(row.get("reason")))
    if not has_generated_draft and not reasons:
        reasons.append("no_generated_draft")
    return ", ".join(list(dict.fromkeys(reason for reason in reasons if reason)))


def _translation_workspace_review_filter_options(rows: list[dict]):
    languages = []
    groups = []
    for row in rows or []:
        locale = row.get("language") or row.get("locale") or ""
        group_key = row.get("group_key", "")
        if locale and locale not in [item["value"] for item in languages]:
            languages.append(
                {
                    "value": locale,
                    "label": _translation_editor_locale_label(locale),
                }
            )
        if group_key and group_key not in [item["value"] for item in groups]:
            groups.append(
                {
                    "value": group_key,
                    "label": _translation_workspace_group_label(group_key),
                }
            )
    return {"languages": languages, "groups": groups}


def _translation_workspace_reason_summary(rows: list[dict]):
    counts = {}
    for row in rows or []:
        reason = _translation_workspace_reason_key(row)
        if not reason:
            continue
        counts[reason] = counts.get(reason, 0) + 1
    return [
        {"reason": reason, "count": count}
        for reason, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ]


def _translation_workspace_reason_key(row: dict):
    if row.get("needs_mapping"):
        return "future_write_needs_resource_mapping"
    reason = _translation_workspace_normalized_reason(
        row.get("block_reason") or row.get("reason") or row.get("status")
    )
    if reason:
        return reason
    if row.get("apply_eligible"):
        return "apply_eligible"
    if row.get("has_generated_draft"):
        return "manual_review_required"
    return ""


def _translation_workspace_normalized_reason(value):
    text = str(value or "").strip()
    if not text:
        return ""
    first_reason = _translation_workspace_split_reasons(text)
    if first_reason:
        text = first_reason[0]
    if text == "already_translated":
        return "existing_translation_current"
    if text == "not_draft_eligible":
        return "not_eligible_technical_field"
    if text == "skipped_child_resource_query_failed":
        return "child_resource_query_failed"
    return text


def _translation_workspace_apply_readiness_summary(rows: list[dict]):
    eligible = []
    blocked = []
    needs_mapping = []
    needs_manual_review = []
    for row in rows or []:
        if not row.get("has_generated_draft"):
            continue
        if row.get("apply_eligible"):
            eligible.append(row)
        else:
            blocked.append(row)
            if row.get("needs_mapping"):
                needs_mapping.append(row)
            else:
                needs_manual_review.append(row)
    return {
        "eligible_apply_count": len(eligible),
        "blocked_apply_count": len(blocked),
        "needs_mapping_count": len(needs_mapping),
        "needs_manual_review_count": len(needs_manual_review),
        "eligible_now_fields": [
            "title",
            "meta_title",
            "meta_description",
        ],
        "blocked_for_future_mapping_groups": [
            "options",
            "variants",
            "important_metafields",
            "media",
        ],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "apply_performed": False,
        "publish_performed": False,
        "rollback_performed": False,
    }


def _translation_workspace_report_diagnostics(status: dict, rows: list[dict]):
    return {
        "variants": _translation_workspace_group_diagnosis(status, rows, "variants"),
        "options": _translation_workspace_group_diagnosis(status, rows, "options"),
    }


def _translation_workspace_group_diagnosis(
    status: dict,
    rows: list[dict],
    group_key: str,
):
    group_rows = [row for row in rows or [] if row.get("group_key") == group_key]
    group_status = _translation_workspace_group_status_row(status, group_key)
    translatable_row_count = max(
        len(group_rows),
        int(group_status.get("source_rows_checked") or 0),
    )
    resource_ids = {
        row.get("resource_id", "")
        for row in group_rows
        if row.get("resource_id")
    }
    generated_count = sum(1 for row in group_rows if row.get("has_generated_draft"))
    needs_mapping_count = sum(1 for row in group_rows if row.get("needs_mapping"))
    blocked_count = sum(1 for row in group_rows if row.get("is_blocked"))
    zero_row_reason = ""
    if translatable_row_count == 0:
        zero_row_reason = (
            group_status.get("message")
            or "No translatable rows were returned in the local report."
        )
    reason_counts = _translation_workspace_reason_summary(group_rows)
    return {
        "group_key": group_key,
        "label": _translation_workspace_group_label(group_key),
        "discovery_status": group_status.get("status_label")
        or group_status.get("status")
        or "Not loaded",
        "resource_count": len(resource_ids),
        "translatable_row_count": translatable_row_count,
        "generated_draft_count": generated_count,
        "blocked_apply_count": blocked_count,
        "needs_mapping_count": needs_mapping_count,
        "zero_row_reason": zero_row_reason,
        "reason_counts": reason_counts,
    }


def _translation_workspace_group_status_row(status: dict, group_key: str):
    for row in status.get("per_group_status") or []:
        if row.get("group_key") == group_key:
            return row
    return {}


def _translation_workspace_bool_flag(value):
    return "1" if value else "0"


def _translation_workspace_safe_write_entry_id(
    resource_id: str,
    field: str,
    locale: str,
    digest: str,
):
    raw = "|".join(
        [
            str(resource_id or ""),
            str(field or ""),
            str(locale or ""),
            str(digest or ""),
        ]
    )
    return "swr_" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:18]


def _translation_workspace_title_status(value):
    text = str(value or "unknown").replace("_", " ").strip()
    return text[:1].upper() + text[1:] if text else "Unknown"


def _translation_workspace_locale_status_label(value):
    labels = {
        "pending": "Waiting",
        "running": "Translating",
        "completed": "Completed",
        "failed": "Failed",
        "skipped": "Skipped",
        "stale": "Stale",
        "cancelled": "Cancelled",
    }
    return labels.get(str(value or ""), _translation_workspace_title_status(value))


def _translation_workspace_locale_status_message(value, *, locale_label: str = ""):
    label = locale_label or "this language"
    messages = {
        "pending": "Waiting to start.",
        "running": "Translation is still running for this language.",
        "completed": "Completed. Translation results are ready for review.",
        "failed": f"Translation failed for {label}. Retry this language.",
        "skipped": "No translatable content found.",
        "stale": f"Translation timed out for {label} after 15 minutes without an update.",
    }
    return messages.get(str(value or ""), _translation_workspace_title_status(value))


def _translation_workspace_locale_status_view(row: dict):
    item = dict(row or {})
    locale = _translation_editor_canonical_locale(item.get("locale", ""))
    locale_label = item.get("locale_label") or _translation_editor_locale_label(locale)
    status_value = str(item.get("status") or "pending")
    error_message = _translation_workspace_safe_text(
        item.get("error_message") or item.get("message") or "",
        500,
    )
    if status_value not in {
        "pending",
        "running",
        "completed",
        "failed",
        "skipped",
        "stale",
        "cancelled",
    }:
        status_value = "pending"
    message = (
        error_message
        if status_value in {"failed", "stale"} and error_message
        else item.get("message")
    )
    item.update(
        {
            "locale_label": locale_label,
            "locale": locale,
            "status": status_value,
            "status_label": _translation_workspace_locale_status_label(status_value),
            "status_key": status_value.replace(" ", "_"),
            "message": message
            or _translation_workspace_locale_status_message(
                status_value,
                locale_label=locale_label,
            ),
            "error_message": error_message if status_value in {"failed", "stale"} else "",
            "retry_allowed": status_value in {"failed", "stale"},
        }
    )
    return item


def _translation_workspace_job_status_label(value):
    labels = {
        "completed": "Translation completed",
        "partial": "Translation completed with warnings",
        "failed": "Translation failed",
        "running": "Translation running",
        "pending": "Translation pending",
        "not_started": "Not started",
        "stale": "Status stale",
        "cancelled": "Cancelled",
    }
    return labels.get(str(value or ""), _translation_workspace_title_status(value))


def _translation_workspace_compact_job_status(status: dict):
    status_value = str((status or {}).get("status") or "not_started")
    counts = (status or {}).get("counts") or {}
    blocked_count = _translation_workspace_int(counts.get("blocked_count"), 0)
    result_count = _translation_workspace_int(
        (status or {}).get("translation_result_count"), 0
    )
    if status_value in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES:
        return {"key": "running", "label": "Running"}
    if blocked_count > 0 or status_value in {"partial", "failed", "stale", "cancelled"}:
        return {"key": "needs_review", "label": "Needs review"}
    if result_count > 0 or status_value == "completed":
        return {"key": "completed", "label": "Completed"}
    return {"key": "not_started", "label": "Not started"}


def _translation_workspace_active_job_status(product_gid: str):
    latest_status = _translation_workspace_latest_job_status(product_gid)
    if latest_status:
        latest_status = _translation_workspace_mark_stale_if_needed(latest_status)
        if latest_status.get("status") in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES:
            return latest_status
    return {}


def _translation_workspace_latest_job_status(product_gid: str):
    normalized_gid = normalize_product_gid(product_gid or "") or ""
    if not normalized_gid:
        return {}
    lock_status = _translation_workspace_job_status_from_lock(normalized_gid)
    if lock_status:
        return lock_status
    for path in _translation_workspace_job_paths_for_product(normalized_gid):
        status = _translation_workspace_load_json(path)
        if status.get("product_gid") == normalized_gid:
            return status
    return {}


def _translation_workspace_job_status_from_lock(product_gid: str):
    lock = _translation_workspace_load_json(
        _translation_workspace_job_lock_path(product_gid)
    )
    job_id = lock.get("job_id", "")
    if not job_id:
        return {}
    status = _translation_workspace_load_job_status(job_id)
    if status.get("product_gid") == product_gid:
        return status
    return {}


def _translation_workspace_mark_stale_if_needed(status: dict, *, persist: bool = True):
    if not status or status.get("status") not in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES:
        return status or {}
    updated_at = _translation_workspace_parse_iso(status.get("updated_at"))
    if not updated_at:
        return status
    age_seconds = (datetime.utcnow() - updated_at).total_seconds()
    if age_seconds <= TRANSLATION_WORKSPACE_JOB_STALE_SECONDS:
        return status
    now = _translation_workspace_now_iso()
    current_locale = str(status.get("current_locale") or "").strip()
    locale_label = _translation_editor_locale_label(current_locale) if current_locale else ""
    stale_message = (
        f"Translation timed out for {locale_label} after 15 minutes without an update."
        if locale_label
        else "Translation status is stale because it has not updated for 15 minutes."
    )
    if current_locale:
        locale_row = _translation_workspace_locale_row(status, current_locale)
        if locale_row.get("status") in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES:
            locale_row.update(
                {
                    "status": "stale",
                    "status_label": _translation_workspace_locale_status_label("stale"),
                    "current_step": "stale timeout",
                    "updated_at": now,
                    "finished_at": now,
                    "message": stale_message,
                    "error_message": stale_message,
                    "blocking_conditions": list(
                        dict.fromkeys(
                            list(locale_row.get("blocking_conditions") or [])
                            + ["locale_stale_timeout"]
                        )
                    ),
                }
            )
    status["status"] = "stale"
    status["finished_at"] = now
    status["current_locale"] = ""
    status["current_group"] = ""
    status["current_step"] = "stale timeout"
    status["status_message"] = stale_message
    _translation_workspace_append_job_error(
        status,
        "stale_timeout",
        stale_message,
        locale=current_locale,
        reason="locale_stale_timeout" if current_locale else "job_stale_timeout",
    )
    _translation_workspace_refresh_job_progress(status)
    if persist:
        _translation_workspace_save_job_status(status)
        _translation_workspace_release_job_lock(
            status.get("product_gid", ""), status.get("job_id", "")
        )
    return status


def _translation_workspace_parse_iso(value: str):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.strptime(text.rstrip("Z"), "%Y-%m-%dT%H:%M:%S")
    except ValueError:
        return None


def _translation_workspace_product_hash(product_gid: str):
    return hashlib.sha256(str(product_gid or "").encode("utf-8")).hexdigest()[:16]


def _translation_workspace_job_report_path(job_id: str):
    return TRANSLATION_WORKSPACE_JOB_DIR / f"{job_id}.json"


def _translation_workspace_job_lock_path(product_gid: str):
    product_hash = _translation_workspace_product_hash(product_gid)
    return TRANSLATION_WORKSPACE_JOB_DIR / f"translation_workspace_job_{product_hash}.lock.json"


def _translation_workspace_job_paths_for_product(product_gid: str):
    product_hash = _translation_workspace_product_hash(product_gid)
    try:
        paths = list(
            TRANSLATION_WORKSPACE_JOB_DIR.glob(
                f"translation_workspace_job_{product_hash}_*.json"
            )
        )
    except OSError:
        return []
    return sorted(paths, key=lambda path: path.stat().st_mtime, reverse=True)


def _translation_workspace_load_job_status(job_id: str):
    if not job_id:
        return {}
    return _translation_workspace_load_json(_translation_workspace_job_report_path(job_id))


def _translation_workspace_load_json(path: Path):
    try:
        if not path.exists() or path.stat().st_size > 4_000_000:
            return {}
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _translation_workspace_save_job_status(status: dict):
    if not status.get("job_id"):
        return
    _translation_workspace_refresh_job_progress(status)
    path = _translation_workspace_job_report_path(status["job_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_name(
        f".{path.name}.{os.getpid()}.{threading.get_ident()}.tmp"
    )
    try:
        with tmp_path.open("w", encoding="utf-8") as handle:
            json.dump(
                status,
                handle,
                ensure_ascii=True,
                indent=2,
                sort_keys=True,
                default=str,
            )
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        try:
            if tmp_path.exists():
                tmp_path.unlink()
        except OSError:
            pass


def _translation_workspace_acquire_job_lock(status: dict):
    path = _translation_workspace_job_lock_path(status.get("product_gid", ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "job_id": status.get("job_id", ""),
        "product_gid": status.get("product_gid", ""),
        "created_at": status.get("started_at", ""),
        "updated_at": status.get("updated_at", ""),
    }
    try:
        fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2, sort_keys=True)
        handle.write("\n")
    return True


def _translation_workspace_release_job_lock(product_gid: str, job_id: str):
    if not product_gid or not job_id:
        return
    path = _translation_workspace_job_lock_path(product_gid)
    lock = _translation_workspace_load_json(path)
    if lock.get("job_id") != job_id:
        return
    try:
        path.unlink()
    except FileNotFoundError:
        return
    except OSError:
        return


def _translation_workspace_release_inactive_job_lock(product_gid: str):
    lock = _translation_workspace_load_json(_translation_workspace_job_lock_path(product_gid))
    job_id = lock.get("job_id", "")
    if not job_id:
        return
    status = _translation_workspace_load_job_status(job_id)
    if status.get("status") not in TRANSLATION_WORKSPACE_JOB_ACTIVE_STATUSES:
        _translation_workspace_release_job_lock(product_gid, job_id)


def _translation_workspace_append_job_error(
    status: dict,
    stage: str,
    message: str,
    *,
    locale: str = "",
    reason: str = "",
    query_failure_type: str = "",
):
    errors = status.setdefault("errors", [])
    if len(errors) >= TRANSLATION_WORKSPACE_JOB_ERROR_LIMIT:
        status["errors_truncated"] = True
        return
    errors.append(
        {
            "stage": _translation_workspace_safe_text(stage, 120),
            "locale": _translation_workspace_safe_text(locale, 20),
            "reason": _translation_workspace_safe_text(reason, 120),
            "query_failure_type": _translation_workspace_safe_text(
                query_failure_type, 120
            ),
            "message": _translation_workspace_safe_text(message, 500),
        }
    )


def _translation_workspace_safe_error_message(exc):
    if isinstance(exc, (ShopifyTranslationConsoleError, requests.RequestException, ValueError)):
        text = safe_translation_console_error_message(exc)
    else:
        text = f"{type(exc).__name__}: {exc}"
    return _translation_workspace_safe_text(text, 500)


def _translation_workspace_safe_text(value, max_length: int = 500):
    text = str(value or "")
    text = TRANSLATION_WORKSPACE_JOB_SECRET_RE.sub("[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_length:
        return text[: max_length - 3].rstrip() + "..."
    return text


def _translation_workspace_display_path(path: Path):
    return str(path).replace("\\", "/")


def _translation_workspace_translate_all_locale_result(
    locale: str,
    draft_result: dict,
    product_id: str,
    product_search_text: str,
    editor_filter: str,
    editor_search_query: str,
):
    per_locale = (draft_result.get("per_locale_results") or {}).get(locale, {})
    missing_count = int(per_locale.get("missing_translation_draft_generated_count") or 0)
    outdated_count = int(
        per_locale.get("outdated_translation_update_draft_generated_count") or 0
    )
    needs_review_count = int(per_locale.get("needs_review_or_blocked_count") or 0)
    blocking_conditions = list(draft_result.get("blocking_conditions") or [])
    if blocking_conditions:
        status = "failed"
        if draft_result.get("failure_type") == OPENAI_INVALID_TRANSLATION_RESPONSE:
            message = (
                f"{_translation_editor_locale_label(locale)} translation failed because OpenAI returned an invalid response format. "
                "Retry this language."
            )
        else:
            message = "Translation did not complete for this language."
    elif needs_review_count:
        status = "needs review"
        message = "Translation results are ready, but some rows need review."
    elif missing_count or outdated_count:
        status = "generated"
        message = "New and updated translations are ready for review."
    else:
        status = "skipped"
        message = "No new or updated translations were found."
    return {
        "locale": locale,
        "locale_label": _translation_editor_locale_label(locale),
        "status": status,
        "status_key": _translation_workspace_locale_status_key(status),
        "status_label": status,
        "missing_draft_count": missing_count,
        "outdated_update_draft_count": outdated_count,
        "already_translated_skipped": int(
            per_locale.get("already_translated_skipped_count") or 0
        ),
        "not_eligible_skipped": int(per_locale.get("not_eligible_skipped_count") or 0),
        "needs_review_blocked": needs_review_count,
        "source_rows_checked": int(per_locale.get("source_row_count") or 0),
        "message": message,
        "blocking_conditions": blocking_conditions,
        "product_id": product_id,
        "product_search_text": product_search_text,
        "editor_filter": editor_filter,
        "editor_search_query": editor_search_query,
        "preview_url": _translation_workspace_preview_url(
            product_id=product_id,
            locale=locale,
            product_search_text=product_search_text,
            editor_filter=editor_filter,
            editor_search_query=editor_search_query,
        ),
    }


def _translation_workspace_translate_all_status(draft_result: dict, summary: dict):
    blocking_conditions = list((draft_result or {}).get("blocking_conditions") or [])
    if blocking_conditions:
        if (draft_result or {}).get("failure_type") == "missing_openai_api_key":
            return (
                "translate_all_languages_all_content_needs_configuration",
                "Translate all could not run because OpenAI configuration is missing. Shopify was not updated.",
            )
        if (draft_result or {}).get("failure_type") == "shopify_read_query_failed":
            return (
                "translate_all_languages_all_content_blocked",
                (draft_result or {}).get("error")
                or "Translate all stayed no-write but the read-only Shopify query failed.",
            )
        return (
            "translate_all_languages_all_content_blocked",
            "Translate all stayed no-write but did not complete. Review the blocking conditions.",
        )
    generated = int(summary.get("missing_drafts_generated") or 0) + int(
        summary.get("outdated_update_drafts_generated") or 0
    )
    needs_review = int(summary.get("needs_review_blocked") or 0)
    if generated:
        if needs_review:
            return (
                "translate_all_languages_all_content_completed_with_review",
                "Translate all produced translation results and some rows need review. Shopify was not updated.",
            )
        return (
            "translate_all_languages_all_content_completed",
            "Translate all produced translation results for new and updated rows. Shopify was not updated.",
        )
    return (
        "translate_all_languages_all_content_skipped",
        "No new or updated translations were found. Shopify was not updated.",
    )


def _generate_translation_workspace_multi_locale_drafts(
    installation,
    product_id: str,
    selected_locale: str,
    target_locales: list[str],
    invalid_locales: list[str] | None = None,
    draft_groups: list[str] | None = None,
    invalid_groups: list[str] | None = None,
    product_search_text: str = "",
    editor_filter: str = "all",
    editor_search_query: str = "",
):
    locale_results = []
    selected_locale_draft_result = None
    draft_groups = list(draft_groups or TRANSLATION_WORKSPACE_DEFAULT_DRAFT_GROUPS)
    invalid_groups = list(invalid_groups or [])
    draft_scopes = _translation_workspace_draft_scopes(draft_groups)
    for target_locale in target_locales:
        try:
            locale_draft_result = generate_selected_product_missing_translation_draft_package(
                product_id=product_id,
                target_locales=[target_locale],
                fields=draft_scopes,
                installation=installation,
            )
            _attach_translation_console_draft_detail(locale_draft_result)
        except Exception as exc:
            locale_draft_result = {
                "draft_status": "draft_generation_failed",
                "failure_type": "unexpected_error",
                "error": f"{type(exc).__name__}: draft generation failed",
                "product_id": product_id,
                "target_locales": [target_locale],
                "requested_fields": list(draft_scopes),
                "blocking_conditions": ["draft_generation_failed"],
                "translation_console_detail": {
                    "summary_counts": {
                        "draft_entry_count": 0,
                        "skipped_entry_count": 0,
                        "existing_translation_count": 0,
                    }
                },
                "shopify_write_performed": False,
                "publish_performed": False,
                "apply_performed": False,
                "rollback_performed": False,
            }
        locale_summary = _translation_workspace_draft_locale_summary(
            locale=target_locale,
            draft_result=locale_draft_result,
            product_search_text=product_search_text,
            product_id=product_id,
            editor_filter=editor_filter,
            editor_search_query=editor_search_query,
        )
        locale_results.append(locale_summary)
        if target_locale == selected_locale:
            selected_locale_draft_result = locale_draft_result

    for invalid_locale in invalid_locales or []:
        locale_results.append(
            {
                "locale": invalid_locale,
                "locale_label": invalid_locale,
                "status": "skipped",
                "status_key": "skipped",
                "status_label": "skipped",
                "draft_field_count": 0,
                "skipped_existing_field_count": 0,
                "skipped_field_count": 0,
                "message": "This target language is not supported.",
                "failure_reason": "Choose Japanese, German, French, Spanish, or Italian.",
                "blocking_conditions": ["unsupported_target_language"],
                "product_id": product_id,
                "product_search_text": product_search_text,
                "editor_filter": editor_filter,
                "editor_search_query": editor_search_query,
                "preview_url": "",
            }
        )

    summary = _translation_workspace_multi_locale_summary(locale_results)
    action_status, message = _translation_workspace_multi_locale_status(summary)
    return {
        "action_status": action_status,
        "message": message,
        "product_id": product_id,
        "selected_locale": selected_locale,
        "requested_locales": list(target_locales),
        "invalid_locales": list(invalid_locales or []),
        "requested_groups": draft_groups,
        "invalid_groups": invalid_groups,
        "locale_results": locale_results,
        "selected_locale_draft_result": selected_locale_draft_result,
        "draft_fields": list(draft_scopes),
        "field_scope_labels": _translation_workspace_draft_field_labels(draft_groups),
        "summary": summary,
        "blocking_conditions": summary.get("blocking_conditions", []),
        "read_only": True,
        "shopify_write_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _translation_workspace_draft_locale_summary(
    locale: str,
    draft_result: dict,
    product_search_text: str,
    product_id: str,
    editor_filter: str,
    editor_search_query: str,
):
    detail = (draft_result or {}).get("translation_console_detail") or {}
    counts = detail.get("summary_counts") or {}
    draft_status = (draft_result or {}).get("draft_status", "")
    failure_type = (draft_result or {}).get("failure_type", "")
    blocking_conditions = list((draft_result or {}).get("blocking_conditions") or [])
    if failure_type == "missing_openai_api_key" or draft_status == "blocked_missing_openai_api_key":
        status = "needs configuration"
        message = "Translation could not run because OpenAI configuration is missing."
    elif failure_type == OPENAI_INVALID_TRANSLATION_RESPONSE:
        status = "failed"
        message = (
            f"{_translation_editor_locale_label(locale)} translation failed because OpenAI returned an invalid response format. "
            "Retry this language."
        )
    elif blocking_conditions:
        status = "failed"
        message = "Translation did not complete for this language."
    elif int((draft_result or {}).get("draft_blocked_count") or 0) or int(
        counts.get("product_identity_mismatch_count")
        or (draft_result or {}).get("product_identity_mismatch_count")
        or 0
    ):
        status = "needs review"
        message = "Translation results include fields that may mention a different product."
    elif int(counts.get("draft_entry_count") or 0):
        status = "generated"
        message = "Translation results are ready for review."
    elif draft_status == "no_missing_translations_found":
        status = "skipped"
        message = "No new translations were found for this language."
    elif (draft_result or {}).get("success"):
        status = "skipped"
        message = "No new translations were needed for this language."
    else:
        status = "failed"
        message = "Translation did not complete for this language."

    return {
        "locale": locale,
        "locale_label": _translation_editor_locale_label(locale),
        "status": status,
        "status_key": _translation_workspace_locale_status_key(status),
        "status_label": status,
        "draft_field_count": int(
            counts.get("draft_entry_count")
            or (draft_result or {}).get("generated_draft_count")
            or 0
        ),
        "blocked_draft_count": int(
            counts.get("draft_blocked_count")
            or (draft_result or {}).get("draft_blocked_count")
            or 0
        ),
        "product_identity_mismatch_count": int(
            counts.get("product_identity_mismatch_count")
            or (draft_result or {}).get("product_identity_mismatch_count")
            or 0
        ),
        "skipped_existing_field_count": int(
            counts.get("existing_translation_count")
            or (draft_result or {}).get("skipped_existing_translation_count")
            or 0
        ),
        "skipped_field_count": int(
            counts.get("skipped_entry_count")
            or (
                int((draft_result or {}).get("skipped_existing_translation_count") or 0)
                + int((draft_result or {}).get("skipped_outdated_translation_count") or 0)
                + int((draft_result or {}).get("skipped_source_empty_count") or 0)
            )
        ),
        "message": message,
        "failure_reason": _translation_workspace_failure_reason(draft_result),
        "draft_status": draft_status,
        "blocking_conditions": blocking_conditions,
        "product_id": product_id,
        "product_search_text": product_search_text,
        "editor_filter": editor_filter,
        "editor_search_query": editor_search_query,
        "preview_url": _translation_workspace_preview_url(
            product_id=product_id,
            locale=locale,
            product_search_text=product_search_text,
            editor_filter=editor_filter,
            editor_search_query=editor_search_query,
        ),
    }


def _translation_workspace_multi_locale_blocked_message(
    has_product: bool,
    requested_locales: list[str] | None,
    invalid_locales: list[str] | None,
    requested_groups: list[str] | None = None,
    invalid_groups: list[str] | None = None,
):
    has_requested_locale = bool(requested_locales)
    has_invalid_locale = bool(invalid_locales)
    has_requested_group = bool(requested_groups)
    has_invalid_group = bool(invalid_groups)
    if has_invalid_group and not has_requested_group:
        return "Choose at least one supported translation area."
    if not has_requested_group:
        return "Choose at least one translation area."
    if not has_product and not has_requested_locale and not has_invalid_locale:
        return "Select one product and choose at least one target language before translating."
    if not has_product and has_invalid_locale and not has_requested_locale:
        return "Select one product and choose only supported target languages: Japanese, German, French, Spanish, or Italian."
    if not has_product:
        return "Select one product before translating."
    if has_invalid_locale and not has_requested_locale:
        return "Choose only supported target languages: Japanese, German, French, Spanish, or Italian."
    if not has_requested_locale:
        return "Choose at least one target language."
    return "Translation could not start. Review the selections and try again."


def _translation_workspace_locale_status_key(status: str):
    return re.sub(r"[^a-z0-9]+", "_", str(status or "").lower()).strip("_") or "unknown"


def _translation_workspace_failure_reason(draft_result: dict | None):
    draft_result = draft_result or {}
    failure_type = str(draft_result.get("failure_type") or "")
    draft_status = str(draft_result.get("draft_status") or "")
    blocking_conditions = list(draft_result.get("blocking_conditions") or [])
    if failure_type == "missing_openai_api_key" or draft_status == "blocked_missing_openai_api_key":
        return "OpenAI configuration is missing."
    if failure_type == "openai_request_failed":
        return "OpenAI translation generation failed. Try again after checking configuration."
    if failure_type == OPENAI_INVALID_TRANSLATION_RESPONSE:
        return "OpenAI returned an invalid translation response format."
    if failure_type == "openai_response_invalid":
        return "OpenAI returned an unexpected translation response."
    if failure_type == "shopify_read_query_failed":
        return "The read-only product translation lookup failed."
    if failure_type == "unexpected_error":
        return "Translation failed unexpectedly."
    reason_labels = {
        "blocked_invalid_product_id": "The selected product was not valid.",
        "blocked_unsupported_locale": "This target language is not supported.",
        "blocked_invalid_field": "The translation field selection was not valid.",
        "blocked_missing_shopify_installation": "Shopify installation is not configured for read-only lookup.",
        "blocked_shopify_read_query_failed": "The read-only product translation lookup failed.",
        "blocked_openai_draft_generation_failed": "OpenAI translation generation failed.",
        "draft_generation_failed": "Translation failed unexpectedly.",
    }
    for reason in blocking_conditions:
        if reason in reason_labels:
            return reason_labels[reason]
    error = str(draft_result.get("error") or "").strip()
    if error:
        return error
    return ""


def _translation_workspace_preview_url(
    product_id: str,
    locale: str,
    product_search_text: str,
    editor_filter: str,
    editor_search_query: str,
):
    params = {
        "ui_mode": "editor",
        "product_gid": product_id,
        "target_locale": locale,
    }
    if product_search_text:
        params["product_search"] = product_search_text
    if editor_filter:
        params["editor_filter"] = editor_filter
    if editor_search_query:
        params["editor_search"] = editor_search_query
    return "?" + urllib.parse.urlencode(params)


def _translation_workspace_multi_locale_summary(locale_results: list[dict]):
    status_counts = {}
    blocking_conditions = []
    for row in locale_results or []:
        status = row.get("status", "")
        if status:
            status_counts[status] = status_counts.get(status, 0) + 1
        blocking_conditions.extend(row.get("blocking_conditions") or [])
    return {
        "locale_count": len(locale_results or []),
        "status_counts": status_counts,
        "generated_locale_count": status_counts.get("generated", 0),
        "needs_review_locale_count": status_counts.get("needs review", 0),
        "skipped_locale_count": status_counts.get("skipped", 0),
        "failed_locale_count": status_counts.get("failed", 0),
        "needs_configuration_locale_count": status_counts.get(
            "needs configuration", 0
        ),
        "draft_field_count": sum(
            int(row.get("draft_field_count") or 0) for row in locale_results or []
        ),
        "blocked_draft_count": sum(
            int(row.get("blocked_draft_count") or 0) for row in locale_results or []
        ),
        "product_identity_mismatch_count": sum(
            int(row.get("product_identity_mismatch_count") or 0)
            for row in locale_results or []
        ),
        "skipped_existing_field_count": sum(
            int(row.get("skipped_existing_field_count") or 0)
            for row in locale_results or []
        ),
        "blocking_conditions": list(dict.fromkeys(blocking_conditions)),
        "shopify_write_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _translation_workspace_multi_locale_status(summary: dict):
    locale_count = int(summary.get("locale_count") or 0)
    generated = int(summary.get("generated_locale_count") or 0)
    needs_review = int(summary.get("needs_review_locale_count") or 0)
    skipped = int(summary.get("skipped_locale_count") or 0)
    failed = int(summary.get("failed_locale_count") or 0)
    needs_configuration = int(summary.get("needs_configuration_locale_count") or 0)
    has_blocking_conditions = bool(summary.get("blocking_conditions"))
    if not locale_count:
        return "multi_locale_draft_blocked", "Choose at least one target language."
    if generated or needs_review:
        if needs_review or failed or needs_configuration or has_blocking_conditions:
            return (
                "multi_locale_draft_completed_with_issues",
                "Translation finished with issues. Shopify was not updated. Review each language below.",
            )
        return (
            "multi_locale_draft_completed",
            "Translation results are ready for review. Shopify was not updated. Open each language below.",
        )
    if needs_configuration and needs_configuration == locale_count:
        return (
            "multi_locale_draft_needs_configuration",
            "Translation could not run because OpenAI configuration is missing. Shopify was not updated.",
        )
    if skipped and skipped == locale_count:
        return (
            "multi_locale_draft_skipped",
            "No new translations were found for the selected languages. Shopify was not updated.",
        )
    return (
        "multi_locale_draft_failed",
        "Translation finished with issues. Shopify was not updated. Review each language below.",
    )


def _translation_workspace_draft_field_labels(draft_groups: list[str] | None = None):
    labels = {
        "title": "product title",
        "body_html": "product description/body",
        "meta_title": "SEO title",
        "meta_description": "SEO description",
        "handle": "URL handle preview",
        "options": "product options",
        "variants": "variants",
        "important_metafields": "important metafields",
        "media": "media alt text",
    }
    return [
        labels.get(field, field)
        for field in _translation_workspace_draft_scopes(draft_groups)
    ]


def build_apply_plan_preview_from_draft_result(draft_result: dict | None):
    if not draft_result:
        return _empty_apply_plan_preview_result("generate_draft_dry_run_first")

    candidate_entries = []
    blocked_entries = []
    for entry in draft_result.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_apply_plan_preview_entry(entry)
        if normalized["would_write"]:
            candidate_entries.append(normalized)
        else:
            blocked_entries.append(normalized)

    blocking_conditions = []
    if draft_result.get("blocking_conditions"):
        blocking_conditions.extend(draft_result.get("blocking_conditions") or [])
    preview_status = (
        "apply_plan_preview_ready"
        if not blocking_conditions
        else "apply_plan_preview_needs_review"
    )
    return {
        "preview_status": preview_status,
        "preview_only": True,
        "product_id": draft_result.get("product_id", ""),
        "product_title": draft_result.get("product_title", ""),
        "configured_locale_scope": draft_result.get("target_locales") or [],
        "configured_fields": draft_result.get("requested_fields") or [],
        "draft_coverage_summary": draft_result.get("draft_coverage_summary") or {},
        "apply_plan_candidate_count": len(candidate_entries),
        "blocked_or_needs_review_count": len(blocked_entries),
        "seo_warning_count": int(draft_result.get("seo_needs_manual_review_count") or 0),
        "existing_translation_count": int(
            draft_result.get("skipped_existing_translation_count") or 0
        ),
        "candidate_entries": candidate_entries[:TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS],
        "blocked_entries": blocked_entries[:TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS],
        "candidate_entries_truncated": len(candidate_entries)
        > TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS,
        "blocked_entries_truncated": len(blocked_entries)
        > TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS,
        "max_rows": TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS,
        "blocking_conditions": blocking_conditions,
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
    }


def build_translation_console_workbench_summary(
    product_selector: dict | None,
    workflow_status: dict | None,
    draft_result: dict | None,
    apply_plan_preview_result: dict | None,
    locked_package_report_result: dict | None,
    locked_report_approval_checklist: dict | None,
    manual_command_package: dict | None,
):
    product_selector = product_selector or {}
    workflow_status = workflow_status or {}
    draft_result = draft_result or {}
    apply_plan_preview_result = apply_plan_preview_result or {}
    locked_package_report_result = locked_package_report_result or {}
    locked_report_approval_checklist = locked_report_approval_checklist or {}
    manual_command_package = manual_command_package or {}
    draft_detail = draft_result.get("translation_console_detail") or {}
    draft_counts = draft_detail.get("summary_counts") or {}
    draft_entry_count = int(draft_counts.get("draft_entry_count") or 0)
    skipped_entry_count = int(draft_counts.get("skipped_entry_count") or 0)
    report_generated_at = (
        locked_package_report_result.get("generated_at")
        or locked_report_approval_checklist.get("generated_at")
        or ""
    )
    return {
        "ui_mode": "normal",
        "selected_product_title": (
            (product_selector.get("selected_product") or {}).get("title", "")
        ),
        "selected_product_gid": product_selector.get("selected_product_gid", ""),
        "selected_product_published_at": (
            (product_selector.get("selected_product") or {}).get("published_at", "")
        ),
        "selected_product_updated_at": (
            (product_selector.get("selected_product") or {}).get("updated_at", "")
        ),
        "workflow_status": workflow_status.get("workflow_status", "unknown"),
        "remaining_eligible_count": workflow_status.get("remaining_eligible_count", 0),
        "duplicate_write_protection_status": workflow_status.get(
            "duplicate_write_protection_status", ""
        ),
        "has_draft_result": bool(draft_result),
        "draft_status": draft_result.get("draft_status", ""),
        "total_fields_checked": draft_entry_count + skipped_entry_count,
        "new_translation_candidates": int(
            apply_plan_preview_result.get("apply_plan_candidate_count")
            or draft_counts.get("ready_for_apply_plan_count")
            or 0
        ),
        "existing_translations_skipped": int(
            draft_counts.get("existing_translation_count") or 0
        ),
        "skipped_entry_count": skipped_entry_count,
        "needs_review_count": int(draft_counts.get("needs_manual_review_count") or 0),
        "draft_blocked_count": int(draft_counts.get("draft_blocked_count") or 0),
        "product_identity_mismatch_count": int(
            draft_counts.get("product_identity_mismatch_count") or 0
        ),
        "seo_warning_count": int(draft_counts.get("seo_warning_count") or 0),
        "has_apply_plan_preview": bool(apply_plan_preview_result),
        "apply_plan_candidate_count": int(
            apply_plan_preview_result.get("apply_plan_candidate_count") or 0
        ),
        "blocked_or_needs_review_count": int(
            apply_plan_preview_result.get("blocked_or_needs_review_count") or 0
        ),
        "next_write_count": int(
            apply_plan_preview_result.get("apply_plan_candidate_count") or 0
        ),
        "candidate_entries": (
            apply_plan_preview_result.get("candidate_entries") or []
        )[:5],
        "has_locked_report": bool(locked_package_report_result)
        or bool(locked_report_approval_checklist.get("report_available")),
        "report_status": (
            locked_package_report_result.get("report_status")
            or locked_report_approval_checklist.get("report_status")
            or ""
        ),
        "report_entry_count": int(
            locked_package_report_result.get("entry_count")
            or locked_report_approval_checklist.get("entry_count")
            or 0
        ),
        "report_generated_at": report_generated_at,
        "safe_for_manual_review": bool(
            locked_report_approval_checklist.get("safe_for_manual_review")
        ),
        "approval_checklist_status": locked_report_approval_checklist.get(
            "checklist_status", ""
        ),
        "approval_product_match": (
            bool(locked_report_approval_checklist.get("selected_product_gid"))
            and locked_report_approval_checklist.get("selected_product_gid")
            == locked_report_approval_checklist.get("product_gid")
        ),
        "approval_safety_status": (
            "all clear"
            if locked_report_approval_checklist.get("safety_flags_all_false")
            else "needs review"
        ),
        "manual_command_status": manual_command_package.get("package_status", ""),
        "manual_command_ready": bool(
            manual_command_package.get("command_package_ready")
        ),
        "manual_command_blocking_conditions": manual_command_package.get(
            "blocking_conditions", []
        ),
        "draft_coverage_summary": draft_result.get("draft_coverage_summary") or {},
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
    }


def build_translation_workspace_single_product_mvp(
    product_selector: dict | None,
    result: dict | None,
    editor_view: dict | None,
    draft_result: dict | None,
    apply_plan_preview_result: dict | None,
    locale: str,
    supported_locales,
):
    product_selector = product_selector or {}
    result = result or {}
    editor_view = editor_view or {}
    draft_result = draft_result or {}
    apply_plan_preview_result = apply_plan_preview_result or {}
    selected_product = product_selector.get("selected_product") or {}
    product = result.get("product") or {}
    product_gid = (
        editor_view.get("product_gid")
        or product.get("id")
        or product_selector.get("selected_product_gid", "")
    )
    product_title = (
        editor_view.get("product_title")
        or product.get("title")
        or selected_product.get("title", "")
    )
    translatable_resource = result.get("translatable_resource") or {}
    source_data_loaded = bool(
        product.get("id")
        or translatable_resource.get("translatable_content_count")
        or draft_result.get("source_read_summary")
    )
    field_coverage = editor_view.get("field_coverage") or {}
    coverage_by_area = {
        entry.get("area_key"): entry
        for entry in field_coverage.get("entries") or []
        if isinstance(entry, dict)
    }
    draft_coverage_summary = draft_result.get("draft_coverage_summary") or {}
    draft_coverage_by_group = {
        group.get("group_key"): group
        for group in draft_coverage_summary.get("groups") or []
        if isinstance(group, dict)
    }
    groups = [
        _translation_workspace_mvp_group(
            "product_basics",
            "Product basics",
            ("title", "body_html"),
            coverage_by_area,
            draft_coverage_by_group,
            product_gid=product_gid,
            source_data_loaded=source_data_loaded,
        ),
        _translation_workspace_mvp_group(
            "seo",
            "SEO",
            ("meta_title", "meta_description", "handle"),
            coverage_by_area,
            draft_coverage_by_group,
            product_gid=product_gid,
            source_data_loaded=source_data_loaded,
        ),
        _translation_workspace_mvp_group(
            "options",
            "Product options",
            ("options",),
            coverage_by_area,
            draft_coverage_by_group,
            product_gid=product_gid,
            source_data_loaded=source_data_loaded,
        ),
        _translation_workspace_mvp_group(
            "variants",
            "Variants",
            ("variants",),
            coverage_by_area,
            draft_coverage_by_group,
            product_gid=product_gid,
            source_data_loaded=source_data_loaded,
        ),
        _translation_workspace_mvp_group(
            "important_metafields",
            "Important metafields",
            ("important_metafields",),
            coverage_by_area,
            draft_coverage_by_group,
            product_gid=product_gid,
            source_data_loaded=source_data_loaded,
        ),
        _translation_workspace_mvp_group(
            "media",
            "Media alt text",
            ("media",),
            coverage_by_area,
            draft_coverage_by_group,
            product_gid=product_gid,
            source_data_loaded=source_data_loaded,
        ),
        _translation_workspace_mvp_group(
            "technical_fields",
            "Technical / not translated",
            ("technical_metafields",),
            coverage_by_area,
            draft_coverage_by_group,
            product_gid=product_gid,
            source_data_loaded=source_data_loaded,
        ),
    ]
    next_actions = _translation_workspace_mvp_next_actions(
        product_gid=product_gid,
        source_data_loaded=source_data_loaded,
        draft_result=draft_result,
        apply_plan_preview_result=apply_plan_preview_result,
    )
    return {
        "summary_status": (
            "ready_for_single_product_review"
            if product_gid and source_data_loaded
            else ("select_product_first" if not product_gid else "load_read_only_rows")
        ),
        "selected_product_title": product_title,
        "selected_product_gid": product_gid,
        "selected_locale": locale,
        "selected_locale_label": _translation_editor_locale_label(locale),
        "supported_target_locales": list(supported_locales or []),
        "draft_fields": list(TRANSLATION_WORKSPACE_DRAFT_FIELDS),
        "source_data_loaded": source_data_loaded,
        "translatable_content_count": int(
            translatable_resource.get("translatable_content_count") or 0
        ),
        "editor_row_count": int(editor_view.get("editor_row_count") or 0),
        "groups": groups,
        "next_actions": next_actions,
        "has_draft_result": bool(draft_result),
        "draft_status": draft_result.get("draft_status", ""),
        "draft_coverage_summary_status": draft_coverage_summary.get(
            "summary_status", "not_loaded"
        ),
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
    }


def _translation_workspace_mvp_group(
    group_key: str,
    label: str,
    area_keys: tuple[str, ...],
    coverage_by_area: dict,
    draft_coverage_by_group: dict,
    product_gid: str,
    source_data_loaded: bool,
):
    items = [
        _translation_workspace_mvp_item(
            coverage_by_area.get(area_key) or {},
            fallback_area_key=area_key,
            product_gid=product_gid,
            source_data_loaded=source_data_loaded,
        )
        for area_key in area_keys
    ]
    included_labels = [
        item["label"] for item in items if item["mvp_status"] == "included"
    ]
    editor_only_labels = [
        item["label"] for item in items if item["mvp_status"] == "editor_only"
    ]
    needs_mapping_labels = [
        item["label"] for item in items if item["mvp_status"] == "needs_mapping"
    ]
    missing_labels = [
        item["label"] for item in items if item["mvp_status"] == "missing"
    ]
    not_loaded_labels = [
        item["label"] for item in items if item["mvp_status"] == "not_loaded"
    ]
    if not product_gid:
        status_label = "Select product"
        status_key = "select_product"
    elif not source_data_loaded:
        status_label = "Load read-only rows"
        status_key = "not_loaded"
    elif included_labels and not (editor_only_labels or needs_mapping_labels or missing_labels):
        status_label = "Included in draft"
        status_key = "included"
    elif included_labels:
        status_label = "Partially included"
        status_key = "partially_included"
    elif needs_mapping_labels:
        status_label = "Needs mapping"
        status_key = "needs_mapping"
    elif editor_only_labels:
        status_label = "Editor-only"
        status_key = "editor_only"
    else:
        status_label = "Missing"
        status_key = "missing"

    draft_group = draft_coverage_by_group.get(group_key) or {}
    return {
        "group_key": group_key,
        "label": label,
        "status_key": status_key,
        "status_label": status_label,
        "items": items,
        "included_labels": included_labels,
        "editor_only_labels": editor_only_labels,
        "needs_mapping_labels": needs_mapping_labels,
        "missing_labels": missing_labels,
        "not_loaded_labels": not_loaded_labels,
        "source_row_count": sum(int(item.get("row_count") or 0) for item in items),
        "visible_row_count": sum(
            int(item.get("visible_row_count") or 0) for item in items
        ),
        "draft_source_row_count": int(draft_group.get("source_row_count") or 0),
        "missing_translation_count": int(
            draft_group.get("missing_translation_count") or 0
        ),
        "existing_translation_count": int(
            draft_group.get("existing_translation_count") or 0
        ),
        "outdated_translation_count": int(
            draft_group.get("outdated_translation_count") or 0
        ),
        "notes": draft_group.get("notes") or _translation_workspace_mvp_group_note(
            group_key
        ),
    }


def _translation_workspace_mvp_item(
    entry: dict,
    fallback_area_key: str,
    product_gid: str,
    source_data_loaded: bool,
):
    area_key = entry.get("area_key") or fallback_area_key
    label = entry.get("area_label") or _translation_workspace_mvp_area_label(area_key)
    coverage_status = entry.get("coverage_status", "")
    support_status = entry.get("support_status", "")
    row_count = int(entry.get("row_count") or 0)
    visible_statuses = {"visible", "available_hidden_by_filter", "nested_only"}
    if not product_gid:
        mvp_status = "select_product"
        status_label = "Select product"
    elif not source_data_loaded:
        mvp_status = "not_loaded"
        status_label = "Not loaded"
    elif coverage_status not in visible_statuses:
        mvp_status = "missing"
        status_label = "Missing"
    elif support_status == "draft_supported":
        mvp_status = "included"
        status_label = "Included"
    elif area_key in {"options", "variants"} and row_count:
        mvp_status = "needs_mapping"
        status_label = "Visible, needs mapping"
    else:
        mvp_status = "editor_only"
        status_label = "Editor-only"
    return {
        "area_key": area_key,
        "label": label,
        "mvp_status": mvp_status,
        "status_label": status_label,
        "coverage_label": entry.get("coverage_label", ""),
        "support_label": entry.get("support_label", ""),
        "row_count": row_count,
        "visible_row_count": int(entry.get("visible_row_count") or 0),
        "field_keys": entry.get("field_keys") or [],
        "notes": entry.get("notes", ""),
    }


def _translation_workspace_mvp_area_label(area_key: str) -> str:
    labels = {
        "title": "Product title",
        "body_html": "Description / body HTML",
        "meta_title": "SEO meta title",
        "meta_description": "SEO meta description",
        "handle": "URL handle",
        "options": "Product options",
        "variants": "Variants",
        "important_metafields": "Important metafields",
        "media": "Media alt text",
        "technical_metafields": "Other technical fields",
    }
    return labels.get(area_key, _translation_editor_humanize_key(area_key))


def _translation_workspace_mvp_group_note(group_key: str) -> str:
    notes = {
        "product_basics": "Title and body HTML can be previewed locally. Body HTML remains review-only for later approval steps.",
        "seo": "Meta title and meta description can be previewed locally.",
        "options": "Option names or values can get local translation results. Future Shopify write mapping remains blocked.",
        "variants": "Variant titles or labels can get local translation results when Shopify exposes them. SKU remains context only.",
        "important_metafields": "Important customer-facing metafields can get local translation results. Future Shopify write mapping remains blocked.",
        "media": "Media/image alt text can get local translation results when Shopify exposes it.",
        "technical_fields": "Other technical fields stay collapsed and out of the translation package.",
    }
    return notes.get(group_key, "")


def _translation_workspace_mvp_next_actions(
    product_gid: str,
    source_data_loaded: bool,
    draft_result: dict,
    apply_plan_preview_result: dict,
):
    draft_ready = bool(draft_result)
    candidate_count = int(apply_plan_preview_result.get("apply_plan_candidate_count") or 0)
    return [
        {
            "label": "Prepare translation package in Workbench",
            "status": "ready" if product_gid else "select_product_first",
        },
        {
            "label": "Review translation preview",
            "status": "ready" if source_data_loaded else "open_or_refresh_editor",
        },
        {
            "label": "Generate locked dry-run report",
            "status": (
                "ready_after_review"
                if candidate_count
                else ("translation_has_no_ready_candidates" if draft_ready else "translate_first")
            ),
        },
        {
            "label": "Manual PowerShell write later",
            "status": "outside_web_page_locked_step",
        },
    ]


def build_translation_console_editor_view(
    product_selector: dict | None,
    result: dict | None,
    draft_result: dict | None,
    apply_plan_preview_result: dict | None,
    locale: str,
    editor_filter: str = "all",
    editor_search_query: str = "",
):
    product_selector = product_selector or {}
    result = result or {}
    draft_result = draft_result or {}
    apply_plan_preview_result = apply_plan_preview_result or {}
    locale = (locale or "ja").strip()
    editor_filter = editor_filter if editor_filter in TRANSLATION_CONSOLE_EDITOR_FILTERS else "all"
    editor_search_query = (editor_search_query or "").strip()
    selected_product = product_selector.get("selected_product") or {}
    product = result.get("product") or {}
    product_has_read_only_lookup = bool(product.get("id"))
    product_gid = product.get("id") or product_selector.get("selected_product_gid", "")
    product_title = product.get("title") or selected_product.get("title", "")

    draft_entries = _translation_editor_draft_entries_by_key(draft_result, locale)
    source_rows = _translation_editor_source_rows_by_key(result)
    source_identity_context = build_product_identity_context(
        product={**selected_product, **product},
        translatable_rows=result.get("translatable_rows") or [],
    )
    field_keys = list(dict.fromkeys(list(source_rows.keys()) + list(draft_entries.keys())))
    if "title" in field_keys and not source_rows.get("title") and product_title:
        source_rows["title"] = {
            "key": "title",
            "source_value": product_title,
            "digest": "",
            "source_locale": "en",
            "target_locale": locale,
            "has_translation": False,
            "translation_value": "",
            "translation_outdated": False,
        }
    elif not field_keys and product_title and not product_has_read_only_lookup:
        source_rows["title"] = {
            "key": "title",
            "source_value": product_title,
            "digest": "",
            "source_locale": "en",
            "target_locale": locale,
            "has_translation": False,
            "translation_value": "",
            "translation_outdated": False,
        }
        field_keys = ["title"]

    rows = [
        _build_translation_editor_row(
            field_key=field_key,
            source_row=source_rows.get(field_key) or {},
            draft_entry=draft_entries.get(field_key) or {},
            locale=locale,
            source_identity_context=source_identity_context,
        )
        for field_key in field_keys
    ]
    searched_rows = [
        row for row in rows if _translation_editor_row_matches_search(row, editor_search_query)
    ]
    visible_rows = [
        row for row in searched_rows if _translation_editor_row_matches_filter(row, editor_filter)
    ]
    sections = []
    folded_row_count = 0
    for section_config in TRANSLATION_CONSOLE_EDITOR_SECTIONS:
        section_key = section_config["section_key"]
        section_rows = [row for row in visible_rows if row["section_key"] == section_key]
        collapsed_by_default = bool(section_config.get("collapsed_by_default"))
        if collapsed_by_default:
            folded_row_count += len(section_rows)
        sections.append(
            {
                "section_key": section_key,
                "section_label": section_config["section_label"],
                "section_hint": section_config.get("section_hint", ""),
                "rows": section_rows,
                "row_count": len(section_rows),
                "has_rows": bool(section_rows),
                "collapsible": bool(section_config.get("collapsible")),
                "collapsed_by_default": collapsed_by_default,
                "is_folded_noise_group": collapsed_by_default,
            }
        )
    field_coverage = build_translation_workspace_field_coverage(
        rows=rows,
        visible_rows=visible_rows,
        locale=locale,
        product_gid=product_gid,
    )
    filter_labels = [
        ("all", "All"),
        ("untranslated", "Needs translation"),
        ("needs_review", "Needs review"),
        ("draft_only", "Preview only"),
        ("seo", "SEO"),
        ("variants_options", "Variants/options"),
        ("metafields", "Metafields"),
        ("media", "Media"),
    ]
    status_summary = {
        "visible": len(visible_rows),
        "untranslated": len(
            [
                row
                for row in searched_rows
                if _translation_editor_row_matches_filter(row, "untranslated")
            ]
        ),
        "translated": len(
            [
                row
                for row in searched_rows
                if _translation_editor_row_matches_filter(row, "translated")
            ]
        ),
        "outdated": len(
            [
                row
                for row in searched_rows
                if _translation_editor_row_matches_filter(row, "outdated")
            ]
        ),
        "needs_review": len(
            [
                row
                for row in searched_rows
                if _translation_editor_row_matches_filter(row, "needs_review")
            ]
        ),
        "draft_only": len(
            [
                row
                for row in searched_rows
                if _translation_editor_row_matches_filter(row, "draft_only")
            ]
        ),
    }
    filter_tabs = [
        {
            "value": value,
            "label": label,
            "active": editor_filter == value,
            "count": len(
                [
                    row
                    for row in searched_rows
                    if _translation_editor_row_matches_filter(row, value)
                ]
            ),
        }
        for value, label in filter_labels
    ]
    if not product_gid:
        empty_message = "Choose a product to review its text."
    elif not rows:
        empty_message = "No text was found for this product."
    elif not visible_rows:
        empty_message = "No text matches this filter."
    else:
        empty_message = ""
    return {
        "editor_view_enabled": True,
        "editor_locale": locale,
        "editor_locale_label": _translation_editor_locale_label(locale),
        "editor_filter": editor_filter,
        "editor_active_filter_label": dict(filter_labels).get(editor_filter, "All"),
        "editor_search_query": editor_search_query,
        "product_gid": product_gid,
        "product_title": product_title,
        "editor_selected_product_label": product_title or product_gid or "No product selected",
        "sections": sections,
        "filter_tabs": filter_tabs,
        "editor_row_count": len(rows),
        "editor_visible_row_count": len(visible_rows),
        "editor_folded_row_count": folded_row_count,
        "editor_primary_visible_row_count": len(visible_rows) - folded_row_count,
        "editor_search_result_count": len(searched_rows),
        "status_summary": status_summary,
        "field_coverage": field_coverage,
        "editor_has_rows": bool(rows),
        "editor_has_visible_rows": bool(visible_rows),
        "editor_empty_message": empty_message,
        "has_draft_result": bool(draft_result),
        "has_apply_plan_preview": bool(apply_plan_preview_result),
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
    }


def build_translation_workspace_field_coverage(
    rows: list[dict],
    visible_rows: list[dict],
    locale: str,
    product_gid: str = "",
):
    rows = rows or []
    visible_rows = visible_rows or []
    locale = (locale or "ja").strip()
    normalized_draft_fields = {
        _translation_editor_normalize_field_key(field)
        for field in TRANSLATION_WORKSPACE_DRAFT_FIELDS
    }
    rows_by_key = {}
    for row in rows:
        field_key = _translation_editor_normalize_field_key(row.get("field_key"))
        if field_key:
            rows_by_key.setdefault(field_key, []).append(row)
    visible_row_ids = {id(row) for row in visible_rows}

    entries = []
    core_entries = []
    for area in TRANSLATION_WORKSPACE_FIELD_COVERAGE_CORE_AREAS:
        entry = _build_translation_workspace_field_coverage_entry(
            area=area,
            rows_by_key=rows_by_key,
            visible_row_ids=visible_row_ids,
            draft_fields=normalized_draft_fields,
        )
        entries.append(entry)
        core_entries.append(entry)

    image_alt_entry = _build_translation_workspace_image_alt_coverage_entry(
        rows_by_key=rows_by_key,
        visible_row_ids=visible_row_ids,
    )
    entries.append(image_alt_entry)

    for section_key, section_label in TRANSLATION_WORKSPACE_FIELD_COVERAGE_EXTRA_SECTIONS:
        entries.append(
            _build_translation_workspace_section_coverage_entry(
                section_key=section_key,
                section_label=section_label,
                rows=rows,
                visible_row_ids=visible_row_ids,
            )
        )

    draft_supported_entries = [
        entry for entry in entries if entry["support_status"] == "draft_supported"
    ]
    visible_statuses = {"visible", "available_hidden_by_filter", "nested_only"}
    missing_core_fields = [
        entry["area_label"]
        for entry in core_entries
        if entry["coverage_status"] == "missing"
    ]
    review_only_or_unsupported = [
        entry["area_label"]
        for entry in entries
        if entry["support_status"] != "draft_supported"
    ]
    visible_row_keys = sorted(
        {
            row.get("field_key", "")
            for row in rows
            if row.get("field_key")
        }
    )
    return {
        "locale": locale,
        "product_gid": product_gid,
        "entries": entries,
        "core_area_count": len(core_entries),
        "core_visible_count": len(
            [
                entry
                for entry in core_entries
                if entry["coverage_status"] in visible_statuses
            ]
        ),
        "draft_supported_area_count": len(draft_supported_entries),
        "draft_supported_visible_count": len(
            [
                entry
                for entry in draft_supported_entries
                if entry["coverage_status"] in visible_statuses
            ]
        ),
        "editor_row_count": len(rows),
        "visible_row_count": len(visible_rows),
        "missing_core_fields": missing_core_fields,
        "missing_core_count": len(missing_core_fields),
        "review_only_or_unsupported_count": len(review_only_or_unsupported),
        "review_only_or_unsupported_fields": review_only_or_unsupported,
        "visible_row_keys": visible_row_keys,
        "has_product": bool(product_gid),
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
    }


def _build_translation_workspace_field_coverage_entry(
    area: dict,
    rows_by_key: dict,
    visible_row_ids: set[int],
    draft_fields: set[str],
):
    field_keys = [
        _translation_editor_normalize_field_key(field)
        for field in area.get("field_keys", ())
    ]
    matching_rows = []
    for field_key in field_keys:
        matching_rows.extend(rows_by_key.get(field_key) or [])
    visible_count = sum(1 for row in matching_rows if id(row) in visible_row_ids)
    if matching_rows and visible_count:
        coverage_status = "visible"
        coverage_label = "Visible"
    elif matching_rows:
        coverage_status = "available_hidden_by_filter"
        coverage_label = "Available, hidden by filter"
    else:
        coverage_status = "missing"
        coverage_label = "Missing"

    draft_supported = any(field_key in draft_fields for field_key in field_keys)
    support_status = "draft_supported" if draft_supported else "review_only"
    support_label = (
        "Draft package supported"
        if draft_supported
        else "Review-only in editor"
    )
    notes = area.get("note", "")
    if not matching_rows:
        notes = f"{notes} Not returned by the current product translation data.".strip()
    elif not draft_supported:
        notes = f"{notes} Current draft generation does not cover this field.".strip()
    return {
        "area_key": area.get("area_key", ""),
        "area_label": area.get("area_label", ""),
        "group_label": area.get("group_label", ""),
        "coverage_status": coverage_status,
        "coverage_label": coverage_label,
        "support_status": support_status,
        "support_label": support_label,
        "field_keys": field_keys,
        "row_count": len(matching_rows),
        "visible_row_count": visible_count,
        "notes": notes,
    }


def _build_translation_workspace_image_alt_coverage_entry(
    rows_by_key: dict,
    visible_row_ids: set[int],
):
    body_rows = (rows_by_key.get("body_html") or []) + (rows_by_key.get("description") or [])
    visible_count = sum(1 for row in body_rows if id(row) in visible_row_ids)
    body_html = "\n".join(
        str(row.get("source_value") or row.get("target_value_display") or "")
        for row in body_rows
    )
    has_image_tag = bool(re.search(r"<img\b", body_html, flags=re.IGNORECASE))
    has_alt_attribute = bool(
        re.search(r"<img\b[^>]*\balt\s*=", body_html, flags=re.IGNORECASE)
    )
    if not body_rows:
        coverage_status = "missing"
        coverage_label = "Missing"
        notes = "Image alt text cannot be reviewed because Description / body HTML is missing."
    elif has_image_tag and has_alt_attribute:
        coverage_status = "nested_only"
        coverage_label = "Nested in body HTML"
        notes = "Alt attributes are visible inside Description HTML only; there is no separate alt-text editor row."
    elif has_image_tag:
        coverage_status = "nested_only"
        coverage_label = "Image HTML visible"
        notes = "Image tags are visible inside Description HTML, but separate alt-text coverage is not available."
    else:
        coverage_status = "not_detected"
        coverage_label = "Not detected"
        notes = "No image tags were detected in the visible Description HTML source."
    return {
        "area_key": "image_alt_text",
        "area_label": "Image alt text in body HTML",
        "group_label": "Media",
        "coverage_status": coverage_status,
        "coverage_label": coverage_label,
        "support_status": "not_separate_field",
        "support_label": "No separate editor row",
        "field_keys": ["body_html"],
        "row_count": len(body_rows),
        "visible_row_count": visible_count,
        "notes": notes,
    }


def _build_translation_workspace_section_coverage_entry(
    section_key: str,
    section_label: str,
    rows: list[dict],
    visible_row_ids: set[int],
):
    section_rows = [row for row in rows if row.get("section_key") == section_key]
    visible_count = sum(1 for row in section_rows if id(row) in visible_row_ids)
    if section_rows and visible_count:
        coverage_status = "visible"
        coverage_label = "Visible"
    elif section_rows:
        coverage_status = "available_hidden_by_filter"
        coverage_label = "Available, hidden by filter"
    else:
        coverage_status = "missing"
        coverage_label = "Missing"
    field_keys = sorted(
        {
            row.get("field_key", "")
            for row in section_rows
            if row.get("field_key")
        }
    )
    notes = (
        _translation_workspace_section_coverage_notes(section_key, section_rows)
        if section_rows
        else "No rows in this section were returned by the current product translation data."
    )
    has_draft_eligible_rows = any(row.get("draft_eligible") for row in section_rows)
    return {
        "area_key": section_key,
        "area_label": section_label,
        "group_label": "Additional sections",
        "coverage_status": coverage_status,
        "coverage_label": coverage_label,
        "support_status": "draft_supported" if has_draft_eligible_rows else "review_only",
        "support_label": (
            "Local drafts supported"
            if has_draft_eligible_rows
            else "Review-only in editor"
        ),
        "field_keys": field_keys,
        "row_count": len(section_rows),
        "visible_row_count": visible_count,
        "notes": notes,
    }


def _translation_workspace_section_coverage_notes(section_key: str, section_rows: list[dict]):
    eligible_count = sum(1 for row in section_rows if row.get("draft_eligible"))
    if section_key == "options":
        return f"{eligible_count} option row(s) are draft eligible; future Shopify writes remain blocked pending resource mapping."
    if section_key == "variants":
        return f"{eligible_count} variant row(s) are draft eligible; SKU, barcode, ID, and code-like values stay context-only."
    if section_key == "important_metafields":
        return f"{eligible_count} customer-facing metafield row(s) are draft eligible; future Shopify writes remain blocked pending resource mapping."
    if section_key == "media":
        return f"{eligible_count} media alt row(s) are draft eligible when source alt text is present."
    return "Rows in this section are visible for review only and excluded from draft generation."


def _translation_editor_draft_entries_by_key(draft_result: dict, locale: str):
    entries = {}
    for entry in draft_result.get("entries") or []:
        if not isinstance(entry, dict) or entry.get("locale") != locale:
            continue
        field_key = _translation_editor_row_identity(entry)
        if field_key:
            entries[field_key] = entry
    return entries


def _translation_editor_source_rows_by_key(result: dict):
    rows = {}
    for row in result.get("translatable_rows") or []:
        if not isinstance(row, dict):
            continue
        field_key = _translation_editor_row_identity(row)
        if field_key:
            rows[field_key] = row
    return rows


def _translation_editor_row_identity(row: dict) -> str:
    return str(
        row.get("entry_key")
        or row.get("draft_key")
        or row.get("field_key")
        or row.get("key")
        or row.get("field")
        or ""
    )


def _build_translation_editor_row(
    field_key: str,
    source_row: dict,
    draft_entry: dict,
    locale: str,
    source_identity_context: dict | None = None,
):
    field_key = _translation_editor_normalize_field_key(
        source_row.get("field_key") or draft_entry.get("field_key") or field_key
    )
    source_value = str(
        source_row.get("source_value")
        or draft_entry.get("source_value")
        or ""
    )
    existing_value = str(
        source_row.get("translation_value")
        or source_row.get("target_value_display")
        or source_row.get("target_value")
        or draft_entry.get("existing_translation_value")
        or draft_entry.get("translation_value")
        or ""
    )
    draft_value = str(draft_entry.get("draft_value") or "")
    existing_translation_present = bool(
        source_row.get("has_translation")
        or draft_entry.get("existing_translation_present")
        or existing_value
    )
    outdated = (
        source_row.get("translation_outdated") is True
        or draft_entry.get("existing_translation_outdated") is True
    )
    target_value = existing_value or draft_value
    seo_notes = _list_from_value(draft_entry.get("seo_notes"))
    seo_review_notes = _list_from_value(draft_entry.get("seo_review_notes")) or [
        note
        for note in seo_notes
        if note in TRANSLATION_WORKSPACE_REVIEW_REASON_CODES
    ]
    quality_notes = _list_from_value(draft_entry.get("quality_notes"))
    target_identity = {}
    if target_value:
        identity_context = (
            draft_entry.get("source_identity_context")
            or source_identity_context
            or build_product_identity_context(source_values=[source_value])
        )
        target_identity = validate_product_identity_draft(
            identity_context,
            target_value,
            field=field_key,
        )
    target_identity_mismatch = bool(target_identity.get("product_identity_mismatch"))
    validation_reasons = _translation_editor_unique_list(
        _list_from_value(draft_entry.get("validation_reasons"))
        + _list_from_value(target_identity.get("validation_reasons"))
    )
    suspicious_terms = _translation_editor_unique_list(
        _list_from_value(draft_entry.get("suspicious_terms"))
        + _list_from_value(target_identity.get("suspicious_terms"))
    )
    identity_warning = str(
        draft_entry.get("identity_warning_text")
        or draft_entry.get("warning_text")
        or target_identity.get("warning_text")
        or ""
    ).strip()
    if target_identity_mismatch and existing_value:
        identity_warning = "This existing translation may mention a different product. Please review before using."
    draft_blocked = bool(
        draft_entry.get("draft_blocked")
        or (draft_value and not existing_value and target_identity_mismatch)
    )
    product_identity_mismatch = bool(
        draft_entry.get("product_identity_mismatch") or target_identity_mismatch
    )
    validation_status = draft_entry.get("validation_status", "")
    if product_identity_mismatch and validation_status in {"", "skipped"}:
        validation_status = (
            "existing_translation_needs_review_identity_mismatch"
            if existing_value
            else "blocked"
        )
    seo_status = draft_entry.get("seo_validation_status", "")
    blocking_reasons = _translation_editor_unique_list(
        (
            _draft_entry_blocking_reasons(draft_entry, seo_review_notes, quality_notes)
            if draft_entry
            else []
        )
        + validation_reasons
        + (["product_identity_mismatch"] if product_identity_mismatch else [])
    )
    review_blocking_reasons = [
        reason
        for reason in blocking_reasons
        if reason in TRANSLATION_WORKSPACE_REVIEW_REASON_CODES
    ]
    needs_review = bool(
        draft_blocked
        or product_identity_mismatch
        or seo_review_notes
        or quality_notes
        or validation_reasons
        or review_blocking_reasons
        or (
            draft_value
            and validation_status
            and validation_status != "draft_ready_for_manual_review"
        )
        or (draft_value and seo_status and seo_status != "seo_ready")
    )
    if existing_translation_present and outdated:
        translation_status = "outdated"
    elif needs_review:
        translation_status = "needs_review"
    elif existing_translation_present:
        translation_status = "translated"
    elif draft_value:
        translation_status = "draft_only"
    elif (
        source_row.get("draft_eligible") is False
        or (
            draft_entry
            and draft_entry.get("draft_eligible") is False
            and draft_entry.get("skip_reason")
        )
    ):
        translation_status = "not_eligible"
    elif draft_entry.get("skip_reason"):
        translation_status = "skipped"
    else:
        translation_status = "untranslated"

    badges = []
    if existing_translation_present:
        badges.append(
            "existing translation needs review"
            if product_identity_mismatch
            else "existing translation"
        )
    if outdated:
        badges.append("outdated")
    if draft_value and not existing_translation_present:
        badges.append("translation result")
    if source_value and source_row.get("draft_eligible") is False:
        badges.append("not eligible")
    if draft_entry.get("future_write_needs_mapping") or source_row.get("future_write_needs_mapping"):
        badges.append("future write blocked")
    if seo_review_notes:
        badges.append("SEO warning")
    if product_identity_mismatch:
        badges.append("wrong product")
    if draft_blocked:
        badges.append("needs review")
    if review_blocking_reasons:
        badges.append("blocked")
    if not target_value:
        badges.append("untranslated")
    char_limit = TRANSLATION_CONSOLE_EDITOR_SEO_LIMITS.get(field_key)
    target_chars = len(target_value)
    exceeds_limit = bool(char_limit and target_chars > char_limit)
    if exceeds_limit:
        badges.append("exceeds limit")
    section_key = (
        source_row.get("section_key")
        or draft_entry.get("section_key")
        or _translation_editor_section_key(field_key)
    )
    resource_type_label = (
        source_row.get("resource_type_label")
        or draft_entry.get("resource_type_label")
        or _translation_editor_resource_type_label(field_key)
    )
    resource_detail = _translation_editor_resource_detail(field_key, source_row, draft_entry)
    resource_note = _translation_editor_resource_note(field_key, source_row, draft_entry)
    has_html_preview = field_key == "body_html"
    return {
        "section_key": section_key,
        "field_key": field_key,
        "field_label": (
            source_row.get("field_label")
            or draft_entry.get("field_label")
            or _translation_editor_field_label(field_key)
        ),
        "resource_type_label": resource_type_label,
        "resource_detail": resource_detail,
        "resource_note": resource_note,
        "resource_key": (
            source_row.get("source_key")
            or source_row.get("key")
            or draft_entry.get("source_key")
            or field_key
        ),
        "resource_id": source_row.get("resource_id") or draft_entry.get("resource_id", ""),
        "source_value": source_value,
        "source_value_preview": _translation_editor_preview_text(
            source_value,
            field_key=field_key,
        ),
        "source_value_html_preview": (
            _translation_editor_sanitize_html_preview(source_value)
            if has_html_preview
            else ""
        ),
        "target_value_display": target_value,
        "existing_value_preview": _translation_editor_preview_text(
            existing_value,
            field_key=field_key,
        ),
        "draft_value_preview": _translation_editor_preview_text(
            draft_value,
            field_key=field_key,
        ),
        "target_value_preview": _translation_editor_preview_text(
            target_value,
            field_key=field_key,
        ),
        "target_value_html_preview": (
            _translation_editor_sanitize_html_preview(target_value)
            if has_html_preview and target_value
            else ""
        ),
        "target_value_source": (
            "existing translation"
            if existing_value
            else ("translation result" if draft_value else "")
        ),
        "target_value_source_label": (
            ("Existing translation" if product_identity_mismatch else "Already translated")
            if existing_value
            else ("Preview only" if draft_value else "")
        ),
        "translation_status": translation_status,
        "translation_status_label": _translation_editor_status_label(translation_status),
        "status_badges": badges,
        "status_badge_labels": [
            _translation_editor_badge_label(badge) for badge in badges
        ],
        "target_chars": target_chars,
        "char_limit": char_limit,
        "char_count_display": f"{target_chars}/{char_limit}" if char_limit else str(target_chars),
        "exceeds_limit": exceeds_limit,
        "seo_warning": ", ".join(seo_notes),
        "seo_review_notes": ", ".join(seo_review_notes),
        "identity_warning": identity_warning,
        "suspicious_terms": ", ".join(suspicious_terms),
        "validation_reasons": ", ".join(validation_reasons),
        "product_identity_validation_status": (
            draft_entry.get("product_identity_validation_status")
            or target_identity.get("validation_status")
            or ""
        ),
        "product_identity_mismatch": product_identity_mismatch,
        "draft_blocked": draft_blocked,
        "validation_status": validation_status,
        "seo_status": seo_status,
        "existing_translation_present": existing_translation_present,
        "outdated": outdated,
        "digest": source_row.get("digest") or draft_entry.get("source_digest") or "",
        "draft_eligible": (
            source_row.get("draft_eligible")
            if "draft_eligible" in source_row
            else draft_entry.get("draft_eligible")
        ),
        "draft_ineligible_reason": source_row.get("draft_ineligible_reason")
        or draft_entry.get("draft_ineligible_reason", ""),
        "future_write_needs_mapping": bool(
            source_row.get("future_write_needs_mapping")
            or draft_entry.get("future_write_needs_mapping")
        ),
        "apply_plan_blocked_reason": source_row.get("apply_plan_blocked_reason")
        or draft_entry.get("apply_plan_blocked_reason", ""),
        "needs_review": needs_review,
        "full_description_display": has_html_preview,
        "has_html_preview": has_html_preview,
        "read_only": True,
    }


def _translation_editor_status_label(status: str) -> str:
    labels = {
        "translated": "Already translated",
        "outdated": "Needs review",
        "needs_review": "Needs review",
        "draft_only": "Preview only",
        "skipped": "Not translated automatically",
        "not_eligible": "Not translated automatically",
        "untranslated": "Needs translation",
    }
    return labels.get(str(status or ""), _translation_editor_humanize_key(status))


def _translation_editor_badge_label(badge: str) -> str:
    labels = {
        "existing translation": "Already translated",
        "existing translation needs review": "Existing translation",
        "outdated": "Needs review",
        "translation result": "Translation result",
        "SEO warning": "Needs review",
        "wrong product": "Possible wrong product",
        "needs review": "Needs review",
        "blocked": "Needs review",
        "untranslated": "Needs translation",
        "exceeds limit": "Too long",
        "not eligible": "Not translated automatically",
        "future write blocked": "Can review now; Shopify update support needs extra mapping",
    }
    return labels.get(str(badge or ""), _translation_editor_humanize_key(badge))


def _translation_editor_row_matches_search(row: dict, query: str) -> bool:
    if not query:
        return True
    query = query.lower()
    haystack = " ".join(
        str(row.get(key, ""))
        for key in [
            "field_label",
            "field_key",
            "resource_type_label",
            "resource_detail",
            "resource_note",
            "resource_key",
            "source_value",
            "target_value_display",
            "identity_warning",
            "suspicious_terms",
            "validation_reasons",
            "translation_status",
            "translation_status_label",
        ]
    ).lower()
    return query in haystack


def _translation_editor_row_matches_filter(row: dict, editor_filter: str) -> bool:
    status = row.get("translation_status")
    if editor_filter == "all":
        return True
    if editor_filter == "translated":
        return status == "translated"
    if editor_filter in {"untranslated", "needs_translation"}:
        return status == "untranslated"
    if editor_filter == "outdated":
        return status == "outdated"
    if editor_filter == "draft_only":
        return status == "draft_only"
    if editor_filter == "needs_review":
        return bool(row.get("needs_review")) or status in {
            "outdated",
            "needs_review",
        }
    if editor_filter == "seo":
        return row.get("section_key") == "seo"
    if editor_filter == "variants_options":
        return row.get("section_key") in {"options", "variants"}
    if editor_filter == "metafields":
        return row.get("section_key") in {"important_metafields", "technical_metafields"}
    if editor_filter == "media":
        return row.get("section_key") == "media"
    return True


def _translation_editor_normalize_field_key(value: str):
    value = str(value or "").strip()
    key = value.split(".", 1)[-1] if value.startswith("product.") else value
    if key == "description":
        return "body_html"
    return key


def _translation_editor_section_key(field_key: str) -> str:
    key = str(field_key or "").lower()
    if key in {"title", "body_html", "description", "product_type"}:
        return "basic"
    if key in {"handle", "meta_title", "meta_description"}:
        return "seo"
    if "option" in key:
        return "options"
    if "variant" in key:
        return "variants"
    if key.startswith("media.") or "image_alt" in key or key.endswith(".alt"):
        return "media"
    if _translation_editor_is_metafield_key(key):
        if _translation_editor_is_important_metafield(key):
            return "important_metafields"
        return "technical_metafields"
    return "basic"


def _translation_editor_field_label(field_key: str) -> str:
    field_key = str(field_key or "")
    labels = {
        "title": "Product title",
        "body_html": "Product description",
        "description": "Product description",
        "product_type": "Product type",
        "handle": "URL handle",
        "meta_title": "SEO title",
        "meta_description": "SEO description",
    }
    if field_key in labels:
        return labels[field_key]
    section_key = _translation_editor_section_key(field_key)
    if section_key == "options":
        return _translation_editor_option_label(field_key)
    if section_key == "variants":
        return _translation_editor_variant_label(field_key)
    if section_key in {"important_metafields", "technical_metafields"}:
        return _translation_editor_metafield_label(field_key)
    return _translation_editor_humanize_key(field_key)


def _translation_editor_resource_type_label(field_key: str) -> str:
    section_key = _translation_editor_section_key(field_key)
    labels = {
        "basic": "Product field",
        "seo": "SEO field",
        "options": "Option field",
        "variants": "Variant field",
        "important_metafields": "Important metafield",
        "media": "Media alt text",
        "technical_metafields": "Technical / other field",
    }
    return labels.get(section_key, "Product field")


def _translation_editor_resource_detail(field_key: str, source_row: dict, draft_entry: dict) -> str:
    if source_row.get("context_label") or draft_entry.get("context_label"):
        return source_row.get("context_label") or draft_entry.get("context_label")
    section_key = _translation_editor_section_key(field_key)
    if section_key in {"important_metafields", "technical_metafields"}:
        namespace, key = _translation_editor_metafield_parts(field_key)
        if namespace and key:
            return f"{namespace} / {key}"
        return key or namespace or ""
    if section_key == "variants":
        return _translation_editor_variant_detail(field_key, source_row, draft_entry)
    if section_key == "options":
        return _translation_editor_option_detail(field_key, source_row, draft_entry)
    return ""


def _translation_editor_resource_note(field_key: str, source_row: dict, draft_entry: dict) -> str:
    if source_row.get("resource_note") or draft_entry.get("resource_note"):
        return source_row.get("resource_note") or draft_entry.get("resource_note")
    section_key = _translation_editor_section_key(field_key)
    if section_key in {"important_metafields", "technical_metafields"}:
        namespace, key = _translation_editor_metafield_parts(field_key)
        parts = []
        if namespace:
            parts.append(f"Namespace: {namespace}")
        if key:
            parts.append(f"Key: {key}")
        parts.append(
            "Group: important"
            if section_key == "important_metafields"
            else "Group: other / technical"
        )
        return " | ".join(parts)
    if section_key == "variants":
        details = _translation_editor_existing_variant_bits(source_row, draft_entry)
        return " | ".join(details)
    if section_key == "options":
        details = _translation_editor_existing_option_bits(source_row, draft_entry)
        return " | ".join(details)
    return ""


def _translation_editor_is_metafield_key(field_key: str) -> bool:
    key = str(field_key or "").lower()
    if key in {
        "title",
        "body_html",
        "description",
        "product_type",
        "handle",
        "meta_title",
        "meta_description",
        "media.alt",
    }:
        return False
    if "option" in key or "variant" in key or key.startswith("media."):
        return False
    return "metafield" in key or "." in key


def _translation_editor_is_important_metafield(field_key: str) -> bool:
    namespace, key = _translation_editor_metafield_parts(field_key)
    namespace = namespace.lower()
    if namespace in TRANSLATION_EDITOR_TECHNICAL_METAFIELD_NAMESPACES:
        return False
    if _translation_editor_key_matches_hint(
        f"{namespace}.{key}", TRANSLATION_EDITOR_TECHNICAL_METAFIELD_HINTS
    ):
        return False
    if namespace in TRANSLATION_EDITOR_IMPORTANT_METAFIELD_NAMESPACES:
        return True
    return _translation_editor_key_matches_hint(
        f"{namespace}.{key}", TRANSLATION_EDITOR_IMPORTANT_METAFIELD_HINTS
    )


def _translation_editor_metafield_parts(field_key: str) -> tuple[str, str]:
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


def _translation_editor_option_label(field_key: str) -> str:
    tokens = set(_translation_editor_key_tokens(field_key))
    option_number = _translation_editor_option_number(field_key)
    prefix = f"Product option {option_number}" if option_number else "Product option"
    if "value" in tokens or "values" in tokens:
        return f"{prefix} value"
    if "name" in tokens:
        return f"{prefix} name"
    return prefix


def _translation_editor_variant_label(field_key: str) -> str:
    tokens = set(_translation_editor_key_tokens(field_key))
    if "sku" in tokens:
        return "Variant SKU"
    if "title" in tokens:
        return "Variant title"
    if "option" in tokens or any(token.startswith("option") for token in tokens):
        return "Variant option"
    return "Variant field"


def _translation_editor_metafield_label(field_key: str) -> str:
    namespace, key = _translation_editor_metafield_parts(field_key)
    if key:
        return f"Metafield: {_translation_editor_humanize_key(key)}"
    if namespace:
        return f"Metafield: {_translation_editor_humanize_key(namespace)}"
    return "Metafield"


def _translation_editor_option_detail(field_key: str, source_row: dict, draft_entry: dict) -> str:
    option_name = _translation_editor_first_value(
        source_row,
        draft_entry,
        ("option_name", "name", "option"),
    )
    option_value = _translation_editor_first_value(
        source_row,
        draft_entry,
        ("option_value", "value", "variant_option"),
    )
    if option_name and option_value:
        return f"{option_name}: {option_value}"
    return option_name or option_value or _translation_editor_option_label(field_key)


def _translation_editor_variant_detail(field_key: str, source_row: dict, draft_entry: dict) -> str:
    details = _translation_editor_existing_variant_bits(source_row, draft_entry)
    if details:
        return " | ".join(details)
    return _translation_editor_variant_label(field_key)


def _translation_editor_existing_option_bits(source_row: dict, draft_entry: dict) -> list[str]:
    bits = []
    option_name = _translation_editor_first_value(
        source_row,
        draft_entry,
        ("option_name", "name", "option"),
    )
    option_value = _translation_editor_first_value(
        source_row,
        draft_entry,
        ("option_value", "variant_option", "selected_option_value"),
    )
    if option_name:
        bits.append(f"Option: {option_name}")
    if option_value:
        bits.append(f"Value: {option_value}")
    return bits


def _translation_editor_existing_variant_bits(source_row: dict, draft_entry: dict) -> list[str]:
    bits = []
    variant_title = _translation_editor_first_value(
        source_row,
        draft_entry,
        ("variant_title", "title", "variant_name"),
    )
    option_value = _translation_editor_first_value(
        source_row,
        draft_entry,
        ("option_value", "variant_option", "selected_option_value"),
    )
    sku = _translation_editor_first_value(source_row, draft_entry, ("sku", "variant_sku"))
    variant_id = _translation_editor_first_value(source_row, draft_entry, ("variant_id", "resource_id"))
    if variant_title:
        bits.append(f"Variant: {variant_title}")
    if variant_id:
        bits.append(f"Variant ID: {variant_id}")
    if option_value:
        bits.append(f"Option: {option_value}")
    if sku:
        bits.append(f"SKU: {sku}")
    return bits


def _translation_editor_first_value(
    source_row: dict,
    draft_entry: dict,
    keys: tuple[str, ...],
) -> str:
    for key in keys:
        value = source_row.get(key)
        if value not in (None, ""):
            return str(value)
        value = draft_entry.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _translation_editor_option_number(field_key: str) -> str:
    match = re.search(r"option[_ .:-]*(\d+)", str(field_key or ""), flags=re.IGNORECASE)
    return match.group(1) if match else ""


def _translation_editor_key_tokens(field_key: str) -> list[str]:
    return [
        token
        for token in re.split(r"[^a-z0-9]+", str(field_key or "").lower())
        if token
    ]


def _translation_editor_key_matches_hint(field_key: str, hints: tuple[str, ...]) -> bool:
    tokens = set(_translation_editor_key_tokens(field_key))
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


def _translation_editor_humanize_key(field_key: str) -> str:
    return str(field_key or "").replace("_", " ").replace(".", " / ").title()


def _translation_editor_locale_label(locale: str) -> str:
    canonical_locale = _translation_editor_canonical_locale(locale)
    return TRANSLATION_EDITOR_LOCALE_LABELS.get(canonical_locale, locale)


def _translation_editor_canonical_locale(locale: str) -> str:
    text = str(locale or "").strip()
    if not text:
        return ""
    normalized = text.lower().replace("_", "-")
    supported = set(SUPPORTED_TRANSLATION_LOCALES)
    candidates = [normalized]
    if "(" in normalized and ")" in normalized:
        candidates.append(normalized.rsplit("(", 1)[1].split(")", 1)[0].strip())
    if " " in normalized:
        candidates.append(normalized.split(" ", 1)[0].strip())
    if "-" in normalized:
        candidates.append(normalized.split("-", 1)[0].strip())
    alias = TRANSLATION_EDITOR_LOCALE_LABEL_ALIASES.get(normalized)
    if alias:
        candidates.append(alias)
    for candidate in candidates:
        candidate = str(candidate or "").strip().lower()
        if candidate in supported:
            return candidate
        base_locale = candidate.split("-", 1)[0]
        if base_locale in supported:
            return base_locale
    return text


def _empty_apply_plan_preview_result(reason: str):
    return {
        "preview_status": "apply_plan_preview_empty",
        "preview_only": True,
        "product_id": "",
        "product_title": "",
        "configured_locale_scope": [],
        "configured_fields": [],
        "apply_plan_candidate_count": 0,
        "blocked_or_needs_review_count": 0,
        "seo_warning_count": 0,
        "existing_translation_count": 0,
        "candidate_entries": [],
        "blocked_entries": [],
        "candidate_entries_truncated": False,
        "blocked_entries_truncated": False,
        "max_rows": TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS,
        "blocking_conditions": [reason],
        "read_only": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "no_new_shopify_writes_performed": True,
    }


def _empty_locked_package_report_result(reason: str):
    return {
        "report_status": "translation_console_locked_package_dry_run_blocked",
        "json_report_path": "",
        "html_report_path": "",
        "entry_count": 0,
        "blocked_or_needs_review_count": 0,
        "blocking_conditions": [reason],
        "dry_run_only": True,
        "preview_only": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
    }


def _normalize_apply_plan_preview_entry(entry: dict):
    seo_notes = _list_from_value(entry.get("seo_notes"))
    seo_review_notes = _list_from_value(entry.get("seo_review_notes")) or [
        note
        for note in seo_notes
        if note in TRANSLATION_WORKSPACE_REVIEW_REASON_CODES
    ]
    quality_notes = _list_from_value(entry.get("quality_notes"))
    blocking_reasons = _draft_entry_blocking_reasons(
        entry,
        seo_review_notes,
        quality_notes,
    )
    proposed_value = str(entry.get("draft_value") or "").strip()
    current_translation_present = bool(entry.get("existing_translation_present"))
    outdated = entry.get("existing_translation_outdated") is True
    seo_ready = (
        entry.get("seo_eligible_for_apply_plan") is True
        or entry.get("seo_validation_status") == "seo_ready"
    )
    reasons = []
    if entry.get("eligible_for_apply_plan") is not True:
        reasons.append("not_eligible_for_apply_plan")
    if not seo_ready:
        reasons.append("seo_not_ready")
    if current_translation_present:
        reasons.append("current_translation_present")
    if outdated:
        reasons.append("current_translation_outdated")
    if not proposed_value:
        reasons.append("missing_proposed_translation")
    if blocking_reasons:
        reasons.extend(blocking_reasons)
    reasons = list(dict.fromkeys(reason for reason in reasons if reason))
    would_write = not reasons
    return {
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "resource_key": entry.get("source_key") or entry.get("field", ""),
        "resource_id": entry.get("resource_id", ""),
        "resource_group": entry.get("resource_group", ""),
        "context_label": entry.get("context_label", ""),
        "proposed_translation_preview": _preview_text(proposed_value),
        "planned_value": proposed_value,
        "source_preview": _preview_text(entry.get("source_value")),
        "chars": len(proposed_value),
        "seo_status": entry.get("seo_validation_status", ""),
        "planned_value_source": "draft_result" if proposed_value else "",
        "digest": entry.get("source_digest", ""),
        "would_write": would_write,
        "safety_status": (
            "preview_only_no_write" if would_write else "blocked_or_needs_review"
        ),
        "reason": ", ".join(reasons),
        "seo_warning": ", ".join(seo_notes),
        "validation_status": entry.get("validation_status", ""),
        "product_identity_validation_status": entry.get(
            "product_identity_validation_status", ""
        ),
        "validation_reasons": ", ".join(_list_from_value(entry.get("validation_reasons"))),
        "suspicious_terms": ", ".join(_list_from_value(entry.get("suspicious_terms"))),
        "identity_warning": entry.get("identity_warning_text")
        or entry.get("warning_text", ""),
        "product_identity_mismatch": bool(entry.get("product_identity_mismatch")),
        "draft_blocked": bool(entry.get("draft_blocked")),
        "future_write_needs_mapping": bool(entry.get("future_write_needs_mapping")),
        "apply_plan_blocked_reason": entry.get("apply_plan_blocked_reason", ""),
        "blocking_reasons": ", ".join(reasons),
        "current_translation_present": current_translation_present,
        "outdated": outdated,
    }


def _translation_workspace_entry_write_eligibility(entry: dict):
    if not str(entry.get("draft_value") or "").strip():
        return "not applicable"
    if (
        entry.get("eligible_for_apply_plan") is True
        and entry.get("field") in TRANSLATION_WORKSPACE_APPLY_SUPPORTED_FIELDS
        and not entry.get("future_write_needs_mapping")
    ):
        return "apply eligible"
    if entry.get("future_write_needs_mapping"):
        return "needs mapping"
    if entry.get("draft_blocked") or entry.get("product_identity_mismatch"):
        return "blocked"
    return "manual review"


def _translation_workspace_entry_write_eligibility_key(entry: dict):
    return _translation_workspace_locale_status_key(
        _translation_workspace_entry_write_eligibility(entry)
    )


def _translation_workspace_existing_or_review_text_fields(
    row: dict,
    prefix: str,
    fallback_preview: str,
    field: str,
):
    display = str(row.get(f"{prefix}_display") or "")
    summary = str(row.get(f"{prefix}_summary") or "")
    if display or summary:
        return {
            "display": display or summary,
            "summary": summary or _preview_text(display, TRANSLATION_CONSOLE_REVIEW_SUMMARY_CHARS),
            "is_long": bool(row.get(f"{prefix}_is_long")),
            "truncated": bool(row.get(f"{prefix}_truncated")),
        }
    return _translation_workspace_review_text_fields(
        prefix,
        fallback_preview,
        field,
        unprefixed=True,
    )


def _translation_workspace_review_text_fields(
    prefix: str,
    value,
    field: str,
    *,
    unprefixed: bool = False,
):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    display = _translation_workspace_review_text(text)
    is_long = (
        _translation_editor_normalize_field_key(field) == "body_html"
        or len(text) > TRANSLATION_CONSOLE_REVIEW_SUMMARY_CHARS
        or "\n" in text
    )
    payload = {
        "summary": _preview_text(text, TRANSLATION_CONSOLE_REVIEW_SUMMARY_CHARS),
        "display": display,
        "is_long": is_long,
        "truncated": len(text) > len(display),
    }
    if unprefixed:
        return payload
    return {f"{prefix}_{key}": value for key, value in payload.items()}


def _translation_workspace_review_text(value):
    text = str(value or "").strip()
    if len(text) <= TRANSLATION_CONSOLE_REVIEW_TEXT_CHARS:
        return text
    return text[: TRANSLATION_CONSOLE_REVIEW_TEXT_CHARS - 3].rstrip() + "..."


def _translation_workspace_split_reasons(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        source_values = value
    else:
        source_values = re.split(r"\s*,\s*", str(value))
    return [
        str(item).strip()
        for item in source_values
        if str(item).strip()
    ]


def _translation_console_draft_summary(draft_result: dict):
    if not draft_result:
        return {"blocking_conditions": ["missing_draft_result"]}
    detail = draft_result.get("translation_console_detail") or {}
    seo_warning_count = (
        int(draft_result.get("seo_needs_manual_review_count") or 0)
        + int(draft_result.get("over_length_after_rewrite_count") or 0)
        + int(draft_result.get("forbidden_phrase_count") or 0)
        + int(draft_result.get("missing_core_keyword_count") or 0)
        + int(draft_result.get("too_short_for_seo_count") or 0)
    )
    skipped_count = (
        int(draft_result.get("skipped_existing_translation_count") or 0)
        + int(draft_result.get("skipped_outdated_translation_count") or 0)
        + int(draft_result.get("skipped_source_empty_count") or 0)
        + int(draft_result.get("skipped_not_draft_eligible_count") or 0)
    )
    return {
        "selected_product_title": draft_result.get("product_title", ""),
        "selected_product_gid": draft_result.get("product_id", ""),
        "locales": ", ".join(draft_result.get("target_locales") or []),
        "configured_fields": ", ".join(draft_result.get("requested_fields") or []),
        "draft_status": draft_result.get("draft_status", ""),
        "draft_entry_count": detail.get(
            "draft_entry_count", draft_result.get("generated_draft_count", 0)
        ),
        "missing_drafts_generated": draft_result.get(
            "missing_translation_draft_generated_count", 0
        ),
        "outdated_update_drafts_generated": draft_result.get(
            "outdated_translation_update_draft_generated_count", 0
        ),
        "already_translated_skipped": draft_result.get(
            "already_translated_skipped_count", 0
        ),
        "not_eligible_skipped": draft_result.get("not_eligible_skipped_count", 0),
        "needs_review_blocked": draft_result.get("needs_review_or_blocked_count", 0),
        "skipped_entry_count": detail.get("skipped_entry_count", skipped_count),
        "seo_warning_count": seo_warning_count,
        "ready_for_apply_plan_count": draft_result.get("eligible_apply_plan_count", 0),
        "needs_manual_review_count": draft_result.get(
            "draft_needs_manual_review_count", 0
        ),
        "draft_blocked_count": draft_result.get("draft_blocked_count", 0),
        "product_identity_mismatch_count": draft_result.get(
            "product_identity_mismatch_count", 0
        ),
        "existing_translation_count": draft_result.get(
            "skipped_existing_translation_count", 0
        ),
        "draft_coverage_summary": draft_result.get("draft_coverage_summary") or {},
        "child_resource_discovery_errors": draft_result.get(
            "child_resource_discovery_errors"
        )
        or [],
        "per_group_discovery_status": draft_result.get("per_group_discovery_status")
        or {},
        "per_group_discovery_reasons": draft_result.get("per_group_discovery_reasons")
        or {},
        "blocking_conditions": draft_result.get("blocking_conditions") or [],
        "shopify_write_performed": draft_result.get("shopify_write_performed", False),
        "mutation_performed": draft_result.get("mutation_performed", False),
        "translations_register_called": draft_result.get(
            "translations_register_called", False
        ),
        "rollback_performed": draft_result.get("rollback_performed", False),
    }


def _attach_translation_console_draft_detail(
    draft_result: dict,
    max_rows: int = TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS,
):
    if not isinstance(draft_result, dict):
        return
    max_rows = int(max_rows or TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS)
    draft_entries = []
    skipped_entries = []
    all_entries = []
    draft_entry_ids = {
        _translation_console_draft_entry_identity(entry)
        for entry in (draft_result.get("draft_entries") or [])
        if isinstance(entry, dict)
    }
    for entry in draft_result.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_translation_console_draft_entry(entry)
        all_entries.append(normalized)
        if _translation_console_draft_entry_identity(entry) in draft_entry_ids or entry.get(
            "draft_value"
        ):
            draft_entries.append(normalized)
        else:
            skipped_entries.append(normalized)

    summary = _translation_console_draft_detail_counts(
        draft_result, draft_entries, skipped_entries
    )
    draft_result["translation_console_detail"] = {
        "max_rows": max_rows,
        "preview_chars": TRANSLATION_CONSOLE_DRAFT_PREVIEW_CHARS,
        "draft_entries": draft_entries[:max_rows],
        "skipped_entries": skipped_entries[:max_rows],
        "all_entries": all_entries[:max_rows],
        "draft_entry_count": len(draft_entries),
        "skipped_entry_count": len(skipped_entries),
        "all_entry_count": len(all_entries),
        "draft_entries_truncated": len(draft_entries) > max_rows,
        "skipped_entries_truncated": len(skipped_entries) > max_rows,
        "all_entries_truncated": len(all_entries) > max_rows,
        "summary_counts": summary,
    }


def _translation_console_draft_entry_identity(entry: dict):
    return (
        entry.get("locale", ""),
        entry.get("draft_key")
        or entry.get("entry_key")
        or entry.get("source_key")
        or entry.get("field", ""),
    )


def _normalize_translation_console_draft_entry(entry: dict):
    seo_notes = _list_from_value(entry.get("seo_notes"))
    seo_review_notes = _list_from_value(entry.get("seo_review_notes")) or [
        note
        for note in seo_notes
        if note in TRANSLATION_WORKSPACE_REVIEW_REASON_CODES
    ]
    quality_notes = _list_from_value(entry.get("quality_notes"))
    blocking_reasons = _draft_entry_blocking_reasons(
        entry,
        seo_review_notes,
        quality_notes,
    )
    return {
        "locale": entry.get("locale", ""),
        "language": entry.get("locale", ""),
        "section": entry.get("section_label") or entry.get("resource_group", ""),
        "section_label": entry.get("section_label", ""),
        "field": entry.get("field", ""),
        "key": entry.get("source_key") or entry.get("field", ""),
        "resource_key": entry.get("source_key") or entry.get("field", ""),
        "resource_id": entry.get("resource_id", ""),
        "source_digest": entry.get("source_digest", ""),
        "digest": entry.get("source_digest", ""),
        "resource_group": entry.get("resource_group", ""),
        "context_label": entry.get("context_label", ""),
        "resource_note": entry.get("resource_note", ""),
        "option_name": entry.get("option_name", ""),
        "option_value": entry.get("option_value", ""),
        "option_position": entry.get("option_position", ""),
        "related_variants": entry.get("related_variants", []),
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
        "status": entry.get("row_status") or entry.get("status") or "",
        "reason": entry.get("status_reason") or entry.get("skip_reason", ""),
        "has_generated_draft": bool(str(entry.get("draft_value") or "").strip()),
        "write_eligibility": _translation_workspace_entry_write_eligibility(entry),
        "write_eligibility_key": _translation_workspace_entry_write_eligibility_key(entry),
        "source_value": entry.get("source_value", ""),
        "source_identity_context": entry.get("source_identity_context") or {},
        "source_value_preview": _preview_text(entry.get("source_value")),
        **_translation_workspace_review_text_fields(
            "source_value", entry.get("source_value"), entry.get("field", "")
        ),
        "proposed_translation": entry.get("draft_value", ""),
        "proposed_translation_preview": _preview_text(entry.get("draft_value")),
        **_translation_workspace_review_text_fields(
            "proposed_translation", entry.get("draft_value"), entry.get("field", "")
        ),
        "proposed_chars": entry.get("draft_value_chars") or 0,
        "validation_status": entry.get("validation_status", ""),
        "product_identity_validation_status": entry.get(
            "product_identity_validation_status", ""
        ),
        "validation_reasons": ", ".join(_list_from_value(entry.get("validation_reasons"))),
        "suspicious_terms": ", ".join(_list_from_value(entry.get("suspicious_terms"))),
        "identity_warning": entry.get("identity_warning_text")
        or entry.get("warning_text", ""),
        "product_identity_mismatch": bool(entry.get("product_identity_mismatch")),
        "draft_blocked": bool(entry.get("draft_blocked")),
        "seo_validation_status": entry.get("seo_validation_status", ""),
        "seo_notes": seo_notes,
        "seo_review_notes": seo_review_notes,
        "quality_notes": quality_notes,
        "seo_warning": ", ".join(seo_notes),
        "eligible_for_apply_plan": bool(entry.get("eligible_for_apply_plan")),
        "future_write_needs_mapping": bool(entry.get("future_write_needs_mapping")),
        "apply_plan_blocked_reason": entry.get("apply_plan_blocked_reason", ""),
        "draft_eligible": entry.get("draft_eligible"),
        "draft_ineligible_reason": entry.get("draft_ineligible_reason", ""),
        "blocking_reasons": ", ".join(blocking_reasons),
        "skip_reason": entry.get("skip_reason", ""),
        "current_translation_present": bool(entry.get("existing_translation_present")),
        "outdated": entry.get("existing_translation_outdated"),
        "existing_translation_outdated": entry.get("existing_translation_outdated"),
        "existing_translation_value": entry.get("existing_translation_value")
        or entry.get("translation_value")
        or "",
        "existing_translation_preview": _preview_text(
            entry.get("existing_translation_value") or entry.get("translation_value")
        ),
        **_translation_workspace_review_text_fields(
            "existing_translation",
            entry.get("existing_translation_value") or entry.get("translation_value"),
            entry.get("field", ""),
        ),
    }


def _translation_console_draft_detail_counts(
    draft_result: dict, draft_entries: list[dict], skipped_entries: list[dict]
):
    skipped_count = (
        int(draft_result.get("skipped_existing_translation_count") or 0)
        + int(draft_result.get("skipped_outdated_translation_count") or 0)
        + int(draft_result.get("skipped_source_empty_count") or 0)
        + int(draft_result.get("skipped_not_draft_eligible_count") or 0)
    )
    return {
        "draft_entry_count": len(draft_entries),
        "skipped_entry_count": skipped_count or len(skipped_entries),
        "all_entry_count": len(draft_entries) + len(skipped_entries),
        "missing_drafts_generated": int(
            draft_result.get("missing_translation_draft_generated_count") or 0
        ),
        "outdated_update_drafts_generated": int(
            draft_result.get("outdated_translation_update_draft_generated_count") or 0
        ),
        "already_translated_skipped": int(
            draft_result.get("already_translated_skipped_count") or 0
        ),
        "not_eligible_skipped": int(draft_result.get("not_eligible_skipped_count") or 0),
        "needs_review_blocked": int(
            draft_result.get("needs_review_or_blocked_count") or 0
        ),
        "seo_warning_count": int(draft_result.get("seo_needs_manual_review_count") or 0),
        "ready_for_apply_plan_count": int(
            draft_result.get("eligible_apply_plan_count") or 0
        ),
        "needs_manual_review_count": int(
            draft_result.get("draft_needs_manual_review_count") or 0
        ),
        "draft_blocked_count": int(draft_result.get("draft_blocked_count") or 0),
        "product_identity_mismatch_count": int(
            draft_result.get("product_identity_mismatch_count") or 0
        ),
        "existing_translation_count": int(
            draft_result.get("skipped_existing_translation_count") or 0
        ),
    }


def _draft_entry_blocking_reasons(entry: dict, seo_notes: list[str], quality_notes: list[str]):
    reasons = []
    if entry.get("skip_reason") and entry.get("skip_reason") != "missing_translation":
        reasons.append(str(entry.get("skip_reason")))
    reasons.extend(_list_from_value(entry.get("validation_reasons")))
    reasons.extend(quality_notes)
    reasons.extend(
        reason
        for reason in seo_notes
        if reason in TRANSLATION_WORKSPACE_REVIEW_REASON_CODES
    )
    if entry.get("draft_blocked"):
        reasons.append("draft_blocked")
    if entry.get("future_write_needs_mapping"):
        reasons.append(entry.get("apply_plan_blocked_reason") or "future_write_needs_resource_mapping")
    if entry.get("draft_ineligible_reason"):
        reasons.append(str(entry.get("draft_ineligible_reason")))
    if entry.get("product_identity_mismatch"):
        reasons.append("product_identity_mismatch")
    if entry.get("validation_status") not in {
        "",
        "skipped",
        "draft_ready_for_manual_review",
    }:
        reasons.append(str(entry.get("validation_status")))
    if entry.get("seo_validation_status") not in {"", "skipped", "seo_ready"}:
        reasons.append(str(entry.get("seo_validation_status")))
    return list(dict.fromkeys(reason for reason in reasons if reason))


def _list_from_value(value):
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item)]
    return [str(value)]


def _translation_editor_unique_list(values):
    return list(dict.fromkeys(str(value) for value in values if str(value)))


class _TranslationConsoleHtmlPreviewSanitizer(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []
        self._drop_stack = []

    def handle_starttag(self, tag, attrs):
        normalized_tag = str(tag or "").lower()
        if self._drop_stack:
            if (
                normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_DROP_CONTENT_TAGS
                or normalized_tag == "iframe"
            ):
                self._drop_stack.append(normalized_tag)
            return
        if normalized_tag == "iframe":
            self._append_iframe_or_placeholder(attrs)
            self._drop_stack.append(normalized_tag)
            return
        if normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_DROP_CONTENT_TAGS:
            self._drop_stack.append(normalized_tag)
            return
        if normalized_tag not in TRANSLATION_CONSOLE_HTML_PREVIEW_ALLOWED_TAGS:
            return
        attr_text = _translation_editor_sanitized_html_preview_attrs(
            normalized_tag,
            attrs,
        )
        if normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_VOID_TAGS:
            self._parts.append(f"<{normalized_tag}{attr_text}>")
            return
        self._parts.append(f"<{normalized_tag}{attr_text}>")

    def handle_startendtag(self, tag, attrs):
        normalized_tag = str(tag or "").lower()
        if self._drop_stack:
            return
        if normalized_tag == "iframe":
            self._append_iframe_or_placeholder(attrs)
            return
        if normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_DROP_CONTENT_TAGS:
            return
        if normalized_tag not in TRANSLATION_CONSOLE_HTML_PREVIEW_ALLOWED_TAGS:
            return
        attr_text = _translation_editor_sanitized_html_preview_attrs(
            normalized_tag,
            attrs,
        )
        if normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_VOID_TAGS:
            self._parts.append(f"<{normalized_tag}{attr_text}>")
            return
        self._parts.append(f"<{normalized_tag}{attr_text}></{normalized_tag}>")

    def handle_endtag(self, tag):
        normalized_tag = str(tag or "").lower()
        if self._drop_stack:
            if normalized_tag == self._drop_stack[-1]:
                self._drop_stack.pop()
            elif normalized_tag in self._drop_stack:
                self._drop_stack = self._drop_stack[
                    : self._drop_stack.index(normalized_tag)
                ]
            return
        if normalized_tag == "iframe":
            return
        if (
            normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_ALLOWED_TAGS
            and normalized_tag not in TRANSLATION_CONSOLE_HTML_PREVIEW_VOID_TAGS
        ):
            self._parts.append(f"</{normalized_tag}>")

    def handle_data(self, data):
        if not self._drop_stack:
            self._parts.append(str(escape(data)))

    def _append_iframe_or_placeholder(self, attrs):
        attr_text = _translation_console_safe_iframe_attrs(attrs)
        if not attr_text:
            self._parts.append(TRANSLATION_CONSOLE_HTML_PREVIEW_BLOCKED_IFRAME_PLACEHOLDER)
            return
        self._parts.append(f"<iframe{attr_text}></iframe>")

    def get_html(self):
        return "".join(self._parts)


def _translation_console_safe_iframe_attrs(attrs) -> str:
    sanitized = []
    seen_names = set()
    has_safe_src = False
    for raw_name, raw_value in attrs or []:
        name = str(raw_name or "").lower()
        value = "" if raw_value is None else str(raw_value)
        if (
            not name
            or name in seen_names
            or name.startswith("on")
            or name not in TRANSLATION_CONSOLE_HTML_PREVIEW_IFRAME_ATTRS
        ):
            continue
        seen_names.add(name)
        if name == "src":
            value = value.strip()
            if not _translation_console_is_safe_video_url(value):
                continue
            has_safe_src = True
            sanitized.append(f' src="{escape(value)}"')
        elif name == "allowfullscreen":
            sanitized.append(" allowfullscreen")
        elif value:
            sanitized.append(f' {name}="{escape(value)}"')
    if not has_safe_src:
        return ""
    return "".join(sanitized)


def _translation_editor_sanitized_html_preview_attrs(tag: str, attrs) -> str:
    sanitized = []
    for raw_name, raw_value in attrs or []:
        name = str(raw_name or "").lower()
        value = "" if raw_value is None else str(raw_value)
        if not name or name.startswith("on"):
            continue
        if name == "dir" and value.lower() in {"auto", "ltr", "rtl"}:
            sanitized.append(f' dir="{escape(value.lower())}"')
        elif (
            tag == "a"
            and name == "href"
            and _translation_editor_html_preview_url_is_safe(value)
        ):
            sanitized.append(f' href="{escape(value)}"')
        elif tag == "a" and name == "title":
            sanitized.append(f' title="{escape(value)}"')
    if tag == "a" and any(attr.startswith(" href=") for attr in sanitized):
        sanitized.append(' rel="noopener noreferrer"')
    return "".join(sanitized)


def _translation_editor_html_preview_url_is_safe(value: str) -> bool:
    href = str(value or "").strip()
    if not href:
        return False
    compact_href = re.sub(r"[\x00-\x20]+", "", href).lower()
    if compact_href.startswith(("javascript:", "data:", "vbscript:")):
        return False
    parsed = urllib.parse.urlparse(compact_href)
    return parsed.scheme.lower() in TRANSLATION_CONSOLE_HTML_PREVIEW_SAFE_URL_SCHEMES


def _translation_console_is_safe_video_url(value: str) -> bool:
    src = str(value or "").strip()
    if not src:
        return False
    compact_src = re.sub(r"[\x00-\x20]+", "", src).lower()
    if compact_src.startswith(("javascript:", "data:", "vbscript:")):
        return False
    parsed = urllib.parse.urlparse(compact_src)
    if parsed.scheme and parsed.scheme not in {"http", "https"}:
        return False
    host = (parsed.hostname or "").rstrip(".").lower()
    return bool(host and host in TRANSLATION_CONSOLE_HTML_PREVIEW_VIDEO_HOSTS)


def _translation_editor_sanitize_html_preview(value):
    sanitizer = _TranslationConsoleHtmlPreviewSanitizer()
    try:
        sanitizer.feed(str(value or ""))
        sanitizer.close()
    except ValueError:
        return mark_safe(str(escape(value or "")))
    return mark_safe(sanitizer.get_html())


def _translation_editor_preview_text(
    value,
    max_chars: int = TRANSLATION_CONSOLE_EDITOR_PREVIEW_CHARS,
    field_key: str = "",
):
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    if _translation_editor_normalize_field_key(field_key) == "body_html":
        return text
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


def _preview_text(value, max_chars: int = TRANSLATION_CONSOLE_DRAFT_PREVIEW_CHARS):
    text = " ".join(str(value or "").split())
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "..."


@login_required
def sync_products(request):
    if not _user_has_shopify_sync_access(request):
        return HttpResponseForbidden("Only authorized Shopify sync users can sync products.")

    shop_domain = "kidstoylover.myshopify.com"
    try:
        installation = ShopifyInstallation.objects.get(shop=shop_domain)
    except ShopifyInstallation.DoesNotExist:
        return JsonResponse(
            {"error": f"Shopify installation not found for {shop_domain}"},
            status=400,
        )

    task_result = run_shopify_sync_task(
        "products_daily",
        lambda: sync_products_for_installation(installation),
        conflict_task_names=["products_daily"],
    )
    if task_result.get("skipped"):
        return JsonResponse(task_result, status=409)
    return JsonResponse(task_result["result"])


@login_required
def sync_shenzhen_orders(request):
    if not _user_has_shopify_sync_access(request):
        return HttpResponseForbidden("Only authorized Shopify sync users can sync Shenzhen orders.")

    try:
        days = int(request.GET.get("days", "3"))
    except ValueError:
        return JsonResponse({"error": "Invalid days value."}, status=400)
    if days not in {1, 3, 7, 30, 60}:
        return JsonResponse({"error": "days must be one of 1, 3, 7, 30, 60."}, status=400)

    shop_domain = "kidstoylover.myshopify.com"
    try:
        installation = ShopifyInstallation.objects.get(shop=shop_domain)
    except ShopifyInstallation.DoesNotExist:
        return JsonResponse(
            {"error": f"Shopify installation not found for {shop_domain}"},
            status=400,
        )

    task_result = run_shopify_sync_task(
        f"orders_manual_{days}",
        lambda: sync_shenzhen_orders_for_installation(installation, days=days),
        conflict_task_names=ORDER_SYNC_TASK_NAMES,
    )
    if task_result.get("skipped"):
        return JsonResponse(task_result, status=409)
    result = dict(task_result["result"])
    try:
        result["trustpilot_queue_auto_refresh"] = (
            run_trustpilot_auto_queue_refresh_after_shopify_order_sync()
        )
    except Exception as exc:
        result["trustpilot_queue_auto_refresh"] = {
            "success": False,
            "last_auto_refresh_status": "auto_refresh_failed_non_blocking",
            "last_auto_refresh_error": f"{exc.__class__.__name__}",
        }
    return JsonResponse(result)


@login_required
def update_shenzhen_tracking(request):
    if not _user_has_shopify_sync_access(request):
        return HttpResponseForbidden("Only authorized Shopify sync users can update Shenzhen tracking.")

    shop_domain = "kidstoylover.myshopify.com"
    try:
        installation = ShopifyInstallation.objects.get(shop=shop_domain)
    except ShopifyInstallation.DoesNotExist:
        return JsonResponse(
            {"error": f"Shopify installation not found for {shop_domain}"},
            status=400,
        )

    task_result = run_shopify_sync_task(
        "tracking_update",
        lambda: update_shenzhen_tracking_for_installation(installation),
        conflict_task_names=["tracking_update"],
    )
    if task_result.get("skipped"):
        return JsonResponse(task_result, status=409)
    return JsonResponse(task_result["result"])


@login_required
def _legacy_sync_dashboard(request):
    if not _user_has_shopify_sync_access(request):
        return HttpResponseForbidden("Only authorized Shopify sync users can view the Shopify sync dashboard.")

    return HttpResponse(
        "<html><head><meta charset='utf-8'><title>Shopify Sync Dashboard</title></head>"
        "<body style='font-family: Arial, sans-serif; padding: 24px;'>"
        "<h1>Shopify 同步仪表盘</h1>"
        "<p>以下按钮将直接调用 Shopify 同步接口，并显示 JSON 结果。</p>"
        "<div style='display: flex; flex-wrap: wrap; gap: 12px; margin-top: 20px;'>"
        "<a style='display:inline-block;padding:10px 16px;background:#0b5ed7;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/sync-products/'>同步 Shopify 产品</a>"
        "<a style='display:inline-block;padding:10px 16px;background:#198754;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/sync-shenzhen-orders/'>同步深圳仓订单</a>"
        "<a style='display:inline-block;padding:10px 16px;background:#fd7e14;color:#fff;text-decoration:none;border-radius:4px;' href='/auth/shopify/update-shenzhen-tracking/'>更新深圳仓物流</a>"
        "</div>"
        "</body></html>",
        content_type="text/html; charset=utf-8",
    )


