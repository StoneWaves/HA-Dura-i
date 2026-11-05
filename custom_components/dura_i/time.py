"""Dura-i time entities (scheduled charge windows)."""

from __future__ import annotations

from datetime import time
import logging

from homeassistant.components.time import TimeEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .inverter import Inverter
from .registers import REGISTERS, encode_time

_LOGGER = logging.getLogger(__name__)

# (key, name, icon). ``key`` is both the unique-ID suffix and the register name
# in registers.py that the entity reads and writes.
TIMES = (
    ("charge_window_1_start", "Charge Window 1 Start", "mdi:clock-start"),
    ("charge_window_1_end", "Charge Window 1 End", "mdi:clock-end"),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create time entities."""
    controller = hass.data[DOMAIN]["controller"]

    for inverter in controller.inverters:
        for key, name, icon in TIMES:
            controller.time_entities[inverter.serial_number + "_" + key] = (
                InverterTimeEntity(controller, inverter, name, key, icon)
            )

    async_add_entities(controller.get_time_entities())

    await controller.setup_done("time")


class InverterTimeEntity(TimeEntity):
    """A time-of-day setting backed by one packed HH:MM register."""

    def __init__(
        self,
        controller,
        inverter: Inverter,
        entityName,
        entityType,
        icon,
        category=EntityCategory.CONFIG,
    ) -> None:
        """Initialise a time entity."""
        self.currentValue = None
        self.controller = controller
        self.inverter = inverter
        self.value_key = entityType
        self.register_to_change = REGISTERS[entityType].address

        self._attr_device_info = inverter.device_info
        self.entity_id = generate_entity_id(
            "time.{}", inverter.serial_number + "_" + entityType, [], None
        )
        self._attr_unique_id = inverter.serial_number + "_" + entityType
        self._attr_name = entityName
        self._attr_icon = icon
        self._attr_native_value = None
        # Controls change the inverter, so users opt in to each one.
        self._attr_entity_registry_enabled_default = False

        if category is not None:
            self._attr_entity_category = category

    def handle_poll(self, values: dict) -> None:
        """Take this setting's value from a completed poll."""
        new_value = values[self.value_key]
        if new_value is None:
            # The register held something that isn't a valid time of day.
            return

        if self.currentValue is not None and self.currentValue == new_value:
            # avoid noise...
            return

        if self.currentValue is not None:
            _LOGGER.info(
                "%s changed from %s to %s", self.name, self.currentValue, new_value
            )

        self.currentValue = new_value
        self._attr_native_value = new_value
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_set_value(self, value: time) -> None:
        """Write a new time from HA to the inverter."""
        # The register holds hours and minutes only.
        value = value.replace(second=0, microsecond=0)
        if self.currentValue is not None and self.currentValue == value:
            return

        await self.controller.set_register(
            self.inverter, self.register_to_change, encode_time(value)
        )
