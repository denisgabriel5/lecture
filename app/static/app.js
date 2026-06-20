/* =====================================================================
   Lecture front-end — vanilla JS, no framework.
   State is minimal: jobs + voices fetched from the API.
   ===================================================================== */

"use strict";

// ── State ─────────────────────────────────────────────────────────────
let _jobs  = [];
let _voices = [];
let _pollTimer = null;
let _selectedFile = null;
let _online = true;

// ── Helpers ───────────────────────────────────────────────────────────
const $ = (id) => document.getElementById(id);

function fmtTime(iso) {
  const d = new Date(iso);
  const now = new Date();
  const diff = (now - d) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return d.toLocaleDateString();
}

function fmtProgress(job) {
  if (!job.total_chunks) return "0 / ?";
  return `${job.done_chunks} / ${job.total_chunks}`;
}

function pct(job) {
  if (!job.total_chunks) return 0;
  return Math.round((job.done_chunks / job.total_chunks) * 100);
}

function setOnline(online) {
  _online = online;
  $("offline-banner").classList.toggle("hidden", online);
}

// ── API ───────────────────────────────────────────────────────────────
async function apiFetch(path, options) {
  try {
    const res = await fetch(path, options);
    if (!res.ok) {
      const body = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(body.detail ?? body.error ?? `HTTP ${res.status}`);
    }
    setOnline(true);
    return res;
  } catch (err) {
    if (err.message === "Failed to fetch" || err instanceof TypeError) {
      setOnline(false);
    }
    throw err;
  }
}

async function fetchJobs() {
  const res = await apiFetch("/api/jobs");
  return res.json();
}

async function fetchVoices() {
  const res = await apiFetch("/api/voices");
  return res.json();
}

async function deleteJob(id) {
  await apiFetch(`/api/jobs/${id}`, { method: "DELETE" });
}

// ── Polling ───────────────────────────────────────────────────────────
function hasActiveJobs(jobs) {
  return jobs.some((j) => j.status === "queued" || j.status === "processing");
}

async function poll() {
  try {
    const jobs = await fetchJobs();
    _jobs = jobs;
    renderJobs();
    if (!hasActiveJobs(jobs)) stopPolling();
  } catch (_) {
    // setOnline(false) handled inside apiFetch
  }
}

function startPolling() {
  if (_pollTimer) return;
  _pollTimer = setInterval(poll, 4000);
}

function stopPolling() {
  if (!_pollTimer) return;
  clearInterval(_pollTimer);
  _pollTimer = null;
}

// ── Rendering ─────────────────────────────────────────────────────────
function renderBadge(status) {
  const labels = { queued: "Queued", processing: "Processing", done: "Done", failed: "Failed" };
  return `<span class="job-badge badge-${status}">${labels[status] ?? status}</span>`;
}

function renderProgress(job) {
  if (job.status !== "processing" && job.status !== "done") return "";
  const p = job.status === "done" ? 100 : pct(job);
  const label = job.status === "done" ? "100 %" : `${fmtProgress(job)} chunks`;
  return `
    <div class="progress-wrap">
      <div class="progress-bar"><div class="progress-fill" style="width:${p}%"></div></div>
      <span class="progress-label">${label}</span>
    </div>
    ${job.current_chunk ? `<div class="chunk-preview">${escHtml(job.current_chunk)}…</div>` : ""}
  `;
}

function renderAudio(job) {
  if (job.status !== "done") return "";
  const src = `/api/jobs/${job.id}/audio`;
  const name = job.filename.replace(/\.pdf$/i, "");
  return `
    <div class="audio-section">
      <div class="audio-actions">
        <button class="btn-secondary btn-sm" id="btn-play-${job.id}"
          onclick="togglePlayer('${job.id}','${escAttr(src)}')">
          <svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><polygon points="5 3 19 12 5 21 5 3"/></svg>
          Play
        </button>
        <button class="btn-secondary btn-sm" onclick="downloadAudio('${job.id}','${escAttr(name)}')">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
          Download
        </button>
      </div>
      <audio class="inline-player hidden" id="player-${job.id}" preload="none" controls
        src="${src}"></audio>
    </div>
  `;
}

function escHtml(s) {
  return String(s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
function escAttr(s) { return escHtml(s); }

function renderCounter(jobs) {
  const counter = $("job-counter");
  if (!jobs.length) { counter.classList.add("hidden"); return; }

  const total      = jobs.length;
  const processing = jobs.filter(j => j.status === "queued" || j.status === "processing").length;
  const done       = jobs.filter(j => j.status === "done").length;
  const failed     = jobs.filter(j => j.status === "failed").length;

  const parts = [`<span>${total} ${total === 1 ? "job" : "jobs"}</span>`];
  if (processing) parts.push(`<span class="cnt-sep">·</span><span class="cnt-processing">${processing} processing</span>`);
  if (done)       parts.push(`<span class="cnt-sep">·</span><span class="cnt-done">${done} done</span>`);
  if (failed)     parts.push(`<span class="cnt-sep">·</span><span class="cnt-failed">${failed} failed</span>`);

  counter.innerHTML = parts.join("");
  counter.classList.remove("hidden");
}

function renderJobs() {
  const list = $("job-list");
  const empty = $("empty-state");

  renderCounter(_jobs);

  if (!_jobs.length) {
    empty.classList.remove("hidden");
    list.innerHTML = "";
    return;
  }
  empty.classList.add("hidden");

  list.innerHTML = _jobs.map((job) => {
    const cls = job.status === "done" ? " done" : job.status === "failed" ? " failed" : "";
    return `
      <li class="job-card${cls}" data-id="${job.id}">
        <div class="job-top">
          <div class="job-meta">
            <div class="job-filename" title="${escAttr(job.filename)}">${escHtml(job.filename)}</div>
            <div class="job-info">${job.language.toUpperCase()} · ${job.voice} · ${fmtTime(job.created_at)}</div>
          </div>
          <div style="display:flex;align-items:center;gap:.5rem">
            ${renderBadge(job.status)}
            <button class="btn-icon btn-sm" onclick="handleDelete('${job.id}')" aria-label="Delete job" title="Delete">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                <polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/>
                <path d="M9 6V4h6v2"/>
              </svg>
            </button>
          </div>
        </div>
        ${renderProgress(job)}
        ${job.error ? `<div class="job-error">${escHtml(job.error)}</div>` : ""}
        ${renderAudio(job)}
      </li>
    `;
  }).join("");
}

// _voices is a list of { id, label, default } from the API.
function populateVoiceSelect() {
  const sel = $("voice-select");
  if (!_voices.length) {
    sel.innerHTML = `<option value="" disabled selected>— no voices —</option>`;
    updateSubmitState();
    return;
  }
  const saved = localStorage.getItem("voice");
  const def = (_voices.find((v) => v.default) || _voices[0]).id;
  const want = _voices.some((v) => v.id === saved) ? saved : def;

  sel.innerHTML = _voices
    .map((v) => `<option value="${escAttr(v.id)}">${escHtml(v.label)}</option>`)
    .join("");
  sel.value = want;
  updateSubmitState();
}

// ── Actions ───────────────────────────────────────────────────────────
async function handleDelete(id) {
  try {
    await deleteJob(id);
    _jobs = _jobs.filter((j) => j.id !== id);
    renderJobs();
    if (!hasActiveJobs(_jobs)) stopPolling();
  } catch (e) {
    alert("Could not delete job: " + e.message);
  }
}

function togglePlayer(jobId, src) {
  const audio = $(`player-${jobId}`);
  const btn   = $(`btn-play-${jobId}`);
  const isHidden = audio.classList.contains("hidden");

  if (isHidden) {
    audio.classList.remove("hidden");
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><rect x="6" y="4" width="4" height="16"/><rect x="14" y="4" width="4" height="16"/></svg> Pause`;
    audio.focus();
  } else {
    audio.classList.add("hidden");
    audio.pause();
    btn.innerHTML = `<svg viewBox="0 0 24 24" fill="currentColor" width="14" height="14"><polygon points="5 3 19 12 5 21 5 3"/></svg> Play`;
  }
}

async function downloadAudio(jobId, name) {
  const url = `/api/jobs/${jobId}/audio`;
  try {
    const res = await apiFetch(url);
    const blob = await res.blob();
    const file = new File([blob], `${name}.mp3`, { type: "audio/mpeg" });
    if (navigator.canShare && navigator.canShare({ files: [file] })) {
      await navigator.share({ files: [file], title: name });
      return;
    }
    // Fallback: blob-URL anchor download
    const burl = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = burl; a.download = `${name}.mp3`;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    setTimeout(() => URL.revokeObjectURL(burl), 5000);
  } catch (e) {
    if (e.name !== "AbortError") alert("Download failed: " + e.message);
  }
}

// ── Theme ─────────────────────────────────────────────────────────────
function applyTheme(theme) {
  if (theme === "dark" || theme === "light") {
    document.documentElement.setAttribute("data-theme", theme);
  } else {
    document.documentElement.removeAttribute("data-theme");
  }
  localStorage.setItem("theme", theme);
  document.querySelectorAll(".theme-btn").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.theme === theme);
  });
}

function initTheme() {
  const saved = localStorage.getItem("theme") ?? "";
  applyTheme(saved);
}

// ── Upload modal ──────────────────────────────────────────────────────
function openUploadModal() {
  _selectedFile = null;
  $("drop-label").textContent = "Tap to choose a PDF";
  $("drop-zone").classList.remove("selected");
  $("upload-error").classList.add("hidden");
  updateSubmitState();
  $("upload-modal").classList.remove("hidden");
}

function closeUploadModal() {
  stopSample();
  $("upload-modal").classList.add("hidden");
}

function updateSubmitState() {
  const hasFile = !!_selectedFile;
  const hasVoice = !!$("voice-select").value;
  $("btn-submit").disabled = !(hasFile && hasVoice);
}

function selectFile(file) {
  if (!file || !file.name.toLowerCase().endsWith(".pdf")) {
    showUploadError("Please choose a PDF file.");
    return;
  }
  _selectedFile = file;
  $("drop-label").textContent = file.name;
  $("drop-zone").classList.add("selected");
  $("upload-error").classList.add("hidden");
  updateSubmitState();
}

function showUploadError(msg) {
  const el = $("upload-error");
  el.textContent = msg;
  el.classList.remove("hidden");
}

// ── Voice sample preview ──────────────────────────────────────────────
function setSampleBtn(playing) {
  const btn = $("btn-sample");
  btn.classList.toggle("playing", playing);
  btn.querySelector(".ic-play").classList.toggle("hidden", playing);
  btn.querySelector(".ic-stop").classList.toggle("hidden", !playing);
}

function stopSample() {
  const audio = $("sample-audio");
  audio.pause();
  audio.currentTime = 0;
  setSampleBtn(false);
}

function toggleSample() {
  const audio = $("sample-audio");
  const voice = $("voice-select").value;
  if (!voice) return;
  if (!audio.paused) { stopSample(); return; }
  audio.src = `/samples/${encodeURIComponent(voice)}.mp3`;
  audio.play().then(() => setSampleBtn(true)).catch(() => setSampleBtn(false));
}

async function submitJob() {
  if (!_selectedFile) return;
  const voice = $("voice-select").value;
  const language = $("lang-select").value;
  if (!voice) { showUploadError("Select a voice first."); return; }

  $("btn-submit").disabled = true;
  $("btn-submit").textContent = "Uploading…";

  const fd = new FormData();
  fd.append("file", _selectedFile);
  fd.append("language", language);
  fd.append("voice", voice);

  try {
    const res = await apiFetch("/api/jobs", { method: "POST", body: fd });
    const job = await res.json();
    _jobs = [job, ..._jobs];
    renderJobs();
    startPolling();
    closeUploadModal();
    localStorage.setItem("language", language);
    localStorage.setItem("voice", voice);
  } catch (e) {
    showUploadError(e.message);
  } finally {
    $("btn-submit").disabled = false;
    $("btn-submit").textContent = "Start";
  }
}

// ── Initialisation ────────────────────────────────────────────────────
async function init() {
  initTheme();

  // Theme buttons
  document.querySelectorAll(".theme-btn").forEach((btn) => {
    btn.addEventListener("click", () => applyTheme(btn.dataset.theme));
  });

  // Restore saved preferences
  const savedLang = localStorage.getItem("language");
  if (savedLang) $("lang-select").value = savedLang;

  try {
    [_jobs, _voices] = await Promise.all([fetchJobs(), fetchVoices()]);
    renderJobs();
    populateVoiceSelect();
    if (hasActiveJobs(_jobs)) startPolling();
  } catch (_) {
    renderJobs();
  }

  // ── Event wiring ────────────────────────────────────────────────────
  $("btn-upload").addEventListener("click", openUploadModal);
  $("btn-close-upload").addEventListener("click", closeUploadModal);

  // Close modal on backdrop click
  $("upload-modal").addEventListener("click", (e) => {
    if (e.target === $("upload-modal")) closeUploadModal();
  });

  // File input (tap)
  const dropZone = $("drop-zone");
  const fileInput = $("file-input");

  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") fileInput.click();
  });
  fileInput.addEventListener("change", () => {
    if (fileInput.files[0]) selectFile(fileInput.files[0]);
  });

  // Drag-and-drop (desktop / iPadOS Files drag)
  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("drag-over");
  });
  dropZone.addEventListener("dragleave", () => dropZone.classList.remove("drag-over"));
  dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) selectFile(e.dataTransfer.files[0]);
  });

  $("voice-select").addEventListener("change", () => { stopSample(); updateSubmitState(); });
  $("btn-submit").addEventListener("click", submitJob);

  // Voice sample preview
  $("btn-sample").addEventListener("click", toggleSample);
  $("sample-audio").addEventListener("ended", () => setSampleBtn(false));

  // Keyboard: Escape closes modal
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      stopSample();
      closeUploadModal();
    }
  });

  // Visibility: resume polling when tab comes back to foreground
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && hasActiveJobs(_jobs)) {
      poll(); // immediate catch-up
      startPolling();
    }
  });
}

document.addEventListener("DOMContentLoaded", init);
