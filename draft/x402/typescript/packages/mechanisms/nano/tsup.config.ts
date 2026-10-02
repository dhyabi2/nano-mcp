import { defineConfig } from "tsup";

export default defineConfig({
  entry: [
    "src/index.ts",
    "src/exact/client/index.ts",
    "src/exact/server/index.ts",
    "src/exact/facilitator/index.ts",
  ],
  format: ["cjs", "esm"],
  dts: true,
  clean: true,
  sourcemap: true,
  target: "es2022",
  outDir: "dist",
  splitting: false,
  external: ["@x402/core"],
});