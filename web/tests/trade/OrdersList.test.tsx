import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { OrdersList } from "@/components/trade/OrdersList";
import { FillsList } from "@/components/trade/FillsList";
import { mockOrders } from "@/lib/mock/orders";
import { mockFills } from "@/lib/mock/fills";
import type { Order } from "@/types/trade";

describe("OrdersList", () => {
  it("renders header labels", () => {
    render(<OrdersList orders={mockOrders()} />);
    expect(screen.getByText("标的")).toBeInTheDocument();
    expect(screen.getByText("方向")).toBeInTheDocument();
    expect(screen.getByText("价格")).toBeInTheDocument();
    expect(screen.getByText("数量")).toBeInTheDocument();
    expect(screen.getByText("已成")).toBeInTheDocument();
    expect(screen.getByText("状态")).toBeInTheDocument();
  });

  it("colors status via the full OrderStatus color map", () => {
    render(<OrdersList orders={mockOrders()} />);

    const cases: Array<{ status: string; cls: string }> = [
      { status: "filled", cls: "text-trading-up" },
      { status: "partial_filled", cls: "text-primary" },
      { status: "submitted", cls: "text-info" },
      { status: "pending", cls: "text-info" },
      { status: "cancelled", cls: "text-muted" },
      { status: "rejected", cls: "text-muted" },
    ];

    for (const { status, cls } of cases) {
      const cell = screen.getByTestId(`order-status-${status}`);
      expect(cell.className).toContain(cls);
    }
  });

  it("sorts orders by ts descending regardless of input order", () => {
    // Scramble the input to prove the component sorts, not the mock.
    const scrambled: Order[] = [...mockOrders()].reverse();
    render(<OrdersList orders={scrambled} />);

    const rows = screen.getAllByTestId("order-row");
    // ts: 1006(1718318000000) > 1005 > 1004 > 1003 > 1002 > 1001(1718300000000)
    expect(rows[0]).toHaveAttribute("data-order-id", "ord-1006");
    expect(rows[rows.length - 1]).toHaveAttribute("data-order-id", "ord-1001");
  });

  it("colors side buy trading-up and sell trading-down", () => {
    render(<OrdersList orders={mockOrders()} />);

    const buyCells = screen.getAllByTestId("order-side-buy");
    const sellCells = screen.getAllByTestId("order-side-sell");
    expect(buyCells.length).toBeGreaterThan(0);
    expect(sellCells.length).toBeGreaterThan(0);
    for (const c of buyCells) expect(c.className).toContain("text-trading-up");
    for (const c of sellCells) expect(c.className).toContain("text-trading-down");
  });
});

describe("FillsList", () => {
  it("renders header labels", () => {
    render(<FillsList fills={mockFills()} />);
    expect(screen.getByText("标的")).toBeInTheDocument();
    expect(screen.getByText("方向")).toBeInTheDocument();
    expect(screen.getByText("价格")).toBeInTheDocument();
    expect(screen.getByText("数量")).toBeInTheDocument();
    expect(screen.getByText("时间")).toBeInTheDocument();
  });

  it("colors buy fill trading-up and sell fill trading-down", () => {
    render(<FillsList fills={mockFills()} />);

    const buyCells = screen.getAllByTestId("fill-side-buy");
    const sellCells = screen.getAllByTestId("fill-side-sell");
    expect(buyCells.length).toBeGreaterThan(0);
    expect(sellCells.length).toBeGreaterThan(0);
    for (const c of buyCells) expect(c.className).toContain("text-trading-up");
    for (const c of sellCells) expect(c.className).toContain("text-trading-down");
  });

  it("sorts fills by ts descending regardless of input order", () => {
    const scrambled = [...mockFills()].reverse();
    render(<FillsList fills={scrambled} />);

    const rows = screen.getAllByTestId("fill-row");
    // ts: 2002(1718303700000) > 2001(1718300100000) > 2003(1718296400000) > 2004(1718292800000)
    expect(rows[0]).toHaveAttribute("data-fill-id", "fill-2002");
    expect(rows[rows.length - 1]).toHaveAttribute("data-fill-id", "fill-2004");
  });
});
