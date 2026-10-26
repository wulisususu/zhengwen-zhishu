#!/usr/bin/env node
/**
 * 生成 gongwen-kit 验证用的「必错样本」与对照样本。
 *
 * 用法：node make_samples.js [gongwen-kit 目录]
 *       目录默认 backend/third_party/gongwen-kit。产物写在本脚本所在目录。
 *
 * 方法：先出一份「基线」通知（应当零命中），每份必错样本只在基线上改一处，
 * 这样命中与否只取决于埋进去的那一个错，不会被版心等无关问题「碰巧」命中。
 * 层次序数一律手打（一、二、三），不用 h1() 自动编号——自动编号不可能跳号，
 * 真实来稿与本项目 markdown_to_docx 的产物也都是手打编号。
 * 各样本埋了什么错见同目录 README.md。
 */
"use strict";
const path = require("path");

const KIT = path.resolve(process.argv[2] || path.join(__dirname, "../../../third_party/gongwen-kit"));
const G = require(path.join(KIT, "lib/gongwen-core")).form("wen");
const { Document } = G.require_docx();
const { externalStyles, numbering, sectionProps, writeDoc, letterhead, title, zhusong, luokuan, banji } = G;

const AGENCY = "示例单位办公室";
const DATE = "2026年10月26日";

function build({
  letterheadOn = true,
  countSentence = "本次培训共 3 项任务：",
  thirdHeading = "三、有关要求",
  signDate = DATE,
  banjiOn = true,
  docNo = { dept: "示办发", year: 2026, seq: 8 },
  subs = [],        // [[原文, 替换]]：对正文段落逐个做字面替换，用来埋写法类错误
  extra = [],       // 插在「（三）」段之后的构件（如表格）
} = {}) {
  const p = (text) => G.p(subs.reduce((t, [from, to]) => t.split(from).join(to), text));
  const children = [
    ...(letterheadOn ? letterhead({ agency: AGENCY, docNo }) : []),
    ...title(["示例单位办公室关于开展公文格式", "规范培训工作的通知"]),
    zhusong("各部门、各直属单位"),
    p("为规范公文格式，提高办文质量，现就开展公文格式规范培训有关事项通知如下。"),
    p("一、培训任务"),
    p(countSentence),
    p("（一）讲解公文版心与行字数要求"),
    p("（二）讲解层次序数与成文日期写法"),
    p("（三）组织常见格式差错案例研讨"),
    ...extra,
    p("二、参训人员"),
    p("各部门负责公文处理工作的同志，每单位 1 至 2 人。"),
    p(thirdHeading),
    p("各单位于 2026年10月30日前将参训人员名单报送办公室文书科；培训具体时间、地点另行通知。"),
    p("联系人：×××，联系电话：×××-××××××××。"),
    ...luokuan({ unit: AGENCY, date: signDate }),
    ...(banjiOn ? banji({ copyTo: ["示例单位领导班子成员"], issuer: AGENCY, date: DATE }) : []),
  ];
  return new Document({
    creator: "innet-agent-ai-box fixtures",
    title: "示例单位办公室关于开展公文格式规范培训工作的通知",
    features: { updateFields: true },
    evenAndOddHeaderAndFooters: true,
    externalStyles: externalStyles(),
    numbering,
    sections: [{ ...sectionProps(), children }],
  });
}

const SAMPLES = {
  "baseline_control.docx": {},
  "bad_01_count_mismatch.docx": { countSentence: "本次培训共 5 项任务：" },
  "bad_02_heading_gap.docx": { thirdHeading: "四、有关要求" },
  "bad_03_no_letterhead.docx": { letterheadOn: false },
  "bad_04_date_iso.docx": { signDate: "2026-10-26" },
  "bad_05_no_banji.docx": { banjiOn: false },
  // 补充探针，不计入 5 份：同一个计数错，换成 check-num 认得的「以下五项」句式
  "probe_01b_count_yixia.docx": { countSentence: "本次培训包括以下五项任务：" },
};

module.exports = { KIT, G, build, writeDoc };

if (require.main === module) (async () => {
  for (const [name, opts] of Object.entries(SAMPLES)) {
    // strict:false —— 必错样本本来就该命中，不让 writeDoc 因此置非零退出码
    await writeDoc(build(opts), path.join(process.env.OUT_DIR || __dirname, name), { strict: false, quiet: true });
  }
  process.exitCode = 0;
})();
