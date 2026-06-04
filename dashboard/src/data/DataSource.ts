import type { Manifest } from './manifest';

export interface RunFilter {
  project?: string;
  since?: string;
  limit?: number;
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

export interface DataSource {
  init(manifest: Manifest): Promise<void>;
  count(table: string): Promise<number>;
  listRuns(filter?: RunFilter): Promise<Run[]>;
  projectStats(filter?: RunFilter): Promise<ProjectStats[]>;
}
