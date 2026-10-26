"""按最新切分规则重建已入库政策的条款（不重新上传文件）。

用途：解析器规则升级后（例如剔除页码行、把「一、」按「（一）」细分），
存量记录需要按新规则重新切分，但不应丢掉已填写的元数据与状态。

用法：
    python scripts/reparse_policies.py           # 全部重建
    python scripts/reparse_policies.py 4 5       # 只重建指定 ID
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.database import SessionLocal  # noqa: E402
from app.policy import parser  # noqa: E402
from app.policy.models import PolicyClause, PolicyDocument  # noqa: E402


def rebuild(db, doc: PolicyDocument) -> tuple[int, int]:
    src = Path(doc.file_path or "")
    if not src.exists():
        return 0, doc.clause_count or 0
    result = parser.parse_policy(src)
    if not result.clauses:
        return 0, doc.clause_count or 0

    db.query(PolicyClause).filter(PolicyClause.policy_id == doc.id).delete()
    for span in result.clauses:
        db.add(PolicyClause(
            policy_id=doc.id,
            seq=span.seq,
            clause_no=span.clause_no,
            chapter=span.chapter,
            heading=span.heading,
            content=span.content,
            page=span.page,
            char_start=span.char_start,
            char_end=span.char_end,
            checksum=span.checksum,
            search_text=parser.normalize_search_text(span.content),
        ))
    doc.clause_count = len(result.clauses)
    doc.char_count = result.char_count
    doc.page_count = result.page_count
    db.commit()
    return doc.clause_count, len(result.clauses)


def main() -> None:
    targets = [int(x) for x in sys.argv[1:] if x.isdigit()]
    db = SessionLocal()
    try:
        query = db.query(PolicyDocument).order_by(PolicyDocument.id)
        if targets:
            query = query.filter(PolicyDocument.id.in_(targets))
        for doc in query:
            before = doc.clause_count
            after, _ = rebuild(db, doc)
            print(f"[{doc.id}] {doc.title[:24]:24} {before} 条 -> {after} 条")
    finally:
        db.close()


if __name__ == "__main__":
    main()
