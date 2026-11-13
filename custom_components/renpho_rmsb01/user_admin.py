"""Bounded, explicit R-MSB01 stored-user read and free-slot registration."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Any

from bleak import BleakClient, BleakError
from bleak_retry_connector import establish_connection

from .const import CONNECTION_TIMEOUT, FFF1, FFF2, FFF3
from .session import checksum_packet, scale_config_packet, time_sync_packet, user_packet

_LOGGER = logging.getLogger(__name__)
ADMIN_TIMEOUT = 35


def read_users_packet() -> bytes:
    """Request slots 1-8; 0xA6 has a slot mask instead of a device type."""
    return checksum_packet(0xA6, device_type=0xFF)


def parse_scale_user(data: bytes) -> dict[str, Any]:
    """Decode one 0xA7 stored-user record without assuming any live identity."""
    if len(data) < 15 or data[0] != 0xA7:
        raise ValueError("Malformed stored-user response")
    return {
        "user_index": data[3],
        "user_key": (data[4] << 8) | data[5],
        "age": data[7],
        "height": ((data[8] << 8) | data[9]) / 10,
        "gender": "female" if data[6] else "male",
        "algorithm": data[10],
        "last_weight_kg": ((data[13] << 8) | data[14]) / 100,
    }


class RenphoUserAdmin:
    """Read stored users or register one profile into a scale-assigned free slot."""

    def __init__(
        self,
        ble_device: Any,
        operation: str,
        *,
        age: int | None = None,
        height: int | None = None,
        male: bool | None = None,
        user_key: int | None = None,
        user_index: int | None = None,
    ) -> None:
        if operation not in ("read", "register", "sync"):
            raise ValueError("Only read, register, and sync operations are supported")
        if operation in ("register", "sync") and (
            age is None
            or height is None
            or male is None
            or user_key is None
            or not 1 <= user_key <= 0xFFFF
            or user_key == 0xFFEE
        ):
            raise ValueError("A complete profile and unique non-visitor key are required")
        if operation == "sync" and (user_index is None or not 1 <= user_index <= 8):
            raise ValueError("Sync requires the existing scale user slot")
        self._ble_device = ble_device
        self._operation = operation
        self._age = age
        self._height = height
        self._male = male
        self._user_key = user_key
        self._user_index = user_index
        self._client = None
        self._disconnected = asyncio.Event()
        self._complete = asyncio.Event()
        self._write_lock = asyncio.Lock()
        self._write_tasks: set[asyncio.Task] = set()
        self._device_type: int | None = None
        self._config_sent = False
        self._time_sent = False
        self._operation_sent = False
        self._registered_index: int | None = None
        self._users: dict[int, dict[str, Any]] = {}
        self._capabilities: dict[str, Any] = {}
        self._result: Any = None
        self._error: str | None = None

    async def run(self) -> Any:
        """Execute only the constructed operation and always disconnect afterward."""
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
                timeout=ADMIN_TIMEOUT,
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not done:
                raise BleakError(f"Timed out during scale-user {self._operation}")
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
            raise BleakError(self._error or "Scale disconnected during user administration")
        return self._result

    async def close(self) -> None:
        """Abort an active admin operation during integration unload."""
        self._fail("Scale-user administration cancelled")
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

    def _user_packet(self, action: int, index: int) -> bytes:
        assert self._age is not None and self._height is not None
        assert self._male is not None and self._user_key is not None
        return user_packet(
            self._age,
            self._height,
            self._male,
            action=action,
            user_index=index,
            user_key=self._user_key,
        )

    def _on_notify(self, _characteristic, data) -> None:
        data = bytes(data)
        if not data:
            return
        command = data[0]
        try:
            if command == 0x12 and len(data) >= 18 and not self._config_sent:
                self._config_sent = True
                self._device_type = data[2]
                self._capabilities = {
                    "device_type": self._device_type,
                    "stored_user_info": bool(data[17] & 0x80),
                    "identify_weight": bool(data[16] & 0x20),
                }
                self._schedule_send(scale_config_packet(self._device_type))
            elif command == 0x14 and not self._time_sent:
                if len(data) <= 5 or data[5] != 1:
                    self._fail("Scale rejected its configuration")
                    return
                self._time_sent = True
                assert self._device_type is not None
                self._schedule_send(
                    time_sync_packet(self._device_type, int(datetime.now(UTC).timestamp()))
                )
            elif command == 0x21 and not self._operation_sent:
                if len(data) <= 3 or data[3] != 1:
                    self._fail("Scale rejected time synchronization")
                    return
                self._operation_sent = True
                if self._operation == "read":
                    self._schedule_send(read_users_packet())
                elif self._operation == "sync":
                    assert self._user_index is not None
                    self._schedule_send(self._user_packet(action=2, index=self._user_index))
                else:
                    # Action 1 asks the scale to allocate a free slot; never name
                    # an occupied slot for registration and never delete a user.
                    self._schedule_send(self._user_packet(action=1, index=0))
            elif command == 0xA7 and self._operation == "read":
                expected = (data[2] & 0xFF).bit_count() if len(data) > 2 else 0
                if expected and len(data) < 15:
                    self._fail("Malformed stored-user response")
                    return
                if expected:
                    user = parse_scale_user(data)
                    if not 1 <= user["user_index"] <= 8:
                        self._fail("Scale returned an invalid stored-user slot")
                        return
                    self._users[user["user_index"]] = user
                if len(self._users) == expected:
                    self._result = [self._users[index] for index in sorted(self._users)]
                    self._complete.set()
            elif command == 0xA1 and self._operation in ("register", "sync"):
                self._handle_user_reply(data)
        except Exception as exc:
            _LOGGER.debug("R-MSB01 user-admin packet handling failed", exc_info=True)
            self._fail(str(exc))

    def _handle_user_reply(self, data: bytes) -> None:
        if len(data) <= 4:
            self._fail("Malformed user-registration response")
            return
        action, index, result = data[2], data[3], data[4]
        if self._operation == "sync":
            if action != 2 or result != 1 or index != self._user_index:
                self._fail("Scale rejected the existing-user profile sync")
                return
            self._result = {
                "user_index": index,
                "user_key": self._user_key,
                "capabilities": dict(self._capabilities),
            }
            self._complete.set()
            return
        if action == 1:
            if self._registered_index is not None:
                if result == 1 and index == self._registered_index:
                    return  # Ignore a duplicate notification on another characteristic.
                self._fail("Scale returned conflicting registration responses")
                return
            if result != 1 or not 1 <= index <= 8:
                self._fail("Scale rejected registration or has no free user slot")
                return
            self._registered_index = index
            # The vendor flow visits the newly assigned slot with the same key.
            self._schedule_send(self._user_packet(action=2, index=index))
            return
        if (
            action != 2
            or result != 1
            or self._registered_index is None
            or index != self._registered_index
        ):
            self._fail("Scale rejected the newly registered user")
            return
        self._result = {
            "user_index": index,
            "user_key": self._user_key,
            "capabilities": dict(self._capabilities),
        }
        self._complete.set()
