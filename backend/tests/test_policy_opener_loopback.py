"""The real urllib3 opener, exercised against an in-process server on 127.0.0.1.

No external network: the server lives in this test process. SafeFetcher itself
would refuse 127.0.0.1, so the opener is called directly with a pinned IP.
"""
from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app.services.policy.fetcher import BodyTooLarge, Target, _default_opener


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "https://www.gov.cn/next")
            self.end_headers()
            return
        size = 4096 if self.path == "/big" else 0
        body = ("<p>第一条　正文。</p>" + "x" * size).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Seen-Host", self.headers.get("Host", ""))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield httpd.server_address[1]
    httpd.shutdown()


def target(port, path):
    return Target(url=f"http://www.gov.cn{path}", scheme="http", host="www.gov.cn", port=port, path=path)


def test_pinned_ip_keeps_hostname_in_host_header(server):
    raw = _default_opener(target(server, "/page"), "127.0.0.1", 5.0, 1024)
    assert raw.status == 200
    assert raw.headers["x-seen-host"] == f"www.gov.cn:{server}"
    assert "第一条" in raw.body.decode("utf-8")


def test_body_over_limit_is_cut_off(server):
    with pytest.raises(BodyTooLarge):
        _default_opener(target(server, "/big"), "127.0.0.1", 5.0, 1024)


def test_redirect_is_returned_not_followed(server):
    raw = _default_opener(target(server, "/redirect"), "127.0.0.1", 5.0, 1024)
    assert raw.status == 302
    assert raw.headers["location"] == "https://www.gov.cn/next"
    assert raw.body == b""
