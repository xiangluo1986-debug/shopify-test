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
from remote_approval.tasks.shopify_review_request_trustpilot_eligibility import (
    BLOCKED_EXISTING_TRUSTPILOT_INVITATION_CUSTOMER_LEVEL,
    BLOCKED_MERGED_ORDER_GROUP_NOT_READY,
    BLOCKED_MISSING_DELIVERED_TAG,
    BLOCKED_MISSING_REVIEW_REQUEST_TAG,
    CANONICAL_REVIEW_REQUEST_TAG,
    evaluate_trustpilot_candidate_eligibility,
    build_trustpilot_eligibility_context,
    eligibility_policy_summary,
    source_report_order_rows,
)
from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_automation_dry_run"
COMMAND_LABEL = TASK_NAME

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_automation_dry_run.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_automation_dry_run.html"

SOURCE_REPORTS = {
    "next_candidate_scan": LOG_DIR / "shopify_review_request_next_repeat_customer_candidate_scan.json",
    "unified_decision_engine": LOG_DIR / "shopify_review_request_unified_decision_engine_dry_run.json",
    "candidate_scan": LOG_DIR / "shopify_review_request_candidate_scan.json",
    "customer_level_duplicate_audit": LOG_DIR
    / "shopify_review_request_customer_level_trustpilot_duplicate_audit.json",
    "gmail_readiness_package": LOG_DIR / "shopify_review_request_gmail_readiness_package.json",
    "trustpilot_gmail_send_audit": LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.json",
    "trustpilot_tag_write_audit": LOG_DIR / "shopify_review_request_trustpilot_tag_write_audit.json",
    "ali_reviews_api_capability_discovery": LOG_DIR
    / "shopify_review_request_ali_reviews_api_capability_discovery.json",
}

DELIVERED_TAG = "Delivered"
CANONICAL_TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = (
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
)

AUTOMATION_STATUS_READY = "ready_for_locked_trustpilot_send_package"
AUTOMATION_STATUS_BLOCKED = "blocked_no_eligible_candidate"
GMAIL_STATUS_BLOCKED_NO_CANDIDATE = "no_gmail_action_until_eligible_candidate"
GMAIL_STATUS_LOCKED_PACKAGE_REQUIRED = "locked_send_package_required_before_gmail_action"
SHOPIFY_TAG_STATUS_BLOCKED = "no_shopify_tag_action_until_email_sent_and_verified"
ALI_REVIEWS_STATUS_BLOCKED = "blocked_waiting_for_vendor_api_documentation"

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
    r"password\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}|"
    r"secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}"
    r")"
)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def run_shopify_review_request_trustpilot_automation_dry_run_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    sources = _load_sources()
    rows = _collect_order_rows(sources)
    customer_context = build_customer_level_duplicate_context(
        [_safe_text(row.get("order_name", "")) for row in rows if _safe_text(row.get("order_name", ""))],
        extra_rows=rows,
    )
    eligibility_context = build_trustpilot_eligibility_context(rows)
    evaluated_rows = _evaluate_rows(rows, customer_context, eligibility_context)
    payload = _build_payload(
        sources=sources,
        evaluated_rows=evaluated_rows,
        customer_context=customer_context,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _load_sources() -> dict:
    return {key: _load_json_report(key, path) for key, path in SOURCE_REPORTS.items()}


def _load_json_report(key: str, path: Path) -> dict:
    report = {
        "key": key,
        "path": str(path),
        "relative_path": f"logs/{path.name}",
        "present": path.exists(),
        "loaded": False,
        "status": "missing",
        "task_name": "",
        "success": None,
        "timestamp": "",
        "error_sanitized": "",
        "data": {},
    }
    if not path.exists():
        return report
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"), strict=False)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error_sanitized"] = _safe_text(str(exc), max_length=300)
        return report
    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error_sanitized"] = "top_level_json_is_not_object"
        return report
    report["loaded"] = True
    report["data"] = data
    report["task_name"] = _safe_text(data.get("task_name") or data.get("task") or "")
    report["status"] = _report_status(data)
    report["success"] = data.get("success") if isinstance(data.get("success"), bool) else None
    report["timestamp"] = _first_text(data, ("timestamp", "generated_at", "created_at", "finished_at"))
    return report


def _collect_order_rows(sources: dict) -> list[dict]:
    rows = []
    for key in (
        "next_candidate_scan",
        "unified_decision_engine",
        "candidate_scan",
        "customer_level_duplicate_audit",
        "gmail_readiness_package",
        "trustpilot_gmail_send_audit",
        "trustpilot_tag_write_audit",
    ):
        report = sources.get(key) or {}
        data = report.get("data") if report.get("loaded") else {}
        if not isinstance(data, dict):
            continue
        for row in _source_rows_for_key(key, data):
            normalized = _public_order_row(row)
            if not normalized:
                continue
            normalized["source_report_key"] = key
            normalized["source_report_path"] = report.get("relative_path", "")
            rows.append(normalized)
    return _dedupe_rows(rows)


def _source_rows_for_key(key: str, data: dict) -> list[dict]:
    if key == "next_candidate_scan":
        return _rows_from_keys(
            data,
            (
                "evaluated_orders",
                "ready_candidate_queue",
                "selected_candidate",
                "selected_candidate_summary",
            ),
        )
    if key == "unified_decision_engine":
        return _rows_from_keys(data, ("decisions", "selected_candidate", "selected_candidate_summary"))
    if key == "candidate_scan":
        rows = source_report_order_rows(data)
        buckets = data.get("classification_buckets")
        if isinstance(buckets, dict):
            for items in buckets.values():
                if isinstance(items, list):
                    rows.extend(item for item in items if isinstance(item, dict))
        return rows
    return source_report_order_rows(data)


def _rows_from_keys(data: dict, keys: tuple[str, ...]) -> list[dict]:
    rows = []
    for key in keys:
        value = data.get(key)
        if isinstance(value, dict):
            rows.append(value)
        elif isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return rows


def _public_order_row(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}
    order_name = _first_text(
        item,
        (
            "order_name",
            "name",
            "selected_order_name",
            "next_candidate_order_name",
            "audit_order_name",
            "audit_order_a",
        ),
    )
    if not order_name:
        return {}
    blocking_reasons = _string_list(item.get("blocking_reasons"))
    blocking_reasons.extend(_string_list(item.get("classification_reasons")))
    return {
        "order_name": order_name,
        "order_id": _first_text(item, ("order_id", "order_id_or_gid", "id")),
        "masked_email": _safe_masked_email(
            _first_text(
                item,
                ("masked_email", "selected_masked_email", "next_candidate_masked_email", "email"),
            )
        ),
        "created_at": _first_text(item, ("createdAt", "created_at", "order_created_at", "processed_at")),
        "tags": _collect_tags(item),
        "status_values": _collect_status_values(item),
        "classification": _first_text(
            item,
            ("classification", "decision", "source_decision", "candidate_status", "status"),
        ),
        "blocking_reasons": _dedupe_text(blocking_reasons),
        "ticket_risk_detected": item.get("ticket_risk_detected") is True or item.get("ticket_blocked") is True,
        "ticket_blocked": item.get("ticket_blocked") is True,
        "repeat_customer_detected": item.get("repeat_customer_detected") is True,
        "customer_id": _first_text(item, ("customer_id", "customer_id_or_gid")),
        "customer_level_duplicate_block_applies": item.get("customer_level_duplicate_block_applies") is True,
        "prior_trustpilot_order_name": _safe_text(item.get("prior_trustpilot_order_name", "")),
        "existing_trustpilot_invitation_tag_detected": (
            item.get("existing_trustpilot_invitation_tag_detected") is True
        ),
        "matched_trustpilot_invitation_tags": _collect_tags_from_keys(
            item,
            ("matched_trustpilot_invitation_tags", "trustpilot_tags"),
        ),
        "safe_tags_summary": item.get("safe_tags_summary") if isinstance(item.get("safe_tags_summary"), dict) else {},
        "source_decision": _first_text(item, ("source_decision", "decision", "classification", "status")),
        "email_present": item.get("email_present") is not False,
    }


def _evaluate_rows(rows: list[dict], customer_context: dict, eligibility_context: dict) -> list[dict]:
    evaluated = []
    for row in rows:
        order_name = _safe_text(row.get("order_name"), max_length=80)
        if not order_name:
            continue
        duplicate = evaluate_customer_level_duplicate(
            order_name,
            _safe_masked_email(row.get("masked_email", "")),
            customer_context,
        )
        if row.get("customer_level_duplicate_block_applies") is True and not duplicate.get(
            "customer_level_duplicate_block_applies"
        ):
            duplicate["customer_level_duplicate_block_applies"] = True
            duplicate["classification"] = CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION
            if not duplicate.get("prior_trustpilot_order_name"):
                duplicate["prior_trustpilot_order_name"] = _safe_text(row.get("prior_trustpilot_order_name", ""))
        eligibility = evaluate_trustpilot_candidate_eligibility(
            row,
            eligibility_context,
            customer_level_duplicate=duplicate,
            existing_blocking_reasons=row.get("blocking_reasons") or [],
        )
        blockers = _blocking_reasons(row, duplicate, eligibility)
        evaluated.append(_evaluated_row(row, duplicate, eligibility, blockers))
    return evaluated


def _blocking_reasons(row: dict, duplicate: dict, eligibility: dict) -> list[str]:
    blockers = []
    if _existing_trustpilot_tag_detected(row):
        blockers.append("blocked_existing_trustpilot_invitation_tag")
    if duplicate.get("customer_level_duplicate_block_applies") is True:
        blockers.append(CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION)
    blockers.extend(_string_list(eligibility.get("blocking_reasons")))
    blockers.extend(_string_list(row.get("blocking_reasons")))
    classification = _safe_text(row.get("classification", ""))
    if classification.startswith("blocked"):
        blockers.append(classification)
    return _dedupe_text(blockers)


def _evaluated_row(row: dict, duplicate: dict, eligibility: dict, blockers: list[str]) -> dict:
    tags = _dedupe_text(row.get("tags") or [])
    selected_ready = (
        not blockers
        and eligibility.get("eligible_for_trustpilot") is True
        and CANONICAL_REVIEW_REQUEST_TAG in tags
        and _safe_masked_email(row.get("masked_email", ""))
    )
    order_name = _safe_text(row.get("order_name"), max_length=80)
    return {
        "order_name": order_name,
        "masked_email": _safe_masked_email(row.get("masked_email", "")),
        "source_report_key": _safe_text(row.get("source_report_key", "")),
        "source_report_path": _safe_text(row.get("source_report_path", "")),
        "delivered_tag_present": eligibility.get("delivered_tag_present") is True,
        "canonical_review_request_tag_present": eligibility.get("canonical_review_request_tag_present") is True,
        "review_request_tag_typo_detected": eligibility.get("review_request_tag_typo_detected") is True,
        "merged_or_related_order_guard_status": _safe_text(
            eligibility.get("merged_or_related_order_guard_status", ""),
            max_length=80,
        ),
        "related_order_names": [_safe_text(value, max_length=80) for value in eligibility.get("related_order_names", [])],
        "customer_level_duplicate_block_applies": duplicate.get("customer_level_duplicate_block_applies") is True,
        "prior_trustpilot_order_name": _safe_text(duplicate.get("prior_trustpilot_order_name", ""), max_length=80),
        "existing_trustpilot_invitation_tag_detected": _existing_trustpilot_tag_detected(row),
        "matched_trustpilot_invitation_tags": _matched_trustpilot_tags(row),
        "eligible_for_trustpilot": eligibility.get("eligible_for_trustpilot") is True,
        "selected_candidate_allowed_for_future_send": selected_ready,
        "blocking_reasons": blockers,
        "blocking_summary": _human_blocking_summary(order_name, blockers, eligibility, duplicate),
        "planned_next_action": _planned_next_action(selected_ready, blockers),
        "gmail_future_action_status": (
            GMAIL_STATUS_LOCKED_PACKAGE_REQUIRED if selected_ready else GMAIL_STATUS_BLOCKED_NO_CANDIDATE
        ),
        "shopify_tag_future_action_status": SHOPIFY_TAG_STATUS_BLOCKED,
    }


def _build_payload(
    sources: dict,
    evaluated_rows: list[dict],
    customer_context: dict,
    duration_seconds: float,
) -> dict:
    eligible_rows = [row for row in evaluated_rows if row["selected_candidate_allowed_for_future_send"]]
    selected = eligible_rows[0] if eligible_rows else {}
    counts = _blocker_counts(evaluated_rows)
    blocked_rows = [row for row in evaluated_rows if row.get("blocking_reasons")]
    focus = _focus_blockers(evaluated_rows)
    automation_status = AUTOMATION_STATUS_READY if selected else AUTOMATION_STATUS_BLOCKED
    gmail_status = (
        GMAIL_STATUS_LOCKED_PACKAGE_REQUIRED if selected else GMAIL_STATUS_BLOCKED_NO_CANDIDATE
    )
    next_admin_action = (
        "Review the locked Trustpilot send package before any real email is sent."
        if selected
        else "Nothing to send now. Wait for a delivered order with 1: review request and no duplicate/customer risk."
    )
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.6",
        "channel": "trustpilot",
        "mode": "dry-run",
        "dry_run": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "automation_status": automation_status,
        "eligible_candidate_count": len(eligible_rows),
        "selected_candidate_order_name": selected.get("order_name", ""),
        "selected_candidate_allowed_for_future_send": bool(selected),
        "blocking_reason": "" if selected else "no_eligible_delivered_review_request_candidate",
        "blocked_orders_summary": _blocked_orders_summary(blocked_rows),
        "blocked_orders_summary_truncated": len(blocked_rows) > 50,
        "customer_level_duplicate_block_count": counts[CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION],
        "missing_delivered_tag_count": counts[BLOCKED_MISSING_DELIVERED_TAG],
        "missing_review_request_tag_count": counts[BLOCKED_MISSING_REVIEW_REQUEST_TAG],
        "related_order_group_not_ready_count": counts[BLOCKED_MERGED_ORDER_GROUP_NOT_READY],
        "already_sent_trustpilot_count": _already_sent_trustpilot_count(customer_context, evaluated_rows),
        "order_22620_blocker_status": focus["order_22620"],
        "order_22582_blocker_status": focus["order_22582"],
        "ali_reviews_status": ALI_REVIEWS_STATUS_BLOCKED,
        "gmail_future_action_status": gmail_status,
        "shopify_tag_future_action_status": SHOPIFY_TAG_STATUS_BLOCKED,
        "next_admin_action": next_admin_action,
        "automation_pipeline_steps": _pipeline_steps(bool(selected)),
        "future_next_action_if_candidate_exists": (
            "Generate a locked Trustpilot Gmail send package for human review; do not send automatically."
        ),
        "candidate_requirements": [
            f"Delivered order detected with {DELIVERED_TAG}.",
            f"Required Shopify tag present: {CANONICAL_REVIEW_REQUEST_TAG}.",
            "Duplicate and customer-level blocker checks pass.",
            "Gmail draft/send readiness remains in locked dry-run preparation.",
            "Admin approval is required before any future real email.",
        ],
        "trustpilot_eligibility_policy": eligibility_policy_summary(),
        "customer_level_duplicate_summary": public_context_summary(customer_context),
        "source_report_status": _source_report_status(sources),
        "safety_gates_active": _safety_gates_active(),
        "safety_summary": _safety_summary(),
        **_safety_summary(),
        "report_paths": {
            "json": str(REPORT_JSON_PATH),
            "html": str(REPORT_HTML_PATH),
        },
        "duration_seconds": duration_seconds,
        "detected_issue_summary": _issue_summary(automation_status, len(eligible_rows), focus),
    }
    return _safe_payload(payload)


def _focus_blockers(evaluated_rows: list[dict]) -> dict:
    rows_by_order = {row["order_name"]: row for row in evaluated_rows}
    order_22620 = rows_by_order.get("#22620") or {}
    order_22582 = rows_by_order.get("#22582") or {}
    prior_order = _safe_text(order_22620.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
    return {
        "order_22620": {
            "order_name": "#22620",
            "status": "blocked" if order_22620 else "not_found_in_loaded_reports",
            "blocker": CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION
            if order_22620.get("customer_level_duplicate_block_applies")
            else "",
            "prior_trustpilot_order_name": prior_order,
            "message": f"Do not send. This customer already received a Trustpilot invitation via {prior_order}.",
            "blocking_reasons": _string_list(order_22620.get("blocking_reasons")),
            "selected_candidate_allowed_for_future_send": False,
        },
        "order_22582": {
            "order_name": "#22582",
            "status": "blocked" if order_22582 else "not_found_in_loaded_reports",
            "blocker": _first_known_blocker(
                order_22582,
                (
                    BLOCKED_MISSING_DELIVERED_TAG,
                    BLOCKED_MISSING_REVIEW_REQUEST_TAG,
                    BLOCKED_MERGED_ORDER_GROUP_NOT_READY,
                ),
            ),
            "message": (
                "Do not send yet. Order is not delivered, missing 1: review request, "
                "and related order group #22582/#22581 is not ready."
            ),
            "delivered_tag_present": order_22582.get("delivered_tag_present") is True,
            "canonical_review_request_tag_present": order_22582.get("canonical_review_request_tag_present") is True,
            "merged_or_related_order_guard_status": _safe_text(
                order_22582.get("merged_or_related_order_guard_status", ""),
                max_length=80,
            ),
            "related_order_names": _dedupe_text(
                [*(order_22582.get("related_order_names") or []), "#22582", "#22581"]
            )[:10],
            "blocking_reasons": _string_list(order_22582.get("blocking_reasons")),
            "selected_candidate_allowed_for_future_send": False,
        },
    }


def _blocked_orders_summary(blocked_rows: list[dict]) -> list[dict]:
    preferred_orders = {"#22620": 0, "#22582": 1}
    sorted_rows = sorted(
        blocked_rows,
        key=lambda row: (preferred_orders.get(row.get("order_name"), 10), row.get("order_name", "")),
    )
    return [
        {
            "order_name": row["order_name"],
            "masked_email": _safe_masked_email(row.get("masked_email", "")),
            "blocking_reasons": _string_list(row.get("blocking_reasons")),
            "blocking_summary": _safe_text(row.get("blocking_summary", ""), max_length=500),
            "planned_next_action": _safe_text(row.get("planned_next_action", ""), max_length=300),
            "prior_trustpilot_order_name": _safe_text(row.get("prior_trustpilot_order_name", ""), max_length=80),
            "source_report_path": _safe_text(row.get("source_report_path", ""), max_length=160),
        }
        for row in sorted_rows[:50]
    ]


def _pipeline_steps(candidate_exists: bool) -> list[dict]:
    return [
        {
            "number": 1,
            "label": "Delivered order detected",
            "status": "required",
            "detail": f"Order must have {DELIVERED_TAG}.",
        },
        {
            "number": 2,
            "label": "Required Shopify tag present: 1: review request",
            "status": "required",
            "detail": f"Exact tag required: {CANONICAL_REVIEW_REQUEST_TAG}.",
        },
        {
            "number": 3,
            "label": "Duplicate/customer-level blocker check",
            "status": "active_dry_run_check",
            "detail": "Customer-level duplicate, related order, ticket, refund, return, shipping, dispute, and chargeback gates must pass.",
        },
        {
            "number": 4,
            "label": "Gmail draft/send readiness",
            "status": "dry_run_preparation_only",
            "detail": "No Gmail API call, draft creation, draft deletion, or send is active in Phase 5.6.",
        },
        {
            "number": 5,
            "label": "Locked admin approval",
            "status": "future_locked_phase_only" if not candidate_exists else "future_locked_package_required",
            "detail": "A separate locked package is required before any real email.",
        },
        {
            "number": 6,
            "label": "Email send",
            "status": "not_active_real_send",
            "detail": "No email is sent by this dry-run orchestrator.",
        },
        {
            "number": 7,
            "label": "Shopify tag write: 1: trustpilot",
            "status": "not_active_shopify_write",
            "detail": f"Future tag write to {CANONICAL_TRUSTPILOT_TAG} requires verified email send and separate approval.",
        },
        {
            "number": 8,
            "label": "History/debug recorded",
            "status": "local_report_only",
            "detail": "This phase records local JSON/HTML dry-run evidence only.",
        },
    ]


def _safety_gates_active() -> list[dict]:
    return [
        {"name": "dry_run_only", "active": True},
        {"name": "no_gmail_api_call", "active": True},
        {"name": "no_gmail_draft_created", "active": True},
        {"name": "no_email_sent", "active": True},
        {"name": "no_shopify_api_call", "active": True},
        {"name": "no_shopify_write", "active": True},
        {"name": "no_tagsAdd_or_tagsRemove", "active": True},
        {"name": "no_trustpilot_kudosi_ali_reviews_api_call", "active": True},
        {"name": "no_tracking_token_or_redirect", "active": True},
        {"name": "masked_customer_email_only", "active": True},
    ]


def _safety_summary() -> dict:
    return {
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_deleted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "ali_reviews_write_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "raw_customer_email_output": False,
        "full_gmail_draft_or_message_id_output": False,
        "logs_committed": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "json_trustpilot_automation_dry_run_path": str(json_path),
        "html_trustpilot_automation_dry_run_path": str(html_path),
        "automation_status": payload["automation_status"],
        "eligible_candidate_count": payload["eligible_candidate_count"],
        "selected_candidate_order_name": payload["selected_candidate_order_name"],
        "selected_candidate_allowed_for_future_send": payload[
            "selected_candidate_allowed_for_future_send"
        ],
        "gmail_future_action_status": payload["gmail_future_action_status"],
        "shopify_tag_future_action_status": payload["shopify_tag_future_action_status"],
        "ali_reviews_status": payload["ali_reviews_status"],
        "order_22620_blocker": payload["order_22620_blocker_status"]["blocker"],
        "order_22582_blocker": payload["order_22582_blocker_status"]["blocker"],
        "detected_issue_summary": payload["detected_issue_summary"],
        **_safety_summary(),
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
    status_class = "ok" if payload["eligible_candidate_count"] else "warn"
    blocked_rows = "\n".join(_render_blocked_row(row) for row in payload["blocked_orders_summary"])
    if not blocked_rows:
        blocked_rows = '<tr><td colspan="4">No blocked rows were reconstructed.</td></tr>'
    step_rows = "\n".join(
        f"<tr><td>{step['number']}</td><td>{escape(step['label'])}</td>"
        f"<td><code>{escape(step['status'])}</code></td><td>{escape(step['detail'])}</td></tr>"
        for step in payload["automation_pipeline_steps"]
    )
    safety_rows = "\n".join(
        f"<tr><td><code>{escape(item['name'])}</code></td><td>{escape(str(item['active']))}</td></tr>"
        for item in payload["safety_gates_active"]
    )
    source_rows = "\n".join(
        f"<tr><td>{escape(source['key'])}</td><td>{escape(source['relative_path'])}</td>"
        f"<td>{escape(str(source['present']))}</td><td>{escape(str(source['loaded']))}</td>"
        f"<td><code>{escape(source['status'])}</code></td></tr>"
        for source in payload["source_report_status"]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Automation Dry Run</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .status {{ border-left: 4px solid #d97706; background: #fff7ed; padding: 10px 12px; }}
    .status.ok {{ border-left-color: #16a34a; background: #f0fdf4; }}
  </style>
</head>
<body>
  <h1>Trustpilot Automation Dry Run</h1>
  <p class="status {status_class}">Status: <strong>{escape(payload["automation_status"])}</strong></p>
  <p>Channel: <code>trustpilot</code>. Mode: <code>dry-run</code>. No Gmail draft was created, no email was sent, no Shopify tag was written, and no external review API was called.</p>
  <table>
    <tbody>
      <tr><th>Eligible candidate count</th><td>{payload["eligible_candidate_count"]}</td></tr>
      <tr><th>Selected candidate</th><td>{escape(payload["selected_candidate_order_name"] or "-")}</td></tr>
      <tr><th>Selected candidate allowed for future send</th><td>{escape(str(payload["selected_candidate_allowed_for_future_send"]))}</td></tr>
      <tr><th>Gmail future action</th><td><code>{escape(payload["gmail_future_action_status"])}</code></td></tr>
      <tr><th>Shopify tag future action</th><td><code>{escape(payload["shopify_tag_future_action_status"])}</code></td></tr>
      <tr><th>Ali Reviews / Kudosi</th><td><code>{escape(payload["ali_reviews_status"])}</code></td></tr>
      <tr><th>Next admin action</th><td>{escape(payload["next_admin_action"])}</td></tr>
    </tbody>
  </table>
  <h2>Current Known Blockers</h2>
  <p>{escape(payload["order_22620_blocker_status"]["message"])}</p>
  <p>{escape(payload["order_22582_blocker_status"]["message"])}</p>
  <h2>Counts</h2>
  <table>
    <tbody>
      <tr><th>Customer-level duplicate blocks</th><td>{payload["customer_level_duplicate_block_count"]}</td></tr>
      <tr><th>Missing delivered tag</th><td>{payload["missing_delivered_tag_count"]}</td></tr>
      <tr><th>Missing 1: review request</th><td>{payload["missing_review_request_tag_count"]}</td></tr>
      <tr><th>Related order group not ready</th><td>{payload["related_order_group_not_ready_count"]}</td></tr>
      <tr><th>Already sent Trustpilot signals</th><td>{payload["already_sent_trustpilot_count"]}</td></tr>
    </tbody>
  </table>
  <h2>Automation Pipeline</h2>
  <table><thead><tr><th>#</th><th>Step</th><th>Status</th><th>Detail</th></tr></thead><tbody>{step_rows}</tbody></table>
  <h2>Blocked Orders Summary</h2>
  <table><thead><tr><th>Order</th><th>Masked email</th><th>Blockers</th><th>Action</th></tr></thead><tbody>{blocked_rows}</tbody></table>
  <h2>Safety Gates</h2>
  <table><tbody>{safety_rows}</tbody></table>
  <details>
    <summary>Advanced source report details</summary>
    <table><thead><tr><th>Key</th><th>Path</th><th>Present</th><th>Loaded</th><th>Status</th></tr></thead><tbody>{source_rows}</tbody></table>
  </details>
</body>
</html>"""


def _render_blocked_row(row: dict) -> str:
    return (
        "<tr>"
        f"<td>{escape(row.get('order_name', ''))}</td>"
        f"<td>{escape(row.get('masked_email', '') or '-')}</td>"
        f"<td>{escape(', '.join(row.get('blocking_reasons') or []))}</td>"
        f"<td>{escape(row.get('planned_next_action', ''))}</td>"
        "</tr>"
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.6 Trustpilot automation dry-run finished.\n"
        f"Status: {payload['automation_status']}\n"
        f"Eligible candidate count: {payload['eligible_candidate_count']}\n"
        f"Selected candidate: {payload['selected_candidate_order_name'] or 'None'}\n"
        f"Gmail future action: {payload['gmail_future_action_status']}\n"
        f"Shopify tag future action: {payload['shopify_tag_future_action_status']}\n"
        f"Ali Reviews / Kudosi: {payload['ali_reviews_status']}\n"
        "Safety: no Gmail API, no draft creation/deletion, no email send, no Shopify API/write/tag mutation, no Trustpilot/Kudosi/Ali Reviews API, and no tracking token.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _issue_summary(status: str, eligible_count: int, focus: dict) -> str:
    if eligible_count:
        return f"Trustpilot dry-run found {eligible_count} eligible candidate(s); next action is a locked send package only."
    return (
        "No eligible Trustpilot candidate. #22620 remains blocked by customer-level duplicate via "
        f"{focus['order_22620'].get('prior_trustpilot_order_name') or '#22621'}; "
        "#22582 remains blocked by missing delivery, missing 1: review request, and related order group readiness."
    )


def _blocker_counts(rows: list[dict]) -> Counter:
    counts = Counter()
    for row in rows:
        blockers = set(row.get("blocking_reasons") or [])
        if row.get("customer_level_duplicate_block_applies"):
            blockers.add(CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION)
        if not row.get("delivered_tag_present"):
            blockers.add(BLOCKED_MISSING_DELIVERED_TAG)
        if not row.get("canonical_review_request_tag_present"):
            blockers.add(BLOCKED_MISSING_REVIEW_REQUEST_TAG)
        if row.get("merged_or_related_order_guard_status") in {"not_ready", "uncertain"}:
            blockers.add(BLOCKED_MERGED_ORDER_GROUP_NOT_READY)
        for blocker in blockers:
            counts[blocker] += 1
    return counts


def _already_sent_trustpilot_count(customer_context: dict, rows: list[dict]) -> int:
    summary = public_context_summary(customer_context)
    orders = {
        _safe_text(item.get("order_name", ""), max_length=80)
        for item in summary.get("prior_trustpilot_invitation_orders", [])
        if isinstance(item, dict)
    }
    for row in rows:
        if row.get("existing_trustpilot_invitation_tag_detected"):
            orders.add(row.get("order_name", ""))
    orders.discard("")
    return len(orders)


def _planned_next_action(selected_ready: bool, blockers: list[str]) -> str:
    if selected_ready:
        return "Prepare a locked Trustpilot send package for admin review; do not send automatically."
    if CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION in blockers:
        return "Do not send. Customer-level Trustpilot duplicate prevention is active."
    if BLOCKED_MISSING_DELIVERED_TAG in blockers:
        return f"Do not send yet. {DELIVERED_TAG} is missing."
    if BLOCKED_MISSING_REVIEW_REQUEST_TAG in blockers:
        return f"Do not send yet. {CANONICAL_REVIEW_REQUEST_TAG} is missing."
    if BLOCKED_MERGED_ORDER_GROUP_NOT_READY in blockers:
        return "Do not send yet. Related order group is not ready."
    return "Do not send until all dry-run eligibility gates pass."


def _human_blocking_summary(order_name: str, blockers: list[str], eligibility: dict, duplicate: dict) -> str:
    if order_name == "#22620" and CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION in blockers:
        prior = _safe_text(duplicate.get("prior_trustpilot_order_name"), max_length=80) or "#22621"
        return f"Do not send. This customer already received a Trustpilot invitation via {prior}."
    if order_name == "#22582":
        return (
            "Do not send yet. Order is not delivered, missing 1: review request, "
            "and related order group #22582/#22581 is not ready."
        )
    details = _string_list(eligibility.get("blocker_details"))
    if details:
        return " ".join(details[:4])
    return ", ".join(blockers)


def _first_known_blocker(row: dict, blockers: tuple[str, ...]) -> str:
    row_blockers = set(row.get("blocking_reasons") or [])
    for blocker in blockers:
        if blocker in row_blockers:
            return blocker
    return ""


def _source_report_status(sources: dict) -> list[dict]:
    return [
        {
            "key": key,
            "relative_path": _safe_text(report.get("relative_path", "")),
            "present": bool(report.get("present")),
            "loaded": bool(report.get("loaded")),
            "status": _safe_text(report.get("status", "")),
            "task_name": _safe_text(report.get("task_name", "")),
            "success": report.get("success"),
            "timestamp": _safe_text(report.get("timestamp", "")),
            "error_sanitized": _safe_text(report.get("error_sanitized", "")),
        }
        for key, report in sources.items()
    ]


def _existing_trustpilot_tag_detected(row: dict) -> bool:
    return bool(_matched_trustpilot_tags(row)) or row.get("existing_trustpilot_invitation_tag_detected") is True


def _matched_trustpilot_tags(row: dict) -> list[str]:
    tags = _collect_tags_from_keys(
        row,
        (
            "tags",
            "matched_trustpilot_invitation_tags",
            "trustpilot_tags",
            "customer_history_tags",
            "customer_order_tags",
            "historical_order_tags",
            "customer_historical_order_tags",
        ),
    )
    summary = row.get("safe_tags_summary") if isinstance(row.get("safe_tags_summary"), dict) else {}
    for key in ("tags_of_interest", "safe_tags", "exact_tags_of_interest", "matched_trustpilot_invitation_tags"):
        tags.extend(_tag_list(summary.get(key)))
    aliases = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    return _dedupe_text(tag for tag in tags if _normalize_tag(tag) in aliases)


def _collect_tags(item: dict) -> list[str]:
    tags = _collect_tags_from_keys(
        item,
        (
            "tags",
            "tags_of_interest",
            "exact_tags_of_interest",
            "matched_trustpilot_invitation_tags",
            "customer_history_tags",
            "customer_order_tags",
            "historical_order_tags",
            "customer_historical_order_tags",
        ),
        split_tags_key=True,
    )
    summary = item.get("safe_tags_summary") if isinstance(item.get("safe_tags_summary"), dict) else {}
    for key in ("safe_tags", "tags_of_interest", "exact_tags_of_interest", "matched_trustpilot_invitation_tags"):
        tags.extend(_tag_list(summary.get(key)))
    return _dedupe_text(tags)


def _collect_tags_from_keys(item: dict, keys: tuple[str, ...], split_tags_key: bool = False) -> list[str]:
    tags = []
    for key in keys:
        value = item.get(key)
        tags.extend(_tag_list(value, split_strings=(split_tags_key and key == "tags")))
    return _dedupe_text(tags)


def _tag_list(value, split_strings: bool = False) -> list[str]:
    if isinstance(value, str):
        pieces = value.split(",") if split_strings else [value]
        return [_safe_text(piece, max_length=160) for piece in pieces if _safe_text(piece, max_length=160)]
    if isinstance(value, (list, tuple, set)):
        return [_safe_text(item, max_length=160) for item in value if _safe_text(item, max_length=160)]
    return []


def _collect_status_values(item: dict) -> list[str]:
    values = []
    for key in (
        "displayFulfillmentStatus",
        "displayFinancialStatus",
        "fulfillment_status",
        "fulfillment_status_raw",
        "status",
        "source_decision",
        "decision",
        "classification",
        "candidate_status",
        "blocking_summary",
    ):
        value = item.get(key)
        if value not in (None, ""):
            values.append(_safe_text(value))
    values.extend(_string_list(item.get("classification_reasons")))
    values.extend(_string_list(item.get("blocking_reasons")))
    return _dedupe_text(values)


def _safe_payload(value):
    if isinstance(value, dict):
        return {str(key): _safe_payload(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value, max_length=4000)
    return value


def _dedupe_rows(rows: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for row in rows:
        key = _safe_text(row.get("order_name", ""), max_length=80)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _report_status(data: dict) -> str:
    for key in (
        "automation_status",
        "next_repeat_customer_candidate_scan_status",
        "decision_engine_status",
        "customer_level_duplicate_audit_status",
        "send_audit_status",
        "tag_write_audit_status",
        "ali_reviews_api_capability_discovery_status",
        "report_status",
        "status",
    ):
        text = _safe_text(data.get(key, ""))
        if text:
            return text
    return "loaded"


def _first_text(mapping: dict, keys: tuple[str, ...]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _safe_text(value)
    return ""


def _string_list(value) -> list[str]:
    if isinstance(value, str):
        return [_safe_text(value)] if _safe_text(value) else []
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            if isinstance(item, dict):
                result.append(_first_text(item, ("status", "reason", "detail", "classification")))
            else:
                result.append(_safe_text(item))
        return _dedupe_text(result)
    return []


def _safe_masked_email(value) -> str:
    text = _safe_text(value, max_length=160)
    if not text or "@" not in text:
        return ""
    if "***" in text:
        return text
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _normalize_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text)


def _safe_text(value, max_length=300) -> str:
    text = str(value or "")
    text = CONTROL_CHARS_RE.sub(" ", text)
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)
    text = " ".join(text.split())
    return text[:max_length]


def _dedupe_text(values) -> list[str]:
    result = []
    seen = set()
    for value in values:
        text = _safe_text(value)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result
