from __future__ import annotations

import json
import signal
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable, Iterator, TextIO
from uuid import UUID

import anyio
from prefect.client.orchestration import get_client
from prefect.client.schemas.filters import LogFilter, LogFilterFlowRunId
from prefect.client.schemas.sorting import LogSort
from prefect.states import Cancelled

from .models import CommandTask
from .routing import route_task


SCHEDULER_EVENT_PREFIX = "__PCS_EVENT__ "
COMMAND_STDOUT_PREFIX = "__PCS_STDOUT__ "
COMMAND_STDERR_PREFIX = "__PCS_STDERR__ "


@dataclass(frozen=True)
class SubmittedRun:
    flow_run_id: str
    run_name: str
    queue_name: str
    resource_class: str


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


async def _submit_task(task: CommandTask) -> SubmittedRun:
    route = route_task(task)
    async with get_client() as client:
        deployment = await client.read_deployment_by_name(route.deployment_name)
        flow_run = await client.create_flow_run_from_deployment(
            deployment.id,
            parameters={"task_payload": task.model_dump(mode="json")},
            name=task.run_name,
        )
    return SubmittedRun(
        flow_run_id=str(flow_run.id),
        run_name=flow_run.name,
        queue_name=route.work_queue_name,
        resource_class=task.resource_class,
    )


def submit_task(task: CommandTask) -> SubmittedRun:
    return anyio.run(_submit_task, task)


def _build_log_filter(flow_run_id: str) -> LogFilter:
    return LogFilter(flow_run_id=LogFilterFlowRunId(any_=[UUID(flow_run_id)]))


async def _attach_submitted_run(
    submitted: SubmittedRun,
    *,
    out: TextIO,
    poll_interval: float,
    interrupt_requested: Callable[[], bool],
) -> int:
    last_waiting_state: str | None = None
    log_offset = 0
    remote_exit_code: int | None = None
    cancellation_sent = False
    async with get_client() as client:
        while True:
            try:
                if interrupt_requested() and not cancellation_sent:
                    _write_line(
                        out,
                        format_scheduler_event_line(
                            "cancelling",
                            run_id=submitted.flow_run_id,
                            reason="keyboard_interrupt",
                        ),
                    )
                    await client.set_flow_run_state(submitted.flow_run_id, Cancelled(), force=True)
                    cancellation_sent = True
                flow_run = await client.read_flow_run(submitted.flow_run_id)
                logs = await client.read_logs(
                    log_filter=_build_log_filter(submitted.flow_run_id),
                    limit=200,
                    offset=log_offset,
                    sort=LogSort.TIMESTAMP_ASC,
                )
            except KeyboardInterrupt:
                if cancellation_sent:
                    return 130
                _write_line(
                    out,
                    format_scheduler_event_line(
                        "cancelling",
                        run_id=submitted.flow_run_id,
                        reason="keyboard_interrupt",
                    ),
                )
                await client.set_flow_run_state(submitted.flow_run_id, Cancelled(), force=True)
                cancellation_sent = True
                await anyio.sleep(poll_interval)
                continue

            for log in logs:
                log_offset += 1
                parsed = parse_scheduler_event_message(log.message)
                if parsed is not None:
                    event = str(parsed.pop("event"))
                    if event == "finished" and "exit_code" in parsed:
                        remote_exit_code = int(parsed["exit_code"])
                    _write_line(out, format_scheduler_event_line(event, **parsed))
                    continue
                if log.message.startswith(COMMAND_STDOUT_PREFIX):
                    _write_line(out, log.message[len(COMMAND_STDOUT_PREFIX) :])
                    continue
                if log.message.startswith(COMMAND_STDERR_PREFIX):
                    _write_line(out, log.message[len(COMMAND_STDERR_PREFIX) :])
                    continue

            state_name = flow_run.state_name or "UNKNOWN"
            if not flow_run.state.is_final():
                if state_name != "Running" and state_name != last_waiting_state:
                    _write_line(
                        out,
                        format_scheduler_event_line(
                            "waiting",
                            run_id=submitted.flow_run_id,
                            state=state_name,
                            queue=submitted.queue_name,
                        ),
                    )
                    last_waiting_state = state_name
                await anyio.sleep(poll_interval)
                continue

            if state_name == "Completed":
                return remote_exit_code if remote_exit_code is not None else 0
            if state_name == "Cancelled":
                return 130
            return remote_exit_code if remote_exit_code is not None else 1


def attach_submitted_run(
    submitted: SubmittedRun,
    *,
    out: TextIO | None = None,
    poll_interval: float = 1.0,
) -> int:
    stream = sys.stdout if out is None else out
    with _capture_interrupt_requests() as interrupt_requested:
        return anyio.run(
            lambda: _attach_submitted_run(
                submitted,
                out=stream,
                poll_interval=poll_interval,
                interrupt_requested=interrupt_requested,
            )
        )


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
