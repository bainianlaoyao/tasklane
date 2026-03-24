from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Sequence

from .attach import SubmittedRun, attach_submitted_run, format_scheduler_event_line, submit_task
from .models import CommandTask, RESOURCE_CLASSES, ResourceClass
from .routing import RESOURCE_SLOT_CAPACITY, route_task
from .scheduler import Scheduler
from .state import ACTIVE_STATUSES, RunRecord, SchedulerState, utc_now


@dataclass(frozen=True)
class SubmitArgs:
    cwd: str
    project: str | None
    resource: ResourceClass
    run_name: str | None
    notes: str | None
    labels: list[str]
    env: list[str]
    detach: bool
    command: list[str]


@dataclass(frozen=True)
class DaemonArgs:
    poll_interval: float
    once: bool


@dataclass(frozen=True)
class QueueArgs:
    db_path: str | None
    watch: bool
    interval: float
    json: bool


def parse_submit_args(argv: Sequence[str]) -> SubmitArgs:
    parser = argparse.ArgumentParser(description="Submit a command to Tasklane.")
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--project")
    parser.add_argument("--resource", required=True, choices=RESOURCE_CLASSES)
    parser.add_argument("--run-name")
    parser.add_argument("--notes")
    parser.add_argument("--label", dest="labels", action="append", default=[])
    parser.add_argument("--env", action="append", default=[])
    parser.add_argument("--detach", action="store_true")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    namespace = parser.parse_args(list(argv))

    command = list(namespace.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("missing command after --")

    return SubmitArgs(
        cwd=namespace.cwd,
        project=namespace.project,
        resource=namespace.resource,
        run_name=namespace.run_name,
        notes=namespace.notes,
        labels=list(namespace.labels),
        env=list(namespace.env),
        detach=bool(namespace.detach),
        command=command,
    )


def parse_daemon_args(argv: Sequence[str]) -> DaemonArgs:
    parser = argparse.ArgumentParser(description="Run the local Tasklane daemon.")
    parser.add_argument("--poll-interval", type=float, default=0.2)
    parser.add_argument("--once", action="store_true", help="Run one scheduling batch and exit.")
    namespace = parser.parse_args(list(argv))
    return DaemonArgs(poll_interval=float(namespace.poll_interval), once=bool(namespace.once))


def parse_queue_args(argv: Sequence[str]) -> QueueArgs:
    parser = argparse.ArgumentParser(description="Show the local Tasklane queue.")
    parser.add_argument("--db-path")
    parser.add_argument("--watch", action="store_true", help="Refresh the queue view until interrupted.")
    parser.add_argument("--interval", type=float, default=1.0, help="Refresh interval for --watch.")
    parser.add_argument("--json", action="store_true", help="Emit queue state as JSON.")
    namespace = parser.parse_args(list(argv))
    return QueueArgs(
        db_path=namespace.db_path,
        watch=bool(namespace.watch),
        interval=float(namespace.interval),
        json=bool(namespace.json),
    )


def _parse_env_overrides(entries: Sequence[str]) -> dict[str, str]:
    env: dict[str, str] = {}
    for entry in entries:
        key, sep, value = entry.partition("=")
        if not sep:
            raise ValueError(f"Invalid env override: {entry}")
        env[key] = value
    return env


def build_command_task(args: SubmitArgs) -> CommandTask:
    metadata = {
        "resource_class": args.resource,
        "labels": args.labels,
    }
    return CommandTask(
        cwd=args.cwd,
        project=args.project,
        command=args.command,
        env_overrides=_parse_env_overrides(args.env),
        metadata=metadata,
        run_name=args.run_name,
        notes=args.notes,
    )


def print_submitted_event(submitted: SubmittedRun) -> None:
    print(
        format_scheduler_event_line(
            "submitted",
            run_id=submitted.run_id,
            queue=submitted.queue_name,
            resource=submitted.resource_class,
        )
    )


def _run_daemon(argv: Sequence[str]) -> int:
    args = parse_daemon_args(argv)
    state = SchedulerState.initialize()
    scheduler = Scheduler(state, poll_interval=args.poll_interval)
    if args.once:
        scheduler.run_once(limit=10)
        return 0
    scheduler.run_forever(limit=10)
    return 0


def _run_queue(argv: Sequence[str]) -> int:
    args = parse_queue_args(argv)
    state = SchedulerState.initialize(args.db_path) if args.db_path else SchedulerState.initialize()
    try:
        while True:
            runs = state.list_runs()
            rendered = render_queue_snapshot(runs, as_json=args.json)
            if args.watch and sys.stdout.isatty():
                sys.stdout.write("\x1b[2J\x1b[H")
            print(rendered)
            if not args.watch:
                return 0
            time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0


def render_queue_snapshot(runs: list[RunRecord], *, as_json: bool) -> str:
    if as_json:
        return json.dumps(build_queue_snapshot(runs), ensure_ascii=False, indent=2)
    return format_queue_snapshot(build_queue_snapshot(runs))


def build_queue_snapshot(runs: list[RunRecord]) -> dict[str, object]:
    updated_at = utc_now()
    status_counts: dict[str, int] = {}
    for run in runs:
        status_counts[run.status] = status_counts.get(run.status, 0) + 1

    resource_usage = dict.fromkeys(RESOURCE_SLOT_CAPACITY, 0)
    for run in runs:
        if run.status not in ACTIVE_STATUSES:
            continue
        for slot in route_task(run.task).concurrency_slots:
            resource_usage[slot] = int(resource_usage.get(slot, 0)) + 1

    return {
        "updated_at": updated_at,
        "counts": {
            "total": len(runs),
            **status_counts,
        },
        "resources": [
            {
                "name": slot,
                "used": int(resource_usage.get(slot, 0)),
                "capacity": capacity,
            }
            for slot, capacity in RESOURCE_SLOT_CAPACITY.items()
        ],
        "runs": [
            {
                "run_id": run.run_id,
                "run_name": run.task.run_name or run.run_id,
                "status": run.status,
                "queue_name": run.queue_name,
                "resource_class": run.resource_class,
                "project": run.task.project,
                "pid": run.pid,
                "exit_code": run.exit_code,
                "created_at": run.created_at,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "age_seconds": _seconds_since(run.created_at),
                "command": run.task.command,
                "cwd": run.task.cwd,
            }
            for run in _sort_runs_for_display(runs)
        ],
    }


def format_queue_snapshot(snapshot: dict[str, object]) -> str:
    counts = snapshot["counts"]
    resources = snapshot["resources"]
    runs = snapshot["runs"]
    count_line = " ".join(f"{key}={value}" for key, value in counts.items())
    resource_line = " | ".join(
        f"{item['name']} {item['used']}/{item['capacity']}"  # type: ignore[index]
        for item in resources  # type: ignore[assignment]
    )
    lines = [
        "Tasklane Queue",
        f"Updated: {snapshot['updated_at']}",
        f"Counts: {count_line}",
        f"Resources: {resource_line}",
        "",
    ]
    if not runs:
        lines.append("No runs found.")
        return "\n".join(lines)

    headers = ("STATUS", "RESOURCE", "QUEUE", "RUN", "PID", "EXIT", "AGE", "COMMAND")
    rows = [
        (
            str(run["status"]),
            str(run["resource_class"]),
            str(run["queue_name"]),
            _truncate(str(run["run_name"]), 24),
            "" if run["pid"] is None else str(run["pid"]),
            "" if run["exit_code"] is None else str(run["exit_code"]),
            format_duration(float(run["age_seconds"])),
            _truncate(" ".join(run["command"]), 60),  # type: ignore[arg-type]
        )
        for run in runs  # type: ignore[assignment]
    ]
    widths = [
        max(len(headers[index]), *(len(row[index]) for row in rows))
        for index in range(len(headers))
    ]
    lines.append(_format_row(headers, widths))
    lines.append(_format_row(tuple("-" * width for width in widths), widths))
    lines.extend(_format_row(row, widths) for row in rows)
    return "\n".join(lines)


def _format_row(columns: tuple[str, ...], widths: list[int]) -> str:
    return "  ".join(value.ljust(widths[index]) for index, value in enumerate(columns))


def _truncate(value: str, width: int) -> str:
    if len(value) <= width:
        return value
    return value[: width - 3] + "..."


def _sort_runs_for_display(runs: list[RunRecord]) -> list[RunRecord]:
    status_order = {
        "running": 0,
        "starting": 1,
        "queued": 2,
        "cancelled": 3,
        "failed": 4,
        "completed": 5,
        "crashed": 6,
    }
    return sorted(runs, key=lambda run: (status_order.get(run.status, 99), run.created_at))


def _seconds_since(timestamp: str) -> float:
    started = datetime.fromisoformat(timestamp)
    return max((datetime.now(timezone.utc) - started).total_seconds(), 0.0)


def format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{int(seconds)}s"
    if seconds < 3600:
        minutes, rem = divmod(int(seconds), 60)
        return f"{minutes}m{rem:02d}s"
    hours, rem = divmod(int(seconds), 3600)
    minutes = rem // 60
    return f"{hours}h{minutes:02d}m"


def main(argv: Sequence[str] | None = None) -> int:
    effective_argv = list(sys.argv[1:] if argv is None else argv)
    if effective_argv and effective_argv[0] == "daemon":
        return _run_daemon(effective_argv[1:])
    if effective_argv and effective_argv[0] == "queue":
        return _run_queue(effective_argv[1:])

    args = parse_submit_args(effective_argv)
    state = SchedulerState.initialize()
    task = build_command_task(args)
    submitted = submit_task(task, state=state)
    print_submitted_event(submitted)
    if args.detach:
        return 0
    return attach_submitted_run(submitted, out=sys.stdout, state=state)


if __name__ == "__main__":
    raise SystemExit(main())
