import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_last_60_days_candidate_scan_task import (
    REPORT_JSON_PATH as LAST_60_DAYS_SCAN_REPORT_JSON_PATH,
    run_shopify_review_request_last_60_days_candidate_scan_task,
)
from remote_approval.tasks.shopify_review_request_on_demand_customer_history_lookup_task import (
    _apply_self_privacy_assertion,
    _build_payload,
    _persist_lookup_cache,
    _run_protected_lookup,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_batch_customer_history_lookup"
COMMAND_LABEL = "shopify_review_request_batch_customer_history_lookup_read_only"
REPORT_DIR = LOG_DIR / "codex_runs"
REPORT_JSON_PATH = REPORT_DIR / "shopify_review_request_batch_customer_history_lookup.json"
REPORT_HTML_PATH = REPORT_DIR / "shopify_review_request_batch_customer_history_lookup.html"

LIMIT_ENV = "SHOPIFY_REVIEW_REQUEST_BATCH_LOOKUP_LIMIT"
ORDER_FILTER_ENV = "SHOPIFY_REVIEW_REQUEST_BATCH_LOOKUP_ORDER_FILTER"
DRY_RUN_ENV = "SHOPIFY_REVIEW_REQUEST_BATCH_LOOKUP_DRY_RUN"
REQUEST_DELAY_ENV = "SHOPIFY_REVIEW_REQUEST_BATCH_LOOKUP_REQUEST_DELAY_SECONDS"
DEFAULT_LIMIT = 25
DEFAULT_REQUEST_DELAY_SECONDS = 1.0

LIVE_HISTORY_MISSING_REASON = "Customer history needs live Shopify check before sending."
LIVE_HISTORY_STALE_REASON = "Customer history check is stale."
LIVE_HISTORY_FAILED_INCOMPLETE_REASON = "Live customer history check failed or incomplete."
TRUSTPILOT_HISTORY_BLOCK_STATUSES = {"blocked_trustpilot_note", "blocked_trustpilot_tag"}
LIVE_LOOKUP_NEEDED_STATUSES = {"missing", "stale", "incomplete", "blocked_lookup_cache"}
FAILED_INCOMPLETE_STATUSES = {"incomplete", "blocked_lookup_cache"}
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
    r"password\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}"
    r")"
)


def run_shopify_review_request_batch_customer_history_lookup_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    limit = _env_int(LIMIT_ENV, DEFAULT_LIMIT)
    request_delay_seconds = _env_float(REQUEST_DELAY_ENV, DEFAULT_REQUEST_DELAY_SECONDS)
    order_filter = _order_filter()
    preview_only = _env_bool(DRY_RUN_ENV, default=False)

    initial_scan, initial_scan_source = _refresh_candidate_scan()
    base_candidates = _base_candidates_needing_live_lookup(initial_scan, order_filter)
    lookup_groups, skipped_duplicate_customer_count = _dedupe_candidates_by_customer(base_candidates)
    lookup_groups = _prioritize_focus_order(lookup_groups, "#22562")
    limited_groups = lookup_groups[:limit]

    lookup_summaries = []
    lookup_results_by_order = {}
    cache_paths_written = []
    cache_paths_failed = []
    checked_count = 0
    clean_count = 0
    blocked_count = 0
    failed_count = 0
    rate_limited_stop = False

    for index, group in enumerate(limited_groups, start=1):
        lookup_order = group["lookup_order"]
        group_started = time.time()
        if preview_only:
            payload = _preview_lookup_payload(lookup_order)
            cache_result = _empty_cache_result()
        else:
            lookup = _run_protected_lookup(lookup_order)
            payload = _build_payload(
                selected_order=lookup_order,
                lookup=lookup,
                duration_seconds=round(time.time() - group_started, 3),
            )
            payload = _apply_self_privacy_assertion(payload)
            cache_result = _persist_lookup_cache(payload)
            _collect_cache_paths(cache_result, cache_paths_written, cache_paths_failed)

        checked_count += 1
        group_status = _lookup_group_status(payload)
        if group_status == "clean":
            clean_count += 1
        elif group_status == "blocked":
            blocked_count += 1
        else:
            failed_count += 1

        order_cache_results = {lookup_order: cache_result}
        lookup_results_by_order[lookup_order] = payload
        if not preview_only:
            for duplicate_order in group["candidate_orders"]:
                if duplicate_order == lookup_order:
                    continue
                duplicate_payload = _clone_lookup_payload_for_order(payload, duplicate_order)
                duplicate_payload = _apply_self_privacy_assertion(duplicate_payload)
                duplicate_cache_result = _persist_lookup_cache(duplicate_payload)
                _collect_cache_paths(duplicate_cache_result, cache_paths_written, cache_paths_failed)
                order_cache_results[duplicate_order] = duplicate_cache_result
                lookup_results_by_order[duplicate_order] = duplicate_payload

        lookup_summaries.append(
            {
                "index": index,
                "lookup_order": lookup_order,
                "candidate_orders": group["candidate_orders"],
                "customer_key_hash": group["customer_key_hash"],
                "customer_key_source": group["customer_key_source"],
                "group_status": group_status,
                "lookup_status": _safe_text(payload.get("lookup_status"), 120),
                "shopify_customer_history_count": _int_value(payload.get("shopify_customer_history_count")),
                "historical_order_names": _safe_order_names(payload.get("historical_order_names") or []),
                "trustpilot_note_evidence_found": payload.get("trustpilot_note_evidence_found") is True,
                "trustpilot_tag_evidence_found": payload.get("trustpilot_tag_evidence_found") is True,
                "evidence_order_name": _canonical_order_name(payload.get("evidence_order_name")),
                "safe_detected_keyword": _safe_text(payload.get("safe_detected_keyword"), 80),
                "should_block_review_send": payload.get("should_block_review_send") is True,
                "blocking_reason": _safe_text(payload.get("blocking_reason"), 300),
                "full_history_confirmed": payload.get("full_history_confirmed") is True,
                "raw_email_output": False,
                "full_note_output": False,
                "cache_saved_for_orders": [
                    order
                    for order, result in order_cache_results.items()
                    if result.get("lookup_cache_saved") is True
                ],
                "cache_write_failed_for_orders": [
                    order
                    for order, result in order_cache_results.items()
                    if result.get("lookup_cache_saved") is not True
                ],
            }
        )

        if _rate_limited(payload):
            rate_limited_stop = True
            break
        if not preview_only and request_delay_seconds > 0 and index < len(limited_groups):
            time.sleep(request_delay_seconds)

    final_scan, final_scan_source = _refresh_candidate_scan()
    final_lists = _final_lists_from_scan(final_scan)
    focus_22562 = _focus_order_22562(final_scan, lookup_results_by_order)
    payload = {
        "timestamp": utc_now_iso(),
        "generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.32I",
        "mode": "dry-run-read-only-batch-customer-history-lookup",
        "command_label": COMMAND_LABEL,
        "task_status": "rate_limited_stop" if rate_limited_stop else "batch_customer_history_lookup_ready",
        "report_status": "rate_limited_stop" if rate_limited_stop else "batch_customer_history_lookup_ready",
        "success": not rate_limited_stop,
        "preview_only": preview_only,
        "read_only_shopify_lookup_allowed": not preview_only,
        "limit": limit,
        "request_delay_seconds": request_delay_seconds,
        "order_filter": sorted(order_filter),
        "initial_scan_source": initial_scan_source,
        "final_scan_source": final_scan_source,
        "base_candidates_needing_live_check_count": len(base_candidates),
        "customers_to_lookup_count": len(lookup_groups),
        "limited_customer_lookup_count": len(limited_groups),
        "checked_count": checked_count,
        "clean_count": clean_count,
        "blocked_count": blocked_count,
        "blocked_by_trustpilot_history_count": blocked_count,
        "failed_count": failed_count,
        "failed_or_incomplete_count": failed_count,
        "skipped_duplicate_customer_count": skipped_duplicate_customer_count,
        "rate_limited_stop": rate_limited_stop,
        "lookup_results": lookup_summaries,
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
        "focus_22562": focus_22562,
        "cache_paths_written": sorted(set(cache_paths_written)),
        "cache_paths_failed": cache_paths_failed,
        "no_gmail_api_call": True,
        "no_shopify_write": True,
        "no_external_review_api": True,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "translations_register_called": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_email_output": False,
        "raw_customer_email_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "duration_seconds": round(time.time() - started, 3),
    }
    payload["detected_issue_summary"] = _issue_summary(payload)
    payload = _apply_batch_privacy_assertion(payload)
    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _refresh_candidate_scan() -> tuple[dict, str]:
    try:
        run_shopify_review_request_last_60_days_candidate_scan_task("dry-run")
        payload = _read_json(LAST_60_DAYS_SCAN_REPORT_JSON_PATH)
        if payload:
            return payload, "refreshed_last_60_days_candidate_scan"
    except Exception:
        pass
    payload = _read_json(LAST_60_DAYS_SCAN_REPORT_JSON_PATH)
    return payload, "existing_last_60_days_candidate_scan" if payload else "scan_unavailable"


def _base_candidates_needing_live_lookup(scan: dict, order_filter: set[str]) -> list[dict]:
    rows = _scan_rows(scan, "blocked")
    result = []
    for row in rows:
        order = _canonical_order_name(row.get("order") or row.get("order_name"))
        if not order:
            continue
        if order_filter and order not in order_filter:
            continue
        if _row_needs_live_lookup(row):
            result.append(dict(row))
    return result


def _row_needs_live_lookup(row: dict) -> bool:
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
    )
    lowered = reason.lower()
    return (
        LIVE_HISTORY_MISSING_REASON.lower() in lowered
        or LIVE_HISTORY_STALE_REASON.lower() in lowered
        or LIVE_HISTORY_FAILED_INCOMPLETE_REASON.lower() in lowered
    )


def _dedupe_candidates_by_customer(candidates: list[dict]) -> tuple[list[dict], int]:
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


def _prioritize_focus_order(groups: list[dict], order_name: str) -> list[dict]:
    target = _canonical_order_name(order_name)
    if not target:
        return groups
    priority = []
    rest = []
    for group in groups:
        if target in set(group.get("candidate_orders") or []):
            priority.append(group)
        else:
            rest.append(group)
    return priority + rest


def _customer_key(row: dict) -> tuple[str, str]:
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


def _preview_lookup_payload(selected_order: str) -> dict:
    generated_at = utc_now_iso()
    return {
        "timestamp": generated_at,
        "generated_at": generated_at,
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


def _clone_lookup_payload_for_order(payload: dict, selected_order: str) -> dict:
    cloned = dict(payload or {})
    cloned["selected_order"] = selected_order
    cloned["generated_at"] = utc_now_iso()
    cloned["timestamp"] = cloned["generated_at"]
    cloned["batch_lookup_source_order"] = _canonical_order_name((payload or {}).get("selected_order"))
    cloned["batch_lookup_reused_for_duplicate_customer"] = True
    cloned["raw_email_output"] = False
    cloned["full_note_output"] = False
    return cloned


def _lookup_group_status(payload: dict) -> str:
    if payload.get("trustpilot_note_evidence_found") is True or payload.get("trustpilot_tag_evidence_found") is True:
        return "blocked"
    if payload.get("should_block_review_send") is True:
        return "failed_or_incomplete"
    if payload.get("full_history_confirmed") is True:
        return "clean"
    return "failed_or_incomplete"


def _rate_limited(payload: dict) -> bool:
    if _int_value(payload.get("shopify_http_status")) == 429:
        return True
    text = json.dumps(_safe_json_fragment(payload), ensure_ascii=True, sort_keys=True).lower()
    return "429" in text and "shopify" in text


def _final_lists_from_scan(scan: dict) -> dict:
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


def _focus_order_22562(scan: dict, lookup_results_by_order: dict) -> dict:
    row, section = _find_order_row(scan, "#22562")
    lookup = lookup_results_by_order.get("#22562") or {}
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
        "order_name": "#22562",
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
        "evidence_order_name": _safe_text(
            lookup.get("evidence_order_name") or (row or {}).get("trustpilot_note_evidence_order_name"),
            80,
        ),
        "safe_detected_keyword": _safe_text(
            lookup.get("safe_detected_keyword") or (row or {}).get("trustpilot_note_safe_keyword"),
            80,
        ),
    }


def _find_order_row(scan: dict, order_name: str) -> tuple[dict, str]:
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


def _scan_rows(scan: dict, section: str) -> list[dict]:
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


def _row_blocked_by_trustpilot_history(row: dict) -> bool:
    status = _safe_text(row.get("customer_history_lookup_block_status"), 80)
    return bool(
        status in TRUSTPILOT_HISTORY_BLOCK_STATUSES
        or row.get("customer_level_trustpilot_already_sent") is True
        or row.get("customer_level_trustpilot_note_evidence_found") is True
        or "previous trustpilot" in _safe_text(row.get("block_reason"), 500).lower()
    )


def _row_failed_or_incomplete_lookup(row: dict) -> bool:
    status = _safe_text(row.get("customer_history_lookup_block_status"), 80)
    if status in FAILED_INCOMPLETE_STATUSES and not _row_blocked_by_trustpilot_history(row):
        return True
    reason = _safe_text(row.get("block_reason") or row.get("reason"), 500).lower()
    return LIVE_HISTORY_FAILED_INCOMPLETE_REASON.lower() in reason


def _row_still_needs_live_lookup(row: dict) -> bool:
    status = _safe_text(row.get("customer_history_lookup_block_status"), 80)
    if status in {"missing", "stale"}:
        return True
    reason = _safe_text(row.get("block_reason") or row.get("reason"), 500).lower()
    return LIVE_HISTORY_MISSING_REASON.lower() in reason or LIVE_HISTORY_STALE_REASON.lower() in reason


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "status": payload.get("task_status"),
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "review_file_path": str(json_path),
        "json_report_path": str(json_path),
        "html_report_path": str(html_path),
        "task_status": payload.get("task_status"),
        "base_candidates_needing_live_check_count": payload.get("base_candidates_needing_live_check_count", 0),
        "customers_to_lookup_count": payload.get("customers_to_lookup_count", 0),
        "checked_count": payload.get("checked_count", 0),
        "clean_count": payload.get("clean_count", 0),
        "blocked_by_trustpilot_history_count": payload.get("blocked_by_trustpilot_history_count", 0),
        "failed_or_incomplete_count": payload.get("failed_or_incomplete_count", 0),
        "skipped_duplicate_customer_count": payload.get("skipped_duplicate_customer_count", 0),
        "final_eligible_count_after_lookup": payload.get("final_eligible_count_after_lookup", 0),
        "focus_22562": payload.get("focus_22562") or {},
        "cache_paths_written": payload.get("cache_paths_written") or [],
        "cache_paths_failed": payload.get("cache_paths_failed") or [],
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "raw_email_output": False,
        "full_note_output": False,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    focus = payload.get("focus_22562") or {}
    return (
        "Batch Shopify customer history lookup completed.\n"
        f"Status: {payload.get('task_status')}\n"
        f"Base candidates needing live check: {payload.get('base_candidates_needing_live_check_count', 0)}\n"
        f"Customers to lookup: {payload.get('customers_to_lookup_count', 0)}\n"
        f"Checked: {payload.get('checked_count', 0)}\n"
        f"Clean: {payload.get('clean_count', 0)}\n"
        f"Blocked by Trustpilot history: {payload.get('blocked_by_trustpilot_history_count', 0)}\n"
        f"Failed/incomplete: {payload.get('failed_or_incomplete_count', 0)}\n"
        f"Skipped duplicate customers: {payload.get('skipped_duplicate_customer_count', 0)}\n"
        f"Final eligible after lookup: {payload.get('final_eligible_count_after_lookup', 0)}\n"
        f"#22562 lookup performed: {focus.get('live_lookup_performed')}\n"
        f"#22562 final section: {focus.get('final_section')}\n"
        f"#22562 final eligibility: {focus.get('final_eligibility')}\n"
        f"#22562 blocker: {focus.get('blocker') or '-'}\n"
        f"Cache paths written: {', '.join(payload.get('cache_paths_written') or []) or '-'}\n"
        "Safety: read-only Shopify lookup only; no Shopify write, no tag mutation, no Gmail API/send, "
        "no external review API, no raw email, no full note output.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "0 = stop"
    )


def _write_json(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2, sort_keys=True)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html(payload: dict) -> str:
    focus = payload.get("focus_22562") or {}
    final_orders = ", ".join(payload.get("final_eligible_orders") or []) or "-"
    blocked_orders = ", ".join(payload.get("blocked_by_historical_trustpilot_evidence_orders") or []) or "-"
    failed_orders = ", ".join(payload.get("blocked_live_lookup_failed_or_incomplete_orders") or []) or "-"
    needs_orders = ", ".join(payload.get("still_needs_live_customer_history_check_orders") or []) or "-"
    cache_paths = ", ".join(payload.get("cache_paths_written") or []) or "-"
    lookup_rows = "\n".join(
        "<tr>"
        f"<td>{escape(str(row.get('lookup_order', '')))}</td>"
        f"<td>{escape(', '.join(row.get('candidate_orders') or []))}</td>"
        f"<td>{escape(str(row.get('group_status', '')))}</td>"
        f"<td>{escape(str(row.get('shopify_customer_history_count', 0)))}</td>"
        f"<td>{escape(str(row.get('evidence_order_name') or '-'))}</td>"
        f"<td>{escape(str(row.get('safe_detected_keyword') or '-'))}</td>"
        f"<td>{escape(str(row.get('blocking_reason') or '-'))}</td>"
        "</tr>"
        for row in payload.get("lookup_results") or []
    )
    if not lookup_rows:
        lookup_rows = '<tr><td colspan="7">No lookup rows.</td></tr>'
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Batch Shopify Customer History Lookup</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Batch Shopify Customer History Lookup</h1>
  <p class="warning">Read-only lookup. No Gmail send, no Shopify write, no tag mutation, no external review API call, no raw email, and no full note output.</p>
  <table><tbody>
    <tr><th>Status</th><td>{escape(str(payload.get('task_status', '')))}</td></tr>
    <tr><th>Base candidates needing live check</th><td>{escape(str(payload.get('base_candidates_needing_live_check_count', 0)))}</td></tr>
    <tr><th>Customers to lookup</th><td>{escape(str(payload.get('customers_to_lookup_count', 0)))}</td></tr>
    <tr><th>Checked</th><td>{escape(str(payload.get('checked_count', 0)))}</td></tr>
    <tr><th>Clean</th><td>{escape(str(payload.get('clean_count', 0)))}</td></tr>
    <tr><th>Blocked by Trustpilot history</th><td>{escape(str(payload.get('blocked_by_trustpilot_history_count', 0)))}</td></tr>
    <tr><th>Failed/incomplete</th><td>{escape(str(payload.get('failed_or_incomplete_count', 0)))}</td></tr>
    <tr><th>Skipped duplicate customers</th><td>{escape(str(payload.get('skipped_duplicate_customer_count', 0)))}</td></tr>
    <tr><th>Final eligible after lookup</th><td>{escape(str(payload.get('final_eligible_count_after_lookup', 0)))}</td></tr>
    <tr><th>Final eligible orders</th><td>{escape(final_orders)}</td></tr>
    <tr><th>Blocked by history</th><td>{escape(blocked_orders)}</td></tr>
    <tr><th>Failed/incomplete orders</th><td>{escape(failed_orders)}</td></tr>
    <tr><th>Still need live check</th><td>{escape(needs_orders)}</td></tr>
    <tr><th>Cache paths written</th><td>{escape(cache_paths)}</td></tr>
  </tbody></table>
  <h2>#22562</h2>
  <table><tbody>
    <tr><th>Live lookup performed</th><td>{escape(str(focus.get('live_lookup_performed')))}</td></tr>
    <tr><th>Lookup status</th><td>{escape(str(focus.get('lookup_status') or '-'))}</td></tr>
    <tr><th>Final section</th><td>{escape(str(focus.get('final_section') or '-'))}</td></tr>
    <tr><th>Final eligibility</th><td>{escape(str(focus.get('final_eligibility') or '-'))}</td></tr>
    <tr><th>Review &amp; Send readiness</th><td>{escape(str(focus.get('review_send_ready') is True))}</td></tr>
    <tr><th>Blocker</th><td>{escape(str(focus.get('blocker') or '-'))}</td></tr>
  </tbody></table>
  <h2>Lookup Results</h2>
  <table>
    <thead><tr><th>Lookup order</th><th>Candidate orders</th><th>Status</th><th>History count</th><th>Evidence order</th><th>Safe keyword</th><th>Blocking reason</th></tr></thead>
    <tbody>{lookup_rows}</tbody>
  </table>
</body>
</html>"""


def _issue_summary(payload: dict) -> str:
    return (
        "Batch customer history lookup "
        f"checked {payload.get('checked_count', 0)} customer group(s), "
        f"clean={payload.get('clean_count', 0)}, "
        f"blocked_by_history={payload.get('blocked_by_trustpilot_history_count', 0)}, "
        f"failed_or_incomplete={payload.get('failed_or_incomplete_count', 0)}, "
        f"final_eligible={payload.get('final_eligible_count_after_lookup', 0)}. "
        "No Shopify write, tag mutation, Gmail API/send, external review API call, raw email output, or full note output."
    )


def _apply_batch_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = [email for email in EMAIL_RE.findall(text) if "***" not in email and email != "info@kidstoylover.com"]
    secret_hits = SECRET_VALUE_RE.findall(text)
    payload["self_privacy_scan"] = {
        "raw_customer_email_count": len(set(raw_emails)),
        "token_secret_pattern_count": len(secret_hits),
    }
    if raw_emails or secret_hits:
        payload["task_status"] = "blocked_privacy_scan_failed"
        payload["report_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["raw_email_output"] = bool(raw_emails)
        payload["secrets_output"] = bool(secret_hits)
        payload["detected_issue_summary"] = "Batch customer history lookup privacy scan failed."
    return payload


def _empty_cache_result() -> dict:
    return {
        "lookup_cache_saved": False,
        "lookup_cache_paths_written": [],
        "lookup_cache_paths_failed": [],
    }


def _collect_cache_paths(cache_result: dict, paths_written: list[str], paths_failed: list[dict]) -> None:
    for path in cache_result.get("lookup_cache_paths_written") or []:
        if path not in paths_written:
            paths_written.append(path)
    for item in cache_result.get("lookup_cache_paths_failed") or []:
        if item not in paths_failed:
            paths_failed.append(item)


def _read_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _order_filter() -> set[str]:
    raw = os.environ.get(ORDER_FILTER_ENV, "")
    values = re.split(r"[\s,;]+", raw)
    return {_canonical_order_name(value) for value in values if _canonical_order_name(value)}


def _env_int(name: str, default: int) -> int:
    try:
        value = int(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(value, 1)


def _env_float(name: str, default: float) -> float:
    try:
        value = float(os.environ.get(name, "") or default)
    except (TypeError, ValueError):
        return default
    return max(value, 0.0)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


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
    text = str(value or "")
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = EMAIL_RE.sub("[masked-email]", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", text).strip()
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def _int_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _hash_text(value: str) -> str:
    return hashlib.sha256(_safe_text(value, 500).encode("utf-8")).hexdigest()[:16]


def _safe_json_fragment(value):
    if isinstance(value, dict):
        return {str(key): _safe_json_fragment(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_safe_json_fragment(item) for item in value]
    return _safe_text(value)
