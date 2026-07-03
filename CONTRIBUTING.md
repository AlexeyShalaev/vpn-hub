# Contributing to vpn-hub

Thank you for your interest in contributing! This document covers everything you need to get started.

## Development setup

```bash
git clone https://github.com/AlexeyShalaev/vpn-hub.git
cd vpn-hub
make install                      # uv sync (backend) + npm install (frontend)
uv run --project backend pre-commit install --install-hooks   # pre-commit + commit-msg hooks (config at repo root)
```

## Running checks

```bash
make check       # ruff lint + format check + mypy (backend)
make test        # pytest — unit + integration on in-memory SQLite, no Docker
make test-unit   # only unit tests
make front-lint  # tsc --noEmit (frontend)
```

## Code style

- **Type hints** on all functions and methods, including tests
- **Docstrings** on public API only — Google style
- **Line length** — 120 characters (ruff enforced)
- **Quotes** — double quotes (ruff enforced)
- **No comments** unless the *why* is non-obvious

## Commit messages

[Conventional Commits](https://www.conventionalcommits.org/) are enforced by pre-commit:

| Prefix | Use for |
|--------|---------|
| `feat:` | New feature or behaviour |
| `fix:` | Bug fix |
| `docs:` | Documentation only |
| `test:` | Test additions or changes |
| `refactor:` | Code restructure, no behaviour change |
| `perf:` | Performance improvement |
| `chore:` | Build, tooling, CI |

Breaking changes: add `!` after the type (`feat!:`) or include a `BREAKING CHANGE:` footer.

## Pull requests

1. Fork the repository
2. Create a branch from `master`: `git checkout -b feat/my-feature`
3. Make your changes with tests
4. Run `make check && make test-unit` locally
5. Open a PR against `master`

## Releasing (maintainers only)

Releases are fully automated via [Release Please](https://github.com/googleapis/release-please).
Merge a PR with conventional commits → Release Please opens a release PR → merge it → a `vX.Y.Z`
tag is created → the Docker image is built and pushed to `ghcr.io/AlexeyShalaev/vpn-hub`.
