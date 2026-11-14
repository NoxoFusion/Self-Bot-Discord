import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import RichPresenceFeature, {
  sliceActivitiesForSpotify,
} from "./RichPresenceFeature";

const {
  getPresenceConfig,
  savePresenceConfig,
  applyPresence,
  clearPresence,
  getSongs,
  saveSongs,
  resolveSong,
  resolveYouTube,
  uploadPresenceImage,
} = vi.hoisted(() => ({
  getPresenceConfig: vi.fn(),
  savePresenceConfig: vi.fn(),
  applyPresence: vi.fn(),
  clearPresence: vi.fn(),
  getSongs: vi.fn(),
  saveSongs: vi.fn(),
  resolveSong: vi.fn(),
  resolveYouTube: vi.fn(),
  uploadPresenceImage: vi.fn(),
}));

const sessionState = vi.hoisted(() => ({
  loading: false,
  authenticated: true,
  csrf: "test-csrf",
  error: null,
}));

vi.mock("../../../lib/session", () => ({
  useSessionContext: () => sessionState,
}));

vi.mock("../../../lib/api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    api: {
      ...actual.api,
      getPresenceConfig,
      savePresenceConfig,
      applyPresence,
      clearPresence,
      getSongs,
      saveSongs,
      resolveSong,
      resolveYouTube,
      uploadPresenceImage,
    },
  };
});

const toast = {
  success: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
};

const CONFIG = {
  enabled: true,
  mode: "custom",
  status: "online",
  service: "",
  activities: [
    {
      type: "playing",
      name: "Cyberpunk 2077",
      details: "Night City",
      state: "",
      show_elapsed: true,
      elapsed_hours: 1,
    },
  ],
};

const SPOTIFY_CONFIG = {
  ...CONFIG,
  mode: "spotify",
  activities: [],
};

const SONGS = [
  {
    name: "0 AI NGHĨ",
    artist: "Wxrdie",
    id: "3IuxFX3kzxDRv4t9anPo43",
    duration_ms: 147272,
    image: "ab67616d00001e02ffbeabd7a6b240df9b086758",
  },
];

function mockLoad(config = CONFIG) {
  getPresenceConfig.mockResolvedValue({ config });
}

function mockSpotifyLoad(songs = SONGS) {
  getPresenceConfig.mockResolvedValue({ config: SPOTIFY_CONFIG });
  getSongs.mockResolvedValue({ songs });
}

beforeEach(() => {
  vi.clearAllMocks();
  sessionState.loading = false;
  sessionState.authenticated = true;
  sessionState.csrf = "test-csrf";
  sessionState.error = null;
  mockLoad();
  getSongs.mockResolvedValue({ songs: [] });
  savePresenceConfig.mockResolvedValue({ ok: true, config: CONFIG });
  applyPresence.mockResolvedValue({ queued: true });
  clearPresence.mockResolvedValue({ queued: true });
  saveSongs.mockResolvedValue({ ok: true, queued: false });
  resolveSong.mockResolvedValue({ song: SONGS[0] });
  resolveYouTube.mockResolvedValue({
    video: {
      video_id: "dQw4w9WgXcQ",
      title: "Never Gonna Give You Up",
      channel: "Rick Astley",
      image: "youtube:dQw4w9WgXcQ",
    },
  });
  uploadPresenceImage.mockResolvedValue({
    url: "https://cdn.example.com/upload.png",
  });
});

describe("RichPresenceFeature", () => {
  it("renders the existing presence and no token selector", async () => {
    render(<RichPresenceFeature toast={toast} />);

    const list = await screen.findByTestId("presence-list");
    expect(within(list).getByText("Cyberpunk 2077")).toBeInTheDocument();
    expect(within(list).getByText("Night City")).toBeInTheDocument();

    expect(screen.queryByText("Tokens")).not.toBeInTheDocument();
    expect(screen.queryByText("Alice")).not.toBeInTheDocument();
    expect(screen.queryByText("Bob")).not.toBeInTheDocument();
  });

  it("adds a presence through the type picker", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));

    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));

    const list = screen.getByTestId("presence-list");
    expect(within(list).getByText("Hades")).toBeInTheDocument();
    expect(within(list).getByText("Cyberpunk 2077")).toBeInTheDocument();
  });

  it("blocks adding a second activity of a used type", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Playing" }));

    expect(toast.error).toHaveBeenCalledWith(
      "This type is already in use — Discord shows only one activity per type.",
      "Rich Presence",
    );
    expect(screen.queryByPlaceholderText("Name")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    expect(screen.getByPlaceholderText("Name")).toBeInTheDocument();
  });

  it("warns when the config has duplicate activity types", async () => {
    getPresenceConfig.mockResolvedValue({
      config: {
        ...CONFIG,
        activities: [
          CONFIG.activities[0],
          { ...CONFIG.activities[0], name: "Second game" },
        ],
      },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(
      screen.getByText(/Discord only shows one activity per type/),
    ).toBeInTheDocument();
  });

  it("shows type-aware fields for listening and streaming", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    expect(screen.getByPlaceholderText("Name")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Album")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Streaming" }));
    expect(screen.getByPlaceholderText("Stream URL")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Album")).not.toBeInTheDocument();
    expect(screen.queryByText("Buttons")).not.toBeInTheDocument();
  });

  it("explains that custom buttons are hidden on your own profile", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));

    expect(
      screen.getByText(/hidden on your own profile/),
    ).toBeInTheDocument();
  });

  it("shows end time controls only for listening and watching", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    expect(screen.getByText("End time")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    expect(screen.getByText("End time")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Competing" }));
    expect(screen.queryByText("End time")).not.toBeInTheDocument();
  });

  it("preview shows the Listening to header and hides an unset platform badge", async () => {
    mockLoad({
      ...CONFIG,
      activities: [
        {
          type: "listening",
          name: "Lo-fi beats",
          details: "Chill",
          state: "",
          platform: "",
          show_elapsed: true,
          elapsed_hours: 1,
        },
      ],
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    const preview = screen.getByTestId("presence-preview");
    expect(within(preview).getByText(/Listening to/)).toBeInTheDocument();
    expect(within(preview).queryByText("Desktop")).not.toBeInTheDocument();
  });

  it("preview shows a countdown badge when end time is enabled", async () => {
    mockLoad({
      ...CONFIG,
      activities: [
        {
          type: "listening",
          name: "Lo-fi beats",
          details: "Chill",
          state: "",
          platform: "",
          show_elapsed: true,
          elapsed_hours: 1,
          show_end: true,
          end_minutes: 30,
        },
      ],
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    const preview = screen.getByTestId("presence-preview");
    expect(within(preview).getByText(/left/)).toBeInTheDocument();
  });

  it("changes the type when editing a presence", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Playing" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByPlaceholderText("Large text")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Listening" }));

    expect(
      screen.queryByPlaceholderText("Large text"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.activities[0].type).toBe("listening");
  });

  it("hides types used by other activities when editing", async () => {
    mockLoad({
      ...CONFIG,
      activities: [
        CONFIG.activities[0],
        {
          type: "listening",
          name: "Lo-fi beats",
          details: "",
          state: "",
          show_elapsed: true,
          elapsed_hours: 1,
        },
      ],
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getAllByRole("button", { name: "Edit" })[0]);

    expect(screen.getByText("Type")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Playing" })).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Listening" }),
    ).not.toBeInTheDocument();
  });

  it("requires a stream URL before saving a streaming presence", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Streaming" }));

    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Live on Twitch" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Streaming activities need a Twitch or YouTube URL.",
      "Rich Presence",
    );
    const list = screen.getByTestId("presence-list");
    expect(
      within(list).queryByText("Live on Twitch"),
    ).not.toBeInTheDocument();
    expect(within(list).getByText("Cyberpunk 2077")).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText("Stream URL"), {
      target: { value: "https://twitch.tv/foo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));

    expect(within(list).getByText("Live on Twitch")).toBeInTheDocument();
    expect(toast.error).toHaveBeenCalledTimes(1);
  });

  it("selects a platform from the collapsible list", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Competing" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Rocket League" },
    });

    const trigger = screen.getByRole("button", { name: "Platform" });
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(trigger);
    expect(trigger).toHaveAttribute("aria-expanded", "true");
    fireEvent.click(screen.getByRole("option", { name: "PS5" }));
    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveTextContent("PS5");

    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "Rocket League",
    );
    expect(added.platform).toBe("ps5");
  });

  it("defaults the application id for new presences", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "Hades",
    );
    expect(added.application_id).toBe("1459720870787547359");
  });

  it("shows the application id field prefilled with the default", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));

    expect(screen.getByPlaceholderText("Application ID")).toHaveValue(
      "1459720870787547359",
    );
  });

  it("selects a service preset and fills its application id", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });

    const trigger = screen.getByRole("button", { name: "Service" });
    expect(trigger).toHaveTextContent("Custom");
    fireEvent.click(trigger);
    fireEvent.click(screen.getByRole("option", { name: "Xbox" }));

    expect(trigger).toHaveTextContent("Xbox");
    expect(
      screen.queryByPlaceholderText("Application ID"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(/Application ID: 438122941302046720/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "Hades",
    );
    expect(added.application_id).toBe("438122941302046720");
  });

  it("clears the application id when the service is None", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Service" }));
    fireEvent.click(screen.getByRole("option", { name: "None" }));

    expect(
      screen.queryByPlaceholderText("Application ID"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "Hades",
    );
    expect(added.application_id).toBe("");
  });

  it("shows the header line and per-type hint", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Spotify" },
    });

    const header = screen.getByText(/Header shows:/);
    expect(header).toHaveTextContent("Listening to Spotify");
    expect(
      screen.getByText(/Album renders as the third line/),
    ).toBeInTheDocument();
  });

  it("maps a stored preset application id to its service", async () => {
    mockLoad({
      ...CONFIG,
      activities: [
        {
          ...CONFIG.activities[0],
          application_id: "981509069309354054",
        },
      ],
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    const trigger = screen.getByRole("button", { name: "Service" });
    expect(trigger).toHaveTextContent("Crunchyroll");
    expect(
      screen.queryByPlaceholderText("Application ID"),
    ).not.toBeInTheDocument();
  });

  it("hides the preview footnotes", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(
      screen.queryByText(/Buttons are only visible/),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Preview only/)).not.toBeInTheDocument();
  });

  it("renders status controls inside the preview section", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    const preview = screen.getByTestId("presence-preview");
    expect(
      within(preview).getByRole("button", { name: "Online" }),
    ).toBeInTheDocument();
    expect(
      within(preview).getByRole("button", { name: "Idle" }),
    ).toBeInTheDocument();
    expect(
      within(preview).getByRole("button", { name: "DND" }),
    ).toBeInTheDocument();
    expect(
      within(preview).getByRole("button", { name: "Invisible" }),
    ).toBeInTheDocument();

    fireEvent.click(within(preview).getByRole("button", { name: "DND" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.status).toBe("dnd");
  });

  it("preserves the stored service value through apply", async () => {
    getPresenceConfig.mockResolvedValue({
      config: { ...CONFIG, service: "desktop" },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    const list = screen.getByTestId("presence-list");
    fireEvent.click(within(list).getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.service).toBe("desktop");
  });

  it("warns about an unsupported stored service and clears it", async () => {
    getPresenceConfig.mockResolvedValue({
      config: { ...CONFIG, service: "samsumg" },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(
      screen.getByText(
        'Stored service "samsumg" is not supported — Apply will fail until it is cleared.',
      ),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Clear service" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.service).toBe("");
  });

  it("does not warn about a supported stored service", async () => {
    getPresenceConfig.mockResolvedValue({
      config: { ...CONFIG, service: "xbox" },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(
      screen.queryByText(/is not supported — Apply will fail/),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Clear service" }),
    ).not.toBeInTheDocument();
  });

  it("saves and applies the single presence entry", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() =>
      expect(savePresenceConfig).toHaveBeenCalledWith(
        { config: CONFIG },
        "test-csrf",
      ),
    );
    await waitFor(() =>
      expect(applyPresence).toHaveBeenCalledWith({}, "test-csrf"),
    );
    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith(
        "Presence applied.",
        "Rich Presence",
      ),
    );
  });

  it("disables adding when three presences exist", async () => {
    mockLoad({
      ...CONFIG,
      activities: [
        { type: "playing", name: "One" },
        { type: "playing", name: "Two" },
        { type: "playing", name: "Three" },
      ],
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(
      screen.getByRole("button", { name: "+ Add presence" }),
    ).toBeDisabled();
  });

  it("switches the main account to Spotify mode", async () => {
    getSongs.mockResolvedValue({ songs: SONGS });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Spotify" }));

    const list = screen.getByTestId("presence-list");
    expect(within(list).getByText(/Uses songs\.json/)).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Name")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));
    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.mode).toBe("spotify");
  });

  it("adds a custom presence in Spotify mode", async () => {
    mockSpotifyLoad();
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    const addButton = screen.getByRole("button", { name: "+ Add presence" });
    expect(addButton).toBeEnabled();
    fireEvent.click(addButton);
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));

    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Lo-fi beats" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));

    const list = screen.getByTestId("presence-list");
    expect(within(list).getByText("Lo-fi beats")).toBeInTheDocument();
    expect(within(list).getByText(/Uses songs\.json/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.mode).toBe("spotify");
    expect(
      payload.config.activities.some(
        (activity) =>
          activity.name === "Lo-fi beats" && activity.type === "listening",
      ),
    ).toBe(true);
  });

  it("warns instead of applying after removing the Spotify card", async () => {
    mockSpotifyLoad();
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Nothing to apply — add a presence first.",
      "Rich Presence",
    );
    expect(savePresenceConfig).not.toHaveBeenCalled();
  });

  it("warns instead of applying when there are no presences", async () => {
    getPresenceConfig.mockResolvedValue({
      config: { ...CONFIG, activities: [] },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Nothing to apply — add a presence first.",
      "Rich Presence",
    );
    expect(savePresenceConfig).not.toHaveBeenCalled();
  });

  it("warns when Spotify mode has no songs", async () => {
    mockSpotifyLoad([]);
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Add at least one Spotify song before applying.",
      "Rich Presence",
    );
    expect(savePresenceConfig).not.toHaveBeenCalled();
  });

  it("hints that only the first custom card is displayed", async () => {
    getPresenceConfig.mockResolvedValue({
      config: {
        ...CONFIG,
        activities: [
          CONFIG.activities[0],
          {
            type: "listening",
            name: "Lo-fi beats",
            details: "Chill",
            state: "",
            show_elapsed: true,
            elapsed_hours: 1,
          },
        ],
      },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(
      screen.getByText(/Discord shows only the first custom card/),
    ).toBeInTheDocument();
  });

  it("shows the songs panel with the loaded Spotify song", async () => {
    mockSpotifyLoad();
    render(<RichPresenceFeature toast={toast} />);

    const list = await screen.findByTestId("songs-list");
    expect(screen.getByText("Spotify Songs (1)")).toBeInTheDocument();
    expect(within(list).getByText("0 AI NGHĨ")).toBeInTheDocument();
    expect(within(list).getByText("Wxrdie")).toBeInTheDocument();
    expect(within(list).getByText("2:27")).toBeInTheDocument();
  });

  it("resolves details and adds a song", async () => {
    mockSpotifyLoad([]);
    resolveSong.mockResolvedValue({
      song: {
        name: "Never Gonna Give You Up",
        artist: "Rick Astley",
        id: "4cOdK2wGLETKBW3PvgPWqT",
        duration_ms: 213573,
        image: "ab67616d00001e02ffbeabd7a6b240df9b086758",
      },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("songs-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add song" }));
    fireEvent.change(screen.getByPlaceholderText("Spotify URL or ID"), {
      target: {
        value: "https://open.spotify.com/track/4cOdK2wGLETKBW3PvgPWqT",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Fetch details" }));

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Name")).toHaveValue(
        "Never Gonna Give You Up",
      ),
    );
    expect(screen.getByPlaceholderText("Artist")).toHaveValue("Rick Astley");
    expect(
      screen.getByPlaceholderText("Duration (seconds or m:ss)"),
    ).toHaveValue("3:33");

    fireEvent.click(screen.getByRole("button", { name: "Add song" }));

    await waitFor(() =>
      expect(saveSongs).toHaveBeenCalledWith(
        {
          songs: [
            {
              name: "Never Gonna Give You Up",
              artist: "Rick Astley",
              id: "4cOdK2wGLETKBW3PvgPWqT",
              duration_ms: 213000,
              image: "ab67616d00001e02ffbeabd7a6b240df9b086758",
            },
          ],
        },
        "test-csrf",
      ),
    );
  });

  it("rejects adding a duplicate song", async () => {
    mockSpotifyLoad();
    resolveSong.mockResolvedValue({ song: { ...SONGS[0] } });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("songs-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add song" }));
    fireEvent.change(screen.getByPlaceholderText("Spotify URL or ID"), {
      target: {
        value: "https://open.spotify.com/track/3IuxFX3kzxDRv4t9anPo43",
      },
    });
    fireEvent.click(screen.getByRole("button", { name: "Fetch details" }));

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Name")).toHaveValue("0 AI NGHĨ"),
    );

    fireEvent.click(screen.getByRole("button", { name: "Add song" }));

    expect(toast.error).toHaveBeenCalledWith(
      "This song is already in the list.",
      "Rich Presence",
    );
    expect(saveSongs).not.toHaveBeenCalled();
  });

  it("deletes a song and saves the remaining list", async () => {
    mockSpotifyLoad();
    render(<RichPresenceFeature toast={toast} />);

    const list = await screen.findByTestId("songs-list");
    fireEvent.click(within(list).getByRole("button", { name: "Delete" }));

    await waitFor(() =>
      expect(saveSongs).toHaveBeenCalledWith({ songs: [] }, "test-csrf"),
    );
  });

  it("warns when a Discord image link has expired", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    fireEvent.change(screen.getByPlaceholderText("Large image"), {
      target: {
        value:
          "https://cdn.discordapp.com/attachments/1/2/x.gif?ex=6a69b58d&is=6a68640d&hm=abc",
      },
    });

    expect(
      screen.getByText(/This Discord link expired on/),
    ).toBeInTheDocument();
    expect(screen.getByText("GIF supported.")).toBeInTheDocument();
  });

  it("previews the first Spotify song", async () => {
    mockSpotifyLoad();
    render(<RichPresenceFeature toast={toast} />);

    const preview = screen.getByTestId("presence-preview");
    expect(await within(preview).findByText("0 AI NGHĨ")).toBeInTheDocument();
    expect(within(preview).getByText("by Wxrdie")).toBeInTheDocument();
    expect(within(preview).getByText("Spotify")).toBeInTheDocument();
  });

  it("stops the presence without changing the config", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Stop presence" }));

    await waitFor(() =>
      expect(clearPresence).toHaveBeenCalledWith({}, "test-csrf"),
    );
    expect(savePresenceConfig).not.toHaveBeenCalled();
    expect(toast.info).toHaveBeenCalledWith(
      "Presence stopped.",
      "Rich Presence",
    );
  });

  it("hints when presences share one application id", async () => {
    getPresenceConfig.mockResolvedValue({
      config: {
        ...CONFIG,
        activities: [
          { ...CONFIG.activities[0], application_id: "111111111111111111" },
          {
            type: "listening",
            name: "Lo-fi beats",
            application_id: "111111111111111111",
          },
        ],
      },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(
      screen.getByText(/share one Application ID/),
    ).toBeInTheDocument();
  });

  it("does not hint when presences use different application ids", async () => {
    getPresenceConfig.mockResolvedValue({
      config: {
        ...CONFIG,
        activities: [
          { ...CONFIG.activities[0], application_id: "111111111111111111" },
          {
            type: "listening",
            name: "Lo-fi beats",
            application_id: "222222222222222222",
          },
        ],
      },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(
      screen.queryByText(/share one Application ID/),
    ).not.toBeInTheDocument();
  });

  it("keeps custom activities when switching to Spotify", async () => {
    mockLoad({
      ...CONFIG,
      activities: [
        CONFIG.activities[0],
        {
          type: "listening",
          name: "Lo-fi beats",
          details: "",
          state: "",
          show_elapsed: true,
          elapsed_hours: 1,
        },
      ],
    });
    getSongs.mockResolvedValue({ songs: SONGS });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Spotify" }));

    const list = screen.getByTestId("presence-list");
    expect(within(list).getByText("Cyberpunk 2077")).toBeInTheDocument();
    expect(within(list).getByText("Lo-fi beats")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Remove" }));

    expect(within(list).getByText("Cyberpunk 2077")).toBeInTheDocument();
    expect(within(list).getByText("Lo-fi beats")).toBeInTheDocument();
    expect(screen.queryByText(/Uses songs\.json/)).not.toBeInTheDocument();
  });

  it("slices custom activities to two when switching to Spotify", () => {
    const activities = [
      { type: "playing", name: "One" },
      { type: "listening", name: "Two" },
      { type: "watching", name: "Three" },
    ];

    expect(sliceActivitiesForSpotify(activities)).toEqual([
      activities[0],
      activities[1],
    ]);
  });

  it("passes through a stored service value outside the preset list", async () => {
    getPresenceConfig.mockResolvedValue({
      config: { ...CONFIG, service: "embedded" },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.service).toBe("embedded");
  });

  it("blocks saving a presence without a name", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Give this presence a name first.",
      "Rich Presence",
    );
    expect(screen.getByPlaceholderText("Name")).toBeInTheDocument();
    expect(
      within(screen.getByTestId("presence-list")).queryByText(
        "Untitled presence",
      ),
    ).not.toBeInTheDocument();
  });

  it("blocks a streaming URL that is not Twitch or YouTube", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Streaming" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Live show" },
    });
    fireEvent.change(screen.getByPlaceholderText("Stream URL"), {
      target: { value: "https://example.com/live" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Stream URLs must start with https://twitch.tv/, https://www.twitch.tv/, https://youtube.com/ or https://www.youtube.com/.",
      "Rich Presence",
    );
    expect(
      within(screen.getByTestId("presence-list")).queryByText("Live show"),
    ).not.toBeInTheDocument();
  });

  it("blocks a non-digit application id", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });
    fireEvent.change(screen.getByPlaceholderText("Application ID"), {
      target: { value: "abc123" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Application ID must contain digits only.",
      "Rich Presence",
    );
    expect(
      within(screen.getByTestId("presence-list")).queryByText("Hades"),
    ).not.toBeInTheDocument();
  });

  it("keeps the enabled toggle off when editing an existing presence", async () => {
    mockLoad({ ...CONFIG, enabled: false });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Cyberpunk 2078" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.enabled).toBe(false);
  });

  it("enables the presence when adding a new one", async () => {
    mockLoad({ ...CONFIG, enabled: false });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.enabled).toBe(true);
  });

  it("blocks applying when activity types are duplicated", async () => {
    getPresenceConfig.mockResolvedValue({
      config: {
        ...CONFIG,
        activities: [
          CONFIG.activities[0],
          { ...CONFIG.activities[0], name: "Second game" },
        ],
      },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Discord shows only one activity per type — fix the duplicates before applying.",
      "Rich Presence",
    );
    expect(savePresenceConfig).not.toHaveBeenCalled();
  });

  it("applies duplicate activity types when the config is disabled", async () => {
    getPresenceConfig.mockResolvedValue({
      config: {
        ...CONFIG,
        enabled: false,
        activities: [
          CONFIG.activities[0],
          { ...CONFIG.activities[0], name: "Second game" },
        ],
      },
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    expect(toast.error).not.toHaveBeenCalledWith(
      "Discord shows only one activity per type — fix the duplicates before applying.",
      "Rich Presence",
    );
    const [payload] = savePresenceConfig.mock.calls[0];
    expect(payload.config.enabled).toBe(false);
  });

  it("disables list actions while a save is pending", async () => {
    savePresenceConfig.mockReturnValue(new Promise(() => {}));
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled(),
    );
    expect(screen.getByRole("button", { name: "Delete" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "+ Add presence" }),
    ).toBeDisabled();
  });

  it("opens a stored activity with at most two button rows", async () => {
    mockLoad({
      ...CONFIG,
      activities: [
        {
          ...CONFIG.activities[0],
          buttons: [
            { label: "One", url: "https://one.example" },
            { label: "Two", url: "https://two.example" },
            { label: "Three", url: "https://three.example" },
          ],
        },
      ],
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getAllByPlaceholderText("Button label")).toHaveLength(2);
    expect(screen.queryByDisplayValue("Three")).not.toBeInTheDocument();
  });

  it("does not save a button without a url", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });
    fireEvent.click(screen.getByRole("button", { name: "+ Add button" }));
    fireEvent.change(screen.getByPlaceholderText("Button label"), {
      target: { value: "Only label" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "Hades",
    );
    expect(added.buttons).toEqual([]);
  });

  it("gives the elapsed and end time toggles accessible names", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));

    expect(
      screen.getByRole("switch", { name: "Elapsed" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("switch", { name: "End time" }),
    ).toBeInTheDocument();
  });

  it("supports keyboard navigation in the service select", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));

    const trigger = screen.getByRole("button", { name: "Service" });
    fireEvent.keyDown(trigger, { key: "ArrowDown" });

    expect(trigger).toHaveAttribute("aria-expanded", "true");
    expect(trigger).toHaveAttribute("aria-activedescendant");

    fireEvent.keyDown(trigger, { key: "ArrowDown" });
    fireEvent.keyDown(trigger, { key: "Enter" });

    expect(trigger).toHaveAttribute("aria-expanded", "false");
    expect(trigger).toHaveTextContent("Xbox");
  });

  it("shows the Spotify presence limit in the panel title", async () => {
    mockSpotifyLoad();
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    expect(screen.getByText("Presences (0/2)")).toBeInTheDocument();
  });

  it("shows a stored embedded platform in the platform select", async () => {
    mockLoad({
      ...CONFIG,
      activities: [{ ...CONFIG.activities[0], platform: "embedded" }],
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(screen.getByRole("button", { name: "Platform" })).toHaveTextContent(
      "Embedded",
    );
  });

  it("restores the typed custom application id after switching presets", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));

    fireEvent.change(screen.getByPlaceholderText("Application ID"), {
      target: { value: "123456789012345678" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Service" }));
    fireEvent.click(screen.getByRole("option", { name: "Xbox" }));
    expect(
      screen.queryByPlaceholderText("Application ID"),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Service" }));
    fireEvent.click(screen.getByRole("option", { name: "Custom" }));

    expect(screen.getByPlaceholderText("Application ID")).toHaveValue(
      "123456789012345678",
    );
  });

  it("fills the platform and default image from a service preset", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Service" }));
    fireEvent.click(screen.getByRole("option", { name: "Xbox" }));

    expect(screen.getByRole("button", { name: "Platform" })).toHaveTextContent(
      "Xbox",
    );
    expect(screen.getByPlaceholderText("Large image")).toHaveValue(
      "https://cdn.simpleicons.org/xbox/107C10",
    );

    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "Hades",
    );
    expect(added.application_id).toBe("438122941302046720");
    expect(added.platform).toBe("xbox");
    expect(added.large_image).toBe(
      "https://cdn.simpleicons.org/xbox/107C10",
    );
  });

  it("keeps an existing platform and image when a preset is picked", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));

    fireEvent.click(screen.getByRole("button", { name: "Platform" }));
    fireEvent.click(screen.getByRole("option", { name: "PS5" }));
    fireEvent.change(screen.getByPlaceholderText("Large image"), {
      target: { value: "https://example.com/custom.png" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Service" }));
    fireEvent.click(screen.getByRole("option", { name: "Xbox" }));

    expect(screen.getByRole("button", { name: "Platform" })).toHaveTextContent(
      "PS5",
    );
    expect(screen.getByPlaceholderText("Large image")).toHaveValue(
      "https://example.com/custom.png",
    );
  });

  it("shows the elapsed time in minutes", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));

    expect(screen.getByLabelText("Elapsed minutes")).toHaveValue(60);
  });

  it("stores elapsed minutes as hours when saving", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });
    fireEvent.change(screen.getByLabelText("Elapsed minutes"), {
      target: { value: "25" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "Hades",
    );
    expect(added.elapsed_hours).toBeCloseTo(25 / 60, 4);
  });

  it("shows the progress row only for listening and watching", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    expect(
      screen.getByRole("switch", { name: "Progress" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    expect(
      screen.getByRole("switch", { name: "Progress" }),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Competing" }));
    expect(
      screen.queryByRole("switch", { name: "Progress" }),
    ).not.toBeInTheDocument();
  });

  it("enables progress with a 30 minute default and forces elapsed", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));

    const progressMinutes = screen.getByLabelText("Progress minutes");
    expect(progressMinutes).toBeDisabled();
    expect(progressMinutes).toHaveAttribute("min", "1");
    expect(progressMinutes).toHaveAttribute("max", "1440");

    const elapsedToggle = screen.getByRole("switch", { name: "Elapsed" });
    fireEvent.click(elapsedToggle);
    expect(elapsedToggle).toHaveAttribute("aria-checked", "false");

    fireEvent.click(screen.getByRole("switch", { name: "Progress" }));

    expect(progressMinutes).toBeEnabled();
    expect(progressMinutes).toHaveValue(30);
    expect(elapsedToggle).toHaveAttribute("aria-checked", "true");
    expect(elapsedToggle).toBeDisabled();
    expect(screen.queryByText("End time")).not.toBeInTheDocument();
    expect(
      within(screen.getByTestId("presence-preview")).getByTestId(
        "presence-progress-bar",
      ),
    ).toBeInTheDocument();
  });

  it("saves duration_minutes when progress is enabled", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "Hades" },
    });
    fireEvent.click(screen.getByRole("switch", { name: "Progress" }));
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "Hades",
    );
    expect(added.duration_minutes).toBe(30);
  });

  it("renders the progress bar instead of the countdown in the preview", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Listening" }));
    fireEvent.click(screen.getByRole("switch", { name: "End time" }));

    expect(
      within(screen.getByTestId("presence-preview")).getByText(/left/),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Progress" }));

    const preview = screen.getByTestId("presence-preview");
    expect(
      within(preview).getByTestId("presence-progress-bar"),
    ).toBeInTheDocument();
    expect(within(preview).queryByText(/left/)).not.toBeInTheDocument();
  });

  it("normalizes elapsed on when editing a progress activity", async () => {
    mockLoad({
      ...CONFIG,
      activities: [
        {
          type: "watching",
          name: "Anime",
          duration_minutes: 24,
          show_elapsed: false,
        },
      ],
    });
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "Edit" }));

    expect(
      screen.getByRole("switch", { name: "Elapsed" }),
    ).toHaveAttribute("aria-checked", "true");
    expect(
      screen.getByRole("switch", { name: "Progress" }),
    ).toHaveAttribute("aria-checked", "true");
  });

  it("prefills streaming presences with Twitch defaults", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Streaming" }));

    expect(screen.getByPlaceholderText("Name")).toHaveValue("Twitch");
    expect(screen.getByPlaceholderText("Large image")).toHaveValue(
      "https://cdn.simpleicons.org/twitch/9146FF",
    );
  });

  it("fills the Watch Stream button with the stream URL", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Streaming" }));
    fireEvent.change(screen.getByPlaceholderText("Stream URL"), {
      target: { value: "https://twitch.tv/shadowbyte" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.type === "streaming",
    );
    expect(added.buttons).toEqual([
      { label: "Watch Stream", url: "https://twitch.tv/shadowbyte" },
    ]);
  });

  it("fills empty presence fields from a YouTube URL", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));
    fireEvent.change(screen.getByPlaceholderText("Name"), {
      target: { value: "My video" },
    });
    fireEvent.change(screen.getByPlaceholderText("YouTube URL"), {
      target: { value: "https://www.youtube.com/watch?v=dQw4w9WgXcQ" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Fetch from YouTube" }));

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Details — line 1")).toHaveValue(
        "Rick Astley",
      ),
    );
    expect(screen.getByPlaceholderText("Name")).toHaveValue("My video");
    expect(screen.getByPlaceholderText("Large image")).toHaveValue(
      "youtube:dQw4w9WgXcQ",
    );
    expect(resolveYouTube).toHaveBeenCalledWith(
      { url: "https://www.youtube.com/watch?v=dQw4w9WgXcQ" },
      "test-csrf",
    );
    expect(toast.success).toHaveBeenCalledWith(
      "YouTube details filled.",
      "Rich Presence",
    );

    fireEvent.click(screen.getByRole("button", { name: "Save presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    await waitFor(() => expect(savePresenceConfig).toHaveBeenCalled());
    const [payload] = savePresenceConfig.mock.calls[0];
    const added = payload.config.activities.find(
      (activity) => activity.name === "My video",
    );
    expect(added.details).toBe("Rick Astley");
    expect(added.large_image).toBe("youtube:dQw4w9WgXcQ");
  });

  it("uploads a large image and fills the field", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));

    const file = new File(["hello"], "art.png", { type: "image/png" });
    fireEvent.change(screen.getByTestId("large-image-upload"), {
      target: { files: [file] },
    });

    await waitFor(() =>
      expect(screen.getByPlaceholderText("Large image")).toHaveValue(
        "https://cdn.example.com/upload.png",
      ),
    );
    expect(uploadPresenceImage).toHaveBeenCalledWith(
      { filename: "art.png", data: "aGVsbG8=" },
      "test-csrf",
    );
    expect(toast.success).toHaveBeenCalledWith(
      "Image uploaded.",
      "Rich Presence",
    );
  });

  it("rejects an image larger than 700 KB", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));

    const file = new File([new Uint8Array(700 * 1024 + 1)], "big.png", {
      type: "image/png",
    });
    fireEvent.change(screen.getByTestId("large-image-upload"), {
      target: { files: [file] },
    });

    expect(toast.error).toHaveBeenCalledWith(
      "Image must be 700 KB or smaller.",
      "Rich Presence",
    );
    expect(uploadPresenceImage).not.toHaveBeenCalled();
  });

  it("shows the image helper hints", async () => {
    render(<RichPresenceFeature toast={toast} />);
    await screen.findByTestId("presence-list");

    fireEvent.click(screen.getByRole("button", { name: "+ Add presence" }));
    fireEvent.click(screen.getByRole("button", { name: "Watching" }));

    expect(
      screen.getByText("Paste a YouTube link to use its thumbnail."),
    ).toBeInTheDocument();
    expect(
      screen.getByText("Uploaded images are hosted publicly."),
    ).toBeInTheDocument();
  });

  it("does not load presence data before the dashboard is paired", async () => {
    sessionState.authenticated = false;
    sessionState.csrf = null;

    render(<RichPresenceFeature toast={toast} />);

    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled(),
    );
    expect(getPresenceConfig).not.toHaveBeenCalled();
    expect(getSongs).not.toHaveBeenCalled();
  });

  it("blocks Apply with a pairing message when unpaired", async () => {
    sessionState.authenticated = false;
    sessionState.csrf = null;

    render(<RichPresenceFeature toast={toast} />);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Apply" })).toBeEnabled(),
    );

    fireEvent.click(screen.getByRole("button", { name: "Apply" }));

    expect(toast.error).toHaveBeenCalledWith(
      "Pair the dashboard first.",
      "Rich Presence",
    );
    expect(savePresenceConfig).not.toHaveBeenCalled();
    expect(applyPresence).not.toHaveBeenCalled();
  });
});
