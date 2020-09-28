"""Control Yeelight bluetooth lamp."""
import logging

from homeassistant.config_entries import SOURCE_IMPORT, ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict):
    """Set up yeelight bt from configuration.yaml."""
    _LOGGER.debug("async setup.")
    # _LOGGER.debug(f"YAML config:{config}")
    _LOGGER.debug(" List entries for domain:")
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


async def async_migrate_entry(hass, entry):
    """Migrate old entry."""
    data = entry.data
    version = entry.version

    _LOGGER.debug(f"Migrating Yeelight_bt from Version {version}. it has data: {data}")
    # Migrate Version 1 -> Version 2: Stuff up... nothing changed.
    if version == 1:
        version = entry.version = 2
        hass.config_entries.async_update_entry(entry, data=data)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry):
    """Unload a config entry."""
    _LOGGER.debug("async unload entry")
    return await hass.config_entries.async_forward_entry_unload(entry, "light")
