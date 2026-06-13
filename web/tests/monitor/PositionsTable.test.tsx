import { describe, it, expect } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { PositionsTable } from "@/components/monitor/PositionsTable";
import { mockPositions } from "@/lib/mock/positions";

describe("PositionsTable", () => {
  it("renders header labels", () => {
    render(<PositionsTable rows={mockPositions()} />);
    expect(screen.getByText("账户")).toBeInTheDocument();
    expect(screen.getByText("标的")).toBeInTheDocument();
    expect(screen.getByText("数量")).toBeInTheDocument();
    expect(screen.getByText("成本")).toBeInTheDocument();
    expect(screen.getByText("现价")).toBeInTheDocument();
    expect(screen.getByText("市值")).toBeInTheDocument();
    expect(screen.getByText("盈亏")).toBeInTheDocument();
    expect(screen.getByText("权重")).toBeInTheDocument();
  });

  it("colors positive pnl trading-up and negative pnl trading-down", () => {
    const rows = mockPositions();
    render(<PositionsTable rows={rows} />);

    // Positive-pnl symbol: 600519 贵州茅台, pnl +3550
    const positiveCell = screen.getByText("+3550.00").closest("span");
    expect(positiveCell?.className).toContain("text-trading-up");

    // Negative-pnl symbol: 000001 平安银行, pnl -800
    const negativeCell = screen.getByText("-800.00").closest("span");
    expect(negativeCell?.className).toContain("text-trading-down");
  });

  it("groups positions by account_id in ascending order", () => {
    render(<PositionsTable rows={mockPositions()} />);

    const groupHeaders = screen.getAllByTestId("account-group");
    // Two account groups.
    expect(groupHeaders).toHaveLength(2);
    // Ascending account order.
    expect(groupHeaders[0].textContent).toBe("acct1");
    expect(groupHeaders[1].textContent).toBe("acct2");

    // acct1 rows (600519, 300750, 000001) appear before acct2 rows (002594).
    const symbols = ["600519", "300750", "000001", "002594"].map(
      (s) => screen.getByText(s),
    );
    const acct2Pos = symbols[3].compareDocumentPosition(symbols[0]);
    // Node.DOCUMENT_POSITION_PRECEDING === 2: acct1's first symbol precedes acct2's symbol.
    expect(acct2Pos & Node.DOCUMENT_POSITION_PRECEDING).toBeTruthy();

    // acct1 group contains exactly its 3 symbols, not acct2's.
    const acct1Group = groupHeaders[0].parentElement!;
    expect(within(acct1Group).getByText("600519")).toBeInTheDocument();
    expect(within(acct1Group).getByText("300750")).toBeInTheDocument();
    expect(within(acct1Group).getByText("000001")).toBeInTheDocument();
    expect(within(acct1Group).queryByText("002594")).toBeNull();
  });
});
