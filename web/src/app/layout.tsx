import "./globals.css";
import type { Metadata } from "next";
import { Providers } from "./providers";
import { TopNav } from "@/components/ui/TopNav";

export const metadata: Metadata = { title: "A 股量化交易系统", description: "Quant trading UI" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN">
      <body>
        <Providers>
          <TopNav />
          <main className="max-w-[1440px] mx-auto px-lg py-lg">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
