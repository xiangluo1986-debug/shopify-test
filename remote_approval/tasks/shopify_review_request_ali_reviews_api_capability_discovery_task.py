import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_ali_reviews_api_capability_discovery"
COMMAND_LABEL = "shopify_review_request_ali_reviews_api_capability_discovery_read_only"
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_ali_reviews_api_capability_discovery.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_ali_reviews_api_capability_discovery.html"

PHASE = "5.0"
DISCOVERY_STATUS_BLOCKED = "blocked_missing_vendor_api_documentation"

ENV_VAR_NAMES = [
    "KUDOSI_API_KEY",
    "ALI_REVIEWS_API_KEY",
    "FIREAPPS_API_KEY",
    "ALI_REVIEWS_BASE_URL",
    "KUDOSI_BASE_URL",
]

RELATED_ENV_VAR_NAMES = [
    "KUDOSI_API_BASE_URL",
    "KUDOSI_API_PROBE_IGNORE_KEY",
]

SEARCH_TERMS = [
    "kudosi",
    "ali reviews",
    "fireapps",
    "review request",
    "request dashboard",
    "blocklist",
    "KUDOSI_API_KEY",
    "ALI_REVIEWS_API_KEY",
    "FIREAPPS_API_KEY",
    "ALI_REVIEWS_BASE_URL",
    "KUDOSI_BASE_URL",
    "KUDOSI_API_BASE_URL",
]

CAPABILITY_REQUIREMENTS = [
    (
        "create_review_request",
        "Vendor endpoint to trigger or create one review request for one Shopify order.",
    ),
    (
        "get_review_request_status",
        "Vendor endpoint to check sent, scheduled, failed, cancelled, opened, or clicked status.",
    ),
    (
        "list_request_dashboard_records",
        "Vendor endpoint or export API for Request Dashboard records.",
    ),
    (
        "cancel_scheduled_request",
        "Vendor endpoint to cancel one scheduled request without deleting other history.",
    ),
    (
        "add_blocklist_customer",
        "Vendor endpoint to add one customer to the Ali Reviews / Kudosi blocklist.",
    ),
    (
        "remove_blocklist_customer",
        "Vendor endpoint to remove one customer from the blocklist.",
    ),
    (
        "bulk_import_blocklist",
        "Vendor endpoint or documented import API for bulk blocklist operations.",
    ),
    (
        "query_by_shopify_order_id",
        "Documented request/dashboard filter by Shopify order gid or numeric order ID.",
    ),
    (
        "query_by_order_name",
        "Documented request/dashboard filter by Shopify order name.",
    ),
    (
        "query_by_customer_email",
        "Documented request/dashboard filter by customer email with privacy controls.",
    ),
    (
        "query_by_shopify_customer_id",
        "Documented request/dashboard filter by Shopify customer gid or numeric customer ID.",
    ),
    (
        "webhook_review_request_status",
        "Webhook or event stream for review request sent, scheduled, failed, cancelled, or delivered status.",
    ),
    (
        "webhook_review_created",
        "Webhook or event stream for review creation tied back to Shopify order/customer identifiers.",
    ),
]

REQUIRED_VENDOR_ENDPOINTS = [
    {
        "endpoint_need": "create_or_send_review_request",
        "required_operation": "Trigger or create one review request for one Shopify order.",
        "required_filters_or_inputs": ["shopify_order_id", "order_name", "shopify_customer_id", "customer_email"],
    },
    {
        "endpoint_need": "query_request_status",
        "required_operation": "Return whether a request is not found, scheduled, sent, failed, cancelled, opened, or clicked.",
        "required_filters_or_inputs": ["shopify_order_id", "order_name", "shopify_customer_id", "customer_email"],
    },
    {
        "endpoint_need": "list_request_dashboard_records",
        "required_operation": "Read Request Dashboard records without creating or changing requests.",
        "required_filters_or_inputs": ["created_at_range", "status", "shopify_order_id", "customer_identifier"],
    },
    {
        "endpoint_need": "cancel_scheduled_request",
        "required_operation": "Cancel one scheduled review request by vendor request ID or Shopify order/customer identifier.",
        "required_filters_or_inputs": ["vendor_request_id", "shopify_order_id", "customer_identifier"],
    },
    {
        "endpoint_need": "blocklist_add_remove",
        "required_operation": "Add, remove, and query customer blocklist records.",
        "required_filters_or_inputs": ["customer_email", "shopify_customer_id", "reason", "source"],
    },
]

EXCLUDED_DIR_NAMES = {
    ".git",
    ".codex",
    ".mypy_cache",
    ".pytest_cache",
    "__pycache__",
    "logs",
    "node_modules",
    "venv",
    ".venv",
    "inputs",
}

TEXT_EXTENSIONS = {
    ".md",
    ".py",
    ".ps1",
    ".txt",
    ".html",
    ".yml",
    ".yaml",
}

MAX_FILE_BYTES = 500_000
MAX_EVIDENCE_ITEMS = 80

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_ASSIGNMENT_RE = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD|ACCESS_TOKEN|REFRESH_TOKEN)[A-Z0-9_]*)"
    r"\s*=\s*([\"'][^\"']*[\"']|[^\s#]+)"
)
AUTH_HEADER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*)([^,\]}]+)")
TOKEN_VALUE_RE = re.compile(r"(?i)\b(?:bearer[ \t]+|shpat_|ghp_|xox[baprs]-)[A-Za-z0-9._~+/=-]+")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def run_shopify_review_request_ali_reviews_api_capability_discovery_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    local_references = _scan_local_references()
    env_presence = _check_env_presence()
    read_only_probe_pattern = _inspect_existing_read_only_probe_pattern()
    capability_matrix = _build_capability_matrix()
    payload = _build_payload(
        local_references=local_references,
        env_presence=env_presence,
        read_only_probe_pattern=read_only_probe_pattern,
        capability_matrix=capability_matrix,
        duration_seconds=round(time.time() - started, 3),
    )
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _scan_local_references() -> dict:
    evidence = []
    match_counts_by_term = {term: 0 for term in SEARCH_TERMS}
    files_scanned = 0
    files_with_matches = set()

    for path in _iter_scan_files():
        files_scanned += 1
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue

        for line_number, line in enumerate(lines, start=1):
            matched_terms = _matched_terms(line)
            if not matched_terms:
                continue
            files_with_matches.add(_relative_path(path))
            for term in matched_terms:
                match_counts_by_term[term] += 1
            if len(evidence) < MAX_EVIDENCE_ITEMS:
                evidence.append(
                    {
                        "path": _relative_path(path),
                        "line": line_number,
                        "matched_terms": matched_terms,
                        "snippet_sanitized": _sanitize_snippet(line),
                    }
                )

    return {
        "scan_roots": ["remote_approval", "AGENTS.md"],
        "excluded_paths_policy": "Skipped .env*, logs, inputs, .git, .codex, cache folders, and binary/non-doc files.",
        "files_scanned": files_scanned,
        "files_with_matches_count": len(files_with_matches),
        "files_with_matches": sorted(files_with_matches),
        "match_counts_by_term": match_counts_by_term,
        "evidence_items_returned": len(evidence),
        "evidence_items_limit": MAX_EVIDENCE_ITEMS,
        "evidence": evidence,
    }


def _iter_scan_files() -> list[Path]:
    roots = [PROJECT_ROOT / "remote_approval", PROJECT_ROOT / "AGENTS.md"]
    current_file = Path(__file__).resolve()
    files = []
    for root in roots:
        if not root.exists():
            continue
        if root.is_file():
            candidates = [root]
        else:
            candidates = [path for path in root.rglob("*") if path.is_file()]
        for path in candidates:
            resolved = path.resolve()
            if resolved == current_file:
                continue
            if _should_skip_path(path):
                continue
            files.append(path)
    return sorted(files)


def _should_skip_path(path: Path) -> bool:
    if path.name.lower().startswith(".env"):
        return True
    if path.suffix.lower() not in TEXT_EXTENSIONS:
        return True
    if any(part in EXCLUDED_DIR_NAMES for part in path.parts):
        return True
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return True
    except OSError:
        return True
    lowered_name = path.name.lower()
    secret_name_markers = ("credential", "credentials", "token", "secret", "password")
    return any(marker in lowered_name for marker in secret_name_markers)


def _matched_terms(line: str) -> list[str]:
    lowered = line.lower()
    matches = []
    for term in SEARCH_TERMS:
        if term.lower() in lowered:
            matches.append(term)
    return matches


def _check_env_presence() -> dict:
    checked = {}
    for name in ENV_VAR_NAMES:
        checked[name] = {
            "present": name in os.environ,
            "value_read": False,
            "value_reported": False,
            "source": "process_environment_presence_only",
        }
    related = {}
    for name in RELATED_ENV_VAR_NAMES:
        related[name] = {
            "present": name in os.environ,
            "value_read": False,
            "value_reported": False,
            "source": "process_environment_presence_only",
        }
    return {
        "checked_env_vars": checked,
        "related_env_vars": related,
        "env_file_read": False,
        "dotenv_file_read": False,
        "values_reported": False,
        "present_count": sum(1 for item in checked.values() if item["present"]),
        "checked_count": len(checked),
    }


def _inspect_existing_read_only_probe_pattern() -> dict:
    probe_path = PROJECT_ROOT / "remote_approval" / "tasks" / "shopify_review_request_kudosi_api_capability_probe_task.py"
    if not probe_path.exists():
        return {
            "found": False,
            "source": "local_code",
            "path": _relative_path(probe_path),
            "network_probe_performed": False,
            "notes": "No existing Kudosi read-only probe pattern was found in local code.",
        }

    try:
        text = probe_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""

    endpoint_match = re.search(r"READ_ONLY_ENDPOINT\s*=\s*[\"']([^\"']+)[\"']", text)
    method_get_present = "method=\"GET\"" in text or "method='GET'" in text
    urlopen_present = "urlopen(" in text
    found = bool(endpoint_match and method_get_present and urlopen_present)
    endpoint = endpoint_match.group(1) if endpoint_match else ""
    return {
        "found": found,
        "source": "local_code",
        "path": _relative_path(probe_path),
        "http_method": "GET" if method_get_present else "",
        "endpoint_path": endpoint,
        "network_probe_performed": False,
        "reused_as_local_evidence_only": found,
        "notes": (
            "Existing local code has a read-only Kudosi probe pattern, but Phase 5.0 did not call it because "
            "this task checks environment presence only and no Request Dashboard, blocklist, send, cancel, "
            "or status endpoint documentation is confirmed."
        )
        if found
        else "Existing local file did not show a complete GET probe pattern.",
    }


def _build_capability_matrix() -> list[dict]:
    capabilities = []
    for capability, requirement in CAPABILITY_REQUIREMENTS:
        capabilities.append(
            {
                "capability": capability,
                "status": "blocked_missing_api_docs",
                "evidence_source": "vendor_docs_needed",
                "safe_to_implement_now": False,
                "notes": (
                    f"{requirement} Local code/docs do not confirm a safe endpoint, authentication model, "
                    "required identifiers, response schema, rate limit, or no-write read path for this capability."
                ),
            }
        )
    return capabilities


def _build_payload(
    local_references: dict,
    env_presence: dict,
    read_only_probe_pattern: dict,
    capability_matrix: list[dict],
    duration_seconds: float,
) -> dict:
    timestamp = utc_now_iso()
    safety_flags = _safety_flags()
    safe_to_implement_count = sum(1 for item in capability_matrix if item["safe_to_implement_now"])
    return {
        "timestamp": timestamp,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "mode": "read-only-api-capability-discovery",
        "command_label": COMMAND_LABEL,
        "ali_reviews_api_capability_discovery_status": DISCOVERY_STATUS_BLOCKED,
        "capability_matrix": capability_matrix,
        "capability_summary": {
            "total_capabilities_checked": len(capability_matrix),
            "confirmed_count": sum(1 for item in capability_matrix if item["status"] == "confirmed"),
            "safe_to_implement_now_count": safe_to_implement_count,
            "blocked_missing_api_docs_count": sum(
                1 for item in capability_matrix if item["status"] == "blocked_missing_api_docs"
            ),
            "automation_decision": "must_wait_for_vendor_api_docs_before_send_status_dashboard_or_blocklist_adapter",
        },
        "env_var_presence": env_presence,
        "local_reference_scan": local_references,
        "existing_read_only_probe_pattern": read_only_probe_pattern,
        "network_probe": {
            "performed": False,
            "http_method": "",
            "endpoint_called": "",
            "reason": (
                "No network call was made. Existing local GET probe evidence is not enough to confirm the "
                "Phase 5.0 request dashboard, review request send/status, cancel, or blocklist capabilities."
            ),
        },
        "required_vendor_endpoints": REQUIRED_VENDOR_ENDPOINTS,
        "recommended_next_steps": _recommended_next_steps(),
        "adapter_skeleton_recommendation": {
            "current_project_can_proceed_with_adapter_skeleton": False,
            "recommendation": "Wait for Ali Reviews / Kudosi vendor API documentation before implementing adapter methods.",
            "limited_safe_work": (
                "A future interface-only skeleton may be planned after docs are reviewed, but it must not contain "
                "send, cancel, blocklist, dashboard, Shopify tag, Gmail, or Trustpilot write behavior."
            ),
        },
        "privacy_and_secret_policy": {
            "env_presence_boolean_only": True,
            "env_values_read": False,
            "env_values_reported": False,
            "dotenv_file_read": False,
            "secret_file_read": False,
            "raw_customer_email_reported": False,
            "api_key_value_reported": False,
            "authorization_header_reported": False,
            "local_evidence_snippets_sanitized": True,
        },
        "safety_summary": safety_flags,
        **safety_flags,
        "post_put_patch_delete_performed": False,
        "requests_post_performed": False,
        "requests_put_performed": False,
        "requests_patch_performed": False,
        "requests_delete_performed": False,
        "review_request_send_endpoint_called": False,
        "blocklist_write_endpoint_called": False,
        "cancel_request_endpoint_called": False,
        "no_write_actions_confirmed": True,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "Ali Reviews / Kudosi Phase 5.0 API capabilities remain blocked because vendor docs/endpoints for "
            "send, status, dashboard, cancel, and blocklist automation were not found locally."
        ),
        "duration_seconds": duration_seconds,
        "json_ali_reviews_api_capability_discovery_path": str(REPORT_JSON_PATH),
        "html_ali_reviews_api_capability_discovery_path": str(REPORT_HTML_PATH),
    }


def _recommended_next_steps() -> dict:
    support_questions = [
        "Do you provide an API endpoint to create or trigger a review request for a Shopify order?",
        "Do you provide an API endpoint to query whether a review request has already been sent or scheduled?",
        "Can Request Dashboard records be read through an API or export endpoint?",
        "Can a scheduled review request be cancelled through an API?",
        "Can customers be added to and removed from the blocklist through an API?",
        "Can API queries filter by Shopify order ID, Shopify order name, customer email, and Shopify customer ID?",
        "What authentication method, scopes, rate limits, and webhook events are available for these endpoints?",
    ]
    return {
        "ask_ali_reviews_support": support_questions,
        "endpoints_required_for_full_automation": [
            "create/send review request",
            "query request status",
            "list dashboard records",
            "cancel scheduled request",
            "blocklist add/remove",
        ],
        "proceed_or_wait": "must_wait_for_vendor_api_docs",
        "reason": (
            "Local code/docs only show general Kudosi/Ali Reviews references and an existing read-only reviews "
            "probe pattern. They do not confirm the Request Dashboard, send/status, cancel, or blocklist APIs "
            "needed to avoid manual management."
        ),
    }


def _safety_flags() -> dict:
    return {
        "ali_reviews_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_review_request_send_performed": False,
        "ali_reviews_write_api_call_performed": False,
        "ali_reviews_blocklist_write_performed": False,
        "ali_reviews_cancel_request_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "tagsAdd_performed": False,
        "tagsRemove_performed": False,
        "trustpilot_api_call_performed": False,
        "tracking_redirect_enabled": False,
        "tracking_token_generated": False,
        "translations_register_called": False,
        "translations_register_performed": False,
    }


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    capability_summary = payload["capability_summary"]
    local_scan = payload["local_reference_scan"]
    env_presence = payload["env_var_presence"]
    safety = payload["safety_summary"]
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_ali_reviews_api_capability_discovery_path": str(json_path),
        "html_ali_reviews_api_capability_discovery_path": str(html_path),
        "ali_reviews_api_capability_discovery_status": payload["ali_reviews_api_capability_discovery_status"],
        "capability_count": capability_summary["total_capabilities_checked"],
        "capability_confirmed_count": capability_summary["confirmed_count"],
        "capability_safe_to_implement_now_count": capability_summary["safe_to_implement_now_count"],
        "blocked_missing_api_docs_count": capability_summary["blocked_missing_api_docs_count"],
        "env_var_checked_count": env_presence["checked_count"],
        "env_var_present_count": env_presence["present_count"],
        "local_reference_files_scanned": local_scan["files_scanned"],
        "local_reference_files_with_matches_count": local_scan["files_with_matches_count"],
        "local_reference_evidence_items_returned": local_scan["evidence_items_returned"],
        "read_only_probe_pattern_found": payload["existing_read_only_probe_pattern"]["found"],
        "network_probe_performed": payload["network_probe"]["performed"],
        **safety,
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(payload, report_file, ensure_ascii=True, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    capabilities = "\n".join(
        "<tr>"
        f"<td>{escape(item['capability'])}</td>"
        f"<td>{escape(item['status'])}</td>"
        f"<td>{escape(item['evidence_source'])}</td>"
        f"<td>{escape(str(item['safe_to_implement_now']))}</td>"
        f"<td>{escape(item['notes'])}</td>"
        "</tr>"
        for item in payload["capability_matrix"]
    )
    env_rows = "\n".join(
        "<tr>"
        f"<td>{escape(name)}</td>"
        f"<td>{escape(str(info['present']))}</td>"
        f"<td>{escape(str(info['value_reported']))}</td>"
        "</tr>"
        for name, info in payload["env_var_presence"]["checked_env_vars"].items()
    )
    evidence_rows = "\n".join(
        "<tr>"
        f"<td>{escape(item['path'])}</td>"
        f"<td>{escape(str(item['line']))}</td>"
        f"<td>{escape(', '.join(item['matched_terms']))}</td>"
        f"<td><code>{escape(item['snippet_sanitized'])}</code></td>"
        "</tr>"
        for item in payload["local_reference_scan"]["evidence"]
    )
    endpoint_rows = "\n".join(
        "<tr>"
        f"<td>{escape(item['endpoint_need'])}</td>"
        f"<td>{escape(item['required_operation'])}</td>"
        f"<td>{escape(', '.join(item['required_filters_or_inputs']))}</td>"
        "</tr>"
        for item in payload["required_vendor_endpoints"]
    )
    safety_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["safety_summary"].items()
    )
    support_questions = "\n".join(
        f"<li>{escape(question)}</li>"
        for question in payload["recommended_next_steps"]["ask_ali_reviews_support"]
    )
    probe = payload["existing_read_only_probe_pattern"]
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Ali Reviews / Kudosi API Capability Discovery</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .blocked {{ border-left: 4px solid #b45309; background: #fffbeb; padding: 10px 12px; }}
  </style>
</head>
<body>
  <h1>Ali Reviews / Kudosi API Capability Discovery</h1>
  <p>Phase: <code>{escape(payload["phase"])}</code></p>
  <p>Mode: <code>{escape(payload["mode"])}</code></p>
  <p>Status: <code>{escape(payload["ali_reviews_api_capability_discovery_status"])}</code></p>
  <p class="blocked">No Ali Reviews / Kudosi request was sent. No write API, blocklist, cancel, Gmail, Shopify, Trustpilot, or tracking action was performed.</p>

  <h2>Capability Matrix</h2>
  <table>
    <thead>
      <tr><th>Capability</th><th>Status</th><th>Evidence Source</th><th>Safe Now</th><th>Notes</th></tr>
    </thead>
    <tbody>{capabilities}</tbody>
  </table>

  <h2>Environment Presence</h2>
  <p>Presence is checked from process environment names only. Values are not read or reported.</p>
  <table>
    <thead><tr><th>Name</th><th>Present</th><th>Value Reported</th></tr></thead>
    <tbody>{env_rows}</tbody>
  </table>

  <h2>Existing Read-Only Probe Pattern</h2>
  <p>Found: <code>{escape(str(probe["found"]))}</code></p>
  <p>Source: <code>{escape(str(probe.get("path", "")))}</code></p>
  <p>Endpoint path: <code>{escape(str(probe.get("endpoint_path", "")))}</code></p>
  <p>Network probe performed: <code>{escape(str(probe["network_probe_performed"]))}</code></p>
  <p>{escape(str(probe["notes"]))}</p>

  <h2>Required Vendor Endpoints</h2>
  <table>
    <thead><tr><th>Need</th><th>Operation</th><th>Inputs / Filters</th></tr></thead>
    <tbody>{endpoint_rows}</tbody>
  </table>

  <h2>Local Evidence</h2>
  <p>Files scanned: {escape(str(payload["local_reference_scan"]["files_scanned"]))}; files with matches: {escape(str(payload["local_reference_scan"]["files_with_matches_count"]))}.</p>
  <table>
    <thead><tr><th>Path</th><th>Line</th><th>Terms</th><th>Sanitized Snippet</th></tr></thead>
    <tbody>{evidence_rows}</tbody>
  </table>

  <h2>Questions For Ali Reviews / Kudosi Support</h2>
  <ul>{support_questions}</ul>

  <h2>Safety Flags</h2>
  <table><tbody>{safety_rows}</tbody></table>
</body>
</html>
"""


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.0 Ali Reviews / Kudosi API capability discovery finished.\n"
        f"Status: {payload['ali_reviews_api_capability_discovery_status']}\n"
        f"Capabilities checked: {payload['capability_summary']['total_capabilities_checked']}\n"
        f"Safe to implement now: {payload['capability_summary']['safe_to_implement_now_count']}\n"
        f"Network probe performed: {payload['network_probe']['performed']}\n"
        "Safety: no Ali Reviews request sent, no Ali Reviews write API, no blocklist write, no cancel request, "
        "no Gmail send, no Shopify write, no Trustpilot API call, and no tracking.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _relative_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(path)


def _sanitize_snippet(text: str) -> str:
    sanitized = CONTROL_RE.sub("", text or "")
    sanitized = EMAIL_RE.sub("[redacted-email]", sanitized)
    sanitized = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted-value]", sanitized)
    sanitized = AUTH_HEADER_RE.sub(lambda match: f"{match.group(1)}[redacted-auth]", sanitized)
    sanitized = TOKEN_VALUE_RE.sub("[redacted-token]", sanitized)
    sanitized = sanitized.strip()
    if len(sanitized) > 240:
        sanitized = sanitized[:237] + "..."
    return sanitized
