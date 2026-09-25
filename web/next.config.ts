import type { NextConfig } from "next";

// Exported as static files; server.py serves them and the API from one local process.
const nextConfig: NextConfig = {
  output: "export",
  images: { unoptimized: true },
  devIndicators: false,
};

export default nextConfig;
