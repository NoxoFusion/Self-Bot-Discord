"use client";
// ─── Shared UI primitives for dashboard feature drawers ───────────────────────

import { useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import { useAccent } from "../../lib/theme";

/* Sub-section wrapper */
export function SubSection({ title, accent: accentProp, children }) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  return (
    <div
      className="rounded-xl border p-4 flex flex-col gap-3"
      style={{
        background: "var(--surface-glass)",
        borderColor: "var(--glass-border)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        boxShadow:
          "inset 0 1px 0 var(--glass-highlight), 0 12px 32px rgba(0,0,0,0.28)",
      }}
    >
      {title && (
        <div
          className="flex items-center gap-2 pb-1 border-b"
          style={{ borderColor: "var(--glass-border)" }}
        >
          <span className="text-xs font-semibold" style={{ color: accent }}>
            {title}
          </span>
        </div>
      )}
      {children}
    </div>
  );
}

/* Field label + content */
export function Field({ label, hint, children, row = false }) {
  return (
    <div
      className={`flex gap-2 ${row ? "items-center justify-between" : "flex-col"}`}
    >
      {label && (
        <label
          className="text-sm font-semibold shrink-0"
          style={{ color: "#94A3B8" }}
        >
          {label}
        </label>
      )}
      <div className={row ? "flex-1" : ""}>{children}</div>
      {hint && !row && (
        <span className="text-xs leading-relaxed" style={{ color: "#94A3B8" }}>
          {hint}
        </span>
      )}
    </div>
  );
}

/* Text input */
export function TextInput({
  value,
  onChange,
  placeholder,
  type = "text",
  mono = false,
  accent: accentProp,
  disabled = false,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const [focused, setFocused] = useState(false);
  return (
    <input
      type={type}
      value={value}
      onChange={(e) => onChange && onChange(e.target.value)}
      placeholder={placeholder}
      disabled={disabled}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      className="w-full text-sm placeholder-[#64748B] outline-none transition-all duration-200"
      style={{
        background: "var(--surface-inset)",
        border: `1px solid ${focused ? accent : "var(--glass-border)"}`,
        borderRadius: 10,
        padding: "9px 12px",
        color: disabled ? "#64748B" : "#E2E8F0",
        fontFamily: mono ? "monospace" : "inherit",
        boxShadow: focused ? `0 0 0 3px ${accent}25` : "none",
        cursor: disabled ? "not-allowed" : "text",
        transitionTimingFunction: "var(--ease-out)",
      }}
    />
  );
}

/* Password / masked input with eye toggle */
export function PasswordInput({
  value,
  onChange,
  placeholder,
  accent: accentProp,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const [show, setShow] = useState(false);
  const [focused, setFocused] = useState(false);
  return (
    <div className="relative">
      <input
        type={show ? "text" : "password"}
        value={value}
        onChange={(e) => onChange && onChange(e.target.value)}
        placeholder={placeholder}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className="w-full text-sm placeholder-[#64748B] outline-none transition-all duration-200 pr-10"
        style={{
          background: "var(--surface-inset)",
          border: `1px solid ${focused ? accent : "var(--glass-border)"}`,
          borderRadius: 10,
          padding: "9px 12px",
          color: "#E2E8F0",
          fontFamily: "monospace",
          boxShadow: focused ? `0 0 0 3px ${accent}25` : "none",
          transitionTimingFunction: "var(--ease-out)",
        }}
      />
      <button
        type="button"
        onClick={() => setShow((v) => !v)}
        aria-label={show ? "Hide password" : "Show password"}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 p-1 rounded-md text-[#94A3B8] hover:text-white transition-all duration-150 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--focus-ring)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#141820]"
      >
        {show ? <EyeOff size={14} /> : <Eye size={14} />}
      </button>
    </div>
  );
}

/* Select / dropdown */
export function Select({ value, onChange, options, accent: accentProp }) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const [focused, setFocused] = useState(false);
  return (
    <select
      value={value}
      onChange={(e) => onChange && onChange(e.target.value)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      className="w-full text-sm outline-none transition-all duration-200 cursor-pointer appearance-none"
      style={{
        background: "var(--surface-inset)",
        border: `1px solid ${focused ? accent : "var(--glass-border)"}`,
        borderRadius: 10,
        padding: "9px 12px",
        color: "#E2E8F0",
        boxShadow: focused ? `0 0 0 3px ${accent}25` : "none",
        backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2394A3B8' stroke-width='2'%3E%3Cpolyline points='6 9 12 15 18 9'/%3E%3C/svg%3E")`,
        backgroundRepeat: "no-repeat",
        backgroundPosition: "right 12px center",
        paddingRight: 36,
        transitionTimingFunction: "var(--ease-out)",
      }}
    >
      {options.map((o) => (
        <option
          key={o.value ?? o}
          value={o.value ?? o}
          style={{ background: "var(--surface-solid)" }}
        >
          {o.label ?? o}
        </option>
      ))}
    </select>
  );
}

/* Textarea */
export function Textarea({
  value,
  onChange,
  placeholder,
  rows = 4,
  accent: accentProp,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const [focused, setFocused] = useState(false);
  return (
    <textarea
      value={value}
      onChange={(e) => onChange && onChange(e.target.value)}
      placeholder={placeholder}
      rows={rows}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      className="w-full text-sm placeholder-[#64748B] outline-none transition-all duration-200 resize-none"
      style={{
        background: "var(--surface-inset)",
        border: `1px solid ${focused ? accent : "var(--glass-border)"}`,
        borderRadius: 10,
        padding: "9px 12px",
        color: "#E2E8F0",
        boxShadow: focused ? `0 0 0 3px ${accent}25` : "none",
        transitionTimingFunction: "var(--ease-out)",
      }}
    />
  );
}

/* Number Input */
export function NumberInput({
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix,
  accent: accentProp,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const [focused, setFocused] = useState(false);
  return (
    <div className="flex items-center gap-2">
      <input
        type="number"
        value={value}
        onChange={(e) => onChange && onChange(e.target.value)}
        min={min}
        max={max}
        step={step}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
        className="w-full text-sm placeholder-[#64748B] outline-none transition-all duration-200 font-mono"
        style={{
          background: "var(--surface-inset)",
          border: `1px solid ${focused ? accent : "var(--glass-border)"}`,
          borderRadius: 10,
          padding: "9px 12px",
          color: "#E2E8F0",
          boxShadow: focused ? `0 0 0 3px ${accent}25` : "none",
          transitionTimingFunction: "var(--ease-out)",
        }}
      />
      {suffix && (
        <span className="text-xs shrink-0" style={{ color: "#94A3B8" }}>
          {suffix}
        </span>
      )}
    </div>
  );
}

/* Primary action button */
export function SaveButton({
  onClick,
  label = "Save Changes",
  accent: accentProp,
  danger = false,
}) {
  const storeAccent = useAccent();
  const accent = accentProp ?? storeAccent;
  const bg = danger
    ? "linear-gradient(135deg,#F23F43,#C0392B)"
    : `linear-gradient(135deg,${accent},${accent}bb)`;
  return (
    <button
      onClick={onClick}
      className="flex items-center gap-2 text-sm font-semibold px-5 py-2.5 rounded-xl text-white transition-all duration-200 hover:brightness-110 active:scale-[0.97] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[color:var(--save-accent)] focus-visible:ring-offset-2 focus-visible:ring-offset-[#121722]"
      style={{
        "--save-accent": danger ? "#F23F43" : accent,
        background: bg,
        boxShadow: `0 4px 16px ${danger ? "rgba(242,63,67,0.3)" : `${accent}40`}`,
      }}
    >
      {label}
    </button>
  );
}

/* Divider */
export function Divider() {
  return (
    <div className="h-px w-full" style={{ background: "var(--glass-border)" }} />
  );
}

/* Image Preview box */
export function ImagePreview({ url, label }) {
  return (
    <div
      className="rounded-xl border flex items-center justify-center overflow-hidden"
      style={{
        background: "var(--surface-inset)",
        borderColor: "var(--glass-border)",
        minHeight: 80,
      }}
    >
      {url ? (
        <img
          src={url}
          alt={label || "preview"}
          className="w-full h-full object-cover"
          style={{ maxHeight: 140 }}
          onError={(e) => {
            e.target.style.display = "none";
            e.target.nextSibling.style.display = "flex";
          }}
        />
      ) : null}
      <div
        className="flex flex-col items-center gap-1 py-4"
        style={{ display: url ? "none" : "flex", color: "#64748B" }}
      >
        <svg
          width="24"
          height="24"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
        >
          <rect x="3" y="3" width="18" height="18" rx="3" />
          <circle cx="8.5" cy="8.5" r="1.5" />
          <path d="M21 15l-5-5L5 21" />
        </svg>
        <span className="text-xs">No image URL</span>
      </div>
    </div>
  );
}
