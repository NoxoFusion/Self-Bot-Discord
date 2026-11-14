import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import ReactionsFeature from "./ReactionsFeature";

const { getReactions, saveReactions } = vi.hoisted(() => ({
  getReactions: vi.fn(),
  saveReactions: vi.fn(),
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
      getReactions,
      saveReactions,
    },
  };
});

const baseReactions = {
  enabled: true,
  target: "user",
  user_id: "123456789012345678",
  channel_id: "",
  emojis: ["<:lamdieu:1547630841172066410>"],
};

const toast = {
  success: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
};

beforeEach(() => {
  vi.clearAllMocks();
  getReactions.mockResolvedValue(baseReactions);
});

afterEach(() => {
  vi.useRealTimers();
});

describe("ReactionsFeature emoji palette", () => {
  it("renders a custom emoji from the Discord CDN with its name", async () => {
    render(<ReactionsFeature toast={toast} />);

    const images = await screen.findAllByAltText(":lamdieu:");
    expect(images[0]).toHaveAttribute(
      "src",
      "https://cdn.discordapp.com/emojis/1547630841172066410.png?size=48&quality=lossless",
    );
    expect(screen.getByText(":lamdieu:")).toBeInTheDocument();
  });

  it("uses the animated CDN endpoint for animated custom emojis", async () => {
    getReactions.mockResolvedValue({
      ...baseReactions,
      emojis: ["<a:party:123456789012345678>"],
    });

    render(<ReactionsFeature toast={toast} />);

    const images = await screen.findAllByAltText(":party:");
    expect(images[0].getAttribute("src")).toContain(
      "/emojis/123456789012345678.gif",
    );
  });

  it("falls back to a clean name chip when the CDN image fails", async () => {
    render(<ReactionsFeature toast={toast} />);

    const name = await screen.findByText(":lamdieu:");
    const chip = name.parentElement;
    const image = within(chip).getByAltText(":lamdieu:");
    fireEvent.error(image);

    await waitFor(() => {
      expect(within(chip).queryByAltText(":lamdieu:")).not.toBeInTheDocument();
    });
    expect(within(chip).getAllByText(":lamdieu:").length).toBeGreaterThan(0);
  });

  it("adds a pasted custom emoji to Selected and clears the draft", async () => {
    getReactions.mockResolvedValue({ ...baseReactions, emojis: [] });

    render(<ReactionsFeature toast={toast} />);
    await screen.findByText("No emojis selected");

    const input = screen.getByPlaceholderText("<:name:id> or <a:name:id>");
    fireEvent.change(input, {
      target: { value: "<:lamdieu:1547630841172066410>" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add/i }));

    const images = await screen.findAllByAltText(":lamdieu:");
    expect(images.length).toBeGreaterThanOrEqual(1);
    expect(screen.getByText(":lamdieu:")).toBeInTheDocument();
    expect(input.value).toBe("");
  });

  it("appends a second custom emoji without replacing the first", async () => {
    render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    const input = screen.getByPlaceholderText("<:name:id> or <a:name:id>");
    fireEvent.change(input, {
      target: { value: "<a:party:123456789012345678>" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add/i }));

    await screen.findAllByAltText(":party:");
    expect(screen.getByText(":lamdieu:")).toBeInTheDocument();
    expect(screen.getByText(":party:")).toBeInTheDocument();
    expect(input.value).toBe("");
  });

  it("rejects empty and malformed custom emoji drafts", async () => {
    getReactions.mockResolvedValue({ ...baseReactions, emojis: [] });

    render(<ReactionsFeature toast={toast} />);
    await screen.findByText("No emojis selected");

    const add = screen.getByRole("button", { name: /Add/i });
    fireEvent.click(add);
    expect(
      screen.getByText("Paste a custom emoji first."),
    ).toBeInTheDocument();

    const input = screen.getByPlaceholderText("<:name:id> or <a:name:id>");
    fireEvent.change(input, { target: { value: "not-an-emoji" } });
    fireEvent.click(add);
    expect(
      screen.getByText("Use a valid Discord custom emoji."),
    ).toBeInTheDocument();
    expect(screen.getByText("No emojis selected")).toBeInTheDocument();
  });

  it("does not add the same custom emoji twice", async () => {
    render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    const input = screen.getByPlaceholderText("<:name:id> or <a:name:id>");
    fireEvent.change(input, {
      target: { value: "<:lamdieu:1547630841172066410>" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add/i }));

    expect(
      await screen.findByText("That emoji is already selected."),
    ).toBeInTheDocument();
    expect(screen.getAllByText(":lamdieu:")).toHaveLength(1);
  });

  it("keeps 10 selected emojis and rejects an 11th", async () => {
    const ten = Array.from(
      { length: 10 },
      (_, i) => `<:e${i}:${100000000000000000 + i}>`,
    );
    getReactions.mockResolvedValue({ ...baseReactions, emojis: ten });

    render(<ReactionsFeature toast={toast} />);
    await screen.findByText(":e0:");

    const input = screen.getByPlaceholderText("<:name:id> or <a:name:id>");
    fireEvent.change(input, {
      target: { value: "<:extra:999999999999999999>" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Add/i }));

    expect(await screen.findByText("Max 10 emojis.")).toBeInTheDocument();
    expect(screen.getAllByText(/^:e\d+:$/)).toHaveLength(10);
  });

  it("places Live Preview after Target and removes the old pipeline", async () => {
    render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    const live = screen.getByText("Live Preview");
    const target = screen
      .getAllByText("Target")
      .find((element) => element.className.includes("text-base"));

    expect(screen.queryByText("Reaction Pipeline")).not.toBeInTheDocument();
    expect(target).toBeTruthy();
    expect(
      target.compareDocumentPosition(live) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(screen.getByText("Selected")).toBeInTheDocument();
    expect(screen.getByText("Quick pick")).toBeInTheDocument();
    expect(screen.getByText("Custom emoji")).toBeInTheDocument();
  });
});

describe("ReactionsFeature loading gate", () => {
  it("disables the master toggle until settings load", async () => {
    let resolveLoad;
    getReactions.mockReturnValue(
      new Promise((resolve) => {
        resolveLoad = resolve;
      }),
    );

    render(<ReactionsFeature toast={toast} />);

    const master = await screen.findByRole("switch", {
      name: "Auto Reactions master toggle",
    });
    expect(master).toBeDisabled();

    await act(async () => {
      resolveLoad(baseReactions);
    });

    await waitFor(() => expect(master).toBeEnabled());
  });
});

describe("ReactionsFeature toggle autosave", () => {
  it("autosaves the master toggle off after the debounce", async () => {
    saveReactions.mockResolvedValue({ saved: true, applied: true });

    render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("switch", { checked: true }));

    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saving…");
    expect(saveReactions).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveReactions).toHaveBeenCalledWith(
      {
        enabled: false,
        target: "user",
        user_id: "123456789012345678",
        channel_id: "",
        emojis: ["<:lamdieu:1547630841172066410>"],
        cooldown: 3,
      },
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("flushes a pending toggle save when unmounted", async () => {
    saveReactions.mockResolvedValue({ saved: true, applied: true });

    const { unmount } = render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("switch", { checked: true }));
    expect(saveReactions).not.toHaveBeenCalled();

    unmount();

    expect(saveReactions).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: false }),
      "test-csrf",
    );
  });

  it("reloads the saved toggle value after remount", async () => {
    saveReactions.mockImplementation(async (payload) => {
      getReactions.mockResolvedValue({
        ...baseReactions,
        enabled: payload.enabled,
      });
      return { saved: true, applied: true };
    });

    const { unmount } = render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("switch", { checked: true }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    vi.useRealTimers();

    expect(saveReactions).toHaveBeenCalledWith(
      expect.objectContaining({ enabled: false }),
      "test-csrf",
    );

    unmount();
    render(<ReactionsFeature toast={toast} />);

    await screen.findAllByAltText(":lamdieu:");
    expect(screen.getByRole("switch", { checked: false })).toBeInTheDocument();
  });
});

describe("ReactionsFeature field autosave", () => {
  it("autosaves target and emoji changes after the debounce", async () => {
    getReactions.mockResolvedValue({
      ...baseReactions,
      channel_id: "999888777",
    });
    saveReactions.mockResolvedValue({ saved: true, applied: true });

    render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    vi.useFakeTimers();
    fireEvent.click(screen.getByTitle("@everyone"));
    fireEvent.click(screen.getByRole("button", { name: "🔥" }));

    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saving…");
    expect(saveReactions).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveReactions).toHaveBeenCalledWith(
      {
        enabled: true,
        target: "everyone",
        user_id: "123456789012345678",
        channel_id: "999888777",
        emojis: ["<:lamdieu:1547630841172066410>", "🔥"],
        cooldown: 3,
      },
      "test-csrf",
    );
    expect(screen.getByTestId("autosave-status")).toHaveTextContent("Saved");
  });

  it("flushes a pending text-field edit when unmounted", async () => {
    saveReactions.mockResolvedValue({ saved: true, applied: true });

    const { unmount } = render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    vi.useFakeTimers();
    fireEvent.change(
      screen.getByPlaceholderText("Channel ID (blank = all)"),
      { target: { value: "999888777" } },
    );
    expect(saveReactions).not.toHaveBeenCalled();

    unmount();

    expect(saveReactions).toHaveBeenCalledWith(
      expect.objectContaining({ channel_id: "999888777" }),
      "test-csrf",
    );
  });
});

describe("ReactionsFeature safety", () => {
  it("blocks enabling everyone mode without a channel", async () => {
    getReactions.mockResolvedValue({
      ...baseReactions,
      enabled: false,
      target: "everyone",
      user_id: "",
      channel_id: "",
      emojis: ["🔥"],
      cooldown: 3,
    });

    render(<ReactionsFeature toast={toast} />);
    await waitFor(() =>
      expect(
        screen.queryByText("Loading reaction settings…"),
      ).not.toBeInTheDocument(),
    );

    expect(
      screen.getByText("Everyone mode needs a channel."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch"));

    expect(saveReactions).not.toHaveBeenCalled();
    expect(
      screen.getByText("Pick a channel before enabling everyone mode."),
    ).toBeInTheDocument();
  });

  it("blocks enabling user mode without a user ID", async () => {
    getReactions.mockResolvedValue({
      ...baseReactions,
      enabled: false,
      target: "user",
      user_id: "",
      emojis: ["🔥"],
    });

    render(<ReactionsFeature toast={toast} />);
    await waitFor(() =>
      expect(
        screen.queryByText("Loading reaction settings…"),
      ).not.toBeInTheDocument(),
    );

    vi.useFakeTimers();
    fireEvent.click(screen.getByRole("switch"));

    expect(
      screen.getByText("Pick a user ID before enabling."),
    ).toBeInTheDocument();
    expect(screen.getByRole("switch")).not.toBeChecked();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });
    expect(saveReactions).not.toHaveBeenCalled();
  });

  it("blocks switching to everyone without a channel while enabled", async () => {
    render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    fireEvent.click(screen.getByTitle("@everyone"));

    expect(
      screen.getByText("Pick a channel before enabling everyone mode."),
    ).toBeInTheDocument();
    expect(screen.getByTitle("Specific user")).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("autosaves the reaction cooldown", async () => {
    saveReactions.mockResolvedValue({ saved: true, applied: true });

    render(<ReactionsFeature toast={toast} />);
    await screen.findAllByAltText(":lamdieu:");

    vi.useFakeTimers();
    fireEvent.change(screen.getByRole("slider"), {
      target: { value: "10" },
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(600);
    });

    expect(saveReactions).toHaveBeenCalledWith(
      expect.objectContaining({ cooldown: 10 }),
      "test-csrf",
    );
  });
});
