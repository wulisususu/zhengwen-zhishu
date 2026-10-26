// Real browser, JWT, SQLite and deployed candidate tools. No request interception.
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, mkdirSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { launchBrowser } from './helpers.mjs';
const base=process.env.GOV_E2E_BASE || 'http://127.0.0.1:4319';
const output=resolve(process.env.GOV_E2E_OUTPUT || '../.gov-runtime/full-integration');
const auth=JSON.parse(readFileSync(process.env.GOV_E2E_ACCOUNTS,'utf8'));
mkdirSync(output,{recursive:true});
const browser=await launchBrowser();const contexts=[];const errors=[];let requests=0;
async function login(name){
 const context=await browser.newContext({viewport:{width:1600,height:1100},acceptDownloads:true});contexts.push(context);
 const page=await context.newPage();page.setDefaultTimeout(45000);
 page.on('pageerror',e=>errors.push(String(e)));page.on('request',r=>{if(r.url().includes('/api/v1/gov/'))requests++;});
 await page.goto(base+'/login');await page.getByPlaceholder('请输入账号').fill(name);await page.getByPlaceholder('请输入密码').fill(auth.password);
 await page.getByRole('button',{name:'登录',exact:true}).click();await page.waitForURL(base+'/gov');return page;
}
async function mutate(page,suffix,operation,timeout=60000){
 const pending=page.waitForResponse(r=>r.url().endsWith(suffix)&&['POST','PUT','DELETE'].includes(r.request().method()),{timeout});
 await operation();const response=await pending;assert.equal(response.status(),200,await response.text());const value=await response.json();assert.equal(value.code,0,value.message);return value.data;
}
async function submit(page){await page.getByRole('button',{name:'提交审核',exact:true}).click();return mutate(page,'/submit',()=>page.getByRole('button',{name:'确认提交',exact:true}).click());}
async function download(page,name){
 await page.getByRole('button',{name:'导出',exact:true}).click();const pending=page.waitForEvent('download',{timeout:90000});
 await page.getByRole('button',{name:'导出内部草稿',exact:true}).click();await(await pending).saveAs(join(output,name));
 await page.getByRole('button',{name:'关闭',exact:true}).click();
}
try{
 const admin=await login('stage2_reviewer');await admin.goto(base+'/gov/library');
 await admin.getByText('管理员导入政策',{exact:true}).click();
 await admin.getByLabel('政策原文网址',{exact:true}).fill('https://www.gov.cn/zhengce/zhengceku/202609/P020260930799553380054.pdf');
 await admin.getByLabel('导入政策标题',{exact:true}).fill('艺术发展十五五规划');
 await admin.getByLabel('上传政策文件',{exact:true}).setInputFiles(process.env.GOV_E2E_PDF_SOURCE);
 const imported=await mutate(admin,'/gov/policies/import',()=>admin.getByRole('button',{name:'导入政策',exact:true}).click());
 assert.equal(imported.extraction.parser,'opendataloader_pdf');assert.equal(imported.extraction.page_count,12);assert.equal(imported.policy.verified_status,'unverified');
 await admin.getByText(/PDF 第 1 页/).first().waitFor();await admin.screenshot({path:join(output,'pdf-library.png'),fullPage:true});
 const writer=await login('stage2_writer');await writer.goto(base+'/gov/draft');const title='整体验收通知-'+Date.now();
 await writer.getByLabel('新建文稿标题',{exact:true}).fill(title);
 const created=await mutate(writer,'/gov/documents',()=>writer.getByRole('button',{name:'创建文稿',exact:true}).click());const id=created.id;
 await writer.waitForURL(base+'/gov/draft/'+id);
 await writer.getByRole('button',{name:'添加材料',exact:true}).click();
 const uploaded=writer.waitForResponse(r=>r.url().endsWith('/gov/materials')&&r.request().method()==='POST');
 await writer.getByLabel('上传材料',{exact:true}).setInputFiles({name:'会务要求.txt',mimeType:'text/plain',buffer:Buffer.from('各单位报送会务需求，办公室负责汇总。')});assert.equal((await uploaded).status(),200);
 await mutate(writer,'/materials',()=>writer.getByRole('button',{name:'添加所选（1）',exact:true}).click());
 await writer.getByLabel('生成要求',{exact:true}).fill('仅写一段不超过一百字的通知正文：各单位报送会务需求，办公室负责汇总。不添加日期、数字或政策。');
 const generated=await mutate(writer,'/generate',()=>writer.getByRole('button',{name:'使用模型生成初稿',exact:true}).click(),180000);assert.ok(generated.body.length>5);
 await writer.locator('#gov-field-recipient').fill('各有关单位');await writer.locator('#gov-field-issuer').fill('测试办公室');await writer.locator('#gov-field-undertaker').fill('综合处');
 await writer.getByLabel('发文字号',{exact:true}).fill('测办发〔2026〕8号');await writer.getByLabel('成文日期',{exact:true}).fill('2026-10-26');
 await writer.getByLabel('正文编辑',{exact:true}).fill('一、工作安排\n请各单位认真落实,及时反馈。\n三、责任分工\n综合处负责汇总。');
 await mutate(writer,id,()=>writer.getByRole('button',{name:'保存草稿',exact:true}).click());
 const defective=await mutate(writer,'/check',()=>writer.getByRole('button',{name:'重新审校',exact:true}).click());
 assert.ok(defective.review.summary.critical>0);assert.equal(defective.review.formatCheck.status,'hit');
 const gap=defective.issues.find(i=>defective.review.issueDetails[i.id]?.code==='NUMBERING_GAP');assert.ok(gap?.anchor);
 await writer.locator('article.gov-issue').filter({hasText:gap.title}).first().getByRole('button',{name:'定位',exact:true}).click();
 assert.ok(await writer.locator(`[data-anchor="${gap.anchor}"].is-focus`).count());await writer.screenshot({path:join(output,'defects-and-location.png'),fullPage:true});
 await download(writer,'defective-internal-draft.docx');
 await submit(writer);await admin.goto(base+'/gov/review-center');await admin.getByRole('row').filter({hasText:title}).click();
 assert.equal(await admin.getByRole('button',{name:'审核通过',exact:true}).isDisabled(),true);
 await admin.getByLabel('审核意见',{exact:true}).fill('补全版记、日期并修正序号后重提');
 await mutate(admin,'/return',()=>admin.getByRole('button',{name:'退回修改',exact:true}).click());
 await writer.reload();await writer.getByLabel('正文编辑',{exact:true}).fill('一、工作安排\n请各单位按要求报送会务需求。\n二、责任分工\n综合处负责汇总，办公室负责复核。');
 await writer.getByLabel('成文日期',{exact:true}).fill('2026年10月26日');await writer.getByLabel('印发机关',{exact:true}).fill('测试办公室');await writer.getByLabel('印发日期',{exact:true}).fill('2026年10月26日');
 await writer.getByRole('button',{name:'添加表格',exact:true}).click();await writer.getByLabel('表格1标题',{exact:true}).fill('会务分工');
 await writer.getByLabel('表格1第1行第1列',{exact:true}).fill('会务准备');await writer.getByLabel('表格1第1行第2列',{exact:true}).fill('1');
 const corrected=await mutate(writer,id,()=>writer.getByRole('button',{name:'保存草稿',exact:true}).click());assert.equal(corrected.checkStatus,'not_run');
 await writer.getByRole('button',{name:'添加政策依据',exact:true}).click();const picker=writer.getByRole('dialog',{name:'选择政策依据',exact:true});
 await picker.getByTestId('policy-open-'+imported.policy.id).click();await picker.locator('[data-testid^="select-clause-"]').first().click();
 await writer.getByText('政策条款已保存到文稿。',{exact:true}).waitFor();
 const checked=await mutate(writer,'/check',()=>writer.getByRole('button',{name:'重新审校',exact:true}).click());
 assert.equal(checked.review.summary.critical,0,JSON.stringify(checked.issues));assert.equal(checked.review.gate.canApprove,true);
 await writer.reload();assert.equal(await writer.getByLabel('发文字号',{exact:true}).inputValue(),'测办发〔2026〕8号');
 assert.equal(await writer.getByLabel('表格1第1行第1列',{exact:true}).inputValue(),'会务准备');
 await submit(writer);await admin.reload();await admin.getByRole('row').filter({hasText:title}).click();
 await admin.getByRole('button',{name:'审核通过',exact:true}).click();const approved=await mutate(admin,'/approve',()=>admin.getByRole('button',{name:'确认通过',exact:true}).click());assert.equal(approved.status,'approved');
 await writer.reload();await download(writer,'standard-notice-with-policy.docx');await writer.screenshot({path:join(output,'approved-notice.png'),fullPage:true});
 const other=await login('stage2_other');await other.goto(base+'/gov/draft/'+id);await other.getByText('文稿不存在或无权访问',{exact:true}).waitFor();
 assert.deepEqual(errors,[]);
 const result={passed:true,documentId:id,policyId:imported.policy.id,pdfPages:12,realGovRequests:requests,modelGenerationChars:generated.body.length,defectCount:defective.issues.length,correctedCritical:checked.review.summary.critical,pageErrors:errors,
  workflow:['real-login','PDF-import','PDF-page-provenance','create','upload','real-model-generation','save','dual-layer-review','locate','defective-draft-download','submit','return','correct','table','cite','reload','recheck','resubmit','other-person-approve','DOCX-download','cross-user-denied']};
 writeFileSync(join(output,'result.json'),JSON.stringify(result,null,2));console.log(JSON.stringify(result));
}catch(e){for(let i=0;i<contexts.length;i++)await contexts[i].pages()[0]?.screenshot({path:join(output,`failure-${i}.png`),fullPage:true}).catch(()=>{});throw e;}
finally{await browser.close();}
