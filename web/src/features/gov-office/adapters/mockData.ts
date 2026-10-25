// DEMO FIXTURES ONLY.
// Every policy, document number, agency and record below is fictional and
// marked "演示". Nothing here may be shown as a backend result: the mock
// adapter stamps origin = "demo" and the UI renders a demo marker for it.

import type { Citation, Material, OfficialDocument, QaSession } from "../types";

export const DEMO_POLICY_STATS = { total: 128, current: 112, abolished: 11, unverified: 5 };

export const DEMO_CITATIONS: Citation[] = [
  {
    id: "c1",
    policyTitle: "示例市小微企业融资贴息实施办法（演示）",
    docNumber: "示政办规〔2025〕3号（演示）",
    issuer: "示例市财政局（演示机关）",
    issuedOn: "2025-03-10",
    effectiveOn: "2025-04-01",
    expiresOn: "2028-03-31",
    status: "current",
    clause: "第六条",
    excerpt: "申请首次贷款贴息的小微企业，应当同时符合下列条件……",
    text: {
      before: "申请首次贷款贴息的小微企业，应当同时符合下列条件：（一）在本市依法登记注册并",
      highlight: "正常经营满一年",
      after: "；（二）近两年内无严重失信记录；（三）贷款用途为生产经营，且贷款合同签订日期在本办法施行之后。",
    },
    previousClause: "第五条 本办法所称首次贷款，是指企业在金融机构获得的第一笔经营性贷款。",
    nextClause: "第七条 贴息资金由市级财政预算安排，实行年度总额控制。",
  },
  {
    id: "c2",
    policyTitle: "示例市小微企业融资贴息实施办法（演示）",
    docNumber: "示政办规〔2025〕3号（演示）",
    issuer: "示例市财政局（演示机关）",
    issuedOn: "2025-03-10",
    effectiveOn: "2025-04-01",
    expiresOn: "2028-03-31",
    status: "current",
    clause: "第八条",
    excerpt: "贴息资金按照贷款实际支付利息的50%给予补贴……",
    text: {
      before: "贴息资金按照贷款实际支付利息的50%给予补贴，单户企业年度补贴金额不超过20万元。",
      highlight: "申请人应当在贷款发放后六个月内提出申请",
      after: "，逾期不予受理。",
    },
    previousClause: "第七条 贴息资金由市级财政预算安排，实行年度总额控制。",
    nextClause: "第九条 申请人应当提交贷款合同、利息支付凭证等材料。",
  },
  {
    id: "c3",
    policyTitle: "示例市普惠金融服务若干措施（演示）",
    docNumber: "示金发〔2024〕11号（演示）",
    issuer: "示例市地方金融管理局（演示机关）",
    issuedOn: "2024-06-18",
    effectiveOn: "2024-07-01",
    expiresOn: "未录入",
    status: "unverified",
    statusNote: "政策库未录入该文件的失效日期，且其提及的配套细则尚未入库，结论未采用此条。",
    clause: "第三条",
    excerpt: "鼓励金融机构对首次贷款的小微企业给予利率优惠……",
    text: { before: "", highlight: "鼓励金融机构对首次贷款的小微企业给予利率优惠", after: "，具体办法由各金融机构另行制定。" },
    previousClause: "第二条 本措施适用于在本市开展普惠金融业务的金融机构。",
    nextClause: "第四条 建立普惠金融服务联络机制。",
  },
  {
    id: "c4",
    policyTitle: "示例市政务数据共享管理办法（演示）",
    docNumber: "示政规〔2025〕2号（演示）",
    issuer: "示例市政务服务管理局（演示机关）",
    issuedOn: "2025-01-20",
    effectiveOn: "2025-03-01",
    expiresOn: "长期有效",
    status: "current",
    clause: "第十五条",
    excerpt: "共享申请提出后，数据提供部门应当在10个工作日内予以答复……",
    text: { before: "共享申请提出后，", highlight: "数据提供部门应当在10个工作日内予以答复", after: "；不予共享的，应当说明理由并提供相关依据。" },
    previousClause: "第十四条 共享申请应当明确数据用途、使用范围和安全保障措施。",
    nextClause: "第十六条 数据使用部门应当按照申请用途使用共享数据。",
  },
  {
    id: "c5",
    policyTitle: "示例市数据共享管理规定（演示，2021年版）",
    docNumber: "示政发〔2021〕8号（演示）",
    issuer: "示例市政务服务管理局（演示机关）",
    issuedOn: "2021-05-12",
    effectiveOn: "2021-06-01",
    expiresOn: "2025-03-01（已废止）",
    status: "abolished",
    statusNote: "已于 2025-03-01 废止，由《示例市政务数据共享管理办法（演示）》替代。仅作历史对照，不作为现行依据。",
    clause: "第十二条",
    excerpt: "数据提供部门应当在15个工作日内予以答复……",
    text: { before: "收到共享申请后，", highlight: "数据提供部门应当在15个工作日内予以答复", after: "。" },
    previousClause: "第十一条 共享申请通过共享平台提交。",
    nextClause: "第十三条 共享数据应当注明来源。",
  },
];

export const DEMO_QA_SESSIONS: QaSession[] = [
  {
    id: "s1",
    origin: "demo",
    title: "小微企业首次贷款贴息条件",
    updatedAt: "今天 10:32",
    badge: { label: "引用 3 条", tone: "info" },
    turns: [
      {
        id: "s1-t1",
        question: "小微企业申请首次贷款贴息需要满足哪些条件？",
        askedAt: "10:31",
        answer: {
          kind: "grounded",
          badges: [
            { label: "依据充分", tone: "success" },
            { label: "含 1 条待核实依据", tone: "warning" },
          ],
          citationIds: ["c1", "c2", "c3"],
          sections: [
            {
              heading: "结论",
              tone: "default",
              segments: [
                { kind: "text", text: "根据现行政策，小微企业申请首次贷款贴息需同时满足三项条件" },
                { kind: "cite", citationId: "c1", label: "[1] 第六条" },
                { kind: "text", text: "：在本市依法登记注册并正常经营满一年；近两年内无严重失信记录；贷款用于生产经营，且合同签订于办法施行之后。贴息按实际支付利息的 50% 给予补贴，单户年度上限 20 万元，须在贷款发放后六个月内提出申请" },
                { kind: "cite", citationId: "c2", label: "[2] 第八条" },
                { kind: "text", text: "。" },
              ],
            },
            {
              heading: "补充说明",
              tone: "muted",
              segments: [
                { kind: "text", text: "另有文件提及金融机构可对首次贷款的小微企业给予利率优惠" },
                { kind: "cite", citationId: "c3", label: "[3] 第三条" },
                { kind: "text", text: "，但该文件有效期未录入，状态待核实，未纳入上述结论。" },
              ],
            },
            {
              heading: "待人工确认",
              tone: "note",
              segments: [{ kind: "text", text: "“小微企业”的划型标准未收录于政策库，需经办人员按相关划型标准另行认定。" }],
            },
          ],
          meta: "引用 3 条 · 检索候选 12 条 · 已排除已废止政策（演示）",
        },
      },
    ],
  },
  {
    id: "s2",
    origin: "demo",
    title: "外地户籍人员人才公寓补贴",
    updatedAt: "今天 09:47",
    badge: { label: "无可靠依据", tone: "warning" },
    turns: [
      {
        id: "s2-t1",
        question: "外地户籍人员能否申请本市人才公寓补贴？",
        askedAt: "09:46",
        answer: {
          kind: "no_basis",
          badges: [{ label: "未找到足够依据", tone: "warning" }],
          citationIds: [],
          sections: [
            {
              heading: "未找到足够依据，请补充材料或人工核实",
              tone: "default",
              segments: [{ kind: "text", text: "已检索政策库 128 件政策（演示），相关度最高的 2 条内容均未对外地户籍人员申请人才公寓补贴作出规定。为避免误导，系统不生成结论。" }],
            },
          ],
          lowRelevance: [
            { title: "《示例市人才安居服务办法（演示）》第四条 · 人才认定层级", score: 0.41 },
            { title: "《示例市公共租赁住房管理规定（演示）》第九条 · 申请材料", score: 0.37 },
          ],
          threshold: 0.6,
          meta: "检索候选 2 条 · 均未达可信阈值（演示）",
        },
      },
    ],
  },
  {
    id: "s3",
    origin: "demo",
    title: "政务数据共享申请答复时限",
    updatedAt: "昨天 15:10",
    badge: { label: "含已废止条款", tone: "danger" },
    turns: [
      {
        id: "s3-t1",
        question: "政务数据共享申请提出后，提供部门应在多长时间内答复？",
        askedAt: "15:09",
        answer: {
          kind: "grounded",
          badges: [
            { label: "依据充分", tone: "success" },
            { label: "检索到已废止条款", tone: "danger" },
          ],
          citationIds: ["c4", "c5"],
          sections: [
            {
              heading: "结论",
              tone: "default",
              segments: [
                { kind: "text", text: "现行规定为：共享申请提出后，数据提供部门应当在 10 个工作日内予以答复；不予共享的，应当说明理由" },
                { kind: "cite", citationId: "c4", label: "[1] 第十五条" },
                { kind: "text", text: "。" },
              ],
            },
            {
              heading: "注意",
              tone: "danger",
              segments: [
                { kind: "text", text: "检索结果中的旧版规定（15 个工作日）已废止" },
                { kind: "cite", citationId: "c5", label: "[2] 第十二条" },
                { kind: "text", text: "，仅作为历史对照，不作为现行依据。" },
              ],
            },
          ],
          meta: "引用 2 条 · 其中已废止 1 条（演示）",
        },
      },
    ],
  },
];

export const DEMO_MATERIAL_LIBRARY: Material[] = [
  { id: "m1", name: "2024年度政务数据安全自查总结（演示）.docx", meta: "DOCX · 已解析" },
  { id: "m2", name: "数据安全检查要点（演示）.pdf", meta: "PDF · 已解析" },
  { id: "m3", name: "第三季度数据共享运行情况（演示）.xlsx", meta: "XLSX · 已解析" },
  { id: "m4", name: "安全事件处置台账模板（演示）.docx", meta: "DOCX · 已解析" },
  { id: "m5", name: "数据安全专题会会议纪要（演示）.docx", meta: "DOCX · 已解析" },
];

const emptyFields = { recipient: "", issuer: "", undertaker: "" };

const noticeDoc: OfficialDocument = {
  id: "demo-d1",
  origin: "demo",
  title: "关于开展2025年度政务数据安全自查工作的通知",
  docType: "notice",
  status: "draft",
  docNumber: { id: "seg-docno", text: "示数办[2025]7号" },
  fields: { ...emptyFields },
  signDate: "2025年10月25日",
  author: "演示用户A",
  department: "综合处",
  createdAt: "2025-10-25 09:30",
  version: 1,
  lastReviewedAt: "2025-10-25 10:41",
  materials: [
    { id: "m1", name: "2024年度政务数据安全自查总结（演示）.docx", meta: "DOCX · 已解析 · 被引用 2 处" },
    { id: "m2", name: "数据安全检查要点（演示）.pdf", meta: "PDF · 已解析 · 被引用 1 处" },
  ],
  policyRefs: [
    { id: "p-security-9", title: "示例市政务数据安全管理办法（演示）", clause: "第九条", status: "current" },
    { id: "p-share-old-12", title: "示例市数据共享管理规定（演示）", clause: "第十二条", status: "abolished" },
  ],
  blocks: [
    { id: "blk-recipient", kind: "recipient", section: "head", segments: [{ kind: "field", id: "seg-recipient", field: "recipient" }] },
    {
      id: "blk-intro",
      kind: "paragraph",
      section: "intro",
      segments: [
        { kind: "text", text: "为贯彻落实《示例市政务数据安全管理办法（演示）》第九条有关要求，" },
        { kind: "text", id: "seg-intro-phrase", text: "切实提升" },
        { kind: "text", text: "，现就开展2025年度政务数据安全自查工作通知如下。" },
      ],
    },
    { id: "blk-s1", kind: "heading1", section: "s1", segments: [{ kind: "text", text: "一、自查范围" }] },
    { id: "blk-s1-p", kind: "paragraph", section: "s1", segments: [{ kind: "text", text: "全市各级政务部门承担政务数据采集、存储、共享职能的信息系统及相关管理制度。" }] },
    { id: "blk-s2", kind: "heading1", section: "s2", segments: [{ kind: "text", text: "二、自查内容" }] },
    { id: "blk-s2-1", kind: "heading2", section: "s2", segments: [{ kind: "text", text: "（一）数据分类分级制度落实情况。" }] },
    { id: "blk-s2-2", kind: "heading2", section: "s2", segments: [{ kind: "text", text: "（二）数据共享交换审批记录。" }] },
    { id: "blk-s2-3", kind: "heading2", section: "s2", segments: [{ kind: "text", text: "（三）安全事件处置台账。" }] },
    { id: "blk-s3", kind: "heading1", section: "s3", segments: [{ kind: "text", text: "三、时间安排" }] },
    {
      id: "blk-time",
      kind: "paragraph",
      section: "s3",
      segments: [
        { kind: "text", text: "自查工作于2025年11月1日至11月20日开展。各单位应于2025年" },
        { kind: "text", id: "seg-date", text: "11月15日" },
        { kind: "text", text: "前报送自查报告。" },
      ],
    },
    { id: "blk-s4", kind: "heading1", section: "s4", segments: [{ kind: "text", text: "四、工作要求" }] },
    {
      id: "blk-cite",
      kind: "paragraph",
      section: "s4",
      segments: [
        { kind: "text", text: "（一）数据共享审批时限按照" },
        { kind: "text", id: "seg-cite", text: "《示例市数据共享管理规定（演示）》第十二条" },
        { kind: "text", text: "执行。" },
      ],
    },
    {
      id: "blk-penalty",
      kind: "paragraph",
      section: "s4",
      segments: [
        { kind: "text", text: "（二）各单位应当如实报送自查结果" },
        { kind: "text", id: "seg-penalty", text: "，对自查不合格的单位予以通报并扣减年度绩效分" },
        { kind: "text", text: "。" },
      ],
    },
    {
      id: "blk-undertaker",
      kind: "paragraph",
      section: "s4",
      segments: [
        { kind: "text", text: "（三）自查报告报送至" },
        { kind: "field", id: "seg-undertaker", field: "undertaker" },
        { kind: "text", text: "，联系人及电话另行通知。" },
      ],
    },
    {
      id: "blk-attach",
      kind: "attachment",
      section: "attach",
      segments: [
        { kind: "text", text: "政务数据安全自查表" },
        { kind: "text", id: "seg-attach-note", text: "（未关联文件）" },
      ],
    },
    { id: "blk-sign", kind: "signature", section: "sign", segments: [{ kind: "field", id: "seg-issuer", field: "issuer" }] },
  ],
  issues: [
    {
      id: "d1-i1", severity: "critical", source: "rule", title: "发文字号格式错误", section: "head",
      description: "“示数办[2025]7号”使用了方括号，年份应使用六角括号“〔〕”。", locationLabel: "发文字号", anchor: "seg-docno",
      suggestion: { text: "修改为“示数办〔2025〕7号”", segmentId: "seg-docno", replacement: "示数办〔2025〕7号" },
    },
    {
      id: "d1-i2", severity: "critical", source: "rule", title: "引用政策已废止", section: "s4",
      description: "《示例市数据共享管理规定（演示）》第十二条已于 2025-03-01 废止，被《示例市政务数据共享管理办法（演示）》第十五条替代。",
      locationLabel: "四、工作要求", anchor: "seg-cite",
      suggestion: {
        text: "替换为现行依据第十五条", segmentId: "seg-cite", replacement: "《示例市政务数据共享管理办法（演示）》第十五条",
        replacePolicyRef: { fromId: "p-share-old-12", to: { id: "p-share-15", title: "示例市政务数据共享管理办法（演示）", clause: "第十五条", status: "current" } },
      },
    },
    {
      id: "d1-i3", severity: "critical", source: "rule", title: "缺少主送机关", section: "head",
      description: "通知须写明主送机关，当前为待补充字段。", locationLabel: "主送机关", anchor: "seg-recipient", requiredField: "recipient",
    },
    {
      id: "d1-i4", severity: "critical", source: "rule", title: "缺少发文机关署名", section: "sign",
      description: "正文之后须有发文机关署名，当前为待补充字段。", locationLabel: "落款", anchor: "seg-issuer", requiredField: "issuer",
    },
    {
      id: "d1-i5", severity: "critical", source: "ai", title: "处罚性表述缺少政策依据", section: "s4",
      description: "“扣减年度绩效分”在已选政策依据中未找到对应规定，可能超出发文权限。此判断由 AI 给出，须人工复核。",
      locationLabel: "四、工作要求", anchor: "seg-penalty",
      suggestion: { text: "删除该表述，或补充对应政策依据后保留", segmentId: "seg-penalty", replacement: "" },
    },
    {
      id: "d1-i6", severity: "warning", source: "rule", title: "日期前后不一致", section: "s3",
      description: "报送截止日期（11月15日）早于自查结束日期（11月20日）。", locationLabel: "三、时间安排", anchor: "seg-date",
      suggestion: { text: "将报送截止日期调整为“11月25日”", segmentId: "seg-date", replacement: "11月25日" },
    },
    {
      id: "d1-i7", severity: "warning", source: "rule", title: "缺少承办部门", section: "s4",
      description: "自查报告的接收部门未明确。", locationLabel: "四、工作要求", anchor: "seg-undertaker", requiredField: "undertaker",
    },
    {
      id: "d1-i8", severity: "hint", source: "ai", title: "语句成分残缺", section: "intro",
      description: "“切实提升”后缺少宾语，语义不完整。", locationLabel: "开头段", anchor: "seg-intro-phrase",
      suggestion: { text: "改为“切实提升全市政务数据安全防护水平”", segmentId: "seg-intro-phrase", replacement: "切实提升全市政务数据安全防护水平" },
    },
    {
      id: "d1-i9", severity: "hint", source: "rule", title: "附件未关联文件", section: "attach",
      description: "正文列有附件“政务数据安全自查表”，但未关联实际文件。", locationLabel: "附件", anchor: "seg-attach-note",
    },
  ],
  resolutions: {},
  history: [
    { id: "d1-h1", action: "创建文稿", actor: "演示用户A", at: "2025-10-25 09:30", tone: "neutral" },
    { id: "d1-h2", action: "审校完成", actor: "系统（演示）", at: "2025-10-25 10:41", note: "规则检查 6 项 · AI 语义审查 2 项 · 待补充字段 3 处", tone: "warning" },
  ],
};

function simpleDoc(partial: Pick<OfficialDocument, "id" | "title" | "docType" | "status" | "author" | "department" | "createdAt" | "issues" | "history"> & { paragraphs: { id: string; text: string }[]; version?: number }): OfficialDocument {
  return {
    origin: "demo",
    docNumber: { id: "seg-docno", text: "" },
    fields: { ...emptyFields },
    signDate: "",
    version: partial.version ?? 1,
    lastReviewedAt: partial.createdAt,
    materials: [],
    policyRefs: [],
    resolutions: {},
    ...partial,
    blocks: partial.paragraphs.map((p) => ({ id: p.id, kind: "paragraph" as const, section: p.id, segments: [{ kind: "text" as const, text: p.text }] })),
  };
}

export const DEMO_DOCUMENTS: OfficialDocument[] = [
  noticeDoc,
  simpleDoc({
    id: "demo-d2", title: "2025年第三季度政务服务工作情况报告", docType: "report", status: "pending",
    author: "演示用户B", department: "政务服务处", createdAt: "2025-10-24 16:20", version: 2,
    paragraphs: [
      { id: "p1", text: "一、总体情况　第三季度共受理政务服务事项12.6万件（演示数据），按时办结率达100%，群众满意度持续提升。" },
      { id: "p2", text: "二、主要做法　推行“一件事一次办”，新增集成服务事项18项；线上办理量占比由61%提升至68%。" },
      { id: "p3", text: "三、存在问题　部分事项材料要求仍不统一，跨部门数据共享响应偏慢。" },
    ],
    issues: [
      { id: "d2-i1", severity: "warning", source: "rule", title: "数据前后不一致", description: "正文“按时办结率达100%”与附表“98.7%”不一致。", locationLabel: "一、总体情况", anchor: "p1", section: "p1" },
      { id: "d2-i2", severity: "hint", source: "rule", title: "计量单位不统一", description: "“12.6万件”与附表“126,000件”写法不一致。", locationLabel: "一、总体情况", anchor: "p1", section: "p1" },
      { id: "d2-i3", severity: "hint", source: "ai", title: "结构缺项", description: "缺少“下一步工作安排”部分。", locationLabel: "三、存在问题", anchor: "p3", section: "p3" },
    ],
    history: [
      { id: "d2-h1", action: "创建文稿", actor: "演示用户B", at: "2025-10-24 15:02", tone: "neutral" },
      { id: "d2-h2", action: "审校完成", actor: "系统（演示）", at: "2025-10-24 16:05", note: "发现 3 项问题，无严重问题", tone: "warning" },
      { id: "d2-h3", action: "提交审核", actor: "演示用户B", at: "2025-10-24 16:20", tone: "info" },
    ],
  }),
  simpleDoc({
    id: "demo-d3", title: "关于申请调整数据共享平台运维经费的请示", docType: "request", status: "returned",
    author: "演示用户C", department: "数据资源处", createdAt: "2025-10-23 11:05",
    paragraphs: [
      { id: "p1", text: "示例市财政局（演示机关）：" },
      { id: "p2", text: "为保障平台稳定运行，拟申请将2026年度运维经费由80万元调整为120万元；同时申请增加运维人员编制2名。" },
      { id: "p3", text: "妥否，请批示。" },
    ],
    issues: [
      { id: "d3-i1", severity: "critical", source: "rule", title: "请示应当一文一事", description: "正文同时请示经费调整与人员增编两项事项。", locationLabel: "正文", anchor: "p2", section: "p2" },
      { id: "d3-i2", severity: "warning", source: "rule", title: "缺少联系人及联系方式", description: "请示应在附注处注明联系人及电话。", locationLabel: "结尾", anchor: "p3", section: "p3" },
    ],
    history: [
      { id: "d3-h1", action: "创建文稿", actor: "演示用户C", at: "2025-10-23 09:10", tone: "neutral" },
      { id: "d3-h2", action: "提交审核", actor: "演示用户C", at: "2025-10-23 11:05", tone: "info" },
      { id: "d3-h3", action: "退回修改", actor: "演示审核人", at: "2025-10-23 15:40", note: "请示应一文一事，人员编制事项请另行请示。", tone: "danger" },
    ],
  }),
  simpleDoc({
    id: "demo-d4", title: "第12次主任办公会议纪要", docType: "minutes", status: "approved",
    author: "演示用户A", department: "综合处", createdAt: "2025-10-22 17:30",
    paragraphs: [
      { id: "p1", text: "时间：2025年10月21日　地点：第一会议室（演示）" },
      { id: "p2", text: "会议听取了数据共享平台运行情况汇报，议定以下事项：一、年底前完成平台安全加固；二、各处室于11月10日前提交年度数据共享需求。" },
    ],
    issues: [],
    history: [
      { id: "d4-h1", action: "创建文稿", actor: "演示用户A", at: "2025-10-22 16:00", tone: "neutral" },
      { id: "d4-h2", action: "提交审核", actor: "演示用户A", at: "2025-10-22 17:30", tone: "info" },
      { id: "d4-h3", action: "审核通过", actor: "演示审核人", at: "2025-10-23 09:12", note: "同意印发。", tone: "success" },
    ],
  }),
  simpleDoc({
    id: "demo-d5", title: "《示例市小微企业融资贴息实施办法（演示）》政策解读", docType: "interpretation", status: "pending",
    author: "演示用户D", department: "政策研究室", createdAt: "2025-10-22 09:15",
    paragraphs: [
      { id: "p1", text: "一、适用对象　在本市依法登记注册并正常经营满一年、近两年内无严重失信记录的小微企业。" },
      { id: "p2", text: "二、补贴标准　按贷款实际支付利息的50%给予补贴，单户年度不超过20万元。" },
      { id: "p3", text: "三、申请时限　应在贷款发放后六个月内提出申请。" },
    ],
    issues: [
      { id: "d5-i1", severity: "hint", source: "ai", title: "建议补充不予受理情形", description: "原文第八条规定逾期不予受理，解读稿未提示。", locationLabel: "三、申请时限", anchor: "p3", section: "p3" },
    ],
    history: [
      { id: "d5-h1", action: "创建文稿", actor: "演示用户D", at: "2025-10-22 08:40", tone: "neutral" },
      { id: "d5-h2", action: "提交审核", actor: "演示用户D", at: "2025-10-22 09:15", tone: "info" },
    ],
  }),
  simpleDoc({
    id: "demo-d6", title: "关于商请提供2025年度数据共享需求清单的函", docType: "letter", status: "pending",
    author: "演示用户B", department: "政务服务处", createdAt: "2025-10-21 14:40",
    paragraphs: [
      { id: "p1", text: "示例市各区政务服务管理部门（演示）：" },
      { id: "p2", text: "为做好年度数据共享规划，请各单位梳理2025年度数据共享需求，形成清单报送我办。" },
      { id: "p3", text: "此致　敬礼" },
    ],
    issues: [
      { id: "d6-i1", severity: "warning", source: "rule", title: "函的结束语不规范", description: "函一般以“特此函商”“请予函复”结尾。", locationLabel: "结尾", anchor: "p3", section: "p3" },
      { id: "d6-i2", severity: "warning", source: "rule", title: "缺少回复期限", description: "未明确清单报送截止时间。", locationLabel: "正文", anchor: "p2", section: "p2" },
    ],
    history: [
      { id: "d6-h1", action: "创建文稿", actor: "演示用户B", at: "2025-10-21 14:00", tone: "neutral" },
      { id: "d6-h2", action: "提交审核", actor: "演示用户B", at: "2025-10-21 14:40", tone: "info" },
    ],
  }),
  simpleDoc({
    id: "demo-d7", title: "数字政务建设专题工作总结（初稿）", docType: "report", status: "pending",
    author: "演示用户C", department: "数据资源处", createdAt: "2025-10-20 10:20",
    paragraphs: [
      { id: "p1", text: "一、主要成效　全年节约行政成本约3000万元，办事效率提升80%。" },
      { id: "p2", text: "1. 平台建设　一、完成统一身份认证改造。" },
      { id: "p3", text: "依据《示例市普惠金融服务若干措施（演示）》开展数据赋能工作。" },
    ],
    issues: [
      { id: "d7-i1", severity: "critical", source: "ai", title: "成效数据缺少来源", description: "“节约约3000万元”“效率提升80%”未关联任何材料。此判断由 AI 给出，须人工复核。", locationLabel: "一、主要成效", anchor: "p1", section: "p1" },
      { id: "d7-i2", severity: "critical", source: "rule", title: "引用政策状态待核实", description: "所引文件未录入有效期，不能作为正式依据。", locationLabel: "正文", anchor: "p3", section: "p3" },
      { id: "d7-i3", severity: "warning", source: "rule", title: "层次序数使用错误", description: "“1.”之后出现“一、”，层级颠倒。", locationLabel: "正文", anchor: "p2", section: "p2" },
    ],
    history: [
      { id: "d7-h1", action: "创建文稿", actor: "演示用户C", at: "2025-10-20 09:00", tone: "neutral" },
      { id: "d7-h2", action: "审校完成", actor: "系统（演示）", at: "2025-10-20 10:00", note: "发现 3 项问题，其中严重 2 项", tone: "warning" },
      { id: "d7-h3", action: "提交审核", actor: "演示用户C", at: "2025-10-20 10:20", tone: "info" },
    ],
  }),
];
