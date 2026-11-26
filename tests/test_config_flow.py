"""Tests for the yeelight_bt config flow."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_MAC, CONF_NAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.yeelight_bt.const import DOMAIN

from .conftest import ADDRESS


def _service_info(name: str = "XMCTD_ABCD", address: str = ADDRESS) -> MagicMock:
    info = MagicMock()
    info.name = name
    info.address = address
    return info


async def test_user_flow_manual_mac(hass: HomeAssistant) -> None:
    with (
        patch(
            "custom_components.yeelight_bt.config_flow.async_discovered_service_info",
            return_value=[],
        ),
        patch("custom_components.yeelight_bt.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        assert result["type"] is FlowResultType.FORM
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Bedroom", CONF_MAC: "nope"}
        )
        assert result["errors"] == {CONF_MAC: "invalid_mac"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Bedroom", CONF_MAC: "f8-24-41-e6-3e-39"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_NAME: "Bedroom", CONF_MAC: ADDRESS}
    assert result["result"].unique_id == ADDRESS.lower()


async def test_user_flow_lists_discovered_lamps(hass: HomeAssistant) -> None:
    with patch(
        "custom_components.yeelight_bt.config_flow.async_discovered_service_info",
        return_value=[_service_info(), _service_info("SomethingElse", "00:11:22:33:44:55")],
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
    selector = result["data_schema"].schema[CONF_MAC]
    values = [o["value"] for o in selector.config["options"]]
    assert values == [ADDRESS]


async def test_bluetooth_discovery(hass: HomeAssistant) -> None:
    with patch("custom_components.yeelight_bt.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_BLUETOOTH},
            data=_service_info(),
        )
        assert result["type"] is FlowResultType.FORM
        assert result["step_id"] == "bluetooth_confirm"
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_NAME: "Bedside"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_NAME: "Bedside", CONF_MAC: ADDRESS}

    # Discovering the same lamp again aborts.
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_BLUETOOTH}, data=_service_info()
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"
