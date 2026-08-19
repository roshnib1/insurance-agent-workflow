import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Standalone output = a self-contained server bundle (only the node_modules this
  // app actually uses, traced automatically) instead of shipping the full
  // node_modules tree into the Docker image. Doesn't change app behavior — this repo
  // has no API routes/SSR data fetching for it to affect — just makes the production
  // image far smaller and the container start faster.
  output: "standalone",
};

export default nextConfig;