import json
import hashlib
from datetime import datetime, timezone

import requests

from .models import ShopifyInstallation
from .translation_apply_plan import build_selected_product_translation_apply_plan
from .translation_console import (
    SHOPIFY_API_VERSION,
    fetch_translation_console_data,
)
from .translation_drafts import generate_selected_product_missing_translation_draft_package
from .translation_final_review import build_selected_product_translation_final_review
from .translation_locked_execution_plan import (
    build_selected_product_translation_locked_execution_plan,
)
from .translation_locked_executor import build_selected_product_translation_locked_executor_shell
from .translation_real_write_executor import (
    build_selected_product_translation_real_write_executor_dry_run,
)
from .translation_real_write_manual_action_package import (
    PACKAGE_READY_STATUS,
    build_selected_product_translation_real_write_manual_action_package,
)
from .translation_real_write_readiness import (
    build_selected_product_translation_real_write_readiness,
)


TASK_NAME = "shopify_translation_selected_product_real_write_execute"
PHASE = "16.2D"
DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
ALLOWED_LOCALES = set(DEFAULT_TARGET_LOCALES)
ALLOWED_FIELDS = set(DEFAULT_FIELDS)
ACK_VALUE = "I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE"
REAL_RUN_MODES = {"real-run", "execute-real-write"}
MUTATION_NAME = "translationsRegister"
FIRST_REAL_WRITE_LOCALE = "de"
FIRST_REAL_WRITE_FIELD = "meta_title"
FIRST_REAL_WRITE_MAX_ENTRIES = 1


def execute_selected_product_translation_real_write(settings):
    settings = dict(settings or {})
    mode = settings.get("mode") or "dry-run"
    dry_run = settings.get("dry_run") is not False
    product_id = settings.get("product_id") or DEFAULT_PRODUCT_ID
    target_locales = list(settings.get("target_locales") or DEFAULT_TARGET_LOCALES)
    requested_fields = list(settings.get("requested_fields") or DEFAULT_FIELDS)
    payload = _empty_payload(settings, mode, dry_run, product_id, target_locales, requested_fields)

    installation = ShopifyInstallation.objects.first()
    if installation is None:
        payload["blocking_conditions"].append("blocked_missing_shopify_installation")
        payload["execution_status"] = _status(payload, dry_run, mutation_called=False)
        return _finalize(payload)

    manual_package = _regenerate_manual_action_package(
        installation, product_id, target_locales, requested_fields
    )
    _attach_manual_package(payload, manual_package)
    payload["blocking_conditions"].extend(_manual_package_blocking_conditions(manual_package))

    entries = _manual_entries(manual_package)
    real_run_requested = mode in REAL_RUN_MODES and not dry_run
    entries = _apply_single_entry_gate(payload, settings, entries, real_run_requested)
    payload["blocking_conditions"].extend(_env_blocking_conditions(payload, settings))

    precheck = _pre_write_readback(
        installation,
        product_id,
        target_locales,
        entries,
        single_entry_active=payload.get("single_entry_active", False),
        requested_locale=payload.get("requested_locale", ""),
        requested_field=payload.get("requested_field", ""),
    )
    payload["pre_write_readback_performed"] = precheck["performed"]
    payload["pre_write_readback_checked"] = precheck["performed"]
    payload["pre_write_digest_verified"] = precheck["all_digest_verified"]
    payload["shopify_api_call_performed"] = precheck["performed"]
    payload["entries"] = precheck["entries"]
    payload["blocking_conditions"].extend(precheck["blocking_conditions"])
    _attach_single_entry_precheck_summary(payload)
    _attach_single_entry_empty_candidate_precheck_summary(payload, precheck.get("target_state") or {})
    payload["blocking_conditions"].extend(payload.get("single_entry_blocking_conditions") or [])

    payload["would_write_count"] = sum(1 for entry in payload["entries"] if entry.get("would_write"))
    payload["real_run_requested"] = bool(real_run_requested)
    payload["translations_register_payload_count"] = payload["would_write_count"]
    preflight_gate_ready = _single_entry_preflight_gate_ready(payload)
    if real_run_requested and not preflight_gate_ready:
        payload["blocking_conditions"].append("single_entry_preflight_not_ready")
    payload["real_write_allowed"] = bool(
        real_run_requested
        and payload.get("single_entry_selected")
        and payload["would_write_count"] == 1
        and payload.get("single_entry_only")
        and _first_real_write_target_matches(payload)
        and payload.get("pre_write_readback_checked")
        and not payload.get("pre_write_existing_current_translation")
        and not payload.get("pre_write_existing_outdated_translation")
        and payload.get("translations_register_payload_count") == 1
        and payload.get("validation_status") == "passed"
        and payload.get("manual_action_package_status") == PACKAGE_READY_STATUS
        and payload.get("no_write_confirmed") is True
        and preflight_gate_ready
        and not payload["blocking_conditions"]
    )

    mutation_result = _empty_mutation_result()
    if payload["real_write_allowed"]:
        mutation_result = _translations_register(installation, product_id, payload["entries"])
        _attach_mutation_result(payload, mutation_result)
        if mutation_result["user_errors"]:
            payload["blocking_conditions"].append("translations_register_user_errors_present")
        if mutation_result["request_failed"]:
            payload["blocking_conditions"].append("translations_register_request_failed")

        postcheck = _post_write_readback(installation, product_id, target_locales, payload["entries"])
        payload["post_write_readback_performed"] = postcheck["performed"]
        payload["post_write_readback_checked"] = postcheck["performed"]
        payload["post_write_verified"] = postcheck["all_verified"]
        payload["post_write_readback_matches"] = postcheck["all_verified"]
        payload["verified_count"] = postcheck["verified_count"]
        payload["entries"] = postcheck["entries"]
        payload["shopify_api_call_performed"] = True
        payload["blocking_conditions"].extend(postcheck["blocking_conditions"])

    payload["execution_status"] = _status(
        payload,
        dry_run=dry_run,
        mutation_called=payload["translations_register_called"],
    )
    return _finalize(payload)


def _regenerate_manual_action_package(installation, product_id, target_locales, requested_fields):
    draft_result = generate_selected_product_missing_translation_draft_package(
        product_id=product_id,
        target_locales=target_locales,
        fields=requested_fields,
        installation=installation,
    )
    apply_plan_result = build_selected_product_translation_apply_plan(draft_result)
    final_review_result = build_selected_product_translation_final_review(apply_plan_result)
    readiness_result = build_selected_product_translation_real_write_readiness(final_review_result)
    locked_execution_plan_result = build_selected_product_translation_locked_execution_plan(
        readiness_result
    )
    locked_executor_result = build_selected_product_translation_locked_executor_shell(
        locked_execution_plan_result
    )
    real_write_executor_result = build_selected_product_translation_real_write_executor_dry_run(
        locked_executor_result,
        selected_product_id=product_id,
    )
    return build_selected_product_translation_real_write_manual_action_package(
        real_write_executor_result,
        selected_product_id=product_id,
    )


def _empty_payload(settings, mode, dry_run, product_id, target_locales, requested_fields):
    return {
        "phase": PHASE,
        "task": TASK_NAME,
        "task_name": TASK_NAME,
        "mode": "dry-run" if dry_run else mode,
        "requested_mode": mode,
        "dry_run": bool(dry_run),
        "execution_status": "",
        "product_id": product_id,
        "product_title": "",
        "entry_count": 0,
        "would_write_count": 0,
        "write_attempted_count": 0,
        "write_succeeded_count": 0,
        "verified_count": 0,
        "user_errors_count": 0,
        "blocking_conditions": [],
        "ack_present": bool(settings.get("ack_present")),
        "ack_matches": bool(settings.get("ack_matches")),
        "real_run_requested": False,
        "real_write_allowed": False,
        "future_write_allowed": False,
        "manual_ack_required": True,
        "manual_ack_phrase_required": ACK_VALUE,
        "validation_status": "failed",
        "no_write_confirmed": False,
        "preflight_status": "single_entry_real_write_preflight_not_requested",
        "manual_real_write_allowed_next_step": False,
        "real_write_next_command_preview": [],
        "locked_real_write_ready": False,
        "locked_real_write_target": {},
        "locked_real_write_command_powershell": [],
        "locked_real_write_required_env": {},
        "locked_real_write_safety_checklist": [],
        "post_write_audit_expected_fields": [],
        "abort_conditions": [],
        "post_real_write_check_command_powershell": [],
        "real_write_target_product_id": DEFAULT_PRODUCT_ID,
        "real_write_target_locale": FIRST_REAL_WRITE_LOCALE,
        "real_write_target_field": FIRST_REAL_WRITE_FIELD,
        "real_write_target_max_entries": FIRST_REAL_WRITE_MAX_ENTRIES,
        "first_real_write_target_mismatch": False,
        "preflight_warnings": [],
        "single_entry_only": bool(settings.get("single_entry_only")),
        "single_entry_active": False,
        "requested_locale": settings.get("requested_locale", ""),
        "requested_field": settings.get("requested_field", ""),
        "manual_action_package_entry_count": 0,
        "single_entry_candidate_count": 0,
        "single_entry_selected": False,
        "single_entry_blocking_conditions": [],
        "target_locales": target_locales,
        "requested_fields": requested_fields,
        "locked_executor_report_path": "logs/shopify_translation_selected_product_locked_executor_shell.json",
        "real_write_executor_report_path": "logs/shopify_translation_selected_product_real_write_execute.json",
        "manual_action_package_status": "",
        "manual_action_package_report_path": "",
        "pre_write_readback_checked": False,
        "pre_write_readback_performed": False,
        "pre_write_existing_current_translation": False,
        "pre_write_existing_outdated_translation": False,
        "pre_write_digest": "",
        "pre_write_digest_verified": False,
        "translations_register_payload_count": 0,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "translations_register_user_errors": [],
        "post_write_readback_performed": False,
        "post_write_readback_checked": False,
        "post_write_readback_required": True,
        "post_write_verified": False,
        "post_write_readback_matches": False,
        "post_write_readback_value_digest": "",
        "post_write_readback_value_chars": 0,
        "audit_status": "single_entry_real_write_audit_not_run",
        "audit_summary": {},
        "rollback_required": False,
        "rollback_approval_required": False,
        "rollback_performed": False,
        "publish_performed": False,
        "apply_performed": False,
        "real_apply_performed": False,
        "existing_translation_overwrite_allowed": False,
        "outdated_translation_overwrite_allowed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
        "no_unverified_write": True,
        "entries": [],
        "generated_at": _utc_now(),
    }


def _attach_manual_package(payload, manual_package):
    payload["manual_action_package_status"] = manual_package.get("package_status", "")
    payload["manual_action_package_report_path"] = manual_package.get(
        "manual_action_package_report_path", ""
    )
    payload["product_title"] = manual_package.get("product_title", "")
    payload["entry_count"] = int(manual_package.get("entry_count") or 0)
    payload["manual_action_package_entry_count"] = int(manual_package.get("entry_count") or 0)
    payload["blocked_entry_count"] = int(manual_package.get("blocked_entry_count") or 0)
    payload["target_locales"] = list(manual_package.get("target_locales") or [])
    payload["requested_fields"] = list(manual_package.get("requested_fields") or [])
    no_write_confirmed = bool(
        manual_package.get("no_new_shopify_writes_performed") is True
        and manual_package.get("all_new_actions_no_write_confirmed") is True
        and manual_package.get("shopify_write_performed") is False
        and manual_package.get("mutation_performed") is False
        and manual_package.get("translations_register_called") is False
    )
    payload["no_write_confirmed"] = no_write_confirmed
    payload["validation_status"] = (
        "passed"
        if manual_package.get("package_status") == PACKAGE_READY_STATUS
        and int(manual_package.get("blocked_entry_count") or 0) == 0
        and not manual_package.get("blocking_conditions")
        and no_write_confirmed
        else "failed"
    )


def _env_blocking_conditions(payload, settings):
    reasons = []
    real_run_requested = settings.get("mode") in REAL_RUN_MODES and settings.get("dry_run") is False
    env_product_id = settings.get("env_product_id", "")
    env_max_entries = settings.get("env_max_entries")
    env_locales = settings.get("env_locales") or []
    env_fields = settings.get("env_fields") or []
    requested_locale = settings.get("requested_locale", "")
    requested_field = settings.get("requested_field", "")
    if real_run_requested:
        if not settings.get("ack_matches"):
            reasons.append("blocked_missing_or_invalid_real_write_ack")
        if not env_product_id:
            reasons.append("blocked_missing_real_write_product_id")
        elif env_product_id != DEFAULT_PRODUCT_ID:
            reasons.append("blocked_product_id_mismatch")
        if not settings.get("single_entry_only"):
            reasons.append("single_entry_only_not_enabled")
        if env_max_entries is None:
            reasons.append("blocked_missing_real_write_max_entries")
        elif int(env_max_entries) != 1:
            reasons.append("single_entry_max_entries_not_one")
        if not requested_locale or requested_locale not in ALLOWED_LOCALES:
            reasons.append("single_entry_locale_missing_or_invalid")
        if not requested_field or requested_field not in ALLOWED_FIELDS:
            reasons.append("single_entry_field_missing_or_invalid")
        if requested_locale != FIRST_REAL_WRITE_LOCALE or requested_field != FIRST_REAL_WRITE_FIELD:
            reasons.append("first_real_write_target_mismatch")
    elif env_product_id and env_product_id != DEFAULT_PRODUCT_ID:
        reasons.append("blocked_product_id_mismatch")

    if payload.get("single_entry_active"):
        if env_max_entries is not None and int(env_max_entries) != 1:
            reasons.append("single_entry_max_entries_not_one")
    elif env_max_entries is not None and int(env_max_entries) != int(payload.get("entry_count") or 0):
        reasons.append("blocked_max_entries_mismatch")
    if requested_locale and requested_locale not in ALLOWED_LOCALES:
        reasons.append("single_entry_locale_missing_or_invalid")
    if requested_field and requested_field not in ALLOWED_FIELDS:
        reasons.append("single_entry_field_missing_or_invalid")
    if env_locales and sorted(env_locales) != sorted(payload.get("target_locales") or []):
        reasons.append("blocked_locale_scope_mismatch")
    if env_fields and sorted(env_fields) != sorted(payload.get("requested_fields") or []):
        reasons.append("blocked_field_scope_mismatch")
    return reasons


def _manual_package_blocking_conditions(manual_package):
    reasons = []
    if manual_package.get("package_status") != PACKAGE_READY_STATUS:
        reasons.append("blocked_manual_action_package_not_ready")
    if int(manual_package.get("entry_count") or 0) <= 0:
        reasons.append("blocked_entry_count_zero")
    if int(manual_package.get("blocked_entry_count") or 0) > 0:
        reasons.append("manual_action_package_has_blocked_entries")
    if manual_package.get("blocking_conditions"):
        reasons.append("blocked_manual_action_package_has_blocking_conditions")
    for key, expected in {
        "real_write_allowed": False,
        "future_write_allowed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "real_apply_performed": False,
        "rollback_performed": False,
        "no_new_shopify_writes_performed": True,
        "all_new_actions_no_write_confirmed": True,
    }.items():
        if manual_package.get(key) is not expected:
            reasons.append(f"blocked_manual_action_package_{key}_not_confirmed")
    return reasons


def _manual_entries(manual_package):
    entries = []
    for item in manual_package.get("manual_action_entries", []):
        planned_value = item.get("planned_value") or item.get("proposed_translation", "")
        planned_key = item.get("planned_key") or item.get("field", "")
        entries.append(
            {
                "product_id": item.get("product_id", ""),
                "locale": item.get("locale", ""),
                "field": item.get("field", ""),
                "key": planned_key,
                "resource_key": planned_key,
                "translatable_content_key": planned_key,
                "digest": item.get("digest", ""),
                "source_value": item.get("source_value", ""),
                "planned_value": planned_value,
                "proposed_translation": item.get("proposed_translation")
                or item.get("planned_value", ""),
                "proposed_value_chars": len(planned_value),
                "planned_resource_id": item.get("planned_resource_id", ""),
                "current_translation_state": item.get("current_translation_state", {}),
                "write_input": {},
                "write_performed": False,
                "mutation_user_error": None,
                "post_write_value": "",
                "post_write_outdated": None,
                "verified": False,
                "would_write": bool(item.get("would_write")),
                "blocking_reasons": list(item.get("blocking_reasons") or []),
            }
        )
    return entries


def _apply_single_entry_gate(payload, settings, entries, real_run_requested):
    requested_locale = settings.get("requested_locale", "")
    requested_field = settings.get("requested_field", "")
    single_entry_active = bool(
        real_run_requested
        or settings.get("single_entry_only")
        or requested_locale
        or requested_field
    )
    payload["single_entry_active"] = single_entry_active
    payload["single_entry_only"] = bool(settings.get("single_entry_only"))
    payload["requested_locale"] = requested_locale
    payload["requested_field"] = requested_field
    payload["single_entry_blocking_conditions"] = []
    if not single_entry_active:
        payload["single_entry_candidate_count"] = 0
        payload["single_entry_selected"] = False
        return entries

    reasons = []
    if real_run_requested and not settings.get("single_entry_only"):
        reasons.append("single_entry_only_not_enabled")
    if real_run_requested and settings.get("env_max_entries") != 1:
        reasons.append("single_entry_max_entries_not_one")
    if not requested_locale or requested_locale not in ALLOWED_LOCALES:
        reasons.append("single_entry_locale_missing_or_invalid")
    if not requested_field or requested_field not in ALLOWED_FIELDS:
        reasons.append("single_entry_field_missing_or_invalid")

    candidates = [
        entry
        for entry in entries
        if entry.get("locale") == requested_locale
        and (entry.get("field") == requested_field or entry.get("key") == requested_field)
        and entry.get("would_write")
    ]
    payload["single_entry_candidate_count"] = len(candidates)
    if requested_locale in ALLOWED_LOCALES and requested_field in ALLOWED_FIELDS:
        if len(candidates) == 0:
            reasons.append("single_entry_target_not_found")
        elif len(candidates) > 1:
            reasons.append("single_entry_target_not_unique")
    selected_entries = candidates if len(candidates) == 1 else []
    if len(selected_entries) != 1:
        reasons.append("single_entry_count_not_one")
    payload["single_entry_selected"] = len(selected_entries) == 1 and not reasons
    payload["single_entry_blocking_conditions"] = _unique(reasons)
    payload["blocking_conditions"].extend(payload["single_entry_blocking_conditions"])
    payload["entry_count"] = len(selected_entries)
    return selected_entries


def _pre_write_readback(
    installation,
    product_id,
    target_locales,
    entries,
    single_entry_active=False,
    requested_locale="",
    requested_field="",
):
    by_locale = {}
    blocking_conditions = []
    for locale in target_locales:
        try:
            by_locale[locale] = fetch_translation_console_data(installation, product_id, locale)
        except Exception:
            blocking_conditions.append("blocked_pre_write_readback_failed")
            by_locale[locale] = {}

    target_state = {}
    if single_entry_active and not entries and requested_locale and requested_field:
        row = _row_for_key(by_locale.get(requested_locale) or {}, requested_field)
        if row:
            existing_present = bool(row.get("has_translation"))
            outdated = row.get("translation_outdated") is True
            target_state = {
                "digest": row.get("digest", ""),
                "existing_translation_present": existing_present,
                "existing_translation_value": row.get("translation_value", ""),
                "existing_translation_outdated": outdated,
            }
            if existing_present:
                blocking_conditions.append("single_entry_existing_current_translation")
            if outdated:
                blocking_conditions.append("single_entry_existing_outdated_translation")

    checked_entries = []
    for entry in entries:
        item = dict(entry)
        locale = item.get("locale", "")
        key = item.get("key", "")
        row = _row_for_key(by_locale.get(locale) or {}, key)
        digest = row.get("digest", "")
        existing_present = bool(row.get("has_translation"))
        existing_value = row.get("translation_value", "")
        outdated = row.get("translation_outdated") is True
        item["pre_write_digest"] = digest
        item["digest_matches"] = bool(digest and digest == item.get("digest"))
        item["pre_existing_translation_state"] = {
            "existing_translation_present": existing_present,
            "existing_translation_value": existing_value,
            "existing_translation_outdated": outdated,
        }
        item["pre_existing_translation_value"] = existing_value
        item["pre_outdated"] = outdated
        item["write_input"] = {
            "locale": locale,
            "key": key,
            "value": item.get("planned_value", ""),
            "translatableContentDigest": item.get("digest", ""),
        }
        if item.get("product_id") != product_id:
            item["blocking_reasons"].append("product_id_mismatch")
        if locale not in ALLOWED_LOCALES:
            item["blocking_reasons"].append("unsupported_locale")
        if key not in ALLOWED_FIELDS:
            item["blocking_reasons"].append("unsupported_field")
        if not item.get("digest"):
            item["blocking_reasons"].append("missing_digest")
        if not item.get("planned_value"):
            item["blocking_reasons"].append("missing_planned_value")
        if not item["digest_matches"]:
            item["blocking_reasons"].append("pre_write_digest_mismatch")
        if existing_present:
            item["blocking_reasons"].append("pre_write_existing_translation_present")
            if single_entry_active:
                item["blocking_reasons"].append("single_entry_existing_current_translation")
        if outdated:
            item["blocking_reasons"].append("pre_write_outdated_translation_present")
            if single_entry_active:
                item["blocking_reasons"].append("single_entry_existing_outdated_translation")
        item["blocking_reasons"] = _unique(item["blocking_reasons"])
        item["would_write"] = bool(item.get("would_write")) and not item["blocking_reasons"]
        if item["blocking_reasons"]:
            blocking_conditions.append("blocked_pre_write_entry_validation_failed")
        checked_entries.append(item)

    return {
        "performed": bool(by_locale),
        "all_digest_verified": bool(checked_entries)
        and all(entry.get("digest_matches") for entry in checked_entries),
        "entries": checked_entries,
        "target_state": target_state,
        "blocking_conditions": _unique(blocking_conditions),
    }


def _attach_single_entry_precheck_summary(payload):
    if not payload.get("single_entry_active") or not payload.get("entries"):
        return
    entry = payload["entries"][0]
    state = entry.get("pre_existing_translation_state") or {}
    payload["pre_write_existing_current_translation"] = bool(
        state.get("existing_translation_present")
    )
    payload["pre_write_existing_outdated_translation"] = bool(
        state.get("existing_translation_outdated")
    )
    payload["pre_write_digest"] = entry.get("pre_write_digest", "")
    single_reasons = [
        reason
        for reason in entry.get("blocking_reasons", [])
        if str(reason).startswith("single_entry_")
    ]
    payload["single_entry_blocking_conditions"] = _unique(
        list(payload.get("single_entry_blocking_conditions") or []) + single_reasons
    )


def _attach_single_entry_empty_candidate_precheck_summary(payload, target_state):
    if not payload.get("single_entry_active") or payload.get("entries") or not target_state:
        return
    payload["pre_write_existing_current_translation"] = bool(
        target_state.get("existing_translation_present")
    )
    payload["pre_write_existing_outdated_translation"] = bool(
        target_state.get("existing_translation_outdated")
    )
    payload["pre_write_digest"] = target_state.get("digest", "")
    reasons = []
    if target_state.get("existing_translation_present"):
        reasons.append("single_entry_existing_current_translation")
    if target_state.get("existing_translation_outdated"):
        reasons.append("single_entry_existing_outdated_translation")
    payload["single_entry_blocking_conditions"] = _unique(
        list(payload.get("single_entry_blocking_conditions") or []) + reasons
    )


def _translations_register(installation, product_id, entries):
    translation_inputs = [entry["write_input"] for entry in entries if entry.get("would_write")]
    query = """
    mutation translationsRegister($resourceId: ID!, $translations: [TranslationInput!]!) {
      translationsRegister(resourceId: $resourceId, translations: $translations) {
        translations {
          key
          locale
          value
          outdated
        }
        userErrors {
          field
          message
          code
        }
      }
    }
    """
    url = f"https://{installation.shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    try:
        response = requests.post(
            url,
            headers={
                "X-Shopify-Access-Token": installation.access_token,
                "Content-Type": "application/json",
            },
            json={
                "query": query,
                "variables": {
                    "resourceId": product_id,
                    "translations": translation_inputs,
                },
            },
            timeout=45,
        )
        http_status = response.status_code
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return {
            **_empty_mutation_result(),
            "called": True,
            "request_failed": True,
            "http_status": locals().get("http_status"),
            "failure_type": exc.__class__.__name__,
        }
    result = ((data.get("data") or {}).get("translationsRegister") or {})
    return {
        "called": True,
        "request_failed": bool(data.get("errors")),
        "http_status": http_status,
        "translations": result.get("translations") or [],
        "user_errors": result.get("userErrors") or data.get("errors") or [],
    }


def _empty_mutation_result():
    return {
        "called": False,
        "request_failed": False,
        "http_status": None,
        "translations": [],
        "user_errors": [],
    }


def _attach_mutation_result(payload, mutation_result):
    called = bool(mutation_result.get("called"))
    payload["translations_register_called"] = called
    payload["mutation_performed"] = called
    payload["shopify_write_performed"] = called
    payload["real_apply_performed"] = called and not mutation_result.get("user_errors")
    payload["translations_register_payload_count"] = sum(
        1 for entry in payload.get("entries", []) if entry.get("would_write")
    )
    payload["write_attempted_count"] = (
        payload["translations_register_payload_count"] if called else 0
    )
    payload["write_succeeded_count"] = (
        payload["translations_register_payload_count"]
        if called
        and not mutation_result.get("user_errors")
        and not mutation_result.get("request_failed")
        else 0
    )
    payload["translations_register_user_errors"] = mutation_result.get("user_errors") or []
    payload["user_errors_count"] = len(payload["translations_register_user_errors"])
    for entry in payload["entries"]:
        entry["write_performed"] = called and entry.get("would_write")
        entry["mutation_user_error"] = None


def _post_write_readback(installation, product_id, target_locales, entries):
    by_locale = {}
    blocking_conditions = []
    for locale in target_locales:
        try:
            by_locale[locale] = fetch_translation_console_data(installation, product_id, locale)
        except Exception:
            blocking_conditions.append("blocked_post_write_readback_failed")
            by_locale[locale] = {}
    verified_count = 0
    output_entries = []
    for entry in entries:
        item = dict(entry)
        row = _row_for_key(by_locale.get(item.get("locale", "")) or {}, item.get("key", ""))
        item["post_write_value"] = row.get("translation_value", "")
        item["post_write_readback_value_chars"] = len(item["post_write_value"])
        item["post_write_readback_value_digest"] = _value_digest(item["post_write_value"])
        item["post_write_outdated"] = row.get("translation_outdated")
        item["verified"] = (
            bool(item.get("write_performed"))
            and item["post_write_value"] == item.get("planned_value")
            and row.get("translation_outdated") is not True
        )
        if item.get("write_performed") and not item["verified"]:
            item["blocking_reasons"] = _unique(
                list(item.get("blocking_reasons") or []) + ["post_write_readback_mismatch"]
            )
            blocking_conditions.append("blocked_post_write_verification_failed")
        if item["verified"]:
            verified_count += 1
        output_entries.append(item)
    written_count = sum(1 for entry in output_entries if entry.get("write_performed"))
    return {
        "performed": bool(by_locale),
        "verified_count": verified_count,
        "all_verified": written_count > 0 and verified_count == written_count,
        "entries": output_entries,
        "blocking_conditions": _unique(blocking_conditions),
    }


def _row_for_key(console_data, key):
    for row in console_data.get("translatable_rows", []) or []:
        if row.get("key") == key:
            return row
    return {}


def _status(payload, dry_run, mutation_called):
    if dry_run:
        return "dry_run_real_write_not_executed"
    if payload.get("blocking_conditions") and not mutation_called:
        return "blocked_real_write_preconditions_failed"
    if mutation_called and payload.get("blocking_conditions"):
        if payload.get("single_entry_active"):
            return "single_entry_real_write_failed_or_unverified"
        return "real_write_failed_needs_manual_review"
    if mutation_called and payload.get("post_write_verified"):
        if payload.get("single_entry_active"):
            return "single_entry_real_write_succeeded_and_verified"
        return "real_write_completed_and_verified"
    if mutation_called:
        if payload.get("single_entry_active"):
            return "single_entry_real_write_failed_or_unverified"
        return "real_write_failed_needs_manual_review"
    return "blocked_real_write_preconditions_failed"


def _finalize(payload):
    payload["blocking_conditions"] = _unique(payload.get("blocking_conditions") or [])
    payload["rollback_required"] = bool(
        payload.get("translations_register_called") and not payload.get("post_write_verified")
    )
    payload["rollback_approval_required"] = payload["rollback_required"]
    payload["no_new_shopify_writes_performed"] = not bool(payload.get("shopify_write_performed"))
    payload["all_new_actions_no_write_confirmed"] = not bool(
        payload.get("shopify_write_performed")
        or payload.get("mutation_performed")
        or payload.get("translations_register_called")
    )
    payload["no_unverified_write"] = bool(
        not payload.get("translations_register_called")
        or (
            payload.get("post_write_verified")
            and not payload.get("rollback_required")
        )
    )
    payload["entries"] = [
        _report_entry(entry)
        for entry in payload.get("entries", [])
        if entry.get("would_write")
    ]
    payload["would_write_count"] = len(payload["entries"])
    if payload.get("single_entry_active"):
        payload["single_entry_selected"] = (
            payload.get("single_entry_candidate_count") == 1
            and len(payload["entries"]) == 1
            and not payload.get("single_entry_blocking_conditions")
        )
    _attach_preflight_result(payload)
    _attach_locked_real_write_package(payload)
    _attach_post_write_audit(payload)
    payload["generated_at"] = _utc_now()
    return payload


def _attach_preflight_result(payload):
    payload["real_write_target_product_id"] = DEFAULT_PRODUCT_ID
    payload["real_write_target_locale"] = FIRST_REAL_WRITE_LOCALE
    payload["real_write_target_field"] = FIRST_REAL_WRITE_FIELD
    payload["real_write_target_max_entries"] = FIRST_REAL_WRITE_MAX_ENTRIES
    payload["post_write_readback_required"] = True
    payload["real_write_next_command_preview"] = _real_write_next_command_preview()
    mismatch = bool(
        payload.get("single_entry_active")
        and not _first_real_write_target_matches(payload)
    )
    payload["first_real_write_target_mismatch"] = mismatch
    warnings = list(payload.get("preflight_warnings") or [])
    if mismatch and "first_real_write_target_mismatch" not in payload.get("blocking_conditions", []):
        warnings.append("first_real_write_target_mismatch")
    payload["preflight_warnings"] = _unique(warnings)

    ready = bool(
        payload.get("dry_run") is True
        and payload.get("single_entry_active")
        and payload.get("single_entry_only") is True
        and _first_real_write_target_matches(payload)
        and payload.get("single_entry_candidate_count") == 1
        and payload.get("single_entry_selected") is True
        and payload.get("entry_count") == 1
        and payload.get("would_write_count") == 1
        and payload.get("pre_write_readback_checked") is True
        and payload.get("pre_write_existing_current_translation") is False
        and payload.get("pre_write_existing_outdated_translation") is False
        and bool(payload.get("pre_write_digest"))
        and payload.get("translations_register_payload_count") == 1
        and payload.get("validation_status") == "passed"
        and payload.get("manual_action_package_status") == PACKAGE_READY_STATUS
        and payload.get("no_write_confirmed") is True
        and not payload.get("blocking_conditions")
    )
    payload["manual_real_write_allowed_next_step"] = ready
    if ready:
        payload["preflight_status"] = "single_entry_real_write_preflight_ready"
    elif not payload.get("single_entry_active"):
        payload["preflight_status"] = "single_entry_real_write_preflight_not_requested"
    elif payload.get("blocking_conditions"):
        payload["preflight_status"] = "single_entry_real_write_preflight_blocked"
    elif mismatch:
        payload["preflight_status"] = "single_entry_real_write_preflight_target_mismatch"
    else:
        payload["preflight_status"] = "single_entry_real_write_preflight_not_ready"


def _single_entry_preflight_gate_ready(payload):
    return bool(
        payload.get("single_entry_active")
        and payload.get("single_entry_only") is True
        and _first_real_write_target_matches(payload)
        and payload.get("single_entry_candidate_count") == 1
        and payload.get("single_entry_selected") is True
        and payload.get("entry_count") == 1
        and payload.get("would_write_count") == 1
        and payload.get("pre_write_readback_checked") is True
        and payload.get("pre_write_existing_current_translation") is False
        and payload.get("pre_write_existing_outdated_translation") is False
        and bool(payload.get("pre_write_digest"))
        and payload.get("translations_register_payload_count") == 1
        and payload.get("validation_status") == "passed"
        and payload.get("manual_action_package_status") == PACKAGE_READY_STATUS
        and payload.get("no_write_confirmed") is True
        and not payload.get("blocking_conditions")
    )


def _attach_locked_real_write_package(payload):
    command = _real_write_next_command_preview()
    payload["locked_real_write_target"] = {
        "product_id": DEFAULT_PRODUCT_ID,
        "locale": FIRST_REAL_WRITE_LOCALE,
        "field": FIRST_REAL_WRITE_FIELD,
        "max_entries": FIRST_REAL_WRITE_MAX_ENTRIES,
        "single_entry_only": True,
    }
    payload["locked_real_write_command_powershell"] = command
    payload["locked_real_write_required_env"] = {
        "SHOPIFY_TRANSLATION_REAL_WRITE_ACK": ACK_VALUE,
        "SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID": DEFAULT_PRODUCT_ID,
        "SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES": str(FIRST_REAL_WRITE_MAX_ENTRIES),
        "SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN": "0",
        "SHOPIFY_TRANSLATION_REAL_WRITE_SINGLE_ENTRY_ONLY": "1",
        "SHOPIFY_TRANSLATION_REAL_WRITE_LOCALE": FIRST_REAL_WRITE_LOCALE,
        "SHOPIFY_TRANSLATION_REAL_WRITE_FIELD": FIRST_REAL_WRITE_FIELD,
    }
    payload["locked_real_write_safety_checklist"] = [
        "This is a real Shopify write and must be run manually by the user.",
        "It may write exactly one translation entry: de/meta_title for the fixed product.",
        "Abort if product_id, locale, field, max entries, or single-entry flag differ.",
        "Abort if pre-write readback shows current or outdated translation.",
        "Abort if digest changed, payload count is not exactly 1, or blocking_conditions is not empty.",
        "Rollback is never automatic; failures require a separate rollback approval package.",
    ]
    payload["post_write_audit_expected_fields"] = [
        "execution_status",
        "audit_status",
        "mode",
        "dry_run",
        "real_write_allowed",
        "shopify_api_call_performed",
        "shopify_write_performed",
        "mutation_performed",
        "translations_register_called",
        "translations_register_payload_count",
        "write_attempted_count",
        "write_succeeded_count",
        "verified_count",
        "post_write_readback_checked",
        "post_write_readback_matches",
        "post_write_readback_value_digest",
        "post_write_readback_value_chars",
        "rollback_approval_required",
        "rollback_performed",
        "blocking_conditions",
    ]
    payload["abort_conditions"] = [
        "SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN is not 0",
        "ACK does not exactly match I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE",
        "product_id does not exactly match gid://shopify/Product/7655686799427",
        "locale is not de",
        "field is not meta_title",
        "MAX_ENTRIES is not 1",
        "SINGLE_ENTRY_ONLY is not 1",
        "entry_count is not 1",
        "single_entry_candidate_count is not 1",
        "selected entries count is not 1",
        "preflight_status is not single_entry_real_write_preflight_ready",
        "pre-write readback shows current translation",
        "pre-write readback shows outdated translation",
        "translations_register_payload_count is not 1",
        "blocking_conditions is not empty",
        "first_real_write_target_mismatch is true",
    ]
    payload["post_real_write_check_command_powershell"] = [_post_real_write_check_command()]
    payload["locked_real_write_ready"] = bool(
        payload.get("preflight_status") == "single_entry_real_write_preflight_ready"
        and payload.get("manual_real_write_allowed_next_step") is True
        and payload.get("product_id") == DEFAULT_PRODUCT_ID
        and payload.get("requested_locale") == FIRST_REAL_WRITE_LOCALE
        and payload.get("requested_field") == FIRST_REAL_WRITE_FIELD
        and payload.get("single_entry_candidate_count") == 1
        and payload.get("entry_count") == 1
        and payload.get("would_write_count") == 1
        and not payload.get("blocking_conditions")
        and payload.get("dry_run") is True
        and payload.get("real_write_allowed") is False
        and payload.get("shopify_write_performed") is False
        and payload.get("translations_register_called") is False
    )


def _attach_post_write_audit(payload):
    written_entries = [
        entry for entry in payload.get("entries", []) if entry.get("write_performed")
    ]
    first_written = written_entries[0] if written_entries else {}
    payload["post_write_readback_value_digest"] = first_written.get(
        "post_write_readback_value_digest", ""
    )
    payload["post_write_readback_value_chars"] = int(
        first_written.get("post_write_readback_value_chars") or 0
    )
    if payload.get("translations_register_called") and payload.get("post_write_verified"):
        payload["audit_status"] = "single_entry_real_write_audit_passed"
    elif payload.get("translations_register_called"):
        payload["audit_status"] = "single_entry_real_write_audit_failed_or_needs_review"
    elif payload.get("dry_run"):
        payload["audit_status"] = "single_entry_real_write_audit_not_run_dry_run"
    else:
        payload["audit_status"] = "single_entry_real_write_audit_not_run"
    payload["audit_summary"] = {
        "execution_status": payload.get("execution_status", ""),
        "audit_status": payload.get("audit_status", ""),
        "write_attempted_count": payload.get("write_attempted_count", 0),
        "write_succeeded_count": payload.get("write_succeeded_count", 0),
        "verified_count": payload.get("verified_count", 0),
        "post_write_readback_checked": payload.get("post_write_readback_checked", False),
        "post_write_readback_matches": payload.get("post_write_readback_matches", False),
        "rollback_approval_required": payload.get("rollback_approval_required", False),
        "rollback_performed": payload.get("rollback_performed", False),
    }


def _first_real_write_target_matches(payload):
    return bool(
        payload.get("product_id") == DEFAULT_PRODUCT_ID
        and payload.get("requested_locale") == FIRST_REAL_WRITE_LOCALE
        and payload.get("requested_field") == FIRST_REAL_WRITE_FIELD
    )


def _real_write_next_command_preview():
    return [
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_ACK="I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID="gid://shopify/Product/7655686799427"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES="1"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN="0"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_SINGLE_ENTRY_ONLY="1"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_LOCALE="de"',
        '$env:SHOPIFY_TRANSLATION_REAL_WRITE_FIELD="meta_title"',
        "python remote_approval_runner.py --task shopify_translation_selected_product_real_write_execute --mode real-run --approval local",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_ACK",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_PRODUCT_ID",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_MAX_ENTRIES",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_DRY_RUN",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_SINGLE_ENTRY_ONLY",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_LOCALE",
        "Remove-Item Env:SHOPIFY_TRANSLATION_REAL_WRITE_FIELD",
    ]


def _post_real_write_check_command():
    return (
        "python -c \"import json; "
        "p='logs/shopify_translation_selected_product_real_write_execute.json'; "
        "d=json.load(open(p,encoding='utf-8')); "
        "keys=['execution_status','audit_status','mode','dry_run','real_write_allowed',"
        "'shopify_api_call_performed','shopify_write_performed','mutation_performed',"
        "'translations_register_called','translations_register_payload_count',"
        "'write_attempted_count','write_succeeded_count','verified_count',"
        "'post_write_readback_checked','post_write_readback_matches',"
        "'rollback_approval_required','rollback_performed','blocking_conditions',"
        "'requested_locale','requested_field','entry_count','would_write_count']; "
        "print(json.dumps({k:d.get(k) for k in keys}, ensure_ascii=False, indent=2))\""
    )


def _report_entry(entry):
    key = entry.get("key") or entry.get("field", "")
    planned_value = entry.get("planned_value") or entry.get("proposed_translation", "")
    blocking_reasons = _unique(entry.get("blocking_reasons") or [])
    return {
        "product_id": entry.get("product_id", ""),
        "locale": entry.get("locale", ""),
        "field": entry.get("field", ""),
        "key": key,
        "resource_key": entry.get("resource_key") or key,
        "translatable_content_key": entry.get("translatable_content_key") or key,
        "digest": entry.get("digest", ""),
        "pre_write_digest": entry.get("pre_write_digest", ""),
        "digest_matches": bool(entry.get("digest_matches")),
        "proposed_value_chars": len(planned_value),
        "blocked": bool(blocking_reasons),
        "blocking_conditions": blocking_reasons,
        "would_write": bool(entry.get("would_write")),
        "write_performed": bool(entry.get("write_performed")),
        "verified": bool(entry.get("verified")),
        "pre_existing_translation_present": bool(
            (entry.get("pre_existing_translation_state") or {}).get(
                "existing_translation_present"
            )
        ),
        "pre_existing_translation_outdated": bool(
            (entry.get("pre_existing_translation_state") or {}).get(
                "existing_translation_outdated"
            )
        ),
        "post_write_outdated": entry.get("post_write_outdated"),
        "post_write_readback_value_digest": entry.get("post_write_readback_value_digest", ""),
        "post_write_readback_value_chars": int(entry.get("post_write_readback_value_chars") or 0),
    }


def _value_digest(value):
    if not value:
        return ""
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
