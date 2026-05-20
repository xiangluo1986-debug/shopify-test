import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from shopify_sync.models import ShopifyInstallation, ShopifyOrder
from shopify_sync.review_request_history_ledger import (
    write_customer_history_lookup_cache_with_mirrors,
)
from shopify_sync.review_request_workbench import build_review_request_workbench_context
from shopify_sync.sync_helpers import (
    ShopifyRateLimitError,
    get_next_page_info_from_link_header,
    shopify_get,
)


TASK_NAME = "run_review_request_batch_customer_history_lookup"
SHOP_DOMAIN = "kidstoylover.myshopify.com"
SHOPIFY_API_VERSION = "2026-01"
DEFAULT_LIMIT = 25
DEFAULT_REQUEST_DELAY_SECONDS = 1.0
FOCUS_ORDER = "#22562"

LIVE_HISTORY_MISSING_REASON = "Customer history needs live Shopify check before sending."
LIVE_HISTORY_STALE_REASON = "Customer history check is stale."
LIVE_HISTORY_FAILED_INCOMPLETE_REASON = "Live customer history check failed or incomplete."
TRUSTPILOT_HISTORY_BLOCK_STATUSES = {"blocked_trustpilot_note", "blocked_trustpilot_tag"}
LIVE_LOOKUP_NEEDED_STATUSES = {"missing", "stale", "incomplete", "blocked_lookup_cache"}
FAILED_INCOMPLETE_STATUSES = {"incomplete", "blocked_lookup_cache"}
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


class Command(BaseCommand):
    help = (
        "Run the Review Request batch customer history lookup inside the Django "
        "web container and write the sanitized lookup cache to Docker-visible paths."
    )

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
        parser.add_argument("--order-filter", default="")
        parser.add_argument("--request-delay", type=float, default=DEFAULT_REQUEST_DELAY_SECONDS)
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        try:
            payload = run_batch_lookup(
                limit=max(int(options["limit"] or DEFAULT_LIMIT), 1),
                order_filter=_parse_order_filter(options.get("order_filter")),
                request_delay_seconds=max(float(options["request_delay"] or 0), 0.0),
                dry_run=options["dry_run"] is True,
            )
        except Exception as exc:
            raise CommandError(
                "Batch customer history lookup failed: "
                f"{exc.__class__.__name__}: {_safe_text(exc, 300)}"
            ) from exc

        self.stdout.write(self.style.SUCCESS("Batch customer history lookup completed."))
        self.stdout.write(f"status: {payload['task_status']}")
        self.stdout.write(f"base_candidates_needing_live_check: {payload['base_candidates_needing_live_check']}")
        self.stdout.write(f"customers_to_lookup: {payload['customers_to_lookup']}")
        self.stdout.write(f"checked: {payload['checked']}")
        self.stdout.write(f"clean: {payload['clean']}")
        self.stdout.write(
            f"blocked_by_trustpilot_history: {payload['blocked_by_trustpilot_history']}"
        )
        self.stdout.write(f"failed_or_incomplete: {payload['failed_or_incomplete']}")
        self.stdout.write(f"final_eligible_after_lookup: {payload['final_eligible_after_lookup']}")
        focus = payload.get("focus_22562") or {}
        self.stdout.write(f"#22562 lookup_status: {focus.get('lookup_status') or '-'}")
        self.stdout.write(f"#22562 final_section: {focus.get('final_section') or '-'}")
        self.stdout.write(f"#22562 final_eligibility: {focus.get('final_eligibility') or '-'}")
        self.stdout.write(f"#22562 review_send_ready: {focus.get('review_send_ready') is True}")
        self.stdout.write("cache_paths_written:")
        for path in payload.get("cache_paths_written") or []:
            self.stdout.write(f"- {path}")
        if payload.get("cache_paths_failed"):
            self.stdout.write("cache_paths_failed:")
            for item in payload["cache_paths_failed"]:
                self.stdout.write(f"- {item.get('path', '')}: {item.get('error', '')}")
        self.stdout.write(
            "safety: read-only Shopify lookup only; no Shopify write, no tag mutation, "
            "no Gmail API/send, no external review API, no raw email, no full note output."
        )
        self.stdout.write("shopify_write_performed: False")
        self.stdout.write("mutation_performed: False")
        self.stdout.write("translations_register_called: False")
        self.stdout.write("gmail_api_call_performed: False")
        self.stdout.write("email_sent: False")


def run_batch_lookup(limit, order_filter, request_delay_seconds, dry_run):
    started = time.time()
    initial_scan = _build_live_scan()
    base_candidates = _base_candidates_needing_live_lookup(initial_scan, order_filter)
    lookup_groups, skipped_duplicate_customer_count = _dedupe_candidates_by_customer(base_candidates)
    lookup_groups = _prioritize_focus_order(lookup_groups, FOCUS_ORDER)
    limited_groups = lookup_groups[:limit]

    checked = 0
    clean = 0
    blocked = 0
    failed = 0
    rate_limited_stop = False
    lookup_results_by_order = {}
    cache_paths_written = []
    cache_paths_failed = []

    for index, group in enumerate(limited_groups, start=1):
        lookup_order = group["lookup_order"]
        group_started = time.time()
        if dry_run:
            payload = _preview_lookup_payload(lookup_order)
            cache_result = _empty_cache_result()
        else:
            lookup = _run_live_customer_history_lookup(lookup_order)
            payload = _build_lookup_payload(
                selected_order=lookup_order,
                lookup=lookup,
                duration_seconds=round(time.time() - group_started, 3),
            )
            _assert_no_private_output(payload)
            cache_result = _persist_lookup_cache(payload)
            _collect_cache_paths(cache_result, cache_paths_written, cache_paths_failed)

        checked += 1
        group_status = _lookup_group_status(payload)
        if group_status == "clean":
            clean += 1
        elif group_status == "blocked":
            blocked += 1
        else:
            failed += 1

        lookup_results_by_order[lookup_order] = payload
        if not dry_run:
            for duplicate_order in group["candidate_orders"]:
                if duplicate_order == lookup_order:
                    continue
                duplicate_payload = _clone_lookup_payload_for_order(payload, duplicate_order)
                _assert_no_private_output(duplicate_payload)
                duplicate_cache_result = _persist_lookup_cache(duplicate_payload)
                _collect_cache_paths(duplicate_cache_result, cache_paths_written, cache_paths_failed)
                lookup_results_by_order[duplicate_order] = duplicate_payload

        if _rate_limited(payload):
            rate_limited_stop = True
            break
        if not dry_run and request_delay_seconds > 0 and index < len(limited_groups):
            time.sleep(request_delay_seconds)

    final_scan = _build_live_scan()
    final_lists = _final_lists_from_scan(final_scan)
    payload = {
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.32I",
        "task_status": "rate_limited_stop" if rate_limited_stop else "batch_customer_history_lookup_ready",
        "success": not rate_limited_stop,
        "dry_run": dry_run,
        "generated_at": _utc_now_iso(),
        "duration_seconds": round(time.time() - started, 3),
        "limit": limit,
        "request_delay_seconds": request_delay_seconds,
        "order_filter": sorted(order_filter),
        "base_candidates_needing_live_check": len(base_candidates),
        "base_candidates_needing_live_check_count": len(base_candidates),
        "customers_to_lookup": len(lookup_groups),
        "customers_to_lookup_count": len(lookup_groups),
        "limited_customer_lookup_count": len(limited_groups),
        "checked": checked,
        "checked_count": checked,
        "clean": clean,
        "clean_count": clean,
        "blocked_by_trustpilot_history": blocked,
        "blocked_by_trustpilot_history_count": blocked,
        "failed_or_incomplete": failed,
        "failed_or_incomplete_count": failed,
        "skipped_duplicate_customer_count": skipped_duplicate_customer_count,
        "final_eligible_after_lookup": final_lists["final_eligible_count"],
        "final_eligible_count_after_lookup": final_lists["final_eligible_count"],
        "final_eligible_orders": final_lists["final_eligible_orders"],
        "blocked_by_historical_trustpilot_evidence_orders": final_lists[
            "blocked_by_historical_trustpilot_evidence_orders"
        ],
        "blocked_live_lookup_failed_or_incomplete_orders": final_lists[
            "blocked_live_lookup_failed_or_incomplete_orders"
        ],
        "still_needs_live_customer_history_check_orders": final_lists[
            "still_needs_live_customer_history_check_orders"
        ],
        "focus_22562": _focus_order_22562(final_scan, lookup_results_by_order),
        "cache_paths_written": sorted(set(cache_paths_written)),
        "cache_paths_failed": cache_paths_failed,
        "no_gmail_api_call": True,
        "no_shopify_write": True,
        "no_external_review_api": True,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "translations_register_called": False,
        "external_review_api_call_performed": False,
        "raw_email_output": False,
        "raw_customer_email_output": False,
        "full_note_output": False,
        "secrets_output": False,
    }
    _assert_no_private_output(payload)
    return payload


def _build_live_scan():
    context = build_review_request_workbench_context({}, use_dashboard_snapshot=False)
    dashboard = (context.get("review_request_workbench") or {}).get("operating_dashboard") or {}
    return dashboard.get("last_60_days_candidate_scan") or {}


def _base_candidates_needing_live_lookup(scan, order_filter):
    result = []
    for row in _scan_rows(scan, "blocked"):
        order = _canonical_order_name(row.get("order") or row.get("order_name"))
        if not order:
            continue
        if order_filter and order not in order_filter:
            continue
        if _row_needs_live_lookup(row):
            result.append(dict(row))
    return result


def _row_needs_live_lookup(row):
    if row.get("blocked_by_customer_history_lookup") is not True:
        return False
    status = _safe_text(row.get("customer_history_lookup_block_status"), 80)
    if status in TRUSTPILOT_HISTORY_BLOCK_STATUSES:
        return False
    if status in LIVE_LOOKUP_NEEDED_STATUSES:
        return True
    reason = " ".join(
        _safe_text(row.get(key), 500)
        for key in ("block_reason", "reason", "eligibility_reason_plain", "missing_requirement")
    ).lower()
    return (
        LIVE_HISTORY_MISSING_REASON.lower() in reason
        or LIVE_HISTORY_STALE_REASON.lower() in reason
        or LIVE_HISTORY_FAILED_INCOMPLETE_REASON.lower() in reason
    )


def _dedupe_candidates_by_customer(candidates):
    groups_by_key = {}
    order = []
    for row in candidates:
        customer_key, source = _customer_key(row)
        if customer_key not in groups_by_key:
            groups_by_key[customer_key] = {
                "customer_key": customer_key,
                "customer_key_hash": _hash_text(customer_key),
                "customer_key_source": source,
                "lookup_order": _canonical_order_name(row.get("order") or row.get("order_name")),
                "candidate_orders": [],
                "rows": [],
            }
            order.append(customer_key)
        group = groups_by_key[customer_key]
        order_name = _canonical_order_name(row.get("order") or row.get("order_name"))
        if order_name and order_name not in group["candidate_orders"]:
            group["candidate_orders"].append(order_name)
        group["rows"].append(row)
    groups = [groups_by_key[key] for key in order]
    skipped = sum(max(len(group["candidate_orders"]) - 1, 0) for group in groups)
    return groups, skipped


def _prioritize_focus_order(groups, order_name):
    target = _canonical_order_name(order_name)
    priority = []
    rest = []
    for group in groups:
        if target in set(group.get("candidate_orders") or []):
            priority.append(group)
        else:
            rest.append(group)
    return priority + rest


def _customer_key(row):
    for key, source in (
        ("customer_identity_key", "customer_identity_key"),
        ("masked_customer", "masked_customer"),
        ("masked_customer_label", "masked_customer_label"),
        ("customer_masked_label", "customer_masked_label"),
        ("customer", "customer_display"),
    ):
        value = _safe_text(row.get(key), 300)
        if value and value.lower() not in {"masked in reports", "customer not loaded"}:
            return f"{source}:{value}", source
    order = _canonical_order_name(row.get("order") or row.get("order_name"))
    return f"order:{order}", "order_fallback"


def _run_live_customer_history_lookup(selected_order):
    result = _empty_lookup(selected_order)
    try:
        local_order = (
            ShopifyOrder.objects.filter(_order_lookup_query(selected_order))
            .select_related("installation")
            .order_by("-updated_at", "-id")
            .first()
        )
        if not local_order:
            return _lookup_failure(
                result,
                "blocked_selected_order_not_found_locally",
                "selected_order_not_found_locally",
                "Selected order was not found in local ShopifyOrder data.",
            )
        result["local_order_found"] = True
        local_rows, local_method = _local_customer_history(local_order)
        result["local_customer_history_count"] = len(_safe_order_names(row.get("order_name") for row in local_rows))
        result["local_customer_history_order_names"] = _safe_order_names(row.get("order_name") for row in local_rows)
        result["local_customer_history_match_method"] = local_method

        installation = local_order.installation or ShopifyInstallation.objects.filter(shop=SHOP_DOMAIN).first()
        if not installation:
            installation = ShopifyInstallation.objects.order_by("-id").first()
        if not installation:
            return _lookup_failure(
                result,
                "blocked_customer_history_lookup_not_available",
                "shopify_installation_missing",
                "Shopify installation was not found in local Django data.",
            )
        result["shopify_installation_found"] = True
        scope_text = str(getattr(installation, "scope", "") or "")
        result["configured_scope_source"] = "ShopifyInstallation.scope"
        result["configured_read_orders_scope_present"] = _scope_present(scope_text, "read_orders")
        result["configured_read_all_orders_scope_present"] = _scope_present(scope_text, "read_all_orders")
        access_token = getattr(installation, "access_" + "token", "")
        result["shopify_credentials_found"] = bool(access_token)
        if not access_token:
            return _lookup_failure(
                result,
                "blocked_customer_history_lookup_not_available",
                "missing_shopify_access_token",
                "Shopify installation exists, but the access token is empty.",
            )

        _verify_access_scopes(installation.shop, access_token, result)
        if result["active_token_scope_verified"] is not True:
            return _lookup_failure(
                result,
                "blocked_customer_history_lookup_not_available",
                "access_scope_verification_unavailable",
                "Shopify token scopes could not be verified. Live customer history check failed or incomplete.",
            )
        if result["read_orders_scope_present"] is not True:
            return _lookup_failure(
                result,
                "blocked_shopify_history_permission_missing",
                "read_orders_scope_missing",
                READ_ORDERS_MISSING_MESSAGE,
            )
        if result["read_all_orders_scope_present"] is not True:
            return _lookup_failure(
                result,
                "blocked_shopify_history_permission_missing",
                "read_all_orders_scope_missing",
                READ_ALL_ORDERS_MISSING_MESSAGE,
            )

        rest_base = f"https://{installation.shop}/admin/api/{SHOPIFY_API_VERSION}"
        graphql_endpoint = f"{rest_base}/graphql.json"
        headers = {"X-Shopify-" + "Access-Token": access_token, "Content-Type": "application/json"}
        selected_shopify_order = _rest_order_by_id(
            rest_base,
            access_token,
            getattr(local_order, "shopify_order_id", ""),
            result,
        )
        if not selected_shopify_order:
            selected_shopify_order = _graphql_selected_order(
                graphql_endpoint,
                headers,
                selected_order,
                result,
            )
        if not selected_shopify_order:
            return _lookup_failure(
                result,
                "blocked_customer_history_lookup_not_available",
                "selected_order_shopify_read_failed",
                "Selected Shopify order could not be read with available read-only helpers.",
            )
        result["shopify_selected_order_found"] = True

        customer_id = _customer_id_from_order(selected_shopify_order)
        selected_email = _selected_email_from_order(selected_shopify_order)
        result["shopify_customer_id_available"] = bool(customer_id)
        result["runtime_email_available"] = bool(selected_email)
        result["shopify_customer_identity_found"] = bool(customer_id or selected_email)
        if not (customer_id or selected_email):
            return _lookup_failure(
                result,
                "blocked_customer_history_lookup_not_available",
                "selected_order_customer_identity_missing",
                "Selected Shopify order did not expose customer id or email for a safe history lookup.",
            )

        history_orders = []
        history_methods = []
        if customer_id:
            customer_orders = _rest_paginated_orders(
                f"{rest_base}/customers/{customer_id}/orders.json",
                access_token,
                {
                    "status": "any",
                    "limit": 250,
                    "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
                },
                "rest_customer_orders_by_customer_id",
                result,
            )
            if customer_orders:
                history_methods.append("rest_customer_orders_by_customer_id")
                history_orders.extend(customer_orders)
        if selected_email:
            email_orders = _rest_paginated_orders(
                f"{rest_base}/orders.json",
                access_token,
                {
                    "status": "any",
                    "limit": 250,
                    "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
                    "email": selected_email,
                },
                "rest_orders_by_email",
                result,
            )
            exact_email_orders = [
                order for order in email_orders if _selected_email_from_order(order) == selected_email
            ]
            if exact_email_orders:
                history_methods.append("rest_orders_by_email")
                history_orders.extend(exact_email_orders)
        if customer_id:
            graphql_orders = _graphql_history_orders(
                graphql_endpoint,
                headers,
                f"customer_id:{customer_id}",
                "graphql_orders_by_customer_id",
                result,
            )
            if graphql_orders:
                history_methods.append("graphql_orders_by_customer_id")
                history_orders.extend(graphql_orders)
        if selected_email:
            graphql_orders = _graphql_history_orders(
                graphql_endpoint,
                headers,
                f"email:{selected_email}",
                "graphql_orders_by_email",
                result,
            )
            exact_graphql_email_orders = [
                order for order in graphql_orders if _selected_email_from_order(order) == selected_email
            ]
            if exact_graphql_email_orders:
                history_methods.append("graphql_orders_by_email")
                history_orders.extend(exact_graphql_email_orders)

        history_orders = _dedupe_history_orders(history_orders)
        if history_methods:
            result["shopify_history_lookup_method"] = "+".join(history_methods)
        result["shopify_customer_history_count"] = len(_safe_order_names(_order_name_from_shopify_order(order) for order in history_orders))
        result["shopify_history_order_names"] = _safe_order_names(
            _order_name_from_shopify_order(order) for order in history_orders
        )
        if not history_orders:
            return _lookup_failure(
                result,
                "blocked_customer_history_lookup_not_available",
                "customer_history_query_returned_no_orders",
                "Customer history lookup returned no orders; Review & Send must stay blocked.",
            )

        note_evidence = {}
        tag_evidence = {}
        for order in history_orders:
            if not note_evidence:
                note_evidence = _detect_note_evidence(order, selected_order)
            if not tag_evidence:
                tag_evidence = _detect_tag_evidence(order, selected_order)
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
        return result
    except ShopifyRateLimitError as exc:
        response = getattr(exc, "response", None)
        result["shopify_http_status"] = getattr(response, "status_code", 429) or 429
        return _lookup_failure(
            result,
            "blocked_customer_history_lookup_not_available",
            "shopify_rate_limited",
            "Shopify read-only customer history lookup was rate limited.",
        )
    except Exception as exc:
        return _lookup_failure(
            result,
            "blocked_customer_history_lookup_not_available",
            "customer_history_lookup_exception",
            _safe_text(exc, 300),
        )


def _empty_lookup(selected_order):
    return {
        "success": False,
        "lookup_status": "blocked_not_started",
        "selected_order": _canonical_order_name(selected_order),
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


def _lookup_failure(result, lookup_status, failure_type, message):
    result["lookup_status"] = lookup_status
    result["failure_type"] = failure_type
    result["error_sanitized"] = _safe_text(message, 300)
    result["reauthorization_required"] = failure_type in {
        "read_orders_scope_missing",
        "read_all_orders_scope_missing",
        "access_scope_verification_unavailable",
    }
    return result


def _verify_access_scopes(shop_domain, access_token, result):
    result["token_scope_source"] = "shopify_access_scopes_endpoint"
    result["customer_history_lookup_methods_attempted"].append("access_scope_verification")
    try:
        result["shopify_api_lookup_performed"] = True
        result["read_only_shopify_lookup_performed"] = True
        response = shopify_get(
            f"https://{shop_domain}/admin/oauth/access_scopes.json",
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
        result["shopify_api_response_errors_sanitized"].append(_safe_text(exc, 240))
        result["scope_verification_status"] = "access_scope_endpoint_unavailable"
        result["customer_history_permission_status"] = "permission_unverified"
        result["next_admin_action"] = "Verify Shopify access scopes before sending."
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
    result["reauthorization_required"] = not all(scope in handles for scope in REQUIRED_HISTORY_SCOPES)
    if result["read_orders_scope_present"] and result["read_all_orders_scope_present"]:
        result["scope_verification_status"] = "active_token_scope_verified"
        result["customer_history_permission_status"] = "full_history_available"
        result["next_admin_action"] = "No reauthorization needed for Review Request customer history reads."
    elif handles:
        result["scope_verification_status"] = "read_all_orders_missing_reauthorization_required"
        result["customer_history_permission_status"] = "permission_missing"
        result["next_admin_action"] = "Reauthorize or reinstall the Shopify app before sending."
    else:
        result["scope_verification_status"] = "access_scope_endpoint_unavailable"
        result["customer_history_permission_status"] = "permission_unverified"
        result["next_admin_action"] = "Verify Shopify access scopes before sending."
    return handles


def _rest_order_by_id(rest_base, access_token, order_id, result):
    if not str(order_id or "").isdigit():
        return {}
    try:
        data, _response = _rest_get_json(
            f"{rest_base}/orders/{order_id}.json",
            access_token,
            {
                "fields": "id,name,order_number,created_at,email,contact_email,customer,tags,note,note_attributes",
            },
            "rest_selected_order_by_local_shopify_order_id",
            result,
        )
        return data.get("order") or {}
    except Exception as exc:
        result["shopify_api_response_error_count"] += 1
        result["shopify_api_response_errors_sanitized"].append(_safe_text(exc, 240))
        return {}


def _graphql_selected_order(endpoint, headers, order_name, result):
    data = _request_graphql(
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
        {"query": f"name:{order_name}"},
        "graphql_selected_order_by_name",
        result,
    )
    edges = (((data.get("orders") or {}).get("edges")) or [])
    orders = [(edge or {}).get("node") or {} for edge in edges]
    return next((order for order in orders if order.get("name") == order_name), orders[0] if orders else {})


def _rest_paginated_orders(url, access_token, params, label, result):
    orders = []
    page_info = None
    seen = set()
    while True:
        current_params = {"limit": 250, "page_info": page_info} if page_info else dict(params)
        try:
            data, response = _rest_get_json(url, access_token, current_params, label, result)
        except Exception as exc:
            result["shopify_api_response_error_count"] += 1
            result["shopify_api_response_errors_sanitized"].append(_safe_text(exc, 240))
            break
        orders.extend(data.get("orders") or [])
        next_page_info = get_next_page_info_from_link_header(response.headers.get("Link", ""))
        if not next_page_info or next_page_info in seen:
            break
        seen.add(next_page_info)
        page_info = next_page_info
    return orders


def _rest_get_json(url, access_token, params, label, result):
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


def _graphql_history_orders(endpoint, headers, search_query, label, result):
    orders = []
    cursor = None
    while True:
        data = _request_graphql(
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
            result,
        )
        connection = data.get("orders") or {}
        edges = connection.get("edges") or []
        orders.extend((edge or {}).get("node") or {} for edge in edges)
        page_info = connection.get("pageInfo") or {}
        if not page_info.get("hasNextPage") or not page_info.get("endCursor"):
            break
        cursor = page_info.get("endCursor")
    return orders


def _request_graphql(endpoint, headers, query, variables, label, result):
    result["customer_history_lookup_methods_attempted"].append(label)
    try:
        response = requests.post(
            endpoint,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=30,
        )
    except requests.RequestException as exc:
        result["shopify_api_response_error_count"] += 1
        result["shopify_api_response_errors_sanitized"].append(_safe_text(exc, 240))
        return {}
    result["shopify_api_lookup_performed"] = True
    result["read_only_shopify_lookup_performed"] = True
    result["shopify_http_status"] = response.status_code
    if response.status_code >= 400:
        result["shopify_api_response_error_count"] += 1
        result["shopify_api_response_errors_sanitized"].append(
            f"Shopify GraphQL HTTP error {response.status_code}"
        )
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
            message = error.get("message") if isinstance(error, dict) else error
            result["shopify_api_response_errors_sanitized"].append(_safe_text(message, 240))
        return {}
    return data.get("data") or {}


def _build_lookup_payload(selected_order, lookup, duration_seconds):
    lookup_status = _safe_text(lookup.get("lookup_status") or "blocked_customer_history_lookup_not_available", 120)
    completed = lookup_status == "customer_history_lookup_completed"
    note_evidence = lookup.get("trustpilot_note_evidence_found") is True
    tag_evidence = lookup.get("trustpilot_tag_evidence_found") is True
    customer_count = _int_value(lookup.get("shopify_customer_history_count"))
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
    should_block = bool(note_evidence or tag_evidence or not full_history_confirmed)
    blocking_reason = _safe_text(lookup.get("error_sanitized"), 300)
    if should_block and not blocking_reason:
        if note_evidence:
            blocking_reason = f"Previous Trustpilot note found on historical order {evidence_order or 'another order'}."
        elif tag_evidence:
            blocking_reason = f"Previous Trustpilot tag found on historical order {evidence_order or 'another order'}."
        else:
            blocking_reason = LIVE_HISTORY_FAILED_INCOMPLETE_REASON
    return {
        "timestamp": _utc_now_iso(),
        "generated_at": _utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.32I",
        "lookup_status": lookup_status,
        "success": completed and not should_block,
        "selected_order": _canonical_order_name(selected_order),
        "duration_seconds": duration_seconds,
        "shopify_api_lookup_performed": shopify_api_lookup_performed,
        "read_only_shopify_lookup_performed": lookup.get("read_only_shopify_lookup_performed") is True,
        "read_all_orders_scope_present": read_all_orders_scope_present,
        "lifetime_history_scope_confirmed": lifetime_history_scope_confirmed,
        "full_history_confirmed": full_history_confirmed,
        "shopify_customer_history_count": customer_count,
        "historical_order_names": _safe_order_names(
            lookup.get("shopify_history_order_names") or lookup.get("local_customer_history_order_names") or []
        ),
        "shopify_history_lookup_method": _safe_text(lookup.get("shopify_history_lookup_method"), 120),
        "customer_history_lookup_methods_attempted": [
            _safe_text(item, 120) for item in lookup.get("customer_history_lookup_methods_attempted") or []
        ],
        "customer_history_permission_status": _safe_text(
            lookup.get("customer_history_permission_status")
            or ("full_history_available" if full_history_confirmed else "full_history_unavailable"),
            120,
        ),
        "trustpilot_note_evidence_found": note_evidence,
        "trustpilot_tag_evidence_found": tag_evidence,
        "evidence_order_name": evidence_order,
        "safe_detected_keyword": _safe_text(lookup.get("safe_detected_keyword"), 80),
        "should_block_review_send": should_block,
        "blocking_reason": blocking_reason,
        "failure_type": _safe_text(lookup.get("failure_type"), 120),
        "shopify_http_status": _int_value(lookup.get("shopify_http_status")),
        "shopify_api_response_error_count": _int_value(lookup.get("shopify_api_response_error_count")),
        "shopify_api_response_errors_sanitized": [
            _safe_text(item, 240) for item in lookup.get("shopify_api_response_errors_sanitized") or []
        ],
        "raw_email_output": False,
        "raw_customer_email_output": False,
        "raw_phone_output": False,
        "raw_address_output": False,
        "full_note_output": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
    }


def _persist_lookup_cache(payload):
    cache_result = write_customer_history_lookup_cache_with_mirrors(_lookup_cache_log_dir(), payload)
    return {
        "lookup_cache_saved": bool(cache_result.get("main_path")),
        "lookup_cache_path": str(cache_result.get("main_path") or ""),
        "lookup_cache_paths_written": cache_result.get("paths_written") or [],
        "lookup_cache_paths_failed": cache_result.get("paths_failed") or [],
        "lookup_cache_aggregate_paths_written": cache_result.get("aggregate_cache_paths_written") or [],
        "lookup_cache_order_paths_written": cache_result.get("order_cache_paths_written") or [],
    }


def _lookup_cache_log_dir():
    return Path(settings.BASE_DIR).resolve() / "logs"


def _collect_cache_paths(cache_result, paths_written, paths_failed):
    for path in cache_result.get("lookup_cache_paths_written") or []:
        if path not in paths_written:
            paths_written.append(path)
    for item in cache_result.get("lookup_cache_paths_failed") or []:
        if item not in paths_failed:
            paths_failed.append(item)


def _preview_lookup_payload(selected_order):
    return {
        "timestamp": _utc_now_iso(),
        "generated_at": _utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "lookup_status": "preview_only_no_live_lookup",
        "success": False,
        "selected_order": selected_order,
        "shopify_api_lookup_performed": False,
        "read_only_shopify_lookup_performed": False,
        "shopify_customer_history_count": 0,
        "historical_order_names": [],
        "trustpilot_note_evidence_found": False,
        "trustpilot_tag_evidence_found": False,
        "evidence_order_name": "",
        "safe_detected_keyword": "",
        "should_block_review_send": True,
        "blocking_reason": LIVE_HISTORY_FAILED_INCOMPLETE_REASON,
        "full_history_confirmed": False,
        "raw_email_output": False,
        "full_note_output": False,
    }


def _clone_lookup_payload_for_order(payload, selected_order):
    cloned = dict(payload or {})
    cloned["selected_order"] = _canonical_order_name(selected_order)
    cloned["generated_at"] = _utc_now_iso()
    cloned["timestamp"] = cloned["generated_at"]
    cloned["batch_lookup_source_order"] = _canonical_order_name((payload or {}).get("selected_order"))
    cloned["batch_lookup_reused_for_duplicate_customer"] = True
    cloned["raw_email_output"] = False
    cloned["full_note_output"] = False
    return cloned


def _lookup_group_status(payload):
    if payload.get("trustpilot_note_evidence_found") is True or payload.get("trustpilot_tag_evidence_found") is True:
        return "blocked"
    if payload.get("should_block_review_send") is True:
        return "failed_or_incomplete"
    if payload.get("full_history_confirmed") is True:
        return "clean"
    return "failed_or_incomplete"


def _rate_limited(payload):
    if _int_value(payload.get("shopify_http_status")) == 429:
        return True
    text = json.dumps(_safe_json_fragment(payload), ensure_ascii=True, sort_keys=True).lower()
    return "429" in text and "shopify" in text


def _final_lists_from_scan(scan):
    eligible_rows = _scan_rows(scan, "eligible")
    blocked_rows = _scan_rows(scan, "blocked")
    return {
        "final_eligible_count": len(eligible_rows),
        "final_eligible_orders": _safe_order_names(row.get("order") for row in eligible_rows),
        "blocked_by_historical_trustpilot_evidence_orders": _safe_order_names(
            row.get("order") for row in blocked_rows if _row_blocked_by_trustpilot_history(row)
        ),
        "blocked_live_lookup_failed_or_incomplete_orders": _safe_order_names(
            row.get("order") for row in blocked_rows if _row_failed_or_incomplete_lookup(row)
        ),
        "still_needs_live_customer_history_check_orders": _safe_order_names(
            row.get("order") for row in blocked_rows if _row_still_needs_live_lookup(row)
        ),
    }


def _focus_order_22562(scan, lookup_results_by_order):
    row, section = _find_order_row(scan, FOCUS_ORDER)
    lookup = lookup_results_by_order.get(FOCUS_ORDER) or {}
    final_eligibility = "not_scanned"
    if row:
        if section in {"eligible", "review_queue"}:
            final_eligibility = "eligible"
        elif section == "already_sent":
            final_eligibility = "already_sent"
        else:
            final_eligibility = "blocked"
    blocker = _safe_text(
        (row or {}).get("block_reason")
        or (row or {}).get("reason")
        or (row or {}).get("eligibility_reason_plain"),
        500,
    )
    return {
        "order_name": FOCUS_ORDER,
        "live_lookup_performed": bool(lookup),
        "lookup_status": _safe_text(lookup.get("lookup_status"), 120),
        "lookup_clean": _lookup_group_status(lookup) == "clean" if lookup else False,
        "lookup_blocked_by_history": _lookup_group_status(lookup) == "blocked" if lookup else False,
        "lookup_failed_or_incomplete": _lookup_group_status(lookup) == "failed_or_incomplete" if lookup else False,
        "final_section": section,
        "final_eligibility": final_eligibility,
        "review_send_ready": bool(row and final_eligibility == "eligible"),
        "blocker": blocker,
        "customer_history_lookup_status": _safe_text((row or {}).get("customer_history_lookup_status"), 120),
        "customer_history_lookup_block_status": _safe_text(
            (row or {}).get("customer_history_lookup_block_status"),
            120,
        ),
    }


def _find_order_row(scan, order_name):
    target = _canonical_order_name(order_name)
    for section, key in (
        ("review_queue", "review_queue_rows"),
        ("review_queue", "review_queue_candidates"),
        ("eligible", "eligible_queue_rows"),
        ("eligible", "eligible_candidates_summary"),
        ("blocked", "blocked_queue_rows"),
        ("blocked", "blocked_candidates_summary"),
        ("already_sent", "already_sent_queue_rows"),
        ("already_sent", "already_sent_summary"),
    ):
        for row in scan.get(key) or []:
            if _canonical_order_name(row.get("order") or row.get("order_name")) == target:
                return row, section
    return {}, "not_scanned"


def _scan_rows(scan, section):
    key_groups = {
        "eligible": ("eligible_queue_rows", "review_queue_rows", "eligible_candidates_summary", "review_queue_candidates"),
        "blocked": ("blocked_queue_rows", "blocked_candidates_summary"),
        "already_sent": ("already_sent_queue_rows", "already_sent_summary"),
    }
    rows = []
    for key in key_groups.get(section, ()):
        for row in scan.get(key) or []:
            if isinstance(row, dict):
                rows.append(dict(row))
        if rows:
            break
    return rows


def _row_blocked_by_trustpilot_history(row):
    status = _safe_text(row.get("customer_history_lookup_block_status"), 80)
    return bool(
        status in TRUSTPILOT_HISTORY_BLOCK_STATUSES
        or row.get("customer_level_trustpilot_already_sent") is True
        or row.get("customer_level_trustpilot_note_evidence_found") is True
        or "previous trustpilot" in _safe_text(row.get("block_reason"), 500).lower()
    )


def _row_failed_or_incomplete_lookup(row):
    status = _safe_text(row.get("customer_history_lookup_block_status"), 80)
    if status in FAILED_INCOMPLETE_STATUSES and not _row_blocked_by_trustpilot_history(row):
        return True
    reason = _safe_text(row.get("block_reason") or row.get("reason"), 500).lower()
    return LIVE_HISTORY_FAILED_INCOMPLETE_REASON.lower() in reason


def _row_still_needs_live_lookup(row):
    status = _safe_text(row.get("customer_history_lookup_block_status"), 80)
    if status in {"missing", "stale"}:
        return True
    reason = _safe_text(row.get("block_reason") or row.get("reason"), 500).lower()
    return LIVE_HISTORY_MISSING_REASON.lower() in reason or LIVE_HISTORY_STALE_REASON.lower() in reason


def _order_lookup_query(order_name):
    text = _safe_text(order_name, 80).strip()
    raw = text.lstrip("#")
    names = {text, _canonical_order_name(text)}
    numbers = set()
    shopify_ids = set()
    if raw.isdigit():
        names.add(raw)
        names.add(f"#{raw}")
        numbers.add(raw)
        shopify_ids.add(raw)
    query = Q(order_name__in=[item for item in names if item])
    if numbers:
        query |= Q(order_number__in=numbers)
    if shopify_ids:
        query |= Q(shopify_order_id__in=shopify_ids)
    return query


def _local_customer_history(local_order):
    email = _normalize_email(getattr(local_order, "customer_email", ""))
    name = str(getattr(local_order, "customer_name", "") or "").strip()
    shipping_name = str(getattr(local_order, "shipping_name", "") or "").strip()
    shipping_phone = re.sub(r"\D+", "", str(getattr(local_order, "shipping_phone", "") or ""))
    shipping_zip = str(getattr(local_order, "shipping_zip", "") or "").strip()
    query = None
    method = ""
    if email:
        query = Q(customer_email__iexact=email)
        method = "customer_email"
    elif name and shipping_phone:
        query = Q(customer_name__iexact=name, shipping_phone__icontains=shipping_phone[-6:])
        method = "customer_name_shipping_phone"
    elif shipping_name and shipping_zip:
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


def _scope_present(scope_text, required_scope):
    scopes = {part.strip() for part in re.split(r"[\s,]+", str(scope_text or "")) if part.strip()}
    return required_scope in scopes


def _selected_email_from_order(order):
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


def _normalize_email(value):
    text = str(value or "").strip().lower()
    return text if EMAIL_RE.fullmatch(text) else ""


def _customer_id_from_order(order):
    customer = (order or {}).get("customer") or {}
    raw = str(customer.get("id") or customer.get("admin_graphql_api_id") or "")
    tail = raw.rsplit("/", 1)[-1]
    return tail if tail.isdigit() else ""


def _order_name_from_shopify_order(order):
    return _canonical_order_name(
        (order or {}).get("name") or (order or {}).get("order_name") or (order or {}).get("order_number")
    )


def _dedupe_history_orders(orders):
    deduped = []
    seen = set()
    for order in orders or []:
        if not isinstance(order, dict):
            continue
        key = str(
            order.get("id")
            or order.get("admin_graphql_api_id")
            or order.get("name")
            or order.get("order_number")
            or ""
        ).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(order)
    return deduped


def _detect_note_evidence(order, target_name):
    order_name = _order_name_from_shopify_order(order)
    if order_name == target_name:
        return {}
    for field in ("note", "note_attributes", "shopify_note", "shopify_note_attributes"):
        for fragment in _text_fragments((order or {}).get(field)):
            keyword = _trustpilot_keyword(fragment)
            if keyword:
                return {"order_name": order_name, "safe_keyword": keyword, "source": "order_note"}
    return {}


def _detect_tag_evidence(order, target_name):
    order_name = _order_name_from_shopify_order(order)
    if order_name == target_name:
        return {}
    for tag in _split_tags((order or {}).get("tags")):
        keyword = _trustpilot_keyword(tag)
        if keyword:
            return {"order_name": order_name, "safe_keyword": keyword, "source": "order_tag"}
    return {}


def _text_fragments(value):
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        fragments = []
        for item in value.values():
            fragments.extend(_text_fragments(item))
        return fragments
    if isinstance(value, (list, tuple, set)):
        fragments = []
        for item in value:
            fragments.extend(_text_fragments(item))
        return fragments
    text = str(value or "")
    return [text[:2000]] if text else []


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


def _parse_order_filter(value):
    values = re.split(r"[\s,;]+", str(value or ""))
    return {_canonical_order_name(item) for item in values if _canonical_order_name(item)}


def _canonical_order_name(value):
    text = _safe_text(value, 80).strip()
    if not text:
        return ""
    if text.startswith("#"):
        return text
    if text.isdigit():
        return f"#{text}"
    return text


def _safe_order_names(values):
    result = []
    seen = set()
    for value in values or []:
        name = _canonical_order_name(value)
        if not name or name in seen:
            continue
        seen.add(name)
        result.append(name)
    return result


def _safe_text(value, max_length=300):
    text = str(value or "")
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = EMAIL_RE.sub("[masked-email]", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def _int_value(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _hash_text(value):
    return hashlib.sha256(_safe_text(value, 500).encode("utf-8")).hexdigest()[:16]


def _safe_json_fragment(value):
    if isinstance(value, dict):
        return {str(key): _safe_json_fragment(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_safe_json_fragment(item) for item in value]
    return _safe_text(value)


def _assert_no_private_output(payload):
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = [email for email in EMAIL_RE.findall(text) if "***" not in email and email != "info@kidstoylover.com"]
    secret_hits = SECRET_VALUE_RE.findall(text)
    if raw_emails or secret_hits:
        raise ValueError("Sanitized batch customer history lookup payload failed privacy scan.")


def _empty_cache_result():
    return {
        "lookup_cache_saved": False,
        "lookup_cache_paths_written": [],
        "lookup_cache_paths_failed": [],
    }


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()
