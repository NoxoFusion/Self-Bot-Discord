import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AFKFeature from "./AFKFeature";

const { getAfk, saveAfk } = vi.hoisted(() => ({
  getAfk: vi.fn(),
  saveAfk: vi.fn(),
}));

vi.mock("../../../lib/session", () => ({
  useSessionContext: () => ({
    loading: false,
    authenticated: true,
    csrf: "test-csrf",
  }),
}));

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    api: {
      getAfk,
      saveAfk,
    },
  };
});

const toast = {
  success: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
};

// Safe defaults when the backend omits the newer fields.
const FULL_PAYLOAD = {
  enabled: true,
  reason: "Busy",
  cooldown: 10,
  reply_mentions: true,
  reply_dms: true,
};

beforeEach(() => {
  vi.resetAllMocks();
  getAfk.mockResolvedValue({ enabled: true, reason: "Busy" });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("AFKFeature", () => {
  it("renders compact rule pills, presets, and the live preview", async () => {
    render(<AFKFeature toast={toast} />);

    expect(await screen.findByText("Quick presets")).toBeInTheDocument();
    expect(screen.getByText("Away Message")).toBeInTheDocument();
    expect(screen.getByText(/I am currently AFK: Busy/)).toBeInTheDocument();
    expect(screen.getByText("Mentions & DMs")).toBeInTheDocument();
    expect(screen.getByText("10s cooldown")).toBeInTheDocument();
    expect(screen.getByText("Bot filter")).toBeInTheDocument();
    expect(screen.queryByText("How it works")).not.toBeInTheDocument();
  });

  it("fills the away message and simulator from a preset", async () => {
    render(<AFKFeature toast={toast} />);

    const textarea = await screen.findByDisplayValue("Busy");
    fireEvent.click(screen.getByRole("button", { name: /Sleeping/ }));

    expect(textarea.value).toBe(
      "Sleeping now, I'll reply tomorrow. Good night!",
    );
    expect(
      screen.getByText(/I am currently AFK: Sleeping now/),
    ).toBeInTheDocument();
  });

  it("clamps the away message to 200 characters", async () => {
    render(<AFKFeature toast={toast} />);

    const textarea = await screen.findByDisplayValue("Busy");
    fireEvent.change(textarea, { target: { value: "x".repeat(250) } });

    expect(textarea.value).toHaveLength(200);
    expect(screen.getAllByText("200/200").length).toBeGreaterThan(0);
  });
});

describe("AFKFeature loading gate", () => {
  it("disables the master toggle until settings load", async () => {
    let resolveLoad;
    getAfk.mockReturnValue(
      new Promise((resolve) => {
        resolveLoad = resolve;
      }),
    );

    render(<AFKFeature toast={toast} />);

    const master = await screen.findByRole("switch", {
      name: "AFK master toggle",
    });
    expect(master).toBeDisabled();

    await act(async () => {
      resolveLoad({ enabled: true, reason: "Busy" });
    });

    await waitFor(() => expect(master).toBeEnabled());
  });
});

describe("AFKFeature toggle autosave", () => {
  it("autosaves the toggle off after the debounce", async () => {
    saveAfk.mockResolvedValue({ saved: true, applied: true });

    render(<AFKFeature toast={toast} />);
    await screen.findByDisplayValue("Busy");

    vi.useFakeTimers();
    fireEvent.click(
      screen.getByRole("switch", { name: "AFK master toggle" }),
    );

    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saving…");
    expect(saveAfk).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAfk).toHaveBeenCalledWith(
      { ...FULL_PAYLOAD, enabled: false },
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("flushes a pending toggle save when unmounted", async () => {
    saveAfk.mockResolvedValue({ saved: true, applied: true });

    const { unmount } = render(<AFKFeature toast={toast} />);
    await screen.findByDisplayValue("Busy");

    vi.useFakeTimers();
    fireEvent.click(
      screen.getByRole("switch", { name: "AFK master toggle" }),
    );
    expect(saveAfk).not.toHaveBeenCalled();

    unmount();

    expect(saveAfk).toHaveBeenCalledWith(
      { ...FULL_PAYLOAD, enabled: false },
      "test-csrf",
    );
  });

  it("reloads the saved toggle value after remount", async () => {
    saveAfk.mockImplementation(async (payload) => {
      getAfk.mockResolvedValue({
        enabled: payload.enabled,
        reason: payload.reason,
      });
      return { saved: true, applied: true };
    });

    const { unmount } = render(<AFKFeature toast={toast} />);
    await screen.findByDisplayValue("Busy");

    vi.useFakeTimers();
    fireEvent.click(
      screen.getByRole("switch", { name: "AFK master toggle" }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    vi.useRealTimers();

    expect(saveAfk).toHaveBeenCalledWith(
      { ...FULL_PAYLOAD, enabled: false },
      "test-csrf",
    );

    unmount();
    render(<AFKFeature toast={toast} />);

    await screen.findByDisplayValue("Busy");
    expect(
      screen.getByRole("switch", { name: "AFK master toggle" }),
    ).not.toBeChecked();
  });
});

describe("AFKFeature field autosave", () => {
  it("autosaves a typed away reason after the debounce", async () => {
    saveAfk.mockResolvedValue({ saved: true, applied: true });

    render(<AFKFeature toast={toast} />);
    const textarea = await screen.findByDisplayValue("Busy");

    vi.useFakeTimers();
    fireEvent.change(textarea, { target: { value: "Sleeping now" } });

    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saving…");
    expect(saveAfk).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAfk).toHaveBeenCalledWith(
      { ...FULL_PAYLOAD, reason: "Sleeping now" },
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("flushes a pending reason edit when unmounted", async () => {
    saveAfk.mockResolvedValue({ saved: true, applied: true });

    const { unmount } = render(<AFKFeature toast={toast} />);
    const textarea = await screen.findByDisplayValue("Busy");

    vi.useFakeTimers();
    fireEvent.change(textarea, { target: { value: "Flush me" } });
    expect(saveAfk).not.toHaveBeenCalled();

    unmount();

    expect(saveAfk).toHaveBeenCalledWith(
      { ...FULL_PAYLOAD, reason: "Flush me" },
      "test-csrf",
    );
  });
});

describe("AFKFeature cooldown and filter autosave", () => {
  it("autosaves a cooldown change after the debounce", async () => {
    saveAfk.mockResolvedValue({ saved: true, applied: true });

    render(<AFKFeature toast={toast} />);
    await screen.findByDisplayValue("Busy");
    const slider = screen.getByRole("slider");

    expect(slider).toHaveAttribute("min", "3");
    expect(slider).toHaveAttribute("max", "60");

    vi.useFakeTimers();
    fireEvent.change(slider, { target: { value: "30" } });

    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saving…");
    expect(saveAfk).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAfk).toHaveBeenCalledWith(
      { ...FULL_PAYLOAD, cooldown: 30 },
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("autosaves the mentions and DMs filter flags", async () => {
    saveAfk.mockResolvedValue({ saved: true, applied: true });

    render(<AFKFeature toast={toast} />);
    await screen.findByDisplayValue("Busy");

    vi.useFakeTimers();

    fireEvent.click(screen.getByRole("switch", { name: "Mentions" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAfk).toHaveBeenLastCalledWith(
      { ...FULL_PAYLOAD, reply_mentions: false },
      "test-csrf",
    );
    expect(screen.getByText("Replying to DMs only")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "DMs" }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAfk).toHaveBeenLastCalledWith(
      { ...FULL_PAYLOAD, reply_mentions: false, reply_dms: false },
      "test-csrf",
    );
    expect(screen.getByText("Auto reply off")).toBeInTheDocument();
  });

  it("shows the loaded cooldown and filters in the hero and subline", async () => {
    getAfk.mockResolvedValue({
      enabled: true,
      reason: "Busy",
      cooldown: 42,
      reply_mentions: true,
      reply_dms: false,
    });

    render(<AFKFeature toast={toast} />);

    expect(
      await screen.findByText("Replying to mentions only"),
    ).toBeInTheDocument();

    await waitFor(() => {
      const stats = screen.getByTestId("feature-hero-stats");
      expect(within(stats).getByText("42s")).toBeInTheDocument();
    });
  });
});

describe("AFKFeature empty reason guard", () => {
  it("does not enable AFK without a reason", async () => {
    getAfk.mockResolvedValue({ enabled: false, reason: "" });
    saveAfk.mockResolvedValue({ saved: true, applied: true });

    render(<AFKFeature toast={toast} />);
    const toggle = await screen.findByRole("switch", {
      name: "AFK master toggle",
    });
    await waitFor(() => expect(toggle).toBeEnabled());

    vi.useFakeTimers();
    fireEvent.click(toggle);

    expect(toggle).not.toBeChecked();
    expect(
      screen.getByText("Enter a reason before enabling AFK."),
    ).toBeInTheDocument();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(saveAfk).not.toHaveBeenCalled();
  });
});
