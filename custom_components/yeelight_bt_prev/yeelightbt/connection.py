"""
Bleak connection backend.
"""
import asyncio
import logging
import struct
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from bleak import BleakClient  # Hass monkey patched version
from bleak.backends.characteristic import BleakGATTCharacteristic
from bleak_retry_connector import NO_RSSI_VALUE, establish_connection
from homeassistant.components import bluetooth
from homeassistant.components.bluetooth.manager import BluetoothManager
from homeassistant.core import HomeAssistant, callback as hass_callback
from enum import Enum, StrEnum

from typing import cast

from bleak.backends.device import BLEDevice

REQUEST_TIMEOUT = 5
RETRY_BACK_OFF_FACTOR = 0.25
RETRIES = 14

# Handles in linux and BTProxy are off by 1. Using UUIDs instead for consistency
PROP_WRITE_UUID = "aa7d3f34-2d4f-41e0-807f-52fbf8cf7443"
PROP_NTFY_UUID = "8f65073d-9f57-4aaa-afea-397d19d5bbeb"

CMD_PAIR = 0x67
CMD_PAIR_ON = 0x02
COMMAND_STX = 0x43
RES_PAIR = 0x63

# bleak backends are very loud on debug, this reduces the log spam when using --debug
# logging.getLogger("bleak.backends").setLevel(logging.WARNING)

_LOGGER = logging.getLogger(__name__)


class Adapter(str, Enum):
    AUTO = "AUTO"
    LOCAL = "LOCAL"


class PairingStatus(StrEnum):
    NOT_PAIRED = "Not Paired"
    PAIRING = "Pairing"
    PAIRED = "Paired"


class BackendException(Exception):
    """Exception to wrap backend exceptions."""


class BleakClientForceAdaptor(BleakClient):
    def __init__(  # pylint: disable=super-init-not-called, keyword-arg-before-vararg
        self,
        scanner_device,
        disconnected_callback: Callable[[BleakClient], None] | None = None,
        *args: Any,
        timeout: float = 10.0,
        **kwargs: Any,
    ) -> None:
        """Initialize the BleakClient."""
        self._scanner_device = scanner_device
        super().__init__(
            scanner_device.ble_device, disconnected_callback, args, timeout, kwargs
        )

    @hass_callback
    def _async_get_best_available_backend_and_device(self, manager: BluetoothManager):
        return self._async_get_backend_for_ble_device(
            manager, self._scanner_device.scanner, self._scanner_device.ble_device
        )


class Connection:
    """Representation of a BTLE Connection."""

    def __init__(
        self,
        mac: str,
        name: str,
        adapter: str,
        stay_connected: bool,
        use_notif: bool,
        hass: HomeAssistant,
        callback,
    ):
        """Initialize the connection."""
        self._mac = mac
        self._name = name
        self._adapter = adapter
        self._stay_connected = stay_connected
        self._use_notif = use_notif
        self._hass = hass
        self._callback = callback
        self._notify_event = asyncio.Event()
        self._paired_event = asyncio.Event()
        self._terminate_event = asyncio.Event()
        self.rssi = None
        self._lock = asyncio.Lock()
        self._conn: BleakClient | None = None
        self._pair_status = PairingStatus.NOT_PAIRED
        self._ble_device: BLEDevice | None = None
        self._connection_callbacks: list = []
        self.retries = 0
        self._round_robin = 0

    def register_connection_callback(self, callback) -> None:
        self._connection_callbacks.append(callback)

    def _on_connection_event(self) -> None:
        for callback in self._connection_callbacks:
            callback()

    async def async_disconnect(self):
        _LOGGER.debug("Trying to disconnect connection")
        if self._conn:
            await self._conn.disconnect()

    def shutdown(self):
        _LOGGER.debug(
            "[%s] closing connections",
            self._name,
        )
        self._terminate_event.set()
        self._notify_event.set()

    async def throw_if_terminating(self):
        if self._terminate_event.is_set():
            if self._conn:
                await self._conn.disconnect()
            raise Exception("Connection cancelled by shutdown")

    def _on_client_disconnect(self, client):
        self._conn=None
        self._pair_status = PairingStatus.NOT_PAIRED
        _LOGGER.debug(f"Client disconnected: {client}, {id(client)}")

    async def async_get_connection(self):
        if self._conn and self._conn.is_connected:
            _LOGGER.debug("Already connected")
            return self._conn
        _LOGGER.debug(f"Adapter for connection: {self._adapter}")
        if self._adapter == Adapter.AUTO:
            self._ble_device = bluetooth.async_ble_device_from_address(
                self._hass, self._mac, connectable=True
            )
            if self._ble_device is None:
                raise Exception("Device not found")

            self._conn = await establish_connection(
                client_class=BleakClient,
                device=self._ble_device,
                name=self._name,
                disconnected_callback=lambda client: self._on_client_disconnect(client),
                max_attempts=2,
                use_services_cache=True,
            )
            self.rssi = self._ble_device.rssi
            _LOGGER.debug(f"The conn is {self._conn}, {id(self._conn)}")
        else:
            device_advertisement_datas = sorted(
                bluetooth.async_scanner_devices_by_address(
                    hass=self._hass, address=self._mac, connectable=True
                ),
                key=lambda device_advertisement_data: device_advertisement_data.advertisement.rssi
                or NO_RSSI_VALUE,
                reverse=True,
            )
            _LOGGER.debug(f"d&a list: {device_advertisement_datas}")
            if self._adapter == Adapter.LOCAL:
                if len(device_advertisement_datas) == 0:
                    raise Exception("Device not found")
                d_and_a = device_advertisement_datas[
                    self._round_robin % len(device_advertisement_datas)
                ]
            else:  # adapter is e.g /org/bluez/hci0
                list_ad = [
                    x
                    for x in device_advertisement_datas
                    if (d := x.ble_device.details)
                    and d.get("props", {}).get("Adapter") == self._adapter
                ]
                list_ad = [
                    x
                    for x in device_advertisement_datas
                    if x.scanner.source == self._adapter
                ]
                if len(list_ad) == 0:
                    raise Exception("Device not found")
                d_and_a = list_ad[0]
                _LOGGER.debug(f"Adapter {d_and_a} found the light")
            self.rssi = d_and_a.advertisement.rssi
            self._ble_device = d_and_a.ble_device
            _LOGGER.debug(
                f"BLE: {self._ble_device}, details: {self._ble_device.details}"
            )
            # UnwrappedBleakClient = cast(type[BleakClient], BleakClient.__bases__[0])
            self._conn = BleakClientForceAdaptor(
                d_and_a,
                disconnected_callback=lambda client: self._on_connection_event(),
                dangerous_use_bleak_cache=True,
            )
            self._pair_status = PairingStatus.NOT_PAIRED
            await self._conn.connect()

        if self._conn.is_connected:
            _LOGGER.debug("[%s] Connected", self._name)
            self._on_connection_event()
            if self._use_notif:
                await self._conn.start_notify(PROP_NTFY_UUID, self.on_notification)
        else:
            raise BackendException("Can't connect")
        return self._conn

    async def on_notification(self, handle: BleakGATTCharacteristic, data: bytearray):
        """Handle Callback from a Bluetooth (GATT) request."""
        if PROP_NTFY_UUID == handle.uuid:
            _LOGGER.debug(f"received notif: 0x{data.hex()}")
            # handle the case
            res_type = struct.unpack("xB16x", data)[0]  # the type of response we got
            if res_type == RES_PAIR:  # pairing result
                self._paired_event.clear()
                pair_mode = struct.unpack("xxB15x", data)[0]
                if (
                    pair_mode == 0x01
                ):  # The lamp is requesting pairing. push small button!
                    _LOGGER.error(
                        "Yeelight pairing request: Push the little button of the lamp now! (All commands will be ignored until the lamp is paired)"
                    )
                    self._pair_status = PairingStatus.PAIRING
                if pair_mode == 0x02:
                    self._pair_status = PairingStatus.PAIRED
                    self._paired_event.set()
                    _LOGGER.debug("Yeelight pairing was successful!")
                if pair_mode == 0x03:
                    self._pair_status = PairingStatus.NOT_PAIRED
                    _LOGGER.error("Yeelight is not paired!")
                if pair_mode == 0x04:
                    self._pair_status = PairingStatus.PAIRED
                    _LOGGER.debug("Yeelight is already paired")
                if pair_mode == 0x06 or pair_mode == 0x07:
                    self._pair_status = PairingStatus.NOT_PAIRED
                    # 0x07: Lamp disconnect imminent
                    _LOGGER.error(
                        "The pairing request returned unexpected results. Please reset the lamp (https://www.youtube.com/watch?v=PnjcOSgnbAM)."
                    )
            self._notify_event.set()
            if res_type != RES_PAIR:
                # Do not call callbacks on pairing since handled within the connection
                self._callback(data)
        else:
            _LOGGER.error(
                "[%s] wrong charasteristic: %s, %s",
                self._name,
                handle.handle,
                handle.uuid,
            )

    async def async_make_request(
        self, value, wait_notif=False, pair_needed=True, retries=RETRIES
    ):
        """Write a GATT Command with callback - not utf-8."""
        async with self._lock:  # only one concurrent request per device
            try:
                await self._async_make_request_try(
                    value, wait_notif, pair_needed, retries
                )
            finally:
                self.retries = 0
                self._on_connection_event()

    async def _async_make_request_try(self, value, wait_notif, pair_needed, retries):
        self.retries = 0
        while True:
            self.retries += 1
            self._on_connection_event()
            try:
                await self.throw_if_terminating()
                conn = await self.async_get_connection()

                try:
                    await self._async_pair(pair_needed, wait_notif)
                    if value != "ONLY CONNECT":
                        self._notify_event.clear()
                        
                        _LOGGER.debug(f"Sending: 0x{value.hex()}")
                        await conn.write_gatt_char(
                            PROP_WRITE_UUID, value, response=True
                        )
                        if wait_notif:
                            await asyncio.wait_for(
                                self._notify_event.wait(), REQUEST_TIMEOUT
                            )

                finally:
                    if not self._stay_connected:
                        await conn.disconnect()
                return
            except Exception as ex:
                await self.throw_if_terminating()
                _LOGGER.debug(
                    "[%s] Broken connection [retry %s/%s]: %s",
                    self._name,
                    self.retries,
                    retries,
                    ex,
                    exc_info=True,
                )
                self._round_robin = self._round_robin + 1
                if self.retries >= retries:
                    raise ex
                await asyncio.sleep(RETRY_BACK_OFF_FACTOR * self.retries)

    async def _async_pair(self, pair_needed, wait_notif):
        if pair_needed and self._pair_status == PairingStatus.NOT_PAIRED:
            self._notify_event.clear()
            bits = bytearray(struct.pack("BBB15x", COMMAND_STX, CMD_PAIR, CMD_PAIR_ON))
            _LOGGER.debug(f"Sending: 0x{bits.hex()}")
            await self._conn.write_gatt_char(PROP_WRITE_UUID, bits, response=True)
            if wait_notif:
                await asyncio.wait_for(self._notify_event.wait(), REQUEST_TIMEOUT)
                if self._pair_status != PairingStatus.PAIRED:
                    raise "Could not automatically pair"
            else:
                # ensure some time to pair if no notif
                await asyncio.sleep(0.3)

    async def wait_paired(self):
        _LOGGER.debug("Conn wait paired started")
        await asyncio.wait_for(self._paired_event.wait(), 30)
        _LOGGER.debug("Conn wait paired done")
