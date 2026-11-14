"use client";
import { useEffect, useRef, useState } from "react";
import {
  Heart,
  User,
  Users,
  Hash,
  Smile,
  Crosshair,
  Globe,
  Target,
  Sparkles,
  Loader2,
  AlertTriangle,
  KeyRound,
  CheckCircle2,
  X,
  Plus,
} from "lucide-react";
import Avatar from "../Avatar";
import {
  FeatureHero,
  Panel,
  EmptyState,
  ChoiceGrid,
  IconInput,
  SliderRow,
} from "../kit";
import { api, ApiError } from "../../../lib/api";
import { useSessionContext } from "../../../lib/session";
import { useAccent } from "../../../lib/theme";
import { TG_EMOJI } from "../../../lib/tgEmoji";

const MAX_EMOJIS = 10;
const AUTOSAVE_DELAY = 600;
const QUICK = [
  "🔥",
  "💀",
  "❤️",
  "👀",
  "💯",
  "⚡",
  "😈",
  "🌙",
  "🎮",
  "🤖",
  "😂",
  "🙌",
  "💎",
  "🎵",
  "🍀",
];
const MODES = [
  { value: "user", label: "Specific user", short: "User", icon: User },
  { value: "everyone", label: "@everyone", short: "Everyone", icon: Users },
];

const CUSTOM_EMOJI_RE = /^<(a?):([^:>]+):(\d+)>$/;

function parseCustomEmoji(value) {
  if (typeof value !== "string") return null;
  const match = value.match(CUSTOM_EMOJI_RE);
  if (!match) return null;

  const [, animated, name, id] = match;
  return {
    name,
    id,
    animated: animated === "a",
    url: `https://cdn.discordapp.com/emojis/${id}.${
      animated === "a" ? "gif" : "png"
    }?size=48&quality=lossless`,
  };
}

function EmojiVisual({ value, size = 22, className = "" }) {
  const custom = parseCustomEmoji(value);
  const [failed, setFailed] = useState(false);
  const [renderedValue, setRenderedValue] = useState(value);

  // Reset the error state during render when the emoji changes. Using an
  // effect here races with an onError fired immediately after mount, which
  // made the CDN fallback test flaky.
  if (renderedValue !== value) {
    setRenderedValue(value);
    setFailed(false);
  }

  if (!custom) {
    return (
      <span
        className={`inline-flex items-center justify-center leading-none ${className}`}
        style={{ fontSize: size * 0.82 }}
        title={value}
      >
        {value}
      </span>
    );
  }

  if (failed) {
    return (
      <span
        className={`inline-flex items-center justify-center rounded-md border px-1.5 font-mono text-xs font-bold ${className}`}
        style={{
          height: size,
          minWidth: size,
          borderColor: "var(--glass-border)",
          background: "var(--surface-inset)",
          color: "#94A3B8",
        }}
        title={value}
      >
        :{custom.name}:
      </span>
    );
  }

  return (
    <img
      src={custom.url}
      alt={`:${custom.name}:`}
      title={`:${custom.name}:`}
      width={size}
      height={size}
      loading="lazy"
      decoding="async"
      draggable={false}
      onError={() => setFailed(true)}
      className={`inline-block object-contain ${className}`}
      style={{ width: size, height: size }}
    />
  );
}

function Banner({ tone = "info", icon: Icon, spin = false, children, action }) {
  const palette = {
    info: { color: "#58B8E8", bg: "#58B8E812", border: "#58B8E840" },
    warn: { color: "#F5B642", bg: "#F5B64212", border: "#F5B64240" },
    error: { color: "#F23F43", bg: "#F23F4312", border: "#F23F4340" },
    success: { color: "#23A55A", bg: "#23A55A12", border: "#23A55A40" },
  }[tone] || {
    color: "#58B8E8",
    bg: "#58B8E812",
    border: "#58B8E840",
  };
  return (
    <div
      className="flex items-center gap-2.5 px-3 py-2.5 rounded-xl border text-sm"
      style={{ background: palette.bg, borderColor: palette.border }}
    >
      {Icon && (
        <Icon
          size={14}
          className={spin ? "animate-spin" : undefined}
          style={{ color: palette.color, flexShrink: 0 }}
        />
      )}
      <span className="flex-1 min-w-0" style={{ color: "#C9D1DB" }}>
        {children}
      </span>
      {action}
    </div>
  );
}

export default function ReactionsFeature() {
  const ACCENT = useAccent();
  const { loading: sessionLoading, authenticated, csrf } = useSessionContext();

  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const [enabled, setEnabled] = useState(false);
  const [mode, setMode] = useState("user");
  const [userId, setUserId] = useState("");
  const [channel, setChannel] = useState("");
  const [emojiInput, setEmojiInput] = useState("");
  const [customEmojiDraft, setCustomEmojiDraft] = useState("");
  const [customEmojiError, setCustomEmojiError] = useState("");
  const [cooldown, setCooldown] = useState(3);

  const [saveError, setSaveError] = useState("");
  const [autosaveStatus, setAutosaveStatus] = useState("");

  const emojis = emojiInput.trim().split(/\s+/).filter(Boolean);

  const markDirty = () => {
    setSaveError("");
  };

  const buildPayload = (overrides = {}) => ({
    enabled,
    target: mode,
    user_id: userId.trim(),
    channel_id: channel.trim(),
    emojis,
    cooldown,
    ...overrides,
  });

  const autosaveTimerRef = useRef(null);
  const autosavePendingRef = useRef(null);
  const autosaveRunningRef = useRef(false);
  const autosaveRunnerRef = useRef(null);
  const autosaveSkipRef = useRef(true);
  const mountedRef = useRef(true);

  const runAutosave = async (payload) => {
    if (!authenticated || !csrf) return;
    if (autosaveRunningRef.current) {
      autosavePendingRef.current = payload;
      return;
    }
    autosaveRunningRef.current = true;
    if (mountedRef.current) setAutosaveStatus("saving");
    try {
      const res = await api.saveReactions(payload, csrf);
      if (!mountedRef.current) return;
      if (!res || res.saved === false) {
        setAutosaveStatus(res?.reason || "Could not save settings.");
        return;
      }
      setAutosaveStatus("saved");
    } catch (err) {
      if (!mountedRef.current) return;
      const msg = err instanceof ApiError ? err.message : "";
      setAutosaveStatus(msg || "Could not save settings.");
    } finally {
      autosaveRunningRef.current = false;
      const next = autosavePendingRef.current;
      autosavePendingRef.current = null;
      if (next && autosaveRunnerRef.current) autosaveRunnerRef.current(next);
    }
  };

  const flushAutosave = () => {
    if (autosaveTimerRef.current) {
      clearTimeout(autosaveTimerRef.current);
      autosaveTimerRef.current = null;
    }
    const payload = autosavePendingRef.current;
    autosavePendingRef.current = null;
    if (payload && autosaveRunnerRef.current) {
      autosaveRunnerRef.current(payload);
    }
  };

  const scheduleAutosave = (payload) => {
    if (!authenticated || !csrf) return;
    if (!loaded) {
      setAutosaveStatus("Waiting for settings…");
      return;
    }
    autosavePendingRef.current = payload;
    setAutosaveStatus("saving");
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current);
    autosaveTimerRef.current = setTimeout(() => {
      autosaveTimerRef.current = null;
      const next = autosavePendingRef.current;
      autosavePendingRef.current = null;
      if (next && autosaveRunnerRef.current) autosaveRunnerRef.current(next);
    }, AUTOSAVE_DELAY);
  };

  useEffect(() => {
    autosaveRunnerRef.current = runAutosave;
  });

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      flushAutosave();
    };
  }, []);

  useEffect(() => {
    if (sessionLoading) return;
    if (!authenticated) {
      setLoading(false);
      setLoaded(false);
      setLoadError("");
      setEnabled(false);
      setMode("user");
      setUserId("");
      setChannel("");
      setEmojiInput("");
      setCustomEmojiDraft("");
      setCustomEmojiError("");
      setSaveError("");
      setAutosaveStatus("");
      autosaveSkipRef.current = true;
      return;
    }

    let cancelled = false;
    autosaveSkipRef.current = true;
    setLoading(true);
    setLoaded(false);
    setLoadError("");
    setCustomEmojiDraft("");
    setCustomEmojiError("");

    api
      .getReactions()
      .then((data) => {
        if (cancelled) return;
        setEnabled(Boolean(data?.enabled));
        setMode(data?.target === "everyone" ? "everyone" : "user");
        setUserId(
          typeof data?.user_id === "string"
            ? data.user_id
            : data?.user_id
              ? String(data.user_id)
              : "",
        );
        setChannel(
          typeof data?.channel_id === "string"
            ? data.channel_id
            : data?.channel_id
              ? String(data.channel_id)
              : "",
        );
        setEmojiInput(
          Array.isArray(data?.emojis)
            ? data.emojis
                .filter((e) => typeof e === "string")
                .slice(0, MAX_EMOJIS)
                .join(" ")
            : "",
        );
        const rawCooldown = Number(data?.cooldown);
        setCooldown(
          Number.isFinite(rawCooldown)
            ? Math.min(30, Math.max(1, Math.round(rawCooldown)))
            : 3,
        );
        setLoaded(true);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : "";
        setLoadError(msg || "Could not load reaction settings.");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [sessionLoading, authenticated, csrf, reloadKey]);

  // Autosave any field edit (debounced). The first run after a load is the
  // server data arriving, not a user edit, so it is skipped.
  useEffect(() => {
    if (!loaded || !authenticated || !csrf) return;
    if (autosaveSkipRef.current) {
      autosaveSkipRef.current = false;
      return;
    }
    scheduleAutosave(buildPayload());
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    loaded,
    authenticated,
    csrf,
    enabled,
    mode,
    userId,
    channel,
    emojiInput,
    cooldown,
  ]);

  const changeMode = (v) => {
    if (v === "everyone" && enabled && !channelValid) {
      setSaveError("Pick a channel before enabling everyone mode.");
      return;
    }
    setMode(v);
    markDirty();
  };

  const toggleEmoji = (e) => {
    markDirty();
    setCustomEmojiError("");
    if (emojis.includes(e)) {
      setEmojiInput(emojis.filter((x) => x !== e).join(" "));
      return;
    }
    if (emojis.length >= MAX_EMOJIS) {
      setSaveError(`Max ${MAX_EMOJIS} emojis.`);
      return;
    }
    setEmojiInput([...emojis, e].join(" "));
  };

  const addCustomEmoji = () => {
    const value = customEmojiDraft.trim();
    if (!value) {
      setCustomEmojiError("Paste a custom emoji first.");
      return;
    }
    if (!parseCustomEmoji(value)) {
      setCustomEmojiError("Use a valid Discord custom emoji.");
      return;
    }
    if (emojis.includes(value)) {
      setCustomEmojiError("That emoji is already selected.");
      return;
    }
    if (emojis.length >= MAX_EMOJIS) {
      setCustomEmojiError(`Max ${MAX_EMOJIS} emojis.`);
      return;
    }

    markDirty();
    setEmojiInput([...emojis, value].join(" "));
    setCustomEmojiDraft("");
    setCustomEmojiError("");
  };

  const scoped = channel.trim().length > 0;
  const ScopeIcon = scoped ? Crosshair : Globe;
  const channelValid = /^\d+$/.test(channel.trim());
  const everyoneNeedsChannel = mode === "everyone" && !channelValid;
  const userIdValid = /^\d+$/.test(userId.trim());
  const needsUser = enabled && mode === "user" && !userIdValid;
  const needsEmoji = enabled && emojis.length === 0;
  const showLoading = sessionLoading || (authenticated && loading);
  const editable = loaded && authenticated && !loadError;
  const autosaveTone =
    autosaveStatus === "saving"
      ? "#F5B642"
      : autosaveStatus === "saved"
        ? "#23A55A"
        : "#F23F43";
  const AutosaveIcon =
    autosaveStatus === "saving"
      ? Loader2
      : autosaveStatus === "saved"
        ? CheckCircle2
        : AlertTriangle;

  return (
    <div className="flex flex-col gap-3">
      {showLoading && (
        <Banner icon={Loader2} spin>
          Loading reaction settings…
        </Banner>
      )}

      {!sessionLoading && !authenticated && (
        <Banner tone="warn" icon={KeyRound}>
          Pair the dashboard to load settings.
        </Banner>
      )}

      {!showLoading && authenticated && loadError && (
        <Banner
          tone="error"
          icon={AlertTriangle}
          action={
            <button
              type="button"
              onClick={() => setReloadKey((k) => k + 1)}
              className="text-xs font-bold px-2 py-1 rounded-lg shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70"
              style={{ background: "#F23F4320", color: "#F23F43" }}
            >
              Retry
            </button>
          }
        >
          {loadError}
        </Banner>
      )}

      <FeatureHero
        icon={Heart}
        title="Auto Reactions"
        emojiId={TG_EMOJI.heart}
        accent={ACCENT}
        enabled={enabled}
        onToggle={(v) => {
          if (v && everyoneNeedsChannel) {
            setSaveError("Pick a channel before enabling everyone mode.");
            return;
          }
          if (v && mode === "user" && !userIdValid) {
            setSaveError("Pick a user ID before enabling.");
            return;
          }
          setEnabled(v);
          markDirty();
          scheduleAutosave(buildPayload({ enabled: v }));
        }}
        toggleLabel="Auto Reactions master toggle"
        disabled={!editable}
        stats={[
          {
            icon: Target,
            label: "Target",
            value: mode === "everyone" ? "Everyone" : "1 user",
            color: ACCENT,
          },
          {
            icon: Smile,
            label: "Emojis",
            value: emojis.length,
            color: "#F5B642",
          },
          {
            icon: Hash,
            label: "Scope",
            value: scoped ? "1 channel" : "All",
            color: "#58B8E8",
          },
          {
            icon: Sparkles,
            label: "Status",
            value: !enabled
              ? "Disabled"
              : everyoneNeedsChannel
                ? "Blocked"
                : needsUser
                  ? "Needs user"
                  : needsEmoji
                    ? "Needs emoji"
                    : "Enabled",
            color: !enabled
              ? "#94A3B8"
              : everyoneNeedsChannel || needsUser || needsEmoji
                ? "#F5B642"
                : "#23A55A",
          },
        ]}
      />

      {saveError && (
        <Banner tone="error" icon={AlertTriangle}>
          {saveError}
        </Banner>
      )}

      {autosaveStatus && (
        <div
          data-testid="autosave-status"
          role="status"
          aria-live="polite"
          className="flex items-center gap-1.5 text-xs font-semibold px-1 -mt-2"
          style={{ color: autosaveTone }}
        >
          <AutosaveIcon
            size={12}
            className={autosaveStatus === "saving" ? "animate-spin" : undefined}
          />
          <span>
            {autosaveStatus === "saving"
              ? "Saving…"
              : autosaveStatus === "saved"
                ? "Saved"
                : autosaveStatus}
          </span>
        </div>
      )}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-stretch">
        <div className="flex flex-col gap-3 min-w-0 h-full">
          <Panel
            icon={Target}
            title="Target"
            accent={ACCENT}
            className="h-full flex-1"
          >
            <ChoiceGrid
              options={MODES}
              value={mode}
              onChange={changeMode}
              accent={ACCENT}
              cols={2}
              disabled={!editable}
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 items-start">
              <IconInput
                icon={User}
                value={userId}
                onChange={(v) => {
                  setUserId(v);
                  markDirty();
                }}
                placeholder="User ID"
                mono
                accent={ACCENT}
                disabled={!editable || mode === "everyone"}
              />
              <div className="flex flex-col gap-1 min-w-0">
                <IconInput
                  icon={Hash}
                  value={channel}
                  onChange={(v) => {
                    setChannel(v);
                    markDirty();
                  }}
                  placeholder={
                    mode === "everyone"
                      ? "Channel ID (required for everyone)"
                      : "Channel ID (blank = all)"
                  }
                  mono
                  accent="#58B8E8"
                  disabled={!editable}
                />
                {everyoneNeedsChannel && (
                  <span
                    role="alert"
                    className="text-xs font-semibold px-1"
                    style={{ color: "#F5B642" }}
                  >
                    Everyone mode needs a channel.
                  </span>
                )}
              </div>
            </div>
            <div
              className="flex items-center gap-2 px-3 py-2 rounded-xl text-xs font-semibold w-fit"
              style={{
                background: everyoneNeedsChannel
                  ? "#F5B64215"
                  : scoped
                    ? "#58B8E815"
                    : "#23A55A15",
                color: everyoneNeedsChannel
                  ? "#F5B642"
                  : scoped
                    ? "#58B8E8"
                    : "#23A55A",
              }}
            >
              <ScopeIcon size={13} />{" "}
              {everyoneNeedsChannel
                ? "All channels — blocked"
                : scoped
                  ? "Scoped to channel"
                  : "All channels"}
            </div>

            <div
              className="flex flex-col gap-1.5 border-t pt-3"
              style={{ borderColor: "var(--glass-border)" }}
            >
              <span
                className="text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                Cooldown
              </span>
              <SliderRow
                value={cooldown}
                onChange={(v) => {
                  setCooldown(v);
                  markDirty();
                }}
                min={1}
                max={30}
                unit="s"
                accent="#58B8E8"
                disabled={!editable}
              />
            </div>

            <div
              className="mt-auto flex flex-1 flex-col gap-2 border-t pt-3 min-h-0"
              style={{ borderColor: "var(--glass-border)" }}
            >
              <span
                className="text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                Live Preview
              </span>
              {loading ? (
                <div
                  className="flex items-center justify-center gap-2 py-3 text-sm"
                  style={{ color: "#94A3B8" }}
                >
                  <Loader2 size={14} className="animate-spin" />
                  Loading preview…
                </div>
              ) : (
                <div
                  className="p-2.5 rounded-xl flex flex-1 flex-col gap-2"
                  style={{ background: "#313338" }}
                >
                  {[
                    "gg bro that was insane 🔥",
                    "anyone up for valorant tonight?",
                  ].map((msg, i) => (
                    <div key={i} className="flex gap-2">
                      <Avatar
                        name={
                          mode === "everyone" ? `user_${i + 1}` : "target_user"
                        }
                        size={28}
                      />
                      <div className="min-w-0">
                        <div
                          className="text-xs font-semibold"
                          style={{ color: "#F23F43" }}
                        >
                          {mode === "everyone"
                            ? `user_${i + 1}`
                            : "target_user"}
                        </div>
                        <div
                          className="text-xs"
                          style={{ color: "#E2E8F0" }}
                        >
                          {msg}
                        </div>
                        <div className="flex flex-wrap gap-1 mt-1">
                          {emojis.map((e) => (
                            <button
                              key={e}
                              onClick={() => toggleEmoji(e)}
                              title="Remove"
                              aria-label={`Remove ${e}`}
                              disabled={!editable}
                              className="flex items-center gap-1 px-1.5 py-0.5 rounded-md border text-xs transition-all duration-200 ease-[var(--ease-out)] hover:-translate-y-px active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:opacity-50 disabled:cursor-not-allowed"
                              style={{
                                background: "#5865F226",
                                borderColor: "#5865F2",
                                color: "#DEE0FC",
                              }}
                              onMouseEnter={(ev) => {
                                ev.currentTarget.style.background = "#F23F4330";
                                ev.currentTarget.style.borderColor = "#F23F43";
                              }}
                              onMouseLeave={(ev) => {
                                ev.currentTarget.style.background = "#5865F226";
                                ev.currentTarget.style.borderColor = "#5865F2";
                              }}
                            >
                              <EmojiVisual value={e} size={14} />
                              <span className="text-[10px] font-bold tabular-nums">
                                1
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Panel>
        </div>

        <div className="flex flex-col gap-3 min-w-0 h-full">
          <Panel
            icon={Smile}
            title="Emojis"
            accent="#F5B642"
            className="h-full flex-1"
          >
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2">
                <span
                  className="text-xs font-semibold"
                  style={{ color: "#94A3B8" }}
                >
                  Selected
                </span>
                <span
                  className="text-xs font-bold px-2 py-0.5 rounded-full tabular-nums"
                  style={{ background: "#F5B64220", color: "#F5B642" }}
                >
                  {emojis.length}/{MAX_EMOJIS}
                </span>
              </div>
              {emojis.length > 0 && (
                <button
                  type="button"
                  onClick={() => {
                    markDirty();
                    setEmojiInput("");
                    setCustomEmojiError("");
                  }}
                  disabled={!editable}
                  className="text-xs font-semibold px-2 py-1 rounded-lg transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:opacity-50 disabled:cursor-not-allowed"
                  style={{ background: "#F23F4315", color: "#F23F43" }}
                >
                  Clear all
                </button>
              )}
            </div>

            <div
              className="flex flex-wrap gap-1.5 p-2 rounded-xl"
              style={{ background: "var(--surface-inset)" }}
            >
              {loading ? (
                <span
                  className="flex items-center gap-2 text-sm"
                  style={{ color: "#94A3B8" }}
                >
                  <Loader2 size={13} className="animate-spin" />
                  Loading emojis…
                </span>
              ) : emojis.length === 0 ? (
                <EmptyState
                  emojiId={TG_EMOJI.heart}
                  title="No emojis selected"
                  compact
                  className="w-full"
                />
              ) : (
                emojis.map((e) => {
                  const custom = parseCustomEmoji(e);
                  return (
                    <span
                      key={e}
                      className="flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-lg"
                      style={{ background: "#F5B64214" }}
                    >
                      <EmojiVisual value={e} size={22} />
                      {custom && (
                        <span
                          className="text-xs font-mono max-w-[120px] truncate"
                          style={{ color: "#94A3B8" }}
                        >
                          :{custom.name}:
                        </span>
                      )}
                      <button
                        type="button"
                        onClick={() => toggleEmoji(e)}
                        title={`Remove ${e}`}
                        disabled={!editable}
                        className="w-4 h-4 rounded-full flex items-center justify-center shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:opacity-50 disabled:cursor-not-allowed"
                        style={{ background: "#F23F4325", color: "#F23F43" }}
                      >
                        <X size={10} />
                      </button>
                    </span>
                  );
                })
              )}
            </div>

            <span
              className="text-xs font-semibold"
              style={{ color: "#94A3B8" }}
            >
              Quick pick
            </span>

            <div className="grid grid-cols-5 sm:grid-cols-8 gap-1.5">
              {QUICK.map((e) => {
                const on = emojis.includes(e);
                const full = !on && emojis.length >= MAX_EMOJIS;
                return (
                  <button
                    key={e}
                    onClick={() => toggleEmoji(e)}
                    disabled={full || !editable}
                    title={full ? `Max ${MAX_EMOJIS} emojis` : e}
                    className={`group relative aspect-square rounded-lg border flex items-center justify-center transition-all duration-200 ease-[var(--ease-out)] hover:-translate-y-px active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 ${
                      on ? "scale-105" : "scale-100"
                    }`}
                    style={{
                      background: on ? "#F5B64220" : "var(--surface-inset)",
                      borderColor: on ? "#F5B642" : "var(--glass-border)",
                      opacity: full || !editable ? 0.4 : 1,
                      cursor:
                        full || !editable ? "not-allowed" : "pointer",
                    }}
                  >
                    <span
                      aria-hidden="true"
                      className="pointer-events-none absolute inset-0 rounded-lg border opacity-0 transition-opacity duration-200 group-hover:opacity-100"
                      style={{ borderColor: "#F5B64288" }}
                    />
                    <EmojiVisual value={e} size={24} />
                  </button>
                );
              })}
            </div>

            <div
              className="mt-auto flex flex-col gap-1.5 border-t pt-3"
              style={{ borderColor: "var(--glass-border)" }}
            >
              <span
                className="text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                Custom emoji
              </span>
              <div className="flex flex-col sm:flex-row gap-2">
                <div className="flex-1 min-w-0">
                  <IconInput
                    icon={Smile}
                    value={customEmojiDraft}
                    onChange={(v) => {
                      setCustomEmojiDraft(v);
                      if (customEmojiError) setCustomEmojiError("");
                    }}
                    placeholder="<:name:id> or <a:name:id>"
                    accent="#F5B642"
                    disabled={!editable}
                  />
                </div>
                <button
                  type="button"
                  onClick={addCustomEmoji}
                  disabled={!editable}
                  className="flex items-center justify-center gap-1.5 px-3 py-2.5 rounded-xl text-sm font-bold w-full sm:w-auto shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
                  style={{
                    background: "#F5B642",
                    color: "#0B0E14",
                    opacity:
                      emojis.length >= MAX_EMOJIS || !editable ? 0.55 : 1,
                    cursor: !editable ? "not-allowed" : "pointer",
                  }}
                >
                  <Plus size={14} /> Add
                </button>
              </div>
              {customEmojiError && (
                <span className="text-sm" style={{ color: "#F23F43" }}>
                  {customEmojiError}
                </span>
              )}
            </div>
          </Panel>
        </div>
      </div>

    </div>
  );
}
