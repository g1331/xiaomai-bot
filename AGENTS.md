# Developer Guidelines

## Environment Setup
- Use `uv` with Python **3.10+**.
- Install `uv` via the official script, then create a virtual environment and sync dependencies:
  ```bash
  curl -LsSf https://astral.sh/uv/install.sh | sh  # or the Windows PowerShell variant
  uv python install 3.11        # install desired Python version
  uv venv --python 3.11         # create venv
  uv sync                       # install dependencies from pyproject.toml
  ```
- Run the project with `uv run main.py`.

## Pre‑commit Checks
- Run `pre-commit run --files <changed files>` before committing. This repository uses **Ruff** for linting and formatting.

## Tests
- Sample tests are located under `tests/md2img`.
- If static resources are missing, run:
  ```bash
  uv run tests/md2img/download_resources.py
  ```
- Execute the demo tests with:
  ```bash
  uv run tests/md2img/main.py
  ```

## Release Workflow
- To bump a version and generate release notes, run:
  ```bash
  python -m scripts.bump <level> [--no-pre] --commit --tag --changelog
  ```
  See `docs/发布 checklist.md` for details. The script updates version numbers, syncs `uv.lock`, generates `CHANGELOG.md` and creates a Git tag. The release commit message follows:
  ```text
  chore(release): 版本更新 vX → vY
  ```

## Commit & PR Guidelines
- Keep commit messages concise in the format `<type>: <summary>`.
- Group related changes into logical commits.
- Pull requests should describe the purpose of the change and reference any relevant issues.
