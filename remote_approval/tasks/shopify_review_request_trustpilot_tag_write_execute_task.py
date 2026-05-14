import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_tag_write_execute"
COMMAND_LABEL = "shopify_review_request_trustpilot_tag_write_execute"

SOURCE_FINAL_PREFLIGHT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_final_preflight.json"
SOURCE_FINAL_PREFLIGHT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_final_preflight.html"
PROTECTED_DRAFT_SOURCE_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_locked_runner.json"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_execute.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_tag_write_execute.html"

DRY_RUN_STATUS = "dry_run_trustpilot_tag_write_not_executed"
FUTURE_SUCCESS_STATUS = "one_trustpilot_tag_written_and_needs_audit"
EXPECTED_PREFLIGHT_STATUS = "trustpilot_tag_write_final_preflight_passed"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
EXPECTED_TAG_VALUE = "1: trustpilot"
TAG_WRITE_ENV = "TRUSTPILOT_SHOPIFY_TAG_WRITE"
TAG_WRITE_MAX_ENV = "TRUSTPILOT_SHOPIFY_TAG_WRITE_MAX"
TAG_WRITE_ACK_ENV = "TRUSTPILOT_SHOPIFY_TAG_WRITE_ACK"
TAG_WRITE_ACK_VALUE = "YES_I_APPROVE_ADDING_ONE_TRUSTPILOT_TAG"
TAG_WRITE_TARGET_ORDER_ENV = "TRUSTPILOT_SHOPIFY_TAG_WRITE_TARGET_ORDER"
TAG_WRITE_VALUE_ENV = "TRUSTPILOT_SHOPIFY_TAG_VALUE"
DRY_RUN_ENV = "DRY_RUN"
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


def run_shopify_review_request_trustpilot_tag_write_execute_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    final_preflight, source_error = _read_source_preflight()
    source_privacy_scan = {
        "json": _privacy_scan_text(_read_text(SOURCE_FINAL_PREFLIGHT_JSON_PATH)),
        "html": _privacy_scan_text(_read_text(SOURCE_FINAL_PREFLIGHT_HTML_PATH)),
    }
    full_draft_id_leak = _full_draft_id_leak_detected(
        _read_text(SOURCE_FINAL_PREFLIGHT_JSON_PATH),
        _read_text(SOURCE_FINAL_PREFLIGHT_HTML_PATH),
    )
    gates = _gate_status(final_preflight)
    blocking_conditions = _blocking_conditions(
        final_preflight=final_preflight,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        gates=gates,
    )
    write_result = _write_result(gates, blocking_conditions)
    status = write_result["tag_write_execute_status"]
    payload = _build_payload(
        final_preflight=final_preflight,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_leak_detected=full_draft_id_leak,
        gates=gates,
        blocking_conditions=blocking_conditions,
        write_result=write_result,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_preflight() -> tuple[dict, str]:
    if not SOURCE_FINAL_PREFLIGHT_JSON_PATH.exists():
        return {}, "blocked_missing_final_preflight_report"
    try:
        return json.loads(SOURCE_FINAL_PREFLIGHT_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_missing_final_preflight_report: source JSON parse failed: {exc}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _gate_status(final_preflight: dict) -> dict:
    requested_tag_write_enabled = os.environ.get(TAG_WRITE_ENV, "").strip() == "1"
    requested_tag_write_max = os.environ.get(TAG_WRITE_MAX_ENV, "").strip()
    ack_raw = os.environ.get(TAG_WRITE_ACK_ENV, "").strip()
    dry_run_raw = os.environ.get(DRY_RUN_ENV, "").strip()
    requested_target_order = os.environ.get(TAG_WRITE_TARGET_ORDER_ENV, "").strip() or _safe_text(
        final_preflight.get("selected_order_name", EXPECTED_ORDER_NAME)
    )
    requested_tag_value = os.environ.get(TAG_WRITE_VALUE_ENV, "").strip() or _safe_text(
        final_preflight.get("planned_shopify_tag", EXPECTED_TAG_VALUE)
    )
    dry_run = dry_run_raw != "0"
    ack_present = bool(ack_raw)
    ack_valid = ack_raw == TAG_WRITE_ACK_VALUE
    target_order_matches = requested_target_order == EXPECTED_ORDER_NAME
    tag_value_matches = requested_tag_value == EXPECTED_TAG_VALUE
    return {
        "requested_tag_write_enabled": requested_tag_write_enabled,
        "requested_tag_write_max": requested_tag_write_max,
        "tag_write_max_is_one": requested_tag_write_max == "1",
        "ack_present": ack_present,
        "ack_valid": ack_valid,
        "dry_run_raw": dry_run_raw or "1",
        "dry_run": dry_run,
        "requested_target_order": requested_target_order,
        "target_order_matches": target_order_matches,
        "requested_tag_value": requested_tag_value,
        "tag_value_matches": tag_value_matches,
        "all_real_run_gates_valid": (
            requested_tag_write_enabled
            and requested_tag_write_max == "1"
            and ack_valid
            and not dry_run
            and target_order_matches
            and tag_value_matches
        ),
    }


def _blocking_conditions(
    final_preflight: dict,
    source_error: str,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    gates: dict,
) -> list[dict]:
    conditions = []
    if source_error:
        return [{"status": "blocked_missing_final_preflight_report", "detail": _sanitize_text(source_error)}]
    if (
        final_preflight.get("tag_write_final_preflight_status") != EXPECTED_PREFLIGHT_STATUS
        or final_preflight.get("success") is not True
    ):
        conditions.append({"status": "blocked_final_preflight_not_passed", "detail": "Phase 3.20 final preflight did not pass."})
    if _safe_text(final_preflight.get("selected_order_name", "")) != EXPECTED_ORDER_NAME:
        conditions.append({"status": "blocked_target_order_mismatch", "detail": "selected_order_name must equal #22621."})
    masked_email = _safe_text(final_preflight.get("selected_masked_email", ""))
    if masked_email != EXPECTED_MASKED_EMAIL or not _is_masked_email(masked_email):
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "selected_masked_email mismatch or unmasked."})
    if _safe_text(final_preflight.get("source_gmail_draft_id_partial", "")) != EXPECTED_DRAFT_ID_PARTIAL:
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "Gmail draft id partial mismatch."})
    if _safe_text(final_preflight.get("planned_shopify_tag", "")) != EXPECTED_TAG_VALUE:
        conditions.append({"status": "blocked_tag_value_mismatch", "detail": "planned Shopify tag must exactly equal 1: trustpilot."})
    if int(final_preflight.get("source_sent_count") or 0) != 1:
        conditions.append({"status": "blocked_unexpected_sent_count", "detail": "source_sent_count must equal 1."})
    if int(final_preflight.get("blocking_condition_count") or 0) != 0:
        conditions.append({"status": "blocked_final_preflight_has_blocking_conditions", "detail": "Phase 3.20 blocking_condition_count must equal 0."})
    if final_preflight.get("tag_write_preflight_ready_for_manual_real_write_approval") is not True:
        conditions.append({"status": "blocked_final_preflight_not_ready_for_manual_approval", "detail": "final preflight is not ready for manual real-write approval."})
    if final_preflight.get("real_tag_write_allowed_now") is not False:
        conditions.append({"status": "blocked_unexpected_real_tag_write_allowed_now", "detail": "Phase 3.20 must not have allowed real tag write."})
    if _any_preflight_write_or_send_flag_true(final_preflight):
        conditions.append({"status": "blocked_unexpected_send_or_write_flag", "detail": "Phase 3.20 source report has an unsafe write/send flag."})
    if _privacy_scan_failed(source_privacy_scan) or full_draft_id_leak_detected:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source final preflight privacy scan failed."})

    if gates["requested_tag_write_max"] and not gates["tag_write_max_is_one"]:
        conditions.append({"status": "blocked_tag_write_max_not_one", "detail": "TRUSTPILOT_SHOPIFY_TAG_WRITE_MAX must be 1."})
    if gates["ack_present"] and not gates["ack_valid"]:
        conditions.append({"status": "blocked_invalid_tag_write_ack", "detail": "TRUSTPILOT_SHOPIFY_TAG_WRITE_ACK is invalid."})
    if not gates["target_order_matches"]:
        conditions.append({"status": "blocked_target_order_mismatch", "detail": "requested target order must be #22621."})
    if not gates["tag_value_matches"]:
        conditions.append({"status": "blocked_tag_value_mismatch", "detail": "requested tag value must exactly equal 1: trustpilot."})
    if not gates["dry_run"]:
        if not gates["requested_tag_write_enabled"]:
            conditions.append({"status": "blocked_missing_tag_write_enabled", "detail": "TRUSTPILOT_SHOPIFY_TAG_WRITE is not 1."})
        if not gates["requested_tag_write_max"]:
            conditions.append({"status": "blocked_tag_write_max_not_one", "detail": "TRUSTPILOT_SHOPIFY_TAG_WRITE_MAX is missing."})
        if not gates["ack_present"]:
            conditions.append({"status": "blocked_missing_tag_write_ack", "detail": "TRUSTPILOT_SHOPIFY_TAG_WRITE_ACK is missing."})
        if gates["all_real_run_gates_valid"]:
            conditions.append(
                {
                    "status": "blocked_real_tag_write_not_enabled_in_phase_3_21",
                    "detail": "Phase 3.21 validates the executor shell only and does not execute Shopify tagsAdd.",
                }
            )
    return conditions


def _any_preflight_write_or_send_flag_true(report: dict) -> bool:
    unsafe_flags = [
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "tags_add_performed",
        "tags_remove_performed",
        "tagsAdd_performed",
        "tagsRemove_performed",
        "gmail_api_call_performed",
        "gmail_drafts_send_called",
        "gmail_messages_send_called",
        "email_sent",
        "kudosi_api_call_performed",
        "ali_reviews_api_call_performed",
    ]
    return any(report.get(flag) is True for flag in unsafe_flags)


def _write_result(gates: dict, blocking_conditions: list[dict]) -> dict:
    return {
        "tag_write_execute_status": DRY_RUN_STATUS if not blocking_conditions else blocking_conditions[0]["status"],
        "mode": "dry-run" if gates["dry_run"] else "real-run-locked",
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
        "tag_write_attempted": False,
        "tag_write_performed": False,
        "written_tag_count": 0,
    }


def _build_payload(
    final_preflight: dict,
    source_error: str,
    source_privacy_scan: dict,
    full_draft_id_leak_detected: bool,
    gates: dict,
    blocking_conditions: list[dict],
    write_result: dict,
    status: str,
    duration_seconds: float,
) -> dict:
    dry_run_success = status == DRY_RUN_STATUS
    safety = _safety_summary(write_result)
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.21",
        "mode": write_result["mode"],
        "command_label": COMMAND_LABEL,
        "tag_write_execute_status": status,
        "success": dry_run_success,
        "source_report_used": {
            "json_path": str(SOURCE_FINAL_PREFLIGHT_JSON_PATH),
            "html_path": str(SOURCE_FINAL_PREFLIGHT_HTML_PATH),
            "json_exists": SOURCE_FINAL_PREFLIGHT_JSON_PATH.exists(),
            "html_exists": SOURCE_FINAL_PREFLIGHT_HTML_PATH.exists(),
            "source_error_sanitized": _sanitize_text(source_error),
        },
        "source_final_preflight_status": _safe_text(final_preflight.get("tag_write_final_preflight_status", "")),
        "selected_order_name": _safe_text(final_preflight.get("selected_order_name", EXPECTED_ORDER_NAME)),
        "selected_masked_email": _safe_text(final_preflight.get("selected_masked_email", EXPECTED_MASKED_EMAIL)),
        "source_gmail_draft_id_partial": _safe_text(final_preflight.get("source_gmail_draft_id_partial", EXPECTED_DRAFT_ID_PARTIAL)),
        "planned_shopify_tag": _safe_text(final_preflight.get("planned_shopify_tag", EXPECTED_TAG_VALUE)),
        "source_sent_count": int(final_preflight.get("source_sent_count") or 0),
        "source_blocking_condition_count": int(final_preflight.get("blocking_condition_count") or 0),
        "source_ready_for_manual_real_write_approval": (
            final_preflight.get("tag_write_preflight_ready_for_manual_real_write_approval") is True
        ),
        "source_real_tag_write_allowed_now": final_preflight.get("real_tag_write_allowed_now") is True,
        "requested_tag_write_enabled": gates["requested_tag_write_enabled"],
        "requested_tag_write_max": gates["requested_tag_write_max"],
        "ack_valid": gates["ack_valid"],
        "ack_present": gates["ack_present"],
        "dry_run": gates["dry_run"],
        "real_tag_write_allowed": False,
        "requested_target_order": gates["requested_target_order"],
        "target_order_matches": gates["target_order_matches"],
        "requested_tag_value": gates["requested_tag_value"],
        "tag_value_matches": gates["tag_value_matches"],
        "would_execute_tags_add": not blocking_conditions or (
            len(blocking_conditions) == 1
            and blocking_conditions[0]["status"] == "blocked_real_tag_write_not_enabled_in_phase_3_21"
        ),
        "would_add_tag_value": EXPECTED_TAG_VALUE,
        "future_real_write_status_on_success": FUTURE_SUCCESS_STATUS,
        "future_real_write_requires_manual_approval": True,
        "future_tag_write_audit_required": True,
        "future_real_write_design": {
            "allowed_shopify_action": "tagsAdd",
            "forbidden_shopify_action": "tagsRemove",
            "exactly_one_target": EXPECTED_ORDER_NAME,
            "exactly_one_tag": EXPECTED_TAG_VALUE,
            "gmail_api_allowed": False,
            "gmail_send_allowed": False,
            "kudosi_ali_reviews_allowed": False,
            "post_write_audit_required_phase": "3.22",
            "on_write_failure": "Do not resend email; output manual recovery package.",
        },
        "source_privacy_scan": source_privacy_scan,
        "source_full_draft_id_leak_detected": full_draft_id_leak_detected,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "safety_summary": safety,
        **safety,
        **write_result,
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_tag_write_execute_path": str(REPORT_JSON_PATH),
        "html_trustpilot_tag_write_execute_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary(write_result: dict) -> dict:
    return {
        "shopify_api_call_performed": bool(write_result["shopify_api_call_performed"]),
        "shopify_write_performed": bool(write_result["shopify_write_performed"]),
        "mutation_performed": bool(write_result["mutation_performed"]),
        "tags_add_performed": bool(write_result["tags_add_performed"]),
        "tags_remove_performed": bool(write_result["tags_remove_performed"]),
        "tagsAdd_performed": bool(write_result["tagsAdd_performed"]),
        "tagsRemove_performed": bool(write_result["tagsRemove_performed"]),
        "gmail_api_call_performed": bool(write_result["gmail_api_call_performed"]),
        "gmail_drafts_send_called": bool(write_result["gmail_drafts_send_called"]),
        "gmail_messages_send_called": bool(write_result["gmail_messages_send_called"]),
        "email_sent": bool(write_result["email_sent"]),
        "kudosi_api_call_performed": bool(write_result["kudosi_api_call_performed"]),
        "ali_reviews_api_call_performed": bool(write_result["ali_reviews_api_call_performed"]),
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_tag_write_execute_path": str(json_path),
        "html_trustpilot_tag_write_execute_path": str(html_path),
        "tag_write_execute_status": payload["tag_write_execute_status"],
        "source_final_preflight_status": payload["source_final_preflight_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "planned_shopify_tag": payload["planned_shopify_tag"],
        "source_sent_count": payload["source_sent_count"],
        "requested_tag_write_enabled": payload["requested_tag_write_enabled"],
        "requested_tag_write_max": payload["requested_tag_write_max"],
        "ack_valid": payload["ack_valid"],
        "dry_run": payload["dry_run"],
        "real_tag_write_allowed": payload["real_tag_write_allowed"],
        "would_execute_tags_add": payload["would_execute_tags_add"],
        "would_add_tag_value": payload["would_add_tag_value"],
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
    future_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["future_real_write_design"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Tag Write Execute Locked Shell</title>
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
  <h1>Trustpilot Tag Write Execute Locked Shell</h1>
  <p class="warning">Phase 3.21 is a locked executor shell. No Shopify API call, mutation, tagsAdd, tagsRemove, or Gmail send was performed.</p>
  <p>Status: <strong>{escape(payload["tag_write_execute_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Planned Shopify tag: <code>{escape(payload["planned_shopify_tag"])}</code></p>
  <p>Dry-run: <strong>{escape(str(payload["dry_run"]))}</strong></p>
  <p>Real tag write allowed now: <strong>{escape(str(payload["real_tag_write_allowed"]))}</strong></p>
  <p>Would execute tagsAdd: <strong>{escape(str(payload["would_execute_tags_add"]))}</strong></p>
  <h2>Future Real-Write Design</h2>
  <table><tbody>{future_rows}</tbody></table>
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
        payload["tag_write_execute_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["real_tag_write_allowed"] = False
        payload["would_execute_tags_add"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "tag-write execute self privacy scan failed."}
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
    if status == DRY_RUN_STATUS:
        return "Trustpilot Shopify tag-write executor stayed dry-run; no Shopify tag was written."
    return "Trustpilot Shopify tag-write executor blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.21 Trustpilot tag-write execute locked shell finished.\n"
        f"Status: {payload.get('tag_write_execute_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Planned tag: {payload.get('planned_shopify_tag')}\n"
        f"Dry-run: {payload.get('dry_run')}\n"
        f"Would execute tagsAdd: {payload.get('would_execute_tags_add')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Shopify API/write/mutation/tagsAdd/tagsRemove, no Gmail send, no Kudosi/Ali Reviews call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
