"""Input validation rules for devices and links."""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from .models import DeviceType


class ValidationError(ValueError):
    """Raised when a device, link or topology definition is invalid."""


_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# Device-type pairs that may be connected directly. End devices (PCs and
# servers) must attach to infrastructure; they cannot be cabled to each other.
ALLOWED_CONNECTIONS: frozenset[frozenset[DeviceType]] = frozenset(
    {
        frozenset({DeviceType.PC, DeviceType.SWITCH}),
        frozenset({DeviceType.PC, DeviceType.ROUTER}),
        frozenset({DeviceType.SERVER, DeviceType.SWITCH}),
        frozenset({DeviceType.SERVER, DeviceType.ROUTER}),
        frozenset({DeviceType.SWITCH}),  # switch <-> switch
        frozenset({DeviceType.SWITCH, DeviceType.ROUTER}),
        frozenset({DeviceType.ROUTER}),  # router <-> router
    }
)


def validate_device_id(device_id: Any) -> str:
    if not isinstance(device_id, str) or not device_id.strip():
        raise ValidationError("Device id must be a non-empty string")
    device_id = device_id.strip()
    if not _ID_PATTERN.match(device_id):
        raise ValidationError(
            f"Invalid device id {device_id!r}: use letters, digits, '_', '-' or '.' "
            "(max 64 chars, must start with a letter or digit)"
        )
    return device_id


def validate_device_type(device_type: Any) -> DeviceType:
    try:
        return DeviceType.parse(device_type)
    except ValueError as exc:
        raise ValidationError(str(exc)) from None


def validate_ip_address(ip: Any) -> str | None:
    if ip is None or ip == "":
        return None
    if not isinstance(ip, str):
        raise ValidationError(f"IP address must be a string, got {type(ip).__name__}")
    try:
        return str(ipaddress.ip_address(ip.strip()))
    except ValueError:
        raise ValidationError(f"Invalid IP address {ip!r}") from None


def validate_positive_number(value: Any, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field_name} must be a number, got {value!r}")
    if value != value or value <= 0 or value == float("inf"):  # NaN / non-positive / inf
        raise ValidationError(f"{field_name} must be a positive finite number, got {value!r}")
    return float(value)


def validate_connection(source_type: DeviceType, target_type: DeviceType) -> None:
    if frozenset({source_type, target_type}) not in ALLOWED_CONNECTIONS:
        raise ValidationError(
            f"A {source_type.value} cannot be connected directly to a {target_type.value}"
        )
