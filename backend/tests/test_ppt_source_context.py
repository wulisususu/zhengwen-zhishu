from __future__ import annotations


def test_incremental_request_accepts_only_ids_and_explicit_source_policy():
    from app.PPT_master.incremental_router import IncrementalPPTRequest

    request = IncrementalPPTRequest(
        user_input="Build a source-grounded presentation",
        page_count=5,
        page_format="ppt169",
        attachment_file_ids=[12, 13],
        knowledge_doc_ids=[101, 102],
        source_policy="parsed_only",
        request_id="ppt-source-contract-001",
    )

    assert request.attachment_file_ids == [12, 13]
    assert request.knowledge_doc_ids == [101, 102]
    assert request.source_policy == "parsed_only"


def test_source_context_preserves_selected_source_boundaries_and_manifest():
    from app.PPT_master.source_context import build_source_context

    result = build_source_context(
        user_id=9,
        attachment_file_ids=[11, 12],
        knowledge_doc_ids=[21],
        source_policy="parsed_only",
        query="围绕收入增长和客户案例制作汇报",
        source_rows=[
            {
                "kind": "file",
                "file_id": 11,
                "parsed_file_id": 41,
                "filename": "revenue.docx",
                "chunks": [{"chunk_id": 1, "content": "收入增长 18%，来自新客户。", "page_start": 1, "page_end": 1}],
            },
            {
                "kind": "file",
                "file_id": 12,
                "parsed_file_id": 42,
                "filename": "case-study.docx",
                "chunks": [{"chunk_id": 2, "content": "客户案例说明交付周期缩短。", "page_start": 2, "page_end": 2}],
            },
            {
                "kind": "knowledge",
                "doc_id": 21,
                "filename": "strategy.pdf",
                "chunks": [{"chunk_id": 3, "content": "战略重点是增长与客户成功。", "page_start": 3, "page_end": 3}],
            },
            {
                "kind": "knowledge",
                "doc_id": 99,
                "filename": "unselected-secret.pdf",
                "chunks": [{"chunk_id": 4, "content": "未选择的全库内容绝不能进入 PPT。", "page_start": 1, "page_end": 1}],
            },
        ],
        max_chars=24000,
    )

    assert "【来源：revenue.docx】" in result.source_context
    assert "【来源：case-study.docx】" in result.source_context
    assert "【来源：strategy.pdf】" in result.source_context
    assert "未选择的全库内容绝不能进入 PPT。" not in result.source_context
    assert [item["filename"] for item in result.source_manifest] == ["revenue.docx", "case-study.docx", "strategy.pdf"]
    assert result.source_manifest[0]["file_id"] == 11
    assert result.source_manifest[2]["doc_id"] == 21
    assert result.source_manifest[0]["content_sha256"]


def test_source_context_rejects_pending_and_failed_sources_without_explicit_skip():
    from app.PPT_master.source_context import SourceResolutionError, resolve_ppt_sources

    try:
        resolve_ppt_sources(
            user_id=9,
            attachment_file_ids=[11],
            knowledge_doc_ids=[],
            source_policy="parsed_only",
            source_rows=[{"kind": "file", "file_id": 11, "filename": "pending.docx", "parse_status": "extracting"}],
        )
    except SourceResolutionError as error:
        assert error.code == "sources_pending"
        assert error.pending_file_ids == [11]
    else:
        raise AssertionError("pending sources must block parsed_only generation")
