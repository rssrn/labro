// @author Claude Sonnet 4.6 Anthropic
import { useState, useRef, useEffect } from 'react';
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

function OutcomeMultiSelect({
  outcomes,
  selected,
  onChange,
}: {
  outcomes: string[];
  selected: string[];
  onChange: (v: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    function handle(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    document.addEventListener('mousedown', handle);
    return () => document.removeEventListener('mousedown', handle);
  }, [open]);

  const allSelected = selected.length === 0 || selected.length === outcomes.length;
  const label = allSelected ? 'All outcomes' : selected.join('+');

  function toggle(o: string) {
    if (selected.includes(o)) {
      onChange(selected.filter((x) => x !== o));
    } else {
      onChange([...selected, o]);
    }
  }

  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        style={{ ...SELECT_STYLE, cursor: 'pointer' }}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="listbox"
        aria-label="Outcomes"
      >
        {label} ▾
      </button>
      {open && (
        <div
          role="listbox"
          aria-multiselectable="true"
          aria-label="Outcomes"
          style={{
            position: 'absolute',
            top: 'calc(100% + 2px)',
            left: 0,
            background: '#1a1a1a',
            border: '1px solid #333',
            borderRadius: '3px',
            padding: '0.25rem 0',
            zIndex: 100,
            minWidth: '130px',
          }}
        >
          {outcomes.map((o) => (
            <label
              key={o}
              style={{
                display: 'flex',
                gap: '0.4rem',
                alignItems: 'center',
                padding: '0.2rem 0.6rem',
                cursor: 'pointer',
                color: '#ddd',
                fontSize: '0.8rem',
                fontFamily: 'monospace',
              }}
            >
              <input
                type="checkbox"
                checked={selected.includes(o)}
                onChange={() => toggle(o)}
                style={{ accentColor: '#aaa' }}
              />
              {o}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

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
      <select
        aria-label="Time range"
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
        aria-label="Project"
        style={SELECT_STYLE}
        value={value.project ?? ''}
        onChange={(e) => set('project', e.target.value || undefined)}
      >
        <option value="">All projects</option>
        {options.projects.map((p) => (
          <option key={p} value={p}>{p}</option>
        ))}
      </select>
      <OutcomeMultiSelect
        outcomes={options.outcomes}
        selected={value.outcomes ?? []}
        onChange={(v) => set('outcomes', v.length === 0 ? undefined : v)}
      />
      <select
        aria-label="Task source"
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
        aria-label="Agent"
        style={SELECT_STYLE}
        value={value.agent ?? ''}
        onChange={(e) => set('agent', e.target.value || undefined)}
      >
        <option value="">All agents</option>
        {options.agents.map((a) => (
          <option key={a} value={a}>{a}</option>
        ))}
      </select>
      <select
        aria-label="Model"
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
