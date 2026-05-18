import json
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_tag_exclusion_audit"
COMMAND_LABEL = "shopify_review_request_trustpilot_tag_exclusion_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_trustpilot_tag_exclusion_audit.json"
REPORT_HTML_PATH = LOG_DIR / "codex_runs" / "shopify_review_request_trustpilot_tag_exclusion_audit.html"
LAST_60_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_EXCLUSION_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_TRUSTPILOT_TAG_EXCLUSION_AUDIT_JSON_END"


def run_shopify_review_request_trustpilot_tag_exclusion_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_audit()
    if completed["success"]:
        payload = completed["payload"]
        payload["duration_seconds"] = round(time.time() - started, 3)
    else:
        payload = _fallback_payload_from_last_scan(completed, round(time.time() - started, 3))

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_audit() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_trustpilot_tag_exclusion_audit_report; "
        "payload = build_review_request_trustpilot_tag_exclusion_audit_report({}); "
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
    return {"success": True, "exit_code": 0, "payload": payload, "stdout": stdout, "stderr": stderr}


def _fallback_payload_from_last_scan(result: dict, duration_seconds: float) -> dict:
    scan = _read_json(LAST_60_SCAN_JSON_PATH)
    row, section = _row_from_scan(scan, "#21225")
    diagnosis = scan.get("order_21225_diagnosis") if isinstance(scan.get("order_21225_diagnosis"), dict) else {}
    local_tags = _safe_list(
        diagnosis.get("local_shopify_tags")
        or diagnosis.get("order_tags_display")
        or (row or {}).get("local_shopify_tags")
        or (row or {}).get("tags")
        or []
    )
    matched = _safe_list(
        (row or {}).get("matched_trustpilot_tag_values")
        or diagnosis.get("matched_trustpilot_tag_values")
        or []
    )
    trustpilot_detected = (row or {}).get("trustpilot_tag_detected") is True or bool(matched)
    needs_review_orders = {
        _safe_text(item.get("order", ""))
        for item in scan.get("eligible_candidates_summary", [])
        if isinstance(item, dict)
    }
    already_sent_orders = {
        _safe_text(item.get("order", ""))
        for item in scan.get("already_sent_summary", [])
        if isinstance(item, dict)
    }
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.29E",
        "mode": "dry-run-local-trustpilot-tag-exclusion-audit-fallback",
        "command_label": COMMAND_LABEL,
        "audit_status": "trustpilot_tag_exclusion_audit_fallback_ready"
        if scan
        else "blocked_trustpilot_tag_exclusion_audit_failed",
        "report_status": "trustpilot_tag_exclusion_audit_fallback_ready"
        if scan
        else "blocked_trustpilot_tag_exclusion_audit_failed",
        "success": bool(scan),
        "source_scan_report_loaded": bool(scan),
        "source_scan_report_path": str(LAST_60_SCAN_JSON_PATH),
        "django_audit_failure_type": _safe_text(result.get("failure_type", "")),
        "django_audit_exit_code": int(result.get("exit_code") or 1),
        "order_21225_found": bool(row) or diagnosis.get("found_in_local_shopify_order") is True,
        "order_21225_local_tags": local_tags,
        "order_21225_trustpilot_tag_detected": trustpilot_detected,
        "order_21225_trustpilot_tag_source": _safe_text(
            (row or {}).get("trustpilot_tag_source") or diagnosis.get("trustpilot_tag_source", "")
        ),
        "order_21225_matched_trustpilot_tag_values": matched,
        "order_21225_candidate_section_before": "not_reconstructed_current_scan",
        "order_21225_candidate_section_after": section,
        "order_21225_removed_from_needs_review": "#21225" not in needs_review_orders,
        "order_21225_shown_in_already_sent": "#21225" in already_sent_orders or section == "already_sent",
        "order_21225_review_send_button_absent": "#21225" not in needs_review_orders,
        "order_21225_shopify_tag_status_label": _safe_text((row or {}).get("shopify_tag_status_label", "")),
        "order_21225_shopify_tag_pending": (row or {}).get("shopify_tag_pending") is True,
        "order_21225_already_sent_reason": _safe_text(
            (row or {}).get("already_sent_reason")
            or diagnosis.get("already_sent_reason", "")
            or ("Shopify tag shows Trustpilot already sent." if trustpilot_detected else "")
        ),
        "order_21225_evidence": _safe_text(
            (row or {}).get("evidence")
            or (row or {}).get("reason")
            or ("Trustpilot tag found on Shopify order." if trustpilot_detected else "")
        ),
        "order_21225_diagnosis": diagnosis,
        "order_21225_trustpilot_tag_detection": scan.get("order_21225_trustpilot_tag_detection") or {},
        "trustpilot_tagged_orders_excluded_count": int(scan.get("trustpilot_tagged_orders_excluded_count") or 0),
        "coverage_warnings": scan.get("coverage_warnings") or [],
        "needs_review_order_count": len(needs_review_orders),
        "already_sent_order_count": len(already_sent_orders),
        **_safety_flags(),
        "duration_seconds": duration_seconds,
    }
    payload["detected_issue_summary"] = _issue_summary(payload)
    return payload


def _row_from_scan(scan: dict, order_name: str) -> tuple[dict, str]:
    for section, key in (
        ("eligible", "eligible_candidates_summary"),
        ("blocked", "blocked_candidates_summary"),
        ("already_sent", "already_sent_summary"),
    ):
        for row in scan.get(key) or []:
            if isinstance(row, dict) and row.get("order") == order_name:
                return row, section
    return {}, "not_scanned"


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
        "stdout": _safe_text(stdout),
        "stderr": _safe_text(stderr),
    }


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json(payload: dict) -> Path:
    REPORT_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return REPORT_JSON_PATH


def _write_html(payload: dict) -> Path:
    REPORT_HTML_PATH.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        ("Audit status", payload.get("audit_status")),
        ("#21225 found", payload.get("order_21225_found")),
        ("#21225 local tags", ", ".join(payload.get("order_21225_local_tags") or [])),
        ("#21225 Trustpilot tag detected", payload.get("order_21225_trustpilot_tag_detected")),
        ("#21225 section after", payload.get("order_21225_candidate_section_after")),
        ("Removed from Needs review", payload.get("order_21225_removed_from_needs_review")),
        ("Shown in Already sent", payload.get("order_21225_shown_in_already_sent")),
        ("Trustpilot-tagged exclusions", payload.get("trustpilot_tagged_orders_excluded_count")),
        ("No Gmail/Shopify/API writes", payload.get("all_new_actions_no_write_confirmed")),
    ]
    body = "\n".join(
        f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )
    html = (
        "<!doctype html><html><head><meta charset=\"utf-8\">"
        "<title>Trustpilot Tag Exclusion Audit</title></head><body>"
        "<h1>Trustpilot Tag Exclusion Audit</h1>"
        f"<p>{escape(str(payload.get('detected_issue_summary', '')))}</p>"
        f"<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">{body}</table>"
        "</body></html>"
    )
    REPORT_HTML_PATH.write_text(html, encoding="utf-8")
    return REPORT_HTML_PATH


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "mode": "dry-run",
        "success": payload.get("success") is True,
        "summary": _summary(payload),
        "approval_message": _approval_message(payload, json_path, html_path),
        "checked_items": 1,
        "warnings": len(payload.get("coverage_warnings") or []),
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "json_trustpilot_tag_exclusion_audit_path": str(json_path),
        "html_trustpilot_tag_exclusion_audit_path": str(html_path),
        "order_21225_found": payload.get("order_21225_found") is True,
        "order_21225_trustpilot_tag_detected": payload.get("order_21225_trustpilot_tag_detected") is True,
        "order_21225_removed_from_needs_review": payload.get("order_21225_removed_from_needs_review") is True,
        "order_21225_shown_in_already_sent": payload.get("order_21225_shown_in_already_sent") is True,
        "trustpilot_tagged_orders_excluded_count": int(
            payload.get("trustpilot_tagged_orders_excluded_count") or 0
        ),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Trustpilot tag exclusion audit completed.\n"
        f"Result: {payload.get('audit_status')}\n"
        f"#21225 found: {payload.get('order_21225_found')}\n"
        f"#21225 Trustpilot tag detected: {payload.get('order_21225_trustpilot_tag_detected')}\n"
        f"#21225 removed from Needs review: {payload.get('order_21225_removed_from_needs_review')}\n"
        f"#21225 shown in Already sent: {payload.get('order_21225_shown_in_already_sent')}\n"
        f"Trustpilot-tagged exclusions: {payload.get('trustpilot_tagged_orders_excluded_count')}\n"
        f"Coverage warnings: {', '.join(payload.get('coverage_warnings') or []) or 'none'}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n"
        "No Gmail, Shopify, external review API, or write calls were performed.\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "0 = stop\n"
        "Enter Y / N / P / STOP / SHOW_LOG / SUMMARY (legacy: 1 / 2 / 0):"
    )


def _summary(payload: dict) -> str:
    return (
        f"#21225 found={payload.get('order_21225_found')}; "
        f"trustpilot_tag_detected={payload.get('order_21225_trustpilot_tag_detected')}; "
        f"removed_from_needs_review={payload.get('order_21225_removed_from_needs_review')}; "
        f"shown_in_already_sent={payload.get('order_21225_shown_in_already_sent')}; "
        f"trustpilot_tagged_exclusions={payload.get('trustpilot_tagged_orders_excluded_count')}. "
        "No Gmail/Shopify/external API calls or writes were performed."
    )


def _issue_summary(payload: dict) -> str:
    if (
        payload.get("order_21225_trustpilot_tag_detected") is True
        and payload.get("order_21225_removed_from_needs_review") is True
        and payload.get("order_21225_shown_in_already_sent") is True
    ):
        return "#21225 Trustpilot tag exclusion is enforced."
    return "#21225 Trustpilot tag exclusion still needs review."


def _safety_flags() -> dict:
    return {
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
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
    }


def _safe_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [_safe_text(item) for item in value if _safe_text(item)]
    text = _safe_text(value)
    if not text:
        return []
    return [_safe_text(part) for part in text.split(",") if _safe_text(part)]


def _safe_text(value, max_length: int = 300) -> str:
    text = str(value or "").strip()
    text = "".join(ch if ch == "\n" or ch == "\t" or ord(ch) >= 32 else " " for ch in text)
    return text[:max_length]


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)
