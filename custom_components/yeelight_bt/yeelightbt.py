import struct
import codecs
import logging
import time
import threading

import logging
import codecs
import time

from bluepy import btle

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
RES_GETNAME = 0x53
RES_GETVER = 0x5D
RES_GETSERIAL = 0x5f
RES_GETTIME = 0x62
cmdDict={}
cmdDict["GetName"]=0x52
cmdDict["GetVersion"]=0x5C
cmdDict["GetSerialNumber"]=0x5e
cmdDict["GetTime"]=0x61

MODE_COLOR = 0x01
MODE_WHITE = 0x02
MODE_FLOW = 0x03

_LOGGER = logging.getLogger(__name__)


DEFAULT_TIMEOUT = 3


class BTLEConnection(btle.DefaultDelegate):
    """Representation of a BTLE Connection."""

    def __init__(self, mac):
        """Initialize the connection."""
        btle.DefaultDelegate.__init__(self)

        self._conn = btle.Peripheral()
        self._conn.withDelegate(self)
        self._mac = mac
        self._callbacks = {}

    def connect(self):
        _LOGGER.debug("Trying to connect to %s", self._mac)
        try:
            self._conn.connect(self._mac)
        except btle.BTLEException as ex:
            _LOGGER.warning("Unable to connect to the device %s, retrying: %s", self._mac, ex)
            try:
                self._conn.connect(self._mac)
            except Exception as ex2:
                _LOGGER.error("Second connection try to %s failed: %s", self._mac, ex2)
                raise

        _LOGGER.debug("Connected to %s", self._mac)

    def disconnect(self):
        if self._conn:
            self._conn.disconnect()
            self._conn = None

    def wait(self, sec):
        end = time.time() + sec
        while time.time() < end:
            self._conn.waitForNotifications(timeout=0.1)

    def get_services(self):
        return self._conn.getServices()

    def get_characteristics(self, uuid=None):
        if uuid:
            _LOGGER.info("Requesting characteristics for uuid %s", uuid)
            return self._conn.getCharacteristics(uuid=uuid)
        return self._conn.getCharacteristics()

    def handleNotification(self, handle, data):
        """Handle Callback from a Bluetooth (GATT) request."""
        _LOGGER.debug("Got notification from %s: %s", handle, codecs.encode(data, 'hex'))
        if handle in self._callbacks:
            self._callbacks[handle](data)

    @property
    def mac(self):
        """Return the MAC address of the connected device."""
        return self._mac

    def set_callback(self, handle, function):
        """Set the callback for a Notification handle. It will be called with the parameter data, which is binary."""
        self._callbacks[handle] = function

    def make_request(self, handle, value, timeout=0, with_response=False):
        """Write a GATT Command without callback - not utf-8."""
        _LOGGER.debug("Writing %s to %s with with_response=%s", codecs.encode(value, 'hex'), handle, with_response)
        res = self._conn.writeCharacteristic(handle, value, withResponse=with_response)
        if timeout:
            self.wait(timeout)

        return res



def cmd(cmd):
    def _wrap(self, *args, **kwargs):
        req = cmd(self, *args, **kwargs)

        params = None
        wait = self._wait_after_call
        if isinstance(req, tuple):
            params = req[1]
            req = req[0]
        
        query = {"type": req}
        if params:
            if "wait" in params:
                wait = params["wait"]
                del params["wait"]
            query.update(params)

        _LOGGER.debug(">> %s (wait: %s)", query, wait)

        try_count = 3
        if req == "Pair":
            bits=struct.pack("BBB15x",COMMAND_STX,CMD_PAIR,CMD_PAIR_ON)
        elif req == "GetState":
            bits=struct.pack("BBB15x",COMMAND_STX,CMD_GETSTATE,CMD_GETSTATE_SEC)
        elif req in cmdDict:
            bits=struct.pack("BB16x",COMMAND_STX,cmdDict[req])
            
        elif req == "SetOnOff":
            cmd2=CMD_POWER_ON if query['state'] else CMD_POWER_OFF
            bits=struct.pack("BBB15x",COMMAND_STX,CMD_POWER,cmd2)
        elif req == "SetBrightness":
            #ensure it is [1-100]
            _LOGGER.debug("brightness to set: %i)", int(query['brightness']))
            bits=struct.pack("BBB15x",COMMAND_STX,CMD_BRIGHTNESS,int(query['brightness']))#.to_bytes(1, 'little')
        elif req == "SetTemperature":
            # 1700 - 6500 K
            bits=struct.pack(">BBhB13x",COMMAND_STX,CMD_TEMP,int(query['temperature']),int(query['brightness']))
            #return "SetTemperature", {"temperature": kelvin, "brightness": brightness} #do we need the brightness ?
        elif req == "SetColor":
            bits=struct.pack("BBBBBBB14x",COMMAND_STX,CMD_RGB,int(query['red']),int(query['green']),int(query['blue']),0x01,int(query['brightness']))
            try_count=2
            #return "SetColor", {"red": red, "green": green, "blue": blue, "brightness": brightness} #do we need the brightness ?
            
        
        _ex = None
        while try_count > 0:
            try:
                #_LOGGER.debug("building Query: %s ", query)
                #bits=Request.build(query)
                _LOGGER.debug("sending CMD %s ", codecs.encode(bits, 'hex'))
                res = self.control_char.write(bits,
                                              withResponse=True)
                self._conn.wait(wait)

                return res
            except Exception as ex:
                _LOGGER.error("got exception on %s, tries left %s: %s",
                              query, try_count, ex)
                _ex = ex
                try_count -= 1
                self.connect()
                continue
        raise _ex

    return _wrap


class Lamp:
    REGISTER_NOTIFY_HANDLE = 0x16
    MAIN_UUID =   "8e2f0cbd-1a66-4b53-ace6-b494e25f87bd"
    NOTIFY_UUID = "8f65073d-9f57-4aaa-afea-397d19d5bbeb"
    CONTROL_UUID = "aa7d3f34-2d4f-41e0-807f-52fbf8cf7443"

    def __init__(self, mac, status_cb=None, paired_cb=None,
                 keep_connection=False, wait_after_call=0):
        self._mac = mac
        self._is_on = False
        self._brightness = None
        self._temperature = None
        self._rgb = None
        self._mode = None
        self._paired_cb = paired_cb
        self._status_cb = status_cb
        self._keep_connection = keep_connection
        self._wait_after_call = wait_after_call
        self._lock = threading.RLock()
        self._conn = None

    @property
    def mac(self):
        return self._mac

    @property
    def available(self):
        return self._mode is not None

    @property
    def mode(self):
        return self._mode

    def connect(self):
        if self._conn:
            self._conn.disconnect()
        self._conn = BTLEConnection(self._mac)
        self._conn.connect()

        notify_char = self._conn.get_characteristics(Lamp.NOTIFY_UUID)
        self.notify_handle = notify_char.pop().getHandle()
        _LOGGER.debug("got notify handle: %s" % self.notify_handle)
        self._conn.set_callback(self.notify_handle, self.handle_notification)

        control_chars = self._conn.get_characteristics(Lamp.CONTROL_UUID)
        self.control_char = control_chars.pop()
        self.control_handle = self.control_char.getHandle()
        _LOGGER.debug("got control handle: %s" % self.control_handle)

        # We need to register to receive notifications
        self._conn.make_request(self.REGISTER_NOTIFY_HANDLE,
                                struct.pack("<BB", 0x01, 0x00),
                                timeout=None)
        self.pair()

    def disconnect(self):
        self._conn.disconnect()

    def __enter__(self):
        self._lock.acquire()
        if not self._conn and self._keep_connection:
            self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()
        if not self._keep_connection:
            _LOGGER.info("not keeping the connection, disconnecting..")
            self._conn.disconnect()

        return

    @cmd
    def pair(self):
        return "Pair"

    def wait(self, sec):
        end = time.time() + sec
        while time.time() < end:
            self._conn.wait(0.1)

    @property
    def is_on(self):
        return self._is_on

    @cmd
    def turn_on(self):
        return "SetOnOff", {"state": True}

    @cmd
    def turn_off(self):
        return "SetOnOff", {"state": False}

    @cmd
    def get_name(self):
        return "GetName", {"wait": 0.5}

    @cmd
    def get_scene(self, scene_id):
        return "GetScene", {"id": scene_id}

    @cmd
    def set_scene(self, scene_id, scene_name):
        return "SetScene", {"scene_id": scene_id, "text": scene_name}

    @cmd
    def get_version_info(self):
        return "GetVersion"

    @cmd
    def get_serial_number(self):
        return "GetSerialNumber"

    @cmd
    def get_time(self):
        return "GetTime"

    @cmd
    def set_time(self, new_time):
        return "SetTime", {"time": new_time}

    @cmd
    def get_nightmode(self):
        return "GetNightMode"

    @cmd
    def get_statistics(self):
        return "GetStatistics"

    @cmd
    def get_wakeup(self):
        return "GetWakeUp"

    @cmd
    def get_night_mode(self):
        return "GetNightMode"

    @property
    def temperature(self):
        return self._temperature

    @cmd
    def set_temperature(self, kelvin: int, brightness: int):
        return "SetTemperature", {"temperature": kelvin, "brightness": brightness}

    @property
    def brightness(self):
        return self._brightness

    @cmd
    def set_brightness(self, brightness: int):
        return "SetBrightness", {"brightness": brightness}

    @property
    def color(self):
        return self._rgb

    @cmd
    def set_color(self, red: int, green: int, blue: int, brightness: int):
        return "SetColor", {"red": red, "green": green, "blue": blue, "brightness": brightness,"wait": 1}

    @cmd
    def state(self):
        return "GetState", {"wait": 0.5}

    @cmd
    def get_alarm(self, number):
        return "GetAlarm", {"id": number, "wait": 0.5}

    @cmd
    def get_flow(self, number):
        return "GetSimpleFlow", {"id": number, "wait": 0.5}

    @cmd
    def get_sleep(self):
        return "GetSleepTimer", {"wait": 0.5}

    def __str__(self):
        return "<Lamp %s is_on(%s) mode(%s) rgb(%s) brightness(%s) colortemp(%s)>" % (
            self._mac, self._is_on, self._mode, self._rgb, self._brightness, self._temperature)
    
    def RawAsInt(self,byteVal):
        return int('{:02x}'.format(byteVal))
    
    def handle_notification(self, data):
        _LOGGER.debug("<< %s", codecs.encode(data, 'hex'))
        #res = Response.parse(data)
        res = struct.unpack("xB16x",data)[0]
        #print(res)
        if res == RES_GETSTATE:
            res2 = struct.unpack(">xxBBBBBBBhx6x",data)
            self._is_on = res2[0]==CMD_POWER_ON
            self._mode = (res2[1]==MODE_COLOR)*"Color"+(res2[1]==MODE_WHITE)*"White"+(res2[1]==MODE_FLOW)*"Flow"
            self._rgb = (res2[2], res2[3], res2[4], res2[5])
            self._brightness = res2[6]
            self._temperature = res2[7]

            if self._status_cb:
                self._status_cb(self)
        elif res == RES_PAIR:
            _LOGGER.debug("pairing res: %s", struct.unpack("xxB"+"x"*15,data)[0])
            if self._paired_cb:
                self._paired_cb(res)
                
        elif res == RES_GETNAME:
            res2 = struct.unpack("xxBB14s",data)
            _LOGGER.debug("id%i index%i, Name res: %s", res2[0],res2[1],res2[2].decode("utf-8") )
        elif res == RES_GETVER:
            res2 = struct.unpack(">xxBHHHH6x",data)
            _LOGGER.debug("Current Running:%i hw_version:%i, sw_version_app1:%i, sw_version_app2:%i, beacon_version:%i", res2[0],res2[1],res2[2],res2[3],res2[4] )
        elif res == RES_GETSERIAL:
            res2 = struct.unpack("xx16s",data)
            _LOGGER.debug("Serial number: %s", res2[0].decode("utf-8") )
        elif res == RES_GETTIME:
            res2 = struct.unpack("xxBBBBxBB9x",data)
            _LOGGER.debug("%i/%i/%i %i:%i:%i", self.RawAsInt(res2[3]),self.RawAsInt(res2[4]),self.RawAsInt(res2[5]),self.RawAsInt(res2[2]),self.RawAsInt(res2[1]),self.RawAsInt(res2[0]) )

        else:
            _LOGGER.info("Unhandled cb: %s", codecs.encode(data, 'hex'))