"use client";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  Cast,
  Check,
  Eye,
  EyeOff,
  Hash,
  Headphones,
  KeyRound,
  Loader2,
  LogIn,
  LogOut,
  Mic,
  MicOff,
  Music2,
  Play,
  Plug,
  Plus,
  Radio,
  RefreshCw,
  Search,
  Server,
  Trash2,
  Unplug,
  Users,
  Video,
  VolumeX,
  Wifi,
  X,
} from "lucide-react";
import {
  FeatureHero,
  Panel,
  EmptyState,
  IconInput,
  IconBtn,
} from "../kit";
import { useSessionContext } from "../../../lib/session";
import { api } from "../../../lib/api";
import { useLiveState } from "../../../lib/ws";
import { useAccent } from "../../../lib/theme";
import { TG_EMOJI } from "../../../lib/tgEmoji";
import Modal from "../Modal";
import VoiceMediaModal from "./VoiceMediaModal";

const STATUS = {
  online: { label: "Online", color: "#23A55A" },
  idle: { label: "Idle", color: "#94A3B8" },
  error: { label: "Error", color: "#F23F43" },
};

function tokenName(token) {
  return token.display_name || token.username || `Token #${token.index}`;
}

function tokenStatus(token) {
  if (!token.alive) return STATUS.error;
  if (token.channels?.length) return STATUS.online;
  return STATUS.idle;
}

function shortId(value) {
  const id = String(value || "");
  return id.length > 10 ? `${id.slice(0, 6)}…${id.slice(-4)}` : id;
}

function formatTime(timestamp) {
  if (!timestamp) return "—";
  return new Date(timestamp * 1000).toLocaleTimeString();
}

function SoundEmoji({ sound }) {
  if (sound.emoji_id && sound.emoji_name) {
    return (
      <img
        src={`https://cdn.discordapp.com/emojis/${sound.emoji_id}.png?size=48`}
        alt={sound.emoji_name}
        className="w-8 h-8 object-contain"
      />
    );
  }
  return (
    <span className="text-3xl leading-none">{sound.emoji_name || "🎵"}</span>
  );
}

function SoundboardModal({ onClose, tokens, selectedToken, toast, csrf }) {
  const ACCENT = useAccent();
  const initialToken =
    selectedToken ||
    tokens.find((token) => token.channels?.length) ||
    tokens[0] ||
    null;
  const [tab, setTab] = useState(initialToken?.guild_id ? "server" : "defaults");
  const [tokenIndex, setTokenIndex] = useState(initialToken?.index ?? 0);
  const [guildId, setGuildId] = useState(initialToken?.guild_id || "");
  const [sounds, setSounds] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [search, setSearch] = useState("");
  const [playingId, setPlayingId] = useState(null);
  const [closing, setClosing] = useState(false);
  const closeRef = useRef(null);
  const closeTimerRef = useRef(null);
  const playingTimerRef = useRef(null);
  const onCloseRef = useRef(onClose);

  useEffect(() => {
    onCloseRef.current = onClose;
  }, [onClose]);

  const requestClose = useCallback(() => {
    if (closeTimerRef.current) return;
    setClosing(true);
    closeTimerRef.current = window.setTimeout(() => {
      closeTimerRef.current = null;
      onCloseRef.current();
    }, 180);
  }, []);

  useEffect(() => {
    return () => {
      if (closeTimerRef.current) {
        window.clearTimeout(closeTimerRef.current);
        closeTimerRef.current = null;
      }
      if (playingTimerRef.current) {
        window.clearTimeout(playingTimerRef.current);
        playingTimerRef.current = null;
      }
    };
  }, []);

  useEffect(() => {
    const onKeyDown = (event) => {
      if (event.key === "Escape") requestClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [requestClose]);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      if (tab === "server" && !guildId) {
        setSounds([]);
        setError(null);
        setLoading(false);
        return;
      }

      setLoading(true);
      setError(null);
      try {
        const data =
          tab === "defaults"
            ? await api.getVoiceDefaultSounds(tokenIndex)
            : await api.getVoiceSoundboard(guildId, tokenIndex);
        if (!cancelled) {
          setSounds(Array.isArray(data?.sounds) ? data.sounds : []);
        }
      } catch (err) {
        if (!cancelled) {
          setSounds([]);
          setError(
            err?.data?.error || err?.message || "Could not load sounds.",
          );
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    load();
    return () => {
      cancelled = true;
    };
  }, [tab, tokenIndex, guildId]);

  const targetToken =
    tokens.find((token) => token.index === tokenIndex) || initialToken;
  const targetChannel = targetToken?.channels?.[0];
  const filteredSounds = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return sounds;
    return sounds.filter((sound) =>
      String(sound.name || "")
        .toLowerCase()
        .includes(query),
    );
  }, [sounds, search]);

  const playSound = async (sound) => {
    if (!targetChannel) {
      toast.error("Join a voice channel first.", "No channel");
      return;
    }
    if (!csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }

    try {
      await api.playVoiceSound(
        {
          token_index: tokenIndex,
          channel_id: targetChannel,
          sound_id: String(sound.sound_id),
          ...(tab === "server" && guildId
            ? { source_guild_id: guildId }
            : {}),
        },
        csrf,
      );
      setPlayingId(sound.sound_id);
      toast.success(`Playing ${sound.name}`, "Soundboard");
      if (playingTimerRef.current) {
        window.clearTimeout(playingTimerRef.current);
      }
      playingTimerRef.current = window.setTimeout(() => {
        playingTimerRef.current = null;
        setPlayingId(null);
      }, 1500);
    } catch (err) {
      toast.error(
        err?.data?.error || err?.message || "Could not play sound.",
        "Soundboard",
      );
    }
  };

  return (
    <div
      className="modal-overlay fixed inset-0 z-[9999] flex items-center justify-center p-4"
      data-closing={closing ? "true" : "false"}
      style={{
        background: "rgba(0,0,0,0.68)",
        backdropFilter: "blur(4px)",
        WebkitBackdropFilter: "blur(4px)",
      }}
      onClick={requestClose}
      role="presentation"
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="soundboard-title"
        className="modal-panel w-full max-w-3xl max-h-[85vh] rounded-2xl border flex flex-col overflow-hidden"
        data-closing={closing ? "true" : "false"}
        style={{
          background: "var(--surface-glass-strong)",
          borderColor: `${ACCENT}45`,
        }}
        onClick={(event) => event.stopPropagation()}
      >
        <div
          className="flex items-center gap-3 px-5 py-4 border-b"
          style={{ borderColor: "var(--glass-border)" }}
        >
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center shrink-0"
            style={{ background: `${ACCENT}18` }}
          >
            <Music2 size={18} style={{ color: ACCENT }} />
          </div>
          <div className="min-w-0 flex-1">
            <h2
              id="soundboard-title"
              className="text-base font-extrabold text-white"
            >
              Soundboard
            </h2>
          </div>
          <button
            ref={closeRef}
            type="button"
            onClick={requestClose}
            aria-label="Close soundboard"
            className="w-8 h-8 rounded-lg flex items-center justify-center transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
            style={{ background: "#ffffff08", color: "#94A3B8" }}
          >
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-3 flex flex-col gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setTab("server")}
              className="px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
              style={{
                background: tab === "server" ? `${ACCENT}20` : "transparent",
                color: tab === "server" ? ACCENT : "#94A3B8",
                border: `1px solid ${
                  tab === "server" ? `${ACCENT}55` : "var(--glass-border)"
                }`,
              }}
            >
              Server Sounds
            </button>
            <button
              type="button"
              onClick={() => setTab("defaults")}
              className="px-3 py-1.5 rounded-lg text-xs font-bold transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
              style={{
                background: tab === "defaults" ? `${ACCENT}20` : "transparent",
                color: tab === "defaults" ? ACCENT : "#94A3B8",
                border: `1px solid ${
                  tab === "defaults" ? `${ACCENT}55` : "var(--glass-border)"
                }`,
              }}
            >
              Defaults
            </button>
            <div className="flex-1" />
            <select
              value={tokenIndex}
              onChange={(event) => setTokenIndex(Number(event.target.value))}
              className="px-2.5 py-1.5 rounded-lg text-sm font-semibold outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
              style={{
                background: "var(--surface-inset)",
                color: "#E2E8F0",
                border: "1px solid var(--glass-border)",
              }}
              aria-label="Soundboard token"
            >
              {tokens.map((token) => (
                <option key={token.index} value={token.index}>
                  {tokenName(token)}
                </option>
              ))}
            </select>
          </div>

          {tab === "server" && (
            <IconInput
              icon={Server}
              value={guildId}
              onChange={setGuildId}
              placeholder="Server ID"
              mono
              accent={ACCENT}
            />
          )}

          <div
            className="flex items-center gap-2 rounded-xl border px-3"
            style={{
              background: "var(--surface-inset)",
              borderColor: "var(--glass-border)",
            }}
          >
            <Search size={14} style={{ color: "#94A3B8" }} />
            <input
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search sounds…"
              className="flex-1 min-w-0 bg-transparent outline-none text-sm py-2.5"
              style={{ color: "#E2E8F0" }}
            />
          </div>
        </div>

        <div className="px-5 pb-4 flex-1 overflow-y-auto min-h-[180px]">
          {loading ? (
            <div
              className="h-40 flex items-center justify-center gap-2 text-sm"
              style={{ color: "#94A3B8" }}
            >
              <Loader2 size={16} className="animate-spin" />
              Loading sounds…
            </div>
          ) : error ? (
            <div className="h-40 flex items-center justify-center text-sm text-red-400">
              {error}
            </div>
          ) : filteredSounds.length === 0 ? (
            <div
              className="h-40 flex flex-col items-center justify-center gap-2 text-sm"
              style={{ color: "#94A3B8" }}
            >
              <Music2 size={24} style={{ color: "#64748B" }} />
              No sounds found.
            </div>
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
              {filteredSounds.map((sound) => {
                const playing = playingId === sound.sound_id;
                return (
                  <button
                    key={`${sound.sound_id}-${sound.name}`}
                    type="button"
                    onClick={() => playSound(sound)}
                    aria-label={`Play ${sound.name}`}
                    className="group relative flex flex-col items-center gap-2 rounded-xl border p-3 transition-all duration-200 ease-[var(--ease-out)] hover:-translate-y-px active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
                    style={{
                      background: playing
                        ? `${ACCENT}18`
                        : "var(--surface-inset)",
                      borderColor: playing ? ACCENT : "var(--glass-border)",
                      boxShadow: playing ? `0 0 15px ${ACCENT}35` : "none",
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-0 rounded-xl border opacity-0 transition-opacity duration-200 group-hover:opacity-100"
                      style={{ borderColor: `${ACCENT}55` }}
                    />
                    <SoundEmoji sound={sound} />
                    <span className="text-sm font-semibold text-white text-center truncate w-full">
                      {sound.name}
                    </span>
                    <span
                      className="text-xs font-mono"
                      style={{ color: "#94A3B8" }}
                    >
                      {sound.sound_id}
                    </span>
                    <Play
                      size={12}
                      className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity"
                      style={{ color: ACCENT }}
                    />
                  </button>
                );
              })}
            </div>
          )}
        </div>

        <div
          className="px-5 py-3 border-t flex flex-wrap items-center gap-2 text-xs"
          style={{ borderColor: "var(--glass-border)", color: "#94A3B8" }}
        >
          <span>
            Target:{" "}
            <strong style={{ color: "#E2E8F0" }}>
              {targetToken ? tokenName(targetToken) : "No token"}
            </strong>
          </span>
          <span style={{ color: "#64748B" }}>→</span>
          <span style={{ color: targetChannel ? ACCENT : "#F5B642" }}>
            {targetChannel ? `ch ${shortId(targetChannel)}` : "No channel"}
          </span>
        </div>
      </div>
    </div>
  );
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function BulkAction({ icon: Icon, label, color, onClick, disabled }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="flex items-center justify-center gap-1.5 px-2 py-2 rounded-lg text-xs font-bold transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:opacity-40 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
      style={{
        background: `${color}12`,
        color,
        border: `1px solid ${color}30`,
      }}
    >
      <Icon size={12} />
      {label}
    </button>
  );
}

export default function VoiceFeature({ toast }) {
  const ACCENT = useAccent();
  const session = useSessionContext();
  const { connected, liveState } = useLiveState();
  const [tokens, setTokens] = useState([]);
  const [removed, setRemoved] = useState(0);
  const [stateUpdatedAt, setStateUpdatedAt] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [selectedIndices, setSelectedIndices] = useState(() => new Set());
  const [channel1, setChannel1] = useState("");
  const [channel2, setChannel2] = useState("");
  const [soundboardOpen, setSoundboardOpen] = useState(false);
  const [mediaOpen, setMediaOpen] = useState(false);
  const [addOpen, setAddOpen] = useState(false);
  const [newToken, setNewToken] = useState("");
  const [showToken, setShowToken] = useState(false);
  const [adding, setAdding] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(null);
  const [confirmLeave, setConfirmLeave] = useState(null);
  const [deletingIndex, setDeletingIndex] = useState(null);
  const [busy, setBusy] = useState(null);
  const [joinProgress, setJoinProgress] = useState(null);
  const mountedRef = useRef(true);
  const refreshTimersRef = useRef(new Set());
  const lastLiveUpdatedAtRef = useRef(null);

  useEffect(() => {
    mountedRef.current = true;
    const timers = refreshTimersRef.current;
    return () => {
      mountedRef.current = false;
      for (const timer of timers) {
        window.clearTimeout(timer);
      }
      timers.clear();
    };
  }, []);

  const fetchTokens = useCallback(async () => {
    try {
      const data = await api.getVoiceTokens();
      if (!mountedRef.current) return;
      const nextTokens = Array.isArray(data?.tokens) ? data.tokens : [];
      setTokens(nextTokens);
      setRemoved(Number(data?.removed) || 0);
      setStateUpdatedAt(data?.state_updated_at ?? null);
      setSelectedIndices((previous) => {
        const valid = new Set(nextTokens.map((token) => token.index));
        const next = new Set();
        for (const index of previous) {
          if (valid.has(index)) next.add(index);
        }
        return next;
      });
      setError(null);
    } catch (err) {
      if (!mountedRef.current) return;
      setError(
        err?.data?.error || err?.message || "Could not load voice tokens.",
      );
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  const scheduleRefresh = useCallback(
    (delay = 2000) => {
      if (!mountedRef.current) return null;
      const timer = window.setTimeout(() => {
        refreshTimersRef.current.delete(timer);
        fetchTokens();
      }, delay);
      refreshTimersRef.current.add(timer);
      return timer;
    },
    [fetchTokens],
  );

  useEffect(() => {
    if (!session.authenticated) {
      setTokens([]);
      setLoading(false);
      return undefined;
    }

    let cancelled = false;
    const load = async () => {
      if (!cancelled) await fetchTokens();
    };
    load();
    if (connected) {
      return () => {
        cancelled = true;
      };
    }
    const interval = window.setInterval(load, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(interval);
    };
  }, [session.authenticated, fetchTokens, connected]);

  useEffect(() => {
    if (!connected || !liveState?.voice) return;

    const voice = liveState.voice;
    if (voice.updated_at != null) {
      setStateUpdatedAt(voice.updated_at);
      // `updated_at` is the change token: an identical value means nothing
      // relevant changed, so skip the whole token merge.
      if (lastLiveUpdatedAtRef.current === voice.updated_at) return;
      lastLiveUpdatedAtRef.current = voice.updated_at;
    }

    const liveTokens = Array.isArray(voice.tokens) ? voice.tokens : [];
    if (liveTokens.length) {
      const declaredCount = Number(liveState?.tokens);
      // A frame is authoritative only when it carries the full token set.
      // The WS payload includes the configured pool size as `tokens`; a
      // shorter live list means some tokens are still missing from the state
      // file, so pruning would drop valid rows.
      const authoritative =
        Number.isFinite(declaredCount) && declaredCount > 0
          ? liveTokens.length >= declaredCount
          : true;
      setTokens((previous) => {
        const liveByIndex = new Map(
          liveTokens.map((token) => [Number(token.index), token]),
        );
        const base = authoritative
          ? previous.filter((token) => liveByIndex.has(Number(token.index)))
          : previous;
        const merged = base.map((token) => {
          const live = liveByIndex.get(Number(token.index));
          if (!live) return token;
          liveByIndex.delete(Number(token.index));
          return {
            ...token,
            ...live,
            alive: token.alive ?? true,
            username: live.username ?? token.username ?? null,
            user_id: live.user_id ?? token.user_id ?? null,
            display_name: token.display_name ?? live.username ?? null,
            avatar_url: token.avatar_url ?? null,
            error: token.error ?? null,
          };
        });
        for (const live of liveByIndex.values()) {
          merged.push({
            alive: true,
            display_name: live.username ?? null,
            avatar_url: null,
            error: null,
            ...live,
          });
        }
        return merged;
      });
      setLoading(false);
    }
  }, [connected, liveState]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    try {
      const saved1 = window.localStorage.getItem("sb_voice_channel_1");
      const saved2 = window.localStorage.getItem("sb_voice_channel_2");
      if (saved1 !== null) setChannel1(saved1);
      if (saved2 !== null) setChannel2(saved2);
    } catch {
      /* localStorage unavailable */
    }
  }, []);

  const persistChannel = (key, value) => {
    if (typeof window === "undefined") return;
    try {
      window.localStorage.setItem(key, value);
    } catch {
      /* localStorage unavailable */
    }
  };

  const changeChannel1 = (value) => {
    setChannel1(value);
    persistChannel("sb_voice_channel_1", value);
  };
  const changeChannel2 = (value) => {
    setChannel2(value);
    persistChannel("sb_voice_channel_2", value);
  };
  const getChannelIds = () =>
    [channel1.trim(), channel2.trim()].filter(Boolean);

  const selectedTokens = useMemo(
    () => tokens.filter((token) => selectedIndices.has(token.index)),
    [tokens, selectedIndices],
  );
  const selectedOnline = selectedTokens.filter(
    (token) => (token.channels || []).length,
  );
  const online = tokens.filter((token) => token.channels?.length);
  const gatewayReady = tokens.filter((token) => token.gateway_ready);
  const streaming = tokens.filter((token) => token.streaming);
  const allSelected =
    tokens.length > 0 && selectedTokens.length === tokens.length;
  const soundboardToken =
    selectedOnline[0] || selectedTokens[0] || online[0] || tokens[0] || null;

  const toggleSelection = (index) => {
    setSelectedIndices((previous) => {
      const next = new Set(previous);
      if (next.has(index)) next.delete(index);
      else next.add(index);
      return next;
    });
  };

  const selectAll = () => {
    setSelectedIndices(new Set(tokens.map((token) => token.index)));
  };

  const clearSelection = () => {
    setSelectedIndices(new Set());
  };

  const guildForChannel = (token, channelId) => {
    const cache = token?.guild_channels || {};
    for (const [guildId, channels] of Object.entries(cache)) {
      if (
        Array.isArray(channels) &&
        channels.some((channel) => String(channel.id) === String(channelId))
      ) {
        return String(guildId);
      }
    }
    return null;
  };

  const queueJoin = async (tokenIndex, channels) => {
    if (!channels.length) {
      toast.error("Enter at least one channel ID first.", "Missing channel");
      return;
    }
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }
    try {
      await api.joinVoice(
        { token_index: tokenIndex, channels },
        session.csrf,
      );
      toast.info("Join command queued. The bot will process it shortly.", "Voice");
      scheduleRefresh(2000);
    } catch (err) {
      toast.error(
        err?.data?.error || err?.message || "Could not queue join.",
        "Voice",
      );
    }
  };

  const joinSelected = async () => {
    const selected = selectedTokens.filter((token) => token.alive);
    const channels = getChannelIds();
    if (!selected.length) {
      toast.error("Select at least one token.", "No token selected");
      return;
    }
    if (!channels.length) {
      toast.error("Enter at least one channel ID first.", "Missing channel");
      return;
    }
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }

    setJoinProgress({ done: 0, total: selected.length });
    let queued = 0;

    for (let i = 0; i < selected.length; i += 1) {
      const token = selected[i];
      try {
        const byGuild = new Map();
        for (const channelId of channels) {
          const guildId = guildForChannel(token, channelId);
          if (guildId) byGuild.set(guildId, channelId);
        }

        const moves = [];
        const joins = [];
        if (byGuild.size === 0) {
          joins.push(...channels);
        } else {
          for (const [guildId, channelId] of byGuild) {
            const inGuild =
              String(token.guild_id || "") === String(guildId) &&
              (token.channels || []).length > 0;
            if (inGuild) moves.push({ guild_id: guildId, channel_id: channelId });
            else joins.push(channelId);
          }
        }

        for (const move of moves) {
          await api.moveVoice(
            { token_index: token.index, ...move },
            session.csrf,
          );
        }
        if (joins.length) {
          await api.joinVoice(
            { token_index: token.index, channels: joins },
            session.csrf,
          );
        }
        queued += 1;
      } catch (err) {
        toast.error(
          err?.data?.error ||
            err?.message ||
            `Could not queue ${tokenName(token)}.`,
          "Voice",
        );
      }

      setJoinProgress({ done: i + 1, total: selected.length });
      if (i < selected.length - 1) {
        await sleep(1200 + Math.random() * 600);
      }
    }

    toast.info(`Queued ${queued}/${selected.length} token(s).`, "Voice");
    scheduleRefresh(2000);
    setJoinProgress(null);
  };

  const performLeave = async (selected) => {
    if (selected.length === 0) {
      toast.info("Skipped — audio tokens untouched.", "Voice");
      return;
    }

    setBusy("leave");
    let queued = 0;
    let failure = null;
    for (let i = 0; i < selected.length; i += 1) {
      const token = selected[i];
      try {
        const results = await Promise.allSettled(
          (token.channels || []).map((channelId) =>
            api.leaveVoice(
              { token_index: token.index, channel_id: channelId },
              session.csrf,
            ),
          ),
        );
        const rejected = results.find(
          (result) => result.status === "rejected",
        );
        if (rejected) {
          failure = failure || { token, reason: rejected.reason };
        } else {
          queued += 1;
        }
      } catch (err) {
        failure = failure || { token, reason: err };
      }
      if (i < selected.length - 1) {
        await sleep(900 + Math.random() * 400);
      }
    }

    if (failure) {
      toast.error(
        failure.reason?.data?.error ||
          failure.reason?.message ||
          `Could not leave ${tokenName(failure.token)}.`,
        "Voice",
      );
    } else {
      toast.info(`Queued leave for ${queued} token(s).`, "Voice");
    }
    scheduleRefresh(2000);
    setBusy(null);
  };

  const leaveSelected = async () => {
    const selected = selectedTokens.filter(
      (token) => (token.channels || []).length,
    );
    if (!selected.length) {
      toast.error("No selected token is in voice.", "Nothing to leave");
      return;
    }
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }
    const audioTokens = selected.filter((token) => token.audio_active);
    if (audioTokens.length) {
      setConfirmLeave({ selected, audioCount: audioTokens.length });
      return;
    }
    await performLeave(selected);
  };

  const toggleTokenState = async (token, field) => {
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }
    const guildId = token.guild_id;
    if (!guildId) {
      toast.error("This token has no active guild.", "Voice");
      return;
    }
    const key = field === "mute" ? "self_mute" : "self_deaf";
    const current = Boolean(token[key]);
    const next = !current;

    setBusy(`${token.index}:${field}`);
    setTokens((previous) =>
      previous.map((item) =>
        item.index === token.index ? { ...item, [key]: next } : item,
      ),
    );

    try {
      await api.setVoiceState(
        { token_index: token.index, guild_id: guildId, [field]: next },
        session.csrf,
      );
    } catch (err) {
      setTokens((previous) =>
        previous.map((item) =>
          item.index === token.index ? { ...item, [key]: current } : item,
        ),
      );
      toast.error(
        err?.data?.error || err?.message || "Could not update voice state.",
        "Voice",
      );
    } finally {
      setBusy(null);
    }
  };

  const bulkState = async (field, value) => {
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }
    const guilds = Array.from(
      new Set(
        tokens
          .filter((token) => token.guild_id)
          .map((token) => String(token.guild_id)),
      ),
    );
    if (!guilds.length) {
      toast.error("No token has an active guild.", "Voice");
      return;
    }

    setBusy(`bulk:${field}:${value}`);
    try {
      for (const guildId of guilds) {
        await api.setVoiceState(
          { all: true, guild_id: guildId, [field]: value },
          session.csrf,
        );
      }
      const label =
        field === "mute"
          ? value
            ? "Muted"
            : "Unmuted"
          : value
            ? "Deafened"
            : "Undeafened";
      toast.success(`${label} all tokens.`, "Voice");
      scheduleRefresh(1200);
    } catch (err) {
      toast.error(
        err?.data?.error || err?.message || "Could not update every token.",
        "Voice",
      );
    } finally {
      setBusy(null);
    }
  };

  const connectToken = (token) => {
    queueJoin(token.index, getChannelIds());
  };

  const disconnectToken = async (token) => {
    const channels = token.channels || [];
    if (!channels.length) {
      toast.error("This token is not in a voice channel.", "No channel");
      return;
    }
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }
    try {
      const results = await Promise.allSettled(
        channels.map((channelId) =>
          api.leaveVoice(
            { token_index: token.index, channel_id: channelId },
            session.csrf,
          ),
        ),
      );
      const rejected = results.filter(
        (result) => result.status === "rejected",
      );
      if (rejected.length) {
        const reason = rejected[0].reason;
        toast.error(
          reason?.data?.error ||
            reason?.message ||
            `Could not leave ${channels.length} channel(s).`,
          "Voice",
        );
      } else {
        toast.info(`Queued leave for ${channels.length} channel(s).`, "Voice");
      }
    } catch (err) {
      toast.error(
        err?.data?.error ||
          err?.message ||
          `Could not leave ${channels.length} channel(s).`,
        "Voice",
      );
    }
    scheduleRefresh(2000);
  };

  const toggleStream = async (token) => {
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }
    if (!(token.channels || []).length) {
      toast.error("Join a voice channel first.", "Voice");
      return;
    }
    const enable = !token.streaming;
    try {
      await api.setVoiceStream(
        { token_index: token.index, enable },
        session.csrf,
      );
      toast.success(
        enable
          ? "Stream started — the LIVE badge may take a few seconds."
          : "Stream stopped.",
      );
      scheduleRefresh(2000);
    } catch (err) {
      toast.error(
        err?.data?.error || err?.message || "Could not toggle stream.",
        "Voice",
      );
    }
  };

  const toggleCamera = async (token) => {
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }
    if (!(token.channels || []).length) {
      toast.error("Join a voice channel first.", "Voice");
      return;
    }
    const enable = !token.video;
    try {
      await api.setVoiceCamera(
        { token_index: token.index, enable },
        session.csrf,
      );
      toast.success(enable ? "Camera on." : "Camera off.");
      scheduleRefresh(2000);
    } catch (err) {
      toast.error(
        err?.data?.error || err?.message || "Could not toggle camera.",
        "Voice",
      );
    }
  };

  const addToken = async (event) => {
    event.preventDefault();
    const token = newToken.trim();
    if (!token || !session.csrf || adding) return;

    setAdding(true);
    try {
      await api.addVoiceToken({ token }, session.csrf);
      toast.success(
        "Voice token added — reloading voice manager.",
        "Token added",
      );
      setNewToken("");
      setShowToken(false);
      await fetchTokens();
    } catch (err) {
      toast.error(
        err?.data?.error || err?.message || "Could not add voice token.",
        "Voice",
      );
    } finally {
      setAdding(false);
    }
  };

  const removeToken = async (token) => {
    if (!session.csrf) {
      toast.error("Pair the dashboard first.", "Not paired");
      return;
    }

    setDeletingIndex(token.index);
    try {
      await api.deleteVoiceToken({ token_index: token.index }, session.csrf);
      toast.success(
        `Removed ${tokenName(token)} — reloading voice manager.`,
        "Token removed",
      );
      setConfirmDelete(null);
      await fetchTokens();
    } catch (err) {
      toast.error(
        err?.data?.error || err?.message || "Could not remove voice token.",
        "Voice",
      );
    } finally {
      setDeletingIndex(null);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div
          className="flex items-center gap-2.5 px-3.5 py-2 rounded-xl border"
          style={{
            background: "linear-gradient(90deg, #F23F4314, #F23F4305)",
            borderColor: "#F23F4340",
            color: "#FCA5A5",
            boxShadow: "0 0 18px #F23F4310",
          }}
        >
          <AlertTriangle
            size={14}
            className="shrink-0"
            style={{ color: "#F23F43" }}
          />
          <span className="flex-1 text-sm">{error}</span>
        </div>
      )}

      {removed > 0 && (
        <div
          className="flex items-center gap-2.5 px-3.5 py-2 rounded-xl border"
          style={{
            background: "linear-gradient(90deg, #F5B64214, #F5B64205)",
            borderColor: "#F5B64240",
            color: "#FCD34D",
            boxShadow: "0 0 18px #F5B64210",
          }}
        >
          <AlertTriangle
            size={14}
            className="shrink-0"
            style={{ color: "#F5B642" }}
          />
          <span className="flex-1 text-sm">
            Removed {removed} expired token{removed === 1 ? "" : "s"} (401)
            from config.
          </span>
        </div>
      )}

      <FeatureHero
        icon={Headphones}
        title="Voice Manager"
        emojiId={TG_EMOJI.headphones}
        accent={ACCENT}
        stats={[
          {
            icon: Users,
            label: "Tokens",
            value: tokens.length,
            color: ACCENT,
          },
          {
            icon: Wifi,
            label: "In Voice",
            value: online.length,
            color: "#23A55A",
          },
          {
            icon: Cast,
            label: "Streaming",
            value: streaming.length,
            color: "#F23F43",
          },
          {
            icon: Radio,
            label: "Gateway",
            value: gatewayReady.length,
            color: "#7C5CFF",
          },
          {
            icon: AlertTriangle,
            label: "Removed",
            value: removed,
            color: "#F5B642",
          },
        ]}
      />

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-stretch">
        <Panel
          icon={KeyRound}
          title="Token Pool"
          accent={ACCENT}
          className="h-full flex-1"
          action={
            <div className="flex flex-wrap items-center justify-end gap-1.5">
              <button
                type="button"
                onClick={allSelected ? clearSelection : selectAll}
                className="text-xs font-bold px-2 py-1 rounded-lg transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                style={{
                  background: `${ACCENT}12`,
                  color: ACCENT,
                  border: `1px solid ${ACCENT}30`,
                }}
              >
                {allSelected ? "Clear" : "Select all"}
              </button>
              <button
                type="button"
                onClick={() => setMediaOpen(true)}
                className="flex items-center gap-1 text-xs font-bold px-2 py-1 rounded-lg transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                style={{
                  background: "linear-gradient(135deg, #5865F226, #7C5CFF18)",
                  color: "#A5B4FC",
                  border: "1px solid #7C5CFF40",
                }}
              >
                <Music2 size={12} />
                Advanced
              </button>
              <button
                type="button"
                onClick={() => setAddOpen((value) => !value)}
                aria-expanded={addOpen}
                className="flex items-center gap-1 text-xs font-bold px-2 py-1 rounded-lg transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                style={{
                  background: addOpen ? `${ACCENT}26` : `${ACCENT}14`,
                  color: ACCENT,
                  border: `1px solid ${ACCENT}40`,
                }}
              >
                <Plus size={12} />
                Add Token
              </button>
            </div>
          }
        >
          {addOpen && (
            <form onSubmit={addToken} className="flex items-center gap-2">
              <div
                className="flex items-center gap-2 flex-1 min-w-0 rounded-xl border px-3 transition-shadow focus-within:ring-1 focus-within:ring-[#58B8E8]/25"
                style={{
                  background: "var(--surface-inset)",
                  borderColor: "var(--glass-border)",
                }}
              >
                <KeyRound
                  size={14}
                  style={{ color: "#94A3B8", flexShrink: 0 }}
                />
                <input
                  type={showToken ? "text" : "password"}
                  value={newToken}
                  onChange={(event) => setNewToken(event.target.value)}
                  placeholder="Paste voice token"
                  aria-label="Voice token"
                  autoComplete="off"
                  spellCheck={false}
                  className="flex-1 min-w-0 bg-transparent outline-none text-sm py-2.5"
                  style={{ color: "#E2E8F0" }}
                />
                <button
                  type="button"
                  onClick={() => setShowToken((value) => !value)}
                  aria-label={showToken ? "Hide token" : "Show token"}
                  title={showToken ? "Hide token" : "Show token"}
                  className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                  style={{ color: "#94A3B8" }}
                >
                  {showToken ? <EyeOff size={14} /> : <Eye size={14} />}
                </button>
              </div>
              <button
                type="submit"
                disabled={!session.csrf || !newToken.trim() || adding}
                className="flex items-center justify-center gap-1.5 px-3.5 py-2.5 rounded-xl text-xs font-bold shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
                style={{
                  background: "linear-gradient(135deg, #58B8E8, #3D8FBF)",
                  color: "#06121A",
                  border: "1px solid #7CCBF0",
                  boxShadow: "0 4px 14px #58B8E835",
                  opacity:
                    !session.csrf || !newToken.trim() || adding ? 0.45 : 1,
                  cursor:
                    !session.csrf || !newToken.trim() || adding
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                {adding ? (
                  <Loader2 size={13} className="animate-spin" />
                ) : (
                  <Plus size={13} />
                )}
                Add
              </button>
            </form>
          )}

          {loading && tokens.length === 0 ? (
            <div
              className="h-40 flex items-center justify-center gap-2 text-sm"
              style={{ color: "#94A3B8" }}
            >
              <Loader2 size={16} className="animate-spin" />
              Loading voice tokens…
            </div>
          ) : tokens.length === 0 ? (
            <EmptyState
              emojiId={TG_EMOJI.headphones}
              icon={KeyRound}
              title="No voice tokens configured."
              className="py-4 flex-1"
            />
          ) : (
            <div className="flex flex-col min-h-0 max-h-[520px] overflow-y-auto -mr-1 pr-1">
              {tokens.map((token) => {
                const status = tokenStatus(token);
                const selected = selectedIndices.has(token.index);
                const inVoice = Boolean(token.channels?.length);
                const ringShadow = token.streaming
                  ? "0 0 0 2px #F23F43, 0 0 10px #F23F4380"
                  : inVoice
                    ? "0 0 0 2px #23A55A"
                    : token.gateway_ready
                      ? "0 0 0 2px #7C5CFF"
                      : "0 0 0 1px #3B4252";
                return (
                  <div
                    key={token.index}
                    data-testid="voice-token-row"
                    role="checkbox"
                    aria-checked={selected}
                    tabIndex={0}
                    onClick={() => toggleSelection(token.index)}
                    onKeyDown={(event) => {
                      if (event.target !== event.currentTarget) return;
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        toggleSelection(token.index);
                      }
                    }}
                    className="relative flex items-center gap-2.5 px-2 py-2.5 border-t first:border-t-0 cursor-pointer transition-colors duration-200 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117] hover:bg-white/[0.03]"
                    style={{
                      borderColor: "var(--glass-border)",
                      background: selected ? `${ACCENT}12` : undefined,
                      boxShadow: selected
                        ? `inset 0 0 0 1px ${ACCENT}55`
                        : undefined,
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="w-4 h-4 rounded-md border flex items-center justify-center shrink-0"
                      style={{
                        borderColor: selected ? ACCENT : "var(--glass-border)",
                        background: selected ? ACCENT : "transparent",
                        color: "#0B0E14",
                      }}
                    >
                      {selected && <Check size={11} strokeWidth={3} />}
                    </span>

                    <div
                      className="relative shrink-0 rounded-full"
                      style={{ boxShadow: ringShadow }}
                    >
                      <img
                        src={
                          token.avatar_url ||
                          "https://cdn.discordapp.com/embed/avatars/0.png"
                        }
                        alt=""
                        className="w-9 h-9 rounded-full block"
                      />
                      {token.streaming && (
                        <span
                          className="absolute -bottom-0.5 -right-0.5 w-2.5 h-2.5 rounded-full animate-pulse"
                          style={{
                            background: "#F23F43",
                            border: "2px solid var(--surface-solid)",
                            boxShadow: "0 0 8px #F23F43",
                          }}
                        />
                      )}
                    </div>

                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5 min-w-0">
                        <span className="text-sm font-bold text-white truncate">
                          {tokenName(token)}
                        </span>
                      </div>
                      <div className="flex flex-wrap items-center gap-1.5 mt-1">
                        <span
                          className="inline-flex items-center gap-1 text-xs font-bold"
                          style={{ color: status.color }}
                        >
                          <span
                            className="w-1.5 h-1.5 rounded-full"
                            style={{
                              background: status.color,
                              boxShadow: `0 0 6px ${status.color}90`,
                            }}
                          />
                          {status.label}
                        </span>
                        {inVoice && (
                          <span
                            className="inline-flex items-center gap-1 min-w-0 max-w-full px-1.5 py-0.5 rounded-md text-xs font-mono"
                            style={{
                              background: `${ACCENT}10`,
                              color: ACCENT,
                            }}
                            title={token.channels.join(", ")}
                          >
                            <Hash
                              size={9}
                              className="shrink-0"
                              style={{ color: `${ACCENT}90` }}
                            />
                            <span className="truncate">
                              ch {token.channels.map(shortId).join(", ")}
                            </span>
                          </span>
                        )}
                        {token.audio_active && (
                          <span
                            data-testid="voice-audio-badge"
                            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-md text-xs font-bold"
                            style={{ background: "#7C5CFF18", color: "#A5B4FC" }}
                            title={
                              token.audio_playing
                                ? "Audio is playing on this token"
                                : "Audio queue is kept for this token"
                            }
                          >
                            <Music2 size={9} className="shrink-0" />
                            {token.audio_playing ? "Playing audio" : "Audio queued"}
                          </span>
                        )}
                      </div>
                      {token.error && token.error !== "network_error" && (
                        <div className="text-xs font-mono text-red-400 mt-0.5 truncate">
                          {token.error}
                        </div>
                      )}
                    </div>

                    <div className="flex items-center gap-0.5 shrink-0">
                      <IconBtn
                        icon={token.self_mute ? MicOff : Mic}
                        color={token.self_mute ? "#F23F43" : "#94A3B8"}
                        title={token.self_mute ? "Unmute" : "Mute"}
                        disabled={!inVoice}
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleTokenState(token, "mute");
                        }}
                      />
                      <IconBtn
                        icon={token.self_deaf ? VolumeX : Headphones}
                        color={token.self_deaf ? "#F5B642" : "#94A3B8"}
                        title={token.self_deaf ? "Undeafen" : "Deafen"}
                        disabled={!inVoice}
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleTokenState(token, "deaf");
                        }}
                      />
                      <IconBtn
                        icon={Cast}
                        color={
                          !inVoice
                            ? "#3B4252"
                            : token.streaming
                              ? "#F23F43"
                              : "#94A3B8"
                        }
                        title={
                          token.streaming
                            ? "Stop stream"
                            : "Start stream (Go Live)"
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleStream(token);
                        }}
                      />
                      <IconBtn
                        icon={Video}
                        color={
                          !inVoice
                            ? "#3B4252"
                            : token.video
                              ? "#23A55A"
                              : "#94A3B8"
                        }
                        title={
                          token.video ? "Turn camera off" : "Turn camera on"
                        }
                        onClick={(event) => {
                          event.stopPropagation();
                          toggleCamera(token);
                        }}
                      />
                      <IconBtn
                        icon={inVoice ? Unplug : Plug}
                        color={inVoice ? "#F5B642" : "#23A55A"}
                        title={inVoice ? "Disconnect" : "Connect"}
                        onClick={(event) => {
                          event.stopPropagation();
                          if (inVoice) disconnectToken(token);
                          else connectToken(token);
                        }}
                      />
                      {confirmDelete === token.index ? (
                        <div
                          className="absolute right-2 top-1/2 -translate-y-1/2 z-20 flex items-center gap-1.5 pl-2 pr-1.5 py-1 rounded-lg"
                          style={{
                            background: "#170F14",
                            border: "1px solid #F23F4350",
                            boxShadow: "0 8px 24px #00000090",
                          }}
                          onClick={(event) => event.stopPropagation()}
                        >
                          <span
                            className="text-xs font-bold"
                            style={{ color: "#F23F43" }}
                          >
                            Remove?
                          </span>
                          <button
                            type="button"
                            aria-label={`Confirm remove ${tokenName(token)}`}
                            onClick={() => removeToken(token)}
                            disabled={deletingIndex === token.index}
                            className="flex items-center justify-center min-w-[52px] text-xs font-bold px-2 py-1 rounded-md transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                            style={{
                              background:
                                "linear-gradient(135deg, #F23F43, #C0392B)",
                              color: "#fff",
                              border: "1px solid #F23F4380",
                              opacity:
                                deletingIndex === token.index ? 0.6 : 1,
                            }}
                          >
                            {deletingIndex === token.index ? (
                              <Loader2 size={11} className="animate-spin" />
                            ) : (
                              "Confirm"
                            )}
                          </button>
                          <button
                            type="button"
                            aria-label={`Cancel remove ${tokenName(token)}`}
                            onClick={() => setConfirmDelete(null)}
                            className="text-xs font-bold px-2 py-1 rounded-md transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
                            style={{
                              background: "#ffffff08",
                              color: "#94A3B8",
                              border: "1px solid var(--glass-border)",
                            }}
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <IconBtn
                          icon={Trash2}
                          color="#F23F43"
                          title={`Remove ${tokenName(token)}`}
                          onClick={(event) => {
                            event.stopPropagation();
                            setConfirmDelete(token.index);
                          }}
                        />
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div
            className="mt-auto grid grid-cols-2 gap-2 border-t pt-3"
            style={{ borderColor: "var(--glass-border)" }}
          >
            <BulkAction
              icon={MicOff}
              label="Mute all"
              color="#F23F43"
              disabled={busy !== null}
              onClick={() => bulkState("mute", true)}
            />
            <BulkAction
              icon={Mic}
              label="Unmute all"
              color="#23A55A"
              disabled={busy !== null}
              onClick={() => bulkState("mute", false)}
            />
            <BulkAction
              icon={VolumeX}
              label="Deafen all"
              color="#F5B642"
              disabled={busy !== null}
              onClick={() => bulkState("deaf", true)}
            />
            <BulkAction
              icon={Headphones}
              label="Undeafen all"
              color="#58B8E8"
              disabled={busy !== null}
              onClick={() => bulkState("deaf", false)}
            />
          </div>
        </Panel>

        <Panel
          icon={Server}
          title="Room Controller"
          accent="#23A55A"
          className="h-full flex-1"
          action={
            <button
              type="button"
              onClick={fetchTokens}
              title="Refresh voice state"
              aria-label="Refresh voice state"
              className="w-7 h-7 rounded-lg flex items-center justify-center transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] hover:rotate-180 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
              style={{
                background: "#23A55A16",
                color: "#23A55A",
                border: "1px solid #23A55A30",
              }}
            >
              <RefreshCw size={12} />
            </button>
          }
        >
          <div
            className="flex flex-wrap items-center justify-between gap-2 text-xs"
            style={{ color: "#94A3B8" }}
          >
            <span className="font-semibold">
              {selectedTokens.length} selected · {selectedOnline.length} in
              voice
            </span>
            <span className="font-mono">
              Last sync: {formatTime(stateUpdatedAt)}
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <label className="flex flex-col gap-1.5 min-w-0">
              <span
                className="flex items-center gap-1 text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                <span
                  className="w-1 h-1 rounded-full"
                  style={{ background: "#23A55A" }}
                />
                Channel 1
              </span>
              <IconInput
                icon={Hash}
                value={channel1}
                onChange={changeChannel1}
                placeholder="Channel ID"
                mono
                accent="#23A55A"
                size="lg"
              />
            </label>
            <label className="flex flex-col gap-1.5 min-w-0">
              <span
                className="flex items-center gap-1 text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                <span
                  className="w-1 h-1 rounded-full"
                  style={{ background: "#23A55A" }}
                />
                Channel 2 (optional)
              </span>
              <IconInput
                icon={Hash}
                value={channel2}
                onChange={changeChannel2}
                placeholder="Second channel ID"
                mono
                accent="#23A55A"
                size="lg"
              />
            </label>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
            <button
              type="button"
              onClick={joinSelected}
              disabled={
                joinProgress !== null ||
                !selectedTokens.length ||
                !getChannelIds().length
              }
              className="flex items-center justify-center gap-1.5 py-3 rounded-xl font-bold text-sm text-white transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
              style={{
                background: "linear-gradient(135deg, #23A55A, #1A7F45)",
                border: "1px solid #2ECC71",
                boxShadow: "0 4px 14px #23A55A45",
              }}
            >
              {joinProgress ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <LogIn size={14} />
              )}
              {joinProgress
                ? `Joining ${joinProgress.done}/${joinProgress.total}…`
                : `Join / Move (${selectedTokens.length})`}
            </button>
            <button
              type="button"
              onClick={leaveSelected}
              disabled={busy === "leave" || !selectedOnline.length}
              className="flex items-center justify-center gap-1.5 py-3 rounded-xl font-bold text-sm transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] disabled:cursor-not-allowed disabled:opacity-45 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
              style={{
                background: "#F23F4312",
                color: "#F23F43",
                border: "1px solid #F23F4355",
              }}
            >
              {busy === "leave" ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <LogOut size={14} />
              )}
              Leave Selected ({selectedOnline.length})
            </button>
          </div>

          <button
            type="button"
            onClick={() => setSoundboardOpen(true)}
            disabled={tokens.length === 0}
            className="flex items-center justify-between gap-2 px-3 py-2.5 rounded-xl font-bold text-xs transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
            style={{
              background: "linear-gradient(135deg, #5865F226, #7C5CFF18)",
              color: "#A5B4FC",
              border: "1px solid #7C5CFF40",
              opacity: tokens.length === 0 ? 0.5 : 1,
              cursor: tokens.length === 0 ? "not-allowed" : "pointer",
              boxShadow:
                tokens.length === 0 ? "none" : "0 0 18px #7C5CFF15",
            }}
          >
            <span className="flex items-center gap-2">
              <Music2 size={14} />
              Soundboard
            </span>
            <span
              aria-hidden="true"
              className="text-xs font-semibold tracking-wide px-1.5 py-0.5 rounded"
              style={{
                background: "#7C5CFF20",
                border: "1px solid #7C5CFF35",
                color: "#C4B5FD",
              }}
            >
              OPEN
            </span>
          </button>

          <div
            className="mt-auto flex flex-col gap-2 pt-3 border-t"
            style={{ borderColor: "var(--glass-border)" }}
          >
            <div className="flex items-center justify-between gap-2">
              <span
                className="flex items-center gap-1.5 text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full animate-pulse"
                  style={{
                    background: "#23A55A",
                    boxShadow: "0 0 8px #23A55A",
                  }}
                />
                Active session
              </span>
              <span
                className="text-xs font-mono whitespace-nowrap"
                style={{ color: "#94A3B8" }}
              >
                Last sync: {formatTime(stateUpdatedAt)}
              </span>
            </div>
            {online.length === 0 ? (
              <EmptyState
                emojiId={TG_EMOJI.headphones}
                icon={Radio}
                title="No active voice connections."
                className="py-2"
              />
            ) : (
              <div className="flex flex-col">
                {online.map((token) => (
                  <div
                    key={token.index}
                    className="flex items-center gap-2 min-w-0 px-2 py-2 border-t"
                    style={{
                      borderColor: "var(--glass-border)",
                      background: token.streaming
                        ? "#F23F430A"
                        : undefined,
                    }}
                  >
                    <div
                      className="relative shrink-0 rounded-full"
                      style={{
                        boxShadow: token.streaming
                          ? "0 0 0 2px #F23F43, 0 0 8px #F23F4360"
                          : "0 0 0 1px #23A55A70",
                      }}
                    >
                      <img
                        src={
                          token.avatar_url ||
                          "https://cdn.discordapp.com/embed/avatars/0.png"
                        }
                        alt=""
                        className="w-6 h-6 rounded-full block"
                      />
                    </div>
                    <span
                      className="text-xs font-mono truncate flex-1 min-w-0"
                      style={{ color: ACCENT }}
                      title={token.channels.join(", ")}
                    >
                      ch {token.channels.map(shortId).join(", ")}
                    </span>
                    {token.streaming && (
                      <span className="flex items-center gap-1 shrink-0">
                        <span
                          className="w-1.5 h-1.5 rounded-full animate-pulse"
                          style={{
                            background: "#F23F43",
                            boxShadow: "0 0 6px #F23F43",
                          }}
                        />
                        <span
                          className="text-xs font-extrabold tracking-wide"
                          style={{ color: "#F23F43" }}
                        >
                          LIVE
                        </span>
                      </span>
                    )}
                    {token.video && (
                      <Video
                        size={11}
                        style={{ color: "#23A55A", flexShrink: 0 }}
                      />
                    )}
                    {token.audio_active && (
                      <Music2
                        size={11}
                        aria-label={
                          token.audio_playing ? "Playing audio" : "Audio queued"
                        }
                        style={{ color: "#A5B4FC", flexShrink: 0 }}
                      />
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        </Panel>
      </div>

      {soundboardOpen && (
        <SoundboardModal
          onClose={() => setSoundboardOpen(false)}
          tokens={tokens}
          selectedToken={soundboardToken}
          toast={toast}
          csrf={session.csrf}
        />
      )}

      <Modal
        open={Boolean(confirmLeave)}
        onClose={() => setConfirmLeave(null)}
        role="alertdialog"
        label="Leave audio tokens?"
        maxWidthClass="max-w-md"
        panelClassName="p-6 flex flex-col gap-4"
        backdropTestId="leave-audio-backdrop"
        panelStyle={{
          background: "var(--surface-glass-strong)",
          borderColor: "#F23F4355",
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
        }}
      >
        <div className="flex items-center gap-3">
          <div
            className="p-2.5 rounded-xl shrink-0"
            style={{ background: "#F23F4322" }}
          >
            <AlertTriangle size={22} style={{ color: "#F23F43" }} />
          </div>
          <div className="min-w-0">
            <div className="font-extrabold text-white text-base">
              Leave audio tokens?
            </div>
            <p className="text-sm mt-0.5" style={{ color: "#94A3B8" }}>
              {confirmLeave?.audioCount} selected token(s) are playing audio.
              Leave them too?
            </p>
          </div>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => {
              const selected = confirmLeave?.selected || [];
              setConfirmLeave(null);
              performLeave(selected.filter((token) => !token.audio_active));
            }}
            className="flex-1 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
            style={{ background: "#2D3748", color: "#E2E8F0" }}
          >
            No, skip audio
          </button>
          <button
            type="button"
            onClick={() => {
              const selected = confirmLeave?.selected || [];
              setConfirmLeave(null);
              performLeave(selected);
            }}
            className="flex-1 py-2.5 text-sm font-bold rounded-xl text-white transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
            style={{
              background: "linear-gradient(135deg, #F23F43, #C0392B)",
              boxShadow: "0 4px 16px #F23F4350",
            }}
          >
            Yes, leave all
          </button>
        </div>
      </Modal>

      <VoiceMediaModal
        open={mediaOpen}
        onClose={() => setMediaOpen(false)}
        tokens={tokens}
        toast={toast}
      />
    </div>
  );
}
