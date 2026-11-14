"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  BadgeCheck,
  Calendar,
  Check,
  CheckCircle2,
  Clock,
  Copy,
  Dices,
  KeyRound,
  Loader2,
  LogOut,
  Palette,
  RefreshCw,
  Save,
  Sparkles,
  Terminal,
  UserRound,
  Users,
  X,
} from "lucide-react";
import { api, normalizeStatus } from "../../../lib/api";
import { createPortal } from "react-dom";
import { useSessionContext } from "../../../lib/session";
import {
  isValidHex,
  randomizeTheme,
  setCustomTheme,
  setTheme,
  THEME_PRESETS,
  useAccent,
  useTheme,
} from "../../../lib/theme";
import { Panel } from "../kit";
import Modal from "../Modal";

const SURFACE = "var(--surface-glass)";
const INSET = "var(--surface-inset)";
const BORDER = "var(--glass-border)";
const SOLID = "var(--surface-solid)";
const MUTED = "#94A3B8";
const FAINT = "#94A3B8";
const ONLINE = "#23A55A";
const OFFLINE = "#94A3B8";
const DANGER = "#F23F43";
const WARNING = "#F5B642";
const NITRO = "#F47FFF";

const RELOAD_POLL_ATTEMPTS = 8;
const RELOAD_POLL_INTERVAL_MS = 1500;

const FOCUS_RING =
  "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-white/50 focus-visible:ring-offset-2 focus-visible:ring-offset-[#0B0E14]";

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function channelLuminance(value) {
  const channel = value / 255;
  return channel <= 0.03928
    ? channel / 12.92
    : Math.pow((channel + 0.055) / 1.055, 2.4);
}

function relativeLuminance(hex) {
  const value = parseInt(hex.slice(1), 16);
  return (
    0.2126 * channelLuminance((value >> 16) & 255) +
    0.7152 * channelLuminance((value >> 8) & 255) +
    0.0722 * channelLuminance(value & 255)
  );
}

function readableOn(hex) {
  if (!isValidHex(hex)) return "#fff";
  const luminance = relativeLuminance(hex);
  const whiteContrast = 1.05 / (luminance + 0.05);
  const darkContrast = (luminance + 0.05) / (0.0036 + 0.05);
  return whiteContrast >= darkContrast ? "#fff" : "#0B0E14";
}

function lightenHex(hex, amount = 0.35) {
  if (!isValidHex(hex)) return "#E2E8F0";
  const value = parseInt(hex.slice(1), 16);
  const channels = [
    (value >> 16) & 255,
    (value >> 8) & 255,
    value & 255,
  ].map((channel) =>
    Math.round(channel + (255 - channel) * amount)
      .toString(16)
      .padStart(2, "0"),
  );
  return `#${channels.join("")}`;
}

function darkenHex(hex, amount = 0.16) {
  if (!isValidHex(hex)) return "#5865F2";
  const value = parseInt(hex.slice(1), 16);
  const channels = [
    (value >> 16) & 255,
    (value >> 8) & 255,
    value & 255,
  ].map((channel) =>
    Math.round(channel * (1 - amount))
      .toString(16)
      .padStart(2, "0"),
  );
  return `#${channels.join("")}`;
}

function buttonSurface(hex) {
  if (!isValidHex(hex)) return { background: "#5865F2", color: "#fff" };
  const color = readableOn(hex);
  if (color === "#fff") {
    return { background: darkenHex(hex), color };
  }
  return { background: hex, color };
}

function accentTextColor(hex) {
  if (!isValidHex(hex)) return "#E2E8F0";
  let color = hex;
  for (let step = 0; step < 12; step += 1) {
    const luminance = relativeLuminance(color);
    const contrast = (luminance + 0.05) / (0.0036 + 0.05);
    if (contrast >= 4.5) return color;
    color = lightenHex(color, 0.2);
  }
  return "#E2E8F0";
}

function toDate(value) {
  if (value == null || value === "") return null;
  let date;
  if (typeof value === "number" || /^\d+$/.test(String(value))) {
    const numeric = Number(value);
    date = new Date(numeric < 1e12 ? numeric * 1000 : numeric);
  } else {
    date = new Date(value);
  }
  return Number.isNaN(date.getTime()) ? null : date;
}

function isBotOnline(state) {
  const key = String(state || "")
    .toLowerCase()
    .replace(/\s+/g, "_");
  return key === "online" || key === "connected" || key === "ready";
}

function reloadAt(lastReload) {
  if (lastReload == null) return null;
  if (typeof lastReload === "object") return lastReload.at ?? null;
  return lastReload;
}

function reloadDetail(lastReload) {
  if (lastReload && typeof lastReload === "object") {
    return lastReload.detail ?? null;
  }
  return null;
}

function reloadOk(lastReload) {
  if (lastReload && typeof lastReload === "object") {
    return lastReload.ok !== false;
  }
  return true;
}

function formatDate(value) {
  const date = toDate(value);
  if (!date) return "—";
  return date.toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

function formatDateTime(value) {
  const date = toDate(value);
  if (!date) return "—";
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function CopyButton({ value, label = "Copy", onError }) {
  const [copied, setCopied] = useState(false);
  const resetTimerRef = useRef(null);

  useEffect(
    () => () => {
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
        resetTimerRef.current = null;
      }
    },
    [],
  );

  const copy = async () => {
    try {
      if (!navigator?.clipboard?.writeText) throw new Error("no_clipboard");
      await navigator.clipboard.writeText(value);
      setCopied(true);
      if (resetTimerRef.current) {
        window.clearTimeout(resetTimerRef.current);
      }
      resetTimerRef.current = window.setTimeout(() => {
        resetTimerRef.current = null;
        setCopied(false);
      }, 1600);
    } catch {
      onError?.();
    }
  };

  return (
    <button
      type="button"
      onClick={copy}
      aria-label={label}
      title={label}
      className={`shrink-0 p-1 rounded-md transition-colors duration-200 active:scale-[0.97] ${FOCUS_RING}`}
      style={{ color: copied ? ONLINE : FAINT }}
      onMouseEnter={(e) => {
        e.currentTarget.style.color = "#E2E8F0";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.color = copied ? ONLINE : FAINT;
      }}
    >
      {copied ? <Check size={12} /> : <Copy size={12} />}
    </button>
  );
}

function Chip({ icon: Icon, label, color }) {
  return (
    <span
      className="inline-flex items-center gap-1.5 text-xs font-semibold px-2 py-1 rounded-full"
      style={{
        background: `${color}18`,
        color,
        border: `1px solid ${color}35`,
      }}
    >
      {Icon && <Icon size={12} />}
      {label}
    </span>
  );
}

function HeroProfile({
  profile,
  status,
  accent,
  authenticated,
  loading,
  unpairing,
  onUnpair,
  onCopyError,
}) {
  const online = isBotOnline(status?.bot?.state);
  const statusColor = online ? ONLINE : OFFLINE;
  const accentText = accentTextColor(accent);
  const displayName =
    profile?.display_name ||
    profile?.username ||
    (loading ? "Loading profile…" : "Profile unavailable");
  const username = profile?.username || null;
  const avatarUrl = profile?.avatar_url || null;
  const bannerUrl = profile?.banner_url || null;
  const bannerColor = isValidHex(profile?.accent_color)
    ? profile.accent_color
    : accent;
  const guildCount = status?.bot?.guildCount;
  const badges = Array.isArray(profile?.badges) ? profile.badges : [];
  const premiumType = Number(profile?.premium_type) || 0;
  const hasBadges = premiumType > 0 || badges.length > 0;

  return (
    <section
      className="rounded-2xl border overflow-hidden"
      style={{
        background: SURFACE,
        borderColor: BORDER,
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
      }}
      aria-label="Bot profile"
      aria-busy={loading}
    >
      <div
        className="relative"
        style={{
          height: 112,
          background: `linear-gradient(135deg, ${bannerColor} 0%, ${bannerColor}99 42%, ${SURFACE} 100%)`,
        }}
      >
        {bannerUrl && (
          <img
            src={bannerUrl}
            alt=""
            aria-hidden="true"
            className="absolute inset-0 w-full h-full object-cover"
            onError={(e) => {
              e.currentTarget.style.display = "none";
            }}
          />
        )}
        <div
          className="absolute inset-0 pointer-events-none"
          style={{
            background:
              "linear-gradient(to top, var(--surface-glass) 0%, rgba(16,20,30,0.28) 38%, transparent 100%)",
          }}
        />

        {authenticated && (
          <button
            type="button"
            onClick={onUnpair}
            disabled={unpairing}
            aria-label="Unpair session"
            className={`absolute top-3 right-3 z-10 inline-flex items-center gap-1.5 text-xs font-bold px-3 py-1.5 rounded-lg border transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.97] hover:brightness-110 disabled:hover:brightness-100 ${FOCUS_RING}`}
            style={{
              background: "rgba(11,14,20,0.78)",
              borderColor: `${DANGER}55`,
              color: unpairing ? FAINT : "#FCA5A5",
              cursor: unpairing ? "wait" : "pointer",
              backdropFilter: "blur(8px)",
              WebkitBackdropFilter: "blur(8px)",
            }}
          >
            <LogOut size={12} />
            {unpairing ? "Unpairing…" : "Unpair session"}
          </button>
        )}

        <div className="absolute left-4 sm:left-6 -bottom-10">
          <div className="relative">
            <div
              className="w-20 h-20 rounded-full overflow-hidden flex items-center justify-center"
              style={{
                background: INSET,
                boxShadow: `0 0 0 4px ${SOLID}, 0 8px 24px rgba(0,0,0,0.38)`,
              }}
            >
              <div className="relative w-full h-full">
                <div className="absolute inset-0 flex items-center justify-center">
                  <UserRound size={30} style={{ color: FAINT }} />
                </div>
                {avatarUrl && (
                  <img
                    src={avatarUrl}
                    alt={displayName ? `${displayName} avatar` : "Bot avatar"}
                    className="relative w-full h-full object-cover"
                    onError={(e) => {
                      e.currentTarget.style.display = "none";
                    }}
                  />
                )}
              </div>
            </div>
            <span
              role="img"
              aria-label={online ? "Bot online" : "Bot offline"}
              title={online ? "Bot online" : "Bot offline"}
              className="absolute bottom-1 right-1 w-4 h-4 rounded-full border-2"
              style={{
                background: statusColor,
                borderColor: SOLID,
                boxShadow: online ? `0 0 8px ${ONLINE}70` : "none",
              }}
            />
          </div>
        </div>
      </div>

      <div className="px-4 sm:px-6 pt-12 pb-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-xl sm:text-2xl font-extrabold text-white leading-tight truncate">
              {displayName}
            </h1>
            {username && (
              <div
                className="text-sm font-mono mt-0.5 truncate"
                style={{ color: MUTED }}
              >
                @{username}
              </div>
            )}
          </div>
          <span
            className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full shrink-0"
            style={{
              background: `${statusColor}18`,
              color: statusColor,
              border: `1px solid ${statusColor}35`,
            }}
          >
            <span
              className="w-1.5 h-1.5 rounded-full"
              style={{ background: statusColor }}
            />
            {online ? "Bot online" : "Bot offline"}
          </span>
        </div>

        {profile ? (
          <>
            <div
              className="mt-4 flex flex-col sm:flex-row sm:items-stretch gap-3 sm:gap-0 rounded-xl px-4 py-3"
              style={{ background: INSET }}
            >
              <div className="min-w-0 flex-1">
                <div
                  className="text-xs font-semibold"
                  style={{ color: MUTED }}
                >
                  User ID
                </div>
                <div className="flex items-center gap-1.5 min-w-0 mt-1">
                  <span
                    className="text-sm font-mono font-semibold truncate"
                    style={{ color: "#E2E8F0" }}
                    title={profile.user_id || "—"}
                  >
                    {profile.user_id || "—"}
                  </span>
                  {profile.user_id && (
                    <CopyButton
                      value={profile.user_id}
                      label="Copy user ID"
                      onError={onCopyError}
                    />
                  )}
                </div>
              </div>

              <div
                className="hidden sm:block w-px mx-4 self-stretch"
                style={{ background: BORDER }}
              />

              <div className="min-w-0 flex-1">
                <div
                  className="text-xs font-semibold"
                  style={{ color: MUTED }}
                >
                  Created
                </div>
                <div
                  className="flex items-center gap-1.5 text-sm font-semibold mt-1"
                  style={{ color: "#E2E8F0" }}
                >
                  <Calendar size={12} style={{ color: accentText }} />
                  {formatDate(profile.created_at)}
                </div>
              </div>

              <div
                className="hidden sm:block w-px mx-4 self-stretch"
                style={{ background: BORDER }}
              />

              <div className="min-w-0 flex-1">
                <div
                  className="text-xs font-semibold"
                  style={{ color: MUTED }}
                >
                  Guilds
                </div>
                <div
                  className="flex items-center gap-1.5 text-sm font-semibold mt-1"
                  style={{ color: "#E2E8F0" }}
                >
                  <Users size={12} style={{ color: accentText }} />
                  {guildCount != null ? guildCount : "—"}
                </div>
              </div>
            </div>

            {hasBadges && (
              <div className="flex flex-wrap items-center gap-1.5 mt-3">
                {premiumType > 0 && (
                  <Chip icon={Sparkles} label="Nitro" color={NITRO} />
                )}
                {badges.map((badge) => (
                  <Chip
                    key={badge.id || badge.label}
                    icon={BadgeCheck}
                    label={badge.label || badge.id}
                    color={accentText}
                  />
                ))}
              </div>
            )}
          </>
        ) : (
          <div
            className="mt-4 flex items-start gap-2.5 rounded-xl px-4 py-3"
            style={{ background: `${WARNING}0D` }}
          >
            <AlertTriangle
              size={15}
              className="mt-0.5 shrink-0"
              style={{ color: WARNING }}
            />
            <div className="text-sm leading-relaxed" style={{ color: MUTED }}>
              <span className="font-bold" style={{ color: WARNING }}>
                {loading ? "Loading profile…" : "Profile unavailable"}
              </span>
              {!loading && (
                <>
                  {" "}
                  — check the bot token in{" "}
                  <code className="font-mono" style={{ color: "#E2E8F0" }}>
                    config.json
                  </code>
                  .
                </>
              )}
            </div>
          </div>
        )}
      </div>
    </section>
  );
}

function PrefixCard({
  prefix,
  savedPrefix,
  onPrefixChange,
  onSave,
  saving,
  error,
  settingsError,
  onRetry,
  disabled,
  accent,
}) {
  const accentText = accentTextColor(accent);
  const saveSurface = buttonSurface(accent);
  const cleaned = prefix.trim();
  const valid =
    cleaned.length > 0 && cleaned.length <= 5 && !/\s/.test(cleaned);
  const changed = cleaned !== savedPrefix;
  const canSave = valid && changed && !saving && !disabled;
  const showInvalid = prefix.length > 0 && !valid;
  const preview = cleaned
    ? `${cleaned}help · ${cleaned}afk · ${cleaned}join`
    : null;

  return (
    <Panel
      icon={Terminal}
      title="Command prefix"
      accent={accent}
      action={
        <span
          className="text-xs font-mono font-bold px-2 py-1 rounded-lg"
          style={{
            background: `${accent}14`,
            color: accentText,
            border: `1px solid ${accent}35`,
          }}
          title="Current saved prefix"
        >
          {savedPrefix || "—"}
        </span>
      }
    >
      <label
        htmlFor="command-prefix"
        className="text-xs font-semibold"
        style={{ color: MUTED }}
      >
        Prefix
      </label>

      <div className="flex items-stretch gap-2">
        <div className="relative flex-1 min-w-0">
          <Terminal
            size={14}
            className="absolute left-3 top-1/2 -translate-y-1/2 pointer-events-none"
            style={{ color: FAINT }}
          />
          <input
            id="command-prefix"
            aria-label="Command prefix"
            aria-invalid={showInvalid}
            type="text"
            value={prefix}
            maxLength={5}
            autoComplete="off"
            spellCheck={false}
            disabled={disabled || saving}
            onChange={(e) => onPrefixChange(e.target.value.slice(0, 5))}
            onBlur={() => onPrefixChange(prefix.trim())}
            placeholder="!"
            className={`w-full text-sm font-mono rounded-xl border pl-9 pr-3 py-2.5 transition-all placeholder-[#64748B] ${FOCUS_RING}`}
            style={{
              background: INSET,
              borderColor: error || showInvalid ? DANGER : BORDER,
              color: "#E2E8F0",
              cursor: disabled || saving ? "not-allowed" : "text",
              opacity: disabled ? 0.55 : 1,
            }}
          />
        </div>

        <button
          type="button"
          onClick={onSave}
          disabled={!canSave}
          aria-label="Save prefix"
          className={`inline-flex items-center justify-center gap-1.5 text-xs font-bold px-4 rounded-xl transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.97] shrink-0 hover:brightness-110 disabled:hover:brightness-100 ${FOCUS_RING}`}
          style={{
            background: canSave ? saveSurface.background : "#2D3748",
            color: canSave ? saveSurface.color : FAINT,
            cursor: canSave ? "pointer" : "not-allowed",
            boxShadow: canSave
              ? `0 4px 14px ${saveSurface.background}35`
              : "none",
          }}
        >
          {saving ? (
            <Loader2 size={14} className="animate-spin" />
          ) : (
            <Save size={14} />
          )}
          {saving ? "Saving…" : "Save"}
        </button>
      </div>

      <div
        className="text-xs font-mono min-h-[16px]"
        style={{ color: preview ? MUTED : FAINT }}
        aria-live="polite"
      >
        {preview ? (
          <>
            <span style={{ color: accentText }}>{cleaned}help</span>
            {" · "}
            <span style={{ color: accentText }}>{cleaned}afk</span>
            {" · "}
            <span style={{ color: accentText }}>{cleaned}join</span>
          </>
        ) : (
          "Enter a prefix to preview commands."
        )}
      </div>

      <div className="text-xs" style={{ color: FAINT }}>
        1–5 characters · no spaces · applied within 2 seconds
      </div>

      {error && (
        <div
          role="alert"
          className="flex items-start gap-2 text-sm leading-relaxed rounded-lg px-3 py-2"
          style={{ background: `${DANGER}0D`, color: "#FCA5A5" }}
        >
          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {settingsError && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-2 text-sm leading-relaxed rounded-lg px-3 py-2"
          style={{ background: `${DANGER}0D`, color: "#FCA5A5" }}
        >
          <AlertTriangle size={13} className="shrink-0" />
          <span className="flex-1">Could not load settings from the local API.</span>
          <button
            type="button"
            onClick={onRetry}
            className={`text-xs font-bold px-2 py-1 rounded-md transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.97] hover:brightness-110 ${FOCUS_RING}`}
            style={{ background: `${DANGER}18`, color: "#FCA5A5" }}
          >
            Retry
          </button>
        </div>
      )}
    </Panel>
  );
}

function ReloadCard({ status, busy, result, onReload, disabled }) {
  const lastAt = reloadAt(status?.lastReload);
  const lastDetail = reloadDetail(status?.lastReload);

  const resultMeta =
    result?.ok === true
      ? { color: ONLINE, Icon: CheckCircle2 }
      : result?.ok === false
        ? { color: DANGER, Icon: AlertTriangle }
        : { color: MUTED, Icon: Clock };
  const ResultIcon = resultMeta.Icon;

  return (
    <Panel
      icon={RefreshCw}
      title="System reload"
      accent={WARNING}
      action={
        lastAt ? (
          <span
            className="text-xs font-mono"
            style={{ color: MUTED }}
            title={lastDetail || "Last reload"}
          >
            {formatDateTime(lastAt)}
          </span>
        ) : null
      }
    >
      <p className="text-sm leading-relaxed" style={{ color: MUTED }}>
        Reload config and cogs without restarting the backend. Use this after
        editing files outside the dashboard.
      </p>

      <button
        type="button"
        onClick={onReload}
        disabled={disabled || busy}
        aria-label="Reload config and cogs"
        className={`w-full inline-flex items-center justify-center gap-2 text-sm font-bold px-4 py-3 rounded-xl transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] active:scale-[0.97] hover:brightness-110 disabled:hover:brightness-100 ${FOCUS_RING}`}
        style={{
          background: disabled || busy ? "#2D3748" : WARNING,
          color: disabled || busy ? FAINT : "#0B0E14",
          cursor: disabled || busy ? "not-allowed" : "pointer",
          boxShadow:
            disabled || busy ? "none" : `0 4px 16px ${WARNING}35`,
        }}
      >
        {busy ? (
          <Loader2 size={16} className="animate-spin" />
        ) : (
          <RefreshCw size={16} />
        )}
        {busy ? "Waiting for the bot…" : "Reload config & cogs"}
      </button>

      {busy && (
        <div className="text-xs font-mono" style={{ color: FAINT }}>
          Polling status every 1.5s · up to 8 attempts
        </div>
      )}

      {result && (
        <div
          role="status"
          aria-live="polite"
          className="flex items-start gap-2 text-sm leading-relaxed rounded-lg px-3 py-2"
          style={{
            background: `${resultMeta.color}0D`,
            color: resultMeta.color,
          }}
        >
          <ResultIcon size={13} className="mt-0.5 shrink-0" />
          <span className="leading-relaxed">{result.detail}</span>
        </div>
      )}

      {!result && !busy && (
        <div className="text-xs" style={{ color: FAINT }}>
          The button asks the bot to reload; it does not restart the backend.
        </div>
      )}
    </Panel>
  );
}

function ColorField({ label, value, onChange, fallback, ariaLabel }) {
  const valid = isValidHex(value);
  return (
    <div className="flex flex-col gap-1.5 min-w-0">
      <span className="text-xs font-semibold" style={{ color: MUTED }}>
        {label}
      </span>
      <div className="flex items-center gap-2">
        <input
          type="color"
          value={valid ? value : fallback}
          onChange={(e) => onChange(e.target.value)}
          aria-label={`${label} picker`}
          className={`h-9 w-10 shrink-0 rounded-lg border p-0.5 cursor-pointer ${FOCUS_RING}`}
          style={{ background: INSET, borderColor: valid ? BORDER : DANGER }}
        />
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value.slice(0, 7))}
          maxLength={7}
          spellCheck={false}
          autoComplete="off"
          aria-label={ariaLabel}
          aria-invalid={!valid}
          placeholder="#5865F2"
          className={`w-full min-w-0 text-sm font-mono rounded-lg border px-2.5 py-2 transition-all placeholder-[#64748B] ${FOCUS_RING}`}
          style={{
            background: INSET,
            borderColor: valid ? BORDER : DANGER,
            color: "#E2E8F0",
          }}
        />
      </div>
    </div>
  );
}

function ThemeDrawer({ open, onClose, toast }) {
  const { themeId, from, to, accent, angle } = useTheme();
  const [customFrom, setCustomFrom] = useState(from);
  const [customTo, setCustomTo] = useState(to);
  const [customAccent, setCustomAccent] = useState(accent);
  const [customAngle, setCustomAngle] = useState(angle);

  useEffect(() => {
    setCustomFrom(from);
    setCustomTo(to);
    setCustomAccent(accent);
    setCustomAngle(angle);
  }, [from, to, accent, angle]);

  const accentText = accentTextColor(accent);
  const fromValid = isValidHex(customFrom);
  const toValid = isValidHex(customTo);
  const accentValid = isValidHex(customAccent);
  const hexValid = fromValid && toValid && accentValid;

  const previewFrom = fromValid ? customFrom : from;
  const previewTo = toValid ? customTo : to;
  const previewAccent = accentValid ? customAccent : accent;
  const previewAngle = Number.isFinite(customAngle) ? customAngle : angle;
  const activePreset = THEME_PRESETS.find((preset) => preset.id === themeId);

  const applyCustom = (overrides = {}) => {
    const nextFrom = overrides.from ?? customFrom;
    const nextTo = overrides.to ?? customTo;
    const nextAccent = overrides.accent ?? customAccent;
    const nextAngle = overrides.angle ?? customAngle;
    if (
      !isValidHex(nextFrom) ||
      !isValidHex(nextTo) ||
      !isValidHex(nextAccent)
    ) {
      return;
    }
    setCustomTheme({
      from: nextFrom,
      to: nextTo,
      accent: nextAccent,
      angle: nextAngle,
    });
  };

  const changeCustomFrom = (value) => {
    setCustomFrom(value);
    applyCustom({ from: value });
  };
  const changeCustomTo = (value) => {
    setCustomTo(value);
    applyCustom({ to: value });
  };
  const changeCustomAccent = (value) => {
    setCustomAccent(value);
    applyCustom({ accent: value });
  };
  const changeCustomAngle = (value) => {
    setCustomAngle(value);
    applyCustom({ angle: value });
  };

  const handleRandomize = () => {
    const theme = randomizeTheme();
    toast?.success(
      `Random gradient applied (${theme.from} → ${theme.to})`,
      "Theme",
    );
  };

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [open, onClose]);

  if (typeof document === "undefined") return null;

  return createPortal(
    <div
      className={`fixed inset-0 z-[9999] ${open ? "" : "pointer-events-none"}`}
      aria-hidden={!open}
    >
      <div
        className="absolute inset-0 transition-opacity duration-200"
        style={{
          background: "rgba(0,0,0,0.55)",
          backdropFilter: "blur(4px)",
          WebkitBackdropFilter: "blur(4px)",
          opacity: open ? 1 : 0,
        }}
        onClick={onClose}
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Theme studio"
        className="absolute right-0 top-0 h-full w-full max-w-md overflow-y-auto border-l p-4 flex flex-col gap-4"
        style={{
          background: "var(--surface-glass-strong)",
          borderColor: "var(--glass-border)",
          backdropFilter: "blur(24px)",
          WebkitBackdropFilter: "blur(24px)",
          transform: open ? "translateX(0)" : "translateX(100%)",
          visibility: open ? "visible" : "hidden",
          pointerEvents: open ? "auto" : "none",
          transition: `transform 260ms cubic-bezier(0.16,1,0.3,1), visibility 0s ${open ? "0s" : "260ms"}`,
          boxShadow: "-24px 0 60px rgba(0,0,0,0.45)",
        }}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <Palette size={16} style={{ color: accentTextColor(accent) }} />
            <span className="text-base font-bold text-white">
              Theme studio
            </span>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close theme studio"
            className={`w-8 h-8 rounded-lg flex items-center justify-center transition-colors hover:bg-white/10 ${FOCUS_RING}`}
            style={{ color: "#CBD5E1" }}
          >
            <X size={16} />
          </button>
        </div>

        <button
          type="button"
          onClick={handleRandomize}
          className={`w-full inline-flex items-center justify-center gap-2 text-sm font-bold px-4 py-2.5 rounded-xl transition-all duration-200 hover:brightness-110 active:scale-[0.97] ${FOCUS_RING}`}
          style={{
            background: `linear-gradient(135deg, ${accent}, ${accent}BB)`,
            color: readableOn(accent),
            boxShadow: `0 4px 16px ${accent}40`,
          }}
        >
          <Dices size={15} /> Randomize gradient
        </button>

        <Panel
          icon={Palette}
          title="Theme"
          accent={accent}
          action={
            <span className="text-xs font-mono" style={{ color: MUTED }}>
              {activePreset ? activePreset.name : "Custom gradient"}
            </span>
          }
        >
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
        {THEME_PRESETS.map((preset) => {
          const active = themeId === preset.id;
          const checkColor = readableOn(preset.accent);
          return (
            <button
              key={preset.id}
              type="button"
              onClick={() => setTheme(preset.id)}
              aria-label={`Use ${preset.name} theme`}
              aria-pressed={active}
              title={preset.name}
              className={`relative overflow-hidden rounded-xl border text-left transition-all duration-200 ease-[cubic-bezier(0.16,1,0.3,1)] hover:-translate-y-px hover:brightness-110 active:scale-[0.99] ${FOCUS_RING}`}
              style={{
                background: `linear-gradient(${preset.angle}deg, ${preset.from}, ${preset.to})`,
                borderColor: active ? preset.accent : BORDER,
                boxShadow: active
                  ? `0 0 0 2px ${preset.accent}, 0 10px 26px rgba(0,0,0,0.32)`
                  : "0 8px 20px rgba(0,0,0,0.18)",
              }}
            >
              {active && (
                <span
                  className="absolute inset-0 pointer-events-none"
                  style={{ background: "rgba(255,255,255,0.06)" }}
                />
              )}
              <div className="p-3">
                <div
                  className="rounded-lg overflow-hidden border"
                  style={{
                    borderColor: "rgba(255,255,255,0.12)",
                    background: "rgba(0,0,0,0.18)",
                  }}
                >
                  <div
                    className="flex items-center gap-1 px-2 py-1.5"
                    style={{ background: "rgba(0,0,0,0.25)" }}
                  >
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: "rgba(255,255,255,0.45)" }}
                    />
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: "rgba(255,255,255,0.45)" }}
                    />
                    <span
                      className="w-1.5 h-1.5 rounded-full"
                      style={{ background: "rgba(255,255,255,0.45)" }}
                    />
                  </div>
                  <div className="flex h-16">
                    <div
                      className="w-8 shrink-0"
                      style={{ background: "rgba(0,0,0,0.28)" }}
                    />
                    <div className="flex-1 min-w-0 p-2 flex flex-col justify-center gap-1.5">
                      <div
                        className="h-1.5 w-3/4 rounded-full"
                        style={{ background: "rgba(255,255,255,0.22)" }}
                      />
                      <div
                        className="h-1.5 w-1/2 rounded-full"
                        style={{ background: "rgba(255,255,255,0.22)" }}
                      />
                      <div
                        className="h-3 w-2/3 rounded-md"
                        style={{ background: "rgba(255,255,255,0.22)" }}
                      />
                    </div>
                  </div>
                </div>
                <div className="flex items-center justify-between gap-2 mt-2.5">
                  <span className="text-xs font-bold text-white truncate">
                    {preset.name}
                  </span>
                  <span
                    className="w-2.5 h-2.5 rounded-full shrink-0"
                    style={{
                      background: preset.accent,
                      boxShadow: `0 0 8px ${preset.accent}`,
                    }}
                  />
                </div>
              </div>
              {active && (
                <span
                  className="absolute top-2 right-2 w-5 h-5 rounded-full flex items-center justify-center"
                  style={{ background: preset.accent, color: checkColor }}
                >
                  <Check size={12} strokeWidth={3} />
                </span>
              )}
            </button>
          );
        })}
      </div>

      <div
        className="rounded-xl border p-4 flex flex-col gap-3"
        style={{ background: INSET, borderColor: BORDER }}
      >
        <div className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <span className="text-sm font-bold text-white">Custom studio</span>
            {themeId === "custom" && (
              <span
                className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full"
                style={{
                  background: `${accent}1F`,
                  color: accentText,
                  border: `1px solid ${accent}40`,
                }}
              >
                <Check size={10} /> Custom
              </span>
            )}
          </div>
          <span
            className="text-xs font-mono shrink-0"
            style={{ color: FAINT }}
          >
            {previewAngle}°
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
          <ColorField
            label="Gradient start"
            value={customFrom}
            onChange={changeCustomFrom}
            fallback={from}
            ariaLabel="Gradient start hex"
          />
          <ColorField
            label="Gradient end"
            value={customTo}
            onChange={changeCustomTo}
            fallback={to}
            ariaLabel="Gradient end hex"
          />
          <ColorField
            label="Accent color"
            value={customAccent}
            onChange={changeCustomAccent}
            fallback={accent}
            ariaLabel="Accent color hex"
          />
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold" style={{ color: MUTED }}>
              Gradient angle
            </span>
            <span
              className="text-xs font-mono font-bold px-2 py-0.5 rounded-md"
              style={{
                background: `${accent}18`,
                color: accentText,
                border: `1px solid ${accent}35`,
              }}
            >
              {previewAngle}°
            </span>
          </div>
          <input
            type="range"
            min={0}
            max={360}
            step={1}
            value={previewAngle}
            onChange={(e) => changeCustomAngle(Number(e.target.value))}
            aria-label="Gradient angle"
            className={`w-full h-1.5 rounded-full appearance-none cursor-pointer ${FOCUS_RING}`}
            style={{
              accentColor: accent,
              background: `linear-gradient(to right, ${accent} ${(previewAngle / 360) * 100}%, rgba(255,255,255,0.12) ${(previewAngle / 360) * 100}%)`,
            }}
          />
        </div>

        <div
          className="relative overflow-hidden rounded-xl border h-16 flex items-center px-4"
          style={{
            background: `linear-gradient(${previewAngle}deg, ${previewFrom}, ${previewTo})`,
            borderColor: BORDER,
            boxShadow: "inset 0 1px 0 var(--glass-highlight)",
          }}
          role="img"
          aria-label="Custom theme preview"
        >
          <div
            className="flex items-center gap-2 rounded-lg px-3 py-2"
            style={{
              background: "rgba(0,0,0,0.28)",
              border: "1px solid rgba(255,255,255,0.12)",
            }}
          >
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{
                background: previewAccent,
                boxShadow: `0 0 10px ${previewAccent}`,
              }}
            />
            <span className="text-xs font-semibold text-white">
              Live preview
            </span>
            <span className="text-[10px] font-mono text-white/60">
              {previewAngle}°
            </span>
          </div>
        </div>

        {!hexValid && (
          <div
            role="alert"
            className="flex items-start gap-2 text-xs leading-relaxed rounded-lg px-3 py-2"
            style={{ background: `${DANGER}0D`, color: "#FCA5A5" }}
          >
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span>
              Use a 6-digit hex color like #5865F2 for each color.
            </span>
          </div>
        )}
      </div>
        </Panel>
      </div>
    </div>,
    document.body,
  );
}

function ThemeCard({ onCustomize, toast }) {
  const { themeId, from, to, accent, angle } = useTheme();
  const activePreset = THEME_PRESETS.find((preset) => preset.id === themeId);
  const accentText = accentTextColor(accent);
  const surface = buttonSurface(accent);

  const handleRandomize = () => {
    const theme = randomizeTheme();
    toast?.success(
      `Random gradient applied (${theme.from} → ${theme.to})`,
      "Theme",
    );
  };

  return (
    <Panel
      icon={Palette}
      title="Theme"
      accent={accent}
      action={
        <span className="text-xs font-mono" style={{ color: MUTED }}>
          {activePreset ? activePreset.name : "Custom gradient"}
        </span>
      }
    >
      <div className="flex flex-col sm:flex-row sm:items-center gap-3">
        <div
          className="relative flex-1 min-w-0 h-20 rounded-xl border overflow-hidden"
          style={{
            background: `linear-gradient(${angle}deg, ${from}, ${to})`,
            borderColor: BORDER,
          }}
        >
          <div className="absolute inset-0 flex items-center gap-3 px-4">
            <span
              className="w-3 h-3 rounded-full shrink-0"
              style={{ background: accent, boxShadow: `0 0 10px ${accent}` }}
            />
            <div className="min-w-0">
              <div className="text-sm font-bold text-white truncate">
                {activePreset ? activePreset.name : "Custom gradient"}
              </div>
              <div
                className="text-xs font-mono truncate"
                style={{ color: "rgba(255,255,255,0.65)" }}
              >
                {from} → {to} · {angle}°
              </div>
            </div>
          </div>
        </div>

        <div className="flex sm:flex-col gap-2 shrink-0">
          <button
            type="button"
            onClick={handleRandomize}
            aria-label="Randomize gradient"
            className={`inline-flex items-center justify-center gap-2 text-sm font-bold px-4 py-2.5 rounded-xl transition-all duration-200 hover:brightness-110 active:scale-[0.97] ${FOCUS_RING}`}
            style={{
              background: surface.background,
              color: surface.color,
              boxShadow: `0 4px 14px ${surface.background}35`,
            }}
          >
            <Dices size={14} /> Randomize
          </button>
          <button
            type="button"
            onClick={onCustomize}
            aria-label="Customize theme"
            className={`inline-flex items-center justify-center gap-2 text-sm font-bold px-4 py-2.5 rounded-xl border transition-all duration-200 hover:brightness-110 active:scale-[0.97] ${FOCUS_RING}`}
            style={{
              background: INSET,
              borderColor: BORDER,
              color: "#E2E8F0",
            }}
          >
            <Palette size={14} /> Customize
          </button>
        </div>
      </div>
    </Panel>
  );
}

function ConfirmDialog({
  open,
  title,
  message,
  confirmLabel,
  tone = "warn",
  onConfirm,
  onCancel,
}) {
  const accent = useAccent();
  const cancelRef = useRef(null);
  const danger = tone === "danger";
  const toneColor = danger ? DANGER : WARNING;
  const confirmBackground = danger
    ? "linear-gradient(135deg,#F23F43,#C0392B)"
    : `linear-gradient(135deg, ${accent}, ${accent}BB)`;

  return (
    <Modal
      open={open}
      onClose={onCancel}
      role="alertdialog"
      label={title}
      maxWidthClass="max-w-md"
      panelClassName="p-6 flex flex-col gap-4"
      initialFocusRef={cancelRef}
      panelStyle={{
        background: "var(--surface-glass-strong)",
        borderColor: `${toneColor}55`,
        backdropFilter: "blur(24px)",
        WebkitBackdropFilter: "blur(24px)",
      }}
    >
      <div className="flex items-center gap-3">
        <div
          className="p-2.5 rounded-xl shrink-0"
          style={{ background: `${toneColor}22` }}
        >
          <AlertTriangle size={22} style={{ color: toneColor }} />
        </div>
        <div className="min-w-0">
          <div className="font-extrabold text-white text-base">{title}</div>
          <p className="text-sm mt-0.5" style={{ color: MUTED }}>
            {message}
          </p>
        </div>
      </div>
      <div className="flex gap-2">
        <button
          ref={cancelRef}
          type="button"
          onClick={onCancel}
          className={`flex-1 py-2.5 text-sm font-semibold rounded-xl transition-all duration-200 ease-[var(--ease-out)] active:scale-[0.97] ${FOCUS_RING}`}
          style={{ background: "#2D3748", color: "#E2E8F0" }}
        >
          Cancel
        </button>
        <button
          type="button"
          onClick={onConfirm}
          className={`flex-1 py-2.5 text-sm font-bold rounded-xl text-white transition-all duration-200 ease-[var(--ease-out)] hover:brightness-110 active:scale-[0.97] ${FOCUS_RING}`}
          style={{
            background: confirmBackground,
            boxShadow: `0 4px 16px ${danger ? "#F23F4350" : `${accent}50`}`,
          }}
        >
          {confirmLabel}
        </button>
      </div>
    </Modal>
  );
}

export default function SettingsView({ toast }) {
  const session = useSessionContext();
  const accent = useAccent();
  const [status, setStatus] = useState(null);
  const [settings, setSettings] = useState(null);
  const [loadingSettings, setLoadingSettings] = useState(false);
  const [settingsError, setSettingsError] = useState(null);
  const [prefix, setPrefix] = useState("");
  const [savedPrefix, setSavedPrefix] = useState("");
  const [prefixSaving, setPrefixSaving] = useState(false);
  const [prefixError, setPrefixError] = useState(null);
  const [unpairing, setUnpairing] = useState(false);
  const [themeDrawerOpen, setThemeDrawerOpen] = useState(false);
  const [reloadBusy, setReloadBusy] = useState(false);
  const [reloadResult, setReloadResult] = useState(null);
  const [confirmState, setConfirmState] = useState(null);
  const confirmResolverRef = useRef(null);
  const aliveRef = useRef(true);

  useEffect(() => {
    aliveRef.current = true;
    return () => {
      aliveRef.current = false;
    };
  }, []);

  const askConfirm = (options) =>
    new Promise((resolve) => {
      confirmResolverRef.current?.(false);
      confirmResolverRef.current = resolve;
      setConfirmState(options);
    });

  const resolveConfirm = (value) => {
    const resolve = confirmResolverRef.current;
    confirmResolverRef.current = null;
    setConfirmState(null);
    resolve?.(value);
  };

  const loadSettings = useCallback(async () => {
    if (!session.authenticated) {
      setSettings(null);
      setPrefix("");
      setSavedPrefix("");
      setPrefixError(null);
      setSettingsError(null);
      setLoadingSettings(false);
      return;
    }

    setLoadingSettings(true);
    setSettingsError(null);
    try {
      const data = await api.getSettings();
      setSettings(data && typeof data === "object" ? data : {});
      const nextPrefix = typeof data?.prefix === "string" ? data.prefix : "";
      setPrefix(nextPrefix);
      setSavedPrefix(nextPrefix);
      setPrefixError(null);
    } catch (err) {
      setSettingsError(err);
      setSettings(null);
    } finally {
      setLoadingSettings(false);
    }
  }, [session.authenticated]);

  const loadStatus = useCallback(async () => {
    if (!session.authenticated) {
      setStatus(null);
      return;
    }
    try {
      setStatus(normalizeStatus(await api.getStatus()));
    } catch {
      // Status is optional here; the profile and prefix still work without it.
    }
  }, [session.authenticated]);

  useEffect(() => {
    loadSettings();
    loadStatus();
  }, [loadSettings, loadStatus]);

  const handleSavePrefix = async () => {
    const cleaned = prefix.trim();
    if (!cleaned || cleaned.length > 5 || /\s/.test(cleaned)) return;

    setPrefixSaving(true);
    setPrefixError(null);
    try {
      const data = await api.savePrefix(cleaned, session.csrf);
      const saved =
        typeof data?.prefix === "string" ? data.prefix : cleaned;
      setPrefix(saved);
      setSavedPrefix(saved);
      toast?.success(
        "Prefix updated — applied within 2 seconds",
        "Settings",
      );
    } catch (err) {
      const code = err?.data?.error;
      if (code === "invalid_prefix") {
        setPrefixError(
          "Invalid prefix — use 1–5 characters with no spaces.",
        );
      } else if (code === "config_write_failed") {
        setPrefixError(
          "Could not write config.json. Check the file permissions and try again.",
        );
      } else if (err?.status === 0) {
        setPrefixError("Local API offline — prefix not saved.");
      } else {
        setPrefixError(
          err?.data?.error || err?.message || "Could not save the prefix.",
        );
      }
    } finally {
      setPrefixSaving(false);
    }
  };

  const handleReload = async () => {
    if (reloadBusy) return;
    const confirmed = await askConfirm({
      title: "Reload config and cogs?",
      message: "Commands will be briefly unavailable while the bot reloads.",
      confirmLabel: "Reload",
      tone: "warn",
    });
    if (!confirmed) return;

    setReloadBusy(true);
    setReloadResult(null);

    let before = reloadAt(status?.lastReload);
    if (before == null) {
      try {
        const baseline = normalizeStatus(await api.getStatus());
        if (!aliveRef.current) return;
        before = reloadAt(baseline?.lastReload);
        setStatus(baseline);
      } catch {
        // The reload can still be requested; polling reports a timeout if
        // the new timestamp cannot be confirmed.
      }
    }

    try {
      await api.requestReload(session.csrf);
    } catch (err) {
      if (!aliveRef.current) return;
      const detail =
        err?.status === 0
          ? "Local API offline — reload not requested."
          : err?.data?.error === "reload_request_failed"
            ? "The backend could not write the reload flag."
            : err?.data?.error || err?.message || "Reload request failed.";
      setReloadResult({ ok: false, detail });
      setReloadBusy(false);
      return;
    }

    for (let attempt = 0; attempt < RELOAD_POLL_ATTEMPTS; attempt += 1) {
      if (attempt > 0) await sleep(RELOAD_POLL_INTERVAL_MS);
      if (!aliveRef.current) return;

      try {
        const raw = await api.getStatus();
        const nextStatus = normalizeStatus(raw);
        if (!aliveRef.current) return;
        setStatus(nextStatus);

        const at = reloadAt(nextStatus?.lastReload);
        if (at != null && at !== before) {
          const detail =
            reloadDetail(nextStatus?.lastReload) ||
            "Config and cogs reloaded.";
          setReloadResult({
            ok: reloadOk(nextStatus?.lastReload),
            detail,
          });
          setReloadBusy(false);
          return;
        }
      } catch {
        // The API can be briefly unavailable while the bot reloads; keep polling.
      }
    }

    if (!aliveRef.current) return;
    setReloadResult({
      ok: null,
      detail: "Reload requested — the bot will apply it shortly.",
    });
    setReloadBusy(false);
  };

  const handleUnpair = async () => {
    const confirmed = await askConfirm({
      title: "Unpair this browser?",
      message: "You will need the pairing code to reconnect.",
      confirmLabel: "Unpair",
      tone: "danger",
    });
    if (!confirmed) return;

    setUnpairing(true);
    try {
      await session.logout();
      toast?.success("Session unpaired.", "Settings");
    } catch (err) {
      toast?.error(
        err?.status === 0
          ? "Local API offline — session cleared locally."
          : "Logout request failed — session cleared locally.",
        "Settings",
      );
    } finally {
      setUnpairing(false);
    }
  };

  const handleCopyError = () => {
    toast?.error("Could not copy to the clipboard.", "Settings");
  };

  if (session.loading) {
    return (
      <div className="w-full max-w-5xl">
        <div
          className="rounded-2xl border px-4 py-5 text-sm"
          style={{ background: SURFACE, borderColor: BORDER, color: MUTED }}
        >
          Connecting to the local API…
        </div>
      </div>
    );
  }

  if (!session.authenticated) {
    return (
      <div className="flex flex-col gap-4 w-full max-w-5xl">
        <div
          className="flex items-start gap-3 rounded-2xl border px-4 py-4"
          style={{ background: `${WARNING}0D`, borderColor: `${WARNING}40` }}
        >
          <KeyRound
            size={17}
            className="mt-0.5 shrink-0"
            style={{ color: WARNING }}
          />
          <div>
            <div className="text-sm font-bold text-white">Not paired</div>
            <div
              className="text-sm leading-relaxed mt-0.5"
              style={{ color: MUTED }}
            >
              Pair this dashboard from the banner above to load your profile
              and settings.
            </div>
          </div>
        </div>
        <ThemeCard
          onCustomize={() => setThemeDrawerOpen(true)}
          toast={toast}
        />
        <ThemeDrawer
          open={themeDrawerOpen}
          onClose={() => setThemeDrawerOpen(false)}
          toast={toast}
        />
      </div>
    );
  }

  const profile = settings?.profile ?? null;
  const profileLoading =
    loadingSettings || (settings === null && !settingsError);

  return (
    <div className="flex flex-col gap-4 w-full max-w-5xl">
      <HeroProfile
        profile={profile}
        status={status}
        accent={accent}
        authenticated={session.authenticated}
        loading={profileLoading}
        unpairing={unpairing}
        onUnpair={handleUnpair}
        onCopyError={handleCopyError}
      />

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <PrefixCard
          prefix={prefix}
          savedPrefix={savedPrefix}
          onPrefixChange={(value) => {
            setPrefix(value);
            setPrefixError(null);
          }}
          onSave={handleSavePrefix}
          saving={prefixSaving}
          error={prefixError}
          settingsError={settingsError}
          onRetry={loadSettings}
          disabled={settings === null || loadingSettings}
          accent={accent}
        />
        <ReloadCard
          status={status}
          busy={reloadBusy}
          result={reloadResult}
          onReload={handleReload}
          disabled={!session.authenticated}
        />
      </div>

      <ThemeCard
        onCustomize={() => setThemeDrawerOpen(true)}
        toast={toast}
      />
      <ThemeDrawer
        open={themeDrawerOpen}
        onClose={() => setThemeDrawerOpen(false)}
        toast={toast}
      />
      <ConfirmDialog
        open={Boolean(confirmState)}
        {...confirmState}
        onConfirm={() => resolveConfirm(true)}
        onCancel={() => resolveConfirm(false)}
      />
    </div>
  );
}
