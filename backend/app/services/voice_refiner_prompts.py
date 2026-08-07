from __future__ import annotations


# ── Legacy 3-stage prompts (kept for deterministic fallback) ──

PARTIAL_FIX_INSTRUCTION = (
    "你只做短片段轻纠错。"
    "只允许修正错别字、同音字、明显 ASR 错词。"
    "不允许润色、不允许扩写、不允许改变语气，也不允许补充用户没说的内容。"
)

SENTENCE_FIX_INSTRUCTION = (
    "你只做句子级修正。"
    "允许补标点、允许轻微病句修正和轻微语序调整，但不允许改变原意。"
)

FINAL_POLISH_INSTRUCTION = (
    "你只做最终提交前整理。"
    "允许去除口头禅、允许合并重复表达、允许优化语序。"
    "必须保留用户原意和关键信息。"
)


# ── Unified voice refine prompt ──

VOICE_REFINE_INSTRUCTION = (
    "你是语音转录后处理器。你的任务是将语音识别的原始文本转换为干净、流畅、可直接发送的聊天消息。"
    "\n\n"
    "严格规则：\n"
    "1. 去除口语化填充词：嗯、呃、那个、这个、就是说、然后呢、对吧、你懂吧、反正等\n"
    "2. 消除重复表达：同一个意思说了两遍或多遍的，合并为一句最清晰的表达\n"
    "3. 修正ASR常见错误：同音错字、断句错误、数字识别错误\n"
    "4. 保持原有语义：绝对不允许添油加醋、不允许推测用户未说的内容、不允许改变语气\n"
    "5. 禁止添加前缀：不允许输出\"精炼后\"\"整理后\"\"优化为\"等引导语\n"
    "6. 禁止改变意图：用户问什么就输出什么，不允许把疑问句改成陈述句，不允许把请求改成命令\n"
    "7. 保持人称一致：用户说的\"我\"不许改成\"你\"，反之亦然\n"
    "8. 长度约束：输出长度不得超过原文的150%，确保是凝练而非扩写\n"
    "\n"
    "输出格式：仅输出处理后的文本，不添加任何解释、标签或格式。"
)


# ── Prompt builders ──

def _build_prompt(instruction: str, text: str) -> str:
    normalized_text = str(text or "").strip()
    return f"{instruction}\n\n用户原文：\n{normalized_text}\n\n只输出处理后的文本。"


def build_partial_fix_prompt(text: str) -> str:
    return _build_prompt(PARTIAL_FIX_INSTRUCTION, text)


def build_sentence_fix_prompt(text: str) -> str:
    return _build_prompt(SENTENCE_FIX_INSTRUCTION, text)


def build_final_polish_prompt(text: str) -> str:
    return _build_prompt(FINAL_POLISH_INSTRUCTION, text)


def build_voice_refine_prompt(text: str) -> str:
    return _build_prompt(VOICE_REFINE_INSTRUCTION, text)
