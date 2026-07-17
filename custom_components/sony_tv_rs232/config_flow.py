"""Config flow for the Sony TV RS-232 integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_PORT
from homeassistant.helpers.selector import SerialPortSelector

from .const import DOMAIN, LOGGER
from .sony_tv_rs232 import CommandError, SonyTV

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
                await tv.connect()
            except (ConnectionError, TimeoutError, OSError, ValueError) as err:
                LOGGER.error("Error opening %s: %s", port, err)
                errors["base"] = "cannot_connect"
            else:
                try:
                    # Pro Bravia displays answer queries; consumer sets
                    # don't, so a timeout here is not an error.
                    await tv.query_power()
                except TimeoutError, CommandError:
                    LOGGER.debug("TV on %s did not answer a power query", port)
                finally:
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
