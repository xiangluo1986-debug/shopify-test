import json
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_last_60_days_candidate_scan"
COMMAND_LABEL = "shopify_review_request_last_60_days_candidate_scan_local_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.html"
SQLITE_DB_PATH = PROJECT_ROOT / "backend" / "db.sqlite3"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_LAST_60_DAYS_SCAN_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_LAST_60_DAYS_SCAN_JSON_END"
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token|refresh[_\s-]?token|client[_\s-]?secret|api[_\s-]?key|password|secret)"
)
CANONICAL_REVIEW_REQUEST_TAG = "1: review request"
TYPO_REVIEW_REQUEST_TAG = "1: reveiw request"
REVIEW_REQUEST_TAG_ALIASES = {
    CANONICAL_REVIEW_REQUEST_TAG,
    TYPO_REVIEW_REQUEST_TAG,
    "1:review request",
    "1 : review request",
    "1:reveiw request",
    "1 : reveiw request",
}
DELIVERED_TAG = "Delivered"
DELIVERED_TAG_ALIASES = {
    "Delivered",
    "delivered",
}
SHOPIFY_ORDER_TAG_FIELD = "shopify_tags"
SHOPIFY_ORDER_TAG_FIELD_LABEL = "ShopifyOrder.shopify_tags"
SHOPIFY_ORDER_TAGS_MISSING_SOURCE = "ShopifyOrder.shopify_tags is not populated by local sync"
SHOPIFY_ORDER_TAGS_FIELD_MISSING_SOURCE = "Local ShopifyOrder tag field is missing; apply the shopify_tags migration"
SHOPIFY_ORDER_TAGS_EMPTY_SOURCE = "Shopify response had no order tags"
SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION = (
    "Run the Review Request Shopify order sync after applying the shopify_tags migration."
)
TRUSTPILOT_TAG_ALIASES = {
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
}
MANUAL_CONFIRMED_ORDER_EVIDENCE = {
    "#22562": {
        "order_name": "#22562",
        "source_report": "user_confirmed_shopify_ui_evidence",
        "tags": [TYPO_REVIEW_REQUEST_TAG, DELIVERED_TAG, "express"],
        "delivered_tag_present": True,
        "canonical_review_request_tag_present": True,
        "review_request_tag_present": True,
        "review_request_tag_data_loaded": True,
        "matched_review_request_tag_value": TYPO_REVIEW_REQUEST_TAG,
        "repeat_customer_detected": True,
        "customer_order_count": 2,
        "blocking_reasons": [],
        "related_order_names": [],
        "reason": "User confirmed Shopify UI tags for #22562; no explicit merge evidence was provided.",
    },
}
FOCUS_ORDER_NAMES = ("#22530", "#22562", "#22581", "#22582", "#22620", "#22621")


def run_shopify_review_request_last_60_days_candidate_scan_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_scan()
    if not completed["success"]:
        fallback = _run_sqlite_local_scan()
        if fallback["success"]:
            completed = fallback
    if completed["success"]:
        payload = completed["payload"]
        payload["duration_seconds"] = round(time.time() - started, 3)
    else:
        payload = _failure_payload(completed, round(time.time() - started, 3))

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_scan() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_last_60_days_candidate_scan_report; "
        "payload = build_review_request_last_60_days_candidate_scan_report({}); "
        f"print('{JSON_BEGIN}'); "
        "print(json.dumps(payload, ensure_ascii=False, sort_keys=True)); "
        f"print('{JSON_END}')"
    )
    command = ["docker", "compose", "exec", "-T", "web", "python", "manage.py", "shell", "-c", script]
    try:
        completed = subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=False,
            timeout=TIMEOUT_SECONDS,
            shell=False,
        )
    except FileNotFoundError:
        return {
            "success": False,
            "exit_code": 127,
            "failure_type": "docker_command_not_found",
            "stdout": "",
            "stderr": "Docker command was not found.",
        }
    except PermissionError:
        return {
            "success": False,
            "exit_code": 126,
            "failure_type": "docker_permission_denied",
            "stdout": "",
            "stderr": "Docker permission denied.",
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "success": False,
            "exit_code": 124,
            "failure_type": "timeout",
            "stdout": _to_text(exc.stdout),
            "stderr": _to_text(exc.stderr),
        }

    stdout = _to_text(completed.stdout)
    stderr = _to_text(completed.stderr)
    payload = _extract_payload(stdout)
    if completed.returncode != 0:
        return {
            "success": False,
            "exit_code": completed.returncode,
            "failure_type": "django_local_scan_failed",
            "stdout": stdout,
            "stderr": stderr,
        }
    if not payload:
        return {
            "success": False,
            "exit_code": 1,
            "failure_type": "scan_payload_missing",
            "stdout": stdout,
            "stderr": stderr,
        }
    return {
        "success": True,
        "exit_code": 0,
        "payload": payload,
        "stdout": stdout,
        "stderr": stderr,
    }


def _extract_payload(stdout: str) -> dict:
    if JSON_BEGIN not in stdout or JSON_END not in stdout:
        return {}
    fragment = stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0].strip()
    try:
        payload = json.loads(fragment)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _run_sqlite_local_scan() -> dict:
    try:
        source_by_order = _load_local_report_source_rows()
        local_orders = _load_sqlite_orders()
        payload = _build_sqlite_scan_payload(local_orders, source_by_order)
    except Exception as exc:
        return {
            "success": False,
            "exit_code": 1,
            "failure_type": "sqlite_local_scan_failed",
            "stdout": "",
            "stderr": _sanitize_text(f"{exc.__class__.__name__}: {exc}"),
        }
    return {"success": True, "exit_code": 0, "payload": payload, "stdout": "", "stderr": ""}


def _load_local_report_source_rows() -> dict:
    rows_by_order = {}
    if not LOG_DIR.exists():
        return rows_by_order
    for path in sorted(LOG_DIR.glob("shopify_review_request*.json")):
        if path.name == REPORT_JSON_PATH.name:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in _walk_dict_rows(data):
            order_name = _canonical_order_name(
                _first_text(
                    row,
                    (
                        "order_name",
                        "selected_order_name",
                        "audit_order_name",
                        "next_candidate_order_name",
                    ),
                )
            )
            if not order_name:
                continue
            safe_row = _public_report_row(row, path.name, order_name)
            rows_by_order[order_name] = _merge_source_rows(rows_by_order.get(order_name, {}), safe_row)
    return rows_by_order


def _walk_dict_rows(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(item.values())
        elif isinstance(item, list):
            stack.extend(item)


def _public_report_row(row: dict, source_name: str, order_name: str) -> dict:
    tags = _collect_tags(row)
    matched_review_request_tags = _matched_review_request_tags(tags)
    blocking_reasons = _collect_list(row.get("blocking_reasons"))
    classification = _safe_text(row.get("classification") or row.get("candidate_status") or row.get("status"))
    if classification.startswith("blocked_"):
        blocking_reasons.append(classification)
    return {
        "order_name": order_name,
        "source_report": source_name,
        "masked_email": _safe_masked_email(
            _first_text(row, ("masked_email", "selected_masked_email", "next_candidate_masked_email", "email"))
        ),
        "customer_display_name": _safe_name(_first_text(row, ("customer_display_name", "customer_name", "shipping_name"))),
        "customer_order_count": _int_value(row.get("customer_order_count") or row.get("repeat_customer_count")),
        "repeat_customer_detected": row.get("repeat_customer_detected") is True,
        "tags": _dedupe(tags),
        "blocking_reasons": _dedupe(blocking_reasons),
        "status": _safe_text(row.get("status")),
        "classification": classification,
        "delivered_tag_present": row.get("delivered_tag_present") is True or has_delivered_tag(tags),
        "canonical_review_request_tag_present": (
            row.get("canonical_review_request_tag_present") is True
            or row.get("review_request_tag_present") is True
            or bool(matched_review_request_tags)
        ),
        "review_request_tag_data_loaded": _tag_data_loaded(row, tags),
        "matched_review_request_tag_value": (
            matched_review_request_tags[0] if matched_review_request_tags else ""
        ),
        "trustpilot_invitation_present": (
            row.get("trustpilot_invitation_present") is True
            or bool(_matched_trustpilot_tags(tags))
        ),
        "prior_trustpilot_order_name": _canonical_order_name(row.get("prior_trustpilot_order_name")),
        "related_order_names": _dedupe(
            _collect_order_name_values(row.get("related_order_names"))
            + _collect_order_name_values(row.get("related_orders"))
            + _collect_order_name_values(row.get("merged_order_names"))
            + _merged_names_from_text(
                " ".join(
                    _safe_text(row.get(key))
                    for key in ("reason", "blocking_summary", "status", "classification")
                )
            )
        ),
        "reason": _safe_text(
            row.get("reason") or row.get("blocking_summary") or row.get("candidate_status") or row.get("status"),
            500,
        ),
        "created_at": _safe_text(
            _first_text(row, ("created_at", "createdAt", "order_created_at", "processed_at", "timestamp")),
            100,
        ),
    }


def _merge_source_rows(left: dict, right: dict) -> dict:
    if not left:
        return dict(right)
    merged = dict(left)
    for key in ("tags", "blocking_reasons", "related_order_names"):
        merged[key] = _dedupe((merged.get(key) or []) + (right.get(key) or []))
    for key in (
        "masked_email",
        "customer_display_name",
        "status",
        "classification",
        "prior_trustpilot_order_name",
        "reason",
        "created_at",
        "matched_review_request_tag_value",
        "customer_order_count",
    ):
        if not merged.get(key) and right.get(key):
            merged[key] = right[key]
    for key in (
        "delivered_tag_present",
        "canonical_review_request_tag_present",
        "review_request_tag_data_loaded",
        "trustpilot_invitation_present",
        "repeat_customer_detected",
    ):
        merged[key] = merged.get(key) is True or right.get(key) is True
    return merged


def _apply_manual_confirmed_order_evidence(source_by_order: dict) -> dict:
    result = dict(source_by_order or {})
    for order_name, evidence in MANUAL_CONFIRMED_ORDER_EVIDENCE.items():
        result[order_name] = _merge_source_rows(result.get(order_name, {}), evidence)
    return result


def _load_sqlite_orders() -> list[dict]:
    if not SQLITE_DB_PATH.exists():
        return []
    connection = sqlite3.connect(SQLITE_DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        columns = _table_columns(connection, "shopify_sync_shopifyorder")
        wanted = [
            column
            for column in (
                "id",
                "order_name",
                "order_number",
                "shopify_order_id",
                "customer_name",
                "customer_email",
                "financial_status",
                "fulfillment_status",
                "order_created_at",
                "fulfilled_at",
                "fulfillment_status_raw",
                "updated_at",
                "settlement_status",
                "shopify_note",
                "shopify_note_attributes",
                SHOPIFY_ORDER_TAG_FIELD,
            )
            if column in columns
        ]
        if not wanted:
            return []
        sql = "SELECT " + ", ".join(wanted) + " FROM shopify_sync_shopifyorder"
        return [dict(row) for row in connection.execute(sql).fetchall()]
    finally:
        connection.close()


def _table_columns(connection, table_name: str) -> set[str]:
    return {row[1] for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()}


def _build_sqlite_scan_payload(local_orders: list[dict], source_by_order: dict) -> dict:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=60)
    source_by_order = _apply_manual_confirmed_order_evidence(source_by_order)
    local_by_order = {}
    for order in local_orders:
        order_name = _canonical_order_name(order.get("order_name") or order.get("order_number"))
        if order_name:
            local_by_order[order_name] = order

    order_names = set(source_by_order) | {
        name
        for name, order in local_by_order.items()
        if _date_in_window(_scan_date(order, source_by_order.get(name, {}))[0], cutoff)
    }
    order_names.update(name for name in FOCUS_ORDER_NAMES if name in source_by_order or name in local_by_order)
    order_names = {name for name in order_names if not _is_simulator_order_name(name)}

    already_sent_rows = _already_sent_rows_from_sources(source_by_order)
    already_sent_orders = {row["order"] for row in already_sent_rows}
    already_sent_customers = {row.get("masked_customer") for row in already_sent_rows if row.get("masked_customer")}

    candidate_rows = []
    for order_name in sorted(order_names, reverse=True):
        if order_name in already_sent_orders:
            continue
        source = source_by_order.get(order_name, {})
        local = local_by_order.get(order_name, {})
        row = _evaluate_sqlite_order(order_name, local, source, already_sent_orders, already_sent_customers, cutoff)
        if row["candidate_status"] == "already_sent":
            already_sent_rows.append(row)
            already_sent_orders.add(row["order"])
        else:
            candidate_rows.append(row)

    candidate_rows = _apply_known_merged_group(candidate_rows)
    eligible_rows = [row for row in candidate_rows if row["candidate_status"] == "eligible"]
    blocked_rows = [row for row in candidate_rows if row["candidate_status"] != "eligible"]
    eligible_rows.sort(key=lambda row: row["order"])
    blocked_rows.sort(key=lambda row: (0 if "#22582" in row.get("group_order_names", [row["order"]]) else 1, row["order"]))
    already_sent_rows = _dedupe_summary_rows(already_sent_rows)
    already_sent_rows.sort(key=lambda row: {"#22621": 0, "#22620": 1}.get(row["order"], 9))
    order_22530_found = "#22530" in local_by_order
    coverage_warnings = ["incomplete_local_order_source"]
    if not order_22530_found:
        coverage_warnings.append("order_not_found_in_local_data")
    if any(row.get("delivered_confirmed") is not True for row in candidate_rows):
        coverage_warnings.append("delivered_order_data_missing")
    order_22530_diagnosis = _sqlite_focus_order_diagnosis(
        "#22530",
        local_by_order,
        eligible_rows,
        blocked_rows,
        already_sent_rows,
    )
    order_data_coverage = {
        "scan_source": "sqlite_report_fallback",
        "coverage_warnings": _dedupe(coverage_warnings),
        "last_shopify_order_sync_window": "Unknown",
        "latest_review_request_sync_finished_at": "",
        "latest_review_request_sync_task_name": "",
        "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
        "local_orders_with_shopify_tag_data": sum(
            1 for order in local_by_order.values() if _shopify_tags_loaded_from_order(order)
        ),
        "local_last_60_days_order_count": len(
            [
                name
                for name, order in local_by_order.items()
                if _date_in_window(_scan_date(order, source_by_order.get(name, {}))[0], cutoff)
            ]
        ),
        "local_order_context_count": len(local_by_order),
        "report_only_context_count": len([name for name in source_by_order if name not in local_by_order]),
        "order_22530_found": order_22530_found,
        "order_22562_found": "#22562" in local_by_order,
    }

    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28F",
        "mode": "dry-run-local-synced-order-scan",
        "command_label": COMMAND_LABEL,
        "window_days": 60,
        "report_status": "last_60_days_candidate_scan_ready",
        "success": True,
        "scan_source": "sqlite_report_fallback",
        "coverage_warnings": order_data_coverage["coverage_warnings"],
        "order_data_coverage": order_data_coverage,
        "order_22530_diagnosis": order_22530_diagnosis,
        "scan_window_started_at": cutoff.isoformat(),
        "scan_window_ended_at": now.isoformat(),
        "scanned_order_count": len(order_names),
        "delivered_order_count": sum(1 for row in candidate_rows + already_sent_rows if row.get("delivered_confirmed")),
        "eligible_candidate_count": len(eligible_rows),
        "already_sent_count": len(already_sent_rows),
        "blocked_count": len(blocked_rows),
        "blocked_merged_group_count": sum(1 for row in blocked_rows if row.get("merged_order_group")),
        "blocked_duplicate_customer_count": sum(1 for row in blocked_rows if "prior Trustpilot" in row.get("block_reason", "") or "already" in row.get("block_reason", "").lower()),
        "blocked_missing_review_request_tag_count": sum(
            1 for row in blocked_rows if row.get("canonical_review_request_tag_present") is False
        ),
        "blocked_not_delivered_count": sum(1 for row in blocked_rows if not row.get("delivered_confirmed")),
        "eligible_candidates_summary": [_eligible_summary(row) for row in eligible_rows],
        "blocked_candidates_summary": [_blocked_summary(row) for row in blocked_rows],
        "already_sent_summary": [_already_sent_public_summary(row) for row in already_sent_rows],
        "date_fallback_order_count": sum(1 for row in candidate_rows + already_sent_rows if row.get("scan_date_fallback_used")),
        "date_fallback_summary": [
            {"order": row["order"], "scan_date": row.get("scan_date", ""), "scan_date_basis": row.get("scan_date_basis", "")}
            for row in (candidate_rows + already_sent_rows)
            if row.get("scan_date_fallback_used")
        ][:25],
        "gmail_permission_status": "not_checked_by_sqlite_fallback",
        "template_available": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            f"Scan source: sqlite_report_fallback. Scanned {len(order_names)} local/report orders; "
            f"{len(eligible_rows)} eligible, {len(already_sent_rows)} already sent, {len(blocked_rows)} blocked. "
            f"Coverage warnings: {', '.join(order_data_coverage['coverage_warnings']) or 'none'}. "
            "No Gmail, Shopify, or external review API calls were performed."
        ),
    }


def _already_sent_rows_from_sources(source_by_order: dict) -> list[dict]:
    rows = []
    for order_name in ("#22621", "#22620"):
        source = source_by_order.get(order_name, {})
        if order_name == "#22621":
            evidence = "Trustpilot email already sent and recorded."
            prior = "#22621"
        else:
            prior = _canonical_order_name(source.get("prior_trustpilot_order_name")) or "#22621"
            evidence = f"Already sent to this customer via {prior}."
        scan_dt, basis = _scan_date({}, source)
        rows.append(
            {
                "order": order_name,
                "customer": source.get("customer_display_name") or "Masked in reports",
                "masked_customer": source.get("masked_email", ""),
                "trustpilot_email_status": "Already sent",
                "evidence": evidence,
                "tags": source.get("tags", []),
                "prior_trustpilot_order_name": prior,
                "delivered_confirmed": source.get("delivered_tag_present") is True,
                "canonical_review_request_tag_present": source.get("canonical_review_request_tag_present") is True,
                "scan_date": scan_dt.isoformat() if scan_dt else "",
                "scan_date_basis": basis,
                "scan_date_fallback_used": basis != "delivered_date",
                "candidate_status": "already_sent",
            }
        )
    for order_name, source in source_by_order.items():
        if _is_simulator_order_name(order_name):
            continue
        if source.get("trustpilot_invitation_present") is True and order_name not in {"#22621", "#22620"}:
            scan_dt, basis = _scan_date({}, source)
            rows.append(
                {
                    "order": order_name,
                    "customer": source.get("customer_display_name") or "Masked in reports",
                    "masked_customer": source.get("masked_email", ""),
                    "trustpilot_email_status": "Already sent",
                    "evidence": "Trustpilot tag or invitation history found.",
                    "tags": source.get("tags", []),
                    "prior_trustpilot_order_name": order_name,
                    "delivered_confirmed": source.get("delivered_tag_present") is True,
                    "canonical_review_request_tag_present": source.get("canonical_review_request_tag_present") is True,
                    "scan_date": scan_dt.isoformat() if scan_dt else "",
                    "scan_date_basis": basis,
                    "scan_date_fallback_used": basis != "delivered_date",
                    "candidate_status": "already_sent",
                }
            )
    return _dedupe_summary_rows(rows)


def _evaluate_sqlite_order(order_name, local, source, already_sent_orders, already_sent_customers, cutoff):
    scan_dt, basis = _scan_date(local, source)
    tags, tag_data_loaded, tag_data_missing_source, tag_data_recommended_action = _effective_order_tags(
        local,
        source,
    )
    matched_review_request_tags = _matched_review_request_tags(tags)
    masked_customer = source.get("masked_email") or _mask_email(local.get("customer_email"))
    delivered = _sqlite_delivered_confirmed(local, source, tags)
    if source.get("canonical_review_request_tag_present") is True or has_review_request_tag(tags):
        canonical_tag = True
    elif tag_data_loaded:
        canonical_tag = False
    else:
        canonical_tag = None
    prior_order = _canonical_order_name(source.get("prior_trustpilot_order_name"))
    trustpilot_sent = (
        order_name in already_sent_orders
        or bool(prior_order)
        or source.get("trustpilot_invitation_present") is True
        or (masked_customer and masked_customer in already_sent_customers)
    )
    blockers = []
    if trustpilot_sent:
        blockers.append(f"Already sent to this customer via {prior_order or order_name}.")
    if not delivered:
        blockers.append("Not delivered.")
    if canonical_tag is None:
        blockers.append("Shopify tag data not loaded, cannot confirm review request tag.")
    elif not canonical_tag:
        blockers.append(f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`.")
    source_blocking_reasons = _filtered_source_blocking_reasons(
        source.get("blocking_reasons") or [],
        canonical_tag,
        source,
    )
    if source_blocking_reasons:
        blockers.extend(_blocker_labels(source_blocking_reasons))
    if _local_risk(local, source):
        blockers.append("Risk, ticket, refund, cancel, return, or dispute evidence is present.")
    status = "eligible" if not blockers else "blocked"
    return {
        "order": order_name,
        "customer": source.get("customer_display_name") or _safe_name(local.get("customer_name")) or "Masked in reports",
        "masked_customer": masked_customer,
        "local_order_id": local.get("id", ""),
        "matched_order_name": _canonical_order_name(local.get("order_name") or local.get("order_number")),
        "order_number": _safe_text(local.get("order_number"), 120),
        "shopify_order_id": _safe_text(local.get("shopify_order_id"), 120),
        "order_created_at": _safe_text(local.get("order_created_at"), 120),
        "fulfillment_status": _safe_text(local.get("fulfillment_status"), 80),
        "shopify_note_present": _order_note_present(local),
        "tags": tags,
        "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
        "tags_summary": _tags_summary(tags, tag_data_loaded),
        "tag_data_available": tag_data_loaded,
        "tag_data_missing_source": tag_data_missing_source,
        "tag_data_recommended_action": tag_data_recommended_action,
        "delivered_confirmed": delivered,
        "canonical_review_request_tag_present": canonical_tag,
        "review_request_tag_data_loaded": tag_data_loaded,
        "matched_review_request_tag_value": (
            source.get("matched_review_request_tag_value")
            or (matched_review_request_tags[0] if matched_review_request_tags else "")
        ),
        "trustpilot_email_status": "Already sent" if trustpilot_sent else "No previous Trustpilot email found",
        "trustpilot_history": (
            f"Already sent to this customer via {prior_order or order_name}"
            if trustpilot_sent
            else "No previous Trustpilot email found"
        ),
        "candidate_status": "already_sent" if trustpilot_sent else status,
        "block_reason": "; ".join(_dedupe(blockers)) if blockers else "Delivered, tagged, and no duplicate or risk found.",
        "missing_requirement": _missing_requirement(delivered, canonical_tag, trustpilot_sent, blockers),
        "evidence": source.get("reason") or "; ".join(_dedupe(blockers)) or "Local synced order and report evidence.",
        "scan_date": scan_dt.isoformat() if scan_dt else "",
        "scan_date_basis": basis,
        "scan_date_fallback_used": basis != "delivered_date",
        "scan_date_in_window": _date_in_window(scan_dt, cutoff),
        "group_order_names": source.get("related_order_names") or [],
    }


def _sqlite_delivered_confirmed(local, source, tags):
    if source.get("delivered_tag_present") is True or has_delivered_tag(tags) or "妥投" in tags:
        return True
    fulfillment_values = {
        _safe_text(local.get(key), 160).lower()
        for key in ("fulfillment_status", "fulfillment_status_raw")
        if _safe_text(local.get(key), 160)
    }
    if "fulfilled" in fulfillment_values:
        return True
    if source.get("delivered_tag_present") is False:
        return False
    status_text = " ".join(
        _safe_text(value, 200).lower()
        for value in (
            source.get("status"),
            source.get("blocking_summary"),
            source.get("classification"),
            local.get("fulfillment_status"),
            local.get("fulfillment_status_raw"),
        )
    )
    if "not delivered" in status_text or "missing delivered" in status_text:
        return False
    if "delivered" in status_text or "妥投" in status_text:
        return True
    return False


def _order_note_present(local):
    if _safe_text(local.get("shopify_note"), 20):
        return True
    note_attributes = local.get("shopify_note_attributes")
    return note_attributes not in (None, "", [], {})


def _effective_order_tags(local, source):
    if _shopify_tags_loaded_from_order(local):
        tags = _shopify_tags_from_order(local)
        return tags, True, "", ""

    source_tags = _dedupe(
        _collect_list((source or {}).get("tags"), split_strings=True)
        + _collect_list((source or {}).get("order_tags_display"))
    )
    if _tag_data_loaded(source, source_tags):
        return source_tags, True, "", ""

    return (
        [],
        False,
        _tag_data_missing_source_for_order(local),
        SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
    )


def _shopify_tags_loaded_from_order(order):
    return isinstance(order, dict) and SHOPIFY_ORDER_TAG_FIELD in order and order.get(SHOPIFY_ORDER_TAG_FIELD) is not None


def _shopify_tags_from_order(order):
    if not _shopify_tags_loaded_from_order(order):
        return []
    return _split_shopify_tag_string(order.get(SHOPIFY_ORDER_TAG_FIELD))


def _split_shopify_tag_string(value):
    if isinstance(value, (list, tuple, set)):
        return _dedupe(_safe_text(item, 120) for item in value if _safe_text(item, 120))
    return _dedupe(
        _safe_text(part, 120)
        for part in str(value or "").split(",")
        if _safe_text(part, 120)
    )


def _tag_data_missing_source_for_order(order):
    if not isinstance(order, dict) or SHOPIFY_ORDER_TAG_FIELD not in order:
        return SHOPIFY_ORDER_TAGS_FIELD_MISSING_SOURCE
    return SHOPIFY_ORDER_TAGS_MISSING_SOURCE


def _tags_summary(tags, tag_data_loaded):
    safe_tags = _dedupe(tags or [])
    if safe_tags:
        return ", ".join(safe_tags)
    if tag_data_loaded:
        return SHOPIFY_ORDER_TAGS_EMPTY_SOURCE
    return "Shopify tag data not loaded"


def _apply_known_merged_group(rows: list[dict]) -> list[dict]:
    by_order = {row["order"]: row for row in rows}
    if "#22582" not in by_order and "#22581" not in by_order:
        return rows
    group_names = [name for name in ("#22582", "#22581") if name in by_order]
    if len(group_names) < 2:
        group_names = ["#22582", "#22581"]
    group_ready = all(
        by_order.get(name, {}).get("candidate_status") == "eligible"
        for name in group_names
        if name in by_order
    ) and len([name for name in group_names if name in by_order]) == len(group_names)
    for name in group_names:
        row = by_order.get(name)
        if not row:
            continue
        row["merged_order_group"] = True
        row["group_order_names"] = group_names
        if not group_ready:
            row["candidate_status"] = "blocked"
            row["block_reason"] = (
                "Merged order group is not ready. #22582/#22581 were shipped together; "
                "not delivered, missing a review-request tag alias, or readiness evidence is missing for the group."
            )
            row["missing_requirement"] = "Whole merged/related group ready, Delivered / 妥投, review-request tag alias"
    return rows


def _sqlite_focus_order_diagnosis(order_name, local_by_order, eligible_rows, blocked_rows, already_sent_rows):
    row = {}
    section = "not_scanned"
    for candidate_section, rows in (
        ("eligible", eligible_rows),
        ("blocked", blocked_rows),
        ("already_sent", already_sent_rows),
    ):
        for item in rows:
            if item.get("order") == order_name:
                row = item
                section = candidate_section
                break
        if row:
            break
    found_locally = order_name in local_by_order
    local = local_by_order.get(order_name, {})
    if not found_locally:
        message = f"{order_name} not found in local ShopifyOrder data. Run Review Request 60-day Shopify sync."
    else:
        message = f"{order_name} found in local ShopifyOrder data."
    local_tags = _shopify_tags_from_order(local)
    tag_data_loaded = (
        bool(row.get("review_request_tag_data_loaded"))
        if row
        else _shopify_tags_loaded_from_order(local)
    )
    review_request_tag_present = (
        row.get("canonical_review_request_tag_present") is True
        if row
        else has_review_request_tag(local_tags)
    )
    if not tag_data_loaded:
        review_request_tag_status = "unavailable"
    elif review_request_tag_present:
        review_request_tag_status = "present"
    else:
        review_request_tag_status = "missing"
    tags = _dedupe(row.get("tags") or local_tags or []) if row or local else []
    return {
        "order_name": order_name,
        "found_in_local_shopify_order": found_locally,
        "matched_field": _sqlite_focus_matched_field(order_name, local) if found_locally else "",
        "matched_order_name": _canonical_order_name(local.get("order_name") or local.get("order_number")),
        "local_order_id": local.get("id", ""),
        "order_number": _safe_text(local.get("order_number"), 120),
        "shopify_order_id": _safe_text(local.get("shopify_order_id"), 120),
        "order_created_at": _safe_text(local.get("order_created_at"), 120),
        "order_created_date": _date_part(local.get("order_created_at")),
        "fulfillment_status": _safe_text(local.get("fulfillment_status"), 80),
        "shopify_note_present": _order_note_present(local),
        "included_in_candidate_scan": bool(row),
        "candidate_scan_section": section,
        "scan_date": _safe_text(row.get("scan_date", ""), 120) if row else "",
        "scan_date_basis": _safe_text(row.get("scan_date_basis", ""), 80) if row else "",
        "delivered_confirmed": row.get("delivered_confirmed") if row else None,
        "delivered_or_fulfilled_detected": row.get("delivered_confirmed") is True if row else False,
        "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
        "tags_summary": _tags_summary(tags, tag_data_loaded),
        "order_tags_display": tags,
        "tag_data_available": tag_data_loaded,
        "review_request_tag_data_loaded": tag_data_loaded,
        "tag_data_missing_source": "" if tag_data_loaded else _tag_data_missing_source_for_order(local),
        "tag_data_recommended_action": "" if tag_data_loaded else SHOPIFY_ORDER_TAGS_RECOMMENDED_ACTION,
        "review_request_tag_status": review_request_tag_status,
        "review_request_tag_present": review_request_tag_present,
        "matched_review_request_tag_value": _safe_text(row.get("matched_review_request_tag_value", ""), 120) if row else "",
        "final_eligibility_status": _sqlite_focus_final_eligibility(found_locally, row, tag_data_loaded),
        "final_blockers": _sqlite_focus_final_blockers(found_locally, row, tag_data_loaded),
        "message": message,
    }


def _sqlite_focus_matched_field(order_name, local):
    target = _canonical_order_name(order_name)
    target_number = target.lstrip("#")
    if _canonical_order_name(local.get("order_name")) == target:
        return "order_name"
    if target_number and _safe_text(local.get("order_number"), 120).lstrip("#") == target_number:
        return "order_number"
    if target_number and _safe_text(local.get("shopify_order_id"), 120) == target_number:
        return "shopify_order_id"
    return ""


def _sqlite_focus_final_eligibility(found_locally, row, tag_data_loaded):
    if not found_locally:
        return "not_found"
    status = _safe_text(row.get("candidate_status"), 80) if row else ""
    if status == "eligible":
        return "eligible"
    if status == "already_sent":
        return "already_sent"
    if not tag_data_loaded:
        return "blocked"
    return "blocked" if row else "not_scanned"


def _sqlite_focus_final_blockers(found_locally, row, tag_data_loaded):
    if not found_locally:
        return ["order_not_found_in_local_shopify_order"]
    blockers = [
        _safe_text(part, 240)
        for part in re.split(r";\s*", _safe_text(row.get("block_reason", ""), 500) if row else "")
        if _safe_text(part, 240)
    ]
    if not tag_data_loaded:
        blockers.append("review_request_tag_data_unavailable")
    return _dedupe(blockers)


def _date_part(value):
    text = _safe_text(value, 120)
    return text[:10] if len(text) >= 10 else text


def _failure_payload(result: dict, duration_seconds: float) -> dict:
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28F",
        "mode": "dry-run-local-synced-order-scan",
        "command_label": COMMAND_LABEL,
        "report_status": "blocked_last_60_days_candidate_scan_failed",
        "success": False,
        "failure_type": _sanitize_text(result.get("failure_type", "")),
        "exit_code": int(result.get("exit_code") or 1),
        "scan_source": "fallback_report_only",
        "coverage_warnings": ["incomplete_local_order_source", "delivered_order_data_missing"],
        "order_data_coverage": {
            "scan_source": "fallback_report_only",
            "coverage_warnings": ["incomplete_local_order_source", "delivered_order_data_missing"],
            "last_shopify_order_sync_window": "Unknown",
            "selected_local_tag_field": SHOPIFY_ORDER_TAG_FIELD_LABEL,
            "local_orders_with_shopify_tag_data": 0,
            "order_22530_found": False,
            "order_22562_found": False,
        },
        "order_22530_diagnosis": {
            "order_name": "#22530",
            "found_in_local_shopify_order": False,
            "included_in_candidate_scan": False,
            "candidate_scan_section": "not_scanned",
            "message": "#22530 not found in local ShopifyOrder data. Run Review Request 60-day Shopify sync.",
        },
        "scanned_order_count": 0,
        "delivered_order_count": 0,
        "eligible_candidate_count": 0,
        "already_sent_count": 0,
        "blocked_count": 0,
        "blocked_merged_group_count": 0,
        "blocked_duplicate_customer_count": 0,
        "blocked_missing_review_request_tag_count": 0,
        "blocked_not_delivered_count": 0,
        "eligible_candidates_summary": [],
        "blocked_candidates_summary": [],
        "already_sent_summary": [],
        "stdout_tail_sanitized": _tail(_sanitize_text(result.get("stdout", ""))),
        "stderr_tail_sanitized": _tail(_sanitize_text(result.get("stderr", ""))),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": "Local last-60-days candidate scan failed before producing a report.",
        "duration_seconds": duration_seconds,
    }


def _write_json(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "exit_code": 0 if payload.get("success") is True else int(payload.get("exit_code") or 1),
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "report_status": payload.get("report_status", ""),
        "scan_source": payload.get("scan_source", "unknown"),
        "coverage_warnings": payload.get("coverage_warnings", []),
        "scanned_order_count": int(payload.get("scanned_order_count") or 0),
        "delivered_order_count": int(payload.get("delivered_order_count") or 0),
        "eligible_candidate_count": int(payload.get("eligible_candidate_count") or 0),
        "already_sent_count": int(payload.get("already_sent_count") or 0),
        "blocked_count": int(payload.get("blocked_count") or 0),
        "blocked_merged_group_count": int(payload.get("blocked_merged_group_count") or 0),
        "blocked_duplicate_customer_count": int(payload.get("blocked_duplicate_customer_count") or 0),
        "blocked_missing_review_request_tag_count": int(
            payload.get("blocked_missing_review_request_tag_count") or 0
        ),
        "blocked_not_delivered_count": int(payload.get("blocked_not_delivered_count") or 0),
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "raw_customer_email_output": False,
        "secrets_output": False,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Last 60 days Trustpilot candidate scan completed.\n"
        f"Result: {payload.get('report_status')}\n"
        f"Scan source: {payload.get('scan_source', 'unknown')}\n"
        f"Scanned orders: {payload.get('scanned_order_count', 0)}\n"
        f"Eligible candidates: {payload.get('eligible_candidate_count', 0)}\n"
        f"Already sent: {payload.get('already_sent_count', 0)}\n"
        f"Blocked / not ready: {payload.get('blocked_count', 0)}\n"
        f"Coverage warnings: {', '.join(payload.get('coverage_warnings') or []) or 'none'}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "0 = stop"
    )


def _render_html(payload: dict) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Last 60 Days Trustpilot Candidate Scan</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
  </style>
</head>
<body>
  <h1>Last 60 Days Trustpilot Candidate Scan</h1>
  <p>Status: <strong>{escape(str(payload.get("report_status", "")))}</strong></p>
  <table><tbody>
    <tr><th>Scan source</th><td>{escape(str(payload.get("scan_source", "unknown")))}</td></tr>
    <tr><th>Coverage warnings</th><td>{escape(", ".join(payload.get("coverage_warnings") or []) or "none")}</td></tr>
    <tr><th>#22530 diagnosis</th><td>{escape(str((payload.get("order_22530_diagnosis") or {}).get("message", "")))}</td></tr>
    <tr><th>Scanned order count</th><td>{escape(str(payload.get("scanned_order_count", 0)))}</td></tr>
    <tr><th>Delivered order count</th><td>{escape(str(payload.get("delivered_order_count", 0)))}</td></tr>
    <tr><th>Eligible candidate count</th><td>{escape(str(payload.get("eligible_candidate_count", 0)))}</td></tr>
    <tr><th>Already sent count</th><td>{escape(str(payload.get("already_sent_count", 0)))}</td></tr>
    <tr><th>Blocked / not ready count</th><td>{escape(str(payload.get("blocked_count", 0)))}</td></tr>
  </tbody></table>
  <h2>Eligible Candidates</h2>
  {_summary_table(payload.get("eligible_candidates_summary") or [])}
  <h2>Already Sent</h2>
  {_summary_table(payload.get("already_sent_summary") or [])}
  <h2>Blocked / Not Ready</h2>
  {_summary_table(payload.get("blocked_candidates_summary") or [])}
  <h2>Safety</h2>
  <table><tbody>
    <tr><th>Gmail API call performed</th><td>{escape(str(payload.get("gmail_api_call_performed") is True))}</td></tr>
    <tr><th>Email sent</th><td>{escape(str(payload.get("email_sent") is True))}</td></tr>
    <tr><th>Shopify write performed</th><td>{escape(str(payload.get("shopify_write_performed") is True))}</td></tr>
    <tr><th>External review API call performed</th><td>{escape(str(payload.get("external_review_api_call_performed") is True))}</td></tr>
    <tr><th>Raw customer email output</th><td>{escape(str(payload.get("raw_customer_email_output") is True))}</td></tr>
  </tbody></table>
</body>
</html>"""


def _summary_table(rows: list[dict]) -> str:
    if not rows:
        return "<p>No rows.</p>"
    keys = list(rows[0].keys())[:8]
    head = "".join(f"<th>{escape(str(key))}</th>" for key in keys)
    body_rows = []
    for row in rows[:50]:
        cells = "".join(f"<td>{escape(_display_value(row.get(key)))}</td>" for key in keys)
        body_rows.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _display_value(value) -> str:
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value if value is not None else "")


def _eligible_summary(row: dict) -> dict:
    return {
        "order": row["order"],
        "customer": row.get("customer") or "Masked in reports",
        "masked_customer": row.get("masked_customer", ""),
        "tags": row.get("tags", []),
        "tag_data_available": row.get("tag_data_available") is True,
        "review_request_tag_present": row.get("canonical_review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": row.get("matched_review_request_tag_value", ""),
        "delivered_status": "Delivered" if row.get("delivered_confirmed") else "Not delivered",
        "trustpilot_history": row.get("trustpilot_history", ""),
        "reason": row.get("block_reason", ""),
        "action": "Review & Send",
        "scan_date": row.get("scan_date", ""),
        "scan_date_basis": row.get("scan_date_basis", ""),
        "scan_date_fallback_used": row.get("scan_date_fallback_used") is True,
    }


def _blocked_summary(row: dict) -> dict:
    return {
        "order_or_group": "/".join(row.get("group_order_names") or [row["order"]]),
        "order": row["order"],
        "group_order_names": row.get("group_order_names", []),
        "customer": row.get("customer") or "Masked in reports",
        "tags": row.get("tags", []),
        "tag_data_available": row.get("tag_data_available") is True,
        "tag_data_missing_source": row.get("tag_data_missing_source", ""),
        "tag_data_recommended_action": row.get("tag_data_recommended_action", ""),
        "review_request_tag_present": row.get("canonical_review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": row.get("matched_review_request_tag_value", ""),
        "delivered_status": "Delivered" if row.get("delivered_confirmed") else "Not delivered",
        "block_reason": row.get("block_reason", ""),
        "missing_requirement": row.get("missing_requirement", ""),
        "evidence": row.get("evidence", ""),
        "scan_date": row.get("scan_date", ""),
        "scan_date_basis": row.get("scan_date_basis", ""),
        "scan_date_fallback_used": row.get("scan_date_fallback_used") is True,
    }


def _already_sent_public_summary(row: dict) -> dict:
    return {
        "order": row["order"],
        "customer": row.get("customer") or "Masked in reports",
        "masked_customer": row.get("masked_customer", ""),
        "trustpilot_email_status": row.get("trustpilot_email_status", "Already sent"),
        "evidence": row.get("evidence", ""),
        "tags": row.get("tags", []),
        "tag_data_available": row.get("tag_data_available") is True,
        "review_request_tag_present": row.get("canonical_review_request_tag_present") is True,
        "review_request_tag_data_loaded": row.get("review_request_tag_data_loaded") is True,
        "matched_review_request_tag_value": row.get("matched_review_request_tag_value", ""),
        "delivered_status": "Delivered" if row.get("delivered_confirmed") else "Not delivered",
    }


def _scan_date(local: dict, source: dict) -> tuple[datetime | None, str]:
    delivered_dt = _parse_dt(
        _first_text(source, ("delivered_at", "delivered_date", "delivery_date", "deliveredAt"))
    )
    if delivered_dt:
        return delivered_dt, "delivered_date"
    for basis, value in (
        ("fulfilled_at", local.get("fulfilled_at")),
        ("updated_at", local.get("updated_at")),
        ("order_created_at", local.get("order_created_at")),
        ("source_created_at", source.get("created_at")),
    ):
        parsed = _parse_dt(value)
        if parsed:
            return parsed, basis
    return None, "unavailable"


def _parse_dt(value) -> datetime | None:
    text = _safe_text(value, 100)
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _date_in_window(value: datetime | None, cutoff: datetime) -> bool:
    return bool(value and value >= cutoff)


def _collect_tags(row: dict) -> list[str]:
    tags = []
    for key in (
        "tags",
        "tags_of_interest",
        "exact_tags_of_interest",
        "matched_trustpilot_invitation_tags",
        "customer_history_tags",
        "customer_order_tags",
    ):
        tags.extend(_collect_list(row.get(key), split_strings=(key == "tags")))
    for key in ("safe_tags_summary", "tags_summary"):
        summary = row.get(key)
        if isinstance(summary, dict):
            for nested_key in ("safe_tags", "tags_of_interest", "exact_tags_of_interest"):
                tags.extend(_collect_list(summary.get(nested_key)))
    return _dedupe(_safe_text(tag, 120) for tag in tags if _safe_text(tag, 120))


def _tag_data_loaded(row: dict, tags: list[str]) -> bool:
    row = row or {}
    if tags:
        return True
    if row.get("review_request_tag_data_loaded") is True:
        return True
    if row.get("tag_data_available") is True:
        return True
    return any(
        _tag_payload_available(row.get(key))
        for key in (
            "tags",
            "order_tags_display",
            "safe_tags_summary",
            "tags_summary",
            "tags_of_interest",
            "exact_tags_of_interest",
        )
    )


def _tag_payload_available(value) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = _safe_text(value, 160).lower()
        return text not in {
            "no tag data",
            "no tag data in row",
            "tag data not loaded",
            "shopify tag data not loaded",
            "unavailable",
            "none",
            "[]",
        }
    if isinstance(value, dict):
        return any(_tag_payload_available(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_tag_payload_available(item) for item in value)
    return True


def _collect_list(value, split_strings: bool = False) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_collect_list(item, split_strings=split_strings))
        return result
    if isinstance(value, dict):
        return []
    text = _safe_text(value, 500)
    if not text:
        return []
    if split_strings:
        return [_safe_text(part, 120) for part in text.split(",") if _safe_text(part, 120)]
    return [text]


def has_review_request_tag(tags: list[str]) -> bool:
    return bool(_matched_review_request_tags(tags))


def has_delivered_tag(tags: list[str]) -> bool:
    return bool(_matched_delivered_tags(tags))


def has_trustpilot_sent_tag(tags: list[str]) -> bool:
    return bool(_matched_trustpilot_tags(tags))


def _matched_review_request_tags(tags: list[str]) -> list[str]:
    return _matched_tag_alias_values(tags, REVIEW_REQUEST_TAG_ALIASES)


def _matched_delivered_tags(tags: list[str]) -> list[str]:
    return _matched_tag_alias_values(tags, DELIVERED_TAG_ALIASES)


def _matched_trustpilot_tags(tags: list[str]) -> list[str]:
    return _matched_tag_alias_values(tags, TRUSTPILOT_TAG_ALIASES)


def _matched_tag_alias_values(tags: list[str], aliases) -> list[str]:
    normalized = {_normalize_tag(tag) for tag in aliases}
    return [tag for tag in tags if _normalize_tag(tag) in normalized]


def _normalize_tag(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _collect_order_name_values(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        result = []
        for item in value:
            result.extend(_collect_order_name_values(item))
        return result
    if isinstance(value, dict):
        return _collect_order_name_values(value.get("order_name") or value.get("name"))
    return [_canonical_order_name(match) for match in re.findall(r"#?\d{3,}", _safe_text(value, 500))]


def _merged_names_from_text(text: str) -> list[str]:
    safe = _safe_text(text, 1000)
    if not re.search(r"(?i)(merged|combined|related|same shipment|shipped together|合并)", safe):
        return []
    return [_canonical_order_name(match) for match in re.findall(r"#?\d{3,}", safe)]


def _blocker_labels(blockers: list[str]) -> list[str]:
    labels = []
    for blocker in blockers:
        text = _safe_text(blocker, 160)
        if text == "blocked_missing_delivered_tag":
            labels.append("Not delivered.")
        elif text == "blocked_missing_review_request_tag":
            labels.append(f"Missing `{CANONICAL_REVIEW_REQUEST_TAG}`.")
        elif text == "blocked_merged_order_group_not_ready":
            labels.append("Merged order group is not ready.")
        elif "duplicate" in text or "trustpilot_invitation" in text:
            labels.append("Prior Trustpilot invitation evidence exists.")
        elif "risk" in text or "ticket" in text or "refund" in text or "cancel" in text:
            labels.append("Risk, ticket, refund, cancel, return, or dispute evidence is present.")
        elif text:
            labels.append(text)
    return labels


def _filtered_source_blocking_reasons(blockers: list[str], review_request_tag_status, source: dict) -> list[str]:
    repeat_confirmed = _int_value(source.get("customer_order_count")) > 1 or source.get("repeat_customer_detected") is True
    filtered = []
    for blocker in blockers:
        text = _safe_text(blocker, 160).lower()
        if review_request_tag_status is True and "missing_review_request_tag" in text:
            continue
        if review_request_tag_status is True and "missing" in text and "review request" in text:
            continue
        if "merged_order_group_not_ready" in text:
            continue
        if repeat_confirmed and (
            "repeat_customer_not_confirmed" in text
            or "first_order" in text
            or "first order" in text
        ):
            continue
        filtered.append(blocker)
    return filtered


def _int_value(value) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _local_risk(local: dict, source: dict) -> bool:
    text = " ".join(
        _safe_text(value, 200).lower()
        for value in (
            local.get("financial_status"),
            local.get("fulfillment_status"),
            local.get("fulfillment_status_raw"),
            local.get("settlement_status"),
            source.get("classification"),
            source.get("status"),
            source.get("reason"),
        )
    )
    return any(
        keyword in text
        for keyword in ("refund", "returned", "return", "cancel", "cancelled", "void", "dispute", "chargeback", "complaint", "ticket")
    )


def _missing_requirement(delivered: bool, canonical_tag: bool, trustpilot_sent: bool, blockers: list[str]) -> str:
    missing = []
    if not delivered:
        missing.append("Delivered / 妥投")
    if canonical_tag is None:
        missing.append("Shopify tag data loaded")
    elif not canonical_tag:
        missing.append(CANONICAL_REVIEW_REQUEST_TAG)
    if trustpilot_sent:
        missing.append("No prior Trustpilot send")
    text = " ".join(blockers).lower()
    if "merged" in text or "related" in text:
        missing.append("Whole merged/related group ready")
    if "risk" in text or "ticket" in text or "refund" in text or "dispute" in text:
        missing.append("No ticket/refund/risk")
    return ", ".join(_dedupe(missing)) or "None"


def _dedupe_summary_rows(rows: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for row in rows:
        key = (row.get("order", ""), row.get("trustpilot_email_status", ""), row.get("evidence", ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result


def _first_text(row: dict, keys: tuple[str, ...]) -> str:
    for key in keys:
        value = row.get(key) if isinstance(row, dict) else ""
        text = _safe_text(value, 300)
        if text:
            return text
    return ""


def _canonical_order_name(value) -> str:
    text = _safe_text(value, 80).strip()
    if not text:
        return ""
    match = re.fullmatch(r"#?(\d{3,})", text)
    return f"#{match.group(1)}" if match else text


def _is_simulator_order_name(value) -> bool:
    return _safe_text(value, 80).upper().startswith("#SIM")


def _safe_masked_email(value) -> str:
    text = _safe_text(value, 120)
    if not text:
        return ""
    if "***" in text and "@" in text:
        return text
    return _mask_email(text)


def _mask_email(value) -> str:
    text = _safe_text(value, 120).strip().lower()
    if not EMAIL_RE.fullmatch(text):
        return ""
    local, domain = text.rsplit("@", 1)
    domain_parts = domain.split(".")
    if len(domain_parts) >= 2:
        domain_mask = f"{domain_parts[0][:1]}***.{domain_parts[-1]}"
    else:
        domain_mask = "***"
    return f"{local[:1]}***@{domain_mask}"


def _safe_name(value) -> str:
    text = _safe_text(value, 120)
    if not text or EMAIL_RE.search(text):
        return ""
    return text


def _dedupe(values) -> list:
    result = []
    seen = set()
    for value in values or []:
        if value in ("", None):
            continue
        key = str(value)
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _safe_text(value: object, max_length: int = 300) -> str:
    return _sanitize_text(value, max_length=max_length).strip()


def _sanitize_text(value: object, max_length: int = 1000) -> str:
    text = str(value or "")
    text = EMAIL_RE.sub("[masked-email]", text)
    text = SECRET_RE.sub("[redacted-secret-marker]", text)
    text = "".join(ch if ch == "\n" or ch == "\t" or ord(ch) >= 32 else " " for ch in text)
    return text[:max_length]


def _tail(value: str, max_lines: int = 80) -> str:
    return "\n".join(str(value or "").splitlines()[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
