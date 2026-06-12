// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState, useCallback } from 'react';
import { SqlJsDataSource } from './data/SqlJsDataSource';
import { fetchManifest } from './data/manifest';
import type { Manifest } from './data/manifest';
import type { Run, ProjectStats, RunFilter, FilterOptions } from './data/DataSource';
import RunsTable from './components/RunsTable';
import RunDrawer from './components/RunDrawer';
import ProjectStatsView from './components/ProjectStats';
import FilterBar from './components/FilterBar';
import ChartsView from './components/ChartsView';

type Tab = 'runs' | 'stats' | 'charts';

type State =
  | { status: 'loading'; step: string }
  | { status: 'ready'; runs: Run[]; stats: ProjectStats[]; manifest: Manifest; filterOptions: FilterOptions }
  | { status: 'error'; message: string };

const ds = new SqlJsDataSource();

export default function App() {
  const [state, setState] = useState<State>({ status: 'loading', step: 'manifest' });
  const [selectedRun, setSelectedRun] = useState<Run | null>(null);
  const [tab, setTab] = useState<Tab>('runs');
  const [filter, setFilter] = useState<RunFilter>({ outcomes: ['success', 'failure'] });
  const [filterOptions, setFilterOptions] = useState<FilterOptions>({ projects: [], agents: [], models: [], task_sources: [], outcomes: [] });

  const fetchData = useCallback(async (f: RunFilter) => {
    const [runs, stats] = await Promise.all([
      ds.listRuns({ ...f, limit: 200 }),
      ds.projectStats(f),
    ]);
    return { runs, stats };
  }, []);

  useEffect(() => {
    (async () => {
      try {
        setState({ status: 'loading', step: 'manifest' });
        const manifest = await fetchManifest();

        setState({ status: 'loading', step: 'database' });
        await ds.init(manifest);

        setState({ status: 'loading', step: 'filter options' });
        const filterOptions = await ds.getFilterOptions();

        setState({ status: 'loading', step: 'data' });
        const { runs, stats } = await fetchData({ outcomes: ['success', 'failure'] });
        setFilterOptions(filterOptions);
        setState({ status: 'ready', runs, stats, manifest, filterOptions });
      } catch (err) {
        setState({ status: 'error', message: String(err) });
      }
    })();
  }, [fetchData]);

  useEffect(() => {
    if (state.status === 'ready') {
      fetchData(filter).then(({ runs, stats }) => {
        setState({ ...state, runs, stats } as State);
      });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, fetchData]);

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
        maxWidth: '1600px',
        margin: '0 auto',
        background: '#111',
        minHeight: '100vh',
        color: '#ddd',
      }}
    >
      <h1 style={{ fontSize: '1.1rem', fontWeight: 'bold', marginBottom: '0.25rem' }}>
        {state.status === 'ready' && state.manifest.title ? state.manifest.title : 'Labro Dashboard'}
      </h1>
      <p style={{ color: '#666', fontSize: '0.8rem', marginBottom: '0.75rem' }}>
        Autonomous agent harness for unattended project tasks.{' '}
        Details: <a href="https://github.com/rssrn/labro" style={{ color: '#888' }}>github.com/rssrn/labro</a>
      </p>

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
          <FilterBar options={filterOptions} value={filter} onChange={setFilter} />
          <div style={{ marginBottom: '1.25rem', borderBottom: '1px solid #2a2a2a' }}>
            <button style={TAB_STYLE(tab === 'runs')} onClick={() => setTab('runs')}>
              runs
            </button>
            <button style={TAB_STYLE(tab === 'stats')} onClick={() => setTab('stats')}>
              by project
            </button>
            <button style={TAB_STYLE(tab === 'charts')} onClick={() => setTab('charts')}>
              charts
            </button>
          </div>
          {tab === 'runs' && (
            <RunsTable runs={state.runs} onSelect={setSelectedRun} />
          )}
          {tab === 'stats' && (
            <ProjectStatsView stats={state.stats} />
          )}
          {tab === 'charts' && (
            <ChartsView ds={ds} filter={filter} />
          )}
        </>
      )}
      <RunDrawer run={selectedRun} onClose={() => setSelectedRun(null)} />
    </div>
  );
}
