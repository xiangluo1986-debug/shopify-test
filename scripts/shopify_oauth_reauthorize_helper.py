"""Safe local Shopify OAuth reauthorization helper.

This helper supports manual Shopify OAuth scope refresh flows. It can generate
an authorization URL, exchange a pasted callback code for a token, optionally
save that token to the local .env with an explicit approval flag, and verify
read-only access scopes. It never prints token or client secret values.
"""

import argparse
import json
import os
import re
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from secrets import token_urlsafe


DEFAULT_SHOP_DOMAIN = "kidstoylover.myshopify.com"
REQUIRED_SCOPES = ("read_orders", "read_all_orders")
TOKEN_ENV_KEYS = (
    "SHOPIFY_ACCESS_TOKEN",
    "SHOPIFY_ADMIN_API_ACCESS_TOKEN",
    "SHOPIFY_API_PASSWORD",
)
SAVE_TOKEN_APPROVAL_VALUE = "YES_I_APPROVE_UPDATING_SHOPIFY_ACCESS_TOKEN"
LOAD_ENV_APPROVAL_VALUE = "YES_I_APPROVE_READING_LOCAL_ENV_FOR_SHOPIFY_OAUTH"
SHOP_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9-]*\.myshopify\.com$")
ENV_KEY_RE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate or complete a safe local Shopify OAuth reauthorization flow."
    )
    parser.add_argument("--mode", required=True, choices=["url", "exchange", "verify"])
    parser.add_argument("--shop", default="")
    parser.add_argument("--client-id", default="")
    parser.add_argument("--redirect-uri", default="")
    parser.add_argument("--scopes", default="")
    parser.add_argument("--state", default="")
    parser.add_argument("--code", default="")
    parser.add_argument("--env-path", default=".env")
    parser.add_argument("--token-env-key", default="")
    args = parser.parse_args()

    env = _load_runtime_env()
    shop = _normalize_shop(
        args.shop
        or _first_env(env, "SHOPIFY_OAUTH_SHOP_DOMAIN", "SHOPIFY_SHOP_DOMAIN", "SHOPIFY_SHOP")
        or DEFAULT_SHOP_DOMAIN
    )
    if not shop:
        print("Missing or invalid Shopify shop domain.", file=sys.stderr)
        return 1

    if args.mode == "url":
        return _mode_url(args, env, shop)
    if args.mode == "exchange":
        return _mode_exchange(args, env, shop)
    if args.mode == "verify":
        return _mode_verify(args, env, shop)
    return 2


def _mode_url(args: argparse.Namespace, env: dict[str, str], shop: str) -> int:
    client_id = args.client_id or env.get("SHOPIFY_CLIENT_ID", "")
    redirect_uri = args.redirect_uri or _first_env(env, "SHOPIFY_OAUTH_REDIRECT_URI", "SHOPIFY_REDIRECT_URI")
    if not client_id:
        print("Missing Shopify client ID. Set SHOPIFY_CLIENT_ID or pass --client-id.", file=sys.stderr)
        return 1
    if not redirect_uri:
        print("Missing Shopify redirect URI. Set SHOPIFY_REDIRECT_URI or pass --redirect-uri.", file=sys.stderr)
        return 1

    scopes = _required_scope_list(args.scopes or _first_env(env, "SHOPIFY_OAUTH_SCOPES", "SHOPIFY_SCOPES"))
    state = args.state or env.get("SHOPIFY_OAUTH_STATE") or token_urlsafe(24)
    params = {
        "client_id": client_id,
        "scope": ",".join(scopes),
        "redirect_uri": redirect_uri,
        "state": state,
    }
    auth_url = f"https://{shop}/admin/oauth/authorize?{urllib.parse.urlencode(params)}"

    print("shop_domain=" + shop)
    print("requested_scopes=" + ",".join(scopes))
    print("redirect_uri=" + redirect_uri)
    print("state_to_verify=" + state)
    print("authorization_url=" + auth_url)
    print("Open the authorization URL in a browser, approve in Shopify, then copy only the code value from the callback URL.")
    print("Do not share the code, client secret, access token, or .env contents.")
    return 0


def _mode_exchange(args: argparse.Namespace, env: dict[str, str], shop: str) -> int:
    client_id = args.client_id or env.get("SHOPIFY_CLIENT_ID", "")
    client_secret = env.get("SHOPIFY_CLIENT_SECRET", "")
    code = args.code or input("Paste Shopify callback code: ").strip()
    if not client_id:
        print("Missing Shopify client ID. Set SHOPIFY_CLIENT_ID or pass --client-id.", file=sys.stderr)
        return 1
    if not client_secret:
        print("Missing Shopify client secret. Set SHOPIFY_CLIENT_SECRET.", file=sys.stderr)
        return 1
    if not code:
        print("Missing Shopify callback code.", file=sys.stderr)
        return 1

    exchange = _exchange_code(shop, client_id, client_secret, code)
    if not exchange["success"]:
        print("token_exchange_succeeded=false")
        print("error_sanitized=" + exchange["error_sanitized"])
        print("token_output=false")
        return 1

    access_token = exchange["access_token"]
    returned_scopes = _split_scopes(exchange.get("scope", ""))
    print("token_exchange_succeeded=true")
    print("token_received=true")
    print("token_output=false")
    if returned_scopes:
        print("returned_scopes=" + ",".join(returned_scopes))

    saved = False
    backup_path = ""
    approval_present = env.get("SHOPIFY_OAUTH_SAVE_TOKEN") == SAVE_TOKEN_APPROVAL_VALUE
    if approval_present:
        save_result = _save_token_to_env(
            access_token=access_token,
            env_path=Path(args.env_path),
            configured_key=args.token_env_key or env.get("SHOPIFY_OAUTH_TOKEN_ENV_KEY", ""),
        )
        if not save_result["success"]:
            print("token_saved=false")
            print("env_backup_created=false")
            print("error_sanitized=" + save_result["error_sanitized"])
            return 1
        saved = True
        backup_path = save_result["backup_path"]
        print("token_saved=true")
        print("env_backup_created=true")
        print("env_backup_path=" + backup_path)
        print("updated_token_env_key=" + save_result["token_env_key"])
    else:
        print("Token exchange succeeded, but token was not saved because approval flag is missing.")
        print("token_saved=false")
        print("env_backup_created=false")

    verification = _verify_access_scopes(shop, access_token)
    _print_scope_verification(verification)
    print("shopify_write_performed=false")
    print("mutation_performed=false")
    print("translations_register_called=false")
    print("gmail_api_call_performed=false")
    print("email_sent=false")
    if saved:
        print("restart_web_recommended=true")
        print("env_backup_created=true")
        print("env_backup_path=" + backup_path)
    return 0 if verification["read_orders_present"] and verification["read_all_orders_present"] else 1


def _mode_verify(args: argparse.Namespace, env: dict[str, str], shop: str) -> int:
    token_result = _resolve_token_for_verify(env, args.token_env_key)
    if not token_result["success"]:
        print("scope_verification_succeeded=false")
        print("error_sanitized=" + token_result["error_sanitized"])
        print("token_output=false")
        return 1

    verification = _verify_access_scopes(shop, token_result["access_token"])
    _print_scope_verification(verification)
    print("token_env_key=" + token_result["token_env_key"])
    print("token_output=false")
    print("shopify_write_performed=false")
    print("mutation_performed=false")
    print("translations_register_called=false")
    print("gmail_api_call_performed=false")
    print("email_sent=false")
    return 0 if verification["read_orders_present"] and verification["read_all_orders_present"] else 1


def _exchange_code(shop: str, client_id: str, client_secret: str, code: str) -> dict[str, object]:
    token_url = f"https://{shop}/admin/oauth/access_token"
    payload = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
        }
    ).encode("utf-8")
    request = urllib.request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        return {
            "success": False,
            "error_sanitized": f"Shopify token endpoint returned HTTP {exc.code}.",
            "access_token": "",
        }
    except urllib.error.URLError as exc:
        return {
            "success": False,
            "error_sanitized": _safe_error(f"Shopify token endpoint request failed: {exc.reason}"),
            "access_token": "",
        }
    except OSError as exc:
        return {
            "success": False,
            "error_sanitized": _safe_error(f"Shopify token endpoint request failed: {exc}"),
            "access_token": "",
        }

    try:
        data = json.loads(body)
    except ValueError:
        return {
            "success": False,
            "error_sanitized": "Shopify token endpoint returned a non-JSON response.",
            "access_token": "",
        }
    access_token = str(data.get("access_token") or "")
    if not access_token:
        return {
            "success": False,
            "error_sanitized": "Shopify token endpoint did not return an access token.",
            "access_token": "",
        }
    return {
        "success": True,
        "access_token": access_token,
        "scope": str(data.get("scope") or ""),
    }


def _verify_access_scopes(shop: str, access_token: str) -> dict[str, object]:
    request = urllib.request.Request(
        f"https://{shop}/admin/oauth/access_scopes.json",
        headers={
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
    except urllib.error.HTTPError as exc:
        return _scope_result(False, set(), f"Shopify access-scope endpoint returned HTTP {exc.code}.", exc.code)
    except urllib.error.URLError as exc:
        return _scope_result(False, set(), _safe_error(f"Shopify access-scope request failed: {exc.reason}"), None)
    except OSError as exc:
        return _scope_result(False, set(), _safe_error(f"Shopify access-scope request failed: {exc}"), None)

    try:
        data = json.loads(body)
    except ValueError:
        return _scope_result(False, set(), "Shopify access-scope endpoint returned a non-JSON response.", status)

    handles = {
        str(scope.get("handle") or "").strip()
        for scope in data.get("access_scopes", [])
        if isinstance(scope, dict) and str(scope.get("handle") or "").strip()
    }
    return _scope_result(True, handles, "", status)


def _scope_result(success: bool, handles: set[str], error: str, status) -> dict[str, object]:
    return {
        "success": success,
        "scope_verification_succeeded": success,
        "shopify_http_status": status,
        "read_orders_present": "read_orders" in handles,
        "read_all_orders_present": "read_all_orders" in handles,
        "required_scopes_present": all(scope in handles for scope in REQUIRED_SCOPES),
        "scopes": sorted(handles),
        "error_sanitized": error,
    }


def _print_scope_verification(result: dict[str, object]) -> None:
    print("scope_verification_succeeded=" + _bool_text(result["scope_verification_succeeded"]))
    print("shopify_http_status=" + str(result["shopify_http_status"] or ""))
    print("active_token_scopes=" + ",".join(result["scopes"]))
    print("read_orders_present=" + _yes_no(result["read_orders_present"]))
    print("read_all_orders_present=" + _yes_no(result["read_all_orders_present"]))
    print("reauthorization_required=" + _bool_text(not result["required_scopes_present"]))
    if result["error_sanitized"]:
        print("error_sanitized=" + str(result["error_sanitized"]))


def _save_token_to_env(access_token: str, env_path: Path, configured_key: str) -> dict[str, str | bool]:
    if env_path.name != ".env":
        return {"success": False, "error_sanitized": "Only a project .env file can be updated.", "backup_path": ""}
    resolved = env_path.resolve(strict=False)
    if resolved.name != ".env":
        return {"success": False, "error_sanitized": "Only a project .env file can be updated.", "backup_path": ""}
    if not env_path.exists() or not env_path.is_file():
        return {"success": False, "error_sanitized": ".env was not found.", "backup_path": ""}

    lines = env_path.read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    present_keys = _present_token_keys(lines)
    token_key = _select_token_key(configured_key, present_keys)
    if not token_key["success"]:
        return {"success": False, "error_sanitized": token_key["error_sanitized"], "backup_path": ""}

    selected_key = token_key["token_env_key"]
    updated_lines = []
    replaced = False
    for line in lines:
        match = ENV_KEY_RE.match(line)
        if match and match.group(1) == selected_key:
            prefix = "export " if line.lstrip().startswith("export ") else ""
            updated_lines.append(f"{prefix}{selected_key}={access_token}{_line_ending(line)}")
            replaced = True
        else:
            updated_lines.append(line)

    if not replaced:
        if updated_lines and not updated_lines[-1].endswith(("\n", "\r")):
            updated_lines[-1] = updated_lines[-1] + "\n"
        updated_lines.append(f"{selected_key}={access_token}\n")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup_path = env_path.with_name(f".env.backup.{timestamp}")
    shutil.copy2(env_path, backup_path)
    env_path.write_text("".join(updated_lines), encoding="utf-8")
    return {
        "success": True,
        "error_sanitized": "",
        "backup_path": str(backup_path),
        "token_env_key": selected_key,
    }


def _resolve_token_for_verify(env: dict[str, str], configured_key: str) -> dict[str, str | bool]:
    selected_key = configured_key or env.get("SHOPIFY_OAUTH_TOKEN_ENV_KEY", "")
    if selected_key:
        if selected_key not in TOKEN_ENV_KEYS:
            return {
                "success": False,
                "error_sanitized": "SHOPIFY_OAUTH_TOKEN_ENV_KEY must be one supported Shopify token key.",
                "access_token": "",
                "token_env_key": "",
            }
        token = env.get(selected_key, "")
        if not token:
            return {
                "success": False,
                "error_sanitized": f"{selected_key} is not set in the current environment.",
                "access_token": "",
                "token_env_key": selected_key,
            }
        return {"success": True, "access_token": token, "token_env_key": selected_key}

    present = [key for key in TOKEN_ENV_KEYS if env.get(key)]
    if len(present) == 1:
        key = present[0]
        return {"success": True, "access_token": env[key], "token_env_key": key}
    if len(present) > 1:
        return {
            "success": False,
            "error_sanitized": "Multiple Shopify token environment keys are set. Set SHOPIFY_OAUTH_TOKEN_ENV_KEY.",
            "access_token": "",
            "token_env_key": "",
        }
    return {
        "success": False,
        "error_sanitized": "No Shopify token was found in the current environment.",
        "access_token": "",
        "token_env_key": "",
    }


def _select_token_key(configured_key: str, present_keys: list[str]) -> dict[str, str | bool]:
    if configured_key:
        if configured_key not in TOKEN_ENV_KEYS:
            return {
                "success": False,
                "error_sanitized": "SHOPIFY_OAUTH_TOKEN_ENV_KEY must be one supported Shopify token key.",
                "token_env_key": "",
            }
        return {"success": True, "error_sanitized": "", "token_env_key": configured_key}
    if len(present_keys) == 1:
        return {"success": True, "error_sanitized": "", "token_env_key": present_keys[0]}
    if len(present_keys) > 1:
        return {
            "success": False,
            "error_sanitized": "Multiple Shopify token keys exist in .env. Set SHOPIFY_OAUTH_TOKEN_ENV_KEY.",
            "token_env_key": "",
        }
    return {
        "success": False,
        "error_sanitized": "No supported Shopify token key exists in .env. Set SHOPIFY_OAUTH_TOKEN_ENV_KEY.",
        "token_env_key": "",
    }


def _present_token_keys(lines: list[str]) -> list[str]:
    keys = []
    for line in lines:
        match = ENV_KEY_RE.match(line)
        if match and match.group(1) in TOKEN_ENV_KEYS:
            keys.append(match.group(1))
    return keys


def _line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\n"):
        return "\n"
    if line.endswith("\r"):
        return "\r"
    return ""


def _load_runtime_env() -> dict[str, str]:
    env = dict(os.environ)
    if env.get("SHOPIFY_OAUTH_LOAD_ENV_FILE") != LOAD_ENV_APPROVAL_VALUE:
        return env
    env_path = Path(".env")
    if not env_path.exists() or not env_path.is_file():
        return env
    for raw_line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export ") :].strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        env.setdefault(key, _strip_env_value(value))
    return env


def _strip_env_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return value[1:-1]
    return value


def _required_scope_list(scope_text: str) -> list[str]:
    scopes = _split_scopes(scope_text)
    for scope in REQUIRED_SCOPES:
        if scope not in scopes:
            scopes.append(scope)
    return scopes


def _split_scopes(scope_text: str) -> list[str]:
    scopes = []
    for part in re.split(r"[\s,]+", str(scope_text or "")):
        scope = part.strip()
        if scope and scope not in scopes:
            scopes.append(scope)
    return scopes


def _first_env(env: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = env.get(key, "")
        if value:
            return value
    return ""


def _normalize_shop(shop: str) -> str:
    shop = (shop or "").strip().lower()
    return shop if SHOP_DOMAIN_RE.fullmatch(shop) else ""


def _yes_no(value: object) -> str:
    return "yes" if value is True else "no"


def _bool_text(value: object) -> str:
    return "true" if value is True else "false"


def _safe_error(value: object) -> str:
    text = str(value or "")
    text = re.sub(r"(?i)(access[_-]?token|client[_-]?secret|authorization|password|api[_-]?key)=?[^,\s&]+", r"\1=[redacted]", text)
    text = re.sub(r"shpat_[A-Za-z0-9_]+", "[redacted]", text)
    return text[:500]


if __name__ == "__main__":
    raise SystemExit(main())
