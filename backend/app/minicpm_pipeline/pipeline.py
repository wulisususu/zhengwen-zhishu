"""文档生成管线 v5 — Qwen3-0.6B 路由 + Qwen2.5-3B 单章生成 + 自动重启。

策略：每章独立调用 3B（独占 2048 tokens → ~1200 chars/章），每 3 次推理后自动重启服务。
  推理1: 大纲 (~50s)
  推理2: 第1章 (~100s, ~1200 chars)
  推理3: 第2章 (~100s, ~1200 chars)
  → 自动重启 3B 服务
  推理4: 第3章 (~100s, ~1200 chars)
  推理5: 第4章 (~100s, ~1200 chars)
  推理6: 第5章 (~100s, ~1200 chars)
  → 自动重启 3B 服务
  推理7: 第6章 (~100s, ~1200 chars)
  总计: 7 次推理, ~7200 chars, ~750s
"""
from __future__ import annotations

import json, logging, re, subprocess, time, uuid
from collections import Counter
from pathlib import Path
from typing import Any
import requests

from app.services.document_service import (
    DOC_OUTPUT_DIR, TEMPLATE_DIR, ENGINE_BY_TYPE, TEMPLATE_BY_TYPE,
    ensure_default_templates, render_with_template, build_dynamic_doc,
)
from app.services.document_agent import _parse_json_object

logger = logging.getLogger(__name__)

# ── 端点 ──────────────────────────────────────────────────────────
ROUTER_URL  = "http://127.0.0.1:8002/v1/chat/completions"
ROUTER_MODEL = "Qwen3-0.6B-Q4_K_M.gguf"
GEN_URL  = "http://127.0.0.1:8093/v1/chat/completions"
GEN_MODEL = "Qwen2.5-3B-Instruct"

WATCHDOG = "/home/youyeetoo/rkllm_model_zoo/qwen2.5-3b-rkllm/watchdog.sh"
INFERENCES_BEFORE_RESTART = 3
RESTART_COOLDOWN = 35  # 服务器重启 + 模型冷却需要的秒数

VALID_DOC_TYPES = {"weekly_report", "resume", "checklist", "simple_report", "complex_report"}

# ── Prompts ───────────────────────────────────────────────────────
ROUTER_SYSTEM = """你是文档类型路由器。分析用户输入,输出JSON分类。
类型: weekly_report(周报) resume(简历) checklist(清单) simple_report(简单报告) complex_report(复杂报告)
引擎: docxtpl(模板型) python-docx(动态型)
规则: 周报/简历/清单→docxtpl, 复杂/分析/方案/调研→python-docx, 其他→simple_report/docxtpl
只输出JSON: {"doc_type":"","engine":"","template_id":""}"""

OUTLINE_SYSTEM = """你是严谨的报告大纲规划师。规划 6 个章节结构，不写正文。
规则：只使用公认知识；不确定的标注"[待核实]"；禁止编造数据。
输出JSON：{"title":"","sections":[{"heading":"","key_points":""},...],"summary":""}
章节数量：6 个。只输出JSON。"""

SECTION_SYSTEM = """你是严谨的报告撰写助手。现在只撰写报告中的一个章节。

核心规则（违反任一条即为失败）：
1. 只使用公认事实、常识和用户提供的参考资料
2. 绝对禁止编造：具体数字、百分比、人名、地名、日期、研究名称、引用来源
3. 不确定的信息写"目前尚无确切数据"，不猜测
4. 使用"建议""可考虑""通常"等审慎措辞
5. 本章正文 1000-1500 字，写不够就一直写

输出格式（Markdown）：
## 章节标题
章节正文内容（1000-1500字）

只输出上述格式。"""


# ══════════════════════════════════════════════════════════════════
# 路由 (Qwen3-0.6B)
# ══════════════════════════════════════════════════════════════════

def route_document(user_input: str) -> dict:
    messages = [
        {"role": "system", "content": ROUTER_SYSTEM},
        {"role": "user", "content": "用户输入：" + user_input},
    ]
    try:
        t0 = time.time()
        resp = requests.post(ROUTER_URL, json={
            "model": ROUTER_MODEL, "messages": messages,
            "max_tokens": 128, "temperature": 0.1, "stop": ["\n\n\n"], "stream": False,
        }, timeout=15)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        logger.info("Route: %.1fs raw=%s", time.time() - t0, raw[:120])
        route = _parse_json_object(raw)
    except Exception as e:
        logger.warning("Route fallback: %s", e)
        route = {}
    return _normalize_route(route, user_input)


def _normalize_route(route: dict, user_input: str) -> dict:
    route = dict(route or {})
    doc_type = route.get("doc_type", "")
    if doc_type not in VALID_DOC_TYPES:
        text = user_input.lower()
        if "周报" in text:      doc_type = "weekly_report"
        elif "简历" in text:    doc_type = "resume"
        elif "清单" in text or "检查表" in text: doc_type = "checklist"
        elif any(k in text for k in ("分析","方案","调研","评估")): doc_type = "complex_report"
        else:                   doc_type = "simple_report"
    route["doc_type"] = doc_type
    route["engine"] = "python-docx"
    route["template_id"] = TEMPLATE_BY_TYPE.get(doc_type, "simple_v1")
    route.setdefault("output_spec", {})["format"] = "docx"
    route.setdefault("primary_operation", "generate")
    return route


# ══════════════════════════════════════════════════════════════════
# 3B 调用 + 自动重启
# ══════════════════════════════════════════════════════════════════

_inference_count = [0]  # 全局推理计数器

def _restart_3b_server():
    """Kill and restart the 3B server via watchdog."""
    logger.info("Restarting 3B server via watchdog...")
    try:
        subprocess.run(["bash", WATCHDOG], capture_output=True, timeout=60)
    except Exception as e:
        logger.error("Watchdog failed: %s", e)
    time.sleep(RESTART_COOLDOWN)
    _inference_count[0] = 0
    logger.info("3B server should be ready")


def _call_3b(system: str, user: str, max_tokens: int = 2048,
             temperature: float = 0.1, timeout: int = 300) -> str:
    """Call 3B. Auto-restart server on connection failure."""

    # Proactive restart before hitting NPU limit
    if _inference_count[0] >= INFERENCES_BEFORE_RESTART:
        logger.info("Proactive restart after %d inferences", _inference_count[0])
        _restart_3b_server()

    payload = {
        "model": GEN_MODEL,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens, "temperature": temperature, "stream": False,
    }

    for attempt in range(3):
        try:
            t0 = time.time()
            resp = requests.post(GEN_URL, json=payload, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(data["error"])
            raw = data["choices"][0]["message"]["content"]
            elapsed = time.time() - t0
            _inference_count[0] += 1
            logger.info("3B [%d/%d]: %.1fs %d chars",
                       _inference_count[0], INFERENCES_BEFORE_RESTART, elapsed, len(raw))
            return raw.strip()
        except requests.ConnectionError:
            logger.warning("3B connection refused (attempt %d), restarting...", attempt + 1)
            _restart_3b_server()
        except Exception as e:
            logger.warning("3B call failed (attempt %d): %s", attempt + 1, e)
            if attempt < 2:
                time.sleep(5)
            else:
                raise RuntimeError("3B unavailable: %s" % e)

    raise RuntimeError("3B unavailable after restart attempts")


def _has_repetition(text: str, threshold: int = 4) -> bool:
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    return len(lines) >= threshold and Counter(lines).most_common(1)[0][1] >= threshold


# ══════════════════════════════════════════════════════════════════
# 推理1: 大纲
# ══════════════════════════════════════════════════════════════════

def generate_outline(user_input: str, attachment_context: str = "") -> dict:
    user_msg = "主题：" + user_input
    if attachment_context:
        user_msg += "\n参考资料：" + attachment_context[:1500]

    temp = 0.1
    for attempt in range(2):
        try:
            raw = _call_3b(OUTLINE_SYSTEM, user_msg, max_tokens=1024, temperature=temp)
            outline = _parse_json_object(raw)
            secs = outline.get("sections") or []
            if isinstance(secs, list) and len(secs) >= 3:
                logger.info("Outline: %d sections", len(secs))
                return outline
            temp = min(temp + 0.15, 0.5)
            time.sleep(2)
        except Exception as e:
            logger.error("Outline error: %s", e)
            if attempt == 1: raise
    return _fallback_outline(user_input)


def _fallback_outline(user_input: str) -> dict:
    t = user_input[:80]
    return {"title": t, "sections": [
        {"heading": "背景与概述", "key_points": "介绍" + t + "的基本背景"},
        {"heading": "现状分析", "key_points": "分析" + t + "的当前状况"},
        {"heading": "关键问题与挑战", "key_points": "识别" + t + "面临的主要挑战"},
        {"heading": "解决方案与策略", "key_points": "提出" + t + "的解决思路"},
        {"heading": "实施建议", "key_points": "给出" + t + "的落地建议"},
        {"heading": "总结与展望", "key_points": "总结并展望未来"},
    ], "summary": "关于" + t + "的综合分析报告"}


# ══════════════════════════════════════════════════════════════════
# 推理2-7: 单章生成（每章独占 2048 tokens）
# ══════════════════════════════════════════════════════════════════

def generate_section(
    section_index: int, total_sections: int,
    heading: str, key_points: str,
    user_input: str, attachment_context: str = "",
) -> dict:
    """Generate ONE section. Returns {heading, content}."""
    user_msg = (
        "报告主题：" + user_input + "\n"
        "章节位置：第 " + str(section_index + 1) + "/" + str(total_sections) + " 章\n"
        "章节标题：" + heading + "\n"
        "核心观点：" + key_points + "\n\n"
        "请输出本章完整内容（1000-1500字）："
    )
    if attachment_context:
        user_msg += "\n参考资料：" + attachment_context[:800]

    temp = 0.1
    for attempt in range(2):
        try:
            raw = _call_3b(SECTION_SYSTEM, user_msg, max_tokens=2048, temperature=temp)
            if _has_repetition(raw):
                logger.warning("Section %d repetition, retry", section_index + 1)
                temp = min(temp + 0.15, 0.5)
                time.sleep(2)
                continue

            # Clean heading if model repeated it
            raw = re.sub(r'^##\s*' + re.escape(heading) + r'\s*', '', raw).strip()
            if len(raw) < 200:
                logger.warning("Section %d too short (%d chars), retry", section_index + 1, len(raw))
                temp = min(temp + 0.15, 0.5)
                time.sleep(2)
                continue

            logger.info("Section %d/%d OK: %d chars", section_index + 1, total_sections, len(raw))
            return {"heading": heading, "content": raw}

        except Exception as e:
            logger.error("Section %d error: %s", section_index + 1, e)
            if attempt == 1:
                return {"heading": heading, "content": "[本章生成失败: " + str(e) + "]"}

    return {"heading": heading, "content": "[本章生成失败]"}


# ══════════════════════════════════════════════════════════════════
# DOCX 渲染 (不变)
# ══════════════════════════════════════════════════════════════════

def _render_markdown_to_docx(markdown_text: str, title: str, output_path: Path) -> None:
    from docx import Document
    doc = Document()
    doc.add_heading(title, level=1)
    lines = markdown_text.splitlines(); i = 0
    while i < len(lines):
        line = lines[i]
        if not line.strip(): i += 1; continue
        if re.match(r"^#[^#]", line): i += 1; continue
        for lvl, pat in [(2, r"^##[^#]"), (3, r"^###[^#]"), (4, r"^####[^#]")]:
            m = re.match(pat + r"\s*(.+)", line)
            if m: doc.add_heading(m.group(1).strip(), level=lvl); i += 1; break
        else:
            if re.match(r"^[\-\*]\s", line.strip()):
                items = []
                while i < len(lines) and re.match(r"^[\-\*]\s", lines[i].strip()):
                    items.append(re.sub(r"^[\-\*]\s+", "", lines[i].strip())); i += 1
                for item in items:
                    p = doc.add_paragraph(style="List Bullet"); _add_md_runs(p, item)
            elif re.match(r"^\d+[\.\、\)]\s", line.strip()):
                items = []
                while i < len(lines) and re.match(r"^\d+[\.\、\)]\s", lines[i].strip()):
                    items.append(re.sub(r"^\d+[\.\、\)]\s+", "", lines[i].strip())); i += 1
                for item in items:
                    p = doc.add_paragraph(style="List Number"); _add_md_runs(p, item)
            else:
                para_lines = []
                while i < len(lines) and lines[i].strip():
                    if re.match(r"^(#{1,4}\s|[\-\*]\s|\d+[\.\、\)]\s)", lines[i].strip()): break
                    para_lines.append(lines[i]); i += 1
                if para_lines:
                    p = doc.add_paragraph(); _add_md_runs(p, "\n".join(para_lines).strip())
                else:
                    i += 1
    doc.save(output_path)


def _add_md_runs(p, text):
    for part in re.split(r"(\*\*[^*]+\*\*)", text):
        if part.startswith("**") and part.endswith("**"):
            inner = part[2:-2]
            for sp in re.split(r"(\*[^*]+\*)", inner):
                if sp.startswith("*") and sp.endswith("*") and len(sp) > 2:
                    r = p.add_run(sp[1:-1]); r.bold = True; r.italic = True
                else:
                    r = p.add_run(sp); r.bold = True
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            r = p.add_run(part[1:-1]); r.italic = True
        else:
            p.add_run(part)


def _safe_filename(text: str) -> str:
    base = re.sub(r"[^0-9A-Za-z一-鿿_-]+", "_", str(text).strip()).strip("_")
    return base[:48] if base else "document"


def _parse_markdown_sections(text: str) -> list[dict]:
    sections = []; cur_h = ""; cur_lines = []
    for line in text.splitlines():
        s = line.strip()
        if re.match(r"^#[^#]", s): continue
        if not cur_h and not s: continue
        if re.match(r"^##[^#]", s):
            c = "\n".join(cur_lines).strip()
            if cur_h and c: sections.append({"heading": cur_h, "content": c})
            cur_h = re.sub(r"^#{2,4}\s*", "", s); cur_lines = []
        else:
            cur_lines.append(line)
    c = "\n".join(cur_lines).strip()
    if cur_h and c: sections.append({"heading": cur_h, "content": c})
    return sections


# ══════════════════════════════════════════════════════════════════
# 主 Pipeline — 单章生成 + 自动重启
# ══════════════════════════════════════════════════════════════════

def run_pipeline_segmented(
    user_input: str, attachment_context: str = "", progress_callback=None,
) -> dict:
    """Single-section pipeline with auto-restart every 3 inferences."""

    # Phase 0: Route
    if progress_callback:
        progress_callback({"phase": "route", "message": "Qwen3-0.6B 分析文档类型..."})
    route = route_document(user_input)

    # Phase 1: Outline (推理 1)
    if progress_callback:
        progress_callback({"phase": "outline", "message": "推理 1: 生成大纲..."})
    outline = generate_outline(user_input, attachment_context=attachment_context)
    sections_plan = outline.get("sections", [])
    title = outline.get("title") or user_input[:40]
    total = len(sections_plan)
    logger.info("Outline: %d sections", total)

    # Phase 2: Section by section (推理 2 - 2+total)
    all_results = []
    total_chars = 0

    for idx, sec in enumerate(sections_plan):
        heading = sec.get("heading", "第" + str(idx + 1) + "章")
        key_points = sec.get("key_points", "")

        inf_num = _inference_count[0] + 1  # +1 because outline already counted
        restart_hint = ""
        if _inference_count[0] > 0 and _inference_count[0] % INFERENCES_BEFORE_RESTART == 0:
            restart_hint = "（即将自动重启服务）"

        if progress_callback:
            progress_callback({
                "phase": "generate", "index": idx + 1, "total": total,
                "heading": heading,
                "message": "推理 {}/{}: {} {}".format(
                    inf_num, total + 1, heading, restart_hint),
            })

        result = generate_section(
            section_index=idx, total_sections=total,
            heading=heading, key_points=key_points,
            user_input=user_input, attachment_context=attachment_context,
        )
        all_results.append(result)
        section_chars = len(result["content"])
        total_chars += section_chars

        if progress_callback:
            progress_callback({
                "phase": "generate", "index": idx + 1, "total": total,
                "heading": heading,
                "message": "完成 {}/{}: {} ({} chars)".format(idx + 1, total, heading, section_chars),
                "sections": [{"heading": r["heading"], "content": r["content"][:200] + "..."}
                           for r in all_results],
            })

    # Phase 3: Render
    all_text = ["## " + r["heading"] + "\n" + r["content"] for r in all_results]
    full_md = "# " + title + "\n\n" + "\n\n".join(all_text)

    if progress_callback:
        progress_callback({
            "phase": "rendering",
            "message": "渲染 DOCX（{}章, {}字）...".format(len(all_results), total_chars),
            "sections": all_results,
        })

    ensure_default_templates()
    fn = _safe_filename(title) + ".docx"
    op = DOC_OUTPUT_DIR / (uuid.uuid4().hex + ".docx")
    _render_markdown_to_docx(full_md, title, op)
    fs = op.stat().st_size

    logger.info("Done: %d sections, %d chars, %s (%d bytes)", len(all_results), total_chars, fn, fs)
    return {
        "route": route,
        "content_schema": {"title": title, "sections": all_results, "summary": outline.get("summary", "")},
        "total_chars": total_chars, "section_count": len(all_results),
        "filename": fn, "filepath": str(op), "filesize": fs,
    }


def run_pipeline(user_input: str, attachment_context: str = "", progress_callback=None) -> dict:
    if progress_callback: progress_callback("Qwen3-0.6B analyzing...")
    return run_pipeline_segmented(user_input, attachment_context=attachment_context, progress_callback=progress_callback)
