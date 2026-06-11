"""Structured meeting context generation via NVIDIA NIM (OpenAI-compatible API)."""

import json
import os
import re

from openai import OpenAI
from pydantic import ValidationError

from .models import ChatMessage, MeetingContext, TranscriptSegment

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL = "nvidia/nemotron-3-ultra-550b-a55b"

SYSTEM_PROMPT = """You are an expert meeting analyst. You receive a speaker-labeled transcript \
and produce a clean, structured context document.

Respond with ONLY a JSON object (no markdown fences, no commentary) matching this schema:
{
  "title": "short descriptive title for the conversation",
  "summary": "2-4 paragraph clean narrative of what was discussed and concluded",
  "key_points": ["..."],
  "decisions": ["decisions that were made; empty list if none"],
  "action_items": [{"task": "...", "owner": "speaker label or name, or null", "due": "deadline if mentioned, or null"}],
  "topics": ["main topics covered"],
  "open_questions": ["unresolved questions raised"],
  "speaker_notes": ["one line per speaker: what they contributed / their apparent role"]
}

Base everything strictly on the transcript. Do not invent names, owners, or deadlines."""


CHAT_SYSTEM_PROMPT = """You are a helpful meeting assistant. The user wants to discuss a \
transcribed recording. Answer questions, clarify points, draft follow-ups (emails, summaries, \
task lists), and reason about what was said — always grounded in the transcript and context below.

If something was not said in the recording, say so plainly instead of inventing it. Refer to \
speakers by their labels (or real names if mentioned in the audio). Be concise and direct.

## Recording: {title}

## Structured context
{context}

## Full transcript
{transcript}"""


def _client() -> OpenAI:
    key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        raise RuntimeError("NVIDIA_API_KEY is not set (see .env.example)")
    return OpenAI(base_url=NIM_BASE_URL, api_key=key)


def _format_transcript(segments: list[TranscriptSegment]) -> str:
    return "\n".join(f"[{s.start:.0f}s] {s.speaker}: {s.text}" for s in segments)


def _extract_json(text: str) -> dict:
    text = text.strip()
    # Tolerate markdown fences or stray prose around the JSON object.
    fence = re.search(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    elif not text.startswith("{"):
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    return json.loads(text)


def generate_context(segments: list[TranscriptSegment]) -> MeetingContext:
    """Run the LLM over the transcript and return a validated MeetingContext.

    Retries once with the validation/parse error appended if the first attempt
    fails to produce schema-conforming JSON.
    """
    client = _client()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": f"Transcript:\n\n{_format_transcript(segments)}"},
    ]

    last_error: Exception | None = None
    for _ in range(2):
        completion = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.2,
            max_tokens=4096,
            # Extraction task — disable reasoning so the output is clean JSON.
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
        )
        raw = completion.choices[0].message.content or ""
        try:
            return MeetingContext.model_validate(_extract_json(raw))
        except (json.JSONDecodeError, ValidationError) as exc:
            last_error = exc
            messages.append({"role": "assistant", "content": raw})
            messages.append(
                {
                    "role": "user",
                    "content": f"Your response was not valid JSON for the schema ({exc}). "
                    "Respond again with ONLY the corrected JSON object.",
                }
            )
    raise RuntimeError(f"LLM did not return valid structured context: {last_error}")


def chat_stream(recording: dict, history: list[ChatMessage]):
    """Yield streamed text deltas for a chat turn grounded in a recording."""
    client = _client()
    model = os.environ.get("LLM_MODEL", DEFAULT_MODEL)

    transcript_text = "\n".join(
        f"[{s['start']:.0f}s] {s['speaker']}: {s['text']}" for s in recording["transcript"]
    )
    ctx = recording.get("context")
    system = CHAT_SYSTEM_PROMPT.format(
        title=recording.get("title") or "Untitled",
        context=json.dumps(ctx, indent=2) if ctx else "(not generated yet)",
        transcript=transcript_text,
    )
    messages = [{"role": "system", "content": system}] + [m.model_dump() for m in history]

    stream = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0.6,
        max_tokens=2048,
        stream=True,
        extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    )
    for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
