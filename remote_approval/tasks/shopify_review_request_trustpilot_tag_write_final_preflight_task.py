import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_tag_write_final_preflight"
COMMAND_LABEL = "shopify_review_request_trustpilot_tag_write_final_preflight"

SOURCE_SEND_AUDIT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.json"
SOURCE_SEND_AUDIT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_audit.html"
SOURCE_TAG_WRITE_DESIGN_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_design_dry_run.json"
SOURCE_TAG_WRITE_DESIGN_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_design_dry_run.html"
SOURCE_TAG_WRITE_LOCKED_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_locked_runner.json"
SOURCE_TAG_WRITE_LOCKED_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_locked_runner.html"
PROTECTED_DRAFT_SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_final_preflight.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_final_preflight.html"

SUCCESS_STATUS = "trustpilot_tag_write_final_preflight_passed"
EXPECTED_SEND_AUDIT_STATUS = "trustpilot_gmail_one_draft_send_audit_passed"
EXPECTED_TAG_WRITE_DESIGN_STATUS = "trustpilot_tag_write_design_dry_run_ready"
EXPECTED_TAG_WRITE_LOCKED_STATUS = "dry_run_trustpilot_tag_not_written"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
EXPECTED_TAG_VALUE = "1: trustpilot"
TAG_WRITE_ACK_VALUE = "YES_I_APPROVE_ADDING_ONE_TRUSTPILOT_TAG"
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


def run_shopify_review_request_trustpilot_tag_write_final_preflight_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    send_audit, send_audit_error = _read_json_report(
        SOURCE_SEND_AUDIT_JSON_PATH, "blocked_missing_send_audit_report"
    )
    tag_write_design, tag_write_design_error = _read_json_report(
        SOURCE_TAG_WRITE_DESIGN_JSON_PATH, "blocked_missing_tag_write_design_report"
    )
    tag_write_locked, tag_write_locked_error = _read_json_report(
        SOURCE_TAG_WRITE_LOCKED_JSON_PATH, "blocked_missing_tag_write_locked_runner_report"
    )
    source_privacy_scan = {
        "send_audit_json": _privacy_scan_text(_read_text(SOURCE_SEND_AUDIT_JSON_PATH)),
        "send_audit_html": _privacy_scan_text(_read_text(SOURCE_SEND_AUDIT_HTML_PATH)),
        "tag_write_design_json": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_DESIGN_JSON_PATH)),
        "tag_write_design_html": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_DESIGN_HTML_PATH)),
        "tag_write_locked_json": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_LOCKED_JSON_PATH)),
        "tag_write_locked_html": _privacy_scan_text(_read_text(SOURCE_TAG_WRITE_LOCKED_HTML_PATH)),
    }
    full_draft_id_leak = _full_draft_id_leak_detected(
        _read_text(SOURCE_SEND_AUDIT_JSON_PATH),
        _read_text(SOURCE_SEND_AUDIT_HTML_PATH),
        _read_text(SOURCE_TAG_WRITE_DESIGN_JSON_PATH),
        _read_text(SOURCE_TAG_WRITE_DESIGN_HTML_PATH),
        _read_text(SOURCE_TAG_WRITE_LOCKED_JSON_PATH),
        _read_text(SOURCE_TAG_WRITE_LOCKED_HTML_PATH),
    )
    blocking_conditions = _blocking_conditions(
        send_audit=send_audit,
        send_audit_error=send_audit_error,
        tag_write_design=tag_write_design,
        tag_write_design_error=tag_write_design_error,
        tag_write_locked=tag_write_locked,
        tag_write_locked_error=tag_write_locked_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
    )
    status = blocking_conditions[0]["status"] if blocking_conditions else SUCCESS_STATUS
    payload = _build_payload(
        send_audit=send_audit,
        send_audit_error=send_audit_error,
        tag_write_design=tag_write_design,
        tag_write_design_error=tag_write_design_error,
        tag_write_locked=tag_write_locked,
        tag_write_locked_error=tag_write_locked_error,
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
    tag_write_design: dict,
    tag_write_design_error: str,
    tag_write_locked: dict,
    tag_write_locked_error: str,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
) -> list[dict]:
    conditions = []
    if send_audit_error:
        conditions.append({"status": "blocked_missing_send_audit_report", "detail": _sanitize_text(send_audit_error)})
    if tag_write_design_error:
        conditions.append(
            {"status": "blocked_missing_tag_write_design_report", "detail": _sanitize_text(tag_write_design_error)}
        )
    if tag_write_locked_error:
        conditions.append(
            {"status": "blocked_missing_tag_write_locked_runner_report", "detail": _sanitize_text(tag_write_locked_error)}
        )
    if conditions:
        return conditions

    if send_audit.get("send_audit_status") != EXPECTED_SEND_AUDIT_STATUS or send_audit.get("success") is not True:
        conditions.append({"status": "blocked_send_audit_not_passed", "detail": "Phase 3.17 send audit did not pass."})
    if tag_write_design.get("tag_write_design_status") != EXPECTED_TAG_WRITE_DESIGN_STATUS or tag_write_design.get("success") is not True:
        conditions.append({"status": "blocked_tag_write_design_not_ready", "detail": "Phase 3.18 tag-write design is not ready."})
    if tag_write_locked.get("tag_write_locked_status") != EXPECTED_TAG_WRITE_LOCKED_STATUS or tag_write_locked.get("success") is not True:
        conditions.append({"status": "blocked_tag_write_locked_runner_not_ready", "detail": "Phase 3.19 locked runner is not dry-run ready."})

    for source_name, source_report in {
        "send_audit": send_audit,
        "tag_write_design": tag_write_design,
        "tag_write_locked": tag_write_locked,
    }.items():
        if _safe_text(source_report.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
            conditions.append({"status": "blocked_target_order_mismatch", "detail": f"{source_name} selected_order_name mismatch."})
        masked_email = _safe_text(source_report.get("selected_masked_email", ""))
        if masked_email != EXPECTED_MASKED_EMAIL or not _is_masked_email(masked_email):
            conditions.append({"status": "blocked_privacy_scan_failed", "detail": f"{source_name} selected_masked_email mismatch or unmasked."})
        if _safe_text(source_report.get("source_gmail_draft_id_partial", "")) != EXPECTED_DRAFT_ID_PARTIAL:
            conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": f"{source_name} Gmail draft id partial mismatch."})

    if int(send_audit.get("sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "Phase 3.17 sent_count must equal 1."})
    if int(tag_write_design.get("source_sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "Phase 3.18 source_sent_count must equal 1."})
    if int(tag_write_locked.get("source_sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "Phase 3.19 source_sent_count must equal 1."})

    if _safe_text(tag_write_design.get("planned_shopify_tag", "")) != EXPECTED_TAG_VALUE:
        conditions.append({"status": "blocked_tag_value_mismatch", "detail": "Phase 3.18 planned_shopify_tag mismatch."})
    if _safe_text(tag_write_locked.get("planned_shopify_tag", "")) != EXPECTED_TAG_VALUE:
        conditions.append({"status": "blocked_tag_value_mismatch", "detail": "Phase 3.19 planned_shopify_tag mismatch."})
    if _safe_text(tag_write_locked.get("would_add_tag_value", "")) != EXPECTED_TAG_VALUE:
        conditions.append({"status": "blocked_tag_value_mismatch", "detail": "Phase 3.19 would_add_tag_value mismatch."})

    if tag_write_design.get("duplicate_trustpilot_tag_detected") is not False:
        conditions.append({"status": "blocked_duplicate_trustpilot_tag_detected", "detail": "Phase 3.18 duplicate tag check did not pass."})
    if tag_write_design.get("repeat_customer_guard_confirmed") is not True:
        conditions.append({"status": "blocked_repeat_customer_guard_not_confirmed", "detail": "Phase 3.18 repeat customer guard was not confirmed."})
    if tag_write_design.get("returned_package_guard_confirmed") is not True:
        conditions.append({"status": "blocked_returned_package_guard_not_confirmed", "detail": "Phase 3.18 returned package guard was not confirmed."})
    if tag_write_locked.get("would_add_tag") is not True:
        conditions.append({"status": "blocked_locked_runner_would_not_add_tag", "detail": "Phase 3.19 would_add_tag is not true."})
    if int(tag_write_locked.get("blocking_condition_count") or 0) != 0:
        conditions.append({"status": "blocked_locked_runner_has_blocking_conditions", "detail": "Phase 3.19 blocking_condition_count must be 0."})

    if _any_source_write_or_send_flag_true(send_audit, tag_write_design, tag_write_locked):
        conditions.append({"status": "blocked_unexpected_send_or_write_flag", "detail": "A source report has an unsafe current-phase write/send flag."})
    if _privacy_scan_failed(source_privacy_scan) or full_draft_id_leak_detected:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "Source JSON/HTML privacy scan failed."})
    return conditions


def _any_source_write_or_send_flag_true(*reports: dict) -> bool:
    unsafe_current_phase_flags = [
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "tags_add_performed",
        "tags_remove_performed",
        "tagsAdd_performed",
        "tagsRemove_performed",
        "gmail_api_call_performed_now",
        "gmail_drafts_send_called_now",
        "gmail_messages_send_called_now",
        "email_sent_now",
        "kudosi_api_call_performed",
        "ali_reviews_api_call_performed",
    ]
    for report in reports:
        for flag in unsafe_current_phase_flags:
            if report.get(flag) is True:
                return True
    return False


def _build_payload(
    send_audit: dict,
    send_audit_error: str,
    tag_write_design: dict,
    tag_write_design_error: str,
    tag_write_locked: dict,
    tag_write_locked_error: str,
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
        "phase": "3.20",
        "mode": "dry-run",
        "command_label": COMMAND_LABEL,
        "tag_write_final_preflight_status": status,
        "success": success,
        "source_reports_used": {
            "send_audit_json_path": str(SOURCE_SEND_AUDIT_JSON_PATH),
            "tag_write_design_json_path": str(SOURCE_TAG_WRITE_DESIGN_JSON_PATH),
            "tag_write_locked_json_path": str(SOURCE_TAG_WRITE_LOCKED_JSON_PATH),
            "send_audit_error_sanitized": _sanitize_text(send_audit_error),
            "tag_write_design_error_sanitized": _sanitize_text(tag_write_design_error),
            "tag_write_locked_error_sanitized": _sanitize_text(tag_write_locked_error),
        },
        "source_send_audit_status": _safe_text(send_audit.get("send_audit_status", "")),
        "source_tag_write_design_status": _safe_text(tag_write_design.get("tag_write_design_status", "")),
        "source_tag_write_locked_status": _safe_text(tag_write_locked.get("tag_write_locked_status", "")),
        "selected_order_name": _safe_text(tag_write_design.get("selected_order_name", EXPECTED_ORDER_NAME)),
        "selected_masked_email": _safe_text(tag_write_design.get("selected_masked_email", EXPECTED_MASKED_EMAIL)),
        "source_gmail_draft_id_partial": _safe_text(tag_write_design.get("source_gmail_draft_id_partial", EXPECTED_DRAFT_ID_PARTIAL)),
        "planned_shopify_tag": _safe_text(tag_write_design.get("planned_shopify_tag", EXPECTED_TAG_VALUE)),
        "source_sent_count": int(tag_write_design.get("source_sent_count") or 0),
        "duplicate_trustpilot_tag_detected": tag_write_design.get("duplicate_trustpilot_tag_detected") is True,
        "repeat_customer_guard_confirmed": tag_write_design.get("repeat_customer_guard_confirmed") is True,
        "returned_package_guard_confirmed": tag_write_design.get("returned_package_guard_confirmed") is True,
        "locked_runner_would_add_tag": tag_write_locked.get("would_add_tag") is True,
        "locked_runner_would_add_tag_value": _safe_text(tag_write_locked.get("would_add_tag_value", "")),
        "locked_runner_blocking_condition_count": int(tag_write_locked.get("blocking_condition_count") or 0),
        "tag_write_preflight_ready_for_manual_real_write_approval": success,
        "real_tag_write_allowed_now": False,
        "future_real_tag_write_requires_manual_approval": True,
        "future_real_tag_write_required_env_gates": {
            "TRUSTPILOT_SHOPIFY_TAG_WRITE": "1",
            "TRUSTPILOT_SHOPIFY_TAG_WRITE_MAX": "1",
            "TRUSTPILOT_SHOPIFY_TAG_WRITE_ACK": TAG_WRITE_ACK_VALUE,
            "DRY_RUN": "0",
        },
        "future_real_tag_write_constraints": {
            "target_order_name": EXPECTED_ORDER_NAME,
            "tag_value_exact": EXPECTED_TAG_VALUE,
            "allowed_shopify_action": "tagsAdd",
            "max_target_count": 1,
            "max_tag_count": 1,
            "post_write_audit_required": True,
            "do_not_resend_email_if_tag_write_fails": True,
        },
        "source_privacy_scan": source_privacy_scan,
        "source_full_draft_id_leak_detected": full_draft_id_leak_detected,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "safety_summary": safety,
        **safety,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_tag_write_final_preflight_path": str(REPORT_JSON_PATH),
        "html_trustpilot_tag_write_final_preflight_path": str(REPORT_HTML_PATH),
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
        "gmail_api_call_performed": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "email_sent": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_tag_write_final_preflight_path": str(json_path),
        "html_trustpilot_tag_write_final_preflight_path": str(html_path),
        "tag_write_final_preflight_status": payload["tag_write_final_preflight_status"],
        "source_send_audit_status": payload["source_send_audit_status"],
        "source_tag_write_design_status": payload["source_tag_write_design_status"],
        "source_tag_write_locked_status": payload["source_tag_write_locked_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "planned_shopify_tag": payload["planned_shopify_tag"],
        "source_sent_count": payload["source_sent_count"],
        "duplicate_trustpilot_tag_detected": payload["duplicate_trustpilot_tag_detected"],
        "repeat_customer_guard_confirmed": payload["repeat_customer_guard_confirmed"],
        "returned_package_guard_confirmed": payload["returned_package_guard_confirmed"],
        "locked_runner_would_add_tag": payload["locked_runner_would_add_tag"],
        "locked_runner_would_add_tag_value": payload["locked_runner_would_add_tag_value"],
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
    gate_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td><code>{escape(str(value))}</code></td></tr>"
        for key, value in payload["future_real_tag_write_required_env_gates"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Tag Write Final Preflight</title>
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
  <h1>Trustpilot Tag Write Final Preflight</h1>
  <p class="warning">Phase 3.20 is preflight only. No Shopify API call, mutation, tagsAdd, tagsRemove, or Gmail send was performed.</p>
  <p>Status: <strong>{escape(payload["tag_write_final_preflight_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Planned Shopify tag: <code>{escape(payload["planned_shopify_tag"])}</code></p>
  <p>Real tag write allowed now: <strong>{escape(str(payload["real_tag_write_allowed_now"]))}</strong></p>
  <p>Ready for manual real-write approval: <strong>{escape(str(payload["tag_write_preflight_ready_for_manual_real_write_approval"]))}</strong></p>
  <h2>Future Real-Write Gates</h2>
  <table><tbody>{gate_rows}</tbody></table>
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
        payload["tag_write_final_preflight_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["tag_write_preflight_ready_for_manual_real_write_approval"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "tag-write final preflight self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
    return payload


def _is_masked_email(value: str) -> bool:
    return "***@" in str(value or "") and not EMAIL_RE.fullmatch(str(value or ""))


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
        return "Trustpilot Shopify tag-write final preflight passed; real tag write remains disabled in this phase."
    return "Trustpilot Shopify tag-write final preflight blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.20 Trustpilot tag-write final preflight finished.\n"
        f"Status: {payload.get('tag_write_final_preflight_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Planned tag: {payload.get('planned_shopify_tag')}\n"
        f"Ready for future manual real-write approval: {payload.get('tag_write_preflight_ready_for_manual_real_write_approval')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Shopify API/write/mutation/tagsAdd/tagsRemove, no Gmail send, no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
