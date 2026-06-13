"use client";

import { useState } from "react";
import { clsx } from "clsx";
import { FactorEvalChart } from "@/components/research/FactorEvalChart";
import { BacktestResultPanel } from "@/components/research/BacktestResultPanel";
import { StrategyLifecycleTable } from "@/components/research/StrategyLifecycleTable";
import { useFactorEval } from "@/hooks/useFactorEval";
import { useBacktest } from "@/hooks/useBacktest";
import { useStrategyLifecycle } from "@/hooks/useStrategyLifecycle";

export function ResearchDashboard() {
  const factors = useFactorEval();
  const backtest = useBacktest();
  const lifecycle = useStrategyLifecycle();

  const factorList = factors.data ?? [];
  const [activeFactor, setActiveFactor] = useState(0);
  const active = factorList[activeFactor];

  return (
    <div className="space-y-lg">
      <h1 className="text-title-lg text-on-dark">研究回测</h1>

      {/* Factor selector tabs */}
      <div className="flex flex-wrap gap-xs" role="tablist">
        {factorList.map((f, i) => (
          <button
            key={f.name}
            role="tab"
            aria-selected={i === activeFactor}
            data-testid={`factor-tab-${f.name}`}
            onClick={() => setActiveFactor(i)}
            className={clsx(
              "rounded-sm px-md py-sm text-body-md",
              i === activeFactor
                ? "bg-primary text-on-primary"
                : "bg-surface-card-dark text-muted hover:text-body",
            )}
          >
            {f.name}
          </button>
        ))}
      </div>

      {active && <FactorEvalChart factor={active} />}

      {backtest.data && <BacktestResultPanel result={backtest.data} />}

      <StrategyLifecycleTable rows={lifecycle.data ?? []} />
    </div>
  );
}
