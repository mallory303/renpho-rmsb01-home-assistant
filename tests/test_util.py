"""Advertisement identification tests."""

import unittest
from types import SimpleNamespace

from tests.helpers import load_module

util = load_module("util")


def advertisement(payload: bytes):
    return SimpleNamespace(manufacturer_data={0xFFFF: payload})


class AdvertisementTest(unittest.TestCase):
    def test_rmsb01_and_resistance_flag(self) -> None:
        payload = bytearray.fromhex("0916" + "00" * 14)
        payload[11] = 0x61
        payload[15] = 0x17
        info = advertisement(bytes(payload))
        self.assertTrue(util.is_rmsb01(info))
        self.assertTrue(util.uses_resistance_encryption(info))
        payload[15] &= ~0x04
        self.assertFalse(util.uses_resistance_encryption(advertisement(bytes(payload))))

    def test_rejects_other_model_and_short_payload(self) -> None:
        payload = bytearray.fromhex("0916" + "00" * 14)
        payload[11] = 0x61
        payload[:2] = b"\xff\xff"
        self.assertFalse(util.is_rmsb01(advertisement(bytes(payload))))
        self.assertFalse(util.is_rmsb01(advertisement(b"\x09\x16")))


if __name__ == "__main__":
    unittest.main()
