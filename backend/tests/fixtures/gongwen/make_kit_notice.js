#!/usr/bin/env node
/**
 * 复测 3：用 gongwen-kit 的标准构件出一份通知，正文与 make_innet_samples.py 的
 * MARKDOWN 逐字相同（含名额表），写到 innet/kit_notice.docx，用于与 python-docx 产物对比。
 * 层次标题按上游 templates/notice.js 用 h1()（自动编号一、二、三，黑体）。
 * 区别只在 gongwen-kit 必需的公文要素：版头（发文机关标志、发文字号）和版记，
 * InNet_box 两条链路都没有这两项的输入，见 docs/spike/gongwen-kit.md 复测 3。
 *
 * 用法：node make_kit_notice.js [gongwen-kit 目录]
 */
"use strict";
const path = require("path");
const { G, writeDoc } = require("./make_samples");
const { Document } = G.require_docx();
const { externalStyles, numbering, sectionProps, letterhead, title, zhusong, p, h1, luokuan, banji, table } = G;

const AGENCY = "示例单位办公室";
const DATE = "2026年10月26日";
const OUT = path.join(process.env.OUT_DIR || __dirname, "innet", "kit_notice.docx");

const doc = new Document({
  creator: "innet-agent-ai-box fixtures",
  title: "示例单位办公室关于开展公文格式规范培训工作的通知",
  features: { updateFields: true },
  evenAndOddHeaderAndFooters: true,
  externalStyles: externalStyles(),
  numbering,
  sections: [{
    ...sectionProps(),
    children: [
      ...letterhead({ agency: AGENCY, docNo: { dept: "示办发", year: 2026, seq: 8 } }),
      ...title(["示例单位办公室关于开展公文格式", "规范培训工作的通知"]),
      zhusong("各部门、各直属单位"),
      p("为规范公文格式，提高办文质量，现就开展公文格式规范培训有关事项通知如下。"),
      h1("培训任务"),
      p("本次培训共 3 项任务："),
      p("1. 讲解公文版心与行字数要求"),
      p("2. 讲解层次序数与成文日期写法"),
      p("3. 组织常见格式差错案例研讨"),
      h1("参训人员"),
      p("各部门负责公文处理工作的同志，名额分配如下："),
      ...table({
        caption: "表1　参训名额",
        head: ["部门", "名额（人）"],
        rows: [["综合处", "12"], ["业务处", "8"], ["财务处", "5"], ["合计", "25"]],
        widths: [3600, 2400],
      }),
      h1("有关要求"),
      p("各单位于 2026年10月30日前将参训人员名单报送办公室文书科；培训具体时间、地点另行通知。"),
      p("联系人：×××，联系电话：×××-××××××××。"),
      ...luokuan({ unit: AGENCY, date: DATE }),
      ...banji({ copyTo: ["示例单位领导班子成员"], issuer: AGENCY, date: DATE }),
    ],
  }],
});

writeDoc(doc, OUT, { strict: true, quiet: true });
