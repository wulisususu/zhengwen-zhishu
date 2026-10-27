# 政策问答放开（会对话、围绕政策库作答）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 政策问答能正常打招呼、按政策名介绍政策、依据政策库回答（未核验的加后端固定前提）、友好转开无关问题，并接得上前几轮对话。

**Architecture:** 每次提问仍然先检索政策库，结果分三条路：有依据（已核验 / 仅待核实 / 已废止或未生效）→ 走现有的引用作答流程；政策名唯一匹配 → 政策概要；都没有 → 新的「对话」路线，由一个受约束的系统提示词生成回复，后端质检后返回 `status: "chat"`。仍然每问只调一次模型；对话路线的模型不可用时用轮换的固定话术兜底。

**Tech Stack:** FastAPI、SQLAlchemy、pytest（后端）；Vue 3 + Vitest（前端 `web/src/views/PolicyPage.vue`）。

**Spec:** `docs/superpowers/specs/2026-10-27-policy-qa-conversational-design.md`

## Global Constraints

- 待核实前提的固定文案（逐字）：`以下内容来自已入库但尚未经人工核验的政策，仅供参考；正式引用前，请审核人在政策库完成核验。`，由后端写入 `basis_notice`，不交给模型生成。
- 已废止、尚未生效的条款不作为依据（`include_deprecated` 显式允许已废止时除外，即现有行为）。
- 对话路线的回复里不得出现：`[n]` 引用标记、政策库中不存在的《书名》、文号（`〔2024〕` 这类）、代码块。出现即改用兜底话术。
- 无关问题不给具体步骤、命令或答案。
- 政策状态只来自人工核验；不新增任何写政策状态的路径。
- 多轮上下文：最多 3 轮，每轮问题截到 200 字、回答截到 300 字。
- 不引入新依赖；不使用 Google Fonts 或商用字体；不出现「离线」「数据不出本机」之类的说法。
- 现有的已核验作答行为（引用、数值直引原文、`_apply_guards` 质检）保持不变。
- 后端测试用能运行 `backend/requirements.txt` 的 Python 环境，命令统一写作 `python -m pytest`；`test_gov_basic_api` / `test_gov_demo_stability` 里因缺 docxtpl、uvicorn、gongwen-kit 失败的 6 个用例是环境基线，与本任务无关。

## Review Focus

1. **追问引用了错误的政策**：上一轮聊的是 A 办法，这一轮「那申请材料呢」被拼接检索后命中 B 办法。期望：只在当前问题单独检索没有依据时才拼接；结果照常带引用，用户能从卡片看出是哪份。测试见 Task 4 `test_followup_only_combines_when_current_question_has_no_basis`。
2. **模型在对话路线里编政策**：对「有没有人才公寓补贴政策」，模型回「根据《某市人才安居办法》……」。期望：质检发现库里没有这个书名，改用兜底话术。测试见 Task 2 `test_chat_reply_naming_unknown_policy_falls_back`。
3. **无关问题被顺手回答**：模型一边说「建议咨询信息部门」，一边给出命令代码块。期望：含代码块即改用兜底。测试见 Task 2 `test_chat_reply_with_code_block_falls_back`。
4. **政策名部分匹配到多份**：库里有「小微企业贴息管理办法」和「小微企业贴息管理办法实施细则」，用户说「看看小微企业贴息办法」。期望：不擅自挑一份，反问并列出两份。测试见 Task 3 `test_ambiguous_title_asks_back_with_suggestions`。
5. **流式中途切换路线**：前端先收到对话路线的增量，后来又收到 `replace`（质检换成兜底）。期望：页面最终只显示兜底话术，不残留模型原文。测试见 Task 5 `renders chat replies and applies the final replacement`。

---

## File Structure

| 文件 | 动作 | 职责 |
|---|---|---|
| `backend/app/policy/qa.py` | 改 | 路线判定（`_prepare`）、依据分层、作答组装；同步和流式两个入口 |
| `backend/app/policy/conversation.py` | 新建 | 对话路线：系统提示词、上下文、回复质检、兜底话术、`chat` 载荷 |
| `backend/app/policy/titles.py` | 新建 | 政策名匹配 |
| `backend/app/policy/router.py` | 改 | 解析 `history`；`scope` 默认值改为 `all` |
| `backend/app/policy/models.py` | 改 | `PolicyQaLog.status` 注释补 `chat` |
| `backend/tests/test_policy_qa_t1.py` | 改 | 更新随新规则变化的旧用例 |
| `backend/tests/test_policy_qa_conversation.py` | 新建 | 本次新增行为的后端测试 |
| `web/src/views/PolicyPage.vue` | 改 | 范围选项、未核验前提、对话气泡、点选建议、带上下文 |
| `web/tests/policy-page-conversation.spec.ts` | 新建 | 前端测试 |
| `backend/docs/policy-api.md`、`README.md` | 改 | 接口与行为说明 |

---

### Task 1: 依据分层：待核实也能作答，拒答原因说真话

**Files:**
- Modify: `backend/app/policy/qa.py`（`_prepare`、`_assemble`、`_evidence_preview`、`answer`、`answer_stream`）
- Modify: `backend/app/policy/router.py:32-40`（`_options` 的 `scope` 默认值）
- Modify: `backend/tests/test_policy_qa_t1.py`
- Create: `backend/tests/test_policy_qa_conversation.py`

**Interfaces:**
- Produces:
  - `qa.UNVERIFIED_NOTICE: str`：Global Constraints 里的固定文案。
  - `ctx["basis"]: Literal["verified", "unverified", "deprecated"]`。
  - `answered` 载荷新增字段 `basis`（同上）、`basis_notice: str`（仅 `unverified` 时为 `UNVERIFIED_NOTICE`，否则 `""`）。
  - `no_basis` 载荷新增字段 `reason_code: Literal["not_in_force", "model_insufficient"]`。
  - 流式 `evidence` 事件新增字段 `basis`、`basis_notice`。
  - `_prepare(...) -> tuple[dict | None, dict | None, ChatContext | None]`：三者恰有一个非 `None`。Task 1 里第三项先固定返回 `None`，原来走「无依据」分支、并且不属于 `not_in_force` 的情况暂时仍返回 `no_basis`；Task 2 再把这些情况改为返回 `ChatContext`。

- [ ] **Step 1: 写失败的测试**

新文件 `backend/tests/test_policy_qa_conversation.py`，开头写 `from test_policy_qa_t1 import api, add, ask, SAMPLE, LOAN_Q  # noqa: F401`，复用那边的 `api` fixture 和辅助函数（`pytestmark` 同样设为 `block_network`）。

```python
def test_unverified_policy_answers_with_fixed_notice(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法")      # 不核验
    res = ask(api, LOAN_Q)                                               # 默认 scope
    assert res["status"] == "answered" and res["basis"] == "unverified"
    assert res["basis_notice"] == qa.UNVERIFIED_NOTICE
    assert res["citations"][0]["status"] == "待核实" and "[1]" in res["conclusion"]
    assert res["sufficiency"] == "partial"

def test_verified_clause_wins_over_unverified(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    add(api.library, SAMPLE.replace("示例市", "另一市"), "另一市小微企业首次贷款贴息管理办法")
    res = ask(api, LOAN_Q)
    assert res["basis"] == "verified" and res["basis_notice"] == ""
    assert {c["status"] for c in res["citations"]} == {"现行有效"}

def test_strict_scope_still_excludes_unverified(api):
    add(api.library, SAMPLE, "未核验贴息办法")
    res = ask(api, LOAN_Q, scope="current")
    assert res["status"] != "answered"

@pytest.mark.parametrize("effective,expire", [("2020-01-01", "2021-01-01"), ("2099-01-01", None)])
def test_not_in_force_reason_does_not_blame_the_threshold(api, effective, expire):
    add(api.library, SAMPLE, "日期不在有效期内的办法", verify="current", effective=effective, expire=expire)
    res = ask(api, LOAN_Q)
    assert res["status"] == "no_basis" and res["reason_code"] == "not_in_force"
    assert "未达到可信阈值" not in res["reason"]

def test_stream_evidence_event_carries_the_notice(api):
    # 用 llm_chat.stream 打桩返回「贴息比例为百分之五十[1]。」，解析 SSE
    # 断言 evidence 事件的 basis == "unverified" 且 basis_notice == qa.UNVERIFIED_NOTICE，
    # final 事件的 data["basis"] == "unverified"
```

再改 `test_policy_qa_t1.py` 里随新规则变化的两个旧用例：

- `test_import_is_unverified_and_not_used_as_basis`：改名为 `test_import_is_unverified_and_strict_scope_excludes_it`。断言改成：`ask(api, LOAN_Q, scope="current")["status"] != "answered"`；`scope="policy"` 指定该政策时 `status == "answered"`，并且 `basis == "unverified"`。
- `test_stream_uses_the_same_rules`：断言改为文本中含 `"basis": "unverified"` 和 `[DONE]`。

`test_verified_but_expired_or_not_yet_effective_is_not_a_basis`、`test_abolished_policy_is_excluded_and_listed_as_history`、`test_model_refusal_remains_no_basis` 保持不变，必须仍然通过。

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && python -m pytest tests/test_policy_qa_conversation.py tests/test_policy_qa_t1.py -q`
Expected: 新用例 FAIL（`KeyError: 'basis'` 或状态为 `no_basis`）。

- [ ] **Step 3: 实现**

在 `_prepare` 里，按「过阈值的候选」挑依据，依次判断：

1. 有 `现行有效` → `basis="verified"`；
2. `include_deprecated` 且有 `已废止` → `basis="deprecated"`（现有的 `used_deprecated`）；
3. 有 `待核实` → `basis="unverified"`，证据取 `pending[:max_evidence]`；
4. 过阈值的只有 `已废止` / `尚未生效` → `no_basis`，`reason_code="not_in_force"`。原因按实际状态写，例如「相关条款来自已废止或尚未生效的文件（《…》），不能作为现行依据。」，**不提阈值**；
5. 其余情况 → Task 1 暂时保留现有的 `no_basis`。这时 reason 里**只有在最高分确实低于阈值时**才写「未达到可信阈值」。

`_assemble` 写入 `basis` 和 `basis_notice`；`basis == "unverified"` 时 `sufficiency` 恒为 `"partial"`，`manual_confirm` 追加「本次引用的《X》尚未经人工核验，正式行文前请审核人在政策库核验。」（每份政策一条）。`_is_insufficient` 分支加 `reason_code="model_insufficient"`。`router._options` 的 `scope` 默认值改为 `"all"`（`current` 保留为「仅已核验现行政策」的严格模式）。

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && python -m pytest tests/test_policy_qa_conversation.py tests/test_policy_qa_t1.py tests/test_policy_router.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/policy/qa.py backend/app/policy/router.py backend/tests/test_policy_qa_t1.py backend/tests/test_policy_qa_conversation.py
git commit -m "feat(policy-qa): 待核实政策可作答并由后端固定加注未核验前提"
```

---

### Task 2: 对话路线：打招呼、库外问题、无关问题

**Files:**
- Create: `backend/app/policy/conversation.py`
- Modify: `backend/app/policy/qa.py`（`_prepare` 的第 5 种情况和覆盖度闸门改为返回 `ChatContext`；`answer`、`answer_stream`、`_log`）
- Modify: `backend/app/policy/models.py:40`（注释补 `chat`）
- Modify: `backend/tests/test_policy_qa_t1.py`（`test_unrelated_question_has_no_basis`）
- Test: `backend/tests/test_policy_qa_conversation.py`

**Interfaces:**
- Consumes: Task 1 的 `_prepare` 三元组。
- Produces（`conversation.py`）：
  - `Kind = Literal["greeting", "policy", "other"]`
  - `classify(question: str, has_candidates: bool) -> Kind`：用正则判断。`greeting`：问题去掉标点后整句是 `你好|您好|hi|hello|在吗|早上好|下午好|晚上好|谢谢|辛苦了` 之一，或以这些词开头且总长不超过 8 个字；`policy`：`has_candidates` 为真（调用方传入「存在分数 ≥ 0.3 的候选」），或包含 `政策|办法|通知|规定|条例|意见|补贴|补助|申请|办理|文件`；其余为 `other`。只用于兜底话术和给模型的提示，不决定路线。
  - `@dataclass ChatContext`：`kind: Kind`、`stats: dict`（`total`、`verified`、`unverified`）、`suggestions: list[dict]`（`policy_id`、`title`、`status`；Task 3 填充，这里默认 `[]`）、`scope_hint: str`（默认 `""`）、`known_titles: set[str]`。
  - `CHAT_SYSTEM_PROMPT: str`
  - `build_chat_messages(question: str, history: list[dict], ctx: ChatContext) -> list[dict[str, str]]`
  - `guard_reply(text: str, known_titles: set[str]) -> str | None`：返回清理后的文本；`None` 表示必须改用兜底。
  - `fallback_reply(ctx: ChatContext, question: str) -> str`
  - `chat_payload(reply: str, generated_by: str, ctx: ChatContext, scope: str) -> dict`
- 对话载荷：`{"status": "chat", "sufficient": False, "reply": str, "conclusion": "", "supplement": "", "reason": "", "reason_code": "", "manual_confirm": [], "citations": [], "candidates": [], "suggestions": ctx.suggestions, "scope_hint": ctx.scope_hint, "meta": {"scope", "generated_by", "kind", "model"}}`，其中 `generated_by` 为 `"chat_llm"` 或 `"chat_fallback"`。
- 流式事件：对话路线依次发 `{"type": "mode", "mode": "chat"}`、若干 `delta`、可选的 `replace`（质检换成兜底时）、`final`。

- [ ] **Step 1: 写失败的测试**

```python
def test_greeting_gets_a_friendly_reply_not_a_refusal(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    with patch("app.services.llm_chat.chat", return_value="您好！我可以帮您查政策条款……"):
        res = api.client.post("/api/v1/policy/qa", json={"question": "你好"}).json()["data"]
    assert res["status"] == "chat" and res["reply"].startswith("您好")
    assert res["citations"] == [] and res["meta"]["generated_by"] == "chat_llm"

@pytest.mark.parametrize("question,kind", [("你好", "greeting"), ("外地户籍人员申请人才公寓补贴需要什么材料", "policy"), ("电脑命令行怎么查看IP地址", "other")])
def test_model_unavailable_uses_rotating_fallback(api, question, kind):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    res = ask(api, question)                       # ask() 已把模型打桩为不可用
    assert res["status"] == "chat" and res["meta"]["kind"] == kind
    assert res["meta"]["generated_by"] == "chat_fallback" and res["reply"]
    assert "已检索" not in res["reply"]

def test_fallback_wording_varies_between_questions():
    ctx = ChatContext(kind="other", stats={"total": 1, "verified": 1, "unverified": 0}, known_titles=set())
    replies = {fallback_reply(ctx, q) for q in ["电脑怎么关机", "打印机连不上怎么办", "WPS怎么改页边距", "Excel公式怎么写"]}
    assert len(replies) >= 2

def test_chat_reply_naming_unknown_policy_falls_back():
    assert guard_reply("根据《某市人才安居办法》，可以申请。", {"示例市小微企业首次贷款贴息管理办法"}) is None
    assert guard_reply("可以参考《示例市小微企业首次贷款贴息管理办法》。", {"示例市小微企业首次贷款贴息管理办法"})

def test_chat_reply_with_code_block_falls_back():
    assert guard_reply("建议咨询信息部门。\n```\nipconfig\n```", set()) is None

def test_chat_reply_strips_citation_markers_and_doc_numbers_fall_back():
    assert "[1]" not in guard_reply("您好[1]，请问需要查哪方面的政策？", set())
    assert guard_reply("见示政发〔2024〕3号。", set()) is None

def test_chat_stream_emits_mode_then_replace_when_guarded(api):
    # llm_chat.stream 打桩返回 ["根据《不存在办法》", "可以申请。"]，问题为「有没有人才公寓补贴」
    # 断言事件类型依次包含 "mode"(mode == "chat")、"delta"、"replace"、"final"，
    # 并且 final 的 data["reply"] == replace 事件的 text，data["meta"]["generated_by"] == "chat_fallback"

def test_chat_turn_is_logged_with_chat_status(api):
    # 调一次「你好」后，GET /api/v1/policy/qa/logs，最新一条 status == "chat"，answer 为回复正文
```

并把 `test_policy_qa_t1.py::test_unrelated_question_has_no_basis` 改名为 `test_unrelated_question_gets_chat_reply_without_citations`，断言改为 `status == "chat"`、`citations == []`、`conclusion == ""`。

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && python -m pytest tests/test_policy_qa_conversation.py -q`
Expected: 新用例 FAIL（`ModuleNotFoundError: app.policy.conversation` 或 `status == "no_basis"`）。

- [ ] **Step 3: 实现 `conversation.py`，并把 `qa.py` 接上**

`CHAT_SYSTEM_PROMPT` 的要求（措辞可以调整，规则不可少）：

- 身份：本单位政务办公系统里的「政策问答」助手，围绕本单位政策库服务；
- 打招呼、寒暄：自然、简短地回应，说明能做什么（查政策条款、解读政策、按名称找政策文件），给一两个问法示例；
- 问政策，但下文「政策库情况」没有给出相关内容：说明政策库暂未找到相关内容，建议换个关键词、写明政策全称，或请审核人导入。**不得凭自身知识陈述任何政策内容、政策名称、文号或数字**；
- 与政策和政务办公无关（电脑操作、编程、生活常识等）：友好说明这里专门解答政策问题，建议咨询信息部门或相关专业人员；**不给出任何具体步骤、命令或答案**；
- 措辞自然，不要每次都用同一句话；不超过 120 字；不使用 `[n]` 引用标记；不输出标题或代码块。

`build_chat_messages` 的组成：

- system 消息：`CHAT_SYSTEM_PROMPT`；
- 依次加入 `history` 中的 user / assistant 消息；
- 最后一条 user 消息：先写「政策库情况：共 N 份，已核验 V 份，待核实 U 份。」；有 `suggestions` 时加「名称相近的政策：《…》、《…》」；有 `scope_hint` 时原样附上；然后写「问题类型参考：{kind}」，最后是用户原话。

`guard_reply`：先去掉 `<think>` 段落，删除 `[n]` 标记；以下情况返回 `None`：

- 含 ```` ``` ````；
- 含文号格式（正则 `〔\d{4}〕`）；
- 出现《X》，但 X 既不在 `known_titles` 中，也不是其中任何一个书名的子串；
- 清理后为空。

超过 300 字时，截到 300 字以内的最后一个句末标点。

`fallback_reply`：每种 `kind` 至少 3 句，按 `sum(map(ord, question)) % len(templates)` 轮换（结果确定，便于测试）：

- `greeting`：例如「您好！我是政策问答助手，可以帮您查找政策条款、解读政策要求。您可以直接问，比如『小微企业贷款贴息的比例是多少』。」
- `policy`：例如「政策库里暂时没有找到和这个问题直接相关的内容。可以换个关键词，或者告诉我政策的全称；如果文件还没入库，可以请审核人导入。」
- `other`：例如「这个问题不在政策问答的范围内，建议咨询单位信息部门或相关专业同事。政策方面有什么需要，随时问我。」

另外两句改换说法，意思不变；`stats["verified"] == 0` 且 `kind == "policy"` 时补一句「目前政策库里的文件都还没有核验」。

`qa.py` 的改动：

- `_prepare` 的第 5 种情况和覆盖度闸门改为返回 `ChatContext`。`stats` 用 `library.store` 现有的计数（同 `/gov/policies/stats` 的做法）。`known_titles` 为 `corpus.load(store, scope="all")` 中所有政策的标题。
- `scope == "current"` 时另外用 `scope="all"` 再检索一次：如果有过阈值的待核实条款，`scope_hint` 写「当前范围为『仅已核验现行政策』；另有 N 条相关条款在待核实政策中，切换到『全部入库政策』可查看。」
- `answer()`：用 `llm_chat.chat(build_chat_messages(...), temperature=0.6)` 生成；异常或 `guard_reply` 返回 `None` 时用 `fallback_reply`。
- `answer_stream()`：先发 `mode` 事件，再用 `llm_chat.stream` 逐块发 `delta`；最终文本与流出的文本不同时发 `replace`。
- `_log`：`status` 取载荷的 `status`（`answered` / `no_basis` / `chat`），`answer` 取 `conclusion or reply or reason`。

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && python -m pytest tests/test_policy_qa_conversation.py tests/test_policy_qa_t1.py tests/test_policy_router.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/policy/conversation.py backend/app/policy/qa.py backend/app/policy/models.py backend/tests/test_policy_qa_t1.py backend/tests/test_policy_qa_conversation.py
git commit -m "feat(policy-qa): 无依据时走对话路线，打招呼和无关问题友好回应"
```

---

### Task 3: 「帮我看看某某政策」：按政策名匹配

**Files:**
- Create: `backend/app/policy/titles.py`
- Modify: `backend/app/policy/qa.py`（`_prepare` 开头接入；概要作答与兜底）
- Test: `backend/tests/test_policy_qa_conversation.py`

**Interfaces:**
- Consumes: `corpus.load` 的行（`(ClauseView, PolicyView)`）；Task 2 的 `ChatContext.suggestions`。
- Produces:
  - `titles.TitleMatch`（dataclass）：`policy: PolicyView`、`score: float`
  - `titles.match_titles(question: str, policies: list[PolicyView]) -> list[TitleMatch]`：按分数降序排列，只返回 `score >= 0.5` 的项
  - `titles.STRONG = 0.8`
  - `ctx["mode"]: Literal["answer", "overview"]`；`answered` 载荷的 `meta.mode` 同值
  - 概要原文兜底的 `generated_by` 为 `"extractive_overview"`

- [ ] **Step 1: 写失败的测试**

```python
def test_match_titles_scores_bookmarked_and_loose_names():
    p = [view(1, "示例市小微企业首次贷款贴息管理办法"), view(2, "示例市政务数据共享办法")]   # view(): 测试内构造 PolicyView 的小工具
    assert match_titles("帮我看看《示例市小微企业首次贷款贴息管理办法》", p)[0].policy.id == 1
    assert match_titles("能帮我看看小微企业首次贷款贴息办法吗", p)[0].score >= STRONG
    assert match_titles("你好", p) == []

def test_named_policy_gets_an_overview_with_citations(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    add(api.library, CURRENT_REPLACEMENT, "示例市政务数据共享办法", verify="current")   # 从 test_policy_qa_t1 导入
    res = ask(api, "能帮我看看小微企业首次贷款贴息管理办法吗")
    assert res["status"] == "answered" and res["meta"]["mode"] == "overview"
    assert {c["policy_title"] for c in res["citations"]} == {"示例市小微企业首次贷款贴息管理办法"}
    assert res["meta"]["generated_by"] == "extractive_overview"      # ask() 下模型不可用

def test_named_policy_with_specific_question_answers_inside_that_policy(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    res = ask(api, "《示例市小微企业首次贷款贴息管理办法》的补贴比例是多少")
    assert res["meta"]["mode"] == "answer" and "第六条" in [c["clause_no"] for c in res["citations"]]

def test_plain_question_is_not_treated_as_a_title_lookup():
    p = [view(1, "示例市小微企业首次贷款贴息管理办法")]
    assert match_titles("贷款贴息比例是多少", p) == []

def test_ambiguous_title_asks_back_with_suggestions(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法")
    add(api.library, SAMPLE.replace("管理办法", "管理办法实施细则"), "示例市小微企业首次贷款贴息管理办法实施细则")
    res = ask(api, "帮我看看小微企业贴息的办法")
    assert res["status"] == "chat"
    assert {s["title"] for s in res["suggestions"]} == {"示例市小微企业首次贷款贴息管理办法", "示例市小微企业首次贷款贴息管理办法实施细则"}

def test_unverified_overview_carries_the_notice(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法")
    res = ask(api, "帮我看看示例市小微企业首次贷款贴息管理办法")
    assert res["meta"]["mode"] == "overview" and res["basis_notice"] == qa.UNVERIFIED_NOTICE
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && python -m pytest tests/test_policy_qa_conversation.py -q -k "title or overview"`
Expected: FAIL（`ModuleNotFoundError: app.policy.titles`）。

- [ ] **Step 3: 实现**

`match_titles` 的算法：

1. **先判断是不是在找政策**：问题里有《…》，或含 `看看|看一下|介绍|了解`，或去掉填充词后以 `办法|通知|规定|条例|意见|细则|方案|政策` 结尾，才算在找政策；否则直接返回 `[]`。这样「贷款贴息比例是多少」这种普通问题不会被当成按名称找政策。
2. **取问题一侧的名称**：有《…》时取书名号里的内容；否则取整句，再去掉填充词 `帮我|看看|看一下|介绍|了解|一下|能|吗|请|这个|政策|文件`。
3. **取标题核心**：去掉 `关于`、`印发`、`的通知`、`（试行）`/`(试行)` 和标点。
4. **打分**：用 `retrieval.tokenize` 切出二元字组，分数 = max(标题二元组被名称覆盖的比例, 名称二元组被标题覆盖的比例)。有书名号、并且两边互为子串时，分数记为 1.0。

在 `_prepare` 最前面接入：

- **唯一强匹配**：只有一项 `score >= STRONG`，并且它比第二名至少高 0.15。先算「剩余问题」：问题里有书名号时，删掉书名号那一段；没有时，先删掉填充词，再删掉问题与标题核心的最长公共子串（`difflib.SequenceMatcher.find_longest_match`，长度至少 4）。
  - 剩余问题的 `retrieval.content_terms` 为空，说明只是想看这份政策 → `mode="overview"`，证据取这份政策前 6 条正文条款（按 `seq` 排序，跳过 `_is_title_only`），不受阈值限制；
  - 不为空 → 只在这份政策内用剩余问题跑 BM25：有过阈值的条款就正常作答（`mode="answer"`），没有就退回 `overview`；
  - 两种情况的 `basis` 都按这份政策的状态定；已废止或尚未生效的政策走 `not_in_force`。
- **否则**：把 `score >= 0.5` 的前 3 项写进 `ChatContext.suggestions`，供 Task 2 的对话路线使用。

概要作答的模型指令：在 `_build_messages` 的 user 内容末尾，把「请依据上述条款作答」换成「请概括这份政策的主要内容：适用对象、主要措施、申请条件或办理要求，每句标注引用序号」。

`_apply_guards` 在 `overview` 模式下不走数值直引（`_asks_number` 分支），其余质检照旧。模型不可用或输出被质检拒掉时，用新函数 `_overview_extract(evidence) -> str`：取前 3 条证据各自的第一句，依次标注 `[1]`、`[2]`、`[3]`，`generated_by="extractive_overview"`。

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && python -m pytest tests/test_policy_qa_conversation.py tests/test_policy_qa_t1.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/policy/titles.py backend/app/policy/qa.py backend/tests/test_policy_qa_conversation.py
git commit -m "feat(policy-qa): 按政策名称匹配，唯一时给出政策概要，多份时反问"
```

---

### Task 4: 多轮上下文

**Files:**
- Modify: `backend/app/policy/router.py`（`_options` 解析 `history`）
- Modify: `backend/app/policy/qa.py`（`answer`、`answer_stream`、`_prepare`、`_build_messages` 接收 `history`）
- Test: `backend/tests/test_policy_qa_conversation.py`

**Interfaces:**
- Consumes: Task 2 的 `build_chat_messages(question, history, ctx)`。
- Produces:
  - 请求体字段 `history: list[{"question": str, "answer": str}]`；
  - `router._clean_history(raw) -> list[dict]`：非列表返回 `[]`；丢掉非 dict 项和两个字段都为空的项；保留最后 3 项；`question` 截到 200 字、`answer` 截到 300 字；
  - `answer(..., history: list[dict] | None = None)`、`answer_stream(..., history=...)`；
  - `_build_messages(question, evidence, history=None)`；
  - `answered` 载荷的 `meta.followup: bool`。

- [ ] **Step 1: 写失败的测试**

```python
def test_clean_history_limits_turns_and_length():
    raw = [{"question": "q" * 500, "answer": "a" * 900}] * 5 + ["bad", {"x": 1}]
    out = _clean_history(raw)
    assert len(out) == 3 and len(out[0]["question"]) == 200 and len(out[0]["answer"]) == 300

def test_followup_question_is_answered_from_the_previous_topic(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    history = [{"question": "小微企业首次贷款贴息有什么规定", "answer": "……"}]
    res = ask(api, "那申请材料包括什么", history=history)
    assert res["status"] == "answered" and res["meta"]["followup"] is True
    assert res["citations"][0]["clause_no"] == "第五条"

def test_followup_only_combines_when_current_question_has_no_basis(api):
    add(api.library, SAMPLE, "示例市小微企业首次贷款贴息管理办法", verify="current")
    add(api.library, CURRENT_REPLACEMENT, "示例市政务数据共享办法", verify="current")
    history = [{"question": "小微企业首次贷款贴息有什么规定", "answer": "……"}]
    res = ask(api, SHARE_Q, history=history)
    assert res["meta"]["followup"] is False
    assert res["citations"][0]["policy_title"] == "示例市政务数据共享办法"

def test_history_is_sent_to_the_model(api):
    # patch llm_chat.chat 捕获 messages；history 一轮、问题「你好」
    # 断言 messages 中依次有 role 为 user（历史问题）、assistant（历史回答）的两条，且位于最后一条 user 之前
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd backend && python -m pytest tests/test_policy_qa_conversation.py -q -k "history or followup"`
Expected: FAIL（`ImportError: _clean_history`，或 `followup` 缺失）。

- [ ] **Step 3: 实现**

- `_options` 增加 `"history": _clean_history(payload.get("history"))`。
- `_prepare`：先用当前问题走完 Task 1 和 Task 3 的判断。如果结果是对话路线，并且 `history` 非空、`classify(...) != "greeting"`，就用 `history[-1]["question"] + "；" + question` 作为检索词（政策名匹配同样用它）再走一遍。第二遍有依据就采用，并设 `meta.followup = True`；否则保持对话路线。
- `_build_messages` 和 `build_chat_messages` 都把历史按 user / assistant 消息插在最后一条 user 消息之前。

- [ ] **Step 4: 运行，确认通过**

Run: `cd backend && python -m pytest tests/test_policy_qa_conversation.py tests/test_policy_qa_t1.py tests/test_policy_router.py -q`
Expected: 全部 PASS。

- [ ] **Step 5: Commit**

```bash
git add backend/app/policy/router.py backend/app/policy/qa.py backend/tests/test_policy_qa_conversation.py
git commit -m "feat(policy-qa): 带最近三轮上下文，追问能接上前文"
```

---

### Task 5: 前端：范围选项、未核验前提、对话气泡、点选建议、带上下文

**Files:**
- Modify: `web/src/views/PolicyPage.vue`（这是真实环境下 `/gov/policy-qa` 嵌入的页面；`gov-office/pages/PolicyQaPage.vue` 在 http 模式下直接渲染它）
- Create: `web/tests/policy-page-conversation.spec.ts`

**Interfaces:**
- Consumes: Task 1 到 Task 4 的载荷字段：`basis`、`basis_notice`、`status: "chat"`、`reply`、`suggestions`、`scope_hint`、`meta.mode`、`meta.generated_by`（`chat_llm` / `chat_fallback` / `extractive_overview`）；流式 `mode` 事件；请求字段 `history`。

- [ ] **Step 1: 写失败的测试**

参照 `web/tests/policy-page.spec.ts` 的 `setup` / `mountPage`。用 `vi.stubGlobal("fetch", ...)` 返回 `new Response(sse, { headers: { "Content-Type": "text/event-stream" } })`，写法同 `web/tests/gov-office/policy-navigation.spec.ts`。

```ts
it("defaults to the whole library and no longer promises a trial search", async () => {
  // select.gov-select 的值为 "all"，选项文本含「全部入库政策（已核验优先）」「仅已核验现行政策」
  // 页面不含「试查」
});
it("shows the backend's unverified notice above the conclusion and in the copied text", async () => {
  // final: status answered, basis "unverified", basis_notice 为固定文案
  // .gov-basis-notice 文本 === 固定文案；徽标为「依据未核验」
  // 点「复制回答」后 navigator.clipboard.writeText 的参数以固定文案开头
});
it("renders chat replies and applies the final replacement", async () => {
  // 事件：mode(chat) → delta「根据《不存在办法》」 → replace「政策库里暂时没有找到…」 → final(status chat, reply 同 replace)
  // .gov-chat 文本含「政策库里暂时没有找到」且不含「不存在办法」；页面不含「未找到足够依据」
});
it("asks about a suggested policy when it is clicked", async () => {
  // final: status chat, suggestions [{policy_id: 2, title: "现行办法", status: "现行有效"}]
  // 点击 .gov-suggestion 后，第二次 fetch 的 body：scope === "policy"、policy_ids 为 [2]、question 为「介绍一下《现行办法》」
});
it("sends the last three finished turns as history", async () => {
  // 连续问 4 次（每次 final 为 chat reply「回复n」），第 5 次请求 body.history 长度为 3，
  // 最后一项为 { question: 第4问, answer: "回复4" }
});
```

- [ ] **Step 2: 运行，确认失败**

Run: `cd web && npx vitest run tests/policy-page-conversation.spec.ts`
Expected: FAIL。

- [ ] **Step 3: 实现（只改 `PolicyPage.vue`）**

- **范围**：`scope` 默认值改为 `'all'`。选项改为：
  - `all`「全部入库政策（已核验优先）」
  - `current`「仅已核验现行政策」
  - `policy`「仅选中政策」
- **待核实提示行**（现在第 119-121 行）改为：「有 {{ stats.unverified }} 份政策尚未核验；回答引用这些政策时会注明『未经核验』。」
- **空态文案**：示例改为同时提到「可以直接提问，或说『帮我看看《某某办法》』」；第二行改为「回答依据政策库；引用未核验政策时会注明」。
- **有依据块**：
  - `basis_notice` 非空时，在结论前渲染 `<p class="gov-basis-notice" role="note">`，用警示色；
  - 徽标：`basis === 'unverified'` 时为「依据未核验」，其余保持现有逻辑；
  - `sourceLabel` 增加 `extractive_overview` →「原文摘录（政策概要）」；
  - `meta.mode === 'overview'` 时，引用标题处写「政策概要的引用依据」。
- **对话块**：新增 `v-else-if="t.data.status === 'chat'"`，结构如下：
  - `.gov-chat` 普通气泡（不带警告图标），显示 `reply`；
  - `scope_hint` 非空时显示提示，并带按钮「切换到全部入库政策」（设 `scope = 'all'`）；
  - `suggestions` 渲染成 `button.gov-suggestion`，内容为《title》加状态标签。点击时设 `focusPolicy = policy_id`、`scope = 'policy'`、`question = '介绍一下《title》'`，再调用 `ask()`。

  原来的无依据块条件从 `t.data.status !== 'answered'` 改为 `t.data.status === 'no_basis'`，并放在对话块之后。
- **流式**：
  - `mode` 事件（`mode === 'chat'`）初始化 `turn.data = { status: 'chat', reply: '', suggestions: [], scope_hint: '', citations: [], meta: {} }`；
  - `delta` / `replace` 在 `status === 'chat'` 时作用于 `reply`，否则作用于 `conclusion`；
  - `evidence` 事件把 `basis`、`basis_notice` 带进 `turn.data`。
- **上下文**：新增 `historyPayload()`。从 `turns` 中取当前这一轮之前、已完成（有 `data`、无 `error`、不在流式中）的最后 3 轮，组成 `{ question, answer: (chat ? reply : conclusion || reason).slice(0, 300) }`，放进请求 `payload.history`。
- **复制**：`copyAnswer` 中，对话轮复制 `reply`；有依据的轮复制 `(basis_notice ? basis_notice + '\n' : '') + conclusion`。
- **删除轮次**：`removeTurn` 里的 `t.data.citations` 改为 `t.data?.citations || []`，防止对话轮或未完成轮报错。

- [ ] **Step 4: 运行，确认通过**

Run: `cd web && npx vitest run tests/policy-page-conversation.spec.ts tests/policy-page.spec.ts tests/gov-office/policy-navigation.spec.ts && npm run typecheck`
Expected: 全部 PASS。`policy-navigation.spec.ts` 里断言「含待核实依据」的用例不带 `basis` 字段，应当保持通过。

- [ ] **Step 5: 全量回归**

Run: `cd web && npm test`
Expected: 全部 PASS（基线：node 16 个、vitest 44 个文件 287 个用例全部通过，再加上本任务新增的）。

- [ ] **Step 6: Commit**

```bash
git add web/src/views/PolicyPage.vue web/tests/policy-page-conversation.spec.ts
git commit -m "feat(web): 政策问答支持对话、未核验前提、点选政策与多轮上下文"
```

---

### Task 6: 文档与真实模型验收

**Files:**
- Modify: `backend/docs/policy-api.md`（问答接口：`scope` 默认值、`history`、`status: "chat"`、`basis` / `basis_notice`、`reason_code`、`mode` 流式事件）
- Modify: `README.md:20`（政策问答一行改为：「基于政策库作答，已核验政策直接引用，未核验政策注明『未经核验』；支持打招呼、按名称介绍政策和多轮追问；与政策无关的问题友好转开」）
- Modify: `docs/測試疑問.md`（在 2026-10-27 两节下各加一行「处理：见 docs/superpowers/specs/2026-10-27-policy-qa-conversational-design.md」）

- [ ] **Step 1: 更新三份文档**（内容以 Task 1 到 Task 5 实际实现的字段为准）。

- [ ] **Step 2: 后端全量回归**

Run: `cd backend && python -m pytest tests -q -k "policy or gov"`
Expected: 除 Global Constraints 中列出的 6 个环境基线用例外全部 PASS。

- [ ] **Step 3: Commit 并推送**

```bash
git add backend/docs/policy-api.md README.md docs/測試疑問.md
git commit -m "docs(policy-qa): 记录对话式政策问答的接口与行为"
git push github feat/policy-qa-conversational
```

- [ ] **Step 4: 在 Win 机器上用真实模型按场景验收**（政策库保持现状：101 份全部待核实）

| # | 输入 | 期望 |
|---|---|---|
| 1 | 你好 | 自然的问候，说明能做什么，没有「未找到足够依据」 |
| 2 | 能帮我看看《某份已入库政策的名称》吗 | 政策概要，开头是未核验前提，带 [n] 引用 |
| 3 | 那申请条件是什么 | 接着上一份政策回答，开头是未核验前提 |
| 4 | 电脑命令行怎么查看 IP 地址 | 友好转开，不给命令；换个说法再问一次，措辞不同 |
| 5 | 有没有关于人才公寓补贴的政策（库里没有的主题） | 说明政策库暂未收录，不出现任何书名或文号 |
| 6 | 审核人在政策库核验一份政策后，再问它的内容 | 不再有未核验前提，徽标为「依据充分」 |
| 7 | 范围切到「仅已核验现行政策」后重复第 2 问 | 提示可切换到全部入库政策 |

把每一项的截图放进收发箱，或者贴到 PR 里。
