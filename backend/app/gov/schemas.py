from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator
from app.services.gongwen.schema import DocNumber, Banji, TableSpec

DocType = Literal["notice", "request", "report", "letter", "minutes", "interpretation"]


class Fields(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recipient: str = Field(default="", max_length=1000)
    issuer: str = Field(default="", max_length=1000)
    undertaker: str = Field(default="", max_length=1000)


class Content(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=256)
    docType: DocType = "notice"
    body: str = Field(default="", max_length=200000)
    fields: Fields = Field(default_factory=Fields)
    urgency: Literal["", "急件", "特急"] = ""
    signDate: str = Field(default="", max_length=30)
    citationIds: list[str] = Field(default_factory=list, max_length=50)
    docNumber: DocNumber | None = None
    banji: Banji | None = None
    note: str = Field(default="", max_length=200)
    titleLines: list[str] | None = Field(default=None, max_length=4)
    tables: list[TableSpec] = Field(default_factory=list, max_length=20)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("标题不能为空")
        return value.strip()


class Revision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)


class Update(Revision):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    docType: DocType | None = None
    body: str | None = Field(default=None, max_length=200000)
    fields: Fields | None = None
    urgency: Literal["", "急件", "特急"] | None = None
    signDate: str | None = Field(default=None, max_length=30)
    docNumber: DocNumber | None = None
    banji: Banji | None = None
    note: str | None = Field(default=None, max_length=200)
    titleLines: list[str] | None = Field(default=None, max_length=4)
    tables: list[TableSpec] | None = Field(default=None, max_length=20)


class Decision(Revision):
    opinion: str = Field(default="", max_length=4000)


class Materials(Revision):
    fileIds: list[int] = Field(max_length=100)


class ExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["internal_draft", "formal"] = "internal_draft"


class Generation(Revision):
    prompt: str = Field(min_length=1, max_length=12000)


class CitationSelection(Revision):
    citationIds: list[str] = Field(max_length=50)
