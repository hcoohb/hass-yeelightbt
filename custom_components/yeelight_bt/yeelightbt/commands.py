"""Models for commands which can be sent to and received from a lamp."""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import IntEnum
import struct
from typing import Any, TypeVar, cast

from .errors import InvalidCommand
from .models import ErrorCode


class PacketBase(ABC):
    """Base class for commands.
    Packets are 18 bytes,
    Starts with common 0x43, followed by the command id, and any other info
    format describe the packet struture past header (common and cmd_id)"""

    cmd_id: int
    format: str

    @property
    def _header(self) -> bytes:
        """Return packed header."""
        return struct.pack(">BB", 0x43, self.cmd_id)  # big endian format

    def _pack(self, *args: Any) -> bytes:
        """Pack the command to bytes."""
        fmt = self.format
        if not fmt.startswith(">"):
            fmt = ">" + fmt  # big endian format
        # add end padding
        if (fmt_len := struct.calcsize(fmt)) < 16:
            fmt = f"{fmt}{16-fmt_len}x"
        return self._header + struct.pack(fmt, *args)

    @classmethod
    def _validate(cls, data: bytes) -> None:
        """Raise if the data is not valid."""
        if len(data) != 18:
            raise InvalidCommand("Invalid length", data.hex())
        if not struct.unpack("B17x", data)[0] & 0x43:
            raise InvalidCommand("Invalid header", data.hex())
        if not struct.unpack("xB16x", data)[0] & cls.cmd_id:
            raise InvalidCommand("Invalid cmd_id", data.hex())
        # TODO: should we check using _header???
        # if data[0] != cls.cmd_id or data[1] != cls._len:
        #     raise InvalidCommand("Invalid header", data.hex())


class Command(PacketBase):
    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self._pack()


class Response(PacketBase):
    @classmethod
    @abstractmethod
    def from_bytes(cls, data: bytes) -> Response:
        """Initialize from serialized representation of the command."""


_CMD_T = TypeVar("_CMD_T", bound=Command)


class UnknownResponse(Response):
    """Unknown response."""

    def __init__(self, data: bytes):
        """Initialize."""
        self.data = data
        self.cmd_id = data[1]

    def __str__(self) -> str:
        return f"{self.__class__.__name__} data: {self.data.hex()}"

    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self.data

    @classmethod
    def from_bytes(cls, data: bytes) -> UnknownResponse:
        """Initialize from serialized representation of the command."""
        return cls(data)


class AssociationStatus(IntEnum):
    """Status report type"""

    REQUESTING_PAIR = 0x01
    SUCCESSFULLY_PAIRED = 0x02
    NOT_PAIRED = 0x03
    ALREADY_PAIRED = 0x04
    DISCONNECTING_NOW = 0x06 #factory reset required
    DISCONNECTING_SOON_2 = 0x07


class AssociationCmd(Command):
    """Association Command."""

    cmd_id = 0x67
    format = "B"

    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self._pack(0x02)


class AssociationRsp(Response):
    """Association Response."""

    cmd_id = 0x63
    format = "B15x"

    def __init__(self, status: AssociationStatus, data: bytes):
        """Initialize."""
        self.status = status
        self.data = data

    def __str__(self) -> str:
        return f"{self.__class__.__name__} {self.status.name}, data: {self.data.hex()}"

    @classmethod
    def from_bytes(cls, data: bytes) -> AssociationRsp:
        """Initialize from serialized representation of the command."""
        cls._validate(data)
        (status,) = struct.unpack_from(cls.format, data, 2)
        return cls(AssociationStatus(status), data)


class StatusRequestCmd(Command):
    """Status Request command."""

    cmd_id = 0x44
    format = "B15x"

    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self._pack(0x02)


class Power(IntEnum):
    ON = 0x01
    OFF = 0x02


class Mode(IntEnum):
    COLOR = 0x01
    WHITE = 0x02
    FLOW = 0x03


class YbtState:
    # model: Model
    power: Power | None = None
    mode: Mode | None = None
    brightness: int = 0  # [1-100]
    temperature: int | None = None  # [1700-6500]
    rbg: tuple[int] | None = None  # [0-255]

    def __str__(self) -> str:
        values = []
        for attr in ("power", "mode"):
            if (value := getattr(self, attr)) is not None:
                values.append(f"{attr}: {value.name}")
        for attr in ("brightness", "temperature", "rgb"):
            if (value := getattr(self, attr)) is not None:
                values.append(f"{attr}: {value}")
        return ", ".join(values)

    @classmethod
    def from_bytes(cls, data: bytes) -> YbtState:
        """Initialize from serialized representation."""
        print(data)
        instance = cls()
        state = struct.unpack(">xxBBBBBBBhx6x", data)
        instance.power = Power(state[0])

        # if self.model == Model.CANDELA:
        #     self.brightness = state[1]
        #     self.mode = Mode(state[2])
        #     # Not entirely sure this is the mode...
        #     # Candela seems to also give something in state 3 and 4...
        # else:
        instance.mode = Mode(state[1])  # Mode only given if connection is paired
        instance.rgb = (state[2], state[3], state[4])  # , state[5])
        instance.brightness = state[6]
        instance.temperature = state[7]
        # _LOGGER.info(f"YBT state: {self}")
        return instance


class StatusRsp(Response):
    """Status Response."""

    cmd_id = 0x45
    format = "xxB15x"

    def __init__(self, state: YbtState):
        """Initialize."""
        self.state = state

    def __str__(self) -> str:
        return f"{self.__class__.__name__} state: {self.state}"

    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self.data

    @classmethod
    def from_bytes(cls, data: bytes) -> StatusRsp:
        """Initialize from serialized representation of the command."""
        cls._validate(data)
        state = YbtState.from_bytes(data)
        print(state)
        return cls(state)


class PowerCmd(Command):
    """Request Power up or down the lamp"""

    cmd_id = 0x40
    format = "B"

    def __init__(self, power: Power):
        self.power = power

    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self._pack(self.power)


class BrightnessCmd(Command):
    """Change brightness of the lamp for the current mode"""

    cmd_id = 0x42
    format = "B"  # [0-100] in one byte

    def __init__(self, brightness: int):
        """brightness int [0-100]"""
        self.brightness = brightness

    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self._pack(self.brightness)


class TemperatureCmd(Command):
    """Change the temperature and brightness of the lamp"""

    cmd_id = 0x43
    format = (
        "hB"  # [1700 - 6500 K] in two bytes, [0-100] in one byte , big-endian format
    )

    def __init__(self, temp_kelvin: int, brightness: int):
        """brightness int [0-100]"""
        self.kelvin = min(6500, max(1700, int(temp_kelvin)))
        self.brightness = min(100, max(0, int(brightness)))

    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self._pack(self.kelvin, self.brightness)


class ColorCmd(Command):
    """Change the color and brightness of the lamp"""

    cmd_id = 0x41
    format = "BBBBB"  # R[0-255], G[0-255], B[0-255], 0x01, brightness[0-100]

    def __init__(self, red: int, green: int, blue: int, brightness: int):
        """R,G,B,brightness int [0-100]"""
        self.red = min(100, max(0, int(red)))
        self.green = min(100, max(0, int(green)))
        self.blue = min(100, max(0, int(blue)))
        self.brightness = min(100, max(0, int(brightness)))

    @property
    def as_bytes(self) -> bytes:
        """Return serialized representation of the command."""
        return self._pack(self.red, self.green, self.blue, 0x01, self.brightness)


class SerialRequestCmd(Command):
    """Request the lamp serial through notif"""

    cmd_id = 0x5E
    format = ""


class SerialRsp(Response):
    """Serial Response."""

    cmd_id = 0x5F

    def __init__(self, state: YbtState):
        """Initialize."""
        self.state = state

    def __str__(self) -> str:
        return f"{self.__class__.__name__} state: {self.state}"

    @classmethod
    def from_bytes(cls, data: bytes) -> SerialRsp:
        """Initialize from serialized representation of the command."""
        cls._validate(data)
        state = YbtState.from_bytes(data)
        print(state)
        return cls(state)


class VersionRequestCmd(Command):
    """Request the lamp version through notif"""

    cmd_id = 0x5C
    format = ""


class VersionRsp(Response):
    """Version Response."""

    cmd_id = 0x5D
    format = "xxBHHHH6x"

    def __init__(self, version: str):
        """Initialize."""
        self.version = version

    def __str__(self) -> str:
        return f"{self.__class__.__name__} version: {self.version}"

    @classmethod
    def from_bytes(cls, data: bytes) -> VersionRsp:
        """Initialize from serialized representation of the command."""
        cls._validate(data)
        version = cast(str, struct.unpack("xxBHHHH6x", data))
        print(f"YBT exposes versions: {version}")
        return cls(version)


class NameRequestCmd(Command):
    """Request the lamp name through notif"""

    cmd_id = 0x52
    format = ""


class NameRsp(Response):
    """Version Response."""

    cmd_id = 0x53
    format = "xxBHHHH6x"

    def __init__(self, version: str):
        """Initialize."""
        self.version = version

    def __str__(self) -> str:
        return f"{self.__class__.__name__} version: {self.version}"

    @classmethod
    def from_bytes(cls, data: bytes) -> VersionRsp:
        """Initialize from serialized representation of the command."""
        cls._validate(data)
        version = cast(str, struct.unpack("xxBHHHH6x", data))
        print(f"YBT exposes versions: {version}")
        return cls(version)


class FactoryResetRequestCmd(Command):
    """Request factory reset of the lamp"""

    cmd_id = 0x74
    format = ""


class FactoryResetRsp(Response):
    """Factory reset Response."""

    cmd_id = 0x82
    # 438243740100000000000000000000000000 # factory reset ok?
    # 438243540100000000000000000000000000 # enabling beacon ?
    format = "xxB15x"

    def __init__(self, state: YbtState):
        """Initialize."""
        self.state = state

    @classmethod
    def from_bytes(cls, data: bytes) -> SerialRsp:
        """Initialize from serialized representation of the command."""
        cls._validate(data)
        state = YbtState.from_bytes(data)
        print(state)
        return cls(state)


COMMAND_TYPES: dict[int, type[Command]] = {
    0x63: AssociationRsp,
    0x45: StatusRsp,
    0x5D: VersionRsp,
}


def parse_command(data: bytes) -> Command:
    """Parse data and return Command."""
    if len(data) != 18:
        raise InvalidCommand("Invalid length", data.hex())

    if command_type := COMMAND_TYPES.get(data[1]):
        return command_type.from_bytes(data)

    return UnknownResponse.from_bytes(data)
