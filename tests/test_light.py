"""Tests for the yeelight_bt light."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.components.light import ColorMode
from homeassistant.config_entries import ConfigEntryState
from homeassistant.const import CONF_MAC, CONF_NAME, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.yeelight_bt.const import DOMAIN
from custom_components.yeelight_bt.light import (
    ha_to_lamp_temp,
    lamp_to_ha_temp,
    to_ha_brightness,
    to_lamp_brightness,
)

from .conftest import ADDRESS, FakeLamp, make_ble_device

ENTITY_ID = "light.bedroom"


async def _setup(hass: HomeAssistant, name: str = "XMCTD_ABCD") -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        version=2,
        unique_id=ADDRESS.lower(),
        title="Bedroom",
        data={CONF_NAME: "Bedroom", CONF_MAC: ADDRESS.lower()},
    )
    entry.add_to_hass(hass)
    with patch(
        "custom_components.yeelight_bt.async_ble_device_from_address",
        return_value=make_ble_device(name),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    return entry


def test_temperature_scale() -> None:
    """HA's white maps onto the lamp's white and the scale round-trips."""
    assert ha_to_lamp_temp(2740) == 4080
    assert ha_to_lamp_temp(1700) == 1700
    assert ha_to_lamp_temp(6500) == 6500
    for kelvin in (1700, 2000, 2740, 3500, 5000, 6500):
        assert abs(lamp_to_ha_temp(ha_to_lamp_temp(kelvin)) - kelvin) <= 1


def test_brightness_scale() -> None:
    assert to_lamp_brightness(255) == 100
    assert to_lamp_brightness(1) == 1
    assert to_ha_brightness(100) == 255
    assert to_ha_brightness(50) == 128


async def test_white_mode_reports_color_temp(hass: HomeAssistant, lamps: list[FakeLamp]) -> None:
    await _setup(hass)
    lamp = lamps[0]
    lamp.mode, lamp.temperature, lamp.brightness = lamp.MODE_WHITE, 4080, 100
    lamp.notify()
    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_ON
    assert state.attributes["color_mode"] == ColorMode.COLOR_TEMP
    assert state.attributes["color_temp_kelvin"] == 2740
    assert state.attributes["brightness"] == 255


async def test_color_mode_reports_hs(hass: HomeAssistant, lamps: list[FakeLamp]) -> None:
    await _setup(hass)
    lamp = lamps[0]
    lamp.mode, lamp.color = lamp.MODE_COLOR, (255, 0, 0)
    lamp.notify()
    state = hass.states.get(ENTITY_ID)
    assert state.attributes["color_mode"] == ColorMode.HS
    assert state.attributes["hs_color"] == (0.0, 100.0)
    assert state.attributes["rgb_color"] == (255, 0, 0)


async def test_candela_brightness_only(hass: HomeAssistant, lamps: list[FakeLamp]) -> None:
    await _setup(hass, name="yeelight_ms_1234")
    lamp = lamps[0]
    lamp.mode = 0x05  # whatever the candela reports
    lamp.notify()
    state = hass.states.get(ENTITY_ID)
    assert state.state == STATE_ON
    assert state.attributes["color_mode"] == ColorMode.BRIGHTNESS
    assert state.attributes["supported_color_modes"] == [ColorMode.BRIGHTNESS]


async def test_unavailable(hass: HomeAssistant, lamps: list[FakeLamp]) -> None:
    await _setup(hass)
    lamps[0].available = False
    lamps[0].notify()
    assert hass.states.get(ENTITY_ID).state == STATE_UNAVAILABLE


@pytest.mark.parametrize(
    ("service_data", "expected_call"),
    [
        ({"hs_color": (0, 100)}, ("set_color", (255, 0, 0), {"brightness": None})),
        (
            {"hs_color": (0, 100), "brightness": 128},
            ("set_color", (255, 0, 0), {"brightness": 50}),
        ),
        ({"color_temp_kelvin": 2740}, ("set_temperature", (4080,), {"brightness": None})),
        ({"brightness": 255}, ("set_brightness", (100,), {})),
    ],
)
async def test_turn_on(
    hass: HomeAssistant, lamps: list[FakeLamp], service_data: dict, expected_call: tuple
) -> None:
    await _setup(hass)
    lamp = lamps[0]
    lamp.notify()
    lamp.calls.clear()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": ENTITY_ID, **service_data}, blocking=True
    )
    assert expected_call in lamp.calls


async def test_turn_on_from_off_powers_on_first(hass: HomeAssistant, lamps: list[FakeLamp]) -> None:
    await _setup(hass)
    lamp = lamps[0]
    lamp.is_on = False
    lamp.notify()
    lamp.calls.clear()
    await hass.services.async_call(
        "light", "turn_on", {"entity_id": ENTITY_ID, "brightness": 128}, blocking=True
    )
    names = [c[0] for c in lamp.calls]
    assert names.index("turn_on") < names.index("set_brightness")
    assert hass.states.get(ENTITY_ID).state == STATE_ON


async def test_unique_id_preserved_and_unload(hass: HomeAssistant, lamps: list[FakeLamp]) -> None:
    entry = await _setup(hass)
    registry = er.async_get(hass)
    assert registry.async_get(ENTITY_ID).unique_id == ADDRESS
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert entry.state is ConfigEntryState.NOT_LOADED
    assert ("disconnect", (), {}) in lamps[0].calls


async def test_not_ready_without_device(hass: HomeAssistant, lamps: list[FakeLamp]) -> None:
    entry = MockConfigEntry(domain=DOMAIN, version=2, data={CONF_NAME: "x", CONF_MAC: ADDRESS})
    entry.add_to_hass(hass)
    with patch("custom_components.yeelight_bt.async_ble_device_from_address", return_value=None):
        await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_diagnostics(hass: HomeAssistant, lamps: list[FakeLamp]) -> None:
    from custom_components.yeelight_bt.diagnostics import async_get_config_entry_diagnostics

    entry = await _setup(hass)
    with patch(
        "custom_components.yeelight_bt.diagnostics.async_last_service_info", return_value=None
    ):
        diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["lamp"]["model"] == "Bedside"
    assert diag["bluetooth"] is None
