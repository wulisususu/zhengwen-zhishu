"""复测 2 / 3：用 InNet_box 现有的两条 DOCX 生成链路出同一份通知，产物写到 innet/。

Run from backend/: python tests/fixtures/gongwen/make_innet_samples.py   (needs python-docx)

- innet_01_markdown_to_docx.docx：app.services.markdown_to_docx.markdown_to_docx（markdown-first 主链路）
- innet_02_render_docx.docx：app.services.document_agent._render_docx（content_json 链路）

document_agent 在 import 时会 mkdir /home/youyeetoo/...，所以这里用 ast 只取出
_render_docx 与 _stringify 两个函数的源码执行，被测的仍是仓库里的原函数，不复制、不改写。
"""
import ast
import re
import sys
from pathlib import Path
from typing import Any

from docx import Document

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[2]
OUT = HERE / "innet"
sys.path.insert(0, str(BACKEND))

from app.services.markdown_to_docx import markdown_to_docx  # noqa: E402

MARKDOWN = """# 示例单位办公室关于开展公文格式规范培训工作的通知

各部门、各直属单位：

为规范公文格式，提高办文质量，现就开展公文格式规范培训有关事项通知如下。

## 一、培训任务

本次培训共 3 项任务：

1. 讲解公文版心与行字数要求
2. 讲解层次序数与成文日期写法
3. 组织常见格式差错案例研讨

## 二、参训人员

各部门负责公文处理工作的同志，名额分配如下：

| 部门 | 名额（人） |
| --- | --- |
| 综合处 | 12 |
| 业务处 | 8 |
| 财务处 | 5 |
| 合计 | 25 |

## 三、有关要求

各单位于 **2026年10月30日前** 将参训人员名单报送办公室文书科；培训具体时间、地点另行通知。

联系人：×××，联系电话：×××-××××××××。

示例单位办公室

2026年10月26日
"""

CONTENT_JSON = {
    "title": "示例单位办公室关于开展公文格式规范培训工作的通知",
    "summary": "各部门、各直属单位：为规范公文格式，提高办文质量，现就开展公文格式规范培训有关事项通知如下。",
    "sections": [
        {"heading": "一、培训任务", "content": "本次培训共 3 项任务：讲解公文版心与行字数要求；讲解层次序数与成文日期写法；组织常见格式差错案例研讨。"},
        {"heading": "二、参训人员", "content": "各部门负责公文处理工作的同志，名额分配见下表。"},
        {"heading": "三、有关要求", "content": "各单位于 2026年10月30日前将参训人员名单报送办公室文书科；培训具体时间、地点另行通知。\n\n联系人：×××，联系电话：×××-××××××××。\n\n示例单位办公室\n\n2026年10月26日"},
    ],
    "tables": [{"title": "参训名额", "headers": ["部门", "名额（人）"],
                "rows": [["综合处", 12], ["业务处", 8], ["财务处", 5], ["合计", 25]]}],
}


def load_render_docx():
    source = (BACKEND / "app" / "services" / "document_agent.py").read_text(encoding="utf-8")
    wanted = {"_render_docx", "_stringify"}
    nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name in wanted]
    assert {n.name for n in nodes} == wanted, "document_agent._render_docx/_stringify not found"
    namespace = {"Document": Document, "re": re, "Any": Any, "Path": Path, "json": __import__("json")}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), "document_agent.py", "exec"), namespace)
    return namespace["_render_docx"]


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    markdown_to_docx(MARKDOWN, OUT / "innet_01_markdown_to_docx.docx")
    load_render_docx()(CONTENT_JSON, OUT / "innet_02_render_docx.docx")
