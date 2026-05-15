import re

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


class ShopifyTranslationConsoleError(Exception):
    pass


def normalize_product_gid(value):
    value = (value or "").strip()
    if PRODUCT_GID_RE.fullmatch(value):
        return value
    if NUMERIC_PRODUCT_ID_RE.fullmatch(value):
        return f"gid://shopify/Product/{value}"
    return ""


def fetch_translation_console_data(installation, search_text, locale):
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
    result["locale"] = locale
    result["search_text"] = search_text
    return result


def _fetch_product_translation_resource(installation, product_gid, locale):
    query = """
    query($id: ID!, $locale: String!) {
      product: node(id: $id) {
        ... on Product {
          id
          title
          handle
          status
          productType
          vendor
          options(first: 20) {
            id
            name
            position
            values
            optionValues {
              id
              name
              hasVariants
              linkedMetafieldValue
            }
          }
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
                  optionValue {
                    id
                    name
                  }
                }
              }
            }
          }
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
          media(first: 100) {
            edges {
              node {
                mediaContentType
                ... on MediaImage {
                  id
                  alt
                  image {
                    url
                  }
                }
              }
            }
          }
        }
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
        nestedTranslatableResources(first: 250) {
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
    }
    """
    data = shopify_graphql_read_only(installation, query, {"id": product_gid, "locale": locale})
    product = data.get("product")
    resource = data.get("translatableResource")
    if not product:
        raise ShopifyTranslationConsoleError(f"Shopify product not found for {product_gid}.")
    if not resource:
        raise ShopifyTranslationConsoleError(f"Translatable resource not found for {product_gid}.")

    product_context = _build_product_resource_context(product)
    nested_resources = [
        (edge.get("node") or {})
        for edge in ((resource.get("nestedTranslatableResources") or {}).get("edges") or [])
        if edge.get("node")
    ]
    resource_by_id = {
        item.get("resourceId"): item
        for item in [resource, *nested_resources]
        if item.get("resourceId")
    }
    child_resource_ids = _product_child_resource_ids(product_context)
    missing_resource_ids = [
        resource_id
        for resource_id in child_resource_ids
        if resource_id not in resource_by_id
    ][:MAX_CHILD_RESOURCE_ID_LOOKUP]
    for child_resource in _fetch_translatable_resources_by_ids(
        installation,
        missing_resource_ids,
        locale,
    ):
        if child_resource.get("resourceId"):
            resource_by_id[child_resource["resourceId"]] = child_resource

    rows = []
    for normalized_resource in resource_by_id.values():
        rows.extend(
            _normalize_translatable_resource_rows(
                normalized_resource,
                locale,
                product_context,
            )
        )

    return {
        "product": _normalize_product(product),
        "search_results": [],
        "translatable_resource": {
            "resource_id": resource.get("resourceId", ""),
            "translatable_content_count": len(rows),
            "translation_count": len(resource.get("translations", [])),
            "nested_resource_count": len(nested_resources),
            "child_resource_count": len(resource_by_id) - 1,
        },
        "translatable_rows": rows,
    }


def _fetch_translatable_resources_by_ids(installation, resource_ids, locale):
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
    resources = {
        product.get("id", ""): {
            "context_label": "Product",
            "resource_note": "Main product translatable resource",
        }
    }
    for option in (product.get("options") or [])[:MAX_PRODUCT_OPTIONS]:
        option_id = option.get("id", "")
        option_name = option.get("name", "")
        option_position = option.get("position", "")
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
        for value in option.get("optionValues") or []:
            value_id = value.get("id", "")
            if not value_id:
                continue
            value_name = value.get("name", "")
            resources[value_id] = {
                "option_name": option_name,
                "option_value": value_name,
                "option_position": option_position,
                "context_label": _join_context(option_name, value_name),
                "resource_note": "Product option value",
            }
    for edge in ((product.get("variants") or {}).get("edges") or [])[:MAX_PRODUCT_VARIANTS]:
        variant = edge.get("node") or {}
        variant_id = variant.get("id", "")
        if not variant_id:
            continue
        selected_options = [
            {
                "name": option.get("name", ""),
                "value": option.get("value", ""),
                "option_value_id": (option.get("optionValue") or {}).get("id", ""),
            }
            for option in variant.get("selectedOptions") or []
        ]
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
    return {"product_id": product.get("id", ""), "resources": resources}


def _product_child_resource_ids(product_context):
    product_id = product_context.get("product_id", "")
    return [
        resource_id
        for resource_id in (product_context.get("resources") or {})
        if resource_id and resource_id != product_id
    ]


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
    elif not row.get("resource_id") or not row.get("digest"):
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
    data = shopify_graphql_read_only(installation, query, {"query": _normalize_product_search_query(search_text)})
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


def shopify_graphql_read_only(installation, query, variables=None):
    url = f"https://{installation.shop}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
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
    data = response.json()
    if data.get("errors"):
        raise ShopifyTranslationConsoleError("Shopify GraphQL returned errors.")
    return data.get("data") or {}


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
