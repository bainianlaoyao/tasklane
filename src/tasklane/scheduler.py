from __future__ import annotations

import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO

from .attach import encode_command_output_message, encode_scheduler_event_message
from .state import RunRecord, SchedulerState


@dataclass
class _LogWriter:
    path: Path
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def write(self, line: str) -> None:
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(f"{line}\n")


@dataclass
class _ActiveRun:
    run: RunRecord
    process: subprocess.Popen[str]
    stdout_thread: threading.Thread
    stderr_thread: threading.Thread
    log_writer: _LogWriter
    cancel_sent: bool = False


class Scheduler:
    def __init__(self, state: SchedulerState, *, poll_interval: float = 0.2) -> None:
        self.state = state
        self.poll_interval = poll_interval
        self._active_runs: dict[str, _ActiveRun] = {}

    def claim_runnable_runs(self, *, limit: int) -> list[RunRecord]:
        return self.state.claim_runnable_runs(limit=limit)

    def tick(self, *, limit: int = 10) -> int:
        self._reconcile_active_runs()
        claimed = self.claim_runnable_runs(limit=limit)
        for run in claimed:
            self._start_run(run)
        self._reconcile_active_runs()
        return len(claimed) + len(self._active_runs)

    def run_once(self, *, limit: int = 10) -> int:
        claimed = self.claim_runnable_runs(limit=limit)
        for run in claimed:
            self._start_run(run)
        while self._active_runs:
            self._reconcile_active_runs()
            if self._active_runs:
                time.sleep(self.poll_interval)
        return len(claimed)

    def run_forever(self, *, limit: int = 10) -> int:
        while True:
            active = self.tick(limit=limit)
            if active == 0:
                time.sleep(self.poll_interval)

    def _start_run(self, run: RunRecord) -> None:
        env = os.environ.copy()
        env.update(run.task.env_overrides)
        process = subprocess.Popen(
            run.task.command,
            cwd=run.task.cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        updated = self.state.mark_running(run.run_id, pid=process.pid)
        log_writer = _LogWriter(updated.log_path)
        log_writer.write(encode_scheduler_event_message("started", pid=process.pid))
        stdout_thread = threading.Thread(
            target=self._stream_process_output,
            args=(process.stdout, log_writer, "stdout"),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=self._stream_process_output,
            args=(process.stderr, log_writer, "stderr"),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        self._active_runs[updated.run_id] = _ActiveRun(
            run=updated,
            process=process,
            stdout_thread=stdout_thread,
            stderr_thread=stderr_thread,
            log_writer=log_writer,
        )

    def _stream_process_output(
        self,
        stream: TextIO | None,
        log_writer: _LogWriter,
        stream_name: str,
    ) -> None:
        if stream is None:
            return
        for raw_line in iter(stream.readline, ""):
            line = raw_line.rstrip()
            if line:
                log_writer.write(encode_command_output_message(stream_name, line))

    def _reconcile_active_runs(self) -> None:
        for run_id, active in list(self._active_runs.items()):
            current = self.state.get_run(run_id)
            if current is None:
                continue
            if current.cancel_requested and not active.cancel_sent and active.process.poll() is None:
                active.process.terminate()
                active.cancel_sent = True

            return_code = active.process.poll()
            if return_code is None:
                continue

            active.stdout_thread.join(timeout=1)
            active.stderr_thread.join(timeout=1)
            if current.cancel_requested:
                status = "cancelled"
                exit_code = 130
            else:
                status = "completed" if return_code == 0 else "failed"
                exit_code = int(return_code)
            active.log_writer.write(encode_scheduler_event_message("finished", status=status, exit_code=exit_code))
            self.state.finish_run(run_id, status=status, exit_code=exit_code)
            del self._active_runs[run_id]
