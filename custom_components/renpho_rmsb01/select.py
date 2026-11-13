"""Measurement-mode and independent dashboard-view selectors."""

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo

from .const import (
    AUTO_PROFILE,
    CONF_ADDRESS,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_SCALE_USER_INDEX,
    DOMAIN,
)
from .entity_ids import entity_unique_id
from .profiles import get_profiles, profile_needs_sync, profile_options, selected_name


def _device_info(entry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        connections={(CONNECTION_BLUETOOTH, entry.data[CONF_ADDRESS])},
        manufacturer="Renpho",
        model="R-MSB01",
        name=entry.title,
    )


class RenphoUserSelect(SelectEntity):
    """Choose native Auto or a forced visitor profile in HA config options."""

    _attr_has_entity_name = True
    _attr_translation_key = "active_profile"

    def __init__(self, entry) -> None:
        self.entry = entry
        self._attr_unique_id = entity_unique_id(entry, "active_profile")
        self._attr_device_info = _device_info(entry)

    @property
    def options(self) -> list[str]:
        return [AUTO_PROFILE, *(p[CONF_PROFILE_NAME] for p in get_profiles(self.entry))]

    @property
    def current_option(self) -> str:
        return selected_name(self.entry)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        profiles = get_profiles(self.entry)
        return {
            "enrolled_slots": {
                profile[CONF_PROFILE_NAME]: profile[CONF_SCALE_USER_INDEX]
                for profile in profiles
                if CONF_SCALE_USER_INDEX in profile
            },
            "profiles_needing_sync": [
                profile[CONF_PROFILE_NAME] for profile in profiles if profile_needs_sync(profile)
            ],
        }

    async def async_select_option(self, option: str) -> None:
        """Persist Auto or a manual profile; no stored scale user is changed."""
        if option not in self.options:
            raise HomeAssistantError(f"Unknown Renpho measurement mode: {option}")
        self.hass.config_entries.async_update_entry(
            self.entry,
            options=profile_options(get_profiles(self.entry), option),
        )


class RenphoViewSelect(SelectEntity):
    """Select whose per-person entities the card displays, without GATT activity."""

    _attr_has_entity_name = True
    _attr_translation_key = "viewed_profile"

    def __init__(self, coordinator) -> None:
        self.coordinator = coordinator
        self.entry = coordinator.entry
        self._attr_unique_id = entity_unique_id(self.entry, "viewed_profile")
        self._attr_device_info = _device_info(self.entry)

    @property
    def options(self) -> list[str]:
        return [profile[CONF_PROFILE_NAME] for profile in get_profiles(self.entry)]

    @property
    def current_option(self) -> str:
        return next(
            (
                profile[CONF_PROFILE_NAME]
                for profile in get_profiles(self.entry)
                if profile[CONF_PROFILE_ID] == self.coordinator.viewed_profile_id
            ),
            self.options[0],
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Resolve actual entity IDs from the registry, including user renames."""
        from .sensor import CARD_SENSOR_KEYS, SENSORS  # Avoid a platform import cycle.

        registry = er.async_get(self.hass)
        mapping = {}
        for profile in get_profiles(self.entry):
            entities = {}
            for description in SENSORS:
                unique_id = entity_unique_id(
                    self.entry, f"{profile[CONF_PROFILE_ID]}_{description.key}"
                )
                entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)
                if entity_id is not None:
                    entities[CARD_SENSOR_KEYS[description.key]] = entity_id
            mapping[profile[CONF_PROFILE_NAME]] = entities
        return {"profile_entities": mapping}

    async def async_select_option(self, option: str) -> None:
        """Change only the in-memory dashboard view; do not reload the config entry."""
        profile = next(
            (p for p in get_profiles(self.entry) if p[CONF_PROFILE_NAME] == option),
            None,
        )
        if profile is None:
            raise HomeAssistantError(f"Unknown Renpho viewed profile: {option}")
        self.coordinator.viewed_profile_id = profile[CONF_PROFILE_ID]
        self.async_write_ha_state()


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    async_add_entities([RenphoUserSelect(entry), RenphoViewSelect(coordinator)])
