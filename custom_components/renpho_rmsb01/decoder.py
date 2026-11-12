"""Decode Qingniu/Renpho VA-TN three-packet body-composition measurements.

Derived statically from Renpho 7.5.2-670, VADecoderImpl.java:
  live:   0x10 / 0x15 / 0x16
  stored: 0x23 / 0x24 / 0x25

This is a protocol decoder, not a body-composition calculator. It does not
invent missing metrics and does not claim that every scale uses VA-TN.
No third-party packages are required.
"""

from __future__ import annotations

import argparse
import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime

R_MSB01_BODY_INDEX_FLAG = 0x37BFF
RENPHO_TIME_BASE_SECONDS = 946684800  # 2000-01-01T00:00:00Z


def be16(packet: bytes, offset: int) -> int:
    return (packet[offset] << 8) | packet[offset + 1]


def swap_bit(value: int, first: int, second: int) -> int:
    """Equivalent to ConvertUtils.swapBit for one unsigned byte."""
    a = (value >> first) & 1
    b = (value >> second) & 1
    if a == b:
        return value
    # The two bits differ, so XOR toggles both and swaps their values.
    return value ^ ((1 << first) | (1 << second))


def decode_resistance(packet: bytes, offset: int, encrypted: bool) -> int:
    hi, lo = packet[offset], packet[offset + 1]
    if encrypted:
        hi = swap_bit(swap_bit(hi, 0, 4), 3, 5)
        lo = swap_bit(swap_bit(lo, 0, 4), 3, 5)
    value = (hi << 8) | lo
    return 0 if value >= 60000 else value


def decode_weight(raw: int, ratio: float) -> float:
    value = raw * ratio
    while value > 300.0:
        value /= 10.0
    return value


def parse_hex_packet(text: str) -> bytes:
    cleaned = re.sub(r"(?:0x)|[^0-9a-fA-F]", "", text)
    if len(cleaned) % 2:
        raise ValueError(f"Odd number of hex digits in packet: {text!r}")
    packet = bytes.fromhex(cleaned)
    if not packet:
        raise ValueError("Empty packet")
    return packet


def _mass(raw: int, weight_kg: float, percentage_mass: bool) -> float:
    if percentage_mass:
        return raw * 0.1 * weight_kg / 100.0
    return raw * 0.01


def decode_tn_packets(
    packets: Iterable[bytes],
    *,
    weight_ratio: float = 0.1,
    percentage_mass: bool = False,
    support_heart: bool = False,
    resistance_encrypted: bool = False,
    body_index_flag: int = R_MSB01_BODY_INDEX_FLAG,
) -> dict:
    """Decode one live or stored three-packet VA-TN measurement.

    The three packets may be supplied in any order; their command bytes select
    their roles. Options mirror decoder state learned from earlier handshake /
    advertisement packets and therefore cannot be inferred from these three
    measurement packets alone.
    """
    if weight_ratio not in (0.01, 0.1):
        raise ValueError("weight_ratio must be 0.01 or 0.1")
    packets = list(packets)
    if len(packets) != 3:
        raise ValueError("Exactly three packets are required")

    live_commands = {0x10: "first", 0x15: "second", 0x16: "third"}
    stored_commands = {0x23: "first", 0x24: "second", 0x25: "third"}
    first_byte = packets[0][0]
    if first_byte in live_commands:
        mode, commands = "live", live_commands
    elif first_byte in stored_commands:
        mode, commands = "stored", stored_commands
    else:
        raise ValueError(f"Not a VA-TN measurement command: 0x{first_byte:02x}")

    by_role: dict[str, bytes] = {}
    for packet in packets:
        if packet[0] not in commands:
            raise ValueError(f"Mixed or invalid packet command: 0x{packet[0]:02x}")
        role = commands[packet[0]]
        if role in by_role:
            raise ValueError(f"Duplicate {role} packet (0x{packet[0]:02x})")
        by_role[role] = packet
    if set(by_role) != {"first", "second", "third"}:
        raise ValueError("Missing one or more VA-TN packets")

    first, second, third = by_role["first"], by_role["second"], by_role["third"]
    minimum_lengths = (19, 15, 15) if mode == "stored" else (14, 15, 15)
    for role, packet, minimum in zip(("first", "second", "third"), (first, second, third), minimum_lengths):
        if len(packet) < minimum:
            raise ValueError(f"{role} packet is {len(packet)} bytes; need at least {minimum}")
    combined_minimum = 52 if mode == "stored" else 47
    if len(first) + len(second) + len(third) < combined_minimum:
        raise ValueError(f"Combined packet length is below the app's {combined_minimum}-byte check")

    if mode == "live":
        weight_raw = be16(first, 5)
        resistance50 = decode_resistance(first, 7, resistance_encrypted)
        resistance500 = decode_resistance(first, 9, resistance_encrypted)
        bodyfat = be16(first, 11) * 0.1
        heart_rate = first[13] if support_heart else 0
        metadata = {"user_index": first[3]}
    else:
        weight_raw = be16(first, 10)
        resistance50 = decode_resistance(first, 12, resistance_encrypted)
        resistance500 = decode_resistance(first, 14, resistance_encrypted)
        bodyfat = be16(first, 16) * 0.1
        heart_rate = first[18] if support_heart else 0
        seconds_since_2000 = sum(first[6 + i] << (8 * i) for i in range(4))
        timestamp = RENPHO_TIME_BASE_SECONDS + seconds_since_2000
        metadata = {
            "total_count": first[3],
            "current_count": first[4],
            "user_index": first[5],
            "seconds_since_2000": seconds_since_2000,
            "measure_time_unix": timestamp,
            "measure_time_utc": datetime.fromtimestamp(timestamp, UTC).isoformat(),
        }

    weight = decode_weight(weight_raw, weight_ratio)
    metrics = {
        "weight_kg": weight,
        "bmi": be16(second, 3) * 0.1,
        "bodyfat_percent": bodyfat,
        "subfat_percent": be16(third, 8) * 0.1,
        "visceral_fat": second[9],
        "water_percent": be16(second, 5) * 0.1,
        "muscle_percent": be16(third, 10) * 0.1,
        "bone_kg": _mass(be16(third, 4), weight, percentage_mass),
        "bmr_kcal": be16(second, 11),
        "protein_percent": be16(second, 13) * 0.1,
        "lean_body_mass_kg": _mass(be16(third, 6), weight, percentage_mass),
        "muscle_mass_kg": _mass(be16(second, 7), weight, percentage_mass),
        "body_age_years": second[10],
        "heart_rate_bpm": heart_rate,
        "heart_index": third[3] * 0.1 if support_heart else 0.0,
        "score": be16(third, 12) * 0.1,
        "body_shape": third[14],
        "resistance_50_raw": resistance50,
        "resistance_500_raw": resistance500,
    }

    # QNScaleData.convertData: weight/BMI are unconditional; other items are
    # controlled by the model's body_index_flag. Impedances remain dedicated
    # fields even when no resistance display item is enabled.
    item_types = {
        "weight_kg": 1,
        "bmi": 2,
        "bodyfat_percent": 3,
        "subfat_percent": 4,
        "visceral_fat": 5,
        "water_percent": 6,
        "muscle_percent": 7,
        "bone_kg": 8,
        "bmr_kcal": 9,
        "body_shape": 10,
        "protein_percent": 11,
        "lean_body_mass_kg": 12,
        "muscle_mass_kg": 13,
        "body_age_years": 14,
        "score": 15,
        "heart_rate_bpm": 16,
        "heart_index": 17,
    }
    qn_items = [
        {"type": item_type, "metric": name, "value": metrics[name]}
        for name, item_type in item_types.items()
        if item_type in (1, 2) or ((body_index_flag >> item_type) & 1)
    ]

    return {
        "protocol": f"VA_TN_{mode}",
        "mode": mode,
        "metadata": metadata,
        "decoder_options": {
            "weight_ratio": weight_ratio,
            "percentage_mass": percentage_mass,
            "support_heart": support_heart,
            "resistance_encrypted": resistance_encrypted,
            "body_index_flag": body_index_flag,
        },
        "metrics": metrics,
        "qn_surface_items": qn_items,
        "decoded_but_masked_out": [
            name for name, item_type in item_types.items()
            if item_type not in (1, 2) and not ((body_index_flag >> item_type) & 1)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("packets", nargs=3, help="Three complete BLE payload packets as hex")
    parser.add_argument("--weight-ratio", type=float, choices=(0.01, 0.1), default=0.1,
                        help="From 0x12 reply byte 10 bit 0 (default matches decoder initialization: 0.1)")
    parser.add_argument("--percentage-mass", action="store_true",
                        help="Set when valueType==1; muscle mass, bone and LBM packets contain percentages")
    parser.add_argument("--support-heart", action="store_true",
                        help="From 0x12 reply byte 10 bit 5")
    parser.add_argument("--resistance-encrypted", action="store_true",
                        help="Apply the capability-dependent resistance bit swaps")
    parser.add_argument("--body-index-flag", type=lambda s: int(s, 0), default=R_MSB01_BODY_INDEX_FLAG,
                        help="Model display mask (default: R-MSB01, 0x37bff)")
    args = parser.parse_args()
    try:
        packets = [parse_hex_packet(text) for text in args.packets]
        result = decode_tn_packets(
            packets,
            weight_ratio=args.weight_ratio,
            percentage_mass=args.percentage_mass,
            support_heart=args.support_heart,
            resistance_encrypted=args.resistance_encrypted,
            body_index_flag=args.body_index_flag,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
