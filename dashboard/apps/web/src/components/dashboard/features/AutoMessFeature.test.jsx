import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import AutoMessFeature from "./AutoMessFeature";

const { getAutomation, saveAutomation } = vi.hoisted(() => ({
  getAutomation: vi.fn(),
  saveAutomation: vi.fn(),
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
      getAutomation,
      saveAutomation,
    },
  };
});

const baseAutomation = {
  enabled: true,
  triggers: [],
  broadcaster: {
    enabled: true,
    mode: "time",
    value: 60,
    channel_id: "",
  },
  pool: [],
};

const toast = {
  success: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  getAutomation.mockResolvedValue(baseAutomation);
});

afterEach(() => {
  vi.useRealTimers();
});

const waitForLoad = () =>
  waitFor(() =>
    expect(
      screen.queryByText("Loading Smart Auto Mess settings…"),
    ).not.toBeInTheDocument(),
  );

describe("AutoMessFeature broadcaster limits", () => {
  it("uses the backend time bounds", async () => {
    render(<AutoMessFeature toast={toast} />);

    const slider = await screen.findByRole("slider");
    expect(slider).toHaveAttribute("min", "30");
    expect(slider).toHaveAttribute("max", "600");
  });

  it("keeps message mode at 1-50 and caps items at 5", async () => {
    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    fireEvent.click(screen.getByText("Every N msgs").closest("button"));

    expect(screen.getByRole("slider")).toHaveAttribute("min", "1");
    expect(screen.getByRole("slider")).toHaveAttribute("max", "50");
    expect(screen.getByTitle("Add trigger")).toBeInTheDocument();
    const triggersPanel = screen
      .getByText("Keyword Triggers")
      .closest(".rounded-2xl");
    expect(within(triggersPanel).getByText("0/5")).toBeInTheDocument();
  });

  it("clamps a stored time below 30 to the UI minimum", async () => {
    getAutomation.mockResolvedValue({
      ...baseAutomation,
      broadcaster: { ...baseAutomation.broadcaster, value: 10 },
    });

    render(<AutoMessFeature toast={toast} />);

    const slider = await screen.findByRole("slider");
    expect(slider.value).toBe("30");
  });
});

describe("AutoMessFeature loading gate", () => {
  it("disables the master toggle until settings load", async () => {
    let resolveLoad;
    getAutomation.mockReturnValue(
      new Promise((resolve) => {
        resolveLoad = resolve;
      }),
    );

    render(<AutoMessFeature toast={toast} />);

    const master = await screen.findByRole("switch", {
      name: "Smart Auto Mess master toggle",
    });
    expect(master).toBeDisabled();

    await act(async () => {
      resolveLoad(baseAutomation);
    });

    await waitFor(() => expect(master).toBeEnabled());
  });
});

describe("AutoMessFeature toggle autosave", () => {
  it("autosaves the master toggle off after the debounce", async () => {
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    vi.useFakeTimers();
    fireEvent.click(screen.getAllByRole("switch", { checked: true })[0]);

    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saving…");
    expect(saveAutomation).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAutomation).toHaveBeenCalledWith(
      {
        enabled: false,
        triggers: [],
        broadcaster: {
          enabled: true,
          mode: "time",
          value: 60,
          channel_id: "",
        },
        pool: [],
      },
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("flushes a pending toggle save when unmounted", async () => {
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    const { unmount } = render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    vi.useFakeTimers();
    fireEvent.click(screen.getAllByRole("switch", { checked: true })[0]);
    expect(saveAutomation).not.toHaveBeenCalled();

    unmount();

    expect(saveAutomation).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: false }),
      "test-csrf",
    );
  });

  it("reloads the saved toggle value after remount", async () => {
    saveAutomation.mockImplementation(async (payload) => {
      getAutomation.mockResolvedValue({
        ...baseAutomation,
        enabled: payload.enabled,
        triggers: [{ keyword: "saved", reply: "value" }],
      });
      return { saved: true, applied: true };
    });

    const { unmount } = render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    vi.useFakeTimers();
    fireEvent.click(screen.getAllByRole("switch", { checked: true })[0]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    vi.useRealTimers();

    expect(saveAutomation).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: false }),
      "test-csrf",
    );

    unmount();
    render(<AutoMessFeature toast={toast} />);

    expect(await screen.findByDisplayValue("saved")).toBeInTheDocument();
    expect(screen.getAllByRole("switch", { checked: false })).toHaveLength(1);
  });
});

describe("AutoMessFeature field autosave", () => {
  const withTrigger = {
    ...baseAutomation,
    triggers: [{ keyword: "hi", reply: "hello" }],
  };

  it("autosaves an edited trigger after the debounce", async () => {
    getAutomation.mockResolvedValue(withTrigger);
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    render(<AutoMessFeature toast={toast} />);
    const keyword = await screen.findByDisplayValue("hi");

    vi.useFakeTimers();
    fireEvent.change(keyword, { target: { value: "hey" } });

    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saving…");
    expect(saveAutomation).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAutomation).toHaveBeenCalledWith(
      {
        enabled: true,
        triggers: [{ keyword: "hey", reply: "hello" }],
        broadcaster: {
          enabled: true,
          mode: "time",
          value: 60,
          channel_id: "",
        },
        pool: [],
      },
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("autosaves a new pool message after the debounce", async () => {
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    vi.useFakeTimers();
    fireEvent.change(screen.getByPlaceholderText("New message…"), {
      target: { value: "yo" },
    });
    fireEvent.click(screen.getByTitle("Add message"));

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAutomation).toHaveBeenCalledWith(
      expect.objectContaining({ pool: ["yo"] }),
      "test-csrf",
    );
  });

  it("caps a new pool message at 200 characters", async () => {
    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    const input = screen.getByPlaceholderText("New message…");
    expect(input).toHaveAttribute("maxlength", "200");

    fireEvent.change(input, { target: { value: "x".repeat(250) } });
    expect(input.value).toHaveLength(200);
  });

  it("flushes a pending trigger edit when unmounted", async () => {
    getAutomation.mockResolvedValue(withTrigger);
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    const { unmount } = render(<AutoMessFeature toast={toast} />);
    const keyword = await screen.findByDisplayValue("hi");

    vi.useFakeTimers();
    fireEvent.change(keyword, { target: { value: "flushed" } });
    expect(saveAutomation).not.toHaveBeenCalled();

    unmount();

    expect(saveAutomation).toHaveBeenCalledWith(
      expect.objectContaining({
        triggers: [{ keyword: "flushed", reply: "hello" }],
      }),
      "test-csrf",
    );
  });
});

describe("AutoMessFeature message mode", () => {
  it("autosaves message mode with a sensible default value", async () => {
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    vi.useFakeTimers();
    fireEvent.click(screen.getByText("Every N msgs").closest("button"));

    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saving…");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAutomation).toHaveBeenCalledWith(
      expect.objectContaining({
        broadcaster: expect.objectContaining({ mode: "message", value: 5 }),
      }),
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("maps a legacy count mode to message on load", async () => {
    getAutomation.mockResolvedValue({
      ...baseAutomation,
      broadcaster: {
        ...baseAutomation.broadcaster,
        mode: "count",
        value: 5,
      },
    });

    render(<AutoMessFeature toast={toast} />);

    const slider = await screen.findByRole("slider");
    expect(slider).toHaveAttribute("min", "1");
    expect(slider).toHaveAttribute("max", "50");
  });
});

describe("AutoMessFeature broadcaster readiness", () => {
  it("auto-enables the master toggle when the broadcaster is turned on", async () => {
    getAutomation.mockResolvedValue({
      ...baseAutomation,
      enabled: false,
      broadcaster: { ...baseAutomation.broadcaster, enabled: false },
    });
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    vi.useFakeTimers();
    fireEvent.click(screen.getAllByRole("switch")[1]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAutomation).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled: true,
        broadcaster: expect.objectContaining({ enabled: true }),
      }),
      "test-csrf",
    );
  });

  it("explains that the master toggle is required", async () => {
    getAutomation.mockResolvedValue({
      ...baseAutomation,
      enabled: false,
      broadcaster: {
        ...baseAutomation.broadcaster,
        enabled: true,
        channel_id: "123",
      },
      pool: ["hi"],
    });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    expect(
      screen.getByText(
        "Paused — enable Smart Auto Mess above.",
      ),
    ).toBeInTheDocument();
    expect(
      within(screen.getByTestId("feature-hero-stats")).getByText("PAUSED"),
    ).toBeInTheDocument();
  });

  it("flags a missing channel ID", async () => {
    getAutomation.mockResolvedValue({
      ...baseAutomation,
      broadcaster: {
        ...baseAutomation.broadcaster,
        enabled: true,
        channel_id: "",
      },
      pool: ["hi"],
    });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    expect(
      screen.getByText("Needs a numeric channel ID."),
    ).toBeInTheDocument();
  });

  it("flags an empty message pool", async () => {
    getAutomation.mockResolvedValue({
      ...baseAutomation,
      broadcaster: {
        ...baseAutomation.broadcaster,
        enabled: true,
        channel_id: "123",
      },
      pool: [],
    });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    expect(
      screen.getByText("Needs at least one pool message."),
    ).toBeInTheDocument();
  });

  it("reports an active broadcaster", async () => {
    getAutomation.mockResolvedValue({
      ...baseAutomation,
      broadcaster: {
        ...baseAutomation.broadcaster,
        enabled: true,
        channel_id: "123",
        mode: "time",
        value: 60,
      },
      pool: ["hi"],
    });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    expect(
      screen.getByText("Active — every 60s."),
    ).toBeInTheDocument();
  });
});

describe("AutoMessFeature empty trigger rows", () => {
  it("omits an empty trigger row from the autosave payload", async () => {
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    vi.useFakeTimers();
    fireEvent.click(screen.getByTitle("Add trigger"));
    fireEvent.click(screen.getAllByRole("switch", { checked: true })[0]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAutomation).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: false, triggers: [] }),
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("still sends a filled trigger row and caps its fields", async () => {
    saveAutomation.mockResolvedValue({ saved: true, applied: true });

    render(<AutoMessFeature toast={toast} />);
    await waitForLoad();

    vi.useFakeTimers();
    fireEvent.click(screen.getByTitle("Add trigger"));

    const keyword = screen.getByPlaceholderText("keyword");
    const reply = screen.getByPlaceholderText("reply");
    expect(keyword).toHaveAttribute("maxlength", "100");
    expect(reply).toHaveAttribute("maxlength", "500");

    fireEvent.change(keyword, { target: { value: "hi" } });
    fireEvent.change(reply, { target: { value: "hello" } });
    fireEvent.click(screen.getAllByRole("switch", { checked: true })[0]);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveAutomation).toHaveBeenCalledWith(
      expect.objectContaining({
        enabled: false,
        triggers: [{ keyword: "hi", reply: "hello" }],
      }),
      "test-csrf",
    );
  });
});
