"""PolicyStore: upsert by url, local search, paging."""
from __future__ import annotations

import sqlite3

import pytest

from app.services.policy import parser
from app.services.policy.store import PolicyStore
from policy_support import block_network, load_fixture  # noqa: F401


@pytest.fixture()
def store(tmp_path):
    return PolicyStore(tmp_path / "policy.db")


def _record(**overrides):
    item = {"title": "关于数据安全的通知", "url": "https://www.gov.cn/zhengce/a.htm", "summary": "摘要甲", "pcode": "国发〔2024〕1号", "pubtimeStr": "2024.01.16"}
    item.update(overrides)
    return parser.parse_item(item, "gongwen")


pytestmark = pytest.mark.usefixtures("block_network")


def test_schema_matches_contract(store):
    with sqlite3.connect(store.db_path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(policy_documents)")]
    # T1 columns first, then the versioning / verification columns added by the follow-up task.
    assert cols == [
        "id", "source", "remote_id", "title", "doc_number", "issuer", "publish_date", "category",
        "subject", "url", "summary", "content", "content_hash", "fetched_at", "verified_status",
        "version", "is_current", "superseded_by", "last_checked_at", "effective_date", "expire_date",
        "status_note", "verified_by", "verified_at", "origin",
    ]
    with sqlite3.connect(store.db_path) as conn:
        clause_cols = [r[1] for r in conn.execute("PRAGMA table_info(gov_policy_clauses)")]
    assert clause_cols == [
        "id", "policy_id", "article_number", "parent_clause_id", "heading", "content",
        "sequence", "page_number", "source_anchor", "needs_review",
    ]


def test_status_column_only_accepts_the_three_frontend_values(store):
    store.upsert(_record())
    with sqlite3.connect(store.db_path) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE policy_documents SET verified_status = 'draft'")


def test_same_url_upserted_twice_creates_one_row(store):
    assert store.upsert(_record()) == "inserted"
    assert store.upsert(_record()) == "unchanged"
    assert store.count() == 1


def test_unchanged_hash_only_refreshes_last_checked_at(store):
    store.upsert(_record(), fetched_at="2024-01-01T00:00:00Z")
    assert store.upsert(_record(), fetched_at="2024-03-01T00:00:00Z") == "unchanged"
    row = store.get_by_url("https://www.gov.cn/zhengce/a.htm")
    assert row.fetched_at == "2024-01-01T00:00:00Z"
    assert row.last_checked_at == "2024-03-01T00:00:00Z"
    assert row.version == 1


def test_changed_content_hash_creates_new_version_and_keeps_old(store):
    # Follow-up task replaced T1's in-place update with versioning.
    store.upsert(_record(), fetched_at="2024-01-01T00:00:00Z")
    first = store.get_by_url("https://www.gov.cn/zhengce/a.htm")
    assert store.upsert(_record(summary="摘要乙"), fetched_at="2024-02-01T00:00:00Z") == "new_version"
    current = store.get_by_url("https://www.gov.cn/zhengce/a.htm")
    assert store.count() == 1
    assert store.count(include_history=True) == 2
    assert current.id != first.id and current.version == 2 and current.summary == "摘要乙"
    old = store.get(first.id)
    assert old.summary == "摘要甲" and old.is_current == 0 and old.superseded_by == current.id
    assert current.verified_status == "unverified"


def test_whole_fixture_page_upserts_without_duplicates(store):
    page = parser.parse_search_response(load_fixture("search_page.json"))
    for record in page.records:
        store.upsert(record)
    for record in page.records:
        store.upsert(record)
    assert store.count() == 3


def test_local_search_matches_title_and_summary(store):
    store.upsert(_record())
    store.upsert(_record(url="https://www.gov.cn/zhengce/b.htm", title="另一份文件", summary="涉及数据安全"))
    store.upsert(_record(url="https://www.gov.cn/zhengce/c.htm", title="无关文件", summary="无关"))
    hits = store.search_local("数据安全", 10)
    assert {h.url for h in hits} == {"https://www.gov.cn/zhengce/a.htm", "https://www.gov.cn/zhengce/b.htm"}


def test_like_wildcards_are_escaped(store):
    store.upsert(_record(title="百分之百", summary="无"))
    assert store.search_local("%", 10) == []
    assert store.search_local("_", 10) == []


def test_list_documents_paginates(store):
    for i in range(5):
        store.upsert(_record(url=f"https://www.gov.cn/zhengce/{i}.htm", pubtimeStr=f"2024.01.0{i + 1}"))
    items, total = store.list_documents(page=2, page_size=2)
    assert total == 5
    assert [i.publish_date for i in items] == ["2024-01-03", "2024-01-02"]
