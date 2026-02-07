const statusPill = document.getElementById("status-pill");
const tempEl = document.getElementById("temp");
const cpuEl = document.getElementById("cpu");
const cpuCoresEl = document.getElementById("cpu-cores");
const memEl = document.getElementById("mem");
const diskRootEl = document.getElementById("disk-root");
const diskSsdEl = document.getElementById("disk-ssd");
const diskRootPathEl = document.getElementById("disk-root-path");
const diskSsdPathEl = document.getElementById("disk-ssd-path");
const npuEl = document.getElementById("npu");
const audioEl = document.getElementById("audio");
const micBtn = document.getElementById("mic-btn");
const micStatus = document.getElementById("mic-status");
const lastHeardEl = document.getElementById("last-heard");
const beepBtn = document.getElementById("beep-btn");
const audioDot = document.getElementById("audio-dot");
const videoStream = document.getElementById("video-stream");
const zonesOverlay = document.getElementById("zones-overlay");
const ollamaModels = document.getElementById("ollama-models");
const deviceStatus = document.getElementById("device-status");
const versionBadge = document.getElementById("version-badge");
const listeningBadge = document.getElementById("listening-badge");
const thinkingBadge = document.getElementById("thinking-badge");
const speakingBadge = document.getElementById("speaking-badge");
const logoEl = document.getElementById("logo");
const barTemp = document.getElementById("bar-temp");
const barCpu = document.getElementById("bar-cpu");
const barMem = document.getElementById("bar-mem");
const barDiskRoot = document.getElementById("bar-disk-root");
const barDiskSsd = document.getElementById("bar-disk-ssd");
const barNpu = document.getElementById("bar-npu");
const barAudio = document.getElementById("bar-audio");
const cameraReconnect = document.getElementById("camera-reconnect");
const cameraHolders = document.getElementById("camera-holders");
const cameraHoldersOutput = document.getElementById("camera-holders-output");
const cameraFormat = document.getElementById("camera-format");
const enrollOwner = document.getElementById("enroll-owner");
const didierOutput = document.getElementById("didier-output");
const didierForm = document.getElementById("didier-form");
const didierPrompt = document.getElementById("didier-prompt");
const clawbotOutput = document.getElementById("clawbot-output");
const clawbotForm = document.getElementById("clawbot-form");
const clawbotPrompt = document.getElementById("clawbot-prompt");
const didierTitle = document.getElementById("didier-title");
const clawbotTitle = document.getElementById("clawbot-title");

const DIDIER_TIMEOUT_MS = 90000;
const CLAWBOT_TIMEOUT_MS = 90000;

function withTimeout(ms) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  return { controller, clear: () => clearTimeout(id) };
}

async function readErrorDetail(res) {
  try {
    const data = await res.json();
    if (data && data.detail) return String(data.detail);
  } catch (err) {
    // ignore
  }
  return `${res.status} ${res.statusText}`.trim();
}

function clampPercent(value) {
  return Math.max(0, Math.min(100, value));
}

function setBar(el, percent) {
  if (!el) return;
  el.style.width = `${clampPercent(percent)}%`;
}

function formatDiskPath(path) {
  if (!path) return "";
  const cleaned = String(path);
  if (cleaned === "/") return "(/)";
  if (cleaned.length <= 12) return `(${cleaned})`;
  const parts = cleaned.split("/").filter(Boolean);
  if (!parts.length) return "";
  if (parts.length === 1) return `(/${parts[0]})`;
  return `(/${parts.slice(-2).join("/")})`;
}

function formatDiskLabel(entry) {
  if (!entry) return "N/D";
  if (entry.label) return entry.label;
  if (entry.used !== undefined && entry.total !== undefined) {
    return `${entry.used}/${entry.total}`;
  }
  if (entry.percent !== undefined) {
    return `${Number(entry.percent).toFixed(1)}%`;
  }
  return "N/D";
}

function setDisk(entry, valueEl, barEl) {
  if (!valueEl || !barEl) return;
  if (!entry || entry.available === false) {
    valueEl.textContent = "N/D";
    setBar(barEl, 0);
    return;
  }
  valueEl.textContent = formatDiskLabel(entry);
  if (entry.percent !== undefined) {
    setBar(barEl, entry.percent);
  }
}

function renderCpuCores(cores) {
  if (!cpuCoresEl) return;
  cpuCoresEl.innerHTML = "";
  if (!Array.isArray(cores) || !cores.length) {
    cpuCoresEl.textContent = "Cores indisponibles";
    return;
  }
  cores.forEach((value, idx) => {
    const core = document.createElement("div");
    core.className = "core";
    const label = document.createElement("span");
    label.className = "core-label";
    label.textContent = `C${idx + 1}`;
    const bar = document.createElement("div");
    bar.className = "core-bar";
    const fill = document.createElement("div");
    fill.className = "core-fill";
    fill.style.width = `${clampPercent(value)}%`;
    bar.appendChild(fill);
    const val = document.createElement("span");
    val.className = "core-value";
    val.textContent = `${Math.round(value)}%`;
    core.appendChild(label);
    core.appendChild(bar);
    core.appendChild(val);
    cpuCoresEl.appendChild(core);
  });
}

function levelToColor(percent) {
  if (percent === null || percent === undefined) {
    return "rgba(148, 163, 184, 0.6)";
  }
  if (percent < 25) return "#22c55e";
  if (percent < 50) return "#eab308";
  if (percent < 75) return "#f97316";
  return "#ef4444";
}

function setAudioDot(percent) {
  if (!audioDot) return;
  const color = levelToColor(percent);
  audioDot.style.background = color;
  audioDot.style.boxShadow = `0 0 10px ${color}66`;
}

function tempToPercent(tempC) {
  if (tempC === null || tempC === undefined) return 0;
  const min = 30;
  const max = 85;
  return clampPercent(((tempC - min) / (max - min)) * 100);
}

async function fetchMetrics() {
  try {
    const res = await fetch("/metrics");
    if (!res.ok) throw new Error("metrics");
    const data = await res.json();
    statusPill.textContent = "EN LIGNE";
    statusPill.style.background = "rgba(34, 211, 238, 0.2)";
    tempEl.textContent =
      data.cpu.temp_c !== null ? `${data.cpu.temp_c.toFixed(1)}°C` : "N/D";
    setBar(barTemp, tempToPercent(data.cpu.temp_c));
    cpuEl.textContent = `${data.cpu.percent.toFixed(1)}%`;
    setBar(barCpu, data.cpu.percent);
    renderCpuCores(data.cpu.per_core);
    memEl.textContent = `${data.memory.percent.toFixed(1)}%`;
    setBar(barMem, data.memory.percent);
    const rootDisk = data.disk && (data.disk.root || data.disk);
    const ssdDisk = data.disk && data.disk.ssd;
    setDisk(rootDisk, diskRootEl, barDiskRoot);
    setDisk(ssdDisk, diskSsdEl, barDiskSsd);
    if (diskRootPathEl) {
      const rootPath = rootDisk && rootDisk.path ? rootDisk.path : "/";
      diskRootPathEl.textContent = formatDiskPath(rootPath);
    }
    if (diskSsdPathEl) {
      const ssdPath = ssdDisk && ssdDisk.path ? ssdDisk.path : null;
      diskSsdPathEl.textContent = ssdPath ? formatDiskPath(ssdPath) : "";
    }
    if (data.npu && data.npu.available) {
      const utilRaw = data.npu.utilization;
      if (utilRaw === null || utilRaw === undefined) {
        npuEl.textContent = "ACTIF";
        setBar(barNpu, 25);
      } else {
        const util = Number.isFinite(Number(utilRaw)) ? Number(utilRaw) : 0;
        npuEl.textContent = `${util}%`;
        setBar(barNpu, util);
      }
    } else {
      npuEl.textContent = "INACTIF";
      setBar(barNpu, 0);
    }
    if (data.audio && data.audio.available) {
      const rawLevel =
        data.audio.level_percent !== undefined ? data.audio.level_percent : null;
      const level = Number.isFinite(Number(rawLevel)) ? Number(rawLevel) : null;
      if (level !== null) {
        audioEl.textContent = `${level}%`;
        setBar(barAudio, level);
        setAudioDot(level);
      } else if (data.audio.listening) {
        audioEl.textContent = "Écoute";
        setBar(barAudio, 0);
        setAudioDot(10);
      } else {
        audioEl.textContent = "N/D";
        setBar(barAudio, 0);
        setAudioDot(null);
      }
    } else {
      audioEl.textContent = "N/D";
      setBar(barAudio, 0);
      setAudioDot(null);
    }
  } catch (err) {
    statusPill.textContent = "HORS LIGNE";
    statusPill.style.background = "rgba(248, 113, 113, 0.2)";
  }
}

async function fetchOllamaModels() {
  if (!ollamaModels) return;
  try {
    const res = await fetch("/ollama/models");
    if (!res.ok) throw new Error("models");
    const data = await res.json();
    const models = (data.models || []).map((m) => m.name || m.model).filter(Boolean);
    ollamaModels.innerHTML = "";
    if (!models.length) {
      const li = document.createElement("li");
      li.textContent = "Aucun modèle chargé";
      ollamaModels.appendChild(li);
      return;
    }
    models.forEach((name) => {
      const li = document.createElement("li");
      li.textContent = name;
      ollamaModels.appendChild(li);
    });
  } catch (err) {
    ollamaModels.innerHTML = "";
    const li = document.createElement("li");
    li.textContent = "Ollama indisponible";
    ollamaModels.appendChild(li);
  }
}

function setDeviceStatus(lines) {
  if (!deviceStatus) return;
  deviceStatus.innerHTML = "";
  lines.forEach((line) => {
    const li = document.createElement("li");
    li.textContent = line;
    deviceStatus.appendChild(li);
  });
}

function updateModelTitles(models) {
  if (!models) return;
  if (didierTitle && models.didier) {
    didierTitle.textContent = `Parler à Didier (${models.didier})`;
  }
  if (clawbotTitle && models.clawbot) {
    clawbotTitle.textContent = `Parler à Clawbot (${models.clawbot})`;
  }
}

async function fetchDeviceStatus() {
  if (!deviceStatus) return;
  try {
    const res = await fetch("/device-status");
    if (!res.ok) throw new Error("status");
    const data = await res.json();
    const lines = [];
    if (data.version) {
      const version = data.version.version || "inconnue";
      const git = data.version.git ? ` (${data.version.git})` : "";
      lines.push(`Version : ${version}${git}`);
      if (versionBadge) versionBadge.textContent = `Version : ${version}${git}`;
    }
    if (data.camera) {
      lines.push(
        `Caméra : ${data.camera.opened ? "ouverte" : "fermée"} ${
          data.camera.frame ? "image ok" : "pas d'image"
        }`
      );
    }
    if (data.camera_usb) {
      lines.push(
        `Cam USB : ${data.camera_usb.present ? "présente" : "absente"}`
      );
    }
    if (data.mic) {
      lines.push(`Micro : ${data.mic.available ? "ok" : "introuvable"}`);
    }
    if (data.sound) {
      lines.push(
        `Soundboks : ${data.sound.available ? "ok" : "absente"}`
      );
    }
    if (data.tts) {
      lines.push(
        `TTS : modèle ${data.tts.model ? "ok" : "absent"}, config ${
          data.tts.config ? "ok" : "absente"
        }, paplay ${data.tts.paplay ? "ok" : "absent"}`
      );
    }
    if (data.npu) {
      lines.push(
        `NPU : périphérique ${data.npu.device ? "ok" : "absent"}, PCIe ${
          data.npu.pcie ? "ok" : "absent"
        }`
      );
    }
    if (data.models) {
      updateModelTitles(data.models);
    }
    setDeviceStatus(lines);
  } catch (err) {
    setDeviceStatus(["État des périphériques indisponible"]);
  }
}

async function fetchVersion() {
  if (!versionBadge) return;
  try {
    const res = await fetch("/version");
    if (!res.ok) throw new Error("version");
    const data = await res.json();
    const version = data.version || "inconnue";
    const git = data.git ? ` (${data.git})` : "";
    versionBadge.textContent = `Version : ${version}${git}`;
  } catch (err) {
    versionBadge.textContent = "Version : inconnue";
  }
}

function loadLogo() {
  if (!logoEl) return;
  const candidates = ["/static/Didier.jpg", "/static/didier.jpg"];
  const img = new Image();
  let index = 0;

  const tryNext = () => {
    if (index >= candidates.length) {
      return;
    }
    img.src = candidates[index];
    index += 1;
  };

  img.onload = () => {
    logoEl.style.backgroundImage = `url('${img.src}')`;
    logoEl.textContent = "";
  };
  img.onerror = () => {
    tryNext();
  };
  tryNext();
}

async function fetchAsrStatus() {
  if (!listeningBadge) return;
  try {
    const res = await fetch("/asr/status");
    if (!res.ok) throw new Error("asr");
    const data = await res.json();
    const state = String(data.state || "").toLowerCase();
    listeningBadge.textContent = `Écoute : ${data.listening ? "oui" : "non"}`;
    listeningBadge.classList.toggle("on", !!data.listening);
    listeningBadge.classList.toggle("off", !data.listening);
    if (thinkingBadge) {
      const thinking = data.thinking || state === "thinking";
      thinkingBadge.textContent = `Réflexion : ${thinking ? "en cours" : "repos"}`;
      thinkingBadge.classList.toggle("thinking-active", !!thinking);
    }
    if (speakingBadge) {
      const speaking = data.speaking || state === "speaking";
      speakingBadge.textContent = `Voix : ${speaking ? "oui" : "non"}`;
      speakingBadge.classList.toggle("on", !!speaking);
      speakingBadge.classList.toggle("off", !speaking);
    }
    if (lastHeardEl) {
      const heard = data.last_transcript || "";
      lastHeardEl.textContent = heard ? `Entendu : ${heard}` : "Entendu : --";
    }
  } catch (err) {
    listeningBadge.textContent = "Écoute : inconnue";
    listeningBadge.classList.remove("on", "off");
    if (speakingBadge) {
      speakingBadge.textContent = "Voix : inconnue";
      speakingBadge.classList.remove("on", "off");
    }
    if (thinkingBadge) {
      thinkingBadge.textContent = "Réflexion : inconnue";
      thinkingBadge.classList.remove("thinking-active");
    }
  }
}

let visionZones = [];

async function fetchVisionZones() {
  if (!zonesOverlay) return;
  try {
    const res = await fetch("/vision/zones");
    if (!res.ok) throw new Error("zones");
    const data = await res.json();
    visionZones = Array.isArray(data.zones) ? data.zones : [];
    drawZones();
  } catch (err) {
    visionZones = [];
    drawZones();
  }
}

function syncOverlaySize() {
  if (!zonesOverlay || !videoStream) return;
  const rect = videoStream.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  if (zonesOverlay.width !== width) zonesOverlay.width = width;
  if (zonesOverlay.height !== height) zonesOverlay.height = height;
}

function drawZones() {
  if (!zonesOverlay) return;
  const ctx = zonesOverlay.getContext("2d");
  if (!ctx) return;
  syncOverlaySize();
  ctx.clearRect(0, 0, zonesOverlay.width, zonesOverlay.height);
  if (!visionZones.length) return;
  ctx.lineWidth = 2;
  ctx.font = "12px 'IBM Plex Mono', monospace";
  visionZones.forEach((zone) => {
    const color = zone.color || "rgba(34, 211, 238, 0.9)";
    const x = zone.x * zonesOverlay.width;
    const y = zone.y * zonesOverlay.height;
    const w = zone.w * zonesOverlay.width;
    const h = zone.h * zonesOverlay.height;
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    ctx.strokeRect(x, y, w, h);
    if (zone.name) {
      const labelX = Math.min(Math.max(4, x + 4), zonesOverlay.width - 4);
      const labelY = Math.min(Math.max(14, y + 14), zonesOverlay.height - 4);
      ctx.fillText(zone.name, labelX, labelY);
    }
  });
}

async function sendDidierPrompt(prompt) {
  appendTerminal(didierOutput, `> ${prompt}`);
  appendTerminal(didierOutput, "... réflexion ...");
  if (thinkingBadge) {
    thinkingBadge.textContent = "Réflexion : en cours";
    thinkingBadge.classList.add("thinking-active");
  }
  try {
    const { controller, clear } = withTimeout(DIDIER_TIMEOUT_MS);
    const res = await fetch("/ask-and-speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
      signal: controller.signal,
    });
    clear();
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw new Error(detail || "service indisponible");
    }
    const data = await res.json();
    if (thinkingBadge) {
      thinkingBadge.textContent = "Réflexion : repos";
      thinkingBadge.classList.remove("thinking-active");
    }
    appendTerminal(didierOutput, data.response || "Pas de réponse.");
  } catch (err) {
    if (thinkingBadge) {
      thinkingBadge.textContent = "Réflexion : erreur";
      thinkingBadge.classList.remove("thinking-active");
    }
    const timeout = err && err.name === "AbortError";
    appendTerminal(
      didierOutput,
      timeout
        ? "Erreur : délai dépassé. Vérifie Ollama / brain."
        : `Erreur : ${err && err.message ? err.message : "impossible de joindre Didier."}`
    );
  }
}

let recognition = null;
function setupSpeech() {
  if (!micBtn) {
    if (micStatus) micStatus.textContent = "Micro : auto";
    return;
  }
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!SpeechRecognition) {
    micBtn.disabled = true;
    micStatus.textContent = "Micro : non supporté";
    return;
  }
  recognition = new SpeechRecognition();
  recognition.lang = "fr-FR";
  recognition.interimResults = false;

  recognition.onstart = () => {
    micStatus.textContent = "Micro : écoute...";
  };
  recognition.onend = () => {
    micStatus.textContent = "Micro : off";
  };
  recognition.onerror = () => {
    micStatus.textContent = "Micro : erreur";
  };
  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    if (transcript) {
      sendDidierPrompt(transcript);
    }
  };
}

if (micBtn) {
  micBtn.addEventListener("click", () => {
    if (!recognition) return;
    recognition.start();
  });
}

setupSpeech();
fetchMetrics();
setInterval(fetchMetrics, 2000);
fetchAsrStatus();
setInterval(fetchAsrStatus, 1500);
fetchDeviceStatus();
setInterval(fetchDeviceStatus, 8000);
fetchOllamaModels();
setInterval(fetchOllamaModels, 15000);
fetchVersion();
setInterval(fetchVersion, 20000);
fetchVisionZones();
setInterval(fetchVisionZones, 20000);
if (zonesOverlay) {
  window.addEventListener("resize", () => {
    drawZones();
  });
}

if (videoStream) {
  let lastVideoErrorAt = 0;
  let videoRetries = 0;
  const maxVideoRetries = 3;
  let reconnectInFlight = false;
  let lastReconnectAt = 0;
  const reconnectCooldownMs = 20000;
  let videoLoaded = false;
  let initialLoadTimer = null;

  async function triggerCameraReconnect(reason) {
    if (reconnectInFlight) return;
    const now = Date.now();
    if (now - lastReconnectAt < reconnectCooldownMs) return;
    reconnectInFlight = true;
    lastReconnectAt = now;
    if (cameraHoldersOutput) {
      cameraHoldersOutput.textContent =
        reason === "auto" ? "Relance auto caméra..." : "Relance en cours...";
    }
    try {
      const res = await fetch("/camera/reconnect", { method: "POST" });
      const data = await res.json();
      if (cameraHoldersOutput) {
        cameraHoldersOutput.textContent = data.status || "Caméra relancée";
      }
      if (videoStream) {
        videoStream.src = `/video/stream?ts=${Date.now()}`;
      }
    } catch (err) {
      if (cameraHoldersOutput)
        cameraHoldersOutput.textContent = "Relance impossible";
    } finally {
      reconnectInFlight = false;
    }
  }

  videoStream.onload = () => {
    videoRetries = 0;
    videoLoaded = true;
    if (initialLoadTimer) {
      clearTimeout(initialLoadTimer);
      initialLoadTimer = null;
    }
    drawZones();
  };

  videoStream.onerror = () => {
    videoLoaded = false;
    const now = Date.now();
    if (!lastVideoErrorAt || now - lastVideoErrorAt > 15000) {
      if (cameraHoldersOutput) {
        cameraHoldersOutput.textContent =
          "Flux vidéo indisponible. Vérifie /dev/video1.";
      }
      lastVideoErrorAt = now;
    }
    if (videoRetries < maxVideoRetries) {
      videoRetries += 1;
      setTimeout(() => {
        videoStream.src = `/video/stream?ts=${Date.now()}`;
      }, 2000);
    } else {
      triggerCameraReconnect("error");
    }
  };

  initialLoadTimer = setTimeout(() => {
    if (!videoLoaded) {
      triggerCameraReconnect("auto");
    }
  }, 8000);
}

if (cameraReconnect) {
  cameraReconnect.addEventListener("click", async () => {
    if (cameraHoldersOutput) cameraHoldersOutput.textContent = "Relance en cours...";
    try {
      const res = await fetch("/camera/reconnect", { method: "POST" });
      const data = await res.json();
      if (cameraHoldersOutput) {
        cameraHoldersOutput.textContent = data.status || "Caméra relancée";
      }
      if (videoStream) {
        videoStream.src = `/video/stream?ts=${Date.now()}`;
      }
    } catch (err) {
      if (cameraHoldersOutput)
        cameraHoldersOutput.textContent = "Relance impossible";
    }
  });
}

if (cameraHolders) {
  cameraHolders.addEventListener("click", async () => {
    if (cameraHoldersOutput)
      cameraHoldersOutput.textContent = "Recherche en cours...";
    try {
      const res = await fetch("/camera/holders");
      const data = await res.json();
      if (cameraHoldersOutput) {
        cameraHoldersOutput.textContent =
          data.output || "Aucun processus détecté";
      }
    } catch (err) {
      if (cameraHoldersOutput)
        cameraHoldersOutput.textContent = "Échec de la vérification";
    }
  });
}

if (cameraFormat) {
  cameraFormat.addEventListener("click", async () => {
    if (cameraHoldersOutput)
      cameraHoldersOutput.textContent = "Forçage du format...";
    try {
      const res = await fetch("/camera/force-format", { method: "POST" });
      const data = await res.json();
      if (cameraHoldersOutput) {
        cameraHoldersOutput.textContent =
          data.output || data.status || "Terminé";
      }
      if (videoStream) {
        videoStream.src = `/video/stream?ts=${Date.now()}`;
      }
    } catch (err) {
      if (cameraHoldersOutput)
        cameraHoldersOutput.textContent = "Échec du format";
    }
  });
}

function appendTerminal(target, text) {
  if (!target) return;
  target.textContent += `${text}\n`;
  target.scrollTop = target.scrollHeight;
}

async function sendConsolePrompt(target, endpoint, prompt) {
  appendTerminal(target, `> ${prompt}`);
  appendTerminal(target, "... réflexion ...");
  try {
    const { controller, clear } = withTimeout(CLAWBOT_TIMEOUT_MS);
    const res = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt }),
      signal: controller.signal,
    });
    clear();
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw new Error(detail || "service indisponible");
    }
    const data = await res.json();
    appendTerminal(target, data.response || "(pas de réponse)");
  } catch (err) {
    const timeout = err && err.name === "AbortError";
    appendTerminal(
      target,
      timeout
        ? "erreur : délai dépassé"
        : `erreur : ${err && err.message ? err.message : "service indisponible"}`
    );
  }
}

if (didierForm) {
  didierForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = didierPrompt.value.trim();
    if (!prompt) return;
    didierPrompt.value = "";
    await sendDidierPrompt(prompt);
  });
}

if (clawbotForm) {
  clawbotForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const prompt = clawbotPrompt.value.trim();
    if (!prompt) return;
    clawbotPrompt.value = "";
    await sendConsolePrompt(clawbotOutput, "/clawbot", prompt);
  });
}

if (beepBtn) {
  beepBtn.addEventListener("click", async () => {
    appendTerminal(didierOutput, "Test audio : aboiement");
    try {
      const res = await fetch("/audio/test", { method: "POST" });
      if (!res.ok) throw new Error("audio");
      appendTerminal(didierOutput, "Aboiement envoyé.");
    } catch (err) {
      appendTerminal(didierOutput, "Erreur : impossible d'envoyer l'aboiement.");
    }
  });
}

if (enrollOwner) {
  enrollOwner.addEventListener("click", async () => {
    if (cameraHoldersOutput) {
      cameraHoldersOutput.textContent = "Enregistrement du visage...";
    }
    try {
      const res = await fetch("/vision/enroll", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ samples: 8 }),
      });
      if (!res.ok) throw new Error("enroll");
      const data = await res.json();
      if (cameraHoldersOutput) {
        if (data.ok) {
          const method = data.method || "inconnu";
          cameraHoldersOutput.textContent = `Visage appris (${method}, ${data.samples || 0} échantillons).`;
        } else {
          cameraHoldersOutput.textContent = data.error || "Échec de l'apprentissage.";
        }
      }
    } catch (err) {
      if (cameraHoldersOutput) {
        cameraHoldersOutput.textContent = "Échec de l'apprentissage.";
      }
    }
  });
}

fetchOllamaModels();
setInterval(fetchOllamaModels, 10000);
fetchDeviceStatus();
setInterval(fetchDeviceStatus, 5000);
fetchAsrStatus();
setInterval(fetchAsrStatus, 2000);
fetchVersion();
setInterval(fetchVersion, 10000);
loadLogo();
