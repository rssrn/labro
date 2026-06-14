// @author Claude Sonnet 4.6 Anthropic
import { useEffect } from 'react';
import type { Run } from '../data/DataSource';
import { OUTCOME_COLOR, OUTCOME_TOOLTIP, SOURCE_TOOLTIP } from '../constants';

interface Props {
  run: Run | null;
  onClose: () => void;
}

function fmtSecs(s: number): string {
  if (s < 60) return s >= 9.5 ? `${Math.round(s)}s` : `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function fmtDuration(duration_s: number | null, started_at: string, ended_at: string | null): string {
  if (duration_s != null) return `${fmtSecs(duration_s)} (reported by agent)`;
  if (ended_at) {
    const delta = (new Date(ended_at).getTime() - new Date(started_at).getTime()) / 1000;
    if (!isNaN(delta)) return `${fmtSecs(delta)} (wall clock)`;
  }
  return '—';
}

function fmtCost(usd: number | null): string {
  if (usd == null) return '—';
  if (usd <= 0) return '$0.0000';
  if (usd < 0.01) return '<$0.01';
  return `$${usd.toFixed(4)}`;
}

function fmtTokens(n: number | null): string {
  if (n == null) return '—';
  return n.toLocaleString();
}

// Compact two-column grid cell: label above value
function Cell({ label, title, children }: { label: string; title?: string; children: React.ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.2rem' }} title={title}>
      <span style={{ color: '#555', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.07em', cursor: title ? 'help' : undefined }}>
        {label}
      </span>
      <span style={{ color: '#ddd', fontSize: '0.85rem' }}>{children}</span>
    </div>
  );
}

// Full-width labeled block for prose / lists
function Block({ label, subtitle, children }: { label: string; subtitle?: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: '1.1rem' }}>
      <div style={{ color: '#555', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: subtitle ? '0.15rem' : '0.35rem' }}>
        {label}
      </div>
      {subtitle && (
        <div style={{ color: '#444', fontSize: '0.7rem', marginBottom: '0.35rem', fontStyle: 'italic' }}>
          {subtitle}
        </div>
      )}
      <div style={{ color: '#ccc', fontSize: '0.82rem', lineHeight: 1.55 }}>{children}</div>
    </div>
  );
}

function Divider() {
  return <div style={{ borderTop: '1px solid #252525', margin: '1rem 0' }} />;
}

export default function RunDrawer({ run, onClose }: Props) {
  useEffect(() => {
    if (!run) return;
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [run, onClose]);

  useEffect(() => {
    document.body.style.overflow = run ? 'hidden' : '';
    return () => { document.body.style.overflow = ''; };
  }, [run]);

  if (!run) return null;

  const outcomeColor = OUTCOME_COLOR[run.outcome ?? ''] ?? '#aaa';

  let actionItems: string[] = [];
  if (run.actions_taken) {
    try { actionItems = JSON.parse(run.actions_taken); }
    catch { actionItems = [run.actions_taken]; }
  }

  return (
    <>
      {/* Backdrop */}
      <div
        onClick={onClose}
        style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', zIndex: 100 }}
      />

      {/* Panel */}
      <div className="run-drawer" style={{
        position: 'fixed', top: 0, right: 0, bottom: 0,
        zIndex: 101,
        background: '#161616',
        borderLeft: '1px solid #2a2a2a',
        overflowY: 'auto',
        fontFamily: 'monospace',
      }}>
        {/* Header bar — project + outcome badge + close */}
        <div style={{
          display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start',
          padding: '1.4rem 1.5rem 1rem',
          borderBottom: '1px solid #222',
          position: 'sticky', top: 0,
          background: '#161616',
          zIndex: 1,
        }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.6rem', flexWrap: 'wrap' }}>
              <span style={{ fontWeight: 'bold', fontSize: '1rem', color: '#eee', letterSpacing: '-0.01em' }}>
                {run.project}
              </span>
              <span
                title={run.outcome ? OUTCOME_TOOLTIP[run.outcome] : undefined}
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: '0.3rem',
                  color: outcomeColor,
                  background: `${outcomeColor}18`,
                  border: `1px solid ${outcomeColor}44`,
                  borderRadius: '3px',
                  padding: '0.1rem 0.45rem',
                  fontSize: '0.7rem',
                  fontWeight: 'bold',
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                  cursor: 'help',
                }}>
                <span style={{ width: '5px', height: '5px', borderRadius: '50%', background: outcomeColor, display: 'inline-block' }} />
                {run.outcome ?? '—'}
              </span>
            </div>
            <div style={{ color: '#444', fontSize: '0.7rem', marginTop: '0.25rem', fontVariantNumeric: 'tabular-nums' }}>
              {run.run_id}
            </div>
          </div>
          <button
            onClick={onClose}
            aria-label="Close"
            style={{
              background: 'none', border: '1px solid #333',
              color: '#666', cursor: 'pointer',
              fontSize: '1rem', lineHeight: 1,
              padding: '0.25rem 0.5rem',
              marginLeft: '1rem', flexShrink: 0,
              borderRadius: '3px',
            }}
          >
            esc
          </button>
        </div>

        <div style={{ padding: '1.25rem 1.5rem 2.5rem' }}>

          {/* 1. Task — what was the job */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
            <Cell label="source" title={run.task_source ? SOURCE_TOOLTIP[run.task_source] : undefined}>{run.task_source ?? '—'}</Cell>
            {run.trigger_label
              ? <Cell label="trigger" title="The GitHub label that triggered this gh-label run.">{run.trigger_label}</Cell>
              : <div />
            }
          </div>
          {(run.task_description || run.item_url) && (
            <Block label="description">
              {run.task_description
                ? run.item_url
                  ? <a href={run.item_url} target="_blank" rel="noreferrer"
                      style={{ color: '#5af', textDecoration: 'none', whiteSpace: 'pre-wrap' }}>
                      {run.task_description}
                    </a>
                  : <span style={{ whiteSpace: 'pre-wrap' }}>{run.task_description}</span>
                : <a href={run.item_url!} target="_blank" rel="noreferrer"
                    style={{ color: '#5af', textDecoration: 'none', wordBreak: 'break-all' }}>
                    {run.item_url}
                  </a>
              }
            </Block>
          )}
          {run.wip_branch_url && (
            <Block label="wip branch" subtitle="Run was cut short (partial) — in-progress changes were pushed here for handover.">
              <a href={run.wip_branch_url} target="_blank" rel="noreferrer"
                style={{ color: '#5af', textDecoration: 'none', wordBreak: 'break-all' }}>
                {run.wip_branch_url}
              </a>
            </Block>
          )}

          <Divider />

          {/* 2. Output — what the agent did */}
          {run.summary && (
            <Block label="agent's summary">
              <span style={{ whiteSpace: 'pre-wrap' }}>{run.summary}</span>
            </Block>
          )}
          {actionItems.length > 0 && (
            <Block label="actions taken by agent">
              <ul style={{ margin: 0, paddingLeft: '1.1em' }}>
                {actionItems.map((item, i) => (
                  <li key={i} style={{ marginBottom: '0.3rem', color: '#bbb' }}>{item}</li>
                ))}
              </ul>
            </Block>
          )}
          {run.failure_reason && (
            <Block label="failure reason">
              <span style={{ color: '#d88', whiteSpace: 'pre-wrap' }}>{run.failure_reason}</span>
            </Block>
          )}

          <Divider />

          {/* 3. Agent + Cost */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem', marginBottom: '1rem' }}>
            <Cell label="agent">{run.agent ?? '—'}</Cell>
            <Cell label="total cost">{fmtCost(run.total_cost_usd)}</Cell>
            <Cell label="model">{run.model ?? '—'}</Cell>
            <Cell label="turns" title="Agent conversation turns used. Capped by max_turns; if turns = max and outcome = partial, the run was cut short.">{run.turns_used ? run.turns_used : <span style={{ color: '#555' }}>Not reported</span>}</Cell>
            {run.provider && <Cell label="provider">{run.provider}</Cell>}
            {run.effort && <Cell label="effort" title="Agent reasoning depth. Higher effort = more thorough but slower and costlier.">{run.effort}</Cell>}
          </div>

          {run.fallback_attempts && (() => {
            let attempts: { slug: string; reason: string }[] = [];
            try { attempts = JSON.parse(run.fallback_attempts); } catch { /* ignore */ }
            return attempts.length > 0 ? (
              <Block label="fallback attempts" subtitle="Earlier models in the chain failed; last successful model is shown above.">
                <ul style={{ margin: 0, paddingLeft: '1.1em' }}>
                  {attempts.map((a, i) => (
                    <li key={i} style={{ marginBottom: '0.25rem', color: '#c80' }}>
                      {a.slug}<span style={{ color: '#888' }}> — {a.reason}</span>
                    </li>
                  ))}
                </ul>
              </Block>
            ) : null;
          })()}

          {/* 4. Token tiles */}
          {(run.input_tokens != null || run.output_tokens != null) && (
            <div style={{ marginBottom: '0.5rem' }}>
              <div style={{ color: '#555', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.07em', marginBottom: '0.15rem' }}>
                tokens
              </div>
              <div style={{ color: '#444', fontSize: '0.7rem', fontStyle: 'italic' }}>
                cache read = reused from prior run (reduces cost); cache write = stored this run for future reuse
              </div>
            </div>
          )}
          {(run.input_tokens != null || run.output_tokens != null) && (
            <div style={{
              display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr',
              gap: '0.5rem', marginBottom: '0.5rem',
            }}>
              {([
                ['input', run.input_tokens],
                ['output', run.output_tokens],
                ['cache read', run.cache_read_tokens],
                ['cache write', run.cache_write_tokens],
              ] as [string, number | null][]).map(([label, val]) => (
                <div key={label} style={{
                  background: '#1d1d1d', border: '1px solid #272727',
                  borderRadius: '4px', padding: '0.5rem 0.6rem',
                }}>
                  <div style={{ color: '#4a4a4a', fontSize: '0.62rem', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: '0.25rem' }}>
                    {label}
                  </div>
                  <div style={{ color: val != null ? '#aaa' : '#333', fontSize: '0.82rem', fontVariantNumeric: 'tabular-nums' }}>
                    {fmtTokens(val)}
                  </div>
                </div>
              ))}
            </div>
          )}

          <Divider />

          {/* 5. Timing — already visible in table, least urgent */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '1rem' }}>
            <Cell label="started">{run.started_at.replace('T', ' ').slice(0, 19)}Z</Cell>
            <Cell label="ended">{run.ended_at ? run.ended_at.replace('T', ' ').slice(0, 19) + 'Z' : '—'}</Cell>
            <Cell label="duration">{fmtDuration(run.duration_s, run.started_at, run.ended_at)}</Cell>
          </div>

          {run.chosen_perspective && (
            <>
              <Divider />
              <Block label="perspective" subtitle="Randomly chosen lens injected into the proactive-improvement prompt to guide the agent's suggestion.">{run.chosen_perspective}</Block>
            </>
          )}
        </div>
      </div>
    </>
  );
}
