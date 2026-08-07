from __future__ import annotations


def test_outline_has_unique_content_briefs_for_exact_requested_count():
    from app.PPT_master.incremental_slides import extract_outline

    outline = extract_outline("### Page 1 - Opening\n", page_count=5, user_input="保护环境")

    assert len(outline) == 5
    assert [item["index"] for item in outline] == [1, 2, 3, 4, 5]
    assert len({item["title"] for item in outline}) == 5
    assert all(item["content_brief"] for item in outline)


def test_page_count_mismatch_is_blocking_and_reports_all_counts():
    from app.PPT_master.incremental_runner import page_count_mismatch_result

    result = page_count_mismatch_result(5, 5, 4, 4)

    assert result["passed"] is False
    assert result["blocking_errors"] == ["page_count_mismatch"]
    assert "requested=5" in result["errors"][0]
    assert "completed=4" in result["errors"][0]
