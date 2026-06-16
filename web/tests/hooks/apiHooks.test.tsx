import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { useAccount } from "@/hooks/useAccount";
import { useAlerts } from "@/hooks/useAlerts";
import { useBacktest } from "@/hooks/useBacktest";
import { useFactorEval } from "@/hooks/useFactorEval";
import { useFills } from "@/hooks/useFills";
import { useKline } from "@/hooks/useKline";
import { useMarkets } from "@/hooks/useMarkets";
import { useOrders } from "@/hooks/useOrders";
import { usePositions } from "@/hooks/usePositions";
import { useRisk } from "@/hooks/useRisk";
import { useSentiment } from "@/hooks/useSentiment";
import { useStrategies } from "@/hooks/useStrategies";
import { useStrategyLifecycle } from "@/hooks/useStrategyLifecycle";
import { apiGet } from "@/lib/api/client";

vi.mock("@/lib/api/client", () => ({
  apiGet: vi.fn(),
}));

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>;
}

describe("API-backed hooks", () => {
  beforeEach(() => {
    vi.mocked(apiGet).mockReset();
    vi.mocked(apiGet).mockResolvedValue([]);
  });

  it.each([
    ["markets", () => useMarkets(), "/api/markets"],
    ["kline", () => useKline("600519"), "/api/kline/600519"],
    ["sentiment", () => useSentiment("600519"), "/api/sentiment/600519"],
    ["account", () => useAccount(), "/api/account"],
    ["positions", () => usePositions(), "/api/positions"],
    ["orders", () => useOrders(), "/api/orders"],
    ["fills", () => useFills(), "/api/fills"],
    ["risk", () => useRisk(), "/api/risk"],
    ["alerts", () => useAlerts(), "/api/alerts"],
    ["strategies", () => useStrategies(), "/api/strategies"],
    ["factor-eval", () => useFactorEval(), "/api/factor-eval"],
    ["backtest", () => useBacktest(), "/api/backtest"],
    ["strategy-lifecycle", () => useStrategyLifecycle(), "/api/strategy-lifecycle"],
  ])("%s uses the read-only API endpoint", async (_name, useHook, endpoint) => {
    renderHook(useHook, { wrapper });

    await waitFor(() => expect(apiGet).toHaveBeenCalledWith(endpoint));
  });
});
