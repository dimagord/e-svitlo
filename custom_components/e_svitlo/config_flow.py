"""Config flow for e-svitlo integration."""
from __future__ import annotations

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import AuthError, ESvitloClient
from .const import CONF_BASE_URL, DEFAULT_BASE_URL, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Optional(CONF_BASE_URL, default=DEFAULT_BASE_URL): str,
        vol.Required("email"): str,
        vol.Required("password"): str,
    }
)


async def _validate_credentials(
    hass: HomeAssistant, base_url: str, email: str, password: str
) -> list[dict]:
    """Try to log in and fetch accounts. Raise AuthError on bad credentials."""
    client = ESvitloClient(base_url, email, password)
    try:
        await client.login()
        accounts = await client.get_accounts()
    finally:
        await client.close()
    return [
        {
            "internal_id": a.internal_id,
            "personal_no": a.personal_no,
            "name": a.name,
            "address": a.address,
        }
        for a in accounts
    ]


class ESvitloConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the e-svitlo config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            base_url = user_input[CONF_BASE_URL].rstrip("/")
            email = user_input["email"].strip()
            password = user_input["password"]

            try:
                accounts = await _validate_credentials(
                    self.hass, base_url, email, password
                )
            except AuthError:
                errors["base"] = "invalid_auth"
            except Exception:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(f"{base_url}_{email}")
                self._abort_if_unique_id_configured()

                return self.async_create_entry(
                    title=f"e-svitlo ({email})",
                    data={
                        CONF_BASE_URL: base_url,
                        "email": email,
                        "password": password,
                        "accounts": accounts,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
