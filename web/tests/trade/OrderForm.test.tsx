import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { OrderForm } from "@/components/trade/OrderForm";

describe("OrderForm", () => {
  it("defaults to buy side with trading-up highlight", () => {
    render(<OrderForm symbol="600519" available={100000} onSubmit={() => {}} />);
    const buyTab = screen.getByRole("tab", { name: /买入/ });
    const sellTab = screen.getByRole("tab", { name: /卖出/ });
    expect(buyTab.className).toContain("bg-trading-up");
    expect(sellTab.className).not.toContain("bg-trading-down");
  });

  it("switches to sell side with trading-down highlight on sell click", () => {
    render(<OrderForm symbol="600519" available={100000} onSubmit={() => {}} />);
    fireEvent.click(screen.getByRole("tab", { name: /卖出/ }));
    const sellTab = screen.getByRole("tab", { name: /卖出/ });
    const buyTab = screen.getByRole("tab", { name: /买入/ });
    expect(sellTab.className).toContain("bg-trading-down");
    expect(buyTab.className).not.toContain("bg-trading-up");
  });

  it("preview amount = price x qty in number font, submit fires {side, price, qty}", () => {
    const onSubmit = vi.fn();
    render(<OrderForm symbol="600519" available={100000} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText(/价格/), { target: { value: "1685" } });
    fireEvent.change(screen.getByLabelText(/数量/), { target: { value: "100" } });

    const preview = screen.getByTestId("order-preview-amount");
    expect(preview.textContent).toBe("168,500");
    expect(preview.className).toContain("font-number");

    fireEvent.click(screen.getByRole("button", { name: /买入/ }));
    expect(onSubmit).toHaveBeenCalledWith({ side: "buy", price: 1685, qty: 100 });
  });

  it("25% quick button computes qty from available/price", () => {
    const onSubmit = vi.fn();
    render(<OrderForm symbol="600519" available={100000} onSubmit={onSubmit} />);

    fireEvent.change(screen.getByLabelText(/价格/), { target: { value: "100" } });
    fireEvent.click(screen.getByRole("button", { name: "25%" }));
    // available 100000 * 0.25 / price 100 = 250
    expect(screen.getByLabelText(/数量/)).toHaveValue(250);
  });
});
