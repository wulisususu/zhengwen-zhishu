"""政策库：政策生命周期管理 + 条款级检索 + 有据问答。

模块划分：
    models     —— policy_documents / policy_clauses / policy_qa_logs
    parser     —— 原文逐页提取、条款切分、页码与校验值
    lifecycle  —— 生效/失效日期、状态推导、元数据体检
    retrieval  —— 条款级 BM25 + 覆盖率打分，原文高亮片段
    qa         —— 有依据才作答，结论带 [n] 引用；无依据不生成结论
    router     —— HTTP 接口
"""
from .models import PolicyClause, PolicyDocument, PolicyQaLog

__all__ = ["PolicyDocument", "PolicyClause", "PolicyQaLog"]
