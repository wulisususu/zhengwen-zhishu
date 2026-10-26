"""PolicyRetrievalService: egress policy, local-first search, sync, no raw exceptions."""
from __future__ import annotations

import pytest
import requests

from app.services.policy import errors
from app.services.policy.client import PolicyClient
from app.services.policy.service import PolicyRetrievalService
from app.services.policy.settings import settings_from_mapping
from app.services.policy.store import PolicyStore
from app.services.policy import parser
from policy_support import FakeClock, FakeHttp, FakeResponse, block_network, load_fixture  # noqa: F401

BASE = "https://example.invalid/search-gov/data"

pytestmark = pytest.mark.usefixtures("block_network")


def build(monkeypatch, tmp_path, responses, *, mode="cloud_allowed", **overrides):
    settings = settings_from_mapping({"enabled": True, "base_url": BASE, "db_path": str(tmp_path / "p.db"), **overrides})
    clock = FakeClock()
    http = FakeHttp(responses)
    monkeypatch.setattr(requests, "get", http)
    client = PolicyClient(settings, sleep=clock.sleep, clock=clock.monotonic, mode_provider=lambda: mode)
    service = PolicyRetrievalService(settings, PolicyStore(settings.db_path), client, mode_provider=lambda: mode)
    return service, http


def seed(service, n=1):
    for i in range(n):
        service.store.upsert(parser.parse_item({"title": f"本地数据安全文件{i}", "url": f"https://www.gov.cn/zhengce/local-{i}.htm"}, "gongwen"))


@pytest.mark.parametrize("mode", ["intranet", "offline"])
def test_blocked_mode_returns_local_only_without_requests(monkeypatch, tmp_path, mode):
    service, http = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))], mode=mode)
    seed(service, 1)
    result = service.search("数据安全", limit=10)
    assert result.source == "local_only"
    assert result.egress_mode == mode
    assert result.error["code"] == errors.EGRESS_BLOCKED
    assert [h.title for h in result.hits] == ["本地数据安全文件0"]
    assert http.calls == []


def test_mode_is_read_from_model_policy_get_mode(monkeypatch, tmp_path):
    """Default wiring reads app.services.model_policy.get_mode (env override)."""
    monkeypatch.setenv("AI_BOX_MODEL_MODE", "intranet")
    settings = settings_from_mapping({"enabled": True, "base_url": BASE, "db_path": str(tmp_path / "p.db")})
    http = FakeHttp([FakeResponse(load_fixture("search_page.json"))])
    monkeypatch.setattr(requests, "get", http)
    service = PolicyRetrievalService(settings, PolicyStore(settings.db_path), PolicyClient(settings))
    result = service.search("数据安全")
    assert result.source == "local_only"
    assert http.calls == []


@pytest.mark.parametrize("mode", ["intranet", "offline"])
def test_blocked_mode_sync_sends_nothing(monkeypatch, tmp_path, mode):
    service, http = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))], mode=mode)
    result = service.sync_topic("数据安全", pages=3)
    assert result.error["code"] == errors.EGRESS_BLOCKED
    assert result.pages_fetched == 0
    assert http.calls == []


def test_enough_local_hits_skip_remote(monkeypatch, tmp_path):
    service, http = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))])
    seed(service, 3)
    result = service.search("数据安全", limit=3)
    assert result.source == "local"
    assert len(result.hits) == 3
    assert http.calls == []


def test_insufficient_local_hits_top_up_from_remote_and_persist(monkeypatch, tmp_path):
    service, http = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))])
    seed(service, 1)
    result = service.search("数据安全", limit=10)
    assert result.source == "local+remote"
    assert len(http.calls) == 1
    assert result.remote_fetched == 3
    assert len(result.hits) == 4
    assert service.store.count() == 4
    assert all(h.verified_status == "unverified" for h in result.hits)


def test_remote_failure_keeps_local_results_with_error_code(monkeypatch, tmp_path):
    service, _ = build(monkeypatch, tmp_path, [requests.Timeout("t")] * 3)
    seed(service, 1)
    result = service.search("数据安全", limit=10)
    assert result.source == "local"
    assert result.error["code"] == errors.REMOTE_TIMEOUT
    assert len(result.hits) == 1


def test_disabled_and_unconfigured_are_local_only(monkeypatch, tmp_path):
    service, http = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))], enabled=False)
    assert service.search("数据").error["code"] == errors.DISABLED
    service, http2 = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))], base_url="")
    assert service.search("数据").error["code"] == errors.NOT_CONFIGURED
    assert http.calls == [] and http2.calls == []


@pytest.mark.parametrize("query", ["", "   ", None, "长" * 101])
def test_invalid_query_returns_error_code(monkeypatch, tmp_path, query):
    service, http = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))])
    result = service.search(query)
    assert result.error["code"] == errors.INVALID_QUERY
    assert http.calls == []


def test_sync_pages_until_short_page_and_dedupes(monkeypatch, tmp_path):
    full = FakeResponse(load_fixture("search_page.json"))
    empty = FakeResponse(load_fixture("empty_page.json"))
    service, http = build(monkeypatch, tmp_path, [full, empty, full])
    result = service.sync_topic("数据安全", pages=3, per_page=5)
    assert [c["params"]["p"] for c in http.calls] == [1, 2]
    assert result.pages_fetched == 2
    assert result.stopped_reason == "last_page"
    assert result.inserted == 3 and result.new_versions == 0
    again = service.sync_topic("数据安全-再次", pages=1, per_page=20)
    assert again.inserted == 0 and again.unchanged == 3
    assert service.store.count() == 3


def test_sync_never_exceeds_twenty_pages(monkeypatch, tmp_path):
    service, http = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))])
    result = service.sync_topic("数据安全", pages=999, per_page=5)
    assert result.pages_requested == 20
    assert len(http.calls) == 20
    assert result.stopped_reason == "page_limit"


def test_sync_error_is_reported_with_progress(monkeypatch, tmp_path):
    service, _ = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json")), FakeResponse(status_code=403, text="")])
    result = service.sync_topic("数据安全", pages=3, per_page=5)
    assert result.pages_fetched == 1
    assert result.inserted == 3
    assert result.error["code"] == errors.REMOTE_HTTP_ERROR
    assert result.stopped_reason == "error"


def test_unexpected_exceptions_become_internal_error(monkeypatch, tmp_path):
    service, _ = build(monkeypatch, tmp_path, [FakeResponse(load_fixture("search_page.json"))])

    def boom(*a, **k):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(service.store, "search_local", boom)
    result = service.search("数据")
    assert result.error["code"] == errors.INTERNAL_ERROR
    assert "disk on fire" not in result.error["message"]
