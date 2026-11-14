import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import VoiceFeature from "./VoiceFeature";

const {
  getVoiceTokens,
  getVoiceSoundboard,
  getVoiceDefaultSounds,
  playVoiceSound,
  joinVoice,
  leaveVoice,
  moveVoice,
  setVoiceState,
  addVoiceToken,
  deleteVoiceToken,
  setVoiceStream,
  setVoiceCamera,
} = vi.hoisted(() => ({
  getVoiceTokens: vi.fn(),
  getVoiceSoundboard: vi.fn(),
  getVoiceDefaultSounds: vi.fn(),
  playVoiceSound: vi.fn(),
  joinVoice: vi.fn(),
  leaveVoice: vi.fn(),
  moveVoice: vi.fn(),
  setVoiceState: vi.fn(),
  addVoiceToken: vi.fn(),
  deleteVoiceToken: vi.fn(),
  setVoiceStream: vi.fn(),
  setVoiceCamera: vi.fn(),
}));

const liveStateRef = vi.hoisted(() => ({
  connected: false,
  liveState: null,
}));

vi.mock("../../../lib/ws", () => ({
  useLiveState: () => ({
    connected: liveStateRef.connected,
    liveState: liveStateRef.liveState,
  }),
}));

vi.mock("../../../lib/session", () => ({
  useSessionContext: () => ({
    loading: false,
    authenticated: true,
    csrf: "test-csrf",
    error: null,
  }),
}));

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    apiFetch: vi.fn().mockResolvedValue({ nowPlaying: null, items: [] }),
    api: {
      ...actual.api,
      getVoiceTokens,
      getVoiceSoundboard,
      getVoiceDefaultSounds,
      playVoiceSound,
      joinVoice,
      leaveVoice,
      moveVoice,
      setVoiceState,
      addVoiceToken,
      deleteVoiceToken,
      setVoiceStream,
      setVoiceCamera,
    },
  };
});

function makeToast() {
  return {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
  };
}

const ALICE = {
  index: 0,
  alive: true,
  username: "alice",
  display_name: "Alice",
  user_id: "1",
  avatar_url: "https://cdn.example/alice.png",
  error: null,
  channels: ["456"],
  guild_id: "789",
  gateway_ready: true,
  streaming: true,
  video: false,
  audio_active: false,
  audio_playing: false,
  self_mute: false,
  self_deaf: false,
  guild_channels: {
    789: [
      { id: "456", name: "General" },
      { id: "999", name: "Music" },
    ],
  },
};

const BOB = {
  index: 1,
  alive: true,
  username: "bob",
  display_name: "Bob",
  user_id: "2",
  avatar_url: "https://cdn.example/bob.png",
  error: null,
  channels: [],
  guild_id: null,
  gateway_ready: true,
  streaming: false,
  video: false,
  audio_active: false,
  audio_playing: false,
  self_mute: false,
  self_deaf: false,
  guild_channels: {
    789: [
      { id: "456", name: "General" },
      { id: "999", name: "Music" },
    ],
  },
};

const CAROL = {
  index: 2,
  alive: false,
  username: null,
  display_name: null,
  user_id: null,
  avatar_url: null,
  error: "network_error",
  channels: [],
  guild_id: null,
  gateway_ready: false,
};

beforeEach(() => {
  vi.resetAllMocks();
  liveStateRef.connected = false;
  liveStateRef.liveState = null;
  getVoiceTokens.mockResolvedValue({
    tokens: [ALICE, BOB, CAROL],
    removed: 1,
    state_updated_at: 123,
  });
  getVoiceSoundboard.mockResolvedValue({
    sounds: [{ sound_id: "1", name: "Quack", emoji_name: "🦆" }],
  });
  getVoiceDefaultSounds.mockResolvedValue({
    sounds: [{ sound_id: "2", name: "Airhorn", emoji_name: "📯" }],
  });
  playVoiceSound.mockResolvedValue({ ok: true });
  joinVoice.mockResolvedValue({ queued: true });
  leaveVoice.mockResolvedValue({ queued: true });
  moveVoice.mockResolvedValue({ queued: true });
  setVoiceState.mockResolvedValue({ ok: true });
  addVoiceToken.mockResolvedValue({ ok: true });
  deleteVoiceToken.mockResolvedValue({ ok: true });
  setVoiceStream.mockResolvedValue({});
  setVoiceCamera.mockResolvedValue({});
});

describe("VoiceFeature", () => {
  it("renders real token names, status under the name, and current channel", async () => {
    render(<VoiceFeature toast={makeToast()} />);

    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    expect(aliceRow).not.toBeNull();
    expect(within(aliceRow).getByText("Online")).toBeInTheDocument();
    expect(within(aliceRow).getByText(/ch 456/)).toBeInTheDocument();
    expect(screen.getByText("Idle")).toBeInTheDocument();
    expect(screen.getByText("Error")).toBeInTheDocument();
    expect(screen.getByText(/Removed 1 expired token/)).toBeInTheDocument();
  });

  it("opens the soundboard modal and plays a server sound", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByRole("button", { name: /Soundboard/i }));

    expect(await screen.findByText("Quack")).toBeInTheDocument();
    expect(getVoiceSoundboard).toHaveBeenCalledWith("789", 0);

    fireEvent.click(screen.getByRole("button", { name: /Quack/i }));

    await waitFor(() => {
      expect(playVoiceSound).toHaveBeenCalledWith(
        {
          token_index: 0,
          channel_id: "456",
          sound_id: "1",
          source_guild_id: "789",
        },
        "test-csrf",
      );
    });
  });

  it("switches to default sounds in the modal", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByRole("button", { name: /Soundboard/i }));
    fireEvent.click(screen.getByRole("button", { name: "Defaults" }));

    expect(await screen.findByText("Airhorn")).toBeInTheDocument();
    expect(getVoiceDefaultSounds).toHaveBeenCalledWith(0);
  });

  it("selects multiple tokens and joins them sequentially", async () => {
    liveStateRef.connected = true;
    liveStateRef.liveState = { voice: { tokens: [], updated_at: 123 } };
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByText("Alice"));
    fireEvent.click(screen.getByText("Bob"));
    fireEvent.change(screen.getByPlaceholderText("Channel ID"), {
      target: { value: "111111111111111111" },
    });

    const joinButton = screen.getByRole("button", { name: /Join \/ Move \(2\)/i });
    vi.useFakeTimers();
    fireEvent.click(joinButton);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(joinVoice).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(2000);
    });
    vi.useRealTimers();

    expect(joinVoice).toHaveBeenCalledTimes(2);
    expect(joinVoice.mock.calls[0][0]).toEqual({
      token_index: 0,
      channels: ["111111111111111111"],
    });
    expect(joinVoice.mock.calls[1][0]).toEqual({
      token_index: 1,
      channels: ["111111111111111111"],
    });
  });

  it("ignores a live frame with the same updated_at", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [ALICE, CAROL],
      removed: 0,
      state_updated_at: 123,
    });

    liveStateRef.connected = true;
    liveStateRef.liveState = {
      voice: {
        updated_at: 1,
        tokens: [
          {
            index: 0,
            username: "alice",
            channels: ["456"],
            guild_id: "789",
            gateway_ready: true,
          },
        ],
      },
    };

    const toast = makeToast();
    const { rerender } = render(<VoiceFeature toast={toast} />);
    await screen.findByText("Alice");
    expect(screen.queryByText("Bob")).not.toBeInTheDocument();

    // Same change token, different payload: the frame must be ignored.
    liveStateRef.liveState = {
      voice: {
        updated_at: 1,
        tokens: [
          {
            index: 5,
            username: "bob",
            display_name: "Bob",
            channels: ["456"],
            guild_id: "789",
            gateway_ready: true,
          },
        ],
      },
    };
    await act(async () => {
      rerender(<VoiceFeature toast={toast} />);
    });

    expect(screen.queryByText("Bob")).not.toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();

    // A new change token applies the payload.
    liveStateRef.liveState = {
      voice: {
        updated_at: 2,
        tokens: [
          {
            index: 5,
            username: "bob",
            display_name: "Bob",
            channels: ["456"],
            guild_id: "789",
            gateway_ready: true,
          },
        ],
      },
    };
    await act(async () => {
      rerender(<VoiceFeature toast={toast} />);
    });

    expect(await screen.findByText("Bob")).toBeInTheDocument();
  });

  it("moves a selected token that is already in the target guild", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByText("Alice"));
    fireEvent.change(screen.getByPlaceholderText("Channel ID"), {
      target: { value: "999" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Join \/ Move \(1\)/i }));

    await waitFor(() => {
      expect(moveVoice).toHaveBeenCalledWith(
        { token_index: 0, guild_id: "789", channel_id: "999" },
        "test-csrf",
      );
    });
    expect(joinVoice).not.toHaveBeenCalled();
  });

  it("queues a leave for the token's current channel", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByTitle("Disconnect"));

    await waitFor(() => {
      expect(leaveVoice).toHaveBeenCalledWith(
        { token_index: 0, channel_id: "456" },
        "test-csrf",
      );
    });
  });

  it("toggles mic and deafen from the token row", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    fireEvent.click(within(aliceRow).getByTitle("Mute"));
    await waitFor(() => {
      expect(setVoiceState).toHaveBeenCalledWith(
        { token_index: 0, guild_id: "789", mute: true },
        "test-csrf",
      );
    });

    fireEvent.click(within(aliceRow).getByTitle("Deafen"));
    await waitFor(() => {
      expect(setVoiceState).toHaveBeenCalledWith(
        { token_index: 0, guild_id: "789", deaf: true },
        "test-csrf",
      );
    });
  });

  it("runs bulk mute and deafen actions per guild", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByRole("button", { name: "Mute all" }));
    await waitFor(() => {
      expect(setVoiceState).toHaveBeenCalledWith(
        { all: true, guild_id: "789", mute: true },
        "test-csrf",
      );
    });

    fireEvent.click(screen.getByRole("button", { name: "Deafen all" }));
    await waitFor(() => {
      expect(setVoiceState).toHaveBeenCalledWith(
        { all: true, guild_id: "789", deaf: true },
        "test-csrf",
      );
    });
  });

  it("opens the advanced media modal", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByRole("button", { name: /Advanced/i }));

    expect(
      await screen.findByRole("dialog", { name: "Voice media studio" }),
    ).toBeInTheDocument();
  });

  it("removes the old fake mute, deaf, and telemetry panels", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    expect(screen.queryByText("Self-Mute")).not.toBeInTheDocument();
    expect(screen.queryByText("Self-Deaf")).not.toBeInTheDocument();
    expect(screen.queryByText("Anti-Flag Telemetry")).not.toBeInTheDocument();
  });

  it("adds a voice token with the csrf token", async () => {
    const toast = makeToast();
    render(<VoiceFeature toast={toast} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByRole("button", { name: /Add Token/i }));
    fireEvent.change(screen.getByPlaceholderText("Paste voice token"), {
      target: { value: "  secret-token  " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => {
      expect(addVoiceToken).toHaveBeenCalledWith(
        { token: "secret-token" },
        "test-csrf",
      );
    });
    await waitFor(() => {
      expect(getVoiceTokens.mock.calls.length).toBeGreaterThanOrEqual(2);
      expect(screen.getByPlaceholderText("Paste voice token")).toHaveValue("");
    });
    expect(toast.success).toHaveBeenCalled();
  });

  it("deletes a voice token after inline confirmation", async () => {
    const toast = makeToast();
    render(<VoiceFeature toast={toast} />);
    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    fireEvent.click(within(aliceRow).getByTitle("Remove Alice"));

    expect(within(aliceRow).getByText("Remove?")).toBeInTheDocument();
    expect(deleteVoiceToken).not.toHaveBeenCalled();

    fireEvent.click(
      within(aliceRow).getByRole("button", { name: /Confirm remove Alice/i }),
    );

    await waitFor(() => {
      expect(deleteVoiceToken).toHaveBeenCalledWith(
        { token_index: 0 },
        "test-csrf",
      );
    });
    expect(toast.success).toHaveBeenCalled();
  });

  it("shows a LIVE badge for a streaming token", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    expect(screen.getByText("LIVE")).toBeInTheDocument();
  });

  it("toggles a stream off with the csrf token", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    fireEvent.click(within(aliceRow).getByTitle("Stop stream"));

    await waitFor(() => {
      expect(setVoiceStream).toHaveBeenCalledWith(
        { token_index: 0, enable: false },
        "test-csrf",
      );
    });
  });

  it("turns the camera on with the csrf token", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    fireEvent.click(within(aliceRow).getByTitle("Turn camera on"));

    await waitFor(() => {
      expect(setVoiceCamera).toHaveBeenCalledWith(
        { token_index: 0, enable: true },
        "test-csrf",
      );
    });
  });

  it("blocks stream toggle when the token is not in a voice channel", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [
        {
          ...ALICE,
          channels: [],
          guild_id: null,
          streaming: false,
        },
      ],
      removed: 0,
      state_updated_at: 123,
    });
    const toast = makeToast();
    render(<VoiceFeature toast={toast} />);
    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    fireEvent.click(within(aliceRow).getByTitle("Start stream (Go Live)"));

    await waitFor(() => {
      expect(toast.error).toHaveBeenCalledWith(
        "Join a voice channel first.",
        "Voice",
      );
    });
    expect(setVoiceStream).not.toHaveBeenCalled();
  });

  it("renders all five hero stats", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    const stats = screen.getByTestId("feature-hero-stats");
    expect(within(stats).getByText("Tokens")).toBeInTheDocument();
    expect(within(stats).getByText("In Voice")).toBeInTheDocument();
    expect(within(stats).getByText("Streaming")).toBeInTheDocument();
    expect(within(stats).getByText("Gateway")).toBeInTheDocument();
    expect(within(stats).getByText("Removed")).toBeInTheDocument();
  });

  it("keeps token action buttons accessible", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    expect(aliceRow).not.toBeNull();

    expect(within(aliceRow).getByTitle("Mute")).toBeInTheDocument();
    expect(within(aliceRow).getByTitle("Deafen")).toBeInTheDocument();
    expect(
      within(aliceRow).queryByTitle("Stop stream") ||
        within(aliceRow).queryByTitle("Start stream (Go Live)"),
    ).not.toBeNull();
    expect(
      within(aliceRow).queryByTitle("Turn camera on") ||
        within(aliceRow).queryByTitle("Turn camera off"),
    ).not.toBeNull();
    expect(
      within(aliceRow).queryByTitle("Disconnect") ||
        within(aliceRow).queryByTitle("Connect"),
    ).not.toBeNull();
    expect(within(aliceRow).getByTitle("Remove Alice")).toBeInTheDocument();
  });

  it("leaves a non-audio token without asking for confirmation", async () => {
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByText("Alice"));
    fireEvent.click(
      screen.getByRole("button", { name: /Leave Selected \(1\)/i }),
    );

    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => {
      expect(leaveVoice).toHaveBeenCalledWith(
        { token_index: 0, channel_id: "456" },
        "test-csrf",
      );
    });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("asks before leaving audio tokens and can skip them", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [
        { ...ALICE, audio_active: true, audio_playing: true },
        { ...BOB, channels: ["456"], guild_id: "789", audio_active: false },
      ],
      removed: 0,
      state_updated_at: 123,
    });
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByText("Alice"));
    fireEvent.click(screen.getByText("Bob"));
    fireEvent.click(
      screen.getByRole("button", { name: /Leave Selected \(2\)/i }),
    );

    expect(
      await screen.findByRole("alertdialog", { name: "Leave audio tokens?" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/1 selected token\(s\) are playing audio/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "No, skip audio" }));

    await waitFor(
      () => {
        expect(leaveVoice).toHaveBeenCalledTimes(1);
      },
      { timeout: 4000 },
    );
    expect(leaveVoice).toHaveBeenCalledWith(
      { token_index: 1, channel_id: "456" },
      "test-csrf",
    );
    expect(
      leaveVoice.mock.calls.some(([payload]) => payload.token_index === 0),
    ).toBe(false);
  });

  it("leaves every selected token when the audio confirmation is accepted", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [
        { ...ALICE, audio_active: true, audio_playing: true },
        { ...BOB, channels: ["456"], guild_id: "789", audio_active: false },
      ],
      removed: 0,
      state_updated_at: 123,
    });
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByText("Alice"));
    fireEvent.click(screen.getByText("Bob"));
    fireEvent.click(
      screen.getByRole("button", { name: /Leave Selected \(2\)/i }),
    );

    fireEvent.click(
      await screen.findByRole("button", { name: "Yes, leave all" }),
    );

    await waitFor(
      () => {
        expect(leaveVoice).toHaveBeenCalledTimes(2);
      },
      { timeout: 4000 },
    );
    expect(leaveVoice).toHaveBeenCalledWith(
      { token_index: 0, channel_id: "456" },
      "test-csrf",
    );
    expect(leaveVoice).toHaveBeenCalledWith(
      { token_index: 1, channel_id: "456" },
      "test-csrf",
    );
  });

  it("shows a playing audio badge for a token with active playback", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [{ ...ALICE, audio_active: true, audio_playing: true }],
      removed: 0,
      state_updated_at: 123,
    });
    render(<VoiceFeature toast={makeToast()} />);
    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    expect(
      within(aliceRow).getByTestId("voice-audio-badge"),
    ).toHaveTextContent("Playing audio");
  });

  it("shows an audio queued badge for a parked token", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [{ ...ALICE, audio_active: true, audio_playing: false }],
      removed: 0,
      state_updated_at: 123,
    });
    render(<VoiceFeature toast={makeToast()} />);
    const alice = await screen.findByText("Alice");
    const aliceRow = alice.closest("[data-testid='voice-token-row']");

    expect(
      within(aliceRow).getByTestId("voice-audio-badge"),
    ).toHaveTextContent("Audio queued");
  });

  it("disconnects an audio token from its row without the bulk confirmation", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [{ ...ALICE, audio_active: true, audio_playing: true }],
      removed: 0,
      state_updated_at: 123,
    });
    render(<VoiceFeature toast={makeToast()} />);
    await screen.findByText("Alice");

    fireEvent.click(screen.getByTitle("Disconnect"));

    await waitFor(() => {
      expect(leaveVoice).toHaveBeenCalledWith(
        { token_index: 0, channel_id: "456" },
        "test-csrf",
      );
    });
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("drops tokens missing from an authoritative live frame", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [ALICE, BOB],
      removed: 0,
      state_updated_at: 123,
    });

    liveStateRef.connected = true;
    liveStateRef.liveState = {
      tokens: 1,
      voice: {
        updated_at: 1,
        tokens: [
          {
            index: 0,
            username: "alice",
            channels: ["456"],
            guild_id: "789",
            gateway_ready: true,
          },
        ],
      },
    };

    const toast = makeToast();
    const { rerender } = render(<VoiceFeature toast={toast} />);
    await screen.findByText("Alice");
    expect(await screen.findByText("Bob")).toBeInTheDocument();

    liveStateRef.liveState = {
      tokens: 1,
      voice: {
        updated_at: 2,
        tokens: [
          {
            index: 0,
            username: "alice",
            channels: ["456"],
            guild_id: "789",
            gateway_ready: true,
          },
        ],
      },
    };
    await act(async () => {
      rerender(<VoiceFeature toast={toast} />);
    });

    expect(screen.queryByText("Bob")).not.toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });

  it("keeps tokens when a live frame is only a partial snapshot", async () => {
    getVoiceTokens.mockResolvedValue({
      tokens: [ALICE, BOB],
      removed: 0,
      state_updated_at: 123,
    });

    liveStateRef.connected = true;
    liveStateRef.liveState = {
      tokens: 2,
      voice: {
        updated_at: 1,
        tokens: [
          {
            index: 0,
            username: "alice",
            channels: ["456"],
            guild_id: "789",
            gateway_ready: true,
          },
        ],
      },
    };

    const toast = makeToast();
    const { rerender } = render(<VoiceFeature toast={toast} />);
    await screen.findByText("Alice");
    expect(await screen.findByText("Bob")).toBeInTheDocument();

    liveStateRef.liveState = {
      tokens: 2,
      voice: {
        updated_at: 2,
        tokens: [
          {
            index: 0,
            username: "alice",
            channels: ["456"],
            guild_id: "789",
            gateway_ready: true,
          },
        ],
      },
    };
    await act(async () => {
      rerender(<VoiceFeature toast={toast} />);
    });

    expect(screen.getByText("Bob")).toBeInTheDocument();
    expect(screen.getByText("Alice")).toBeInTheDocument();
  });
});
