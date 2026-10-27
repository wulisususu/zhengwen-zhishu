// Domain types for the government-office workbench.
// Every payload carries `origin` so demo fixtures can never be presented as
// backend results: the UI shows a demo marker whenever origin === "demo".

export type DataOrigin = "demo" | "backend";
export type Tone = "neutral" | "info" | "success" | "warning" | "danger";

/* ---------- runtime / actor ---------- */

export type ModelMode = "cloud_allowed" | "intranet" | "offline" | "unknown";

export interface RuntimeStatus {
  origin: DataOrigin;
  modelMode: ModelMode;
  label: string;
  detail: string;
}

export type ActorRole = "drafter" | "reviewer";

export interface Actor {
  origin: DataOrigin;
  /** Login account, e.g. "demo_drafter". Used for the self-review check. */
  account: string;
  name: string;
  department: string;
  roles: ActorRole[];
  /** Permission to issue / formally export official documents. */
  canFormalIssue: boolean;
}

/* ---------- policy QA ---------- */

export type PolicyStatus = "current" | "abolished" | "unverified";

export interface Citation {
  pageNumber?: number;
  sourceAnchor?: string;
  id: string;
  policyTitle: string;
  docNumber: string;
  issuer: string;
  issuedOn: string;
  effectiveOn: string;
  expiresOn: string;
  status: PolicyStatus;
  statusNote?: string;
  clause: string;
  excerpt: string;
  text: { before: string; highlight: string; after: string };
  previousClause?: string;
  nextClause?: string;
  sourceUrl?: string;
  policyId?: number;
  version?: number;
}

export interface PolicyDocument {
  id: number; title: string; url: string; doc_number?: string; issuer?: string;
  publish_date?: string; verified_status: PolicyStatus; version: number;
  is_current: boolean; status_note?: string; superseded_by?: number;
}
export interface PolicyClause { id: number; article_number?: string; heading?: string; content: string; sequence: number; needs_review: boolean; page_number?: number; source_anchor?: string; }
export interface PolicyDetail { policy: PolicyDocument; clauses: PolicyClause[]; }
export interface PolicyHit { citation_id: string; policy_id: number; policy_title: string; clause: string; status: PolicyStatus; excerpt: { before: string; highlight: string; after: string }; }

export type AnswerSegment =
  | { kind: "text"; text: string }
  | { kind: "cite"; citationId: string; label: string };

export interface AnswerSection {
  heading: string;
  tone: "default" | "muted" | "note" | "danger";
  segments: AnswerSegment[];
}

export interface QaAnswer {
  kind: "grounded" | "no_basis" | "unavailable";
  badges: { label: string; tone: Tone }[];
  sections: AnswerSection[];
  citationIds: string[];
  lowRelevance?: { title: string; score: number }[];
  threshold?: number;
  meta: string;
}

export interface QaTurn {
  id: string;
  question: string;
  askedAt: string;
  answer: QaAnswer;
}

export interface QaSession {
  id: string;
  origin: DataOrigin;
  title: string;
  updatedAt: string;
  badge: { label: string; tone: Tone };
  turns: QaTurn[];
}

export interface PolicyStats {
  available?: boolean;
  origin: DataOrigin;
  total: number;
  current: number;
  abolished: number;
  unverified: number;
}

export interface AskOptions {
  scope: "current" | "all" | "picked";
  excludeAbolished: boolean;
}

/* ---------- official documents ---------- */

export type DocStatus = "draft" | "pending" | "returned" | "approved";
export type DocTypeId = "notice" | "request" | "report" | "letter" | "minutes" | "interpretation";
export type FieldKey = "recipient" | "issuer" | "undertaker";

export type DocSegment =
  | { kind: "text"; id?: string; text: string }
  | { kind: "field"; id: string; field: FieldKey };

export type BlockKind = "recipient" | "paragraph" | "heading1" | "heading2" | "heading3" | "heading4" | "attachment" | "signature" | "table";

export interface NoticeTable { caption: string; head: string[]; rows: string[][]; }
export interface NoticeMetadata { docNumber: string; printer: string; printDate: string; copyTo: string; note: string; titleLines: string; tables: NoticeTable[]; }
export interface NoticeReview {
  formatCheck: { status: "pass" | "hit" | "unavailable"; message?: string; errorCode?: string; toolVersion?: string };
  gate: { canApprove: boolean; canExportFormal?: boolean; reasons: string[] };
  issueDetails?: Record<string, { layer?: string; anchorPrecision?: string; candidates?: string[] }>;
  policyVerification?: { message: string };
}

export interface DocBlock {
  id: string;
  kind: BlockKind;
  section: string;
  segments: DocSegment[];
  table?: NoticeTable;
}

export interface Material {
  id: string;
  name: string;
  meta: string;
  downloadUrl?: string;
}

export interface PolicyRef {
  pageNumber?: number;
  sourceAnchor?: string;
  id: string;
  title: string;
  clause: string;
  status: PolicyStatus;
  sourceUrl?: string;
  policyId?: number;
  version?: number;
  statusNote?: string;
  excerpt?: string;
  unresolved?: boolean;
}

export type IssueSeverity = "critical" | "warning" | "hint";
export type IssueSource = "rule" | "ai";

export interface IssueSuggestion {
  text: string;
  segmentId: string;
  replacement: string;
  replacePolicyRef?: { fromId: string; to: PolicyRef };
}

export interface ReviewIssue {
  id: string;
  severity: IssueSeverity;
  source: IssueSource;
  title: string;
  description: string;
  locationLabel: string;
  /** Segment id or block id used for highlight and scroll. */
  anchor: string;
  section: string;
  suggestion?: IssueSuggestion;
  requiredField?: FieldKey;
}

export type IssueResolution =
  | { kind: "fixed"; by: string; at: string }
  | { kind: "ai_confirmed"; by: string; at: string }
  | { kind: "ai_dismissed"; by: string; reason: string; at: string }
  | { kind: "hint_ignored"; by: string; at: string }
  | { kind: "exception_requested"; by: string; reason: string; at: string }
  | { kind: "exception_approved"; by: string; reason: string; at: string };

export interface ReviewRecord {
  id: string;
  action: string;
  actor: string;
  at: string;
  note?: string;
  tone: Tone;
}

export interface OfficialDocument {
  banji?: { copyTo: string[]; printer: string; printDate: string } | null;
  note?: string;
  titleLines?: string[] | null;
  tables?: NoticeTable[];
  review?: NoticeReview | null;
  body?: string;
  checkStatus?: "not_run" | "completed";
  id: string;
  origin: DataOrigin;
  title: string;
  docType: DocTypeId;
  status: DocStatus;
  docNumber: { id: string; text: string };
  fields: Record<FieldKey, string>;
  blocks: DocBlock[];
  signDate: string;
  author: string;
  /** Account that drafted and submits the document; it may not review it. */
  authorAccount: string;
  department: string;
  createdAt: string;
  version: number;
  materials: Material[];
  policyRefs: PolicyRef[];
  issues: ReviewIssue[];
  resolutions: Record<string, IssueResolution>;
  history: ReviewRecord[];
  lastReviewedAt: string;
}

export interface DocumentFilter {
  keyword: string;
  docType: DocTypeId | "all";
  status: DocStatus | "all";
  criticalOnly: boolean;
}

export interface ExportResult {
  generated: boolean;
  kind: "internal_draft" | "formal";
  watermark?: string;
  message: string;
  filename?: string;
}

export interface DraftChanges {
  docNumber?: { text: string };
  banji?: { copyTo: string[]; printer: string; printDate: string };
  note?: string;
  titleLines?: string[];
  tables?: NoticeTable[];
  title?: string;
  docType?: DocTypeId;
  body?: string;
  fields?: Record<FieldKey, string>;
  signDate?: string;
}

/** 提炼总结 */
export type SummaryMode = "material" | "meeting";

/** One numbered passage of the original material that a summary item cites. */
export interface SummarySource {
  id: string;
  fileId: string;
  fileName: string;
  page: number | null;
  paragraph: number;
  text: string;
}

export interface SummaryItem {
  text: string;
  sources: string[];
  /** Meeting tasks only; empty when the material does not state it. */
  owner?: string;
  deadline?: string;
  notes: string[];
}

export interface SummaryResult {
  origin: "backend" | "demo";
  mode: SummaryMode;
  materials: { fileId: string; fileName: string; segments: number }[];
  sections: { key: string; label: string; items: SummaryItem[] }[];
  sources: Record<string, SummarySource>;
  /** Items the model returned that failed source checks; shown, never silently discarded. */
  dropped: { section: string; text: string; reason: string }[];
  generatedAt: string;
}
