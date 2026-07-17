"""DataUpdateCoordinator wrapping a Sony TV serial connection.

Sony's RS-232 protocol emits no unsolicited state reports, so the
coordinator polls. Consumer Bravia TVs are set-only and ignore query
packets — every poll attempt is best-effort, and state otherwise updates
optimistically when set commands are acknowledged (the library notifies
subscribers on both paths).
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    LOGGER,
    RECONNECT_INITIAL_DELAY,
    RECONNECT_MAX_DELAY,
    SCAN_INTERVAL_SECONDS,
)
from .sony_tv_rs232 import CommandError

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

    from .data import SonyTVConfigEntry
    from .sony_tv_rs232 import SonyTV, TVState


class SonyTVCoordinator(DataUpdateCoordinator["TVState"]):
    """Poll the TV for state; reconnect when the serial link drops."""

    config_entry: SonyTVConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: SonyTVConfigEntry,
        tv: SonyTV,
    ) -> None:
        """Initialize the coordinator around an unconnected TV."""
        super().__init__(
            hass,
            LOGGER,
            config_entry=entry,
            name=f"{DOMAIN} {entry.title}",
            update_interval=timedelta(seconds=SCAN_INTERVAL_SECONDS),
        )
        self.tv = tv
        self._unsubscribe: Callable[[], None] | None = None
        self._reconnect_task: asyncio.Task | None = None

    async def _async_setup(self) -> None:
        """Open the serial port and subscribe to state changes."""
        try:
            await self.tv.connect()
        except (ConnectionError, TimeoutError, OSError) as err:
            raise UpdateFailed(f"Cannot open serial port to Sony TV: {err}") from err
        await self._arm_standby_listening()
        self._unsubscribe = self.tv.subscribe(self._handle_state)

    async def _async_update_data(self) -> TVState:
        """Poll the queryable functions; consumer sets ignore them all."""
        if not self.tv.connected:
            raise UpdateFailed("Not connected to the TV")
        for query in (
            self.tv.query_power,
            self.tv.query_input_source,
            self.tv.query_volume,
            self.tv.query_mute,
        ):
            try:
                await query()
            except TimeoutError, CommandError:
                continue
        return self.tv.state

    async def async_shutdown(self) -> None:
        """Stop reconnecting and close the serial connection."""
        if self._reconnect_task is not None:
            self._reconnect_task.cancel()
            self._reconnect_task = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        await self.tv.disconnect()
        await super().async_shutdown()

    async def _arm_standby_listening(self) -> None:
        """Enable Sony's Standby Command so Power ON works from standby.

        Only takes effect while the TV is on; harmless to retry after
        reconnects.
        """
        try:
            await self.tv.enable_standby_listening()
        except (TimeoutError, CommandError) as err:
            LOGGER.debug("Could not enable standby listening: %s", err)

    @callback
    def _handle_state(self, state: TVState | None) -> None:
        """Handle a state notification from the library."""
        if state is None:
            LOGGER.warning("Connection to Sony TV lost; will reconnect")
            self.async_set_update_error(ConnectionError("Connection to TV lost"))
            self._schedule_reconnect()
            return
        self.async_set_updated_data(state)

    @callback
    def _schedule_reconnect(self) -> None:
        if self._reconnect_task is not None and not self._reconnect_task.done():
            return
        self._reconnect_task = self.config_entry.async_create_background_task(
            self.hass,
            self._reconnect(),
            name=f"{DOMAIN} reconnect",
        )

    async def _reconnect(self) -> None:
        delay = RECONNECT_INITIAL_DELAY
        while True:
            await asyncio.sleep(delay)
            try:
                await self.tv.connect()
            except (ConnectionError, TimeoutError, OSError) as err:
                LOGGER.debug("Reconnect failed (%s); retrying in %.0f s", err, delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
                continue
            LOGGER.info("Reconnected to Sony TV")
            await self._arm_standby_listening()
            self.async_set_updated_data(self.tv.state)
            return
