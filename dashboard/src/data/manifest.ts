export interface Manifest {
  schema_version: number;
  db_filename: string;
  content_hash: string;
  generated_at: string;
  size_bytes: number;
  row_count: number;
}

export async function fetchManifest(): Promise<Manifest> {
  const res = await fetch('/manifest.json', { cache: 'no-cache' });
  if (!res.ok) throw new Error(`manifest fetch failed: ${res.status}`);
  return res.json() as Promise<Manifest>;
}
