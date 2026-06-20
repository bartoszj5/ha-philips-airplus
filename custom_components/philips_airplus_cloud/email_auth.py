from __future__ import annotations

import hashlib
import json
import secrets
import time
import urllib.parse
from base64 import urlsafe_b64encode

from aiohttp import ClientError, ClientSession

from .const import (
    AUTH_URL,
    CLIENT_ID,
    GIGYA_API_KEY,
    GIGYA_GET_IDS_URL,
    GIGYA_OTP_LOGIN_URL,
    GIGYA_OTP_SEND_URL,
    OIDC_TOKEN_URL,
    REDIRECT_URI,
    SCOPE,
)


class EmailOTPAuthError(Exception):
    """Raised when email verification login fails."""


class EmailOTPAuth:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def async_request_otp(self, email: str) -> str:
        try:
            async with self._session.post(
                GIGYA_OTP_SEND_URL,
                data={
                    "email": email.strip(),
                    "apiKey": GIGYA_API_KEY,
                    "format": "json",
                },
            ) as response:
                data = await response.json(content_type=None)
        except (ClientError, json.JSONDecodeError) as ex:
            raise EmailOTPAuthError(f"OTP request failed: {ex}") from ex

        if data.get("errorCode") != 0:
            message = data.get("errorMessage", "Unknown error")
            raise EmailOTPAuthError(f"OTP request rejected: {message}")

        vtoken = data.get("vToken")
        if not vtoken:
            raise EmailOTPAuthError("OTP response did not include vToken")
        return vtoken

    async def async_verify_otp(self, email: str, code: str, vtoken: str) -> str:
        try:
            async with self._session.post(
                GIGYA_OTP_LOGIN_URL,
                data={
                    "email": email.strip(),
                    "code": code.strip(),
                    "vToken": vtoken,
                    "apiKey": GIGYA_API_KEY,
                    "format": "json",
                },
            ) as response:
                data = await response.json(content_type=None)
        except (ClientError, json.JSONDecodeError) as ex:
            raise EmailOTPAuthError(f"OTP verification failed: {ex}") from ex

        if data.get("errorCode") != 0:
            message = data.get("errorMessage", "Unknown error")
            raise EmailOTPAuthError(f"OTP verification rejected: {message}")

        session_token = data.get("sessionInfo", {}).get("cookieValue")
        if not session_token:
            raise EmailOTPAuthError("OTP response did not include session token")
        return session_token

    async def async_exchange_session(self, session_token: str) -> dict:
        verifier = secrets.token_urlsafe(64)
        challenge = (
            urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )
        code = await self._async_authorize_with_session(session_token, challenge)
        return await self._async_exchange_code(code, verifier)

    async def _async_authorize_with_session(
        self,
        session_token: str,
        challenge: str,
    ) -> str:
        authorize_params = {
            "client_id": CLIENT_ID,
            "response_type": "code",
            "redirect_uri": REDIRECT_URI,
            "scope": SCOPE,
            "state": secrets.token_urlsafe(16),
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "prompt": "none",
        }
        authorize_url = f"{AUTH_URL}?{urllib.parse.urlencode(authorize_params)}"

        async with self._session.get(authorize_url, allow_redirects=False) as response:
            if response.status not in (301, 302, 303, 307, 308):
                body = (await response.text())[:300]
                raise EmailOTPAuthError(
                    f"Authorize step returned HTTP {response.status}: {body}"
                )
            location = response.headers.get("Location", "")

        query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        context = (query.get("context") or [""])[0]
        if not context:
            raise EmailOTPAuthError("Authorize step did not return context")

        async with self._session.post(
            GIGYA_GET_IDS_URL,
            data={
                "APIKey": GIGYA_API_KEY,
                "includeTicket": "true",
                "format": "json",
            },
        ) as response:
            data = await response.json(content_type=None)
        gmid_ticket = data.get("gmidTicket")
        if not gmid_ticket:
            raise EmailOTPAuthError("Gigya getIDs did not return gmidTicket")

        continue_params = {
            "context": context,
            "login_token": session_token,
            "gmidTicket": gmid_ticket,
            "client_id": CLIENT_ID,
        }
        continue_url = f"{AUTH_URL}/continue?{urllib.parse.urlencode(continue_params)}"
        async with self._session.get(continue_url, allow_redirects=False) as response:
            if response.status not in (301, 302, 303, 307, 308):
                body = (await response.text())[:300]
                raise EmailOTPAuthError(
                    f"Authorize continue returned HTTP {response.status}: {body}"
                )
            location = response.headers.get("Location", "")

        query = urllib.parse.parse_qs(urllib.parse.urlparse(location).query)
        if error := (query.get("errorMessage") or [""])[0]:
            raise EmailOTPAuthError(f"Authorize continue failed: {error}")
        code = (query.get("code") or [""])[0]
        if not code:
            raise EmailOTPAuthError("Authorize continue did not return code")
        return code

    async def _async_exchange_code(self, code: str, verifier: str) -> dict:
        async with self._session.post(
            OIDC_TOKEN_URL,
            data={
                "client_id": CLIENT_ID,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": REDIRECT_URI,
                "code_verifier": verifier,
            },
        ) as response:
            text = await response.text()

        try:
            token = json.loads(text)
        except json.JSONDecodeError as ex:
            raise EmailOTPAuthError(f"Token response was not JSON: {text[:200]}") from ex

        if "access_token" not in token:
            message = token.get("error_description") or token.get("error") or "unknown"
            raise EmailOTPAuthError(f"Token exchange failed: {message}")

        token["obtained_at"] = int(time.time())
        if "expires_in" in token:
            token["expires_at"] = token["obtained_at"] + int(token["expires_in"]) - 60
        return token
