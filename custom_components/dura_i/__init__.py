"""The Dura-i integration."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, PLATFORMS
from .controller import Controller

_LOGGER = logging.getLogger(__name__)

# Unique-ID suffixes of entities earlier versions created but no longer provide.
RETIRED_UNIQUE_ID_SUFFIXES = (
    "_max_grid_load_kw",  # sanity-limit controls
    "_max_load_spike_kw",
    "_excess_target_soc",  # feed-in matching
    "_match_feed_in_to_excess_power",
    "dura_i_average_excess_pv_power",
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Dura-i from a config entry."""
    controller = Controller(entry.data["host"], entry.data["port"], hass, entry)
    await controller.initialise()

    if not controller.inverters:
        controller.terminate()
        # HA retries the setup later with back-off.
        raise ConfigEntryNotReady(f"No Dura-i inverter answered at {entry.data['host']}")

    hass.data.setdefault(DOMAIN, {})["controller"] = controller

    _clean_up_entity_registry(hass, entry)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reconnect with the new host/port when they're changed in the options form.
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))

    return True


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration after its settings change."""
    await hass.config_entries.async_reload(entry.entry_id)


def _clean_up_entity_registry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove entities earlier versions created but no longer provide.

    Without this they would linger as unavailable: the raw "Config Register"
    debug sensors, the sanity-limit controls and the feed-in matching controls.
    """
    registry = er.async_get(hass)
    for entity in er.async_entries_for_config_entry(registry, entry.entry_id):
        unique_id = entity.unique_id
        if "_config_reg_" in unique_id or unique_id.endswith(
            RETIRED_UNIQUE_ID_SUFFIXES
        ):
            _LOGGER.info("Removing old entity %s from the registry", entity.entity_id)
            registry.async_remove(entity.entity_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    controller = hass.data[DOMAIN].pop("controller", None)
    if controller is not None:
        # Stops polling and closes the Modbus connections.
        controller.terminate()

    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_migrate_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug("Migrating from version %s", entry.version)

    return True
