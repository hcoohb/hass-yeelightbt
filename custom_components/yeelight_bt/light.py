""" light platform """

import logging
import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import CONF_NAME, CONF_MAC
from .const import DOMAIN
from homeassistant.components.light import ENTITY_ID_FORMAT
from homeassistant.helpers.entity import generate_entity_id

from homeassistant.components.light import (
    ATTR_BRIGHTNESS, ATTR_COLOR_TEMP, ATTR_EFFECT,
    ATTR_RGB_COLOR, SUPPORT_BRIGHTNESS,ATTR_HS_COLOR,
    SUPPORT_COLOR_TEMP, SUPPORT_EFFECT, SUPPORT_COLOR,
    LightEntity, PLATFORM_SCHEMA)

from homeassistant.util.color import (
    color_temperature_mired_to_kelvin as mired_to_kelvin,
    color_temperature_kelvin_to_mired as kelvin_to_mired,
    color_temperature_to_rgb,
    color_hs_to_RGB)


PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend({
    vol.Required(CONF_MAC): cv.string,
    vol.Optional(CONF_NAME, default=DOMAIN): cv.string,
})

LIGHT_EFFECT_LIST = ['flow', 'none']

SUPPORT_YEELIGHTBT = (SUPPORT_BRIGHTNESS | SUPPORT_COLOR_TEMP |
                      # SUPPORT_EFFECT |
                      SUPPORT_COLOR)

_LOGGER = logging.getLogger(__name__)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Setup the yeelightbt light platform."""
    mac = config[CONF_MAC]
    name = config[CONF_NAME]

    if discovery_info is not None:
        _LOGGER.debug("Adding autodetected %s", discovery_info['hostname'])
        name=DOMAIN
    _LOGGER.debug(f"Adding light {name} with mac:{mac}")
    add_entities([YeelightBT(name, mac)])


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the platform from config_entry."""
    _LOGGER.debug(f"async_setup_entry:setting up the config entry {config_entry.title} with data:{config_entry.data}")
    name = config_entry.data.get(CONF_NAME) or DOMAIN
    mac = config_entry.data.get(CONF_MAC)
    async_add_entities([YeelightBT(name, mac)])


class YeelightBT(LightEntity):
    """Represenation of a light."""

    def __init__(self, name, mac):
        """Initialize the light."""
        self._name = name
        self._mac = mac
        self.entity_id = generate_entity_id(ENTITY_ID_FORMAT, self._name, [])
        self._is_on = None
        self._rgb = None
        self._ct = None
        self._brightness = None
        self._effect_list = LIGHT_EFFECT_LIST
        self._effect = 'none'
        self._available = False
        self._is_updating = False

        self.__dev = None

    @property
    def device_info(self):
        return {
            "identifiers": {
                # Serial numbers are unique identifiers within a specific domain
                (DOMAIN, self.unique_id)
            },
            "name": self._name,
            "manufacturer": "xiaomi",
            "model": "yeelight_bt",
            # "sw_version": self.light.swversion,
        }

    @property
    def unique_id(self):
        """Return the unique id of the light."""
        return self._mac

    @property
    def available(self) -> bool:
        return self._available

    @property
    def should_poll(self):
        """Polling needed for a updating status."""
        return True

    @property
    def name(self) -> str:
        """Return the name of the light if any."""
        return self._name

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return self._brightness

    @property
    def rgb_color(self):
        """Return the RBG color value."""
        return self._rgb

    @property
    def color_temp(self) -> int:
        """Return the CT color temperature."""
        return self._ct

    # @property
    # def effect_list(self):
    #     """Return the list of supported effects."""
    #     return self._effect_list

    # @property
    # def effect(self):
    #     """Return the current effect."""
    #     return self._effect

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        return self._is_on

    @property
    def supported_features(self):
        """Flag supported features."""
        return SUPPORT_YEELIGHTBT

    @property
    def _dev(self):
        from .yeelightbt import Lamp
        if not self.__dev:
            _LOGGER.debug(f"Initializing {self.name}, {self._mac}")
            self.__dev = Lamp(self._mac)
            self.__dev.add_callback_on_state_received(self._status_cb)
        return self.__dev

    def _status_cb(self):
        _LOGGER.debug("Got state notification from the lamp")
        self._available = self._dev.available
        if not self._available:
            _LOGGER.debug(f"IS UPDATING2 {self._is_updating}")
            self.schedule_update_ha_state()
            return

        self._brightness = 255 * (int(self._dev.brightness) / 100)
        self._is_on = self._dev.is_on
        if self._dev.mode == self._dev.MODE_WHITE:
            self._ct = int(kelvin_to_mired(int(self._dev.temperature)))
            # when in white mode, rgb is not set so we calculate it ourselves
            self._rgb = color_temperature_to_rgb(self._dev.temperature)
        else:
            self._ct = 0
            self._rgb = self._dev.color

        # _LOGGER.debug("available: %s, state: %s, mode: %s, bright: %s, rgb: %s, ct: %s",
        #               self._available, self._is_on, self._dev.mode, self._brightness, self._rgb, self._ct)
    
        self._is_updating = False
        _LOGGER.debug(f"IS UPDATING2 {self._is_updating}")
        self.schedule_update_ha_state()

    def update(self):
        # Note, update should only start fetching,
        # followed by asynchronous updates through notifications.
        if self._is_updating:
            _LOGGER.debug("An update is still in progress... NOT requesting another one")
            return
        try:
            _LOGGER.debug("Requesting an update of the lamp status")
            self._is_updating = True
            _LOGGER.debug(f"IS UPDATING1 {self._is_updating}")
            ret = self._dev.get_state() #blocking...
            if not ret: #Could not connect and finished all re-tries
                _LOGGER.debug(f"Update returned {ret}")
                self._is_updating=False
            _LOGGER.debug(f"IS UPDATING1b {self._is_updating}")
        except Exception as ex:
            _LOGGER.error(f"Fail requesting the light status. Got exception: {ex}")
            self._is_updating = False
            _LOGGER.debug(f"IS UPDATING1c {self._is_updating}")

    def turn_on(self, **kwargs):
        """Turn the light on."""
        _LOGGER.debug("Trying to turn on. ATTR:")
        _LOGGER.debug(kwargs)
        self._is_on = True

        if ATTR_HS_COLOR in kwargs:
            rgb = color_hs_to_RGB(*kwargs.get(ATTR_HS_COLOR))
            self._rgb = rgb
            _LOGGER.debug("Trying to set color RGB: %i %i %i",rgb[0], rgb[1], rgb[2])
            self._dev.set_color(rgb[0], rgb[1], rgb[2], int(self._brightness / 255 * 100))

        if ATTR_COLOR_TEMP in kwargs:
            mireds = kwargs[ATTR_COLOR_TEMP]
            temp_in_k = mired_to_kelvin(mireds)
            _LOGGER.debug("Trying to set temp: %i",int(temp_in_k))
            self._dev.set_temperature(int(temp_in_k),int(self._brightness / 255 * 100))
            self._ct = mireds

        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            _LOGGER.debug("Trying to set brightness: %i",int(brightness / 255 * 100))
            self._dev.set_brightness(int(brightness / 255 * 100))
            self._brightness = brightness

        # if we are just started without parameters, turn on.
        if ATTR_HS_COLOR not in kwargs and \
            ATTR_COLOR_TEMP not in kwargs and \
            ATTR_BRIGHTNESS not in kwargs:
            self._dev.turn_on()

        # if ATTR_EFFECT in kwargs:
        #    self._effect = kwargs[ATTR_EFFECT]

    def turn_off(self, **kwargs):
        """Turn the light off."""
        
        self._dev.turn_off()
        self._is_on = False
