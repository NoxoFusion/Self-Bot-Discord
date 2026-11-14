import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  ACCENT_PRESETS,
  DEFAULT_ACCENT,
  DEFAULT_THEME_ID,
  SEMANTIC_COLORS,
  THEME_PRESETS,
  accentTextColor,
  applyTheme,
  contrastRatio,
  isValidHex,
  readableAccent,
  relativeLuminance,
  setAccent,
  setCustomTheme,
  setTheme,
  useAccent,
  useAccentStore,
  useTheme,
} from "./theme";

const STORAGE_KEY = "noxo-accent";
const DEFAULT_THEME = THEME_PRESETS[0];

const DEFAULT_STATE = {
  themeId: DEFAULT_THEME_ID,
  from: DEFAULT_THEME.from,
  to: DEFAULT_THEME.to,
  accent: DEFAULT_ACCENT,
  angle: DEFAULT_THEME.angle,
};

function cssVar(name) {
  return document.documentElement.style.getPropertyValue(name);
}

function resetTheme() {
  useAccentStore.setState({ ...DEFAULT_STATE });
}

async function loadFreshTheme() {
  vi.resetModules();
  return import("./theme");
}

beforeEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("style");
  resetTheme();
});

describe("THEME_PRESETS", () => {
  it("exposes the nine documented presets", () => {
    expect(DEFAULT_THEME_ID).toBe("midnight-blurple");
    expect(THEME_PRESETS.map((preset) => preset.id)).toEqual([
      "midnight-blurple",
      "chroma-glow",
      "retro-storm",
      "emerald-twilight",
      "strawberry-dusk",
      "oceanic-deep",
      "crimson-moon",
      "amber-sunset",
      "pure-obsidian",
    ]);

    expect(THEME_PRESETS[0]).toEqual({
      id: "midnight-blurple",
      name: "Midnight Blurple",
      from: "#1E1F38",
      to: "#0C0D1A",
      accent: "#5865F2",
      angle: 135,
    });

    for (const preset of THEME_PRESETS) {
      expect(preset.name).toEqual(expect.any(String));
      expect(isValidHex(preset.from)).toBe(true);
      expect(isValidHex(preset.to)).toBe(true);
      expect(isValidHex(preset.accent)).toBe(true);
      expect(preset.angle).toBeGreaterThanOrEqual(0);
      expect(preset.angle).toBeLessThanOrEqual(360);
    }
  });

  it("keeps the legacy accent presets available", () => {
    expect(ACCENT_PRESETS).toContainEqual({
      name: "Electric Cyan",
      value: "#06B6D4",
    });
  });
});

describe("setTheme", () => {
  it("applies a preset to state and to the document CSS variables", () => {
    setTheme("emerald-twilight");

    expect(useAccentStore.getState()).toMatchObject({
      themeId: "emerald-twilight",
      from: "#0D2818",
      to: "#040D0A",
      accent: "#10B981",
      angle: 135,
    });

    expect(cssVar("--accent")).toBe("#10B981");
    expect(cssVar("--bg-from")).toBe("#0D2818");
    expect(cssVar("--bg-to")).toBe("#040D0A");
    expect(cssVar("--bg-gradient")).toBe(
      "linear-gradient(135deg, #0D2818 0%, #040D0A 100%)",
    );
    expect(cssVar("--surface-glass")).toBe("rgba(16,20,30,0.66)");
    expect(cssVar("--surface-glass-strong")).toBe("rgba(16,20,30,0.82)");
    expect(cssVar("--surface-inset")).toBe("rgba(8,11,17,0.55)");
    expect(cssVar("--surface-solid")).toBe("#0E1219");
    expect(cssVar("--glass-border")).toBe("rgba(255,255,255,0.09)");
    expect(cssVar("--glass-highlight")).toBe("rgba(255,255,255,0.04)");
  });

  it("applies every preset exactly", () => {
    for (const preset of THEME_PRESETS) {
      setTheme(preset.id);

      expect(useAccentStore.getState()).toMatchObject({
        themeId: preset.id,
        from: preset.from,
        to: preset.to,
        accent: preset.accent,
        angle: preset.angle,
      });
      expect(cssVar("--accent")).toBe(preset.accent);
      expect(cssVar("--bg-gradient")).toBe(
        `linear-gradient(${preset.angle}deg, ${preset.from} 0%, ${preset.to} 100%)`,
      );
    }
  });

  it("ignores unknown preset ids", () => {
    setTheme("midnight-blurple");
    setTheme("not-a-real-theme");

    expect(useAccentStore.getState().themeId).toBe("midnight-blurple");
  });
});

describe("setCustomTheme", () => {
  it("stores a custom gradient and clamps the angle to 0-360", () => {
    setCustomTheme({
      from: "#112233",
      to: "#445566",
      accent: "#ABCDEF",
      angle: 400,
    });

    expect(useAccentStore.getState()).toMatchObject({
      themeId: "custom",
      from: "#112233",
      to: "#445566",
      accent: "#ABCDEF",
      angle: 360,
    });
    expect(cssVar("--bg-gradient")).toBe(
      "linear-gradient(360deg, #112233 0%, #445566 100%)",
    );

    setCustomTheme({
      from: "#112233",
      to: "#445566",
      accent: "#ABCDEF",
      angle: -20,
    });

    expect(useAccentStore.getState().angle).toBe(0);
    expect(cssVar("--bg-gradient")).toBe(
      "linear-gradient(0deg, #112233 0%, #445566 100%)",
    );
  });

  it("rejects invalid hex colors without changing state", () => {
    setTheme("retro-storm");
    const before = useAccentStore.getState();

    const invalidPayloads = [
      { from: "nope", to: "#445566", accent: "#ABCDEF", angle: 90 },
      { from: "#112233", to: "#12345", accent: "#ABCDEF", angle: 90 },
      { from: "#112233", to: "#445566", accent: "rgb(1,2,3)", angle: 90 },
    ];

    for (const payload of invalidPayloads) {
      setCustomTheme(payload);

      expect(useAccentStore.getState()).toMatchObject({
        themeId: before.themeId,
        from: before.from,
        to: before.to,
        accent: before.accent,
        angle: before.angle,
      });
    }
  });

  it("keeps the current angle when the supplied angle is not numeric", () => {
    setTheme("crimson-moon");

    setCustomTheme({
      from: "#112233",
      to: "#445566",
      accent: "#ABCDEF",
      angle: "sideways",
    });

    expect(useAccentStore.getState()).toMatchObject({
      themeId: "custom",
      angle: 150,
    });
  });
});

describe("setAccent", () => {
  it("changes only the accent and keeps the active gradient", () => {
    setTheme("chroma-glow");
    const gradient = cssVar("--bg-gradient");

    setAccent("#123456");

    expect(useAccentStore.getState()).toMatchObject({
      themeId: "chroma-glow",
      from: "#2A1145",
      to: "#0B1A30",
      accent: "#123456",
      angle: 135,
    });
    expect(cssVar("--accent")).toBe("#123456");
    expect(cssVar("--bg-gradient")).toBe(gradient);
  });

  it("ignores invalid accents", () => {
    setTheme("midnight-blurple");
    setAccent("blue");

    expect(useAccentStore.getState().accent).toBe("#5865F2");
  });
});

describe("useTheme", () => {
  it("exposes the full active theme and updates with the store", () => {
    const { result } = renderHook(() => useTheme());

    expect(result.current).toEqual(DEFAULT_STATE);

    act(() => setTheme("oceanic-deep"));

    expect(result.current).toEqual({
      themeId: "oceanic-deep",
      from: "#062038",
      to: "#040D18",
      accent: "#38BDF8",
      angle: 135,
    });
  });
});

describe("accent contrast helpers", () => {
  it("computes WCAG luminance and contrast ratios", () => {
    expect(relativeLuminance("#FFFFFF")).toBeCloseTo(1, 5);
    expect(relativeLuminance("#000000")).toBeCloseTo(0, 5);
    expect(contrastRatio("#FFFFFF", "#000000")).toBeCloseTo(21, 1);
    expect(contrastRatio("#0E1219", "#0E1219")).toBeCloseTo(1, 5);
  });

  it("lightens a dark accent until it is readable on the dark surface", () => {
    const readable = readableAccent("#123456");

    expect(readable).not.toBe("#123456");
    expect(isValidHex(readable)).toBe(true);
    expect(contrastRatio(readable, "#0E1219")).toBeGreaterThanOrEqual(3);
  });

  it("leaves an already readable accent untouched", () => {
    expect(readableAccent(DEFAULT_ACCENT)).toBe(DEFAULT_ACCENT);
    expect(readableAccent("#F59E0B")).toBe("#F59E0B");
  });

  it("falls back to the default accent for invalid input", () => {
    expect(readableAccent("not-a-color")).toBe(DEFAULT_ACCENT);
    expect(readableAccent(undefined)).toBe(DEFAULT_ACCENT);
  });

  it("picks dark or white text based on the accent's contrast", () => {
    expect(accentTextColor("#F59E0B")).toBe("#0B0E14");
    expect(accentTextColor("#5865F2")).toBe("#FFFFFF");
    expect(accentTextColor("#0B0E14")).toBe("#FFFFFF");
  });

  it("keeps --accent exact while exposing readable accent tokens", () => {
    applyTheme({ ...DEFAULT_STATE, accent: "#123456" });

    expect(cssVar("--accent")).toBe("#123456");
    expect(cssVar("--accent-readable")).toBe(readableAccent("#123456"));
    expect(cssVar("--accent-contrast")).toBe(accentTextColor("#123456"));
  });

  it("exposes the semantic status colors", () => {
    expect(SEMANTIC_COLORS).toEqual({
      info: "#58B8E8",
      success: "#23A55A",
      warn: "#F5B642",
      danger: "#F23F43",
      blurple: "#5865F2",
    });
  });
});

describe("useAccent", () => {
  it("returns the readable variant for a dark accent", () => {
    setAccent("#123456");
    const { result } = renderHook(() => useAccent());

    expect(useAccentStore.getState().accent).toBe("#123456");
    expect(cssVar("--accent")).toBe("#123456");
    expect(result.current).toBe(readableAccent("#123456"));
    expect(result.current).not.toBe("#123456");
    expect(contrastRatio(result.current, "#0E1219")).toBeGreaterThanOrEqual(3);
  });

  it("returns the raw accent when it is already readable", () => {
    setAccent(DEFAULT_ACCENT);
    const { result } = renderHook(() => useAccent());

    expect(result.current).toBe(DEFAULT_ACCENT);
  });
});

describe("persistence", () => {
  it("migrates a legacy accent-only value to a custom theme", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ state: { accent: "#06B6D4" }, version: 0 }),
    );

    const theme = await loadFreshTheme();

    expect(theme.useAccentStore.getState()).toMatchObject({
      themeId: "custom",
      from: "#1E1F38",
      to: "#0C0D1A",
      accent: "#06B6D4",
      angle: 135,
    });
    expect(cssVar("--accent")).toBe("#06B6D4");
    expect(cssVar("--bg-gradient")).toBe(
      "linear-gradient(135deg, #1E1F38 0%, #0C0D1A 100%)",
    );
  });

  it("restores a persisted gradient theme", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        state: {
          themeId: "crimson-moon",
          from: "#360D16",
          to: "#0F0407",
          accent: "#EF4444",
          angle: 150,
        },
        version: 0,
      }),
    );

    const theme = await loadFreshTheme();

    expect(theme.useAccentStore.getState()).toMatchObject({
      themeId: "crimson-moon",
      from: "#360D16",
      to: "#0F0407",
      accent: "#EF4444",
      angle: 150,
    });
    expect(cssVar("--bg-gradient")).toBe(
      "linear-gradient(150deg, #360D16 0%, #0F0407 100%)",
    );
  });

  it("falls back to defaults for invalid persisted values", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        state: {
          themeId: "not-a-theme",
          from: "blue",
          to: "#12345",
          accent: "nope",
          angle: "sideways",
        },
        version: 0,
      }),
    );

    const theme = await loadFreshTheme();

    expect(theme.useAccentStore.getState()).toMatchObject(DEFAULT_STATE);
    expect(cssVar("--accent")).toBe("#5865F2");
    expect(cssVar("--bg-gradient")).toBe(
      "linear-gradient(135deg, #1E1F38 0%, #0C0D1A 100%)",
    );
  });
});
