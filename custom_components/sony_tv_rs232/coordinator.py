"""DataUpdateCoordinator wrapping a Sony TV serial connection.

Sony's RS-232 protocol emits no unsolicited state reports, so the coordinator
polls. Consumer Bravia TVs are set-only and ignore query packets — every poll
attempt is best-effort, and state otherwise updates optimistically when set
commands are acknowledged (the library notifies subscribers on both paths).

Reconnect is owned by the vendored serialkit runtime, not this coordinator: on
a dropped link the library fails in-flight requests, notifies subscribers with
``None``, backs off, reopens, re-runs the connect handshake, and notifies
again. The coordinator only reflects those notifications into HA.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from datetime import timedelta
from typing import TYPE_CHECKING

from homeassistant.core import callback
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DOMAIN,
    LOGGER,
    POWER_ON_QUERY_DELAY,
    SCAN_INTERVAL_SECONDS,
)
from .sony_tv_rs232 import (
    CommandTimeoutError,
    ConnectionLostError,
    PowerState,
    ProtocolError,
    SerialKitError,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant

    from .data import SonyTVConfigEntry
    from .sony_tv_rs232 import SonyTV, TVState


class SonyTVCoordinator(DataUpdateCoordinator["TVState"]):
    """Poll the TV for state; serialkit handles the serial link and reconnect."""

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
        self._power_refresh_task: asyncio.Task | None = None
        self._last_power: bool | None = None
        # on_connect() already ran a full query during setup, so the first
        # poll right after would just repeat 4 of those queries; skip it once.
        self._skip_next_poll = False

    async def _async_setup(self) -> None:
        """Open the serial port and subscribe to state changes.

        The library's ``connect()`` runs the handshake (arm standby listening,
        probe query support, full query if the TV is on); nothing else to do.
        """
        try:
            await self.tv.connect()
        except (SerialKitError, OSError) as err:
            raise UpdateFailed(f"Cannot open serial port to Sony TV: {err}") from err
        self._last_power = _power_is_on(self.tv.state)
        self._unsubscribe = self.tv.subscribe(self._handle_state)
        self._skip_next_poll = True

    async def _async_update_data(self) -> TVState:
        """Poll the queryable functions; consumer sets ignore them all."""
        if not self.tv.connected:
            raise UpdateFailed("Not connected to the TV")
        if self._skip_next_poll:
            # on_connect() just populated state during setup — don't re-query.
            self._skip_next_poll = False
            return self.tv.state.copy()
        if self.tv.supports_queries is False:
            # A set-only TV: polling would just burn a serialized timeout per
            # function. Optimistic state from command acks is all we get.
            return self.tv.state.copy()
        for query in (
            self.tv.query_power,
            self.tv.query_input_source,
            self.tv.query_volume,
            self.tv.query_mute,
        ):
            try:
                await query()
            except (CommandTimeoutError, ProtocolError):
                continue
        return self.tv.state.copy()

    async def async_shutdown(self) -> None:
        """Stop polling and close the serial connection."""
        if self._power_refresh_task is not None:
            self._power_refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._power_refresh_task
            self._power_refresh_task = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
        await self.tv.disconnect()
        await super().async_shutdown()

    @callback
    def _handle_state(self, state: TVState | None) -> None:
        """Handle a state notification from the library.

        ``None`` means the serial link dropped; serialkit reconnects on its
        own, so we only surface the outage — no reconnect is scheduled here.
        """
        if state is None:
            LOGGER.warning("Connection to Sony TV lost; serialkit will reconnect")
            self.async_set_update_error(ConnectionLostError("Connection to TV lost"))
            return
        if state.power is not None:
            power_on = state.power is PowerState.ON
            turned_on = power_on and self._last_power is False
            self._last_power = power_on
            if turned_on and self.tv.supports_queries:
                # Repopulate everything once the set has booted -- only
                # worthwhile on displays that actually answer queries.
                self._schedule_power_refresh()
        self.async_set_updated_data(state)

    @callback
    def _schedule_power_refresh(self) -> None:
        if self._power_refresh_task is not None and not self._power_refresh_task.done():
            return
        self._power_refresh_task = self.config_entry.async_create_background_task(
            self.hass,
            self._power_on_refresh(),
            name=f"{DOMAIN} power-on refresh",
        )

    async def _power_on_refresh(self) -> None:
        """Re-query the full state after the TV powers on."""
        await asyncio.sleep(POWER_ON_QUERY_DELAY)
        try:
            await self.tv.query_state()
        except (CommandTimeoutError, ProtocolError) as err:
            LOGGER.debug("Power-on refresh query failed: %s", err)
        self.async_set_updated_data(self.tv.state.copy())


def _power_is_on(state: TVState | None) -> bool | None:
    if state is None or state.power is None:
        return None
    return state.power is PowerState.ON
