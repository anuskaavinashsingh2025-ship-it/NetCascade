"""Data models for network devices and links."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class DeviceType(str, Enum):
    """Kinds of devices that can appear in a NetCascade topology."""

    PC = "pc"
    SWITCH = "switch"
    ROUTER = "router"
    SERVER = "server"

    @classmethod
    def parse(cls, value: "DeviceType | str") -> "DeviceType":
        if isinstance(value, cls):
            return value
        if isinstance(value, str):
            try:
                return cls(value.strip().lower())
            except ValueError:
                pass
        valid = ", ".join(t.value for t in cls)
        raise ValueError(f"Unknown device type {value!r}. Expected one of: {valid}")

    @property
    def is_end_device(self) -> bool:
        return self in (DeviceType.PC, DeviceType.SERVER)

    @property
    def is_infrastructure(self) -> bool:
        return self in (DeviceType.SWITCH, DeviceType.ROUTER)


@dataclass(frozen=True)
class Device:
    """A node in the network graph."""

    id: str
    type: DeviceType
    name: str = ""
    ip_address: str | None = None
    attributes: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["type"] = self.type.value
        return data


@dataclass(frozen=True)
class Link:
    """An undirected connection between two devices.

    ``latency_ms`` is used as the weight for weighted shortest-path analysis.
    """

    source: str
    target: str
    bandwidth_mbps: float = 1000.0
    latency_ms: float = 1.0
    attributes: dict[str, Any] = field(default_factory=dict)

    @property
    def key(self) -> frozenset[str]:
        return frozenset((self.source, self.target))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
