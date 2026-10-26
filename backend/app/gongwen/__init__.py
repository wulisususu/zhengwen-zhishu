"""公文结构化生成与 GB/T 9704-2012 版式渲染。

模块划分：
    schema   —— IR 定义、版式常量、结构层校验
    checker  —— 内容层校核规则（序号、结尾用语、标点、称谓等）
    renderer —— 确定性版式渲染（python-docx）
    service  —— 模型生成 → IR 装配（含失败回退）
    router   —— HTTP 接口
"""
from .schema import DOC_TYPES, BodyPara, GongwenDoc

__all__ = ["DOC_TYPES", "BodyPara", "GongwenDoc"]
