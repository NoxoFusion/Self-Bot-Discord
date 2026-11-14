import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { Sidebar } from "./page";

const { getStatus } = vi.hoisted(() => ({ getStatus: vi.fn() }));
const { sessionState } = vi.hoisted(() => ({
  sessionState: { loading: false, authenticated: true, error: null },
}));

vi.mock("../lib/session", () => ({
  useSessionContext: () => sessionState,
}));

vi.mock("../lib/api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    api: { ...actual.api, getStatus },
  };
});

beforeEach(() => {
  vi.clearAllMocks();
  sessionState.loading = false;
  sessionState.authenticated = true;
  sessionState.error = null;
  getStatus.mockResolvedValue({
    bot: {
      state: "online",
      username: "alice",
      user_id: "123456789012345678",
      avatar_url: "https://cdn.example/avatar.png",
    },
  });
});

describe("Sidebar", () => {
  it("shows the authenticated Discord user instead of creator branding", async () => {
    render(<Sidebar activeView="dashboard" setView={() => {}} />);

    expect(await screen.findByText("alice")).toBeInTheDocument();
    const avatar = screen.getByAltText("alice avatar");
    expect(avatar).toHaveAttribute("src", "https://cdn.example/avatar.png");
    expect(avatar).toHaveAttribute("width", "64");
    expect(avatar).toHaveAttribute("height", "64");
    expect(screen.queryByText("Noxo Fusion")).not.toBeInTheDocument();
    expect(
      screen.queryByText("Tool Creator & Lead Developer"),
    ).not.toBeInTheDocument();
  });

  it("renders the initial disc when the status has no avatarUrl", async () => {
    getStatus.mockResolvedValue({
      bot: {
        state: "online",
        username: "alice",
        user_id: "123456789012345678",
      },
    });

    render(<Sidebar activeView="dashboard" setView={() => {}} />);

    const disc = await screen.findByText("A");
    expect(disc).toBeInTheDocument();
    expect(disc.style.background).toContain("linear-gradient");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("shows the pending disc while the bot status is loading", () => {
    getStatus.mockReturnValue(new Promise(() => {}));

    render(<Sidebar activeView="dashboard" setView={() => {}} />);

    expect(screen.getByText("…")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("keeps the user header display-only", async () => {
    const setView = vi.fn();
    render(<Sidebar activeView="dashboard" setView={setView} />);

    const username = await screen.findByText("alice");
    expect(username.closest("button")).toBeNull();

    fireEvent.click(username);
    expect(setView).not.toHaveBeenCalled();
  });

  it("moves Settings to a labelled bottom navigation item and removes the profile card", async () => {
    render(<Sidebar activeView="dashboard" setView={() => {}} />);

    await screen.findByText("alice");

    expect(screen.getByText("Settings")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Settings" }),
    ).toBeInTheDocument();
    const buttons = screen.getAllByRole("button");
    expect(buttons.at(-1)).toHaveTextContent("Settings");
    expect(screen.queryByTitle("View Profile")).not.toBeInTheDocument();
    expect(screen.queryByText("Bot profile")).not.toBeInTheDocument();
  });

  it("follows the accent theme for inactive and active navigation", async () => {
    const setView = vi.fn();
    const { rerender } = render(
      <Sidebar activeView="dashboard" setView={setView} />,
    );

    await screen.findByText("alice");

    const about = screen.getByRole("button", { name: "About" });
    expect(about).toHaveClass("text-[#94A3B8]");
    expect(about).toHaveClass("font-medium");
    expect(about).toHaveClass("tracking-[0.025em]");
    expect(about).toHaveClass("hover:translate-x-[3px]");
    expect(about).toHaveClass("focus-visible:ring-2");
    expect(about).not.toHaveAttribute("aria-current");
    expect(about.className).not.toMatch(/\bsky-/);
    expect(about.className).not.toContain("text-shadow");
    expect(about.style.getPropertyValue("--nav-hover-bg")).toMatch(
      /^#[0-9a-f]{6}14$/i,
    );

    fireEvent.click(about);
    expect(setView).toHaveBeenCalledWith("about");

    rerender(<Sidebar activeView="voice" setView={setView} />);

    const voice = screen.getByRole("button", { name: /Voice/ });
    expect(voice).toHaveAttribute("aria-current", "page");
    expect(voice).toHaveClass("text-white");
    expect(voice.style.background).toContain("linear-gradient");
    const accent = voice.style.getPropertyValue("--accent");
    expect(accent).toMatch(/^#[0-9a-f]{6}$/i);
    expect(voice.style.background.toLowerCase()).toContain(accent.toLowerCase());
    expect(voice.style.getPropertyValue("--tw-ring-color")).toMatch(
      /^#[0-9a-f]{6}99$/i,
    );
    expect(voice.className).not.toMatch(/\bsky-/);
    expect(voice.className).not.toContain("text-shadow");
    expect(voice.className).not.toContain("shadow-[");
    expect(screen.getByRole("button", { name: "About" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("falls back to Discord User when the status has no username", async () => {
    getStatus.mockResolvedValue({ bot: { state: "offline", username: null } });

    render(<Sidebar activeView="dashboard" setView={() => {}} />);

    expect(await screen.findByText("Discord User")).toBeInTheDocument();
  });

  it("shows Not paired when the local session is not authenticated", () => {
    sessionState.authenticated = false;

    render(<Sidebar activeView="dashboard" setView={() => {}} />);

    expect(screen.getByTitle("Not paired")).toBeInTheDocument();
  });
});
