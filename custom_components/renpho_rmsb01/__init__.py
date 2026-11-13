"""Renpho R-MSB01 Home Assistant integration."""

import logging

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_ADDRESS
from .coordinator import RenphoCoordinator
from .entity_ids import migrate_entity_unique_ids
from .frontend import async_setup_card

_LOGGER = logging.getLogger(__name__)

PLATFORMS = [Platform.SENSOR, Platform.SELECT]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up a configured scale."""
    coordinator = RenphoCoordinator(hass, entry)
    entry.runtime_data = coordinator
    try:
        await async_setup_card(hass)
    except Exception:
        _LOGGER.exception("Could not set up the optional Renpho Lovelace card")
    migrate_entity_unique_ids(hass, entry)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(coordinator.async_start())
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    return True


async def _async_options_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload profile options while retaining the latest in-memory measurements."""
    previous_data = entry.runtime_data.data
    previous_profiles = dict(entry.runtime_data.profile_measurements)
    previous_view = entry.runtime_data.viewed_profile_id
    await hass.config_entries.async_reload(entry.entry_id)
    if entry.state is ConfigEntryState.LOADED:
        entry.runtime_data.profile_measurements = previous_profiles
        entry.runtime_data.viewed_profile_id = previous_view
        if previous_data is not None:
            entry.runtime_data.async_set_updated_data(previous_data)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the scale and close any active GATT session."""
    await entry.runtime_data.async_close()
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Allow the removed address to trigger discovery again."""
    from homeassistant.components import bluetooth

    bluetooth.async_rediscover_address(hass, entry.data[CONF_ADDRESS])
