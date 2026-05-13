import json
import hmac
import os
import re
import secrets
import hashlib
import urllib.parse
import urllib.request
from datetime import datetime
from urllib.error import HTTPError, URLError

import requests
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import (
    HttpResponse,
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseRedirect,
    HttpResponseServerError,
    JsonResponse,
)
from django.shortcuts import render
from django.utils.html import escape

from .models import ShopifyInstallation, ShopifyOrder, ShopifyProduct, ShopifyOrderItem, ShopifySyncState
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
)
from .translation_apply_plan import (
    APPLY_PLAN_HTML_PATH,
    APPLY_PLAN_JSON_PATH,
    build_selected_product_translation_apply_plan,
)
from .translation_drafts import (
    DEFAULT_FIELDS as TRANSLATION_DRAFT_FIELDS,
    DEFAULT_TARGET_LOCALES as TRANSLATION_DRAFT_TARGET_LOCALES,
    generate_selected_product_missing_translation_draft_package,
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


SHOPIFY_OAUTH_STATE_SESSION_KEY = "shopify_oauth_states"
SHOPIFY_SHOP_DOMAIN_RE = re.compile(
    r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com$"
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
def translation_console(request):
    post_action = (request.POST.get("action") or "").strip() if request.method == "POST" else ""
    is_refresh_status_post = post_action == "refresh_status"
    is_locked_package_placeholder_post = post_action == "generate_locked_package_dry_run_placeholder"
    is_status_only_safe_action_post = (
        is_refresh_status_post or is_locked_package_placeholder_post
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
        or is_apply_plan_post
        or is_final_review_post
        or is_readiness_post
        or is_locked_execution_plan_post
        or is_locked_executor_post
        or is_real_write_executor_post
        or is_real_write_manual_action_package_post
        or is_status_only_safe_action_post
    )
    raw_search_text = request.POST.get("q", "") if is_post_action else request.GET.get("q", "")
    raw_locale = request.POST.get("locale", "ja") if is_post_action else request.GET.get("locale", "ja")
    search_text = (raw_search_text or "").strip()
    locale = ((raw_locale or "ja") or "ja").strip()
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
        "search_text": search_text,
    }
    error_message = ""
    draft_result = None
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
    workflow_product_id = (
        search_text
        if search_text.startswith("gid://shopify/Product/")
        else TRANSLATION_WORKFLOW_DEFAULT_PRODUCT_ID
    )

    if search_text and not is_status_only_safe_action_post:
        try:
            installation = ShopifyInstallation.objects.first()
            if installation is None:
                error_message = f"Shopify installation not found for {shop_domain}."
            elif (
                is_draft_post
                or is_apply_plan_post
                or is_final_review_post
                or is_readiness_post
                or is_locked_execution_plan_post
                or is_locked_executor_post
                or is_real_write_executor_post
                or is_real_write_manual_action_package_post
            ):
                selected_product_id = _resolve_translation_console_product_id(installation, search_text, locale)
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
                            summary={
                                "product_id": draft_result.get("product_id", ""),
                                "product_title": draft_result.get("product_title", ""),
                                "draft_entry_count": draft_result.get("draft_entry_count"),
                                "skipped_entry_count": draft_result.get("skipped_entry_count"),
                                "blocking_conditions": draft_result.get("blocking_conditions")
                                or [],
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
                result.update(fetch_translation_console_data(installation, search_text, locale))
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
    elif is_locked_package_placeholder_post:
        safe_action_result = _translation_console_safe_action_result(
            action=post_action,
            action_status="locked_package_dry_run_placeholder",
            message=(
                "Locked package generation from the Safe Actions panel is read-only "
                "and remains a placeholder in this phase."
            ),
            summary={
                "workflow_status": workflow_status.get("workflow_status"),
                "placeholder": True,
                "future_phase_required": True,
            },
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

    return render(
        request,
        "admin/shopify_sync/translation_console.html",
        {
            "title": "Shopify Product Translation Console",
            "search_text": search_text,
            "selected_locale": locale,
            "supported_locales": SUPPORTED_TRANSLATION_LOCALES,
            "shop_domain": shop_domain,
            "result": result,
            "workflow_status": workflow_status,
            "safe_action_result": safe_action_result,
            "error_message": error_message,
            "draft_result": draft_result,
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


