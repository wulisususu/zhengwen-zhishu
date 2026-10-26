// Real browser + real JWT + real cloud model API; no request interception.
// Policy QA (/policy) and drafting (/gongwen) on top of the existing policy library and document flow:
//   reviewer imports a policy (unverified) → verifies it → drafter asks, the cloud model answers with
//   citations → citations carried into /gongwen → cloud-generated notice saved into /gov/draft/:id →
//   save / submit / return / resubmit / approval by the other role → marked internal DOCX;
//   a 请示 is saved and exported from /gongwen as a marked internal draft.
// The backend must run with model.mode=cloud_allowed and EXTERNAL_MODEL_* configured, on fresh isolated data
// (imports are keyed by text hash: a rerun on the same policy.db gets the already-verified policy back).
import assert from "node:assert/strict";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import JSZip from "jszip";
import { enterAsRole, launchBrowser } from "./helpers.mjs";

const base = process.env.GOV_E2E_BASE || "http://127.0.0.1:4318";
const output = resolve(process.env.GOV_E2E_OUTPUT || "../.gov-runtime/drafting-policy");
mkdirSync(output, { recursive: true });
const MODEL_TIMEOUT = 120000;

const POLICY = `示例市小微企业首次贷款贴息管理办法
第一条 为支持小微企业发展，规范首次贷款贴息管理，制定本办法。
第二条 本办法适用于本市行政区域内依法登记注册的小微企业。
第三条 申请贴息应当同时具备下列条件：在本市依法登记注册并正常经营满一年；近两年内无严重失信记录；贷款用于生产经营。
第四条 申请材料包括营业执照、贷款合同、还款凭证和银行出具的利息清单。
第五条 贴息按实际支付利息的百分之五十给予补贴，单户年度上限二十万元。
第六条 申请人应当在贷款发放后六个月内提出申请，逾期不再受理。`;

const browser = await launchBrowser();
const contexts = [];
const errors = [];
let requests = 0;

async function enter(role) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  contexts.push(context);
  const page = await context.newPage();
  page.setDefaultTimeout(30000);
  page.on("pageerror", (err) => errors.push(String(err)));
  page.on("request", (req) => { if (req.url().includes("/api/v1/")) requests++; });
  await enterAsRole(page, base, role);
  return page;
}

async function okResponse(page, match, run, timeout = 30000) {
  const pending = page.waitForResponse((res) => match(res.url()) && ["POST", "PUT"].includes(res.request().method()), { timeout });
  await run();
  const response = await pending;
  assert.equal(response.status(), 200, `${response.url()}: ${await response.text()}`);
  const body = await response.json().catch(() => ({}));
  if ("code" in body) assert.equal(body.code, 0, JSON.stringify(body));
  return body.data;
}

async function headerText(download, name) {
  const file = join(output, name);
  await download.saveAs(file);
  const zip = await JSZip.loadAsync(readFileSync(file));
  const headers = await Promise.all(Object.keys(zip.files).filter((n) => /^word\/header\d*\.xml$/.test(n)).map((n) => zip.file(n).async("string")));
  assert.ok(headers.length > 0, `${name}: no headers`);
  return headers.join("\n");
}

async function api(page, path, body) {
  return page.evaluate(async ({ path, body }) => {
    const token = JSON.parse(localStorage.getItem("mqw-session") || "{}").token;
    const res = await fetch("/api/v1" + path, { method: "POST", headers: { "Content-Type": "application/json", Authorization: "Bearer " + token }, body: JSON.stringify(body) });
    return { status: res.status, body: await res.json() };
  }, { path, body });
}

try {
  // ---------- 1. reviewer imports a policy: unverified until a human verifies it ----------
  const reviewer = await enter("reviewer");
  await reviewer.goto(base + "/policy");
  await reviewer.getByRole("button", { name: "导入政策" }).click();
  await reviewer.getByRole("button", { name: "粘贴正文", exact: true }).click();
  await reviewer.getByPlaceholder("把政策正文整段粘贴到这里（含「第一条 第二条…」或「一、二、」编号）").fill(POLICY);
  await reviewer.getByPlaceholder("政策标题（留空自动提取）").fill("示例市小微企业首次贷款贴息管理办法");
  const imported = await okResponse(reviewer, (u) => u.endsWith("/api/v1/gov/policies/import"),
    () => reviewer.getByRole("button", { name: "导入（待核实）" }).click());
  assert.equal(imported.policy.verified_status, "unverified");
  await reviewer.getByText("状态：待核实", { exact: false }).waitFor();
  const verified = await api(reviewer, `/gov/policies/${imported.policy.id}/verify`, { status: "current", status_note: "联调核验", effective_date: "2020-01-01" });
  assert.equal(verified.status, 200); assert.equal(verified.body.code, 0, JSON.stringify(verified.body));

  // ---------- 2. drafter asks; the cloud model answers from the verified policy ----------
  const drafter = await enter("drafter");
  await drafter.goto(base + "/policy");
  assert.equal(await drafter.getByRole("button", { name: "导入政策" }).count(), 0, "drafter must not see import");
  await drafter.getByPlaceholder("输入政策问题，例如：小微企业的贴息比例和上限是多少").fill("申请首次贷款贴息需要具备哪些条件");
  const stream = drafter.waitForResponse((r) => r.url().endsWith("/api/v1/policy/qa/stream"), { timeout: MODEL_TIMEOUT });
  await drafter.locator(".gov-send").click();
  const qaBody = await (await stream).text();
  const final = JSON.parse(qaBody.split("\n").filter((l) => l.includes('"type": "final"')).pop().slice(5)).data;
  assert.equal(final.status, "answered", JSON.stringify(final).slice(0, 400));
  assert.ok(final.citations.length && final.citations.every((c) => c.citation_id.startsWith("clause:")));
  await drafter.getByRole("button", { name: "加入公文起草依据" }).click({ timeout: MODEL_TIMEOUT });
  await drafter.waitForURL(base + "/gongwen");
  await drafter.getByText(`起草依据 ${final.citations.length} 条`, { exact: false }).waitFor();

  // ---------- 3. cloud-generated notice saved into the existing document flow ----------
  await drafter.getByRole("button", { name: "通知", exact: true }).click();
  await drafter.getByPlaceholder("如：加强政务服务中心窗口作风建设").fill("做好小微企业首次贷款贴息申报工作");
  await drafter.getByPlaceholder("各县（市、区）政务服务管理局").fill("各区金融工作部门");
  await drafter.getByPlaceholder("XX市政务服务管理局").fill("示例市地方金融管理局");
  const drafted = await okResponse(drafter, (u) => u.endsWith("/api/v1/gongwen/draft"),
    () => drafter.getByRole("button", { name: /生成正文/ }).click(), MODEL_TIMEOUT);
  assert.notEqual(drafted.meta.generated_by, "template", "cloud model did not answer: " + drafted.meta.error);
  const created = await okResponse(drafter, (u) => u.endsWith("/api/v1/gov/documents"),
    () => drafter.getByRole("button", { name: "保存并进入审校" }).click());
  assert.equal(created.docType, "notice");
  assert.deepEqual(created.citationIds, final.citations.map((c) => c.citation_id));
  await drafter.waitForURL(base + `/gov/draft/${created.id}`);
  assert.ok((await drafter.getByLabel("正文编辑", { exact: true }).inputValue()).length > 100);
  await drafter.getByRole("complementary", { name: "起草要素与材料" }).getByText("示例市小微企业首次贷款贴息管理办法", { exact: false }).first().waitFor();
  await drafter.screenshot({ path: join(output, "notice-from-gongwen.png"), fullPage: true });

  // ---------- 4. save / submit / return / resubmit / approval by the other role ----------
  await drafter.getByLabel("正文编辑", { exact: true }).fill("一、申报范围\n本市依法登记注册的小微企业首次取得的经营性贷款。\n二、申报要求\n各区金融工作部门于规定时间内汇总报送。");
  await drafter.getByLabel("发文字号", { exact: true }).fill("示金发〔2026〕5号");
  await drafter.getByLabel("成文日期", { exact: true }).fill("2026年10月26日");
  await drafter.getByLabel("印发机关", { exact: true }).fill("示例市地方金融管理局");
  await drafter.getByLabel("印发日期", { exact: true }).fill("2026年10月26日");
  await okResponse(drafter, (u) => u.endsWith(`/api/v1/gov/documents/${created.id}`), () => drafter.getByRole("button", { name: "保存草稿", exact: true }).click());
  const submit = () => okResponse(drafter, (u) => u.endsWith("/submit"), async () => {
    await drafter.getByRole("button", { name: "提交审核", exact: true }).click();
    await drafter.getByRole("button", { name: "确认提交", exact: true }).click();
  });
  await submit();
  await reviewer.goto(base + "/gov/review-center");
  await reviewer.getByRole("row").filter({ hasText: created.title }).click();
  await reviewer.getByLabel("审核意见", { exact: true }).fill("请补充申报截止时间");
  await okResponse(reviewer, (u) => u.endsWith("/return"), () => reviewer.getByRole("button", { name: "退回修改", exact: true }).click());
  await drafter.reload();
  await drafter.getByLabel("正文编辑", { exact: true }).fill("一、申报范围\n本市依法登记注册的小微企业首次取得的经营性贷款。\n二、申报要求\n各区金融工作部门于2026年11月30日前汇总报送。");
  await okResponse(drafter, (u) => u.endsWith(`/api/v1/gov/documents/${created.id}`), () => drafter.getByRole("button", { name: "保存草稿", exact: true }).click());
  await submit();
  await reviewer.reload();
  await reviewer.getByRole("row").filter({ hasText: created.title }).click();
  await reviewer.getByRole("button", { name: "审核通过", exact: true }).click();
  const approved = await okResponse(reviewer, (u) => u.endsWith("/approve"), () => reviewer.getByRole("button", { name: "确认通过", exact: true }).click(), MODEL_TIMEOUT);
  assert.equal(approved.status, "approved");

  await drafter.reload();
  await drafter.getByRole("button", { name: "导出", exact: true }).click();
  const noticeDownload = drafter.waitForEvent("download");
  await drafter.getByRole("button", { name: "导出内部草稿", exact: true }).click();
  assert.match(await headerText(await noticeDownload, "notice-internal.docx"), /内部草稿/);

  // ---------- 5. a 请示 saved and exported from /gongwen as a marked internal draft ----------
  await drafter.goto(base + "/gongwen");
  await drafter.getByRole("button", { name: "请示", exact: true }).click();
  await drafter.getByPlaceholder("如：加强政务服务中心窗口作风建设").fill("调整小微企业贴息资金预算");
  await drafter.getByPlaceholder("各县（市、区）政务服务管理局").fill("示例市财政局");
  await drafter.getByPlaceholder("XX市政务服务管理局").fill("示例市地方金融管理局");
  const request = await okResponse(drafter, (u) => u.endsWith("/api/v1/gongwen/draft"),
    () => drafter.getByRole("button", { name: /生成正文/ }).click(), MODEL_TIMEOUT);
  assert.equal(request.ir.doc_type, "请示");
  const savedRequest = await okResponse(drafter, (u) => u.endsWith("/api/v1/gov/documents"), () => drafter.getByRole("button", { name: "保存为文稿" }).click());
  assert.equal(savedRequest.docType, "request");
  await drafter.getByText("已保存为内部草稿", { exact: false }).waitFor();
  const requestDownload = drafter.waitForEvent("download");
  await drafter.getByRole("button", { name: "导出内部草稿" }).click();
  assert.match(await headerText(await requestDownload, "request-internal.docx"), /未审核 · 内部草稿/);
  await drafter.screenshot({ path: join(output, "request-gongwen.png"), fullPage: true });

  assert.deepEqual(errors, []);
  const result = { passed: true, policyId: imported.policy.id, noticeId: created.id, requestId: savedRequest.id, realApiRequests: requests,
    qaGeneratedBy: final.meta.generated_by, noticeGeneratedBy: drafted.meta.generated_by, requestGeneratedBy: request.meta.generated_by,
    citations: final.citations.map((c) => c.citation_id), pageErrors: errors,
    workflow: ["role-entry", "reviewer-import-unverified", "verify", "cloud-qa-with-citations", "citations-to-gongwen", "cloud-notice-draft",
      "save-into-gov-draft", "submit", "return", "resubmit", "other-role-approve", "marked-internal-docx", "request-save-and-marked-export"] };
  writeFileSync(join(output, "result.json"), JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result));
} catch (error) {
  for (let i = 0; i < contexts.length; i++) {
    for (const page of contexts[i].pages()) await page.screenshot({ path: join(output, `failure-${i}.png`), fullPage: true }).catch(() => {});
  }
  throw error;
} finally {
  await browser.close();
}
