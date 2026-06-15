// @author Claude Sonnet 4.6 Anthropic

export const OUTCOME_COLOR: Record<string, string> = {
  success: '#2a9',
  failure: '#c33',
  partial: '#c80',
  skipped: '#888',
};

export const OUTCOME_TOOLTIP: Record<string, string> = {
  success: 'Agent ran to completion and reported success.',
  failure: 'Agent ran but reported failure, or the run errored out.',
  partial: 'Agent hit the configured turn limit and was cut short. Work is saved to a WIP branch and a handover comment is posted.',
  skipped: 'Harness did not invoke the agent — see failure reason for why (e.g. no task found, daily budget exceeded, project already locked).',
};

export const SOURCE_TOOLTIP: Record<string, string> = {
  'gh-label': 'Picks up open GitHub issues/PRs that carry a configured trigger label.',
  'gh-author': 'Picks up PRs/issues matching a configured author pattern (e.g. Dependabot).',
  'proactive-improvement': 'Labro uses a randomly chosen perspective to guide an improvement suggestion.',
  'grafana-alerts': 'Picks up firing Grafana alert rules for the project.',
};
