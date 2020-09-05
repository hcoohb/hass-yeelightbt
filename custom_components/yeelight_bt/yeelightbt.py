"""
Creator : hcoohb
License : MIT
Source  : https://github.com/hcoohb/hass-yeelightbt
"""

# Standard imports
import time  # for delays
import struct
import logging
from functools import wraps

# 3rd party imports
import bluepy  # for BLE transmission


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
CMD_GETSERIAL = 0x5e
RES_GETSERIAL = 0x5f
RES_GETTIME = 0x62

_LOGGER = logging.getLogger(__name__)


def retry(ExceptionToCheck, tries=3, delay=0.1):
    """Retry calling the decorated function.

    :param ExceptionToCheck: the exception to check. may be a tuple of exceptions to check
    :type ExceptionToCheck: Exception or tuple
    :param tries: number of times to try (not retry) before giving up
    :type tries: int
    :param delay: initial delay between retries in seconds
    :type delay: int
    """
    def deco_retry(f):

        @wraps(f)
        def f_retry(*args, **kwargs):
            mtries, mdelay = tries, delay
            while mtries > 0:
                try:
                    return f(*args, **kwargs)
                except ExceptionToCheck as e:
                    msg = f"Could not connect to lamp: error{e.__class__}({str(e)})"
                    if mtries>1:
                      msg +=f", Retrying in {mdelay} seconds..."
                      _LOGGER.warning(msg)
                      time.sleep(mdelay)
                      mtries -= 1
                    else:
                      _LOGGER.error(msg)
                      return False
                    
        return f_retry  # true decorator

    return deco_retry



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
        self._mac = mac_address
        self._is_on = False
        self._mode = None
        self._rgb = None
        self._brightness = None
        self._temperature = None
        
        self._handle_notif = False
        self._handle_control = False
        self._state_callbacks=[] # store func to call on state received
        
        self.lamp = None
        self.delegate = None
        self._conn_time = 0
        self._conn_max_time =60 # minutes before reconnection

    def __str__(self):
        """ The string representation """
        mode_str = {self.MODE_COLOR:"Color", self.MODE_WHITE:"White", self.MODE_FLOW:"Flow"}
        str_rep = (
          f"<Lamp {self._mac} "
          f"{'ON' if self._is_on else 'OFF'} "
          f"mode_{mode_str[self._mode]} "
          f"rgb_{self._rgb} "
          f"brightness_{self._brightness} "
          f"colortemp_{self._temperature}>"
        )
        return str_rep

    def add_callback_on_state_changed(self, func):
      """ register callbacks to be called when lamp state is received or bt disconnected """
      self._state_callbacks.append(func)

    @retry(Exception, tries=3)
    def connect(self):
        """Connect to the lamp
        - Create a modified bluepy.btle.Peripheral object (see YeelightPeripheral)
        - Connect to the lamp
        - Add a delegate for notifications
        - Send the "enable bit" for notifications
        - send pair signal
        Tries 3 times if exceptions encountered...
        :return: True if the connection is successful, false otherwise
        """
        self.lamp = YeelightPeripheral()
        self.delegate = YeelightDelegate(self)

        self.lamp.connect(self._mac)

        self.lamp.withDelegate(self.delegate)
        self._get_handles()
        self.enable_notifications()
        self.pair()
        self._conn_time = time.time() #num seconds since 1970
        return True

    def disconnect(self):
        """Disconnect from the lamp
        Cleanup properly the bluepy's Peripheral and the Notification's Delegate to avoid weird issues
        """
        self._mode = None # lamp not available
        # call callback as there is a change in state=not available
        for func in self._state_callbacks:
            func()

        try:
            self.lamp.disconnect()
        except Exception:
            pass
        del self.lamp
        del self.delegate

    def _get_handles(self):
        """ Get the notify and control handles from the UUID
        Only once for this Lamp instance
        """
        if not self._handle_notif:
          notif_char = self.lamp.getCharacteristics(uuid=NOTIFY_UUID)
          _LOGGER.debug(f"{len(notif_char)} Characteristics for notify service. 1st handle={notif_char[0].getHandle()}")
          self._handle_notif = notif_char[0].getHandle()
        if not self._handle_control:
          ctrl_char = self.lamp.getCharacteristics(uuid=CONTROL_UUID)
          _LOGGER.debug(f"{len(ctrl_char)} Characteristics for control service. 1st handle={ctrl_char[0].getHandle()}")
          self._handle_control = ctrl_char[0].getHandle()

    def enable_notifications(self):
        """ enable notifications, 0100 is the "enable bit" """
        self.writeCharacteristic(self._handle_notif+1, b'\x01\x00')

    def pair(self):
      """ Send the pairing request to the lamp
      Needed to be able to send control command
      """
      bits=struct.pack("BBB15x",COMMAND_STX, CMD_PAIR, CMD_PAIR_ON)
      self.writeCharacteristic(self._handle_control, bits, wait_notif=0.5)

    def writeCharacteristic(self, handle, bits, withResponse=False, wait_notif:float=0):
      """ write characetristic to the lamp and wait for notification if defined.
          In case excepion is raised: disconnect and reconnect bt lamp
          Tries 3 times max
          Return True if no exception has risen (does not 100% means we wrote on device...)
          Return False if we could not write for sure 
      """
      mtries=3
      while mtries > 0:
          try:
              _LOGGER.debug(f"Writing  0x{bits.hex()} on handle {handle}")
              self.lamp.writeCharacteristic(handle,bits,withResponse)
              if wait_notif > 0:
                self.lamp.waitForNotifications(wait_notif)
              return True
          except Exception as e:
              msg = f"Could not write to lamp: error{e.__class__}({str(e)})"
              if mtries>1:
                msg +=f", Retrying now..."
                _LOGGER.warning(msg)
                self.disconnect()
                self.connect()
                mtries -= 1
              else:
                _LOGGER.error(msg)
                return False
      
    def send_cmd(self, bits, withResponse=True, wait_notif:float=1):
        """ Send a control command to the lamp, checking for response and waiting for notif
        Check if connection is xx min old and reconnect if it is... Potentially fix some issues.
        """
        if wait_notif == 0:
          wait_notif = 0.1 # (Allows to catch errors during writting)
        ret = self.writeCharacteristic(self._handle_control, bits, withResponse, wait_notif)

        if ret and (time.time() - self._conn_time > 60*self._conn_max_time):
          _LOGGER.debug(f"Connection is {self._conn_max_time}min old - reconnecting...")
          self.disconnect()
          self.connect()
        return ret
            
            
    @property
    def mac(self):
        return self._mac
      
    @property
    def available(self):
        return self._mode is not None
            
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
      
    def get_state(self):
        """Request the state of the lamp (send back state through notif)
        """
        _LOGGER.debug("Get_state")
        bits=struct.pack("BBB15x",COMMAND_STX,CMD_GETSTATE,CMD_GETSTATE_SEC)
        return self.send_cmd(bits)
            
            
    def turn_on(self):
        """Turn the lamp on. (send back state through notif) """
        _LOGGER.debug("Turn_on")
        bits=struct.pack("BBB15x",COMMAND_STX,CMD_POWER,CMD_POWER_ON)
        return self.send_cmd(bits)
            
    def turn_off(self):
        """Turn the lamp off. (send back state through notif) """
        _LOGGER.debug("Turn_off")
        bits=struct.pack("BBB15x",COMMAND_STX,CMD_POWER, CMD_POWER_OFF)
        return self.send_cmd(bits)
            
    def set_brightness(self, brightness:int):
      """ Set the brightness [1-100] (no notif)"""
      brightness = min(100, max( 0, int(brightness)))
      _LOGGER.debug(f"Set_brightness {brightness}")
      bits=struct.pack("BBB15x",COMMAND_STX,CMD_BRIGHTNESS, brightness)
      ret = self.send_cmd(bits, wait_notif=0)
      if ret:
        self._brightness = brightness
      return ret
      
    def set_temperature(self, kelvin:int, brightness:int=None):
      """ Set the temperature (White mode) [1700 - 6500 K] (no notif)"""
      if brightness is None:
        brightness =self.brightness
      kelvin = min(6500, max( 1700, int(kelvin)))
      _LOGGER.debug(f"Set_temperature {kelvin}, {brightness}")
      bits=struct.pack(">BBhB13x",COMMAND_STX,CMD_TEMP,kelvin,brightness)
      ret = self.send_cmd(bits, wait_notif=0)
      if ret:
        self._temperature=kelvin
        self._brightness = brightness
        self._mode = self.MODE_WHITE
      return ret
      
    def set_color(self, red:int, green:int, blue:int, brightness:int=None):
      """ Set the color of the lamp [0-255] (no notif)"""
      if brightness is None:
        brightness =self.brightness
      _LOGGER.debug(f"Set_color {(red, green, blue)}, {brightness}")
      bits=struct.pack("BBBBBBB11x",COMMAND_STX,CMD_RGB,red,green,blue,0x01,brightness)
      ret = self.send_cmd(bits, wait_notif=0)
      if ret:
        self._rgb=(red,green,blue)
        self._brightness = brightness
        self._mode = self.MODE_COLOR
      return ret
    
    def get_name(self):
      """ Get the name from the lamp (through notif)"""
      _LOGGER.debug("Get_name")
      bits=struct.pack("BB16x",COMMAND_STX, CMD_GETNAME)
      return self.send_cmd(bits)
    
    def get_version(self):
      """ Get the versions from the lamp (through notif) """
      _LOGGER.debug("Get_version")
      bits=struct.pack("BB16x",COMMAND_STX, CMD_GETVER)
      return self.send_cmd(bits)
      
    def get_serial(self):
      """ Get the serial from the lamp (through notif) """
      _LOGGER.debug("Get_serial")
      bits=struct.pack("BB16x",COMMAND_STX, CMD_GETSERIAL)
      return self.send_cmd(bits)
    
    def _process_notification(self, cHandle, data):
        """Method called when a notification is send from the lamp
        It is processed here rather than in the handleNotification() function,
        because the latter is not a method of the Lamp class, therefore it can't access
        the Lamp object's data
        :args: - data : the received data from the lamp in hex format
        """
        _LOGGER.debug(f"Received 0x{data.hex()} fron handle={cHandle}")
        
        res_type = struct.unpack("xB16x",data)[0] #the type of response we got
        if res_type == RES_GETSTATE:  # state result
          state = struct.unpack(">xxBBBBBBBhx6x",data)
          self._is_on = state[0]==CMD_POWER_ON
          self._mode = state[1]
          self._rgb = (state[2], state[3], state[4]) #, state[5])
          self._brightness = state[6]
          self._temperature = state[7]
          _LOGGER.debug(self)
          # Call any callback registered:
          for func in self._state_callbacks:
              func()
          
        if res_type == RES_PAIR: # pairing result
          pair_mode = struct.unpack("xxB15x",data)[0]
          if pair_mode != 0x04:
            # we do NOT have successfully paired
            _LOGGER.error("The pairing request returned unexpected results. retry")
            self.disconnect()
            
        if res_type == RES_GETVER: 
          self.versions = struct.unpack("Bhhhh8x",data)
          
        if res_type == RES_GETSERIAL: 
          self.serial = struct.unpack("B17x",data)[0]

def discover_yeelight_lamps():
    """Scanning feature
    Scan the BLE neighborhood for an Yeelight lamp
    This method requires the script to be launched as root
    Returns the list of nearby lamps
    """
    lamp_list = []
    from bluepy.btle import Scanner, DefaultDelegate

    class ScanDelegate(DefaultDelegate):
        """Overwrite of the Scan Delegate class"""

        def __init__(self):
            DefaultDelegate.__init__(self)

    scanner = Scanner().withDelegate(ScanDelegate())
    devices = scanner.scan(6.0)
    for dev in devices:
      #_LOGGER.debug(f"found {dev.addr} = {dev.getScanData()}")
        for (adtype, desc, value) in dev.getScanData():
            if "XMCTD" in value:
                _LOGGER.debug(f"found Yeelight lamp with mac: {dev.addr}")
                lamp_list.append(Lamp(dev.addr))
    return lamp_list

class YeelightDelegate(bluepy.btle.DefaultDelegate):
    """Overwrite of Bluepy's DefaultDelegate class
    It adds a lamp object that refers to the Lamp.lamp object which
    called this delegate.
    It is used to call the lamp._process_notification() function
    """

    def __init__(self, lampObject):
        self.lamp = lampObject

    def handleNotification(self, cHandle, data):
        """Overwrite of the async function called when a device sends a notification.
        It's just passing the data to _process_notification(),
        which is linked to the emitting lamp (via self.lamp).
        This allows us to use the lamp's functions and interact with the response.
        """
        self.lamp._process_notification(cHandle,data)
        
        
class YeelightPeripheral(bluepy.btle.Peripheral):
    """Overwrite of the Bluepy 'Peripheral' class.
    It overwrite the default to _getResp() correct bug waiting for notifications
    """

  # PR348: https://github.com/IanHarvey/bluepy/pull/348
  # TO BE REMOVED once pluepy release > 1.3.0
    def _getResp(self, wantType, timeout=None):
        if isinstance(wantType, list) is not True:
            wantType = [wantType]

        while True:
            resp = self._waitResp(wantType + ['ntfy', 'ind'], timeout)
            if resp is None:
                return None

            respType = resp['rsp'][0]
            if respType == 'ntfy' or respType == 'ind':
                hnd = resp['hnd'][0]
                data = resp['d'][0]
                if self.delegate is not None:
                    self.delegate.handleNotification(hnd, data)
            if respType not in wantType:
                continue
            return resp
