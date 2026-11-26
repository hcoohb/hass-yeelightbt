"""Light platform for Yeelight bluetooth lamps."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_COLOR_TEMP_KELVIN,
    ATTR_HS_COLOR,
    ColorMode,
    LightEntity,
)
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import CONNECTION_BLUETOOTH, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util.color import color_hs_to_RGB, color_RGB_to_hs

from . import YeelightBTConfigEntry
from .const import DOMAIN
from .yeelightbt import MODEL_CANDELA, Lamp

_LOGGER = logging.getLogger(__name__)

# Bluetooth commands to a single lamp must not overlap.
PARALLEL_UPDATES = 1

# The lamp aborts a running transition when it receives another command
# (including a state request), so give it time before HA polls it again.
TRANSITION_WAIT = 0.7
# Time the lamp needs after power on before it accepts colour/brightness.
POWER_ON_WAIT = 0.5

TEMP_MIN = 1700
TEMP_MAX = 6500
# HA's "white" colour temperature and the temperature that is real white on the lamp.
# Temperatures are rescaled piecewise-linearly so both whites line up.
HA_WHITE = 2740
LAMP_WHITE = 4080


def ha_to_lamp_temp(kelvin: int) -> int:
    """Scale a HA colour temperature to the lamp's scale."""
    a, b = TEMP_MIN, TEMP_MAX
    if kelvin < HA_WHITE:
        new = (LAMP_WHITE - a) / (HA_WHITE - a) * kelvin + a * (HA_WHITE - LAMP_WHITE) / (
            HA_WHITE - a
        )
    else:
        new = (b - LAMP_WHITE) / (b - HA_WHITE) * kelvin + b * (LAMP_WHITE - HA_WHITE) / (
            b - HA_WHITE
        )
    return min(TEMP_MAX, max(TEMP_MIN, round(new)))


def lamp_to_ha_temp(kelvin: int) -> int:
    """Scale a lamp colour temperature back to HA's scale."""
    a, b = TEMP_MIN, TEMP_MAX
    if kelvin < LAMP_WHITE:
        new = (HA_WHITE - a) / (LAMP_WHITE - a) * kelvin - a * (HA_WHITE - LAMP_WHITE) / (
            LAMP_WHITE - a
        )
    else:
        new = (b - HA_WHITE) / (b - LAMP_WHITE) * kelvin - b * (LAMP_WHITE - HA_WHITE) / (
            b - LAMP_WHITE
        )
    return min(TEMP_MAX, max(TEMP_MIN, round(new)))


def to_lamp_brightness(brightness: int) -> int:
    """Convert HA brightness (0-255) to lamp brightness (1-100)."""
    return min(100, max(1, round(brightness / 255 * 100)))


def to_ha_brightness(brightness: int) -> int:
    """Convert lamp brightness (0-100) to HA brightness (0-255)."""
    return min(255, max(0, round(brightness / 100 * 255)))


async def async_setup_entry(
    hass: HomeAssistant,
    entry: YeelightBTConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the light from a config entry."""
    async_add_entities([YeelightBTLight(entry.runtime_data, entry)])


class YeelightBTLight(LightEntity):
    """A Yeelight bluetooth lamp."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_should_poll = True
    _attr_available = False
    _attr_min_color_temp_kelvin = TEMP_MIN
    _attr_max_color_temp_kelvin = TEMP_MAX

    def __init__(self, lamp: Lamp, entry: YeelightBTConfigEntry) -> None:
        """Initialize the light."""
        self._lamp = lamp
        self._is_candela = lamp.model == MODEL_CANDELA
        # Kept identical to earlier releases so existing entities are preserved.
        self._attr_unique_id = lamp.mac
        if self._is_candela:
            self._attr_supported_color_modes = {ColorMode.BRIGHTNESS}
            self._attr_color_mode = ColorMode.BRIGHTNESS
        else:
            self._attr_supported_color_modes = {ColorMode.COLOR_TEMP, ColorMode.HS}
            self._attr_color_mode = ColorMode.COLOR_TEMP
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, lamp.mac)},
            connections={(CONNECTION_BLUETOOTH, lamp.mac)},
            name=entry.data.get(CONF_NAME) or entry.title,
            manufacturer="Yeelight",
            model=lamp.model,
        )
        self._sw_version_reported = False

    async def async_added_to_hass(self) -> None:
        """Register for lamp notifications and fetch the initial state."""
        self.async_on_remove(self._lamp.add_callback_on_state_changed(self._handle_lamp_update))
        self.async_schedule_update_ha_state(force_refresh=True)

    @callback
    def _handle_lamp_update(self) -> None:
        """Handle a state notification (or a disconnect) from the lamp."""
        self._update_from_lamp()
        self._report_sw_version()
        self.async_write_ha_state()

    @callback
    def _update_from_lamp(self) -> None:
        """Copy the lamp state onto the entity."""
        lamp = self._lamp
        self._attr_available = lamp.available
        if not lamp.available:
            return
        self._attr_is_on = lamp.is_on
        self._attr_brightness = to_ha_brightness(lamp.brightness)
        if self._is_candela:
            return
        if lamp.mode == lamp.MODE_WHITE:
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_color_temp_kelvin = lamp_to_ha_temp(lamp.temperature)
        elif lamp.mode in (lamp.MODE_COLOR, lamp.MODE_FLOW):
            self._attr_color_mode = ColorMode.HS
            self._attr_hs_color = color_RGB_to_hs(*lamp.color)

    @callback
    def _report_sw_version(self) -> None:
        """Store the firmware version on the device once the lamp has sent it."""
        if self._sw_version_reported or not self._lamp.versions:
            return
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device(identifiers={(DOMAIN, self._lamp.mac)})
        if device is None:
            return
        sw_version = "-".join(map(str, self._lamp.versions[1:4]))
        device_registry.async_update_device(device.id, sw_version=sw_version)
        self._sw_version_reported = True

    async def async_update(self) -> None:
        """Request the lamp state; the answer arrives as a notification."""
        try:
            await self._lamp.get_state()
        except Exception:  # noqa: BLE001 - keep polling alive on any BLE failure
            _LOGGER.debug("Failed requesting the state of %s", self._lamp.mac, exc_info=True)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the light on."""
        _LOGGER.debug("Turn on %s with %s", self._lamp.mac, kwargs)
        brightness: int | None = None
        if ATTR_BRIGHTNESS in kwargs:
            brightness = to_lamp_brightness(kwargs[ATTR_BRIGHTNESS])

        if not self.is_on:
            await self._lamp.turn_on()
            if kwargs:
                await asyncio.sleep(POWER_ON_WAIT)

        if ATTR_HS_COLOR in kwargs and not self._is_candela:
            red, green, blue = color_hs_to_RGB(*kwargs[ATTR_HS_COLOR])
            await self._lamp.set_color(red, green, blue, brightness=brightness)
            self._attr_color_mode = ColorMode.HS
            self._attr_hs_color = kwargs[ATTR_HS_COLOR]
        elif ATTR_COLOR_TEMP_KELVIN in kwargs and not self._is_candela:
            kelvin = kwargs[ATTR_COLOR_TEMP_KELVIN]
            await self._lamp.set_temperature(ha_to_lamp_temp(kelvin), brightness=brightness)
            self._attr_color_mode = ColorMode.COLOR_TEMP
            self._attr_color_temp_kelvin = kelvin
        elif brightness is not None:
            await self._lamp.set_brightness(brightness)

        self._attr_is_on = True
        if brightness is not None:
            self._attr_brightness = kwargs[ATTR_BRIGHTNESS]
        self.async_write_ha_state()
        if kwargs:
            await asyncio.sleep(TRANSITION_WAIT)

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the light off."""
        await self._lamp.turn_off()
        self._attr_is_on = False
        self.async_write_ha_state()
