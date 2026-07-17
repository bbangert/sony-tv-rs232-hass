"""The Sony TV RS-232 integration.

Integrates Sony Bravia TVs controlled over RS-232 into Home Assistant,
using the vendored ``sony-tv-rs232`` library.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.const import CONF_PORT, Platform

from .coordinator import SonyTVCoordinator
from .data import SonyTVData
from .sony_tv_rs232 import SonyTV

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .data import SonyTVConfigEntry

PLATFORMS: list[Platform] = [Platform.MEDIA_PLAYER]


async def async_setup_entry(hass: HomeAssistant, entry: SonyTVConfigEntry) -> bool:
    """Set up a Sony TV from a config entry."""
    tv = SonyTV(entry.data[CONF_PORT])
    coordinator = SonyTVCoordinator(hass, entry, tv)

    await coordinator.async_config_entry_first_refresh()

    entry.runtime_data = SonyTVData(coordinator=coordinator, tv=tv)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SonyTVConfigEntry) -> bool:
    """Unload a config entry (the coordinator closes the serial connection)."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
