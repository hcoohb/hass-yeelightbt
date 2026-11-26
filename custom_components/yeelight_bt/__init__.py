"""Control Yeelight bluetooth lamps."""

from __future__ import annotations

import logging

from homeassistant.components.bluetooth import (
    BluetoothCallbackMatcher,
    BluetoothChange,
    BluetoothScanningMode,
    BluetoothServiceInfoBleak,
    async_ble_device_from_address,
    async_register_callback,
    async_scanner_count,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_MAC, EVENT_HOMEASSISTANT_STOP, Platform
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN
from .yeelightbt import Lamp

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.LIGHT]

type YeelightBTConfigEntry = ConfigEntry[Lamp]


async def async_setup_entry(hass: HomeAssistant, entry: YeelightBTConfigEntry) -> bool:
    """Set up yeelight_bt from a config entry."""
    address: str = entry.data[CONF_MAC].upper()

    ble_device = async_ble_device_from_address(hass, address, connectable=True)
    if ble_device is None:
        if async_scanner_count(hass, connectable=True) < 1:
            raise ConfigEntryNotReady(translation_domain=DOMAIN, translation_key="no_scanner")
        raise ConfigEntryNotReady(
            translation_domain=DOMAIN,
            translation_key="device_not_found",
            translation_placeholders={"address": address},
        )

    lamp = Lamp(ble_device)
    entry.runtime_data = lamp

    @callback
    def _async_update_ble(service_info: BluetoothServiceInfoBleak, change: BluetoothChange) -> None:
        """Keep the BLEDevice current, e.g. when a different proxy hears the lamp."""
        lamp.set_ble_device(service_info.device)

    entry.async_on_unload(
        async_register_callback(
            hass,
            _async_update_ble,
            BluetoothCallbackMatcher(address=address, connectable=True),
            BluetoothScanningMode.PASSIVE,
        )
    )

    async def _async_stop(event: Event) -> None:
        """Release the bluetooth connection when Home Assistant stops."""
        await lamp.disconnect()

    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, _async_stop))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: YeelightBTConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        await entry.runtime_data.disconnect()
    return unload_ok
