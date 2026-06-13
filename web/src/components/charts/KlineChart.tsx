"use client";
import { useEffect, useRef } from "react";
import { createChart, ColorType } from "lightweight-charts";
import { Bar, ReplaySignal } from "@/types/domain";
import { theme } from "@/lib/theme";

interface Props {
  bars: Bar[];
  signals?: ReplaySignal[];
}

export function KlineChart({ bars, signals = [] }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = createChart(ref.current, {
      layout: { background: { type: ColorType.Solid, color: theme.colors.surfaceCardDark }, textColor: theme.colors.body },
      grid: { vertLines: { color: theme.colors.hairlineOnDark }, horzLines: { color: theme.colors.hairlineOnDark } },
      width: ref.current.clientWidth,
      height: 360,
    });

    const candle = chart.addCandlestickSeries({
      upColor: theme.colors.tradingUp,
      downColor: theme.colors.tradingDown,
      borderUpColor: theme.colors.tradingUp,
      borderDownColor: theme.colors.tradingDown,
      wickUpColor: theme.colors.tradingUp,
      wickDownColor: theme.colors.tradingDown,
    });
    candle.setData(
      bars.map((b) => ({ time: (b.ts / 1000) as any, open: b.open, high: b.high, low: b.low, close: b.close }))
    );

    const vol = chart.addHistogramSeries({ priceScaleId: "vol", color: theme.colors.muted });
    vol.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    vol.setData(
      bars.map((b) => ({
        time: (b.ts / 1000) as any,
        value: b.volume,
        color: b.close >= b.open ? theme.colors.tradingUp : theme.colors.tradingDown,
      }))
    );

    if (signals.length > 0) {
      candle.setMarkers(
        signals.map((s) => ({
          time: (s.ts / 1000) as any,
          position: s.direction === "buy" ? "belowBar" : "aboveBar",
          color:
            s.direction === "buy"
              ? theme.colors.tradingUp
              : s.direction === "sell"
                ? theme.colors.tradingDown
                : theme.colors.primary,
          shape: s.direction === "buy" ? "arrowUp" : s.direction === "sell" ? "arrowDown" : "circle",
          text: s.label,
        }))
      );
    }

    const onResize = () => chart.applyOptions({ width: ref.current?.clientWidth || 800 });
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.remove();
    };
  }, [bars, signals]);

  return <div ref={ref} className="w-full" />;
}
