"""Pydantic models shared across the app."""

from pydantic import BaseModel, Field


class TranscriptSegment(BaseModel):
    speaker: str  # "Speaker 1", "Speaker 2", ...
    start: float  # seconds
    end: float
    text: str


class ActionItem(BaseModel):
    task: str
    owner: str | None = None  # speaker label or real name if mentioned
    due: str | None = None


class MeetingContext(BaseModel):
    title: str
    summary: str  # 2-4 paragraph clean narrative
    key_points: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    action_items: list[ActionItem] = Field(default_factory=list)
    topics: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    speaker_notes: list[str] = Field(default_factory=list)


class ChatMessage(BaseModel):
    role: str  # "user" | "assistant"
    content: str


class ChatPayload(BaseModel):
    messages: list[ChatMessage]


class LiveSessionPayload(BaseModel):
    """Sent by the frontend when a live session ends."""

    title: str | None = None
    duration: float = 0.0
    segments: list[TranscriptSegment]
