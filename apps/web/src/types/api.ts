export type RoleCode =
  | "super_admin"
  | "org_admin"
  | "ops_manager"
  | "investigator"
  | "approver"
  | "viewer";

export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type Priority = "LOW" | "MEDIUM" | "HIGH" | "URGENT";
export type RiskLevel = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_active: boolean;
  is_superadmin: boolean;
  job_title?: string | null;
  locale?: string;
  avatar_color?: string | null;
  last_login_at?: string | null;
}

export interface Organization {
  id: string;
  name: string;
  slug: string;
  legal_name?: string | null;
  tax_id?: string | null;
  default_currency: string;
  timezone: string;
  settings: Record<string, any>;
  branding: Record<string, any>;
  is_demo: boolean;
  created_at?: string | null;
}

export interface OrganizationChoice {
  id: string;
  name: string;
  slug: string;
  role: RoleCode;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  refresh_expires_in: number;
  user: User;
  organization: Organization;
  role: RoleCode;
  permissions: string[];
  organizations: OrganizationChoice[];
}

export interface MeResponse {
  user: User;
  organization: Organization;
  role: RoleCode;
  permissions: string[];
  organizations: OrganizationChoice[];
  is_superadmin: boolean;
  demo_mode: boolean;
}

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
  pages: number;
  has_next: boolean;
}

export interface Page<T> {
  items: T[];
  meta: PageMeta;
}

export interface UserRef {
  id: string;
  full_name: string;
  email: string;
  avatar_color?: string | null;
}

export type CaseStatus =
  | "OPEN"
  | "INVESTIGATING"
  | "AWAITING_INFORMATION"
  | "AWAITING_APPROVAL"
  | "RESOLUTION_IN_PROGRESS"
  | "RESOLVED"
  | "REOPENED"
  | "CLOSED"
  | "CANCELLED";

export interface CaseSummary {
  id: string;
  case_number: string;
  title: string;
  status: CaseStatus;
  priority: Priority;
  severity: Severity;
  assigned_user?: UserRef | null;
  due_at?: string | null;
  sla_hours: number;
  sla_breached: boolean;
  tags: string[];
  exception_count: number;
  is_demo: boolean;
  created_at: string;
  last_activity_at: string;
}

export interface CaseLink {
  id: string;
  entity_type: string;
  entity_id: string;
  label?: string | null;
  created_at: string;
}

export interface CaseException {
  id: string;
  exception_type: string;
  severity: Severity;
  status: string;
  title: string;
  rule_code: string;
  rule_version: number;
  detection_count: number;
  first_detected_at: string;
  last_detected_at: string;
}

export interface CaseComment {
  id: string;
  author_id?: string | null;
  author_name?: string | null;
  body: string;
  visibility: "INTERNAL" | "EXTERNAL";
  created_at: string;
  edited_at?: string | null;
}

export interface CaseActivity {
  id: string;
  actor_id?: string | null;
  actor_name?: string | null;
  activity_type: string;
  summary: string;
  payload: Record<string, any>;
  created_at: string;
}

export interface CaseDetail extends CaseSummary {
  description: string;
  resolution_summary?: string | null;
  resolved_at?: string | null;
  closed_at?: string | null;
  first_response_at?: string | null;
  created_by?: UserRef | null;
  merged_into_case_id?: string | null;
  links: CaseLink[];
  exceptions: CaseException[];
  comments: CaseComment[];
  activities: CaseActivity[];
}

export interface ExceptionRecord {
  id: string;
  exception_type: string;
  severity: Severity;
  status: string;
  title: string;
  description: string;
  rule_code: string;
  rule_version: number;
  entity_type: string;
  entity_id: string;
  case_id?: string | null;
  case_number?: string | null;
  case_status?: CaseStatus | null;
  detection_count: number;
  first_detected_at: string;
  last_detected_at: string;
  evidence: Record<string, any>;
  is_demo: boolean;
  rule_name?: string | null;
  related?: Record<string, any>;
}

export interface ExceptionRule {
  id: string;
  code: string;
  name: string;
  description: string;
  exception_type: string;
  severity: Severity;
  applies_to: string[];
  is_enabled: boolean;
  is_system: boolean;
  active_version?: number | null;
  config: Record<string, any>;
  conditions: Record<string, any>;
  test_cases: Record<string, any>[];
  updated_at?: string | null;
  versions?: {
    id: string;
    version: number;
    config: Record<string, any>;
    conditions: Record<string, any>;
    thresholds: Record<string, any>;
    test_cases: Record<string, any>[];
    is_active: boolean;
    change_note?: string | null;
    created_at: string;
  }[];
}

export type DocumentStatus =
  | "UPLOADED"
  | "QUEUED"
  | "PROCESSING"
  | "EXTRACTED"
  | "VALIDATING"
  | "INDEXED"
  | "FAILED"
  | "REQUIRES_REVIEW";

export interface DocumentRecord {
  id: string;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  sha256: string;
  document_type: string;
  status: DocumentStatus;
  page_count: number;
  char_count: number;
  ocr_confidence?: number | null;
  requires_review: boolean;
  current_version: number;
  vendor_id?: string | null;
  processing_error?: string | null;
  is_demo: boolean;
  created_at: string;
  processed_at?: string | null;
  indexed_at?: string | null;
  has_extraction: boolean;
  chunk_count: number;
}

export interface ExtractedField {
  id: string;
  field_name: string;
  value?: string | null;
  effective_value?: string | null;
  normalized_value?: string | null;
  page_number?: number | null;
  source_text?: string | null;
  confidence: number;
  method: string;
  review_status: string;
  corrected_value?: string | null;
  bounding_box?: Record<string, any> | null;
  notes?: string | null;
}

export interface Extraction {
  id: string;
  document_id: string;
  document_version: number;
  status: string;
  provider: string;
  model?: string | null;
  prompt_version?: string | null;
  field_count: number;
  avg_confidence?: number | null;
  requires_review: boolean;
  review_status: string;
  review_note?: string | null;
  error?: string | null;
  created_at: string;
  fields: ExtractedField[];
}

export interface DocumentDetail extends DocumentRecord {
  metadata: Record<string, any>;
  pages: {
    page_number: number;
    text: string;
    char_count: number;
    has_text_layer: boolean;
    ocr_confidence?: number | null;
    extra: Record<string, any>;
  }[];
  versions: {
    id: string;
    version: number;
    sha256: string;
    size_bytes: number;
    note?: string | null;
    created_at: string;
  }[];
  extraction?: Extraction | null;
  capabilities: Record<string, any>;
}

export interface Vendor {
  id: string;
  vendor_number: string;
  legal_name: string;
  display_name?: string | null;
  normalized_name: string;
  tax_id?: string | null;
  address_line1?: string | null;
  address_line2?: string | null;
  city?: string | null;
  postal_code?: string | null;
  country?: string | null;
  contact_name?: string | null;
  email?: string | null;
  phone?: string | null;
  payment_terms_days: number;
  currency: string;
  status: string;
  risk_flags: string[];
  notes?: string | null;
  is_demo: boolean;
  created_at?: string | null;
  updated_at?: string | null;
  invoice_count: number;
  open_exception_count: number;
}

export interface VendorDetail extends Vendor {
  purchase_orders: Record<string, any>[];
  recent_invoices: Record<string, any>[];
  documents: { id: string; original_filename: string; document_type: string; status: string }[];
  exceptions: { id: string; exception_type: string; severity: string; status: string; title: string }[];
}

export interface Invoice {
  id: string;
  invoice_number: string;
  vendor?: { id: string; legal_name: string; vendor_number: string; tax_id?: string | null } | null;
  purchase_order_id?: string | null;
  purchase_order_number?: string | null;
  document_id?: string | null;
  invoice_date: string;
  due_date?: string | null;
  currency: string;
  subtotal: string;
  tax: string;
  total: string;
  status: string;
  validation_status: string;
  source: string;
  is_demo: boolean;
  vendor_name_raw?: string | null;
  created_at?: string | null;
  open_exception_count: number;
  case_id?: string | null;
}

export interface InvoiceDetail extends Invoice {
  payment_terms_days: number;
  notes?: string | null;
  validation_notes: { code: string; severity: string; message: string; details: Record<string, any> }[];
  items: {
    id: string;
    line_number: number;
    description: string;
    quantity: string;
    unit_price: string;
    tax_rate: string;
    line_total: string;
  }[];
  exceptions: { id: string; exception_type: string; severity: string; status: string; title: string; case_id?: string | null }[];
  purchase_order_candidates: {
    id: string;
    po_number: string;
    total: string;
    currency: string;
    percent_difference: string;
    within_tolerance: boolean;
  }[];
  approval?: Record<string, any> | null;
}

export interface PurchaseOrder {
  id: string;
  po_number: string;
  vendor_id: string;
  vendor_name?: string | null;
  currency: string;
  issue_date: string;
  expiration_date?: string | null;
  status: string;
  subtotal: string;
  tax: string;
  total: string;
  description?: string | null;
  is_demo: boolean;
  created_at?: string | null;
  invoiced_amount: string;
  invoice_count: number;
}

export interface PurchaseOrderDetail extends PurchaseOrder {
  notes?: string | null;
  items: {
    id: string;
    line_number: number;
    description: string;
    quantity: string;
    unit_price: string;
    tax_rate: string;
    line_total: string;
    received_quantity: string;
  }[];
  invoices: Record<string, any>[];
}

export interface Approval {
  id: string;
  case_id: string;
  case_number?: string | null;
  case_title?: string | null;
  resolution_id?: string | null;
  resolution_status?: string | null;
  action_type: string;
  title: string;
  description: string;
  requester?: UserRef | null;
  approver_role?: string | null;
  assigned_approver?: UserRef | null;
  risk_level: RiskLevel;
  status: string;
  evidence: Record<string, any>[];
  parameters: Record<string, any>;
  expires_at?: string | null;
  overdue: boolean;
  decided_at?: string | null;
  decided_by?: UserRef | null;
  decision_note?: string | null;
  created_at: string;
  can_decide: boolean;
  decisions?: { id: string; decision: string; decided_by_name?: string | null; comment?: string | null; created_at: string }[];
  resolution?: Record<string, any> | null;
}

export interface Resolution {
  id: string;
  case_id: string;
  case_number?: string | null;
  investigation_id?: string | null;
  action_type: string;
  description: string;
  parameters: Record<string, any>;
  supporting_evidence: Record<string, any>[];
  risk_level: RiskLevel;
  expected_outcome?: string | null;
  required_permissions: string[];
  requires_approval: boolean;
  status: string;
  created_by_id?: string | null;
  created_by_name?: string | null;
  ai_model?: string | null;
  prompt_version?: string | null;
  execution_result?: Record<string, any> | null;
  error?: string | null;
  executed_at?: string | null;
  created_at: string;
  approval?: Record<string, any> | null;
  executions: Record<string, any>[];
}

export interface Evidence {
  id: string;
  source_type: string;
  source_id?: string | null;
  document_id?: string | null;
  page_number?: number | null;
  field_name?: string | null;
  quote: string;
  relationship?: string | null;
  is_contradicting: boolean;
  is_validated: boolean;
  validation_error?: string | null;
}

export interface Investigation {
  id: string;
  case_id: string;
  status: string;
  provider: string;
  model?: string | null;
  prompt_version: string;
  summary?: string | null;
  root_cause?: string | null;
  root_cause_hypotheses: Record<string, any>[];
  risk_level?: RiskLevel | null;
  confidence?: number | null;
  confidence_basis?: string | null;
  requires_human_review: boolean;
  missing_information: string[];
  limitations: string[];
  required_actions: string[];
  suggested_resolutions: {
    action_type: string;
    description: string;
    rationale: string;
    risk_level: RiskLevel;
  }[];
  input_tokens: number;
  output_tokens: number;
  cost_usd?: number | null;
  latency_ms?: number | null;
  error?: string | null;
  error_code?: string | null;
  created_at: string;
  completed_at?: string | null;
  evidence_count: number;
  invalid_evidence_count: number;
  evidence: Evidence[];
}

export interface Integration {
  id: string;
  name: string;
  kind: string;
  status: string;
  is_enabled: boolean;
  config: Record<string, any>;
  event_filter: string[];
  credential_keys: string[];
  last_checked_at?: string | null;
  last_success_at?: string | null;
  last_error?: string | null;
  created_at?: string | null;
}

export interface WebhookEvent {
  id: string;
  integration_id?: string | null;
  direction: string;
  event_type: string;
  payload: Record<string, any>;
  signature_valid: boolean;
  status: string;
  response_status?: number | null;
  attempts: number;
  last_error?: string | null;
  idempotency_key: string;
  created_at: string;
  processed_at?: string | null;
}

export interface WorkflowExecution {
  id: string;
  integration_id?: string | null;
  workflow_key: string;
  trigger_type: string;
  case_id?: string | null;
  status: string;
  payload: Record<string, any>;
  result?: Record<string, any> | null;
  attempts: number;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
}

export interface BackgroundJob {
  id: string;
  task_name: string;
  status: string;
  payload: Record<string, any>;
  result?: Record<string, any> | null;
  error?: string | null;
  attempts: number;
  max_attempts: number;
  created_at: string;
  started_at?: string | null;
  finished_at?: string | null;
}

export interface Notification {
  id: string;
  type: string;
  title: string;
  body: string;
  entity_type?: string | null;
  entity_id?: string | null;
  channel: string;
  status: string;
  payload: Record<string, any>;
  read_at?: string | null;
  created_at: string;
}

export interface Kpi {
  key: string;
  label: string;
  value: number;
  previous?: number | null;
  delta_percent?: number | null;
  unit: string;
  detail?: string | null;
}

export interface AnalyticsOverview {
  range_days: number;
  generated_at: string;
  kpis: Kpi[];
  exception_trend: { bucket: string; value: number }[];
  case_trend: { bucket: string; value: number }[];
  resolution_trend: { bucket: string; value: number }[];
  exception_distribution: { key: string; label: string; count: number }[];
  priority_distribution: { key: string; label: string; count: number }[];
  resolution_distribution: { key: string; label: string; count: number }[];
  sla: { breached: number; due_within_24h: number; average_resolution_hours: number };
  workload: { user_id?: string | null; name: string; open_cases: number; overdue_cases: number }[];
  recent_activity: {
    id: string;
    case_id: string;
    case_number: string;
    case_title: string;
    activity_type: string;
    summary: string;
    actor_name?: string | null;
    created_at: string;
  }[];
  processing: {
    documents_by_status: { key: string; label: string; count: number }[];
    jobs_by_status: { key: string; label: string; count: number }[];
    failed_jobs: number;
    ai_runs: number;
    ai_tokens: number;
    ai_cost_usd: number;
    ai_average_latency_ms: number;
  };
  counts: Record<string, number>;
}

export interface EvaluationDataset {
  id: string;
  name: string;
  description: string;
  version: string;
  is_synthetic: boolean;
  sample_count: number;
  created_at: string;
  samples?: Record<string, any>[];
}

export interface EvaluationRun {
  id: string;
  dataset_id: string;
  dataset_name?: string | null;
  name: string;
  provider: string;
  model?: string | null;
  prompt_version: string;
  retrieval_config: Record<string, any>;
  status: string;
  metrics: Record<string, any>;
  sample_total: number;
  sample_completed: number;
  error?: string | null;
  started_at?: string | null;
  finished_at?: string | null;
  created_at: string;
  results?: {
    id: string;
    sample_key: string;
    predicted: Record<string, any>;
    expected: Record<string, any>;
    scores: Record<string, any>;
    latency_ms?: number | null;
    input_tokens: number;
    output_tokens: number;
    cost_usd?: number | null;
    error?: string | null;
  }[];
}

export interface AuditRecord {
  id: string;
  actor_user_id?: string | null;
  actor_email?: string | null;
  action: string;
  entity_type: string;
  entity_id?: string | null;
  summary: string;
  before?: Record<string, any> | null;
  after?: Record<string, any> | null;
  context: Record<string, any>;
  ip_address?: string | null;
  request_id?: string | null;
  created_at: string;
}

export interface Member {
  id: string;
  user_id: string;
  email: string;
  full_name: string;
  role_code: RoleCode;
  role_name: string;
  is_active: boolean;
  job_title?: string | null;
  last_active_at?: string | null;
  created_at?: string | null;
}

export interface SavedFilter {
  id: string;
  resource: string;
  name: string;
  query: Record<string, any>;
  is_shared: boolean;
  is_owner: boolean;
}

export interface SystemInfo {
  name: string;
  version: string;
  environment: string;
  demo_mode: boolean;
  features: Record<string, any>;
  ai: Record<string, any>;
}
