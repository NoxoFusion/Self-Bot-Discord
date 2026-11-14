"use client";
import { useEffect, useState } from "react";
import {
  ExternalLink,
  Code2,
  Heart,
  Rocket,
  Layers,
  Star,
  Coffee,
  MessageCircle,
  ShieldCheck,
  Zap,
  Lock,
} from "lucide-react";
import {
  api,
  normalizeCapabilities,
  normalizeStatus,
} from "../../../lib/api";
import { useSessionContext } from "../../../lib/session";

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B0E14]";

const GLASS_SHADOW =
  "inset 0 1px 0 var(--glass-highlight), 0 12px 32px rgba(0,0,0,0.28)";

const LINKS = {
  github: "https://github.com/NoxoFusion",
  discord: "https://discord.gg/rxw8Hwk3qA",
  tiktok: "https://www.tiktok.com/@noxofusion",
  youtube: "https://www.youtube.com/@noxofusion2010",
};

function DiscordLogo({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M20.317 4.37a19.79 19.79 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.74 19.74 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.1 13.1 0 0 1-1.872-.892.077.077 0 0 1-.008-.128c.126-.094.252-.192.372-.291a.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.3 12.3 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.84 19.84 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z" />
    </svg>
  );
}
function TikTokLogo({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M19.59 6.69a4.83 4.83 0 0 1-3.77-4.25V2h-3.45v13.67a2.89 2.89 0 0 1-5.2 1.74 2.89 2.89 0 0 1 2.31-4.64 2.93 2.93 0 0 1 .88.13V9.4a6.84 6.84 0 0 0-1-.05A6.33 6.33 0 0 0 5 20.1a6.34 6.34 0 0 0 10.86-4.43v-7a8.16 8.16 0 0 0 4.77 1.52v-3.4a4.85 4.85 0 0 1-1-.1z" />
    </svg>
  );
}
function YouTubeLogo({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M23.5 6.19a3.02 3.02 0 0 0-2.12-2.14C19.5 3.55 12 3.55 12 3.55s-7.5 0-9.38.5A3.02 3.02 0 0 0 .5 6.19C0 8.08 0 12 0 12s0 3.92.5 5.81a3.02 3.02 0 0 0 2.12 2.14c1.88.5 9.38.5 9.38.5s7.5 0 9.38-.5a3.02 3.02 0 0 0 2.12-2.14C24 15.92 24 12 24 12s0-3.92-.5-5.81zM9.55 15.57V8.43L15.82 12l-6.27 3.57z" />
    </svg>
  );
}
function GitHubLogo({ size = 24 }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="currentColor">
      <path d="M12 .5C5.73.5.5 5.73.5 12a11.5 11.5 0 0 0 7.86 10.92c.58.1.79-.25.79-.56v-2.17c-3.2.7-3.88-1.54-3.88-1.54-.53-1.34-1.29-1.7-1.29-1.7-1.05-.72.08-.71.08-.71 1.16.08 1.77 1.19 1.77 1.19 1.03 1.77 2.7 1.26 3.36.96.1-.75.4-1.26.73-1.55-2.55-.29-5.23-1.28-5.23-5.7 0-1.26.45-2.29 1.19-3.1-.12-.29-.52-1.46.11-3.05 0 0 .97-.31 3.18 1.18a11.1 11.1 0 0 1 5.79 0c2.2-1.49 3.17-1.18 3.17-1.18.63 1.59.23 2.76.11 3.05.74.81 1.19 1.84 1.19 3.1 0 4.43-2.69 5.41-5.25 5.69.41.35.78 1.05.78 2.12v3.14c0 .31.21.67.8.56A11.5 11.5 0 0 0 23.5 12C23.5 5.73 18.27.5 12 .5z" />
    </svg>
  );
}

function SocialCard({ href, logo: Logo, name, handle, color, bg, cta }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className={`group rounded-2xl border p-4 flex items-center gap-4 transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px active:scale-[0.97] relative overflow-hidden ${FOCUS_RING}`}
      style={{
        background: "var(--surface-glass)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        borderColor: "var(--glass-border)",
        boxShadow: GLASS_SHADOW,
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = color;
        e.currentTarget.style.boxShadow = `0 8px 28px ${color}30`;
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "var(--glass-border)";
        e.currentTarget.style.boxShadow = GLASS_SHADOW;
      }}
    >
      <div
        className="absolute inset-0 pointer-events-none"
        style={{
          background: `radial-gradient(circle at 0% 50%, ${color}18 0%, transparent 60%)`,
        }}
      />
      <div
        className="relative w-14 h-14 rounded-2xl flex items-center justify-center shrink-0"
        style={{
          background: bg,
          color: "#fff",
          boxShadow: `0 6px 18px ${color}40`,
        }}
      >
        <Logo size={28} />
      </div>
      <div className="relative flex-1 min-w-0">
        <div className="text-base font-bold text-white">{name}</div>
        <div
          className="text-xs font-mono truncate"
          style={{ color: "#94A3B8" }}
        >
          {handle}
        </div>
        <div
          className="text-xs font-bold mt-1.5 inline-flex items-center gap-1 px-2 py-0.5 rounded-full"
          style={{ background: `${color}20`, color }}
        >
          {cta} <ExternalLink size={10} />
        </div>
      </div>
    </a>
  );
}

const STACK = [
  { label: "Python", color: "#3776AB" },
  { label: "discord.py-self", color: "#5865F2" },
  { label: "aiohttp", color: "#23A55A" },
  { label: "React", color: "#58B8E8" },
  { label: "Vite", color: "#A855F7" },
  { label: "Tailwind", color: "#38BDF8" },
  { label: "WebSocket", color: "#F5B642" },
];

const HIGHLIGHTS = [
  {
    icon: ShieldCheck,
    title: "Anti-Flag Telemetry",
    text: "Real-client fingerprint, X-Super-Properties and jittered telemetry keep traffic consistent.",
    color: "#23A55A",
  },
  {
    icon: Zap,
    title: "Async Multi-Engine",
    text: "Threaded voice connectors, shared HTTP sessions and automatic 429 retry handling.",
    color: "#F5B642",
  },
  {
    icon: Lock,
    title: "Zero-Leak Control Plane",
    text: "Loopback-only dashboard API with pairing, CSRF and no token exposure to the browser.",
    color: "#58B8E8",
  },
];

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
  return { label: "Unknown", color: "#94A3B8" };
}

export default function AboutView() {
  const session = useSessionContext();
  const [status, setStatus] = useState(null);
  const [capabilities, setCapabilities] = useState([]);

  useEffect(() => {
    if (!session.authenticated) {
      setStatus(null);
      setCapabilities([]);
      return;
    }

    let cancelled = false;
    Promise.allSettled([api.getStatus(), api.getCapabilities()]).then(
      ([statusResult, capResult]) => {
        if (cancelled) return;
        if (statusResult.status === "fulfilled") {
          setStatus(normalizeStatus(statusResult.value));
        }
        if (capResult.status === "fulfilled") {
          setCapabilities(normalizeCapabilities(capResult.value));
        }
      },
    );

    return () => {
      cancelled = true;
    };
  }, [session.authenticated]);

  const bot = status?.bot || {};
  const stateMeta = botStateMeta(bot.state);
  const apiVersion = status?.apiVersion ?? "—";
  const availableCount = capabilities.filter(
    (cap) => cap.status === "available",
  ).length;

  const stats = [
    {
      icon: Layers,
      label: "Features",
      value: capabilities.length ? String(capabilities.length) : "—",
      color: "#5865F2",
    },
    {
      icon: Code2,
      label: "Available",
      value: capabilities.length ? String(availableCount) : "—",
      color: "#23A55A",
    },
    {
      icon: Rocket,
      label: "API Version",
      value: apiVersion,
      color: "#F5B642",
    },
    {
      icon: Star,
      label: "Bot State",
      value: status ? stateMeta.label : "—",
      color: stateMeta.color,
    },
  ];

  return (
    <div className="flex flex-col gap-4">
      {/* Hero */}
      <div
        className="rounded-2xl border overflow-hidden"
        style={{
          background: "var(--surface-glass)",
          backdropFilter: "blur(16px)",
          WebkitBackdropFilter: "blur(16px)",
          borderColor: "var(--glass-border)",
          boxShadow: GLASS_SHADOW,
        }}
      >
        <div className="px-5 sm:px-6 pt-5 pb-5 flex flex-col sm:flex-row sm:items-center gap-4">
          <div
            className="p-[3px] rounded-full shrink-0 w-fit"
            style={{
              background: "linear-gradient(135deg,#5865F2,#23A55A)",
              boxShadow: "0 0 30px #5865F260",
            }}
          >
            <img
              src="https://github.com/NoxoFusion.png"
              alt="Noxo Fusion"
              className="w-24 h-24 rounded-full border-4"
              style={{ borderColor: "var(--surface-solid)" }}
              onError={(e) => {
                if (!e.currentTarget.dataset.fallback) {
                  e.currentTarget.dataset.fallback = "1";
                  e.currentTarget.src =
                    "https://avatars.githubusercontent.com/u/226039593?v=4";
                }
              }}
            />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-2xl sm:text-3xl font-extrabold text-white tracking-tight">
              Noxo Fusion
            </div>
            <div
              className="text-sm font-semibold mt-1"
              style={{ color: "#8B9CF8" }}
            >
              Automation Specialist &amp; Lead Developer
            </div>
            <p
              className="text-sm mt-2 max-w-2xl leading-relaxed"
              style={{ color: "#94A3B8" }}
            >
              Building high-performance Discord automation, selfbot tooling and
              a local-first control plane.
            </p>
            <div className="flex flex-wrap items-center gap-2 mt-2.5">
              <span
                className="text-xs font-semibold px-2.5 py-1 rounded-full"
                style={{ background: "var(--surface-inset)", color: "#94A3B8" }}
              >
                📍 VietNam
              </span>
              <span
                className="text-xs font-bold px-2.5 py-1 rounded-full flex items-center gap-1.5"
                style={{
                  background: `${stateMeta.color}20`,
                  color: stateMeta.color,
                }}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ background: stateMeta.color }}
                />{" "}
                {status
                  ? stateMeta.label
                  : session.authenticated
                    ? "Loading…"
                    : "Not connected"}
              </span>
              <span
                className="text-xs font-mono px-2.5 py-1 rounded-full"
                style={{ background: "var(--surface-inset)", color: "#94A3B8" }}
              >
                Local dashboard · API v{apiVersion}
              </span>
            </div>
          </div>
        </div>
        <div
          className="grid grid-cols-2 sm:grid-cols-4 border-t"
          style={{ borderColor: "var(--glass-border)" }}
        >
          {stats.map(({ icon: Ic, label, value, color }, i) => (
            <div
              key={label}
              className="flex items-center gap-3 px-5 py-4"
              style={{
                borderLeft: i ? "1px solid var(--glass-border)" : "none",
              }}
            >
              <Ic size={18} style={{ color }} />
              <div>
                <div className="text-lg font-extrabold text-white leading-none">
                  {value}
                </div>
                <div className="text-xs mt-1" style={{ color: "#94A3B8" }}>
                  {label}
                </div>
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Connect & Support */}
      <div className="flex items-center gap-2 mt-1">
        <MessageCircle size={15} style={{ color: "#5865F2" }} />
        <span className="text-base font-bold text-white">Connect &amp; Support</span>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
        <SocialCard
          href={LINKS.github}
          logo={GitHubLogo}
          name="GitHub"
          handle="@NoxoFusion"
          color="#E6EDF3"
          bg="#181717"
          cta="Follow profile"
        />
        <SocialCard
          href={LINKS.discord}
          logo={DiscordLogo}
          name="Discord"
          handle="discord.gg/rxw8Hwk3qA"
          color="#5865F2"
          bg="#5865F2"
          cta="Join server"
        />
        <SocialCard
          href={LINKS.youtube}
          logo={YouTubeLogo}
          name="YouTube"
          handle="@noxofusion2010"
          color="#FF0033"
          bg="#FF0033"
          cta="Subscribe"
        />
        <SocialCard
          href={LINKS.tiktok}
          logo={TikTokLogo}
          name="TikTok"
          handle="@noxofusion"
          color="#FE2C55"
          bg="linear-gradient(135deg,#25F4EE,#000 50%,#FE2C55)"
          cta="Follow"
        />
      </div>

      {/* Core highlights */}
      <div className="flex items-center gap-2 mt-1">
        <Rocket size={15} style={{ color: "#F5B642" }} />
        <span className="text-base font-bold text-white">Core Highlights</span>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {HIGHLIGHTS.map(({ icon: Icon, title, text, color }) => (
          <div
            key={title}
            className="rounded-2xl border p-4 flex flex-col gap-2.5 relative overflow-hidden"
            style={{
              background: "var(--surface-glass)",
              backdropFilter: "blur(16px)",
              WebkitBackdropFilter: "blur(16px)",
              borderColor: "var(--glass-border)",
              boxShadow: GLASS_SHADOW,
            }}
          >
            <div
              className="absolute inset-0 pointer-events-none"
              style={{
                background: `radial-gradient(circle at 0% 0%, ${color}14 0%, transparent 60%)`,
              }}
            />
            <div
              className="relative w-9 h-9 rounded-xl flex items-center justify-center"
              style={{ background: `${color}18`, border: `1px solid ${color}35` }}
            >
              <Icon size={18} style={{ color }} />
            </div>
            <div className="relative text-base font-bold text-white">
              {title}
            </div>
            <div
              className="relative text-sm leading-relaxed"
              style={{ color: "#94A3B8" }}
            >
              {text}
            </div>
          </div>
        ))}
      </div>

      {/* Bottom: Built With | Thanks */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
        <div
          className="rounded-2xl border p-4 flex flex-col gap-3"
          style={{
            background: "var(--surface-glass)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            borderColor: "var(--glass-border)",
            boxShadow: GLASS_SHADOW,
          }}
        >
          <div className="flex items-center gap-2">
            <Code2 size={15} style={{ color: "#58B8E8" }} />
            <span className="text-base font-bold text-white">Built With</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {STACK.map(({ label, color }) => (
              <span
                key={label}
                className="text-xs font-semibold px-2.5 py-1 rounded-lg flex items-center gap-1.5"
                style={{ background: `${color}18`, color }}
              >
                <span
                  className="w-1.5 h-1.5 rounded-full"
                  style={{ background: color }}
                />{" "}
                {label}
              </span>
            ))}
          </div>
        </div>
        <div
          className="rounded-2xl border p-4 flex items-center gap-4 relative overflow-hidden"
          style={{
            background: "var(--surface-glass)",
            backdropFilter: "blur(16px)",
            WebkitBackdropFilter: "blur(16px)",
            borderColor: "#F23F4330",
            boxShadow: GLASS_SHADOW,
          }}
        >
          <div
            className="absolute inset-0 pointer-events-none"
            style={{
              background:
                "radial-gradient(circle at 0% 50%, #F23F4318 0%, transparent 60%)",
            }}
          />
          <div
            className="relative w-12 h-12 rounded-full flex items-center justify-center shrink-0"
            style={{ background: "#F23F4320" }}
          >
            <Heart size={22} style={{ color: "#F23F43" }} fill="#F23F43" />
          </div>
          <div className="relative flex-1 min-w-0">
            <div className="text-base font-bold text-white">
              Thanks for using!
            </div>
            <div
              className="flex items-center gap-1.5 text-xs mt-0.5"
              style={{ color: "#94A3B8" }}
            >
              <Coffee size={12} /> Support = follow &amp; share
            </div>
            <a
              href={LINKS.github}
              target="_blank"
              rel="noreferrer"
              className={`relative inline-flex items-center gap-1 text-xs font-semibold mt-1.5 rounded transition-colors duration-200 active:scale-[0.97] ${FOCUS_RING}`}
              style={{ color: "#8B9CF8" }}
            >
              github.com/NoxoFusion <ExternalLink size={10} />
            </a>
          </div>
        </div>
      </div>
    </div>
  );
}
