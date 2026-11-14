import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import UtilityFeature from "./UtilityFeature";

const {
  utilityWeather,
  utilityImage,
  utilityEmojiCopy,
  utilityClone,
  getCloneStatus,
  getEmojiCopyStatus,
} = vi.hoisted(() => ({
  utilityWeather: vi.fn(),
  utilityImage: vi.fn(),
  utilityEmojiCopy: vi.fn(),
  utilityClone: vi.fn(),
  getCloneStatus: vi.fn(),
  getEmojiCopyStatus: vi.fn(),
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
    api: {
      utilityWeather,
      utilityImage,
      utilityEmojiCopy,
      utilityClone,
      getCloneStatus,
      getEmojiCopyStatus,
    },
  };
});

const toast = {
  success: vi.fn(),
  info: vi.fn(),
  error: vi.fn(),
};

beforeEach(() => {
  vi.resetAllMocks();
});

describe("UtilityFeature", () => {
  it("runs weather and renders the result", async () => {
    utilityWeather.mockResolvedValue({
      ok: true,
      data: {
        location: "Hanoi, Vietnam",
        latitude: 21.03,
        longitude: 105.85,
        temperature_c: 31.2,
        feels_like_c: 35,
        humidity: 70,
        wind_kmh: 8.5,
        description: "Mainly clear 🌤️",
      },
    });

    render(<UtilityFeature toast={toast} />);
    fireEvent.change(screen.getByPlaceholderText("City or lat,lon"), {
      target: { value: "Hanoi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Get" }));

    expect(await screen.findByText("Hanoi, Vietnam")).toBeInTheDocument();
    expect(screen.getByText("31.2°C")).toBeInTheDocument();
    expect(screen.getByText("Humidity")).toBeInTheDocument();
    expect(screen.getByText("Wind")).toBeInTheDocument();
    expect(screen.getByText("Feels like")).toBeInTheDocument();
    expect(screen.getByText("Coordinates")).toBeInTheDocument();
    expect(screen.getByText("70%")).toBeInTheDocument();
    expect(screen.getByText("8.5 km/h")).toBeInTheDocument();
    expect(screen.getByText("21.03, 105.85")).toBeInTheDocument();
    expect(screen.getByTestId("weather-card").className).toContain(
      "h-[230px]",
    );
    expect(utilityWeather).toHaveBeenCalledWith(
      { location: "Hanoi" },
      "test-csrf",
    );
  });

  it("keeps fixed-size placeholders before data arrives", () => {
    render(<UtilityFeature toast={toast} />);

    expect(screen.getByText("No weather data yet")).toBeInTheDocument();
    expect(screen.getByText("Your image will appear here")).toBeInTheDocument();
    expect(screen.getByTestId("weather-card").className).toContain(
      "h-[230px]",
    );
    expect(screen.getByTestId("weather-card").className).toContain(
      "sm:h-[170px]",
    );
    expect(screen.getByTestId("image-card").className).toContain("h-[170px]");
  });

  it("generates an image preview URL", async () => {
    utilityImage.mockResolvedValue({
      ok: true,
      data: {
        prompt: "cat in space",
        url: "https://image.pollinations.ai/prompt/cat%20in%20space",
      },
    });

    render(<UtilityFeature toast={toast} />);
    fireEvent.change(screen.getByPlaceholderText("Describe the image…"), {
      target: { value: "cat in space" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Generate" }));

    const image = await screen.findByAltText("cat in space");
    expect(image).toHaveAttribute(
      "src",
      "https://image.pollinations.ai/prompt/cat%20in%20space",
    );
    expect(screen.getByTestId("image-card").className).toContain("h-[170px]");
    expect(utilityImage).toHaveBeenCalledWith(
      { prompt: "cat in space" },
      "test-csrf",
    );
  });

  it("sends optional emoji IDs and reports bot offline", async () => {
    utilityEmojiCopy.mockResolvedValue({
      applied: false,
      reason: "bot_offline",
      data: {
        source_id: "111",
        target_id: "222",
        emoji_ids: ["333", "444"],
      },
      result: {},
    });

    render(<UtilityFeature toast={toast} />);
    fireEvent.change(screen.getByPlaceholderText("Emoji source guild ID"), {
      target: { value: "111" },
    });
    fireEvent.change(screen.getByPlaceholderText("Emoji target guild ID"), {
      target: { value: "222" },
    });
    fireEvent.change(screen.getByPlaceholderText("Emoji IDs (blank = all)"), {
      target: { value: "333, 444" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Copy Emojis" }));

    expect(
      await screen.findByText(/Not executed — bot offline/i),
    ).toBeInTheDocument();
    expect(utilityEmojiCopy).toHaveBeenCalledWith(
      {
        source_id: "111",
        target_id: "222",
        emoji_ids: ["333", "444"],
      },
      "test-csrf",
    );
  });

  it("polls queued emoji copy status", async () => {
    utilityEmojiCopy.mockResolvedValue({
      queued: true,
      request_id: "emoji-1",
    });
    getEmojiCopyStatus.mockResolvedValue({
      status: "success",
      message: "Copied 2/2 emojis",
    });

    render(<UtilityFeature toast={toast} />);
    fireEvent.change(screen.getByPlaceholderText("Emoji source guild ID"), {
      target: { value: "111" },
    });
    fireEvent.change(screen.getByPlaceholderText("Emoji target guild ID"), {
      target: { value: "222" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Copy Emojis" }));

    expect(
      await screen.findByText(/Emoji copy queued/),
    ).toBeInTheDocument();
    await waitFor(
      () => {
        expect(screen.getByText("Copied 2/2 emojis")).toBeInTheDocument();
      },
      { timeout: 4000 },
    );
    expect(getEmojiCopyStatus).toHaveBeenCalledWith("emoji-1");
  });

  it("requires clone confirmation before calling the API", async () => {
    utilityClone.mockResolvedValue({
      applied: false,
      reason: "bot_offline",
      data: { source_id: "111", target_id: "222" },
      result: {},
    });

    render(<UtilityFeature toast={toast} />);
    fireEvent.change(screen.getByPlaceholderText("Clone source guild ID"), {
      target: { value: "111" },
    });
    fireEvent.change(screen.getByPlaceholderText("Clone target guild ID"), {
      target: { value: "222" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run .clone" }));

    expect(screen.getByText("Destructive Operation")).toBeInTheDocument();
    expect(utilityClone).not.toHaveBeenCalled();

    fireEvent.click(
      screen.getByRole("button", { name: "Yes, Run .clone" }),
    );

    expect(
      await screen.findByText(/Not executed — bot offline/i),
    ).toBeInTheDocument();
    expect(utilityClone).toHaveBeenCalledWith(
      {
        source_id: "111",
        target_id: "222",
        confirm: true,
        options: { info: true, structure: true, emojis: false },
      },
      "test-csrf",
    );
  });

  it("sends only the enabled clone sections", async () => {
    utilityClone.mockResolvedValue({
      applied: false,
      reason: "bot_offline",
    });

    render(<UtilityFeature toast={toast} />);
    fireEvent.change(screen.getByPlaceholderText("Clone source guild ID"), {
      target: { value: "111" },
    });
    fireEvent.change(screen.getByPlaceholderText("Clone target guild ID"), {
      target: { value: "222" },
    });

    const emojiLabel = screen.getByText("Emojis");
    const emojiRow = emojiLabel.parentElement.parentElement;
    fireEvent.click(within(emojiRow).getByRole("switch"));

    const structureLabel = screen.getByText("Structure");
    const structureRow = structureLabel.parentElement.parentElement;
    fireEvent.click(within(structureRow).getByRole("switch"));

    fireEvent.click(screen.getByRole("button", { name: "Run .clone" }));
    fireEvent.click(
      screen.getByRole("button", { name: "Yes, Run .clone" }),
    );

    await waitFor(() => {
      expect(utilityClone).toHaveBeenCalledWith(
        {
          source_id: "111",
          target_id: "222",
          confirm: true,
          options: { info: true, structure: false, emojis: true },
        },
        "test-csrf",
      );
    });
  });

  it("requires at least one clone option", () => {
    render(<UtilityFeature toast={toast} />);
    fireEvent.change(screen.getByPlaceholderText("Clone source guild ID"), {
      target: { value: "111" },
    });
    fireEvent.change(screen.getByPlaceholderText("Clone target guild ID"), {
      target: { value: "222" },
    });

    const infoRow = screen.getByText("Server info").parentElement.parentElement;
    fireEvent.click(within(infoRow).getByRole("switch"));
    const structureRow =
      screen.getByText("Structure").parentElement.parentElement;
    fireEvent.click(within(structureRow).getByRole("switch"));

    fireEvent.click(screen.getByRole("button", { name: "Run .clone" }));

    expect(
      screen.getByText("Select at least one clone option."),
    ).toBeInTheDocument();
    expect(utilityClone).not.toHaveBeenCalled();
  });
});
