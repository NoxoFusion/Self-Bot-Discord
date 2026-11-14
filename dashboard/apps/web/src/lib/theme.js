"use client";

// ─── Global gradient theme ──────────────────────────────────────────────────
// A Discord-Nitro-style theme is a background gradient (from/to/angle) plus an
// accent color. Components read the accent through useAccent(), the full theme
// through useTheme(), and the Settings view writes it through setTheme(),
// setCustomTheme() or the legacy setAccent(). The active theme is mirrored onto
// the document root as CSS custom properties so the whole UI can consume it.

import { create } from "zustand";
import { persist } from "zustand/middleware";

export const DEFAULT_THEME_ID = "midnight-blurple";

export const THEME_PRESETS = [
  {
    id: "midnight-blurple",
    name: "Midnight Blurple",
    from: "#1E1F38",
    to: "#0C0D1A",
    accent: "#5865F2",
    angle: 135,
  },
  {
    id: "chroma-glow",
    name: "Chroma Glow",
    from: "#2A1145",
    to: "#0B1A30",
    accent: "#00F2FE",
    angle: 135,
  },
  {
    id: "retro-storm",
    name: "Retro Storm",
    from: "#3D144C",
    to: "#110E26",
    accent: "#F43F5E",
    angle: 160,
  },
  {
    id: "emerald-twilight",
    name: "Emerald Twilight",
    from: "#0D2818",
    to: "#040D0A",
    accent: "#10B981",
    angle: 135,
  },
  {
    id: "strawberry-dusk",
    name: "Strawberry Dusk",
    from: "#3B1424",
    to: "#151124",
    accent: "#FB7185",
    angle: 145,
  },
  {
    id: "oceanic-deep",
    name: "Oceanic Deep",
    from: "#062038",
    to: "#040D18",
    accent: "#38BDF8",
    angle: 135,
  },
  {
    id: "crimson-moon",
    name: "Crimson Moon",
    from: "#360D16",
    to: "#0F0407",
    accent: "#EF4444",
    angle: 150,
  },
  {
    id: "amber-sunset",
    name: "Amber Sunset",
    from: "#362208",
    to: "#120B04",
    accent: "#F59E0B",
    angle: 135,
  },
  {
    id: "pure-obsidian",
    name: "Pure Obsidian",
    from: "#18191C",
    to: "#08090A",
    accent: "#94A3B8",
    angle: 180,
  },
];

const DEFAULT_THEME = THEME_PRESETS[0];

export const DEFAULT_ACCENT = DEFAULT_THEME.accent;

// Canonical status colors. Kept in JS so components can reference the same
// values the design tokens use instead of hardcoding hex literals.
export const SEMANTIC_COLORS = {
  info: "#58B8E8",
  success: "#23A55A",
  warn: "#F5B642",
  danger: "#F23F43",
  blurple: "#5865F2",
};

// Legacy accent-only presets, kept for the existing Settings view.
export const ACCENT_PRESETS = [
  { name: "Discord Blurple", value: "#5865F2" },
  { name: "Electric Cyan", value: "#06B6D4" },
  { name: "Matrix Emerald", value: "#10B981" },
  { name: "Neon Purple", value: "#8B5CF6" },
  { name: "Cyber Pink", value: "#EC4899" },
  { name: "Sunset Amber", value: "#F59E0B" },
  { name: "Crimson Red", value: "#EF4444" },
];

const HEX_COLOR = /^#[0-9a-fA-F]{6}$/;

export function isValidHex(value) {
  return typeof value === "string" && HEX_COLOR.test(value);
}

// The dark surface accents are painted on (--surface-solid) and the dark text
// color used on top of a light accent.
const ACCENT_SURFACE = "#0E1219";
const ACCENT_TEXT_DARK = "#0B0E14";
const ACCENT_MIN_CONTRAST = 3;
const ACCENT_TEXT_MIN_CONTRAST = 4.5;
const ACCENT_LIGHTEN_STEPS = 12;

function hexToRgb(hex) {
  return {
    r: parseInt(hex.slice(1, 3), 16),
    g: parseInt(hex.slice(3, 5), 16),
    b: parseInt(hex.slice(5, 7), 16),
  };
}

function rgbToHex(r, g, b) {
  const channel = (value) =>
    Math.round(Math.min(255, Math.max(0, value)))
      .toString(16)
      .padStart(2, "0");
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

function linearizeChannel(channel) {
  const value = channel / 255;
  return value <= 0.03928
    ? value / 12.92
    : ((value + 0.055) / 1.055) ** 2.4;
}

// WCAG relative luminance. Invalid input has no luminance, so it reports 0.
export function relativeLuminance(hex) {
  if (!isValidHex(hex)) return 0;
  const { r, g, b } = hexToRgb(hex);
  return (
    0.2126 * linearizeChannel(r) +
    0.7152 * linearizeChannel(g) +
    0.0722 * linearizeChannel(b)
  );
}

export function contrastRatio(hexA, hexB) {
  const luminanceA = relativeLuminance(hexA);
  const luminanceB = relativeLuminance(hexB);
  const lighter = Math.max(luminanceA, luminanceB);
  const darker = Math.min(luminanceA, luminanceB);
  return (lighter + 0.05) / (darker + 0.05);
}

// Return an accent that is legible as text/icons on the dark surface. Dark
// accents are mixed toward white in small steps until they reach the minimum
// contrast, so custom themes cannot produce invisible accent text.
export function readableAccent(hex) {
  if (!isValidHex(hex)) return DEFAULT_ACCENT;
  if (contrastRatio(hex, ACCENT_SURFACE) >= ACCENT_MIN_CONTRAST) return hex;

  const { r, g, b } = hexToRgb(hex);
  for (let step = 1; step <= ACCENT_LIGHTEN_STEPS; step += 1) {
    const amount = step / ACCENT_LIGHTEN_STEPS;
    const candidate = rgbToHex(
      r + (255 - r) * amount,
      g + (255 - g) * amount,
      b + (255 - b) * amount,
    );
    if (contrastRatio(candidate, ACCENT_SURFACE) >= ACCENT_MIN_CONTRAST) {
      return candidate;
    }
  }
  return "#FFFFFF";
}

// Pick the text color to place on top of an accent-filled control.
export function accentTextColor(hex) {
  if (contrastRatio(hex, ACCENT_TEXT_DARK) >= ACCENT_TEXT_MIN_CONTRAST) {
    return ACCENT_TEXT_DARK;
  }
  return "#FFFFFF";
}

function toFiniteNumber(value) {
  if (typeof value === "number") {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === "string" && value.trim() !== "") {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : null;
  }
  return null;
}

function clampAngle(value, fallback = DEFAULT_THEME.angle) {
  const numeric = toFiniteNumber(value);
  if (numeric === null) return fallback;
  return Math.min(360, Math.max(0, numeric));
}

function isKnownThemeId(themeId) {
  return (
    themeId === "custom" ||
    THEME_PRESETS.some((preset) => preset.id === themeId)
  );
}

// The persisted shape used to be { accent } only. Migrate that legacy shape to
// a custom theme built on the default gradient, and reject anything malformed.
function mergePersistedTheme(persisted, current) {
  if (!persisted || typeof persisted !== "object") return current;

  const hasThemeShape =
    "themeId" in persisted ||
    "from" in persisted ||
    "to" in persisted ||
    "angle" in persisted;

  if (!hasThemeShape) {
    if (isValidHex(persisted.accent)) {
      return {
        ...current,
        themeId: "custom",
        from: DEFAULT_THEME.from,
        to: DEFAULT_THEME.to,
        accent: persisted.accent,
        angle: DEFAULT_THEME.angle,
      };
    }
    return current;
  }

  const angle = toFiniteNumber(persisted.angle);
  if (
    !isKnownThemeId(persisted.themeId) ||
    !isValidHex(persisted.from) ||
    !isValidHex(persisted.to) ||
    angle === null
  ) {
    return current;
  }

  return {
    ...current,
    themeId: persisted.themeId,
    from: persisted.from,
    to: persisted.to,
    accent: isValidHex(persisted.accent) ? persisted.accent : current.accent,
    angle: clampAngle(angle),
  };
}

// Mirror the active theme onto the document root. Guarded so the module can be
// imported during SSR.
export function applyTheme(theme) {
  if (typeof document === "undefined") return;

  const from = isValidHex(theme?.from) ? theme.from : DEFAULT_THEME.from;
  const to = isValidHex(theme?.to) ? theme.to : DEFAULT_THEME.to;
  const accent = isValidHex(theme?.accent) ? theme.accent : DEFAULT_ACCENT;
  const angle = clampAngle(theme?.angle, DEFAULT_THEME.angle);
  const style = document.documentElement.style;

  style.setProperty("--accent", accent);
  style.setProperty("--accent-readable", readableAccent(accent));
  style.setProperty("--accent-contrast", accentTextColor(accent));
  style.setProperty("--bg-from", from);
  style.setProperty("--bg-to", to);
  style.setProperty(
    "--bg-gradient",
    `linear-gradient(${angle}deg, ${from} 0%, ${to} 100%)`,
  );
  style.setProperty("--surface-glass", "rgba(16,20,30,0.66)");
  style.setProperty("--surface-glass-strong", "rgba(16,20,30,0.82)");
  style.setProperty("--surface-inset", "rgba(8,11,17,0.55)");
  style.setProperty("--surface-solid", "#0E1219");
  style.setProperty("--glass-border", "rgba(255,255,255,0.09)");
  style.setProperty("--glass-highlight", "rgba(255,255,255,0.04)");
}

export const useAccentStore = create(
  persist(
    (set, get) => ({
      themeId: DEFAULT_THEME_ID,
      from: DEFAULT_THEME.from,
      to: DEFAULT_THEME.to,
      accent: DEFAULT_ACCENT,
      angle: DEFAULT_THEME.angle,

      setTheme: (presetId) => {
        const preset = THEME_PRESETS.find((item) => item.id === presetId);
        if (!preset) return;
        set({
          themeId: preset.id,
          from: preset.from,
          to: preset.to,
          accent: preset.accent,
          angle: preset.angle,
        });
      },

      setCustomTheme: (theme) => {
        const { from, to, accent, angle } = theme ?? {};
        if (!isValidHex(from) || !isValidHex(to) || !isValidHex(accent)) {
          return;
        }
        set({
          themeId: "custom",
          from,
          to,
          accent,
          angle: clampAngle(angle, get().angle),
        });
      },

      // Backward-compatible accent-only update: keeps the current gradient.
      setAccent: (color) => {
        if (!isValidHex(color)) return;
        set({ accent: color });
      },
    }),
    {
      name: "noxo-accent",
      merge: mergePersistedTheme,
      onRehydrateStorage: () => (state) => {
        if (state) applyTheme(state);
      },
    },
  ),
);

// Apply on module init and on every change (including rehydration).
applyTheme(useAccentStore.getState());
if (typeof document !== "undefined") {
  useAccentStore.subscribe((state) => applyTheme(state));
}

export function useAccent() {
  // Components use the accent for text/icons, so hand them the readable
  // variant. The store and useTheme() keep the raw picked color.
  return useAccentStore((state) => readableAccent(state.accent));
}

export function useTheme() {
  const themeId = useAccentStore((state) => state.themeId);
  const from = useAccentStore((state) => state.from);
  const to = useAccentStore((state) => state.to);
  const accent = useAccentStore((state) => state.accent);
  const angle = useAccentStore((state) => state.angle);

  return { themeId, from, to, accent, angle };
}

export function setAccent(color) {
  useAccentStore.getState().setAccent(color);
}

// ─── Random Nitro-style gradient ─────────────────────────────────────────────
// Harmonic dark palette: deep start, darker end, vibrant accent.

function hslToHex(h, s, l) {
  const hue = ((h % 360) + 360) % 360;
  const sat = Math.min(1, Math.max(0, s / 100));
  const light = Math.min(1, Math.max(0, l / 100));
  const c = (1 - Math.abs(2 * light - 1)) * sat;
  const x = c * (1 - Math.abs(((hue / 60) % 2) - 1));
  const m = light - c / 2;
  let r = 0;
  let g = 0;
  let b = 0;
  if (hue < 60) [r, g, b] = [c, x, 0];
  else if (hue < 120) [r, g, b] = [x, c, 0];
  else if (hue < 180) [r, g, b] = [0, c, x];
  else if (hue < 240) [r, g, b] = [0, x, c];
  else if (hue < 300) [r, g, b] = [x, 0, c];
  else [r, g, b] = [c, 0, x];
  const channel = (value) =>
    Math.round((value + m) * 255)
      .toString(16)
      .padStart(2, "0");
  return `#${channel(r)}${channel(g)}${channel(b)}`;
}

export function generateRandomTheme() {
  const hue = Math.random() * 360;
  const endHue = hue + (Math.random() * 80 - 40);
  const accentHue =
    Math.random() < 0.5
      ? hue + (Math.random() * 60 - 30)
      : hue + 180 + (Math.random() * 40 - 20);
  return {
    from: hslToHex(hue, 60 + Math.random() * 20, 12 + Math.random() * 6),
    to: hslToHex(endHue, 55 + Math.random() * 20, 4 + Math.random() * 4),
    accent: hslToHex(
      accentHue,
      90 + Math.random() * 10,
      58 + Math.random() * 10,
    ),
    angle: Math.round(120 + Math.random() * 40),
  };
}

export function randomizeTheme() {
  const theme = generateRandomTheme();
  useAccentStore.getState().setCustomTheme(theme);
  return theme;
}

export function setTheme(presetId) {
  useAccentStore.getState().setTheme(presetId);
}

export function setCustomTheme(theme) {
  useAccentStore.getState().setCustomTheme(theme);
}
