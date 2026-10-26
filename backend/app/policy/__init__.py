"""政策问答：条款级检索 + 有依据才作答。

政策资料只有一处：既有政策库（T1，policy.db）。导入（含 PDF 逐页解析与 OCR，T3）、
元数据补录与人工核验都走 /gov/policies；本包不另建政策表、不另做解析。

模块划分：
    corpus     —— 读取政策库条款，按人工核验状态与生效日期给出可用状态
    lifecycle  —— 日期解析与展示、状态是否可作现行依据
    retrieval  —— 条款级 BM25 + 覆盖率打分，原文高亮片段
    qa         —— 有依据才作答，结论带 [n] 引用；无依据不生成结论
    models     —— policy_qa_logs（问答留痕）
    router     —— HTTP 接口
"""
from .models import PolicyQaLog

__all__ = ["PolicyQaLog"]
