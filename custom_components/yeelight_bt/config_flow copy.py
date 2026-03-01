"""Config flow for yeelight_bt"""
from __future__ import annotations

import logging
from typing import Any
import asyncio

import voluptuous as vol
from homeassistant.helpers import config_validation as cv
from homeassistant.config_entries import ConfigFlow, OptionsFlow, ConfigEntry
from homeassistant.components.bluetooth import (
    BluetoothServiceInfoBleak,
    # async_get_scanner,
    async_scanner_devices_by_address,
    _get_manager,
)
from homeassistant.core import callback

# from homeassistant.components.bluetooth.scanner import create_bleak_scanner
from homeassistant.const import CONF_MAC, CONF_NAME, CONF_SCAN_INTERVAL
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import selector

from .const import (
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    CONF_ADAPTER,
    DEFAULT_ADAPTER,
    CONF_STAY_CONNECTED,
    DEFAULT_STAY_CONNECTED,
    CONF_DEBUG_MODE,
)

from .yeelightbt.connection import Adapter, PairingStatus
from .yeelightbt.yeelightbt import ybt_model_from_ble_name, YeelightBT

_LOGGER = logging.getLogger(__name__)


def ybt_name_from_info_service(info: BluetoothServiceInfoBleak) -> str:
    name = info.device.name or info.name
    model = ybt_model_from_ble_name(name)
    #TODO: Can we try to read the name?
    return f"{model}_{info.address.replace(':', '')[-4:]}"


class Yeelight_btConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore
    """Handle a config flow for yeelight_bt."""

    VERSION = 2
    # CONNECTION_CLASS = config_entries.CONN_CLASS_LOCAL_POLL

    def __init__(self):
        """Initialize the Config flow."""
        self.discovery_info: BluetoothServiceInfoBleak = None
        self.set_pairing = None
        self.wait_pairing = None
        self.ybt = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        _LOGGER.debug("async_step_user: %s", user_input)

        errors = {}
        if user_input is None:
            schema = vol.Schema(
                {
                    vol.Required(CONF_NAME): str,
                    vol.Required(CONF_MAC): str,
                }
            )
            return self.async_show_form(
                step_id="user", data_schema=schema, errors=errors
            )
        await self.async_set_unique_id(format_mac(user_input[CONF_MAC]))
        self._abort_if_unique_id_configured(updates=user_input)
        return self.async_create_entry(title=user_input[CONF_NAME], data=user_input)

    async def async_step_bluetooth(
        self, discovery_info: BluetoothServiceInfoBleak
    ) -> FlowResult:
        """Handle the bluetooth discovery step."""
        _LOGGER.debug(
            "Discovered bluetooth device: %s on source %s",
            discovery_info,
            discovery_info.source,
        )
        await self.async_set_unique_id(format_mac(discovery_info.address))
        self._abort_if_unique_id_configured()

        self.discovery_info = discovery_info
        name = ybt_name_from_info_service(discovery_info)
        self.context.update(
            {
                "title_placeholders": {
                    CONF_NAME: name,
                    CONF_MAC: discovery_info.address,
                    "rssi": discovery_info.rssi,
                }
            }
        )
        return await self.async_step_init()

    async def async_step_init(self, user_input=None):
        """Handle a flow start."""
        _LOGGER.debug("I am in the init step")
        if self.discovery_info is None:
            # mainly to shut up the type checker
            return self.async_abort(reason="not_supported")
        address = self.discovery_info.address
        self._async_abort_entries_match({CONF_MAC: address})
        if user_input is None:
            name = ybt_name_from_info_service(self.discovery_info)
            adapters = async_scanner_devices_by_address(
                self.hass, address=address, connectable=True
            )
            # TODO sort the adapter list by RSSI
            _LOGGER.debug(
                f"The following adapters found the light:{[f'{ad.scanner.name} (source: {ad.scanner.source}, rssi: {ad.advertisement.rssi}dBm, connectable: {ad.scanner.connectable}]' for ad in adapters]}"
            )
            if not adapters:
                # no adapters found the light
                return self.async_abort(reason="no_longer_discovered")
            adapters_options = [
                {
                    "label": f"{ad.scanner.name} ({ad.advertisement.rssi}dB)",
                    "value": ad.scanner.source,
                }
                for ad in adapters
            ]
            return self.async_show_form(
                step_id="init",
                data_schema=vol.Schema(
                    {
                        vol.Required(CONF_NAME, default=name): str,  # type: ignore
                        vol.Required(
                            CONF_ADAPTER,
                            description={
                                "suggested_value": adapters_options[0]["value"]
                            },
                        ): selector(
                            {
                                "select": {
                                    "options": adapters_options,
                                    "custom_value": False,
                                }
                            }
                        ),
                    }
                ),
                description_placeholders={
                    CONF_NAME: name,
                    CONF_MAC: address,
                },
            )
        _LOGGER.debug(f"The data received from the form was {user_input}")
        self.data = {
            CONF_NAME: user_input[CONF_NAME],
            CONF_MAC: address,
            CONF_ADAPTER: user_input[CONF_ADAPTER],
        }
        ble_name = self.discovery_info.device.name or self.discovery_info.name
        model = ybt_model_from_ble_name(ble_name)
        self.ybt = YeelightBT(
            address,
            model,
            user_input[CONF_NAME],
            user_input[CONF_ADAPTER],
            True,
            True,
            self.hass,
        )
        # onto the pairing step:
        return await self.async_step_set_pairing()

    async def async_step_set_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """We connect and set the lamp for pairing"""
        _LOGGER.debug("In set pairing step")
        if not self.set_pairing:
            task = self.ybt.set_pairing_mode()
            _LOGGER.info("scheduling set pairing")
            self.set_pairing = self.hass.async_create_task(self._async_do_task(task))
            return self.async_show_progress(
                step_id="set_pairing",
                progress_action="set_pairing",
            )
        try:
            await self.set_pairing
        except asyncio.TimeoutError:
            self.set_pairing = None
            return self.async_show_progress_done(next_step_id="pairing_timeout")
        _LOGGER.info("async_step_progress - set_pairing done")
        self.set_pairing = None
        if self.ybt.pairing_status == PairingStatus.PAIRING:
            return self.async_show_progress_done(next_step_id="wait_pairing")
        if self.ybt.pairing_status == PairingStatus.PAIRED:
            return self.async_show_progress_done(next_step_id="finish")
        _LOGGER.error("Could not set the lamp to pairing mode")
        return self.async_show_progress_done(next_step_id="pairing_needs_reset")
        # return self.async_abort(reason="request_pairing_failed")

    async def async_step_pairing_needs_reset(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        return self.async_abort(reason="pairing_needs_reset")

    async def async_step_wait_pairing(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """We connect and set the lamp for pairing"""
        _LOGGER.debug("In wait pairing step")
        if not self.wait_pairing:
            task = self.ybt.wait_paired()
            _LOGGER.info("scheduling wait pairing")
            self.wait_pairing = self.hass.async_create_task(self._async_do_task(task))
            return self.async_show_progress(
                step_id="wait_pairing",
                progress_action="wait_pairing",
            )
        try:
            await self.wait_pairing
        except asyncio.TimeoutError:
            self.wait_pairing = None
            return self.async_show_progress_done(next_step_id="pairing_timeout")
        _LOGGER.info("async_step_progress - wait_pairing done")
        self.wait_pairing = None
        _LOGGER.debug(f"pair status: {self.ybt.pairing_status}")
        _LOGGER.debug(self.ybt.pairing_status)
        _LOGGER.debug(PairingStatus.PAIRED)
        _LOGGER.debug(self.ybt.pairing_status == PairingStatus.PAIRED)
        if self.ybt.pairing_status == PairingStatus.PAIRED:
            return self.async_show_progress_done(next_step_id="finish")
        _LOGGER.error("Could not detect lamp as paired")
        self.async_abort(reason="request_pairing_failed")

    async def _async_do_task(self, task):
        await task  # A task that take some time to complete.
        # Ensure we go back to the flow
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
        )

    async def async_step_pairing_timeout(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Inform the user that the device never entered pairing mode."""
        if user_input is not None:
            return await self.async_step_progress()

        self._set_confirm_only()
        return self.async_show_form(step_id="pairing_timeout")

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        _LOGGER.debug("In finish step")
        if user_input is None:
            return self.async_show_form(step_id="finish")
        # Finally create the config_entry
        await self.ybt.async_disconnect()
        return self.async_create_entry(
            title=self.data[CONF_NAME],
            data=self.data,
        )

    @callback
    def async_remove(self):
        """Clean up resources or tasks associated with the flow."""
        if self.set_pairing:
            self.set_pairing.cancel()

        if self.ybt:
            self.ybt.shutdown()
            self.ybt = None

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: ConfigEntry,
    ) -> OptionsFlow:
        """Create the options flow."""
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(OptionsFlow):
    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        _LOGGER.debug(f"OptionsFlowHandler_user_input: {user_input}")
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
            
        mac = self.config_entry.data["mac"]
        _LOGGER.debug(f"OptionsFlowHandler_config_entry: {mac}")
        adapters = async_scanner_devices_by_address(
            self.hass, address=mac, connectable=True
        )
        scanners = [ad.scanner for ad in adapters]
        _LOGGER.debug(f"The following adapters found the light:{ {scan.name:scan.source for scan in scanners}}")
        # # adapt3 = _get_manager(self.hass).async_scanner_devices_by_address(
        # #     mac, connectable=False
        # # )
        # # _LOGGER.debug(f"The following adapters found the light:{adapt3}")
        # scanners = _get_manager(self.hass)._connectable_scanners
        # _LOGGER.debug(f"The following adapters available:{scanners}")
        # devs = []
        # for scanner in scanners:
        #     devs += scanner.discovered_devices_and_advertisement_data
        # _LOGGER.debug(f"The adapters had the devices:{devs}")


        adapters_options = [
            {"label": "Automatic", "value": Adapter.AUTO},
            {
                "label": "Local adapters only",
                "value": Adapter.LOCAL,
            },
        ]
        adapters_options += [{"label": scan.name, "value": scan.source} for scan in scanners]
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_SCAN_INTERVAL,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL
                            )
                        },
                    ): cv.positive_float,
                    vol.Required(
                        CONF_ADAPTER,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_ADAPTER, DEFAULT_ADAPTER
                            )
                        },
                    ): selector(
                        {
                            "select": {
                                "options": adapters_options,
                                "custom_value": True,
                            }
                        }
                    ),
                    vol.Required(
                        CONF_STAY_CONNECTED,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_STAY_CONNECTED, DEFAULT_STAY_CONNECTED
                            )
                        },
                    ): cv.boolean,
                    vol.Required(
                        CONF_DEBUG_MODE,
                        description={
                            "suggested_value": self.config_entry.options.get(
                                CONF_DEBUG_MODE, False
                            )
                        },
                    ): cv.boolean,
                }
            ),
        )
