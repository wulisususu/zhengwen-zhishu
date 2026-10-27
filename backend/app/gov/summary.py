"""提炼总结：单份材料提炼与会议纪要提炼，每条结论都要对应原文片段。

POST /gov/summaries {fileIds: [id], mode: "material" | "meeting"}

材料按页、按段切成编号片段（S1、S2…），模型只能引用这些编号。返回前逐条校验：
- 引用的片段必须存在，没有有效引用的条目剔除；
- 条目里的数字必须出现在所引片段中，否则剔除（不让模型编造数据）；
- 会议任务的责任部门、时间要求必须能在所引片段中找到原文，否则置空并注明。
剔除的条目连同原因一并返回，前端如实展示，不悄悄丢弃。结果不入库。
"""
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.models import File

MAX_BYTES = 20 * 1024 * 1024
MAX_CHARS = 40000
MAX_SEGMENT_CHARS = 400
MAX_ITEMS = 12
TEXT_TYPES = {".txt", ".md"}
SUPPORTED = TEXT_TYPES | {".docx", ".pdf"}

SECTIONS = {
    "material": [("summary", "摘要"), ("keyData", "关键数据"), ("conclusions", "重要结论"), ("pending", "待确认事项")],
    "meeting": [("decisions", "会议决议"), ("tasks", "工作任务")],
}

SYSTEM_PROMPT = (
    "你负责从政务材料中提炼要点。只能依据给出的原文片段，每条结论都必须在 sources 中列出所依据的片段编号（如 S3）。"
    "不得编造数字、日期、部门或政策依据；原文没有的内容不要写。只输出一个 JSON 对象，不要输出其他文字。"
)

MODE_PROMPTS = {
    "material": (
        "请提炼这份材料，输出 JSON：\n"
        '{"summary":[{"text":"…","sources":["S1"]}],"keyData":[…],"conclusions":[…],"pending":[…]}\n'
        "summary：3 至 5 条概括；keyData：原文中的关键数字、日期、范围，数字照抄原文；"
        "conclusions：材料明确提出的结论、要求或决定；pending：原文表述不明确、相互矛盾或需要人工确认的事项。"
    ),
    "meeting": (
        "这是一份会议记录或纪要，请提炼，输出 JSON：\n"
        '{"decisions":[{"text":"…","sources":["S1"]}],"tasks":[{"task":"…","owner":"…","deadline":"…","sources":["S2"]}]}\n'
        "decisions：会议形成的决议或议定事项；tasks：分配的工作任务。"
        "owner 和 deadline 必须照抄原文中的责任部门（或责任人）和时间要求，原文没有写明就填空字符串。"
    ),
}


class SummaryRequest(BaseModel):
    fileIds: list[int] = Field(min_length=1)
    mode: Literal["material", "meeting"] = "material"


def call_model(messages: list[dict[str, str]]) -> str:
    """Same cloud API, configuration and egress check as drafting and policy QA."""
    from app.services import llm_chat
    from app.services.llm_client import _clean_model_text
    return _clean_model_text(llm_chat.chat(messages, max_tokens=4096, temperature=0.1, timeout=120))


# ---------- 材料读取与切分 ----------

def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_SEGMENT_CHARS:
        return [text]
    parts, current = [], ""
    for sentence in re.split(r"(?<=[。；！？])", text):
        if current and len(current) + len(sentence) > MAX_SEGMENT_CHARS:
            parts.append(current)
            current = ""
        current += sentence
        while len(current) > MAX_SEGMENT_CHARS:
            parts.append(current[:MAX_SEGMENT_CHARS])
            current = current[MAX_SEGMENT_CHARS:]
    if current:
        parts.append(current)
    return parts


def _pdf_pages(path: str) -> list[str]:
    try:
        run = subprocess.run(["pdftotext", "-layout", path, "-"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        raise HTTPException(503, "PDF 文本提取工具不可用，无法读取该材料")
    return re.split(r"\f", run.stdout or "")


def _join_pdf_block(block: str) -> str:
    # pdftotext 按版面断行：中文行之间直接相连，英文与数字之间留一个空格
    lines = [line.strip() for line in block.splitlines() if line.strip()]
    text = ""
    for line in lines:
        if text and re.match(r"[A-Za-z0-9]", line) and re.search(r"[A-Za-z0-9]$", text):
            text += " "
        text += re.sub(r"\s{2,}", " ", line)
    return text


def read_units(file: File) -> list[tuple[int | None, str]]:
    """Return (page, paragraph text) in reading order. page is None for formats without pages."""
    ext = (file.filetype or Path(file.filename or "").suffix).lower()
    path = Path(file.filepath)
    if ext not in SUPPORTED:
        raise HTTPException(422, f"提炼总结暂支持 TXT、Markdown、DOCX、PDF，不支持 {ext or '该类型'}")
    if not path.is_file():
        raise HTTPException(404, "材料文件不存在")
    if path.stat().st_size > MAX_BYTES:
        raise HTTPException(422, "材料超过 20MiB，请拆分后再提炼")
    if ext in TEXT_TYPES:
        try:
            text = path.read_bytes().decode("utf-8-sig")
        except UnicodeError:
            raise HTTPException(422, "材料无法按 UTF-8 读取，请转换编码后重试")
        return [(None, line.strip()) for line in text.splitlines() if line.strip()]
    if ext == ".docx":
        from docx import Document
        try:
            doc = Document(str(path))
        except Exception:
            raise HTTPException(422, "DOCX 材料无法打开，请确认文件未损坏")
        units = [(None, p.text.strip()) for p in doc.paragraphs if p.text.strip()]
        for table in doc.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    units.append((None, " | ".join(cells)))
        return units
    units = []
    for page, text in enumerate(_pdf_pages(str(path)), start=1):
        for block in re.split(r"\n\s*\n", text):
            joined = _join_pdf_block(block)
            if joined:
                units.append((page, joined))
    return units


def segment(files: list[File]) -> list[dict]:
    segments: list[dict] = []
    for file in files:
        paragraph = {}
        for page, text in read_units(file):
            for piece in _split_long(text):
                paragraph[page] = paragraph.get(page, 0) + 1
                segments.append({"id": f"S{len(segments) + 1}", "fileId": str(file.id), "fileName": file.filename,
                                 "page": page, "paragraph": paragraph[page], "text": piece})
    if not segments:
        raise HTTPException(422, "材料中没有提取到文字。扫描件需要先做文字识别，本功能不对图片做识别")
    if sum(len(s["text"]) for s in segments) > MAX_CHARS:
        raise HTTPException(422, f"材料文字超过 {MAX_CHARS} 字，请拆分后分别提炼；未截断材料")
    return segments


# ---------- 模型输出解析与出处校验 ----------

def parse_model_json(text: str) -> dict:
    start, end = text.find("{"), text.rfind("}")
    try:
        data = json.loads(text[start:end + 1]) if start >= 0 and end > start else None
    except json.JSONDecodeError:
        data = None
    if not isinstance(data, dict):
        raise HTTPException(502, "模型返回的格式无法解析，未生成提炼结果，请重试")
    return data


_FULLWIDTH = str.maketrans("０１２３４５６７８９．", "0123456789.")


def _plain(text: str) -> str:
    return re.sub(r"\s+", "", str(text).translate(_FULLWIDTH))


def _numbers(text: str) -> list[str]:
    return re.findall(r"\d+(?:\.\d+)?", _plain(text))


def check_item(raw, by_id: dict[str, dict], meeting_task: bool) -> tuple[dict | None, str]:
    """Return (item, "") when it passes, or (None, reason)."""
    if not isinstance(raw, dict):
        return None, "条目格式不正确"
    text = str(raw.get("task" if meeting_task else "text") or raw.get("text") or "").strip()
    if not text:
        return None, "条目内容为空"
    sources = [s for s in dict.fromkeys(str(s).strip().upper() for s in raw.get("sources") or []) if s in by_id]
    if not sources:
        return None, "没有引用有效的原文片段"
    cited = "".join(_plain(by_id[s]["text"]) for s in sources)
    for number in _numbers(text):
        if number not in cited:
            return None, f"数字「{number}」未出现在所引原文中"
    item = {"text": text[:500], "sources": sources, "notes": []}
    if meeting_task:
        for key, label in (("owner", "责任部门"), ("deadline", "时间要求")):
            value = str(raw.get(key) or "").strip()
            if value and _plain(value) not in cited:
                item["notes"].append(f"模型给出的{label}「{value}」未在所引原文中找到，已置空")
                value = ""
            item[key] = value
    return item, ""


def validate(data: dict, mode: str, segments: list[dict]) -> tuple[list[dict], list[dict]]:
    by_id = {s["id"]: s for s in segments}
    sections, dropped = [], []
    for key, label in SECTIONS[mode]:
        raw_items = data.get(key) if isinstance(data.get(key), list) else []
        items = []
        for raw in raw_items:
            item, reason = check_item(raw, by_id, meeting_task=(mode == "meeting" and key == "tasks"))
            if item is None:
                text = str((raw.get("task") or raw.get("text")) if isinstance(raw, dict) else raw)[:200]
                dropped.append({"section": label, "text": text, "reason": reason})
            elif len(items) < MAX_ITEMS:
                items.append(item)
        sections.append({"key": key, "label": label, "items": items})
    return sections, dropped


def summarize(db, user, body: SummaryRequest) -> dict:
    ids = list(dict.fromkeys(body.fileIds))
    if len(ids) > 1:
        raise HTTPException(422, "多材料综合尚未支持，请一次选择一份材料")
    files = db.query(File).filter(File.id.in_(ids), File.user_id == user.id).all()
    if len(files) != len(ids):
        raise HTTPException(404, "材料不存在或不属于当前用户")
    segments = segment(files)
    listing = "\n".join(
        f"[{s['id']}]（{'第%d页 ' % s['page'] if s['page'] else ''}第{s['paragraph']}段）{s['text']}" for s in segments)
    messages = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": f"{MODE_PROMPTS[body.mode]}\n\n材料《{files[0].filename}》原文片段：\n{listing}"}]
    try:
        reply = call_model(messages)
    except Exception:
        reply = ""
    if not reply.strip():
        raise HTTPException(503, "模型服务不可用或返回空内容，未生成提炼结果。请检查模型连接与出口策略")
    sections, dropped = validate(parse_model_json(reply), body.mode, segments)
    cited = {sid for section in sections for item in section["items"] for sid in item["sources"]}
    return {
        "origin": "backend",
        "mode": body.mode,
        "materials": [{"fileId": str(f.id), "fileName": f.filename,
                       "segments": sum(1 for s in segments if s["fileId"] == str(f.id))} for f in files],
        "sections": sections,
        "sources": {s["id"]: s for s in segments if s["id"] in cited},
        "dropped": dropped,
        "generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
