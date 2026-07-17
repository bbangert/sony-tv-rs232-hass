"""Media player platform for the Sony TV RS-232 integration.

Sony's consumer RS-232 protocol is set-only: the TV acknowledges commands
but does not report state changes made with the IR remote, and most models
ignore query packets. The entity is therefore an assumed-state media
player — state tracks acknowledged commands (and query replies on Pro
Bravia displays that answer them).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.media_player import (
    MediaPlayerDeviceClass,
    MediaPlayerEntity,
    MediaPlayerEntityFeature,
    MediaPlayerState,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.device_registry import DeviceInfo

from .const import DOMAIN, MANUFACTURER
from .entity import SonyTVEntity
from .sony_tv_rs232 import (
    CommandError,
    InputSource,
    PowerState,
    ProtocolError,
    SoundMode,
)

if TYPE_CHECKING:
    from collections.abc import Coroutine

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddEntitiesCallback

    from .coordinator import SonyTVCoordinator
    from .data import SonyTVConfigEntry

SOURCE_NAMES: dict[InputSource, str] = {
    InputSource.TV: "TV",
    InputSource.VIDEO1: "Video 1",
    InputSource.VIDEO2: "Video 2",
    InputSource.VIDEO3: "Video 3",
    InputSource.COMPONENT1: "Component 1",
    InputSource.COMPONENT2: "Component 2",
    InputSource.HDMI1: "HDMI 1",
    InputSource.HDMI2: "HDMI 2",
    InputSource.HDMI3: "HDMI 3",
    InputSource.HDMI4: "HDMI 4",
    InputSource.PC: "PC",
}

SOUND_MODE_NAMES: dict[SoundMode, str] = {mode: mode.name.title() for mode in SoundMode}


async def async_setup_entry(
    hass: HomeAssistant,  # noqa: ARG001
    entry: SonyTVConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the media player entity for the TV."""
    async_add_entities([SonyTVMediaPlayer(entry.runtime_data.coordinator, entry)])


class SonyTVMediaPlayer(SonyTVEntity, MediaPlayerEntity):
    """A Sony Bravia TV controlled over RS-232."""

    _attr_device_class = MediaPlayerDeviceClass.TV
    _attr_assumed_state = True
    _attr_name = None
    _attr_supported_features = (
        MediaPlayerEntityFeature.TURN_ON
        | MediaPlayerEntityFeature.TURN_OFF
        | MediaPlayerEntityFeature.VOLUME_SET
        | MediaPlayerEntityFeature.VOLUME_STEP
        | MediaPlayerEntityFeature.VOLUME_MUTE
        | MediaPlayerEntityFeature.SELECT_SOURCE
        | MediaPlayerEntityFeature.SELECT_SOUND_MODE
    )

    def __init__(
        self,
        coordinator: SonyTVCoordinator,
        entry: SonyTVConfigEntry,
    ) -> None:
        """Set up the unique id and device."""
        super().__init__(coordinator)
        self._attr_source_list = list(SOURCE_NAMES.values())
        self._attr_sound_mode_list = list(SOUND_MODE_NAMES.values())
        self._attr_unique_id = entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            manufacturer=MANUFACTURER,
            name=entry.title,
        )

    @property
    def state(self) -> MediaPlayerState | None:
        """Return on/off from the last known power state."""
        power = self.coordinator.data.power
        if power is None:
            return None
        return MediaPlayerState.ON if power is PowerState.ON else MediaPlayerState.OFF

    @property
    def volume_level(self) -> float | None:
        """Map the TV's 0-100 volume onto 0..1."""
        volume = self.coordinator.data.volume
        return volume / 100 if volume is not None else None

    @property
    def is_volume_muted(self) -> bool | None:
        """Return the last known mute state."""
        return self.coordinator.data.audio_mute

    @property
    def source(self) -> str | None:
        """Return the name of the last known input source."""
        current = self.coordinator.data.input_source
        if current is None:
            return None
        return SOURCE_NAMES.get(current, current.name.title())

    @property
    def sound_mode(self) -> str | None:
        """Return the last known sound mode."""
        mode = self.coordinator.data.sound_mode
        return SOUND_MODE_NAMES[mode] if mode is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Expose picture and aspect modes."""
        data = self.coordinator.data
        attrs: dict[str, Any] = {}
        if data.picture_mode is not None:
            attrs["picture_mode"] = data.picture_mode.name.lower()
        if data.wide_mode is not None:
            attrs["wide_mode"] = data.wide_mode.name.lower()
        return attrs

    async def _send(self, command: Coroutine[Any, Any, Any]) -> None:
        """Await a TV command, mapping library errors to HA errors."""
        try:
            await command
        except (
            CommandError,
            ProtocolError,
            TimeoutError,
            ConnectionError,
            OSError,
        ) as err:
            raise HomeAssistantError(f"Command to Sony TV failed: {err}") from err

    async def async_turn_on(self) -> None:
        """Turn the TV on (requires standby listening to have been armed)."""
        await self._send(self.coordinator.tv.power_on())

    async def async_turn_off(self) -> None:
        """Turn the TV off (standby)."""
        await self._send(self.coordinator.tv.power_off())

    async def async_set_volume_level(self, volume: float) -> None:
        """Set the TV volume."""
        await self._send(self.coordinator.tv.set_volume(round(volume * 100)))

    async def async_volume_up(self) -> None:
        """Step the volume up."""
        await self._send(self.coordinator.tv.volume_up())

    async def async_volume_down(self) -> None:
        """Step the volume down."""
        await self._send(self.coordinator.tv.volume_down())

    async def async_mute_volume(self, mute: bool) -> None:
        """Mute or unmute the TV."""
        tv = self.coordinator.tv
        await self._send(tv.mute_on() if mute else tv.mute_off())

    async def async_select_source(self, source: str) -> None:
        """Select an input source by name."""
        for input_source, name in SOURCE_NAMES.items():
            if name == source:
                await self._send(self.coordinator.tv.select_input_source(input_source))
                return
        raise HomeAssistantError(f"Unknown source: {source}")

    async def async_select_sound_mode(self, sound_mode: str) -> None:
        """Select a sound mode by name."""
        for mode, name in SOUND_MODE_NAMES.items():
            if name == sound_mode:
                await self._send(self.coordinator.tv.set_sound_mode(mode))
                return
        raise HomeAssistantError(f"Unknown sound mode: {sound_mode}")
