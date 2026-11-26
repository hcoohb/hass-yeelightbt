"""Diagnostics support for yeelight_bt."""

from __future__ import annotations

from typing import Any

from homeassistant.components.bluetooth import async_last_service_info
from homeassistant.core import HomeAssistant

from . import YeelightBTConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: YeelightBTConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    lamp = entry.runtime_data
    service_info = async_last_service_info(hass, lamp.mac, connectable=True)
    return {
        "entry_data": dict(entry.data),
        "lamp": {
            "model": lamp.model,
            "available": lamp.available,
            "is_on": lamp.is_on,
            "mode": lamp.mode,
            "brightness": lamp.brightness,
            "temperature": lamp.temperature,
            "color": lamp.color,
            "versions": lamp.versions,
            "state": str(lamp),
        },
        "bluetooth": None
        if service_info is None
        else {
            "name": service_info.name,
            "rssi": service_info.rssi,
            "source": service_info.source,
            "connectable": service_info.connectable,
        },
    }
