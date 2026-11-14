import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import SettingsView from "./SettingsView";
import {
  DEFAULT_THEME_ID,
  THEME_PRESETS,
  useAccentStore,
} from "../../../lib/theme";

const {
  getSettings,
  getStatus,
  savePrefix,
  requestReload,
  logout,
  sessionState,
} = vi.hoisted(() => ({
  getSettings: vi.fn(),
  getStatus: vi.fn(),
  savePrefix: vi.fn(),
  requestReload: vi.fn(),
  logout: vi.fn(),
  sessionState: {
    loading: false,
    authenticated: true,
    csrf: "test-csrf",
    error: null,
  },
}));

vi.mock("../../../lib/session", () => ({
  useSessionContext: () => ({ ...sessionState, logout }),
}));

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    api: {
      ...actual.api,
      getSettings,
      getStatus,
      savePrefix,
      requestReload,
    },
  };
});

const PROFILE = {
  username: "alice",
  display_name: "Alice",
  user_id: "123456789012345678",
  avatar_url: "https://cdn.example/alice.png",
  banner_url: null,
  accent_color: null,
  created_at: "2015-12-07T16:13:12.216000+00:00",
  premium_type: 2,
  badges: [{ id: "staff", label: "Discord Staff" }],
};

const STATUS = {
  bot: { state: "online", guild_count: 12 },
  last_reload: {
    at: "2026-01-01T00:00:00.000Z",
    ok: true,
    detail: "Initial reload",
  },
};

function makeToast() {
  return {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
  };
}

beforeEach(() => {
  vi.resetAllMocks();

  sessionState.loading = false;
  sessionState.authenticated = true;
  sessionState.csrf = "test-csrf";
  sessionState.error = null;

  logout.mockResolvedValue(undefined);
  getSettings.mockResolvedValue({ prefix: "36", profile: PROFILE });
  getStatus.mockResolvedValue(STATUS);
  savePrefix.mockResolvedValue({
    saved: true,
    prefix: "!",
    reload_requested: true,
  });
  requestReload.mockResolvedValue({ requested: true });

  const defaultTheme = THEME_PRESETS[0];
  useAccentStore.setState({
    themeId: DEFAULT_THEME_ID,
    from: defaultTheme.from,
    to: defaultTheme.to,
    accent: defaultTheme.accent,
    angle: defaultTheme.angle,
  });
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("SettingsView", () => {
  it("renders the profile display name, username, and user ID", async () => {
    render(<SettingsView toast={makeToast()} />);

    expect(await screen.findByText("Alice")).toBeInTheDocument();
    expect(screen.getByText("@alice")).toBeInTheDocument();
    expect(screen.getByText("123456789012345678")).toBeInTheDocument();
    expect(screen.getByText("Discord Staff")).toBeInTheDocument();
    expect(screen.getByText("Nitro")).toBeInTheDocument();
  });

  it("loads the prefix and saves a changed prefix with csrf", async () => {
    const toast = makeToast();
    render(<SettingsView toast={toast} />);

    const input = await screen.findByLabelText("Command prefix");
    expect(input).toHaveValue("36");

    const save = screen.getByRole("button", { name: "Save prefix" });
    expect(save).toBeDisabled();

    fireEvent.change(input, { target: { value: "!" } });
    expect(save).not.toBeDisabled();

    fireEvent.click(save);

    await waitFor(() => {
      expect(savePrefix).toHaveBeenCalledWith("!", "test-csrf");
    });
    await waitFor(() => {
      expect(toast.success).toHaveBeenCalledWith(
        "Prefix updated — applied within 2 seconds",
        "Settings",
      );
    });
  });

  it("requests a reload and polls until the last reload changes", async () => {
    getStatus
      .mockResolvedValueOnce(STATUS)
      .mockResolvedValue({
        bot: { state: "online", guild_count: 12 },
        last_reload: {
          at: "2026-01-01T00:00:05.000Z",
          ok: true,
          detail: "Config and cogs reloaded.",
        },
      });

    render(<SettingsView toast={makeToast()} />);

    await screen.findByText("Alice");
    await waitFor(() => expect(getStatus).toHaveBeenCalledTimes(1));

    fireEvent.click(
      screen.getByRole("button", { name: "Reload config and cogs" }),
    );

    const dialog = await screen.findByRole("alertdialog", {
      name: "Reload config and cogs?",
    });
    expect(requestReload).not.toHaveBeenCalled();
    fireEvent.click(within(dialog).getByRole("button", { name: "Reload" }));

    await waitFor(() => {
      expect(requestReload).toHaveBeenCalledWith("test-csrf");
    });
    expect(
      await screen.findByText("Config and cogs reloaded."),
    ).toBeInTheDocument();
  });

  it("asks for confirmation before unpairing the session", async () => {
    render(<SettingsView toast={makeToast()} />);

    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Unpair session" }));

    const dialog = await screen.findByRole("alertdialog", {
      name: "Unpair this browser?",
    });
    expect(logout).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Unpair" }));

    await waitFor(() => expect(logout).toHaveBeenCalledTimes(1));
  });

  it("renders a safe fallback when the profile is unavailable", async () => {
    getSettings.mockResolvedValue({ prefix: "!", profile: null });

    render(<SettingsView toast={makeToast()} />);

    await waitFor(() => expect(getSettings).toHaveBeenCalled());
    expect(screen.getAllByText("Profile unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText(/check the bot token/i)).toBeInTheDocument();
  });

  it("applies a preset theme card to the theme store", async () => {
    render(<SettingsView toast={makeToast()} />);

    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Customize theme" }));
    const preset = THEME_PRESETS[1];
    fireEvent.click(
      screen.getByRole("button", { name: `Use ${preset.name} theme` }),
    );

    const state = useAccentStore.getState();
    expect(state.themeId).toBe(preset.id);
    expect(state.accent).toBe(preset.accent);
    expect(state.from).toBe(preset.from);
    expect(state.to).toBe(preset.to);
    expect(state.angle).toBe(preset.angle);
  });

  it("applies a custom gradient live from the studio", async () => {
    render(<SettingsView toast={makeToast()} />);

    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Customize theme" }));
    fireEvent.change(screen.getByLabelText("Gradient start hex"), {
      target: { value: "#112233" },
    });

    // No Apply button: a valid edit is persisted immediately.
    expect(useAccentStore.getState().themeId).toBe("custom");
    expect(useAccentStore.getState().from).toBe("#112233");

    fireEvent.change(screen.getByLabelText("Gradient end hex"), {
      target: { value: "#445566" },
    });
    fireEvent.change(screen.getByLabelText("Accent color hex"), {
      target: { value: "#778899" },
    });
    fireEvent.change(screen.getByLabelText("Gradient angle"), {
      target: { value: "220" },
    });

    const state = useAccentStore.getState();
    expect(state.themeId).toBe("custom");
    expect(state.from).toBe("#112233");
    expect(state.to).toBe("#445566");
    expect(state.accent).toBe("#778899");
    expect(state.angle).toBe(220);
    expect(screen.getByText("Custom")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Apply custom theme" }),
    ).not.toBeInTheDocument();
  });

  it("shows an error and does not apply an invalid custom hex", async () => {
    render(<SettingsView toast={makeToast()} />);

    await screen.findByText("Alice");
    fireEvent.click(screen.getByRole("button", { name: "Customize theme" }));
    fireEvent.change(screen.getByLabelText("Gradient start hex"), {
      target: { value: "#12" },
    });

    expect(screen.getByRole("alert")).toHaveTextContent(
      /6-digit hex color/i,
    );
    const state = useAccentStore.getState();
    expect(state.themeId).toBe(DEFAULT_THEME_ID);
    expect(state.from).toBe(THEME_PRESETS[0].from);
  });

  it("randomizes a fresh gradient from the theme card", async () => {
    render(<SettingsView toast={makeToast()} />);

    await screen.findByText("Alice");
    fireEvent.click(
      screen.getByRole("button", { name: "Randomize gradient" }),
    );

    const state = useAccentStore.getState();
    expect(state.themeId).toBe("custom");
    expect(state.from).toMatch(/^#[0-9a-fA-F]{6}$/);
    expect(state.to).toMatch(/^#[0-9a-fA-F]{6}$/);
    expect(state.accent).toMatch(/^#[0-9a-fA-F]{6}$/);
  });

  it("opens the theme studio drawer and closes it with Escape", async () => {
    render(<SettingsView toast={makeToast()} />);

    await screen.findByText("Alice");
    expect(
      screen.queryByRole("dialog", { name: "Theme studio" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Customize theme" }));
    expect(
      screen.getByRole("dialog", { name: "Theme studio" }),
    ).toBeInTheDocument();

    fireEvent.keyDown(window, { key: "Escape" });
    expect(
      screen.queryByRole("dialog", { name: "Theme studio" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the theme studio hidden until it is opened", async () => {
    render(<SettingsView toast={makeToast()} />);

    await screen.findByText("Alice");
    const closedDrawer = screen
      .getByText("Theme studio")
      .closest('[role="dialog"]');
    expect(closedDrawer).toHaveStyle({ visibility: "hidden" });

    fireEvent.click(screen.getByRole("button", { name: "Customize theme" }));

    const openDrawer = screen
      .getByText("Theme studio")
      .closest('[role="dialog"]');
    expect(openDrawer).toHaveStyle({ visibility: "visible" });
  });

  it("shows a minimal notice instead of a pairing form when unauthenticated", () => {
    sessionState.authenticated = false;

    render(<SettingsView toast={makeToast()} />);

    expect(screen.getByText("Not paired")).toBeInTheDocument();
    expect(
      screen.getByText(/Pair this dashboard from the banner above/i),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText("Pairing code")).not.toBeInTheDocument();
    expect(getSettings).not.toHaveBeenCalled();
    expect(getStatus).not.toHaveBeenCalled();
  });
});
