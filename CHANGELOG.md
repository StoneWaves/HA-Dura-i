# Changelog

All notable changes to this project will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/).

## [2.0.0-beta.4] - 2026-11-12

### Added
- **Keep Charge Window Set** switch, disabled by default. The inverter clears Charge Window 1 to 00:00–00:00 shortly after each window ends. While this switch is on, the integration writes the planner's window back: a minute after each window ends, as the next one opens, and on every 30-minute refresh if it has been cleared or changed. It works without Auto Grid Charge, so you can keep the window while setting Grid Charge Max SoC by hand.
- **Delay Grid Charge Start** switch, disabled by default. It moves the charge window's start later so the battery reaches its set point about 30 minutes before the window ends, instead of charging at the start and sitting full. The start is re-planned every minute from 30 minutes before the window opens, using the SoC, the set point, the charge power, the expected drain until charging starts, and a charge rate learned from each night's grid charge. It allows 25 % extra charge time in case the battery charges slower than the set power. Once charging starts it's left alone, and the window's end doesn't change. The switch's attributes show the plan.
- **Target strategy** option for Auto Grid Charge. **Minimum** (the default, unchanged) charges the lowest SoC that stays above the reserve, plus the margin. **Maximum** charges the highest SoC that doesn't cause any extra solar to be exported for lack of room, less the margin, and never below the minimum, so the battery takes as much cheap energy as the solar leaves room for. The target sensor shows both as `minimum_target_soc` and `max_soc_before_margin`, with the chosen `strategy`.

### Fixed
- With a schedule helper, a restart no longer forgets the window's length, or takes the restart time as the start of a window already in progress. Both now come from the schedule's history in the recorder. Before, the night's plan after a restart could use the fixed times' length.

## [2.0.0-beta.3] - 2026-11-05

### Added
- **Auto Grid Charge.** Sets Grid Charge Max SoC each night from the solar forecast and your usual consumption. It simulates the battery in 30-minute steps from the end of the charge window to the next one, using your average hourly use over the last 7 days, and picks the lowest SoC that stays above your reserve, plus a margin. You choose the forecast sensors yourself: a plain daily total (spread in the shape of your own PV output) or Solcast-style hourly detail (P10 by default). Configure it in the integration options, along with the consumption sensor, battery capacity, margin and charge window. The reserve is the inverter's own Battery Reserve SoC (`0x211B`).
  - New sensor **Auto Grid Charge Target SoC**. Its attributes show the forecast solar, expected use and the SoC needed.
  - New switch **Auto Grid Charge**, disabled by default. While on, it writes the target each night.
  - The cheap window can come from a **schedule helper**: the target is calculated and written as the schedule turns on, so windows that move with the seasons are followed automatically. Otherwise, fixed start/end times and a run time (default 00:45) are used.
- The integration now depends on Home Assistant's recorder, for the usage history.

### Removed
- The Inverter Clock, Battery State of Health and Max/Min Cell Voltage sensors added in beta.2. They used input registers (function 04), which the Dura-i doesn't answer. The failed reads also stalled a poll for up to about 25 seconds every 10 minutes. The four entities are removed from the registry on startup.
- The Charge and Discharge Window 1 Current Limit sensors added in beta.2. They're removed from the registry on startup.

## [2.0.0-beta.2] - 2026-11-05

### Added
- "Discharge Window 1 Start" and "Discharge Window 1 End" time controls (registers `0x2105`/`0x2106`, same format as the charge window). They come from the Solis map, are unconfirmed, and are disabled by default.
- Read-only diagnostic sensors, disabled by default and all unconfirmed (Solis map): Charge and Discharge Window 1 Current Limit (`0x2104`, `0x2107`), Battery Reserve SoC (`0x211B`), Max Depth of Discharge (`0x212D`), Max Charge Limit Power (`0x2125`), Register 8505 (`0x2139`, meaning unknown), Inverter Clock (input registers 3021–3026), and Battery State of Health with Max/Min Cell Voltage (input registers 33140–33142).
- Optional register blocks: the clock and BMS reads use input registers (function 04). If the inverter doesn't answer them, those sensors stay unknown, the main poll carries on, and the block is retried every 10 minutes.
- "Force Charge Target SoC" control (register `0x2138`, 0–100 %). It comes from the Solis map and is unconfirmed on Dura-i hardware. Disabled by default.

### Fixed
- Controls no longer show red validation errors. The SoC limits use 1 % steps and the power limits 0.01 kW steps, so values set in the app (such as a 3.68 kW grid charge limit) are valid. Power values are rounded to the nearest watt when written, rather than truncated.
- Power control maximums now come from the inverter model's datasheet, not a fixed 6 kW: 4.0 / 5.5 / 5.5 / 6.6 kW battery and grid charge, and 3.6 / 4.6 / 5.0 / 6.0 kW feed-in, for the 3.6K / 4.6K / 5K / 6K G3 models. On a 6K the battery limits now reach the full 6.6 kW, so the value the inverter reports is no longer flagged as out of range. Unrecognised models get the smallest (3.6K) limits to be safe, and a warning is logged.
- Controls that earlier versions created hidden are un-hidden on startup. Nothing is hidden by default any more; controls are disabled by default instead. Entities you hid yourself stay hidden.
- Two leftovers from an older version, a per-inverter "Dura-i Consumer Load" and "Dura-i Excess PV Power" registered under the raw serial number, are now removed on startup as well.

## [2.0.0-beta.1] - 2026-11-05

### Breaking
- Feed-in matching is removed: the "Match Feed In To Excess Solar" switch, the "Excess Target SoC" control, the "Dura-i Excess PV Power" sensor, the `dura_i.set_excess_params` service and their options-flow fields. The leftover entities are removed on startup.
- The ClickHouse database export and its options-flow field are removed.

### Added
- "Charge Window 1 Start" and "Charge Window 1 End" time controls (registers `0x2102`/`0x2103`, packed as hour × 256 + minute). Like the other controls, they are disabled by default.
- "Force Charge" switch on register `0x212E` (8494): on writes 1, off writes 0. The register comes from the Solis map and is not yet confirmed on Dura-i hardware. Disabled by default.

### Changed
- New installs create every control (numbers, the work mode select, switches and times) disabled, instead of enabled but hidden. Users who only want to read data never see a control that changes the inverter; enable the ones you want from the device page. Existing controls keep their current state.
- The two charge limits are renamed to say what they limit: "Grid Charge End SoC" (`0x2117`) is now "Grid Charge Max SoC" and "Battery Max SoC" (`0x2119`) is now "Solar Charge Max SoC". Their entity IDs are unchanged.
- The inverter config block read grows from 34 to 58 registers (`0x2100`–`0x2139`) to cover the force-charge register. `0x2139` (8505) is decoded too, but its meaning is still unknown.
- All register reading now goes through `registers.py`: one table of polled blocks, plus every register's address, data type and scale. Sensors are a declarative table in `sensor.py`, and the number/select/switch controls take their write address from the same register table. Unique IDs are unchanged.
- Modbus requests on a connection are serialised, and a write from HA can no longer overlap a background poll.
- If no inverter answers at startup, setup now fails with "not ready" and Home Assistant retries it later.
- Logging: a failing inverter is logged once as a warning with the reason (which block failed, or the traceback for unexpected errors), then at debug level until it recovers. Routine messages such as option changes and register writes are no longer logged as warnings.

### Fixed
- Changing the host or port in the integration's options now takes effect straight away: the integration reloads and reconnects. Before, the change was saved but ignored until Home Assistant restarted. Saving the options also clears settings left over from older versions.
- The "Version Master" sensor is populated again (register `0x1A1C`). Each firmware version is now read separately, so one unreadable version no longer blanks the others.
- The "Am Exporting" / "Am Importing" binary sensors now request a `binary_sensor.` entity ID instead of `sensor.`. Home Assistant was already registering them as binary sensors, so existing entity IDs don't change.
- A failed read on one inverter no longer stops the other inverters updating for that poll.
- Modbus connections are closed when the integration is unloaded or reloaded, and after the connection check in the setup/options form, so the TCP adapter isn't left holding stale connections.
- The six "today" energy sensors (PV, grid in/out, battery in/out) no longer stay stuck on yesterday's value after midnight. The v1.1.0 drop guard was ignoring their daily reset to zero. That guard now only covers the five lifetime totals, which still ignore any drop of more than 1 kWh so a bad read can't make the energy dashboard log a fake meter reset.

### Removed
- The 64 raw "Config Register 0x2100–0x213F" diagnostic sensors used for reverse-engineering the schedule registers. Any existing ones are removed from the entity registry on startup.
- The configurable grid/battery load sanity limits, along with the "Max Grid Load Sanity Limit" and "Max Load Spike Sanity Limit" controls and their options-flow fields. Grid and battery load are reported as read again. The leftover controls are removed from the entity registry on startup.
- Unused per-sensor min/max/spike validation.

## [1.1.0] - 2026-09-21

### Added
- Read-only diagnostic sensors exposing all 64 registers in the inverter config block (`0x2100`–`0x213F`) for reverse-engineering scheduled charge/time-of-use settings
- Monotonic validation for `TOTAL_INCREASING` energy sensors to prevent spikes caused by temporary inverter register drops

### Fixed
- Changing the host or port in the integration's options now takes effect straight away: the integration reloads and reconnects. Before, the change was saved but ignored until Home Assistant restarted. Saving the options also clears settings left over from older versions.
- Energy total sensors (PV, grid in/out, battery in/out) now reject readings that drop significantly below the last known value, eliminating massive spikes when the inverter briefly returns corrupted/zero data

## [0.4.0] - Unreleased

Forked from [HA-Skyline](https://github.com/iPeel/HA-Skyline) v0.3 by @iPeel and adapted for the Duracell Dura-i.

### Added
- Dura-i specific register map and sensor configuration
- Support for RS485 pins 7 and 9 (Dura-i connector pinout)
- CHANGELOG.md

### Changed
- New installs create every control (numbers, the work mode select, switches and times) disabled, instead of enabled but hidden. Users who only want to read data never see a control that changes the inverter; enable the ones you want from the device page. Existing controls keep their current state.
- **BREAKING:** Renamed integration package from `cyg_skyline` to `dura_i`
- **BREAKING:** Entity IDs now use `dura_i_` prefix instead of `skyline_`
- Replaced all "Skyline" / "CYG" branding with "Dura-i" / "Duracell" throughout codebase
- Device info shows manufacturer as "Duracell" and name as "Dura-i"
- ClickHouse table renamed from `skyline_stats` to `dura_i_stats`
- Documentation URL updated to this repository
- Version format changed to valid semver string

### Fixed
- Changing the host or port in the integration's options now takes effect straight away: the integration reloads and reconnects. Before, the change was saved but ignored until Home Assistant restarted. Saving the options also clears settings left over from older versions.
- Removed DCDC version sensor exposure (not applicable to Dura-i)
- Corrected battery voltage calculation in `set_native_value`
- Ensured `async_write_ha_state` is only called when hass is available
- Fixed number entities using wrong entity domain (`sensor` instead of `number`), resolving HA 2027.5.0 deprecation warning
- Swapped grid energy in/out icons (import and export icons were reversed)
