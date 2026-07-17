"""Base entity for the Sony TV RS-232 integration."""

from __future__ import annotations

from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .coordinator import SonyTVCoordinator


class SonyTVEntity(CoordinatorEntity[SonyTVCoordinator]):
    """Base class for Sony TV entities."""

    _attr_has_entity_name = True
