from __future__ import annotations

import voluptuous as vol
from aiohttp import ClientResponseError

from homeassistant import config_entries
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AirplusClient, extract_code, make_auth_url, make_pkce
from .const import CONF_TOKEN, DOMAIN


class PhilipsAirplusConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self) -> None:
        self._verifier: str | None = None
        self._auth_url: str | None = None

    async def async_step_user(self, user_input: dict | None = None):
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
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional("auth_url", default=self._auth_url or ""): str,
                    vol.Required("redirect_url"): str,
                }
            ),
            errors=errors,
            description_placeholders={"auth_url": self._auth_url or ""},
        )
