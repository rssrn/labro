# Contributing

Thanks for your interest in contributing to Labro. All contributions are welcome — bug fixes, documentation improvements, new prompts and personas, task source plugins, test coverage, or just asking questions that surface rough edges.

## Code of Conduct

This project follows the [Contributor Covenant](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you agree to uphold its standards. Report unacceptable behaviour via [GitHub Security Advisories](https://github.com/rssrn/labro/security/advisories/new).

## Getting Started

Follow the [Local Python section of QUICKSTART.md](QUICKSTART.md#local-python-recommended-for-development) for clone, virtual environment, and dependency setup.

### Docker builds

If you're making changes to the Dockerfile or entrypoint, build the `dev` target which includes the test suite:

```bash
docker build --target dev -t labro:dev .
```

## Development

The full quality-gate toolchain is installed with `uv pip install -e '.[dev]'`:

| Tool | Purpose |
|---|---|
| `ruff` | Linting and formatting — `uv run ruff check .` / `uv run ruff format .` |
| `mypy` | Type checking in strict mode — `uv run mypy src/` |
| `bandit` | Security linting — `uv run bandit -r src/` |
| `pytest` | Test suite with 80% coverage floor — `uv run pytest` |
| `pre-commit` | Hooks: ruff, mypy, bandit, shellcheck, pytest on commit; pip-audit on push |

**Before every commit:** run `uv run ruff format .` — the pre-commit hook aborts and reformats if you skip it, requiring a second commit attempt.

## Testing

```bash
uv run pytest            # full test suite
uv run pytest -x         # stop on first failure
uv run pytest -k name    # run tests matching a name
```

Tests live in `tests/`. The coverage floor is 80% — new code should be covered.

## Contributing

1. Fork the repo and create a feature branch.
2. Follow the quality gates: ruff, mypy strict, bandit (no `shell=True` — B602 must not be skipped), and 80% test coverage.
3. Open a PR against `main` with a clear description of what and why.

The harness is deliberately simple — if you're adding intelligence, it probably belongs in a prompt, not the codebase. Read [Architecture](docs/ARCHITECTURE.md) and the [ADRs](docs/adr/) before adding abstractions.

## Security

The `bandit` B602 rule (`shell=True`) must never be skipped — all subprocess calls use list form. Report security vulnerabilities privately via [GitHub Security Advisories](https://github.com/rssrn/labro/security/advisories/new).
