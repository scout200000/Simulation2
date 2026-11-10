const SETTINGS_KEY = "simulation2.settings";

export const DEFAULT_MODEL = "deepseek-v4-flash";

export const DEFAULT_AGENTS = Object.freeze({
  count: 30,
  density: "medium",
  zoom: 1,
  showLabels: true
});

export const DEFAULT_UI = Object.freeze({
  showTokenStats: true
});

export const DEFAULT_OPINION_POOL = Object.freeze({
  source: "generate",
  generateCount: 60,
  harvestCount: 40,
  harvestVideos: 3
});

export const AGENT_DENSITIES = Object.freeze({
  low: 0.18,
  medium: 0.3,
  high: 0.55
});

const DENSITY_KEYS = Object.keys(AGENT_DENSITIES);

function clamp(value, minimum, maximum) {
  const number = Number(value);
  if (!Number.isFinite(number)) return minimum;
  return Math.min(maximum, Math.max(minimum, number));
}

export function normalizeAgents(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  return {
    count: Math.round(clamp(source.count ?? DEFAULT_AGENTS.count, 10, 60) / 5) * 5,
    density: DENSITY_KEYS.includes(source.density)
      ? source.density
      : DEFAULT_AGENTS.density,
    zoom: Math.round(clamp(source.zoom ?? DEFAULT_AGENTS.zoom, 0.8, 1.3) * 100) / 100,
    showLabels:
      source.showLabels === undefined && source.showEmotion === undefined
        ? DEFAULT_AGENTS.showLabels
        : Boolean(source.showLabels ?? source.showEmotion)
  };
}

export function normalizeUi(value = {}) {
  const source = value && typeof value === "object" ? value : {};
  return {
    showTokenStats: source.showTokenStats !== false
  };
}

export function normalizeOpinionPool(value = {}) {
  const source = value && value.source === "harvest" ? "harvest" : "generate";
  return {
    source,
    generateCount:
      Math.round(clamp(value && value.generateCount, 30, 120) / 10) * 10 ||
      DEFAULT_OPINION_POOL.generateCount,
    harvestCount:
      Math.round(clamp(value && value.harvestCount, 20, 120) / 10) * 10 ||
      DEFAULT_OPINION_POOL.harvestCount,
    harvestVideos: Math.round(clamp(value && value.harvestVideos, 1, 5)) ||
      DEFAULT_OPINION_POOL.harvestVideos
  };
}

/** 转成后端 opinion_pool_config：只提交本次会话需要的字段。 */
export function opinionPoolRequestConfig(value) {
  const pool = normalizeOpinionPool(value);
  return {
    source: pool.source,
    generate: { comment_count: pool.generateCount },
    harvest: {
      comment_count: pool.harvestCount,
      videos: pool.harvestVideos
    }
  };
}

export function getSettings() {
  try {
    const raw = sessionStorage.getItem(SETTINGS_KEY);
    const saved = raw ? JSON.parse(raw) : {};
    return {
      apiKey: saved.apiKey || "",
      model: saved.model || DEFAULT_MODEL,
      agents: normalizeAgents(saved.agents),
      ui: normalizeUi(saved.ui),
      opinionPool: normalizeOpinionPool(saved.opinionPool)
    };
  } catch {
    return {
      apiKey: "",
      model: DEFAULT_MODEL,
      agents: { ...DEFAULT_AGENTS },
      ui: { ...DEFAULT_UI },
      opinionPool: { ...DEFAULT_OPINION_POOL }
    };
  }
}

export function saveSettings(settings) {
  const payload = {
    apiKey: String(settings.apiKey || "").trim(),
    model: settings.model || DEFAULT_MODEL,
    agents: normalizeAgents(settings.agents),
    ui: normalizeUi(settings.ui),
    opinionPool: normalizeOpinionPool(settings.opinionPool)
  };
  sessionStorage.setItem(SETTINGS_KEY, JSON.stringify(payload));
  return payload;
}

export function clearSettings() {
  sessionStorage.removeItem(SETTINGS_KEY);
}
