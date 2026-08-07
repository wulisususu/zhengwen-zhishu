from __future__ import annotations
import pytest

def test_tabular_import_builds_chart_and_table_with_source_reference(tmp_path):
    from app.PPT_master.native_data import build_chart_from_rows, build_table_from_rows
    rows = [["季度", "收入", "成本"], ["Q1", "120", "70"], ["Q2", "180", "90"]]
    table = build_table_from_rows(rows, source_ref={"file_id": 901, "sheet": "数据", "range": "A1:C3"})
    chart = build_chart_from_rows(rows, chart_type="column", source_ref={"file_id": 901, "sheet": "数据", "range": "A1:C3"})
    assert table["columns"] == ["季度", "收入", "成本"]
    assert table["source_refs"] == [{"file_id": 901, "sheet": "数据", "range": "A1:C3"}]
    assert chart["categories"] == ["Q1", "Q2"]
    assert chart["series"] == [{"name": "收入", "values": [120.0, 180.0]}, {"name": "成本", "values": [70.0, 90.0]}]


def test_tabular_import_rejects_formula_and_non_numeric_chart_rows():
    from app.PPT_master.native_data import build_chart_from_rows, build_table_from_rows
    with pytest.raises(ValueError, match="native_table_formula_unsafe"):
        build_table_from_rows([["A"], ["=CMD()"]], source_ref={"file_id": 1})
    with pytest.raises(ValueError, match="native_chart_values_invalid"):
        build_chart_from_rows([["A", "B"], ["Q1", "not-a-number"]], chart_type="line", source_ref={"file_id": 1})


def test_load_tabular_csv_and_tsv(tmp_path):
    from app.PPT_master.native_data import load_tabular_file
    csv_path = tmp_path / "data.csv"; csv_path.write_text("分类,数值\nA,3\n", encoding="utf-8")
    tsv_path = tmp_path / "data.tsv"; tsv_path.write_text("分类\t数值\nB\t4\n", encoding="utf-8")
    assert load_tabular_file(csv_path, "text/csv") == [["分类", "数值"], ["A", "3"]]
    assert load_tabular_file(tsv_path, "text/tab-separated-values") == [["分类", "数值"], ["B", "4"]]
