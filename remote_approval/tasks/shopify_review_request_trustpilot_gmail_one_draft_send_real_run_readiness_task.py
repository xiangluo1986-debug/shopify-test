import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness"

SOURCE_EXECUTOR_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.json"
SOURCE_EXECUTOR_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_execute.html"
SOURCE_PREFLIGHT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight.json"
SOURCE_PREFLIGHT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_final_preflight.html"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness.html"

READY_STATUS = "trustpilot_gmail_one_draft_real_send_ready_for_manual_execution"
EXPECTED_PREFLIGHT_STATUS = "trustpilot_gmail_one_draft_send_final_preflight_ready"
EXPECTED_EXECUTOR_DRY_RUN_STATUS = "dry_run_real_send_not_executed"
EXPECTED_ORDER_NAME = "#22621"
EXPECTED_MASKED_EMAIL = "m***@gmail.com"
EXPECTED_DRAFT_ID_PARTIAL = "r-22...3521"
GMAIL_SEND_ACK_VALUE = "YES_I_APPROVE_SENDING_ONE_TRUSTPILOT_GMAIL_DRAFT"
ALLOWED_REPORT_EMAILS = {"info@kidstoylover.com"}
EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
FULL_DRAFT_ID_RE = re.compile(r"\br-[A-Za-z0-9_-]{10,}\b")
SECRET_VALUE_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._-]{8,}"),
    re.compile(r"ya29\.[A-Za-z0-9._-]+"),
    re.compile(r"shpat_[A-Za-z0-9_]+"),
    re.compile(r"(?i)access[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._-]{12,}"),
    re.compile(r"(?i)refresh[_\s-]?token\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)client[_\s-]?secret\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
    re.compile(r"(?i)authorization\s*[:=]\s*[\"']?[A-Za-z0-9._/-]{12,}"),
]


def run_shopify_review_request_trustpilot_gmail_one_draft_send_real_run_readiness_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    executor_report, executor_error = _read_json_report(
        SOURCE_EXECUTOR_JSON_PATH, "blocked_missing_executor_dry_run_report"
    )
    preflight_report, preflight_error = _read_json_report(
        SOURCE_PREFLIGHT_JSON_PATH, "blocked_missing_final_preflight_report"
    )
    source_privacy_scan = {
        "executor_json": _privacy_scan_text(_read_text(SOURCE_EXECUTOR_JSON_PATH)),
        "executor_html": _privacy_scan_text(_read_text(SOURCE_EXECUTOR_HTML_PATH)),
        "preflight_json": _privacy_scan_text(_read_text(SOURCE_PREFLIGHT_JSON_PATH)),
        "preflight_html": _privacy_scan_text(_read_text(SOURCE_PREFLIGHT_HTML_PATH)),
    }
    full_draft_id_scan = {
        "executor_json": _full_draft_id_leak_risk(_read_text(SOURCE_EXECUTOR_JSON_PATH)),
        "executor_html": _full_draft_id_leak_risk(_read_text(SOURCE_EXECUTOR_HTML_PATH)),
        "preflight_json": _full_draft_id_leak_risk(_read_text(SOURCE_PREFLIGHT_JSON_PATH)),
        "preflight_html": _full_draft_id_leak_risk(_read_text(SOURCE_PREFLIGHT_HTML_PATH)),
    }
    blocking_conditions = _blocking_conditions(
        executor_report=executor_report,
        executor_error=executor_error,
        preflight_report=preflight_report,
        preflight_error=preflight_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_scan=full_draft_id_scan,
    )
    status = blocking_conditions[0]["status"] if blocking_conditions else READY_STATUS
    payload = _build_payload(
        executor_report=executor_report,
        executor_error=executor_error,
        preflight_report=preflight_report,
        preflight_error=preflight_error,
        source_privacy_scan=source_privacy_scan,
        full_draft_id_scan=full_draft_id_scan,
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
    executor_report: dict,
    executor_error: str,
    preflight_report: dict,
    preflight_error: str,
    source_privacy_scan: dict,
    full_draft_id_scan: dict,
) -> list[dict]:
    conditions = []
    if preflight_error:
        conditions.append({"status": "blocked_missing_final_preflight_report", "detail": _sanitize_text(preflight_error)})
    if executor_error:
        conditions.append({"status": "blocked_missing_executor_dry_run_report", "detail": _sanitize_text(executor_error)})
    if conditions:
        return conditions

    if preflight_report.get("final_preflight_status") != EXPECTED_PREFLIGHT_STATUS:
        conditions.append({"status": "blocked_final_preflight_not_ready", "detail": "Phase 3.15 final preflight is not ready."})
    if preflight_report.get("ready_for_manual_real_send_approval") is not True:
        conditions.append({"status": "blocked_final_preflight_not_ready", "detail": "ready_for_manual_real_send_approval is not true."})
    if executor_report.get("one_draft_send_execute_status") != EXPECTED_EXECUTOR_DRY_RUN_STATUS:
        conditions.append({"status": "blocked_executor_dry_run_not_ready", "detail": "Phase 3.16 executor report is not a clean dry-run."})
    if executor_report.get("success") is not True:
        conditions.append({"status": "blocked_executor_dry_run_not_ready", "detail": "Phase 3.16 executor success was not true."})

    _check_identity_consistency(executor_report, preflight_report, conditions)
    _check_no_send_or_write_flags(executor_report, "executor", conditions)
    _check_no_send_or_write_flags(preflight_report, "preflight", conditions)

    if executor_report.get("gmail_api_call_performed") is True:
        conditions.append({"status": "blocked_gmail_send_flag_detected", "detail": "executor gmail_api_call_performed was true."})
    if executor_report.get("sent_count") not in (0, None):
        conditions.append({"status": "blocked_email_already_sent", "detail": "executor sent_count was not zero."})
    if executor_report.get("blocking_condition_count") not in (0, None):
        conditions.append({"status": "blocked_executor_dry_run_not_ready", "detail": "executor report has blocking conditions."})

    if _privacy_scan_failed(source_privacy_scan):
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source JSON/HTML privacy scan failed."})
    if any(full_draft_id_scan.values()):
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "source JSON/HTML appears to include a full Gmail draft id."})
    if not _is_masked_email(executor_report.get("selected_masked_email", "")):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "executor selected_masked_email is missing or not masked."})
    if not _is_masked_email(preflight_report.get("selected_masked_email", "")):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "preflight selected_masked_email is missing or not masked."})
    return conditions


def _check_identity_consistency(executor_report: dict, preflight_report: dict, conditions: list[dict]) -> None:
    checks = [
        ("selected_order_name", EXPECTED_ORDER_NAME),
        ("selected_masked_email", EXPECTED_MASKED_EMAIL),
        ("source_gmail_draft_id_partial", EXPECTED_DRAFT_ID_PARTIAL),
    ]
    for field, expected in checks:
        executor_value = _safe_text(executor_report.get(field, ""))
        preflight_value = _safe_text(preflight_report.get(field, ""))
        if executor_value != expected or preflight_value != expected:
            conditions.append(
                {
                    "status": "blocked_executor_dry_run_not_ready",
                    "detail": f"{field} mismatch between expected, executor, and final preflight reports.",
                }
            )


def _check_no_send_or_write_flags(report: dict, label: str, conditions: list[dict]) -> None:
    if any(report.get(flag) is True for flag in ("gmail_drafts_send_called", "gmail_messages_send_called", "gmail_send_performed", "email_sent")):
        conditions.append({"status": "blocked_gmail_send_flag_detected", "detail": f"{label} send flag was true."})
    if any(report.get(flag) is True for flag in ("shopify_write_performed", "mutation_performed")):
        conditions.append({"status": "blocked_shopify_write_flag_detected", "detail": f"{label} Shopify write flag was true."})
    if any(report.get(flag) is True for flag in ("tags_add_performed", "tags_remove_performed", "tagsAdd_performed", "tagsRemove_performed")):
        conditions.append({"status": "blocked_tag_write_flag_detected", "detail": f"{label} tag write flag was true."})
    if any(report.get(flag) is True for flag in ("kudosi_api_call_performed", "ali_reviews_api_call_performed")):
        conditions.append({"status": "blocked_kudosi_flag_detected", "detail": f"{label} Kudosi/Ali Reviews flag was true."})


def _build_payload(
    executor_report: dict,
    executor_error: str,
    preflight_report: dict,
    preflight_error: str,
    source_privacy_scan: dict,
    full_draft_id_scan: dict,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.16B",
        "mode": "read-report-only-real-run-readiness",
        "command_label": COMMAND_LABEL,
        "real_run_readiness_status": status,
        "success": status == READY_STATUS,
        "selected_order_name": _safe_text(executor_report.get("selected_order_name") or preflight_report.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(executor_report.get("selected_masked_email") or preflight_report.get("selected_masked_email", "")),
        "source_gmail_draft_id_partial": _safe_text(executor_report.get("source_gmail_draft_id_partial") or preflight_report.get("source_gmail_draft_id_partial", "")),
        "executor_dry_run_status": _safe_text(executor_report.get("one_draft_send_execute_status", "")),
        "final_preflight_status": _safe_text(preflight_report.get("final_preflight_status", "")),
        "ready_for_manual_real_send_approval": preflight_report.get("ready_for_manual_real_send_approval") is True,
        "real_send_not_yet_executed": executor_report.get("email_sent") is not True and int(executor_report.get("sent_count") or 0) == 0,
        "future_real_send_allowed_only_with_manual_env_gates": True,
        "required_real_run_env": {
            "TRUSTPILOT_GMAIL_SEND_DRAFT": "1",
            "TRUSTPILOT_GMAIL_SEND_DRAFT_MAX": "1",
            "TRUSTPILOT_GMAIL_SEND_DRAFT_ACK": GMAIL_SEND_ACK_VALUE,
            "DRY_RUN": "0",
        },
        "forbidden_in_real_send_phase": [
            "Shopify tag write",
            "Shopify mutation",
            "Kudosi/Ali Reviews API",
            "Gmail messages.send",
            "Gmail draft create",
            "sending more than one draft",
        ],
        "after_real_send_next_required_phase": "Phase 3.17 send audit",
        "shopify_tag_write_allowed_now": False,
        "source_reports_used": {
            "executor_json_path": str(SOURCE_EXECUTOR_JSON_PATH),
            "executor_html_path": str(SOURCE_EXECUTOR_HTML_PATH),
            "executor_json_exists": SOURCE_EXECUTOR_JSON_PATH.exists(),
            "executor_html_exists": SOURCE_EXECUTOR_HTML_PATH.exists(),
            "executor_error_sanitized": _sanitize_text(executor_error),
            "final_preflight_json_path": str(SOURCE_PREFLIGHT_JSON_PATH),
            "final_preflight_html_path": str(SOURCE_PREFLIGHT_HTML_PATH),
            "final_preflight_json_exists": SOURCE_PREFLIGHT_JSON_PATH.exists(),
            "final_preflight_html_exists": SOURCE_PREFLIGHT_HTML_PATH.exists(),
            "final_preflight_error_sanitized": _sanitize_text(preflight_error),
        },
        "source_privacy_scan": source_privacy_scan,
        "full_draft_id_scan": full_draft_id_scan,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "json_path": str(REPORT_JSON_PATH),
        "html_path": str(REPORT_HTML_PATH),
        "json_trustpilot_gmail_one_draft_send_real_run_readiness_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_one_draft_send_real_run_readiness_path": str(REPORT_HTML_PATH),
        "logs_committed": False,
        "safety_summary": safety,
        **safety,
        "detected_issue_summary": _issue_summary(status, blocking_conditions),
        "duration_seconds": duration_seconds,
    }
    return _apply_self_privacy_assertion(payload)


def _safety_summary() -> dict:
    return {
        "gmail_api_call_performed": False,
        "gmail_draft_create_attempted": False,
        "gmail_draft_created": False,
        "gmail_draft_send_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "sent_count": 0,
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
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_one_draft_send_real_run_readiness_path": str(json_path),
        "html_trustpilot_gmail_one_draft_send_real_run_readiness_path": str(html_path),
        "real_run_readiness_status": payload["real_run_readiness_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "executor_dry_run_status": payload["executor_dry_run_status"],
        "final_preflight_status": payload["final_preflight_status"],
        "ready_for_manual_real_send_approval": payload["ready_for_manual_real_send_approval"],
        "real_send_not_yet_executed": payload["real_send_not_yet_executed"],
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
    env_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td><code>{escape(str(value))}</code></td></tr>"
        for key, value in payload["required_real_run_env"].items()
    )
    forbidden_rows = "\n".join(f"<li>{escape(item)}</li>" for item in payload["forbidden_in_real_send_phase"])
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail One-Draft Real-Run Readiness</title>
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
  <h1>Trustpilot Gmail One-Draft Real-Run Readiness</h1>
  <p class="warning">Phase 3.16B is report-only. No Gmail API, Shopify API, tag write, Kudosi call, or email send was performed.</p>
  <p>Status: <strong>{escape(payload["real_run_readiness_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Executor dry-run status: <code>{escape(payload["executor_dry_run_status"])}</code></p>
  <p>Final preflight status: <code>{escape(payload["final_preflight_status"])}</code></p>
  <p>Ready for manual real-send approval: <strong>{escape(str(payload["ready_for_manual_real_send_approval"]))}</strong></p>
  <h2>Required Future Real-Run Env</h2>
  <table><tbody>{env_rows}</tbody></table>
  <h2>Forbidden In Real Send Phase</h2>
  <ul>{forbidden_rows}</ul>
  <h2>Blocking Conditions</h2>
  <table><thead><tr><th>Status</th><th>Detail</th></tr></thead><tbody>{blocking_rows}</tbody></table>
  <h2>Safety Flags</h2>
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


def _full_draft_id_leak_risk(text: str) -> bool:
    if not text:
        return False
    return any("..." not in match.group(0) for match in FULL_DRAFT_ID_RE.finditer(text))


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["real_run_readiness_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "readiness report self privacy scan failed."}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
        payload["detected_issue_summary"] = _issue_summary(payload["real_run_readiness_status"], payload["blocking_conditions"])
    return payload


def _is_masked_email(value) -> bool:
    text = str(value or "")
    return bool(text and "@" in text and "***" in text and not EMAIL_RE.fullmatch(text))


def _safe_masked_email(value) -> str:
    text = _sanitize_text(str(value or ""))
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


def _safe_text(value) -> str:
    return _sanitize_text(str(value or ""))


def _sanitize_text(text: str) -> str:
    redacted = str(text or "")
    for pattern in SECRET_VALUE_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return EMAIL_RE.sub(lambda match: _mask_email(match.group(0).lower()), redacted)


def _issue_summary(status: str, blocking_conditions: list[dict]) -> str:
    if status == READY_STATUS:
        return "One-draft real-send readiness is ready for manual execution approval; no send or write was performed."
    return "One-draft real-send readiness blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.16B Trustpilot Gmail one-draft real-run readiness finished.\n"
        f"Status: {payload.get('real_run_readiness_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Executor dry-run status: {payload.get('executor_dry_run_status')}\n"
        f"Final preflight status: {payload.get('final_preflight_status')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail API, no send, no Shopify tag write, no Kudosi call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
