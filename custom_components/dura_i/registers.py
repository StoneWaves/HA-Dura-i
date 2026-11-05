"""Modbus register map for the Dura-i.

This is the single place that knows where values live on the inverter.

* ``BLOCKS`` are the contiguous ranges read on every poll, one Modbus request
  each.
* ``REGISTERS`` names every register we decode. Each one must fall inside one
  of the blocks.

To make a new register available, add it to ``REGISTERS`` (growing a block if
needed); the poll decodes it automatically and its value appears under its
name. To show it in Home Assistant, add an entity for that name in the matching
platform file (sensor.py, number.py, ...).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from enum import Enum


class DataType(Enum):
    """How a register's raw 16-bit words are interpreted."""

    U16 = "u16"
    S16 = "s16"
    U32 = "u32"  # two words, high word first
    S32 = "s32"  # two words, high word first
    TIME = "time"  # hour in the high byte, minute in the low byte


@dataclass(frozen=True)
class Block:
    """A contiguous range of holding registers read in one request."""

    name: str
    start: int
    count: int

    def contains(self, address: int, words: int) -> bool:
        """Return True if ``words`` registers from ``address`` fit in the block."""
        return self.start <= address and address + words <= self.start + self.count


@dataclass(frozen=True)
class Register:
    """A single named value on the inverter."""

    address: int
    data_type: DataType = DataType.U16
    scale: float = 1

    @property
    def words(self) -> int:
        """Number of 16-bit registers this value occupies."""
        return 2 if self.data_type in (DataType.U32, DataType.S32) else 1


BLOCKS: tuple[Block, ...] = (
    Block("inverter_power", 0x1001, 64),
    Block("grid_power", 0x1300, 63),
    Block("eps", 0x1350, 19),
    Block("battery", 0x2000, 19),
    Block("inverter_config", 0x2100, 58),  # 0x2100-0x2139; 0x212E needs at least 47
    Block("grid_config", 0x30B0, 12),
)

# Power registers are in units of 0.1 W; scaling by 0.0001 gives kW.
KW = 0.0001

REGISTERS: dict[str, Register] = {
    # --- Inverter and PV (0x1001 block) ---
    "inverter_load_l1": Register(0x1003, DataType.S32, KW),
    "inverter_load_l2": Register(0x1008, DataType.S32, KW),
    "inverter_load_l3": Register(0x100D, DataType.S32, KW),
    "mppt1_voltage": Register(0x1010, DataType.U16, 0.1),
    "mppt1_current": Register(0x1011, DataType.U16, 0.01),
    "mppt1_power": Register(0x1012, DataType.U32, KW),
    "mppt2_voltage": Register(0x1014, DataType.U16, 0.1),
    "mppt2_current": Register(0x1015, DataType.U16, 0.01),
    "mppt2_power": Register(0x1016, DataType.U32, KW),
    "system_temp": Register(0x101C, DataType.S16),
    "pv_energy_total": Register(0x1021, DataType.U32),  # kWh
    "pv_energy_today": Register(0x1027, DataType.U32, 0.001),  # Wh -> kWh
    # --- Grid (0x1300 block) --- grid_load: + import, - export (confirmed)
    "grid_load": Register(0x1300, DataType.S32, KW),
    "grid_energy_in_total": Register(0x1306, DataType.U32, 0.01),
    "grid_energy_out_total": Register(0x1308, DataType.U32, 0.01),
    "grid_tied_load": Register(0x130A, DataType.S32, KW),
    "grid_voltage": Register(0x131A, DataType.U16, 0.1),
    "grid_current": Register(0x131D, DataType.S32, 0.01),
    "grid_energy_in_today": Register(0x1332, DataType.U32, 0.01),
    "grid_energy_out_today": Register(0x1334, DataType.U32, 0.01),
    # --- EPS / backup output (0x1350 block) ---
    "eps_load_l1": Register(0x1353, DataType.S32, KW),
    "eps_load_l2": Register(0x1359, DataType.S32, KW),
    "eps_load_l3": Register(0x135E, DataType.S32, KW),
    # --- Battery (0x2000 block) --- battery_load and battery_current: - charging, + discharging (confirmed)
    "soc": Register(0x2000),
    "battery_temp": Register(0x2001, DataType.S16),  # reads 0 on Dura-i firmware
    "battery_voltage": Register(0x2006, DataType.U16, 0.1),
    "battery_current": Register(0x2007, DataType.S32, 0.01),
    "battery_load": Register(0x2009, DataType.S32, KW),
    "battery_energy_in_today": Register(0x200B, DataType.U32, 0.01),
    "battery_energy_in_total": Register(0x200D, DataType.U32, 0.01),
    "battery_energy_out_today": Register(0x200F, DataType.U32, 0.01),
    "battery_energy_out_total": Register(0x2011, DataType.U32, 0.01),
    # --- Inverter settings (0x2100 block, writable) ---
    "hybrid_work_mode": Register(0x2100),
    "charge_window_1_start": Register(0x2102, DataType.TIME),
    "charge_window_1_end": Register(0x2103, DataType.TIME),
    "grid_max_charge_power": Register(0x2116),  # W
    "grid_max_charge_soc": Register(0x2117),  # %, max SoC when charging from grid (confirmed)
    "battery_max_charge_power": Register(0x2118),  # W
    "battery_max_soc": Register(0x2119),  # %, max SoC when charging from solar (confirmed)
    "battery_max_power": Register(0x211A),  # W
    "eps_enabled": Register(0x211C),  # 1 = on, 0 = off
    # 0 = auto, 1 = force charge, 2 = force discharge (from the Solis map; unconfirmed)
    "force_charge": Register(0x212E),
    # 0x2139 (8505): Solis map says "grid charge end SoC", but it reads 100 while
    # grid_max_charge_soc (0x2117) holds the real setting of 85. Meaning unknown.
    "unidentified_2139": Register(0x2139),
    # --- Grid settings (0x30B0 block, writable) ---
    "grid_max_feed_in_power": Register(0x30BA),  # W
}


def _block_for(register: Register) -> Block:
    for block in BLOCKS:
        if block.contains(register.address, register.words):
            return block
    raise ValueError(f"Register 0x{register.address:04X} is not inside any polled block")


# Fail at import time, not on the first poll, if a register is misplaced.
REGISTER_BLOCKS: dict[str, Block] = {
    name: _block_for(register) for name, register in REGISTERS.items()
}


def decode(name: str, blocks: dict[str, list[int]]):
    """Decode a named register from the raw words of a completed poll."""
    register = REGISTERS[name]
    block = REGISTER_BLOCKS[name]
    words = blocks[block.name]
    offset = register.address - block.start

    if register.data_type is DataType.TIME:
        word = words[offset]
        return time(hour=(word >> 8) & 0xFF, minute=word & 0xFF)

    if register.words == 2:
        raw = (words[offset] << 16) | words[offset + 1]
        if register.data_type is DataType.S32 and raw & 0x8000_0000:
            raw -= 0x1_0000_0000
    else:
        raw = words[offset]
        if register.data_type is DataType.S16 and raw & 0x8000:
            raw -= 0x1_0000

    if register.scale == 1:
        return raw
    # Round away float noise (e.g. 513 * 0.1 = 51.300000000000004).
    return round(raw * register.scale, 6)


def decode_all(blocks: dict[str, list[int]]) -> dict:
    """Decode every named register from the raw words of a completed poll.

    TIME registers that hold an invalid value (hour > 23 or minute > 59) are
    returned as None rather than raising.
    """
    values = {}
    for name in REGISTERS:
        try:
            values[name] = decode(name, blocks)
        except ValueError:
            values[name] = None
    return values


def encode_time(value: time) -> int:
    """Pack a time of day into one register: hour in the high byte, minute low."""
    return (value.hour << 8) | value.minute


def registers_to_string(words: list[int]) -> str:
    """Decode ASCII text stored two characters per register, high byte first."""
    chars = []
    for word in words:
        for byte in ((word >> 8) & 0xFF, word & 0xFF):
            if byte:
                chars.append(chr(byte))
    return "".join(chars).strip()
