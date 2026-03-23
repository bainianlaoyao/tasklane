from __future__ import annotations

import json
import os
import shlex
import subprocess
import threading
import time
from datetime import datetime, timezone
from typing import Callable

from .attach import encode_command_output_message, encode_scheduler_event_message
from .models import CommandTask


CANCEL_POLL_INTERVAL_SECONDS = 0.1


class CancelledRun(RuntimeError):
    pass


class _DefaultLogger:
    def info(self, message: str) -> None:
        return None

    def warning(self, message: str) -> None:
        return None


def get_run_logger() -> _DefaultLogger:
    return _DefaultLogger()


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


def run_command(
    task_payload: CommandTask,
    *,
    cancellation_requested: Callable[[], bool] | None = None,
) -> dict[str, object]:
    logger = get_run_logger()
    env = os.environ.copy()
    env.update(task_payload.env_overrides)
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
    logger.info(encode_scheduler_event_message("started", pid=process.pid))

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
    try:
        while True:
            try:
                return_code = process.poll()
            except KeyboardInterrupt:
                _terminate_process(process)
                raise
            if return_code is not None:
                break
            if cancellation_requested is not None and cancellation_requested():
                _terminate_process(process)
                logger.info(encode_scheduler_event_message("finished", status="cancelled", exit_code=130))
                raise CancelledRun("Run cancellation detected.")
            time.sleep(CANCEL_POLL_INTERVAL_SECONDS)
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


run_command.fn = run_command  # type: ignore[attr-defined]


def _stream_process_output(stream: object, log_method: object, stream_name: str) -> None:
    if stream is None:
        return
    for raw_line in iter(stream.readline, ""):
        line = raw_line.rstrip()
        if line:
            log_method(encode_command_output_message(stream_name, line))


def _terminate_process(process: subprocess.Popen[str]) -> None:
    try:
        process.terminate()
    except Exception:
        return None


def run_command_task(task_payload: dict[str, object]) -> dict[str, object]:
    parsed = CommandTask.model_validate(task_payload)
    result = run_command(parsed)
    if int(result["exit_code"]) != 0:
        raise RuntimeError(f"Command failed with exit code {result['exit_code']}")
    return result
