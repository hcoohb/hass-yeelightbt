"""
Creator : hcoohb
License : MIT
Source  : https://github.com/hcoohb/hass-yeelightbt
"""

# Standard imports
from __future__ import annotations
from dataclasses import dataclass
import asyncio
import logging
from enum import IntEnum
import struct
from typing import Callable, cast, Any
from abc import ABC, abstractmethod

# Local imports
from .models import LampModel as Model, DeviceInfo, DisconnectReason
from .errors import InvalidCommand, YBTError, Timeout, Disconnected, NotConnected

# 3rd party imports
from bleak import BleakClient
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData
from bleak_retry_connector import (
    BLEAK_RETRY_EXCEPTIONS,
    BleakClientWithServiceCache,
    establish_connection,
    retry_bluetooth_connection_error,
)

_LOGGER = logging.getLogger(__name__)


DEFAULT_ATTEMPTS = 3

DISCONNECT_DELAY = 300

PROP_WRITE_UUID = "aa7d3f34-2d4f-41e0-807f-52fbf8cf7443"
PROP_NTFY_UUID = "8f65073d-9f57-4aaa-afea-397d19d5bbeb"


@dataclass
class YbtData:
    version: str | None = None
    serial: str | None = None

    def parse_version(self, data):
        self.version = cast(str, struct.unpack("xxBHHHH6x", data))
        _LOGGER.info(f"YBT exposes versions: {self.version}")

    def parse_serial(self, data):
        serial = str(struct.unpack("xxB15x", data)[0]).strip()
        self.serial = serial.replace("(", "").replace(")", "").replace(", ", ".")
        _LOGGER.info(f"YBT exposes serial: {self.serial}")


class AuthStatus(IntEnum):
    NOT_PAIRED = 1
    PAIRING = 2
    PAIRED = 3


class AuthRspStatus(IntEnum):
    """Status report type"""

    REQUESTING_PAIR = 0x01
    SUCCESSFULLY_PAIRED = 0x02
    NOT_PAIRED = 0x03
    ALREADY_PAIRED = 0x04
    DISCONNECTING_NOW = 0x06  # factory reset required
    DISCONNECTING_SOON_2 = 0x07


class Power(IntEnum):
    ON = 0x01
    OFF = 0x02


class Mode(IntEnum):
    COLOR = 0x01
    WHITE = 0x02
    FLOW = 0x03


class VersionRunning(IntEnum):
    APP1 = 0x01
    APP2 = 0x02
    CANDELA = 0x31


@dataclass
class Versions:
    current_running: VersionRunning
    hw_version: int
    sw_version_app1: int
    sw_version_app2: int
    beacon_version: int


def ybt_model_from_ble_name(ble_name: str) -> Model:
    model = Model.CANDELA  # default to candela
    if ble_name.startswith("XMCTD_"):
        model = Model.BEDSIDE
    if ble_name.startswith("yeelight_ms"):
        model = Model.CANDELA
    return model


def ybt_display_name(ble_name: str, address: str) -> str:
    # Model and last 4 from the mac address
    model = ybt_model_from_ble_name(ble_name)
    return f"{model}_{address.replace(':', '')[-4:]}"


class BaseCommand(ABC):
    """Base class for procedures."""

    need_auth = True
    cmd_id = None
    cmd_format = None
    cmd_data = None
    response = None

    def __init__(self, lamp: YeelightBT) -> None:
        """Initialize."""
        if self.cmd_id is None:
            _LOGGER.error("CMD_ID error | not defined")
            raise ValueError
        self._lamp: YeelightBT = lamp

    @property
    def _header(self) -> bytes:
        """Return packed header."""
        return struct.pack(">BB", 0x43, self.cmd_id)  # big endian format

    def set_data(self, data_list: list):
        self.cmd_data = data_list

    def _pack(self) -> bytes:
        """Pack the command to bytes."""
        if self.cmd_format and not self.cmd_data:
            _LOGGER.error(
                f"PACKING error | {self.__class__.__name__} | format:{self.cmd_format}, data:{self.cmd_data}"
            )
            raise ValueError
        fmt = "" if self.cmd_format is None else self.cmd_format
        data = [] if self.cmd_data is None else self.cmd_data
        if not fmt.startswith(">"):
            fmt = ">" + fmt  # big endian format
        # add end padding
        if (fmt_len := struct.calcsize(fmt)) < 16:
            fmt = f"{fmt}{16-fmt_len}x"
        return self._header + struct.pack(fmt, *data)

    async def execute(self) -> bool:
        """Execute the procedure"""
        cmd_bytes = self._pack()
        _LOGGER.debug(f"TX: {cmd_bytes.hex()} | ({self.__class__.__name__})")
        await self._lamp.send_cmd(cmd_bytes)
        return True


class BaseResponse(ABC):
    rsp_id: int | None = None
    rsp_format: str | None = None
    rsp_packets: int = 1

    def __init__(self, lamp: YeelightBT) -> None:
        """Initialize."""
        if self.rsp_id is None:
            _LOGGER.error(f"RSP_ID error | not defined for {self.__class__.__name__}")
            raise ValueError
        self._lamp = lamp

    def _unpack(self, data: bytes) -> tuple:
        if not self.rsp_format:
            _LOGGER.error(
                f"UNPACKING error | {self.__class__.__name__} | no format definied :{self.rsp_format}"
            )
            raise ValueError
        fmt = self.rsp_format
        fmt = fmt if fmt.startswith(">") else (">" + fmt)
        return struct.unpack_from(fmt, data, 2)

    @abstractmethod
    def extract(self, data: bytes):
        pass


@dataclass
class YbtState:
    power: Power | None = None
    mode: Mode | None = None
    brightness: int = 0  # [1-100]
    temperature: int | None = None  # [1700-6500]
    rgb: tuple[int, int, int] | None = None  # [0-255]


class AuthResponse(BaseResponse):
    rsp_id = 0x63
    rsp_format = "B"

    def extract(self, data: bytes) -> AuthRspStatus:
        status = AuthRspStatus(self._unpack(data)[0])
        return status


class AuthCommand(BaseCommand):
    """Authentication of the lamp ."""

    need_auth = False
    cmd_id = 0x67
    cmd_format = "B"
    cmd_data = [0x02]
    response = AuthResponse

    # -> AuthCommand
    # <- AuthResponse


class StateResponse(BaseResponse):
    rsp_id = 0x45
    rsp_format = "BBBBBxBH"

    def extract(self, data: bytes) -> YbtState:
        """Initialize from serialized representation."""
        state = YbtState()
        res = self._unpack(data)
        state.power = Power(res[0])

        # if self_lamp.model == Model.CANDELA:
        #     self.brightness = res[1]
        #     self.mode = Mode(res[2])
        #     # Not entirely sure this is the mode...
        #     # Candela seems to also give something in state 3 and 4...
        # else:
        state.mode = Mode(res[1])  # Mode only given if connection is paired
        rgb = (res[2], res[3], res[4])
        state.rgb = rgb
        state.brightness = res[5]
        state.temperature = res[6]
        _LOGGER.info(f"Data {data.hex()}")
        _LOGGER.info(
            f"R:{res[2]}, G:{res[3]}, B:{res[4]}_{rgb}_{state.rgb}- Temp:{res[6]}"
        )
        _LOGGER.info(f"YBT state: {self}")
        # 01 01 64 64 64 00 22 00001f000000000000
        # YbtState(power=<Power.ON: 1>, mode=<Mode.COLOR: 1>, brightness=34, temperature=7936, rbg=None)
        # 01  01  64 64 64  00  22  0000  1e000000000000
        # YbtState(power=<Power.ON: 1>, mode=<Mode.COLOR: 1>, brightness=34, temperature=7680, rbg=None)
        return state


class GetStateCommand(BaseCommand):
    """Get lamp state."""

    need_auth = True  # if False, we will get an answer but lamp disconnects in 7s
    cmd_id = 0x44
    cmd_format = "B"
    cmd_data = [0x02]
    response = StateResponse

    # -> GetStateCommand
    # <- StateResponse


class SetPowerCommand(BaseCommand):
    """Power up or down the lamp status."""

    need_auth = True  # if not auth before, it will disconnect
    cmd_id = 0x40
    cmd_format = "B"
    response = StateResponse

    # Power procedure:
    # -> SetPowerCommand
    # <- StateResponse

    def __init__(self, lamp: YeelightBT, power: Power) -> None:
        """Initialize."""
        super().__init__(lamp)
        self.set_data([power])


class SetBrightnessCommand(BaseCommand):
    """Set the brightness of the light"""

    need_auth = True
    cmd_id = 0x42
    cmd_format = "B"  # [0-100] in one byte
    response = None

    # procedure:
    # -> SetBrightnessCommand
    # (no response) but transition takes time so await
    # No effect if lamp is off!
    # Brightness at 0 leaves it unchanged

    def __init__(self, lamp: YeelightBT, brightness: int) -> None:
        """Setting brightness [0-100]."""
        super().__init__(lamp)
        self.set_data([brightness])

    async def execute(self) -> bool:
        """Execute the procedure"""
        await super().execute()
        await asyncio.sleep(0.6)
        return True


class SetTempCommand(BaseCommand):
    """Set the temperature brightness of the light"""

    need_auth = True
    cmd_id = 0x43
    # [1700 - 6500 K] in two bytes, [0-100] in one byte , big-endian format
    cmd_format = "hB"
    response = None

    # -> SetTempCommand
    # (no response) but transition takes time so await
    # No effect if lamp is off!
    # Change to WHITE mode
    # Brightness at 0 leaves it unchanged

    def __init__(self, lamp: YeelightBT, temp_kelvin: int, brightness: int) -> None:
        """Setting temperature [1700 - 6500] and brightness [0-100]."""
        super().__init__(lamp)
        temp_kelvin = min(6500, max(1700, int(temp_kelvin)))
        brightness = min(100, max(0, int(brightness)))
        self.set_data([temp_kelvin, brightness])

    async def execute(self) -> bool:
        """Execute the procedure"""
        await super().execute()
        await asyncio.sleep(0.6)
        return True


class SetColorCommand(BaseCommand):
    """Set the Color brightness of the light"""

    need_auth = True
    cmd_id = 0x41
    # R[0-255], G[0-255], B[0-255], 0x01, brightness[0-100]
    cmd_format = "BBBBB"
    response = None

    # -> ColorCommand
    # (no response) but transition takes time so await
    # No effect if lamp is off!
    # Change to WHITE mode
    # Brightness at 0 leaves it unchanged

    def __init__(
        self, lamp: YeelightBT, red: int, green: int, blue: int, brightness: int
    ) -> None:
        """Setting color R[0-255], G[0-255], B[0-255], and brightness [0-100]."""
        super().__init__(lamp)
        red = min(255, max(0, int(red)))
        green = min(255, max(0, int(green)))
        blue = min(255, max(0, int(blue)))
        brightness = min(100, max(0, int(brightness)))
        self.set_data([red, green, blue, 0x01, brightness])

    async def execute(self) -> bool:
        """Execute the procedure"""
        await super().execute()
        await asyncio.sleep(0.6)
        return True


# Does not seem to work ????
# class SerialResponse(BaseResponse):
#     rsp_id = 0x5F
#     rsp_format = "B"

#     def extract(self, data: bytes):
#         """Initialize from serialized representation."""
#         # state = struct.unpack(">xxBBBBBBBhx6x", data)
#         # instance.power = Power(state[0])
#         _LOGGER.info(f"Serial data: {data}")


# class GetSerialCommand(BaseCommand):
#     """Get lamp serial."""

#     need_auth = True
#     cmd_id = 0x5E
#     response = SerialResponse


class VersionsResponse(BaseResponse):
    rsp_id = 0x5D
    rsp_format = "BHHHH"

    def extract(self, data: bytes) -> Versions:
        """Initialize from serialized representation."""
        vers = self._unpack(data)
        vers[0] = VersionRunning(vers[0])
        ver = Versions(*vers)
        _LOGGER.info(f"Version: {ver} from data: {data}")
        return ver


class GetVersionsCommand(BaseCommand):
    """Get lamp versions."""  # will send rsp if not, but will also disconnect in 7s

    need_auth = True
    cmd_id = 0x5C
    response = VersionsResponse

    # -> GetVersionsCommand
    # <- VersionsResponse


class NameResponse(BaseResponse):
    rsp_id = 0x53
    rsp_format = "xBx13sxxxBx13s"  # 2 pckts, only first header already removed [idx0, str0, idx1, str1]
    rsp_packets = 2
    # two consecutive responses. 4th byte is the index.
    # data = b"CQ\x01\x00\rYeelight Beds"
    # data2 = b"CQ\x01\x01\x08ide Lamp\x00\x00\x00\x00\x00"
    # notif handler concatenate the messages, assuming in correct order

    def extract(self, data: bytes) -> str:
        """Initialize from serialized representation."""
        res = self._unpack(data)
        name = res[1].decode("ascii") + res[3].decode("ascii")
        return name


class GetNameCommand(BaseCommand):
    """Get lamp Name."""

    need_auth = True  # if False, we will get an answer but lamp disconnects in 7s
    cmd_id = 0x52
    response = NameResponse

    # -> GetNameCommand
    # <- NameResponse
    # <- NameResponse


class SetNameCommand(BaseCommand):
    """Set lamp Name."""

    need_auth = True  # if False, it will perform action but lamp disconnects in 7s
    cmd_id = 0x51
    cmd_format = "BBB13s"

    def __init__(self, lamp: YeelightBT, name: str) -> None:
        """Setting lamp name."""
        super().__init__(lamp)
        self.name: bytes = name[:26].encode("utf-8")

    async def execute(self) -> bool:
        """Execute the procedure"""
        self.set_data([0x01, 0x00, 0x0D, self.name[0:13]])
        await super().execute()
        self.set_data([0x01, 0x01, 0x08, self.name[13:]])
        await super().execute()


class GetStatsCommand(BaseCommand):
    need_auth = True  # ??
    cmd_id = 0x8C
    # -> GetStatsCommand
    # <- Stats1Rsp 438d00000000000000060000000000000000
    # <- Stats2Rsp 438e00000000000000000000000000000000
    # <- Stats3Rsp 438f00000000000000000000000000000000
    # <- Stats4Rsp 439000000000000000000000000000000000
    # <- Stats5Rsp 439100000000000000000000000000000000


class FactoryResetResponse(BaseResponse):
    rsp_id = 0x82
    rsp_format = "xB"
    # 438243740100000000000000000000000000 # factory reset ok?
    # 438243540100000000000000000000000000 # enabling beacon ?

    def extract(self, data: bytes) -> str:
        """Initialize from serialized representation."""
        res = self._unpack(data)
        _LOGGER.info(f"FactoryReset: code {res[0]} from data: {data}")
        return res[0]


class FactoryResetCommand(BaseCommand):
    """Get lamp versions."""  # will send rsp if not, but will also disconnect in 7s

    need_auth = True  # TODO: I think needs yes
    cmd_id = 0x74
    response = FactoryResetResponse

    # -> FactoryResetRequestCmd
    # <- FactoryResetRsp1
    # <- FactoryResetRsp2


class YeelightBT:
    """Manage of a Yeelight lamp"""

    def __init__(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData | None = None
    ):
        """Initialize."""
        self._advertisement_data = advertisement_data
        self._authenticated: bool = False
        self._auth_status: AuthStatus = AuthStatus.NOT_PAIRED
        self._ble_device = ble_device
        self._callbacks: list[Callable[[YbtState], None]] = []
        self._client: BleakClient | None = None
        self._reponse_handlers: dict[BaseResponse, callable] = {}
        self._reponse_handlers_once: dict[BaseResponse, asyncio.Future] = {}
        self._response_counters: dict[int, list[bytes]] = {}
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._notif_enabled: bool = True
        self._expected_disconnect: bool = False
        self._disconnect_reason: DisconnectReason | None = None
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._procedure_lock: asyncio.Lock = asyncio.Lock()
        self.loop = asyncio.get_running_loop()
        self.device_info = DeviceInfo()

        # Adding a handler for state notifs
        def handle_state_notif(state: YbtState):
            _LOGGER.debug(f"Calling callbacks with status: {state}")
            for callback in self._callbacks:
                callback(state)

        def handle_auth_notif(rsp_status: AuthRspStatus):
            _LOGGER.debug(f"Auth_rsp_handler with: <{rsp_status.name}: {rsp_status}>")
            self._auth_status = self._auth_resp_to_auth_status(rsp_status)

        self._add_response_handler(AuthResponse, handle_auth_notif)
        self._add_response_handler(StateResponse, handle_state_notif)

    @staticmethod
    def _auth_resp_to_auth_status(auth_resp: AuthRspStatus) -> AuthStatus:
        if (
            auth_resp == AuthRspStatus.ALREADY_PAIRED
            or auth_resp == AuthRspStatus.SUCCESSFULLY_PAIRED
        ):
            status = AuthStatus.PAIRED
        elif auth_resp == AuthRspStatus.REQUESTING_PAIR:
            status = AuthStatus.PAIRING
        else:
            status = AuthStatus.NOT_PAIRED
        return status

    def set_ble_device_and_advertisement_data(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData
    ) -> None:
        """Set the ble device."""
        self._ble_device = ble_device
        self._advertisement_data = advertisement_data

    @property
    def address(self) -> str:
        """Get the address of the device."""
        return str(self._ble_device.address)

    @property
    def name(self) -> str:
        """Get the name of the device."""
        return str(self._ble_device.name or self._ble_device.address)

    @property
    def rssi(self) -> int | None:
        """Get the rssi of the device."""
        if self._advertisement_data:
            return self._advertisement_data.rssi
        return None

    @property
    def prop_min_max(self) -> dict[str, Any]:
        return {
            "brightness": {"min": 0, "max": 100},
            "temperature": {"min": 1700, "max": 6500},
            "color": {"min": 0, "max": 255},
        }

    async def set_name(self, name):
        cmd = SetNameCommand(self, name)
        await self._execute(cmd)

    async def get_state(self) -> YbtState:
        """Update the Lamp status."""
        _LOGGER.debug("%s: get_state", self.name)
        cmd = GetStateCommand(self)
        res = await self._execute(cmd)
        print(f"get_state_res {res}")
        return res

    async def turn_on(self) -> YbtState:
        """Turn on the lamp."""
        _LOGGER.debug("%s: Turn on", self.name)
        proc = SetPowerCommand(self, Power.ON)
        return await self._execute(proc)

    async def turn_off(self) -> YbtState:
        """Turn off the lamp."""
        _LOGGER.debug("%s: Turn off", self.name)
        proc = SetPowerCommand(self, Power.OFF)
        return await self._execute(proc)

    async def set_brightness(self, brightness: int) -> None:
        """Set the brightness of the lamp [0-100]."""
        _LOGGER.debug("%s: Setting brightness to %d", self.name, brightness)
        # TODO: clamp value
        proc = SetBrightnessCommand(self, int(brightness))
        await self._execute(proc)

    async def set_temperature(self, temp_kelvin: int, brightness: int) -> None:
        """Set temperature [1700 - 6500] and brightness [0-100]."""
        # _LOGGER.debug("%s: Setting brightness to %d", self.name, brightness)
        # TODO: clamp values
        proc = SetTempCommand(self, int(temp_kelvin), int(brightness))
        await self._execute(proc)

    async def set_color(self, red: int, green: int, blue: int, brightness: int) -> None:
        """Set temperature [1700 - 6500] and brightness [0-100]."""
        # _LOGGER.debug("%s: Setting brightness to %d", self.name, brightness)
        proc = SetColorCommand(self, int(red), int(green), int(blue), int(brightness))
        await self._execute(proc)

    async def authenticate(self) -> AuthRspStatus:
        """Authenticate the lamp with notif.
        Return Auth status"""
        _LOGGER.debug("%s: authenticate", self.name)
        proc = AuthCommand(self)
        rsp_status = await self._execute(proc)
        return self._auth_resp_to_auth_status(rsp_status)

    async def authenticate_no_notif(self) -> callable[[],]:
        """Authenticate the lamp.
        If the lamp works with no notif, a callback is return.
        The callback MUST be called once the lamp has been manually paired"""
        _LOGGER.debug("%s: authenticate no notif", self.name)
        # if notif are used, execute as usual
        # if no notif, we are in pairing mode until the given callback is called
        proc = AuthCommand(self)
        self._auth_status = AuthStatus.PAIRING
        await self._execute(proc)  # set in pairing more
        await asyncio.sleep(0.1)

        # define callback to ensure pairing
        def paired_cb():
            self._auth_status = AuthStatus.PAIRED

        return paired_cb

    # async def get_serial(self) -> bool:
    #     """Update the lamp serial."""
    #     proc = GetVersionsCommand(self)
    #     return await self._execute(proc)

    async def get_versions(self) -> Versions:
        """Update the lamp versions."""
        proc = GetVersionsCommand(self)
        res = await self._execute(proc)
        return res

    async def get_name(self) -> str:
        """Update the lamp name."""
        proc = GetNameCommand(self)
        return await self._execute(proc)

    async def get_stats(self) -> None:
        await self._execute(GetStatsCommand(self))

    async def factory_reset(self) -> None:
        proc = FactoryResetCommand(self)
        await self._execute(proc)

    # def _disconnect(self, reason: DisconnectReason) -> None:
    #     """Disconnect from device."""
    #     asyncio.create_task(self._execute_disconnect(reason))

    # async def _execute_disconnect(self, reason: DisconnectReason) -> None:
    #     """Execute disconnection."""
    #     _LOGGER.debug("%s: Execute disconnect", self.name)
    #     if self._connect_lock.locked():
    #         _LOGGER.debug(
    #             "%s: Connection already in progress, waiting for it to complete; "
    #             "RSSI: %s",
    #             self.name,
    #             self.rssi,
    #         )
    #     async with self._connect_lock:
    #         client = self._client
    #         self._client = None
    #         if client and client.is_connected:
    #             self._expected_disconnect = True
    #             await client.stop_notify(CHARACTERISTIC_UUID_TO_SERVER)
    #             await client.stop_notify(CHARACTERISTIC_UUID_FROM_SERVER)
    #             await client.disconnect()
    #         self._reset(reason)
    #     _LOGGER.debug("%s: Execute disconnect done", self.name)

    async def send_cmd(self, data: bytes) -> None:
        """Send a command."""

        self._raise_if_not_connected()
        assert self._client
        await self._client.write_gatt_char(PROP_WRITE_UUID, data, response=True)

    async def _ensure_connected(self) -> None:
        """Ensure connection to device is established."""
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete; "
                "RSSI: %s",
                self.name,
                self.rssi,
            )
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return
        async with self._connect_lock:
            # Check again while holding the lock
            if self._client and self._client.is_connected:
                self._reset_disconnect_timer()
                return
            # no current connection
            _LOGGER.debug("%s: Connecting; RSSI: %s", self.name, self.rssi)
            client = await establish_connection(
                client_class=BleakClientWithServiceCache,
                device=self._ble_device,
                name=self.name,
                disconnected_callback=self._disconnected,
                use_services_cache=True,
                ble_device_callback=lambda: self._ble_device,
            )
            _LOGGER.debug("%s: Connected; RSSI: %s", self.name, self.rssi)
            # services = client.services
            # for service in services:
            #    _LOGGER.debug("%s:service: %s", self.name, service.uuid)
            #    characteristics = service.characteristics
            #    for char in characteristics:
            #        _LOGGER.debug("%s:characteristic: %s", self.name, char.uuid)
            # resolved = self._resolve_characteristics(client.services)
            # if not resolved:
            #    # Try to handle services failing to load
            #    resolved = self._resolve_characteristics(await client.get_services())

            self._client = client
            self._disconnect_reason = None
            self._reset_disconnect_timer()

            _LOGGER.debug(
                "%s: Subscribe to notifications; RSSI: %s", self.name, self.rssi
            )
            await client.start_notify(PROP_NTFY_UUID, self._notif_handler)

    async def _notif_handler(
        self, characteristic: BleakGATTCharacteristic, data: bytes
    ) -> None:
        """Notification handler."""
        self._reset_disconnect_timer()
        if len(data) < 2:
            _LOGGER.warning("Received invalid notif %s", data.hex())
            self._disconnect(DisconnectReason.INVALID_COMMAND)
            return

        try:
            if len(data) != 18:
                raise InvalidCommand("Invalid reponse length", data.hex())
            if data[0] != 0x43:
                raise InvalidCommand("Invalid reponse header", data.hex())
            rsp_id = data[1]
        except InvalidCommand as err:
            _LOGGER.warning("Received invalid response %s", err)
            self._disconnect(DisconnectReason.INVALID_COMMAND)
            return
        # check if response is needed in any handlers:
        rsps = list(self._reponse_handlers.keys()) + list(
            self._reponse_handlers_once.keys()
        )
        rsp_id_map = {rsp.rsp_id: rsp for rsp in rsps}
        if not (rsp_cls := rsp_id_map.get(rsp_id)):
            # the rsp_id is not in any stored response
            _LOGGER.warning(
                f"RX: {data.hex()} | UNKNOWN notif | h{characteristic.handle:#04x}"
            )
            return
        packets = self._response_counters.get(rsp_id, [])
        packets.append(data)
        if rsp_cls.rsp_packets > len(packets):
            # we haven't received all packets for the response
            self._response_counters[rsp_id] = packets
            _LOGGER.debug(
                f"RX: {data.hex()} | ({rsp_cls.__name__}) | h{characteristic.handle:#04x} -- incomplete response"
            )
            return

        result = rsp_cls(self).extract(b"".join(packets))
        self._response_counters[rsp_id] = []
        _LOGGER.debug(
            f"RX: {data.hex()} | ({rsp_cls.__name__}) | h{characteristic.handle:#04x} -- res: {result}"
        )
        if handler := self._reponse_handlers.get(rsp_cls):
            handler(result)
        if fut := self._reponse_handlers_once.pop(rsp_cls, False):
            if not fut.done():
                fut.set_result(result)

    def _raise_if_not_connected(self) -> None:
        """Raise if the connection to device is lost."""
        if self._client and self._client.is_connected:
            self._reset_disconnect_timer()
            return
        raise NotConnected

    def _reset_disconnect_timer(self) -> None:
        """Reset disconnect timer."""
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._expected_disconnect = False
        self._disconnect_timer = self.loop.call_later(
            DISCONNECT_DELAY, self._timed_disconnect
        )

    def _disconnected(self, client: BleakClient) -> None:
        """Disconnected callback."""
        if self._expected_disconnect:
            _LOGGER.debug(
                "%s: Disconnected from device; RSSI: %s", self.name, self.rssi
            )
            return
        _LOGGER.warning(
            "%s: Device unexpectedly disconnected; RSSI: %s",
            self.name,
            self.rssi,
        )
        # we continue the disconnect only if we were connected before
        _LOGGER.debug(client)
        _LOGGER.debug(self._client)
        self._client = None

        self._disconnect(DisconnectReason.UNEXPECTED)

    async def disconnect(self) -> None:
        await self._execute_disconnect(DisconnectReason.USER_REQUESTED)

    def _disconnect(self, reason: DisconnectReason) -> None:
        """Disconnect from device."""
        asyncio.create_task(self._execute_disconnect(reason))

    async def _execute_disconnect(self, reason: DisconnectReason) -> None:
        """Execute disconnection."""
        _LOGGER.debug("%s: Execute disconnect", self.name)
        if self._connect_lock.locked():
            _LOGGER.debug(
                "%s: Connection already in progress, waiting for it to complete; "
                "RSSI: %s",
                self.name,
                self.rssi,
            )
        async with self._connect_lock:
            client = self._client
            self._client = None
            if client and client.is_connected:
                self._expected_disconnect = True
                await client.stop_notify(PROP_NTFY_UUID)
                await client.disconnect()
            self._reset(reason)
        _LOGGER.debug("%s: Execute disconnect done", self.name)

    def _timed_disconnect(self) -> None:
        """Disconnect from device."""
        self._disconnect_timer = None
        asyncio.create_task(self._execute_timed_disconnect())

    async def _execute_timed_disconnect(self) -> None:
        """Execute timed disconnection."""
        _LOGGER.debug(
            "%s: Disconnecting after timeout of %s",
            self.name,
            DISCONNECT_DELAY,
        )
        await self._execute_disconnect(DisconnectReason.TIMEOUT)

    def _reset(self, reason: DisconnectReason) -> None:
        """Reset."""
        _LOGGER.debug("%s: reset", self.name)
        self._auth_status = AuthStatus.NOT_PAIRED
        for fut in self._reponse_handlers_once.values():
            fut.cancel()
        self._reponse_handlers_once = {}
        self._response_counters = {}
        self._disconnect_reason = reason
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._disconnect_timer = None

    def _add_response_handler(self, rsp_class: type[BaseResponse], handler: Callable):
        self._reponse_handlers[rsp_class] = handler

    def receive_notif_once(self, rsp_class: type[BaseResponse]) -> asyncio.Future:
        """Receive a response once."""
        fut: asyncio.Future = asyncio.Future()
        self._reponse_handlers_once[rsp_class] = fut

        return fut

    @retry_bluetooth_connection_error(DEFAULT_ATTEMPTS)  # type: ignore[misc]
    async def _execute(self, procedure: BaseCommand) -> bool:
        """Execute a procedure."""
        if self._procedure_lock.locked():
            _LOGGER.debug(
                "%s: Procedure already in progress, ignoring while waiting for it to complete; "
                "RSSI: %s",
                self.name,
                self.rssi,
            )
        async with self._procedure_lock:
            try:
                await self._ensure_connected()
                if procedure.need_auth:
                    await self._enusure_authenticated()
                    if self._auth_status != AuthStatus.PAIRED:
                        # still not paired, let's cancel this cmd that need auth
                        _LOGGER.warning(
                            f"{procedure.__class__} cancelled as auth needed while it is <{self._auth_status.name}: {self._auth_status}>"
                        )
                        return

                if procedure.response and self._notif_enabled:
                    rsp_fut = self.receive_notif_once(procedure.response)
                    await procedure.execute()
                    result = await rsp_fut
                    return result
                else:
                    return await procedure.execute()
            except asyncio.CancelledError as err:
                if self._disconnect_reason is None:
                    raise YBTError from err
                if self._disconnect_reason == DisconnectReason.TIMEOUT:
                    raise Timeout from err
                raise Disconnected(self._disconnect_reason) from err
            except YBTError:
                self._disconnect(DisconnectReason.ERROR)
                raise

    async def _enusure_authenticated(self) -> None:
        """Ensure we have associated with the lamp"""
        if self._auth_status == AuthStatus.PAIRED:
            return
        # _ensure_authenticated is only called when other command that needs auth got called
        # NOT when the main "association" method is run.
        # so if notif not enabled, we send command and ASSUME we have authenticated
        # if notif enabled, we await the first reponse, but _auth_status updated by auth handler
        cmd = AuthCommand(self)
        if self._notif_enabled:
            rsp_fut = self.receive_notif_once(cmd.response)
            await cmd.execute()
            await rsp_fut
        else:
            self._auth_status = AuthStatus.PAIRING
            await cmd.execute()
            await asyncio.sleep(0.1)
            self._auth_status = AuthStatus.PAIRED

    def register_state_callback(
        self, callback: Callable[[YbtState], None]
    ) -> Callable[[], None]:
        """Register a callback to be called when the state changes."""

        def unregister_callback() -> None:
            self._callbacks.remove(callback)

        self._callbacks.append(callback)
        return unregister_callback
