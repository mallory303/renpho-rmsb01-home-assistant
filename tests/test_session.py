"""Protocol tests for the embedded VA/TN session manager using synthetic data."""

import asyncio
import unittest
from unittest.mock import patch

from bleak import BleakError

from tests.helpers import load_module

session_module = load_module("session")
decoder_module = load_module("decoder")
RenphoSession = session_module.RenphoSession


def finish(packet: bytearray) -> bytes:
    packet[1] = len(packet)
    packet[-1] = sum(packet[:-1]) & 0xFF
    return bytes(packet)


def model_reply() -> bytes:
    packet = bytearray(19)
    packet[0] = 0x12
    packet[2] = 0xFF
    packet[9] = 44  # Scale version
    packet[10] = 0x07  # 0.01 kg, stored-user metadata, no heart-rate support
    packet[11] = 6  # BLE version
    packet[13:18] = bytes.fromhex("03050770ee")
    return finish(packet)


def put16(packet: bytearray, offset: int, value: int) -> None:
    packet[offset] = value >> 8
    packet[offset + 1] = value & 0xFF


def synthetic_triplet() -> tuple[bytes, bytes, bytes]:
    first = bytearray(20)
    first[0] = 0x10
    first[2] = 0xFF
    first[3] = 254
    first[4] = 2
    put16(first, 5, 7000)  # 70.00 kg
    put16(first, 7, 500)
    put16(first, 9, 501)
    put16(first, 11, 223)  # 22.3%
    for offset in (7, 9):
        for index in (offset, offset + 1):
            first[index] = decoder_module.swap_bit(
                decoder_module.swap_bit(first[index], 0, 4), 3, 5
            )

    second = bytearray(20)
    second[0] = 0x15
    second[2] = 0xFF
    put16(second, 3, 221)
    put16(second, 5, 550)
    put16(second, 7, 400)  # 40.0% of 70 kg = 28 kg
    second[9] = 8
    second[10] = 35
    put16(second, 11, 1500)
    put16(second, 13, 180)

    third = bytearray(20)
    third[0] = 0x16
    third[2] = 0xFF
    third[3] = 25
    put16(third, 4, 36)  # 3.6% of 70 kg = 2.52 kg
    put16(third, 6, 750)  # 75.0% of 70 kg = 52.5 kg
    put16(third, 8, 150)
    put16(third, 10, 400)
    put16(third, 12, 850)
    third[14] = 4
    return finish(first), finish(second), finish(third)


MODEL_REPLY = model_reply()
CONFIG_REPLY = bytes.fromhex("140bff010001090300002c")
TIME_REPLY = bytes.fromhex("2105ff0126")
VISITOR_REPLY = bytes.fromhex("a10602fe01a8")
TRIPLET = synthetic_triplet()


class FakeClient:
    """Small GATT peer that enforces the scale's request/response sequence."""

    def __init__(self, disconnected_callback, complete: bool, auto: bool = False) -> None:
        self.address = "02:00:00:00:00:00"
        self.is_connected = True
        self.writes: list[bytes] = []
        self.callbacks = {}
        self._disconnected_callback = disconnected_callback
        self._complete = complete
        self._auto = auto

    async def start_notify(self, uuid, callback) -> None:
        self.callbacks[uuid] = callback
        if len(self.callbacks) == 2:
            asyncio.get_running_loop().call_soon(self._emit, MODEL_REPLY)

    def _emit(self, packet: bytes) -> None:
        if not self.is_connected:
            return
        for callback in self.callbacks.values():
            callback(None, packet)

    async def write_gatt_char(self, uuid, packet, response=True) -> None:
        assert response is True
        packet = bytes(packet)
        self.writes.append(packet)
        command = packet[0]
        if command == 0x13:
            assert packet == bytes.fromhex("1309ff01100000002c")
            self._emit(CONFIG_REPLY)
        elif command == 0x20:
            assert packet[:3] == bytes.fromhex("2008ff")
            self._emit(TIME_REPLY)
            if self._auto and self._complete:
                first = bytearray(TRIPLET[0])
                first[3] = 3  # Native scale-side identification, not visitor 254.
                self._emit(finish(first))
                for reply in TRIPLET[1:]:
                    self._emit(reply)
        elif command == 0xA0:
            self._emit(VISITOR_REPLY)
            if self._complete:
                for reply in TRIPLET:
                    self._emit(reply)
            else:
                await self.disconnect()

    async def disconnect(self) -> None:
        if self.is_connected:
            self.is_connected = False
            self._disconnected_callback(self)


class RenphoSessionTest(unittest.IsolatedAsyncioTestCase):
    async def _measure(self, complete: bool, auto: bool = False):
        client: FakeClient | None = None

        async def fake_establish(_class, _device, _name, **kwargs):
            nonlocal client
            client = FakeClient(kwargs["disconnected_callback"], complete, auto)
            return client

        session = RenphoSession(
            object(), age=45, height=165, male=False, resistance_encrypted=True, auto=auto
        )
        with patch.object(session_module, "establish_connection", fake_establish):
            result = await asyncio.wait_for(session.measure(), timeout=2)
        assert client is not None
        return result, client

    async def test_synthetic_measurement_handshake_and_decode(self) -> None:
        result, client = await self._measure(complete=True)
        expected = {
            "weight_kg": 70.0,
            "bmi": 22.1,
            "bodyfat_percent": 22.3,
            "water_percent": 55.0,
            "muscle_mass_kg": 28.0,
            "visceral_fat": 8,
            "body_age_years": 35,
            "bmr_kcal": 1500,
            "protein_percent": 18.0,
            "heart_rate_bpm": 0,
            "heart_index": 0.0,
            "bone_kg": 2.52,
            "lean_body_mass_kg": 52.5,
            "subfat_percent": 15.0,
            "muscle_percent": 40.0,
            "score": 85.0,
            "body_shape": 4,
            "resistance_50_raw": 500,
            "resistance_500_raw": 501,
        }
        for name, value in expected.items():
            self.assertAlmostEqual(result["metrics"][name], value, msg=name)
        self.assertEqual(result["metadata"]["user_index"], 254)
        self.assertEqual(result["capabilities"]["weight_ratio"], 0.01)
        self.assertEqual(result["capabilities"]["value_type"], 1)
        self.assertTrue(result["capabilities"]["visitor_accepted"])
        self.assertEqual(client.writes[0], bytes.fromhex("1309ff01100000002c"))
        self.assertEqual(client.writes[1][0], 0x20)
        self.assertEqual(client.writes[2], bytes.fromhex("a00d02feffee012d0672050045"))
        self.assertEqual(client.writes[-1], bytes.fromhex("1f05ff1033"))
        self.assertFalse(client.is_connected)

    async def test_auto_sends_no_visitor_and_decodes_identified_slot(self) -> None:
        result, client = await self._measure(complete=True, auto=True)
        self.assertTrue(result["automatic"])
        self.assertEqual(result["metadata"]["user_index"], 3)
        self.assertTrue(result["capabilities"]["identify_weight"])
        self.assertFalse(any(packet[0] == 0xA0 for packet in client.writes))
        self.assertEqual(client.writes[-1], bytes.fromhex("1f05ff1033"))
        self.assertFalse(client.is_connected)

    async def test_disconnect_before_triplet_raises_without_result(self) -> None:
        with self.assertRaisesRegex(BleakError, "disconnected before"):
            await self._measure(complete=False)


if __name__ == "__main__":
    unittest.main()
