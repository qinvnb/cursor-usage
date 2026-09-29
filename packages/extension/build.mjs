// Bundle the extension and copy the shared dashboard + icon into media/.
import { build } from "esbuild";
import { copyFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, "..", "..");
const dashboard = join(root, "web", "dist", "index.html");
if (!existsSync(dashboard)) {
  console.error("web/dist/index.html is missing: run `npm run build` at the repository root first");
  process.exit(1);
}

mkdirSync(join(here, "media"), { recursive: true });
copyFileSync(dashboard, join(here, "media", "dashboard.html"));
copyFileSync(join(root, "assets", "app.png"), join(here, "media", "icon.png"));
copyFileSync(join(root, "LICENSE"), join(here, "LICENSE"));

await build({
  entryPoints: [join(here, "src", "extension.ts")],
  outfile: join(here, "dist", "extension.js"),
  bundle: true,
  platform: "node",
  format: "cjs",
  target: "node20",
  external: ["vscode"],
  sourcemap: false,
  minify: true,
  logLevel: "info",
});
