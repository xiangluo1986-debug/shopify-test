import hashlib
import hmac
import urllib.parse
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings

from .models import ShopifyInstallation
from .translation_apply_plan import (
    ALL_LANGUAGES_MAPPING_BLOCKED_REASON,
    build_translation_workspace_all_languages_update_state,
    validate_and_update_all_languages_to_shopify,
)
from .translation_drafts import (
    SOURCE_CHANGED_REFRESH_MESSAGE,
    _html_structure_notes_for_draft,
    _html_text_nodes_for_entry,
    _translation_cache_key,
    generate_selected_product_missing_translation_draft_package,
)
from .views import SHOPIFY_OAUTH_STATE_SESSION_KEY


def shopify_hmac(params, secret="test-secret"):
    signed_params = []
    for key in sorted(params.keys()):
        if key in {"hmac", "signature"}:
            continue
        value = params[key]
        if isinstance(value, list):
            signed_params.extend((key, item) for item in value)
        else:
            signed_params.append((key, value))
    message = "&".join(f"{key}={value}" for key, value in signed_params)
    return hmac.new(
        secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


@override_settings(
    ROOT_URLCONF="config.urls",
    SECRET_KEY="test-secret-key",
)
class ShopifyOAuthTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(
            username="admin",
            email="admin@example.com",
            password="password",
        )

    @patch.dict(
        "os.environ",
        {
            "SHOPIFY_CLIENT_ID": "client-id",
            "SHOPIFY_CLIENT_SECRET": "test-secret",
            "SHOPIFY_SCOPES": "read_orders,read_products",
            "SHOPIFY_REDIRECT_URI": "https://example.com/auth/shopify/callback/",
        },
    )
    def test_install_redirects_with_session_state(self):
        self.client.force_login(self.user)

        response = self.client.get(
            "/auth/shopify/install/",
            {"shop": "Example-Shop.myshopify.com"},
        )

        self.assertEqual(response.status_code, 302)
        redirect = urllib.parse.urlparse(response["Location"])
        query = urllib.parse.parse_qs(redirect.query)
        self.assertEqual(redirect.netloc, "example-shop.myshopify.com")
        self.assertEqual(query["client_id"], ["client-id"])
        self.assertEqual(query["scope"], ["read_orders,read_products"])
        self.assertEqual(query["redirect_uri"], ["https://example.com/auth/shopify/callback/"])
        self.assertTrue(query["state"][0])

    def test_install_rejects_invalid_shop(self):
        self.client.force_login(self.user)

        response = self.client.get(
            "/auth/shopify/install/",
            {"shop": "evil.example.com"},
        )

        self.assertEqual(response.status_code, 400)

    @patch.dict(
        "os.environ",
        {
            "SHOPIFY_CLIENT_ID": "client-id",
            "SHOPIFY_CLIENT_SECRET": "test-secret",
            "SHOPIFY_SCOPES": "read_orders,read_products",
            "SHOPIFY_REDIRECT_URI": "https://example.com/auth/shopify/callback/",
        },
    )
    def test_callback_rejects_invalid_hmac(self):
        response = self.client.get(
            "/auth/shopify/callback/",
            {
                "shop": "example-shop.myshopify.com",
                "code": "temporary-code",
                "state": "state-value",
                "hmac": "bad-signature",
            },
        )

        self.assertEqual(response.status_code, 403)

    @patch.dict(
        "os.environ",
        {
            "SHOPIFY_CLIENT_ID": "client-id",
            "SHOPIFY_CLIENT_SECRET": "test-secret",
            "SHOPIFY_SCOPES": "read_orders,read_products",
            "SHOPIFY_REDIRECT_URI": "https://example.com/auth/shopify/callback/",
        },
    )
    def test_callback_rejects_missing_session_state(self):
        params = {
            "shop": "example-shop.myshopify.com",
            "code": "temporary-code",
            "state": "state-value",
            "timestamp": "1710000000",
        }
        params["hmac"] = shopify_hmac(params)

        response = self.client.get("/auth/shopify/callback/", params)

        self.assertEqual(response.status_code, 403)

    @patch.dict(
        "os.environ",
        {
            "SHOPIFY_CLIENT_ID": "client-id",
            "SHOPIFY_CLIENT_SECRET": "test-secret",
            "SHOPIFY_SCOPES": "read_orders,read_products",
            "SHOPIFY_REDIRECT_URI": "https://example.com/auth/shopify/callback/",
        },
    )
    @patch("urllib.request.urlopen")
    def test_callback_stores_access_token(self, mock_urlopen):
        class TokenResponse:
            def read(self):
                return b'{"access_token":"shpat_test_token","scope":"read_orders"}'

        class AccessScopesResponse:
            def read(self):
                return (
                    b'{"access_scopes":['
                    b'{"handle":"read_orders"},'
                    b'{"handle":"read_translations"},'
                    b'{"handle":"write_translations"},'
                    b'{"handle":"read_locales"}'
                    b"]}"
                )

        mock_urlopen.side_effect = [TokenResponse(), AccessScopesResponse()]
        session = self.client.session
        session[SHOPIFY_OAUTH_STATE_SESSION_KEY] = {
            "example-shop.myshopify.com": "state-value"
        }
        session.save()
        params = {
            "shop": "example-shop.myshopify.com",
            "code": "temporary-code",
            "state": "state-value",
            "timestamp": "1710000000",
        }
        params["hmac"] = shopify_hmac(params)

        response = self.client.get("/auth/shopify/callback/", params)

        self.assertEqual(response.status_code, 200)
        installation = ShopifyInstallation.objects.get(shop="example-shop.myshopify.com")
        self.assertEqual(installation.access_token, "shpat_test_token")
        self.assertEqual(
            installation.scope,
            "read_orders,read_translations,write_translations,read_locales",
        )


class TranslationWorkspaceBodyHtmlSourceChangeTests(SimpleTestCase):
    product_gid = "gid://shopify/Product/222"

    old_body_html = "<p>Intro text</p><p>Text after video</p>"
    new_body_html = (
        "<p>Intro text</p>"
        '<div class="video-section">'
        '<iframe src="https://www.youtube.com/embed/demo123" title="Demo video"></iframe>'
        "</div>"
        "<p>Text after video</p>"
    )

    def _console_result(self):
        return {
            "product": {"id": self.product_gid, "title": "Demo RC Part"},
            "translatable_resource": {
                "translatable_content_count": 1,
                "translation_count": 1,
            },
            "translatable_rows": [
                {
                    "entry_key": "body_html",
                    "draft_key": "body_html",
                    "key": "body_html",
                    "source_key": "body_html",
                    "field_key": "body_html",
                    "resource_id": self.product_gid,
                    "resource_type": "Product",
                    "resource_group": "product_basics",
                    "section_key": "basic",
                    "source_value": self.new_body_html,
                    "digest": "digest-new-body",
                    "source_locale": "en",
                    "target_locale": "ja",
                    "has_translation": True,
                    "translation_value": "<p>OLD FULL BODY CACHE</p>",
                    "translation_locale": "ja",
                    "translation_outdated": False,
                    "draft_eligible": True,
                    "draft_ineligible_reason": "",
                }
            ],
            "child_resource_discovery_errors": [],
            "per_group_discovery_status": {},
            "per_group_discovery_reasons": {},
        }

    def test_body_html_source_change_refreshes_translation_and_preserves_youtube_iframe(self):
        old_cache_key = _translation_cache_key(
            "ja",
            {
                "field": "body_html",
                "resource_group": "product_basics",
                "source_value": self.old_body_html,
                "source_digest": "digest-old-body",
            },
        )
        new_cache_key = _translation_cache_key(
            "ja",
            {
                "field": "body_html",
                "resource_group": "product_basics",
                "source_value": self.new_body_html,
                "source_digest": "digest-new-body",
            },
        )
        self.assertNotEqual(old_cache_key, new_cache_key)

        nodes = _html_text_nodes_for_entry({"source_value": self.new_body_html})
        node_text = [node["text"] for node in nodes]
        self.assertEqual(node_text, ["Intro text", "Text after video"])
        self.assertFalse(any("youtube" in value.lower() for value in node_text))

        previous_source_index = {
            (self.product_gid, "body_html", "ja"): {
                "source_digest": "digest-old-body",
                "source_text_hash": "",
            }
        }
        old_cache = {
            old_cache_key: {
                "value": "<p>OLD FULL BODY CACHE</p>",
                "locale": "ja",
                "field": "body_html",
                "source_digest": "digest-old-body",
            }
        }
        openai_body_response = {
            "translations": {
                "body_html": {
                    "html_text_nodes": {
                        "n1": "JP Intro text",
                        "n2": "JP Text after video",
                    }
                }
            }
        }

        with patch.dict("os.environ", {"OPENAI_API_KEY": "test-key"}), patch(
            "shopify_sync.translation_drafts.fetch_translation_console_data",
            return_value=self._console_result(),
        ), patch(
            "shopify_sync.translation_drafts._previous_translation_source_index",
            return_value=previous_source_index,
        ), patch(
            "shopify_sync.translation_drafts._load_translation_cache",
            return_value=old_cache,
        ), patch(
            "shopify_sync.translation_drafts._save_translation_cache"
        ) as mock_save_cache, patch(
            "shopify_sync.translation_drafts._request_openai_profile",
            return_value=openai_body_response,
        ) as mock_openai_profile:
            result = generate_selected_product_missing_translation_draft_package(
                product_id=self.product_gid,
                target_locales=["ja"],
                fields=["product_basics"],
                installation=SimpleNamespace(shop="example.myshopify.com"),
                include_missing=True,
                include_outdated=True,
            )

        self.assertTrue(result["success"])
        mock_openai_profile.assert_called_once()
        mock_save_cache.assert_called_once()
        body_entry = result["draft_entries"][0]
        self.assertEqual(
            body_entry["row_status"],
            "outdated_translation_update_draft_ready",
        )
        self.assertTrue(body_entry["existing_translation_outdated"])
        self.assertTrue(body_entry["source_changed_from_previous_report"])
        self.assertEqual(
            body_entry["source_change_message"],
            SOURCE_CHANGED_REFRESH_MESSAGE,
        )
        self.assertIn(
            '<iframe src="https://www.youtube.com/embed/demo123" title="Demo video"></iframe>',
            body_entry["draft_value"],
        )
        self.assertIn("JP Intro text", body_entry["draft_value"])
        self.assertIn("JP Text after video", body_entry["draft_value"])
        self.assertNotIn("OLD FULL BODY CACHE", body_entry["draft_value"])
        self.assertNotIn("html_media_or_link_tag_broken", body_entry["quality_notes"])
        self.assertNotIn("body_html_structure_broken", body_entry["quality_notes"])

        broken_notes = _html_structure_notes_for_draft(
            {"field": "body_html", "source_value": self.new_body_html},
            "<p>JP Intro text</p><p>JP Text after video</p>",
        )
        self.assertIn("html_media_or_link_tag_broken", broken_notes)


class TranslationAllLanguagesShopifyUpdateTests(SimpleTestCase):
    product_gid = "gid://shopify/Product/111"

    def _report(self, rows, status="completed"):
        return {
            "exists": True,
            "job_id": "translation_workspace_job_test",
            "status": status,
            "product_gid": self.product_gid,
            "product_title": "Test Product",
            "selected_locales": ["ja", "de", "fr", "es", "it"],
            "per_locale_status": [
                {"locale": locale, "status": "completed"} for locale in ["ja", "de", "fr", "es", "it"]
            ],
            "review_rows": rows,
        }

    def _title_row(self, locale, proposed, **overrides):
        row = {
            "locale": locale,
            "language": locale,
            "resource_group": "product_basics",
            "field": "title",
            "key": "title",
            "resource_id": self.product_gid,
            "source_digest": f"digest-title-{locale}",
            "source_value": "RC plane spare part",
            "proposed_translation": proposed,
            "has_generated_draft": True,
            "validation_status": "draft_ready_for_manual_review",
            "seo_validation_status": "seo_ready",
        }
        row.update(overrides)
        return row

    def test_all_languages_state_blocks_mapping_and_invalid_body_html(self):
        rows = [
            self._title_row("ja", "RC飛行機スペアパーツ"),
            {
                "locale": "ja",
                "resource_group": "product_basics",
                "field": "body_html",
                "key": "body_html",
                "resource_id": self.product_gid,
                "source_digest": "digest-body-ja",
                "source_value": '<p>Part <img src="part.jpg"></p>',
                "proposed_translation": "<p>部品</p>",
                "has_generated_draft": True,
                "validation_status": "draft_ready_for_manual_review",
                "seo_validation_status": "seo_ready",
            },
            {
                "locale": "ja",
                "resource_group": "options",
                "field": "option.name",
                "key": "option.name",
                "resource_id": "gid://shopify/ProductOption/1",
                "source_digest": "digest-option-ja",
                "source_value": "Color",
                "proposed_translation": "色",
                "has_generated_draft": True,
                "validation_status": "draft_ready_for_manual_review",
                "seo_validation_status": "seo_ready",
            },
        ]

        state = build_translation_workspace_all_languages_update_state(
            self._report(rows),
            selected_product_gid=self.product_gid,
        )

        self.assertEqual(state["write_ready_count"], 1)
        blocked = {entry["key"]: entry for entry in state["entries"] if entry["status"] == "blocked"}
        self.assertIn("blocked_html_media_or_link_tag_broken", blocked["body_html"]["blocking_reasons"])
        self.assertEqual(
            blocked["option.name"]["blocking_reason"],
            ALL_LANGUAGES_MAPPING_BLOCKED_REASON,
        )

    @patch("shopify_sync.translation_apply_plan.requests.post")
    def test_all_languages_update_prefers_manual_edit_and_verifies_readback(self, mock_post):
        rows = [
            self._title_row(
                locale,
                f"OpenAI {locale}",
                **(
                    {
                        "manual_edit_value": "Manual Japanese title",
                        "manual_translation_override_value": "Manual Japanese title",
                        "using_manual_edit": True,
                    }
                    if locale == "ja"
                    else {}
                ),
            )
            for locale in ["ja", "de", "fr", "es", "it"]
        ]
        captured = {}

        class Response:
            status_code = 200

            def __init__(self, data):
                self._data = data

            def raise_for_status(self):
                return None

            def json(self):
                return self._data

        def fake_post(_url, headers=None, json=None, timeout=None):
            variables = (json or {}).get("variables") or {}
            if "translations" in variables:
                translations = []
                for item in variables["translations"]:
                    key = (variables["resourceId"], item["locale"], item["key"])
                    captured[key] = item["value"]
                    translations.append(
                        {
                            "key": item["key"],
                            "locale": item["locale"],
                            "value": item["value"],
                            "outdated": False,
                        }
                    )
                return Response(
                    {
                        "data": {
                            "translationsRegister": {
                                "translations": translations,
                                "userErrors": [],
                            }
                        }
                    }
                )
            resource_id = variables["id"]
            locale = variables["locale"]
            return Response(
                {
                    "data": {
                        "translatableResource": {
                            "resourceId": resource_id,
                            "translations": [
                                {
                                    "key": key,
                                    "locale": item_locale,
                                    "value": value,
                                    "outdated": False,
                                }
                                for (item_resource, item_locale, key), value in captured.items()
                                if item_resource == resource_id and item_locale == locale
                            ],
                        }
                    }
                }
            )

        mock_post.side_effect = fake_post
        result = validate_and_update_all_languages_to_shopify(
            self._report(rows),
            installation=SimpleNamespace(shop="example.myshopify.com", access_token="token"),
            selected_product_gid=self.product_gid,
            write_reports=False,
        )

        self.assertEqual(
            result["status"],
            "all_languages_shopify_translations_written_and_verified",
        )
        self.assertEqual(result["updated_count"], 5)
        self.assertEqual(result["verified_count"], 5)
        self.assertTrue(result["translations_register_called"])
        self.assertEqual(
            captured[(self.product_gid, "ja", "title")],
            "Manual Japanese title",
        )

    @patch("shopify_sync.translation_apply_plan.requests.post")
    def test_all_languages_update_with_no_safe_candidates_does_not_mutate(self, mock_post):
        rows = [
            {
                "locale": "de",
                "resource_group": "variants",
                "field": "variant.title",
                "key": "variant.title",
                "resource_id": "gid://shopify/ProductVariant/1",
                "source_digest": "digest-variant-de",
                "source_value": "Blue",
                "proposed_translation": "Blau",
                "has_generated_draft": True,
                "validation_status": "draft_ready_for_manual_review",
                "seo_validation_status": "seo_ready",
            }
        ]

        result = validate_and_update_all_languages_to_shopify(
            self._report(rows),
            installation=SimpleNamespace(shop="example.myshopify.com", access_token="token"),
            selected_product_gid=self.product_gid,
            write_reports=False,
        )

        self.assertEqual(result["status"], "all_languages_shopify_translations_blocked")
        self.assertFalse(result["mutation_called"])
        self.assertFalse(result["shopify_write_performed"])
        mock_post.assert_not_called()

    @patch("shopify_sync.translation_apply_plan.requests.post")
    def test_all_languages_update_without_selected_product_is_blocked(self, mock_post):
        result = validate_and_update_all_languages_to_shopify(
            self._report([self._title_row("fr", "Piece RC")]),
            installation=SimpleNamespace(shop="example.myshopify.com", access_token="token"),
            selected_product_gid="",
            write_reports=False,
        )

        self.assertEqual(result["status"], "all_languages_shopify_translations_blocked")
        self.assertIn("blocked_missing_selected_product", result["blocking_conditions"])
        self.assertFalse(result["mutation_called"])
        mock_post.assert_not_called()
