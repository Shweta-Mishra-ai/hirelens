// HireLens — Complete TypeScript Types

export type Recommendation = "recommended" | "manual_review" | "high_risk";
export type Severity = "high" | "medium" | "low";
export type JobStatus = "queued" | "running" | "complete" | "failed";
export type Decision = "advance" | "schedule_followup" | "reject";

export interface Candidate {
  name: string | null;
  email: string | null;
  phone: string | null;
  location: string | null;
  linkedin?: string | null;
  github?: string | null;
  current_role?: string | null;
  total_experience_years?: number | null;
}

export interface Skills {
  all_claimed: string[];
  verified_by_evidence: string[];
  unverified: string[];
  keyword_stuffing_risk: "none" | "low" | "medium" | "high";
  primary_domain: string;
  domain_spread_concern?: boolean;
  domain_spread_note?: string | null;
}

export interface Experience {
  role: string;
  company: string;
  period: string;
  start_date?: string | null;
  end_date?: string | null;
  duration_months?: number | null;
  responsibilities?: string[];
  technologies?: string[];
  is_verifiable?: boolean;
}

export interface Education {
  degree: string;
  institution: string;
  period?: string;
  duration_years?: number | null;
  field?: string | null;
  grade?: string | null;
  is_recognized_institution?: boolean;
  concern?: string | null;
}

export interface Project {
  name: string;
  description: string;
  technologies: string[];
  metrics: string[];
  has_link: boolean;
}

export interface SubScores {
  timeline: number;
  skills_consistency: number;
  education: number;
  project_authenticity: number;
  resume_quality: number;
  content_authenticity: number;
}

export interface AIContentAnalysis {
  likelihood: "low" | "medium" | "high";
  indicators: string[];
  human_indicators: string[];
  note: string;
}

export interface Credibility {
  overall: number;
  recommendation: Recommendation;
  confidence: "high" | "medium" | "low";
  sub_scores: SubScores;
  score_rationale?: Record<string, string>;
  ai_recommendation?: Recommendation;
  recommendation_adjusted_by_verification?: boolean;
  recommendation_adjustment_reason?: string;
}

export interface Flag {
  severity: Severity;
  category: string;
  title: string;
  description: string;
  evidence: string;
  action?: string | null;
}

export interface TimelineGap {
  from: string;
  to: string;
  duration: string;
  severity: Severity;
  note?: string;
}

export interface PositiveSignal {
  title: string;
  description: string;
}

export interface InterviewQuestion {
  question: string;
  rationale?: string | null;
  targets_flag?: string | null;
  category?: "technical" | "clarification" | "behavioral";
}

export interface TalentVelocity {
  growth_velocity_index: number;
  trajectory_stage: string;
  promotion_cadence_months: number;
  retention_stability_score: number;
  note: string;
}

export interface Report {
  id?: string;
  created_at?: string;
  file_name?: string;
  team_id?: string | null;
  candidate: Candidate;
  skills: Skills;
  experience: Experience[];
  education: Education[];
  projects?: Project[];
  certifications?: string[];
  credibility: Credibility;
  ai_content_analysis?: AIContentAnalysis;
  talent_velocity?: TalentVelocity;
  timeline_gaps: TimelineGap[];
  flags: Flag[];
  positive_signals: PositiveSignal[];
  interview_questions: InterviewQuestion[];
  summary: string;
  one_liner?: string;
  recruiter_decision: Decision | null;
}


export interface AnalysisJob {
  id: string;
  status: JobStatus;
  stage: string;
  progress: number;
  file_name?: string;
  report_id?: string | null;
  error?: string | null;
}

// ── JD Match (Feature 2) ────────────────────────────────────────────────────
export type MatchVerdict = "strong_fit" | "partial_fit" | "weak_fit" | "unknown";

export interface MatchedCandidate {
  rank: number;
  is_best_fit: boolean;
  report_id: string;
  file_name: string;
  candidate_name: string;
  overall_score: number;
  recommendation: Recommendation;
  match_percent: number;
  matching_skills: string[];
  missing_skills: string[];
  verdict: MatchVerdict;
  rationale: string;
}

export interface MatchBatchStatus {
  batch_id: string;
  total: number;
  queued: number;
  running: number;
  complete: number;
  failed: number;
  is_done: boolean;
  jobs: AnalysisJob[];
  ranking: MatchedCandidate[];
}

// ── Bulk Upload (Feature 1) ────────────────────────────────────────────────
export interface BulkUploadResponse {
  batch_id: string;
  total: number;
  accepted: number;
  rejected: number;
  message: string;
}

export interface RankedCandidate {
  rank: number;
  report_id: string;
  file_name: string;
  candidate_name: string;
  overall_score: number;
  recommendation: Recommendation;
}

export interface BatchStatus {
  batch_id: string;
  total: number;
  queued: number;
  running: number;
  complete: number;
  failed: number;
  is_done: boolean;
  jobs: AnalysisJob[];
  ranking: RankedCandidate[];
}

export interface User {
  id: string;
  email: string;
  full_name?: string;
  company?: string;
}

export interface AuthState {
  user: User | null;
  token: string | null;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  signup: (email: string, password: string, fullName: string, company?: string) => Promise<void>;
  logout: () => void;
}

// ── Public Data Verification (Feature 3) ────────────────────────────────────
export type GithubVerifyStatus =
  | "verified" | "partial" | "no_public_activity" | "not_found"
  | "no_username" | "rate_limited" | "error";

export interface GithubVerification {
  status: GithubVerifyStatus;
  username: string | null;
  profile_url?: string;
  avatar_url?: string;
  public_repos?: number;
  account_created?: string;
  top_languages?: string[];
  verified_skills?: string[];
  unverified_skills?: string[];
  note?: string;
}

export interface EducationVerification {
  institution: string | null;
  status: "verified" | "not_found" | "skipped" | "error";
  matched_name?: string;
  country?: string;
  domain?: string;
  note?: string;
}

export interface CertificationVerification {
  name: string;
  url?: string;
  status: "verified_via_link" | "link_reachable_name_not_confirmed" | "link_unreachable" | "no_link_provided" | "error";
  note?: string;
}

export interface ExperienceVerification {
  company: string | null;
  domain_checked?: string;
  status: "domain_found" | "domain_not_found" | "skipped";
  note?: string;
}

export interface Team {
  id: string;
  name: string;
  owner_id: string;
  created_at: string;
  my_role?: "owner" | "admin" | "member";
}

export interface TeamMember {
  user_id: string;
  role: "owner" | "admin" | "member";
  joined_at: string;
}

export interface ReportComment {
  id: string;
  report_id: string;
  user_id: string;
  comment: string;
  created_at: string;
}

export interface VotesResult {
  votes: { report_id: string; user_id: string; vote: "advance" | "reject" | "maybe" }[];
  tally: { advance: number; reject: number; maybe: number };
  my_vote: "advance" | "reject" | "maybe" | null;
}

export interface DuplicateCluster {
  similarity: number;
  members: { id: string; name: string }[];
}

export interface DuplicateCheckResult {
  batch_id: string;
  candidates_compared: number;
  clusters: DuplicateCluster[];
  note: string;
}

export interface TrustAssessment {
  verdict: "high_confidence" | "moderate_confidence" | "low_confidence" | "insufficient_evidence";
  score: number;
  reasoning: string[];
  evidence_available: boolean;
}

export interface VerificationResult {
  run_at: string;
  github: GithubVerification;
  education: EducationVerification[];
  certifications: CertificationVerification[];
  experience: ExperienceVerification[];
  trust_assessment?: TrustAssessment;
  recommendation_update?: {
    new_recommendation: Recommendation;
    ai_recommendation: Recommendation;
    reason: string;
  } | null;
}
