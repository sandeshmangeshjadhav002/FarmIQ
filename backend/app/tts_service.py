"""Server-side text-to-speech synthesis.

Why this exists
---------------
Windows desktops and stock Android devices often ship no Marathi (mr-IN) or
Hindi (hi-IN) voice. The browser's ``speechSynthesis`` API then reads
Devanagari text with an English voice and plays nothing at all, and the
Android TextToSpeech engine reports an unsupported locale. The client detects
the missing voice and posts the answer to ``POST /api/voice/speak``, which
synthesises it here.

Provider
--------
The free Microsoft Edge neural voices, via the optional ``edge-tts`` package
(``mr-IN-AarohiNeural`` for Marathi by default). No API key is required, but
the server needs outbound internet access. When the package is absent the
endpoint degrades to HTTP 503 instead of breaking application start-up.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import get_settings
from app.errors import AppError

logger = logging.getLogger("farmiq.tts")

try:  # Optional dependency — see requirements.txt.
    import edge_tts
except ImportError:  # pragma: no cover - exercised by patching this attribute
    edge_tts = None


async def synthesize(text: str, language: str) -> bytes:
    """Return MP3 audio of ``text`` spoken in ``language`` ("mr" or "en").

    Raises:
        AppError: 503 when synthesis is disabled or ``edge-tts`` is missing,
            504 when the provider does not respond in time, 502 when the
            provider cannot be reached or returns no audio.
    """
    settings = get_settings()
    if not settings.tts_enabled:
        raise AppError(503, "Text-to-speech is not enabled on the server.")
    if edge_tts is None:
        raise AppError(
            503,
            "Text-to-speech is not installed on the server. "
            "Run: pip install -r requirements.txt",
        )

    voice = settings.tts_voice_for(language)
    communicate = edge_tts.Communicate(text, voice)

    audio = bytearray()
    try:
        async with asyncio.timeout(settings.tts_timeout_seconds):
            async for chunk in communicate.stream():
                if chunk.get("type") == "audio":
                    audio.extend(chunk.get("data") or b"")
    except TimeoutError as exc:
        logger.warning(
            "Speech synthesis timed out after %ss (voice=%s)",
            settings.tts_timeout_seconds,
            voice,
        )
        raise AppError(504, "Speech synthesis timed out. Please try again.") from exc
    except Exception as exc:  # noqa: BLE001 — any websocket/provider failure
        logger.warning("Speech synthesis failed (voice=%s): %s", voice, exc)
        raise AppError(
            502, f"Could not reach the speech synthesis service: {exc}"
        ) from exc

    if not audio:
        raise AppError(502, "The speech synthesis service returned no audio.")

    return bytes(audio)
