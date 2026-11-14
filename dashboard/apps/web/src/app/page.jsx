"use client";
import { useCallback, useEffect, useState } from "react";
import {
  LayoutDashboard,
  Grid3X3,
  Radio,
  MessageSquare,
  Moon,
  Heart,
  Headphones,
  Wrench,
  Settings,
  ChevronDown,
  Menu,
  X,
  Info,
  AlertTriangle,
  KeyRound,
} from "lucide-react";
import { ToastContainer, useToast } from "../components/dashboard/Toast";
import DashboardView from "../components/dashboard/views/DashboardView";
import SettingsView from "../components/dashboard/views/SettingsView";
import AboutView from "../components/dashboard/views/AboutView";
import RichPresenceFeature from "../components/dashboard/features/RichPresenceFeature";
import AutoMessFeature from "../components/dashboard/features/AutoMessFeature";
import AFKFeature from "../components/dashboard/features/AFKFeature";
import ReactionsFeature from "../components/dashboard/features/ReactionsFeature";
import VoiceFeature from "../components/dashboard/features/VoiceFeature";
import UtilityFeature from "../components/dashboard/features/UtilityFeature";
import { SessionProvider, useSessionContext } from "../lib/session";
import { api, normalizeStatus } from "../lib/api";
import { useAccent } from "../lib/theme";

// ─── constants ───────────────────────────────────────────────────────────────
const FEATURES = [
  {
    id: "rpc",
    label: "Rich Presence",
    icon: Radio,
  },
  {
    id: "automess",
    label: "Smart Auto Mess",
    icon: MessageSquare,
  },
  { id: "afk", label: "AFK Assistant", icon: Moon },
  { id: "reactions", label: "Auto Reactions", icon: Heart },
  { id: "voice", label: "Voice", icon: Headphones },
  {
    id: "utility",
    label: "Utility",
    icon: Wrench,
  },
];

const VIEW_LABELS = {
  dashboard: "Dashboard",
  rpc: "Rich Presence",
  automess: "Smart Auto Mess",
  afk: "AFK Assistant",
  reactions: "Auto Reactions",
  voice: "Voice",
  utility: "Utility",
  settings: "Settings",
  about: "Noxo Fusion",
};

// ─── View switcher ────────────────────────────────────────────────────────────
function ViewContent({ view, toast }) {
  switch (view) {
    case "dashboard":
      return <DashboardView />;
    case "rpc":
      return <RichPresenceFeature toast={toast} />;
    case "automess":
      return <AutoMessFeature toast={toast} />;
    case "afk":
      return <AFKFeature toast={toast} />;
    case "reactions":
      return <ReactionsFeature toast={toast} />;
    case "voice":
      return <VoiceFeature toast={toast} />;
    case "utility":
      return <UtilityFeature toast={toast} />;
    case "settings":
      return <SettingsView toast={toast} />;
    case "about":
      return <AboutView />;
    default:
      return <DashboardView />;
  }
}

// ─── API status helpers ──────────────────────────────────────────────────────
function apiState(session) {
  if (session.loading) return { label: "Local API · Checking…", color: "#94A3B8" };
  if (session.authenticated)
    return { label: "Local API · Online", color: "#23A55A" };
  if (session.error?.status === 0)
    return { label: "Local API · Offline", color: "#F23F43" };
  return { label: "Local API · Not paired", color: "#F5B642" };
}

function userStatusMeta({ authenticated, loading, error, botStatus }) {
  if (!authenticated) {
    if (error?.status === 0) return { label: "Offline", color: "#F23F43" };
    if (loading) return { label: "Connecting", color: "#94A3B8" };
    return { label: "Not paired", color: "#F5B642" };
  }

  if (!botStatus) return { label: "Connecting", color: "#94A3B8" };

  const key = String(botStatus.bot?.state || "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  if (key === "online" || key === "ready" || key === "connected")
    return { label: "Online", color: "#23A55A" };
  if (key === "offline" || key === "disconnected")
    return { label: "Offline", color: "#F23F43" };
  if (key === "not_configured" || key === "unconfigured")
    return { label: "Not configured", color: "#F5B642" };
  return { label: "Connected", color: "#23A55A" };
}

function ApiPill() {
  const session = useSessionContext();
  const { label, color } = apiState(session);

  return (
    <>
      <div
        className="hidden md:flex items-center gap-2 px-3 py-1.5 rounded-full border text-xs shrink-0"
        style={{
          background: `${color}12`,
          borderColor: `${color}45`,
          color,
        }}
      >
        <span
          className="w-1.5 h-1.5 rounded-full"
          style={{ background: "currentColor", boxShadow: "0 0 6px currentColor" }}
        />
        <span className="font-mono text-xs">{label}</span>
      </div>
      <span
        role="status"
        aria-label={label}
        title={label}
        className="md:hidden flex items-center justify-center w-7 h-7 rounded-full border shrink-0"
        style={{
          background: `${color}12`,
          borderColor: `${color}45`,
          color,
        }}
      >
        <span
          aria-hidden="true"
          className="w-2 h-2 rounded-full"
          style={{ background: "currentColor", boxShadow: "0 0 6px currentColor" }}
        />
      </span>
    </>
  );
}

function FooterStatus() {
  const session = useSessionContext();
  const { color } = apiState(session);
  const label = session.loading
    ? "Checking…"
    : session.authenticated
      ? "Online"
      : session.error?.status === 0
        ? "Offline"
        : "Not paired";

  return (
    <span
      className="flex items-center gap-1.5 text-xs font-mono"
      style={{ color }}
    >
      <span
        className="w-1.5 h-1.5 rounded-full"
        style={{ background: color, boxShadow: `0 0 6px ${color}` }}
      />
      {label}
    </span>
  );
}

// ─── Pairing banner ──────────────────────────────────────────────────────────
function PairingBanner() {
  const { loading, authenticated, error, pair } = useSessionContext();
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [pairError, setPairError] = useState(null);

  const handlePair = async (e) => {
    e.preventDefault();
    if (code.length !== 6) return;
    setBusy(true);
    setPairError(null);
    try {
      await pair(code);
      setCode("");
    } catch (err) {
      if (err?.status === 0) setPairError("Local API offline.");
      else if (err?.status === 401 || err?.status === 403)
        setPairError("Invalid or expired pairing code.");
      else if (err?.status === 429)
        setPairError("Too many attempts. Try again shortly.");
      else setPairError(err?.data?.error || "Pairing failed.");
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="mb-4 text-sm" style={{ color: "#94A3B8" }}>
        Connecting to local API…
      </div>
    );
  }

  if (error?.status === 0) {
    return (
      <div
        className="mb-4 flex items-start gap-3 rounded-xl border px-4 py-3"
        style={{
          background: "#F23F430D",
          borderColor: "#F23F4340",
          color: "#F87171",
        }}
      >
        <AlertTriangle size={16} className="mt-0.5 shrink-0" />
        <div className="text-sm">
          <div className="font-bold">Local API offline</div>
          <div className="mt-1" style={{ color: "#FCA5A5" }}>
            Run{" "}
            <code
              className="font-mono px-1.5 py-0.5 rounded"
              style={{ background: "#F23F4315" }}
            >
              python dashboard/backend/main.py
            </code>{" "}
            from the repo root.
          </div>
        </div>
      </div>
    );
  }

  if (!authenticated) {
    return (
      <div
        className="mb-4 rounded-xl border px-4 py-3"
        style={{ background: "#F5B6420D", borderColor: "#F5B64240" }}
      >
        <div className="flex flex-wrap items-center gap-3">
          <KeyRound size={16} style={{ color: "#F5B642", flexShrink: 0 }} />
          <div className="min-w-0">
            <div className="text-sm font-semibold text-white">
              Pair this dashboard
            </div>
            <div className="text-xs mt-0.5" style={{ color: "#94A3B8" }}>
              Enter the 6-digit code shown by the backend.
            </div>
          </div>
          <form
            onSubmit={handlePair}
            className="flex items-center gap-2 ml-auto shrink-0"
          >
            <input
              value={code}
              onChange={(e) =>
                setCode(e.target.value.replace(/\D/g, "").slice(0, 6))
              }
              inputMode="numeric"
              autoComplete="one-time-code"
              placeholder="000000"
              aria-label="Pairing code"
              className="w-28 px-3 py-1.5 rounded-lg border text-center font-mono text-sm tracking-[0.3em] text-white outline-none"
              style={{ background: "var(--surface-inset)", borderColor: "var(--glass-border)" }}
            />
            <button
              type="submit"
              disabled={busy || code.length !== 6}
              className="px-3.5 py-1.5 rounded-lg text-sm font-bold transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.97]"
              style={{
                background: code.length === 6 ? "#F5B642" : "#2D3748",
                color: code.length === 6 ? "#0B0E14" : "#94A3B8",
                cursor: busy || code.length !== 6 ? "not-allowed" : "pointer",
              }}
            >
              {busy ? "Pairing…" : "Pair"}
            </button>
          </form>
        </div>
        {(pairError || error) && (
          <div className="text-xs mt-2" style={{ color: "#F87171" }}>
            {pairError || error?.message}
          </div>
        )}
      </div>
    );
  }

  return null;
}

// ─── Sidebar ─────────────────────────────────────────────────────────────────
export function Sidebar({ activeView, setView }) {
  const ACCENT = useAccent();
  const [featOpen, setFeatOpen] = useState(true);
  const [botStatus, setBotStatus] = useState(null);
  const [failedAvatarUrl, setFailedAvatarUrl] = useState(null);
  const { loading, authenticated, error } = useSessionContext();

  useEffect(() => {
    if (!authenticated) {
      setBotStatus(null);
      return undefined;
    }

    let cancelled = false;
    api
      .getStatus()
      .then((raw) => {
        if (!cancelled) setBotStatus(normalizeStatus(raw));
      })
      .catch(() => {
        if (!cancelled) setBotStatus({ bot: { state: "offline" } });
      });

    return () => {
      cancelled = true;
    };
  }, [authenticated]);

  const bot = botStatus?.bot || {};
  const username = authenticated
    ? bot.displayName || bot.username || "Discord User"
    : error?.status === 0
      ? "Offline"
      : loading
        ? "Connecting…"
        : "Not paired";
  const avatarUrl = bot.avatarUrl || null;
  const showAvatarImg = Boolean(avatarUrl) && failedAvatarUrl !== avatarUrl;
  const initialSource = bot.displayName || bot.username || "";
  const firstInitial = Array.from(initialSource.trim())[0];
  const avatarInitial = firstInitial ? firstInitial.toUpperCase() : "…";
  const statusMeta = userStatusMeta({
    authenticated,
    loading,
    error,
    botStatus,
  });
  const featuresActive = FEATURES.some(({ id }) => id === activeView);
  const accentVars = {
    "--accent": ACCENT,
    "--nav-hover-bg": `${ACCENT}14`,
    "--nav-hover-border": `${ACCENT}2E`,
    "--tw-ring-color": `${ACCENT}99`,
  };

  return (
    <div
      className="flex flex-col h-full select-none"
      style={{ background: "transparent" }}
    >
      <style>{`
        @keyframes avatarFadeIn { from { opacity: 0; } to { opacity: 1; } }
        .avatar-fade { animation: avatarFadeIn 200ms cubic-bezier(0.16,1,0.3,1) both; }
      `}</style>
      {/* Discord user profile */}
      <div
        className="px-5 pt-6 pb-5 border-b"
        style={{ borderColor: "var(--glass-border, rgba(255,255,255,0.09))" }}
      >
        <div className="flex flex-col items-center gap-3 text-center">
          <div className="relative">
            <div
              className="p-[2px] rounded-full"
              style={{
                background: `linear-gradient(135deg,${ACCENT},#23A55A)`,
                boxShadow: `0 0 18px ${ACCENT}50`,
              }}
            >
              <div
                className="w-16 h-16 rounded-full overflow-hidden"
                style={{ background: "var(--surface-solid, #0D1117)" }}
              >
                {showAvatarImg ? (
                  <img
                    key={avatarUrl}
                    src={avatarUrl}
                    alt={`${username} avatar`}
                    width={64}
                    height={64}
                    onError={() => setFailedAvatarUrl(avatarUrl)}
                    className="avatar-fade w-full h-full object-cover"
                  />
                ) : (
                  <span
                    className="w-full h-full flex items-center justify-center text-2xl font-bold leading-none text-white"
                    style={{
                      background: `linear-gradient(135deg, ${ACCENT}, ${ACCENT}88)`,
                    }}
                  >
                    {avatarInitial}
                  </span>
                )}
              </div>
            </div>
            <span
              className="absolute w-3.5 h-3.5 rounded-full border-2"
              style={{
                background: statusMeta.color,
                borderColor:
                  "var(--surface-glass-strong, rgba(16,20,30,0.82))",
                bottom: 2,
                right: 2,
                boxShadow: `0 0 8px ${statusMeta.color}`,
              }}
            />
          </div>
          <div className="min-w-0 max-w-[190px]">
            <div
              className="text-base font-bold text-white tracking-tight truncate"
              title={username}
            >
              {username}
            </div>
            <div
              className="inline-flex items-center gap-1.5 text-xs font-semibold mt-1.5 px-3 py-1 rounded-full"
              style={{
                background: `${statusMeta.color}15`,
                color: statusMeta.color,
                border: `1px solid ${statusMeta.color}30`,
              }}
            >
              <span
                className="w-1.5 h-1.5 rounded-full"
                style={{ background: statusMeta.color }}
              />
              {statusMeta.label}
            </div>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 overflow-y-auto px-3 py-4 flex flex-col gap-0.5">
        {/* Dashboard */}
        <NavBtn
          id="dashboard"
          label="Dashboard"
          Icon={LayoutDashboard}
          activeView={activeView}
          setView={setView}
          accent={ACCENT}
        />

        {/* Features accordion parent */}
        <button
          onClick={() => setFeatOpen((v) => !v)}
          aria-expanded={featOpen}
          className={`group flex items-center gap-3 px-3 py-2.5 rounded-xl w-full text-left text-sm tracking-[0.025em] border border-transparent transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:translate-x-[3px] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117] mt-1 ${
            featuresActive
              ? "font-semibold text-white"
              : "font-medium text-[#94A3B8] hover:bg-[var(--nav-hover-bg)] hover:border-[color:var(--nav-hover-border)] hover:text-[#F8FAFC]"
          }`}
          style={{
            ...accentVars,
            ...(featuresActive
              ? {
                  background: `linear-gradient(90deg, ${ACCENT}26, ${ACCENT}08)`,
                  borderColor: `${ACCENT}55`,
                }
              : {}),
          }}
        >
          <Grid3X3
            size={15}
            className={`shrink-0 transition-colors duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] ${
              featuresActive
                ? ""
                : "text-[#64748B] group-hover:text-[var(--accent)]"
            }`}
            style={featuresActive ? { color: ACCENT } : undefined}
          />
          <span className="flex-1">Features</span>
          <span
            className="text-xs font-semibold px-1.5 py-0.5 rounded-full mr-1"
            style={{
              background: `${ACCENT}1F`,
              color: ACCENT,
              border: `1px solid ${ACCENT}33`,
            }}
          >
            {FEATURES.length}
          </span>
          <ChevronDown
            size={13}
            className="shrink-0 text-[#64748B] group-hover:text-[#CBD5E1] transition-transform duration-200 ease-[cubic-bezier(0.16,1,0.3,1)]"
            style={{ transform: featOpen ? "rotate(180deg)" : "rotate(0deg)" }}
          />
        </button>

        {/* Submenu — animated slide */}
        <div
          style={{
            display: "grid",
            gridTemplateRows: featOpen ? "1fr" : "0fr",
            transition: "grid-template-rows 260ms cubic-bezier(0.16,1,0.3,1)",
          }}
        >
          <div style={{ overflow: "hidden" }}>
            <div
              className="ml-3 pl-3 pr-1 border-l flex flex-col gap-0.5 py-1"
              style={{ borderColor: "var(--glass-border, rgba(255,255,255,0.09))" }}
            >
              {FEATURES.map(({ id, label, icon: Ic }) => {
                const active = activeView === id;
                return (
                  <button
                    key={id}
                    onClick={() => setView(id)}
                    aria-current={active ? "page" : undefined}
                    className={`group flex items-center gap-2.5 px-3 py-2 rounded-xl w-full text-left text-sm tracking-[0.02em] border border-transparent transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:translate-x-[3px] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117] ${
                      active
                        ? "font-semibold text-white"
                        : "font-medium text-[#94A3B8] hover:bg-[var(--nav-hover-bg)] hover:border-[color:var(--nav-hover-border)] hover:text-[#F8FAFC]"
                    }`}
                    style={{
                      ...accentVars,
                      ...(active
                        ? {
                            background: `linear-gradient(90deg, ${ACCENT}26, ${ACCENT}08)`,
                            borderColor: `${ACCENT}55`,
                          }
                        : {}),
                    }}
                  >
                    <Ic
                      size={14}
                      className={`shrink-0 transition-colors duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] ${
                        active ? "" : "text-[#64748B] group-hover:text-[var(--accent)]"
                      }`}
                      style={active ? { color: ACCENT } : undefined}
                    />
                    <span className="truncate flex-1">{label}</span>
                    {active && (
                      <span
                        aria-hidden="true"
                        className="w-1.5 h-1.5 rounded-full shrink-0"
                        style={{
                          background: ACCENT,
                          boxShadow: `0 0 6px ${ACCENT}66`,
                        }}
                      />
                    )}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        <div
          className="my-2 mx-3 h-px"
          style={{ background: "var(--glass-border, rgba(255,255,255,0.09))" }}
        />
        <NavBtn
          id="about"
          label="About"
          Icon={Info}
          activeView={activeView}
          setView={setView}
          accent={ACCENT}
        />
      </nav>

      {/* Bottom Settings */}
      <div
        className="border-t p-3"
        style={{ borderColor: "var(--glass-border, rgba(255,255,255,0.09))" }}
      >
        <NavBtn
          id="settings"
          label="Settings"
          Icon={Settings}
          activeView={activeView}
          setView={setView}
          accent={ACCENT}
        />
      </div>
    </div>
  );
}

function NavBtn({ id, label, Icon, activeView, setView, accent }) {
  const active = activeView === id;
  const accentVars = {
    "--accent": accent,
    "--nav-hover-bg": `${accent}14`,
    "--nav-hover-border": `${accent}2E`,
    "--tw-ring-color": `${accent}99`,
  };

  return (
    <button
      onClick={() => setView(id)}
      aria-current={active ? "page" : undefined}
      className={`group flex items-center gap-3 px-3 py-2.5 rounded-xl w-full text-left text-sm tracking-[0.025em] border border-transparent transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:translate-x-[3px] active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0D1117] ${
        active
          ? "font-semibold text-white"
          : "font-medium text-[#94A3B8] hover:bg-[var(--nav-hover-bg)] hover:border-[color:var(--nav-hover-border)] hover:text-[#F8FAFC]"
      }`}
      style={{
        ...accentVars,
        ...(active
          ? {
              background: `linear-gradient(90deg, ${accent}26, ${accent}08)`,
              borderColor: `${accent}55`,
            }
          : {}),
      }}
    >
      <Icon
        size={15}
        className={`shrink-0 transition-colors duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] ${
          active ? "" : "text-[#64748B] group-hover:text-[var(--accent)]"
        }`}
        style={active ? { color: accent } : undefined}
      />
      <span className="flex-1 truncate">{label}</span>

      {active && (
        <span
          aria-hidden="true"
          className="w-1.5 h-1.5 rounded-full shrink-0"
          style={{
            background: accent,
            boxShadow: `0 0 8px ${accent}66`,
          }}
        />
      )}
    </button>
  );
}

// ─── Dashboard shell ─────────────────────────────────────────────────────────
function DashboardShell() {
  const { toasts, removeToast, toast } = useToast();
  const [activeView, setActiveView] = useState("dashboard");
  const [mobileSidebar, setMobileSidebar] = useState(false);
  const [fadeKey, setFadeKey] = useState(0);

  const setView = useCallback((v) => {
    setActiveView(v);
    setFadeKey((k) => k + 1);
    setMobileSidebar(false);
  }, []);

  return (
    <div
      className="relative flex h-screen overflow-hidden"
      style={{
        background: "var(--bg-gradient, #0B0E14)",
        fontFamily:
          'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif',
      }}
    >
      <style>{`
        html, body { margin: 0; height: 100%; overflow: hidden; background: #0B0E14; }
        body { background: var(--bg-gradient, #0B0E14); background-attachment: fixed; }
        * { scrollbar-width: thin; scrollbar-color: #2D3748 transparent; box-sizing: border-box; }
        *::-webkit-scrollbar { width: 4px; height: 4px; }
        *::-webkit-scrollbar-thumb { background: #2D3748; border-radius: 4px; }
        @keyframes fadeSlideIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        .view-fade { animation: fadeSlideIn 220ms cubic-bezier(0.16,1,0.3,1) both; }
      `}</style>

      {/* Decorative depth — cheap radial glows, no blur */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          zIndex: 0,
          background:
            "radial-gradient(ellipse at 20% -10%, var(--accent) 0%, transparent 55%)",
          opacity: 0.16,
        }}
      />
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0"
        style={{
          zIndex: 0,
          background:
            "radial-gradient(ellipse at 100% 100%, var(--bg-from, #0B0E14) 0%, transparent 55%)",
          opacity: 0.25,
        }}
      />

      <ToastContainer toasts={toasts} removeToast={removeToast} />

      {/* Mobile sidebar backdrop */}
      {mobileSidebar && (
        <div
          className="fixed inset-0 z-40 lg:hidden"
          style={{
            background: "rgba(0,0,0,0.75)",
            backdropFilter: "blur(4px)",
          }}
          onClick={() => setMobileSidebar(false)}
        />
      )}

      {/* ══ LEFT SIDEBAR ═════════════════════════════════════════ */}
      <aside
        id="app-sidebar"
        className="fixed top-0 left-0 h-full z-50 flex flex-col border-r lg:relative lg:translate-x-0"
        style={{
          width: 272,
          background: "var(--surface-glass-strong, rgba(16,20,30,0.82))",
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
          borderColor: "var(--glass-border, rgba(255,255,255,0.09))",
          transform: mobileSidebar ? "translateX(0)" : "translateX(-100%)",
          transition: "transform 240ms cubic-bezier(0.16,1,0.3,1)",
          flexShrink: 0,
        }}
      >
        <Sidebar activeView={activeView} setView={setView} />
      </aside>

      {/* Desktop sidebar always visible */}
      <style>{`@media (min-width: 1024px) { .sb-fixed { position: relative !important; transform: translateX(0) !important; } }`}</style>

      {/* ══ MAIN COLUMN ══════════════════════════════════════════ */}
      <div className="relative z-10 flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Sticky Top Header */}
        <header
          className="shrink-0 flex items-center gap-3 px-4 sm:px-6 py-3 border-b"
          style={{
            background: "var(--surface-glass, rgba(16,20,30,0.55))",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            borderColor: "var(--glass-border, rgba(255,255,255,0.09))",
            zIndex: 30,
          }}
        >
          {/* Mobile menu */}
          <button
            className="lg:hidden p-2 rounded-xl transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.97] hover:text-[#E2E8F0] shrink-0"
            style={{ color: "#94A3B8" }}
            onClick={() => setMobileSidebar((v) => !v)}
          >
            {mobileSidebar ? <X size={18} /> : <Menu size={18} />}
          </button>

          {/* Breadcrumb */}
          <nav
            aria-label="Breadcrumb"
            className="flex-1 min-w-0 flex items-center gap-1.5 text-sm"
          >
            {activeView !== "dashboard" && (
              <>
                <button
                  type="button"
                  onClick={() => setView("dashboard")}
                  className="shrink-0 rounded-md px-1 -mx-1 font-medium transition-colors duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:text-white focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B0E14]"
                  style={{ color: "#94A3B8" }}
                >
                  Dashboard
                </button>
                <span
                  aria-hidden="true"
                  className="shrink-0"
                  style={{ color: "#64748B" }}
                >
                  ›
                </span>
              </>
            )}
            <span aria-current="page" className="font-bold text-white truncate">
              {VIEW_LABELS[activeView] || "Dashboard"}
            </span>
          </nav>

          <ApiPill />
        </header>

        {/* Right Content Area */}
        <main className="flex-1 overflow-y-auto p-4 sm:p-6 lg:p-8">
          <PairingBanner />
          <div key={fadeKey} className="view-fade">
            <ViewContent view={activeView} toast={toast} />
          </div>
        </main>

        {/* Footer */}
        <footer
          className="shrink-0 px-5 py-2.5 border-t flex items-center justify-between gap-2"
          style={{
            background: "var(--surface-glass, rgba(16,20,30,0.55))",
            borderColor: "var(--glass-border, rgba(255,255,255,0.09))",
          }}
        >
          <span className="text-xs font-mono" style={{ color: "#94A3B8" }}>
            Local dashboard · API 127.0.0.1:8765
          </span>
          <div className="flex items-center gap-3">
            <FooterStatus />
          </div>
        </footer>
      </div>

      {/* Desktop sidebar CSS override — scoped to #app-sidebar only so it can
          never leak onto dialogs/drawers that also use <aside>. */}
      <style>{`
        @media (min-width: 1024px) {
          #app-sidebar { position: sticky !important; transform: translateX(0) !important; align-self: stretch; }
        }
      `}</style>
    </div>
  );
}

// ─── Root Page ────────────────────────────────────────────────────────────────
export default function DashboardPage() {
  return (
    <SessionProvider>
      <DashboardShell />
    </SessionProvider>
  );
}
