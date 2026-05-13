import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from .translation_real_write_executor import (
    DRY_RUN_EXECUTOR_STATUS,
    MANUAL_ACK_PHRASE_REQUIRED,
)


REAL_WRITE_MANUAL_ACTION_JSON_PATH = Path(
    "logs/shopify_translation_selected_product_real_write_manual_action_package.json"
)
REAL_WRITE_MANUAL_ACTION_HTML_PATH = Path(
    "logs/shopify_translation_selected_product_real_write_manual_action_package.html"
)
PACKAGE_READY_STATUS = (
    "selected_product_translation_real_write_manual_action_package_ready_for_manual_review"
)
PLANNED_MUTATION_NAME = "translationsRegister"
FUTURE_REAL_WRITE_TASK_NAME = "shopify_translation_selected_product_real_write_execute"


def build_selected_product_translation_real_write_manual_action_package(
    real_write_executor_result,
    selected_product_id="",
    write_reports=True,
):
    real_write_executor_result = dict(real_write_executor_result or {})
    selected_product_id = str(selected_product_id or "").strip()
    payload = _empty_manual_action_package(real_write_executor_result, selected_product_id)

    if not real_write_executor_result:
        payload["package_status"] = "blocked_missing_real_write_executor_dry_run"
        payload["blocking_conditions"].append("blocked_missing_real_write_executor_dry_run")
    elif real_write_executor_result.get("executor_status") != DRY_RUN_EXECUTOR_STATUS:
        payload["package_status"] = "blocked_real_write_executor_not_dry_run_ready"
        payload["blocking_conditions"].append("blocked_real_write_executor_not_dry_run_ready")
    else:
        _collect_manual_action_entries(payload, real_write_executor_result)
        payload["blocking_conditions"].extend(
            _real_write_executor_blocking_reasons(real_write_executor_result)
        )
        payload["blocking_conditions"].extend(_scope_blocking_reasons(payload))
        _fill_planned_execution_section(payload)
        if payload["entry_count"] == 0:
            payload["package_status"] = "blocked_no_manual_action_entries"
            payload["blocking_conditions"].append("blocked_no_manual_action_entries")
        elif payload["blocked_entry_count"]:
            payload["package_status"] = "blocked_manual_action_entry_validation_failed"
            payload["blocking_conditions"].append(
                "blocked_manual_action_entry_validation_failed"
            )
        elif payload["blocking_conditions"]:
            payload["package_status"] = "blocked_manual_action_package_safety_not_confirmed"
        else:
            payload["package_status"] = PACKAGE_READY_STATUS
            payload["success"] = True

    payload["blocking_conditions"] = _unique(payload["blocking_conditions"])
    payload["timestamp"] = _utc_now()
    payload["generated_at"] = payload["timestamp"]
    payload["manual_action_package_report_path"] = str(REAL_WRITE_MANUAL_ACTION_JSON_PATH)
    payload["json_selected_product_real_write_manual_action_package_path"] = str(
        REAL_WRITE_MANUAL_ACTION_JSON_PATH
    )
    payload["html_selected_product_real_write_manual_action_package_path"] = str(
        REAL_WRITE_MANUAL_ACTION_HTML_PATH
    )

    if write_reports:
        _write_reports(payload)
    return payload


def _empty_manual_action_package(real_write_executor_result, selected_product_id):
    product_id = real_write_executor_result.get("product_id", "")
    return {
        "success": False,
        "package_status": "",
        "mode": "manual-action-package",
        "product_id": product_id,
        "selected_product_id": selected_product_id,
        "product_title": real_write_executor_result.get("product_title", ""),
        "entry_count": 0,
        "blocked_entry_count": 0,
        "target_locales": list(real_write_executor_result.get("target_locales") or []),
        "requested_fields": list(real_write_executor_result.get("requested_fields") or []),
        "manual_ack_required": True,
        "manual_ack_phrase_required": MANUAL_ACK_PHRASE_REQUIRED,
        "manual_ack_effective": False,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "real_write_executor_status": real_write_executor_result.get("executor_status", ""),
        "real_write_executor_report_path": real_write_executor_result.get(
            "real_write_executor_report_path",
            "logs/shopify_translation_selected_product_real_write_executor.json",
        ),
        "manual_action_package_report_path": str(REAL_WRITE_MANUAL_ACTION_JSON_PATH),
        "manual_action_entries": [],
        "blocking_conditions": [],
        "planned_mutation_name": PLANNED_MUTATION_NAME,
        "planned_resource_id": product_id,
        "planned_translation_inputs_count": 0,
        "planned_translation_inputs_preview": [],
        "planned_graphql_variables_preview": {
            "resourceId": product_id,
            "translations": [],
        },
        "future_powershell_command_preview": [
            (
                "python remote_approval_runner.py --task "
                f"{FUTURE_REAL_WRITE_TASK_NAME} --approval local --mode real-run "
                f"--ack {MANUAL_ACK_PHRASE_REQUIRED}"
            )
        ],
        "readback_verify_plan": [
            "After a future real write, call translatableResource read-only for the same product.",
            "Compare each product_id / locale / key against the planned value.",
            "Confirm every readback value equals planned_value.",
            "Confirm outdated=False or the equivalent Shopify returned status for each translation.",
            "Confirm translationsRegister userErrors is empty.",
            "Mark each entry verified=True only after all checks pass.",
        ],
        "rollback_plan": [
            "This phase performs no rollback.",
            "If a future real write fails, generate a rollback approval package only.",
            "Rollback must be a separate future phase with manual approval.",
            "The page must not automatically rollback.",
        ],
        "shopify_api_call_performed": False,
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
        "safety_summary": {
            "manual_action_package_only": True,
            "manual_ack_required": True,
            "manual_ack_effective": False,
            "real_write_allowed": False,
            "future_write_allowed": False,
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


def _collect_manual_action_entries(payload, real_write_executor_result):
    for entry in real_write_executor_result.get("real_write_executor_entries", []):
        manual_entry = _manual_action_entry(entry, payload)
        payload["manual_action_entries"].append(manual_entry)
        if manual_entry["blocking_reasons"]:
            payload["blocked_entry_count"] += 1
    payload["entry_count"] = len(payload["manual_action_entries"])


def _manual_action_entry(entry, payload):
    blocking_reasons = _entry_blocking_reasons(entry, payload)
    would_write = bool(entry.get("would_write")) and not blocking_reasons
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
        "planned_translatable_content_digest": entry.get("digest", ""),
        "would_write": would_write,
        "write_performed": False,
        "manual_action_entry_status": (
            "ready_for_future_manual_real_write"
            if would_write
            else "blocked_by_manual_action_package"
        ),
        "blocking_reasons": blocking_reasons,
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
        reasons.append("product_id_mismatch")
    if payload_product_id and product_id and product_id != payload_product_id:
        reasons.append("executor_product_id_mismatch")
    if entry.get("locale") not in payload.get("target_locales", []):
        reasons.append("locale_not_in_target_locales")
    if entry.get("field") not in payload.get("requested_fields", []):
        reasons.append("field_not_in_requested_fields")
    if not str(entry.get("digest") or "").strip():
        reasons.append("missing_digest")
    if not str(entry.get("proposed_translation") or "").strip():
        reasons.append("missing_proposed_translation")
    if not str(entry.get("source_value") or "").strip():
        reasons.append("missing_source_value")
    if state.get("existing_translation_present"):
        reasons.append("existing_translation_present")
    if state.get("existing_translation_outdated") is True:
        reasons.append("outdated_translation_present")
    if str(entry.get("planned_mutation_name") or "") != PLANNED_MUTATION_NAME:
        reasons.append("planned_mutation_name_not_translations_register")
    if not entry.get("would_write"):
        reasons.append("real_write_executor_entry_would_write_not_true")
    if entry.get("blocking_reasons"):
        reasons.append("real_write_executor_entry_has_blocking_reasons")
    if entry.get("write_performed") is not False:
        reasons.append("source_entry_write_performed_not_false")
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


def _real_write_executor_blocking_reasons(real_write_executor_result):
    checks = {
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
        "existing_translation_overwrite_allowed": False,
        "outdated_translation_overwrite_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }
    reasons = []
    if real_write_executor_result.get("blocking_conditions"):
        reasons.append("real_write_executor_has_blocking_conditions")
    if int(real_write_executor_result.get("entry_count") or 0) == 0:
        reasons.append("entry_count_zero")
    if int(real_write_executor_result.get("blocked_entry_count") or 0) > 0:
        reasons.append("blocked_entry_count_nonzero")
    if real_write_executor_result.get("executor_status") != DRY_RUN_EXECUTOR_STATUS:
        reasons.append("real_write_executor_status_not_dry_run_ready")
    for key, expected in checks.items():
        if real_write_executor_result.get(key) is not expected:
            reasons.append(f"real_write_executor_safety_{key}_not_confirmed")
    return reasons


def _scope_blocking_reasons(payload):
    reasons = []
    selected_product_id = str(payload.get("selected_product_id") or "").strip()
    product_id = str(payload.get("product_id") or "").strip()
    if not product_id:
        reasons.append("missing_product_id")
    if selected_product_id and product_id and product_id != selected_product_id:
        reasons.append("product_id_mismatch")
    return reasons


def _fill_planned_execution_section(payload):
    translation_inputs = []
    for entry in payload["manual_action_entries"]:
        if not entry.get("would_write"):
            continue
        translation_inputs.append(
            {
                "locale": entry.get("planned_locale", ""),
                "key": entry.get("planned_key", ""),
                "value": entry.get("planned_value", ""),
                "translatableContentDigest": entry.get(
                    "planned_translatable_content_digest", ""
                ),
            }
        )
    payload["planned_translation_inputs_preview"] = translation_inputs
    payload["planned_translation_inputs_count"] = len(translation_inputs)
    payload["planned_graphql_variables_preview"] = {
        "resourceId": payload.get("planned_resource_id", ""),
        "translations": translation_inputs,
    }


def _write_reports(payload):
    REAL_WRITE_MANUAL_ACTION_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    REAL_WRITE_MANUAL_ACTION_JSON_PATH.write_text(text, encoding="utf-8")
    REAL_WRITE_MANUAL_ACTION_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Package Status", "package_status"),
            ("Mode", "mode"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Blocked Entry Count", "blocked_entry_count"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Manual ACK Required", "manual_ack_required"),
            ("Manual ACK Phrase Required", "manual_ack_phrase_required"),
            ("Manual ACK Effective", "manual_ack_effective"),
            ("Real Write Allowed", "real_write_allowed"),
            ("Future Write Allowed", "future_write_allowed"),
            ("Real Write Executor Report Path", "real_write_executor_report_path"),
            ("Manual Action Package Report Path", "manual_action_package_report_path"),
            ("Blocking Conditions", "blocking_conditions"),
        ]
    )
    safety_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
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
    planned_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Planned Mutation Name", "planned_mutation_name"),
            ("Planned Resource ID", "planned_resource_id"),
            ("Planned Translation Inputs Count", "planned_translation_inputs_count"),
            ("Planned Translation Inputs Preview", "planned_translation_inputs_preview"),
            ("Planned GraphQL Variables Preview", "planned_graphql_variables_preview"),
            ("Future PowerShell Command Preview", "future_powershell_command_preview"),
            ("Readback Verify Plan", "readback_verify_plan"),
            ("Rollback Plan", "rollback_plan"),
        ]
    )
    entry_rows = "\n".join(
        _entry_row(entry) for entry in payload.get("manual_action_entries", [])
    )
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Real Write Manual Action Package</title></head>
<body>
  <h1>Selected Product Translation Real Write Manual Action Package</h1>
  <p>This is a manual action package only. It does not write to Shopify, call translationsRegister, publish, apply, or rollback.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Safety</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{safety_rows}</tbody></table>
  <h2>Planned Execution</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{planned_rows}</tbody></table>
  <h2>Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Planned value</th><th>Digest</th><th>Would write</th><th>Write performed</th><th>Manual action status</th><th>Blocking reasons</th></tr></thead>
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
        f"<td>{escape(str(entry.get('would_write', '')))}</td>"
        f"<td>{escape(str(entry.get('write_performed', '')))}</td>"
        f"<td>{escape(str(entry.get('manual_action_entry_status', '')))}</td>"
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
