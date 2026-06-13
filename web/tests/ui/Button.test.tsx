import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { Button } from "@/components/ui/Button";

describe("Button", () => {
  it("renders primary variant with yellow bg + black text", () => {
    render(<Button variant="primary">买入</Button>);
    const btn = screen.getByRole("button", { name: "买入" });
    expect(btn.className).toContain("bg-primary");
    expect(btn.className).toContain("text-on-primary");
    expect(btn.className).toContain("rounded-md");
  });

  it("renders trading-up variant green", () => {
    render(<Button variant="trading-up">买</Button>);
    expect(screen.getByRole("button", { name: "买" }).className).toContain("bg-trading-up");
  });

  it("renders trading-down variant red", () => {
    render(<Button variant="trading-down">卖</Button>);
    expect(screen.getByRole("button", { name: "卖" }).className).toContain("bg-trading-down");
  });

  it("renders pill variant", () => {
    render(<Button variant="primary-pill">Sign Up</Button>);
    expect(screen.getByRole("button", { name: "Sign Up" }).className).toContain("rounded-pill");
  });

  it("renders disabled state", () => {
    render(<Button variant="primary" disabled>提交</Button>);
    const btn = screen.getByRole("button", { name: "提交" });
    expect(btn).toBeDisabled();
    expect(btn.className).toContain("bg-primary-disabled");
  });
});
