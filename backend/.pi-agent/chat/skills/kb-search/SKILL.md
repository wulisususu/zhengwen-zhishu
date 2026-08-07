---
name: kb-search
description: 当用户要求基于知识库检索结果回答时，先调用内部知识库检索服务并返回 grounding 元数据。
metadata:
  openclaw:
    requires:
      env:
        - BACKEND_BASE_URL
        - BACKEND_SERVICE_TOKEN
---

# 知识库检索

当用户明确要求“根据知识库回答”“从知识库检索后回答”“带引用回答”时，必须先调用内部知识库服务：

- `POST {BACKEND_BASE_URL}/api/v1/internal/kb/search`
- Header: `Authorization: Bearer {BACKEND_SERVICE_TOKEN}`
- Body:

```json
{
  "query": "<检索问题>",
  "top_k": 5
}
```

响应体为统一结构，重点字段：

- `data.passages`
- `data.sources`

## 约束

- 没有调用 `kb_search` 前，不要声称答案来自知识库。
- 如果没有调用 `kb_search` 就直接回答，本次回答应视为无效。
- 如果 `data.sources` 为空，要明确说明“未命中知识库”。
- 回答时优先基于 `data.sources` 和 `data.passages`，不要编造引用。
