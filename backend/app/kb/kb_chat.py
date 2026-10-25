"""Knowledge-base-augmented chat: search -> filter -> prompt -> stream -> audit.

Hybrid retrieval: FAISS semantic search first, keyword fallback on low scores.
Small chunk hit -> expand to parent ParsedFileChunk for richer LLM context.
"""
import json as _json
import asyncio
import re
import logging

logger = logging.getLogger('app.kb.chat')

# Thresholds for hybrid search
_TOP1_SCORE_FLOOR = 0.35
_KEYWORD_FALLBACK_TOP_N = 6


# ---------------------------------------------------------------------------
# Query condensation
# ---------------------------------------------------------------------------

def _condense_query(content: str, history: list) -> str:
    """Lightweight pronoun-detection: only rewrite if history exists and
    the query contains demonstrative/anaphoric references."""
    if not history or len(history) < 2:
        return content
    pronoun_pattern = re.compile(r'(?:它|他|她|这个|那个|其|该|此人|上述|前述|那起|该案|该嫌)')
    if not pronoun_pattern.search(content):
        return content
    try:
        from app.services.llm_client import refine_prompt
        return refine_prompt(content)
    except Exception:
        return content


# ---------------------------------------------------------------------------
# Hybrid search
# ---------------------------------------------------------------------------

def _hybrid_search(kb, query: str, top_k: int = 6, user_id=None, is_admin: bool = False) -> tuple[list[dict], bool]:
    """Unified retrieval: semantic first, keyword fallback on low scores.

    Returns (results, grounded).
    Each result has:
        chunk_text, context_text (expanded parent), filename,
        source_ref, parsed_file_id, chunk_id, parent_parsed_chunk_id,
        page_no, score, retrieval_type
    """
    # 0. 归属范围：非管理员只能检索自己上传的文档
    allowed_doc_ids = None
    if not is_admin:
        from app.kb.db import list_document_ids

        allowed_doc_ids = list_document_ids(user_id) if user_id is not None else []

    # 1. FAISS semantic search
    try:
        raw_chunks, grounded = kb.search_with_filter(
            query, top_k=top_k, allowed_clearance=None, allowed_doc_ids=allowed_doc_ids,
        )
    except Exception as e:
        logger.error('FAISS search failed: %s', e)
        raw_chunks, grounded = [], False

    # 2. Score-based decision: use semantic results or fall back
    use_semantic = False
    if raw_chunks:
        top1_score = raw_chunks[0].get('score', 0)
        if top1_score >= _TOP1_SCORE_FLOOR:
            use_semantic = True
            logger.info('Hybrid: semantic hit (top1=%.4f), %d chunks', top1_score, len(raw_chunks))
        else:
            logger.info('Hybrid: semantic low score (top1=%.4f < %.2f), trying keyword fallback',
                        top1_score, _TOP1_SCORE_FLOOR)
    else:
        logger.info('Hybrid: no semantic results, trying keyword fallback')

    if use_semantic:
        results = _normalize_semantic_results(raw_chunks)
        return results, True

    # 3. Keyword fallback: search ParsedFileChunk
    keyword_results = _keyword_search_from_parsed_chunks(
        query, top_n=_KEYWORD_FALLBACK_TOP_N, user_id=user_id, is_admin=is_admin,
    )
    if keyword_results:
        logger.info('Hybrid: keyword fallback returned %d chunks', len(keyword_results))
        return keyword_results, True

    # 4. Both failed — return semantic results (even if low score) if any
    if raw_chunks:
        results = _normalize_semantic_results(raw_chunks)
        logger.info('Hybrid: returning %d low-score semantic results as last resort', len(results))
        return results, True

    return [], False


def _normalize_semantic_results(chunks: list[dict]) -> list[dict]:
    """Convert KB search results to unified format with parent expansion."""
    results = []
    for c in chunks:
        context_text = ''
        try:
            from app.kb.kb_ingest_service import expand_to_parent_chunk
            context_text = expand_to_parent_chunk(c)
        except Exception as e:
            logger.debug('Parent expansion failed for chunk %s: %s', c.get('chunk_id'), e)

        results.append({
            "chunk_text": c.get("chunk_text", ""),
            "context_text": context_text or c.get("chunk_text", ""),
            "filename": c.get("filename", ""),
            "source_ref": c.get("source_ref", ""),
            "parsed_file_id": c.get("parsed_file_id", 0),
            "chunk_id": c.get("chunk_id"),
            "parent_parsed_chunk_id": c.get("parent_parsed_chunk_id", 0),
            "page_no": c.get("page_no", 0),
            "score": round(c.get("score", 0), 4),
            "retrieval_type": "vector",
        })
    return results


def _keyword_search_from_parsed_chunks(query: str, top_n: int = 6, user_id=None, is_admin: bool = False) -> list[dict]:
    """Fallback: keyword match against ParsedFileChunk table."""
    try:
        from app.database import SessionLocal
        from app.models import ParsedFileChunk, ParsedFile
        import re as _re

        keywords = set(_re.findall(r'[A-Za-z0-9_\-/]{2,}|[一-鿿]{2,}', query or ''))
        if not keywords:
            return []

        db = SessionLocal()
        try:
            q = db.query(ParsedFileChunk)
            if not is_admin:
                # 关键词回退同样必须做归属过滤，否则会绕过语义检索的权限边界
                from app.models import File as _FileModel

                q = (
                    q.join(ParsedFile, ParsedFile.id == ParsedFileChunk.parsed_file_id)
                     .join(_FileModel, _FileModel.id == ParsedFile.file_id)
                     .filter(_FileModel.owner_user_id == user_id)
                )
            chunks = q.order_by(ParsedFileChunk.id.desc()).limit(500).all()
            scored = []
            for chunk in chunks:
                text = chunk.content or ''
                score = sum(1 for kw in keywords if kw in text)
                if score > 0:
                    scored.append((score, chunk))
            scored.sort(key=lambda x: -x[0])
            top = scored[:top_n]

            results = []
            for score, chunk in top:
                parsed = db.query(ParsedFile).filter(ParsedFile.id == chunk.parsed_file_id).first()
                filename = parsed.title if parsed else ''
                results.append({
                    "chunk_text": (chunk.content or "")[:500],
                    "context_text": chunk.content or "",
                    "filename": filename,
                    "source_ref": f"parsed:{chunk.parsed_file_id}",
                    "parsed_file_id": chunk.parsed_file_id,
                    "chunk_id": None,
                    "parent_parsed_chunk_id": chunk.id,
                    "page_no": chunk.page_start or 0,
                    "score": round(score / max(len(keywords), 1), 4),
                    "retrieval_type": "keyword",
                })
            return results
        finally:
            db.close()
    except Exception as e:
        logger.error('Keyword fallback search failed: %s', e)
        return []


# ---------------------------------------------------------------------------
# Source collection & grounding event
# ---------------------------------------------------------------------------

def _collect_sources(chunks: list[dict]) -> list[dict]:
    return [
        {
            'chunk_id': r.get('chunk_id'),
            'filename': r.get('filename', ''),
            'chunk_text': (r.get('chunk_text', '') or '')[:200],
            'score': r.get('score', 0),
            'retrieval_type': r.get('retrieval_type', ''),
            'page_no': r.get('page_no', 0),
        }
        for r in chunks
    ]


def _build_grounding_event(workflow_type, intent_type, grounded, source_count, sources):
    return _json.dumps({
        'type': 'grounding',
        'workflow': workflow_type,
        'intent_type': intent_type,
        'grounded': grounded,
        'source_count': source_count,
        'sources': sources,
    }, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Build context from hybrid results
# ---------------------------------------------------------------------------

def _build_context_from_results(results: list[dict], grounded: bool) -> str:
    """Build LLM context string from hybrid search results.
    Prefers context_text (expanded parent) over chunk_text (small chunk).
    """
    if not grounded or not results:
        return ''
    parts = []
    for i, r in enumerate(results[:5], 1):
        filename = r.get('filename', 'unknown')
        page = r.get('page_no', 0)
        page_hint = f' (第{page}页)' if page else ''
        text = r.get('context_text') or r.get('chunk_text', '')
        parts.append(f'[来源{i}: {filename}{page_hint}]\n{text}')
    return '\n\n'.join(parts)


# ---------------------------------------------------------------------------
# Streaming KB chat
# ---------------------------------------------------------------------------

def stream_kb_chat(content, history_messages, workflow_type, intent_type,
                   msg, msg_attachments, conv, user_id, is_admin: bool = False):
    """Generator for SSE events in knowledge workflow."""
    import json as json_mod
    from app.kb.kb_manager import KnowledgeBase
    from app.kb.kb_prompt import build_kb_prompt
    from app.kb.db import insert_audit_log
    from app.kb.config import TOP_K
    from app.services.llm_client import generate_stream

    NL = "\n\n"

    condensed = _condense_query(content, history_messages)

    kb = _get_or_create_kb()
    if kb is None:
        error_text = '知识库未就绪，请稍后重试。'
        yield 'data: ' + json_mod.dumps({
            'type': 'token', 'content': error_text,
            'workflow': workflow_type, 'intent_type': intent_type,
        }, ensure_ascii=False) + NL
        yield 'data: ' + json_mod.dumps({
            'type': 'done', 'content': error_text, 'grounded': False,
            'workflow': workflow_type, 'intent_type': intent_type,
        }, ensure_ascii=False) + NL
        return

    # Hybrid search
    try:
        results, grounded = _hybrid_search(kb, condensed, top_k=TOP_K, user_id=user_id, is_admin=is_admin)
    except Exception as e:
        logger.error('Hybrid search failed: %s', e)
        results, grounded = [], False

    sources = _collect_sources(results) if grounded else []

    # Emit grounding metadata early
    yield 'data: ' + _build_grounding_event(workflow_type, intent_type, grounded, len(sources), sources) + NL

    # Build prompt with hybrid context
    if grounded:
        context_text = _build_context_from_results(results, grounded)
        # Use context-aware prompt builder
        kb_prompt = _build_hybrid_prompt(condensed, context_text, results)
    else:
        from app.kb.kb_prompt import build_kb_prompt
        kb_prompt = build_kb_prompt(condensed, [], False)

    # Stream LLM response
    full_text = ''
    for event in generate_stream(kb_prompt, max_tokens=4096):
        for line in event.strip().split('\n'):
            if not line.startswith('data: '):
                continue
            payload = line[6:]
            if payload == '[DONE]':
                break
            try:
                llm_data = json_mod.loads(payload)
                if 'error' in llm_data:
                    token = '[LLM] ' + llm_data['error']
                    full_text += token
                    yield 'data: ' + json_mod.dumps({
                        'type': 'token', 'content': token,
                        'workflow': workflow_type, 'intent_type': intent_type,
                    }, ensure_ascii=False) + NL
                elif 'text' in llm_data:
                    token = llm_data['text']
                    full_text += token
                    yield 'data: ' + json_mod.dumps({
                        'type': 'token', 'content': token,
                        'workflow': workflow_type, 'intent_type': intent_type,
                    }, ensure_ascii=False) + NL
            except Exception:
                pass

    # Done event
    yield 'data: ' + json_mod.dumps({
        'type': 'done',
        'content': full_text,
        'grounded': grounded,
        'source_count': len(sources),
        'sources': sources,
        'workflow': workflow_type,
        'intent_type': intent_type,
    }, ensure_ascii=False) + NL

    # Audit log
    try:
        insert_audit_log(
            user_id=user_id,
            query=condensed,
            hit_chunk_ids=[s['chunk_id'] for s in sources if s.get('chunk_id')],
            hit_filenames=[s['filename'] for s in sources],
            answer_snippet=full_text[:500],
            grounded=grounded,
        )
    except Exception as e:
        logger.error('KB audit log failed: %s', e)


# ---------------------------------------------------------------------------
# Non-streaming KB chat
# ---------------------------------------------------------------------------

def kb_chat_reply(content, history_messages, user_id, is_admin: bool = False):
    """Non-stream version. Returns (reply_text, grounding_info dict)."""
    from app.kb.kb_manager import KnowledgeBase
    from app.kb.kb_prompt import build_kb_prompt
    from app.kb.db import insert_audit_log
    from app.kb.config import TOP_K
    from app.services.llm_client import generate

    condensed = _condense_query(content, history_messages)

    kb = _get_or_create_kb()
    if kb is None:
        return '知识库未就绪，请稍后重试。', {'grounded': False, 'sources': []}

    try:
        results, grounded = _hybrid_search(kb, condensed, top_k=TOP_K, user_id=user_id, is_admin=is_admin)
    except Exception as e:
        logger.error('Hybrid search failed: %s', e)
        results, grounded = [], False

    sources = _collect_sources(results) if grounded else []

    if grounded:
        context_text = _build_context_from_results(results, grounded)
        kb_prompt = _build_hybrid_prompt(condensed, context_text, results)
    else:
        kb_prompt = build_kb_prompt(condensed, [], False)

    result = generate(kb_prompt, max_tokens=4096)
    reply_text = result.get('text', '') if 'error' not in result else '[LLM] ' + result['error']

    try:
        insert_audit_log(
            user_id=user_id,
            query=condensed,
            hit_chunk_ids=[s['chunk_id'] for s in sources if s.get('chunk_id')],
            hit_filenames=[s['filename'] for s in sources],
            answer_snippet=reply_text[:500],
            grounded=grounded,
        )
    except Exception as e:
        logger.error('KB audit log failed: %s', e)

    return reply_text, {
        'grounded': grounded,
        'source_count': len(sources),
        'sources': sources,
    }


# ---------------------------------------------------------------------------
# Hybrid prompt builder
# ---------------------------------------------------------------------------

def _build_hybrid_prompt(query: str, context: str, results: list[dict]) -> str:
    """Build a prompt that uses expanded context from hybrid search."""
    source_lines = []
    for i, r in enumerate(results[:5], 1):
        fname = r.get('filename', '未知')
        page = r.get('page_no', 0)
        rtype = r.get('retrieval_type', '')
        page_hint = f', 第{page}页' if page else ''
        source_lines.append(f'来源{i}: {fname}{page_hint} (检索方式: {rtype})')

    sources_text = '\n'.join(source_lines)

    return f"""你是一个专业的文档问答助手。请根据以下参考资料回答用户问题。

## 参考资料

{context}

## 来源信息
{sources_text}

## 要求
1. 基于上述参考资料回答问题，不要编造信息
2. 如果参考资料中没有相关内容，请如实说明
3. 回答时引用来源文件名和页码
4. 使用中文回答

## 用户问题
{query}
"""


# ---------------------------------------------------------------------------
# KB singleton
# ---------------------------------------------------------------------------

_kb_instance = None


def _get_or_create_kb():
    global _kb_instance
    if _kb_instance is not None:
        return _kb_instance
    try:
        from app.kb.kb_manager import KnowledgeBase
        _kb_instance = KnowledgeBase()
        return _kb_instance
    except Exception as e:
        logger.error('KB init failed: %s', e)
        return None
