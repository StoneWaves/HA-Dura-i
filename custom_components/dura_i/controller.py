"""Dura-i communication and stats collection."""
import asyncio
import contextlib
import logging
import math
import struct
import time

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DEFAULT_MAX_BATTERY_LOAD_KW,
    DEFAULT_MAX_GRID_LOAD_KW,
    DEFAULT_MAX_LOAD_SPIKE_KW,
    IMPORT_EXPORT_MONITOR_DURATION_SECONDS,
    IMPORT_EXPORT_THRESHOLD,
    INVERTER_POLL_INTERVAL_SECONDS,
    MAX_GRID_EXPORT_POWER_W,
    MODBUS_MAX_SLAVE_ADDRESS,
    NO_AGGREGATION,
    PLATFORMS,
)
from .inverter import Inverter, ModbusHost

_LOGGER = logging.getLogger(__name__)


class Controller:
    """Controller class orchestrating the data fetching and entitities."""

    def __init__(
        self, host: str, port: int, hass: HomeAssistant, entry: ConfigEntry
    ) -> None:
        """Initialise the controller."""
        self.host = host
        self.port = port
        self.hass = hass
        self.config = entry
        self.poller_task = None
        self.have_identity_info = False

        self.sensor_entities = {}
        self.binary_sensor_entities = {}
        self.switch_entities = {}
        self.select_entities = {}
        self.number_entities = {}
        self.binary_sensor_entities = {}
        self._init_count = 0
        self.aggregates = {}
        # Last known-good raw readings per key, used to reject implausible spikes
        # before they are aggregated or summed into totals.
        self.last_good_raw = {}
        # User-configurable sanity-check limits (kW). Defaults from const.py.
        self.max_grid_load_kw = float(DEFAULT_MAX_GRID_LOAD_KW)
        self.max_battery_load_kw = float(DEFAULT_MAX_BATTERY_LOAD_KW)
        self.max_load_spike_kw = float(DEFAULT_MAX_LOAD_SPIKE_KW)
        self.inverters = []
        self.clickhouse_url = ""
        self.clickhouse_is_init = True
        self.aio_http_session = None
        self.match_feed_in_to_excess_power = False
        self.last_feed_in_sync = time.time()
        self.last_feed_in_poll = time.time()
        self.last_excess = -1
        self.current_state_of_charge = -1
        self.excess_target_soc = 90
        self.excess_rate_soc = 0.3
        self.excess_min_feed_in_rate = 0
        self.excess_rapid_change_threshold = 500
        self.excess_slow_change_threshold = 100
        self.excess_slow_change_period_seconds = 600
        self.excess_averaging_period_seconds = 300
        self.excess_max_soc_deviation_kw = float(3)
        self.excess_load_ratio = float(1)
        self.excess_load_entity_id = ""
        self.excess_load_entity_id_multiplier = float(1)
        self.excess_always_account_soc = False

        if "match_feed_in_to_excess_power" in entry.options:
            self.match_feed_in_to_excess_power = bool(
                entry.options["match_feed_in_to_excess_power"]
            )
            _LOGGER.info(
                "Found match feed in to excess power setting of %s",
                entry.options["match_feed_in_to_excess_power"],
            )
        else:
            _LOGGER.info(
                "Defaulting feed in to excess power setting of %s",
                self.match_feed_in_to_excess_power,
            )

        if "excess_target_soc" in entry.options:
            self.excess_target_soc = int(
                entry.options["excess_target_soc"]
            )
            _LOGGER.info(
                "Foundexcess target soc setting of %s",
                entry.options["excess_target_soc"],
            )
        else:
            _LOGGER.info(
                "Defaulting excess target soc setting of %s",
                self.excess_target_soc,
            )

        if "excess_rate_soc" in entry.data:
            self.excess_rate_soc = float(entry.data["excess_rate_soc"]) / 10

        if "excess_min_feed_in_rate" in entry.data:
            self.excess_min_feed_in_rate = int(entry.data["excess_min_feed_in_rate"])

        if "excess_max_soc_deviation_w" in entry.data:
            self.excess_max_soc_deviation_kw = (
                float(entry.data["excess_max_soc_deviation_w"]) / 1000
            )
        if "excess_load_percentage" in entry.data:
            self.excess_load_ratio = float(entry.data["excess_load_percentage"]) / 100

        if (
            "excess_load_entity_id" in entry.data
            and len(str(entry.data["excess_load_entity_id"])) > 5
        ):
            self.excess_load_entity_id = str(entry.data["excess_load_entity_id"])
            if "*" in self.excess_load_entity_id:
                self.excess_load_entity_id_multiplier = float(
                    self.excess_load_entity_id.partition("*")[2]
                )
                self.excess_load_entity_id = self.excess_load_entity_id.partition("*")[
                    0
                ]

                _LOGGER.info(
                    "Found multiplier in excess_load_entity_id, entity is now %s, multiplier is %s",
                    self.excess_load_entity_id,
                    self.excess_load_entity_id_multiplier,
                )

        # Sanity limits may be set via the options flow (entry.data) or live via
        # the number controls (entry.options). Options take precedence.
        if "max_grid_load_kw" in entry.data:
            self.max_grid_load_kw = float(entry.data["max_grid_load_kw"])
        if "max_grid_load_kw" in entry.options:
            self.max_grid_load_kw = float(entry.options["max_grid_load_kw"])

        if "max_battery_load_kw" in entry.data:
            self.max_battery_load_kw = float(entry.data["max_battery_load_kw"])
        if "max_battery_load_kw" in entry.options:
            self.max_battery_load_kw = float(entry.options["max_battery_load_kw"])

        if "max_load_spike_kw" in entry.data:
            self.max_load_spike_kw = float(entry.data["max_load_spike_kw"])
        if "max_load_spike_kw" in entry.options:
            self.max_load_spike_kw = float(entry.options["max_load_spike_kw"])

        _LOGGER.info(
            "Dura-i sanity limits: max grid %skW, max battery %skW, max spike %skW",
            self.max_grid_load_kw,
            self.max_battery_load_kw,
            self.max_load_spike_kw,
        )

        _LOGGER.info("Dura-i controller starting")

    def aggregate(
        self,
        name: str,
        value,
        count: int,
        trimTo=-1,
        always_aggregate=False,
        fetch_only=False,
        insert_only=False,
    ):
        """Stash a value to an aggregate array and return the average."""

        if insert_only is True or fetch_only is False:
            if trimTo == -1:
                trimTo = count

            if name not in self.aggregates:
                self.aggregates[name] = []

            while len(self.aggregates[name]) >= trimTo:
                self.aggregates[name].pop(0)

            self.aggregates[name].append(value)

        if insert_only is True:
            return

        t = 0
        num = 0
        for v in self.aggregates[name]:
            t = t + v
            num = num + 1
            if num == count:
                break

        if NO_AGGREGATION is True and always_aggregate is False:
            return value

        return t / num

    def battery_load_limit_kw(self, inverter: Inverter) -> float:
        """Return the max plausible battery load (kW) for an inverter.

        Uses the inverter's own reported "Battery Discharge Max Power" and
        "Battery Max Charge Power" number entities. Battery load is signed
        (charge vs discharge), and the two limits are asymmetric, so we bound
        the magnitude by whichever is larger to avoid rejecting valid readings
        in either direction. Falls back to the configured limit if those
        entities have not been populated yet.
        """
        candidates = []
        for suffix in ("_battery_max_power", "_battery_max_charge_power"):
            entity = self.number_entities.get(inverter.serial_number + suffix)
            if entity is not None and isinstance(
                getattr(entity, "currentValue", None), (int, float)
            ):
                candidates.append(float(entity.currentValue))

        if not candidates:
            return self.max_battery_load_kw

        # A small headroom factor avoids rejecting readings that momentarily sit
        # right at the configured maximum.
        return max(candidates) * 1.1

    def sane_raw(self, key: str, value, max_abs, max_delta):
        """Sanity check a raw reading before it is aggregated or summed.

        Rejects values outside +/- max_abs, or that jump more than max_delta from
        the last known-good reading, and substitutes the last good value instead.
        This stops a single bad Modbus read from polluting rolling averages and
        multi-inverter totals. Returns the value to use.
        """
        last = self.last_good_raw.get(key)

        if abs(value) > max_abs:
            _LOGGER.warning(
                "Dura-i raw %s value %s exceeds +/-%s, using last good %s",
                key,
                value,
                max_abs,
                last,
            )
            return last if last is not None else 0

        if last is not None and abs(value - last) > max_delta:
            _LOGGER.warning(
                "Dura-i raw %s value %s jumped more than %s from %s, using last good",
                key,
                value,
                max_delta,
                last,
            )
            return last

        self.last_good_raw[key] = value
        return value

    def am_exporting_importing(self, inverter: Inverter, is_import: bool) -> bool:
        """Determine if we're importing or exporting."""
        minCount = math.ceil(
            IMPORT_EXPORT_MONITOR_DURATION_SECONDS / INVERTER_POLL_INTERVAL_SECONDS
        )

        if len(self.aggregates[inverter.serial_number + "_grid_load"]) < minCount:
            return False

        vals = ""

        for v in self.aggregates[inverter.serial_number + "_grid_load"]:
            if len(vals) > 0:
                vals = vals + ","
            vals = vals + str(v)

            if is_import and v <= float(IMPORT_EXPORT_THRESHOLD):
                return False

            if not is_import and v >= float(0) - IMPORT_EXPORT_THRESHOLD:
                return False

        _LOGGER.debug(
            "Import / Export values %s so returning true with is_import as  %s",
            vals,
            str(is_import),
        )

        return True

    async def start_poller(self):
        """Start the async polling of inverter data."""

        async def periodic():
            while True:
                _LOGGER.debug("Polling Inverter Modbus")
                await asyncio.sleep(
                    INVERTER_POLL_INTERVAL_SECONDS
                )  # first because we polled it in await after init.
                await self.poll_inverters()

        task = self.config.async_create_background_task(
            self.hass, periodic(), "Dura-i Inverter Poll"
        )

        self.poller_task = task

    async def poll_inverters(self):
        """Poll all inverters."""
        dura_i_pv_power = float(0)
        dura_i_battery_load = float(0)
        dura_i_grid_load = float(0)
        dura_i_grid_tied_load = float(0)
        dura_i_eps_load = float(0)
        dura_i_inverter_load = float(0)

        work_mode = -1

        for inverter in self.inverters:
            try:
                await inverter.update_software_versions()
                inverter_power_data = await inverter.read_holding_registers(0x1001, 64)
                grid_power_data = await inverter.read_holding_registers(0x1300, 63)
                battery_data = await inverter.read_holding_registers(0x2000, 19)
                inverter_config_data = await inverter.read_holding_registers(0x2100, 64)
                grid_config_data = await inverter.read_holding_registers(0x30B0, 12)
                eps_data = await inverter.read_holding_registers(0x1350, 19)

                # Each block must be present, error-free, and the expected
                # length. Validate them uniformly so a single failed/short read
                # can be named rather than crashing on len(None.registers).
                expected_blocks = {
                    "inverter_power (0x1001)": (inverter_power_data, 64),
                    "grid_power (0x1300)": (grid_power_data, 63),
                    "battery (0x2000)": (battery_data, 19),
                    "inverter_config (0x2100)": (inverter_config_data, 64),
                    "grid_config (0x30B0)": (grid_config_data, 12),
                    "eps (0x1350)": (eps_data, 19),
                }

                failed_block = None
                for name, (data, expected_len) in expected_blocks.items():
                    if (
                        data is None
                        or data.isError()
                        or data.registers is None
                        or len(data.registers) < expected_len
                    ):
                        failed_block = name
                        break

                if failed_block is not None:
                    _LOGGER.warning(
                        "Dura-i Inverter did not provide all results at host %s "
                        "(incomplete read of %s block)",
                        self.host,
                        failed_block,
                    )
                    return

                # if grid and battery totals are zero, smell a mis-report
                if (
                    registers_to_unsigned_32(grid_power_data.registers, 6) == 0
                    and registers_to_unsigned_32(grid_power_data.registers, 8) == 0
                    and registers_to_unsigned_32(battery_data.registers, 13) == 0
                    and registers_to_unsigned_32(battery_data.registers, 17) == 0
                ):
                    _LOGGER.warning(
                        "Dura-i Inverter provided too many zero registers at host %s",
                        self.host,
                    )
                    return

                self.sensor_entities[inverter.serial_number + "_soc"].set_native_value(
                    battery_data.registers[0]
                )

                self.current_state_of_charge = battery_data.registers[0]

                inverter_pv_power = (
                    registers_to_unsigned_32(inverter_power_data.registers, 17)
                    + registers_to_unsigned_32(inverter_power_data.registers, 21)
                ) / 10000

                dura_i_pv_power = dura_i_pv_power + inverter_pv_power

                self.sensor_entities[
                    inverter.serial_number + "_pv_power"
                ].set_native_value(
                    round(
                        inverter_pv_power,
                        1,
                    )
                )

                self.sensor_entities[
                    inverter.serial_number + "_mppt1_power"
                ].set_native_value(
                    registers_to_unsigned_32(inverter_power_data.registers, 17) / 10000
                )

                self.sensor_entities[
                    inverter.serial_number + "_mppt2_power"
                ].set_native_value(
                    registers_to_unsigned_32(inverter_power_data.registers, 21) / 10000
                )

                inverter_battery_load = self.sane_raw(
                    inverter.serial_number + "_battery_load_raw",
                    registers_to_signed_32(battery_data.registers, 9) / 10000,
                    max_abs=self.battery_load_limit_kw(inverter),
                    max_delta=self.max_load_spike_kw,
                )
                dura_i_battery_load = dura_i_battery_load + inverter_battery_load
                self.sensor_entities[
                    inverter.serial_number + "_battery_load"
                ].set_native_value(inverter_battery_load)

                inverter_grid_load = self.sane_raw(
                    inverter.serial_number + "_grid_load_raw",
                    registers_to_signed_32(grid_power_data.registers, 0) / 10000,
                    max_abs=self.max_grid_load_kw,
                    max_delta=self.max_load_spike_kw,
                )
                dura_i_grid_load = dura_i_grid_load + inverter_grid_load
                self.sensor_entities[
                    inverter.serial_number + "_grid_load"
                ].set_native_value(
                    round(
                        self.aggregate(
                            inverter.serial_number + "_grid_load",
                            inverter_grid_load,
                            math.ceil(30 / INVERTER_POLL_INTERVAL_SECONDS),
                            trimTo=math.ceil(
                                IMPORT_EXPORT_MONITOR_DURATION_SECONDS
                                / INVERTER_POLL_INTERVAL_SECONDS
                            )
                            + 1,
                        ),
                        1,
                    )
                )

                inverter_grid_tied_load = (
                    registers_to_signed_32(grid_power_data.registers, 10) / 10000
                )
                dura_i_grid_tied_load = (
                    dura_i_grid_tied_load + inverter_grid_tied_load
                )
                self.sensor_entities[
                    inverter.serial_number + "_grid_tied_load"
                ].set_native_value(inverter_grid_tied_load)

                inverter_eps_load = (
                    registers_to_signed_32(eps_data.registers, 3)
                    + registers_to_signed_32(eps_data.registers, 9)
                    + registers_to_signed_32(eps_data.registers, 14)
                ) / 10000

                dura_i_eps_load = dura_i_eps_load + inverter_eps_load
                self.sensor_entities[
                    inverter.serial_number + "_eps_load"
                ].set_native_value(inverter_eps_load)

                inverter_load = (
                    registers_to_signed_32(inverter_power_data.registers, 2)
                    + registers_to_signed_32(inverter_power_data.registers, 7)
                    + registers_to_signed_32(inverter_power_data.registers, 12)
                ) / 10000
                dura_i_inverter_load = dura_i_inverter_load + inverter_load
                self.sensor_entities[
                    inverter.serial_number + "_inverter_load"
                ].set_native_value(inverter_load)

                self.sensor_entities[
                    inverter.serial_number + "_pv_energy_today"
                ].set_native_value(
                    inverter.shag_pv_energy_today(
                        registers_to_unsigned_32(inverter_power_data.registers, 38)
                        / 1000
                    )
                )

                self.sensor_entities[
                    inverter.serial_number + "_pv_energy_total"
                ].set_native_value(
                    registers_to_unsigned_32(inverter_power_data.registers, 32)
                )

                self.sensor_entities[
                    inverter.serial_number + "_grid_energy_in_total"
                ].set_native_value(
                    registers_to_unsigned_32(grid_power_data.registers, 6) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_grid_energy_out_total"
                ].set_native_value(
                    registers_to_unsigned_32(grid_power_data.registers, 8) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_grid_energy_in_today"
                ].set_native_value(
                    registers_to_unsigned_32(grid_power_data.registers, 50) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_grid_energy_out_today"
                ].set_native_value(
                    registers_to_unsigned_32(grid_power_data.registers, 52) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_battery_energy_in_total"
                ].set_native_value(
                    registers_to_unsigned_32(battery_data.registers, 13) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_battery_energy_out_total"
                ].set_native_value(
                    registers_to_unsigned_32(battery_data.registers, 17) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_battery_energy_in_today"
                ].set_native_value(
                    registers_to_unsigned_32(battery_data.registers, 11) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_battery_energy_out_today"
                ].set_native_value(
                    registers_to_unsigned_32(battery_data.registers, 15) / 100
                )

                self.number_entities[
                    inverter.serial_number + "_battery_max_soc"
                ].set_number_value(inverter_config_data.registers[25])

                self.number_entities[
                    inverter.serial_number + "_grid_max_charge_soc"
                ].set_number_value(inverter_config_data.registers[23])

                self.number_entities[
                    inverter.serial_number + "_grid_max_charge_power"
                ].set_number_value(inverter_config_data.registers[22])

                self.number_entities[
                    inverter.serial_number + "_battery_max_charge_power"
                ].set_number_value(inverter_config_data.registers[24])

                self.number_entities[
                    inverter.serial_number + "_battery_max_power"
                ].set_number_value(inverter_config_data.registers[26])

                self.number_entities[
                    inverter.serial_number + "_grid_max_feed_in_power"
                ].set_number_value(grid_config_data.registers[10])

                work_mode = inverter_config_data.registers[0]

                self.select_entities[
                    inverter.serial_number + "_hybrid_work_mode"
                ].set_selected_option(str(work_mode))

                # Mirror the raw value of every register in the 0x2100 block into
                # its diagnostic sensor. Used to decode the scheduled-charge slots.
                for offset, raw_value in enumerate(inverter_config_data.registers):
                    register_address = 0x2100 + offset
                    sensor = self.sensor_entities.get(
                        inverter.serial_number + f"_config_reg_{register_address:04x}"
                    )
                    if sensor is not None:
                        sensor.set_native_value(raw_value)

                self.switch_entities[
                    inverter.serial_number + "_eps_enabled"
                ].set_selected_option(inverter_config_data.registers[28])

                self.sensor_entities[
                    inverter.serial_number + "_battery_voltage"
                ].set_native_value(battery_data.registers[6] * 0.1)

                self.sensor_entities[
                    inverter.serial_number + "_battery_current"
                ].set_native_value(
                    registers_to_signed_32(battery_data.registers, 7) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_grid_voltage"
                ].set_native_value(grid_power_data.registers[26] / 10)

                self.sensor_entities[
                    inverter.serial_number + "_grid_current"
                ].set_native_value(
                    registers_to_signed_32(grid_power_data.registers, 29) / 100
                )

                self.sensor_entities[
                    inverter.serial_number + "_mppt1_voltage"
                ].set_native_value(inverter_power_data.registers[15] / 10)

                self.sensor_entities[
                    inverter.serial_number + "_mppt1_current"
                ].set_native_value(inverter_power_data.registers[16] / 100)

                self.sensor_entities[
                    inverter.serial_number + "_mppt2_voltage"
                ].set_native_value(inverter_power_data.registers[19] / 10)

                self.sensor_entities[
                    inverter.serial_number + "_mppt2_current"
                ].set_native_value(inverter_power_data.registers[20] / 100)

                self.binary_sensor_entities[
                    inverter.serial_number + "_grid_am_exporting"
                ].set_binary_value(self.am_exporting_importing(inverter, False))

                self.binary_sensor_entities[
                    inverter.serial_number + "_grid_am_importing"
                ].set_binary_value(self.am_exporting_importing(inverter, True))

                self.sensor_entities[
                    inverter.serial_number + "_system_temp"
                ].set_native_value(
                    register_to_signed_16(inverter_power_data.registers[27])
                )

                self.sensor_entities[
                    inverter.serial_number + "_master_software_version"
                ].set_native_value(inverter.master_software_version)

                self.sensor_entities[
                    inverter.serial_number + "_slave_software_version"
                ].set_native_value(inverter.slave_software_version)

                self.sensor_entities[
                    inverter.serial_number + "_ems_software_version"
                ].set_native_value(inverter.ems_software_version)

                self.switch_entities[
                    inverter.serial_number + "_match_feed_in_to_excess_power"
                ].set_selected_option(self.match_feed_in_to_excess_power)

                self.number_entities[
                    inverter.serial_number + "_excess_target_soc"
                ].set_number_value(self.excess_target_soc)

                self.number_entities[
                    inverter.serial_number + "_max_grid_load_kw"
                ].set_number_value(self.max_grid_load_kw)

                self.number_entities[
                    inverter.serial_number + "_max_load_spike_kw"
                ].set_number_value(self.max_load_spike_kw)
            
                # No point in the below as the inverter is always returning zero until this is fixed.
                # self.sensor_entities[
                #    inverter.serial_number + "_battery_temp"
                # ].set_native_value(register_to_signed_16(battery_data.registers[1]))

            except:  # noqa: E722
                _LOGGER.info("Error retrieving inverter stats")

        self.sensor_entities["dura_i_consumer_load"].set_native_value(
            round(
                self.aggregate(
                    "dura_i_consumer_load",
                    dura_i_eps_load + dura_i_grid_tied_load,
                    math.ceil(60 / INVERTER_POLL_INTERVAL_SECONDS),
                ),
                2,
            )
        )

        try:
            if len(self.excess_load_entity_id) > 0:
                self_consumption_load = self.hass.states.get(
                    self.excess_load_entity_id
                ).state

                if self_consumption_load is None:
                    self_consumption_load = dura_i_grid_tied_load
                else:
                    self_consumption_load = (
                        float(self_consumption_load)
                        * self.excess_load_entity_id_multiplier
                    )
            else:
                self_consumption_load = dura_i_grid_tied_load

            dura_i_average_excess_pv_power = self.aggregate(
                "dura_i_average_excess_pv_power",
                dura_i_pv_power
                - ((self_consumption_load + dura_i_eps_load) * self.excess_load_ratio),
                math.ceil(
                    self.excess_averaging_period_seconds
                    / INVERTER_POLL_INTERVAL_SECONDS
                ),
                always_aggregate=True,
            )

            self.sensor_entities["dura_i_average_excess_pv_power"].set_native_value(
                round(
                    dura_i_average_excess_pv_power,
                    2,
                )
            )
        except:  # noqa: E722
            _LOGGER.error("Exception trying to gather excess load")

        _LOGGER.debug(
            "Work mode: %s, match_feed_in_to_excess: %s, last_update: %s",
            work_mode,
            self.match_feed_in_to_excess_power,
            self.last_feed_in_poll,
        )
        if (
            work_mode == 1
            and self.match_feed_in_to_excess_power is True
            and time.time() - self.last_feed_in_poll >= 60
        ):
            with contextlib.suppress(Exception):
                _LOGGER.debug("update_feed_in_excess()")
                await self.update_feed_in_excess()

        if len(self.inverters) > 1:
            self.sensor_entities["dura_i_pv_power"].set_native_value(
                round(
                    self.aggregate(
                        "dura_i_pv_power",
                        dura_i_pv_power,
                        math.ceil(60 / INVERTER_POLL_INTERVAL_SECONDS),
                    ),
                    2,
                )
            )

            self.sensor_entities["dura_i_battery_load"].set_native_value(
                round(dura_i_battery_load, 2)
            )

            self.sensor_entities["dura_i_grid_load"].set_native_value(
                round(dura_i_grid_load, 2)
            )

            self.sensor_entities["dura_i_grid_tied_load"].set_native_value(
                round(dura_i_grid_tied_load, 2)
            )
            self.sensor_entities["dura_i_inverter_load"].set_native_value(
                round(dura_i_inverter_load, 2)
            )

            self.sensor_entities["dura_i_eps_load"].set_native_value(
                round(dura_i_eps_load, 2)
            )

        await self.record_stats_to_clickhouse()

    async def set_feed_in_excess(self, setting: bool):
        """Update the feed in excess setting."""
        self.match_feed_in_to_excess_power = setting

        options = {"match_feed_in_to_excess_power": self.match_feed_in_to_excess_power, "excess_target_soc": self.excess_target_soc }

        self.hass.config_entries.async_update_entry(self.config, options=options)

    async def set_excess_target_soc(self, setting: int):
        """Update the excess target soc."""
        self.excess_target_soc = setting

        options = {"match_feed_in_to_excess_power": self.match_feed_in_to_excess_power, "excess_target_soc": self.excess_target_soc }

        self.hass.config_entries.async_update_entry(self.config, options=options)

    def _persist_option(self, key: str, value):
        """Persist a single option without clobbering the others."""
        options = dict(self.config.options)
        options[key] = value
        self.hass.config_entries.async_update_entry(self.config, options=options)

    async def set_max_grid_load_kw(self, setting: float):
        """Update the max plausible grid load limit (kW)."""
        self.max_grid_load_kw = float(setting)
        _LOGGER.info("Max grid load sanity limit set to %skW", self.max_grid_load_kw)
        self._persist_option("max_grid_load_kw", self.max_grid_load_kw)

    async def set_max_load_spike_kw(self, setting: float):
        """Update the max allowed load change between polls (kW)."""
        self.max_load_spike_kw = float(setting)
        _LOGGER.info("Max load spike sanity limit set to %skW", self.max_load_spike_kw)
        self._persist_option("max_load_spike_kw", self.max_load_spike_kw)

    async def update_feed_in_excess(self):
        """Set the feed in power to the recent average."""
        self.last_feed_in_poll = time.time()
        if self.match_feed_in_to_excess_power is False:
            return

        to_value = self.aggregate(
            "dura_i_average_excess_pv_power",
            0,
            0,
            fetch_only=True,
            always_aggregate=True,
        )

        if self.excess_always_account_soc is True or to_value > 0:  # only account for SoC if we actually have excess solar.
            if self.excess_target_soc > 0:
                soc_variance = (
                    float(self.current_state_of_charge - self.excess_target_soc)
                    * self.excess_rate_soc
                )
            else:
                soc_variance = 0

            if soc_variance > self.excess_max_soc_deviation_kw:
                _LOGGER.info(
                    "Excess SoC variance would be %skW so limiting to %skW",
                    soc_variance,
                    self.excess_max_soc_deviation_kw,
                )
                soc_variance = self.excess_max_soc_deviation_kw
            elif soc_variance < 0 - self.excess_max_soc_deviation_kw:
                _LOGGER.info(
                    "Excess SoC variance would be %skW so limiting to %skW",
                    soc_variance,
                    0 - self.excess_max_soc_deviation_kw,
                )
                soc_variance = 0 - self.excess_max_soc_deviation_kw
            else:
                _LOGGER.info("Excess SoC variance is %skW", soc_variance)

            to_value = (
                to_value + soc_variance
            )  # affect the value based around the current Soc, targeting 90% battery with a shift of 3kW per 10 percent.

        _LOGGER.info(
            "Synchronising feed in to average of solar power: %skW and balancing to %s pc SoC with rate of %s per pc",
            to_value,
            self.excess_target_soc,
            self.excess_rate_soc,
        )

        if to_value > MAX_GRID_EXPORT_POWER_W / 1000:
            to_value = MAX_GRID_EXPORT_POWER_W / 1000
            _LOGGER.info("Limited export to the limit of %skW", to_value)

        to_value = (to_value * 1000) / len(self.inverters)
        to_value = int(max(to_value, self.excess_min_feed_in_rate))

        if self.last_excess >= 0:
            change = int(to_value) - self.last_excess
            if change == 0:
                _LOGGER.info("No change")
                return

            if (
                (0 - self.excess_slow_change_threshold)
                < change
                < self.excess_slow_change_threshold
            ) and int(to_value) > self.excess_min_feed_in_rate:
                _LOGGER.info("Change of %sW per inverter  is not enough", change)
                return

            if (
                (
                    (0 - self.excess_rapid_change_threshold)
                    < change
                    < self.excess_rapid_change_threshold
                )
                and time.time() - self.last_feed_in_sync
                < self.excess_slow_change_period_seconds
            ):
                _LOGGER.info(
                    "Change of %sW per inverter is not enough for fast update", change
                )
                return

        to_value = int(math.ceil(float(to_value) / 50.0)) * 50

        self.last_excess = to_value
        self.last_feed_in_sync = time.time()

        _LOGGER.info(
            "Setting feed in to %sW",
            to_value,
        )

        await self.set_register(self.inverters[0], 0x30BA, int(to_value), no_poll=True)

    async def record_stats_to_clickhouse(self):
        """Record all our sensors to a clickhouse database if configured."""
        if self.clickhouse_url is None or len(self.clickhouse_url) < 5:
            return

        if self.clickhouse_is_init is True:
            self.aio_http_session = async_get_clientsession(self.hass)
            await self.clickhouse_exec(
                "create table if not exists dura_i_stats ( at_utc DateTime ) ENGINE = MergeTree PARTITION BY toYYYYMM(at_utc) ORDER BY at_utc;"
            )

        create = ""

        columns = ""
        values = ""

        for k in self.sensor_entities:
            e: SensorEntity = self.sensor_entities[k]

            if self.clickhouse_is_init is True:
                if create == "":
                    create = (
                        create
                        + "alter table dura_i_stats add column if not exists "
                        + k.replace("-", "_")
                        + " Float64"
                    )
                else:
                    create = (
                        create
                        + ", add column if not exists "
                        + k.replace("-", "_")
                        + " Float64"
                    )

            if columns == "":
                columns = k.replace("-", "_")
                values = str(e.native_value)
            else:
                columns = columns + "," + k.replace("-", "_")
                values = values + "," + str(e.native_value)

        if self.clickhouse_is_init is True:
            await self.clickhouse_exec(create + ";")
            self.clickhouse_is_init = False

        await self.clickhouse_exec(
            "insert into dura_i_stats ( at_utc,"  # noqa: S608
            + columns
            + ") values ( toDateTime(now(), 'UTC'),"
            + values
            + ");"
        )

    async def clickhouse_exec(self, cmd: str):
        """Execute a statement to the clikchouse database."""
        try:
            x = await self.aio_http_session.post(self.clickhouse_url, data=cmd)

            if x.status != 200:
                _LOGGER.error("Clickhouse command failed: %s", cmd)
        except:  # noqa: E722
            _LOGGER.error("Clickhouse command failed: %s", cmd)

    async def set_register(
        self, inverter: Inverter, register: int, value: int, no_poll=False
    ):
        """Set a modbus register from a change in HA."""
        try:
            await inverter.write_register(register, value)
        except:  # noqa: E722
            _LOGGER.info("Pymodbus still raising errors on register writes")
        if no_poll is False:
            await self.poll_inverters()

    async def update_ha_state(self):
        """Schedule an update for all other included entities."""

    async def get_identity_info(self):
        """Obtain the serial number, model etc."""
        hosts = self.host.replace(" ", "").split(sep=",")
        for host in hosts:
            _LOGGER.info("Scanning for slaves on modbus host %s", host)
            port = self.port
            if ":" in host:
                port = int(host.split(sep=":")[1])
                host = host.split(sep=":")[0]

            modbus = ModbusHost(host=host, port=port)
            detect_loops = 5  # We want to detect at least one slave on each specified modbus adapter, so retry if we don't

            while detect_loops > 0:
                detect_loops = detect_loops - 1
                for slave in range(1, MODBUS_MAX_SLAVE_ADDRESS + 1):
                    try:
                        _LOGGER.info("Attempting to query slave %s", str(slave))
                        modelResponse = await modbus.read_holding_registers(
                            0x1A00, 8, slave_address=slave
                        )

                        _LOGGER.info("Query complete, querying serial")

                        if modelResponse.isError():
                            _LOGGER.info(
                                "Stopped scanning for modbus slaves at slave %s",
                                str(slave),
                            )
                            break

                        serialResponse = await modbus.read_holding_registers(
                            0x1A10, 8, slave_address=slave
                        )

                        _LOGGER.info("Query complete")

                        inverter = Inverter(
                            serial_number=registers_to_string(
                                serialResponse.registers, 0, 8
                            ),
                            model_number=registers_to_string(
                                modelResponse.registers, 0, 8
                            ),
                            slave_address=slave,
                            host=modbus,
                        )

                        _LOGGER.info("Created inverter")

                        _LOGGER.info(
                            "Dura-i Model Number is %s", inverter.model_number
                        )
                        _LOGGER.info(
                            "Dura-i Serial Number is %s", inverter.serial_number
                        )

                        await inverter.update_software_versions()

                        detect_loops = 0
                        self.inverters.append(inverter)
                        self.have_identity_info = True
                    except:  # noqa: E722
                        _LOGGER.exception("Exception while scanning")
                        _LOGGER.info(
                            "Stopped scanning with exception for modbus host %s at slave %s",
                            host,
                            str(slave),
                        )
                        if detect_loops <= 0:
                            break

    def __del__(self):
        """Log deletion."""
        _LOGGER.debug("Controller deleted")
        self.terminate()

    def terminate(self):
        """End the controller."""
        if self.poller_task is not None:
            self.poller_task.cancel()
            self.poller_task = None
            _LOGGER.info("Dura-i is no longer polling")

    async def initialise(self):
        """Self intialisation."""
        await self.get_identity_info()

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

    def get_binary_sensor_entities(self):
        """Get binary sensor entities."""

        return list(self.binary_sensor_entities.values())

    async def setup_done(self, name):
        """Entities setup is done."""
        self._init_count = self._init_count + 1
        _LOGGER.debug("Entities %s setup done", name)
        if self._init_count >= len(PLATFORMS):
            await self.poll_inverters()
            await self.start_poller()


def registers_to_string(registers, start: int, length: int):
    """Convert a section of registers into a string."""
    data = ""
    i = 0
    while i < length:
        x = registers[start + i]
        c = (x >> 8) & 0xFF
        f = x & 0xFF

        if c > 0:
            data = data + chr(c)

        if f > 0:
            data = data + chr(f)

        i = i + 1

    return data.strip()


def registers_to_signed_32(registers, pos):
    """Convert a section of registers into a signed 32."""
    regs = [registers[pos], registers[pos + 1]]
    b = struct.pack(">2H", *regs)
    return struct.unpack(">l", b)[0]


def register_to_signed_16(register):
    """Convert a section of registers into a signed 16."""
    b = struct.pack(">H", register)
    return struct.unpack(">h", b)[0]


def registers_to_unsigned_32(registers, pos):
    """Convert a section of registers into a unsigned 32."""
    regs = [registers[pos], registers[pos + 1]]
    b = struct.pack(">2H", *regs)
    return struct.unpack(">L", b)[0]
