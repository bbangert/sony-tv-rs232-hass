"""Constants for the Sony TV RS-232 integration."""

from logging import Logger, getLogger

LOGGER: Logger = getLogger(__package__)

DOMAIN = "sony_tv_rs232"
MANUFACTURER = "Sony"

SCAN_INTERVAL_SECONDS = 60

# Reconnect/backoff is owned by the vendored serialkit runtime, not this
# integration, so no reconnect-delay constants live here.

# Seconds to wait after the TV reports power-on before the full state query,
# giving the set time to finish booting.
POWER_ON_QUERY_DELAY = 3.0
