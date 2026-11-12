"""Switch entity for an inverter."""

from __future__ import annotations

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .auto_charge import (
    AutoChargeSwitch,
    DelayChargeStartSwitch,
    KeepChargeWindowSwitch,
)
from .const import DOMAIN
from .inverter import Inverter
from .registers import REGISTERS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Initialise from the controller."""
    controller = hass.data[DOMAIN]["controller"]

    for inverter in controller.inverters:
        controller.switch_entities[inverter.serial_number + "_eps_enabled"] = (
            InverterSwitchEntity(
                controller, inverter, "EPS Enabled", "eps_enabled", "mdi:power-socket"
            )
        )
        # On writes 1 (force charge), off writes 0 (normal operation). If the
        # inverter is force-discharging (2) this shows off, and turning it off
        # also ends the force discharge.
        controller.switch_entities[inverter.serial_number + "_force_charge"] = (
            InverterSwitchEntity(
                controller,
                inverter,
                "Force Charge",
                "force_charge",
                "mdi:battery-charging-high",
            )
        )

    entities = controller.get_switch_entities()
    # Not fed by the poll, so kept out of controller.switch_entities.
    if controller.inverters:
        entities.append(AutoChargeSwitch(hass.data[DOMAIN]["auto_charge"]))
        entities.append(KeepChargeWindowSwitch(hass.data[DOMAIN]["auto_charge"]))
        entities.append(DelayChargeStartSwitch(hass.data[DOMAIN]["auto_charge"]))
    async_add_entities(entities)

    await controller.setup_done("switch")


class InverterSwitchEntity(SwitchEntity):
    """An on/off setting backed by one register."""

    def __init__(
        self,
        controller,
        inverter: Inverter,
        entityName,
        entityType,
        icon,
        category=EntityCategory.CONFIG,
        valueOn=1,
        valueOff=0,
    ) -> None:
        """Inverter switch entity initialiser."""
        self.currentValue = None
        self.controller = controller
        self.inverter = inverter
        self.value_key = entityType
        self.register_to_change = REGISTERS[entityType].address
        self.value_on = valueOn
        self.value_off = valueOff

        self._attr_device_info = inverter.device_info
        self.entity_id = generate_entity_id(
            "switch.{}", inverter.serial_number + "_" + entityType, [], None
        )
        self._attr_unique_id = inverter.serial_number + "_" + entityType
        self._attr_name = entityName
        self._attr_icon = icon
        # Controls change the inverter, so users opt in to each one.
        self._attr_entity_registry_enabled_default = False

        if category is not None:
            self._attr_entity_category = category

    def handle_poll(self, values: dict) -> None:
        """Take this setting's value from a completed poll."""
        new_value = values[self.value_key]
        if self.currentValue is not None and self.currentValue == new_value:
            # avoid noise...
            return

        if self.currentValue is not None:
            _LOGGER.info(
                "%s changed from %s to %s", self.name, self.currentValue, new_value
            )

        self.currentValue = new_value
        self._attr_is_on = new_value == self.value_on
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_turn_on(self, **kwargs) -> None:
        """Turn on switch."""
        await self.controller.set_register(
            self.inverter, self.register_to_change, self.value_on
        )

    async def async_turn_off(self, **kwargs) -> None:
        """Turn off switch."""
        await self.controller.set_register(
            self.inverter, self.register_to_change, self.value_off
        )
