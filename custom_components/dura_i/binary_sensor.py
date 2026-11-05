"""Inverter Binary Sensor."""

from __future__ import annotations

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .inverter import Inverter

_LOGGER = logging.getLogger(__name__)

# (key, name, icon, is_import)
GRID_DIRECTION_SENSORS = (
    ("grid_am_exporting", "Am Exporting", "mdi:transmission-tower-import", False),
    ("grid_am_importing", "Am Importing", "mdi:transmission-tower-export", True),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up binary sensors."""
    controller = hass.data[DOMAIN]["controller"]

    for inverter in controller.inverters:
        for key, name, icon, is_import in GRID_DIRECTION_SENSORS:
            controller.binary_sensor_entities[inverter.serial_number + "_" + key] = (
                GridDirectionSensor(controller, inverter, name, key, icon, is_import)
            )

    async_add_entities(controller.get_binary_sensor_entities())

    await controller.setup_done("binary_sensor")


class GridDirectionSensor(BinarySensorEntity):
    """On while the inverter has steadily imported (or exported) for a while."""

    _attr_device_class = BinarySensorDeviceClass.POWER

    def __init__(
        self,
        controller,
        inverter: Inverter,
        entityName,
        entityType,
        icon,
        is_import: bool,
    ) -> None:
        """Init binary sensor entity."""
        self.controller = controller
        self.inverter = inverter
        self._is_import = is_import

        self._attr_device_info = inverter.device_info
        self.entity_id = generate_entity_id(
            "binary_sensor.{}", inverter.serial_number + "_" + entityType, [], None
        )
        self._attr_unique_id = inverter.serial_number + "_" + entityType
        self._attr_name = entityName
        self._attr_icon = icon
        self._attr_is_on = False

    def handle_poll(self, values: dict) -> None:
        """Re-evaluate from the controller's grid load history."""
        new_state = self.controller.am_exporting_importing(
            self.inverter, self._is_import
        )
        if new_state == self._attr_is_on:
            return

        self._attr_is_on = new_state
        if self.hass is not None:
            self.async_write_ha_state()
