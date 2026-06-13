import { BacktestPoint, BacktestResult } from "@/types/research";

// Deterministic 90-point daily series: equity drifts up with periodic drawdown
// dips and a rising benchmark. No Math.random — fully reproducible.
function buildSeries(): BacktestPoint[] {
  const points: BacktestPoint[] = [];
  const DAY = 86400;
  const start = 1716422400; // 2024-05-23
  const n = 90;
  let equity = 1.0;
  let peak = 1.0;
  let benchmark = 1.0;
  // Fixed pseudo-noise cycle so output is byte-stable across runs.
  const noise = (i: number) => Math.sin(i * 0.7) * 0.004 + Math.cos(i * 1.3) * 0.003;

  for (let i = 0; i < n; i++) {
    // Base positive drift with a mid-sample drawdown window (i=30..42) and a
    // brief late dip (i=68..74).
    let drift = 0.0016 + noise(i);
    if (i >= 30 && i <= 42) drift -= 0.006; // drawdown episode
    if (i >= 68 && i <= 74) drift -= 0.004; // secondary dip
    equity = equity * (1 + drift);
    peak = Math.max(peak, equity);
    benchmark = benchmark * (1 + 0.0006 + noise(i) * 0.4);
    points.push({
      ts: start + i * DAY,
      equity: Number(equity.toFixed(5)),
      drawdown: Number((equity / peak - 1).toFixed(5)),
      benchmark: Number(benchmark.toFixed(5)),
    });
  }
  return points;
}

export function mockBacktest(): BacktestResult {
  const series = buildSeries();
  return {
    strategy: "multi_factor_alpha_v3",
    series,
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
      { factor: "momentum_20d", contribution: 0.063 },
    ],
  };
}
