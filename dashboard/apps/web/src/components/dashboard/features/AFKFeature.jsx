"use client";
import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Bot,
  CheckCircle2,
  KeyRound,
  Loader2,
  MessageSquare,
  MinusCircle,
  Moon,
  PenLine,
  Sun,
  Timer,
} from "lucide-react";
import Toggle from "../Toggle";
import Avatar from "../Avatar";
import { FeatureHero, Panel, SliderRow } from "../kit";
import { api, ApiError } from "../../../lib/api";
import { useSessionContext } from "../../../lib/session";
import { useAccent } from "../../../lib/theme";
import { TG_EMOJI } from "../../../lib/tgEmoji";

const AUTOSAVE_DELAY = 600;

const PRESETS = [
  {
    emoji: "😴",
    label: "Sleeping",
    text: "Sleeping now, I'll reply tomorrow. Good night!",
  },
  {
    emoji: "📚",
    label: "Studying",
    text: "Studying right now, I'll get back to you later.",
  },
  {
    emoji: "💼",
    label: "Working",
    text: "Busy working, I'll reply when I'm free.",
  },
  {
    emoji: "🎮",
    label: "Gaming",
    text: "In-game right now, I'll reply after this match.",
  },
  {
    emoji: "🍜",
    label: "Eating",
    text: "Grabbing a meal, I'll reply when I'm back!",
  },
  {
    emoji: "🚗",
    label: "Out",
    text: "Out right now, away from my phone.",
  },
];

function Banner({ tone = "info", icon: Icon, spin = false, children, action }) {
  const palette =
    {
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

export default function AFKFeature({ toast }) {
  const ACCENT = useAccent();
  const {
    loading: sessionLoading,
    authenticated,
    csrf,
  } = useSessionContext();

  const [loading, setLoading] = useState(true);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  const [afk, setAfk] = useState(false);
  const [reason, setReason] = useState("");
  const [cooldown, setCooldown] = useState(10);
  const [replyMentions, setReplyMentions] = useState(true);
  const [replyDms, setReplyDms] = useState(true);
  const [saved, setSaved] = useState(false);

  const [autosaveStatus, setAutosaveStatus] = useState("");

  const markDirty = () => {
    setSaved(false);
  };

  const buildPayload = (overrides = {}) => ({
    enabled: afk,
    reason,
    cooldown,
    reply_mentions: replyMentions,
    reply_dms: replyDms,
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
      const res = await api.saveAfk(payload, csrf);
      if (!mountedRef.current) return;
      if (!res || res.saved === false) {
        setSaved(false);
        setAutosaveStatus(res?.reason || "Could not save settings.");
        return;
      }
      setSaved(true);
      setAutosaveStatus("saved");
    } catch (err) {
      if (!mountedRef.current) return;
      setSaved(false);
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
      setSaved(false);
      setLoadError("");
      setAfk(false);
      setReason("");
      setCooldown(10);
      setReplyMentions(true);
      setReplyDms(true);
      setAutosaveStatus("");
      autosaveSkipRef.current = true;
      return;
    }

    let cancelled = false;
    autosaveSkipRef.current = true;
    setLoading(true);
    setLoaded(false);
    setLoadError("");

    api
      .getAfk()
      .then((data) => {
        if (cancelled) return;
        setAfk(Boolean(data?.enabled));
        setReason(typeof data?.reason === "string" ? data.reason : "");
        const rawCooldown = Number(data?.cooldown);
        setCooldown(
          Number.isFinite(rawCooldown)
            ? Math.min(Math.max(Math.round(rawCooldown), 3), 60)
            : 10,
        );
        setReplyMentions(data?.reply_mentions !== false);
        setReplyDms(data?.reply_dms !== false);
        setSaved(true);
        setLoaded(true);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : "";
        setLoadError(msg || "Could not load AFK settings.");
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
    afk,
    reason,
    cooldown,
    replyMentions,
    replyDms,
  ]);

  const changeAfk = (v) => {
    if (v && !reason.trim()) {
      setAutosaveStatus("Enter a reason before enabling AFK.");
      return;
    }
    setAfk(v);
    markDirty();
    scheduleAutosave(buildPayload({ enabled: v }));
  };

  const changeReason = (v) => {
    setReason(v.slice(0, 200));
    markDirty();
  };

  const changeCooldown = (v) => {
    setCooldown(v);
    markDirty();
  };

  const changeReplyMentions = (v) => {
    setReplyMentions(v);
    markDirty();
  };

  const changeReplyDms = (v) => {
    setReplyDms(v);
    markDirty();
  };

  const BigIcon = afk ? Moon : Sun;
  const glow = afk ? ACCENT : "#64748B";
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
  const replySubline = !replyMentions && !replyDms
    ? "Auto reply off"
    : replyMentions && replyDms
      ? "Replying to mentions · DMs"
      : replyMentions
        ? "Replying to mentions only"
        : "Replying to DMs only";
  const filtersPill = !replyMentions && !replyDms
    ? "Replies off"
    : replyMentions && replyDms
      ? "Mentions & DMs"
      : replyMentions
        ? "Mentions only"
        : "DMs only";

  return (
    <div className="flex flex-col gap-3">
      {showLoading && (
        <Banner icon={Loader2} spin>
          Loading AFK settings…
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
        icon={Moon}
        emojiId={TG_EMOJI.moon}
        title="AFK Assistant"
        accent={ACCENT}
        enabled={afk}
        onToggle={changeAfk}
        toggleLabel="AFK master toggle"
        disabled={!editable}
        stats={[
          {
            icon: afk ? Moon : Sun,
            label: "Status",
            value: afk ? "AFK" : "Online",
            color: afk ? ACCENT : "#23A55A",
          },
          {
            icon: PenLine,
            label: "Reason length",
            value: `${reason.length}/200`,
            color: "#58B8E8",
          },
          {
            icon: Timer,
            label: "Cooldown",
            value: `${cooldown}s`,
            color: "#58B8E8",
          },
          {
            icon: saved ? CheckCircle2 : MinusCircle,
            label: "API state",
            value: saved ? "Saved" : "Not saved",
            color: saved ? "#23A55A" : "#94A3B8",
          },
        ]}
      />

      {autosaveStatus && (
        <div
          data-testid="autosave-status"
          role="status"
          aria-live="polite"
          className="flex items-center gap-1.5 text-xs font-semibold px-1 -mt-1"
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

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 items-stretch">
        <div className="flex flex-col gap-3 min-w-0 h-full">
          <Panel icon={Bot} title="Status" accent={ACCENT} className="flex-1">
            <div className="flex flex-col items-center gap-3">
              <div
                className={`relative w-16 h-16 rounded-full flex items-center justify-center${
                  afk ? " orb-pulse" : ""
                }`}
                style={{
                  background: `${glow}18`,
                  boxShadow: `0 0 0 2px ${glow}55, 0 0 32px ${glow}35`,
                }}
              >
                <BigIcon
                  size={32}
                  style={{ color: afk ? ACCENT : "#94A3B8" }}
                />
              </div>
              <div className="text-center">
                <div
                  className="text-lg font-extrabold tracking-tight"
                  style={{ color: afk ? ACCENT : "#E2E8F0" }}
                >
                  {afk ? "AFK ACTIVE" : "AVAILABLE"}
                </div>
                <div className="text-sm mt-0.5" style={{ color: "#94A3B8" }}>
                  {afk ? replySubline : "Not auto replying"}
                </div>
              </div>
            </div>

            <div
              className="border-t pt-3"
              style={{ borderColor: "var(--glass-border)" }}
            >
              <div
                className="text-xs font-semibold mb-2"
                style={{ color: "#94A3B8" }}
              >
                Cooldown
              </div>
              <SliderRow
                value={cooldown}
                onChange={changeCooldown}
                min={3}
                max={60}
                unit="s"
                accent={afk ? ACCENT : "#94A3B8"}
                disabled={!editable}
              />
            </div>

            <div
              className="border-t"
              style={{ borderColor: "var(--glass-border)" }}
            >
              <div className="flex items-center justify-between gap-3 py-2.5">
                <span
                  className="text-sm font-semibold"
                  style={{ color: "#E2E8F0" }}
                >
                  Mentions
                </span>
                <Toggle
                  enabled={replyMentions}
                  onChange={changeReplyMentions}
                  size="sm"
                  label="Mentions"
                  disabled={!editable}
                />
              </div>
              <div
                className="flex items-center justify-between gap-3 py-2.5 border-t"
                style={{ borderColor: "var(--glass-border)" }}
              >
                <span
                  className="text-sm font-semibold"
                  style={{ color: "#E2E8F0" }}
                >
                  DMs
                </span>
                <Toggle
                  enabled={replyDms}
                  onChange={changeReplyDms}
                  size="sm"
                  label="DMs"
                  disabled={!editable}
                />
              </div>
            </div>

            <div className="flex flex-wrap gap-1.5">
              <span
                className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full"
                style={{
                  background: "var(--surface-inset)",
                  color: "#94A3B8",
                }}
              >
                <MessageSquare size={11} style={{ color: "#58B8E8" }} />
                {filtersPill}
              </span>
              <span
                className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full"
                style={{
                  background: "var(--surface-inset)",
                  color: "#94A3B8",
                }}
              >
                <Timer size={11} style={{ color: "#58B8E8" }} />
                {cooldown}s cooldown
              </span>
              <span
                className="inline-flex items-center gap-1.5 text-[11px] font-semibold px-2 py-0.5 rounded-full"
                style={{
                  background: "var(--surface-inset)",
                  color: "#94A3B8",
                }}
              >
                <Bot size={11} style={{ color: "#58B8E8" }} />
                Bot filter
              </span>
            </div>
          </Panel>
        </div>

        <div className="flex flex-col gap-3 min-w-0 h-full">
          <Panel
            icon={PenLine}
            title="Away Message"
            accent={ACCENT}
            className="flex-1"
          >
            <div className="flex flex-col gap-1.5">
              <textarea
                value={reason}
                onChange={(e) => changeReason(e.target.value)}
                rows={2}
                maxLength={200}
                disabled={!editable}
                className="w-full text-sm outline-none resize-none rounded-xl border px-3 py-2 placeholder-[#64748B] transition-colors duration-200 focus-visible:ring-2 focus-visible:ring-sky-400/40 disabled:opacity-50 disabled:cursor-not-allowed"
                style={{
                  background: "var(--surface-inset)",
                  borderColor: "var(--glass-border)",
                  color: "#E2E8F0",
                }}
                onFocus={(e) => (e.target.style.borderColor = ACCENT)}
                onBlur={(e) =>
                  (e.target.style.borderColor = "var(--glass-border)")
                }
                placeholder="Away reason…"
              />
              <div className="flex justify-end">
                <span
                  className="font-mono text-xs font-semibold"
                  style={{ color: reason.length > 180 ? "#F5B642" : "#94A3B8" }}
                >
                  {reason.length}/200
                </span>
              </div>
            </div>

            <div className="flex flex-col gap-2">
              <div
                className="text-xs font-semibold"
                style={{ color: "#94A3B8" }}
              >
                Quick presets
              </div>
              <div className="flex flex-wrap gap-1.5">
                {PRESETS.map((preset) => {
                  const active = reason === preset.text;
                  return (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => changeReason(preset.text)}
                      title={preset.text}
                      disabled={!editable}
                      className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-200 ease-[var(--ease-out)] hover:-translate-y-px active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117] disabled:opacity-50 disabled:cursor-not-allowed"
                      style={{
                        background: active
                          ? `${ACCENT}18`
                          : "var(--surface-inset)",
                        boxShadow: active ? `0 0 0 1px ${ACCENT}55` : "none",
                        color: active ? ACCENT : "#CBD5E1",
                      }}
                    >
                      <span aria-hidden="true">{preset.emoji}</span>
                      <span className="truncate">{preset.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>

            <div
              className="mt-auto flex flex-1 flex-col gap-2 border-t pt-3 min-h-0"
              style={{ borderColor: "var(--glass-border)" }}
            >
              <div className="flex items-center justify-between gap-2">
                <span
                  className="text-xs font-semibold"
                  style={{ color: "#94A3B8" }}
                >
                  Live Preview
                </span>
              </div>
              <div
                className="flex flex-1 flex-col rounded-xl overflow-hidden min-h-0"
                style={{
                  background: "#313338",
                  border: `1px solid ${ACCENT}2E`,
                  boxShadow: `0 0 0 1px ${ACCENT}14, 0 12px 32px rgba(0,0,0,0.28)`,
                }}
              >
                <div
                  className="flex items-center gap-2 px-3 py-2 border-b shrink-0"
                  style={{ borderColor: "#26282C" }}
                >
                  <Avatar name="friend" size={20} />
                  <span className="text-xs font-semibold text-white">
                    friend
                  </span>
                  <span
                    className="text-[10px]"
                    style={{ color: "#94A3B8" }}
                  >
                    Direct Message
                  </span>
                </div>
                <div className="flex flex-1 flex-col gap-3 p-3 min-h-0">
                  <div className="flex gap-2">
                    <Avatar name="friend" size={28} />
                    <div className="min-w-0">
                      <div
                        className="text-sm font-semibold"
                        style={{ color: "#F5B642" }}
                      >
                        friend
                      </div>
                      <div
                        className="text-sm mt-0.5"
                        style={{ color: "#E2E8F0" }}
                      >
                        <span
                          className="px-1 rounded"
                          style={{ color: "#C9CDFB", background: "#5865F230" }}
                        >
                          @shadowbyte_exe
                        </span>{" "}
                        are you free tonight?
                      </div>
                    </div>
                  </div>

                  <div className="flex gap-2">
                    <Avatar name="shadowbyte_exe" size={28} />
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-white flex items-center gap-1.5">
                        shadowbyte_exe
                        <span
                          className="text-xs font-bold px-1 py-0.5 rounded"
                          style={{ background: `${ACCENT}30`, color: ACCENT }}
                        >
                          💤 AFK
                        </span>
                      </div>
                      <div
                        className="text-sm mt-0.5"
                        style={{ color: "#E2E8F0" }}
                      >
                        ⚠️ I am currently AFK: {reason || "…"}
                      </div>
                    </div>
                  </div>

                  <div
                    className="mt-auto flex items-center gap-1.5 text-xs"
                    style={{ color: "#94A3B8" }}
                  >
                    <span className="flex gap-0.5">
                      <span
                        className="w-1 h-1 rounded-full animate-pulse"
                        style={{ background: "#94A3B8" }}
                      />
                      <span
                        className="w-1 h-1 rounded-full animate-pulse"
                        style={{
                          background: "#94A3B8",
                          animationDelay: "120ms",
                        }}
                      />
                      <span
                        className="w-1 h-1 rounded-full animate-pulse"
                        style={{
                          background: "#94A3B8",
                          animationDelay: "240ms",
                        }}
                      />
                    </span>
                    friend is typing…
                  </div>
                </div>
                <div className="px-3 pb-3 shrink-0">
                  <div
                    className="flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs"
                    style={{ background: "#383A40", color: "#6D6F78" }}
                  >
                    <MessageSquare size={12} />
                    Message @friend…
                  </div>
                </div>
              </div>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
