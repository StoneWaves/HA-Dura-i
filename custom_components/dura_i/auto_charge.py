"""Automatic Grid Charge Max SoC planning.

Each night the inverter charges from the grid during the cheap window and
stops at Grid Charge Max SoC (0x2117). This module picks that SoC from the
solar forecast and the household's usual consumption, so the battery charges
only as much as tomorrow needs.

How the target is chosen:

1. Work out the next charge window (default 02:00-08:00).
2. Step through the day after it in 30-minute slots, from the end of the window
   until the start of the next one. Each slot adds the forecast solar for that
   hour and takes away the average consumption for that hour of day over the
   last week, from HA's long-term statistics. The forecast comes from sensors
   the user chooses: hourly detail is used as-is, and a plain daily total is
   spread in the shape of the system's own recent PV output.
3. Simulate the battery from each starting SoC (0-100 %), capping at full
   capacity because surplus solar is exported. Two strategies:
   * minimum: the lowest start SoC that never drops below the reserve, plus
     a safety margin. Buys only what tomorrow needs.
   * maximum: the highest start SoC that doesn't cause any extra solar to be
     exported for lack of room, less the margin, and never below the
     minimum. Buys as much cheap energy as the solar leaves
     room for.

The target is shown in a sensor all the time. It is only written to the
inverter at the user's chosen time (default 00:45, before the window opens),
while the Auto Grid Charge switch is on.

The inverter clears Charge Window 1 to 00:00-00:00 shortly after each window
ends. While the Keep Charge Window Set switch is on, the window being planned
for is written back to the inverter: shortly after each window ends, as the
next one opens, and on every 30-minute refresh if it has been cleared or
changed. This is independent of Auto Grid Charge, so the window can be kept
while Grid Charge Max SoC is set by hand.

With the Delay Grid Charge Start switch on, the window's start is moved later
so the battery reaches its set point about 30 minutes before the window ends,
rather than charging straight away and sitting full for hours. From 30
minutes before the window opens, the start is re-planned every minute from
the current SoC, the set point, the charge power, the expected drain until
charging starts, and a charge rate learned from earlier nights. It assumes
the battery charges at the set charge power, and allows 25 % extra charge time
in case it's slower. Once charging has started the start is left alone. The window keeps its usual end, so a
slow charge still has until then to finish.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, time, timedelta
import logging

from homeassistant.components.recorder import get_instance, history
from homeassistant.components.recorder.statistics import statistics_during_period
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.components.switch import SwitchEntity
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .registers import REGISTERS, encode_time

_LOGGER = logging.getLogger(__name__)

# Option keys (stored in the config entry's data by the options form).
OPT_FORECAST_TODAY = "auto_charge_forecast_today"
OPT_FORECAST_TOMORROW = "auto_charge_forecast_tomorrow"
OPT_FORECAST_FIELD = "auto_charge_forecast_field"
OPT_CONSUMPTION = "auto_charge_consumption"
OPT_CAPACITY = "auto_charge_capacity_kwh"
OPT_MARGIN = "auto_charge_margin_soc"
OPT_WINDOW_START = "auto_charge_window_start"
OPT_WINDOW_END = "auto_charge_window_end"
OPT_RUN_TIME = "auto_charge_run_time"
OPT_WINDOW_SCHEDULE = "auto_charge_window_schedule"
OPT_STRATEGY = "auto_charge_strategy"

STRATEGY_MINIMUM = "minimum"
STRATEGY_MAXIMUM = "maximum"
STRATEGIES = (STRATEGY_MINIMUM, STRATEGY_MAXIMUM)

# Solcast estimate names, as shown in the options form, mapped to the keys in
# its detailedHourly attribute.
FORECAST_FIELDS = {
    "estimate10": "pv_estimate10",  # pessimistic: 90 % chance of beating it
    "estimate": "pv_estimate",  # typical
    "estimate90": "pv_estimate90",  # optimistic
}

DEFAULTS = {
    OPT_FORECAST_FIELD: "estimate10",
    OPT_CAPACITY: 0.0,  # 0 = not configured
    OPT_MARGIN: 5,
    OPT_STRATEGY: STRATEGY_MINIMUM,
    OPT_WINDOW_START: "02:00:00",
    OPT_WINDOW_END: "08:00:00",
    # Before the earliest window start; windows can move with the seasons.
    OPT_RUN_TIME: "00:45:00",
}

# Used only until the inverter's own Battery Reserve SoC (0x211B) has been read.
FALLBACK_RESERVE_SOC = 20

PROFILE_DAYS = 7
SLOT = timedelta(minutes=30)
REFRESH_INTERVAL = timedelta(minutes=30)
# The inverter clears its charge window about 10 s after the window ends.
REARM_DELAY = timedelta(minutes=1)
# How far back to look for the schedule's last on/off period after a restart.
SCHEDULE_HISTORY = timedelta(days=8)
WINDOW_KEYS = ("charge_window_1_start", "charge_window_1_end")

# Delayed start: aim to reach the set point this long before the window ends.
LATE_FINISH_MARGIN = timedelta(minutes=30)
# Start planning (and move the start) this long before the window opens.
LATE_LEAD = timedelta(minutes=30)
# Leave the inverter's start alone if it's at most this much earlier than
# planned, so it isn't rewritten every minute.
LATE_SLACK = timedelta(minutes=10)
LATE_INTERVAL = timedelta(minutes=1)
# The plan assumes the battery charges at the inverter's set charge power, but
# the BMS (a smaller battery, or a cold one) can hold it lower. Plan as if the
# charge takes this much longer, on top of LATE_FINISH_MARGIN. Together they
# cover charging at about 70 % of the set power.
CHARGE_TIME_BUFFER = 1.25
# Until a rate has been learned: SoC % per kWh charged, as a fraction of
# 100 / capacity. Below the ~0.8 measured on a Dura16, so it starts early.
CHARGE_EFFICIENCY_GUESS = 0.75
# Battery Load below this (kW, negative = charging) counts as charging.
CHARGING_KW = -0.3
# Learn only from charges at least this big.
MIN_LEARN_KWH = 2.0
# A gap this long in charging ends a charge (the hold top-ups are separate).
CHARGE_GAP = timedelta(minutes=3)


def plan_late_start(
    now: datetime,
    window_start: datetime,
    finish_by: datetime,
    soc: float,
    target: float,
    charge_pct_per_hour: float,
    drain_pct_per_hour: float,
) -> datetime:
    """When to start charging so the battery reaches ``target`` at ``finish_by``.

    Until charging starts the battery covers the house, so it drains at
    ``drain_pct_per_hour``. Solves
    charge * (finish_by - start) = target - soc + drain * (start - now)
    for the start, kept between the window's start (or now) and finish_by.
    """
    if finish_by <= window_start:
        return window_start
    hours_left = (finish_by - now) / timedelta(hours=1)
    hours = (charge_pct_per_hour * hours_left - (target - soc)) / (
        charge_pct_per_hour + drain_pct_per_hour
    )
    start = now + timedelta(hours=hours)
    return min(max(start, window_start, now), finish_by)


def nearest_minute(moment: datetime) -> time:
    """Local time of day rounded to the nearest minute (registers hold HH:MM).

    Rounded rather than truncated: a window measured from the schedule can end
    at 07:59:59.9996, which must be written as 08:00.
    """
    rounded = dt_util.as_local(moment) + timedelta(seconds=30)
    return rounded.time().replace(second=0, microsecond=0)


def plan_target_soc(
    pv_kwh: list[float],
    load_kwh: list[float],
    capacity_kwh: float,
    reserve_soc: int,
    margin_soc: int,
) -> tuple[int, int]:
    """Return (target SoC, SoC needed before the margin) for one day.

    ``pv_kwh`` and ``load_kwh`` are per-slot energy from the end of the charge
    window to the start of the next one.
    """
    reserve_kwh = capacity_kwh * reserve_soc / 100
    needed = 100
    for soc in range(101):
        energy = lowest = capacity_kwh * soc / 100
        for pv, load in zip(pv_kwh, load_kwh):
            # Surplus beyond a full battery is exported, not stored.
            energy = min(capacity_kwh, energy + pv - load)
            lowest = min(lowest, energy)
        if lowest >= reserve_kwh:
            needed = soc
            break
    target = max(reserve_soc, min(100, needed + margin_soc))
    return target, needed


def plan_max_soc(
    pv_kwh: list[float],
    load_kwh: list[float],
    capacity_kwh: float,
    reserve_soc: int,
) -> int:
    """The highest start SoC that doesn't make any more solar go to export.

    Simulates each start SoC, with the battery held at the reserve when the
    house would take it lower (the grid covers the rest), and adds up the
    solar that has to be exported because the battery is full. Some days
    export the same amount from any start (the solar fills the battery
    anyway), so the answer is the highest start that exports no more than
    starting empty would. On days the solar never fills the battery, 100.
    """
    reserve_kwh = capacity_kwh * reserve_soc / 100
    tolerance = 0.05  # kWh, for rounding

    def exported(soc: int) -> float:
        energy = capacity_kwh * soc / 100
        spilled = 0.0
        for pv, load in zip(pv_kwh, load_kwh):
            # The house can't take the battery below the reserve (or below
            # where it already is, if it starts under the reserve).
            floor = min(energy, reserve_kwh)
            energy = max(floor, energy + pv - load)
            if energy > capacity_kwh:
                spilled += energy - capacity_kwh
                energy = capacity_kwh
        return spilled

    unavoidable = exported(0)
    for soc in range(100, -1, -1):
        if exported(soc) <= unavoidable + tolerance:
            return soc
    return 0


def choose_target(
    strategy: str,
    min_target: int,
    max_soc: int,
    reserve_soc: int,
    margin_soc: int,
) -> int:
    """The target for the chosen strategy (see the module docstring)."""
    if strategy != STRATEGY_MAXIMUM:
        return min_target
    return max(min_target, reserve_soc, min(100, max_soc - margin_soc))


def _to_kwh(value, unit: str | None) -> float | None:
    """Convert a forecast sensor's state to kWh, or None if it isn't a number."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    factor = {"Wh": 0.001, "MWh": 1000.0}.get(unit or "", 1.0)
    return max(0.0, number * factor)


def next_window(now: datetime, start: time, end: time) -> tuple[datetime, datetime]:
    """Return the start and end of the charge window that ends next.

    Keyed on the end, so running just before or during a window (or a little
    after a window that started earlier than usual) still plans for tonight
    rather than tomorrow night.
    """
    end_dt = datetime.combine(now.date(), end, tzinfo=now.tzinfo)
    if end_dt <= now:
        end_dt += timedelta(days=1)
    start_dt = datetime.combine(end_dt.date(), start, tzinfo=now.tzinfo)
    if start_dt >= end_dt:
        start_dt -= timedelta(days=1)
    return start_dt, end_dt


class AutoChargeManager:
    """Keeps the recommended target up to date and writes it when enabled."""

    def __init__(self, hass: HomeAssistant, controller, config: dict) -> None:
        """Set up from the config entry's data."""
        self.hass = hass
        self.controller = controller
        self.config = {**DEFAULTS, **{k: v for k, v in config.items() if v not in ("", None)}}
        self.enabled = False  # set by the Auto Grid Charge switch
        self.keep_window = False  # set by the Keep Charge Window Set switch
        self.late_charge = False  # set by the Delay Grid Charge Start switch
        self.soc_per_kwh: float | None = None  # learned charge rate
        self.late_details: dict = {}
        self._charge_log: dict | None = None
        self._load_profile: dict[int, float] | None = None
        self._late_dirty = False  # late_details changed since entities updated
        self.target: int | None = None
        self.details: dict = {}
        self._listeners: list = []
        self._unsubs: list = []

        self.window_start = dt_util.parse_time(str(self.config[OPT_WINDOW_START]))
        self.window_end = dt_util.parse_time(str(self.config[OPT_WINDOW_END]))
        self.run_time = dt_util.parse_time(str(self.config[OPT_RUN_TIME]))
        # A schedule helper (e.g. schedule.night_tariff) that is on during the
        # cheap window. When set, it replaces the fixed times and the run time.
        self.schedule = self.config.get(OPT_WINDOW_SCHEDULE)
        self._schedule_on_at: datetime | None = None
        self._schedule_duration: timedelta | None = None
        self._rearm_unsub = None

    @property
    def configured(self) -> bool:
        """True once the capacity and at least one forecast sensor are set."""
        return float(self.config[OPT_CAPACITY]) > 0 and bool(
            self.config.get(OPT_FORECAST_TODAY) or self.config.get(OPT_FORECAST_TOMORROW)
        )

    @callback
    def async_start(self) -> None:
        """Start refreshing the plan, and schedule the nightly write."""
        self.hass.async_create_task(self._async_startup())
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_refresh_cb, REFRESH_INTERVAL)
        )
        self._unsubs.append(
            async_track_time_interval(self.hass, self._async_minute_cb, LATE_INTERVAL)
        )
        if self.schedule:
            # Calculate and write the moment the cheap window opens, when its
            # end time is known exactly.
            state = self.hass.states.get(self.schedule)
            if state is not None and state.state == "on":
                self._schedule_on_at = state.last_changed
            self._unsubs.append(
                async_track_state_change_event(
                    self.hass, [self.schedule], self._async_schedule_changed
                )
            )
        else:
            self._unsubs.append(
                async_track_time_change(
                    self.hass,
                    self._async_write_cb,
                    hour=self.run_time.hour,
                    minute=self.run_time.minute,
                    second=0,
                )
            )
            # Put the window back once the inverter has cleared it.
            rearm = (
                datetime.combine(datetime.min, self.window_end) + REARM_DELAY
            ).time()
            self._unsubs.append(
                async_track_time_change(
                    self.hass,
                    self._async_arm_cb,
                    hour=rearm.hour,
                    minute=rearm.minute,
                    second=rearm.second,
                )
            )

    @callback
    def async_stop(self) -> None:
        """Cancel the timers."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._rearm_unsub is not None:
            self._rearm_unsub()
            self._rearm_unsub = None

    async def _async_startup(self) -> None:
        """Learn the schedule's window from history, then plan and arm."""
        if self.schedule:
            try:
                await self._async_learn_schedule()
            except Exception:  # planning still works with the fallback length
                _LOGGER.exception(
                    "Auto grid charge: could not read %s's history", self.schedule
                )
        await self.async_refresh()
        await self.async_arm_window()

    async def _async_learn_schedule(self) -> None:
        """Find the schedule's last full on period in the recorder.

        Without this, a restart forgets the window's length until it has been
        through one more window, and a restart during the window would take
        the restart time as the window's start.
        """
        end = dt_util.utcnow()
        changes = await get_instance(self.hass).async_add_executor_job(
            history.state_changes_during_period,
            self.hass,
            end - SCHEDULE_HISTORY,
            end,
            self.schedule,
        )
        previous = None
        on_at = None
        for state in changes.get(self.schedule, []):
            if state.state not in ("on", "off"):
                continue  # unavailable during a restart: not a real change
            if state.state == "on" and previous == "off":
                on_at = state.last_changed
            elif state.state == "off" and previous == "on" and on_at is not None:
                self._schedule_duration = state.last_changed - on_at
                on_at = None
            previous = state.state
        if previous == "on" and on_at is not None:
            self._schedule_on_at = on_at

    @callback
    def add_listener(self, update) -> callable:
        """Call ``update`` whenever the plan changes. Returns a remover."""
        self._listeners.append(update)
        return lambda: self._listeners.remove(update)

    async def _async_refresh_cb(self, _now) -> None:
        await self.async_refresh()
        await self.async_arm_window()

    async def _async_arm_cb(self, _now) -> None:
        self._rearm_unsub = None
        await self.async_arm_window()

    async def _async_minute_cb(self, now) -> None:
        """Learn the charge rate, and re-plan a delayed start."""
        self._sample_charge(now)
        if self.late_charge:
            await self.async_arm_window()

    def _values(self) -> dict:
        """The first inverter's last poll."""
        if not self.controller.inverters:
            return {}
        serial = self.controller.inverters[0].serial_number
        return self.controller.last_values.get(serial, {})

    def _notify(self) -> None:
        for update in list(self._listeners):
            update()

    def _sample_charge(self, now: datetime) -> None:
        """Track a grid charge's SoC rise and energy, to learn the rate."""
        values = self._values()
        load, soc = values.get("battery_load"), values.get("soc")
        log = self._charge_log
        charging = isinstance(load, (int, float)) and load < CHARGING_KW
        if charging:
            # Only grid charges in the window; solar charging varies too much.
            window = self._known_window(now)
            charging = window is not None and window[0] <= now < window[1]
        if charging and isinstance(soc, (int, float)):
            if log is None:
                self._charge_log = {
                    "first_soc": soc, "last_soc": soc, "kwh": 0.0, "last_at": now
                }
                return
            step = min(now - log["last_at"], CHARGE_GAP) / timedelta(hours=1)
            log["kwh"] += -load * step
            log["last_soc"] = soc
            log["last_at"] = now
        elif log is not None and now - log["last_at"] >= CHARGE_GAP:
            self._charge_log = None
            self._learn(log)

    def _default_soc_per_kwh(self) -> float | None:
        capacity = float(self.config[OPT_CAPACITY])
        return 100 / capacity * CHARGE_EFFICIENCY_GUESS if capacity > 0 else None

    def _learn(self, log: dict) -> None:
        """Update the learned SoC % per kWh from a finished charge."""
        rise = log["last_soc"] - log["first_soc"]
        capacity = float(self.config[OPT_CAPACITY])
        if log["kwh"] < MIN_LEARN_KWH or rise <= 0 or capacity <= 0:
            return
        ideal = 100 / capacity
        rate = min(max(rise / log["kwh"], 0.5 * ideal), 1.2 * ideal)
        self.soc_per_kwh = (
            rate if self.soc_per_kwh is None else (self.soc_per_kwh + rate) / 2
        )
        _LOGGER.info(
            "Delay grid charge: learned %.2f %% per kWh (%s %% from %.1f kWh)",
            self.soc_per_kwh,
            rise,
            log["kwh"],
        )
        self._notify()

    async def _async_write_cb(self, _now) -> None:
        await self.async_write_target()

    async def _async_schedule_changed(self, event) -> None:
        """Write the target when the cheap window opens; learn its length."""
        new, old = event.data.get("new_state"), event.data.get("old_state")
        if new is None:
            return
        was_on = old is not None and old.state == "on"
        if new.state == "on" and not was_on:
            # Only a real off -> on is the window's start; coming back from a
            # restart keeps the start learned from history.
            if (old is not None and old.state == "off") or self._schedule_on_at is None:
                self._schedule_on_at = new.last_changed
            await self.async_write_target()
            await self.async_arm_window()
        elif new.state == "off" and was_on:
            if self._schedule_on_at is not None:
                self._schedule_duration = new.last_changed - self._schedule_on_at
            self._schedule_on_at = None
            await self.async_refresh()
            if self._rearm_unsub is not None:
                self._rearm_unsub()
            self._rearm_unsub = async_call_later(
                self.hass, REARM_DELAY, self._async_arm_cb
            )

    def _window(self, now: datetime) -> tuple[datetime, datetime, str]:
        """The charge window being planned for, and where it came from."""
        state = self.hass.states.get(self.schedule) if self.schedule else None
        if state is not None and state.state in ("on", "off"):
            next_event = state.attributes.get("next_event")
            if not isinstance(next_event, datetime):
                next_event = dt_util.parse_datetime(str(next_event))
            if next_event is not None:
                next_event = dt_util.as_local(next_event)
                if state.state == "on":
                    # In the window: it started when the schedule turned on,
                    # and ends at the schedule's next event.
                    started = self._schedule_on_at or state.last_changed
                    return dt_util.as_local(started), next_event, self.schedule
                # Between windows: the next one starts at the next event. Its
                # length is the last window seen, or the fixed times' length.
                fixed_start, fixed_end = next_window(
                    now, self.window_start, self.window_end
                )
                length = self._schedule_duration or (fixed_end - fixed_start)
                return next_event, next_event + length, self.schedule
        start, end = next_window(now, self.window_start, self.window_end)
        return start, end, "fixed times"

    async def async_refresh(self) -> None:
        """Recalculate the target from the latest forecast and usage."""
        try:
            self.target, self.details = await self._async_calculate()
        except Exception:  # keep the timers running whatever goes wrong
            _LOGGER.exception("Auto grid charge: could not calculate a target")
            self.target = None
            self.details = {"reason": "Calculation failed; see the log"}
        for update in list(self._listeners):
            update()

    async def _async_calculate(self) -> tuple[int | None, dict]:
        if not self.configured:
            return None, {
                "reason": "Set the battery capacity and a solar forecast sensor "
                "in the integration options"
            }

        now = dt_util.now()
        start_dt, end_dt, window_source = self._window(now)
        horizon_end = start_dt + timedelta(days=1)

        hourly_pv = await self._async_forecast_by_hour(now)
        if not hourly_pv:
            return None, {
                "reason": "The solar forecast sensors have no usable value "
                "(a kWh total, or Solcast-style hourly detail)"
            }

        consumption = self._own_sensor("_grid_tied_load", OPT_CONSUMPTION)
        if consumption is None:
            return None, {"reason": "No consumption sensor found"}
        profile = await self._async_hourly_profile(consumption)
        self._load_profile = profile
        if profile is None:
            return None, {
                "reason": f"No usage history for {consumption} yet; it needs a "
                "few hours of long-term statistics"
            }

        pv_kwh, load_kwh = [], []
        slot = end_dt
        while slot < horizon_end:
            hour_start = slot.replace(minute=0, second=0, microsecond=0)
            pv_kwh.append(hourly_pv.get(dt_util.as_utc(hour_start), 0.0) * SLOT / timedelta(hours=1))
            load_kwh.append(profile[slot.hour] * SLOT / timedelta(hours=1))
            slot += SLOT

        capacity = float(self.config[OPT_CAPACITY])
        reserve, reserve_source = self._reserve_soc()
        margin = int(self.config[OPT_MARGIN])
        min_target, needed = plan_target_soc(
            pv_kwh,
            load_kwh,
            capacity,
            reserve,
            margin,
        )
        strategy = self.config[OPT_STRATEGY]
        max_soc = plan_max_soc(pv_kwh, load_kwh, capacity, reserve)
        target = choose_target(strategy, min_target, max_soc, reserve, margin)
        return target, {
            "strategy": strategy,
            "minimum_target_soc": min_target,
            "max_soc_before_margin": max_soc,
            "planned_for": start_dt.isoformat(),
            "window_source": window_source,
            "set_at": (
                "when the schedule turns on"
                if self.schedule
                else self.run_time.strftime("%H:%M")
            ),
            "plan_starts": end_dt.isoformat(),
            "plan_ends": horizon_end.isoformat(),
            "solar_forecast_kwh": round(sum(pv_kwh), 2),
            "expected_use_kwh": round(sum(load_kwh), 2),
            "forecast_estimate": self.config[OPT_FORECAST_FIELD],
            "needed_soc_before_margin": needed,
            "consumption_sensor": consumption,
            "battery_capacity_kwh": capacity,
            "reserve_soc": reserve,
            "reserve_source": reserve_source,
            "margin_soc": int(self.config[OPT_MARGIN]),
        }

    def _reserve_soc(self) -> tuple[int, str]:
        """The SoC to keep in reserve: the inverter's own setting if readable.

        Read from the last poll (register 0x211B, Battery Reserve SoC), so it
        works whether or not that sensor is enabled. Uses the highest reserve
        across parallel inverters, falling back to a safe default.
        """
        reserves = [
            values.get("battery_reserve_soc")
            for values in self.controller.last_values.values()
        ]
        valid = [r for r in reserves if isinstance(r, int) and 0 < r < 100]
        if valid:
            return max(valid), "inverter (Battery Reserve SoC)"
        return FALLBACK_RESERVE_SOC, "default (inverter reserve not read yet)"

    async def _async_forecast_by_hour(self, now: datetime) -> dict[datetime, float]:
        """Forecast solar kWh for each hour, keyed by UTC hour start.

        Each forecast sensor can be either:
        * Solcast-style, with a ``detailedHourly`` attribute: used hour by hour;
        * a plain total for its day, in kWh (or Wh/MWh): spread over the day in
          the same shape as this system's PV output over the last week.

        The "today" sensor covers today's date and the "tomorrow" sensor
        tomorrow's, so the plan stays right either side of midnight.
        """
        field = FORECAST_FIELDS.get(self.config[OPT_FORECAST_FIELD], "pv_estimate10")
        hourly: dict[datetime, float] = {}
        shape: list[float] | None = None

        for key, day_offset in ((OPT_FORECAST_TODAY, 0), (OPT_FORECAST_TOMORROW, 1)):
            entity_id = self.config.get(key)
            state = self.hass.states.get(entity_id) if entity_id else None
            if state is None:
                continue

            detail = state.attributes.get("detailedHourly")
            if detail:
                for row in detail:
                    period = dt_util.parse_datetime(str(row.get("period_start")))
                    value = row.get(field, row.get("pv_estimate"))
                    if period is not None and value is not None:
                        hourly[dt_util.as_utc(period)] = float(value)
                continue

            total = _to_kwh(state.state, state.attributes.get("unit_of_measurement"))
            if total is None:
                _LOGGER.debug("Auto grid charge: %s has no usable value", entity_id)
                continue
            if shape is None:
                shape = await self._async_solar_shape()
            day = now.date() + timedelta(days=day_offset)
            for hour in range(24):
                hour_start = datetime.combine(day, time(hour), tzinfo=now.tzinfo)
                hourly.setdefault(dt_util.as_utc(hour_start), total * shape[hour])
        return hourly

    async def _async_solar_shape(self) -> list[float]:
        """Fraction of a day's solar produced in each hour of the day.

        Taken from this system's own PV Power over the last week; falls back to
        a simple 08:00-16:00 curve until there's history.
        """
        pv_sensor = self._own_sensor("_pv_power")
        profile = await self._async_hourly_profile(pv_sensor) if pv_sensor else None
        if profile and sum(profile.values()) > 0:
            total = sum(profile.values())
            return [profile[hour] / total for hour in range(24)]
        weights = [max(0, 4 - abs(hour + 0.5 - 12)) for hour in range(24)]
        return [w / sum(weights) for w in weights]

    def _own_sensor(self, suffix: str, option: str | None = None) -> str | None:
        """The chosen sensor for ``option``, else this integration's own one."""
        if option and self.config.get(option):
            return self.config[option]
        if not self.controller.inverters:
            return None
        return er.async_get(self.hass).async_get_entity_id(
            "sensor", DOMAIN, self.controller.inverters[0].serial_number + suffix
        )

    async def _async_hourly_profile(self, entity_id: str) -> dict[int, float] | None:
        """Average kWh in each hour of the day over the last week.

        Works with an energy sensor (uses the hourly change) or a power sensor
        (the hourly mean in kW is the kWh in that hour).
        """
        state = self.hass.states.get(entity_id)
        is_energy = state is not None and state.attributes.get("device_class") == "energy"
        stat = "change" if is_energy else "mean"

        end = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)
        start = end - timedelta(days=PROFILE_DAYS)
        stats = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            {entity_id},
            "hour",
            {"energy": "kWh", "power": "kW"},
            {stat},
        )

        buckets: dict[int, list[float]] = defaultdict(list)
        for row in stats.get(entity_id, []):
            value = row.get(stat)
            if value is None:
                continue
            row_start = row["start"]
            if isinstance(row_start, (int, float)):
                row_start = dt_util.utc_from_timestamp(row_start)
            buckets[dt_util.as_local(row_start).hour].append(max(0.0, float(value)))

        samples = [v for values in buckets.values() for v in values]
        if not samples:
            return None
        overall = sum(samples) / len(samples)
        return {
            hour: (sum(buckets[hour]) / len(buckets[hour]) if buckets[hour] else overall)
            for hour in range(24)
        }

    def _known_window(self, now: datetime) -> tuple[datetime, datetime] | None:
        """The window being planned for, or None if it isn't known for sure.

        With a schedule, its length is only known once a full window has been
        seen (or found in history), and guessing could cut the night short.
        """
        start_dt, end_dt, source = self._window(now)
        if self.schedule:
            state = self.hass.states.get(self.schedule)
            if source != self.schedule or state is None:
                return None
            if state.state == "off" and self._schedule_duration is None:
                return None
        return dt_util.as_local(start_dt), dt_util.as_local(end_dt)

    def window_times(self) -> tuple[time, time] | None:
        """Start and end (HH:MM) of the window to keep on the inverter."""
        now = dt_util.now()
        window = self._known_window(now)
        if window is None:
            return None
        start_dt, end_dt = window
        if self.late_charge and start_dt - LATE_LEAD <= now < end_dt:
            start_dt = self._late_start(now, start_dt, end_dt)
        elif self.late_details:
            self.late_details = {}
            self._late_dirty = True
        return nearest_minute(start_dt), nearest_minute(end_dt)

    def _inverter_start(self, window_start: datetime, end: datetime) -> datetime | None:
        """The inverter's current window start, as a moment in this window."""
        current = self._values().get("charge_window_1_start")
        if not isinstance(current, time):
            return None
        moment = datetime.combine(window_start.date(), current, tzinfo=window_start.tzinfo)
        if moment < window_start.replace(second=0, microsecond=0):
            moment += timedelta(days=1)
        return moment if moment < end else None

    def _late_start(self, now: datetime, window_start: datetime, end: datetime) -> datetime:
        """The delayed start for this window (see plan_late_start)."""
        current = self._inverter_start(window_start, end)
        if current is not None and current <= now:
            # Charging has started (or the window opened as planned): leave it.
            self._set_late_details({"status": "charging", "start": current})
            return current

        values = self._values()
        soc = values.get("soc")
        target = self.target if self.enabled and self.target is not None else values.get(
            "grid_max_charge_soc"
        )
        powers = [
            values.get(key)
            for key in ("grid_max_charge_power", "battery_max_charge_power")
        ]
        powers = [p for p in powers if isinstance(p, (int, float)) and p > 0]
        capacity = float(self.config[OPT_CAPACITY])
        soc_per_kwh = self.soc_per_kwh or self._default_soc_per_kwh()
        if not (
            isinstance(soc, (int, float))
            and isinstance(target, (int, float))
            and powers
            and soc_per_kwh
        ):
            reason = (
                "Set the battery capacity in the integration options"
                if capacity <= 0
                else "Waiting for the inverter's SoC, set point and charge power"
            )
            self._set_late_details({"status": "full window", "reason": reason})
            return window_start

        charge_kw = min(powers) / 1000
        if self._load_profile:
            load_kw = self._load_profile[now.hour]
        else:
            load_kw = max(0.0, float(values.get("battery_load") or 0))
        charge_rate = soc_per_kwh * charge_kw
        drain_rate = load_kw * 100 / capacity
        finish_by = end - LATE_FINISH_MARGIN
        planned = plan_late_start(
            now,
            window_start,
            finish_by,
            soc,
            target,
            charge_rate / CHARGE_TIME_BUFFER,
            drain_rate,
        )
        start = planned
        if current is not None and planned - LATE_SLACK <= current <= planned:
            start = current  # close enough: finishes a little early
        self._set_late_details(
            {
                "status": "waiting",
                "start": start,
                "planned_start": planned,
                "finish_by": finish_by,
                "soc": soc,
                "set_point": target,
                "charge_rate_pct_per_hour": round(charge_rate, 1),
                "charge_time_buffer_pct": round((CHARGE_TIME_BUFFER - 1) * 100),
                "drain_pct_per_hour": round(drain_rate, 1),
            }
        )
        return start

    def _set_late_details(self, details: dict) -> None:
        """Record the delayed-start plan; async_arm_window tells the entities.

        Not notified from here: this runs inside window_times, which entity
        attributes call too, and writing state from there would re-enter.
        """
        shown = {
            key: (nearest_minute(value).strftime("%H:%M") if isinstance(value, datetime) else value)
            for key, value in details.items()
        }
        if shown != self.late_details:
            self.late_details = shown
            self._late_dirty = True

    async def async_arm_window(self) -> None:
        """Write the charge window to the inverters if it was cleared or differs."""
        if not (self.keep_window or self.late_charge):
            return
        window = self.window_times()
        if self._late_dirty:
            self._late_dirty = False
            self._notify()
        if window is None:
            _LOGGER.debug(
                "Keep charge window: window from %s not known yet", self.schedule
            )
            return
        for inverter in self.controller.inverters:
            for key, wanted in zip(WINDOW_KEYS, window):
                # Re-read each time: set_register polls, replacing the values.
                current = self.controller.last_values.get(
                    inverter.serial_number, {}
                ).get(key)
                if current == wanted:
                    continue
                _LOGGER.info(
                    "Keep charge window: setting %s to %s on %s (was %s)",
                    key,
                    wanted.strftime("%H:%M"),
                    inverter.serial_number,
                    current.strftime("%H:%M") if isinstance(current, time) else current,
                )
                try:
                    await self.controller.set_register(
                        inverter, REGISTERS[key].address, encode_time(wanted)
                    )
                except Exception:  # retried on the next refresh
                    _LOGGER.exception(
                        "Keep charge window: could not write %s on %s",
                        key,
                        inverter.serial_number,
                    )
                    return

    async def async_write_target(self) -> None:
        """Write the target to every inverter's Grid Charge Max SoC, if enabled."""
        if not self.enabled:
            return
        await self.async_refresh()
        if self.target is None:
            _LOGGER.warning(
                "Auto grid charge is on but there is no target (%s); "
                "leaving Grid Charge Max SoC unchanged",
                self.details.get("reason"),
            )
            return

        register = REGISTERS["grid_max_charge_soc"].address
        for inverter in self.controller.inverters:
            entity = self.controller.number_entities.get(
                inverter.serial_number + "_grid_max_charge_soc"
            )
            if entity is not None and entity.currentValue == self.target:
                continue
            _LOGGER.info(
                "Auto grid charge: setting Grid Charge Max SoC to %s%% on %s "
                "(forecast %s kWh solar, %s kWh use)",
                self.target,
                inverter.serial_number,
                self.details.get("solar_forecast_kwh"),
                self.details.get("expected_use_kwh"),
            )
            await self.controller.set_register(inverter, register, self.target)


def _device_info(manager: AutoChargeManager):
    inverters = manager.controller.inverters
    return inverters[0].device_info if inverters else None


class AutoChargeTargetSensor(SensorEntity):
    """The Grid Charge Max SoC the planner recommends for the next night."""

    _attr_has_entity_name = True
    _attr_name = "Auto Grid Charge Target SoC"
    _attr_icon = "mdi:battery-clock"
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_unique_id = "dura_i_auto_charge_target_soc"

    def __init__(self, manager: AutoChargeManager) -> None:
        """Create the sensor."""
        self._manager = manager
        self._attr_device_info = _device_info(manager)
        self.entity_id = generate_entity_id(
            "sensor.{}", "dura_i_auto_charge_target_soc", [], None
        )

    async def async_added_to_hass(self) -> None:
        """Update whenever the plan changes."""
        self.async_on_remove(self._manager.add_listener(self.async_write_ha_state))

    @property
    def native_value(self) -> int | None:
        """The target SoC, or unknown when it can't be calculated."""
        return self._manager.target

    @property
    def extra_state_attributes(self) -> dict:
        """The inputs behind the target, or why there isn't one."""
        return self._manager.details


class AutoChargeSwitch(SwitchEntity, RestoreEntity):
    """Lets the planner write Grid Charge Max SoC each night."""

    _attr_has_entity_name = True
    _attr_name = "Auto Grid Charge"
    _attr_icon = "mdi:battery-sync"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_unique_id = "dura_i_auto_grid_charge"
    # Changes the inverter, so users opt in, like the other controls.
    _attr_entity_registry_enabled_default = False

    def __init__(self, manager: AutoChargeManager) -> None:
        """Create the switch."""
        self._manager = manager
        self._attr_device_info = _device_info(manager)
        self.entity_id = generate_entity_id("switch.{}", "dura_i_auto_grid_charge", [], None)

    async def async_added_to_hass(self) -> None:
        """Restore whether it was on before a restart."""
        last = await self.async_get_last_state()
        self._manager.enabled = last is not None and last.state == "on"

    @property
    def is_on(self) -> bool:
        """Whether the planner writes the target each night."""
        return self._manager.enabled

    async def async_turn_on(self, **kwargs) -> None:
        """Start writing the target before each charge window."""
        self._manager.enabled = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Stop writing; Grid Charge Max SoC keeps its current value."""
        self._manager.enabled = False
        self.async_write_ha_state()


class KeepChargeWindowSwitch(SwitchEntity, RestoreEntity):
    """Writes Charge Window 1 back after the inverter clears it."""

    _attr_has_entity_name = True
    _attr_name = "Keep Charge Window Set"
    _attr_icon = "mdi:clock-check-outline"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_unique_id = "dura_i_keep_charge_window"
    # Changes the inverter, so users opt in, like the other controls.
    _attr_entity_registry_enabled_default = False

    def __init__(self, manager: AutoChargeManager) -> None:
        """Create the switch."""
        self._manager = manager
        self._attr_device_info = _device_info(manager)
        self.entity_id = generate_entity_id(
            "switch.{}", "dura_i_keep_charge_window", [], None
        )

    async def async_added_to_hass(self) -> None:
        """Restore whether it was on, and show the window as the plan updates."""
        last = await self.async_get_last_state()
        self._manager.keep_window = last is not None and last.state == "on"
        self.async_on_remove(self._manager.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        """Whether the charge window is written back each night."""
        return self._manager.keep_window

    @property
    def extra_state_attributes(self) -> dict:
        """The window that will be kept, or why it isn't known yet."""
        window = self._manager.window_times()
        if window is None:
            return {"reason": "Waiting to see one full window from the schedule"}
        return {
            "window_start": window[0].strftime("%H:%M"),
            "window_end": window[1].strftime("%H:%M"),
        }

    async def async_turn_on(self, **kwargs) -> None:
        """Keep the window set, and set it now if it has been cleared."""
        self._manager.keep_window = True
        self.async_write_ha_state()
        await self._manager.async_arm_window()

    async def async_turn_off(self, **kwargs) -> None:
        """Stop writing the window; the inverter keeps whatever it has."""
        self._manager.keep_window = False
        self.async_write_ha_state()


class DelayChargeStartSwitch(SwitchEntity, RestoreEntity):
    """Moves the window's start so charging finishes just before it ends."""

    _attr_has_entity_name = True
    _attr_name = "Delay Grid Charge Start"
    _attr_icon = "mdi:timer-sand"
    _attr_entity_category = EntityCategory.CONFIG
    _attr_unique_id = "dura_i_delay_charge_start"
    # Changes the inverter, so users opt in, like the other controls.
    _attr_entity_registry_enabled_default = False

    def __init__(self, manager: AutoChargeManager) -> None:
        """Create the switch."""
        self._manager = manager
        self._attr_device_info = _device_info(manager)
        self.entity_id = generate_entity_id(
            "switch.{}", "dura_i_delay_charge_start", [], None
        )

    async def async_added_to_hass(self) -> None:
        """Restore the switch and the learned charge rate."""
        last = await self.async_get_last_state()
        self._manager.late_charge = last is not None and last.state == "on"
        if last is not None:
            learned = last.attributes.get("learned_soc_per_kwh")
            if isinstance(learned, (int, float)) and learned > 0:
                self._manager.soc_per_kwh = float(learned)
        self.async_on_remove(self._manager.add_listener(self.async_write_ha_state))

    @property
    def is_on(self) -> bool:
        """Whether the window's start is moved later each night."""
        return self._manager.late_charge

    @property
    def extra_state_attributes(self) -> dict:
        """Tonight's plan, and the charge rate it uses."""
        attrs = dict(self._manager.late_details)
        if self._manager.soc_per_kwh is not None:
            attrs["learned_soc_per_kwh"] = round(self._manager.soc_per_kwh, 3)
        return attrs

    async def async_turn_on(self, **kwargs) -> None:
        """Delay the start from tonight; also keeps the window set."""
        self._manager.late_charge = True
        self.async_write_ha_state()
        await self._manager.async_arm_window()

    async def async_turn_off(self, **kwargs) -> None:
        """Charge from the window's usual start again."""
        self._manager.late_charge = False
        self.async_write_ha_state()
        await self._manager.async_arm_window()
