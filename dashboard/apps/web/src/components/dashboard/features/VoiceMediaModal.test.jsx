import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import VoiceMediaModal from "./VoiceMediaModal";

const {
  apiFetch,
  searchVoice,
  setVoiceFilters,
  setVoiceVolume,
  setVoiceLoop,
  replayVoice,
  forcefixVoice,
} = vi.hoisted(() => ({
  apiFetch: vi.fn(),
  searchVoice: vi.fn(),
  setVoiceFilters: vi.fn(),
  setVoiceVolume: vi.fn(),
  setVoiceLoop: vi.fn(),
  replayVoice: vi.fn(),
  forcefixVoice: vi.fn(),
}));

vi.mock("../../../lib/session", () => ({
  useSessionContext: () => ({
    loading: false,
    authenticated: true,
    csrf: "test-csrf",
    error: null,
  }),
}));

vi.mock("../../../lib/api", () => ({
  apiFetch,
  api: {
    searchVoice,
    setVoiceFilters,
    setVoiceVolume,
    setVoiceLoop,
    replayVoice,
    forcefixVoice,
  },
}));

const GUILD_ID = "999999999999999999";
const CHANNEL_ID = "111111111111111111";
const OTHER_CHANNEL_ID = "222222222222222222";

const TOKENS = [
  null,
  {
    index: 0,
    alive: true,
    username: "alice",
    display_name: "Alice",
    guild_id: GUILD_ID,
    channels: [CHANNEL_ID],
    guild_channels: {
      [GUILD_ID]: [
        { id: CHANNEL_ID, name: "General" },
        { id: OTHER_CHANNEL_ID, name: "Music" },
      ],
    },
  },
  {},
  { index: "" },
];

const QUEUE = {
  audio: {
    playing: true,
    title: "Midnight City",
    queue: ["Out of Touch", "Blue Monday"],
    filters: [],
    bass_level: 100,
    volume_pct: 100,
    loop_mode: "off",
    position_ms: 0,
    length_ms: null,
  },
};

beforeEach(() => {
  vi.resetAllMocks();
  setVoiceLoop.mockResolvedValue({ loop_mode: "off" });
  replayVoice.mockResolvedValue({ queued: true });
  apiFetch.mockImplementation((path) => {
    if (String(path).startsWith("/voice/audio/queue")) {
      return Promise.resolve(QUEUE);
    }
    return Promise.resolve({ queued: true });
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("VoiceMediaModal", () => {
  it("renders nothing when closed", () => {
    const { container } = render(
      <VoiceMediaModal open={false} onClose={vi.fn()} tokens={TOKENS} />,
    );

    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalled();
  });

  it("renders the token, channel, and query controls when open", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);

    const dialog = screen.getByRole("dialog", {
      name: "Voice media studio",
    });
    expect(dialog).toHaveAttribute("aria-modal", "true");

    const tokenSelect = within(dialog).getByRole("combobox", {
      name: "Voice token",
    });
    expect(tokenSelect).toHaveValue("0");
    expect(
      within(tokenSelect).getByRole("option", { name: "#0 alice" }),
    ).toBeInTheDocument();
    expect(within(tokenSelect).getAllByRole("option")).toHaveLength(1);

    const channel = within(dialog).getByRole("textbox", {
      name: "Channel ID",
    });
    expect(channel).toHaveValue("");
    expect(channel).toHaveAttribute("placeholder", "Channel ID");

    expect(
      within(dialog).getByPlaceholderText(
        "YouTube URL or song name (auto-queues)",
      ),
    ).toBeInTheDocument();
    await within(dialog).findByText("Midnight City");
    expect(
      within(dialog).getByRole("button", { name: "Add to Queue" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Skip" }),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByRole("button", { name: "Stop" }),
    ).toBeInTheDocument();
  });

  it("keeps the Play label when the queue is idle", async () => {
    apiFetch.mockImplementation((path) => {
      if (String(path).startsWith("/voice/audio/queue")) {
        return Promise.resolve({
          audio: { playing: false, title: null, queue: [] },
        });
      }
      return Promise.resolve({ queued: true });
    });

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);

    await waitFor(() =>
      expect(apiFetch).toHaveBeenCalledWith("/voice/audio/queue?token_index=0"),
    );
    expect(
      screen.getByRole("button", { name: "Play" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Add to Queue" }),
    ).not.toBeInTheDocument();
  });

  it("posts playback with the selected channel and query", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);

    const channel = screen.getByRole("textbox", { name: "Channel ID" });
    expect(channel).toHaveValue("");

    await screen.findByText("Midnight City");
    fireEvent.change(channel, { target: { value: OTHER_CHANNEL_ID } });
    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      {
        target: { value: "  https://youtu.be/dQw4w9WgXcQ  " },
      },
    );
    fireEvent.click(screen.getByRole("button", { name: "Add to Queue" }));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith("/voice/play", {
        method: "POST",
        csrf: "test-csrf",
        body: {
          token_index: 0,
          guild_id: "",
          channel_id: OTHER_CHANNEL_ID,
          query: "https://youtu.be/dQw4w9WgXcQ",
        },
      });
    });
  });

  it("ignores a double click while playback is being queued", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);

    await screen.findByText("Midnight City");
    fireEvent.change(screen.getByRole("textbox", { name: "Channel ID" }), {
      target: { value: OTHER_CHANNEL_ID },
    });
    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      {
        target: { value: "https://youtu.be/dQw4w9WgXcQ" },
      },
    );

    const playButton = screen.getByRole("button", { name: "Add to Queue" });
    // Both clicks land before React commits the disabled state, so only the
    // synchronous ref guard can stop the second request.
    act(() => {
      fireEvent.click(playButton);
      fireEvent.click(playButton);
    });

    const playCalls = () =>
      apiFetch.mock.calls.filter(([path]) => path === "/voice/play");

    await waitFor(() => {
      expect(playCalls()).toHaveLength(1);
    });
    expect(playCalls()).toHaveLength(1);
  });

  it("explains that the bot is offline instead of faking a queue", async () => {
    apiFetch.mockImplementation((path) => {
      if (String(path).startsWith("/voice/audio/queue")) {
        return Promise.resolve(QUEUE);
      }
      if (path === "/voice/play") {
        return Promise.reject({ data: { error: "bot_offline" } });
      }
      return Promise.resolve({ queued: true });
    });
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);

    await screen.findByText("Midnight City");
    fireEvent.change(screen.getByRole("textbox", { name: "Channel ID" }), {
      target: { value: OTHER_CHANNEL_ID },
    });
    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      { target: { value: "https://youtu.be/dQw4w9WgXcQ" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Add to Queue" }));

    expect(
      await screen.findByText(
        /Bot is offline — start it before queueing playback/,
      ),
    ).toBeInTheDocument();
  });

  it("requires a channel before playing", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      { target: { value: "first song" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Add to Queue" }));

    expect(
      await screen.findByText("Choose a channel first."),
    ).toBeInTheDocument();
    expect(
      screen.queryByText("This token has no active guild."),
    ).not.toBeInTheDocument();
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/voice/play",
      expect.anything(),
    );
  });

  it("plays with a token that has no active guild", async () => {
    const tokens = [
      { index: 0, alive: true, username: "alice", channels: [] },
    ];

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={tokens} />);
    await screen.findByText("Midnight City");

    fireEvent.change(screen.getByRole("textbox", { name: "Channel ID" }), {
      target: { value: CHANNEL_ID },
    });
    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      { target: { value: "first song" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Add to Queue" }));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith("/voice/play", {
        method: "POST",
        csrf: "test-csrf",
        body: {
          token_index: 0,
          guild_id: "",
          channel_id: CHANNEL_ID,
          query: "first song",
        },
      });
    });
  });

  it("searches and queues a result by URL", async () => {
    searchVoice.mockResolvedValue({
      results: [
        {
          title: "First Song",
          uploader: "Artist One",
          duration: 215,
          url: "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
        {
          title: "Second Song",
          uploader: "Artist Two",
          duration: null,
          url: "https://www.youtube.com/watch?v=bbbbbbbbbbb",
        },
      ],
    });

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);

    const channel = screen.getByRole("textbox", { name: "Channel ID" });
    fireEvent.change(channel, { target: { value: CHANNEL_ID } });

    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      { target: { value: "  first song  " } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("First Song")).toBeInTheDocument();
    expect(screen.getByText("Second Song")).toBeInTheDocument();
    expect(screen.getByText("Artist One · 3:35")).toBeInTheDocument();
    expect(screen.getByText("Artist Two · LIVE")).toBeInTheDocument();
    expect(searchVoice).toHaveBeenCalledWith("first song", "test-csrf");

    const firstRow = screen.getByText("First Song").closest("li");
    fireEvent.click(within(firstRow).getByRole("button", { name: "+ Queue" }));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith("/voice/play", {
        method: "POST",
        csrf: "test-csrf",
        body: {
          token_index: 0,
          guild_id: "",
          channel_id: CHANNEL_ID,
          query: "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
      });
    });
    expect(screen.getByText("First Song")).toBeInTheDocument();
  });

  it("searches without a channel ID", async () => {
    searchVoice.mockResolvedValue({
      results: [
        {
          title: "First Song",
          uploader: "Artist One",
          duration: 215,
          url: "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
      ],
    });

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);

    expect(screen.getByRole("textbox", { name: "Channel ID" })).toHaveValue("");
    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      { target: { value: "  first song  " } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("First Song")).toBeInTheDocument();
    expect(screen.getByTestId("voice-search-results")).toBeInTheDocument();
    expect(searchVoice).toHaveBeenCalledWith("first song", "test-csrf");
    expect(apiFetch).not.toHaveBeenCalledWith(
      "/voice/play",
      expect.anything(),
    );
  });

  it("dismisses search results with the close button", async () => {
    searchVoice.mockResolvedValue({
      results: [
        {
          title: "First Song",
          uploader: "Artist One",
          duration: 215,
          url: "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
      ],
    });

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Channel ID" }), {
      target: { value: CHANNEL_ID },
    });
    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      { target: { value: "first song" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("First Song")).toBeInTheDocument();
    expect(screen.getByTestId("voice-search-results")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Close search results" }),
    );

    expect(screen.queryByText("First Song")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("voice-search-results"),
    ).not.toBeInTheDocument();
  });

  it("clears search results when the token changes", async () => {
    searchVoice.mockResolvedValue({
      results: [
        {
          title: "First Song",
          uploader: "Artist One",
          duration: 215,
          url: "https://www.youtube.com/watch?v=aaaaaaaaaaa",
        },
      ],
    });

    const tokens = [
      TOKENS[1],
      {
        index: 1,
        alive: true,
        username: "bob",
        guild_id: GUILD_ID,
        channels: [],
      },
    ];

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={tokens} />);
    fireEvent.change(screen.getByRole("textbox", { name: "Channel ID" }), {
      target: { value: CHANNEL_ID },
    });
    fireEvent.change(
      screen.getByPlaceholderText("YouTube URL or song name (auto-queues)"),
      { target: { value: "first song" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Search" }));

    expect(await screen.findByText("First Song")).toBeInTheDocument();

    fireEvent.change(screen.getByRole("combobox", { name: "Voice token" }), {
      target: { value: "1" },
    });

    await waitFor(() => {
      expect(screen.queryByText("First Song")).not.toBeInTheDocument();
    });
    expect(
      screen.queryByTestId("voice-search-results"),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Channel ID" })).toHaveValue("");
  });

  it("posts skip for the selected token", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    fireEvent.click(screen.getByRole("button", { name: "Skip" }));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith("/voice/audio/skip", {
        method: "POST",
        csrf: "test-csrf",
        body: { token_index: 0 },
      });
    });
  });

  it("posts stop for the selected token", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    fireEvent.click(screen.getByRole("button", { name: "Stop" }));

    await waitFor(() => {
      expect(apiFetch).toHaveBeenCalledWith("/voice/audio/stop", {
        method: "POST",
        csrf: "test-csrf",
        body: { token_index: 0 },
      });
    });
  });

  it("reconnects and restores playback for the selected token", async () => {
    forcefixVoice.mockResolvedValue({ queued: true });

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    fireEvent.click(
      screen.getByRole("button", { name: "Reconnect & restore" }),
    );

    await waitFor(() => {
      expect(forcefixVoice).toHaveBeenCalledWith(0, "test-csrf");
    });
    expect(
      await screen.findByText("Reconnected and restored playback."),
    ).toBeInTheDocument();
  });

  it("selects one effect at a time and keeps Bass Boost independent", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    const bass = screen.getByRole("switch", { name: "Bass Boost" });
    expect(bass).toHaveAttribute("aria-checked", "false");

    fireEvent.click(bass);

    await waitFor(() => {
      expect(setVoiceFilters).toHaveBeenCalledWith(
        0,
        ["bass"],
        100,
        "test-csrf",
      );
    });
    expect(bass).toHaveAttribute("aria-checked", "true");

    fireEvent.click(screen.getByRole("button", { name: "Lo-Fi" }));

    await waitFor(() => {
      expect(setVoiceFilters).toHaveBeenLastCalledWith(
        0,
        ["bass", "lofi"],
        100,
        "test-csrf",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "8D" }));

    await waitFor(() => {
      expect(setVoiceFilters).toHaveBeenLastCalledWith(
        0,
        ["bass", "8d"],
        100,
        "test-csrf",
      );
    });
    expect(screen.getByRole("button", { name: "Lo-Fi" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(screen.getByRole("button", { name: "8D" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    fireEvent.click(screen.getByRole("button", { name: "8D" }));

    await waitFor(() => {
      expect(setVoiceFilters).toHaveBeenLastCalledWith(
        0,
        ["bass"],
        100,
        "test-csrf",
      );
    });

    fireEvent.click(bass);

    await waitFor(() => {
      expect(setVoiceFilters).toHaveBeenLastCalledWith(
        0,
        [],
        null,
        "test-csrf",
      );
    });
    expect(bass).toHaveAttribute("aria-checked", "false");
  });

  it("shows the bass level slider only while Bass Boost is active", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    expect(
      screen.queryByRole("slider", { name: "Bass level" }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Bass Boost" }));

    const bassSlider = screen.getByRole("slider", { name: "Bass level" });
    expect(bassSlider.value).toBe("100");

    fireEvent.change(bassSlider, { target: { value: "250" } });

    await waitFor(() => {
      expect(setVoiceFilters).toHaveBeenLastCalledWith(
        0,
        ["bass"],
        250,
        "test-csrf",
      );
    });
  });

  it("resets audio to default", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    fireEvent.click(screen.getByRole("switch", { name: "Bass Boost" }));
    fireEvent.click(screen.getByRole("button", { name: "Lo-Fi" }));

    await waitFor(() => {
      expect(setVoiceFilters).toHaveBeenLastCalledWith(
        0,
        ["bass", "lofi"],
        100,
        "test-csrf",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Default" }));

    await waitFor(() => {
      expect(setVoiceFilters).toHaveBeenLastCalledWith(
        0,
        [],
        null,
        "test-csrf",
      );
      expect(setVoiceVolume).toHaveBeenLastCalledWith(0, 100, "test-csrf");
    });
    expect(screen.getByRole("switch", { name: "Bass Boost" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("button", { name: "Lo-Fi" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("changes the playback volume", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    const volume = screen.getByRole("slider", { name: "Volume" });
    expect(volume.value).toBe("100");

    fireEvent.change(volume, { target: { value: "35" } });

    await waitFor(() => {
      expect(setVoiceVolume).toHaveBeenCalledWith(0, 35, "test-csrf");
    });
  });

  it("debounces rapid volume changes into one request", async () => {
    vi.useFakeTimers();
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const volume = screen.getByRole("slider", { name: "Volume" });
    fireEvent.change(volume, { target: { value: "40" } });
    fireEvent.change(volume, { target: { value: "35" } });

    expect(setVoiceVolume).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(499);
    });
    expect(setVoiceVolume).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(setVoiceVolume).toHaveBeenCalledTimes(1);
    expect(setVoiceVolume).toHaveBeenCalledWith(0, 35, "test-csrf");
  });

  it("debounces rapid bass level changes into one request", async () => {
    vi.useFakeTimers();
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    fireEvent.click(screen.getByRole("switch", { name: "Bass Boost" }));
    expect(setVoiceFilters).toHaveBeenCalledWith(
      0,
      ["bass"],
      100,
      "test-csrf",
    );
    setVoiceFilters.mockClear();

    const bass = screen.getByRole("slider", { name: "Bass level" });
    fireEvent.change(bass, { target: { value: "200" } });
    fireEvent.change(bass, { target: { value: "250" } });

    expect(setVoiceFilters).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(500);
    });
    expect(setVoiceFilters).toHaveBeenCalledTimes(1);
    expect(setVoiceFilters).toHaveBeenCalledWith(
      0,
      ["bass"],
      250,
      "test-csrf",
    );
  });

  it("keeps a pending volume edit during a queue poll", async () => {
    vi.useFakeTimers();
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2600);
    });

    const volume = screen.getByRole("slider", { name: "Volume" });
    fireEvent.change(volume, { target: { value: "35" } });

    // The poll lands at 3s while the 500ms debounce is still pending.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(400);
    });
    expect(volume.value).toBe("35");
    expect(setVoiceVolume).not.toHaveBeenCalled();

    await act(async () => {
      await vi.advanceTimersByTimeAsync(100);
    });
    expect(setVoiceVolume).toHaveBeenCalledWith(0, 35, "test-csrf");
  });

  it("toggles loop on and off", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    const loop = screen.getByRole("switch", { name: "Loop" });
    expect(loop).toHaveAttribute("aria-checked", "false");

    fireEvent.click(loop);

    await waitFor(() => {
      expect(setVoiceLoop).toHaveBeenCalledWith(0, "queue", "test-csrf");
    });
    expect(loop).toHaveAttribute("aria-checked", "true");
    await waitFor(() => expect(loop).not.toBeDisabled());

    fireEvent.click(loop);

    await waitFor(() => {
      expect(setVoiceLoop).toHaveBeenLastCalledWith(0, "off", "test-csrf");
    });
    expect(loop).toHaveAttribute("aria-checked", "false");
  });

  it("treats track loop as enabled", async () => {
    apiFetch.mockImplementation((path) => {
      if (String(path).startsWith("/voice/audio/queue")) {
        return Promise.resolve({
          audio: {
            playing: true,
            title: "Midnight City",
            queue: [],
            loop_mode: "track",
          },
        });
      }
      return Promise.resolve({ queued: true });
    });

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    expect(screen.getByRole("switch", { name: "Loop" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("replays the current track", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    fireEvent.click(screen.getByRole("button", { name: "Replay" }));

    await waitFor(() => {
      expect(replayVoice).toHaveBeenCalledWith(0, "test-csrf");
    });
    expect(
      await screen.findByText("Replaying current track."),
    ).toBeInTheDocument();
  });

  it("syncs sliders, loop, and progress from the queue payload", async () => {
    apiFetch.mockImplementation((path) => {
      if (String(path).startsWith("/voice/audio/queue")) {
        return Promise.resolve({
          audio: {
            playing: true,
            title: "Midnight City",
            queue: ["Out of Touch"],
            filters: ["bass", "lofi"],
            bass_level: 250,
            volume_pct: 40,
            loop_mode: "queue",
            position_ms: 65000,
            length_ms: 180000,
          },
        });
      }
      return Promise.resolve({ queued: true });
    });

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    expect(screen.getByRole("slider", { name: "Volume" }).value).toBe("40");
    expect(screen.getByRole("slider", { name: "Bass level" }).value).toBe(
      "250",
    );
    expect(screen.getByRole("switch", { name: "Bass Boost" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("button", { name: "Lo-Fi" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("switch", { name: "Loop" })).toHaveAttribute(
      "aria-checked",
      "true",
    );

    const progress = screen.getByRole("progressbar", {
      name: "Playback progress",
    });
    expect(progress).toHaveAttribute("aria-valuenow", "65000");
    expect(progress).toHaveAttribute("aria-valuemax", "180000");
    expect(screen.getByText("1:05")).toBeInTheDocument();
    expect(screen.getByText("3:00")).toBeInTheDocument();
  });

  it("hides the progress bar when the track length is unknown", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("reports filter failures in the status line", async () => {
    setVoiceFilters.mockRejectedValue({
      data: { error: "voice_unavailable" },
    });

    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    fireEvent.click(screen.getByRole("button", { name: "Soft" }));

    expect(
      await screen.findByText("Voice control is not available."),
    ).toBeInTheDocument();
  });

  it("polls the queue and renders the now-playing and queued titles", async () => {
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);

    expect(await screen.findByTestId("voice-now-playing")).toHaveTextContent(
      "Midnight City",
    );
    expect(screen.getByText("Out of Touch")).toBeInTheDocument();
    expect(screen.getByText("Blue Monday")).toBeInTheDocument();
    expect(apiFetch).toHaveBeenCalledWith(
      "/voice/audio/queue?token_index=0",
    );
  });

  it("closes from the X button, the backdrop, and Escape", async () => {
    const onClose = vi.fn();
    render(<VoiceMediaModal open onClose={onClose} tokens={TOKENS} />);
    await screen.findByText("Midnight City");

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("voice-media-backdrop"));
    expect(onClose).toHaveBeenCalledTimes(2);

    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(3);
  });

  it("keeps an optimistic loop toggle during a stale queue poll", async () => {
    vi.useFakeTimers();
    render(<VoiceMediaModal open onClose={vi.fn()} tokens={TOKENS} />);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });

    const loop = screen.getByRole("switch", { name: "Loop" });
    expect(loop).toHaveAttribute("aria-checked", "false");

    fireEvent.click(loop);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(setVoiceLoop).toHaveBeenCalledWith(0, "queue", "test-csrf");
    expect(loop).toHaveAttribute("aria-checked", "true");

    // The 3s poll still reports the old server loop mode.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    expect(loop).toHaveAttribute("aria-checked", "true");
  });
});
