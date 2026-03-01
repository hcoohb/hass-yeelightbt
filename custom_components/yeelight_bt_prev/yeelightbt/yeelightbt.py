"""
Creator : hcoohb
License : MIT
Source  : https://github.com/hcoohb/hass-yeelightbt
"""
from __future__ import annotations
from dataclasses import dataclass

# Standard imports
import codecs
import asyncio
import enum
import logging
import struct
from typing import Any, Callable, cast

# 3rd party imports
from bleak import BleakClient, BleakError, BleakScanner
from bleak.backends.client import BaseBleakClient
from bleak.backends.device import BLEDevice
from bleak_retry_connector import establish_connection
from homeassistant.core import HomeAssistant
from .connection import Connection, PairingStatus

COMMAND_STX = 0x43
CMD_PAIR = 0x67
CMD_PAIR_ON = 0x02
RES_PAIR = 0x63
CMD_POWER = 0x40
CMD_POWER_ON = 0x01
CMD_POWER_OFF = 0x02
CMD_COLOR = 0x41
CMD_BRIGHTNESS = 0x42
CMD_TEMP = 0x43
CMD_RGB = 0x41
CMD_GETSTATE = 0x44
CMD_GETSTATE_SEC = 0x02
RES_GETSTATE = 0x45
CMD_GETNAME = 0x52
RES_GETNAME = 0x53
CMD_GETVER = 0x5C
RES_GETVER = 0x5D
CMD_GETSERIAL = 0x5E
RES_GETSERIAL = 0x5F
RES_GETTIME = 0x62


class Model(enum.StrEnum):
    BEDSIDE = "Bedside"
    CANDELA = "Candela"


class Mode(enum.Enum):
    COLOR = 0x01
    WHITE = 0x02
    FLOW = 0x03


class Status(enum.Enum):
    ON = CMD_POWER_ON
    OFF = CMD_POWER_OFF


@dataclass
class YbtState:
    model: Model
    status: Status | None = None
    mode: Mode | None = None
    brightness: int = 0  # [1-100]
    temperature: int | None = None  # [1700-6500]
    rbg: tuple[int] | None = None  # [0-255]

    def parse_state(self, data: bytearray):
        state = struct.unpack(">xxBBBBBBBhx6x", data)
        self.status = Status(state[0])
        if self.model == Model.CANDELA:
            self.brightness = state[1]
            self.mode = Mode(state[2])
            # Not entirely sure this is the mode...
            # Candela seems to also give something in state 3 and 4...
        else:
            self.mode = Mode(state[1])  # Mode only given if connection is paired
            self.rgb = (state[2], state[3], state[4])  # , state[5])
            self.brightness = state[6]
            self.temperature = state[7]
        _LOGGER.info(f"YBT state: {self}")


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


class Conn(enum.Enum):
    DISCONNECTED = 1
    UNPAIRED = 2
    PAIRING = 3
    PAIRED = 4


_LOGGER = logging.getLogger(__name__)


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


class YeelightBT:
    """Representation of a Yeelight lamp"""

    def __init__(
        self,
        mac: str,
        model: Model,
        name: str,
        adapter: str,
        stay_connected: bool,
        use_notif: bool,
        hass: HomeAssistant,
    ):
        _LOGGER.debug(f"Initializing Yeelight Lamp {name} ({mac}) using adapter {adapter}")

        

        self._conn = Connection(
            mac=mac,
            name=name,
            adapter=adapter,
            stay_connected=stay_connected,
            use_notif=use_notif,
            hass=hass,
            callback=self._handle_notification,
        )
        # TODO can we remove hass?
        # TODO can we have notif default set based on model?
        self.name = name
        self._model = model
        self.state = YbtState(model=self._model)
        self._device_data = YbtData()
        self._on_update_callbacks: list = []

    def register_update_callback(self, on_update):
        self._on_update_callbacks.append(on_update)

    def shutdown(self):
        self._conn.shutdown()

    async def async_disconnect(self):
        await self._conn.async_disconnect()

    def _handle_notification(self, data: bytearray):
        """Handle Callback from a Bluetooth (GATT) request."""
        updated = True
        _LOGGER.debug(f"Received notif 0x{data.hex()} from device {self.name}")

        res_type = struct.unpack("xB16x", data)[0]  # the type of response we got
        if res_type == RES_GETSTATE:  # state result
            self.state.parse_state(data)

        elif res_type == RES_GETVER:
            self._device_data.parse_version(data)

        elif res_type == RES_GETSERIAL:
            self._device_data.parse_serial(data)

        # elif res_type == RES_PAIR:  # pairing result
        #     pair_mode = struct.unpack("xxB15x", data)[0]
        #     if pair_mode == 0x01:  # The lamp is requesting pairing. push small button!
        #         _LOGGER.error(
        #             "Yeelight pairing request: Push the little button of the lamp now! (All commands will be ignored until the lamp is paired)"
        #         )
        #     if pair_mode == 0x02:
        #         _LOGGER.debug("Yeelight pairing was successful!")
        #     if pair_mode == 0x03:
        #         _LOGGER.error(
        #             "Yeelight is not paired! The next connection will attempt a new pairing request."
        #         )
        #     if pair_mode == 0x04:
        #         _LOGGER.debug("Yeelight is already paired")
        #     if pair_mode == 0x06 or pair_mode == 0x07:
        #         # 0x07: Lamp disconnect imminent
        #         _LOGGER.error(
        #             "The pairing request returned unexpected results. Please reset the lamp (https://www.youtube.com/watch?v=PnjcOSgnbAM) and the pairing process will be attempted again on next connection."
        #         )
        else:
            updated = False
            _LOGGER.debug(
                "[%s] Unknown notification %s (%s)",
                self.name,
                data[0],
                codecs.encode(data, "hex"),
            )
        if updated:
            for callback in self._on_update_callbacks:
                callback()

    @property
    def pairing_status(self):
        return self._conn._pair_status

    @property
    def firmware_version(self) -> str | None:
        """Return the firmware version."""
        return self._device_data and self._device_data.version  # type: ignore

    @property
    def device_serial(self) -> str | None:
        """Return the device serial number."""
        return self._device_data and self._device_data.serial  # type: ignore

    @property
    def mac(self):
        """Return the mac address."""
        return self._conn._mac

    @property
    def model(self) -> str:
        return self._model

    @property
    def prop_min_max(self) -> dict[str, Any]:
        return {
            "brightness": {"min": 0, "max": 100},
            "temperature": {"min": 1700, "max": 6500},
            "color": {"min": 0, "max": 255},
        }

    async def async_update(self) -> None:
        """Request the state of the lamp (send back state through notif)"""
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_GETSTATE, CMD_GETSTATE_SEC)
        _LOGGER.debug("Send Cmd: Get_state")
        await self._conn.async_make_request(bits, wait_notif=True, pair_needed=False)

    async def set_pairing_mode(self) -> None:
        bits = bytearray(struct.pack("BBB15x", COMMAND_STX, CMD_PAIR, CMD_PAIR_ON))
        _LOGGER.debug("Send Cmd: Set pairing")
        # we send the actual pairing command:
        await self._conn.async_make_request(bits, wait_notif=True, pair_needed=False)

    async def wait_paired(self) -> None:
        # wait until the lamp is paired
        if self.pairing_status == PairingStatus.PAIRING:
            _LOGGER.debug("ybt wait paired started")
            await self._conn.wait_paired()
        _LOGGER.debug("ybt wait paired done")

    async def turn_on(self) -> None:
        """Turn the lamp on. (send back state through notif)"""
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_POWER, CMD_POWER_ON)
        _LOGGER.debug("Send Cmd: Turn On")
        await self._conn.async_make_request(bits, wait_notif=True)

    async def turn_off(self) -> None:
        """Turn the lamp off. (send back state through notif)"""
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_POWER, CMD_POWER_OFF)
        _LOGGER.debug("Send Cmd: Turn Off")
        await self._conn.async_make_request(bits, wait_notif=True)

    # set_brightness/temperature/color do NOT send a notification back.
    # However, the lamp takes time to transition to new state
    # and if another command (including get_state) is sent during that time,
    # it stops the transition where it is...
    async def set_brightness(self, brightness: int) -> None:
        """Set the brightness [1-100] (no notif)"""
        brightness = min(100, max(0, int(brightness)))
        _LOGGER.debug(f"Set_brightness {brightness}")
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_BRIGHTNESS, brightness)
        _LOGGER.debug("Send Cmd: Brightness")
        if await self._conn.async_make_request(bits, wait_notif=False):
            self._brightness = brightness

    async def set_temperature(self, kelvin: int, brightness: int | None = None) -> None:
        """Set the temperature (White mode) [1700 - 6500 K] (no notif)"""
        if brightness is None:
            brightness = self._brightness
        kelvin = min(6500, max(1700, int(kelvin)))
        _LOGGER.debug(f"Set_temperature {kelvin}, {brightness}")
        bits = struct.pack(">BBhB13x", COMMAND_STX, CMD_TEMP, kelvin, brightness)
        _LOGGER.debug("Send Cmd: Temperature")
        if await self._conn.async_make_request(bits, wait_notif=False):
            self._temperature = kelvin
            self._brightness = brightness
            self._mode = Mode.WHITE

    async def set_color(
        self, red: int, green: int, blue: int, brightness: int | None = None
    ) -> None:
        """Set the color of the lamp [0-255] (no notif)"""
        if brightness is None:
            brightness = self._brightness
        _LOGGER.debug(f"Set_color {(red, green, blue)}, {brightness}")
        bits = struct.pack(
            "BBBBBBB11x", COMMAND_STX, CMD_RGB, red, green, blue, 0x01, brightness
        )
        _LOGGER.debug("Send Cmd: Color")
        if await self._conn.async_make_request(bits, wait_notif=False):
            self._rgb = (red, green, blue)
            self._brightness = brightness
            self._mode = Mode.COLOR

    async def get_name(self) -> None:
        """Get the name from the lamp (through notif)"""
        bits = struct.pack("BB16x", COMMAND_STX, CMD_GETNAME)
        _LOGGER.debug("Send Cmd: Get_Name")
        await self._conn.async_make_request(bits)

    async def get_version(self) -> None:
        """Get the versions from the lamp (through notif)"""
        bits = struct.pack("BB16x", COMMAND_STX, CMD_GETVER)
        _LOGGER.debug("Send Cmd: Get_Version")
        await self._conn.async_make_request(bits)

    async def get_serial(self) -> None:
        """Get the serial from the lamp (through notif)"""
        bits = struct.pack("BB16x", COMMAND_STX, CMD_GETSERIAL)
        _LOGGER.debug("Send Cmd: Get_Serial")
        await self._conn.async_make_request(bits)
