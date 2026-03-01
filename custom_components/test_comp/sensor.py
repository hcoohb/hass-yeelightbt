from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Add sensors for passed config_entry in HA."""
    async_add_entities([Base()])


class Base(SensorEntity):
    def __init__(self):
        self._attr_name = "Base"
        self._attr_has_entity_name = True

    @property
    def unique_id(self) -> str:
        assert self.name
        return "ID_" + self.name

    @property
    def state(self):
        return "hello"
