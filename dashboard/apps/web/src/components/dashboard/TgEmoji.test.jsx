import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { Moon } from "lucide-react";
import TgEmoji from "./TgEmoji";

describe("TgEmoji", () => {
  it("renders the vault asset URL for a valid id", () => {
    render(<TgEmoji id="5041906342642582678" size={24} alt="moon" />);

    const image = screen.getByRole("img", { name: "moon" });
    expect(image.getAttribute("src")).toContain(
      "/api/emoji-assets/5041906342642582678",
    );
  });

  it("falls back to the provided icon when the asset fails", () => {
    render(<TgEmoji id="123" fallback={Moon} alt="moon" />);

    fireEvent.error(screen.getByRole("img", { name: "moon" }));

    expect(
      screen.queryByRole("img", { name: "moon" }),
    ).not.toBeInTheDocument();
    expect(document.querySelector("svg")).toBeInTheDocument();
  });

  it("renders the fallback directly when no id is provided", () => {
    render(<TgEmoji fallback={Moon} />);

    expect(document.querySelector("img")).not.toBeInTheDocument();
    expect(document.querySelector("svg")).toBeInTheDocument();
  });
});
