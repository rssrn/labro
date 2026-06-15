// @author Claude Sonnet 4.6 Anthropic
import { useState } from 'react';
import type { Run } from '../data/DataSource';
import { OUTCOME_COLOR, OUTCOME_TOOLTIP, SOURCE_TOOLTIP } from '../constants';

type SortKey = 'started_at' | 'project' | 'task_source' | 'agent' | 'model' | 'outcome' | 'total_cost_usd' | 'turns_used';
type SortDir = 'asc' | 'desc';

interface Props {
  runs: Run[];
  onSelect: (run: Run) => void;
  projectEmoji: Record<string, string>;
}

// Swaps 🎭→💡 on thumbs-up runs so successful proactive suggestions are visually distinct at a glance.
function sourceLabel(run: Run): string {
  const label = run.source_description ?? run.task_source ?? '—';
  const thumbsUp = (run.thumbs_up ?? 0) > 0;
  return thumbsUp ? label.replace('🎭', '💡') : label;
}

function localTZ(): string {
  const offset = -new Date().getTimezoneOffset();
  const sign = offset >= 0 ? '+' : '';
  const h = Math.floor(offset / 60);
  const m = offset % 60;
  return `GMT${sign}${h}${m !== 0 ? ':' + String(m).padStart(2, '0') : ''}`;
}

function DateCell({ iso }: { iso: string }) {
  const s = new Date(iso).toLocaleString('sv-SE');
  return (
    <>
      <span className="date-full">{s.slice(0, 16)}</span>
      <span className="date-short">{s.slice(5, 16)}</span>
    </>
  );
}

function fmtModel(provider: string | null, model: string | null): string {
  if (!model) {
    return "[agent's internal default]";
  }
  const short = model.replace(/^claude-/, '');
  return provider ? `${provider}/${short}` : short;
}

function fmtCost(usd: number | null): string {
  if (usd == null) return '—';
  if (usd <= 0) return '$0.00';
  if (usd < 0.01) return '<$0.01';
  return `$${usd.toFixed(2)}`;
}

function parseFallbacks(raw: string | null): string | null {
  if (!raw) return null;
  try {
    const attempts: { slug: string }[] = JSON.parse(raw);
    return attempts.map((a) => a.slug).join(', ');
  } catch {
    return null;
  }
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

export default function RunsTable({ runs, onSelect, projectEmoji }: Props) {
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

  function sort(key: SortKey): 'ascending' | 'descending' | 'none' {
    if (key !== sortKey) return 'none';
    return sortDir === 'asc' ? 'ascending' : 'descending';
  }

  function th(label: string, key: SortKey, extra?: React.CSSProperties, thTitle?: string) {
    return (
      <th style={{ ...TH_STYLE, ...extra }} onClick={() => handleSort(key)} title={thTitle} aria-sort={sort(key)}>
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
            {th('date', 'started_at', undefined, localTZ())}
            <th style={TH_STYLE} onClick={() => handleSort('project')} aria-sort={sort('project')}>
              <span className="proj-mobile">proj</span>
              <span className="proj-desktop">project</span>
              {arrow('project')}
            </th>
            <th style={TH_STYLE} onClick={() => handleSort('task_source')} title="Where the task came from." aria-sort={sort('task_source')}>
              <span className="proj-mobile">src</span>
              <span className="proj-desktop">source</span>
              {arrow('task_source')}
            </th>
            <th className="col-desktop" style={TH_STYLE} onClick={() => handleSort('agent')} aria-sort={sort('agent')}>agent{arrow('agent')}</th>
            <th className="col-desktop" style={TH_STYLE} onClick={() => handleSort('model')} aria-sort={sort('model')}>model{arrow('model')}</th>
            <th style={TH_STYLE} onClick={() => handleSort('outcome')} title="Recorded at the end of the run; updated by thumbs up/down reactions." aria-sort={sort('outcome')}>
              <span className="proj-mobile">out</span>
              <span className="proj-desktop">outcome</span>
              {arrow('outcome')}
            </th>
            <th className="col-desktop" style={{ ...TH_STYLE, textAlign: 'right' }} onClick={() => handleSort('total_cost_usd')} aria-sort={sort('total_cost_usd')}>cost{arrow('total_cost_usd')}</th>
            <th className="col-desktop" style={{ ...TH_STYLE, textAlign: 'right' }} onClick={() => handleSort('turns_used')} title="Number of agent conversation turns used. Capped by the configured max_turns; if turns = max and outcome = partial, the run was cut short." aria-sort={sort('turns_used')}>turns{arrow('turns_used')}</th>
            <th className="col-desktop" style={{ ...TH_STYLE, cursor: 'default', minWidth: '120px' }}>
              detail
            </th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((run) => (
            <tr
              key={run.run_id}
              style={{ color: '#ddd' }}
              onClick={() => onSelect(run)}
              tabIndex={0}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(run); } }}
            >
              <td style={TD_STYLE}><DateCell iso={run.started_at} /></td>
              <td style={TD_STYLE}>
                <span className="proj-mobile">{projectEmoji[run.project] || run.project}</span>
                <span className="proj-desktop">{run.project}</span>
              </td>
              <td style={TD_STYLE} title={run.task_source ? SOURCE_TOOLTIP[run.task_source] : undefined}>
                <span className="proj-mobile">{[...sourceLabel(run)][0] ?? '—'}</span>
                <span className="proj-desktop">{sourceLabel(run)}</span>
              </td>
              <td className="col-desktop" style={TD_STYLE}>{run.agent ?? '—'}</td>
              <td className="col-desktop" style={TD_STYLE}>
                {run.fallback_attempts
                  ? <span style={{ color: '#c80' }} title={`fallback from ${parseFallbacks(run.fallback_attempts) ?? '?'}`}>⤳ </span>
                  : null}
                {fmtModel(run.provider, run.model)}
              </td>
              <td style={TD_STYLE}>
                <span style={{ color: OUTCOME_COLOR[run.outcome ?? ''] ?? '#aaa', fontWeight: 'bold' }} title={run.outcome ? OUTCOME_TOOLTIP[run.outcome] : undefined}>
                  <span className="proj-desktop">{run.outcome ?? '—'}</span>
                  <span className="proj-mobile" style={{ fontWeight: 'bold', fontSize: '1rem' }}>
                    {run.outcome === 'success' ? '✔' : run.outcome === 'failure' ? '✖' : run.outcome ?? '—'}
                  </span>
                </span>
                {(run.thumbs_up ?? 0) > 0 && <span title={`${run.thumbs_up} thumbs up`}> 👍</span>}
                {(run.thumbs_down ?? 0) > 0 && <span title={`${run.thumbs_down} thumbs down`}> 👎</span>}
              </td>
              <td className="col-desktop" style={{ ...TD_STYLE, textAlign: 'right', color: '#aaa' }}>
                {fmtCost(run.total_cost_usd)}
              </td>
              <td className="col-desktop" style={{ ...TD_STYLE, textAlign: 'right', color: '#aaa' }}>
                {run.turns_used == null || run.turns_used === 0 ? '—' : run.turns_used}
              </td>
              <td className="col-desktop" style={{ ...TD_STYLE, whiteSpace: 'normal' }}>
                {run.outcome === 'failure'
                  ? <span style={{ color: '#c33' }}>{run.failure_reason ?? '—'}</span>
                  : run.item_url
                    ? <a href={run.item_url} target="_blank" rel="noreferrer"
                        style={{ color: '#5af', textDecoration: 'none' }}
                        onClick={(e) => e.stopPropagation()}
                      >{truncate(run.task_description ?? run.item_url, 45)}</a>
                    : <span style={{ color: '#888' }}>—</span>
                }
              </td>
            </tr>
          ))}
          {sorted.length === 0 && (
            <tr>
              <td colSpan={9} style={{ ...TD_STYLE, color: '#666', textAlign: 'center' }}>
                no runs
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
