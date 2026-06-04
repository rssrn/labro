import { useEffect, useState } from 'react';
import { SqlJsDataSource } from './data/SqlJsDataSource';
import { fetchManifest } from './data/manifest';
import type { Manifest } from './data/manifest';

type State =
  | { status: 'loading'; step: string }
  | { status: 'ready'; runCount: number; manifest: Manifest }
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

        const runCount = await ds.count('runs');
        setState({ status: 'ready', runCount, manifest });
      } catch (err) {
        setState({ status: 'error', message: String(err) });
      }
    })();
  }, []);

  return (
    <div style={{ fontFamily: 'monospace', padding: '2rem', maxWidth: '800px', margin: '0 auto' }}>
      <h1 style={{ fontSize: '1.25rem', fontWeight: 'bold', marginBottom: '1rem' }}>
        Labro Dashboard
      </h1>
      {state.status === 'loading' && (
        <p style={{ color: '#888' }}>Loading {state.step}…</p>
      )}
      {state.status === 'error' && (
        <p style={{ color: '#c00' }}>Error: {state.message}</p>
      )}
      {state.status === 'ready' && (
        <div>
          <p>
            <strong>{state.runCount}</strong> runs · snapshot{' '}
            <span style={{ color: '#888' }}>{state.manifest.generated_at}</span>
          </p>
          <p style={{ color: '#888', fontSize: '0.85rem' }}>
            {(state.manifest.size_bytes / 1024).toFixed(1)} KB ·{' '}
            {state.manifest.content_hash.slice(0, 16)}
          </p>
        </div>
      )}
    </div>
  );
}
