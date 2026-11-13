"""Live VA/TN GATT session for the Renpho R-MSB01."""

import asyncio
import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection

from .const import (
    ALGORITHM,
    CONNECTION_TIMEOUT,
    FFF1,
    FFF2,
    FFF3,
    SESSION_TIMEOUT,
)
from .decoder import decode_tn_packets

_LOGGER = logging.getLogger(__name__)


def checksum_packet(command: int, payload: Sequence[int] = b"", device_type: int = 0) -> bytes:
    """Build the additive-checksum VA command frame."""
    body = bytes([command, len(payload) + 4, device_type]) + bytes(payload)
    return body + bytes([sum(body) & 0xFF])


def scale_config_packet(device_type: int) -> bytes:
    """Select kg and the standard display timeout."""
    return checksum_packet(0x13, [1, 16, 0, 0, 0], device_type)


def time_sync_packet(device_type: int, now: int) -> bytes:
    """Encode seconds since 2000-01-01 UTC."""
    seconds = now - 946684800
    return checksum_packet(0x20, (seconds & 0xFFFFFFFF).to_bytes(4, "little"), device_type)


def user_packet(
    age: int,
    height_cm: int,
    male: bool,
    *,
    action: int,
    user_index: int,
    user_key: int,
) -> bytes:
    """Build a VA registration/visit packet; callers choose the explicit operation."""
    if action not in (1, 2):
        raise ValueError("Only register (1) and visit (2) are supported")
    if not 0 <= user_index <= 254 or not 0 <= user_key <= 0xFFFF:
        raise ValueError("Invalid scale user index or key")
    height = max(40, min(240, int(height_cm))) * 10
    payload = [
        user_index,
        user_key >> 8,
        user_key & 0xFF,
        0 if male else 1,
        int(age),
        height >> 8,
        height & 0xFF,
        ALGORITHM,
        0,
    ]
    # Unlike most VA commands, 0xA0's byte after length is the action.
    return checksum_packet(0xA0, payload, action)


def visitor_packet(age: int, height_cm: int, male: bool) -> bytes:
    """Select visitor 254 without modifying stored scale users."""
    return user_packet(
        age,
        height_cm,
        male,
        action=2,
        user_index=254,
        user_key=0xFFEE,
    )


class RenphoSession:
    """Perform one bounded connection/handshake/measurement session."""

    def __init__(
        self,
        ble_device: Any,
        *,
        age: int,
        height: int,
        male: bool,
        resistance_encrypted: bool = False,
        auto: bool = False,
    ) -> None:
        self._ble_device = ble_device
        self._age = age
        self._height = height
        self._male = male
        self._auto = auto
        self._resistance_encrypted = resistance_encrypted
        self._client = None
        self._disconnected = asyncio.Event()
        self._complete = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._write_tasks: set[asyncio.Task] = set()
        self._device_type = None
        self._weight_ratio = 0.1
        self._support_heart = False
        self._value_type = None
        self._config_sent = False
        self._time_sent = False
        self._visitor_sent = False
        self._packets: dict[int, bytes] = {}
        self._capabilities: dict[str, Any] = {}
        self._result: dict[str, Any] | None = None
        self._error: str | None = None

    async def measure(self) -> dict[str, Any]:
        """Connect and return one complete measurement, or raise BleakError."""
        self._client = await establish_connection(
            BleakClient,
            self._ble_device,
            getattr(self._ble_device, "address", "Renpho R-MSB01"),
            disconnected_callback=self._on_disconnect,
            max_attempts=3,
            use_services_cache=False,
            timeout=CONNECTION_TIMEOUT,
        )
        complete_wait = None
        disconnect_wait = None
        try:
            await self._client.start_notify(FFF1, self._on_notify)
            await self._client.start_notify(FFF3, self._on_notify)
            complete_wait = asyncio.create_task(self._complete.wait())
            disconnect_wait = asyncio.create_task(self._disconnected.wait())
            done, _ = await asyncio.wait(
                {complete_wait, disconnect_wait},
                timeout=SESSION_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise BleakError("Timed out waiting for a complete R-MSB01 measurement")
            await self._flush_writes()
        finally:
            for task in (complete_wait, disconnect_wait):
                if task is not None:
                    task.cancel()
            if self._client is not None:
                try:
                    if self._client.is_connected:
                        await self._client.disconnect()
                finally:
                    self._client = None
        if self._result is None:
            raise BleakError(self._error or "Scale disconnected before sending a complete measurement")
        return self._result

    async def close(self) -> None:
        """Abort an active session during integration unload."""
        self._fail("Measurement session cancelled")
        if self._client is not None and self._client.is_connected:
            await self._client.disconnect()

    def _on_disconnect(self, _client) -> None:
        self._disconnected.set()

    def _fail(self, message: str) -> None:
        self._error = message
        self._complete.set()

    def _schedule_send(self, packet: bytes) -> None:
        task = asyncio.create_task(self._send(packet))
        self._write_tasks.add(task)
        task.add_done_callback(self._write_done)

    def _write_done(self, task: asyncio.Task) -> None:
        self._write_tasks.discard(task)
        if task.cancelled():
            return
        if (exc := task.exception()) is not None:
            self._fail(f"GATT write failed: {exc}")

    async def _flush_writes(self) -> None:
        while self._write_tasks:
            await asyncio.gather(*tuple(self._write_tasks), return_exceptions=True)

    async def _send(self, packet: bytes) -> None:
        if self._client is None:
            raise BleakError("GATT client is not connected")
        async with self._write_lock:
            await self._client.write_gatt_char(FFF2, packet, response=True)

    def _on_notify(self, characteristic, data) -> None:
        data = bytes(data)
        if not data:
            return
        command = data[0]
        try:
            if command in (0x10, 0x15, 0x16):
                self._packets[command] = data
                self._decode_if_complete()
            elif command == 0x12 and len(data) >= 18 and not self._config_sent:
                self._config_sent = True
                self._device_type = data[2]
                flags = data[10]
                self._weight_ratio = 0.01 if flags & 1 else 0.1
                self._support_heart = bool(flags & 0x20)
                self._capabilities = {
                    "device_type": self._device_type,
                    "scale_version": data[9],
                    "ble_version": data[11],
                    "weight_ratio": self._weight_ratio,
                    "support_heart": self._support_heart,
                    "stored_user_info": bool(data[17] & 0x80),
                    "identify_weight": bool(data[16] & 0x20),
                }
                self._schedule_send(scale_config_packet(self._device_type))
            elif command == 0x14 and not self._time_sent:
                if len(data) <= 5 or data[5] != 1:
                    self._fail("Scale rejected its configuration")
                    return
                self._time_sent = True
                self._value_type = data[3] & 1
                self._capabilities["value_type"] = self._value_type
                assert self._device_type is not None
                self._schedule_send(time_sync_packet(self._device_type, int(datetime.now(UTC).timestamp())))
            elif command == 0x21 and not self._visitor_sent:
                if len(data) <= 3 or data[3] != 1:
                    self._fail("Scale rejected time synchronization")
                    return
                self._visitor_sent = True
                if not self._auto:
                    self._schedule_send(visitor_packet(self._age, self._height, self._male))
            elif command == 0xA1 and not self._auto:
                if len(data) <= 4 or data[2:5] != bytes([2, 254, 1]):
                    self._fail("Scale rejected the synthetic visitor")
                    return
                self._capabilities["visitor_accepted"] = True
        except Exception as exc:  # Decode errors must terminate the wait cleanly.
            _LOGGER.debug("R-MSB01 packet handling failed", exc_info=True)
            self._fail(str(exc))

    def _decode_if_complete(self) -> None:
        if self._result is not None or not {0x10, 0x15, 0x16}.issubset(self._packets):
            return
        packets = [self._packets[code] for code in (0x10, 0x15, 0x16)]
        decoded = decode_tn_packets(
            packets,
            weight_ratio=self._weight_ratio,
            percentage_mass=self._value_type == 1,
            support_heart=self._support_heart,
            resistance_encrypted=self._resistance_encrypted,
        )
        self._result = {
            "metrics": decoded["metrics"],
            "metadata": decoded["metadata"],
            "masked_out": decoded["decoded_but_masked_out"],
            "raw_packets": {f"0x{code:02x}": packet.hex() for code, packet in zip((0x10, 0x15, 0x16), packets)},
            "capabilities": self._capabilities,
            "automatic": self._auto,
            "measured_at": datetime.now(UTC).isoformat(),
        }
        assert self._device_type is not None
        self._schedule_send(checksum_packet(0x1F, [16], self._device_type))
        self._complete.set()
