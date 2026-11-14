"use client";
import { useEffect, useRef, useState } from "react";
import {
  MessageSquare,
  Zap,
  Plus,
  Trash2,
  ArrowRight,
  Radio,
  Timer,
  MessagesSquare,
  Hash,
  Layers,
  Send,
  KeyRound,
  Reply,
  X,
  Loader2,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import Toggle from "../Toggle";
import Avatar from "../Avatar";
import {
  FeatureHero,
  Panel,
  EmptyState,
  ChoiceGrid,
  IconInput,
  SliderRow,
  IconBtn,
} from "../kit";
import { api, ApiError } from "../../../lib/api";
import { useSessionContext } from "../../../lib/session";
import { useAccent } from "../../../lib/theme";
import { TG_EMOJI } from "../../../lib/tgEmoji";

const MAX_ITEMS = 5;
const AUTOSAVE_DELAY = 600;
let _id = 100;

const MODES = [
  {
    value: "time",
    label: "Time",
    short: "Every N sec",
    icon: Timer,
    color: "#F5B642",
  },
  {
    value: "message",
    label: "Messages",
    short: "Every N msgs",
    icon: MessagesSquare,
    color: "#58B8E8",
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

function RuleRow({ r, onUpd, onDel, first, disabled = false }) {
  const ACCENT = useAccent();
  return (
    <div
      className={`grid grid-cols-[minmax(0,1fr)_auto] sm:grid-cols-[minmax(0,38%)_auto_minmax(0,1fr)_auto] items-center gap-1.5 py-2 ${
        first ? "" : "border-t"
      }`}
      style={{ borderColor: "var(--glass-border)" }}
    >
      <div className="col-span-2 min-w-0 sm:col-span-1">
        <IconInput
          icon={KeyRound}
          value={r.keyword}
          onChange={(v) => onUpd("keyword", v)}
          placeholder="keyword"
          mono
          accent={ACCENT}
          disabled={disabled}
          maxLength={100}
        />
      </div>
      <ArrowRight
        size={13}
        className="hidden sm:block"
        style={{ color: "#64748B", flexShrink: 0 }}
      />
      <div className="min-w-0">
        <IconInput
          icon={Reply}
          value={r.reply}
          onChange={(v) => onUpd("reply", v)}
          placeholder="reply"
          accent={ACCENT}
          disabled={disabled}
          maxLength={500}
        />
      </div>
      <IconBtn
        icon={Trash2}
        color="#F23F43"
        title="Delete"
        onClick={onDel}
        disabled={disabled}
      />
    </div>
  );
}

export default function AutoMessFeature({ toast }) {
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

  const [enabled, setEnabled] = useState(false);
  const [rules, setRules] = useState([]);
  const [broadcast, setBroadcast] = useState(false);
  const [mode, setMode] = useState("time");
  const [freq, setFreq] = useState(60);
  const [channel, setChannel] = useState("");
  const [pool, setPool] = useState([]);
  const [newMsg, setNewMsg] = useState("");

  const [autosaveStatus, setAutosaveStatus] = useState("");

  const buildPayload = (overrides = {}) => ({
    enabled,
    triggers: rules
      .map(({ keyword, reply }) => ({ keyword, reply }))
      .filter((r) => r.keyword.trim() !== "" || r.reply.trim() !== ""),
    broadcaster: {
      enabled: broadcast,
      mode,
      value: freq,
      channel_id: channel,
    },
    pool,
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
      const res = await api.saveAutomation(payload, csrf);
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
      setRules([]);
      setBroadcast(false);
      setMode("time");
      setFreq(60);
      setChannel("");
      setPool([]);
      setNewMsg("");
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
      .getAutomation()
      .then((data) => {
        if (cancelled) return;

        const triggers = Array.isArray(data?.triggers)
          ? data.triggers.slice(0, MAX_ITEMS)
          : [];
        setRules(
          triggers.map((t) => ({
            id: ++_id,
            keyword: typeof t?.keyword === "string" ? t.keyword : "",
            reply: typeof t?.reply === "string" ? t.reply : "",
          })),
        );

        const b = data?.broadcaster || {};
        // "count" is the legacy value for what is now called "message".
        const nextMode =
          b.mode === "message" || b.mode === "count" ? "message" : "time";
        const min = nextMode === "time" ? 30 : 1;
        const max = nextMode === "time" ? 600 : 50;
        const raw = b.value == null ? NaN : Number(b.value);
        setMode(nextMode);
        setFreq(
          Number.isFinite(raw)
            ? Math.min(Math.max(Math.round(raw), min), max)
            : nextMode === "time"
              ? 60
              : 5,
        );
        setBroadcast(Boolean(b.enabled));
        setChannel(
          typeof b.channel_id === "string"
            ? b.channel_id
            : b.channel_id
              ? String(b.channel_id)
              : "",
        );

        setPool(
          Array.isArray(data?.pool)
            ? data.pool
                .filter((m) => typeof m === "string")
                .slice(0, MAX_ITEMS)
            : [],
        );
        setEnabled(Boolean(data?.enabled));
        setLoaded(true);
      })
      .catch((err) => {
        if (cancelled) return;
        const msg = err instanceof ApiError ? err.message : "";
        setLoadError(msg || "Could not load Smart Auto Mess settings.");
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
    rules,
    broadcast,
    mode,
    freq,
    channel,
    pool,
  ]);

  const upd = (id, k, v) => {
    setRules((p) => p.map((r) => (r.id === id ? { ...r, [k]: v } : r)));
  };

  const addRule = () => {
    if (rules.length >= MAX_ITEMS) return;
    setRules((p) =>
      p.length >= MAX_ITEMS
        ? p
        : [...p, { id: ++_id, keyword: "", reply: "" }],
    );
  };

  const delRule = (id) => {
    setRules((p) => p.filter((r) => r.id !== id));
  };

  const addMsg = () => {
    const msg = newMsg.trim();
    if (!msg || pool.length >= MAX_ITEMS) return;
    setPool((p) => (p.length >= MAX_ITEMS ? p : [...p, msg]));
    setNewMsg("");
  };

  const removeMsg = (idx) => {
    setPool((p) => p.filter((_, i) => i !== idx));
  };

  const unit = mode === "time" ? "s" : " msg";
  const minFreq = mode === "time" ? 30 : 1;
  const maxFreq = mode === "time" ? 600 : 50;
  const preview = rules.find((r) => r.keyword && r.reply);
  const rulesFull = rules.length >= MAX_ITEMS;
  const poolFull = pool.length >= MAX_ITEMS;
  const ModeIcon = mode === "time" ? Timer : MessagesSquare;
  const modeColor = mode === "time" ? "#F5B642" : "#58B8E8";
  const channelValid = /^\d+$/.test(channel.trim());
  const broadcastStatus = !broadcast
    ? {
        tone: "idle",
        color: "#94A3B8",
        Icon: Radio,
        text: "Broadcaster is off.",
      }
    : !enabled
      ? {
          tone: "warn",
          color: "#F5B642",
          Icon: AlertTriangle,
          text: "Paused — enable Smart Auto Mess above.",
        }
      : !channelValid
        ? {
            tone: "warn",
            color: "#F5B642",
            Icon: AlertTriangle,
            text: "Needs a numeric channel ID.",
          }
        : pool.length === 0
          ? {
              tone: "warn",
              color: "#F5B642",
              Icon: AlertTriangle,
              text: "Needs at least one pool message.",
            }
          : {
              tone: "ok",
              color: "#23A55A",
              Icon: CheckCircle2,
              text:
                mode === "time"
                  ? `Active — every ${freq}s.`
                  : `Active — every ${freq} messages.`,
            };
  const StatusIcon = broadcastStatus.Icon;
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
          Loading Smart Auto Mess settings…
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
        icon={MessageSquare}
        title="Smart Auto Mess"
        emojiId={TG_EMOJI.chat}
        accent={ACCENT}
        enabled={enabled}
        onToggle={(v) => {
          setEnabled(v);
          scheduleAutosave(buildPayload({ enabled: v }));
        }}
        toggleLabel="Smart Auto Mess master toggle"
        disabled={!editable}
        stats={[
          {
            icon: KeyRound,
            label: "Triggers",
            value: rules.length,
            color: ACCENT,
          },
          {
            icon: Layers,
            label: "Message pool",
            value: pool.length,
            color: "#58B8E8",
          },
          {
            icon: Radio,
            label: "Broadcast",
            value: enabled && broadcast ? "ON" : broadcast ? "PAUSED" : "OFF",
            color:
              enabled && broadcast
                ? "#23A55A"
                : broadcast
                  ? "#F5B642"
                  : "#94A3B8",
          },
          {
            icon: ModeIcon,
            label: "Frequency",
            value: `${freq}${unit}`,
            color: modeColor,
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

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 items-stretch">
        {/* LEFT — triggers + preview */}
        <div className="flex flex-col gap-3 min-w-0 h-full">
          <Panel
            icon={Zap}
            title="Keyword Triggers"
            accent={ACCENT}
            className="flex-1"
            action={
              <div className="flex items-center gap-2">
                <span
                  className="text-xs font-bold tabular-nums px-2 py-0.5 rounded-full"
                  style={{ background: `${ACCENT}20`, color: ACCENT }}
                >
                  {rules.length}/{MAX_ITEMS}
                </span>
                <span
                  style={{
                    opacity: rulesFull ? 0.4 : 1,
                    cursor: rulesFull ? "not-allowed" : "pointer",
                    display: "inline-flex",
                    pointerEvents: rulesFull ? "none" : "auto",
                  }}
                >
                  <IconBtn
                    icon={Plus}
                    color={ACCENT}
                    title={
                      rulesFull
                        ? `Max ${MAX_ITEMS} triggers`
                        : "Add trigger"
                    }
                    onClick={rulesFull ? undefined : addRule}
                    disabled={rulesFull || !editable}
                  />
                </span>
              </div>
            }
          >
            {loading ? (
              <div
                className="flex items-center justify-center gap-2 py-6 text-sm"
                style={{ color: "#94A3B8" }}
              >
                <Loader2 size={14} className="animate-spin" />
                Loading triggers…
              </div>
            ) : rules.length === 0 ? (
              <EmptyState
                emojiId={TG_EMOJI.lightning}
                title="No triggers yet"
              />
            ) : (
              <div className="flex flex-col">
                {rules.map((r, i) => (
                  <RuleRow
                    key={r.id}
                    r={r}
                    first={i === 0}
                    onUpd={(k, v) => upd(r.id, k, v)}
                    onDel={() => delRule(r.id)}
                    disabled={!editable}
                  />
                ))}
              </div>
            )}

            {!loading && (
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
                <div
                  className="flex flex-1 flex-col rounded-xl overflow-hidden min-h-0"
                  style={{ background: "#313338" }}
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
                  {preview ? (
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
                            className="text-sm"
                            style={{ color: "#E2E8F0" }}
                          >
                            {preview.keyword}
                          </div>
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <Avatar name="shadowbyte_exe" size={28} />
                        <div className="min-w-0">
                          <div className="text-sm font-semibold text-white">
                            shadowbyte_exe
                          </div>
                          <div
                            className="text-sm"
                            style={{ color: "#E2E8F0" }}
                          >
                            {preview.reply}
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
                  ) : (
                    <div className="flex flex-1 flex-col gap-3 p-3 min-h-0 opacity-40">
                      <div className="flex gap-2">
                        <div
                          className="w-7 h-7 rounded-full shrink-0"
                          style={{ background: "#4E5058" }}
                        />
                        <div className="flex flex-col gap-1.5 pt-1">
                          <div
                            className="h-2.5 w-16 rounded"
                            style={{ background: "#4E5058" }}
                          />
                          <div
                            className="h-2.5 w-40 rounded"
                            style={{ background: "#4E5058" }}
                          />
                        </div>
                      </div>
                      <div className="flex gap-2">
                        <div
                          className="w-7 h-7 rounded-full shrink-0"
                          style={{ background: "#4E5058" }}
                        />
                        <div className="flex flex-col gap-1.5 pt-1">
                          <div
                            className="h-2.5 w-24 rounded"
                            style={{ background: "#4E5058" }}
                          />
                          <div
                            className="h-2.5 w-48 rounded"
                            style={{ background: "#4E5058" }}
                          />
                        </div>
                      </div>
                    </div>
                  )}
                  <div className="px-3 pb-3 shrink-0">
                    <div
                      className="flex items-center gap-2 px-2.5 py-2 rounded-lg text-xs"
                      style={{ background: "#383A40", color: "#6D6F78" }}
                    >
                      <Send size={12} />
                      Message @friend…
                    </div>
                  </div>
                </div>
              </div>
            )}
          </Panel>
        </div>

        {/* RIGHT — broadcaster + pool */}
        <div className="flex flex-col gap-3 min-w-0 h-full">
          <Panel
            icon={Radio}
            title="Broadcaster"
            accent="#58B8E8"
            action={
              <Toggle
                enabled={broadcast}
                onChange={(v) => {
                  setBroadcast(v);
                  if (v && !enabled) setEnabled(true);
                }}
                size="sm"
                label="Broadcaster toggle"
                disabled={!editable}
              />
            }
          >
            <div className="flex flex-col gap-2.5">
              <ChoiceGrid
                options={MODES}
                value={mode}
                onChange={(v) => {
                  setMode(v);
                  setFreq(v === "time" ? 60 : 5);
                }}
                accent="#58B8E8"
                cols={2}
                disabled={!editable}
              />
              <div
                role="status"
                aria-live="polite"
                className="flex items-start gap-2 px-2.5 py-2 rounded-lg text-xs font-semibold"
                style={{
                  background: `${broadcastStatus.color}12`,
                  color: broadcastStatus.color,
                }}
              >
                <StatusIcon size={13} className="mt-0.5 shrink-0" />
                <span className="leading-relaxed">{broadcastStatus.text}</span>
              </div>
              <div
                className="flex flex-col gap-2.5"
                style={{
                  opacity: broadcast ? 1 : 0.45,
                  transition: "opacity .2s",
                }}
              >
                <SliderRow
                  value={freq}
                  onChange={(v) => {
                    setFreq(v);
                  }}
                  min={minFreq}
                  max={maxFreq}
                  unit={unit}
                  accent={modeColor}
                  disabled={!editable}
                />
                <IconInput
                  icon={Hash}
                  value={channel}
                  onChange={(v) => {
                    setChannel(v);
                  }}
                  placeholder="Channel ID (optional)"
                  mono
                  accent={modeColor}
                  disabled={!editable}
                />
              </div>
            </div>
          </Panel>

          <Panel
            icon={Layers}
            title="Message Pool"
            accent="#F5B642"
            className="flex-1"
            action={
              <span
                className="text-xs font-bold tabular-nums px-2 py-0.5 rounded-full"
                style={{ background: "#F5B64220", color: "#F5B642" }}
              >
                {pool.length}/{MAX_ITEMS}
              </span>
            }
          >
            {loading ? (
              <div
                className="flex items-center gap-2 text-sm py-2"
                style={{ color: "#94A3B8" }}
              >
                <Loader2 size={13} className="animate-spin" />
                Loading messages…
              </div>
            ) : pool.length === 0 ? (
              <EmptyState emojiId={TG_EMOJI.chat} title="No messages yet" />
            ) : (
              <div className="flex flex-wrap gap-1.5">
                {pool.map((m, i) => (
                  <span
                    key={i}
                    className="flex items-center gap-1.5 text-xs pl-2 pr-1 py-0.5 rounded-full max-w-[220px] truncate"
                    title={m}
                    style={{
                      background: "var(--surface-inset)",
                      color: "#E2E8F0",
                    }}
                  >
                    <span className="min-w-0 truncate">{m}</span>
                    <button
                      onClick={() => removeMsg(i)}
                      disabled={!editable}
                      className="w-4 h-4 shrink-0 rounded-full flex items-center justify-center transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 disabled:opacity-50 disabled:cursor-not-allowed"
                      style={{ background: "#F23F4325", color: "#F23F43" }}
                    >
                      <X size={10} />
                    </button>
                  </span>
                ))}
              </div>
            )}
            <div className="flex gap-2">
              <div className="flex-1 min-w-0">
                <IconInput
                  icon={Send}
                  value={newMsg}
                  onChange={(v) => setNewMsg(v.slice(0, 200))}
                  placeholder="New message…"
                  maxLength={200}
                  accent="#F5B642"
                  disabled={!editable}
                />
              </div>
              <button
                onClick={addMsg}
                disabled={poolFull || loading || !editable}
                title={
                  poolFull ? `Max ${MAX_ITEMS} messages` : "Add message"
                }
                className="w-10 rounded-xl flex items-center justify-center shrink-0 transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-sky-400/70 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117]"
                style={{
                  background: "#F5B642",
                  color: "#0B0E14",
                  opacity: poolFull || loading || !editable ? 0.4 : 1,
                  cursor:
                    poolFull || loading || !editable
                      ? "not-allowed"
                      : "pointer",
                }}
              >
                <Plus size={16} />
              </button>
            </div>
          </Panel>
        </div>
      </div>
    </div>
  );
}
