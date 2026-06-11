"use strict";

// ---------- tabs ----------
function switchTab(name) {
  document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  document.querySelectorAll(".tab").forEach((t) => t.classList.toggle("active", t.id === `tab-${name}`));
  if (name === "library") loadLibrary();
  if (name === "chat") loadChatRecordings();
}

document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchTab(btn.dataset.tab));
});

const SPEAKER_COLORS = ["--sp1", "--sp2", "--sp3", "--sp4", "--sp5", "--sp6"];

function speakerColor(label) {
  const m = /(\d+)/.exec(label);
  const idx = m ? (parseInt(m[1], 10) - 1) % SPEAKER_COLORS.length : 0;
  return `var(${SPEAKER_COLORS[idx]})`;
}

function fmtTime(sec) {
  const m = Math.floor(sec / 60);
  const s = Math.floor(sec % 60).toString().padStart(2, "0");
  return `${m}:${s}`;
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function segmentNode(seg, interim = false) {
  const row = el("div", `seg${interim ? " interim" : ""}`);
  row.appendChild(el("span", "time", fmtTime(seg.start)));
  const badge = el("span", "badge", seg.speaker);
  badge.style.background = speakerColor(seg.speaker);
  row.appendChild(badge);
  row.appendChild(el("span", "text", seg.text));
  return row;
}

function renderTranscript(container, segments) {
  container.innerHTML = "";
  segments.forEach((s) => container.appendChild(segmentNode(s)));
}

function renderContext(container, ctx) {
  container.innerHTML = "";
  const card = el("div", "card");
  card.appendChild(el("h2", null, ctx.title));
  ctx.summary.split(/\n+/).forEach((p) => card.appendChild(el("p", null, p)));

  const sections = [
    ["Key points", ctx.key_points],
    ["Decisions", ctx.decisions],
    ["Topics", ctx.topics],
    ["Open questions", ctx.open_questions],
    ["Speaker notes", ctx.speaker_notes],
  ];
  for (const [label, items] of sections) {
    if (!items || !items.length) continue;
    card.appendChild(el("h3", null, label));
    const ul = el("ul");
    items.forEach((i) => ul.appendChild(el("li", null, i)));
    card.appendChild(ul);
  }

  if (ctx.action_items && ctx.action_items.length) {
    card.appendChild(el("h3", null, "Action items"));
    const ul = el("ul");
    ctx.action_items.forEach((a) => {
      let line = a.task;
      if (a.owner) line += ` — ${a.owner}`;
      if (a.due) line += ` (due ${a.due})`;
      ul.appendChild(el("li", null, line));
    });
    card.appendChild(ul);
  }
  container.appendChild(card);
}

function renderRecording(container, rec) {
  container.innerHTML = "";
  if (rec.context) renderContext(container, rec.context);
  if (rec.transcript && rec.transcript.length) {
    const card = el("div", "card");
    card.appendChild(el("h2", null, "Transcript"));
    const t = el("div", "transcript");
    renderTranscript(t, rec.transcript);
    card.appendChild(t);
    container.appendChild(card);
  }
  container.classList.remove("hidden");
}

// ---------- polling ----------
async function pollRecording(id, statusEl, resultEl) {
  statusEl.classList.remove("hidden", "error");
  for (;;) {
    const rec = await fetch(`/api/recordings/${id}`).then((r) => r.json());
    if (rec.status === "done") {
      statusEl.classList.add("hidden");
      renderRecording(resultEl, rec);
      return;
    }
    if (rec.status === "error") {
      statusEl.classList.add("error");
      statusEl.textContent = `Failed: ${rec.error}`;
      if (rec.transcript && rec.transcript.length) renderRecording(resultEl, rec);
      return;
    }
    statusEl.textContent = rec.transcript && rec.transcript.length
      ? "Transcribed — generating structured context…"
      : "Transcribing with speaker detection…";
    await new Promise((res) => setTimeout(res, 2000));
  }
}

// ---------- upload tab ----------
const dropzone = document.getElementById("dropzone");
const fileInput = document.getElementById("file-input");
const uploadStatus = document.getElementById("upload-status");
const uploadResult = document.getElementById("upload-result");

dropzone.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => fileInput.files[0] && uploadFile(fileInput.files[0]));
dropzone.addEventListener("dragover", (e) => { e.preventDefault(); dropzone.classList.add("dragover"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
dropzone.addEventListener("drop", (e) => {
  e.preventDefault();
  dropzone.classList.remove("dragover");
  if (e.dataTransfer.files[0]) uploadFile(e.dataTransfer.files[0]);
});

async function uploadFile(file) {
  uploadResult.classList.add("hidden");
  uploadResult.innerHTML = "";
  uploadStatus.classList.remove("hidden", "error");
  uploadStatus.textContent = `Uploading ${file.name}…`;

  const form = new FormData();
  form.append("file", file);
  try {
    const resp = await fetch("/api/recordings", { method: "POST", body: form });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const { id } = await resp.json();
    await pollRecording(id, uploadStatus, uploadResult);
  } catch (err) {
    uploadStatus.classList.add("error");
    uploadStatus.textContent = `Upload failed: ${err.message}`;
  }
}

// ---------- live tab ----------
const liveToggle = document.getElementById("live-toggle");
const liveEnd = document.getElementById("live-end");
const liveIndicator = document.getElementById("live-indicator");
const liveTranscript = document.getElementById("live-transcript");
const liveStatus = document.getElementById("live-status");
const liveResult = document.getElementById("live-result");

let ws = null;
let recorder = null;
let micStream = null;
let finalSegments = [];
let interimNode = null;

liveToggle.addEventListener("click", () => (recorder ? stopListening() : startListening()));
liveEnd.addEventListener("click", endSession);

async function startListening() {
  liveResult.classList.add("hidden");
  liveResult.innerHTML = "";
  liveStatus.classList.add("hidden");
  if (!finalSegments.length) liveTranscript.innerHTML = "";

  try {
    micStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  } catch {
    showLiveError("Microphone access denied. Allow mic access and try again.");
    return;
  }

  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws/live`);
  ws.onmessage = (e) => handleLiveEvent(JSON.parse(e.data));
  ws.onerror = () => showLiveError("Connection error — check the server logs.");
  ws.onopen = () => {
    recorder = new MediaRecorder(micStream, { mimeType: "audio/webm;codecs=opus" });
    recorder.ondataavailable = (e) => {
      if (e.data.size > 0 && ws && ws.readyState === WebSocket.OPEN) ws.send(e.data);
    };
    recorder.start(250); // ~250ms chunks
    liveToggle.textContent = "⏸ Stop listening";
    liveToggle.classList.add("recording");
    liveIndicator.classList.remove("hidden");
    liveEnd.disabled = false;
  };
}

function handleLiveEvent(event) {
  if (event.type === "error") {
    showLiveError(event.message);
    stopListening();
    return;
  }
  if (interimNode) { interimNode.remove(); interimNode = null; }
  if (event.type === "final") {
    finalSegments.push(event);
    liveTranscript.appendChild(segmentNode(event));
  } else {
    interimNode = segmentNode(event, true);
    liveTranscript.appendChild(interimNode);
  }
  liveTranscript.scrollTop = liveTranscript.scrollHeight;
}

function stopListening() {
  if (recorder && recorder.state !== "inactive") recorder.stop();
  recorder = null;
  if (micStream) { micStream.getTracks().forEach((t) => t.stop()); micStream = null; }
  if (ws) { ws.close(); ws = null; }
  if (interimNode) { interimNode.remove(); interimNode = null; }
  liveToggle.textContent = "🎤 Start listening";
  liveToggle.classList.remove("recording");
  liveIndicator.classList.add("hidden");
}

async function endSession() {
  stopListening();
  liveEnd.disabled = true;
  if (!finalSegments.length) {
    showLiveError("Nothing was transcribed in this session.");
    return;
  }
  const segments = finalSegments;
  finalSegments = [];
  const duration = segments[segments.length - 1].end || 0;

  liveStatus.classList.remove("hidden", "error");
  liveStatus.textContent = "Saving session and generating structured context…";
  try {
    const resp = await fetch("/api/recordings/live", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ duration, segments }),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);
    const { id } = await resp.json();
    await pollRecording(id, liveStatus, liveResult);
  } catch (err) {
    showLiveError(`Failed to save session: ${err.message}`);
  }
}

function showLiveError(msg) {
  liveStatus.classList.remove("hidden");
  liveStatus.classList.add("error");
  liveStatus.textContent = msg;
}

// ---------- library tab ----------
const libraryList = document.getElementById("library-list");
const libraryDetail = document.getElementById("library-detail");

async function loadLibrary() {
  libraryDetail.classList.add("hidden");
  libraryDetail.innerHTML = "";
  libraryList.classList.remove("hidden");
  const recs = await fetch("/api/recordings").then((r) => r.json());
  libraryList.innerHTML = "";
  if (!recs.length) {
    libraryList.appendChild(el("p", "muted", "No recordings yet — upload a file or run a live session."));
    return;
  }
  recs.forEach((rec) => {
    const item = el("div", "item");
    const left = el("div");
    left.appendChild(el("div", null, rec.title));
    left.appendChild(
      el("div", "meta", `${rec.source} · ${new Date(rec.created_at).toLocaleString()} · ${fmtTime(rec.duration)}`)
    );
    item.appendChild(left);
    item.appendChild(el("span", `pill ${rec.status}`, rec.status));
    item.addEventListener("click", () => openRecording(rec.id));
    libraryList.appendChild(item);
  });
}

async function openRecording(id) {
  const rec = await fetch(`/api/recordings/${id}`).then((r) => r.json());
  libraryList.classList.add("hidden");
  libraryDetail.innerHTML = "";
  const back = el("button", "back-btn", "← Back to library");
  back.addEventListener("click", loadLibrary);
  libraryDetail.appendChild(back);
  if (rec.transcript && rec.transcript.length) {
    const chatBtn = el("button", "back-btn", "💬 Chat about this recording");
    chatBtn.style.marginLeft = "16px";
    chatBtn.addEventListener("click", () => openChatFor(id));
    libraryDetail.appendChild(chatBtn);
  }
  if (rec.status === "error") {
    const errBox = el("div", "status error", `Processing failed: ${rec.error}`);
    errBox.classList.remove("hidden");
    libraryDetail.appendChild(errBox);
  }
  const body = el("div");
  libraryDetail.appendChild(body);
  renderRecording(body, rec);
  libraryDetail.classList.remove("hidden");
}

// ---------- chat tab ----------
const chatSelect = document.getElementById("chat-recording");
const chatThread = document.getElementById("chat-thread");
const chatForm = document.getElementById("chat-form");
const chatText = document.getElementById("chat-text");
const chatSend = document.getElementById("chat-send");

const chatHistories = {}; // recording id -> [{role, content}, ...]
let chatStreaming = false;

async function loadChatRecordings(preselectId) {
  const recs = await fetch("/api/recordings").then((r) => r.json());
  const usable = recs.filter((r) => r.status !== "processing");
  const current = preselectId || chatSelect.value;
  chatSelect.innerHTML = "";
  if (!usable.length) {
    chatSelect.appendChild(new Option("No recordings yet — upload or record one first", ""));
    chatSelect.disabled = true;
    chatText.disabled = true;
    chatSend.disabled = true;
    return;
  }
  chatSelect.disabled = false;
  chatText.disabled = false;
  chatSend.disabled = false;
  usable.forEach((r) => {
    chatSelect.appendChild(new Option(`${r.title} (${new Date(r.created_at).toLocaleDateString()})`, r.id));
  });
  if (current && usable.some((r) => r.id === current)) chatSelect.value = current;
  renderChatThread();
}

function openChatFor(id) {
  switchTab("chat");
  loadChatRecordings(id);
}

chatSelect.addEventListener("change", renderChatThread);

function chatBubble(role, text, pending = false) {
  const row = el("div", `msg ${role}`);
  const bubble = el("div", `bubble${pending ? " pending" : ""}`, text);
  row.appendChild(bubble);
  chatThread.appendChild(row);
  chatThread.scrollTop = chatThread.scrollHeight;
  return bubble;
}

function renderChatThread() {
  chatThread.innerHTML = "";
  const history = chatHistories[chatSelect.value] || [];
  history.forEach((m) => chatBubble(m.role, m.content));
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const question = chatText.value.trim();
  const recId = chatSelect.value;
  if (!question || !recId || chatStreaming) return;

  const history = (chatHistories[recId] = chatHistories[recId] || []);
  history.push({ role: "user", content: question });
  chatBubble("user", question);
  chatText.value = "";

  chatStreaming = true;
  chatSend.disabled = true;
  const bubble = chatBubble("assistant", "", true);
  try {
    const resp = await fetch(`/api/recordings/${recId}/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    if (!resp.ok) throw new Error((await resp.json()).detail || resp.statusText);

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let answer = "";
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      answer += decoder.decode(value, { stream: true });
      bubble.textContent = answer;
      chatThread.scrollTop = chatThread.scrollHeight;
    }
    history.push({ role: "assistant", content: answer || "(no response)" });
    bubble.textContent = answer || "(no response)";
  } catch (err) {
    history.pop(); // let the user retry the question
    bubble.textContent = `Error: ${err.message}`;
  } finally {
    bubble.classList.remove("pending");
    chatStreaming = false;
    chatSend.disabled = false;
    chatText.focus();
  }
});
