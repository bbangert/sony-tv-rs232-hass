"""Constants for the Sony TV RS-232 integration."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "sony_tv_rs232"
MANUFACTURER = "Sony"

SCAN_INTERVAL_SECONDS = 60

RECONNECT_INITIAL_DELAY = 5.0
RECONNECT_MAX_DELAY = 300.0
