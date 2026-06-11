"""Deepgram speech-to-text: prerecorded file transcription and live streaming proxy."""

import json
import os

import httpx
import websockets

DEEPGRAM_HTTP_URL = "https://api.deepgram.com/v1/listen"
DEEPGRAM_WS_URL = "wss://api.deepgram.com/v1/listen"

FILE_PARAMS = {
    "model": "nova-3",
    "diarize": "true",
    "smart_format": "true",
    "punctuate": "true",
    "utterances": "true",
}

LIVE_PARAMS = {
    "model": "nova-3",
    "diarize": "true",
    "smart_format": "true",
    "punctuate": "true",
    "interim_results": "true",
}


def _api_key() -> str:
    key = os.environ.get("DEEPGRAM_API_KEY", "")
    if not key:
        raise RuntimeError("DEEPGRAM_API_KEY is not set (see .env.example)")
    return key


def _speaker_label(index: int | None) -> str:
    return f"Speaker {index + 1}" if index is not None else "Speaker ?"


async def transcribe_file(audio: bytes, content_type: str | None) -> tuple[list[dict], float]:
    """Transcribe an uploaded audio or video file (Deepgram extracts the audio
    track from video containers like mp4/webm/mov). Returns (segments, duration_seconds)."""
    headers = {
        "Authorization": f"Token {_api_key()}",
        "Content-Type": content_type or "application/octet-stream",
    }
    async with httpx.AsyncClient(timeout=600) as client:
        resp = await client.post(DEEPGRAM_HTTP_URL, params=FILE_PARAMS, headers=headers, content=audio)
    if resp.status_code != 200:
        raise RuntimeError(f"Deepgram error {resp.status_code}: {resp.text[:500]}")

    data = resp.json()
    duration = float(data.get("metadata", {}).get("duration", 0.0))
    segments: list[dict] = []
    for utt in data.get("results", {}).get("utterances", []):
        text = (utt.get("transcript") or "").strip()
        if not text:
            continue
        segments.append(
            {
                "speaker": _speaker_label(utt.get("speaker")),
                "start": round(float(utt.get("start", 0.0)), 2),
                "end": round(float(utt.get("end", 0.0)), 2),
                "text": text,
            }
        )
    return segments, duration


def connect_live():
    """Open a Deepgram live-streaming websocket (containerized audio is auto-detected)."""
    qs = "&".join(f"{k}={v}" for k, v in LIVE_PARAMS.items())
    return websockets.connect(
        f"{DEEPGRAM_WS_URL}?{qs}",
        additional_headers={"Authorization": f"Token {_api_key()}"},
    )


def parse_live_message(raw: str | bytes) -> dict | None:
    """Convert a Deepgram live 'Results' message into a frontend transcript event."""
    try:
        msg = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if msg.get("type") != "Results":
        return None

    alt = (msg.get("channel", {}).get("alternatives") or [{}])[0]
    text = (alt.get("transcript") or "").strip()
    if not text:
        return None

    # Diarization is per-word on the live API; take the majority speaker of the segment.
    words = alt.get("words") or []
    speakers = [w["speaker"] for w in words if w.get("speaker") is not None]
    speaker_idx = max(set(speakers), key=speakers.count) if speakers else None

    start = float(msg.get("start", 0.0))
    return {
        "type": "final" if msg.get("is_final") else "interim",
        "speaker": _speaker_label(speaker_idx),
        "text": text,
        "start": round(start, 2),
        "end": round(start + float(msg.get("duration", 0.0)), 2),
    }
