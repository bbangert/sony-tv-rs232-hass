"""Main SonyTV controller."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

import serialx

from .const import (
    BAUD_RATE,
    COMMAND_TIMEOUT,
    HEADER_ANSWER,
    INTER_COMMAND_DELAY,
    AdvancedIris,
    AnswerCode,
    CineMotion,
    ClosedCaption,
    Function,
    InputSource,
    Language,
    Mode4_3,
    OffTimer,
    PictureMode,
    PowerState,
    SoundMode,
    WideMode,
)
from .protocol import (
    Answer,
    CommandError,
    PendingCommand,
    byte_to_percent,
    encode_control,
    encode_query,
    parse_answer,
    percent_to_byte,
)
from .state import TVState

_LOGGER = logging.getLogger(__name__)


StateCallback = Callable[[TVState | None], None]


class SonyTV:
    """Async controller for a Sony Bravia TV over RS232.

    The controller speaks the Sony Bravia RS-232C protocol over a
    serial connection (any serialx-supported URL: ``/dev/ttyUSB0``,
    ``socket://host:port``, ``esphome://host/?port_name=TTL``, etc).

    Sony's documented protocol is set-only: every Set command is
    acknowledged by the TV, and ``state`` is updated optimistically
    when an ack arrives. A community-discovered query format
    (``8C 01 ...``) is also supported for the models that honour it;
    callers should expect ``query_*`` methods to time out on sets that
    don't.
    """

    def __init__(self, port: str) -> None:
        self._port = port
        self._reader: asyncio.StreamReader | None = None
        self._writer: serialx.SerialStreamWriter | None = None
        self._read_task: asyncio.Task | None = None
        self._state = TVState()
        self._subscribers: list[StateCallback] = []
        self._pending: list[PendingCommand] = []
        self._write_lock = asyncio.Lock()
        self._connected = False
        self._last_send_at: float = 0.0

    @property
    def state(self) -> TVState:
        """Return a snapshot of the current state."""
        return self._state.copy()

    @property
    def connected(self) -> bool:
        return self._connected

    def subscribe(self, callback: StateCallback) -> Callable[[], None]:
        """Subscribe to state changes; returns an unsubscribe callable."""
        self._subscribers.append(callback)
        return lambda: self._subscribers.remove(callback)

    # -- Connection lifecycle ------------------------------------------------

    async def connect(self) -> None:
        """Open the serial connection.

        Sony's documented protocol does not have a canonical "ping" — the
        TV only replies to commands you actually send. We therefore just
        open the port and assume connectivity; the first command will
        surface any wiring or baud-rate problems via ``TimeoutError``.
        """
        self._reader, self._writer = await serialx.open_serial_connection(
            self._port,
            baudrate=BAUD_RATE,
        )
        self._connected = True
        self._read_task = asyncio.create_task(self._read_loop())
        _LOGGER.info("Connected to Sony TV on %s", self._port)

    async def disconnect(self) -> None:
        """Close the serial connection."""
        await self._teardown()
        _LOGGER.info("Disconnected from Sony TV")

    # -- Status queries (compound) ------------------------------------------

    async def query_state(self) -> None:
        """Query every supported attribute and populate ``state``.

        Each query is issued sequentially. Sets that do not honour
        queries simply time out, and the loop moves on. Many consumer
        Bravia models will skip every entry except power.
        """
        attempts: tuple[tuple[Function, str], ...] = (
            (Function.POWER, "power"),
            (Function.INPUT_SELECT, "input_source"),
            (Function.VOLUME, "volume"),
            (Function.AUDIO_MUTE, "audio_mute"),
            (Function.PICTURE_MODE, "picture_mode"),
            (Function.PICTURE, "picture_level"),
            (Function.BRIGHTNESS, "brightness"),
            (Function.COLOR, "color"),
            (Function.SHARPNESS, "sharpness"),
            (Function.CINE_MOTION, "cine_motion"),
            (Function.ADVANCED_IRIS, "advanced_iris"),
            (Function.SOUND_MODE, "sound_mode"),
            (Function.TREBLE, "treble"),
            (Function.BASS, "bass"),
            (Function.SPEAKER_OFF, "speaker_off"),
            (Function.WIDE_MODE, "wide_mode"),
            (Function.MODE_4_3, "mode_4_3"),
            (Function.OFF_TIMER, "off_timer"),
        )
        for function, _attr in attempts:
            try:
                await self._query(function)
            except (TimeoutError, CommandError) as err:
                _LOGGER.debug(
                    "Skipping query for function 0x%02x: %s", function.value, err
                )

    # -- Power ---------------------------------------------------------------

    async def power_on(self) -> None:
        """Turn the TV on. Requires that Standby Command was previously
        Enabled — otherwise the TV will not accept Power ON while in
        standby. See ``enable_standby_listening``."""
        await self._send_set(Function.POWER, bytes([0x01]))
        self._update_state("power", PowerState.ON)

    async def power_off(self) -> None:
        """Turn the TV off (into standby)."""
        await self._send_set(Function.POWER, bytes([0x00]))
        self._update_state("power", PowerState.OFF)

    async def query_power(self) -> PowerState:
        """Query the TV's power state (community query format)."""
        answer = await self._query(Function.POWER)
        return self._parse_power(answer.data)

    async def enable_standby_listening(self) -> None:
        """Allow the TV to accept Power ON commands while in standby.

        Send this once after the TV is powered on; it persists until
        the TV is reset or the standby command is disabled.
        """
        await self._send_set(Function.STANDBY_COMMAND, bytes([0x01]))

    async def disable_standby_listening(self) -> None:
        """Stop the TV from listening for Power ON while in standby."""
        await self._send_set(Function.STANDBY_COMMAND, bytes([0x00]))

    # -- Input ---------------------------------------------------------------

    async def select_input_source(self, source: InputSource) -> None:
        """Select an input source."""
        await self._send_set(Function.INPUT_SELECT, bytes(source.value))
        self._update_state("input_source", source)

    async def select_next_input_source(self) -> None:
        """Cycle to the next input (same effect as the remote's INPUT key)."""
        await self._send_set(Function.INPUT_SELECT, bytes(InputSource.TOGGLE.value))

    async def query_input_source(self) -> InputSource:
        answer = await self._query(Function.INPUT_SELECT)
        return InputSource(tuple(answer.data))

    # -- Volume / mute -------------------------------------------------------

    async def set_volume(self, percent: int) -> None:
        """Set volume to a 0..100 percent."""
        await self._send_set(
            Function.VOLUME, bytes([0x01, percent_to_byte(percent)])
        )
        self._update_state("volume", percent)

    async def volume_up(self) -> None:
        await self._send_set(Function.VOLUME, bytes([0x00, 0x00]))

    async def volume_down(self) -> None:
        await self._send_set(Function.VOLUME, bytes([0x00, 0x01]))

    async def query_volume(self) -> int:
        answer = await self._query(Function.VOLUME)
        # Reply data echoes the Set shape: [Direct=0x01, value]
        return byte_to_percent(answer.data[1])

    async def mute_on(self) -> None:
        await self._send_set(Function.AUDIO_MUTE, bytes([0x01, 0x01]))
        self._update_state("audio_mute", True)

    async def mute_off(self) -> None:
        await self._send_set(Function.AUDIO_MUTE, bytes([0x01, 0x00]))
        self._update_state("audio_mute", False)

    async def mute_toggle(self) -> None:
        await self._send_set(Function.AUDIO_MUTE, bytes([0x00]))

    async def query_mute(self) -> bool:
        """Query mute. Returns True when audio is muted."""
        answer = await self._query(Function.AUDIO_MUTE)
        # Reply data echoes the Set shape: [Direct=0x01, mute_flag]
        return answer.data[1] == 0x01

    # -- Picture controls (all 0..100) --------------------------------------

    async def set_picture_level(self, percent: int) -> None:
        """Set "Picture" (contrast on most Sony menus) to 0..100."""
        await self._send_set(
            Function.PICTURE, bytes([0x01, percent_to_byte(percent)])
        )
        self._update_state("picture_level", percent)

    async def query_picture_level(self) -> int:
        return byte_to_percent((await self._query(Function.PICTURE)).data[1])

    async def set_brightness(self, percent: int) -> None:
        await self._send_set(
            Function.BRIGHTNESS, bytes([0x01, percent_to_byte(percent)])
        )
        self._update_state("brightness", percent)

    async def query_brightness(self) -> int:
        return byte_to_percent((await self._query(Function.BRIGHTNESS)).data[1])

    async def set_color(self, percent: int) -> None:
        await self._send_set(
            Function.COLOR, bytes([0x01, percent_to_byte(percent)])
        )
        self._update_state("color", percent)

    async def query_color(self) -> int:
        return byte_to_percent((await self._query(Function.COLOR)).data[1])

    async def set_hue(self, red: int, green: int) -> None:
        """Set hue. Sony exposes both red-bias and green-bias on a 0..100 scale."""
        await self._send_set(
            Function.HUE,
            bytes([0x01, 0x00, percent_to_byte(red), 0x01, percent_to_byte(green)]),
        )

    async def set_sharpness(self, percent: int) -> None:
        await self._send_set(
            Function.SHARPNESS, bytes([0x01, percent_to_byte(percent)])
        )
        self._update_state("sharpness", percent)

    async def query_sharpness(self) -> int:
        return byte_to_percent((await self._query(Function.SHARPNESS)).data[1])

    # -- Audio controls ------------------------------------------------------

    async def set_treble(self, percent: int) -> None:
        await self._send_set(
            Function.TREBLE, bytes([0x01, 0x00, percent_to_byte(percent)])
        )
        self._update_state("treble", percent)

    async def set_bass(self, percent: int) -> None:
        await self._send_set(
            Function.BASS, bytes([0x01, 0x00, percent_to_byte(percent)])
        )
        self._update_state("bass", percent)

    async def speaker_on(self) -> None:
        """Re-enable the TV's internal speakers."""
        await self._send_set(Function.SPEAKER_OFF, bytes([0x01, 0x00]))
        self._update_state("speaker_off", False)

    async def speaker_off(self) -> None:
        """Mute the TV's internal speakers (e.g. for external audio)."""
        await self._send_set(Function.SPEAKER_OFF, bytes([0x01, 0x01]))
        self._update_state("speaker_off", True)

    # -- Modes ---------------------------------------------------------------

    async def set_picture_mode(self, mode: PictureMode) -> None:
        await self._send_set(Function.PICTURE_MODE, bytes([0x01, mode.value]))
        self._update_state("picture_mode", mode)

    async def query_picture_mode(self) -> PictureMode:
        return PictureMode((await self._query(Function.PICTURE_MODE)).data[1])

    async def set_sound_mode(self, mode: SoundMode) -> None:
        await self._send_set(Function.SOUND_MODE, bytes([0x01, mode.value]))
        self._update_state("sound_mode", mode)

    async def query_sound_mode(self) -> SoundMode:
        return SoundMode((await self._query(Function.SOUND_MODE)).data[1])

    async def set_cine_motion(self, mode: CineMotion) -> None:
        await self._send_set(Function.CINE_MOTION, bytes([mode.value]))
        self._update_state("cine_motion", mode)

    async def set_advanced_iris(self, mode: AdvancedIris) -> None:
        """SXRD models only."""
        await self._send_set(Function.ADVANCED_IRIS, bytes([mode.value]))
        self._update_state("advanced_iris", mode)

    async def set_wide_mode(self, mode: WideMode) -> None:
        await self._send_set(Function.WIDE_MODE, bytes([0x01, mode.value]))
        self._update_state("wide_mode", mode)

    async def query_wide_mode(self) -> WideMode:
        return WideMode((await self._query(Function.WIDE_MODE)).data[1])

    async def set_4_3_mode(self, mode: Mode4_3) -> None:
        await self._send_set(Function.MODE_4_3, bytes([0x01, mode.value]))
        self._update_state("mode_4_3", mode)

    # -- Misc ---------------------------------------------------------------

    async def toggle_display(self) -> None:
        """Toggle the on-screen info display (same as the remote's "info" key)."""
        await self._send_set(Function.DISPLAY, bytes([0x00]))

    async def set_off_timer(self, timer: OffTimer) -> None:
        """Set the sleep timer."""
        await self._send_set(Function.OFF_TIMER, bytes([0x01, timer.value]))
        self._update_state("off_timer", timer)

    async def set_language(self, language: Language) -> None:
        """Set the menu language."""
        await self._send_set(Function.LANGUAGE, bytes([0x00]) + language.value)
        self._update_state("language", language)

    async def set_closed_caption(self, caption: ClosedCaption) -> None:
        await self._send_set(Function.CLOSED_CAPTION, bytes(caption.value))

    # -- Internals ----------------------------------------------------------

    async def _send_set(self, function: Function, data: bytes) -> Answer:
        return await self._send_and_wait(
            function, encode_control(function.value, data), is_query=False
        )

    async def _query(self, function: Function) -> Answer:
        return await self._send_and_wait(
            function, encode_query(function.value), is_query=True
        )

    async def _send_and_wait(
        self,
        function: Function,
        packet: bytes,
        is_query: bool,
        timeout: float = COMMAND_TIMEOUT,
    ) -> Answer:
        if self._writer is None:
            raise ConnectionError("Not connected")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Answer] = loop.create_future()
        pending = PendingCommand(
            function=function.value,
            is_query=is_query,
            future=future,
        )

        try:
            async with self._write_lock:
                # Sony spec mandates >= 500 ms between commands
                wait = INTER_COMMAND_DELAY - (time.monotonic() - self._last_send_at)
                if wait > 0:
                    await asyncio.sleep(wait)

                self._pending.append(pending)
                _LOGGER.debug("Sending: %s", packet.hex(" "))
                try:
                    self._writer.write(packet)
                    await self._writer.drain()
                except Exception:
                    _LOGGER.exception("Error writing to serial port")
                    self._pending.remove(pending)
                    await self._teardown()
                    raise
                self._last_send_at = time.monotonic()

            answer = await asyncio.wait_for(future, timeout=timeout)
        finally:
            if pending in self._pending:
                self._pending.remove(pending)

        answer.raise_for_status(function.value)
        return answer

    async def _teardown(self) -> None:
        if not self._connected:
            return
        self._connected = False

        current = asyncio.current_task()
        if self._read_task is not None and self._read_task is not current:
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass
        self._read_task = None

        if self._writer is not None:
            self._writer.close()
            try:
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

        for pending in self._pending:
            if not pending.future.done():
                pending.future.set_exception(ConnectionError("Connection lost"))
        self._pending.clear()

        self._notify_subscribers()

    async def _read_loop(self) -> None:
        assert self._reader is not None
        while self._connected:
            try:
                header = await self._reader.readexactly(1)
            except asyncio.IncompleteReadError:
                if self._connected:
                    _LOGGER.warning("Serial connection closed")
                    await self._teardown()
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                if not self._connected:
                    return
                _LOGGER.exception("Error reading from serial port")
                await self._teardown()
                return

            if header[0] != HEADER_ANSWER:
                _LOGGER.debug("Discarding stray byte 0x%02x", header[0])
                continue

            # Two response shapes are possible:
            #   Short:  [0x70][status][cs]                  (3 bytes total)
            #   Long:   [0x70][status][size][data...][cs]   (3 + size bytes)
            # The Pro Bravia spec says Set acks are short and query replies
            # are long, but several Sony Bravia models reply in long form for
            # *everything* (echoing the value back). Distinguish by checksum:
            # in a short packet, byte 2 IS the checksum, so it must equal
            # (HEADER_ANSWER + status) & 0xFF. In a long packet, byte 2 is
            # the size — typically 2 or 3, far from the short-form checksum.
            try:
                tail = await self._reader.readexactly(2)
            except asyncio.IncompleteReadError:
                if self._connected:
                    await self._teardown()
                return

            short_cs = (HEADER_ANSWER + tail[0]) & 0xFF
            if tail[1] == short_cs:
                packet = header + tail
            else:
                size = tail[1]
                try:
                    rest = await self._reader.readexactly(size)
                except asyncio.IncompleteReadError:
                    if self._connected:
                        await self._teardown()
                    return
                packet = header + tail + rest

            self._handle_packet(packet)

    def _handle_packet(self, packet: bytes) -> None:
        _LOGGER.debug("Received: %s", packet.hex(" "))
        try:
            answer = parse_answer(packet)
        except Exception:
            # Garbage on the line (stale buffer, UART glitch, unsupported
            # response format) — log it and keep listening. The pending
            # command times out cleanly if no valid reply ever arrives.
            _LOGGER.warning("Discarding malformed answer: %s", packet.hex(" "))
            return

        if not self._pending:
            _LOGGER.debug("Unsolicited answer dropped")
            return

        pending = self._pending.pop(0)
        if pending.future.done():
            return
        pending.future.set_result(answer)
        if answer.ok and answer.data:
            self._update_state_from_query(pending.function, answer)

    # -- State updates ------------------------------------------------------

    def _update_state(self, attr: str, value: object) -> None:
        if getattr(self._state, attr) == value:
            return
        setattr(self._state, attr, value)
        self._notify_subscribers()

    def _update_state_from_query(self, function: int, answer: Answer) -> None:
        """Update ``self._state`` from a successful query reply.

        Reply data shape mirrors the corresponding Set command. Functions
        whose Set begins with the Direct marker ``0x01`` echo it back, so
        the actual value is at ``data[1]``; functions like Power and Input
        carry the value(s) directly at ``data[0]``.
        """
        data = answer.data
        try:
            if function == Function.POWER.value:
                self._update_state("power", self._parse_power(data))
            elif function == Function.INPUT_SELECT.value:
                self._update_state("input_source", InputSource(tuple(data)))
            elif function == Function.VOLUME.value:
                self._update_state("volume", byte_to_percent(data[1]))
            elif function == Function.AUDIO_MUTE.value:
                self._update_state("audio_mute", data[1] == 0x01)
            elif function == Function.PICTURE_MODE.value:
                self._update_state("picture_mode", PictureMode(data[1]))
            elif function == Function.PICTURE.value:
                self._update_state("picture_level", byte_to_percent(data[1]))
            elif function == Function.BRIGHTNESS.value:
                self._update_state("brightness", byte_to_percent(data[1]))
            elif function == Function.COLOR.value:
                self._update_state("color", byte_to_percent(data[1]))
            elif function == Function.SHARPNESS.value:
                self._update_state("sharpness", byte_to_percent(data[1]))
            elif function == Function.CINE_MOTION.value:
                # Cine Motion Set has no Direct marker
                self._update_state("cine_motion", CineMotion(data[0]))
            elif function == Function.ADVANCED_IRIS.value:
                self._update_state("advanced_iris", AdvancedIris(data[0]))
            elif function == Function.SOUND_MODE.value:
                self._update_state("sound_mode", SoundMode(data[1]))
            elif function == Function.TREBLE.value:
                # Treble Set is [0x01, plus/minus, value]
                self._update_state("treble", byte_to_percent(data[2]))
            elif function == Function.BASS.value:
                self._update_state("bass", byte_to_percent(data[2]))
            elif function == Function.SPEAKER_OFF.value:
                self._update_state("speaker_off", data[1] == 0x01)
            elif function == Function.WIDE_MODE.value:
                self._update_state("wide_mode", WideMode(data[1]))
            elif function == Function.MODE_4_3.value:
                self._update_state("mode_4_3", Mode4_3(data[1]))
            elif function == Function.OFF_TIMER.value:
                self._update_state("off_timer", OffTimer(data[1]))
        except (ValueError, KeyError) as err:
            _LOGGER.debug(
                "Could not parse query data %s for function 0x%02x: %s",
                answer.data.hex(" "),
                function,
                err,
            )

    @staticmethod
    def _parse_power(data: bytes) -> PowerState:
        if data == b"\x00":
            return PowerState.OFF
        if data == b"\x01":
            return PowerState.ON
        raise ValueError(f"Unknown power data: {data!r}")

    def _notify_subscribers(self) -> None:
        snapshot = self._state.copy() if self._connected else None
        for callback in list(self._subscribers):
            try:
                callback(snapshot)
            except Exception:
                _LOGGER.exception("Error in state callback %s", callback)
