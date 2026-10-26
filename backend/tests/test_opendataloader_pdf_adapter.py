"""OpenDataLoader adapter — MOCK tests (no Java, no opendataloader-pdf needed).

The JVM is replaced by fakes. Envelope mapping uses JSON captured from a real
opendataloader-pdf 2.5.15 run (tests/fixtures/pdf/odl_json/), so the mapping is
tested against the real output structure. Real-parse tests live in
test_opendataloader_pdf_real.py and are reported separately.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import opendataloader_pdf_adapter as odl
from app.services.opendataloader_pdf_adapter import AdapterConfig, OpenDataLoaderError

FIX = Path(__file__).resolve().parent / "fixtures" / "pdf"
CAPTURED = FIX / "odl_json"


def captured(name: str) -> dict:
    return json.loads((CAPTURED / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def _clear_java_cache():
    odl._java_cache.clear()
    yield
    odl._java_cache.clear()


@pytest.fixture()
def fake_jvm(monkeypatch, tmp_path):
    """Replace java with a fake that writes captured outputs for each staged input."""
    jar = tmp_path / "fake.jar"
    jar.write_bytes(b"PK")
    calls: list[list[str]] = []
    behaviour = {"outputs": {}, "stdout": "", "stderr": "", "returncode": 0, "raise": None, "delay": 0.0}

    def fake_run(cmd, **kwargs):
        calls.append({"cmd": list(cmd), "kwargs": kwargs})
        if cmd[1] == "-version":
            return SimpleNamespace(returncode=0, stdout="", stderr='openjdk version "17.0.20.1" 2026-08-18\n')
        if behaviour["raise"] is not None:
            raise behaviour["raise"]
        time.sleep(behaviour["delay"])
        out_dir = Path(cmd[cmd.index("--output-dir") + 1])
        inputs = [Path(a) for a in cmd[cmd.index("-jar") + 2: cmd.index("--output-dir")]]
        for staged in inputs:
            source = os.path.realpath(staged)
            fixture = behaviour["outputs"].get(Path(source).name)
            if fixture is None:
                continue
            (out_dir / f"{staged.stem}.json").write_text(json.dumps(captured(fixture)), encoding="utf-8")
            md = CAPTURED / f"{fixture}.md"
            if md.exists():
                (out_dir / f"{staged.stem}.md").write_text(md.read_text(encoding="utf-8"), encoding="utf-8")
        return SimpleNamespace(returncode=behaviour["returncode"], stdout=behaviour["stdout"], stderr=behaviour["stderr"])

    monkeypatch.setattr(odl.subprocess, "run", fake_run)
    config = AdapterConfig(jar_path=str(jar), allowed_output_roots=(str(tmp_path / "allowed"),), temp_root=str(tmp_path))
    return SimpleNamespace(calls=calls, behaviour=behaviour, config=config, tmp=tmp_path)


def pdf(tmp_path: Path, name: str, src: str = "text_3p.pdf") -> str:
    target = tmp_path / name
    target.write_bytes((FIX / src).read_bytes())
    return str(target)


def jvm_calls(fake):
    return [c for c in fake.calls if c["cmd"][1] != "-version"]


# ---------------------------------------------------------------- envelope mapping (captured real JSON)

def test_text_pdf_envelope_pages_and_markdown():
    env = odl.build_envelope(captured("text_3p"), (CAPTURED / "text_3p.md").read_text(encoding="utf-8"), version="2.5.15")
    assert env["success"] is True and env["error"] is None
    assert env["page_count"] == 3
    assert [p["page"] for p in env["pages"]] == [1, 2, 3]
    assert "第一条" in env["pages"][0]["text"] and "第五条" in env["pages"][1]["text"] and "第九条" in env["pages"][2]["text"]
    assert env["markdown"].startswith("# 示例市政务数据共享管理办法（演示）")
    assert env["metadata"] == {"parser": "opendataloader-pdf", "version": "2.5.15", "mode": "local", "title": env["metadata"]["title"], "elapsed_ms": 0}


def test_blocks_keep_type_page_and_bounding_box():
    env = odl.build_envelope(captured("text_3p"), "", version="x")
    heading = env["pages"][0]["blocks"][2]
    assert heading["type"] == "heading" and heading["heading_level"] == 2
    assert heading["page"] == 1 and len(heading["bbox"]) == 4
    assert all(b["page"] == p["page"] for p in env["pages"] for b in p["blocks"])


def test_table_structure_is_preserved():
    env = odl.build_envelope(captured("table_1p"), "", version="x")
    table = next(b for b in env["pages"][0]["blocks"] if b["type"] == "table")
    assert (table["rows"], table["columns"]) == (4, 4)
    header = [c for c in table["cells"] if c["row"] == 1]
    assert [c["text"] for c in header] == ["序号", "事项名称", "责任单位", "完成时限"]
    assert all(c["is_header"] for c in header)
    cell = next(c for c in table["cells"] if c["row"] == 2 and c["col"] == 2)
    assert cell["text"] == "编制政务数据资源目录" and len(cell["bbox"]) == 4
    assert table["text"].splitlines()[0] == "序号\t事项名称\t责任单位\t完成时限"
    assert not any("表格" in w for w in env["warnings"])


def test_broken_table_geometry_produces_warning():
    doc = captured("table_1p")
    table = next(k for k in doc["kids"] if k["type"] == "table")
    table["rows"][1]["cells"].pop()
    env = odl.build_envelope(doc, "", version="x")
    assert any("表格" in w and "不一致" in w for w in env["warnings"])


def test_scanned_page_is_reported_not_faked():
    env = odl.build_envelope(captured("scanned_1p"), "![](x.png)", version="x")
    assert env["success"] is False
    assert env["error"].startswith("NO_TEXT")
    assert env["markdown"] == ""
    assert env["page_count"] == 1
    assert any("疑似扫描件" in w and "OCR" in w for w in env["warnings"])


def test_text_block_and_list_items_are_not_dropped():
    """Regression from the real gov.cn sample B: page 8 is one ``text block``
    wrapping a ``list`` whose items carry both ``content`` and ``kids``."""
    doc = captured("real_B_p7-9")
    raw_chars = 0

    def collect(node):
        nonlocal raw_chars
        if isinstance(node.get("content"), str):
            raw_chars += len("".join(node["content"].split()))
        for key in ("kids", "list items"):
            for child in node.get(key) or []:
                collect(child)
        for row in node.get("rows") or []:
            for cell in row.get("cells") or []:
                collect(cell)

    for node in doc["kids"]:
        collect(node)
    env = odl.build_envelope(doc, "", version="x")
    page8 = next(p for p in env["pages"] if p["page"] == 8)
    assert page8["text"].strip(), "page 8 text was dropped"
    assert all(b["type"] != "text block" for p in env["pages"] for b in p["blocks"])  # container flattened
    got = sum(len("".join(p["text"].split())) for p in env["pages"])
    assert got == raw_chars
    lists = [b for p in env["pages"] for b in p["blocks"] if b["type"] == "list"]
    assert lists and all(item["bbox"] for b in lists for item in b["items"])


def test_scanned_document_with_frame_tables_is_flagged_as_scan():
    doc = {"number of pages": 2, "kids": [
        {"type": "table", "id": 1, "page number": 1, "bounding box": [0, 0, 1, 1], "number of rows": 1, "number of columns": 1,
         "rows": [{"type": "table row", "row number": 1, "cells": [{"type": "table cell", "row number": 1, "column number": 1, "kids": []}]}]},
    ]}
    env = odl.build_envelope(doc, "| |\n|---|", version="x")
    assert env["success"] is False and env["markdown"] == ""
    assert env["warnings"][0].startswith("整份文件没有可提取的文本层")
    assert any("空表格" in w for w in env["warnings"])
    assert any(w.startswith("第1页无文本层") for w in env["warnings"])


def test_invalid_json_shape_is_rejected():
    with pytest.raises(OpenDataLoaderError) as exc:
        odl.build_envelope({"unexpected": True}, "", version="x")
    assert exc.value.code == OpenDataLoaderError.OUTPUT_INVALID


def test_block_without_page_number_is_warned():
    doc = captured("text_3p")
    doc["kids"][0].pop("page number")
    env = odl.build_envelope(doc, "", version="x")
    assert any("缺少页码" in w for w in env["warnings"])


# ---------------------------------------------------------------- environment errors

def test_not_installed_returns_explicit_error(monkeypatch, tmp_path):
    monkeypatch.setattr(odl.importlib.util, "find_spec", lambda name: None)
    env = odl.parse_pdf(pdf(tmp_path, "a.pdf"))
    assert env["success"] is False
    assert env["error"].startswith("NOT_INSTALLED")
    assert env["pages"] == [] and env["markdown"] == ""


def test_real_environment_without_package_reports_not_installed(tmp_path):
    # This test venv genuinely has no opendataloader-pdf installed.
    if odl.importlib.util.find_spec("opendataloader_pdf") is not None:
        pytest.skip("opendataloader-pdf is installed in this environment")
    assert odl.parse_pdf(pdf(tmp_path, "a.pdf"))["error"].startswith("NOT_INSTALLED")


def test_missing_java_is_explicit(tmp_path):
    jar = tmp_path / "x.jar"
    jar.write_bytes(b"PK")
    env = odl.parse_pdf(pdf(tmp_path, "a.pdf"), config=AdapterConfig(jar_path=str(jar), java_bin=str(tmp_path / "no-java")))
    assert env["error"].startswith("JAVA_NOT_FOUND")


def test_old_java_is_rejected(monkeypatch, tmp_path):
    jar = tmp_path / "x.jar"
    jar.write_bytes(b"PK")
    monkeypatch.setattr(odl.subprocess, "run", lambda cmd, **k: SimpleNamespace(returncode=0, stdout="", stderr='java version "1.8.0_292"'))
    env = odl.parse_pdf(pdf(tmp_path, "a.pdf"), config=AdapterConfig(jar_path=str(jar)))
    assert env["error"].startswith("JAVA_TOO_OLD")


@pytest.mark.parametrize("content, code", [(b"", "INVALID_INPUT"), (b"hello, not a pdf", "INVALID_INPUT")])
def test_empty_and_non_pdf_inputs_never_reach_the_jvm(fake_jvm, content, code):
    path = fake_jvm.tmp / "bad.pdf"
    path.write_bytes(content)
    env = odl.parse_pdf(str(path), config=fake_jvm.config)
    assert env["success"] is False and env["error"].startswith(code)
    assert jvm_calls(fake_jvm) == []


def test_missing_file(fake_jvm):
    assert odl.parse_pdf(str(fake_jvm.tmp / "nope.pdf"), config=fake_jvm.config)["error"].startswith("INVALID_INPUT")


def test_corrupt_file_error_comes_from_cli(fake_jvm):
    corrupt = pdf(fake_jvm.tmp, "broken.pdf", "corrupt.pdf")
    fake_jvm.behaviour.update(returncode=1, stdout="Error: 'f0001.pdf' is not a valid PDF file (corrupted or truncated content).\n")
    env = odl.parse_pdf(corrupt, config=fake_jvm.config)
    assert env["success"] is False
    assert env["error"] == "CLI_FAILED: 'broken.pdf' is not a valid PDF file (corrupted or truncated content)."


# ---------------------------------------------------------------- output_dir guard

@pytest.mark.parametrize("bad", ["../escape", "/etc", "/tmp", "allowed/../../outside", ""])
def test_output_dir_outside_allowed_root_is_rejected(fake_jvm, bad, monkeypatch):
    monkeypatch.chdir(fake_jvm.tmp)
    env = odl.parse_pdf(pdf(fake_jvm.tmp, "a.pdf"), output_dir=bad, config=fake_jvm.config)
    assert env["success"] is False and env["error"].startswith("OUTPUT_DIR_REJECTED")
    assert jvm_calls(fake_jvm) == []


def test_symlink_escape_is_rejected(fake_jvm, tmp_path):
    allowed = fake_jvm.tmp / "allowed"
    allowed.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (allowed / "link").symlink_to(outside)
    env = odl.parse_pdf(pdf(fake_jvm.tmp, "a.pdf"), output_dir=str(allowed / "link"), config=fake_jvm.config)
    assert env["error"].startswith("OUTPUT_DIR_REJECTED")


def test_output_dir_inside_root_receives_outputs(fake_jvm):
    fake_jvm.behaviour["outputs"] = {"a.pdf": "text_3p"}
    dest = fake_jvm.tmp / "allowed" / "job1"
    env = odl.parse_pdf(pdf(fake_jvm.tmp, "a.pdf"), output_dir=str(dest), config=fake_jvm.config)
    assert env["success"] is True
    assert sorted(p.name for p in dest.iterdir()) == ["a.json", "a.md"]
    assert env["metadata"]["output_files"][0] == str(dest / "a.json")


# ---------------------------------------------------------------- subprocess contract

def test_jvm_is_called_with_argument_list_timeout_and_local_mode(fake_jvm):
    fake_jvm.behaviour["outputs"] = {"a.pdf": "text_3p"}
    config = AdapterConfig(**{**fake_jvm.config.__dict__, "timeout_seconds": 42, "jvm_options": ("-Xmx1g",)})
    odl.parse_pdf(pdf(fake_jvm.tmp, "a.pdf"), config=config)
    (call,) = jvm_calls(fake_jvm)
    cmd, kwargs = call["cmd"], call["kwargs"]
    assert isinstance(cmd, list) and kwargs.get("shell") is False
    assert kwargs["timeout"] == 42
    assert "-Xmx1g" in cmd and cmd[cmd.index("--image-output") + 1] == "off"
    assert not any(a.startswith("--hybrid") for a in cmd)
    assert cmd[cmd.index("--format") + 1] == "json,markdown"


def test_option_like_and_duplicate_file_names_are_staged_safely(fake_jvm):
    weird = fake_jvm.tmp / "--output-dir=evil.pdf"
    weird.write_bytes((FIX / "text_3p.pdf").read_bytes())
    sub = fake_jvm.tmp / "sub"
    sub.mkdir()
    same_name = sub / "--output-dir=evil.pdf"
    same_name.write_bytes((FIX / "table_1p.pdf").read_bytes())
    fake_jvm.behaviour["outputs"] = {weird.name: "text_3p"}
    odl.parse_pdfs([str(weird), str(same_name)], config=fake_jvm.config)
    (call,) = jvm_calls(fake_jvm)
    inputs = call["cmd"][call["cmd"].index("-jar") + 2: call["cmd"].index("--output-dir")]
    assert [Path(p).name for p in inputs] == ["f0001.pdf", "f0002.pdf"]


def test_timeout_is_explicit_and_temp_files_are_cleaned(fake_jvm):
    fake_jvm.behaviour["raise"] = subprocess.TimeoutExpired(cmd="java", timeout=1)
    env = odl.parse_pdf(pdf(fake_jvm.tmp, "a.pdf"), config=fake_jvm.config)
    assert env["success"] is False and env["error"].startswith("TIMEOUT")
    assert not list(fake_jvm.tmp.glob("odl-*"))


def test_temp_files_are_cleaned_after_success(fake_jvm):
    fake_jvm.behaviour["outputs"] = {"a.pdf": "text_3p"}
    assert odl.parse_pdf(pdf(fake_jvm.tmp, "a.pdf"), config=fake_jvm.config)["success"] is True
    assert not list(fake_jvm.tmp.glob("odl-*"))


def test_batch_uses_one_jvm_and_keeps_order_with_partial_failure(fake_jvm):
    a = pdf(fake_jvm.tmp, "a.pdf")
    b = pdf(fake_jvm.tmp, "b.pdf", "table_1p.pdf")
    c = pdf(fake_jvm.tmp, "c.pdf", "corrupt.pdf")
    empty = fake_jvm.tmp / "e.pdf"
    empty.write_bytes(b"")
    fake_jvm.behaviour.update(outputs={"a.pdf": "text_3p", "b.pdf": "table_1p"}, returncode=1,
                              stdout="Error: 'f0003.pdf' is not a valid PDF file (corrupted or truncated content).\n")
    results = odl.parse_pdfs([a, b, c, str(empty)], config=fake_jvm.config)
    assert len(jvm_calls(fake_jvm)) == 1
    assert [r["success"] for r in results] == [True, True, False, False]
    assert results[1]["page_count"] == 1 and results[0]["page_count"] == 3
    assert "'c.pdf'" in results[2]["error"] and results[3]["error"].startswith("INVALID_INPUT")
    assert results[0]["metadata"]["batch_size"] == 3


def test_cli_warnings_are_attributed_per_file(fake_jvm):
    fake_jvm.behaviour.update(outputs={"a.pdf": "text_3p", "b.pdf": "table_1p"}, stderr=(
        "INFO: File name: /x/in/f0001.pdf\nWARNING: Incorrect bfrange in toUnicode CMap\nWARNING: Incorrect bfrange in toUnicode CMap\n"
        "INFO: File name: /x/in/f0002.pdf\nWARNING: Detected background on page 1\n"))
    a, b = odl.parse_pdfs([pdf(fake_jvm.tmp, "a.pdf"), pdf(fake_jvm.tmp, "b.pdf", "table_1p.pdf")], config=fake_jvm.config)
    assert any("2 条警告" in w for w in a["warnings"])
    assert any("1 条警告" in w and "background" in w for w in b["warnings"])


# ---------------------------------------------------------------- concurrency (single uvicorn worker)

def _concurrency_app(fake_jvm, path):
    from fastapi import FastAPI

    app = FastAPI()

    @app.get("/parse-async")
    async def parse_async():
        env = await odl.parse_pdf_async(path, config=fake_jvm.config)
        return {"success": env["success"]}

    @app.get("/parse-blocking")
    async def parse_blocking():  # anti-pattern on purpose: blocks the event loop
        env = odl.parse_pdf(path, config=fake_jvm.config)
        return {"success": env["success"]}

    @app.get("/ping")
    async def ping():
        return {"ok": True}

    return app


async def _probe(app, parse_path: str) -> tuple[float, float]:
    """Start a parse, then a ping 0.1s later. Returns (seconds until ping answered, total).

    Both are measured from the start: if the loop is blocked, even the 0.1s
    sleep cannot return until the parse finishes.
    """
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        started = time.monotonic()
        parse_task = asyncio.create_task(client.get(parse_path))
        await asyncio.sleep(0.1)  # parse is now in progress
        assert (await client.get("/ping")).status_code == 200
        ping_done = time.monotonic() - started
        assert (await parse_task).json() == {"success": True}
        return ping_done, time.monotonic() - started


def test_async_parse_does_not_block_other_requests(fake_jvm):
    fake_jvm.behaviour.update(outputs={"a.pdf": "text_3p"}, delay=1.5)
    app = _concurrency_app(fake_jvm, pdf(fake_jvm.tmp, "a.pdf"))
    ping_done, total = asyncio.run(_probe(app, "/parse-async"))
    assert total >= 1.5
    assert ping_done < 0.6, f"ping answered after {ping_done:.2f}s while a 1.5s parse was running"


def test_calling_parse_pdf_directly_on_the_loop_would_block(fake_jvm):
    """Negative control: documents why callers must use parse_pdf_async."""
    fake_jvm.behaviour.update(outputs={"a.pdf": "text_3p"}, delay=1.0)
    app = _concurrency_app(fake_jvm, pdf(fake_jvm.tmp, "a.pdf"))
    ping_done, _ = asyncio.run(_probe(app, "/parse-blocking"))
    assert ping_done >= 0.95, f"expected the blocking call to hold ping for ~1s, got {ping_done:.2f}s"


# ---------------------------------------------------------------- regression: legacy chain untouched

def _legacy_fakes(monkeypatch):
    from app.services import file_parse_service as parser

    calls: list[str] = []

    def fake_run(cmd, **_kwargs):
        calls.append(str(cmd[0]))
        if cmd[0] == "pdftotext":
            return SimpleNamespace(returncode=0, stdout="第一条　原有链路正文。", stderr="")
        if cmd[0] == "pdfinfo":
            return SimpleNamespace(returncode=0, stdout="Pages:          1\n", stderr="")
        if cmd[0] == "pdfimages":
            return SimpleNamespace(returncode=0, stdout="page num type width height\n", stderr="")
        raise AssertionError(f"unexpected command {cmd}")

    monkeypatch.setattr(parser.subprocess, "run", fake_run)
    return parser, calls


def test_default_engine_is_legacy_and_adapter_is_never_called(monkeypatch, tmp_path):
    parser, calls = _legacy_fakes(monkeypatch)
    monkeypatch.setattr(odl, "parse_pdf", lambda *a, **k: pytest.fail("adapter must not run by default"))
    path = pdf(tmp_path, "r.pdf")
    assert odl.selected_engine() == "legacy"
    result = odl.extract_pdf_with_engine(path, legacy_extract=parser._extract_pdf)
    assert result[1]["source"] == "poppler_pdf_hybrid"


def test_adapter_failure_leaves_legacy_pdftotext_chain_unchanged(monkeypatch, tmp_path):
    parser, calls = _legacy_fakes(monkeypatch)
    path = pdf(tmp_path, "r.pdf")
    direct = parser._extract_pdf(path)
    direct_calls = list(calls)
    calls.clear()

    monkeypatch.setattr(odl.importlib.util, "find_spec", lambda name: None)  # adapter fails: not installed
    via_fallback = odl.extract_pdf_with_engine(path, engine="opendataloader", legacy_extract=parser._extract_pdf)
    assert via_fallback == direct
    assert calls == direct_calls == ["pdfinfo", "pdftotext", "pdfimages"]


def test_adapter_crash_also_falls_back(monkeypatch, tmp_path):
    parser, _ = _legacy_fakes(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(odl, "parse_pdf", boom)
    result = odl.extract_pdf_with_engine(pdf(tmp_path, "r.pdf"), engine="opendataloader", legacy_extract=parser._extract_pdf)
    assert result[1]["source"] == "poppler_pdf_hybrid"


def test_adapter_success_uses_legacy_return_shape(fake_jvm):
    fake_jvm.behaviour["outputs"] = {"a.pdf": "text_3p"}
    markdown, metadata, ocr_pages = odl.extract_pdf_with_engine(
        pdf(fake_jvm.tmp, "a.pdf"), engine="opendataloader", legacy_extract=lambda *a, **k: pytest.fail("legacy not expected"),
        config=fake_jvm.config,
    )
    assert metadata["source"] == "opendataloader_pdf" and metadata["page_count"] == 3
    assert markdown.startswith("# 示例市") and ocr_pages == []


def test_extract_pdf_itself_is_untouched_by_this_spike():
    import inspect

    from app.services import file_parse_service as parser

    source = inspect.getsource(parser._extract_pdf)
    assert "opendataloader" not in source.lower()
    assert '["pdftotext", "-layout", pdf_path, "-"]' in source
