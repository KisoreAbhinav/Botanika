"""One-owner offline STT/TTS coordinator for the Pi.

The coordinator follows the proven InnoHack shape: bounded command turns,
short-silence endpointing, lazy cached local models, interruptible playback,
and one lock around microphone/speaker ownership.  Missing devices or model
artifacts are surfaced as unavailable states; no transcript or audio is
fabricated.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import io
import importlib.util
import json
import logging
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import wave
from typing import Any, Callable

import numpy as np

from botanika.core.settings import AppSettings


LOGGER = logging.getLogger("botanika.voice")
WAV_REQUIREMENT = "audio must be a 16kHz mono 16-bit PCM WAV file"


class VoiceState(str, Enum):
    IDLE = "idle"
    LISTENING = "listening"
    TRANSCRIBING = "transcribing"
    SPEAKING = "speaking"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


class VoiceUnavailable(RuntimeError):
    """Raised when a requested voice operation cannot run locally."""


class InvalidAudio(ValueError):
    """Raised when an uploaded or recorded audio payload is not supported."""


@dataclass(frozen=True, slots=True)
class VoiceStatus:
    state: str
    microphone_available: bool
    speaker_available: bool
    stt_available: bool
    tts_available: bool
    stt_model: str | None
    tts_model: str | None
    detail: str
    error: str | None = None

    @property
    def available(self) -> bool:
        return self.microphone_available and self.speaker_available and self.stt_available and self.tts_available

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "available": self.available,
            "microphone_available": self.microphone_available,
            "speaker_available": self.speaker_available,
            "stt_available": self.stt_available,
            "tts_available": self.tts_available,
            "stt_model": self.stt_model,
            "tts_model": self.tts_model,
            "detail": self.detail,
            "error": self.error,
            "typed_chat_remains_available": True,
        }


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    transcript: str
    answer: Any | None = None
    playback: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        value: dict[str, Any] = {"transcript": self.transcript}
        if self.answer is not None:
            value["answer"] = self.answer.to_dict() if hasattr(self.answer, "to_dict") else self.answer
        if self.playback is not None:
            value["playback"] = self.playback
        return value


def find_vosk_model(root: Path, preferred_name: str | None = None) -> Path | None:
    """Find an extracted Vosk model without downloading anything."""

    root = Path(root)
    candidates: list[Path] = []
    if all((root / name).is_dir() for name in ("am", "conf", "graph")):
        candidates.append(root)
    if root.is_dir():
        if preferred_name:
            candidates.insert(0, root / preferred_name)
        candidates.extend(sorted(path for path in root.iterdir() if path.is_dir()))
    for candidate in candidates:
        if all((candidate / name).is_dir() for name in ("am", "conf", "graph")):
            return candidate
    return None


def find_piper_voice(root: Path, preferred_name: str | None = None) -> Path | None:
    """Find a Piper ONNX voice and its adjacent JSON config."""

    root = Path(root)
    candidates: list[Path] = []
    if preferred_name:
        preferred = root / preferred_name
        candidates.append(preferred)
    if root.is_dir():
        candidates.extend(sorted(root.rglob("*.onnx")))
    for candidate in candidates:
        if candidate.is_file() and Path(f"{candidate}.json").is_file():
            return candidate
    return None


def validate_wav(audio: bytes, *, max_bytes: int, max_seconds: float) -> tuple[np.ndarray, int]:
    """Decode a bounded PCM WAV and return int16 samples plus sample rate."""

    if not isinstance(audio, (bytes, bytearray)) or not audio:
        raise InvalidAudio(WAV_REQUIREMENT)
    if len(audio) > max_bytes:
        raise InvalidAudio(f"audio exceeds the configured {max_bytes} byte limit")
    try:
        handle = wave.open(io.BytesIO(bytes(audio)), "rb")
    except (EOFError, wave.Error) as exc:
        raise InvalidAudio(WAV_REQUIREMENT) from exc
    with handle:
        if (
            handle.getnchannels() != 1
            or handle.getsampwidth() != 2
            or handle.getframerate() != 16000
            or handle.getcomptype() != "NONE"
        ):
            raise InvalidAudio(WAV_REQUIREMENT)
        frames = handle.getnframes()
        if frames <= 0 or frames / 16000.0 > max_seconds:
            raise InvalidAudio(f"audio must be at most {max_seconds:g} seconds")
        payload = handle.readframes(frames)
    return np.frombuffer(payload, dtype=np.int16).copy(), 16000


def endpoint_reached(
    *,
    speech_detected: bool,
    silence_seconds: float,
    short_silence_seconds: float,
    long_silence_seconds: float,
) -> str | None:
    """Return ``end`` or ``timeout`` for a bounded command-turn state."""

    if speech_detected and silence_seconds >= short_silence_seconds:
        return "end"
    if not speech_detected and silence_seconds >= long_silence_seconds:
        return "timeout"
    return None


class AudioCoordinator:
    """Own microphone and speaker operations for the complete Pi voice turn."""

    def __init__(self, settings: AppSettings) -> None:
        self.settings = settings
        self._owner_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._state = VoiceState.IDLE
        self._last_error: str | None = None
        self._stt_model: Any = None
        self._stt_model_path: Path | None = None
        self._tts_voice: Any = None
        self._tts_model_path: Path | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._interrupt = threading.Event()

    def status(self, *, load_models: bool = False) -> VoiceStatus:
        microphone, speaker, device_detail = self._audio_devices()
        stt_path = find_vosk_model(self.settings.stt_models_path, self.settings.stt_model_name)
        tts_path = find_piper_voice(self.settings.tts_models_path, self.settings.tts_model_name)
        stt_provider = str(self.settings.stt_provider).lower()
        tts_provider = str(self.settings.tts_provider).lower()
        stt_runtime = stt_provider == "vosk" and _runtime_binding_available("vosk")
        tts_runtime = tts_provider == "piper" and _runtime_binding_available("piper")
        stt_configured = stt_provider == "vosk" and stt_path is not None and stt_runtime
        tts_configured = tts_provider == "piper" and tts_path is not None and tts_runtime
        if load_models:
            if stt_configured:
                try:
                    self._ensure_stt(stt_path)
                except Exception as exc:
                    self._last_error = str(exc)
            if tts_configured:
                try:
                    self._ensure_tts(tts_path)
                except Exception as exc:
                    self._last_error = str(exc)
        stt_available = stt_configured and self._stt_model is not None if load_models else stt_configured
        tts_available = tts_configured and self._tts_voice is not None if load_models else tts_configured
        errors = [item for item in (device_detail, self._last_error) if item]
        if stt_provider == "vosk" and stt_path is None:
            errors.append("offline Vosk STT model is unavailable")
        elif stt_provider == "vosk" and not stt_runtime:
            errors.append("Vosk STT runtime binding is unavailable")
        elif stt_provider != "disabled" and stt_provider != "vosk":
            errors.append(f"unsupported STT provider: {self.settings.stt_provider}")
        if tts_provider == "piper" and tts_path is None:
            errors.append("offline Piper TTS voice is unavailable")
        elif tts_provider == "piper" and not tts_runtime:
            errors.append("Piper TTS runtime binding is unavailable")
        elif tts_provider != "disabled" and tts_provider != "piper":
            errors.append(f"unsupported TTS provider: {self.settings.tts_provider}")
        with self._state_lock:
            state = self._state.value
        if not microphone or not speaker or not stt_available or not tts_available:
            state = VoiceState.UNAVAILABLE.value if state == VoiceState.IDLE.value else state
        return VoiceStatus(
            state=state,
            microphone_available=microphone,
            speaker_available=speaker,
            stt_available=stt_available,
            tts_available=tts_available,
            stt_model=str(self._stt_model_path or stt_path) if stt_path else None,
            tts_model=str(self._tts_model_path or tts_path) if tts_path else None,
            detail="; ".join(errors) if errors else "Offline microphone, STT, TTS, and speaker are ready.",
            error=self._last_error,
        )

    def transcribe_wav(self, audio: bytes) -> dict[str, Any]:
        samples, _ = validate_wav(
            audio,
            max_bytes=self.settings.voice_max_audio_bytes,
            max_seconds=self.settings.voice_max_turn_seconds,
        )
        with self._owner_lock:
            self._interrupt.clear()
            self._set_state(VoiceState.TRANSCRIBING)
            try:
                if self._interrupt.is_set():
                    return _interrupted_transcription()
                model_path = find_vosk_model(self.settings.stt_models_path, self.settings.stt_model_name)
                model = self._ensure_stt(model_path)
                result = self._transcribe_samples(model, samples, interrupt=self._interrupt)
                if result.get("interrupted") or self._interrupt.is_set():
                    return _interrupted_transcription()
                self._last_error = None
                return result
            except VoiceUnavailable:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                raise VoiceUnavailable(f"offline transcription failed: {exc}") from exc
            finally:
                self._set_state(VoiceState.IDLE)

    def listen_once(self) -> dict[str, Any]:
        """Capture one bounded command with speech and silence endpointing."""

        with self._owner_lock:
            # A prior cancelled turn must not cancel the next turn. The
            # interrupt event is deliberately separate from the owner lock so
            # the API's /interrupt request can set it while capture is blocked
            # inside sounddevice.read().
            self._interrupt.clear()
            self._set_state(VoiceState.LISTENING)
            try:
                microphone, _, detail = self._audio_devices()
                if not microphone:
                    raise VoiceUnavailable(detail or "Pi microphone is unavailable")
                model_path = find_vosk_model(self.settings.stt_models_path, self.settings.stt_model_name)
                model = self._ensure_stt(model_path)
                if self._interrupt.is_set():
                    return _interrupted_turn()
                try:
                    import sounddevice as sd
                except Exception as exc:
                    raise VoiceUnavailable(f"microphone runtime is unavailable: {exc}") from exc
                chunk_size = max(1, round(self.settings.voice_sample_rate * self.settings.voice_chunk_ms / 1000))
                recorded: list[np.ndarray] = []
                speech = False
                silence_started: float | None = None
                started = time.monotonic()
                with sd.InputStream(
                    samplerate=self.settings.voice_sample_rate,
                    channels=1,
                    dtype="int16",
                    blocksize=chunk_size,
                ) as stream:
                    while True:
                        chunk, _ = stream.read(chunk_size)
                        if self._interrupt.is_set():
                            return _interrupted_turn()
                        values = np.asarray(chunk[:, 0] if getattr(chunk, "ndim", 1) == 2 else chunk, dtype=np.int16).copy()
                        recorded.append(values)
                        rms = float(np.sqrt(np.mean(values.astype(np.float32) ** 2))) if values.size else 0.0
                        now = time.monotonic()
                        if rms >= self.settings.voice_silence_rms:
                            speech = True
                            silence_started = None
                        elif silence_started is None:
                            silence_started = now
                        silence_seconds = now - silence_started if silence_started is not None else 0.0
                        endpoint = endpoint_reached(
                            speech_detected=speech,
                            silence_seconds=silence_seconds,
                            short_silence_seconds=self.settings.voice_short_silence_seconds,
                            long_silence_seconds=self.settings.voice_long_silence_seconds,
                        )
                        if endpoint is not None:
                            break
                        if (
                            not speech
                            and now - started >= self.settings.voice_start_timeout_seconds
                        ) or now - started >= self.settings.voice_max_turn_seconds:
                            break
                if self._interrupt.is_set():
                    return _interrupted_turn()
                if not speech:
                    return {"transcript": "", "status": "timeout", "detail": "No speech was detected."}
                self._set_state(VoiceState.TRANSCRIBING)
                if self._interrupt.is_set():
                    return _interrupted_turn()
                result = self._transcribe_samples(model, np.concatenate(recorded), interrupt=self._interrupt)
                if result.get("interrupted") or self._interrupt.is_set():
                    return _interrupted_turn()
                return {"transcript": result["text"], "status": "ok"}
            except VoiceUnavailable:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                raise VoiceUnavailable(f"offline microphone capture failed: {exc}") from exc
            finally:
                self._set_state(VoiceState.IDLE)

    def speak(self, text: str) -> dict[str, Any]:
        text = " ".join(str(text or "").split())
        if not text:
            raise ValueError("text to speak cannot be empty")
        if len(text) > 4000:
            raise ValueError("text to speak is too long")
        with self._owner_lock:
            _, speaker, detail = self._audio_devices()
            if not speaker:
                raise VoiceUnavailable(detail or "Pi speaker is unavailable")
            model_path = find_piper_voice(self.settings.tts_models_path, self.settings.tts_model_name)
            voice = self._ensure_tts(model_path)
            self._interrupt.clear()
            self._set_state(VoiceState.SPEAKING)
            try:
                payload = self._synthesize(voice, text)
                if self._interrupt.is_set():
                    return {"status": "interrupted", "text": text, "bytes": len(payload), "played": False, "interrupted": True}
                played = self._play(payload)
                if not played or self._interrupt.is_set():
                    return {"status": "interrupted", "text": text, "bytes": len(payload), "played": False, "interrupted": True}
                return {"status": "played", "text": text, "bytes": len(payload), "interrupted": False}
            except VoiceUnavailable:
                raise
            except Exception as exc:
                self._last_error = str(exc)
                raise VoiceUnavailable(f"offline speech playback failed: {exc}") from exc
            finally:
                self._process = None
                self._set_state(VoiceState.IDLE)

    def interrupt(self) -> dict[str, Any]:
        self._interrupt.set()
        process = self._process
        if process is not None and process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass
        with self._state_lock:
            was_active = self._state in {VoiceState.SPEAKING, VoiceState.LISTENING, VoiceState.TRANSCRIBING}
        # Leave the active state owned by the worker until its finally block
        # releases the owner. Reporting IDLE here made an in-flight capture
        # look finished and allowed callers to race a second turn.
        return {"ok": True, "interrupted": was_active}

    def _audio_devices(self) -> tuple[bool, bool, str | None]:
        try:
            import sounddevice as sd

            devices = sd.query_devices()
            microphone = any(int(item.get("max_input_channels", 0)) > 0 for item in devices)
            speaker = any(int(item.get("max_output_channels", 0)) > 0 for item in devices)
            if microphone and speaker:
                return True, True, None
            missing = []
            if not microphone:
                missing.append("no microphone capture device was enumerated")
            if not speaker:
                missing.append("no speaker playback device was enumerated")
            return microphone, speaker, "; ".join(missing)
        except Exception as exc:
            return False, False, f"audio devices unavailable: {exc}"

    def _ensure_stt(self, model_path: Path | None) -> Any:
        if str(self.settings.stt_provider).lower() != "vosk":
            raise VoiceUnavailable(f"unsupported STT provider: {self.settings.stt_provider}")
        if model_path is None:
            raise VoiceUnavailable("no offline Vosk model was found; typed chat remains available")
        if self._stt_model is not None and self._stt_model_path == model_path:
            return self._stt_model
        try:
            from vosk import Model

            self._stt_model = Model(str(model_path))
            self._stt_model_path = model_path
            return self._stt_model
        except Exception as exc:
            raise VoiceUnavailable(f"could not load offline Vosk model: {exc}") from exc

    def _ensure_tts(self, model_path: Path | None) -> Any:
        if str(self.settings.tts_provider).lower() != "piper":
            raise VoiceUnavailable(f"unsupported TTS provider: {self.settings.tts_provider}")
        if model_path is None:
            raise VoiceUnavailable("no offline Piper voice was found; typed chat remains available")
        if self._tts_voice is not None and self._tts_model_path == model_path:
            return self._tts_voice
        try:
            from piper import PiperVoice

            self._tts_voice = PiperVoice.load(str(model_path))
            self._tts_model_path = model_path
            return self._tts_voice
        except Exception as exc:
            raise VoiceUnavailable(f"could not load offline Piper voice: {exc}") from exc

    @staticmethod
    def _transcribe_samples(
        model: Any,
        samples: np.ndarray,
        *,
        interrupt: threading.Event | None = None,
    ) -> dict[str, Any]:
        from vosk import KaldiRecognizer

        recognizer = KaldiRecognizer(model, 16000)
        recognizer.SetWords(True)
        complete: list[str] = []
        words: list[dict[str, Any]] = []
        for offset in range(0, len(samples), 4000):
            if interrupt is not None and interrupt.is_set():
                return _interrupted_transcription()
            chunk = samples[offset : offset + 4000].tobytes()
            if recognizer.AcceptWaveform(chunk):
                value = _json_result(recognizer.Result())
                if value.get("text"):
                    complete.append(str(value["text"]))
                if isinstance(value.get("result"), list):
                    words.extend(value["result"])
        final = _json_result(recognizer.FinalResult())
        if final.get("text"):
            complete.append(str(final["text"]))
        if isinstance(final.get("result"), list):
            words.extend(final["result"])
        confidences = [float(item["conf"]) for item in words if isinstance(item, dict) and "conf" in item]
        return {
            "text": " ".join(complete).strip(),
            "confidence": round(sum(confidences) / len(confidences), 4) if confidences else None,
            "provider": "vosk",
        }

    @staticmethod
    def _synthesize(voice: Any, text: str) -> bytes:
        output = io.BytesIO()
        with wave.open(output, "wb") as handle:
            voice.synthesize_wav(text, handle)
        return output.getvalue()

    def _play(self, payload: bytes) -> bool:
        if shutil.which("aplay") is None:
            raise VoiceUnavailable("aplay is not installed; synthesized speech was not played")
        if self._interrupt.is_set():
            return False
        process = subprocess.Popen(
            ["aplay", "-q", "-t", "wav", "-"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self._process = process
        try:
            if process.stdin is not None:
                try:
                    process.stdin.write(payload)
                    process.stdin.close()
                except (BrokenPipeError, OSError) as exc:
                    if self._interrupt.is_set():
                        return False
                    raise VoiceUnavailable(f"speaker playback input failed: {exc}") from exc
            deadline = time.monotonic() + self.settings.voice_tts_timeout_seconds
            while process.poll() is None:
                if self._interrupt.is_set():
                    _terminate_process(process)
                    return False
                if time.monotonic() > deadline:
                    _terminate_process(process)
                    raise VoiceUnavailable("speech playback exceeded its time limit")
                time.sleep(0.03)
            if self._interrupt.is_set():
                return False
            stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
            if process.returncode != 0:
                raise VoiceUnavailable(stderr.strip() or "speaker playback failed")
            return True
        finally:
            self._process = None

    def _set_state(self, state: VoiceState) -> None:
        with self._state_lock:
            self._state = state


def _json_result(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _runtime_binding_available(module_name: str) -> bool:
    """Return whether an optional runtime can be imported without importing it."""

    try:
        if module_name in sys.modules:
            return True
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ValueError, AttributeError):
        # A partially initialized/mocked module can have no import spec. It is
        # still safe to let the real lazy loader provide the detailed error.
        return module_name in sys.modules


def _interrupted_turn() -> dict[str, Any]:
    return {
        "transcript": "",
        "status": "interrupted",
        "detail": "Voice capture was interrupted.",
        "interrupted": True,
    }


def _interrupted_transcription() -> dict[str, Any]:
    return {
        "text": "",
        "confidence": None,
        "provider": "vosk",
        "status": "interrupted",
        "detail": "Voice transcription was interrupted.",
        "interrupted": True,
    }


def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    try:
        process.terminate()
    except OSError:
        return
    try:
        process.wait(timeout=1.0)
    except (subprocess.TimeoutExpired, OSError):
        try:
            process.kill()
        except OSError:
            pass


__all__ = [
    "AudioCoordinator",
    "InvalidAudio",
    "VoiceState",
    "VoiceStatus",
    "VoiceTurn",
    "VoiceUnavailable",
    "endpoint_reached",
    "find_piper_voice",
    "find_vosk_model",
    "validate_wav",
]
