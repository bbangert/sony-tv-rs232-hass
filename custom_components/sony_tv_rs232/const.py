"""Constants for the Sony TV RS-232 integration."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "sony_tv_rs232"
MANUFACTURER = "Sony"

SCAN_INTERVAL_SECONDS = 60

RECONNECT_INITIAL_DELAY = 5.0
RECONNECT_MAX_DELAY = 300.0

# Seconds to wait after the TV reports power-on before the full state query,
# giving the set time to finish booting.
POWER_ON_QUERY_DELAY = 3.0
