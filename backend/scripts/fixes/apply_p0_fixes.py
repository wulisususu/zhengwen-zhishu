#!/usr/bin/env python3
"""
Apply all P0 fixes to PI Agent document generation pipeline.
Run on remote server: python3 apply_p0_fixes.py

Backups are created as .bak-20260714 before each file is modified.
"""

import os
import sys
import shutil
from datetime import datetime

BACKEND_DIR = "/home/youyeetoo/InNet_box/backend"
BACKUP_SUFFIX = ".bak-20260714"

def backup(filepath):
    """Create backup if not already done."""
    bak = filepath + BACKUP_SUFFIX
    if not os.path.exists(bak):
        shutil.copy2(filepath, bak)
        print(f"  [BACKUP] {filepath} -> {bak}")
    else:
        print(f"  [SKIP] backup already exists: {bak}")

# ============================================================
# P0-1: Remove duplicate preface emission in conversations.py
# ============================================================
def fix_p01_preface_duplicate():
    """Remove the duplicate user event + preface block from sse_doc_gen().

    conversations.py L888-898 currently emits user event + message_start +
    preface tokens + status:analyzing. doc_with_degradation() also emits
    the same sequence. Since PI_AGENT_DOC=1 permanently, doc_with_degradation()
    always runs and handles preface emission. Remove from sse_doc_gen().
    """
    filepath = os.path.join(BACKEND_DIR, "app", "routers", "conversations.py")
    backup(filepath)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # The block to remove (exact text from L889-898):
    old_block = '''                    yield "data: " + _json.dumps(_workflow_event(workflow_type, intent_type, _user_event_payload(msg, msg_attachments, conv)), ensure_ascii=False) + NL
                    _trace_doc_stream(conv_id, "user_emitted")
                    preface_text = _build_document_preface(content)
                    if preface_text:
                        yield "data: " + _json.dumps(_workflow_event(workflow_type, intent_type, {"type": "message_start", "role": "assistant"}), ensure_ascii=False) + NL
                        for token in emit_text_chunks(preface_text, chunk_size=6):
                            yield "data: " + _json.dumps(_workflow_event(workflow_type, intent_type, {"type": "token", "content": token}), ensure_ascii=False) + NL
                            time.sleep(0.02)
                        yield "data: " + _json.dumps(_workflow_event(workflow_type, intent_type, {"type": "status", "stage": "analyzing", "message": "正在分析你的文档需求…"}), ensure_ascii=False) + NL
                        _trace_doc_stream(conv_id, "preface_emitted", preface_text[:80])
                    for task in attachment_bundle.get("tasks", []):'''

    # Replacement: keep trace line, skip to attachment tasks
    new_block = '''                    for task in attachment_bundle.get("tasks", []):'''

    if old_block in content:
        content = content.replace(old_block, new_block)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print("  [P0-1 OK] Removed duplicate preface emission from sse_doc_gen()")
        return True
    else:
        print("  [P0-1 WARN] Target block not found — may already be fixed or code changed")
        # Try to find the block with different whitespace
        if 'preface_emitted' in content:
            print("  [P0-1 WARN] 'preface_emitted' found but exact match failed. Manual check needed.")
        else:
            print("  [P0-1 INFO] 'preface_emitted' not found — fix may already be applied")
        return False


# ============================================================
# P0-2: Add session deadlock timeout protection
# ============================================================
def fix_p02_session_timeout():
    """Add asyncio.wait_for timeout to _stream_pi_doc() call.

    Wraps the PI Agent SSE stream with per-frame timeouts:
    - First frame: 900s (matches models.json timeoutSeconds for 35B inference)
    - Subsequent frames: 120s (normal typing should be faster)

    On timeout, raises asyncio.TimeoutError which is caught by the existing
    except block in doc_with_degradation(), triggering docs_pipeline fallback.
    """
    filepath = os.path.join(BACKEND_DIR, "app", "services", "pi_agent_client", "degradation.py")
    backup(filepath)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Original block: the async for loop over _stream_pi_doc
    old_block = '''            # 5. PI Agent content generation
            agent_text = ""
            async for frame in _stream_pi_doc(
                content, user_id, conversation_id, message_id,
                workflow, intent, attachment_ids, attachment_context,
            ):
                yield frame
                try:
                    payload_str = frame[6:].strip()
                    obj = json.loads(payload_str)
                    if obj.get("type") == "token":
                        t = obj.get("content", "")
                        agent_text += t
                        full_content += t
                except Exception:
                    pass'''

    # New block: with timeout on first frame (900s) and subsequent frames (120s)
    new_block = '''            # 5. PI Agent content generation (with timeout guard against session deadlock)
            agent_text = ""
            _doc_stream = _stream_pi_doc(
                content, user_id, conversation_id, message_id,
                workflow, intent, attachment_ids, attachment_context,
            )
            _doc_iter = _doc_stream.__aiter__()
            _is_first_frame = True
            while True:
                try:
                    _timeout = 900 if _is_first_frame else 120
                    frame = await asyncio.wait_for(_doc_iter.__anext__(), timeout=_timeout)
                    _is_first_frame = False
                    yield frame
                    try:
                        payload_str = frame[6:].strip()
                        obj = json.loads(payload_str)
                        if obj.get("type") == "token":
                            t = obj.get("content", "")
                            agent_text += t
                            full_content += t
                    except Exception:
                        pass
                except StopAsyncIteration:
                    break'''

    if old_block in content:
        content = content.replace(old_block, new_block)
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(content)
        print("  [P0-2 OK] Added asyncio.wait_for timeout guard to _stream_pi_doc()")
        return True
    else:
        print("  [P0-2 WARN] Target block not found — may already be fixed or code changed")
        return False


# ============================================================
# P0-3: Add 35B reachability cache
# ============================================================
def fix_p03_35b_cache():
    """Add module-level 35B reachability cache to llm_client.py.

    The cache is shared between degradation.py's _is_35b_reachable() and
    _ollama_generate_with_fallback(). When 35B is known unreachable,
    _ollama_generate_with_fallback() skips the 4-retry loop and goes
    directly to local fallback model, saving up to 4×240s = 16 minutes.
    """
    filepath = os.path.join(BACKEND_DIR, "app", "services", "llm_client.py")
    backup(filepath)

    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # 1. Add cache functions after the imports section
    import_section_end = '''PROMPT_REWRITE_TEMPLATE'''

    cache_code = '''
# === 35B reachability cache (shared with degradation.py) ===
# Cache TTL: 30 seconds. Set by degradation.py _is_35b_reachable(),
# checked by _ollama_generate_with_fallback() before retry loop.
_35b_reachability_cache: dict = {}  # keyed by host:port string

def set_35b_reachable(host: str = "192.168.10.212", port: int = 8081, reachable: bool = True):
    """Called by degradation.py after TCP probe. Updates shared cache."""
    import time as _time
    key = f"{host}:{port}"
    _35b_reachability_cache[key] = {"reachable": reachable, "checked_at": _time.time()}

def is_35b_reachable_cached(host: str = "192.168.10.212", port: int = 8081, ttl: float = 30.0) -> bool | None:
    """Check cache. Returns None if no cache entry or expired (caller should probe)."""
    import time as _time
    key = f"{host}:{port}"
    entry = _35b_reachability_cache.get(key)
    if entry is None:
        return None
    if _time.time() - entry["checked_at"] > ttl:
        del _35b_reachability_cache[key]
        return None
    return entry["reachable"]
# ================================================================

PROMPT_REWRITE_TEMPLATE'''

    if import_section_end in content and '_35b_reachability_cache' not in content:
        content = content.replace(import_section_end, cache_code)
        print("  [P0-3 STEP1 OK] Added reachability cache functions to llm_client.py")
    elif '_35b_reachability_cache' in content:
        print("  [P0-3 STEP1 SKIP] Cache functions already exist")
    else:
        print("  [P0-3 STEP1 WARN] Could not find insertion point for cache code")

    # 2. Add cache check in _ollama_generate_with_fallback before retry loop
    old_retry_block = '''    if "error" in result:
        # Retry 35B 3-5 times before degrading
        retry_count = 0
        max_retries = 4
        retry_result = result
        while retry_count < max_retries and "error" in retry_result:
            retry_count += 1
            import time as _time
            _time.sleep(1.5)
            try:
                retry_result = _ollama_generate(prompt, max_tokens=max_tokens)
            except Exception:
                retry_result = {"error": "retry failed"}
        if "error" not in retry_result:
            return retry_result
        # All retries exhausted → degrade to 0.6B
        local = _local_small_generate(_extract_user_content(prompt), max_tokens=max_tokens)
        if "error" not in local:
            return local
    return result'''

    new_retry_block = '''    if "error" in result:
        # Check 35B reachability cache before retrying
        _cached = is_35b_reachable_cached()
        if _cached is False:
            # 35B confirmed unreachable by degradation.py — skip retries, go directly to fallback
            local = _local_small_generate(_extract_user_content(prompt), max_tokens=max_tokens)
            if "error" not in local:
                return local
            return result

        # Retry 35B 3-5 times before degrading
        retry_count = 0
        max_retries = 4
        retry_result = result
        while retry_count < max_retries and "error" in retry_result:
            retry_count += 1
            import time as _time
            _time.sleep(1.5)
            try:
                retry_result = _ollama_generate(prompt, max_tokens=max_tokens)
            except Exception:
                retry_result = {"error": "retry failed"}
        if "error" not in retry_result:
            # 35B recovered — update cache
            set_35b_reachable(reachable=True)
            return retry_result
        # All retries exhausted — update cache and degrade to 0.6B
        set_35b_reachable(reachable=False)
        local = _local_small_generate(_extract_user_content(prompt), max_tokens=max_tokens)
        if "error" not in local:
            return local
    return result'''

    if old_retry_block in content:
        content = content.replace(old_retry_block, new_retry_block)
        print("  [P0-3 STEP2 OK] Added cache check in _ollama_generate_with_fallback()")
    else:
        print("  [P0-3 STEP2 WARN] Could not find retry block in _ollama_generate_with_fallback()")

    # Write back
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

    return True


# ============================================================
# Main
# ============================================================
if __name__ == "__main__":
    print("=" * 60)
    print("PI Agent P0 Fixes — Applying...")
    print(f"Backend: {BACKEND_DIR}")
    print(f"Backup suffix: {BACKUP_SUFFIX}")
    print("=" * 60)

    results = []

    print("\n--- P0-1: Duplicate Preface ---")
    results.append(("P0-1", fix_p01_preface_duplicate()))

    print("\n--- P0-2: Session Timeout ---")
    results.append(("P0-2", fix_p02_session_timeout()))

    print("\n--- P0-3: 35B Reachability Cache ---")
    results.append(("P0-3", fix_p03_35b_cache()))

    print("\n" + "=" * 60)
    print("Summary:")
    for name, ok in results:
        status = "OK" if ok else "WARNING"
        print(f"  {name}: {status}")
    print("=" * 60)
    print("\nTo rollback: cp *{suffix} back to original filenames".format(suffix=BACKUP_SUFFIX))
