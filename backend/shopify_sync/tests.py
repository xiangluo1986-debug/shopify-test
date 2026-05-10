import hashlib
import hmac
import urllib.parse
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from .models import ShopifyInstallation
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
