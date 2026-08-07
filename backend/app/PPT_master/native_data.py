from __future__ import annotations
import copy, html, json, math
from typing import Any
CHART_TYPES={"bar","column","line","pie"}; MAX_CATEGORIES=50; MAX_SERIES=12; MAX_TABLE_ROWS=100; MAX_TABLE_COLUMNS=20; MAX_TEXT=500

def _text(v:Any, code:str)->str:
    if not isinstance(v,str) or not (v:=v.strip()) or len(v)>MAX_TEXT: raise ValueError(code)
    return v

def _finite(v:Any,code:str)->float:
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(float(v)): raise ValueError(code)
    return float(v)

def _refs(v:Any)->list[dict[str,Any]]:
    if v is None:return []
    if not isinstance(v,list) or len(v)>20:raise ValueError("native_source_refs_invalid")
    out=[]
    for x in v:
        if not isinstance(x,dict) or not isinstance(x.get("file_id"),int) or x["file_id"]<=0:raise ValueError("native_source_refs_invalid")
        out.append({k:(x[k] if k=="file_id" else str(x[k])[:200]) for k in ("file_id","sheet","range","page") if x.get(k) not in (None,"")})
    return out

def validate_chart(c:Any)->dict[str,Any]:
    if not isinstance(c,dict):raise ValueError("native_chart_invalid")
    kind=str(c.get("chart_type") or c.get("type") or "").lower()
    if kind not in CHART_TYPES:raise ValueError("native_chart_type_invalid")
    raw=c.get("categories")
    if not isinstance(raw,list) or not 1<=len(raw)<=MAX_CATEGORIES:raise ValueError("native_chart_categories_invalid")
    cats=[_text(x,"native_chart_categories_invalid") for x in raw]; raw_series=c.get("series")
    if not isinstance(raw_series,list) or not 1<=len(raw_series)<=MAX_SERIES:raise ValueError("native_chart_series_invalid")
    series=[]
    for x in raw_series:
        if not isinstance(x,dict) or not isinstance(x.get("values"),list) or len(x["values"])!=len(cats):raise ValueError("native_chart_series_invalid")
        series.append({"name":_text(x.get("name"),"native_chart_series_invalid"),"values":[_finite(n,"native_chart_values_invalid") for n in x["values"]]})
    if kind=="pie" and len(series)!=1:raise ValueError("native_chart_pie_series_invalid")
    title=str(c.get("title") or "").strip()
    if len(title)>MAX_TEXT:raise ValueError("native_chart_title_invalid")
    style=c.get("style") if isinstance(c.get("style"),dict) else {}; colors=style.get("colors",[])
    if not isinstance(colors,list) or any(not isinstance(x,str) or not x.startswith("#") or len(x) not in {4,7} for x in colors):raise ValueError("native_chart_style_invalid")
    return {"chart_type":kind,"title":title,"categories":cats,"series":series,"style":{"colors":colors},"source_refs":_refs(c.get("source_refs"))}

def validate_table(c:Any)->dict[str,Any]:
    if not isinstance(c,dict):raise ValueError("native_table_invalid")
    cols,raw_rows=c.get("columns"),c.get("rows")
    if not isinstance(cols,list) or not 1<=len(cols)<=MAX_TABLE_COLUMNS or not isinstance(raw_rows,list) or len(raw_rows)>MAX_TABLE_ROWS:raise ValueError("native_table_dimensions_invalid")
    cols=[_text(x.get("text") if isinstance(x,dict) else x,"native_table_cells_invalid") for x in cols]; rows=[]
    for row in raw_rows:
        if not isinstance(row,list) or len(row)!=len(cols):raise ValueError("native_table_dimensions_invalid")
        clean=[]
        for x in row:
            value=_text(str(x),"native_table_cells_invalid")
            if value.startswith(("=","+","-","@")):raise ValueError("native_table_formula_unsafe")
            clean.append(value)
        rows.append(clean)
    style=c.get("style") if isinstance(c.get("style"),dict) else {}
    return {"columns":cols,"rows":rows,"style":{k:str(v)[:32] for k,v in style.items() if k in {"header_fill","header_color","cell_fill","cell_color","border_color"}},"source_refs":_refs(c.get("source_refs"))}

def validate_native_element(e:dict[str,Any])->dict[str,Any]:
    if e.get("type")=="chart":return validate_chart(e.get("content"))
    if e.get("type")=="table":return validate_table(e.get("content"))
    raise ValueError("native_element_invalid")

def has_native_elements(d:dict[str,Any])->bool:return any(e.get("type") in {"chart","table"} for s in d.get("slides",[]) for e in s.get("elements",[]))
def marker_svg(e:dict[str,Any])->str:
    c=validate_native_element(e); x,y,w,h=(float(e[k]) for k in ("x","y","width","height")); name=str(e.get("id") or "native_object")
    if e["type"]=="chart":
        p={"name":name,"x":x,"y":y,"width":w,"height":h,"type":c["chart_type"],"title":c["title"],"categories":c["categories"],"series":c["series"],"style":c["style"]}; r="chart"; fallback=f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#F8FAFC" stroke="#94A3B8"/><text x="{x+16}" y="{y+30}" font-size="18" fill="#0F172A">{html.escape(c["title"] or "Chart")}</text><line x1="{x+36}" y1="{y+h-32}" x2="{x+w-24}" y2="{y+h-32}" stroke="#64748B"/>'
    else:
        p={"name":name,"x":x,"y":y,"width":w,"height":h,"columns":[{"text":v,"bold":True} for v in c["columns"]],"rows":[[{"text":v} for v in row] for row in c["rows"]],"style":c["style"]}; r="table"; step = max(80, w / max(1, len(c["columns"])))
        labels = "".join('<text x="{}" y="{}" font-size="14" font-weight="700" fill="#FFFFFF">{}</text>'.format(x + 12 + i * step, y + 24, html.escape(v)) for i, v in enumerate(c["columns"])); fallback=f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="#FFFFFF" stroke="#94A3B8"/><rect x="{x}" y="{y}" width="{w}" height="30" fill="#2563EB"/>{labels}'
    return f'<g id="{html.escape(name,quote=True)}" data-pptx-replace-with="{r}"><metadata type="application/json">{html.escape(json.dumps(p,ensure_ascii=False,separators=(",",":")))}</metadata>{fallback}</g>'
def sidecar(d:dict[str,Any])->dict[str,Any]:return {"objects":[{"slide_id":s.get("slide_id"),"id":e.get("id"),"type":e.get("type"),"content":copy.deepcopy(e.get("content"))} for s in d.get("slides",[]) for e in s.get("elements",[]) if e.get("type") in {"chart","table"}]}


def _normal_rows(rows: Any) -> list[list[str]]:
    if not isinstance(rows, list) or len(rows) < 2:
        raise ValueError("native_tabular_rows_invalid")
    normalized: list[list[str]] = []
    width: int | None = None
    for row in rows:
        if not isinstance(row, (list, tuple)):
            raise ValueError("native_tabular_rows_invalid")
        values = [str(value).strip() for value in row]
        if width is None:
            width = len(values)
        if not width or width > MAX_TABLE_COLUMNS or len(values) != width:
            raise ValueError("native_tabular_rows_invalid")
        if any(not value or len(value) > MAX_TEXT for value in values):
            raise ValueError("native_tabular_rows_invalid")
        normalized.append(values)
    if len(normalized) - 1 > MAX_TABLE_ROWS:
        raise ValueError("native_table_dimensions_invalid")
    return normalized


def build_table_from_rows(rows: Any, *, source_ref: dict[str, Any]) -> dict[str, Any]:
    normalized = _normal_rows(rows)
    return validate_table({"columns": normalized[0], "rows": normalized[1:], "source_refs": [source_ref]})


def build_chart_from_rows(rows: Any, *, chart_type: str, source_ref: dict[str, Any], title: str = "") -> dict[str, Any]:
    normalized = _normal_rows(rows)
    if len(normalized[0]) < 2:
        raise ValueError("native_chart_series_invalid")
    categories = [row[0] for row in normalized[1:]]
    series = []
    for column in range(1, len(normalized[0])):
        values = []
        for row in normalized[1:]:
            try:
                numeric = float(row[column])
            except (TypeError, ValueError) as exc:
                raise ValueError("native_chart_values_invalid") from exc
            values.append(_finite(numeric, "native_chart_values_invalid"))
        series.append({"name": normalized[0][column], "values": values})
    return validate_chart({"chart_type": chart_type, "title": title, "categories": categories, "series": series, "source_refs": [source_ref]})


def load_tabular_file(path: Any, mime_type: str) -> list[list[str]]:
    """Read a bounded local CSV/TSV/XLSX into plain cells; never preserve formulas or links."""
    from pathlib import Path
    import csv
    source = Path(path)
    if not source.is_file() or source.stat().st_size > 2 * 1024 * 1024:
        raise ValueError("native_tabular_file_invalid")
    mime = str(mime_type or "").lower()
    if mime in {"text/csv", "application/csv"} or source.suffix.lower() == ".csv":
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            return _normal_rows(list(csv.reader(stream)))
    if mime in {"text/tab-separated-values", "text/tsv"} or source.suffix.lower() == ".tsv":
        with source.open("r", encoding="utf-8-sig", newline="") as stream:
            return _normal_rows(list(csv.reader(stream, delimiter="\t")))
    if mime == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet" or source.suffix.lower() == ".xlsx":
        try:
            from openpyxl import load_workbook
            workbook = load_workbook(source, read_only=True, data_only=False, keep_links=False)
            sheet = workbook.active
            rows = [["" if value is None else str(value) for value in row] for row in sheet.iter_rows(values_only=True)]
            workbook.close()
            return _normal_rows(rows)
        except ValueError:
            raise
        except Exception as exc:
            raise ValueError("native_tabular_file_invalid") from exc
    raise ValueError("native_tabular_file_type_invalid")
