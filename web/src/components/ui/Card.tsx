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
