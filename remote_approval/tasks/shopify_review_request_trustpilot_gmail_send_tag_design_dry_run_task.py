import json
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run"

SOURCE_AUDIT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_first_draft_audit.json"
SOURCE_AUDIT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_first_draft_audit.html"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run.html"

READY_STATUS = "trustpilot_gmail_send_tag_design_dry_run_ready"
TRUSTPILOT_TAG = "1: trustpilot"
TRUSTPILOT_TAG_ALIASES = ["1: trustpilot", "1: trustpoilt"]
EXPECTED_AUDIT_STATUS = "first_trustpilot_gmail_draft_audit_passed"
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


def run_shopify_review_request_trustpilot_gmail_send_tag_design_dry_run_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_audit, source_error = _read_source_audit()
    source_privacy_scan = {
        "json": _privacy_scan_text(_read_text(SOURCE_AUDIT_JSON_PATH)),
        "html": _privacy_scan_text(_read_text(SOURCE_AUDIT_HTML_PATH)),
    }
    blocking_conditions = _blocking_conditions(source_audit, source_error, source_privacy_scan)
    status = blocking_conditions[0]["status"] if blocking_conditions else READY_STATUS
    payload = _build_payload(
        source_audit=source_audit,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        blocking_conditions=blocking_conditions,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_audit() -> tuple[dict, str]:
    if not SOURCE_AUDIT_JSON_PATH.exists():
        return {}, "blocked_missing_first_draft_audit"
    try:
        return json.loads(SOURCE_AUDIT_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_missing_first_draft_audit: source JSON parse failed: {exc}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _blocking_conditions(source_audit: dict, source_error: str, source_privacy_scan: dict) -> list[dict]:
    conditions = []
    if source_error:
        return [{"status": "blocked_missing_first_draft_audit", "detail": _sanitize_text(source_error)}]

    if source_audit.get("first_draft_audit_status") != EXPECTED_AUDIT_STATUS or source_audit.get("success") is not True:
        conditions.append({"status": "blocked_first_draft_audit_not_passed", "detail": "Phase 3.12 audit did not pass"})
    if source_audit.get("source_gmail_draft_created") is not True:
        conditions.append({"status": "blocked_source_draft_not_created", "detail": "source audit does not confirm draft created"})
    if int(source_audit.get("source_gmail_drafts_created_count") or 0) != 1:
        conditions.append(
            {
                "status": "blocked_unexpected_source_draft_count",
                "detail": f"source_gmail_drafts_created_count={int(source_audit.get('source_gmail_drafts_created_count') or 0)}",
            }
        )
    if not _is_masked_email(source_audit.get("selected_masked_email", "")):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected_masked_email is missing or not masked"})
    if source_audit.get("source_gmail_draft_id_present") is not True or not source_audit.get("source_gmail_draft_id_partial"):
        conditions.append({"status": "blocked_source_draft_not_created", "detail": "source draft id partial is missing"})
    if _full_draft_id_leak_risk(_read_text(SOURCE_AUDIT_JSON_PATH)) or _full_draft_id_leak_risk(_read_text(SOURCE_AUDIT_HTML_PATH)):
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "source audit appears to contain a full draft id field"})
    if source_audit.get("raw_email_leak_risk_detected") is True:
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source audit reported raw email leak risk"})
    if _privacy_scan_failed(source_privacy_scan):
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source audit JSON/HTML privacy scan failed"})

    source_flags = source_audit.get("source_no_send_no_write_flags") if isinstance(source_audit.get("source_no_send_no_write_flags"), dict) else {}
    if any(source_flags.get(flag) is True for flag in ("gmail_drafts_send_called", "gmail_messages_send_called", "gmail_send_performed", "email_sent")):
        conditions.append({"status": "blocked_unexpected_send_or_write_flag", "detail": "source send flag was true"})
    if any(source_flags.get(flag) is True for flag in ("shopify_write_performed", "mutation_performed", "tags_add_performed", "tags_remove_performed")):
        conditions.append({"status": "blocked_unexpected_send_or_write_flag", "detail": "source Shopify write flag was true"})
    if source_flags.get("kudosi_api_call_performed") is True:
        conditions.append({"status": "blocked_unexpected_send_or_write_flag", "detail": "source Kudosi flag was true"})
    if source_audit.get("blocking_condition_count") not in (0, None):
        conditions.append({"status": "blocked_first_draft_audit_not_passed", "detail": "source audit contains blocking conditions"})
    return conditions


def _build_payload(
    source_audit: dict,
    source_error: str,
    source_privacy_scan: dict,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.13",
        "mode": "trustpilot-gmail-send-tag-design-dry-run",
        "command_label": COMMAND_LABEL,
        "send_tag_design_status": status,
        "success": status == READY_STATUS,
        "source_audit_status": _safe_text(source_audit.get("first_draft_audit_status", "")),
        "source_report_used": {
            "json_path": str(SOURCE_AUDIT_JSON_PATH),
            "html_path": str(SOURCE_AUDIT_HTML_PATH),
            "json_exists": SOURCE_AUDIT_JSON_PATH.exists(),
            "html_exists": SOURCE_AUDIT_HTML_PATH.exists(),
            "source_error_sanitized": _sanitize_text(source_error),
        },
        "selected_order_name": _safe_text(source_audit.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_audit.get("selected_masked_email", "")),
        "source_gmail_draft_id_partial": _safe_text(source_audit.get("source_gmail_draft_id_partial", "")),
        "source_gmail_drafts_created_count": int(source_audit.get("source_gmail_drafts_created_count") or 0),
        "successful_fallback_query_label": _safe_text(source_audit.get("successful_fallback_query_label", "")),
        "planned_send_action": "Gmail draft send, dry-run only",
        "planned_shopify_tag_action": f'add tag "{TRUSTPILOT_TAG}", dry-run only',
        "planned_trustpilot_tag": TRUSTPILOT_TAG,
        "trustpilot_tag_aliases": TRUSTPILOT_TAG_ALIASES,
        "duplicate_trustpilot_tag_rule": (
            "Future real send/tag phase must block if order/customer already has 1: trustpilot or 1: trustpoilt."
        ),
        "duplicate_email_send_rule": (
            "Future real send phase must block if the order is already Trustpilot invited, draft sent, or tagged."
        ),
        "future_real_send_hard_gates": {
            "TRUSTPILOT_GMAIL_SEND_DRAFT": "1",
            "TRUSTPILOT_GMAIL_SEND_DRAFT_MAX": "1",
            "TRUSTPILOT_GMAIL_SEND_DRAFT_ACK": "YES_I_APPROVE_SENDING_ONE_TRUSTPILOT_GMAIL_DRAFT",
        },
        "future_real_tag_write_hard_gates": {
            "TRUSTPILOT_SHOPIFY_TAG_WRITE": "1",
            "TRUSTPILOT_SHOPIFY_TAG_WRITE_MAX": "1",
            "TRUSTPILOT_SHOPIFY_TAG_WRITE_ACK": "YES_I_APPROVE_ADDING_ONE_TRUSTPILOT_TAG",
        },
        "forced_execution_order": [
            "send Gmail draft successfully",
            "readback / confirmation",
            "then write Shopify tag",
            "tag write readback",
        ],
        "failure_recovery_rules": {
            "send_success_tag_write_failed": "Do not resend email; output a manual recovery package.",
            "send_failed": "Do not write Shopify tag.",
            "trustpilot_tag_already_exists": "Do not send email and do not write tag.",
        },
        "source_privacy_scan": source_privacy_scan,
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_gmail_send_tag_design_dry_run_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_send_tag_design_dry_run_path": str(REPORT_HTML_PATH),
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
        "gmail_draft_send_attempted": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "gmail_send_performed": False,
        "email_sent": False,
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
        "no_new_external_api_calls_performed": True,
        "no_new_send_or_write_performed": True,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload["success"],
        "exit_code": 0 if payload["success"] else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_trustpilot_gmail_send_tag_design_dry_run_path": str(json_path),
        "html_trustpilot_gmail_send_tag_design_dry_run_path": str(html_path),
        "send_tag_design_status": payload["send_tag_design_status"],
        "blocking_condition_count": payload["blocking_condition_count"],
        "blocking_conditions": payload["blocking_conditions"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "planned_send_action": payload["planned_send_action"],
        "planned_shopify_tag_action": payload["planned_shopify_tag_action"],
        "successful_fallback_query_label": payload["successful_fallback_query_label"],
        "source_json_raw_customer_email_count": payload["source_privacy_scan"]["json"]["raw_customer_email_count"],
        "source_html_raw_customer_email_count": payload["source_privacy_scan"]["html"]["raw_customer_email_count"],
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
    gates_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td><code>{escape(value)}</code></td></tr>"
        for key, value in payload["future_real_send_hard_gates"].items()
    )
    tag_gates_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td><code>{escape(value)}</code></td></tr>"
        for key, value in payload["future_real_tag_write_hard_gates"].items()
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Send / Tag Design Dry Run</title>
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
  <h1>Trustpilot Gmail Send / Tag Design Dry Run</h1>
  <p class="warning">Phase 3.13 is design-only. No Gmail send, Shopify write, tag mutation, or Kudosi call was performed.</p>
  <p>Status: <strong>{escape(payload["send_tag_design_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Planned send action: <strong>{escape(payload["planned_send_action"])}</strong></p>
  <p>Planned Shopify tag action: <strong>{escape(payload["planned_shopify_tag_action"])}</strong></p>
  <h2>Future Send Gates</h2>
  <table><tbody>{gates_rows}</tbody></table>
  <h2>Future Tag Write Gates</h2>
  <table><tbody>{tag_gates_rows}</tbody></table>
  <h2>Forced Order</h2>
  <ol>{''.join(f'<li>{escape(item)}</li>' for item in payload["forced_execution_order"])}</ol>
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
    if re.search(r'"gmail_draft_id"\s*:', text or ""):
        return True
    return False


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["send_tag_design_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "design report self privacy scan failed"}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
        payload["detected_issue_summary"] = _issue_summary(payload["send_tag_design_status"], payload["blocking_conditions"])
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
        return "Trustpilot Gmail send/tag design dry run is ready; this task performed no send, write, or external API call."
    return "Trustpilot Gmail send/tag design dry run blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.13 Trustpilot Gmail send/tag design dry run finished.\n"
        f"Status: {payload.get('send_tag_design_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Planned send action: {payload.get('planned_send_action')}\n"
        f"Planned tag action: {payload.get('planned_shopify_tag_action')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail API call, no Shopify API call, no Kudosi API call, no send, and no tag write.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
