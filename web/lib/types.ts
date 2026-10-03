// Mirrors the JSON produced by goodfirst/api.py (build_result) and goodfirst/honesty.py.

export type Language = "english" | "hinglish";
export type StepName = "fetching" | "explaining" | "picking" | "honesty_check";
export type CIStepName = "fetching" | "explaining" | "honesty_check";
export type StepStatus = "pending" | "started" | "done" | "skipped" | "failed";

export interface StepEvent {
  step: string;
  status: Exclude<StepStatus, "pending">;
  seconds?: number;
  detail?: string;
}

export type EvidenceStatus = "verified" | "unchecked" | "flagged" | "removed";

export interface Evidence {
  claim: string;
  source: string;
  status: EvidenceStatus;
  by: "model" | "goodfirst";
  reason: string | null;
  section?: "repo" | "issues";
}

export interface SetupStep {
  text: string;
  verified: boolean;
}

export interface ImportantFile {
  path: string;
  why: string;
  url: string;
}

export interface Explanation {
  question: string | null;
  answer: string | null;
  answer_found: boolean | null;
  answer_flags: string[];
  summary: string;
  setup_steps: SetupStep[];
  important_files: ImportantFile[];
  questions_for_maintainers: string[];
  unsure_about: string[];
  confidence: number;
  model_confidence: number;
  low_confidence: boolean;
  ask_maintainer: string | null;
  ask_reason: "answer_not_found" | "low_confidence" | null;
  warnings: string[];
}

export interface IssuePick {
  number: number;
  title: string;
  url: string;
  labels: string[];
  comments: number;
  assigned: boolean;
  why_this_one: string;
  where_to_start: string;
  facts: string[];
  source: "model" | "ranking";
  unverified_files: string[];
}

export interface Issues {
  picks: IssuePick[];
  confidence: number;
  model_confidence: number | null;
  low_confidence: boolean;
  ask_maintainer: string | null;
  warnings: string[];
  message: string | null;
}

export interface CallTiming {
  wall_s: number;
  load_s: number;
  prompt_tokens: number;
  prompt_s: number;
  output_tokens: number;
  output_s: number;
  attempts: number;
}

export interface AnalyzeResult {
  repo: {
    full_name: string;
    html_url: string;
    description: string;
    language: string | null;
    stars: number;
    license: string | null;
    archived: boolean;
    readme_path: string | null;
    contributing_path: string | null;
    file_count: number;
    tree_truncated: boolean;
    labels_used: string[];
    issue_count: number;
    notes: string[];
  };
  explanation: Explanation | null;
  issues: Issues | null;
  explain_error: string | null;
  issues_error: string | null;
  evidence: Evidence[];
  overall_confidence: number;
  overall_low: boolean;
  confidence_floor: number;
  timings: { github_s?: number; explain?: CallTiming; issues?: CallTiming };
  total_s: number;
  model: string;
  language: Language;
  question: string | null;
}

export interface Health {
  ok: boolean;
  model: string;
  ollama_reachable: boolean;
  model_available: boolean;
  github_token: boolean;
}

// ---- PR CI Explainer (goodfirst/ci.py + api.build_ci_result) ----

export interface FailedCheck {
  name: string;
  conclusion: string;
  url: string;
  check_id: number;
  is_actions: boolean;
  annotations: string[];
  log_excerpt: string | null;
  log_status: "ok" | "needs_token" | "missing" | "not_actions" | "not_fetched";
}

export interface CIExplanation {
  what_failed: string;
  why: string;
  fix_steps: SetupStep[];
  quoted_lines: { text: string; verified: boolean }[];
  files: { path: string; in_pr: boolean }[];
  caused_by_this_pr: "yes" | "no" | "unsure";
  model_confidence: number;
}

export interface CIResult {
  pr: {
    owner: string;
    repo: string;
    number: number;
    title: string;
    url: string;
    head_sha: string;
    state: string;
    checks_total: number;
    checks_pending: number;
    failed: FailedCheck[];
    changed_files: string[];
    notes: string[];
  };
  explanation: CIExplanation | null;
  linked_files: string[];
  warnings: string[];
  evidence: Evidence[];
  confidence: number | null;
  low_confidence: boolean;
  ask_comment: string | null;
  explain_error: string | null;
  confidence_floor: number;
  total_s: number;
  model: string;
}
