"""Advertisement helpers for Renpho R-MSB01."""

from typing import Any

MODEL_IDS = (b"\x09\x16", b"\x08\xa5", b"\x0a\x5e", b"\x0a\x5f", b"\x0a\x60")
SCALE_NAME = "Renpho-Scale"
SCALE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"


def manufacturer_payload(service_info: Any) -> bytes:
    """Return the Renpho manufacturer payload, if present."""
    return service_info.manufacturer_data.get(0xFFFF, b"")


def is_minimal_rmsb01(service_info: Any) -> bool:
    """Identify the verified connectable name/UUID-only advertisement."""
    return (
        getattr(service_info, "name", None) == SCALE_NAME
        and SCALE_SERVICE_UUID in getattr(service_info, "service_uuids", ())
        and bool(getattr(service_info, "connectable", False))
    )


def is_rmsb01(service_info: Any) -> bool:
    """Identify either verified R-MSB01 advertisement variant."""
    payload = manufacturer_payload(service_info)
    return (
        len(payload) > 15
        and payload[:2] in MODEL_IDS
        and payload[11] == 0x61
    ) or is_minimal_rmsb01(service_info)


def uses_resistance_encryption(service_info: Any) -> bool:
    """Use the advertised flag, or the verified R-MSB01 minimal-packet behavior."""
    payload = manufacturer_payload(service_info)
    if len(payload) > 15:
        return bool((payload[15] >> 2) & 1)
    return is_minimal_rmsb01(service_info)


def normalized_address(address: str) -> str:
    """Normalize a Bluetooth address for unique IDs."""
    return address.upper()
