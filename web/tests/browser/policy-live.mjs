// Real browser, real JWT and real policy storage; no API interception.
// No login page: identities enter through /entry (审核人 maintains the library, 起草人 cites it).
import assert from "node:assert/strict";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { enterAsRole, launchBrowser } from "./helpers.mjs";
const base = process.env.GOV_E2E_BASE || "http://127.0.0.1:4318";
const output = resolve(process.env.GOV_E2E_OUTPUT || "../.gov-runtime/policy-evidence");
const source = process.env.GOV_E2E_POLICY_SOURCE;
assert.ok(source, "GOV_E2E_POLICY_SOURCE must be an actual official HTML document");
mkdirSync(output, { recursive: true });
const browser = await launchBrowser(); const contexts = []; const errors = [];
async function enter(role) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  contexts.push(context); const page = await context.newPage(); page.setDefaultTimeout(20000);
  page.on("pageerror", error => errors.push(String(error)));
  await enterAsRole(page, base, role);
  return page;
}
try {
  const admin = await enter("reviewer"); await admin.goto(base + "/gov/library");
  await admin.getByText("管理员导入政策", { exact: true }).click();
  await admin.getByLabel("政策原文网址", { exact: true }).fill("https://www.gov.cn/zhengce/content/202506/content_7026294.htm");
  await admin.getByLabel("导入政策标题", { exact: true }).fill("政务数据共享条例");
  await admin.getByLabel("上传政策文件", { exact: true }).setInputFiles(source);
  const importing = admin.waitForResponse(r => r.url().endsWith("/gov/policies/import") && r.request().method() === "POST");
  await admin.getByRole("button", { name: "导入政策", exact: true }).click();
  const imported = await (await importing).json(); assert.equal(imported.code, 0, imported.message);
  const policyId = imported.data.policy.id; assert.equal(imported.data.policy.verified_status, "unverified");
  const writer = await enter("drafter"); await writer.goto(base + "/gov/draft");
  await writer.getByLabel("新建文稿标题", { exact: true }).fill("政策引用验收通知-" + Date.now());
  const creating = writer.waitForResponse(r => r.url().endsWith("/gov/documents") && r.request().method() === "POST");
  await writer.getByRole("button", { name: "创建文稿", exact: true }).click();
  const doc = (await (await creating).json()).data; await writer.waitForURL(base + "/gov/draft/" + doc.id);
  await writer.getByRole("button", { name: "添加政策依据", exact: true }).click();
  const dialog = writer.getByRole("dialog", { name: "选择政策依据", exact: true });
  await dialog.getByLabel("政策检索词", { exact: true }).fill("政务数据");
  await dialog.getByLabel("条款包含未核验", { exact: true }).check();
  const searching = writer.waitForResponse(r => r.url().endsWith("/gov/policies/search"));
  await dialog.getByRole("button", { name: "搜索政策", exact: true }).click();
  const found = (await (await searching).json()).data; assert.ok(found.hits.length > 0);
  const opening = writer.waitForResponse(r => r.url().endsWith(`/gov/policies/${policyId}`));
  await dialog.locator(`[data-testid="policy-open-${policyId}"]`).click();
  const detail = (await (await opening).json()).data;
  const clause = detail.clauses.find(c => c.content.startsWith("第一条")); assert.ok(clause);
  const attaching = writer.waitForResponse(r => r.url().endsWith(`/documents/${doc.id}/citations`));
  await dialog.locator(`[data-testid="select-clause-${clause.id}"]`).click();
  const attached = (await (await attaching).json()).data; assert.equal(attached.policyRefs[0].sourceUrl, detail.policy.url);
  assert.equal(attached.policyRefs[0].status, "unverified");
  await writer.reload();
  await writer.getByRole("button", { name: "查看条款与来源", exact: true }).waitFor();
  await writer.getByLabel("正文编辑", { exact: true }).fill("一、工作安排\n请依法开展政务数据共享。政策有效性仍须人工核验。");
  const saving = writer.waitForResponse(r => r.url().endsWith(`/documents/${doc.id}`) && r.request().method() === "PUT");
  await writer.getByRole("button", { name: "保存草稿", exact: true }).click();
  assert.equal((await (await saving).json()).data.policyRefs.length, 1);
  await writer.getByRole("button", { name: "导出", exact: true }).click();
  const downloading = writer.waitForEvent("download");
  await writer.getByRole("button", { name: "导出内部草稿", exact: true }).click();
  await (await downloading).saveAs(join(output, "policy-reference-draft.docx"));
  await writer.getByRole("button", { name: "关闭", exact: true }).click().catch(() => {});
  await writer.screenshot({ path: join(output, "policy-reference-saved.png"), fullPage: true });
  await admin.screenshot({ path: join(output, "policy-library.png"), fullPage: true });
  assert.deepEqual(errors, []);
  const result = { passed: true, policyId, clauseId: clause.id, documentId: doc.id, hits: found.hits.length,
    policyStatus: "unverified", sourceUrl: detail.policy.url, durableReference: true, pageErrors: errors };
  writeFileSync(join(output, "result.json"), JSON.stringify(result, null, 2)); console.log(JSON.stringify(result));
} catch (error) {
  for (let i = 0; i < contexts.length; i++) await contexts[i].pages()[0]?.screenshot({ path: join(output, `failure-${i}.png`), fullPage: true }).catch(() => {});
  throw error;
} finally { await browser.close(); }
