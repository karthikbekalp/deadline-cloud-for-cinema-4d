# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from shutil import copy2, rmtree

import pytest
import xa11y

from .utils import (
    assert_all_images_close,
    assert_expected_job_bundle_and_generated_job_bundle_are_equal,
    assert_is_valid_job_bundle,
    assert_openjd_run_with_cinema4d_successful,
    build_cinema4d_scene,
    build_submitter_pythonpath,
    kill_proc,
    log,
    resolve_c4d_exe,
    wait_for_bundle,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_REAL_PLUGIN_DIR = _REPO_ROOT / "deadline_cloud_extension"
_REAL_PLUGIN_FILE = _REAL_PLUGIN_DIR / "DeadlineCloud.pyp"

# Test-only sidecar plugin loaded alongside the real plugin (see its docstring).
# Its presence on g_additionalModulePath is what auto-opens the submitter; the
# shipped DeadlineCloud.pyp carries no test hook of its own.
_AUTO_OPEN_PLUGIN_DIR = Path(__file__).parent / "fixtures" / "auto_open_submitter"
_AUTO_OPEN_PLUGIN_FILE = _AUTO_OPEN_PLUGIN_DIR / "AutoOpenSubmitter.pyp"

# Selector strings pinned by inspecting the live UIA tree at runtime
# (see commit history for tree dumps). UIA on Windows surfaces the Qt
# QApplication display name as the dialog's accessible name — *not*
# Qt's windowTitle. The Submit/Export-bundle buttons keep their visible
# labels as accessible names.
#
# Export button: deadline-cloud/src/deadline/client/ui/dialogs/
#                    submit_job_to_deadline_dialog.py:250
_DIALOG_NAME_PREFIX = "Deadline Cloud Cinema4D Submitter"
_EXPORT_BUTTON_NAME = "Export bundle"
# Both the UIA App for the dialog and the dialog window itself surface
# the same name (the QApplication display name + version), so we reuse
# the same prefix for both.
_DIALOG_APP_PREFIX = _DIALOG_NAME_PREFIX

_C4D_BOOT_TIMEOUT_S = 180.0
_DIALOG_VISIBLE_TIMEOUT_S = 60.0
_BUNDLE_EXPORT_TIMEOUT_S = 60.0


def _prepend(new: str, existing: str, sep: str) -> str:
    """Prepend `new` to `existing` using `sep`, without leaving a dangling
    separator when `existing` is empty.

    Cinema 4D parses g_additionalModulePath strictly — a trailing separator
    leaves the last path interpreted as `<path>:` and fails to resolve.
    """
    return f"{new}{sep}{existing}" if existing else new


def _wait_for_dialog_app(pid: int, name_prefix: str, timeout_s: float):
    """Poll xa11y.App.list() for an app whose name starts with `name_prefix`
    and whose PID matches. Returns the matching App or None on timeout.

    The Qt submitter dialog registers as a separate UIA app from Cinema 4D
    even though they share a process — so we have to enumerate apps and
    pick the right one rather than going through the C4D app handle.
    """
    import time as _t

    deadline_t = _t.monotonic() + timeout_s
    while _t.monotonic() < deadline_t:
        try:
            for a in xa11y.App.list():
                if a.pid == pid and a.name and a.name.startswith(name_prefix):
                    return a
        except Exception as e:
            log(f"App.list() raised while polling: {e!r}")
        _t.sleep(0.5)
    return None


def _dump_plugin_diag_log(log_path: Path) -> None:
    """Echo the sidecar plugin's diagnostic log into the test output. C4D's
    stdout is detached from pytest's, so this is how the plugin's traces (scene
    load, CallCommand result, any exceptions) reach a failing run's report.
    Called before the staging dir is removed."""
    if not log_path.is_file():
        log(f"no plugin diag log at {log_path}")
        return
    log(f"--- sidecar plugin diag log ({log_path}) ---")
    print(log_path.read_text(encoding="utf-8", errors="replace"))
    log("--- end sidecar plugin diag log ---")


def _prepare_generated_bundle_dir(
    test_scenes_folder_location: Path, test_name: str
) -> tuple[Path, Path]:
    """Resolve the test scene folder and the generated_bundle/ output dir,
    creating the latter. Returns (test_scene_folder, job_bundle_generated)."""
    test_scene_folder = test_scenes_folder_location / test_name
    job_bundle_generated = test_scene_folder / "generated_bundle"
    os.makedirs(job_bundle_generated, exist_ok=True)
    return test_scene_folder, job_bundle_generated


def _build_cinema4d_scene(
    cinema4d_location: Path,
    test_scene_folder: Path,
    job_bundle_generated: Path,
    test_name: str,
) -> Path:
    """Build the parametrized test scene with c4dpy and return the saved
    scene path. The scene is whichever one lives under test_scene_folder
    (selected by test_name); its scene/scene.py is run by c4dpy and is
    expected to save the scene as <test_name>.c4d.

    The scene is saved into generated_bundle/ rather than scene/ so that
    render_data RDATA_PATH = "renders/$prj" (resolved against
    doc.GetDocumentPath()) lands renders inside generated_bundle/renders/,
    matching the layout assert_all_images_close expects. Same trick the
    existing test/integ/ test relies on.
    """
    c4dpy_location = resolve_c4d_exe(cinema4d_location, "c4dpy")
    test_scene_script = test_scene_folder / "scene" / "scene.py"
    return build_cinema4d_scene(
        c4dpy_location, test_scene_script, job_bundle_generated, f"{test_name}.c4d"
    )


def _build_launch_env(
    scene_path: Path,
    plugin_diag_log: Path,
    mock_env_overlay: dict,
) -> dict:
    """Build the environment for the Cinema 4D subprocess.

    Starts from ``mock_env_overlay`` (built by the ``deadline_farm`` fixture):
    that overlay already carries this process's environment plus the redirect to
    the mock Deadline backend -- endpoint override, dummy credentials, telemetry
    opt-out, isolated HOME, the temp deadline config path, and the mock-mode flag
    that switches on the sidecar's ``management.`` getaddrinfo redirect. So the
    submitter talks to the local mock, never real AWS.
    """
    return {
        **mock_env_overlay,
        # Point C4D at two plugin dirs: the real submitter plugin checked into
        # this repo, and the test-only sidecar that auto-opens the submitter.
        # C4D loads every .pyp on this path at startup; the sidecar dispatches
        # into the real, unmodified plugin via CallCommand. Same env var the
        # InstallBuilder installer sets. C4D uses ';' as the separator on every
        # platform (it is not the OS pathsep).
        "g_additionalModulePath": _prepend(
            str(_AUTO_OPEN_PLUGIN_DIR),
            _prepend(
                str(_REAL_PLUGIN_DIR),
                os.environ.get("g_additionalModulePath", ""),
                ";",
            ),
            ";",
        ),
        # C4D's bundled Python uses this for extra package resolution.
        # We need the editable submitter source plus the venv site-packages
        # (PySide6 / qtpy / deadline-client all live there).
        "C4DPYTHONPATH311": _prepend(
            build_submitter_pythonpath(_REPO_ROOT),
            os.environ.get("C4DPYTHONPATH311", ""),
            os.pathsep,
        ),
        # Where the sidecar plugin writes its diagnostics (read back on
        # failure once the subprocess is killed).
        "DEADLINE_CLOUD_DIAG_LOG": str(plugin_diag_log),
        # Pass the scene path via env var on all platforms so the sidecar
        # plugin loads it with LoadDocument before opening the submitter.
        # C4DPL_PROGRAM_STARTED fires before C4D processes argv files, so
        # without this the active document has no path when the submitter
        # opens.
        "DEADLINE_CLOUD_SCENE_PATH": str(scene_path),
    }


def _launch_cinema4d(cinema4d_gui_exe: Path, scene_path: Path, env: dict) -> subprocess.Popen:
    """Launch Cinema 4D with the submitter + sidecar plugins.

    On macOS we don't pass the scene on argv (the sidecar loads it via
    DEADLINE_CLOUD_SCENE_PATH); on Windows we pass it on argv too.
    """
    if sys.platform == "darwin":
        proc = subprocess.Popen(
            [str(cinema4d_gui_exe)],
            env=env,
        )
    else:
        proc = subprocess.Popen(
            [str(cinema4d_gui_exe), str(scene_path)],
            env=env,
        )
    return proc


def _dump_dialog_discovery_failure(app) -> None:
    """Dump the C4D app tree and the full running-app list when the submitter
    dialog never registers as its own UIA app (Windows). Diagnostics only."""
    log("dialog never registered as a UIA app; debugging info:")
    try:
        log("Cinema 4D app tree:")
        print(app.dump())
    except Exception:
        pass
    try:
        log("All running apps:")
        for a in xa11y.App.list():
            print(f"  - {a.name!r} (pid={a.pid})")
    except Exception as e:
        log(f"App.list() failed: {e!r}")


def _resolve_dialog_app(proc: subprocess.Popen):
    """Attach xa11y to the launched Cinema 4D process and return the
    accessibility app that hosts the submitter dialog.

    The sidecar plugin opens the submitter automatically once C4D finishes
    starting (C4DPL_PROGRAM_STARTED). Where the dialog appears in the
    accessibility tree is platform-specific:
      - Windows UIA: Qt registers each dialog as a separate top-level UIA
        app sharing the C4D pid.
      - macOS AX: dialogs are child windows of the host app.
    """
    log(f"waiting up to {_C4D_BOOT_TIMEOUT_S:.0f}s for xa11y to attach by pid")
    app = xa11y.App.by_pid(proc.pid, timeout=_C4D_BOOT_TIMEOUT_S)
    log("xa11y attached to Cinema 4D")

    if sys.platform == "win32":
        dialog_app = _wait_for_dialog_app(
            pid=proc.pid,
            name_prefix=_DIALOG_APP_PREFIX,
            timeout_s=_DIALOG_VISIBLE_TIMEOUT_S,
        )
        if dialog_app is None:
            _dump_dialog_discovery_failure(app)
            raise AssertionError(
                "Submitter dialog did not register with UIA "
                f"(expected app name prefix {_DIALOG_APP_PREFIX!r})"
            )
        log(f"submitter dialog UIA app: {dialog_app.name!r}")
    else:
        # On macOS the dialog is a child window of the C4D app.
        dialog_app = app
        log("macOS: using C4D app handle for dialog discovery")

    # Dump the tree for diagnostics on first run / failures.
    try:
        log("dialog app tree (depth=8):")
        print(dialog_app.dump(max_depth=8))
    except Exception as e:
        log(f"dialog_app.dump() failed: {e!r}")

    return dialog_app


def _wait_for_submitter_dialog(dialog_app):
    """Wait for the submitter dialog to become visible and return its locator.

    On Windows UIA: role=dialog, name=QApplication display name.
    On macOS AX: role=window, name=window title. Try both selectors.
    """
    log(f"waiting for dialog: {_DIALOG_NAME_PREFIX!r}")
    dialog = dialog_app.locator(
        f"dialog[name^='{_DIALOG_NAME_PREFIX}'], " f"window[name^='{_DIALOG_NAME_PREFIX}']"
    )
    try:
        dialog.wait_visible(timeout=_DIALOG_VISIBLE_TIMEOUT_S)
    except Exception:
        log("dialog selector failed; final tree:")
        try:
            print(dialog_app.dump())
        except Exception:
            pass
        raise
    log("submitter dialog visible")
    return dialog


def _wait_for_queue_environment_loading(dialog_app) -> None:
    """Wait for the queue-environment loading caption to clear. Non-fatal if it
    times out — Export bundle may still be clickable.

    The mock returns no queue environments, so the caption ("Loading Queue
    Environments...") should appear briefly and clear almost immediately; we
    still wait for it to confirm the dialog has settled before pressing Export.
    """
    log("waiting for queue environment loading to finish")
    loading = dialog_app.locator(
        "static_text[name^='Loading Queue Environments'], "
        "static_text[name^='Reloading Queue Environments'], "
        "static_text[name^='Error loading queue environments']"
    )
    try:
        loading.wait_hidden(timeout=_DIALOG_VISIBLE_TIMEOUT_S)
        log("queue environment loading finished (loading caption hidden)")
    except Exception as e:
        log(f"loading-text wait failed (non-fatal): {e!r}")


def _save_dialog_screenshot(dialog, dialog_app, dest: Path) -> None:
    """Save a PNG of the submitter dialog into `dest` as a record of the run.

    Captured just before Export is pressed, so it shows the fully-loaded dialog
    state that produced the bundle. Best-effort and never fatal — a screenshot
    failure must not fail the test. Tries to capture just the dialog element;
    falls back to the dialog app's window, then the full screen.

    Lives in `generated_bundle/`, which is removed on a successful run and kept
    on failure — so the screenshot survives exactly when you'd want to inspect
    it (a failed run).
    """
    out = dest / "submitter_dialog.png"
    for label, kwargs in (
        ("dialog element", {"element": dialog.element()}),
        ("dialog app window", {"element": dialog_app.as_element()}),
        ("full screen", {}),
    ):
        try:
            xa11y.screenshot(**kwargs).save_png(str(out))
            log(f"saved submitter screenshot ({label}) -> {out}")
            return
        except Exception as e:
            log(f"screenshot via {label} failed (trying next): {e!r}")
    log("could not capture submitter screenshot (non-fatal)")


def _press_export_bundle(dialog, dialog_app) -> None:
    """Wait for the Export bundle button to be visible and enabled, then
    press it."""
    log(f"waiting for button: {_EXPORT_BUTTON_NAME!r}")
    export_btn = dialog.descendant(f"button[name='{_EXPORT_BUTTON_NAME}']")
    export_btn.wait_visible(timeout=_DIALOG_VISIBLE_TIMEOUT_S)
    export_btn.wait_enabled(timeout=_DIALOG_VISIBLE_TIMEOUT_S)
    log("pressing Export bundle")
    try:
        export_btn.press()
    except Exception:
        log("Export bundle press failed; final dialog tree:")
        try:
            print(dialog_app.dump())
        except Exception:
            pass
        raise


def _dismiss_success_popup() -> None:
    """Dismiss the "Saved the submission as a job bundle" popup promptly.

    The popup is deadline-cloud's success QMessageBox. Two things make it
    awkward to match (both confirmed by dumping the live AX tree):

    * It is hosted by the **Cinema 4D** app, NOT the separate submitter-dialog
      app, so searching ``dialog_app`` never finds it.
    * Its title ("Cinema4D job submission") is not exposed as the dialog's AX
      name on macOS -- the role is ``dialog`` with an empty name. The reliable
      anchor is the message body static_text, which starts with "Saved the
      submission as a job bundle".

    So we poll all apps for a dialog/window/sheet containing that body text and
    press its OK button. Best-effort and non-fatal: the bundle is already on
    disk and asserted separately. Polling (rather than one 5s blocking
    wait_visible that previously always timed out and left the popup up) makes
    this dismiss within a fraction of a second once the popup appears.
    """
    import time as _t

    log("dismissing success popup ('Saved the submission as a job bundle')")
    deadline_t = _t.monotonic() + 5.0
    while _t.monotonic() < deadline_t:
        try:
            for app in xa11y.App.list():
                ok = app.locator(
                    "dialog button[name='OK'], "
                    "window button[name='OK'], "
                    "sheet button[name='OK']"
                )
                # Only treat it as our popup if the success body text is present
                # in the same app, so we don't press an unrelated OK button.
                body = app.locator("static_text[name^='Saved the submission as a job bundle']")
                if body.exists() and ok.exists():
                    ok.press()
                    log("success popup dismissed (OK)")
                    return
        except Exception as e:
            log(f"success-popup scan raised (retrying): {e!r}")
        _t.sleep(0.25)
    log("success popup not found within 5s (non-fatal, bundle already exported)")


def _copy_bundle_files(staged_bundle: Path, dest: Path) -> None:
    """Copy the exported bundle files flat into `dest`."""
    log(f"copying bundle files {staged_bundle} -> {dest}")
    for src in staged_bundle.iterdir():
        if src.is_file():
            copy2(src, dest / src.name)
            log(f"  copied {src.name}")


def _drive_submitter_ui(proc: subprocess.Popen, history_dir: Path, screenshot_dest: Path) -> Path:
    """Drive the running submitter dialog via xa11y and return the exported
    bundle directory once it lands on disk.

    Waits for the dialog, lets queue-environment loading settle (the mock
    returns no queue environments, so there are no Conda parameter widgets to
    rebuild and thus no reload race), saves a screenshot of the dialog into
    `screenshot_dest`, presses Export bundle, then waits for the bundle to
    appear under `history_dir` before dismissing the success popup.
    """
    dialog_app = _resolve_dialog_app(proc)
    dialog = _wait_for_submitter_dialog(dialog_app)
    _wait_for_queue_environment_loading(dialog_app)
    # Record the fully-loaded dialog state just before Export, for inspection.
    _save_dialog_screenshot(dialog, dialog_app, screenshot_dest)
    _press_export_bundle(dialog, dialog_app)

    # Wait for the bundle to land on disk. This is the source of truth for
    # export success — more reliable than matching the QMessageBox success
    # popup's AX name across platforms.
    staged_bundle = wait_for_bundle(history_dir, timeout_s=_BUNDLE_EXPORT_TIMEOUT_S)

    _dismiss_success_popup()
    # Note: on Windows the submitter would normally open the bundle folder in
    # File Explorer (os.startfile); the sidecar plugin suppresses that in mock
    # mode, so there's no Explorer window to clean up here.
    return staged_bundle


def _export_job_bundle_via_submitter(
    cinema4d_location: Path,
    scene_path: Path,
    job_bundle_generated: Path,
    deadline_farm: dict,
) -> None:
    """Launch Cinema 4D, drive the real submitter UI to export a job bundle,
    and copy the bundle files flat into `job_bundle_generated`.

    The submitter exports via create_job_history_bundle_dir, which always
    writes under <history_dir>/<YYYY-mm>/<bundle-name>/. The history dir is set
    in the temp deadline config the `deadline_farm` fixture wrote (read inside
    the C4D subprocess), so the bundle lands under that dir; we then copy the
    bundle files flat into generated_bundle/ so asserts use the same layout as
    the existing render integ tests.

    Owns all cleanup: the C4D subprocess is always killed and its diagnostic
    log echoed before the staging dir is removed, even on failure.
    """
    cinema4d_gui_exe = resolve_c4d_exe(cinema4d_location, "Cinema 4D")

    history_dir = deadline_farm["job_history_dir"]
    bundle_staging = Path(tempfile.mkdtemp(prefix="c4d-submitter-ui-"))
    plugin_diag_log = bundle_staging / "plugin-diag.log"
    log(f"bundle staging dir: {bundle_staging}; job history dir: {history_dir}")
    try:
        env = _build_launch_env(scene_path, plugin_diag_log, deadline_farm["env_overlay"])
        proc = _launch_cinema4d(cinema4d_gui_exe, scene_path, env)
        try:
            staged_bundle = _drive_submitter_ui(proc, history_dir, job_bundle_generated)
            _copy_bundle_files(staged_bundle, job_bundle_generated)
        finally:
            kill_proc(proc)
            _dump_plugin_diag_log(plugin_diag_log)
    finally:
        rmtree(bundle_staging, ignore_errors=True)
        log(f"removed staging dir: {bundle_staging}")


@pytest.mark.parametrize("test_name", ["cube"])
def test_integ(
    cinema4d_location: Path,
    test_scenes_folder_location: Path,
    deadline_farm: dict,
    test_name: str,
) -> None:
    """
    Performs integration testing for Cinema 4D rendering, driven through
    the real submitter UI via xa11y.

    The body reads as the sequence of steps it performs; see each helper for
    the details. Two facts the call sequence doesn't make obvious: the
    test-only sidecar plugin auto-opens the real submitter once Cinema 4D
    finishes starting, and the openjd run + render compare is skipped on
    macOS (submitter-only coverage there).

    Args:
        cinema4d_location (Path): Path to the Cinema 4D installation directory
        test_scenes_folder_location (Path): Path to the root directory containing test scenes

    Raises:
        AssertionError: If any validation step fails, including:
            - Cinema 4D failing to launch
            - Submitter dialog not appearing in the UIA tree
            - Export bundle not producing the expected files
            - openjd check reporting a non-success status
            - generated bundle differing from expected_job_bundle/
            - openjd run failing for any step
    """
    test_scene_folder, job_bundle_generated = _prepare_generated_bundle_dir(
        test_scenes_folder_location, test_name
    )

    scene_path = _build_cinema4d_scene(
        cinema4d_location, test_scene_folder, job_bundle_generated, test_name
    )

    _export_job_bundle_via_submitter(
        cinema4d_location=cinema4d_location,
        scene_path=scene_path,
        job_bundle_generated=job_bundle_generated,
        deadline_farm=deadline_farm,
    )

    # The submitter ran against the mock backend, not real AWS. Prove its calls
    # reached our server and nothing hit an unmocked route. call_counts lives in
    # this process; the C4D subprocess populated it over HTTP.
    backend = deadline_farm["backend"]
    log(f"mock backend call_counts: {dict(backend.call_counts)}")
    assert (
        backend.unmatched_requests == []
    ), f"submitter hit routes the mock doesn't implement: {backend.unmatched_requests}"
    # GetQueueEnvironment is intentionally NOT expected: the mock returns an
    # empty queue-environment list (see list_queue_environments), so the
    # submitter never fetches an env template.
    for op in ("ListFarms", "GetFarm", "GetQueue", "ListQueueEnvironments"):
        assert (
            backend.call_counts.get(op, 0) >= 1
        ), f"expected the submitter to call {op}; saw {dict(backend.call_counts)}"

    assert_is_valid_job_bundle(job_bundle_generated / "template.yaml")

    # Compare against the platform-appropriate expected bundle (the _darwin
    # variant on macOS).
    suffix = "_darwin" if sys.platform == "darwin" else ""
    assert_expected_job_bundle_and_generated_job_bundle_are_equal(
        test_scene_folder / f"expected_job_bundle{suffix}", job_bundle_generated
    )

    # Run the bundle via openjd and compare rendered output. This adaptor
    # portion only runs on Windows; on macOS the test is submitter-only (the
    # render path needs Conda-managed cinema4d-openjd, which we don't ship for
    # darwin yet).
    if sys.platform != "darwin":
        assert_openjd_run_with_cinema4d_successful(
            cinema4d_location,
            job_bundle_generated / "template.yaml",
            job_bundle_generated / "parameter_values.yaml",
        )
        assert_all_images_close(
            test_scene_folder / "expected_job_output" / "renders",
            job_bundle_generated / "renders",
        )

    # Clean up if the test was successful
    rmtree(job_bundle_generated, ignore_errors=True)
