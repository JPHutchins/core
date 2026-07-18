# Home Assistant Core → camas migration

Migrating HA Core's dev/CI task orchestration to
[camas](https://github.com/JPHutchins/camas) as a single source of truth, and
logging genuine camas friction to file as well-scoped upstream issues.

## What is actually being migrated

HA Core does **not** use `invoke`/`tox`/`Makefile`. Its orchestration is spread
across layers, and *that sprawl* is what camas consolidates:

| Layer | Where today | Examples |
|---|---|---|
| Lint/format/type hooks | `.pre-commit-config.yaml` (via `prek`) | ruff-check `--fix`, ruff-format, codespell, yamllint, prettier, zizmor, mypy, pylint, hassfest, gen_requirements_all |
| Dev command menu | `.vscode/tasks.json` | Pytest, Ruff, Prek, Pylint, Generate Requirements, Compile translations |
| Shell scripts | `script/*` | `lint`, `lint_and_test.py`, `hassfest`, `gen_requirements_all`, `translations`, `run-in-env.sh`, `split_tests.py` |
| CI | `.github/workflows/ci.yaml` | the matrix'd re-encoding of the above across a Python-version matrix + test buckets |

camas models these as one root `tasks.py`. The **orchestration/glue** is what
camas replaces; the **functional** scripts (`hassfest`, `gen_requirements_all`,
`translations`) stay and are invoked as camas leaves.

## Current state

- `camas[mcp]==0.1.26` in `requirements_test.txt`.
- `.venv` = `uv pip install -e . -r requirements_test.txt colorlog` (skips
  `requirements_all.txt`; see Env note 1).
- Single-file `tasks.py` (12 tasks), no `Project`, no `name=`, bound nodes:
  `fix` (ruff --fix → format, `mutates`) · `check` = `Parallel(ruff_lint,
  ruff_format_check, mypy, pylint, hassfest, codespell, test)` · `dev =
  Sequential(fix, check)`. `Config(default_task=dev, github_task=check,
  agent=Claude(fix=fix, check=check))`. `default=dev`, `github_default=check`,
  `run_default=check` all resolve.
- `.mcp.json` + `.claude/settings.json` hooks launch camas via `sh
  script/run-in-env.sh camas …` (activates `.venv`; Finding 2). `.camas/` gitignored.
- **Next:** GH Actions SSOT (`--github-matrix`, axis from `.python-version`),
  assessment of HA-scripting removal, and a lint-parallelism benchmark.

## Findings ledger (fileable upstream)

**Filed upstream (2026-07-17):** #216 (anonymous node → null `github_default`), #217
(venv launcher / child PATH + requirements.txt onboarding), #218 (gate `--under` can't
budget a persistently-failing leaf), #219 (`camas_run` no `paths`), #220 (prefix+suffix
`PathScope` matcher), #221 (fix hook should no-op). Cross-project comment added to
existing #214 (redundant `name=`). Findings 0/3/5/6 withdrawn (documented behavior /
camas self-handles / author error) — deliberately *not* filed.

Each finding below became a standalone issue at `JPHutchins/camas`. Status:
`open` / `filed #NNN` / `withdrawn`.

### 0. (meta) Author-time diagnostics for documented anti-patterns — `open` (modest)
Honest framing: that I authored several documented anti-patterns despite the
docs being surfaced (the MCP points at `camas_docs`, which returns the full
module docstring, and I fetched it twice) is mostly a *me* problem — I skimmed
and re-derived — not a camas defect. The one salvageable, **general** suggestion
(useful to any user, not just an agent): a few author-time, rule-citing warnings
in `camas_check`/`camas_list` for documented anti-patterns that currently pass
silently — most concretely an unnamed `Config` task node → `github_default:
null` (Finding 8). camas already does this for *types* (ty); extending it to a
small set of authoring foot-guns is modest DX polish. Not a headline, and not an
LLM-specific concern — a human wiring `Config` hits the same silent null.

### 1. Onboarding assumes a pyproject-managed dev-dependency story — `open`
**docs / onboarding.** Install guidance (`pipx`, `uv tool install`, PEP 621
extras) and `camas mcp init`'s launcher resolution (`uv run`/`uvx`) assume the
project manages dev deps via `pyproject.toml` + `uv sync`, or installs camas as a
standalone tool. HA has no `[project.optional-dependencies]`, no
`[dependency-groups]`, and never runs `uv sync`; all dev tooling is pinned in
`requirements_test.txt` and installed with `uv pip install`. A pyproject pin —
the "obvious" placement — would never be installed.
**Ask:** document the requirements-file model; have `camas mcp init` detect
`.venv` + a requirements file as a launcher/pin strategy.

### 2. No venv-activating launcher; camas doesn't add its bin to child PATH — `open` (headline)
**feature gap (hard evidence).** For the requirements.txt model, tools live in
`.venv/bin`. Two compounding problems: (a) `camas mcp init --claude` writes
`command: uvx camas[mcp]==… mcp` **even when run from an activated venv** where
`camas` is already `.venv/bin/camas` — and a uvx server is isolated from the
project venv, so it can't see `ruff`/`mypy`/`pytest`; `--launcher` offers
`uv|uvx|camas`, none of which *activates a project venv*. (b) camas does not
prepend its interpreter's `bin/` to task-subprocess PATH — proven: `PATH=<no
.venv/bin> .venv/bin/camas ruff_lint` → `no such file or directory: ruff`. So
even an absolute-path launcher wouldn't find the tools. **Workaround here:** wrap
with HA's `script/run-in-env.sh` (activates `.venv`) in `.mcp.json` + every hook.
**Ask:** a first-class venv-activating launcher for `camas mcp init` (detect
`.venv`/`VIRTUAL_ENV`), and/or prepend the interpreter's `bin/` to child PATH.

### 3. `.camas/` gitignore — `withdrawn` (camas self-ignores)
camas writes `.camas/.gitignore` containing `*`, so the directory's contents
(runs, timings) are ignored with no root `.gitignore` entry — `git check-ignore
.camas/runs` confirms. My root `.gitignore` edit was redundant and was reverted.
Not a finding; author error (didn't check for the self-ignore).

### 4. `camas_run` (MCP) has no `paths` argument — `open`
**MCP surface gap.** The CLI has `--paths` and the whole gate is path-scoped, but
the `camas_run` MCP tool exposes only `task/args/under/matrix_overrides/jobs/
dry_run/verbosity` — no way to reproduce `camas <task> --paths <changed files>`
from an agent. So an agent can run a whole task or the gate, but not an ad-hoc
scoped run of an arbitrary task.
**Ask:** add a `paths` argument to `camas_run` (or document that the gate is the
only scoped-run entry point).

### 5. Gate runs the whole tree on a trivial edit — `withdrawn` (documented + author error)
The Stop gate ran `mypy`/`pylint`/`hassfest`/`codespell` over all of
`homeassistant/` after I edited only `tasks.py`. Not a bug: (a) the module
docstring (`__init__.py:52-55`) states a cold timing cache runs the whole tree
under a budget until leaves are measured; (b) `mypy`/`pylint` take file args, so
they *should* carry `{paths}` (docstring L85-88) — I didn't add it. Author gap,
not a camas defect. (There may be a mild UX note — a nominal `--under 5s` gate
silently launching a multi-minute cold run is surprising — but the behavior is
documented, so at most a docs-emphasis suggestion, not an issue.)

### 6. `when=` vs `{paths}` disambiguation — `withdrawn` (documented in the opening docstring)
The rule "a leaf whose command can't take `{paths}` instead sets `when=`" is
stated plainly in the opening module docstring (`__init__.py:85-88`), not buried.
My misuse was not reading it. Not a camas finding.

### 7. No declarative prefix+suffix/`types:` matcher to port pre-commit filters — `open`
**verbosity / feature gap.** pre-commit hooks carry rich filters — hassfest on
`(icons|manifest|strings)\.json|…|requirements.+\.txt`, mypy on
`^(homeassistant|pylint)/.+\.(py|pyi)$`. camas `paths=` is `str | PathScope`
(single dir prefix, or a callable); `by_suffix` filters by suffix only, not
"changed `.py` *under* `homeassistant/`". Faithful ports need a hand-written
Python predicate per leaf.
**Ask:** a declarative prefix+suffix/glob matcher (a `types:`-style shorthand).

### 8. The monorepo doc example yields a null `github_default` — `open`
**docs/UX gotcha.** The README shows `Config(github_task=Parallel(libs, api))` —
an *anonymous* inline node. camas_list resolves `github_default` from the node's
name, so an anonymous task there reports `github_default: null` (and
`run_default: null`), silently breaking "run exactly what CI runs" discovery and
the pre-push hook story. Binding it first (`ci_all = Parallel(...)`;
`github_task=ci_all`) fixes it.
**Ask:** either name composed Config nodes automatically, or warn when a
`Config` task field is an unnamed node; update the monorepo example to bind it.

### 9. `camas mcp fix` (PostToolBatch autofix) should fail-safe to a no-op — `open`
**robustness.** The PostToolBatch hook `camas mcp fix` **blocked agent
continuation** when its launcher failed (`sh: 0: cannot open
script/run-in-env.sh` — a relative launcher path invoked from the wrong cwd).
The immediate cause is mine (relative `sh script/run-in-env.sh` launcher assumes
cwd = repo root), but the durable ask is camas's: the free, best-effort autofix
hook should degrade to a no-op on *any* launcher/env/config failure and never
stop the turn — the same fail-safe the Stop gate already applies for a missing
check node / tasks.py load error. A broken autofix should cost nothing, not halt
the agent.
**Ask:** `camas mcp init --claude` should emit a non-blocking fix hook (e.g. a
trailing `|| true`, or camas exiting 0 when it can't run), and prefer a
cwd-independent launcher (`$CLAUDE_PROJECT_DIR`-anchored) so a changed cwd can't
break it.

## Not camas bugs (author error / environment — recorded for honesty, not filed)

- **`name=` and my "github_default is broken" confusion.** I repeatedly stamped
  `name=` and mis-declared an anonymous github node; the fix was to *bind* nodes
  and declare them in `Config`. Author error, not a camas defect (the residual
  docs angle is Finding 8).
- **Forcing `Project()`/per-integration children.** HA's split source/test trees
  (`homeassistant/components/X` vs `tests/components/X`) make integrations
  non-viable monorepo children; trying anyway produced duplication and a
  shared-import smell. That's "don't use monorepo where there are no
  subprojects," not a camas bug.
- **Env note 1 — partial venv.** Skipping `requirements_all.txt` (one dep,
  `dtlssocket` via `pytradfri[async]`, needs `autoconf`) leaves integration deps
  uninstalled, so `mypy`/`hassfest` hit `ModuleNotFoundError: hassil`. Not camas.
- **Env note 2 — config fidelity IS the SSOT value, not a defect.** Getting the
  `codespell` leaf right (HA's `--ignore-words-list` + the `generated/`/`fixtures/`/
  `snapshots/` excludes) took two tries — precisely because HA's codespell config
  lives only in `.pre-commit-config.yaml` and had to be *re-encoded* here. Under
  camas-as-SSOT that config is defined once in `tasks.py` and local + CI + gate all
  run it; the re-encoding pain is the deficiency camas removes, not a camas flaw.
  (`mypy` would likewise need HA's `mypy.ini`/`.strict-typing` scoping to be faithful
  — same story; the partial venv also blocks it here regardless.)

## GH Actions SSOT (assessment)

- CI Python matrix = `.python-version` (default `3.14.5`) + `ADDITIONAL_PYTHON_VERSIONS`
  (`[]` today), merged via `jq` (ci.yaml L164-168). Test job matrixes `python_versions ×
  group[1..10]`, where `group` = `script/split_tests.py`'s dynamic count-balanced buckets.
- **`--github-matrix` works and is a real SSOT for the version list** (verified). A `PY`
  axis sourced from `.python-version` (`test_matrix` in tasks.py) emits `{"PY":
  ["3.14.5"]}` via `camas_github_matrix`; `--PY 3.13,3.14` override emits `{"PY":
  ["3.13","3.14"]}`. Pattern: a GHA `discover` job runs `camas test_matrix
  --github-matrix`, downstream jobs `fromJSON` it — the version list lives once in
  `.python-version`, never re-encoded in YAML. camas owns the LIST; GHA `setup-python`
  consumes each value (the README's "YAML-side axis composes with `fromJSON(...).PY`").
- **What does NOT map:** the test-bucket fan-out. `split_tests.py` packs ~1000 test dirs
  into N *count-balanced* buckets at runtime (`pytest --collect-only` + greedy pack →
  `pytest_buckets.txt`) — a dynamic partition, not a static cross-product, so camas can
  emit the `GROUP` numbers but not the balancing; `split_tests.py` stays. Reasonable
  boundary, and the honest limit of the matrix-SSOT story for HA.

## Scripting-removal assessment (what camas subsumes)

From the full orchestration map. camas replaces the **glue**, not the tools/scripts:

- **camas REPLACES (orchestration):** the `.github/workflows/ci.yaml` lint-job sprawl
  (10 parallel jobs: `prek`, `zizmor`, `pylint`, `pylint-tests`, `mypy`, `hassfest`,
  `gen-requirements-all`, `gen-copilot-instructions`, `audit-licenses`, `hadolint` →
  one `camas check`/`lint` that parallelizes on one machine); the `info` job's
  full-vs-partial/lint-only dispatch; `script/lint`, `script/lint_and_test.py`,
  `script/check_format`, `script/server`; and the `.vscode/tasks.json` labels +
  `dependsOn` chains. The `.pre-commit-config.yaml` orchestration also folds in (though
  `prek` is still wanted as the git-hook driver).
- **STAYS as functional leaves camas CALLS:** `script/hassfest`, `gen_requirements_all`,
  `gen_copilot_instructions`, `licenses`, `translations`, `check_requirements`,
  `scaffold`, `split_tests.py` (the packing algorithm), `check_dirty`, and the tools
  themselves (ruff/pylint/mypy/pytest/codespell/zizmor/yamllint/prettier/hadolint).
- **STAYS in GitHub Actions (infra camas doesn't own):** venv build/cache, `.mypy_cache`
  restore, artifact up/download, Codecov uploads, `dependency-review`, DB service
  containers, the strategy-matrix expansion itself, and all repo-automation workflows
  (`builder`, `wheels`, `codeql`, `stale`, `lock`, issue bots, translations upload, e2e).
- **One definition, context-appropriate dispatch.** The tree and its matrix are declared once;
  camas dispatches the *same* definition across **GH runners** in CI (`--github-matrix` →
  `strategy.matrix`) and across **local processes/cores** in dev. That SSOT-dispatch — not any
  "1/N runner-minutes" cost angle — is the win: a developer runs the exact matrix CI runs, and
  HA's per-hook parallelism (today only `script/lint_and_test.py`'s `asyncio.gather(pylint, ruff)`)
  comes from the same source as the CI fan-out.

## Finish line (next session)

The `.venv` was intentionally partial (skipped `requirements_all.txt`), so `mypy`/`hassfest`/
`test` fail on missing imports (`hassil`, `paho`, integration libs) and pre-existing strictness.
That is an environment artifact, not the migration — the goal is a **real full-deps env** where
`camas check` reproduces HA CI green.

1. **Full deps — DONE.** `autoconf`/`automake`/`libtool` installed (June); the full
   `uv pip install -e . -r requirements_all.txt -r requirements_test.txt` reconciled the env
   (1667 pkgs, `dtlssocket` built; `hassil`/`paho.mqtt`/`pyoverkiz`/`pytradfri` all import OK).
   The env is real now — no more partial-venv artifacts. (`hassfest -p metadata` already green.)
2. **Verify CI reproduction.** With real deps, `mypy homeassistant pylint` (reads `mypy.ini`),
   `pylint homeassistant`, `hassfest`, and `pytest tests` should go green like HA CI — run
   `camas check` (the `github_task`) and confirm. The 1294 mypy errors were the missing-deps
   artifact; with deps + `mypy.ini` they should clear.
3. **Restore the gate.** The gate was narrowed to `ruff`-only because `mypy`/`pylint` failed on
   the partial env (and #218: a failing leaf can't be `--under`-excluded). With green lint,
   either fold `mypy`/`pylint` back into `agent.check`, or keep the gate lean (ruff) with a green
   full `check` in CI — decide per how fast lint runs.
4. **PR.** Optionally open the PR on `JPHutchins/core@migrate-to-camas`.

## Overall assessment: is camas a win for a project the size of HA?

**Where camas clearly wins:**

1. **SSOT kills the 3–4× duplication.** HA's lint/format/type invocations are re-encoded in
   `.pre-commit-config.yaml`, `.github/workflows/ci.yaml` (one job each), `.vscode/tasks.json`,
   and `script/lint`/`lint_and_test.py`. A ruff-version or arg change today touches several of
   these and drifts silently. camas defines the tree **once**; local dev, the agent gate, and CI
   run the same nodes. This is the biggest concrete win for HA.
2. **Agent-gated per-edit loop at 1400-integration scale.** HA takes a firehose of
   drive-by + increasingly LLM-assisted contributions. A deterministic `FileChanged → fix`
   plus a scoped tripwire that mirrors CI (`{paths}`/`when=` = the pre-commit `files:` filters)
   keeps a contributor's change green in their own context, off the maintainer's plate.
3. **Matrix SSOT with context-appropriate dispatch (the core value).** The matrix — e.g. the
   Python-version axis sourced from `.python-version` — is defined **once** in `tasks.py`.
   `camas <task> --github-matrix` emits it so GitHub fans out across N runners; `camas <task>`
   locally fans the *same* matrix across processes/cores. One definition → CI dispatches over
   runners, dev dispatches over cores, and a developer reproduces the exact CI matrix locally,
   with zero YAML/local duplication. Verified: `.python-version` → `{"PY": ["3.14.5"]}`.
4. **Typed, testable task defs.** `tasks.py` is typed Python checked by ty/mypy (`camas_check`)
   — vs YAML/shell that drifts without a checker.
5. **(secondary, downstream of #3)** Because the same tree can run as one camas job on a single
   runner (parallel across cores) rather than N GH jobs, paid-runner minutes drop — but that's a
   *consequence* of the SSOT-dispatch in #3, not the point, and it's blunted for HA by free OSS runners.

**Where camas is *not* the win (honest boundaries):**

- Doesn't own the **dynamic test-bucket sharding** (`split_tests.py`'s count-balanced packing);
  camas emits the group axis, not the balancing.
- Doesn't replace **GH Actions infra** — venv cache, artifacts, Codecov, DB service containers,
  matrix expansion, repo-automation bots all stay.
- The **functional scripts** (hassfest, gen_requirements, translations) stay; camas just calls them.
- Small, seldom-used **dev helpers** (`scaffold`, `version_bump`, …) don't want SSOT/parallelism at
  all — leave them as plain `python -m script.X`.

**Net:** for HA the payoff is (1) collapsing the pre-commit/CI/vscode/script duplication into one
authoritative tree, and (2) the agent-gated contributor loop — not a wholesale replacement of GH
Actions. The parallelism-cost win lands hardest on paid-runner (enterprise) setups.
