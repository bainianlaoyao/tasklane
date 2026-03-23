# Tasklane

Tasklane is a local command scheduler for single-host experiment workflows.

It keeps your original command intact, queues runs in sqlite, enforces simple CPU/GPU resource classes, streams output back to the terminal, and supports cancellation with `Ctrl+C`.

## What it solves

- queue arbitrary shell or Python commands
- separate `gpu`, `cpu-exclusive`, and `cpu-light` workloads
- prevent host or GPU oversubscription
- keep the default terminal UX blocking and observable
- make cancellation propagate to the real child process

## Resource Classes

- `gpu-exclusive`
  For GPU jobs that can share the host with CPU work.
- `gpu-host-exclusive`
  For GPU jobs that also need exclusive host CPU / memory / IO.
- `cpu-exclusive`
  For heavy CPU or memory jobs that should not share the host.
- `cpu-light`
  For light evaluation, post-processing, or report generation.

The built-in slot model is:

- `gpu-0 = 1`
- `host-exclusive = 1`
- `cpu-light = 2`

## Install

### Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

### Linux

```bash
bash ./scripts/install-linux.sh
```

Both scripts install:

- `tasklane`
- `tasklane-bootstrap`
- `pcs` and `pcs-bootstrap` as legacy aliases
- `prefect-submit` and `prefect-bootstrap` as compatibility aliases for older setups

You can also install directly from GitHub:

```powershell
uv tool install git+https://github.com/bainianlaoyao/tasklane.git
```

```bash
uv tool install git+https://github.com/bainianlaoyao/tasklane.git
```

## Quick Start

### 1. Initialize local Tasklane state

Preview:

```powershell
tasklane-bootstrap
```

Apply:

```powershell
tasklane-bootstrap --apply
```

By default, Tasklane stores state under:

- Windows: `%LOCALAPPDATA%\tasklane`
- Linux: `~/.local/share/tasklane`

Override with:

```powershell
$env:TASKLANE_HOME = "D:\Data\Tasklane"
```

```bash
export TASKLANE_HOME=/data/tasklane
```

### 2. Submit a command in attached mode

```powershell
tasklane `
  --cwd E:\freqtrade `
  --project tabicl `
  --resource gpu-exclusive `
  --run-name tabicl-ra-001 `
  --label tabicl `
  --env TABICL_DEVICE=cuda `
  -- uv run python user_data/tabicl_pipeline/generate_random_anchor_predictions.py
```

Attached mode:

- submits the run
- starts local scheduling if needed
- waits for completion
- streams stdout and stderr
- returns the child exit code

Typical output:

```text
[scheduler] submitted run_id=... queue=gpu resource=gpu-exclusive
[scheduler] waiting run_id=... state=queued queue=gpu
[scheduler] started pid=12345
loading data...
epoch 1/10
[scheduler] finished status=completed exit_code=0
```

### 3. Run a daemon for detached or shared queue processing

If you want queued detached runs to keep progressing without an attached terminal, run:

```powershell
tasklane daemon
```

Useful for:

- `--detach` submissions
- long-lived shared queues
- keeping the scheduler alive across multiple terminals

## Attached vs Detached

Default mode is attached.

Use `--detach` only when you intentionally want fire-and-forget submission:

```powershell
tasklane `
  --cwd E:\freqtrade `
  --project tabicl `
  --resource cpu-exclusive `
  --detach `
  -- uv run python train.py
```

Detached runs need some scheduler process to be active, usually `tasklane daemon`.

## Migration Note

Older Tasklane revisions used Prefect for orchestration.

Current Tasklane is fully local:

- no Prefect server
- no Prefect worker
- no remote API
- local sqlite state and local log files only

The legacy entry points `pcs`, `pcs-bootstrap`, `prefect-submit`, and `prefect-bootstrap` are still installed so older scripts can keep working.

## Local State Model

Tasklane does not use Prefect.

Runtime state lives in:

- a local sqlite database
- per-run log files

That state includes:

- submitted command payload
- current run status
- requested cancellation state
- exit code
- per-run scheduler and command logs

## Development

```powershell
uv sync --group dev
uv run --group dev pytest
```

Install the editable tool locally:

```powershell
uv tool install -e . --force
tasklane --help
tasklane-bootstrap --help
```

## Agent Skill

This repository also ships with a reusable agent skill:

- [Skill Install Guide](./docs/SKILL-INSTALL.md)
- [Skill File](./SKILL.md)

## Repository Layout

```text
tasklane/
  docs/
  scripts/
  src/tasklane/
    attach.py
    bootstrap.py
    cli.py
    scheduler.py
    state.py
  tests/
```

## License

MIT. See [LICENSE](./LICENSE).
