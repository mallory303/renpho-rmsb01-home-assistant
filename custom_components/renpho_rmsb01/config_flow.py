"""Config flow for Renpho R-MSB01."""

import re
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.bluetooth import BluetoothServiceInfoBleak
from homeassistant.core import callback

from .const import (
    CONF_ADDRESS,
    CONF_AGE,
    CONF_GENDER,
    CONF_HEIGHT,
    CONF_NAME,
    DEFAULT_AGE,
    DEFAULT_GENDER,
    DEFAULT_HEIGHT,
    DEFAULT_NAME,
    DOMAIN,
)
from .util import is_rmsb01, normalized_address

ADDRESS_RE = re.compile(r"^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$")


def _profile_schema(values: dict[str, Any] | None = None) -> vol.Schema:
    values = values or {}
    return vol.Schema({
        vol.Required(CONF_AGE, default=values.get(CONF_AGE, DEFAULT_AGE)):
            vol.All(vol.Coerce(int), vol.Range(min=10, max=100)),
        vol.Required(CONF_HEIGHT, default=values.get(CONF_HEIGHT, DEFAULT_HEIGHT)):
            vol.All(vol.Coerce(int), vol.Range(min=100, max=230)),
        vol.Required(CONF_GENDER, default=values.get(CONF_GENDER, DEFAULT_GENDER)):
            vol.In(("male", "female")),
    })


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
        """Collect the profile used for visitor measurements."""
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
        """Return the profile options flow."""
        return RenphoOptionsFlow()


class RenphoOptionsFlow(config_entries.OptionsFlow):
    """Edit the visitor profile without changing the Bluetooth address."""

    async def async_step_init(self, user_input=None):
        """Show and save profile options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        values = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_profile_schema(values))
