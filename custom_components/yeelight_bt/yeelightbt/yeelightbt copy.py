"""
Creator : hcoohb
License : MIT
Source  : https://github.com/hcoohb/hass-yeelightbt
"""


# Standard imports
from __future__ import annotations
from dataclasses import dataclass
import codecs
import asyncio
import enum
import logging
import struct
from typing import Any, Callable, cast
from abc import ABC, abstractmethod

# Local imports
# from .connection import Connection, PairingStatus
from .models import LampModel as Model, DeviceInfo, DisconnectReason
from .commands import _CMD_T, Command, parse_command, YbtState
from . import commands as cmds
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

DISCONNECT_DELAY = 30

PROP_WRITE_UUID = "aa7d3f34-2d4f-41e0-807f-52fbf8cf7443"
PROP_NTFY_UUID = "8f65073d-9f57-4aaa-afea-397d19d5bbeb"



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




class Status(enum.Enum):
    ON = CMD_POWER_ON
    OFF = CMD_POWER_OFF


# @dataclass
# class YbtState:
#     model: Model
#     status: Status | None = None
#     mode: Mode | None = None
#     brightness: int = 0  # [1-100]
#     temperature: int | None = None  # [1700-6500]
#     rbg: tuple[int] | None = None  # [0-255]

#     def parse_state(self, data: bytearray):
#         state = struct.unpack(">xxBBBBBBBhx6x", data)
#         self.status = Status(state[0])
#         if self.model == Model.CANDELA:
#             self.brightness = state[1]
#             self.mode = Mode(state[2])
#             # Not entirely sure this is the mode...
#             # Candela seems to also give something in state 3 and 4...
#         else:
#             self.mode = Mode(state[1])  # Mode only given if connection is paired
#             self.rgb = (state[2], state[3], state[4])  # , state[5])
#             self.brightness = state[6]
#             self.temperature = state[7]
#         _LOGGER.info(f"YBT state: {self}")


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


class BaseProcedure(ABC):
    """Base class for procedures."""

    enable_notifications: bool = False
    need_auth: bool = False

    def __init__(self, lamp: YeelightBT) -> None:
        """Initialize."""
        self._lamp = lamp

    @abstractmethod
    async def execute(self) -> bool:
        """Execute the procedure"""


class NullProcedure(BaseProcedure):
    """Do nothing."""

    enable_notifications = True
    need_auth = True

    async def execute(self) -> bool:
        """Execute the procedure"""
        return True


class AssociationProcedure(BaseProcedure):
    """Associate to the lamp ."""

    enable_notifications = False
    need_auth = False

    # Unlock procedure:
    # -> AssociationCmd
    # <- AssociationRsp

    async def execute(self) -> bool:
        """Execute the procedure"""
        ass_rsp_fut = self._lamp.receive_once(cmds.AssociationRsp)
        await self._lamp.send_cmd(cmds.AssociationCmd())
        await ass_rsp_fut
        print(ass_rsp_fut.result())
        print("finished Association")

        return True


class StatusProcedure(BaseProcedure):
    """Get lamp status."""

    enable_notifications = False
    need_auth = False

    # Unlock procedure:
    # -> StatusRequestCmd
    # <- StatusRequestRsp (handled in general notif)

    async def execute(self) -> bool:
        """Execute the procedure"""
        # unlock_rsp_fut = self._lock.receive_once(cmds.UnlockRsp)
        await self._lamp.send_cmd(cmds.StatusRequestCmd())
        # await unlock_rsp_fut

        return True


class PowerProcedure(BaseProcedure):
    """Power up or down the lamp status."""

    enable_notifications = False
    need_auth = True

    # Power procedure:
    # -> PowerCmd
    # <- StatusRsp

    def __init__(self, lamp: YeelightBT, power: cmds.Power) -> None:
        """Initialize."""
        super().__init__(lamp)
        self._power = power

    async def execute(self) -> bool:
        """Execute the procedure"""
        # unlock_rsp_fut = self._lock.receive_once(cmds.UnlockRsp)
        await self._lamp.send_cmd(cmds.PowerCmd(self._power))
        # await unlock_rsp_fut

        return True



class BrightnessProcedure(BaseProcedure):
    """Set the brightness of the light"""

    enable_notifications = False
    need_auth = True

    # procedure:
    # -> BrightnessCmd
    # (no response) but transition takes time so await
    # No effect if lamp is off!

    def __init__(self, lamp: YeelightBT, brightness: int) -> None:
        """Setting brightness [0-100]."""
        super().__init__(lamp)
        self._brightness = brightness

    async def execute(self) -> bool:
        """Execute the procedure"""
        await self._lamp.send_cmd(cmds.BrightnessCmd(self._brightness))
        await asyncio.sleep(0.2)
        return True



class TempProcedure(BaseProcedure):
    """Set the temperature brightness of the light"""

    enable_notifications = False
    need_auth = True

    # procedure:
    # -> TemperatureCmd
    # (no response) but transition takes time so await
    # No effect if lamp is off!

    def __init__(self, lamp: YeelightBT, temp_kelvin:int, brightness: int) -> None:
        """Setting temperature [1700 - 6500] and brightness [0-100]."""
        super().__init__(lamp)
        self._kelvin = temp_kelvin
        self._brightness = brightness

    async def execute(self) -> bool:
        """Execute the procedure"""
        await self._lamp.send_cmd(cmds.TemperatureCmd(self._kelvin, self._brightness))
        await asyncio.sleep(0.2)
        return True

# class ChangeModeProcedure(BaseProcedure):
#     """Change mode of a lock."""

#     enable_notifications = True
#     need_auth = True

#     # Change mode procedure:
#     # -> ChangeModeCmd
#     # <- StatusReportCmd (if lock/unlock)

#     def __init__(self, lock: DKEYLock, mode: cmds.LockMode) -> None:
#         """Initialize."""
#         super().__init__(lock)
#         self._mode = mode

#     async def execute(self) -> bool:
#         """Execute the procedure"""

#         await self._lock.send_cmd(cmds.ChangeModeCmd(self._mode))

#         return True

class YeelightBT:
    """Manage of a Yeelight lamp"""
    def __init__(
        self, ble_device: BLEDevice, advertisement_data: AdvertisementData | None = None
    ):
        """Initialize."""
        self._advertisement_data = advertisement_data
        self._authenticated: bool = False
        self._associated:bool =False
        self._ble_device = ble_device
        # self._callbacks: list[Callable[[cmds.Notifications], None]] = []
        self._client: BleakClient | None = None
        self._command_handlers: dict[int, Callable[[Command], None]] = {}
        self._command_handlers_oneshot: dict[int, asyncio.Future[Command]] = {}
        self._connect_lock: asyncio.Lock = asyncio.Lock()
        self._notifications_enabled: bool = False
        self._expected_disconnect: bool = False
        self._disconnect_reason: DisconnectReason | None = None
        self._disconnect_timer: asyncio.TimerHandle | None = None
        self._procedure_lock: asyncio.Lock = asyncio.Lock()
        self.loop = asyncio.get_running_loop()
        self.device_info = DeviceInfo()
        # self.state: Notifications = Notifications()


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


    async def update(self) -> bool:
        """Update the lock's status."""
        _LOGGER.debug("%s: Update", self.name)
        status_proc = StatusProcedure(self)
        return await self._execute(status_proc)

    async def turn_on(self) -> bool:
        """Turn on the lamp."""
        _LOGGER.debug("%s: Turn on", self.name)
        proc = PowerProcedure(self, cmds.Power.ON)
        return await self._execute(proc)

    async def turn_off(self) -> bool:
        """Turn off the lamp."""
        _LOGGER.debug("%s: Turn off", self.name)
        proc = PowerProcedure(self, cmds.Power.OFF)
        return await self._execute(proc)


    async def set_brightness(self, brightness:int) -> bool:
        """Set the brightness of the lamp [0-100]."""
        _LOGGER.debug("%s: Setting brightness to %d", self.name, brightness)
        proc = BrightnessProcedure(self, brightness)
        return await self._execute(proc)
    
    async def set_temperature(self, temp_kelvin:int, brightness:int) -> bool:
        """Set temperature [1700 - 6500] and brightness [0-100]."""
        # _LOGGER.debug("%s: Setting brightness to %d", self.name, brightness)
        proc = TempProcedure(self, temp_kelvin, brightness)
        return await self._execute(proc)

    async def associate(self) -> bool:
        """Associate the lamp."""
        _LOGGER.debug("%s: Associate", self.name)
        proc = AssociationProcedure(self)
        return await self._execute(proc)

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


    async def send_cmd(self, command: Command) -> None:
        """Send a command."""
        char_specifier = PROP_WRITE_UUID
        data = command.as_bytes
        _LOGGER.debug("TX: %s", command)
        _LOGGER.debug("TX: %s: %s", char_specifier, data.hex())

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
            _LOGGER.debug("%s: Connecting; RSSI: %s", self.name, self.rssi)
            client = await establish_connection(
                BleakClientWithServiceCache,
                self._ble_device,
                self.name,
                self._disconnected,
                use_services_cache=True,
                ble_device_callback=lambda: self._ble_device,
            )
            # await client.pair()
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
            await client.start_notify(
                PROP_NTFY_UUID, self._notification_handler
            )

    async def _notification_handler(
        self, characteristic: BleakGATTCharacteristic, data: bytes
    ) -> None:
        """Notification handler."""
        self._reset_disconnect_timer()
        _LOGGER.debug("RX: %02x: %s", characteristic.handle, data.hex())
        if len(data) < 2:
            _LOGGER.warning("Received invalid notif %s", data.hex())
            self._disconnect(DisconnectReason.INVALID_COMMAND)
            return


        try:
            command = parse_command(data)
        except InvalidCommand as err:
            _LOGGER.warning("Received invalid command %s", err)
            self._disconnect(DisconnectReason.INVALID_COMMAND)
            return
        _LOGGER.debug("RX: %s (%s)", command, command.cmd_id)
        if command_handler := self._command_handlers.get(command.cmd_id):
            command_handler(command)
        if fut := self._command_handlers_oneshot.pop(command.cmd_id, None):
            if fut and not fut.done():
                fut.set_result(command)


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
        self._client = None
        self._disconnect(DisconnectReason.UNEXPECTED)

    
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
        self._authenticated = False
        self._associated=False
        self._command_handlers = {}
        for fut in self._command_handlers_oneshot.values():
            fut.cancel()
        self._command_handlers_oneshot = {}
        self._disconnect_reason = reason
        if self._disconnect_timer:
            self._disconnect_timer.cancel()
        self._disconnect_timer = None
        self._notifications_enabled = False

    def receive_once(self, cmd: type[_CMD_T]) -> asyncio.Future[_CMD_T]:
        """Receive a response once."""
        fut: asyncio.Future[_CMD_T] = asyncio.Future()
        self._command_handlers_oneshot[cmd.cmd_id] = cast(asyncio.Future[Command], fut)
        return fut

    @retry_bluetooth_connection_error(DEFAULT_ATTEMPTS)  # type: ignore[misc]
    async def _execute(self, procedure: BaseProcedure) -> bool:
        """Execute a procedure."""
        if self._procedure_lock.locked():
            _LOGGER.debug(
                "%s: Procedure already in progress, waiting for it to complete; "
                "RSSI: %s",
                self.name,
                self.rssi,
            )
        async with self._procedure_lock:
            try:
                if procedure.need_auth:
                    await self._enusure_associated()
                else:
                    await self._ensure_connected()
                result = await procedure.execute()
                return result
            except asyncio.CancelledError as err:
                if self._disconnect_reason is None:
                    raise YBTError from err
                if self._disconnect_reason == DisconnectReason.TIMEOUT:
                    raise Timeout from err
                raise Disconnected(self._disconnect_reason) from err
            except YBTError:
                self._disconnect(DisconnectReason.ERROR)
                raise

    async def _enusure_associated(self)->None:
        """Ensure we have associated with the lamp"""
        await self._ensure_connected()
        if self._associated:
            return
        proc = AssociationProcedure(self)
        await proc.execute()
        self._associated=True

class YeelightBT_o:
    """Manage of a Yeelight lamp"""

    def __init__(
        self,
        mac: str,
        model: Model,
        name: str,
        adapter: str,
        stay_connected: bool,
        use_notif: bool,
    ):
        _LOGGER.debug(f"Initializing Yeelight Lamp {name} ({mac}) using adapter {adapter}")

        

        self._conn = Connection(
            mac=mac,
            name=name,
            adapter=adapter,
            stay_connected=stay_connected,
            use_notif=use_notif,
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
