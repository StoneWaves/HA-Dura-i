"""Dura-i Select Entity."""

from __future__ import annotations

import logging

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .inverter import Inverter
from .registers import REGISTERS

_LOGGER = logging.getLogger(__name__)

# Option label -> register value for 0x2100.
WORK_MODES = {
    "Self Consumption Priority": 0,
    "Feed In Priority": 1,
    "Time based Control": 2,
    "Backup Supply": 3,
    "Battery Discharge": 4,
}


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Create select entities."""
    controller = hass.data[DOMAIN]["controller"]

    for inverter in controller.inverters:
        controller.select_entities[inverter.serial_number + "_hybrid_work_mode"] = (
            InverterSelectEntity(
                controller,
                inverter,
                "Hybrid Work Mode",
                "hybrid_work_mode",
                "mdi:all-inclusive-box-outline",
                WORK_MODES,
            )
        )

    async_add_entities(controller.get_select_entities())

    await controller.setup_done("select")


class InverterSelectEntity(SelectEntity):
    """A setting with a fixed set of values, backed by one register."""

    def __init__(
        self,
        controller,
        inverter: Inverter,
        entityName,
        entityType,
        icon,
        options: dict[str, int],
        category=EntityCategory.CONFIG,
    ) -> None:
        """Inverter initialiser."""
        self.currentValue = None
        self.controller = controller
        self.inverter = inverter
        self.value_key = entityType
        self.register_to_change = REGISTERS[entityType].address
        self._option_values = options

        self._attr_device_info = inverter.device_info
        self._attr_options = list(options)
        self._attr_current_option = None
        self.entity_id = generate_entity_id(
            "select.{}", inverter.serial_number + "_" + entityType, [], None
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
        raw = values[self.value_key]
        option = next(
            (label for label, value in self._option_values.items() if value == raw),
            None,
        )
        if option is None:
            _LOGGER.warning(
                "%s: inverter reports unknown value %s for register 0x%04X",
                self.name,
                raw,
                self.register_to_change,
            )

        if self.currentValue is not None and self.currentValue == option:
            # avoid noise...
            return

        if self.currentValue is not None:
            _LOGGER.info("%s changed from %s to %s", self.name, self.currentValue, option)

        self.currentValue = option
        self._attr_current_option = option
        if self.hass is not None:
            self.async_write_ha_state()

    async def async_select_option(self, option: str) -> None:
        """Receive changes from HomeAssistant and push to the inverter."""
        if self.currentValue is not None and self.currentValue == option:
            # avoid noise...
            return

        await self.controller.set_register(
            self.inverter, self.register_to_change, self._option_values[option]
        )
