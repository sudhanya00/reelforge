import type { Metadata } from "next";
import { GeistSans } from "geist/font/sans";
import { GeistMono } from "geist/font/mono";
import "./globals.css";
import { Providers } from "@/components/shell";
import { cn } from "@/lib/utils";

export const metadata: Metadata = {
  title: "ReelForge",
  description: "Idea in, film out.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={cn(GeistSans.variable, GeistMono.variable, "flex min-h-screen flex-col font-sans")}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
