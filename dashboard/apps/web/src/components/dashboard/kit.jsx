"use client";
import { useState } from "react";
import { Save } from "lucide-react";
import Toggle from "./Toggle";
import TgEmoji from "./TgEmoji";
import { useAccent } from "../../lib/theme";

/* ── Hero header for every feature view: icon + title + master toggle + stat tiles ── */
export function FeatureHero({
  icon: Icon,
  title,
  emojiId,
  accent: accentProp,
  enabled,
  onToggle,
  toggleLabel,
  disabled = false,
  stats = [],
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const statsGridClass =
    stats.length === 5
      ? "grid grid-cols-2 sm:grid-cols-3 xl:grid-cols-5 gap-2 flex-1"
      : stats.length === 3
        ? "grid grid-cols-2 sm:grid-cols-3 gap-2 flex-1"
        : "grid grid-cols-2 sm:grid-cols-4 gap-2 flex-1";

  return (
    <div
      className="rounded-2xl border p-4 sm:p-5 relative overflow-hidden"
      style={{
        background: "var(--surface-glass)",
        borderColor: "var(--glass-border)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        boxShadow: "var(--elevation-2)",
      }}
    >
      <div
        className="absolute inset-0 pointer-events-none hero-wash"
        style={{
          background: `radial-gradient(ellipse at 0% 0%, ${accent}0D 0%, transparent 55%)`,
        }}
      />
      <div className="relative flex flex-col xl:flex-row xl:items-center gap-4">
        <div className="flex items-center gap-4 min-w-0 xl:w-[300px] shrink-0">
          <div
            className="w-14 h-14 rounded-2xl flex items-center justify-center shrink-0"
            style={{
              background: `linear-gradient(135deg, ${accent}40, ${accent}10)`,
              border: `1px solid ${accent}55`,
              boxShadow: `0 0 24px ${accent}35`,
            }}
          >
            <TgEmoji id={emojiId} size={30} fallback={Icon} />
          </div>
          <div className="min-w-0 flex-1">
            <div
              className="text-xl sm:text-2xl font-extrabold text-white leading-tight truncate"
              style={{
                fontFamily: "var(--font-display)",
                letterSpacing: "-0.02em",
              }}
            >
              {title}
            </div>
          </div>
          {onToggle && (
            <div className="flex flex-col items-center gap-1 shrink-0">
              <Toggle
                enabled={enabled}
                onChange={onToggle}
                size="lg"
                label={toggleLabel}
                disabled={disabled}
              />
              <span
                className="text-xs font-semibold tracking-wide"
                style={{ color: enabled ? "#23A55A" : "#64748B" }}
              >
                {enabled ? "ON" : "OFF"}
              </span>
            </div>
          )}
        </div>
        <div className={statsGridClass} data-testid="feature-hero-stats">
          {stats.map((s, i) => (
            <StatTile key={s.label} index={i} {...s} />
          ))}
        </div>
      </div>
    </div>
  );
}

export function StatTile({ icon: Icon, label, value, color: colorProp, index = 0 }) {
  const storeAccent = useAccent();
  const color = colorProp ?? storeAccent;
  return (
    <div
      className="stagger-item relative overflow-hidden flex items-center gap-2 xl:gap-1.5 px-2.5 py-2 sm:px-3 sm:py-2.5 xl:px-2 xl:py-2 rounded-xl border transition-colors duration-200"
      style={{
        "--i": index,
        background: "var(--surface-inset)",
        borderColor: "var(--glass-border)",
        borderTop: `2px solid ${color}80`,
        boxShadow: "inset 0 1px 0 var(--glass-highlight)",
      }}
    >
      <div
        className="relative z-10 w-7 h-7 xl:w-6 xl:h-6 rounded-lg flex items-center justify-center shrink-0"
        style={{ background: `${color}18` }}
      >
        <Icon size={13} style={{ color }} />
      </div>
      <div className="relative z-10 min-w-0">
        <div
          className="text-base font-bold text-white tabular-nums truncate leading-tight"
          style={{
            fontFamily: "var(--font-display)",
            letterSpacing: "-0.01em",
          }}
        >
          {value}
        </div>
        <div className="text-xs font-medium text-[#94A3B8] truncate">
          {label}
        </div>
      </div>
    </div>
  );
}

/* ── Compact card with icon title ── */
export function Panel({
  icon: Icon,
  title,
  accent: accentProp,
  action,
  children,
  className = "",
  danger = false,
  style,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  return (
    <div
      className={`rounded-2xl border p-4 flex flex-col gap-3 ${className}`}
      style={{
        background: danger
          ? "linear-gradient(0deg, rgba(242,63,67,0.08), rgba(242,63,67,0.08)), var(--surface-glass)"
          : "var(--surface-glass)",
        borderColor: danger ? "rgba(242,63,67,0.28)" : "var(--glass-border)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        boxShadow: "var(--elevation-1)",
        ...style,
      }}
    >
      <div className="flex items-center gap-2">
        {Icon && (
          <div
            className="w-7 h-7 rounded-lg flex items-center justify-center shrink-0"
            style={{ background: `${accent}18` }}
          >
            <Icon size={14} style={{ color: accent }} />
          </div>
        )}
        <span className="text-base font-bold text-white flex-1 truncate">
          {title}
        </span>
        {action}
      </div>
      {children}
    </div>
  );
}

/* ── Compact empty state with a Telegram illustration ── */
export function EmptyState({
  emojiId,
  icon: Icon,
  title,
  description,
  action,
  compact = false,
  className = "",
}) {
  return (
    <div
      className={`flex flex-col items-center justify-center gap-2 ${
        compact ? "py-2.5" : "py-6"
      } text-center ${className}`}
    >
      <TgEmoji id={emojiId} size={34} fallback={Icon} />
      {title && (
        <div className="text-sm font-semibold" style={{ color: "#CBD5E1" }}>
          {title}
        </div>
      )}
      {description && (
        <div
          className="text-xs leading-relaxed max-w-[38ch]"
          style={{ color: "#94A3B8" }}
        >
          {description}
        </div>
      )}
      {action}
    </div>
  );
}

/* ── Visual choice grid (replaces dropdowns) ── */
export function ChoiceGrid({
  options,
  value,
  onChange,
  accent: accentProp,
  cols = 4,
  disabled = false,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const colClass =
    {
      2: "grid-cols-2",
      3: "grid-cols-3",
      4: "grid-cols-4",
      5: "grid-cols-5",
      7: "grid-cols-4 sm:grid-cols-7",
    }[cols] || "grid-cols-4";
  return (
    <div className={`grid ${colClass} gap-2`}>
      {options.map((o) => {
        const active = value === o.value;
        const Ic = o.icon;
        const c = o.color || accent;
        return (
          <button
            key={o.value}
            type="button"
            onClick={() => !disabled && onChange(o.value)}
            title={o.label}
            aria-pressed={active}
            disabled={disabled}
            className={`flex flex-col items-center justify-center gap-1.5 py-2.5 px-1 rounded-xl border transition-all duration-200 hover:-translate-y-px active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--tile-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121722] disabled:opacity-50 disabled:cursor-not-allowed ${
              active
                ? "border-[color:var(--tile-accent)]"
                : "border-[#1F2636] hover:border-[color:var(--tile-accent)]"
            }`}
            style={{
              "--tile-accent": c,
              background: active ? `${c}1F` : "#0B0E14",
              boxShadow: active ? `0 0 12px ${c}30` : "none",
              transitionTimingFunction: "var(--ease-out)",
            }}
          >
            {Ic && <Ic size={18} style={{ color: active ? c : "#94A3B8" }} />}
            {o.dot && (
              <span
                className="w-3.5 h-3.5 rounded-full"
                style={{
                  background: o.dot,
                  boxShadow: active ? `0 0 8px ${o.dot}` : "none",
                }}
              />
            )}
            <span
              className="text-xs font-semibold truncate max-w-full"
              style={{ color: active ? "#fff" : "#94A3B8" }}
            >
              {o.short || o.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}

/* ── Square toggle tile ── */
export function ToggleTile({
  icon: Icon,
  label,
  enabled,
  onChange,
  accent = "#23A55A",
}) {
  return (
    <button
      type="button"
      onClick={() => onChange(!enabled)}
      aria-pressed={enabled}
      className={`flex flex-col items-center justify-center gap-1.5 py-3 rounded-xl border transition-all duration-200 hover:-translate-y-px active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--tile-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121722] ${
        enabled
          ? "border-[color:var(--tile-accent)]"
          : "border-[#1F2636] hover:border-[color:var(--tile-accent)]"
      }`}
      style={{
        "--tile-accent": accent,
        background: enabled ? `${accent}18` : "#0B0E14",
        boxShadow: enabled ? `0 0 12px ${accent}30` : "none",
        transitionTimingFunction: "var(--ease-out)",
      }}
    >
      <Icon size={18} style={{ color: enabled ? accent : "#94A3B8" }} />
      <span
        className="text-xs font-semibold"
        style={{ color: enabled ? "#fff" : "#94A3B8" }}
      >
        {label}
      </span>
    </button>
  );
}

/* ── Input with leading icon ── */
export function IconInput({
  icon: Icon,
  value,
  onChange,
  placeholder,
  mono = false,
  accent: accentProp,
  disabled = false,
  type = "text",
  size = "md",
  maxLength,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const [focused, setFocused] = useState(false);
  const padding = size === "lg" ? "py-3" : "py-2.5";
  return (
    <div
      className="flex items-center gap-2 rounded-xl border px-3 transition-all duration-200"
      style={{
        background: "var(--surface-inset)",
        borderColor: focused ? accent : "var(--glass-border)",
        boxShadow: focused ? `0 0 0 3px ${accent}25` : "none",
        transitionTimingFunction: "var(--ease-out)",
      }}
    >
      {Icon && (
        <Icon
          size={14}
          style={{
            color: focused ? accent : "#94A3B8",
            flexShrink: 0,
            opacity: disabled ? 0.5 : 1,
          }}
        />
      )}
      <input
        type={type}
        value={value}
        disabled={disabled}
        maxLength={maxLength}
        onChange={(e) => onChange && onChange(e.target.value)}
        placeholder={placeholder}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className={`flex-1 min-w-0 bg-transparent outline-none text-sm ${padding} placeholder-[#64748B] disabled:opacity-50 disabled:cursor-not-allowed`}
        style={{
          color: disabled ? "#64748B" : "#E2E8F0",
          fontFamily: mono ? "monospace" : "inherit",
        }}
      />
    </div>
  );
}

/* ── Slider with big value badge ── */
export function SliderRow({
  value,
  onChange,
  min,
  max,
  step = 1,
  unit = "",
  accent: accentProp,
  disabled = false,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const pct = ((value - min) / (max - min)) * 100;
  return (
    <div className="flex items-center gap-3">
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
        className="flex-1 h-1.5 rounded-full appearance-none cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--slider-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121722]"
        style={{
          "--slider-accent": accent,
          accentColor: accent,
          background: `linear-gradient(to right, ${accent} ${pct}%, #1F2636 ${pct}%)`,
        }}
      />
      <span
        className="text-base font-bold font-mono px-2.5 py-1 rounded-lg shrink-0 min-w-[64px] text-center"
        style={{
          background: `${accent}18`,
          color: accent,
          border: `1px solid ${accent}40`,
          opacity: disabled ? 0.5 : 1,
        }}
      >
        {value}
        {unit}
      </span>
    </div>
  );
}

/* ── Small icon button ── */
export function IconBtn({
  icon: Icon,
  onClick,
  color: colorProp,
  title,
  filled = false,
  disabled = false,
}) {
  const storeAccent = useAccent();
  const color = colorProp ?? storeAccent;
  return (
    <button
      type="button"
      onClick={disabled ? undefined : onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 transition-all duration-200 hover:brightness-110 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--btn-color)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121722] disabled:opacity-50 disabled:cursor-not-allowed`}
      style={{
        "--btn-color": color,
        background: filled ? color : `${color}15`,
        color: filled ? "#fff" : color,
        border: `1px solid ${color}35`,
      }}
    >
      <Icon size={14} />
    </button>
  );
}

/* ── Bottom save bar ── */
export function SaveBar({
  label,
  accent: accentProp,
  onSave,
  onReset,
  danger = false,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const bg = danger
    ? "linear-gradient(135deg,#F23F43,#C0392B)"
    : `linear-gradient(135deg, ${accent}, ${accent}BB)`;
  return (
    <div
      className="flex items-center justify-end gap-2 px-4 py-3 rounded-2xl border"
      style={{
        "--save-accent": danger ? "#F23F43" : accent,
        background: "rgba(18,23,34,0.92)",
        backdropFilter: "blur(12px)",
        WebkitBackdropFilter: "blur(12px)",
        borderColor: "#1F2636",
      }}
    >
      {onReset && (
        <button
          onClick={onReset}
          className="text-sm font-semibold px-4 py-2.5 rounded-xl transition-all duration-200 hover:brightness-110 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--save-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121722]"
          style={{ background: "#1F2636", color: "#94A3B8" }}
        >
          Reset
        </button>
      )}
      <button
        onClick={onSave}
        className="flex items-center gap-2 text-sm font-bold px-5 py-2.5 rounded-xl text-white transition-all duration-200 hover:brightness-110 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--save-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121722]"
        style={{
          background: bg,
          boxShadow: `0 4px 16px ${danger ? "#F23F4350" : `${accent}50`}`,
        }}
      >
        <Save size={14} /> {label}
      </button>
    </div>
  );
}
