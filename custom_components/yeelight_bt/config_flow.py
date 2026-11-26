"""Config flow for yeelight_bt."""

from __future__ import annotations

import logging
import re
from typing import Any

import voluptuous as vol
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    async_discovered_service_info,
)
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import DOMAIN
from .yeelightbt import MODEL_UNKNOWN, model_from_name

_LOGGER = logging.getLogger(__name__)

MAC_REGEX = re.compile(r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$")


def _default_name(model: str) -> str:
    return f"Yeelight {model}"


class YeelightBTConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for yeelight_bt."""

    VERSION = 2

    def __init__(self) -> None:
        """Initialize the flow."""
        self._discovery: BluetoothServiceInfoBleak | None = None

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> ConfigFlowResult:
        """Handle a lamp discovered by the bluetooth integration."""
        _LOGGER.debug("Discovered bluetooth device: %s", discovery_info)
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()
        self._discovery = discovery_info
        self.context["title_placeholders"] = {
            "name": _default_name(model_from_name(discovery_info.name))
        }
        return await self.async_step_bluetooth_confirm()

    async def async_step_bluetooth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Confirm a discovered lamp and choose its name."""
        assert self._discovery is not None
        model = model_from_name(self._discovery.name)
        if user_input is not None:
            return self.async_create_entry(
                title=user_input[CONF_NAME],
                data={
                    CONF_NAME: user_input[CONF_NAME],
                    CONF_MAC: self._discovery.address,
                },
            )

        self._set_confirm_only()
        return self.async_show_form(
            step_id="bluetooth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_NAME, default=_default_name(model)): str}),
            description_placeholders={
                "model": model,
                "address": self._discovery.address,
            },
        )

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Pick a discovered lamp, or enter a MAC address manually."""
        errors: dict[str, str] = {}

        if user_input is not None:
            address = user_input[CONF_MAC].strip()
            if not MAC_REGEX.match(address):
                errors[CONF_MAC] = "invalid_mac"
            else:
                address = address.replace("-", ":").upper()
                await self.async_set_unique_id(format_mac(address))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_NAME],
                    data={CONF_NAME: user_input[CONF_NAME], CONF_MAC: address},
                )

        configured = self._async_current_ids(include_ignore=False)
        options = [
            SelectOptionDict(
                value=info.address,
                label=f"{info.name} ({info.address}) - {model_from_name(info.name)}",
            )
            for info in async_discovered_service_info(self.hass, connectable=True)
            if model_from_name(info.name) != MODEL_UNKNOWN
            and format_mac(info.address) not in configured
        ]

        schema = vol.Schema(
            {
                vol.Required(CONF_NAME, default="Yeelight"): str,
                vol.Required(CONF_MAC): SelectSelector(
                    SelectSelectorConfig(
                        options=options,
                        custom_value=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(schema, user_input),
            errors=errors,
        )
