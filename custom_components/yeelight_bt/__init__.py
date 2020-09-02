"""Control Yeelight bluetooth lamp."""
import voluptuous as vol
import logging

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry, ConfigEntries
from homeassistant.core import HomeAssistant
import homeassistant.helpers.config_validation as cv

from .const import DOMAIN, PLATFORM


_LOGGER = logging.getLogger(__name__)



async def async_setup(hass: HomeAssistant, config: dict):
    """Set up yeelight bt from configuration.yaml."""
    _LOGGER.debug(f"async setup.")
    # _LOGGER.debug(f"YAML config:{config}")
    _LOGGER.debug(f" List entries for domain:")
    _LOGGER.debug(hass.config_entries.async_entries(DOMAIN))
    
    conf = config.get(DOMAIN)
    if conf:
        hass.async_create_task(
            hass.config_entries.flow.async_init(
                DOMAIN, data=conf, context={"source": SOURCE_IMPORT}
            )
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Set up yeelight_bt from a config entry."""
    _LOGGER.debug(f"async setup entry: {entry.as_dict()}")
    hass.async_create_task(
        hass.config_entries.async_forward_entry_setup(entry, "light")
    )
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.debug("async unload entry")
    return await hass.config_entries.async_forward_entry_unload(entry, "light")