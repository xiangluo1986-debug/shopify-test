import json
import hmac
import os
import re
import secrets
import hashlib
import urllib.parse
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError

import requests
from django.contrib import admin
from django.core.exceptions import FieldDoesNotExist
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import F, Q
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
from .review_request_workbench import build_review_request_workbench_context
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
)
from .translation_apply_plan import (
    APPLY_PLAN_HTML_PATH,
    APPLY_PLAN_JSON_PATH,
    build_selected_product_translation_apply_plan,
)
from .translation_drafts import (
    DEFAULT_FIELDS as TRANSLATION_DRAFT_FIELDS,
    DEFAULT_TARGET_LOCALES as TRANSLATION_DRAFT_TARGET_LOCALES,
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
TRANSLATION_CONSOLE_DRAFT_PREVIEW_CHARS = 120
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
    "li",
    "ol",
    "p",
    "strong",
    "ul",
}
TRANSLATION_CONSOLE_HTML_PREVIEW_VOID_TAGS = {"br", "hr"}
TRANSLATION_CONSOLE_HTML_PREVIEW_DROP_CONTENT_TAGS = {
    "embed",
    "iframe",
    "object",
    "script",
    "style",
}
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
]
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
}
TRANSLATION_CONSOLE_EDITOR_SECTIONS = [
    {
        "section_key": "basic",
        "section_label": "Basic",
        "section_hint": "Core product fields shown first for daily review.",
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
        "section_key": "technical_metafields",
        "section_label": "Other metafields / technical fields",
        "section_hint": "Low-signal or system-like fields are folded to reduce daily noise.",
        "collapsible": True,
        "collapsed_by_default": True,
    },
]
TRANSLATION_CONSOLE_EDITOR_SEO_LIMITS = {
    "title": 70,
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
]
TRANSLATION_WORKSPACE_FIELD_COVERAGE_EXTRA_SECTIONS = [
    ("options", "Product options"),
    ("variants", "Variants"),
    ("important_metafields", "Important metafields"),
    ("technical_metafields", "Other metafields / technical fields"),
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


@staff_member_required
def review_request_workbench(request):
    if not _user_has_shopify_sync_access(request):
        return HttpResponseForbidden("Only authorized Shopify sync staff can view this workbench.")
    if request.method not in {"GET", "HEAD"}:
        return HttpResponseNotAllowed(["GET", "HEAD"])

    context = admin.site.each_context(request)
    context.update(build_review_request_workbench_context(request.GET))
    context["title"] = "Review Request Workbench"
    return render(request, "admin/shopify_sync/review_request_workbench.html", context)


@staff_member_required
def translation_console(request):
    post_action = (request.POST.get("action") or "").strip() if request.method == "POST" else ""
    is_refresh_status_post = post_action == "refresh_status"
    is_locked_package_preview_post = post_action in {
        "generate_locked_package_dry_run_placeholder",
        "generate_locked_package_dry_run_preview",
        "generate_locked_package_dry_run_report",
    }
    is_locked_package_report_post = post_action == "generate_locked_package_dry_run_report"
    is_status_only_safe_action_post = is_refresh_status_post
    is_multi_locale_draft_post = post_action == "generate_multi_locale_drafts"
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
        or is_apply_plan_post
        or is_final_review_post
        or is_readiness_post
        or is_locked_execution_plan_post
        or is_locked_executor_post
        or is_real_write_executor_post
        or is_real_write_manual_action_package_post
        or is_status_only_safe_action_post
        or is_locked_package_preview_post
    )
    request_params = request.POST if is_post_action else request.GET
    translation_console_warnings = []
    product_search_text = _translation_console_request_product_search_text(
        request_params,
        is_post_action=is_post_action,
    )
    raw_product_url_parameter = (
        request_params.get("product_gid", "") or request_params.get("product_id", "")
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
        request_params.get("selected_product_gid", "") or raw_product_url_parameter
    )
    raw_manual_product_gid = request_params.get("manual_product_gid", "")
    raw_post_product_query = request.POST.get("q", "") if is_post_action else ""
    raw_locale = (
        request_params.get("target_locale", "") or request_params.get("locale", "ja")
    )
    locale = ((raw_locale or "ja") or "ja").strip()
    if locale not in SUPPORTED_TRANSLATION_LOCALES:
        translation_console_warnings.append(
            f"Unsupported locale '{locale}' was ignored; using {SUPPORTED_TRANSLATION_LOCALES[0]}."
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
    )
    draft_locale_options = _translation_workspace_draft_locale_options(
        selected_locale=locale,
        requested_locales=(
            requested_draft_locales if is_multi_locale_draft_post else [locale]
        ),
    )
    product_selector = _build_translation_console_product_selector(
        product_search_text=product_search_text,
        requested_product_gid=(
            "" if invalid_product_url_parameter else raw_selected_product_gid or raw_manual_product_gid
        ),
    )
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
    workflow_product_id = (
        selected_product_gid
        if selected_product_gid.startswith("gid://shopify/Product/")
        else TRANSLATION_WORKFLOW_DEFAULT_PRODUCT_ID
    )

    should_run_translation_lookup = bool(action_product_query) and (
        (request.method == "POST" and not is_status_only_safe_action_post)
        or request.GET.get("fetch_read_only") == "1"
        or (request.method == "GET" and ui_mode == "editor")
    )

    if should_run_translation_lookup:
        try:
            installation = ShopifyInstallation.objects.first()
            if installation is None:
                error_message = f"Shopify installation not found for {shop_domain}."
            elif is_multi_locale_draft_post:
                if not requested_draft_locales:
                    multi_locale_draft_result = _translation_workspace_empty_multi_locale_result(
                        product_id=action_product_query,
                        selected_locale=locale,
                        requested_locales=requested_draft_locales,
                        invalid_locales=invalid_draft_locales,
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
                            )
                        )
                        multi_locale_draft_result = _translation_workspace_empty_multi_locale_result(
                            product_id=action_product_query,
                            selected_locale=locale,
                            requested_locales=requested_draft_locales,
                            invalid_locales=invalid_draft_locales,
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
                            "Draft generation blocked: "
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
                    draft_error_message = "Select a single Shopify product before generating drafts."
                    if post_action == "generate_draft_dry_run":
                        safe_action_result = _translation_console_safe_action_result(
                            action=post_action,
                            action_status="draft_dry_run_blocked",
                            message="Select a single Shopify product before generating a draft dry-run package.",
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
            error_message = f"Read-only Shopify query failed: {exc.__class__.__name__}"

    workflow_status = load_translation_workflow_status(workflow_product_id)
    if is_refresh_status_post:
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
    elif post_action == "generate_multi_locale_drafts" and safe_action_result is None:
        blocked_message = _translation_workspace_multi_locale_blocked_message(
            has_product=bool(action_product_query),
            requested_locales=requested_draft_locales,
            invalid_locales=invalid_draft_locales,
        )
        multi_locale_draft_result = _translation_workspace_empty_multi_locale_result(
            product_id=action_product_query,
            selected_locale=locale,
            requested_locales=requested_draft_locales,
            invalid_locales=invalid_draft_locales,
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

    return render(
        request,
        "admin/shopify_sync/translation_console.html",
        {
            "title": "Shopify Product Translation Console",
            "search_text": search_text,
            "product_search_text": product_search_text,
            "product_selector": product_selector,
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


def _build_translation_console_product_selector(
    product_search_text: str,
    requested_product_gid: str = "",
    limit: int = TRANSLATION_CONSOLE_PRODUCT_SELECTOR_LIMIT,
):
    query = (product_search_text or "").strip()
    requested_gid = normalize_product_gid((requested_product_gid or "").strip()) or ""
    queryset = ShopifyProduct.objects.all()
    supported_fields = _translation_console_supported_product_search_fields()
    order_by_fields, supported_sort_fields = _translation_console_product_ordering()
    for term in [part for part in query.split() if part.strip()]:
        queryset = queryset.filter(_translation_console_product_search_q(term, supported_fields))
    queryset = queryset.order_by(*order_by_fields)

    product_options = []
    seen_product_ids = set()
    for product in queryset[: max(limit * 20, limit)]:
        product_id = getattr(product, "shopify_product_id", None)
        if not product_id or product_id in seen_product_ids:
            continue
        seen_product_ids.add(product_id)
        product_options.append(_translation_console_selector_option_from_product(product))
        if len(product_options) >= limit:
            break

    if query:
        product_options.sort(
            key=lambda option: _translation_console_product_search_relevance(option, query),
            reverse=True,
        )

    matching_result_count = len(product_options)
    included_selected_product = False
    if requested_gid and not _find_selector_option(product_options, requested_gid):
        selected_option = _translation_console_selector_option_for_gid(requested_gid)
        if selected_option:
            product_options.insert(0, selected_option)
            included_selected_product = True

    selected_gid = requested_gid
    if not selected_gid:
        selected_gid = product_options[0]["gid"] if product_options else requested_gid

    return {
        "product_options": product_options,
        "selected_product_gid": selected_gid,
        "selected_product": _find_selector_option(product_options, selected_gid),
        "product_search_text": query,
        "result_count": len(product_options),
        "matching_result_count": matching_result_count,
        "limit": limit,
        "has_products": bool(product_options),
        "included_selected_product": included_selected_product,
        "no_matching_products": bool(query) and matching_result_count == 0,
        "no_products_available": not query and not product_options,
        "sort_fields": supported_sort_fields,
        "search_supported_fields": supported_fields,
    }


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
            product_gid,
        )
        if value
    )
    return {
        "gid": product_gid,
        "numeric_id": str(product_id),
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
    numeric_id = _extract_shopify_numeric_id(value)
    if numeric_id:
        if "shopify_product_id" in supported_fields:
            query |= Q(shopify_product_id=numeric_id)
        if "shopify_variant_id" in supported_fields:
            query |= Q(shopify_variant_id=numeric_id)
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
    return re.sub(r"[\s_-]+", "", (value or "").lower())


def _translation_console_product_search_relevance(option: dict, query: str) -> int:
    normalized_query = _translation_console_normalize_search_text(query)
    if not normalized_query:
        return 0
    searchable_normalized = (
        option.get("searchable_normalized")
        or _translation_console_normalize_search_text(option.get("searchable_text", ""))
    )
    title_normalized = _translation_console_normalize_search_text(option.get("title", ""))
    sku_normalized = _translation_console_normalize_search_text(option.get("sku", ""))
    variant_normalized = _translation_console_normalize_search_text(
        option.get("variant_title", "")
    )
    handle_normalized = _translation_console_normalize_search_text(option.get("handle", ""))
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
        score += 120
    if title_normalized.startswith(normalized_query):
        score += 90
    if normalized_query in title_normalized:
        score += 70
    if sku_normalized.startswith(normalized_query):
        score += 65
    if variant_normalized.startswith(normalized_query):
        score += 60
    if handle_normalized.startswith(normalized_query):
        score += 45
    if normalized_query in searchable_normalized:
        score += 35
    if tokens and all(token in searchable_normalized for token in tokens):
        score += 20 + len(tokens)
    return score


def _extract_shopify_numeric_id(value: str):
    normalized_gid = normalize_product_gid(value)
    if normalized_gid:
        return int(normalized_gid.rsplit("/", 1)[-1])
    numeric = (value or "").strip()
    if numeric.isdigit():
        return int(numeric)
    return None


def _find_selector_option(product_options, selected_gid: str):
    for option in product_options:
        if option.get("gid") == selected_gid:
            return option
    return {}


def _format_optional_datetime(value):
    if not value:
        return ""
    return value.isoformat()


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
):
    if not is_multi_locale_draft_post:
        return [], []

    raw_locales = request.POST.getlist("draft_target_locales")
    if not raw_locales:
        raw_locales = request.POST.getlist("target_locales")
    allowed_locales = set(SUPPORTED_TRANSLATION_LOCALES)
    requested = []
    invalid = []
    for raw_locale in raw_locales:
        locale = str(raw_locale or "").strip()
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
    checked_locales = set(requested_locales or [selected_locale])
    return [
        {
            "value": locale,
            "label": _translation_editor_locale_label(locale),
            "checked": locale in checked_locales,
        }
        for locale in SUPPORTED_TRANSLATION_LOCALES
    ]


def _translation_workspace_empty_multi_locale_result(
    product_id: str,
    selected_locale: str,
    requested_locales: list[str] | None,
    invalid_locales: list[str] | None,
    message: str = "",
    action_status: str = "multi_locale_draft_blocked",
    blocking_conditions: list[str] | None = None,
):
    requested_locales = list(requested_locales or [])
    invalid_locales = list(invalid_locales or [])
    blocking_conditions = list(blocking_conditions or [])
    locale_results = []
    if invalid_locales and "unsupported_target_language" not in blocking_conditions:
        blocking_conditions.append("unsupported_target_language")
    if not requested_locales and not invalid_locales:
        blocking_conditions.append("no_target_language_selected")
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
        if invalid_locales:
            message = "Choose only supported target languages."
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
        "locale_results": locale_results,
        "selected_locale_draft_result": None,
        "draft_fields": list(TRANSLATION_WORKSPACE_DRAFT_FIELDS),
        "field_scope_labels": _translation_workspace_draft_field_labels(),
        "summary": summary,
        "blocking_conditions": blocking_conditions,
        "read_only": True,
        "shopify_write_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "rollback_performed": False,
    }


def _generate_translation_workspace_multi_locale_drafts(
    installation,
    product_id: str,
    selected_locale: str,
    target_locales: list[str],
    invalid_locales: list[str] | None = None,
    product_search_text: str = "",
    editor_filter: str = "all",
    editor_search_query: str = "",
):
    locale_results = []
    selected_locale_draft_result = None
    for target_locale in target_locales:
        try:
            locale_draft_result = generate_selected_product_missing_translation_draft_package(
                product_id=product_id,
                target_locales=[target_locale],
                fields=TRANSLATION_WORKSPACE_DRAFT_FIELDS,
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
                "requested_fields": list(TRANSLATION_WORKSPACE_DRAFT_FIELDS),
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
        "locale_results": locale_results,
        "selected_locale_draft_result": selected_locale_draft_result,
        "draft_fields": list(TRANSLATION_WORKSPACE_DRAFT_FIELDS),
        "field_scope_labels": _translation_workspace_draft_field_labels(),
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
        message = "Draft generation could not run because OpenAI configuration is missing."
    elif blocking_conditions:
        status = "failed"
        message = "Draft generation did not complete for this language."
    elif int((draft_result or {}).get("draft_blocked_count") or 0) or int(
        counts.get("product_identity_mismatch_count")
        or (draft_result or {}).get("product_identity_mismatch_count")
        or 0
    ):
        status = "needs review"
        message = "Draft preview has fields that may mention a different product."
    elif int(counts.get("draft_entry_count") or 0):
        status = "generated"
        message = "Draft preview is ready for review."
    elif draft_status == "no_missing_translations_found":
        status = "skipped"
        message = "No missing draft fields were found for this language."
    elif (draft_result or {}).get("success"):
        status = "skipped"
        message = "No new draft fields were needed for this language."
    else:
        status = "failed"
        message = "Draft generation did not complete for this language."

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
):
    has_requested_locale = bool(requested_locales)
    has_invalid_locale = bool(invalid_locales)
    if not has_product and not has_requested_locale and not has_invalid_locale:
        return "Select one product and choose at least one target language before generating drafts."
    if not has_product and has_invalid_locale and not has_requested_locale:
        return "Select one product and choose only supported target languages: Japanese, German, French, Spanish, or Italian."
    if not has_product:
        return "Select one product before generating drafts."
    if has_invalid_locale and not has_requested_locale:
        return "Choose only supported target languages: Japanese, German, French, Spanish, or Italian."
    if not has_requested_locale:
        return "Choose at least one target language."
    return "Draft generation could not start. Review the selections and try again."


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
        return "OpenAI draft generation failed. Try again after checking configuration."
    if failure_type == "openai_response_invalid":
        return "OpenAI returned an unexpected draft response."
    if failure_type == "shopify_read_query_failed":
        return "The read-only product translation lookup failed."
    if failure_type == "unexpected_error":
        return "Draft generation failed unexpectedly."
    reason_labels = {
        "blocked_invalid_product_id": "The selected product was not valid.",
        "blocked_unsupported_locale": "This target language is not supported.",
        "blocked_invalid_field": "The draft field selection was not valid.",
        "blocked_missing_shopify_installation": "Shopify installation is not configured for read-only lookup.",
        "blocked_shopify_read_query_failed": "The read-only product translation lookup failed.",
        "blocked_openai_draft_generation_failed": "OpenAI draft generation failed.",
        "draft_generation_failed": "Draft generation failed unexpectedly.",
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
                "Draft generation finished with issues. Shopify was not updated. Review each language below.",
            )
        return (
            "multi_locale_draft_completed",
            "Draft previews are ready for review. Shopify was not updated. Open each language below.",
        )
    if needs_configuration and needs_configuration == locale_count:
        return (
            "multi_locale_draft_needs_configuration",
            "Draft generation could not run because OpenAI configuration is missing. Shopify was not updated.",
        )
    if skipped and skipped == locale_count:
        return (
            "multi_locale_draft_skipped",
            "No missing draft fields were found for the selected languages. Shopify was not updated.",
        )
    return (
        "multi_locale_draft_failed",
        "Draft generation finished with issues. Shopify was not updated. Review each language below.",
    )


def _translation_workspace_draft_field_labels():
    labels = {
        "title": "product title",
        "body_html": "product description/body",
        "meta_title": "SEO title",
        "meta_description": "SEO description",
    }
    return [labels.get(field, field) for field in TRANSLATION_WORKSPACE_DRAFT_FIELDS]


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
            ("meta_title", "meta_description"),
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
            "technical_fields",
            "Other technical fields",
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
        "options": "Product options",
        "variants": "Variants",
        "important_metafields": "Important metafields",
        "technical_metafields": "Other technical fields",
    }
    return labels.get(area_key, _translation_editor_humanize_key(area_key))


def _translation_workspace_mvp_group_note(group_key: str) -> str:
    notes = {
        "product_basics": "Title and body HTML are draft-supported for local previews. Body HTML remains review-only for later approval steps.",
        "seo": "Meta title and meta description are draft-supported.",
        "options": "Option names or values are not drafted until Shopify row keys are mapped safely.",
        "variants": "Variant titles or labels are not drafted until Shopify row keys are mapped safely. SKU remains context only.",
        "important_metafields": "Important metafields are editor-only in this phase.",
        "technical_fields": "Other technical fields stay collapsed and out of the MVP draft package.",
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
            "label": "Generate draft package in Workbench",
            "status": "ready" if product_gid else "select_product_first",
        },
        {
            "label": "Review editor preview",
            "status": "ready" if source_data_loaded else "open_or_refresh_editor",
        },
        {
            "label": "Generate locked dry-run report",
            "status": (
                "ready_after_review"
                if candidate_count
                else ("draft_has_no_ready_candidates" if draft_ready else "generate_draft_first")
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
        ("draft_only", "Draft only"),
        ("seo", "SEO"),
        ("variants_options", "Variants/options"),
        ("metafields", "Metafields"),
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
        "Rows in this section are visible for review only; current draft generation does not cover them."
        if section_rows
        else "No rows in this section were returned by the current product translation data."
    )
    return {
        "area_key": section_key,
        "area_label": section_label,
        "group_label": "Additional sections",
        "coverage_status": coverage_status,
        "coverage_label": coverage_label,
        "support_status": "review_only",
        "support_label": "Review-only in editor",
        "field_keys": field_keys,
        "row_count": len(section_rows),
        "visible_row_count": visible_count,
        "notes": notes,
    }


def _translation_editor_draft_entries_by_key(draft_result: dict, locale: str):
    entries = {}
    for entry in draft_result.get("entries") or []:
        if not isinstance(entry, dict) or entry.get("locale") != locale:
            continue
        field_key = _translation_editor_normalize_field_key(
            entry.get("source_key") or entry.get("field")
        )
        if field_key:
            entries[field_key] = entry
    return entries


def _translation_editor_source_rows_by_key(result: dict):
    rows = {}
    for row in result.get("translatable_rows") or []:
        if not isinstance(row, dict):
            continue
        field_key = _translation_editor_normalize_field_key(row.get("key"))
        if field_key:
            rows[field_key] = row
    return rows


def _build_translation_editor_row(
    field_key: str,
    source_row: dict,
    draft_entry: dict,
    locale: str,
    source_identity_context: dict | None = None,
):
    field_key = _translation_editor_normalize_field_key(field_key)
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
            _draft_entry_blocking_reasons(draft_entry, seo_notes, quality_notes)
            if draft_entry
            else []
        )
        + validation_reasons
        + (["product_identity_mismatch"] if product_identity_mismatch else [])
    )
    needs_review = bool(
        draft_blocked
        or product_identity_mismatch
        or seo_notes
        or quality_notes
        or validation_reasons
        or blocking_reasons
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
        badges.append("GPT draft")
    if seo_notes:
        badges.append("SEO warning")
    if product_identity_mismatch:
        badges.append("wrong product")
    if draft_blocked:
        badges.append("blocked draft")
    if blocking_reasons:
        badges.append("blocked")
    if not target_value:
        badges.append("untranslated")
    char_limit = TRANSLATION_CONSOLE_EDITOR_SEO_LIMITS.get(field_key)
    target_chars = len(target_value)
    exceeds_limit = bool(char_limit and target_chars > char_limit)
    if exceeds_limit:
        badges.append("exceeds limit")
    section_key = _translation_editor_section_key(field_key)
    resource_type_label = _translation_editor_resource_type_label(field_key)
    resource_detail = _translation_editor_resource_detail(field_key, source_row, draft_entry)
    resource_note = _translation_editor_resource_note(field_key, source_row, draft_entry)
    has_html_preview = field_key == "body_html"
    return {
        "section_key": section_key,
        "field_key": field_key,
        "field_label": _translation_editor_field_label(field_key),
        "resource_type_label": resource_type_label,
        "resource_detail": resource_detail,
        "resource_note": resource_note,
        "resource_key": source_row.get("key") or draft_entry.get("source_key") or field_key,
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
            else ("GPT draft" if draft_value else "")
        ),
        "target_value_source_label": (
            ("Existing translation" if product_identity_mismatch else "Already translated")
            if existing_value
            else ("Draft only" if draft_value else "")
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
        "draft_only": "Draft only",
        "skipped": "Needs review",
        "untranslated": "Needs translation",
    }
    return labels.get(str(status or ""), _translation_editor_humanize_key(status))


def _translation_editor_badge_label(badge: str) -> str:
    labels = {
        "existing translation": "Already translated",
        "existing translation needs review": "Existing translation",
        "outdated": "Needs review",
        "GPT draft": "Draft only",
        "SEO warning": "Needs review",
        "wrong product": "Possible wrong product",
        "blocked draft": "Blocked draft",
        "blocked": "Needs review",
        "untranslated": "Needs translation",
        "exceeds limit": "Too long",
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
            "skipped",
        }
    if editor_filter == "seo":
        return row.get("section_key") == "seo"
    if editor_filter == "variants_options":
        return row.get("section_key") in {"options", "variants"}
    if editor_filter == "metafields":
        return row.get("section_key") in {"important_metafields", "technical_metafields"}
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
        "technical_metafields": "Technical / other field",
    }
    return labels.get(section_key, "Product field")


def _translation_editor_resource_detail(field_key: str, source_row: dict, draft_entry: dict) -> str:
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
    }:
        return False
    if "option" in key or "variant" in key:
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
    if variant_title:
        bits.append(f"Variant: {variant_title}")
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
    labels = {
        "ja": "Japanese",
        "de": "German",
        "fr": "French",
        "es": "Spanish",
        "it": "Italian",
    }
    return labels.get(locale, locale)


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
    quality_notes = _list_from_value(entry.get("quality_notes"))
    blocking_reasons = _draft_entry_blocking_reasons(entry, seo_notes, quality_notes)
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
        "blocking_reasons": ", ".join(reasons),
        "current_translation_present": current_translation_present,
        "outdated": outdated,
    }


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
        "blocking_conditions": draft_result.get("blocking_conditions") or [],
        "shopify_write_performed": draft_result.get("shopify_write_performed", False),
        "mutation_performed": draft_result.get("mutation_performed", False),
        "translations_register_called": draft_result.get(
            "translations_register_called", False
        ),
        "rollback_performed": draft_result.get("rollback_performed", False),
    }


def _attach_translation_console_draft_detail(draft_result: dict):
    if not isinstance(draft_result, dict):
        return
    draft_entries = []
    skipped_entries = []
    draft_entry_ids = {
        (entry.get("locale"), entry.get("field"))
        for entry in (draft_result.get("draft_entries") or [])
        if isinstance(entry, dict)
    }
    for entry in draft_result.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        normalized = _normalize_translation_console_draft_entry(entry)
        if (entry.get("locale"), entry.get("field")) in draft_entry_ids or entry.get(
            "draft_value"
        ):
            draft_entries.append(normalized)
        else:
            skipped_entries.append(normalized)

    summary = _translation_console_draft_detail_counts(
        draft_result, draft_entries, skipped_entries
    )
    draft_result["translation_console_detail"] = {
        "max_rows": TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS,
        "preview_chars": TRANSLATION_CONSOLE_DRAFT_PREVIEW_CHARS,
        "draft_entries": draft_entries[:TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS],
        "skipped_entries": skipped_entries[:TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS],
        "draft_entry_count": len(draft_entries),
        "skipped_entry_count": len(skipped_entries),
        "draft_entries_truncated": len(draft_entries)
        > TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS,
        "skipped_entries_truncated": len(skipped_entries)
        > TRANSLATION_CONSOLE_DRAFT_DETAIL_MAX_ROWS,
        "summary_counts": summary,
    }


def _normalize_translation_console_draft_entry(entry: dict):
    seo_notes = _list_from_value(entry.get("seo_notes"))
    quality_notes = _list_from_value(entry.get("quality_notes"))
    blocking_reasons = _draft_entry_blocking_reasons(entry, seo_notes, quality_notes)
    return {
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "resource_key": entry.get("source_key") or entry.get("field", ""),
        "source_value_preview": _preview_text(entry.get("source_value")),
        "proposed_translation_preview": _preview_text(entry.get("draft_value")),
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
        "seo_warning": ", ".join(seo_notes),
        "eligible_for_apply_plan": bool(entry.get("eligible_for_apply_plan")),
        "blocking_reasons": ", ".join(blocking_reasons),
        "skip_reason": entry.get("skip_reason", ""),
        "current_translation_present": bool(entry.get("existing_translation_present")),
        "outdated": entry.get("existing_translation_outdated"),
        "existing_translation_preview": _preview_text(
            entry.get("existing_translation_value") or entry.get("translation_value")
        ),
    }


def _translation_console_draft_detail_counts(
    draft_result: dict, draft_entries: list[dict], skipped_entries: list[dict]
):
    skipped_count = (
        int(draft_result.get("skipped_existing_translation_count") or 0)
        + int(draft_result.get("skipped_outdated_translation_count") or 0)
        + int(draft_result.get("skipped_source_empty_count") or 0)
    )
    return {
        "draft_entry_count": len(draft_entries),
        "skipped_entry_count": skipped_count or len(skipped_entries),
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
    reasons.extend(seo_notes)
    if entry.get("draft_blocked"):
        reasons.append("draft_blocked")
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
        if normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_DROP_CONTENT_TAGS:
            self._drop_stack.append(normalized_tag)
            return
        if self._drop_stack or normalized_tag not in TRANSLATION_CONSOLE_HTML_PREVIEW_ALLOWED_TAGS:
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
        if (
            self._drop_stack
            or normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_DROP_CONTENT_TAGS
            or normalized_tag not in TRANSLATION_CONSOLE_HTML_PREVIEW_ALLOWED_TAGS
        ):
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
        if (
            normalized_tag in TRANSLATION_CONSOLE_HTML_PREVIEW_ALLOWED_TAGS
            and normalized_tag not in TRANSLATION_CONSOLE_HTML_PREVIEW_VOID_TAGS
        ):
            self._parts.append(f"</{normalized_tag}>")

    def handle_data(self, data):
        if not self._drop_stack:
            self._parts.append(str(escape(data)))

    def get_html(self):
        return "".join(self._parts)


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
    return JsonResponse(task_result["result"])


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


