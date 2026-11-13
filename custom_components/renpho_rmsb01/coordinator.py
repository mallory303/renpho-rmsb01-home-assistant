"""Advertisement-driven measurements and explicit stored-user administration."""

import asyncio
import hashlib
import logging
import time
from typing import Any, cast

from bleak import BleakError
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.active_update_coordinator import (
    ActiveBluetoothDataUpdateCoordinator,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_ADDRESS,
    CONF_AGE,
    CONF_GENDER,
    CONF_HEIGHT,
    CONF_PROFILE_ID,
    CONF_PROFILE_NAME,
    CONF_SCALE_USER_INDEX,
    CONF_SCALE_USER_KEY,
    DOMAIN,
    RETRY_COOLDOWN,
    SUCCESS_COOLDOWN,
)
from .profiles import (
    active_profile,
    is_auto_mode,
    profile_for_scale_user,
    profile_needs_sync,
)
from .session import RenphoSession
from .user_admin import RenphoUserAdmin
from .util import is_rmsb01, uses_resistance_encryption

_LOGGER = logging.getLogger(__name__)


class RenphoCoordinator(ActiveBluetoothDataUpdateCoordinator):
    """Connect for measurements, or for one explicit user-admin operation."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._last_attempt = 0.0
        self._last_success = 0.0
        self._session: RenphoSession | None = None
        self._admin: RenphoUserAdmin | None = None
        self._session_lock = asyncio.Lock()
        self.profile_measurements: dict[str, dict[str, Any]] = {}
        self.viewed_profile_id = active_profile(entry)[CONF_PROFILE_ID]
        super().__init__(
            hass,
            _LOGGER,
            address=entry.data[CONF_ADDRESS].upper(),
            mode=bluetooth.BluetoothScanningMode.ACTIVE,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_measure,
            connectable=True,
        )

    def _needs_poll(self, service_info, last_poll: float | None) -> bool:
        """Suppress duplicate advertisements, retries, and admin/measurement collisions."""
        if (
            self._session is not None
            or self._admin is not None
            or self._session_lock.locked()
            or not is_rmsb01(service_info)
        ):
            return False
        now = time.monotonic()
        if now - self._last_attempt < RETRY_COOLDOWN:
            return False
        if self.data is not None and now - self._last_success < SUCCESS_COOLDOWN:
            return False
        return last_poll is None or last_poll >= RETRY_COOLDOWN

    async def _async_measure(self, service_info) -> dict:
        """Run one session; never override the base class's no-argument _async_poll."""
        async with self._session_lock:
            if service_info.connectable:
                ble_device = service_info.device
            else:
                ble_device = bluetooth.async_ble_device_from_address(
                    self.hass, service_info.device.address, connectable=True
                )
            if ble_device is None:
                raise BleakError("No connectable Bluetooth adapter can reach the scale")
            self._last_attempt = time.monotonic()
            profile = active_profile(self.entry)
            automatic = is_auto_mode(self.entry)
            self._session = RenphoSession(
                ble_device,
                age=profile[CONF_AGE],
                height=profile[CONF_HEIGHT],
                male=profile[CONF_GENDER] == "male",
                resistance_encrypted=uses_resistance_encryption(service_info),
                auto=automatic,
            )
            try:
                result = await self._session.measure()
                self._classify_result(result, automatic)
                self._last_success = time.monotonic()
                return result
            finally:
                self._session = None
                bluetooth.async_clear_advertisement_history(self.hass, self.address)

    def _classify_result(self, result: dict[str, Any], automatic: bool) -> None:
        """Attach only explicit slot mappings; unknown users never alter history."""
        if automatic:
            user_index = result["metadata"]["user_index"]
            profile = profile_for_scale_user(self.entry, user_index)
            result["identified"] = profile is not None
        else:
            profile = active_profile(self.entry)
            result["identified"] = True
        if profile is None:
            result["profile"] = None
            result["profile_id"] = None
            _LOGGER.warning(
                "R-MSB01 measurement from unassigned scale user slot %s; "
                "no per-person history was updated",
                result["metadata"]["user_index"],
            )
            self.hass.bus.async_fire(
                f"{DOMAIN}_unassigned_measurement",
                {
                    "entry_id": self.entry.entry_id,
                    "user_index": result["metadata"]["user_index"],
                },
            )
            return
        result["profile"] = profile[CONF_PROFILE_NAME]
        result["profile_id"] = profile[CONF_PROFILE_ID]
        self.profile_measurements[profile[CONF_PROFILE_ID]] = result
        _LOGGER.info(
            "R-MSB01 measurement for %s: %.2f kg, BMI %.1f, body fat %.1f%%",
            profile[CONF_PROFILE_NAME],
            result["metrics"]["weight_kg"],
            result["metrics"]["bmi"],
            result["metrics"]["bodyfat_percent"],
        )

    async def _run_admin(
        self, operation: str, ble_device: Any, profile: dict[str, Any] | None = None
    ) -> Any:
        kwargs: dict[str, Any] = {}
        if profile is not None:
            kwargs = {
                "age": profile[CONF_AGE],
                "height": profile[CONF_HEIGHT],
                "male": profile[CONF_GENDER] == "male",
                "user_key": profile.get(CONF_SCALE_USER_KEY),
                "user_index": profile.get(CONF_SCALE_USER_INDEX),
            }
        self._admin = RenphoUserAdmin(ble_device, operation, **kwargs)
        try:
            return await self._admin.run()
        finally:
            self._admin = None

    def _new_user_key(self, profile: dict[str, Any], occupied: set[int]) -> int:
        digest = hashlib.sha256(
            f"{self.entry.entry_id}:{profile[CONF_PROFILE_ID]}".encode()
        ).digest()
        start = int.from_bytes(digest[:2], "big") % 65535 + 1
        for offset in range(65535):
            key = (start - 1 + offset) % 65535 + 1
            if key != 0xFFEE and key not in occupied:
                return key
        raise BleakError("No unique scale-user key is available")

    async def async_register_profile(self, profile: dict[str, Any]) -> dict[str, int]:
        """Read first, then reuse/sync a mapping or allocate a free scale slot."""
        ble_device = bluetooth.async_ble_device_from_address(
            self.hass, self.entry.data[CONF_ADDRESS], connectable=True
        )
        if ble_device is None:
            raise BleakError("Wake the scale beside Home Assistant, then retry")
        async with self._session_lock:
            self._last_attempt = time.monotonic()
            try:
                users = await self._run_admin("read", ble_device)
                by_index = {user["user_index"]: user for user in users}
                occupied = {user["user_key"] for user in users}
                old_index = profile.get(CONF_SCALE_USER_INDEX)
                old_key = profile.get(CONF_SCALE_USER_KEY)
                if old_index is not None or old_key is not None:
                    existing = by_index.get(old_index)
                    if (
                        old_index not in range(1, 9)
                        or old_key is None
                        or existing is None
                        or existing["user_key"] != old_key
                    ):
                        raise BleakError(
                            "Stored HA slot/key mapping does not match the scale; no changes made"
                        )
                    if profile_needs_sync(profile):
                        await self._run_admin("sync", ble_device, profile)
                    return {
                        CONF_SCALE_USER_INDEX: cast(int, old_index),
                        CONF_SCALE_USER_KEY: cast(int, old_key),
                    }

                candidate = dict(profile)
                candidate[CONF_SCALE_USER_KEY] = self._new_user_key(profile, set())
                # Recover only an exact key+demographics match from an earlier HA
                # enrollment. Similar bodies or equal weights are not identity proof.
                existing = next(
                    (
                        user
                        for user in users
                        if user["user_key"] == candidate[CONF_SCALE_USER_KEY]
                        and all(user[key] == candidate[key] for key in (CONF_AGE, CONF_HEIGHT, CONF_GENDER))
                    ),
                    None,
                )
                if existing is not None:
                    return {
                        CONF_SCALE_USER_INDEX: existing["user_index"],
                        CONF_SCALE_USER_KEY: existing["user_key"],
                    }
                candidate[CONF_SCALE_USER_KEY] = self._new_user_key(profile, occupied)
                if len(users) >= 8:
                    raise BleakError("All eight scale-user slots are occupied; no changes made")
                result = await self._run_admin("register", ble_device, candidate)
                return {
                    CONF_SCALE_USER_INDEX: result["user_index"],
                    CONF_SCALE_USER_KEY: result["user_key"],
                }
            finally:
                self._last_attempt = time.monotonic()
                bluetooth.async_clear_advertisement_history(self.hass, self.address)

    async def async_close(self) -> None:
        """Disconnect promptly when the entry is unloaded."""
        if self._session is not None:
            await self._session.close()
        if self._admin is not None:
            await self._admin.close()
