# Labro Dashboard

Read-only SPA that loads a published snapshot of `labro.db` client-side via sql.js and renders run history and per-project stats. No server; no live link to the harness.

## Local dev (against live data)

The Vite dev server proxies `/manifest.json` and `/db/*` to `https://labro.rossarnold.uk`, so local dev works against the real published snapshot with no CORS issues.

```bash
cd dashboard
npm install
npm run dev        # http://localhost:5173
```

## Build

```bash
npm run build      # output → dashboard/dist/
```

The `postinstall` hook copies `sql-wasm.wasm` into `public/` automatically.

## Deploy

Building and uploading to R2 is handled by the `dashboard-publish.yml` workflow in the config repo. The workflow is triggered automatically when `dashboard/**` changes on the labro `main` branch (via `dashboard-dispatch.yml` → repository dispatch) and can also be run manually.

See the main [README.md](../README.md#metrics-dashboard) for the full setup guide.

## Data layer

All database access goes through the `DataSource` interface (`src/data/DataSource.ts`). The live implementation is `SqlJsDataSource` (`src/data/SqlJsDataSource.ts`), which downloads the whole `.db` snapshot and runs SQL client-side via `sql.js`.

The interface is the upgrade seam: if the snapshot ever grows beyond ~10 MB, switching to `sql.js-httpvfs` (HTTP-Range paging) only requires a new `DataSource` implementation — nothing else changes.

```typescript
interface DataSource {
  init(manifest: Manifest): Promise<void>;
  count(table: string): Promise<number>;
  listRuns(filter?: RunFilter): Promise<Run[]>;
  projectStats(filter?: RunFilter): Promise<ProjectStats[]>;
}
```

## Tech stack

- React 18 + Vite + TypeScript
- [sql.js](https://github.com/sql-js/sql.js) — SQLite compiled to WASM
- Dark monospace UI (no component library)
