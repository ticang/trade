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
            className={clsx(
              "text-nav-link",
              pathname === n.href ? "text-primary" : "text-body hover:text-primary",
            )}
          >
            {n.label}
          </Link>
        ))}
      </div>
    </nav>
  );
}
