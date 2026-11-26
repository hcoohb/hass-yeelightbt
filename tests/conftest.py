"""Fixtures for yeelight_bt tests."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.yeelight_bt.yeelightbt import Lamp, model_from_name

ADDRESS = "F8:24:41:E6:3E:39"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations: None) -> None:
    """Enable loading custom integrations."""


@pytest.fixture(autouse=True)
def fake_bluetooth(hass: HomeAssistant) -> None:
    """Pretend the bluetooth integration is loaded; its API is patched per test."""
    hass.config.components.add("bluetooth")


class FakeLamp:
    """In-memory stand-in for the BLE Lamp."""

    MODE_COLOR = Lamp.MODE_COLOR
    MODE_WHITE = Lamp.MODE_WHITE
    MODE_FLOW = Lamp.MODE_FLOW

    def __init__(self, ble_device: Any) -> None:
        self.mac = ble_device.address
        self.model = model_from_name(ble_device.name)
        self.available = True
        self.is_on = True
        self.mode: int | None = self.MODE_WHITE
        self.brightness = 50
        self.temperature = 4080
        self.color = (0, 0, 0)
        self.versions: tuple[int, ...] | None = None
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self._callbacks: list[Callable[[], None]] = []

    def add_callback_on_state_changed(self, func: Callable[[], None]) -> Callable[[], None]:
        self._callbacks.append(func)
        return lambda: self._callbacks.remove(func)

    def notify(self) -> None:
        for func in list(self._callbacks):
            func()

    def set_ble_device(self, ble_device: Any) -> None:
        self.calls.append(("set_ble_device", (ble_device,), {}))

    def __getattr__(self, name: str) -> Any:
        if name in {
            "get_state",
            "turn_on",
            "turn_off",
            "set_brightness",
            "set_temperature",
            "set_color",
            "disconnect",
        }:

            async def _record(*args: Any, **kwargs: Any) -> None:
                self.calls.append((name, args, kwargs))

            return _record
        raise AttributeError(name)


def make_ble_device(name: str = "XMCTD_ABCD", address: str = ADDRESS) -> MagicMock:
    device = MagicMock()
    device.name = name
    device.address = address
    device.details = {"source": "esp-proxy"}
    return device


@pytest.fixture
def lamps() -> Generator[list[FakeLamp]]:
    """Patch the integration to use FakeLamp and BLE helpers that find the lamp."""
    created: list[FakeLamp] = []

    def _factory(ble_device: Any) -> FakeLamp:
        lamp = FakeLamp(ble_device)
        created.append(lamp)
        return lamp

    with (
        patch("custom_components.yeelight_bt.Lamp", side_effect=_factory),
        patch("custom_components.yeelight_bt.async_register_callback", return_value=lambda: None),
        patch("custom_components.yeelight_bt.async_scanner_count", return_value=1),
        patch("custom_components.yeelight_bt.light.TRANSITION_WAIT", 0),
        patch("custom_components.yeelight_bt.light.POWER_ON_WAIT", 0),
    ):
        yield created
