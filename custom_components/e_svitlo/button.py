"""Button entity to submit meter readings for e-svitlo."""
from __future__ import annotations

import logging

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .api import ESvitloClient
from .const import DOMAIN
from .coordinator import ESvitloCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, ESvitloCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    client: ESvitloClient = hass.data[DOMAIN][entry.entry_id]["client"]

    async_add_entities(
        ESvitloSubmitButton(coordinator, client)
        for coordinator in coordinators.values()
    )


class ESvitloSubmitButton(CoordinatorEntity[ESvitloCoordinator], ButtonEntity):
    """Button that reads zone number entities and submits to e-svitlo."""

    _attr_has_entity_name = True
    _attr_name = "Submit reading"
    _attr_icon = "mdi:upload"

    def __init__(self, coordinator: ESvitloCoordinator, client: ESvitloClient) -> None:
        super().__init__(coordinator)
        self._client = client
        self._attr_unique_id = f"{coordinator.account_id}_submit"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.account_id)},
            name=coordinator.account_name,
            manufacturer="e-svitlo",
            model="Household account",
        )

    def _get_zone_value(self, zone: int) -> int | None:
        """Look up the current value of a zone number entity via the entity registry."""
        registry = er.async_get(self.hass)
        unique_id = f"{self.coordinator.account_id}_input_z{zone}"
        entity_id = registry.async_get_entity_id("number", DOMAIN, unique_id)
        if entity_id is None:
            return None
        state = self.hass.states.get(entity_id)
        if state is None or state.state in ("unknown", "unavailable"):
            return None
        try:
            return int(float(state.state))
        except ValueError:
            return None

    async def async_press(self) -> None:
        account_id = self.coordinator.account_id
        data = self.coordinator.data or {}

        z1 = self._get_zone_value(1)
        if z1 is None:
            raise HomeAssistantError(
                "e-svitlo: Zone 1 reading entity has no value. Set it first."
            )

        z2 = self._get_zone_value(2) or 0

        # Validate against last known readings
        last_z1 = data.get("last_z1") or 0
        last_z2 = data.get("last_z2") or 0
        if z1 < last_z1:
            raise HomeAssistantError(
                f"e-svitlo: Zone 1 value {z1} is less than last recorded {last_z1}."
            )
        if z2 and z2 < last_z2:
            raise HomeAssistantError(
                f"e-svitlo: Zone 2 value {z2} is less than last recorded {last_z2}."
            )

        # Check submission window
        try:
            info = await self._client.get_meter_info(account_id)
        except Exception as err:
            raise HomeAssistantError(f"e-svitlo: could not fetch meter info: {err}") from err

        if not info["submission_allowed"]:
            raise HomeAssistantError(
                "e-svitlo: submission is not allowed right now (outside the permitted window)."
            )

        _LOGGER.info("e-svitlo: submitting Z1=%s Z2=%s for account %s", z1, z2, account_id)
        try:
            await self._client.submit_reading(account_id, z1, z2)
        except Exception as err:
            raise HomeAssistantError(f"e-svitlo: submission failed: {err}") from err

        await self.coordinator.async_request_refresh()
