"""Hardware limits for each Dura-i inverter model.

Figures from the Dura-i G3 Inverter datasheet V1.1 (UK). The model number is
read from the inverter at 0x1A00 at startup.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelLimits:
    """Per-inverter power limits in watts."""

    battery_power_w: int  # max battery charge/discharge power
    ac_output_w: int  # nominal AC output power (caps grid feed-in)


MODEL_LIMITS: dict[str, ModelLimits] = {
    "PD-DH1P-3.6K-G3": ModelLimits(battery_power_w=4000, ac_output_w=3600),
    "PD-DH1P-4.6K-G3": ModelLimits(battery_power_w=5500, ac_output_w=4600),
    "PD-DH1P-5K-G3": ModelLimits(battery_power_w=5500, ac_output_w=5000),
    "PD-DH1P-6K-G3": ModelLimits(battery_power_w=6600, ac_output_w=6000),
}

# Used for models not in the table (e.g. G1 units): the smallest G3 limits, so
# HA never offers a value beyond what the hardware might handle. Add a model
# above once its datasheet figures are known.
DEFAULT_LIMITS = MODEL_LIMITS["PD-DH1P-3.6K-G3"]


def limits_for(model_number: str) -> ModelLimits:
    """Return the power limits for an inverter model number."""
    limits = MODEL_LIMITS.get(model_number.strip().upper())
    if limits is None:
        _LOGGER.warning(
            "No datasheet limits for inverter model %r; using the 3.6 kW G3 "
            "limits to be safe. Please report the model so it can be added",
            model_number,
        )
        return DEFAULT_LIMITS
    return limits
