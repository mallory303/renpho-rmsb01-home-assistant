"""Advertisement-driven Bluetooth coordinator."""

import logging
import time

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
    DEFAULT_AGE,
    DEFAULT_GENDER,
    DEFAULT_HEIGHT,
    RETRY_COOLDOWN,
    SUCCESS_COOLDOWN,
)
from .session import RenphoSession
from .util import is_rmsb01, uses_resistance_encryption

_LOGGER = logging.getLogger(__name__)


class RenphoCoordinator(ActiveBluetoothDataUpdateCoordinator):
    """Connect only when the scale advertises a new measurement session."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.entry = entry
        self._last_attempt = 0.0
        self._last_success = 0.0
        self._session: RenphoSession | None = None
        super().__init__(
            hass,
            _LOGGER,
            address=entry.data[CONF_ADDRESS].upper(),
            mode=bluetooth.BluetoothScanningMode.ACTIVE,
            needs_poll_method=self._needs_poll,
            poll_method=self._async_poll,
            connectable=True,
        )

    def _profile(self) -> dict:
        values = {**self.entry.data, **self.entry.options}
        return {
            "age": values.get(CONF_AGE, DEFAULT_AGE),
            "height": values.get(CONF_HEIGHT, DEFAULT_HEIGHT),
            "male": values.get(CONF_GENDER, DEFAULT_GENDER) == "male",
        }

    def _needs_poll(self, service_info, last_poll: float | None) -> bool:
        """Suppress duplicate advertisements and immediate retry loops."""
        if self._session is not None or not is_rmsb01(service_info):
            return False
        now = time.monotonic()
        if now - self._last_attempt < RETRY_COOLDOWN:
            return False
        if self.data is not None and now - self._last_success < SUCCESS_COOLDOWN:
            return False
        return last_poll is None or last_poll >= RETRY_COOLDOWN

    async def _async_poll(self, service_info) -> dict:
        """Run one real VA/TN session without discarding prior data on failure."""
        if service_info.connectable:
            ble_device = service_info.device
        else:
            ble_device = bluetooth.async_ble_device_from_address(
                self.hass, service_info.device.address, connectable=True
            )
        if ble_device is None:
            raise BleakError("No connectable Bluetooth adapter can reach the scale")
        self._last_attempt = time.monotonic()
        self._session = RenphoSession(
            ble_device,
            **self._profile(),
            resistance_encrypted=uses_resistance_encryption(service_info),
        )
        try:
            result = await self._session.measure()
            self._last_success = time.monotonic()
            _LOGGER.info(
                "R-MSB01 measurement: %.2f kg, BMI %.1f, body fat %.1f%%",
                result["metrics"]["weight_kg"],
                result["metrics"]["bmi"],
                result["metrics"]["bodyfat_percent"],
            )
            return result
        finally:
            self._session = None
            bluetooth.async_clear_advertisement_history(self.hass, self.address)

    async def async_close(self) -> None:
        """Disconnect promptly when the entry is unloaded."""
        if self._session is not None:
            await self._session.close()
