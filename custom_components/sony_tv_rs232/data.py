"""Custom types for the Sony TV RS-232 integration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry

    from .coordinator import SonyTVCoordinator
    from .sony_tv_rs232 import SonyTV

type SonyTVConfigEntry = ConfigEntry[SonyTVData]


@dataclass
class SonyTVData:
    """Runtime data for a Sony TV config entry."""

    coordinator: SonyTVCoordinator
    tv: SonyTV
