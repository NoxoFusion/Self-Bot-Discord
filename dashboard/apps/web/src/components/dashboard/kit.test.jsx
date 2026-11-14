import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Activity, Headphones, Radio, Server, Trash2 } from "lucide-react";
import { FeatureHero } from "./kit";

const fiveStats = [
  { icon: Headphones, label: "Tokens", value: "42", color: "#58B8E8" },
  { icon: Activity, label: "In Voice", value: "3", color: "#23A55A" },
  { icon: Radio, label: "Streaming", value: "1", color: "#F23F43" },
  { icon: Server, label: "Gateway", value: "OK", color: "#7C5CFF" },
  { icon: Trash2, label: "Removed", value: "0", color: "#F5B642" },
];

describe("FeatureHero stats layout", () => {
  it("renders all 5 hero stats in a single-row layout container", () => {
    render(
      <FeatureHero
        icon={Headphones}
        title="Voice Manager"
        tag="GATEWAY V10"
        accent="#58B8E8"
        stats={fiveStats}
      />,
    );

    expect(screen.getByText("Tokens")).toBeInTheDocument();
    expect(screen.getByText("In Voice")).toBeInTheDocument();
    expect(screen.getByText("Streaming")).toBeInTheDocument();
    expect(screen.getByText("Gateway")).toBeInTheDocument();
    expect(screen.getByText("Removed")).toBeInTheDocument();

    const container = screen.getByTestId("feature-hero-stats");
    expect(container.className).toContain("xl:grid-cols-5");
  });

  it("keeps 3 stats on the three-column layout without the 5-column class", () => {
    render(
      <FeatureHero
        icon={Headphones}
        title="AutoMess"
        accent="#23A55A"
        stats={fiveStats.slice(0, 3)}
      />,
    );

    const container = screen.getByTestId("feature-hero-stats");
    expect(container.className).toContain("sm:grid-cols-3");
    expect(container.className).not.toContain("xl:grid-cols-5");
  });
});
