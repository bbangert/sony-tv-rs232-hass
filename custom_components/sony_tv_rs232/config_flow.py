"""Config flow for the Sony TV RS-232 integration."""

from __future__ import annotations

import asyncio
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PORT
from homeassistant.helpers.selector import SerialPortSelector

from .const import DOMAIN, LOGGER
from .sony_tv_rs232 import SerialKitError, SonyTV

# Bound the port open so an unreachable socket:// / esphome:// URL surfaces as
# cannot_connect instead of hanging the flow. connect() opens the port and runs
# the handshake, which is paced; the handshake's own query timeouts are small.
_CONNECT_TIMEOUT = 15.0

# SerialPortSelector lists the host's serial ports plus remote ports from
# ESPHome serial proxies; requires "usb" in the manifest dependencies.
STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_PORT): SerialPortSelector(),
    },
)


class SonyTVConfigFlow(ConfigFlow, domain=DOMAIN):
    """Ask for the serial port the TV is wired to.

    Sony's protocol has no ping and consumer Bravia TVs ignore query
    packets entirely, so the flow can only verify that the port opens; a
    wiring problem surfaces later as unacknowledged commands.
    """

    VERSION = 1

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}
        if user_input is not None:
            port = user_input[CONF_PORT].strip()
            self._async_abort_entries_match({CONF_PORT: port})
            tv = SonyTV(port)
            try:
                async with asyncio.timeout(_CONNECT_TIMEOUT):
                    await tv.connect()
            except (SerialKitError, OSError, ValueError, TimeoutError) as err:
                LOGGER.error("Error opening %s: %s", port, err)
                errors["base"] = "cannot_connect"
            else:
                # connect() opened the port and ran the handshake (which
                # probes with a power query). Consumer sets ignore queries, so
                # reaching here simply means the port is usable.
                await tv.disconnect()
                return self.async_create_entry(
                    title="Sony TV",
                    data={CONF_PORT: port},
                )

        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_SCHEMA, user_input
            ),
            errors=errors,
        )
