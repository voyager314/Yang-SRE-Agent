# Repository Guidelines

## Project Structure & Module Organization

Application code lives in `src/sre_agent/`. Keep orchestration and provider-neutral behavior in `core/`, command-line commands in `cli.py`, settings in `config.py`, reusable template helpers in `utils/`, Jinja prompts in `prompts/`, and built-in diagnostic integrations in `toolsets/` (Python tools plus YAML definitions). Place tests in `tests/`; the current suite is `tests/test_core.py`. Do not commit local output under `temp/`, virtual environments, or cache directories.

## Build, Test, and Development Commands

Use Python 3.13 and uv for the normal workflow:

- `uv sync --dev` installs the application and development dependencies.
- `uv run pytest` runs the test suite.
- `uv run ruff check .` checks imports, style, and common Python errors.
- `uv run ruff format --check .` verifies formatting; use `uv run ruff format .` to apply it.
- `uv run mypy src` runs the strict type checks configured in `pyproject.toml`.
- `uv run sre-agent --help` verifies the packaged CLI; use `ask`, `chat`, or `toolset` subcommands for manual checks.

## Coding Style & Naming Conventions

Follow the existing typed Python style: four-space indentation, `from __future__ import annotations`, 100-character lines, and standard Ruff import ordering. Use `snake_case` for modules, functions, variables, and test methods; `PascalCase` for classes and Pydantic models; and `UPPER_SNAKE_CASE` for module constants. Keep public functions typed and satisfy strict mypy rather than adding broad `Any` annotations. Name toolset YAML files after the integration, such as `kubernetes.yaml`.

## Testing Guidelines

Write pytest tests named `test_<behavior>` and group related cases in `Test<Feature>` classes. Test observable outcomes, including error and prerequisite paths, and mock LLM or external command boundaries so the suite needs no credentials, cluster, or network access. Run `uv run pytest`, Ruff, and mypy before opening a pull request; no coverage threshold is currently configured.

## Commit & Pull Request Guidelines

The two existing commits use short lowercase subjects (for example, `update`), with no enforced convention. Prefer a concise imperative subject that identifies the affected area, such as `add prometheus timeout handling`. Keep commits focused. Pull requests should explain the behavior change, list validation commands run, link related issues, and include terminal output or screenshots for CLI-visible changes.

## Configuration & Secrets

Runtime configuration is read from `~/.sre-agent/config.yaml`, optional `models.yaml`, and `SRE_AGENT_` environment variables. Never commit API keys, production endpoints, credentials, or locally generated configuration files.
