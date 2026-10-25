"""PolicyClient: paging, retry, rate limit, cache, egress check. No real network."""
from __future__ import annotations

import pytest
import requests

from app.services.policy import errors
from app.services.policy.client import PolicyClient
from app.services.policy.errors import PolicyError
from app.services.policy.settings import settings_from_mapping
from policy_support import FakeClock, FakeHttp, FakeResponse, RealNetworkAttempted, block_network, load_fixture  # noqa: F401

BASE = "https://example.invalid/search-gov/data"


def make_client(monkeypatch, responses, *, mode="cloud_allowed", **overrides):
    settings = settings_from_mapping({"enabled": True, "base_url": BASE, "db_path": ":memory:", **overrides})
    clock = FakeClock()
    http = FakeHttp(responses)
    # Patch the real requests.get so an unpatched code path would also be caught.
    monkeypatch.setattr(requests, "get", http)
    client = PolicyClient(settings, sleep=clock.sleep, clock=clock.monotonic, mode_provider=lambda: mode)
    return client, http, clock


@pytest.mark.usefixtures("block_network")
class TestPolicyClient:
    def test_page_zero_is_normalized_to_one_and_n_is_sent(self, monkeypatch):
        client, http, _ = make_client(monkeypatch, [FakeResponse(load_fixture("search_page.json"))])
        result = client.search_page("数据安全", page=0, per_page=5)
        params = http.calls[0]["params"]
        assert params == {"t": "zhengcelibrary", "q": "数据安全", "p": 1, "n": 5}
        assert result.page == 1 and result.per_page == 5
        assert http.calls[0]["timeout"] == 15.0

    def test_negative_and_garbage_pages_are_normalized(self, monkeypatch):
        assert PolicyClient.normalize_page(-3) == 1
        assert PolicyClient.normalize_page("x") == 1
        assert PolicyClient.normalize_page(4) == 4
        assert PolicyClient.normalize_per_page(500) == 50

    def test_has_next_uses_returned_count_vs_n(self, monkeypatch):
        client, _, _ = make_client(monkeypatch, [FakeResponse(load_fixture("search_page.json"))])
        assert client.search_page("数据", page=1, per_page=5).has_next is True  # 5 raw entries == n
        client, _, _ = make_client(monkeypatch, [FakeResponse(load_fixture("search_page.json"))])
        assert client.search_page("数据", page=1, per_page=20).has_next is False

    def test_rate_limit_sleeps_between_requests(self, monkeypatch):
        page = FakeResponse(load_fixture("search_page.json"))
        client, http, clock = make_client(monkeypatch, [page])
        client.search_page("甲", page=1, per_page=20)
        clock.advance(0.3)
        client.search_page("乙", page=1, per_page=20)
        assert len(http.calls) == 2
        assert clock.sleeps and clock.sleeps[-1] == pytest.approx(0.7)

    def test_min_interval_cannot_be_configured_below_one_second(self, monkeypatch):
        client, _, _ = make_client(monkeypatch, [FakeResponse(load_fixture("search_page.json"))], min_interval_seconds=0.1)
        assert client.settings.min_interval_seconds == 1.0

    def test_cache_hit_does_not_send_a_second_request(self, monkeypatch):
        client, http, clock = make_client(monkeypatch, [FakeResponse(load_fixture("search_page.json"))])
        first = client.search_page("数据安全", page=1, per_page=20)
        clock.advance(120)
        second = client.search_page("数据安全", page=1, per_page=20)
        assert len(http.calls) == 1
        assert second.from_cache is True
        assert [r.url for r in second.records] == [r.url for r in first.records]

    def test_cache_expires_after_ttl(self, monkeypatch):
        client, http, clock = make_client(monkeypatch, [FakeResponse(load_fixture("search_page.json"))])
        client.search_page("数据安全", page=1, per_page=20)
        clock.advance(301)
        client.search_page("数据安全", page=1, per_page=20)
        assert len(http.calls) == 2

    def test_retries_timeouts_at_most_twice(self, monkeypatch):
        client, http, _ = make_client(monkeypatch, [requests.Timeout("t")] * 3)
        with pytest.raises(PolicyError) as exc:
            client.search_page("数据", page=1)
        assert exc.value.code == errors.REMOTE_TIMEOUT
        assert len(http.calls) == 3  # 1 attempt + 2 retries

    def test_retries_5xx_then_succeeds(self, monkeypatch):
        client, http, _ = make_client(monkeypatch, [FakeResponse(status_code=502, text=""), FakeResponse(load_fixture("search_page.json"))])
        result = client.search_page("数据", page=1)
        assert len(http.calls) == 2
        assert len(result.records) == 3

    def test_does_not_retry_4xx(self, monkeypatch):
        client, http, _ = make_client(monkeypatch, [FakeResponse(status_code=404, text="")])
        with pytest.raises(PolicyError) as exc:
            client.search_page("数据", page=1)
        assert exc.value.code == errors.REMOTE_HTTP_ERROR
        assert len(http.calls) == 1

    def test_does_not_retry_connection_errors(self, monkeypatch):
        client, http, _ = make_client(monkeypatch, [requests.ConnectionError("refused")])
        with pytest.raises(PolicyError) as exc:
            client.search_page("数据", page=1)
        assert exc.value.code == errors.REMOTE_UNAVAILABLE
        assert len(http.calls) == 1

    def test_bad_json_is_reported_not_raised_raw(self, monkeypatch):
        client, _, _ = make_client(monkeypatch, [FakeResponse(payload=None, text="<html>")])
        with pytest.raises(PolicyError) as exc:
            client.search_page("数据", page=1)
        assert exc.value.code == errors.REMOTE_BAD_RESPONSE

    @pytest.mark.parametrize("mode", ["intranet", "offline"])
    def test_blocked_modes_never_send_requests(self, monkeypatch, mode):
        client, http, _ = make_client(monkeypatch, [FakeResponse(load_fixture("search_page.json"))], mode=mode)
        with pytest.raises(PolicyError) as exc:
            client.search_page("数据", page=1)
        assert exc.value.code == errors.EGRESS_BLOCKED
        assert http.calls == []

    def test_missing_base_url_is_not_configured(self, monkeypatch):
        client, http, _ = make_client(monkeypatch, [FakeResponse(load_fixture("search_page.json"))], base_url="")
        with pytest.raises(PolicyError) as exc:
            client.search_page("数据", page=1)
        assert exc.value.code == errors.NOT_CONFIGURED
        assert http.calls == []


def test_block_network_fixture_catches_real_requests(block_network):
    with pytest.raises(RealNetworkAttempted):
        requests.get("https://sousuo.www.gov.cn/search-gov/data", timeout=1)
