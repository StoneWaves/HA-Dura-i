# Changelog

All notable changes to this project will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
