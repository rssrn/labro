"""Push run metrics to a Prometheus Pushgateway.

Called at the end of each live run when PUSHGATEWAY_URL is set.  Silent no-op
if the env var is absent or the push fails (metrics are best-effort).

Metrics pushed per run:
  labro_run_duration_seconds  — wall-clock run time (non-skipped runs only)
  labro_last_run_timestamp    — Unix timestamp of this run (all outcomes)

Both carry labels: project, outcome.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def push_run(
    *,
    project: str,
    outcome: str,
    duration_s: float,
    started_at_ts: float,
) -> None:
    """Push run metrics to Pushgateway.  Silent no-op if PUSHGATEWAY_URL is unset."""
    url = os.environ.get("PUSHGATEWAY_URL")
    if not url:
        return

    try:
        from prometheus_client import (  # type: ignore[import-not-found]  # optional dep
            CollectorRegistry,
            Gauge,
            push_to_gateway,
        )

        registry = CollectorRegistry()
        labels = ["project", "outcome"]

        ts_gauge = Gauge(
            "labro_last_run_timestamp",
            "Unix timestamp of the last Labro run",
            labels,
            registry=registry,
        )
        ts_gauge.labels(project=project, outcome=outcome).set(started_at_ts)

        if outcome != "skipped":
            dur_gauge = Gauge(
                "labro_run_duration_seconds",
                "Wall-clock duration of the last non-skipped Labro run",
                labels,
                registry=registry,
            )
            dur_gauge.labels(project=project, outcome=outcome).set(duration_s)

        push_to_gateway(url, job="labro", grouping_key={"project": project}, registry=registry)
        _log.debug("metrics pushed to %s (project=%s outcome=%s)", url, project, outcome)

    except ImportError:
        _log.warning("PUSHGATEWAY_URL set but prometheus-client not installed; skipping push")
    except Exception as exc:
        _log.warning("metrics push failed: %s", exc)
