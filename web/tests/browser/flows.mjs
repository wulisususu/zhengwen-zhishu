// Interaction flows: drafting, issue handling, two demo identities, review
// decisions and policy QA. Runs from a fresh page load (fresh mock state).
import { currentAccount, navigate, switchIdentity } from "./helpers.mjs";

export async function runFlows(page, { check, base, shotDir, compact }) {
  const card = (title) => page.locator("article.gov-issue", { hasText: title });
  const issueCount = async () => Number((await page.locator(".gov-issues__count").first().textContent()).trim());

  // ---------- identities and honesty markers ----------
  await page.goto(base + "/gov/draft", { waitUntil: "networkidle" });
  check("defaults to demo_drafter", (await currentAccount(page)).includes("演示起草人") || (await currentAccount(page)).includes("demo_drafter"));
  const navText = await page.locator(".gov-nav").evaluate((el) => el.textContent + (el.querySelector(".gov-nav__identity-mini")?.title ?? ""));
  check("no offline / 数据不出本机 claim", !navText.includes("数据不出本机") && !navText.includes("离线模式"));
  check("demo identity marked as demo permission", compact || navText.includes("演示权限"));

  // ---------- drafting ----------
  const critical = page.locator("article.gov-issue", { has: page.locator(".gov-tag--danger", { hasText: "严重" }) });
  let ignoreOnCritical = 0;
  for (let i = 0; i < (await critical.count()); i++) ignoreOnCritical += await critical.nth(i).getByRole("button", { name: "忽略提示" }).count();
  check("critical issues offer no ignore", (await critical.count()) > 0 && ignoreOnCritical === 0, `critical cards=${await critical.count()}`);
  check("warnings offer ignore", (await card("日期前后不一致").getByRole("button", { name: "忽略提示" }).count()) === 1);
  const disabledTypes = await page.locator("select.gov-select").first().locator("option:disabled").allTextContents();
  check("unsupported doc types disabled as 待支持", disabledTypes.length === 5 && disabledTypes.every((t) => t.includes("待支持")));

  const before = await issueCount();
  await card("发文字号格式错误").getByRole("button", { name: "采纳建议" }).click();
  await page.waitForTimeout(200);
  check("apply suggestion updates the A4 text", (await page.locator('[data-anchor="seg-docno"]').textContent()).includes("〔2025〕"));
  check("issue count decreases", (await issueCount()) === before - 1, `${before} -> ${await issueCount()}`);

  await card("缺少主送机关").getByRole("button", { name: "去填写" }).click();
  await page.waitForTimeout(200);
  check("去填写 focuses the field", (await page.evaluate(() => document.activeElement?.id)) === "gov-field-recipient");
  await page.keyboard.type("各区政务服务管理部门（演示）");
  await page.waitForTimeout(200);
  const recipient = await page.locator('[data-anchor="seg-recipient"]').textContent();
  check("typed field replaces 【待补充】 in A4 preview", recipient.includes("各区政务服务管理部门") && !recipient.includes("待补充"));

  await card("日期前后不一致").getByRole("button", { name: "定位" }).click();
  await page.waitForTimeout(700);
  const located = await page.evaluate(() => {
    const el = document.querySelector(".gov-a4-page .is-focus");
    const desk = document.querySelector(".gov-a4-desk");
    if (!el || !desk) return false;
    const r = el.getBoundingClientRect();
    const d = desk.getBoundingClientRect();
    return el.getAttribute("data-anchor") === "seg-date" && r.top >= d.top && r.bottom <= d.bottom;
  });
  check("定位 scrolls A4 preview and highlights the passage", located);
  await page.screenshot({ path: `${shotDir}/flow-locate.png` });

  const ai = card("处罚性表述缺少政策依据");
  check("AI critical needs human review first", (await ai.locator(".gov-tag", { hasText: "待人工复核" }).count()) === 1 && (await ai.getByRole("button", { name: "采纳建议" }).count()) === 0);
  await ai.getByRole("button", { name: "判定不成立…" }).click();
  await page.getByRole("dialog").getByRole("button", { name: "确认不成立" }).click();
  check("dismissal without reason is refused", (await page.getByRole("dialog").getByRole("alert").count()) === 1);
  await page.getByRole("dialog").locator("textarea").fill("已补充绩效考核依据（演示）");
  await page.getByRole("dialog").getByRole("button", { name: "确认不成立" }).click();
  await page.waitForTimeout(200);
  check("AI issue dismissed with reason", (await ai.count()) === 0);

  await card("引用政策已废止").getByRole("button", { name: "申请例外…" }).click();
  await page.getByRole("dialog").locator("textarea").fill("历史对照引用（演示）");
  await page.getByRole("dialog").getByRole("button", { name: "提交例外申请" }).click();
  await page.waitForTimeout(200);
  check("exception request still blocks", (await card("引用政策已废止").locator(".gov-tag", { hasText: "例外待审核人批准" }).count()) === 1);

  await page.getByRole("button", { name: "导出", exact: true }).click();
  const exportDialog = page.getByRole("dialog");
  check("formal export disabled before approval", await exportDialog.getByRole("button", { name: "正式导出 DOCX" }).isDisabled());
  await exportDialog.getByRole("button", { name: "导出内部草稿" }).click();
  await page.waitForTimeout(150);
  check("internal draft export never claims a file", (await exportDialog.getByRole("status").textContent()).includes("未生成文件"));
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: "提交审核", exact: true }).click();
  check("submit warns about remaining blockers", (await page.getByRole("dialog").textContent()).includes("项严重问题未处理"));
  await page.getByRole("dialog").getByRole("button", { name: "确认提交" }).click();
  await page.waitForTimeout(200);
  check("submit drives status to 待审核", (await page.locator(".gov-header .gov-tag", { hasText: "待审核" }).count()) === 1);
  check("editing locked while pending", await page.getByRole("button", { name: "保存草稿" }).isDisabled());

  // ---------- drafter cannot review ----------
  await navigate(page, "/gov/review-center");
  check("drafter sees no-review-permission notice", (await page.locator(".gov-rc__role").count()) === 1);
  await page.locator(".gov-table__row", { hasText: "关于开展2025年度政务数据安全自查工作的通知" }).click();
  check("drafter cannot approve own submission", await page.getByRole("button", { name: "审核通过", exact: true }).isDisabled());

  // ---------- reviewer ----------
  await switchIdentity(page, "reviewer");
  check("switched to demo_reviewer", (await currentAccount(page)).includes("审核人") || (await currentAccount(page)).includes("demo_reviewer"));
  await page.locator(".gov-table__row", { hasText: "关于开展2025年度政务数据安全自查工作的通知" }).click();
  await page.waitForTimeout(150);
  check("approve blocked while critical issues remain", await page.getByRole("button", { name: "审核通过", exact: true }).isDisabled());
  check("blocked reason shown", (await page.locator(".gov-rc__reason").textContent()).includes("严重问题"));
  await page.locator("article.gov-issue", { hasText: "引用政策已废止" }).getByRole("button", { name: "批准例外…" }).click();
  await page.getByRole("dialog").locator("textarea").fill("同意按历史对照保留（演示）");
  await page.getByRole("dialog").getByRole("button", { name: "批准例外" }).click();
  await page.waitForTimeout(200);
  check("reviewer exception approval recorded", (await page.locator(".gov-rc__reviewed", { hasText: "引用政策已废止" }).count()) === 1);
  await page.getByRole("button", { name: "退回修改", exact: true }).click();
  check("return requires an opinion", (await page.locator(".gov-rc__error").count()) === 1);
  await page.locator("#gov-rc-opinion").fill("请补充发文机关署名（演示）");
  await page.getByRole("button", { name: "退回修改", exact: true }).click();
  await page.waitForTimeout(300);
  const lastRecord = await page.locator(".gov-timeline__item").first().textContent();
  check("return recorded under demo reviewer", lastRecord.includes("退回修改") && lastRecord.includes("演示审核人") && lastRecord.includes("请补充发文机关署名"));
  await page.screenshot({ path: `${shotDir}/flow-review-returned.png` });

  await navigate(page, "/gov/draft");
  check("reviewer cannot edit drafts", (await page.locator(".gov-banner", { hasText: "没有起草权限" }).count()) === 1 && (await page.getByRole("button", { name: "保存草稿" }).isDisabled()));

  // ---------- drafter sees the result ----------
  await switchIdentity(page, "drafter");
  await page.waitForTimeout(150);
  const result = page.locator(".gov-banner", { hasText: "审核结果" });
  check("drafter sees review result and opinion", (await result.count()) === 1 && (await result.textContent()).includes("请补充发文机关署名"));
  check("returned draft editable again", !(await page.getByRole("button", { name: "保存草稿" }).isDisabled()));

  // ---------- reviewer approves a clean document ----------
  await switchIdentity(page, "reviewer");
  await navigate(page, "/gov/review-center");
  await page.locator(".gov-filter__chip", { hasText: "待审核" }).click();
  await page.locator(".gov-table__row", { hasText: "2025年第三季度政务服务工作情况报告" }).click();
  await page.getByRole("tab", { name: "文稿预览" }).click();
  await page.waitForTimeout(400);
  const scale = await page.evaluate(() => Number((document.querySelector(".gov-rc__preview .gov-a4-page")?.style.transform.match(/scale\(([\d.]+)\)/) || [])[1] || 0));
  check("review preview rescales when shown", scale > 0.35, `scale=${scale.toFixed(3)}`);
  await page.getByRole("tab", { name: "审核要点" }).click();
  await page.getByRole("button", { name: "审核通过", exact: true }).click();
  await page.getByRole("dialog").getByRole("button", { name: "确认通过" }).click();
  await page.waitForTimeout(300);
  await page.locator(".gov-filter__chip", { hasText: "审核通过" }).click();
  check("approved document listed as 审核通过", (await page.locator(".gov-table__row", { hasText: "2025年第三季度政务服务工作情况报告" }).count()) === 1);

  // ---------- policy QA ----------
  await navigate(page, "/gov/policy-qa");
  await page.locator(".gov-cite", { hasText: "[1] 第六条" }).click();
  check("citation chip opens clause detail", (await page.locator(".gov-evidence__clause-text").textContent()).includes("正常经营满一年"));
  await page.screenshot({ path: `${shotDir}/flow-citation.png` });
  const historyButton = page.getByRole("button", { name: /^会话记录（/ });
  if (await historyButton.count()) await historyButton.click();
  await page.locator(".gov-sessions__item", { hasText: "外地户籍人员人才公寓补贴" }).click();
  await page.waitForTimeout(200);
  check("no-basis answer is explicit", (await page.locator(".gov-answer").textContent()).includes("未找到足够依据，请补充材料或人工核实"));
  if (compact) check("history drawer closes after choosing (compact)", (await page.locator(".gov-qa__history").count()) === 0);
  await page.locator("#gov-qa-input").fill("申请贴息需要哪些材料？");
  await page.getByRole("button", { name: "提问" }).click();
  await page.waitForTimeout(300);
  check("new question gets 未接入 state, not a fabricated answer", (await page.locator(".gov-answer").last().textContent()).includes("未连接政策检索服务"));
  await page.locator("[aria-label='收起依据栏']").click();
  check("evidence panel collapses", (await page.locator(".gov-qa__evidence").count()) === 0);
}
