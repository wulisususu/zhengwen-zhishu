// Browser checks for the gov-office workbench.
//
//   npm run test:browser        build, then check 1280×800 / 1440×900 / 1920×1080
//   node tests/browser/run.mjs  check an existing dist/ build
//
// Screenshots and report.json go to tests/browser/shots/ (git-ignored).
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { preview } from "vite";
import { createReporter, launchBrowser, newContext, VIEWPORTS } from "./helpers.mjs";
import { runLayout } from "./layout.mjs";
import { runFlows } from "./flows.mjs";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = join(here, "..", "..");
const shotsRoot = join(here, "shots");
rmSync(shotsRoot, { recursive: true, force: true });
mkdirSync(shotsRoot, { recursive: true });

const server = await preview({ root: webRoot, logLevel: "warn", preview: { host: "127.0.0.1", port: 4317, strictPort: false } });
const base = (server.resolvedUrls?.local[0] ?? "http://127.0.0.1:4317/").replace(/\/$/, "");
const browser = await launchBrowser();
const all = [];

try {
  for (const viewport of VIEWPORTS) {
    const label = `${viewport.width}x${viewport.height}`;
    const shotDir = join(shotsRoot, label);
    mkdirSync(shotDir, { recursive: true });
    console.log(`\n== ${label}`);
    const reporter = createReporter(label);
    const pageErrors = [];
    for (const suite of ["layout", "flows"]) {
      const context = await newContext(browser, viewport);
      const page = await context.newPage();
      page.on("pageerror", (e) => pageErrors.push(`${suite}: ${e}`));
      try {
        if (suite === "layout") await runLayout(page, { check: reporter.check, base, shotDir });
        else await runFlows(page, { check: reporter.check, base, shotDir, compact: viewport.width < 1366 });
      } catch (err) {
        reporter.check(`${suite} suite completed`, false, String(err).split("\n")[0]);
        await page.screenshot({ path: join(shotDir, `${suite}-error.png`) }).catch(() => {});
      }
      await context.close();
    }
    reporter.check("no uncaught page errors", pageErrors.length === 0, pageErrors.join(" | "));
    all.push(...reporter.results);
  }
} finally {
  await browser.close();
  await new Promise((resolve) => server.httpServer.close(resolve));
}

const failed = all.filter((r) => !r.ok);
writeFileSync(join(shotsRoot, "report.json"), JSON.stringify({ at: new Date().toISOString(), total: all.length, failed: failed.length, results: all }, null, 2));
console.log(`\n${all.length - failed.length}/${all.length} checks passed across ${VIEWPORTS.length} viewports`);
if (failed.length) {
  console.log("Failed:");
  failed.forEach((f) => console.log(`  [${f.viewport}] ${f.name}${f.detail ? ` — ${f.detail}` : ""}`));
}
console.log(`Screenshots: ${shotsRoot}`);
process.exit(failed.length ? 1 : 0);
