import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StrategyTable } from "@/components/monitor/StrategyTable";
import { LifecycleBadge } from "@/components/monitor/LifecycleBadge";
import { mockStrategies } from "@/lib/mock/strategies";

describe("LifecycleBadge", () => {
  it("maps live to trading-up color", () => {
    const { container } = render(<LifecycleBadge status="live" />);
    expect(container.firstChild).toHaveClass("text-trading-up");
  });

  it("maps paper to primary color", () => {
    const { container } = render(<LifecycleBadge status="paper" />);
    expect(container.firstChild).toHaveClass("text-primary");
  });

  it("maps degraded to trading-down color", () => {
    const { container } = render(<LifecycleBadge status="degraded" />);
    expect(container.firstChild).toHaveClass("text-trading-down");
  });

  it("maps offline to muted color", () => {
    const { container } = render(<LifecycleBadge status="offline" />);
    expect(container.firstChild).toHaveClass("text-muted");
  });

  it("maps remaining statuses to info color", () => {
    const { container } = render(<LifecycleBadge status="draft" />);
    expect(container.firstChild).toHaveClass("text-info");
  });
});

describe("StrategyTable", () => {
  it("renders header labels", () => {
    render(<StrategyTable rows={mockStrategies()} />);
    expect(screen.getByText("策略")).toBeInTheDocument();
    expect(screen.getByText("状态")).toBeInTheDocument();
    expect(screen.getByText("IC")).toBeInTheDocument();
    expect(screen.getByText("换手")).toBeInTheDocument();
    expect(screen.getByText("回撤")).toBeInTheDocument();
    expect(screen.getByText("配比")).toBeInTheDocument();
  });

  it("renders each strategy name", () => {
    render(<StrategyTable rows={mockStrategies()} />);
    expect(screen.getByText("动量轮动")).toBeInTheDocument();
    expect(screen.getByText("情绪反向")).toBeInTheDocument();
    expect(screen.getByText("事件驱动")).toBeInTheDocument();
  });

  it("renders a LifecycleBadge for each strategy status", () => {
    render(<StrategyTable rows={mockStrategies()} />);
    expect(screen.getByText("live")).toBeInTheDocument();
    expect(screen.getByText("paper")).toBeInTheDocument();
    expect(screen.getByText("degraded")).toBeInTheDocument();
  });

  it("colors drawdown red via PriceCell direction", () => {
    render(<StrategyTable rows={mockStrategies()} />);
    // All mock drawdowns are negative (e.g. -8.00%).
    const drawdownCell = screen.getByText("-8.00%").closest("span.text-trading-down");
    expect(drawdownCell).not.toBeNull();
  });

  it("colors positive IC green via PriceCell direction", () => {
    render(<StrategyTable rows={mockStrategies()} />);
    // 动量轮动 IC 0.062 -> +6.20%.
    const icCell = screen.getByText("+6.20%").closest("span.text-trading-up");
    expect(icCell).not.toBeNull();
  });
});
