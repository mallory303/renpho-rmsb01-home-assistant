"""Advertisement helpers for Renpho R-MSB01."""

from typing import Any

MODEL_IDS = (b"\x09\x16", b"\x08\xa5", b"\x0a\x5e", b"\x0a\x5f", b"\x0a\x60")


def manufacturer_payload(service_info: Any) -> bytes:
    """Return the Renpho manufacturer payload, if present."""
    return service_info.manufacturer_data.get(0xFFFF, b"")


def is_rmsb01(service_info: Any) -> bool:
    """Identify the verified R-MSB01 VA/TN advertisement."""
    payload = manufacturer_payload(service_info)
    return (
        len(payload) > 15
        and payload[:2] in MODEL_IDS
        and payload[11] == 0x61
    )


def uses_resistance_encryption(service_info: Any) -> bool:
    """Return whether VA impedance bit permutation is advertised."""
    payload = manufacturer_payload(service_info)
    return len(payload) > 15 and bool((payload[15] >> 2) & 1)


def normalized_address(address: str) -> str:
    """Normalize a Bluetooth address for unique IDs."""
    return address.upper()
