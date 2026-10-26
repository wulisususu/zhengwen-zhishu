"""Render the compliant sample ok_03_markdown_to_docx.docx with the backend's own renderer.

Run from backend/: python tests/fixtures/gongwen/make_md_sample.py
Only calls app.services.markdown_to_docx.markdown_to_docx (python-docx); does not change it.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[2]))

from app.services.markdown_to_docx import markdown_to_docx  # noqa: E402

MARKDOWN = """# 示例单位办公室关于开展公文格式规范培训工作的通知

各部门、各直属单位：

为规范公文格式，提高办文质量，现就开展公文格式规范培训有关事项通知如下。

## 一、培训任务

本次培训共 3 项任务：

### （一）讲解公文版心与行字数要求

### （二）讲解层次序数与成文日期写法

### （三）组织常见格式差错案例研讨

## 二、参训人员

各部门负责公文处理工作的同志，每单位 1 至 2 人。

## 三、有关要求

各单位于 2026年10月30日前将参训人员名单报送办公室文书科；培训具体时间、地点另行通知。

联系人：×××，联系电话：×××-××××××××。

示例单位办公室

2026年10月26日
"""

if __name__ == "__main__":
    markdown_to_docx(MARKDOWN, HERE / "ok_03_markdown_to_docx.docx")
