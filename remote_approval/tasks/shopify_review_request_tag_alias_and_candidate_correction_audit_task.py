import json
import subprocess
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_tag_alias_and_candidate_correction_audit"
COMMAND_LABEL = "shopify_review_request_tag_alias_and_candidate_correction_audit_local_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_tag_alias_and_candidate_correction_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_tag_alias_and_candidate_correction_audit.html"
LAST_60_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_TAG_ALIAS_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_TAG_ALIAS_AUDIT_JSON_END"

REVIEW_REQUEST_TAG_ALIASES = [
    "1: review request",
    "1: reveiw request",
    "1:review request",
    "1 : review request",
    "1:reveiw request",
    "1 : reveiw request",
]
DELIVERED_TAG_ALIASES = ["Delivered", "delivered"]
TRUSTPILOT_SENT_TAG_ALIASES = [
    "1: trustpilot",
    "1: trustpoilt",
    "1:trustpilot",
    "1 : trustpilot",
    "1:trustpoilt",
    "1 : trustpoilt",
]


def run_shopify_review_request_tag_alias_and_candidate_correction_audit_task(mode: str) -> dict:
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
        "build_review_request_tag_alias_and_candidate_correction_audit_report; "
        "payload = build_review_request_tag_alias_and_candidate_correction_audit_report({}); "
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


def _failed_run(failure_type: str, exit_code: int, stdout: str, stderr: str) -> dict:
    return {
        "success": False,
        "exit_code": exit_code,
        "failure_type": failure_type,
        "stdout": _sanitize_text(stdout),
        "stderr": _sanitize_text(stderr),
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


def _fallback_payload_from_last_scan(result: dict, duration_seconds: float) -> dict:
    scan = _read_json(LAST_60_SCAN_JSON_PATH)
    candidate = scan.get("candidate_22562_audit") if isinstance(scan.get("candidate_22562_audit"), dict) else {}
    if not candidate:
        candidate = _candidate_from_summaries(scan)
    payload = {
        "timestamp": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28A",
        "mode": "dry-run-local-audit-fallback",
        "command_label": COMMAND_LABEL,
        "report_status": "tag_alias_and_candidate_correction_audit_fallback_ready"
        if scan
        else "blocked_tag_alias_and_candidate_correction_audit_failed",
        "success": bool(scan),
        "source_scan_report_loaded": bool(scan),
        "source_scan_report_path": str(LAST_60_SCAN_JSON_PATH),
        "django_audit_failure_type": _sanitize_text(result.get("failure_type", "")),
        "django_audit_exit_code": int(result.get("exit_code") or 1),
        "review_request_tag_aliases": REVIEW_REQUEST_TAG_ALIASES,
        "canonical_review_request_tag_for_future_writes": "1: review request",
        "delivered_tag_aliases": DELIVERED_TAG_ALIASES,
        "trustpilot_sent_tag_aliases": TRUSTPILOT_SENT_TAG_ALIASES,
        "order_22562_tags_loaded": candidate.get("tags_loaded") is True,
        "order_22562_review_request_tag_detected": candidate.get("review_request_tag_detected") is True,
        "order_22562_matched_review_request_tag_value": _safe_text(
            candidate.get("matched_review_request_tag_value", "")
        ),
        "order_22562_delivered_detected": candidate.get("delivered_detected") is True,
        "order_22562_merged_group_evidence_source": _safe_text(
            candidate.get("merged_group_evidence_source", "none")
        ),
        "order_22562_explicit_merge_evidence": candidate.get("explicit_merge_evidence") is True,
        "order_22562_final_eligibility_status": _safe_text(
            candidate.get("final_eligibility_status", "not_scanned")
        ),
        "order_22562_final_blockers": _safe_list(candidate.get("final_blockers")),
        "candidate_22562_audit": candidate,
        "eligible_candidate_count_after_fix": int(scan.get("eligible_candidate_count") or 0),
        "eligible_candidate_orders_after_fix": [
            _safe_text(row.get("order", ""))
            for row in scan.get("eligible_candidates_summary", [])
            if isinstance(row, dict) and row.get("order")
        ],
        "blocked_merged_group_count_after_fix": int(scan.get("blocked_merged_group_count") or 0),
        **_safety_flags(),
        "duration_seconds": duration_seconds,
    }
    payload["detected_issue_summary"] = _issue_summary(payload)
    return payload


def _candidate_from_summaries(scan: dict) -> dict:
    for section, key in (
        ("eligible", "eligible_candidates_summary"),
        ("blocked", "blocked_candidates_summary"),
        ("already_sent", "already_sent_summary"),
    ):
        for row in scan.get(key) or []:
            if not isinstance(row, dict):
                continue
            order = row.get("order") or row.get("order_or_group")
            if order != "#22562":
                continue
            tags = _safe_list(row.get("tags"))
            matched = _safe_text(row.get("matched_review_request_tag_value", ""))
            blockers = []
            if section == "blocked":
                blockers = _split_blockers(row.get("block_reason", ""))
            elif section == "already_sent":
                blockers = [_safe_text(row.get("evidence", ""))]
            return {
                "order_name": "#22562",
                "row_found": True,
                "row_section": section,
                "tags": tags,
                "tags_loaded": bool(tags),
                "review_request_tag_detected": row.get("review_request_tag_present") is True or bool(matched),
                "matched_review_request_tag_value": matched,
                "delivered_detected": row.get("delivered_status") == "Delivered",
                "merged_group_evidence_source": _safe_text(row.get("merged_group_evidence_source", "none")),
                "explicit_merge_evidence": bool(row.get("merged_group_evidence_source")),
                "final_eligibility_status": "eligible" if section == "eligible" else section,
                "final_blockers": [blocker for blocker in blockers if blocker],
            }
    return {
        "order_name": "#22562",
        "row_found": False,
        "row_section": "not_scanned",
        "tags": [],
        "tags_loaded": False,
        "review_request_tag_detected": False,
        "matched_review_request_tag_value": "",
        "delivered_detected": False,
        "merged_group_evidence_source": "none",
        "explicit_merge_evidence": False,
        "final_eligibility_status": "not_scanned",
        "final_blockers": ["Order #22562 was not present in the local last-60-days scan."],
    }


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


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


def _write_json(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=True, indent=2)
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
        "exit_code": 0 if payload.get("success") is True else 1,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "report_status": payload.get("report_status", ""),
        "order_22562_tags_loaded": payload.get("order_22562_tags_loaded") is True,
        "order_22562_review_request_tag_detected": (
            payload.get("order_22562_review_request_tag_detected") is True
        ),
        "order_22562_matched_review_request_tag_value": payload.get(
            "order_22562_matched_review_request_tag_value", ""
        ),
        "order_22562_delivered_detected": payload.get("order_22562_delivered_detected") is True,
        "order_22562_explicit_merge_evidence": payload.get("order_22562_explicit_merge_evidence") is True,
        "order_22562_final_eligibility_status": payload.get("order_22562_final_eligibility_status", ""),
        "eligible_candidate_count_after_fix": int(payload.get("eligible_candidate_count_after_fix") or 0),
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
        "Review request tag alias and #22562 correction audit completed.\n"
        f"Result: {payload.get('report_status')}\n"
        f"#22562 final status: {payload.get('order_22562_final_eligibility_status')}\n"
        f"#22562 matched tag: {payload.get('order_22562_matched_review_request_tag_value') or 'none'}\n"
        f"Eligible candidates after fix: {payload.get('eligible_candidate_count_after_fix', 0)}\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "0 = stop"
    )


def _render_html(payload: dict) -> str:
    blockers = "".join(
        f"<li>{escape(str(blocker))}</li>"
        for blocker in payload.get("order_22562_final_blockers", [])
    )
    if not blockers:
        blockers = "<li>None</li>"
    aliases = "".join(
        f"<span class=\"pill\">{escape(alias)}</span>"
        for alias in payload.get("review_request_tag_aliases", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review Request Tag Alias Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; margin: 12px 0 24px; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .pill {{ display: inline-block; margin: 2px; padding: 2px 6px; border: 1px solid #bcccdc; border-radius: 4px; }}
  </style>
</head>
<body>
  <h1>Review Request Tag Alias Audit</h1>
  <p>Status: <strong>{escape(str(payload.get("report_status", "")))}</strong></p>
  <p>{aliases}</p>
  <table><tbody>
    <tr><th>#22562 tags loaded</th><td>{escape(str(payload.get("order_22562_tags_loaded") is True))}</td></tr>
    <tr><th>#22562 review request tag detected</th><td>{escape(str(payload.get("order_22562_review_request_tag_detected") is True))}</td></tr>
    <tr><th>#22562 matched review request tag value</th><td>{escape(str(payload.get("order_22562_matched_review_request_tag_value", "")))}</td></tr>
    <tr><th>#22562 delivered detected</th><td>{escape(str(payload.get("order_22562_delivered_detected") is True))}</td></tr>
    <tr><th>#22562 merged group evidence source</th><td>{escape(str(payload.get("order_22562_merged_group_evidence_source", "")))}</td></tr>
    <tr><th>#22562 explicit merge evidence</th><td>{escape(str(payload.get("order_22562_explicit_merge_evidence") is True))}</td></tr>
    <tr><th>#22562 final eligibility status</th><td>{escape(str(payload.get("order_22562_final_eligibility_status", "")))}</td></tr>
    <tr><th>Eligible candidate count after fix</th><td>{escape(str(payload.get("eligible_candidate_count_after_fix", 0)))}</td></tr>
  </tbody></table>
  <h2>#22562 Final Blockers</h2>
  <ul>{blockers}</ul>
  <h2>Safety</h2>
  <table><tbody>
    <tr><th>Gmail API call performed</th><td>{escape(str(payload.get("gmail_api_call_performed") is True))}</td></tr>
    <tr><th>Email sent</th><td>{escape(str(payload.get("email_sent") is True))}</td></tr>
    <tr><th>Shopify API call performed</th><td>{escape(str(payload.get("shopify_api_call_performed") is True))}</td></tr>
    <tr><th>Shopify write performed</th><td>{escape(str(payload.get("shopify_write_performed") is True))}</td></tr>
    <tr><th>External review API call performed</th><td>{escape(str(payload.get("external_review_api_call_performed") is True))}</td></tr>
  </tbody></table>
</body>
</html>"""


def _issue_summary(payload: dict) -> str:
    return (
        f"#22562 status after alias correction: {payload.get('order_22562_final_eligibility_status')}; "
        f"matched tag: {payload.get('order_22562_matched_review_request_tag_value') or 'none'}; "
        f"eligible candidates after fix: {payload.get('eligible_candidate_count_after_fix', 0)}. "
        "No Gmail, Shopify, Trustpilot, Kudosi, or Ali Reviews API calls were performed."
    )


def _split_blockers(value) -> list[str]:
    text = _safe_text(value, 500)
    if not text:
        return []
    return [_safe_text(part, 240) for part in text.split(";") if _safe_text(part, 240)]


def _safe_list(value) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [_safe_text(item) for item in value if _safe_text(item)]
    if value in (None, ""):
        return []
    return [_safe_text(value)]


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _safe_text(value, max_length: int = 300) -> str:
    text = str(value or "").replace("\x00", "")
    text = " ".join(text.split())
    if len(text) > max_length:
        return text[: max_length - 3] + "..."
    return text


def _sanitize_text(value, max_length: int = 1000) -> str:
    text = _safe_text(value, max_length=max_length)
    secret_markers = (
        "access_token",
        "refresh_token",
        "client_secret",
        "api_key",
        "password",
        "secret",
        "bearer ",
        "shpat_",
        "ya29.",
    )
    lowered = text.lower()
    if any(marker in lowered for marker in secret_markers):
        return "[redacted sensitive output]"
    return text
