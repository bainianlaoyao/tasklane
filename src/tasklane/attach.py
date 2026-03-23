from __future__ import annotations

import json
import signal
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, TextIO

from .models import CommandTask
from .routing import route_task
from .state import SchedulerState


SCHEDULER_EVENT_PREFIX = "__PCS_EVENT__ "
COMMAND_STDOUT_PREFIX = "__PCS_STDOUT__ "
COMMAND_STDERR_PREFIX = "__PCS_STDERR__ "


@dataclass(frozen=True)
class SubmittedRun:
    run_id: str
    run_name: str
    queue_name: str
    resource_class: str

    @property
    def flow_run_id(self) -> str:
        return self.run_id


def encode_scheduler_event_message(event: str, **fields: object) -> str:
    payload = {"event": event, **fields}
    return f"{SCHEDULER_EVENT_PREFIX}{json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}"


def parse_scheduler_event_message(message: str) -> dict[str, object] | None:
    if not message.startswith(SCHEDULER_EVENT_PREFIX):
        return None
    return json.loads(message[len(SCHEDULER_EVENT_PREFIX) :])


def encode_command_output_message(stream_name: str, line: str) -> str:
    if stream_name == "stdout":
        return f"{COMMAND_STDOUT_PREFIX}{line}"
    if stream_name == "stderr":
        return f"{COMMAND_STDERR_PREFIX}{line}"
    raise ValueError(f"Unsupported stream name: {stream_name}")


def format_scheduler_event_line(event: str, **fields: object) -> str:
    suffix = " ".join(f"{key}={value}" for key, value in fields.items())
    if suffix:
        return f"[scheduler] {event} {suffix}"
    return f"[scheduler] {event}"


def _write_line(out: TextIO, line: str) -> None:
    out.write(f"{line}\n")
    out.flush()


def submit_task(task: CommandTask, *, state: SchedulerState | None = None) -> SubmittedRun:
    scheduler_state = SchedulerState.initialize() if state is None else state
    created = scheduler_state.create_run(task)
    return SubmittedRun(
        run_id=created.run_id,
        run_name=created.task.run_name or created.run_id,
        queue_name=created.queue_name,
        resource_class=created.resource_class,
    )


def attach_submitted_run(
    submitted: SubmittedRun,
    *,
    out: TextIO | None = None,
    poll_interval: float = 1.0,
    state: SchedulerState | None = None,
) -> int:
    from .scheduler import Scheduler

    stream = sys.stdout if out is None else out
    scheduler_state = SchedulerState.initialize() if state is None else state
    scheduler = Scheduler(scheduler_state, poll_interval=min(poll_interval, 0.2))
    log_offset = 0
    last_waiting_state: str | None = None
    cancellation_sent = False

    with _capture_interrupt_requests() as interrupt_requested:
        while True:
            scheduler.tick(limit=10)
            if interrupt_requested() and not cancellation_sent:
                _write_line(
                    stream,
                    format_scheduler_event_line(
                        "cancelling",
                        run_id=submitted.run_id,
                        reason="keyboard_interrupt",
                    ),
                )
                scheduler_state.request_cancel(submitted.run_id)
                cancellation_sent = True

            current = scheduler_state.get_run(submitted.run_id)
            if current is None:
                raise RuntimeError(f"Unknown run id: {submitted.run_id}")

            log_offset = _render_new_log_lines(current.log_path, offset=log_offset, out=stream)

            if not current.is_final:
                if current.status != "running" and current.status != last_waiting_state:
                    _write_line(
                        stream,
                        format_scheduler_event_line(
                            "waiting",
                            run_id=submitted.run_id,
                            state=current.status,
                            queue=submitted.queue_name,
                        ),
                    )
                    last_waiting_state = current.status
                time.sleep(poll_interval)
                continue

            if current.status == "completed":
                return current.exit_code or 0
            if current.status == "cancelled":
                return 130
            return current.exit_code or 1


def _render_new_log_lines(log_path, *, offset: int, out: TextIO) -> int:  # noqa: ANN001
    if not log_path.exists():
        return offset
    with log_path.open("r", encoding="utf-8") as handle:
        handle.seek(offset)
        payload = handle.read()
        next_offset = handle.tell()
    for line in payload.splitlines():
        parsed = parse_scheduler_event_message(line)
        if parsed is not None:
            event = str(parsed.pop("event"))
            _write_line(out, format_scheduler_event_line(event, **parsed))
            continue
        if line.startswith(COMMAND_STDOUT_PREFIX):
            _write_line(out, line[len(COMMAND_STDOUT_PREFIX) :])
            continue
        if line.startswith(COMMAND_STDERR_PREFIX):
            _write_line(out, line[len(COMMAND_STDERR_PREFIX) :])
            continue
    return next_offset


@contextmanager
def _capture_interrupt_requests() -> Iterator[Callable[[], bool]]:
    interrupted = {"requested": False}
    previous_handlers: list[tuple[int, object]] = []

    def _handler(signum, frame):  # noqa: ANN001, ARG001
        interrupted["requested"] = True

    for signum in _supported_interrupt_signals():
        previous_handlers.append((signum, signal.getsignal(signum)))
        signal.signal(signum, _handler)

    try:
        yield lambda: bool(interrupted["requested"])
    finally:
        for signum, previous in previous_handlers:
            signal.signal(signum, previous)


def _supported_interrupt_signals() -> tuple[int, ...]:
    signals = [signal.SIGINT]
    if hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    return tuple(signals)
