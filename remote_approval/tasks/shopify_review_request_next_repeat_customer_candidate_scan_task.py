import json
import re
import time
from collections import Counter
from html import escape
from pathlib import Path

from remote_approval.tasks.shopify_review_request_customer_level_duplicate_suppression import (
    CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
    build_customer_level_duplicate_context,
    evaluate_customer_level_duplicate,
    public_context_summary,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_next_repeat_customer_candidate_scan"
COMMAND_LABEL = "shopify_review_request_next_repeat_customer_candidate_scan_local_reports_only"

SOURCE_CANDIDATE_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_candidate_scan.json"
SOURCE_UNIFIED_DECISION_JSON_PATH = LOG_DIR / "shopify_review_request_unified_decision_engine_dry_run.json"
SOURCE_COMPLETION_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_completion_next_batch_design.json"
SOURCE_SUPPRESS_ALI_REVIEWS_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_suppress_ali_reviews_design.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_next_repeat_customer_candidate_scan.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_next_repeat_customer_candidate_scan.html"

SUCCESS_STATUS = "next_repeat_customer_candidate_scan_ready"
NO_CANDIDATE_STATUS = "blocked_no_safe_repeat_customer_candidate_found"
SOURCE_BLOCKED_STATUS = "blocked_missing_or_invalid_source_report"
COUNT_SEMANTICS_INVALID_STATUS = "blocked_invalid_next_candidate_count_semantics"

CANONICAL_TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]
DEFAULT_COMPLETED_ORDER_NAMES = ["#22621"]
ALLOWED_REPORT_EMAILS = {"info@kidstoylover.com"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"shpat_[A-Za-z0-9_]+"),
    re.compile(r"(?i)access[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)refresh[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)client[_\s-]?secret\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
]


def run_shopify_review_request_next_repeat_customer_candidate_scan_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    sources, source_errors = _load_sources()
    source_status = _source_report_status(sources, source_errors)
    completed_order_names = _completed_order_names(sources)
    rows = _merged_order_rows(sources)
    customer_duplicate_context = build_customer_level_duplicate_context(
        [_row_order_name(row) for row in rows],
        extra_rows=[(row.get("candidate_scan_order") or {}) for row in rows]
        + [(row.get("unified_decision") or {}) for row in rows],
    )
    evaluated_rows = [
        _evaluate_order(row, completed_order_names, index, customer_duplicate_context)
        for index, row in enumerate(rows, start=1)
    ]
    ready_candidates = [
        row
        for row in evaluated_rows
        if row["candidate_status"] == "ready_next_trustpilot_repeat_customer_candidate"
    ]
    blocking_conditions = _blocking_conditions(source_status)
    status = _status(blocking_conditions, ready_candidates)
    payload = _build_payload(
        source_status=source_status,
        completed_order_names=completed_order_names,
        evaluated_rows=evaluated_rows,
        ready_candidates=ready_candidates,
        blocking_conditions=blocking_conditions,
        customer_duplicate_context=customer_duplicate_context,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_sources() -> tuple[dict, dict]:
    source_paths = {
        "candidate_scan": SOURCE_CANDIDATE_SCAN_JSON_PATH,
        "unified_decision_engine": SOURCE_UNIFIED_DECISION_JSON_PATH,
        "trustpilot_completion_next_batch_design": SOURCE_COMPLETION_JSON_PATH,
        "trustpilot_suppress_ali_reviews_design": SOURCE_SUPPRESS_ALI_REVIEWS_JSON_PATH,
    }
    sources = {}
    errors = {}
    for name, path in source_paths.items():
        if not path.exists():
            errors[name] = "missing_source_report"
            continue
        try:
            sources[name] = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors[name] = _sanitize_text(f"source_report_json_parse_error: {exc}")
    return sources, errors


def _source_report_status(sources: dict, source_errors: dict) -> dict:
    expected = {
        "candidate_scan": {
            "path": str(SOURCE_CANDIDATE_SCAN_JSON_PATH),
            "required": True,
            "task_name": "shopify_review_request_candidate_scan",
            "status_key": "report_status",
            "ready": lambda data: data.get("task_name") == "shopify_review_request_candidate_scan"
            and data.get("success") is True
            and str(data.get("phase")) == "1.1",
        },
        "unified_decision_engine": {
            "path": str(SOURCE_UNIFIED_DECISION_JSON_PATH),
            "required": True,
            "task_name": "shopify_review_request_unified_decision_engine_dry_run",
            "status_key": "decision_engine_status",
            "ready": lambda data: data.get("task_name") == "shopify_review_request_unified_decision_engine_dry_run"
            and data.get("success") is True
            and data.get("decision_engine_status") == "decision_engine_dry_run_ready",
        },
        "trustpilot_completion_next_batch_design": {
            "path": str(SOURCE_COMPLETION_JSON_PATH),
            "required": False,
            "task_name": "shopify_review_request_trustpilot_completion_next_batch_design",
            "status_key": "completion_next_batch_design_status",
            "ready": lambda data: data.get("task_name") == "shopify_review_request_trustpilot_completion_next_batch_design"
            and data.get("success") is True,
        },
        "trustpilot_suppress_ali_reviews_design": {
            "path": str(SOURCE_SUPPRESS_ALI_REVIEWS_JSON_PATH),
            "required": False,
            "task_name": "shopify_review_request_trustpilot_suppress_ali_reviews_design",
            "status_key": "trustpilot_suppress_ali_reviews_design_status",
            "ready": lambda data: data.get("task_name") == "shopify_review_request_trustpilot_suppress_ali_reviews_design"
            and data.get("success") is True,
        },
    }
    status = {}
    for name, meta in expected.items():
        data = sources.get(name) or {}
        error = source_errors.get(name, "")
        present = not error
        task_matches = data.get("task_name") == meta["task_name"]
        ready = present and bool(meta["ready"](data))
        status[name] = {
            "path": meta["path"],
            "required": meta["required"],
            "present": present,
            "task_name": _safe_text(data.get("task_name", "")),
            "task_name_matches": task_matches,
            "status": _safe_text(data.get(meta["status_key"], "")),
            "success": data.get("success") is True,
            "ready": ready,
            "error_sanitized": _sanitize_text(error),
        }
    return status


def _completed_order_names(sources: dict) -> list[str]:
    names = list(DEFAULT_COMPLETED_ORDER_NAMES)
    for source_name in ("trustpilot_completion_next_batch_design", "trustpilot_suppress_ali_reviews_design"):
        source = sources.get(source_name) or {}
        name = _safe_text(source.get("selected_order_name", ""))
        if name:
            names.append(name)
    return _dedupe(names)


def _merged_order_rows(sources: dict) -> list[dict]:
    candidate_orders = [
        item
        for item in ((sources.get("candidate_scan") or {}).get("orders") or [])
        if isinstance(item, dict)
    ]
    decisions = [
        item
        for item in ((sources.get("unified_decision_engine") or {}).get("decisions") or [])
        if isinstance(item, dict)
    ]
    rows = []
    indexes = {}
    for order in candidate_orders:
        row = {"candidate_scan_order": order, "unified_decision": {}}
        rows.append(row)
        for key in _order_keys(order):
            indexes.setdefault(key, row)
    for decision in decisions:
        row = next((indexes[key] for key in _order_keys(decision) if key in indexes), None)
        if row is None:
            row = {"candidate_scan_order": {}, "unified_decision": decision}
            rows.append(row)
            for key in _order_keys(decision):
                indexes.setdefault(key, row)
        else:
            row["unified_decision"] = decision
    return rows


def _order_keys(row: dict) -> list[str]:
    keys = []
    for key in ("order_name", "order_id", "order_id_or_gid", "id"):
        value = _safe_text(row.get(key, ""))
        if value:
            keys.append(f"{key}:{value.lower()}")
    name = _safe_text(row.get("order_name", ""))
    if name:
        keys.append(f"name:{name.lower()}")
    return _dedupe(keys)


def _row_order_name(row: dict) -> str:
    order = row.get("candidate_scan_order") or {}
    decision = row.get("unified_decision") or {}
    return _safe_text(order.get("order_name") or decision.get("order_name") or "")


def _evaluate_order(row: dict, completed_order_names: list[str], source_index: int, customer_duplicate_context: dict) -> dict:
    order = row.get("candidate_scan_order") or {}
    decision = row.get("unified_decision") or {}
    order_name = _safe_text(order.get("order_name") or decision.get("order_name") or "")
    order_id = _safe_text(order.get("order_id") or decision.get("order_id_or_gid") or "")
    masked_email = _safe_masked_email(order.get("masked_email") or decision.get("masked_email") or "")
    tags = _collect_tags(order, decision)
    matched_trustpilot_tags = _matched_trustpilot_tags(order, decision, tags)
    source_decision = _safe_text(decision.get("decision", ""))
    classification_buckets = [
        _safe_text(bucket)
        for bucket in order.get("classification_buckets", [])
        if _safe_text(bucket)
    ]
    repeat_customer_detected = bool(
        order.get("repeat_customer_detected")
        or decision.get("repeat_customer_detected")
        or source_decision == "trustpilot_gmail_candidate_dry_run"
    )
    ticket_risk = _has_ticket_risk(order, decision)
    customer_level_duplicate = evaluate_customer_level_duplicate(
        order_name,
        masked_email,
        customer_duplicate_context,
    )
    block_reasons = _candidate_block_reasons(
        order_name=order_name,
        completed_order_names=completed_order_names,
        masked_email=masked_email,
        tags=tags,
        matched_trustpilot_tags=matched_trustpilot_tags,
        source_decision=source_decision,
        classification_buckets=classification_buckets,
        repeat_customer_detected=repeat_customer_detected,
        ticket_risk=ticket_risk,
        order=order,
        customer_level_duplicate=customer_level_duplicate,
    )
    ready = not block_reasons
    classification = (
        CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION
        if customer_level_duplicate["customer_level_duplicate_block_applies"]
        else ("ready_next_trustpilot_repeat_customer_candidate" if ready else "blocked")
    )
    return {
        "source_index": source_index,
        "order_name": order_name,
        "order_id_or_gid": order_id,
        "masked_email": masked_email,
        "email_present": bool(masked_email and "***@" in masked_email),
        "email_masking_applied": True,
        "repeat_customer_detected": repeat_customer_detected,
        "source_decision": source_decision,
        "classification_buckets": classification_buckets,
        "tags_of_interest": _tags_of_interest(tags),
        "matched_trustpilot_invitation_tags": matched_trustpilot_tags,
        "existing_trustpilot_invitation_tag_detected": bool(matched_trustpilot_tags),
        "ticket_risk_detected": ticket_risk,
        "candidate_status": "ready_next_trustpilot_repeat_customer_candidate" if ready else "blocked",
        "classification": classification,
        "customer_level_duplicate_block_applies": customer_level_duplicate[
            "customer_level_duplicate_block_applies"
        ],
        "prior_trustpilot_invitation_detected": customer_level_duplicate[
            "prior_trustpilot_invitation_detected"
        ],
        "prior_trustpilot_order_name": customer_level_duplicate["prior_trustpilot_order_name"],
        "customer_level_duplicate_match_basis": customer_level_duplicate[
            "same_customer_detection_basis"
        ],
        "same_customer_detected": customer_level_duplicate["same_customer_detected"],
        "same_email_detected": customer_level_duplicate["same_email_detected"],
        "same_masked_email_detected": customer_level_duplicate["same_masked_email_detected"],
        "blocking_reasons": block_reasons,
        "planned_action": "report_candidate_only_no_draft_no_send_no_tag_write" if ready else "do_not_contact",
        "future_write_tag_if_later_approved": CANONICAL_TRUSTPILOT_TAG if ready else "",
        "gmail_draft_planned": False,
        "email_send_planned": False,
        "shopify_tag_write_planned": False,
        "kudosi_or_ali_reviews_call_planned": False,
    }


def _collect_tags(order: dict, decision: dict) -> list[str]:
    tags = []
    for value in order.get("tags", []) or []:
        tags.append(_safe_text(value))
    tag_summary = decision.get("safe_tags_summary") if isinstance(decision.get("safe_tags_summary"), dict) else {}
    for key in ("tags_of_interest", "matched_trustpilot_invitation_tags", "safe_tags", "exact_tags_of_interest"):
        for value in tag_summary.get(key, []) or []:
            tags.append(_safe_text(value))
    for key in ("matched_trustpilot_invitation_tags", "customer_history_tags", "customer_order_tags", "historical_order_tags"):
        for value in decision.get(key, []) or []:
            tags.append(_safe_text(value))
    return [tag for tag in _dedupe(tags) if tag]


def _matched_trustpilot_tags(order: dict, decision: dict, tags: list[str]) -> list[str]:
    matched = _matched_trustpilot_tags_from_tags(tags)
    for source in (order, decision):
        if source.get("existing_trustpilot_invitation_tag_detected") is True:
            matched.append("trustpilot_alias_present_in_source_summary")
        if source.get("customer_historical_trustpilot_tag_detected") is True:
            matched.append("trustpilot_alias_present_in_customer_history")
        if source.get("contains_trustpilot_alias") is True:
            matched.append("trustpilot_alias_present_in_source_summary")
    tag_summary = decision.get("safe_tags_summary") if isinstance(decision.get("safe_tags_summary"), dict) else {}
    if tag_summary.get("contains_trustpilot_alias") is True:
        matched.append("trustpilot_alias_present_in_source_summary")
    for value in decision.get("matched_trustpilot_invitation_tags", []) or []:
        matched.append(_safe_text(value))
    return sorted(set(_safe_text(tag) for tag in matched if _safe_text(tag)))


def _candidate_block_reasons(
    order_name: str,
    completed_order_names: list[str],
    masked_email: str,
    tags: list[str],
    matched_trustpilot_tags: list[str],
    source_decision: str,
    classification_buckets: list[str],
    repeat_customer_detected: bool,
    ticket_risk: bool,
    order: dict,
    customer_level_duplicate: dict,
) -> list[str]:
    reasons = []
    tag_set = set(tags)
    if order_name in completed_order_names:
        reasons.append("completed_trustpilot_order_already_processed")
    if matched_trustpilot_tags or source_decision == "blocked_existing_trustpilot_invitation_tag":
        reasons.append("existing_trustpilot_invitation_tag_or_alias_detected")
    if customer_level_duplicate.get("customer_level_duplicate_block_applies") is True:
        reasons.append(CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION)
    if not repeat_customer_detected:
        reasons.append("repeat_customer_not_confirmed")
    if not masked_email or "***@" not in masked_email:
        reasons.append("masked_email_missing")
    if source_decision and source_decision != "trustpilot_gmail_candidate_dry_run":
        reasons.append(f"source_decision_{source_decision}")
    if _has_any_bucket(classification_buckets, {"blocked_cancelled", "blocked_refunded_or_partially_refunded"}):
        reasons.append("refund_cancel_or_dispute_risk")
    if _has_any_bucket(classification_buckets, {"blocked_returned_package", "blocked_shipping_or_delivery_issue"}):
        reasons.append("return_or_shipping_issue_risk")
    if ticket_risk:
        reasons.append("ticket_risk_detected")
    if _has_returned_package_tag(tags):
        reasons.append("returned_package_tag_detected")
    if _has_risk_tag(tags):
        reasons.append("risk_tag_detected")
    if "Review sent" in tag_set:
        reasons.append("ali_reviews_review_sent_tag_present")
    if order.get("ticket_status") in {"ticket_blocked", "ticket_match_detected"} and order.get("ticket_blocked") is True:
        reasons.append("ticket_blocked_in_candidate_scan")
    return _dedupe(reasons)


def _has_ticket_risk(order: dict, decision: dict) -> bool:
    if order.get("ticket_blocked") is True:
        return True
    if decision.get("decision") == "blocked_ticket_risk":
        return True
    risk_categories = set(_safe_text(value) for value in order.get("ticket_risk_categories", []))
    risk = decision.get("risk_summary") if isinstance(decision.get("risk_summary"), dict) else {}
    risk_categories.update(_safe_text(value) for value in risk.get("ticket_risk_categories", []))
    if risk.get("ticket_blocked") is True or risk.get("ticket_match_detected") is True and risk_categories:
        return True
    return bool(risk_categories.intersection({"refund", "shipping_issue", "complaint", "dispute", "chargeback"}))


def _blocking_conditions(source_status: dict) -> list[dict]:
    conditions = []
    for name, status in source_status.items():
        if status["required"] and not status["ready"]:
            conditions.append(
                {
                    "status": SOURCE_BLOCKED_STATUS,
                    "detail": f"{name} is required but not ready: {status.get('error_sanitized') or status.get('status') or 'unknown'}",
                }
            )
    return conditions


def _status(blocking_conditions: list[dict], ready_candidates: list[dict]) -> str:
    if blocking_conditions:
        return SOURCE_BLOCKED_STATUS
    if ready_candidates:
        return SUCCESS_STATUS
    return NO_CANDIDATE_STATUS


def _build_payload(
    source_status: dict,
    completed_order_names: list[str],
    evaluated_rows: list[dict],
    ready_candidates: list[dict],
    blocking_conditions: list[dict],
    customer_duplicate_context: dict,
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary()
    selected_candidate = ready_candidates[0] if ready_candidates and not blocking_conditions else {}
    eligible_candidate_count = len(ready_candidates)
    next_candidate_count = 1 if selected_candidate else 0
    count_semantics_validation = _count_semantics_validation(
        next_candidate_selected=bool(selected_candidate),
        next_candidate_count=next_candidate_count,
    )
    if not count_semantics_validation["valid"]:
        status = COUNT_SEMANTICS_INVALID_STATUS
        blocking_conditions = [
            *blocking_conditions,
            {
                "status": COUNT_SEMANTICS_INVALID_STATUS,
                "detail": "; ".join(count_semantics_validation["errors"]),
            },
        ]
    blocked_counts = Counter(
        reason
        for row in evaluated_rows
        for reason in row.get("blocking_reasons", [])
    )
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "4.0",
        "mode": "local-report-only-next-repeat-customer-candidate-scan",
        "command_label": COMMAND_LABEL,
        "next_repeat_customer_candidate_scan_status": status,
        "success": status == SUCCESS_STATUS,
        "local_source_reports_only": True,
        "shopify_live_query_allowed": False,
        "shopify_live_query_performed": False,
        "completed_order_names_excluded": completed_order_names,
        "source_report_status": source_status,
        "total_orders_evaluated": len(evaluated_rows),
        "total_candidates_seen": eligible_candidate_count,
        "eligible_candidate_count": eligible_candidate_count,
        "eligible_repeat_customer_candidate_count": eligible_candidate_count,
        "next_candidate_selected": bool(selected_candidate),
        "next_candidate_count": next_candidate_count,
        "next_candidate_order_name": selected_candidate.get("order_name", ""),
        "next_candidate_masked_email": selected_candidate.get("masked_email", ""),
        "candidate_selected_count": next_candidate_count,
        "selected_candidate": selected_candidate,
        "selected_order_name": selected_candidate.get("order_name", ""),
        "selected_masked_email": selected_candidate.get("masked_email", ""),
        "already_completed_orders": [
            {"order_name": name, "reason": "already_completed_trustpilot_workflow"}
            for name in completed_order_names
        ],
        "ready_candidate_queue": ready_candidates[:10],
        "evaluated_orders": evaluated_rows[:150],
        "blocked_counts": dict(sorted(blocked_counts.items())),
        "customer_level_duplicate_summary": public_context_summary(customer_duplicate_context),
        "trustpilot_tag_matching_policy": {
            "canonical_write_tag_for_future_real_write_only": CANONICAL_TRUSTPILOT_TAG,
            "current_task_write_tag": "",
            "future_real_writes_must_use_exact_canonical_tag": True,
            "duplicate_detection_uses_tolerant_alias_matching": True,
            "customer_level_duplicate_suppression_enabled": True,
            "customer_level_duplicate_classification": CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
            "legacy_tags_are_not_removed": True,
            **_trustpilot_alias_coverage(),
        },
        "safe_output_policy": {
            "masked_email_only": True,
            "raw_email_output": False,
            "phone_output": False,
            "address_output": False,
            "ticket_body_output": False,
            "ticket_comments_output": False,
            "private_customer_notes_output": False,
        },
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "count_semantics_validation": count_semantics_validation,
        "safety_summary": safety,
        **safety,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_next_repeat_customer_candidate_scan_path": str(REPORT_JSON_PATH),
        "html_next_repeat_customer_candidate_scan_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, selected_candidate, ready_candidates, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _count_semantics_validation(next_candidate_selected: bool, next_candidate_count: int) -> dict:
    errors = []
    if next_candidate_count > 1:
        errors.append("next_candidate_count_must_not_exceed_one")
    if next_candidate_selected and next_candidate_count != 1:
        errors.append("selected_candidate_requires_next_candidate_count_one")
    if not next_candidate_selected and next_candidate_count != 0:
        errors.append("no_selected_candidate_requires_next_candidate_count_zero")
    return {
        "valid": not errors,
        "errors": errors,
        "next_candidate_selected": next_candidate_selected,
        "next_candidate_count": next_candidate_count,
        "max_next_candidate_count": 1,
    }


def _safety_summary() -> dict:
    return {
        "shopify_api_call_performed": False,
        "read_only_shopify_query_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_oauth_token_exchange_performed": False,
        "gmail_draft_created": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_next_repeat_customer_candidate_scan_path": str(json_path),
        "html_next_repeat_customer_candidate_scan_path": str(html_path),
        "next_repeat_customer_candidate_scan_status": payload["next_repeat_customer_candidate_scan_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "candidate_selected_count": payload["candidate_selected_count"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "eligible_repeat_customer_candidate_count": payload["eligible_repeat_customer_candidate_count"],
        "next_candidate_selected": payload["next_candidate_selected"],
        "next_candidate_count": payload["next_candidate_count"],
        "total_candidates_seen": payload["total_candidates_seen"],
        "total_orders_evaluated": payload["total_orders_evaluated"],
        "blocked_counts": payload["blocked_counts"],
        "blocking_condition_count": payload["blocking_condition_count"],
        "blocking_conditions": payload["blocking_conditions"],
        **payload["safety_summary"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    source_rows = "\n".join(
        f"<tr><td>{escape(name)}</td><td>{escape(str(status.get('required')))}</td><td>{escape(str(status.get('ready')))}</td><td>{escape(str(status.get('status')))}</td><td>{escape(str(status.get('error_sanitized')))}</td></tr>"
        for name, status in payload["source_report_status"].items()
    )
    selected = payload.get("selected_candidate") or {}
    selected_rows = _render_candidate_rows([selected]) if selected else '<tr><td colspan="8">No candidate selected.</td></tr>'
    queue_rows = _render_candidate_rows(payload.get("ready_candidate_queue", []))
    if not queue_rows:
        queue_rows = '<tr><td colspan="8">No ready candidates found.</td></tr>'
    evaluated_rows = _render_candidate_rows(payload.get("evaluated_orders", []), include_blocking=True)
    if not evaluated_rows:
        evaluated_rows = '<tr><td colspan="8">No evaluated rows available.</td></tr>'
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    alias_rows = "\n".join(
        f"<tr><td><code>{escape(alias)}</code></td><td><code>{escape(_normalize_tag(alias))}</code></td></tr>"
        for alias in payload["trustpilot_tag_matching_policy"]["configured_aliases"]
    )
    blocking_rows = "\n".join(
        f"<tr><td>{escape(item.get('status', ''))}</td><td>{escape(item.get('detail', ''))}</td></tr>"
        for item in payload["blocking_conditions"]
    ) or "<tr><td colspan=\"2\">None</td></tr>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Next Repeat Customer Candidate Scan</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #2563eb; background: #eff6ff; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Next Repeat Customer Candidate Scan</h1>
  <p class="warning">Phase 4.0 is local-report-only. It does not call Shopify, Gmail, Kudosi, Ali Reviews, or write Shopify tags.</p>
  <p>Status: <strong>{escape(payload["next_repeat_customer_candidate_scan_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload.get("selected_order_name", ""))}</code></p>
  <p>Selected masked email: <code>{escape(payload.get("selected_masked_email", ""))}</code></p>
  <p>Ready candidates: {int(payload.get("total_candidates_seen") or 0)} | Evaluated orders: {int(payload.get("total_orders_evaluated") or 0)}</p>
  <h2>Source Reports</h2>
  <table><thead><tr><th>Source</th><th>Required</th><th>Ready</th><th>Status</th><th>Error</th></tr></thead><tbody>{source_rows}</tbody></table>
  <h2>Selected Candidate</h2>
  <table><thead><tr><th>Order</th><th>Masked email</th><th>Repeat</th><th>Source decision</th><th>Candidate status</th><th>Tags of interest</th><th>Trustpilot matches</th><th>Blocking reasons</th></tr></thead><tbody>{selected_rows}</tbody></table>
  <h2>Ready Candidate Queue</h2>
  <table><thead><tr><th>Order</th><th>Masked email</th><th>Repeat</th><th>Source decision</th><th>Candidate status</th><th>Tags of interest</th><th>Trustpilot matches</th><th>Blocking reasons</th></tr></thead><tbody>{queue_rows}</tbody></table>
  <h2>Evaluated Orders</h2>
  <table><thead><tr><th>Order</th><th>Masked email</th><th>Repeat</th><th>Source decision</th><th>Candidate status</th><th>Tags of interest</th><th>Trustpilot matches</th><th>Blocking reasons</th></tr></thead><tbody>{evaluated_rows}</tbody></table>
  <h2>Trustpilot Alias Matching</h2>
  <table><thead><tr><th>Alias</th><th>Normalized form</th></tr></thead><tbody>{alias_rows}</tbody></table>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


def _render_candidate_rows(rows: list[dict], include_blocking: bool = False) -> str:
    rendered = []
    for row in rows:
        if not row:
            continue
        tags = ", ".join(f"<code>{escape(str(tag))}</code>" for tag in row.get("tags_of_interest", []))
        matches = ", ".join(
            f"<code>{escape(str(tag))}</code>"
            for tag in row.get("matched_trustpilot_invitation_tags", [])
        )
        blocking = ", ".join(str(reason) for reason in row.get("blocking_reasons", [])) if include_blocking else ""
        rendered.append(
            f"<tr><td>{escape(str(row.get('order_name', '')))}<br><code>{escape(str(row.get('order_id_or_gid', '')))}</code></td>"
            f"<td>{escape(str(row.get('masked_email', '')))}</td>"
            f"<td>{escape(str(row.get('repeat_customer_detected')))}</td>"
            f"<td><code>{escape(str(row.get('source_decision', '')))}</code></td>"
            f"<td><code>{escape(str(row.get('candidate_status', '')))}</code></td>"
            f"<td>{tags}</td><td>{matches}</td><td>{escape(blocking)}</td></tr>"
        )
    return "\n".join(rendered)


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 4.0 next repeat-customer candidate scan finished.\n"
        f"Status: {payload.get('next_repeat_customer_candidate_scan_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Ready candidates: {payload.get('total_candidates_seen')}\n"
        f"Evaluated orders: {payload.get('total_orders_evaluated')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: local source reports only; no Shopify API call, no Shopify writes, no tagsAdd/tagsRemove, no Gmail API/draft/send, and no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, selected_candidate: dict, ready_candidates: list[dict], blocking_conditions: list[dict]) -> str:
    if status == SUCCESS_STATUS:
        return (
            f"Selected next repeat-customer Trustpilot candidate {selected_candidate.get('order_name', '')} "
            f"from {len(ready_candidates)} local-report candidate(s). No APIs, writes, drafts, or sends were performed."
        )
    if status == SOURCE_BLOCKED_STATUS:
        return "Next candidate scan blocked because required local source reports are missing or not ready: " + ", ".join(
            _safe_text(item.get("detail", "")) for item in blocking_conditions
        )
    return "No safe next repeat-customer Trustpilot candidate was found in the local source reports."


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["next_repeat_customer_candidate_scan_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["selected_candidate"] = {}
        payload["selected_order_name"] = ""
        payload["selected_masked_email"] = ""
        payload["next_candidate_selected"] = False
        payload["next_candidate_count"] = 0
        payload["candidate_selected_count"] = 0
        payload["count_semantics_validation"] = _count_semantics_validation(
            next_candidate_selected=False,
            next_candidate_count=0,
        )
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "next candidate scan self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
        payload["detected_issue_summary"] = "Next candidate scan blocked by self privacy assertion."
    return payload


def _trustpilot_alias_coverage() -> dict:
    required = {
        "1: trustpilot",
        "1: trustpoilt",
        "1:trustpilot",
        "1 : trustpilot",
        "1:trustpoilt",
        "1 : trustpoilt",
    }
    normalized_required = {_normalize_tag(tag) for tag in required}
    normalized_configured = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    return {
        "configured_aliases": TRUSTPILOT_TAG_ALIASES,
        "required_aliases": sorted(required),
        "normalized_required_aliases": sorted(normalized_required),
        "normalized_configured_aliases": sorted(normalized_configured),
        "all_required_aliases_present": normalized_required.issubset(normalized_configured),
        "canonical_tag": CANONICAL_TRUSTPILOT_TAG,
    }


def _matched_trustpilot_tags_from_tags(tags: list[str]) -> list[str]:
    aliases = {_normalize_tag(alias) for alias in TRUSTPILOT_TAG_ALIASES}
    return [_safe_text(tag) for tag in tags if _normalize_tag(tag) in aliases]


def _normalize_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text)


def _tags_of_interest(tags: list[str]) -> list[str]:
    interests = []
    for tag in tags:
        normalized = _normalize_tag(tag)
        if normalized in {_normalize_tag(alias) for alias in TRUSTPILOT_TAG_ALIASES}:
            interests.append(tag)
        elif tag in {"1: reveiw request", "1: Review request", "Review sent", "Delivered"}:
            interests.append(tag)
        elif _has_returned_package_tag([tag]) or _has_risk_tag([tag]):
            interests.append(tag)
    return _dedupe(interests)


def _has_any_bucket(buckets: list[str], wanted: set[str]) -> bool:
    return bool(set(buckets).intersection(wanted))


def _has_returned_package_tag(tags: list[str]) -> bool:
    for tag in tags:
        normalized = re.sub(r"[\s_-]+", " ", str(tag or "").strip().lower())
        compact = normalized.replace(" ", "")
        if "return" in compact or "returned" in compact:
            return True
    return False


def _has_risk_tag(tags: list[str]) -> bool:
    pattern = re.compile(r"(?i)(refund|cancel|chargeback|dispute|complaint|shipping[_ -]?issue|delivery[_ -]?issue)")
    return any(pattern.search(str(tag or "")) for tag in tags)


def _privacy_scan_text(text: str) -> dict:
    raw_customer_emails = []
    for match in EMAIL_RE.finditer(text or ""):
        email = match.group(0).lower()
        if email in ALLOWED_REPORT_EMAILS or "***" in email:
            continue
        raw_customer_emails.append(_mask_email(email))
    return {
        "raw_customer_email_count": len(set(raw_customer_emails)),
        "masked_raw_customer_email_findings": sorted(set(raw_customer_emails))[:5],
        "token_secret_bearer_pattern_count": sum(1 for pattern in SECRET_VALUE_PATTERNS if pattern.search(text or "")),
    }


def _safe_masked_email(value) -> str:
    text = _safe_text(value)
    if not text:
        return ""
    if "***@" in text:
        return text
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)


def _safe_text(value) -> str:
    return _sanitize_text(str(value or ""))


def _sanitize_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _dedupe(values: list[str]) -> list[str]:
    result = []
    for value in values:
        if value not in result:
            result.append(value)
    return result
