import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


LOCKED_EXECUTION_PLAN_JSON_PATH = Path(
    "logs/shopify_translation_selected_product_locked_execution_plan.json"
)
LOCKED_EXECUTION_PLAN_HTML_PATH = Path(
    "logs/shopify_translation_selected_product_locked_execution_plan.html"
)
READY_READINESS_STATUS = "selected_product_translation_real_write_readiness_ready_for_manual_ack"
READY_READINESS_ENTRY_STATUS = "ready_for_future_manual_ack"
READY_EXECUTION_PLAN_STATUS = "selected_product_translation_locked_execution_plan_ready_for_review"
ALLOWED_FIELDS = {"title", "meta_title", "meta_description"}
ALLOWED_LOCALES = {"ja", "de", "fr", "es", "it"}
PLANNED_MUTATION_NAME = "translationsRegister"


def build_selected_product_translation_locked_execution_plan(readiness_result, write_reports=True):
    readiness_result = dict(readiness_result or {})
    payload = _empty_execution_plan(readiness_result)

    if not readiness_result:
        payload["execution_plan_status"] = "blocked_missing_real_write_readiness_package"
        payload["blocking_conditions"].append("blocked_missing_real_write_readiness_package")
    elif readiness_result.get("readiness_status") != READY_READINESS_STATUS:
        payload["execution_plan_status"] = "blocked_real_write_readiness_not_ready"
        payload["blocking_conditions"].append("blocked_real_write_readiness_not_ready")
    else:
        _collect_execution_entries(payload, readiness_result)
        payload["blocking_conditions"].extend(_readiness_safety_blocking_reasons(readiness_result))
        if payload["entry_count"] == 0:
            payload["execution_plan_status"] = "blocked_no_locked_execution_plan_entries"
            payload["blocking_conditions"].append("blocked_no_locked_execution_plan_entries")
        elif payload["blocked_entry_count"]:
            payload["execution_plan_status"] = "blocked_locked_execution_plan_entry_validation_failed"
            payload["blocking_conditions"].append(
                "blocked_locked_execution_plan_entry_validation_failed"
            )
        elif payload["blocking_conditions"]:
            payload["execution_plan_status"] = "blocked_locked_execution_plan_safety_not_confirmed"
        else:
            payload["execution_plan_status"] = READY_EXECUTION_PLAN_STATUS
            payload["success"] = True

    payload["blocking_conditions"] = _unique(payload["blocking_conditions"])
    payload["timestamp"] = _utc_now()
    payload["generated_at"] = payload["timestamp"]
    payload["execution_plan_report_path"] = str(LOCKED_EXECUTION_PLAN_JSON_PATH)
    payload["json_selected_product_locked_execution_plan_path"] = str(
        LOCKED_EXECUTION_PLAN_JSON_PATH
    )
    payload["html_selected_product_locked_execution_plan_path"] = str(
        LOCKED_EXECUTION_PLAN_HTML_PATH
    )

    if write_reports:
        _write_reports(payload)
    return payload


def _empty_execution_plan(readiness_result):
    return {
        "success": False,
        "execution_plan_status": "",
        "execution_plan_only": True,
        "executor_locked": True,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "dangerous_ack_effective": False,
        "manual_ack_required_for_future_write": True,
        "future_phase_required": True,
        "product_id": readiness_result.get("product_id", ""),
        "product_title": readiness_result.get("product_title", ""),
        "entry_count": 0,
        "blocked_entry_count": 0,
        "target_locales": list(readiness_result.get("target_locales") or []),
        "requested_fields": list(readiness_result.get("requested_fields") or []),
        "readiness_status": readiness_result.get("readiness_status", ""),
        "readiness_report_path": readiness_result.get(
            "readiness_report_path",
            "logs/shopify_translation_selected_product_real_write_readiness_package.json",
        ),
        "execution_plan_report_path": str(LOCKED_EXECUTION_PLAN_JSON_PATH),
        "locked_execution_plan_entries": [],
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
        },
    }


def _collect_execution_entries(payload, readiness_result):
    for entry in readiness_result.get("readiness_entries", []):
        execution_entry = _execution_entry(payload, entry)
        payload["locked_execution_plan_entries"].append(execution_entry)
        if execution_entry["blocking_reasons"]:
            payload["blocked_entry_count"] += 1
    payload["entry_count"] = len(payload["locked_execution_plan_entries"])


def _execution_entry(payload, entry):
    blocking_reasons = _entry_blocking_reasons(entry)
    product_id = entry.get("product_id") or payload.get("product_id", "")
    field = entry.get("field", "")
    locale = entry.get("locale", "")
    digest = entry.get("digest", "")
    proposed_translation = entry.get("proposed_translation", "")
    return {
        "product_id": product_id,
        "locale": locale,
        "field": field,
        "digest": digest,
        "source_value": entry.get("source_value", ""),
        "proposed_translation": proposed_translation,
        "current_translation_state": entry.get("current_translation_state", {}),
        "readiness_entry_status": entry.get("readiness_entry_status", ""),
        "planned_mutation_name": PLANNED_MUTATION_NAME,
        "planned_resource_id": product_id,
        "planned_translatable_content_digest": digest,
        "planned_locale": locale,
        "planned_key": field,
        "planned_value": proposed_translation,
        "execution_entry_status": (
            "locked_plan_ready_for_future_phase"
            if not blocking_reasons
            else "blocked_by_locked_execution_plan"
        ),
        "blocking_reasons": blocking_reasons,
        "planned_only": True,
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
    state = entry.get("current_translation_state") or {}
    if entry.get("readiness_entry_status") != READY_READINESS_ENTRY_STATUS:
        reasons.append("readiness_entry_not_ready")
    if not str(entry.get("product_id") or "").strip():
        reasons.append("missing_product_id")
    if entry.get("locale") not in ALLOWED_LOCALES:
        reasons.append("unsupported_locale")
    if entry.get("field") not in ALLOWED_FIELDS:
        reasons.append("unsupported_field")
    if not str(entry.get("digest") or "").strip():
        reasons.append("missing_digest")
    if not str(entry.get("source_value") or "").strip():
        reasons.append("missing_source_value")
    if not str(entry.get("proposed_translation") or "").strip():
        reasons.append("missing_proposed_translation")
    if state.get("existing_translation_present"):
        reasons.append("existing_translation_present")
    if state.get("existing_translation_outdated") is True:
        reasons.append("outdated_translation_present")
    return _unique(reasons)


def _readiness_safety_blocking_reasons(readiness_result):
    checks = {
        "readiness_package_only": True,
        "final_review_only": True,
        "future_write_allowed": False,
        "manual_ack_required_for_future_write": True,
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
        if readiness_result.get(key) is not expected:
            reasons.append(f"readiness_safety_{key}_not_confirmed")
    return reasons


def _write_reports(payload):
    LOCKED_EXECUTION_PLAN_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    LOCKED_EXECUTION_PLAN_JSON_PATH.write_text(text, encoding="utf-8")
    LOCKED_EXECUTION_PLAN_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Execution Plan Status", "execution_plan_status"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Readiness Report Path", "readiness_report_path"),
            ("Execution Plan Report Path", "execution_plan_report_path"),
            ("Executor Locked", "executor_locked"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Future Write Allowed", "future_write_allowed"),
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
    entry_rows = "\n".join(
        _entry_row(entry) for entry in payload.get("locked_execution_plan_entries", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Locked Execution Plan</title></head>
<body>
  <h1>Selected Product Translation Locked Execution Plan</h1>
  <p>This is a locked execution plan only. It does not write to Shopify. Real writes require a separate future phase and explicit manual ACK.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Locked Execution Plan Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Planned value</th><th>Digest</th><th>Readiness status</th><th>Planned mutation</th><th>Execution entry status</th><th>Blocking reasons</th></tr></thead>
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
        f"<td>{escape(str(entry.get('readiness_entry_status', '')))}</td>"
        f"<td>{escape(str(entry.get('planned_mutation_name', '')))}</td>"
        f"<td>{escape(str(entry.get('execution_entry_status', '')))}</td>"
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
