"""Combined fix for conversations.py: P0-1 + task persistence.

Fix 1 (P0-1): Remove duplicate preface emission from sse_doc_gen().
  doc_with_degradation() already emits user event + message_start + preface.
  sse_doc_gen() should NOT also emit them before delegating to doc_with_degradation().

Fix 2 (task persistence): Save doc_tasks in message metadata.
  Extract doc_task from SSE frames during doc_with_degradation() loop,
  then pass to _save_assistant_reply() metadata so frontend can recover on refresh.
"""
import sys

filepath = "/home/youyeetoo/InNet_box/backend/app/routers/conversations.py"

with open(filepath, 'r') as f:
    content = f.read()

# ============================================================
# Fix 1: Remove duplicate preface (P0-1)
# ============================================================
old_preface_block = '''                    yield "data: " + _json.dumps(_workflow_event(workflow_type, intent_type, _user_event_payload(msg, msg_attachments, conv)), ensure_ascii=False) + NL
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

new_preface_block = '''                    for task in attachment_bundle.get("tasks", []):'''

if old_preface_block in content:
    content = content.replace(old_preface_block, new_preface_block)
    print("Fix 1 OK: Removed duplicate preface emission")
else:
    print("Fix 1 SKIP: Already applied or code changed")

# ============================================================
# Fix 2: Task persistence — capture doc_task from stream,
#         pass to _save_assistant_reply metadata
# ============================================================

# Step 2a: Initialize captured_doc_task before the async for loop
old_init = '''                        _trace_doc_stream(conv_id, "pi_agent_doc_stream")
                        doc_full_text = ""
                        async for sse_frame in doc_with_degradation('''

new_init = '''                        _trace_doc_stream(conv_id, "pi_agent_doc_stream")
                        doc_full_text = ""
                        captured_doc_task = None
                        async for sse_frame in doc_with_degradation('''

if old_init in content:
    content = content.replace(old_init, new_init)
    print("Fix 2a OK: Added captured_doc_task initialization")
else:
    print("Fix 2a SKIP: Already applied or code changed")

# Step 2b: Extract doc_task from SSE frames
old_token = '''                                    if obj.get("type") == "token":
                                        doc_full_text += obj.get("content", "")'''

new_token = '''                                    if obj.get("type") == "doc_task":
                                        captured_doc_task = obj.get("task")
                                    elif obj.get("type") == "token":
                                        doc_full_text += obj.get("content", "")'''

# Only replace the first occurrence (inside sse_doc_gen, not the non-stream path)
if old_token in content:
    content = content.replace(old_token, new_token, 1)
    print("Fix 2b OK: Added doc_task extraction")
else:
    print("Fix 2b SKIP: Already applied or code changed")

# Step 2c: Add metadata to _save_assistant_reply (only the PI Agent path one)
old_save = '''                        # Save assistant reply to DB
                        reply = _save_assistant_reply(db, conv, doc_full_text, intent_type=intent_type)'''

new_save = '''                        # Save assistant reply to DB (with doc_tasks for frontend persistence)
                        reply = _save_assistant_reply(db, conv, doc_full_text, intent_type=intent_type,
                            metadata={"doc_tasks": [captured_doc_task] if captured_doc_task else []})'''

if old_save in content:
    content = content.replace(old_save, new_save)
    print("Fix 2c OK: Added metadata to _save_assistant_reply")
else:
    print("Fix 2c SKIP: Already applied or code changed")

# Write back
with open(filepath, 'w') as f:
    f.write(content)

# Verify syntax
import py_compile
try:
    py_compile.compile(filepath, doraise=True)
    print("SYNTAX: OK")
except py_compile.PyCompileError as e:
    print(f"SYNTAX ERROR: {e}")
    sys.exit(1)
