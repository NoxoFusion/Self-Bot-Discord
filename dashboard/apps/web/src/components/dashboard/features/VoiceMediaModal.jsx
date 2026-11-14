"use client";
import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Hash,
  Info,
  ListMusic,
  ListPlus,
  Loader2,
  Music2,
  Play,
  RefreshCw,
  RotateCcw,
  Search,
  SkipForward,
  SlidersHorizontal,
  Square,
  Users,
  Volume2,
  X,
} from "lucide-react";
import Modal from "../Modal";
import Toggle from "../Toggle";
import { api, apiFetch } from "../../../lib/api";
import { useSessionContext } from "../../../lib/session";
import { useAccent } from "../../../lib/theme";

const QUEUE_POLL_MS = 3000;
const SLIDER_DEBOUNCE_MS = 500;
const SNOWFLAKE_RE = /^\d{17,20}$/;

const IDLE_STATUS = { kind: "idle", message: "Ready." };

const BASS_FILTER_KEY = "bass";
const EFFECT_OPTIONS = [
  { key: "soft", label: "Soft" },
  { key: "lofi", label: "Lo-Fi" },
  { key: "slowed reverb", label: "Slowed Reverb" },
  { key: "reverb", label: "Reverb" },
  { key: "sped up", label: "Sped Up" },
  { key: "dolby", label: "Dolby" },
  { key: "8d", label: "8D" },
  { key: "concert", label: "Concert" },
  { key: "instrumental", label: "Instrumental" },
];
const BASS_LEVEL_DEFAULT = 100;
const BASS_LEVEL_SERVER_DEFAULT = 10;
const BASS_LEVEL_MIN = 1;
const BASS_LEVEL_MAX = 999;
const VOLUME_DEFAULT = 100;
const VOLUME_MIN = 0;
const VOLUME_MAX = 200;

const LOOP_MODES = [
  { value: "off", label: "Off" },
  { value: "track", label: "Track" },
  { value: "queue", label: "Queue" },
];

const EMPTY_QUEUE = {
  nowPlaying: null,
  items: [],
  filters: [],
  bassLevel: BASS_LEVEL_SERVER_DEFAULT,
  volume: VOLUME_DEFAULT,
  loopMode: "off",
  positionMs: 0,
  lengthMs: null,
};

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]";

function tokenName(token) {
  return (
    token?.username || token?.display_name || `Token #${token?.index ?? "?"}`
  );
}

function tokenLabel(token) {
  const name = token?.username || token?.display_name;
  return name ? `#${token.index} ${name}` : `#${token.index}`;
}

const ERROR_LABELS = {
  bot_offline: "Bot is offline — start it before queueing playback.",
  voice_unavailable: "Voice control is not available.",
};

function errorMessage(err, fallback) {
  const details = Array.isArray(err?.data?.details)
    ? err.data.details.join(" · ")
    : null;
  if (details) return details;
  const code = err?.data?.error;
  if (code && ERROR_LABELS[code]) return ERROR_LABELS[code];
  return code || err?.message || fallback;
}

function formatDuration(value) {
  if (value === null || value === undefined || value === "") return "LIVE";
  const total = Number(value);
  if (!Number.isFinite(total) || total < 0) return "LIVE";
  const minutes = Math.floor(total / 60);
  const seconds = Math.floor(total % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function formatClock(value) {
  const total = Math.max(0, Number(value) || 0);
  const minutes = Math.floor(total / 60);
  const seconds = Math.floor(total % 60);
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}

function toInt(value, fallback) {
  if (typeof value === "number" && Number.isFinite(value)) {
    return Math.trunc(value);
  }
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.trunc(parsed);
  }
  return fallback;
}

function normalizeLoopMode(value) {
  return value === "track" || value === "queue" ? value : "off";
}

function itemTitle(item) {
  if (typeof item === "string") return item.trim();
  if (typeof item === "number") return String(item);
  if (!item || typeof item !== "object") return "";

  const direct =
    item.title ?? item.name ?? item.query ?? item.url ?? item.track_title;
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  if (typeof item.track === "string" && item.track.trim()) {
    return item.track.trim();
  }
  if (item.track && typeof item.track === "object") {
    return itemTitle(item.track);
  }
  return "";
}

function normalizeQueue(raw) {
  if (Array.isArray(raw)) {
    return {
      ...EMPTY_QUEUE,
      items: raw.map(itemTitle).filter(Boolean),
    };
  }

  let source = raw && typeof raw === "object" ? raw : {};
  if (source.audio && typeof source.audio === "object") {
    source = source.audio;
  }
  if (
    source.data &&
    typeof source.data === "object" &&
    !Array.isArray(source.data)
  ) {
    source = source.data;
  }

  const nowRaw =
    source.now_playing ??
    source.nowPlaying ??
    source.current ??
    source.current_track ??
    source.title ??
    source.track ??
    null;
  const queuedRaw =
    source.queue ??
    source.items ??
    source.upcoming ??
    source.up_next ??
    source.tracks ??
    [];
  const queuedList = Array.isArray(queuedRaw)
    ? queuedRaw
    : Array.isArray(queuedRaw?.items)
      ? queuedRaw.items
      : Array.isArray(queuedRaw?.tracks)
        ? queuedRaw.tracks
        : [];
  const filters = Array.isArray(source.filters)
    ? source.filters.filter((name) => typeof name === "string")
    : [];
  const lengthValue = source.length_ms ?? source.lengthMs;
  const parsedLength =
    lengthValue === null || lengthValue === undefined || lengthValue === ""
      ? null
      : toInt(lengthValue, null);

  return {
    nowPlaying: itemTitle(nowRaw) || null,
    items: queuedList.map(itemTitle).filter(Boolean),
    filters,
    bassLevel: toInt(
      source.bass_level ?? source.bassLevel,
      BASS_LEVEL_SERVER_DEFAULT,
    ),
    volume: toInt(source.volume_pct ?? source.volumePct, 100),
    loopMode: normalizeLoopMode(source.loop_mode ?? source.loopMode),
    positionMs: Math.max(0, toInt(source.position_ms ?? source.positionMs, 0)),
    lengthMs: parsedLength === null ? null : Math.max(0, parsedLength),
  };
}

function usableTokens(tokens) {
  if (!Array.isArray(tokens)) return [];
  return tokens.filter((token) => {
    if (!token || typeof token !== "object") return false;
    const index = token.index;
    return index !== null && index !== undefined && String(index).trim() !== "";
  });
}

function StatusLine({ status, accent, idleMessage = "Ready." }) {
  const kind = status?.kind || "idle";
  const color =
    kind === "error"
      ? "#FCA5A5"
      : kind === "success"
        ? "#23A55A"
        : kind === "working"
          ? accent
          : "#94A3B8";
  const Icon =
    kind === "error"
      ? AlertTriangle
      : kind === "success"
        ? CheckCircle2
        : kind === "working"
          ? Loader2
          : Info;

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex flex-1 items-center gap-1.5 min-w-0 text-xs"
      style={{ color }}
    >
      <Icon
        size={12}
        className={`shrink-0 ${kind === "working" ? "animate-spin" : ""}`}
      />
      <span className="truncate">{status?.message || idleMessage}</span>
    </div>
  );
}

function SectionHeader({ icon: Icon, label, accent, children }) {
  return (
    <div className="flex items-center gap-2 min-w-0">
      <span
        className="flex items-center gap-1.5 text-xs font-semibold shrink-0"
        style={{
          color: "#94A3B8",
          fontFamily: "var(--font-display)",
          letterSpacing: "0.01em",
        }}
      >
        <Icon size={12} style={{ color: accent }} />
        {label}
      </span>
      <div className="flex-1" />
      {children}
    </div>
  );
}

export default function VoiceMediaModal({
  open,
  onClose,
  tokens = [],
  toast,
}) {
  const ACCENT = useAccent();
  const session = useSessionContext();

  const [selectedIndex, setSelectedIndex] = useState("");
  const [channelId, setChannelId] = useState("");
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(null);
  const [status, setStatus] = useState(IDLE_STATUS);
  const [queue, setQueue] = useState(EMPTY_QUEUE);
  const [queueError, setQueueError] = useState(null);
  const [queueLoading, setQueueLoading] = useState(false);
  const [results, setResults] = useState([]);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState(null);
  const [bassOn, setBassOn] = useState(false);
  const [selectedEffect, setSelectedEffect] = useState(null);
  const [bassLevel, setBassLevel] = useState(BASS_LEVEL_DEFAULT);
  const [volume, setVolume] = useState(VOLUME_DEFAULT);
  const [loopMode, setLoopMode] = useState("off");
  const [positionMs, setPositionMs] = useState(0);
  const [lengthMs, setLengthMs] = useState(null);
  const volumeTimerRef = useRef(null);
  const bassTimerRef = useRef(null);
  const pendingLoopRef = useRef(null);
  const pendingFiltersRef = useRef(null);
  const activeFiltersRef = useRef([]);
  const busyRef = useRef(null);

  const activeFilters = useMemo(() => {
    const list = [];
    if (bassOn) list.push(BASS_FILTER_KEY);
    if (selectedEffect) list.push(selectedEffect);
    return list;
  }, [bassOn, selectedEffect]);

  const queueActive = Boolean(queue.nowPlaying) || queue.items.length > 0;
  const hasLength = Number.isFinite(lengthMs) && lengthMs > 0;
  const clampedPositionMs = hasLength
    ? Math.min(Math.max(positionMs, 0), lengthMs)
    : 0;
  const progressPct = hasLength
    ? (clampedPositionMs / lengthMs) * 100
    : 0;

  useEffect(() => {
    activeFiltersRef.current = activeFilters;
  }, [activeFilters]);

  const availableTokens = useMemo(() => usableTokens(tokens), [tokens]);

  const selectedToken = useMemo(() => {
    if (!availableTokens.length) return null;
    return (
      availableTokens.find(
        (token) => String(token.index) === selectedIndex,
      ) || availableTokens[0]
    );
  }, [availableTokens, selectedIndex]);

  useEffect(() => {
    if (!open) return;
    if (!availableTokens.length) {
      setSelectedIndex("");
      return;
    }
    setSelectedIndex((previous) =>
      availableTokens.some((token) => String(token.index) === previous)
        ? previous
        : String(
            (
              availableTokens.find((token) => token.channels?.length) ||
              availableTokens[0]
            ).index,
          ),
    );
  }, [open, availableTokens]);

  useEffect(() => {
    if (!open) {
      setResults([]);
      setSearchError(null);
      return;
    }
    // The channel is always manual: never prefill it from cached token data.
    // Results belong to the previous token/session, so dismiss them too.
    setChannelId("");
    setResults([]);
    setSearchError(null);
  }, [open, selectedToken?.index]);

  useEffect(() => {
    if (!open) return;
    setStatus(IDLE_STATUS);
  }, [open, selectedToken?.index]);

  useEffect(() => {
    if (!open || !selectedToken) {
      setQueue(EMPTY_QUEUE);
      setQueueError(null);
      setQueueLoading(false);
      if (!selectedToken) {
        setBassOn(false);
        setSelectedEffect(null);
        setBassLevel(EMPTY_QUEUE.bassLevel);
        setVolume(EMPTY_QUEUE.volume);
        setLoopMode(EMPTY_QUEUE.loopMode);
        setPositionMs(EMPTY_QUEUE.positionMs);
        setLengthMs(EMPTY_QUEUE.lengthMs);
        pendingLoopRef.current = null;
        pendingFiltersRef.current = null;
      }
      return undefined;
    }

    let active = true;
    const tokenIndex = selectedToken.index;
    setQueue(EMPTY_QUEUE);
    setPositionMs(0);
    setLengthMs(null);
    setQueueError(null);
    setQueueLoading(true);

    const tick = async () => {
      try {
        const data = await apiFetch(
          `/voice/audio/queue?token_index=${encodeURIComponent(tokenIndex)}`,
        );
        if (!active) return;
        const parsed = normalizeQueue(data);
        setQueue(parsed);
        setQueueError(null);
        const serverBassOn = parsed.filters.includes(BASS_FILTER_KEY);
        const serverEffect =
          parsed.filters.find((name) => name !== BASS_FILTER_KEY) || null;
        const pendingFilters = pendingFiltersRef.current;
        if (pendingFilters) {
          // The command is only queued; keep the optimistic selection until
          // a poll reflects it, then resume following the server.
          if (
            pendingFilters.bassOn === serverBassOn &&
            pendingFilters.selectedEffect === serverEffect
          ) {
            pendingFiltersRef.current = null;
            setBassOn(serverBassOn);
            setSelectedEffect(serverEffect);
          }
        } else {
          setBassOn(serverBassOn);
          setSelectedEffect(serverEffect);
        }
        if (bassTimerRef.current === null) setBassLevel(parsed.bassLevel);
        if (volumeTimerRef.current === null) setVolume(parsed.volume);
        if (pendingLoopRef.current === null) {
          setLoopMode(parsed.loopMode);
        } else if (pendingLoopRef.current === parsed.loopMode) {
          pendingLoopRef.current = null;
          setLoopMode(parsed.loopMode);
        }
        setPositionMs(parsed.positionMs);
        setLengthMs(parsed.lengthMs);
      } catch (err) {
        if (!active) return;
        setQueueError(
          errorMessage(err, "Could not load the playback queue."),
        );
      } finally {
        if (active) setQueueLoading(false);
      }
    };

    tick();
    const interval = window.setInterval(tick, QUEUE_POLL_MS);
    return () => {
      active = false;
      window.clearInterval(interval);
      // A token switch must not let a pending slider edit commit against the
      // newly selected token.
      if (volumeTimerRef.current !== null) {
        window.clearTimeout(volumeTimerRef.current);
        volumeTimerRef.current = null;
      }
      if (bassTimerRef.current !== null) {
        window.clearTimeout(bassTimerRef.current);
        bassTimerRef.current = null;
      }
      pendingLoopRef.current = null;
      pendingFiltersRef.current = null;
    };
  }, [open, selectedToken?.index]);

  useEffect(() => {
    return () => {
      if (volumeTimerRef.current !== null) {
        window.clearTimeout(volumeTimerRef.current);
        volumeTimerRef.current = null;
      }
      if (bassTimerRef.current !== null) {
        window.clearTimeout(bassTimerRef.current);
        bassTimerRef.current = null;
      }
      pendingLoopRef.current = null;
      pendingFiltersRef.current = null;
    };
  }, [selectedToken?.index]);

  const selectToken = (event) => {
    setSelectedIndex(event.target.value);
    setStatus(IDLE_STATUS);
  };

  const playbackTargetError = () => {
    if (!selectedToken) return "Select a voice token first.";
    if (!session.csrf) return "Pair the dashboard first.";
    const channel = String(channelId || "").trim();
    if (!channel) return "Choose a channel first.";
    if (!SNOWFLAKE_RE.test(channel)) return "Channel ID must be 17-20 digits.";
    return null;
  };

  const play = async (event) => {
    event.preventDefault();
    const guard = playbackTargetError();
    if (guard) {
      setStatus({ kind: "error", message: guard });
      return;
    }

    const channel = String(channelId || "").trim();
    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      setStatus({
        kind: "error",
        message: "Enter a YouTube URL or song name.",
      });
      return;
    }

    if (busyRef.current !== null) return;
    busyRef.current = "play";
    setBusy("play");
    setStatus({
      kind: "working",
      message: queueActive ? "Adding to queue…" : "Starting playback…",
    });
    try {
      await apiFetch("/voice/play", {
        method: "POST",
        csrf: session.csrf,
        body: {
          token_index: Number(selectedToken.index),
          guild_id: "",
          channel_id: channel,
          query: trimmedQuery,
        },
      });
      const message = queueActive
        ? "Added to queue — it will play after the current track."
        : "Playback queued — the bot will start shortly.";
      setStatus({ kind: "success", message });
      toast?.success?.(message, "Voice media");
    } catch (err) {
      const message = errorMessage(err, "Could not queue playback.");
      setStatus({ kind: "error", message });
      toast?.error?.(message, "Voice media");
    } finally {
      busyRef.current = null;
      setBusy(null);
    }
  };

  const search = async (event) => {
    event.preventDefault();
    if (!selectedToken) {
      setStatus({
        kind: "error",
        message: "Select a voice token first.",
      });
      return;
    }
    if (!session.csrf) {
      setStatus({ kind: "error", message: "Pair the dashboard first." });
      return;
    }

    const trimmedQuery = query.trim();
    if (!trimmedQuery) {
      setStatus({
        kind: "error",
        message: "Enter a YouTube URL or song name.",
      });
      return;
    }

    setSearching(true);
    setSearchError(null);
    setResults([]);
    setStatus({ kind: "working", message: "Searching YouTube…" });
    try {
      const data = await api.searchVoice(trimmedQuery, session.csrf);
      const found = Array.isArray(data?.results)
        ? data.results.slice(0, 6)
        : [];
      setResults(found);
      if (found.length) {
        setStatus({
          kind: "success",
          message: `Found ${found.length} result${
            found.length === 1 ? "" : "s"
          }.`,
        });
      } else {
        setStatus({ kind: "idle", message: "No results found." });
      }
    } catch (err) {
      const message =
        err?.data?.message || errorMessage(err, "Could not search YouTube.");
      setSearchError(message);
      setStatus({ kind: "error", message });
    } finally {
      setSearching(false);
    }
  };

  const dismissResults = () => {
    setResults([]);
    setSearchError(null);
  };

  const queueResult = async (result) => {
    const guard = playbackTargetError();
    if (guard) {
      setStatus({ kind: "error", message: guard });
      return;
    }

    const channel = String(channelId || "").trim();
    if (busyRef.current !== null) return;
    busyRef.current = `queue:${result.url}`;
    setBusy(`queue:${result.url}`);
    setStatus({
      kind: "working",
      message: queueActive ? "Adding to queue…" : "Starting playback…",
    });
    try {
      await apiFetch("/voice/play", {
        method: "POST",
        csrf: session.csrf,
        body: {
          token_index: Number(selectedToken.index),
          guild_id: "",
          channel_id: channel,
          query: result.url,
        },
      });
      const message = queueActive
        ? "Added to queue — it will play after the current track."
        : "Playback queued — the bot will start shortly.";
      setStatus({ kind: "success", message });
      toast?.success?.(message, "Voice media");
    } catch (err) {
      const message = errorMessage(err, "Could not queue playback.");
      setStatus({ kind: "error", message });
      toast?.error?.(message, "Voice media");
    } finally {
      busyRef.current = null;
      setBusy(null);
    }
  };

  const control = async (action) => {
    if (!selectedToken) {
      setStatus({
        kind: "error",
        message: "Select a voice token first.",
      });
      return;
    }
    if (!session.csrf) {
      setStatus({ kind: "error", message: "Pair the dashboard first." });
      return;
    }

    if (busyRef.current !== null) return;
    busyRef.current = action;
    setBusy(action);
    setStatus({
      kind: "working",
      message:
        action === "stop" ? "Stopping playback…" : "Skipping track…",
    });
    try {
      await apiFetch(`/voice/audio/${action}`, {
        method: "POST",
        csrf: session.csrf,
        body: { token_index: Number(selectedToken.index) },
      });
      const message =
        action === "stop"
          ? "Playback stopped."
          : "Skipped to the next track.";
      setStatus({ kind: "success", message });
      toast?.success?.(message, "Voice media");
    } catch (err) {
      const message = errorMessage(
        err,
        action === "stop"
          ? "Could not stop playback."
          : "Could not skip the track.",
      );
      setStatus({ kind: "error", message });
      toast?.error?.(message, "Voice media");
    } finally {
      busyRef.current = null;
      setBusy(null);
    }
  };

  const forcefix = async () => {
    if (!selectedToken) {
      setStatus({
        kind: "error",
        message: "Select a voice token first.",
      });
      return;
    }
    if (!session.csrf) {
      setStatus({ kind: "error", message: "Pair the dashboard first." });
      return;
    }

    if (busyRef.current !== null) return;
    busyRef.current = "forcefix";
    setBusy("forcefix");
    setStatus({
      kind: "working",
      message: "Reconnecting and restoring playback…",
    });
    try {
      await api.forcefixVoice(Number(selectedToken.index), session.csrf);
      const message = "Reconnected and restored playback.";
      setStatus({ kind: "success", message });
      toast?.success?.(message, "Voice media");
    } catch (err) {
      const message = errorMessage(err, "Could not reconnect playback.");
      setStatus({ kind: "error", message });
      toast?.error?.(message, "Voice media");
    } finally {
      busyRef.current = null;
      setBusy(null);
    }
  };

  const audioGuard = () => {
    if (!selectedToken) return "Select a voice token first.";
    if (!session.csrf) return "Pair the dashboard first.";
    return null;
  };

  const applyFilters = async (
    nextFilters,
    nextBassLevel,
    successMessage,
    previousFilters = null,
  ) => {
    const guard = audioGuard();
    if (guard) {
      if (previousFilters) {
        pendingFiltersRef.current = null;
        setBassOn(previousFilters.bassOn);
        setSelectedEffect(previousFilters.selectedEffect);
      }
      setStatus({ kind: "error", message: guard });
      return;
    }

    const level = nextFilters.includes("bass") ? nextBassLevel : null;
    setStatus({ kind: "working", message: "Updating audio filters…" });
    try {
      await api.setVoiceFilters(
        Number(selectedToken.index),
        nextFilters,
        level,
        session.csrf,
      );
      setStatus({ kind: "success", message: successMessage });
    } catch (err) {
      if (previousFilters) {
        pendingFiltersRef.current = null;
        setBassOn(previousFilters.bassOn);
        setSelectedEffect(previousFilters.selectedEffect);
      }
      setStatus({
        kind: "error",
        message: errorMessage(err, "Could not update audio filters."),
      });
    }
  };

  const cancelBassTimer = () => {
    if (bassTimerRef.current !== null) {
      window.clearTimeout(bassTimerRef.current);
      bassTimerRef.current = null;
    }
  };

  const applyFilterSelection = (nextBassOn, nextEffect, successMessage) => {
    const next = [];
    if (nextBassOn) next.push(BASS_FILTER_KEY);
    if (nextEffect) next.push(nextEffect);
    const previous = { bassOn, selectedEffect };
    pendingFiltersRef.current = {
      bassOn: nextBassOn,
      selectedEffect: nextEffect,
    };
    setBassOn(nextBassOn);
    setSelectedEffect(nextEffect);
    applyFilters(next, bassLevel, successMessage, previous);
  };

  const toggleBass = (enabled) => {
    cancelBassTimer();
    applyFilterSelection(
      enabled,
      selectedEffect,
      enabled ? "Bass Boost enabled." : "Bass Boost disabled.",
    );
  };

  const selectEffect = (key) => {
    const next = selectedEffect === key ? null : key;
    const label =
      EFFECT_OPTIONS.find((option) => option.key === key)?.label || key;
    applyFilterSelection(
      bassOn,
      next,
      next ? `${label} enabled.` : "Effect cleared.",
    );
  };

  const commitBassLevel = async (next) => {
    const guard = audioGuard();
    if (guard) {
      setStatus({ kind: "error", message: guard });
      return;
    }

    setStatus({ kind: "working", message: "Updating audio filters…" });
    try {
      await api.setVoiceFilters(
        Number(selectedToken.index),
        activeFiltersRef.current,
        next,
        session.csrf,
      );
      setStatus({ kind: "success", message: `Bass level set to ${next}.` });
    } catch (err) {
      setStatus({
        kind: "error",
        message: errorMessage(err, "Could not update audio filters."),
      });
    }
  };

  const changeBassLevel = (event) => {
    const next = Number(event.target.value);
    setBassLevel(next);
    if (bassTimerRef.current !== null) {
      window.clearTimeout(bassTimerRef.current);
    }
    bassTimerRef.current = window.setTimeout(() => {
      bassTimerRef.current = null;
      commitBassLevel(next);
    }, SLIDER_DEBOUNCE_MS);
  };

  const resetAudioDefaults = async () => {
    const guard = audioGuard();
    if (guard) {
      setStatus({ kind: "error", message: guard });
      return;
    }

    cancelBassTimer();
    setBassOn(false);
    setSelectedEffect(null);
    setBassLevel(BASS_LEVEL_SERVER_DEFAULT);
    setVolume(VOLUME_DEFAULT);
    setStatus({ kind: "working", message: "Resetting audio to default…" });
    try {
      await api.setVoiceFilters(
        Number(selectedToken.index),
        [],
        null,
        session.csrf,
      );
      await api.setVoiceVolume(
        Number(selectedToken.index),
        VOLUME_DEFAULT,
        session.csrf,
      );
      setStatus({ kind: "success", message: "Audio reset to default." });
    } catch (err) {
      setStatus({
        kind: "error",
        message: errorMessage(err, "Could not reset the audio settings."),
      });
    }
  };

  const commitVolume = async (next) => {
    const guard = audioGuard();
    if (guard) {
      setStatus({ kind: "error", message: guard });
      return;
    }

    setStatus({ kind: "working", message: `Setting volume to ${next}…` });
    try {
      await api.setVoiceVolume(
        Number(selectedToken.index),
        next,
        session.csrf,
      );
      setStatus({ kind: "success", message: `Volume set to ${next}.` });
    } catch (err) {
      setStatus({
        kind: "error",
        message: errorMessage(err, "Could not change the volume."),
      });
    }
  };

  const changeVolume = (event) => {
    const next = Number(event.target.value);
    setVolume(next);
    if (volumeTimerRef.current !== null) {
      window.clearTimeout(volumeTimerRef.current);
    }
    volumeTimerRef.current = window.setTimeout(() => {
      volumeTimerRef.current = null;
      commitVolume(next);
    }, SLIDER_DEBOUNCE_MS);
  };

  const changeLoop = async (mode) => {
    const guard = audioGuard();
    if (guard) {
      setStatus({ kind: "error", message: guard });
      return;
    }

    const label =
      LOOP_MODES.find((entry) => entry.value === mode)?.label || mode;
    const previous = loopMode;
    if (busyRef.current !== null) return;
    busyRef.current = "loop";
    pendingLoopRef.current = mode;
    setLoopMode(mode);
    setBusy("loop");
    setStatus({ kind: "working", message: `Setting loop to ${label}…` });
    try {
      await api.setVoiceLoop(Number(selectedToken.index), mode, session.csrf);
      setStatus({ kind: "success", message: `Loop set to ${label}.` });
    } catch (err) {
      pendingLoopRef.current = null;
      setLoopMode(previous);
      setStatus({
        kind: "error",
        message: errorMessage(err, "Could not change the loop mode."),
      });
    } finally {
      busyRef.current = null;
      setBusy(null);
    }
  };

  const replay = async () => {
    const guard = audioGuard();
    if (guard) {
      setStatus({ kind: "error", message: guard });
      return;
    }

    if (busyRef.current !== null) return;
    busyRef.current = "replay";
    setBusy("replay");
    setStatus({ kind: "working", message: "Replaying current track…" });
    try {
      await api.replayVoice(Number(selectedToken.index), session.csrf);
      setStatus({ kind: "success", message: "Replaying current track." });
    } catch (err) {
      setStatus({
        kind: "error",
        message: errorMessage(err, "Could not replay the track."),
      });
    } finally {
      busyRef.current = null;
      setBusy(null);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      label="Voice media studio"
      backdropTestId="voice-media-backdrop"
      maxWidthClass="max-w-4xl"
      panelClassName="overflow-hidden"
      overlayStyle={{
        background: `radial-gradient(ellipse at 50% 0%, ${ACCENT}14 0%, transparent 58%), rgba(0,0,0,0.68)`,
        backdropFilter: "blur(8px)",
        WebkitBackdropFilter: "blur(8px)",
      }}
      panelStyle={{
        background: "var(--surface-glass-strong)",
        borderColor: `${ACCENT}45`,
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
        boxShadow: `inset 0 1px 0 var(--glass-highlight), 0 24px 80px rgba(0,0,0,0.55), 0 0 0 1px ${ACCENT}12`,
      }}
    >
      <div
        className="flex items-center gap-3 px-5 py-4 border-b shrink-0"
        style={{ borderColor: "var(--glass-border)" }}
      >
        <div
          className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
          style={{
            background: `linear-gradient(135deg, ${ACCENT}30, ${ACCENT}10)`,
            border: `1px solid ${ACCENT}45`,
            boxShadow: `0 0 18px ${ACCENT}25`,
          }}
        >
          <Music2 size={18} style={{ color: ACCENT }} />
        </div>
        <div className="min-w-0 flex-1">
          <h2
            className="text-base font-extrabold text-white truncate"
            style={{
              fontFamily: "var(--font-display)",
              letterSpacing: "-0.02em",
            }}
          >
            Voice media studio
          </h2>
          <p className="text-xs truncate" style={{ color: "#94A3B8" }}>
            Playback queue and controls
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close"
          title="Close voice media studio"
          className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] ${FOCUS_RING}`}
          style={{ background: "#ffffff08", color: "#94A3B8" }}
        >
          <X size={16} />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto px-5 py-4 flex flex-col gap-4">
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <section className="flex flex-col gap-3 min-w-0">
            <SectionHeader icon={Search} label="Source" accent={ACCENT} />

            <label className="flex flex-col gap-1 min-w-0">
              <span
                className="text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                Voice token
              </span>
              <div
                className="flex items-center gap-2 rounded-xl border px-3 transition-all duration-200 focus-within:ring-2 focus-within:ring-sky-400/70 focus-within:ring-offset-2 focus-within:ring-offset-[#0D1117]"
                style={{
                  background: "var(--surface-inset)",
                  borderColor: "var(--glass-border)",
                  transitionTimingFunction: "var(--ease-out)",
                }}
              >
                <Users
                  size={14}
                  style={{ color: "#94A3B8", flexShrink: 0 }}
                />
                {availableTokens.length > 0 ? (
                  <select
                    value={selectedToken ? String(selectedToken.index) : ""}
                    onChange={selectToken}
                    aria-label="Voice token"
                    className="flex-1 min-w-0 bg-transparent outline-none text-sm py-2.5"
                    style={{ color: "#E2E8F0" }}
                  >
                    {availableTokens.map((token) => (
                      <option key={token.index} value={String(token.index)}>
                        {tokenLabel(token)}
                      </option>
                    ))}
                  </select>
                ) : (
                  <span
                    className="flex-1 min-w-0 text-sm py-2.5"
                    style={{ color: "#64748B" }}
                  >
                    No voice tokens configured.
                  </span>
                )}
              </div>
            </label>

            <label className="flex flex-col gap-1 min-w-0">
              <span
                className="text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                Channel ID
              </span>
              <div
                className="flex items-center gap-2 rounded-xl border px-3 transition-all duration-200 focus-within:ring-2 focus-within:ring-sky-400/70 focus-within:ring-offset-2 focus-within:ring-offset-[#0D1117]"
                style={{
                  background: "var(--surface-inset)",
                  borderColor: "var(--glass-border)",
                  transitionTimingFunction: "var(--ease-out)",
                }}
              >
                <Hash
                  size={14}
                  style={{ color: "#94A3B8", flexShrink: 0 }}
                />
                <input
                  value={channelId}
                  onChange={(event) => setChannelId(event.target.value)}
                  aria-label="Channel ID"
                  placeholder="Channel ID"
                  inputMode="numeric"
                  autoComplete="off"
                  spellCheck={false}
                  className="flex-1 min-w-0 bg-transparent outline-none text-sm py-2.5 placeholder-[#64748B]"
                  style={{ color: "#E2E8F0", fontFamily: "monospace" }}
                />
              </div>
            </label>

            <form onSubmit={play} className="flex flex-col gap-3">
              <label className="flex flex-col gap-1 min-w-0">
                <span
                  className="text-xs font-semibold"
                  style={{ color: "#94A3B8" }}
                >
                  Search or URL
                </span>
                <div
                  className="flex items-center gap-2 rounded-xl border px-3 transition-all duration-200 focus-within:ring-2 focus-within:ring-sky-400/70 focus-within:ring-offset-2 focus-within:ring-offset-[#0D1117]"
                  style={{
                    background: "var(--surface-inset)",
                    borderColor: "var(--glass-border)",
                    transitionTimingFunction: "var(--ease-out)",
                  }}
                >
                  <Search
                    size={14}
                    style={{ color: "#94A3B8", flexShrink: 0 }}
                  />
                  <input
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    placeholder="YouTube URL or song name (auto-queues)"
                    aria-label="Media query"
                    autoComplete="off"
                    spellCheck={false}
                    className="flex-1 min-w-0 bg-transparent outline-none text-sm py-2.5 placeholder-[#64748B]"
                    style={{ color: "#E2E8F0" }}
                  />
                </div>
              </label>

              <div className="flex flex-wrap items-center gap-2">
                <StatusLine status={status} accent={ACCENT} />
                <button
                  type="button"
                  onClick={search}
                  disabled={searching || busy !== null}
                  className={`flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl text-xs font-bold shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING}`}
                  style={{
                    background: "#ffffff08",
                    color: "#E2E8F0",
                    border: "1px solid var(--glass-border)",
                  }}
                >
                  {searching ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : (
                    <Search size={14} />
                  )}
                  Search
                </button>
                <button
                  type="submit"
                  disabled={busy !== null}
                  className={`flex items-center justify-center gap-1.5 px-4 py-2.5 rounded-xl text-xs font-bold text-white shrink-0 transition-all duration-200 hover:brightness-110 active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-50 ${FOCUS_RING}`}
                  style={{
                    background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT}BB)`,
                    boxShadow: `0 4px 16px ${ACCENT}50`,
                  }}
                >
                  {busy === "play" ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : queueActive ? (
                    <ListPlus size={14} />
                  ) : (
                    <Play size={14} />
                  )}
                  {queueActive ? "Add to Queue" : "Play"}
                </button>
              </div>
            </form>

            {(results.length > 0 || searchError) && (
              <div
                className="flex flex-col gap-2"
                data-testid="voice-search-results"
              >
                <div className="flex items-center gap-2">
                  <span
                    className="flex items-center gap-1.5 text-xs font-semibold"
                    style={{ color: "#94A3B8" }}
                  >
                    <Search size={12} style={{ color: ACCENT }} />
                    Search results
                  </span>
                  <div className="flex-1" />
                  {results.length > 0 && (
                    <span
                      className="text-xs font-mono whitespace-nowrap"
                      style={{ color: "#64748B" }}
                    >
                      {results.length} found
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={dismissResults}
                    aria-label="Close search results"
                    title="Close search results"
                    className={`w-6 h-6 rounded-md flex items-center justify-center shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] ${FOCUS_RING}`}
                    style={{ background: "#ffffff08", color: "#94A3B8" }}
                  >
                    <X size={12} />
                  </button>
                </div>

                {searchError && (
                  <div
                    role="alert"
                    className="flex items-center gap-1.5 text-xs"
                    style={{ color: "#FCA5A5" }}
                  >
                    <AlertTriangle
                      size={12}
                      className="shrink-0"
                      style={{ color: "#F23F43" }}
                    />
                    <span className="truncate">{searchError}</span>
                  </div>
                )}

                {results.length > 0 && (
                  <ol
                    className="flex flex-col max-h-40 overflow-y-auto rounded-xl"
                    style={{ background: "var(--surface-inset)" }}
                  >
                    {results.slice(0, 6).map((result, index) => (
                      <li
                        key={`${result.url}-${index}`}
                        className="flex items-center gap-2 px-2.5 py-1.5 border-t first:border-t-0"
                        style={{ borderColor: "var(--glass-border)" }}
                      >
                        <span
                          className="text-xs font-mono w-4 text-right shrink-0"
                          style={{ color: "#64748B" }}
                        >
                          {index + 1}
                        </span>
                        <div className="min-w-0 flex-1">
                          <div
                            className="text-xs font-semibold truncate"
                            style={{ color: "#E2E8F0" }}
                            title={result.title}
                          >
                            {result.title}
                          </div>
                          <div
                            className="text-[11px] truncate"
                            style={{ color: "#94A3B8" }}
                          >
                            {result.uploader || "Unknown uploader"} ·{" "}
                            {formatDuration(result.duration)}
                          </div>
                        </div>
                        <button
                          type="button"
                          onClick={() => queueResult(result)}
                          disabled={busy !== null || searching}
                          className={`flex items-center justify-center gap-1 px-2.5 py-1.5 rounded-lg text-[11px] font-bold shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 ${FOCUS_RING}`}
                          style={{
                            background: `${ACCENT}12`,
                            color: ACCENT,
                            border: `1px solid ${ACCENT}35`,
                          }}
                        >
                          {busy === `queue:${result.url}` ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <ListPlus size={12} />
                          )}
                          + Queue
                        </button>
                      </li>
                    ))}
                  </ol>
                )}
              </div>
            )}
          </section>

          <section className="flex flex-col gap-3 min-w-0">
            <SectionHeader icon={ListMusic} label="Playback" accent={ACCENT}>
              <span
                className="text-xs font-mono truncate min-w-0"
                style={{ color: "#64748B" }}
              >
                {selectedToken ? tokenName(selectedToken) : "No token selected"}
              </span>
            </SectionHeader>

            <div
              className="flex flex-col gap-2 p-2.5 rounded-xl"
              style={{
                background: queue.nowPlaying
                  ? `${ACCENT}10`
                  : "var(--surface-inset)",
                boxShadow: queue.nowPlaying
                  ? `inset 0 0 0 1px ${ACCENT}35`
                  : "none",
              }}
            >
              <div className="flex items-center gap-2.5">
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center shrink-0"
                  style={{
                    background: queue.nowPlaying
                      ? `${ACCENT}20`
                      : "#ffffff06",
                  }}
                >
                  <Music2
                    size={14}
                    style={{
                      color: queue.nowPlaying ? ACCENT : "#64748B",
                    }}
                  />
                </div>
                <div className="min-w-0 flex-1">
                  <div
                    className="text-[11px] font-semibold"
                    style={{ color: "#94A3B8" }}
                  >
                    Now playing
                  </div>
                  <div
                    data-testid="voice-now-playing"
                    className="text-sm font-bold truncate"
                    style={{
                      color: queue.nowPlaying ? "#FFFFFF" : "#94A3B8",
                      fontFamily: "var(--font-display)",
                    }}
                    title={queue.nowPlaying || undefined}
                  >
                    {queue.nowPlaying || "Nothing playing"}
                  </div>
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  <span
                    className="text-[10px] font-semibold uppercase tracking-wide"
                    style={{ color: "#64748B" }}
                  >
                    Loop
                  </span>
                  <Toggle
                    label="Loop"
                    size="sm"
                    enabled={loopMode !== "off"}
                    onChange={(value) => changeLoop(value ? "queue" : "off")}
                    disabled={busy !== null}
                  />
                </div>
              </div>

              {hasLength && (
                <div className="flex flex-col gap-1">
                  <div
                    role="progressbar"
                    aria-label="Playback progress"
                    aria-valuemin={0}
                    aria-valuemax={lengthMs}
                    aria-valuenow={clampedPositionMs}
                    className="h-1 w-full rounded-full overflow-hidden"
                    style={{ background: "var(--glass-border)" }}
                  >
                    <div
                      className="h-full rounded-full transition-all duration-200"
                      style={{
                        width: `${progressPct}%`,
                        background: ACCENT,
                        boxShadow: `0 0 8px ${ACCENT}80`,
                      }}
                    />
                  </div>
                  <div
                    className="flex items-center justify-between text-[10px] font-mono"
                    style={{ color: "#64748B" }}
                  >
                    <span>{formatClock(clampedPositionMs / 1000)}</span>
                    <span>{formatClock(lengthMs / 1000)}</span>
                  </div>
                </div>
              )}
            </div>

            {queueLoading &&
            !queue.nowPlaying &&
            queue.items.length === 0 ? (
              <div
                role="status"
                className="flex items-center gap-1.5 text-xs"
                style={{ color: "#94A3B8" }}
              >
                <Loader2 size={12} className="animate-spin shrink-0" />
                Loading queue…
              </div>
            ) : queue.items.length > 0 ? (
              <ol className="flex flex-col max-h-64 overflow-y-auto">
                {queue.items.map((title, index) => (
                  <li
                    key={`${title}-${index}`}
                    className="flex items-center gap-2 px-2.5 py-1.5 border-t"
                    style={{ borderColor: "var(--glass-border)" }}
                  >
                    <span
                      className="text-xs font-mono w-4 text-right shrink-0"
                      style={{ color: "#64748B" }}
                    >
                      {index + 1}
                    </span>
                    <ListMusic
                      size={12}
                      className="shrink-0"
                      style={{ color: "#94A3B8" }}
                    />
                    <span
                      className="text-xs truncate"
                      style={{ color: "#E2E8F0" }}
                      title={title}
                    >
                      {title}
                    </span>
                  </li>
                ))}
              </ol>
            ) : !queueError ? (
              <div className="text-xs" style={{ color: "#94A3B8" }}>
                Nothing queued.
              </div>
            ) : null}

            {queueError && (
              <div
                role="alert"
                className="flex items-center gap-1.5 text-xs"
                style={{ color: "#FCA5A5" }}
              >
                <AlertTriangle
                  size={12}
                  className="shrink-0"
                  style={{ color: "#F23F43" }}
                />
                <span className="truncate">{queueError}</span>
              </div>
            )}

            <div
              className="flex flex-wrap items-center justify-between gap-2 pt-2 border-t"
              style={{ borderColor: "var(--glass-border)" }}
            >
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={replay}
                  disabled={busy !== null}
                  title="Replay the current track from the start"
                  className={`flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 ${FOCUS_RING}`}
                  style={{
                    background: "#ffffff08",
                    color: "#E2E8F0",
                    border: "1px solid var(--glass-border)",
                  }}
                >
                  {busy === "replay" ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <RotateCcw size={12} />
                  )}
                  Replay
                </button>
                <button
                  type="button"
                  onClick={forcefix}
                  disabled={busy !== null}
                  title="Reconnect the voice client and restore playback"
                  className={`flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 ${FOCUS_RING}`}
                  style={{
                    background: "#ffffff08",
                    color: "#E2E8F0",
                    border: "1px solid var(--glass-border)",
                  }}
                >
                  {busy === "forcefix" ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <RefreshCw size={12} />
                  )}
                  Reconnect &amp; restore
                </button>
              </div>
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => control("stop")}
                  disabled={busy !== null}
                  className={`flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 ${FOCUS_RING}`}
                  style={{
                    background: "#F23F4308",
                    color: "#F23F43",
                    border: "1px solid #F23F4335",
                  }}
                >
                  {busy === "stop" ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <Square size={12} />
                  )}
                  Stop
                </button>
                <button
                  type="button"
                  onClick={() => control("skip")}
                  disabled={busy !== null}
                  className={`flex items-center justify-center gap-1.5 px-3 py-2 rounded-lg text-xs font-bold transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 ${FOCUS_RING}`}
                  style={{
                    background: `${ACCENT}12`,
                    color: ACCENT,
                    border: `1px solid ${ACCENT}35`,
                  }}
                >
                  {busy === "skip" ? (
                    <Loader2 size={12} className="animate-spin" />
                  ) : (
                    <SkipForward size={12} />
                  )}
                  Skip
                </button>
              </div>
            </div>
          </section>
        </div>

        <section
          className="flex flex-col gap-2.5 pt-4 border-t"
          style={{ borderColor: "var(--glass-border)" }}
          data-testid="voice-audio-filters"
        >
          <SectionHeader icon={SlidersHorizontal} label="Audio" accent={ACCENT}>
            <button
              type="button"
              onClick={resetAudioDefaults}
              className={`flex items-center justify-center gap-1.5 px-2.5 py-1.5 rounded-lg text-[11px] font-bold shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] ${FOCUS_RING}`}
              style={{
                background: "#ffffff06",
                color: "#94A3B8",
                border: "1px solid var(--glass-border)",
              }}
            >
              <RotateCcw size={12} />
              Default
            </button>
          </SectionHeader>

          <div className="flex flex-col sm:flex-row sm:items-center gap-2.5">
            <div className="flex items-center gap-2 shrink-0 sm:w-[230px]">
              <Toggle
                enabled={bassOn}
                onChange={toggleBass}
                size="sm"
                label="Bass Boost"
              />
              <span
                className="text-[11px] font-semibold shrink-0"
                style={{ color: bassOn ? ACCENT : "#94A3B8" }}
              >
                Bass Boost
              </span>
              {bassOn && (
                <div className="flex items-center gap-1.5 min-w-0 flex-1">
                  <input
                    type="range"
                    min={BASS_LEVEL_MIN}
                    max={BASS_LEVEL_MAX}
                    step={1}
                    value={bassLevel}
                    onChange={changeBassLevel}
                    aria-label="Bass level"
                    className="w-full min-w-[56px] cursor-pointer"
                    style={{ accentColor: ACCENT }}
                  />
                  <span
                    className="font-mono text-[10px] tabular-nums"
                    style={{ color: ACCENT }}
                  >
                    {bassLevel}
                  </span>
                </div>
              )}
            </div>

            <div
              className="flex items-center gap-1.5 overflow-x-auto min-w-0 flex-1 pb-1"
              role="group"
              aria-label="Audio effect"
            >
              {EFFECT_OPTIONS.map((option) => {
                const active = selectedEffect === option.key;
                return (
                  <button
                    key={option.key}
                    type="button"
                    onClick={() => selectEffect(option.key)}
                    aria-pressed={active}
                    className={`shrink-0 px-2.5 py-1.5 rounded-lg text-[11px] font-bold transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] ${FOCUS_RING}`}
                    style={{
                      background: active ? ACCENT : "var(--surface-inset)",
                      color: active ? "#0B0E14" : "#94A3B8",
                      border: `1px solid ${
                        active ? ACCENT : "var(--glass-border)"
                      }`,
                    }}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>

          <label className="flex flex-col gap-1">
            <span
              className="flex items-center justify-between text-xs font-semibold"
              style={{ color: "#94A3B8" }}
            >
              <span className="flex items-center gap-1.5">
                <Volume2 size={12} style={{ color: ACCENT }} />
                Volume
              </span>
              <span className="font-mono" style={{ color: ACCENT }}>
                {volume}
              </span>
            </span>
            <input
              type="range"
              min={VOLUME_MIN}
              max={VOLUME_MAX}
              step={1}
              value={volume}
              onChange={changeVolume}
              aria-label="Volume"
              className="w-full cursor-pointer"
              style={{ accentColor: ACCENT }}
            />
          </label>
        </section>
      </div>
    </Modal>
  );
}
