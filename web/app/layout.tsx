import type { Metadata } from "next";
import { Instrument_Sans, Instrument_Serif, JetBrains_Mono } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/shell";
import { cn } from "@/lib/utils";

// Interface text, the big editorial titles, and numbers/code.
const sans = Instrument_Sans({ subsets: ["latin"], variable: "--font-ui", display: "swap" });
const serif = Instrument_Serif({ subsets: ["latin"], weight: "400", style: ["normal", "italic"], variable: "--font-serif", display: "swap" });
const mono = JetBrains_Mono({ subsets: ["latin"], variable: "--font-code", display: "swap" });

export const metadata: Metadata = {
  title: "ReelForge",
  description: "Idea in, film out.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={cn(sans.variable, serif.variable, mono.variable, "flex min-h-screen flex-col font-sans")}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
