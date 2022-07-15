"""
Creator : hcoohb
License : MIT
Source  : https://github.com/hcoohb/hass-yeelightbt
"""

# Standard imports
import asyncio
import struct
import logging

# 3rd party imports
from bleak import BleakClient, BleakError

NOTIFY_UUID = "8f65073d-9f57-4aaa-afea-397d19d5bbeb"
CONTROL_UUID = "aa7d3f34-2d4f-41e0-807f-52fbf8cf7443"

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

MODEL_BEDSIDE = "Bedside"
MODEL_CANDELA = "Candela"


_LOGGER = logging.getLogger(__name__)


class Lamp:
    """The class that represents a Yeelight lamp
    A Lamp object describe a real world Yeelight lamp.
    It is linked to an YeelightPeripheral object for BLE transmissions
    and an YeelightDelegate for BLE notifications handling.
    """

    MODE_COLOR = 0x01
    MODE_WHITE = 0x02
    MODE_FLOW = 0x03

    def __init__(self, mac_address):
        """ Just setup some vars"""
        _LOGGER.debug(f"Creating Yeelight Lamp {mac_address}")
        self._client =  BleakClient(mac_address, timeout=10)
        self._mac = mac_address
        self._is_on = False
        self._mode = None
        self._rgb = None
        self._brightness = None
        self._temperature = None
        self._paired = True
        self.versions = None
        self._model = "Unknown"

        self._state_callbacks = []  # store func to call on state received
        self._wait_next_cmd = 0

    def __str__(self):
        """ The string representation """
        mode_str = {
            self.MODE_COLOR: "Color",
            self.MODE_WHITE: "White",
            self.MODE_FLOW: "Flow",
        }
        str_rgb = f"rgb_{self._rgb} " if self._rgb is not None else ""
        str_temp = f"temp_{self._temperature}" if self._temperature is not None else ""
        str_mode = mode_str[self._mode] if self._mode in mode_str else self._mode
        str_rep = (
            f"<Lamp {self._mac} "
            f"{'ON' if self._is_on else 'OFF'} "
            f"mode_{str_mode} "
            f"{str_rgb}{str_temp}"
            f">"
        )

        return str_rep

    def add_callback_on_state_changed(self, func):
        """
        Register callbacks to be called when lamp state is received or bt disconnected
        """
        self._state_callbacks.append(func)

    def run_state_changed_cb(self):
        """Execute all registered callbacks for a state change"""
        for func in self._state_callbacks:
            func()

    def diconnected_cb(self, client):
        _LOGGER.debug(f"Client with address {client.address} got disconnected!")
        self._mode = None  # lamp not available
        self.run_state_changed_cb()

    async def connect(self):
        if self._client.is_connected:
            return
        for i in range(3):
            try:
                await self._client.disconnect()
                self._client =  BleakClient(self._mac, timeout=10)
                await self._client.connect()
                _LOGGER.debug(f"Connected: {self._client.is_connected}")
                self._client.set_disconnected_callback(self.diconnected_cb)
                await self._client.start_notify(NOTIFY_UUID, self.notification_handler)
                _LOGGER.debug("Notifying")
                await self.pair()
                if not self.versions:
                    await self.get_version()
                    await self.get_serial()
                break
            except asyncio.TimeoutError:
                _LOGGER.error("Connection Timeout error")
            except BleakError as err:
                _LOGGER.error(f"Connection: BleakError: {err}")

    async def disconnect(self):
        if self._client.is_connected:
            try:
                await self._client.disconnect()
            except asyncio.TimeoutError:
                _LOGGER.error("Disconnection: Timeout error")
            except BleakError as err:
                _LOGGER.error(f"Disconnection: BleakError: {err}")


    @property
    def mac(self):
        return self._mac

    @property
    def available(self):
        return self._mode is not None

    @property
    def model(self):
        return self._model

    @property
    def mode(self):
        return self._mode

    @property
    def is_on(self):
        return self._is_on

    @property
    def temperature(self):
        return self._temperature

    @property
    def brightness(self):
        return self._brightness

    @property
    def color(self):
        return self._rgb

    def get_prop_min_max(self):
        return {
            "brightness": {"min": 0, "max": 100},
            "temperature": {"min": 1700, "max": 6500},
            "color": {"min": 0, "max": 255},
        }


    async def send_cmd(self, bits, withResponse=True, wait_notif: float = 1, wait_before_next_cmd=0.5):
        await self.connect()
        if self._client.is_connected:
            try:
                await self._client.write_gatt_char(CONTROL_UUID, bits)
                await asyncio.sleep(wait_before_next_cmd)
            except asyncio.TimeoutError:
                _LOGGER.error("Send Cmd: Timeout error")
            except BleakError as err:
                _LOGGER.error(f"Send Cmd: BleakError: {err}")

    async def pair(self):
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_PAIR, CMD_PAIR_ON)
        await self.send_cmd(bits)

    async def get_state(self):
        """Request the state of the lamp (send back state through notif)"""
        _LOGGER.debug("Get_state")
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_GETSTATE, CMD_GETSTATE_SEC)
        await self.send_cmd(bits)

    async def turn_on(self):
        """Turn the lamp on. (send back state through notif) """
        _LOGGER.debug("Turn_on")
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_POWER, CMD_POWER_ON)
        await self.send_cmd(bits, wait_before_next_cmd=1)

    async def turn_off(self):
        """Turn the lamp off. (send back state through notif) """
        _LOGGER.debug("Turn_off")
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_POWER, CMD_POWER_OFF)
        await self.send_cmd(bits, wait_before_next_cmd=1)

    # set_brightness/temperature/color do NOT send a notification back.
    # However, the lamp takes time to transition to new state
    # and if another command (including get_state) is sent during that time,
    # it stops the transition where it is...
    async def set_brightness(self, brightness: int):
        """ Set the brightness [1-100] (no notif)"""
        brightness = min(100, max(0, int(brightness)))
        _LOGGER.debug(f"Set_brightness {brightness}")
        bits = struct.pack("BBB15x", COMMAND_STX, CMD_BRIGHTNESS, brightness)
        await self.send_cmd(bits, wait_notif=0)
        ret = True
        if ret:
            self._brightness = brightness
        return ret

    async def set_temperature(self, kelvin: int, brightness: int = None):
        """ Set the temperature (White mode) [1700 - 6500 K] (no notif)"""
        if brightness is None:
            brightness = self.brightness
        kelvin = min(6500, max(1700, int(kelvin)))
        _LOGGER.debug(f"Set_temperature {kelvin}, {brightness}")
        bits = struct.pack(">BBhB13x", COMMAND_STX, CMD_TEMP, kelvin, brightness)
        await self.send_cmd(bits, wait_notif=0)
        ret = True
        if ret:
            self._temperature = kelvin
            self._brightness = brightness
            self._mode = self.MODE_WHITE
        return ret

    async def set_color(self, red: int, green: int, blue: int, brightness: int = None):
        """ Set the color of the lamp [0-255] (no notif)"""
        if brightness is None:
            brightness = self.brightness
        _LOGGER.debug(f"Set_color {(red, green, blue)}, {brightness}")
        bits = struct.pack(
            "BBBBBBB11x", COMMAND_STX, CMD_RGB, red, green, blue, 0x01, brightness
        )
        await self.send_cmd(bits, wait_notif=0)
        ret = True
        if ret:
            self._rgb = (red, green, blue)
            self._brightness = brightness
            self._mode = self.MODE_COLOR
        return ret

    async def get_name(self):
        """ Get the name from the lamp (through notif)"""
        _LOGGER.debug("Get_name")
        bits = struct.pack("BB16x", COMMAND_STX, CMD_GETNAME)
        await self.send_cmd(bits)

    async def get_version(self):
        """ Get the versions from the lamp (through notif) """
        _LOGGER.debug("Get_version")
        bits = struct.pack("BB16x", COMMAND_STX, CMD_GETVER)
        await self.send_cmd(bits)

    async def get_serial(self):
        """ Get the serial from the lamp (through notif) """
        _LOGGER.debug("Get_serial")
        bits = struct.pack("BB16x", COMMAND_STX, CMD_GETSERIAL)
        await self.send_cmd(bits)

    def notification_handler(self, cHandle, data):
        """Method called when a notification is sent from the lamp
        It is processed here rather than in the handleNotification() function,
        because the latter is not a method of the Lamp class, therefore it can't access
        the Lamp object's data
        :args: - data : the received data from the lamp in hex format
        """
        _LOGGER.debug(f"Received 0x{data.hex()} fron handle={cHandle}")

        res_type = struct.unpack("xB16x", data)[0]  # the type of response we got
        if res_type == RES_GETSTATE:  # state result
            state = struct.unpack(">xxBBBBBBBhx6x", data)
            self._is_on = state[0] == CMD_POWER_ON
            if self._model == MODEL_CANDELA:
                self._brightness = state[1]
                self._mode = (
                    state[2] if self._paired else None
                )  # Not entirely sure this is the mode...
                # Candela seems to also give something in state 3 and 4...
            else:
                self._mode = state[1] if self._paired else None
                self._rgb = (state[2], state[3], state[4])  # , state[5])
                self._brightness = state[6]
                self._temperature = state[7]
            _LOGGER.debug(self)
            # Call any callback registered:
            self.run_state_changed_cb()

        if res_type == RES_PAIR:  # pairing result
            self._paired = False
            pair_mode = struct.unpack("xxB15x", data)[0]
            if pair_mode == 0x01:  # The lamp is requesting pairing. push small button!
                _LOGGER.error(
                    "Yeelight pairing request: Push the little button of the lamp now!"
                )
                self._mode = None  # unavailable in HA for now
            if pair_mode == 0x02:
                _LOGGER.debug("Yeelight pairing was successful!")
                self._paired = True
            if pair_mode == 0x03:
                _LOGGER.error("Yeelight is not paired! Restart the process to pair")
                self._mode = None  # unavailable in HA
            if pair_mode == 0x04:
                _LOGGER.debug("Yeelight is already paired")
                self._paired = True
            if pair_mode == 0x06 or pair_mode == 0x07:
                _LOGGER.error(
                    "The pairing request returned unexpected results. Reconnecting"
                )
                # self.reconnect()

        if res_type == RES_GETVER:
            self.versions = struct.unpack("xxBHHHH6x", data)
            _LOGGER.info(f"Lamp {self._mac} exposes versions:{self.versions}")
            self._model = MODEL_BEDSIDE
            if self.versions[0] > 2:
                self._model = MODEL_CANDELA
            _LOGGER.info(f"Lamp {self._mac} is a '{self._model}'")

        if res_type == RES_GETSERIAL:
            self.serial = struct.unpack("xxB15x", data)[0]
            _LOGGER.info(f"Lamp {self._mac} exposes serial:{self.serial}")


async def discover_yeelight_lamps():
    """Scanning feature
    Scan the BLE neighborhood for an Yeelight lamp
    This method requires the script to be launched as root
    Returns the list of nearby lamps
    """
    lamp_list = []
    from bleak import BleakScanner

    devices = await BleakScanner.discover()
    for d in devices:
        if d.name.startswith("XMCTD"):
            lamp_list.append({"mac": d.address, "model": MODEL_BEDSIDE})
            _LOGGER.info(f"found {MODEL_BEDSIDE} with mac: {d.address}, details:{d.details}")
        if "yeelight_ms" in d.name:
            lamp_list.append({"mac": d.address, "model": MODEL_CANDELA})
            _LOGGER.info(f"found {MODEL_CANDELA} with mac: {d.address}, details:{d.details}")
    return lamp_list


if __name__ == "__main__":

    import sys

    # bleak backends are very loud, this reduces the log spam when using --debug
    logging.getLogger("bleak.backends").setLevel(logging.WARNING)
    # start the logger to stdout
    logging.basicConfig(stream=sys.stdout, level=logging.DEBUG)
    _LOGGER.info("YEELIGHT_BT scanning starts")

    # start discovery:
    # lamp_list = asyncio.run(discover_yeelight_lamps())
    # _LOGGER.info("YEELIGHT_BT scanning ends")

    lamp_list = [{"mac":"F8:24:41:E6:3E:39", "model":MODEL_BEDSIDE}]
    # now try to connect to the lamp
    if not lamp_list:
        exit
    
    async def test_light():
        yee = Lamp(lamp_list[0]["mac"])
        await yee.connect()
        await yee.turn_on()
        await asyncio.sleep(5.0)
        await yee.turn_off()
        await asyncio.sleep(2.0)
    
    asyncio.run(test_light())
    print("The end")