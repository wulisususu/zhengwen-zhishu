# 政策检索接口契约（T1 + 文件/条款两级增补）

数据只来自公开政策库，存放在 `policy.db`（默认路径 `backend/data/policy.db`，可通过 `policy.db_path` 配置），与用户私有知识库（`app/kb`，独立数据库）**分库存放**，检索时从不混用。

## 1. 数据来源（gov.cn 政策文件库）

`GET {policy.base_url}`，必需参数 `t=zhengcelibrary`；可选参数 `q`、`p`、`n`、`searchfield`、`sort`、`pubtimeyear`。

| 事实 | 处理 |
|---|---|
| `p` 为 1 起始；`p=0` 时 `n` 失效 | 客户端把 `p` 归一到 `>= 1` |
| 结果在 `searchVO.catMap.{gongwen,bumenfile,otherfile,gongbao}.listVO`，不在 `data` 里 | 解析器只读 `catMap`；同一 url 在多个分类重复出现时只保留第一条 |
| `searchVO.totalCount` 恒为 0 | 不使用；「还有下一页」= 本页返回条数 ≥ `n` |
| `title` 含 `<em>`、`<br/>` 及实体 | 去标签、反转义、合并空白 |
| `summary` 只是正文开头 | 只作摘要展示，不当全文 |
| `pcode` = 发文字号（`fwzh` 常为空） | 文号只取 `pcode` |
| `pubtimeStr` 形如 `2024.01.16`，可能缺失 | 统一为 `YYYY-MM-DD`；缺失时用 `ptime`（毫秒，按北京时间换算） |

网络行为：
- 超时 15 秒；只在超时或 5xx 时重试，最多 2 次；
- 请求间隔 ≥ 1 秒，串行执行；
- 同一组 `(q, p, n)` 5 分钟内走内存缓存；
- 翻页不超过 20 页。

日志只记录检索词、页码、耗时、条数和错误类型，不打印响应体。

**出口策略**：每次请求前读取 `app/services/model_policy.get_mode()`。只有 `cloud_allowed` 才能访问 gov.cn；`intranet`、`offline` 或模式配置无效时一律不发请求。

## 2. 存储

### `policy_documents`（每个版本一行）

T1 字段：`id, source, remote_id, title, doc_number, issuer, publish_date(YYYY-MM-DD), category, subject, url, summary, content, content_hash, fetched_at, verified_status`

增补字段：`version, is_current, superseded_by, last_checked_at, effective_date, expire_date, status_note, verified_by, verified_at, origin(search|url_import|file_import)`

版本规则：
- 以 `url`（即 source_url）为版本链主键，每个版本一行；`(url, version)` 唯一，同一 url 只有一行 `is_current = 1`。
- 正文 `content_hash` 变化时：插入新的一行（`version + 1`），旧行置 `is_current = 0`、`superseded_by` 指向新行。旧行和旧条款**全部保留**，不做物理覆盖。
- hash 未变：只更新 `last_checked_at`。
- 整个过程在同一个事务中完成；任何一步失败都会回滚，已有数据（包括已核验的数据）保持原样。
- 检索结果的元数据不会覆盖已经导入的正文版本，只会刷新 `last_checked_at`。
- T1 的「`url UNIQUE` + 原地更新」已改为上述版本化规则。旧库在首次启动时会自动重建迁移。

状态规则：
- `verified_status` 只允许 `current | abolished | unverified`（CHECK 约束），默认 `unverified`。
- 状态**只来自人工核验**（`/verify`）。网页能否访问不影响状态。每个新版本都从 `unverified` 开始。

### `gov_policy_clauses`

`id, policy_id, article_number, parent_clause_id, heading, content, sequence, page_number, source_anchor, needs_review`

条款切分：
- 按文中的层级标记切分：第X编 / 章 / 节 / 条、一、、（一）、1.、（1）。**不按长度切块。**
- `content` 保存该条完整原文（含编号），不做改写。
- 没有编号的段落并入当前条款；全部条款按 `sequence` 依次拼接，可以还原原文的每一段。
- `sequence` 在同一个 `policy_id` 内从 1 开始连续编号。
- `parent_clause_id` 记录层级关系；`source_anchor` 记录路径，例如 `第二章>第三条>（二）`。
- 以下情况置 `needs_review = 1`，正文照常保留：
  - 全文没有任何编号标记（每段各成一条）；
  - 编号跳号或倒序；
  - 单条超过 3000 字；
  - 网页中找不到正文容器。

## 3. 接口

除特别说明外，所有接口都返回统一包装 `{code, message, data, trace_id}`，`code = 0` 表示成功。失败时 `data.error = {code, message[, fallback]}`。

### T1（`/api/v1/policy`，保留）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/policy/search?q=&limit=` | 登录 | 先查本地（标题 / 摘要 LIKE），不足时联网补充并入库。`data.source` 取值：`local` / `local+remote` / `local_only`。联网失败时 `code` 仍为 0，返回本地结果，原因写在 `data.error` |
| GET | `/policy/documents?page=&page_size=` | 登录 | 分页，只返回当前版本 |
| GET | `/policy/documents/{id}` | 登录 | 不存在时返回 `40400` |
| POST | `/policy/sync` `{topic, pages≤20, per_page≤50}` | 管理员 | 返回 `{pages_fetched, fetched, inserted, new_versions, unchanged, stopped_reason}` |

### 增补（`/api/v1/gov`）

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/gov/policies/import` | 管理员 | multipart 表单：`url` 或 `file` 二选一，可选 `source_url`、`title`、`doc_number`、`issuer`、`publish_date`。**同步返回** `{policy, created_new_version, superseded_id, clause_count, needs_review_count}` |
| GET | `/gov/policies` | 登录 | 筛选：`keyword`、`doc_number`、`issuer`、`status`（可重复）、`include_history`、`url`、`page`、`page_size` |
| POST | `/gov/policies/search` | 登录 | `{query, statuses?, limit, include_history}`。**默认只检索 `current`**，其他状态必须显式传入；每条结果都带 `status` |
| POST | `/gov/citations/batch` | 登录 | `{ids: string[]}` → `{citations: Citation[], missing: string[]}`，按传入顺序返回 |
| POST | `/gov/policies/{id}/verify` | 管理员 | `{status, status_note?, title?, doc_number?, issuer?, publish_date?, effective_date?, expire_date?}`，记录 `verified_by` 和 `verified_at` |

条款检索命中示例（`data.hits[]`）：

```json
{
  "clause_id": 7, "citation_id": "clause:7@16-21", "policy_id": 3,
  "policy_title": "…", "doc_number": "…", "issuer": "…", "publish_date": "2025-01-20",
  "status": "current", "version": 2, "is_current_version": true,
  "article_number": "第三条", "heading": null, "clause": "第三条",
  "sequence": 4, "source_anchor": "第三条", "needs_review": false,
  "excerpt": {"before": "…", "highlight": "15个工作日", "after": "…"},
  "match": {"start": 16, "end": 21}
}
```

**citation id 格式**：`clause:<clause_id>@<start>-<end>`。命中位置在检索时记录在 id 里，前端原样传给 `citations/batch` 即可还原命中片段，无需保存会话状态。不带位置的 `clause:<id>` 也可以使用，此时高亮取该条第一句。

## 4. 后端字段 → `Citation`（`web/src/features/gov-office/types.ts`）

| Citation 字段 | 来源 | 说明 |
|---|---|---|
| `id` | 请求里传入的 citation id，原样返回 | 例如 `clause:7@16-21` |
| `policyTitle` | `policy_documents.title` | |
| `docNumber` | `policy_documents.doc_number`（即 gov.cn 的 `pcode`） | 为空时返回 `"未录入"` |
| `issuer` | `policy_documents.issuer`（即 `puborg`） | 为空时返回 `"未录入"` |
| `issuedOn` | `policy_documents.publish_date` | `YYYY-MM-DD`；为空时返回 `"未录入"` |
| `effectiveOn` | `policy_documents.effective_date` | 由人工核验录入；为空时返回 `"未录入"` |
| `expiresOn` | `policy_documents.expire_date` | 由人工核验录入；为空时返回 `"未录入"` |
| `status` | `policy_documents.verified_status` | 只可能是 `current` / `abolished` / `unverified` |
| `statusNote?` | `status_note` + 自动说明 | 自动说明包括：未核验提示；「所属版本已被第 N 版替代」；「条款切分需人工复核」。没有说明时省略该字段 |
| `clause` | `gov_policy_clauses.article_number`，其次 `heading`，否则 `第{sequence}段` | |
| `excerpt` | 条款 `content` 的前 60 字 | |
| `text.before / highlight / after` | 按 citation id 中的匹配位置，从 `content` 截取 | 前文 60 字、后文 80 字，截断处加 `…`；**不是整条原文** |
| `previousClause?` | 同一 `policy_id` 中 `sequence - 1` 的条款 | 格式为「编号 + 前 80 字」；第一条时省略 |
| `nextClause?` | 同一 `policy_id` 中 `sequence + 1` 的条款 | 最后一条时省略 |

## 5. 抓取的 SSRF 防护（`/gov/policies/import` 的 `url`）

- 只允许 http / https，不得包含用户名和密码，只允许默认端口。
- 域名必须**精确匹配**白名单：默认 `sousuo.www.gov.cn`、`www.gov.cn`；部门站点要写进 `policy.fetch.extra_allowed_hosts`。直接写 IP 的 URL 一律拒绝。
- 解析 DNS 后，**任意一个**地址属于私网、回环、链路本地（含 169.254.169.254）、CGNAT、ULA（fd00::）、保留地址或 IPv4 映射形式时，直接拒绝。
- 连接时固定使用已校验的 IP（SNI 和 Host 仍为原域名），防止 DNS 重绑定。
- 重定向最多 2 跳，每一跳都重新校验域名和 IP。
- 响应体上限 10 MB，超时 15 秒，只接受 `text/html` 和 `text/plain`。
- 抓取失败时返回 `FETCH_*` 错误码和原因，**不会编造正文**，同时在 `error.fallback` 中给出人工上传的替代路径：`file` 加上 `source_url`，可以接到同一条版本链上。
- 限制：连接是固定 IP 直连，如果部署环境必须经过 HTTP 代理才能出网，URL 导入无法使用，只能人工上传文件。

## 6. 错误码（`data.error.code`）

| 分类 | 错误码 |
|---|---|
| 参数（业务码 40000） | `INVALID_QUERY`、`INVALID_STATUS`、`UNSUPPORTED_FILE`、`FETCH_BAD_URL` |
| 不存在（业务码 40400） | `NOT_FOUND` |
| 其他（业务码 50200） | `EGRESS_BLOCKED`、`POLICY_DISABLED`、`POLICY_NOT_CONFIGURED`、`REMOTE_TIMEOUT`、`REMOTE_HTTP_ERROR`、`REMOTE_UNAVAILABLE`、`REMOTE_BAD_RESPONSE`、`FETCH_HOST_NOT_ALLOWED`、`FETCH_PRIVATE_ADDRESS`、`FETCH_DNS_FAILED`、`FETCH_TOO_MANY_REDIRECTS`、`FETCH_TOO_LARGE`、`FETCH_TIMEOUT`、`FETCH_HTTP_ERROR`、`FETCH_FAILED`、`FETCH_UNSUPPORTED_CONTENT`、`EXTRACT_FAILED`、`EMPTY_CONTENT`、`STORE_ERROR`、`INTERNAL_ERROR` |
