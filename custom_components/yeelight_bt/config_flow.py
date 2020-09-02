"""Config flow for yeelight_bt"""
import logging
from homeassistant import config_entries
from homeassistant.const import CONF_NAME, CONF_MAC
import voluptuous as vol
from homeassistant.helpers import device_registry as dr, config_validation as cv

from .const import DOMAIN



_LOGGER = logging.getLogger(__name__)

class SimpleConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for yeelight_bt."""

    VERSION = 1
    CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL


    @property
    def data_schema(self):
        """Return the data schema for integration."""
        return vol.Schema(
            {
                vol.Required(CONF_NAME): str,
                vol.Required(CONF_MAC): str,
            }
        )


    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}
        _LOGGER.debug(f"User_input: {user_input}")
        if not user_input:
            return self.async_show_form(step_id="user", data_schema=self.data_schema)
            
        unique_id = dr.format_mac(user_input[CONF_MAC])
        _LOGGER.debug(f"UniqueID: {unique_id}")

        await self.async_set_unique_id(unique_id)
        self._abort_if_unique_id_configured()
        
        
        
        
        # try:
        #     #Check if we can connect to the lamp here
        #     await client.cdc_reports.status_by_coordinates(
        #         user_input[CONF_LATITUDE], user_input[CONF_LONGITUDE]
        #     )
        # except FluNearYouError as err:
        #     _LOGGER.error("Error while configuring integration: %s", err)
        #     errors["base"] = "auth_error"
        #     return self.async_show_form(
        #         step_id="user", errors=errors
        #     )

        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

    async def async_step_import(self, import_info):
        """Handle import from config file."""
        return await self.async_step_user(import_info)