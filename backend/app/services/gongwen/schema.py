"""Structured 通知 draft accepted by the backend.

Shape follows the frontend OfficialDocument (web/src/features/gov-office/types.ts)
so the HTTP adapter can send a document as-is: blocks with segment ids, fields
recipient / issuer / undertaker, docNumber {id, text}, signDate, policyRefs.
Two additions the frontend does not model yet: `banji` (版记) and `table` blocks.
Extra keys (origin, status, issues, history, ...) are ignored.

All text is data. Nothing here is ever evaluated as code; the Node bridge only
receives a fixed component spec built by converter.py.
"""
from __future__ import annotations

import re
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

FieldKey = Literal["recipient", "issuer", "undertaker"]
ID_PATTERN = r"^[A-Za-z0-9_.:-]{1,64}$"
_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")
MAX_TOTAL_CHARS = 100_000


def _clean(value: str) -> str:
    if _CONTROL.search(value):
        raise ValueError("文本含控制字符")
    return value


class _Model(BaseModel):
    model_config = ConfigDict(extra="ignore", str_strip_whitespace=False)


class TextSegment(_Model):
    kind: Literal["text"]
    id: str | None = Field(default=None, pattern=ID_PATTERN)
    text: str = Field(max_length=5000)

    @field_validator("text")
    @classmethod
    def check_text(cls, v: str) -> str:
        return _clean(v)


class FieldSegment(_Model):
    kind: Literal["field"]
    id: str = Field(pattern=ID_PATTERN)
    field: FieldKey


Segment = Annotated[Union[TextSegment, FieldSegment], Field(discriminator="kind")]


class TableSpec(_Model):
    caption: str = Field(default="", max_length=60)
    head: list[Annotated[str, Field(max_length=40)]] = Field(min_length=1, max_length=8)
    rows: list[list[Annotated[str, Field(max_length=200)]]] = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def _shape(self):
        for cell in [self.caption, *self.head, *(c for r in self.rows for c in r)]:
            _clean(cell)
        width = len(self.head)
        if any(len(row) != width for row in self.rows):
            raise ValueError("表格每行的列数必须与表头一致")
        return self


BlockKind = Literal["recipient", "paragraph", "heading1", "heading2", "heading3", "heading4",
                    "attachment", "signature", "table"]


class Block(_Model):
    id: str = Field(pattern=ID_PATTERN)
    kind: BlockKind
    section: str = Field(default="", max_length=64)
    segments: list[Segment] = Field(default_factory=list, max_length=200)
    table: TableSpec | None = None

    @model_validator(mode="after")
    def _table_only_for_table(self):
        if (self.kind == "table") != (self.table is not None):
            raise ValueError("只有 kind=table 的块带 table，且必须带")
        return self


class DocNumber(_Model):
    id: str = Field(default="seg-docno", pattern=ID_PATTERN)
    text: str = Field(default="", max_length=60)

    @field_validator("text")
    @classmethod
    def check_text(cls, v: str) -> str:
        return _clean(v)


class Fields(_Model):
    recipient: str = Field(default="", max_length=300)
    issuer: str = Field(default="", max_length=100)
    undertaker: str = Field(default="", max_length=100)

    @field_validator("recipient", "issuer", "undertaker")
    @classmethod
    def check_text(cls, v: str) -> str:
        return _clean(v)


class PolicyRefIn(_Model):
    id: str = Field(pattern=ID_PATTERN)
    title: str = Field(max_length=200)
    clause: str = Field(default="", max_length=100)
    # Client-provided status is never treated as verified; see rules.check_policy_refs.
    status: str = Field(default="unverified", max_length=20)


class Banji(_Model):
    copyTo: list[Annotated[str, Field(max_length=60)]] = Field(default_factory=list, max_length=20)
    printer: str = Field(default="", max_length=60)
    printDate: str = Field(default="", max_length=30)

    @model_validator(mode="after")
    def _text(self):
        for value in [*self.copyTo, self.printer, self.printDate]:
            _clean(value)
        return self


class NoticeDraft(_Model):
    docType: Literal["notice"]
    title: str = Field(default="", max_length=120)
    titleLines: list[Annotated[str, Field(max_length=60)]] | None = Field(default=None, max_length=4)
    docNumber: DocNumber | None = None
    fields: Fields = Field(default_factory=Fields)
    blocks: list[Block] = Field(default_factory=list, max_length=500)
    signDate: str = Field(default="", max_length=30)
    note: str = Field(default="", max_length=200)   # 附注，如「（此件公开发布）」
    policyRefs: list[PolicyRefIn] = Field(default_factory=list, max_length=100)
    banji: Banji | None = None

    @field_validator("title", "signDate", "note")
    @classmethod
    def check_text(cls, v: str) -> str:
        return _clean(v)

    @model_validator(mode="after")
    def _consistency(self):
        ids: set[str] = set()
        total = len(self.title)
        for block in self.blocks:
            for ident in [block.id, *(s.id for s in block.segments if s.id)]:
                if ident in ids:
                    raise ValueError(f"id 重复：{ident}")
                ids.add(ident)
            total += sum(len(s.text) for s in block.segments if isinstance(s, TextSegment))
            if block.table:
                total += sum(len(c) for r in block.table.rows for c in r)
        if total > MAX_TOTAL_CHARS:
            raise ValueError(f"正文超过 {MAX_TOTAL_CHARS} 字")
        if self.titleLines and "".join(self.titleLines).replace(" ", "") != self.title.replace(" ", ""):
            raise ValueError("titleLines 拼起来必须等于 title")
        return self

    def block_text(self, block: Block) -> str:
        """Visible text of a block with field segments resolved (empty fields stay empty)."""
        return "".join(
            s.text if isinstance(s, TextSegment) else getattr(self.fields, s.field)
            for s in block.segments
        )


class ExportRequest(_Model):
    draft: NoticeDraft
    kind: Literal["internal_draft", "formal"]
