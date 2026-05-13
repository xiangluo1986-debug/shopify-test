import json
from datetime import datetime, timezone
from html import escape
from pathlib import Path


REAL_WRITE_READINESS_JSON_PATH = Path(
    "logs/shopify_translation_selected_product_real_write_readiness_package.json"
)
REAL_WRITE_READINESS_HTML_PATH = Path(
    "logs/shopify_translation_selected_product_real_write_readiness_package.html"
)
READY_FINAL_REVIEW_STATUS = "selected_product_translation_final_review_ready_for_manual_approval"
READY_FINAL_ENTRY_STATUS = "ready_for_final_manual_review"
READY_READINESS_STATUS = "selected_product_translation_real_write_readiness_ready_for_manual_ack"
ALLOWED_FIELDS = {"title", "meta_title", "meta_description"}
ALLOWED_LOCALES = {"ja", "de", "fr", "es", "it"}


def build_selected_product_translation_real_write_readiness(final_review_result, write_reports=True):
    final_review_result = dict(final_review_result or {})
    payload = _empty_readiness(final_review_result)

    if not final_review_result:
        payload["readiness_status"] = "blocked_missing_final_review_package"
        payload["blocking_conditions"].append("blocked_missing_final_review_package")
    elif final_review_result.get("final_review_status") != READY_FINAL_REVIEW_STATUS:
        payload["readiness_status"] = "blocked_final_review_not_ready"
        payload["blocking_conditions"].append("blocked_final_review_not_ready")
    else:
        _collect_readiness_entries(payload, final_review_result)
        payload["blocking_conditions"].extend(_final_review_safety_blocking_reasons(final_review_result))
        if payload["entry_count"] == 0:
            payload["readiness_status"] = "blocked_no_readiness_entries"
            payload["blocking_conditions"].append("blocked_no_readiness_entries")
        elif payload["blocked_entry_count"]:
            payload["readiness_status"] = "blocked_readiness_entry_validation_failed"
            payload["blocking_conditions"].append("blocked_readiness_entry_validation_failed")
        elif payload["blocking_conditions"]:
            payload["readiness_status"] = "blocked_readiness_safety_not_confirmed"
        else:
            payload["readiness_status"] = READY_READINESS_STATUS
            payload["success"] = True

    payload["blocking_conditions"] = _unique(payload["blocking_conditions"])
    payload["timestamp"] = _utc_now()
    payload["generated_at"] = payload["timestamp"]
    payload["readiness_report_path"] = str(REAL_WRITE_READINESS_JSON_PATH)
    payload["json_selected_product_real_write_readiness_package_path"] = str(
        REAL_WRITE_READINESS_JSON_PATH
    )
    payload["html_selected_product_real_write_readiness_package_path"] = str(
        REAL_WRITE_READINESS_HTML_PATH
    )

    if write_reports:
        _write_reports(payload)
    return payload


def _empty_readiness(final_review_result):
    return {
        "success": False,
        "readiness_status": "",
        "readiness_package_only": True,
        "final_review_only": True,
        "apply_plan_only": True,
        "product_id": final_review_result.get("product_id", ""),
        "product_title": final_review_result.get("product_title", ""),
        "entry_count": 0,
        "blocked_entry_count": 0,
        "skipped_count": int(final_review_result.get("skipped_count") or 0),
        "target_locales": list(final_review_result.get("target_locales") or []),
        "requested_fields": list(final_review_result.get("requested_fields") or []),
        "final_review_status": final_review_result.get("final_review_status", ""),
        "final_review_report_path": final_review_result.get(
            "final_review_report_path",
            "logs/shopify_translation_selected_product_final_review_package.json",
        ),
        "readiness_report_path": str(REAL_WRITE_READINESS_JSON_PATH),
        "readiness_entries": [],
        "blocking_conditions": [],
        "manual_ack_required_for_future_write": True,
        "future_write_allowed": False,
        "future_write_requires_separate_phase": True,
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
            "readiness_package_only": True,
            "final_review_only": True,
            "apply_plan_only": True,
            "shopify_write_performed": False,
            "mutation_performed": False,
            "translations_register_called": False,
            "publish_performed": False,
            "apply_performed": False,
            "real_apply_performed": False,
            "rollback_performed": False,
            "existing_translation_overwrite_allowed": False,
            "outdated_translation_overwrite_allowed": False,
            "future_write_allowed": False,
            "manual_ack_required_for_future_write": True,
            "no_new_shopify_writes_performed": True,
            "all_new_actions_no_write_confirmed": True,
        },
    }


def _collect_readiness_entries(payload, final_review_result):
    for entry in final_review_result.get("final_review_entries", []):
        readiness_entry = _readiness_entry(payload, entry)
        payload["readiness_entries"].append(readiness_entry)
        if readiness_entry["blocking_reasons"]:
            payload["blocked_entry_count"] += 1
    payload["entry_count"] = len(payload["readiness_entries"])


def _readiness_entry(payload, entry):
    blocking_reasons = _entry_blocking_reasons(entry)
    return {
        "product_id": entry.get("product_id") or payload.get("product_id", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "digest": entry.get("digest", ""),
        "source_value": entry.get("source_value", ""),
        "proposed_translation": entry.get("proposed_translation", ""),
        "current_translation_state": entry.get("current_translation_state", {}),
        "final_review_status": entry.get("final_review_status", ""),
        "readiness_entry_status": (
            "ready_for_future_manual_ack" if not blocking_reasons else "blocked_by_readiness_gate"
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


def _entry_blocking_reasons(entry):
    reasons = []
    state = entry.get("current_translation_state") or {}
    if entry.get("final_review_status") != READY_FINAL_ENTRY_STATUS:
        reasons.append("final_review_entry_not_ready")
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


def _final_review_safety_blocking_reasons(final_review_result):
    checks = {
        "final_review_only": True,
        "apply_plan_only": True,
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
        "manual_ack_required_for_future_write": True,
    }
    reasons = []
    for key, expected in checks.items():
        if final_review_result.get(key) is not expected:
            reasons.append(f"final_review_safety_{key}_not_confirmed")
    return reasons


def _write_reports(payload):
    REAL_WRITE_READINESS_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, ensure_ascii=True, indent=2) + "\n"
    json.loads(text)
    REAL_WRITE_READINESS_JSON_PATH.write_text(text, encoding="utf-8")
    REAL_WRITE_READINESS_HTML_PATH.write_text(_render_html(payload), encoding="utf-8")


def _render_html(payload):
    summary_rows = "\n".join(
        _row(label, payload.get(key))
        for label, key in [
            ("Readiness Status", "readiness_status"),
            ("Product ID", "product_id"),
            ("Product Title", "product_title"),
            ("Entry Count", "entry_count"),
            ("Skipped Count", "skipped_count"),
            ("Target Locales", "target_locales"),
            ("Requested Fields", "requested_fields"),
            ("Final Review Report Path", "final_review_report_path"),
            ("Readiness Report Path", "readiness_report_path"),
            ("Future Write Allowed", "future_write_allowed"),
            ("Manual ACK Required For Future Write", "manual_ack_required_for_future_write"),
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
    entry_rows = "\n".join(_entry_row(entry) for entry in payload.get("readiness_entries", []))
    return f"""<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><title>Selected Product Translation Real Write Readiness</title></head>
<body>
  <h1>Selected Product Translation Real Write Readiness</h1>
  <p>This is a no-write readiness package. Real Shopify writes remain disabled and require a separate future phase plus explicit manual ACK.</p>
  <h2>Summary</h2>
  <table border="1" cellspacing="0" cellpadding="6"><tbody>{summary_rows}</tbody></table>
  <h2>Readiness Entries</h2>
  <table border="1" cellspacing="0" cellpadding="6">
    <thead><tr><th>Locale</th><th>Field</th><th>Source value</th><th>Proposed translation</th><th>Digest</th><th>Current translation state</th><th>Final review status</th><th>Readiness status</th><th>Blocking reasons</th></tr></thead>
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
        f"<td>{escape(str(entry.get('proposed_translation', '')))}</td>"
        f"<td>{escape(str(entry.get('digest', '')))}</td>"
        f"<td>{escape(str(entry.get('current_translation_state', {})))}</td>"
        f"<td>{escape(str(entry.get('final_review_status', '')))}</td>"
        f"<td>{escape(str(entry.get('readiness_entry_status', '')))}</td>"
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
