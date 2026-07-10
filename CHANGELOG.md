# Changelog

All notable changes to this project will be documented in this file.

This project follows [Semantic Versioning](https://semver.org/).

## [0.4.0] - Unreleased

Forked from [HA-Skyline](https://github.com/iPeel/HA-Skyline) v0.3 by @iPeel and adapted for the Duracell Dura-i.

### Added
- Dura-i specific register map and sensor configuration
- Support for RS485 pins 7 and 9 (Dura-i connector pinout)
- CHANGELOG.md

### Changed
- **BREAKING:** Renamed integration package from `cyg_skyline` to `dura_i`
- **BREAKING:** Entity IDs now use `dura_i_` prefix instead of `skyline_`
- Replaced all "Skyline" / "CYG" branding with "Dura-i" / "Duracell" throughout codebase
- Device info shows manufacturer as "Duracell" and name as "Dura-i"
- ClickHouse table renamed from `skyline_stats` to `dura_i_stats`
- Documentation URL updated to this repository
- Version format changed to valid semver string

### Fixed
- Removed DCDC version sensor exposure (not applicable to Dura-i)
- Corrected battery voltage calculation in `set_native_value`
- Ensured `async_write_ha_state` is only called when hass is available
- Fixed number entities using wrong entity domain (`sensor` instead of `number`), resolving HA 2027.5.0 deprecation warning
- Swapped grid energy in/out icons (import and export icons were reversed)
