"""Shared helpers for the policy retrieval tests.

Every policy test must run without real network access. ``block_network``
makes any real socket connection or un-patched ``requests`` call fail the
test loudly.
"""
from __future__ import annotations

import json
import pathlib
import socket

import pytest

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures" / "policy"


class RealNetworkAttempted(AssertionError):
    pass


def load_fixture(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


@pytest.fixture()
def block_network(monkeypatch):
    def _refuse(*args, **kwargs):
        raise RealNetworkAttempted(f"测试中发生了真实网络请求: {args!r}")

    monkeypatch.setattr(socket.socket, "connect", _refuse)
    monkeypatch.setattr(socket.socket, "connect_ex", _refuse)
    monkeypatch.setattr(socket, "create_connection", _refuse)
    import requests

    monkeypatch.setattr(requests, "get", _refuse)
    monkeypatch.setattr(requests.Session, "request", _refuse)


class FakeResponse:
    def __init__(self, payload=None, status_code: int = 200, text: str | None = None):
        self._payload = payload
        self.status_code = status_code
        self.text = text if text is not None else json.dumps(payload, ensure_ascii=False)

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeHttp:
    """Stands in for ``requests.get``; records every call."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls: list[dict] = []

    def __call__(self, url, params=None, timeout=None, headers=None):
        self.calls.append({"url": url, "params": dict(params or {}), "timeout": timeout})
        item = self._responses.pop(0) if len(self._responses) > 1 else self._responses[0]
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds

    def advance(self, seconds: float) -> None:
        self.now += seconds
