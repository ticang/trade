import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceCell } from "@/components/ui/PriceCell";

describe("PriceCell", () => {
  it("renders up value green with arrow", () => {
    render(<PriceCell value={12.34} direction="up" />);
    const el = screen.getByText("12.34");
    expect(el.className).toContain("text-trading-up");
    expect(el.parentElement?.textContent).toContain("▲");
  });

  it("renders down value red", () => {
    render(<PriceCell value={-5.67} direction="down" />);
    expect(screen.getByText("-5.67").className).toContain("text-trading-down");
  });

  it("renders flat muted", () => {
    render(<PriceCell value={0} direction="flat" />);
    expect(screen.getByText("0").className).toContain("text-muted");
  });
});
