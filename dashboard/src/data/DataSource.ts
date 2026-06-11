import type { Manifest } from './manifest';

export interface RunFilter {
  project?: string;
  since?: string;
  limit?: number;
  model?: string;
  task_source?: string;
  outcomes?: string[];
}

export interface Run {
  run_id: string;
  project: string;
  started_at: string;
  ended_at: string | null;
  task_source: string | null;
  task_description: string | null;
  item_url: string | null;
  trigger_label: string | null;
  agent: string | null;
  provider: string | null;
  model: string | null;
  effort: string | null;
  outcome: string | null;
  failure_reason: string | null;
  duration_s: number | null;
  total_cost_usd: number | null;
  turns_used: number | null;
  input_tokens: number | null;
  output_tokens: number | null;
  cache_read_tokens: number | null;
  cache_write_tokens: number | null;
  summary: string | null;
  actions_taken: string | null;
  wip_branch_url: string | null;
  chosen_perspective: string | null;
  fallback_attempts: string | null;
  thumbs_up: number | null;
  thumbs_down: number | null;
}

export interface ProjectStats {
  project: string;
  total_runs: number;
  success_count: number;
  failure_count: number;
  partial_count: number;
  skipped_count: number;
  total_cost_usd: number | null;
  avg_cost_usd: number | null;
  avg_duration_s: number | null;
  avg_turns: number | null;
}

export interface TrendPoint {
  date: string;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  success: number;
  failure: number;
  partial: number;
  skipped: number;
}

export interface BreakdownEntry {
  label: string;
  count: number;
}

export interface EngagementRow {
  outcome_state: string;
  count: number;
  thumbs_up: number;
  thumbs_down: number;
  follow_up_commits: number;
}

export interface DurationPoint {
  date: string;
  model: string;
  avg_duration_s: number;
}

export interface FilterOptions {
  projects: string[];
  models: string[];
  task_sources: string[];
  outcomes: string[];
}

export interface DataSource {
  init(manifest: Manifest): Promise<void>;
  count(table: string): Promise<number>;
  listRuns(filter?: RunFilter): Promise<Run[]>;
  projectStats(filter?: RunFilter): Promise<ProjectStats[]>;
  getFilterOptions(): Promise<FilterOptions>;
  trend(filter?: RunFilter): Promise<TrendPoint[]>;
  modelBreakdown(filter?: RunFilter): Promise<BreakdownEntry[]>;
  taskSourceBreakdown(filter?: RunFilter): Promise<BreakdownEntry[]>;
  perspectiveBreakdown(filter?: RunFilter): Promise<BreakdownEntry[]>;
  engagementSignals(filter?: RunFilter): Promise<EngagementRow[]>;
  durationTrend(filter?: RunFilter): Promise<DurationPoint[]>;
}
