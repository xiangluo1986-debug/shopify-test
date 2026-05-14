import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_tag_write_design_dry_run"
COMMAND_LABEL = "shopify_review_request_trustpilot_tag_write_design_dry_run"

SOURCE_SEND_AUDIT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.json"
SOURCE_SEND_AUDIT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.html"
SOURCE_REPEAT_GUARD_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_repeat_customer_guard.json"
SOURCE_RETURN_GUARD_JSON_PATH = LOG_DIR / "shopify_review_request_returned_package_guard.json"
SOURCE_CANDIDATE_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_candidate_scan.json"
PROTECTED_DRAFT_SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_design_dry_run.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_design_dry_run.html"

SUCCESS_STATUS = "trustpilot_tag_write_design_dry_run_ready"
EXPECTED_SEND_AUDIT_STATUS = "trustpilot_gmail_one_draft_send_audit_passed"
EXPECTED_REPEAT_GUARD_STATUS = "repeat_customer_guard_passed"
EXPECTED_RETURN_GUARD_STATUS = "returned_package_guard_passed"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
PLANNED_SHOPIFY_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]
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


def run_shopify_review_request_trustpilot_tag_write_design_dry_run_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    send_audit, send_audit_error = _read_json_report(SOURCE_SEND_AUDIT_JSON_PATH, "blocked_missing_send_audit_report")
    repeat_guard, repeat_guard_error = _read_json_report(SOURCE_REPEAT_GUARD_JSON_PATH, "blocked_repeat_customer_guard_not_passed")
    return_guard, return_guard_error = _read_json_report(SOURCE_RETURN_GUARD_JSON_PATH, "blocked_returned_package_guard_not_passed")
    candidate_scan, candidate_scan_error = _read_json_report(SOURCE_CANDIDATE_SCAN_JSON_PATH, "candidate_scan_missing_for_duplicate_tag_check")
    source_privacy_scan = {
        "send_audit_json": _privacy_scan_text(_read_text(SOURCE_SEND_AUDIT_JSON_PATH)),
        "send_audit_html": _privacy_scan_text(_read_text(SOURCE_SEND_AUDIT_HTML_PATH)),
    }
    duplicate_check = _duplicate_trustpilot_tag_check(candidate_scan, candidate_scan_error)
    full_draft_id_leak = _full_draft_id_leak_detected(
        _read_text(SOURCE_SEND_AUDIT_JSON_PATH),
        _read_text(SOURCE_SEND_AUDIT_HTML_PATH),
    )
    blocking_conditions = _blocking_conditions(
        send_audit=send_audit,
        send_audit_error=send_audit_error,
        repeat_guard=repeat_guard,
        repeat_guard_error=repeat_guard_error,
        return_guard=return_guard,
        return_guard_error=return_guard_error,
        duplicate_check=duplicate_check,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
    )
    status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        send_audit=send_audit,
        send_audit_error=send_audit_error,
        repeat_guard=repeat_guard,
        repeat_guard_error=repeat_guard_error,
        return_guard=return_guard,
        return_guard_error=return_guard_error,
        duplicate_check=duplicate_check,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        blocking_conditions=blocking_conditions,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_json_report(path: Path, missing_status: str) -> tuple[dict, str]:
    if not path.exists():
        return {}, missing_status
    try:
        return json.loads(path.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"{missing_status}: source JSON parse failed: {exc}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _blocking_conditions(
    send_audit: dict,
    send_audit_error: str,
    repeat_guard: dict,
    repeat_guard_error: str,
    return_guard: dict,
    return_guard_error: str,
    duplicate_check: dict,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
) -> list[dict]:
    conditions = []
    if send_audit_error:
        return [{"status": "blocked_missing_send_audit_report", "detail": _sanitize_text(send_audit_error)}]
    if send_audit.get("send_audit_status") != EXPECTED_SEND_AUDIT_STATUS or send_audit.get("success") is not True:
        conditions.append({"status": "blocked_send_audit_not_passed", "detail": "Phase 3.17 send audit did not pass."})
    if _safe_text(send_audit.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_send_audit_not_passed", "detail": "selected_order_name mismatch."})
    if _safe_text(send_audit.get("selected_masked_email", "")) != EXPECTED_MASKED_EMAIL:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "selected_masked_email mismatch."})
    if not _is_masked_email(send_audit.get("selected_masked_email", "")):
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "selected_masked_email is not masked."})
    if _safe_text(send_audit.get("source_gmail_draft_id_partial", "")) != EXPECTED_DRAFT_ID_PARTIAL:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "Gmail draft id partial mismatch."})
    if int(send_audit.get("sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "sent_count must equal 1."})
    if send_audit.get("gmail_drafts_send_confirmed") is not True:
        conditions.append({"status": "blocked_email_not_sent", "detail": "Gmail drafts.send is not confirmed."})
    if send_audit.get("gmail_messages_send_confirmed_false") is not True:
        conditions.append({"status": "blocked_messages_send_detected", "detail": "Gmail messages.send false confirmation missing."})
    if send_audit.get("email_sent_confirmed") is not True:
        conditions.append({"status": "blocked_email_not_sent", "detail": "email_sent is not confirmed."})
    if send_audit.get("shopify_write_confirmed_false") is not True:
        conditions.append({"status": "blocked_shopify_write_already_detected", "detail": "source Shopify write false confirmation missing."})
    if send_audit.get("tag_write_confirmed_false") is not True:
        conditions.append({"status": "blocked_tag_write_already_detected", "detail": "source tag write false confirmation missing."})
    if send_audit.get("kudosi_ali_confirmed_false") is not True:
        conditions.append({"status": "blocked_send_audit_not_passed", "detail": "source Kudosi/Ali false confirmation missing."})

    if repeat_guard_error or repeat_guard.get("repeat_customer_guard_status") != EXPECTED_REPEAT_GUARD_STATUS:
        conditions.append({"status": "blocked_repeat_customer_guard_not_passed", "detail": _sanitize_text(repeat_guard_error or "repeat guard did not pass.")})
    if repeat_guard.get("repeat_customer_confirmed") is not True or repeat_guard.get("future_trustpilot_send_allowed") is not True:
        conditions.append({"status": "blocked_repeat_customer_guard_not_passed", "detail": "repeat customer guard did not confirm send eligibility."})

    if return_guard_error or return_guard.get("return_guard_status") != EXPECTED_RETURN_GUARD_STATUS:
        conditions.append({"status": "blocked_returned_package_guard_not_passed", "detail": _sanitize_text(return_guard_error or "returned package guard did not pass.")})
    if return_guard.get("return_tag_detected") is True or return_guard.get("trustpilot_send_allowed") is not True:
        conditions.append({"status": "blocked_returned_package_guard_not_passed", "detail": "returned package guard does not allow Trustpilot send/tag flow."})

    if duplicate_check["duplicate_trustpilot_tag_detected"]:
        conditions.append({"status": "blocked_duplicate_trustpilot_tag_detected", "detail": "local source report already contains a Trustpilot tag alias."})
    if _privacy_scan_failed(source_privacy_scan) or full_draft_id_leak_detected:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source report privacy scan failed."})
    return conditions


def _duplicate_trustpilot_tag_check(candidate_scan: dict, candidate_scan_error: str) -> dict:
    result = {
        "duplicate_tag_check_source": str(SOURCE_CANDIDATE_SCAN_JSON_PATH),
        "duplicate_tag_check_source_available": False,
        "candidate_order_found": False,
        "duplicate_trustpilot_tag_detected": False,
        "canonical_trustpilot_tag_detected": False,
        "legacy_trustpilot_tag_detected": False,
        "matched_trustpilot_tags": [],
        "matched_legacy_trustpilot_tags": [],
        "safe_tags_summary": [],
        "duplicate_tag_check_error_sanitized": _sanitize_text(candidate_scan_error),
        "future_live_shopify_tag_readback_required": True,
    }
    if candidate_scan_error:
        return result
    orders = candidate_scan.get("orders") if isinstance(candidate_scan.get("orders"), list) else []
    result["duplicate_tag_check_source_available"] = True
    row = next((order for order in orders if _safe_text(order.get("order_name", "")) == EXPECTED_ORDER_NAME), {})
    if not row:
        result["duplicate_tag_check_error_sanitized"] = "selected order was not found in local candidate scan report."
        return result
    result["candidate_order_found"] = True
    tags = [_safe_text(tag) for tag in row.get("tags", []) if str(tag).strip()]
    result["safe_tags_summary"] = tags
    matched = [tag for tag in tags if _is_trustpilot_tag_alias(tag)]
    legacy_matched = [tag for tag in matched if not _is_exact_canonical_trustpilot_tag(tag)]
    result["matched_trustpilot_tags"] = matched
    result["matched_legacy_trustpilot_tags"] = legacy_matched
    result["duplicate_trustpilot_tag_detected"] = bool(matched)
    result["canonical_trustpilot_tag_detected"] = any(_is_exact_canonical_trustpilot_tag(tag) for tag in matched)
    result["legacy_trustpilot_tag_detected"] = bool(legacy_matched)
    return result


def _is_trustpilot_tag_alias(tag: str) -> bool:
    normalized = _normalize_tag(tag)
    return normalized in {_normalize_tag(alias) for alias in TRUSTPILOT_TAG_ALIASES}


def _is_exact_canonical_trustpilot_tag(tag: str) -> bool:
    return str(tag or "").strip() == PLANNED_SHOPIFY_TAG


def _normalize_tag(tag: str) -> str:
    text = str(tag or "").strip().lower()
    text = re.sub(r"\s*:\s*", ":", text)
    return re.sub(r"\s+", " ", text)


def _build_payload(
    send_audit: dict,
    send_audit_error: str,
    repeat_guard: dict,
    repeat_guard_error: str,
    return_guard: dict,
    return_guard_error: str,
    duplicate_check: dict,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    success = status == SUCCESS_STATUS
    safety = _safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.18",
        "mode": "trustpilot-shopify-tag-write-design-dry-run",
        "command_label": COMMAND_LABEL,
        "tag_write_design_status": status,
        "success": success,
        "selected_order_name": EXPECTED_ORDER_NAME,
        "selected_masked_email": EXPECTED_MASKED_EMAIL,
        "source_gmail_draft_id_partial": EXPECTED_DRAFT_ID_PARTIAL,
        "source_send_audit_status": _safe_text(send_audit.get("send_audit_status", "")),
        "source_sent_count": int(send_audit.get("sent_count") or 0),
        "planned_shopify_tag": PLANNED_SHOPIFY_TAG,
        "planned_shopify_tag_action": f'add tag "{PLANNED_SHOPIFY_TAG}", dry-run only',
        "tag_write_dry_run_only": True,
        "real_tag_write_allowed_now": False,
        "future_real_tag_write_requires_manual_approval": True,
        "duplicate_trustpilot_tag_detected": duplicate_check["duplicate_trustpilot_tag_detected"],
        "matched_trustpilot_tags": duplicate_check["matched_trustpilot_tags"],
        "canonical_trustpilot_tag_detected": duplicate_check["canonical_trustpilot_tag_detected"],
        "legacy_trustpilot_tag_detected": duplicate_check["legacy_trustpilot_tag_detected"],
        "matched_legacy_trustpilot_tags": duplicate_check["matched_legacy_trustpilot_tags"],
        "canonical_trustpilot_tag": PLANNED_SHOPIFY_TAG,
        "trustpilot_tag_aliases": TRUSTPILOT_TAG_ALIASES,
        "trustpilot_tag_matching_policy": {
            "canonical_write_tag": PLANNED_SHOPIFY_TAG,
            "future_write_requires_exact_canonical_tag": True,
            "matching_normalizes_whitespace_around_colon": True,
            "matching_tolerates_legacy_trustpoilt_typo": True,
            "legacy_tags_are_not_removed_automatically": True,
        },
        "duplicate_tag_check_source": duplicate_check["duplicate_tag_check_source"],
        "duplicate_tag_check_source_available": duplicate_check["duplicate_tag_check_source_available"],
        "duplicate_tag_check_candidate_order_found": duplicate_check["candidate_order_found"],
        "duplicate_tag_check_error_sanitized": duplicate_check["duplicate_tag_check_error_sanitized"],
        "future_live_shopify_tag_readback_required": True,
        "repeat_customer_guard_confirmed": (
            repeat_guard.get("repeat_customer_guard_status") == EXPECTED_REPEAT_GUARD_STATUS
            and repeat_guard.get("repeat_customer_confirmed") is True
            and repeat_guard.get("future_trustpilot_send_allowed") is True
        ),
        "returned_package_guard_confirmed": (
            return_guard.get("return_guard_status") == EXPECTED_RETURN_GUARD_STATUS
            and return_guard.get("return_tag_detected") is not True
            and return_guard.get("trustpilot_send_allowed") is True
        ),
        "source_reports_used": {
            "send_audit_json_path": str(SOURCE_SEND_AUDIT_JSON_PATH),
            "send_audit_html_path": str(SOURCE_SEND_AUDIT_HTML_PATH),
            "repeat_guard_json_path": str(SOURCE_REPEAT_GUARD_JSON_PATH),
            "returned_package_guard_json_path": str(SOURCE_RETURN_GUARD_JSON_PATH),
            "candidate_scan_json_path": str(SOURCE_CANDIDATE_SCAN_JSON_PATH),
            "send_audit_error_sanitized": _sanitize_text(send_audit_error),
            "repeat_guard_error_sanitized": _sanitize_text(repeat_guard_error),
            "returned_package_guard_error_sanitized": _sanitize_text(return_guard_error),
        },
        "future_real_tag_write_gates": {
            "TRUSTPILOT_SHOPIFY_TAG_WRITE": "1",
            "TRUSTPILOT_SHOPIFY_TAG_WRITE_MAX": "1",
            "TRUSTPILOT_SHOPIFY_TAG_WRITE_ACK": "YES_I_APPROVE_ADDING_ONE_TRUSTPILOT_TAG",
            "DRY_RUN": "0",
            "target_order_name": EXPECTED_ORDER_NAME,
            "exact_tag_required": PLANNED_SHOPIFY_TAG,
        },
        "mandatory_future_real_write_rules": [
            "Re-read Shopify tags immediately before any real tag write.",
            "Block if any Trustpilot tag alias already exists.",
            "Block if repeat-customer guard is missing or not passed.",
            "Block if returned-package guard is missing or not passed.",
            "Do not resend email if future tag write fails; generate a manual recovery package.",
            "Use tagsAdd only in the future real-write phase; never overwrite the full tags field.",
        ],
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "source_privacy_scan": source_privacy_scan,
        "source_full_draft_id_leak_detected": full_draft_id_leak_detected,
        "privacy_scan_passed": not _privacy_scan_failed(source_privacy_scan) and not full_draft_id_leak_detected,
        "gmail_drafts_send_called_now": False,
        "gmail_messages_send_called_now": False,
        "email_sent_now": False,
        "shopify_tag_write_performed_now": False,
        "safety_summary": safety,
        **safety,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_tag_write_design_dry_run_path": str(REPORT_JSON_PATH),
        "html_trustpilot_tag_write_design_dry_run_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary() -> dict:
    return {
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "kudosi_api_call_performed": False,
        "kudosi_write_api_call_performed": False,
        "kudosi_review_request_send_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_tag_write_design_dry_run_path": str(json_path),
        "html_trustpilot_tag_write_design_dry_run_path": str(html_path),
        "tag_write_design_status": payload["tag_write_design_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "source_send_audit_status": payload["source_send_audit_status"],
        "source_sent_count": payload["source_sent_count"],
        "planned_shopify_tag": payload["planned_shopify_tag"],
        "duplicate_trustpilot_tag_detected": payload["duplicate_trustpilot_tag_detected"],
        "legacy_trustpilot_tag_detected": payload["legacy_trustpilot_tag_detected"],
        "repeat_customer_guard_confirmed": payload["repeat_customer_guard_confirmed"],
        "returned_package_guard_confirmed": payload["returned_package_guard_confirmed"],
        "real_tag_write_allowed_now": payload["real_tag_write_allowed_now"],
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
    blocking_rows = "\n".join(
        f"<tr><td>{escape(item.get('status', ''))}</td><td>{escape(item.get('detail', ''))}</td></tr>"
        for item in payload["blocking_conditions"]
    ) or "<tr><td colspan=\"2\">None</td></tr>"
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    gates = payload["future_real_tag_write_gates"]
    gate_rows = "\n".join(f"<tr><th>{escape(str(key))}</th><td><code>{escape(str(value))}</code></td></tr>" for key, value in gates.items())
    rules = "".join(f"<li>{escape(rule)}</li>" for rule in payload["mandatory_future_real_write_rules"])
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Shopify Tag Write Design Dry Run</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .warning {{ border-left: 4px solid #c2410c; background: #fff7ed; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Trustpilot Shopify Tag Write Design Dry Run</h1>
  <p class="warning">Phase 3.18 is design/dry-run only. No Shopify tag was written and no Gmail send was performed.</p>
  <p>Status: <strong>{escape(payload["tag_write_design_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Planned Shopify tag: <code>{escape(payload["planned_shopify_tag"])}</code></p>
  <p>Duplicate Trustpilot tag detected in local report: <strong>{escape(str(payload["duplicate_trustpilot_tag_detected"]))}</strong></p>
  <p>Legacy Trustpilot tag detected: <strong>{escape(str(payload["legacy_trustpilot_tag_detected"]))}</strong></p>
  <p>Repeat customer guard confirmed: <strong>{escape(str(payload["repeat_customer_guard_confirmed"]))}</strong></p>
  <p>Returned package guard confirmed: <strong>{escape(str(payload["returned_package_guard_confirmed"]))}</strong></p>
  <p>Real tag write allowed now: <strong>{escape(str(payload["real_tag_write_allowed_now"]))}</strong></p>
  <h2>Future Real Tag-Write Gates</h2>
  <table><tbody>{gate_rows}</tbody></table>
  <h2>Mandatory Future Rules</h2>
  <ul>{rules}</ul>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>This Task Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>"""


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


def _privacy_scan_failed(source_privacy_scan: dict) -> bool:
    for scan in source_privacy_scan.values():
        if scan.get("raw_customer_email_count") or scan.get("token_secret_bearer_pattern_count"):
            return True
    return False


def _full_draft_id_leak_detected(*texts: str) -> bool:
    if not PROTECTED_DRAFT_SOURCE_JSON_PATH.exists():
        return False
    try:
        source = json.loads(PROTECTED_DRAFT_SOURCE_JSON_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return False
    draft_id = str(source.get("gmail_draft_id") or "").strip()
    if not draft_id:
        return False
    return any(draft_id in (text or "") for text in texts)


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["tag_write_design_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["privacy_scan_passed"] = False
        payload["real_tag_write_allowed_now"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "tag-write design self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    return payload


def _is_masked_email(value) -> bool:
    text = str(value or "")
    return bool(text and "@" in text and "***" in text and not EMAIL_RE.fullmatch(text))


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


def _issue_summary(status: str, blocking_conditions: list[dict]) -> str:
    if status == SUCCESS_STATUS:
        return "Trustpilot tag-write design dry-run is ready; future real write remains locked behind manual gates."
    return "Trustpilot tag-write design blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.18 Trustpilot Shopify tag-write design dry-run finished.\n"
        f"Status: {payload.get('tag_write_design_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Planned tag: {payload.get('planned_shopify_tag')}\n"
        f"Duplicate Trustpilot tag detected: {payload.get('duplicate_trustpilot_tag_detected')}\n"
        f"Legacy Trustpilot tag detected: {payload.get('legacy_trustpilot_tag_detected')}\n"
        f"Repeat guard confirmed: {payload.get('repeat_customer_guard_confirmed')}\n"
        f"Returned package guard confirmed: {payload.get('returned_package_guard_confirmed')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail send, no Shopify API/write/mutation/tagsAdd/tagsRemove, no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
