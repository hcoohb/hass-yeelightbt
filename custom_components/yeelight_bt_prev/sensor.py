from .const import CONF_DEBUG_MODE, DOMAIN
import asyncio
import logging

from homeassistant.helpers.device_registry import format_mac
from .yeelightbt.yeelightbt import YeelightBT
from homeassistant.components.sensor import SensorEntity, SensorDeviceClass, SensorStateClass
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import device_registry as dr
from homeassistant.core import HomeAssistant
from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    ybt = hass.data[DOMAIN][config_entry.entry_id]
    debug_mode = config_entry.options.get(CONF_DEBUG_MODE, False)

    new_devices = [
        SerialNumberSensor(ybt),
        FirmwareVersionSensor(ybt),
    ]
    async_add_entities(new_devices)
    if debug_mode:
        new_devices = [
            RssiSensor(ybt),
            MacSensor(ybt),
            RetriesSensor(ybt),
            PathSensor(ybt),
        ]
        async_add_entities(new_devices)


class Base(SensorEntity):
    def __init__(self, ybt: YeelightBT):
        self._ybt = ybt
        self._attr_has_entity_name = True
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, self._ybt.mac)})

    @property
    def unique_id(self) -> str:
        assert self.name
        return format_mac(self._ybt.mac) + "_" + self.name



class RssiSensor(Base):
    def __init__(self, ybt: YeelightBT):
        super().__init__(ybt)
        # ybt._conn.register_connection_callback(self.async_schedule_update_ha_state)
        self._attr_name = "Rssi"
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
        self._attr_entity_registry_enabled_default = False
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def state(self):
        return self._ybt._conn.rssi


class SerialNumberSensor(Base):
    def __init__(self, ybt: YeelightBT):
        super().__init__(ybt)
        self._attr_name = "Serial"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_added_to_hass(self) -> None:
        _LOGGER.debug("In serial async_added_to_ass")
        self._ybt.register_update_callback(self.async_schedule_update_ha_state)
        # asyncio.get_event_loop().create_task(self.fetch_serial())

    async def fetch_serial(self):
        _LOGGER.debug("Fetching serial")
        await self._ybt.get_serial()

        _LOGGER.debug(
            "[%s] serial: %s",
            self._ybt.name,
            self._ybt.device_serial,
        )

    @property
    def state(self):
        return self._ybt.device_serial


class FirmwareVersionSensor(Base):
    def __init__(self, ybt: YeelightBT):
        super().__init__(ybt)
        self._attr_name = "Firmware Version"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    async def async_added_to_hass(self) -> None:
        _LOGGER.debug("In firmware async_added_to_ass")
        self._ybt.register_update_callback(self.async_schedule_update_ha_state)
        asyncio.get_event_loop().create_task(self.fetch_version())

    async def fetch_version(self):
        _LOGGER.debug("Fetching version")
        await self._ybt.get_version()
        _LOGGER.debug("version fetched")
        device_registry = dr.async_get(self.hass)
        device = device_registry.async_get_device(
            identifiers={(DOMAIN, self._ybt.mac)},
        )
        if device:
            device_registry.async_update_device(
                device_id=device.id, sw_version=self._ybt.firmware_version
            )

        _LOGGER.debug(
            "[%s] firmware: %s",
            self._ybt.name,
            self._ybt.firmware_version
        )

    @property
    def state(self):
        return self._ybt.firmware_version


class MacSensor(Base):
    def __init__(self, ybt: YeelightBT):
        super().__init__(ybt)
        self._attr_name = "MAC"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def state(self):
        return self._ybt.mac


class RetriesSensor(Base):
    def __init__(self, ybt: YeelightBT):
        super().__init__(ybt)
        # _ybt._conn.register_connection_callback(self.async_schedule_update_ha_state)
        self._attr_name = "Retries"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def state(self):
        return self._ybt._conn.retries


class PathSensor(Base):
    def __init__(self, ybt: YeelightBT):
        super().__init__(ybt)
        # _ybt._conn.register_connection_callback(self.async_schedule_update_ha_state)
        self._attr_name = "Path"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def state(self):
        if self._ybt._conn._conn is None:
            return None
        # _LOGGER.debug(f"Backend is {self._ybt._conn._conn._backend}")
        # return self._ybt._conn._conn._backend._device_path
        return "the_path"
