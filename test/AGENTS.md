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
│   ├── test_scenes/         # Test scene definitions (mirrors integ/)
│   ├── test_cinema4d.py     # Drives the real submitter dialog via xa11y
│   ├── conftest.py          # Fixtures, incl. deadline_farm (starts the mock)
│   ├── utils.py             # Test utilities
│   ├── mock_aws/            # Hand-rolled offline mock Deadline Cloud backend
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
5. The parametrized test runner (`test_cinema4d.py`) will automatically pick up the new scene

### Running specific integration tests

```bash
hatch run integ:test -k "physical"
hatch run integ:test -k "redshift"
hatch run integ:test -k "redshift_tiles"
```

### xa11y-driven integration test (`test/integ_xa11y/`)

Mirrors the layout and naming of `test/integ/` (`test_cinema4d.py`,
`test_scenes/<name>/scene/scene.py`, `generated_bundle/`, etc.) but
drives the **real Deadline Cloud submitter dialog** with
[xa11y](https://xa11y.dev) instead of calling `internal_create_job_bundle()`
directly.

Once we're confident in this test, the plan is to delete `test/integ/`
and rename this folder to `test/integ/`.

Runs fully **offline** — no real AWS, no login, no real farm. A hand-rolled mock
Deadline Cloud backend (`test/integ_xa11y/mock_aws/`) speaks the rest-json
protocol; the `deadline_farm` fixture starts it and wires the Cinema 4D
subprocess to it. No credentials or `deadline config` are required, and the
generated bundle carries only sanitized fake farm/queue IDs, so
`expected_job_bundle/` is NOT farm-specific.

The test launches the Cinema 4D GUI binary with two plugin directories on
`g_additionalModulePath`: the real, unmodified
`deadline_cloud_extension/DeadlineCloud.pyp` and a test-only sidecar plugin
(`test/integ_xa11y/fixtures/auto_open_submitter/AutoOpenSubmitter.pyp`). On
`C4DPL_PROGRAM_STARTED` the sidecar loads the test scene and opens the real
submitter via `c4d.CallCommand(SUBMITTER_PLUGIN_ID)` — the same command
`Extensions > AWS Deadline Cloud Submitter` invokes. Keeping the test hook in
the sidecar means the shipped plugin stays unmodified and is exercised exactly
as a customer would. The test then drives the resulting Qt dialog with xa11y,
clicks `Export bundle`, copies the resulting bundle flat into
`<scene>/generated_bundle/`, then runs `openjd check` and `openjd run`
against it — same final assertions as the existing test.

#### Offline mock architecture

- **Mock backend** (`mock_aws/deadline.py`): an in-memory Deadline Cloud
  simulator serving only the five operations the Export-bundle flow was observed
  to call against a real farm — `ListFarms`, `GetFarm`, `GetQueue`,
  `ListQueueEnvironments`, `GetQueueEnvironment`. It records `call_counts` /
  `request_log` / `unmatched_requests` so the test can assert exactly which
  calls reached it and that nothing hit an unmocked route. Seeded from sanitized
  real response data in `mock_aws/fixtures_data.py`.
- **Separate process** (`mock_aws/server_process.py`): the mock runs in its own
  process, NOT a thread. xa11y's native `wait_*` calls hold the CPython GIL for
  most of their duration, which would starve an in-process server thread and
  hang the test for the full 60s timeout. The out-of-process server keeps
  serving; the test reads its observability over a `GET /__admin__/calls` admin
  endpoint via a `RemoteBackend` proxy.
- **Subprocess wiring** (`mock_aws/wiring.py` + the `deadline_farm` fixture):
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
- **No queue environments**: the mock returns an empty `ListQueueEnvironments`,
  so there are no Conda parameter widgets for `OpenJDParametersWidget.rebuild_ui`
  to recreate mid-Export and thus no reload race. Consequence: the exported
  bundle carries no `CondaPackages` / `CondaChannels`, and the expected bundles
  omit them too.
- **No S3 / STS mock**: Export writes the bundle to disk (no upload), and
  telemetry — the only STS caller — is opted out. Only Deadline is mocked.

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

Caveats:
- Windows SMF workers run in Session 0 with no interactive desktop, so
  UI Automation returns nothing there. Local interactive sessions only.
- The mock and the offline wiring are developed/verified on macOS; the
  Windows-only paths (the `openjd run` render comparison, the `os.startfile`
  suppression) need a Windows run to confirm.

## Installer Tests

Test the built installer. Requires having run `hatch run installer:build-installer` first.

```bash
hatch run test-installer
```

## Coverage

The project requires minimum 23% code coverage. Coverage settings are in `pyproject.toml` under `[tool.coverage.report]`.
