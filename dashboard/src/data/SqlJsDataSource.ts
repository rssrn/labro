import type { Database } from 'sql.js';
import type { DataSource, ProjectStats, Run, RunFilter, TrendPoint, BreakdownEntry, EngagementRow, FilterOptions, DurationPoint } from './DataSource';
import type { Manifest } from './manifest';

export class SqlJsDataSource implements DataSource {
  private db: Database | null = null;

  async init(manifest: Manifest): Promise<void> {
    // Dynamic import handles CJS/ESM interop: Vite dev resolves the browser ESM build
    // which has no `default`; the prod bundle uses CJS with a default export.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const mod = await import('sql.js') as any;
    const initSqlJs = mod.default ?? mod;
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

  private _whereClause(filter: RunFilter): { clause: string; params: (string | number)[] } {
    const conditions: string[] = [];
    const params: (string | number)[] = [];

    if (filter.project) {
      conditions.push('r.project = ?');
      params.push(filter.project);
    }
    if (filter.since) {
      conditions.push('r.started_at >= ?');
      params.push(filter.since);
    }
    if (filter.model) {
      conditions.push('r.model = ?');
      params.push(filter.model);
    }
    if (filter.task_source) {
      conditions.push('r.task_source = ?');
      params.push(filter.task_source);
    }
    if (filter.outcomes && filter.outcomes.length > 0) {
      const placeholders = filter.outcomes.map(() => '?').join(', ');
      conditions.push(`r.outcome IN (${placeholders})`);
      params.push(...filter.outcomes);
    }

    return {
      clause: conditions.length ? `WHERE ${conditions.join(' AND ')}` : '',
      params,
    };
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
    if (filter.model) {
      conditions.push('model = ?');
      params.push(filter.model);
    }
    if (filter.task_source) {
      conditions.push('task_source = ?');
      params.push(filter.task_source);
    }
    if (filter.outcomes && filter.outcomes.length > 0) {
      const placeholders = filter.outcomes.map(() => '?').join(', ');
      conditions.push(`outcome IN (${placeholders})`);
      params.push(...filter.outcomes);
    }

    const where = conditions.length ? `WHERE ${conditions.join(' AND ')}` : '';
    const limitClause = filter.limit != null ? `LIMIT ${filter.limit}` : 'LIMIT 200';
    const sql = `
      SELECT run_id, project, started_at, ended_at,
             task_source, task_description, item_url, trigger_label,
             agent, provider, model, effort,
             outcome, failure_reason, duration_s, total_cost_usd, turns_used,
             input_tokens, output_tokens, cache_read_tokens, cache_write_tokens,
             summary, actions_taken, wip_branch_url, chosen_perspective
      FROM runs
      ${where}
      ORDER BY started_at DESC
      ${limitClause}
    `;

    const result = db.exec(sql, params);
    if (!result[0]) return [];

    return result[0].values.map((row) => ({
      run_id:             row[0]  as string,
      project:            row[1]  as string,
      started_at:         row[2]  as string,
      ended_at:           row[3]  as string | null,
      task_source:        row[4]  as string | null,
      task_description:   row[5]  as string | null,
      item_url:           row[6]  as string | null,
      trigger_label:      row[7]  as string | null,
      agent:              row[8]  as string | null,
      provider:           row[9]  as string | null,
      model:              row[10] as string | null,
      effort:             row[11] as string | null,
      outcome:            row[12] as string | null,
      failure_reason:     row[13] as string | null,
      duration_s:         row[14] as number | null,
      total_cost_usd:     row[15] as number | null,
      turns_used:         row[16] as number | null,
      input_tokens:       row[17] as number | null,
      output_tokens:      row[18] as number | null,
      cache_read_tokens:  row[19] as number | null,
      cache_write_tokens: row[20] as number | null,
      summary:            row[21] as string | null,
      actions_taken:      row[22] as string | null,
      wip_branch_url:     row[23] as string | null,
      chosen_perspective: row[24] as string | null,
    }));
  }

  async projectStats(filter: RunFilter = {}): Promise<ProjectStats[]> {
    const db = this._db();
    const { clause, params } = this._whereClause(filter);
    const sql = `
      SELECT
        project,
        COUNT(*) AS total_runs,
        SUM(outcome = 'success')  AS success_count,
        SUM(outcome = 'failure')  AS failure_count,
        SUM(outcome = 'partial')  AS partial_count,
        SUM(outcome = 'skipped')  AS skipped_count,
        SUM(total_cost_usd)       AS total_cost_usd,
        AVG(total_cost_usd)       AS avg_cost_usd,
        AVG(COALESCE(duration_s, CASE WHEN ended_at IS NOT NULL THEN (strftime('%s', ended_at) - strftime('%s', started_at)) END)) AS avg_duration_s,
        AVG(turns_used)           AS avg_turns
      FROM runs
      ${clause.replace(/r\./g, '')}
      GROUP BY project
      ORDER BY project
    `;
    const result = db.exec(sql, params);
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

  async getFilterOptions(): Promise<FilterOptions> {
    const db = this._db();

    const projects = db.exec('SELECT DISTINCT project FROM runs ORDER BY project');
    const models = db.exec('SELECT DISTINCT model FROM runs WHERE model IS NOT NULL ORDER BY model');
    const taskSources = db.exec('SELECT DISTINCT task_source FROM runs WHERE task_source IS NOT NULL ORDER BY task_source');
    const outcomes = db.exec("SELECT DISTINCT outcome FROM runs WHERE outcome IS NOT NULL ORDER BY outcome");

    const extract = (r: typeof projects) =>
      r[0]?.values.map((v) => v[0] as string) ?? [];

    return {
      projects: extract(projects),
      models: extract(models),
      task_sources: extract(taskSources),
      outcomes: extract(outcomes),
    };
  }

  async trend(filter: RunFilter = {}): Promise<TrendPoint[]> {
    const db = this._db();
    const { clause, params } = this._whereClause(filter);
    const sql = `
      SELECT date(r.started_at) as date,
        SUM(r.total_cost_usd) as cost_usd,
        SUM(r.input_tokens) as input_tokens,
        SUM(r.output_tokens) as output_tokens,
        SUM(r.cache_read_tokens) as cache_read_tokens,
        SUM(r.cache_write_tokens) as cache_write_tokens,
        SUM(CASE WHEN r.outcome='success' THEN 1 ELSE 0 END) as success,
        SUM(CASE WHEN r.outcome='failure' THEN 1 ELSE 0 END) as failure,
        SUM(CASE WHEN r.outcome='partial' THEN 1 ELSE 0 END) as partial,
        SUM(CASE WHEN r.outcome='skipped' THEN 1 ELSE 0 END) as skipped
      FROM runs r
      ${clause}
      GROUP BY date(r.started_at)
      ORDER BY date
    `;
    const result = db.exec(sql, params);
    if (!result[0]) return [];

    return result[0].values.map((row) => ({
      date: row[0] as string,
      cost_usd: row[1] as number,
      input_tokens: row[2] as number,
      output_tokens: row[3] as number,
      cache_read_tokens: row[4] as number,
      cache_write_tokens: row[5] as number,
      success: row[6] as number,
      failure: row[7] as number,
      partial: row[8] as number,
      skipped: row[9] as number,
    }));
  }

  async modelBreakdown(filter: RunFilter = {}): Promise<BreakdownEntry[]> {
    const db = this._db();
    const { clause, params } = this._whereClause(filter);
    const sql = `
      SELECT r.model AS label, COUNT(*) as count
      FROM runs r
      ${clause}
      GROUP BY r.model
      ORDER BY count DESC
    `;
    const result = db.exec(sql, params);
    if (!result[0]) return [];
    return result[0].values.map((row) => ({ label: row[0] as string, count: row[1] as number }));
  }

  async taskSourceBreakdown(filter: RunFilter = {}): Promise<BreakdownEntry[]> {
    const db = this._db();
    const { clause, params } = this._whereClause(filter);
    const sql = `
      SELECT r.task_source AS label, COUNT(*) as count
      FROM runs r
      ${clause}
      GROUP BY r.task_source
      ORDER BY count DESC
    `;
    const result = db.exec(sql, params);
    if (!result[0]) return [];
    return result[0].values.map((row) => ({ label: row[0] as string, count: row[1] as number }));
  }

  async perspectiveBreakdown(filter: RunFilter = {}): Promise<BreakdownEntry[]> {
    const db = this._db();
    const { clause, params } = this._whereClause(filter);
    const sql = `
      SELECT r.chosen_perspective AS label, COUNT(*) as count
      FROM runs r
      ${clause}
      GROUP BY r.chosen_perspective
      ORDER BY count DESC
    `;
    const result = db.exec(sql, params);
    if (!result[0]) return [];
    return result[0].values.map((row) => ({ label: row[0] as string, count: row[1] as number }));
  }

  async engagementSignals(filter: RunFilter = {}): Promise<EngagementRow[]> {
    const db = this._db();
    const { clause, params } = this._whereClause(filter);
    const sql = `
      SELECT it.outcome_state,
        COUNT(*) as count,
        SUM(it.thumbs_up) as thumbs_up,
        SUM(it.thumbs_down) as thumbs_down,
        SUM(it.follow_up_commits) as follow_up_commits
      FROM items_touched it
      JOIN runs r ON it.run_id = r.run_id
      ${clause}
      GROUP BY it.outcome_state
      ORDER BY count DESC
    `;
    const result = db.exec(sql, params);
    if (!result[0]) return [];

    return result[0].values.map((row) => ({
      outcome_state: row[0] as string,
      count: row[1] as number,
      thumbs_up: row[2] as number,
      thumbs_down: row[3] as number,
      follow_up_commits: row[4] as number,
    }));
  }

  async durationTrend(filter: RunFilter = {}): Promise<DurationPoint[]> {
    const db = this._db();
    const { clause, params } = this._whereClause(filter);
    const sql = `
      SELECT date(r.started_at) as date,
        r.model,
        AVG(COALESCE(r.duration_s, CASE WHEN r.ended_at IS NOT NULL THEN (strftime('%s', r.ended_at) - strftime('%s', r.started_at)) END)) as avg_duration_s
      FROM runs r
      ${clause}
      GROUP BY date(r.started_at), r.model
      ORDER BY date, r.model
    `;
    const result = db.exec(sql, params);
    if (!result[0]) return [];

    return result[0].values.map((row) => ({
      date: row[0] as string,
      model: row[1] as string,
      avg_duration_s: row[2] as number,
    }));
  }

  private _db(): Database {
    if (!this.db) throw new Error('DataSource not initialised — call init() first');
    return this.db;
  }
}
