# 0.6B 大纲 + 3B 正文生成 8000 字文档尝试方案

## 目标

在 RK3588 + Qwen2.5-3B RKLLM 存在 NPU IOVA 空间限制的前提下，尽力完成约 8000 字文档生成。

本方案不假设 3B 可以连续稳定推理 8 次，而是采用“单章生成、即时保存、失败可续跑”的方式，把一次高风险长任务拆成多个可恢复的小任务。

## 核心原则

```text
0.6B：生成 8 章大纲
3B：一次只生成 1 章正文
每章成功后立即保存
每章后重启 3B 服务
失败后从失败章节继续
```

## 模型分工

### 0.6B 模型

用于生成大纲。

要求：

- 默认生成 8 章。
- 只输出 JSON。
- 不写正文。
- 不编造具体数字、政策、人名、机构名。

大纲格式：

```json
{
  "title": "文档标题",
  "sections": [
    {
      "heading": "第一章 章节标题",
      "key_points": "本章核心观点"
    }
  ],
  "summary": "一句话概括"
}
```

### 3B 模型

用于逐章生成正文。

要求：

- 每次只写 1 章。
- 每章目标 900-1100 中文字。
- 8 章合计约 7200-8800 字。
- 不允许一次性生成全文。
- 每章生成完成后必须保存结果。

## 任务目录结构

建议为每次文档生成创建独立任务目录：

```text
/tmp/docs_pipeline_runs/{task_id}/
├── outline.json
├── state.json
├── sections/
│   ├── 01.md
│   ├── 02.md
│   ├── 03.md
│   └── ...
└── final.md
```

## 状态文件

`state.json` 用于断点续跑。

示例：

```json
{
  "task_id": "20260629_xxxxx",
  "status": "running",
  "title": "文档标题",
  "total_sections": 8,
  "next_section": 4,
  "completed_sections": [1, 2, 3],
  "failed_section": null,
  "error": null
}
```

失败时：

```json
{
  "task_id": "20260629_xxxxx",
  "status": "failed",
  "title": "文档标题",
  "total_sections": 8,
  "next_section": 4,
  "completed_sections": [1, 2, 3],
  "failed_section": 4,
  "error": "3B unavailable"
}
```

## 生成流程

1. 用户输入文档主题。
2. 调用 0.6B 生成 8 章大纲。
3. 保存 `outline.json`。
4. 初始化 `state.json`。
5. 从第 1 章开始调用 3B。
6. 每章生成成功后保存到 `sections/{index}.md`。
7. 对章节内容执行幻觉风险扫描。
8. 更新 `state.json`。
9. 重启 3B 服务并等待恢复。
10. 继续下一章。
11. 8 章全部完成后组装 `final.md` 和 DOCX。

## 3B 单章 Prompt 模板

```text
你只写当前这一章，不写其他章节。

报告主题：{topic}
全文共 8 章
当前章节：第 {index}/8 章
章节标题：{heading}
核心观点：{key_points}

硬性要求：
1. 本章 900-1100 中文字。
2. 不得编造具体数字、百分比、年份、政策文件名、机构名、人名、引用来源。
3. 没有依据时写“暂无确切数据”或“需结合正式资料进一步核实”。
4. 使用审慎表达，例如“通常”“可考虑”“建议”“需要结合实际情况”。
5. 输出 Markdown。
6. 使用 3-4 个三级标题，格式为：### {index}.1 标题。
7. 只输出本章正文，不输出解释。
```

## 幻觉降低策略

第一版先做硬规则扫描，不引入复杂 RAG。

章节生成后扫描以下高风险内容：

- 数字：百分比、金额、数量、年份。
- 引用表达：`数据显示`、`研究表明`、`根据某报告`。
- 政策表达：`规划纲要`、`白皮书`、`指导意见`。
- 机构表达：未由用户提供的政府部门、企业、研究机构。

如果用户没有提供明确资料来源，高风险句子改写为审慎表达。

示例：

```text
原句：
根据某某报告，市场规模将在2025年达到100亿元。

改写：
相关市场规模仍需结合正式统计资料进一步核实，本文不作具体数值判断。
```

## 失败处理

建议规则：

```text
每章最多尝试 1 次
失败后重启 3B
同一章失败则停止任务
保留已完成章节
下一次从失败章节继续
```

不要在同一轮中反复重试。重试越多，NPU IOVA 碎片化风险越高。

## 3B 重启策略

比“每 3 次重启”更保守：

```text
每生成 1 章后重启 3B 服务
等待 45 秒
检查 8093 是否恢复
恢复后继续下一章
```

## 建议默认参数

```text
默认章节数：8
每章字数：900-1100
3B max_tokens：1536 或 1792
temperature：0.1
单章超时：300 秒
每章后重启：是
重启等待：45 秒
单章重试：1 次
连续失败：停止并保留进度
正文 fallback 到 0.6B：否
```

## 伪代码

```python
def run_long_doc_pipeline(topic):
    task = load_or_create_task(topic)

    if not task.outline_exists():
        outline = call_06b_outline(topic, section_count=8)
        task.save_outline(outline)

    for section in task.remaining_sections():
        try:
            content = call_3b_one_section(section)
            content = hallucination_guard(content)
            task.save_section(section.index, content)
            task.mark_completed(section.index)
        except Exception as exc:
            restart_3b()
            task.mark_failed(section.index, str(exc))
            return task.partial_result()

        restart_3b()
        wait_until_3b_ready(timeout=120)

    return task.render_docx()
```

## 预期结果

理想情况：

```text
0.6B 生成大纲成功
3B 分 8 次完成正文
每章后重启
最终输出约 8000 字 DOCX
```

现实情况：

```text
一次完成 2-4 章
3B 服务崩溃或 NPU 分配失败
已完成章节保留
重启后从失败章节继续
分多轮完成 8 章
```

## 结论

在当前硬件限制下，3B 连续完成 8000 字长文生成并不可靠。最可尝试的方式是将 3B 限制为“单章生成器”，并通过断点保存、每章重启、失败续跑来提高最终完成概率。

该方案牺牲速度，但最大限度保留 3B 正文质量，同时避免一次失败导致整篇文档报废。
