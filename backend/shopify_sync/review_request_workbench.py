import json
import re
from pathlib import Path

from django.conf import settings

from .models import ShopifyOrder


EXACT_REVIEW_REQUEST_TAG = "1: reveiw request"
DELIVERED_TAG = "Delivered"
TRUSTPILOT_TAG_ALIASES = (
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
)
FUTURE_TRACKING_STATUSES = (
    "invitation_draft_prepared",
    "invitation_sent",
    "shopify_tag_written",
    "clicked",
    "review_detected",
    "blocked_existing_trustpilot_invitation_tag",
    "blocked_returned_package",
    "blocked_first_order_customer",
    "blocked_risk_or_ticket",
)

REPORT_DEFINITIONS = (
    (
        "next_candidate_scan",
        "Next repeat customer candidate scan",
        "shopify_review_request_next_repeat_customer_candidate_scan.json",
        (
            "next_repeat_customer_candidate_scan_status",
            "report_status",
            "status",
        ),
    ),
    (
        "candidate_scan",
        "Candidate scan",
        "shopify_review_request_candidate_scan.json",
        ("report_status", "status"),
    ),
    (
        "manual_action_package",
        "Manual action package",
        "shopify_review_request_manual_action_package.json",
        ("manual_action_package_status", "report_status", "status"),
    ),
    (
        "unified_decision_engine",
        "Unified decision engine dry-run",
        "shopify_review_request_unified_decision_engine_dry_run.json",
        ("decision_engine_status", "report_status", "status"),
    ),
    (
        "returned_package_guard",
        "Returned package guard",
        "shopify_review_request_returned_package_guard.json",
        ("returned_package_guard_status", "report_status", "status"),
    ),
    (
        "trustpilot_one_candidate_draft_package",
        "Trustpilot one-candidate draft package",
        "shopify_review_request_trustpilot_one_candidate_gmail_draft_package.json",
        ("draft_package_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_draft_package",
        "Trustpilot Gmail draft package",
        "shopify_review_request_trustpilot_gmail_draft_package.json",
        ("draft_package_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_draft_locked_test",
        "Trustpilot Gmail draft create locked test",
        "shopify_review_request_trustpilot_gmail_draft_create_locked_test.json",
        ("draft_create_locked_test_status", "report_status", "status"),
    ),
    (
        "trustpilot_gmail_first_draft_audit",
        "Trustpilot Gmail first draft audit",
        "shopify_review_request_trustpilot_gmail_first_draft_audit.json",
        ("first_draft_audit_status", "report_status", "status"),
    ),
    (
        "trustpilot_completion_next_batch_design",
        "Trustpilot completion next batch design",
        "shopify_review_request_trustpilot_completion_next_batch_design.json",
        ("completion_next_batch_design_status", "report_status", "status"),
    ),
    (
        "trustpilot_suppress_ali_reviews_design",
        "Trustpilot suppress Ali Reviews design",
        "shopify_review_request_trustpilot_suppress_ali_reviews_design.json",
        ("trustpilot_suppress_ali_reviews_design_status", "report_status", "status"),
    ),
    (
        "trustpilot_tag_write_design",
        "Trustpilot tag write design dry-run",
        "shopify_review_request_trustpilot_tag_write_design_dry_run.json",
        ("tag_write_design_status", "report_status", "status"),
    ),
    (
        "trustpilot_tag_write_audit",
        "Trustpilot tag write audit",
        "shopify_review_request_trustpilot_tag_write_audit.json",
        ("tag_write_audit_status", "report_status", "status"),
    ),
    (
        "trustpilot_send_audit",
        "Trustpilot invitation audit",
        "shopify_review_request_trustpilot_gmail_send_audit.json",
        ("send_audit_status", "report_status", "status"),
    ),
)

SAFETY_FLAGS = (
    "shopify_write_performed",
    "mutation_performed",
    "tags_add_performed",
    "tags_remove_performed",
    "gmail_api_call_performed",
    "gmail_draft_created",
    "email_sent",
    "kudosi_api_call_performed",
    "ali_reviews_api_call_performed",
    "trustpilot_api_call_performed",
    "tracking_redirect_enabled",
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
    r"password\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{8,}"
    r")"
)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")

MAX_REPORT_BYTES = 4_000_000
MAX_SOURCE_ROWS = 500
MAX_TABLE_ROWS = 25


def build_review_request_workbench_context():
    reports = _load_known_reports()
    all_rows = _dedupe_rows(_collect_report_rows(reports))
    latest_scan = _latest_scan_summary(reports.get("next_candidate_scan", {}))
    candidate_queue = _candidate_queue(reports)
    invitation_history = _rows_with_trustpilot_tags(all_rows)
    review_request_queue = _rows_with_exact_review_request_tag(all_rows)
    blocked_orders = _blocked_rows(reports, all_rows)
    report_history = _report_history(reports)
    safety_history = _safety_history(reports)
    local_stats = _local_order_stats()

    return {
        "review_request_workbench": {
            "summary": _summary(
                latest_scan=latest_scan,
                candidate_queue=candidate_queue,
                invitation_history=invitation_history,
                review_request_queue=review_request_queue,
                blocked_orders=blocked_orders,
                reports=reports,
                local_stats=local_stats,
            ),
            "latest_scan": latest_scan,
            "candidate_queue": candidate_queue[:MAX_TABLE_ROWS],
            "invitation_history": invitation_history[:MAX_TABLE_ROWS],
            "review_request_queue": review_request_queue[:MAX_TABLE_ROWS],
            "blocked_orders": blocked_orders[:MAX_TABLE_ROWS],
            "report_history": report_history,
            "safety_history": safety_history,
            "local_stats": local_stats,
            "tracking_design": _tracking_design(),
            "trustpilot_aliases": TRUSTPILOT_TAG_ALIASES,
            "exact_review_request_tag": EXACT_REVIEW_REQUEST_TAG,
            "delivered_tag": DELIVERED_TAG,
            "safety_confirmations": _current_page_safety_confirmations(),
        }
    }


def mask_email(email):
    value = str(email or "").strip()
    if not value or "@" not in value:
        return ""
    if "*" in value:
        return _sanitize_text(value, max_length=120)
    local, domain = value.rsplit("@", 1)
    if not local or not domain:
        return ""
    local_mask = f"{local[:1]}***"
    domain_parts = domain.split(".")
    if len(domain_parts) >= 2 and domain_parts[0]:
        domain_mask = f"{domain_parts[0][:1]}***.{domain_parts[-1]}"
    else:
        domain_mask = "***"
    return f"{local_mask}@{domain_mask}"


def _project_root():
    return Path(settings.BASE_DIR).resolve().parent


def _log_dir():
    return _project_root() / "logs"


def _load_known_reports():
    reports = {}
    for key, label, filename, status_keys in REPORT_DEFINITIONS:
        reports[key] = _load_json_report(key, label, filename, status_keys)
    return reports


def _load_json_report(key, label, filename, status_keys):
    path = _log_dir() / filename
    report = {
        "key": key,
        "label": label,
        "filename": filename,
        "relative_path": f"logs/{filename}",
        "present": False,
        "loaded": False,
        "status": "missing",
        "timestamp": "",
        "modified_at": "",
        "success": None,
        "error": "",
        "data": {},
    }
    if not path.exists():
        return report
    report["present"] = True
    try:
        stat = path.stat()
        report["modified_at"] = _safe_text(_format_file_time(stat.st_mtime))
        report["size_bytes"] = stat.st_size
        if stat.st_size > MAX_REPORT_BYTES:
            report["status"] = "present_but_too_large_for_workbench"
            report["error"] = "report_too_large"
            return report
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        report["status"] = "present_but_unreadable"
        report["error"] = _sanitize_text(str(exc), max_length=300)
        return report

    if not isinstance(data, dict):
        report["status"] = "present_but_not_object"
        report["error"] = "top_level_json_is_not_object"
        return report

    report["loaded"] = True
    report["data"] = data
    report["status"] = _first_text(data, status_keys) or "loaded"
    report["timestamp"] = _first_text(
        data,
        ("timestamp", "generated_at", "created_at", "started_at", "finished_at"),
    )
    if "success" in data:
        report["success"] = bool(data.get("success"))
    return report


def _format_file_time(timestamp):
    from datetime import datetime

    return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S")


def _local_order_stats():
    try:
        orders = ShopifyOrder.objects.all()
        with_email = orders.exclude(customer_email__isnull=True).exclude(customer_email="")
        latest = orders.order_by("-order_created_at").values(
            "order_name",
            "customer_email",
            "order_created_at",
            "fulfillment_status",
            "financial_status",
        )[:10]
        return {
            "available": True,
            "total_orders": orders.count(),
            "orders_with_email": with_email.count(),
            "recent_orders": [
                {
                    "order_name": _safe_text(row.get("order_name")),
                    "masked_email": mask_email(row.get("customer_email")),
                    "order_created_at": _safe_text(row.get("order_created_at")),
                    "fulfillment_status": _safe_text(row.get("fulfillment_status")),
                    "financial_status": _safe_text(row.get("financial_status")),
                }
                for row in latest
            ],
            "note": (
                "Local ShopifyOrder rows do not store Shopify order tags; tag sections "
                "come from local review-request reports when present."
            ),
        }
    except Exception as exc:  # pragma: no cover - defensive admin display path.
        return {
            "available": False,
            "total_orders": 0,
            "orders_with_email": 0,
            "recent_orders": [],
            "error": _sanitize_text(str(exc), max_length=300),
            "note": "Local order summary could not be loaded.",
        }


def _collect_report_rows(reports):
    rows = []
    for report in reports.values():
        data = report.get("data") if report.get("loaded") else {}
        if not isinstance(data, dict):
            continue
        rows.extend(_rows_from_report(data, report["label"], report["relative_path"]))
        if len(rows) >= MAX_SOURCE_ROWS:
            break
    return rows[:MAX_SOURCE_ROWS]


def _rows_from_report(data, source_label, source_path):
    rows = []
    selected = data.get("selected_candidate")
    if isinstance(selected, dict):
        rows.append(_row_from_mapping(selected, source_label, source_path, "selected_candidate"))

    for list_key, section in (
        ("ready_candidate_queue", "ready_candidate_queue"),
        ("evaluated_orders", "evaluated_orders"),
        ("orders", "orders"),
        ("blocked_orders", "blocked_orders"),
        ("repeat_customer_candidates", "repeat_customer_candidates"),
        ("needs_manual_review", "needs_manual_review"),
        ("decisions", "decisions"),
    ):
        value = data.get(list_key)
        if isinstance(value, list):
            rows.extend(
                _row_from_mapping(item, source_label, source_path, section)
                for item in value
                if isinstance(item, dict)
            )

    classification_buckets = data.get("classification_buckets")
    if isinstance(classification_buckets, dict):
        for bucket, items in classification_buckets.items():
            if isinstance(items, list):
                rows.extend(
                    _row_from_mapping(
                        item,
                        source_label,
                        source_path,
                        f"classification:{bucket}",
                    )
                    for item in items
                    if isinstance(item, dict)
                )

    manual_sections = data.get("manual_action_sections")
    if isinstance(manual_sections, dict):
        for section, items in manual_sections.items():
            if isinstance(items, list):
                rows.extend(
                    _row_from_mapping(
                        item,
                        source_label,
                        source_path,
                        f"manual_action:{section}",
                    )
                    for item in items
                    if isinstance(item, dict)
                )

    top_level_row = _row_from_top_level_report(data, source_label, source_path)
    if top_level_row:
        rows.append(top_level_row)
    return [row for row in rows if row]


def _row_from_top_level_report(data, source_label, source_path):
    order_name = _first_text(data, ("selected_order_name", "next_candidate_order_name"))
    masked_email = _first_text(data, ("selected_masked_email", "next_candidate_masked_email"))
    if not order_name and not masked_email:
        return None
    return {
        "order_name": order_name,
        "order_id": "",
        "masked_email": mask_email(masked_email),
        "created_at": _first_text(data, ("timestamp", "created_at")),
        "status": _first_text(
            data,
            (
                "next_repeat_customer_candidate_scan_status",
                "report_status",
                "status",
            ),
        ),
        "source": source_label,
        "source_path": source_path,
        "source_section": "report_summary",
        "tags": [],
        "tags_summary": "No tag data in this summary row",
        "trustpilot_tags": [],
        "trustpilot_invitation_present": False,
        "review_request_tag_present": False,
        "blocking_reasons": [],
        "blocking_summary": "",
        "repeat_customer_detected": "",
    }


def _row_from_mapping(item, source_label, source_path, source_section):
    order_name = _first_text(
        item,
        (
            "order_name",
            "name",
            "selected_order_name",
            "next_candidate_order_name",
        ),
    )
    order_id = _first_text(item, ("order_id", "order_id_or_gid", "id"))
    masked_email = _first_text(
        item,
        ("masked_email", "selected_masked_email", "next_candidate_masked_email", "email"),
    )
    tags = _collect_tags(item)
    trustpilot_tags = _matched_trustpilot_tags(item, tags)
    blocking_reasons = _collect_string_list(item, "blocking_reasons")
    if not blocking_reasons:
        blocking_reasons = _collect_string_list(item, "classification_reasons")
    status = _first_text(
        item,
        (
            "candidate_status",
            "classification",
            "decision",
            "source_decision",
            "suggested_next_manual_action",
            "status",
        ),
    )
    if not any((order_name, order_id, masked_email, tags, trustpilot_tags, status)):
        return None

    return {
        "order_name": order_name or order_id,
        "order_id": order_id,
        "masked_email": mask_email(masked_email),
        "created_at": _first_text(
            item,
            ("createdAt", "created_at", "order_created_at", "processed_at", "timestamp"),
        ),
        "status": status or source_section,
        "source": source_label,
        "source_path": source_path,
        "source_section": source_section,
        "tags": tags,
        "tags_summary": ", ".join(tags) if tags else "No tag data in row",
        "trustpilot_tags": trustpilot_tags,
        "trustpilot_invitation_present": bool(trustpilot_tags),
        "review_request_tag_present": EXACT_REVIEW_REQUEST_TAG in tags,
        "blocking_reasons": blocking_reasons,
        "blocking_summary": ", ".join(blocking_reasons),
        "repeat_customer_detected": _safe_text(item.get("repeat_customer_detected")),
    }


def _candidate_queue(reports):
    next_data = (reports.get("next_candidate_scan") or {}).get("data") or {}
    queue = next_data.get("ready_candidate_queue") if isinstance(next_data, dict) else []
    rows = [
        _row_from_mapping(
            item,
            "Next repeat customer candidate scan",
            "logs/shopify_review_request_next_repeat_customer_candidate_scan.json",
            "ready_candidate_queue",
        )
        for item in queue or []
        if isinstance(item, dict)
    ]
    rows = [row for row in rows if row]
    if rows:
        return rows

    candidate_data = (reports.get("candidate_scan") or {}).get("data") or {}
    fallback = candidate_data.get("repeat_customer_candidates") if isinstance(candidate_data, dict) else []
    return [
        row
        for row in (
            _row_from_mapping(
                item,
                "Candidate scan",
                "logs/shopify_review_request_candidate_scan.json",
                "repeat_customer_candidates",
            )
            for item in fallback or []
            if isinstance(item, dict)
        )
        if row
    ]


def _blocked_rows(reports, all_rows):
    next_data = (reports.get("next_candidate_scan") or {}).get("data") or {}
    rows = []
    if isinstance(next_data, dict):
        for item in next_data.get("evaluated_orders") or []:
            if not isinstance(item, dict):
                continue
            row = _row_from_mapping(
                item,
                "Next repeat customer candidate scan",
                "logs/shopify_review_request_next_repeat_customer_candidate_scan.json",
                "evaluated_orders",
            )
            if row and (row["blocking_reasons"] or row["status"] == "blocked"):
                rows.append(row)
    if rows:
        return _dedupe_rows(rows)

    candidate_data = (reports.get("candidate_scan") or {}).get("data") or {}
    if isinstance(candidate_data, dict):
        for item in candidate_data.get("blocked_orders") or []:
            if isinstance(item, dict):
                row = _row_from_mapping(
                    item,
                    "Candidate scan",
                    "logs/shopify_review_request_candidate_scan.json",
                    "blocked_orders",
                )
                if row:
                    rows.append(row)
    if rows:
        return _dedupe_rows(rows)
    return [
        row
        for row in all_rows
        if row.get("blocking_reasons") or str(row.get("status", "")).startswith("blocked")
    ]


def _rows_with_trustpilot_tags(rows):
    return [row for row in rows if row.get("trustpilot_invitation_present")]


def _rows_with_exact_review_request_tag(rows):
    return [row for row in rows if row.get("review_request_tag_present")]


def _latest_scan_summary(report):
    data = report.get("data") if report.get("loaded") else {}
    data = data if isinstance(data, dict) else {}
    return {
        "present": bool(report.get("present")),
        "loaded": bool(report.get("loaded")),
        "relative_path": report.get("relative_path", "logs/shopify_review_request_next_repeat_customer_candidate_scan.json"),
        "status": report.get("status", "missing"),
        "timestamp": _first_text(data, ("timestamp",)) or report.get("modified_at", ""),
        "generated_time": _first_text(data, ("timestamp",)) or report.get("modified_at", ""),
        "selected_order_name": _first_text(
            data,
            ("selected_order_name", "next_candidate_order_name"),
        ),
        "selected_masked_email": mask_email(
            _first_text(data, ("selected_masked_email", "next_candidate_masked_email"))
        ),
        "eligible_candidate_count": _int_or_zero(
            data.get("eligible_candidate_count")
            or data.get("eligible_repeat_customer_candidate_count")
        ),
        "next_candidate_count": _int_or_zero(data.get("next_candidate_count")),
        "report_status": _first_text(
            data,
            ("next_repeat_customer_candidate_scan_status", "report_status", "status"),
        )
        or report.get("status", "missing"),
    }


def _report_history(reports):
    rows = []
    for report in reports.values():
        rows.append(
            {
                "label": report["label"],
                "relative_path": report["relative_path"],
                "present": report["present"],
                "loaded": report["loaded"],
                "status": _safe_text(report.get("status")),
                "timestamp": _safe_text(report.get("timestamp")),
                "modified_at": _safe_text(report.get("modified_at")),
                "success": report.get("success"),
                "error": _safe_text(report.get("error")),
            }
        )
    return rows


def _safety_history(reports):
    rows = []
    for report in reports.values():
        data = report.get("data") if report.get("loaded") else {}
        if not isinstance(data, dict):
            continue
        flags = []
        true_flags = []
        for flag in SAFETY_FLAGS:
            if flag in data:
                value = bool(data.get(flag))
                flags.append({"name": flag, "value": value})
                if value:
                    true_flags.append(flag)
        safety_summary = data.get("safety_summary")
        if isinstance(safety_summary, dict):
            for flag in SAFETY_FLAGS:
                if flag in safety_summary and flag not in {item["name"] for item in flags}:
                    value = bool(safety_summary.get(flag))
                    flags.append({"name": flag, "value": value})
                    if value:
                        true_flags.append(flag)
        rows.append(
            {
                "label": report["label"],
                "relative_path": report["relative_path"],
                "status": _safe_text(report.get("status")),
                "timestamp": _safe_text(report.get("timestamp")),
                "flags": flags,
                "true_flags": true_flags,
                "true_flag_count": len(true_flags),
            }
        )
    return rows


def _summary(
    latest_scan,
    candidate_queue,
    invitation_history,
    review_request_queue,
    blocked_orders,
    reports,
    local_stats,
):
    candidate_data = (reports.get("candidate_scan") or {}).get("data") or {}
    next_data = (reports.get("next_candidate_scan") or {}).get("data") or {}
    classification_counts = (
        candidate_data.get("classification_counts")
        if isinstance(candidate_data.get("classification_counts"), dict)
        else {}
    )
    blocked_counts = (
        next_data.get("blocked_counts")
        if isinstance(next_data.get("blocked_counts"), dict)
        else {}
    )
    total_candidate_like = (
        _int_or_zero(candidate_data.get("orders_queried"))
        or _int_or_zero(next_data.get("total_orders_evaluated"))
        or local_stats.get("orders_with_email", 0)
    )
    blocked_returned = (
        _int_or_zero(classification_counts.get("blocked_returned_package"))
        or _int_or_zero(blocked_counts.get("returned_package_tag_detected"))
        or sum(
            1
            for row in blocked_orders
            if "returned" in row.get("blocking_summary", "").lower()
            or "return" in row.get("blocking_summary", "").lower()
        )
    )
    blocked_duplicate = (
        _int_or_zero(blocked_counts.get("existing_trustpilot_invitation_tag_or_alias_detected"))
        or sum(1 for row in blocked_orders if row.get("trustpilot_invitation_present"))
    )
    next_candidate = latest_scan.get("selected_order_name") or (
        candidate_queue[0]["order_name"] if candidate_queue else ""
    )
    next_candidate_email = latest_scan.get("selected_masked_email") or (
        candidate_queue[0]["masked_email"] if candidate_queue else ""
    )
    return [
        {
            "label": "Candidate-like orders",
            "value": total_candidate_like,
            "note": "From latest scan report, else local orders with email.",
        },
        {
            "label": "Trustpilot sent/tagged",
            "value": len(invitation_history),
            "note": "Detected from Trustpilot alias tags in local reports.",
        },
        {
            "label": f"Exact {EXACT_REVIEW_REQUEST_TAG}",
            "value": len(review_request_queue),
            "note": "Exact tag only; corrected spelling is not treated as equivalent.",
        },
        {
            "label": "Blocked returned package",
            "value": blocked_returned,
            "note": "From scan classification or blocking reasons if available.",
        },
        {
            "label": "Blocked duplicate Trustpilot",
            "value": blocked_duplicate,
            "note": "Trustpilot invitation alias already present.",
        },
        {
            "label": "Next candidate",
            "value": next_candidate or "None",
            "note": next_candidate_email or "No selected candidate in latest report.",
        },
    ]


def _tracking_design():
    return {
        "tracking_redirect_enabled": False,
        "limitations": (
            "Gmail alone cannot reliably confirm whether a customer clicked a "
            "Trustpilot link or left a review.",
        ),
        "future_click_tracking": (
            "A future write phase could create a local invitation record and a "
            "unique redirect token per invitation. That redirect route is not "
            "enabled in Phase 4.2."
        ),
        "future_review_detection": (
            "A future phase would need Trustpilot Business/API/export support "
            "or Kudosi/Ali Reviews API, webhook, or export support to detect "
            "reviews."
        ),
        "future_statuses": FUTURE_TRACKING_STATUSES,
    }


def _current_page_safety_confirmations():
    return [
        {"name": "shopify_write_performed", "value": False},
        {"name": "mutation_performed", "value": False},
        {"name": "tags_add_performed", "value": False},
        {"name": "tags_remove_performed", "value": False},
        {"name": "gmail_api_call_performed", "value": False},
        {"name": "gmail_draft_created", "value": False},
        {"name": "email_sent", "value": False},
        {"name": "kudosi_api_call_performed", "value": False},
        {"name": "ali_reviews_api_call_performed", "value": False},
        {"name": "trustpilot_api_call_performed", "value": False},
        {"name": "tracking_redirect_enabled", "value": False},
    ]


def _collect_tags(item):
    tags = []
    for key in (
        "tags",
        "tags_of_interest",
        "matched_trustpilot_invitation_tags",
        "customer_history_tags",
        "customer_order_tags",
        "historical_order_tags",
        "exact_tags_of_interest",
    ):
        tags.extend(_collect_tag_values(item.get(key), split_strings=(key == "tags")))

    for dict_key in ("safe_tags_summary", "tags_summary"):
        summary = item.get(dict_key)
        if not isinstance(summary, dict):
            continue
        for key in (
            "safe_tags",
            "tags_of_interest",
            "exact_tags_of_interest",
            "matched_trustpilot_invitation_tags",
        ):
            tags.extend(_collect_tag_values(summary.get(key)))
    return _dedupe_text(tags)


def _collect_tag_values(value, split_strings=False):
    if value is None:
        return []
    if isinstance(value, str):
        values = value.split(",") if split_strings else [value]
        return [_safe_tag(item) for item in values if _safe_tag(item)]
    if isinstance(value, (list, tuple, set)):
        return [_safe_tag(item) for item in value if _safe_tag(item)]
    return []


def _matched_trustpilot_tags(item, tags):
    normalized_aliases = {_normalize_trustpilot_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    matches = [
        tag
        for tag in tags
        if _normalize_trustpilot_tag(tag) in normalized_aliases
    ]
    for key in ("matched_trustpilot_invitation_tags",):
        matches.extend(_collect_string_list(item, key))
    for key in (
        "existing_trustpilot_invitation_tag_detected",
        "customer_historical_trustpilot_tag_detected",
        "contains_trustpilot_alias",
    ):
        if item.get(key) is True:
            matches.append(key)
    for dict_key in ("safe_tags_summary", "tags_summary"):
        summary = item.get(dict_key)
        if isinstance(summary, dict) and summary.get("contains_trustpilot_alias") is True:
            matches.append("contains_trustpilot_alias")
    return _dedupe_text(matches)


def _normalize_trustpilot_tag(tag):
    return re.sub(r"\s+", "", str(tag or "").strip().lower())


def _collect_string_list(item, key):
    value = item.get(key)
    if isinstance(value, str):
        return [_safe_text(value)] if value else []
    if isinstance(value, (list, tuple, set)):
        return [_safe_text(item) for item in value if _safe_text(item)]
    return []


def _first_text(mapping, keys):
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _safe_text(value)
    return ""


def _safe_tag(value):
    return _sanitize_text(value, max_length=120)


def _safe_text(value, max_length=300):
    return _sanitize_text(value, max_length=max_length)


def _sanitize_text(value, max_length=300):
    text = str(value or "")
    text = CONTROL_CHARS_RE.sub("", text)
    text = EMAIL_RE.sub(lambda match: mask_email(match.group(0)), text)
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = text.strip()
    if len(text) > max_length:
        return f"{text[:max_length]}..."
    return text


def _int_or_zero(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe_text(values):
    seen = set()
    result = []
    for value in values:
        text = _safe_text(value)
        if text and text not in seen:
            seen.add(text)
            result.append(text)
    return result


def _dedupe_rows(rows):
    seen = set()
    result = []
    for row in rows:
        if not row:
            continue
        key = (
            row.get("order_name") or "",
            row.get("order_id") or "",
            row.get("source_section") or "",
            row.get("status") or "",
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result
