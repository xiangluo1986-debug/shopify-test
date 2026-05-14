import hashlib
import re
import sqlite3

from remote_approval.utils import PROJECT_ROOT


CANONICAL_REVIEW_REQUEST_TAG = "1: review request"
TYPO_REVIEW_REQUEST_TAGS = ("1: reveiw request",)
DELIVERED_TAGS = ("Delivered", "妥投")

BLOCKED_MISSING_DELIVERED_TAG = "blocked_missing_delivered_tag"
BLOCKED_MISSING_REVIEW_REQUEST_TAG = "blocked_missing_review_request_tag"
BLOCKED_MERGED_ORDER_GROUP_NOT_READY = "blocked_merged_order_group_not_ready"
BLOCKED_EXISTING_TRUSTPILOT_INVITATION_CUSTOMER_LEVEL = (
    "blocked_existing_trustpilot_invitation_customer_level"
)
BLOCKED_RETURNED_PACKAGE = "blocked_returned_package"
BLOCKED_RISK_OR_TICKET = "blocked_risk_or_ticket"

TRUSTPILOT_ELIGIBILITY_BLOCKERS = (
    BLOCKED_MISSING_DELIVERED_TAG,
    BLOCKED_MISSING_REVIEW_REQUEST_TAG,
    BLOCKED_MERGED_ORDER_GROUP_NOT_READY,
    BLOCKED_EXISTING_TRUSTPILOT_INVITATION_CUSTOMER_LEVEL,
    BLOCKED_RETURNED_PACKAGE,
    BLOCKED_RISK_OR_TICKET,
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token|refresh[_\s-]?token|client[_\s-]?secret|api[_\s-]?key|password|secret)"
)
MERGED_ORDER_RE = re.compile(
    r"(?i)(merged|merge|combined|combine|combined[_ -]?order|merged[_ -]?order|合并|合併|併單|并单|鍚堝苟)"
)
RISK_TEXT_RE = re.compile(
    r"(?i)(refund|cancel|chargeback|dispute|complaint|shipping[_ -]?issue|delivery[_ -]?issue|"
    r"ticket_risk|ticket_blocked|blocked_ticket|returned_package|return_or_shipping_issue)"
)


def eligibility_policy_summary() -> dict:
    return {
        "delivered_required": True,
        "delivered_tags_or_statuses": list(DELIVERED_TAGS),
        "canonical_review_request_tag_required": CANONICAL_REVIEW_REQUEST_TAG,
        "typo_review_request_tags_reported_but_not_canonical": list(TYPO_REVIEW_REQUEST_TAGS),
        "merged_or_related_order_group_must_be_ready": True,
        "customer_level_duplicate_suppression_required": True,
        "existing_risk_blockers_required": True,
        "raw_customer_email_output": False,
        "email_hash_output": False,
    }


def source_report_order_rows(report: dict) -> list[dict]:
    rows = []
    if not isinstance(report, dict):
        return rows
    for key in (
        "orders",
        "evaluated_orders",
        "ready_candidate_queue",
        "repeat_customer_candidates",
        "blocked_orders",
        "decisions",
        "selected_candidate",
        "selected_candidate_summary",
    ):
        value = report.get(key)
        if isinstance(value, dict):
            rows.append(value)
        elif isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    for key in ("source_candidate_scan_summary", "source_package_summary", "source_preflight_summary"):
        value = report.get(key)
        if isinstance(value, dict):
            rows.append(value)
    return rows


def build_trustpilot_eligibility_context(rows: list[dict]) -> dict:
    public_rows = _merge_public_order_rows(rows)
    identities, db_status = _load_local_order_identities(list(public_rows.keys()))
    group_by_key = {}
    order_to_group_key = {}
    for order_name, row in public_rows.items():
        identity = identities.get(order_name) or {}
        group_key = _related_group_key(row, identity)
        if not group_key:
            continue
        order_to_group_key[order_name] = group_key
        group_by_key.setdefault(group_key, []).append(row)
    return {
        "_rows_by_order": public_rows,
        "_order_to_group_key": order_to_group_key,
        "_group_by_key": group_by_key,
        "local_db_related_lookup": db_status,
        "related_order_group_count": sum(1 for group in group_by_key.values() if len(group) > 1),
    }


def evaluate_trustpilot_candidate_eligibility(
    candidate: dict,
    context: dict | None = None,
    customer_level_duplicate: dict | None = None,
    existing_blocking_reasons: list[str] | None = None,
) -> dict:
    context = context or build_trustpilot_eligibility_context([candidate])
    base_row = _public_order_row(candidate)
    order_name = base_row["order_name"]
    merged_row = dict((context.get("_rows_by_order") or {}).get(order_name) or {})
    row = _merge_two_rows(merged_row, base_row) if merged_row else base_row

    tag_evidence = _tag_evidence(row)
    related_guard = _related_order_guard(row, context)
    customer_level_duplicate = customer_level_duplicate or {}
    existing_blocking_reasons = _dedupe_text(existing_blocking_reasons or row.get("blocking_reasons") or [])

    blocker_reasons = []
    blocker_details = []
    if not tag_evidence["delivered_tag_present"]:
        blocker_reasons.append(BLOCKED_MISSING_DELIVERED_TAG)
        blocker_details.append("Delivered / 妥投 tag or delivered status is missing.")
    if not tag_evidence["canonical_review_request_tag_present"]:
        blocker_reasons.append(BLOCKED_MISSING_REVIEW_REQUEST_TAG)
        blocker_details.append(f"Canonical {CANONICAL_REVIEW_REQUEST_TAG} tag is missing.")
    if related_guard["merged_or_related_order_guard_status"] != "ready":
        if related_guard["merged_or_related_order_guard_status"] != "not_applicable":
            blocker_reasons.append(BLOCKED_MERGED_ORDER_GROUP_NOT_READY)
            blocker_details.append("Merged or related order group is not fully delivered/ready.")
    if customer_level_duplicate.get("customer_level_duplicate_block_applies") is True:
        blocker_reasons.append(BLOCKED_EXISTING_TRUSTPILOT_INVITATION_CUSTOMER_LEVEL)
        blocker_details.append("Same customer/email already has a Trustpilot invitation signal.")
    if _returned_package_detected(row, existing_blocking_reasons):
        blocker_reasons.append(BLOCKED_RETURNED_PACKAGE)
        blocker_details.append("Returned package or return-risk evidence is present.")
    if _risk_or_ticket_detected(row, existing_blocking_reasons):
        blocker_reasons.append(BLOCKED_RISK_OR_TICKET)
        blocker_details.append("Risk, ticket, refund, cancel, dispute, or shipping blocker is present.")

    blocker_reasons = _dedupe_text(blocker_reasons)
    classification = blocker_reasons[0] if blocker_reasons else "eligible_for_trustpilot"
    eligible = not blocker_reasons
    return {
        "audit_order_name": order_name,
        "order_name": order_name,
        "masked_email": _safe_masked_email(row.get("masked_email", "")),
        "delivered_tag_present": tag_evidence["delivered_tag_present"],
        "delivered_indicator_present": tag_evidence["delivered_tag_present"],
        "delivered_evidence": tag_evidence["delivered_evidence"],
        "canonical_review_request_tag": CANONICAL_REVIEW_REQUEST_TAG,
        "canonical_review_request_tag_present": tag_evidence["canonical_review_request_tag_present"],
        "review_request_tag_typo_detected": tag_evidence["review_request_tag_typo_detected"],
        "typo_review_request_tags_detected": tag_evidence["typo_review_request_tags_detected"],
        "returned_package_detected": _returned_package_detected(row, existing_blocking_reasons),
        "risk_or_ticket_detected": _risk_or_ticket_detected(row, existing_blocking_reasons),
        "merged_or_related_order_guard_status": related_guard["merged_or_related_order_guard_status"],
        "merged_or_combined_indicator_present": related_guard["merged_or_combined_indicator_present"],
        "related_order_names": related_guard["related_order_names"],
        "related_order_count": related_guard["related_order_count"],
        "related_orders": related_guard["related_orders"],
        "eligible_for_trustpilot": eligible,
        "classification": classification,
        "blocking_reasons": blocker_reasons,
        "blocker_details": _dedupe_text(blocker_details),
        "policy": eligibility_policy_summary(),
    }


def source_eligibility_summary(source: dict) -> dict:
    if not isinstance(source, dict):
        return {}
    for key in (
        "trustpilot_eligibility_summary",
        "selected_candidate_trustpilot_eligibility",
        "candidate_trustpilot_eligibility",
    ):
        value = source.get(key)
        if isinstance(value, dict):
            return value
    selected = source.get("selected_candidate_summary")
    if isinstance(selected, dict):
        value = selected.get("trustpilot_eligibility_summary")
        if isinstance(value, dict):
            return value
    return {}


def eligibility_blocking_conditions(summary: dict) -> list[dict]:
    if not isinstance(summary, dict) or not summary:
        return [
            {
                "status": "blocked_missing_trustpilot_eligibility_recheck",
                "detail": "Source report does not include the required Trustpilot eligibility re-check.",
            }
        ]
    if summary.get("eligible_for_trustpilot") is True:
        return []
    blockers = summary.get("blocking_reasons") or [summary.get("classification") or "blocked_trustpilot_eligibility"]
    details = summary.get("blocker_details") or []
    conditions = []
    for index, blocker in enumerate(_dedupe_text(blockers)):
        conditions.append(
            {
                "status": _safe_text(blocker),
                "detail": _safe_text(details[index] if index < len(details) else "Trustpilot eligibility gate failed."),
            }
        )
    return conditions


def _merge_public_order_rows(rows: list[dict]) -> dict:
    merged = {}
    for item in rows or []:
        if not isinstance(item, dict):
            continue
        row = _public_order_row(item)
        order_name = row["order_name"]
        if not order_name:
            continue
        merged[order_name] = _merge_two_rows(merged.get(order_name, {}), row)
    return merged


def _merge_two_rows(left: dict, right: dict) -> dict:
    if not left:
        return dict(right)
    result = dict(left)
    for key in ("order_id_or_gid", "masked_email", "source_decision", "status", "created_at"):
        if not result.get(key) and right.get(key):
            result[key] = right[key]
    for key in ("tags", "status_values", "classification_buckets", "blocking_reasons"):
        result[key] = _dedupe_text([*(result.get(key) or []), *(right.get(key) or [])])
    for key in ("ticket_risk_detected", "ticket_blocked", "repeat_customer_detected"):
        result[key] = bool(result.get(key) or right.get(key))
    return result


def _public_order_row(item: dict) -> dict:
    order_name = _first_text(
        item,
        (
            "order_name",
            "name",
            "selected_order_name",
            "next_candidate_order_name",
            "audit_order_name",
        ),
    )
    return {
        "order_name": order_name,
        "order_id_or_gid": _first_text(item, ("order_id_or_gid", "order_id", "id")),
        "masked_email": _safe_masked_email(
            _first_text(item, ("masked_email", "selected_masked_email", "next_candidate_masked_email", "email"))
        ),
        "created_at": _first_text(item, ("createdAt", "created_at", "order_created_at", "processed_at", "timestamp")),
        "tags": _collect_tags(item),
        "status_values": _collect_status_values(item),
        "classification_buckets": _collect_string_list(item, "classification_buckets"),
        "blocking_reasons": _dedupe_text(
            [
                *_collect_string_list(item, "blocking_reasons"),
                *_collect_string_list(item, "classification_reasons"),
            ]
        ),
        "source_decision": _first_text(item, ("source_decision", "decision", "classification", "candidate_status", "status")),
        "ticket_risk_detected": item.get("ticket_risk_detected") is True or item.get("ticket_blocked") is True,
        "ticket_blocked": item.get("ticket_blocked") is True,
        "repeat_customer_detected": item.get("repeat_customer_detected") is True,
        "customer_id": _first_text(item, ("customer_id", "customer_id_or_gid")),
    }


def _tag_evidence(row: dict) -> dict:
    tags = [str(tag) for tag in row.get("tags") or []]
    status_values = [str(value) for value in row.get("status_values") or []]
    delivered_tags = [tag for tag in tags if tag in DELIVERED_TAGS]
    delivered_statuses = [value for value in status_values if _is_delivered_status_evidence(value)]
    typo_tags = [tag for tag in tags if tag in TYPO_REVIEW_REQUEST_TAGS]
    return {
        "delivered_tag_present": bool(delivered_tags or delivered_statuses),
        "delivered_evidence": _dedupe_text([*delivered_tags, *delivered_statuses])[:5],
        "canonical_review_request_tag_present": any(tag == CANONICAL_REVIEW_REQUEST_TAG for tag in tags),
        "review_request_tag_typo_detected": bool(typo_tags),
        "typo_review_request_tags_detected": _dedupe_text(typo_tags),
    }


def _related_order_guard(row: dict, context: dict) -> dict:
    order_name = row.get("order_name", "")
    rows_by_order = context.get("_rows_by_order") or {}
    group_key = (context.get("_order_to_group_key") or {}).get(order_name, "")
    related_rows = list((context.get("_group_by_key") or {}).get(group_key, [])) if group_key else []
    if order_name and order_name not in {item.get("order_name") for item in related_rows}:
        related_rows.append(rows_by_order.get(order_name) or row)
    related_rows = _dedupe_related_rows(related_rows)
    merged_indicator_present = _merged_indicator_present(row)
    if not related_rows:
        related_rows = [row]

    related_public = []
    undelivered = []
    for related in related_rows:
        evidence = _tag_evidence(related)
        item = {
            "order_name": _safe_text(related.get("order_name", "")),
            "delivered_tag_present": evidence["delivered_tag_present"],
            "canonical_review_request_tag_present": evidence["canonical_review_request_tag_present"],
            "review_request_tag_typo_detected": evidence["review_request_tag_typo_detected"],
        }
        related_public.append(item)
        if not evidence["delivered_tag_present"]:
            undelivered.append(item["order_name"])

    if len(related_public) <= 1 and not merged_indicator_present:
        status = "ready"
        public_names = []
    elif merged_indicator_present and len(related_public) <= 1:
        status = "uncertain"
        public_names = [item["order_name"] for item in related_public if item["order_name"]]
    elif undelivered:
        status = "not_ready"
        public_names = [item["order_name"] for item in related_public if item["order_name"]]
    else:
        status = "ready"
        public_names = [item["order_name"] for item in related_public if item["order_name"]]

    return {
        "merged_or_related_order_guard_status": status,
        "merged_or_combined_indicator_present": merged_indicator_present,
        "related_order_names": public_names,
        "related_order_count": len(public_names),
        "related_orders": related_public[:10] if public_names or merged_indicator_present else [],
    }


def _is_delivered_status_evidence(value: str) -> bool:
    text = str(value or "").strip()
    lowered = text.lower()
    if not text:
        return False
    if lowered in {"delivered", "delivered_status", "status_delivered"} or text == "妥投":
        return True
    return "exact delivered tag is present" in lowered or "delivered tag is present" in lowered


def _load_local_order_identities(order_names: list[str]) -> tuple[dict, dict]:
    order_names = _dedupe_text(order_names)
    db_path = PROJECT_ROOT / "backend" / "db.sqlite3"
    status = {
        "sqlite_db_path": "backend/db.sqlite3",
        "sqlite_read_only": True,
        "sqlite_db_present": db_path.exists(),
        "lookup_attempted": bool(order_names),
        "orders_requested_count": len(order_names),
        "orders_found_count": 0,
        "error_sanitized": "",
        "raw_customer_email_output": False,
        "email_hash_output": False,
    }
    identities = {}
    if not order_names or not db_path.exists():
        return identities, status

    placeholders = ",".join("?" for _ in order_names)
    try:
        with sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT order_name, customer_email, customer_name
                FROM shopify_sync_shopifyorder
                WHERE order_name IN ({placeholders})
                """,
                order_names,
            ).fetchall()
    except sqlite3.Error as exc:
        status["error_sanitized"] = _safe_text(str(exc))[:300]
        return identities, status

    status["orders_found_count"] = len(rows)
    for row in rows:
        email = _normalize_email(row["customer_email"])
        identities[_safe_text(row["order_name"])] = {
            "order_name": _safe_text(row["order_name"]),
            "masked_email": _mask_email(email),
            "customer_name_present": bool(str(row["customer_name"] or "").strip()),
            "_email_key": _email_key(email),
        }
    return identities, status


def _related_group_key(row: dict, identity: dict) -> str:
    customer_id = _safe_text(row.get("customer_id", ""))
    if customer_id:
        return f"customer_id:{customer_id}"
    if identity.get("_email_key"):
        return f"email:{identity['_email_key']}"
    masked = _safe_masked_email(identity.get("masked_email") or row.get("masked_email", ""))
    if masked:
        return f"masked:{masked.lower()}"
    return ""


def _collect_tags(item: dict) -> list[str]:
    tags = []
    for key in (
        "tags",
        "tags_of_interest",
        "matched_trustpilot_invitation_tags",
        "customer_history_tags",
        "customer_order_tags",
        "historical_order_tags",
        "customer_historical_order_tags",
        "exact_tags_of_interest",
    ):
        tags.extend(_collect_tag_values(item.get(key), split_strings=key == "tags"))
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
    values.extend(_collect_string_list(item, "classification_reasons"))
    values.extend(_collect_string_list(item, "blocking_reasons"))
    risk_summary = item.get("risk_summary")
    if isinstance(risk_summary, dict):
        values.extend(_collect_string_list(risk_summary, "classification_reasons"))
    return _dedupe_text(values)


def _collect_tag_values(value, split_strings=False) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = value.split(",") if split_strings else [value]
        return [_safe_text(item, max_length=120) for item in values if _safe_text(item, max_length=120)]
    if isinstance(value, (list, tuple, set)):
        return [_safe_text(item, max_length=120) for item in value if _safe_text(item, max_length=120)]
    return []


def _collect_string_list(item: dict, key: str) -> list[str]:
    value = item.get(key)
    if isinstance(value, str):
        return [_safe_text(value)] if value else []
    if isinstance(value, (list, tuple, set)):
        return [_safe_text(item) for item in value if _safe_text(item)]
    return []


def _returned_package_detected(row: dict, existing_blocking_reasons: list[str]) -> bool:
    haystack = " ".join(
        [
            *(row.get("tags") or []),
            *(row.get("classification_buckets") or []),
            *(row.get("status_values") or []),
            *existing_blocking_reasons,
        ]
    ).lower()
    compact = re.sub(r"[\s_-]+", "", haystack)
    return "returnedpackage" in compact or "returnpackage" in compact or "returned_package" in haystack


def _risk_or_ticket_detected(row: dict, existing_blocking_reasons: list[str]) -> bool:
    if row.get("ticket_risk_detected") or row.get("ticket_blocked"):
        return True
    haystack = " ".join(
        [
            row.get("source_decision", ""),
            *(row.get("classification_buckets") or []),
            *(row.get("blocking_reasons") or []),
            *existing_blocking_reasons,
        ]
    )
    haystack = re.sub(r"(?i)\bnon[- ]cancelled\b|\bnon[- ]canceled\b", "", haystack)
    return bool(RISK_TEXT_RE.search(haystack))


def _merged_indicator_present(row: dict) -> bool:
    haystack = " ".join(
        [
            *(row.get("tags") or []),
            *(row.get("classification_buckets") or []),
            *(row.get("blocking_reasons") or []),
            *(row.get("status_values") or []),
        ]
    )
    return bool(MERGED_ORDER_RE.search(haystack))


def _dedupe_related_rows(rows: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for row in rows:
        name = _safe_text(row.get("order_name", ""))
        key = name or _safe_text(row.get("order_id_or_gid", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _first_text(mapping: dict, keys: tuple[str, ...]) -> str:
    if not isinstance(mapping, dict):
        return ""
    for key in keys:
        value = mapping.get(key)
        if value not in (None, ""):
            return _safe_text(value)
    return ""


def _normalize_email(email: str) -> str:
    email = str(email or "").strip().lower()
    return email if EMAIL_RE.fullmatch(email) else ""


def _email_key(email: str) -> str:
    email = _normalize_email(email)
    if not email:
        return ""
    return hashlib.sha256(email.encode("utf-8")).hexdigest()


def _safe_masked_email(value) -> str:
    text = _safe_text(value)
    if not text or "@" not in text:
        return ""
    if "***" in text:
        return text
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), text)


def _mask_email(email: str) -> str:
    email = _normalize_email(email)
    if not email:
        return ""
    local, domain = email.split("@", 1)
    return f"{local[:1] or '*'}***@{domain}"


def _safe_text(value, max_length=300) -> str:
    text = SENSITIVE_TEXT_RE.sub("[redacted]", str(value or ""))
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", text)
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
