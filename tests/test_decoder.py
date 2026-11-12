import unittest

from tests.helpers import load_module

_decoder = load_module("decoder")
RENPHO_TIME_BASE_SECONDS = _decoder.RENPHO_TIME_BASE_SECONDS
decode_tn_packets = _decoder.decode_tn_packets
swap_bit = _decoder.swap_bit


def put16(packet, offset, value):
    packet[offset] = (value >> 8) & 0xFF
    packet[offset + 1] = value & 0xFF


def live_packets():
    first = bytearray(20)
    first[0] = 0x10
    first[3] = 2
    put16(first, 5, 7000)       # 70.00 kg at ratio 0.01
    put16(first, 7, 500)
    put16(first, 9, 501)
    put16(first, 11, 223)       # 22.3 %
    first[13] = 65

    second = bytearray(20)
    second[0] = 0x15
    put16(second, 3, 221)       # BMI 22.1
    put16(second, 5, 550)       # water 55.0 %
    put16(second, 7, 3000)      # muscle mass 30.00 kg in absolute mode
    second[9] = 8
    second[10] = 35
    put16(second, 11, 1500)
    put16(second, 13, 180)      # protein 18.0 %

    third = bytearray(20)
    third[0] = 0x16
    third[3] = 25               # heart index 2.5
    put16(third, 4, 250)        # bone 2.50 kg in absolute mode
    put16(third, 6, 5250)       # LBM 52.50 kg in absolute mode
    put16(third, 8, 150)        # subcutaneous fat 15.0 %
    put16(third, 10, 400)       # muscle 40.0 %
    put16(third, 12, 850)       # score 85.0
    third[14] = 4
    return [bytes(first), bytes(second), bytes(third)]


class DecodeVaTnTest(unittest.TestCase):
    def test_live_absolute_and_surface_mask(self):
        result = decode_tn_packets(
            reversed(live_packets()), weight_ratio=0.01, support_heart=True
        )
        self.assertEqual(result["protocol"], "VA_TN_live")
        self.assertEqual(result["metadata"]["user_index"], 2)
        expected = {
            "weight_kg": 70.0,
            "bmi": 22.1,
            "bodyfat_percent": 22.3,
            "water_percent": 55.0,
            "muscle_mass_kg": 30.0,
            "visceral_fat": 8,
            "body_age_years": 35,
            "bmr_kcal": 1500,
            "protein_percent": 18.0,
            "heart_rate_bpm": 65,
            "heart_index": 2.5,
            "bone_kg": 2.5,
            "lean_body_mass_kg": 52.5,
            "subfat_percent": 15.0,
            "muscle_percent": 40.0,
            "score": 85.0,
            "body_shape": 4,
            "resistance_50_raw": 500,
            "resistance_500_raw": 501,
        }
        for name, value in expected.items():
            self.assertEqual(result["metrics"][name], value, name)
        self.assertCountEqual(result["decoded_but_masked_out"], ["body_shape", "score"])
        self.assertEqual(len(result["qn_surface_items"]), 15)
        self.assertNotIn(32, [item["type"] for item in result["qn_surface_items"]])
        self.assertEqual(result["metrics"]["resistance_50_raw"], 500)

    def test_percentage_mass_mode(self):
        first, second, third = map(bytearray, live_packets())
        put16(second, 7, 400)     # 40.0 % of 70 kg = 28 kg
        put16(third, 4, 36)       # 3.6 % of 70 kg = 2.52 kg
        put16(third, 6, 750)      # 75.0 % of 70 kg = 52.5 kg
        result = decode_tn_packets(
            [bytes(first), bytes(second), bytes(third)],
            weight_ratio=0.01,
            percentage_mass=True,
        )
        self.assertAlmostEqual(result["metrics"]["muscle_mass_kg"], 28.0)
        self.assertAlmostEqual(result["metrics"]["bone_kg"], 2.52)
        self.assertAlmostEqual(result["metrics"]["lean_body_mass_kg"], 52.5)

    def test_resistance_bit_swaps_are_reversed_per_byte(self):
        first, second, third = map(bytearray, live_packets())
        for offset in (7, 9):
            for index in (offset, offset + 1):
                first[index] = swap_bit(swap_bit(first[index], 0, 4), 3, 5)
        result = decode_tn_packets(
            [bytes(first), bytes(second), bytes(third)],
            weight_ratio=0.01,
            resistance_encrypted=True,
        )
        self.assertEqual(result["metrics"]["resistance_50_raw"], 500)
        self.assertEqual(result["metrics"]["resistance_500_raw"], 501)

    def test_stored_packet_layout_and_little_endian_time(self):
        first, second, third = live_packets()
        stored = bytearray(20)
        stored[0] = 0x23
        stored[3:6] = bytes((7, 3, 2))
        for i in range(4):
            stored[6 + i] = (1000 >> (8 * i)) & 0xFF
        stored[10:19] = first[5:14]
        second = bytes([0x24]) + second[1:]
        third = bytes([0x25]) + third[1:]
        result = decode_tn_packets(
            [bytes(stored), second, third], weight_ratio=0.01, support_heart=True
        )
        self.assertEqual(result["protocol"], "VA_TN_stored")
        self.assertEqual(result["metadata"]["total_count"], 7)
        self.assertEqual(result["metadata"]["current_count"], 3)
        self.assertEqual(result["metadata"]["user_index"], 2)
        self.assertEqual(
            result["metadata"]["measure_time_unix"], RENPHO_TIME_BASE_SECONDS + 1000
        )
        self.assertEqual(result["metrics"]["weight_kg"], 70.0)
        self.assertEqual(result["metrics"]["bodyfat_percent"], 22.3)
        self.assertEqual(result["metrics"]["heart_rate_bpm"], 65)

    def test_invalid_or_mixed_packets_fail(self):
        packets = list(live_packets())
        with self.assertRaises(ValueError):
            decode_tn_packets(packets[:2])
        packets[1] = bytes([0x24]) + packets[1][1:]
        with self.assertRaises(ValueError):
            decode_tn_packets(packets)


if __name__ == "__main__":
    unittest.main()
