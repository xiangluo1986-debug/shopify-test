import hashlib
import json
import re
import sqlite3
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT


CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION = "blocked_existing_trustpilot_invitation_customer_level"
CUSTOMER_LEVEL_DUPLICATE_NOT_DETECTED = "customer_level_duplicate_not_detected"
CANONICAL_TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SENSITIVE_TEXT_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token|refresh[_\s-]?token|client[_\s-]?secret|api[_\s-]?key|password|secret)"
)

SOURCE_REPORTS = {
    "trustpilot_gmail_send_audit": LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.json",
    "trustpilot_tag_write_audit": LOG_DIR / "shopify_review_request_trustpilot_tag_write_audit.json",
    "trustpilot_tag_write_execute": LOG_DIR / "shopify_review_request_trustpilot_tag_write_execute.json",
    "trustpilot_gmail_one_draft_send_execute": LOG_DIR
    / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.json",
    "trustpilot_one_candidate_gmail_draft_send_execute": LOG_DIR
    / "shopify_review_request_trustpilot_one_candidate_gmail_draft_send_execute.json",
    "candidate_scan": LOG_DIR / "shopify_review_request_candidate_scan.json",
    "unified_decision_engine": LOG_DIR / "shopify_review_request_unified_decision_engine_dry_run.json",
    "next_repeat_customer_candidate_scan": LOG_DIR
    / "shopify_review_request_next_repeat_customer_candidate_scan.json",
}


def build_customer_level_duplicate_context(order_names=None, extra_rows=None) -> dict:
    order_names = _dedupe_text(order_names or [])
    for row in extra_rows or []:
        if isinstance(row, dict):
            name = _safe_text(row.get("order_name") or row.get("selected_order_name") or "")
            if name:
                order_names.append(name)

    source_reports = _load_source_reports()
    prior_records = _prior_trustpilot_invitation_records(source_reports)
    for record in prior_records:
        if record["order_name"]:
            order_names.append(record["order_name"])

    identities, db_status = _load_local_order_identities(_dedupe_text(order_names))
    enriched_records = [_enrich_prior_record(record, identities) for record in prior_records]
    return {
        "_identity_by_order": identities,
        "_prior_invitation_records": enriched_records,
        "source_report_status": _source_report_status(source_reports),
        "local_db_identity_lookup": db_status,
        "public_summary": _public_context_summary(enriched_records, db_status, source_reports),
    }


def evaluate_customer_level_duplicate(order_name: str, masked_email: str = "", context: dict | None = None) -> dict:
    context = context or build_customer_level_duplicate_context([order_name])
    order_name = _safe_text(order_name)
    identity = _candidate_identity(order_name, masked_email, context.get("_identity_by_order", {}))
    matches = []
    for record in context.get("_prior_invitation_records", []):
        basis = _match_basis(identity, record)
        if not basis:
            continue
        matches.append({**_public_prior_record(record), "match_basis": basis})

    matches = _dedupe_prior_matches(matches)
    first_match = _preferred_prior_match(order_name, matches)
    same_email_detected = any(
        "same_normalized_email_hash" in match["match_basis"]
        or "same_masked_email_from_safe_reports" in match["match_basis"]
        for match in matches
    )
    same_customer_id_detected = any("same_customer_id" in match["match_basis"] for match in matches)
    same_customer_detected = bool(matches)
    return {
        "customer_level_duplicate_block_applies": bool(matches),
        "classification": CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION if matches else CUSTOMER_LEVEL_DUPLICATE_NOT_DETECTED,
        "selected_order_name": order_name,
        "selected_masked_email": identity["masked_email"],
        "same_customer_detected": same_customer_detected,
        "same_email_detected": same_email_detected,
        "same_masked_email_detected": any(
            "same_masked_email_from_safe_reports" in match["match_basis"] for match in matches
        ),
        "same_customer_id_detected": same_customer_id_detected,
        "same_customer_detection_basis": _dedupe_text(
            basis for match in matches for basis in match.get("match_basis", [])
        ),
        "prior_trustpilot_invitation_detected": bool(matches),
        "prior_trustpilot_order_name": first_match.get("order_name", "") if first_match else "",
        "prior_trustpilot_invitation_sources": _dedupe_text(
            match.get("source_key", "") for match in matches if match.get("source_key")
        ),
        "prior_trustpilot_invitation_matches": matches[:10],
        "existing_unsent_gmail_draft_should_not_be_sent": bool(matches),
        "future_optional_draft_cleanup_needs_separate_locked_phase": bool(matches),
    }


def compare_order_customer_identity(order_a: str, order_b: str, context: dict | None = None) -> dict:
    context = context or build_customer_level_duplicate_context([order_a, order_b])
    identities = context.get("_identity_by_order", {})
    identity_a = _candidate_identity(order_a, "", identities)
    identity_b = _candidate_identity(order_b, "", identities)
    basis = _match_basis(identity_a, identity_b)
    return {
        "audit_order_a": _safe_text(order_a),
        "audit_order_b": _safe_text(order_b),
        "same_customer_detected": bool(basis),
        "same_email_detected": (
            "same_normalized_email_hash" in basis or "same_masked_email_from_safe_reports" in basis
        ),
        "same_masked_email_detected": "same_masked_email_from_safe_reports" in basis,
        "same_customer_id_detected": "same_customer_id" in basis,
        "same_customer_detection_basis": basis,
        "order_a_identity": _public_identity(identity_a),
        "order_b_identity": _public_identity(identity_b),
    }


def public_context_summary(context: dict) -> dict:
    return context.get("public_summary") or {}


def trustpilot_alias_coverage() -> dict:
    normalized_required = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    return {
        "canonical_tag": CANONICAL_TRUSTPILOT_TAG,
        "configured_aliases": TRUSTPILOT_TAG_ALIASES,
        "normalized_configured_aliases": sorted(normalized_required),
        "customer_level_duplicate_classification": CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
        "customer_level_duplicate_uses_prior_send_or_tag_reports": True,
        "customer_level_duplicate_uses_local_db_email_hash_in_memory_only": True,
        "customer_level_duplicate_allows_masked_email_fallback": True,
    }


def _load_source_reports() -> dict:
    reports = {}
    for key, path in SOURCE_REPORTS.items():
        data = {}
        error = ""
        if not path.exists():
            error = "missing_source_report"
        else:
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
            except json.JSONDecodeError as exc:
                error = _sanitize_text(f"source_report_json_parse_error: {exc}")
        reports[key] = {"path": str(path), "present": path.exists(), "data": data, "error_sanitized": error}
    return reports


def _source_report_status(source_reports: dict) -> dict:
    return {
        key: {
            "path": report["path"],
            "present": report["present"],
            "task_name": _safe_text((report.get("data") or {}).get("task_name", "")),
            "success": (report.get("data") or {}).get("success") is True,
            "error_sanitized": _safe_text(report.get("error_sanitized", "")),
        }
        for key, report in source_reports.items()
    }


def _prior_trustpilot_invitation_records(source_reports: dict) -> list[dict]:
    records = []
    for key, report in source_reports.items():
        data = report.get("data") or {}
        if not isinstance(data, dict):
            continue
        records.extend(_direct_success_records(key, report["path"], data))
        if key in {"candidate_scan", "unified_decision_engine", "next_repeat_customer_candidate_scan"}:
            records.extend(_trustpilot_tag_records_from_report(key, report["path"], data))
    return _dedupe_prior_records(records)


def _direct_success_records(source_key: str, path: str, data: dict) -> list[dict]:
    status = _report_status(data)
    success = data.get("success") is True
    order_name = _safe_text(data.get("selected_order_name", ""))
    masked_email = _safe_masked_email(data.get("selected_masked_email", ""))
    if not order_name:
        return []

    records = []
    if (
        source_key in {"trustpilot_gmail_send_audit", "trustpilot_gmail_one_draft_send_execute"}
        and success
        and (status in {"trustpilot_gmail_one_draft_send_audit_passed", "real_gmail_draft_sent_and_verified"})
        and _safe_int(data.get("sent_count") or data.get("source_sent_count")) >= 1
    ):
        records.append(
            _base_prior_record(
                source_key,
                path,
                order_name,
                masked_email,
                "successful_trustpilot_gmail_send_report",
                status,
            )
        )
    if (
        source_key == "trustpilot_one_candidate_gmail_draft_send_execute"
        and success
        and status == "real_gmail_draft_sent_and_verified"
        and _safe_int(data.get("sent_count")) >= 1
    ):
        records.append(
            _base_prior_record(
                source_key,
                path,
                order_name,
                masked_email,
                "successful_trustpilot_gmail_send_report",
                status,
            )
        )
    if (
        source_key == "trustpilot_tag_write_execute"
        and success
        and status == "one_trustpilot_tag_written_and_needs_audit"
        and data.get("shopify_write_performed") is True
        and (data.get("tags_add_performed") is True or data.get("tagsAdd_performed") is True)
    ):
        record = _base_prior_record(
            source_key,
            path,
            order_name,
            masked_email,
            "successful_trustpilot_tag_write_report",
            status,
        )
        record["matched_trustpilot_invitation_tags"] = [CANONICAL_TRUSTPILOT_TAG]
        records.append(record)
    if (
        source_key == "trustpilot_tag_write_audit"
        and success
        and status == "trustpilot_tag_write_audit_passed"
        and (_matched_trustpilot_tags(data) or data.get("post_write_tag_present") is True)
    ):
        record = _base_prior_record(
            source_key,
            path,
            order_name,
            masked_email,
            "successful_trustpilot_tag_write_audit_report",
            status,
        )
        record["matched_trustpilot_invitation_tags"] = _matched_trustpilot_tags(data) or [CANONICAL_TRUSTPILOT_TAG]
        records.append(record)
    return records


def _trustpilot_tag_records_from_report(source_key: str, path: str, data: dict) -> list[dict]:
    records = []
    for row in _order_rows_for_source(source_key, data):
        order_name = _safe_text(row.get("order_name") or row.get("selected_order_name") or "")
        if not order_name:
            continue
        matched_tags = _matched_trustpilot_tags(row)
        trustpilot_decision = _safe_text(row.get("decision", "")) == "blocked_existing_trustpilot_invitation_tag"
        trustpilot_flags = (
            row.get("existing_trustpilot_invitation_tag_detected") is True
            or row.get("customer_historical_trustpilot_tag_detected") is True
            or row.get("contains_trustpilot_alias") is True
        )
        if not matched_tags and not trustpilot_decision and not trustpilot_flags:
            continue
        masked_email = _safe_masked_email(
            row.get("masked_email") or row.get("selected_masked_email") or row.get("next_candidate_masked_email") or ""
        )
        record = _base_prior_record(
            source_key,
            path,
            order_name,
            masked_email,
            "trustpilot_alias_tag_in_local_report",
            _safe_text(row.get("decision") or row.get("candidate_status") or ""),
        )
        record["matched_trustpilot_invitation_tags"] = matched_tags or ["trustpilot_alias_present_in_source_summary"]
        records.append(record)
    return records


def _order_rows_for_source(source_key: str, data: dict) -> list[dict]:
    keys_by_source = {
        "candidate_scan": ("orders", "blocked_orders", "repeat_customer_candidates"),
        "unified_decision_engine": ("decisions",),
        "next_repeat_customer_candidate_scan": ("evaluated_orders", "ready_candidate_queue", "selected_candidate"),
    }
    rows = []
    for key in keys_by_source.get(source_key, ()):
        value = data.get(key)
        if isinstance(value, dict):
            rows.append(value)
        elif isinstance(value, list):
            rows.extend(item for item in value if isinstance(item, dict))
    return rows


def _walk_order_dicts(value):
    if isinstance(value, dict):
        if "order_name" in value or "selected_order_name" in value:
            yield value
        for nested in value.values():
            yield from _walk_order_dicts(nested)
    elif isinstance(value, list):
        for item in value:
            yield from _walk_order_dicts(item)


def _base_prior_record(source_key: str, path: str, order_name: str, masked_email: str, signal_type: str, status: str) -> dict:
    return {
        "source_key": source_key,
        "path": path,
        "order_name": _safe_text(order_name),
        "masked_email": _safe_masked_email(masked_email),
        "signal_type": signal_type,
        "status": _safe_text(status),
        "prior_trustpilot_invitation_detected": True,
        "matched_trustpilot_invitation_tags": [],
        "customer_id_available": False,
        "customer_id_present": False,
        "_email_key": "",
        "_customer_id_key": "",
    }


def _load_local_order_identities(order_names: list[str]) -> tuple[dict, dict]:
    db_path = PROJECT_ROOT / "backend" / "db.sqlite3"
    status = {
        "sqlite_db_path": "backend/db.sqlite3",
        "sqlite_read_only": True,
        "sqlite_db_present": db_path.exists(),
        "lookup_attempted": bool(order_names),
        "orders_requested_count": len(order_names),
        "orders_found_count": 0,
        "customer_id_available": False,
        "error_sanitized": "",
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
                SELECT order_name, shopify_order_id, customer_email, customer_name
                FROM shopify_sync_shopifyorder
                WHERE order_name IN ({placeholders})
                """,
                order_names,
            ).fetchall()
    except sqlite3.Error as exc:
        status["error_sanitized"] = _sanitize_text(str(exc))[:300]
        return identities, status

    status["orders_found_count"] = len(rows)
    for row in rows:
        email = _normalize_email(row["customer_email"])
        identities[_safe_text(row["order_name"])] = {
            "order_name": _safe_text(row["order_name"]),
            "masked_email": _mask_email(email),
            "email_present": bool(email),
            "local_db_order_found": True,
            "shopify_order_id_present": bool(row["shopify_order_id"]),
            "customer_name_present": bool(str(row["customer_name"] or "").strip()),
            "customer_id_available": False,
            "customer_id_present": False,
            "_email_key": _email_key(email),
            "_customer_id_key": "",
        }
    return identities, status


def _enrich_prior_record(record: dict, identities: dict) -> dict:
    identity = identities.get(record["order_name"]) or {}
    if identity.get("masked_email"):
        record["masked_email"] = identity["masked_email"]
    record["_email_key"] = identity.get("_email_key", "")
    record["_customer_id_key"] = identity.get("_customer_id_key", "")
    record["customer_id_available"] = bool(identity.get("customer_id_available"))
    record["customer_id_present"] = bool(identity.get("customer_id_present"))
    return record


def _candidate_identity(order_name: str, masked_email: str, identities: dict) -> dict:
    identity = dict(identities.get(_safe_text(order_name)) or {})
    if not identity:
        identity = {
            "order_name": _safe_text(order_name),
            "masked_email": "",
            "email_present": False,
            "local_db_order_found": False,
            "shopify_order_id_present": False,
            "customer_name_present": False,
            "customer_id_available": False,
            "customer_id_present": False,
            "_email_key": "",
            "_customer_id_key": "",
        }
    fallback_mask = _safe_masked_email(masked_email)
    if fallback_mask and not identity.get("masked_email"):
        identity["masked_email"] = fallback_mask
    return identity


def _match_basis(candidate: dict, prior: dict) -> list[str]:
    basis = []
    if candidate.get("order_name") and candidate.get("order_name") == prior.get("order_name"):
        basis.append("same_order_name_prior_trustpilot_report")
    if candidate.get("_customer_id_key") and candidate.get("_customer_id_key") == prior.get("_customer_id_key"):
        basis.append("same_customer_id")
    if candidate.get("_email_key") and candidate.get("_email_key") == prior.get("_email_key"):
        basis.append("same_normalized_email_hash")
    candidate_mask = _safe_masked_email(candidate.get("masked_email", ""))
    prior_mask = _safe_masked_email(prior.get("masked_email", ""))
    if candidate_mask and candidate_mask == prior_mask:
        basis.append("same_masked_email_from_safe_reports")
    return _dedupe_text(basis)


def _public_context_summary(records: list[dict], db_status: dict, source_reports: dict) -> dict:
    return {
        "customer_level_duplicate_suppression_enabled": True,
        "classification": CUSTOMER_LEVEL_DUPLICATE_CLASSIFICATION,
        "local_db_identity_lookup": db_status,
        "prior_trustpilot_invitation_record_count": len(records),
        "prior_trustpilot_invitation_orders": [_public_prior_record(record) for record in records[:20]],
        "source_report_status": _source_report_status(source_reports),
        "trustpilot_tag_matching_policy": trustpilot_alias_coverage(),
        "raw_customer_email_output": False,
        "email_hash_output": False,
    }


def _public_prior_record(record: dict) -> dict:
    return {
        "source_key": _safe_text(record.get("source_key", "")),
        "path": _safe_text(record.get("path", "")),
        "order_name": _safe_text(record.get("order_name", "")),
        "masked_email": _safe_masked_email(record.get("masked_email", "")),
        "signal_type": _safe_text(record.get("signal_type", "")),
        "status": _safe_text(record.get("status", "")),
        "prior_trustpilot_invitation_detected": record.get("prior_trustpilot_invitation_detected") is True,
        "matched_trustpilot_invitation_tags": [
            _safe_text(tag) for tag in record.get("matched_trustpilot_invitation_tags", []) if _safe_text(tag)
        ],
        "customer_id_available": record.get("customer_id_available") is True,
        "customer_id_present": record.get("customer_id_present") is True,
    }


def _public_identity(identity: dict) -> dict:
    return {
        "order_name": _safe_text(identity.get("order_name", "")),
        "masked_email": _safe_masked_email(identity.get("masked_email", "")),
        "email_present": identity.get("email_present") is True,
        "local_db_order_found": identity.get("local_db_order_found") is True,
        "shopify_order_id_present": identity.get("shopify_order_id_present") is True,
        "customer_name_present": identity.get("customer_name_present") is True,
        "customer_id_available": identity.get("customer_id_available") is True,
        "customer_id_present": identity.get("customer_id_present") is True,
    }


def _dedupe_prior_records(records: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for record in records:
        key = (
            record.get("source_key"),
            record.get("order_name"),
            record.get("masked_email"),
            record.get("signal_type"),
            record.get("status"),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(record)
    return result


def _dedupe_prior_matches(matches: list[dict]) -> list[dict]:
    result = []
    seen = set()
    for match in matches:
        key = (match.get("source_key"), match.get("order_name"), tuple(match.get("match_basis", [])))
        if key in seen:
            continue
        seen.add(key)
        result.append(match)
    return result


def _preferred_prior_match(order_name: str, matches: list[dict]) -> dict:
    for match in matches:
        if match.get("order_name") and match.get("order_name") != order_name:
            return match
    return matches[0] if matches else {}


def _matched_trustpilot_tags(row: dict) -> list[str]:
    tags = []
    for key in (
        "tags",
        "tags_of_interest",
        "matched_trustpilot_invitation_tags",
        "customer_history_tags",
        "customer_order_tags",
        "historical_order_tags",
        "customer_historical_order_tags",
    ):
        value = row.get(key)
        if isinstance(value, list):
            tags.extend(_safe_text(item) for item in value)
    summary = row.get("safe_tags_summary") if isinstance(row.get("safe_tags_summary"), dict) else {}
    for key in ("tags_of_interest", "safe_tags", "exact_tags_of_interest", "matched_trustpilot_invitation_tags"):
        value = summary.get(key)
        if isinstance(value, list):
            tags.extend(_safe_text(item) for item in value)
    aliases = {_normalize_tag(tag) for tag in TRUSTPILOT_TAG_ALIASES}
    return _dedupe_text(tag for tag in tags if _normalize_tag(tag) in aliases)


def _report_status(data: dict) -> str:
    for key in (
        "send_audit_status",
        "tag_write_audit_status",
        "tag_write_execute_status",
        "one_draft_send_execute_status",
        "one_candidate_gmail_draft_send_execute_status",
        "status",
    ):
        value = _safe_text(data.get(key, ""))
        if value:
            return value
    return ""


def _normalize_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text)


def _normalize_email(email: str) -> str:
    email = str(email or "").strip().lower()
    return email if EMAIL_RE.fullmatch(email) else ""


def _email_key(email: str) -> str:
    email = _normalize_email(email)
    if not email:
        return ""
    return "sha256:" + hashlib.sha256(email.encode("utf-8")).hexdigest()


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


def _safe_text(value) -> str:
    return _sanitize_text(str(value or ""))


def _sanitize_text(text: str) -> str:
    redacted = SENSITIVE_TEXT_RE.sub("[redacted]", str(text or ""))
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _safe_int(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _dedupe_text(values) -> list[str]:
    result = []
    for value in values:
        text = _safe_text(value)
        if text and text not in result:
            result.append(text)
    return result
