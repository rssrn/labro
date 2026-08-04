"""Shared pytest fixtures for the Labro test suite."""
# Fixtures that span multiple test modules will live here.
# Module-specific fixtures belong in their respective test files.

import os
from collections.abc import Iterator
from typing import Any

import pytest

_real_kill = os.kill
_real_killpg = os.killpg


def _plausible(target: object) -> bool:
    """True if *target* is a real pid/pgid rather than a mock or a broadcast."""
    # bool is an int subclass and True == 1, so killpg(True) is kill(-1).
    return isinstance(target, int) and not isinstance(target, bool)


@pytest.fixture(autouse=True, scope="session")
def _forbid_broadcast_signals() -> Iterator[None]:
    """Fail any test that would signal beyond a single process or group.

    ``killpg(pgid)`` is ``kill(-pgid)``, and ``kill(-1)`` means "every process
    this uid may signal" — it logs the developer out and destroys their open
    work. A ``MagicMock`` pid from a mocked ``Popen`` coerces to exactly 1 via
    ``__index__``, so an ordinary unit test can reach it by accident. That is
    not hypothetical: it happened twice while fixing #58.

    ``agents/_subprocess._signal_group`` guards its own call site. This net is
    broader on purpose — it covers any *future* signalling path that forgets to,
    which is the one gap the targeted regression tests cannot see.
    """

    def guarded_kill(pid: Any, sig: Any, /, *args: Any, **kwargs: Any) -> None:
        if not _plausible(pid) or pid <= 0:
            raise AssertionError(
                f"refusing os.kill({pid!r}, {sig!r}): pid must be a real process. "
                "pid <= 0 signals a whole group or every process this uid owns."
            )
        _real_kill(pid, sig, *args, **kwargs)

    def guarded_killpg(pgid: Any, sig: Any, /, *args: Any, **kwargs: Any) -> None:
        if not _plausible(pgid) or pgid <= 1:
            raise AssertionError(
                f"refusing os.killpg({pgid!r}, {sig!r}): killpg(1) is kill(-1), "
                "which would SIGKILL every process this uid owns."
            )
        _real_killpg(pgid, sig, *args, **kwargs)

    setattr(os, "kill", guarded_kill)  # noqa: B010 - mypy rejects direct assignment
    setattr(os, "killpg", guarded_killpg)  # noqa: B010
    try:
        yield
    finally:
        setattr(os, "kill", _real_kill)  # noqa: B010
        setattr(os, "killpg", _real_killpg)  # noqa: B010


def pytest_configure(config: pytest.Config) -> None:
    # Skip the coverage floor when running a subset of test files so that
    # `pytest tests/test_foo.py` doesn't fail due to partial coverage.
    args = config.args
    if args and any(arg.endswith(".py") or ("tests/" in arg and arg != "tests/") for arg in args):
        cov_plugin = config.pluginmanager.get_plugin("_cov")
        if cov_plugin is not None:
            cov_plugin.options.cov_fail_under = 0.0
