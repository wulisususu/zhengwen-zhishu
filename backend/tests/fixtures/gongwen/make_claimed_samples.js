#!/usr/bin/env node
/**
 * 复测 1：gongwen-kit README／源码明确声称能查的写法类错误，每类两种写法，
 * 每份只在 make_samples.js 的基线上埋一处，产物写到 claimed/。
 *
 * 用法：node make_claimed_samples.js [gongwen-kit 目录]
 * 期望命中的规则名写在 claimed/expected.json，供 tests/spike/gongwen_claimed_bench.py 计分。
 */
"use strict";
const fs = require("fs");
const path = require("path");
const { KIT, G, build, writeDoc } = require("./make_samples");
const JSZip = require(path.join(KIT, "node_modules/jszip"));

const OUT = path.join(process.env.OUT_DIR || __dirname, "claimed");
const INTRO = "为规范公文格式，提高办文质量，现就开展公文格式规范培训有关事项通知如下。";
const DUE = "各单位于 2026年10月30日前将参训人员名单报送办公室文书科；培训具体时间、地点另行通知。";
const PEOPLE = "各部门负责公文处理工作的同志，每单位 1 至 2 人。";

// 合计行 = 12 + 8 + 5 = 25，故意写成 26
const totalTable = () => G.table({
  caption: "表1　各部门参训名额",
  head: ["部门", "名额（人）"],
  rows: [["综合处", "12"], ["业务处", "8"], ["财务处", "5"], ["合计", "26"]],
  widths: [3600, 2400],
});

// [文件名, 声称的规则, 期望规则名, build 选项, 埋错位置说明, 后处理]
const CASES = [
  ["c01a_docno_bracket_letterhead", "发文字号用六角括号", "发文字号", { docNo: "示办发【2026】8号" }, "版头发文字号 示办发【2026】8号"],
  ["c01b_docno_bracket_body", "发文字号用六角括号", "发文字号", { subs: [[INTRO, "根据示办发[2026]8号文件精神，" + INTRO]] }, "正文引用 示办发[2026]8号"],
  ["c02a_docno_di", "发文顺序号不加「第」", "发文字号", { docNo: "示办发〔2026〕第8号" }, "版头 示办发〔2026〕第8号"],
  ["c02b_docno_zero", "发文顺序号不编虚位", "发文字号", { docNo: "示办发〔2026〕008号" }, "版头 示办发〔2026〕008号"],
  ["c03a_date_pad_sign", "月日不编虚位", "月日编虚位", { signDate: "2026年10月06日" }, "落款日期 2026年10月06日"],
  ["c03b_date_pad_body", "月日不编虚位", "月日编虚位", { subs: [["2026年10月30日", "2026年09月30日"]] }, "正文 2026年09月30日"],
  ["c04a_date_cn_sign", "成文日期用阿拉伯数字", "中文数字日期", { signDate: "二〇二六年十月二十六日" }, "落款日期 二〇二六年十月二十六日"],
  ["c04b_date_cn_body", "正文日期用阿拉伯数字", "中文数字日期", { subs: [["2026年10月30日", "二〇二六年十月三十日"]] }, "正文 二〇二六年十月三十日"],
  ["c05a_half_colon", "中文里的半角标点", "中文里的半角标点", { subs: [["通知如下。", "通知如下:"]] }, "正文 通知如下:（半角冒号）"],
  ["c05b_half_comma", "中文里的半角标点", "中文里的半角标点", { subs: [["提高办文质量，", "提高办文质量,"]] }, "正文 提高办文质量,（半角逗号）"],
  ["c06a_half_paren", "中文用全角括号", "半角括号", { subs: [["办公室文书科", "办公室文书科(208室)"]] }, "正文 文书科(208室)"],
  ["c06b_half_paren_word", "中文用全角括号", "半角括号", { subs: [["各部门负责", "各部门(单位)负责"]] }, "正文 各部门(单位)"],
  ["c07a_yixingci_chouhua", "异形词（GF 1001-2001）", "异形词", { subs: [[PEOPLE, PEOPLE + "请各单位认真筹画参训安排。"]] }, "正文 筹画"],
  ["c07b_yixingci_danxin", "异形词（GF 1001-2001）", "异形词", { subs: [[PEOPLE, PEOPLE + "不必耽心名额不足。"]] }, "正文 耽心"],
  ["c08a_total_declared", "表格合计与分项", "合计不符", { extra: totalTable() }, "工具自带表格构件，合计 26 ≠ 25"],
  ["c08b_total_handmade", "表格合计与分项", "合计不符", { extra: totalTable() }, "同上，但去掉 tblHeader（模拟手工/python-docx 表格）", "stripTblHeader"],
  ["c09a_fullwidth_digit", "阿拉伯数字用半角", "全角数字", { subs: [["每单位 1 至 2 人", "每单位 １ 至 ２ 人"]] }, "正文 １ 至 ２"],
  ["c09b_fullwidth_year", "阿拉伯数字用半角", "全角数字", { subs: [["2026年10月30日", "２０２６年10月30日"]] }, "正文 ２０２６年"],
  ["c10a_dotted_level", "公文不用 1.1 式层次", "公文层次序数", { subs: [["（一）讲解", "1.1 讲解"]] }, "层次 1.1 讲解…"],
  ["c10b_dotted_level_sub", "公文不用 1.1 式层次", "公文层次序数", { subs: [[DUE, "3.1 名单报送。" + DUE]] }, "层次 3.1 名单报送"],
];

async function stripTblHeader(file) {
  const zip = await JSZip.loadAsync(fs.readFileSync(file));
  const xml = await zip.file("word/document.xml").async("string");
  zip.file("word/document.xml", xml.replace(/<w:tblHeader\/>/g, "").replace(/<w:tblHeader [^>]*\/>/g, ""));
  fs.writeFileSync(file, await zip.generateAsync({ type: "nodebuffer", compression: "DEFLATE" }));
}

(async () => {
  fs.mkdirSync(OUT, { recursive: true });
  const expected = {};
  for (const [name, claim, rule, opts, where, post] of CASES) {
    const file = path.join(OUT, name + ".docx");
    await writeDoc(build(opts), file, { strict: false, quiet: true });
    if (post === "stripTblHeader") await stripTblHeader(file);
    expected[name + ".docx"] = { claim, rule, where };
  }
  fs.writeFileSync(path.join(OUT, "expected.json"), JSON.stringify(expected, null, 1) + "\n");
  process.exitCode = 0;
})();
