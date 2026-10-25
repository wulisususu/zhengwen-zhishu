"""Clause segmentation: hierarchy markers, order, full text, needs_review."""
from __future__ import annotations

from app.services.policy.clauses import chinese_number, segment

REGULATION = """示例市政务数据共享管理办法（演示）
为了规范政务数据共享，制定本办法。
第一章　总则
第一条　为了规范政务数据共享活动，根据有关法律法规，结合本市实际，制定本办法。
第二条　本办法适用于本市行政区域内的政务数据共享活动。
本办法所称政务数据，是指政务部门在履行职责过程中产生的数据。
第二章　共享管理
第三条　数据提供部门应当履行下列职责：
（一）编制数据资源目录；
（二）按照目录提供数据；
1.保证数据准确；
2.及时更新数据。
（三）配合开展安全检查。
第四条　共享申请提出后，数据提供部门应当在10个工作日内予以答复。
"""


def test_chinese_number():
    assert chinese_number("一") == 1
    assert chinese_number("十") == 10
    assert chinese_number("十二") == 12
    assert chinese_number("二十三") == 23
    assert chinese_number("一百零五") == 105
    assert chinese_number("15") == 15
    assert chinese_number("甲") is None


def test_articles_chapters_and_items_keep_hierarchy_and_order():
    clauses = segment(REGULATION)
    labels = [c.article_number for c in clauses]
    assert labels == [None, "第一章", "第一条", "第二条", "第二章", "第三条", "（一）", "（二）", "1.", "2.", "（三）", "第四条"]
    assert [c.sequence for c in clauses] == list(range(1, len(clauses) + 1))
    by_label = {c.article_number: c for c in clauses if c.article_number}
    assert clauses[by_label["第一条"].parent_index].article_number == "第一章"
    assert clauses[by_label["（二）"].parent_index].article_number == "第三条"
    assert clauses[by_label["1."].parent_index].article_number == "（二）"
    assert clauses[by_label["第四条"].parent_index].article_number == "第二章"
    assert by_label["第一章"].heading == "总则"
    assert by_label["（三）"].source_anchor == "第二章>第三条>（三）"


def test_clause_keeps_full_original_text_including_continuation_paragraphs():
    clauses = segment(REGULATION)
    second = next(c for c in clauses if c.article_number == "第二条")
    assert second.content == "第二条　本办法适用于本市行政区域内的政务数据共享活动。\n本办法所称政务数据，是指政务部门在履行职责过程中产生的数据。"
    assert all(not c.needs_review for c in clauses)


def test_no_text_is_lost():
    clauses = segment(REGULATION)
    rebuilt = "\n".join(c.content for c in clauses)
    expected = "\n".join(line.strip() for line in REGULATION.splitlines() if line.strip())
    assert rebuilt == expected


def test_never_splits_long_articles_by_length():
    long_body = "第一条　" + "很长的条款内容。" * 200  # ~1600 chars, a single article
    clauses = segment(long_body + "\n第二条　短条款。")
    assert [c.article_number for c in clauses] == ["第一条", "第二条"]
    assert clauses[0].content == long_body


def test_notice_style_numbering():
    text = "各单位：\n一、自查范围\n全市各级政务部门的信息系统。\n二、自查内容\n（一）数据分类分级。\n（二）共享审批记录。\n三、时间安排\n11月1日至20日。"
    clauses = segment(text)
    assert [c.article_number for c in clauses] == [None, "一、", "二、", "（一）", "（二）", "三、"]
    first = clauses[1]
    assert first.heading == "自查范围"
    assert first.content == "一、自查范围\n全市各级政务部门的信息系统。"


def test_out_of_order_numbering_is_flagged_not_dropped():
    text = "第一条　甲。\n第三条　丙。\n第二条　乙。"
    clauses = segment(text)
    assert [c.article_number for c in clauses] == ["第一条", "第三条", "第二条"]
    assert [c.needs_review for c in clauses] == [False, True, True]
    assert clauses[2].content == "第二条　乙。"


def test_unrecognised_structure_keeps_paragraphs_with_needs_review():
    text = "这是一段没有条款标记的正文。\n另一段同样没有标记。"
    clauses = segment(text)
    assert [c.content for c in clauses] == ["这是一段没有条款标记的正文。", "另一段同样没有标记。"]
    assert all(c.needs_review for c in clauses)
    assert all(c.article_number is None for c in clauses)


def test_unreliable_source_marks_everything_for_review():
    clauses = segment("第一条　甲。\n第二条　乙。", reliable=False)
    assert all(c.needs_review for c in clauses)


def test_references_inside_sentences_are_not_markers():
    clauses = segment("第一条　依照本办法第五条的规定执行。\n2024.01.16 发布")
    assert [c.article_number for c in clauses] == ["第一条"]
    assert "2024.01.16 发布" in clauses[0].content


def test_empty_text():
    assert segment("") == []
    assert segment("   \n  ") == []
