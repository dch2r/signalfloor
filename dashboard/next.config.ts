import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // The Docker build asks for a self contained server without the full node_modules. Local
  // builds don't, because `next start` warns that it can't serve standalone output.
  output: process.env.NEXT_OUTPUT === "standalone" ? "standalone" : undefined,
  cacheComponents: true,
  partialPrefetching: true,
  // Don't write AGENTS.md or other files for AI coding tools into the project.
  agentRules: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
