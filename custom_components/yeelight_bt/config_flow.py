"""Config flow for yeelight_bt"""
import logging
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_MAC
import voluptuous as vol
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, CONF_ENTRY_METHOD, CONF_ENTRY_SCAN, CONF_ENTRY_MANUAL

from .yeelightbt import (
    discover_yeelight_lamps,
    BTLEDisconnectError,
    BTLEManagementError,
)

_LOGGER = logging.getLogger(__name__)


class Yeelight_btConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):  # type: ignore
    """Handle a config flow for yeelight_bt."""

    VERSION = 2
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    @property
    def data_schema(self):
        """Return the data schema for integration."""
        return vol.Schema({vol.Required(CONF_NAME): str, vol.Required(CONF_MAC): str})

    async def async_step_user(self, user_input=None):
        """Handle a flow initialized by the user."""

        if user_input is None:
            schema = {
                vol.Required(CONF_ENTRY_METHOD): vol.In(
                    [CONF_ENTRY_SCAN, CONF_ENTRY_MANUAL]
                )
            }
            return self.async_show_form(step_id="user", data_schema=vol.Schema(schema))
        method = user_input[CONF_ENTRY_METHOD]
        _LOGGER.debug(f"Method selected: {method}")
        if method == CONF_ENTRY_SCAN:
            return await self.async_step_scan()
        else:
            self.devices = []
            return await self.async_step_device()

    async def async_step_scan(self, user_input=None):
        """Handle the discovery by scanning."""
        errors = {}
        if user_input is None:
            return self.async_show_form(step_id="scan")
        _LOGGER.debug("Starting a scan for Yeelight Bt devices")
        try:
            devices = await self.hass.async_add_executor_job(discover_yeelight_lamps)
        except BTLEDisconnectError as err:
            _LOGGER.error(f"Bluetooth connection error while trying to scan: {err}")
            errors["base"] = "BTLEDisconnectError"
            return self.async_show_form(step_id="scan", errors=errors)
        except BTLEManagementError as err:
            _LOGGER.error(f"Bluetooth connection error while trying to scan: {err}")
            errors["base"] = "BTLEManagementError"
            return self.async_show_form(step_id="scan", errors=errors)

        if not devices:
            return self.async_abort(reason="no_devices_found")
        self.devices = [f"{dev['mac']} ({dev['model']})" for dev in devices]
        # TODO: filter existing devices ?

        return await self.async_step_device()

    async def async_step_device(self, user_input=None):
        """Handle setting up a device."""
        # _LOGGER.debug(f"User_input: {user_input}")
        if not user_input:
            schema_mac = str
            if self.devices:
                schema_mac = vol.In(self.devices)
            schema = vol.Schema(
                {vol.Required(CONF_NAME): str, vol.Required(CONF_MAC): schema_mac}
            )
            return self.async_show_form(step_id="device", data_schema=schema)

        user_input[CONF_MAC] = user_input[CONF_MAC][:17]
        unique_id = dr.format_mac(user_input[CONF_MAC])
        _LOGGER.debug(f"Yeelight UniqueID: {unique_id}")

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()

        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

    async def async_step_import(self, import_info):
        """Handle import from config file."""
        return await self.async_step_device(import_info)
