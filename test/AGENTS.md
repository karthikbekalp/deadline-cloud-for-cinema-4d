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

The test launches the Cinema 4D GUI binary, points it at the real
`deadline_cloud_extension/DeadlineCloud.pyp` via `g_additionalModulePath`
(no test-only plugin), clicks `Extensions > AWS Deadline Cloud Submitter`,
clicks `Export bundle`, copies the resulting bundle flat into
`<scene>/generated_bundle/`, then runs `openjd check` and `openjd run`
against it — same final assertions as the existing test.

```bash
hatch run integ-xa11y:test                        # all xa11y integ tests
hatch run integ-xa11y:test -k cube                # one parametrization
```

Caveats:
- Windows SMF workers run in Session 0 with no interactive desktop, so
  UI Automation returns nothing there. Local interactive sessions only.

## Installer Tests

Test the built installer. Requires having run `hatch run installer:build-installer` first.

```bash
hatch run test-installer
```

## Coverage

The project requires minimum 23% code coverage. Coverage settings are in `pyproject.toml` under `[tool.coverage.report]`.
