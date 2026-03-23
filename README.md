# Tasklane

Resource-aware local command scheduler built on Prefect 3.

Tasklane turns arbitrary shell or Python commands into queued Prefect runs with explicit CPU/GPU resource metadata. It is designed for single-host experiment workflows where you need:

- explicit CPU vs GPU scheduling
- prevention of host or GPU oversubscription
- queue-based execution
- attached terminal behavior by default
- a thin wrapper that keeps the original command intact

## Features

- Arbitrary command submission with minimal wrapping
- Explicit resource classes:
  - `gpu-exclusive`
  - `gpu-host-exclusive`
  - `cpu-exclusive`
  - `cpu-light`
- Default attached mode:
  - waits for remote completion
  - streams command output back to the local terminal
  - exits with the remote command status
- Scheduler event lines:
  - `submitted`
  - `waiting`
  - `started`
  - `cancelling`
  - `finished`
- `Ctrl+C` propagation:
  - attached client requests cancellation
  - worker terminates the remote child process

## Requirements

- Python `>=3.12`
- [uv](https://docs.astral.sh/uv/)
- Prefect local server or another reachable Prefect 3 API

## Install

### Windows

Clone the repository, then run:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-windows.ps1
```

The script defaults to installing the checkout that contains the script, so it also works when invoked from another directory.

This installs the global commands:

- `tasklane`
- `tasklane-bootstrap`

### Linux

Clone the repository, then run:

```bash
bash ./scripts/install-linux.sh
```

The script defaults to installing the checkout that contains the script, so it also works when invoked from another directory.

This installs the global commands:

- `tasklane`
- `tasklane-bootstrap`

### Install from a package spec

If you later publish to PyPI or want to install directly from a Git URL, both install scripts accept an explicit source argument. Examples:

```powershell
.\scripts\install-windows.ps1 git+https://github.com/<owner>/<repo>.git
```

```bash
bash ./scripts/install-linux.sh git+https://github.com/<owner>/<repo>.git
```

## Quick Start

### 1. Start Prefect

```powershell
prefect server start
```

### 2. Bootstrap the local queues and deployments

Preview:

```powershell
tasklane-bootstrap
```

Apply:

```powershell
tasklane-bootstrap --apply
```

Bootstrap creates:

- work pool: `local-process`
- work queues:
  - `gpu`
  - `cpu-exclusive`
  - `cpu-light`
- global concurrency limits:
  - `gpu-0 = 1`
  - `host-exclusive = 1`
  - `cpu-light = 2`
- deployments:
  - `command/gpu-exclusive`
  - `command/gpu-host-exclusive`
  - `command/cpu-exclusive`
  - `command/cpu-light`

### 3. Start workers

```powershell
prefect worker start --pool local-process --work-queue gpu --type process --limit 1
prefect worker start --pool local-process --work-queue cpu-exclusive --type process --limit 1
prefect worker start --pool local-process --work-queue cpu-light --type process --limit 2
```

### 4. Submit a command

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

## Attached Terminal Behavior

`tasklane` attaches by default. That means it behaves like a blocking terminal command:

- it submits the run
- prints scheduler event lines
- waits for remote completion
- streams remote command output back to the terminal
- returns the remote command exit code

Typical output:

```text
[scheduler] submitted run_id=... queue=gpu resource=gpu-exclusive
[scheduler] waiting run_id=... state=Scheduled queue=gpu
[scheduler] started pid=12345
loading data...
epoch 1/10
[scheduler] finished status=completed exit_code=0
```

Use `--detach` for fire-and-forget submission:

```powershell
tasklane `
  --cwd E:\freqtrade `
  --project tabicl `
  --resource gpu-exclusive `
  --detach `
  -- uv run python train.py
```

## Resource Classes

- `gpu-exclusive`
  - For GPU jobs that can share the host with CPU work
  - Concurrency slots: `gpu-0`
- `gpu-host-exclusive`
  - For GPU jobs that also need exclusive host CPU / memory / IO
  - Concurrency slots: `gpu-0`, `host-exclusive`
- `cpu-exclusive`
  - For CPU / memory heavy jobs
  - Concurrency slots: `host-exclusive`
- `cpu-light`
  - For lightweight post-processing, evaluation, or other shareable CPU work
  - Concurrency slots: `cpu-light`

## Install Script Notes

Both install scripts:

- use `uv tool install`
- install from the script's checkout in editable mode by default
- install from any explicit local path or package spec you pass in
- call `uv tool update-shell`
- expose `tasklane` and `tasklane-bootstrap` on `PATH`

## Publishing Notes

Recommended GitHub release shape:

- publish the repository as source-first
- keep installation based on `uv tool install`
- document Git install first, PyPI optional later

After publishing, users can install directly without cloning:

```powershell
uv tool install git+https://github.com/<owner>/tasklane.git
```

```bash
uv tool install git+https://github.com/<owner>/tasklane.git
```

## Development

```powershell
uv sync --group dev
uv run --group dev pytest
```

## Repository Layout

```text
tasklane/
  CONTRIBUTING.md
  docs/
  RELEASING.md
  scripts/
  src/tasklane/
  tests/
  bootstrap_prefect.py
  submit_experiment.py
```

## License

MIT. See [LICENSE](./LICENSE).
