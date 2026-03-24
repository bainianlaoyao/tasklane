---
name: tasklane
description: Use when submitting arbitrary shell or Python commands to a local Tasklane queue with explicit GPU/CPU resource metadata, or when operating the local sqlite-backed Tasklane scheduler in D:\Data\DEV\prefect-command-scheduler.
---

# Tasklane

## State Model

- Treat this repository as code and configuration only.
- Runtime work state does not live in agent memory.
- Runtime work state lives in local Tasklane storage:
  - sqlite state database
  - per-run log files
- This repository stores:
  - CLI and daemon code
  - resource routing rules
  - bootstrap logic
  - tests

## Repository Layout

- Entry points:
  - `tasklane`
  - `tasklane-bootstrap`
  - compatibility wrappers:
    - `submit_experiment.py`
    - `bootstrap_prefect.py`
- Core package:
  - `src/tasklane/models.py`
  - `src/tasklane/routing.py`
  - `src/tasklane/state.py`
  - `src/tasklane/scheduler.py`
  - `src/tasklane/attach.py`
  - `src/tasklane/cli.py`
  - `src/tasklane/bootstrap.py`
- Tests:
  - `tests/`

## Resource Classes

- `gpu-exclusive`
  - GPU work that can share the host with CPU tasks
  - consumes slot `gpu-0`
- `gpu-host-exclusive`
  - GPU work that also needs exclusive host resources
  - consumes slots `gpu-0` and `host-exclusive`
- `cpu-exclusive`
  - CPU or memory heavy work
  - consumes slot `host-exclusive`
- `cpu-light`
  - lightweight CPU work
  - consumes one `cpu-light` slot

Built-in slot capacities:

- `gpu-0 = 1`
- `host-exclusive = 1`
- `cpu-light = 150`

## Standard Workflow

### 1. Install dependencies

Run in `D:\Data\DEV\prefect-command-scheduler`:

```powershell
uv sync --group dev
```

### 2. Initialize local state

Run in `D:\Data\DEV\prefect-command-scheduler`:

```powershell
uv run tasklane-bootstrap --apply
```

This creates:

- local sqlite state
- local log directories

Default local paths:

- Windows: `%LOCALAPPDATA%\tasklane`
- Linux: `~/.local/share/tasklane`

Override with `TASKLANE_HOME` when needed.

### 3. Submit a command

```powershell
uv run tasklane `
  --cwd E:\freqtrade `
  --project tabicl `
  --resource gpu-exclusive `
  --run-name tabicl-ra-001 `
  --label tabicl `
  --env TABICL_DEVICE=cuda `
  -- uv run python user_data/tabicl_pipeline/generate_random_anchor_predictions.py
```

Rules:

- Keep the original command after `--` unchanged.
- Pass `cwd` explicitly.
- Pass `project` when it helps with experiment labeling.
- Always pass the correct `--resource`.
- Default mode is attached and blocks until the run finishes.
- Use `--detach` only if a daemon is already running or you intentionally want the run to wait in queue.

### 4. Run a daemon when detached queue processing is needed

```powershell
uv run tasklane daemon
```

Use the daemon when:

- running detached jobs
- keeping a shared queue alive across terminals
- processing queued work without an attached submitter
- supervising multiple submitters from one host process

### 5. Inspect the queue

```powershell
uv run tasklane queue
uv run tasklane queue --watch
uv run tasklane queue --json
```

Use this when you need a direct view of:

- queued runs
- running runs
- current resource occupancy
- exit states of recent runs

### 6. Manage an existing run

Use the run id from `tasklane queue`:

```powershell
uv run tasklane cancel <run-id>
uv run tasklane interrupt <run-id>
uv run tasklane delete <run-id>
```

Rules:

- `cancel` is cooperative cancellation.
- `interrupt` also attempts immediate PID-level termination for a running task.
- `delete` only applies to non-active runs and also removes the local log file.

### Scheduler Event Lines

Attached mode prints stable scheduler-prefixed lines:

```text
[scheduler] submitted run_id=... queue=gpu resource=gpu-exclusive
[scheduler] waiting run_id=... state=queued queue=gpu
[scheduler] started pid=12345
[scheduler] cancelling run_id=... reason=keyboard_interrupt
[scheduler] finished status=completed exit_code=0
```

Lines without the `[scheduler]` prefix are original command output.

## Execution Semantics

- The submitted command is stored in sqlite as a serialized task payload.
- The scheduler claims queued runs in FIFO order while respecting resource slots.
- Child process stdout and stderr are appended to the run log with stable prefixes.
- Attached mode tails the run log and renders scheduler lifecycle markers.
- Local `Ctrl+C` requests cancellation and propagates to the real child process.

## Important Boundaries

- Do not assume Tasklane infers resource type from the command; resource metadata must be explicit.
- Do not assume detached runs progress by themselves; they need an attached submitter or a `tasklane daemon`.
- Do not replace the original command with a project-specific wrapper unless explicitly requested.
- Legacy commands `pcs`, `pcs-bootstrap`, `prefect-submit`, and `prefect-bootstrap` still map to the same local scheduler for compatibility.

## Verification

Use these checks after edits:

```powershell
uv run --group dev pytest
uv run tasklane --help
uv run tasklane-bootstrap --help
```
