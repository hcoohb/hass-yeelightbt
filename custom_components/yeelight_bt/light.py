""" light platform """

import logging
import time

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.const import CONF_NAME, CONF_MAC
from .const import DOMAIN
from homeassistant.components.light import ENTITY_ID_FORMAT
from homeassistant.helpers.entity import generate_entity_id

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP,
    ATTR_HS_COLOR,
    # ATTR_EFFECT,
    SUPPORT_BRIGHTNESS,
    SUPPORT_COLOR_TEMP,
    SUPPORT_COLOR,
    # SUPPORT_EFFECT,
    LightEntity,
    PLATFORM_SCHEMA,
)

from homeassistant.util.color import (
    color_temperature_mired_to_kelvin as mired_to_kelvin,
    color_temperature_kelvin_to_mired as kelvin_to_mired,
    color_hs_to_RGB,
    color_RGB_to_hs,
)

from .yeelightbt import Lamp

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MAC): cv.string,
        vol.Optional(CONF_NAME, default=DOMAIN): cv.string,
    }
)

LIGHT_EFFECT_LIST = ["flow", "none"]

SUPPORT_YEELIGHTBT = (
    SUPPORT_BRIGHTNESS
    | SUPPORT_COLOR_TEMP
    | SUPPORT_COLOR
    # | SUPPORT_EFFECT
)

_LOGGER = logging.getLogger(__name__)


def setup_platform(hass, config, add_entities, discovery_info=None):
    """Setup the yeelightbt light platform."""
    mac = config[CONF_MAC]
    name = config[CONF_NAME]

    if discovery_info is not None:
        _LOGGER.debug("Adding autodetected %s", discovery_info["hostname"])
        name = DOMAIN
    _LOGGER.debug(f"Adding light {name} with mac:{mac}")
    add_entities([YeelightBT(name, mac)])


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the platform from config_entry."""
    _LOGGER.debug(
        f"async_setup_entry:setting up the config entry {config_entry.title} "
        f"with data:{config_entry.data}"
    )
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
        self._effect = "none"
        self._available = False

        _LOGGER.info(f"Initializing {self.name}, {self._mac}")
        self._dev = Lamp(self._mac)
        self._dev.add_callback_on_state_changed(self._status_cb)
        self._prop_min_max = self._dev.get_prop_min_max()
        self._min_mireds = kelvin_to_mired(
            self._prop_min_max["temperature"]["max"]
        )  # reversed scale
        self._max_mireds = kelvin_to_mired(
            self._prop_min_max["temperature"]["min"]
        )  # reversed scale

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
    def min_mireds(self):
        """Return minimum supported color temperature."""
        return self._min_mireds

    @property
    def max_mireds(self):
        """Return minimum supported color temperature."""
        return self._max_mireds

    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        return self._brightness

    @property
    def hs_color(self):
        """
        Return the Hue and saturation color value.
        Lamp has rgb => we calculate hs
        """
        if self._rgb is None:
            return None
        return color_RGB_to_hs(*self._rgb)

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

    def _status_cb(self):
        _LOGGER.debug("Got state notification from the lamp")
        self._available = self._dev.available
        if not self._available:
            self.schedule_update_ha_state()
            return

        self._brightness = int(round(255.0 * self._dev.brightness / 100))
        self._is_on = self._dev.is_on
        if self._dev.mode == self._dev.MODE_WHITE:
            self._ct = int(kelvin_to_mired(int(self._dev.temperature)))
            self._rgb = (0, 0, 0)
        else:
            self._ct = None
            self._rgb = self._dev.color

        self.schedule_update_ha_state()

    def update(self):
        # Note, update should only start fetching,
        # followed by asynchronous updates through notifications.
        try:
            _LOGGER.debug("Requesting an update of the lamp status")
            self._dev.get_state()  # blocking...
        except Exception as ex:
            _LOGGER.error(f"Fail requesting the light status. Got exception: {ex}")

    def turn_on(self, **kwargs):
        """Turn the light on."""
        _LOGGER.debug(f"Trying to turn on. with ATTR:{kwargs}")

        # First if brightness of dev to 0: turn off
        if ATTR_BRIGHTNESS in kwargs:
            brightness_dev = int(round(kwargs[ATTR_BRIGHTNESS] * 1.0 / 255 * 100))
            if brightness_dev == 0:
                _LOGGER.debug("Lamp brightness to be set to 0... so turning off")
                self.turn_off()
                return

        # ATTR can be set while light is off, so turn it on first:
        if not self._is_on:
            self._dev.turn_on()
            time.sleep(0.3)
        self._is_on = True

        if ATTR_HS_COLOR in kwargs:
            rgb = color_hs_to_RGB(*kwargs.get(ATTR_HS_COLOR))
            self._rgb = rgb
            _LOGGER.debug(f"Trying to set color RGB: {rgb}")
            self._dev.set_color(*rgb, int(round(self._brightness * 1.0 / 255 * 100)))

        if ATTR_COLOR_TEMP in kwargs:
            mireds = kwargs[ATTR_COLOR_TEMP]
            temp_in_k = int(mired_to_kelvin(mireds))
            _LOGGER.debug(f"Trying to set temp: {temp_in_k}")
            self._dev.set_temperature(
                temp_in_k, int(round(self._brightness * 1.0 / 255 * 100))
            )
            self._ct = mireds

        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            brightness_dev = int(round(brightness * 1.0 / 255 * 100))
            _LOGGER.debug(f"Trying to set brightness: {brightness_dev}")
            self._dev.set_brightness(brightness_dev)
            self._brightness = brightness

        # if ATTR_EFFECT in kwargs:
        #    self._effect = kwargs[ATTR_EFFECT]

    def turn_off(self, **kwargs):
        """Turn the light off."""

        self._dev.turn_off()
        self._is_on = False
