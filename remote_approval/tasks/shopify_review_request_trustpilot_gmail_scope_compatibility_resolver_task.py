import json
import os
import re
import time
from html import escape
from pathlib import Path

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver"
COMMAND_LABEL = TASK_NAME
PHASE = "5.18B"

REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.html"

LEGACY_SCOPE_ENV = "GOOGLE_GMAIL_SCOPES"
NEW_SCOPE_ENV = "GMAIL_REQUIRED_SCOPE"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
BROAD_MAIL_SCOPE = "https://mail.google.com/"

ENV_EXAMPLE_PATH = PROJECT_ROOT / ".env.example"
HELPER_TASK_PATH = (
    PROJECT_ROOT
    / "remote_approval"
    / "tasks"
    / "shopify_review_request_trustpilot_gmail_oauth_config_helper_task.py"
)

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
BEARER_TOKEN_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._-]{8,}")
ACCESS_TOKEN_VALUE_RE = re.compile(r"(?i)\baccess[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
REFRESH_TOKEN_VALUE_RE = re.compile(r"(?i)\brefresh[_-]?token\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
CLIENT_SECRET_VALUE_RE = re.compile(r"(?i)\bclient[_-]?secret\b\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}")
PRIVATE_KEY_RE = re.compile(r"(?i)-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----|\bprivate_key\b\s*[:=]")
FULL_GMAIL_ID_RE = re.compile(r"(?i)\"(?:gmail_)?(?:draft|message)_id\"\s*:\s*\"[A-Za-z0-9_-]{16,}\"")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
SECRET_VALUE_RE = re.compile(
    r"(?i)("
    r"shpat_[A-Za-z0-9_]+|"
    r"ya29\.[A-Za-z0-9._-]+|"
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"x-shopify-access-token\s*[:=]\s*[A-Za-z0-9._-]+|"
    r"access[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"refresh[_\s-]?token\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"client[_\s-]?secret\s*[:=]\s*['\"]?[A-Za-z0-9._/-]{12,}|"
    r"private_key\s*[:=]\s*['\"]?[^,'\"]+"
    r")"
)
ALLOWED_EMAILS = {"info@kidstoylover.com"}
ALLOWED_EMAIL_DOMAINS = {"example.invalid"}


def run_shopify_review_request_trustpilot_gmail_scope_compatibility_resolver_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    legacy_summary = _scope_env_summary(LEGACY_SCOPE_ENV, "legacy")
    new_summary = _scope_env_summary(NEW_SCOPE_ENV, "new")
    decision = _scope_decision(legacy_summary, new_summary)
    generated_at = utc_now_iso()
    payload = {
        "timestamp": generated_at,
        "report_generated_at": generated_at,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": PHASE,
        "channel": "trustpilot",
        "mode": "gmail-scope-compatibility-resolver",
        "dry_run": True,
        "resolver_only": True,
        "command_label": COMMAND_LABEL,
        "success": True,
        "scope_resolver_status": decision["scope_resolver_status"],
        "scope_compatibility_status": decision["scope_resolver_status"],
        "legacy_scope_env_present": legacy_summary["env_present"],
        "new_scope_env_present": new_summary["env_present"],
        "legacy_scope_recognized_summary": legacy_summary,
        "new_scope_recognized_summary": new_summary,
        "legacy_new_scope_comparison": _scope_source_comparison(legacy_summary, new_summary),
        "compose_scope_available": decision["compose_scope_available"],
        "send_scope_available": decision["send_scope_available"],
        "broad_mail_scope_available": decision["broad_mail_scope_available"],
        "draft_only_mode": decision["draft_only_mode"],
        "real_send_scope_available": decision["real_send_scope_available"],
        "future_real_send_scope_blocker": decision["future_real_send_scope_blocker"],
        "compatibility_recommendation": decision["compatibility_recommendation"],
        "warnings": decision["warnings"],
        "env_example_scope_placeholder_summary": _env_example_scope_placeholder_summary(),
        "helper_task_scope_constant_summary": _helper_task_scope_constant_summary(),
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "gmail_draft_update_performed": False,
        "gmail_draft_delete_performed": False,
        "gmail_drafts_send_called": False,
        "gmail_messages_send_called": False,
        "token_file_read": False,
        "credential_file_read": False,
        "secret_value_printed": False,
        "dotenv_read": False,
        "scope_values_reported": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "privacy_scan_summary": _empty_privacy_scan_summary(),
        "next_admin_action": decision["next_admin_action"],
        "dashboard_message": decision["dashboard_message"],
        "safety_message": (
            "No Gmail network/API call was made. No email was sent. No Gmail draft was created."
        ),
        "report_paths": {
            "json": f"logs/{REPORT_JSON_PATH.name}",
            "html": f"logs/{REPORT_HTML_PATH.name}",
        },
        "duration_seconds": round(time.time() - started, 3),
        "detected_issue_summary": decision["detected_issue_summary"],
    }
    payload["privacy_scan_summary"] = _privacy_scan_for_payload(payload)
    if not payload["privacy_scan_summary"]["passed"]:
        payload["scope_resolver_status"] = "blocked_privacy_scan_failed"
        payload["scope_compatibility_status"] = "blocked_privacy_scan_failed"
        payload["future_real_send_scope_blocker"] = True
        payload["real_send_scope_available"] = False
        payload["compatibility_recommendation"] = (
            "Generated report privacy scan failed. Review counts only; do not use this report for approval."
        )
        payload["next_admin_action"] = "Inspect the privacy scan counters before rerunning the resolver."
    payload = _safe_payload(payload)
    json_path = _write_json_report(payload)
    html_path = _write_html_report(payload)
    return _task_result(payload, json_path, html_path)


def _scope_env_summary(env_name: str, style: str) -> dict:
    raw_value = os.environ.get(env_name, "")
    scopes = _split_scopes(raw_value)
    send_present = GMAIL_SEND_SCOPE in scopes
    compose_present = GMAIL_COMPOSE_SCOPE in scopes
    broad_present = BROAD_MAIL_SCOPE in scopes
    recognized_count = sum(1 for present in (send_present, compose_present, broad_present) if present)
    return {
        "style": style,
        "env_name": env_name,
        "env_present": bool(raw_value.strip()),
        "scope_configured": bool(scopes),
        "recognized_scope_count": recognized_count,
        "unrecognized_scope_count": max(len(scopes) - recognized_count, 0),
        "gmail_compose_scope_present": compose_present,
        "gmail_send_scope_present": send_present,
        "broad_mail_scope_present": broad_present,
        "scope_compatibility_status": _single_scope_status(send_present, broad_present, compose_present),
        "process_environment_only": True,
        "scope_value_reported": False,
        "secret_value_reported": False,
    }


def _split_scopes(raw_value: str) -> set[str]:
    return {item.strip() for item in re.split(r"[\s,;]+", raw_value or "") if item.strip()}


def _single_scope_status(send_present: bool, broad_present: bool, compose_present: bool) -> str:
    if send_present:
        return "gmail_send_scope_available"
    if broad_present:
        return "broad_mail_scope_available"
    if compose_present:
        return "gmail_compose_only"
    return "scope_missing"


def _scope_decision(legacy_summary: dict, new_summary: dict) -> dict:
    send_present = (
        legacy_summary["gmail_send_scope_present"] or new_summary["gmail_send_scope_present"]
    )
    broad_present = (
        legacy_summary["broad_mail_scope_present"] or new_summary["broad_mail_scope_present"]
    )
    compose_present = (
        legacy_summary["gmail_compose_scope_present"] or new_summary["gmail_compose_scope_present"]
    )
    if send_present:
        return {
            "scope_resolver_status": "gmail_send_scope_available",
            "compose_scope_available": compose_present,
            "send_scope_available": True,
            "broad_mail_scope_available": broad_present,
            "draft_only_mode": False,
            "real_send_scope_available": True,
            "future_real_send_scope_blocker": False,
            "warnings": _broad_scope_warning(broad_present),
            "dashboard_message": (
                "Gmail send permission is available. Final approval is still required before sending."
            ),
            "compatibility_recommendation": (
                "Configured Gmail scope includes gmail.send. Keep the future real-send path locked "
                "behind final human approval."
            ),
            "next_admin_action": (
                "Rerun helper/readiness checks and keep real sending disabled until a later approved phase."
            ),
            "detected_issue_summary": (
                "Gmail send scope is available from configured scope env names. No Gmail API call was made."
            ),
        }
    if broad_present:
        return {
            "scope_resolver_status": "broad_mail_scope_available",
            "compose_scope_available": compose_present,
            "send_scope_available": False,
            "broad_mail_scope_available": True,
            "draft_only_mode": False,
            "real_send_scope_available": True,
            "future_real_send_scope_blocker": False,
            "warnings": _broad_scope_warning(True),
            "dashboard_message": (
                "Gmail send permission is available through a broad mail scope. Final approval is still required before sending."
            ),
            "compatibility_recommendation": (
                "Broad mail scope can support real sending, but prefer least-privilege gmail.send if possible."
            ),
            "next_admin_action": (
                "Review whether broad Gmail mail scope is intentional; prefer gmail.send for least privilege."
            ),
            "detected_issue_summary": (
                "Broad Gmail mail scope was detected from configured scope env names. No Gmail API call was made."
            ),
        }
    if compose_present:
        return {
            "scope_resolver_status": "gmail_compose_only",
            "compose_scope_available": True,
            "send_scope_available": False,
            "broad_mail_scope_available": False,
            "draft_only_mode": True,
            "real_send_scope_available": False,
            "future_real_send_scope_blocker": True,
            "warnings": [],
            "dashboard_message": (
                "Gmail can prepare drafts, but direct sending needs extra permission."
            ),
            "compatibility_recommendation": (
                "Existing config can support draft creation, but direct automatic sending requires gmail.send scope."
            ),
            "next_admin_action": (
                "Use draft creation/manual send for compose-only OAuth, or upgrade OAuth to gmail.send "
                "before any future direct-send phase."
            ),
            "detected_issue_summary": (
                "Only Gmail compose scope was detected. Draft preparation is possible; direct send remains blocked."
            ),
        }
    return {
        "scope_resolver_status": "scope_missing",
        "compose_scope_available": False,
        "send_scope_available": False,
        "broad_mail_scope_available": False,
        "draft_only_mode": False,
        "real_send_scope_available": False,
        "future_real_send_scope_blocker": True,
        "warnings": [],
        "dashboard_message": "Gmail permission is not configured yet.",
        "compatibility_recommendation": (
            "Configure Gmail scope explicitly. Use gmail.compose for draft-only workflows or gmail.send "
            "for a future direct-send workflow after approval."
        ),
        "next_admin_action": (
            f"Set {NEW_SCOPE_ENV} or legacy {LEGACY_SCOPE_ENV} to an approved Gmail scope before "
            "any future Gmail workflow."
        ),
        "detected_issue_summary": (
            "No recognized Gmail scope was detected from configured scope env names. No Gmail API call was made."
        ),
    }


def _broad_scope_warning(broad_present: bool) -> list[str]:
    if not broad_present:
        return []
    return ["Broad mail scope detected; prefer least-privilege gmail.send if possible."]


def _scope_source_comparison(legacy_summary: dict, new_summary: dict) -> str:
    legacy_present = legacy_summary["env_present"]
    new_present = new_summary["env_present"]
    if legacy_present and new_present:
        if legacy_summary["scope_compatibility_status"] == new_summary["scope_compatibility_status"]:
            return "legacy_and_new_scope_sources_match"
        return "legacy_and_new_scope_sources_differ"
    if legacy_present:
        return "legacy_scope_source_only"
    if new_present:
        return "new_scope_source_only"
    return "both_scope_sources_missing"


def _env_example_scope_placeholder_summary() -> dict:
    summary = {
        "path": ".env.example",
        "present": ENV_EXAMPLE_PATH.exists(),
        "file_read": False,
        "values_reported": False,
        "scope_env_names_checked": [LEGACY_SCOPE_ENV, NEW_SCOPE_ENV],
        "placeholders": {},
    }
    if not ENV_EXAMPLE_PATH.exists():
        return summary
    found = {}
    try:
        for line in ENV_EXAMPLE_PATH.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            key = key.strip()
            if key in {LEGACY_SCOPE_ENV, NEW_SCOPE_ENV}:
                found[key] = _placeholder_scope_summary(value.strip())
    except OSError:
        summary["file_read"] = False
        summary["read_error_sanitized"] = "unable_to_read_env_example"
        return summary
    summary["file_read"] = True
    summary["placeholders"] = {
        name: found.get(
            name,
            {
                "present": False,
                "recognized_scope_count": 0,
                "gmail_compose_scope_present": False,
                "gmail_send_scope_present": False,
                "broad_mail_scope_present": False,
                "value_reported": False,
            },
        )
        for name in (LEGACY_SCOPE_ENV, NEW_SCOPE_ENV)
    }
    return summary


def _placeholder_scope_summary(raw_placeholder: str) -> dict:
    scopes = _split_scopes(raw_placeholder)
    send_present = GMAIL_SEND_SCOPE in scopes
    compose_present = GMAIL_COMPOSE_SCOPE in scopes
    broad_present = BROAD_MAIL_SCOPE in scopes
    return {
        "present": True,
        "recognized_scope_count": sum(1 for present in (send_present, compose_present, broad_present) if present),
        "gmail_compose_scope_present": compose_present,
        "gmail_send_scope_present": send_present,
        "broad_mail_scope_present": broad_present,
        "value_reported": False,
    }


def _helper_task_scope_constant_summary() -> dict:
    summary = {
        "path": "remote_approval/tasks/shopify_review_request_trustpilot_gmail_oauth_config_helper_task.py",
        "present": HELPER_TASK_PATH.exists(),
        "file_read": False,
        "values_reported": False,
        "legacy_scope_env_name_detected": False,
        "new_scope_env_name_detected": False,
        "compose_scope_constant_detected": False,
        "send_scope_constant_detected": False,
        "broad_mail_scope_constant_detected": False,
    }
    if not HELPER_TASK_PATH.exists():
        return summary
    try:
        text = HELPER_TASK_PATH.read_text(encoding="utf-8", errors="replace")
    except OSError:
        summary["read_error_sanitized"] = "unable_to_read_helper_task"
        return summary
    summary.update(
        {
            "file_read": True,
            "legacy_scope_env_name_detected": LEGACY_SCOPE_ENV in text,
            "new_scope_env_name_detected": NEW_SCOPE_ENV in text,
            "compose_scope_constant_detected": GMAIL_COMPOSE_SCOPE in text,
            "send_scope_constant_detected": GMAIL_SEND_SCOPE in text,
            "broad_mail_scope_constant_detected": BROAD_MAIL_SCOPE in text,
        }
    )
    return summary


def _empty_privacy_scan_summary() -> dict:
    return {
        "scan_performed": False,
        "passed": False,
        "raw_email_like_disallowed_count": 0,
        "allowed_placeholder_email_count": 0,
        "bearer_token_count": 0,
        "access_token_value_count": 0,
        "refresh_token_value_count": 0,
        "client_secret_value_count": 0,
        "private_key_pattern_count": 0,
        "full_gmail_id_pattern_count": 0,
        "sensitive_matches_reported": False,
    }


def _privacy_scan_for_payload(payload: dict) -> dict:
    json_text = json.dumps(_safe_payload(payload), ensure_ascii=False, indent=2)
    html_text = _render_html_report(_safe_payload(payload))
    content = f"{json_text}\n{html_text}"
    email_matches = EMAIL_RE.findall(content)
    disallowed_email_count = 0
    allowed_email_count = 0
    for email in email_matches:
        normalized = email.lower()
        domain = normalized.rsplit("@", 1)[-1]
        if normalized in ALLOWED_EMAILS or domain in ALLOWED_EMAIL_DOMAINS:
            allowed_email_count += 1
        else:
            disallowed_email_count += 1
    counts = {
        "raw_email_like_disallowed_count": disallowed_email_count,
        "allowed_placeholder_email_count": allowed_email_count,
        "bearer_token_count": len(BEARER_TOKEN_RE.findall(content)),
        "access_token_value_count": len(ACCESS_TOKEN_VALUE_RE.findall(content)),
        "refresh_token_value_count": len(REFRESH_TOKEN_VALUE_RE.findall(content)),
        "client_secret_value_count": len(CLIENT_SECRET_VALUE_RE.findall(content)),
        "private_key_pattern_count": len(PRIVATE_KEY_RE.findall(content)),
        "full_gmail_id_pattern_count": len(FULL_GMAIL_ID_RE.findall(content)),
    }
    passed = all(value == 0 for key, value in counts.items() if key != "allowed_placeholder_email_count")
    return {
        "scan_performed": True,
        "passed": passed,
        **counts,
        "sensitive_matches_reported": False,
    }


def _write_json_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with REPORT_JSON_PATH.open("w", encoding="utf-8") as report_file:
        json.dump(_safe_payload(payload), report_file, ensure_ascii=False, indent=2)
        report_file.write("\n")
    return REPORT_JSON_PATH


def _write_html_report(payload: dict) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html_report(_safe_payload(payload)), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html_report(payload: dict) -> str:
    status_class = (
        "ok"
        if payload["scope_resolver_status"] in {"gmail_send_scope_available", "broad_mail_scope_available"}
        else "warn"
    )
    legacy_rows = _scope_summary_rows(payload["legacy_scope_recognized_summary"])
    new_rows = _scope_summary_rows(payload["new_scope_recognized_summary"])
    warning_rows = "".join(f"<li>{escape(str(item))}</li>" for item in payload.get("warnings", []))
    if not warning_rows:
        warning_rows = "<li>No scope warnings recorded.</li>"
    privacy_rows = "\n".join(
        f"<tr><th>{escape(str(key))}</th><td>{escape(str(value))}</td></tr>"
        for key, value in payload["privacy_scan_summary"].items()
    )
    helper_summary = payload.get("helper_task_scope_constant_summary") or {}
    env_example_summary = payload.get("env_example_scope_placeholder_summary") or {}
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Trustpilot Gmail Scope Compatibility Resolver</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    code {{ background: #f5f7fa; padding: 1px 4px; }}
    table {{ border-collapse: collapse; margin: 8px 0 24px; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f0f4f8; }}
    .status {{ border-left: 4px solid #d97706; background: #fff7ed; padding: 10px 12px; }}
    .status.ok {{ border-left-color: #16a34a; background: #f0fdf4; }}
  </style>
</head>
<body>
  <h1>Trustpilot Gmail Scope Compatibility Resolver</h1>
  <p class="status {status_class}">Scope resolver status: <strong>{escape(payload["scope_resolver_status"])}</strong></p>
  <p>{escape(payload["dashboard_message"])}</p>
  <p>{escape(payload["compatibility_recommendation"])}</p>
  <p>Mode: <code>{escape(payload["mode"])}</code>. This task checks only the two Gmail scope env names and safe placeholders; it does not call Gmail or read token/credential files.</p>
  <table>
    <tbody>
      <tr><th>Legacy scope env present</th><td>{payload["legacy_scope_env_present"]}</td></tr>
      <tr><th>New scope env present</th><td>{payload["new_scope_env_present"]}</td></tr>
      <tr><th>Compose scope available</th><td>{payload["compose_scope_available"]}</td></tr>
      <tr><th>Send scope available</th><td>{payload["send_scope_available"]}</td></tr>
      <tr><th>Broad mail scope available</th><td>{payload["broad_mail_scope_available"]}</td></tr>
      <tr><th>Draft-only mode</th><td>{payload["draft_only_mode"]}</td></tr>
      <tr><th>Real-send scope available</th><td>{payload["real_send_scope_available"]}</td></tr>
      <tr><th>Future real-send scope blocker</th><td>{payload["future_real_send_scope_blocker"]}</td></tr>
      <tr><th>Gmail network/API/send/draft</th><td>false / false / false / false</td></tr>
      <tr><th>Token or credential file read</th><td>false</td></tr>
      <tr><th>Secret value printed</th><td>false</td></tr>
    </tbody>
  </table>
  <h2>Scope Sources</h2>
  <h3>Legacy</h3>
  <table><tbody>{legacy_rows}</tbody></table>
  <h3>New</h3>
  <table><tbody>{new_rows}</tbody></table>
  <h2>Warnings</h2>
  <ul>{warning_rows}</ul>
  <details>
    <summary>Advanced technical details</summary>
    <p>JSON report: <code>logs/{escape(REPORT_JSON_PATH.name)}</code></p>
    <p>HTML report: <code>logs/{escape(REPORT_HTML_PATH.name)}</code></p>
    <p>Scope comparison: <code>{escape(payload["legacy_new_scope_comparison"])}</code></p>
    <p>.env.example read: {escape(str(env_example_summary.get("file_read") is True))}; values reported: false</p>
    <p>Helper constants read: {escape(str(helper_summary.get("file_read") is True))}; values reported: false</p>
    <p>Next admin action: {escape(payload["next_admin_action"])}</p>
    <h2>Privacy Scan</h2>
    <table><tbody>{privacy_rows}</tbody></table>
  </details>
</body>
</html>"""


def _scope_summary_rows(summary: dict) -> str:
    rows = [
        ("Env name", summary.get("env_name")),
        ("Present", summary.get("env_present")),
        ("Recognized scope count", summary.get("recognized_scope_count")),
        ("Unrecognized scope count", summary.get("unrecognized_scope_count")),
        ("gmail.compose", summary.get("gmail_compose_scope_present")),
        ("gmail.send", summary.get("gmail_send_scope_present")),
        ("mail.google.com", summary.get("broad_mail_scope_present")),
        ("Compatibility", summary.get("scope_compatibility_status")),
        ("Scope value reported", summary.get("scope_value_reported") is True),
    ]
    return "\n".join(
        f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"
        for label, value in rows
    )


def _task_result(payload: dict, json_path: Path, html_path: Path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": True,
        "exit_code": 0,
        "command_label": COMMAND_LABEL,
        "review_path": str(json_path),
        "json_review_path": str(json_path),
        "html_review_path": str(html_path),
        "json_trustpilot_gmail_scope_compatibility_resolver_path": str(json_path),
        "html_trustpilot_gmail_scope_compatibility_resolver_path": str(html_path),
        "scope_resolver_status": payload["scope_resolver_status"],
        "scope_compatibility_status": payload["scope_compatibility_status"],
        "legacy_scope_env_present": payload["legacy_scope_env_present"],
        "new_scope_env_present": payload["new_scope_env_present"],
        "legacy_scope_recognized_summary": payload["legacy_scope_recognized_summary"],
        "new_scope_recognized_summary": payload["new_scope_recognized_summary"],
        "compose_scope_available": payload["compose_scope_available"],
        "send_scope_available": payload["send_scope_available"],
        "broad_mail_scope_available": payload["broad_mail_scope_available"],
        "draft_only_mode": payload["draft_only_mode"],
        "real_send_scope_available": payload["real_send_scope_available"],
        "future_real_send_scope_blocker": payload["future_real_send_scope_blocker"],
        "compatibility_recommendation": payload["compatibility_recommendation"],
        "next_admin_action": payload["next_admin_action"],
        "gmail_network_call_performed": False,
        "gmail_api_call_performed": False,
        "gmail_send_performed": False,
        "gmail_draft_create_performed": False,
        "token_file_read": False,
        "credential_file_read": False,
        "secret_value_printed": False,
        "privacy_scan_summary": payload["privacy_scan_summary"],
        "detected_issue_summary": payload["detected_issue_summary"],
        "approval_message": _approval_message(payload, json_path, html_path),
    }


def _approval_message(payload: dict, json_path: Path, html_path: Path) -> str:
    return (
        "Shopify review request Phase 5.18B Gmail scope compatibility resolver finished.\n"
        f"Scope resolver status: {payload.get('scope_resolver_status')}\n"
        f"Legacy scope env present: {payload.get('legacy_scope_env_present')}\n"
        f"New scope env present: {payload.get('new_scope_env_present')}\n"
        f"Compose scope available: {payload.get('compose_scope_available')}\n"
        f"Send scope available: {payload.get('send_scope_available')}\n"
        f"Broad mail scope available: {payload.get('broad_mail_scope_available')}\n"
        f"Draft-only mode: {payload.get('draft_only_mode')}\n"
        f"Real-send scope available: {payload.get('real_send_scope_available')}\n"
        f"Future real-send scope blocker: {payload.get('future_real_send_scope_blocker')}\n"
        f"Recommendation: {payload.get('compatibility_recommendation')}\n"
        "Safety: no Gmail network/API call, no draft create/update/delete, no send, no token/credential file read, no Shopify write, and no external review API call.\n"
        f"JSON report: {json_path}\n"
        f"HTML report: {html_path}\n\n"
        "Choose next step:\n"
        "1 = keep review files\n"
        "SHOW_LOG = show recent log summary\n"
        "0 = stop"
    )


def _safe_payload(value):
    if isinstance(value, dict):
        return {str(key): _safe_payload(nested) for key, nested in value.items()}
    if isinstance(value, list):
        return [_safe_payload(item) for item in value]
    if isinstance(value, str):
        return _safe_text(value, max_length=4000)
    return value


def _safe_text(value, max_length=300) -> str:
    text = str(value or "")
    text = CONTROL_CHARS_RE.sub(" ", text)
    text = SECRET_VALUE_RE.sub("[redacted]", text)
    text = EMAIL_RE.sub(_safe_email_replacement, text)
    text = " ".join(text.split())
    return text[:max_length]


def _safe_email_replacement(match) -> str:
    email = match.group(0)
    normalized = email.lower()
    domain = normalized.rsplit("@", 1)[-1]
    if normalized in ALLOWED_EMAILS or domain in ALLOWED_EMAIL_DOMAINS:
        return email
    return "[redacted-email]"
