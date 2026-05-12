import re

import requests


SHOPIFY_API_VERSION = "2026-01"
SUPPORTED_TRANSLATION_LOCALES = ("ja", "de", "fr", "es", "it")
PRODUCT_GID_RE = re.compile(r"^gid://shopify/Product/\d+$")
NUMERIC_PRODUCT_ID_RE = re.compile(r"^\d+$")
MAX_SEARCH_RESULTS = 5


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

    translations_by_key = {
        item.get("key"): item
        for item in resource.get("translations", [])
        if item.get("key")
    }
    rows = []
    for item in resource.get("translatableContent", []):
        translation = translations_by_key.get(item.get("key")) or {}
        rows.append(
            {
                "key": item.get("key", ""),
                "source_value": item.get("value", ""),
                "digest": item.get("digest", ""),
                "source_locale": item.get("locale", ""),
                "target_locale": locale,
                "has_translation": bool(translation.get("value")),
                "translation_value": translation.get("value", ""),
                "translation_locale": translation.get("locale", ""),
                "translation_outdated": translation.get("outdated"),
            }
        )

    return {
        "product": _normalize_product(product),
        "search_results": [],
        "translatable_resource": {
            "resource_id": resource.get("resourceId", ""),
            "translatable_content_count": len(rows),
            "translation_count": len(resource.get("translations", [])),
        },
        "translatable_rows": rows,
    }


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
