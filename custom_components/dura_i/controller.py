"""Dura-i communication and stats collection."""

from __future__ import annotations

import asyncio
from collections import deque
from itertools import chain
import logging
import math

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    IMPORT_EXPORT_MONITOR_DURATION_SECONDS,
    IMPORT_EXPORT_THRESHOLD,
    INVERTER_POLL_INTERVAL_SECONDS,
    MODBUS_MAX_SLAVE_ADDRESS,
    PLATFORMS,
)
from .inverter import Inverter, InverterReadError, ModbusHost
from .registers import decode_all, registers_to_string

_LOGGER = logging.getLogger(__name__)

IDENTITY_ATTEMPTS = 5
IDENTITY_RETRY_DELAY_SECONDS = 2

# Grid load samples kept to decide whether we're steadily importing/exporting.
GRID_HISTORY_MIN = math.ceil(
    IMPORT_EXPORT_MONITOR_DURATION_SECONDS / INVERTER_POLL_INTERVAL_SECONDS
)

# Per-inverter values that are summed into the system-wide "Dura-i ..." sensors.
SUMMED_KEYS = (
    "pv_power",
    "battery_load",
    "grid_load",
    "grid_tied_load",
    "eps_load",
    "inverter_load",
)

# Lifetime counters that should never all read zero on a working inverter.
LIFETIME_COUNTERS = (
    "grid_energy_in_total",
    "grid_energy_out_total",
    "battery_energy_in_total",
    "battery_energy_out_total",
)


class Controller:
    """Finds the inverters, polls them and pushes values to the entities."""

    def __init__(
        self, host: str, port: int, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Initialise the controller."""
        self.host = host
        self.port = port
        self.hass = hass
        self.config = entry
        self.poller_task = None

        self.sensor_entities = {}
        self.binary_sensor_entities = {}
        self.switch_entities = {}
        self.select_entities = {}
        self.number_entities = {}
        self.time_entities = {}
        self._init_count = 0

        self.inverters: list[Inverter] = []
        self.modbus_hosts: list[ModbusHost] = []

        # Serialises whole polls and writes, so a write from HA and the
        # follow-up poll can't overlap the background poll.
        self._poll_lock = asyncio.Lock()
        self._grid_history: dict[str, deque] = {}
        # Each inverter's decoded values from its last successful poll, for
        # features that need settings even when their entities are disabled.
        self.last_values: dict[str, dict] = {}
        # Serial numbers of inverters whose last poll failed (for log throttling).
        self._failing: set[str] = set()

    # ------------------------------------------------------------------
    # Polling
    # ------------------------------------------------------------------

    async def start_poller(self):
        """Start the async polling of inverter data."""

        async def periodic():
            while True:
                # Sleep first: setup_done() has just polled.
                await asyncio.sleep(INVERTER_POLL_INTERVAL_SECONDS)
                await self.poll_inverters()

        self.poller_task = self.config.async_create_background_task(
            self.hass, periodic(), "Dura-i Inverter Poll"
        )

    async def poll_inverters(self):
        """Poll all inverters and update every entity."""
        async with self._poll_lock:
            await self._poll_inverters()

    async def _poll_inverters(self):
        totals = dict.fromkeys(SUMMED_KEYS, 0.0)
        all_ok = True

        for inverter in self.inverters:
            values = await self._read_inverter(inverter)
            if values is None:
                all_ok = False
                continue

            try:
                self._publish(inverter, values)
            except Exception:
                self._log_failure(
                    inverter, "unexpected error updating entities", exc_info=True
                )
                all_ok = False
                continue

            self._log_recovery(inverter)
            for key in SUMMED_KEYS:
                totals[key] += values[key]

        # A partial sum would look like a sudden drop, so skip the
        # system-wide sensors unless every inverter answered.
        if not all_ok or not self.inverters:
            return

        totals["consumer_load"] = totals["eps_load"] + totals["grid_tied_load"]
        for entity in self.sensor_entities.values():
            if entity.inverter is None:
                entity.handle_poll(totals)

    async def _read_inverter(self, inverter: Inverter) -> dict | None:
        """Read and decode one inverter. Returns None (and logs) on failure."""
        try:
            await inverter.update_software_versions()
            blocks = await inverter.read_blocks()
        except InverterReadError as err:
            self._log_failure(inverter, str(err))
            return None
        except Exception:
            self._log_failure(inverter, "unexpected error reading", exc_info=True)
            return None

        values = decode_all(blocks)

        if all(values[key] == 0 for key in LIFETIME_COUNTERS):
            self._log_failure(inverter, "all lifetime energy counters read zero")
            return None

        # Values built from several registers.
        values["pv_power"] = round(values["mppt1_power"] + values["mppt2_power"], 6)
        values["inverter_load"] = round(
            values["inverter_load_l1"]
            + values["inverter_load_l2"]
            + values["inverter_load_l3"],
            6,
        )
        values["eps_load"] = round(
            values["eps_load_l1"] + values["eps_load_l2"] + values["eps_load_l3"], 6
        )
        values["pv_energy_today"] = inverter.shag_pv_energy_today(
            values["pv_energy_today"]
        )
        values["master_software_version"] = inverter.master_software_version
        values["slave_software_version"] = inverter.slave_software_version
        values["ems_software_version"] = inverter.ems_software_version

        return values

    def _publish(self, inverter: Inverter, values: dict) -> None:
        """Push one inverter's decoded values to its entities."""
        history = self._grid_history.setdefault(
            inverter.serial_number, deque(maxlen=GRID_HISTORY_MIN + 1)
        )
        history.append(values["grid_load"])
        self.last_values[inverter.serial_number] = values

        for entity in chain(
            self.sensor_entities.values(),
            self.number_entities.values(),
            self.select_entities.values(),
            self.switch_entities.values(),
            self.time_entities.values(),
            self.binary_sensor_entities.values(),
        ):
            if entity.inverter is inverter:
                entity.handle_poll(values)

    def am_exporting_importing(self, inverter: Inverter, is_import: bool) -> bool:
        """Return True if grid load has stayed past the threshold for the whole window."""
        history = self._grid_history.get(inverter.serial_number, ())
        if len(history) < GRID_HISTORY_MIN:
            return False
        if is_import:
            return all(v > IMPORT_EXPORT_THRESHOLD for v in history)
        return all(v < -IMPORT_EXPORT_THRESHOLD for v in history)

    def _log_failure(self, inverter: Inverter, reason: str, exc_info=False) -> None:
        """Log a failed poll loudly once, then quietly until it recovers."""
        if inverter.serial_number in self._failing:
            _LOGGER.debug(
                "Dura-i inverter %s still failing: %s",
                inverter.serial_number,
                reason,
                exc_info=exc_info,
            )
            return

        self._failing.add(inverter.serial_number)
        _LOGGER.warning(
            "Dura-i inverter %s at %s: %s. Keeping its last values and retrying "
            "every %ss; repeats are logged at debug level until it recovers",
            inverter.serial_number,
            self.host,
            reason,
            INVERTER_POLL_INTERVAL_SECONDS,
            exc_info=exc_info,
        )

    def _log_recovery(self, inverter: Inverter) -> None:
        if inverter.serial_number in self._failing:
            self._failing.discard(inverter.serial_number)
            _LOGGER.info("Dura-i inverter %s is responding again", inverter.serial_number)

    # ------------------------------------------------------------------
    # Writing
    # ------------------------------------------------------------------

    async def set_register(self, inverter: Inverter, register: int, value: int):
        """Write a register from a change in HA, then refresh the entities."""
        async with self._poll_lock:
            await inverter.write_register(register, value)
        await self.poll_inverters()

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    async def initialise(self):
        """Find the inverters on every configured Modbus host."""
        for host in self.host.replace(" ", "").split(","):
            port = self.port
            if ":" in host:
                host, port_text = host.split(":", 1)
                port = int(port_text)

            modbus = ModbusHost(host=host, port=port)
            self.modbus_hosts.append(modbus)

            for attempt in range(1, IDENTITY_ATTEMPTS + 1):
                if await self._scan_host(modbus):
                    break
                _LOGGER.debug(
                    "No inverter found on %s:%s (attempt %s of %s)",
                    host,
                    port,
                    attempt,
                    IDENTITY_ATTEMPTS,
                )
                await asyncio.sleep(IDENTITY_RETRY_DELAY_SECONDS)
            else:
                _LOGGER.warning("No Dura-i inverter answered on %s:%s", host, port)

    async def _scan_host(self, modbus: ModbusHost) -> bool:
        """Look for inverters on one Modbus host. Returns True if any were found."""
        found = False
        for slave in range(1, MODBUS_MAX_SLAVE_ADDRESS + 1):
            model = await modbus.read_holding_registers(0x1A00, 8, slave_address=slave)
            if model is None:
                break
            serial = await modbus.read_holding_registers(0x1A10, 8, slave_address=slave)
            if serial is None:
                break

            inverter = Inverter(
                serial_number=registers_to_string(serial.registers),
                model_number=registers_to_string(model.registers),
                slave_address=slave,
                host=modbus,
            )
            await inverter.update_software_versions()
            _LOGGER.info(
                "Found Dura-i inverter %s (model %s) at %s, slave %s",
                inverter.serial_number,
                inverter.model_number,
                modbus.host,
                slave,
            )
            self.inverters.append(inverter)
            found = True
        return found

    def terminate(self):
        """Stop polling and close every Modbus connection."""
        if self.poller_task is not None:
            self.poller_task.cancel()
            self.poller_task = None
            _LOGGER.info("Dura-i is no longer polling")

        for modbus in self.modbus_hosts:
            modbus.close()
        self.modbus_hosts.clear()

    # ------------------------------------------------------------------
    # Platform setup
    # ------------------------------------------------------------------

    def get_sensor_entities(self):
        """Get sensor entities."""
        return list(self.sensor_entities.values())

    def get_switch_entities(self):
        """Get switch entities."""
        return list(self.switch_entities.values())

    def get_select_entities(self):
        """Get select entities."""
        return list(self.select_entities.values())

    def get_number_entities(self):
        """Get number entities."""
        return list(self.number_entities.values())

    def get_time_entities(self):
        """Get time entities."""
        return list(self.time_entities.values())

    def get_binary_sensor_entities(self):
        """Get binary sensor entities."""
        return list(self.binary_sensor_entities.values())

    async def setup_done(self, name):
        """Start polling once every platform has added its entities."""
        self._init_count = self._init_count + 1
        _LOGGER.debug("Entities %s setup done", name)
        if self._init_count >= len(PLATFORMS):
            await self.poll_inverters()
            await self.start_poller()
