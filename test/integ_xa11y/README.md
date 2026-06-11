# xa11y-driven submitter integration test — design

This document explains how the `test/integ_xa11y/` test works: what it covers,
how the pieces fit together, and why the trickier parts exist. It's meant to be
read top-to-bottom by someone who has never seen this folder before.

## What this test proves

The existing `test/integ/` test calls the submitter's
`internal_create_job_bundle()` function directly. That validates the bundle-
generation logic but **skips the entire UI layer** — the Qt dialog, the queue-
environment loading, the Export button wiring, and the plugin entry point a real
user clicks.

This test closes that gap. It launches the **real Cinema 4D GUI** with the
**real, unmodified** `deadline_cloud_extension/DeadlineCloud.pyp` plugin, opens
the submitter the same way a user does, clicks **Export bundle** by driving the
OS accessibility tree, and then runs the same bundle assertions as the old test
(`openjd check`, golden-bundle comparison, `openjd run`, render comparison).

In short: same final assertions, but the bundle is now produced by the actual
UI instead of a direct function call.

> The long-term plan (per `test/AGENTS.md`) is to delete `test/integ/` and
> rename this folder to `test/integ/`. That's why several helpers here are
> deliberately kept byte-for-byte identical to their `test/integ/` counterparts.

## Prerequisites

This test runs **fully offline** against a hand-rolled mock Deadline Cloud
backend (`mock_aws/`) — **no real AWS, no login, no farm/queue selection**. You
do not need credentials or a `deadline config`; the `deadline_farm` fixture
starts the mock and writes a temp config pointing at it.

The only requirements are an interactive desktop session and Cinema 4D installed
(see *How to run*).

## The big picture

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
  ├─ build_cinema4d_scene()  ── runs c4dpy scene.py ──▶ cube.c4d
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
                │   - wait for dialog
                │   - wait for queue-env loading to finish
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

## The files, and what each is responsible for

| File | Role |
|------|------|
| `test_cinema4d.py` | The test itself. Orchestrates scene build → launch → UI drive → assertions. |
| `conftest.py` | Fixtures: locate Cinema 4D, set `C4DPYTHONPATH`, and the `deadline_farm` fixture (starts the mock backend + builds the subprocess env). |
| `utils.py` | Helpers: exe resolution, scene build, bundle waiting, golden-bundle + image comparison. |
| `mock_aws/deadline.py` | In-memory mock Deadline Cloud backend (rest-json) + HTTP server, with observability (`call_counts`, `request_log`, `unmatched_requests`). |
| `mock_aws/server_process.py` | Runs the mock in a separate process; `RemoteBackend` reads its observability over a `GET /__admin__/calls` admin endpoint. |
| `mock_aws/wiring.py` | Builds the temp deadline config + subprocess env overlay that point C4D at the mock. |
| `mock_aws/fixtures_data.py` | Sanitized real response bodies (fake farm/queue IDs) the mock serves. |
| `fixtures/auto_open_submitter/AutoOpenSubmitter.pyp` | Test-only C4D plugin: auto-opens the real submitter and (in mock mode) applies the getaddrinfo / `os.startfile` patches. Never shipped. |
| `submitter_ui.py` | Page-object for driving the dialog (tabs, fields, checkboxes) from a case's `configure.py`. |
| `test_cases/cube/input/scene.py` | Builds the one-cube test scene with `c4dpy`. |
| `test_cases/cube/input/configure.py` | Drives the dialog (changes settings) before Export. |
| `test_cases/cube/expected/job_bundle/` | Golden bundle files to compare against. |
| `test_cases/cube/expected/renders/` | Golden render output to compare against. |

## Walkthrough of the flow

### 1. Build the scene (`build_cinema4d_scene` → `input/scene.py`)

`input/scene.py` runs inside **`c4dpy`** (Cinema 4D's headless Python). It builds
a cube, sets the render output to `renders/$prj`, single frame, PNG, Standard/
Physical renderer, then saves `cube.c4d`.

Two non-obvious details:

- The scene is saved **into `actual/`**, not `input/`. Because the render path
  `renders/$prj` resolves relative to the document's directory, saving the scene
  there makes renders land in `actual/renders/` — and the render compare derives
  its directory from the bundle's `OutputPath` param, so a `configure.py` that
  overrides the output path is followed automatically.
- `c4dpy` often exits non-zero during teardown even after the script succeeds,
  so the helper treats **"the .c4d file exists"** as the source of truth, not
  the exit code.

### 2. Start the mock backend + wire the subprocess (`deadline_farm` fixture)

The submitter dialog makes AWS calls on open. Instead of letting them hit real
AWS, the `deadline_farm` fixture stands up a local mock and points the C4D
subprocess at it:

1. **Starts the mock Deadline backend** (`mock_aws/`) — an in-memory simulator
   speaking the Deadline rest-json protocol, seeded with one fake farm, queue,
   and (empty) queue-environment list. It records every served request, so the
   test can assert exactly which operations the submitter made.
2. **Writes a temp `deadline config`** naming the mock's fake `farm_id` /
   `queue_id`, pointed at via `DEADLINE_CONFIG_FILE_PATH`. The bundle's
   `job_history_dir` is set here too, so the export lands in a dir the test
   controls.
3. **Builds the subprocess env overlay** (`mock_aws/wiring.py`):
   `AWS_ENDPOINT_URL_DEADLINE` → mock, dummy static AWS creds, an isolated
   `HOME`, `DEADLINE_CLOUD_TELEMETRY_OPT_OUT=true`, and
   `DEADLINE_CLOUD_MOCK_MODE=1`.

The submitter ends up calling four Deadline operations — `ListFarms` (auth
probe), `GetFarm`, `GetQueue`, `ListQueueEnvironments` — all served by the mock.
`GetQueueEnvironment` is *not* called because the queue-env list comes back
empty (the mock implements that route, but the submitter has no env to fetch).
**No STS** call fires because telemetry (its only caller) is opted out, and **no
S3** because Export writes to disk without uploading. The mock's observability
is read back via a `RemoteBackend` proxy and asserted after export (expected
calls present, no unmatched routes).

> Because the mock returns fake, sanitized farm/queue IDs and an **empty
> queue-environment list**, the exported bundle is **not** farm-specific and
> carries **no** `CondaPackages` / `CondaChannels`. The golden
> `expected/job_bundle/` files reflect that and need no per-farm regeneration.

#### Why a separate process (not a thread)

The mock HTTP server runs in its **own process**, not a daemon thread in the
pytest process. xa11y is a native extension whose `wait_*` calls hold the
CPython GIL for most of their duration. If the server were an in-process thread,
the test's `wait_hidden(timeout=60s)` would starve it — it couldn't answer the
submitter's HTTP calls, the queue-environment load would never complete, and the
test would hang for the full 60s. An out-of-process server has its own GIL and
keeps serving; the test reads its `call_counts` / `request_log` /
`unmatched_requests` over a `GET /__admin__/calls` admin endpoint.

#### Why the sidecar patches `getaddrinfo` and `os.startfile` (mock mode)

Both are gated on `DEADLINE_CLOUD_MOCK_MODE=1`, so shipped behaviour is
untouched for real users:

- **`management.` → `127.0.0.1` getaddrinfo redirect** — the Deadline service
  model injects a `management.` host prefix onto every operation, so a client
  pointed at `127.0.0.1` actually tries `management.127.0.0.1`, which wouldn't
  resolve to the loopback mock. The patch rewrites any `management.*` host to
  `127.0.0.1`.
- **`os.startfile` → no-op** — on Windows the submitter calls
  `os.startfile(bundle_dir)` after Export, popping a File Explorer window that
  would linger and pile up across runs. The patch suppresses it.

### 3. Launch Cinema 4D with two plugins

`test_cinema4d.py` builds the child environment and puts **two** directories on
`g_additionalModulePath`:

1. `deadline_cloud_extension/` — the **real** shipped plugin.
2. `fixtures/auto_open_submitter/` — the **test-only** sidecar.

The key design decision: **the test hook lives in the sidecar, not the shipped
plugin.** This means the test exercises the real plugin exactly as a customer
would, and no test-only code ever reaches production. The `_prepend` helper
joins paths with `;` (C4D's separator on every platform — not the OS pathsep)
and avoids a trailing separator, which C4D would otherwise mis-parse.

### 4. The sidecar auto-opens the submitter (`AutoOpenSubmitter.pyp`)

On `C4DPL_PROGRAM_STARTED` the sidecar:

1. Loads `cube.c4d` (named via `DEADLINE_CLOUD_SCENE_PATH`) and makes it the
   active document. This is needed because `C4DPL_PROGRAM_STARTED` fires
   *before* C4D processes argv file arguments, and on macOS argv files are
   ignored entirely (files only arrive via Apple Events). Passing the scene by
   env var sidesteps both.
2. Calls `c4d.CallCommand(SUBMITTER_PLUGIN_ID)` — the **same entry point** as
   clicking `Extensions > AWS Deadline Cloud Submitter`.

It logs every step to `DEADLINE_CLOUD_DIAG_LOG` because C4D's stdout is detached
from pytest; the test reads this file back on teardown to surface failures.

### 5. Drive the dialog with xa11y

xa11y attaches to the C4D process by PID, then finds the dialog. **Where the
dialog lives differs by platform**, and this is the second subtle area:

- **Windows (UIA):** Qt registers the dialog as a *separate top-level UIA app*
  that shares C4D's PID. So the test enumerates apps (`_wait_for_dialog_app`)
  and matches by PID + accessible-name prefix.
- **macOS (AX):** the dialog is a child window of the C4D app, so the C4D app
  handle is reused directly.

Also note: UIA surfaces the Qt **QApplication display name** as the dialog's
accessible name, *not* Qt's `windowTitle`. That's why the selector matches
`"Deadline Cloud Cinema4D Submitter"` rather than the window title.

The test then: waits for the dialog, waits for "Loading Queue Environments" to
disappear (non-fatal if it times out), waits for the Export button to be visible
and enabled, and presses it.

### 6. Reading the exported bundle

The submitter writes the bundle files and only then shows the success popup
(`on_export_bundle`), so once the popup appears the bundle is complete on disk.
After pressing Export, the test dismisses the popup, then reads the finished
bundle with `find_complete_bundle` (newest bundle dir that contains all three
expected files).

The submitter always writes to `<job_history_dir>/<YYYY-mm>/<bundle-name>/`. The
`job_history_dir` is set in the temp deadline config the `deadline_farm` fixture
wrote (read inside the C4D subprocess), so the bundle lands in a dir the test
controls; the test then copies the bundle files **flat** into the case's
`actual/` dir to match the layout the assertions expect.

### 7. Assertions

- The mock saw exactly the expected calls (`ListFarms`, `GetFarm`, `GetQueue`,
  `ListQueueEnvironments`) and **no** request hit an unmocked route — proving the
  submitter ran against the mock, not real AWS.
- `assert_is_valid_job_bundle` → `openjd check` returns `success`.
- `assert_expected_job_bundle_and_generated_job_bundle_are_equal` → compares the
  three bundle files after normalizations (see below).
- On Windows only: `assert_openjd_run_with_cinema4d_successful` runs each step
  via `openjd run` against C4D Commandline, then `assert_all_images_close`
  compares render dimensions.
- macOS stops after bundle comparison — the render path needs Conda-managed
  `cinema4d-openjd`, which isn't shipped for darwin yet.

On success, the case's `actual/` dir is removed; on failure it's left behind for
inspection (and is gitignored, so it never gets committed).

### Golden-bundle normalizations

Direct byte comparison would be too brittle, so before comparing the helper
normalizes a fixed set of moving parts:

- `PATH_TO_BE_REPLACED` → the local absolute repo prefix.
- Backslashes → forward slashes (preserving unicode escapes).
- `SubmitterIntegrationVersion` (changes every build) → a fixed placeholder.
- `jobEnvironments` is stripped from `template.yaml` before comparison.

The final assertion requires exactly the three expected files
(`template.yaml`, `parameter_values.yaml`, `asset_references.yaml`) to match.

## Platform support matrix

| Stage | Windows | macOS |
|-------|:-------:|:-----:|
| Scene build (`c4dpy`) | ✅ | ✅ |
| Launch + drive UI (xa11y) | ✅ | ✅ |
| Bundle comparison | ✅ | ✅ |
| `openjd run` + render compare | ✅ | ❌ skipped |

**Known caveat (from `test/AGENTS.md`):** Windows SMF workers run in Session 0
with no interactive desktop, so UI Automation returns nothing there. This test
only works in a local interactive session.

## How to run

```bash
hatch run integ-xa11y:test            # all xa11y integ tests
```

The `integ-xa11y:test` script hardcodes the `test/integ_xa11y` path and
`--numprocesses=1`. Args you pass *replace* that path (hatch
`{args:test/integ_xa11y}` falls back to the global `testpaths = ["test"]`), so
`hatch run integ-xa11y:test -k cube` would scan the whole `test/` tree. To
filter or run in-process (e.g. `-s` to see C4D/xa11y stdout, which xdist hides),
invoke pytest directly with an explicit path — the test spawns its own
subprocesses regardless of `--numprocesses`:

```bash
hatch -e integ-xa11y run pytest --no-cov test/integ_xa11y/test_cinema4d.py \
    --numprocesses=0 -s -k cube
```

No AWS login or farm/queue selection is needed (the mock provides them). Cinema
4D location resolves from `C4D_LOCATION`, else `C4D_VERSION` + platform default,
else a scan of known install paths (newest first).

## Extending the test

### Anatomy of a test case

A case is a self-contained folder under `test_cases/<name>/`:

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

The case is then **registered explicitly** in the `_CASES` list in
`test_cinema4d.py` — adding the folder is not enough, you add its name to the
list. The expected bundle works on every platform and is **not** farm-specific
(the mock provides fake, stable farm/queue IDs and no queue environments), so
the expected files are portable and don't need per-farm regeneration.

### Add a plain case (no UI interaction)

1. Create `test_cases/<name>/input/scene.py` (model it on `cube`'s).
2. Add `"<name>"` to the `_CASES` list in `test_cinema4d.py`.
3. Run it once — it fails the bundle comparison because `expected/` is empty.
   **Capture the golden** (see below).
4. Re-run — green.

### Add a configured case (click buttons / change settings before Export)

Same as above, plus an `input/configure.py` defining a top-level
`configure(dialog)` that drives the dialog via the `submitter_ui` page-object:

```python
from test.integ_xa11y import submitter_ui as ui

def configure(dialog):
    ui.set_priority(dialog, 75)
    ui.set_detailed_logging(dialog, True)
```

`configure` runs after the dialog settles and before Export, so the screenshot
captures the configured state. See `submitter_ui.py` for the available helpers
and the hard-won gotchas (tabs are `radio_button`, spin boxes step rather than
set, duplicate accessible names need `.nth()`, etc.), and `cube`'s
`input/configure.py` for a worked example. Configurators are expected to work on
**both** macOS and Windows; if a selector misses on one, the failure dumps the
accessibility tree — use that to widen it.

### Capturing the golden bundle (manual)

After a run, the generated bundle is in the case's `actual/`. Copy the three
files into `expected/job_bundle/` and sanitize the absolute repo prefix — replace
everything up to (but not including) `deadline-cloud-for-cinema-4d` with
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

Whatever a configurator changes is reflected in the captured bundle by
construction, so re-capture whenever you change `scene.py` or `configure.py`.
The render PNGs (`expected/renders/`) are captured the same way (copy from the
run's render dir) and only compared on Windows.

### New mocked operation

If a submitter change makes it call a Deadline operation the mock doesn't
implement, the test fails its `unmatched_requests` assertion (and the mock logs
a `404 NO ROUTE`). Add a `@route`-decorated handler in `mock_aws/deadline.py`
and, if it returns resource data, seed it in `mock_aws/fixtures_data.py`.
