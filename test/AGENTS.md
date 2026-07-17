# AGENTS.md — test/

Test suite for deadline-cloud-for-cinema-4d. Three categories of tests.

## Directory Layout

```
test/
├── unit/                    # Unit tests (always runnable, no Cinema 4D required)
│   ├── deadline_adaptor_for_cinema4d/
│   └── deadline_submitter_for_cinema4d/
├── integ/                   # Integration tests (Windows only, requires Cinema 4D)
│   ├── test_scenes/         # Test scene definitions
│   ├── test_cinema4d.py     # Parametrized test runner
│   ├── conftest.py          # Test fixtures
│   └── utils.py             # Test utilities
├── integ_xa11y/             # xa11y-driven submitter test, offline mock backend
│   ├── test_cases/          # Self-contained cases: input/ expected/ actual/
│   ├── test_cinema4d.py     # Drives the real submitter dialog via xa11y
│   ├── submitter_ui.py      # C4D-specific controls; re-exports shared controls
│   ├── conftest.py          # Fixtures, incl. deadline_farm (starts the mock)
│   ├── utils.py             # Test utilities
│   └── fixtures/            # Test-only sidecar plugin (auto-opens submitter)
└── installer/               # Installer tests
```

## Running Tests

Always use `hatch run` — do NOT invoke `pytest` directly.

```bash
hatch run test                                    # All unit tests
hatch run test test/unit/<path>                   # One test file or directory
hatch run test -k "test_name"                     # One test by name
hatch run all:test                                # All supported Python versions
hatch run integ:test                              # Integration tests (Windows only)
hatch run test-installer                          # Installer tests
```

## Unit Tests

Unit tests do NOT require Cinema 4D installed. They should use mocks for the `c4d` module and other external dependencies. These are the primary tests run in CI and during development.

When adding new features or fixing bugs, always add unit tests.

## Integration Tests (Windows Only)

Integration tests are currently only supported on Windows. They require Cinema 4D installed with licensing configured.

### Test flow

1. **Scene generation**: Each test case uses scene generation scripts (`scene.py`) to create test scenes with specific configurations
2. **Job bundle generation**: Generated scenes are processed through the submitter code, exporting job bundles to a temporary location
3. **Job bundle validation**: Exported bundles are compared against expected bundles in `expected_job_bundle/`
4. **Scene rendering**: Job bundles are run using OpenJD `run` command with Cinema 4D Commandline
5. **Output validation**: Generated output files are compared with expected output files

### Test scene structure

```
test/integ/test_scenes/<scene_name>/
├── expected_job_bundle/      # Reference job bundle for validation
│   ├── asset_references.yaml
│   ├── parameter_values.yaml
│   └── template.yaml
├── expected_job_output/      # Expected render output
│   └── renders/
└── scene/
    └── scene.py              # Scene generation script
```

### Existing test scenes

| Scene | Renderer | Description |
|-------|----------|-------------|
| `physical` | Physical | Basic physical renderer test |
| `phy_apos_path` | Physical | Path with special characters (apostrophes) |
| `physical_chunking` | Physical | Frame chunking across tasks |
| `physical_multi_takes` | Physical | Multiple takes rendering |
| `physical_textured` | Physical | Scene with textures |
| `physical_tiles` | Physical | Tile rendering |
| `redshift` | Redshift | Basic Redshift render |
| `redshift_takes` | Redshift | Redshift with multiple takes |
| `redshift_textured` | Redshift | Redshift with textures |
| `redshift_textured_with_nonascii_characters` | Redshift | Non-ASCII path handling |
| `redshift_tiles` | Redshift | Redshift tile rendering |

### Adding a new test scene

1. Create a new directory under `test/integ/test_scenes/<scene_name>/`
2. Add a `scene/scene.py` script that generates the test scene programmatically
3. Add `expected_job_bundle/` with the expected template, parameter values, and asset references
4. Add `expected_job_output/` with expected render output files
5. Add `<scene_name>` to the `@pytest.mark.parametrize("test_name", [...])` list in `test_cinema4d.py` so the runner picks it up

### Running specific integration tests

```bash
hatch run integ:test -k "physical"
hatch run integ:test -k "redshift"
hatch run integ:test -k "redshift_tiles"
```

### xa11y-driven integration test (`test/integ_xa11y/`)

Drives the **real Deadline Cloud submitter dialog** with
[xa11y](https://xa11y.dev) instead of calling `internal_create_job_bundle()`
directly. The existing `test/integ/` test calls `internal_create_job_bundle()`,
which validates bundle generation but **skips the entire UI layer** (the Qt
dialog, queue-environment loading, the Export button, the plugin entry point a
user clicks). This test closes that gap: it launches the real Cinema 4D GUI with
the real, unmodified plugin, opens the submitter as a user does, drives it via
the OS accessibility tree, clicks **Export bundle**, and runs the same bundle/
render assertions as the old test. Once we're confident in it, the plan is to
delete `test/integ/` and rename this folder to `test/integ/`.

This file is the single source of truth for the suite — there is no separate
README.

#### The big picture

```
pytest (parent process)
  │
  ├─ deadline_farm fixture
  │     ├─ starts the mock Deadline backend in a SEPARATE process
  │     │     (own GIL — see "Why a separate process" below)
  │     ├─ writes a temp deadline config naming the mock's fake farm/queue
  │     └─ builds the subprocess env overlay (endpoint override, dummy creds,
  │           telemetry opt-out, isolated HOME, DEADLINE_CLOUD_MOCK_MODE=1)
  │
  ├─ build_cinema4d_scene()  ── runs c4dpy input/scene.py ──▶ cube.c4d (in actual/)
  │
  └─ launches Cinema 4D GUI (child process)
         │   env: overlay above + two plugin dirs + python path
         │
         ├─ loads DeadlineCloud.pyp           (real, shipped plugin)
         ├─ loads AutoOpenSubmitter.pyp       (test-only sidecar)
         │      on C4DPL_PROGRAM_STARTED (mock mode):
         │        1. patch socket.getaddrinfo (management.* → 127.0.0.1)
         │        2. patch os.startfile → no-op (no Explorer popup)
         │        3. LoadDocument(cube.c4d)
         │        4. CallCommand(SUBMITTER_PLUGIN_ID)  ◀─ opens real submitter
         │
         └─ Qt submitter dialog appears ──── AWS_ENDPOINT_URL_DEADLINE ───▶ mock
                ▲                                                          (parent)
                │ xa11y drives it via the OS accessibility tree
                │   - wait for dialog, wait for queue-env loading
                │   - run the case's configure(dialog) (optional)
                │   - press "Export bundle"
                ▼
         bundle written to <job_history_dir>/<YYYY-mm>/<bundle-name>/
                │
   parent ◀────┘ copies bundle flat into <case>/actual/
         │
         ├─ assert the mock saw exactly the expected calls (no unmatched routes)
         ├─ openjd check
         ├─ compare against expected/job_bundle/ (golden files)
         ├─ openjd run  (Windows only)
         └─ compare renders against expected/renders/ (Windows only)
```

#### Files

| File | Role |
|------|------|
| `test_cinema4d.py` | The test. Orchestrates scene build → launch → UI drive → assertions. Holds the `_CASES` registry. |
| `conftest.py` | Fixtures: locate Cinema 4D, set `C4DPYTHONPATH`, and `deadline_farm` (starts the mock + builds the subprocess env). |
| `submitter_ui.py` | C4D-specific controls plus re-exports of shared controls from `deadline_test_fixtures.xa11y.controls`. |
| `utils.py` | C4D executable/scene/render helpers and C4D's bundle normalization policy. Generic assertions come from `deadline-cloud-test-fixtures`. |
| `deadline_test_fixtures.deadline_mock` | Scenario-driven Deadline REST-JSON mock, out-of-process lifecycle, observability, config, and environment wiring. |
| `deadline_test_fixtures.job_bundle` | Shared case layout, bundle discovery, validation, and structural comparison. |
| `deadline_test_fixtures.images` | Shared render-image comparison. |
| `fixtures/auto_open_submitter/AutoOpenSubmitter.pyp` | Test-only C4D plugin: auto-opens the real submitter and (mock mode) applies the getaddrinfo / `os.startfile` patches. Never shipped. |
| `test_cases/<name>/` | A self-contained case (see *Anatomy of a test case*). |

#### Anatomy of a test case

Each case is a self-contained folder under `test_cases/<name>/`:

```
test_cases/<name>/
├── input/                 # what you author
│   ├── scene.py           #   required — builds <name>.c4d (runs in c4dpy)
│   └── configure.py       #   OPTIONAL — configure(dialog) drives the dialog
│                          #              before Export (runs in pytest + xa11y)
├── expected/              # what we compare against
│   ├── job_bundle/        #   golden template/parameter_values/asset_references
│   └── renders/           #   golden render PNGs (Windows-only compare)
└── actual/                # gitignored — runtime output; kept on failure
```

Cases are **registered explicitly** in the `_CASES` list in `test_cinema4d.py`
— adding the folder is not enough, you add its name to the list. The expected
bundle works on every platform and is **not** farm-specific (the mock provides
fake, stable farm/queue IDs and no queue environments), so the expected files
are portable and don't need per-farm regeneration.

`input/scene.py` runs inside **c4dpy** (Cinema 4D's headless Python) and is saved
into `actual/` (not `input/`), so the render path `renders/$prj` resolves into
`actual/renders/`. The render comparison derives its directory from the bundle's
`OutputPath` param, so a `configure.py` that overrides the output path is
followed automatically.

#### Finding selectors (harvesting locators for a `configure.py`)

A `configure.py` drives widgets by their accessibility **role + name** (e.g.
`dialog.descendant("check_box[name='Activate detailed logging']")`). You cannot
guess these names — and they differ between macOS (AX) and Windows (UIA), so a
configurator must be verified on both. Harvest the live names with the built-in
dump mode, which prints both settings tabs' accessibility trees and then stops
(no Export):

```bash
# macOS / Linux
DIALOG_DUMP=1 hatch -e integ-xa11y run pytest --no-cov \
    test/integ_xa11y/test_cinema4d.py --numprocesses=0 -s -k <case>
```
```powershell
# Windows PowerShell
$env:DIALOG_DUMP=1; hatch -e integ-xa11y run pytest --no-cov `
    test/integ_xa11y/test_cinema4d.py --numprocesses=0 -s -k <case>; $env:DIALOG_DUMP=$null
```

Each line is `<role> "<name>" value="<value>"`. Match on role + name. Shared
cross-platform widget behavior and selector gotchas are documented in
`deadline_test_fixtures.xa11y.controls`; Cinema 4D-specific selectors remain in
`submitter_ui.py`. Prefer the reusable helpers exposed by `submitter_ui.py` over
raw `descendant(...)` calls.

#### Offline mock architecture

The suite runs **fully offline** — no real AWS, no login, no farm. The test hook
lives in the **sidecar** plugin, not the shipped `DeadlineCloud.pyp`, so the real
plugin is exercised exactly as a customer would and no test-only code reaches
production.

- **Mock backend** (`deadline_test_fixtures.deadline_mock`): an in-memory
  Deadline Cloud simulator serving the resource-read operations used by
  submitters, with an empty queue-environment list by default. It records
  `call_counts` / `request_log` / `unmatched_requests` so the
  test can assert exactly which calls reached it and that nothing hit an unmocked
  route. Its default scenario provides stable fake farm and queue resources.
- **Separate process** (`MockDeadlineServerProcess`): the mock runs in its own
  process, NOT a thread. xa11y's native `wait_*` calls hold the CPython GIL for
  most of their duration, which would starve an in-process server thread and
  hang the test for the full 60s timeout. The out-of-process server keeps
  serving; the test reads its observability over the package's admin endpoint
  via a `RemoteDeadlineBackend` proxy.
- **Subprocess wiring** (`build_mock_environment` + the `deadline_farm` fixture):
  a temp `deadline config` names the mock's farm/queue, and the C4D subprocess
  env gets `AWS_ENDPOINT_URL_DEADLINE` → mock, dummy AWS creds, telemetry
  opt-out (so no STS call fires), an isolated `HOME`, and
  `DEADLINE_CLOUD_MOCK_MODE=1`.
- **Sidecar mock-mode patches** (gated on `DEADLINE_CLOUD_MOCK_MODE=1`, so the
  shipped plugin behaviour is untouched for real users):
  - `management.` → `127.0.0.1` `socket.getaddrinfo` redirect — the Deadline
    service model injects a `management.` host prefix, which wouldn't resolve to
    the loopback mock otherwise.
  - `os.startfile` no-op — stops the submitter popping a File Explorer window at
    the bundle folder on Windows (it would linger/pile up across runs).
- **Empty queue environments**: the mock returns an empty `ListQueueEnvironments`,
  so there are no Conda parameter widgets for `OpenJDParametersWidget.rebuild_ui`
  to recreate mid-Export and thus no reload race. Consequence: the exported
  bundle carries no `CondaPackages` / `CondaChannels`, and the expected bundles
  omit them too.

```bash
hatch run integ-xa11y:test                        # all xa11y integ tests
```

The `integ-xa11y:test` script hardcodes the `test/integ_xa11y` path and
`--numprocesses=1`. Beware: any args you pass *replace* the path (hatch
`{args:test/integ_xa11y}` falls back to the global `testpaths = ["test"]`), so
`hatch run integ-xa11y:test -k cube` would scan the whole `test/` tree. To
filter or run in-process (e.g. to see C4D/xa11y stdout, which xdist hides), call
pytest directly with an explicit path — the test spawns its own subprocesses
regardless of `--numprocesses`:

```bash
hatch -e integ-xa11y run pytest --no-cov test/integ_xa11y/test_cinema4d.py \
    --numprocesses=0 -s -k cube
```

#### Platform support matrix

| Stage | Windows | macOS |
|-------|:-------:|:-----:|
| Scene build (`c4dpy`) | ✅ | ✅ |
| Launch + drive UI (xa11y) | ✅ | ✅ |
| Bundle comparison | ✅ | ✅ |
| `openjd run` + render compare | ✅ | ❌ skipped |

macOS stops after bundle comparison — the render path needs Conda-managed
`cinema4d-openjd`, which isn't shipped for darwin yet.

Caveats:
- Windows SMF workers run in Session 0 with no interactive desktop, so UI
  Automation returns nothing there. Local interactive sessions only.
- Accessibility roles/names differ between macOS AX and Windows UIA, so any new
  `configure.py` selector must be verified on both platforms (the page-object
  helpers in `submitter_ui.py` already are).

#### Golden-bundle comparison

Direct byte comparison would be too brittle, so before comparing, the helper
(`BundleNormalization` through the local comparison wrapper) normalizes a
fixed set of moving parts: `PATH_TO_BE_REPLACED` → the local repo prefix;
backslashes → forward slashes (preserving unicode escapes);
`SubmitterIntegrationVersion` (changes every build) → a fixed placeholder; and
`jobEnvironments` is stripped from `template.yaml`. The final assertion requires
exactly the three files (`template.yaml`, `parameter_values.yaml`,
`asset_references.yaml`) to match.

#### Adding / changing a case

**Plain case (no UI interaction):**
1. Create `test_cases/<name>/input/scene.py` (model it on `cube`'s).
2. Add `"<name>"` to the `_CASES` list in `test_cinema4d.py`.
3. Run it once (it fails — `expected/` is empty), capture the golden (below), re-run.

**Configured case (drive the dialog before Export):** same, plus an
`input/configure.py` with a top-level `configure(dialog)` using the
`submitter_ui` page-object:

```python
from test.integ_xa11y import submitter_ui as ui

def configure(dialog):
    ui.set_priority(dialog, 51)
    ui.set_detailed_logging(dialog, True)
```

It runs after the dialog settles and before Export. See `submitter_ui.py` for
the helpers and gotchas, and `cube`'s `input/configure.py` for a worked example.

**Capturing the golden bundle (manual):** after a run, the generated bundle is in
the case's `actual/`. Copy the three files into `expected/job_bundle/`, replacing
the absolute prefix up to (not including) `deadline-cloud-for-cinema-4d` with
`PATH_TO_BE_REPLACED`:

```bash
case=<name>
parent="$(dirname "$(pwd)")"   # run from the repo root
for f in template.yaml parameter_values.yaml asset_references.yaml; do
  perl -pe "s{\Q$parent\E}{PATH_TO_BE_REPLACED}g" \
    test/integ_xa11y/test_cases/$case/actual/$f \
    > test/integ_xa11y/test_cases/$case/expected/job_bundle/$f
done
```

The submitter sometimes emits `parameter_values.yaml` as single-line JSON; the
comparison parses both, but commit block YAML (re-serialize with
`deadline.client.job_bundle._yaml.deadline_yaml_dump`). The render PNGs
(`expected/renders/`) are captured the same way and only compared on Windows.

**New mocked operation:** if a submitter change calls a Deadline operation the
mock doesn't implement, the test fails its `unmatched_requests` assertion (and
the mock logs `404 NO ROUTE`). Add a `@route`-decorated handler in
`deadline_test_fixtures.deadline_mock.MockDeadlineBackend`. If it returns
resource data, extend `MockDeadlineScenario` there. Keep DCC-specific launch
behavior in this repository.

## Installer Tests

Test the built installer. Requires having run `hatch run installer:build-installer` first.

```bash
hatch run test-installer
```

## Coverage

The project requires minimum 23% code coverage. Coverage settings are in `pyproject.toml` under `[tool.coverage.report]`.
