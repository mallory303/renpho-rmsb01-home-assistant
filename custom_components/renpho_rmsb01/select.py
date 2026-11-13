"""Select the HA-side profile used for the next visitor measurement."""

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr

from .const import CONF_ADDRESS, CONF_PROFILE_NAME, DOMAIN, MODEL
from .profiles import active_profile, get_profiles, profile_options


async def async_setup_entry(hass, entry, async_add_entities) -> None:
    """Create the active-user selector."""
    async_add_entities([RenphoUserSelect(entry)])


class RenphoUserSelect(SelectEntity):
    """A user selector backed by config-entry options."""

    _attr_has_entity_name = True
    _attr_translation_key = "active_profile"
    _attr_icon = "mdi:account-switch"

    def __init__(self, entry) -> None:
        self._entry = entry
        address = entry.data[CONF_ADDRESS].upper()
        self._attr_unique_id = f"{address.replace(':', '')}_active_profile"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, address)},
            "connections": {(dr.CONNECTION_BLUETOOTH, address)},
            "name": entry.title,
            "manufacturer": "Renpho",
            "model": MODEL,
        }

    @property
    def options(self) -> list[str]:
        """Read names live so profile edits appear without recreating the entity."""
        return [profile[CONF_PROFILE_NAME] for profile in get_profiles(self._entry)]

    @property
    def current_option(self) -> str:
        """Return the user that will be sent with the next measurement."""
        return active_profile(self._entry)[CONF_PROFILE_NAME]

    async def async_select_option(self, option: str) -> None:
        """Persist the selection and reload the coordinator with the new profile."""
        profiles = get_profiles(self._entry)
        if option not in [profile[CONF_PROFILE_NAME] for profile in profiles]:
            raise HomeAssistantError(f"Unknown Renpho profile: {option}")
        self.hass.config_entries.async_update_entry(
            self._entry,
            options=profile_options(profiles, option),
        )
