// @author Claude Sonnet 4.6 Anthropic
import { useState } from 'react';
import type { ProjectStats } from '../data/DataSource';

type SortKey = keyof ProjectStats;
type SortDir = 'asc' | 'desc';

interface Props {
  stats: ProjectStats[];
}

const OUTCOME_COLORS: Record<string, string> = {
  success: '#2a9',
  failure: '#c33',
  partial: '#c80',
  skipped: '#888',
};

function fmtCost(usd: number | null): string {
  if (usd == null) return '—';
  if (usd <= 0) return '$0.00';
  if (usd < 0.01) return '<$0.01';
  return `$${usd.toFixed(2)}`;
}

function fmtDuration(s: number | null): string {
  if (s == null) return '—';
  if (s < 60) return `${s.toFixed(0)}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return rem > 0 ? `${m}m ${rem}s` : `${m}m`;
}

function fmtTurns(t: number | null): string {
  if (t == null) return '—';
  return t.toFixed(1);
}

function SuccessBar({ stats }: { stats: ProjectStats }) {
  const total = stats.total_runs;
  if (total === 0) return <span style={{ color: '#555' }}>—</span>;

  const pct = (n: number) => `${((n / total) * 100).toFixed(0)}%`;
  const parts: [number, string, string][] = [
    [stats.success_count, 'success', OUTCOME_COLORS.success],
    [stats.failure_count, 'failure', OUTCOME_COLORS.failure],
    [stats.partial_count, 'partial', OUTCOME_COLORS.partial],
    [stats.skipped_count, 'skipped', OUTCOME_COLORS.skipped],
  ];

  return (
    <span style={{ letterSpacing: '0.05em', whiteSpace: 'nowrap' }}>
      {parts
        .filter(([n]) => n > 0)
        .map(([n, label, color]) => (
          <span key={label} style={{ color }} title={`${label}: ${n}`}>
            {pct(n)}
          </span>
        ))
        .reduce<React.ReactNode[]>((acc, el, i) => (i === 0 ? [el] : [...acc, <span key={i} style={{ color: '#444', margin: '0 0.2em' }}>/</span>, el]), [])}
    </span>
  );
}

const TH: React.CSSProperties = {
  padding: '0.35rem 0.6rem',
  textAlign: 'left',
  borderBottom: '2px solid #444',
  whiteSpace: 'nowrap',
  cursor: 'pointer',
  userSelect: 'none',
  color: '#aaa',
};

const TD: React.CSSProperties = {
  padding: '0.3rem 0.6rem',
  borderBottom: '1px solid #2a2a2a',
  verticalAlign: 'middle',
  whiteSpace: 'nowrap',
};

const TD_NUM: React.CSSProperties = { ...TD, textAlign: 'right', color: '#aaa' };

export default function ProjectStats({ stats }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('total_runs');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  const sorted = [...stats].sort((a, b) => {
    const av = a[sortKey] ?? 0;
    const bv = b[sortKey] ?? 0;
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === 'asc' ? cmp : -cmp;
  });

  function arrow(key: SortKey) {
    if (key !== sortKey) return '';
    return sortDir === 'asc' ? ' ▲' : ' ▼';
  }

  function th(label: string, key: SortKey, style?: React.CSSProperties) {
    return (
      <th style={{ ...TH, ...style }} onClick={() => handleSort(key)}>
        {label}{arrow(key)}
      </th>
    );
  }

  const totalRuns = stats.reduce((s, r) => s + r.total_runs, 0);
  const totalCost = stats.reduce((s, r) => s + (r.total_cost_usd ?? 0), 0);

  return (
    <div>
      <div style={{ display: 'flex', gap: '2rem', marginBottom: '1rem', color: '#888', fontSize: '0.82rem' }}>
        <span>{stats.length} project{stats.length !== 1 ? 's' : ''}</span>
        <span>{totalRuns} total runs</span>
        <span className="col-desktop">{fmtCost(totalCost)} total cost</span>
      </div>
      <div style={{ overflowX: 'auto' }}>
        <table
          className="stats-table"
          style={{
            width: '100%',
            borderCollapse: 'collapse',
            fontFamily: 'monospace',
            fontSize: '0.82rem',
          }}
        >
          <thead>
            <tr>
              {th('project', 'project')}
              {th('runs', 'total_runs', { textAlign: 'right' })}
              <th style={{ ...TH, cursor: 'default' }}>outcomes</th>
              <th className="col-desktop" style={{ ...TH, textAlign: 'right' }} onClick={() => handleSort('total_cost_usd')}>total cost{arrow('total_cost_usd')}</th>
              <th className="col-desktop" style={{ ...TH, textAlign: 'right' }} onClick={() => handleSort('avg_cost_usd')}>avg/run{arrow('avg_cost_usd')}</th>
              {th('avg dur', 'avg_duration_s', { textAlign: 'right' })}
              <th className="col-desktop" style={{ ...TH, textAlign: 'right' }} onClick={() => handleSort('avg_turns')}>avg turns{arrow('avg_turns')}</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((row) => (
              <tr key={row.project} style={{ color: '#ddd' }}>
                <td style={TD}>{row.project}</td>
                <td style={TD_NUM}>{row.total_runs}</td>
                <td style={TD}><SuccessBar stats={row} /></td>
                <td className="col-desktop" style={TD_NUM}>{fmtCost(row.total_cost_usd)}</td>
                <td className="col-desktop" style={TD_NUM}>{fmtCost(row.avg_cost_usd)}</td>
                <td style={TD_NUM}>{fmtDuration(row.avg_duration_s)}</td>
                <td className="col-desktop" style={TD_NUM}>{fmtTurns(row.avg_turns)}</td>
              </tr>
            ))}
            {sorted.length === 0 && (
              <tr>
                <td colSpan={4} style={{ ...TD, color: '#666', textAlign: 'center' }}>
                  no data
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
