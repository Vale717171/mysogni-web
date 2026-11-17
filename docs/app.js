"use strict";

const STORAGE_KEY = "mysogni-web-settings";
const POLL_MS = 4000;

const $ = (id) => document.getElementById(id);

function loadSettings() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || {};
  } catch {
    return {};
  }
}

function saveSettings(settings) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
    return true;
  } catch {
    return false;
  }
}

let settings = loadSettings();

function apiBase() {
  return (settings.apiUrl || "").replace(/\/+$/, "");
}

function authHeaders() {
  return { "Modal-Key": settings.modalKey || "", "Modal-Secret": settings.modalSecret || "" };
}

function configured() {
  return Boolean(apiBase() && settings.modalKey && settings.modalSecret);
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(apiBase() + path, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
    });
  } catch {
    throw new Error(
      "Connessione non riuscita. Controlla indirizzo e token; se sono giusti, il blocco è probabilmente il CORS."
    );
  }
  if (response.status === 401 || response.status === 403) {
    throw new Error("Token rifiutato: controlla Token ID e secret.");
  }
  if (!response.ok) {
    let detail = "";
    try { detail = (await response.json()).detail || ""; } catch { /* corpo non JSON */ }
    throw new Error(`Errore ${response.status}${detail ? ": " + detail : ""}`);
  }
  return response;
}

// --- Impostazioni ---

function fillSettingsForm() {
  $("api-url").value = settings.apiUrl || "";
  $("modal-key").value = settings.modalKey || "";
  $("modal-secret").value = settings.modalSecret || "";
}

function setStatus(element, text, isError = false) {
  element.textContent = text;
  element.classList.toggle("error", isError);
}

$("toggle-settings").addEventListener("click", () => {
  $("settings").hidden = !$("settings").hidden;
});

$("save-settings").addEventListener("click", () => {
  settings = {
    apiUrl: $("api-url").value.trim(),
    modalKey: $("modal-key").value.trim(),
    modalSecret: $("modal-secret").value.trim(),
  };
  const ok = saveSettings(settings);
  setStatus(
    $("settings-status"),
    ok ? "Salvate." : "Salvate solo per questa sessione: il browser non permette di memorizzarle.",
    !ok
  );
});

$("test-settings").addEventListener("click", async () => {
  const status = $("settings-status");
  if (!configured()) {
    setStatus(status, "Compila e salva prima tutti e tre i campi.", true);
    return;
  }
  setStatus(status, "Provo…");
  try {
    const data = await (await api("/health")).json();
    setStatus(status, data.fake_worker ? "Connesso. Worker di prova attivo: nessuna GPU in uso." : "Connesso.");
  } catch (error) {
    setStatus(status, error.message, true);
  }
});

// --- Lavori ---

function addJobCard(job) {
  $("empty").hidden = true;
  const item = document.createElement("li");
  item.className = "job";
  const meta = document.createElement("div");
  meta.className = "meta";
  const prompt = document.createElement("div");
  prompt.className = "prompt";
  prompt.textContent = job.prompt;
  const body = document.createElement("div");
  item.append(meta, prompt, body);
  $("jobs").prepend(item);
  return { item, meta, body };
}

function renderMeta(card, job, text) {
  card.meta.textContent = `${job.duration} s · ${job.model} · ${text}`;
}

async function showVideo(card, jobId) {
  const response = await api(`/jobs/${encodeURIComponent(jobId)}/video`);
  const url = URL.createObjectURL(await response.blob());
  const video = document.createElement("video");
  video.src = url;
  video.controls = true;
  video.playsInline = true;
  const link = document.createElement("a");
  link.href = url;
  link.download = `mysogni-${jobId}.mp4`;
  link.textContent = "Scarica il video";
  card.body.replaceChildren(video, link);
}

async function poll(card, job, jobId, started) {
  try {
    const data = await (await api(`/jobs/${encodeURIComponent(jobId)}`)).json();
    const elapsed = Math.round((Date.now() - started) / 1000);
    if (data.status === "running") {
      renderMeta(card, job, `in corso, ${elapsed} s`);
      setTimeout(() => poll(card, job, jobId, started), POLL_MS);
      return;
    }
    if (data.status === "done") {
      const worker = data.timings ? `, worker ${data.timings.total_s} s` : "";
      renderMeta(card, job, `pronto in ${elapsed} s${worker}${data.fake ? " · video di prova" : ""}`);
      await showVideo(card, jobId);
      return;
    }
    renderMeta(card, job, data.status === "expired" ? "scaduto" : "errore");
    const error = document.createElement("p");
    error.className = "error";
    error.textContent = data.error ? `Errore nel worker: ${data.error}` : "Il lavoro non è più disponibile.";
    card.body.replaceChildren(error);
  } catch (error) {
    renderMeta(card, job, "errore");
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = error.message;
    card.body.replaceChildren(message);
  }
}

$("job-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!configured()) {
    $("settings").hidden = false;
    setStatus($("settings-status"), "Prima inserisci indirizzo e token.", true);
    return;
  }
  const job = {
    prompt: $("prompt").value.trim(),
    duration: Number($("duration").value),
    model: $("model").value,
    backend: $("backend").value,
  };
  if (!job.prompt) return;

  const submit = $("submit");
  submit.disabled = true;
  const card = addJobCard(job);
  renderMeta(card, job, "invio…");
  try {
    const response = await api("/jobs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(job),
    });
    const data = await response.json();
    renderMeta(card, job, "in coda");
    poll(card, job, data.job_id, Date.now());
  } catch (error) {
    renderMeta(card, job, "errore");
    const message = document.createElement("p");
    message.className = "error";
    message.textContent = error.message;
    card.body.replaceChildren(message);
  } finally {
    submit.disabled = false;
  }
});

fillSettingsForm();
if (!configured()) $("settings").hidden = false;
