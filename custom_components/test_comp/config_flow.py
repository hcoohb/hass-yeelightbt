from __future__ import annotations

import logging
from typing import Any
import asyncio

from homeassistant.config_entries import ConfigFlow
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult

DOMAIN = "test_comp"


_LOGGER = logging.getLogger(__name__)


class TempCompConfigFlow(ConfigFlow, domain=DOMAIN):  # type: ignore
    VERSION = 1
    task_one = None
    task_two = None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle a flow initialized by the user."""
        _LOGGER.info("async_step_user: %s", user_input)

        if user_input is None:
            return self.async_show_form(step_id="user")
        return await self.async_step_progress()

    async def async_step_progress(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Displaying progress for two tasks"""
        _LOGGER.info("async_step_progress")
        if not self.task_one:
            task = asyncio.sleep(10)
            _LOGGER.info("scheduling task1")
            self.task_one = self.hass.async_create_task(self._async_do_task(task))
            return self.async_show_progress(
                step_id="progress",
                progress_action="task_one",
            )
        try:
            await self.task_one
        except asyncio.TimeoutError:
            self.task_one = None
            return self.async_show_progress_done(next_step_id="task_timeout")
        _LOGGER.info("async_step_progress - task1 done")
        self.task_one = None
        return self.async_show_progress_done(next_step_id="progress2")

        
    async def async_step_progress2(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Displaying progress for two tasks"""
        _LOGGER.info("async_step_progress2")
        if not self.task_two:
            task = asyncio.sleep(5)
            _LOGGER.info("scheduling task2")
            self.task_two = self.hass.async_create_task(self._async_do_task(task))
            return self.async_show_progress(
                step_id="progress2",
                progress_action="task_two",
            )
        try:
            await self.task_two
        except asyncio.TimeoutError:
            self.task_two = None
            return self.async_show_progress_done(next_step_id="task_timeout")
        _LOGGER.info("async_step_progress - task2 done")
        self.task_two = None
        return self.async_show_progress_done(next_step_id="finish")


    async def _async_do_task(self, task):
        _LOGGER.info("task pre")
        await task  # A task that take some time to complete.
        _LOGGER.info("task done")
        # Ensure we go back to the flow
        self.hass.async_create_task(
            self.hass.config_entries.flow.async_configure(flow_id=self.flow_id)
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        _LOGGER.info("async_step_finish")
        return self.async_create_entry(
            title="Test_Comp",
            data={},
        )

        
    async def async_step_task_timeout(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Inform the user that the device never entered pairing mode."""
        if user_input is not None:
            return await self.async_step_progress()

        self._set_confirm_only()
        return self.async_show_form(step_id="pairing_timeout")

    @callback
    def async_remove(self):
        """Clean up resources or tasks associated with the flow."""
        _LOGGER.info("async_remove")
        if self.task_one:
            self.task_one.cancel()

        if self.task_two:
            self.task_two.cancel()
