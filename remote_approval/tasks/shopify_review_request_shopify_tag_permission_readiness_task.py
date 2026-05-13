import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_shopify_tag_permission_readiness"
COMMAND_LABEL = "shopify_review_request_shopify_tag_permission_readiness_docs_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_shopify_tag_permission_readiness.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_shopify_tag_permission_readiness.html"

REQUIRED_ORDER_TAG_SCOPES = ["read_orders", "write_orders"]
REQUIRED_CUSTOMER_TAG_SCOPES = ["read_customers", "write_customers"]
REQUIRED_MUTATIONS = ["tagsAdd", "tagsRemove"]
EXACT_EXISTING_REVIEW_REQUEST_TAG = "1: reveiw request"
EXACT_EXISTING_DELIVERED_TAG = "Delivered"
AUTOMATION_DECISION_STATUS = "blocked_until_shopify_write_scopes_and_manual_approval_confirmed"

FUTURE_CANDIDATE_TAGS = [
    "review_request_ali_sent",
    "review_request_ali_already_sent",
    "review_request_ali_failed",
    "trustpilot_request_sent",
    "review_request_blocked",
    "review_request_no_email",
    "review_request_has_ticket",
    "review_request_refunded",
    "review_request_cancelled",
    "review_request_shipping_issue",
]


def run_shopify_review_request_shopify_tag_permission_readiness_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    start_time = utc_now_iso()
    end_time = utc_now_iso()
    payload = _build_payload(start_time, end_time, round(time.time() - started, 3))
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_shopify_tag_permission_readiness_path": str(json_path),
        "html_shopify_tag_permission_readiness_path": str(html_path),
        "phase": payload["phase"],
        "mode": payload["mode"],
        "required_order_tag_scopes": payload["required_order_tag_scopes"],
        "required_customer_tag_scopes": payload["required_customer_tag_scopes"],
        "required_mutations": payload["required_mutations"],
        "direct_tags_field_overwrite_allowed": False,
        "exact_existing_review_request_tag": EXACT_EXISTING_REVIEW_REQUEST_TAG,
        "exact_existing_delivered_tag": EXACT_EXISTING_DELIVERED_TAG,
        "future_candidate_tag_count": len(FUTURE_CANDIDATE_TAGS),
        "shopify_tag_write_allowed": False,
        "automation_decision_status": AUTOMATION_DECISION_STATUS,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(json_path, html_path),
    }


def _build_payload(start_time: str, end_time: str, duration_seconds: float) -> dict:
    return {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "0.4",
        "mode": "docs-only-shopify-tag-write-readiness",
        "command_label": COMMAND_LABEL,
        "required_order_tag_scopes": REQUIRED_ORDER_TAG_SCOPES,
        "required_customer_tag_scopes": REQUIRED_CUSTOMER_TAG_SCOPES,
        "required_mutations": REQUIRED_MUTATIONS,
        "direct_tags_field_overwrite_allowed": False,
        "exact_existing_review_request_tag": EXACT_EXISTING_REVIEW_REQUEST_TAG,
        "exact_existing_delivered_tag": EXACT_EXISTING_DELIVERED_TAG,
        "exact_string_matching_required": True,
        "preserve_exact_tag_strings": True,
        "full_tags_field_overwrite_allowed": False,
        "future_candidate_tags": FUTURE_CANDIDATE_TAGS,
        "shopify_tag_write_allowed": False,
        "automation_decision_status": AUTOMATION_DECISION_STATUS,
        "future_write_gate_requirements": [
            "Confirm required Shopify scopes.",
            "Generate a dry-run tag mutation plan.",
            "Use exact Shopify resource IDs.",
            "Use exact tag strings.",
            "Use GraphQL Admin API tagsAdd / tagsRemove only.",
            "Confirm Ali Reviews / Kudosi sent-status handling before removing 1: reveiw request.",
            "Require final human approval before any mutation.",
        ],
        "phase_0_4_forbidden_actions": [
            "Do not add future candidate tags.",
            "Do not remove existing tag 1: reveiw request.",
            "Do not remove Delivered.",
            "Do not call Shopify APIs.",
            "Do not run tagsAdd.",
            "Do not run tagsRemove.",
        ],
        "safety_summary": {
            "docs_only_shopify_tag_write_readiness": True,
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "tags_add_performed": False,
            "tags_remove_performed": False,
            "tagsAdd_performed": False,
            "tagsRemove_performed": False,
            "ali_reviews_api_call_performed": False,
            "gmail_api_call_performed": False,
            "email_sent": False,
            "candidate_tags_added": False,
            "existing_review_request_tag_removed": False,
            "delivered_tag_removed": False,
            "logs_are_local_reports_only": True,
        },
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Shopify tag writes remain blocked until scopes, dry-run plan, and manual approval are confirmed."
        ),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "json_shopify_tag_permission_readiness_path": str(REPORT_JSON_PATH),
        "html_shopify_tag_permission_readiness_path": str(REPORT_HTML_PATH),
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
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Shopify Tag Permission Readiness</title>
</head>
<body>
  <h1>Shopify Tag Permission Readiness</h1>
  <p>Phase: <code>{escape(payload["phase"])}</code></p>
  <p>Mode: <code>{escape(payload["mode"])}</code></p>
  <p>Decision status: <code>{escape(payload["automation_decision_status"])}</code></p>
  <p>Existing review request tag: <code>{escape(payload["exact_existing_review_request_tag"])}</code></p>
  <p>Existing delivered tag: <code>{escape(payload["exact_existing_delivered_tag"])}</code></p>
  <p>Direct tags field overwrite allowed: <code>{escape(str(payload["direct_tags_field_overwrite_allowed"]))}</code></p>
  <h2>Required Scopes</h2>
  <ul>
    <li>Order tags: {escape(", ".join(payload["required_order_tag_scopes"]))}</li>
    <li>Customer tags: {escape(", ".join(payload["required_customer_tag_scopes"]))}</li>
  </ul>
  <h2>Required Mutations</h2>
  {_render_list(payload["required_mutations"])}
  <h2>Future Candidate Tags</h2>
  {_render_list(payload["future_candidate_tags"])}
  <h2>Safety Flags</h2>
  <table>
    <tbody>{safety_rows}</tbody>
  </table>
</body>
</html>
"""


def _render_list(items: list[str]) -> str:
    return "<ul>" + "\n".join(f"<li><code>{escape(str(item))}</code></li>" for item in items) + "</ul>"


def _build_approval_message(json_path: Path, html_path: Path) -> str:
    return (
        "Shopify tag permission readiness package generated locally.\n"
        f"Decision status: {AUTOMATION_DECISION_STATUS}\n"
        "Safety: docs-only; no Shopify API/write/mutation, tagsAdd/tagsRemove, Ali Reviews API, Gmail API, or email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
