"""light platform"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any
from datetime import timedelta

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.components.light import (  # ATTR_EFFECT,; SUPPORT_EFFECT,
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_RGB_COLOR,
    ENTITY_ID_FORMAT,
    PLATFORM_SCHEMA,
    LightEntity,
    LightEntityFeature,
    ColorMode,
)
from homeassistant.util.color import value_to_brightness, brightness_to_value

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_MAC,
    CONF_NAME,
    CONF_SCAN_INTERVAL,
    EVENT_HOMEASSISTANT_STOP,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import format_mac, CONNECTION_BLUETOOTH
from homeassistant.helpers.entity import (
    generate_entity_id,
    DeviceInfo,
    EntityPlatformState,
)
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util.color import color_hs_to_RGB, color_RGB_to_hs
from homeassistant.util.color import (
    color_temperature_kelvin_to_mired as kelvin_to_mired,
)
from homeassistant.util.color import (
    color_temperature_mired_to_kelvin as mired_to_kelvin,
)

from .const import DOMAIN, DEFAULT_SCAN_INTERVAL
from .yeelightbt.yeelightbt import YeelightBT, Power, Mode, YbtState
from .models import YeelightBtConfigurationData

if TYPE_CHECKING:
    from bleak.backends.device import BLEDevice

if TYPE_CHECKING:
    from . import YBTConfigEntry

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {
        vol.Required(CONF_MAC): cv.string,
        vol.Optional(CONF_NAME, default=DOMAIN): cv.string,
    }
)
DEVICE_SCHEMA = vol.Schema({vol.Required(CONF_MAC): cv.string})
SCAN_INTERVAL = timedelta(minutes=5)
BRIGHTNESS_SCALE = (1, 100)

LIGHT_EFFECT_LIST = ["flow", "none"]


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YBTConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the platform from config_entry."""
    data: YeelightBtConfigurationData = entry.runtime_data
    # hass.data[DOMAIN][entry.entry_id]
    _LOGGER.debug(f"light async_setup_entry: setting up the config entry {data.title}")

    scan_interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
    async_add_entities([HaYBTLight(data, scan_interval)])

    # ybt = hass.data[DOMAIN][config_entry.entry_id]

    # entity = YBTLight(ybt, scan_interval)
    # async_add_entities(
    #     [entity],
    #     update_before_add=False,
    # )


class HaYBTLight(LightEntity):
    """Representation of a light."""

    # This is the main entity of the device and should use the device name. (so name=None)
    # See https://developers.home-assistant.io/docs/core/entity#has_entity_name-true-mandatory-for-new-integrations
    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = True

    def __init__(self, data: YeelightBtConfigurationData, scan_interval: int) -> None:
        """Initialize the light."""
        self._device = data.device
        self._attr_unique_id = data.device.address
        self._attr_device_info = DeviceInfo(
            name=data.title,
            # name=self._device.name,
            manufacturer="Yeelight",
            # model=self._device.model,
            model="BedsideBT",
            identifiers={(DOMAIN, data.device.address)},
            # sw_version=self._device.firmware_version,
            connections={(CONNECTION_BLUETOOTH, data.device.address)},
        )
        self._device.register_state_callback(self._on_updated)
        # self._device.register_update_callback(self._on_updated)
        self._scan_interval = scan_interval
        self._is_available = True
        self._cancel_timer = None

        color_mode = set()
        color_mode.add(ColorMode.COLOR_TEMP)
        color_mode.add(ColorMode.RGB)
        self._attr_supported_color_modes = color_mode

        # self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
        self._attr_max_color_temp_kelvin = self._device.prop_min_max["temperature"][
            "max"
        ]
        self._attr_min_color_temp_kelvin = self._device.prop_min_max["temperature"][
            "min"
        ]
        # self._attr_supported_features = SUPPORT_BRIGHTNESS
        _LOGGER.info(f"Initializing YBTLight Entity: {self._attr_unique_id}. DevInfo:{self._attr_device_info}")

        self._is_on: bool | None = False
        self._brightness: int | None = None
        self._rgb_color: tuple[float, float, float] | None = None
        self._color_temp_kelvin: int | None = None
        self._color_mode: ColorMode | None = None

    # async def async_added_to_hass(self) -> None:
    #     """Run when entity about to be added to hass."""
    #     # Start our custom loop for status update
    #     asyncio.get_event_loop().create_task(self._async_scan_loop())

    #     # self.async_on_remove(
    #     #     self.hass.bus.async_listen_once(
    #     #         EVENT_HOMEASSISTANT_STOP, self.async_will_remove_from_hass
    #     #     )
    #     # )
    #     # # schedule immediate refresh of lamp state:
    #     # self.async_schedule_update_ha_state(force_refresh=True)
    #     self._is_on = False

    async def async_will_remove_from_hass(self, event=None) -> None:
        """Run when entity will be removed from hass."""
        _LOGGER.debug("Running async_will_remove_from_hass")
        # if self._cancel_timer:
        #     self._cancel_timer()

    # async def _async_scan_loop(self, now=None):
    #     """Execute a scan of device and schedule next one"""
    #     await self.async_scan()
    #     if self._platform_state != EntityPlatformState.REMOVED:
    #         self._cancel_timer = async_call_later(
    #             self.hass, timedelta(minutes=self._scan_interval), self._async_scan_loop
    #         )

    # async def async_scan(self):
    #     """Update the data from the ybt."""
    #     try:
    #         _LOGGER.debug("Running async_update from light entity")
    #         await self._device.async_update()
    #     except Exception as ex:
    #         self._is_available = False
    #         self.schedule_update_ha_state()
    #         _LOGGER.error(
    #             "[%s] Error updating: %s",
    #             self._device.name,
    #             ex,
    #         )

    @callback
    def _on_updated(self, state:YbtState):
        self._is_available = True
        # self._is_on = self._device.state.status == Status.ON
        _LOGGER.debug(f"HA received YBT state: {state}")
        if self.entity_id is None:
            _LOGGER.warn("[%s] Updated but the entity is not loaded", self._device.name)
            return
        self._is_on = True if state.power == Power.ON else False
        if state.mode==Mode.WHITE:
            self._color_mode=ColorMode.COLOR_TEMP
            self._color_temp_kelvin = state.temperature
        if state.mode==Mode.COLOR:
            self._color_mode=ColorMode.RGB
            self._rgb_color=state.rgb
        self._brightness = value_to_brightness(BRIGHTNESS_SCALE, state.brightness)
        _LOGGER.debug(F"Colormode:{self._color_mode}")
        # ensure HA update reflect the update
        self.schedule_update_ha_state()

    @property
    def available(self) -> bool:
        """Return if ybt device is available."""
        return self._is_available

    # @property
    # def device_info(self) -> DeviceInfo:
    #     # TODO: replace with _attr
    #     return self._device.device_info
    #     # return DeviceInfo(
    #     #     name=self._device.name,
    #     #     manufacturer="Yeelight",
    #     #     model=self._device.model,
    #     #     identifiers={(DOMAIN, self._device.mac)},
    #     #     sw_version=self._device.firmware_version,
    #     #     connections={(CONNECTION_BLUETOOTH, self._device.mac)},
    #     # )

    @property
    def brightness(self) -> int | None:
        """Return the current brightness of this light between 0..255."""
        return self._brightness
        # if self._device.state.brightness is None:
        #     return None
        # return value_to_brightness(BRIGHTNESS_SCALE, self._device.state.brightness)


    @property
    def rgb_color(self) -> tuple[int, int, int] | None:
        """
        Return the rgb color tuple.
        """
        return self._rgb_color
        # if self._device.state.mode != Mode.COLOR:
        #     return None
        # return *self._device.state.rgb

    @property
    def color_temp_kelvin(self) -> int | None:
        """Return the CT color temperature."""
        return self._color_temp_kelvin
        # if self._device.state.mode != Mode.WHITE:
        #     return None
        # return self._device.state.temperature
        # return self.temp_ybt_to_hass(self._device.state.temperature)

    @property
    def color_mode(self) -> ColorMode:
        """Return the color mode of the light."""
        return self._color_mode
        # if self._device.state.mode == Mode.COLOR:
        #     return ColorMode.RGB
        # return ColorMode.COLOR_TEMP

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

    async def async_update(self) -> None:
        # Note, update should only start fetching,
        # followed by asynchronous updates through notifications.
        try:
            _LOGGER.debug("Requesting an update of the lamp status")
            await self._device.get_state()
        except Exception as ex:
            _LOGGER.error(f"Fail requesting the light status. Got exception: {ex}")
            _LOGGER.debug("Yeelight_BT trace:", exc_info=True)

    async def async_turn_on(self, **kwargs: int) -> None:
        """Turn the light on."""
        _LOGGER.debug(f"HA Trying to turn on. with ATTR:{kwargs}")

        # First if brightness of dev to 0: turn off
        if ATTR_BRIGHTNESS in kwargs:
            brightness = kwargs[ATTR_BRIGHTNESS]
            if brightness == 0:
                _LOGGER.debug("Lamp brightness to be set to 0... so turning off")
                await self.async_turn_off()
                return
        else:
            brightness = self.brightness
        
        second_stage = any(
                keyword in kwargs
                for keyword in (ATTR_RGB_COLOR, ATTR_COLOR_TEMP_KELVIN, ATTR_BRIGHTNESS)
            )

        # ATTR cannot be set while light is off, so turn it on first
        if not self._is_on:
            await self._device.turn_on()
            self._is_on = True
            if second_stage:
                await asyncio.sleep(0.5)  # wait for the lamp to turn on before changing color
        if not second_stage:
            # not changing any attributes, returning
            return
                
        
        brightness_dev = int(brightness_to_value(BRIGHTNESS_SCALE, brightness)) # calc brightness for dev
        

        if ATTR_RGB_COLOR in kwargs:
            rgb: tuple[int, int, int] = kwargs.get(ATTR_RGB_COLOR)
            _LOGGER.debug(
                f"HA Trying to set color RGB:{rgb} with brighntess:{brightness_dev}"
            )
            await self._device.set_color(*rgb, brightness=brightness_dev)
            # assuming new state before lamp update comes through:
            self._brightness = brightness
            self._rgb_color = rgb
            self._color_mode = ColorMode.RGB
            self.schedule_update_ha_state()
            return

        if ATTR_COLOR_TEMP_KELVIN in kwargs:
            temp = kwargs[ATTR_COLOR_TEMP_KELVIN]
            _LOGGER.debug(
                f"HA Trying to set temp:{temp} with brightness:{brightness_dev}"
            )
            await self._device.set_temperature(temp, brightness=brightness_dev)
            self._brightness = brightness
            self._color_temp_kelvin = temp
            self._color_mode = ColorMode.COLOR_TEMP
            self.schedule_update_ha_state()
            return

        if ATTR_BRIGHTNESS in kwargs:
            _LOGGER.debug(f"HA Trying to set brightness: {brightness_dev}")
            await self._device.set_brightness(brightness_dev)
            self._brightness = brightness
            self.schedule_update_ha_state()
            return

        # if ATTR_EFFECT in kwargs:
        #    self._effect = kwargs[ATTR_EFFECT]

    async def async_turn_off(self, **kwargs: int) -> None:
        """Turn the light off."""
        await self._device.turn_off()
        self._is_on = False

    def temp_hass_to_ybt(self, temp: int) -> int:
        """Scale the temperature so that the white in HA UI correspond to the
        white on the lamp!"""
        a = self._device.prop_min_max["temperature"]["min"]
        b = self._device.prop_min_max["temperature"]["max"]
        mid = 2740  # the temp HA wants to set at when cliking on white in UI
        white = 4080  # the temp that correspond to true white on the lamp

        if temp < mid:
            new_temp = (white - a) / (mid - a) * temp + a * (mid - white) / (mid - a)
        else:
            new_temp = (b - white) / (b - mid) * temp + b * (white - mid) / (b - mid)
        return round(new_temp)

    def temp_ybt_to_hass(self, temp: int) -> int:
        """Reverse the scale to match HA UI"""
        a = self._device.prop_min_max["temperature"]["min"]
        b = self._device.prop_min_max["temperature"]["max"]
        mid = 2740
        white = 4080

        if temp < white:
            new_temp = (mid - a) / (white - a) * temp - a * (mid - white) / (white - a)
        else:
            new_temp = (b - mid) / (b - white) * temp - b * (white - mid) / (b - white)
        return round(new_temp)
