"""Tests for the ``labro gen-crontab`` CLI subcommand.

@author Claude Sonnet 4.6 Anthropic
"""

from __future__ import annotations

import argparse
from pathlib import Path
from unittest.mock import patch

import pytest

from labro.cli import _cmd_gen_crontab
from labro.config.schema import (
    DashboardConfig,
    DefaultsConfig,
    DigestConfig,
    GhLabelSource,
    LabelRule,
    LabroConfig,
    ProjectConfig,
    SignalsConfig,
)


def _make_project(name: str, cron: str = "0 9 * * *", enabled: bool = True) -> ProjectConfig:
    return ProjectConfig(
        name=name,
        repo=f"org/{name}",
        cron=cron,
        enabled=enabled,
        task_sources=[
            GhLabelSource(
                type="gh-label", label_rules=[LabelRule(label="ai-dev", done_label="ai-dev-done")]
            )
        ],
    )


def _run(config: LabroConfig, capsys: pytest.CaptureFixture[str]) -> str:
    args = argparse.Namespace(config=Path("labro.toml"))
    with patch("labro.cli.load_config", return_value=config):
        rc = _cmd_gen_crontab(args)
    assert rc == 0
    return capsys.readouterr().out


def _make_config(
    projects: list[ProjectConfig],
    digest_enabled: bool = False,
    digest_cron: str = "0 8 * * *",
    dashboard_enabled: bool = False,
    dashboard_cron: str = "17 * * * *",
    signals_enabled: bool = True,
    signals_cron: str = "0 6 * * *",
) -> LabroConfig:
    return LabroConfig(
        digest=DigestConfig(enabled=digest_enabled, cron=digest_cron),
        dashboard=DashboardConfig(
            enabled=dashboard_enabled,
            cron=dashboard_cron,
        ),
        signals=SignalsConfig(enabled=signals_enabled, cron=signals_cron),
        defaults=DefaultsConfig(),
        projects=projects,
    )


# ── Tests ──────────────────────────────────────────────────────────────────────


def test_enabled_project_appears(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config([_make_project("myproject", cron="0 9 * * *")])
    out = _run(config, capsys)
    assert "myproject" in out
    assert "0 9 * * *" in out
    assert "labro run myproject" in out


def test_disabled_project_absent(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        [
            _make_project("active", cron="0 9 * * *", enabled=True),
            _make_project("inactive", cron="0 10 * * *", enabled=False),
        ]
    )
    out = _run(config, capsys)
    assert "active" in out
    assert "inactive" not in out


def test_digest_absent_when_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config([_make_project("proj")], digest_enabled=False)
    out = _run(config, capsys)
    assert "labro digest" not in out


def test_digest_present_when_enabled(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config([_make_project("proj")], digest_enabled=True, digest_cron="0 8 * * *")
    out = _run(config, capsys)
    assert "labro digest" in out
    assert "0 8 * * *" in out


def test_dashboard_absent_when_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config([_make_project("proj")], dashboard_enabled=False)
    out = _run(config, capsys)
    assert "labro publish-db" not in out


def test_dashboard_present_when_enabled(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        [_make_project("proj")],
        dashboard_enabled=True,
        dashboard_cron="17 * * * *",
    )
    out = _run(config, capsys)
    assert "labro publish-db" in out
    assert "17 * * * *" in out


def test_signals_absent_when_disabled(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config([_make_project("proj")], signals_enabled=False)
    out = _run(config, capsys)
    assert "labro collect-signals" not in out


def test_signals_present_when_enabled(capsys: pytest.CaptureFixture[str]) -> None:
    config = _make_config(
        [_make_project("proj")],
        signals_enabled=True,
        signals_cron="0 7,18 * * *",
    )
    out = _run(config, capsys)
    assert "labro collect-signals" in out
    assert "0 7,18 * * *" in out
