import preact from "@preact/preset-vite";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import { viteSingleFile } from "vite-plugin-singlefile";

// One self-contained web/dist/index.html: the desktop app hands it to pywebview
// as an HTML string, and a Cursor extension can set it as a webview's html.
export default defineConfig(({ command }) => ({
  plugins: [preact(), viteSingleFile({ removeViteModuleLoader: true })],
  // Compile-time switch: production builds drop the mock host and its fixture entirely.
  define: { __MOCK__: JSON.stringify(command === "serve" || process.env.VITE_MOCK === "1") },
  base: "./",
  build: {
    outDir: fileURLToPath(new URL("../../web/dist", import.meta.url)),
    emptyOutDir: true,
    target: "es2022",
    sourcemap: false,
  },
}));
