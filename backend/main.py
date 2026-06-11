"""VoiceAI — FastAPI app: upload transcription, live transcription proxy, structured context."""

import asyncio
import contextlib
import os
from pathlib import Path

import websockets.exceptions
from dotenv import load_dotenv
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import db, transcription
from .context import chat_stream, generate_context
from .models import ChatPayload, LiveSessionPayload, TranscriptSegment

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

app = FastAPI(title="VoiceAI")
db.init_db()


@app.on_event("startup")
async def warn_missing_keys() -> None:
    for var in ("DEEPGRAM_API_KEY", "NVIDIA_API_KEY"):
        if not os.environ.get(var):
            print(f"WARNING: {var} is not set — copy .env.example to .env and fill it in.")


# ---------- upload flow ----------

async def _process_upload(rec_id: str, audio: bytes, content_type: str | None) -> None:
    try:
        segments, duration = await transcription.transcribe_file(audio, content_type)
        if not segments:
            raise RuntimeError("No speech detected in the recording.")
        db.set_transcript(rec_id, segments, duration)
        ctx = await asyncio.to_thread(
            generate_context, [TranscriptSegment(**s) for s in segments]
        )
        db.set_context(rec_id, ctx.model_dump())
    except Exception as exc:  # surface any failure to the UI via status=error
        db.set_error(rec_id, str(exc))


@app.post("/api/recordings")
async def upload_recording(background: BackgroundTasks, file: UploadFile = File(...)):
    audio = await file.read()
    if not audio:
        raise HTTPException(400, "Empty file")
    rec_id = db.create_recording(title=file.filename or "Recording", source="upload")
    background.add_task(_process_upload, rec_id, audio, file.content_type)
    return {"id": rec_id, "status": "processing"}


# ---------- live flow ----------

async def _process_live(rec_id: str, payload: LiveSessionPayload) -> None:
    try:
        ctx = await asyncio.to_thread(generate_context, payload.segments)
        db.set_context(rec_id, ctx.model_dump())
    except Exception as exc:
        db.set_error(rec_id, str(exc))


@app.post("/api/recordings/live")
async def save_live_session(payload: LiveSessionPayload, background: BackgroundTasks):
    if not payload.segments:
        raise HTTPException(400, "No transcript segments in this session")
    rec_id = db.create_recording(title=payload.title or "Live session", source="live")
    db.set_transcript(rec_id, [s.model_dump() for s in payload.segments], payload.duration)
    background.add_task(_process_live, rec_id, payload)
    return {"id": rec_id, "status": "processing"}


@app.websocket("/ws/live")
async def live_transcription(client_ws: WebSocket):
    """Proxy mic audio from the browser to Deepgram and relay transcripts back."""
    await client_ws.accept()
    try:
        async with transcription.connect_live() as dg_ws:

            async def pump_audio():
                while True:
                    chunk = await client_ws.receive_bytes()
                    await dg_ws.send(chunk)

            async def pump_results():
                async for raw in dg_ws:
                    event = transcription.parse_live_message(raw)
                    if event:
                        await client_ws.send_json(event)

            tasks = [asyncio.create_task(pump_audio()), asyncio.create_task(pump_results())]
            try:
                done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_EXCEPTION)
                for task in done:
                    exc = task.exception()
                    if exc and not isinstance(
                        exc, (WebSocketDisconnect, websockets.exceptions.ConnectionClosed)
                    ):
                        raise exc
            finally:
                for task in tasks:
                    task.cancel()
                    with contextlib.suppress(BaseException):
                        await task
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        with contextlib.suppress(Exception):
            await client_ws.send_json({"type": "error", "message": str(exc)})
        with contextlib.suppress(Exception):
            await client_ws.close()


# ---------- chat ----------

@app.post("/api/recordings/{rec_id}/chat")
async def chat_about_recording(rec_id: str, payload: ChatPayload):
    rec = db.get_recording(rec_id)
    if rec is None:
        raise HTTPException(404, "Recording not found")
    if not rec.get("transcript"):
        raise HTTPException(400, "Recording has no transcript yet")
    if not payload.messages:
        raise HTTPException(400, "No messages")
    # Sync generator — Starlette iterates it in a threadpool, so the event loop stays free.
    return StreamingResponse(
        chat_stream(rec, payload.messages), media_type="text/plain; charset=utf-8"
    )


# ---------- library ----------

@app.get("/api/recordings")
async def list_recordings():
    return db.list_recordings()


@app.get("/api/recordings/{rec_id}")
async def get_recording(rec_id: str):
    rec = db.get_recording(rec_id)
    if rec is None:
        raise HTTPException(404, "Recording not found")
    return rec


@app.delete("/api/recordings/{rec_id}")
async def delete_recording(rec_id: str):
    if not db.delete_recording(rec_id):
        raise HTTPException(404, "Recording not found")
    return {"deleted": rec_id}


# ---------- frontend ----------

FRONTEND = ROOT / "frontend"


@app.get("/")
async def index():
    return FileResponse(FRONTEND / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND), name="static")
