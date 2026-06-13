import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { BacktestResultPanel } from "@/components/research/BacktestResultPanel";
import { AttributionBars } from "@/components/research/AttributionBars";
import { BacktestResult } from "@/types/research";

const backtest: BacktestResult = {
  strategy: "multi_factor_alpha_v3",
  series: [
    { ts: 1716422400, equity: 1.0, drawdown: 0, benchmark: 1.0 },
    { ts: 1716508800, equity: 1.012, drawdown: 0, benchmark: 1.004 },
    { ts: 1716595200, equity: 0.991, drawdown: -0.021, benchmark: 1.001 },
    { ts: 1716681600, equity: 1.028, drawdown: 0, benchmark: 1.011 },
  ],
  annual_return: 0.312,
  sharpe: 1.84,
  max_drawdown: -0.094,
  win_rate: 0.56,
  turnover: 0.38,
  attribution: [
    { factor: "price_reversal_5d", contribution: 0.072 },
    { factor: "earnings_surprise", contribution: 0.118 },
    { factor: "liquidity_amihud", contribution: -0.024 },
    { factor: "value_bp", contribution: 0.041 },
  ],
};

describe("BacktestResultPanel", () => {
  it("renders strategy name", () => {
    render(<BacktestResultPanel result={backtest} />);
    expect(screen.getByText("multi_factor_alpha_v3")).toBeInTheDocument();
  });

  it("renders the five key metric labels", () => {
    render(<BacktestResultPanel result={backtest} />);
    expect(screen.getByText(/年化/)).toBeInTheDocument();
    expect(screen.getByText(/夏普/)).toBeInTheDocument();
    expect(screen.getByText(/最大回撤/)).toBeInTheDocument();
    expect(screen.getByText(/胜率/)).toBeInTheDocument();
    expect(screen.getByText(/换手/)).toBeInTheDocument();
  });

  it("colors max_drawdown red (trading-down)", () => {
    render(<BacktestResultPanel result={backtest} />);
    const dd = screen.getByTestId("backtest-metric-max_drawdown");
    expect(dd.className).toContain("text-trading-down");
  });

  it("renders equity chart and drawdown chart containers", () => {
    render(<BacktestResultPanel result={backtest} />);
    expect(screen.getByTestId("backtest-equity-chart")).toBeInTheDocument();
    expect(screen.getByTestId("backtest-drawdown-chart")).toBeInTheDocument();
  });
});

describe("AttributionBars", () => {
  it("renders factor names", () => {
    render(<AttributionBars attribution={backtest.attribution} />);
    expect(screen.getByText("price_reversal_5d")).toBeInTheDocument();
    expect(screen.getByText("earnings_surprise")).toBeInTheDocument();
    expect(screen.getByText("liquidity_amihud")).toBeInTheDocument();
    expect(screen.getByText("value_bp")).toBeInTheDocument();
  });

  it("colors positive contribution trading-up and negative trading-down", () => {
    render(<AttributionBars attribution={backtest.attribution} />);
    const bars = screen.getAllByTestId("attribution-bar");
    // Sorted by |contribution| desc: earnings_surprise(0.118), price_reversal_5d(0.072),
    // value_bp(0.041), liquidity_amihud(-0.024).
    expect(bars).toHaveLength(4);
    const [earnings, reversal, value, liquidity] = bars;
    expect(earnings.className).toContain("bg-trading-up");
    expect(reversal.className).toContain("bg-trading-up");
    expect(value.className).toContain("bg-trading-up");
    expect(liquidity.className).toContain("bg-trading-down");
  });
});
