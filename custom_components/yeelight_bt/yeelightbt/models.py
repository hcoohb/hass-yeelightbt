"""Models."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, StrEnum, IntEnum, auto
from typing import Any


@dataclass
class DeviceInfo:
    """Device info."""

    device_id: str | None = None
    device_name: str | None = None
    sw_version: str | None = None



class LampModel(StrEnum):
    BEDSIDE = "Bedside"
    CANDELA = "Candela"




class DisconnectReason(Enum):
    """Disconnect reason."""

    ERROR = auto()
    INVALID_COMMAND = auto()
    LOCK_REQUESTED = auto()
    TIMEOUT = auto()
    UNEXPECTED = auto()
    USER_REQUESTED = auto()


class ErrorCode(IntEnum):
    """Error code."""

    SUCCESS = 0
    UNKNOWN_CMD = 1
    NOT_AUTHENTICATED = 2
    AUTHENTICATION_FAILED = 3
    WRONG_PIN = 4
    NO_AVAILABLE_KEYS = 5
    FLASH_WRITE_FAILED = 6
    MAX_ADMINS = 7
    MAX_PENDING_KEYS = 8
    MAX_KEY_FOBS_PENDING = 9
    WRONG_STATE = 10
    INC_PREPARE = 12
    REPEAT = 13
    PARAM_NOT_SUPPORTED = 14