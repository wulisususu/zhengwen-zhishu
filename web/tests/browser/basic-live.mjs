// Real browser + real JWT + real HTTP. No route interception or fake token.
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { launchBrowser } from "./helpers.mjs";

const base = process.env.GOV_E2E_BASE || "http://127.0.0.1:4318";
const output = resolve(process.env.GOV_E2E_OUTPUT || "../.gov-runtime/evidence");
const credentials = JSON.parse(readFileSync(process.env.GOV_E2E_ACCOUNTS || "../.gov-runtime/accounts.json", "utf8"));
mkdirSync(output, { recursive: true });
const browser = await launchBrowser();
const contexts = [];
const errors = [];
let requestCount = 0;
async function login(username) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  contexts.push(context);
  const page = await context.newPage();
  page.setDefaultTimeout(15000);
  page.on("pageerror", (err) => errors.push(String(err)));
  page.on("request", (req) => { if (req.url().includes("/api/v1/gov/")) requestCount++; });
  await page.goto(base + "/login");
  await page.getByPlaceholder("请输入账号").fill(username);
  await page.getByPlaceholder("请输入密码").fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await page.waitForURL(base + "/gov");
  return page;
}
async function mutation(page, suffix, run) {
  const promise = page.waitForResponse((res) => res.url().includes("/api/v1/gov/documents") && res.url().endsWith(suffix) && ["POST", "PUT", "DELETE"].includes(res.request().method()));
  await run();
  const response = await promise;
  assert.equal(response.status(), 200, `${suffix}: ${await response.text()}`);
  return (await response.json()).data;
}
async function submit(page) {
  await page.getByRole("button", { name: "提交审核", exact: true }).click();
  return mutation(page, "/submit", () => page.getByRole("button", { name: "确认提交", exact: true }).click());
}

try {
  const writer = await login("gov_writer");
  await writer.goto(base + "/gov/draft");
  const title = `基础联调通知-${Date.now()}`;
  await writer.getByLabel("新建文稿标题", { exact: true }).fill(title);
  const created = await mutation(writer, "/documents", () => writer.getByRole("button", { name: "创建文稿", exact: true }).click());
  const path = `/gov/draft/${created.id}`;
  await writer.waitForURL(base + path);
  await writer.getByLabel("正文编辑", { exact: true }).fill("一、工作安排\n请各单位在本周内完成材料核对。\n二、报送要求\n不确定的信息须人工确认。");
  await writer.locator("#gov-field-recipient").fill("各单位");
  await writer.locator("#gov-field-issuer").fill("联调测试办公室");
  await writer.locator("#gov-field-undertaker").fill("综合处");
  await mutation(writer, created.id, () => writer.getByRole("button", { name: "保存草稿", exact: true }).click());
  await writer.reload();
  assert.match(await writer.getByLabel("正文编辑", { exact: true }).inputValue(), /材料核对/);
  await writer.getByRole("button", { name: "添加材料", exact: true }).click();
  const upload = writer.waitForResponse((res) => res.url().endsWith("/api/v1/gov/materials") && res.request().method() === "POST");
  await writer.getByLabel("上传材料", { exact: true }).setInputFiles({ name: "联调材料.txt", mimeType: "text/plain", buffer: Buffer.from("测试材料：本周完成材料核对。") });
  assert.equal((await upload).status(), 200);
  await mutation(writer, "/materials", () => writer.getByRole("button", { name: "添加所选（1）", exact: true }).click());
  await writer.screenshot({ path: join(output, "draft.png"), fullPage: true });
  await submit(writer);
  await writer.getByText("文稿审核中，编辑已锁定", { exact: false }).waitFor();
  assert.equal(await writer.getByLabel("正文编辑", { exact: true }).isDisabled(), true);

  const reviewer = await login("gov_reviewer");
  await reviewer.goto(base + "/gov/review-center");
  await reviewer.getByRole("row").filter({ hasText: title }).click();
  await reviewer.getByLabel("审核意见", { exact: true }).fill("请补充承办要求");
  await mutation(reviewer, "/return", () => reviewer.getByRole("button", { name: "退回修改", exact: true }).click());

  await writer.reload();
  await writer.getByLabel("正文编辑", { exact: true }).fill("一、工作安排\n请各单位核对材料。\n二、承办要求\n综合处负责汇总。");
  await mutation(writer, created.id, () => writer.getByRole("button", { name: "保存草稿", exact: true }).click());
  await submit(writer);
  await reviewer.reload();
  await reviewer.getByRole("row").filter({ hasText: title }).click();
  await reviewer.getByRole("button", { name: "审核通过", exact: true }).click();
  await mutation(reviewer, "/approve", () => reviewer.getByRole("button", { name: "确认通过", exact: true }).click());
  await reviewer.screenshot({ path: join(output, "review.png"), fullPage: true });

  await writer.reload();
  await writer.getByRole("button", { name: "导出", exact: true }).click();
  const event = writer.waitForEvent("download");
  await writer.getByRole("button", { name: "导出内部草稿", exact: true }).click();
  const download = await event;
  const docx = join(output, "internal-draft.docx");
  await download.saveAs(docx);
  assert.ok(statSync(docx).size > 1000);

  const other = await login("gov_other");
  await other.goto(base + path);
  await other.getByText("文稿不存在或无权访问", { exact: true }).waitFor();
  assert.equal(await other.getByLabel("正文编辑", { exact: true }).count(), 0);
  assert.ok(requestCount >= 15);
  assert.deepEqual(errors, []);
  const result = { passed: true, documentId: created.id, realGovRequests: requestCount, pageErrors: errors, workflow: ["real-login", "create", "save", "reload", "upload", "submit", "return", "revise", "resubmit", "approve", "docx-download", "cross-user-denied"] };
  writeFileSync(join(output, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  for (let i = 0; i < contexts.length; i++) {
    const page = contexts[i].pages()[0];
    if (page) await page.screenshot({ path: join(output, `failure-${i}.png`), fullPage: true }).catch(() => {});
  }
  throw error;
} finally {
  await browser.close();
}
