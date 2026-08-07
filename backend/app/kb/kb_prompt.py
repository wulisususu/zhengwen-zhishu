"""Prompt builder for knowledge-base-augmented chat.

Builds a structured prompt with explicit source markers so the model can
reliably cite specific chunks. Does NOT reuse the attachment-context prompt
builder (_build_qwen_context_prompt) — that one assumes a single source and
has no concept of chunk IDs or relevance scores.
"""


def build_kb_prompt(question: str, chunks: list[dict], grounded: bool) -> str:
    """Build prompt for KB-augmented generation.

    Args:
        question: The user's original or condensed query.
        chunks: List of dicts with keys: chunk_text, filename, score, chunk_id.
        grounded: Whether KB retrieval returned relevant results.

    Returns:
        Prompt string to pass to the LLM.
    """
    if not grounded or not chunks:
        return _build_no_ground_prompt(question)

    source_lines = []
    for i, chunk in enumerate(chunks, 1):
        filename = chunk.get('filename', '未知文件')
        score = chunk.get('score', 0)
        text = (chunk.get('chunk_text', '') or '').strip()
        source_lines.append(
            f'[来源{i}: {filename} | 相关度: {score:.2f}]\n{text}'
        )

    sources_block = '\n\n'.join(source_lines)

    return (
        '你是一个基于档案资料回答问题的助手。\n'
        '以下是知识库中检索到的相关档案片段，每个片段用 [来源N: 文件名] 标记。\n'
        '\n'
        '规则：\n'
        '1. 只根据下方提供的档案内容回答问题，不要使用你的预训练知识补充档案中没有的信息。\n'
        '2. 回答时在相关句子后用 [来源N] 标注出处，例如："该嫌疑人于2024年3月被捕 [来源1]。"\n'
        '3. 如果档案内容不足以完整回答问题，明确说明哪些部分无法从档案中确认。\n'
        '4. 不要输出思考过程、分析步骤或 Markdown 格式标记。\n'
        '5. 回答要准确、简洁、可直接引用。\n'
        '\n'
        f'检索到的档案片段（共 {len(chunks)} 条）：\n'
        f'{sources_block}\n'
        '\n'
        f'用户问题：{question.strip()}\n'
        '\n'
        '基于上述档案的回答：'
    )


def _build_no_ground_prompt(question: str) -> str:
    return (
        '你是一个助手。用户的问题在知识库中没有检索到相关档案。\n'
        '请直接告知用户：该问题在当前知识库中未找到相关档案资料，'
        '建议核实问题关键词或联系管理员补充相关档案。\n'
        '不要编造信息。\n'
        '\n'
        f'用户问题：{question.strip()}\n'
        '\n'
        '回答：'
    )


def estimate_token_count(text: str) -> int:
    """Rough token estimate: ~1 token per CJK char, ~0.25 per ASCII word."""
    cjk = sum(1 for c in text if '一' <= c <= '鿿')
    ascii_chars = len(text) - cjk
    return cjk + max(ascii_chars // 4, 1)
