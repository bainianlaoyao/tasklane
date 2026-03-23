from pathlib import Path

import pytest

from tasklane.bootstrap import apply_bootstrap, build_bootstrap_preview_lines, main


def test_build_bootstrap_preview_lines_describe_local_state() -> None:
    lines = build_bootstrap_preview_lines()

    assert any("tasklane home:" in line for line in lines)
    assert any("sqlite db:" in line for line in lines)
    assert any("log dir:" in line for line in lines)
    assert any("tasklane daemon --poll-interval 0.2" in line for line in lines)


def test_bootstrap_preview_prints_local_setup(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main([])

    captured = capsys.readouterr()

    assert exit_code == 0
    assert "sqlite db:" in captured.out
    assert "tasklane daemon --poll-interval 0.2" in captured.out


def test_apply_bootstrap_initializes_sqlite_and_logs_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("TASKLANE_HOME", str(tmp_path / ".tasklane"))

    state = apply_bootstrap()

    assert state.db_path.exists()
    assert state.logs_dir.exists()
