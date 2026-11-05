"""Dura-i Number Entities."""

from __future__ import annotations

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfPower
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, MAX_FEED_IN_POWER_W
from .inverter import Inverter
from .registers import REGISTERS

_LOGGER = logging.getLogger(__name__)

_POWER_KW = {
    "valueMultiplier": 1000,  # register is in W, entity shows kW
    "adjustForParallel": True,
}
_SOC = {
    "minValue": 0,
    "maxValue": 100,
    "stepSize": 5,
    "unitOfMeasurement": PERCENTAGE,
}

# (key, name, icon, options). ``key`` is both the unique-ID suffix and the
# register name in registers.py that the entity reads and writes.
NUMBERS = (
    (
        "battery_max_power",
        "Battery Discharge Max Power",
        "mdi:home-battery-outline",
        {"maxValue": 6, "stepSize": 0.5, **_POWER_KW},
    ),
    (
        "grid_max_charge_power",
        "Grid Charge Max Power",
        "mdi:transmission-tower-export",
        {"maxValue": 6, "stepSize": 0.5, **_POWER_KW},
    ),
    (
        "battery_max_charge_power",
        "Battery Max Charge Power",
        "mdi:battery-positive",
        {"maxValue": 6, "stepSize": 0.1, **_POWER_KW},
    ),
    (
        "grid_max_feed_in_power",
        "Grid Feed In Max Power",
        "mdi:transmission-tower-import",
        {"maxValue": MAX_FEED_IN_POWER_W / 1000, "stepSize": 0.1, **_POWER_KW},
    ),
    # Keys are kept as they were so existing entity IDs don't change.
    ("grid_max_charge_soc", "Grid Charge Max SoC", "mdi:battery-charging-high", _SOC),
    ("battery_max_soc", "Solar Charge Max SoC", "mdi:battery-arrow-up", _SOC),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up entities on intialisation."""
    controller = hass.data[DOMAIN]["controller"]

    for inverter in controller.inverters:
        for key, name, icon, options in NUMBERS:
            controller.number_entities[inverter.serial_number + "_" + key] = (
                InverterNumberEntity(controller, inverter, name, key, icon, **options)
            )

    async_add_entities(controller.get_number_entities())

    await controller.setup_done("number")


class InverterNumberEntity(NumberEntity):
    """A writable inverter setting backed by one register."""

    def __init__(
        self,
        controller,
        inverter: Inverter,
        entityName,
        entityType,
        icon,
        unitOfMeasurement=UnitOfPower.KILO_WATT,
        minValue=0,
        maxValue=0,
        stepSize=1,
        category=None,
        valueMultiplier=1,
        adjustForParallel=False,
    ) -> None:
        """Initialise a number entity."""
        self.currentValue = None
        self.inverter = inverter
        self.controller = controller
        self.value_key = entityType
        self.register_to_change = REGISTERS[entityType].address

        self._attr_device_info = inverter.device_info
        self.entity_id = generate_entity_id(
            "number.{}", inverter.serial_number + "_" + entityType, [], None
        )
        self._attr_unique_id = inverter.serial_number + "_" + entityType
        self._attr_name = entityName
        self._attr_native_unit_of_measurement = unitOfMeasurement
        self._attr_icon = icon
        self._attr_mode = NumberMode.BOX

        if category is not None:
            self._attr_entity_category = category

        self._attr_native_min_value = minValue
        # On parallel systems the limit applies to the whole system, so the
        # entity's range is the sum and the value is split across inverters.
        if adjustForParallel:
            self._attr_native_max_value = maxValue * len(self.controller.inverters)
        else:
            self._attr_native_max_value = maxValue

        self._attr_native_step = stepSize
        self.value_multiplier = valueMultiplier
        # Controls change the inverter, so users opt in to each one.
        self._attr_entity_registry_enabled_default = False
        self.adjust_for_parallel = adjustForParallel

    async def async_set_native_value(self, value: float) -> None:
        """Set the value from a HA interaction."""
        if self.currentValue is not None and self.currentValue == value:
            # avoid noise...
            return

        # Don't update currentValue here; the next poll confirms the change.
        await self.controller.set_register(
            self.inverter,
            self.register_to_change,
            int(value * self.get_value_multiplier()),
        )

    def get_value_multiplier(self) -> float:
        """Register units per displayed unit, split across parallel inverters."""
        if self.adjust_for_parallel is True and len(self.controller.inverters) > 1:
            return self.value_multiplier / len(self.controller.inverters)

        return self.value_multiplier

    def handle_poll(self, values: dict) -> None:
        """Take this setting's value from a completed poll."""
        self.set_number_value(values[self.value_key])

    def set_number_value(self, new_state: float) -> None:
        """Set the HA value from the inverter's modbus response."""
        newValue = new_state / self.get_value_multiplier()

        if self.currentValue is not None and self.currentValue == newValue:
            # avoid noise...
            return

        self.currentValue = newValue

        self._attr_native_value = self.currentValue

        if self.hass is not None:
            self.async_write_ha_state()
