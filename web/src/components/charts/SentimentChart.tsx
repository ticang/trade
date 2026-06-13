"use client";
import { LineChart, Line, XAxis, YAxis, ReferenceLine, ResponsiveContainer, Tooltip } from "recharts";
import { SentimentPoint } from "@/types/domain";
import { theme } from "@/lib/theme";

interface Props {
  points: SentimentPoint[];
}

export function SentimentChart({ points }: Props) {
  const data = points.map((p) => ({ ts: p.ts, score: p.score }));
  return (
    <div className="h-[160px]">
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <XAxis dataKey="ts" tick={false} axisLine={{ stroke: theme.colors.hairlineOnDark }} />
          <YAxis
            domain={[-1, 1]}
            tick={{ fill: theme.colors.muted, fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            width={32}
          />
          <ReferenceLine y={0} stroke={theme.colors.hairlineOnDark} />
          <Tooltip
            contentStyle={{
              background: theme.colors.surfaceCardDark,
              border: `1px solid ${theme.colors.hairlineOnDark}`,
              color: theme.colors.body,
            }}
          />
          <Line type="monotone" dataKey="score" stroke={theme.colors.primary} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
