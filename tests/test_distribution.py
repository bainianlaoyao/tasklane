from __future__ import annotations

import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_exposes_short_global_commands() -> None:
    data = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    scripts = data["project"]["scripts"]

    assert scripts["tasklane"] == "tasklane.cli:main"
    assert scripts["tasklane-bootstrap"] == "tasklane.bootstrap:main"
    assert scripts["pcs"] == "tasklane.cli:main"
    assert scripts["pcs-bootstrap"] == "tasklane.bootstrap:main"
    assert scripts["prefect-submit"] == "tasklane.cli:main"
    assert scripts["prefect-bootstrap"] == "tasklane.bootstrap:main"


def test_install_scripts_exist_for_windows_and_linux() -> None:
    assert (REPO_ROOT / "scripts" / "install-windows.ps1").exists()
    assert (REPO_ROOT / "scripts" / "install-linux.sh").exists()


def test_repository_has_open_source_metadata_docs() -> None:
    assert (REPO_ROOT / "LICENSE").exists()
    assert (REPO_ROOT / "CONTRIBUTING.md").exists()
    assert (REPO_ROOT / "RELEASING.md").exists()
    assert (REPO_ROOT / "docs" / "SKILL-INSTALL.md").exists()
