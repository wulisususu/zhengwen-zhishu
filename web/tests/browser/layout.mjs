// Layout checks: horizontal overflow, clipped or covered controls, A4 preview
// geometry and dialog usability, per page and viewport.
import { isInViewport, isUnobstructed, navigate, switchIdentity } from "./helpers.mjs";

const PAGES = [
  { path: "/gov", key: "home", keyButtons: [] },
  { path: "/gov/policy-qa", key: "policy-qa", keyButtons: ["提问"] },
  { path: "/gov/summary", key: "summary", keyButtons: ["开始提炼"] },
  { path: "/gov/draft", key: "draft", keyButtons: ["保存草稿", "导出", "提交审核"], a4: true },
  { path: "/gov/proofread", key: "proofread", keyButtons: ["前往审核中心"], a4: true },
  { path: "/gov/review-center", key: "review-center", keyButtons: ["退回修改", "审核通过"], reviewer: true },
];

async function pageReport(page) {
  return page.evaluate(() => {
    const overflow = Math.max(document.documentElement.scrollWidth, document.body.scrollWidth) - window.innerWidth;
    const controls = [...document.querySelectorAll("button, a.gov-btn, input, select, textarea")].filter((el) => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== "hidden";
    });
    const label = (el) => (el.textContent || el.getAttribute("aria-label") || el.tagName).trim().slice(0, 24);
    const clipped = controls.filter((el) => {
      const r = el.getBoundingClientRect();
      return r.right > window.innerWidth + 1 || r.left < -1;
    }).map(label);
    const squeezed = [...document.querySelectorAll(".gov-btn")]
      .filter((el) => el.getBoundingClientRect().width > 0 && el.scrollWidth > el.clientWidth + 1)
      .map(label);
    return { overflow, clipped, squeezed };
  });
}

async function a4Report(page) {
  return page.evaluate(() => {
    const pageEl = document.querySelector(".gov-a4-page");
    const frame = document.querySelector(".gov-a4-frame");
    const desk = document.querySelector(".gov-a4-desk");
    if (!pageEl || !frame || !desk) return null;
    const scale = Number((pageEl.style.transform.match(/scale\(([\d.]+)\)/) || [])[1] || 0);
    return {
      width: pageEl.offsetWidth,
      height: pageEl.offsetHeight,
      scale,
      fitsDesk: frame.getBoundingClientRect().width <= desk.clientWidth + 1,
      deskScrollsX: desk.scrollWidth > desk.clientWidth + 1,
    };
  });
}

/** Opens a dialog with `open`, checks it is usable, then closes it with Escape. */
async function checkDialog(page, check, name, open) {
  await open();
  const dialog = page.getByRole("dialog");
  await dialog.waitFor({ state: "visible", timeout: 3000 }).catch(() => {});
  if (!(await dialog.isVisible())) {
    check(`dialog「${name}」opens`, false);
    return;
  }
  const inView = await isInViewport(dialog);
  const buttons = dialog.getByRole("button");
  const count = await buttons.count();
  let blocked = 0;
  for (let i = 0; i < count; i++) if (!(await isUnobstructed(buttons.nth(i))) || !(await isInViewport(buttons.nth(i)))) blocked += 1;
  const focusInside = await dialog.evaluate((el) => el.contains(document.activeElement));
  await page.keyboard.press("Escape");
  await page.waitForTimeout(150);
  const closed = !(await dialog.isVisible());
  check(`dialog「${name}」usable`, inView && blocked === 0 && focusInside && closed, `inView=${inView} blockedButtons=${blocked}/${count} focusInside=${focusInside} escCloses=${closed}`);
}

export async function runLayout(page, { check, base, shotDir }) {
  for (const pg of PAGES) {
    await page.goto(base + pg.path, { waitUntil: "networkidle" });
    if (pg.reviewer) {
      await switchIdentity(page, "reviewer");
    }
    await page.waitForTimeout(300);

    const r = await pageReport(page);
    check(`${pg.path} no horizontal overflow`, r.overflow <= 0, `overflow=${r.overflow}px`);
    check(`${pg.path} no clipped controls`, !r.clipped.length, r.clipped.join(", "));
    check(`${pg.path} no squeezed button labels`, !r.squeezed.length, r.squeezed.join(", "));
    for (const name of pg.keyButtons) {
      // Some key actions are router links styled as buttons.
      const btn = page.getByRole("button", { name, exact: true }).or(page.getByRole("link", { name, exact: true })).first();
      const ok = (await btn.count()) > 0 && (await isInViewport(btn)) && (await isUnobstructed(btn));
      check(`${pg.path} key button「${name}」visible and not covered`, ok);
    }
    if (pg.a4) {
      const a4 = await a4Report(page);
      check(
        `${pg.path} A4 preview geometry`,
        !!a4 && a4.width === 794 && a4.height >= 1123 && a4.scale >= 0.3 && a4.scale <= 1.25 && a4.fitsDesk && !a4.deskScrollsX,
        a4 ? `page=${a4.width}×${a4.height} scale=${a4.scale.toFixed(3)} fitsDesk=${a4.fitsDesk}` : "no preview",
      );
    }
    await page.screenshot({ path: `${shotDir}/${pg.key}.png` });
  }

  // Dialogs (drafter identity, fresh state).
  await page.goto(base + "/gov/draft", { waitUntil: "networkidle" });
  await checkDialog(page, check, "导出", () => page.getByRole("button", { name: "导出", exact: true }).click());
  await checkDialog(page, check, "提交审核", () => page.getByRole("button", { name: "提交审核", exact: true }).click());
  const materialsToggle = page.getByRole("button", { name: "要素与材料" });
  if (await materialsToggle.count()) await materialsToggle.click();
  await checkDialog(page, check, "添加材料", () => page.getByRole("button", { name: "添加材料" }).click());
  await checkDialog(page, check, "申请例外", () =>
    page.locator("article.gov-issue", { hasText: "发文字号格式错误" }).getByRole("button", { name: "申请例外…" }).click(),
  );
  await page.getByRole("button", { name: "导出", exact: true }).click();
  await page.screenshot({ path: `${shotDir}/dialog-export.png` });
  await page.keyboard.press("Escape");

  await navigate(page, "/gov/proofread");
  await checkDialog(page, check, "审核记录", () => page.getByRole("button", { name: /^审核记录/ }).click());

  await switchIdentity(page, "reviewer");
  await navigate(page, "/gov/review-center");
  await checkDialog(page, check, "审核通过确认", () => page.getByRole("button", { name: "审核通过", exact: true }).click());
}
