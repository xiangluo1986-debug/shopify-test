import re
from datetime import datetime, timezone

import requests


SHOPIFY_API_VERSION = "2026-01"
SUPPORTED_TRANSLATION_LOCALES = ("ja", "de", "fr", "es", "it")
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/\d+$")
NUMERIC_PRODUCT_ID_RE = re.compile(r"^\d+$")
SHOPIFY_GID_TYPE_RE = re.compile(r"^gid://shopify/([^/]+)/")
MAX_SEARCH_RESULTS = 5
MAX_CHILD_TRANSLATABLE_RESOURCES = 250
MAX_CHILD_RESOURCE_ID_LOOKUP = 250
MAX_PRODUCT_OPTIONS = 20
MAX_PRODUCT_VARIANTS = 100
MAX_PRODUCT_METAFIELDS = 100
MAX_PRODUCT_MEDIA = 100
OPTIONAL_CHILD_RESOURCE_GROUPS = ("options", "variants", "metafields", "media")
DISCOVERY_STATUS_KEYS = (
    "product_basics",
    "seo",
    "options",
    "variants",
    "important_metafields",
    "technical_metafields",
    "media",
    "media_alt_text",
)
CHILD_RESOURCE_STATUS_KEYS = {
    "options": ("options",),
    "variants": ("variants",),
    "metafields": ("important_metafields", "technical_metafields"),
    "media": ("media", "media_alt_text"),
}
DISCOVERY_GROUP_LABELS = {
    "product": "Product",
    "product_basics": "Product basics",
    "seo": "SEO",
    "options": "Options",
    "variants": "Variants",
    "metafields": "Metafields",
    "important_metafields": "Important metafields",
    "technical_metafields": "Technical metafields",
    "media": "Media",
    "media_alt_text": "Media alt text",
}
SECRET_ASSIGNMENT_RE = re.compile(
    r"\b(access[_-]?token|secret|password|api[_-]?key|authorization)\s*[:=]\s*[^,\s;]+",
    flags=re.IGNORECASE,
)
SECRET_LIKE_RE = re.compile(
    r"\b(?:shpat_|shpca_|shppa_|shpss_|sk-)[A-Za-z0-9_\-]+\b|\b[A-Za-z0-9_\-]{48,}\b"
)

IMPORTANT_METAFIELD_NAMESPACES = {
    "custom",
    "details",
    "descriptor",
    "descriptors",
    "features",
    "spec",
    "specs",
    "specification",
    "specifications",
}
IMPORTANT_METAFIELD_HINTS = (
    "benefit",
    "bullet",
    "compat",
    "description",
    "feature",
    "highlight",
    "included",
    "material",
    "model",
    "package",
    "scale",
    "short_description",
    "size",
    "spec",
    "subtitle",
    "summary",
)
TECHNICAL_METAFIELD_NAMESPACES = {
    "google",
    "inventory",
    "judgeme",
    "okendo",
    "reviews",
    "shopify",
    "stamped",
    "system",
    "yotpo",
}
TECHNICAL_FIELD_HINTS = (
    "admin_graphql",
    "barcode",
    "count",
    "created",
    "gid",
    "gtin",
    "hash",
    "id",
    "inventory",
    "json",
    "mpn",
    "rating",
    "schema",
    "sku",
    "sync",
    "template",
    "timestamp",
    "token",
    "updated",
)
TECHNICAL_VALUE_TYPES = {
    "boolean",
    "color",
    "dimension",
    "id",
    "json",
    "money",
    "number",
    "rating",
    "url",
    "volume",
    "weight",
}
IDENTIFIER_LIKE_RE = re.compile(
    r"^(?:gid://|[A-Z0-9._:-]{6,}|[0-9]+|[0-9A-F]{8,})$",
    flags=re.IGNORECASE,
)
DEFAULT_OPTION_SOURCE_VALUES = {"default title", "title"}


class ShopifyTranslationConsoleError(Exception):
    def __init__(
        self,
        message,
        stage="read_only_shopify_query",
        resource_group="product",
        query_failure_type="shopify_read_query_failed",
    ):
        self.stage = stage or "read_only_shopify_query"
        self.resource_group = resource_group or "product"
        self.query_failure_type = query_failure_type or "shopify_read_query_failed"
        self.safe_message = sanitize_shopify_error_message(message)
        super().__init__(self.safe_message)


def sanitize_shopify_error_message(message):
    text = str(message or "").strip()
    if not text:
        return "Shopify read-only query failed."
    text = SECRET_ASSIGNMENT_RE.sub(lambda match: f"{match.group(1)}=[redacted]", text)
    text = SECRET_LIKE_RE.sub("[redacted]", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:500] or "Shopify read-only query failed."


def translation_console_error_details(exc, stage="", resource_group=""):
    if isinstance(exc, ShopifyTranslationConsoleError):
        return {
            "stage": exc.stage or stage or "read_only_shopify_query",
            "resource_group": exc.resource_group or resource_group or "product",
            "query_failure_type": exc.query_failure_type or "shopify_read_query_failed",
            "message": exc.safe_message,
        }
    return {
        "stage": stage or "read_only_shopify_query",
        "resource_group": resource_group or "product",
        "query_failure_type": _query_failure_type_for_exception(exc),
        "message": sanitize_shopify_error_message(str(exc) or type(exc).__name__),
    }


def safe_translation_console_error_message(exc, stage="", resource_group=""):
    details = translation_console_error_details(exc, stage=stage, resource_group=resource_group)
    return (
        "Read-only Shopify query failed during "
        f"{details['stage']} for {details['resource_group']}: {details['message']}"
    )


def _query_failure_type_for_exception(exc):
    if isinstance(exc, requests.HTTPError):
        return "shopify_http_error"
    if isinstance(exc, requests.RequestException):
        return "shopify_request_error"
    if isinstance(exc, ValueError):
        return "shopify_invalid_json"
    return f"unexpected_{_slug(type(exc).__name__)}"


def normalize_product_gid(value):
    value = (value or "").strip()
    if PRODUCT_GID_RE.fullmatch(value):
        return value
    if NUMERIC_PRODUCT_ID_RE.fullmatch(value):
        return f"gid://shopify/Product/{value}"
    return ""


def fetch_translation_console_data(installation, search_text, locale):
    source_fetched_at = _utc_now_iso()
    search_text = (search_text or "").strip()
    locale = (locale or "ja").strip()
    if locale not in SUPPORTED_TRANSLATION_LOCALES:
        raise ShopifyTranslationConsoleError(f"Unsupported locale: {locale}")
    if not search_text:
        raise ShopifyTranslationConsoleError("Enter a product ID, title, or handle to fetch read-only data.")

    product_gid = normalize_product_gid(search_text)
    if product_gid:
        result = _fetch_product_translation_resource(installation, product_gid, locale)
    else:
        result = _search_products(installation, search_text)
        if len(result["search_results"]) == 1:
            product_id = result["search_results"][0]["id"]
            fetched = _fetch_product_translation_resource(installation, product_id, locale)
            result.update(fetched)

    result.update(_safety_flags(shopify_api_call_performed=True))
    result["source_fetched_live_from_shopify"] = True
    result["source_fetched_at"] = source_fetched_at
    result["locale"] = locale
    result["search_text"] = search_text
    return result


def _utc_now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )


def _fetch_product_translation_resource(installation, product_gid, locale):
    product, resource = _fetch_product_base_translation_resource(
        installation,
        product_gid,
        locale,
    )
    product_context = _build_product_resource_context(product)
    resource_by_id = {
        resource.get("resourceId"): resource,
    }
    per_group_status, per_group_reasons = _initial_discovery_status()
    per_group_status["product_basics"] = "ok"
    per_group_status["seo"] = "ok"
    child_discovery_errors = []

    for child_group in OPTIONAL_CHILD_RESOURCE_GROUPS:
        try:
            child_product = _fetch_product_child_context(installation, product_gid, child_group)
            child_context = _build_product_resource_context(child_product)
            _merge_product_resource_context(product_context, child_context)
            child_resource_ids = _product_child_resource_ids(child_context)
            for child_resource in _fetch_translatable_resources_by_ids(
                installation,
                child_resource_ids[:MAX_CHILD_RESOURCE_ID_LOOKUP],
                locale,
                resource_group=child_group,
            ):
                if child_resource.get("resourceId"):
                    resource_by_id[child_resource["resourceId"]] = child_resource
            _mark_discovery_status(per_group_status, per_group_reasons, child_group, "ok")
        except Exception as exc:
            child_discovery_errors.append(
                _child_discovery_error(
                    exc,
                    stage=f"{child_group}_child_resource_discovery",
                    resource_group=child_group,
                )
            )
            _mark_discovery_status(
                per_group_status,
                per_group_reasons,
                child_group,
                "skipped",
                "skipped_child_resource_query_failed",
            )

    rows = []
    for normalized_resource in resource_by_id.values():
        rows.extend(
            _normalize_translatable_resource_rows(
                normalized_resource,
                locale,
                product_context,
            )
        )
    rows.extend(
        _visible_product_option_fallback_rows(
            product_context,
            resource_by_id,
            rows,
            locale,
        )
    )

    return {
        "product": _normalize_product(product),
        "search_results": [],
        "translatable_resource": {
            "resource_id": resource.get("resourceId", ""),
            "translatable_content_count": len(rows),
            "translation_count": len(resource.get("translations", [])),
            "nested_resource_count": 0,
            "child_resource_count": len(resource_by_id) - 1,
            "child_resource_discovery_error_count": len(child_discovery_errors),
        },
        "translatable_rows": rows,
        "child_resource_discovery_errors": child_discovery_errors,
        "per_group_discovery_status": per_group_status,
        "per_group_discovery_reasons": per_group_reasons,
    }


def _fetch_product_base_translation_resource(installation, product_gid, locale):
    query = """
    query($id: ID!, $locale: String!) {
      product(id: $id) {
        id
        title
        handle
        status
        productType
        vendor
      }
      translatableResource(resourceId: $id) {
        resourceId
        translatableContent {
          key
          value
          digest
          locale
        }
        translations(locale: $locale) {
          key
          value
          locale
          outdated
        }
      }
    }
    """
    data = shopify_graphql_read_only(
        installation,
        query,
        {"id": product_gid, "locale": locale},
        stage="product_base_translatable_resource_query",
        resource_group="product",
    )
    product = data.get("product")
    resource = data.get("translatableResource")
    if not product:
        raise ShopifyTranslationConsoleError(
            f"Shopify product not found for {product_gid}.",
            stage="product_base_lookup",
            resource_group="product",
            query_failure_type="shopify_product_not_found",
        )
    if not resource:
        raise ShopifyTranslationConsoleError(
            f"Translatable resource not found for {product_gid}.",
            stage="product_base_translatable_resource_query",
            resource_group="product",
            query_failure_type="shopify_translatable_resource_not_found",
        )
    return product, resource


def _fetch_product_child_context(installation, product_gid, resource_group):
    if resource_group == "options":
        return _fetch_product_options_child_context(installation, product_gid)
    query = _child_context_query(resource_group)
    data = shopify_graphql_read_only(
        installation,
        query,
        {"id": product_gid},
        stage=f"{resource_group}_product_child_context_query",
        resource_group=resource_group,
    )
    product = data.get("product")
    if not product:
        raise ShopifyTranslationConsoleError(
            "Shopify product child query returned no product.",
            stage=f"{resource_group}_product_child_context_query",
            resource_group=resource_group,
            query_failure_type="shopify_product_child_context_missing",
        )
    return product


def _fetch_product_options_child_context(installation, product_gid):
    try:
        data = shopify_graphql_read_only(
            installation,
            _child_context_query("options"),
            {"id": product_gid},
            stage="options_product_child_context_query",
            resource_group="options",
        )
    except ShopifyTranslationConsoleError:
        data = shopify_graphql_read_only(
            installation,
            _child_context_query("options_fallback"),
            {"id": product_gid},
            stage="options_product_child_context_fallback_query",
            resource_group="options",
        )
    product = data.get("product")
    if not product:
        raise ShopifyTranslationConsoleError(
            "Shopify product options query returned no product.",
            stage="options_product_child_context_query",
            resource_group="options",
            query_failure_type="shopify_product_child_context_missing",
        )
    return product


def _child_context_query(resource_group):
    if resource_group == "options":
        return """
        query($id: ID!) {
          product(id: $id) {
            id
            options(first: 20) {
            id
            name
            position
            values
            optionValues {
              id
              name
            }
            }
          }
        }
        """
    if resource_group == "options_fallback":
        return """
        query($id: ID!) {
          product(id: $id) {
            id
            options(first: 20) {
              id
              name
              position
              values
            }
          }
        }
        """
    if resource_group == "variants":
        return """
        query($id: ID!) {
          product(id: $id) {
            id
            variants(first: 100) {
              edges {
                node {
                  id
                  title
                  sku
                  barcode
                  selectedOptions {
                    name
                    value
                  }
                }
              }
            }
          }
        }
        """
    if resource_group == "metafields":
        return """
        query($id: ID!) {
          product(id: $id) {
            id
            metafields(first: 100) {
              edges {
                node {
                  id
                  namespace
                  key
                  type
                  value
                }
              }
            }
          }
        }
        """
    if resource_group == "media":
        return """
        query($id: ID!) {
          product(id: $id) {
            id
            media(first: 100) {
              edges {
                node {
                  id
                  alt
                  mediaContentType
                  ... on MediaImage {
                    image {
                      url
                    }
                  }
                }
              }
            }
          }
        }
        """
    raise ShopifyTranslationConsoleError(
        f"Unsupported child resource group: {resource_group}",
        stage="child_resource_discovery",
        resource_group=resource_group,
        query_failure_type="unsupported_child_resource_group",
    )


def _fetch_translatable_resources_by_ids(installation, resource_ids, locale, resource_group="child"):
    resource_ids = [resource_id for resource_id in resource_ids or [] if resource_id]
    if not resource_ids:
        return []
    query = """
    query($ids: [ID!]!, $locale: String!, $first: Int!) {
      translatableResourcesByIds(first: $first, resourceIds: $ids) {
        edges {
          node {
            resourceId
            translatableContent {
              key
              value
              digest
              locale
            }
            translations(locale: $locale) {
              key
              value
              locale
              outdated
            }
          }
        }
      }
    }
    """
    data = shopify_graphql_read_only(
        installation,
        query,
        {"ids": resource_ids, "locale": locale, "first": len(resource_ids)},
        stage=f"{resource_group}_child_translatable_resource_query",
        resource_group=resource_group,
    )
    return [
        edge.get("node") or {}
        for edge in ((data.get("translatableResourcesByIds") or {}).get("edges") or [])
        if edge.get("node")
    ]


def _normalize_translatable_resource_rows(resource, locale, product_context):
    resource_id = resource.get("resourceId", "")
    translations_by_key = {
        item.get("key"): item
        for item in resource.get("translations", [])
        if item.get("key")
    }
    rows = []
    for item in resource.get("translatableContent", []):
        translation = translations_by_key.get(item.get("key")) or {}
        rows.append(
            _normalize_translatable_content_row(
                resource_id=resource_id,
                content=item,
                translation=translation,
                target_locale=locale,
                product_context=product_context,
            )
        )
    return rows


def _normalize_translatable_content_row(
    resource_id,
    content,
    translation,
    target_locale,
    product_context,
):
    raw_key = str((content or {}).get("key") or "").strip()
    resource_type = _shopify_gid_type(resource_id)
    context = (product_context.get("resources") or {}).get(resource_id, {})
    resource_group = _resource_group_for_row(resource_type, raw_key, context)
    field_key = _field_key_for_row(resource_type, raw_key, resource_group, context)
    entry_key = _entry_key_for_row(resource_id, raw_key, field_key)
    source_value = str((content or {}).get("value") or "")
    row = {
        "entry_key": entry_key,
        "draft_key": _draft_key_for_row(resource_id, raw_key, field_key),
        "key": field_key,
        "source_key": raw_key,
        "field_key": field_key,
        "resource_id": resource_id,
        "resource_type": resource_type,
        "resource_group": resource_group,
        "section_key": _section_key_for_group(resource_group),
        "source_value": source_value,
        "digest": str((content or {}).get("digest") or ""),
        "source_locale": (content or {}).get("locale", ""),
        "target_locale": target_locale,
        "has_translation": bool((translation or {}).get("value")),
        "translation_value": (translation or {}).get("value", ""),
        "translation_locale": (translation or {}).get("locale", ""),
        "translation_outdated": (translation or {}).get("outdated"),
        "context_label": context.get("context_label", ""),
        "resource_note": context.get("resource_note", ""),
        "field_label": _field_label_for_row(field_key, raw_key, resource_group, context),
        "resource_type_label": _resource_type_label(resource_group),
        "option_name": context.get("option_name", ""),
        "option_value": context.get("option_value", ""),
        "option_position": context.get("option_position", ""),
        "related_variants": list(context.get("related_variants") or []),
        "visible_product_option": bool(context.get("visible_product_option")),
        "translation_preview_available": bool(
            context.get("translation_preview_available")
        ),
        "shopify_update_mapping_ready": bool(
            context.get("shopify_update_mapping_ready")
        ),
        "translation_preview_without_digest": bool(
            context.get("translation_preview_without_digest")
        ),
        "variant_title": context.get("variant_title", ""),
        "variant_id": context.get("variant_id", ""),
        "sku": context.get("sku", ""),
        "barcode": context.get("barcode", ""),
        "selected_options": context.get("selected_options", []),
        "metafield_namespace": context.get("metafield_namespace", ""),
        "metafield_key": context.get("metafield_key", ""),
        "metafield_type": context.get("metafield_type", ""),
        "media_alt": context.get("media_alt", ""),
        "media_content_type": context.get("media_content_type", ""),
        "media_url": context.get("media_url", ""),
        "source_is_customer_facing": False,
        "draft_eligible": False,
        "draft_ineligible_reason": "",
        "draft_requires_manual_review": False,
        "draft_manual_review_reason": "",
        "future_write_needs_mapping": resource_group
        not in {"product_basics", "seo"},
        "apply_plan_blocked_reason": "",
    }
    _attach_draft_eligibility(row)
    return row


def _build_product_resource_context(product):
    product = product or {}
    product_id = product.get("id", "")
    resources = {
        product_id: {
            "context_label": "Product",
            "resource_note": "Main product translatable resource",
        }
    }
    visible_option_rows_by_key = {}
    option_position_by_name = {}
    option_id_by_name = {}

    def remember_option(option_name, option_position="", option_id=""):
        normalized_name = _option_context_key(option_name)
        if not normalized_name:
            return
        if option_position and not option_position_by_name.get(normalized_name):
            option_position_by_name[normalized_name] = option_position
        if option_id and not option_id_by_name.get(normalized_name):
            option_id_by_name[normalized_name] = option_id

    def add_visible_option_row(
        field_key,
        option_name,
        option_value="",
        option_position="",
        resource_id="",
        resource_type="",
        related_variant=None,
    ):
        option_name = str(option_name or "").strip()
        option_value = str(option_value or "").strip()
        source_value = option_value if field_key == "option.value" else option_name
        if not source_value or _is_default_option_source_value(source_value):
            return
        normalized_name = _option_context_key(option_name)
        normalized_value = _option_context_key(option_value)
        key = (field_key, normalized_name, normalized_value)
        row = visible_option_rows_by_key.get(key)
        if not row:
            option_position = (
                option_position
                or option_position_by_name.get(normalized_name, "")
            )
            resource_id = resource_id or _visible_option_resource_id(
                product_id,
                field_key,
                option_name,
                option_value,
                option_position,
            )
            row = {
                "field_key": field_key,
                "source_key": "name" if field_key == "option.name" else "value",
                "source_value": source_value,
                "resource_id": resource_id,
                "resource_type": resource_type
                or (
                    "VisibleProductOption"
                    if field_key == "option.name"
                    else "VisibleProductOptionValue"
                ),
                "resource_group": "options",
                "option_name": option_name,
                "option_value": option_value,
                "option_position": option_position,
                "context_label": _option_context_label(
                    field_key,
                    option_name,
                    option_value,
                    option_position,
                ),
                "resource_note": (
                    "Visible product option. Translation preview available; "
                    "Shopify update mapping not ready."
                ),
                "field_label": (
                    "Option name" if field_key == "option.name" else "Option value"
                ),
                "related_variants": [],
                "visible_product_option": True,
                "translation_preview_available": True,
                "shopify_update_mapping_ready": False,
                "translation_preview_without_digest": True,
            }
            visible_option_rows_by_key[key] = row
        else:
            if option_position and not row.get("option_position"):
                row["option_position"] = option_position
                row["context_label"] = _option_context_label(
                    field_key,
                    row.get("option_name", ""),
                    row.get("option_value", ""),
                    option_position,
                )
            if resource_id and row.get("resource_id", "").startswith("visible://"):
                row["resource_id"] = resource_id
            if resource_type and row.get("resource_type", "").startswith("Visible"):
                row["resource_type"] = resource_type
        if related_variant:
            _append_related_variant(row.setdefault("related_variants", []), related_variant)

    for option in (product.get("options") or [])[:MAX_PRODUCT_OPTIONS]:
        option_id = option.get("id", "")
        option_name = option.get("name", "")
        option_position = option.get("position", "")
        remember_option(option_name, option_position, option_id)
        if option_id:
            resources[option_id] = {
                "option_name": option_name,
                "option_position": option_position,
                "context_label": _join_context(
                    "Option",
                    f"{option_position}" if option_position else "",
                    option_name,
                ),
                "resource_note": "Product option name",
            }
        add_visible_option_row(
            "option.name",
            option_name,
            option_position=option_position,
            resource_id=option_id,
            resource_type="ProductOption" if option_id else "VisibleProductOption",
        )
        option_value_names = []
        for value_name in option.get("values") or []:
            value_name = str(value_name or "").strip()
            if value_name and value_name not in option_value_names:
                option_value_names.append(value_name)
        for value in option.get("optionValues") or []:
            value_id = value.get("id", "")
            value_name = value.get("name", "")
            if value_name and value_name not in option_value_names:
                option_value_names.append(value_name)
            if value_id:
                resources[value_id] = {
                    "option_name": option_name,
                    "option_value": value_name,
                    "option_position": option_position,
                    "context_label": _join_context(option_name, value_name),
                    "resource_note": "Product option value",
                }
            add_visible_option_row(
                "option.value",
                option_name,
                option_value=value_name,
                option_position=option_position,
                resource_id=value_id,
                resource_type=(
                    "ProductOptionValue" if value_id else "VisibleProductOptionValue"
                ),
            )
        for value_name in option_value_names:
            add_visible_option_row(
                "option.value",
                option_name,
                option_value=value_name,
                option_position=option_position,
                resource_type="VisibleProductOptionValue",
            )
    for edge in ((product.get("variants") or {}).get("edges") or [])[:MAX_PRODUCT_VARIANTS]:
        variant = edge.get("node") or {}
        variant_id = variant.get("id", "")
        if not variant_id:
            continue
        related_variant = {
            "variant_id": variant_id,
            "title": variant.get("title", ""),
            "sku": variant.get("sku", ""),
        }
        selected_options = [
            {
                "name": option.get("name", ""),
                "value": option.get("value", ""),
                "option_value_id": (option.get("optionValue") or {}).get("id", ""),
            }
            for option in variant.get("selectedOptions") or []
        ]
        for selected_option in selected_options:
            option_name = selected_option.get("name", "")
            option_value = selected_option.get("value", "")
            normalized_name = _option_context_key(option_name)
            remember_option(
                option_name,
                option_position_by_name.get(normalized_name, ""),
                option_id_by_name.get(normalized_name, ""),
            )
            add_visible_option_row(
                "option.name",
                option_name,
                option_position=option_position_by_name.get(normalized_name, ""),
                resource_id=option_id_by_name.get(normalized_name, ""),
                resource_type=(
                    "ProductOption"
                    if option_id_by_name.get(normalized_name, "")
                    else "VisibleProductOption"
                ),
                related_variant=related_variant,
            )
            add_visible_option_row(
                "option.value",
                option_name,
                option_value=option_value,
                option_position=option_position_by_name.get(normalized_name, ""),
                resource_id=selected_option.get("option_value_id", ""),
                resource_type=(
                    "ProductOptionValue"
                    if selected_option.get("option_value_id")
                    else "VisibleProductOptionValue"
                ),
                related_variant=related_variant,
            )
        option_text = ", ".join(
            _join_context(option.get("name"), option.get("value"))
            for option in selected_options
            if option.get("name") or option.get("value")
        )
        resources[variant_id] = {
            "variant_id": variant_id,
            "variant_title": variant.get("title", ""),
            "sku": variant.get("sku", ""),
            "barcode": variant.get("barcode", ""),
            "selected_options": selected_options,
            "option_value": option_text,
            "context_label": _join_context(
                variant.get("title", ""),
                f"SKU {variant.get('sku')}" if variant.get("sku") else "",
                option_text,
            ),
            "resource_note": "Product variant",
        }
    for edge in ((product.get("metafields") or {}).get("edges") or [])[:MAX_PRODUCT_METAFIELDS]:
        metafield = edge.get("node") or {}
        metafield_id = metafield.get("id", "")
        if not metafield_id:
            continue
        namespace = metafield.get("namespace", "")
        key = metafield.get("key", "")
        resources[metafield_id] = {
            "metafield_namespace": namespace,
            "metafield_key": key,
            "metafield_type": metafield.get("type", ""),
            "context_label": _join_context(namespace, key),
            "resource_note": f"Metafield type: {metafield.get('type', '')}".strip(),
        }
    for edge in ((product.get("media") or {}).get("edges") or [])[:MAX_PRODUCT_MEDIA]:
        media = edge.get("node") or {}
        media_id = media.get("id", "")
        if not media_id:
            continue
        resources[media_id] = {
            "media_alt": media.get("alt", ""),
            "media_content_type": media.get("mediaContentType", ""),
            "media_url": ((media.get("image") or {}).get("url") or ""),
            "context_label": _join_context(
                media.get("mediaContentType", "Media image"),
                media.get("alt", ""),
            ),
            "resource_note": "Media/image alt text",
        }
    return {
        "product_id": product_id,
        "resources": resources,
        "visible_option_rows": list(visible_option_rows_by_key.values()),
    }


def _option_context_key(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _is_default_option_source_value(value):
    return _option_context_key(value) in DEFAULT_OPTION_SOURCE_VALUES


def _visible_option_resource_id(
    product_id,
    field_key,
    option_name,
    option_value="",
    option_position="",
):
    resource_type = (
        "ProductOption" if field_key == "option.name" else "ProductOptionValue"
    )
    suffix = "_".join(
        item
        for item in (
            _slug(product_id.rsplit("/", 1)[-1] if product_id else "product"),
            _slug(option_position),
            _slug(option_name),
            _slug(option_value),
        )
        if item
    )
    return f"visible://shopify/{resource_type}/{suffix or _slug(field_key)}"


def _option_context_label(field_key, option_name, option_value="", option_position=""):
    position_label = f"Option {option_position}" if option_position else "Option"
    if field_key == "option.name":
        return _join_context(position_label, option_name)
    return _join_context(position_label, option_name, option_value)


def _append_related_variant(target, related_variant):
    variant_id = str((related_variant or {}).get("variant_id") or "").strip()
    title = str((related_variant or {}).get("title") or "").strip()
    sku = str((related_variant or {}).get("sku") or "").strip()
    key = variant_id or _join_context(title, sku)
    if not key:
        return
    for existing in target:
        existing_key = (
            str((existing or {}).get("variant_id") or "").strip()
            or _join_context(
                (existing or {}).get("title", ""),
                (existing or {}).get("sku", ""),
            )
        )
        if existing_key == key:
            return
    target.append({"variant_id": variant_id, "title": title, "sku": sku})


def _product_child_resource_ids(product_context):
    product_id = product_context.get("product_id", "")
    return [
        resource_id
        for resource_id in (product_context.get("resources") or {})
        if resource_id and resource_id != product_id
    ]


def _merge_product_resource_context(target_context, source_context):
    target_resources = target_context.setdefault("resources", {})
    target_product_id = target_context.get("product_id", "")
    for resource_id, context in (source_context.get("resources") or {}).items():
        if not resource_id or resource_id == target_product_id:
            continue
        target_resources[resource_id] = context
    target_visible_rows = target_context.setdefault("visible_option_rows", [])
    target_visible_by_key = {
        _visible_option_row_key(row): row
        for row in target_visible_rows
        if isinstance(row, dict)
    }
    for row in source_context.get("visible_option_rows") or []:
        if not isinstance(row, dict):
            continue
        key = _visible_option_row_key(row)
        existing = target_visible_by_key.get(key)
        if not existing:
            target_visible_rows.append(row)
            target_visible_by_key[key] = row
            continue
        if row.get("option_position") and not existing.get("option_position"):
            existing["option_position"] = row.get("option_position")
        if row.get("resource_id") and str(existing.get("resource_id") or "").startswith(
            "visible://"
        ):
            existing["resource_id"] = row.get("resource_id")
        if row.get("resource_type") and str(existing.get("resource_type") or "").startswith(
            "Visible"
        ):
            existing["resource_type"] = row.get("resource_type")
        for related_variant in row.get("related_variants") or []:
            _append_related_variant(
                existing.setdefault("related_variants", []),
                related_variant,
            )


def _visible_option_row_key(row):
    return (
        str((row or {}).get("field_key") or "").strip(),
        _option_context_key((row or {}).get("option_name")),
        _option_context_key((row or {}).get("option_value")),
    )


def _visible_product_option_fallback_rows(
    product_context,
    resource_by_id,
    existing_rows,
    locale,
):
    resource_by_id = resource_by_id or {}
    existing_keys = {
        _visible_option_row_key(row)
        for row in existing_rows or []
        if (row or {}).get("resource_group") == "options"
    }
    fallback_rows = []
    for option_row in product_context.get("visible_option_rows") or []:
        if not isinstance(option_row, dict):
            continue
        field_key = option_row.get("field_key", "")
        if field_key not in {"option.name", "option.value"}:
            continue
        source_value = str(option_row.get("source_value") or "").strip()
        if not source_value or _is_default_option_source_value(source_value):
            continue
        row_key = _visible_option_row_key(option_row)
        if row_key in existing_keys:
            continue
        resource_id = option_row.get("resource_id", "")
        if (
            resource_id in resource_by_id
            and (resource_by_id.get(resource_id) or {}).get("translatableContent")
        ):
            continue
        fallback_rows.append(
            _visible_product_option_row_from_context(option_row, locale)
        )
        existing_keys.add(row_key)
    return fallback_rows


def _visible_product_option_row_from_context(option_row, locale):
    field_key = option_row.get("field_key", "")
    resource_id = option_row.get("resource_id", "")
    source_key = option_row.get("source_key") or (
        "name" if field_key == "option.name" else "value"
    )
    source_value = str(option_row.get("source_value") or "")
    row = {
        "entry_key": _entry_key_for_row(resource_id, source_key, field_key),
        "draft_key": _draft_key_for_row(resource_id, source_key, field_key),
        "key": field_key,
        "source_key": source_key,
        "field_key": field_key,
        "resource_id": resource_id,
        "resource_type": option_row.get("resource_type", ""),
        "resource_group": "options",
        "section_key": "options",
        "source_value": source_value,
        "digest": "",
        "source_locale": "en",
        "target_locale": locale,
        "has_translation": False,
        "translation_value": "",
        "translation_locale": "",
        "translation_outdated": False,
        "context_label": option_row.get("context_label", ""),
        "resource_note": option_row.get("resource_note", ""),
        "field_label": option_row.get("field_label", ""),
        "resource_type_label": "Product option",
        "option_name": option_row.get("option_name", ""),
        "option_value": option_row.get("option_value", ""),
        "option_position": option_row.get("option_position", ""),
        "related_variants": list(option_row.get("related_variants") or []),
        "variant_title": "",
        "variant_id": "",
        "sku": "",
        "barcode": "",
        "selected_options": [],
        "metafield_namespace": "",
        "metafield_key": "",
        "metafield_type": "",
        "media_alt": "",
        "media_content_type": "",
        "media_url": "",
        "visible_product_option": True,
        "translation_preview_available": True,
        "shopify_update_mapping_ready": False,
        "translation_preview_without_digest": True,
        "source_is_customer_facing": True,
        "draft_eligible": False,
        "draft_ineligible_reason": "",
        "draft_requires_manual_review": False,
        "draft_manual_review_reason": "",
        "future_write_needs_mapping": True,
        "apply_plan_blocked_reason": "future_write_needs_resource_mapping",
    }
    _attach_draft_eligibility(row)
    row["future_write_needs_mapping"] = True
    row["apply_plan_blocked_reason"] = "future_write_needs_resource_mapping"
    return row



def _initial_discovery_status():
    return (
        {key: "skipped" for key in DISCOVERY_STATUS_KEYS},
        {key: "" for key in DISCOVERY_STATUS_KEYS},
    )


def _mark_discovery_status(statuses, reasons, resource_group, status, reason=""):
    for status_key in CHILD_RESOURCE_STATUS_KEYS.get(resource_group, (resource_group,)):
        statuses[status_key] = status
        reasons[status_key] = reason or ""


def _child_discovery_error(exc, stage, resource_group):
    details = translation_console_error_details(
        exc,
        stage=stage,
        resource_group=resource_group,
    )
    skipped_groups = list(CHILD_RESOURCE_STATUS_KEYS.get(resource_group, (resource_group,)))
    return {
        "stage": details["stage"],
        "resource_group": resource_group,
        "group_label": DISCOVERY_GROUP_LABELS.get(resource_group, resource_group),
        "skipped_groups": skipped_groups,
        "skipped_group_labels": [
            DISCOVERY_GROUP_LABELS.get(group, group) for group in skipped_groups
        ],
        "status": "skipped",
        "reason": "skipped_child_resource_query_failed",
        "query_failure_type": details["query_failure_type"],
        "message": details["message"],
    }


def _resource_group_for_row(resource_type, raw_key, context):
    resource_type = str(resource_type or "")
    raw_key = str(raw_key or "").lower()
    if resource_type == "Product":
        if raw_key in {"meta_title", "meta_description", "handle"}:
            return "seo"
        return "product_basics"
    if resource_type in {"ProductOption", "ProductOptionValue"}:
        return "options"
    if resource_type == "ProductVariant":
        return "variants"
    if resource_type == "Metafield":
        namespace = str(context.get("metafield_namespace") or "").lower()
        key = str(context.get("metafield_key") or raw_key or "").lower()
        field_key = f"{namespace}.{key}".strip(".")
        if _is_important_metafield(field_key):
            return "important_metafields"
        return "technical_metafields"
    if resource_type in {"MediaImage", "Image"}:
        return "media"
    return "technical_metafields"


def _field_key_for_row(resource_type, raw_key, resource_group, context):
    raw_key = str(raw_key or "").strip()
    normalized_key = "body_html" if raw_key == "description" else raw_key
    if resource_type == "Product":
        return normalized_key
    if resource_type == "ProductOption":
        return "option.name"
    if resource_type == "ProductOptionValue":
        return "option.value"
    if resource_type == "ProductVariant":
        if "option" in normalized_key.lower():
            return "variant.option"
        if normalized_key.lower() in {"sku", "barcode"}:
            return f"variant.{normalized_key.lower()}"
        return f"variant.{normalized_key or 'title'}"
    if resource_type == "Metafield":
        namespace = context.get("metafield_namespace", "")
        key = context.get("metafield_key", "") or normalized_key
        return f"metafield.{namespace}.{key}".strip(".")
    if resource_group == "media":
        return "media.alt"
    return normalized_key or resource_type.lower()


def _field_label_for_row(field_key, raw_key, resource_group, context):
    if context.get("field_label"):
        return context["field_label"]
    labels = {
        "title": "Product title",
        "body_html": "Product description",
        "meta_title": "SEO title",
        "meta_description": "SEO description",
        "handle": "URL handle",
        "option.name": "Product option name",
        "option.value": "Product option value",
        "variant.title": "Variant title",
        "variant.option": "Variant option value",
        "media.alt": "Media alt text",
    }
    if field_key in labels:
        return labels[field_key]
    if resource_group in {"important_metafields", "technical_metafields"}:
        key = context.get("metafield_key") or raw_key
        return f"Metafield: {_humanize_key(key)}"
    return _humanize_key(field_key or raw_key)


def _resource_type_label(resource_group):
    return {
        "product_basics": "Product field",
        "seo": "SEO field",
        "options": "Product option",
        "variants": "Variant field",
        "important_metafields": "Important metafield",
        "technical_metafields": "Technical / not translated",
        "media": "Media alt text",
    }.get(resource_group, "Technical / not translated")


def _section_key_for_group(resource_group):
    return {
        "product_basics": "basic",
        "seo": "seo",
        "options": "options",
        "variants": "variants",
        "important_metafields": "important_metafields",
        "technical_metafields": "technical_metafields",
        "media": "media",
    }.get(resource_group, "technical_metafields")


def _attach_draft_eligibility(row):
    source_value = str(row.get("source_value") or "")
    field_key = str(row.get("field_key") or "")
    raw_key = str(row.get("source_key") or "")
    resource_group = row.get("resource_group", "")
    row["source_is_customer_facing"] = resource_group in {
        "product_basics",
        "seo",
        "options",
        "variants",
        "important_metafields",
        "media",
    }
    if not source_value.strip():
        row["draft_ineligible_reason"] = "source_empty"
    elif (
        not row.get("resource_id")
        or (not row.get("digest") and not row.get("translation_preview_without_digest"))
    ):
        row["draft_ineligible_reason"] = "missing_resource_id_or_digest"
    elif resource_group == "technical_metafields":
        row["draft_ineligible_reason"] = "technical_or_internal_field"
    elif _is_technical_field(row):
        row["draft_ineligible_reason"] = "technical_code_or_identifier"
    elif _looks_like_json_or_schema(source_value):
        row["draft_ineligible_reason"] = "json_or_schema_value"
    elif _looks_like_identifier(source_value):
        row["draft_ineligible_reason"] = "sku_numeric_id_barcode_or_code"
    elif resource_group == "product_basics" and field_key not in {"title", "body_html"}:
        row["draft_ineligible_reason"] = "product_field_not_in_draft_scope"
    elif resource_group == "seo" and field_key not in {
        "meta_title",
        "meta_description",
        "handle",
    }:
        row["draft_ineligible_reason"] = "seo_field_not_in_draft_scope"
    elif resource_group == "variants" and raw_key.lower() in {"sku", "barcode"}:
        row["draft_ineligible_reason"] = "variant_sku_or_barcode_context_only"
    elif resource_group == "media" and "alt" not in field_key.lower() and "alt" not in raw_key.lower():
        row["draft_ineligible_reason"] = "media_field_not_alt_text"
    else:
        row["draft_eligible"] = True
        row["draft_ineligible_reason"] = ""

    if field_key == "handle":
        row["draft_requires_manual_review"] = True
        row["draft_manual_review_reason"] = "url_handle_manual_review_required"
        row["future_write_needs_mapping"] = True
        row["apply_plan_blocked_reason"] = "url_handle_future_write_blocked"
    elif row["future_write_needs_mapping"]:
        row["apply_plan_blocked_reason"] = "future_write_needs_resource_mapping"


def _is_technical_field(row):
    field_key = str(row.get("field_key") or "")
    raw_key = str(row.get("source_key") or "")
    metafield_type = str(row.get("metafield_type") or "").lower()
    if _key_matches_hint(f"{field_key}.{raw_key}", TECHNICAL_FIELD_HINTS):
        return True
    if metafield_type:
        type_tokens = set(re.split(r"[^a-z0-9]+", metafield_type))
        if type_tokens & TECHNICAL_VALUE_TYPES:
            return True
    return False


def _looks_like_json_or_schema(value):
    value = str(value or "").strip()
    if not value:
        return False
    return (
        (value.startswith("{") and value.endswith("}"))
        or (value.startswith("[") and value.endswith("]"))
    )


def _looks_like_identifier(value):
    value = str(value or "").strip()
    if not value:
        return False
    if len(value) <= 3 and value.isalpha():
        return False
    return bool(IDENTIFIER_LIKE_RE.fullmatch(value))


def _is_important_metafield(field_key):
    namespace, key = _metafield_parts(field_key)
    namespace = namespace.lower()
    combined = f"{namespace}.{key}"
    if namespace in TECHNICAL_METAFIELD_NAMESPACES:
        return False
    if _key_matches_hint(combined, TECHNICAL_FIELD_HINTS):
        return False
    if namespace in IMPORTANT_METAFIELD_NAMESPACES:
        return True
    return _key_matches_hint(combined, IMPORTANT_METAFIELD_HINTS)


def _metafield_parts(field_key):
    key = str(field_key or "").strip()
    lower_key = key.lower()
    for prefix in ("product.metafields.", "product.metafield.", "metafields.", "metafield.", "metafield."):
        if lower_key.startswith(prefix):
            key = key[len(prefix):]
            break
    parts = [part for part in re.split(r"[./:]+", key) if part]
    if len(parts) >= 2:
        return parts[0], ".".join(parts[1:])
    if parts:
        return "", parts[0]
    return "", ""


def _key_matches_hint(field_key, hints):
    tokens = set(
        token
        for token in re.split(r"[^a-z0-9]+", str(field_key or "").lower())
        if token
    )
    compact_key = re.sub(r"[^a-z0-9]+", "_", str(field_key or "").lower()).strip("_")
    for hint in hints:
        normalized_hint = re.sub(r"[^a-z0-9]+", "_", hint.lower()).strip("_")
        if not normalized_hint:
            continue
        if "_" in normalized_hint and normalized_hint in compact_key:
            return True
        if normalized_hint in tokens:
            return True
        if len(normalized_hint) >= 4 and any(
            token.startswith(normalized_hint) for token in tokens
        ):
            return True
    return False


def _entry_key_for_row(resource_id, raw_key, field_key):
    if _shopify_gid_type(resource_id) == "Product":
        return field_key or raw_key
    return f"{resource_id}::{raw_key or field_key}"


def _draft_key_for_row(resource_id, raw_key, field_key):
    if _shopify_gid_type(resource_id) == "Product":
        return field_key or raw_key
    resource_type = _shopify_gid_type(resource_id).lower() or "resource"
    resource_number = str(resource_id or "").rsplit("/", 1)[-1]
    return "_".join(
        value
        for value in [
            _slug(resource_type),
            _slug(resource_number),
            _slug(raw_key or field_key),
        ]
        if value
    )


def _shopify_gid_type(resource_id):
    match = SHOPIFY_GID_TYPE_RE.match(str(resource_id or ""))
    return match.group(1) if match else ""


def _slug(value):
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")


def _humanize_key(value):
    return str(value or "").replace("_", " ").replace(".", " / ").title()


def _join_context(*parts):
    return " | ".join(str(part).strip() for part in parts if str(part or "").strip())


def _search_products(installation, search_text):
    query = """
    query($query: String!) {
      products(first: 5, query: $query) {
        edges {
          node {
            id
            title
            handle
            status
            productType
            vendor
          }
        }
      }
    }
    """
    data = shopify_graphql_read_only(
        installation,
        query,
        {"query": _normalize_product_search_query(search_text)},
        stage="product_search_query",
        resource_group="product",
    )
    edges = (data.get("products") or {}).get("edges") or []
    return {
        "product": {},
        "search_results": [_normalize_product(edge.get("node") or {}) for edge in edges[:MAX_SEARCH_RESULTS]],
        "translatable_resource": {},
        "translatable_rows": [],
    }


def _normalize_product_search_query(search_text):
    value = (search_text or "").strip()
    if value.lower().startswith("handle:"):
        return f"handle:{value.split(':', 1)[1].strip()}"
    if value.lower().startswith("title:"):
        return f"title:{value.split(':', 1)[1].strip()}"
    return value


def _normalize_product(product):
    return {
        "id": product.get("id", ""),
        "title": product.get("title", ""),
        "handle": product.get("handle", ""),
        "status": product.get("status", ""),
        "product_type": product.get("productType", ""),
        "vendor": product.get("vendor", ""),
    }


def shopify_graphql_read_only(
    installation,
    query,
    variables=None,
    stage="read_only_shopify_query",
    resource_group="product",
):
    url = f"https://{installation.shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    try:
        response = requests.post(
            url,
            headers={
                "X-Shopify-Access-Token": installation.access_token,
                "Content-Type": "application/json",
            },
            json={"query": query, "variables": variables or {}},
            timeout=30,
        )
        response.raise_for_status()
    except requests.HTTPError as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", "")
        raise ShopifyTranslationConsoleError(
            f"Shopify HTTP {status_code} returned for read-only GraphQL query.",
            stage=stage,
            resource_group=resource_group,
            query_failure_type="shopify_http_error",
        ) from exc
    except requests.RequestException as exc:
        raise ShopifyTranslationConsoleError(
            f"Shopify request failed: {exc}",
            stage=stage,
            resource_group=resource_group,
            query_failure_type="shopify_request_error",
        ) from exc
    try:
        data = response.json()
    except ValueError as exc:
        raise ShopifyTranslationConsoleError(
            "Shopify returned a non-JSON response for read-only GraphQL query.",
            stage=stage,
            resource_group=resource_group,
            query_failure_type="shopify_invalid_json_response",
        ) from exc
    if data.get("errors"):
        raise ShopifyTranslationConsoleError(
            _shopify_graphql_error_summary(data.get("errors")),
            stage=stage,
            resource_group=resource_group,
            query_failure_type="shopify_graphql_errors",
        )
    return data.get("data") or {}


def _shopify_graphql_error_summary(errors):
    messages = []
    for item in (errors or [])[:3]:
        if isinstance(item, dict):
            message = item.get("message") or "Shopify GraphQL error"
            path = ".".join(str(part) for part in (item.get("path") or []) if part is not None)
            if path:
                message = f"{message} (path: {path})"
            messages.append(message)
        else:
            messages.append(str(item))
    return "; ".join(messages) or "Shopify GraphQL returned errors."


def _safety_flags(shopify_api_call_performed=False):
    return {
        "shopify_read_only": True,
        "shopify_api_call_performed": bool(shopify_api_call_performed),
        "shopify_write_performed": False,
        "mutation_performed": False,
        "translations_register_called": False,
        "publish_performed": False,
        "real_apply_performed": False,
        "rollback_performed": False,
    }
