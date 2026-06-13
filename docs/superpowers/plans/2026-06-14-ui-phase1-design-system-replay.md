# UI 第 1 期：设计系统基础 + 复盘报表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 `DESIGN.md`（币安风格设计 token 系统）搭建 Next.js + Tailwind 前端骨架，实现设计 token 到 Tailwind theme 的映射 + 基础组件库（Button/Card/MarketTable/TopNav），并交付第一个完整页面——复盘报表（价格 K 线 + 成交量 + 散户情绪曲线 + 信号标注三合一），全部用 mock 数据驱动。

**Architecture:** Next.js 14 (app router) + TypeScript + Tailwind CSS。`DESIGN.md` 的 colors/typography/spacing/rounded/components 映射到 `tailwind.config.ts` 的 theme tokens + 一组基础 React 组件。数据层用 TanStack Query + mock fetchers（types 先行，后续接真 API 改 fetcher 即可）。图表：K 线用 `lightweight-charts`，情绪/成交量副图用 `recharts`。字体用 DESIGN.md 建议的替代（Inter ≈ BinanceNova，IBM Plex Sans ≈ BinancePlex）。

**Tech Stack:** Next.js 14 · TypeScript · Tailwind CSS · TanStack Query · lightweight-charts · recharts · vitest + @testing-library/react

**关联设计：**
- `DESIGN.md`（项目根）— 币安设计 token 系统（视觉规范）
- `docs/specs/2026-06-14-a-stock-quant-trading-system-design.md` v0.5 §4.10（三合一复盘报表）、§4.8（情景模拟与复盘）

**全范围 UI 分期说明：** 本 plan 是全范围 UI 的第 1 期。后续 plan：
- 第 2 期：监控面板（持仓/盈亏/策略状态/风控/告警）
- 第 3 期：交易终端（行情 K 线 + 下单 + 账户）
- 第 4 期：研究回测界面（因子评价 IC/分层 + 回测结果 + 策略生命周期）

**前置事实（来自环境）：**
- 当前分支 `feat/m1a-local-probes`（M-1a 暂停，进度 3/8）。UI 在新分支 `feat/ui-phase1` 上做。
- 项目根 `/Users/rock/code/python/trade`，已有后端 Python 代码（probes/）。前端独立子目录 `web/`。
- pip 镜像坏（清华 SSL），用官方 PyPI；node/npm 镜像状态未知，npm install 若慢可设 `--registry https://registry.npmjs.org`。

---

## File Structure

```
trade/
├── web/                           # 前端独立子目录
│   ├── package.json               # Create: Next 14 + TS + Tailwind + 图表 + 测试
│   ├── tsconfig.json              # Create
│   ├── next.config.mjs            # Create
│   ├── tailwind.config.ts         # Create: DESIGN.md tokens → theme
│   ├── postcss.config.mjs         # Create
│   ├── vitest.config.ts           # Create
│   ├── src/
│   │   ├── app/
│   │   │   ├── layout.tsx         # Create: 根布局 + 字体 + Providers
│   │   │   ├── globals.css        # Create: Tailwind + 字体变量 + 主题
│   │   │   ├── page.tsx           # Create: 首页 dashboard 入口
│   │   │   └── replay/
│   │   │       └── page.tsx       # Create: 复盘报表页
│   │   ├── components/
│   │   │   ├── ui/                # 基础组件库（映射 DESIGN.md components）
│   │   │   │   ├── Button.tsx     # Create: button-primary/secondary/trading-up/down/subscribe/pill
│   │   │   │   ├── Card.tsx       # Create: markets-table-card/trust-badge/cta-band 变体
│   │   │   │   ├── MarketTable.tsx# Create: 行情表（markets-row + price-up/down-cell）
│   │   │   │   ├── TopNav.tsx     # Create: top-nav-dark
│   │   │   │   └── PriceCell.tsx  # Create: 涨跌色数字单元格
│   │   │   ├── charts/
│   │   │   │   ├── KlineChart.tsx # Create: lightweight-charts K 线 + 成交量
│   │   │   │   └── SentimentChart.tsx # Create: recharts 情绪曲线
│   │   │   └── replay/
│   │   │       ├── SignalMarkers.tsx # Create: 信号标注叠加层
│   │   │       └── ReplayReport.tsx  # Create: 复盘报告卡片
│   │   ├── lib/
│   │   │   ├── theme.ts           # Create: DESIGN.md token 常量（TS 侧）
│   │   │   └── mock/
│   │   │       ├── kline.ts       # Create: mock K 线 + 成交量生成器
│   │   │       ├── sentiment.ts   # Create: mock 情绪序列
│   │   │       ├── signals.ts     # Create: mock 信号标注
│   │   │       └── markets.ts     # Create: mock 行情表数据
│   │   ├── types/
│   │   │   └── domain.ts          # Create: Bar/Signal/Sentiment/Market 领域类型
│   │   └── hooks/
│   │       ├── useKline.ts        # Create: TanStack Query fetcher（mock）
│   │       ├── useSentiment.ts    # Create
│   │       └── useMarkets.ts      # Create
│   └── tests/
│       ├── ui/Button.test.tsx
│       ├── ui/PriceCell.test.tsx
│       ├── ui/MarketTable.test.tsx
│       └── replay/ReplayReport.test.tsx
```

**职责边界：**
- `tailwind.config.ts`：唯一 DESIGN.md token 映射点（colors/typography/spacing/radius）
- `components/ui/`：基础组件库（无业务逻辑，纯 DESIGN.md 实现）
- `components/charts/`：图表组件（K 线/情绪）
- `lib/mock/`：mock 数据生成（后续替换为真 API fetcher）
- `hooks/`：TanStack Query 取数抽象（mock → 真切换零改动）
- `types/domain.ts`：领域类型（前后端契约）

---

## Task 1: Next.js 项目骨架 + Tailwind + 字体 + vitest

**Files:**
- Create: `web/package.json`
- Create: `web/tsconfig.json`
- Create: `web/next.config.mjs`
- Create: `web/postcss.config.mjs`
- Create: `web/vitest.config.ts`
- Create: `web/src/app/layout.tsx`
- Create: `web/src/app/globals.css`
- Create: `web/src/app/page.tsx`
- Create: `web/.gitignore`

- [ ] **Step 1: 开 UI 分支**

```bash
cd /Users/rock/code/python/trade
git checkout -b feat/ui-phase1
```

- [ ] **Step 2: 创建 package.json**

```json
{
  "name": "trade-web",
  "version": "0.1.0",
  "private": true,
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start",
    "test": "vitest run",
    "test:watch": "vitest"
  },
  "dependencies": {
    "next": "14.2.25",
    "react": "18.3.1",
    "react-dom": "18.3.1",
    "@tanstack/react-query": "5.51.1",
    "lightweight-charts": "4.2.0",
    "recharts": "2.12.7",
    "clsx": "2.1.1"
  },
  "devDependencies": {
    "typescript": "5.5.3",
    "@types/react": "18.3.3",
    "@types/react-dom": "18.3.0",
    "@types/node": "20.14.10",
    "tailwindcss": "3.4.6",
    "postcss": "8.4.39",
    "autoprefixer": "10.4.19",
    "vitest": "2.0.3",
    "@testing-library/react": "16.0.0",
    "@testing-library/jest-dom": "6.4.6",
    "jsdom": "24.1.0",
    "@vitejs/plugin-react": "4.3.1"
  }
}
```

- [ ] **Step 3: 创建 tsconfig.json**

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["dom", "dom.iterable", "esnext"],
    "allowJs": false,
    "skipLibCheck": true,
    "strict": true,
    "noEmit": true,
    "esModuleInterop": true,
    "module": "esnext",
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "jsx": "preserve",
    "incremental": true,
    "plugins": [{ "name": "next" }],
    "paths": { "@/*": ["./src/*"] }
  },
  "include": ["next-env.d.ts", "**/*.ts", "**/*.tsx", ".next/types/**/*.ts"],
  "exclude": ["node_modules"]
}
```

- [ ] **Step 4: 创建 next.config.mjs**

```js
/** @type {import('next').NextConfig} */
const nextConfig = { reactStrictMode: true };
export default nextConfig;
```

- [ ] **Step 5: 创建 postcss.config.mjs**

```js
export default { plugins: { tailwindcss: {}, autoprefixer: {} } };
```

- [ ] **Step 6: 创建 vitest.config.ts**

```ts
import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

export default defineConfig({
  plugins: [react()],
  test: { environment: "jsdom", globals: true, setupFiles: [] },
  resolve: { alias: { "@": path.resolve(__dirname, "./src") } },
});
```

- [ ] **Step 7: 创建 globals.css（Tailwind 指令 + 字体变量，theme 在 Task 2 补）**

`web/src/app/globals.css`:
```css
@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  --font-display: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-number: "IBM Plex Sans", "Inter", monospace;
}

html, body { background-color: #0b0e11; color: #eaecef; }
body { font-family: var(--font-display); -webkit-font-smoothing: antialiased; }
```

- [ ] **Step 8: 创建 layout.tsx**

`web/src/app/layout.tsx`:
```tsx
import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "A 股量化交易系统", description: "Quant trading UI" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
```

- [ ] **Step 9: 创建 page.tsx（占位首页，Task 5 替换）**

`web/src/app/page.tsx`:
```tsx
export default function Home() {
  return <main className="p-8"><h1 className="text-2xl">A 股量化交易系统</h1></main>;
}
```

- [ ] **Step 10: 创建 .gitignore**

`web/.gitignore`:
```
node_modules/
.next/
*.log
.DS_Store
```

- [ ] **Step 11: 安装依赖并验证**

Run: `cd web && npm install --registry https://registry.npmjs.org`
Expected: 安装成功

Run: `cd web && npx next build`
Expected: build 成功（可能有 font 警告，无 error）

Run: `cd web && npx vitest run`
Expected: `No test files found`（无 error 即骨架 OK）

- [ ] **Step 12: Commit**

```bash
cd /Users/rock/code/python/trade
git add web/
git commit -m "scaffold Next.js + Tailwind + vitest frontend skeleton"
```

---

## Task 2: DESIGN.md tokens → Tailwind theme

**Files:**
- Create: `web/tailwind.config.ts`
- Create: `web/src/lib/theme.ts`

- [ ] **Step 1: 创建 tailwind.config.ts（映射 DESIGN.md 全部 tokens）**

```ts
import type { Config } from "tailwindcss";

const config: Config = {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // Brand & accent (DESIGN.md colors)
        primary: { DEFAULT: "#FCD535", active: "#f0b90b", disabled: "#3a3a1f" },
        ink: "#181a20",
        body: { DEFAULT: "#eaecef", onlight: "#181a20" },
        muted: { DEFAULT: "#707a8a", strong: "#929aa5" },
        hairline: { onlight: "#eaecef", ondark: "#2b3139" },
        "border-strong": "#cdd1d6",
        canvas: { light: "#ffffff", dark: "#0b0e11" },
        surface: {
          "card-dark": "#1e2329",
          "elevated-dark": "#2b3139",
          "soft-light": "#fafafa",
          "strong-light": "#f5f5f5",
        },
        "on-primary": "#181a20",
        "on-dark": "#ffffff",
        trading: { up: "#0ecb81", down: "#f6465d" },
        "accent-turquoise": "#2dbdb6",
        info: "#3b82f6",
      },
      fontFamily: {
        display: ['"Inter"', "-apple-system", "BlinkMacSystemFont", '"Segoe UI"', "sans-serif"],
        number: ['"IBM Plex Sans"', '"Inter"', "monospace"],
      },
      fontSize: {
        "hero-display": ["64px", { lineHeight: "1.1", letterSpacing: "-1px", fontWeight: "700" }],
        "display-lg": ["48px", { lineHeight: "1.1", letterSpacing: "-0.5px", fontWeight: "700" }],
        "display-md": ["40px", { lineHeight: "1.15", letterSpacing: "-0.3px", fontWeight: "600" }],
        "display-sm": ["32px", { lineHeight: "1.2", fontWeight: "600" }],
        "title-lg": ["24px", { lineHeight: "1.3", fontWeight: "600" }],
        "title-md": ["20px", { lineHeight: "1.35", fontWeight: "600" }],
        "title-sm": ["16px", { lineHeight: "1.4", fontWeight: "600" }],
        "number-display": ["40px", { lineHeight: "1.1", letterSpacing: "-0.3px", fontWeight: "700" }],
        "number-md": ["16px", { lineHeight: "1.4", fontWeight: "500" }],
        "number-sm": ["14px", { lineHeight: "1.4", fontWeight: "500" }],
        "body-md": ["14px", { lineHeight: "1.5", fontWeight: "400" }],
        "body-sm": ["13px", { lineHeight: "1.5", fontWeight: "400" }],
        caption: ["12px", { lineHeight: "1.4", fontWeight: "500" }],
        button: ["14px", { lineHeight: "1", fontWeight: "600" }],
        "nav-link": ["14px", { lineHeight: "1.4", fontWeight: "500" }],
      },
      borderRadius: { xs: "2px", sm: "4px", md: "6px", lg: "8px", xl: "12px", pill: "9999px" },
      spacing: { xxs: "4px", xs: "8px", sm: "12px", md: "16px", lg: "24px", xl: "32px", xxl: "48px", section: "80px" },
    },
  },
  plugins: [],
};
export default config;
```

- [ ] **Step 2: 创建 theme.ts（TS 侧 token 常量，供非 Tailwind 场景如 inline style / 图表配色）**

`web/src/lib/theme.ts`:
```ts
// DESIGN.md tokens as TS constants (for chart configs, inline styles outside Tailwind).
export const theme = {
  colors: {
    primary: "#FCD535",
    primaryActive: "#f0b90b",
    canvasDark: "#0b0e11",
    surfaceCardDark: "#1e2329",
    body: "#eaecef",
    muted: "#707a8a",
    tradingUp: "#0ecb81",
    tradingDown: "#f6465d",
    hairlineOnDark: "#2b3139",
    info: "#3b82f6",
  },
} as const;
```

- [ ] **Step 3: 验证 build 仍通过 + Tailwind class 可用**

Run: `cd web && npx next build`
Expected: build 成功

在 `web/src/app/page.tsx` 临时加 `<p className="text-primary bg-canvas-dark p-lg">token test</p>`，`npx next build` 成功后还原。

- [ ] **Step 4: Commit**

```bash
git add web/tailwind.config.ts web/src/lib/theme.ts
git commit -m "map DESIGN.md tokens to Tailwind theme"
```

---

## Task 3: Button 组件（DESIGN.md button variants）

**Files:**
- Create: `web/src/components/ui/Button.tsx`
- Create: `web/tests/ui/Button.test.tsx`

- [ ] **Step 1: 写失败测试**

`web/tests/ui/Button.test.tsx`:
```tsx
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
```

- [ ] **Step 2: 运行验证失败**

Run: `cd web && npx vitest run tests/ui/Button.test.tsx`
Expected: FAIL（Button 未定义）

- [ ] **Step 3: 实现 Button**

`web/src/components/ui/Button.tsx`:
```tsx
import { clsx } from "clsx";
import { ButtonHTMLAttributes } from "react";

type Variant = "primary" | "primary-active" | "primary-pill" | "secondary-dark" | "secondary-light" | "tertiary-text" | "trading-up" | "trading-down" | "subscribe";

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
}

const VARIANT_CLASSES: Record<Variant, string> = {
  primary: "bg-primary text-on-primary rounded-md px-6 py-3 h-10 text-button",
  "primary-active": "bg-primary-active text-on-primary rounded-md px-6 py-3 h-10 text-button",
  "primary-pill": "bg-primary text-on-primary rounded-pill px-8 py-3.5 text-button",
  "secondary-dark": "bg-surface-card-dark text-on-dark rounded-md px-6 py-3 h-10 text-button",
  "secondary-light": "bg-canvas-light text-ink rounded-md px-6 py-3 h-10 text-button border border-hairline-onlight",
  "tertiary-text": "bg-transparent text-body text-button",
  "trading-up": "bg-trading-up text-on-dark rounded-sm px-5 py-2 text-button",
  "trading-down": "bg-trading-down text-on-dark rounded-sm px-5 py-2 text-button",
  subscribe: "bg-primary text-on-primary rounded-sm px-4 h-7 text-button",
};

export function Button({ variant = "primary", className, disabled, children, ...rest }: ButtonProps) {
  const isPrimary = variant === "primary" || variant === "primary-pill";
  const disabledOverride = disabled && isPrimary ? "bg-primary-disabled text-muted cursor-not-allowed" : "";
  return (
    <button
      disabled={disabled}
      className={clsx("font-display inline-flex items-center justify-center", VARIANT_CLASSES[variant], disabledOverride, className)}
      {...rest}
    >
      {children}
    </button>
  );
}
```

- [ ] **Step 4: 运行验证通过**

Run: `cd web && npx vitest run tests/ui/Button.test.tsx`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/components/ui/Button.tsx web/tests/ui/Button.test.tsx
git commit -m "add Button component with DESIGN.md variants"
```

---

## Task 4: PriceCell + MarketTable 组件

**Files:**
- Create: `web/src/components/ui/PriceCell.tsx`
- Create: `web/src/components/ui/MarketTable.tsx`
- Create: `web/tests/ui/PriceCell.test.tsx`
- Create: `web/tests/ui/MarketTable.test.tsx`

- [ ] **Step 1: 写 PriceCell 失败测试**

`web/tests/ui/PriceCell.test.tsx`:
```tsx
import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { PriceCell } from "@/components/ui/PriceCell";

describe("PriceCell", () => {
  it("renders up value green with arrow", () => {
    render(<PriceCell value={12.34} direction="up" />);
    const el = screen.getByText("12.34");
    expect(el.className).toContain("text-trading-up");
    expect(el.parentElement?.textContent).toContain("▲");
  });

  it("renders down value red", () => {
    render(<PriceCell value={-5.67} direction="down" />);
    expect(screen.getByText("-5.67").className).toContain("text-trading-down");
  });

  it("renders flat muted", () => {
    render(<PriceCell value={0} direction="flat" />);
    expect(screen.getByText("0").className).toContain("text-muted");
  });
});
```

- [ ] **Step 2: 实现 PriceCell**

`web/src/components/ui/PriceCell.tsx`:
```tsx
import { clsx } from "clsx";

interface PriceCellProps {
  value: number;
  direction: "up" | "down" | "flat";
  format?: (v: number) => string;
}

const ARROW = { up: "▲", down: "▼", flat: "—" };
const COLOR = { up: "text-trading-up", down: "text-trading-down", flat: "text-muted" };

export function PriceCell({ value, direction, format }: PriceCellProps) {
  const text = format ? format(value) : String(value);
  return (
    <span className={clsx("font-number text-number-md inline-flex items-center gap-1", COLOR[direction])}>
      <span className="text-[10px]">{ARROW[direction]}</span>
      <span>{text}</span>
    </span>
  );
}
```

- [ ] **Step 3: PriceCell 测试通过**

Run: `cd web && npx vitest run tests/ui/PriceCell.test.tsx`
Expected: 3 PASS

- [ ] **Step 4: 写 MarketTable 失败测试**

`web/tests/ui/MarketTable.test.tsx`:
```tsx
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
```

- [ ] **Step 5: 实现 MarketTable**

`web/src/components/ui/MarketTable.tsx`:
```tsx
import { clsx } from "clsx";
import { PriceCell } from "./PriceCell";

export interface MarketRow {
  symbol: string;
  name: string;
  last: number;
  change: number;   // percent
  volume: number;
}

interface MarketTableProps {
  rows: MarketRow[];
}

const pctFmt = (v: number) => `${v > 0 ? "+" : ""}${v.toFixed(2)}%`;
const numFmt = (v: number) => v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function MarketTable({ rows }: MarketTableProps) {
  return (
    <div className="bg-surface-card-dark rounded-xl p-lg text-on-dark">
      <div className="grid grid-cols-4 gap-md pb-sm border-b border-hairline-ondark text-muted text-body-md">
        <span>交易对</span><span className="text-right">最新价</span><span className="text-right">24h 涨跌</span><span className="text-right">24h 成交额</span>
      </div>
      {rows.map((r) => {
        const dir = r.change > 0 ? "up" : r.change < 0 ? "down" : "flat";
        return (
          <div key={r.symbol} className="grid grid-cols-4 gap-md py-sm border-b border-hairline-ondark last:border-0 items-center">
            <div className="flex items-center gap-xs">
              <div className="w-8 h-8 rounded-full bg-surface-elevated-dark" />
              <div>
                <div className="font-number text-number-md">{r.symbol}</div>
                <div className="text-caption text-muted">{r.name}</div>
              </div>
            </div>
            <div className="text-right"><PriceCell value={r.last} direction={dir} format={numFmt} /></div>
            <div className="text-right"><PriceCell value={r.change} direction={dir} format={pctFmt} /></div>
            <div className="text-right font-number text-number-md text-muted">{Math.round(r.volume).toLocaleString()}</div>
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 6: MarketTable 测试通过**

Run: `cd web && npx vitest run tests/ui/MarketTable.test.tsx`
Expected: 2 PASS

- [ ] **Step 7: Commit**

```bash
git add web/src/components/ui/PriceCell.tsx web/src/components/ui/MarketTable.tsx web/tests/ui/PriceCell.test.tsx web/tests/ui/MarketTable.test.tsx
git commit -m "add PriceCell and MarketTable components"
```

---

## Task 5: TopNav + 卡片壳组件 + 布局

**Files:**
- Create: `web/src/components/ui/Card.tsx`
- Create: `web/src/components/ui/TopNav.tsx`
- Modify: `web/src/app/layout.tsx`（加 Providers + TopNav）
- Modify: `web/src/app/page.tsx`（替换为 dashboard 入口）

- [ ] **Step 1: 实现 Card（DESIGN.md 卡片变体）**

`web/src/components/ui/Card.tsx`:
```tsx
import { clsx } from "clsx";
import { ReactNode } from "react";

type CardVariant = "surface-dark" | "elevated-dark" | "cta-band" | "light";

interface CardProps {
  variant?: CardVariant;
  children: ReactNode;
  className?: string;
}

const VARIANT: Record<CardVariant, string> = {
  "surface-dark": "bg-surface-card-dark rounded-xl",
  "elevated-dark": "bg-surface-elevated-dark rounded-xl",
  "cta-band": "bg-surface-card-dark rounded-xl p-xxl",
  light: "bg-canvas-light rounded-lg border border-hairline-onlight",
};

export function Card({ variant = "surface-dark", children, className }: CardProps) {
  return <div className={clsx("text-on-dark", VARIANT[variant], className)}>{children}</div>;
}
```

- [ ] **Step 2: 实现 TopNav（top-nav-dark）**

`web/src/components/ui/TopNav.tsx`:
```tsx
"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { clsx } from "clsx";

const NAV = [
  { href: "/", label: "首页" },
  { href: "/replay", label: "复盘" },
  { href: "/monitor", label: "监控" },
  { href: "/trade", label: "交易" },
  { href: "/research", label: "研究" },
];

export function TopNav() {
  const pathname = usePathname();
  return (
    <nav className="bg-canvas-dark text-on-dark h-16 flex items-center px-lg border-b border-hairline-ondark sticky top-0 z-50">
      <div className="font-display text-title-md text-primary font-bold mr-xl">A 股量化</div>
      <div className="flex gap-lg">
        {NAV.map((n) => (
          <Link
            key={n.href}
            href={n.href}
            className={clsx("text-nav-link", pathname === n.href ? "text-primary" : "text-body hover:text-primary")}
          >
            {n.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
```

- [ ] **Step 3: 加 Providers（TanStack Query）**

`web/src/app/providers.tsx`:
```tsx
"use client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, ReactNode } from "react";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient());
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
```

- [ ] **Step 4: 更新 layout.tsx**

`web/src/app/layout.tsx`:
```tsx
import "./globals.css";
import type { Metadata } from "next";
import { Providers } from "./providers";
import { TopNav } from "@/components/ui/TopNav";

export const metadata: Metadata = { title: "A 股量化交易系统", description: "Quant trading UI" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>
          <TopNav />
          <main className="max-w-[1440px] mx-auto px-lg py-lg">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
```

- [ ] **Step 5: 替换首页为 dashboard 入口**

`web/src/app/page.tsx`:
```tsx
import { Card } from "@/components/ui/Card";

export default function Home() {
  return (
    <div className="space-y-lg">
      <h1 className="text-display-sm">A 股量化交易系统</h1>
      <div className="grid grid-cols-3 gap-lg">
        <Card><div className="p-lg"><div className="text-muted text-body-sm">总资产</div><div className="text-number-display text-primary">¥1,234,567</div></div></Card>
        <Card><div className="p-lg"><div className="text-muted text-body-sm">当日盈亏</div><div className="text-number-display text-trading-up">+2.34%</div></div></Card>
        <Card><div className="p-lg"><div className="text-muted text-body-sm">运行策略</div><div className="text-number-display text-on-dark">3</div></div></Card>
      </div>
    </div>
  );
}
```

- [ ] **Step 6: 验证 build + dev**

Run: `cd web && npx next build`
Expected: build 成功（TopNav/Card/Providers 无类型错误）

- [ ] **Step 7: Commit**

```bash
git add web/src/components/ui/Card.tsx web/src/components/ui/TopNav.tsx web/src/app/providers.tsx web/src/app/layout.tsx web/src/app/page.tsx
git commit -m "add Card, TopNav, Providers, dashboard layout"
```

---

## Task 6: 领域类型 + mock 数据 + TanStack Query hooks

**Files:**
- Create: `web/src/types/domain.ts`
- Create: `web/src/lib/mock/kline.ts`
- Create: `web/src/lib/mock/sentiment.ts`
- Create: `web/src/lib/mock/signals.ts`
- Create: `web/src/lib/mock/markets.ts`
- Create: `web/src/hooks/useKline.ts`
- Create: `web/src/hooks/useSentiment.ts`
- Create: `web/src/hooks/useMarkets.ts`

- [ ] **Step 1: 领域类型**

`web/src/types/domain.ts`:
```ts
export interface Bar {
  ts: number;        // unix ms
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface SentimentPoint {
  ts: number;
  score: number;     // [-1, 1]
}

export type SignalDirection = "buy" | "sell" | "warn";
export interface ReplaySignal {
  ts: number;
  direction: SignalDirection;
  label: string;     // e.g. "CPO 起飞", "抄底", "清仓"
  price: number;
}

export interface MarketRow {
  symbol: string;
  name: string;
  last: number;
  change: number;
  volume: number;
}
```

- [ ] **Step 2: mock K 线生成器**

`web/src/lib/mock/kline.ts`:
```ts
import { Bar } from "@/types/domain";

// Deterministic synthetic kline (seeded) so the chart is stable across reloads.
export function mockKline(n: number = 240, startPrice = 4100): Bar[] {
  let price = startPrice;
  const bars: Bar[] = [];
  let seed = 42;
  const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  const dayStart = new Date("2024-03-15T09:30:00").getTime();
  for (let i = 0; i < n; i++) {
    const open = price;
    const drift = (rnd() - 0.48) * 8;
    const close = Math.max(3800, open + drift);
    const high = Math.max(open, close) + rnd() * 3;
    const low = Math.min(open, close) - rnd() * 3;
    const volume = Math.round(50000 + rnd() * 200000);
    bars.push({ ts: dayStart + i * 60_000, open, high, low, close, volume });
    price = close;
  }
  return bars;
}
```

- [ ] **Step 3: mock 情绪序列**

`web/src/lib/mock/sentiment.ts`:
```ts
import { SentimentPoint } from "@/types/domain";
import { mockKline } from "./kline";

export function mockSentiment(): SentimentPoint[] {
  const bars = mockKline();
  let seed = 7;
  const rnd = () => { seed = (seed * 9301 + 49297) % 233280; return seed / 233280; };
  return bars.map((b) => ({ ts: b.ts, score: (rnd() - 0.5) * 1.6 }));
}
```

- [ ] **Step 4: mock 信号标注**

`web/src/lib/mock/signals.ts`:
```ts
import { ReplaySignal } from "@/types/domain";
import { mockKline } from "./kline";

export function mockSignals(): ReplaySignal[] {
  const bars = mockKline();
  const pick = (i: number) => bars[Math.min(i, bars.length - 1)];
  const s1 = pick(30), s2 = pick(75), s3 = pick(120), s4 = pick(180);
  return [
    { ts: s1.ts, direction: "buy", label: "CPO 起飞", price: s1.close },
    { ts: s2.ts, direction: "warn", label: "风险清仓", price: s2.close },
    { ts: s3.ts, direction: "buy", label: "跌停抄底", price: s3.close },
    { ts: s4.ts, direction: "sell", label: "尾盘防套", price: s4.close },
  ];
}
```

- [ ] **Step 5: mock 行情表**

`web/src/lib/mock/markets.ts`:
```ts
import { MarketRow } from "@/types/domain";

export function mockMarkets(): MarketRow[] {
  return [
    { symbol: "000001", name: "平安银行", last: 11.34, change: 0.89, volume: 234_000_000 },
    { symbol: "600519", name: "贵州茅台", last: 1685.50, change: -1.23, volume: 1_200_000_000 },
    { symbol: "300750", name: "宁德时代", last: 182.70, change: 2.45, volume: 890_000_000 },
    { symbol: "002594", name: "比亚迪", last: 245.60, change: -0.56, volume: 567_000_000 },
    { symbol: "688981", name: "中芯国际", last: 48.92, change: 1.78, volume: 445_000_000 },
  ];
}
```

- [ ] **Step 6: TanStack Query hooks**

`web/src/hooks/useKline.ts`:
```ts
import { useQuery } from "@tanstack/react-query";
import { Bar } from "@/types/domain";
import { mockKline } from "@/lib/mock/kline";

export function useKline(symbol: string) {
  return useQuery<Bar[]>({
    queryKey: ["kline", symbol],
    queryFn: () => mockKline(),
    staleTime: Infinity,
  });
}
```

`web/src/hooks/useSentiment.ts`:
```ts
import { useQuery } from "@tanstack/react-query";
import { SentimentPoint } from "@/types/domain";
import { mockSentiment } from "@/lib/mock/sentiment";

export function useSentiment(symbol: string) {
  return useQuery<SentimentPoint[]>({
    queryKey: ["sentiment", symbol],
    queryFn: () => mockSentiment(),
    staleTime: Infinity,
  });
}
```

`web/src/hooks/useMarkets.ts`:
```ts
import { useQuery } from "@tanstack/react-query";
import { MarketRow } from "@/types/domain";
import { mockMarkets } from "@/lib/mock/markets";

export function useMarkets() {
  return useQuery<MarketRow[]>({
    queryKey: ["markets"],
    queryFn: () => mockMarkets(),
    staleTime: Infinity,
  });
}
```

- [ ] **Step 7: 验证 build**

Run: `cd web && npx next build`
Expected: build 成功（types + mock + hooks 无错误）

- [ ] **Step 8: Commit**

```bash
git add web/src/types/domain.ts web/src/lib/mock/ web/src/hooks/
git commit -m "add domain types, mock data, and TanStack Query hooks"
```

---

## Task 7: 复盘报表页面（三合一：K 线 + 成交量 + 情绪 + 信号标注）

**Files:**
- Create: `web/src/components/charts/KlineChart.tsx`
- Create: `web/src/components/charts/SentimentChart.tsx`
- Create: `web/src/components/replay/ReplayReport.tsx`
- Create: `web/src/app/replay/page.tsx`

- [ ] **Step 1: 实现 KlineChart（lightweight-charts K 线 + 成交量副图）**

`web/src/components/charts/KlineChart.tsx`:
```tsx
"use client";
import { useEffect, useRef } from "react";
import { createChart, ColorType, IChartApi } from "lightweight-charts";
import { Bar, ReplaySignal } from "@/types/domain";
import { theme } from "@/lib/theme";

interface Props {
  bars: Bar[];
  signals?: ReplaySignal[];
}

export function KlineChart({ bars, signals = [] }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: theme.colors.surfaceCardDark }, textColor: theme.colors.body },
      grid: { vertLines: { color: theme.colors.hairlineOnDark }, horzLines: { color: theme.colors.hairlineOnDark } },
      width: ref.current.clientWidth,
      height: 360,
    });
    chartRef.current = chart;

    const candle = chart.addCandlestickSeries({
      upColor: theme.colors.tradingUp, downColor: theme.colors.tradingDown,
      borderUpColor: theme.colors.tradingUp, borderDownColor: theme.colors.tradingDown,
      wickUpColor: theme.colors.tradingUp, wickDownColor: theme.colors.tradingDown,
    });
    candle.setData(bars.map((b) => ({ time: b.ts / 1000 as any, open: b.open, high: b.high, low: b.low, close: b.close })));

    const vol = chart.addHistogramSeries({ priceScaleId: "vol", color: theme.colors.muted });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vol.setData(bars.map((b) => ({ time: b.ts / 1000 as any, value: b.volume, color: b.close >= b.open ? theme.colors.tradingUp : theme.colors.tradingDown })));

    signals.forEach((s) => {
      candle.setMarkers([{
        time: s.ts / 1000 as any,
        position: s.direction === "buy" ? "belowBar" : "aboveBar",
        color: s.direction === "buy" ? theme.colors.tradingUp : s.direction === "sell" ? theme.colors.tradingDown : theme.colors.primary,
        shape: s.direction === "buy" ? "arrowUp" : s.direction === "sell" ? "arrowDown" : "circle",
        text: s.label,
      }]);
    });

    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth || 800 });
    window.addEventListener("resize", onResize);
    return () => { window.removeEventListener("resize", onResize); chart.remove(); };
  }, [bars, signals]);

  return <div ref={ref} className="w-full" />;
}
```

- [ ] **Step 2: 实现 SentimentChart（recharts 情绪曲线）**

`web/src/components/charts/SentimentChart.tsx`:
```tsx
"use client";
import { LineChart, Line, XAxis, YAxis, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import { SentimentPoint } from "@/types/domain";
import { theme } from "@/lib/theme";

interface Props { points: SentimentPoint[]; }

export function SentimentChart({ points }: Props) {
  const data = points.map((p) => ({ ts: p.ts, score: p.score }));
  return (
    <div className="h-[160px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <XAxis dataKey="ts" tick={false} axisLine={{ stroke: theme.colors.hairlineOnDark }} />
          <YAxis domain={[-1, 1]} tick={{ fill: theme.colors.muted, fontSize: 11 }} axisLine={false} tickLine={false} width={32} />
          <ReferenceLine y={0} stroke={theme.colors.hairlineOnDark} />
          <Tooltip contentStyle={{ background: theme.colors.surfaceCardDark, border: `1px solid ${theme.colors.hairlineOnDark}`, color: theme.colors.body }} />
          <Line type="monotone" dataKey="score" stroke={theme.colors.primary} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

- [ ] **Step 3: 实现 ReplayReport（三合一组合 + 复盘信息卡片）**

`web/src/components/replay/ReplayReport.tsx`:
```tsx
"use client";
import { Card } from "@/components/ui/Card";
import { KlineChart } from "@/components/charts/KlineChart";
import { SentimentChart } from "@/components/charts/SentimentChart";
import { useKline } from "@/hooks/useKline";
import { useSentiment } from "@/hooks/useSentiment";
import { mockSignals } from "@/lib/mock/signals";

export function ReplayReport({ symbol }: { symbol: string }) {
  const kline = useKline(symbol);
  const sentiment = useSentiment(symbol);
  const signals = mockSignals();

  return (
    <div className="space-y-lg">
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="text-title-lg text-on-dark">{symbol} 复盘</h2>
          <div className="text-body-sm text-muted">2024-03-15 全天 · 价格 + 成交量 + 散户情绪</div>
        </div>
      </div>

      <Card variant="surface-dark">
        <div className="p-lg">
          <div className="text-caption text-muted mb-sm">价格走势 + 成交量 + 信号标注</div>
          {kline.data && <KlineChart bars={kline.data} signals={signals} />}
        </div>
      </Card>

      <Card variant="surface-dark">
        <div className="p-lg">
          <div className="text-caption text-muted mb-sm">散户情绪曲线</div>
          {sentiment.data && <SentimentChart points={sentiment.data} />}
        </div>
      </Card>

      <Card variant="surface-dark">
        <div className="p-lg">
          <div className="text-caption text-muted mb-md">信号清单</div>
          <div className="space-y-sm">
            {signals.map((s) => (
              <div key={s.ts} className="flex justify-between text-body-md border-b border-hairline-ondark pb-sm">
                <span className="text-on-dark">{s.label}</span>
                <span className={s.direction === "buy" ? "text-trading-up" : s.direction === "sell" ? "text-trading-down" : "text-primary"}>
                  {s.direction === "buy" ? "买" : s.direction === "sell" ? "卖" : "警示"} @ {s.price.toFixed(2)}
                </span>
              </div>
            ))}
          </div>
        </div>
      </Card>
    </div>
  );
}
```

- [ ] **Step 4: 复盘页面**

`web/src/app/replay/page.tsx`:
```tsx
import { ReplayReport } from "@/components/replay/ReplayReport";

export default function ReplayPage() {
  return <ReplayReport symbol="000001" />;
}
```

- [ ] **Step 5: 验证 build + 手动预览**

Run: `cd web && npx next build`
Expected: build 成功

Run: `cd web && npx next dev`，浏览器打开 `http://localhost:3000/replay`
Expected: 看到深黑底 + K 线图（涨绿跌红）+ 成交量副图 + 黄色信号标注 + 紫黄情绪曲线 + 信号清单（币安黄/涨绿跌红配色）。确认后 Ctrl+C 停止 dev。

- [ ] **Step 6: Commit**

```bash
git add web/src/components/charts/ web/src/components/replay/ web/src/app/replay/
git commit -m "add replay report page with kline, volume, sentiment, signal markers"
```

---

## Self-Review（plan 作者自检）

**1. Spec coverage：**
- DESIGN.md 视觉映射 → Task 2（Tailwind theme）✓
- 基础组件（button/card/market-table/top-nav）→ Task 3/4/5 ✓
- 三合一复盘报表（v0.5 §4.10）→ Task 7 ✓
- mock 数据 + hooks 抽象（便于接真 API）→ Task 6 ✓
- 项目骨架 → Task 1 ✓

**2. Placeholder scan：** 无 TBD/TODO；每步含完整代码与命令。lightweight-charts 的 `time as any` 是该库对时间戳类型的已知宽松（number epoch 秒），非占位。

**3. Type consistency：** `Bar/SentimentPoint/ReplaySignal/MarketRow` 类型在 domain.ts 定义，被 mock/hooks/charts 一致使用。`Button` variant 字符串与测试一致。`Card` variant 与使用处一致。

**4. 已知限制：**
- 字体用 Inter + IBM Plex Sans（BinanceNova/Plex 是付费字体，DESIGN.md 建议的替代）。
- 复盘页用 mock 数据；后续接真 API 只改 hooks 的 queryFn。
- lightweight-charts marker API（setMarkers）在 v4 有效；v5 可能变（实现时锁定 4.2.0）。
- 未覆盖：交易终端/监控/研究界面（第 2-4 期 plan）。
