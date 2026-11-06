// The website: Astro + React islands, served at /football-analysis/ on
// GitHub Pages and built into web/dist.

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import react from "@astrojs/react";
import { defineConfig } from "astro/config";

// The pipeline's JSON (src/export_web.py writes it into web/src/data), read
// through an alias. FP_DATA_DIR
// points the build at another copy (src/lib/data.ts validates whatever it
// finds, so a broken copy must fail the build).
const DATA_DIR = process.env.FP_DATA_DIR
  ? resolve(process.env.FP_DATA_DIR)
  : fileURLToPath(new URL("./src/data", import.meta.url));
const DATA_LABEL = process.env.FP_DATA_DIR ?? "web/src/data";

export default defineConfig({
  site: "https://hphillips9.github.io",
  base: "/football-analysis",
  trailingSlash: "ignore",
  outDir: "./dist",
  build: {
    // /e0/table/index.html, so /e0/table and /e0/table/ both work on Pages
    format: "directory",
  },
  integrations: [react()],
  vite: {
    // Where the data came from, for data.ts's error messages
    define: { "import.meta.env.FP_DATA_DIR": JSON.stringify(DATA_LABEL) },
    resolve: {
      alias: { "@data": DATA_DIR },
    },
    server: {
      // The dev server may serve files from these folders only
      fs: { allow: [fileURLToPath(new URL(".", import.meta.url)), DATA_DIR] },
    },
  },
});
