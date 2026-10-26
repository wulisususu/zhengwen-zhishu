"""SafeFetcher SSRF guard: scheme, allowlist, private IPs, redirects, size. No real network."""
from __future__ import annotations

import socket

import pytest

from app.services.policy import errors
from app.services.policy.errors import PolicyError
from app.services.policy.fetcher import RawResponse, SafeFetcher, is_public_ip
from app.services.policy.settings import fetch_settings_from_mapping
from policy_support import FakeClock, block_network  # noqa: F401

pytestmark = pytest.mark.usefixtures("block_network")

PUBLIC_IP = "203.119.25.1"


def resolver_for(mapping):
    def resolve(host, port, *args, **kwargs):
        ips = mapping.get(host)
        if ips is None:
            raise socket.gaierror("no such host")
        return [(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in ips]

    return resolve


class FakeOpener:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, target, ip, timeout, max_bytes):
        self.calls.append({"url": target.url, "host": target.host, "ip": ip, "timeout": timeout, "max_bytes": max_bytes})
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def html(body="<div id='UCAP-CONTENT'><p>第一条　正文。</p></div>", status=200, headers=None):
    return RawResponse(status=status, headers={"content-type": "text/html; charset=utf-8", **(headers or {})}, body=body.encode("utf-8"))


def make(opener, dns=None, mode="cloud_allowed", **fetch):
    clock = FakeClock()
    dns = dns if dns is not None else {"www.gov.cn": [PUBLIC_IP], "sousuo.www.gov.cn": [PUBLIC_IP]}
    return SafeFetcher(
        fetch_settings_from_mapping(fetch),
        resolver=resolver_for(dns),
        opener=opener,
        mode_provider=lambda: mode,
        sleep=clock.sleep,
        clock=clock.monotonic,
    )


@pytest.mark.parametrize(
    "ip, public",
    [
        ("10.0.0.5", False), ("172.16.3.4", False), ("172.31.255.255", False), ("192.168.1.10", False),
        ("127.0.0.1", False), ("169.254.169.254", False), ("::1", False), ("fd00::1", False),
        ("fe80::1", False), ("0.0.0.0", False), ("100.64.0.1", False), ("::ffff:10.0.0.1", False),
        ("203.119.25.1", True), ("2400:da00::1", True),
    ],
)
def test_is_public_ip(ip, public):
    assert is_public_ip(ip) is public


def test_fetches_allowed_host_with_pinned_ip():
    opener = FakeOpener([html()])
    result = make(opener).fetch("https://www.gov.cn/zhengce/content/202401/content_1.htm")
    assert result.final_url == "https://www.gov.cn/zhengce/content/202401/content_1.htm"
    assert opener.calls[0]["ip"] == PUBLIC_IP
    assert opener.calls[0]["timeout"] == 15.0
    assert opener.calls[0]["max_bytes"] == 10 * 1024 * 1024


@pytest.mark.parametrize("url", ["ftp://www.gov.cn/a", "file:///etc/passwd", "gopher://www.gov.cn/", "javascript:alert(1)", "www.gov.cn/a", ""])
def test_rejects_non_http_schemes(url):
    with pytest.raises(PolicyError) as exc:
        make(FakeOpener([])).fetch(url)
    assert exc.value.code == errors.FETCH_BAD_URL


@pytest.mark.parametrize(
    "url",
    [
        "https://evil.example.com/a",
        "https://www.gov.cn.evil.com/a",
        "https://evilwww.gov.cn/a",
        "https://www.miit.gov.cn/a",  # department sites need explicit config
        "https://user:pw@www.gov.cn/a",
        "https://www.gov.cn:8443/a",
    ],
)
def test_rejects_hosts_outside_allowlist(url):
    opener = FakeOpener([])
    with pytest.raises(PolicyError) as exc:
        make(opener).fetch(url)
    assert exc.value.code in (errors.FETCH_HOST_NOT_ALLOWED, errors.FETCH_BAD_URL)
    assert opener.calls == []


def test_department_site_allowed_when_configured():
    opener = FakeOpener([html()])
    fetcher = make(opener, dns={"www.miit.gov.cn": [PUBLIC_IP]}, extra_allowed_hosts=["www.miit.gov.cn"])
    assert fetcher.fetch("https://www.miit.gov.cn/a").status == 200


@pytest.mark.parametrize("private_ip", ["10.1.2.3", "127.0.0.1", "169.254.169.254", "192.168.0.117", "::1", "fd00::5"])
def test_rejects_allowlisted_host_resolving_to_private_address(private_ip):
    opener = FakeOpener([html()])
    with pytest.raises(PolicyError) as exc:
        make(opener, dns={"www.gov.cn": [private_ip]}).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_PRIVATE_ADDRESS
    assert opener.calls == []


def test_rejects_when_any_resolved_address_is_private():
    opener = FakeOpener([html()])
    with pytest.raises(PolicyError) as exc:
        make(opener, dns={"www.gov.cn": [PUBLIC_IP, "10.0.0.1"]}).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_PRIVATE_ADDRESS


def test_rejects_literal_ip_urls():
    with pytest.raises(PolicyError) as exc:
        make(FakeOpener([])).fetch("http://127.0.0.1/admin")
    assert exc.value.code == errors.FETCH_HOST_NOT_ALLOWED


def test_dns_failure_is_reported():
    with pytest.raises(PolicyError) as exc:
        make(FakeOpener([]), dns={}).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_DNS_FAILED


def test_follows_up_to_two_redirects_revalidating_each_hop():
    opener = FakeOpener([
        html(status=302, headers={"location": "https://sousuo.www.gov.cn/b"}),
        html(status=301, headers={"location": "/c"}),
        html(),
    ])
    result = make(opener).fetch("https://www.gov.cn/a")
    assert [c["url"] for c in opener.calls] == ["https://www.gov.cn/a", "https://sousuo.www.gov.cn/b", "https://sousuo.www.gov.cn/c"]
    assert result.redirects == 2


def test_third_redirect_is_refused():
    opener = FakeOpener([html(status=302, headers={"location": f"https://www.gov.cn/{i}"}) for i in range(4)])
    with pytest.raises(PolicyError) as exc:
        make(opener).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_TOO_MANY_REDIRECTS
    assert len(opener.calls) == 3


def test_redirect_to_disallowed_host_is_refused():
    opener = FakeOpener([html(status=302, headers={"location": "http://169.254.169.254/latest/meta-data"})])
    with pytest.raises(PolicyError) as exc:
        make(opener).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_HOST_NOT_ALLOWED
    assert len(opener.calls) == 1


def test_redirect_to_allowlisted_host_with_private_dns_is_refused():
    opener = FakeOpener([html(status=302, headers={"location": "https://sousuo.www.gov.cn/x"})])
    dns = {"www.gov.cn": [PUBLIC_IP], "sousuo.www.gov.cn": ["10.0.0.8"]}
    with pytest.raises(PolicyError) as exc:
        make(opener, dns=dns).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_PRIVATE_ADDRESS


def test_oversized_body_is_refused():
    from app.services.policy.fetcher import BodyTooLarge

    opener = FakeOpener([BodyTooLarge()])
    with pytest.raises(PolicyError) as exc:
        make(opener).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_TOO_LARGE


def test_declared_oversized_content_length_is_refused():
    big = RawResponse(status=200, headers={"content-type": "text/html", "content-length": str(11 * 1024 * 1024)}, body=b"")
    with pytest.raises(PolicyError) as exc:
        make(FakeOpener([big])).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_TOO_LARGE


def test_timeout_and_http_errors_have_codes():
    with pytest.raises(PolicyError) as exc:
        make(FakeOpener([TimeoutError()])).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_TIMEOUT
    with pytest.raises(PolicyError) as exc:
        make(FakeOpener([html(status=404)])).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.FETCH_HTTP_ERROR


def test_pdf_is_unsupported_content():
    pdf = RawResponse(status=200, headers={"content-type": "application/pdf"}, body=b"%PDF-1.7")
    with pytest.raises(PolicyError) as exc:
        make(FakeOpener([pdf])).fetch("https://www.gov.cn/a.pdf")
    assert exc.value.code == errors.FETCH_UNSUPPORTED_CONTENT


@pytest.mark.parametrize("mode", ["intranet", "offline"])
def test_blocked_egress_mode_never_resolves_or_connects(mode):
    opener = FakeOpener([html()])
    with pytest.raises(PolicyError) as exc:
        make(opener, mode=mode).fetch("https://www.gov.cn/a")
    assert exc.value.code == errors.EGRESS_BLOCKED
    assert opener.calls == []


def test_timeout_and_size_cannot_be_configured_above_limits():
    settings = fetch_settings_from_mapping({"timeout_seconds": 60, "max_bytes": 10**9, "max_redirects": 9})
    assert settings.timeout_seconds == 15.0
    assert settings.max_bytes == 10 * 1024 * 1024
    assert settings.max_redirects == 2
