"""Sensor platform for e-svitlo."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import ESvitloCoordinator


@dataclass(frozen=True)
class ESvitloSensorDescription(SensorEntityDescription):
    data_key: str = ""
    always_add: bool = True


SENSOR_TYPES: tuple[ESvitloSensorDescription, ...] = (
    ESvitloSensorDescription(
        key="balance",
        data_key="balance",
        name="Balance",
        native_unit_of_measurement="UAH",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:currency-uah",
    ),
    ESvitloSensorDescription(
        key="last_payment",
        data_key="last_payment",
        name="Last payment",
        native_unit_of_measurement="UAH",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:cash-check",
    ),
    ESvitloSensorDescription(
        key="last_payment_date",
        data_key="last_payment_date",
        name="Last payment date",
        icon="mdi:calendar-check",
    ),
    ESvitloSensorDescription(
        key="last_reading_z1",
        data_key="last_z1",
        name="Last reading zone 1",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:meter-electric",
    ),
    ESvitloSensorDescription(
        key="last_reading_z2",
        data_key="last_z2",
        name="Last reading zone 2",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:meter-electric-outline",
        always_add=False,  # Only added for 2-zone meters
    ),
    ESvitloSensorDescription(
        key="last_reading_date",
        data_key="last_reading_date",
        name="Last reading date",
        icon="mdi:calendar-clock",
    ),
    ESvitloSensorDescription(
        key="monthly_consumption",
        data_key="monthly_consumption",
        name="Monthly consumption",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        icon="mdi:lightning-bolt",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinators: dict[str, ESvitloCoordinator] = hass.data[DOMAIN][entry.entry_id]["coordinators"]
    entities: list[ESvitloSensor] = []

    for coordinator in coordinators.values():
        # Do initial refresh to know zone count before adding entities
        await coordinator.async_config_entry_first_refresh()
        data = coordinator.data or {}
        has_z2 = data.get("last_z2") is not None

        for description in SENSOR_TYPES:
            if not description.always_add and description.key == "last_reading_z2" and not has_z2:
                continue
            entities.append(ESvitloSensor(coordinator, description))

    async_add_entities(entities)


class ESvitloSensor(CoordinatorEntity[ESvitloCoordinator], SensorEntity):
    """A single sensor for an e-svitlo account."""

    entity_description: ESvitloSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: ESvitloCoordinator,
        description: ESvitloSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{coordinator.account_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.account_id)},
            name=coordinator.account_name,
            manufacturer="e-svitlo",
            model="Household account",
        )

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.coordinator.data.get(self.entity_description.data_key)
