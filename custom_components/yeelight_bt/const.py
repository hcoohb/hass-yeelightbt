""" Constants """
from enum import Enum
from .yeelightbt.connection import Adapter
# Component constants

DOMAIN = "yeelight_bt"
PLATFORM = "light"

CONF_DEBUG_MODE = "conf_debug_mode"



CONF_ADAPTER = "conf_adapter"
CONF_STAY_CONNECTED = "conf_stay_connected"
DEFAULT_ADAPTER = Adapter.AUTO
DEFAULT_STAY_CONNECTED = True
DEFAULT_SCAN_INTERVAL = 15  # minutes
