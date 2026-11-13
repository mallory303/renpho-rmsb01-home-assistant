"""Config flow, HA profiles, and explicit scale-user enrollment."""

import logging
import re
from typing import Any
from uuid import uuid4

import voluptuous as vol
from bleak import BleakError
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import callback

from .const import (
    AUTO_PROFILE,
    CONF_ACTIVE_PROFILE,
    CONF_ADDRESS,
    CONF_AGE,
    CONF_GENDER,
    CONF_HEIGHT,
    CONF_NAME,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_SCALE_PROFILE,
    CONF_SCALE_USER_INDEX,
    CONF_SCALE_USER_KEY,
    DEFAULT_AGE,
    DEFAULT_GENDER,
    DEFAULT_HEIGHT,
    DEFAULT_NAME,
    DEFAULT_PROFILE_NAME,
    DOMAIN,
)
from .profiles import get_profiles, profile_options, selected_name
from .util import is_rmsb01, normalized_address

ADDRESS_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")
_LOGGER = logging.getLogger(__name__)


def _profile_schema(values: dict[str, Any] | None = None) -> vol.Schema:
    values = values or {}
    return vol.Schema({
        vol.Required(
            CONF_PROFILE_NAME,
            default=values.get(CONF_PROFILE_NAME, DEFAULT_PROFILE_NAME),
        ): vol.All(str, vol.Length(min=1, max=40)),
        vol.Required(CONF_AGE, default=values.get(CONF_AGE, DEFAULT_AGE)):
            vol.All(vol.Coerce(int), vol.Range(min=10, max=100)),
        vol.Required(CONF_HEIGHT, default=values.get(CONF_HEIGHT, DEFAULT_HEIGHT)):
            vol.All(vol.Coerce(int), vol.Range(min=100, max=230)),
        vol.Required(CONF_GENDER, default=values.get(CONF_GENDER, DEFAULT_GENDER)):
            vol.In(("male", "female")),
    })


def _clean_profile(
    user_input: dict[str, Any], original: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Normalize demographics and preserve stable identity/enrollment metadata."""
    profile = {
        CONF_PROFILE_NAME: user_input[CONF_PROFILE_NAME].strip(),
        CONF_AGE: user_input[CONF_AGE],
        CONF_HEIGHT: user_input[CONF_HEIGHT],
        CONF_GENDER: user_input[CONF_GENDER],
        CONF_PROFILE_ID: (
            original.get(CONF_PROFILE_ID) if original is not None else uuid4().hex[:12]
        ),
    }
    if original is not None:
        for key in (CONF_SCALE_USER_INDEX, CONF_SCALE_USER_KEY, CONF_SCALE_PROFILE):
            if key in original:
                profile[key] = dict(original[key]) if key == CONF_SCALE_PROFILE else original[key]
    return profile


class RenphoConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle manual and Bluetooth-discovered setup."""

    VERSION = 1

    def __init__(self) -> None:
        self._address: str | None = None
        self._discovered_name = DEFAULT_NAME

    async def async_step_user(self, user_input=None):
        """Add an address manually; the scale may be asleep during setup."""
        errors = {}
        if user_input is not None:
            address = user_input[CONF_ADDRESS].strip()
            if not ADDRESS_RE.fullmatch(address):
                errors[CONF_ADDRESS] = "invalid_address"
            else:
                address = normalized_address(address)
                await self.async_set_unique_id(address)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME].strip() or DEFAULT_NAME,
                    data={**user_input, CONF_ADDRESS: address},
                )
        schema = _profile_schema(user_input).extend({
            vol.Required(CONF_NAME, default=(user_input or {}).get(CONF_NAME, DEFAULT_NAME)): str,
            vol.Required(CONF_ADDRESS, default=(user_input or {}).get(CONF_ADDRESS, "")): str,
        })
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    async def async_step_bluetooth(self, discovery_info: BluetoothServiceInfoBleak):
        """Validate and accept an R-MSB01 Bluetooth discovery."""
        if not is_rmsb01(discovery_info):
            return self.async_abort(reason="not_supported")
        self._address = normalized_address(discovery_info.address)
        await self.async_set_unique_id(self._address)
        self._abort_if_unique_id_configured()
        self._discovered_name = f"{DEFAULT_NAME} {self._address[-5:]}"
        self.context["title_placeholders"] = {"name": self._discovered_name}
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(self, user_input=None):
        """Collect the initial profile used for visitor measurements."""
        if user_input is not None:
            return self.async_create_entry(
                title=self._discovered_name,
                data={**user_input, CONF_ADDRESS: self._address, CONF_NAME: self._discovered_name},
            )
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=_profile_schema(),
            description_placeholders={"name": self._discovered_name, "address": self._address or ""},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return the multi-profile options flow."""
        return RenphoOptionsFlow()


class RenphoOptionsFlow(config_entries.OptionsFlow):
    """Manage HA profiles; only the explicit enrollment step writes the scale."""

    def __init__(self) -> None:
        self._editing_name: str | None = None

    def _profiles(self) -> list[dict[str, Any]]:
        return get_profiles(self.config_entry)

    def _active_name(self) -> str:
        return selected_name(self.config_entry)

    def _save(self, profiles: list[dict[str, Any]], selected: str):
        return self.async_create_entry(title="", data=profile_options(profiles, selected))

    def _profile_picker(self, step_id: str, errors=None, placeholders=None):
        names = [profile[CONF_PROFILE_NAME] for profile in self._profiles()]
        selected = self._active_name()
        default = selected if selected in names else names[0]
        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required(CONF_ACTIVE_PROFILE, default=default): vol.In(names),
            }),
            errors=errors or {},
            description_placeholders=placeholders or {},
        )

    async def async_step_init(self, user_input=None):
        """Show profile-management and explicit scale-enrollment actions."""
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "active_profile",
                "add_profile",
                "edit_profile",
                "enroll_profile",
                "delete_profile",
            ],
        )

    async def async_step_active_profile(self, user_input=None):
        """Select native Auto identification or one forced visitor profile."""
        if user_input is not None:
            return self._save(self._profiles(), user_input[CONF_ACTIVE_PROFILE])
        names = [profile[CONF_PROFILE_NAME] for profile in self._profiles()]
        return self.async_show_form(
            step_id="active_profile",
            data_schema=vol.Schema({
                vol.Required(CONF_ACTIVE_PROFILE, default=self._active_name()):
                    vol.In([AUTO_PROFILE, *names]),
            }),
        )

    async def async_step_add_profile(self, user_input=None):
        """Add and activate a new HA-side profile without writing the scale."""
        errors = {}
        if user_input is not None:
            profile = _clean_profile(user_input)
            name = profile[CONF_PROFILE_NAME]
            profiles = self._profiles()
            existing = {p[CONF_PROFILE_NAME].casefold() for p in profiles}
            if not name:
                errors[CONF_PROFILE_NAME] = "name_required"
            elif name.casefold() == AUTO_PROFILE.casefold():
                errors[CONF_PROFILE_NAME] = "reserved_name"
            elif name.casefold() in existing:
                errors[CONF_PROFILE_NAME] = "name_exists"
            else:
                profiles.append(profile)
                return self._save(profiles, name)
        return self.async_show_form(
            step_id="add_profile", data_schema=_profile_schema(user_input), errors=errors
        )

    async def async_step_edit_profile(self, user_input=None):
        """Choose a profile to edit."""
        if user_input is not None:
            self._editing_name = user_input[CONF_ACTIVE_PROFILE]
            return await self.async_step_edit_details()
        return self._profile_picker("edit_profile")

    async def async_step_edit_details(self, user_input=None):
        """Edit a profile while preserving its identity and scale mapping."""
        profiles = self._profiles()
        original = next(
            profile for profile in profiles
            if profile[CONF_PROFILE_NAME] == self._editing_name
        )
        errors = {}
        if user_input is not None:
            replacement = _clean_profile(user_input, original)
            new_name = replacement[CONF_PROFILE_NAME]
            duplicates = {
                profile[CONF_PROFILE_NAME].casefold()
                for profile in profiles if profile is not original
            }
            if not new_name:
                errors[CONF_PROFILE_NAME] = "name_required"
            elif new_name.casefold() == AUTO_PROFILE.casefold():
                errors[CONF_PROFILE_NAME] = "reserved_name"
            elif new_name.casefold() in duplicates:
                errors[CONF_PROFILE_NAME] = "name_exists"
            else:
                profiles[profiles.index(original)] = replacement
                selected = self._active_name()
                return self._save(
                    profiles, new_name if selected == self._editing_name else selected
                )
        return self.async_show_form(
            step_id="edit_details", data_schema=_profile_schema(original), errors=errors
        )

    async def async_step_enroll_profile(self, user_input=None):
        """Read slots first, then explicitly register or sync the chosen profile."""
        errors = {}
        if user_input is not None:
            name = user_input[CONF_ACTIVE_PROFILE]
            profiles = self._profiles()
            profile = next(p for p in profiles if p[CONF_PROFILE_NAME] == name)
            try:
                mapping = await self.config_entry.runtime_data.async_register_profile(profile)
            except (BleakError, TimeoutError) as exc:
                _LOGGER.debug("R-MSB01 profile enrollment failed", exc_info=True)
                errors["base"] = "enroll_failed"
                return self._profile_picker(
                    "enroll_profile", errors, {"error": str(exc)}
                )
            profile.update(mapping)
            profile[CONF_SCALE_PROFILE] = {
                CONF_AGE: profile[CONF_AGE],
                CONF_HEIGHT: profile[CONF_HEIGHT],
                CONF_GENDER: profile[CONF_GENDER],
            }
            return self._save(profiles, AUTO_PROFILE)
        return self._profile_picker("enroll_profile")

    async def async_step_delete_profile(self, user_input=None):
        """Delete only the HA profile; never delete or overwrite a scale user."""
        profiles = self._profiles()
        errors = {}
        if user_input is not None:
            if len(profiles) == 1:
                errors["base"] = "last_profile"
            else:
                removed = user_input[CONF_ACTIVE_PROFILE]
                profiles = [
                    profile for profile in profiles
                    if profile[CONF_PROFILE_NAME] != removed
                ]
                selected = self._active_name()
                if selected == removed:
                    selected = profiles[0][CONF_PROFILE_NAME]
                return self._save(profiles, selected)
        return self._profile_picker("delete_profile", errors)
