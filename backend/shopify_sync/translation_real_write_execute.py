import json
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
PHASE = "16.2"
DEFAULT_PRODUCT_ID = "gid://shopify/Product/7655686799427"
DEFAULT_TARGET_LOCALES = ["ja", "de", "fr", "es", "it"]
DEFAULT_FIELDS = ["title", "meta_title", "meta_description"]
ALLOWED_LOCALES = set(DEFAULT_TARGET_LOCALES)
ALLOWED_FIELDS = set(DEFAULT_FIELDS)
ACK_VALUE = "I_APPROVE_SELECTED_PRODUCT_TRANSLATION_REAL_WRITE"
REAL_RUN_MODES = {"real-run", "execute-real-write"}
MUTATION_NAME = "translationsRegister"


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
    payload["blocking_conditions"].extend(_env_blocking_conditions(payload, settings))
    payload["blocking_conditions"].extend(_manual_package_blocking_conditions(manual_package))

    entries = _manual_entries(manual_package)
    precheck = _pre_write_readback(installation, product_id, target_locales, entries)
    payload["pre_write_readback_performed"] = precheck["performed"]
    payload["pre_write_digest_verified"] = precheck["all_digest_verified"]
    payload["shopify_api_call_performed"] = precheck["performed"]
    payload["entries"] = precheck["entries"]
    payload["blocking_conditions"].extend(precheck["blocking_conditions"])

    payload["would_write_count"] = sum(1 for entry in payload["entries"] if entry.get("would_write"))
    real_run_requested = mode in REAL_RUN_MODES and not dry_run
    payload["real_run_requested"] = bool(real_run_requested)
    payload["real_write_allowed"] = bool(real_run_requested and not payload["blocking_conditions"])

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
        payload["post_write_verified"] = postcheck["all_verified"]
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
        "target_locales": target_locales,
        "requested_fields": requested_fields,
        "locked_executor_report_path": "logs/shopify_translation_selected_product_locked_executor_shell.json",
        "real_write_executor_report_path": "logs/shopify_translation_selected_product_real_write_execute.json",
        "manual_action_package_status": "",
        "manual_action_package_report_path": "",
        "pre_write_readback_performed": False,
        "pre_write_digest_verified": False,
        "shopify_api_call_performed": False,
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "translations_register_user_errors": [],
        "post_write_readback_performed": False,
        "post_write_verified": False,
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
    payload["blocked_entry_count"] = int(manual_package.get("blocked_entry_count") or 0)
    payload["target_locales"] = list(manual_package.get("target_locales") or [])
    payload["requested_fields"] = list(manual_package.get("requested_fields") or [])


def _env_blocking_conditions(payload, settings):
    reasons = []
    real_run_requested = settings.get("mode") in REAL_RUN_MODES and settings.get("dry_run") is False
    env_product_id = settings.get("env_product_id", "")
    env_max_entries = settings.get("env_max_entries")
    env_locales = settings.get("env_locales") or []
    env_fields = settings.get("env_fields") or []
    if real_run_requested:
        if not settings.get("ack_matches"):
            reasons.append("blocked_missing_or_invalid_real_write_ack")
        if not env_product_id:
            reasons.append("blocked_missing_real_write_product_id")
        elif env_product_id != DEFAULT_PRODUCT_ID:
            reasons.append("blocked_product_id_mismatch")
        if env_max_entries is None:
            reasons.append("blocked_missing_real_write_max_entries")
        elif int(env_max_entries) != int(payload.get("entry_count") or 0):
            reasons.append("blocked_max_entries_mismatch")
    elif env_product_id and env_product_id != DEFAULT_PRODUCT_ID:
        reasons.append("blocked_product_id_mismatch")

    if env_max_entries is not None and int(env_max_entries) != int(payload.get("entry_count") or 0):
        reasons.append("blocked_max_entries_mismatch")
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
        reasons.append("blocked_manual_action_package_blocked_entries")
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
        entries.append(
            {
                "product_id": item.get("product_id", ""),
                "locale": item.get("locale", ""),
                "field": item.get("field", ""),
                "key": item.get("planned_key") or item.get("field", ""),
                "digest": item.get("digest", ""),
                "source_value": item.get("source_value", ""),
                "planned_value": item.get("planned_value")
                or item.get("proposed_translation", ""),
                "proposed_translation": item.get("proposed_translation")
                or item.get("planned_value", ""),
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


def _pre_write_readback(installation, product_id, target_locales, entries):
    by_locale = {}
    blocking_conditions = []
    for locale in target_locales:
        try:
            by_locale[locale] = fetch_translation_console_data(installation, product_id, locale)
        except Exception:
            blocking_conditions.append("blocked_pre_write_readback_failed")
            by_locale[locale] = {}

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
        if outdated:
            item["blocking_reasons"].append("pre_write_outdated_translation_present")
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
        "blocking_conditions": _unique(blocking_conditions),
    }


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
    if mutation_called and payload.get("post_write_verified"):
        return "real_write_completed_and_verified"
    if mutation_called:
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
    payload["generated_at"] = _utc_now()
    return payload


def _utc_now():
    return datetime.now(timezone.utc).isoformat()


def _unique(values):
    output = []
    for value in values:
        if value and value not in output:
            output.append(value)
    return output
