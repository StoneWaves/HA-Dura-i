"""Dura-i sensors.

Each sensor is one row in INVERTER_SENSORS (one per inverter) or SYSTEM_SENSORS
(summed across inverters). ``value_key`` names a value produced by the poll:
either a register in registers.py or one the controller derives (pv_power,
inverter_load, eps_load, versions, consumer_load).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfElectricCurrent,
    UnitOfElectricPotential,
    UnitOfEnergy,
    UnitOfPower,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .auto_charge import AutoChargeTargetSensor
from .const import DOMAIN
from .inverter import Inverter

_LOGGER = logging.getLogger(__name__)

DIAGNOSTIC = EntityCategory.DIAGNOSTIC


@dataclass(frozen=True)
class DuraSensor:
    """Definition of one sensor."""

    key: str  # unique-ID suffix; never change it for an existing sensor
    name: str
    icon: str
    unit: str | None = UnitOfPower.KILO_WATT
    device_class: SensorDeviceClass | None = SensorDeviceClass.POWER
    state_class: SensorStateClass | None = SensorStateClass.MEASUREMENT
    decimals: int | None = 2  # display precision
    category: EntityCategory | None = None
    enabled_by_default: bool = True
    never_decreases: bool = False  # lifetime counters only, not daily totals
    round_to: int | None = None  # round the stored value (cuts state churn)
    value_key: str | None = None  # defaults to key

    @property
    def value(self) -> str:
        return self.value_key or self.key


def _energy(key, name, icon, **kwargs) -> DuraSensor:
    return DuraSensor(
        key,
        name,
        icon,
        unit=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL_INCREASING,
        **kwargs,
    )


def _lifetime(key, name, icon, **kwargs) -> DuraSensor:
    return _energy(
        key, name, icon, never_decreases=True, category=DIAGNOSTIC, **kwargs
    )


def _current(key, name, icon) -> DuraSensor:
    return DuraSensor(
        key,
        name,
        icon,
        unit=UnitOfElectricCurrent.AMPERE,
        device_class=SensorDeviceClass.CURRENT,
        category=DIAGNOSTIC,
    )


def _voltage(key, name) -> DuraSensor:
    return DuraSensor(
        key,
        name,
        "mdi:lightning-bolt",
        unit=UnitOfElectricPotential.VOLT,
        device_class=SensorDeviceClass.VOLTAGE,
        decimals=1,
        category=DIAGNOSTIC,
    )


def _version(key, name, icon) -> DuraSensor:
    return DuraSensor(
        key,
        name,
        icon,
        unit=None,
        device_class=None,
        state_class=None,
        decimals=None,
        category=DIAGNOSTIC,
        enabled_by_default=False,
    )


def _readout(key, name, icon, unit=None, device_class=None, decimals=None):
    """A read-only view of a setting register: diagnostic, disabled by default."""
    return DuraSensor(
        key,
        name,
        icon,
        unit=unit,
        device_class=device_class,
        state_class=None,
        decimals=decimals,
        category=DIAGNOSTIC,
        enabled_by_default=False,
    )


INVERTER_SENSORS: tuple[DuraSensor, ...] = (
    DuraSensor(
        "SoC",
        "State of Charge",
        "mdi:battery",
        unit=PERCENTAGE,
        device_class=SensorDeviceClass.BATTERY,
        decimals=0,
        value_key="soc",
    ),
    # Power
    DuraSensor("pv_power", "PV Power", "mdi:solar-power", round_to=1),
    DuraSensor("mppt1_power", "MPPT1 Power", "mdi:solar-power", category=DIAGNOSTIC),
    DuraSensor("mppt2_power", "MPPT2 Power", "mdi:solar-power", category=DIAGNOSTIC),
    DuraSensor("battery_load", "Battery Load", "mdi:battery-minus-variant"),
    DuraSensor("grid_load", "Grid Load", "mdi:transmission-tower", round_to=1),
    DuraSensor("grid_tied_load", "Current Load", "mdi:home-lightning-bolt"),
    DuraSensor("eps_load", "EPS Load", "mdi:power-socket"),
    DuraSensor("inverter_load", "Inverter Load", "mdi:flash"),
    # Energy
    _energy("pv_energy_today", "PV Energy Today", "mdi:solar-power-variant"),
    _lifetime(
        "pv_energy_total", "PV Energy Total", "mdi:solar-power-variant", decimals=0
    ),
    _energy(
        "grid_energy_in_today", "Grid Energy In Today", "mdi:transmission-tower-import"
    ),
    _lifetime(
        "grid_energy_in_total", "Grid Energy In Total", "mdi:transmission-tower-import"
    ),
    _energy(
        "grid_energy_out_today",
        "Grid Energy Out Today",
        "mdi:transmission-tower-export",
    ),
    _lifetime(
        "grid_energy_out_total",
        "Grid Energy Out Total",
        "mdi:transmission-tower-export",
    ),
    _energy("battery_energy_in_today", "Battery Energy In Today", "mdi:battery-plus"),
    _lifetime("battery_energy_in_total", "Battery Energy In Total", "mdi:battery-plus"),
    _energy(
        "battery_energy_out_today", "Battery Energy Out Today", "mdi:battery-minus"
    ),
    _lifetime(
        "battery_energy_out_total", "Battery Energy Out Total", "mdi:battery-minus"
    ),
    # Electrical detail
    _current("battery_current", "Battery Current", "mdi:current-dc"),
    _current("grid_current", "Grid Current", "mdi:current-ac"),
    _current("mppt1_current", "MPPT1 Current", "mdi:current-dc"),
    _current("mppt2_current", "MPPT2 Current", "mdi:current-dc"),
    _voltage("battery_voltage", "Battery Voltage"),
    _voltage("grid_voltage", "Grid Voltage"),
    _voltage("mppt1_voltage", "MPPT1 Voltage"),
    _voltage("mppt2_voltage", "MPPT2 Voltage"),
    DuraSensor(
        "system_temp",
        "System Temp",
        "mdi:temperature-celsius",
        unit=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        decimals=0,
        category=DIAGNOSTIC,
    ),
    # Firmware
    _version("master_software_version", "Version Master", "mdi:code-block-braces"),
    _version("slave_software_version", "Version Slave", "mdi:code-block-brackets"),
    _version("ems_software_version", "Version EMS", "mdi:code-block-parentheses"),
    # Read-only views of inverter settings. All from the Solis map and
    # unconfirmed on Dura-i hardware, though the values look plausible
    # (see registers.py).
    _readout(
        "battery_reserve_soc",
        "Battery Reserve SoC",
        "mdi:battery-lock",
        unit=PERCENTAGE,
        decimals=0,
    ),
    _readout(
        "max_depth_of_discharge",
        "Max Depth of Discharge",
        "mdi:battery-arrow-down",
        unit=PERCENTAGE,
        decimals=0,
    ),
    _readout(
        "max_charge_limit_power",
        "Max Charge Limit Power",
        "mdi:battery-charging-high",
        unit=UnitOfPower.KILO_WATT,
        device_class=SensorDeviceClass.POWER,
        decimals=2,
    ),
    _readout("unidentified_2139", "Register 8505 (Unidentified)", "mdi:help-circle"),
)

# Created once, not per inverter. consumer_load always exists; the rest are
# only added when there is more than one inverter to sum.
CONSUMER_LOAD = DuraSensor(
    "consumer_load",
    "Dura-i Consumer Load",
    "mdi:power-socket",
    enabled_by_default=False,
    round_to=2,
)
SYSTEM_SENSORS: tuple[DuraSensor, ...] = tuple(
    replace(sensor, name="Dura-i " + sensor.name, round_to=2)
    for sensor in INVERTER_SENSORS
    if sensor.key
    in (
        "pv_power",
        "battery_load",
        "grid_load",
        "grid_tied_load",
        "eps_load",
        "inverter_load",
    )
)


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up sensor platform."""
    controller = hass.data[DOMAIN]["controller"]

    for inverter in controller.inverters:
        for description in INVERTER_SENSORS:
            controller.sensor_entities[
                inverter.serial_number + "_" + description.key
            ] = InverterSensorEntity(controller, inverter, description)

    system_sensors = [CONSUMER_LOAD]
    if len(controller.inverters) > 1:
        system_sensors.extend(SYSTEM_SENSORS)
    for description in system_sensors:
        controller.sensor_entities["dura_i_" + description.key] = InverterSensorEntity(
            controller, None, description
        )

    entities = controller.get_sensor_entities()
    # Not fed by the poll, so kept out of controller.sensor_entities.
    if controller.inverters:
        entities.append(AutoChargeTargetSensor(hass.data[DOMAIN]["auto_charge"]))
    async_add_entities(entities)

    await controller.setup_done("sensor")


class InverterSensorEntity(SensorEntity):
    """A sensor fed from the poll."""

    _attr_has_entity_name = True

    def __init__(
        self, controller, inverter: Inverter | None, description: DuraSensor
    ) -> None:
        """Create the sensor for one inverter, or system-wide if inverter is None."""
        self.controller = controller
        self.inverter = inverter
        self.description = description
        self.currentValue = None

        if inverter is not None:
            object_id = inverter.serial_number + "_" + description.key
            self._attr_device_info = inverter.device_info
        else:
            object_id = "dura_i_" + description.key
        self._attr_unique_id = object_id
        self.entity_id = generate_entity_id("sensor.{}", object_id, [], None)

        self._attr_name = description.name
        self._attr_translation_key = description.key.lower()
        self._attr_icon = description.icon
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_entity_registry_enabled_default = description.enabled_by_default
        if description.category is not None:
            self._attr_entity_category = description.category
        if description.decimals is not None:
            self._attr_suggested_display_precision = description.decimals

    def handle_poll(self, values: dict) -> None:
        """Take this sensor's value from a completed poll."""
        value = values.get(self.description.value)
        if value is None:
            return
        if self.description.round_to is not None:
            value = round(value, self.description.round_to)
        self.set_native_value(value)

    def set_native_value(self, new_state) -> None:
        """Set the HA value from the modbus response."""
        if self.currentValue is not None and self.currentValue == new_state:
            # avoid noise...
            return

        # Lifetime energy totals must never go backwards: HA treats a drop as a
        # meter reset and the energy dashboard then shows a huge spike. A drop of
        # more than 1 kWh means the inverter returned bad data, so ignore it.
        if (
            self.description.never_decreases
            and isinstance(new_state, (int, float))
            and isinstance(self.currentValue, (int, float))
            and new_state < self.currentValue - 1.0
        ):
            _LOGGER.warning(
                "Dura-i %s ignored value %s: energy total dropped from %s",
                self.entity_id,
                new_state,
                self.currentValue,
            )
            return

        self.currentValue = new_state
        self._attr_native_value = new_state

        if self.hass is not None:
            self.async_write_ha_state()
