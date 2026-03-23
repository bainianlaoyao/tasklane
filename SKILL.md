---
name: prefect-command-scheduler
description: Use when submitting arbitrary shell or Python commands to a local Prefect 3 queue with explicit GPU/CPU resource metadata, or when bootstrapping and operating the Prefect command scheduler in D:\Data\DEV\prefect-command-scheduler.
---

# Prefect Command Scheduler

## State Model

- Treat this repository as code and configuration only.
- Do not assume runtime scheduler state lives in this repository.
- Runtime work state lives in the active Prefect server backend.
- On local single-machine setup, that state is typically stored by Prefect in its local server database.
- Flow runs, queue state, deployment state, concurrency slots, and run history come from Prefect, not from in-memory agent state.
- This repository stores:
  - scheduler code
  - routing rules
  - bootstrap logic
  - tests

## Repository Layout

- Entry points:
  - `pcs`
  - `pcs-bootstrap`
  - compatibility wrappers:
    - `submit_experiment.py`
    - `bootstrap_prefect.py`
- Core package:
  - `src/prefect_command_scheduler/models.py`
  - `src/prefect_command_scheduler/routing.py`
  - `src/prefect_command_scheduler/cli.py`
  - `src/prefect_command_scheduler/flows.py`
  - `src/prefect_command_scheduler/bootstrap.py`
- Tests:
  - `tests/`

## Resource Classes

- `gpu-exclusive`
  - For commands that need GPU access but can share the host with CPU work.
  - Routed to queue `gpu`.
  - Uses concurrency slot `gpu-0`.
- `gpu-host-exclusive`
  - For GPU commands that also need exclusive host CPU / memory / IO access.
  - Routed to queue `gpu`.
  - Uses concurrency slots `gpu-0` and `host-exclusive`.
- `cpu-exclusive`
  - For CPU or memory heavy commands that should not share the host.
  - Routed to queue `cpu-exclusive`.
  - Uses concurrency slot `host-exclusive`.
- `cpu-light`
  - For lightweight evaluation or post-processing commands.
  - Routed to queue `cpu-light`.
  - Uses concurrency slot `cpu-light`.

## Standard Workflow

### 1. Install dependencies

Run in `D:\Data\DEV\prefect-command-scheduler`:

```powershell
uv sync --group dev
```

### 2. Start Prefect server

```powershell
uv run prefect server start
```

### 3. Preview bootstrap plan

```powershell
uv run pcs-bootstrap
```

### 4. Apply bootstrap

```powershell
uv run pcs-bootstrap --apply
```

This creates or updates:

- work pool `local-process`
- queues:
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

### 5. Start workers

```powershell
uv run prefect worker start --pool local-process --work-queue gpu --type process --limit 1
uv run prefect worker start --pool local-process --work-queue cpu-exclusive --type process --limit 1
uv run prefect worker start --pool local-process --work-queue cpu-light --type process --limit 2
```

### 6. Submit a command

```powershell
uv run pcs `
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
- Pass `project` if useful for indexing/filtering; it is metadata, not the execution authority.
- Always pass the correct `--resource`.
- The CLI attaches by default: it waits for remote completion, streams logs, and exits with the remote command status.
- Use `--detach` only when you want fire-and-forget submission.

### Scheduler Event Lines

Attached mode prints stable scheduler-prefixed lines, for example:

```text
[scheduler] submitted run_id=... queue=gpu resource=gpu-exclusive
[scheduler] waiting run_id=... state=Scheduled queue=gpu
[scheduler] started pid=12345
[scheduler] cancelling run_id=... reason=keyboard_interrupt
[scheduler] finished status=completed exit_code=0
```

Treat lines without the `[scheduler]` prefix as original command output.

## Execution Semantics

- The submitted command is stored as task payload and execution artifact input.
- The flow records:
  - `cwd`
  - `project`
  - original command
  - env overrides
  - metadata
  - git context if available
- The flow then acquires Prefect concurrency slots and runs the command in the supplied `cwd`.
- Result status is published as an execution result artifact.
- Worker-side execution emits scheduler lifecycle markers into Prefect logs so attached clients can render start/finish transitions.
- In attached mode, local `Ctrl+C` sends a cancellation request to the corresponding Prefect flow run.

## Important Boundaries

- Do not assume this scheduler infers resource type correctly from the command. Resource metadata must be supplied explicitly.
- Do not assume this repository alone is enough to answer queue/run status questions. Query Prefect for actual runtime state.
- Do not rewrite the user command into a project-specific wrapper unless explicitly requested.
- Prefer `command + metadata` over adding hardcoded experiment templates.

## Verification

Use these checks after edits:

```powershell
uv run --group dev pytest
uv run pcs --help
uv run pcs-bootstrap
```
