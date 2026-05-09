"""e-svitlo integration for Home Assistant."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
import homeassistant.helpers.config_validation as cv

from .api import ESvitloClient
from .const import CONF_BASE_URL, DOMAIN

_LOGGER = logging.getLogger(__name__)

SERVICE_SUBMIT_READING = "submit_meter_reading"

SERVICE_SCHEMA = vol.Schema(
    {
        vol.Required("account_id"): cv.string,
        vol.Required("zone1"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("zone2", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("zone3", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up e-svitlo from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    client = ESvitloClient(
        base_url=entry.data[CONF_BASE_URL],
        email=entry.data["email"],
        password=entry.data["password"],
    )
    # Authenticate eagerly so we know it works at startup.
    try:
        await client.login()
    except Exception as err:
        _LOGGER.error("e-svitlo: failed to authenticate at startup: %s", err)
        # Don't fail setup — login will be retried on first service call.

    hass.data[DOMAIN][entry.entry_id] = client

    async def handle_submit_reading(call: ServiceCall) -> None:
        account_id: str = call.data["account_id"]
        z1: int = call.data["zone1"]
        z2: int = call.data.get("zone2", 0)
        z3: int = call.data.get("zone3", 0)

        _LOGGER.debug(
            "e-svitlo: submitting reading for account %s — Z1=%s Z2=%s Z3=%s",
            account_id, z1, z2, z3,
        )

        # Validate new reading is not less than previous (safety check).
        try:
            info = await client.get_meter_info(account_id)
        except Exception as err:
            raise HomeAssistantError(
                f"e-svitlo: could not fetch meter info: {err}"
            ) from err

        if not info["submission_allowed"]:
            raise HomeAssistantError(
                "e-svitlo: meter reading submission is currently not allowed "
                "(outside the permitted window)"
            )

        if z1 < info["last_z1"]:
            raise HomeAssistantError(
                f"e-svitlo: zone1 value {z1} is less than the last recorded "
                f"reading {info['last_z1']}. Submission refused."
            )
        if info["zone_count"] >= 2 and z2 < info["last_z2"]:
            raise HomeAssistantError(
                f"e-svitlo: zone2 value {z2} is less than the last recorded "
                f"reading {info['last_z2']}. Submission refused."
            )

        try:
            result = await client.submit_reading(account_id, z1, z2, z3)
            _LOGGER.info(
                "e-svitlo: reading submitted for account %s. Response: %s",
                account_id,
                result[:200] if result else "(empty)",
            )
        except Exception as err:
            raise HomeAssistantError(
                f"e-svitlo: submission failed: {err}"
            ) from err

    hass.services.async_register(
        DOMAIN,
        SERVICE_SUBMIT_READING,
        handle_submit_reading,
        schema=SERVICE_SCHEMA,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    client: ESvitloClient = hass.data[DOMAIN].pop(entry.entry_id, None)
    if client:
        await client.close()

    if not hass.data[DOMAIN]:
        hass.services.async_remove(DOMAIN, SERVICE_SUBMIT_READING)
        hass.data.pop(DOMAIN, None)

    return True
