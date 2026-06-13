import "./globals.css";
import type { Metadata } from "next";

export const metadata: Metadata = { title: "A 股量化交易系统", description: "Quant trading UI" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
