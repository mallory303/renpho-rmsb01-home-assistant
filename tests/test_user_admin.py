"""Synthetic tests for bounded scale-user reading and free-slot registration."""

import asyncio
import unittest
from unittest.mock import patch

from bleak import BleakError

from tests.helpers import load_module
from tests.test_session import CONFIG_REPLY, MODEL_REPLY, TIME_REPLY, finish

admin_module = load_module("user_admin")
RenphoUserAdmin = admin_module.RenphoUserAdmin


def user_reply(action: int, index: int, result: int) -> bytes:
    return finish(bytearray([0xA1, 6, action, index, result, 0]))


def stored_user(index: int, key: int, mask: int, weight: int) -> bytes:
    packet = bytearray(16)
    packet[0] = 0xA7
    packet[2] = mask
    packet[3] = index
    packet[4:6] = key.to_bytes(2, "big")
    packet[6] = 1 if index == 3 else 0
    packet[7] = 35 if index == 2 else 40
    packet[8:10] = (1650 if index == 2 else 1800).to_bytes(2, "big")
    packet[10] = 5
    packet[13:15] = weight.to_bytes(2, "big")
    return finish(packet)


class FakeClient:
    def __init__(self, disconnected_callback, operation, register_ok=True) -> None:
        self.is_connected = True
        self.writes: list[bytes] = []
        self.callbacks = {}
        self._disconnected_callback = disconnected_callback
        self._operation = operation
        self._register_ok = register_ok

    async def start_notify(self, uuid, callback) -> None:
        self.callbacks[uuid] = callback
        if len(self.callbacks) == 2:
            asyncio.get_running_loop().call_soon(self._emit, MODEL_REPLY)

    def _emit(self, packet: bytes) -> None:
        if self.is_connected:
            for callback in self.callbacks.values():
                callback(None, packet)

    async def write_gatt_char(self, uuid, packet, response=True) -> None:
        assert response is True
        packet = bytes(packet)
        self.writes.append(packet)
        command = packet[0]
        if command == 0x13:
            self._emit(CONFIG_REPLY)
        elif command == 0x20:
            self._emit(TIME_REPLY)
        elif command == 0xA6:
            assert packet == bytes.fromhex("a604ffa9")
            if self._operation == "read_empty":
                self._emit(finish(bytearray([0xA7, 4, 0, 0])))
            else:
                self._emit(stored_user(1, 0x1234, 0b101, 7000))
                self._emit(stored_user(3, 0x5678, 0b101, 6500))
        elif command == 0xA0 and packet[2] == 1:
            assert packet[3] == 0  # Registration must request a free slot.
            self._emit(user_reply(1, 3, 1 if self._register_ok else 0))
        elif command == 0xA0 and packet[2] == 2:
            assert packet[3] == 3
            self._emit(user_reply(2, 3, 1))
        else:
            raise AssertionError(f"Unexpected admin command: {packet.hex()}")

    async def disconnect(self) -> None:
        if self.is_connected:
            self.is_connected = False
            self._disconnected_callback(self)


class UserAdminTest(unittest.IsolatedAsyncioTestCase):
    async def _run(self, operation, register_ok=True):
        client = None

        async def fake_establish(_class, _device, _name, **kwargs):
            nonlocal client
            client = FakeClient(
                kwargs["disconnected_callback"], operation, register_ok
            )
            return client

        if operation.startswith("read"):
            admin = RenphoUserAdmin(object(), "read")
        else:
            admin = RenphoUserAdmin(
                object(),
                "sync" if operation == "sync" else "register",
                age=40,
                height=180,
                male=True,
                user_key=0x2468,
                user_index=3 if operation == "sync" else None,
            )
        with patch.object(admin_module, "establish_connection", fake_establish):
            result = await asyncio.wait_for(admin.run(), timeout=2)
        assert client is not None
        return result, client

    async def test_read_empty_scale_sends_no_user_write(self):
        result, client = await self._run("read_empty")
        self.assertEqual(result, [])
        self.assertEqual([packet[0] for packet in client.writes], [0x13, 0x20, 0xA6])
        self.assertFalse(client.is_connected)

    async def test_read_two_slots_decodes_records(self):
        result, client = await self._run("read")
        self.assertEqual([user["user_index"] for user in result], [1, 3])
        self.assertEqual(result[0]["user_key"], 0x1234)
        self.assertEqual(result[0]["height"], 180.0)
        self.assertEqual(result[1]["gender"], "female")
        self.assertEqual(result[1]["last_weight_kg"], 65.0)
        self.assertFalse(client.is_connected)

    async def test_register_uses_allocated_slot_then_visits(self):
        result, client = await self._run("register")
        self.assertEqual(result["user_index"], 3)
        self.assertEqual(result["user_key"], 0x2468)
        registration = next(p for p in client.writes if p[0] == 0xA0)
        self.assertEqual(registration[2:4], bytes([1, 0]))
        visits = [p for p in client.writes if p[0] == 0xA0 and p[2] == 2]
        self.assertEqual(len(visits), 1)
        self.assertEqual(visits[0][3], 3)
        self.assertFalse(client.is_connected)

    async def test_full_scale_registration_fails_without_overwrite(self):
        with self.assertRaisesRegex(BleakError, "no free user slot"):
            await self._run("register", register_ok=False)

    async def test_sync_visits_existing_slot_without_registration(self):
        result, client = await self._run("sync")
        self.assertEqual(result["user_index"], 3)
        user_packets = [p for p in client.writes if p[0] == 0xA0]
        self.assertEqual(len(user_packets), 1)
        self.assertEqual(user_packets[0][2:4], bytes([2, 3]))
        self.assertFalse(client.is_connected)


if __name__ == "__main__":
    unittest.main()
