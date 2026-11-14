// ─── Local dashboard API client ──────────────────────────────────────────────
// The backend binds loopback only and allows this exact dashboard origin.

const API_HOST =
  typeof window !== "undefined" && window.location.hostname === "localhost"
    ? "localhost"
    : "127.0.0.1";
const API_BASE = `http://${API_HOST}:8765/api/v1`;

export class ApiError extends Error {
  constructor(status, data) {
    const detail =
      Array.isArray(data?.details) && data.details.length > 0
        ? data.details[0]
        : null;
    const message =
      (data && (detail || data.error || data.message)) ||
      (status === 0 ? "network_error" : `Request failed (${status})`);
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

export async function apiFetch(
  path,
  { method = "GET", body, csrf, timeoutMs = 10000 } = {},
) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let res;
  try {
    res = await fetch(API_BASE + path, {
      credentials: "include",
      headers: {
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
        ...(csrf ? { "X-CSRF-Token": csrf } : {}),
      },
      method,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      signal: controller.signal,
    });
  } catch {
    throw new ApiError(0, { error: "network_error" });
  } finally {
    clearTimeout(timer);
  }

  let data = null;
  const text = await res.text();
  if (text) {
    try {
      data = JSON.parse(text);
    } catch {
      data = { error: "invalid_response" };
    }
  }

  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  getSession: () => apiFetch("/session"),
  pair: (code) => apiFetch("/pair", { method: "POST", body: { code } }),
  logout: (csrf) => apiFetch("/logout", { method: "POST", csrf }),
  getStatus: () => apiFetch("/status"),
  getSettings: () => apiFetch("/settings"),
  savePrefix: (prefix, csrf) =>
    apiFetch("/settings/prefix", { method: "PUT", body: { prefix }, csrf }),
  requestReload: (csrf) =>
    apiFetch("/settings/reload", { method: "POST", csrf }),
  getCapabilities: () => apiFetch("/capabilities"),
  getAutomation: () => apiFetch("/automation"),
  saveAutomation: (data, csrf) =>
    apiFetch("/automation", { method: "PUT", body: data, csrf }),
  getAfk: () => apiFetch("/afk"),
  saveAfk: (data, csrf) =>
    apiFetch("/afk", { method: "PUT", body: data, csrf }),
  getReactions: () => apiFetch("/reactions"),
  saveReactions: (data, csrf) =>
    apiFetch("/reactions", { method: "PUT", body: data, csrf }),
  utilityWeather: (data, csrf) =>
    apiFetch("/utility/weather", { method: "POST", body: data, csrf }),
  utilityImage: (data, csrf) =>
    apiFetch("/utility/image", { method: "POST", body: data, csrf }),
  utilityEmojiCopy: (data, csrf) =>
    apiFetch("/utility/emoji-copy", { method: "POST", body: data, csrf }),
  utilityClone: (data, csrf) =>
    apiFetch("/utility/clone", { method: "POST", body: data, csrf }),
  getCloneStatus: (requestId) =>
    apiFetch(
      `/utility/clone/status?request_id=${encodeURIComponent(requestId)}`,
    ),
  getEmojiCopyStatus: (requestId) =>
    apiFetch(
      `/utility/emoji-copy/status?request_id=${encodeURIComponent(requestId)}`,
    ),
  getVoiceTokens: () => apiFetch("/voice/tokens"),
  getPresenceConfig: () => apiFetch("/presence/config"),
  savePresenceConfig: (data, csrf) =>
    apiFetch("/presence/config", { method: "PUT", body: data, csrf }),
  applyPresence: (data, csrf) =>
    apiFetch("/presence/apply", { method: "POST", body: data, csrf }),
  clearPresence: (data, csrf) =>
    apiFetch("/presence/clear", { method: "POST", body: data, csrf }),
  getSongs: () => apiFetch("/presence/songs"),
  saveSongs: (data, csrf) =>
    apiFetch("/presence/songs", { method: "PUT", body: data, csrf }),
  resolveSong: (data, csrf) =>
    apiFetch("/presence/songs/resolve", { method: "POST", body: data, csrf }),
  resolveYouTube: (data, csrf) =>
    apiFetch("/presence/youtube/resolve", { method: "POST", body: data, csrf }),
  uploadPresenceImage: (data, csrf) =>
    apiFetch("/presence/upload-image", {
      method: "POST",
      body: data,
      csrf,
      // The endpoint accepts up to 700 KB and forwards to catbox, which can
      // take far longer than the default 10s budget.
      timeoutMs: 60000,
    }),
  addVoiceToken: (data, csrf) =>
    apiFetch("/voice/tokens", { method: "POST", body: data, csrf }),
  deleteVoiceToken: (data, csrf) =>
    apiFetch("/voice/tokens", { method: "DELETE", body: data, csrf }),
  searchVoice: (query, csrf) =>
    apiFetch("/voice/search", { method: "POST", body: { query }, csrf }),
  setVoiceStream: (data, csrf) =>
    apiFetch("/voice/stream", { method: "POST", body: data, csrf }),
  setVoiceCamera: (data, csrf) =>
    apiFetch("/voice/camera", { method: "POST", body: data, csrf }),
  getVoiceSoundboard: (guildId, tokenIndex) =>
    apiFetch(
      `/voice/soundboard?guild_id=${encodeURIComponent(guildId)}&token_index=${tokenIndex}`,
    ),
  getVoiceDefaultSounds: (tokenIndex) =>
    apiFetch(`/voice/soundboard/defaults?token_index=${tokenIndex}`),
  playVoiceSound: (data, csrf) =>
    apiFetch("/voice/soundboard/play", { method: "POST", body: data, csrf }),
  joinVoice: (data, csrf) =>
    apiFetch("/voice/join", { method: "POST", body: data, csrf }),
  leaveVoice: (data, csrf) =>
    apiFetch("/voice/leave", { method: "POST", body: data, csrf }),
  moveVoice: (data, csrf) =>
    apiFetch("/voice/move", { method: "POST", body: data, csrf }),
  setVoiceState: (data, csrf) =>
    apiFetch("/voice/state", { method: "POST", body: data, csrf }),
  setVoiceFilters: (tokenIndex, filters, bassLevel, csrf) =>
    apiFetch("/voice/audio/filters", {
      method: "POST",
      body: {
        token_index: tokenIndex,
        filters,
        ...(bassLevel !== null && bassLevel !== undefined
          ? { bass_level: bassLevel }
          : {}),
      },
      csrf,
    }),
  setVoiceVolume: (tokenIndex, volume, csrf) =>
    apiFetch("/voice/audio/volume", {
      method: "POST",
      body: { token_index: tokenIndex, volume },
      csrf,
    }),
  setVoiceLoop: (tokenIndex, mode, csrf) =>
    apiFetch("/voice/audio/loop", {
      method: "POST",
      body: { token_index: tokenIndex, mode },
      csrf,
    }),
  replayVoice: (tokenIndex, csrf) =>
    apiFetch("/voice/audio/replay", {
      method: "POST",
      body: { token_index: tokenIndex },
      csrf,
    }),
  forcefixVoice: (tokenIndex, csrf) =>
    apiFetch("/voice/audio/forcefix", {
      method: "POST",
      body: { token_index: tokenIndex },
      csrf,
    }),
};

// ─── Response normalizers ────────────────────────────────────────────────────
// The backend may expose bot fields nested under `bot` or flat. Accept both so
// a small backend shape change never produces fake-looking dashboard values.

export function normalizeStatus(raw) {
  if (!raw || typeof raw !== "object") return null;
  const bot = raw.bot && typeof raw.bot === "object" ? raw.bot : {};
  const user = bot.user && typeof bot.user === "object" ? bot.user : {};
  const api = raw.api && typeof raw.api === "object" ? raw.api : {};

  return {
    apiVersion:
      raw.api_version ?? raw.apiVersion ?? raw.version ?? api.version ?? null,
    uptimeSeconds:
      raw.uptime_seconds ??
      raw.uptimeSeconds ??
      raw.uptime ??
      api.uptime_seconds ??
      null,
    lastReload: raw.last_reload ?? null,
    bot: {
      state:
        bot.state ??
        raw.bot_state ??
        (bot.configured === false ? "not_configured" : "unknown"),
      username:
        bot.username ?? user.username ?? raw.username ?? raw.bot_username ?? null,
      displayName:
        bot.display_name ??
        bot.displayName ??
        user.global_name ??
        user.displayName ??
        null,
      userId:
        bot.user_id ??
        bot.id ??
        user.id ??
        user.user_id ??
        raw.bot_user_id ??
        raw.user_id ??
        null,
      applicationId:
        bot.application_id ??
        user.application_id ??
        raw.application_id ??
        raw.app_id ??
        null,
      avatarUrl:
        bot.avatar_url ??
        bot.avatarUrl ??
        bot.avatar ??
        user.avatar_url ??
        user.avatarUrl ??
        user.avatar ??
        raw.avatar_url ??
        raw.avatarUrl ??
        null,
      guildCount: bot.guild_count ?? raw.guild_count ?? null,
      latencyMs: bot.latency_ms ?? bot.latency ?? raw.latency_ms ?? null,
    },
    warnings: Array.isArray(raw.warnings) ? raw.warnings : [],
  };
}

export function normalizeCapabilities(raw) {
  const list = Array.isArray(raw)
    ? raw
    : raw && Array.isArray(raw.features)
      ? raw.features
      : raw && Array.isArray(raw.capabilities)
        ? raw.capabilities
        : [];

  return list.map((item, index) => ({
    id: item?.id ?? item?.key ?? `feature-${index}`,
    label: item?.label ?? item?.name ?? item?.id ?? "Feature",
    status:
      item?.status ??
      (item?.available === true
        ? "available"
        : item?.available === false
          ? "needs_config"
          : "unknown"),
    reason: item?.reason ?? item?.detail ?? null,
  }));
}

export function formatUptime(seconds) {
  if (seconds === null || seconds === undefined || seconds === "") return "—";
  const total = Number(seconds);
  if (!Number.isFinite(total) || total < 0) return "—";

  const d = Math.floor(total / 86400);
  const h = Math.floor((total % 86400) / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = Math.floor(total % 60);

  if (d > 0) return `${d}d ${h}h ${m}m`;
  if (h > 0) return `${h}h ${m}m`;
  if (m > 0) return `${m}m ${s}s`;
  return `${s}s`;
}
