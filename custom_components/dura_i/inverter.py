"""Dura-i inverter modules."""

import asyncio
from datetime import datetime, timedelta
import logging
import time

from pymodbus import FramerType
from pymodbus.client import AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, INVERTER_POLL_INTERVAL_SECONDS
from .registers import BLOCKS, registers_to_string

_LOGGER = logging.getLogger(__name__)

# Firmware version strings: (attribute, start register, register count).
VERSION_REGISTERS = (
    ("master_software_version", 0x1A1C, 3),
    ("slave_software_version", 0x1A26, 3),
    ("ems_software_version", 0x1A60, 3),
)
VERSION_POLL_INTERVAL_SECONDS = 7200


class InverterReadError(Exception):
    """A register block could not be read completely."""


class ModbusHost:
    """One Modbus TCP endpoint (e.g. a TCP-RS485 adapter).

    Every request goes through a lock, so polls and writes from Home Assistant
    never interleave on the same connection.
    """

    def __init__(self, host: str, port: int) -> None:
        """Modbus intitialiser."""
        self.host = host
        self.port = port
        self.client = AsyncModbusTcpClient(
            host=self.host, port=self.port, framer=FramerType.SOCKET
        )
        self._lock = asyncio.Lock()

    async def _ensure_connected(self) -> bool:
        if not self.client.connected:
            await self.client.connect()
        if not self.client.connected:
            _LOGGER.debug("Could not connect to Modbus host %s:%s", self.host, self.port)
            return False
        return True

    async def read_holding_registers(self, start_address, num_registers, slave_address):
        """Read registers from an inverter. Returns None on failure."""
        async with self._lock:
            if not await self._ensure_connected():
                return None
            try:
                response = await self.client.read_holding_registers(
                    address=start_address, count=num_registers, device_id=slave_address
                )
            except (ModbusException, OSError) as err:
                _LOGGER.debug(
                    "Reading %s registers from 0x%04X on %s failed: %s",
                    num_registers,
                    start_address,
                    self.host,
                    err,
                )
                return None

        if response.isError():
            _LOGGER.debug(
                "Inverter returned an error reading 0x%04X: %s", start_address, response
            )
            return None
        return response

    async def write_register(self, register, value, slave_address) -> bool:
        """Write one register. Returns True if the inverter accepted it."""
        async with self._lock:
            if not await self._ensure_connected():
                return False
            try:
                response = await self.client.write_register(
                    address=register, value=value, device_id=slave_address
                )
            except (ModbusException, OSError) as err:
                _LOGGER.warning(
                    "Writing %s to register 0x%04X on %s failed: %s",
                    value,
                    register,
                    self.host,
                    err,
                )
                return False

        if response.isError():
            _LOGGER.warning(
                "Inverter rejected writing %s to register 0x%04X: %s",
                value,
                register,
                response,
            )
            return False
        return True

    def close(self) -> None:
        """Close the TCP connection so the adapter isn't left holding it open."""
        self.client.close()


class Inverter:
    """An individual inverter."""

    def __init__(
        self,
        serial_number: str,
        model_number: str,
        slave_address: int,
        host: ModbusHost,
    ) -> None:
        """Inverter intialiser."""
        self.serial_number = serial_number
        self._slave_address = slave_address
        self.model_number = model_number
        self._host = host
        self._written_registers = {}
        self.previous_pv_energy_today = float(0)
        self.pv_energy_today_offset = float(0)
        self.master_software_version = ""
        self.slave_software_version = ""
        self.ems_software_version = ""
        self.last_version_poll = None

        self.device_info = DeviceInfo(
            identifiers={(DOMAIN, self.serial_number)},
            name="Dura-i " + self.serial_number,
            manufacturer="Duracell",
            model=self.model_number,
        )

    def shag_pv_energy_today(self, pv_energy_today: float):
        """Shag a PV energy today from offset because the inverter resets incorrectly."""
        if self.previous_pv_energy_today > pv_energy_today and pv_energy_today < 1:
            self.pv_energy_today_offset = pv_energy_today
            _LOGGER.debug("Setting PV energy offset to %s", self.pv_energy_today_offset)

        self.previous_pv_energy_today = pv_energy_today
        return pv_energy_today - self.pv_energy_today_offset

    async def update_software_versions(self):
        """Refresh firmware version strings, at most every couple of hours."""
        if (
            self.last_version_poll is not None
            and time.time() - self.last_version_poll < VERSION_POLL_INTERVAL_SECONDS
        ):
            return
        self.last_version_poll = time.time()

        # Read each one separately so one unreadable version doesn't hide the rest.
        for attribute, address, count in VERSION_REGISTERS:
            response = await self.read_holding_registers(address, count)
            if response is None:
                _LOGGER.debug(
                    "Could not read %s from 0x%04X on inverter %s",
                    attribute,
                    address,
                    self.serial_number,
                )
                continue
            setattr(self, attribute, registers_to_string(response.registers))

        _LOGGER.debug(
            "Inverter %s versions are Master: %s, Slave: %s, EMS: %s",
            self.serial_number,
            self.master_software_version,
            self.slave_software_version,
            self.ems_software_version,
        )

    async def read_blocks(self) -> dict[str, list[int]]:
        """Read every register block in ``BLOCKS``.

        Raises InverterReadError naming the first block that failed or came
        back short, so a poll is never decoded from partial data.
        """
        blocks = {}
        for block in BLOCKS:
            response = await self.read_holding_registers(block.start, block.count)
            if response is None or len(response.registers) < block.count:
                raise InverterReadError(
                    f"incomplete read of {block.name} block (0x{block.start:04X})"
                )
            blocks[block.name] = response.registers
        return blocks

    async def write_register(self, register, value) -> bool:
        """Write a register and remember it so it can be re-sent if it doesn't stick."""
        _LOGGER.info(
            "Inverter %s: writing %s to register 0x%04X",
            self.serial_number,
            value,
            register,
        )
        self._written_registers[register] = {
            "value": value,
            "attempts_left": 10,
            "from": datetime.now()
            + timedelta(seconds=INVERTER_POLL_INTERVAL_SECONDS - 1),
        }
        return await self._host.write_register(
            register=register, value=value, slave_address=self._slave_address
        )

    async def read_holding_registers(self, start_address, num_registers):
        """Read registers, re-sending any recent write that the inverter dropped."""
        response = await self._host.read_holding_registers(
            start_address, num_registers, slave_address=self._slave_address
        )
        if response is None or not response.registers:
            return None

        for register_num, register in enumerate(response.registers, start_address):
            pending = self._written_registers.get(register_num)
            if pending is None or pending["from"] > datetime.now():
                continue

            if pending["value"] == register:
                self._written_registers.pop(register_num, None)
                continue

            pending["attempts_left"] -= 1
            if pending["attempts_left"] <= 0:
                _LOGGER.warning(
                    "Inverter %s: register 0x%04X still reads %s instead of %s; giving up",
                    self.serial_number,
                    register_num,
                    register,
                    pending["value"],
                )
                self._written_registers.pop(register_num, None)
                continue

            _LOGGER.info(
                "Inverter %s: register 0x%04X reads %s instead of %s; re-sending "
                "(%s attempts left)",
                self.serial_number,
                register_num,
                register,
                pending["value"],
                pending["attempts_left"],
            )
            await self._host.write_register(
                register=register_num,
                value=pending["value"],
                slave_address=self._slave_address,
            )

        return response
