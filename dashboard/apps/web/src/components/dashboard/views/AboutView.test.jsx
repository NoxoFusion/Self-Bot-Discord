import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import AboutView from "./AboutView";

vi.mock("../../../lib/session", () => ({
  useSessionContext: () => ({
    loading: false,
    authenticated: false,
    csrf: null,
  }),
}));

describe("AboutView", () => {
  it("uses the GitHub avatar and exposes the new profile sections", () => {
    render(<AboutView />);

    expect(screen.getByAltText("Noxo Fusion")).toHaveAttribute(
      "src",
      "https://github.com/NoxoFusion.png",
    );
    expect(
      screen.getByText("Automation Specialist & Lead Developer"),
    ).toBeInTheDocument();
    expect(screen.getByText("Core Highlights")).toBeInTheDocument();
    expect(screen.getByText("Anti-Flag Telemetry")).toBeInTheDocument();
    expect(screen.getByText("Async Multi-Engine")).toBeInTheDocument();
    expect(screen.getByText("Zero-Leak Control Plane")).toBeInTheDocument();
    expect(screen.getByText("@NoxoFusion")).toBeInTheDocument();
    expect(screen.getByText("@noxofusion")).toBeInTheDocument();
    expect(screen.getByText("github.com/NoxoFusion")).toBeInTheDocument();
  });
});
