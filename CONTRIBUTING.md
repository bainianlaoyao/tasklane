# Contributing

## Development Setup

```powershell
uv sync --group dev
```

## Common Commands

```powershell
uv run --group dev pytest
uv run pcs --help
uv run pcs-bootstrap
```

## Project Scope

- Keep the scheduler command-first: the original command after `--` should remain intact.
- Treat `cwd`, `project`, labels, and metadata as explicit inputs, not inferred magic.
- Keep scheduling policy explicit through `--resource`.
- Preserve attached-mode semantics unless a change is intentional and covered by tests.

## Pull Requests

- Add or update tests for behavior changes.
- Update `README.md` when CLI, install, or operational behavior changes.
- Avoid committing local Prefect state, caches, logs, or temporary test artifacts.
