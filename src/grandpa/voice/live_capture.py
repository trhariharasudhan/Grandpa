"""A microphone stream held open, so the first word is not lost.

The hold path opens a PortAudio stream only after the key press is noticed.
Measured on this machine: selecting the device takes 0.8ms, negotiating the
rate 0.2ms, and opening and starting the stream **245ms on average and up to
361ms**. With the 30ms poll interval on top, up to 392ms of speech after the key
goes down was never recorded. The 0.3s pre-roll inside ``MicrophoneCapture``
cannot help: it buffers chunks the stream already produced, and before the
stream starts there are none.

A quarter to four-tenths of a second is one to two syllables. It did not show up
in three rounds of word-error measurement because reading prepared phrases means
pressing, settling, and then reading -- the protocol hid it.

So this holds the stream open from the moment the bubble starts, keeps the last
300ms in memory, and on key-down begins the utterance with that tail. The deaf
window becomes the poll interval alone.

**Three properties this is built to have, each tested:**

* the pre-roll never reaches disk. It is a bounded deque of PCM chunks in RAM,
  capped at :data:`PREROLL_SECONDS`, and nothing in this module opens a file,
  writes a path, or logs audio. A test reads this file as a syntax tree and
  fails on any file-writing call.
* it can be turned off -- ``--no-live-mic`` or ``voice.live_microphone = false``
  -- and with it off nothing here is constructed, so behaviour returns to
  open-on-demand with the deaf window and all.
* a device that disappears mid-session is a live failure, not a startup one.
  The reader thread marks the stream dead and records why; the next hold falls
  back to opening on demand, so unplugging a headset costs the words in flight
  and not the session.

``MicrophoneCapture`` is deliberately untouched. Every other voice surface keeps
the open-on-demand path it has always had, and this is used by the bubble alone.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable

from grandpa.voice.device_manager import MicrophoneDeviceManager, import_sounddevice
from grandpa.voice.microphone import (
    CapturedAudio,
    _downmix_pcm16,
    _negotiate_capture_settings,
    _normalize_pcm16_audio,
    _wav_bytes,
    calculate_pcm16_rms,
)

#: How much speech to keep in memory ahead of the key press. 300ms covers the
#: measured worst-case open latency of 361ms less the poll interval, and is one
#: to two syllables -- enough for the word that used to disappear.
PREROLL_SECONDS = 0.30

#: The reader's chunk, matching the capture path's own 0.1s so the level meter
#: and the waveform see the same cadence.
CHUNK_SECONDS = 0.1

#: A hard ceiling on what is held, whatever the chunk size works out to. The
#: buffer is bounded twice on purpose: once by seconds and once by count, so a
#: device that reports an odd rate cannot grow it without limit.
MAX_PREROLL_CHUNKS = 8


@dataclass
class LiveMicrophone:
    """A stream held open, with a bounded RAM pre-roll.

    Satisfies the same ``capture(stop_event=...)`` contract
    ``PushToTalkSession`` already calls, so it drops into the controller's
    ``capture`` slot without the hold path changing.
    """

    device: int | None = None
    device_name: str | None = None
    sample_rate: int = 16_000
    chunk_seconds: float = CHUNK_SECONDS
    preroll_seconds: float = PREROLL_SECONDS
    #: Called with each chunk's RMS, as MicrophoneCapture's on_level is.
    on_level: Callable[[float], None] | None = None
    sounddevice: Any = None
    device_manager: Any = None

    last_error: str = ""
    last_warning: str = ""
    last_device: Any = None
    #: How many pre-roll chunks the last utterance began with. Carried here
    #: rather than on CapturedAudio, which has no field for it, so a test can
    #: prove the pre-roll was actually used and not merely held.
    last_preroll_chunks: int = 0

    _stream: Any = field(default=None, init=False)
    _reader: Any = field(default=None, init=False)
    _stop_reader: Any = field(default_factory=threading.Event, init=False)
    #: The pre-roll. RAM only, bounded, newest last.
    _preroll: Any = field(default=None, init=False)
    #: Chunks of the utterance in progress, or None when not recording.
    _recording: Any = field(default=None, init=False)
    _lock: Any = field(default_factory=threading.Lock, init=False)
    _rate: int = field(default=0, init=False)
    _channels: int = field(default=0, init=False)
    _live: bool = field(default=False, init=False)

    @property
    def live(self) -> bool:
        """Whether the stream is open and the reader is running."""
        return bool(self._live)

    def preroll_chunks(self) -> int:
        """How many chunks the pre-roll holds. Bounded twice, as documented."""
        # round, not int: 0.3 / 0.1 is 2.9999999999999996 in binary floating
        # point, so truncating gave two chunks and a 200ms pre-roll where 300
        # was intended. Measured, which is the only way that shows up.
        by_seconds = round(self.preroll_seconds / max(0.01, self.chunk_seconds))
        return max(1, min(MAX_PREROLL_CHUNKS, by_seconds))

    # --- opening and closing -------------------------------------------------

    def start(self) -> bool:
        """Open the stream and begin reading. False means it could not."""
        if self._live:
            return True
        try:
            sounddevice = (
                self.sounddevice
                or getattr(self.device_manager, "sounddevice", None)
                or import_sounddevice()
            )
            manager = self.device_manager or MicrophoneDeviceManager(sounddevice)
            self.device_manager = manager
            selection = manager.select(
                requested_index=self.device,
                requested_name=self.device_name,
                allow_fallback=self.device is None and self.device_name is None,
            )
            self.last_warning = selection.warning or ""
            self._rate, self._channels = _negotiate_capture_settings(
                sounddevice, selection.device, requested_rate=int(self.sample_rate)
            )
            stream = sounddevice.InputStream(
                samplerate=self._rate,
                channels=self._channels,
                dtype="int16",
                device=selection.device.index,
            )
            stream.start()
        except Exception as exc:  # noqa: BLE001 - absence is a reported outcome
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._live = False
            return False

        self._stream = stream
        self.last_device = selection.device
        self._preroll = deque(maxlen=self.preroll_chunks())
        self._stop_reader = threading.Event()
        self._live = True
        self._reader = threading.Thread(
            target=self._read_forever, name="grandpa-live-mic", daemon=True
        )
        self._reader.start()
        return True

    def close(self) -> None:
        """Stop reading and release the device."""
        self._live = False
        self._stop_reader.set()
        reader, self._reader = self._reader, None
        if reader is not None and reader is not threading.current_thread():
            reader.join(timeout=2.0)
        stream, self._stream = self._stream, None
        for name in ("stop", "close"):
            method = getattr(stream, name, None)
            if method is None:
                continue
            try:
                method()
            except Exception:  # noqa: BLE001 - releasing must not raise
                pass
        with self._lock:
            if self._preroll is not None:
                self._preroll.clear()
            self._recording = None

    # --- the reader ----------------------------------------------------------

    def _read_forever(self) -> None:
        """Read chunks until asked to stop, or until the device goes away.

        A device that disappears mid-session lands here as an exception from
        ``read``. The stream is marked dead and the reason kept, so the next
        hold can fall back to opening on demand rather than failing.
        """
        frames_per_chunk = max(1, int(self._rate * self.chunk_seconds))
        while not self._stop_reader.is_set():
            stream = self._stream
            if stream is None:
                break
            try:
                recording, _overflowed = stream.read(frames_per_chunk)
            except Exception as exc:  # noqa: BLE001 - the device left
                self.last_error = f"{type(exc).__name__}: {exc}"
                self._live = False
                return
            chunk = recording.tobytes()
            level = calculate_pcm16_rms(_downmix_pcm16(chunk, self._channels))
            if self.on_level is not None:
                try:
                    self.on_level(level)
                except Exception:  # noqa: BLE001 - a meter must not stop a read
                    pass
            with self._lock:
                if self._recording is not None:
                    self._recording.append(chunk)
                elif self._preroll is not None:
                    self._preroll.append(chunk)

    # --- the hold ------------------------------------------------------------

    def capture(
        self,
        stop_event: threading.Event | None = None,
        on_speech_start: Callable[[], None] | None = None,
    ) -> CapturedAudio:
        """One utterance, beginning with the pre-roll already in hand.

        The same signature ``MicrophoneCapture.capture`` offers, so the hold
        path does not know which one it has.
        """
        stop = stop_event or threading.Event()
        if not self._live:
            return CapturedAudio(
                b"",
                speech_detected=False,
                finalization_reason="stream_unavailable",
            )
        with self._lock:
            # The pre-roll becomes the start of the utterance, and the reader
            # appends to the utterance from here on.
            self._recording = list(self._preroll or ())
            self.last_preroll_chunks = len(self._recording)
        if on_speech_start is not None:
            try:
                on_speech_start()
            except Exception:  # noqa: BLE001
                pass
        stop.wait()
        with self._lock:
            chunks = self._recording or []
            self._recording = None
            if self._preroll is not None:
                self._preroll.clear()

        native = b"".join(chunks)
        audio = _normalize_pcm16_audio(
            native,
            input_rate=self._rate or int(self.sample_rate),
            input_channels=self._channels or 1,
            output_rate=int(self.sample_rate),
        )
        return CapturedAudio(
            data=_wav_bytes(audio, channels=1, sample_rate=int(self.sample_rate)),
            format="wav",
            rms_level=calculate_pcm16_rms(audio),
            device_name=getattr(self.last_device, "name", ""),
            device_index=getattr(self.last_device, "index", None),
            captured_frame_count=len(audio) // 2,
            speech_detected=bool(chunks),
            capture_sample_rate=self._rate or int(self.sample_rate),
            capture_channels=self._channels or 1,
            native_frame_count=len(native) // (max(1, self._channels) * 2),
            finalization_reason=(
                "key_released" if self._live else "device_lost"
            ),
            chunks_read=len(chunks),
        )

    def reset(self) -> None:
        """Discard anything held. The stream stays open."""
        with self._lock:
            if self._preroll is not None:
                self._preroll.clear()
            self._recording = None


__all__ = [
    "CHUNK_SECONDS",
    "MAX_PREROLL_CHUNKS",
    "PREROLL_SECONDS",
    "LiveMicrophone",
]
