// @author Claude Sonnet 4.6 Anthropic
import { useEffect, useState } from 'react';
import { SqlJsDataSource } from './data/SqlJsDataSource';
import { fetchManifest } from './data/manifest';
import type { Manifest } from './data/manifest';
import type { Run } from './data/DataSource';
import RunsTable from './components/RunsTable';

type State =
  | { status: 'loading'; step: string }
  | { status: 'ready'; runs: Run[]; manifest: Manifest }
  | { status: 'error'; message: string };

const ds = new SqlJsDataSource();

export default function App() {
  const [state, setState] = useState<State>({ status: 'loading', step: 'manifest' });

  useEffect(() => {
    (async () => {
      try {
        setState({ status: 'loading', step: 'manifest' });
        const manifest = await fetchManifest();

        setState({ status: 'loading', step: 'database' });
        await ds.init(manifest);

        setState({ status: 'loading', step: 'runs' });
        const runs = await ds.listRuns({ limit: 200 });
        setState({ status: 'ready', runs, manifest });
      } catch (err) {
        setState({ status: 'error', message: String(err) });
      }
    })();
  }, []);

  return (
    <div
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
          <p style={{ color: '#666', fontSize: '0.8rem', marginBottom: '1.25rem' }}>
            {state.runs.length} runs · snapshot {state.manifest.generated_at} ·{' '}
            {(state.manifest.size_bytes / 1024).toFixed(1)} KB ·{' '}
            {state.manifest.content_hash.slice(0, 16)}
          </p>
          <RunsTable runs={state.runs} />
        </>
      )}
    </div>
  );
}
