"""SSRF-safe fetcher for importing policy pages by URL.

Every hop (initial request and each redirect):
1. scheme must be http/https, no userinfo, default ports only;
2. host must exactly match the allowlist (policy.fetch.allowed_hosts +
   extra_allowed_hosts); literal IPs are never allowed;
3. the host is resolved and *every* address must be public — private,
   loopback, link-local (incl. 169.254.169.254 metadata), CGNAT, ULA (fd00::),
   reserved and IPv4-mapped forms are refused;
4. the connection is pinned to a validated IP (SNI/Host stay the hostname),
   so a second DNS answer cannot redirect the socket (DNS rebinding).
At most 2 redirects, body capped at 10 MB, timeout 15s. Failures raise
PolicyError with an explicit code; no text is ever fabricated.

Limitation: the pinned connection is direct. In a deployment that must go
through an HTTP proxy to reach the internet this opener cannot connect.
"""
from __future__ import annotations

import ipaddress
import logging
import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable
from urllib.parse import urljoin, urlsplit

from app.services.policy import errors
from app.services.policy.client import egress_mode, remote_allowed
from app.services.policy.errors import PolicyError
from app.services.policy.settings import FetchSettings

logger = logging.getLogger("app.policy.fetcher")

USER_AGENT = "InNetBox-PolicyImport/1.0"
REDIRECT_STATUSES = {301, 302, 303, 307, 308}
ACCEPTED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")
DEFAULT_PORTS = {"http": 80, "https": 443}
MIN_INTERVAL_SECONDS = 1.0


class BodyTooLarge(Exception):
    pass


@dataclass(frozen=True)
class Target:
    url: str
    scheme: str
    host: str
    port: int
    path: str


@dataclass
class RawResponse:
    status: int
    headers: dict = field(default_factory=dict)  # lower-case keys
    body: bytes = b""


@dataclass
class FetchResult:
    final_url: str
    status: int
    content_type: str
    charset: str | None
    body: bytes
    redirects: int


def is_public_ip(value: str) -> bool:
    try:
        ip = ipaddress.ip_address(value.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    blocked = (
        ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast
        or ip.is_reserved or ip.is_unspecified or not ip.is_global
    )
    return not blocked


def _default_opener(target: Target, ip: str, timeout: float, max_bytes: int) -> RawResponse:
    import certifi
    import urllib3

    timeouts = urllib3.Timeout(connect=timeout, read=timeout)
    if target.scheme == "https":
        pool = urllib3.HTTPSConnectionPool(
            ip, port=target.port, timeout=timeouts, retries=False, maxsize=1,
            server_hostname=target.host, assert_hostname=target.host,
            cert_reqs="CERT_REQUIRED", ca_certs=certifi.where(),
        )
    else:
        pool = urllib3.HTTPConnectionPool(ip, port=target.port, timeout=timeouts, retries=False, maxsize=1)
    host_header = target.host if target.port == DEFAULT_PORTS[target.scheme] else f"{target.host}:{target.port}"
    try:
        resp = pool.urlopen(
            "GET", target.path, redirect=False, preload_content=False, retries=False,
            headers={"Host": host_header, "User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9"},
        )
    except urllib3.exceptions.TimeoutError as exc:
        raise TimeoutError() from exc
    try:
        headers = {k.lower(): v for k, v in resp.headers.items()}
        if resp.status in REDIRECT_STATUSES:
            return RawResponse(resp.status, headers, b"")
        chunks, size = [], 0
        for chunk in resp.stream(64 * 1024):
            size += len(chunk)
            if size > max_bytes:
                raise BodyTooLarge()
            chunks.append(chunk)
        return RawResponse(resp.status, headers, b"".join(chunks))
    except urllib3.exceptions.TimeoutError as exc:
        raise TimeoutError() from exc
    finally:
        resp.release_conn()
        pool.close()


class SafeFetcher:
    def __init__(
        self,
        settings: FetchSettings,
        *,
        resolver: Callable = socket.getaddrinfo,
        opener: Callable = _default_opener,
        mode_provider: Callable[[], str] = egress_mode,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.settings = settings
        self._resolver = resolver
        self._opener = opener
        self._mode_provider = mode_provider
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last_at: float | None = None

    def check_url(self, url: str) -> Target:
        try:
            parts = urlsplit((url or "").strip())
        except ValueError:
            raise PolicyError(errors.FETCH_BAD_URL, "URL 格式无效。") from None
        scheme = (parts.scheme or "").lower()
        if scheme not in DEFAULT_PORTS or not parts.hostname:
            raise PolicyError(errors.FETCH_BAD_URL, "只允许 http / https 地址。")
        if parts.username or parts.password:
            raise PolicyError(errors.FETCH_BAD_URL, "URL 不得包含用户名或密码。")
        host = parts.hostname.lower().rstrip(".")
        try:
            port = parts.port or DEFAULT_PORTS[scheme]
        except ValueError:
            raise PolicyError(errors.FETCH_BAD_URL, "URL 端口无效。") from None
        if host not in self.settings.allowed_hosts:
            raise PolicyError(errors.FETCH_HOST_NOT_ALLOWED, f"域名 {host} 不在抓取白名单内（部门站点需在 policy.fetch.extra_allowed_hosts 显式配置）。")
        if port != DEFAULT_PORTS[scheme]:
            raise PolicyError(errors.FETCH_HOST_NOT_ALLOWED, "只允许默认端口（80 / 443）。")
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        canonical = f"{scheme}://{host}{path}"
        return Target(url=canonical, scheme=scheme, host=host, port=port, path=path)

    def resolve_public(self, target: Target) -> str:
        try:
            infos = self._resolver(target.host, target.port, 0, socket.SOCK_STREAM)
        except (socket.gaierror, OSError):
            raise PolicyError(errors.FETCH_DNS_FAILED, f"无法解析域名 {target.host}。") from None
        ips = list(dict.fromkeys(info[4][0] for info in infos))
        if not ips:
            raise PolicyError(errors.FETCH_DNS_FAILED, f"无法解析域名 {target.host}。")
        bad = [ip for ip in ips if not is_public_ip(ip)]
        if bad:
            logger.warning("policy fetch refused host=%s reason=private_address", target.host)
            raise PolicyError(errors.FETCH_PRIVATE_ADDRESS, f"域名 {target.host} 解析到内网 / 本机 / 保留地址，已拒绝。")
        return ips[0]

    def _throttle(self):
        if self._last_at is not None:
            wait = MIN_INTERVAL_SECONDS - (self._clock() - self._last_at)
            if wait > 0:
                self._sleep(wait)
        self._last_at = self._clock()

    def fetch(self, url: str) -> FetchResult:
        target = self.check_url(url)
        mode = self._mode_provider()
        if not remote_allowed(mode):
            raise PolicyError(errors.EGRESS_BLOCKED, f"当前出口模式为 {mode}，不允许抓取外部网页。")
        with self._lock:
            return self._fetch_chain(target)

    def _fetch_chain(self, target: Target) -> FetchResult:
        started = self._clock()
        redirects = 0
        while True:
            ip = self.resolve_public(target)
            self._throttle()
            try:
                raw = self._opener(target, ip, self.settings.timeout_seconds, self.settings.max_bytes)
            except BodyTooLarge:
                raise PolicyError(errors.FETCH_TOO_LARGE, "响应体超过 10 MB 上限。") from None
            except TimeoutError:
                logger.warning("policy fetch timeout host=%s", target.host)
                raise PolicyError(errors.FETCH_TIMEOUT, "抓取超时。") from None
            except PolicyError:
                raise
            except Exception as exc:
                logger.warning("policy fetch failed host=%s error=%s", target.host, type(exc).__name__)
                raise PolicyError(errors.FETCH_FAILED, "抓取失败，无法连接原文页面。") from None

            if raw.status in REDIRECT_STATUSES:
                location = raw.headers.get("location")
                if not location:
                    raise PolicyError(errors.FETCH_HTTP_ERROR, "重定向缺少目标地址。")
                redirects += 1
                if redirects > self.settings.max_redirects:
                    raise PolicyError(errors.FETCH_TOO_MANY_REDIRECTS, f"重定向超过 {self.settings.max_redirects} 次。")
                target = self.check_url(urljoin(target.url, location))
                continue

            if raw.status != 200:
                raise PolicyError(errors.FETCH_HTTP_ERROR, f"原文页面返回 HTTP {raw.status}。")
            declared = raw.headers.get("content-length")
            if declared and declared.isdigit() and int(declared) > self.settings.max_bytes:
                raise PolicyError(errors.FETCH_TOO_LARGE, "响应体超过 10 MB 上限。")
            if len(raw.body) > self.settings.max_bytes:
                raise PolicyError(errors.FETCH_TOO_LARGE, "响应体超过 10 MB 上限。")
            content_type, charset = _content_type(raw.headers.get("content-type", ""))
            if not content_type.startswith(ACCEPTED_CONTENT_TYPES):
                raise PolicyError(errors.FETCH_UNSUPPORTED_CONTENT, f"不支持的内容类型 {content_type or '未知'}（如为 PDF，请人工上传可解析的文件）。")
            logger.info(
                "policy fetch ok host=%s redirects=%d bytes=%d elapsed_ms=%d",
                target.host, redirects, len(raw.body), int((self._clock() - started) * 1000),
            )
            return FetchResult(target.url, raw.status, content_type, charset, raw.body, redirects)


def _content_type(header: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in header.split(";")]
    charset = None
    for p in parts[1:]:
        if p.lower().startswith("charset="):
            charset = p.split("=", 1)[1].strip("\"' ") or None
    return parts[0].lower(), charset
