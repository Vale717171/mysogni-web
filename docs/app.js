"use strict";

const STORAGE_KEY = "mysogni-web-settings";
const POLL_MS = 4000;
const DEFAULT_API = "https://valentinoricco--mysogni-web-api.us-east.modal.run";

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

// Link di configurazione: https://vale717171.github.io/mysogni-web/#token=<TOKEN>[&api=<URL>]
// La parte dopo "#" non viene inviata a nessun server; la togliamo subito dalla barra degli indirizzi.
function applySetupLink() {
  if (!location.hash.includes("token=")) return null;
  const params = {};
  for (const pair of location.hash.slice(1).split("&")) {
    const i = pair.indexOf("=");
    if (i > 0) {
      try {
        params[pair.slice(0, i)] = decodeURIComponent(pair.slice(i + 1));
      } catch {
        // parametro malformato: ignorato
      }
    }
  }
  history.replaceState(null, "", location.pathname + location.search);
  if (!params.token) return null;
  settings = { ...settings, apiToken: params.token.trim(), apiUrl: params.api || settings.apiUrl || DEFAULT_API };
  return saveSettings(settings);
}

const setupResult = applySetupLink();

function apiBase() {
  return (settings.apiUrl || "").replace(/\/+$/, "");
}

function authHeaders() {
  return { Authorization: `Bearer ${settings.apiToken || ""}` };
}

function configured() {
  return Boolean(apiBase() && settings.apiToken);
}

async function api(path, options = {}) {
  let response;
  try {
    response = await fetch(apiBase() + path, {
      ...options,
      headers: { ...authHeaders(), ...(options.headers || {}) },
    });
  } catch {
    const error = new Error("Connessione non riuscita: controlla l'indirizzo del backend.");
    error.status = 0;
    throw error;
  }
  if (response.status === 401 || response.status === 403) {
    const error = new Error("Token rifiutato: controlla il token di accesso.");
    error.status = response.status;
    throw error;
  }
  if (!response.ok) {
    let detail = "";
    try { detail = (await response.json()).detail || ""; } catch { /* corpo non JSON */ }
    const text = typeof detail === "object" && detail ? detail.message || "" : detail;
    const error = new Error(`Errore ${response.status}${text ? ": " + text : ""}`);
    error.status = response.status;
    if (typeof detail === "object" && detail) error.detail = detail;
    throw error;
  }
  return response;
}

// --- Impostazioni ---

function fillSettingsForm() {
  $("api-url").value = settings.apiUrl || "";
  $("api-token").value = settings.apiToken || "";
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
    apiToken: $("api-token").value.trim(),
  };
  const ok = saveSettings(settings);
  setStatus(
    $("settings-status"),
    ok ? "Salvate." : "Salvate solo per questa sessione: il browser non permette di memorizzarle.",
    !ok
  );
  loadModels();
});

$("copy-setup-link").addEventListener("click", async () => {
  const status = $("settings-status");
  if (!configured()) {
    setStatus(status, "Salva prima indirizzo e token.", true);
    return;
  }
  const base = location.origin + location.pathname;
  let link = `${base}#token=${encodeURIComponent(settings.apiToken)}`;
  if (apiBase() !== DEFAULT_API) link += `&api=${encodeURIComponent(apiBase())}`;

  // Il link resta visibile nel campo qui sotto: se la copia automatica fallisce, si copia a mano.
  const field = $("setup-link");
  field.value = link;
  $("setup-link-field").hidden = false;
  field.focus();
  field.select();

  let copied = false;
  try {
    await navigator.clipboard.writeText(link);
    copied = true;
  } catch {
    try {
      copied = document.execCommand("copy");
    } catch {
      copied = false;
    }
  }
  setStatus(
    status,
    copied
      ? "Link copiato negli appunti. Contiene il token: conservalo nel password manager."
      : "Copia automatica non riuscita: il link è selezionato qui sotto, copialo con Ctrl+C (Cmd+C su Mac).",
    !copied
  );
});

$("test-settings").addEventListener("click", async () => {
  const status = $("settings-status");
  if (!configured()) {
    setStatus(status, "Compila e salva prima entrambi i campi.", true);
    return;
  }
  setStatus(status, "Provo…");
  try {
    const data = await (await api("/health")).json();
    setStatus(status, data.gpu_enabled ? "Connesso. GPU abilitata." : "Connesso. GPU non abilitata: solo video di prova.");
    await loadModels();
  } catch (error) {
    setStatus(status, error.message, true);
  }
});

// --- Modelli ---

let models = [];

function fillSelect(id, values, label) {
  $(id).replaceChildren(
    ...values.map((value, i) => {
      const option = document.createElement("option");
      option.value = String(value.id ?? value);
      option.textContent = label(value, i);
      return option;
    })
  );
}

function updateOptionFields() {
  const model = models.find((m) => m.id === $("model").value);
  const profile = model && model.profiles ? model.profiles.find((p) => p.id === $("profile").value) : null;
  const scope = profile || model;
  const resolutions = scope ? scope.resolutions || [] : [];
  const previous = $("resolution").value;
  $("resolution-field").hidden = resolutions.length === 0;
  fillSelect("resolution", resolutions, (r) => r.replace("x", "×"));
  if (resolutions.includes(previous)) $("resolution").value = previous;
  const m3 = scope && scope.m3 ? scope.m3 : [];
  $("m3-field").hidden = m3.length === 0;
  fillSelect("m3", m3, (value, i) =>
    value === 0 ? "spenta" : value.toFixed(1).replace(".", ",") + (i === 0 ? " (predefinita)" : "")
  );
}

function updateModelFields() {
  const model = models.find((m) => m.id === $("model").value);
  const profiles = model && model.profiles ? model.profiles : [];
  $("profile-field").hidden = profiles.length === 0;
  fillSelect("profile", profiles, (p, i) => p.label + (i === 0 ? " (predefinito)" : ""));
  const steps = model && model.steps ? model.steps : [];
  $("steps-field").hidden = steps.length === 0;
  fillSelect("steps", steps, (n, i) => `${n} step` + (i === 0 ? " (predefinito)" : ""));
  updateOptionFields();
  $("model-note").textContent = model ? model.note : "";
}

async function loadModels() {
  if (!configured()) return;
  try {
    const data = await (await api("/health")).json();
    models = data.models || [];
    const select = $("model");
    const current = select.value;
    select.replaceChildren(
      ...models.map((m) => {
        const option = document.createElement("option");
        option.value = m.id;
        option.textContent = m.label;
        return option;
      })
    );
    // Finché l'utente non sceglie, si propone il primo modello dell'elenco (il più adatto secondo il backend).
    if (select.dataset.touched && models.some((m) => m.id === current)) select.value = current;
    else if (models.length) select.value = models[0].id;
    updateModelFields();
    const writer = data.screenwriter || {};
    $("screenwriter").hidden = !writer.enabled;
    $("write-prompt").title = writer.model ? `Modello: ${writer.model}, zero data retention` : "";
  } catch {
    // La pagina resta utilizzabile con il solo video di prova.
  }
}

$("profile").addEventListener("change", updateOptionFields);

$("model").addEventListener("change", () => {
  $("model").dataset.touched = "1";
  updateModelFields();
});

// --- Screenwriter ---

let writtenFor = null; // durata per cui è stato scritto il prompt attuale

function checkPromptDuration() {
  const duration = Number($("duration").value);
  if (writtenFor !== null && writtenFor !== duration) {
    setStatus(
      $("screenwriter-status"),
      `Il prompt è scritto per ${writtenFor} s: premi di nuovo "Scrivi il prompt H3" per adattarlo a ${duration} s.`,
      true
    );
  } else if (writtenFor !== null) {
    setStatus($("screenwriter-status"), `Prompt scritto per ${writtenFor} s. Puoi correggerlo a mano prima di generare.`);
  }
}

$("duration").addEventListener("change", checkPromptDuration);

$("write-prompt").addEventListener("click", async () => {
  const status = $("screenwriter-status");
  const idea = $("idea").value.trim();
  if (!idea) {
    setStatus(status, "Scrivi prima l'idea.", true);
    return;
  }
  const duration = Number($("duration").value);
  const button = $("write-prompt");
  button.disabled = true;
  setStatus(status, `Lo screenwriter sta scrivendo per ${duration} s…`);
  try {
    const response = await api("/screenwriter", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ idea, duration }),
    });
    const data = await response.json();
    $("prompt").value = data.prompt;
    writtenFor = data.duration;
    checkPromptDuration();
  } catch (error) {
    let message = error.message;
    if (error.detail && error.detail.raw) {
      // Mostra cosa ha restituito il modello: si può correggere a mano invece di perderlo.
      $("prompt").value = error.detail.raw;
      writtenFor = null;
      message += ` (fine: ${error.detail.finish_reason || "?"}). La risposta grezza è nel campo Prompt: controllala prima di generare.`;
    }
    setStatus(status, message, true);
  } finally {
    button.disabled = false;
  }
});

// --- Lavori ---
// I lavori restano in memoria nel browser (ultimi 20, al massimo 7 giorni, come i video su Modal):
// dopo un ricaricamento la pagina riprende a seguirli invece di perderli.

const JOBS_KEY = "mysogni-web-jobs";
const MAX_JOBS = 20;
const KEEP_MS = 7 * 24 * 3600 * 1000;
const RETRY_MS = 6000;
const GIVE_UP_MS = 15 * 60 * 1000; // dopo 15 minuti senza risposte dal router si smette di riprovare

function loadJobs() {
  try {
    const list = JSON.parse(localStorage.getItem(JOBS_KEY) || "[]");
    return Array.isArray(list) ? list.filter((j) => j && j.id && Date.now() - j.started < KEEP_MS) : [];
  } catch {
    return [];
  }
}

function saveJob(record) {
  try {
    const list = loadJobs().filter((j) => j.id !== record.id);
    list.unshift(record);
    localStorage.setItem(JOBS_KEY, JSON.stringify(list.slice(0, MAX_JOBS)));
  } catch {
    // memoria del browser non disponibile: il lavoro resta solo in questa scheda
  }
}

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

function showError(card, text) {
  const message = document.createElement("p");
  message.className = "error";
  message.textContent = text;
  card.body.replaceChildren(message);
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

function offerVideo(card, jobId) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "secondary";
  button.textContent = "Mostra il video";
  button.addEventListener("click", async () => {
    button.disabled = true;
    try {
      await showVideo(card, jobId);
    } catch (error) {
      showError(card, error.status === 404 ? "Video non più disponibile (conservati 7 giorni)." : error.message);
    }
  });
  card.body.replaceChildren(button);
}

function doneText(data, elapsed) {
  const t = data.timings || {};
  const parts = elapsed != null ? [`pronto in ${elapsed} s`] : ["pronto"];
  if (t.total_s != null) parts.push(`worker ${t.total_s} s`);
  if (t.sampling_s != null) parts.push(`sampling ${t.sampling_s} s`);
  if (t.workflow_s != null) parts.push(`workflow ${t.workflow_s} s`);
  if (data.m3_strength != null) parts.push(data.m3_strength > 0 ? `M3 ${data.m3_strength}${data.m3_applied ? "" : " NON verificata"}` : "M3 spenta");
  if (data.lora_applied === false) parts.push("Turbo LoRA non verificata");
  if (data.profile) parts.push(data.profile);
  if (data.steps != null) parts.push(`${data.steps} step`);
  if (data.resolution) parts.push(data.resolution);
  if (data.seed != null) parts.push(`seed ${data.seed}`);
  if (data.cold != null) parts.push(data.cold ? "a freddo" : "a caldo");
  if (data.fake) parts.push("video di prova");
  return parts.join(" · ");
}

async function poll(card, record, failingSince = null, showNow = true) {
  const { job } = record;
  let data;
  try {
    data = await (await api(`/jobs/${encodeURIComponent(record.id)}`)).json();
  } catch (error) {
    // Errori temporanei (rete, router riavviato o prelazionato da Modal): il lavoro sulla GPU continua, si riprova.
    const transient = error.status === 0 || error.status >= 500;
    const since = failingSince || Date.now();
    if (transient && Date.now() - since < GIVE_UP_MS) {
      renderMeta(card, job, `collegamento interrotto, riprovo… (${error.message})`);
      setTimeout(() => poll(card, record, since, showNow), RETRY_MS);
      return;
    }
    renderMeta(card, job, "stato sconosciuto");
    showError(card, `${error.message}. Il lavoro potrebbe essere ancora in corso: ricarica la pagina più tardi.`);
    return;
  }
  const elapsed = Math.round((Date.now() - record.started) / 1000);
  if (data.status === "running") {
    renderMeta(card, job, `in corso, ${elapsed} s`);
    setTimeout(() => poll(card, record, null, showNow), POLL_MS);
    return;
  }
  if (data.status === "done") {
    const text = doneText(data, record.finished ? null : elapsed);
    saveJob({ ...record, status: "done", text, finished: record.finished || Date.now() });
    renderMeta(card, job, text);
    if (showNow) {
      try {
        await showVideo(card, record.id);
      } catch (error) {
        showError(card, error.message);
      }
    } else {
      offerVideo(card, record.id);
    }
    return;
  }
  const text = data.status === "expired" ? "scaduto" : "errore";
  const message = data.error ? `Errore nel worker: ${data.error}` : "Il lavoro non è più disponibile.";
  saveJob({ ...record, status: text, text, error: message });
  renderMeta(card, job, text);
  showError(card, message);
}

function restoreJobs() {
  const list = loadJobs().reverse(); // dal più vecchio, così il più recente finisce in cima
  for (const record of list) {
    const card = addJobCard(record.job);
    if (record.status === "done") {
      renderMeta(card, record.job, record.text || "pronto");
      offerVideo(card, record.id);
    } else if (record.status === "errore" || record.status === "scaduto") {
      renderMeta(card, record.job, record.status);
      showError(card, record.error || "Errore");
    } else {
      renderMeta(card, record.job, "riprendo a seguirlo…");
      poll(card, record, null, false);
    }
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
  if (!$("resolution-field").hidden) job.resolution = $("resolution").value;
  if (!$("m3-field").hidden) job.m3_strength = Number($("m3").value);
  if (!$("profile-field").hidden) job.profile = $("profile").value;
  if (!$("steps-field").hidden) job.steps = Number($("steps").value);
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
    const record = { id: data.job_id, job: { ...job, prompt: job.prompt.slice(0, 2000) }, started: Date.now(), status: "running" };
    saveJob(record);
    renderMeta(card, job, "in coda");
    poll(card, record);
  } catch (error) {
    renderMeta(card, job, "errore");
    showError(card, error.message);
  } finally {
    submit.disabled = false;
  }
});

fillSettingsForm();
if (!configured()) $("settings").hidden = false;
if (setupResult !== null) {
  $("settings").hidden = false;
  setStatus(
    $("settings-status"),
    setupResult
      ? "Configurazione importata dal link e salvata su questo dispositivo."
      : "Configurazione importata solo per questa sessione: il browser non permette di memorizzarla.",
    !setupResult
  );
}
updateModelFields();
loadModels();
if (configured()) restoreJobs();
