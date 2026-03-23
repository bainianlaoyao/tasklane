from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from contextlib import suppress
from datetime import datetime, timezone

from prefect import flow, get_run_logger, runtime, task
from prefect.artifacts import create_markdown_artifact
from prefect.client.orchestration import get_client
from prefect.concurrency.sync import concurrency
from prefect.exceptions import CancelledRun

from .attach import encode_command_output_message, encode_scheduler_event_message
from .models import CommandTask
from .routing import route_task


CANCEL_POLL_INTERVAL_SECONDS = 0.5


def format_command(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def capture_git_context(cwd: str) -> dict[str, object]:
    def _run_git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
        )

    sha_result = _run_git("rev-parse", "HEAD")
    if sha_result.returncode != 0:
        return {"git_sha": None, "git_dirty": None}
    status_result = _run_git("status", "--short")
    return {
        "git_sha": sha_result.stdout.strip() or None,
        "git_dirty": bool(status_result.stdout.strip()),
    }


def build_execution_markdown(
    task_payload: CommandTask,
    git_context: dict[str, object] | None = None,
) -> str:
    git_context = git_context or {"git_sha": None, "git_dirty": None}
    env_lines = "\n".join(
        f"- `{key}={value}`" for key, value in sorted(task_payload.env_overrides.items())
    ) or "- `<none>`"
    labels = task_payload.metadata.get("labels") or []
    label_lines = ", ".join(f"`{label}`" for label in labels) if labels else "`<none>`"
    return (
        "# Execution Spec\n\n"
        f"- cwd: `{task_payload.cwd}`\n"
        f"- project: `{task_payload.project or '<none>'}`\n"
        f"- resource_class: `{task_payload.resource_class}`\n"
        f"- run_name: `{task_payload.run_name or '<none>'}`\n"
        f"- labels: {label_lines}\n\n"
        f"- git_sha: `{git_context.get('git_sha') or '<none>'}`\n"
        f"- git_dirty: `{git_context.get('git_dirty')}`\n\n"
        "## Command\n"
        "```powershell\n"
        f"{format_command(task_payload.command)}\n"
        "```\n\n"
        "## Env Overrides\n"
        f"{env_lines}\n\n"
        "## Metadata\n"
        "```json\n"
        f"{json.dumps(task_payload.metadata, ensure_ascii=False, indent=2)}\n"
        "```\n\n"
        "## Notes\n"
        f"{task_payload.notes or '<none>'}\n"
    )


@task
def publish_execution_spec(task_payload: CommandTask, git_context: dict[str, object]) -> None:
    create_markdown_artifact(
        key=f"execution-spec-{int(time.time())}",
        markdown=build_execution_markdown(task_payload, git_context=git_context),
    )


def build_result_markdown(result: dict[str, object]) -> str:
    return (
        "# Execution Result\n\n"
        f"- status: `{result['status']}`\n"
        f"- exit_code: `{result['exit_code']}`\n"
        f"- started_at: `{result['started_at']}`\n"
        f"- finished_at: `{result['finished_at']}`\n"
        f"- duration_seconds: `{result['duration_seconds']}`\n"
        f"- stderr_summary: `{result.get('stderr_summary') or '<none>'}`\n"
    )


@task
def publish_execution_result(result: dict[str, object]) -> None:
    create_markdown_artifact(
        key=f"execution-result-{int(time.time())}",
        markdown=build_result_markdown(result),
    )


@task
def run_command(task_payload: CommandTask) -> dict[str, object]:
    logger = get_run_logger()
    env = os.environ.copy()
    env.update(task_payload.env_overrides)
    route = route_task(task_payload)
    with concurrency(list(route.concurrency_slots), strict=True):
        process = subprocess.Popen(
            task_payload.command,
            cwd=task_payload.cwd,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=1,
        )
        started_at = datetime.now(timezone.utc)
        start_fields: dict[str, object] = {}
        if getattr(process, "pid", None) is not None:
            start_fields["pid"] = process.pid
        logger.info(encode_scheduler_event_message("started", **start_fields))

        stdout_thread = threading.Thread(
            target=_stream_process_output,
            args=(process.stdout, logger.info, "stdout"),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=_stream_process_output,
            args=(process.stderr, logger.warning, "stderr"),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()
        flow_run_id = runtime.flow_run.id
        try:
            return_code = _wait_for_process(process, flow_run_id=flow_run_id)
        except CancelledRun:
            logger.info(encode_scheduler_event_message("finished", status="cancelled", exit_code=130))
            raise
        except BaseException:
            _terminate_process(process)
            raise
        finally:
            stdout_thread.join(timeout=1)
            stderr_thread.join(timeout=1)

    finished_at = datetime.now(timezone.utc)
    status = "completed" if return_code == 0 else "failed"
    logger.info(encode_scheduler_event_message("finished", status=status, exit_code=return_code))
    return {
        "status": status,
        "exit_code": return_code,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": (finished_at - started_at).total_seconds(),
        "stderr_summary": None,
    }


def _stream_process_output(stream: object, log_method: object, stream_name: str) -> None:
    if stream is None:
        return
    for raw_line in iter(stream.readline, ""):
        line = raw_line.rstrip()
        if line:
            log_method(encode_command_output_message(stream_name, line))


def _terminate_process(process: subprocess.Popen[str]) -> None:
    with suppress(Exception):
        process.terminate()


def _wait_for_process(process: subprocess.Popen[str], *, flow_run_id: str | None) -> int:
    while True:
        return_code = process.poll()
        if return_code is not None:
            return return_code
        if flow_run_id and _is_flow_run_cancelled(flow_run_id):
            _terminate_process(process)
            raise CancelledRun("Flow run cancellation detected.")
        time.sleep(CANCEL_POLL_INTERVAL_SECONDS)


def _is_flow_run_cancelled(flow_run_id: str) -> bool:
    with get_client(sync_client=True) as client:
        flow_run = client.read_flow_run(flow_run_id)
    return flow_run.state_name in {"Cancelling", "Cancelled"}


@flow(name="command-executor")
def run_command_task(task_payload: dict[str, object]) -> dict[str, object]:
    parsed = CommandTask.model_validate(task_payload)
    git_context = capture_git_context(parsed.cwd)
    publish_execution_spec(parsed, git_context)
    result = run_command(parsed)
    publish_execution_result(result)
    if int(result["exit_code"]) != 0:
        raise RuntimeError(f"Command failed with exit code {result['exit_code']}")
    return result
