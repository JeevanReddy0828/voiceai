# 🎙️ VoiceAI

**Turn any conversation into a transcript, a structured brief, and an agent you can talk to.**

VoiceAI is a local web app that transcribes recordings and live meetings with speaker
diarization, distills them into clean structured context (summary, decisions, action
items), and lets you chat with an AI agent that knows everything that was said.

## ✨ Features

- **📁 Upload mode** — drop in an audio file (mp3, wav, m4a, webm, ogg, flac) or a video
  file (mp4, webm, mov — the audio track is transcribed). Get back a speaker-labeled
  transcript (Speaker 1, Speaker 2, …) with timestamps.
- **🧠 Structured context** — every recording is distilled by an LLM into a clean brief:
  title, narrative summary, key points, decisions, action items (with owner and due
  date), topics, open questions, and per-speaker notes.
- **🔴 Live meeting assistant** — stream your microphone and watch the transcript appear
  in real time with speaker diarization. Interim text shows in gray and finalizes with
  colored speaker badges. End the session to get the same structured brief.
- **💬 Chat with your recordings** — pick any transcribed recording and ask an agent
  about it: who said what, what was decided, or "draft the follow-up email". Responses
  stream in live and are grounded strictly in the transcript — the agent says so when
  something wasn't discussed, instead of making it up.
- **📚 Library** — every recording, transcript, and brief persists locally in SQLite.

## 🏗️ How it works

```
Browser (vanilla JS, served by FastAPI)
 ├─ Upload ──POST /api/recordings──▶ FastAPI ──▶ Deepgram nova-3 (prerecorded, diarize)
 │                                     │              │ speaker-labeled transcript
 │                                     ▼              ▼
 │                                  SQLite ◀── NVIDIA NIM · Nemotron 3 Ultra (structured JSON brief)
 ├─ Live ──mic chunks──WS /ws/live──▶ FastAPI ──proxy──▶ Deepgram live WS (diarize, interim results)
 └─ Chat ──POST /api/recordings/{id}/chat──▶ Nemotron grounded in transcript + context (streamed)
```

| Layer | Tech |
|---|---|
| Speech-to-text | [Deepgram](https://deepgram.com) `nova-3` — file + live streaming, speaker diarization |
| Context & chat LLM | [NVIDIA NIM](https://build.nvidia.com) `nvidia/nemotron-3-ultra-550b-a55b` (OpenAI-compatible API) |
| Backend | Python · FastAPI · WebSockets · SQLite |
| Frontend | Vanilla JS · single page, zero build step |

## 🚀 Quickstart

Requires **Python 3.11+** and two free API keys.

```powershell
git clone https://github.com/JeevanReddy0828/voiceai.git
cd voiceai
pip install -r requirements.txt

copy .env.example .env     # then edit .env:
#   DEEPGRAM_API_KEY  — https://console.deepgram.com  ($200 free credit)
#   NVIDIA_API_KEY    — https://build.nvidia.com      (nvapi-... key)

uvicorn backend.main:app --port 8010
```

Open <http://localhost:8010> — upload a recording, or hit **Live** and start talking.

## 🔌 API

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/recordings` | Upload an audio/video file (multipart `file`) → `{id}` |
| `POST` | `/api/recordings/live` | Save a finished live session (`{duration, segments}`) |
| `POST` | `/api/recordings/{id}/chat` | Chat about a recording (`{messages}`) → streamed text |
| `GET` | `/api/recordings` | List recordings |
| `GET` | `/api/recordings/{id}` | Full recording with transcript + context |
| `DELETE` | `/api/recordings/{id}` | Delete a recording |
| `WS` | `/ws/live` | Stream mic audio (webm/opus chunks) → live transcript events |

## 📂 Project structure

```
backend/
  main.py            FastAPI app: routes, live WebSocket proxy, static serving
  transcription.py   Deepgram: file transcription + live streaming connection
  context.py         Nemotron: structured brief generation + grounded chat (streaming)
  models.py          Pydantic schemas (TranscriptSegment, MeetingContext, chat payloads)
  db.py              SQLite persistence
frontend/
  index.html · app.js · styles.css   Upload / Live / Library / Chat tabs
```

## ⚠️ Notes & limitations

- Diarization labels speakers by voice (Speaker 1/2/…); it can't know real names unless
  they're spoken. Synthetic/TTS voices may collapse into one speaker — use real voices.
- Live mode captures the **microphone only**. For online meetings, remote participants
  are picked up via your speakers; system-audio capture is a possible future upgrade.
- Keep API keys in `.env` (gitignored) — never commit them. Rotate any key that may
  have been exposed.

## 💸 Cost

Deepgram ≈ $0.46/hour of audio (the free credit covers ~430 hours). Context generation
and chat are billed through your NVIDIA NIM credits per request.
