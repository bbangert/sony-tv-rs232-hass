# Sony TV RS-232 for Home Assistant

A [HACS](https://hacs.xyz) custom integration for Sony Bravia TVs controlled
over **RS-232**, built on the
[sony-tv-rs232](https://github.com/home-assistant-libs/sony-tv-rs232) library.

Unlike the core `braviatv` integration (which uses the network API), this
integration talks to the TV's serial port — useful for wall-mounted installs
wired for serial, rack rooms with serial matrices, or sets whose network
control is disabled.

## Installation

### HACS (recommended)

1. In HACS, add `https://github.com/bbangert/sony-tv-rs232-hass` as a
   **custom repository** (category: *Integration*).
2. Install **Sony TV RS-232** and restart Home Assistant.

### Manual

Copy `custom_components/sony_tv_rs232/` into your Home Assistant
`config/custom_components/` directory and restart.

> [!NOTE]
> The [sony-tv-rs232](https://github.com/home-assistant-libs/sony-tv-rs232)
> library has no PyPI release yet, so its package is **vendored** into the
> integration (`custom_components/sony_tv_rs232/sony_tv_rs232/`, currently at
> upstream commit `18b4977`). The only
> requirement Home Assistant installs from PyPI is
> [serialx](https://pypi.org/project/serialx/), the async serial transport.

## Configuration

Add the integration via **Settings → Devices & Services → Add Integration →
Sony TV RS-232**. The only input is the serial port, picked from a dropdown
that lists the host's local serial ports (e.g. `/dev/ttyUSB0`) together with
any ESPHome serial proxy ports (requires Home Assistant 2026.7 or later).

Serial settings are fixed by Sony: 9600 baud 8N1, no flow control. Most
Bravia TVs use a DE-9 male connector and need a **null-modem** cable; some
sets expose RS-232 on a 3.5 mm jack instead.

> [!IMPORTANT]
> Sony TVs only accept **Power ON from standby** if the "Standby Command"
> was enabled while the TV was on. The integration arms this automatically
> on every connect, so turn the TV on once after setup and power control
> will work from then on.

## Entities

One `media_player` (device class `tv`) with:

- **Power** on/off
- **Volume** set/step/mute (0–100 mapped onto 0–1)
- **Source selection** — TV, Video 1–3, Component 1–2, HDMI 1–4, PC
- **Sound mode** — Dynamic / Standard / Custom
- Picture and wide/aspect modes as state attributes

### A note on state

Sony's consumer RS-232 protocol is **set-only**: the TV acknowledges
commands but doesn't report changes made with the IR remote, and most
consumer models ignore status queries (only Pro Bravia / B2B displays answer
them). The entity is therefore an *assumed-state* media player: it reflects
the last acknowledged command, and the integration polls the queryable
functions once a minute for displays that do answer. If the serial link
drops, the integration reconnects automatically with backoff.

## License

MIT
