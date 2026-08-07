"""LangGraph 节点函数 — docs_pipeline v3."""
import asyncio
import json
import logging
import os
import re
import uuid
from pathlib import Path

import requests
from docx import Document

from app.docs_pipeline.state import PipelineState
from app.docs_pipeline.retry import async_retry_with_restart, retry_render
from app.docs_pipeline.core import (
    generate_outline,
    _fallback_outline,
    _restart_3b,
    _parse_json_object,
    load_prompt,
    ROUTER_URL,
    ROUTER_MODEL,
    GEN_URL,
    GEN_MODEL,
)
from app.services.markdown_to_docx import markdown_to_docx
from app.services.document_service import DOC_OUTPUT_DIR, ensure_default_templates

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# SSE queue context
# ═══════════════════════════════════════════════════════════

import contextvars
_sse_queue_ctx: contextvars.ContextVar = contextvars.ContextVar("sse_queue", default=None)


def set_sse_queue(queue: asyncio.Queue) -> None:
    _sse_queue_ctx.set(queue)


def get_sse_queue() -> asyncio.Queue | None:
    return _sse_queue_ctx.get(None)


async def _push_sse(event_type: str, data: dict) -> None:
    queue = get_sse_queue()
    if queue:
        await queue.put({"type": event_type, "data": data})


def _parse_json_value(text: str):
    """解析 JSON——支持 dict 和 array."""
    from app.docs_pipeline.core import _parse_json_object
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
        if isinstance(value, (dict, list)):
            return value
    except Exception:
        pass
    for pattern in (r"\[[\s\S]*\]", r"\{[\s\S]*\}"):
        match = re.search(pattern, text)
        if match:
            try:
                value = json.loads(match.group(0))
                if isinstance(value, (dict, list)):
                    return value
            except Exception:
                pass
    return _parse_json_object(text)


# ═══════════════════════════════════════════════════════════
# 节点 ① — 3B 一站式：标题 + 大纲 + 100字章节提示词
# ═══════════════════════════════════════════════════════════

PLAN_SYSTEM = """你是报告大纲策划师。为主题生成恰好 {section_count} 章大纲。
要求：标题≤20字；章节标题必须具体、互不重复；禁止“具体内容标题/章节标题/待定”等占位词；章节按背景→问题→方案→实施→保障/总结递进；不编造数据。
输出 JSON：{{"title":"","sections":[{{"heading":"","key_points":"1-2句","gen_prompt":"约60字，说明本章写作重点和承接关系"}}],"summary":"一句话全文主线"}}
只输出 JSON。"""

_PLACEHOLDER_HEADING_PATTERNS = (
    r"具体内容标题", r"章节标题", r"内容标题", r"标题待定", r"待定",
    r"未命名章节", r"^第\s*\d+\s*章$", r"^chapter\s*\d+$",
)


def _is_placeholder_heading(heading: str) -> bool:
    text = (heading or "").strip()
    if not text:
        return True
    normalized = re.sub(r"^第\s*\d+\s*章\s*", "", text).strip()
    if not normalized:
        return True
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in _PLACEHOLDER_HEADING_PATTERNS)


def _clean_outline_sections(outline: dict, section_count: int) -> list[dict]:
    sections = outline.get("sections", []) if isinstance(outline, dict) else []
    cleaned: list[dict] = []
    seen: set[str] = set()
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        heading = str(sec.get("heading", "")).strip()
        if _is_placeholder_heading(heading):
            continue
        key = _clean_heading_text(heading)
        normalized_key = re.sub(r"\s+", "", key).lower()
        if normalized_key in seen:
            continue
        seen.add(normalized_key)
        item = dict(sec)
        item["heading"] = heading
        item["key_points"] = str(item.get("key_points", "")).strip()
        if not item.get("gen_prompt"):
            item["gen_prompt"] = f"请围绕「{item.get('key_points', '')}」撰写本章，注意与前后章的衔接。"
        cleaned.append(item)
        if len(cleaned) >= section_count:
            break
    return cleaned if len(cleaned) == section_count else []


_WEAK_TITLE_SUFFIXES = ("的", "与", "和", "及", "对于", "关于", "基于", "面向", "结合")


def _clean_report_title(title: str, user_input: str, max_chars: int = 34) -> str:
    candidate = re.sub(r"\s+", "", (title or "").strip())
    source = re.sub(r"\s+", "", (user_input or "").strip())
    if not candidate or any(candidate.endswith(suffix) for suffix in _WEAK_TITLE_SUFFIXES):
        candidate = source
    candidate = candidate.strip("，。；：,. ;:")
    candidate = candidate.replace("对于", "").replace("关于", "")
    candidate = candidate.replace("相结合的", "融合").replace("相结合", "融合")
    candidate = candidate.replace("大模型与低空经济融合的", "大模型与低空经济融合")
    while any(candidate.endswith(suffix) for suffix in _WEAK_TITLE_SUFFIXES):
        for suffix in _WEAK_TITLE_SUFFIXES:
            if candidate.endswith(suffix):
                candidate = candidate[:-len(suffix)].strip("，。；：,. ;:")
                break
    if not re.search(r"(报告|方案|规划|研究|分析|白皮书)$", candidate):
        if "规划" in source:
            candidate += "规划报告"
        elif "方案" in source:
            candidate += "方案"
        else:
            candidate += "研究报告"
    return candidate[:max_chars] or "未命名文档"


async def polish_outline_node(state: PipelineState) -> PipelineState:
    """3B 一站式生成标题 + 大纲 + 章节指令."""
    task_id = state.get("task_id", "?")
    user_input = state["user_input"]
    section_count = state.get("section_count", 6)
    logger.info("[%s] Node ① polish_outline START — topic='%s', sections=%d (3B)", task_id, user_input[:30], section_count)

    await _push_sse("status", {"phase": "polishing", "message": "正在分析你的写作要求..."})

    system = PLAN_SYSTEM.format(section_count=section_count)
    polished_title = _clean_report_title("", user_input)
    outline = {}
    clean_sections = []

    try:
        resp = await asyncio.to_thread(requests.post, GEN_URL, json={
            "model": GEN_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"主题：{user_input}\n请生成可直接展示的标题、恰好{section_count}章大纲和每章撰写指令。章节标题必须具体，禁止占位标题，章节之间要有清晰递进。"},
            ],
            "max_tokens": 1500,
            "temperature": 0.15,
            "stream": False,
        }, timeout=300)
        resp.raise_for_status()
        raw = resp.json()["choices"][0]["message"]["content"]
        parsed = _parse_json_value(raw)

        if isinstance(parsed, dict):
            polished_title = _clean_report_title(parsed.get("title", ""), user_input)
            outline = {"title": polished_title, "sections": parsed.get("sections", []), "summary": parsed.get("summary", "")}
            clean_sections = _clean_outline_sections(outline, section_count)
            if not clean_sections:
                logger.warning("[%s] 3B outline rejected by quality gate; raw_sections=%s", task_id, parsed.get("sections", []))
    except Exception as e:
        logger.warning("[%s] 3B outline failed: %s; using deterministic outline", task_id, e)

    # Keep the document degradation path 3B-only. If 3B planning is
    # unavailable, retain service continuity with a deterministic outline;
    # do not contend for the NPU by invoking the 0.6B chat fallback.
    if not clean_sections:
        logger.warning("[%s] 3B outline unavailable; using deterministic outline", task_id)
        outline = _fallback_outline(polished_title, section_count)
        clean_sections = _clean_outline_sections(outline, section_count)

    polished_title = _clean_report_title(polished_title, user_input)
    outline["title"] = polished_title
    outline["sections"] = clean_sections

    await _push_sse("outline", {
        "title": polished_title,
        "sections": clean_sections,
        "summary": outline.get("summary", ""),
    })

    logger.info("[%s] Node ① polish_outline DONE — title='%s', sections=%d", task_id, polished_title, len(clean_sections))
    return {
        **state,
        "polished_title": polished_title,
        "outline": outline,
        "global_thread": _build_global_thread(polished_title, outline),
        "status": "outlining",
    }


# ═══════════════════════════════════════════════════════════
# 节点 ② — 提取章节指令（3B 已在 ① 里生成了 gen_prompt）
# ═══════════════════════════════════════════════════════════

async def build_chapter_prompts_node(state: PipelineState) -> PipelineState:
    """直接使用 Node ① 中 3B 生成的 gen_prompt，无需额外调用."""
    task_id = state.get("task_id", "?")
    sections = state["outline"].get("sections", [])
    logger.info("[%s] Node ② build_chapter_prompts START — sections=%d (from 3B)", task_id, len(sections))

    await _push_sse("status", {"phase": "building_prompts", "message": "正在编排写作逻辑..."})

    chapter_prompts = []
    for sec in sections:
        gen_prompt = sec.get("gen_prompt", "")
        if not gen_prompt:
            gen_prompt = f"请围绕「{sec.get('key_points', '')}」撰写本章。注意与前后章的衔接。"
        chapter_prompts.append({
            "heading": sec["heading"],
            "key_points": sec.get("key_points", ""),
            "gen_prompt": gen_prompt,
        })

    logger.info("[%s] Node ② build_chapter_prompts DONE — prompts=%d", task_id, len(chapter_prompts))
    return {
        **state,
        "chapter_prompts": chapter_prompts,
        "status": "generating",
    }


# ═══════════════════════════════════════════════════════════
# 节点 ③ — 逐章生成正文（循环节点）
# ═══════════════════════════════════════════════════════════

FALLBACK_SECTION_SYSTEM = """你需为以下章节生成一段简短摘要（200-300字），因为主模型暂时不可用。
章节：{heading}
核心观点：{key_points}
只输出正文。使用审慎措辞，不编造任何具体数据。"""


# 精简版 section system，避免 prompt 过长撑爆 ctx
SECTION_SYSTEM_SHORT = """只写第{index}/{total}章《{heading}》，{min_words}-{max_words}字。主题：{topic}，核心：{key_points}。
规则：不要写全篇大纲；不要写其他章节内容；不编造企业动作/资金/合作/排名；Markdown 输出；3-4个###子标题。"""


def _clean_heading_text(heading: str) -> str:
    heading = (heading or "").strip()
    heading = re.sub(r"^第\s*\d+\s*章\s*", "", heading).strip()
    return heading or "未命名章节"


def _build_global_thread(topic: str, outline: dict, max_chars: int = 120) -> str:
    sections = outline.get("sections", []) if isinstance(outline, dict) else []
    names = [_clean_heading_text(s.get("heading", "")) for s in sections if isinstance(s, dict)]
    progression = " -> ".join(names[:6])
    thread = f"全文主线：围绕{topic}，按{progression}递进。" if progression else f"全文主线：围绕{topic}递进展开。"
    return thread[:max_chars]


def _summarize_chapter_for_bridge(content: str, max_chars: int = 90) -> str:
    text = re.sub(r"^#{1,6}\s+.*$", "", content or "", flags=re.MULTILINE)
    sentences = re.split(r"(?<=[。！？])", text)
    for sentence in sentences:
        sentence = re.sub(r"\s+", "", sentence)
        if len(sentence) >= 12:
            return sentence[:max_chars]
    return re.sub(r"\s+", "", text)[:max_chars]


def _build_section_system(topic: str, idx: int, total: int, heading: str, key_points: str, gen_prompt: str, global_thread: str = "", prev_summary: str = "") -> str:
    system = SECTION_SYSTEM_SHORT.format(
        topic=topic, total=total, index=idx, heading=heading, key_points=key_points,
        min_words=800, max_words=1200,
    )
    parts = []
    if global_thread:
        parts.append(global_thread[:120])
    if idx > 1 and prev_summary:
        parts.append(f"上一章结论：{prev_summary[:90]}。本章开头承接上一章，不重复上一章。")
    if gen_prompt:
        parts.append(f"本章任务：{gen_prompt[:150]}")

    # 按章节位置加差异化边界约束
    if idx == 1:
        parts.append("本章只写背景、现状和基础分析，禁止写解决方案、实施步骤、保障措施、总结或展望段。"
                      "禁止出现‘方案设计’‘实施路径’‘保障措施’‘总结展望’等二级话题。")
    elif idx == total:
        parts.append("本章只做总结提炼：回顾前文各章的核心结论（2-3句/章），然后给出整体展望。"
                      "禁止重新展开叙述任何前文内容，禁止再写‘项目背景’‘问题分析’‘方案设计’等段。"
                      "字数可以略少于前文章节。")
    else:
        parts.append("本章只围绕标题展开，禁止提前涉及到后面章节才写的主题。"
                      "禁止在非总结章节末尾写‘总结’‘展望’‘保障措施’子标题。")
    parts.append("未由用户提供的资金、政策、合作、领先地位、时间表，一律写成‘建议’或‘可考虑’等审慎措辞，"
                  "绝不写成确定性动作或已发生事实。")
    return system + "\n" + "\n".join(parts)
async def _call_3b_one_section(
    topic: str,
    idx: int,
    total: int,
    heading: str,
    key_points: str,
    gen_prompt: str,
    global_thread: str = "",
    prev_summary: str = "",
) -> str:
    """调用 3B 生成单章正文."""
    system = _build_section_system(
        topic=topic, idx=idx, total=total, heading=heading,
        key_points=key_points, gen_prompt=gen_prompt,
        global_thread=global_thread, prev_summary=prev_summary,
    )

    resp = await asyncio.to_thread(requests.post, GEN_URL, json={
        "model": GEN_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"请输出第 {idx} 章正文（800-1200字）:"},
        ],
        "max_tokens": 1500,
        "temperature": 0.1,
        "stream": False,
    }, timeout=300)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["choices"][0]["message"]["content"].strip()


async def _fallback_section_06b(heading: str, key_points: str) -> str:
    """0.6B 代写降级章节."""
    try:
        system = FALLBACK_SECTION_SYSTEM.format(heading=heading, key_points=key_points)
        resp = requests.post(ROUTER_URL, json={
            "model": ROUTER_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"请输出 {heading} 的简要内容（200-300字）:"},
            ],
            "max_tokens": 512,
            "temperature": 0.2,
            "stream": False,
        }, timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
        return "[本章内容需人工补充]\n\n" + content
    except Exception:
        return f"[本章内容需人工补充]\n\n## {heading}\n\n（本章因服务暂时不可用，需要人工补充。核心观点：{key_points}）"


async def generate_next_chapter_node(state: PipelineState) -> PipelineState:
    """3B 生成下一章正文（单章，循环调用）."""
    idx = state["current_idx"]
    total = state["section_count"]
    chapter_prompts = state.get("chapter_prompts", [])
    topic = state["polished_title"]
    task_id = state.get("task_id", "?")
    logger.info("[%s] Node ③ generate_chapter START — chapter %d/%d '%s'",
                task_id, idx, total,
                chapter_prompts[idx - 1].get("heading", "?") if idx <= len(chapter_prompts) else "?")

    if idx == 1:
        await _push_sse("status", {"phase": "generating", "message": "正在生成文档内容，请稍等..."})

    if idx > total or idx > len(chapter_prompts):
        return state

    prompt = chapter_prompts[idx - 1]
    heading = prompt.get("heading", f"第{idx}章")
    key_points = prompt.get("key_points", "")
    gen_prompt = prompt.get("gen_prompt", key_points)

    content, retries_used, success = await async_retry_with_restart(
        fn=lambda: _call_3b_one_section(
            topic, idx, total, heading, key_points, gen_prompt,
            state.get("global_thread", ""),
            (state.get("chapter_summaries", []) or [""])[-1] if idx > 1 else "",
        ),
        max_retries=5,
        label=f"Chapter {idx}",
    )

    fallback = False
    if not success:
        logger.error("[%s] Chapter %d/%d: 3B unavailable after extended retries; pausing chapter output", task_id, idx, total)
        content = (
            "[本章生成暂停]\n\n"
            f"## {heading}\n\n"
            "主模型当前未能稳定完成本章生成。为避免输出低质量兜底内容，"
            "已暂停本章正文输出。请在3B模型恢复稳定后重新生成。"
        )
        fallback = True
    else:
        pass

    retries = dict(state.get("chapter_retries", {}))
    if retries_used > 0:
        retries[str(idx)] = retries_used

    chapter = {
        "idx": idx, "total": total,
        "heading": _format_chapter_heading(idx, heading),
        "content": content,
        "fallback": fallback,
    }
    chapter = _quality_check_chapter(chapter)
    await _push_sse("chapter", chapter)

    if idx < total and not fallback:
        logger.info("[%s] Node ③ chapter %d/%d done (%d chars, fallback=%s), restarting 3B...",
                    task_id, idx, total, len(content) if content else 0, fallback)
        await asyncio.to_thread(_restart_3b)
    else:
        logger.info("[%s] Node ③ chapter %d/%d done (%d chars, fallback=%s)",
                    task_id, idx, total, len(content) if content else 0, fallback)

    return {
        **state,
        "generated_chapters": [chapter],
        "current_idx": idx + 1,
        "chapter_retries": retries,
        "chapter_summaries": [_summarize_chapter_for_bridge(chapter.get("content", ""))],
    }



def _format_chapter_heading(idx: int, heading: str) -> str:
    heading = (heading or f"第{idx}章").strip()
    # 依次剥离各类编号前缀，避免双编号（如 "第1章 1. 标题"）
    heading = re.sub(r"^第\s*\d+\s*[章節节]\s*", "", heading)     # "第1章 " "第2节 "
    heading = re.sub(r"^\d+\s*[\.、．)）\s]\s*", "", heading)     # "1. " "1、" "1) " "1．"
    heading = re.sub(r"^[零一二三四五六七八九十百千]+\s*[、．\s]\s*", "", heading)  # "一、" "二、"
    heading = heading.strip()
    return f"第{idx}章 {heading}" if heading else f"第{idx}章"


def _normalize_section_content(content: str, chapter_idx: int) -> str:
    counter = 0
    lines = []

    def normalize_heading(raw_heading: str) -> str:
        nonlocal counter
        heading = raw_heading.strip()
        # 循环剥离各类编号前缀，确保多层编号（1.1.1 或 1.1 1.）也能剥干净
        prev = None
        while heading != prev:
            prev = heading
            heading = re.sub(r"^\d+\.\d+(?:\.\d+)?\s*", "", heading)  # "1.1 " "2.3.1 "
            heading = re.sub(r"^\d+[\.、．)）\s]+", "", heading)      # "1." "1、" "1) "
            heading = re.sub(r"^[零一二三四五六七八九十百千]+[、．\s]+", "", heading)  # "一、"
            heading = re.sub(r"^[（(][零一二三四五六七八九十百千\d]+[）)]\s*", "", heading)  # "（一）"
            heading = heading.strip()
        counter += 1
        return f"### {chapter_idx}.{counter} {heading}"

    for raw_line in (content or "").splitlines():
        line = raw_line.rstrip()
        marked = re.match(r"^#{3,6}\s+(.+)$", line.strip())
        numbered = re.match(rf"^{chapter_idx}\.\d+\s+(.+)$", line.strip())
        if marked:
            lines.append(normalize_heading(marked.group(1)))
        elif numbered:
            lines.append(normalize_heading(numbered.group(1)))
        else:
            lines.append(line)
    return "\n".join(lines)




_HIGH_RISK_COMMITMENT_PATTERNS = [
    (r"(?:设立|划拨|安排|投入)\s*(?:专项基金|专项资金|产业基金|扶持资金)", "可评估专项资金安排"),
    (r"申请\s*.{2,10}(?:扶持资金|补贴|税收减免|优惠政策)", "可结合现行政策条件评估"),
    (r"(?:成为|建成|打造)\s*.{2,20}?(?:示范区|领军者|全国领先|国际一流)", "可规划提升区域能力与示范效应"),
    (r"(?:是|作为)\s*.{2,20}?(?:全国|国际|行业)\s*.{2,5}?(?:领先|一流|领军|龙头)", "作为行业相关主体"),
    (r"(?:决定|计划)\s*(?:设立|投资|并购|组建)", "可评估相关方向"),
]

def _downgrade_unsupported_commitments(content: str) -> tuple:
    """用正则模式检测高风险声称，降级为审慎表达。返回 (content, changed, risk_count)."""
    updated = content or ""
    changed = False
    risk_count = 0
    for pattern, replacement in _HIGH_RISK_COMMITMENT_PATTERNS:
        matches = list(re.finditer(pattern, updated))
        if matches:
            risk_count += len(matches)
            updated = re.sub(pattern, replacement, updated)
            changed = True
    return updated, changed, risk_count


def _quality_check_chapter(chapter: dict, min_chars: int = 700) -> dict:
    checked = dict(chapter)
    flags = list(checked.get("quality_flags", []))
    idx = int(checked.get("idx", 1))
    content = _normalize_section_content(checked.get("content", "") or "", idx)
    content, downgraded, hallucination_count = _downgrade_unsupported_commitments(content)
    if downgraded:
        flags.append("unsupported_commitments_downgraded")
    checked["blocked"] = False
    if len(re.sub(r"[#*`\s]", "", content)) < min_chars:
        flags.append("too_short")
    checked["content"] = content
    checked["quality_flags"] = sorted(set(flags))
    return checked

def _build_section_messages(**kwargs) -> list[dict]:
    idx = kwargs["idx"]
    system = _build_section_system(**kwargs)
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": f"请输出第 {idx} 章正文（800-1200字）:"},
    ]

# ═══════════════════════════════════════════════════════════
# 节点 ④ — 组装 + DOCX 渲染 + 校验
# ═══════════════════════════════════════════════════════════

def _assemble_final_md(state: PipelineState) -> str:
    title = state["polished_title"]
    chapters = state["generated_chapters"]
    lines = [f"# {title}\n"]
    for ch in chapters:
        idx = int(ch.get("idx", len(lines)))
        lines.append(f"## {_format_chapter_heading(idx, ch.get('heading', ''))}\n")
        lines.append(_normalize_section_content(ch.get("content", ""), idx))
        lines.append("")
    return "\n".join(lines)


def _validate_docx(path: str) -> bool:
    if not os.path.exists(path):
        return False
    if os.path.getsize(path) < 1024:
        return False
    try:
        Document(path)
        return True
    except Exception:
        return False


async def assemble_render_validate_node(state: PipelineState) -> PipelineState:
    """组装 final.md → 渲染 DOCX → 校验."""
    task_id = state["task_id"]
    n_chapters = len(state.get("generated_chapters", []))
    logger.info("[%s] Node ④ assemble_render START — chapters=%d", task_id, n_chapters)
    final_md = _assemble_final_md(state)

    await _push_sse("status", {"phase": "rendering", "message": "渲染 DOCX 并校验..."})

    ensure_default_templates()
    docx_path = str(DOC_OUTPUT_DIR / f"{task_id}.docx")

    async def _render_once():
        markdown_to_docx(final_md, docx_path, title=state["polished_title"])
        return _validate_docx(docx_path)

    ok, retries = await retry_render(_render_once, max_retries=1)

    if not ok and retries > 0:
        await _push_sse("retry", {"phase": "retry_render", "message": "正在重新生成文档..."})

    if ok:
        size_kb = os.path.getsize(docx_path) / 1024
        logger.info("[%s] Node ④ assemble_render DONE — file=%s, size=%.1fKB",
                    task_id, os.path.basename(docx_path), size_kb)
        return {
            **state,
            "final_md": final_md,
            "docx_path": docx_path,
            "docx_size": os.path.getsize(docx_path),
            "docx_valid": True,
            "render_retries": state.get("render_retries", 0) + retries,
            "status": "done",
        }
    else:
        logger.error("[%s] Node ④ assemble_render FAILED — retries exhausted", task_id)
        return {
            **state,
            "final_md": final_md,
            "docx_path": "",
            "docx_size": 0,
            "docx_valid": False,
            "render_retries": state.get("render_retries", 0) + retries + 1,
            "status": "graceful_fallback",
            "graceful_error": "文档渲染暂时不可用，请稍后重试。已生成的完整文本可在页面中查看。",
        }
