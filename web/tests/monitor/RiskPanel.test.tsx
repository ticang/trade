import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskPanel } from "@/components/monitor/RiskPanel";
import { AlertList } from "@/components/monitor/AlertList";
import { mockRisk } from "@/lib/mock/risk";
import { mockAlerts } from "@/lib/mock/alerts";

describe("RiskPanel", () => {
  it("renders total position percent", () => {
    render(<RiskPanel state={mockRisk()} />);
    // mockRisk total_position_pct = 0.62 -> 62.0%.
    expect(screen.getByText("62.0%")).toBeInTheDocument();
  });

  it("renders max single position percent", () => {
    render(<RiskPanel state={mockRisk()} />);
    // max_single_pct = 0.32 -> 32.0% scoped to the 单票上限 cell
    // (白酒 industry also renders 32.0%, so scope via the cell label).
    const cell = screen.getByText("单票上限").closest("div");
    expect(cell?.querySelector(".font-number")?.textContent).toBe("32.0%");
  });

  it("renders drawdown value", () => {
    render(<RiskPanel state={mockRisk()} />);
    // mockRisk drawdown = -0.08 -> -8.00%.
    expect(screen.getByText("-8.00%")).toBeInTheDocument();
  });

  it("renders circuit_breaker=normal with trading-up color and 正常 label", () => {
    const { container } = render(<RiskPanel state={mockRisk()} />);
    const badge = screen.getByText("正常");
    expect(badge).toBeInTheDocument();
    expect(badge).toHaveClass("text-trading-up");
    // Container sanity check.
    expect(container.firstChild).not.toBeNull();
  });

  it("renders circuit_breaker=halted with trading-down color and 熔断 label", () => {
    const state = { ...mockRisk(), circuit_breaker: "halted" as const };
    render(<RiskPanel state={state} />);
    const badge = screen.getByText("熔断");
    expect(badge).toHaveClass("text-trading-down");
  });

  it("renders circuit_breaker=degraded with primary color and 降级 label", () => {
    const state = { ...mockRisk(), circuit_breaker: "degraded" as const };
    render(<RiskPanel state={state} />);
    const badge = screen.getByText("降级");
    expect(badge).toHaveClass("text-primary");
  });

  it("renders all industry exposure labels", () => {
    render(<RiskPanel state={mockRisk()} />);
    expect(screen.getByText("白酒")).toBeInTheDocument();
    expect(screen.getByText("新能源")).toBeInTheDocument();
    expect(screen.getByText("银行")).toBeInTheDocument();
  });
});

describe("AlertList", () => {
  it("renders every alert title", () => {
    render(<AlertList alerts={mockAlerts()} />);
    expect(screen.getByText("事件驱动策略回撤接近阈值")).toBeInTheDocument();
    expect(screen.getByText("动量轮动调仓完成")).toBeInTheDocument();
    expect(screen.getByText("AkShare 数据源延迟")).toBeInTheDocument();
  });

  it("colors error alert with trading-down", () => {
    const { container } = render(<AlertList alerts={mockAlerts()} />);
    const errorRow = container.querySelector('[data-level="error"]');
    expect(errorRow).not.toBeNull();
    expect(errorRow!.querySelector(".text-trading-down")).not.toBeNull();
  });

  it("colors warn alert with primary", () => {
    const { container } = render(<AlertList alerts={mockAlerts()} />);
    const warnRow = container.querySelector('[data-level="warn"]');
    expect(warnRow!.querySelector(".text-primary")).not.toBeNull();
  });

  it("colors info alert with muted", () => {
    const { container } = render(<AlertList alerts={mockAlerts()} />);
    const infoRow = container.querySelector('[data-level="info"]');
    expect(infoRow!.querySelector(".text-muted")).not.toBeNull();
  });
});
