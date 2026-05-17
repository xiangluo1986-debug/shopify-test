import json
import re
import subprocess
import time
from html import escape

from remote_approval.utils import LOG_DIR, PROJECT_ROOT, utc_now_iso


TASK_NAME = "shopify_review_request_review_send_failure_audit"
COMMAND_LABEL = TASK_NAME
REPORT_JSON_PATH = LOG_DIR / "shopify_review_request_review_send_failure_audit.json"
REPORT_HTML_PATH = LOG_DIR / "shopify_review_request_review_send_failure_audit.html"
REVIEW_SEND_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_review_and_send_execute.json"
LAST_60_SCAN_JSON_PATH = LOG_DIR / "shopify_review_request_last_60_days_candidate_scan.json"
SCOPE_RESOLVER_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_scope_compatibility_resolver.json"
ENV_LOADING_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_env_loading_audit.json"
OAUTH_CONFIG_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_oauth_config_helper.json"
CONFIG_COMPAT_JSON_PATH = LOG_DIR / "shopify_review_request_trustpilot_gmail_config_compatibility_audit.json"
TIMEOUT_SECONDS = 180
JSON_BEGIN = "SHOPIFY_REVIEW_REQUEST_REVIEW_SEND_FAILURE_AUDIT_JSON_BEGIN"
JSON_END = "SHOPIFY_REVIEW_REQUEST_REVIEW_SEND_FAILURE_AUDIT_JSON_END"

EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
SECRET_RE = re.compile(
    r"(?i)(bearer\s+[A-Za-z0-9._-]{8,}|ya29\.[A-Za-z0-9._-]+|shpat_[A-Za-z0-9_]+|"
    r"access[_\s-]?token\s*[:=]|refresh[_\s-]?token\s*[:=]|client[_\s-]?secret\s*[:=]|"
    r"api[_\s-]?key\s*[:=]|password\s*[:=]|secret\s*[:=])"
)


def run_shopify_review_request_review_send_failure_audit_task(mode: str) -> dict:
    if mode != "dry-run":
        raise ValueError(f"{TASK_NAME} only supports dry-run mode.")

    started = time.time()
    completed = _run_django_local_audit()
    if completed["success"]:
        payload = completed["payload"]
        payload["django_audit_source"] = "django"
    else:
        payload = _fallback_payload(completed)
    payload["duration_seconds"] = round(time.time() - started, 3)
    payload["privacy_scan_summary"] = _privacy_scan(payload)

    json_path = _write_json(payload)
    html_path = _write_html(payload)
    return _task_result(payload, json_path, html_path)


def _run_django_local_audit() -> dict:
    script = (
        "import json; "
        "from shopify_sync.review_request_workbench import "
        "build_review_request_review_send_failure_audit_report; "
        "payload = build_review_request_review_send_failure_audit_report({}); "
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
    return {"success": True, "exit_code": 0, "payload": payload}


def _extract_payload(stdout: str) -> dict:
    if JSON_BEGIN not in stdout or JSON_END not in stdout:
        return {}
    fragment = stdout.split(JSON_BEGIN, 1)[1].split(JSON_END, 1)[0].strip()
    try:
        payload = json.loads(fragment)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _fallback_payload(result: dict) -> dict:
    latest_attempt = _load_json(REVIEW_SEND_JSON_PATH)
    last_scan = _load_json(LAST_60_SCAN_JSON_PATH)
    gmail_status = _fallback_gmail_status()
    order_diagnosis = last_scan.get("order_21075_diagnosis") if isinstance(last_scan, dict) else {}
    order_diagnosis = order_diagnosis if isinstance(order_diagnosis, dict) else {}
    latest_order = _safe_text(latest_attempt.get("selected_order") or latest_attempt.get("target_order"))
    latest_matches = latest_order == "#21075"
    latest_message = _safe_text(
        latest_attempt.get("exact_user_message")
        or latest_attempt.get("blocking_detail")
        or latest_attempt.get("detected_issue_summary"),
        max_length=400,
    )
    candidate_found = order_diagnosis.get("found_in_local_shopify_order") is True
    candidate_currently_eligible = order_diagnosis.get("final_eligibility_status") == "eligible"
    customer_history_confirmed = (
        order_diagnosis.get("customer_history_confirmed") is True
        or candidate_currently_eligible
        or _safe_text(order_diagnosis.get("customer_history_confidence"))
        in {"high", "medium"}
    )
    prior_trustpilot_found = bool(order_diagnosis.get("previous_trustpilot_order_names"))
    note_risk_found = order_diagnosis.get("note_risk_detected") is True
    blocked_reason, exact_user_message, recommended_fix = _fallback_diagnosis_message(
        candidate_found=candidate_found,
        candidate_currently_eligible=candidate_currently_eligible,
        customer_history_confirmed=customer_history_confirmed,
        prior_trustpilot_found=prior_trustpilot_found,
        note_risk_found=note_risk_found,
        gmail_status=gmail_status,
        latest_message=latest_message,
    )
    return {
        "timestamp": utc_now_iso(),
        "report_generated_at": utc_now_iso(),
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "phase": "5.28K",
        "mode": "dry-run-local-review-send-failure-audit-fallback",
        "review_send_failure_audit_status": "review_send_failure_audit_ready_from_fallback",
        "report_status": "review_send_failure_audit_ready_from_fallback",
        "success": True,
        "django_failure_type": _safe_text(result.get("failure_type")),
        "django_exit_code": int(result.get("exit_code") or 1),
        "stdout_tail_sanitized": _tail(result.get("stdout", "")),
        "stderr_tail_sanitized": _tail(result.get("stderr", "")),
        "target_order": "#21075",
        "candidate_found": candidate_found,
        "candidate_currently_eligible": candidate_currently_eligible,
        "customer_history_confirmed": customer_history_confirmed,
        "prior_trustpilot_found": prior_trustpilot_found,
        "note_risk_found": note_risk_found,
        "gmail_scope_status": gmail_status["gmail_scope_status"],
        "gmail_scope_missing": gmail_status["gmail_scope_missing"],
        "gmail_scope_compose_only": gmail_status["gmail_scope_compose_only"],
        "gmail_send_path_requires_gmail_send": False,
        "gmail_send_permission_ready": gmail_status["gmail_send_permission_ready"],
        "gmail_helper_ready": gmail_status["gmail_helper_ready"],
        "gmail_credentials_missing": gmail_status["gmail_credentials_missing"],
        "direct_send_supported_by_current_helper": False,
        "draft_send_supported_by_existing_locked_helper": True,
        "previous_gmail_draft_send_helper_found": True,
        "helper_module": (
            "remote_approval.tasks.shopify_review_request_trustpilot_gmail_one_draft_send_execute_task"
        ),
        "helper_supports_dynamic_order": False,
        "helper_requires_remote_approval_runner": True,
        "can_be_called_from_admin_post": False,
        "drafts_send_path_available": True,
        "blocker_if_not_reusable": (
            "Previous #22621 drafts.send helper is hard-coded to #22621 and a fixed draft identity; "
            "it cannot create or send for a dynamic admin-selected order."
        ),
        "blocked_reason": blocked_reason,
        "exact_user_message": exact_user_message,
        "recommended_fix": recommended_fix,
        "latest_review_send_attempt_found": bool(latest_attempt),
        "latest_review_send_attempt_matches_target": latest_matches,
        "latest_review_send_attempt_message": latest_message,
        "gmail_api_call_performed": False,
        "email_sent": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "shopify_tag_write_performed": False,
        "mutation_performed": False,
        "tags_add_performed": False,
        "tags_remove_performed": False,
        "external_review_api_call_performed": False,
        "trustpilot_api_call_performed": False,
        "kudosi_api_call_performed": False,
        "ali_reviews_api_call_performed": False,
        "translations_register_called": False,
        "raw_customer_email_output": False,
        "full_note_output": False,
        "secrets_output": False,
        "all_new_actions_no_write_confirmed": True,
        "detected_issue_summary": (
            "#21075 Review & Send audit used fallback data. No Gmail API call, email send, "
            "Shopify write, Trustpilot/Kudosi/Ali Reviews API call, or translationsRegister call was performed."
        ),
    }


def _failed_run(failure_type: str, exit_code: int, stdout: str, stderr: str) -> dict:
    return {
        "success": False,
        "exit_code": exit_code,
        "failure_type": failure_type,
        "stdout": _sanitize_text(stdout),
        "stderr": _sanitize_text(stderr),
    }


def _load_json(path):
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8", errors="replace"), strict=False)
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _fallback_gmail_status() -> dict:
    scope_resolver = _load_json(SCOPE_RESOLVER_JSON_PATH)
    env_loading = _load_json(ENV_LOADING_JSON_PATH)
    oauth_config = _load_json(OAUTH_CONFIG_JSON_PATH)
    compatibility = _load_json(CONFIG_COMPAT_JSON_PATH)
    send_scope = (
        scope_resolver.get("send_scope_available") is True
        or scope_resolver.get("real_send_scope_available") is True
        or env_loading.get("os_environ_send_scope_detected") is True
        or oauth_config.get("gmail_send_scope_present") is True
        or compatibility.get("gmail_send_scope_present") is True
    )
    compose_scope = (
        scope_resolver.get("compose_scope_available") is True
        or env_loading.get("os_environ_compose_scope_detected") is True
        or oauth_config.get("gmail_compose_scope_present") is True
        or compatibility.get("gmail_compose_scope_present") is True
    )
    broad_scope = (
        scope_resolver.get("broad_mail_scope_available") is True
        or env_loading.get("os_environ_broad_mail_scope_detected") is True
        or oauth_config.get("gmail_broad_mail_scope_present") is True
    )
    if broad_scope or send_scope:
        scope_status = "gmail_send_scope_available"
    elif compose_scope:
        scope_status = "gmail_compose_only"
    else:
        scope_status = _safe_text(
            scope_resolver.get("scope_resolver_status")
            or env_loading.get("env_loading_audit_status")
            or "scope_missing",
            max_length=120,
        )
    dependencies_ready = (
        oauth_config.get("gmail_dependencies_importable") is True
        or compatibility.get("gmail_dependencies_importable") is True
    )
    credentials_ready = (
        (
            oauth_config.get("gmail_oauth_client_secret_path_exists") is True
            and oauth_config.get("gmail_oauth_token_path_exists") is True
        )
        or oauth_config.get("legacy_gmail_oauth_config_present") is True
        or compatibility.get("legacy_gmail_oauth_config_present") is True
    )
    return {
        "gmail_scope_status": scope_status,
        "gmail_scope_missing": scope_status in {"scope_missing", "gmail_scope_not_configured_anywhere_detected"},
        "gmail_scope_compose_only": scope_status == "gmail_compose_only",
        "gmail_send_permission_ready": bool(send_scope or broad_scope),
        "gmail_helper_ready": bool(dependencies_ready and credentials_ready),
        "gmail_credentials_missing": not credentials_ready,
    }


def _fallback_diagnosis_message(
    candidate_found: bool,
    candidate_currently_eligible: bool,
    customer_history_confirmed: bool,
    prior_trustpilot_found: bool,
    note_risk_found: bool,
    gmail_status: dict,
    latest_message: str,
) -> tuple[str, str, str]:
    if not candidate_found:
        return (
            "candidate no longer eligible",
            "No email was sent. This order is no longer eligible.",
            "Refresh the queue and re-run the candidate scan if #21075 should still qualify.",
        )
    if not candidate_currently_eligible:
        return (
            "candidate no longer eligible",
            "No email was sent. This order is no longer eligible.",
            "Review #21075's current candidate status before retrying.",
        )
    if not customer_history_confirmed:
        return (
            "customer history changed",
            "No email was sent. Customer history not confirmed.",
            "Confirm repeat-customer history before retrying Review & Send.",
        )
    if prior_trustpilot_found:
        return (
            "already sent",
            "No email was sent. Already sent Trustpilot to this customer.",
            "Do not send another Trustpilot email unless a separate manual exception is approved.",
        )
    if note_risk_found:
        return (
            "risk blocker",
            "No email was sent. Aftersales/ticket note found.",
            "Manually review ticket or note risk before any customer-facing email.",
        )
    if gmail_status["gmail_scope_compose_only"]:
        return (
            "Previous Gmail helper not reusable",
            "No email was sent. The previous Gmail send helper is not reusable from this admin action yet.",
            "Run the helper reuse audit and build a reviewed dynamic drafts.create plus drafts.send path.",
        )
    if not gmail_status["gmail_send_permission_ready"]:
        return (
            "Gmail scope missing",
            latest_message or "No email was sent. Gmail compose/send permission is missing.",
            "Configure Gmail compose permission for the reviewed drafts.create plus drafts.send path.",
        )
    if not gmail_status["gmail_helper_ready"]:
        return (
            "Gmail helper not configured",
            "No email was sent. The Gmail send helper is not ready.",
            "Configure Gmail OAuth helper readiness without exposing secret values.",
        )
    return (
        "Previous Gmail helper not reusable",
        "No email was sent. The previous Gmail send helper is not reusable from this admin action yet.",
        "Enable a reviewed dynamic draft-create plus drafts.send helper before retrying Review & Send.",
    )


def _write_json(payload: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_JSON_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return REPORT_JSON_PATH


def _write_html(payload: dict):
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")
    return REPORT_HTML_PATH


def _render_html(payload: dict) -> str:
    rows = "\n".join(
        f"<tr><th>{escape(label)}</th><td>{escape(str(value))}</td></tr>"
        for label, value in (
            ("Target order", payload.get("target_order")),
            ("Candidate found", payload.get("candidate_found")),
            ("Currently eligible", payload.get("candidate_currently_eligible")),
            ("Gmail scope status", payload.get("gmail_scope_status")),
            ("Send permission ready", payload.get("gmail_send_permission_ready")),
            ("Gmail helper ready", payload.get("gmail_helper_ready")),
            ("Blocked reason", payload.get("blocked_reason")),
            ("Exact user message", payload.get("exact_user_message")),
            ("Gmail API call performed", payload.get("gmail_api_call_performed")),
            ("Email sent", payload.get("email_sent")),
            ("Shopify write performed", payload.get("shopify_write_performed")),
        )
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Review &amp; Send Failure Audit</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; color: #1f2933; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #d9e2ec; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ width: 260px; background: #f0f4f8; }}
  </style>
</head>
<body>
  <h1>Review &amp; Send Failure Audit</h1>
  <p>Status: <strong>{escape(str(payload.get("review_send_failure_audit_status", "")))}</strong></p>
  <table><tbody>{rows}</tbody></table>
</body>
</html>"""


def _task_result(payload: dict, json_path, html_path) -> dict:
    return {
        "task_type": TASK_NAME,
        "success": payload.get("success") is True,
        "review_path": str(json_path),
        "html_review_path": str(html_path),
        "target_order": payload.get("target_order"),
        "blocked_reason": payload.get("blocked_reason"),
        "exact_user_message": payload.get("exact_user_message"),
        "gmail_scope_status": payload.get("gmail_scope_status"),
        "gmail_api_call_performed": payload.get("gmail_api_call_performed") is True,
        "email_sent": payload.get("email_sent") is True,
        "shopify_write_performed": payload.get("shopify_write_performed") is True,
        "approval_message": _build_approval_message(payload, json_path, html_path),
    }


def _build_approval_message(payload: dict, json_path, html_path) -> str:
    return (
        "Review & Send failure audit complete.\n"
        f"Target order: {payload.get('target_order')}\n"
        f"Blocked reason: {payload.get('blocked_reason')}\n"
        f"Message: {payload.get('exact_user_message')}\n"
        f"Gmail scope: {payload.get('gmail_scope_status')}\n"
        f"Gmail API call performed: {payload.get('gmail_api_call_performed')}\n"
        f"Email sent: {payload.get('email_sent')}\n"
        f"Shopify write performed: {payload.get('shopify_write_performed')}\n"
        f"JSON: {json_path}\n"
        f"HTML: {html_path}"
    )


def _privacy_scan(payload: dict) -> dict:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw_emails = [match.group(0) for match in EMAIL_RE.finditer(text) if "***" not in match.group(0)]
    return {
        "scan_performed": True,
        "passed": not raw_emails and not SECRET_RE.search(text),
        "raw_customer_email_count": len(set(raw_emails)),
        "token_secret_bearer_pattern_count": 1 if SECRET_RE.search(text) else 0,
    }


def _to_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _safe_text(value, max_length=300):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    text = EMAIL_RE.sub("[masked-email]", text)
    text = SECRET_RE.sub("[redacted]", text)
    return text[:max_length]


def _sanitize_text(value):
    return _safe_text(value, max_length=2000)


def _tail(value, max_length=1200):
    text = _sanitize_text(value)
    return text[-max_length:]
