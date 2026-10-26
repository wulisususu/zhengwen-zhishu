"""OpenDataLoader PDF benchmark (spike). Measures the exact JVM command the
adapter builds, under /usr/bin/time -v, and also the adapter end to end.

    .venv-pdf/bin/python tests/spike/odl_benchmark.py <case>=<pdf>[,<pdf>...] ... [--runs 3] [--json out.json]

Example (real gov.cn samples):
    .venv-pdf/bin/python tests/spike/odl_benchmark.py \
        D=/srv/box/in/policy-pdfs/D_*.pdf  batchABCD=/srv/box/in/policy-pdfs/A_*.pdf,...

Reports per case: pages, wall seconds (mean / max over runs), seconds per page,
max RSS of the JVM (KB from /usr/bin/time -v, "Maximum resident set size").
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BACKEND))

from app.services import opendataloader_pdf_adapter as odl  # noqa: E402

TIME_BIN = "/usr/bin/time"
_RSS = re.compile(r"Maximum resident set size \(kbytes\):\s*(\d+)")
_WALL = re.compile(r"Elapsed \(wall clock\) time \(h:mm:ss or m:ss\):\s*([\d:.]+)")


def _seconds(text: str) -> float:
    parts = [float(p) for p in text.split(":")]
    total = 0.0
    for p in parts:
        total = total * 60 + p
    return total


def measure_jvm(pdfs: list[Path], config: odl.AdapterConfig) -> dict:
    jar = odl.locate_jar(config)
    work = Path(tempfile.mkdtemp(prefix="odl-bench-"))
    try:
        in_dir, out_dir, jtmp = work / "in", work / "out", work / "jtmp"
        for d in (in_dir, out_dir, jtmp):
            d.mkdir()
        staged = []
        for n, src in enumerate(pdfs, start=1):
            link = in_dir / f"f{n:04d}.pdf"
            link.symlink_to(src.resolve())
            staged.append(link)
        cmd = [TIME_BIN, "-v", *odl.build_command(staged, out_dir, jar=jar, config=config, java_tmp=jtmp)]
        started = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=config.timeout_seconds)
        wall = time.monotonic() - started
        outputs = sorted(p.name for p in out_dir.iterdir())
        return {
            "exit": proc.returncode,
            "wall_s": round(wall, 3),
            "time_wall_s": _seconds(_WALL.search(proc.stderr).group(1)) if _WALL.search(proc.stderr) else None,
            "max_rss_kb": int(_RSS.search(proc.stderr).group(1)) if _RSS.search(proc.stderr) else None,
            "outputs": outputs,
        }
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cases", nargs="+", help="name=path[,path...]")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--json", default="")
    ap.add_argument("--xmx", default="", help="optional JVM heap cap, e.g. 1g")
    args = ap.parse_args()
    config = odl.AdapterConfig(timeout_seconds=600, jvm_options=((f"-Xmx{args.xmx}",) if args.xmx else ()))
    report = {"java": odl.check_java(config.java_bin), "package": odl.package_version(), "runs": args.runs, "cases": []}
    for spec in args.cases:
        name, _, paths = spec.partition("=")
        pdfs = [Path(p) for p in paths.split(",") if p]
        envelopes = odl.parse_pdfs([str(p) for p in pdfs], config=config)
        pages = sum(e["page_count"] for e in envelopes)
        runs = [measure_jvm(pdfs, config) for _ in range(args.runs)]
        walls = [r["wall_s"] for r in runs]
        rss = [r["max_rss_kb"] for r in runs if r["max_rss_kb"]]
        case = {
            "case": name,
            "files": [p.name for p in pdfs],
            "pages": pages,
            "exit_codes": [r["exit"] for r in runs],
            "wall_mean_s": round(statistics.mean(walls), 2),
            "wall_max_s": round(max(walls), 2),
            "s_per_page": round(statistics.mean(walls) / pages, 3) if pages else None,
            "max_rss_mb": round(max(rss) / 1024, 1) if rss else None,
            "adapter_success": [e["success"] for e in envelopes],
            "adapter_errors": [e["error"] for e in envelopes],
        }
        report["cases"].append(case)
        print(json.dumps(case, ensure_ascii=False))
    if args.json:
        Path(args.json).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
