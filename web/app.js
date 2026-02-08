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
const videoFrame = document.getElementById("video-frame");
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
const detectionTags = document.getElementById("detection-tags");
const detectionTagsEmpty = document.getElementById("detection-tags-empty");
const detectionTagsMeta = document.getElementById("detection-tags-meta");
const detectionTagsEditor = document.getElementById("detection-tags-editor");
const detectionTagsEditorLabel = document.getElementById(
  "detection-tags-editor-label"
);
const detectionTagsEditorInput = document.getElementById(
  "detection-tags-editor-input"
);
const clawbotLog = document.getElementById("clawbot-log");
const clawbotLogMeta = document.getElementById("clawbot-log-meta");
const vscodeFrame = document.getElementById("vscode-frame");
const codingOutput = document.getElementById("coding-output");
const codingForm = document.getElementById("coding-form");
const codingPrompt = document.getElementById("coding-prompt");
const tabButtons = document.querySelectorAll("[data-tab]");
const tabPanels = document.querySelectorAll("[data-tab-panel]");
const dockerGraph = document.getElementById("docker-graph");
const dockerMeta = document.getElementById("docker-meta");
const didierFilesInput = document.getElementById("didier-files");
const didierFileSearch = document.getElementById("didier-file-search");
const didierFileResults = document.getElementById("didier-file-results");
const didierFileMeta = document.getElementById("didier-file-meta");

const DIDIER_TIMEOUT_MS = 90000;
const CLAWBOT_TIMEOUT_MS = 90000;
const CODING_TIMEOUT_MS = 120000;
const MAX_FILE_SIZE = 200 * 1024;
const MAX_INSERT_CHARS = 4000;

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

const DETECTION_LABELS_KEY = "didier:detectionLabels";
let detectionLabels = {};

function loadDetectionLabels() {
  try {
    const raw = localStorage.getItem(DETECTION_LABELS_KEY);
    detectionLabels = raw ? JSON.parse(raw) : {};
  } catch (err) {
    detectionLabels = {};
  }
}

function saveDetectionLabels() {
  try {
    localStorage.setItem(DETECTION_LABELS_KEY, JSON.stringify(detectionLabels));
  } catch (err) {
    // ignore storage errors
  }
}

loadDetectionLabels();

async function loadDetectionLabelsFromServer() {
  try {
    const res = await fetch("/vision/tags");
    if (!res.ok) return;
    const data = await res.json();
    if (!data || typeof data.tags !== "object") return;
    detectionLabels = { ...data.tags, ...detectionLabels };
    saveDetectionLabels();
  } catch (err) {
    // ignore
  }
}

let lastTagSyncAt = 0;
async function saveDetectionLabelToServer(key, label) {
  const now = Date.now();
  if (now - lastTagSyncAt < 400) return;
  lastTagSyncAt = now;
  try {
    await fetch("/vision/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key, label }),
    });
  } catch (err) {
    // ignore
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
let visionDetections = [];
let visionFrame = null;
let visionDetectionsTs = 0;
let activeDetection = null;
let activeDetectionKey = null;
let dockerNodesMap = new Map();
let dockerEdges = [];
let localDidierFiles = [];
let fileSearchResults = [];
let lastFileSearch = "";
let fileSearchTimer = null;

function detectionKey(det) {
  if (!det) return null;
  let bbox = det.bbox;
  if (!Array.isArray(bbox) && Array.isArray(det.poly) && det.poly.length >= 3) {
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    det.poly.forEach((pt) => {
      if (!Array.isArray(pt) || pt.length < 2) return;
      const px = Number(pt[0]);
      const py = Number(pt[1]);
      if (Number.isNaN(px) || Number.isNaN(py)) return;
      minX = Math.min(minX, px);
      minY = Math.min(minY, py);
      maxX = Math.max(maxX, px);
      maxY = Math.max(maxY, py);
    });
    if (Number.isFinite(minX) && Number.isFinite(minY)) {
      bbox = [minX, minY, maxX - minX, maxY - minY];
    }
  }
  if (!Array.isArray(bbox)) return null;
  const [x, y, w, h] = bbox.map((val) =>
    Math.round(Number(val || 0) / 10) * 10
  );
  const base =
    det.class_id !== null && det.class_id !== undefined
      ? `c${det.class_id}`
      : String(det.label || "obj");
  return `${base}:${x},${y},${w},${h}`;
}

function getCustomLabel(det) {
  const key = detectionKey(det);
  if (!key) return "";
  return detectionLabels[key] || "";
}

function setCustomLabel(key, value) {
  if (!key) return;
  const label = String(value || "").trim();
  if (!label) {
    delete detectionLabels[key];
  } else {
    detectionLabels[key] = label;
  }
  saveDetectionLabels();
  saveDetectionLabelToServer(key, label);
}

function formatTime(ts) {
  if (!ts) return "--:--:--";
  const date = new Date(Number(ts) * 1000);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return date.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function renderDetectionTags() {
  if (!detectionTags || !detectionTagsEmpty) return;
  detectionTags.innerHTML = "";
  if (!visionDetections.length) {
    detectionTagsEmpty.style.display = "block";
    if (detectionTagsEditor) {
      detectionTagsEditor.classList.remove("is-open");
      detectionTagsEditor.setAttribute("aria-hidden", "true");
    }
    if (detectionTagsMeta) detectionTagsMeta.textContent = "0 objet";
    return;
  }
  detectionTagsEmpty.style.display = "none";
  if (detectionTagsMeta) {
    const count = visionDetections.length;
    const suffix = count > 1 ? "objets" : "objet";
    const at = visionDetectionsTs ? formatTime(visionDetectionsTs) : "--:--:--";
    detectionTagsMeta.textContent = `${count} ${suffix} · ${at}`;
  }
  visionDetections.forEach((det, idx) => {
    const customLabel = getCustomLabel(det);
    const baseLabel = det.label || "objet";
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "detection-chip";
    if (!customLabel) chip.classList.add("is-unset");
    if (activeDetectionKey && activeDetectionKey === detectionKey(det)) {
      chip.classList.add("is-active");
    }
    chip.textContent = customLabel || baseLabel;
    chip.addEventListener("click", () => {
      openTagEditor(det, idx);
    });
    detectionTags.appendChild(chip);
  });
}
function openTagEditor(det, idx) {
  if (!detectionTagsEditor || !detectionTagsEditorInput) return;
  activeDetection = det;
  activeDetectionKey = detectionKey(det);
  if (detectionTagsEditorLabel) {
    const baseLabel = det.label || "objet";
    detectionTagsEditorLabel.textContent = `Objet ${idx + 1} · ${baseLabel}`;
  }
  detectionTagsEditorInput.value = getCustomLabel(det) || "";
  detectionTagsEditor.classList.add("is-open");
  detectionTagsEditor.setAttribute("aria-hidden", "false");
  detectionTagsEditorInput.focus();
  detectionTagsEditorInput.select();
  renderDetectionTags();
}

function closeTagEditor() {
  if (!detectionTagsEditor) return;
  activeDetection = null;
  activeDetectionKey = null;
  detectionTagsEditor.classList.remove("is-open");
  detectionTagsEditor.setAttribute("aria-hidden", "true");
  renderDetectionTags();
}

function applyTagEditor() {
  if (!activeDetection || !activeDetectionKey || !detectionTagsEditorInput) {
    closeTagEditor();
    return;
  }
  setCustomLabel(activeDetectionKey, detectionTagsEditorInput.value);
  renderDetectionTags();
  drawZones();
  closeTagEditor();
}

function formatBytes(size) {
  if (!Number.isFinite(size)) return "";
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function insertIntoDidierPrompt(text) {
  if (!didierPrompt) return;
  const prefix = didierPrompt.value ? `${didierPrompt.value}\n\n` : "";
  didierPrompt.value = `${prefix}${text}`;
  didierPrompt.focus();
}

function renderDidierFiles() {
  if (!didierFileResults) return;
  didierFileResults.innerHTML = "";
  if (didierFileMeta) {
    const count = localDidierFiles.length;
    didierFileMeta.textContent = `${count} fichier${count > 1 ? "s" : ""}`;
  }

  const localLabel = document.createElement("div");
  localLabel.className = "file-section-label";
  localLabel.textContent = "Déposés";
  didierFileResults.appendChild(localLabel);

  if (!localDidierFiles.length) {
    const empty = document.createElement("div");
    empty.className = "file-chip";
    empty.textContent = "Aucun fichier déposé.";
    didierFileResults.appendChild(empty);
  } else {
    localDidierFiles.forEach((file) => {
      const chip = document.createElement("button");
      chip.type = "button";
      chip.className = "file-chip";
      const name = document.createElement("span");
      name.textContent = file.name;
      const meta = document.createElement("small");
      meta.textContent = formatBytes(file.size);
      chip.appendChild(name);
      chip.appendChild(meta);
      chip.addEventListener("click", () => {
        if (file.content) {
          const snippet = file.content.slice(0, MAX_INSERT_CHARS);
          const suffix =
            file.content.length > MAX_INSERT_CHARS ? "\n...[tronqué]" : "";
          insertIntoDidierPrompt(
            `[Fichier: ${file.name}]\n${snippet}${suffix}\n[/Fichier]`
          );
        } else {
          insertIntoDidierPrompt(`Fichier: ${file.name}`);
        }
      });
      didierFileResults.appendChild(chip);
    });
  }

  const searchLabel = document.createElement("div");
  searchLabel.className = "file-section-label";
  searchLabel.textContent = "Recherche";
  didierFileResults.appendChild(searchLabel);

  if (!lastFileSearch) {
    const hint = document.createElement("div");
    hint.className = "file-chip";
    hint.textContent = "Tape au moins 2 caractères pour chercher.";
    didierFileResults.appendChild(hint);
    return;
  }

  if (!fileSearchResults.length) {
    const empty = document.createElement("div");
    empty.className = "file-chip";
    empty.textContent = "Aucun fichier trouvé.";
    didierFileResults.appendChild(empty);
    return;
  }

  fileSearchResults.forEach((item) => {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "file-chip";
    const name = document.createElement("span");
    name.textContent = item.path;
    const meta = document.createElement("small");
    meta.textContent = formatBytes(item.size);
    chip.appendChild(name);
    chip.appendChild(meta);
    chip.addEventListener("click", () => {
      insertIntoDidierPrompt(`Fichier: ${item.path}`);
    });
    didierFileResults.appendChild(chip);
  });
}

function readFileAsText(file) {
  return new Promise((resolve) => {
    if (!file || !file.size || file.size > MAX_FILE_SIZE) {
      resolve(null);
      return;
    }
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => resolve(null);
    reader.readAsText(file);
  });
}

async function handleDidierFiles(files) {
  if (!files || !files.length) return;
  const next = [];
  for (const file of files) {
    const content = await readFileAsText(file);
    next.push({
      name: file.name,
      size: file.size,
      type: file.type,
      content: content || "",
    });
  }
  localDidierFiles = next;
  renderDidierFiles();
}

async function fetchFileSearch(query) {
  try {
    const res = await fetch(`/files/search?q=${encodeURIComponent(query)}`);
    if (!res.ok) throw new Error("search");
    const data = await res.json();
    fileSearchResults = Array.isArray(data.results) ? data.results : [];
  } catch (err) {
    fileSearchResults = [];
  }
  renderDidierFiles();
}

function statusToClass(status) {
  if (!status) return "is-unknown";
  const normalized = String(status).toLowerCase();
  if (normalized.includes("run")) return "is-running";
  if (normalized.includes("pause")) return "is-paused";
  if (
    normalized.includes("exit") ||
    normalized.includes("dead") ||
    normalized.includes("stop")
  ) {
    return "is-stopped";
  }
  return "is-unknown";
}

function buildDockerLayout(containers) {
  const columns = [[], [], []];
  const known = [
    { name: "didier-proxy", label: "Reverse Proxy", column: 0 },
    { name: "didier-brain", label: "Didier Brain", column: 1 },
    { name: "didier-vscode", label: "VSCode", column: 1 },
    { name: "ollama", label: "Ollama", column: 2 },
  ];
  const knownSet = new Set();
  known.forEach((item) => {
    const match = containers.find((c) => c.name === item.name);
    if (!match) return;
    knownSet.add(match.name);
    columns[item.column].push({
      id: match.name,
      label: item.label,
      status: match.status,
      image: match.image,
    });
  });
  containers.forEach((c) => {
    if (knownSet.has(c.name)) return;
    columns[2].push({
      id: c.name,
      label: c.name,
      status: c.status,
      image: c.image,
    });
  });
  dockerEdges = [
    ["didier-proxy", "didier-brain"],
    ["didier-proxy", "didier-vscode"],
    ["didier-brain", "ollama"],
  ].filter(
    ([a, b]) => containers.some((c) => c.name === a) && containers.some((c) => c.name === b)
  );
  return columns;
}

function drawDockerLinks(svg) {
  if (!dockerGraph || !svg) return;
  const rect = dockerGraph.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${rect.width} ${rect.height}`);
  svg.setAttribute("width", rect.width);
  svg.setAttribute("height", rect.height);
  svg.innerHTML = "";
  const defs = document.createElementNS("http://www.w3.org/2000/svg", "defs");
  const marker = document.createElementNS("http://www.w3.org/2000/svg", "marker");
  marker.setAttribute("id", "arrow");
  marker.setAttribute("markerWidth", "8");
  marker.setAttribute("markerHeight", "8");
  marker.setAttribute("refX", "6");
  marker.setAttribute("refY", "3");
  marker.setAttribute("orient", "auto");
  const markerPath = document.createElementNS("http://www.w3.org/2000/svg", "path");
  markerPath.setAttribute("d", "M0,0 L6,3 L0,6 Z");
  marker.appendChild(markerPath);
  defs.appendChild(marker);
  svg.appendChild(defs);

  dockerEdges.forEach(([fromId, toId]) => {
    const fromEl = dockerNodesMap.get(fromId);
    const toEl = dockerNodesMap.get(toId);
    if (!fromEl || !toEl) return;
    const fromRect = fromEl.getBoundingClientRect();
    const toRect = toEl.getBoundingClientRect();
    const startX = fromRect.right - rect.left;
    const startY = fromRect.top - rect.top + fromRect.height / 2;
    const endX = toRect.left - rect.left;
    const endY = toRect.top - rect.top + toRect.height / 2;
    const midX = (startX + endX) / 2;
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute(
      "d",
      `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`
    );
    path.setAttribute("marker-end", "url(#arrow)");
    svg.appendChild(path);
  });
}

function renderDockerDiagram(payload) {
  if (!dockerGraph) return;
  const containers = Array.isArray(payload?.containers) ? payload.containers : [];
  dockerGraph.innerHTML = "";
  dockerNodesMap = new Map();
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("docker-links");
  dockerGraph.appendChild(svg);
  const columns = buildDockerLayout(containers);
  columns.forEach((col) => {
    const columnEl = document.createElement("div");
    columnEl.className = "docker-column";
    col.forEach((node) => {
      const nodeEl = document.createElement("div");
      nodeEl.className = `docker-node ${statusToClass(node.status)}`;
      nodeEl.dataset.nodeId = node.id;
      const title = document.createElement("span");
      title.className = "docker-node-title";
      title.textContent = node.label;
      const meta = document.createElement("span");
      meta.className = "docker-node-meta";
      const statusLabel = node.status ? node.status : "inconnu";
      meta.textContent = statusLabel;
      nodeEl.appendChild(title);
      nodeEl.appendChild(meta);
      columnEl.appendChild(nodeEl);
      dockerNodesMap.set(node.id, nodeEl);
    });
    dockerGraph.appendChild(columnEl);
  });
  if (dockerMeta) {
    const count = containers.length;
    const suffix = count > 1 ? "conteneurs" : "conteneur";
    const at = payload?.ts ? formatTime(payload.ts) : "--:--:--";
    dockerMeta.textContent = `${count} ${suffix} · ${at}`;
  }
  requestAnimationFrame(() => drawDockerLinks(svg));
}

async function fetchDockerDiagram() {
  if (!dockerGraph) return;
  try {
    const res = await fetch("/docker/diagram");
    if (!res.ok) throw new Error("docker");
    const data = await res.json();
    renderDockerDiagram(data);
  } catch (err) {
    dockerGraph.textContent = "Diagramme Docker indisponible.";
    if (dockerMeta) dockerMeta.textContent = "--";
  }
}

function truncateText(text, maxLen) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return "";
  if (clean.length <= maxLen) return clean;
  return `${clean.slice(0, maxLen).trimEnd()}…`;
}

function formatDateTime(ts) {
  if (!ts) return "--:--:--";
  const date = new Date(Number(ts) * 1000);
  if (Number.isNaN(date.getTime())) return "--:--:--";
  return date.toLocaleTimeString("fr-FR", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

async function fetchClawbotReport() {
  if (!clawbotLog) return;
  try {
    const res = await fetch("/clawbot/report?limit=6");
    if (!res.ok) throw new Error("clawbot report");
    const data = await res.json();
    const history = Array.isArray(data.history) ? data.history : [];
    if (!history.length) {
      clawbotLog.textContent = "Aucun rapport Clawbot.";
      if (clawbotLogMeta) clawbotLogMeta.textContent = "0 rapport";
      return;
    }
    const lines = history.map((item) => {
      const ts = item && item.ts ? formatDateTime(item.ts) : "--:--:--";
      const response = item && item.response ? String(item.response) : "";
      const summary = response.split("\n").find((line) => line.trim()) || "RAS";
      return `[${ts}] ${truncateText(summary, 180)}`;
    });
    clawbotLog.textContent = lines.join("\n");
    if (clawbotLogMeta) {
      const last = history[history.length - 1];
      const lastTs = last && last.ts ? formatDateTime(last.ts) : "--:--:--";
      clawbotLogMeta.textContent = `${history.length} rapports · ${lastTs}`;
    }
    clawbotLog.scrollTop = clawbotLog.scrollHeight;
  } catch (err) {
    clawbotLog.textContent = "Rapport Clawbot indisponible.";
    if (clawbotLogMeta) clawbotLogMeta.textContent = "--";
  }
}

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
  if (visionZones.length) {
    ctx.save();
    ctx.globalAlpha = 0.35;
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
    ctx.restore();
  }
  drawDetections(ctx);
}

function drawDetections(ctx) {
  if (!visionDetections || !visionDetections.length) return;
  const frameW =
    visionFrame && Number.isFinite(visionFrame.width)
      ? Number(visionFrame.width)
      : zonesOverlay.width;
  const frameH =
    visionFrame && Number.isFinite(visionFrame.height)
      ? Number(visionFrame.height)
      : zonesOverlay.height;
  const scaleX = frameW ? zonesOverlay.width / frameW : 1;
  const scaleY = frameH ? zonesOverlay.height / frameH : 1;
  ctx.lineWidth = 2;
  ctx.font = "12px 'IBM Plex Mono', monospace";
  visionDetections.forEach((det) => {
    const bbox = det.bbox;
    const baseLabel = det.label || "objet";
    const customLabel = getCustomLabel(det);
    const label = customLabel || baseLabel;
    const confidence =
      det.confidence !== null && det.confidence !== undefined
        ? Number(det.confidence)
        : null;
    const color = baseLabel === "personne" ? "#22c55e" : "#f59e0b";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    let labelX = 4;
    let labelY = 14;
    if (Array.isArray(det.poly) && det.poly.length >= 3) {
      ctx.beginPath();
      det.poly.forEach((pt, idx) => {
        if (!Array.isArray(pt) || pt.length < 2) return;
        const px = Number(pt[0]) * scaleX;
        const py = Number(pt[1]) * scaleY;
        if (idx === 0) {
          ctx.moveTo(px, py);
          labelX = px + 4;
          labelY = py + 12;
        } else {
          ctx.lineTo(px, py);
        }
      });
      ctx.closePath();
      ctx.stroke();
    } else if (Array.isArray(bbox) && bbox.length >= 4) {
      const [x, y, w, h] = bbox;
      const sx = x * scaleX;
      const sy = y * scaleY;
      const sw = w * scaleX;
      const sh = h * scaleY;
      ctx.strokeRect(sx, sy, sw, sh);
      labelX = sx + 4;
      labelY = sy + 14;
    } else {
      return;
    }
    const text =
      confidence !== null && Number.isFinite(confidence)
        ? `${label} ${(confidence * 100).toFixed(0)}%`
        : label;
    const clampedX = Math.min(Math.max(4, labelX), zonesOverlay.width - 4);
    const clampedY = Math.min(Math.max(14, labelY), zonesOverlay.height - 4);
    ctx.fillText(text, clampedX, clampedY);
  });
}

function pointInPolygon(x, y, points) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const xi = points[i].x;
    const yi = points[i].y;
    const xj = points[j].x;
    const yj = points[j].y;
    const intersect =
      yi > y !== yj > y &&
      x < ((xj - xi) * (y - yi)) / (yj - yi + 0.000001) + xi;
    if (intersect) inside = !inside;
  }
  return inside;
}

function findDetectionAtPoint(canvasX, canvasY) {
  if (!visionDetections || !visionDetections.length || !zonesOverlay) {
    return null;
  }
  const frameW =
    visionFrame && Number.isFinite(visionFrame.width)
      ? Number(visionFrame.width)
      : zonesOverlay.width;
  const frameH =
    visionFrame && Number.isFinite(visionFrame.height)
      ? Number(visionFrame.height)
      : zonesOverlay.height;
  const scaleX = frameW ? zonesOverlay.width / frameW : 1;
  const scaleY = frameH ? zonesOverlay.height / frameH : 1;
  let best = null;
  let bestArea = Infinity;
  visionDetections.forEach((det, idx) => {
    let hit = false;
    let area = Infinity;
    if (Array.isArray(det.poly) && det.poly.length >= 3) {
      const pts = det.poly
        .map((pt) => {
          if (!Array.isArray(pt) || pt.length < 2) return null;
          return { x: Number(pt[0]) * scaleX, y: Number(pt[1]) * scaleY };
        })
        .filter(Boolean);
      if (pts.length >= 3) {
        hit = pointInPolygon(canvasX, canvasY, pts);
        const xs = pts.map((p) => p.x);
        const ys = pts.map((p) => p.y);
        const minX = Math.min(...xs);
        const minY = Math.min(...ys);
        const maxX = Math.max(...xs);
        const maxY = Math.max(...ys);
        area = Math.max(1, (maxX - minX) * (maxY - minY));
      }
    } else if (Array.isArray(det.bbox) && det.bbox.length >= 4) {
      const [x, y, w, h] = det.bbox;
      const sx = x * scaleX;
      const sy = y * scaleY;
      const sw = w * scaleX;
      const sh = h * scaleY;
      hit =
        canvasX >= sx &&
        canvasX <= sx + sw &&
        canvasY >= sy &&
        canvasY <= sy + sh;
      area = Math.max(1, sw * sh);
    }
    if (!hit) return;
    if (area < bestArea) {
      best = { det, idx };
      bestArea = area;
    }
  });
  return best;
}

async function fetchVisionDetections() {
  if (!zonesOverlay) return;
  try {
    const res = await fetch("/vision/detections");
    if (!res.ok) throw new Error("detections");
    const data = await res.json();
    visionDetections = Array.isArray(data.detections) ? data.detections : [];
    visionFrame = data.frame || null;
    visionDetectionsTs = data.ts || 0;
    drawZones();
    renderDetectionTags();
  } catch (err) {
    visionDetections = [];
    visionFrame = null;
    drawZones();
    renderDetectionTags();
  }
}

if (detectionTagsEditorInput) {
  detectionTagsEditorInput.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      applyTagEditor();
    }
    if (event.key === "Escape") {
      event.preventDefault();
      closeTagEditor();
    }
  });
  detectionTagsEditorInput.addEventListener("blur", () => {
    if (activeDetectionKey) applyTagEditor();
  });
}

function setActiveTab(name) {
  tabButtons.forEach((btn) => {
    const active = btn.dataset.tab === name;
    btn.classList.toggle("is-active", active);
  });
  tabPanels.forEach((panel) => {
    const active = panel.dataset.tabPanel === name;
    panel.classList.toggle("is-active", active);
    panel.toggleAttribute("hidden", !active);
  });
  if (name) {
    try {
      localStorage.setItem("didier:activeTab", name);
    } catch (err) {
      // ignore
    }
  }
}

if (tabButtons.length && tabPanels.length) {
  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      setActiveTab(btn.dataset.tab);
    });
  });
  const saved = (() => {
    try {
      return localStorage.getItem("didier:activeTab");
    } catch (err) {
      return null;
    }
  })();
  if (saved) setActiveTab(saved);
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

async function sendCodingPrompt(prompt) {
  if (!codingOutput) return;
  appendTerminal(codingOutput, `> ${prompt}`);
  appendTerminal(codingOutput, "... réflexion ...");
  try {
    const { controller, clear } = withTimeout(CODING_TIMEOUT_MS);
    const res = await fetch("/coding", {
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
    appendTerminal(codingOutput, data.response || "Pas de réponse.");
  } catch (err) {
    const timeout = err && err.name === "AbortError";
    appendTerminal(
      codingOutput,
      timeout
        ? "Erreur : délai dépassé. Vérifie l'agent coding."
        : `Erreur : ${err && err.message ? err.message : "impossible de joindre l'agent."}`
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
loadDetectionLabelsFromServer();
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
fetchVisionDetections();
setInterval(fetchVisionDetections, 1000);
fetchClawbotReport();
setInterval(fetchClawbotReport, 6000);
loadLogo();
if (zonesOverlay) {
  window.addEventListener("resize", () => {
    drawZones();
  });
  zonesOverlay.addEventListener("click", (event) => {
    const rect = zonesOverlay.getBoundingClientRect();
    const x = event.clientX - rect.left;
    const y = event.clientY - rect.top;
    const hit = findDetectionAtPoint(x, y);
    if (hit) {
      openTagEditor(hit.det, hit.idx);
    } else {
      closeTagEditor();
    }
  });
}

if (dockerGraph) {
  window.addEventListener("resize", () => {
    const svg = dockerGraph.querySelector("svg.docker-links");
    if (svg) drawDockerLinks(svg);
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

if (codingForm && codingPrompt) {
  codingForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const prompt = codingPrompt.value.trim();
    if (!prompt) return;
    codingPrompt.value = "";
    sendCodingPrompt(prompt);
  });
}

if (vscodeFrame) {
  const host = window.location.hostname;
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  vscodeFrame.src = `${protocol}//${host}/vscode/`;
}

fetchDockerDiagram();
setInterval(fetchDockerDiagram, 5000);

if (didierFilesInput) {
  didierFilesInput.addEventListener("change", (event) => {
    const files = event.target && event.target.files ? event.target.files : [];
    handleDidierFiles(Array.from(files));
  });
}

if (didierFileSearch) {
  didierFileSearch.addEventListener("input", () => {
    const query = didierFileSearch.value.trim();
    lastFileSearch = query;
    if (fileSearchTimer) clearTimeout(fileSearchTimer);
    if (!query || query.length < 2) {
      fileSearchResults = [];
      renderDidierFiles();
      return;
    }
    fileSearchTimer = setTimeout(() => {
      fetchFileSearch(query);
    }, 350);
  });
}

renderDidierFiles();


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
