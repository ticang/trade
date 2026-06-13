// Color tokens mirror tailwind.config.ts (source of truth); this file exposes raw hex for chart/inline-style use. If a DESIGN.md color changes, update BOTH.
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
