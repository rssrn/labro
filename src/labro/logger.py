"""Execution-record writer for the Labro run loop.

``write_run`` is a pure write helper — it does not manage locks.
Lock release belongs in ``cli.py``'s ``finally`` block.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import json
import sqlite3

from labro.models import AgentConfig, AgentResult, Task


def write_run(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    project: str,
    task: Task | None,
    agent_cfg: AgentConfig | None,
    agent_result: AgentResult | None,
    outcome: str,
    failure_reason: str | None,
    started_at: str,
    ended_at: str,
) -> None:
    """Write a single run record to the ``runs`` table.

    Both *task* and *agent_result* may be ``None`` (e.g. for skipped runs
    where no task was found).  ``outcome`` must be one of ``"success"``,
    ``"failure"``, or ``"skipped"`` — the CHECK constraint on the ``runs``
    table will reject any other value.

    ``AgentResult.outcome = "partial"`` must be mapped to ``"failure"`` by
    the caller before passing *outcome* here (ARCHITECTURE line 263).

    Args:
        conn: Open database connection (WAL mode, created by ``store.open_db``).
        run_id: UUID v4 string generated for this run.
        project: Project name matching the ``labro.toml`` stanza.
        task: Resolved :class:`~labro.models.Task`, or ``None`` for skipped runs.
        agent_cfg: Resolved :class:`~labro.models.AgentConfig`, or ``None``.
        agent_result: :class:`~labro.models.AgentResult` from the agent
            subprocess, or ``None`` if the agent was never invoked.
        outcome: ``"success"``, ``"failure"``, or ``"skipped"``.
        failure_reason: Human-readable failure / skip description, or ``None``.
        started_at: ISO 8601 UTC timestamp for run start.
        ended_at: ISO 8601 UTC timestamp for run end.
    """
    # Derive duration_s from agent_result.duration_ms when available.
    duration_s: float | None = None
    if agent_result is not None and agent_result.duration_ms:
        duration_s = agent_result.duration_ms / 1000.0

    # Serialise actions_taken as a JSON array string (display only — not aggregated).
    actions_taken_json: str | None = None
    if agent_result is not None:
        actions_taken_json = json.dumps(agent_result.actions_taken)

    # Pre-extract optional fields to keep the INSERT dict within line-length limits.
    ar = agent_result
    with conn:
        conn.execute(
            """
            INSERT INTO runs (
                run_id, project,
                task_source, task_description, item_url, trigger_label,
                agent, model,
                started_at, ended_at, duration_s,
                outcome,
                turns_used, total_cost_usd,
                input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens,
                summary, actions_taken, failure_reason
            ) VALUES (
                :run_id, :project,
                :task_source, :task_description, :item_url, :trigger_label,
                :agent, :model,
                :started_at, :ended_at, :duration_s,
                :outcome,
                :turns_used, :total_cost_usd,
                :input_tokens, :output_tokens,
                :cache_read_tokens, :cache_write_tokens,
                :summary, :actions_taken, :failure_reason
            )
            """,
            {
                "run_id": run_id,
                "project": project,
                "task_source": task.source if task is not None else None,
                "task_description": task.description.splitlines()[0] if task is not None else None,
                "item_url": task.item_url if task is not None else None,
                "trigger_label": task.source_label if task is not None else None,
                "agent": agent_cfg.agent if agent_cfg is not None else None,
                "model": agent_cfg.model if agent_cfg is not None else None,
                "started_at": started_at,
                "ended_at": ended_at,
                "duration_s": duration_s,
                "outcome": outcome,
                "turns_used": ar.num_turns if ar is not None else None,
                "total_cost_usd": ar.total_cost_usd if ar is not None else None,
                "input_tokens": ar.input_tokens if ar is not None else None,
                "output_tokens": ar.output_tokens if ar is not None else None,
                "cache_read_tokens": ar.cache_read_tokens if ar is not None else None,
                "cache_write_tokens": ar.cache_write_tokens if ar is not None else None,
                "summary": ar.summary if ar is not None else None,
                "actions_taken": actions_taken_json,
                "failure_reason": failure_reason,
            },
        )
