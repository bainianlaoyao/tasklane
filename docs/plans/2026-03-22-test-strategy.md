# Prefect Command Scheduler Test Strategy

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Define and execute a concrete test strategy for the Prefect command scheduler without depending on a live Prefect runtime for every test.

**Architecture:** Keep fast unit and interaction tests in `pytest`, then use a small smoke layer for entrypoints and dry-run bootstrap output. Avoid turning the suite into an infrastructure test harness.

**Tech Stack:** Python 3.13, pytest, Prefect 3

---

### Scope

#### 1. Unit tests

Cover pure behavior with no external processes:

- `CommandTask` validation
- resource routing
- markdown builders for execution and result artifacts
- CLI parsing after `--`

#### 2. Interaction tests

Cover important process boundaries with monkeypatch-based tests:

- `submit_task` builds the correct `prefect deployment run ...` command
- `run_command` acquires the expected concurrency slots and returns normalized result metadata
- `apply_bootstrap` registers queues, limits, and deployments with expected names and queue bindings

#### 3. Smoke tests

Run simple commands that prove the repository is usable:

- `uv run --group dev pytest`
- `uv run python submit_experiment.py --help`
- `uv run python bootstrap_prefect.py`

### Non-goals

- Do not require a live Prefect server for most tests.
- Do not require a running worker for the repository test suite.
- Do not test Prefect internals.

### Current success criteria

- Tests protect command submission, resource routing, bootstrap registration, and artifact formatting.
- Dry-run bootstrap output shows both infrastructure commands and deployment registration intent.
- Smoke commands exit successfully.
