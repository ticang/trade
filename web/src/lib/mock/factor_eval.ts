import { FactorEval } from "@/types/research";

// Daily timestamps for a 24-point IC series (one point per business day window).
const IC_TS = [
  1716422400, 1716681600, 1716768000, 1716854400, 1716940800, 1717200000,
  1717286400, 1717372800, 1717459200, 1717545600, 1717804800, 1717891200,
  1717977600, 1718064000, 1718323200, 1718409600, 1718496000, 1718582400,
  1718841600, 1718928000, 1719014400, 1719100800, 1719360000, 1719446400,
];

// Monotonic long-short decile returns: factor is valid, low quantile negative,
// high quantile positive, near-linear decay.
const QUANTILE_RETURNS = [-0.18, -0.13, -0.08, -0.04, -0.01, 0.02, 0.05, 0.09, 0.13, 0.18];

export function mockFactorEval(): FactorEval[] {
  return [
    {
      name: "price_reversal_5d",
      ic_series: IC_TS.map((ts, i) => ({
        ts,
        ic: [0.062, 0.048, 0.071, 0.053, 0.069, 0.082, 0.061, 0.074, 0.058, 0.066, 0.079, 0.071][
          i % 12
        ],
      })),
      ic: 0.068,
      ir: 0.74,
      turnover: 0.42,
      quantile_returns: QUANTILE_RETURNS,
      novelty_corr: 0.31,
    },
    {
      name: "earnings_surprise",
      ic_series: IC_TS.map((ts, i) => ({
        ts,
        ic: [0.091, 0.105, 0.087, 0.099, 0.112, 0.094, 0.108, 0.085, 0.101, 0.097, 0.113, 0.092][
          i % 12
        ],
      })),
      ic: 0.099,
      ir: 1.12,
      turnover: 0.28,
      quantile_returns: [-0.22, -0.15, -0.09, -0.03, 0.01, 0.04, 0.08, 0.12, 0.17, 0.24],
      novelty_corr: 0.45,
    },
    {
      name: "liquidity_amihud",
      ic_series: IC_TS.map((ts, i) => ({
        ts,
        ic: [-0.041, -0.028, -0.052, -0.037, -0.019, -0.044, -0.031, -0.048, -0.025, -0.036, -0.029, -0.042][
          i % 12
        ],
      })),
      ic: -0.036,
      ir: -0.52,
      turnover: 0.55,
      // Negative-IC factor: high quantile (illiquid) underperforms, curve inverted.
      quantile_returns: [0.14, 0.1, 0.06, 0.03, 0, -0.02, -0.05, -0.08, -0.11, -0.15],
      novelty_corr: 0.62,
    },
  ];
}
