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
}

export interface Credibility {
  overall: number;
  recommendation: Recommendation;
  confidence: "high" | "medium" | "low";
  sub_scores: SubScores;
  score_rationale?: Record<string, string>;
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

export interface Report {
  id?: string;
  created_at?: string;
  file_name?: string;
  candidate: Candidate;
  skills: Skills;
  experience: Experience[];
  education: Education[];
  projects?: Project[];
  certifications?: string[];
  credibility: Credibility;
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
