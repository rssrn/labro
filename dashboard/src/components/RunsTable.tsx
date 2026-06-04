// @author Claude Sonnet 4.6 Anthropic
import { useState } from 'react';
import type { Run } from '../data/DataSource';

type SortKey = 'started_at' | 'project' | 'task_source' | 'model' | 'outcome' | 'total_cost_usd' | 'turns_used';
type SortDir = 'asc' | 'desc';

interface Props {
  runs: Run[];
}

const OUTCOME_COLOR: Record<string, string> = {
  success: '#2a9',
  failure: '#c33',
  partial: '#c80',
  skipped: '#888',
};

function DateCell({ iso }: { iso: string }) {
  const full = iso.replace('T', ' ').slice(0, 16) + 'Z'; // 2026-06-04 09:30Z
  const short = iso.slice(5, 16).replace('T', ' ');       // 06-04 09:30
  return (
    <>
      <span className="date-full">{full}</span>
      <span className="date-short">{short}</span>
    </>
  );
}

function fmtModel(provider: string | null, model: string | null): string {
  if (!model) return '—';
  const short = model.replace(/^claude-/, '');
  return provider ? `${provider}/${short}` : short;
}

function fmtCost(usd: number | null): string {
  if (usd == null) return '—';
  if (usd < 0.01) return '<$0.01';
  return `$${usd.toFixed(2)}`;
}

function truncate(s: string | null, n: number): string {
  if (!s) return '';
  return s.length > n ? s.slice(0, n) + '…' : s;
}

const TH_STYLE: React.CSSProperties = {
  padding: '0.35rem 0.6rem',
  textAlign: 'left',
  borderBottom: '2px solid #444',
  whiteSpace: 'nowrap',
  cursor: 'pointer',
  userSelect: 'none',
};

const TD_STYLE: React.CSSProperties = {
  padding: '0.3rem 0.6rem',
  borderBottom: '1px solid #2a2a2a',
  verticalAlign: 'top',
  whiteSpace: 'nowrap',
};

export default function RunsTable({ runs }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('started_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  function handleSort(key: SortKey) {
    if (key === sortKey) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  const sorted = [...runs].sort((a, b) => {
    const av = a[sortKey] ?? '';
    const bv = b[sortKey] ?? '';
    const cmp = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === 'asc' ? cmp : -cmp;
  });

  function arrow(key: SortKey): string {
    if (key !== sortKey) return '';
    return sortDir === 'asc' ? ' ▲' : ' ▼';
  }

  function th(label: string, key: SortKey, extra?: React.CSSProperties) {
    return (
      <th style={{ ...TH_STYLE, ...extra }} onClick={() => handleSort(key)}>
        {label}{arrow(key)}
      </th>
    );
  }

  return (
    <div style={{ overflowX: 'auto' }}>
      <table
        className="runs-table"
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          fontFamily: 'monospace',
        }}
      >
        <thead>
          <tr style={{ color: '#aaa' }}>
            {th('date', 'started_at')}
            {th('project', 'project')}
            {th('source', 'task_source')}
            <th className="col-desktop" style={TH_STYLE} onClick={() => handleSort('model')}>model{arrow('model')}</th>
            {th('outcome', 'outcome')}
            <th className="col-desktop" style={{ ...TH_STYLE, textAlign: 'right' }} onClick={() => handleSort('total_cost_usd')}>cost{arrow('total_cost_usd')}</th>
            <th className="col-desktop" style={{ ...TH_STYLE, textAlign: 'right' }} onClick={() => handleSort('turns_used')}>turns{arrow('turns_used')}</th>
            <th className="col-desktop" style={{ ...TH_STYLE, cursor: 'default', minWidth: '180px' }}>
              failure reason
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((run) => (
            <tr key={run.run_id} style={{ color: '#ddd' }}>
              <td style={TD_STYLE}><DateCell iso={run.started_at} /></td>
              <td style={TD_STYLE}>{run.project}</td>
              <td style={TD_STYLE}>{run.task_source ?? '—'}</td>
              <td className="col-desktop" style={TD_STYLE}>{fmtModel(run.provider, run.model)}</td>
              <td style={TD_STYLE}>
                <span style={{ color: OUTCOME_COLOR[run.outcome ?? ''] ?? '#aaa', fontWeight: 'bold' }}>
                  {run.outcome ?? '—'}
                </span>
              </td>
              <td className="col-desktop" style={{ ...TD_STYLE, textAlign: 'right', color: '#aaa' }}>
                {fmtCost(run.total_cost_usd)}
              </td>
              <td className="col-desktop" style={{ ...TD_STYLE, textAlign: 'right', color: '#aaa' }}>
                {run.turns_used ?? '—'}
              </td>
              <td className="col-desktop" style={{ ...TD_STYLE, whiteSpace: 'normal', color: '#888' }}>
                {truncate(run.failure_reason, 60)}
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={8} style={{ ...TD_STYLE, color: '#666', textAlign: 'center' }}>
                no runs
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
