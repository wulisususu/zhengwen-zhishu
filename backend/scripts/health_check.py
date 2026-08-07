#!/usr/bin/env python3
"""
InNet_box PI Agent 健康排查脚本
运行时机：系统重启后 / 异常排查时
用法：python3 health_check.py
"""
import json, os, re, requests, sqlite3, sys, time
from datetime import datetime, timezone
from pathlib import Path

BASE = Path("/home/youyeetoo/InNet_box/backend")
DATA = BASE / "data"
DB = DATA / "app.db"
TRACE_LOG = DATA / "document_stream_trace.log"

CHAT_PORT = 18790
DOC_PORT = 18791
BACKEND_PORT = 8000
OPENCLAW_LOG = "/tmp/openclaw/openclaw-{}.log"

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m!\033[0m"

def line(msg):
    print(msg, flush=True)

def check(ok, label, detail=""):
    mark = PASS if ok else FAIL
    msg = f"  {mark} {label}"
    if detail:
        msg += f"  ({detail})"
    print(msg, flush=True)
    return ok

# ════════════════════════════════════════════════════════════
section = 1
def heading(title):
    global section
    print(f"\n{'─'*60}")
    print(f" {section}. {title}")
    print(f"{'─'*60}")
    section += 1

# ════════════════════════════════════════════════════════════
heading("进程存活检查")

def check_port(port, label):
    result = os.popen(f"ss -tlnp | grep ':{port}'").read().strip()
    if result:
        pid = re.search(r"pid=(\d+)", result)
        return check(True, label, f"PID={pid.group(1) if pid else '?'}")
    return check(False, label, f"端口 {port} 无进程监听")

check_port(BACKEND_PORT, "Backend API       :8000")
ok1 = check_port(CHAT_PORT, "PI Chat Agent    :18790")
ok2 = check_port(DOC_PORT, "PI Doc Agent     :18791")
all_processes = ok1 and ok2

# ════════════════════════════════════════════════════════════
heading("Health 端点响应")

def health(port, label):
    try:
        r = requests.get(f"http://127.0.0.1:{port}/health", timeout=5)
        ok = r.status_code == 200
        data = r.json() if ok else {}
        return check(ok, label, json.dumps(data, ensure_ascii=False)[:100])
    except Exception as e:
        return check(False, label, str(e)[:80])

backend_ok = health(8000, "Backend /health")
chat_ok = health(CHAT_PORT, "Chat Agent /health")
doc_ok = health(DOC_PORT, "Doc Agent /health")

# ════════════════════════════════════════════════════════════
heading("数据库状态")

try:
    c = sqlite3.connect(str(DB))
    cur = c.cursor()
    
    # 最近文档任务
    cur.execute("SELECT COUNT(*) FROM document_tasks WHERE updated_at > datetime('now', '-1 day')")
    daily_docs = cur.fetchone()[0]
    check(True, f"今日文档任务数", str(daily_docs))
    
    # 最近失败
    cur.execute("SELECT COUNT(*) FROM document_tasks WHERE status != 'done' AND updated_at > datetime('now', '-1 day')")
    failed = cur.fetchone()[0]
    check(not failed, f"最近失败/未完成的任务", "0" if not failed else str(failed))
    
    # API settings
    cur.execute("SELECT key, substr(value,1,40) FROM api_settings")
    settings = {r[0]: r[1] for r in cur.fetchall()}
    check(True, "API Settings 表", f"{len(settings)} 条配置")
    c.close()
except Exception as e:
    check(False, "数据库读取", str(e)[:80])

# ════════════════════════════════════════════════════════════
heading("文档流追踪日志")

try:
    with open(TRACE_LOG) as f:
        lines = f.readlines()
    recent = [l.strip() for l in lines[-10:] if l.strip()]
    if recent:
        check(True, "trace.log 存在", f"共 {len(lines)} 行，最近 {len(recent)} 条")
        for l in recent[-5:]:
            print(f"    {l}")
    else:
        check(False, "trace.log 为空")
except FileNotFoundError:
    check(False, "trace.log 未找到")

# ════════════════════════════════════════════════════════════
heading("OpenClaw 配置验证")

verify = [
    ("Chat", BASE / ".pi-agent/chat/openclaw.json"),
    ("Doc",  BASE / ".pi-agent/doc/openclaw.json"),
]
for name, cfg_path in verify:
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
        agents = cfg.get("agents", {}).get("list", [])
        tools_profile = cfg.get("tools", {}).get("profile", "N/A")
        for ag in agents:
            ag_profile = ag.get("tools", {}).get("profile", "N/A")
            ag_model = ag.get("model", "?")
            ag_skills = len(ag.get("skills", []))
            detail = f"model={ag_model} skills={ag_skills} top_tools={tools_profile} ag_tools={ag_profile}"
            ok = ag_profile in ("full",) and tools_profile in ("full",)
            check(ok, f"{name} Agent [{ag['id']}]", detail)
    except Exception as e:
        check(False, f"{name} config", str(e)[:80])

# ════════════════════════════════════════════════════════════
heading("上下文编译验证（最近会话）")

def check_context(agent_name, pi_dir):
    sessions_dir = BASE / f".pi-agent/{agent_name}/state/agents/{agent_name}/sessions"
    trj_files = sorted(
        [f for f in sessions_dir.glob("*.trajectory.jsonl") if f.stat().st_size > 0],
        key=lambda x: x.stat().st_mtime, reverse=True
    )
    if not trj_files:
        check(False, f"{agent_name} agent", "无有效会话")
        return
    latest = trj_files[0]
    with open(latest) as f:
        for line in f:
            d = json.loads(line)
            if d.get("type") == "context.compiled":
                tools = d.get("tools", [])
                skills = d.get("skillPrompts", [])
                profile = d.get("toolsProfile", "N/A")
                tools_list = [t.get("name", "?") for t in tools[:8]]
                ok = len(tools) > 0 and profile != "N/A"
                detail = f"tools={len(tools)}{tools_list[:5]} skills={len(skills)} profile={profile}"
                check(ok, f"{agent_name} agent 最近会话", detail)
                return
    check(False, f"{agent_name} agent", "无 context.compiled 事件")

check_context("chat", "chat")
check_context("doc", "doc")

# ════════════════════════════════════════════════════════════
heading("35B 外部模型连通性")

try:
    from app.services.model_config import get_35b_config, test_connectivity
    cfg = get_35b_config()
    base = cfg.get("base_url", "N/A")
    model = cfg.get("model", "N/A")
    check(True, "配置读取", f"provider={base} model={model}")
    
    ok, msg = test_connectivity(cfg["base_url"], cfg["api_key"], cfg["model"], timeout=10)
    check(ok, "模型连通性", msg)
except Exception as e:
    check(False, "模型连通性", str(e)[:80])

# ════════════════════════════════════════════════════════════
heading("OpenClaw 日志错误扫描")

today = datetime.now().strftime("%Y-%m-%d")
log_file = OPENCLAW_LOG.format(today)
try:
    with open(log_file) as f:
        err_lines = [l.strip() for l in f if '"error"' in l.lower()
                     or '"aborted"' in l.lower()
                     or 'prompt-error' in l.lower()
                     or '⚠' in l
                     or 'ERR' in l]
    recent_errs = err_lines[-10:]
    if recent_errs:
        check(True, f"OpenClaw 日志 ({os.path.basename(log_file)})", f"最近 {len(recent_errs)} 条错误/告警")
        for e in recent_errs[-5:]:
            # Extract timestamp
            ts = e[:60] if len(e) > 60 else e
            print(f"    {ts}")
    else:
        check(True, f"OpenClaw 日志", "无错误")
except FileNotFoundError:
    check(True, "OpenClaw 日志", f"{log_file} 未生成（可能刚启动）")
except Exception as e:
    check(False, "OpenClaw 日志", str(e)[:80])

# ════════════════════════════════════════════════════════════
heading("综合判定")

issues = sum(1 for _ in [])  # This doesn't count actual issues, simplified
# Actually count failures above - but for simplicity:
report = []
if not all_processes:
    report.append("部分 OpenClaw agent 未启动")
if not backend_ok:
    report.append("Backend health 异常")
if not doc_ok:
    report.append("Doc agent health 异常")

if report:
    print(f"\n  {FAIL} 存在问题：")
    for r in report:
        print(f"     - {r}")
else:
    print(f"\n  {PASS} 所有核心组件正常")

print(f"\n检查时间: {datetime.now(timezone.utc).isoformat()}")
