import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


LOCKED_EXECUTOR_JSON_PATH = Path(
    "logs/shopify_translation_selected_product_locked_executor_shell.json"
)
LOCKED_EXECUTOR_HTML_PATH = Path(
    "logs/shopify_translation_selected_product_locked_executor_shell.html"
)
READY_EXECUTION_PLAN_STATUS = "selected_product_translation_locked_execution_plan_ready_for_review"
READY_EXECUTION_ENTRY_STATUS = "locked_plan_ready_for_future_phase"
READY_EXECUTOR_STATUS = "selected_product_translation_locked_executor_shell_ready_for_review"
EXECUTOR_ENTRY_STATUS = "executor_locked_no_shopify_write"


def build_selected_product_translation_locked_executor_shell(
    locked_execution_plan_result,
    ack_preview_text=None,
    write_reports=True,
):
    locked_execution_plan_result = dict(locked_execution_plan_result or {})
    dangerous_ack_present = bool(str(ack_preview_text or "").strip())
    payload = _empty_executor_shell(locked_execution_plan_result, dangerous_ack_present)

    if not locked_execution_plan_result:
        payload["executor_status"] = "blocked_missing_locked_execution_plan"
        payload["blocking_conditions"].append("blocked_missing_locked_execution_plan")
    elif locked_execution_plan_result.get("execution_plan_status") != READY_EXECUTION_PLAN_STATUS:
        payload["executor_status"] = "blocked_locked_execution_plan_not_ready"
        payload["blocking_conditions"].append("blocked_locked_execution_plan_not_ready")
    else:
        _collect_executor_entries(payload, locked_execution_plan_result)
        payload["blocking_conditions"].extend(
            _execution_plan_safety_blocking_reasons(locked_execution_plan_result)
        )
        if payload["entry_count"] == 0:
            payload["executor_status"] = "blocked_no_locked_executor_entries"
            payload["blocking_conditions"].append("blocked_no_locked_executor_entries")
        elif payload["blocked_entry_count"]:
            payload["executor_status"] = "blocked_locked_executor_entry_validation_failed"
            payload["blocking_conditions"].append(
                "blocked_locked_executor_entry_validation_failed"
            )
        elif payload["blocking_conditions"]:
            payload["executor_status"] = "blocked_locked_executor_safety_not_confirmed"
        else:
            payload["executor_status"] = READY_EXECUTOR_STATUS
            payload["success"] = True

    payload["blocking_conditions"] = _unique(payload["blocking_conditions"])
    payload["timestamp"] = _utc_now()
    payload["generated_at"] = payload["timestamp"]
    payload["executor_report_path"] = str(LOCKED_EXECUTOR_JSON_PATH)
    payload["json_selected_product_locked_executor_shell_path"] = str(
        LOCKED_EXECUTOR_JSON_PATH
    )
    payload["html_selected_product_locked_executor_shell_path"] = str(
        LOCKED_EXECUTOR_HTML_PATH
    )

    if write_reports:
        _write_reports(payload)
    return payload


def _empty_executor_shell(locked_execution_plan_result, dangerous_ack_present):
    return {
        "success": False,
        "executor_status": "",
        "executor_shell_only": True,
        "executor_locked": True,
        "execution_plan_only": True,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "dangerous_ack_present": dangerous_ack_present,
        "dangerous_ack_effective": False,
        "manual_ack_preview_recorded": dangerous_ack_present,
        "manual_ack_preview_value_recorded": False,
        "manual_ack_required_for_future_write": True,
        "future_phase_required": True,
        "product_id": locked_execution_plan_result.get("product_id", ""),
        "product_title": locked_execution_plan_result.get("product_title", ""),
        "entry_count": 0,
        "locked_entry_count": 0,
        "blocked_entry_count": 0,
        "target_locales": list(locked_execution_plan_result.get("target_locales") or []),
        "requested_fields": list(locked_execution_plan_result.get("requested_fields") or []),
        "execution_plan_status": locked_execution_plan_result.get(
            "execution_plan_status", ""
        ),
        "execution_plan_report_path": locked_execution_plan_result.get(
            "execution_plan_report_path",
            "logs/shopify_translation_selected_product_locked_execution_plan.json",
        ),
        "executor_report_path": str(LOCKED_EXECUTOR_JSON_PATH),
        "locked_executor_entries": [],
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
        },
    }


def _collect_executor_entries(payload, locked_execution_plan_result):
    for entry in locked_execution_plan_result.get("locked_execution_plan_entries", []):
        executor_entry = _executor_entry(entry)
        payload["locked_executor_entries"].append(executor_entry)
        if executor_entry["blocking_reasons"]:
            payload["blocked_entry_count"] += 1
    payload["entry_count"] = len(payload["locked_executor_entries"])
    payload["locked_entry_count"] = sum(
        1
        for entry in payload["locked_executor_entries"]
        if entry.get("executor_entry_status") == EXECUTOR_ENTRY_STATUS
    )


def _executor_entry(entry):
    blocking_reasons = _entry_blocking_reasons(entry)
    return {
        "product_id": entry.get("product_id", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "digest": entry.get("digest", ""),
        "source_value": entry.get("source_value", ""),
        "proposed_translation": entry.get("proposed_translation", ""),
        "planned_mutation_name": entry.get("planned_mutation_name", ""),
        "planned_resource_id": entry.get("planned_resource_id", ""),
        "planned_locale": entry.get("planned_locale", ""),
        "planned_key": entry.get("planned_key", ""),
        "planned_value": entry.get("planned_value", ""),
        "execution_entry_status": entry.get("execution_entry_status", ""),
        "executor_entry_status": (
            EXECUTOR_ENTRY_STATUS if not blocking_reasons else "blocked_by_locked_executor_shell"
        ),
        "blocking_reasons": blocking_reasons,
        "executor_locked": True,
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


def _entry_blocking_reasons(entry):
    reasons = []
    if entry.get("execution_entry_status") != READY_EXECUTION_ENTRY_STATUS:
        reasons.append("execution_plan_entry_not_ready")
    for key in [
        "product_id",
        "locale",
        "field",
        "digest",
        "source_value",
        "proposed_translation",
        "planned_mutation_name",
        "planned_resource_id",
        "planned_locale",
        "planned_key",
        "planned_value",
    ]:
        if not str(entry.get(key) or "").strip():
            reasons.append(f"missing_{key}")
    if entry.get("shopify_write_performed") is not False:
        reasons.append("source_entry_shopify_write_not_false")
    if entry.get("mutation_performed") is not False:
        reasons.append("source_entry_mutation_not_false")
    if entry.get("translations_register_called") is not False:
        reasons.append("source_entry_translations_register_not_false")
    return _unique(reasons)


def _execution_plan_safety_blocking_reasons(locked_execution_plan_result):
    checks = {
        "execution_plan_only": True,
        "executor_locked": True,
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
        if locked_execution_plan_result.get(key) is not expected:
            reasons.append(f"execution_plan_safety_{key}_not_confirmed")
    return reasons


def _write_reports(payload):
    LOCKED_EXECUTOR_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    LOCKED_EXECUTOR_JSON_PATH.write_text(text, encoding="utf-8")
    LOCKED_EXECUTOR_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Executor Status", "executor_status"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Locked Entry Count", "locked_entry_count"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Execution Plan Report Path", "execution_plan_report_path"),
            ("Executor Report Path", "executor_report_path"),
            ("Executor Locked", "executor_locked"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Future Write Allowed", "future_write_allowed"),
            ("Dangerous ACK Present", "dangerous_ack_present"),
            ("Dangerous ACK Effective", "dangerous_ack_effective"),
            ("Manual ACK Required For Future Write", "manual_ack_required_for_future_write"),
            ("Future Phase Required", "future_phase_required"),
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
            ("Executor Shell Only", "executor_shell_only"),
            ("Executor Locked", "executor_locked"),
            ("Execution Plan Only", "execution_plan_only"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Future Write Allowed", "future_write_allowed"),
            ("Dangerous ACK Effective", "dangerous_ack_effective"),
            ("Manual ACK Required For Future Write", "manual_ack_required_for_future_write"),
            ("Future Phase Required", "future_phase_required"),
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
        _entry_row(entry) for entry in payload.get("locked_executor_entries", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Locked Executor Shell</title></head>
<body>
  <h1>Selected Product Translation Locked Executor Shell</h1>
  <p>This is a locked executor shell only. It cannot write to Shopify. Any ACK entered here is recorded only as a preview and is not effective in this phase.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Locked Executor Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Planned value</th><th>Digest</th><th>Planned mutation</th><th>Execution entry status</th><th>Executor entry status</th><th>Blocking reasons</th></tr></thead>
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
        f"<td>{escape(str(entry.get('execution_entry_status', '')))}</td>"
        f"<td>{escape(str(entry.get('executor_entry_status', '')))}</td>"
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
