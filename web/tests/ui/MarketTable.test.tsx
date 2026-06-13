import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { MarketTable } from "@/components/ui/MarketTable";

const rows = [
  { symbol: "BTCUSDT", name: "Bitcoin", last: 79065.04, change: 0.45, volume: 1234567 },
  { symbol: "ETHUSDT", name: "Ethereum", last: 3050.12, change: -1.23, volume: 987654 },
];

describe("MarketTable", () => {
  it("renders header row", () => {
    render(<MarketTable rows={rows} />);
    expect(screen.getByText("交易对")).toBeInTheDocument();
    expect(screen.getByText("最新价")).toBeInTheDocument();
    expect(screen.getByText("24h 涨跌")).toBeInTheDocument();
  });

  it("renders each row with correct direction color", () => {
    render(<MarketTable rows={rows} />);
    expect(screen.getByText("79065.04")).toBeInTheDocument();
    expect(screen.getByText("BTCUSDT").className).toContain("text-trading-up");
    expect(screen.getByText("ETHUSDT").className).toContain("text-trading-down");
  });
});
