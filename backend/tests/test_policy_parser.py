"""Parser: field cleaning and response navigation (pure functions)."""
from __future__ import annotations

import pytest

from app.services.policy import parser
from policy_support import load_fixture


def test_clean_text_strips_em_and_br_and_unescapes():
    raw = "关于加强<em>数据</em><em>安全</em>管理的<br/>指导意见 &amp; 解读 &ldquo;引号&rdquo;"
    assert parser.clean_text(raw) == "关于加强数据安全管理的 指导意见 & 解读 “引号”"


def test_clean_text_handles_none_and_whitespace():
    assert parser.clean_text(None) == ""
    assert parser.clean_text("  a \n\t b  ") == "a b"


@pytest.mark.parametrize(
    "pubtime, ptime, expected",
    [
        ("2024.01.16", None, "2024-01-16"),
        ("2024-1-6", None, "2024-01-06"),
        ("2024年3月5日", None, "2024-03-05"),
        ("", 1708963200000, "2024-02-27"),  # 2024-02-26T16:00Z == 2024-02-27 in Asia/Shanghai
        (None, "1705334400000", "2024-01-16"),
        (None, None, None),
        ("not a date", None, None),
    ],
)
def test_normalize_date(pubtime, ptime, expected):
    assert parser.normalize_date(pubtime, ptime) == expected


def test_parse_page_reads_catmap_listvo_not_data():
    page = parser.parse_search_response(load_fixture("search_page.json"))
    urls = [r.url for r in page.records]
    assert urls == [
        "https://www.gov.cn/zhengce/content/202401/content_0000001.htm",
        "https://www.gov.cn/zhengce/zhengceku/202402/content_0000002.htm",
        "https://www.gov.cn/zhengce/zhengceku/202403/content_0000003.htm",
    ]
    # raw_count counts every listVO entry returned, including the duplicate and the invalid one
    assert page.raw_count == 5
    assert page.skipped == 2


def test_parse_item_fields():
    page = parser.parse_search_response(load_fixture("search_page.json"))
    first = page.records[0]
    assert first.title == "国务院办公厅关于加强数据安全管理的 指导意见"
    assert first.doc_number == "国办发〔2024〕5号"
    assert first.issuer == "国务院办公厅"
    assert first.publish_date == "2024-01-16"
    assert first.category == "gongwen"
    assert first.subject == "综合政务\\其他"
    assert first.remote_id == "remote-001"
    assert first.source == "gov_zcwjk"
    assert len(first.content_hash) == 64


def test_doc_number_comes_from_pcode_not_fwzh():
    item = {"title": "t", "url": "https://www.gov.cn/zhengce/x.htm", "pcode": "国发〔2024〕1号", "fwzh": "错误字段"}
    assert parser.parse_item(item, "gongwen").doc_number == "国发〔2024〕1号"
    item = {"title": "t", "url": "https://www.gov.cn/zhengce/x.htm", "pcode": "", "fwzh": "错误字段"}
    assert parser.parse_item(item, "gongwen").doc_number is None


def test_missing_pubtimestr_falls_back_to_ptime():
    page = parser.parse_search_response(load_fixture("search_page.json"))
    second = page.records[1]
    assert second.publish_date == "2024-02-27"
    assert second.title == "关于印发《数据出境安全评估办法》的通知 & 解读"
    assert second.summary == "评估办法自发布之日起施行。"


def test_total_count_zero_is_not_treated_as_no_results():
    payload = load_fixture("search_page.json")
    assert payload["searchVO"]["totalCount"] == 0
    page = parser.parse_search_response(payload)
    assert len(page.records) == 3


def test_empty_page_is_valid_and_has_no_records():
    page = parser.parse_search_response(load_fixture("empty_page.json"))
    assert page.records == []
    assert page.raw_count == 0


def test_has_next_uses_page_size_not_total_count():
    assert parser.has_next_page(raw_count=20, per_page=20) is True
    assert parser.has_next_page(raw_count=7, per_page=20) is False
    assert parser.has_next_page(raw_count=0, per_page=20) is False


@pytest.mark.parametrize("payload", [None, [], {}, {"searchVO": None}, {"searchVO": {"catMap": "x"}}])
def test_malformed_payload_raises_parse_error(payload):
    with pytest.raises(parser.PolicyParseError):
        parser.parse_search_response(payload)


def test_content_hash_changes_with_content():
    a = parser.parse_item({"title": "标题", "url": "https://www.gov.cn/zhengce/a.htm", "summary": "甲"}, "gongwen")
    b = parser.parse_item({"title": "标题", "url": "https://www.gov.cn/zhengce/a.htm", "summary": "乙"}, "gongwen")
    c = parser.parse_item({"title": "<em>标题</em>", "url": "https://www.gov.cn/zhengce/a.htm", "summary": "甲"}, "gongwen")
    assert a.content_hash != b.content_hash
    assert a.content_hash == c.content_hash  # highlight markup does not change the hash
