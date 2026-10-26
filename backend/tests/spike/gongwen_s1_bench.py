"""S1 measurement for gongwen-kit `check --json` over tests/fixtures/gongwen.

Usage (from backend/): python tests/spike/gongwen_s1_bench.py [--kit DIR] [--node node] [--dir DIR]
Prints one line per fixture plus a JSON summary. Stdlib only; argument-list subprocess.
If DIR holds expected.json ({file: {rule, ...}}), each file is also scored: hit = the
expected rule was reported; blocking = that hit blocks (status "hit", exit 1).
"""
import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
FIXTURES = BACKEND / "tests" / "fixtures" / "gongwen"


def md5(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def run_check(node: str, kit: Path, docx: Path) -> dict:
    before = md5(docx)
    start = time.perf_counter()
    proc = subprocess.run(
        [node, str(kit / "bin" / "gongwen.js"), "check", str(docx), "--json"],
        capture_output=True, text=True, timeout=60,
    )
    elapsed = time.perf_counter() - start
    after = md5(docx)
    try:
        report = json.loads(proc.stdout)
    except json.JSONDecodeError:
        report = None
    hits = []
    for check in (report or {}).get("checks", []):
        for hit in check.get("hits", []):
            hits.append({"check": check.get("check"), "rule": hit.get("rule"), "blocking": hit.get("blocking")})
    return {
        "file": docx.name,
        "exit_code": proc.returncode,
        "status": (report or {}).get("status"),
        "blocking": (report or {}).get("blocking"),
        "hits": hits,
        "json_ok": report is not None,
        "stderr_bytes": len(proc.stderr.encode()),
        "seconds": round(elapsed, 3),
        "md5_unchanged": before == after,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--kit", default=str(BACKEND / "third_party" / "gongwen-kit"))
    parser.add_argument("--node", default="node")
    parser.add_argument("--dir", default=str(FIXTURES))
    args = parser.parse_args()
    kit = Path(args.kit)
    fixtures = Path(args.dir)
    files = sorted(fixtures.glob("*.docx"))
    expected_path = fixtures / "expected.json"
    expected = json.loads(expected_path.read_text(encoding="utf-8")) if expected_path.exists() else {}
    results = []
    total_start = time.perf_counter()
    for docx in files:
        r = run_check(args.node, kit, docx)
        results.append(r)
        rules = ", ".join(f"{h['rule']}{'' if h['blocking'] else '(hint)'}" for h in r["hits"]) or "-"
        want = expected.get(docx.name, {}).get("rule")
        if want:
            matched = [h for h in r["hits"] if h["rule"] == want]
            r["expected_rule"] = want
            r["detected"] = bool(matched)
            r["detected_blocking"] = any(h["blocking"] for h in matched)
            rules += f"  expect={want} detected={r['detected']} blocking={r['detected_blocking']}"
        print(f"{r['file']:<32} exit={r['exit_code']} status={r['status']:<5} {r['seconds']:.3f}s "
              f"md5_same={r['md5_unchanged']} hits=[{rules}]")
    summary = {"files": len(files), "total_seconds": round(time.perf_counter() - total_start, 3),
               "max_seconds": max(r["seconds"] for r in results)}
    if expected:
        scored = [r for r in results if "expected_rule" in r]
        summary["detected"] = f"{sum(r['detected'] for r in scored)}/{len(scored)}"
        summary["detected_blocking"] = f"{sum(r['detected_blocking'] for r in scored)}/{len(scored)}"
    print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
