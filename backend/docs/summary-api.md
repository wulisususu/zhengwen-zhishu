# 提炼总结接口

`POST /api/v1/gov/summaries`，需要登录（角色入口的令牌即可）。实现在 `app/gov/summary.py`。

## 请求

```json
{ "fileIds": [12], "mode": "material" }
```

- `fileIds`：`/gov/materials` 上传后得到的材料 ID。本期只接受一份；多份返回 422「多材料综合尚未支持」。
- `mode`：`material`（单材料提炼）或 `meeting`（会议纪要提炼）。
- 支持 TXT、Markdown、DOCX、PDF（文本层，经 pdftotext）。扫描件不做文字识别，返回 422。
- 材料文字超过 40000 字返回 422，不截断。

## 处理

1. 材料按页、按段切成编号片段 `S1`、`S2`……，超过 400 字的段落按句切开。
2. 片段连同编号发给云端模型（与公文起草、政策问答同一套接口和出口策略），要求只输出 JSON，每条结论列出所依据的片段编号。
3. 逐条校验后返回：
   - 没有引用有效片段的条目剔除；
   - 条目里的数字没有出现在所引片段中的，剔除；
   - 会议任务的责任部门、时间要求不能在所引片段中找到原文的，置空并在 `notes` 中说明。

剔除的条目放在 `dropped` 里返回，前端如实展示。结果不入库。

## 响应 `data`

```json
{
  "origin": "backend",
  "mode": "meeting",
  "materials": [{ "fileId": "12", "fileName": "纪要.txt", "segments": 4 }],
  "sections": [
    { "key": "decisions", "label": "会议决议", "items": [{ "text": "同意启动自查", "sources": ["S2"], "notes": [] }] },
    { "key": "tasks", "label": "工作任务", "items": [
      { "text": "完成自查报告", "owner": "数据安全处", "deadline": "2025年11月30日前", "sources": ["S3"], "notes": [] }
    ] }
  ],
  "sources": { "S3": { "id": "S3", "fileId": "12", "fileName": "纪要.txt", "page": null, "paragraph": 3, "text": "由数据安全处牵头，于2025年11月30日前完成自查报告。" } },
  "dropped": [{ "section": "工作任务", "text": "编造的任务", "reason": "没有引用有效的原文片段" }],
  "generatedAt": "2026-10-26T12:00:00+00:00"
}
```

`material` 模式的分节为 `summary` 摘要、`keyData` 关键数据、`conclusions` 重要结论、`pending` 待确认事项。`sources` 只含被引用的片段；`page` 仅 PDF 有值。

## 错误

| 状态 | 情形 |
|---|---|
| 404 | 材料不存在或不属于当前用户 |
| 422 | 类型不支持、没有文字、超长、多份材料、编码不是 UTF-8 |
| 502 | 模型返回的内容无法解析为 JSON |
| 503 | 模型不可用或返回空内容；PDF 提取工具不可用 |
