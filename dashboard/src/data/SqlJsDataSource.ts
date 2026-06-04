import initSqlJs from 'sql.js';
import type { Database } from 'sql.js';
import type { DataSource, ProjectStats, Run, RunFilter } from './DataSource';
import type { Manifest } from './manifest';

export class SqlJsDataSource implements DataSource {
  private db: Database | null = null;

  async init(manifest: Manifest): Promise<void> {
    const SQL = await initSqlJs({ locateFile: () => '/sql-wasm.wasm' });
    const res = await fetch('/' + manifest.db_filename);
    if (!res.ok) throw new Error(`db fetch failed: ${res.status}`);
    const buf = await res.arrayBuffer();
    this.db = new SQL.Database(new Uint8Array(buf));
  }

  async count(table: string): Promise<number> {
    const db = this._db();
    const result = db.exec(`SELECT COUNT(*) FROM ${table}`);
    const val = result[0]?.values[0]?.[0];
    return typeof val === 'number' ? val : 0;
  }

  async listRuns(filter: RunFilter = {}): Promise<Run[]> {
    const db = this._db();
    const conditions: string[] = [];
    const params: (string | number)[] = [];

    if (filter.project) {
      conditions.push('project = ?');
      params.push(filter.project);
    }
    if (filter.since) {
      conditions.push('started_at >= ?');
      params.push(filter.since);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
    const limitClause = filter.limit != null ? `LIMIT ${filter.limit}` : 'LIMIT 200';
    const sql = `
      SELECT run_id, project, started_at, task_source, provider, model,
             outcome, failure_reason, duration_s, total_cost_usd
      FROM runs
      ${where}
      ORDER BY started_at DESC
      ${limitClause}
    `;

    const result = db.exec(sql, params);
    if (!result[0]) return [];

    return result[0].values.map((row) => ({
      run_id: row[0] as string,
      project: row[1] as string,
      started_at: row[2] as string,
      task_source: row[3] as string | null,
      provider: row[4] as string | null,
      model: row[5] as string | null,
      outcome: row[6] as string | null,
      failure_reason: row[7] as string | null,
      duration_s: row[8] as number | null,
      total_cost_usd: row[9] as number | null,
    }));
  }

  async projectStats(_filter: RunFilter = {}): Promise<ProjectStats[]> {
    const db = this._db();
    const result = db.exec(`
      SELECT
        project,
        COUNT(*) AS total_runs,
        SUM(outcome = 'success')  AS success_count,
        SUM(outcome = 'failure')  AS failure_count,
        SUM(outcome = 'partial')  AS partial_count,
        SUM(outcome = 'skipped')  AS skipped_count,
        SUM(total_cost_usd)       AS total_cost_usd,
        AVG(total_cost_usd)       AS avg_cost_usd,
        AVG(duration_s)           AS avg_duration_s,
        AVG(turns_used)           AS avg_turns
      FROM runs
      GROUP BY project
      ORDER BY project
    `);
    if (!result[0]) return [];

    return result[0].values.map((row) => ({
      project: row[0] as string,
      total_runs: row[1] as number,
      success_count: row[2] as number,
      failure_count: row[3] as number,
      partial_count: row[4] as number,
      skipped_count: row[5] as number,
      total_cost_usd: row[6] as number | null,
      avg_cost_usd: row[7] as number | null,
      avg_duration_s: row[8] as number | null,
      avg_turns: row[9] as number | null,
    }));
  }

  private _db(): Database {
    if (!this.db) throw new Error('DataSource not initialised — call init() first');
    return this.db;
  }
}
