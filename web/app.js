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
const zonesOverlaySecondary = document.getElementById("zones-overlay-secondary");
const SHOW_STATIC_VISION_ZONES = false;
const OVERLAY_MIN_CONFIDENCE_PRIMARY = 0.4;
const OVERLAY_MIN_CONFIDENCE_SECONDARY = 0.25;
const OVERLAY_HIDE_BBOX_POLYGONS = true;
const ollamaModels = document.getElementById("ollama-models");
const versionBadge = document.getElementById("version-badge");
const uiVersionText = document.getElementById("ui-version-text");
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
const npuCoresEl = document.getElementById("npu-cores");
const barAudio = document.getElementById("bar-audio");
const cameraReconnect = document.getElementById("camera-reconnect");
const cameraHolders = document.getElementById("camera-holders");
const cameraHoldersOutput = document.getElementById("camera-holders-output");
const cameraFormat = document.getElementById("camera-format");
const enrollOwner = document.getElementById("enroll-owner");
const didierOutput = document.getElementById("didier-output");
const didierTechOutput = document.getElementById("didier-tech-output");
const didierForm = document.getElementById("didier-form");
const didierPrompt = document.getElementById("didier-prompt");
const didierBoost = document.getElementById("didier-boost");
const didierTitle = document.getElementById("didier-title");
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
const vscodeFrame = document.getElementById("vscode-frame");
const vscodeFallback = document.getElementById("vscode-fallback");
const vscodeDirectLink = document.getElementById("vscode-direct-link");
const edgeTerminalOutput = document.getElementById("edge-terminal-output");
const edgeTerminalForm = document.getElementById("edge-terminal-form");
const edgeTerminalInput = document.getElementById("edge-terminal-input");
const codingOutput = document.getElementById("coding-output");
const codingForm = document.getElementById("coding-form");
const codingPrompt = document.getElementById("coding-prompt");
const tabButtons = document.querySelectorAll("[data-tab]");
const tabPanels = document.querySelectorAll("[data-tab-panel]");
const dockerGraph = document.getElementById("docker-graph");
const dockerMeta = document.getElementById("docker-meta");
const dockerSummary = document.getElementById("docker-summary");
const dockerWorkersList = document.getElementById("docker-workers-list");
const dockerLinksList = document.getElementById("docker-links-list");
const picobotKpis = document.getElementById("picobot-kpis");
const picobotMeta = document.getElementById("picobot-meta");
const picobotTaskList = document.getElementById("picobot-task-list");
const picobotTimeline = document.getElementById("picobot-timeline");
const picobotRefresh = document.getElementById("picobot-refresh");
const picobotToolsMeta = document.getElementById("picobot-tools-meta");
const picobotBuiltinTools = document.getElementById("picobot-builtin-tools");
const picobotConfiguredTools = document.getElementById("picobot-configured-tools");
const llmfitMeta = document.getElementById("llmfit-meta");
const llmfitSummary = document.getElementById("llmfit-summary");
const llmfitCards = document.getElementById("llmfit-cards");
const llmfitTableBody = document.getElementById("llmfit-table-body");
const hardwareRefresh = document.getElementById("hardware-refresh");
const hardwareMeta = document.getElementById("hardware-meta");
const hardwareCurrent = document.getElementById("hardware-current");
const hardwareMessage = document.getElementById("hardware-message");
const peripheralsList = document.getElementById("peripherals-list");
const peripheralsRefresh = document.getElementById("peripherals-refresh");
const peripheralsMessage = document.getElementById("peripherals-message");
const actuatorsList = document.getElementById("actuators-list");
const actuatorsRefresh = document.getElementById("actuators-refresh");
const actuatorsMessage = document.getElementById("actuators-message");
const didierFilesInput = document.getElementById("didier-files");
const didierFileSearch = document.getElementById("didier-file-search");
const didierFileResults = document.getElementById("didier-file-results");
const didierFileMeta = document.getElementById("didier-file-meta");
const devicePillPs3Video = document.getElementById("pill-ps3-video");
const devicePillSurfaceVideo = document.getElementById("pill-surface-video");
const devicePillSound = document.getElementById("pill-sound");
const devicePillMic = document.getElementById("pill-mic");
const devicePillNpu = document.getElementById("pill-npu");
const didierTabTime = document.getElementById("didier-tab-time");
const videoStreamSecondary = document.getElementById("video-stream-secondary");
const primaryStreamFallback = document.getElementById("primary-stream-fallback");
const primaryStreamFallbackText = document.getElementById(
  "primary-stream-fallback-text"
);
const primaryStreamFallbackLogo = document.getElementById(
  "primary-stream-fallback-logo"
);
const surfaceStreamFallback = document.getElementById("surface-stream-fallback");
const surfaceStreamFallbackText = document.getElementById(
  "surface-stream-fallback-text"
);
const surfaceStreamFallbackLogo = document.getElementById(
  "surface-stream-fallback-logo"
);

const DIDIER_TIMEOUT_MS = 90000;
const CODING_TIMEOUT_MS = 120000;
const TERMINAL_TIMEOUT_MS = 10000;
const DIDIER_BOOST_STORAGE_KEY = "didier:boostEnabled";
const MAX_FILE_SIZE = 200 * 1024;
const MAX_INSERT_CHARS = 4000;
const VIDEO_STALE_S = 8.0;
const VIDEO_REFRESH_COOLDOWN_MS = 30000;
const VIDEO_KEEPALIVE_REFRESH_MS = 240000;
const METRICS_POLL_MS = 2000;
const CPU_GRAPH_REFRESH_MS = 5000;
const SURFACE_STATUS_POLL_MS = 4000;
const SERVICE_503_BACKOFF_MS = 30000;
const METRICS_WS_RETRY_MS = 3000;
const METRICS_WS_PATH = "/ws/metrics";
const POLL_FETCH_TIMEOUT_MS = 1800;
const PICOBOT_EXPECTED_BUILTIN_TOOLS = [
  "CreateSkill",
  "Cron",
  "DeleteSkill",
  "Exec",
  "Filesystem",
  "ListSkills",
  "Message",
  "ReadSkill",
  "Spawn",
  "Web",
  "WriteMemory",
];

let lastVideoRefreshAt = 0;
let lastSecondaryRefreshAt = 0;
let lastPrimaryStreamLoadAt = 0;
let lastSecondaryStreamLoadAt = 0;
let latestCpuMetrics = null;
let latestNpuMetrics = null;
let hasRenderedCpuMetrics = false;
let actuatorsDevices = [];
let actuatorsStatusById = new Map();
let peripheralsItems = [];
let ollamaBackoffUntil = 0;
let visionSecondaryBackoffUntil = 0;
let latestDeviceStatus = null;
let currentActiveTab = null;
let vscodeInitInFlight = false;
let asrChatSyncInitialized = false;
let asrSeenPromptAt = 0;
let asrSeenResponseAt = 0;
let metricsSocket = null;
let metricsSocketRetryTimer = null;
let metricsSocketConnected = false;
let metricsPollTimer = null;
let asrPollTimer = null;
let metricsInFlight = false;
let asrStatusInFlight = false;
let deviceStatusInFlight = false;
let surfaceStatusInFlight = false;
let ollamaModelsInFlight = false;
let versionInFlight = false;
let visionZonesInFlight = false;
const actuatorRealtimeTimers = new Map();

function isVisionTabActive() {
  // Backward compatibility: older builds used "vision" while current UI uses "dashboard".
  return currentActiveTab === "dashboard" || currentActiveTab === "vision";
}

const ACTUATOR_COLOR_PRESETS = [
  "#ffffff",
  "#ff4d4f",
  "#ff8a00",
  "#ffd400",
  "#52c41a",
  "#00d4ff",
  "#1677ff",
  "#722ed1",
];

function withTimeout(ms) {
  const controller = new AbortController();
  const id = setTimeout(() => controller.abort(), ms);
  return { controller, clear: () => clearTimeout(id) };
}

async function fetchWithAbortTimeout(
  url,
  options = {},
  timeoutMs = POLL_FETCH_TIMEOUT_MS
) {
  const { controller, clear } = withTimeout(timeoutMs);
  try {
    return await fetch(url, { ...options, signal: controller.signal });
  } finally {
    clear();
  }
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

function terminalLines(target) {
  if (!target) return [];
  return String(target.textContent || "")
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
}

function terminalHasRecentLine(target, line, maxLines = 8) {
  const needle = String(line || "").trim();
  if (!needle) return false;
  const lines = terminalLines(target);
  if (!lines.length) return false;
  const recent = lines.slice(-Math.max(1, maxLines));
  return recent.includes(needle);
}

const PILL_CLASSES = ["is-ok", "is-warn", "is-bad", "is-unknown"];
let surfaceLastFrameAt = null;
let surfaceLastErrorAt = null;
let hasSurfaceBackendStatus = false;

function setPillState(pill, state, text) {
  if (!pill) return;
  PILL_CLASSES.forEach((cls) => pill.classList.remove(cls));
  pill.classList.add(`is-${state}`);
  const statusEl = pill.querySelector(".pill-status");
  if (statusEl) statusEl.textContent = text || "--";
}

function updateSurfacePill() {
  if (!devicePillSurfaceVideo) return;
  if (hasSurfaceBackendStatus) return;
  const now = Date.now();
  if (
    surfaceLastErrorAt &&
    (!surfaceLastFrameAt || surfaceLastErrorAt > surfaceLastFrameAt)
  ) {
    setPillState(devicePillSurfaceVideo, "bad", "flux KO");
    return;
  }
  if (surfaceLastFrameAt) {
    const ageS = (now - surfaceLastFrameAt) / 1000;
    if (ageS < 6) {
      setPillState(devicePillSurfaceVideo, "ok", "flux ok");
    } else if (ageS < 18) {
      setPillState(devicePillSurfaceVideo, "warn", "flux lent");
    } else {
      setPillState(devicePillSurfaceVideo, "bad", "flux figé");
    }
    return;
  }
  setPillState(devicePillSurfaceVideo, "unknown", "en attente");
}

function updateSurfacePillFromBackend(secondary) {
  if (!devicePillSurfaceVideo || !secondary) {
    hasSurfaceBackendStatus = false;
    return false;
  }
  hasSurfaceBackendStatus = true;
  if (secondary.enabled === false) {
    setPillState(devicePillSurfaceVideo, "unknown", "désactivé");
    return true;
  }
  const status = String(secondary.status || "").toLowerCase();
  if (status === "online") {
    const ageRaw = secondary.age_s;
    const ageS = Number.isFinite(Number(ageRaw)) ? Number(ageRaw) : 0;
    if (ageS < 6) {
      setPillState(devicePillSurfaceVideo, "ok", "flux ok");
    } else if (ageS < 18) {
      setPillState(devicePillSurfaceVideo, "warn", "flux lent");
    } else {
      setPillState(devicePillSurfaceVideo, "bad", "flux figé");
    }
    return true;
  }
  if (status === "offline") {
    setPillState(devicePillSurfaceVideo, "bad", "flux KO");
    return true;
  }
  const ageRaw = secondary.last_frame_age_s;
  const ageS = Number.isFinite(Number(ageRaw)) ? Number(ageRaw) : null;
  const opened = secondary.opened === true;
  const hasFrame = secondary.frame === true;
  if (opened && hasFrame) {
    if (ageS === null || ageS < 6) {
      setPillState(devicePillSurfaceVideo, "ok", "flux ok");
    } else if (ageS < 18) {
      setPillState(devicePillSurfaceVideo, "warn", "flux lent");
    } else {
      setPillState(devicePillSurfaceVideo, "bad", "flux figé");
    }
    return true;
  }
  if (opened) {
    setPillState(devicePillSurfaceVideo, "warn", "en attente");
    return true;
  }
  setPillState(devicePillSurfaceVideo, "unknown", "en attente");
  return true;
}

function setStreamFallback(container, textEl, visible, message) {
  if (!container) return;
  container.hidden = !visible;
  if (textEl && message) {
    textEl.textContent = message;
  }
}

function setSurfaceFallback(visible, message) {
  setStreamFallback(
    surfaceStreamFallback,
    surfaceStreamFallbackText,
    visible,
    message
  );
}

function setPrimaryFallback(visible, message) {
  setStreamFallback(
    primaryStreamFallback,
    primaryStreamFallbackText,
    visible,
    message
  );
}

function loadFallbackLogo(targetEl) {
  if (!targetEl) return;
  const candidates = ["/static/Didier.jpg", "/static/didier.jpg"];
  const img = new Image();
  let index = 0;

  const tryNext = () => {
    if (index >= candidates.length) return;
    img.src = candidates[index];
    index += 1;
  };

  img.onload = () => {
    targetEl.style.backgroundImage = `url('${img.src}')`;
    targetEl.textContent = "";
  };
  img.onerror = () => {
    tryNext();
  };
  tryNext();
}

function updateDidierTabTime() {
  if (!didierTabTime) return;
  const formatter = new Intl.DateTimeFormat("fr-FR", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
  didierTabTime.textContent = formatter.format(new Date());
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

if (didierTabTime) {
  updateDidierTabTime();
  setInterval(updateDidierTabTime, 30000);
}

if (videoStreamSecondary) {
  videoStreamSecondary.addEventListener("load", () => {
    surfaceLastFrameAt = Date.now();
    lastSecondaryStreamLoadAt = Date.now();
    setSurfaceFallback(false);
    if (!hasSurfaceBackendStatus) updateSurfacePill();
  });
  videoStreamSecondary.addEventListener("error", () => {
    surfaceLastErrorAt = Date.now();
    setSurfaceFallback(true, "Flux indisponible. Verifie l'emetteur UDP.");
    if (!hasSurfaceBackendStatus) updateSurfacePill();
  });
  setSurfaceFallback(true, "En attente du flux UDP 1234...");
  updateSurfacePill();
}

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

function npuCoreLabel(core, idx) {
  const raw = core && core.id ? String(core.id) : "";
  if (!raw) return `N${idx + 1}`;
  const compact = raw.replace(/[^a-zA-Z0-9]/g, "");
  if (!compact) return `N${idx + 1}`;
  return compact.toUpperCase();
}

function renderNpuCores(cores) {
  if (!npuCoresEl) return;
  npuCoresEl.innerHTML = "";
  if (!Array.isArray(cores) || !cores.length) {
    return;
  }
  cores.forEach((core, idx) => {
    const coreRow = document.createElement("div");
    coreRow.className = "core";
    const label = document.createElement("span");
    label.className = "core-label";
    label.textContent = npuCoreLabel(core, idx);
    const bar = document.createElement("div");
    bar.className = "core-bar";
    const fill = document.createElement("div");
    fill.className = "core-fill";
    const valueRaw = core ? core.utilization : null;
    const hasValue = valueRaw !== null && valueRaw !== undefined && Number.isFinite(Number(valueRaw));
    const value = hasValue ? Number(valueRaw) : 0;
    fill.style.width = `${clampPercent(value)}%`;
    bar.appendChild(fill);
    const val = document.createElement("span");
    val.className = "core-value";
    val.textContent = hasValue ? `${Math.round(value)}%` : "--";
    coreRow.appendChild(label);
    coreRow.appendChild(bar);
    coreRow.appendChild(val);
    npuCoresEl.appendChild(coreRow);
  });
}

function npuUtilization(npuData) {
  if (!npuData || typeof npuData !== "object") return null;
  const direct = npuData.utilization;
  if (direct !== null && direct !== undefined && Number.isFinite(Number(direct))) {
    return Number(direct);
  }
  const cores = Array.isArray(npuData.cores) ? npuData.cores : [];
  const values = cores
    .map((core) => (core && Number.isFinite(Number(core.utilization)) ? Number(core.utilization) : null))
    .filter((value) => value !== null);
  if (!values.length) return null;
  return values.reduce((acc, value) => acc + value, 0) / values.length;
}

function updateNpuPillFromMetrics(npuData) {
  if (!devicePillNpu) return;
  if (!npuData || npuData.available !== true) {
    setPillState(devicePillNpu, "bad", "off");
    return;
  }
  const util = npuUtilization(npuData);
  const realFpsRaw = npuData.real_fps;
  const realFps =
    realFpsRaw !== null && realFpsRaw !== undefined && Number.isFinite(Number(realFpsRaw))
      ? Number(realFpsRaw)
      : null;
  const cores = Array.isArray(npuData.cores) ? npuData.cores : [];
  const coreCountRaw =
    npuData.core_count !== undefined && npuData.core_count !== null
      ? Number(npuData.core_count)
      : cores.length;
  const coreCount = Number.isFinite(coreCountRaw) ? Math.max(0, Math.round(coreCountRaw)) : cores.length;
  const inferredActive =
    Boolean(npuData.active) ||
    (util !== null && util > 1) ||
    cores.some((core) => Number(core && core.utilization) > 1);

  if (inferredActive) {
    const utilText = util === null ? "--" : `${Math.round(util)}%`;
    const fpsText = realFps !== null && realFps > 0.1 ? `${realFps.toFixed(1)}f` : null;
    const suffix = coreCount > 1 ? `/${coreCount}c` : "";
    const head = util !== null ? utilText : fpsText || utilText;
    setPillState(devicePillNpu, "ok", `${head}${suffix}`);
    return;
  }

  if (util !== null) {
    const suffix = coreCount > 1 ? `/${coreCount}c` : "";
    setPillState(devicePillNpu, "ok", `idle ${Math.round(util)}%${suffix}`);
    return;
  }

  const suffix = coreCount > 1 ? `${coreCount}c` : "dispo";
  setPillState(devicePillNpu, "ok", suffix);
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

function renderCpuMetrics(cpuData) {
  if (!cpuData) return;
  cpuEl.textContent = `${cpuData.percent.toFixed(1)}%`;
  setBar(barCpu, cpuData.percent);
  renderCpuCores(cpuData.per_core);
  hasRenderedCpuMetrics = true;
}

function refreshCpuMetrics() {
  if (!latestCpuMetrics) return;
  renderCpuMetrics(latestCpuMetrics);
}

function applyMetricsData(data) {
  if (!data || typeof data !== "object") return;
  if (!data.cpu || !data.memory) return;
  statusPill.textContent = "EN LIGNE";
  statusPill.style.background = "rgba(34, 211, 238, 0.2)";
  tempEl.textContent =
    data.cpu.temp_c !== null ? `${data.cpu.temp_c.toFixed(1)}°C` : "N/D";
  setBar(barTemp, tempToPercent(data.cpu.temp_c));
  latestCpuMetrics = data.cpu || null;
  if (!hasRenderedCpuMetrics) refreshCpuMetrics();
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
  const npuData = data.npu && typeof data.npu === "object" ? data.npu : null;
  latestNpuMetrics = npuData;
  if (npuData && npuData.available) {
    const util = npuUtilization(npuData);
    const realFpsRaw = npuData.real_fps;
    const realFps =
      realFpsRaw !== null && realFpsRaw !== undefined && Number.isFinite(Number(realFpsRaw))
        ? Number(realFpsRaw)
        : null;
    const cores = Array.isArray(npuData.cores) ? npuData.cores : [];
    renderNpuCores(cores);
    if (util === null) {
      if (npuData.active) {
        if (realFps !== null && realFps > 0.1) {
          npuEl.textContent = `ACTIF ${realFps.toFixed(1)}fps`;
          setBar(barNpu, Math.max(10, Math.min(100, Math.round(realFps * 8))));
        } else {
          npuEl.textContent = "ACTIF";
          setBar(barNpu, 25);
        }
      } else {
        npuEl.textContent = "IDLE";
        setBar(barNpu, 5);
      }
    } else {
      const utilRounded = Math.round(util);
      const inferredActive =
        Boolean(npuData.active) ||
        utilRounded > 1 ||
        cores.some((core) => Number(core && core.utilization) > 1);
      const fpsSuffix =
        realFps !== null && realFps > 0.1 ? ` · ${realFps.toFixed(1)}fps` : "";
      npuEl.textContent = inferredActive
        ? `${utilRounded}%${fpsSuffix}`
        : `IDLE ${utilRounded}%`;
      setBar(barNpu, utilRounded);
    }
  } else {
    npuEl.textContent = "INACTIF";
    setBar(barNpu, 0);
    renderNpuCores([]);
  }
  updateNpuPillFromMetrics(npuData);
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
}

async function fetchMetrics() {
  if (metricsInFlight) return;
  metricsInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/metrics");
    if (!res.ok) throw new Error("metrics");
    const data = await res.json();
    applyMetricsData(data);
  } catch (err) {
    statusPill.textContent = "HORS LIGNE";
    statusPill.style.background = "rgba(248, 113, 113, 0.2)";
  } finally {
    metricsInFlight = false;
  }
}

async function fetchVisionStatusSecondary() {
  if (surfaceStatusInFlight) return;
  surfaceStatusInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/vision/status-secondary");
    if (!res.ok) throw new Error("status-secondary");
    const data = await res.json();
    const secondary = data && data.camera_secondary ? data.camera_secondary : data;
    if (secondary && secondary.enabled === false) {
      setSurfaceFallback(true, "Flux secondaire desactive.");
    } else if (secondary && secondary.status === "online") {
      setSurfaceFallback(false);
    } else if (secondary && secondary.opened && secondary.frame === false) {
      setSurfaceFallback(true, "Flux detecte, attente d'image...");
    } else {
      setSurfaceFallback(true, "Aucun paquet recu sur UDP 1234.");
    }
    if (!updateSurfacePillFromBackend(secondary)) {
      updateSurfacePill();
    }
  } catch (err) {
    hasSurfaceBackendStatus = false;
    setSurfaceFallback(true, "Etat du flux secondaire indisponible.");
    updateSurfacePill();
  } finally {
    surfaceStatusInFlight = false;
  }
}

async function fetchOllamaModels() {
  if (!ollamaModels) return;
  if (Date.now() < ollamaBackoffUntil) return;
  if (ollamaModelsInFlight) return;
  ollamaModelsInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/ollama/models", {}, 2500);
    if (!res.ok) {
      if (res.status === 503) {
        ollamaBackoffUntil = Date.now() + SERVICE_503_BACKOFF_MS;
      }
      throw new Error("models");
    }
    ollamaBackoffUntil = 0;
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
  } finally {
    ollamaModelsInFlight = false;
  }
}

function updateModelTitles(models) {
  if (!models) return;
  if (didierTitle && models.didier) {
    didierTitle.textContent = `Parler à Didier (${models.didier})`;
  }
}

async function fetchDeviceStatus() {
  if (deviceStatusInFlight) return;
  deviceStatusInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/device-status");
    if (!res.ok) throw new Error("status");
    const data = await res.json();
    latestDeviceStatus = data;
    if (data.version) {
      const version = data.version.version || "inconnue";
      const git = data.version.git ? ` (${data.version.git})` : "";
      if (versionBadge) versionBadge.textContent = `Version : ${version}${git}`;
      if (uiVersionText) uiVersionText.textContent = version;
    }
    if (data.camera) {
      const age = data.camera.last_frame_age_s;
      const stale =
        age !== null && age !== undefined && Number(age) > VIDEO_STALE_S;
      const missing = data.camera.frame === false || data.camera.opened === false;
      if (videoStream && missing) {
        const now = Date.now();
        if (now - lastVideoRefreshAt > VIDEO_REFRESH_COOLDOWN_MS) {
          lastVideoRefreshAt = now;
          if (cameraHoldersOutput) {
            cameraHoldersOutput.textContent = "Relance auto du flux vidéo...";
          }
          videoStream.src = `/video/stream?ts=${Date.now()}`;
        }
      }
      if (data.camera.opened && data.camera.frame) {
        setPrimaryFallback(false);
        if (stale) {
          setPillState(devicePillPs3Video, "warn", "flux lent");
        } else {
          setPillState(devicePillPs3Video, "ok", "flux ok");
        }
      } else {
        setPrimaryFallback(true, "Flux indisponible. Verifie /dev/video0.");
        setPillState(devicePillPs3Video, "bad", "flux KO");
      }
    } else {
      setPrimaryFallback(true, "Etat camera indisponible.");
      setPillState(devicePillPs3Video, "unknown", "N/D");
    }
    if (data.camera_secondary && videoStreamSecondary) {
      const ageRaw = data.camera_secondary.last_frame_age_s;
      const age =
        ageRaw === null || ageRaw === undefined ? null : Number(ageRaw);
      const stale = age !== null && Number.isFinite(age) && age > VIDEO_STALE_S;
      const missing =
        data.camera_secondary.frame === false ||
        data.camera_secondary.opened === false;
      if (missing) {
        const now = Date.now();
        if (now - lastSecondaryRefreshAt > VIDEO_REFRESH_COOLDOWN_MS) {
          lastSecondaryRefreshAt = now;
          videoStreamSecondary.src = `/video/stream-secondary?ts=${Date.now()}`;
        }
      }
    }
    if (data.mic) {
      setPillState(
        devicePillMic,
        data.mic.available ? "ok" : "bad",
        data.mic.available ? "ok" : "absent"
      );
    } else {
      setPillState(devicePillMic, "unknown", "N/D");
    }
    if (data.sound) {
      setPillState(
        devicePillSound,
        data.sound.available ? "ok" : "bad",
        data.sound.available ? "ok" : "absent"
      );
    } else {
      setPillState(devicePillSound, "unknown", "N/D");
    }
    // Keep device-status fallback only until metrics stream is available.
    if (!latestNpuMetrics) {
      if (data.npu) {
        if (data.npu.device === true && data.npu.pcie === true) {
          setPillState(devicePillNpu, "ok", "dispo");
        } else if (data.npu.device === false && data.npu.pcie === false) {
          setPillState(devicePillNpu, "bad", "absent");
        } else if (data.npu.device === false || data.npu.pcie === false) {
          setPillState(devicePillNpu, "warn", "partiel");
        } else {
          setPillState(devicePillNpu, "unknown", "N/D");
        }
      } else {
        setPillState(devicePillNpu, "unknown", "N/D");
      }
    }
    if (data.models) {
      updateModelTitles(data.models);
    }
  } catch (err) {
    latestDeviceStatus = null;
    setPrimaryFallback(true, "Etat camera indisponible.");
    setPillState(devicePillPs3Video, "unknown", "N/D");
    setPillState(devicePillSound, "unknown", "N/D");
    setPillState(devicePillMic, "unknown", "N/D");
    setPillState(devicePillNpu, "unknown", "N/D");
  } finally {
    deviceStatusInFlight = false;
  }
}

async function fetchVersion() {
  if (!versionBadge) return;
  if (versionInFlight) return;
  versionInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/version");
    if (!res.ok) throw new Error("version");
    const data = await res.json();
    const version = data.version || "inconnue";
    const git = data.git ? ` (${data.git})` : "";
    versionBadge.textContent = `Version : ${version}${git}`;
    if (uiVersionText) uiVersionText.textContent = version;
  } catch (err) {
    versionBadge.textContent = "Version : inconnue";
    if (uiVersionText) uiVersionText.textContent = "inconnue";
  } finally {
    versionInFlight = false;
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

function applyAsrStatusData(data) {
  if (!listeningBadge) return;
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
  const promptAt = Number(data.last_prompt_at || 0);
  const responseAt = Number(data.last_response_at || 0);
  const responseText = String(data.last_response || "").trim();
  if (!asrChatSyncInitialized) {
    asrSeenPromptAt = promptAt;
    asrSeenResponseAt = responseAt;
    asrChatSyncInitialized = true;
  } else {
    if (promptAt && promptAt > asrSeenPromptAt) {
      asrSeenPromptAt = promptAt;
    }
    if (responseAt && responseAt > asrSeenResponseAt) {
      asrSeenResponseAt = responseAt;
      if (
        responseText &&
        !terminalHasRecentLine(didierOutput, responseText, 10)
      ) {
        appendTerminal(didierOutput, responseText);
      }
    }
  }
}

function setAsrUnavailableState() {
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

async function fetchAsrStatus() {
  if (!listeningBadge) return;
  if (asrStatusInFlight) return;
  asrStatusInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/asr/status");
    if (!res.ok) throw new Error("asr");
    const data = await res.json();
    applyAsrStatusData(data);
  } catch (err) {
    setAsrUnavailableState();
  } finally {
    asrStatusInFlight = false;
  }
}

function startFallbackStatusPolling() {
  if (!metricsPollTimer) {
    metricsPollTimer = setInterval(fetchMetrics, METRICS_POLL_MS);
  }
  if (!asrPollTimer) {
    asrPollTimer = setInterval(fetchAsrStatus, 1500);
  }
}

function stopFallbackStatusPolling() {
  if (metricsPollTimer) {
    clearInterval(metricsPollTimer);
    metricsPollTimer = null;
  }
  if (asrPollTimer) {
    clearInterval(asrPollTimer);
    asrPollTimer = null;
  }
}

function metricsSocketUrl() {
  const wsProto = window.location.protocol === "https:" ? "wss" : "ws";
  return `${wsProto}://${window.location.host}${METRICS_WS_PATH}`;
}

function scheduleMetricsSocketReconnect() {
  if (metricsSocketRetryTimer) return;
  metricsSocketRetryTimer = setTimeout(() => {
    metricsSocketRetryTimer = null;
    connectMetricsSocket();
  }, METRICS_WS_RETRY_MS);
}

function connectMetricsSocket() {
  if (metricsSocket && (metricsSocket.readyState === WebSocket.OPEN || metricsSocket.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    metricsSocket = new WebSocket(metricsSocketUrl());
  } catch (_err) {
    metricsSocketConnected = false;
    startFallbackStatusPolling();
    scheduleMetricsSocketReconnect();
    return;
  }

  metricsSocket.onopen = () => {
    metricsSocketConnected = true;
    stopFallbackStatusPolling();
  };

  metricsSocket.onmessage = (event) => {
    let payload = null;
    try {
      payload = JSON.parse(String(event.data || "{}"));
    } catch (_err) {
      return;
    }
    if (payload && payload.metrics) {
      applyMetricsData(payload.metrics);
    }
    if (payload && payload.asr) {
      applyAsrStatusData(payload.asr);
    }
  };

  metricsSocket.onerror = () => {
    if (metricsSocket && metricsSocket.readyState === WebSocket.OPEN) {
      metricsSocket.close();
    }
  };

  metricsSocket.onclose = () => {
    metricsSocketConnected = false;
    metricsSocket = null;
    startFallbackStatusPolling();
    scheduleMetricsSocketReconnect();
  };
}

let visionZones = [];
let visionDetections = [];
let visionFrame = null;
let visionDetectionsTs = 0;
let visionDetectionsSecondary = [];
let visionFrameSecondary = null;
let visionDetectionsSecondaryTs = 0;
let visionDetectionsInFlight = false;
let visionDetectionsSecondaryInFlight = false;
let activeDetection = null;
let activeDetectionKey = null;
let dockerNodesMap = new Map();
let dockerEdges = [];
let picobotCachedTasks = [];
let picobotLastSnapshot = null;
let llmfitLastReport = null;
let hardwareCurrentModels = null;
let hardwareApplyInFlight = false;
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
  if (
    normalized.includes("run") ||
    normalized.includes("ok") ||
    normalized.includes("up") ||
    normalized.includes("healthy")
  ) {
    return "is-running";
  }
  if (
    normalized.includes("warn") ||
    normalized.includes("degrad") ||
    normalized.includes("partial") ||
    normalized.includes("lent")
  ) {
    return "is-warn";
  }
  if (normalized.includes("pause")) return "is-paused";
  if (
    normalized.includes("exit") ||
    normalized.includes("dead") ||
    normalized.includes("stop") ||
    normalized.includes("ko") ||
    normalized.includes("down") ||
    normalized.includes("error") ||
    normalized.includes("absent")
  ) {
    return "is-stopped";
  }
  return "is-unknown";
}

function statusToShortLabel(status) {
  const cls = statusToClass(status);
  if (cls === "is-running") return "OK";
  if (cls === "is-warn") return "WARN";
  if (cls === "is-paused") return "PAUSE";
  if (cls === "is-stopped") return "KO";
  return "UNK";
}

function workerTypeLabel(value) {
  const key = String(value || "edge").toLowerCase();
  if (key === "entry") return "Entry";
  if (key === "gateway") return "Gateway";
  if (key === "perception") return "Perception";
  if (key === "cognition") return "Cognition";
  if (key === "audio") return "Audio";
  if (key === "speech") return "Speech";
  if (key === "agentic") return "Agentic";
  if (key === "device") return "Device";
  if (key === "llm") return "Model";
  if (key === "runtime") return "Runtime";
  return "Edge";
}

function workerTypeClass(value) {
  return String(value || "edge")
    .toLowerCase()
    .replace(/[^a-z0-9_-]/g, "-");
}

const EDGE_WORKER_ORDER = [
  "didier-api",
  "didier-vision",
  "didier-brain",
  "didier-audio",
  "didier-asr",
  "didier-picobot",
];

const EDGE_LINK_LABEL_NOISE = new Set([
  "http",
  "rpc",
  "queue",
  "stream",
  "i/o",
  "pcie",
  "dev",
  "unix",
  "ipc",
]);

const EDGE_LINK_LABEL_SIGNAL = new Set([
  "llm",
  "react",
  "proxy",
  "transcript",
  "tts",
  "wake",
  "asr",
  "vision",
  "audio",
  "capture",
  "infer",
  "pcie",
]);

const EDGE_MAX_FLOW_ANIMATIONS = 18;

function canonicalWorkerName(value) {
  const raw = String(value || "").trim().toLowerCase();
  if (!raw) return "";
  const base = raw.endsWith(".service") ? raw.slice(0, -8) : raw;
  if (base.startsWith("didier-")) return base;
  if (base === "api") return "didier-api";
  if (base === "vision") return "didier-vision";
  if (base === "brain") return "didier-brain";
  if (base === "audio") return "didier-audio";
  if (base === "asr") return "didier-asr";
  if (
    base === "picobot" ||
    base === "didier-picobot" ||
    base === "picobot-bridge" ||
    base === "didier-picobot-bridge"
  ) {
    return "didier-picobot";
  }
  return base;
}

function normalizeEdgeLabel(value) {
  return String(value || "")
    .trim()
    .toLowerCase();
}

function isWorkerNodeId(nodeId) {
  return String(nodeId || "").startsWith("edge-worker-");
}

function isWorkerCommunicationEdge(edge) {
  const from = edge && edge.from ? String(edge.from) : "";
  const to = edge && edge.to ? String(edge.to) : "";
  if (!from || !to) return false;
  return isWorkerNodeId(from) || isWorkerNodeId(to);
}

function shouldDisplayEdgeLabel(edge) {
  const labelRaw = edge && edge.label ? String(edge.label) : "";
  const label = normalizeEdgeLabel(labelRaw);
  if (!label) return false;
  if (EDGE_LINK_LABEL_SIGNAL.has(label)) return true;
  if (EDGE_LINK_LABEL_NOISE.has(label)) return false;
  if (isWorkerCommunicationEdge(edge)) return label.length <= 14;
  return false;
}

function workerDefaultLink(workerType) {
  const key = String(workerType || "edge").toLowerCase();
  if (key === "audio") return { mode: "async", label: "queue" };
  if (key === "speech") return { mode: "async", label: "stream" };
  if (key === "agentic") return { mode: "async", label: "proxy" };
  return { mode: "sync", label: "RPC" };
}

function ensureWorkerLinks(edges, workerNodes) {
  const next = Array.isArray(edges)
    ? edges
        .filter(Boolean)
        .map((edge) => ({
          from: edge && edge.from ? String(edge.from) : "",
          to: edge && edge.to ? String(edge.to) : "",
          mode:
            edge && String(edge.mode || "sync").toLowerCase() === "async"
              ? "async"
              : "sync",
          label: edge && edge.label ? String(edge.label) : "",
        }))
        .filter((edge) => edge.from && edge.to)
    : [];
  const hasRoute = (from, to) =>
    next.some((edge) => edge.from === from && edge.to === to);
  workerNodes.forEach((worker) => {
    const nodeId = worker && worker.id ? String(worker.id) : "";
    if (!nodeId || nodeId === "edge-worker-didier-api") return;
    if (hasRoute("edge-api", nodeId)) return;
    const fallback = workerDefaultLink(worker && worker.type ? worker.type : "edge");
    next.push({
      from: "edge-api",
      to: nodeId,
      mode: fallback.mode,
      label: fallback.label,
    });
  });
  return next;
}

function shortImageName(image) {
  if (!image) return "";
  const value = String(image);
  const slash = value.lastIndexOf("/");
  return slash >= 0 ? value.slice(slash + 1) : value;
}

function buildDockerLayout(payload) {
  const columns = [[], [], [], []];
  const containers = Array.isArray(payload?.containers) ? payload.containers : [];
  const workers = Array.isArray(payload?.workers) ? payload.workers : [];
  const deviceStatus = payload?.deviceStatus || {};
  const addNode = (column, id, label, status, meta, nodeType = "infra") => {
    columns[column].push({
      id,
      label,
      status: status || "inconnu",
      meta: meta || "",
      nodeType: nodeType || "infra",
    });
  };

  const healthOk = payload?.healthOk === true;
  const healthName = payload?.healthName ? String(payload.healthName) : "Didier";
  const models = deviceStatus.models && typeof deviceStatus.models === "object"
    ? deviceStatus.models
    : {};
  const llmModel =
    (models.didier && String(models.didier)) ||
    (models.ask && String(models.ask)) ||
    (models.brain && String(models.brain)) ||
    (models.clawbot && String(models.clawbot)) ||
    "";

  addNode(0, "edge-dashboard", "Dashboard", healthOk ? "ok" : "inconnu", "HTTP 5010", "entry");
  addNode(0, "edge-vscode", "VSCode", "ok", "/vscode", "entry");
  addNode(1, "edge-api", healthName, healthOk ? "running" : "inconnu", "API gateway 5010", "gateway");
  const workerNodes = [];
  workers.forEach((worker, idx) => {
    const canonicalName = canonicalWorkerName(
      worker && worker.name ? String(worker.name) : `worker-${idx + 1}`
    );
    const rawName = canonicalName || `worker-${idx + 1}`;
    const nodeId = `edge-worker-${rawName.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
    const typeValue = worker && worker.worker_type ? String(worker.worker_type) : "edge";
    const ipcValue = worker && worker.ipc ? String(worker.ipc) : "unix";
    const metaParts = [workerTypeLabel(typeValue), ipcValue];
    if (worker && worker.meta) metaParts.push(String(worker.meta));
    workerNodes.push({ id: nodeId, type: typeValue });
    addNode(
      2,
      nodeId,
      worker && worker.label ? String(worker.label) : rawName,
      worker && worker.status ? String(worker.status) : "inconnu",
      metaParts.filter(Boolean).join(" · "),
      typeValue
    );
  });
  addNode(
    3,
    "edge-didier-model",
    "LLM Didier",
    llmModel ? "ok" : "inconnu",
    llmModel || "modèle non défini",
    "llm"
  );

  const camera = deviceStatus.camera || {};
  const cameraAge = Number(camera.last_frame_age_s);
  let cameraState = "inconnu";
  if (camera.opened === true && camera.frame === true) {
    cameraState = Number.isFinite(cameraAge) && cameraAge > VIDEO_STALE_S ? "warn" : "ok";
  } else if (camera.opened === false || camera.frame === false) {
    cameraState = "ko";
  }
  addNode(
    3,
    "edge-camera",
    "Caméra PS3",
    cameraState,
    camera.device ? String(camera.device) : "source locale",
    "device"
  );

  const secondary = deviceStatus.camera_secondary || {};
  let secondaryState = "inconnu";
  if (secondary.enabled === false) {
    secondaryState = "inconnu";
  } else if (secondary.opened === true && secondary.frame === true) {
    const age = Number(secondary.last_frame_age_s);
    secondaryState = Number.isFinite(age) && age > 10 ? "warn" : "ok";
  } else if (secondary.opened === true && secondary.frame === false) {
    secondaryState = "warn";
  } else if (secondary.enabled === true) {
    secondaryState = "ko";
  }
  addNode(3, "edge-camera-secondary", "Caméra Surface", secondaryState, "flux secondaire", "device");

  const micAvail = deviceStatus.mic ? deviceStatus.mic.available : null;
  const soundAvail = deviceStatus.sound ? deviceStatus.sound.available : null;
  let audioState = "inconnu";
  if (micAvail === true && soundAvail === true) {
    audioState = "ok";
  } else if (micAvail === false && soundAvail === false) {
    audioState = "ko";
  } else if (micAvail === false || soundAvail === false) {
    audioState = "warn";
  }
  addNode(
    3,
    "edge-audio",
    "Audio",
    audioState,
    `mic:${micAvail === true ? "ok" : micAvail === false ? "ko" : "?"} · son:${
      soundAvail === true ? "ok" : soundAvail === false ? "ko" : "?"
    }`,
    "device"
  );

  const npu = deviceStatus.npu || {};
  let npuState = "inconnu";
  if (npu.device === true && npu.pcie === true) {
    npuState = "ok";
  } else if (npu.device === false && npu.pcie === false) {
    npuState = "ko";
  } else if (npu.device === false || npu.pcie === false) {
    npuState = "warn";
  }
  addNode(
    3,
    "edge-npu",
    "NPU Hailo",
    npuState,
    `dev:${npu.device === true ? "ok" : npu.device === false ? "ko" : "?"} · pcie:${
      npu.pcie === true ? "ok" : npu.pcie === false ? "ko" : "?"
    }`,
    "device"
  );

  const tts = deviceStatus.tts || {};
  const ttsFlags = [tts.model, tts.config, tts.paplay];
  const ttsTrueCount = ttsFlags.filter((item) => item === true).length;
  let ttsState = "inconnu";
  if (ttsTrueCount === ttsFlags.length && ttsFlags.length > 0) {
    ttsState = "ok";
  } else if (ttsTrueCount === 0 && ttsFlags.some((item) => item === false)) {
    ttsState = "ko";
  } else if (ttsFlags.some((item) => item === true) || ttsFlags.some((item) => item === false)) {
    ttsState = "warn";
  }
  addNode(
    3,
    "edge-tts",
    "TTS",
    ttsState,
    `modèle:${tts.model === true ? "ok" : tts.model === false ? "ko" : "?"}`,
    "device"
  );

  const containerNodeIds = [];
  if (containers.length) {
    addNode(
      3,
      "edge-docker-runtime",
      "Runtime Dev",
      "ok",
      `${containers.length} service${containers.length > 1 ? "s" : ""} dev`,
      "runtime"
    );
    containers.slice(0, 8).forEach((container, idx) => {
      const rawName = container && container.name ? String(container.name) : `container-${idx + 1}`;
      const serviceName = container && container.service ? String(container.service) : rawName;
      const nodeId = `edge-container-${rawName.replace(/[^a-zA-Z0-9_-]/g, "_")}`;
      containerNodeIds.push(nodeId);
      addNode(
        3,
        nodeId,
        serviceName,
        container && container.status ? String(container.status) : "inconnu",
        shortImageName(container && container.image ? container.image : ""),
        "runtime"
      );
    });
  }

  const linkSource = Array.isArray(payload?.links) ? payload.links : [];
  if (linkSource.length) {
    dockerEdges = linkSource
      .map((link) => {
        const from = link && link.from ? String(link.from) : "";
        const to = link && link.to ? String(link.to) : "";
        if (!from || !to) return null;
        const mode = String(link.mode || "sync").toLowerCase() === "async" ? "async" : "sync";
        const label = link && link.label ? String(link.label) : "";
        return { from, to, mode, label };
      })
      .filter(Boolean);
  } else {
    dockerEdges = [
      { from: "edge-dashboard", to: "edge-api", mode: "sync", label: "HTTP" },
      { from: "edge-vscode", to: "edge-api", mode: "sync", label: "HTTP" },
      ...workerNodes
        .filter((worker) => worker.id !== "edge-worker-didier-api")
        .map((worker) => {
          const fallback = workerDefaultLink(worker.type);
          return {
            from: "edge-api",
            to: worker.id,
            mode: fallback.mode,
            label: fallback.label,
          };
        }),
      { from: "edge-api", to: "edge-didier-model", mode: "sync", label: "LLM" },
      { from: "edge-api", to: "edge-camera", mode: "sync", label: "I/O" },
      { from: "edge-api", to: "edge-camera-secondary", mode: "sync", label: "I/O" },
      { from: "edge-api", to: "edge-audio", mode: "async", label: "queue" },
      { from: "edge-api", to: "edge-npu", mode: "sync", label: "PCIe" },
      { from: "edge-api", to: "edge-tts", mode: "async", label: "queue" },
      { from: "edge-api", to: "edge-docker-runtime", mode: "async", label: "dev" },
      ...containerNodeIds.map((nodeId) => ({
        from: "edge-docker-runtime",
        to: nodeId,
        mode: "async",
        label: "dev",
      })),
    ];
  }
  dockerEdges = ensureWorkerLinks(dockerEdges, workerNodes);
  return columns;
}

function flattenDockerNodes(columns) {
  const nodes = [];
  if (!Array.isArray(columns)) return nodes;
  columns.forEach((column) => {
    if (!Array.isArray(column)) return;
    column.forEach((node) => {
      if (node) nodes.push(node);
    });
  });
  return nodes;
}

function createDockerSummaryCard({ title, value, meta, status }) {
  const card = document.createElement("div");
  card.className = `docker-summary-card ${statusToClass(status)}`;
  const titleEl = document.createElement("span");
  titleEl.className = "docker-summary-title";
  titleEl.textContent = title;
  const valueEl = document.createElement("strong");
  valueEl.className = "docker-summary-value";
  valueEl.textContent = value;
  const metaEl = document.createElement("span");
  metaEl.className = "docker-summary-meta";
  metaEl.textContent = meta;
  card.appendChild(titleEl);
  card.appendChild(valueEl);
  card.appendChild(metaEl);
  return card;
}

function renderDockerSummary(payload) {
  if (!dockerSummary) return;
  dockerSummary.innerHTML = "";
  const workers = Array.isArray(payload?.workers) ? payload.workers : [];
  const containers = Array.isArray(payload?.containers) ? payload.containers : [];
  const integrations =
    payload?.integrations && typeof payload.integrations === "object"
      ? payload.integrations
      : {};
  const runningWorkers = workers.filter(
    (worker) => statusToClass(worker && worker.status) === "is-running"
  ).length;
  const warnWorkers = workers.filter(
    (worker) => statusToClass(worker && worker.status) === "is-warn"
  ).length;
  const stoppedWorkers = workers.filter(
    (worker) => statusToClass(worker && worker.status) === "is-stopped"
  ).length;
  const syncLinks = dockerEdges.filter((edge) => edge && edge.mode !== "async").length;
  const asyncLinks = dockerEdges.filter((edge) => edge && edge.mode === "async").length;
  const integrationStatus = integrations.status ? String(integrations.status) : "inconnu";
  const cards = [
    {
      title: "Workers",
      value: `${runningWorkers}/${workers.length || 0}`,
      meta: `warn:${warnWorkers} · ko:${stoppedWorkers}`,
      status: stoppedWorkers > 0 ? "ko" : warnWorkers > 0 ? "warn" : "running",
    },
    {
      title: "Flux",
      value: `${syncLinks + asyncLinks}`,
      meta: `sync:${syncLinks} · async:${asyncLinks}`,
      status: asyncLinks > syncLinks ? "warn" : "running",
    },
    {
      title: "Runtime",
      value: `${containers.length}`,
      meta: `service${containers.length > 1 ? "s dev" : " dev"}`,
      status: containers.length > 0 ? "running" : "unknown",
    },
    {
      title: "Intégrations",
      value: statusToShortLabel(integrationStatus),
      meta: [
        integrations.ollama ? `ollama:${statusToShortLabel(integrations.ollama.status)}` : "",
        integrations.picobot
          ? `picobot:${statusToShortLabel(integrations.picobot.status)}`
          : "",
        integrations.signal ? `signal:${statusToShortLabel(integrations.signal.status)}` : "",
      ]
        .filter(Boolean)
        .join(" · ") || "—",
      status: integrationStatus,
    },
  ];
  cards.forEach((card) => dockerSummary.appendChild(createDockerSummaryCard(card)));
}

function renderDockerWorkersList(payload) {
  if (!dockerWorkersList) return;
  dockerWorkersList.innerHTML = "";
  const workers = Array.isArray(payload?.workers) ? payload.workers : [];
  if (!workers.length) {
    const empty = document.createElement("div");
    empty.className = "docker-empty";
    empty.textContent = "Aucun worker edge remonté.";
    dockerWorkersList.appendChild(empty);
    return;
  }
  workers.forEach((worker) => {
    const row = document.createElement("div");
    row.className = `docker-worker-row ${statusToClass(worker && worker.status)}`;
    const main = document.createElement("div");
    main.className = "docker-worker-main";
    const head = document.createElement("div");
    head.className = "docker-worker-head";
    const label = document.createElement("strong");
    label.className = "docker-worker-label";
    label.textContent = worker && worker.label ? String(worker.label) : "Worker";
    const pill = document.createElement("span");
    pill.className = `docker-link-pill ${statusToClass(worker && worker.status)}`;
    pill.textContent = statusToShortLabel(worker && worker.status);
    head.appendChild(label);
    head.appendChild(pill);
    const meta = document.createElement("span");
    meta.className = "docker-worker-meta";
    meta.textContent = [
      workerTypeLabel(worker && worker.worker_type),
      worker && worker.ipc ? String(worker.ipc) : "",
      worker && worker.meta ? String(worker.meta) : "",
    ]
      .filter(Boolean)
      .join(" · ");
    main.appendChild(head);
    main.appendChild(meta);
    if (worker && worker.detail) {
      const detail = document.createElement("span");
      detail.className = "docker-worker-detail";
      detail.textContent = String(worker.detail);
      main.appendChild(detail);
    }
    row.appendChild(main);
    dockerWorkersList.appendChild(row);
  });
}

function renderDockerLinksList(nodeList) {
  if (!dockerLinksList) return;
  dockerLinksList.innerHTML = "";
  const nodeLabels = new Map(
    (Array.isArray(nodeList) ? nodeList : []).map((node) => [
      String(node && node.id ? node.id : ""),
      String(node && node.label ? node.label : ""),
    ])
  );
  const rankedEdges = dockerEdges
    .filter((edge) => edge && edge.from && edge.to)
    .map((edge) => {
      const label = normalizeEdgeLabel(edge.label);
      let score = 0;
      if (EDGE_LINK_LABEL_SIGNAL.has(label)) score += 4;
      if (isWorkerCommunicationEdge(edge)) score += 3;
      if (edge.mode === "async") score += 1;
      return { edge, score };
    })
    .sort((a, b) => b.score - a.score)
    .slice(0, 10)
    .map((item) => item.edge);
  if (!rankedEdges.length) {
    const empty = document.createElement("div");
    empty.className = "docker-empty";
    empty.textContent = "Aucun flux edge exploitable.";
    dockerLinksList.appendChild(empty);
    return;
  }
  rankedEdges.forEach((edge) => {
    const row = document.createElement("div");
    row.className = `docker-link-row docker-link-row-${edge.mode}`;
    const top = document.createElement("div");
    top.className = "docker-link-row-top";
    const route = document.createElement("span");
    route.className = "docker-link-route";
    const fromLabel = nodeLabels.get(String(edge.from)) || String(edge.from);
    const toLabel = nodeLabels.get(String(edge.to)) || String(edge.to);
    route.textContent = `${fromLabel} → ${toLabel}`;
    const pill = document.createElement("span");
    pill.className = `docker-link-pill ${
      edge.mode === "async" ? "is-warn" : "is-running"
    }`;
    pill.textContent = edge.mode === "async" ? "ASYNC" : "SYNC";
    top.appendChild(route);
    top.appendChild(pill);
    const meta = document.createElement("span");
    meta.className = "docker-worker-detail";
    meta.textContent = edge.label ? String(edge.label) : "flux interne";
    row.appendChild(top);
    row.appendChild(meta);
    dockerLinksList.appendChild(row);
  });
}

function drawDockerLinks(svg) {
  if (!dockerGraph || !svg) return;
  const rect = dockerGraph.getBoundingClientRect();
  if (rect.width < 8 || rect.height < 8) return;
  const svgNs = "http://www.w3.org/2000/svg";
  svg.setAttribute("viewBox", `0 0 ${rect.width} ${rect.height}`);
  svg.setAttribute("width", rect.width);
  svg.setAttribute("height", rect.height);
  svg.innerHTML = "";
  const defs = document.createElementNS(svgNs, "defs");
  const marker = document.createElementNS(svgNs, "marker");
  marker.setAttribute("id", "arrow-sync");
  marker.setAttribute("markerWidth", "8");
  marker.setAttribute("markerHeight", "8");
  marker.setAttribute("refX", "6");
  marker.setAttribute("refY", "3");
  marker.setAttribute("orient", "auto");
  const markerPath = document.createElementNS(svgNs, "path");
  markerPath.setAttribute("d", "M0,0 L6,3 L0,6 Z");
  marker.appendChild(markerPath);
  defs.appendChild(marker);
  const markerAsync = document.createElementNS(svgNs, "marker");
  markerAsync.setAttribute("id", "arrow-async");
  markerAsync.setAttribute("markerWidth", "8");
  markerAsync.setAttribute("markerHeight", "8");
  markerAsync.setAttribute("refX", "6");
  markerAsync.setAttribute("refY", "3");
  markerAsync.setAttribute("orient", "auto");
  const markerPathAsync = document.createElementNS(svgNs, "path");
  markerPathAsync.setAttribute("d", "M0,0 L6,3 L0,6 Z");
  markerAsync.appendChild(markerPathAsync);
  defs.appendChild(markerAsync);
  svg.appendChild(defs);

  let flowCount = 0;
  dockerEdges.forEach((edge, idx) => {
    const fromId = edge && edge.from ? String(edge.from) : "";
    const toId = edge && edge.to ? String(edge.to) : "";
    const mode = edge && String(edge.mode || "sync").toLowerCase() === "async" ? "async" : "sync";
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
    const path = document.createElementNS(svgNs, "path");
    const pathId = `docker-link-path-${idx}`;
    const workerEdge = isWorkerCommunicationEdge(edge);
    path.setAttribute(
      "d",
      `M ${startX} ${startY} C ${midX} ${startY}, ${midX} ${endY}, ${endX} ${endY}`
    );
    path.setAttribute("id", pathId);
    path.setAttribute("class", `docker-link docker-link-${mode}`);
    path.classList.add(workerEdge ? "docker-link-worker" : "docker-link-muted");
    path.setAttribute("marker-end", mode === "async" ? "url(#arrow-async)" : "url(#arrow-sync)");
    svg.appendChild(path);

    if (workerEdge && flowCount < EDGE_MAX_FLOW_ANIMATIONS) {
      const flowDot = document.createElementNS(svgNs, "circle");
      flowDot.setAttribute("r", mode === "async" ? "2.4" : "2.1");
      flowDot.setAttribute("class", `docker-link-flow docker-link-flow-${mode}`);
      const animateMotion = document.createElementNS(svgNs, "animateMotion");
      animateMotion.setAttribute("dur", mode === "async" ? "1.45s" : "1.95s");
      animateMotion.setAttribute("repeatCount", "indefinite");
      animateMotion.setAttribute("rotate", "auto");
      const mpath = document.createElementNS(svgNs, "mpath");
      mpath.setAttribute("href", `#${pathId}`);
      mpath.setAttributeNS("http://www.w3.org/1999/xlink", "xlink:href", `#${pathId}`);
      animateMotion.appendChild(mpath);
      flowDot.appendChild(animateMotion);
      svg.appendChild(flowDot);
      flowCount += 1;
    }

    const label = edge && edge.label ? String(edge.label) : "";
    if (label && shouldDisplayEdgeLabel(edge)) {
      const text = document.createElementNS(svgNs, "text");
      text.setAttribute("class", `docker-link-label docker-link-label-${mode}`);
      text.setAttribute("x", String(midX));
      text.setAttribute("y", String((startY + endY) / 2 - 4));
      text.textContent = label;
      svg.appendChild(text);
    }
  });
}

function renderDockerDiagram(payload) {
  if (!dockerGraph) return;
  const containers = Array.isArray(payload?.containers) ? payload.containers : [];
  const columnTitles = ["Entrées", "Contrôle", "Workers Edge", "Infra"];
  dockerGraph.innerHTML = "";
  dockerNodesMap = new Map();
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("docker-links");
  dockerGraph.appendChild(svg);
  const columns = buildDockerLayout(payload);
  const nodes = flattenDockerNodes(columns);
  renderDockerSummary(payload);
  renderDockerWorkersList(payload);
  renderDockerLinksList(nodes);
  columns.forEach((col, idx) => {
    const columnEl = document.createElement("div");
    columnEl.className = "docker-column";
    const columnTitle = document.createElement("h3");
    columnTitle.className = "docker-column-title";
    columnTitle.textContent = columnTitles[idx] || `Bloc ${idx + 1}`;
    columnEl.appendChild(columnTitle);
    col.forEach((node) => {
      const nodeEl = document.createElement("div");
      const workerTypeCls = workerTypeClass(node.nodeType || "edge");
      nodeEl.className = `docker-node ${statusToClass(node.status)} worker-type-${workerTypeCls}`;
      nodeEl.dataset.nodeId = node.id;
      const title = document.createElement("span");
      title.className = "docker-node-title";
      title.textContent = node.label;
      const typeBadge = document.createElement("span");
      typeBadge.className = `docker-node-type worker-type-${workerTypeCls}`;
      typeBadge.textContent = workerTypeLabel(node.nodeType);
      const metaRow = document.createElement("div");
      metaRow.className = "docker-node-meta-row";
      const pill = document.createElement("span");
      pill.className = `docker-node-pill ${statusToClass(node.status)}`;
      pill.textContent = statusToShortLabel(node.status);
      const meta = document.createElement("span");
      meta.className = "docker-node-meta";
      meta.textContent = node.meta ? String(node.meta) : (node.status ? String(node.status) : "inconnu");
      nodeEl.appendChild(title);
      nodeEl.appendChild(typeBadge);
      metaRow.appendChild(pill);
      metaRow.appendChild(meta);
      nodeEl.appendChild(metaRow);
      columnEl.appendChild(nodeEl);
      dockerNodesMap.set(node.id, nodeEl);
    });
    dockerGraph.appendChild(columnEl);
  });
  if (dockerMeta) {
    const count = columns.reduce((total, col) => total + col.length, 0);
    const workersCount = Array.isArray(payload?.workers) ? payload.workers.length : 0;
    const suffix = count > 1 ? "composants" : "composant";
    const runtime = `${containers.length} service${containers.length > 1 ? "s dev" : " dev"}`;
    const workersLabel = `${workersCount} worker${workersCount > 1 ? "s" : ""}`;
    const syncLinks = dockerEdges.filter((edge) => edge && edge.mode !== "async").length;
    const asyncLinks = dockerEdges.filter((edge) => edge && edge.mode === "async").length;
    const at = payload?.ts ? formatTime(payload.ts) : "--:--:--";
    const integrationState =
      payload?.integrations && payload.integrations.status
        ? statusToShortLabel(payload.integrations.status)
        : "UNK";
    dockerMeta.textContent = `${count} ${suffix} · ${workersLabel} · sync:${syncLinks} async:${asyncLinks} · ${runtime} · int:${integrationState} · ${at}`;
  }
  requestAnimationFrame(() => drawDockerLinks(svg));
  setTimeout(() => drawDockerLinks(svg), 120);
}

async function fetchJsonSafe(url) {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return await res.json();
  } catch (err) {
    return null;
  }
}

async function fetchDockerDiagram() {
  if (!dockerGraph) return;
  if (currentActiveTab !== "docker") return;
  try {
    const [diagramData, healthData, deviceData, metricsData, integrationsData] = await Promise.all([
      fetchJsonSafe("/docker/diagram"),
      fetchJsonSafe("/health"),
      latestDeviceStatus ? Promise.resolve(latestDeviceStatus) : fetchJsonSafe("/device-status"),
      fetchJsonSafe("/metrics"),
      fetchJsonSafe("/system/integrations"),
    ]);
    if (!diagramData && !healthData && !deviceData && !metricsData && !integrationsData) {
      throw new Error("edge");
    }
    const workersFromMetricsRaw = metricsData && metricsData.workers ? metricsData.workers : null;
    let workersFromMetrics = [];
    if (Array.isArray(workersFromMetricsRaw)) {
      workersFromMetrics = workersFromMetricsRaw;
    } else if (workersFromMetricsRaw && typeof workersFromMetricsRaw === "object") {
      workersFromMetrics = Object.entries(workersFromMetricsRaw).map(([name, info]) => ({
        name,
        label: `Worker ${String(name)}`,
        status: info && info.status ? String(info.status) : "inconnu",
        detail: info && info.detail ? String(info.detail) : "",
        meta: info && info.service ? String(info.service) : "",
      }));
    }
    const diagramWorkers = diagramData && Array.isArray(diagramData.workers) ? diagramData.workers : [];
    const workerMap = new Map();
    diagramWorkers.forEach((worker) => {
      const key = canonicalWorkerName(worker && worker.name ? String(worker.name) : "");
      if (!key) return;
      workerMap.set(key, {
        ...worker,
        name: key,
      });
    });
    workersFromMetrics.forEach((worker) => {
      const key = canonicalWorkerName(worker && worker.name ? String(worker.name) : "");
      if (!key) return;
      const previous = workerMap.get(key);
      if (!previous) return;
      workerMap.set(key, {
        ...previous,
        status: worker && worker.status ? String(worker.status) : previous.status,
        detail: worker && worker.detail ? String(worker.detail) : previous.detail,
      });
    });
    const mergedWorkers = Array.from(workerMap.values()).sort((a, b) => {
      const aKey = canonicalWorkerName(a && a.name ? String(a.name) : "");
      const bKey = canonicalWorkerName(b && b.name ? String(b.name) : "");
      const aPos = EDGE_WORKER_ORDER.indexOf(aKey);
      const bPos = EDGE_WORKER_ORDER.indexOf(bKey);
      const aRank = aPos >= 0 ? aPos : Number.MAX_SAFE_INTEGER;
      const bRank = bPos >= 0 ? bPos : Number.MAX_SAFE_INTEGER;
      if (aRank !== bRank) return aRank - bRank;
      return String(a && a.name ? a.name : "").localeCompare(
        String(b && b.name ? b.name : "")
      );
    });

    const payload = {
      ts: diagramData && diagramData.ts ? diagramData.ts : Date.now() / 1000,
      containers:
        diagramData && Array.isArray(diagramData.containers) ? diagramData.containers : [],
      workers: mergedWorkers,
      links: diagramData && Array.isArray(diagramData.links) ? diagramData.links : [],
      healthOk:
        healthData &&
        String(healthData.status || "").toLowerCase() === "ok",
      healthName: healthData && healthData.name ? String(healthData.name) : "Didier",
      deviceStatus: deviceData || latestDeviceStatus || null,
      integrations: integrationsData || null,
    };
    renderDockerDiagram(payload);
  } catch (err) {
    dockerGraph.textContent = "Schéma Workers Edge indisponible.";
    if (dockerSummary) dockerSummary.innerHTML = "";
    if (dockerWorkersList) dockerWorkersList.innerHTML = "";
    if (dockerLinksList) dockerLinksList.innerHTML = "";
    if (dockerMeta) dockerMeta.textContent = "--";
  }
}

function normalizeEpochSeconds(value) {
  const raw = Number(value);
  if (!Number.isFinite(raw) || raw <= 0) return null;
  if (raw > 1e12) return raw / 1000;
  if (raw > 1e10) return raw / 1000;
  return raw;
}

function formatAgeSeconds(tsSeconds) {
  if (!tsSeconds) return "--";
  const delta = Math.max(0, Date.now() / 1000 - Number(tsSeconds));
  if (delta < 1) return "maintenant";
  if (delta < 60) return `${Math.floor(delta)}s`;
  if (delta < 3600) return `${Math.floor(delta / 60)}m`;
  return `${Math.floor(delta / 3600)}h`;
}

function normalizePicobotToolNames(rawValue, fallback = []) {
  const source = Array.isArray(rawValue) ? rawValue : fallback;
  const names = source
    .map((item) => String(item || "").trim())
    .filter((item) => item.length > 0);
  return Array.from(new Set(names)).sort((a, b) => a.localeCompare(b));
}

function normalizeConfiguredPicobotTools(rawValue) {
  if (!Array.isArray(rawValue)) return [];
  return rawValue
    .map((item) => {
      if (!item || typeof item !== "object") return null;
      const name = String(item.name || "").trim();
      if (!name) return null;
      const method = String(item.method || "GET").trim().toUpperCase() || "GET";
      const type = String(item.type || "http").trim() || "http";
      const endpoint = String(item.endpoint || "").trim();
      return {
        name,
        enabled: Boolean(item.enabled),
        method,
        type,
        endpoint: endpoint || null,
      };
    })
    .filter(Boolean)
    .sort((a, b) => a.name.localeCompare(b.name));
}

function renderPicobotToolItems(target, items, emptyText) {
  if (!target) return;
  target.innerHTML = "";
  if (!Array.isArray(items) || !items.length) {
    const empty = document.createElement("div");
    empty.className = "picobot-empty";
    empty.textContent = String(emptyText || "Aucun outil.");
    target.appendChild(empty);
    return;
  }
  items.forEach((item) => {
    const row = document.createElement("article");
    row.className = `picobot-tool-item ${item.className || ""}`.trim();

    const left = document.createElement("div");
    left.className = "picobot-tool-left";
    const name = document.createElement("div");
    name.className = "picobot-tool-name";
    name.textContent = item.name || "--";
    left.appendChild(name);
    if (item.meta) {
      const meta = document.createElement("div");
      meta.className = "picobot-tool-meta";
      meta.textContent = item.meta;
      left.appendChild(meta);
    }

    const pill = document.createElement("span");
    pill.className = "picobot-tool-pill";
    pill.textContent = item.pill || "--";

    row.appendChild(left);
    row.appendChild(pill);
    target.appendChild(row);
  });
}

function renderPicobotTools(snapshotPayload) {
  if (!picobotBuiltinTools || !picobotConfiguredTools) return;
  const snapshot =
    snapshotPayload && typeof snapshotPayload === "object" ? snapshotPayload : {};
  const info =
    snapshot.picobot && typeof snapshot.picobot === "object" ? snapshot.picobot : {};

  const expectedBuiltin = normalizePicobotToolNames(
    info.expected_builtin_tools,
    PICOBOT_EXPECTED_BUILTIN_TOOLS
  );
  const builtinTools = normalizePicobotToolNames(
    info.builtin_tools,
    expectedBuiltin
  );
  const missingBuiltin = new Set(
    normalizePicobotToolNames(info.missing_builtin_tools)
  );
  const configuredTools = normalizeConfiguredPicobotTools(info.configured_tools);

  const builtinItems = builtinTools.map((name) => {
    const isMissing = missingBuiltin.has(name);
    return {
      name,
      pill: isMissing ? "MISSING" : "OK",
      className: isMissing ? "is-missing" : "",
      meta: isMissing ? "non détecté dans le runtime Picobot" : "outil natif",
    };
  });
  const configuredItems = configuredTools.map((item) => {
    const location = item.endpoint ? item.endpoint : item.type;
    return {
      name: item.name,
      pill: item.enabled ? "ON" : "OFF",
      className: item.enabled ? "" : "is-disabled",
      meta: `${item.method} · ${location}`,
    };
  });
  renderPicobotToolItems(
    picobotBuiltinTools,
    builtinItems,
    "Aucun outil built-in détecté."
  );
  renderPicobotToolItems(
    picobotConfiguredTools,
    configuredItems,
    "Aucun outil configuré dans picobot_data/config.json."
  );

  if (!picobotToolsMeta) return;
  const builtinCount = Number.isFinite(Number(info.builtin_tools_count))
    ? Number(info.builtin_tools_count)
    : builtinTools.length;
  const expectedCount = Number.isFinite(Number(info.expected_builtin_tools_count))
    ? Number(info.expected_builtin_tools_count)
    : expectedBuiltin.length;
  const configuredCount = Number.isFinite(Number(info.configured_tools_count))
    ? Number(info.configured_tools_count)
    : configuredTools.length;
  const enabledConfiguredCount = Number.isFinite(
    Number(info.enabled_configured_tools_count)
  )
    ? Number(info.enabled_configured_tools_count)
    : configuredTools.filter((item) => item.enabled).length;
  const installRequired = Boolean(info.install_required);
  const scanError = String(info.tool_scan_error || "").trim();
  const source = String(info.tools_source || "").trim();
  const statusLabel = statusToShortLabel(info.status || snapshot.status || "unknown");
  const parts = [
    `Built-in ${builtinCount}/${expectedCount || builtinCount || 11}`,
    `Config ${enabledConfiguredCount}/${configuredCount}`,
    installRequired ? "install requis" : "runtime OK",
    source ? `source: ${source}` : null,
    `statut: ${statusLabel}`,
  ].filter(Boolean);
  if (scanError) {
    parts.push(`scan: ${scanError.slice(0, 80)}`);
  }
  picobotToolsMeta.textContent = parts.join(" · ");
}

function normalizePicobotCards(payload) {
  const snapshot = payload && typeof payload === "object" ? payload : {};
  const ts = normalizeEpochSeconds(snapshot.ts) || Date.now() / 1000;
  const integrations = [
    { id: "picobot", title: "Picobot", data: snapshot.picobot || {} },
    { id: "ollama", title: "Ollama", data: snapshot.ollama || {} },
    { id: "signal", title: "Signal", data: snapshot.signal || {} },
  ];
  return integrations.map((entry) => {
    const info = entry.data && typeof entry.data === "object" ? entry.data : {};
    const status = String(info.status || "unknown");
    const detailParts = [];
    if (info.detail) detailParts.push(String(info.detail));
    if (entry.id === "picobot") {
      if (Number.isFinite(Number(info.tools_count))) {
        detailParts.push(`${Number(info.tools_count)} tool(s)`);
      }
      if (info.model) detailParts.push(`model=${String(info.model)}`);
    } else if (entry.id === "ollama") {
      if (Number.isFinite(Number(info.model_count))) {
        detailParts.push(`${Number(info.model_count)} model(s)`);
      }
      if (info.base_url) detailParts.push(String(info.base_url));
    } else if (entry.id === "signal") {
      if (info.base_url) detailParts.push(String(info.base_url));
      if (info.http_status !== undefined && info.http_status !== null) {
        detailParts.push(`http ${String(info.http_status)}`);
      }
    }
    return {
      id: entry.id,
      title: entry.title,
      status,
      progress: null,
      started_at: ts,
      updated_at: ts,
      duration_s: null,
      result: detailParts.join(" · ") || "Aucun détail.",
      error: null,
    };
  });
}

function taskProgressPercent(task) {
  const normalized = String(task && task.status ? task.status : "").toLowerCase();
  if (Number.isFinite(Number(task && task.progress))) {
    const p = Number(task.progress);
    if (p <= 1) return clampPercent(p * 100);
    return clampPercent(p);
  }
  if (normalized.includes("done") || normalized.includes("success") || normalized.includes("ok")) {
    return 100;
  }
  if (normalized.includes("error") || normalized.includes("fail")) {
    return 100;
  }
  if (normalized.includes("run") || normalized.includes("progress") || normalized.includes("queue")) {
    return 55;
  }
  return 15;
}

function renderPicobotKpis(snapshotPayload, tasks, latencyMs) {
  if (!picobotKpis) return;
  const snapshot =
    snapshotPayload && typeof snapshotPayload === "object" ? snapshotPayload : {};
  const picobotStatus = String(
    snapshot.picobot && snapshot.picobot.status
      ? snapshot.picobot.status
      : "unknown"
  );
  const ollamaStatus = String(
    snapshot.ollama && snapshot.ollama.status ? snapshot.ollama.status : "unknown"
  );
  const signalStatus = String(
    snapshot.signal && snapshot.signal.status ? snapshot.signal.status : "unknown"
  );
  const globalStatus = String(snapshot.status || "unknown");
  const runningCount = tasks.filter(
    (task) => statusToClass(task.status) === "is-running"
  ).length;
  const total = tasks.length || 1;
  const modelCount = Number(
    snapshot.ollama && Number.isFinite(Number(snapshot.ollama.model_count))
      ? snapshot.ollama.model_count
      : 0
  );
  const builtinToolsCount =
    snapshot.picobot && Number.isFinite(Number(snapshot.picobot.builtin_tools_count))
      ? Number(snapshot.picobot.builtin_tools_count)
      : normalizePicobotToolNames(
          snapshot.picobot ? snapshot.picobot.builtin_tools : [],
          PICOBOT_EXPECTED_BUILTIN_TOOLS
        ).length;
  const configuredToolsCount =
    snapshot.picobot && Number.isFinite(Number(snapshot.picobot.configured_tools_count))
      ? Number(snapshot.picobot.configured_tools_count)
      : normalizeConfiguredPicobotTools(
          snapshot.picobot ? snapshot.picobot.configured_tools : []
        ).length;
  const kpis = [
    { label: "État global", value: statusToShortLabel(globalStatus) },
    { label: "Picobot", value: statusToShortLabel(picobotStatus) },
    { label: "Ollama", value: statusToShortLabel(ollamaStatus) },
    { label: "Signal", value: statusToShortLabel(signalStatus) },
    { label: "Connecteurs OK", value: `${runningCount}/${total}` },
    { label: "Tools natifs", value: String(builtinToolsCount) },
    { label: "Tools config", value: String(configuredToolsCount) },
    { label: "Latence check", value: `${Math.max(0, Math.round(latencyMs))} ms` },
    { label: "Modèles Ollama", value: String(modelCount) },
  ];
  picobotKpis.innerHTML = "";
  kpis.forEach((item) => {
    const card = document.createElement("div");
    card.className = "picobot-kpi";
    const label = document.createElement("span");
    label.className = "picobot-kpi-label";
    label.textContent = item.label;
    const value = document.createElement("span");
    value.className = "picobot-kpi-value";
    value.textContent = item.value;
    card.appendChild(label);
    card.appendChild(value);
    picobotKpis.appendChild(card);
  });
}

function renderPicobotTasks(tasks) {
  if (!picobotTaskList) return;
  picobotTaskList.innerHTML = "";
  if (!tasks.length) {
    const empty = document.createElement("div");
    empty.className = "picobot-empty";
    empty.textContent = "Aucune donnée d'intégration.";
    picobotTaskList.appendChild(empty);
    return;
  }
  tasks.slice(0, 10).forEach((task) => {
    const card = document.createElement("article");
    card.className = `picobot-task-card ${statusToClass(task.status)}`;

    const head = document.createElement("div");
    head.className = "picobot-task-head";
    const title = document.createElement("h4");
    title.className = "picobot-task-title";
    title.textContent = task.title || task.id;
    const pill = document.createElement("span");
    pill.className = `picobot-task-pill ${statusToClass(task.status)}`;
    pill.textContent = statusToShortLabel(task.status);
    head.appendChild(title);
    head.appendChild(pill);

    const meta = document.createElement("div");
    meta.className = "picobot-task-meta";
    const started = task.started_at ? formatTime(task.started_at) : "--:--:--";
    const age = formatAgeSeconds(task.updated_at || task.started_at);
    meta.innerHTML = `<span>ID: ${task.id}</span><span>Probe: ${started}</span><span>Age: ${age}</span>`;

    const progress = document.createElement("div");
    progress.className = "picobot-progress";
    const fill = document.createElement("div");
    fill.className = "picobot-progress-fill";
    fill.style.width = `${taskProgressPercent(task)}%`;
    progress.appendChild(fill);

    const note = document.createElement("p");
    note.className = "picobot-task-note";
    note.textContent =
      (task.error !== undefined && task.error !== null
        ? `Erreur: ${String(task.error)}`
        : task.result !== undefined && task.result !== null
        ? `Détail: ${String(task.result).slice(0, 200)}`
        : "Aucun détail.");

    card.appendChild(head);
    card.appendChild(meta);
    card.appendChild(progress);
    card.appendChild(note);
    picobotTaskList.appendChild(card);
  });
}

function renderPicobotTimeline(tasks) {
  if (!picobotTimeline) return;
  picobotTimeline.innerHTML = "";
  if (!tasks.length) {
    const empty = document.createElement("div");
    empty.className = "picobot-empty";
    empty.textContent = "Timeline vide.";
    picobotTimeline.appendChild(empty);
    return;
  }
  tasks.slice(0, 16).forEach((task) => {
    const event = document.createElement("article");
    event.className = "picobot-event";
    const title = document.createElement("p");
    title.className = "picobot-event-title";
    title.textContent = `${task.title || task.id} · ${statusToShortLabel(task.status)}`;
    const meta = document.createElement("p");
    meta.className = "picobot-event-meta";
    meta.textContent = `${formatTime(task.updated_at || task.started_at)} · ${formatAgeSeconds(
      task.updated_at || task.started_at
    )}`;
    event.appendChild(title);
    event.appendChild(meta);
    picobotTimeline.appendChild(event);
  });
}

function llmfitScoreClass(score) {
  const normalized = String(score || "").trim().toLowerCase();
  if (normalized.includes("perfect")) return "is-perfect";
  if (normalized.includes("good")) return "is-good";
  if (normalized.includes("marginal")) return "is-marginal";
  return "is-fallback";
}

function llmfitScoreLabel(score) {
  const normalized = String(score || "").trim().toLowerCase();
  if (normalized.includes("perfect")) return "Perfect";
  if (normalized.includes("good")) return "Good";
  if (normalized.includes("marginal")) return "Marginal";
  return "Fallback";
}

function setHardwareMessage(text, isError = false) {
  if (!hardwareMessage) return;
  hardwareMessage.textContent = String(text || "--");
  hardwareMessage.classList.toggle("is-error", !!isError);
}

function normalizeHardwareTaskType(value) {
  const task = String(value || "").trim().toLowerCase();
  if (task === "conversation" || task === "ask") return "chat";
  if (task === "react") return "react_task";
  return task;
}

function isLlmfitSelectableRecommendation(item) {
  if (!item || typeof item !== "object") return false;
  const task = normalizeHardwareTaskType(item.task_type);
  if (!["chat", "coding", "react_task"].includes(task)) return false;
  const model = String(item.model || "").trim();
  if (!model || model.endsWith(".hef")) return false;
  const backend = String(item.backend || "").toLowerCase();
  if (
    backend.includes("ollama") ||
    backend.includes("pixel_ollama") ||
    backend.includes("local_ollama")
  ) {
    return true;
  }
  return model.includes(":");
}

function renderHardwareCurrent(snapshotPayload) {
  if (!hardwareCurrent) return;
  hardwareCurrent.innerHTML = "";
  const payload =
    snapshotPayload && typeof snapshotPayload === "object" ? snapshotPayload : null;
  const current =
    payload && payload.current && typeof payload.current === "object"
      ? payload.current
      : null;

  if (!current) {
    const empty = document.createElement("div");
    empty.className = "picobot-empty";
    empty.textContent = "Modèles courants indisponibles.";
    hardwareCurrent.appendChild(empty);
    return;
  }

  const models = [
    { label: "Par défaut", value: current.default || "--" },
    { label: "Profil ask", value: current.ask || "--" },
    { label: "Profil coding", value: current.coding || "--" },
  ];
  models.forEach((item) => {
    const card = document.createElement("article");
    card.className = "hardware-current-card";
    const label = document.createElement("span");
    label.className = "hardware-current-label";
    label.textContent = item.label;
    const value = document.createElement("strong");
    value.className = "hardware-current-value";
    value.textContent = String(item.value || "--");
    card.appendChild(label);
    card.appendChild(value);
    hardwareCurrent.appendChild(card);
  });
}

function renderLlmfitReport(reportPayload) {
  if (!llmfitSummary || !llmfitCards || !llmfitTableBody) return;
  const report =
    reportPayload && typeof reportPayload === "object" ? reportPayload : null;
  if (!report) {
    if (llmfitMeta) llmfitMeta.textContent = "Rapport indisponible";
    llmfitSummary.innerHTML = "";
    llmfitCards.innerHTML = '<div class="picobot-empty">Aucun rapport llmfit.</div>';
    llmfitTableBody.innerHTML =
      '<tr><td colspan="7" class="picobot-empty">Aucune recommandation.</td></tr>';
    return;
  }

  const recommendations = Array.isArray(report.recommendations)
    ? report.recommendations
    : [];
  const summary =
    report.summary && typeof report.summary === "object" ? report.summary : {};
  const ts = normalizeEpochSeconds(report.ts) || Date.now() / 1000;
  if (llmfitMeta) {
    llmfitMeta.textContent = `Sync ${formatTime(ts)} · ${statusToShortLabel(
      report.status
    )} · provider=${String(report.provider || "llmfit")}`;
  }

  const chips = [
    { label: "Tasks", value: Number(summary.tasks_total || recommendations.length || 0) },
    { label: "Perfect", value: Number(summary.perfect || 0) },
    { label: "Good", value: Number(summary.good || 0) },
    { label: "Marginal", value: Number(summary.marginal || 0) },
    { label: "Fallback", value: Number(summary.fallback || 0) },
    { label: "llmfit hits", value: Number(summary.llmfit_hits || 0) },
  ];
  llmfitSummary.innerHTML = "";
  chips.forEach((item) => {
    const chip = document.createElement("div");
    chip.className = "llmfit-chip";
    const label = document.createElement("span");
    label.className = "llmfit-chip-label";
    label.textContent = item.label;
    const value = document.createElement("span");
    value.className = "llmfit-chip-value";
    value.textContent = String(item.value);
    chip.appendChild(label);
    chip.appendChild(value);
    llmfitSummary.appendChild(chip);
  });

  llmfitCards.innerHTML = "";
  if (!recommendations.length) {
    llmfitCards.innerHTML = '<div class="picobot-empty">Aucune recommandation disponible.</div>';
  } else {
    recommendations.slice(0, 6).forEach((item) => {
      const scoreClass = llmfitScoreClass(item.score);
      const card = document.createElement("article");
      card.className = `llmfit-card ${scoreClass}`;

      const head = document.createElement("div");
      head.className = "llmfit-card-head";
      const title = document.createElement("h4");
      title.className = "llmfit-card-title";
      title.textContent = String(item.task_type || "task");
      const pill = document.createElement("span");
      pill.className = "llmfit-card-pill";
      pill.textContent = llmfitScoreLabel(item.score);
      head.appendChild(title);
      head.appendChild(pill);

      const meta = document.createElement("div");
      meta.className = "llmfit-card-meta";
      const backend = String(item.backend || "-");
      const model = String(item.model || "-");
      meta.innerHTML = `<span>${backend}</span><span>${model}</span><span>${String(
        item.source || "fallback"
      )}</span>`;

      const note = document.createElement("p");
      note.className = "llmfit-card-note";
      note.textContent = String(item.reason || "Pas de detail.");

      card.appendChild(head);
      card.appendChild(meta);
      card.appendChild(note);
      llmfitCards.appendChild(card);
    });
  }

  llmfitTableBody.innerHTML = "";
  if (!recommendations.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = 7;
    cell.className = "picobot-empty";
    cell.textContent = "Aucune recommandation.";
    row.appendChild(cell);
    llmfitTableBody.appendChild(row);
    return;
  }

  recommendations.forEach((item) => {
    const row = document.createElement("tr");
    const fields = [
      String(item.task_type || "-"),
      String(item.backend || "-"),
      String(item.model || "-"),
      llmfitScoreLabel(item.score),
      String(item.source || "-"),
      String(item.reason || "-"),
    ];
    fields.forEach((value) => {
      const cell = document.createElement("td");
      cell.textContent = value;
      row.appendChild(cell);
    });
    const actionCell = document.createElement("td");
    if (isLlmfitSelectableRecommendation(item)) {
      const actionButton = document.createElement("button");
      actionButton.type = "button";
      actionButton.className = "llmfit-apply-btn";
      actionButton.dataset.hardwareAction = "apply-model";
      actionButton.dataset.taskType = String(item.task_type || "");
      actionButton.dataset.backend = String(item.backend || "");
      actionButton.dataset.model = String(item.model || "");
      actionButton.textContent = "Appliquer";
      actionCell.appendChild(actionButton);
    } else {
      actionCell.textContent = "--";
    }
    row.appendChild(actionCell);
    llmfitTableBody.appendChild(row);
  });
}

async function applyRecommendedModel(item) {
  if (!item || typeof item !== "object") return;
  const taskType = normalizeHardwareTaskType(item.task_type);
  const model = String(item.model || "").trim();
  const backend = String(item.backend || "").trim();
  if (!taskType || !model) return;
  if (hardwareApplyInFlight) return;
  hardwareApplyInFlight = true;
  setHardwareMessage(`Application ${taskType} -> ${model}...`);
  try {
    const res = await fetchWithAbortTimeout(
      "/hardware/models/select",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          task_type: taskType,
          model,
          backend,
          allow_unbenchmarked: false,
        }),
      },
      3000
    );
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw new Error(detail || "application refusée");
    }
    const data = await res.json();
    const applied = data && data.applied ? data.applied : {};
    const appliedTask = String(applied.task_type || taskType);
    const appliedModel = String(applied.model || model);
    setHardwareMessage(`Modèle appliqué: ${appliedTask} -> ${appliedModel}`);
    await fetchHardwareModels(true);
    await fetchDeviceStatus();
  } catch (err) {
    setHardwareMessage(
      `Erreur: ${err && err.message ? err.message : "application impossible"}`,
      true
    );
  } finally {
    hardwareApplyInFlight = false;
  }
}

async function fetchHardwareModels(force = false) {
  if (!force && currentActiveTab !== "hardware") return;
  const llmfitUrl = force ? "/hardware/llmfit?refresh=1" : "/hardware/llmfit";
  const currentUrl = "/hardware/models/current";
  try {
    const [llmfitReport, currentPayload] = await Promise.all([
      fetchJsonSafe(llmfitUrl),
      fetchJsonSafe(currentUrl),
    ]);
    if (llmfitReport && typeof llmfitReport === "object") {
      llmfitLastReport = llmfitReport;
    }
    if (currentPayload && typeof currentPayload === "object") {
      hardwareCurrentModels = currentPayload;
    }
    renderLlmfitReport(llmfitLastReport);
    renderHardwareCurrent(hardwareCurrentModels);
    if (hardwareMeta) {
      const ts = normalizeEpochSeconds(
        (llmfitLastReport && llmfitLastReport.ts) ||
          (hardwareCurrentModels && hardwareCurrentModels.ts) ||
          Date.now() / 1000
      );
      hardwareMeta.textContent = `Sync ${formatTime(ts)} · Hardware ready`;
    }
  } catch (_err) {
    renderLlmfitReport(llmfitLastReport);
    renderHardwareCurrent(hardwareCurrentModels);
    if (hardwareMeta) hardwareMeta.textContent = "Hardware indisponible";
  }
}

async function buildLegacyIntegrationsSnapshot() {
  const [agentMetrics, ollamaPayload] = await Promise.all([
    fetchJsonSafe("/agent/metrics?timeout_s=2"),
    fetchJsonSafe("/ollama/models"),
  ]);
  if (!agentMetrics && !ollamaPayload) return null;
  const modelCount =
    ollamaPayload && Array.isArray(ollamaPayload.models)
      ? ollamaPayload.models.length
      : 0;
  const ollamaStatus = ollamaPayload ? "running" : "offline";
  const legacyDegraded =
    agentMetrics &&
    Object.prototype.hasOwnProperty.call(agentMetrics, "degraded") &&
    Boolean(agentMetrics.degraded);
  const picobotStatus = legacyDegraded ? "degraded" : "running";
  return {
    ts: Date.now() / 1000,
    status: legacyDegraded ? "degraded" : "running",
    picobot: {
      status: picobotStatus,
      detail: "bridge legacy OpenClaw (compat)",
      tools_count: 0,
      model: null,
    },
    ollama: {
      status: ollamaStatus,
      detail: ollamaPayload ? "legacy endpoint /ollama/models" : "indisponible",
      base_url: null,
      model_count: modelCount,
    },
    signal: {
      status: "unknown",
      detail: "probe signal absent en mode legacy",
      base_url: null,
    },
  };
}

async function fetchPicobotStatus(force = false) {
  if (!picobotTaskList || !picobotTimeline) return;
  if (!force && currentActiveTab !== "picobot") return;
  const startedMs = Date.now();
  try {
    const integrationsUrl = force
      ? "/system/integrations?refresh=1"
      : "/system/integrations";
    let snapshot = await fetchJsonSafe(integrationsUrl);
    if (!snapshot) {
      snapshot = await buildLegacyIntegrationsSnapshot();
    }
    if (!snapshot) throw new Error("integrations_unavailable");
    const tasks = normalizePicobotCards(snapshot);
    picobotCachedTasks = tasks;
    picobotLastSnapshot = snapshot;
    renderPicobotKpis(snapshot, tasks, Date.now() - startedMs);
    renderPicobotTasks(tasks);
    renderPicobotTimeline(tasks);
    renderPicobotTools(snapshot);
    if (picobotMeta) {
      const ts = normalizeEpochSeconds(snapshot.ts) || Date.now() / 1000;
      picobotMeta.textContent = `Sync ${formatTime(ts)} · ${statusToShortLabel(snapshot.status)}`;
    }
  } catch (_err) {
    renderPicobotKpis(picobotLastSnapshot, picobotCachedTasks, Date.now() - startedMs);
    renderPicobotTasks(picobotCachedTasks);
    renderPicobotTimeline(picobotCachedTasks);
    renderPicobotTools(picobotLastSnapshot);
    if (picobotMeta) {
      picobotMeta.textContent = "Intégrations indisponibles";
    }
  }
}

function setActuatorsMessage(text, isError = false) {
  if (!actuatorsMessage) return;
  actuatorsMessage.textContent = text || "--";
  actuatorsMessage.classList.toggle("is-error", !!isError);
}

function setPeripheralsMessage(text, isError = false) {
  if (!peripheralsMessage) return;
  peripheralsMessage.textContent = text || "--";
  peripheralsMessage.classList.toggle("is-error", !!isError);
}

function normalizePeripheralItems(payload) {
  if (Array.isArray(payload)) return payload;
  if (payload && Array.isArray(payload.items)) return payload.items;
  return [];
}

function peripheralStateData(item) {
  const state = String(item && item.state ? item.state : "").toLowerCase();
  const active = item && item.active === true;
  if (active || state === "active" || state === "activating") {
    return { cls: "is-on", text: "connecté" };
  }
  if (state === "inactive" || state === "failed" || state === "deactivating") {
    return { cls: "is-off", text: "déconnecté" };
  }
  return { cls: "is-unknown", text: state || "inconnu" };
}

function renderPeripherals() {
  if (!peripheralsList) return;
  peripheralsList.innerHTML = "";
  if (!peripheralsItems.length) {
    const empty = document.createElement("div");
    empty.className = "peripheral-empty";
    empty.textContent = "Aucun périphérique déclaré.";
    peripheralsList.appendChild(empty);
    return;
  }

  peripheralsItems.forEach((item) => {
    const state = peripheralStateData(item);
    const card = document.createElement("article");
    card.className = "peripheral-card";
    card.dataset.peripheralId = String(item && item.id ? item.id : "");

    const head = document.createElement("div");
    head.className = "peripheral-head";
    const title = document.createElement("h3");
    title.className = "peripheral-title";
    title.textContent = String(item && item.label ? item.label : item.id || "Périphérique");
    head.appendChild(title);

    const badges = document.createElement("div");
    badges.className = "peripheral-badges";
    const kind = document.createElement("span");
    kind.className = "peripheral-badge";
    kind.textContent = String(item && item.kind ? item.kind : "inconnu");
    badges.appendChild(kind);
    const channel = document.createElement("span");
    channel.className = "peripheral-badge";
    channel.textContent = String(item && item.channel ? item.channel : "n/a");
    badges.appendChild(channel);
    head.appendChild(badges);

    const status = document.createElement("div");
    status.className = "peripheral-status";
    const service = document.createElement("span");
    const svc = String(item && item.service ? item.service : "service n/a");
    const link = String(item && item.link_state ? item.link_state : "").trim();
    service.textContent = link ? `${svc} · lien ${link}` : svc;
    status.appendChild(service);
    const pill = document.createElement("span");
    pill.className = `peripheral-state-pill ${state.cls}`;
    pill.textContent = state.text;
    status.appendChild(pill);

    const actions = document.createElement("div");
    actions.className = "peripheral-actions";
    const btnOn = document.createElement("button");
    btnOn.type = "button";
    btnOn.className = "peripheral-on";
    btnOn.dataset.peripheralAction = "start";
    btnOn.dataset.peripheralId = String(item && item.id ? item.id : "");
    btnOn.textContent = "Activer";
    const btnOff = document.createElement("button");
    btnOff.type = "button";
    btnOff.className = "peripheral-off";
    btnOff.dataset.peripheralAction = "stop";
    btnOff.dataset.peripheralId = String(item && item.id ? item.id : "");
    btnOff.textContent = "Désactiver";
    actions.appendChild(btnOn);
    actions.appendChild(btnOff);

    card.appendChild(head);
    card.appendChild(status);
    card.appendChild(actions);
    peripheralsList.appendChild(card);
  });
}

async function fetchPeripherals() {
  if (!peripheralsList) return;
  setPeripheralsMessage("Chargement...");
  try {
    const res = await fetch("/peripherals");
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw new Error(detail || "peripherals indisponible");
    }
    const data = await res.json();
    const items = normalizePeripheralItems(data)
      .filter((item) => item && item.id)
      .sort((a, b) =>
        String(a.label || a.id).localeCompare(String(b.label || b.id), "fr")
      );
    peripheralsItems = items;
    renderPeripherals();
    setPeripheralsMessage(`${items.length} périphérique${items.length > 1 ? "s" : ""}`);
  } catch (err) {
    peripheralsItems = [];
    renderPeripherals();
    setPeripheralsMessage(
      `Erreur: ${err && err.message ? err.message : "peripherals indisponible"}`,
      true
    );
  }
}

async function sendPeripheralToggle(id, action) {
  const normalizedAction =
    String(action || "").toLowerCase() === "stop" ? "stop" : "start";
  const res = await fetch("/peripherals/toggle", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, action: normalizedAction }),
  });
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw new Error(detail || "commande refusée");
  }
  const data = await res.json();
  if (data && data.ok === false) {
    const detail =
      data.error !== undefined && data.error !== null
        ? String(data.error)
        : "commande refusée";
    throw new Error(detail);
  }
  return data;
}

function normalizeActuatorDevices(payload) {
  if (Array.isArray(payload)) return payload;
  if (payload && Array.isArray(payload.devices)) return payload.devices;
  return [];
}

function formatActuatorLastCommand(command) {
  if (!command || typeof command !== "object") return "--";
  const action = command.action ? String(command.action) : "?";
  const ts = Number(command.ts);
  const at = Number.isFinite(ts)
    ? formatTime(ts)
    : "--:--:--";
  return `${action} @ ${at}`;
}

function toIntOrNull(value) {
  const n = Number.parseInt(String(value ?? ""), 10);
  return Number.isFinite(n) ? n : null;
}

function rgbNumberToHex(value) {
  const n = toIntOrNull(value);
  if (n === null || n < 0 || n > 16777215) return "#ffffff";
  return `#${n.toString(16).padStart(6, "0")}`;
}

function actuatorViewModel(device) {
  const id = device && device.id ? String(device.id) : "";
  const status = actuatorsStatusById.get(id) || {};
  const merged = { ...(device || {}), ...status };
  const state = merged && typeof merged.state === "object" ? merged.state : {};
  let powerOn = null;
  if (state && typeof state.power_on === "boolean") {
    powerOn = state.power_on;
  } else if (merged.last_command && typeof merged.last_command === "object") {
    const lastAction = String(merged.last_command.action || "").toLowerCase();
    if (lastAction === "on") powerOn = true;
    if (lastAction === "off") powerOn = false;
  }
  const brightRaw = toIntOrNull(state.bright);
  const brightness = brightRaw === null ? 100 : Math.max(1, Math.min(100, brightRaw));
  const colorHex = rgbNumberToHex(state.rgb);
  return {
    id,
    name: String(merged.name || "").trim(),
    powerOn,
    brightness,
    colorHex,
  };
}

function renderActuators() {
  if (!actuatorsList) return;
  actuatorsList.innerHTML = "";
  if (!actuatorsDevices.length) {
    const empty = document.createElement("div");
    empty.className = "actuator-empty";
    empty.textContent = "Aucun actionneur.";
    actuatorsList.appendChild(empty);
    return;
  }
  actuatorsDevices.forEach((device) => {
    const model = actuatorViewModel(device);
    const card = document.createElement("article");
    card.className = "actuator-card";
    card.dataset.actuatorId = model.id;

    const head = document.createElement("div");
    head.className = "actuator-head";
    const title = document.createElement("h3");
    title.textContent = model.name || model.id;
    head.appendChild(title);

    const actions = document.createElement("div");
    actions.className = "actuator-actions";
    const toggleBtn = document.createElement("button");
    toggleBtn.type = "button";
    toggleBtn.className = `actuator-toggle ${
      model.powerOn === true ? "is-on" : "is-off"
    }`;
    toggleBtn.dataset.actuatorAction = "toggle";
    toggleBtn.dataset.actuatorNextAction = model.powerOn === true ? "off" : "on";
    toggleBtn.textContent = model.powerOn === true ? "ON" : "OFF";
    actions.appendChild(toggleBtn);

    const dimmerRow = document.createElement("div");
    dimmerRow.className = "actuator-dimmer";
    const dimmerLabel = document.createElement("span");
    dimmerLabel.textContent = "Intensité";
    const dimmerInput = document.createElement("input");
    dimmerInput.type = "range";
    dimmerInput.min = "1";
    dimmerInput.max = "100";
    dimmerInput.step = "1";
    dimmerInput.value = String(model.brightness);
    dimmerInput.dataset.actuatorAction = "bright";
    const dimmerValue = document.createElement("span");
    dimmerValue.className = "actuator-dimmer-value";
    dimmerValue.textContent = `${model.brightness}%`;
    dimmerRow.appendChild(dimmerLabel);
    dimmerRow.appendChild(dimmerInput);
    dimmerRow.appendChild(dimmerValue);

    const colorRow = document.createElement("div");
    colorRow.className = "actuator-color";
    const colorLabel = document.createElement("span");
    colorLabel.textContent = "Couleur";
    const colorInput = document.createElement("input");
    colorInput.type = "color";
    colorInput.value = model.colorHex;
    colorInput.dataset.actuatorAction = "color";
    const palette = document.createElement("div");
    palette.className = "actuator-color-palette";
    ACTUATOR_COLOR_PRESETS.forEach((hex) => {
      const swatch = document.createElement("button");
      swatch.type = "button";
      swatch.className = "actuator-color-swatch";
      if (hex.toLowerCase() === String(model.colorHex || "").toLowerCase()) {
        swatch.classList.add("is-active");
      }
      swatch.style.backgroundColor = hex;
      swatch.dataset.actuatorAction = "color-preset";
      swatch.dataset.colorValue = hex;
      swatch.title = hex;
      palette.appendChild(swatch);
    });
    colorRow.appendChild(colorLabel);
    colorRow.appendChild(colorInput);
    colorRow.appendChild(palette);

    const renameRow = document.createElement("div");
    renameRow.className = "actuator-rename";
    const nameInput = document.createElement("input");
    nameInput.type = "text";
    nameInput.className = "actuator-name-input";
    nameInput.placeholder = "Nom";
    nameInput.value = model.name || "";
    const validateBtn = document.createElement("button");
    validateBtn.type = "button";
    validateBtn.dataset.actuatorAction = "validate";
    validateBtn.textContent = "Valider";
    renameRow.appendChild(nameInput);
    renameRow.appendChild(validateBtn);

    card.appendChild(head);
    card.appendChild(actions);
    card.appendChild(dimmerRow);
    card.appendChild(colorRow);
    card.appendChild(renameRow);
    actuatorsList.appendChild(card);
  });
}

async function fetchActuatorStatus(id, silent = false) {
  try {
    const res = await fetch(`/actuators/${encodeURIComponent(id)}/status`);
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw new Error(detail || "status indisponible");
    }
    const status = await res.json();
    actuatorsStatusById.set(id, status || {});
    return status;
  } catch (err) {
    if (!silent) {
      setActuatorsMessage(
        `Erreur status ${id}: ${err && err.message ? err.message : "indisponible"}`,
        true
      );
    }
    return null;
  }
}

async function fetchActuators() {
  if (!actuatorsList) return;
  setActuatorsMessage("Chargement...");
  try {
    const res = await fetch("/actuators");
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw new Error(detail || "actuators indisponible");
    }
    const data = await res.json();
    const devices = normalizeActuatorDevices(data)
      .filter((item) => item && item.id)
      .sort((a, b) => String(a.id).localeCompare(String(b.id), "fr"));
    actuatorsDevices = devices;
    await Promise.all(
      devices.map((device) => fetchActuatorStatus(String(device.id), true))
    );
    renderActuators();
    const count = devices.length;
    setActuatorsMessage(`${count} device${count > 1 ? "s" : ""}`);
  } catch (err) {
    actuatorsDevices = [];
    actuatorsStatusById.clear();
    renderActuators();
    setActuatorsMessage(
      `Erreur: ${err && err.message ? err.message : "actuators indisponible"}`,
      true
    );
  }
}

async function sendActuatorCommand(id, action, params) {
  const res = await fetch(`/actuators/${encodeURIComponent(id)}/command`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, params }),
  });
  if (!res.ok) {
    const detail = await readErrorDetail(res);
    throw new Error(detail || "commande refusée");
  }
  const data = await res.json();
  if (data && data.ok === false) {
    const detail =
      data.error !== undefined && data.error !== null
        ? String(data.error)
        : "commande refusée";
    throw new Error(detail);
  }
  return data;
}

async function fetchVisionZones() {
  if (!zonesOverlay) return;
  if (visionZonesInFlight) return;
  visionZonesInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/vision/zones");
    if (!res.ok) throw new Error("zones");
    const data = await res.json();
    visionZones = Array.isArray(data.zones) ? data.zones : [];
    drawZones();
  } catch (err) {
    visionZones = [];
    drawZones();
  } finally {
    visionZonesInFlight = false;
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

function syncSecondaryOverlaySize() {
  if (!zonesOverlaySecondary || !videoStreamSecondary) return;
  const rect = videoStreamSecondary.getBoundingClientRect();
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  if (zonesOverlaySecondary.width !== width) zonesOverlaySecondary.width = width;
  if (zonesOverlaySecondary.height !== height) zonesOverlaySecondary.height = height;
}

function drawZones() {
  if (!zonesOverlay) return;
  const ctx = zonesOverlay.getContext("2d");
  if (!ctx) return;
  syncOverlaySize();
  ctx.clearRect(0, 0, zonesOverlay.width, zonesOverlay.height);
  if (SHOW_STATIC_VISION_ZONES && visionZones.length) {
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

function _toFiniteNumber(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function isBboxLikePolygon(det) {
  if (
    !det ||
    !Array.isArray(det.poly) ||
    det.poly.length !== 4 ||
    !Array.isArray(det.bbox) ||
    det.bbox.length < 4
  ) {
    return false;
  }
  const x = _toFiniteNumber(det.bbox[0]);
  const y = _toFiniteNumber(det.bbox[1]);
  const w = _toFiniteNumber(det.bbox[2]);
  const h = _toFiniteNumber(det.bbox[3]);
  if (x === null || y === null || w === null || h === null) return false;
  const expected = [
    [x, y],
    [x + w, y],
    [x + w, y + h],
    [x, y + h],
  ];
  const tolerancePx = 4;
  for (let i = 0; i < 4; i += 1) {
    const pt = det.poly[i];
    if (!Array.isArray(pt) || pt.length < 2) return false;
    const px = _toFiniteNumber(pt[0]);
    const py = _toFiniteNumber(pt[1]);
    if (px === null || py === null) return false;
    if (
      Math.abs(px - expected[i][0]) > tolerancePx ||
      Math.abs(py - expected[i][1]) > tolerancePx
    ) {
      return false;
    }
  }
  return true;
}

function shouldDrawDetectionOverlay(det, options = {}) {
  if (!det || !Array.isArray(det.poly) || det.poly.length < 3) return false;
  const allowBBoxPolygon = Boolean(options.allowBBoxPolygon);
  if (
    OVERLAY_HIDE_BBOX_POLYGONS &&
    !allowBBoxPolygon &&
    isBboxLikePolygon(det)
  ) {
    return false;
  }
  const minConfidence =
    options.minConfidence !== null && options.minConfidence !== undefined
      ? Number(options.minConfidence)
      : OVERLAY_MIN_CONFIDENCE_PRIMARY;
  if (det.confidence !== null && det.confidence !== undefined) {
    const confidence = Number(det.confidence);
    if (Number.isFinite(confidence) && confidence < minConfidence) {
      return false;
    }
  }
  return true;
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
    if (!shouldDrawDetectionOverlay(det, { minConfidence: OVERLAY_MIN_CONFIDENCE_PRIMARY })) return;
    const baseLabel = det.label || "objet";
    const shapeLabel =
      det.shape !== null && det.shape !== undefined
        ? String(det.shape).trim()
        : "";
    const customLabel = getCustomLabel(det);
    const label = customLabel || (shapeLabel ? `${baseLabel} (${shapeLabel})` : baseLabel);
    const confidence =
      det.confidence !== null && det.confidence !== undefined
        ? Number(det.confidence)
        : null;
    const color = baseLabel === "personne" ? "#22c55e" : "#f59e0b";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    let labelX = 4;
    let labelY = 14;
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
    const text =
      confidence !== null && Number.isFinite(confidence)
        ? `${label} ${(confidence * 100).toFixed(0)}%`
        : label;
    const clampedX = Math.min(Math.max(4, labelX), zonesOverlay.width - 4);
    const clampedY = Math.min(Math.max(14, labelY), zonesOverlay.height - 4);
    ctx.fillText(text, clampedX, clampedY);
  });
}

function drawSecondaryOverlay() {
  if (!zonesOverlaySecondary) return;
  const ctx = zonesOverlaySecondary.getContext("2d");
  if (!ctx) return;
  syncSecondaryOverlaySize();
  ctx.clearRect(0, 0, zonesOverlaySecondary.width, zonesOverlaySecondary.height);
  drawDetectionsSecondary(ctx);
}

function drawDetectionsSecondary(ctx) {
  if (!visionDetectionsSecondary || !visionDetectionsSecondary.length) return;
  const frameW =
    visionFrameSecondary && Number.isFinite(visionFrameSecondary.width)
      ? Number(visionFrameSecondary.width)
      : zonesOverlaySecondary.width;
  const frameH =
    visionFrameSecondary && Number.isFinite(visionFrameSecondary.height)
      ? Number(visionFrameSecondary.height)
      : zonesOverlaySecondary.height;
  const scaleX = frameW ? zonesOverlaySecondary.width / frameW : 1;
  const scaleY = frameH ? zonesOverlaySecondary.height / frameH : 1;
  ctx.lineWidth = 2;
  ctx.font = "12px 'IBM Plex Mono', monospace";
  visionDetectionsSecondary.forEach((det) => {
    if (
      !shouldDrawDetectionOverlay(det, {
        allowBBoxPolygon: true,
        minConfidence: OVERLAY_MIN_CONFIDENCE_SECONDARY,
      })
    ) {
      return;
    }
    const shapeLabel =
      det.shape !== null && det.shape !== undefined
        ? String(det.shape).trim()
        : "";
    const labelBase = det.label || "objet";
    const label = shapeLabel ? `${labelBase} (${shapeLabel})` : labelBase;
    const confidence =
      det.confidence !== null && det.confidence !== undefined
        ? Number(det.confidence)
        : null;
    const color = label === "personne" ? "#22c55e" : "#f59e0b";
    ctx.strokeStyle = color;
    ctx.fillStyle = color;
    let labelX = 4;
    let labelY = 14;
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
    const text =
      confidence !== null && Number.isFinite(confidence)
        ? `${label} ${(confidence * 100).toFixed(0)}%`
        : label;
    const clampedX = Math.min(Math.max(4, labelX), zonesOverlaySecondary.width - 4);
    const clampedY = Math.min(
      Math.max(14, labelY),
      zonesOverlaySecondary.height - 4
    );
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
  if (document.hidden || !isVisionTabActive()) return;
  if (visionDetectionsInFlight) return;
  visionDetectionsInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/vision/detections");
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
  } finally {
    visionDetectionsInFlight = false;
  }
}

async function fetchVisionDetectionsSecondary() {
  if (!zonesOverlaySecondary) return;
  if (document.hidden || !isVisionTabActive()) return;
  if (Date.now() < visionSecondaryBackoffUntil) return;
  if (visionDetectionsSecondaryInFlight) return;
  visionDetectionsSecondaryInFlight = true;
  try {
    const res = await fetchWithAbortTimeout("/vision/detections-secondary");
    if (!res.ok) {
      if (res.status === 503) {
        visionSecondaryBackoffUntil = Date.now() + SERVICE_503_BACKOFF_MS;
      }
      throw new Error("detections-secondary");
    }
    visionSecondaryBackoffUntil = 0;
    const data = await res.json();
    visionDetectionsSecondary = Array.isArray(data.detections)
      ? data.detections
      : [];
    visionFrameSecondary = data.frame || null;
    visionDetectionsSecondaryTs = data.ts || 0;
    drawSecondaryOverlay();
  } catch (err) {
    visionDetectionsSecondary = [];
    visionFrameSecondary = null;
    drawSecondaryOverlay();
  } finally {
    visionDetectionsSecondaryInFlight = false;
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
  if (name === "peripherals") name = "actuators";
  currentActiveTab = name || null;
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
  if (name === "actuators") {
    fetchActuators();
  }
  if (name === "docker") {
    fetchDockerDiagram();
  }
  if (name === "picobot") {
    fetchPicobotStatus(true);
  }
  if (name === "hardware") {
    fetchHardwareModels(true);
  }
  if (name === "vscode") {
    initVscodeFrame(true);
  }
  if (name === "terminal" && edgeTerminalInput) {
    edgeTerminalInput.focus();
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
  if (saved) {
    setActiveTab(saved);
  } else {
    const defaultTab =
      tabButtons.find((btn) => btn.classList.contains("is-active"))?.dataset.tab ||
      tabButtons[0]?.dataset.tab;
    if (defaultTab) setActiveTab(defaultTab);
  }
}

function loadDidierBoostPreference() {
  if (!didierBoost) return;
  try {
    const raw = localStorage.getItem(DIDIER_BOOST_STORAGE_KEY);
    didierBoost.checked = raw === "1" || raw === "true";
  } catch (err) {
    didierBoost.checked = false;
  }
}

function persistDidierBoostPreference() {
  if (!didierBoost) return;
  try {
    localStorage.setItem(DIDIER_BOOST_STORAGE_KEY, didierBoost.checked ? "1" : "0");
  } catch (err) {
    // Ignore storage errors; chat flow must stay operational.
  }
}

async function sendDidierPrompt(prompt) {
  const shouldForceTask = false;
  const boostEnabled = Boolean(didierBoost && didierBoost.checked);
  const startedAtMs = Date.now();
  appendTerminal(didierOutput, `> ${String(prompt || "").trim()}`);
  const traceStartTs = new Date().toISOString();
  appendTerminal(
    didierTechOutput,
    `[${traceStartTs}] prompt="${String(prompt || "").replace(/\s+/g, " ").trim()}" boost=${
      boostEnabled ? "on" : "off"
    }`
  );
  if (thinkingBadge) {
    thinkingBadge.textContent = "Réflexion : en cours";
    thinkingBadge.classList.add("thinking-active");
  }
  try {
    const { controller, clear } = withTimeout(DIDIER_TIMEOUT_MS);
    const res = await fetch("/ask-and-speak", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        prompt,
        source: "didier_chat",
        is_voice: false,
        force_task: shouldForceTask,
        vision_glance: false,
        boost: boostEnabled,
      }),
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
    const doneTs = new Date().toISOString();
    const elapsedMs = Math.max(0, Date.now() - startedAtMs);
    const route = String(
      data.route ||
        (data.routing && data.routing.execution_backend) ||
        (data.routing && data.routing.route_hint) ||
        ""
    ).trim() || "-";
    const audioStatus = String(data.audio_status || "").trim() || "-";
    const reactSource = String(
      (data.react && data.react.source) || data.source || "-"
    ).trim();
    appendTerminal(
      didierTechOutput,
      `[${doneTs}] route=${route} source=${reactSource} audio=${audioStatus} latency_ms=${elapsedMs}`
    );
    const diagnostics =
      data && data.diagnostics && typeof data.diagnostics === "object"
        ? data.diagnostics
        : {};
    const responseDiag =
      diagnostics.response && typeof diagnostics.response === "object"
        ? diagnostics.response
        : {};
    const ttsDiag =
      diagnostics.tts && typeof diagnostics.tts === "object"
        ? diagnostics.tts
        : {};
    const metricsParts = [];
    const responseChars = Number(responseDiag.chars);
    if (Number.isFinite(responseChars)) {
      metricsParts.push(`resp_chars=${Math.max(0, Math.round(responseChars))}`);
    }
    const responseSentences = Number(responseDiag.sentences);
    if (Number.isFinite(responseSentences)) {
      metricsParts.push(`resp_sent=${Math.max(0, Math.round(responseSentences))}`);
    }
    const ttsChars = Number(ttsDiag.chars);
    if (Number.isFinite(ttsChars)) {
      metricsParts.push(`tts_chars=${Math.max(0, Math.round(ttsChars))}`);
    }
    const ttsSentences = Number(ttsDiag.sentences);
    if (Number.isFinite(ttsSentences)) {
      metricsParts.push(`tts_sent=${Math.max(0, Math.round(ttsSentences))}`);
    }
    const queueMs = Number(diagnostics.audio_queue_ms);
    if (Number.isFinite(queueMs)) {
      metricsParts.push(`audio_queue_ms=${Math.max(0, Math.round(queueMs))}`);
    }
    const serverMs = Number(data.server_elapsed_ms);
    if (Number.isFinite(serverMs)) {
      metricsParts.push(`server_ms=${Math.max(0, Math.round(serverMs))}`);
    }
    if (metricsParts.length) {
      appendTerminal(didierTechOutput, `[${doneTs}] metrics ${metricsParts.join(" ")}`);
    }
    const audioNote = String(data.audio_note || "").trim();
    if (audioNote) {
      appendTerminal(didierTechOutput, `[${doneTs}] audio_note=${audioNote}`);
    }
    const audioDetail = String(data.audio_detail || "").trim();
    if (audioDetail) {
      appendTerminal(didierTechOutput, `[${doneTs}] audio_detail=${audioDetail}`);
    }
  } catch (err) {
    if (thinkingBadge) {
      thinkingBadge.textContent = "Réflexion : erreur";
      thinkingBadge.classList.remove("thinking-active");
    }
    const doneTs = new Date().toISOString();
    const elapsedMs = Math.max(0, Date.now() - startedAtMs);
    const timeout = err && err.name === "AbortError";
    appendTerminal(
      didierOutput,
      timeout
        ? "Je n'arrive pas a repondre pour le moment."
        : "Je n'arrive pas a repondre pour le moment."
    );
    appendTerminal(
      didierTechOutput,
      `[${doneTs}] error=${
        timeout
          ? "timeout ask-and-speak"
          : err && err.message
            ? String(err.message)
            : "join failure"
      } latency_ms=${elapsedMs}`
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
startFallbackStatusPolling();
connectMetricsSocket();
setInterval(refreshCpuMetrics, CPU_GRAPH_REFRESH_MS);
fetchAsrStatus();
fetchDeviceStatus();
setInterval(fetchDeviceStatus, 10000);
fetchVisionStatusSecondary();
setInterval(fetchVisionStatusSecondary, SURFACE_STATUS_POLL_MS);
fetchOllamaModels();
setInterval(fetchOllamaModels, 20000);
fetchVersion();
setInterval(fetchVersion, 20000);
fetchVisionZones();
setInterval(fetchVisionZones, 20000);
fetchVisionDetections();
setInterval(fetchVisionDetections, 1500);
fetchVisionDetectionsSecondary();
setInterval(fetchVisionDetectionsSecondary, 2200);
fetchPicobotStatus();
setInterval(fetchPicobotStatus, 4000);
fetchHardwareModels();
setInterval(fetchHardwareModels, 6000);
loadLogo();
loadFallbackLogo(primaryStreamFallbackLogo);
loadFallbackLogo(surfaceStreamFallbackLogo);
if (zonesOverlay) {
  window.addEventListener("resize", () => {
    drawZones();
    drawSecondaryOverlay();
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

if (picobotRefresh) {
  picobotRefresh.addEventListener("click", () => {
    fetchPicobotStatus(true);
  });
}

if (hardwareRefresh) {
  hardwareRefresh.addEventListener("click", () => {
    fetchHardwareModels(true);
  });
}

if (llmfitTableBody) {
  llmfitTableBody.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const button = target.closest("button[data-hardware-action='apply-model']");
    if (!(button instanceof HTMLButtonElement)) return;
    const taskType = String(button.dataset.taskType || "");
    const model = String(button.dataset.model || "");
    const backend = String(button.dataset.backend || "");
    applyRecommendedModel({ task_type: taskType, model, backend });
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
    lastPrimaryStreamLoadAt = Date.now();
    setPrimaryFallback(false);
    if (initialLoadTimer) {
      clearTimeout(initialLoadTimer);
      initialLoadTimer = null;
    }
    drawZones();
  };

  videoStream.onerror = () => {
    videoLoaded = false;
    setPrimaryFallback(true, "Flux indisponible. Verifie /dev/video0.");
    const now = Date.now();
    if (!lastVideoErrorAt || now - lastVideoErrorAt > 15000) {
      if (cameraHoldersOutput) {
        cameraHoldersOutput.textContent =
          "Flux vidéo indisponible. Vérifie /dev/video0.";
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
  setPrimaryFallback(true, "En attente de /video/stream...");
}

setInterval(() => {
  if (document.hidden || !isVisionTabActive()) return;
  const now = Date.now();
  if (videoStream && VIDEO_KEEPALIVE_REFRESH_MS > 0) {
    if (!lastPrimaryStreamLoadAt) lastPrimaryStreamLoadAt = now;
    if (now - lastPrimaryStreamLoadAt > VIDEO_KEEPALIVE_REFRESH_MS) {
      lastPrimaryStreamLoadAt = now;
      videoStream.src = `/video/stream?ts=${now}`;
    }
  }
  if (videoStreamSecondary && VIDEO_KEEPALIVE_REFRESH_MS > 0) {
    if (!lastSecondaryStreamLoadAt) lastSecondaryStreamLoadAt = now;
    if (now - lastSecondaryStreamLoadAt > VIDEO_KEEPALIVE_REFRESH_MS) {
      lastSecondaryStreamLoadAt = now;
      videoStreamSecondary.src = `/video/stream-secondary?ts=${now}`;
    }
  }
}, 5000);

if (codingForm && codingPrompt) {
  codingForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const prompt = codingPrompt.value.trim();
    if (!prompt) return;
    codingPrompt.value = "";
    sendCodingPrompt(prompt);
  });
}

async function initVscodeFrame(force = false) {
  if (!vscodeFrame) return;
  if (vscodeInitInFlight && !force) return;
  vscodeInitInFlight = true;
  try {
    const host = window.location.hostname;
    const isHttps = window.location.protocol === "https:";
    const projectFolder = "/home/coder/project";
    const folderQuery = `?folder=${encodeURIComponent(projectFolder)}`;
    const proxyUrl = `${window.location.origin}/vscode/${folderQuery}`;
    const directUrl = `${isHttps ? "http:" : window.location.protocol}//${host}:8080/${folderQuery}`;
    if (vscodeDirectLink) vscodeDirectLink.href = directUrl;

    let proxyOk = false;
    try {
      const res = await fetch("/vscode/", { cache: "no-store" });
      proxyOk = res.ok || (res.status >= 300 && res.status < 400);
    } catch (_err) {
      proxyOk = false;
    }

    if (proxyOk) {
      if (vscodeFallback) vscodeFallback.hidden = true;
      vscodeFrame.src = proxyUrl;
      return;
    }

    if (vscodeFallback) vscodeFallback.hidden = false;
    if (isHttps) {
      // Browsers block insecure iframe content when UI runs on HTTPS.
      vscodeFrame.src = "about:blank";
      return;
    }
    let directReachable = false;
    try {
      await fetch(directUrl, { cache: "no-store", mode: "no-cors" });
      directReachable = true;
    } catch (_err) {
      directReachable = false;
    }
    if (!directReachable) {
      if (vscodeFallback) vscodeFallback.hidden = false;
      vscodeFrame.src = "about:blank";
      return;
    }
    if (vscodeFallback) vscodeFallback.hidden = true;
    vscodeFrame.src = directUrl;
  } finally {
    vscodeInitInFlight = false;
  }
}

initVscodeFrame();

if (edgeTerminalOutput) {
  appendTerminal(edgeTerminalOutput, "Didier Terminal prêt.");
  appendTerminal(edgeTerminalOutput, "Exemples: ls -la, df -h, systemctl --failed");
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

if (actuatorsRefresh) {
  actuatorsRefresh.addEventListener("click", () => {
    fetchActuators();
  });
}

if (peripheralsRefresh) {
  peripheralsRefresh.addEventListener("click", () => {
    fetchPeripherals();
  });
}

if (peripheralsList) {
  peripheralsList.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-peripheral-action]");
    if (!button) return;
    const action = String(button.dataset.peripheralAction || "").toLowerCase();
    const id = String(button.dataset.peripheralId || "").trim();
    if (!id || (action !== "start" && action !== "stop")) return;
    const card = button.closest(".peripheral-card");
    const titleEl = card ? card.querySelector(".peripheral-title") : null;
    const label = titleEl ? String(titleEl.textContent || "").trim() : id;
    const actionText = action === "start" ? "Activation" : "Désactivation";

    const cardButtons = card
      ? Array.from(card.querySelectorAll("button[data-peripheral-action]"))
      : [button];
    cardButtons.forEach((btn) => {
      btn.disabled = true;
    });

    setPeripheralsMessage(`${actionText} ${label}...`);
    try {
      const data = await sendPeripheralToggle(id, action);
      await fetchPeripherals();
      const afterState =
        data && data.after && data.after.active === true ? "connecté" : "déconnecté";
      setPeripheralsMessage(
        `${label} ${action === "start" ? "activé" : "désactivé"} (${afterState})`
      );
    } catch (err) {
      const verb = action === "start" ? "démarrer" : "arrêter";
      setPeripheralsMessage(
        `Impossible de ${verb} ${label}: ${err && err.message ? err.message : "échec"}`,
        true
      );
    } finally {
      cardButtons.forEach((btn) => {
        btn.disabled = false;
      });
    }
  });
}

if (actuatorsList) {
  const queueRealtimeCommand = (id, action, params, delayMs = 120) => {
    const key = `${id}:${action}`;
    const previous = actuatorRealtimeTimers.get(key);
    if (previous) clearTimeout(previous);
    const timer = setTimeout(async () => {
      actuatorRealtimeTimers.delete(key);
      try {
        await sendActuatorCommand(id, action, params);
      } catch (err) {
        setActuatorsMessage(
          `Erreur ${action}: ${err && err.message ? err.message : "échec"}`,
          true
        );
      }
    }, delayMs);
    actuatorRealtimeTimers.set(key, timer);
  };

  actuatorsList.addEventListener("input", (event) => {
    const range = event.target.closest('input[type="range"][data-actuator-action="bright"]');
    if (!range) return;
    const row = range.closest(".actuator-dimmer");
    const valueEl = row ? row.querySelector(".actuator-dimmer-value") : null;
    if (valueEl) {
      const value = Number(range.value || 100);
      valueEl.textContent = `${Math.max(1, Math.min(100, value))}%`;
    }
    const card = range.closest(".actuator-card");
    if (!card) return;
    const id = card.dataset.actuatorId;
    if (!id) return;
    const value = Number.parseInt(String(range.value || "100"), 10);
    queueRealtimeCommand(
      id,
      "bright",
      { value: Math.max(1, Math.min(100, Number.isFinite(value) ? value : 100)) },
      120
    );
  });

  actuatorsList.addEventListener("click", async (event) => {
    const button = event.target.closest("button[data-actuator-action]");
    if (!button) return;
    const card = button.closest(".actuator-card");
    if (!card) return;
    const id = card.dataset.actuatorId;
    const action = button.dataset.actuatorAction;
    if (!id || !action) return;
    if (action === "color-preset") {
      const hex = String(button.dataset.colorValue || "#ffffff");
      const colorInput = card.querySelector('input[type="color"][data-actuator-action="color"]');
      if (colorInput) colorInput.value = hex;
      setActuatorsMessage("Envoi color...");
      button.disabled = true;
      try {
        await sendActuatorCommand(id, "color", { value: hex });
        await fetchActuatorStatus(id, true);
        renderActuators();
        setActuatorsMessage("Commande color envoyée");
      } catch (err) {
        setActuatorsMessage(
          `Erreur color: ${err && err.message ? err.message : "échec"}`,
          true
        );
      } finally {
        button.disabled = false;
      }
      return;
    }
    const effectiveAction =
      action === "toggle"
        ? String(button.dataset.actuatorNextAction || "on").toLowerCase()
        : action;
    const nameInput = card.querySelector(".actuator-name-input");
    const params =
      effectiveAction === "validate"
        ? { name: nameInput ? String(nameInput.value || "").trim() : "" }
        : {};
    setActuatorsMessage(`Envoi ${effectiveAction}...`);
    button.disabled = true;
    try {
      await sendActuatorCommand(id, effectiveAction, params);
      await fetchActuatorStatus(id, true);
      renderActuators();
      setActuatorsMessage(`Commande ${effectiveAction} envoyée`);
    } catch (err) {
      setActuatorsMessage(
        `Erreur ${effectiveAction}: ${err && err.message ? err.message : "échec"}`,
        true
      );
    } finally {
      button.disabled = false;
    }
  });

  actuatorsList.addEventListener("change", async (event) => {
    const input = event.target.closest("input[data-actuator-action]");
    if (!input) return;
    const card = input.closest(".actuator-card");
    if (!card) return;
    const id = card.dataset.actuatorId;
    const action = String(input.dataset.actuatorAction || "").toLowerCase();
    if (!id || !action) return;
    if (action !== "color") return;

    let params = {};
    params = { value: String(input.value || "#ffffff") };

    input.disabled = true;
    setActuatorsMessage(`Envoi ${action}...`);
    try {
      await sendActuatorCommand(id, action, params);
      await fetchActuatorStatus(id, true);
      renderActuators();
      setActuatorsMessage(`Commande ${action} envoyée`);
    } catch (err) {
      setActuatorsMessage(
        `Erreur ${action}: ${err && err.message ? err.message : "échec"}`,
        true
      );
    } finally {
      input.disabled = false;
    }
  });
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

async function runEdgeTerminalCommand(command) {
  const cmd = String(command || "").trim();
  if (!cmd) return;
  appendTerminal(edgeTerminalOutput, `$ ${cmd}`);
  try {
    const { controller, clear } = withTimeout(TERMINAL_TIMEOUT_MS);
    const res = await fetch("/terminal/exec", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ command: cmd }),
      signal: controller.signal,
    });
    clear();
    if (!res.ok) {
      const detail = await readErrorDetail(res);
      throw new Error(detail || "commande refusée");
    }
    const data = await res.json();
    const out = String(data.output || "").trim();
    appendTerminal(edgeTerminalOutput, out || "(aucune sortie)");
    appendTerminal(
      edgeTerminalOutput,
      `[exit:${Number(data.exit_code || 0)} · ${Number(data.elapsed_ms || 0)}ms]`
    );
  } catch (err) {
    const timeout = err && err.name === "AbortError";
    appendTerminal(
      edgeTerminalOutput,
      timeout
        ? "Erreur: timeout commande"
        : `Erreur: ${err && err.message ? err.message : "execution impossible"}`
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

if (didierBoost) {
  loadDidierBoostPreference();
  didierBoost.addEventListener("change", () => {
    persistDidierBoostPreference();
  });
}

if (edgeTerminalForm && edgeTerminalInput) {
  edgeTerminalForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const command = edgeTerminalInput.value.trim();
    if (!command) return;
    edgeTerminalInput.value = "";
    await runEdgeTerminalCommand(command);
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
