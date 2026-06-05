// @author Claude Sonnet 4.6 Anthropic
import type { RunFilter, FilterOptions } from '../data/DataSource';

interface Props {
  options: FilterOptions;
  value: RunFilter;
  onChange: (f: RunFilter) => void;
}

function timespanSince(ts: string): string | undefined {
  if (ts === 'all') return undefined;
  const d = new Date();
  if (ts === '7d') d.setDate(d.getDate() - 7);
  else if (ts === '30d') d.setDate(d.getDate() - 30);
  else if (ts === '90d') d.setDate(d.getDate() - 90);
  return d.toISOString().slice(0, 10);
}

const SELECT_STYLE: React.CSSProperties = {
  background: '#1a1a1a',
  color: '#ddd',
  border: '1px solid #333',
  borderRadius: '3px',
  padding: '0.25rem 0.5rem',
  fontFamily: 'monospace',
  fontSize: '0.8rem',
};

export default function FilterBar({ options, value, onChange }: Props) {
  const timespan = !value.since ? 'all'
    : value.since === timespanSince('7d') ? '7d'
    : value.since === timespanSince('30d') ? '30d'
    : value.since === timespanSince('90d') ? '90d'
    : 'all';

  function set<K extends keyof RunFilter>(key: K, val: RunFilter[K]) {
    onChange({ ...value, [key]: val });
  }

  return (
    <div style={{ display: 'flex', gap: '1rem', alignItems: 'center', marginBottom: '1rem', flexWrap: 'wrap' }}>
      <span style={{ color: '#888', fontSize: '0.8rem' }}>filter:</span>
      <select
        style={SELECT_STYLE}
        value={timespan}
        onChange={(e) => set('since', timespanSince(e.target.value))}
      >
        <option value="all">All time</option>
        <option value="90d">Last 90 days</option>
        <option value="30d">Last 30 days</option>
        <option value="7d">Last 7 days</option>
      </select>
      <select
        style={SELECT_STYLE}
        value={value.project ?? ''}
        onChange={(e) => set('project', e.target.value || undefined)}
      >
        <option value="">All projects</option>
        {options.projects.map((p) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </select>
      <select
        style={SELECT_STYLE}
        value={value.outcome ?? ''}
        onChange={(e) => set('outcome', e.target.value || undefined)}
      >
        <option value="">All outcomes</option>
        {options.outcomes.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
      <select
        style={SELECT_STYLE}
        value={value.task_source ?? ''}
        onChange={(e) => set('task_source', e.target.value || undefined)}
      >
        <option value="">All task sources</option>
        {options.task_sources.map((s) => (
          <option key={s} value={s}>{s}</option>
        ))}
      </select>
      <select
        style={SELECT_STYLE}
        value={value.model ?? ''}
        onChange={(e) => set('model', e.target.value || undefined)}
      >
        <option value="">All models</option>
        {options.models.map((m) => (
          <option key={m} value={m}>{m}</option>
        ))}
      </select>
    </div>
  );
}
