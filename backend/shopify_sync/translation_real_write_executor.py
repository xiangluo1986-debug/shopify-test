import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


REAL_WRITE_EXECUTOR_JSON_PATH = Path(
    "logs/shopify_translation_selected_product_real_write_executor.json"
)
REAL_WRITE_EXECUTOR_HTML_PATH = Path(
    "logs/shopify_translation_selected_product_real_write_executor.html"
)
READY_LOCKED_EXECUTOR_STATUS = "selected_product_translation_locked_executor_shell_ready_for_review"
READY_LOCKED_EXECUTOR_ENTRY_STATUS = "executor_locked_no_shopify_write"
READY_EXECUTION_ENTRY_STATUS = "locked_plan_ready_for_future_phase"
DRY_RUN_EXECUTOR_STATUS = "selected_product_translation_real_write_executor_dry_run_ready"
MANUAL_ACK_PHRASE_REQUIRED = "I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE"
ALLOWED_FIELDS = {"title", "meta_title", "meta_description"}
ALLOWED_LOCALES = {"ja", "de", "fr", "es", "it"}
PLANNED_MUTATION_NAME = "translationsRegister"


def build_selected_product_translation_real_write_executor_dry_run(
    locked_executor_result,
    selected_product_id="",
    manual_ack_text=None,
    mode="dry-run",
    write_reports=True,
):
    locked_executor_result = dict(locked_executor_result or {})
    selected_product_id = str(selected_product_id or "").strip()
    dangerous_ack_present = bool(str(manual_ack_text or "").strip())
    payload = _empty_real_write_executor(
        locked_executor_result,
        selected_product_id=selected_product_id,
        mode=mode,
        dangerous_ack_present=dangerous_ack_present,
    )

    if not locked_executor_result:
        payload["executor_status"] = "blocked_missing_locked_executor_shell_report"
        payload["blocking_conditions"].append("blocked_missing_locked_executor_shell_report")
    elif locked_executor_result.get("executor_status") != READY_LOCKED_EXECUTOR_STATUS:
        payload["executor_status"] = "blocked_locked_executor_shell_not_ready"
        payload["blocking_conditions"].append("blocked_locked_executor_shell_not_ready")
    else:
        _collect_real_write_entries(payload, locked_executor_result)
        payload["blocking_conditions"].extend(
            _locked_executor_safety_blocking_reasons(locked_executor_result)
        )
        payload["blocking_conditions"].extend(_scope_blocking_reasons(payload))
        if payload["entry_count"] == 0:
            payload["executor_status"] = "blocked_no_real_write_executor_entries"
            payload["blocking_conditions"].append("blocked_no_real_write_executor_entries")
        elif payload["blocked_entry_count"]:
            payload["executor_status"] = "blocked_real_write_executor_entry_validation_failed"
            payload["blocking_conditions"].append(
                "blocked_real_write_executor_entry_validation_failed"
            )
        elif payload["blocking_conditions"]:
            payload["executor_status"] = "blocked_real_write_executor_safety_not_confirmed"
        else:
            payload["executor_status"] = DRY_RUN_EXECUTOR_STATUS
            payload["success"] = True

    payload["blocking_conditions"] = _unique(payload["blocking_conditions"])
    payload["timestamp"] = _utc_now()
    payload["generated_at"] = payload["timestamp"]
    payload["real_write_executor_report_path"] = str(REAL_WRITE_EXECUTOR_JSON_PATH)
    payload["json_selected_product_real_write_executor_path"] = str(
        REAL_WRITE_EXECUTOR_JSON_PATH
    )
    payload["html_selected_product_real_write_executor_path"] = str(
        REAL_WRITE_EXECUTOR_HTML_PATH
    )

    if write_reports:
        _write_reports(payload)
    return payload


def _empty_real_write_executor(
    locked_executor_result,
    selected_product_id,
    mode,
    dangerous_ack_present,
):
    product_id = locked_executor_result.get("product_id", "")
    return {
        "success": False,
        "executor_status": "",
        "mode": mode or "dry-run",
        "real_write_executor_only": True,
        "dry_run_only": True,
        "product_id": product_id,
        "selected_product_id": selected_product_id,
        "product_title": locked_executor_result.get("product_title", ""),
        "entry_count": 0,
        "blocked_entry_count": 0,
        "target_locales": list(locked_executor_result.get("target_locales") or []),
        "requested_fields": list(locked_executor_result.get("requested_fields") or []),
        "locked_executor_status": locked_executor_result.get("executor_status", ""),
        "locked_executor_report_path": locked_executor_result.get(
            "executor_report_path",
            "logs/shopify_translation_selected_product_locked_executor_shell.json",
        ),
        "real_write_executor_report_path": str(REAL_WRITE_EXECUTOR_JSON_PATH),
        "real_write_executor_entries": [],
        "real_write_allowed": False,
        "future_write_allowed": False,
        "manual_ack_required": True,
        "manual_ack_phrase_required": MANUAL_ACK_PHRASE_REQUIRED,
        "dangerous_ack_present": dangerous_ack_present,
        "dangerous_ack_effective": False,
        "blocking_conditions": [],
        "existing_translation_overwrite_allowed": False,
        "outdated_translation_overwrite_allowed": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "safety_summary": {
            "real_write_executor_only": True,
            "dry_run_only": True,
            "real_write_allowed": False,
            "future_write_allowed": False,
            "manual_ack_required": True,
            "dangerous_ack_effective": False,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "publish_performed": False,
            "apply_performed": False,
            "real_apply_performed": False,
            "rollback_performed": False,
            "existing_translation_overwrite_allowed": False,
            "outdated_translation_overwrite_allowed": False,
            "no_new_shopify_writes_performed": True,
            "all_new_actions_no_write_confirmed": True,
        },
    }


def _collect_real_write_entries(payload, locked_executor_result):
    for entry in locked_executor_result.get("locked_executor_entries", []):
        real_write_entry = _real_write_entry(entry, payload)
        payload["real_write_executor_entries"].append(real_write_entry)
        if real_write_entry["blocking_reasons"]:
            payload["blocked_entry_count"] += 1
    payload["entry_count"] = len(payload["real_write_executor_entries"])


def _real_write_entry(entry, payload):
    blocking_reasons = _entry_blocking_reasons(entry, payload)
    would_write = not blocking_reasons
    return {
        "product_id": entry.get("product_id", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "digest": entry.get("digest", ""),
        "source_value": entry.get("source_value", ""),
        "proposed_translation": entry.get("proposed_translation", ""),
        "current_translation_state": entry.get("current_translation_state", {}),
        "planned_mutation_name": PLANNED_MUTATION_NAME,
        "planned_resource_id": entry.get("planned_resource_id", ""),
        "planned_locale": entry.get("planned_locale", ""),
        "planned_key": entry.get("planned_key", ""),
        "planned_value": entry.get("planned_value", ""),
        "execution_entry_status": entry.get("execution_entry_status", ""),
        "executor_entry_status": entry.get("executor_entry_status", ""),
        "real_write_entry_status": (
            "dry_run_would_write_after_future_manual_ack"
            if would_write
            else "blocked_by_real_write_executor_dry_run"
        ),
        "blocking_reasons": blocking_reasons,
        "would_write": would_write,
        "write_performed": False,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "dangerous_ack_effective": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
    }


def _entry_blocking_reasons(entry, payload):
    reasons = []
    state = entry.get("current_translation_state") or {}
    product_id = str(entry.get("product_id") or "").strip()
    selected_product_id = str(payload.get("selected_product_id") or "").strip()
    payload_product_id = str(payload.get("product_id") or "").strip()
    if not product_id:
        reasons.append("missing_product_id")
    if selected_product_id and product_id and product_id != selected_product_id:
        reasons.append("selected_product_scope_mismatch")
    if payload_product_id and product_id and product_id != payload_product_id:
        reasons.append("locked_executor_product_scope_mismatch")
    if entry.get("locale") not in ALLOWED_LOCALES:
        reasons.append("unsupported_locale")
    if entry.get("field") not in ALLOWED_FIELDS:
        reasons.append("unsupported_field")
    for key in [
        "digest",
        "source_value",
        "proposed_translation",
        "planned_resource_id",
        "planned_locale",
        "planned_key",
        "planned_value",
    ]:
        if not str(entry.get(key) or "").strip():
            reasons.append(f"missing_{key}")
    if str(entry.get("planned_mutation_name") or "") != PLANNED_MUTATION_NAME:
        reasons.append("planned_mutation_name_not_translations_register")
    if entry.get("execution_entry_status") != READY_EXECUTION_ENTRY_STATUS:
        reasons.append("execution_entry_not_ready")
    if entry.get("executor_entry_status") != READY_LOCKED_EXECUTOR_ENTRY_STATUS:
        reasons.append("locked_executor_entry_not_ready")
    if entry.get("blocking_reasons"):
        reasons.append("source_locked_executor_entry_has_blocking_reasons")
    if state.get("existing_translation_present"):
        reasons.append("existing_translation_present")
    if state.get("existing_translation_outdated") is True:
        reasons.append("outdated_translation_present")
    for key in [
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "publish_performed",
        "apply_performed",
        "real_apply_performed",
        "rollback_performed",
    ]:
        if entry.get(key) is not False:
            reasons.append(f"source_entry_{key}_not_false")
    return _unique(reasons)


def _scope_blocking_reasons(payload):
    reasons = []
    selected_product_id = str(payload.get("selected_product_id") or "").strip()
    product_id = str(payload.get("product_id") or "").strip()
    if not product_id:
        reasons.append("missing_product_id")
    if selected_product_id and product_id and product_id != selected_product_id:
        reasons.append("selected_product_scope_mismatch")
    if not payload.get("target_locales"):
        reasons.append("missing_target_locales")
    if not payload.get("requested_fields"):
        reasons.append("missing_requested_fields")
    return reasons


def _locked_executor_safety_blocking_reasons(locked_executor_result):
    checks = {
        "executor_shell_only": True,
        "executor_locked": True,
        "execution_plan_only": True,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "dangerous_ack_effective": False,
        "manual_ack_required_for_future_write": True,
        "future_phase_required": True,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "existing_translation_overwrite_allowed": False,
        "outdated_translation_overwrite_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }
    reasons = []
    for key, expected in checks.items():
        if locked_executor_result.get(key) is not expected:
            reasons.append(f"locked_executor_safety_{key}_not_confirmed")
    return reasons


def _write_reports(payload):
    REAL_WRITE_EXECUTOR_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    REAL_WRITE_EXECUTOR_JSON_PATH.write_text(text, encoding="utf-8")
    REAL_WRITE_EXECUTOR_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Executor Status", "executor_status"),
            ("Mode", "mode"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Blocked Entry Count", "blocked_entry_count"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Locked Executor Report Path", "locked_executor_report_path"),
            ("Real Write Executor Report Path", "real_write_executor_report_path"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Future Write Allowed", "future_write_allowed"),
            ("Manual ACK Required", "manual_ack_required"),
            ("Manual ACK Phrase Required", "manual_ack_phrase_required"),
            ("Dangerous ACK Present", "dangerous_ack_present"),
            ("Dangerous ACK Effective", "dangerous_ack_effective"),
            ("Blocking Conditions", "blocking_conditions"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Publish Performed", "publish_performed"),
            ("Apply Performed", "apply_performed"),
            ("Real Apply Performed", "real_apply_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No Write Confirmed", "all_new_actions_no_write_confirmed"),
        ]
    )
    safety_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Real Write Executor Only", "real_write_executor_only"),
            ("Dry Run Only", "dry_run_only"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Future Write Allowed", "future_write_allowed"),
            ("Manual ACK Required", "manual_ack_required"),
            ("Dangerous ACK Effective", "dangerous_ack_effective"),
            ("Shopify Write Performed", "shopify_write_performed"),
            ("Mutation Performed", "mutation_performed"),
            ("translationsRegister Called", "translations_register_called"),
            ("Publish Performed", "publish_performed"),
            ("Apply Performed", "apply_performed"),
            ("Real Apply Performed", "real_apply_performed"),
            ("Rollback Performed", "rollback_performed"),
            ("Existing Translation Overwrite Allowed", "existing_translation_overwrite_allowed"),
            ("Outdated Translation Overwrite Allowed", "outdated_translation_overwrite_allowed"),
            ("No New Shopify Writes Performed", "no_new_shopify_writes_performed"),
            ("All New Actions No Write Confirmed", "all_new_actions_no_write_confirmed"),
        ]
    )
    entry_rows = "\n".join(
        _entry_row(entry) for entry in payload.get("real_write_executor_entries", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Real Write Executor Dry Run</title></head>
<body>
  <h1>Selected Product Translation Real Write Executor Dry Run</h1>
  <p>This is a dry-run executor package only. It does not write to Shopify. Manual ACK input is recorded only as present and is not effective in this phase.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Executor Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Planned value</th><th>Digest</th><th>Planned mutation</th><th>Would write</th><th>Write performed</th><th>Real write entry status</th><th>Blocking reasons</th></tr></thead>
    <tbody>{entry_rows}</tbody>
  </table>
</body>
</html>
"""


def _row(label, value):
    return f"<tr><th>{escape(str(label))}</th><td>{escape(str(value))}</td></tr>"


def _entry_row(entry):
    return (
        "<tr>"
        f"<td>{escape(str(entry.get('locale', '')))}</td>"
        f"<td>{escape(str(entry.get('field', '')))}</td>"
        f"<td>{escape(str(entry.get('source_value', '')))}</td>"
        f"<td>{escape(str(entry.get('planned_value', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('planned_mutation_name', '')))}</td>"
        f"<td>{escape(str(entry.get('would_write', '')))}</td>"
        f"<td>{escape(str(entry.get('write_performed', '')))}</td>"
        f"<td>{escape(str(entry.get('real_write_entry_status', '')))}</td>"
        f"<td>{escape(str(entry.get('blocking_reasons', [])))}</td>"
        "</tr>"
    )


def _unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output


def _utc_now():
    return datetime.now(timezone.utc).isoformat()
