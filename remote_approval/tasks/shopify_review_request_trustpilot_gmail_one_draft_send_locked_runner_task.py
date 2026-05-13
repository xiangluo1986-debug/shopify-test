import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner"
COMMAND_LABEL = "shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner"

SOURCE_DESIGN_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run.json"
SOURCE_DESIGN_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_send_tag_design_dry_run.html"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner.html"

DRY_RUN_STATUS = "dry_run_one_gmail_draft_not_sent"
READY_SOURCE_STATUS = "trustpilot_gmail_send_tag_design_dry_run_ready"
EXPECTED_SOURCE_AUDIT_STATUS = "first_trustpilot_gmail_draft_audit_passed"
SEND_DRAFT_ENV = "TRUSTPILOT_GMAIL_SEND_DRAFT"
SEND_DRAFT_MAX_ENV = "TRUSTPILOT_GMAIL_SEND_DRAFT_MAX"
SEND_DRAFT_ACK_ENV = "TRUSTPILOT_GMAIL_SEND_DRAFT_ACK"
SEND_DRAFT_ACK_VALUE = "YES_I_APPROVE_SENDING_ONE_TRUSTPILOT_GMAIL_DRAFT"
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


def run_shopify_review_request_trustpilot_gmail_one_draft_send_locked_runner_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    source_design, source_error = _read_source_design()
    source_privacy_scan = {
        "json": _privacy_scan_text(_read_text(SOURCE_DESIGN_JSON_PATH)),
        "html": _privacy_scan_text(_read_text(SOURCE_DESIGN_HTML_PATH)),
    }
    gates = _gate_status()
    blocking_conditions = _blocking_conditions(source_design, source_error, source_privacy_scan, gates)
    status = blocking_conditions[0]["status"] if blocking_conditions else DRY_RUN_STATUS
    payload = _build_payload(
        source_design=source_design,
        source_error=source_error,
        source_privacy_scan=source_privacy_scan,
        gates=gates,
        blocking_conditions=blocking_conditions,
        status=status,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _read_source_design() -> tuple[dict, str]:
    if not SOURCE_DESIGN_JSON_PATH.exists():
        return {}, "blocked_missing_send_tag_design_report"
    try:
        return json.loads(SOURCE_DESIGN_JSON_PATH.read_text(encoding="utf-8")), ""
    except json.JSONDecodeError as exc:
        return {}, _sanitize_text(f"blocked_missing_send_tag_design_report: source JSON parse failed: {exc}")


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _gate_status() -> dict:
    requested_send_enabled = os.environ.get(SEND_DRAFT_ENV, "").strip() == "1"
    requested_send_max = os.environ.get(SEND_DRAFT_MAX_ENV, "").strip()
    ack_raw = os.environ.get(SEND_DRAFT_ACK_ENV, "").strip()
    dry_run_raw = os.environ.get(DRY_RUN_ENV, "").strip()
    dry_run = dry_run_raw != "0"
    ack_present = bool(ack_raw)
    ack_valid = ack_raw == SEND_DRAFT_ACK_VALUE
    return {
        "requested_send_enabled": requested_send_enabled,
        "requested_send_max": requested_send_max,
        "send_max_is_one": requested_send_max == "1",
        "ack_present": ack_present,
        "ack_valid": ack_valid,
        "dry_run_raw": dry_run_raw or "1",
        "dry_run": dry_run,
        "real_send_allowed": False,
        "future_real_send_requires_manual_approval": True,
        "future_tag_write_requires_separate_phase": True,
        "gate_notes": _gate_notes(requested_send_enabled, requested_send_max, ack_present, ack_valid, dry_run),
    }


def _gate_notes(requested_send_enabled: bool, requested_send_max: str, ack_present: bool, ack_valid: bool, dry_run: bool) -> list[str]:
    notes = []
    if not requested_send_enabled:
        notes.append("TRUSTPILOT_GMAIL_SEND_DRAFT is not enabled; dry-run remains no-send.")
    if requested_send_max != "1":
        notes.append("TRUSTPILOT_GMAIL_SEND_DRAFT_MAX is not 1; future real send would block.")
    if not ack_present:
        notes.append("TRUSTPILOT_GMAIL_SEND_DRAFT_ACK is missing; future real send would block.")
    elif not ack_valid:
        notes.append("TRUSTPILOT_GMAIL_SEND_DRAFT_ACK is invalid; future real send would block.")
    if dry_run:
        notes.append("DRY_RUN is active; no Gmail send is allowed even if other gates are valid.")
    notes.append("Phase 3.14 does not implement real Gmail drafts.send.")
    return notes


def _blocking_conditions(source_design: dict, source_error: str, source_privacy_scan: dict, gates: dict) -> list[dict]:
    conditions = []
    if source_error:
        return [{"status": "blocked_missing_send_tag_design_report", "detail": _sanitize_text(source_error)}]
    if source_design.get("send_tag_design_status") != READY_SOURCE_STATUS or source_design.get("success") is not True:
        conditions.append({"status": "blocked_send_tag_design_not_ready", "detail": "Phase 3.13 design package is not ready"})
    if source_design.get("source_audit_status") != EXPECTED_SOURCE_AUDIT_STATUS:
        conditions.append({"status": "blocked_source_audit_not_passed", "detail": "source audit status is not passed"})
    if int(source_design.get("source_gmail_drafts_created_count") or 0) != 1:
        conditions.append(
            {
                "status": "blocked_unexpected_source_draft_count",
                "detail": f"source_gmail_drafts_created_count={int(source_design.get('source_gmail_drafts_created_count') or 0)}",
            }
        )
    if not _is_masked_email(source_design.get("selected_masked_email", "")):
        conditions.append({"status": "blocked_unmasked_email_detected", "detail": "selected_masked_email is missing or not masked"})
    if not source_design.get("source_gmail_draft_id_partial"):
        conditions.append({"status": "blocked_source_draft_not_created", "detail": "source draft id partial is missing"})
    if _full_draft_id_leak_risk(_read_text(SOURCE_DESIGN_JSON_PATH)) or _full_draft_id_leak_risk(_read_text(SOURCE_DESIGN_HTML_PATH)):
        conditions.append({"status": "blocked_full_draft_id_leak_risk", "detail": "source design report appears to contain a full draft id field"})
    if _privacy_scan_failed(source_privacy_scan):
        conditions.append({"status": "blocked_privacy_scan_failed", "detail": "source design JSON/HTML privacy scan failed"})
    if any(source_design.get(flag) is True for flag in _send_write_flag_names()):
        conditions.append({"status": "blocked_unexpected_send_or_write_flag", "detail": "source design send/write flag was true"})
    if source_design.get("blocking_condition_count") not in (0, None):
        conditions.append({"status": "blocked_send_tag_design_not_ready", "detail": "source design has blocking conditions"})
    return conditions


def _build_payload(
    source_design: dict,
    source_error: str,
    source_privacy_scan: dict,
    gates: dict,
    blocking_conditions: list[dict],
    status: str,
    duration_seconds: float,
) -> dict:
    safety = _safety_summary()
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "3.14",
        "mode": "trustpilot-gmail-one-draft-send-locked-runner-dry-run",
        "command_label": COMMAND_LABEL,
        "one_draft_send_status": status,
        "success": status == DRY_RUN_STATUS,
        "source_design_status": _safe_text(source_design.get("send_tag_design_status", "")),
        "source_audit_status": _safe_text(source_design.get("source_audit_status", "")),
        "source_report_used": {
            "json_path": str(SOURCE_DESIGN_JSON_PATH),
            "html_path": str(SOURCE_DESIGN_HTML_PATH),
            "json_exists": SOURCE_DESIGN_JSON_PATH.exists(),
            "html_exists": SOURCE_DESIGN_HTML_PATH.exists(),
            "source_error_sanitized": _sanitize_text(source_error),
        },
        "selected_order_name": _safe_text(source_design.get("selected_order_name", "")),
        "selected_masked_email": _safe_masked_email(source_design.get("selected_masked_email", "")),
        "source_gmail_draft_id_partial": _safe_text(source_design.get("source_gmail_draft_id_partial", "")),
        "source_gmail_drafts_created_count": int(source_design.get("source_gmail_drafts_created_count") or 0),
        "requested_send_enabled": gates["requested_send_enabled"],
        "requested_send_max": gates["requested_send_max"],
        "ack_valid": gates["ack_valid"],
        "ack_present": gates["ack_present"],
        "dry_run": gates["dry_run"],
        "dry_run_raw": gates["dry_run_raw"],
        "real_send_allowed": False,
        "future_real_send_requires_manual_approval": True,
        "future_tag_write_requires_separate_phase": True,
        "future_real_send_required_gates": {
            SEND_DRAFT_ENV: "1",
            SEND_DRAFT_MAX_ENV: "1",
            SEND_DRAFT_ACK_ENV: SEND_DRAFT_ACK_VALUE,
            DRY_RUN_ENV: "0",
        },
        "gate_notes": gates["gate_notes"],
        "blocking_conditions": blocking_conditions,
        "blocking_condition_count": len(blocking_conditions),
        "source_privacy_scan": source_privacy_scan,
        "html_path": str(REPORT_HTML_PATH),
        "json_path": str(REPORT_JSON_PATH),
        "json_trustpilot_gmail_one_draft_send_locked_runner_path": str(REPORT_JSON_PATH),
        "html_trustpilot_gmail_one_draft_send_locked_runner_path": str(REPORT_HTML_PATH),
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
        "json_trustpilot_gmail_one_draft_send_locked_runner_path": str(json_path),
        "html_trustpilot_gmail_one_draft_send_locked_runner_path": str(html_path),
        "one_draft_send_status": payload["one_draft_send_status"],
        "source_design_status": payload["source_design_status"],
        "source_audit_status": payload["source_audit_status"],
        "selected_order_name": payload["selected_order_name"],
        "selected_masked_email": payload["selected_masked_email"],
        "source_gmail_draft_id_partial": payload["source_gmail_draft_id_partial"],
        "requested_send_enabled": payload["requested_send_enabled"],
        "requested_send_max": payload["requested_send_max"],
        "ack_valid": payload["ack_valid"],
        "dry_run": payload["dry_run"],
        "real_send_allowed": payload["real_send_allowed"],
        "future_real_send_requires_manual_approval": payload["future_real_send_requires_manual_approval"],
        "future_tag_write_requires_separate_phase": payload["future_tag_write_requires_separate_phase"],
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
    gate_rows = "\n".join(
        f"<tr><th>{escape(key)}</th><td><code>{escape(value)}</code></td></tr>"
        for key, value in payload["future_real_send_required_gates"].items()
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail One-Draft Send Locked Runner</title>
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
  <h1>Trustpilot Gmail One-Draft Send Locked Runner</h1>
  <p class="warning">Phase 3.14 is locked dry-run only. No Gmail draft send, no Gmail messages.send, no Shopify tag write, and no Kudosi call was performed.</p>
  <p>Status: <strong>{escape(payload["one_draft_send_status"])}</strong></p>
  <p>Selected order: <code>{escape(payload["selected_order_name"])}</code></p>
  <p>Selected masked email: <code>{escape(payload["selected_masked_email"])}</code></p>
  <p>Source Gmail draft id partial: <code>{escape(payload["source_gmail_draft_id_partial"])}</code></p>
  <p>Requested send enabled: <strong>{escape(str(payload["requested_send_enabled"]))}</strong></p>
  <p>ACK valid: <strong>{escape(str(payload["ack_valid"]))}</strong></p>
  <p>Dry-run: <strong>{escape(str(payload["dry_run"]))}</strong></p>
  <p>Real send allowed: <strong>{escape(str(payload["real_send_allowed"]))}</strong></p>
  <h2>Future Real Send Required Gates</h2>
  <table><tbody>{gate_rows}</tbody></table>
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
    return bool(re.search(r'"gmail_draft_id"\s*:', text or ""))


def _apply_self_privacy_assertion(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    self_scan = _privacy_scan_text(text)
    payload["self_privacy_scan"] = self_scan
    if self_scan["raw_customer_email_count"] or self_scan["token_secret_bearer_pattern_count"]:
        payload["one_draft_send_status"] = "blocked_privacy_scan_failed"
        payload["success"] = False
        payload["blocking_conditions"].append(
            {"status": "blocked_privacy_scan_failed", "detail": "locked runner report self privacy scan failed"}
        )
        payload["blocking_condition_count"] = len(payload["blocking_conditions"])
        payload["detected_issue_summary"] = _issue_summary(payload["one_draft_send_status"], payload["blocking_conditions"])
    return payload


def _send_write_flag_names() -> tuple[str, ...]:
    return (
        "gmail_api_call_performed",
        "gmail_draft_send_attempted",
        "gmail_drafts_send_called",
        "gmail_messages_send_called",
        "gmail_send_performed",
        "email_sent",
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "tags_add_performed",
        "tags_remove_performed",
        "kudosi_api_call_performed",
        "ali_reviews_api_call_performed",
    )


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
    if status == DRY_RUN_STATUS:
        return "One-draft send locked runner stayed in dry-run; no Gmail, Shopify, or Kudosi action was performed."
    return "One-draft send locked runner blocked: " + ", ".join(
        _safe_text(item.get("status", "")) for item in blocking_conditions
    )


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 3.14 Trustpilot Gmail one-draft send locked runner finished.\n"
        f"Status: {payload.get('one_draft_send_status')}\n"
        f"Selected order: {payload.get('selected_order_name')}\n"
        f"Selected masked email: {payload.get('selected_masked_email')}\n"
        f"Requested send enabled: {payload.get('requested_send_enabled')}\n"
        f"ACK valid: {payload.get('ack_valid')}\n"
        f"Dry-run: {payload.get('dry_run')}\n"
        f"Blocking conditions: {payload.get('blocking_condition_count')}\n"
        "Safety: no Gmail API call, no draft send, no Shopify API/write, no Kudosi call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
