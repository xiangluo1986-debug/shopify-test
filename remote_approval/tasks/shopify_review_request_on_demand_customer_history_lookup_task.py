import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.error
import urllib.request
from html import escape
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

from backend.shopify_sync.review_request_history_ledger import write_customer_history_lookup_cache
from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_on_demand_customer_history_lookup"
COMMAND_LABEL = "shopify_review_request_on_demand_customer_history_lookup_read_only"
REPORT_DIR = LOG_DIR / "codex_runs"
REPORT_JSON_PATH = REPORT_DIR / "shopify_review_request_on_demand_customer_history_lookup.json"
REPORT_HTML_PATH = REPORT_DIR / "shopify_review_request_on_demand_customer_history_lookup.html"
SQLITE_DB_PATH = PROJECT_ROOT / "backend" / "db.sqlite3"

SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
DEFAULT_LOOKUP_ORDER = "#21687"
LOOKUP_ORDER_ENV = "SHOPIFY_REVIEW_REQUEST_LOOKUP_ORDER"
DOCKER_TIMEOUT_SECONDS = 240
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_ON_DEMAND_CUSTOMER_HISTORY_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_ON_DEMAND_CUSTOMER_HISTORY_JSON_END"
REQUIRED_HISTORY_SCOPES = ("read_orders", "read_all_orders")
READ_ALL_ORDERS_MISSING_MESSAGE = "Shopify token does not have read_all_orders. Reauthorize app before sending."
READ_ORDERS_MISSING_MESSAGE = "Shopify token does not have read_orders. Reauthorize app before sending."

TRUSTPILOT_KEYWORDS = (
    "1: trustpilot",
    "1: trustpoilt",
    "trustpilot",
    "trustpoilt",
    "truspilot",
    "trustpoit",
    "trust pilot",
    "trust poilt",
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"shpat_[A-Za-z0-9_]+|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"x-shopify-access-token\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"access[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"refresh[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"client[_\s-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"api[_\s-]?key\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"authorization\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"password\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}"
    r")"
)


def run_shopify_review_request_on_demand_customer_history_lookup_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    selected_order = _canonical_order_name(os.environ.get(LOOKUP_ORDER_ENV) or DEFAULT_LOOKUP_ORDER)
    if not selected_order:
        selected_order = DEFAULT_LOOKUP_ORDER

    lookup = _run_protected_lookup(selected_order)
    payload = _build_payload(
        selected_order=selected_order,
        lookup=lookup,
        duration_seconds=round(time.time() - started, 3),
    )
    payload = _apply_self_privacy_assertion(payload)
    payload = _persist_lookup_cache(payload)
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _run_protected_lookup(selected_order: str) -> dict:
    command = [
        "docker",
        "compose",
        "exec",
        "-T",
        "web",
        "python",
        "manage.py",
        "shell",
        "-c",
        _django_shell_script(selected_order),
    ]
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
            **_empty_lookup(),
            "failure_type": "timeout",
            "error_sanitized": f"Read-only customer history lookup timed out after {DOCKER_TIMEOUT_SECONDS} seconds.",
            "stdout_tail": _tail(_decode_bytes(exc.stdout or b"")),
            "stderr_tail": _tail(_decode_bytes(exc.stderr or b"")),
        }
    except FileNotFoundError as exc:
        return {**_empty_lookup(), "failure_type": "docker_command_not_found", "error_sanitized": _sanitize_text(str(exc))}
    except PermissionError as exc:
        return {**_empty_lookup(), "failure_type": "docker_permission_denied", "error_sanitized": _sanitize_text(str(exc))}

    stdout = _decode_bytes(completed.stdout)
    stderr = _decode_bytes(completed.stderr)
    parsed = _extract_payload(stdout)
    if not parsed:
        docker_failure = {
            **_empty_lookup(),
            "failure_type": "lookup_payload_missing",
            "error_sanitized": "Read-only customer history lookup did not return parseable JSON.",
            "exit_code": completed.returncode,
            "stdout_tail": _tail(stdout),
            "stderr_tail": _tail(stderr),
        }
        fallback = _run_host_sqlite_lookup(selected_order, docker_failure)
        if fallback.get("fallback_attempted") is True:
            return fallback
        return docker_failure
    parsed = {**_empty_lookup(), **parsed}
    parsed["exit_code"] = completed.returncode
    if completed.returncode != 0 and not parsed.get("error_sanitized"):
        parsed["error_sanitized"] = _sanitize_text(stderr or stdout or "Read-only customer history lookup failed.")
    parsed["stdout_tail"] = "" if parsed.get("success") else _tail(stdout)
    parsed["stderr_tail"] = "" if parsed.get("success") else _tail(stderr)
    return parsed


def _run_host_sqlite_lookup(selected_order: str, docker_failure: dict) -> dict:
    lookup = {
        **_empty_lookup(),
        "fallback_attempted": True,
        "fallback_source": "host_sqlite",
        "docker_failure_type": _safe_text(docker_failure.get("failure_type"), 120),
        "docker_error_sanitized": _safe_text(docker_failure.get("error_sanitized"), 500),
        "docker_stderr_tail": _safe_text(docker_failure.get("stderr_tail"), 800),
    }
    if not SQLITE_DB_PATH.exists():
        lookup["failure_type"] = "sqlite_db_missing"
        lookup["error_sanitized"] = "Local SQLite database was not found."
        return lookup

    try:
        connection = sqlite3.connect(SQLITE_DB_PATH)
        connection.row_factory = sqlite3.Row
        try:
            selected_order_row = _sqlite_selected_order(connection, selected_order)
            if not selected_order_row:
                lookup["lookup_status"] = "blocked_selected_order_not_found_locally"
                lookup["failure_type"] = "selected_order_not_found_locally"
                lookup["error_sanitized"] = "Selected order was not found in local ShopifyOrder data."
                return lookup
            lookup["local_order_found"] = True
            local_history_rows, local_method = _sqlite_local_customer_history(connection, selected_order_row)
            lookup["local_customer_history_count"] = len(_safe_order_names(row["order_name"] for row in local_history_rows))
            lookup["local_customer_history_order_names"] = _safe_order_names(
                row["order_name"] or row["order_number"] for row in local_history_rows
            )
            lookup["local_customer_history_match_method"] = local_method

            installation = _sqlite_installation(connection)
            if not installation:
                lookup["failure_type"] = "shopify_installation_missing"
                lookup["error_sanitized"] = "Shopify installation was not found in local SQLite data."
                return lookup
            lookup["shopify_installation_found"] = True
            installation_scope = str(installation["scope"] or "")
            lookup["configured_scope_source"] = "ShopifyInstallation.scope"
            lookup["configured_read_orders_scope_present"] = _scope_present(installation_scope, "read_orders")
            lookup["configured_read_all_orders_scope_present"] = _scope_present(installation_scope, "read_all_orders")
            access_token = str(installation["access_token"] or "")
            lookup["shopify_credentials_found"] = bool(access_token)
            if not access_token:
                lookup["failure_type"] = "missing_shopify_access_token"
                lookup["error_sanitized"] = "Shopify installation exists, but the access token is empty."
                return lookup

            shop = str(installation["shop"] or SHOP_DOMAIN)
            _host_verify_access_scopes(shop, access_token, lookup)
            if lookup.get("active_token_scope_verified") is not True:
                lookup["lookup_status"] = "blocked_customer_history_lookup_not_available"
                lookup["failure_type"] = "access_scope_verification_unavailable"
                lookup["error_sanitized"] = "Shopify token scopes could not be verified. Customer history needs live Shopify check before sending."
                lookup["reauthorization_required"] = True
                lookup["next_admin_action"] = "Verify Shopify access scopes from /admin/oauth/access_scopes.json before sending."
                return lookup
            if lookup.get("read_orders_scope_present") is not True:
                lookup["lookup_status"] = "blocked_shopify_history_permission_missing"
                lookup["failure_type"] = "read_orders_scope_missing"
                lookup["error_sanitized"] = READ_ORDERS_MISSING_MESSAGE
                lookup["reauthorization_required"] = True
                lookup["next_admin_action"] = "Reauthorize or reinstall the Shopify app with read_orders and read_all_orders before sending."
                return lookup
            if lookup.get("read_all_orders_scope_present") is not True:
                lookup["lookup_status"] = "blocked_shopify_history_permission_missing"
                lookup["failure_type"] = "read_all_orders_scope_missing"
                lookup["error_sanitized"] = READ_ALL_ORDERS_MISSING_MESSAGE
                lookup["reauthorization_required"] = True
                lookup["next_admin_action"] = "Reauthorize or reinstall the Shopify app, then save the new access token before sending."
                return lookup
            lookup["lifetime_history_scope_confirmed"] = True

            rest_base = f"https://{shop}/admin/api/{SHOPIFY_API_VERSION}"
            selected_shopify_order = _host_rest_selected_order(
                rest_base,
                access_token,
                selected_order,
                selected_order_row["shopify_order_id"],
                lookup,
            )
            if not selected_shopify_order:
                lookup["failure_type"] = "selected_order_shopify_read_failed"
                lookup["error_sanitized"] = "Selected Shopify order could not be read with available read-only helpers."
                return lookup
            lookup["shopify_selected_order_found"] = True

            graphql_endpoint = f"{rest_base}/graphql.json"
            customer_id = _host_customer_id_from_order(selected_shopify_order)
            selected_email = _host_selected_email_from_order(selected_shopify_order)
            lookup["shopify_customer_id_available"] = bool(customer_id)
            lookup["runtime_email_available"] = bool(selected_email)
            lookup["shopify_customer_identity_found"] = bool(customer_id or selected_email)
            if not (customer_id or selected_email):
                lookup["failure_type"] = "selected_order_customer_identity_missing"
                lookup["error_sanitized"] = "Selected Shopify order did not expose customer id or email for a safe history lookup."
                return lookup

            history_orders = []
            history_methods = []
            if customer_id:
                customer_orders = _host_rest_paginated_orders(
                    f"{rest_base}/customers/{customer_id}/orders.json",
                    access_token,
                    {
                        "status": "any",
                        "limit": 250,
                        "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
                    },
                    "host_sqlite_rest_customer_orders_by_customer_id",
                    lookup,
                )
                if customer_orders:
                    history_methods.append("host_sqlite_rest_customer_orders_by_customer_id")
                    history_orders.extend(customer_orders)
            if selected_email:
                email_orders = _host_rest_paginated_orders(
                    f"{rest_base}/orders.json",
                    access_token,
                    {
                        "status": "any",
                        "limit": 250,
                        "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
                        "email": selected_email,
                    },
                    "host_sqlite_rest_orders_by_email",
                    lookup,
                )
                exact_email_orders = [
                    order for order in email_orders if _host_selected_email_from_order(order) == selected_email
                ]
                if exact_email_orders:
                    history_methods.append("host_sqlite_rest_orders_by_email")
                    history_orders.extend(exact_email_orders)
            if customer_id:
                graphql_customer_orders = _host_graphql_history_orders(
                    graphql_endpoint,
                    access_token,
                    f"customer_id:{customer_id}",
                    "host_sqlite_graphql_orders_by_customer_id",
                    lookup,
                )
                exact_customer_orders = list(graphql_customer_orders)
                if exact_customer_orders:
                    history_methods.append("host_sqlite_graphql_orders_by_customer_id")
                    history_orders.extend(exact_customer_orders)
            if selected_email:
                graphql_email_orders = _host_graphql_history_orders(
                    graphql_endpoint,
                    access_token,
                    f"email:{selected_email}",
                    "host_sqlite_graphql_orders_by_email",
                    lookup,
                )
                exact_graphql_email_orders = [
                    order for order in graphql_email_orders if _host_selected_email_from_order(order) == selected_email
                ]
                if exact_graphql_email_orders:
                    history_methods.append("host_sqlite_graphql_orders_by_email")
                    history_orders.extend(exact_graphql_email_orders)

            history_orders = _dedupe_host_history_orders(history_orders)
            if history_methods:
                lookup["shopify_history_lookup_method"] = "+".join(history_methods)

            lookup["shopify_customer_history_count"] = len(_safe_order_names(_host_order_name(order) for order in history_orders))
            lookup["shopify_history_order_names"] = _safe_order_names(_host_order_name(order) for order in history_orders)
            if not history_orders:
                lookup["failure_type"] = "customer_history_query_returned_no_orders"
                lookup["error_sanitized"] = "Customer history lookup returned no orders; Review & Send must stay blocked."
                return lookup

            note_evidence = {}
            tag_evidence = {}
            for order in history_orders:
                if not note_evidence:
                    note_evidence = _host_detect_note_evidence(order, selected_order)
                if not tag_evidence:
                    tag_evidence = _host_detect_tag_evidence(order, selected_order)
                if note_evidence and tag_evidence:
                    break
            if note_evidence:
                lookup["trustpilot_note_evidence_found"] = True
                lookup["evidence_order_name"] = note_evidence["order_name"]
                lookup["safe_detected_keyword"] = note_evidence["safe_keyword"]
                lookup["evidence_source"] = "order_note"
            if tag_evidence:
                lookup["trustpilot_tag_evidence_found"] = True
                if not lookup["evidence_order_name"]:
                    lookup["evidence_order_name"] = tag_evidence["order_name"]
                    lookup["safe_detected_keyword"] = tag_evidence["safe_keyword"]
                    lookup["evidence_source"] = "order_tag"

            lookup["lookup_status"] = "customer_history_lookup_completed"
            lookup["success"] = True
            return lookup
        finally:
            connection.close()
    except Exception as exc:
        lookup["failure_type"] = "host_sqlite_lookup_exception"
        lookup["error_sanitized"] = _safe_text(exc, 500)
        return lookup


def _sqlite_selected_order(connection, selected_order: str):
    names, numbers, shopify_ids = _order_lookup_values(selected_order)
    clauses = []
    params = []
    if names:
        clauses.append("order_name IN (" + ",".join("?" for _ in names) + ")")
        params.extend(names)
    if numbers:
        clauses.append("order_number IN (" + ",".join("?" for _ in numbers) + ")")
        params.extend(numbers)
    if shopify_ids:
        clauses.append("CAST(shopify_order_id AS TEXT) IN (" + ",".join("?" for _ in shopify_ids) + ")")
        params.extend(shopify_ids)
    if not clauses:
        return None
    sql = (
        "SELECT * FROM shopify_sync_shopifyorder WHERE "
        + " OR ".join(clauses)
        + " ORDER BY updated_at DESC, id DESC LIMIT 1"
    )
    return connection.execute(sql, params).fetchone()


def _sqlite_local_customer_history(connection, order):
    email = _normalize_email(order["customer_email"])
    if email:
        return (
            connection.execute(
                "SELECT order_name, order_number FROM shopify_sync_shopifyorder "
                "WHERE lower(customer_email)=? ORDER BY order_created_at, id",
                [email],
            ).fetchall(),
            "customer_email",
        )
    customer_name = str(order["customer_name"] or "").strip()
    shipping_phone = re.sub(r"\D+", "", str(order["shipping_phone"] or ""))
    if customer_name and shipping_phone:
        return (
            connection.execute(
                "SELECT order_name, order_number FROM shopify_sync_shopifyorder "
                "WHERE lower(customer_name)=? AND shipping_phone LIKE ? ORDER BY order_created_at, id",
                [customer_name.lower(), f"%{shipping_phone[-6:]}"],
            ).fetchall(),
            "customer_name_shipping_phone",
        )
    shipping_name = str(order["shipping_name"] or "").strip()
    shipping_zip = str(order["shipping_zip"] or "").strip()
    if shipping_name and shipping_zip:
        return (
            connection.execute(
                "SELECT order_name, order_number FROM shopify_sync_shopifyorder "
                "WHERE lower(shipping_name)=? AND shipping_zip=? ORDER BY order_created_at, id",
                [shipping_name.lower(), shipping_zip],
            ).fetchall(),
            "shipping_name_postcode",
        )
    return [], "unavailable"


def _sqlite_installation(connection):
    return connection.execute(
        "SELECT shop, access_token, scope FROM shopify_sync_shopifyinstallation WHERE shop=? ORDER BY id DESC LIMIT 1",
        [SHOP_DOMAIN],
    ).fetchone() or connection.execute(
        "SELECT shop, access_token, scope FROM shopify_sync_shopifyinstallation ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _scope_present(scope_text, required_scope):
    scopes = {part.strip() for part in re.split(r"[\s,]+", str(scope_text or "")) if part.strip()}
    return required_scope in scopes


def _host_verify_access_scopes(shop, access_token, lookup):
    lookup["token_scope_source"] = "shopify_access_scopes_endpoint"
    lookup["active_token_scope_verified"] = False
    data = _host_shopify_get_json(
        f"https://{shop}/admin/oauth/access_scopes.json",
        access_token,
        {},
        "host_sqlite_access_scope_verification",
        lookup,
    )
    handles = {
        str(scope.get("handle") or "").strip()
        for scope in (data or {}).get("access_scopes", [])
        if isinstance(scope, dict) and str(scope.get("handle") or "").strip()
    }
    lookup["read_orders_scope_present"] = "read_orders" in handles
    lookup["read_all_orders_scope_present"] = "read_all_orders" in handles
    lookup["active_token_scope_verified"] = bool(handles)
    lookup["lifetime_history_scope_confirmed"] = lookup["read_all_orders_scope_present"] is True
    lookup["reauthorization_required"] = not all(scope in handles for scope in REQUIRED_HISTORY_SCOPES)
    if lookup["read_orders_scope_present"] and lookup["read_all_orders_scope_present"]:
        lookup["scope_verification_status"] = "active_token_scope_verified"
        lookup["customer_history_permission_status"] = "full_history_available"
        lookup["next_admin_action"] = "No reauthorization needed for Review Request customer history reads."
    elif handles:
        lookup["scope_verification_status"] = "read_all_orders_missing_reauthorization_required"
        lookup["customer_history_permission_status"] = "permission_missing"
        lookup["next_admin_action"] = "Reauthorize or reinstall the Shopify app, then save the new access token before sending."
    else:
        lookup["scope_verification_status"] = "access_scope_endpoint_unavailable"
        lookup["customer_history_permission_status"] = "permission_unverified"
        lookup["next_admin_action"] = (
            "Verify Shopify access scopes from /admin/oauth/access_scopes.json before sending."
        )


def _host_rest_selected_order(rest_base, access_token, selected_order, local_shopify_order_id, lookup):
    order_id = str(local_shopify_order_id or "").strip()
    if order_id.isdigit():
        data = _host_shopify_get_json(
            f"{rest_base}/orders/{order_id}.json",
            access_token,
            {"fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes"},
            "host_sqlite_rest_selected_order_by_id",
            lookup,
        )
        order = (data or {}).get("order") or {}
        if order:
            return order
    data = _host_shopify_get_json(
        f"{rest_base}/orders.json",
        access_token,
        {
            "status": "any",
            "limit": 10,
            "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
            "name": selected_order,
        },
        "host_sqlite_rest_selected_order_by_name",
        lookup,
    )
    orders = (data or {}).get("orders") or []
    return next((order for order in orders if _host_order_name(order) == selected_order), orders[0] if orders else {})


def _host_rest_paginated_orders(url, access_token, params, label, lookup):
    orders = []
    page_info = None
    seen = set()
    while True:
        current_params = {"limit": 250, "page_info": page_info} if page_info else dict(params)
        data, response = _host_shopify_get_json(
            url,
            access_token,
            current_params,
            label,
            lookup,
            include_response=True,
        )
        orders.extend((data or {}).get("orders") or [])
        next_page_info = _next_page_info(response.headers.get("Link", "") if response is not None else "")
        if not next_page_info or next_page_info in seen:
            break
        seen.add(next_page_info)
        page_info = next_page_info
    return orders


def _host_graphql_history_orders(endpoint, access_token, search_query, label, lookup):
    orders = []
    cursor = None
    while True:
        data = _host_graphql_request(
            endpoint,
            access_token,
            """
query CustomerHistory($first: Int!, $after: String, $query: String!) {
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        email
        createdAt
        tags
        note
      }
    }
  }
}
""",
            {"first": 100, "after": cursor, "query": search_query},
            label,
            lookup,
        )
        connection = (data or {}).get("orders") or {}
        edges = connection.get("edges") or []
        orders.extend((edge or {}).get("node") or {} for edge in edges)
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            break
        cursor = page_info.get("endCursor")
    return orders


def _host_graphql_request(endpoint, access_token, query, variables, label, lookup):
    lookup.setdefault("customer_history_lookup_methods_attempted", []).append(label)
    payload = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    response = None
    try:
        with urllib.request.urlopen(request, timeout=30) as opened:
            body = opened.read()
            response = _HostResponse(opened.status, opened.headers)
    except urllib.error.HTTPError as exc:
        body = exc.read()
        response = _HostResponse(exc.code, exc.headers)
    except urllib.error.URLError as exc:
        lookup["shopify_api_response_error_count"] = _int_or_zero(
            lookup.get("shopify_api_response_error_count")
        ) + 1
        lookup.setdefault("shopify_api_response_errors_sanitized", []).append(
            _safe_text(f"Shopify GraphQL request failed: {exc.reason}", 240)
        )
        return {}

    lookup["shopify_api_lookup_performed"] = True
    lookup["read_only_shopify_lookup_performed"] = True
    lookup["shopify_http_status"] = response.status_code if response is not None else 0
    if response is not None and response.status_code >= 400:
        lookup["shopify_api_response_error_count"] = _int_or_zero(
            lookup.get("shopify_api_response_error_count")
        ) + 1
        lookup.setdefault("shopify_api_response_errors_sanitized", []).append(
            f"Shopify GraphQL HTTP error {response.status_code}"
        )
        return {}
    try:
        parsed = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        lookup["shopify_api_response_error_count"] = _int_or_zero(
            lookup.get("shopify_api_response_error_count")
        ) + 1
        lookup.setdefault("shopify_api_response_errors_sanitized", []).append("Shopify GraphQL non-JSON response")
        return {}
    errors = parsed.get("errors") or []
    if errors:
        lookup["shopify_api_response_error_count"] = _int_or_zero(
            lookup.get("shopify_api_response_error_count")
        ) + len(errors)
        for error in errors[:5]:
            message = error.get("message") if isinstance(error, dict) else error
            lookup.setdefault("shopify_api_response_errors_sanitized", []).append(_safe_text(message, 240))
        return {}
    return parsed.get("data") or {}


def _host_shopify_get_json(url, access_token, params, label, lookup, include_response=False):
    headers = {
        "X-Shopify-Access-Token": access_token,
        "Content-Type": "application/json",
    }
    lookup.setdefault("customer_history_lookup_methods_attempted", []).append(label)
    response = None
    for attempt in range(4):
        request_url = url
        if params:
            request_url = url + "?" + urlencode(params)
        request = urllib.request.Request(request_url, headers=headers, method="GET")
        body = b""
        try:
            with urllib.request.urlopen(request, timeout=30) as opened:
                body = opened.read()
                response = _HostResponse(opened.status, opened.headers)
        except urllib.error.HTTPError as exc:
            body = exc.read()
            response = _HostResponse(exc.code, exc.headers)
        except urllib.error.URLError as exc:
            lookup["shopify_api_response_error_count"] = _int_or_zero(
                lookup.get("shopify_api_response_error_count")
            ) + 1
            lookup.setdefault("shopify_api_response_errors_sanitized", []).append(
                _safe_text(f"Shopify REST request failed: {exc.reason}", 240)
            )
            return ({}, response) if include_response else {}
        lookup["shopify_api_lookup_performed"] = True
        lookup["read_only_shopify_lookup_performed"] = True
        lookup["shopify_http_status"] = response.status_code
        if response.status_code == 429 or 500 <= response.status_code < 600:
            if attempt < 3:
                time.sleep(_retry_delay_seconds(response, attempt))
                continue
        if response.status_code >= 400:
            lookup["shopify_api_response_error_count"] = _int_or_zero(
                lookup.get("shopify_api_response_error_count")
            ) + 1
            lookup.setdefault("shopify_api_response_errors_sanitized", []).append(
                f"Shopify REST HTTP error {response.status_code}"
            )
            return ({}, response) if include_response else {}
        try:
            data = json.loads(body.decode("utf-8", errors="replace"))
        except ValueError:
            lookup["shopify_api_response_error_count"] = _int_or_zero(
                lookup.get("shopify_api_response_error_count")
            ) + 1
            lookup.setdefault("shopify_api_response_errors_sanitized", []).append("Shopify REST non-JSON response")
            return ({}, response) if include_response else {}
        return (data, response) if include_response else data
    return ({}, response) if include_response else {}


class _HostResponse:
    def __init__(self, status_code, headers):
        self.status_code = int(status_code or 0)
        self.headers = headers or {}


def _retry_delay_seconds(response, attempt):
    retry_after = response.headers.get("Retry-After") if response is not None else ""
    try:
        return min(max(float(retry_after), 0), 60)
    except (TypeError, ValueError):
        return min(2 * (2 ** attempt), 30)


def _next_page_info(link_header):
    if not link_header:
        return ""
    for part in str(link_header).split(","):
        if 'rel="next"' not in part and "rel=next" not in part:
            continue
        match = re.search(r"<([^>]+)>", part)
        if not match:
            continue
        page_info = parse_qs(urlparse(match.group(1)).query).get("page_info")
        if page_info:
            return page_info[0]
    return ""


def _host_customer_id_from_order(order):
    customer = (order or {}).get("customer") or {}
    raw = str(customer.get("id") or customer.get("admin_graphql_api_id") or "")
    tail = raw.rsplit("/", 1)[-1]
    return tail if tail.isdigit() else ""


def _host_selected_email_from_order(order):
    customer = (order or {}).get("customer") or {}
    for value in (
        (order or {}).get("email"),
        (order or {}).get("contact_email"),
        (order or {}).get("contactEmail"),
        customer.get("email"),
    ):
        email = _normalize_email(value)
        if email:
            return email
    return ""


def _host_order_name(order):
    return _canonical_order_name((order or {}).get("name") or (order or {}).get("order_name") or (order or {}).get("order_number"))


def _dedupe_host_history_orders(orders):
    deduped = []
    seen = set()
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        key = str(order.get("id") or order.get("admin_graphql_api_id") or _host_order_name(order) or "").strip()
        if not key:
            continue
        if key in seen:
            continue
        seen.add(key)
        deduped.append(order)
    return deduped


def _host_detect_note_evidence(order, selected_order):
    order_name = _host_order_name(order)
    if order_name == selected_order:
        return {}
    for field in ("note", "note_attributes", "shopify_note", "shopify_note_attributes"):
        for fragment in _note_fragments((order or {}).get(field)):
            keyword = _trustpilot_keyword(fragment)
            if keyword:
                return {"order_name": order_name, "safe_keyword": keyword}
    return {}


def _host_detect_tag_evidence(order, selected_order):
    order_name = _host_order_name(order)
    if order_name == selected_order:
        return {}
    for tag in _split_tags((order or {}).get("tags")):
        keyword = _trustpilot_keyword(tag)
        if keyword:
            return {"order_name": order_name, "safe_keyword": keyword}
    return {}


def _note_fragments(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [stripped[:2000]]
        return _note_fragments(parsed)
    if isinstance(value, dict):
        fragments = []
        for item in value.values():
            fragments.extend(_note_fragments(item))
        return fragments
    if isinstance(value, (list, tuple, set)):
        fragments = []
        for item in value:
            fragments.extend(_note_fragments(item))
        return fragments
    return [str(value)[:2000]]


def _split_tags(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []


def _trustpilot_keyword(value):
    compact = re.sub(r"[^a-z0-9]+", "", str(value or "").lower())
    if not compact:
        return ""
    for keyword in TRUSTPILOT_KEYWORDS:
        if re.sub(r"[^a-z0-9]+", "", keyword.lower()) in compact:
            return keyword
    return ""


def _normalize_email(value):
    text = str(value or "").strip().lower()
    return text if EMAIL_RE.fullmatch(text) else ""


def _order_lookup_values(order_name):
    text = _safe_text(order_name, 80).strip()
    canonical = _canonical_order_name(text)
    raw = text.lstrip("#")
    names = [item for item in (text, canonical, raw if raw.isdigit() else "") if item]
    numbers = [raw] if raw.isdigit() else []
    shopify_ids = [raw] if raw.isdigit() else []
    return list(dict.fromkeys(names)), numbers, shopify_ids


def _django_shell_script(selected_order: str) -> str:
    template = r'''
import json
import re
import requests
from django.db.models import Q
from shopify_sync.models import ShopifyInstallation, ShopifyOrder
from shopify_sync.sync_helpers import get_next_page_info_from_link_header, shopify_get

shop = __SHOP_LITERAL__
api_version = __API_VERSION_LITERAL__
target_order_name = __ORDER_LITERAL__
keywords = __KEYWORDS_LITERAL__

email_re = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
secret_re = re.compile(
    r"(?i)(shpat_[A-Za-z0-9_]+|ya29\.[A-Za-z0-9._-]+|bearer\s+[A-Za-z0-9._-]{8,}|"
    r"x-shopify-access-token|authorization|access[_\s-]?token|refresh[_\s-]?token|"
    r"client[_\s-]?secret|api[_\s-]?key|password|secret)"
)

result = {
    "success": False,
    "lookup_status": "blocked_not_started",
    "selected_order": target_order_name,
    "local_order_found": False,
    "local_customer_history_count": 0,
    "local_customer_history_order_names": [],
    "local_customer_history_match_method": "",
    "shopify_api_lookup_performed": False,
    "read_only_shopify_lookup_performed": False,
    "shopify_installation_found": False,
    "shopify_credentials_found": False,
    "shopify_selected_order_found": False,
    "shopify_customer_identity_found": False,
    "shopify_customer_id_available": False,
    "runtime_email_available": False,
    "raw_email_output": False,
    "raw_phone_output": False,
    "raw_address_output": False,
    "full_note_output": False,
    "shopify_customer_history_count": 0,
    "shopify_history_order_names": [],
    "shopify_history_lookup_method": "",
    "customer_history_lookup_methods_attempted": [],
    "configured_scope_source": "unavailable",
    "configured_read_orders_scope_present": False,
    "configured_read_all_orders_scope_present": False,
    "token_scope_source": "unavailable",
    "active_token_scope_verified": False,
    "read_orders_scope_present": False,
    "read_all_orders_scope_present": False,
    "lifetime_history_scope_confirmed": False,
    "reauthorization_required": True,
    "next_admin_action": "",
    "scope_verification_status": "scope_check_not_started",
    "customer_history_permission_status": "permission_unverified",
    "trustpilot_note_evidence_found": False,
    "trustpilot_tag_evidence_found": False,
    "evidence_order_name": "",
    "safe_detected_keyword": "",
    "evidence_source": "",
    "failure_type": "",
    "error_sanitized": "",
    "shopify_http_status": None,
    "shopify_api_response_error_count": 0,
    "shopify_api_response_errors_sanitized": [],
}

def sanitize(text):
    text = str(text or "")
    text = secret_re.sub("[redacted]", text)
    return email_re.sub("[masked-email]", text)[:600]

def canonical_order_name(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.startswith("#"):
        return text
    if text.isdigit():
        return "#" + text
    return text

def order_lookup_query(order_name):
    text = str(order_name or "").strip()
    raw = text.lstrip("#")
    names = {text, canonical_order_name(text)}
    numbers = set()
    shopify_ids = set()
    if raw.isdigit():
        names.add(raw)
        names.add("#" + raw)
        numbers.add(raw)
        shopify_ids.add(raw)
    query = Q(order_name__in=[item for item in names if item])
    if numbers:
        query |= Q(order_number__in=numbers)
    if shopify_ids:
        query |= Q(shopify_order_id__in=shopify_ids)
    return query

def safe_order_names(orders):
    names = []
    seen = set()
    for order in orders or []:
        name = canonical_order_name(order.get("name") or order.get("order_name") or order.get("order_number"))
        if not name or name in seen:
            continue
        seen.add(name)
        names.append(name[:80])
    return names

def dedupe_orders(orders):
    deduped = []
    seen = set()
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        key = str(order.get("id") or order.get("admin_graphql_api_id") or order.get("name") or order.get("order_number") or "").strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(order)
    return deduped

def normalize_email(value):
    text = str(value or "").strip().lower()
    return text if email_re.fullmatch(text) else ""

def scope_present(scope_text, required_scope):
    scopes = {part.strip() for part in re.split(r"[\s,]+", str(scope_text or "")) if part.strip()}
    return required_scope in scopes

def selected_email_from_order(order):
    customer = order.get("customer") or {}
    candidates = [
        order.get("email"),
        order.get("contact_email"),
        order.get("contactEmail"),
        customer.get("email"),
    ]
    for value in candidates:
        email = normalize_email(value)
        if email:
            return email
    return ""

def numeric_id_from_gid(value):
    text = str(value or "").strip()
    if text.isdigit():
        return text
    tail = text.rsplit("/", 1)[-1]
    return tail if tail.isdigit() else ""

def customer_id_from_order(order):
    customer = order.get("customer") or {}
    raw = customer.get("id") or customer.get("admin_graphql_api_id") or ""
    return numeric_id_from_gid(raw)

def compact_text(value):
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())

def keyword_in_text(value):
    compact = compact_text(value)
    if not compact:
        return ""
    for keyword in keywords:
        if compact_text(keyword) in compact:
            return str(keyword)[:80]
    return ""

def text_fragments(value):
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        fragments = []
        for item in value.values():
            fragments.extend(text_fragments(item))
        return fragments
    if isinstance(value, (list, tuple, set)):
        fragments = []
        for item in value:
            fragments.extend(text_fragments(item))
        return fragments
    text = str(value or "")
    return [text[:2000]] if text else []

def split_tags(value):
    if value in (None, ""):
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return []

def detect_note_evidence(order, target_name):
    order_name = canonical_order_name(order.get("name") or order.get("order_name") or order.get("order_number"))
    if order_name == target_name:
        return {}
    for field in ("note", "note_attributes", "shopify_note", "shopify_note_attributes"):
        for fragment in text_fragments(order.get(field)):
            keyword = keyword_in_text(fragment)
            if keyword:
                return {
                    "evidence_found": True,
                    "order_name": order_name,
                    "safe_keyword": keyword,
                    "source": "order_note",
                }
    return {}

def detect_tag_evidence(order, target_name):
    order_name = canonical_order_name(order.get("name") or order.get("order_name") or order.get("order_number"))
    if order_name == target_name:
        return {}
    for tag in split_tags(order.get("tags")):
        keyword = keyword_in_text(tag)
        if keyword:
            return {
                "evidence_found": True,
                "order_name": order_name,
                "safe_keyword": keyword,
                "source": "order_tag",
            }
    return {}

def local_customer_history(local_order):
    email = normalize_email(getattr(local_order, "customer_email", ""))
    name = str(getattr(local_order, "customer_name", "") or "").strip()
    shipping_name = str(getattr(local_order, "shipping_name", "") or "").strip()
    shipping_phone = re.sub(r"\D+", "", str(getattr(local_order, "shipping_phone", "") or ""))
    shipping_zip = str(getattr(local_order, "shipping_zip", "") or "").strip()
    shipping_address1 = str(getattr(local_order, "shipping_address1", "") or "").strip()
    query = None
    method = ""
    if email:
        query = Q(customer_email__iexact=email)
        method = "customer_email"
    elif name and shipping_phone:
        query = Q(customer_name__iexact=name, shipping_phone__icontains=shipping_phone[-6:])
        method = "customer_name_shipping_phone"
    elif shipping_name and shipping_zip and shipping_address1:
        query = Q(shipping_name__iexact=shipping_name, shipping_zip__iexact=shipping_zip)
        method = "shipping_name_postcode"
    if query is None:
        return [], "unavailable"
    rows = list(
        ShopifyOrder.objects.filter(query)
        .values("order_name", "order_number")
        .order_by("order_created_at", "id")[:5000]
    )
    return rows, method

def request_graphql(endpoint, headers, query, variables, label):
    result["customer_history_lookup_methods_attempted"].append(label)
    response = requests.post(endpoint, json={"query": query, "variables": variables}, headers=headers, timeout=30)
    result["shopify_api_lookup_performed"] = True
    result["read_only_shopify_lookup_performed"] = True
    result["shopify_http_status"] = response.status_code
    if response.status_code >= 400:
        result["shopify_api_response_error_count"] += 1
        result["shopify_api_response_errors_sanitized"].append("Shopify GraphQL HTTP error " + str(response.status_code))
        return {}
    try:
        data = response.json()
    except ValueError:
        result["shopify_api_response_error_count"] += 1
        result["shopify_api_response_errors_sanitized"].append("Shopify GraphQL non-JSON response")
        return {}
    errors = data.get("errors") or []
    if errors:
        result["shopify_api_response_error_count"] += len(errors)
        for error in errors[:5]:
            if isinstance(error, dict):
                result["shopify_api_response_errors_sanitized"].append(sanitize(error.get("message") or "GraphQL error"))
            else:
                result["shopify_api_response_errors_sanitized"].append(sanitize(error))
        return {}
    return data.get("data") or {}

def rest_get_json(url, access_token, params, label):
    result["customer_history_lookup_methods_attempted"].append(label)
    response = shopify_get(
        url,
        access_token,
        params=params,
        timeout=30,
        max_retries=3,
        request_context=label,
        stop_on_429=False,
    )
    result["shopify_api_lookup_performed"] = True
    result["read_only_shopify_lookup_performed"] = True
    result["shopify_http_status"] = response.status_code
    return response.json(), response

def verify_access_scopes(shop_domain, access_token):
    result["token_scope_source"] = "shopify_access_scopes_endpoint"
    result["customer_history_lookup_methods_attempted"].append("access_scope_verification")
    try:
        result["shopify_api_lookup_performed"] = True
        result["read_only_shopify_lookup_performed"] = True
        response = shopify_get(
            "https://" + shop_domain + "/admin/oauth/access_scopes.json",
            access_token,
            timeout=20,
            max_retries=2,
            request_context="review_request_access_scope_verification",
            stop_on_429=False,
        )
        result["shopify_http_status"] = response.status_code
        data = response.json()
    except Exception as exc:
        result["shopify_api_response_error_count"] += 1
        result["shopify_api_response_errors_sanitized"].append(sanitize(exc))
        result["scope_verification_status"] = "access_scope_endpoint_unavailable"
        result["customer_history_permission_status"] = "permission_unverified"
        result["next_admin_action"] = "Verify Shopify access scopes from /admin/oauth/access_scopes.json before sending."
        return set()
    handles = {
        str(scope.get("handle") or "").strip()
        for scope in data.get("access_scopes", [])
        if isinstance(scope, dict) and str(scope.get("handle") or "").strip()
    }
    result["active_token_scope_verified"] = bool(handles)
    result["read_orders_scope_present"] = "read_orders" in handles
    result["read_all_orders_scope_present"] = "read_all_orders" in handles
    result["lifetime_history_scope_confirmed"] = result["read_all_orders_scope_present"] is True
    result["reauthorization_required"] = not all(scope in handles for scope in __REQUIRED_HISTORY_SCOPES_LITERAL__)
    if result["read_orders_scope_present"] and result["read_all_orders_scope_present"]:
        result["scope_verification_status"] = "active_token_scope_verified"
        result["customer_history_permission_status"] = "full_history_available"
        result["next_admin_action"] = "No reauthorization needed for Review Request customer history reads."
    elif handles:
        result["scope_verification_status"] = "read_all_orders_missing_reauthorization_required"
        result["customer_history_permission_status"] = "permission_missing"
        result["next_admin_action"] = "Reauthorize or reinstall the Shopify app, then save the new access token before sending."
    else:
        result["scope_verification_status"] = "access_scope_endpoint_unavailable"
        result["customer_history_permission_status"] = "permission_unverified"
        result["next_admin_action"] = "Verify Shopify access scopes from /admin/oauth/access_scopes.json before sending."
    return handles

def rest_order_by_id(rest_base, access_token, order_id):
    if not str(order_id or "").isdigit():
        return {}
    try:
        data, _response = rest_get_json(
            rest_base + "/orders/" + str(order_id) + ".json",
            access_token,
            {
                "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
            },
            "rest_selected_order_by_local_shopify_order_id",
        )
        return data.get("order") or {}
    except Exception as exc:
        result["shopify_api_response_error_count"] += 1
        result["shopify_api_response_errors_sanitized"].append(sanitize(exc))
        return {}

def graphql_selected_order(endpoint, headers, order_name):
    data = request_graphql(
        endpoint,
        headers,
        """
query SelectedOrder($query: String!) {
  orders(first: 10, query: $query) {
    edges {
      node {
        id
        name
        email
        tags
        note
      }
    }
  }
}
""",
        {"query": "name:" + order_name},
        "graphql_selected_order_by_name",
    )
    edges = (((data.get("orders") or {}).get("edges")) or [])
    orders = [edge.get("node") or {} for edge in edges]
    return next((order for order in orders if order.get("name") == order_name), orders[0] if orders else {})

def rest_paginated_orders(url, access_token, params, label):
    orders = []
    page_info = None
    seen = set()
    while True:
        current_params = {"limit": 250, "page_info": page_info} if page_info else dict(params)
        try:
            data, response = rest_get_json(url, access_token, current_params, label)
        except Exception as exc:
            result["shopify_api_response_error_count"] += 1
            result["shopify_api_response_errors_sanitized"].append(sanitize(exc))
            break
        orders.extend(data.get("orders") or [])
        next_page_info = get_next_page_info_from_link_header(response.headers.get("Link", ""))
        if not next_page_info or next_page_info in seen:
            break
        seen.add(next_page_info)
        page_info = next_page_info
    return orders

def graphql_history_orders(endpoint, headers, search_query, label):
    orders = []
    cursor = None
    while True:
        data = request_graphql(
            endpoint,
            headers,
            """
query CustomerHistory($first: Int!, $after: String, $query: String!) {
  orders(first: $first, after: $after, query: $query, sortKey: CREATED_AT) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        name
        email
        createdAt
        tags
        note
      }
    }
  }
}
""",
            {"first": 100, "after": cursor, "query": search_query},
            label,
        )
        connection = data.get("orders") or {}
        edges = connection.get("edges") or []
        orders.extend(edge.get("node") or {} for edge in edges)
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            break
        cursor = page_info.get("endCursor")
    return orders

try:
    local_order = (
        ShopifyOrder.objects.filter(order_lookup_query(target_order_name))
        .order_by("-updated_at", "-id")
        .first()
    )
    if not local_order:
        result["lookup_status"] = "blocked_selected_order_not_found_locally"
        result["failure_type"] = "selected_order_not_found_locally"
        result["error_sanitized"] = "Selected order was not found in local ShopifyOrder data."
        print("__JSON_BEGIN__")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        print("__JSON_END__")
        raise SystemExit(0)
    result["local_order_found"] = True
    local_rows, local_method = local_customer_history(local_order)
    result["local_customer_history_count"] = len(safe_order_names(local_rows))
    result["local_customer_history_order_names"] = safe_order_names(local_rows)
    result["local_customer_history_match_method"] = local_method

    installation = ShopifyInstallation.objects.get(shop=shop)
    result["shopify_installation_found"] = True
    installation_scope = str(getattr(installation, "scope", "") or "")
    result["configured_scope_source"] = "ShopifyInstallation.scope"
    result["configured_read_orders_scope_present"] = scope_present(installation_scope, "read_orders")
    result["configured_read_all_orders_scope_present"] = scope_present(installation_scope, "read_all_orders")
    access_token = getattr(installation, "access_" + "token")
    result["shopify_credentials_found"] = bool(access_token)
    if not access_token:
        result["lookup_status"] = "blocked_customer_history_lookup_not_available"
        result["failure_type"] = "missing_shopify_access_token"
        result["error_sanitized"] = "Shopify installation exists, but the access token is empty."
        print("__JSON_BEGIN__")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        print("__JSON_END__")
        raise SystemExit(0)

    verify_access_scopes(installation.shop, access_token)
    if result["active_token_scope_verified"] is not True:
        result["lookup_status"] = "blocked_customer_history_lookup_not_available"
        result["failure_type"] = "access_scope_verification_unavailable"
        result["error_sanitized"] = "Shopify token scopes could not be verified. Customer history needs live Shopify check before sending."
        result["reauthorization_required"] = True
        result["next_admin_action"] = "Verify Shopify access scopes from /admin/oauth/access_scopes.json before sending."
        print("__JSON_BEGIN__")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        print("__JSON_END__")
        raise SystemExit(0)
    if result["read_orders_scope_present"] is not True:
        result["lookup_status"] = "blocked_shopify_history_permission_missing"
        result["failure_type"] = "read_orders_scope_missing"
        result["error_sanitized"] = __READ_ORDERS_MISSING_MESSAGE_LITERAL__
        result["reauthorization_required"] = True
        result["next_admin_action"] = "Reauthorize or reinstall the Shopify app with read_orders and read_all_orders before sending."
        print("__JSON_BEGIN__")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        print("__JSON_END__")
        raise SystemExit(0)
    if result["read_all_orders_scope_present"] is not True:
        result["lookup_status"] = "blocked_shopify_history_permission_missing"
        result["failure_type"] = "read_all_orders_scope_missing"
        result["error_sanitized"] = __READ_ALL_ORDERS_MISSING_MESSAGE_LITERAL__
        result["reauthorization_required"] = True
        result["next_admin_action"] = "Reauthorize or reinstall the Shopify app, then save the new access token before sending."
        print("__JSON_BEGIN__")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        print("__JSON_END__")
        raise SystemExit(0)

    rest_base = "https://" + installation.shop + "/admin/api/" + api_version
    graphql_endpoint = rest_base + "/graphql.json"
    headers = {"X-Shopify-" + "Access-Token": access_token, "Content-Type": "application/json"}
    selected_order = rest_order_by_id(rest_base, access_token, getattr(local_order, "shopify_order_id", ""))
    if not selected_order:
        selected_order = graphql_selected_order(graphql_endpoint, headers, target_order_name)
    if not selected_order:
        result["lookup_status"] = "blocked_customer_history_lookup_not_available"
        result["failure_type"] = "selected_order_shopify_read_failed"
        result["error_sanitized"] = "Selected Shopify order could not be read with available read-only helpers."
        print("__JSON_BEGIN__")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        print("__JSON_END__")
        raise SystemExit(0)

    result["shopify_selected_order_found"] = True
    customer_id = customer_id_from_order(selected_order)
    selected_email = selected_email_from_order(selected_order)
    result["shopify_customer_id_available"] = bool(customer_id)
    result["runtime_email_available"] = bool(selected_email)
    result["shopify_customer_identity_found"] = bool(customer_id or selected_email)
    if not (customer_id or selected_email):
        result["lookup_status"] = "blocked_customer_history_lookup_not_available"
        result["failure_type"] = "selected_order_customer_identity_missing"
        result["error_sanitized"] = "Selected Shopify order did not expose customer id or email for a safe history lookup."
        print("__JSON_BEGIN__")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        print("__JSON_END__")
        raise SystemExit(0)

    history_orders = []
    history_methods = []
    if customer_id:
        customer_orders = rest_paginated_orders(
            rest_base + "/customers/" + customer_id + "/orders.json",
            access_token,
            {
                "status": "any",
                "limit": 250,
                "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
            },
            "rest_customer_orders_by_customer_id",
        )
        if customer_orders:
            history_methods.append("rest_customer_orders_by_customer_id")
            history_orders.extend(customer_orders)

    if selected_email:
        email_orders = rest_paginated_orders(
            rest_base + "/orders.json",
            access_token,
            {
                "status": "any",
                "limit": 250,
                "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
                "email": selected_email,
            },
            "rest_orders_by_email",
        )
        exact_email_orders = [order for order in email_orders if selected_email_from_order(order) == selected_email]
        if exact_email_orders:
            history_methods.append("rest_orders_by_email")
            history_orders.extend(exact_email_orders)

    if customer_id:
        graphql_orders = graphql_history_orders(
            graphql_endpoint,
            headers,
            "customer_id:" + customer_id,
            "graphql_orders_by_customer_id",
        )
        exact_graphql_customer_orders = list(graphql_orders)
        if exact_graphql_customer_orders:
            history_methods.append("graphql_orders_by_customer_id")
            history_orders.extend(exact_graphql_customer_orders)

    if selected_email:
        graphql_orders = graphql_history_orders(
            graphql_endpoint,
            headers,
            "email:" + selected_email,
            "graphql_orders_by_email",
        )
        exact_graphql_email_orders = [
            order for order in graphql_orders if selected_email_from_order(order) == selected_email
        ]
        if exact_graphql_email_orders:
            history_methods.append("graphql_orders_by_email")
            history_orders.extend(exact_graphql_email_orders)

    history_orders = dedupe_orders(history_orders)
    if history_methods:
        result["shopify_history_lookup_method"] = "+".join(history_methods)

    result["shopify_customer_history_count"] = len(safe_order_names(history_orders))
    result["shopify_history_order_names"] = safe_order_names(history_orders)
    if not history_orders:
        result["lookup_status"] = "blocked_customer_history_lookup_not_available"
        result["failure_type"] = "customer_history_query_returned_no_orders"
        result["error_sanitized"] = "Customer history lookup returned no orders; Review & Send must stay blocked."
        print("__JSON_BEGIN__")
        print(json.dumps(result, ensure_ascii=True, sort_keys=True))
        print("__JSON_END__")
        raise SystemExit(0)

    note_evidence = {}
    tag_evidence = {}
    for order in history_orders:
        if not note_evidence:
            note_evidence = detect_note_evidence(order, target_order_name)
        if not tag_evidence:
            tag_evidence = detect_tag_evidence(order, target_order_name)
        if note_evidence and tag_evidence:
            break
    if note_evidence:
        result["trustpilot_note_evidence_found"] = True
        result["evidence_order_name"] = note_evidence.get("order_name", "")
        result["safe_detected_keyword"] = note_evidence.get("safe_keyword", "")
        result["evidence_source"] = note_evidence.get("source", "")
    if tag_evidence:
        result["trustpilot_tag_evidence_found"] = True
        if not result["evidence_order_name"]:
            result["evidence_order_name"] = tag_evidence.get("order_name", "")
            result["safe_detected_keyword"] = tag_evidence.get("safe_keyword", "")
            result["evidence_source"] = tag_evidence.get("source", "")

    result["lookup_status"] = "customer_history_lookup_completed"
    result["success"] = True
    print("__JSON_BEGIN__")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    print("__JSON_END__")
    raise SystemExit(0)
except Exception as exc:
    result["lookup_status"] = "blocked_customer_history_lookup_not_available"
    result["failure_type"] = "customer_history_lookup_exception"
    result["error_sanitized"] = sanitize(exc)
    print("__JSON_BEGIN__")
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    print("__JSON_END__")
    raise SystemExit(0)
'''
    script = template.replace("__SHOP_LITERAL__", json.dumps(SHOP_DOMAIN))
    script = script.replace("__API_VERSION_LITERAL__", json.dumps(SHOPIFY_API_VERSION))
    script = script.replace("__ORDER_LITERAL__", json.dumps(selected_order))
    script = script.replace("__KEYWORDS_LITERAL__", json.dumps(list(TRUSTPILOT_KEYWORDS)))
    script = script.replace("__REQUIRED_HISTORY_SCOPES_LITERAL__", json.dumps(list(REQUIRED_HISTORY_SCOPES)))
    script = script.replace("__READ_ALL_ORDERS_MISSING_MESSAGE_LITERAL__", json.dumps(READ_ALL_ORDERS_MISSING_MESSAGE))
    script = script.replace("__READ_ORDERS_MISSING_MESSAGE_LITERAL__", json.dumps(READ_ORDERS_MISSING_MESSAGE))
    script = script.replace("__JSON_BEGIN__", JSON_BEGIN)
    script = script.replace("__JSON_END__", JSON_END)
    return script


def _build_payload(selected_order: str, lookup: dict, duration_seconds: float) -> dict:
    lookup_status = _safe_text(lookup.get("lookup_status") or "blocked_customer_history_lookup_not_available", 120)
    completed = lookup_status == "customer_history_lookup_completed"
    note_evidence = lookup.get("trustpilot_note_evidence_found") is True
    tag_evidence = lookup.get("trustpilot_tag_evidence_found") is True
    customer_count = _int_or_zero(lookup.get("shopify_customer_history_count"))
    lifetime_history_scope_confirmed = lookup.get("lifetime_history_scope_confirmed") is True
    shopify_api_lookup_performed = lookup.get("shopify_api_lookup_performed") is True
    read_all_orders_scope_present = lookup.get("read_all_orders_scope_present") is True
    full_history_confirmed = bool(
        completed
        and lifetime_history_scope_confirmed
        and read_all_orders_scope_present
        and shopify_api_lookup_performed
        and customer_count > 0
    )
    evidence_order = _canonical_order_name(lookup.get("evidence_order_name"))
    safe_keyword = _safe_text(lookup.get("safe_detected_keyword"), 80)
    blocking_reason = ""
    if lookup.get("failure_type") == "read_all_orders_scope_missing":
        blocking_reason = READ_ALL_ORDERS_MISSING_MESSAGE
    elif lookup.get("failure_type") == "read_orders_scope_missing":
        blocking_reason = READ_ORDERS_MISSING_MESSAGE
    elif not completed:
        blocking_reason = "Customer history needs live Shopify check before sending."
    elif note_evidence:
        blocking_reason = f"Previous Trustpilot note found on historical order {evidence_order or 'another order'}."
    elif tag_evidence:
        blocking_reason = f"Previous Trustpilot tag found on historical order {evidence_order or 'another order'}."
    elif not full_history_confirmed:
        blocking_reason = "Customer history could not be fully verified."
    elif customer_count <= 1:
        blocking_reason = "Live Shopify customer history does not confirm a repeat customer."

    should_block = bool(blocking_reason)
    final_recommendation = "block_review_send" if should_block else "allow_review_send"
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.32E",
        "mode": "dry-run-read-only-on-demand-customer-history-lookup",
        "command_label": COMMAND_LABEL,
        "lookup_status": lookup_status,
        "success": bool(completed),
        "selected_order": selected_order,
        "lookup_order_env_var": LOOKUP_ORDER_ENV,
        "local_order_found": lookup.get("local_order_found") is True,
        "local_customer_history_count": _int_or_zero(lookup.get("local_customer_history_count")),
        "local_customer_history_order_names": _safe_order_names(lookup.get("local_customer_history_order_names") or []),
        "local_customer_history_match_method": _safe_text(lookup.get("local_customer_history_match_method"), 120),
        "shopify_api_lookup_performed": shopify_api_lookup_performed,
        "read_only_shopify_lookup_performed": lookup.get("read_only_shopify_lookup_performed") is True,
        "shopify_selected_order_found": lookup.get("shopify_selected_order_found") is True,
        "shopify_customer_identity_found": lookup.get("shopify_customer_identity_found") is True,
        "shopify_customer_id_available": lookup.get("shopify_customer_id_available") is True,
        "runtime_email_available": lookup.get("runtime_email_available") is True,
        "configured_scope_source": _safe_text(lookup.get("configured_scope_source"), 120),
        "configured_read_orders_scope_present": lookup.get("configured_read_orders_scope_present") is True,
        "configured_read_all_orders_scope_present": lookup.get("configured_read_all_orders_scope_present") is True,
        "token_scope_source": _safe_text(lookup.get("token_scope_source"), 120) or "unavailable",
        "active_token_scope_verified": lookup.get("active_token_scope_verified") is True,
        "read_orders_scope_present": lookup.get("read_orders_scope_present") is True,
        "read_all_orders_scope_present": read_all_orders_scope_present,
        "lifetime_history_scope_confirmed": lifetime_history_scope_confirmed,
        "full_history_confirmed": full_history_confirmed,
        "full_history_unavailable_reason": ""
        if full_history_confirmed
        else _safe_text(blocking_reason or "Customer history could not be fully verified.", 300),
        "reauthorization_required": lookup.get("reauthorization_required") is True,
        "next_admin_action": _safe_text(lookup.get("next_admin_action"), 400),
        "scope_verification_status": _safe_text(lookup.get("scope_verification_status"), 120),
        "customer_history_permission_status": _customer_history_permission_status(lookup, completed),
        "shopify_customer_history_count": customer_count,
        "historical_order_names": _safe_order_names(lookup.get("shopify_history_order_names") or []),
        "shopify_history_order_names": _safe_order_names(lookup.get("shopify_history_order_names") or []),
        "shopify_history_lookup_method": _safe_text(lookup.get("shopify_history_lookup_method"), 120),
        "customer_history_lookup_methods_attempted": [
            _safe_text(item, 120) for item in (lookup.get("customer_history_lookup_methods_attempted") or [])
        ],
        "trustpilot_note_evidence_found": note_evidence,
        "trustpilot_tag_evidence_found": tag_evidence,
        "evidence_order_name": evidence_order,
        "safe_detected_keyword": safe_keyword,
        "evidence_source": _safe_text(lookup.get("evidence_source"), 80),
        "full_note_output": False,
        "raw_email_output": False,
        "raw_phone_output": False,
        "raw_address_output": False,
        "final_recommendation": final_recommendation,
        "should_block_review_send": should_block,
        "blocking_reason": blocking_reason,
        "report_json_path": str(REPORT_JSON_PATH),
        "report_html_path": str(REPORT_HTML_PATH),
        "json_on_demand_customer_history_lookup_path": str(REPORT_JSON_PATH),
        "html_on_demand_customer_history_lookup_path": str(REPORT_HTML_PATH),
        "shop_domain": SHOP_DOMAIN,
        "shopify_api_version": SHOPIFY_API_VERSION,
        "shopify_installation_found": lookup.get("shopify_installation_found") is True,
        "shopify_credentials_found": lookup.get("shopify_credentials_found") is True,
        "shopify_http_status": lookup.get("shopify_http_status"),
        "shopify_api_response_error_count": _int_or_zero(lookup.get("shopify_api_response_error_count")),
        "shopify_api_response_errors_sanitized": [
            _safe_text(item, 300) for item in (lookup.get("shopify_api_response_errors_sanitized") or [])[:10]
        ],
        "failure_type": _safe_text(lookup.get("failure_type"), 120),
        "error_sanitized": _safe_text(lookup.get("error_sanitized"), 500),
        "stdout_tail": _safe_text(lookup.get("stdout_tail"), 800),
        "stderr_tail": _safe_text(lookup.get("stderr_tail"), 800),
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "translations_register_called": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "privacy_assertion_passed": True,
        "raw_email_leak_risk_detected": False,
        "detected_issue_summary": _issue_summary(
            selected_order=selected_order,
            lookup_status=lookup_status,
            customer_count=customer_count,
            note_evidence=note_evidence,
            tag_evidence=tag_evidence,
            final_recommendation=final_recommendation,
        ),
        "duration_seconds": duration_seconds,
    }
    return payload


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_on_demand_customer_history_lookup_path": str(json_path),
        "html_on_demand_customer_history_lookup_path": str(html_path),
        "lookup_status": payload["lookup_status"],
        "selected_order": payload["selected_order"],
        "local_order_found": payload["local_order_found"],
        "local_customer_history_count": payload["local_customer_history_count"],
        "shopify_api_lookup_performed": payload["shopify_api_lookup_performed"],
        "shopify_customer_history_count": payload["shopify_customer_history_count"],
        "shopify_history_order_names": payload["shopify_history_order_names"],
        "read_orders_scope_present": payload["read_orders_scope_present"],
        "read_all_orders_scope_present": payload["read_all_orders_scope_present"],
        "lifetime_history_scope_confirmed": payload["lifetime_history_scope_confirmed"],
        "token_scope_source": payload["token_scope_source"],
        "reauthorization_required": payload["reauthorization_required"],
        "next_admin_action": payload["next_admin_action"],
        "customer_history_permission_status": payload["customer_history_permission_status"],
        "trustpilot_note_evidence_found": payload["trustpilot_note_evidence_found"],
        "trustpilot_tag_evidence_found": payload["trustpilot_tag_evidence_found"],
        "evidence_order_name": payload["evidence_order_name"],
        "safe_detected_keyword": payload["safe_detected_keyword"],
        "final_recommendation": payload["final_recommendation"],
        "should_block_review_send": payload["should_block_review_send"],
        "blocking_reason": payload["blocking_reason"],
        "lookup_cache_saved": payload.get("lookup_cache_saved") is True,
        "lookup_cache_path": payload.get("lookup_cache_path", ""),
        "lookup_cache_write_error_sanitized": payload.get("lookup_cache_write_error_sanitized", ""),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "raw_email_output": False,
        "full_note_output": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _write_json_report(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _persist_lookup_cache(payload: dict) -> dict:
    try:
        cache_path = write_customer_history_lookup_cache(LOG_DIR, payload)
    except (OSError, ValueError) as exc:
        payload["lookup_cache_saved"] = False
        payload["lookup_cache_path"] = ""
        payload["lookup_cache_write_error_sanitized"] = _safe_text(exc, 300)
        return payload
    payload["lookup_cache_saved"] = cache_path is not None
    payload["lookup_cache_path"] = str(cache_path) if cache_path else ""
    payload["lookup_cache_write_error_sanitized"] = ""
    return payload


def _render_html_report(payload: dict) -> str:
    history_names = ", ".join(payload["shopify_history_order_names"]) or "-"
    local_names = ", ".join(payload["local_customer_history_order_names"]) or "-"
    methods = ", ".join(payload["customer_history_lookup_methods_attempted"]) or "-"
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(payload.get(key)))}</td></tr>"
        for key in (
            "shopify_api_lookup_performed",
            "shopify_write_performed",
            "mutation_performed",
            "tags_add_performed",
            "tags_remove_performed",
            "gmail_api_call_performed",
            "email_sent",
            "raw_email_output",
            "full_note_output",
            "lookup_cache_saved",
            "all_new_actions_no_write_confirmed",
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>On-demand Shopify Customer History Lookup</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; width: 280px; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
    .ok {{ border-left: 4px solid #15803d; background: #f0fdf4; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>On-demand Shopify Customer History Lookup</h1>
  <p class="warning">Read-only lookup. No Gmail send, no Shopify write, no tag mutation, no external review API call, no raw email, and no full note output.</p>
  <p>Status: <strong>{escape(payload["lookup_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order"])}</code></p>
  <p>Final recommendation: <strong>{escape(payload["final_recommendation"])}</strong></p>
  <p>Blocking reason: {escape(payload["blocking_reason"] or "-")}</p>
  <table>
    <tbody>
      <tr><th>Local order found</th><td>{escape(str(payload["local_order_found"]))}</td></tr>
      <tr><th>Local customer history count</th><td>{escape(str(payload["local_customer_history_count"]))}</td></tr>
      <tr><th>Local order names</th><td>{escape(local_names)}</td></tr>
      <tr><th>Shopify live lookup performed</th><td>{escape(str(payload["shopify_api_lookup_performed"]))}</td></tr>
      <tr><th>read_orders scope present</th><td>{escape(str(payload["read_orders_scope_present"]))}</td></tr>
      <tr><th>read_all_orders scope present</th><td>{escape(str(payload["read_all_orders_scope_present"]))}</td></tr>
      <tr><th>Customer history permission status</th><td>{escape(payload["customer_history_permission_status"])}</td></tr>
      <tr><th>Shopify customer history count</th><td>{escape(str(payload["shopify_customer_history_count"]))}</td></tr>
      <tr><th>Shopify history order names</th><td>{escape(history_names)}</td></tr>
      <tr><th>Lookup methods attempted</th><td>{escape(methods)}</td></tr>
      <tr><th>Trustpilot note evidence found</th><td>{escape(str(payload["trustpilot_note_evidence_found"]))}</td></tr>
      <tr><th>Trustpilot tag evidence found</th><td>{escape(str(payload["trustpilot_tag_evidence_found"]))}</td></tr>
      <tr><th>Evidence order</th><td>{escape(payload["evidence_order_name"] or "-")}</td></tr>
      <tr><th>Safe keyword</th><td>{escape(payload["safe_detected_keyword"] or "-")}</td></tr>
    </tbody>
  </table>
  <h2>Safety</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.31D on-demand customer history lookup finished.\n"
        f"Lookup status: {payload.get('lookup_status')}\n"
        f"Selected order: {payload.get('selected_order')}\n"
        f"Local history count: {payload.get('local_customer_history_count')}\n"
        f"Shopify live lookup performed: {payload.get('shopify_api_lookup_performed')}\n"
        f"read_orders present: {payload.get('read_orders_scope_present')}\n"
        f"read_all_orders present: {payload.get('read_all_orders_scope_present')}\n"
        f"Customer history permission status: {payload.get('customer_history_permission_status')}\n"
        f"Shopify customer history count: {payload.get('shopify_customer_history_count')}\n"
        f"Trustpilot note evidence found: {payload.get('trustpilot_note_evidence_found')}\n"
        f"Trustpilot tag evidence found: {payload.get('trustpilot_tag_evidence_found')}\n"
        f"Evidence order: {payload.get('evidence_order_name') or '-'}\n"
        f"Safe keyword: {payload.get('safe_detected_keyword') or '-'}\n"
        f"Final recommendation: {payload.get('final_recommendation')}\n"
        f"Should block Review & Send: {payload.get('should_block_review_send')}\n"
        f"Blocking reason: {payload.get('blocking_reason') or '-'}\n"
        f"Lookup cache saved: {payload.get('lookup_cache_saved')}\n"
        "Safety: no Shopify write, no tag mutation, no Gmail API/send, no raw email, no full note output.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _extract_payload(stdout: str) -> dict:
    if JSON_BEGIN not in stdout or JSON_END not in stdout:
        return {}
    fragment = stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0].strip()
    try:
        data = json.loads(fragment)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _empty_lookup() -> dict:
    return {
        "success": False,
        "lookup_status": "blocked_customer_history_lookup_not_available",
        "selected_order": "",
        "local_order_found": False,
        "local_customer_history_count": 0,
        "local_customer_history_order_names": [],
        "shopify_api_lookup_performed": False,
        "read_only_shopify_lookup_performed": False,
        "shopify_customer_history_count": 0,
        "shopify_history_order_names": [],
        "configured_scope_source": "unavailable",
        "configured_read_orders_scope_present": False,
        "configured_read_all_orders_scope_present": False,
        "token_scope_source": "unavailable",
        "active_token_scope_verified": False,
        "read_orders_scope_present": False,
        "trustpilot_note_evidence_found": False,
        "trustpilot_tag_evidence_found": False,
        "evidence_order_name": "",
        "safe_detected_keyword": "",
        "failure_type": "",
        "error_sanitized": "",
        "read_all_orders_scope_present": False,
        "lifetime_history_scope_confirmed": False,
        "reauthorization_required": True,
        "next_admin_action": "",
        "scope_verification_status": "scope_check_not_available",
        "customer_history_permission_status": "customer_history_incomplete",
    }


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = sorted(set(EMAIL_RE.findall(text)))
    secret_hits = SECRET_VALUE_RE.findall(text)
    payload["self_privacy_scan"] = {
        "raw_customer_email_count": len(raw_emails),
        "token_secret_pattern_count": len(secret_hits),
    }
    if raw_emails or secret_hits:
        payload["lookup_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["final_recommendation"] = "block_review_send"
        payload["should_block_review_send"] = True
        payload["blocking_reason"] = "Customer history lookup privacy scan failed."
        payload["privacy_assertion_passed"] = False
        payload["raw_email_leak_risk_detected"] = bool(raw_emails)
    return payload


def _customer_history_permission_status(lookup: dict, completed: bool) -> str:
    if lookup.get("reauthorization_required") is True:
        return "reauthorization_needed"
    if lookup.get("read_all_orders_scope_present") is not True:
        return "permission_missing"
    if completed and lookup.get("lifetime_history_scope_confirmed") is True:
        return "full_history_available"
    if completed:
        return "customer_history_checked"
    return "customer_history_incomplete"


def _issue_summary(
    selected_order: str,
    lookup_status: str,
    customer_count: int,
    note_evidence: bool,
    tag_evidence: bool,
    final_recommendation: str,
) -> str:
    return (
        f"{selected_order} on-demand customer history lookup status={lookup_status}; "
        f"Shopify customer history count={customer_count}; "
        f"Trustpilot note evidence found={note_evidence}; "
        f"Trustpilot tag evidence found={tag_evidence}; "
        f"final recommendation={final_recommendation}. "
        "No Shopify write, tag mutation, Gmail API/send, external review API call, raw email output, or full note output."
    )


def _decode_bytes(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return value.decode("utf-8", errors="replace")


def _tail(text: str, max_chars: int = 1000) -> str:
    return _sanitize_text((text or "")[-max_chars:])


def _canonical_order_name(value) -> str:
    text = _safe_text(value, 80).strip()
    if not text:
        return ""
    if text.startswith("#"):
        return text
    if text.isdigit():
        return f"#{text}"
    return text


def _safe_order_names(values) -> list[str]:
    result = []
    seen = set()
    for value in values or []:
        name = _canonical_order_name(value)
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _safe_text(value, max_length: int = 300) -> str:
    return _sanitize_text(str(value or ""), max_length=max_length)


def _sanitize_text(text: str, max_length: int = 300) -> str:
    redacted = SECRET_VALUE_RE.sub("[redacted]", str(text or ""))
    redacted = EMAIL_RE.sub("[masked-email]", redacted)
    return redacted[:max_length]


def _int_or_zero(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0
