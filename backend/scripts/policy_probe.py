"""One real request to the policy library search, printed as a redacted structure.

    python scripts/policy_probe.py --allow-network --q 数据安全 --n 3

Sends exactly one request (the client's rate limit / retry rules still apply)
and prints: top-level keys, searchVO.catMap categories with listVO counts,
the key set and value types of the first raw item, and the cleaned records
with long text truncated. The full response body is never printed.
Without --allow-network it exits without touching the network.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import requests  # noqa: E402

from app.services.policy.client import SEARCH_TYPE, USER_AGENT  # noqa: E402
from app.services.policy.parser import CATEGORIES, parse_search_response  # noqa: E402
from app.services.policy.settings import load_settings  # noqa: E402


def _shape(value):
    if isinstance(value, str):
        return f"str(len={len(value)})"
    if isinstance(value, (int, float)):
        return type(value).__name__
    if value is None:
        return "null"
    if isinstance(value, list):
        return f"list(len={len(value)})"
    if isinstance(value, dict):
        return f"object(keys={len(value)})"
    return type(value).__name__


def _cut(text, limit=40):
    text = text or ""
    return text if len(text) <= limit else text[:limit] + "…"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--allow-network", action="store_true", help="required: actually send the request")
    ap.add_argument("--base-url", default="", help="override policy.base_url")
    ap.add_argument("--q", default="数据安全")
    ap.add_argument("--p", type=int, default=1)
    ap.add_argument("--n", type=int, default=3)
    args = ap.parse_args()
    if not args.allow_network:
        print("未加 --allow-network，未发送任何请求。")
        return 2
    settings = load_settings()
    base_url = args.base_url or settings.base_url
    if not base_url:
        print("未配置 policy.base_url，可用 --base-url 指定。")
        return 2

    params = {"t": SEARCH_TYPE, "q": args.q, "p": max(1, args.p), "n": max(1, min(50, args.n))}
    try:
        resp = requests.get(base_url, params=params, timeout=settings.timeout_seconds, headers={"User-Agent": USER_AGENT})
    except requests.RequestException as exc:
        print(json.dumps({"request": params, "error": type(exc).__name__, "detail": _cut(str(exc), 160)}, ensure_ascii=False, indent=2))
        return 1
    report = {"request": params, "http_status": resp.status_code, "elapsed_ms": int(resp.elapsed.total_seconds() * 1000)}
    try:
        payload = resp.json()
    except ValueError:
        report["error"] = "response is not JSON"
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 1

    report["top_level_keys"] = {k: _shape(v) for k, v in payload.items()} if isinstance(payload, dict) else _shape(payload)
    vo = payload.get("searchVO") if isinstance(payload, dict) else None
    if isinstance(vo, dict):
        report["searchVO_keys"] = {k: _shape(v) for k, v in vo.items()}
        cat_map = vo.get("catMap") or {}
        report["catMap"] = {c: len((cat_map.get(c) or {}).get("listVO") or []) for c in CATEGORIES if c in cat_map}
        for c in CATEGORIES:
            items = (cat_map.get(c) or {}).get("listVO") or []
            if items:
                report["first_raw_item_shape"] = {"category": c, "fields": {k: _shape(v) for k, v in items[0].items()}}
                break
    try:
        page = parse_search_response(payload)
        report["parsed"] = {
            "raw_count": page.raw_count,
            "records": [
                {"title": _cut(r.title), "doc_number": r.doc_number, "issuer": r.issuer, "publish_date": r.publish_date,
                 "category": r.category, "url": r.url, "summary": _cut(r.summary, 30)}
                for r in page.records[:3]
            ],
        }
    except Exception as exc:
        report["parse_error"] = type(exc).__name__
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
