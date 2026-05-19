import json
import re
import sqlite3
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_customer_identity_drilldown_audit"
COMMAND_LABEL = "shopify_review_request_customer_identity_drilldown_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_customer_identity_drilldown_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_customer_identity_drilldown_audit.html"
SQLITE_DB_PATH = PROJECT_ROOT / "backend" / "db.sqlite3"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_CUSTOMER_IDENTITY_DRILLDOWN_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_CUSTOMER_IDENTITY_DRILLDOWN_AUDIT_JSON_END"
TARGET_ORDER_NAME = "#21687"
USER_REPORTED_SHOPIFY_UI_ORDER_COUNT = 7
NOTE_FIELDS = (
    "shopify_note",
    "shopify_note_attributes",
    "warehouse_note",
    "transfer_note",
    "exception_review_reason",
)
NOTE_KEYWORDS = (
    "trustpilot",
    "trustpoilt",
    "truspilot",
    "trustpoit",
    "trust pilot",
    "trust poilt",
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=]|secret\s*[:=])"
)


def run_shopify_review_request_customer_identity_drilldown_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_audit()
    if completed["success"]:
        payload = completed["payload"]
    else:
        payload = _fallback_from_sqlite(completed) or _failure_payload(completed)
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["privacy_scan_summary"] = _privacy_scan(payload)

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_audit() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_customer_identity_drilldown_audit_report; "
        "payload = build_review_request_customer_identity_drilldown_audit_report({}); "
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
        return _failed_run("docker_command_not_found", 127, "", "Docker command was not found.")
    except PermissionError:
        return _failed_run("docker_permission_denied", 126, "", "Docker permission denied.")
    except subprocess.TimeoutExpired as exc:
        return _failed_run("timeout", 124, _to_text(exc.stdout), _to_text(exc.stderr))

    stdout = _to_text(completed.stdout)
    stderr = _to_text(completed.stderr)
    payload = _extract_payload(stdout)
    if completed.returncode != 0:
        return _failed_run("django_local_audit_failed", completed.returncode, stdout, stderr)
    if not payload:
        return _failed_run("audit_payload_missing", 1, stdout, stderr)
    payload["django_audit_source"] = "django"
    return {"success": True, "exit_code": 0, "payload": payload}


def _fallback_from_sqlite(result: dict) -> dict:
    orders = _load_sqlite_orders()
    if not orders:
        return {}
    target = _find_order(orders, TARGET_ORDER_NAME)
    if not target:
        return _sqlite_payload(
            target={},
            strategy_details=[],
            local_confirmed_order_names=[],
            note_checks=[],
            note_matches=[],
            django_failure_type=_sanitize_text(result.get("failure_type", "")),
        )

    strategy_details = _sqlite_identity_strategy_details(target, orders)
    strategy_names = {item["strategy"]: item.get("matched_order_names") or [] for item in strategy_details}
    local_confirmed_order_names = _dedupe(
        (strategy_names.get("customer_email_exact") or [])
        + (strategy_names.get("combined_name_phone") or [])
        + (strategy_names.get("combined_shipping_name_address") or [])
    )
    safe_candidate_names = _safe_candidate_order_names(strategy_details)
    candidate_orders = [_find_order(orders, name) for name in safe_candidate_names]
    candidate_orders = [order for order in candidate_orders if order]
    if TARGET_ORDER_NAME not in {_canonical_order_name(item.get("order_name")) for item in candidate_orders}:
        candidate_orders.append(target)
    note_checks, note_matches = _sqlite_note_evidence_checks(candidate_orders, TARGET_ORDER_NAME)
    return _sqlite_payload(
        target=target,
        strategy_details=strategy_details,
        local_confirmed_order_names=local_confirmed_order_names,
        note_checks=note_checks,
        note_matches=note_matches,
        django_failure_type=_sanitize_text(result.get("failure_type", "")),
    )


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
                "shipping_name",
                "shipping_address1",
                "shipping_address2",
                "shipping_city",
                "shipping_province",
                "shipping_zip",
                "shipping_country",
                "shipping_phone",
                "order_created_at",
                "shopify_note",
                "shopify_note_attributes",
                "warehouse_note",
                "transfer_note",
                "exception_review_reason",
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


def _find_order(orders: list[dict], order_name: str) -> dict:
    target = _canonical_order_name(order_name)
    for order in orders:
        if _canonical_order_name(order.get("order_name") or order.get("order_number")) == target:
            return order
    return {}


def _sqlite_identity_strategy_details(target: dict, orders: list[dict]) -> list[dict]:
    customer_name = _safe_text(target.get("customer_name"), 255)
    shipping_name = _safe_text(target.get("shipping_name"), 255)
    email = _normalize_email(target.get("customer_email"))
    phone = _safe_text(target.get("shipping_phone"), 80)
    postcode = _safe_text(target.get("shipping_zip"), 40)
    address1 = _safe_text(target.get("shipping_address1"), 255)
    city = _safe_text(target.get("shipping_city"), 255)
    country = _safe_text(target.get("shipping_country"), 20)
    name_values = _dedupe([customer_name, shipping_name])

    return [
        _strategy_detail(
            "customer_email_exact",
            bool(email),
            orders,
            lambda order: _normalize_email(order.get("customer_email")) == email,
            ("customer_email",),
        ),
        _strategy_detail(
            "customer_name_exact",
            bool(customer_name),
            orders,
            lambda order: _safe_text(order.get("customer_name"), 255).casefold() == customer_name.casefold(),
            ("customer_name",),
        ),
        _strategy_detail(
            "shipping_name_exact",
            bool(shipping_name),
            orders,
            lambda order: _safe_text(order.get("shipping_name"), 255).casefold() == shipping_name.casefold(),
            ("shipping_name",),
        ),
        _strategy_detail(
            "shipping_phone_exact",
            bool(phone),
            orders,
            lambda order: _safe_text(order.get("shipping_phone"), 80) == phone,
            ("shipping_phone",),
        ),
        _strategy_detail(
            "shipping_postcode_exact",
            bool(postcode),
            orders,
            lambda order: _safe_text(order.get("shipping_zip"), 40).casefold() == postcode.casefold(),
            ("shipping_zip",),
        ),
        _strategy_detail(
            "combined_name_phone",
            bool(name_values and phone),
            orders,
            lambda order: _order_has_any_name(order, name_values)
            and _safe_text(order.get("shipping_phone"), 80) == phone,
            ("customer_name_or_shipping_name", "shipping_phone"),
        ),
        _strategy_detail(
            "combined_name_postcode",
            bool(name_values and postcode),
            orders,
            lambda order: _order_has_any_name(order, name_values)
            and _safe_text(order.get("shipping_zip"), 40).casefold() == postcode.casefold(),
            ("customer_name_or_shipping_name", "shipping_zip"),
        ),
        _strategy_detail(
            "shipping_name_postcode_exact",
            bool(shipping_name and postcode),
            orders,
            lambda order: _safe_text(order.get("shipping_name"), 255).casefold() == shipping_name.casefold()
            and _safe_text(order.get("shipping_zip"), 40).casefold() == postcode.casefold(),
            ("shipping_name", "shipping_zip"),
        ),
        _strategy_detail(
            "combined_shipping_name_address",
            bool(shipping_name and address1),
            orders,
            lambda order: _shipping_name_address_match(order, shipping_name, address1, city, postcode, country),
            ("shipping_name", "shipping_address"),
        ),
    ]


def _strategy_detail(strategy: str, available: bool, orders: list[dict], predicate, fields_used: tuple[str, ...]) -> dict:
    matched = [order for order in orders if available and predicate(order)]
    names = _dedupe(
        _canonical_order_name(order.get("order_name") or order.get("order_number"))
        for order in sorted(matched, key=_order_sort_key)
    )
    return {
        "strategy": strategy,
        "available": bool(available),
        "fields_used": list(fields_used),
        "match_order_count": len(names),
        "matched_order_names": names,
    }


def _order_has_any_name(order: dict, names: list[str]) -> bool:
    order_names = {
        _safe_text(order.get("customer_name"), 255).casefold(),
        _safe_text(order.get("shipping_name"), 255).casefold(),
    }
    return bool(order_names.intersection({name.casefold() for name in names if name}))


def _shipping_name_address_match(
    order: dict,
    shipping_name: str,
    address1: str,
    city: str,
    postcode: str,
    country: str,
) -> bool:
    if _safe_text(order.get("shipping_name"), 255).casefold() != shipping_name.casefold():
        return False
    if _safe_text(order.get("shipping_address1"), 255).casefold() != address1.casefold():
        return False
    if city and _safe_text(order.get("shipping_city"), 255).casefold() != city.casefold():
        return False
    if postcode and _safe_text(order.get("shipping_zip"), 40).casefold() != postcode.casefold():
        return False
    if country and _safe_text(order.get("shipping_country"), 20).casefold() != country.casefold():
        return False
    return True


def _safe_candidate_order_names(strategy_details: list[dict]) -> list[str]:
    safe_strategies = {
        "customer_email_exact",
        "customer_name_exact",
        "shipping_name_exact",
        "shipping_phone_exact",
        "combined_name_phone",
        "combined_name_postcode",
        "shipping_name_postcode_exact",
        "combined_shipping_name_address",
    }
    names = []
    for detail in strategy_details:
        if detail.get("strategy") in safe_strategies:
            names.extend(detail.get("matched_order_names") or [])
    return _dedupe(names)


def _sqlite_note_evidence_checks(candidate_orders: list[dict], target_order_name: str) -> tuple[list[dict], list[dict]]:
    checks = []
    matches = []
    target = _canonical_order_name(target_order_name)
    for order in sorted(candidate_orders, key=_order_sort_key):
        order_name = _canonical_order_name(order.get("order_name") or order.get("order_number"))
        if not order_name:
            continue
        for field_name in NOTE_FIELDS:
            keyword = ""
            for fragment in _note_text_fragments(order.get(field_name)):
                keyword = _trustpilot_keyword(fragment)
                if keyword:
                    break
            check = {
                "order_name": order_name,
                "field_name": field_name,
                "matched_keyword": keyword,
                "note_evidence_found": bool(keyword),
            }
            checks.append(check)
            if keyword and order_name != target:
                matches.append(check)
    return checks, matches


def _sqlite_payload(
    target: dict,
    strategy_details: list[dict],
    local_confirmed_order_names: list[str],
    note_checks: list[dict],
    note_matches: list[dict],
    django_failure_type: str,
) -> dict:
    strategy_counts = {item["strategy"]: int(item.get("match_order_count") or 0) for item in strategy_details}
    strategy_order_names = {item["strategy"]: item.get("matched_order_names") or [] for item in strategy_details}
    safe_candidate_names = _safe_candidate_order_names(strategy_details)
    possible_missed = [name for name in safe_candidate_names if name not in set(local_confirmed_order_names)]
    evidence = note_matches[0] if note_matches else {}
    local_missing = len(local_confirmed_order_names) < USER_REPORTED_SHOPIFY_UI_ORDER_COUNT
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.31B",
        "mode": "dry-run-local-customer-identity-drilldown-audit-sqlite-fallback",
        "command_label": COMMAND_LABEL,
        "report_status": "customer_identity_drilldown_audit_ready_from_sqlite_fallback",
        "success": True,
        "fallback_source": "sqlite",
        "django_failure_type": django_failure_type,
        "target_order_name": TARGET_ORDER_NAME,
        "target_order_found": bool(target),
        "user_reported_shopify_ui_order_count": USER_REPORTED_SHOPIFY_UI_ORDER_COUNT,
        "local_order_fields": _local_order_fields(target),
        "local_confirmed_order_count": len(local_confirmed_order_names),
        "local_confirmed_order_names": local_confirmed_order_names,
        "local_confirmed_match_method": _match_method_from_strategy_counts(strategy_counts),
        "local_confirmed_confidence": "high" if strategy_counts.get("customer_email_exact") else "medium",
        "identity_strategy_counts": strategy_counts,
        "identity_strategy_order_names": strategy_order_names,
        "identity_strategy_details": strategy_details,
        "exact_email_match_order_count": strategy_counts.get("customer_email_exact", 0),
        "exact_customer_name_match_order_count": strategy_counts.get("customer_name_exact", 0),
        "shipping_phone_match_order_count": strategy_counts.get("shipping_phone_exact", 0),
        "shipping_name_postcode_match_order_count": strategy_counts.get("shipping_name_postcode_exact", 0),
        "broader_safe_candidate_matched_order_names": safe_candidate_names,
        "possible_missed_historical_orders": possible_missed,
        "why_only_counted_orders": _count_reason(local_confirmed_order_names, strategy_details, local_missing),
        "note_evidence_checks": note_checks,
        "note_evidence_matches": note_matches,
        "trustpilot_note_evidence_found": bool(note_matches),
        "trustpoilt_note_evidence_found": bool(note_matches),
        "evidence_order_name": _safe_text(evidence.get("order_name"), 80),
        "evidence_field_name": _safe_text(evidence.get("field_name"), 120),
        "evidence_safe_keyword": _safe_text(evidence.get("matched_keyword"), 80),
        "should_block_order_21687": bool(note_matches),
        "candidate_scan_blocker_update_needed": bool(note_matches),
        "local_data_missing_customer_history": local_missing,
        "manual_evidence_mode": {
            "shopify_ui_order_count_reported_by_user": USER_REPORTED_SHOPIFY_UI_ORDER_COUNT,
            "local_data_missing_customer_history": local_missing,
            "recommended_action": _recommended_action(local_missing, possible_missed),
        },
        "#21687_local_confirmed_order_count": len(local_confirmed_order_names),
        "#21687_identity_strategy_counts": strategy_counts,
        "#21687_potential_matched_order_names": safe_candidate_names,
        "#21687_trustpoilt_note_evidence_found": bool(note_matches),
        "#21687_evidence_order_name": _safe_text(evidence.get("order_name"), 80),
        "#21687_should_now_be_blocked": bool(note_matches),
        "#21687_local_data_appears_incomplete": local_missing,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
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
        "raw_phone_output": False,
        "raw_address_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            f"#21687 identity drilldown ready from SQLite fallback. Local confirmed orders={len(local_confirmed_order_names)}; "
            f"potential local candidate orders={len(safe_candidate_names)}; "
            f"historical Trustpilot note evidence found={bool(note_matches)}; "
            f"local data missing versus Shopify UI count={local_missing}. "
            "No Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, external API, email, tag write, "
            "mutation, or translationsRegister call was performed."
        ),
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


def _failed_run(failure_type: str, exit_code: int, stdout: str, stderr: str) -> dict:
    return {
        "success": False,
        "exit_code": exit_code,
        "failure_type": failure_type,
        "stdout": _sanitize_text(stdout),
        "stderr": _sanitize_text(stderr),
    }


def _failure_payload(result: dict) -> dict:
    return {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.31B",
        "mode": "dry-run-local-customer-identity-drilldown-audit",
        "command_label": COMMAND_LABEL,
        "report_status": "blocked_customer_identity_drilldown_audit_failed",
        "success": False,
        "failure_type": _sanitize_text(result.get("failure_type", "")),
        "exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(result.get("stdout", "")),
        "stderr_tail_sanitized": _tail(result.get("stderr", "")),
        "target_order_name": "#21687",
        "local_confirmed_order_count": 0,
        "local_confirmed_order_names": [],
        "identity_strategy_counts": {},
        "broader_safe_candidate_matched_order_names": [],
        "trustpilot_note_evidence_found": False,
        "evidence_order_name": "",
        "should_block_order_21687": False,
        "local_data_missing_customer_history": True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
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
        "raw_phone_output": False,
        "raw_address_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": "Customer identity drilldown audit failed before producing a local report.",
    }


def _write_json(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(_sanitize_payload(payload), report_file, ensure_ascii=True, indent=2, sort_keys=True)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(_sanitize_payload(payload)), encoding="utf-8")
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
        "order_21687_local_confirmed_order_count": int(payload.get("local_confirmed_order_count") or 0),
        "order_21687_identity_strategy_counts": payload.get("identity_strategy_counts") or {},
        "order_21687_potential_matched_order_names": payload.get("broader_safe_candidate_matched_order_names") or [],
        "order_21687_trustpoilt_note_evidence_found": payload.get("trustpoilt_note_evidence_found") is True
        or payload.get("trustpilot_note_evidence_found") is True,
        "order_21687_evidence_order_name": payload.get("evidence_order_name", ""),
        "order_21687_should_now_be_blocked": payload.get("should_block_order_21687") is True,
        "order_21687_local_data_appears_incomplete": payload.get("local_data_missing_customer_history") is True,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "external_review_api_call_performed": False,
        "raw_customer_email_output": False,
        "raw_phone_output": False,
        "raw_address_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "detected_issue_summary": payload.get("detected_issue_summary", ""),
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    counts = payload.get("identity_strategy_counts") or {}
    return (
        "Customer identity drilldown audit complete.\n"
        f"Status: {payload.get('report_status')}\n"
        f"#21687 local confirmed orders: {payload.get('local_confirmed_order_count')}\n"
        f"#21687 potential matched orders: {', '.join(payload.get('broader_safe_candidate_matched_order_names') or [])}\n"
        f"Identity counts: {json.dumps(counts, ensure_ascii=True, sort_keys=True)}\n"
        f"Trustpoilt/Trustpilot note evidence found: {payload.get('trustpoilt_note_evidence_found') is True or payload.get('trustpilot_note_evidence_found') is True}\n"
        f"Evidence order: {payload.get('evidence_order_name') or 'None'}\n"
        f"Should block #21687: {payload.get('should_block_order_21687') is True}\n"
        f"Local data appears incomplete: {payload.get('local_data_missing_customer_history') is True}\n"
        "Safety: no Gmail, Shopify, Trustpilot, Kudosi, Ali Reviews, external API, email, tag write, "
        "mutation, or translationsRegister call was performed.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}"
    )


def _render_html(payload: dict) -> str:
    counts = payload.get("identity_strategy_counts") or {}
    details = payload.get("identity_strategy_details") or []
    note_matches = payload.get("note_evidence_matches") or []
    count_rows = "".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in counts.items()
    )
    detail_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('strategy', '')))}</td>"
        f"<td>{escape(str(item.get('match_order_count', 0)))}</td>"
        f"<td>{escape(', '.join(item.get('matched_order_names') or []))}</td>"
        "</tr>"
        for item in details
    )
    match_rows = "".join(
        "<tr>"
        f"<td>{escape(str(item.get('order_name', '')))}</td>"
        f"<td>{escape(str(item.get('field_name', '')))}</td>"
        f"<td>{escape(str(item.get('matched_keyword', '')))}</td>"
        "</tr>"
        for item in note_matches
    )
    if not match_rows:
        match_rows = "<tr><td colspan=\"3\">No historical Trustpilot note evidence found.</td></tr>"
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Customer Identity Drilldown Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Customer Identity Drilldown Audit</h1>
  <table><tbody>
    <tr><th>Status</th><td>{escape(str(payload.get("report_status", "")))}</td></tr>
    <tr><th>Target order</th><td>{escape(str(payload.get("target_order_name", "")))}</td></tr>
    <tr><th>Local confirmed orders</th><td>{escape(str(payload.get("local_confirmed_order_count", 0)))}</td></tr>
    <tr><th>Local confirmed order names</th><td>{escape(", ".join(payload.get("local_confirmed_order_names") or []))}</td></tr>
    <tr><th>Potential matched order names</th><td>{escape(", ".join(payload.get("broader_safe_candidate_matched_order_names") or []))}</td></tr>
    <tr><th>Trustpoilt note evidence found</th><td>{escape(str(payload.get("trustpoilt_note_evidence_found") is True or payload.get("trustpilot_note_evidence_found") is True))}</td></tr>
    <tr><th>Evidence order</th><td>{escape(str(payload.get("evidence_order_name", "")))}</td></tr>
    <tr><th>Evidence field</th><td>{escape(str(payload.get("evidence_field_name", "")))}</td></tr>
    <tr><th>Safe keyword</th><td>{escape(str(payload.get("evidence_safe_keyword", "")))}</td></tr>
    <tr><th>Should block #21687</th><td>{escape(str(payload.get("should_block_order_21687") is True))}</td></tr>
    <tr><th>Local data incomplete</th><td>{escape(str(payload.get("local_data_missing_customer_history") is True))}</td></tr>
    <tr><th>Why only counted orders</th><td>{escape(str(payload.get("why_only_counted_orders", "")))}</td></tr>
  </tbody></table>
  <h2>Identity Strategy Counts</h2>
  <table><tbody>{count_rows}</tbody></table>
  <h2>Identity Strategy Order Names</h2>
  <table><thead><tr><th>Strategy</th><th>Count</th><th>Order names</th></tr></thead><tbody>{detail_rows}</tbody></table>
  <h2>Historical Note Evidence Matches</h2>
  <table><thead><tr><th>Order</th><th>Field</th><th>Matched keyword</th></tr></thead><tbody>{match_rows}</tbody></table>
  <h2>Safety</h2>
  <table><tbody>
    <tr><th>Shopify API call performed</th><td>{escape(str(payload.get("shopify_api_call_performed") is True))}</td></tr>
    <tr><th>Shopify write performed</th><td>{escape(str(payload.get("shopify_write_performed") is True))}</td></tr>
    <tr><th>Gmail API call performed</th><td>{escape(str(payload.get("gmail_api_call_performed") is True))}</td></tr>
    <tr><th>Email sent</th><td>{escape(str(payload.get("email_sent") is True))}</td></tr>
    <tr><th>Raw customer email output</th><td>{escape(str(payload.get("raw_customer_email_output") is True))}</td></tr>
    <tr><th>Raw phone output</th><td>{escape(str(payload.get("raw_phone_output") is True))}</td></tr>
    <tr><th>Raw address output</th><td>{escape(str(payload.get("raw_address_output") is True))}</td></tr>
    <tr><th>Full note output</th><td>{escape(str(payload.get("full_note_output") is True))}</td></tr>
  </tbody></table>
</body>
</html>"""


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(_sanitize_payload(payload), ensure_ascii=False, sort_keys=True)
    return {
        "scan_performed": True,
        "passed": EMAIL_RE.search(text) is None and SECRET_RE.search(text) is None,
        "raw_customer_email_count": 1 if EMAIL_RE.search(text) else 0,
        "secret_pattern_count": 1 if SECRET_RE.search(text) else 0,
        "full_note_output": False,
    }


def _sanitize_payload(value):
    if isinstance(value, dict):
        return {str(key): _sanitize_payload(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_sanitize_payload(item) for item in value]
    if isinstance(value, str):
        return _sanitize_text(value)
    return value


def _safe_text(value: object, max_length: int = 300) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return text[:max_length]


def _sanitize_text(value: object, max_length: int = 1000) -> str:
    text = _safe_text(value, max_length)
    text = EMAIL_RE.sub("[masked-email]", text)
    text = SECRET_RE.sub("[redacted-secret-like-value]", text)
    return text


def _tail(value: str, max_lines: int = 80) -> str:
    return "\n".join(_sanitize_text(line, 500) for line in str(value or "").splitlines()[-max_lines:])


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _canonical_order_name(value) -> str:
    text = _safe_text(value, 80)
    if not text:
        return ""
    match = re.fullmatch(r"#?(\d{3,})", text)
    if match:
        return f"#{match.group(1)}"
    return text


def _dedupe(values) -> list[str]:
    result = []
    seen = set()
    for value in values or []:
        text = _safe_text(value, 120)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _normalize_email(value) -> str:
    text = _safe_text(value, 255).lower()
    return text if EMAIL_RE.fullmatch(text) else ""


def _order_sort_key(order: dict):
    return (_safe_text(order.get("order_created_at"), 80), int(order.get("id") or 0))


def _note_text_fragments(value) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, dict):
        fragments = []
        for item in value.values():
            fragments.extend(_note_text_fragments(item))
        return fragments
    if isinstance(value, (list, tuple, set)):
        fragments = []
        for item in value:
            fragments.extend(_note_text_fragments(item))
        return fragments
    text = _safe_text(value, 2000)
    if text.startswith("{") or text.startswith("["):
        try:
            return _note_text_fragments(json.loads(text))
        except json.JSONDecodeError:
            pass
    return [text] if text else []


def _trustpilot_keyword(value) -> str:
    compact = re.sub(r"[^a-z0-9]+", "", _safe_text(value, 2000).lower())
    if not compact:
        return ""
    for keyword in NOTE_KEYWORDS:
        if re.sub(r"[^a-z0-9]+", "", keyword.lower()) in compact:
            return keyword
    return ""


def _local_order_fields(order: dict) -> dict:
    order = order or {}
    return {
        "order_name": _canonical_order_name(order.get("order_name") or order.get("order_number")),
        "order_number": _safe_text(order.get("order_number"), 80),
        "customer_name": _partial_person_name(order.get("customer_name")),
        "customer_name_present": bool(_safe_text(order.get("customer_name"), 120)),
        "customer_email_present": bool(_normalize_email(order.get("customer_email"))),
        "shipping_name": _partial_person_name(order.get("shipping_name")),
        "shipping_name_present": bool(_safe_text(order.get("shipping_name"), 120)),
        "shipping_phone_present": bool(_safe_text(order.get("shipping_phone"), 80)),
        "shipping_address_present": bool(
            _safe_text(order.get("shipping_address1"), 120)
            or _safe_text(order.get("shipping_address2"), 120)
            or _safe_text(order.get("shipping_city"), 120)
            or _safe_text(order.get("shipping_province"), 120)
            or _safe_text(order.get("shipping_country"), 20)
        ),
        "shipping_postcode_present": bool(_safe_text(order.get("shipping_zip"), 40)),
        "shipping_address_postcode_present": bool(
            _safe_text(order.get("shipping_address1"), 120)
            and _safe_text(order.get("shipping_zip"), 40)
        ),
    }


def _partial_person_name(value) -> str:
    text = _safe_text(value, 120)
    if not text or EMAIL_RE.search(text):
        return ""
    parts = [part for part in re.split(r"\s+", text) if part]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"{parts[0][:1]}***"
    return f"{parts[0][:1]}*** {parts[-1][:1]}***"


def _match_method_from_strategy_counts(strategy_counts: dict) -> str:
    methods = []
    if strategy_counts.get("customer_email_exact"):
        methods.append("customer_email")
    if strategy_counts.get("combined_name_phone"):
        methods.append("name_shipping_phone")
    if strategy_counts.get("combined_shipping_name_address"):
        methods.append("name_shipping_address_postcode")
    return "+".join(_dedupe(methods)) or "unavailable"


def _count_reason(local_confirmed_order_names: list[str], strategy_details: list[dict], local_missing: bool) -> str:
    confirmed = _dedupe(local_confirmed_order_names)
    reason = (
        f"Current customer-history logic confirms {len(confirmed)} local orders: "
        f"{_join_order_names(confirmed) if confirmed else 'none'}."
    )
    broader = [
        f"{detail.get('strategy')}={int(detail.get('match_order_count') or 0)}"
        for detail in strategy_details
        if int(detail.get("match_order_count") or 0) > len(confirmed)
    ]
    if broader:
        reason += (
            " Broader local identity strategies show additional candidate orders "
            f"({', '.join(broader)}), but they are drilldown evidence until the matching policy is widened."
        )
    elif local_missing:
        reason += (
            " No broader local identity strategy found the 7-order Shopify UI history, so local sync or "
            "identity persistence appears incomplete."
        )
    return reason


def _recommended_action(local_missing: bool, possible_missed: list[str]) -> str:
    if local_missing:
        return (
            "Run wider Shopify customer/order sync or sync by customer id/email, and add Shopify customer id "
            "persistence if local orders do not store it."
        )
    if possible_missed:
        return (
            "Review the broader local candidate matches, then explicitly approve any matching-policy widening "
            "before changing send eligibility."
        )
    return "No wider customer-history sync action is indicated by local data."


def _join_order_names(order_names: list[str]) -> str:
    return ", ".join(_dedupe(order_names))
