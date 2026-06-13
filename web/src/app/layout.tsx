import "./globals.css";
import type { Metadata } from "next";
import { Inter, IBM_Plex_Sans } from "next/font/google";
import { Providers } from "./providers";
import { TopNav } from "@/components/ui/TopNav";

const displayFont = Inter({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});

const numberFont = IBM_Plex_Sans({
  subsets: ["latin"],
  weight: ["500", "700"],
  variable: "--font-number",
  display: "swap",
});

export const metadata: Metadata = { title: "A 股量化交易系统", description: "Quant trading UI" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" className={`${displayFont.variable} ${numberFont.variable}`}>
      <body>
        <Providers>
          <TopNav />
          <main className="max-w-[1440px] mx-auto px-lg py-lg">{children}</main>
        </Providers>
      </body>
    </html>
  );
}
