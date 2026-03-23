# Releasing

## 1. Prepare the release

- Update the version in `pyproject.toml`.
- Review `README.md` install examples and command names.
- Make sure `LICENSE`, `CONTRIBUTING.md`, and install scripts are current.

## 2. Verify locally

```powershell
uv sync --group dev
uv run --group dev pytest
uv tool install -e . --force
tasklane --help
tasklane-bootstrap --help
```

## 3. Publish on GitHub

- Commit the release changes.
- Create a tag such as `v0.1.0`.
- Push the branch and tag to GitHub.
- Create a GitHub Release from the tag.

## 4. Optional future distribution

If you later publish to PyPI, keep the GitHub install path working as the documented fallback:

```powershell
uv tool install git+https://github.com/<owner>/tasklane.git
```
