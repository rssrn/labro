// @author Claude Sonnet 4.6 Anthropic
import { render, fireEvent } from '@testing-library/react';
import { vi } from 'vitest';
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
  source_description: '🔍 Analyst',
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

  it('outcome button reflects open state via aria-expanded', () => {
    const { getByRole } = render(
      <FilterBar options={FILTER_OPTIONS} value={FILTER_VALUE} onChange={() => {}} />
    );
    const btn = getByRole('button', { name: /outcomes/i });
    expect(btn).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(btn);
    expect(btn).toHaveAttribute('aria-expanded', 'true');
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

  it('marks the default sort column (date) as descending', () => {
    const { getAllByRole } = render(
      <RunsTable runs={[SAMPLE_RUN]} onSelect={() => {}} projectEmoji={{}} />
    );
    const headers = getAllByRole('columnheader');
    expect(headers[0]).toHaveAttribute('aria-sort', 'descending');
    expect(headers[1]).toHaveAttribute('aria-sort', 'none');
  });

  it('updates aria-sort when a column header is clicked', () => {
    const { getAllByRole } = render(
      <RunsTable runs={[SAMPLE_RUN]} onSelect={() => {}} projectEmoji={{}} />
    );
    const headers = getAllByRole('columnheader');
    fireEvent.click(headers[1]); // project column
    expect(headers[1]).toHaveAttribute('aria-sort', 'descending');
    expect(headers[0]).toHaveAttribute('aria-sort', 'none');
    fireEvent.click(headers[1]); // toggle to ascending
    expect(headers[1]).toHaveAttribute('aria-sort', 'ascending');
  });

  it('activates a row on Enter key', () => {
    const onSelect = vi.fn();
    const { getAllByRole } = render(
      <RunsTable runs={[SAMPLE_RUN]} onSelect={onSelect} projectEmoji={{}} />
    );
    const rows = getAllByRole('row');
    fireEvent.keyDown(rows[1], { key: 'Enter' }); // rows[0] is the header row
    expect(onSelect).toHaveBeenCalledWith(SAMPLE_RUN);
  });

  it('activates a row on Space key', () => {
    const onSelect = vi.fn();
    const { getAllByRole } = render(
      <RunsTable runs={[SAMPLE_RUN]} onSelect={onSelect} projectEmoji={{}} />
    );
    const rows = getAllByRole('row');
    fireEvent.keyDown(rows[1], { key: ' ' });
    expect(onSelect).toHaveBeenCalledWith(SAMPLE_RUN);
  });

  it('mobile emoji cells have aria-label with the real text value', () => {
    const run = { ...SAMPLE_RUN, thumbs_up: 0 };
    const { container } = render(
      <RunsTable runs={[run]} onSelect={() => {}} projectEmoji={{ labro: '🤖' }} />
    );
    const mobileSpans = container.querySelectorAll('.proj-mobile[aria-label]');
    const labels = Array.from(mobileSpans).map((el) => el.getAttribute('aria-label'));
    expect(labels).toContain('labro');
    expect(labels).toContain('gh-label: Analyst');
    expect(labels).toContain('success');
  });

  it('thumbs-up/down spans have descriptive aria-label and title', () => {
    const run = { ...SAMPLE_RUN, thumbs_up: 2, thumbs_down: 1 };
    const { container } = render(
      <RunsTable runs={[run]} onSelect={() => {}} projectEmoji={{}} />
    );
    const thumbsUp = container.querySelector('[aria-label*="positive GitHub reaction"]');
    const thumbsDown = container.querySelector('[aria-label*="negative GitHub reaction"]');
    expect(thumbsUp).toHaveAttribute('aria-label', '2 positive GitHub reactions on the linked issue or PR');
    expect(thumbsUp).toHaveAttribute('title', '2 positive GitHub reactions on the linked issue or PR');
    expect(thumbsDown).toHaveAttribute('aria-label', '1 negative GitHub reaction on the linked issue or PR');
    expect(thumbsDown).toHaveAttribute('title', '1 negative GitHub reaction on the linked issue or PR');
  });

  it('source aria-label includes sub-type and (highly rated) for thumbs-up runs', () => {
    const thumbsUpRun = { ...SAMPLE_RUN, task_source: 'proactive-improvement', source_description: '🎭 Black Hat', thumbs_up: 1 };
    const normalRun = { ...SAMPLE_RUN, run_id: 'run-002', task_source: 'proactive-improvement', source_description: '🎭 Black Hat', thumbs_up: 0 };
    const { container } = render(
      <RunsTable runs={[thumbsUpRun, normalRun]} onSelect={() => {}} projectEmoji={{}} />
    );
    const sourceSpans = container.querySelectorAll('[aria-label*="proactive-improvement"]');
    const labels = Array.from(sourceSpans).map((el) => el.getAttribute('aria-label'));
    expect(labels).toContain('proactive-improvement: Black Hat (highly rated)');
    expect(labels).toContain('proactive-improvement: Black Hat');
  });
});
