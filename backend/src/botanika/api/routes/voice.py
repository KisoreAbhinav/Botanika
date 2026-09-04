"""Pi-local bounded voice routes for Ask Botanika."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, File, Request, UploadFile

from botanika.api.auth import require_local_operator, require_local_or_controller
from botanika.api.concurrency import run_blocking
from botanika.api.runtime import get_runtime
from botanika.api.schemas import VoiceSpeakRequest
from botanika.core.errors import CapabilityUnavailableError, ValidationError
from botanika.voice import InvalidAudio, VoiceUnavailable


router = APIRouter(prefix="/voice", tags=["voice"])


@router.get("/status")
async def voice_status(request: Request) -> dict[str, Any]:
    runtime = get_runtime(request)
    require_local_or_controller(runtime, request)
    if runtime.voice is None:
        return {
            "state": "unavailable",
            "available": False,
            "detail": "Pi voice coordinator is not initialized.",
            "typed_chat_remains_available": True,
        }
    return runtime.voice.status().to_dict()


@router.get("/stt/status")
async def stt_status(request: Request) -> dict[str, Any]:
    value = await voice_status(request)
    return {
        "state": value.get("state"),
        "available": value.get("stt_available", False),
        "model": value.get("stt_model"),
        "detail": value.get("detail"),
    }


@router.get("/tts/status")
async def tts_status(request: Request) -> dict[str, Any]:
    value = await voice_status(request)
    return {
        "state": value.get("state"),
        "available": value.get("tts_available", False),
        "model": value.get("tts_model"),
        "detail": value.get("detail"),
    }


@router.post("/listen")
@router.post("/start")
async def listen(request: Request) -> dict[str, Any]:
    """Capture one spoken botanical question and ground its answer locally."""

    require_local_operator(request)
    runtime = get_runtime(request)
    if runtime.voice is None:
        raise CapabilityUnavailableError("Pi voice coordinator is unavailable")
    try:
        # Audio capture/model work is synchronous and can occupy the Pi for
        # several seconds. Keep it off the event loop so /interrupt, health,
        # and typed-chat requests remain serviceable while a turn is active.
        turn = await run_blocking(runtime.voice.listen_once)
    except VoiceUnavailable as exc:
        raise CapabilityUnavailableError(str(exc)) from exc
    transcript = str(turn.get("transcript") or "").strip()
    if not transcript:
        return {
            "transcript": "",
            "answer": None,
            "playback": None,
            "status": turn.get("status"),
            "interrupted": bool(turn.get("interrupted")),
            "detail": turn.get("detail") or "No spoken question was captured.",
        }
    answer = await run_blocking(runtime.knowledge.answer, transcript)
    playback: dict[str, Any] | None = None
    if not answer.abstained:
        try:
            playback = await run_blocking(runtime.voice.speak, answer.answer)
        except VoiceUnavailable as exc:
            # Identification/typed chat stays useful when the speaker or
            # Piper voice is absent; make the degradation explicit.
            playback = {"status": "unavailable", "detail": str(exc), "played": False}
    return {
        "transcript": transcript,
        "answer": answer.to_dict(),
        "playback": playback,
        "status": turn.get("status", "ok"),
        "interrupted": bool(turn.get("interrupted")),
    }


@router.post("/transcribe")
async def transcribe(request: Request, file: UploadFile = File(...)) -> dict[str, Any]:
    require_local_operator(request)
    runtime = get_runtime(request)
    if runtime.voice is None:
        raise CapabilityUnavailableError("Pi voice coordinator is unavailable")
    payload = await file.read(runtime.settings.voice_max_audio_bytes + 1)
    try:
        return await run_blocking(runtime.voice.transcribe_wav, payload)
    except InvalidAudio as exc:
        raise ValidationError(str(exc)) from exc
    except VoiceUnavailable as exc:
        raise CapabilityUnavailableError(str(exc)) from exc


@router.post("/speak")
async def speak(request: Request, body: VoiceSpeakRequest) -> dict[str, Any]:
    require_local_operator(request)
    runtime = get_runtime(request)
    if runtime.voice is None:
        raise CapabilityUnavailableError("Pi voice coordinator is unavailable")
    try:
        return await run_blocking(runtime.voice.speak, body.text)
    except (ValueError, InvalidAudio) as exc:
        raise ValidationError(str(exc)) from exc
    except VoiceUnavailable as exc:
        raise CapabilityUnavailableError(str(exc)) from exc


@router.post("/interrupt")
@router.post("/stop")
@router.post("/cancel")
async def interrupt(request: Request) -> dict[str, Any]:
    require_local_operator(request)
    runtime = get_runtime(request)
    if runtime.voice is None:
        raise CapabilityUnavailableError("Pi voice coordinator is unavailable")
    return runtime.voice.interrupt()


__all__ = ["router"]
