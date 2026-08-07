"""
docs_pipeline core v2 — 完全按照 3b_8000_doc_attempt_plan.md 实现

0.6B 大纲 + 3B 逐章正文 + 每章后重启 3B + 幻觉扫描 + 断点续跑。
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from jsonschema import validate, ValidationError

from app.services.markdown_to_docx import markdown_to_docx
from app.services.document_agent import _parse_json_object
from app.services.document_service import DOC_OUTPUT_DIR, ensure_default_templates

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════════════

PIPELINE_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = PIPELINE_DIR / "prompts"
SCHEMAS_DIR = PIPELINE_DIR / "schemas"
RUNS_DIR = Path("/tmp/docs_pipeline_runs")

# 模型端点：文档降级流水线只使用当前统一管理的 3B 服务。
# 保留环境变量入口，便于后续将 3B 移到内网独立主机。
GEN_BASE_URL = os.getenv("DOC_PIPELINE_3B_BASE_URL", "http://127.0.0.1:8004").rstrip("/")
GEN_URL = GEN_BASE_URL + "/v1/chat/completions"
GEN_HEALTH_URL = GEN_BASE_URL + "/health"
GEN_MODEL = "Qwen2.5-3B-Instruct"
RESTART_SCRIPT = "/home/youyeetoo/InNet_box/restart_backend.sh"
# Compatibility exports for legacy helpers. The active nodes do not call
# generate_outline/_fallback_section_06b, so docs_pipeline remains 3B-only.
ROUTER_URL = os.getenv("LEGACY_ROUTER_URL", "http://127.0.0.1:8002/v1/chat/completions")
ROUTER_MODEL = "Qwen3-0.6B-Q4_K_M.gguf"

# 默认参数（来自 plan.md）
DEFAULT_SECTION_COUNT = 6
DEFAULT_WORDS_PER_SECTION = (1200, 1500)
RESTART_WAIT_SECONDS = 60
MAX_RETRY_PER_SECTION = 10
GEN_TIMEOUT_SECONDS = 600
GEN_MAX_TOKENS = 1792
GEN_TEMPERATURE = 0.1


# ══════════════════════════════════════════════════════════════════════
# Prompt 加载（从文件，0 硬编码）
# ══════════════════════════════════════════════════════════════════════

def _read_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    if text.startswith("---"):
        parts = text.split("---", 2)
        text = parts[2] if len(parts) >= 3 else text
    return text.strip()


def load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    if path.exists():
        return _read_file(path)
    logger.warning("Prompt file %s not found", path)
    return ""


# ══════════════════════════════════════════════════════════════════════
# 0.6B 大纲生成
# ══════════════════════════════════════════════════════════════════════

OUTLINE_SYSTEM = """你是严谨的报告大纲规划师。只规划章节结构，不写正文。

规则：
1. 生成恰好 {section_count} 章
2. 只使用公认的、可查证的知识
3. 不确定的信息标注"[待核实]"
4. 禁止编造具体人名、数字、日期、政策名、机构名
5. 每章给出 1-2 句核心观点
6. 章节标题必须根据用户主题内容自主规划，反映具体内容，禁止使用泛泛的模板标签（如"项目背景""总体目标""核心内容""实施路径""保障措施""预期成效"等）

输出 JSON 格式：
{{"title":"","sections":[{{"heading":"第X章 具体内容标题","key_points":"核心观点"}}],"summary":""}}

章节标题要求：从用户主题出发自然递进，例如分析类主题按"定义→现状→原因→方案→风险"，规划类主题按"需求→目标→策略→计划→保障"，具体取决于主题内容。
只输出 JSON。"""


def generate_outline(topic: str, section_count: int = DEFAULT_SECTION_COUNT) -> dict:
    system = OUTLINE_SYSTEM.format(section_count=section_count)
    user = f"主题：{topic}\n请生成 {section_count} 章大纲。"

    for attempt in range(2):
        try:
            resp = requests.post(ROUTER_URL, json={
                "model": ROUTER_MODEL,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": 512,
                "temperature": 0.1,
                "stop": ["\n\n\n"],
                "stream": False,
            }, timeout=30)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
            outline = _parse_json_object(raw)
            secs = outline.get("sections", [])
            if isinstance(secs, list) and len(secs) >= 3:
                logger.info("0.6B outline: %d sections", len(secs))
                return outline
            logger.warning("0.6B outline too short (%d), retry %d", len(secs), attempt + 1)
        except Exception as e:
            logger.error("0.6B outline error: %s", e)
            if attempt == 1:
                raise
    return _fallback_outline(topic, section_count)


def _fallback_outline(topic: str, n: int) -> dict:
    # 截取短标题，避免完整题目嵌到每个章节标题里
    short = topic[:60].strip()
    # 去掉常见前缀后缀，缩到 8 字以内
    short = re.sub(r"关于|相结合?|的.*规划|未来.*规划|公司", "", short)
    short = short.strip()[:8] or topic[:8]

    templates = [
        ("背景与意义", f"阐述{short}的背景和重要性"),
        ("现状分析", f"分析{short}当前面临的情况"),
        ("面临的机遇与挑战", f"识别{short}的机遇和挑战"),
        ("核心策略与方案", f"提出{short}的核心方案"),
        ("实施路径与步骤", f"规划{short}的落地步骤"),
        ("资源配置与保障", f"明确{short}所需资源和保障"),
        ("风险识别与应对", f"分析{short}的潜在风险和应对"),
        ("总结与展望", f"总结并展望{short}的未来"),
    ]
    return {
        "title": topic[:60],
        "sections": [
            {"heading": f"第{i+1}章 {h}", "key_points": k}
            for i, (h, k) in enumerate(templates[:n])
        ],
        "summary": f"关于{topic[:60]}的综合分析报告",
    }


# ══════════════════════════════════════════════════════════════════════
# 3B 单章生成
# ══════════════════════════════════════════════════════════════════════

SECTION_SYSTEM = """你只写当前这一章，不写其他章节。

报告主题：{topic}
全文共 {total} 章
当前章节：第 {index}/{total} 章
章节标题：{heading}
核心观点：{key_points}

硬性要求：
1. 本章 {min_words}-{max_words} 中文字。
2. 不得编造具体数字、百分比、年份、政策文件名、机构名、人名、引用来源。
3. 没有依据时写"暂无确切数据"或"需结合正式资料进一步核实"。
4. 使用审慎表达，例如"通常""可考虑""建议""需要结合实际情况"。
5. 输出 Markdown。
6. 使用 3-4 个三级标题，格式为：### {index}.1 标题。
7. 只输出本章正文，不输出解释。"""


def generate_section(
    topic: str,
    index: int,
    total: int,
    heading: str,
    key_points: str,
    min_words: int = DEFAULT_WORDS_PER_SECTION[0],
    max_words: int = DEFAULT_WORDS_PER_SECTION[1],
) -> str:
    system = SECTION_SYSTEM.format(
        topic=topic, total=total, index=index, heading=heading,
        key_points=key_points, min_words=min_words, max_words=max_words,
    )
    user = f"请输出第 {index} 章正文（{min_words}-{max_words}字）："

    resp = requests.post(GEN_URL, json={
        "model": GEN_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "max_tokens": GEN_MAX_TOKENS,
        "temperature": GEN_TEMPERATURE,
        "stream": False,
    }, timeout=GEN_TIMEOUT_SECONDS)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["choices"][0]["message"]["content"].strip()


# ══════════════════════════════════════════════════════════════════════
# 幻觉扫描 + 改写
# ══════════════════════════════════════════════════════════════════════

# 高风险模式
HALLUCINATION_PATTERNS = [
    # 数字类
    (r'\d+\.?\d*\s*%', '百分比'),
    (r'\d+\.?\d*\s*亿[元美元]', '金额'),
    (r'\d+\.?\d*\s*万[元美元吨亩]', '数量'),
    (r'\d{4}\s*年', '年份'),
    (r'(?:约|大约|预计|达到|超过)\s*\d+', '估算数字'),
    # 引用类
    (r'(?:根据|据|按照)\s*[^，。,.\n]{3,30}?(?:报告|数据|统计|研究|调查)', '引用来源'),
    (r'(?:显示|表明|指出)\s*[^，。,.\n]*?\d', '数据声称'),
    # 政策类
    (r'(?:规划纲要|白皮书|指导意见|实施方案|行动计划|若干意见)', '政策文件'),
    (r'《[^》]{3,40}》', '文件/报告名'),
    # 机构类
    (r'(?:国家|中国|省|市|区|县)[^，。,.\n]{2,20}(?:部|委|局|厅|办|中心|协会|研究院)', '机构名'),
    (r'(?:公司|集团|企业)[^，。,.\n]{0,10}(?:有限公司|股份有限公司)', '企业名'),
    # 专项资金声称（高度危险）
    (r'(?:设立|划拨|安排)\s*(?:专项基金|专项资金|产业基金)', '专项资金声称'),
    # 扶持政策声称（高度危险）
    (r'申请\s*.{2,10}(?:扶持资金|补贴|税收减免)', '政策扶持声称'),
]

REWRITE_HINT = """[审核标记：原文含高风险内容（{risk_type}），建议改为审慎表达。
原表述："{matched}"
建议：所涉数据与结论建议结合正式资料进一步核实，本段不作具体数值判断。]"""


def _hallucination_scan(content: str) -> list[dict]:
    """Scan content for hallucination risks. Returns list of findings."""
    findings = []
    for pattern, risk_type in HALLUCINATION_PATTERNS:
        for m in re.finditer(pattern, content):
            findings.append({
                "risk_type": risk_type,
                "matched": m.group(),
                "start": m.start(),
                "end": m.end(),
            })
    return findings


def _rewrite_risky_content(content: str, findings: list[dict]) -> str:
    """Replace risky spans with rewrite hints. Keeps original content intact
    but inserts warning markers. Does NOT remove the original text, only flags it."""
    if not findings:
        return content

    # Sort by position, process from end to start to preserve indices
    findings.sort(key=lambda f: f["start"], reverse=True)
    result = content

    for f in findings:
        hint = REWRITE_HINT.format(risk_type=f["risk_type"], matched=f["matched"])
        # Wrap risky span with warning
        result = result[:f["end"]] + "\n" + hint + "\n" + result[f["end"]:]

    return result


def _hallucination_guard(content: str) -> dict:
    """Full guard: scan + produce report. Returns {content, findings, risk_level}."""
    findings = _hallucination_scan(content)
    risk_level = "none"
    if len(findings) >= 8:
        risk_level = "high"
    elif len(findings) >= 4:
        risk_level = "medium"
    elif len(findings) >= 1:
        risk_level = "low"

    if risk_level in ("medium", "high"):
        logger.warning("Hallucination risk: %s (%d findings)", risk_level, len(findings))

    return {"content": content, "findings": findings, "risk_level": risk_level}


# ══════════════════════════════════════════════════════════════════════
# 3B 服务管理
# ══════════════════════════════════════════════════════════════════════

def _restart_3b() -> bool:
    """Restart 3B server via watchdog. Returns True if successful."""
    logger.info("Restarting 3B server...")
    try:
        subprocess.run([RESTART_SCRIPT, "--3b"], capture_output=True, timeout=150)
    except Exception as e:
        logger.error("Watchdog failed: %s", e)
        return False

    # Wait for health
    for _ in range(RESTART_WAIT_SECONDS // 2):
        try:
            resp = requests.get(GEN_HEALTH_URL, timeout=5)
            if resp.status_code == 200:
                logger.info("3B server ready")
                return True
        except Exception:
            pass
        time.sleep(2)

    logger.error("3B server did not become ready within %ds", RESTART_WAIT_SECONDS)
    return False


def _is_3b_ready() -> bool:
    try:
        resp = requests.get(GEN_HEALTH_URL, timeout=3)
        return resp.status_code == 200
    except Exception:
        return False


# ══════════════════════════════════════════════════════════════════════
# 任务状态管理
# ══════════════════════════════════════════════════════════════════════

class TaskState:
    """Manages task directory, state.json, and section files."""

    def __init__(self, task_id: str | None = None):
        self.task_id = task_id or datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
        self.dir = RUNS_DIR / self.task_id
        self.sections_dir = self.dir / "sections"
        self.state_path = self.dir / "state.json"
        self.outline_path = self.dir / "outline.json"
        self.final_path = self.dir / "final.md"

    def init(self, topic: str) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        self.sections_dir.mkdir(exist_ok=True)
        self._write_state({
            "task_id": self.task_id,
            "status": "initialized",
            "topic": topic,
            "title": "",
            "total_sections": 0,
            "next_section": 1,
            "completed_sections": [],
            "failed_section": None,
            "error": None,
            "created_at": datetime.now().isoformat(),
        })

    def save_outline(self, outline: dict) -> None:
        self.outline_path.write_text(json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8")
        state = self._read_state()
        state["title"] = outline.get("title", "")
        state["total_sections"] = len(outline.get("sections", []))
        state["status"] = "outline_ready"
        self._write_state(state)

    def outline_exists(self) -> bool:
        return self.outline_path.exists()

    def load_outline(self) -> dict:
        return json.loads(self.outline_path.read_text(encoding="utf-8"))

    def remaining_sections(self) -> list[dict]:
        """Return sections not yet completed, in order."""
        if not self.outline_exists():
            return []
        outline = self.load_outline()
        state = self._read_state()
        completed = set(state.get("completed_sections", []))
        return [
            (i, sec) for i, sec in enumerate(outline["sections"], 1)
            if i not in completed
        ]

    def save_section(self, index: int, content: str) -> None:
        path = self.sections_dir / f"{index:02d}.md"
        path.write_text(content, encoding="utf-8")
        logger.info("Section %d saved: %d chars", index, len(content))

    def mark_completed(self, index: int) -> None:
        state = self._read_state()
        completed = state.get("completed_sections", [])
        if index not in completed:
            completed.append(index)
            completed.sort()
        state["completed_sections"] = completed
        state["next_section"] = max(completed) + 1 if len(completed) < state["total_sections"] else state["total_sections"] + 1
        if len(completed) >= state["total_sections"]:
            state["status"] = "all_sections_done"
        else:
            state["status"] = "running"
        state["failed_section"] = None
        state["error"] = None
        self._write_state(state)

    def mark_failed(self, index: int, error: str) -> None:
        state = self._read_state()
        state["status"] = "failed"
        state["failed_section"] = index
        state["error"] = error
        self._write_state(state)

    def mark_done(self) -> None:
        state = self._read_state()
        state["status"] = "done"
        self._write_state(state)

    def get_state(self) -> dict:
        return self._read_state()

    def assemble_final_md(self) -> str:
        outline = self.load_outline()
        state = self._read_state()
        lines = [f"# {state['title']}\n"]
        for i, sec in enumerate(outline["sections"], 1):
            heading = sec["heading"]
            lines.append(f"## {heading}\n")
            section_path = self.sections_dir / f"{i:02d}.md"
            if section_path.exists():
                lines.append(section_path.read_text(encoding="utf-8"))
            else:
                lines.append(f"[本章未生成]")
            lines.append("")
        return "\n".join(lines)

    def _read_state(self) -> dict:
        if self.state_path.exists():
            return json.loads(self.state_path.read_text(encoding="utf-8"))
        return {}

    def _write_state(self, state: dict) -> None:
        state["updated_at"] = datetime.now().isoformat()
        self.state_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


# ══════════════════════════════════════════════════════════════════════
# 主 Pipeline
# ══════════════════════════════════════════════════════════════════════

def run_pipeline(
    prompt: str,
    progress_callback=None,
    section_count: int = DEFAULT_SECTION_COUNT,
    task_id: str | None = None,
) -> dict:
    """主入口：0.6B 大纲 + 3B 逐章 + 每章重启 + 幻觉扫描 + 断点续跑。

    Args:
        prompt: 文档主题
        progress_callback: callable({phase, message, index, total, ...})
        section_count: 章节数，默认 8
        task_id: 续跑任务 ID，为 None 则新建

    Returns:
        {task_id, content_schema, total_chars, section_count, filename, filepath, filesize, state}
    """
    task = TaskState(task_id)

    # ── 初始化或续跑 ──
    if task.outline_exists():
        outline = task.load_outline()
        logger.info("Resuming task %s", task.task_id)
    else:
        task.init(prompt)
        if progress_callback:
            progress_callback({"phase": "outline", "message": f"0.6B 生成 {section_count} 章大纲..."})
        outline = generate_outline(prompt, section_count)
        task.save_outline(outline)
        logger.info("Task %s: outline ready, %d sections", task.task_id, len(outline["sections"]))

    state = task.get_state()
    title = state.get("title", "")
    total = state.get("total_sections", 0)

    # ── 首章前强制重启，确保 NPU 干净 ──
    if progress_callback:
        progress_callback({"phase": "restart", "message": "启动 3B 服务..."})
    _restart_3b()

    # ── 逐章生成 ──
    remaining = task.remaining_sections()
    if progress_callback and remaining:
        progress_callback({
            "phase": "generate", "index": remaining[0][0] - 1, "total": total,
            "message": f"续跑模式：{len(remaining)} 章待生成",
        })

    for index, sec in remaining:
        heading = sec["heading"]
        key_points = sec.get("key_points", "")

        if progress_callback:
            progress_callback({
                "phase": "generate", "index": index, "total": total,
                "heading": heading,
                "message": f"3B 生成第 {index}/{total} 章：{heading}",
            })

        # 生成
        try:
            content = generate_section(
                topic=prompt, index=index, total=total,
                heading=heading, key_points=key_points,
            )
        except Exception as e:
            logger.error("Section %d generation failed: %s", index, e)
            task.mark_failed(index, str(e))
            if progress_callback:
                progress_callback({
                    "phase": "generate", "index": index, "total": total,
                    "heading": heading,
                    "message": f"第 {index} 章失败: {e}",
                })
            break

        # 幻觉扫描
        guard_result = _hallucination_guard(content)
        content = guard_result["content"]

        # 保存
        task.save_section(index, content)
        task.mark_completed(index)

        if progress_callback:
            progress_callback({
                "phase": "generate", "index": index, "total": total,
                "heading": heading,
                "message": f"完成第 {index}/{total} 章 ({len(content)}字, 幻觉风险:{guard_result['risk_level']})",
                "sections": _build_progress_sections(task, index),
            })

        # 每章后重启 3B（除了最后一章）
        if index < total:
            if progress_callback:
                progress_callback({"phase": "restart", "message": f"重启 3B 服务（等待 {RESTART_WAIT_SECONDS}s）..."})
            _restart_3b()

    # ── 组装 + 渲染 ──
    final_state = task.get_state()
    completed = final_state.get("completed_sections", [])

    if progress_callback:
        progress_callback({
            "phase": "rendering",
            "message": f"组装 {len(completed)}/{total} 章，渲染 DOCX...",
        })

    final_md = task.assemble_final_md()
    task.final_path.write_text(final_md, encoding="utf-8")
    task.mark_done()

    # 渲染
    from app.services.document_service import DOC_OUTPUT_DIR, ensure_default_templates
    ensure_default_templates()
    title_clean = re.sub(r'[^0-9A-Za-z一-鿿_-]+', '_', title).strip('_')[:48] or "document"
    filename = f"{title_clean}.docx"
    filepath = str(DOC_OUTPUT_DIR / f"{task.task_id}.docx")

    markdown_to_docx(final_md, filepath, title=title)
    filesize = Path(filepath).stat().st_size

    total_chars = 0
    for i in completed:
        p = task.sections_dir / f"{i:02d}.md"
        if p.exists():
            total_chars += len(p.read_text(encoding="utf-8"))

    # Build content_schema from saved sections
    outline = task.load_outline()
    sections_out = []
    for i, sec in enumerate(outline["sections"], 1):
        sp = task.sections_dir / f"{i:02d}.md"
        sections_out.append({
            "heading": sec["heading"],
            "content": sp.read_text(encoding="utf-8") if sp.exists() else "[未生成]",
        })

    logger.info("Pipeline done: %d/%d chapters, %d chars, %s",
                len(completed), total, total_chars, filename)

    return {
        "task_id": task.task_id,
        "content_schema": {"title": title, "sections": sections_out, "summary": outline.get("summary", "")},
        "total_chars": total_chars,
        "section_count": len(completed),
        "total_sections": total,
        "filename": filename,
        "filepath": filepath,
        "filesize": filesize,
        "state": final_state,
    }


def _build_progress_sections(task: TaskState, up_to: int) -> list[dict]:
    """Build progress-friendly section summaries for frontend display."""
    result = []
    for i in range(1, up_to + 1):
        path = task.sections_dir / f"{i:02d}.md"
        if path.exists():
            content = path.read_text(encoding="utf-8")
            result.append({"heading": f"第{i}章", "content": content})
    return result
