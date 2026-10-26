"""Draft generation through the shared cloud model client, without canned conversational fallbacks."""
import json
from pathlib import Path
from fastapi import HTTPException
from app.models import File
from .models import GovDocumentMaterial
from . import service

SYSTEM_PROMPT = "你负责起草内部公文初稿。仅根据用户提供的事实和材料写正文，未知内容标注【待补充】，不编造政策依据、日期或数字。"


def generate_text(prompt: str) -> dict:
    """Same cloud API, configuration and egress check as /gongwen and /policy (app.services.llm_chat)."""
    import requests
    from app.services import llm_chat
    from app.services.llm_client import _clean_model_text
    try:
        text = llm_chat.chat([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": prompt}],
                             max_tokens=4096, temperature=0.2, timeout=90)
    except requests.HTTPError:
        return {"error": "model unavailable"}
    return {"text": _clean_model_text(text)}


def generate(db, user, document_id, body):
    doc = service.get_document(db, user, document_id)
    service.editable(doc, user)
    if doc.version != body.version:
        raise HTTPException(409, "文稿已更新，请刷新后重试")
    if not body.prompt.strip():
        raise HTTPException(422, "请填写生成要求")
    payload = json.loads(doc.payload_json)
    files = db.query(File).join(GovDocumentMaterial, GovDocumentMaterial.file_id == File.id).filter(GovDocumentMaterial.document_id == doc.id).all()
    sources = []
    for file in files:
        if file.filetype.lower() not in {".txt", ".md"}:
            raise HTTPException(422, "存在尚未解析的材料；请先完成解析或移除关联后再生成。本期直接读取TXT/Markdown材料。")
        try:
            with Path(file.filepath).open("rb") as source:
                data = source.read(80001)
            if len(data) > 80000:
                raise HTTPException(422, "材料过长（单份上限80000字节），请拆分后重试；未截断材料或修改文稿")
            text = data.decode("utf-8-sig")
        except (OSError, UnicodeError):
            raise HTTPException(422, "材料无法按UTF-8读取，请转换编码后重试")
        sources.append(f"材料《{file.filename}》：\n{text}")
    prompt = f"标题：{payload['title']}\n文种：{payload['docType']}\n要素：{json.dumps(payload['fields'],ensure_ascii=False)}\n现有正文：{payload.get('body','')}\n要求：{body.prompt}\n" + "\n\n".join(sources)
    try:
        result = generate_text(prompt)
        text = result.get("text", "").strip() if not result.get("error") else ""
    except Exception:
        text = ""
    if not text:
        raise HTTPException(503, "模型服务不可用或返回空内容，原文稿未修改。请检查模型连接与出口策略。")
    if len(text) > 200000:
        raise HTTPException(503, "模型输出过长，原文稿未修改")
    payload["body"] = text
    payload.pop("_review", None)
    from .proofread import validate_notice
    validate_notice(doc.id, payload)
    service.write_revision(db, doc, body.version, payload=payload)
    service.record(db, doc, user, "生成初稿", f"实际模型接口返回；使用{len(sources)}份文本材料，内容待人工核实")
    db.commit()
    return service.serialize(db, doc)
