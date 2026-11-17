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
    throw new Error(
      "Connessione non riuscita: controlla l'indirizzo del backend."
    );
  }
  if (response.status === 401 || response.status === 403) {
    throw new Error("Token rifiutato: controlla il token di accesso.");
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
  try {
    await navigator.clipboard.writeText(link);
    setStatus(status, "Link copiato. Contiene il token: conservalo nel password manager, non condividerlo.");
  } catch {
    setStatus(status, "Il browser non permette di copiare negli appunti.", true);
  }
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

function updateModelFields() {
  const model = models.find((m) => m.id === $("model").value);
  const resolutions = model ? model.resolutions : [];
  $("resolution-field").hidden = resolutions.length === 0;
  $("resolution").replaceChildren(
    ...resolutions.map((r) => {
      const option = document.createElement("option");
      option.value = r;
      option.textContent = r.replace("x", "×");
      return option;
    })
  );
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
    if (models.some((m) => m.id === current)) select.value = current;
    updateModelFields();
  } catch {
    // La pagina resta utilizzabile con il solo video di prova.
  }
}

$("model").addEventListener("change", updateModelFields);

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
      const t = data.timings || {};
      const parts = [`pronto in ${elapsed} s`];
      if (t.total_s != null) parts.push(`worker ${t.total_s} s`);
      if (t.sampling_s != null) parts.push(`sampling ${t.sampling_s} s`);
      if (data.resolution) parts.push(data.resolution);
      if (data.seed != null) parts.push(`seed ${data.seed}`);
      if (data.cold != null) parts.push(data.cold ? "a freddo" : "a caldo");
      if (data.fake) parts.push("video di prova");
      renderMeta(card, job, parts.join(" · "));
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
  if (!$("resolution-field").hidden) job.resolution = $("resolution").value;
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
