"""Manual Gmail OAuth helper for review-request draft-only setup.

This script does not call Gmail drafts.create, drafts.send, or messages.send.
It only helps build an OAuth authorization URL or exchange a pasted
authorization code for a refresh token when run manually.
"""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request


AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DEFAULT_SCOPE = "https://www.googleapis.com/auth/gmail.compose"
DEFAULT_REDIRECT_URI = "http://localhost:8080/"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Manual Gmail OAuth setup helper for draft-only Trustpilot review invitations."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    auth_parser = subparsers.add_parser("auth-url", help="Print a Gmail OAuth authorization URL.")
    auth_parser.add_argument("--client-id", default=os.environ.get("GOOGLE_GMAIL_CLIENT_ID", ""))
    auth_parser.add_argument("--redirect-uri", default=os.environ.get("GOOGLE_GMAIL_REDIRECT_URI", DEFAULT_REDIRECT_URI))
    auth_parser.add_argument("--scope", default=os.environ.get("GOOGLE_GMAIL_SCOPES", DEFAULT_SCOPE))

    exchange_parser = subparsers.add_parser("exchange-code", help="Exchange an authorization code for a refresh token.")
    exchange_parser.add_argument("--client-id", default=os.environ.get("GOOGLE_GMAIL_CLIENT_ID", ""))
    exchange_parser.add_argument("--client-secret", default=os.environ.get("GOOGLE_GMAIL_CLIENT_SECRET", ""))
    exchange_parser.add_argument("--code", default="")
    exchange_parser.add_argument("--redirect-uri", default=os.environ.get("GOOGLE_GMAIL_REDIRECT_URI", DEFAULT_REDIRECT_URI))
    exchange_parser.add_argument(
        "--show-refresh-token",
        action="store_true",
        help="Print the real refresh token locally. Do not share it and do not commit it.",
    )

    args = parser.parse_args()
    if args.command == "auth-url":
        return _auth_url(args)
    if args.command == "exchange-code":
        return _exchange_code(args)
    return 2


def _auth_url(args) -> int:
    if not args.client_id:
        print("Missing client ID. Set GOOGLE_GMAIL_CLIENT_ID or pass --client-id.", file=sys.stderr)
        return 1
    params = {
        "client_id": args.client_id,
        "redirect_uri": args.redirect_uri,
        "response_type": "code",
        "scope": args.scope or DEFAULT_SCOPE,
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
    }
    url = AUTH_URL + "?" + urllib.parse.urlencode(params)
    print("Open this URL in a browser signed in as info@kidstoylover.com:")
    print(url)
    print()
    print("After approval, paste only the authorization code into the exchange-code command.")
    print("Do not share the code, client secret, refresh token, or access token.")
    return 0


def _exchange_code(args) -> int:
    code = args.code or input("Paste authorization code: ").strip()
    if not args.client_id:
        print("Missing client ID. Set GOOGLE_GMAIL_CLIENT_ID or pass --client-id.", file=sys.stderr)
        return 1
    if not args.client_secret:
        print("Missing client secret. Set GOOGLE_GMAIL_CLIENT_SECRET or pass --client-secret.", file=sys.stderr)
        return 1
    if not code:
        print("Missing authorization code.", file=sys.stderr)
        return 1

    payload = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": args.client_id,
            "client_secret": args.client_secret,
            "redirect_uri": args.redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        print("OAuth token exchange failed. No token was stored.", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 1

    refresh_token = data.get("refresh_token", "")
    if not refresh_token:
        print("No refresh token returned. Try generating a fresh auth URL with prompt=consent.")
        print("No token was stored.")
        return 1

    print("Refresh token received. No file was written.")
    print("Masked refresh token:", _mask_token(refresh_token))
    print("Put the real token into local .env only as GOOGLE_GMAIL_REFRESH_TOKEN=...")
    print("Do not paste it into chat, logs, reports, screenshots, or Git.")
    if args.show_refresh_token:
        print()
        print("WARNING: showing the real refresh token locally. Do not share it.")
        print("GOOGLE_GMAIL_REFRESH_TOKEN=" + refresh_token)
    else:
        print("Run again with --show-refresh-token only if you need to display it locally.")
    return 0


def _mask_token(token: str) -> str:
    if len(token) <= 8:
        return "*" * len(token)
    return token[:4] + "*" * max(8, len(token) - 8) + token[-4:]


if __name__ == "__main__":
    raise SystemExit(main())
