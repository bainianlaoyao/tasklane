# Tasklane Local Scheduler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace Prefect-backed command scheduling with a local sqlite-backed Tasklane daemon that preserves queueing, resource isolation, attached terminal behavior, and cancellation.

**Architecture:** Tasklane will persist runs in a local sqlite database and write execution logs to local files. A daemon loop will claim queued runs, enforce resource-slot limits, spawn child processes, stream output into per-run logs, and update run state. The existing `tasklane` CLI will keep its current user-facing submission syntax, but submit into the local database instead of creating Prefect flow runs.

**Tech Stack:** Python 3.12+, sqlite3, subprocess, threading, pathlib, pydantic, pytest

---

### Task 1: Define local scheduler state and storage

**Files:**
- Create: `D:\Data\DEV\prefect-command-scheduler\src\tasklane\state.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\tests\test_state.py`
- Modify: `D:\Data\DEV\prefect-command-scheduler\src\tasklane\models.py`

**Step 1: Write the failing test**

```python
def test_insert_run_persists_command_task_and_log_path(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    task = CommandTask(
        cwd=str(tmp_path),
        command=["python", "-c", "print('hi')"],
        metadata={"resource_class": "cpu-light", "labels": ["demo"]},
        project="demo",
        run_name="demo-run",
    )

    run = state.create_run(task)

    loaded = state.get_run(run.run_id)
    assert loaded is not None
    assert loaded.task.command == ["python", "-c", "print('hi')"]
    assert loaded.status == "queued"
    assert loaded.log_path.name == f"{run.run_id}.log"
```

**Step 2: Run test to verify it fails**

Run: `uv run --group dev pytest tests/test_state.py::test_insert_run_persists_command_task_and_log_path -v`
Expected: FAIL because `SchedulerState` does not exist.

**Step 3: Write minimal implementation**

```python
class SchedulerState:
    @classmethod
    def initialize(cls, db_path: Path) -> "SchedulerState":
        ...

    def create_run(self, task: CommandTask) -> RunRecord:
        ...

    def get_run(self, run_id: str) -> RunRecord | None:
        ...
```

Persist:
- run id
- serialized task payload
- status
- log path
- created / updated timestamps

**Step 4: Run test to verify it passes**

Run: `uv run --group dev pytest tests/test_state.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_state.py src/tasklane/state.py src/tasklane/models.py
git commit -m "feat: add local scheduler state storage"
```

### Task 2: Implement scheduler claiming and resource-slot gating

**Files:**
- Create: `D:\Data\DEV\prefect-command-scheduler\src\tasklane\scheduler.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\tests\test_scheduler.py`
- Modify: `D:\Data\DEV\prefect-command-scheduler\src\tasklane\routing.py`

**Step 1: Write the failing test**

```python
def test_claim_runnable_runs_respects_gpu_and_host_exclusive_limits(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    gpu_run = state.create_run(make_task(tmp_path, "gpu-exclusive", "gpu"))
    host_run = state.create_run(make_task(tmp_path, "cpu-exclusive", "host"))
    waiting_run = state.create_run(make_task(tmp_path, "gpu-host-exclusive", "gpu-host"))

    scheduler = Scheduler(state)
    first = scheduler.claim_runnable_runs(limit=10)

    assert {run.run_id for run in first} == {gpu_run.run_id, host_run.run_id}
    assert state.get_run(waiting_run.run_id).status == "queued"
```

**Step 2: Run test to verify it fails**

Run: `uv run --group dev pytest tests/test_scheduler.py::test_claim_runnable_runs_respects_gpu_and_host_exclusive_limits -v`
Expected: FAIL because `Scheduler` does not exist.

**Step 3: Write minimal implementation**

```python
class Scheduler:
    def claim_runnable_runs(self, *, limit: int) -> list[RunRecord]:
        ...
```

Rules:
- `gpu-exclusive` consumes `gpu-0`
- `gpu-host-exclusive` consumes `gpu-0` and `host-exclusive`
- `cpu-exclusive` consumes `host-exclusive`
- `cpu-light` consumes one `cpu-light` slot with capacity 2

**Step 4: Run test to verify it passes**

Run: `uv run --group dev pytest tests/test_scheduler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_scheduler.py src/tasklane/scheduler.py src/tasklane/routing.py
git commit -m "feat: add local resource-aware scheduler"
```

### Task 3: Implement daemon execution, log streaming, and cancellation

**Files:**
- Modify: `D:\Data\DEV\prefect-command-scheduler\src\tasklane\attach.py`
- Modify: `D:\Data\DEV\prefect-command-scheduler\src\tasklane\scheduler.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\tests\test_daemon.py`

**Step 1: Write the failing test**

```python
def test_run_once_executes_child_and_streams_output_to_log(tmp_path: Path) -> None:
    state = SchedulerState.initialize(tmp_path / "tasklane.db")
    run = state.create_run(
        CommandTask(
            cwd=str(tmp_path),
            command=["python", "-c", "print('hello from tasklane')"],
            metadata={"resource_class": "cpu-light", "labels": []},
        )
    )

    scheduler = Scheduler(state)
    scheduler.run_once()

    updated = state.get_run(run.run_id)
    assert updated.status == "completed"
    assert "hello from tasklane" in updated.log_path.read_text(encoding="utf-8")
```

**Step 2: Run test to verify it fails**

Run: `uv run --group dev pytest tests/test_daemon.py::test_run_once_executes_child_and_streams_output_to_log -v`
Expected: FAIL because `run_once` does not execute anything yet.

**Step 3: Write minimal implementation**

```python
def run_once(self) -> int:
    claimed = self.claim_runnable_runs(limit=1)
    for run in claimed:
        self._execute_run(run)
    return len(claimed)
```

Execution behavior:
- mark run `running`
- spawn child process
- append scheduler events and stdout/stderr lines to the run log
- mark run `completed` / `failed` / `cancelled`
- release resource slots
- if cancellation is requested while attached, terminate child and mark `cancelled`

**Step 4: Run test to verify it passes**

Run: `uv run --group dev pytest tests/test_daemon.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_daemon.py src/tasklane/scheduler.py src/tasklane/attach.py
git commit -m "feat: add local daemon execution and cancellation"
```

### Task 4: Rewire CLI and bootstrap to local Tasklane

**Files:**
- Modify: `D:\Data\DEV\prefect-command-scheduler\src\tasklane\cli.py`
- Modify: `D:\Data\DEV\prefect-command-scheduler\src\tasklane\bootstrap.py`
- Modify: `D:\Data\DEV\prefect-command-scheduler\tests\test_cli.py`
- Modify: `D:\Data\DEV\prefect-command-scheduler\tests\test_bootstrap.py`
- Modify: `D:\Data\DEV\prefect-command-scheduler\README.md`

**Step 1: Write the failing test**

```python
def test_main_submits_to_local_scheduler_and_attaches(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TASKLANE_HOME", str(tmp_path / ".tasklane"))
    result = main([
        "--cwd", str(tmp_path),
        "--resource", "cpu-light",
        "--", "python", "-c", "print('ok')",
    ])
    assert result == 0
```

**Step 2: Run test to verify it fails**

Run: `uv run --group dev pytest tests/test_cli.py::test_main_submits_to_local_scheduler_and_attaches -v`
Expected: FAIL because CLI still depends on Prefect submission and attachment.

**Step 3: Write minimal implementation**

```python
def main(argv: Sequence[str] | None = None) -> int:
    ...
    state = SchedulerState.initialize(default_db_path())
    submitted = submit_task(task, state=state)
    ...
```

Bootstrap behavior:
- preview local paths instead of Prefect commands
- `--apply` initializes local sqlite DB and log directory

**Step 4: Run test to verify it passes**

Run: `uv run --group dev pytest tests/test_cli.py tests/test_bootstrap.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add tests/test_cli.py tests/test_bootstrap.py src/tasklane/cli.py src/tasklane/bootstrap.py README.md
git commit -m "feat: switch tasklane to local scheduler runtime"
```

### Task 5: Full verification and cleanup

**Files:**
- Modify: `D:\Data\DEV\prefect-command-scheduler\README.md`
- Modify: `D:\Data\DEV\prefect-command-scheduler\SKILL.md`

**Step 1: Run focused verification**

Run: `uv run --group dev pytest tests/test_state.py tests/test_scheduler.py tests/test_daemon.py -v`
Expected: PASS

**Step 2: Run full verification**

Run: `uv run --group dev pytest`
Expected: PASS

**Step 3: Verify installed commands**

Run:

```bash
uv tool install -e . --force
tasklane --help
tasklane-bootstrap --help
```

Expected: all commands succeed

**Step 4: Update docs**

Document:
- local sqlite storage
- daemon responsibility
- attach / cancel behavior
- migration note from Prefect-backed versions

**Step 5: Commit**

```bash
git add README.md SKILL.md
git commit -m "docs: document local tasklane scheduler"
```
