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

## The big picture

```
pytest (parent process)
  │
  ├─ mock_deadline_farm fixture
  │     ├─ starts mock Deadline HTTP server   (127.0.0.1:<ephemeral>)
  │     ├─ starts mock STS HTTP server        (127.0.0.1:<ephemeral>)
  │     └─ writes a temp deadline-client config pointing at them
  │
  ├─ build_cube_scene()  ── runs c4dpy scene.py ──▶ cube.c4d
  │
  └─ launches Cinema 4D GUI (child process)
         │   env: AWS endpoints → mocks, two plugin dirs, python path + shim
         │
         ├─ loads DeadlineCloud.pyp           (real, shipped plugin)
         ├─ loads AutoOpenSubmitter.pyp       (test-only sidecar)
         │      on C4DPL_PROGRAM_STARTED:
         │        1. patch botocore host prefix
         │        2. LoadDocument(cube.c4d)
         │        3. CallCommand(SUBMITTER_PLUGIN_ID)  ◀─ opens real submitter
         │
         └─ Qt submitter dialog appears
                ▲
                │ xa11y drives it via the OS accessibility tree
                │   - wait for dialog
                │   - wait for queue-env loading to finish
                │   - press "Export bundle"
                ▼
         bundle written to <job_history_dir>/<YYYY-mm>/<bundle-name>/
                │
   parent ◀────┘ copies bundle flat into <scene>/generated_bundle/
         │
         ├─ openjd check
         ├─ compare against expected_job_bundle/ (golden files)
         ├─ openjd run  (Windows/Linux only)
         └─ compare renders against expected_job_output/ (Windows/Linux only)
```

## The files, and what each is responsible for

| File | Role |
|------|------|
| `test_cinema4d.py` | The test itself. Orchestrates scene build → launch → UI drive → assertions. |
| `conftest.py` | Fixtures: locate Cinema 4D, set `C4DPYTHONPATH`, and the `mock_deadline_farm` fixture. |
| `mock_deadline_backend.py` | In-process HTTP mocks for the Deadline and STS APIs the dialog calls. |
| `utils.py` | Helpers: exe resolution, scene build, bundle waiting, golden-bundle + image comparison. |
| `fixtures/auto_open_submitter/AutoOpenSubmitter.pyp` | Test-only C4D plugin that auto-opens the real submitter. Never shipped. |
| `test_scenes/cube/scene/scene.py` | Builds the one-cube test scene with `c4dpy`. |
| `test_scenes/cube/expected_job_bundle[_darwin]/` | Golden bundle files to compare against. |
| `test_scenes/cube/expected_job_output/renders/` | Golden render output to compare against. |

## Walkthrough of the flow

### 1. Build the scene (`build_cube_scene` → `scene.py`)

`scene.py` runs inside **`c4dpy`** (Cinema 4D's headless Python). It builds a
cube, sets the render output to `renders/$prj`, single frame, PNG, Standard/
Physical renderer, then saves `cube.c4d`.

Two non-obvious details:

- The scene is saved **into `generated_bundle/`**, not `scene/`. Because the
  render path `renders/$prj` resolves relative to the document's directory,
  saving the scene there makes renders land in `generated_bundle/renders/` —
  exactly where `assert_all_images_close` looks.
- `c4dpy` often exits non-zero during teardown even after the script succeeds,
  so the helper treats **"the .c4d file exists"** as the source of truth, not
  the exit code.

### 2. Stand up the mock backend (`mock_deadline_farm` fixture)

The submitter dialog makes real AWS calls on open. Rather than require a live
farm, the fixture starts two tiny `http.server` instances on `127.0.0.1`:

- **Mock Deadline** serves the routes the dialog hits at startup: `GetFarm`,
  `GetQueue`, `ListQueueEnvironments`, `GetQueueEnvironment` (plus list
  variants). Any unmocked route returns **400 with a helpful message** so a new
  API dependency fails loudly instead of silently passing.
- **Mock STS** answers `GetCallerIdentity` (the dialog's auth probe) with a
  canned XML identity. Note STS uses the XML query protocol, not JSON.

The fixture writes a temp `deadline_config` file seeding the farm/queue IDs and
points both the child process **and** the parent (via
`DEADLINE_CONFIG_FILE_PATH`) at it, so `override_job_history_dir` in the parent
writes to the same config the child reads.

### 3. The `management.` host-prefix problem

This is the subtlest part of the whole test. botocore injects a `management.`
host prefix on every Deadline API call, so requests would go to
`http://management.127.0.0.1:<port>/...` and miss the mock. The fix is to patch
`botocore.awsrequest._urljoin` to drop the prefix. It's applied in **two
places** because two different interpreters make calls:

- **`AutoOpenSubmitter.pyp`** patches it inside the C4D process (where the
  submitter actually runs).
- **`conftest.py`** writes a `sitecustomize.py` shim onto `C4DPYTHONPATH` so
  C4D's bundled Python applies the same patch on interpreter start.

### 4. Launch Cinema 4D with two plugins

`test_cinema4d.py` builds the child environment and puts **two** directories on
`g_additionalModulePath`:

1. `deadline_cloud_extension/` — the **real** shipped plugin.
2. `fixtures/auto_open_submitter/` — the **test-only** sidecar.

The key design decision: **the test hook lives in the sidecar, not the shipped
plugin.** This means the test exercises the real plugin exactly as a customer
would, and no test-only code ever reaches production. The `_prepend` helper
joins paths with `;` (C4D's separator on every platform — not the OS pathsep)
and avoids a trailing separator, which C4D would otherwise mis-parse.

### 5. The sidecar auto-opens the submitter (`AutoOpenSubmitter.pyp`)

On `C4DPL_PROGRAM_STARTED` the sidecar:

1. Patches the botocore host prefix (see §3).
2. Loads `cube.c4d` (named via `DEADLINE_CLOUD_SCENE_PATH`) and makes it the
   active document. This is needed because `C4DPL_PROGRAM_STARTED` fires
   *before* C4D processes argv file arguments, and on macOS argv files are
   ignored entirely (files only arrive via Apple Events). Passing the scene by
   env var sidesteps both.
3. Calls `c4d.CallCommand(SUBMITTER_PLUGIN_ID)` — the **same entry point** as
   clicking `Extensions > AWS Deadline Cloud Submitter`.

It logs every step to `DEADLINE_CLOUD_DIAG_LOG` because C4D's stdout is detached
from pytest; the test reads this file back on teardown to surface failures.

### 6. Drive the dialog with xa11y

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

### 7. Bundle on disk is the source of truth

After pressing Export, the test waits for a bundle to appear under the staging
dir (`wait_for_bundle`) rather than trying to match the success popup's
accessible name — popups surface differently across UIA and AX, so the file on
disk is the reliable signal. The success popup is dismissed *if* found, but a
miss is non-fatal.

The submitter always writes to `<job_history_dir>/<YYYY-mm>/<bundle-name>/`, so
the test overrides `job_history_dir` to a temp staging dir, then copies the
bundle files **flat** into `generated_bundle/` to match the layout the
assertions expect.

### 8. Assertions

- `assert_is_valid_job_bundle` → `openjd check` returns `success`.
- `assert_expected_job_bundle_and_generated_job_bundle_are_equal` → compares the
  three bundle files after normalizations (see below).
- On Windows/Linux only: `assert_openjd_run_with_cinema4d_successful` runs each
  step via `openjd run` against C4D Commandline, then `assert_all_images_close`
  compares render dimensions.
- macOS stops after bundle comparison — the render path needs Conda-managed
  `cinema4d-openjd`, which isn't shipped for darwin yet.

On success, `generated_bundle/` is removed; on failure it's left behind for
inspection.

### Golden-bundle normalizations

Direct byte comparison would be too brittle, so before comparing the helper
normalizes a fixed set of moving parts:

- `PATH_TO_BE_REPLACED` → the local absolute repo prefix.
- Backslashes → forward slashes (preserving unicode escapes).
- Conda package versions (`cinema4d=…`) → a fixed placeholder.
- `SubmitterIntegrationVersion` (changes every build) → a fixed placeholder.
- `jobEnvironments` is stripped from `template.yaml` before comparison.

The final assertion requires exactly the three expected files
(`template.yaml`, `parameter_values.yaml`, `asset_references.yaml`) to match.

## Platform support matrix

| Stage | Windows | macOS | Linux |
|-------|:-------:|:-----:|:-----:|
| Scene build (`c4dpy`) | ✅ | ✅ | ✅ |
| Launch + drive UI (xa11y) | ✅ | ✅ | ⚠️ untested |
| Bundle comparison | ✅ | ✅ | ✅ |
| `openjd run` + render compare | ✅ | ❌ skipped | ✅ |

**Known caveat (from `test/AGENTS.md`):** Windows SMF workers run in Session 0
with no interactive desktop, so UI Automation returns nothing there. This test
only works in a local interactive session.

## How to run

```bash
hatch run integ-xa11y:test            # all xa11y integ tests
hatch run integ-xa11y:test -k cube    # just the cube parametrization
```

Cinema 4D location resolves from `C4D_LOCATION`, else `C4D_VERSION` + platform
default, else a scan of known install paths (newest first).

## Extending the test

- **New scene:** add `test_scenes/<name>/scene/scene.py`, an
  `expected_job_bundle/` (and `_darwin` variant if needed), and
  `expected_job_output/renders/`, then add `<name>` to the `@parametrize` list
  in `test_cinema4d.py`.
- **New API dependency:** if the dialog starts calling a new Deadline API, the
  mock returns 400 and tells you to add a route — add it to `MockDeadlineFarm`.
