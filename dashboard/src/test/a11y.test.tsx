// @author Claude Sonnet 4.6 Anthropic
import { render } from '@testing-library/react';
import { axe } from 'jest-axe';
import FilterBar from '../components/FilterBar';
import RunDrawer from '../components/RunDrawer';
import RunsTable from '../components/RunsTable';
import type { Run, FilterOptions, RunFilter } from '../data/DataSource';

const FILTER_OPTIONS: FilterOptions = {
  projects: ['labro', 'infra'],
  agents: ['claude-code'],
  models: ['claude-sonnet-4-6'],
  task_sources: ['gh-label', 'proactive-improvement'],
  outcomes: ['success', 'failure', 'partial'],
};

const FILTER_VALUE: RunFilter = { outcomes: ['success', 'failure'] };

const SAMPLE_RUN: Run = {
  run_id: 'run-001',
  project: 'labro',
  task_source: 'gh-label',
  agent: 'claude-code',
  provider: 'anthropic',
  model: 'claude-sonnet-4-6',
  effort: 'high',
  outcome: 'success',
  started_at: '2025-06-01T10:00:00Z',
  ended_at: '2025-06-01T10:05:00Z',
  duration_s: 300,
  total_cost_usd: 0.12,
  input_tokens: 5000,
  output_tokens: 800,
  cache_read_tokens: 1200,
  cache_write_tokens: 400,
  turns_used: 8,
  summary: 'Reviewed PR and left comments.',
  task_description: 'Review open PRs',
  item_url: 'https://github.com/example/repo/pulls/1',
  trigger_label: null,
  failure_reason: null,
  actions_taken: null,
  wip_branch_url: null,
  source_description: '🏷️ gh-label',
  thumbs_up: 1,
  thumbs_down: 0,
  chosen_perspective: null,
  fallback_attempts: null,
};

describe('FilterBar accessibility', () => {
  it('has no axe violations', async () => {
    const { container } = render(
      <FilterBar options={FILTER_OPTIONS} value={FILTER_VALUE} onChange={() => {}} />
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});

describe('RunDrawer accessibility', () => {
  it('has no axe violations when open', async () => {
    const { container } = render(
      <RunDrawer run={SAMPLE_RUN} onClose={() => {}} />
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('renders nothing when run is null', () => {
    const { container } = render(<RunDrawer run={null} onClose={() => {}} />);
    expect(container.firstChild).toBeNull();
  });
});

describe('RunsTable accessibility', () => {
  it('has no axe violations with data', async () => {
    const { container } = render(
      <RunsTable runs={[SAMPLE_RUN]} onSelect={() => {}} projectEmoji={{ labro: '🤖' }} />
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('has no axe violations when empty', async () => {
    const { container } = render(
      <RunsTable runs={[]} onSelect={() => {}} projectEmoji={{}} />
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
