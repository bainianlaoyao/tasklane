# Prefect Command Scheduler Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a standalone Prefect 3 command scheduler that queues arbitrary commands with explicit resource metadata.

**Architecture:** A thin CLI submits `CommandTask` payloads into Prefect deployments selected by resource class. A shared flow validates input, records execution metadata, and runs the original command in the supplied working directory.

**Tech Stack:** Python 3.12, Prefect 3, Pydantic, pytest

---

### Task 1: Define scheduler behaviors in tests

**Files:**
- Create: `D:\Data\DEV\prefect-command-scheduler\tests\test_models.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\tests\test_routing.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\tests\test_cli.py`

**Step 1: Write the failing tests**

Cover:
- command task validation
- resource to deployment mapping
- CLI parsing after `--`

**Step 2: Run test to verify it fails**

Run: `uv run --group dev pytest`
Expected: FAIL because scheduler modules do not exist yet.

### Task 2: Implement minimal scheduler modules

**Files:**
- Create: `D:\Data\DEV\prefect-command-scheduler\src\prefect_command_scheduler\models.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\src\prefect_command_scheduler\routing.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\src\prefect_command_scheduler\cli.py`
- Create: `D:\Data\DEV\prefect-command-scheduler\src\prefect_command_scheduler\flows.py`

**Step 1: Implement only enough code to satisfy tests**

**Step 2: Run tests again**

Run: `uv run --group dev pytest`
Expected: PASS.

### Task 3: Add docs and examples

**Files:**
- Create: `D:\Data\DEV\prefect-command-scheduler\README.md`

**Step 1: Document CLI usage and routing model**

**Step 2: Re-run tests**

Run: `uv run --group dev pytest`
Expected: PASS.
