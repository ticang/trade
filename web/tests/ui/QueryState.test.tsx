import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { QueryState } from "@/components/ui/QueryState";

describe("QueryState", () => {
  it("renders loading state", () => {
    render(<QueryState label="持仓" isLoading />);

    expect(screen.getByRole("status")).toHaveTextContent("持仓加载中");
  });

  it("renders error state", () => {
    render(<QueryState label="订单" isError error={new Error("backend down")} />);

    expect(screen.getByRole("alert")).toHaveTextContent("订单加载失败");
    expect(screen.getByRole("alert")).toHaveTextContent("backend down");
  });

  it("renders empty state", () => {
    render(<QueryState label="告警" isEmpty />);

    expect(screen.getByRole("status")).toHaveTextContent("暂无告警数据");
  });

  it("renders nothing when data is ready", () => {
    const { container } = render(<QueryState label="行情" />);

    expect(container).toBeEmptyDOMElement();
  });
});
