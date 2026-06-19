#!/usr/bin/env python3
"""Small Philips Air+ / Versuni DA OAuth and device-list probe.

This intentionally keeps user tokens out of the repository unless --save-token is
provided. It uses the same OneID OAuth + PKCE flow observed in Air+ 3.18.1.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


CLIENT_ID = "-XsK7O6iEkLml77yDGDUi0ku"
CLIENT_SECRET = "V34BlAhuilIdOx0Imo16rGQ2"
REDIRECT_URI = "com.philips.air://loginredirect"
OIDC_BASE = "https://cdc.accounts.home.id/oidc/op/v1.0/4_JGZWlP8eQHpEqkvQElolbA"
AUTH_URL = f"{OIDC_BASE}/authorize"
TOKEN_URL = f"{OIDC_BASE}/oauth/token"
DA_BASE = "https://prod.eu-da.iot.versuni.com/api/da"
SCOPE = (
    "openid email profile address DI.Account.read DI.Account.write "
    "DI.AccountProfile.read DI.AccountProfile.write "
    "DI.AccountGeneralConsent.read DI.AccountGeneralConsent.write "
    "DI.GeneralConsent.read subscriptions profile_extended consents "
    "DI.AccountSubscription.read DI.AccountSubscription.write"
)


def b64url_no_pad(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def make_pkce() -> tuple[str, str]:
    verifier = b64url_no_pad(secrets.token_bytes(64))
    challenge = b64url_no_pad(hashlib.sha256(verifier.encode("iso-8859-1")).digest())
    return verifier, challenge


def http_form(url: str, data: dict[str, str]) -> dict:
    body = urllib.parse.urlencode(data).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    return http_json(request)


def http_json(request: urllib.request.Request) -> dict | list:
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"HTTP {exc.code} for {request.full_url}\n{detail}") from exc


def get_json(path: str, access_token: str) -> dict | list:
    request = urllib.request.Request(
        f"{DA_BASE}{path}",
        headers={"authorization": f"Bearer {access_token}"},
        method="GET",
    )
    return http_json(request)


def extract_code(redirect: str) -> str:
    parsed = urllib.parse.urlparse(redirect.strip())
    query = urllib.parse.parse_qs(parsed.query)
    code = query.get("code", [None])[0]
    if not code:
        if "accounts.home.id/authui/client/proxy" in redirect and "mode=afterConsent" in redirect:
            raise SystemExit(
                "To jest pośredni URL po zgodzie, jeszcze bez parametru code=. "
                "Przeglądarka nie wykonała końcowego przekierowania do "
                "com.philips.air://loginredirect. Uruchom skrypt ponownie i użyj "
                "nowo wygenerowanego linku; jeżeli znowu zatrzyma się na spinnerze, "
                "otwórz DevTools -> Network/Console i poszukaj blokowanego adresu "
                "com.philips.air://loginredirect?code=..."
            )
        raise SystemExit("Nie widzę parametru code= w podanym redirect URL.")
    return code


def print_json(label: str, value: dict | list) -> None:
    print(f"\n## {label}")
    print(json.dumps(value, indent=2, ensure_ascii=False))


def login(args: argparse.Namespace) -> dict:
    verifier, challenge = make_pkce()
    # Match the Android SDK's hand-built URL closely. In particular, the app
    # uses %20 for scope separators and appends the custom redirect URI raw.
    scope = urllib.parse.quote(SCOPE, safe="")
    url = (
        f"{AUTH_URL}?client_id={CLIENT_ID}"
        f"&code_challenge={challenge}"
        "&code_challenge_method=S256"
        "&response_type=code"
        f"&redirect_uri={REDIRECT_URI}"
        f"&ui_locales={args.locale}"
        f"&scope={scope}"
    )
    print("Otwórz ten URL w przeglądarce i zaloguj się kontem Air+/Philips:")
    print(url)
    print("\nPo przekierowaniu wklej pełny URL zaczynający się od:")
    print(f"{REDIRECT_URI}?code=...")
    redirect = input("\nRedirect URL: ").strip()
    code = extract_code(redirect)
    token = http_form(
        TOKEN_URL,
        {
            "client_id": CLIENT_ID,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
            "client_secret": CLIENT_SECRET,
            "code_verifier": verifier,
        },
    )
    if args.save_token:
        Path(args.save_token).write_text(json.dumps(token, indent=2), encoding="utf-8")
        print(f"\nZapisano token lokalnie: {args.save_token}")
    return token


def load_or_login(args: argparse.Namespace) -> dict:
    if args.token_file:
        return json.loads(Path(args.token_file).read_text(encoding="utf-8"))
    return login(args)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--locale", default="pl-PL")
    parser.add_argument("--token-file", help="Wczytaj wcześniej zapisany JSON z tokenami.")
    parser.add_argument("--save-token", help="Zapisz świeżo pobrany token JSON pod tą ścieżką.")
    parser.add_argument("--signature", action="store_true", help="Pobierz też podpis MQTT.")
    args = parser.parse_args()

    token = load_or_login(args)
    access_token = token.get("access_token")
    if not access_token:
        raise SystemExit("Token response nie zawiera access_token.")

    print_json("current user", get_json("/user/self", access_token))
    print_json("devices", get_json("/user/self/device", access_token))
    if args.signature:
        print_json("mqtt signature", get_json("/user/self/signature", access_token))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
