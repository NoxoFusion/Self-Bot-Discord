import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import DashboardView from "./DashboardView";

const { getStatus, getCapabilities } = vi.hoisted(() => ({
  getStatus: vi.fn(),
  getCapabilities: vi.fn(),
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
      getStatus,
      getCapabilities,
    },
  };
});

beforeEach(() => {
  vi.resetAllMocks();
  getStatus.mockResolvedValue({
    bot: {
      state: "offline",
      username: null,
      user_id: null,
      latency_ms: null,
      guild_count: 0,
      uptime_seconds: 0,
    },
    api: { version: "0.1.0", uptime_seconds: 42 },
    features: {},
    warnings: ["Bot token not configured"],
  });
  getCapabilities.mockResolvedValue({
    features: [
      {
        id: "utility",
        label: "Utility",
        status: "partial",
        reason: "Weather and image work",
      },
    ],
  });
});

describe("DashboardView", () => {
  it("shows a prominent Not configured state and readable system health", async () => {
    render(<DashboardView />);

    expect(await screen.findByText("System health")).toBeInTheDocument();
    expect(screen.getAllByText("Not configured").length).toBeGreaterThan(0);
    expect(screen.getByText("Last updated")).toBeInTheDocument();
    expect(screen.getByText("Bot state")).toBeInTheDocument();
    expect(screen.getAllByText("API version").length).toBeGreaterThanOrEqual(2);
    expect(screen.getAllByText("0.1.0").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("127.0.0.1:8765")).toBeInTheDocument();
  });
});
