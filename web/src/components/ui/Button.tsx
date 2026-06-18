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
  const disabledOverride = disabled
    ? isPrimary
      ? "bg-primary-disabled text-muted cursor-not-allowed"
      : "opacity-50 cursor-not-allowed"
    : "";
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
