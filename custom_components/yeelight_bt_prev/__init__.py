"""Control Yeelight bluetooth lamp."""
import logging

from homeassistant.components.bluetooth import (
    async_ble_device_from_address,
    async_scanner_count,
    async_scanner_devices_by_address,
    async_rediscover_address
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .yeelightbt.yeelightbt import YeelightBT, Model as YBTModel

from .const import (
    DOMAIN,
    CONF_ADAPTER,
    DEFAULT_ADAPTER,
    CONF_STAY_CONNECTED,
    DEFAULT_STAY_CONNECTED,
)

PLATFORMS = [
    Platform.LIGHT,
    Platform.SENSOR,
]


_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up yeelight_bt from a config entry."""
    _LOGGER.debug(f"integration async setup entry: {entry.as_dict()}")

    # Store an instance of the "connecting" class that does the work of speaking
    # with your actual devices.
    _LOGGER.debug(f"MAC of entry: {entry.data[CONF_MAC]}")
    ybt = YeelightBT(
        mac=entry.data[CONF_MAC],
        model=YBTModel.BEDSIDE,
        name=entry.data[CONF_NAME],
        # adapter=entry.data[CONF_ADAPTER],
        adapter=entry.options.get(CONF_ADAPTER, DEFAULT_ADAPTER),
        stay_connected=entry.options.get(CONF_STAY_CONNECTED, DEFAULT_STAY_CONNECTED),
        use_notif=True,
        hass=hass,
    )
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = ybt

    # # Find ble device here so that we can raise device not found on startup
    # address = entry.data.get(CONF_MAC)
    # adapter = entry.options.get(CONF_ADAPTER, DEFAULT_ADAPTER)
    # stay_connected = entry.options.get(CONF_STAY_CONNECTED, DEFAULT_STAY_CONNECTED)

    # # try to get ble_device using HA scanner first
    # ble_device = async_ble_device_from_address(hass, address.upper(), connectable=True)
    # _LOGGER.debug(f"BLE device through HA bt: {ble_device}")
    # if ble_device is None:
    #     # Check if any HA scanner on:
    #     count_scanners = async_scanner_count(hass, connectable=True)
    #     _LOGGER.debug(f"Count of BLE scanners in HA bt: {count_scanners}")
    #     if count_scanners < 1:
    #         raise ConfigEntryNotReady(
    #             "No bluetooth scanner detected. \
    #             Enable the bluetooth integration or ensure an esphome device \
    #             is running as a bluetooth proxy"
    #         )
    #     raise ConfigEntryNotReady(f"Could not find Yeelight with address {address}")

    # hass.data.setdefault(DOMAIN, {})[entry.entry_id] = ble_device

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # This creates each HA object for each platform your device requires.
    # It's done by calling the `async_setup_entry` function in each platform module.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # This is called when an entry/configured device is to be removed. The class
    # needs to unload itself, and remove callbacks. See the classes for further
    # details
    _LOGGER.debug("async unload entry")
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        ybt = hass.data[DOMAIN].pop(entry.entry_id)
        await ybt.async_disconnect()
        if not hass.config_entries.async_entries(DOMAIN):
            hass.data.pop(DOMAIN)
        # Trigger rediscover:
        async_rediscover_address(hass, ybt.mac)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener. Called when integration options are changed"""
    data: YeelightBT = hass.data[DOMAIN][entry.entry_id]
    # if entry.title != data.title:
    # TODO only reload if an option has changed
    await hass.config_entries.async_reload(entry.entry_id)
