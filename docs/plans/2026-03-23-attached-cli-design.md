# Attached CLI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make the scheduler CLI behave like a blocking terminal command by default, with live scheduler events, streamed command logs, and `Ctrl+C` cancellation propagation.

**Architecture:** Replace the current CLI-based `prefect deployment run` wrapper with a Python client workflow that creates a flow run directly, then optionally attaches to it. The attached client prints scheduler event lines, tails Prefect logs for the flow run, waits for terminal completion, and sends cancellation on local interrupt. The worker-side flow emits explicit scheduler lifecycle markers and streams subprocess output incrementally instead of waiting until process exit.

**Tech Stack:** Python 3.12, Prefect 3 client/orchestration APIs, Prefect logging, Pydantic, pytest

---

### Task 1: Define attached CLI behavior in tests

**Files:**
- Modify: `D:\Data\DEV\prefect-command-scheduler\tests\test_cli.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\tests\test_attach.py`

**Step 1: Write failing tests**

Cover:
- CLI defaults to attached mode and supports `--detach`
- scheduler event formatting for `submitted`, `waiting`, `started`, `cancelling`, `finished`
- attached runner tails logs in order and maps final flow state to local exit code
- attached runner sends cancellation when interrupted

**Step 2: Run tests to verify they fail**

Run: `uv run --group dev pytest tests/test_cli.py tests/test_attach.py`
Expected: FAIL because the new attach abstractions and flags do not exist yet.

### Task 2: Implement attach-side client workflow

**Files:**
- Modify: `D:\Data\DEV\prefect-command-scheduler\src\prefect_command_scheduler\cli.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\src\prefect_command_scheduler\attach.py`

**Step 1: Implement the minimal API to satisfy tests**

Add:
- direct deployment submission through Prefect Python client
- attached runner that polls flow run state and log stream
- scheduler event output helpers
- local interrupt handling and remote cancellation

**Step 2: Run tests again**

Run: `uv run --group dev pytest tests/test_cli.py tests/test_attach.py`
Expected: PASS.

### Task 3: Emit worker-side lifecycle markers and live logs

**Files:**
- Modify: `D:\Data\DEV\prefect-command-scheduler\src\prefect_command_scheduler\flows.py`
- Modify: `D:\Data\DEV\prefect-command-scheduler\tests\test_flows.py`

**Step 1: Write the failing test**

Cover:
- lifecycle marker logs are emitted before waiting, at actual command start, and on finish
- subprocess output is logged incrementally rather than only after completion
- cancellation/exception path terminates the child process

**Step 2: Run focused tests to verify failure**

Run: `uv run --group dev pytest tests/test_flows.py`
Expected: FAIL because `run_command` still buffers output and does not emit lifecycle markers.

**Step 3: Implement minimal flow changes**

Use `subprocess.Popen`, line-by-line streaming, lifecycle log markers, and defensive cleanup on cancellation/error.

**Step 4: Re-run focused tests**

Run: `uv run --group dev pytest tests/test_flows.py`
Expected: PASS.

### Task 4: Verify end-to-end behavior and document usage

**Files:**
- Modify: `D:\Data\DEV\prefect-command-scheduler\README.md`
- Modify: `D:\Data\DEV\prefect-command-scheduler\SKILL.md`

**Step 1: Update docs**

Document:
- default attached behavior
- `--detach`
- scheduler event lines
- interrupt/cancel semantics

**Step 2: Run full verification**

Run:
- `uv run --group dev pytest`
- `uv run python submit_experiment.py --help`

Expected: PASS.
