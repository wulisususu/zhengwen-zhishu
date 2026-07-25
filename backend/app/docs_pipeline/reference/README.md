# 文档模板目录

此目录用于存放 DOCX 文档模板文件。

## 规划中的模板

| 模板文件 | 用途 | 引擎 |
|----------|------|------|
| `official_report.docx` | 公文/正式报告 | python-docx |
| `weekly_report.docx` | 周报 | docxtpl |
| `resume.docx` | 简历 | docxtpl |
| `simple_report.docx` | 普通报告 | docxtpl |

## 模板规范

- docxtpl 模板使用 Jinja2 占位符：`{{ field_name }}`
- python-docx 模板使用标记段落 + 程序化替换
- 公文格式参考 GB/T 9704-2012

> 注意：此目录暂不启用，模板文件待后续开发。
