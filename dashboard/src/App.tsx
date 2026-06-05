// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState } from 'react';
import { SqlJsDataSource } from './data/SqlJsDataSource';
import { fetchManifest } from './data/manifest';
import type { Manifest } from './data/manifest';
import type { Run, ProjectStats } from './data/DataSource';
import RunsTable from './components/RunsTable';
import RunDrawer from './components/RunDrawer';
import ProjectStatsView from './components/ProjectStats';

type Tab = 'runs' | 'stats';

type State =
  | { status: 'loading'; step: string }
  | { status: 'ready'; runs: Run[]; stats: ProjectStats[]; manifest: Manifest }
  | { status: 'error'; message: string };

const ds = new SqlJsDataSource();

export default function App() {
  const [state, setState] = useState<State>({ status: 'loading', step: 'manifest' });
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [tab, setTab] = useState<Tab>('runs');

  useEffect(() => {
    (async () => {
      try {
        setState({ status: 'loading', step: 'manifest' });
        const manifest = await fetchManifest();

        setState({ status: 'loading', step: 'database' });
        await ds.init(manifest);

        setState({ status: 'loading', step: 'runs' });
        const [runs, stats] = await Promise.all([
          ds.listRuns({ limit: 200 }),
          ds.projectStats(),
        ]);
        setState({ status: 'ready', runs, stats, manifest });
      } catch (err) {
        setState({ status: 'error', message: String(err) });
      }
    })();
  }, []);

  const TAB_STYLE = (active: boolean): React.CSSProperties => ({
    background: 'none',
    border: 'none',
    fontFamily: 'monospace',
    fontSize: '0.9rem',
    cursor: 'pointer',
    padding: '0.25rem 0',
    marginRight: '1.5rem',
    color: active ? '#ddd' : '#555',
    borderBottom: active ? '2px solid #aaa' : '2px solid transparent',
  });

  return (
    <div
      className="mobile-pad"
      style={{
        fontFamily: 'monospace',
        padding: '1.5rem',
        maxWidth: '1100px',
        margin: '0 auto',
        background: '#111',
        minHeight: '100vh',
        color: '#ddd',
      }}
    >
      <h1 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '0.25rem' }}>
        Labro Dashboard
      </h1>

      {state.status === 'loading' && (
        <p style={{ color: '#888' }}>Loading {state.step}…</p>
      )}
      {state.status === 'error' && (
        <p style={{ color: '#c00' }}>Error: {state.message}</p>
      )}
      {state.status === 'ready' && (
        <>
          <p style={{ color: '#666', fontSize: '0.8rem', marginBottom: '1rem' }}>
            {state.runs.length} runs · snapshot {state.manifest.generated_at} ·{' '}
            {(state.manifest.size_bytes / 1024).toFixed(1)} KB ·{' '}
            {state.manifest.content_hash.slice(0, 16)}
          </p>
          <div style={{ marginBottom: '1.25rem', borderBottom: '1px solid #2a2a2a' }}>
            <button style={TAB_STYLE(tab === 'runs')} onClick={() => setTab('runs')}>
              runs
            </button>
            <button style={TAB_STYLE(tab === 'stats')} onClick={() => setTab('stats')}>
              by project
            </button>
          </div>
          {tab === 'runs' && (
            <RunsTable runs={state.runs} onSelect={setSelectedRun} />
          )}
          {tab === 'stats' && (
            <ProjectStatsView stats={state.stats} />
          )}
        </>
      )}
      <RunDrawer run={selectedRun} onClose={() => setSelectedRun(null)} />
    </div>
  );
}
