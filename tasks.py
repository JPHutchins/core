"""camas task definitions for Home Assistant Core.

Single source of truth for the dev/CI task tree, migrated from HA's scattered
orchestration (prek/pre-commit, script/*, .vscode/tasks.json, GitHub Actions).
Work in progress — see MIGRATION.md for the migration narrative and the running
list of camas friction/shortcomings being filed upstream.

Assumes camas runs inside HA's .venv (see requirements_test.txt), so the bare
tool names below resolve to .venv/bin/*. Heavy leaves carry `{paths}`/`when=`
scopes that mirror the pre-commit `files:` filters, so the gate checks only
changed files while a full `camas check` (CI) still covers the whole default.
"""

from pathlib import Path

from camas import Claude, Config, Parallel, Sequential, Task
from camas.v0.task import PathScope, by_suffix


def under(
    prefixes: tuple[str, ...], suffixes: tuple[str, ...], default: tuple[str, ...]
) -> PathScope:
    """Build a PathScope for a prefix+suffix filter.

    Changed files under `prefixes` with `suffixes` on a scoped run; `default` on a
    full run — the prefix+suffix filter that pre-commit `files:` regexes express.
    """

    def scope(changed: tuple[str, ...]) -> tuple[str, ...]:
        if not changed:
            return default
        return tuple(
            p for p in changed if p.startswith(prefixes) and p.endswith(suffixes)
        )

    return scope


py_files = by_suffix((".py", ".pyi"), default=(".",))

ruff_fix = Task("ruff check --fix {paths}", mutates=True, paths=py_files)
ruff_format = Task("ruff format {paths}", mutates=True, paths=py_files)
fix = Sequential(ruff_fix, ruff_format)

ruff_lint = Task("ruff check {paths}", paths=py_files)
ruff_format_check = Task("ruff format --check {paths}", paths=py_files)
mypy = Task(
    "mypy {paths}",
    paths=under(
        ("homeassistant/", "pylint/"), (".py", ".pyi"), ("homeassistant", "pylint")
    ),
)
pylint = Task(
    "pylint {paths}",
    paths=under(("homeassistant/",), (".py", ".pyi"), ("homeassistant",)),
)
hassfest = Task("python3 -m script.hassfest", when=("homeassistant", "requirements"))
codespell = Task(
    "codespell {paths} "
    "--ignore-words-list=aiport,astroid,checkin,currenty,hass,iif,incomfort,lookin,nam,NotIn "
    "--skip=./.*,*.csv,*.json,*.ambr",
    paths=".",
)
test = Task(
    "pytest {paths} --timeout=10", paths=under(("tests/",), (".py",), ("tests",))
)

py_versions = tuple((Path(__file__).parent / ".python-version").read_text().split())
test_matrix = Parallel(Task("pytest tests --timeout=10"), matrix={"PY": py_versions})

lint = Parallel(ruff_lint, ruff_format_check, mypy, pylint, codespell)
check = Parallel(lint, hassfest, test)
gate = Parallel(ruff_lint, ruff_format_check)
dev = Sequential(fix, check)

_ = Config(
    default_task=dev,
    github_task=check,
    agent=Claude(fix=fix, check=gate),
)
