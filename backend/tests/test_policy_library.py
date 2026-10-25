"""Policy library: versioned import, clause order/adjacency, status filtering,
citations batch, SSRF on import, failure safety, library isolation."""
from __future__ import annotations

import ast
import pathlib
import socket

import pytest

from app.services.policy import errors
from app.services.policy.fetcher import RawResponse, SafeFetcher
from app.services.policy.library import ImportRequest, PolicyLibraryService, fragment, parse_citation_id
from app.services.policy.settings import settings_from_mapping
from app.services.policy.store import PolicyStore
from policy_support import FakeClock, block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

SOURCE = "https://www.gov.cn/zhengce/content/202501/content_0000009.htm"
V1 = "示例办法（演示）\n第一条　为了规范政务数据共享，制定本办法。\n第二条　本办法适用于本市政务数据共享活动。\n第三条　数据提供部门应当在15个工作日内予以答复。"
V2 = "示例办法（演示）\n第一条　为了规范政务数据共享，制定本办法。\n第二条　本办法适用于本市政务数据共享活动。\n第三条　数据提供部门应当在10个工作日内予以答复。"
FRONTEND_CITATION_KEYS = {"id", "policyTitle", "docNumber", "issuer", "issuedOn", "effectiveOn", "expiresOn", "status", "clause", "excerpt", "text"}


class Opener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, target, ip, timeout, max_bytes):
        self.calls.append(target.url)
        return self.responses.pop(0)


def make(tmp_path, *, dns=None, responses=(), mode="cloud_allowed"):
    settings = settings_from_mapping({"enabled": True, "base_url": "https://example.invalid/data", "db_path": str(tmp_path / "p.db")})
    clock = FakeClock()
    dns = dns or {"www.gov.cn": ["203.119.25.1"]}

    def resolver(host, port, *a, **k):
        if host not in dns:
            raise socket.gaierror()
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in dns[host]]

    opener = Opener(responses)
    fetcher = SafeFetcher(settings.fetch, resolver=resolver, opener=opener, mode_provider=lambda: mode, sleep=clock.sleep, clock=clock.monotonic)
    return PolicyLibraryService(settings, PolicyStore(settings.db_path), fetcher), opener


def upload(lib, text, **kw):
    return lib.import_policy(ImportRequest(filename="policy.txt", data=text.encode("utf-8"), source_url=SOURCE, **kw))


def verify_current(lib, policy_id):
    return lib.verify(policy_id, status="current", note="人工核验：现行有效（演示）", fields={"doc_number": "示政规〔2025〕9号"}, verifier="admin")


# ---------- import + clauses ----------

def test_file_import_stores_ordered_clauses_with_full_text(tmp_path):
    lib, _ = make(tmp_path)
    result = upload(lib, V1, title="示例办法（演示）")
    assert result["error"] is None
    assert result["created_new_version"] is True
    clauses = lib.store.clauses_for(result["policy"]["id"])
    assert [c.sequence for c in clauses] == [1, 2, 3, 4]
    assert [c.article_number for c in clauses] == [None, "第一条", "第二条", "第三条"]
    assert clauses[3].content == "第三条　数据提供部门应当在15个工作日内予以答复。"
    assert result["policy"]["verified_status"] == "unverified"


def test_same_content_does_not_create_a_version(tmp_path):
    lib, _ = make(tmp_path)
    first = upload(lib, V1)
    again = upload(lib, V1)
    assert again["created_new_version"] is False
    assert again["policy"]["id"] == first["policy"]["id"]
    assert again["policy"]["last_checked_at"] >= first["policy"]["last_checked_at"]
    assert lib.store.count(include_history=True) == 1


def test_changed_content_creates_new_version_and_old_version_stays_queryable(tmp_path):
    lib, _ = make(tmp_path)
    v1 = upload(lib, V1)
    v1_id = v1["policy"]["id"]
    verify_current(lib, v1_id)
    v1_clause_ids = [c.id for c in lib.store.clauses_for(v1_id)]

    v2 = upload(lib, V2)
    assert v2["created_new_version"] is True and v2["superseded_id"] == v1_id
    assert v2["policy"]["version"] == 2 and v2["policy"]["verified_status"] == "unverified"

    old = lib.store.get(v1_id)
    assert old.is_current == 0 and old.superseded_by == v2["policy"]["id"]
    assert old.verified_status == "current"  # earlier verification is kept on the old row
    assert [c.id for c in lib.store.clauses_for(v1_id)] == v1_clause_ids
    assert "15个工作日" in lib.store.clauses_for(v1_id)[3].content

    history = lib.list_policies(url=SOURCE, include_history=True)
    assert [d["version"] for d in history["items"]] == [2, 1]
    assert lib.list_policies(url=SOURCE)["total"] == 1

    cites = lib.citations([f"clause:{v1_clause_ids[3]}"])
    assert cites["citations"][0]["status"] == "current"
    assert "已被第 2 版替代" in cites["citations"][0]["statusNote"]


def test_failed_update_leaves_existing_verified_data_untouched(tmp_path, monkeypatch):
    lib, _ = make(tmp_path)
    v1 = upload(lib, V1)
    verify_current(lib, v1["policy"]["id"])

    import app.services.policy.store as store_module

    real_insert = store_module.PolicyStore._insert_doc

    def failing_insert(conn, values):
        real_insert(conn, values)
        raise RuntimeError("disk full")

    monkeypatch.setattr(store_module.PolicyStore, "_insert_doc", staticmethod(failing_insert))
    result = upload(lib, V2)
    assert result["error"]["code"] == errors.INTERNAL_ERROR
    monkeypatch.undo()

    current = lib.store.get_by_url(SOURCE)
    assert current.id == v1["policy"]["id"]
    assert current.is_current == 1 and current.verified_status == "current"
    assert lib.store.count(include_history=True) == 1
    assert len(lib.store.clauses_for(current.id)) == 4


def test_unrecognised_text_is_kept_and_flagged(tmp_path):
    lib, _ = make(tmp_path)
    result = lib.import_policy(ImportRequest(filename="a.txt", data="一段没有条款编号的正文。\n第二段。".encode()))
    assert result["needs_review_count"] == 2
    assert [c.content for c in lib.store.clauses_for(result["policy"]["id"])] == ["一段没有条款编号的正文。", "第二段。"]


def test_import_requires_exactly_one_source(tmp_path):
    lib, _ = make(tmp_path)
    assert lib.import_policy(ImportRequest())["error"]["code"] == errors.INVALID_QUERY
    both = ImportRequest(url=SOURCE, filename="a.txt", data=b"x")
    assert lib.import_policy(both)["error"]["code"] == errors.INVALID_QUERY


def test_pdf_upload_is_unsupported_not_guessed(tmp_path):
    lib, _ = make(tmp_path)
    result = lib.import_policy(ImportRequest(filename="a.pdf", data=b"%PDF-1.7"))
    assert result["error"]["code"] == errors.UNSUPPORTED_FILE
    assert lib.store.count(include_history=True) == 0


# ---------- URL import / SSRF ----------

PAGE = (
    "<html><head><title>示例办法（演示）_中国政府网</title><meta name='PubDate' content='2025-01-20 10:00'></head>"
    "<body><div class='nav'>首页 &gt; 政策</div><div id='UCAP-CONTENT'><p>第一条　为了规范政务数据共享，制定本办法。</p>"
    "<p>第二条　本办法适用于本市。</p></div><script>var x=1;</script></body></html>"
)


def test_url_import_extracts_content_container(tmp_path):
    lib, opener = make(tmp_path, responses=[RawResponse(200, {"content-type": "text/html; charset=utf-8"}, PAGE.encode("utf-8"))])
    result = lib.import_policy(ImportRequest(url=SOURCE))
    assert result["error"] is None
    policy = result["policy"]
    assert policy["title"] == "示例办法（演示）"
    assert policy["publish_date"] == "2025-01-20"
    assert policy["origin"] == "url_import"
    contents = [c.content for c in lib.store.clauses_for(policy["id"])]
    assert contents == ["第一条　为了规范政务数据共享，制定本办法。", "第二条　本办法适用于本市。"]
    assert result["needs_review_count"] == 0


def test_url_import_rejects_private_address_and_writes_nothing(tmp_path):
    lib, opener = make(tmp_path, dns={"www.gov.cn": ["10.0.0.9"]}, responses=[RawResponse(200, {"content-type": "text/html"}, PAGE.encode())])
    result = lib.import_policy(ImportRequest(url=SOURCE))
    assert result["error"]["code"] == errors.FETCH_PRIVATE_ADDRESS
    assert "人工上传" in result["error"]["fallback"]
    assert opener.calls == []
    assert lib.store.count(include_history=True) == 0


def test_url_import_rejects_non_allowlisted_host(tmp_path):
    lib, opener = make(tmp_path)
    result = lib.import_policy(ImportRequest(url="https://intranet.example.local/policy"))
    assert result["error"]["code"] == errors.FETCH_HOST_NOT_ALLOWED
    assert opener.calls == []


def test_upload_source_url_is_validated_but_never_fetched(tmp_path):
    lib, opener = make(tmp_path)
    bad = lib.import_policy(ImportRequest(filename="a.txt", data="第一条　甲。".encode(), source_url="http://192.168.0.1/x"))
    assert bad["error"]["code"] == errors.FETCH_HOST_NOT_ALLOWED
    good = upload(lib, V1)
    assert good["error"] is None and opener.calls == []


# ---------- search + status semantics ----------

def test_search_defaults_to_current_only(tmp_path):
    lib, _ = make(tmp_path)
    v1 = upload(lib, V1)
    assert lib.search("工作日")["hits"] == []  # unverified is not returned by default
    explicit = lib.search("工作日", statuses=["unverified"])
    assert [h["status"] for h in explicit["hits"]] == ["unverified"]
    verify_current(lib, v1["policy"]["id"])
    hits = lib.search("工作日")["hits"]
    assert len(hits) == 1 and hits[0]["status"] == "current"
    assert hits[0]["clause"] == "第三条"


def test_search_does_not_treat_reachability_as_current(tmp_path):
    lib, _ = make(tmp_path, responses=[RawResponse(200, {"content-type": "text/html"}, PAGE.encode())])
    result = lib.import_policy(ImportRequest(url=SOURCE))  # page fetched fine = still unverified
    assert result["policy"]["verified_status"] == "unverified"


def test_search_mixed_statuses_are_labelled_per_hit(tmp_path):
    lib, _ = make(tmp_path)
    a = upload(lib, V1)
    verify_current(lib, a["policy"]["id"])
    b = lib.import_policy(ImportRequest(filename="b.txt", data="第一条　数据提供部门应当在20个工作日内答复。".encode()))
    lib.verify(b["policy"]["id"], status="abolished", note="已废止（演示）", fields={}, verifier="admin")
    hits = lib.search("工作日", statuses=["current", "abolished"])["hits"]
    assert sorted(h["status"] for h in hits) == ["abolished", "current"]


def test_search_records_match_position_and_fragment(tmp_path):
    lib, _ = make(tmp_path)
    v1 = upload(lib, V1)
    verify_current(lib, v1["policy"]["id"])
    hit = lib.search("15个工作日")["hits"][0]
    content = lib.store.clauses_for(v1["policy"]["id"])[3].content
    start, end = hit["match"]["start"], hit["match"]["end"]
    assert content[start:end] == "15个工作日"
    assert hit["excerpt"] == {"before": content[:start], "highlight": "15个工作日", "after": content[end:]}
    assert hit["citation_id"] == f"clause:{hit['clause_id']}@{start}-{end}"


@pytest.mark.parametrize("bad", ["draft", "pending"])
def test_unknown_status_values_are_rejected(tmp_path, bad):
    lib, _ = make(tmp_path)
    assert lib.search("数据", statuses=[bad])["error"]["code"] == errors.INVALID_STATUS
    v1 = upload(lib, V1)
    assert lib.verify(v1["policy"]["id"], status=bad, note=None, fields={}, verifier="x")["error"]["code"] == errors.INVALID_STATUS


# ---------- citations batch ----------

def test_citations_batch_returns_frontend_shape_in_requested_order(tmp_path):
    lib, _ = make(tmp_path)
    v1 = upload(lib, V1, issuer="示例市政务服务管理局（演示机关）")
    verify_current(lib, v1["policy"]["id"])
    clauses = lib.store.clauses_for(v1["policy"]["id"])
    hit = lib.search("15个工作日")["hits"][0]
    ids = [hit["citation_id"], f"clause:{clauses[1].id}", "clause:999999", "garbage"]
    result = lib.citations(ids)
    got = result["citations"]
    assert [c["id"] for c in got] == ids[:2]
    assert result["missing"] == ["garbage", "clause:999999"]

    first = got[0]
    assert FRONTEND_CITATION_KEYS <= set(first)
    assert set(first) <= FRONTEND_CITATION_KEYS | {"statusNote", "previousClause", "nextClause"}
    assert first["status"] == "current"
    assert first["docNumber"] == "示政规〔2025〕9号"
    assert first["issuer"] == "示例市政务服务管理局（演示机关）"
    assert first["effectiveOn"] == "未录入"
    assert first["clause"] == "第三条"
    assert first["text"]["highlight"] == "15个工作日"
    assert first["previousClause"].startswith("第二条")
    assert "nextClause" not in first  # last clause has no next

    second = got[1]
    assert second["clause"] == "第一条"
    assert second["previousClause"].startswith("第1段") or second["previousClause"].startswith("序言")
    assert second["nextClause"].startswith("第二条")


def test_citation_id_round_trip_and_fragment_fallback():
    assert parse_citation_id("clause:12@3-9") == (12, 3, 9)
    assert parse_citation_id("clause:12") == (12, None, None)
    assert parse_citation_id("clause:12@9-3") == (12, None, None)
    assert parse_citation_id("c1") is None
    no_match = fragment("第一条　第一句。第二句很长。", None, None)
    assert no_match["before"] == "" and no_match["highlight"] == "第一条　第一句。"


# ---------- isolation ----------

def test_public_policy_library_never_touches_private_knowledge_base():
    package = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "policy"
    for path in package.glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module:
                assert not node.module.startswith("app.kb"), f"{path.name} imports {node.module}"
            if isinstance(node, ast.Import):
                assert not any(a.name.startswith("app.kb") for a in node.names), path.name
    from app.services.policy.settings import PolicySettings

    assert PolicySettings().db_path.name == "policy.db"
