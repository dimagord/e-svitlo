"""Number entities for e-svitlo meter reading input."""
from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode, RestoreNumber
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ESvitloCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, ESvitloCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities: list[ESvitloNumber] = []

    for coordinator in coordinators.values():
        await coordinator.async_config_entry_first_refresh()
        data = coordinator.data or {}

        entities.append(ESvitloNumber(coordinator, zone=1))
        if data.get("last_z2") is not None:
            entities.append(ESvitloNumber(coordinator, zone=2))

    async_add_entities(entities)


class ESvitloNumber(CoordinatorEntity[ESvitloCoordinator], RestoreNumber):
    """Number entity for entering a meter zone reading before submission."""

    _attr_has_entity_name = True
    _attr_native_min_value = 0
    _attr_native_max_value = 999999
    _attr_native_step = 1
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:counter"

    def __init__(self, coordinator: ESvitloCoordinator, zone: int) -> None:
        super().__init__(coordinator)
        self._zone = zone
        self._data_key = f"last_z{zone}"
        self._attr_unique_id = f"{coordinator.account_id}_input_z{zone}"
        self._attr_name = f"Reading zone {zone}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.account_id)},
            name=coordinator.account_name,
            manufacturer="e-svitlo",
            model="Household account",
        )
        self._attr_native_value: float = 0

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_number_data()
        if last is not None and last.native_value is not None:
            self._attr_native_value = last.native_value
        elif self.coordinator.data:
            self._attr_native_value = float(
                self.coordinator.data.get(self._data_key) or 0
            )

    async def async_set_native_value(self, value: float) -> None:
        self._attr_native_value = value
        self.async_write_ha_state()
