import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Two lockfiles live in this repository (the newsroom app at the root and this one);
  // tell Next where this project starts so it does not guess the workspace root.
  turbopack: { root: __dirname },
  outputFileTracingRoot: __dirname,
};

export default nextConfig;
