from __future__ import annotations

import voluptuous as vol
from aiohttp import ClientResponseError

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AirplusClient, extract_code, make_auth_url, make_pkce
from .const import AUTH_METHOD_EMAIL_OTP, AUTH_METHOD_OAUTH, CONF_TOKEN, DOMAIN
from .email_auth import EmailOTPAuth, EmailOTPAuthError


class PhilipsAirplusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._verifier: str | None = None
        self._auth_url: str | None = None
        self._email: str | None = None
        self._vtoken: str | None = None

    async def async_step_user(self, user_input: dict | None = None):
        return await self.async_step_auth_method(user_input)

    async def async_step_auth_method(self, user_input: dict | None = None):
        if user_input is not None:
            method = user_input["auth_method"]
            if method == AUTH_METHOD_EMAIL_OTP:
                return await self.async_step_email()
            return await self.async_step_oauth()

        return self.async_show_form(
            step_id="auth_method",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "auth_method",
                        default=AUTH_METHOD_EMAIL_OTP,
                    ): vol.In(
                        {
                            AUTH_METHOD_EMAIL_OTP: "Email + verification code",
                            AUTH_METHOD_OAUTH: "Redirect URL / OAuth",
                        }
                    ),
                }
            ),
        )

    async def async_step_email(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            email = user_input["email"].strip()
            if not email or "@" not in email:
                errors["email"] = "invalid_email"
            else:
                session = async_get_clientsession(self.hass)
                auth = EmailOTPAuth(session)
                try:
                    self._vtoken = await auth.async_request_otp(email)
                except EmailOTPAuthError:
                    errors["base"] = "otp_send_failed"
                else:
                    self._email = email
                    return await self.async_step_email_otp()

        return self.async_show_form(
            step_id="email",
            data_schema=vol.Schema({vol.Required("email"): str}),
            errors=errors,
        )

    async def async_step_email_otp(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if user_input is not None:
            otp_code = user_input["otp_code"].strip()
            if not otp_code:
                errors["otp_code"] = "missing_otp"
            else:
                session = async_get_clientsession(self.hass)
                auth = EmailOTPAuth(session)
                try:
                    session_token = await auth.async_verify_otp(
                        self._email or "",
                        otp_code,
                        self._vtoken or "",
                    )
                    token = await auth.async_exchange_session(session_token)
                    client = AirplusClient(session, token)
                    user = await client.async_get_user()
                except (ClientResponseError, EmailOTPAuthError, KeyError):
                    errors["base"] = "otp_verify_failed"
                else:
                    await self.async_set_unique_id(user["id"])
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user.get("name") or user["id"],
                        data={CONF_TOKEN: token},
                    )

        return self.async_show_form(
            step_id="email_otp",
            data_schema=vol.Schema({vol.Required("otp_code"): str}),
            errors=errors,
            description_placeholders={"email": self._email or ""},
        )

    async def async_step_oauth(self, user_input: dict | None = None):
        errors: dict[str, str] = {}

        if self._verifier is None:
            self._verifier, challenge = make_pkce()
            self._auth_url = make_auth_url(challenge)

        if user_input is not None:
            code = extract_code(user_input["redirect_url"])
            if not code:
                errors["redirect_url"] = "missing_code"
            else:
                session = async_get_clientsession(self.hass)
                client = AirplusClient(session, {})
                try:
                    token = await client.async_exchange_code(code, self._verifier)
                    user = await client.async_get_user()
                except ClientResponseError:
                    errors["base"] = "auth_failed"
                else:
                    await self.async_set_unique_id(user["id"])
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title=user.get("name") or user["id"],
                        data={CONF_TOKEN: token},
                    )

        return self.async_show_form(
            step_id="oauth",
            data_schema=vol.Schema(
                {
                    vol.Optional("auth_url", default=self._auth_url or ""): str,
                    vol.Required("redirect_url"): str,
                }
            ),
            errors=errors,
            description_placeholders={"auth_url": self._auth_url or ""},
        )
