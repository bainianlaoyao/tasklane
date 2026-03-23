from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

from .models import CommandTask
from .routing import RESOURCE_SLOT_CAPACITY, route_task


FINAL_STATUSES = {"completed", "failed", "cancelled", "crashed"}
ACTIVE_STATUSES = {"starting", "running"}


@dataclass(frozen=True)
class RunRecord:
    run_id: str
    task: CommandTask
    status: str
    queue_name: str
    resource_class: str
    log_path: Path
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None
    exit_code: int | None
    cancel_requested: bool
    pid: int | None
    error: str | None

    @property
    def is_final(self) -> bool:
        return self.status in FINAL_STATUSES


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_tasklane_home() -> Path:
    configured = os.getenv("TASKLANE_HOME")
    if configured:
        return Path(configured).expanduser()
    if os.name == "nt":
        local_app_data = os.getenv("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "tasklane"
    return Path.home() / ".local" / "share" / "tasklane"


def default_db_path() -> Path:
    return default_tasklane_home() / "tasklane.db"


def default_logs_dir() -> Path:
    return default_tasklane_home() / "logs"


class SchedulerState:
    def __init__(self, db_path: Path, logs_dir: Path, connection: sqlite3.Connection) -> None:
        self.db_path = db_path
        self.logs_dir = logs_dir
        self._connection = connection

    @classmethod
    def initialize(
        cls,
        db_path: Path | str | None = None,
        *,
        logs_dir: Path | str | None = None,
    ) -> "SchedulerState":
        resolved_db_path = Path(db_path) if db_path is not None else default_db_path()
        resolved_logs_dir = Path(logs_dir) if logs_dir is not None else default_logs_dir()
        resolved_db_path.parent.mkdir(parents=True, exist_ok=True)
        resolved_logs_dir.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(resolved_db_path, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        state = cls(resolved_db_path, resolved_logs_dir, connection)
        state._create_schema()
        return state

    def _create_schema(self) -> None:
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                task_payload TEXT NOT NULL,
                status TEXT NOT NULL,
                queue_name TEXT NOT NULL,
                resource_class TEXT NOT NULL,
                log_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                exit_code INTEGER,
                cancel_requested INTEGER NOT NULL DEFAULT 0,
                pid INTEGER,
                error TEXT
            );

            CREATE INDEX IF NOT EXISTS ix_runs_status_created_at
            ON runs(status, created_at);
            """
        )
        self._connection.commit()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            self._connection.rollback()
            raise
        else:
            self._connection.commit()

    def create_run(self, task: CommandTask) -> RunRecord:
        run_id = str(uuid4())
        now = utc_now()
        route = route_task(task)
        log_path = self.logs_dir / f"{run_id}.log"
        log_path.touch()
        self._connection.execute(
            """
            INSERT INTO runs (
                run_id, task_payload, status, queue_name, resource_class, log_path,
                created_at, updated_at, cancel_requested
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0)
            """,
            (
                run_id,
                json.dumps(task.model_dump(mode="json"), ensure_ascii=True),
                "queued",
                route.work_queue_name,
                task.resource_class,
                str(log_path),
                now,
                now,
            ),
        )
        self._connection.commit()
        record = self.get_run(run_id)
        assert record is not None
        return record

    def get_run(self, run_id: str) -> RunRecord | None:
        row = self._connection.execute(
            "SELECT * FROM runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_runs(self, *, statuses: tuple[str, ...] | None = None) -> list[RunRecord]:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = self._connection.execute(
                f"SELECT * FROM runs WHERE status IN ({placeholders}) ORDER BY created_at ASC",
                statuses,
            ).fetchall()
        else:
            rows = self._connection.execute(
                "SELECT * FROM runs ORDER BY created_at ASC",
            ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def claim_runnable_runs(self, *, limit: int) -> list[RunRecord]:
        with self._transaction():
            active_rows = self._connection.execute(
                "SELECT * FROM runs WHERE status IN ('starting', 'running') ORDER BY created_at ASC"
            ).fetchall()
            capacities = dict(RESOURCE_SLOT_CAPACITY)
            for row in active_rows:
                record = self._row_to_record(row)
                for slot in route_task(record.task).concurrency_slots:
                    capacities[slot] -= 1

            queued_rows = self._connection.execute(
                "SELECT * FROM runs WHERE status = 'queued' ORDER BY created_at ASC"
            ).fetchall()

            claimed_run_ids: list[str] = []
            now = utc_now()
            for row in queued_rows:
                if len(claimed_run_ids) >= limit:
                    break
                record = self._row_to_record(row)
                slots = route_task(record.task).concurrency_slots
                if any(capacities[slot] <= 0 for slot in slots):
                    continue
                updated = self._connection.execute(
                    """
                    UPDATE runs
                    SET status = 'starting', updated_at = ?
                    WHERE run_id = ? AND status = 'queued'
                    """,
                    (now, record.run_id),
                )
                if updated.rowcount != 1:
                    continue
                for slot in slots:
                    capacities[slot] -= 1
                claimed_run_ids.append(record.run_id)

        return [self.get_run(run_id) for run_id in claimed_run_ids if self.get_run(run_id) is not None]

    def mark_running(self, run_id: str, *, pid: int | None) -> RunRecord:
        now = utc_now()
        self._connection.execute(
            """
            UPDATE runs
            SET status = 'running', pid = ?, started_at = COALESCE(started_at, ?), updated_at = ?
            WHERE run_id = ?
            """,
            (pid, now, now, run_id),
        )
        self._connection.commit()
        record = self.get_run(run_id)
        assert record is not None
        return record

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        exit_code: int,
        error: str | None = None,
    ) -> RunRecord:
        now = utc_now()
        self._connection.execute(
            """
            UPDATE runs
            SET status = ?, exit_code = ?, error = ?, finished_at = ?, updated_at = ?, cancel_requested = 0
            WHERE run_id = ?
            """,
            (status, exit_code, error, now, now, run_id),
        )
        self._connection.commit()
        record = self.get_run(run_id)
        assert record is not None
        return record

    def request_cancel(self, run_id: str) -> RunRecord:
        record = self.get_run(run_id)
        if record is None:
            raise KeyError(run_id)
        now = utc_now()
        if record.status in {"queued", "starting"}:
            self._connection.execute(
                """
                UPDATE runs
                SET status = 'cancelled', cancel_requested = 0, exit_code = 130,
                    finished_at = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (now, now, run_id),
            )
        elif record.status == "running":
            self._connection.execute(
                """
                UPDATE runs
                SET cancel_requested = 1, updated_at = ?
                WHERE run_id = ?
                """,
                (now, run_id),
            )
        self._connection.commit()
        updated = self.get_run(run_id)
        assert updated is not None
        return updated

    def _row_to_record(self, row: sqlite3.Row) -> RunRecord:
        task_payload = json.loads(row["task_payload"])
        return RunRecord(
            run_id=row["run_id"],
            task=CommandTask.model_validate(task_payload),
            status=row["status"],
            queue_name=row["queue_name"],
            resource_class=row["resource_class"],
            log_path=Path(row["log_path"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            exit_code=row["exit_code"],
            cancel_requested=bool(row["cancel_requested"]),
            pid=row["pid"],
            error=row["error"],
        )
