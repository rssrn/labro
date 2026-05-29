"""Shared pytest fixtures for the Labro test suite."""
# Fixtures that span multiple test modules will live here.
# Module-specific fixtures belong in their respective test files.

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Skip the coverage floor when running a subset of test files so that
    # `pytest tests/test_foo.py` doesn't fail due to partial coverage.
    args = config.args
    if args and any(arg.endswith(".py") or ("tests/" in arg and arg != "tests/") for arg in args):
        cov_plugin = config.pluginmanager.get_plugin("_cov")
        if cov_plugin is not None:
            cov_plugin.options.cov_fail_under = 0.0
