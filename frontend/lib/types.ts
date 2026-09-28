export type Page<T> = { items: T[]; next_cursor: number | null };
export type Source = "contracts-finder" | "find-a-tender" | "ted" | "world-bank";
export interface Tender {
  id: number;
  source: string;
  external_id: string | null;
  title: string;
  organization: string | null;
  category: string | null;
  location: string | null;
  published_at: string | null;
  deadline: string | null;
  first_seen_at: string;
  last_seen_at: string;
  latest_revision_index: number;
  document_count: number;
  latest_analysis_status: string | null;
}
export interface DiscoverSource {
  source: Source;
  status: "success" | "unavailable";
  fetched_at: string | null;
  error_code: "source_unavailable" | null;
}
export interface DiscoverResponse
  extends Page<Tender & { freshly_fetched: boolean }> {
  requested_at: string;
  mode: "live" | "recorded";
  sources: DiscoverSource[];
  result_count: number;
}
export interface Revision {
  revision_id: number;
  revision_index: number;
  observed_at: string;
  deadline: string | null;
  snapshot_hash: string;
}
export interface Version {
  id: number;
  content_hash: string;
  byte_size: number;
  media_type: string | null;
  downloaded_at: string;
  extraction_status: string;
  has_analysis: boolean;
  is_indexed: boolean;
}
export interface TenderDocument {
  id: number;
  title: string | null;
  media_type: string | null;
  versions: Page<Version>;
}
export interface AnalysisSummary {
  id: number;
  document_version_id: number;
  status: string;
  model: string;
  created_at: string;
}
export interface TenderDetail extends Tender {
  description: string | null;
  description_truncated: boolean;
  source_url: string;
  latest_revision: Revision | null;
  documents: Page<TenderDocument>;
  analyses: Page<AnalysisSummary>;
  latest_metadata_change: ChangeSummary | null;
  matches_count: number;
}
export type Fact = {
  value?: string;
  label?: string;
  criterion?: string;
  date?: string | null;
  notes?: string | null;
  weighting?: string | null;
  name?: string | null;
  organization?: string | null;
  email?: string | null;
  phone?: string | null;
  role?: string | null;
  evidence: string;
};
export interface Analysis extends AnalysisSummary {
  analysis_schema_version: string;
  provider: string;
  prompt_version: string;
  facts: {
    summary: string | null;
    summary_evidence: string[];
    eligibility_requirements: Fact[];
    required_documents: Fact[];
    technical_requirements: Fact[];
    financial_requirements: Fact[];
    submission_instructions: Fact[];
    evaluation_criteria: Fact[];
    important_dates: Fact[];
    contact_information: Fact[];
    risks_or_ambiguities: Fact[];
  } | null;
}
export type Json =
  | null
  | string
  | number
  | boolean
  | Json[]
  | { [key: string]: Json };
export interface ChangeSummary {
  id: number;
  tender_id: number;
  kind: "metadata" | "document";
  change_count: number;
  created_at: string;
}
export interface Change extends ChangeSummary {
  from_id: number;
  to_id: number;
  changeset_version: string;
  category_counts: Record<string, number>;
  changed_fields: string[];
  changes: {
    field: string | null;
    category: string | null;
    change_type: string;
    old: Json;
    new: Json;
    old_preview: string | null;
    new_preview: string | null;
    old_hash: string | null;
    new_hash: string | null;
    match_basis: string | null;
    requires_review: boolean;
  }[];
}
export interface Completeness {
  capabilities_complete: boolean;
  certifications_complete: boolean;
  experience_complete: boolean;
  financials_complete: boolean;
}
export interface CompanySummary extends Completeness {
  id: number;
  name: string;
  country: string | null;
  capability_count: number;
  certification_count: number;
  experience_count: number;
}
export interface CompanyProfile extends Completeness {
  name: string;
  description: string | null;
  country: string | null;
  website: string | null;
  employee_count: number | null;
  annual_revenue: string | null;
  currency: string | null;
  years_in_business: number | null;
  capabilities: { name: string; description: string | null }[];
  certifications: {
    name: string;
    issuer: string | null;
    identifier: string | null;
    valid_from: string | null;
    valid_until: string | null;
  }[];
  experience: {
    title: string | null;
    client: string | null;
    description: string | null;
    country: string | null;
    contract_value: string | null;
    currency: string | null;
    started_at: string | null;
    completed_at: string | null;
  }[];
}
export interface Company {
  id: number;
  profile: CompanyProfile;
}
export interface MatchSummary {
  match_id: number;
  company_id: number;
  analysis_id: number;
  eligibility_status: string;
  score: number | null;
  coverage_ratio: number;
  created_at: string;
}
export interface Requirement {
  requirement: string;
  status: string;
  company_fact: Json;
  reason: string;
  tender_evidence: string;
  hard_requirement: boolean;
  category: string;
}
export interface Match extends MatchSummary {
  reused: boolean;
  hard_blockers: Requirement[];
  matched_requirements: Requirement[];
  unmatched_requirements: Requirement[];
  unknown_requirements: Requirement[];
  capability_matches: Requirement[];
  certification_matches: Requirement[];
  experience_matches: Requirement[];
  risks: { kind: string; reason: string; tender_evidence: string | null }[];
}
export interface Answer {
  question_id: number;
  status: "completed" | "insufficient";
  answer: string | null;
  citations: {
    document_version_id: number;
    chunk_id: number;
    chunk_index: number;
    quote: string;
  }[];
  reused: boolean;
}
export interface Run {
  id: number;
  source: string;
  trigger: string;
  status: string;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  stage_count: number;
}
export interface Stage {
  id: number;
  stage: string;
  entity_type: string;
  entity_id: number;
  status: string;
  attempt: number;
  metrics: Record<string, number | boolean>;
  failure_reason: string | null;
}
export interface RunDetail extends Run {
  summary: Record<string, number | boolean>;
  failure_reason: string | null;
  stages: Stage[];
  next_after_stage_id: number | null;
}
export interface Dashboard {
  active_tenders_count: number;
  tender_count: number;
  company_count: number;
  upcoming_deadlines: Tender[];
  recent_changes: ChangeSummary[];
  recent_runs: Run[];
  saved_tenders_count: number;
  unread_alerts_count: number;
  matching_opportunities_count: number;
}
export interface SavedTender {
  id: number;
  company_id: number;
  tender: Tender;
  saved_at: string;
  updated_since_saved: boolean;
}
export interface Alert {
  id: number;
  company_id: number;
  company_name: string;
  tender_id: number;
  tender_title: string;
  type: "new_match" | "tender_updated" | "deadline_reminder";
  title: string;
  message: string;
  created_at: string;
  read_at: string | null;
}
export interface NotificationPreferenceInput {
  notification_email: string | null;
  email_enabled: boolean;
  minimum_match_score: number;
  new_match_alerts: boolean;
  tender_change_alerts: boolean;
  deadline_reminders: boolean;
  delivery_mode: "instant" | "daily_digest";
}
export interface NotificationPreference extends NotificationPreferenceInput {
  company_id: number;
  created_at: string | null;
  updated_at: string | null;
}
export interface MatchOpportunity extends MatchSummary {
  tender_id: number;
  tender_title: string;
  organization: string | null;
  deadline: string | null;
  source: string;
  matched_reasons: string[];
  unknown_reasons: string[];
}
