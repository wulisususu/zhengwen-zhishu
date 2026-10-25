// Shared helpers for the browser checks (gov-office workbench).
import { chromium } from "playwright-core";

export const VIEWPORTS = [
  { width: 1280, height: 800 },
  { width: 1440, height: 900 },
  { width: 1920, height: 1080 },
];

/** Use CHROME_PATH if given, else the installed Chrome, else Edge (always present on Windows). */
export async function launchBrowser() {
  if (process.env.CHROME_PATH) return chromium.launch({ executablePath: process.env.CHROME_PATH, args: ["--no-sandbox"] });
  const channels = process.env.BROWSER_CHANNEL ? [process.env.BROWSER_CHANNEL] : ["chrome", "msedge"];
  let lastError;
  for (const channel of channels) {
    try {
      return await chromium.launch({ channel, args: ["--no-sandbox"] });
    } catch (err) {
      lastError = err;
    }
  }
  throw new Error(`找不到可用的 Chrome / Edge，可用 CHROME_PATH 指定浏览器路径。\n${lastError}`);
}

/** A fresh context per viewport: the mock adapter resets on every full page load. */
export async function newContext(browser, viewport) {
  const context = await browser.newContext({ viewport, deviceScaleFactor: 1 });
  // The app's router guard needs a session token; gov pages use the mock adapter only.
  await context.addInitScript(() => localStorage.setItem("mqw-session", JSON.stringify({ token: "browser-check" })));
  return context;
}

export function createReporter(label) {
  const results = [];
  return {
    results,
    check(name, ok, detail = "") {
      results.push({ viewport: label, name, ok: !!ok, detail });
      console.log(`  ${ok ? "PASS" : "FAIL"} [${label}] ${name}${detail ? ` — ${detail}` : ""}`);
    },
  };
}

/** True if the element's center point is not covered by another element. */
export async function isUnobstructed(locator) {
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    if (!r.width || !r.height) return false;
    const x = Math.min(window.innerWidth - 1, r.left + r.width / 2);
    const y = Math.min(window.innerHeight - 1, r.top + r.height / 2);
    const hit = document.elementFromPoint(x, y);
    return !!hit && (hit === el || el.contains(hit));
  });
}

/** Fully inside the viewport horizontally and vertically. */
export async function isInViewport(locator) {
  return locator.evaluate((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left >= -1 && r.top >= -1 && r.right <= window.innerWidth + 1 && r.bottom <= window.innerHeight + 1;
  });
}

/** Switch the demo identity through the sidebar (expanded toggle or collapsed mini button). */
export async function switchIdentity(page, role) {
  const label = role === "reviewer" ? "审核人" : "起草人";
  const seg = page.locator(".gov-nav__identity-seg");
  if (await seg.isVisible()) {
    await seg.getByRole("button", { name: label, exact: true }).click();
  } else {
    const mini = page.locator(".gov-nav__identity-mini");
    if ((await mini.textContent()).trim() !== label.slice(0, 1)) await mini.click();
  }
  await page.waitForTimeout(150);
}

export async function currentAccount(page) {
  const account = page.locator(".gov-nav__identity-account");
  if (await account.isVisible()) return (await account.textContent()).trim();
  return (await page.locator(".gov-nav__identity-mini").getAttribute("aria-label")) ?? "";
}

export async function navigate(page, path) {
  await page.locator(`.gov-nav a[href='${path}']`).click();
  await page.waitForTimeout(350);
}
