import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { FactorEvalChart } from "@/components/research/FactorEvalChart";
import { FactorEval } from "@/types/research";

const factor: FactorEval = {
  name: "price_reversal_5d",
  ic_series: [
    { ts: 1716422400, ic: 0.062 },
    { ts: 1716681600, ic: 0.048 },
    { ts: 1716768000, ic: 0.071 },
  ],
  ic: 0.068,
  ir: 0.74,
  turnover: 0.42,
  quantile_returns: [-0.18, -0.13, -0.08, -0.04, -0.01, 0.02, 0.05, 0.09, 0.13, 0.18],
  novelty_corr: 0.31,
};

describe("FactorEvalChart", () => {
  it("renders factor name and IC/IR/turnover/novelty metrics", () => {
    render(<FactorEvalChart factor={factor} />);
    expect(screen.getByText("price_reversal_5d")).toBeInTheDocument();
    // IC value surfaced in the metric row.
    expect(screen.getByText(/0\.068/)).toBeInTheDocument();
    expect(screen.getByText(/0\.74/)).toBeInTheDocument();
    expect(screen.getByText(/0\.42/)).toBeInTheDocument();
    expect(screen.getByText(/0\.31/)).toBeInTheDocument();
  });

  it("colors positive IC with trading-up", () => {
    render(<FactorEvalChart factor={factor} />);
    const icValue = screen.getByTestId("factor-ic-value");
    expect(icValue.className).toContain("text-trading-up");
  });

  it("colors negative IC with trading-down", () => {
    render(<FactorEvalChart factor={{ ...factor, ic: -0.05 }} />);
    const icValue = screen.getByTestId("factor-ic-value");
    expect(icValue.className).toContain("text-trading-down");
  });

  it("renders IC time-series chart container", () => {
    render(<FactorEvalChart factor={factor} />);
    expect(screen.getByTestId("factor-ic-chart")).toBeInTheDocument();
  });

  it("renders 10 quantile return bars", () => {
    render(<FactorEvalChart factor={factor} />);
    const bars = screen.getByTestId("factor-quantile-bars");
    const barEls = within(bars).getAllByTestId("quantile-bar");
    expect(barEls).toHaveLength(10);
  });
});
