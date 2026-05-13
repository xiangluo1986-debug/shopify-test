import json
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, utc_now_iso


TASK_NAME = "shopify_review_request_ali_reviews_capability_discovery"
COMMAND_LABEL = "shopify_review_request_ali_reviews_capability_discovery_docs_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_ali_reviews_capability_discovery.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_ali_reviews_capability_discovery.html"

ALI_REVIEWS_PUBLIC_API_BASE_URL = "https://pub.kudosi.ai"
AUTOMATION_DECISION_STATUS = "blocked_until_send_and_status_capabilities_confirmed"


KNOWN_PUBLIC_API_CAPABILITIES = [
    {
        "capability": "List Reviews",
        "status": "documented_public_capability",
        "automation_relevance": "May help inspect submitted reviews, but does not confirm review request email send/status.",
    },
    {
        "capability": "React to a Review",
        "status": "documented_public_capability",
        "automation_relevance": "Review response workflow only; not a review request send/status capability.",
    },
    {
        "capability": "Product Ratings",
        "status": "documented_public_capability",
        "automation_relevance": "May help rating display or reporting; not order-level review request status.",
    },
    {
        "capability": "List Questions",
        "status": "documented_public_capability",
        "automation_relevance": "Question workflow only; not review request send/status.",
    },
    {
        "capability": "React to a Question",
        "status": "documented_public_capability",
        "automation_relevance": "Question response workflow only; not review request send/status.",
    },
]

MISSING_OR_UNCONFIRMED_CAPABILITIES = [
    "Send a review request email for a specific Shopify order.",
    "Check whether a review request email has already been sent for a Shopify order.",
    "Check whether a customer already received a review request email.",
    "Search request history by Shopify order ID.",
    "Search request history by Shopify order name.",
    "Search request history by customer email.",
    "Expose auto-request email scheduled status.",
    "Expose auto-request email sent status.",
    "Expose opened, clicked, failed, or bounced request-email status.",
    "Webhook for review request sent.",
    "Webhook for review submitted tied back to a Shopify order.",
    "Export manual review request history.",
    "Export auto-request history.",
]

MANUAL_DASHBOARD_FEATURES_TO_CHECK = [
    "Auto-Request email settings page.",
    "Auto-request rule timing after fulfillment.",
    "Manual review request send screen.",
    "Order-level or customer-level review request history.",
    "Sent, scheduled, failed, opened, clicked, or bounced request-email status.",
    "Exports for manual request history.",
    "Exports for auto-request history.",
    "API key management page and current plan availability.",
    "Rate limit or developer settings page.",
]

REQUIRED_DASHBOARD_SCREENSHOTS_OR_PAGES = [
    "Auto-Request email settings page showing rule timing after fulfillment.",
    "API key or developer settings page showing whether API keys are available in the current plan.",
    "Manual review request workflow page for a delivered Shopify order.",
    "Any order/customer history page showing whether a review request was sent.",
    "Any export page for manual or auto-request email history.",
]

SUPPORT_QUESTIONS = [
    "Does Kudosi / Ali Reviews provide an API endpoint to send a review request email for a specific Shopify order?",
    "Does Kudosi / Ali Reviews provide an API endpoint to check whether a review request email has already been sent for a Shopify order?",
    "Can the API search by Shopify order ID, order name, customer email, or product ID?",
    "Does the API expose auto-request email status, scheduled status, sent status, opened/clicked status, or failed status?",
    "Is there a webhook for review request sent / review submitted?",
    "Can manual review request history be exported?",
    "Can auto-request history be exported?",
    "Are API keys available in the current plan?",
    "Are rate limits documented?",
]


def run_shopify_review_request_ali_reviews_capability_discovery_task(mode: str) -> dict:
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
        "json_ali_reviews_capability_discovery_path": str(json_path),
        "html_ali_reviews_capability_discovery_path": str(html_path),
        "phase": payload["phase"],
        "mode": payload["mode"],
        "ali_reviews_public_api_base_url": payload["ali_reviews_public_api_base_url"],
        "known_public_api_capability_count": len(payload["known_public_api_capabilities"]),
        "missing_or_unconfirmed_capability_count": len(payload["missing_or_unconfirmed_capabilities"]),
        "support_question_count": len(payload["support_questions"]),
        "automation_decision_status": payload["automation_decision_status"],
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "email_sent": False,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _build_approval_message(json_path, html_path),
    }


def _build_payload(start_time: str, end_time: str, duration_seconds: float) -> dict:
    return {
        "timestamp": end_time,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "0.2",
        "mode": "docs-only-capability-discovery",
        "command_label": COMMAND_LABEL,
        "ali_reviews_public_api_base_url": ALI_REVIEWS_PUBLIC_API_BASE_URL,
        "api_key_needed": True,
        "api_key_value_recorded": False,
        "known_public_api_capabilities": KNOWN_PUBLIC_API_CAPABILITIES,
        "missing_or_unconfirmed_capabilities": MISSING_OR_UNCONFIRMED_CAPABILITIES,
        "manual_dashboard_features_to_check": MANUAL_DASHBOARD_FEATURES_TO_CHECK,
        "required_dashboard_screenshots_or_pages": REQUIRED_DASHBOARD_SCREENSHOTS_OR_PAGES,
        "support_questions": SUPPORT_QUESTIONS,
        "automation_decision_status": AUTOMATION_DECISION_STATUS,
        "shopify_tag_context": {
            "review_request_tag": "1: reveiw request",
            "delivered_tag": "Delivered",
            "exact_string_matching_required": True,
            "do_not_normalize_tags": True,
            "note": "Never assume Shopify tag state proves whether Ali Reviews has sent or not sent an email.",
        },
        "fallback_automation_guidance": (
            "If Ali Reviews / Kudosi cannot confirm send/status API support, future automation must only "
            "produce Shopify candidate reports and may require manual sending in the Ali Reviews dashboard."
        ),
        "safety_summary": {
            "docs_only_capability_discovery": True,
            "ali_reviews_api_call_performed": False,
            "gmail_api_call_performed": False,
            "shopify_api_call_performed": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "tags_add_performed": False,
            "tags_remove_performed": False,
            "email_sent": False,
            "review_request_sent": False,
            "secrets_recorded": False,
            "logs_are_local_reports_only": True,
        },
        "ali_reviews_api_call_performed": False,
        "gmail_api_call_performed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "email_sent": False,
        "review_request_sent": False,
        "no_shopify_writes_performed": True,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Ali Reviews / Kudosi send and status capabilities are unconfirmed; automation remains blocked."
        ),
        "start_time": start_time,
        "end_time": end_time,
        "duration_seconds": duration_seconds,
        "json_ali_reviews_capability_discovery_path": str(REPORT_JSON_PATH),
        "html_ali_reviews_capability_discovery_path": str(REPORT_HTML_PATH),
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
    capabilities = _render_list(payload["known_public_api_capabilities"], item_renderer=_render_capability)
    missing = _render_list(payload["missing_or_unconfirmed_capabilities"])
    dashboard = _render_list(payload["manual_dashboard_features_to_check"])
    screenshots = _render_list(payload["required_dashboard_screenshots_or_pages"])
    questions = _render_list(payload["support_questions"])
    safety = payload["safety_summary"]
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in safety.items()
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Ali Reviews / Kudosi Capability Discovery</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    h1, h2 {{ margin-bottom: 8px; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin-top: 8px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    li {{ margin-bottom: 4px; }}
  </style>
</head>
<body>
  <h1>Ali Reviews / Kudosi Capability Discovery</h1>
  <p>Phase: <code>{escape(payload["phase"])}</code></p>
  <p>Mode: <code>{escape(payload["mode"])}</code></p>
  <p>Public API base URL: <code>{escape(payload["ali_reviews_public_api_base_url"])}</code></p>
  <p>Decision status: <code>{escape(payload["automation_decision_status"])}</code></p>

  <h2>Known Public API Capabilities</h2>
  {capabilities}

  <h2>Missing Or Unconfirmed Capabilities</h2>
  {missing}

  <h2>Manual Dashboard Features To Check</h2>
  {dashboard}

  <h2>Required Dashboard Screenshots Or Pages</h2>
  {screenshots}

  <h2>Support Questions</h2>
  {questions}

  <h2>Safety Flags</h2>
  <table>
    <tbody>
      {safety_rows}
    </tbody>
  </table>
</body>
</html>
"""


def _render_list(items: list, item_renderer=None) -> str:
    renderer = item_renderer or (lambda item: escape(str(item)))
    rendered_items = "\n".join(f"<li>{renderer(item)}</li>" for item in items)
    return f"<ul>{rendered_items}</ul>"


def _render_capability(item: dict) -> str:
    return (
        f"<strong>{escape(str(item['capability']))}</strong> "
        f"({escape(str(item['status']))}): {escape(str(item['automation_relevance']))}"
    )


def _build_approval_message(json_path: Path, html_path: Path) -> str:
    return (
        "Ali Reviews / Kudosi capability discovery report generated locally.\n"
        f"Decision status: {AUTOMATION_DECISION_STATUS}\n"
        "Safety: docs-only; no Ali Reviews API, Gmail API, Shopify write, mutation, tagsAdd/tagsRemove, or email sending.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )
