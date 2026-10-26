#!/usr/bin/env node
/**
 * Fixed bridge: validated component spec (JSON on stdin) → 通知 DOCX via gongwen-kit.
 *
 *   node render_notice.js --kit <gongwen-kit dir> --out <file.docx>  < spec.json
 *
 * The kit directory and output path come from the backend configuration, never
 * from the request. The spec is data only: every component `type` maps to one
 * fixed gongwen-kit call below, every value is checked for type and length, and
 * unknown types or keys are rejected. Nothing from the spec is evaluated or required.
 *
 * stdout: exactly one JSON line.
 *   {"ok":true,"out":…,"bytes":…,"toolVersion":…,"components":N}          exit 0
 *   {"ok":false,"code":"SPEC_INVALID"|"KIT_REJECTED","message":…}          exit 3
 *   {"ok":false,"code":"RENDER_FAILED","message":…}                        exit 2
 */
"use strict";
const fs = require("fs");
const path = require("path");

const MAX_STDIN = 2 * 1024 * 1024;
const MAX_TEXT = 5000;
const SCHEMA = {
  letterhead: { agency: "short", docNo: "short" },
  title: { lines: "lines" },
  zhusong: { text: "text" },
  p: { text: "text" },
  h1: { text: "text" }, h2: { text: "text" }, h3: { text: "text" }, h4: { text: "text" },
  table: { caption: "short?", head: "cells", rows: "rows", widths: "widths" },
  fujian: { items: "lines" },
  luokuan: { unit: "short", date: "short" },
  fuzhu: { text: "text" },
  banji: { copyTo: "lines?", issuer: "short", date: "short" },
};

class Rejected extends Error {
  constructor(code, message) { super(message); this.code = code; }
}

function emit(obj, exitCode) {
  process.stdout.write(JSON.stringify(obj) + "\n");
  process.exitCode = exitCode;
}

function arg(name) {
  const i = process.argv.indexOf(name);
  if (i < 0 || !process.argv[i + 1]) throw new Rejected("SPEC_INVALID", `缺少参数 ${name}`);
  return process.argv[i + 1];
}

const isStr = (v, max) => typeof v === "string" && v.length <= max && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(v);
const strList = (v, maxItems, maxLen) => Array.isArray(v) && v.length <= maxItems && v.every((s) => isStr(s, maxLen));

function checkValue(kind, v) {
  switch (kind) {
    case "text": return isStr(v, MAX_TEXT);
    case "short": return isStr(v, 200) && v.trim().length > 0;
    case "short?": return isStr(v, 200);
    case "lines": return strList(v, 20, 200) && v.length > 0;
    case "lines?": return strList(v, 20, 200);
    case "cells": return strList(v, 8, 40) && v.length > 0;
    case "rows": return Array.isArray(v) && v.length > 0 && v.length <= 200 && v.every((r) => strList(r, 8, 200));
    case "widths": return Array.isArray(v) && v.length <= 8 && v.every((n) => Number.isInteger(n) && n >= 300 && n <= 9000)
      && v.reduce((a, b) => a + b, 0) <= 8844;
    default: return false;
  }
}

function validate(spec) {
  if (!spec || typeof spec !== "object" || Array.isArray(spec)) throw new Rejected("SPEC_INVALID", "spec 必须是对象");
  if (spec.version !== 1 || spec.docType !== "notice") throw new Rejected("SPEC_INVALID", "只支持 version 1 的 notice");
  if (!isStr(spec.title, 200)) throw new Rejected("SPEC_INVALID", "title 无效");
  if (spec.draftMark !== null && spec.draftMark !== undefined && !isStr(spec.draftMark, 60)) {
    throw new Rejected("SPEC_INVALID", "draftMark 无效");
  }
  const comps = spec.components;
  if (!Array.isArray(comps) || comps.length === 0 || comps.length > 1500) throw new Rejected("SPEC_INVALID", "components 无效");
  comps.forEach((c, i) => {
    if (!c || typeof c !== "object" || !Object.prototype.hasOwnProperty.call(SCHEMA, c.type)) {
      throw new Rejected("SPEC_INVALID", `第 ${i + 1} 个构件类型不受支持`);
    }
    const allowed = SCHEMA[c.type];
    for (const key of Object.keys(c)) {
      if (key !== "type" && !Object.prototype.hasOwnProperty.call(allowed, key)) {
        throw new Rejected("SPEC_INVALID", `第 ${i + 1} 个构件（${c.type}）有未知字段 ${key}`);
      }
    }
    for (const [key, kind] of Object.entries(allowed)) {
      const optional = kind.endsWith("?");
      if (c[key] === undefined && optional) continue;
      if (!checkValue(kind, c[key])) throw new Rejected("SPEC_INVALID", `第 ${i + 1} 个构件（${c.type}）的 ${key} 无效`);
    }
    if (c.type === "table") {
      if (c.widths.length !== c.head.length || c.rows.some((r) => r.length !== c.head.length)) {
        throw new Rejected("SPEC_INVALID", `第 ${i + 1} 个构件（table）行列数不一致`);
      }
    }
  });
}

function build(G, spec) {
  const out = [];
  for (const c of spec.components) {
    switch (c.type) {
      case "letterhead": out.push(...G.letterhead({ agency: c.agency, docNo: c.docNo })); break;
      case "title": out.push(...G.title(c.lines)); break;
      case "zhusong": out.push(G.zhusong(c.text)); break;
      case "p": out.push(G.p(c.text)); break;
      case "h1": out.push(G.h1(c.text)); break;
      case "h2": out.push(G.h2(c.text)); break;
      case "h3": out.push(G.h3(c.text)); break;
      case "h4": out.push(G.h4(c.text)); break;
      case "table": out.push(...G.table({ caption: c.caption || undefined, head: c.head, rows: c.rows, widths: c.widths })); break;
      case "fujian": out.push(...G.fujian(c.items)); break;
      case "luokuan": out.push(...G.luokuan({ unit: c.unit, date: c.date })); break;
      case "fuzhu": out.push(G.fuzhu(c.text)); break;
      case "banji": out.push(...G.banji({ copyTo: c.copyTo || [], issuer: c.issuer, date: c.date })); break;
      default: throw new Rejected("SPEC_INVALID", `构件类型不受支持：${c.type}`);
    }
  }
  return out;
}

function draftHeaders(docx, text) {
  const make = () => new docx.Header({
    children: [new docx.Paragraph({
      alignment: docx.AlignmentType.CENTER,
      indent: { firstLine: 0, firstLineChars: 0 },
      children: [new docx.TextRun({ text, color: "C00000", size: 24 })],
    })],
  });
  return { default: make(), even: make() };
}

async function main() {
  const kit = path.resolve(arg("--kit"));
  const out = path.resolve(arg("--out"));
  if (!out.endsWith(".docx") || !fs.existsSync(path.dirname(out))) throw new Rejected("SPEC_INVALID", "--out 必须是已存在目录里的 .docx");
  const raw = fs.readFileSync(0);
  if (raw.length > MAX_STDIN) throw new Rejected("SPEC_INVALID", "spec 过大");
  let spec;
  try { spec = JSON.parse(raw.toString("utf8")); } catch (e) { throw new Rejected("SPEC_INVALID", "spec 不是 JSON"); }
  validate(spec);

  const core = require(path.join(kit, "lib", "gongwen-core.js"));
  const version = require(path.join(kit, "package.json")).version;
  const G = core.form("wen");
  const docx = G.require_docx();
  let children;
  try {
    children = build(G, spec);
  } catch (e) {
    if (e instanceof Rejected) throw e;
    throw new Rejected("KIT_REJECTED", String(e.message || e));   // e.g. 发文机关标志过长
  }
  const section = G.sectionProps();
  if (spec.draftMark) section.headers = draftHeaders(docx, spec.draftMark);
  const doc = new docx.Document({
    creator: "InNet_box",
    title: spec.title,
    features: { updateFields: true },
    evenAndOddHeaderAndFooters: true,
    externalStyles: G.externalStyles(),
    numbering: G.numbering,
    sections: [{ ...section, children }],
  });

  // writeDoc prints its own check summary to stdout; keep stdout for our single JSON line.
  const realWrite = process.stdout.write.bind(process.stdout);
  process.stdout.write = () => true;
  let result;
  try {
    result = await G.writeDoc(doc, out, { strict: false, quiet: true });
  } finally {
    process.stdout.write = realWrite;
  }
  process.exitCode = 0;
  if (!result || !fs.existsSync(out)) {
    return emit({ ok: false, code: "RENDER_FAILED", message: "gongwen-kit 未能写出文件" }, 2);
  }
  // checked=false means either malformed XML or that writeDoc's own check run faulted.
  // Only the first is a render failure; a check fault surfaces in the separate `check --json`.
  if (result.checked === false) {
    const { checkXmlParts } = require(path.join(kit, "lib", "doc-integrity.js"));
    const problems = await checkXmlParts(fs.readFileSync(out));
    if (problems.length) {
      return emit({ ok: false, code: "RENDER_FAILED", message: `生成的 DOCX 有 ${problems.length} 个 XML 部件结构错误` }, 2);
    }
  }
  emit({ ok: true, out, bytes: fs.statSync(out).size, toolVersion: version, components: spec.components.length }, 0);
}

main().catch((e) => {
  if (e instanceof Rejected) emit({ ok: false, code: e.code, message: e.message }, 3);
  else emit({ ok: false, code: "RENDER_FAILED", message: String((e && e.message) || e).slice(0, 500) }, 2);
});
