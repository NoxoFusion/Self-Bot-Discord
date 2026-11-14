"use client";
import { useCallback, useEffect, useState } from "react";
import {
  Activity,
  AlertTriangle,
  Bot,
  Clock,
  Gauge,
  RefreshCw,
  Users,
} from "lucide-react";
import {
  api,
  formatUptime,
  normalizeCapabilities,
  normalizeStatus,
} from "../../../lib/api";
import { useSessionContext } from "../../../lib/session";
import { useLiveState } from "../../../lib/ws";
import { useAccent } from "../../../lib/theme";

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B0E14]";

// ─── Helpers ─────────────────────────────────────────────────────────────────
function botStateMeta(state) {
  const key = String(state || "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  if (key === "online" || key === "connected" || key === "ready")
    return { label: "Online", color: "#23A55A" };
  if (key === "offline" || key === "disconnected")
    return { label: "Offline", color: "#F23F43" };
  if (key === "not_configured" || key === "unconfigured")
    return { label: "Not configured", color: "#F5B642" };
  if (!key || key === "unknown") return { label: "Unknown", color: "#94A3B8" };
  return { label: key.replace(/_/g, " "), color: "#94A3B8" };
}

function capMeta(status) {
  const key = String(status || "").toLowerCase();
  if (key === "available" || key === "ready" || key === "ok")
    return { label: "Available", color: "#23A55A" };
  if (key === "needs_config" || key === "needs-config" || key === "config")
    return { label: "Needs config", color: "#F5B642" };
  if (key === "partial")
    return { label: "Partial", color: "#F5B642" };
  if (key === "unsupported" || key === "unavailable")
    return { label: "Unsupported", color: "#94A3B8" };
  return { label: key ? key.replace(/_/g, " ") : "Unknown", color: "#94A3B8" };
}

// ─── Metric Card ─────────────────────────────────────────────────────────────
function Metric({ icon: Icon, label, value, accent, index = 0 }) {
  return (
    <div
      className="stagger-item rounded-2xl border p-4 flex flex-col gap-3 relative overflow-hidden"
      style={{
        "--i": index,
        background: "var(--surface-glass)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        borderColor: "var(--glass-border)",
        boxShadow: "var(--elevation-1)",
      }}
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(ellipse at 85% 15%, ${accent}12 0%, transparent 55%)`,
        }}
      />
      <div className="relative flex items-start justify-between">
        <div
          className="w-10 h-10 rounded-xl flex items-center justify-center"
          style={{ background: `${accent}18`, border: `1px solid ${accent}30` }}
        >
          <Icon size={17} style={{ color: accent }} />
        </div>
      </div>
      <div className="relative min-w-0">
        <div
          className="text-lg font-extrabold text-white tracking-tight leading-none truncate"
          style={{
            fontFamily: "var(--font-display)",
            letterSpacing: "-0.01em",
          }}
        >
          {value}
        </div>
        <div
          className="text-xs font-medium mt-1.5"
          style={{ color: "#94A3B8" }}
        >
          {label}
        </div>
      </div>
    </div>
  );
}

function CapBadge({ status }) {
  const meta = capMeta(status);
  return (
    <span
      className="text-xs font-bold px-2.5 py-1 rounded-full shrink-0"
      style={{
        background: `${meta.color}18`,
        color: meta.color,
        border: `1px solid ${meta.color}35`,
      }}
    >
      {meta.label}
    </span>
  );
}

function Stat({ label, value }) {
  return (
    <div
      className="rounded-xl border px-3 py-2 min-w-0"
      style={{
        background: "var(--surface-inset)",
        borderColor: "var(--glass-border)",
      }}
    >
      <div className="text-xs font-semibold" style={{ color: "#94A3B8" }}>
        {label}
      </div>
      <div
        className="text-sm font-extrabold font-mono truncate mt-1 text-white"
        title={String(value)}
      >
        {value}
      </div>
    </div>
  );
}

function Notice({ tone = "amber", title, children }) {
  const palette =
    tone === "red"
      ? { color: "#F23F43", bg: "#F23F430D", border: "#F23F4340" }
      : tone === "blue"
        ? { color: "#5865F2", bg: "#5865F20D", border: "#5865F240" }
        : { color: "#F5B642", bg: "#F5B6420D", border: "#F5B64240" };

  return (
    <div
      className="rounded-xl border px-4 py-3 flex items-start gap-3"
      style={{ background: palette.bg, borderColor: palette.border }}
    >
      <AlertTriangle
        size={16}
        className="mt-0.5 shrink-0"
        style={{ color: palette.color }}
      />
      <div className="min-w-0">
        <div
          className="text-sm font-bold"
          style={{ color: palette.color }}
        >
          {title}
        </div>
        <div
          className="text-sm leading-relaxed mt-1"
          style={{ color: "#CBD5E1" }}
        >
          {children}
        </div>
      </div>
    </div>
  );
}

// ─── Main ────────────────────────────────────────────────────────────────────
export default function DashboardView() {
  const ACCENT = useAccent();
  const session = useSessionContext();
  const { connected, liveState } = useLiveState();
  const [status, setStatus] = useState(null);
  const [capabilities, setCapabilities] = useState([]);
  const [error, setError] = useState(null);
  const [capError, setCapError] = useState(null);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [refreshing, setRefreshing] = useState(false);

  const refresh = useCallback(async () => {
    if (!session.authenticated) return;
    setRefreshing(true);
    const [statusResult, capResult] = await Promise.allSettled([
      api.getStatus(),
      api.getCapabilities(),
    ]);

    if (statusResult.status === "fulfilled") {
      setStatus(normalizeStatus(statusResult.value));
      setError(null);
      setLastUpdated(new Date());
    } else {
      setError(statusResult.reason);
    }

    if (capResult.status === "fulfilled") {
      setCapabilities(normalizeCapabilities(capResult.value));
      setCapError(null);
    } else {
      setCapError(capResult.reason);
    }

    setRefreshing(false);
  }, [session.authenticated]);

  useEffect(() => {
    if (!session.authenticated) {
      setStatus(null);
      setCapabilities([]);
      setError(null);
      setCapError(null);
      setLastUpdated(null);
      return;
    }

    refresh();
    if (connected) {
      // The WebSocket pushes bot status every 2s; REST stays the fallback.
      return undefined;
    }
    const timer = setInterval(() => {
      api
        .getStatus()
        .then((data) => {
          setStatus(normalizeStatus(data));
          setError(null);
          setLastUpdated(new Date());
        })
        .catch((err) => setError(err));
    }, 10000);

    return () => clearInterval(timer);
  }, [session.authenticated, refresh, connected]);

  useEffect(() => {
    if (!connected || !liveState?.bot) return;

    setStatus((previous) =>
      normalizeStatus({
        bot: liveState.bot,
        api: {
          version: previous?.apiVersion ?? null,
          uptime_seconds: previous?.uptimeSeconds ?? null,
        },
        warnings: previous?.warnings ?? [],
      }),
    );
    setError(null);
    setLastUpdated(new Date());
  }, [connected, liveState]);

  const bot = status?.bot || {};
  const stateMeta = botStateMeta(bot.state);
  const apiVersion = status?.apiVersion ?? "—";
  const guildCount = bot.guildCount != null ? bot.guildCount : "—";
  const latency = bot.latencyMs != null ? `${bot.latencyMs} ms` : "—";
  const uptime = formatUptime(status?.uptimeSeconds);
  const notConfigured = Array.isArray(status?.warnings)
    ? status.warnings.some((warning) => /not configured/i.test(warning))
    : false;
  const identityMeta = notConfigured
    ? { label: "Not configured", color: "#F5B642" }
    : stateMeta;
  const username =
    bot.username || (notConfigured ? "Not configured" : "Bot offline");
  const botId = bot.userId || "—";
  const offline = session.error?.status === 0 || error?.status === 0;

  let notice = null;
  if (session.loading) {
    notice = (
      <Notice tone="blue" title="Connecting to local API…">
        Waiting for the local backend at 127.0.0.1:8765.
      </Notice>
    );
  } else if (offline) {
    notice = (
      <Notice tone="red" title="Local API offline">
        Run{" "}
        <code className="font-mono" style={{ color: "#FCA5A5" }}>
          python dashboard/backend/main.py
        </code>{" "}
        from the repo root, then refresh.
      </Notice>
    );
  } else if (!session.authenticated) {
    notice = (
      <Notice tone="amber" title="Not paired">
        Enter the 6-digit pairing code in the banner above to load live data.
        {session.error ? ` (${session.error.message})` : ""}
      </Notice>
    );
  } else if (error) {
    notice = (
      <Notice tone="red" title="Could not load bot status">
        {error?.data?.error || error?.message || "Unknown API error."}
      </Notice>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {notice}

      {status?.warnings?.length > 0 && (
        <Notice tone="amber" title="Backend warnings">
          {status.warnings.join(" · ")}
        </Notice>
      )}

      {/* Row 1: Metrics */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4">
        <Metric
          icon={Bot}
          label="Bot State"
          value={identityMeta.label}
          accent={identityMeta.color}
          index={0}
        />
        <Metric
          icon={Users}
          label="Guilds"
          value={guildCount}
          accent={ACCENT}
          index={1}
        />
        <Metric
          icon={Gauge}
          label="Latency"
          value={latency}
          accent={ACCENT}
          index={2}
        />
        <Metric
          icon={Clock}
          label="API uptime"
          value={uptime}
          accent="#FEE75C"
          index={3}
        />
      </div>

      {/* Row 2: Bot status | Features | Health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Bot status */}
        <div
          className="rounded-2xl border p-4 flex flex-col gap-3 h-full relative overflow-hidden"
          style={{
            background: "var(--surface-glass)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            borderColor: "var(--glass-border)",
            boxShadow:
              "inset 0 1px 0 var(--glass-highlight), 0 12px 32px rgba(0,0,0,0.28)",
          }}
        >
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              background: `radial-gradient(ellipse at 15% 0%, ${identityMeta.color}12 0%, transparent 55%)`,
            }}
          />
          <div className="relative flex items-center gap-3">
            <div
              className="w-16 h-16 rounded-full flex items-center justify-center shrink-0"
              style={{
                background: "linear-gradient(135deg,#5865F2,#7C5CFF)",
                border: `2px solid ${identityMeta.color}45`,
                boxShadow: `0 0 22px ${identityMeta.color}30`,
              }}
            >
              <Bot size={28} color="#fff" />
            </div>
            <div className="min-w-0 flex-1">
              <div
                className="text-lg font-extrabold truncate leading-tight"
                style={{ color: notConfigured ? "#F5B642" : "#FFFFFF" }}
              >
                {username}
              </div>
              <div
                className="text-xs font-mono truncate mt-0.5"
                style={{ color: "#94A3B8" }}
              >
                {botId}
              </div>
              <span
                className="inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1 rounded-full mt-2"
                style={{
                  background: `${identityMeta.color}20`,
                  color: identityMeta.color,
                  border: `1px solid ${identityMeta.color}55`,
                }}
              >
                <span
                  className="w-2 h-2 rounded-full"
                  style={{
                    background: identityMeta.color,
                    boxShadow: `0 0 8px ${identityMeta.color}`,
                  }}
                />
                {identityMeta.label}
              </span>
            </div>
          </div>
          <div className="h-px" style={{ background: "var(--glass-border)" }} />
          <div className="grid grid-cols-2 gap-2 mt-auto">
            <Stat label="Latency" value={latency} />
            <Stat label="Guilds" value={guildCount} />
            <Stat label="API version" value={apiVersion} />
            <Stat label="API uptime" value={uptime} />
          </div>
        </div>

        {/* Feature availability */}
        <div
          className="rounded-2xl border p-4 flex flex-col gap-2.5 h-full"
          style={{
            background: "var(--surface-glass)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            borderColor: "var(--glass-border)",
            boxShadow:
              "inset 0 1px 0 var(--glass-highlight), 0 12px 32px rgba(0,0,0,0.28)",
          }}
        >
          <div
            className="text-base font-bold text-white"
            style={{
              fontFamily: "var(--font-display)",
              letterSpacing: "-0.01em",
            }}
          >
            Feature availability
          </div>

          {capError ? (
            <div className="text-sm leading-relaxed" style={{ color: "#F87171" }}>
              Could not load capabilities:{" "}
              {capError?.data?.error || capError?.message || "unknown error"}
            </div>
          ) : capabilities.length === 0 ? (
            <div
              className="text-sm py-4 text-center"
              style={{ color: "#94A3B8" }}
            >
              {session.authenticated
                ? "No capability data reported by the backend."
                : "Pair the dashboard to load capabilities."}
            </div>
          ) : (
            <div className="flex flex-col gap-1.5 overflow-y-auto pr-1" style={{ maxHeight: 230 }}>
              {capabilities.map((cap) => (
                <div
                  key={cap.id}
                  className="flex items-start gap-2.5 p-2.5 rounded-xl border"
                  style={{
                    background: "var(--surface-inset)",
                    borderColor: "var(--glass-border)",
                  }}
                >
                  <div className="flex-1 min-w-0">
                    <div className="text-sm font-semibold text-white truncate">
                      {cap.label}
                    </div>
                    {cap.reason && (
                      <div
                        className="text-xs mt-0.5 leading-relaxed"
                        style={{ color: "#94A3B8" }}
                      >
                        {cap.reason}
                      </div>
                    )}
                  </div>
                  <CapBadge status={cap.status} />
                </div>
              ))}
            </div>
          )}
        </div>

        {/* System health */}
        <div
          className="rounded-2xl border p-4 flex flex-col gap-3 h-full"
          style={{
            background: "var(--surface-glass)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            borderColor: "var(--glass-border)",
            boxShadow: "var(--elevation-2)",
          }}
        >
          <div className="flex items-center justify-between gap-2">
            <div className="flex items-center gap-2">
              <Activity size={16} style={{ color: "#35C46A" }} />
              <span
                className="text-base font-bold text-white"
                style={{
                  fontFamily: "var(--font-display)",
                  letterSpacing: "-0.01em",
                }}
              >
                System health
              </span>
            </div>
            <button
              onClick={refresh}
              disabled={!session.authenticated || refreshing}
              className={`flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg border transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.97] ${FOCUS_RING}`}
              style={{
                background: `${ACCENT}18`,
                borderColor: `${ACCENT}50`,
                color: session.authenticated ? ACCENT : "#64748B",
                cursor:
                  !session.authenticated || refreshing
                    ? "not-allowed"
                    : "pointer",
              }}
            >
              <RefreshCw
                size={12}
                aria-hidden="true"
                className={refreshing ? "animate-spin" : undefined}
              />
              Refresh
            </button>
          </div>

          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium" style={{ color: "#94A3B8" }}>
              API version
            </span>
            <span className="text-sm font-mono font-bold text-white truncate">
              {apiVersion}
            </span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium" style={{ color: "#94A3B8" }}>
              Bot state
            </span>
            <span
              className="inline-flex items-center gap-1.5 text-xs font-bold px-2.5 py-1 rounded-full"
              style={{
                background: `${identityMeta.color}18`,
                color: identityMeta.color,
                border: `1px solid ${identityMeta.color}45`,
              }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{
                  background: identityMeta.color,
                  boxShadow: `0 0 6px ${identityMeta.color}`,
                }}
              />
              {identityMeta.label}
            </span>
          </div>
          <div className="flex items-center justify-between gap-2">
            <span className="text-xs font-medium" style={{ color: "#94A3B8" }}>
              Last updated
            </span>
            <span className="text-sm font-mono font-bold text-white truncate">
              {lastUpdated ? lastUpdated.toLocaleTimeString() : "—"}
            </span>
          </div>

          <div
            className="h-px mt-auto"
            style={{ background: "var(--glass-border)" }}
          />
          <div
            className="flex items-center gap-2 px-3 py-2 rounded-xl border"
            style={{
              background: "var(--surface-inset)",
              borderColor: "var(--glass-border)",
            }}
          >
            <span
              className="w-2 h-2 rounded-full shrink-0"
              style={{
                background: identityMeta.color,
                boxShadow: `0 0 8px ${identityMeta.color}`,
              }}
            />
            <span
              className="text-xs font-mono font-bold truncate"
              style={{ color: "#E2E8F0" }}
            >
              127.0.0.1:8765
            </span>
            <span
              className="ml-auto text-xs font-bold shrink-0"
              style={{
                color: session.authenticated ? "#23A55A" : "#F5B642",
              }}
            >
              {session.authenticated ? "Active" : "Unpaired"}
            </span>
          </div>
        </div>
      </div>
    </div>
  );
}
