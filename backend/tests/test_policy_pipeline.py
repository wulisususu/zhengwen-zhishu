"""政策库链路自检（无需真实模型、无需 HTTP）。

覆盖：
1. 原文解析：条款切分、页码、校验值
2. 条款检索：打分排序、阈值区分
3. 问答降级：模型不可用时退回原文摘录，且必须带引用
4. 无依据：不生成结论
5. 已废止：可检出但不作为现行依据
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.policy import lifecycle, parser, qa, retrieval
from app.policy.models import PolicyClause, PolicyDocument

SAMPLE = """示例市小微企业首次贷款贴息管理办法

第一章 总则

第一条 为支持小微企业发展，规范首次贷款贴息管理，制定本办法。

第二条 本办法适用于本市行政区域内依法登记注册的小微企业。

第二章 申请与条件

第三条 申请贴息应当同时具备下列条件：在本市依法登记注册并正常经营满一年；近两年内无严重失信记录；贷款用于生产经营。

第四条 贷款合同应当签订于本办法施行之后，且为借款人首次取得的经营性贷款。

第五条 申请材料包括营业执照、贷款合同、还款凭证和银行出具的利息清单。

第六条 贴息按实际支付利息的百分之五十给予补贴，单户年度上限二十万元。

第七条 申请人应当在贷款发放后六个月内提出申请，逾期不再受理。

第三章 监督与附则

第八条 主管部门应当对贴息资金使用情况进行监督检查，发现虚报冒领的追回资金并依法处理。

第九条 本办法自2026年3月1日起施行，有效期至2029年2月28日。

第十条 本办法由市地方金融管理局负责解释。
"""

DEPRECATED = """示例市政务数据共享管理办法

第一条 为规范政务数据共享，制定本办法。

第十二条 数据提供部门应当在收到共享申请后十五个工作日内予以答复。

第十五条 数据提供部门应当在收到共享申请后十个工作日内予以答复；不予共享的，应当说明理由。
"""

CURRENT_REPLACEMENT = """示例市政务数据共享办法

第一条 为规范政务数据共享，提高行政效率，制定本办法。

第八条 数据提供部门应当在收到共享申请后十个工作日内予以答复；不予共享的，应当说明理由。

第九条 本办法自2025年1月1日起施行。
"""

IRRELEVANT = "外地户籍人员申请人才公寓补贴需要什么材料"


def new_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def load(db, text: str, tmp: Path, name: str, **meta) -> PolicyDocument:
    path = tmp / f"{name}.txt"
    path.write_text(text, encoding="utf-8")
    parsed = parser.parse_policy(path)
    doc = PolicyDocument(
        title=meta.get("title", name),
        doc_no=meta.get("doc_no", ""),
        issuer=meta.get("issuer", ""),
        status=meta.get("status") or lifecycle.derive_status(
            meta.get("effective_date", ""), meta.get("expire_date", ""), "", ""),
        publish_date=lifecycle.normalize_date(meta.get("publish_date", "")),
        effective_date=lifecycle.normalize_date(meta.get("effective_date", "")),
        expire_date=lifecycle.normalize_date(meta.get("expire_date", "")),
        superseded_by=meta.get("superseded_by", ""),
        page_count=parsed.page_count,
        clause_count=len(parsed.clauses),
        char_count=parsed.char_count,
        checksum=parsed.checksum,
    )
    db.add(doc)
    db.flush()
    for span in parsed.clauses:
        db.add(PolicyClause(
            policy_id=doc.id, seq=span.seq, clause_no=span.clause_no, chapter=span.chapter,
            heading=span.heading, content=span.content, page=span.page,
            char_start=span.char_start, char_end=span.char_end, checksum=span.checksum,
            search_text=parser.normalize_search_text(span.content),
        ))
    db.commit()
    db.refresh(doc)
    return doc


def main() -> int:
    failures: list[str] = []

    def expect(cond: bool, label: str, detail: str = ""):
        print(("[OK]   " if cond else "[FAIL] ") + label + (f"  {detail}" if detail and not cond else ""))
        if not cond:
            failures.append(label)

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        db = new_session()

        # ---------- 1. 解析 ----------
        parsed = parser.parse_policy(Path(tmpdir) / "t.txt") if False else None
        path = tmp / "loan.txt"
        path.write_text(SAMPLE, encoding="utf-8")
        parsed = parser.parse_policy(path)
        expect(len(parsed.clauses) == 10, "切分出 10 条", f"实际 {len(parsed.clauses)}")
        expect(parsed.clauses[0].clause_no == "第一条", "首条编号正确", parsed.clauses[0].clause_no)
        expect(all(c.page >= 1 for c in parsed.clauses), "每条都有页码")
        expect(len(parsed.checksum) == 32, "全文校验值 32 位", parsed.checksum)
        expect("第二章" in parsed.clauses[2].chapter, "章节归属正确", parsed.clauses[2].chapter)

        doc = load(db, SAMPLE, tmp, "贷款贴息办法", title="示例市小微企业首次贷款贴息管理办法",
                   doc_no="示例金规〔2026〕1号", issuer="示例市地方金融管理局",
                   publish_date="2026年2月20日", effective_date="2026年3月1日",
                   expire_date="2029年2月28日")
        expect(doc.status == "现行有效", "状态推导为现行有效", doc.status)

        new_doc = load(db, CURRENT_REPLACEMENT, tmp, "数据共享办法（新）",
                       title="示例市政务数据共享办法", doc_no="示例政发〔2024〕22号",
                       issuer="示例市人民政府", publish_date="2024年12月20日",
                       effective_date="2025年1月1日")

        old = load(db, DEPRECATED, tmp, "数据共享办法（旧）", title="示例市政务数据共享管理办法",
                   doc_no="示例政发〔2019〕8号", issuer="示例市人民政府",
                   publish_date="2019年5月1日", effective_date="2019年6月1日",
                   expire_date="2024年5月31日", superseded_by="《示例市数据条例》")

        # ---------- 2. 检索 ----------
        cands = retrieval.search(db, "小微企业首次贷款贴息的补贴比例是多少", scope="current")
        expect(bool(cands), "检索返回候选")
        top = cands[0]
        expect(top.clause.clause_no == "第六条", "最高分命中第六条", top.clause.clause_no)
        expect(top.score >= 0.6, "相关条款分数过阈值", f"{top.score:.3f}")
        scores = [c.score for c in cands]
        expect(scores == sorted(scores, reverse=True), "分数降序")

        # ---------- 3. 有依据作答（模型不可用 → 原文摘录） ----------
        original_chat = qa.llm_chat.chat

        def offline(*a, **k):
            raise RuntimeError("model offline")

        qa.llm_chat.chat = offline
        try:
            res = qa.answer(db, "小微企业首次贷款贴息的补贴比例是多少")
        finally:
            qa.llm_chat.chat = original_chat

        expect(res["status"] == "answered", "有依据时给出结论", res["status"])
        expect(res["meta"]["generated_by"].startswith("extractive"), "降级为原文摘录",
               res["meta"]["generated_by"])
        expect("[1]" in res["conclusion"], "结论带引用标记")
        expect(len(res["citations"]) >= 1, "返回引用明细")
        expect(res["citations"][0]["clause_no"] == "第六条", "引用指向第六条",
               res["citations"][0]["clause_no"])
        expect(bool(res["citations"][0]["excerpt"]["hl"]), "原文有高亮片段")

        # ---------- 4. 无依据不生成结论 ----------
        res2 = qa.answer(db, IRRELEVANT, threshold=0.6)
        expect(res2["status"] == "no_basis", "无关问题不生成结论", res2["status"])
        expect(res2["conclusion"] == "", "无结论正文")
        expect(bool(res2["reason"]), "给出不生成结论的理由")
        expect(all(c["below_threshold"] for c in res2["candidates"]), "候选均低于阈值")

        # ---------- 5. 已废止处理：新版现行，旧版只能作历史对照 ----------
        res3 = qa.answer(db, "政务数据共享申请多少个工作日内答复", scope="all")
        expect(res3["status"] == "answered", "含已废止检索仍可作答", res3["status"])
        cited_clauses = [c["clause_no"] for c in res3["citations"]]
        cited_policies = {c["policy_title"] for c in res3["citations"]}
        expect("第八条" in cited_clauses, "引用现行文件第八条", str(cited_clauses))
        expect("示例市政务数据共享管理办法" not in cited_policies, "已废止文件未进入引用",
               str(cited_policies))
        expect(res3["meta"]["excluded_deprecated"] >= 1, "记录了被排除的已废止条款")
        expect(bool(res3.get("deprecated_refs")), "已废止条款作为历史对照列出")

        # 只允许旧文件时，结论必须拒绝
        res4 = qa.answer(db, "政务数据共享申请多少个工作日内答复",
                         scope="policy", policy_ids=[old.id])
        expect(res4["status"] == "no_basis", "仅有已废止文件时不生成结论", res4["status"])
        expect("已废止" in (res4["reason"] or ""), "理由中说明已废止", res4.get("reason", ""))

    print()
    if failures:
        print(f"失败 {len(failures)} 项：" + "；".join(failures))
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
